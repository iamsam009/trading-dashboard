"""
Dashboard Analytics API Endpoints

Aggregates data from multiple sources (performance, trading, positions,
strategies) into a single comprehensive dashboard response.

- GET  /dashboard/overview  – aggregated metrics, equity curve, daily PnL
- GET  /dashboard/balance    – wallet balance (delegates to OrderManager)
- GET  /dashboard/positions   – open positions (delegates to OrderManager)
- GET  /dashboard/strategies  – active strategies with status
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.order_manager import OrderManager, get_order_manager
from app.db.base import get_db
from app.deps import get_current_user
from app.models.performance import Performance
from app.models.position import Position
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.models.user import User
from app.schemas.order import (
    AccountBalanceResponse,
    PositionListResponse,
    PositionResponse,
)

router = APIRouter()


# ── Pydantic response models ──────────────────────────────────


class EquityPointOut(BaseModel):
    """A single point on the equity curve."""
    ts: str = Field(..., description="ISO-8601 timestamp")
    equity: float = Field(..., description="Portfolio equity value at this point")


class PerformanceMetricsOut(BaseModel):
    """Aggregated performance metrics for the dashboard."""
    total_pnl: float = Field(0.0, description="Cumulative realised PnL")
    total_pnl_percent: float = Field(0.0, description="Percentage return")
    win_rate: float = Field(0.0, description="Win rate (0-100)")
    profit_factor: float = Field(0.0, description="Gross profit / gross loss")
    sharpe_ratio: float = Field(0.0, description="Sharpe ratio (annualised)")
    max_drawdown_percent: float = Field(0.0, description="Maximum drawdown percentage")
    total_trades: int = Field(0, description="Total number of trades")
    winning_trades: int = Field(0, description="Number of winning trades")
    losing_trades: int = Field(0, description="Number of losing trades")
    equity_curve: list[EquityPointOut] = Field(
        default_factory=list, description="Equity curve data points"
    )


class StrategySummaryOut(BaseModel):
    """Lightweight strategy summary for the dashboard runner."""
    id: int
    name: str
    description: str | None = None
    is_active: bool = False
    symbols: list[str] = Field(default_factory=list)
    version: int = 1

    model_config = {"from_attributes": True}


class DashboardOverviewResponse(BaseModel):
    """Full dashboard overview payload."""
    metrics: PerformanceMetricsOut
    daily_pnl: float = Field(0.0, description="Today's realised PnL")
    balance: AccountBalanceResponse | None = None
    positions: list[PositionResponse] = Field(default_factory=list)
    positions_total: int = 0
    strategies: list[StrategySummaryOut] = Field(default_factory=list)
    strategies_active: int = 0


# ── Helpers ───────────────────────────────────────────────────


def _decimal_or_zero(val: Decimal | None) -> float:
    """Safely convert a nullable Decimal to float."""
    return float(val) if val is not None else 0.0


async def _compute_daily_pnl(db: AsyncSession, user_id: int) -> float:
    """Sum today's realised PnL from the trades table."""
    today = date.today()
    start_of_day = datetime.combine(today, datetime.min.time())
    end_of_day = datetime.combine(today, datetime.max.time())

    result = await db.execute(
        select(func.coalesce(func.sum(Trade.pnl), 0)).where(
            Trade.user_id == user_id,
            Trade.closed_at >= start_of_day,
            Trade.closed_at <= end_of_day,
            Trade.status == "FILLED",
        )
    )
    return float(result.scalar_one() or 0)


