"""
Prometheus Metrics Module

Exposes application metrics for monitoring and alerting:
- http_requests_total (counter, labels: method, path, status_code)
- websocket_connections (gauge, active connections)
- orders_total (counter, labels: side, status)
- order_errors_total (counter, labels: error_type)
- risk_rejections_total (counter, labels: reason)
- db_connection_errors_total (counter)
- redis_connection_errors_total (counter)
"""

from __future__ import annotations

import logging
from typing import Callable

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("trading_dashboard.metrics")

# ── Registry ────────────────────────────────────────────────
registry = CollectorRegistry(auto_describe=True)

# ── Counters ────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    labelnames=["method", "path", "status_code"],
    registry=registry,
)

orders_total = Counter(
    "orders_total",
    "Total orders placed",
    labelnames=["side", "status"],
    registry=registry,
)

order_errors_total = Counter(
    "order_errors_total",
    "Total order placement errors",
    labelnames=["error_type"],
    registry=registry,
)

risk_rejections_total = Counter(
    "risk_rejections_total",
    "Total orders rejected by risk checks",
    labelnames=["reason"],
    registry=registry,
)

db_connection_errors_total = Counter(
    "db_connection_errors_total",
    "Total database connection errors",
    registry=registry,
)

redis_connection_errors_total = Counter(
    "redis_connection_errors_total",
    "Total Redis connection errors",
    registry=registry,
)

# ── Gauges ──────────────────────────────────────────────────
websocket_connections = Gauge(
    "websocket_connections",
    "Active WebSocket connections",
    registry=registry,
)

active_positions = Gauge(
    "active_positions",
    "Number of currently open positions",
    registry=registry,
)

# ── Histograms ──────────────────────────────────────────────
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)


# ── Middleware ──────────────────────────────────────────────
class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that records HTTP request metrics.

    Tracks:
    - http_requests_total (counter by method, path, status)
    - http_request_duration_seconds (histogram)
    """

    def __init__(self, app: ASGIApp, path_filter: Callable[[str], bool] | None = None) -> None:
        super().__init__(app)
        self._path_filter = path_filter or (lambda p: not p.startswith("/metrics"))

    async def dispatch(self, request: Request, call_next):
        import time

        path = request.url.path
        method = request.method

        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        if self._path_filter(path):
            http_requests_total.labels(
                method=method,
                path=path,
                status_code=str(response.status_code),
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                path=path,
            ).observe(duration)

        return response


# ── Metrics endpoint handler ────────────────────────────────
def generate_metrics() -> str:
    """Return Prometheus text format metrics as a string."""
    return generate_latest(registry).decode("utf-8")


# ── Convenience helpers ─────────────────────────────────────
def record_order(side: str, status: str) -> None:
    """Record a placed order."""
    orders_total.labels(side=side, status=status).inc()


def record_order_error(error_type: str) -> None:
    """Record an order placement error."""
    order_errors_total.labels(error_type=error_type).inc()


def record_risk_rejection(reason: str) -> None:
    """Record a risk-based order rejection."""
    risk_rejections_total.labels(reason=reason).inc()


def record_db_error() -> None:
    """Record a database connection error."""
    db_connection_errors_total.inc()


def record_redis_error() -> None:
    """Record a Redis connection error."""
    redis_connection_errors_total.inc()


def set_ws_connections(count: int) -> None:
    """Set the current number of active WebSocket connections."""
    websocket_connections.set(count)


def inc_ws_connections() -> None:
    """Increment active WebSocket connection count."""
    websocket_connections.inc()


def dec_ws_connections() -> None:
    """Decrement active WebSocket connection count."""
    websocket_connections.dec()


def set_active_positions(count: int) -> None:
    """Set the current number of open positions."""
    active_positions.set(count)