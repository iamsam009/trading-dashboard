"""
Log model – structured application/audit logs per user.

Supports standard log levels (INFO, WARNING, ERROR, etc.) and flexible JSONB
metadata for arbitrary context.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Log(Base):
    __tablename__ = "logs"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INFO"
    )  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True
    )  # e.g. "trade", "system", "auth"

    # Flexible extra data (tracebacks, request payloads, etc.)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="logs")

    def __repr__(self) -> str:
        return (
            f"<Log(id={self.id!r}, level={self.level!r}, "
            f"category={self.category!r})>"
        )