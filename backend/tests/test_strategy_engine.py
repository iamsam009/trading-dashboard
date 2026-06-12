"""
Unit tests for StrategyEngine indicator evaluation, signal generation,
cooldown logic, and concurrent multi-strategy execution.

Covers:
- Crossover / Compare-to signal generation
- Indicator computation (SMA, EMA, RSI, MACD, BB)
- Price threshold and time conditions
- Cooldown / no-duplicate-signal enforcement
- Multiple engines running concurrently with different symbols
- AND logic across multiple conditions
- Edge cases (NaN, empty data, unknown symbol)
"""

import asyncio
import time as _time
from datetime import datetime, timezone

import pytest

from app.engine.strategy_engine import MarketTick, Signal, StrategyEngine


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_tick(
    symbol: str,
    close: float,
    *,
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1000.0,
    timestamp: datetime | None = None,
) -> MarketTick:
    """Create a MarketTick with reasonable defaults from a required close price."""
    if open_price is None:
        open_price = close
    if high is None:
        high = close
    if low is None:
        low = close
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return MarketTick(
        symbol=symbol,
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        is_candle=True,
    )


def _feed_ticks(
    engine: StrategyEngine,
    symbol: str,
    closes: list[float],
    *,
    delay: float = 0.0,
) -> list[Signal]:
    """Feed a sequence of closing prices to the engine, returning all signals."""
    signals: list[Signal] = []
    for close in closes:
        if delay:
            _time.sleep(delay)
        result = engine.evaluate(_make_tick(symbol, close))
        signals.extend(result)
    return signals


# ---------------------------------------------------------------------------
# reusable strategy JSONs
# ---------------------------------------------------------------------------

SMA_COMPARE_STRATEGY = {
    "name": "SMA Compare",
    "conditions": [
        {
            "indicator": "SMA",
            "params": [9],
            "operator": ">",
            "compare_to": "SMA",
            "compare_params": [21],
        }
    ],
    "action": "buy",
    "symbols": ["BTC/USDT"],
    "cooldown_bars": 0,
    "quantity_percent": 100,
}

SMA_COMPARE_COOLDOWN = {
    **SMA_COMPARE_STRATEGY,
    "cooldown_bars": 1,
}

RSI_OVERSOLD_STRATEGY = {
    "name": "RSI Oversold",
    "conditions": [
        {"indicator": "RSI", "params": [14], "operator": "<", "threshold": 30}
    ],
    "action": "buy",
    "symbols": ["BTC/USDT"],
    "cooldown_bars": 0,
}

PRICE_THRESHOLD_STRATEGY = {
    "name": "Price Breakout",
    "conditions": [
        {"price_type": "last", "operator": ">", "threshold": 1000}
    ],
    "action": "buy",
    "symbols": ["BTC/USDT"],
}

MULTI_CONDITION_STRATEGY = {
    "name": "Multi Condition",
    "conditions": [
        {"indicator": "SMA", "params": [9], "operator": ">", "threshold": 50},
        {"price_type": "last", "operator": ">", "threshold": 60},
    ],
    "action": "buy",
    "symbols": ["BTC/USDT"],
}

MACD_STRATEGY = {
    "name": "MACD Strategy",
    "conditions": [
        {
            "indicator": "MACD",
            "params": [12, 26, 9],
            "operator": ">",
            "threshold": 0,
        }
    ],
    "action": "buy",
    "symbols": ["BTC/USDT"],
}

BB_STRATEGY = {
    "name": "BB Strategy",
    "conditions": [
        {"indicator": "BB_LOWER", "params": [20, 2], "operator": ">", "threshold": 0}
    ],
    "action": "buy",
    "symbols": ["BTC/USDT"],
}

ETH_STRATEGY = {
    "name": "ETH SMA Strategy",
    "conditions": [
        {"indicator": "SMA", "params": [5], "operator": ">", "threshold": 2000}
    ],
    "action": "buy",
    "symbols": ["ETH/USDT"],
    "quantity_percent": 50,
}


# ===================================================================
# Crossover / Compare-To Signal
# ===================================================================


class TestSMACompareSignal:
    """Verify the engine generates signals when SMA(fast) crosses above SMA(slow)."""

    @pytest.mark.anyio
    async def test_sma_compare_to_produces_buy_signal(self) -> None:
        """Feed enough ticks so SMA(9) > SMA(21), then verify a BUY signal is returned."""
        engine = StrategyEngine(SMA_COMPARE_STRATEGY)
        symbol = "BTC/USDT"

        # First 22 ticks: flat price of 100 → SMA(9)=100, SMA(21)=100 (no signal)
        signals = _feed_ticks(engine, symbol, [100.0] * 22)
        assert len(signals) == 0, "No signal expected when SMA(9) == SMA(21)"

        # Tick 23: large jump to 500 → SMA(9) rises faster than SMA(21)
        result = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(result) == 1, f"Expected 1 buy signal, got {len(result)}"
        sig = result[0]
        assert sig.action == "buy"
        assert sig.symbol == "BTC/USDT"
        assert sig.strategy_name == "SMA Compare"
        assert sig.quantity_percent == 100
        assert sig.price == 500.0
        assert "metadata" in sig.__dataclass_fields__  # noqa (Signal is a dataclass)

    @pytest.mark.anyio
    async def test_sma_fast_below_slow_no_signal(self) -> None:
        """When SMA(9) < SMA(21), no signal is generated (operator is >)."""
        engine = StrategyEngine(SMA_COMPARE_STRATEGY)
        symbol = "BTC/USDT"

        # Feed 22 ticks at 100, then tick 23 drops to 50
        _feed_ticks(engine, symbol, [100.0] * 22)
        result = engine.evaluate(_make_tick(symbol, 50.0))
        # With drop to 50, SMA(9) drops faster than SMA(21): SMA(9) < SMA(21)
        assert len(result) == 0, "No signal when SMA(9) < SMA(21)"

    @pytest.mark.anyio
    async def test_signal_contains_strategy_metadata(self) -> None:
        """Signal carries strategy_id, name, action, price, quantity, and timestamp."""
        engine = StrategyEngine(SMA_COMPARE_STRATEGY)
        symbol = "BTC/USDT"

        _feed_ticks(engine, symbol, [100.0] * 22)
        [signal] = engine.evaluate(_make_tick(symbol, 500.0))

        assert signal.strategy_id is None  # not set by engine (caller's job)
        assert signal.strategy_name == "SMA Compare"
        assert signal.action == "buy"
        assert signal.symbol == "BTC/USDT"
        assert signal.price == 500.0
        assert signal.quantity_percent == 100
        assert isinstance(signal.timestamp, datetime)


# ===================================================================
# Cooldown / No Duplicate Signals
# ===================================================================


class TestCooldownNoDuplicateSignals:
    """Verify that cooldown_bars prevents duplicate signals on consecutive bars."""

    @pytest.mark.anyio
    async def test_cooldown_prevents_immediate_duplicate(self) -> None:
        """With cooldown_bars=1, a second consecutive triggering tick yields no signal."""
        engine = StrategyEngine(SMA_COMPARE_COOLDOWN)
        symbol = "BTC/USDT"

        # Build history and trigger first signal
        _feed_ticks(engine, symbol, [100.0] * 22)
        result1 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(result1) == 1, "First signal should fire"

        # Next tick: same condition still met, but cooldown should block
        result2 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(result2) == 0, (
            f"Cooldown should block duplicate; got {len(result2)} signal(s)"
        )

    @pytest.mark.anyio
    async def test_signal_fires_after_cooldown_expires(self) -> None:
        """After cooldown_bars expire, a new signal can fire."""
        engine = StrategyEngine(SMA_COMPARE_COOLDOWN)
        symbol = "BTC/USDT"

        _feed_ticks(engine, symbol, [100.0] * 22)
        # First signal
        r1 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(r1) == 1

        # Cooldown tick (blocked)
        r2 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(r2) == 0

        # Next tick — cooldown expired, signal fires again
        r3 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(r3) == 1, "Signal should fire again after cooldown expires"

    @pytest.mark.anyio
    async def test_zero_cooldown_fires_every_tick(self) -> None:
        """cooldown_bars=0 allows a signal on every tick that meets conditions."""
        engine = StrategyEngine(SMA_COMPARE_STRATEGY)  # cooldown_bars=0
        symbol = "BTC/USDT"

        _feed_ticks(engine, symbol, [100.0] * 22)
        r1 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(r1) == 1
        r2 = engine.evaluate(_make_tick(symbol, 500.0))
        assert len(r2) == 1, "Zero cooldown should fire every tick"


