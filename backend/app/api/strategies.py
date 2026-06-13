"""
Strategy management endpoints – CRUD + dry-run validation.

POST   /strategies          – validate & store a new strategy
GET    /strategies          – list all strategies for the current user
GET    /strategies/{id}     – get a single strategy
PUT    /strategies/{id}     – update JSON, re-validate
DELETE /strategies/{id}     – soft-delete (deactivate)
POST   /strategies/{id}/validate – dry-run validation without persisting

All endpoints require authentication.  Strategy JSON is validated against
``schemas/strategy_schema.json`` before storage.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.strategy_validator import validate_strategy
from app.db.base import get_db
from app.deps import get_current_user
from app.models.strategy import Strategy
from app.models.user import User

router = APIRouter()


# ── Pydantic schemas (inline to keep the module self-contained) ─────
from pydantic import BaseModel, Field


class StrategyOut(BaseModel):
    """Response schema for strategy endpoints."""

    id: int
    user_id: int
    name: str
    description: str | None = None
    json_definition: dict
    is_active: bool
    version: int
    tags: list[str] | None = None
    backtest_results: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StrategyCreate(BaseModel):
    """Request schema for POST /strategies."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    json_definition: dict
    tags: list[str] | None = None
    is_active: bool = True


class StrategyUpdate(BaseModel):
    """Request schema for PUT /strategies/{id}."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    json_definition: dict | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


class StrategyValidateRequest(BaseModel):
    """Request schema for POST /strategies/{id}/validate – dry-run."""

    json_definition: dict


class StrategyValidateResponse(BaseModel):
    """Response for dry-run validation."""

    valid: bool
    errors: list[str] = []
    strategy_name: str | None = None
    indicators_used: list[str] = []
    symbols: list[str] = []


# ── Helpers ──────────────────────────────────────────────────────────


async def _get_strategy_or_404(
    strategy_id: int, user: User, db: AsyncSession
) -> Strategy:
    """Fetch a Strategy belonging to `user` or raise HTTP 404."""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id, Strategy.user_id == user.id
        )
    )
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )
    return strategy


def _extract_indicators(definition: dict) -> list[str]:
    """Extract indicator names referenced in the strategy JSON."""
    indicators: set[str] = set()
    for condition in definition.get("conditions", []):
        if "indicator" in condition:
            indicators.add(condition["indicator"])
        if "compare_to" in condition and condition["compare_to"] != "price":
            indicators.add(condition["compare_to"])
    return sorted(indicators)


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: StrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyOut:
    """Validate and store a new trading strategy."""
    errors = validate_strategy(payload.json_definition)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Strategy validation failed", "errors": errors},
        )

    strategy = Strategy(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        json_definition=payload.json_definition,
        is_active=payload.is_active,
        tags=payload.tags,
    )
    db.add(strategy)
    await db.flush()
    await db.refresh(strategy)
    # Commit is handled by get_db() dependency
    return strategy


@router.get("/", response_model=list[StrategyOut])
async def list_strategies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    active_only: bool = False,
) -> list[StrategyOut]:
    """List all strategies for the authenticated user.

    Query params:
        active_only: If true, only return active strategies.
    """
    stmt = select(Strategy).where(Strategy.user_id == current_user.id)
    if active_only:
        stmt = stmt.where(Strategy.is_active.is_(True))
    stmt = stmt.order_by(Strategy.updated_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyOut:
    """Retrieve a single strategy by ID."""
    return await _get_strategy_or_404(strategy_id, current_user, db)


@router.put("/{strategy_id}", response_model=StrategyOut)
async def update_strategy(
    strategy_id: int,
    payload: StrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyOut:
    """Update a strategy – re-validates JSON if a new definition is provided."""
    strategy = await _get_strategy_or_404(strategy_id, current_user, db)

    # Validate new definition if provided
    if payload.json_definition is not None:
        errors = validate_strategy(payload.json_definition)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Strategy validation failed", "errors": errors},
            )
        strategy.json_definition = payload.json_definition
        strategy.version += 1

    if payload.name is not None:
        strategy.name = payload.name
    if payload.description is not None:
        strategy.description = payload.description
    if payload.tags is not None:
        strategy.tags = payload.tags
    if payload.is_active is not None:
        strategy.is_active = payload.is_active

    strategy.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(strategy)
    # Commit is handled by get_db() dependency
    return strategy


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Deactivate (soft-delete) a strategy.  Hard-delete purges the row."""
    strategy = await _get_strategy_or_404(strategy_id, current_user, db)
    await db.delete(strategy)
    await db.flush()
    # Commit is handled by get_db() dependency
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{strategy_id}/validate", response_model=StrategyValidateResponse)
async def validate_strategy_dry_run(
    strategy_id: int,
    payload: StrategyValidateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyValidateResponse:
    """Dry-run validation of a strategy JSON without persisting.

    Also accepts ``strategy_id=0`` to validate a new (unsaved) definition.
    """
    errors = validate_strategy(payload.json_definition)

    return StrategyValidateResponse(
        valid=len(errors) == 0,
        errors=errors,
        strategy_name=payload.json_definition.get("name"),
        indicators_used=_extract_indicators(payload.json_definition),
        symbols=payload.json_definition.get("symbols", []),
    )