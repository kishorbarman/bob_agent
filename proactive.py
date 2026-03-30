import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from google_services import get_recent_emails, get_upcoming_events
from ops_logging import dispatch_alert, log_event, record_failure, reset_failure
from preferences import get_user_preferences
from storage import (
    get_proactive_settings,
    list_due_proactive_jobs,
    list_due_watchers,
    record_delivery_log,
    record_proactive_event,
    update_proactive_job_state,
    update_watcher_schedule,
)

logger = logging.getLogger(__name__)


class ProactiveScheduler:
    def __init__(self, app):
        self.app = app
        self._task = None
        self._stop = asyncio.Event()
        self.enabled = os.getenv("PROACTIVE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self._last_tick: Optional[datetime] = None
        raw_admin = os.getenv("ADMIN_CHAT_ID", "").strip()
        self.admin_chat_id = int(raw_admin) if raw_admin.isdigit() else None
        self.slack_webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
        self._digest_buffer: Dict[int, list[str]] = {}

    def start(self) -> None:
        if not self.enabled:
            logger.info("Proactive scheduler disabled via PROACTIVE_ENABLED.")
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Proactive scheduler started.")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        await self._task
        logger.info("Proactive scheduler stopped.")

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Proactive scheduler loop failed.")
            await asyncio.sleep(60)

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_tick:
            gap = (now - self._last_tick).total_seconds()
            if gap > 180:
                logger.warning("Proactive scheduler missed-run recovery window detected: gap=%.1fs", gap)
        self._last_tick = now
        now_iso = now.isoformat()

        for job in list_due_proactive_jobs(now_iso):
            await self._handle_job(job, now)

        for watcher in list_due_watchers(now_iso):
            await self._handle_watcher(watcher, now)
        await self._flush_digests()

    async def _handle_job(self, job: Dict[str, Any], now: datetime) -> None:
        user_id = int(job["user_id"])
        settings = get_proactive_settings(user_id)
        if not int(settings.get("enabled", 1)):
            next_run = now + timedelta(hours=1)
            update_proactive_job_state(int(job["id"]), next_run.isoformat(), "disabled", now.isoformat())
            return

        job_type = job.get("job_type", "")
        status = "ok"
        log_event(logger, "proactive_job", action=job_type, user_id=user_id, result="start")
        try:
            if self._in_quiet_hours(user_id, now):
                status = "deferred_quiet_hours"
                next_run = now + timedelta(minutes=30)
                update_proactive_job_state(int(job["id"]), next_run.isoformat(), status, now.isoformat())
                return
            if job_type == "morning_brief":
                await self._send_morning_brief(user_id, now)
            elif job_type == "calendar_nudge":
                await self._send_calendar_nudge(user_id, now)
            else:
                status = "unknown_job"
            reset_failure("proactive_job:%s" % job_type)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Proactive job failed: %s", job_type)
            status = f"error:{exc}"
            count, should_alert = record_failure("proactive_job:%s" % job_type)
            if should_alert:
                await dispatch_alert(
                    logger,
                    f"Bob alert: proactive job `{job_type}` failing repeatedly ({count} consecutive).",
                    bot=self.app.bot,
                    admin_chat_id=self.admin_chat_id,
                    slack_webhook_url=self.slack_webhook,
                )

        next_run = self._compute_next_job_run(job, settings, now)
        update_proactive_job_state(int(job["id"]), next_run.isoformat(), status, now.isoformat())
        log_event(logger, "proactive_job", action=job_type, user_id=user_id, result=status)

    async def _handle_watcher(self, watcher: Dict[str, Any], now: datetime) -> None:
        user_id = int(watcher["user_id"])
        watcher_type = watcher.get("watcher_type", "")
        query = watcher.get("query", "")
        params = watcher.get("params", {})
        log_event(logger, "proactive_watcher", action=watcher_type, user_id=user_id, result="start", query=query)

        try:
            if watcher_type == "news_keyword":
                await self._eval_news_watcher(user_id, query, now)
            elif watcher_type == "price_threshold":
                await self._eval_price_watcher(user_id, query, params, now)
            reset_failure("watcher:%s" % watcher_type)
        except Exception:
            logger.exception("Watcher eval failed: %s", watcher_type)
            count, should_alert = record_failure("watcher:%s" % watcher_type)
            if should_alert:
                await dispatch_alert(
                    logger,
                    f"Bob alert: watcher `{watcher_type}` failing repeatedly ({count} consecutive).",
                    bot=self.app.bot,
                    admin_chat_id=self.admin_chat_id,
                    slack_webhook_url=self.slack_webhook,
                )

        interval = int(params.get("check_every_minutes", 60))
        next_check = now + timedelta(minutes=max(5, interval))
        update_watcher_schedule(int(watcher["id"]), next_check.isoformat(), now.isoformat())
        log_event(logger, "proactive_watcher", action=watcher_type, user_id=user_id, result="ok")

    async def _send_morning_brief(self, user_id: int, now: datetime) -> None:
        prefs = get_user_preferences(user_id)
        city = os.getenv("MORNING_BRIEF_CITY", "San Francisco")
        cal = get_upcoming_events(5)
        emails = get_recent_emails(3)
        weather_text = await asyncio.to_thread(self._fetch_weather_summary, city)
        message = (
            "Morning Brief\n"
            f"- Timezone: {prefs.timezone}\n\n"
            "Calendar:\n"
            f"{cal}\n\n"
            "Weather:\n"
            f"{weather_text}\n\n"
            "Top Emails:\n"
            f"{emails}"
        )
        dedupe_key = f"brief:{user_id}:{now.date().isoformat()}"
        if not record_proactive_event(user_id, "morning_brief", dedupe_key, {"date": now.date().isoformat()}):
            return
        await self._send_message(user_id, message, "morning_brief")

    async def _send_calendar_nudge(self, user_id: int, now: datetime) -> None:
        text = get_upcoming_events(1)
        message = "Calendar nudge:\n" + text
        dedupe_key = f"calendar_nudge:{user_id}:{now.strftime('%Y-%m-%dT%H')}"
        if not record_proactive_event(user_id, "calendar_nudge", dedupe_key, {"hour": now.strftime('%Y-%m-%dT%H')}):
            return
        await self._send_message(user_id, message, "calendar_nudge")

    async def _eval_news_watcher(self, user_id: int, query: str, now: datetime) -> None:
        from bot import search_web

        result = await asyncio.to_thread(search_web, query, 3)
        if "No results found." in result or "temporarily unavailable" in result.lower():
            return
        digest = hashlib.sha256(result.encode("utf-8")).hexdigest()[:16]
        dedupe_key = f"news:{query}:{digest}"
        if not record_proactive_event(user_id, "watcher_news", dedupe_key, {"query": query}):
            return
        message = f"Watcher alert (news): {query}\n\n{result}"
        await self._send_message(user_id, message, "watcher_news")

    async def _eval_price_watcher(self, user_id: int, symbol: str, params: Dict[str, Any], now: datetime) -> None:
        current = await asyncio.to_thread(self._fetch_price_usd, symbol)
        if current is None:
            return
        direction = str(params.get("direction", "below")).lower()
        threshold = float(params.get("threshold", 0))
        hit = (direction == "below" and current <= threshold) or (direction == "above" and current >= threshold)
        if not hit:
            return
        dedupe_key = f"price:{symbol}:{direction}:{threshold}:{now.strftime('%Y-%m-%d')}"
        if not record_proactive_event(user_id, "watcher_price", dedupe_key, {"symbol": symbol, "price": current}):
            return
        message = f"Watcher alert (price): {symbol} is {current:.2f} USD ({direction} {threshold})"
        await self._send_message(user_id, message, "watcher_price")

    async def _send_message(self, user_id: int, text: str, message_type: str) -> None:
        settings = get_proactive_settings(user_id)
        if message_type.startswith("watcher_") and settings.get("digest_mode") == "batched":
            self._digest_buffer.setdefault(user_id, []).append(text)
            return
        try:
            await self.app.bot.send_message(chat_id=user_id, text=text)
            record_delivery_log(user_id, "telegram", message_type, "sent")
        except Exception as exc:  # noqa: BLE001
            record_delivery_log(user_id, "telegram", message_type, "failed", str(exc)[:250])
            raise

    async def _flush_digests(self) -> None:
        if not self._digest_buffer:
            return
        items = dict(self._digest_buffer)
        self._digest_buffer.clear()
        for user_id, messages in items.items():
            if not messages:
                continue
            text = "Watcher Digest\n\n" + "\n\n---\n\n".join(messages[:5])
            try:
                await self.app.bot.send_message(chat_id=user_id, text=text)
                record_delivery_log(user_id, "telegram", "watcher_digest", "sent")
            except Exception as exc:  # noqa: BLE001
                record_delivery_log(user_id, "telegram", "watcher_digest", "failed", str(exc)[:250])

    def _in_quiet_hours(self, user_id: int, now_utc: datetime) -> bool:
        settings = get_proactive_settings(user_id)
        start = str(settings.get("quiet_hours_start") or "").strip()
        end = str(settings.get("quiet_hours_end") or "").strip()
        if not start or not end:
            return False
        prefs = get_user_preferences(user_id)
        try:
            from zoneinfo import ZoneInfo

            local_now = now_utc.astimezone(ZoneInfo(prefs.timezone))
        except Exception:
            local_now = now_utc
        current_minutes = local_now.hour * 60 + local_now.minute
        sh, sm = _parse_hhmm(start)
        eh, em = _parse_hhmm(end)
        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em
        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes < end_minutes
        return current_minutes >= start_minutes or current_minutes < end_minutes

    def _compute_next_job_run(self, job: Dict[str, Any], settings: Dict[str, Any], now: datetime) -> datetime:
        schedule = job.get("schedule", {})
        job_type = job.get("job_type", "")
        if job_type == "morning_brief":
            target = settings.get("morning_brief_time", "08:00")
            hour, minute = _parse_hhmm(target)
            next_local = now.astimezone(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_local <= now:
                next_local += timedelta(days=1)
            return next_local
        if job_type == "calendar_nudge":
            return now + timedelta(minutes=int(schedule.get("interval_minutes", 30)))
        return now + timedelta(hours=1)

    def _fetch_weather_summary(self, city: str) -> str:
        from bot import fetch_weather

        return fetch_weather(city)

    def _fetch_price_usd(self, symbol: str) -> Optional[float]:
        pair = f"{symbol.upper()}-USD"
        url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
        resp = httpx.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return float(data["data"]["amount"])


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":", 1)
        hour = max(0, min(23, int(hh)))
        minute = max(0, min(59, int(mm)))
        return hour, minute
    except Exception:
        return 8, 0