async def _get_latest_performance(
    db: AsyncSession, user_id: int
) -> Performance | None:
    """Fetch the most recent performance snapshot for the user."""
    result = await db.execute(
        select(Performance)
        .where(Performance.user_id == user_id)
        .order_by(desc(Performance.snapshot_date))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_strategies(db: AsyncSession, user_id: int) -> list[Strategy]:
    """Fetch all strategies for the user."""
    result = await db.execute(
        select(Strategy).where(Strategy.user_id == user_id).order_by(Strategy.id)
    )
    return list(result.scalars().all())


def _extract_symbols(strategy: Strategy) -> list[str]:
    """Extract symbols from a strategy's definition JSON."""
    try:
        definition = strategy.definition or {}
        if isinstance(definition, dict):
            symbols = definition.get("symbols", [])
            if isinstance(symbols, list):
                return [str(s) for s in symbols]
    except Exception:
        pass
    return []


async def _get_equity_curve(
    db: AsyncSession, user_id: int, days: int = 30
) -> list[EquityPointOut]:
    """Build equity curve from daily performance snapshots (last N days)."""
    cutoff = date.today() - timedelta(days=days)

    result = await db.execute(
        select(Performance)
        .where(
            Performance.user_id == user_id,
            Performance.snapshot_date >= cutoff,
        )
        .order_by(Performance.snapshot_date.asc())
    )
    rows = result.scalars().all()

    curve: list[EquityPointOut] = []
    cumulative = 0.0

    for row in rows:
        cumulative += _decimal_or_zero(row.total_pnl)
        curve.append(
            EquityPointOut(
                ts=row.snapshot_date.isoformat(),
                equity=round(cumulative, 2),
            )
        )

    # If no performance rows exist, fall back to an empty useful curve
    if not curve:
        curve.append(
            EquityPointOut(
                ts=date.today().isoformat(),
                equity=0.0,
            )
        )

    return curve


# ── Endpoints ─────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Dashboard overview",
    description="Aggregated dashboard data: metrics, equity curve, balances, positions, strategies.",
)
async def get_dashboard_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    order_manager: OrderManager = Depends(get_order_manager),
) -> DashboardOverviewResponse:
    """Return a comprehensive dashboard overview for the authenticated user."""
    user_id = current_user.id

    # Fetch performance, daily PnL, equity curve, strategies in parallel
    perf = await _get_latest_performance(db, user_id)
    daily_pnl = await _compute_daily_pnl(db, user_id)
    equity_curve = await _get_equity_curve(db, user_id)
    strategies = await _get_strategies(db, user_id)

    # Build metrics
    if perf is not None:
        metrics = PerformanceMetricsOut(
            total_pnl=_decimal_or_zero(perf.total_pnl),
            total_pnl_percent=_decimal_or_zero(perf.total_pnl_percent),
            win_rate=_decimal_or_zero(perf.win_rate) * 100,  # stored as 0-1, show as %
            profit_factor=_decimal_or_zero(perf.profit_factor),
            sharpe_ratio=_decimal_or_zero(perf.sharpe_ratio),
            max_drawdown_percent=_decimal_or_zero(perf.max_drawdown_percent),
            total_trades=perf.total_trades or 0,
            winning_trades=perf.winning_trades or 0,
            losing_trades=perf.losing_trades or 0,
            equity_curve=equity_curve,
        )
    else:
        metrics = PerformanceMetricsOut(equity_curve=equity_curve)

    # Fetch balance
    try:
        balance = await order_manager.get_balance(user_id)
    except Exception:
        balance = None

    # Fetch positions
    try:
        positions = await order_manager.get_positions(user_id)
    except Exception:
        positions = []

    # Build strategy summaries
    strategy_summaries: list[StrategySummaryOut] = []
    active_count = 0
    for s in strategies:
        active = s.is_active or False
        if active:
            active_count += 1
        strategy_summaries.append(
            StrategySummaryOut(
                id=s.id or 0,
                name=s.name or "Unnamed",
                description=s.description,
                is_active=active,
                symbols=_extract_symbols(s),
                version=s.version or 1,
            )
        )

    return DashboardOverviewResponse(
        metrics=metrics,
        daily_pnl=daily_pnl,
        balance=balance,
        positions=positions,
        positions_total=len(positions),
        strategies=strategy_summaries,
        strategies_active=active_count,
    )


@router.get(
    "/balance",
    response_model=AccountBalanceResponse,
    summary="Dashboard balance",
    description="Fetch wallet balance via the OrderManager (same as /trading/balance).",
)
async def get_dashboard_balance(
    current_user: User = Depends(get_current_user),
    order_manager: OrderManager = Depends(get_order_manager),
) -> AccountBalanceResponse:
    """Return the authenticated user's wallet balance."""
    return await order_manager.get_balance(current_user.id)


@router.get(
    "/positions",
    response_model=PositionListResponse,
    summary="Dashboard positions",
    description="List open positions via the OrderManager (same as /trading/positions).",
)
async def get_dashboard_positions(
    symbol: str | None = Query(
        None,
        min_length=2,
        max_length=20,
        pattern=r"^[A-Z0-9]+$",
        description="Filter by trading pair (e.g. BTCINR)",
    ),
    current_user: User = Depends(get_current_user),
    order_manager: OrderManager = Depends(get_order_manager),
) -> PositionListResponse:
    """List open positions, optionally filtered by symbol."""
    positions = await order_manager.get_positions(current_user.id, symbol=symbol)
    return PositionListResponse(positions=positions, total=len(positions))


@router.get(
    "/strategies",
    response_model=list[StrategySummaryOut],
    summary="Dashboard strategies",
    description="List all strategies with their active status and symbols.",
)
async def get_dashboard_strategies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StrategySummaryOut]:
    """Return all strategies for the dashboard runner."""
    strategies = await _get_strategies(db, current_user.id)

    return [
        StrategySummaryOut(
            id=s.id or 0,
            name=s.name or "Unnamed",
            description=s.description,
            is_active=s.is_active or False,
            symbols=_extract_symbols(s),
            version=s.version or 1,
        )
        for s in strategies
    ]