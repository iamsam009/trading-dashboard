"""Celery application instance for the trading dashboard.

Configures broker (Redis) and result backend, discovers periodic tasks
from ``app.tasks``.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "trading_dashboard",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "app.tasks.risk_monitor",
        "app.tasks.backtest",
        "app.tasks.reports",
        "app.tasks.notifications",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# ---------------------------------------------------------------------------
# Periodic tasks (Celery Beat schedule)
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    "risk-monitor-every-5-seconds": {
        "task": "app.tasks.risk_monitor.risk_monitor_cycle",
        "schedule": 5.0,  # every 5 seconds
        "options": {"expires": 4},
    },
    "daily-performance-report": {
        "task": "app.tasks.reports.daily_performance_report",
        "schedule": crontab(hour=0, minute=5),  # 00:05 UTC every day
        "options": {"expires": 300},
    },
}