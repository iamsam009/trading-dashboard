"""Celery task – daily performance reports.

Aggregates all trades from the *previous* UTC day for every user, computes
standard performance metrics (PnL, win rate, profit factor, Sharpe ratio,
max drawdown), and upserts a row into ``performance_stats``.

Also rebuilds the equity curve from the user's trade history and stores it
as JSONB alongside the daily snapshot.

Scheduled via Celery Beat (runs every day at 00:05 UTC).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from celery import Task
from sqlalchemy import and_, func, select, text

from app.celery_app import celery_app
from app.db.base import async_session
from app.models.performance import Performance
from app.models.trade import Trade
from app.models.user import User

logger = logging.getLogger(__name__)


class DailyReportTask(Task):
    name = "app.tasks.reports.daily_performance_report"


async def _aggregate_user_trades(
    user_id: int, report_date: date
) -> dict[str, Any]:
    """Compute daily PnL, win rate, profit factor for a single user."""
    start_dt = datetime.combine(report_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    async with async_session() as db:
        # Fetch all filled trades for the user on the report date
        stmt = select(Trade).where(
            and_(
                Trade.user_id == user_id,
                Trade.status == "FILLED",
                Trade.closed_at >= start_dt,
                Trade.closed_at < end_dt,
            )
        )
        result = await db.execute(stmt)
        trades: list[Trade] = list(result.scalars().all())

    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_pnl": Decimal("0"),
            "total_pnl_percent": Decimal("0"),
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "sharpe_ratio": None,
            "max_drawdown_percent": None,
            "total_fees": Decimal("0"),
            "equity_curve": [],
        }

    total_pnl = Decimal("0")
    total_fees = Decimal("0")
    winning_trades = 0
    losing_trades = 0
    gross_profit = Decimal("0")
    gross_loss = Decimal("0")

    for t in trades:
        pnl = t.pnl or Decimal("0")
        fees = t.fees or Decimal("0")
        total_pnl += pnl
        total_fees += fees
        if pnl > 0:
            winning_trades += 1
            gross_profit += pnl
        elif pnl < 0:
            losing_trades += 1
            gross_loss += abs(pnl)

    win_rate = (Decimal(winning_trades) / Decimal(total_trades)) if total_trades > 0 else None
    profit_factor = (
        (gross_profit / gross_loss) if gross_loss > 0 else None
    )

    # Build equity curve from trades sorted by closed_at
    sorted_trades = sorted(
        [t for t in trades if t.closed_at is not None],
        key=lambda t: t.closed_at,  # type: ignore[arg-type]
    )
    equity_curve: list[dict[str, Any]] = []
    running_equity = Decimal("10000")  # default starting equity

    for t in sorted_trades:
        running_equity += (t.pnl or Decimal("0"))
        equity_curve.append({
            "ts": t.closed_at.isoformat(),
            "equity": float(running_equity),
        })

    # Sharpe: daily return stddev annualised (simplified)
    sharpe_ratio = None
    if len(equity_curve) >= 2:
        returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["equity"]
            curr = equity_curve[i]["equity"]
            if prev != 0:
                returns.append((curr - prev) / prev)
        if returns:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            std_ret = variance ** 0.5
            if std_ret > 0:
                sharpe_ratio = (mean_ret / std_ret) * (252 ** 0.5)

    # Max drawdown from equity curve
    max_dd_pct = None
    if equity_curve:
        peak = equity_curve[0]["equity"]
        max_dd = 0.0
        for point in equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        max_dd_pct = round(max_dd * 100, 2)

    return {
        "total_pnl": total_pnl,
        "total_pnl_percent": Decimal(str(round(float(total_pnl) / 10000 * 100, 4))),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": float(win_rate) if win_rate is not None else None,
        "profit_factor": float(profit_factor) if profit_factor is not None else None,
        "sharpe_ratio": round(sharpe_ratio, 4) if sharpe_ratio is not None else None,
        "max_drawdown_percent": max_dd_pct,
        "total_fees": total_fees,
        "equity_curve": equity_curve,
    }


async def _upsert_performance(user_id: int, report_date: date, metrics: dict[str, Any]) -> None:
    """Insert or update the performance snapshot for (user_id, report_date)."""
    async with async_session() as db:
        stmt = select(Performance).where(
            and_(
                Performance.user_id == user_id,
                Performance.snapshot_date == report_date,
            )
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.total_pnl = metrics["total_pnl"]
            existing.total_pnl_percent = metrics["total_pnl_percent"]
            existing.total_trades = metrics["total_trades"]
            existing.winning_trades = metrics["winning_trades"]
            existing.losing_trades = metrics["losing_trades"]
            existing.win_rate = metrics["win_rate"]
            existing.profit_factor = metrics["profit_factor"]
            existing.sharpe_ratio = metrics["sharpe_ratio"]
            existing.max_drawdown_percent = metrics["max_drawdown_percent"]
            existing.equity_curve = metrics["equity_curve"]
            existing.total_fees = metrics["total_fees"]
            existing.updated_at = datetime.now(timezone.utc)
        else:
            perf = Performance(
                user_id=user_id,
                snapshot_date=report_date,
                total_pnl=metrics["total_pnl"],
                total_pnl_percent=metrics["total_pnl_percent"],
                total_trades=metrics["total_trades"],
                winning_trades=metrics["winning_trades"],
                losing_trades=metrics["losing_trades"],
                win_rate=metrics["win_rate"],
                profit_factor=metrics["profit_factor"],
                sharpe_ratio=metrics["sharpe_ratio"],
                max_drawdown_percent=metrics["max_drawdown_percent"],
                equity_curve=metrics["equity_curve"],
                total_fees=metrics["total_fees"],
            )
            db.add(perf)

        await db.commit()

    logger.info(
        "Performance snapshot upserted: user=%d date=%s trades=%d pnl=%s",
        user_id, report_date, metrics["total_trades"], metrics["total_pnl"],
    )


async def _async_daily_report(self) -> dict[str, Any]:
    """Aggregate performance for all users for the previous UTC day."""
    yesterday = date.today() - timedelta(days=1)
    logger.info("Starting daily performance report for %s", yesterday)

    async with async_session() as db:
        stmt = select(User.id)
        result = await db.execute(stmt)
        user_ids = [row[0] for row in result.all()]

    processed = 0
    errors = 0
    total_users = len(user_ids)

    for idx, user_id in enumerate(user_ids):
        self.update_state(
            state="PROGRESS",
            meta={"current": idx + 1, "total": total_users, "user_id": user_id},
        )
        try:
            metrics = await _aggregate_user_trades(user_id, yesterday)
            await _upsert_performance(user_id, yesterday, metrics)
            processed += 1
        except Exception:
            logger.exception("Failed to compute performance for user %d", user_id)
            errors += 1

    logger.info(
        "Daily performance report complete: %s processed=%d errors=%d",
        yesterday, processed, errors,
    )
    return {
        "date": yesterday.isoformat(),
        "processed": processed,
        "errors": errors,
        "total_users": total_users,
    }


@celery_app.task(
    bind=True,
    base=DailyReportTask,
    name="app.tasks.reports.daily_performance_report",
    max_retries=2,
    default_retry_delay=60,
    track_started=True,
)
def daily_performance_report(self) -> dict[str, Any]:
    """Celery task entry point: compute & persist daily performance snapshots."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(_async_daily_report(self))