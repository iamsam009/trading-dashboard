"""Celery task – real-time notifications via WebSocket.

Sends real-time alerts (kill-switch engaged, large drawdown, margin call, etc.)
to all connected frontend clients via the ConnectionManager.

Provides a low-level ``send_notification`` task that pushes a JSON payload
directly to a user's WebSocket.  Also exposes a ``broadcast_alert`` helper
for system-wide messages (e.g. "exchange under maintenance").

Email / SMS delivery is provided as a placeholder – wire up your provider
(SendGrid, Twilio, etc.) when needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import Task

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


class NotificationTask(Task):
    name = "app.tasks.notifications.send_notification"


async def _send_ws_message(user_id: int, message: dict[str, Any]) -> bool:
    """Push a message to a specific user's WebSocket connection(s).

    Returns True if at least one connection received the message.
    """
    try:
        from app.websocket.manager import get_ws_manager

        manager = get_ws_manager()
        await manager.send(user_id, message)
        return True
    except Exception:
        logger.exception("Failed to send WS notification to user %d", user_id)
        return False


async def _broadcast_ws_message(message: dict[str, Any]) -> int:
    """Broadcast a message to ALL connected WebSocket clients.

    Returns the number of users the message was delivered to.
    """
    try:
        from app.websocket.manager import get_ws_manager

        manager = get_ws_manager()
        await manager.broadcast(message["type"], message)
        return manager.connection_count()
    except Exception:
        logger.exception("Failed to broadcast WS message")
        return 0


# ---------------------------------------------------------------------------
# Email / SMS placeholders
# ---------------------------------------------------------------------------


async def _send_email(
    to_email: str, subject: str, body: str
) -> bool:
    """Placeholder: send an email via your provider (SendGrid, SES, SMTP, etc.).

    Implement this when email delivery is needed.
    """
    logger.info(
        "[EMAIL PLACEHOLDER] To: %s | Subject: %s | Body: %s",
        to_email, subject, body[:200],
    )
    # TODO: Integrate with your email provider
    # import sendgrid
    # sg = sendgrid.SendGridAPIClient(api_key=...)
    # ...
    return True


async def _send_sms(
    to_phone: str, message: str
) -> bool:
    """Placeholder: send an SMS via your provider (Twilio, etc.).

    Implement this when SMS delivery is needed.
    """
    logger.info(
        "[SMS PLACEHOLDER] To: %s | Message: %s",
        to_phone, message[:200],
    )
    # TODO: Integrate with your SMS provider
    # from twilio.rest import Client
    # client = Client(account_sid, auth_token)
    # ...
    return True


# ---------------------------------------------------------------------------
# Task implementations
# ---------------------------------------------------------------------------


async def _async_send_notification(
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    severity: str = "info",
    metadata: dict[str, Any] | None = None,
    *,
    send_email: bool = False,
    send_sms: bool = False,
    email_address: str | None = None,
    phone_number: str | None = None,
) -> dict[str, Any]:
    """Core async logic for sending a notification to a user."""
    payload: dict[str, Any] = {
        "type": "notification",
        "notification_type": notification_type,
        "title": title,
        "message": message,
        "severity": severity,
        "metadata": metadata or {},
    }

    try:
        ws_ok = await _send_ws_message(user_id, payload)
    except Exception:
        ws_ok = False
    result: dict[str, Any] = {
        "user_id": user_id,
        "notification_type": notification_type,
        "ws_delivered": ws_ok,
    }

    if send_email and email_address:
        result["email_sent"] = await _send_email(
            email_address,
            f"[{severity.upper()}] {title}",
            message,
        )

    if send_sms and phone_number:
        result["sms_sent"] = await _send_sms(phone_number, message)

    return result


async def _async_broadcast_alert(
    alert_type: str,
    title: str,
    message: str,
    severity: str = "warning",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Core async logic for broadcasting a system-wide alert."""
    payload: dict[str, Any] = {
        "type": "alert",
        "alert_type": alert_type,
        "title": title,
        "message": message,
        "severity": severity,
        "metadata": metadata or {},
    }

    delivered = await _broadcast_ws_message(payload)
    logger.info(
        "Broadcast alert '%s' delivered to %d users",
        alert_type, delivered,
    )
    return {
        "alert_type": alert_type,
        "users_delivered": delivered,
    }


# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    base=NotificationTask,
    name="app.tasks.notifications.send_notification",
    max_retries=2,
    default_retry_delay=10,
    track_started=True,
)
def send_notification(
    self,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    severity: str = "info",
    metadata: dict[str, Any] | None = None,
    *,
    send_email: bool = False,
    send_sms: bool = False,
    email_address: str | None = None,
    phone_number: str | None = None,
) -> dict[str, Any]:
    """Send a notification to a specific user.

    Delivers via WebSocket by default.  Set ``send_email=True`` or
    ``send_sms=True`` (and provide address/phone) for additional channels.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        _async_send_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            severity=severity,
            metadata=metadata,
            send_email=send_email,
            send_sms=send_sms,
            email_address=email_address,
            phone_number=phone_number,
        )
    )


@celery_app.task(
    bind=True,
    base=NotificationTask,
    name="app.tasks.notifications.broadcast_alert",
    max_retries=1,
    default_retry_delay=10,
    track_started=True,
)
def broadcast_alert(
    self,
    alert_type: str,
    title: str,
    message: str,
    severity: str = "warning",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Broadcast a system-wide alert to ALL connected users.

    Use for exchange downtime, kill-switch global events, etc.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        _async_broadcast_alert(
            alert_type=alert_type,
            title=title,
            message=message,
            severity=severity,
            metadata=metadata,
        )
    )