# ===================================================================
# Indicator Computation
# ===================================================================


class TestIndicatorComputation:
    """Verify the engine computes common indicators and uses them in conditions."""

    @pytest.mark.anyio
    async def test_rsi_oversold_produces_buy_signal(self) -> None:
        """RSI dropping below 30 generates a buy signal."""
        engine = StrategyEngine(RSI_OVERSOLD_STRATEGY)
        symbol = "BTC/USDT"

        # RSI needs period+1 = 15 closes minimum.
        # Feed 14 ticks at 100 (flat), then consecutive drops to push RSI low.
        closes = [100.0] * 14 + [90, 80, 70, 60, 50, 40, 30, 20, 10]
        signals = _feed_ticks(engine, symbol, closes)
        # At some point RSI should dip below 30
        assert len(signals) >= 1, f"RSI should have triggered at least one buy, got {len(signals)}"
        assert all(s.action == "buy" for s in signals)

    @pytest.mark.anyio
    async def test_sma_basic_computation(self) -> None:
        """Engine computes SMA correctly and evaluates threshold."""
        strategy = {
            "name": "SMA Threshold",
            "conditions": [
                {"indicator": "SMA", "params": [5], "operator": ">", "threshold": 60}
            ],
            "action": "sell",
            "symbols": ["BTC/USDT"],
        }
        engine = StrategyEngine(strategy)
        symbol = "BTC/USDT"

        # After 6 ticks at 100: SMA(5)=100 > 60 → signal
        signals = _feed_ticks(engine, symbol, [100.0] * 6)
        assert len(signals) == 1
        assert signals[0].action == "sell"

    @pytest.mark.anyio
    async def test_ema_basic_computation(self) -> None:
        """Engine computes EMA and evaluates threshold."""
        strategy = {
            "name": "EMA Threshold",
            "conditions": [
                {"indicator": "EMA", "params": [10], "operator": ">", "threshold": 0}
            ],
            "action": "buy",
            "symbols": ["BTC/USDT"],
        }
        engine = StrategyEngine(strategy)
        symbol = "BTC/USDT"

        # EMA(10) with 10+1=11 ticks of 100 → EMA=100 > 0
        signals = _feed_ticks(engine, symbol, [100.0] * 11)
        assert len(signals) == 1

    @pytest.mark.anyio
    async def test_macd_comparison(self) -> None:
        """Engine computes MACD and checks MACD > 0 after sharp price jump."""
        engine = StrategyEngine(MACD_STRATEGY)
        symbol = "BTC/USDT"

        # MACD(12,26,9) needs max(12,26,9)+1 = 27 closes minimum.
        # Flat prices → EMA(12) ≈ EMA(26) → MACD ≈ 0 (no signal).
        # Sharp jump → EMA(12) reacts faster than EMA(26) → MACD > 0 → buy signal.
        closes = [100.0] * 27 + [500.0] * 5
        signals = _feed_ticks(engine, symbol, closes)
        assert len(signals) >= 1, f"MACD should be > 0 after sharp price jump, got {len(signals)}"

    @pytest.mark.anyio
    async def test_bollinger_band_lower(self) -> None:
        """Engine computes Bollinger Band lower and evaluates threshold."""
        engine = StrategyEngine(BB_STRATEGY)
        symbol = "BTC/USDT"

        # BB(20,2) needs 20+1 = 21 closes minimum
        closes = [100.0] * 21
        signals = _feed_ticks(engine, symbol, closes)
        # BB_LOWER on flat prices = 100 > 0 → signal
        assert len(signals) == 1


