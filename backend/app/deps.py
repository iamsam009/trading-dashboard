"""
FastAPI dependencies – reusable dependency-injection callables.

- `get_db` – yields an async database session (forwarded from `app.db.base`).
- `get_current_user` – decodes the JWT from the `Authorization` header and fetches the
  corresponding user from the database.

Usage::

    @router.get("/me")
    async def me(current_user: User = Depends(get_current_user)):
        return {"email": current_user.email}
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.base import get_db
from app.models.user import User
from app.schemas.auth import TokenData

# ── OAuth2 scheme ────────────────────────────────────────
# This tells FastAPI to extract the Bearer token from the
# `Authorization: Bearer <token>` header on protected routes.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode JWT, verify `type` claim is 'access', and return the DB user.

    Raises HTTP 401 if the token is missing, expired, or invalid,
    or if the user no longer exists / is deactivated.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    # Reject refresh tokens used as access tokens
    if payload.get("type") != "access":
        raise credentials_exception

    try:
        token_data = TokenData(**payload)
    except Exception:
        raise credentials_exception

    result = await db.execute(
        select(User).where(User.id == token_data.user_id)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_exception

    return user