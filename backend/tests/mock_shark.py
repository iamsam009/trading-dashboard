"""
Mock Shark Exchange server for E2E testing.

Provides a self-contained FastAPI application that mimics Shark Exchange
REST + WebSocket endpoints with configurable state.  The mock server is
designed to be started on a random port during tests and torn down
afterwards, allowing the full backend stack (SharkClient → OrderManager →
RiskManager) to be exercised without real exchange connectivity.

Key features:
- REST endpoints: balance, positions, place/cancel/query orders, ticker,
  listen-key management.
- WebSocket endpoint: streams ``24hrTicker`` events that the
  ``SharkWebSocketClient`` can consume.
- Shared ``MockSharkState`` singleton so tests can inspect which orders
  were placed and push price ticks programmatically.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse


# ── Shared mutable state ──────────────────────────────────────
class MockSharkState:
    """Thread-safe-ish state holder shared between REST handlers, the
    WebSocket broadcaster, and the test fixture.

    Because this runs in a single-threaded asyncio event loop in the
    test process, plain attributes are safe.
    """

    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []
        self.positions: list[dict[str, Any]] = []
        self.balances: list[dict[str, Any]] = [
            {
                "asset": "INR",
                "walletBalance": "1000000",
                "availableBalance": "900000",
                "totalInitialMargin": "100000",
                "totalUnrealizedProfit": "0",
            },
            {
                "asset": "BTC",
                "walletBalance": "2.0",
                "availableBalance": "1.5",
                "totalInitialMargin": "0.5",
                "totalUnrealizedProfit": "0",
            },
        ]
        self.market_prices: dict[str, dict[str, Any]] = {}
        self._connected_ws: list[WebSocket] = []
        self._price_update_event: asyncio.Event = asyncio.Event()
        self._order_counter: int = 0

    # ── Order management ────────────────────────────────

    def add_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Record an order and return a mock exchange filled-response."""
        self._order_counter += 1
        order_id = f"mock-order-{self._order_counter}"
        symbol = order.get("symbol", "")
        price = float(
            self.market_prices.get(symbol, {}).get("lastPrice", 0)
        )
        recorded: dict[str, Any] = {
            **order,
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": str(order.get("quantity", 0)),
            "avgPrice": str(order.get("price") or price),
            "cumulativeQuoteQty": str(
                float(order.get("quantity", 0)) * (order.get("price") or price)
            ),
            "createdAt": int(time.time() * 1000),
            "updatedAt": int(time.time() * 1000),
            "positionId": f"mock-pos-{self._order_counter}",
        }
        self.orders.append(recorded)

        # Update positions to reflect the fill
        self._update_position_from_order(symbol, order, price)
        return recorded

    def _update_position_from_order(
        self, symbol: str, order: dict[str, Any], price: float
    ) -> None:
        side = order.get("side", "BUY").upper()
        qty = float(order.get("quantity", 0))
        leverage = int(order.get("leverage", 1))

        existing: dict[str, Any] | None = None
        for p in self.positions:
            if p.get("symbol") == symbol and p.get("status") == "OPEN":
                existing = p
                break

        if existing:
            existing["quantity"] = str(
                float(existing.get("quantity", 0)) + qty
            )
            existing["currentPrice"] = str(price)
            existing["markPrice"] = str(price)
            entry = float(existing.get("entryPrice", 0))
            new_qty = float(existing.get("quantity", 0))
            existing["unrealizedPnl"] = str((price - entry) * new_qty)
            existing["marginUsed"] = str(price * new_qty / leverage)
        else:
            self.positions.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "entryPrice": str(price),
                    "currentPrice": str(price),
                    "markPrice": str(price),
                    "quantity": str(qty),
                    "leverage": leverage,
                    "unrealizedPnl": "0",
                    "unrealizedPnlPercent": "0",
                    "realizedPnl": "0",
                    "liquidationPrice": "0",
                    "marginUsed": str(price * qty / leverage),
                    "status": "OPEN",
                    "positionId": f"mock-pos-{self._order_counter}",
                }
            )

    def get_last_order(self) -> dict[str, Any] | None:
        """Return the most recently placed order, or None."""
        return self.orders[-1] if self.orders else None

    # ── Price management ───────────────────────────────

    def set_price(
        self,
        symbol: str,
        price: float,
        *,
        high: float | None = None,
        low: float | None = None,
        volume: float = 100.0,
    ) -> None:
        """Update the market price and trigger WebSocket broadcast."""
        self.market_prices[symbol] = {
            "symbol": symbol,
            "lastPrice": str(price),
            "priceChange": "0",
            "priceChangePercent": "0",
            "highPrice": str(high or price * 1.02),
            "lowPrice": str(low or price * 0.98),
            "volume": str(volume),
            "openPrice": str(price),
        }
        # Wake the WebSocket broadcaster
        loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(self._price_update_event.set)

    def broadcast_ticker(self, symbol: str) -> dict[str, Any] | None:
        """Build a ``24hrTicker`` event dict for a symbol."""
        data = self.market_prices.get(symbol)
        if not data:
            return None
        return {
            "e": "24hrTicker",
            "E": int(time.time() * 1000),
            "s": symbol,
            "c": data["lastPrice"],
            "p": data["priceChange"],
            "P": data["priceChangePercent"],
            "h": data["highPrice"],
            "l": data["lowPrice"],
            "v": data["volume"],
            "o": data["openPrice"],
        }

    # ── Balance helpers ────────────────────────────────

    def set_balance(self, asset: str, wallet_balance: float) -> None:
        """Update or add a wallet balance entry."""
        for b in self.balances:
            if b["asset"] == asset:
                b["walletBalance"] = str(wallet_balance)
                return
        self.balances.append(
            {
                "asset": asset,
                "walletBalance": str(wallet_balance),
                "availableBalance": str(wallet_balance),
                "totalInitialMargin": "0",
                "totalUnrealizedProfit": "0",
            }
        )