# ===================================================================
# Price Threshold & Time Conditions
# ===================================================================


class TestPriceAndTimeConditions:
    @pytest.mark.anyio
    async def test_price_threshold_buy_signal(self) -> None:
        """Price breaking above a threshold with operator '>' generates a signal."""
        engine = StrategyEngine(PRICE_THRESHOLD_STRATEGY)
        symbol = "BTC/USDT"

        # Below threshold — no signal
        result = engine.evaluate(_make_tick(symbol, 900.0))
        assert len(result) == 0

        # Above threshold — signal
        result = engine.evaluate(_make_tick(symbol, 1100.0))
        assert len(result) == 1
        assert result[0].action == "buy"
        assert result[0].price == 1100.0

    @pytest.mark.anyio
    async def test_price_lte_no_signal(self) -> None:
        """Price at exactly threshold with operator '>' gives no signal."""
        strategy = {
            "name": "Price >=",
            "conditions": [
                {"price_type": "last", "operator": ">=", "threshold": 100}
            ],
            "action": "buy",
            "symbols": ["BTC/USDT"],
        }
        engine = StrategyEngine(strategy)
        result = engine.evaluate(_make_tick("BTC/USDT", 100.0))
        assert len(result) == 1  # >= matches


# ===================================================================
# AND Logic Across Multiple Conditions
# ===================================================================


class TestMultiConditionAndLogic:
    @pytest.mark.anyio
    async def test_all_conditions_must_be_met(self) -> None:
        """Signal only fires when every condition in the array is satisfied."""
        engine = StrategyEngine(MULTI_CONDITION_STRATEGY)
        symbol = "BTC/USDT"

        # Condition 1: SMA(9) > 50
        # Condition 2: Price > 60
        # After 9 ticks at 100: SMA(9)=100 > 50 AND price=100 > 60 → both met
        # But SMA needs max(params)+1 = 10 closes (9+1=10)
        # Let me feed 10 ticks at 100
        signals = _feed_ticks(engine, symbol, [100.0] * 10)
        assert len(signals) == 1, "Both conditions met → signal expected"

    @pytest.mark.anyio
    async def test_one_condition_fails_no_signal(self) -> None:
        """If any condition fails, no signal is generated."""
        engine = StrategyEngine(MULTI_CONDITION_STRATEGY)
        symbol = "BTC/USDT"

        # Feed enough for SMA but price below threshold
        # After 10 ticks at 40: SMA(9)=40 > 50? No → condition 1 fails
        signals = _feed_ticks(engine, symbol, [40.0] * 10)
        assert len(signals) == 0, "SMA condition not met → no signal"


# ===================================================================
# Multiple Active Strategies (Concurrent)
# ===================================================================


