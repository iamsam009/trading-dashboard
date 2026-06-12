"""
FastAPI Application Entry Point

Provides health-check, root, and readiness endpoints, plus the v1 API router
(auth + API key management).  An audit-logging middleware writes every
authenticated request to the `logs` table.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.core.metrics import PrometheusMiddleware, generate_metrics
from prometheus_client import CONTENT_TYPE_LATEST

# ── Logging ────────────────────────────────────────────
settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("trading_dashboard")


# ── Lifespan (startup / shutdown) ──────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify DB/Redis connectivity.  Shutdown: graceful teardown."""
    logger.info("🚀 Trading Dashboard backend starting up …")

    # Encryption key bootstrap
    if not settings.encryption_key:
        from cryptography.fernet import Fernet

        generated = Fernet.generate_key().decode()
        logger.warning(
            "⚠️  ENCRYPTION_KEY not set – generated temporary key. "
            "Set ENCRYPTION_KEY in .env for production.\n"
            "    Generated key (save this!): %s",
            generated,
        )

    # DB check
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        logger.info("✅ Database connection healthy")
        await engine.dispose()
    except Exception:
        logger.exception("❌ Database connection failed – continuing anyway")

    # Redis check
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        logger.info("✅ Redis connection healthy")
        await r.aclose()
    except Exception:
        logger.exception("❌ Redis connection failed – continuing anyway")

    yield  # ── application runs here ──

    logger.info("👋 Trading Dashboard backend shutting down …")


# ── App instance ───────────────────────────────────────
app = FastAPI(
    title="Trading Dashboard API",
    description="Backend for the Shark trading dashboard – real-time orders, positions, risk metrics.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

# ── CORS ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Prometheus Metrics Middleware ──────────────────────
app.add_middleware(PrometheusMiddleware)


# ── Audit Logging Middleware ───────────────────────────
@app.middleware("http")
async def audit_log_middleware(request: Request, call_next):
    """Log every authenticated request to the `logs` table for audit trail."""
    start_time = time.monotonic()

    # Execute the request
    response = await call_next(request)
    duration_ms = (time.monotonic() - start_time) * 1000

    # Only log authenticated API requests (skip health checks, static files)
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return response

    # Fire-and-forget audit log (don't block the response)
    try:
        import asyncio

        asyncio.ensure_future(
            _write_audit_log(
                user_id=user_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
        )
    except Exception:
        logger.exception("Failed to schedule audit log write")

    return response


async def _write_audit_log(
    *,
    user_id: int,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """Persist an audit log entry asynchronously."""
    try:
        from app.db.base import async_session
        from app.models.log import Log

        async with async_session() as session:
            log_entry = Log(
                user_id=user_id,
                level="INFO",
                message=f"{method} {path} → {status_code} ({duration_ms:.2f}ms)",
                category="audit",
                metadata_={
                    "method": method,
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            session.add(log_entry)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist audit log entry")


# ── Register API v1 router ─────────────────────────────
from app.api import router as api_router  # noqa: E402

app.include_router(api_router)


# ── Health / Root Routes ───────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    """Root endpoint – returns API metadata."""
    return {
        "service": "Trading Dashboard API",
        "version": "0.1.0",
        "docs": "/docs" if settings.is_development else None,
    }


@app.get("/health", tags=["Health"])
async def health():
    """
    Lightweight health-check.

    Returns HTTP 200 as soon as FastAPI is accepting requests.
    For a deeper ready-check see `/ready`.
    """
    return {"status": "ok"}


@app.get("/metrics", tags=["Monitoring"])
async def metrics():
    """
    Prometheus metrics endpoint.

    Exposes HTTP request counts, WebSocket connection gauges,
    order counters, and other application-level metrics in
    the text/plain Prometheus exposition format.
    """
    return Response(content=generate_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready", tags=["Health"])
async def readiness():
    """
    Readiness probe – verifies DB and Redis are reachable.

    Returns HTTP 200 only when all external dependencies are healthy.
    """
    checks = {"database": False, "redis": False}

    # DB
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        checks["database"] = True
        await engine.dispose()
    except Exception as exc:
        checks["database"] = str(exc)

    # Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        checks["redis"] = True
        await r.aclose()
    except Exception as exc:
        checks["redis"] = str(exc)

    all_ok = all(v is True for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=status_code,
    )


# ── Error handlers ─────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    logger.exception("Unhandled exception on %s", request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )