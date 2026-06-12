"""
Strategy model – user-defined trading strategies stored as JSON definitions.

Strategies can be toggled active/inactive and version-tracked.  Backtest
results are stored as JSONB for flexible querying.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.trade import Trade
    from app.models.position import Position


class Strategy(Base):
    __tablename__ = "strategies"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Flexible strategy definition (indicators, entry/exit rules, etc.)
    json_definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Tags stored as JSONB array, e.g. ["scalping", "BTC", "trend-following"]
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Backtest results (metrics, equity curve slices, etc.)
    backtest_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="strategies")
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="strategy", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship(
        "Position", back_populates="strategy", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Strategy(id={self.id!r}, name={self.name!r}, v{self.version})>"