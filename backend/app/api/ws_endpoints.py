"""
FastAPI WebSocket endpoint for real-time dashboard updates.

Provides:
- ``/ws/{user_id}`` – main WebSocket endpoint (token auth via query param)
- Initial account snapshot (balance, positions, open orders)
- Streaming market price updates filtered to user's active strategy symbols
- Trade execution notifications
- PNL updates

Authentication:
  Pass the JWT access token as a query parameter:
  ``ws://localhost:8000/ws/42?token=eyJ...``

  The token is validated and the ``user_id`` in the URL path must match
  the ``user_id`` claim in the JWT.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.security import decode_token
from app.websocket.manager import ConnectionManager, get_ws_manager

logger = logging.getLogger("trading_dashboard.ws_endpoint")

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────


async def _get_user_active_symbols(user_id: int) -> set[str]:
    """Query the database for the user's active strategy symbols."""
    try:
        from app.db.base import async_session
        from app.models.strategy import Strategy
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(
                select(Strategy).where(
                    Strategy.user_id == user_id,
                    Strategy.is_active == True,  # noqa: E712
                )
            )
            strategies = result.scalars().all()

        symbols: set[str] = set()
        for s in strategies:
            definition = s.json_definition or {}
            for sym in definition.get("symbols", []):
                symbols.add(sym)
        return symbols
    except Exception:
        logger.exception("Failed to fetch active symbols for user=%d", user_id)
        return set()


async def _get_initial_snapshot(user_id: int) -> dict[str, Any]:
    """Build an initial account snapshot for the connecting client."""
    snapshot: dict[str, Any] = {
        "balance": None,
        "positions": [],
        "open_orders": [],
    }
    try:
        from app.core.order_manager import get_order_manager

        manager = get_order_manager()
        snapshot["balance"] = (await manager.get_balance(user_id)).model_dump()
        snapshot["positions"] = [
            p.model_dump() for p in await manager.get_positions(user_id)
        ]
        orders, _ = await manager.get_orders(user_id, page=1, size=20)
        snapshot["open_orders"] = [o.model_dump() for o in orders]
    except Exception:
        logger.exception("Failed to build initial snapshot for user=%d", user_id)
    return snapshot


# ── WebSocket Endpoint ────────────────────────────────────────────────


@router.websocket("/{user_id}")
async def ws_endpoint(
    websocket: WebSocket,
    user_id: int,
    token: str = Query(...),
) -> None:
    """Main WebSocket connection for real-time dashboard updates.

    Authenticates via JWT token in query string, then streams:
    - Initial account snapshot
    - Market price updates (filtered to user's active symbols)
    - Trade notifications
    - PNL updates
    """
    # ── Authenticate ──────────────────────────────────────────────
    payload = decode_token(token)
    if payload is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    if payload.get("type") != "access":
        await websocket.close(code=4001, reason="Token must be an access token")
        return

    token_user_id: int = payload.get("user_id", 0)
    if token_user_id != user_id:
        await websocket.close(code=4003, reason="User ID mismatch")
        return

    # ── Determine relevant symbols ────────────────────────────────
    symbols = await _get_user_active_symbols(user_id)
    if not symbols:
        # No active strategies – still connect but with empty filter
        symbols = set()

    # ── Register with ConnectionManager ────────────────────────────
    manager = get_ws_manager()
    await manager.connect(user_id, websocket, symbols)

    # ── Send initial snapshot ──────────────────────────────────────
    try:
        snapshot = await _get_initial_snapshot(user_id)
        await manager.send(user_id, {
            "type": "initial_snapshot",
            "data": snapshot,
        })
    except Exception:
        logger.exception("Failed to send initial snapshot to user=%d", user_id)

    # ── Main receive loop ──────────────────────────────────────────
    try:
        # Start the queue consumer
        await _run_consumer(manager, user_id, websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: user=%d", user_id)
    except Exception:
        logger.exception("WebSocket error for user=%d", user_id)
    finally:
        await manager.disconnect(user_id, websocket)


async def _run_consumer(
    manager: ConnectionManager,
    user_id: int,
    websocket: WebSocket,
) -> None:
    """Consume messages from the connection queue and send them,
    while also listening for client messages (pong, subscribe, etc.).
    """
    # Find the connection
    conns = manager._connections.get(user_id, [])
    conn = None
    for c in conns:
        if c.ws is websocket:
            conn = c
            break
    if conn is None:
        return

    async def sender() -> None:
        """Drain the outbound queue."""
        while True:
            msg = await conn.queue.get()
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_text(json.dumps(msg))
                    if msg.get("type") == "pong":
                        conn._last_pong = asyncio.get_event_loop().time()
            except Exception:
                break

    async def receiver() -> None:
        """Listen for client messages."""
        while True:
            try:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                msg_type = data.get("type", "")

                if msg_type == "pong":
                    conn._last_pong = asyncio.get_event_loop().time()
                elif msg_type == "subscribe":
                    new_symbols = set(data.get("symbols", []))
                    conn.symbols.update(new_symbols)
                    await manager.send(user_id, {
                        "type": "subscribed",
                        "symbols": sorted(conn.symbols),
                    })
                elif msg_type == "unsubscribe":
                    remove_symbols = set(data.get("symbols", []))
                    conn.symbols.difference_update(remove_symbols)
            except WebSocketDisconnect:
                break
            except Exception:
                break

    # Run sender and receiver concurrently
    sender_task = asyncio.ensure_future(sender())
    receiver_task = asyncio.ensure_future(receiver())

    done, pending = await asyncio.wait(
        [sender_task, receiver_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
    for task in done:
        if task.exception():
            logger.debug("WebSocket task exception: %s", task.exception())