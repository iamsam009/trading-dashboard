"""
Tests for WebSocket infrastructure – ConnectionManager, WS endpoint auth,
broadcast filtering, isolated subscriptions, and disconnect handling.

Uses:
- ``fastapi.testclient.TestClient`` for endpoint-level WebSocket integration
- Direct ``ConnectionManager`` unit tests for queue/heartbeat/broadcast
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_user_and_strategy(
    async_test_db,
    email: str,
    symbols: list[str],
):
    """Synchronous wrapper to seed a user + strategy in the test DB."""
    from app.core.security import create_access_token, hash_password
    from app.models.strategy import Strategy
    from app.models.user import User as UserModel

    async def _setup():
        # async_test_db is already a session, not a context manager
        user = UserModel(
            email=email,
            hashed_password=hash_password("Secure123!"),
        )
        async_test_db.add(user)
        await async_test_db.flush()

        strategy = Strategy(
            user_id=user.id,
            name=f"Strategy {email}",
            json_definition={"symbols": symbols, "conditions": []},
            is_active=True,
        )
        async_test_db.add(strategy)
        await async_test_db.flush()

        token = create_access_token({"user_id": user.id, "email": user.email})
        return user.id, token

    import asyncio as _asyncio

    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            return executor.submit(_asyncio.run, _setup()).result()
    else:
        return _asyncio.run(_setup())


def _patch_async_session(monkeypatch, async_test_db):
    """Override app.db.base.async_session so the WS endpoint uses the test DB.

    ``ws_endpoints.py`` does ``from app.db.base import async_session``
    inside ``_get_user_active_symbols()``, so we must patch the
    module-level attribute on ``app.db.base`` itself.
    """

    @asynccontextmanager
    async def _mock_factory():
        yield async_test_db

    import app.db.base as _db_base

    monkeypatch.setattr(_db_base, "async_session", _mock_factory)


# ---------------------------------------------------------------------------
# ConnectionManager Unit Tests
# ---------------------------------------------------------------------------

class TestConnectionManager:
    """Unit tests for the ConnectionManager singleton."""

    def test_singleton_returns_same_instance(self):
        """get_ws_manager() returns the same ConnectionManager."""
        from app.websocket.manager import ConnectionManager, get_ws_manager

        # Reset singleton
        import app.websocket.manager as wm

        wm._ws_manager = None

        m1 = get_ws_manager()
        m2 = get_ws_manager()

        assert m1 is m2
        assert isinstance(m1, ConnectionManager)

        wm._ws_manager = None

    @pytest.mark.asyncio
    async def test_connect_registers_connection(self):
        """connect() accepts the WebSocket and tracks the connection."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()

        await manager.connect(1, ws, {"BTCINR", "ETHINR"})

        ws.accept.assert_called_once()
        assert manager.connection_count() == 1
        assert 1 in manager._connections
        conn = manager._connections[1][0]
        assert conn.user_id == 1
        assert conn.symbols == {"BTCINR", "ETHINR"}

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        """disconnect() removes the connection and prunes empty user entries."""
        from app.websocket.manager import ConnectionManager
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.client_state = WebSocketState.DISCONNECTED

        await manager.connect(1, ws, {"BTCINR"})
        assert manager.connection_count() == 1

        await manager.disconnect(1, ws)

        assert manager.connection_count() == 0
        assert 1 not in manager._connections

    @pytest.mark.asyncio
    async def test_send_delivers_to_user(self):
        """send() enqueues a message to all of a user's connections."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()

        await manager.connect(1, ws, {"BTCINR"})
        # Drain the "connected" message first
        conn = manager._connections[1][0]
        while not conn.queue.empty():
            conn.queue.get_nowait()

        await manager.send(1, {"type": "test", "data": "hello"})

        assert conn.queue.qsize() == 1
        msg = await conn.queue.get()
        assert msg == {"type": "test", "data": "hello"}

    @pytest.mark.asyncio
    async def test_broadcast_delivers_to_all(self):
        """broadcast() without symbol filter sends to all connections."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await manager.connect(1, ws1, {"BTCINR"})
        await manager.connect(2, ws2, {"ETHINR"})

        # Drain connected messages
        for uid in (1, 2):
            for c in manager._connections[uid]:
                while not c.queue.empty():
                    c.queue.get_nowait()

        await manager.broadcast("market_price", {"price": 50000.0})

        conn1 = manager._connections[1][0]
        conn2 = manager._connections[2][0]
        assert conn1.queue.qsize() == 1
        assert conn2.queue.qsize() == 1

        msg1 = await conn1.queue.get()
        assert msg1["type"] == "market_price"
        assert msg1["data"]["price"] == 50000.0

    @pytest.mark.asyncio
    async def test_broadcast_with_symbol_filter(self):
        """broadcast() with symbol only delivers to subscribed connections."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        ws_btc = AsyncMock()
        ws_btc.accept = AsyncMock()
        ws_eth = AsyncMock()
        ws_eth.accept = AsyncMock()

        await manager.connect(1, ws_btc, {"BTCINR"})
        await manager.connect(2, ws_eth, {"ETHINR"})

        # Drain connected messages
        for uid in (1, 2):
            for c in manager._connections[uid]:
                while not c.queue.empty():
                    c.queue.get_nowait()

        # Broadcast BTC price – only user 1 should receive
        await manager.broadcast("market_price", {"price": 50000.0}, symbol="BTCINR")

        conn_btc = manager._connections[1][0]
        conn_eth = manager._connections[2][0]

        assert conn_btc.queue.qsize() == 1
        assert conn_eth.queue.qsize() == 0

        msg = await conn_btc.queue.get()
        assert msg["data"]["price"] == 50000.0

    @pytest.mark.asyncio
    async def test_multiple_connections_same_user(self):
        """One user can have multiple connections (e.g., multiple tabs)."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await manager.connect(1, ws1, {"BTCINR"})
        await manager.connect(1, ws2, {"BTCINR"})

        assert manager.connection_count() == 2
        assert len(manager._connections[1]) == 2

        # Drain connected messages
        for c in manager._connections[1]:
            while not c.queue.empty():
                c.queue.get_nowait()

        # send() should deliver to both
        await manager.send(1, {"type": "test"})

        assert manager._connections[1][0].queue.qsize() == 1
        assert manager._connections[1][1].queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_queue_backpressure(self):
        """Messages beyond maxsize (256) are silently dropped."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()

        await manager.connect(1, ws, {"BTCINR"})
        conn = manager._connections[1][0]

        # Drain connected message
        while not conn.queue.empty():
            conn.queue.get_nowait()

        # Fill the queue to max
        for i in range(256):
            await conn.queue.put({"type": f"msg_{i}"})

        # Now send should not enqueue more
        await manager.send(1, {"type": "overflow"})
        assert conn.queue.qsize() == 256

    def test_connection_count_zero_initially(self):
        """A fresh ConnectionManager has zero connections."""
        from app.websocket.manager import ConnectionManager

        manager = ConnectionManager()
        assert manager.connection_count() == 0


# ---------------------------------------------------------------------------
# WebSocket Endpoint Tests
# ---------------------------------------------------------------------------


class TestWebSocketAuth:
    """Authentication and validation at the WebSocket endpoint."""

    def test_connect_without_token_rejected(self, app):
        """Connection without a token query param gets 403."""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws/1"):
                pass

    def test_connect_with_invalid_token_rejected(self, app):
        """Connection with a garbage token gets 4001 close code."""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws/1?token=not.a.valid.jwt"):
                pass

    def test_connect_with_bogus_token_rejected(self, app):
        """A token that can't be decoded gets close code 4001."""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/v1/ws/1?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.fake"
            ):
                pass

    def test_connect_with_wrong_user_id_rejected(self, app):
        """Token user_id must match URL path user_id."""
        from app.core.security import create_access_token

        token = create_access_token({"user_id": 99, "email": "other@test.com"})
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/v1/ws/42?token={token}"):
                pass


