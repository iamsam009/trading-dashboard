"""
Helpers for encryption (Fernet), password hashing (passlib), and JWT tokens.

- Fernet symmetric encryption for API keys/secrets at rest.
- bcrypt password hashing for user credentials.
- JWT token creation/verification for authentication.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

# ── Password Hashing ─────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return bcrypt hash of the plain-text password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ── Fernet Encryption (API secrets at rest) ──────────────

def _get_fernet() -> Fernet:
    """Lazily initialise a Fernet instance from settings or env."""
    settings = get_settings()
    key: str = settings.encryption_key
    if not key:
        # Auto-generate and warn – in production this MUST be set explicitly
        key = os.environ.get("ENCRYPTION_KEY", "")
        if not key:
            key = Fernet.generate_key().decode()
            os.environ["ENCRYPTION_KEY"] = key
            import logging
            logging.getLogger(__name__).warning(
                "⚠️  ENCRYPTION_KEY not set – generated a temporary key. "
                "Set ENCRYPTION_KEY in .env for production."
            )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plain-text value with Fernet. Returns base64-encoded ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted value back to plain text."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()


# ── JWT Tokens ───────────────────────────────────────────

def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(
    data: dict,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT refresh token with longer expiry."""
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.refresh_token_expire_days)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token. Returns payload dict or None on failure."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None