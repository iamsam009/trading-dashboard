"""Risk Management REST API – endpoints for risk settings, kill-switch, and status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.risk_manager import RiskManager, get_risk_manager
from app.db.base import async_session
from app.deps import get_current_user
from app.models.risk_setting import RiskSetting
from app.models.user import User
from app.schemas.risk import (
    KillSwitchRequest,
    KillSwitchResponse,
    RiskCheckRequest,
    RiskCheckResponse,
    RiskSettingsResponse,
    RiskSettingsUpdate,
    RiskStatusResponse,
)

router = APIRouter()


def _get_rm() -> RiskManager:
    return get_risk_manager()


# ---------------------------------------------------------------------------
# Risk Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=RiskSettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
) -> RiskSettingsResponse:
    """Return the current risk-management configuration for the authenticated user."""
    async with async_session() as db:
        from sqlalchemy import select

        stmt = select(RiskSetting).where(RiskSetting.user_id == current_user.id)
        result = await db.execute(stmt)
        risk: RiskSetting | None = result.scalar_one_or_none()

        if risk is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No risk settings configured for this user.",
            )

        return RiskSettingsResponse.model_validate(risk)


@router.put("/settings", response_model=RiskSettingsResponse)
async def update_settings(
    payload: RiskSettingsUpdate,
    current_user: User = Depends(get_current_user),
) -> RiskSettingsResponse:
    """Update one or more risk parameters for the authenticated user."""
    async with async_session() as db:
        from sqlalchemy import select

        stmt = select(RiskSetting).where(RiskSetting.user_id == current_user.id)
        result = await db.execute(stmt)
        risk: RiskSetting | None = result.scalar_one_or_none()

        if risk is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No risk settings configured for this user.",
            )

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(risk, field, value)

        db.add(risk)
        await db.commit()
        await db.refresh(risk)

        return RiskSettingsResponse.model_validate(risk)


# ---------------------------------------------------------------------------
# Pre-order Risk Check
# ---------------------------------------------------------------------------


@router.post("/check", response_model=RiskCheckResponse)
async def check_order(
    request: RiskCheckRequest,
    current_user: User = Depends(get_current_user),
    rm: RiskManager = Depends(_get_rm),
) -> RiskCheckResponse:
    """Evaluate whether a proposed order would violate risk limits."""
    return await rm.check_order(current_user.id, request)


# ---------------------------------------------------------------------------
# Kill Switch
# ---------------------------------------------------------------------------


@router.post("/kill-switch", response_model=KillSwitchResponse)
async def toggle_kill_switch(
    payload: KillSwitchRequest,
    current_user: User = Depends(get_current_user),
    rm: RiskManager = Depends(_get_rm),
) -> KillSwitchResponse:
    """Engage or disengage the emergency kill-switch.

    When engaged:
    - All open positions are marked CLOSING.
    - Trading is disabled.
    - An audit log entry is written.
    - A WebSocket alert is broadcast.
    """
    if payload.enabled:
        reason = payload.reason or "Manual kill-switch activation"
        result = await rm.activate_kill_switch(current_user.id, reason)
        return KillSwitchResponse(
            kill_switch_enabled=True,
            message=result["message"],
            positions_closed=result.get("positions_closed", 0),
        )
    else:
        result = await rm.deactivate_kill_switch(current_user.id)
        return KillSwitchResponse(
            kill_switch_enabled=False,
            message=result["message"],
            positions_closed=0,
        )


# ---------------------------------------------------------------------------
# Risk Status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=RiskStatusResponse)
async def get_status(
    current_user: User = Depends(get_current_user),
    rm: RiskManager = Depends(_get_rm),
) -> RiskStatusResponse:
    """Return a real-time risk snapshot (daily PnL, drawdown, trailing stops)."""
    return await rm.get_status(current_user.id)