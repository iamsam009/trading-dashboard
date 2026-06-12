"""
Strategy Engine – evaluates a strategy JSON definition against live market data
and generates trading signals.

Each instance of ``StrategyEngine`` is bound to a single strategy definition.
Multiple engines (one per active strategy per user) can run concurrently as
asyncio tasks, each subscribing to the same market data feed.

Architecture
------------
::

    MarketFeed (WebSocket/Redis pub-sub)
        │
        ├──► StrategyEngine A (user 1, strat "EMA Cross")  →  signals
        ├──► StrategyEngine B (user 1, strat "RSI Div")    →  signals
        └──► StrategyEngine C (user 2, strat "BB Break")   →  signals

Each engine receives a ``MarketTick`` (or OHLCV candle) and evaluates all
conditions defined in the strategy JSON.  When all conditions are satisfied,
it emits a ``Signal`` (action, symbol, quantity, metadata).

Usage
-----
::

    import asyncio
    from app.engine.strategy_engine import StrategyEngine, Signal

    async def run_strategy(strategy_json: dict, feed: MarketFeed):
        engine = StrategyEngine(strategy_json)
        async for tick in feed.subscribe(symbols=["BTC/USDT"]):
            signals = engine.evaluate(tick)
            for sig in signals:
                await execute_signal(sig)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from app.engine.indicators import (
    _INDICATOR_REGISTRY,
    atr,
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
    vwap,
)

# ── Data structures ─────────────────────────────────────────────────────────


@dataclass
class MarketTick:
    """A single market update – either a tick or a closed candle."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_candle: bool = False  # True for closed OHLCV candle, False for real-time tick


@dataclass
class Signal:
    """Trading signal emitted by the strategy engine."""

    strategy_id: int | None  # DB strategy ID, if persisted
    strategy_name: str
    action: str  # buy, sell, close, close_long, close_short
    symbol: str
    price: float
    quantity_percent: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Engine ──────────────────────────────────────────────────────────────────