# ── Module-level singleton ───────────────────────────────────
_mock_state: MockSharkState | None = None


def get_mock_state() -> MockSharkState:
    """Return (or lazily create) the shared mock state singleton."""
    global _mock_state
    if _mock_state is None:
        _mock_state = MockSharkState()
    return _mock_state


def reset_mock_state() -> None:
    """Destroy the current state and create a fresh one.

    Call this between tests to ensure isolation.
    """
    global _mock_state
    _mock_state = MockSharkState()


# ── FastAPI application ──────────────────────────────────────

mock_shark_app = FastAPI(
    title="Mock Shark Exchange",
    version="0.1.0",
    docs_url=None,   # disable OpenAPI UI to avoid port conflicts
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# REST Endpoints  (all ignore HMAC headers – the test SharkClient will point
# at this server's base URL so signatures are irrelevant)
# ---------------------------------------------------------------------------

@mock_shark_app.get("/v1/wallet/futures-wallet/details")
async def _get_balance(_request: Request) -> dict[str, Any]:
    state = get_mock_state()
    # Mirror the structure Shark Exchange actually returns
    return {"data": state.balances}


@mock_shark_app.get("/v1/positions")
async def _get_positions(pair: str | None = None) -> dict[str, Any]:
    state = get_mock_state()
    positions = state.positions
    if pair:
        positions = [p for p in positions if p.get("symbol") == pair.upper()]
    return {"data": positions, "total": len(positions)}


@mock_shark_app.post("/v1/order/place-order")
async def _place_order(body: dict[str, Any]) -> dict[str, Any]:
    state = get_mock_state()
    return state.add_order(body)


@mock_shark_app.post("/v1/order/delete-order")
async def _cancel_order(body: dict[str, Any]) -> dict[str, Any]:
    order_id = body.get("orderId") or body.get("clientOrderId", "unknown")
    return {
        "orderId": order_id,
        "status": "CANCELLED",
        "message": "Order cancelled successfully",
    }


@mock_shark_app.get("/v1/order/order-details")
async def _get_order_status(
    orderId: str | None = None,
    clientOrderId: str | None = None,
) -> dict[str, Any]:
    state = get_mock_state()
    lookup = orderId or clientOrderId
    for order in state.orders:
        if order.get("orderId") == lookup or order.get("clientOrderId") == lookup:
            return order
    return JSONResponse(
        status_code=404, content={"code": -1, "msg": "Order not found"}
    )


@mock_shark_app.get("/v1/market/ticker24Hr/{symbol}")
async def _get_ticker(symbol: str) -> dict[str, Any]:
    state = get_mock_state()
    ticker = state.market_prices.get(symbol.upper())
    if ticker:
        return ticker
    # Default fallback price
    return {
        "symbol": symbol.upper(),
        "lastPrice": "50000",
        "priceChange": "0",
        "priceChangePercent": "0",
        "highPrice": "51000",
        "lowPrice": "49000",
        "volume": "100",
        "openPrice": "50000",
    }


@mock_shark_app.post("/v1/retail/listen-key")
async def _create_listen_key() -> dict[str, str]:
    key = f"mock-listen-{uuid.uuid4().hex[:12]}"
    return {"listenKey": key}


@mock_shark_app.put("/v1/retail/listen-key")
async def _refresh_listen_key() -> dict[str, str]:
    return {"message": "ok"}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@mock_shark_app.websocket("/auth-stream/{listen_key}")
async def _auth_stream(websocket: WebSocket, listen_key: str) -> None:
    """Stream ``24hrTicker`` events to connected clients.

    Every time ``MockSharkState.set_price()`` is called the broadcaster
    emits a ticker JSON frame for the updated symbol.
    """
    await websocket.accept()
    state = get_mock_state()
    state._connected_ws.append(websocket)

    try:
        while True:
            await state._price_update_event.wait()
            state._price_update_event.clear()

            # Push all known prices
            for symbol in list(state.market_prices.keys()):
                ticker = state.broadcast_ticker(symbol)
                if ticker:
                    try:
                        await websocket.send_json(ticker)
                    except Exception:
                        return
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if websocket in state._connected_ws:
            state._connected_ws.remove(websocket)


# ── Convenience runner (used by test fixtures) ─────────────────
def _find_free_port() -> int:
    """Return an available TCP port on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_mock_server(port: int | None = None) -> tuple[uvicorn.Server, int]:
    """Start the mock Shark server asynchronously.

    Returns ``(server, actual_port)``.  The caller should call
    ``server.should_exit = True`` to stop it.
    """
    if port is None:
        port = _find_free_port()

    config = uvicorn.Config(
        mock_shark_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Run the server in the background
    _task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.3)  # give uvicorn a moment to bind

    return server, port