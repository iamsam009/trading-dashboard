"""
Authentication endpoints: signup, login, token refresh, and current user lookup.

POST   /auth/signup  – register a new user
POST   /auth/login   – obtain JWT access + refresh tokens
POST   /auth/refresh – rotate refresh token for a new pair
GET    /auth/me      – return the authenticated user's profile
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.base import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.auth import Token, TokenData, TokenRefresh, UserCreate, UserLogin, UserOut

router = APIRouter()


@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    """Register a new user and return JWT tokens."""
    # Check for duplicate email
    existing = await db.execute(
        select(User).where(User.email == payload.email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    # Issue tokens
    token_data = {"user_id": user.id, "email": user.email}
    return Token(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/login", response_model=Token)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    """Authenticate with email + password and return JWT tokens."""
    result = await db.execute(
        select(User).where(User.email == payload.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    token_data = {"user_id": user.id, "email": user.email}
    return Token(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    payload: TokenRefresh, db: AsyncSession = Depends(get_db)
) -> Token:
    """Accept a valid refresh token and return a fresh token pair."""
    refresh_payload = decode_token(payload.refresh_token)
    if refresh_payload is None or refresh_payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    try:
        token_data = TokenData(**refresh_payload)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed refresh token payload",
        )

    # Verify the user still exists and is active
    result = await db.execute(
        select(User).where(User.id == token_data.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    new_data = {"user_id": user.id, "email": user.email}
    return Token(
        access_token=create_access_token(new_data),
        refresh_token=create_refresh_token(new_data),
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the currently authenticated user's profile."""
    return UserOut.model_validate(current_user)