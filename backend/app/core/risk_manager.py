"""Risk Manager – continuous risk enforcement and protection rules.

Responsibilities
----------------
* Pre-order risk checks (daily loss, open-trade count, position size vs equity).
* Daily loss counter stored in Redis with midnight-UTC expiry.
* Trailing-stop evaluation: track peak price per position; close if price
  retreats by ``trailing_stop_distance_percent``.
* Max-drawdown monitoring: close all positions when unrealised drawdown
  exceeds the configured threshold.
* Emergency kill-switch: close everything and disable trading.
* All emergency closures are audit-logged and broadcast via WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings
from app.db.base import async_session
from app.models.log import Log
from app.models.position import Position
from app.models.risk_setting import RiskSetting
from app.models.trade import Trade
from app.schemas.order import ManualOrderRequest
from app.schemas.risk import RiskCheckRequest, RiskCheckResponse, RiskStatusResponse, TrailingStopStatus
from app.websocket.manager import ConnectionManager, get_ws_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------


def _daily_loss_key(user_id: int) -> str:
    """Redis key for today's realised loss counter (resets at midnight UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"risk:daily_loss:{user_id}:{today}"


def _peak_equity_key(user_id: int) -> str:
    return f"risk:peak_equity:{user_id}"


def _trailing_peak_key(position_id: int) -> str:
    return f"risk:trailing_peak:{position_id}"