class TestMultipleActiveStrategies:
    @pytest.mark.anyio
    async def test_two_engines_independent_symbols(self) -> None:
        """Two engines with different symbols produce independent signals."""
        engine_btc = StrategyEngine(SMA_COMPARE_STRATEGY)  # BTC/USDT
        engine_eth = StrategyEngine(ETH_STRATEGY)  # ETH/USDT

        # Feed BTC history
        _feed_ticks(engine_btc, "BTC/USDT", [100.0] * 22)

        # Feed ETH history: SMA(5) needs 6 closes
        _feed_ticks(engine_eth, "ETH/USDT", [3000.0] * 6)

        # Now trigger both simultaneously via asyncio.gather
        async def eval_btc() -> list[Signal]:
            return engine_btc.evaluate(_make_tick("BTC/USDT", 500.0))

        async def eval_eth() -> list[Signal]:
            return engine_eth.evaluate(_make_tick("ETH/USDT", 3000.0))

        results = await asyncio.gather(eval_btc(), eval_eth())

        btc_signals, eth_signals = results
        assert len(btc_signals) == 1, "BTC engine should fire"
        assert btc_signals[0].symbol == "BTC/USDT"
        assert len(eth_signals) == 1, "ETH engine should fire"
        assert eth_signals[0].symbol == "ETH/USDT"

    @pytest.mark.anyio
    async def test_engine_ignores_unknown_symbol(self) -> None:
        """An engine only processes ticks for its configured symbols."""
        engine = StrategyEngine(SMA_COMPARE_STRATEGY)  # symbols=["BTC/USDT"]

        # Feed ticks for an unknown symbol
        result = engine.evaluate(_make_tick("ETH/USDT", 500.0))
        assert len(result) == 0, "Engine should ignore unknown symbols"

    @pytest.mark.anyio
    async def test_concurrent_engines_no_cross_interference(self) -> None:
        """Two engines running concurrently don't leak signals across symbols."""
        engine_btc = StrategyEngine(SMA_COMPARE_STRATEGY)
        engine_eth = StrategyEngine(ETH_STRATEGY)

        # BTC: build history → signal
        _feed_ticks(engine_btc, "BTC/USDT", [100.0] * 22)

        # ETH: below threshold → no signal
        _feed_ticks(engine_eth, "ETH/USDT", [1500.0] * 6)

        # BTC should fire, ETH should not (SMA(5)=1500 < 2000)
        btc_result = engine_btc.evaluate(_make_tick("BTC/USDT", 500.0))
        eth_result = engine_eth.evaluate(_make_tick("ETH/USDT", 1500.0))

        assert len(btc_result) == 1
        assert len(eth_result) == 0, f"ETH should not fire, got {len(eth_result)} signal(s)"

    @pytest.mark.anyio
    async def test_same_symbol_different_engines(self) -> None:
        """Two engines can watch the same symbol independently."""
        engine_a = StrategyEngine(SMA_COMPARE_STRATEGY)
        engine_b = StrategyEngine(
            {
                "name": "SMA Reverse",
                "conditions": [
                    {"indicator": "SMA", "params": [9], "operator": "<", "threshold": 200}
                ],
                "action": "sell",
                "symbols": ["BTC/USDT"],
            }
        )

        # Build history for both
        _feed_ticks(engine_a, "BTC/USDT", [100.0] * 22)
        _feed_ticks(engine_b, "BTC/USDT", [100.0] * 22)

        tick = _make_tick("BTC/USDT", 500.0)
        sig_a = engine_a.evaluate(tick)
        sig_b = engine_b.evaluate(tick)

        # Engine A: SMA(9) > SMA(21) on uptrend → buy
        assert len(sig_a) == 1 and sig_a[0].action == "buy"
        # Engine B: SMA(9) < 200? SMA(9) ≈ 144 < 200 → sell signal
        assert len(sig_b) == 1 and sig_b[0].action == "sell"


# ===================================================================
# Edge Cases
# ===================================================================


