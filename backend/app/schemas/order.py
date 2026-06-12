"""
Pydantic schemas for order requests, responses, and position updates.

These models define the contract for the trading API endpoints
(GET /trading/balance, GET /trading/positions, POST /trading/manual-order, GET /trading/orders).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LIQUIDATED = "LIQUIDATED"


# ── Order Request ────────────────────────────────────────────


class ManualOrderRequest(BaseModel):
    """Payload for POST /trading/manual-order (admin only)."""

    symbol: str = Field(
        ...,
        min_length=2,
        max_length=20,
        pattern=r"^[A-Z0-9]+$",
        description="Trading pair symbol (e.g. BTCINR, ETHINR)",
    )
    side: OrderSide = Field(..., description="BUY or SELL")
    order_type: OrderType = Field(..., description="MARKET, LIMIT, STOP_MARKET, STOP_LIMIT")
    quantity: float = Field(..., gt=0, description="Order quantity in base asset")
    price: float | None = Field(
        None,
        gt=0,
        description="Limit price (required for LIMIT, STOP_LIMIT; optional for MARKET)",
    )
    stop_price: float | None = Field(
        None,
        gt=0,
        description="Stop/trigger price (required for STOP_MARKET, STOP_LIMIT)",
    )
    leverage: int = Field(
        1,
        ge=1,
        le=125,
        description="Leverage multiplier (1-125, default 1)",
    )
    reduce_only: bool = Field(
        False,
        description="If True, order only reduces an existing position",
    )
    client_order_id: str | None = Field(
        None,
        max_length=64,
        description="Custom client order ID for idempotency",
    )

    @field_validator("symbol")
    @classmethod
    def _uppercase_symbol(cls, v: str) -> str:
        return v.upper()

    @field_validator("price")
    @classmethod
    def _require_price_for_limit(cls, v: float | None, info: Any) -> float | None:
        order_type = info.data.get("order_type") if info.data else None
        if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and v is None:
            raise ValueError("price is required for LIMIT and STOP_LIMIT orders")
        return v

    @field_validator("stop_price")
    @classmethod
    def _require_stop_for_stop_orders(cls, v: float | None, info: Any) -> float | None:
        order_type = info.data.get("order_type") if info.data else None
        if order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT) and v is None:
            raise ValueError("stop_price is required for STOP_MARKET and STOP_LIMIT orders")
        return v


# ── Order Response ───────────────────────────────────────────


class OrderResponse(BaseModel):
    """Response from the exchange after placing/modifying an order."""

    order_id: str = Field(..., description="Exchange-generated order ID")
    client_order_id: str | None = Field(None, description="Client-supplied order ID")
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    executed_qty: float = 0.0
    avg_price: float | None = None
    status: OrderStatus
    leverage: int = 1
    reduce_only: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    raw_response: dict[str, Any] | None = Field(
        None, description="Full exchange response for audit trail"
    )


class OrderListResponse(BaseModel):
    """Paginated list of orders."""

    orders: list[OrderResponse]
    total: int
    page: int
    size: int


# ── Balance ───────────────────────────────────────────────────


class WalletBalance(BaseModel):
    """Futures wallet balance information."""

    asset: str = Field(..., description="Asset symbol (e.g. INR)")
    wallet_balance: float = 0.0
    available_balance: float = 0.0
    used_margin: float = 0.0
    unrealized_pnl: float = 0.0


class AccountBalanceResponse(BaseModel):
    """Full account balance response."""

    balances: list[WalletBalance]
    total_equity: float = 0.0
    total_used_margin: float = 0.0
    total_available: float = 0.0
    total_unrealized_pnl: float = 0.0


# ── Position ─────────────────────────────────────────────────


class PositionResponse(BaseModel):
    """Open position information."""

    symbol: str
    side: PositionSide
    entry_price: float
    mark_price: float | None = None
    current_price: float | None = None
    quantity: float
    leverage: int = 1
    unrealized_pnl: float = 0.0
    unrealized_pnl_percent: float = 0.0
    realized_pnl: float = 0.0
    liquidation_price: float | None = None
    margin_used: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    exchange_position_id: str | None = None
    updated_at: datetime | None = None


class PositionListResponse(BaseModel):
    """List of open positions."""

    positions: list[PositionResponse]
    total: int


# ── Trade Record ──────────────────────────────────────────────


class TradeRecordResponse(BaseModel):
    """A completed trade / fill record."""

    id: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
    fees: float | None = None
    status: str
    exchange_order_id: str | None = None
    created_at: datetime | None = None
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}