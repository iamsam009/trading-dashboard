"""
Risk settings model – per-user risk management configuration.

A single-user risk profile (one-to-one with User). Controls daily loss
limits, drawdown thresholds, position sizing, stop-loss/take-profit defaults,
and a global kill-switch.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class RiskSetting(Base):
    __tablename__ = "risk_settings"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    # --- Loss / Drawdown Limits ---
    daily_loss_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    max_drawdown_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    weekly_loss_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    # --- Position Sizing ---
    max_open_trades: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    position_size_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_leverage: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    # --- Stop-Loss / Take-Profit defaults ---
    stop_loss_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    take_profit_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    trailing_stop_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trailing_stop_distance_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # --- Risk per Trade ---
    risk_per_trade_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # --- Kill Switch ---
    kill_switch_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    kill_switch_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Trading Window ---
    trading_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="risk_setting")

    def __repr__(self) -> str:
        return (
            f"<RiskSetting(id={self.id!r}, user_id={self.user_id!r}, "
            f"kill_switch={self.kill_switch_enabled})>"
        )