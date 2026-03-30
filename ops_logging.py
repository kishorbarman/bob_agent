import asyncio
import json
import threading
import time
import uuid
from typing import Any, Optional

import httpx

_FAILURE_LOCK = threading.Lock()
_FAILURE_COUNTS: dict[str, int] = {}
_LAST_ALERT_AT: dict[str, float] = {}


def make_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def log_event(logger, event_type: str, **fields: Any) -> None:
    payload = {"event_type": event_type, **fields, "ts": time.time()}
    logger.info("EVENT %s", json.dumps(payload, sort_keys=True, default=str))


def record_failure(
    key: str, threshold: int = 3, cooldown_seconds: int = 300
) -> tuple[int, bool]:
    now = time.time()
    with _FAILURE_LOCK:
        count = _FAILURE_COUNTS.get(key, 0) + 1
        _FAILURE_COUNTS[key] = count
        last_alert = _LAST_ALERT_AT.get(key, 0.0)
        should_alert = count >= threshold and (now - last_alert) >= cooldown_seconds
        if should_alert:
            _LAST_ALERT_AT[key] = now
        return count, should_alert


def reset_failure(key: str) -> None:
    with _FAILURE_LOCK:
        _FAILURE_COUNTS[key] = 0


async def dispatch_alert(
    logger,
    message: str,
    bot=None,
    admin_chat_id: Optional[int] = None,
    slack_webhook_url: str = "",
) -> None:
    if bot and admin_chat_id:
        try:
            await bot.send_message(chat_id=admin_chat_id, text=message)
        except Exception:
            logger.debug("Failed to send Telegram alert", exc_info=True)

    if slack_webhook_url:
        try:
            await asyncio.to_thread(
                httpx.post,
                slack_webhook_url,
                json={"text": message},
                timeout=8,
            )
        except Exception:
            logger.debug("Failed to send Slack alert", exc_info=True)
