"""
Pydantic schemas for API key CRUD endpoints.

Plain secrets are ONLY accepted on input (ApiKeyCreate / ApiKeyUpdate).
All output types return masked keys – plain secrets are never exposed in responses.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


def _mask(value: str, visible: int = 4) -> str:
    """Return a masked string showing only the first/last `visible` characters."""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * (len(value) - visible * 2)}{value[-visible:]}"


class ApiKeyCreate(BaseModel):
    """Payload for POST /api-keys – plain-text secrets accepted for encryption."""

    exchange_name: str = Field("shark", max_length=50, description="Exchange identifier")
    label: str | None = Field(None, max_length=100, description="Human-readable label")
    api_key: str = Field(..., min_length=1, max_length=512, description="Exchange API key (plain)")
    api_secret: str = Field(..., min_length=1, max_length=512, description="Exchange API secret (plain)")
    passphrase: str | None = Field(None, max_length=512, description="Optional passphrase (plain)")


class ApiKeyUpdate(BaseModel):
    """Payload for PUT /api-keys/{id} – all fields optional for partial updates."""

    exchange_name: str | None = Field(None, max_length=50)
    label: str | None = Field(None, max_length=100)
    api_key: str | None = Field(None, min_length=1, max_length=512, description="New API key (plain)")
    api_secret: str | None = Field(None, min_length=1, max_length=512, description="New API secret (plain)")
    passphrase: str | None = Field(None, max_length=512, description="New passphrase (plain)")


class ApiKeyOut(BaseModel):
    """Response for GET /api-keys and POST/PUT responses – NEVER exposes plain secrets."""

    id: int
    exchange_name: str
    label: str | None
    api_key_masked: str = Field(..., description="Masked API key (first 4 … last 4)")
    has_passphrase: bool = Field(..., description="Whether a passphrase is stored")
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, api_key_obj) -> "ApiKeyOut":
        """Build output schema from an ORM APIKey instance, masking secrets."""
        from app.models.api_key import APIKey as ApiKeyModel

        obj: ApiKeyModel = api_key_obj
        return cls(
            id=obj.id,
            exchange_name=obj.exchange_name,
            label=obj.label,
            api_key_masked=_mask(obj.api_key),
            has_passphrase=obj.passphrase is not None,
            created_at=obj.created_at,
            last_used_at=obj.last_used_at,
        )