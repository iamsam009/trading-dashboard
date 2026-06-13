"""
API key management endpoints – CRUD with Fernet-encrypted storage.

POST   /api-keys       – store a new encrypted API key
GET    /api-keys       – list all keys (masked) for the current user
GET    /api-keys/{id}  – get a single key (masked)
PUT    /api-keys/{id}  – update an existing key
DELETE /api-keys/{id}  – delete a key

All endpoints require authentication.  Plain secrets are NEVER returned in responses.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.deps import get_current_user
from app.models.api_key import APIKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyOut, ApiKeyUpdate

router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────
async def _get_key_or_404(
    key_id: int, user: User, db: AsyncSession
) -> APIKey:
    """Fetch an APIKey belonging to `user` or raise HTTP 404."""
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    return api_key


# ── Routes ──────────────────────────────────────────────────
@router.post("/", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    """Store a new exchange API key with Fernet-encrypted secrets."""
    encrypted = APIKey.encrypt_credentials(
        payload.api_key,
        payload.api_secret,
        payload.passphrase,
    )

    api_key = APIKey(
        user_id=current_user.id,
        exchange_name=payload.exchange_name,
        label=payload.label,
        api_key_encrypted=encrypted["api_key_encrypted"],
        api_secret_encrypted=encrypted["api_secret_encrypted"],
        passphrase_encrypted=encrypted["passphrase_encrypted"],
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    await db.commit()

    return ApiKeyOut.from_orm_model(api_key)


@router.get("/", response_model=list[ApiKeyOut])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyOut]:
    """List all API keys for the authenticated user (secrets masked)."""
    result = await db.execute(
        select(APIKey).where(APIKey.user_id == current_user.id)
    )
    return [ApiKeyOut.from_orm_model(k) for k in result.scalars().all()]


@router.get("/{key_id}", response_model=ApiKeyOut)
async def get_api_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    """Retrieve a single API key by ID (secrets masked)."""
    api_key = await _get_key_or_404(key_id, current_user, db)
    return ApiKeyOut.from_orm_model(api_key)


@router.put("/{key_id}", response_model=ApiKeyOut)
async def update_api_key(
    key_id: int,
    payload: ApiKeyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    """Update an existing API key.  Only provided fields are changed."""
    api_key = await _get_key_or_404(key_id, current_user, db)

    if payload.exchange_name is not None:
        api_key.exchange_name = payload.exchange_name
    if payload.label is not None:
        api_key.label = payload.label
    if payload.api_key is not None:
        from app.core.security import encrypt_value

        api_key.api_key_encrypted = encrypt_value(payload.api_key)
    if payload.api_secret is not None:
        from app.core.security import encrypt_value

        api_key.api_secret_encrypted = encrypt_value(payload.api_secret)
    if payload.passphrase is not None:
        from app.core.security import encrypt_value

        api_key.passphrase_encrypted = encrypt_value(payload.passphrase)

    await db.flush()
    await db.refresh(api_key)
    await db.commit()
    return ApiKeyOut.from_orm_model(api_key)


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an API key by ID."""
    api_key = await _get_key_or_404(key_id, current_user, db)
    await db.delete(api_key)
    await db.flush()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)