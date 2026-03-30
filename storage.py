import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

DB_PATH = Path(__file__).with_name("bob.db")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_storage() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
                language TEXT NOT NULL DEFAULT 'en',
                response_style TEXT NOT NULL DEFAULT 'normal',
                selected_model TEXT NOT NULL DEFAULT 'models/gemini-3.1-flash-lite-preview',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_contexts (
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                original_prompt TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS callback_events (
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_transcriptions (
                user_id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                file_id TEXT,
                file_name TEXT,
                mime_type TEXT,
                content_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_user_created
                ON conversation_messages(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS proactive_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                job_type TEXT NOT NULL,
                schedule_kind TEXT NOT NULL,
                schedule_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                next_run_at TEXT NOT NULL,
                last_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                watcher_type TEXT NOT NULL,
                query TEXT NOT NULL,
                params_json TEXT NOT NULL DEFAULT '{}',
                enabled INTEGER NOT NULL DEFAULT 1,
                cooldown_minutes INTEGER NOT NULL DEFAULT 60,
                last_checked_at TEXT,
                next_check_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proactive_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL,
                sent_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_proactive_events_dedupe
                ON proactive_events(user_id, event_type, dedupe_key);

            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                message_type TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proactive_settings (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                quiet_hours_start TEXT NOT NULL DEFAULT '',
                quiet_hours_end TEXT NOT NULL DEFAULT '',
                morning_brief_time TEXT NOT NULL DEFAULT '08:00',
                digest_mode TEXT NOT NULL DEFAULT 'instant',
                updated_at TEXT NOT NULL
            );
            """
        )
        # Lightweight schema migration for existing databases.
        try:
            conn.execute(
                "ALTER TABLE user_preferences ADD COLUMN selected_model TEXT NOT NULL DEFAULT 'models/gemini-3.1-flash-lite-preview'"
            )
        except sqlite3.OperationalError:
            # Column already exists.
            pass


def get_user_pref_row(user_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            return dict(row)

        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO user_preferences (user_id, timezone, language, response_style, selected_model, created_at, updated_at)
            VALUES (?, 'America/Los_Angeles', 'en', 'normal', 'models/gemini-3.1-flash-lite-preview', ?, ?)
            """,
            (user_id, now, now),
        )
        return {
            "user_id": user_id,
            "timezone": "America/Los_Angeles",
            "language": "en",
            "response_style": "normal",
            "selected_model": "models/gemini-3.1-flash-lite-preview",
            "created_at": now,
            "updated_at": now,
        }


def update_user_pref(user_id: int, key: str, value: str) -> None:
    if key not in {"timezone", "language", "response_style", "selected_model"}:
        raise ValueError(f"Unsupported preference key: {key}")

    now = utc_now_iso()
    with get_conn() as conn:
        get_user_pref_row(user_id)
        conn.execute(
            f"UPDATE user_preferences SET {key} = ?, updated_at = ? WHERE user_id = ?",
            (value, now, user_id),
        )


def save_message_context(
    user_id: int,
    message_id: int,
    original_prompt: str,
    reply_text: str,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    now = utc_now_iso()
    payload = json.dumps(meta or {})
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO message_contexts
            (user_id, message_id, original_prompt, reply_text, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, message_id, original_prompt, reply_text, payload, now),
        )


def get_message_context(user_id: int, message_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM message_contexts WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["meta"] = json.loads(data.get("meta_json") or "{}")
    return data


def is_duplicate_callback(user_id: int, message_id: int, action: str, window_seconds: int = 3) -> bool:
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT created_at FROM callback_events
            WHERE user_id = ? AND message_id = ? AND action = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id, message_id, action),
        ).fetchall()

        if rows:
            last = datetime.fromisoformat(rows[0]["created_at"])
            if (now - last).total_seconds() <= window_seconds:
                return True

        conn.execute(
            "INSERT INTO callback_events (user_id, message_id, action, created_at) VALUES (?, ?, ?, ?)",
            (user_id, message_id, action, now.isoformat()),
        )
    return False


def save_pending_transcription(user_id: int, text: str) -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO pending_transcriptions (user_id, text, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET text = excluded.text, updated_at = excluded.updated_at
            """,
            (user_id, text, now, now),
        )


def get_pending_transcription(user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT text FROM pending_transcriptions WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["text"] if row else None


def clear_pending_transcription(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_transcriptions WHERE user_id = ?", (user_id,))


def save_artifact(
    user_id: int,
    artifact_type: str,
    content_text: str,
    file_id: str = "",
    file_name: str = "",
    mime_type: str = "",
) -> int:
    now = utc_now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO artifacts (user_id, artifact_type, file_id, file_name, mime_type, content_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, artifact_type, file_id, file_name, mime_type, content_text, now),
        )
        return int(cur.lastrowid)


def get_latest_artifact(user_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def append_conversation_message(user_id: int, role: str, content_json: dict[str, Any]) -> None:
    now = utc_now_iso()
    payload = json.dumps(content_json)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO conversation_messages (user_id, role, content_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, role, payload, now),
        )


def load_recent_conversation(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content_json, created_at
            FROM conversation_messages
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    ordered = list(reversed(rows))
    return [
        {
            "role": row["role"],
            "content": json.loads(row["content_json"]),
            "created_at": row["created_at"],
        }
        for row in ordered
    ]


def trim_conversation(user_id: int, keep_last: int = 40) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            DELETE FROM conversation_messages
            WHERE user_id = ?
              AND id NOT IN (
                SELECT id
                FROM conversation_messages
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
              )
            """,
            (user_id, user_id, keep_last),
        )


def clear_conversation(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM conversation_messages WHERE user_id = ?", (user_id,))


def list_known_user_ids() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT user_id FROM user_preferences
            UNION
            SELECT DISTINCT user_id FROM message_contexts
            UNION
            SELECT DISTINCT user_id FROM callback_events
            UNION
            SELECT DISTINCT user_id FROM pending_transcriptions
            UNION
            SELECT DISTINCT user_id FROM artifacts
            UNION
            SELECT DISTINCT user_id FROM conversation_messages
            UNION
            SELECT DISTINCT user_id FROM proactive_jobs
            UNION
            SELECT DISTINCT user_id FROM watchers
            UNION
            SELECT DISTINCT user_id FROM proactive_events
            UNION
            SELECT DISTINCT user_id FROM delivery_log
            ORDER BY user_id
            """
        ).fetchall()
    return [int(r["user_id"]) for r in rows if r["user_id"] is not None]


def upsert_proactive_job(
    user_id: int,
    job_type: str,
    schedule_kind: str,
    schedule_json: dict[str, Any],
    next_run_at: str,
    enabled: bool = True,
) -> int:
    now = utc_now_iso()
    payload = json.dumps(schedule_json)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM proactive_jobs WHERE user_id = ? AND job_type = ?",
            (user_id, job_type),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE proactive_jobs
                SET schedule_kind = ?, schedule_json = ?, enabled = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (schedule_kind, payload, 1 if enabled else 0, next_run_at, now, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO proactive_jobs
            (user_id, job_type, schedule_kind, schedule_json, enabled, next_run_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, job_type, schedule_kind, payload, 1 if enabled else 0, next_run_at, now, now),
        )
        return int(cur.lastrowid)


def get_proactive_job(user_id: int, job_type: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM proactive_jobs WHERE user_id = ? AND job_type = ?",
            (user_id, job_type),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["schedule"] = json.loads(data.get("schedule_json") or "{}")
    return data


def list_due_proactive_jobs(now_iso: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM proactive_jobs
            WHERE enabled = 1 AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (now_iso,),
        ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["schedule"] = json.loads(data.get("schedule_json") or "{}")
        out.append(data)
    return out


def update_proactive_job_state(job_id: int, next_run_at: str, status: str, last_run_at: str) -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE proactive_jobs
            SET next_run_at = ?, last_status = ?, last_run_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_run_at, status, last_run_at, now, job_id),
        )


def set_proactive_job_enabled(user_id: int, job_type: str, enabled: bool) -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            "UPDATE proactive_jobs SET enabled = ?, updated_at = ? WHERE user_id = ? AND job_type = ?",
            (1 if enabled else 0, now, user_id, job_type),
        )


def upsert_proactive_setting(user_id: int, key: str, value: Union[str, int]) -> None:
    if key not in {"enabled", "quiet_hours_start", "quiet_hours_end", "morning_brief_time", "digest_mode"}:
        raise ValueError(f"Unsupported proactive setting: {key}")
    now = utc_now_iso()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT user_id FROM proactive_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO proactive_settings (user_id, enabled, quiet_hours_start, quiet_hours_end, morning_brief_time, digest_mode, updated_at)
                VALUES (?, 1, '', '', '08:00', 'instant', ?)
                """,
                (user_id, now),
            )
        conn.execute(
            f"UPDATE proactive_settings SET {key} = ?, updated_at = ? WHERE user_id = ?",
            (value, now, user_id),
        )


def get_proactive_settings(user_id: int) -> dict[str, Any]:
    now = utc_now_iso()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM proactive_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO proactive_settings (user_id, enabled, quiet_hours_start, quiet_hours_end, morning_brief_time, digest_mode, updated_at)
                VALUES (?, 1, '', '', '08:00', 'instant', ?)
                """,
                (user_id, now),
            )
            return {
                "user_id": user_id,
                "enabled": 1,
                "quiet_hours_start": "",
                "quiet_hours_end": "",
                "morning_brief_time": "08:00",
                "digest_mode": "instant",
                "updated_at": now,
            }
    return dict(row)


def upsert_watcher(
    user_id: int,
    watcher_type: str,
    query: str,
    params: dict[str, Any],
    cooldown_minutes: int = 60,
    check_every_minutes: int = 60,
) -> int:
    now = utc_now_iso()
    next_check_at = now
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO watchers
            (user_id, watcher_type, query, params_json, enabled, cooldown_minutes, next_check_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (user_id, watcher_type, query, json.dumps(params), cooldown_minutes, next_check_at, now, now),
        )
        return int(cur.lastrowid)


def list_watchers(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watchers WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["params"] = json.loads(data.get("params_json") or "{}")
        out.append(data)
    return out


def list_due_watchers(now_iso: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM watchers
            WHERE enabled = 1 AND next_check_at <= ?
            ORDER BY next_check_at ASC
            """,
            (now_iso,),
        ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["params"] = json.loads(data.get("params_json") or "{}")
        out.append(data)
    return out


def update_watcher_schedule(watcher_id: int, next_check_at: str, last_checked_at: str) -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE watchers
            SET next_check_at = ?, last_checked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_check_at, last_checked_at, now, watcher_id),
        )


def set_watcher_enabled(user_id: int, watcher_id: int, enabled: bool) -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            "UPDATE watchers SET enabled = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (1 if enabled else 0, now, watcher_id, user_id),
        )


def delete_watcher(user_id: int, watcher_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watchers WHERE id = ? AND user_id = ?", (watcher_id, user_id))


def record_proactive_event(
    user_id: int,
    event_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    status: str = "sent",
) -> bool:
    now = utc_now_iso()
    with get_conn() as conn:
        try:
            conn.execute(
                """
                INSERT INTO proactive_events (user_id, event_type, dedupe_key, payload_json, occurred_at, sent_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, event_type, dedupe_key, json.dumps(payload), now, now, status),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def record_delivery_log(user_id: int, channel: str, message_type: str, status: str, error: str = "") -> None:
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO delivery_log (user_id, channel, message_type, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, channel, message_type, status, error, now),
        )
