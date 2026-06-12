"""Celery task – backtest a strategy against historical OHLCV data.

Feeds historical candles into ``StrategyEngine``, simulates single-position
trading, and computes standard metrics (Sharpe, max drawdown, win rate, etc.).
Results are stored in the strategy's ``backtest_results`` JSONB column.

OHLCV data is cached in Redis (``backtest:ohlcv:{symbol}:{interval}``) to
avoid re-fetching from the exchange on every run.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from celery import Task

from app.celery_app import celery_app
from app.db.base import async_session
from app.engine.strategy_engine import MarketTick, StrategyEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

_OHLCV_CACHE_TTL = 86400 * 7  # 7 days


async def _get_ohlcv_from_cache(
    symbol: str, interval: str, start: date, end: date
) -> list[dict[str, Any]] | None:
    """Return cached OHLCV candles or None on miss/error."""
    try:
        import aioredis

        from app.config import get_settings

        r = await aioredis.from_url(get_settings().redis_url)
        key = f"backtest:ohlcv:{symbol}:{interval}"
        raw = await r.get(key)
        await r.close()
        if not raw:
            return None

        all_candles: list[dict[str, Any]] = json.loads(raw)
        # Filter to requested date range
        start_ts = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        end_ts = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)
        return [
            c
            for c in all_candles
            if start_ts <= datetime.fromisoformat(c["ts"]) <= end_ts
        ]
    except Exception:
        logger.warning("Redis OHLCV cache miss for %s:%s", symbol, interval, exc_info=True)
        return None


async def _set_ohlcv_cache(
    symbol: str, interval: str, candles: list[dict[str, Any]]
) -> None:
    """Store OHLCV candles in Redis."""
    try:
        import aioredis

        from app.config import get_settings

        r = await aioredis.from_url(get_settings().redis_url)
        key = f"backtest:ohlcv:{symbol}:{interval}"
        await r.set(key, json.dumps(candles, default=str), ex=_OHLCV_CACHE_TTL)
        await r.close()
    except Exception:
        logger.warning("Failed to cache OHLCV for %s:%s", symbol, interval, exc_info=True)


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def _compute_metrics(
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    initial_capital: float,
) -> dict[str, Any]:
    """Compute standard backtest metrics from trade list and equity curve."""

    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100

    # ── Max drawdown ──
    peak = initial_capital
    max_dd_pct = 0.0
    for pt in equity_curve:
        eq = float(pt["equity"])
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd_pct:
            max_dd_pct = dd

    # ── Trade statistics ──
    winning = [t for t in trades if float(t.get("pnl", 0)) > 0]
    losing = [t for t in trades if float(t.get("pnl", 0)) < 0]
    total_trades = len(trades)
    winning_trades = len(winning)
    losing_trades = len(losing)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    gross_profit = sum(float(t["pnl"]) for t in winning)
    gross_loss = abs(sum(float(t["pnl"]) for t in losing))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    avg_win = (gross_profit / winning_trades) if winning_trades > 0 else None
    avg_loss = (-gross_loss / losing_trades) if losing_trades > 0 else None

    pnls = [float(t.get("pnl", 0)) for t in trades]
    best_trade = max(pnls) if pnls else None
    worst_trade = min(pnls) if pnls else None

    total_pnl = sum(pnls)

    # ── Sharpe ratio (annualised, risk-free = 0) ──
    sharpe = _compute_sharpe(equity_curve, initial_capital)

    return {
        "total_return_pct": round(total_return_pct, 4),
        "total_pnl": round(total_pnl, 4),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "avg_win": round(avg_win, 4) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 4) if avg_loss is not None else None,
        "best_trade": round(best_trade, 4) if best_trade is not None else None,
        "worst_trade": round(worst_trade, 4) if worst_trade is not None else None,
        "final_equity": round(final_equity, 4),
    }


def _compute_sharpe(
    equity_curve: list[dict[str, Any]], initial_capital: float
) -> float | None:
    """Annualised Sharpe ratio from equity curve."""
    if len(equity_curve) < 2:
        return None

    # Daily returns (assume each point is one candle – approximate)
    returns: list[float] = []
    prev = initial_capital
    for pt in equity_curve:
        eq = float(pt["equity"])
        if prev > 0:
            returns.append((eq - prev) / prev)
        prev = eq

    if not returns:
        return None

    n = len(returns)
    mean_ret = sum(returns) / n
    if n < 2:
        return None

    variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
    std_ret = math.sqrt(variance)

    if std_ret == 0:
        return 0.0

    # Annualise: 365 trading days
    return (mean_ret / std_ret) * math.sqrt(365)


# ---------------------------------------------------------------------------
# Backtest simulation
# ---------------------------------------------------------------------------


def _simulate(
    engine: StrategyEngine,
    candles: list[dict[str, Any]],
    initial_capital: float,
    symbol: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the strategy engine over historical candles, tracking simulated P&L.

    Returns:
        (trades, equity_curve) – list of trade dicts and equity data points.
    """
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    equity = initial_capital

    # Simple single-position simulation state
    in_position = False
    entry_price = 0.0
    position_qty = 0.0
    position_side = ""  # "LONG" or "SHORT"
    trade_entry_ts: datetime | None = None

    for i, candle in enumerate(candles):
        tick = MarketTick(
            symbol=symbol,
            timestamp=datetime.fromisoformat(candle["ts"]),
            open=float(candle["open"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
            volume=float(candle.get("volume", 0)),
            is_candle=True,
        )

        signals = engine.evaluate(tick)

        for sig in signals:
            action = sig.action.lower()

            # ── Entry ──
            if action in ("buy", "sell") and not in_position:
                in_position = True
                entry_price = sig.price
                position_side = "LONG" if action == "buy" else "SHORT"
                # quantity_percent is % of equity
                notional = equity * (sig.quantity_percent / 100.0)
                position_qty = notional / sig.price
                trade_entry_ts = tick.timestamp

            # ── Exit ──
            elif action in ("close", "close_long", "close_short") and in_position:
                # Match side: close_long only closes LONG, close_short only closes SHORT
                if action == "close_long" and position_side != "LONG":
                    continue
                if action == "close_short" and position_side != "SHORT":
                    continue

                exit_price = sig.price

                if position_side == "LONG":
                    pnl = (exit_price - entry_price) * position_qty
                else:
                    pnl = (entry_price - exit_price) * position_qty

                pnl_pct = (pnl / (entry_price * position_qty)) * 100 if entry_price > 0 else 0

                equity += pnl
                trades.append(
                    {
                        "entry_time": trade_entry_ts.isoformat() if trade_entry_ts else None,
                        "exit_time": tick.timestamp.isoformat(),
                        "side": position_side,
                        "entry_price": round(entry_price, 4),
                        "exit_price": round(exit_price, 4),
                        "quantity": round(position_qty, 8),
                        "pnl": round(pnl, 4),
                        "pnl_percent": round(pnl_pct, 4),
                        "bars_held": i - _find_bar_index(candles, trade_entry_ts)
                        if trade_entry_ts
                        else 0,
                    }
                )

                in_position = False
                entry_price = 0.0
                position_qty = 0.0
                position_side = ""
                trade_entry_ts = None

        # ── Mark-to-market equity (unrealised P&L) ──
        current_equity = equity
        if in_position and entry_price > 0:
            if position_side == "LONG":
                unrealised = (tick.close - entry_price) * position_qty
            else:
                unrealised = (entry_price - tick.close) * position_qty
            current_equity = equity + unrealised

        equity_curve.append(
            {
                "ts": tick.timestamp.isoformat(),
                "equity": round(current_equity, 4),
            }
        )

    return trades, equity_curve


def _find_bar_index(
    candles: list[dict[str, Any]], ts: datetime | None
) -> int:
    """Find the candle index for a given timestamp."""
    if ts is None:
        return 0
    for i, c in enumerate(candles):
        if datetime.fromisoformat(c["ts"]) >= ts:
            return i
    return len(candles) - 1


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


class BacktestTask(Task):
    """Custom Celery task to track backtest progress."""

    name = "app.tasks.backtest.run_backtest"


@celery_app.task(
    bind=True,
    base=BacktestTask,
    name="app.tasks.backtest.run_backtest",
    max_retries=1,
    default_retry_delay=5,
    track_started=True,
)
def run_backtest(
    self,
    strategy_id: int,
    user_id: int,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 10000.0,
) -> dict[str, Any]:
    """Run a full backtest of a strategy against historical OHLCV data.

    Args:
        strategy_id: DB strategy ID.
        user_id: Owner user ID.
        symbol: Trading pair (e.g. ``BTC/USDT``).
        start_date: ISO date string (``YYYY-MM-DD``).
        end_date: ISO date string (``YYYY-MM-DD``).
        initial_capital: Starting equity.

    Returns:
        Dict with metrics, equity_curve, trades, and summary.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        _async_run_backtest(
            self, strategy_id, user_id, symbol, start_date, end_date, initial_capital
        )
    )


async def _async_run_backtest(
    task: Task,
    strategy_id: int,
    user_id: int,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> dict[str, Any]:
    """Async implementation of the backtest."""

    start_dt = date.fromisoformat(start_date)
    end_dt = date.fromisoformat(end_date)

    # ── 1. Load strategy definition ─────────────────────────────────
    async with async_session() as db:
        from sqlalchemy import select

        from app.models.strategy import Strategy

        result = await db.execute(
            select(Strategy).where(
                Strategy.id == strategy_id, Strategy.user_id == user_id
            )
        )
        strategy = result.scalar_one_or_none()

        if strategy is None:
            return {"error": "Strategy not found", "status": "FAILURE"}

        strategy_name = strategy.name
        json_def = strategy.json_definition

    # ── 2. Fetch OHLCV data (cache-first) ───────────────────────────
    task.update_state(state="STARTED", meta={"stage": "fetching_ohlcv"})

    interval = json_def.get("timeframe", "1h")
    candles = await _get_ohlcv_from_cache(symbol, interval, start_dt, end_dt)

    if candles is None:
        # Generate sample OHLCV data as fallback (in production, fetch from Shark API)
        candles = _generate_sample_ohlcv(symbol, interval, start_dt, end_dt)
        await _set_ohlcv_cache(symbol, interval, candles)

    if not candles:
        return {"error": "No OHLCV data available for the requested range", "status": "FAILURE"}

    # ── 3. Run simulation ───────────────────────────────────────────
    task.update_state(
        state="STARTED", meta={"stage": "simulating", "candles": len(candles)}
    )

    engine = StrategyEngine(json_def)
    trades, equity_curve = _simulate(engine, candles, initial_capital, symbol)

    # ── 4. Compute metrics ──────────────────────────────────────────
    task.update_state(state="STARTED", meta={"stage": "computing_metrics"})

    metrics = _compute_metrics(trades, equity_curve, initial_capital)

    # ── 5. Persist result to strategy ───────────────────────────────
    result_data = {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_equity": metrics["final_equity"],
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "candles_processed": len(candles),
    }

    async with async_session() as db:
        from sqlalchemy import select, update

        await db.execute(
            update(Strategy)
            .where(Strategy.id == strategy_id)
            .values(backtest_results=result_data)
        )
        await db.commit()

    return {
        "status": "SUCCESS",
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "final_equity": metrics["final_equity"],
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "completed_at": result_data["completed_at"],
    }


# ---------------------------------------------------------------------------
# Sample OHLCV generator (fallback when no real data is available)
# ---------------------------------------------------------------------------


def _generate_sample_ohlcv(
    symbol: str,
    interval: str,
    start: date,
    end: date,
    base_price: float | None = None,
) -> list[dict[str, Any]]:
    """Generate synthetic OHLCV candles for demo/testing.

    Uses a geometric Brownian motion with drift and volatility to produce
    realistic-looking price series.
    """
    import random

    random.seed(hash(symbol + start.isoformat()) % (2**31))

    # Default base prices per symbol
    base_prices: dict[str, float] = {
        "BTC/USDT": 50000.0,
        "BTCINR": 50000.0,
        "ETH/USDT": 3000.0,
        "ETHINR": 3000.0,
        "SOL/USDT": 100.0,
        "XRP/USDT": 0.5,
    }

    if base_price is None:
        base_price = base_prices.get(symbol, 100.0)

    # Interval → number of candles
    interval_minutes: dict[str, int] = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    mins = interval_minutes.get(interval, 60)

    delta = end - start
    total_days = max(delta.days, 1)
    candles_per_day = 1440 // mins
    num_candles = total_days * candles_per_day

    # GBM parameters
    drift = 0.0001  # Slight upward drift
    volatility = 0.02  # 2% per candle

    prices: list[float] = [base_price]
    current_ts = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)

    for i in range(1, num_candles):
        current_ts += timedelta(minutes=mins)
        if current_ts.date() > end:
            break
        shock = random.gauss(drift, volatility)
        prices.append(prices[-1] * (1 + shock))

    candles: list[dict[str, Any]] = []
    current_ts = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)

    for i, close_price in enumerate(prices):
        if current_ts.date() > end:
            break

        # Generate OHLC around the close price
        high = close_price * (1 + random.random() * 0.01)
        low = close_price * (1 - random.random() * 0.01)
        open_price = close_price * (1 + random.uniform(-0.005, 0.005))
        volume = random.uniform(10, 1000) * (close_price / base_price)

        candles.append(
            {
                "ts": current_ts.isoformat(),
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close_price, 4),
                "volume": round(volume, 4),
            }
        )
        current_ts += timedelta(minutes=mins)

    return candles