def _seconds_until_midnight_utc() -> int:
    """Return seconds remaining until the next midnight UTC."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------


class RiskManager:
    """Singleton that enforces risk limits and monitors positions continuously."""

    def __init__(self, redis: aioredis.Redis | None = None, ws_manager: ConnectionManager | None = None) -> None:
        self._redis: aioredis.Redis | None = redis
        self._ws: ConnectionManager | None = ws_manager

    # -- helpers ----------------------------------------------------------

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            settings = get_settings()
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=False)
        return self._redis

    def _get_ws(self) -> ConnectionManager:
        if self._ws is None:
            self._ws = get_ws_manager()
        return self._ws

    # -- daily loss counter (Redis) --------------------------------------

    async def add_daily_loss(self, user_id: int, loss_amount: float) -> None:
        """Increment the daily realised-loss counter.  Expires at midnight UTC."""
        if loss_amount <= 0:
            return  # only track losses
        r = await self._get_redis()
        key = _daily_loss_key(user_id)
        await r.incrbyfloat(key, loss_amount)
        ttl = _seconds_until_midnight_utc()
        await r.expire(key, ttl)

    async def get_daily_loss(self, user_id: int) -> float:
        """Return today's realised loss from Redis.  Falls back to DB on miss."""
        r = await self._get_redis()
        key = _daily_loss_key(user_id)
        val = await r.get(key)
        if val is not None:
            return float(val)

        # Cache miss – compute from DB and seed Redis
        db_loss = await self._compute_daily_pnl_from_db(user_id)
        if db_loss < 0:
            await r.set(key, str(abs(db_loss)), ex=_seconds_until_midnight_utc())
            return abs(db_loss)
        return 0.0

    async def _compute_daily_pnl_from_db(self, user_id: int) -> float:
        """Sum today's realised PnL from the ``trades`` table."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with async_session() as db:
            from sqlalchemy import select, func as sqlfunc

            stmt = select(sqlfunc.coalesce(sqlfunc.sum(Trade.pnl), 0.0)).where(
                Trade.user_id == user_id,
                Trade.created_at >= today_start,
            )
            result = await db.execute(stmt)
            return float(result.scalar() or 0.0)

    # -- peak equity (drawdown tracking) ---------------------------------

    async def _get_peak_equity(self, user_id: int) -> float:
        r = await self._get_redis()
        val = await r.get(_peak_equity_key(user_id))
        return float(val) if val else 0.0

    async def _set_peak_equity(self, user_id: int, equity: float) -> None:
        r = await self._get_redis()
        await r.set(_peak_equity_key(user_id), str(equity))

    # -- pre-order check -------------------------------------------------

    async def check_order(self, user_id: int, request: RiskCheckRequest) -> RiskCheckResponse:
        """Evaluate whether a new order would violate any risk limit.

        Called **before** the order is placed on the exchange.
        """
        async with async_session() as db:
            from sqlalchemy import select

            # 1. Load risk settings
            rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
            rs_result = await db.execute(rs_stmt)
            risk: RiskSetting | None = rs_result.scalar_one_or_none()

            if risk is None:
                return RiskCheckResponse(allowed=False, reason="No risk settings configured.")

            # 2. Kill-switch
            if risk.kill_switch_enabled:
                return RiskCheckResponse(
                    allowed=False,
                    reason=f"Kill-switch active: {risk.kill_switch_reason or 'No reason given'}",
                    daily_loss_limit=float(risk.daily_loss_limit),
                    max_open_trades=risk.max_open_trades,
                )

            # 3. Trading disabled
            if not risk.trading_enabled:
                return RiskCheckResponse(
                    allowed=False,
                    reason="Trading is disabled.",
                    daily_loss_limit=float(risk.daily_loss_limit),
                    max_open_trades=risk.max_open_trades,
                )

            # 4. Daily loss limit
            daily_loss = await self.get_daily_loss(user_id)
            daily_pnl = await self._compute_daily_pnl_from_db(user_id)
            if daily_loss >= float(risk.daily_loss_limit):
                return RiskCheckResponse(
                    allowed=False,
                    reason=f"Daily loss limit reached: {daily_loss:.2f} >= {risk.daily_loss_limit:.2f}",
                    daily_pnl=daily_pnl,
                    daily_loss_limit=float(risk.daily_loss_limit),
                    open_trades=0,
                    max_open_trades=risk.max_open_trades,
                )

            # 5. Max open trades
            pos_stmt = select(Position).where(
                Position.user_id == user_id,
                Position.status == "OPEN",
            )
            pos_result = await db.execute(pos_stmt)
            open_positions = pos_result.scalars().all()
            open_count = len(open_positions)

            if open_count >= risk.max_open_trades:
                return RiskCheckResponse(
                    allowed=False,
                    reason=f"Max open trades reached: {open_count} >= {risk.max_open_trades}",
                    daily_pnl=daily_pnl,
                    daily_loss_limit=float(risk.daily_loss_limit),
                    open_trades=open_count,
                    max_open_trades=risk.max_open_trades,
                )

            # 6. Position size limit
            if risk.risk_per_trade_percent > 0:
                total_margin = sum(float(p.margin_used or 0) for p in open_positions)
                unrealised_pnl = sum(float(p.unrealized_pnl or 0) for p in open_positions)
                total_equity = total_margin + unrealised_pnl

                if total_equity > 0:
                    notional = float(request.quantity) * (request.price if request.price else 1.0)
                    max_notional = float(risk.risk_per_trade_percent) / 100.0 * total_equity
                    if notional > max_notional:
                        return RiskCheckResponse(
                            allowed=False,
                            reason=f"Position size exceeds limit: {notional:.2f} > {max_notional:.2f}",
                            daily_pnl=daily_pnl,
                            daily_loss_limit=float(risk.daily_loss_limit),
                            open_trades=open_count,
                            max_open_trades=risk.max_open_trades,
                        )

        return RiskCheckResponse(
            allowed=True,
            daily_pnl=daily_pnl,
            daily_loss_limit=float(risk.daily_loss_limit),
            open_trades=open_count,
            max_open_trades=risk.max_open_trades,
        )

    # -- trailing stop ---------------------------------------------------

    async def _get_trailing_peak(self, position_id: int) -> float | None:
        r = await self._get_redis()
        val = await r.get(_trailing_peak_key(position_id))
        return float(val) if val else None

    async def _set_trailing_peak(self, position_id: int, price: float) -> None:
        r = await self._get_redis()
        await r.set(_trailing_peak_key(position_id), str(price))

    async def evaluate_trailing_stops(self) -> list[dict[str, Any]]:
        """Check every open position for trailing-stop triggers.

        Returns a list of positions that should be closed.
        """
        triggered: list[dict[str, Any]] = []

        async with async_session() as db:
            from sqlalchemy import select

            pos_stmt = select(Position).where(Position.status == "OPEN")
            result = await db.execute(pos_stmt)
            positions: list[Position] = list(result.scalars().all())

            for pos in positions:
                # Load risk settings for this user
                rs_stmt = select(RiskSetting).where(RiskSetting.user_id == pos.user_id)
                rs_result = await db.execute(rs_stmt)
                risk: RiskSetting | None = rs_result.scalar_one_or_none()

                if risk is None or not risk.trailing_stop_enabled:
                    continue

                current_price = float(pos.current_price or pos.mark_price or 0)
                if current_price <= 0:
                    continue

                distance_pct = float(risk.trailing_stop_distance_percent)

                # Get or initialise peak
                peak = await self._get_trailing_peak(pos.id)
                if peak is None:
                    peak = float(pos.entry_price)
                    await self._set_trailing_peak(pos.id, peak)

                if pos.side == "LONG":
                    # Update peak if price moved higher
                    if current_price > peak:
                        peak = current_price
                        await self._set_trailing_peak(pos.id, peak)

                    # Trigger if price dropped below peak by distance_pct
                    trigger_price = peak * (1.0 - distance_pct / 100.0)
                    if current_price <= trigger_price:
                        triggered.append({
                            "position_id": pos.id,
                            "user_id": pos.user_id,
                            "symbol": pos.symbol,
                            "side": pos.side,
                            "entry_price": float(pos.entry_price),
                            "peak_price": peak,
                            "current_price": current_price,
                            "trigger_price": trigger_price,
                            "reason": f"Trailing stop triggered: {current_price:.2f} <= {trigger_price:.2f}",
                        })

                elif pos.side == "SHORT":
                    # Update peak (lowest price) if price moved lower
                    if current_price < peak:
                        peak = current_price
                        await self._set_trailing_peak(pos.id, peak)

                    # Trigger if price rose above peak by distance_pct
                    trigger_price = peak * (1.0 + distance_pct / 100.0)
                    if current_price >= trigger_price:
                        triggered.append({
                            "position_id": pos.id,
                            "user_id": pos.user_id,
                            "symbol": pos.symbol,
                            "side": pos.side,
                            "entry_price": float(pos.entry_price),
                            "peak_price": peak,
                            "current_price": current_price,
                            "trigger_price": trigger_price,
                            "reason": f"Trailing stop triggered: {current_price:.2f} >= {trigger_price:.2f}",
                        })

        return triggered

    # -- drawdown check --------------------------------------------------

    async def check_drawdown(self) -> list[dict[str, Any]]:
        """Check all users for max-drawdown violations.

        Returns a list of users whose drawdown exceeds the threshold.
        """
        violations: list[dict[str, Any]] = []

        async with async_session() as db:
            from sqlalchemy import select

            # Load all risk settings
            rs_stmt = select(RiskSetting)
            rs_result = await db.execute(rs_stmt)
            all_settings: list[RiskSetting] = list(rs_result.scalars().all())

            for risk in all_settings:
                if risk.max_drawdown_percent is None or float(risk.max_drawdown_percent) <= 0:
                    continue

                # Compute current equity = balance + unrealised PnL
                pos_stmt = select(Position).where(
                    Position.user_id == risk.user_id,
                    Position.status == "OPEN",
                )
                pos_result = await db.execute(pos_stmt)
                positions: list[Position] = list(pos_result.scalars().all())

                unrealised_pnl = sum(float(p.unrealized_pnl or 0) for p in positions)

                # Compute total equity from positions: margin_used + unrealised_pnl.
                # This avoids an exchange API call in the monitor loop.
                total_margin = sum(float(p.margin_used or 0) for p in positions)
                total_equity = total_margin + unrealised_pnl
                if total_equity <= 0:
                    continue

                # Track peak equity
                peak = await self._get_peak_equity(risk.user_id)
                if peak == 0 or total_equity > peak:
                    peak = total_equity
                    await self._set_peak_equity(risk.user_id, peak)

                if peak <= 0:
                    continue

                drawdown_pct = ((peak - total_equity) / peak) * 100.0
                if drawdown_pct >= float(risk.max_drawdown_percent):
                    violations.append({
                        "user_id": risk.user_id,
                        "peak_equity": peak,
                        "current_equity": total_equity,
                        "drawdown_percent": drawdown_pct,
                        "max_drawdown_percent": float(risk.max_drawdown_percent),
                        "reason": (
                            f"Max drawdown exceeded: {drawdown_pct:.2f}% >= "
                            f"{risk.max_drawdown_percent:.2f}%"
                        ),
                    })

        return violations

    async def close_all_positions(self, user_id: int) -> int:
        """Emergency close all open positions for a user.

        Returns the number of positions marked for closure.
        """
        closed_count = 0
        async with async_session() as db:
            from sqlalchemy import select

            pos_stmt = select(Position).where(
                Position.user_id == user_id,
                Position.status == "OPEN",
            )
            result = await db.execute(pos_stmt)
            positions: list[Position] = list(result.scalars().all())

            for pos in positions:
                pos.status = "CLOSING"
                db.add(pos)
                closed_count += 1

            await db.commit()

        return closed_count

    # -- kill switch -----------------------------------------------------

    async def activate_kill_switch(self, user_id: int, reason: str) -> dict[str, Any]:
        """Engage the emergency kill-switch: close all positions, disable trading."""
        async with async_session() as db:
            from sqlalchemy import select

            rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
            rs_result = await db.execute(rs_stmt)
            risk: RiskSetting | None = rs_result.scalar_one_or_none()

            if risk is None:
                return {"success": False, "message": "No risk settings found."}

            risk.kill_switch_enabled = True
            risk.kill_switch_reason = reason
            risk.trading_enabled = False
            db.add(risk)
            await db.commit()

        positions_closed = await self.close_all_positions(user_id)

        # Audit log
        await self._log_event(
            user_id=user_id,
            level="CRITICAL",
            message=f"KILL SWITCH ENGAGED: {reason}",
            category="risk",
            metadata={
                "action": "kill_switch_activated",
                "reason": reason,
                "positions_closed": positions_closed,
            },
        )

        # WebSocket notification
        try:
            ws = self._get_ws()
            await ws.broadcast(
                "risk_alert",
                {
                    "type": "kill_switch_activated",
                    "user_id": user_id,
                    "reason": reason,
                    "positions_closed": positions_closed,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            logger.exception("Failed to broadcast kill-switch via WebSocket")

        return {
            "success": True,
            "message": f"Kill-switch engaged. {positions_closed} position(s) marked for closure.",
            "positions_closed": positions_closed,
        }

    async def deactivate_kill_switch(self, user_id: int) -> dict[str, Any]:
        """Disengage the kill-switch and re-enable trading."""
        async with async_session() as db:
            from sqlalchemy import select

            rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
            rs_result = await db.execute(rs_stmt)
            risk: RiskSetting | None = rs_result.scalar_one_or_none()

            if risk is None:
                return {"success": False, "message": "No risk settings found."}

            risk.kill_switch_enabled = False
            risk.kill_switch_reason = None
            risk.trading_enabled = True
            db.add(risk)
            await db.commit()

        await self._log_event(
            user_id=user_id,
            level="INFO",
            message="Kill-switch disengaged",
            category="risk",
            metadata={"action": "kill_switch_deactivated"},
        )

        return {"success": True, "message": "Kill-switch disengaged. Trading re-enabled."}

    # -- status snapshot -------------------------------------------------

    async def get_status(self, user_id: int) -> RiskStatusResponse:
        """Build a comprehensive risk snapshot for the dashboard."""
        async with async_session() as db:
            from sqlalchemy import select

            rs_stmt = select(RiskSetting).where(RiskSetting.user_id == user_id)
            rs_result = await db.execute(rs_stmt)
            risk: RiskSetting | None = rs_result.scalar_one_or_none()

            if risk is None:
                return RiskStatusResponse(
                    daily_pnl=0.0,
                    daily_loss_limit=0.0,
                    daily_loss_used_percent=0.0,
                    unrealized_pnl=0.0,
                    max_drawdown_percent=0.0,
                    current_drawdown_percent=0.0,
                    open_positions=0,
                    max_open_trades=0,
                    kill_switch_enabled=False,
                    trading_enabled=False,
                )

            daily_pnl = await self._compute_daily_pnl_from_db(user_id)
            daily_loss = await self.get_daily_loss(user_id)

            daily_limit = float(risk.daily_loss_limit)
            daily_used = (daily_loss / daily_limit * 100.0) if daily_limit > 0 else 0.0

            pos_stmt = select(Position).where(
                Position.user_id == user_id,
                Position.status == "OPEN",
            )
            pos_result = await db.execute(pos_stmt)
            positions: list[Position] = list(pos_result.scalars().all())

            unrealised_pnl = sum(float(p.unrealized_pnl or 0) for p in positions)

            peak = await self._get_peak_equity(user_id)
            # Compute total equity from positions: margin_used + unrealised_pnl.
            total_margin = sum(float(p.margin_used or 0) for p in positions)
            total_equity = total_margin + unrealised_pnl

            if peak == 0 or total_equity > peak:
                peak = total_equity
                await self._set_peak_equity(user_id, peak)

            drawdown_pct = ((peak - total_equity) / peak * 100.0) if peak > 0 else 0.0

            # Trailing-stop statuses
            trailing_stops: list[TrailingStopStatus] = []
            for pos in positions:
                if not risk.trailing_stop_enabled:
                    continue
                peak_price = await self._get_trailing_peak(pos.id)
                if peak_price is None:
                    peak_price = float(pos.entry_price)
                current_price = float(pos.current_price or pos.mark_price or 0)
                if current_price <= 0:
                    continue

                if pos.side == "LONG":
                    dd_from_peak = (peak_price - current_price) / peak_price * 100.0
                    triggered = dd_from_peak >= float(risk.trailing_stop_distance_percent)
                else:
                    dd_from_peak = (current_price - peak_price) / peak_price * 100.0
                    triggered = dd_from_peak >= float(risk.trailing_stop_distance_percent)

                trailing_stops.append(
                    TrailingStopStatus(
                        position_id=pos.id,
                        symbol=pos.symbol,
                        side=pos.side,
                        entry_price=float(pos.entry_price),
                        current_price=current_price,
                        peak_price=peak_price,
                        drawdown_from_peak_percent=round(dd_from_peak, 4),
                        trailing_stop_distance_percent=float(risk.trailing_stop_distance_percent),
                        trailing_stop_triggered=triggered,
                    )
                )

        return RiskStatusResponse(
            daily_pnl=daily_pnl,
            daily_loss_limit=daily_limit,
            daily_loss_used_percent=round(daily_used, 2),
            unrealized_pnl=round(unrealised_pnl, 2),
            max_drawdown_percent=float(risk.max_drawdown_percent),
            current_drawdown_percent=round(drawdown_pct, 4),
            open_positions=len(positions),
            max_open_trades=risk.max_open_trades,
            kill_switch_enabled=risk.kill_switch_enabled,
            trading_enabled=risk.trading_enabled,
            trailing_stops=trailing_stops,
        )

    # -- audit logging ---------------------------------------------------

    async def _log_event(
        self,
        user_id: int,
        level: str,
        message: str,
        category: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a risk-related event to the audit log."""
        try:
            async with async_session() as db:
                log_entry = Log(
                    user_id=user_id,
                    level=level,
                    message=message,
                    category=category,
                    metadata_=metadata or {},
                )
                db.add(log_entry)
                await db.commit()
        except Exception:
            logger.exception("Failed to write risk audit log")

    # -- periodic monitor (called by Celery task) ------------------------

    async def run_monitor_cycle(self) -> dict[str, Any]:
        """Single monitoring cycle: eval trailing stops + drawdown.

        Called every 5 seconds by the Celery periodic task.
        Returns a summary of actions taken.
        """
        result: dict[str, Any] = {
            "trailing_stops_triggered": 0,
            "drawdown_violations": 0,
            "positions_closed": 0,
            "details": [],
        }

        # 1. Evaluate trailing stops
        trailing_triggers = await self.evaluate_trailing_stops()
        for trigger in trailing_triggers:
            await self._log_event(
                user_id=trigger["user_id"],
                level="WARNING",
                message=trigger["reason"],
                category="risk",
                metadata={"action": "trailing_stop_triggered", **trigger},
            )
            try:
                ws = self._get_ws()
                await ws.broadcast(
                    "risk_alert",
                    {
                        "type": "trailing_stop_triggered",
                        **trigger,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception:
                logger.exception("Failed to broadcast trailing-stop alert")

            # Mark position for closure
            async with async_session() as db:
                from sqlalchemy import select

                pos_stmt = select(Position).where(Position.id == trigger["position_id"])
                pos_result = await db.execute(pos_stmt)
                pos: Position | None = pos_result.scalar_one_or_none()
                if pos and pos.status == "OPEN":
                    pos.status = "CLOSING"
                    db.add(pos)
                    await db.commit()
                    result["positions_closed"] += 1

            result["trailing_stops_triggered"] += 1
            result["details"].append(trigger)

        # 2. Evaluate drawdown
        drawdown_violations = await self.check_drawdown()
        for violation in drawdown_violations:
            uid = violation["user_id"]
            await self._log_event(
                user_id=uid,
                level="CRITICAL",
                message=violation["reason"],
                category="risk",
                metadata={"action": "drawdown_violation", **violation},
            )
            # Auto-engage kill-switch on drawdown violation
            await self.activate_kill_switch(uid, violation["reason"])
            result["drawdown_violations"] += 1
            result["details"].append(violation)

        return result


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_risk_manager: RiskManager | None = None


def get_risk_manager() -> RiskManager:
    """Return the module-level RiskManager singleton."""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager