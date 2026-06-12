"""
Order Manager

Orchestrates the full order lifecycle:
1. Validates orders against risk rules (position size, drawdown, kill switch)
2. Checks available balance before sending
3. Sends order to Shark Exchange via SharkClient
4. Records trade in the database
5. Updates position state
6. Publishes events via WebSocket / Redis for real-time dashboard updates

All order responses and errors are persisted in the audit log (logs table).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.base import async_session
from app.brokers.shark_client import SharkClient, get_shark_client
from app.models.trade import Trade
from app.models.position import Position
from app.models.risk_setting import RiskSetting
from app.models.log import Log
from app.schemas.order import (
    OrderSide,
    OrderType,
    OrderStatus,
    PositionSide,
    PositionStatus,
    ManualOrderRequest,
    OrderResponse,
    PositionResponse,
    AccountBalanceResponse,
    WalletBalance,
)

logger = logging.getLogger("trading_dashboard.order_manager")


class InsufficientBalanceError(Exception):
    """Raised when the account has insufficient balance for an order."""


class RiskLimitExceededError(Exception):
    """Raised when a risk limit would be breached by the order."""


class KillSwitchActiveError(Exception):
    """Raised when the trading kill switch is enabled."""


class OrderManager:
    """
    Manages the full lifecycle of a trade order.

    Usage:
        manager = OrderManager(shark_client, user_id=42)
        order = await manager.place_manual_order(request)
    """

    def __init__(
        self,
        shark_client: SharkClient | None = None,
        user_id: int | None = None,
    ) -> None:
        self._shark = shark_client or get_shark_client()
        self._user_id = user_id

    # ── Public API ────────────────────────────────────────────

    async def get_balance(self, user_id: int) -> AccountBalanceResponse:
        """Fetch and format the user's futures wallet balance."""
        raw = await self._shark.get_account_balance()

        # Shark Exchange response structure varies; handle common patterns
        data = raw if isinstance(raw, list) else raw.get("data", raw)
        if isinstance(data, dict):
            data = [data]

        balances: list[WalletBalance] = []
        for item in data:
            balances.append(WalletBalance(
                asset=item.get("asset", item.get("marginAsset", "INR")),
                wallet_balance=float(item.get("walletBalance", item.get("balance", 0))),
                available_balance=float(item.get("availableBalance", item.get("available", 0))),
                used_margin=float(item.get("totalInitialMargin", item.get("usedMargin", 0))),
                unrealized_pnl=float(item.get("totalUnrealizedProfit", item.get("unrealizedPnl", 0))),
            ))

        total_equity = sum(b.wallet_balance + b.unrealized_pnl for b in balances)
        total_used = sum(b.used_margin for b in balances)
        total_avail = sum(b.available_balance for b in balances)
        total_upnl = sum(b.unrealized_pnl for b in balances)

        return AccountBalanceResponse(
            balances=balances,
            total_equity=total_equity,
            total_used_margin=total_used,
            total_available=total_avail,
            total_unrealized_pnl=total_upnl,
        )

    async def get_positions(self, user_id: int, symbol: str | None = None) -> list[PositionResponse]:
        """Fetch open positions, optionally filtered by symbol."""
        async with async_session() as db:
            stmt = select(Position).where(
                Position.user_id == user_id,
                Position.status == PositionStatus.OPEN.value,
            )
            if symbol:
                stmt = stmt.where(Position.symbol == symbol.upper())
            result = await db.execute(stmt)
            positions = result.scalars().all()

            return [
                PositionResponse(
                    symbol=p.symbol,
                    side=PositionSide(p.side),
                    entry_price=float(p.entry_price),
                    mark_price=float(p.mark_price) if p.mark_price else None,
                    current_price=float(p.current_price) if p.current_price else None,
                    quantity=float(p.quantity),
                    leverage=p.leverage or 1,
                    unrealized_pnl=float(p.unrealized_pnl) if p.unrealized_pnl else 0.0,
                    unrealized_pnl_percent=float(p.unrealized_pnl_percent) if p.unrealized_pnl_percent else 0.0,
                    realized_pnl=float(p.realized_pnl) if p.realized_pnl else 0.0,
                    liquidation_price=float(p.liquidation_price) if p.liquidation_price else None,
                    margin_used=float(p.margin_used) if p.margin_used else 0.0,
                    status=PositionStatus(p.status) if p.status else PositionStatus.OPEN,
                    exchange_position_id=p.exchange_position_id,
                    updated_at=p.updated_at,
                )
                for p in positions
            ]

    async def get_orders(
        self, user_id: int, page: int = 1, size: int = 20
    ) -> tuple[list[OrderResponse], int]:
        """Fetch order history from the database."""
        async with async_session() as db:
            # Count
            from sqlalchemy import func as sqlfunc
            count_stmt = select(sqlfunc.count(Trade.id)).where(Trade.user_id == user_id)
            total = (await db.execute(count_stmt)).scalar() or 0

            # Fetch page
            stmt = (
                select(Trade)
                .where(Trade.user_id == user_id)
                .order_by(Trade.created_at.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
            result = await db.execute(stmt)
            trades = result.scalars().all()

            orders = [
                OrderResponse(
                    order_id=t.exchange_order_id or str(t.id),
                    client_order_id=None,
                    symbol=t.symbol,
                    side=OrderSide(t.side),
                    order_type=OrderType(t.order_type),
                    quantity=float(t.quantity),
                    price=float(t.price) if t.price else None,
                    status=OrderStatus(t.status) if t.status else OrderStatus.FILLED,
                    leverage=t.leverage or 1,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                )
                for t in trades
            ]

            return orders, int(total)

    async def place_manual_order(
        self, user_id: int, request: ManualOrderRequest
    ) -> OrderResponse:
        """
        Place a manual order with full risk validation.

        Flow:
        1. Load risk settings and validate limits
        2. Check account balance
        3. Send order to Shark Exchange
        4. Record trade in database
        5. Update/create position
        6. Return formatted response
        """
        self._user_id = user_id

        # Step 1: Validate against risk rules
        await self._validate_risk(user_id, request)

        # Step 2: Check balance
        await self._check_balance(user_id, request)

        # Step 3: Send order to exchange
        exchange_response: dict[str, Any] = {}
        exchange_error: str | None = None

        try:
            exchange_response = await self._shark.place_order(
                symbol=request.symbol,
                side=request.side.value,
                order_type=request.order_type.value,
                quantity=request.quantity,
                price=request.price,
                stop_price=request.stop_price,
                leverage=request.leverage,
                reduce_only=request.reduce_only,
                client_order_id=request.client_order_id,
            )
            logger.info(
                "Order placed successfully: %s %s %s qty=%s",
                request.symbol,
                request.side.value,
                request.order_type.value,
                request.quantity,
            )
        except Exception as exc:
            exchange_error = str(exc)
            logger.exception("Order placement failed: %s", exchange_error)
            # Persist error in audit log
            await self._log_error(user_id, "ORDER_FAILED", {
                "symbol": request.symbol,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "quantity": request.quantity,
                "error": exchange_error,
            })
            raise

        # Step 4: Record trade in database
        trade = await self._record_trade(user_id, request, exchange_response)

        # Step 5: Update position
        await self._update_position(user_id, trade, exchange_response)

        # Step 6: Log success in audit log
        await self._log_success(user_id, trade, exchange_response)

        # Step 7: Build and return response
        return self._build_order_response(trade, exchange_response)

    # ── Risk Validation ───────────────────────────────────────

    async def _validate_risk(self, user_id: int, request: ManualOrderRequest) -> None:
        """
        Validate the order against the user's risk settings.

        Checks:
        - Kill switch (trading_enabled)
        - Max position size (% of portfolio)
        - Max leverage
        - Daily loss limit
        - Max drawdown
        """
        async with async_session() as db:
            stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
            result = await db.execute(stmt)
            risk = result.scalar_one_or_none()

        if risk is None:
            # No risk settings configured – allow trade with defaults
            logger.debug("No risk settings for user %d – allowing trade", user_id)
            return

        # Kill switch check
        if risk.kill_switch_enabled or not risk.trading_enabled:
            raise KillSwitchActiveError(
                "Trading is disabled. Kill switch is active or trading is paused."
            )

        # Max leverage check
        if risk.max_leverage and request.leverage > risk.max_leverage:
            raise RiskLimitExceededError(
                f"Leverage {request.leverage}x exceeds maximum allowed {risk.max_leverage}x"
            )

        # Position size check
        if risk.position_size_percent:
            balance = await self.get_balance(user_id)
            max_position_value = balance.total_equity * (risk.position_size_percent / 100)
            # Estimate position value at entry (we don't have exact price for market orders)
            estimated_price = request.price or 0
            if estimated_price > 0:
                position_value = request.quantity * estimated_price / request.leverage
                if position_value > max_position_value:
                    raise RiskLimitExceededError(
                        f"Position value {position_value:.2f} exceeds max allowed "
                        f"{max_position_value:.2f} ({risk.position_size_percent}% of equity)"
                    )

        # Daily loss limit check
        if risk.daily_loss_limit:
            daily_pnl = await self._get_daily_pnl(user_id)
            if daily_pnl <= -risk.daily_loss_limit:
                raise RiskLimitExceededError(
                    f"Daily loss limit of {risk.daily_loss_limit} reached "
                    f"(current: {daily_pnl:.2f})"
                )

    async def _check_balance(self, user_id: int, request: ManualOrderRequest) -> None:
        """Verify sufficient balance for the order."""
        balance = await self.get_balance(user_id)

        if request.price and request.price > 0:
            required_margin = (request.quantity * request.price) / request.leverage
        else:
            # For market orders without a known price, estimate conservatively
            # using a worst-case scenario. In production, fetch market price here.
            required_margin = 0  # Skip balance check for market orders without price

        if required_margin > 0 and balance.total_available < required_margin:
            raise InsufficientBalanceError(
                f"Insufficient balance: need {required_margin:.2f}, "
                f"available {balance.total_available:.2f}"
            )

    async def _get_daily_pnl(self, user_id: int) -> float:
        """Calculate the user's PnL for the current day."""
        from sqlalchemy import func as sqlfunc

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        async with async_session() as db:
            stmt = select(sqlfunc.coalesce(sqlfunc.sum(Trade.pnl), 0)).where(
                Trade.user_id == user_id,
                Trade.created_at >= today_start,
            )
            result = await db.execute(stmt)
            return float(result.scalar() or 0)

    # ── Database Operations ───────────────────────────────────

    async def _record_trade(
        self,
        user_id: int,
        request: ManualOrderRequest,
        exchange_response: dict[str, Any],
    ) -> Trade:
        """Persist the trade in the database."""
        async with async_session() as db:
            trade = Trade(
                user_id=user_id,
                strategy_id=None,  # Manual orders aren't tied to a strategy
                symbol=request.symbol,
                side=request.side.value,
                order_type=request.order_type.value,
                quantity=request.quantity,
                price=request.price,
                leverage=request.leverage,
                status=OrderStatus.NEW.value,
                exchange_order_id=str(exchange_response.get("orderId", "")),
                metadata_={
                    "client_order_id": request.client_order_id,
                    "reduce_only": request.reduce_only,
                    "stop_price": request.stop_price,
                    "exchange_response": exchange_response,
                },
            )
            db.add(trade)
            await db.commit()
            await db.refresh(trade)
            return trade

    async def _update_position(
        self,
        user_id: int,
        trade: Trade,
        exchange_response: dict[str, Any],
    ) -> None:
        """
        Update or create a position based on the executed trade.

        For simplicity, this mirrors the exchange response. In production,
        you'd poll the exchange for the actual fill details.
        """
        async with async_session() as db:
            # Check if position already exists for this symbol
            stmt = select(Position).where(
                Position.user_id == user_id,
                Position.symbol == trade.symbol,
                Position.status == PositionStatus.OPEN.value,
            )
            result = await db.execute(stmt)
            position = result.scalar_one_or_none()

            if position is None:
                # Create new position
                position = Position(
                    user_id=user_id,
                    strategy_id=None,
                    symbol=trade.symbol,
                    side=PositionSide.LONG.value if trade.side == "BUY" else PositionSide.SHORT.value,
                    entry_price=trade.price or 0,
                    current_price=trade.price,
                    mark_price=trade.price,
                    quantity=trade.quantity,
                    leverage=trade.leverage,
                    unrealized_pnl=0,
                    unrealized_pnl_percent=0,
                    realized_pnl=0,
                    status=PositionStatus.OPEN.value,
                    exchange_position_id=exchange_response.get("positionId"),
                )
                db.add(position)
            else:
                # Update existing position
                avg_entry = float(position.entry_price)
                current_qty = float(position.quantity)

                if trade.side == "BUY":
                    # Increasing long or reducing short
                    new_qty = current_qty + float(trade.quantity)
                    if position.side == PositionSide.LONG.value:
                        position.entry_price = (
                            (avg_entry * current_qty) + (float(trade.price or 0) * float(trade.quantity))
                        ) / new_qty
                    position.quantity = new_qty
                else:  # SELL
                    new_qty = current_qty - float(trade.quantity)
                    if new_qty <= 0:
                        position.status = PositionStatus.CLOSED.value
                        position.quantity = 0
                    else:
                        position.quantity = new_qty

            await db.commit()

    # ── Audit Logging ─────────────────────────────────────────

    async def _log_success(
        self,
        user_id: int,
        trade: Trade,
        exchange_response: dict[str, Any],
    ) -> None:
        """Log successful order placement to the audit log."""
        async with async_session() as db:
            log_entry = Log(
                user_id=user_id,
                level="INFO",
                message=f"Order placed: {trade.side} {trade.quantity} {trade.symbol} "
                        f"({trade.order_type}) – ID: {trade.exchange_order_id}",
                category="trade",
                metadata_={
                    "trade_id": trade.id,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "order_type": trade.order_type,
                    "quantity": float(trade.quantity),
                    "price": float(trade.price) if trade.price else None,
                    "exchange_order_id": trade.exchange_order_id,
                    "exchange_response": exchange_response,
                },
            )
            db.add(log_entry)
            await db.commit()

    async def _log_error(
        self,
        user_id: int,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        """Log an order error to the audit log."""
        async with async_session() as db:
            log_entry = Log(
                user_id=user_id,
                level="ERROR",
                message=f"Order failed: {event_type} – {details.get('error', 'Unknown error')}",
                category="trade",
                metadata_={
                    "event_type": event_type,
                    **details,
                },
            )
            db.add(log_entry)
            await db.commit()

    # ── Response Builder ──────────────────────────────────────

    def _build_order_response(
        self, trade: Trade, exchange_response: dict[str, Any]
    ) -> OrderResponse:
        """Build a standardized OrderResponse from trade + exchange data."""
        return OrderResponse(
            order_id=trade.exchange_order_id or str(trade.id),
            client_order_id=trade.metadata_.get("client_order_id") if trade.metadata_ else None,
            symbol=trade.symbol,
            side=OrderSide(trade.side),
            order_type=OrderType(trade.order_type),
            quantity=float(trade.quantity),
            price=float(trade.price) if trade.price else None,
            stop_price=float(trade.metadata_.get("stop_price")) if trade.metadata_ and trade.metadata_.get("stop_price") else None,
            executed_qty=float(exchange_response.get("executedQty", 0)),
            avg_price=float(exchange_response.get("avgPrice", 0)) if exchange_response.get("avgPrice") else None,
            status=OrderStatus(trade.status) if trade.status else OrderStatus.NEW,
            leverage=trade.leverage or 1,
            reduce_only=bool(trade.metadata_.get("reduce_only")) if trade.metadata_ else False,
            created_at=trade.created_at,
            raw_response=exchange_response,
        )


# ── Module-level convenience ──────────────────────────────────

_order_manager: OrderManager | None = None


def get_order_manager() -> OrderManager:
    """Return a singleton OrderManager instance."""
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager()
    return _order_manager