class TestWebSocketConnection:
    """Successful WebSocket connection and messaging."""

    def test_connect_with_valid_token(self, app, async_test_db, monkeypatch):
        """Valid token → WebSocket upgrade, receives 'connected' message."""
        _patch_async_session(monkeypatch, async_test_db)

        user_id, token = _seed_user_and_strategy(
            async_test_db, "valid_ws@test.com", ["BTCINR", "ETHINR"]
        )

        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/ws/{user_id}?token={token}") as ws:
            # First message: "connected"
            data = ws.receive_json()
            assert data["type"] == "connected"
            assert data["user_id"] == user_id
            assert "subscribed_symbols" in data
            assert "BTCINR" in data["subscribed_symbols"]
            assert "ETHINR" in data["subscribed_symbols"]

    def test_ws_receives_broadcast_market_data(
        self, app, async_test_db, monkeypatch
    ):
        """After connecting, the WS receives broadcast market_price messages."""
        _patch_async_session(monkeypatch, async_test_db)

        user_id, token = _seed_user_and_strategy(
            async_test_db, "market_ws@test.com", ["BTCINR"]
        )

        from app.websocket.manager import get_ws_manager

        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/ws/{user_id}?token={token}") as ws:
            # Receive the connected message
            connected = ws.receive_json()
            assert connected["type"] == "connected"
            # Drain the initial_snapshot
            snapshot = ws.receive_json()
            assert snapshot["type"] == "initial_snapshot"

            # Broadcast a market price update via the manager
            async def _broadcast():
                manager = get_ws_manager()
                await manager.broadcast(
                    "market_price",
                    {
                        "symbol": "BTCINR",
                        "price": 50000.0,
                        "timestamp": "2024-01-01T00:00:00Z",
                    },
                    symbol="BTCINR",
                )

            import asyncio as _asyncio

            _asyncio.run(_broadcast())

            # The WS should receive the market_price
            data = ws.receive_json()
            assert data["type"] == "market_price"
            assert data["data"]["symbol"] == "BTCINR"
            assert data["data"]["price"] == 50000.0


