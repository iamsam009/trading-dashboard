"""Pydantic schemas for Backtest API – request/response validation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Request ──────────────────────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    """Submit a new backtest for a strategy."""

    strategy_id: int = Field(..., gt=0, description="DB strategy ID to backtest")
    start_date: date = Field(..., description="Backtest start date (inclusive)")
    end_date: date = Field(..., description="Backtest end date (inclusive)")
    symbol: str | None = Field(
        None,
        min_length=2,
        max_length=20,
        description="Override symbol; defaults to first symbol in strategy definition",
    )
    initial_capital: float = Field(
        10_000.0,
        gt=0,
        description="Starting capital for the backtest simulation",
    )


class BacktestSubmitResponse(BaseModel):
    """Response after submitting a backtest job."""

    task_id: str = Field(..., description="Celery AsyncResult task ID")
    status: str = "PENDING"


# ── Result ───────────────────────────────────────────────────────────────────


class BacktestMetrics(BaseModel):
    """Quantitative metrics computed from the backtest."""

    total_return_pct: float = Field(..., description="(final_equity - initial) / initial * 100")
    total_pnl: float = Field(..., description="Absolute P&L in quote currency")
    max_drawdown_pct: float = Field(..., description="Largest peak-to-trough decline, as %")
    sharpe_ratio: float | None = Field(None, description="Annualised Sharpe (risk-free=0)")
    win_rate_pct: float = Field(..., description="Winning trades / total trades * 100")
    profit_factor: float | None = Field(None, description="Gross profit / gross loss")
    total_trades: int = Field(..., ge=0)
    winning_trades: int = Field(0, ge=0)
    losing_trades: int = Field(0, ge=0)
    avg_win: float | None = Field(None, description="Average P&L per winning trade")
    avg_loss: float | None = Field(None, description="Average P&L per losing trade")
    best_trade: float | None = Field(None)
    worst_trade: float | None = Field(None)


class BacktestEquityPoint(BaseModel):
    """Single point on the equity curve."""

    ts: datetime
    equity: float


class BacktestResult(BaseModel):
    """Full backtest result including metrics and equity curve."""

    task_id: str
    status: str  # PENDING, STARTED, SUCCESS, FAILURE
    strategy_id: int
    strategy_name: str
    symbol: str
    start_date: date
    end_date: date
    initial_capital: float
    final_equity: float | None = None
    metrics: BacktestMetrics | None = None
    equity_curve: list[BacktestEquityPoint] = []
    trades: list[dict[str, Any]] = []
    error: str | None = None
    completed_at: datetime | None = None