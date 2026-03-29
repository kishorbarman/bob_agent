import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