class StrategyEngine:
    """Evaluate a strategy definition against live market data.

    Maintains a rolling window of OHLCV data per symbol and computes
    technical indicators on-demand.  Thread-safe for a single consumer
    (the asyncio task that owns the engine).
    """

    # Maximum number of candles to keep in the rolling window per symbol.
    _MAX_CANDLES: int = 500

    def __init__(self, strategy_json: dict[str, Any]) -> None:
        self._definition = strategy_json
        self._name: str = strategy_json.get("name", "Unnamed Strategy")
        self._action: str = strategy_json["action"]
        self._quantity_percent: float = strategy_json.get("quantity_percent", 100.0)
        self._symbols: list[str] = strategy_json.get("symbols", [])
        self._conditions: list[dict[str, Any]] = strategy_json.get("conditions", [])
        self._cooldown_bars: int = strategy_json.get("cooldown_bars", 0)

        # Rolling OHLCV windows per symbol
        self._ohlcv: dict[str, _OHLCVWindow] = {
            s: _OHLCVWindow(self._MAX_CANDLES) for s in self._symbols
        }

        # Cooldown counter per symbol (bars since last signal)
        self._cooldown_counters: dict[str, int] = {s: 0 for s in self._symbols}

        # Cached indicator values to avoid recomputation
        self._indicator_cache: dict[str, Any] = {}

    # ── Public API ──────────────────────────────────────────────────────

    def evaluate(self, tick: MarketTick) -> list[Signal]:
        """Evaluate the strategy against a new market tick.

        Returns:
            List of zero or more trading signals.  Multiple signals can be
            emitted in a single evaluation (e.g., close existing + open new).
        """
        # Update rolling window
        window = self._ohlcv.get(tick.symbol)
        if window is None:
            return []  # Not tracking this symbol

        window.append(tick)

        # Increment cooldown counters for all symbols
        for sym in self._cooldown_counters:
            self._cooldown_counters[sym] += 1

        # Clear indicator cache (new data invalidates old computations)
        self._indicator_cache.clear()

        # Skip if still in cooldown
        if self._cooldown_counters.get(tick.symbol, 0) <= self._cooldown_bars:
            return []

        # Evaluate all conditions
        if not self._evaluate_all_conditions(tick.symbol):
            return []

        # Reset cooldown for this symbol
        self._cooldown_counters[tick.symbol] = 0

        return [
            Signal(
                strategy_id=None,
                strategy_name=self._name,
                action=self._action,
                symbol=tick.symbol,
                price=tick.close,
                quantity_percent=self._quantity_percent,
                metadata={
                    "trigger_condition": "all_conditions_met",
                    "tick_timestamp": tick.timestamp.isoformat(),
                },
            )
        ]

    # ── Condition evaluation ────────────────────────────────────────────

    def _evaluate_all_conditions(self, symbol: str) -> bool:
        """Return True only if ALL conditions are satisfied."""
        window = self._ohlcv.get(symbol)
        if window is None:
            return False

        closes = window.close
        highs = window.high
        lows = window.low
        volumes = window.volume

        for condition in self._conditions:
            if not self._evaluate_single_condition(condition, closes, highs, lows, volumes):
                return False
        return True

    def _evaluate_single_condition(
        self,
        condition: dict[str, Any],
        closes: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
        volumes: Sequence[float],
    ) -> bool:
        # ── Indicator conditions ──
        if "indicator" in condition:
            return self._evaluate_indicator_condition(
                condition, closes, highs, lows, volumes
            )

        # ── Price threshold conditions ──
        if "price_type" in condition:
            return self._evaluate_price_condition(condition, closes, highs, lows)

        # ── Time conditions ──
        if "metric" in condition:
            return self._evaluate_time_condition(condition)

        return False

    def _evaluate_indicator_condition(
        self,
        cond: dict[str, Any],
        closes: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
        volumes: Sequence[float],
    ) -> bool:
        indicator: str = cond["indicator"]
        params: list[int] = cond.get("params", [])

        # Compute the primary indicator value
        primary_value = self._compute_indicator(indicator, params, closes, highs, lows, volumes)
        if primary_value is None:
            return False

        # crossover / crossunder
        if cond.get("crossover"):
            # Need two series (fast, slow) and check if fast crosses above slow
            return self._check_crossover(indicator, params, closes, highs, lows, volumes, direction="above")

        if cond.get("crossunder"):
            return self._check_crossover(indicator, params, closes, highs, lows, volumes, direction="below")

        # Compare to threshold
        if "threshold" in cond:
            return self._compare(primary_value, cond["operator"], cond["threshold"])

        # Compare to another indicator or price
        if "compare_to" in cond:
            compare_to: str = cond["compare_to"]
            cmp_params = cond.get("compare_params", [])
            if compare_to == "price":
                cmp_value = closes[-1] if closes else None
            else:
                cmp_value = self._compute_indicator(
                    compare_to, cmp_params, closes, highs, lows, volumes
                )
            if cmp_value is None:
                return False
            return self._compare(primary_value, cond.get("operator", ">"), cmp_value)

        return False

    def _evaluate_price_condition(
        self,
        cond: dict[str, Any],
        closes: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
    ) -> bool:
        price_type = cond.get("price_type", "last")
        operator = cond["operator"]
        threshold = cond["threshold"]

        if price_type == "last" and closes:
            price = closes[-1]
        elif price_type == "bid" and lows:
            price = lows[-1]  # Bid ≈ low in OHLCV
        elif price_type == "ask" and highs:
            price = highs[-1]  # Ask ≈ high in OHLCV
        elif price_type == "mark" and closes:
            price = closes[-1]  # Mark ≈ last price in absence of real mark
        else:
            return False

        return self._compare(price, operator, threshold)

    def _evaluate_time_condition(self, cond: dict[str, Any]) -> bool:
        # Time conditions are relative to position state, not candle data.
        # They require external state (position open time) to evaluate.
        # For now, pass-through – engine returns True and lets the caller
        # handle time-based exit logic.
        return True  # pragma: no cover – requires position state

    # ── Indicator computation ───────────────────────────────────────────

    def _compute_indicator(
        self,
        name: str,
        params: list[int],
        closes: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
        volumes: Sequence[float],
    ) -> float | None:
        """Compute the latest value of a named indicator. Returns None if insufficient data."""
        cache_key = f"{name}:{tuple(params)}"
        if cache_key in self._indicator_cache:
            return self._indicator_cache[cache_key]

        if len(closes) < max(params, default=1) + 1:
            return None

        value: float | None = None

        if name == "SMA":
            result = sma(closes, params[0])
            value = result[-1] if not _isnan(result[-1]) else None
        elif name == "EMA":
            result = ema(closes, params[0])
            value = result[-1] if not _isnan(result[-1]) else None
        elif name == "RSI":
            result = rsi(closes, params[0])
            value = result[-1] if not _isnan(result[-1]) else None
        elif name == "MACD":
            macd_line, _, _ = macd(closes, params[0], params[1], params[2])
            value = macd_line[-1] if not _isnan(macd_line[-1]) else None
        elif name == "MACD_SIGNAL":
            _, signal_line, _ = macd(closes, params[0], params[1], params[2])
            value = signal_line[-1] if not _isnan(signal_line[-1]) else None
        elif name == "MACD_HIST":
            _, _, hist = macd(closes, params[0], params[1], params[2])
            value = hist[-1] if not _isnan(hist[-1]) else None
        elif name == "BB_UPPER":
            upper, _, _ = bollinger_bands(closes, params[0], params[1])
            value = upper[-1] if not _isnan(upper[-1]) else None
        elif name == "BB_MIDDLE":
            _, middle, _ = bollinger_bands(closes, params[0], params[1])
            value = middle[-1] if not _isnan(middle[-1]) else None
        elif name == "BB_LOWER":
            _, _, lower = bollinger_bands(closes, params[0], params[1])
            value = lower[-1] if not _isnan(lower[-1]) else None
        elif name == "ATR":
            result = atr(highs, lows, closes, params[0])
            value = result[-1] if not _isnan(result[-1]) else None
        elif name == "VWAP":
            result = vwap(highs, lows, closes, volumes)
            value = result[-1] if not _isnan(result[-1]) else None
        elif name == "VOLUME":
            value = volumes[-1] if volumes else None

        if value is not None:
            self._indicator_cache[cache_key] = value
        return value

    def _check_crossover(
        self,
        indicator: str,
        params: list[int],
        closes: Sequence[float],
        highs: Sequence[float],
        lows: Sequence[float],
        volumes: Sequence[float],
        direction: str,
    ) -> bool:
        """Check if fast line crosses above/below slow line.

        For indicator conditions with two params: fast period = params[0], slow = params[1].
        """
        if len(params) != 2:
            return False

        # Compute fast and slow lines
        fast = self._compute_indicator(indicator, [params[0]], closes, highs, lows, volumes)
        slow = self._compute_indicator(indicator, [params[1]], closes, highs, lows, volumes)

        if fast is None or slow is None:
            return False

        # Compute previous values
        # We need to check the previous bar's values too
        if len(closes) < 3:
            return False

        prev_closes = closes[:-1]
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        prev_volumes = volumes[:-1]

        prev_fast = self._compute_indicator(indicator, [params[0]], prev_closes, prev_highs, prev_lows, prev_volumes)
        prev_slow = self._compute_indicator(indicator, [params[1]], prev_closes, prev_highs, prev_lows, prev_volumes)

        if prev_fast is None or prev_slow is None:
            return False

        if direction == "above":
            return prev_fast <= prev_slow and fast > slow
        else:  # "below"
            return prev_fast >= prev_slow and fast < slow

    @staticmethod
    def _compare(a: float, op: str, b: float) -> bool:
        if op == ">":
            return a > b
        if op == ">=":
            return a >= b
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == "==":
            return abs(a - b) < 1e-9
        if op == "!=":
            return abs(a - b) >= 1e-9
        return False


# ── OHLCV rolling window ────────────────────────────────────────────────────


class _OHLCVWindow:
    """Fixed-size rolling window of OHLCV data for a single symbol."""

    __slots__ = ("open", "high", "low", "close", "volume", "_max_size")

    def __init__(self, max_size: int = 500) -> None:
        self._max_size = max_size
        self.open: list[float] = []
        self.high: list[float] = []
        self.low: list[float] = []
        self.close: list[float] = []
        self.volume: list[float] = []

    def append(self, tick: MarketTick) -> None:
        """Append a tick/candle, evicting the oldest if over capacity."""
        self.open.append(tick.open)
        self.high.append(tick.high)
        self.low.append(tick.low)
        self.close.append(tick.close)
        self.volume.append(tick.volume)

        if len(self.open) > self._max_size:
            self.open.pop(0)
            self.high.pop(0)
            self.low.pop(0)
            self.close.pop(0)
            self.volume.pop(0)

    def __len__(self) -> int:
        return len(self.open)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _isnan(value: float) -> bool:
    """Check for NaN without importing math at module level."""
    return value != value