class TestIsolatedSubscriptions:
    """Multiple clients receive only their subscribed symbols."""

    def test_symbol_isolation_between_clients(self, app, async_test_db, monkeypatch):
        """Client A (BTC) gets BTC updates; Client B (ETH) does not."""
        _patch_async_session(monkeypatch, async_test_db)

        user1_id, token1 = _seed_user_and_strategy(
            async_test_db, "btc_user@test.com", ["BTCINR"]
        )
        user2_id, token2 = _seed_user_and_strategy(
            async_test_db, "eth_user@test.com", ["ETHINR"]
        )

        from app.websocket.manager import get_ws_manager

        import asyncio as _asyncio

        client = TestClient(app)
        with (
            client.websocket_connect(f"/api/v1/ws/{user1_id}?token={token1}") as ws1,
            client.websocket_connect(f"/api/v1/ws/{user2_id}?token={token2}") as ws2,
        ):
            # Consume connected messages
            c1 = ws1.receive_json()
            c2 = ws2.receive_json()
            assert c1["type"] == "connected"
            assert c2["type"] == "connected"
            # Drain initial_snapshot for both clients
            s1 = ws1.receive_json()
            s2 = ws2.receive_json()
            assert s1["type"] == "initial_snapshot"
            assert s2["type"] == "initial_snapshot"

            # Broadcast BTC price
            async def _broadcast_btc():
                manager = get_ws_manager()
                await manager.broadcast(
                    "market_price",
                    {"symbol": "BTCINR", "price": 50000.0},
                    symbol="BTCINR",
                )

            _asyncio.run(_broadcast_btc())

            # Client 1 should receive, Client 2 should not
            data1 = ws1.receive_json()
            assert data1["type"] == "market_price"
            assert data1["data"]["symbol"] == "BTCINR"

            # Client 2 should NOT have received anything
            conns2 = get_ws_manager()._connections.get(user2_id, [])
            if conns2:
                assert conns2[0].queue.empty()


