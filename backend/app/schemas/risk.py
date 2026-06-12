"""Pydantic schemas for Risk Management – request/response validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Risk Settings
# ---------------------------------------------------------------------------


class RiskSettingsResponse(BaseModel):
    """Current risk-management configuration for the authenticated user."""

    daily_loss_limit: float = Field(..., description="Max allowed daily realized loss (INR)")
    weekly_loss_limit: float = Field(..., description="Max allowed weekly realized loss (INR)")
    max_drawdown_percent: float = Field(..., description="Max unrealised drawdown % before forced closure")
    max_open_trades: int = Field(..., ge=1, description="Maximum concurrent open positions")
    position_size_percent: float = Field(..., ge=0.1, le=100.0, description="Max position size as % of equity")
    max_leverage: int = Field(..., ge=1, le=125, description="Maximum allowed leverage")
    stop_loss_percent: float = Field(..., ge=0.0, description="Default stop-loss %")
    take_profit_percent: float = Field(..., ge=0.0, description="Default take-profit %")
    trailing_stop_enabled: bool = Field(False, description="Whether trailing stop is active")
    trailing_stop_distance_percent: float = Field(0.0, ge=0.0, description="Trailing stop distance % from peak")
    risk_per_trade_percent: float = Field(..., ge=0.1, le=100.0, description="Max risk per trade as % of equity")
    kill_switch_enabled: bool = Field(False, description="Emergency kill-switch state")
    kill_switch_reason: str | None = Field(None, description="Reason the kill-switch was activated")
    trading_enabled: bool = Field(True, description="Whether automated trading is enabled")

    model_config = {"from_attributes": True}


class RiskSettingsUpdate(BaseModel):
    """Partial update payload for risk settings.  All fields optional."""

    daily_loss_limit: float | None = Field(None, gt=0)
    weekly_loss_limit: float | None = Field(None, gt=0)
    max_drawdown_percent: float | None = Field(None, ge=0.0, le=100.0)
    max_open_trades: int | None = Field(None, ge=1)
    position_size_percent: float | None = Field(None, ge=0.1, le=100.0)
    max_leverage: int | None = Field(None, ge=1, le=125)
    stop_loss_percent: float | None = Field(None, ge=0.0)
    take_profit_percent: float | None = Field(None, ge=0.0)
    trailing_stop_enabled: bool | None = None
    trailing_stop_distance_percent: float | None = Field(None, ge=0.0)
    risk_per_trade_percent: float | None = Field(None, ge=0.1, le=100.0)
    trading_enabled: bool | None = None


# ---------------------------------------------------------------------------
# Risk Check (pre-order validation)
# ---------------------------------------------------------------------------


class RiskCheckRequest(BaseModel):
    """Payload submitted before an order is executed to evaluate risk limits."""

    symbol: str = Field(..., min_length=1, description="Trading symbol e.g. BTCINR")
    quantity: Decimal = Field(..., gt=0, description="Order quantity")
    leverage: int = Field(..., ge=1, le=125)
    price: float | None = Field(None, gt=0, description="Limit price (optional for market orders)")


class RiskCheckResponse(BaseModel):
    """Result of a pre-order risk evaluation."""

    allowed: bool
    reason: str | None = Field(None, description="Human-readable reason when rejected")
    daily_pnl: float = Field(0.0, description="Today's realised PnL at time of check")
    daily_loss_limit: float = Field(0.0)
    open_trades: int = Field(0, description="Current open position count")
    max_open_trades: int = Field(0)


# ---------------------------------------------------------------------------
# Kill Switch
# ---------------------------------------------------------------------------


class KillSwitchRequest(BaseModel):
    """Activate or deactivate the emergency kill-switch."""

    enabled: bool = Field(..., description="True = engage kill-switch (close all); False = disengage")
    reason: str | None = Field(None, description="Reason for engaging / disengaging")


class KillSwitchResponse(BaseModel):
    """Confirmation after a kill-switch toggle."""

    kill_switch_enabled: bool
    message: str
    positions_closed: int = Field(0, description="Number of positions liquidated by this action")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Risk Status (dashboard snapshot)
# ---------------------------------------------------------------------------


class TrailingStopStatus(BaseModel):
    """Per-position trailing-stop snapshot."""

    position_id: int
    symbol: str
    side: str  # LONG / SHORT
    entry_price: float
    current_price: float
    peak_price: float  # highest seen for LONG, lowest for SHORT
    drawdown_from_peak_percent: float
    trailing_stop_distance_percent: float
    trailing_stop_triggered: bool


class RiskStatusResponse(BaseModel):
    """Real-time risk snapshot for the dashboard."""

    daily_pnl: float = Field(..., description="Today's realised PnL")
    daily_loss_limit: float
    daily_loss_used_percent: float = Field(..., description="0-100 % of daily limit consumed")
    unrealized_pnl: float = Field(..., description="Sum of unrealized PnL across all open positions")
    max_drawdown_percent: float
    current_drawdown_percent: float = Field(0.0, description="Current drawdown % relative to peak equity")
    open_positions: int
    max_open_trades: int
    kill_switch_enabled: bool
    trading_enabled: bool
    trailing_stops: list[TrailingStopStatus] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)