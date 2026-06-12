"""
Performance model – daily performance snapshots with aggregated metrics.

Tracks per-user daily PnL, win rate, profit factor, Sharpe ratio, max drawdown,
and equity curve data (stored as JSONB).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Performance(Base):
    __tablename__ = "performance_stats"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Date this snapshot covers (unique per user per day)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    # ── Aggregate metrics ─────────────────────────────────
    total_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    total_pnl_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    profit_factor: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_drawdown_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Equity curve data points (e.g. [{"ts": "...", "equity": 1000.0}, ...])
    equity_curve: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # Fees for the day
    total_fees: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    # ── Timestamps ────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="performance_stats")

    def __repr__(self) -> str:
        return (
            f"<Performance(id={self.id!r}, user_id={self.user_id!r}, "
            f"date={self.snapshot_date!r}, pnl={self.total_pnl!r})>"
        )