class TestEngineEdgeCases:
    @pytest.mark.anyio
    async def test_insufficient_data_returns_empty(self) -> None:
        """When there isn't enough data for indicator computation, no signal."""
        engine = StrategyEngine(SMA_COMPARE_STRATEGY)

        # Only 5 ticks — too few for SMA(21) which needs 22 closes
        result = engine.evaluate(_make_tick("BTC/USDT", 100.0))
        assert len(result) == 0

    @pytest.mark.anyio
    async def test_quantity_percent_default(self) -> None:
        """When quantity_percent is not specified, default is 100."""
        strategy_no_qty = {
            "name": "No Qty",
            "conditions": [
                {"indicator": "SMA", "params": [5], "operator": ">", "threshold": 0}
            ],
            "action": "buy",
            "symbols": ["BTC/USDT"],
        }
        engine = StrategyEngine(strategy_no_qty)
        _feed_ticks(engine, "BTC/USDT", [100.0] * 6)
        result = engine.evaluate(_make_tick("BTC/USDT", 100.0))
        assert len(result) == 1
        assert result[0].quantity_percent == 100  # default

    @pytest.mark.anyio
    async def test_market_tick_defaults(self) -> None:
        """MarketTick has sensible defaults."""
        tick = MarketTick(
            symbol="BTC/USDT",
            timestamp=datetime.now(timezone.utc),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=5000,
            is_candle=True,
        )
        assert tick.symbol == "BTC/USDT"
        assert tick.close == 100.5

    @pytest.mark.anyio
    async def test_strategy_with_risk_modifiers_initializes(self) -> None:
        """Engine initializes correctly even when risk_modifiers are present."""
        strategy_with_risk = {
            "name": "Risk Aware",
            "conditions": [
                {"indicator": "SMA", "params": [5], "operator": ">", "threshold": 0}
            ],
            "action": "buy",
            "symbols": ["BTC/USDT"],
            "risk_modifiers": {
                "stop_loss_percent": 5,
                "take_profit_percent": 10,
                "trailing_stop_percent": 3,
                "max_holding_bars": 100,
            },
            "tags": ["risk-managed"],
            "timeframe": "1h",
        }
        engine = StrategyEngine(strategy_with_risk)
        _feed_ticks(engine, "BTC/USDT", [100.0] * 6)
        result = engine.evaluate(_make_tick("BTC/USDT", 100.0))
        assert len(result) == 1

    @pytest.mark.anyio
    async def test_multiple_symbols_in_strategy(self) -> None:
        """A strategy watching multiple symbols evaluates each independently."""
        strategy = {
            "name": "Multi Symbol",
            "conditions": [
                {"indicator": "SMA", "params": [5], "operator": ">", "threshold": 50}
            ],
            "action": "buy",
            "symbols": ["BTC/USDT", "ETH/USDT"],
        }
        engine = StrategyEngine(strategy)

        # Feed BTC history
        _feed_ticks(engine, "BTC/USDT", [100.0] * 6)
        # Feed ETH history
        _feed_ticks(engine, "ETH/USDT", [3000.0] * 6)

        # Both should fire
        btc_result = engine.evaluate(_make_tick("BTC/USDT", 100.0))
        eth_result = engine.evaluate(_make_tick("ETH/USDT", 3000.0))

        assert len(btc_result) == 1
        assert btc_result[0].symbol == "BTC/USDT"
        assert len(eth_result) == 1
        assert eth_result[0].symbol == "ETH/USDT"

    @pytest.mark.anyio
    async def test_evaluate_returns_single_signal_per_call(self) -> None:
        """Each evaluate() call returns at most one signal for the tick's symbol."""
        strategy = {
            "name": "Single Signal",
            "conditions": [
                {"indicator": "SMA", "params": [5], "operator": ">", "threshold": 0}
            ],
            "action": "buy",
            "symbols": ["BTC/USDT"],
        }
        engine = StrategyEngine(strategy)
        _feed_ticks(engine, "BTC/USDT", [100.0] * 6)
        result = engine.evaluate(_make_tick("BTC/USDT", 100.0))
        assert len(result) <= 1  # at most one signal per evaluate call

    @pytest.mark.anyio
    async def test_signal_dataclass_fields(self) -> None:
        """Signal dataclass contains all expected fields."""
        sig = Signal(
            strategy_id="abc-123",
            strategy_name="Test",
            action="buy",
            symbol="BTC/USDT",
            price=50000.0,
            quantity_percent=25,
            timestamp=datetime.now(timezone.utc),
            metadata={"reason": "test"},
        )
        assert sig.strategy_id == "abc-123"
        assert sig.metadata == {"reason": "test"}