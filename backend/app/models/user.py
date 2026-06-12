"""
User model – the central identity for the trading dashboard.

Each user owns API keys, strategies, trades, positions, risk settings,
logs, and performance snapshots.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.api_key import APIKey
    from app.models.strategy import Strategy
    from app.models.trade import Trade
    from app.models.position import Position
    from app.models.risk_setting import RiskSetting
    from app.models.log import Log  # noqa: F811
    from app.models.performance import Performance


class User(Base):
    __tablename__ = "users"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────
    api_keys: Mapped[list["APIKey"]] = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan"
    )
    strategies: Mapped[list["Strategy"]] = relationship(
        "Strategy", back_populates="user", cascade="all, delete-orphan"
    )
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="user", cascade="all, delete-orphan"
    )
    positions: Mapped[list["Position"]] = relationship(
        "Position", back_populates="user", cascade="all, delete-orphan"
    )
    risk_setting: Mapped["RiskSetting | None"] = relationship(
        "RiskSetting", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    logs: Mapped[list["Log"]] = relationship(
        "Log", back_populates="user", cascade="all, delete-orphan"
    )
    performance_stats: Mapped[list["Performance"]] = relationship(
        "Performance", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id!r}, email={self.email!r})>"