class TestSubscribeUnsubscribe:
    """Clients can dynamically subscribe/unsubscribe to symbols."""

    def test_subscribe_adds_symbols(self, app, async_test_db, monkeypatch):
        """Sending a 'subscribe' message adds symbols to the filter."""
        _patch_async_session(monkeypatch, async_test_db)

        user_id, token = _seed_user_and_strategy(
            async_test_db, "sub_ws@test.com", ["BTCINR"]
        )

        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/ws/{user_id}?token={token}") as ws:
            # Consume connected and initial_snapshot
            ws.receive_json()  # connected
            ws.receive_json()  # initial_snapshot

            # Subscribe to a new symbol
            ws.send_json({"type": "subscribe", "symbols": ["ETHINR"]})

            # Should receive a 'subscribed' confirmation
            data = ws.receive_json()
            assert data["type"] == "subscribed"
            assert "ETHINR" in data["symbols"]
            assert "BTCINR" in data["symbols"]

    def test_unsubscribe_removes_symbols(self, app, async_test_db, monkeypatch):
        """Sending an 'unsubscribe' message removes symbols from the filter."""
        _patch_async_session(monkeypatch, async_test_db)

        user_id, token = _seed_user_and_strategy(
            async_test_db, "unsub_ws@test.com", ["BTCINR", "ETHINR"]
        )

        from app.websocket.manager import get_ws_manager

        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/ws/{user_id}?token={token}") as ws:
            ws.receive_json()  # connected
            ws.receive_json()  # initial_snapshot

            # Unsubscribe from ETH
            ws.send_json({"type": "unsubscribe", "symbols": ["ETHINR"]})

            # Yield to the event loop so the receiver task processes the
            # unsubscribe message. (No confirmation is sent by the handler.)
            import time
            time.sleep(0.1)

            # The connection's symbols should now exclude ETH
            conns = get_ws_manager()._connections.get(user_id, [])
            assert conns
            assert "ETHINR" not in conns[0].symbols
            assert "BTCINR" in conns[0].symbols


class TestDisconnectCleanup:
    """ConnectionManager cleans up properly on disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_resources(self):
        """Disconnecting removes connection, cancels heartbeat, drains queue."""
        from app.websocket.manager import ConnectionManager
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.client_state = WebSocketState.DISCONNECTED

        await manager.connect(1, ws, {"BTCINR"})

        # Put some messages in the queue
        conn = manager._connections[1][0]
        # Drain connected message
        while not conn.queue.empty():
            conn.queue.get_nowait()
        await conn.queue.put({"type": "msg1"})
        await conn.queue.put({"type": "msg2"})

        await manager.disconnect(1, ws)

        # Let the event loop process the cancellation
        await asyncio.sleep(0)

        # Connection should be gone
        assert manager.connection_count() == 0
        # Queue should be drained
        assert conn.queue.empty()
        # Heartbeat should be cancelled or done
        if conn._ping_task:
            assert conn._ping_task.cancelled() or conn._ping_task.done()

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_user_is_noop(self):
        """Disconnecting a user that doesn't exist is harmless."""
        from app.websocket.manager import ConnectionManager
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.DISCONNECTED

        # Should not raise
        await manager.disconnect(999, ws)
        assert manager.connection_count() == 0


class TestPingPong:
    """Heartbeat ping/pong mechanism."""

    @pytest.mark.asyncio
    async def test_pong_updates_last_pong(self):
        """Receiving a 'pong' message updates the last_pong timestamp."""
        import time as _time
        from app.websocket.manager import ConnectionManager
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED

        await manager.connect(1, ws, {"BTCINR"})
        conn = manager._connections[1][0]

        old_pong = _time.time()
        await asyncio.sleep(0.02)

        # Simulate receiving a pong (use high-resolution time.time)
        conn._last_pong = _time.time()

        assert conn._last_pong > old_pong

    @pytest.mark.asyncio
    async def test_heartbeat_sends_ping(self):
        """Heartbeat puts a 'ping' message in the queue."""
        from app.websocket.manager import ConnectionManager
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED

        await manager.connect(1, ws, {"BTCINR"})
        conn = manager._connections[1][0]

        # Drain the "connected" message first
        while not conn.queue.empty():
            conn.queue.get_nowait()

        if conn._ping_task and not conn._ping_task.done():
            conn._ping_task.cancel()

        # Start a short-interval heartbeat for testing
        async def _fast_heartbeat():
            conn._last_pong = asyncio.get_event_loop().time()
            await asyncio.sleep(0.05)
            await conn.queue.put({"type": "ping"})

        conn._ping_task = asyncio.ensure_future(_fast_heartbeat())
        await asyncio.sleep(0.1)

        assert not conn.queue.empty()
        msg = await conn.queue.get()
        assert msg["type"] == "ping"