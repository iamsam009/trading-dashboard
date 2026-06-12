"""
Pydantic schemas for authentication endpoints: signup, login, token refresh, user info.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Payload for POST /auth/signup."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (min 8 characters)",
    )


class UserLogin(BaseModel):
    """Payload for POST /auth/login."""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., description="Plain-text password")


class Token(BaseModel):
    """JWT token pair returned on login / refresh."""

    access_token: str = Field(..., description="Signed JWT access token")
    refresh_token: str = Field(..., description="Signed JWT refresh token")
    token_type: str = Field("bearer", description="Token type")


class TokenRefresh(BaseModel):
    """Payload for POST /auth/refresh."""

    refresh_token: str = Field(..., description="Valid refresh token")


class TokenData(BaseModel):
    """Decoded JWT payload used internally by dependency injection."""

    user_id: int
    email: str
    type: str | None = None  # "access" or "refresh"


class UserOut(BaseModel):
    """Public user profile returned by GET /auth/me."""

    id: int
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}