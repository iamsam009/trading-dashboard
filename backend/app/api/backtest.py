"""Backtest REST API – trigger backtest runs and fetch results.

Endpoints
---------
POST  /api/v1/backtest               – Submit a backtest (returns task_id)
GET   /api/v1/backtest/{task_id}/result – Poll for the backtest result
"""

from __future__ import annotations

import logging
from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status

from app.celery_app import celery_app
from app.deps import get_current_user
from app.models.user import User
from app.schemas.backtest import (
    BacktestRequest,
    BacktestResult,
    BacktestSubmitResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    response_model=BacktestSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_backtest(
    body: BacktestRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit a backtest job for a strategy.

    The backtest runs asynchronously via Celery.  Use the returned
    ``task_id`` to poll for the result at ``GET /backtest/{task_id}/result``.
    """
    from app.tasks.backtest import run_backtest

    task = run_backtest.delay(
        strategy_id=body.strategy_id,
        user_id=current_user.id,
        symbol=body.symbol,
        start_date=body.start_date.isoformat(),
        end_date=body.end_date.isoformat(),
        initial_capital=body.initial_capital,
    )

    logger.info(
        "Backtest submitted: strategy=%d symbol=%s user=%d task=%s",
        body.strategy_id, body.symbol, current_user.id, task.id,
    )

    return {
        "task_id": task.id,
        "status": "queued",
        "strategy_id": body.strategy_id,
        "symbol": body.symbol,
    }


@router.get("/{task_id}/result", response_model=BacktestResult)
async def get_backtest_result(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll for the result of a previously submitted backtest.

    Returns the full result (metrics, equity curve, trades) once the
    Celery task has completed.  Returns a ``PENDING`` / ``PROGRESS``
    status while the task is still running.

    *404* – task not found (invalid or expired task_id).
    *403* – the result belongs to a different user.
    """
    task_result = AsyncResult(task_id, app=celery_app)

    if task_result.state == "PENDING":
        return {
            "task_id": task_id,
            "status": "pending",
            "metrics": None,
            "equity_curve": [],
            "trades": [],
        }

    if task_result.state == "PROGRESS":
        meta = task_result.info or {}
        return {
            "task_id": task_id,
            "status": "running",
            "progress": meta,
            "metrics": None,
            "equity_curve": [],
            "trades": [],
        }

    if task_result.state == "FAILURE":
        error_info = str(task_result.info) if task_result.info else "Unknown error"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backtest failed: {error_info}",
        )

    if task_result.state == "SUCCESS":
        result: dict[str, Any] = task_result.result
        # Verify ownership – the task result must belong to this user
        if result.get("user_id") != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This backtest result belongs to a different user.",
            )

        return {
            "task_id": task_id,
            "status": "completed",
            "metrics": result.get("metrics"),
            "equity_curve": result.get("equity_curve", []),
            "trades": result.get("trades", []),
        }

    # Unknown state – treat as still processing
    return {
        "task_id": task_id,
        "status": "unknown",
        "metrics": None,
        "equity_curve": [],
        "trades": [],
    }