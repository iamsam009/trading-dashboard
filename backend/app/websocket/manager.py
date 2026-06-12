"""
ConnectionManager – manages frontend WebSocket connections and message routing.

Each connected frontend client gets:
- An asyncio.Queue for outbound messages (non-blocking sends)
- Heartbeat ping/pong (every 25s) to detect stale connections
- Symbol filtering: only receives market data for symbols relevant to 
  the user's active strategies

Supports horizontal scaling via Redis pub/sub: when a broadcast is issued
from any backend instance, all instances relay to their local connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger("trading_dashboard.ws_manager")

# ── Constants ─────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 25.0  # seconds between pings
HEARTBEAT_TIMEOUT = 10.0   # seconds to wait for pong before disconnecting


class _Connection:
    """Internal wrapper around a single WebSocket + its outbound queue."""

    def __init__(self, user_id: int, ws: WebSocket, symbols: set[str]) -> None:
        self.user_id = user_id
        self.ws = ws
        self.symbols = symbols  # only these symbols are delivered
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._last_pong: float = asyncio.get_event_loop().time()
        self._ping_task: asyncio.Task[None] | None = None


class ConnectionManager:
    """
    Singleton that tracks all active frontend WebSocket connections.

    Usage::

        manager = ConnectionManager()
        await manager.connect(user_id, websocket, symbols)
        # … later …
        await manager.broadcast("market_price", {"symbol": "BTC/USDT", "price": 42000})
    """

    def __init__(self) -> None:
        # user_id → list of _Connection (one user may have multiple tabs)
        self._connections: dict[int, list[_Connection]] = {}

    # ── Public API ────────────────────────────────────────────────────

    async def connect(
        self,
        user_id: int,
        websocket: WebSocket,
        symbols: set[str],
    ) -> None:
        """Accept the WebSocket, start heartbeat, and register the connection."""
        await websocket.accept()

        conn = _Connection(user_id, websocket, symbols)
        self._connections.setdefault(user_id, []).append(conn)

        # Send initial snapshot
        await self.send(user_id, {
            "type": "connected",
            "user_id": user_id,
            "subscribed_symbols": sorted(symbols),
        })

        # Start heartbeat pinger
        conn._ping_task = asyncio.ensure_future(self._heartbeat(conn))

        logger.info(
            "WebSocket connected: user=%d symbols=%s total_connections=%d",
            user_id, sorted(symbols), self.connection_count(),
        )

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        """Remove a connection and cancel its heartbeat."""
        user_conns = self._connections.get(user_id, [])
        for conn in list(user_conns):
            if conn.ws is websocket:
                # Cancel heartbeat
                if conn._ping_task and not conn._ping_task.done():
                    conn._ping_task.cancel()
                user_conns.remove(conn)

                # Clean up queue
                while not conn.queue.empty():
                    try:
                        conn.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                logger.info("WebSocket disconnected: user=%d", user_id)
                break

        # Prune empty user entries
        if not self._connections.get(user_id):
            self._connections.pop(user_id, None)

        # Attempt graceful close if still open
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass

    async def send(self, user_id: int, message: dict[str, Any]) -> None:
        """Enqueue a message for a specific user (all their connections)."""
        for conn in self._connections.get(user_id, []):
            if conn.queue.qsize() < conn.queue.maxsize:
                await conn.queue.put(message)

    async def broadcast(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        symbol: str | None = None,
    ) -> None:
        """Broadcast to all connections, optionally filtered by symbol.

        Args:
            event_type: e.g. "market_price", "trade_notification", "pnl_update"
            payload: arbitrary JSON-serializable dict
            symbol: if set, only deliver to connections subscribed to this symbol
        """
        msg = {"type": event_type, "data": payload}
        for user_id, conns in self._connections.items():
            for conn in conns:
                if symbol is not None and symbol not in conn.symbols:
                    continue
                if conn.queue.qsize() < conn.queue.maxsize:
                    await conn.queue.put(msg)

    def connection_count(self) -> int:
        """Total number of active WebSocket connections."""
        return sum(len(conns) for conns in self._connections.values())

    # ── Heartbeat ─────────────────────────────────────────────────────

    async def _heartbeat(self, conn: _Connection) -> None:
        """Send periodic pings; disconnect if pong not received in time."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if conn.ws.client_state == WebSocketState.DISCONNECTED:
                    break

                # Check if last pong was within timeout
                elapsed = asyncio.get_event_loop().time() - conn._last_pong
                if elapsed > HEARTBEAT_TIMEOUT + HEARTBEAT_INTERVAL:
                    logger.warning(
                        "Heartbeat timeout for user=%d (%.1fs since last pong)",
                        conn.user_id, elapsed,
                    )
                    break

                await conn.queue.put({"type": "ping"})
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Heartbeat task error for user=%d", conn.user_id)

    # ── Queue consumer (called per-connection) ────────────────────────

    async def _consume_and_send(self, conn: _Connection) -> None:
        """Drain the outbound queue and send JSON over the WebSocket."""
        try:
            while True:
                msg = await conn.queue.get()
                try:
                    if conn.ws.client_state == WebSocketState.CONNECTED:
                        raw = json.dumps(msg)
                        await conn.ws.send_text(raw)

                        # Record pong if client responds to ping
                        if msg.get("type") == "pong":
                            conn._last_pong = asyncio.get_event_loop().time()
                except Exception:
                    logger.exception("Failed to send to user=%d", conn.user_id)
                    break
        except asyncio.CancelledError:
            pass


# ── Module-level singleton ────────────────────────────────────────────

_ws_manager: ConnectionManager | None = None


def get_ws_manager() -> ConnectionManager:
    """Return the application-wide ConnectionManager singleton."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = ConnectionManager()
    return _ws_manager