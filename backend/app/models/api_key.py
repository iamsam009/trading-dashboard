"""
API key model with Fernet-encrypted secrets at rest.

Stores exchange API credentials (e.g. Shark Exchange) encrypted via Fernet.
The encryption helper lives in `app.core.security`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class APIKey(Base):
    __tablename__ = "api_keys"

    # ── Columns ───────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exchange_name: Mapped[str] = mapped_column(
        String(50), nullable=False, default="shark"
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Fernet-encrypted fields – NEVER expose raw plaintext
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    passphrase_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    # ── Convenience helpers ───────────────────────────────
    @property
    def api_key(self) -> str:
        """Decrypt and return the plain-text API key."""
        from app.core.security import decrypt_value

        return decrypt_value(self.api_key_encrypted)

    @property
    def api_secret(self) -> str:
        """Decrypt and return the plain-text API secret."""
        from app.core.security import decrypt_value

        return decrypt_value(self.api_secret_encrypted)

    @property
    def passphrase(self) -> str | None:
        """Decrypt and return the plain-text passphrase (if set)."""
        if self.passphrase_encrypted is None:
            return None
        from app.core.security import decrypt_value

        return decrypt_value(self.passphrase_encrypted)

    @classmethod
    def encrypt_credentials(
        cls,
        api_key_plain: str,
        api_secret_plain: str,
        passphrase_plain: str | None = None,
    ) -> dict[str, str | None]:
        """Encrypt plain-text credentials (useful before persisting)."""
        from app.core.security import encrypt_value

        return {
            "api_key_encrypted": encrypt_value(api_key_plain),
            "api_secret_encrypted": encrypt_value(api_secret_plain),
            "passphrase_encrypted": encrypt_value(passphrase_plain)
            if passphrase_plain
            else None,
        }

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id!r}, exchange={self.exchange_name!r}, user_id={self.user_id!r})>"