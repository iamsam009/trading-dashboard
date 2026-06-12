"""
Trading API Endpoints

Provides REST endpoints for Shark Exchange integration:
- GET  /trading/balance      – futures wallet balance
- GET  /trading/positions    – open positions (optional ?symbol= filter)
- GET  /trading/orders       – paginated order history
- POST /trading/manual-order – place a manual order (admin only)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.order_manager import OrderManager, get_order_manager
from app.deps import get_current_user
from app.models.user import User
from app.schemas.order import (
    AccountBalanceResponse,
    ManualOrderRequest,
    OrderListResponse,
    OrderResponse,
    PositionListResponse,
)

router = APIRouter()


# ── Admin guard ────────────────────────────────────────────────


async def _require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow only active users with admin privileges.

    NOTE: This is a minimal admin check. In production, replace with a
    proper role/permission system (e.g. ``is_superuser`` column on User).
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user


# ── Balance ────────────────────────────────────────────────────


@router.get("/balance", response_model=AccountBalanceResponse)
async def get_balance(
    current_user: User = Depends(get_current_user),
    manager: OrderManager = Depends(get_order_manager),
) -> AccountBalanceResponse:
    """Fetch the authenticated user's futures wallet balance from Shark Exchange."""
    return await manager.get_balance(current_user.id)


# ── Positions ──────────────────────────────────────────────────


@router.get("/positions", response_model=PositionListResponse)
async def get_positions(
    symbol: str | None = Query(
        None,
        min_length=2,
        max_length=20,
        pattern=r"^[A-Z0-9]+$",
        description="Filter by trading pair (e.g. BTCINR)",
    ),
    current_user: User = Depends(get_current_user),
    manager: OrderManager = Depends(get_order_manager),
) -> PositionListResponse:
    """List open positions, optionally filtered by symbol."""
    positions = await manager.get_positions(current_user.id, symbol=symbol)
    return PositionListResponse(positions=positions, total=len(positions))


# ── Orders ─────────────────────────────────────────────────────


@router.get("/orders", response_model=OrderListResponse)
async def get_orders(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    manager: OrderManager = Depends(get_order_manager),
) -> OrderListResponse:
    """Fetch paginated order history for the authenticated user."""
    orders, total = await manager.get_orders(current_user.id, page=page, size=size)
    return OrderListResponse(orders=orders, total=total, page=page, size=size)


# ── Manual Order (admin only) ──────────────────────────────────


@router.post(
    "/manual-order",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def place_manual_order(
    request: ManualOrderRequest,
    current_user: User = Depends(_require_admin),
    manager: OrderManager = Depends(get_order_manager),
) -> OrderResponse:
    """Place a manual order on Shark Exchange.

    Requires admin access. The order goes through full risk validation
    (kill switch, leverage, position size, daily loss limit) before
    being sent to the exchange.
    """
    try:
        return await manager.place_manual_order(current_user.id, request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc