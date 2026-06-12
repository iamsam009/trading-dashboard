"""
Position model – currently open trading positions with real-time stats.

Tracks entry/current price, unrealized PnL, liquidation price, and strategy link.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.strategy import Strategy


class Position(Base):
    __tablename__ = "positions"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # LONG / SHORT

    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # PnL
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    unrealized_pnl_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    # Liquidation
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    # Margin
    margin_used: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    # Status: OPEN, CLOSING, LIQUIDATED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    exchange_position_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="positions")
    strategy: Mapped["Strategy | None"] = relationship("Strategy", back_populates="positions")

    def __repr__(self) -> str:
        return (
            f"<Position(id={self.id!r}, symbol={self.symbol!r}, "
            f"side={self.side!r}, status={self.status!r})>"
        )