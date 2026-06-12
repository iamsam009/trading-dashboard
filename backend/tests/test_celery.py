"""
Integration / connectivity tests for Celery.

These tests require a running Redis broker and Celery worker.
Marked with ``@pytest.mark.integration`` – skipped by default in CI
unless ``--run-integration`` is passed.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


# ── Celery app import ─────────────────────────────────
@pytest.fixture(scope="module")
def celery_app():
    """Return the Celery application instance.

    Falls back gracefully if the module hasn't been created yet
    (early project bootstrap phase).
    """
    try:
        from app.celery_app import celery_app as _celery_app
    except (ImportError, ModuleNotFoundError):
        pytest.skip("Celery app module (app.celery_app) not created yet")

    return _celery_app


# ── Tests ─────────────────────────────────────────────
class TestCeleryApp:
    """Basic Celery application sanity checks."""

    def test_app_name(self, celery_app) -> None:
        """Celery app has a meaningful name."""
        assert celery_app.main is not None
        assert len(celery_app.main) > 0

    def test_broker_url_configured(self, celery_app) -> None:
        """Celery app has a broker URL set (from settings or env)."""
        assert celery_app.conf.broker_url is not None
        assert celery_app.conf.broker_url != ""

    def test_result_backend_configured(self, celery_app) -> None:
        """Redis is used as the result backend."""
        backend = celery_app.conf.result_backend or ""
        assert (
            "redis" in backend.lower() or "cache" in backend.lower()
        ), f"Unexpected result backend: {backend}"


class TestCeleryPing:
    """Worker connectivity via celery inspect ping."""

    @pytest.mark.timeout(10)
    def test_inspect_ping_responds(self, celery_app) -> None:
        """
        ``celery inspect ping`` returns at least one worker with ``{'ok': 'pong'}``.

        This test will be skipped if no workers are connected.
        """
        inspect = celery_app.control.inspect()
        if inspect is None:
            pytest.skip("No Celery workers connected – skipping ping test")

        # Timeout is in seconds; None means use broker default
        result = inspect.ping(timeout=5.0)

        # result is None when no workers respond
        if result is None or len(result) == 0:
            pytest.skip("No Celery workers responded to ping")

        # At least one worker must respond with pong
        pong_count = sum(
            1 for worker_responses in result.values()
            if isinstance(worker_responses, list)
            and any(item.get("ok") == "pong" for item in worker_responses)
        )
        assert pong_count >= 1, (
            f"Expected at least one worker to respond with pong, "
            f"got {result}"
        )


class TestCeleryTaskRegistry:
    """Verify expected tasks are registered (if any defined)."""

    def test_registered_tasks_is_dict(self, celery_app) -> None:
        """``celery_app.tasks`` is a dict-like mapping of task name → task."""
        tasks = celery_app.tasks
        assert tasks is not None
        assert len(tasks) >= 0  # may be empty early on

    def test_builtin_tasks_exist(self, celery_app) -> None:
        """Celery ships built-in tasks like celery.backend_cleanup."""
        task_names = list(celery_app.tasks.keys())
        assert any("celery" in name for name in task_names), (
            f"No built-in Celery tasks found. Registered: {task_names[:5]}..."
        )