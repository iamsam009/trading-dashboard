"""
Trade model – records of completed (or in-flight) trades and orders.

Tracks entry/exit details, PnL, fees, and links to the originating strategy.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.strategy import Strategy


class Trade(Base):
    __tablename__ = "trades"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY / SELL
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MARKET")

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    leverage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # PnL fields
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    pnl_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    fees: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    # Status lifecycle: PENDING → OPEN → FILLED / CANCELLED / REJECTED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")

    # Exchange reference
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Flexible metadata (slippage, execution latency, raw exchange response, etc.)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="trades")
    strategy: Mapped["Strategy | None"] = relationship("Strategy", back_populates="trades")

    def __repr__(self) -> str:
        return (
            f"<Trade(id={self.id!r}, symbol={self.symbol!r}, "
            f"side={self.side!r}, status={self.status!r})>"
        )