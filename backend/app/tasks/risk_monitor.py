"""Celery periodic task – risk monitor (runs every 5 seconds).

Evaluates trailing stops, checks drawdown, and triggers emergency
closures.  All actions are audit-logged and broadcast via WebSocket.
"""

from __future__ import annotations

import asyncio
import logging

from app.celery_app import celery_app
from app.core.risk_manager import get_risk_manager

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.risk_monitor.risk_monitor_cycle",
    bind=True,
    max_retries=1,
    default_retry_delay=2,
)
def risk_monitor_cycle(self) -> dict:
    """Periodic risk-monitoring cycle.

    Runs every 5 seconds (configured in ``celery_app.conf.beat_schedule``).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        rm = get_risk_manager()
        result = loop.run_until_complete(rm.run_monitor_cycle())
    except Exception as exc:
        logger.exception("Risk monitor cycle failed: %s", exc)
        try:
            raise self.retry(exc=exc)
        except Exception:
            # Retry exhausted – do not reraise to avoid crashing the worker
            return {"error": str(exc), "retries_exhausted": True}
    return result