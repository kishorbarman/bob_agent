import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from google import genai

from storage import DB_PATH


def _check_db() -> tuple[bool, str]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1").fetchone()
        return True, f"SQLite OK ({DB_PATH})"
    except Exception as exc:  # noqa: BLE001
        return False, f"SQLite check failed: {exc}"


def _check_gemini() -> tuple[bool, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return False, "GEMINI_API_KEY is missing"

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        return False, f"Gemini client init failed: {exc}"

    if os.getenv("HEALTHCHECK_SKIP_GEMINI_API", "false").strip().lower() in {"1", "true", "yes"}:
        return True, "Gemini client init OK (API ping skipped)"

    model = os.getenv("HEALTHCHECK_MODEL", "models/gemini-3.1-flash-lite-preview")
    try:
        client.models.get(model=model)
        return True, f"Gemini API OK (model reachable: {model})"
    except Exception as exc:  # noqa: BLE001
        return False, f"Gemini API check failed for {model}: {exc}"


def _check_token_file() -> tuple[bool, str]:
    token_path = Path("token.json")
    if not token_path.exists():
        return True, "token.json not found (Google integrations may require re-auth)"

    age_hours = (time.time() - token_path.stat().st_mtime) / 3600.0
    hint = f"token.json present (last updated {age_hours:.1f}h ago)"

    try:
        payload = json.loads(token_path.read_text())
        expiry = payload.get("expiry")
        if expiry:
            hint += f"; expiry={expiry}"
    except Exception:
        pass
    return True, hint


def main() -> int:
    checks = [
        ("db", _check_db),
        ("gemini", _check_gemini),
        ("google_token", _check_token_file),
    ]
    failures = 0
    for name, fn in checks:
        ok, detail = fn()
        prefix = "OK" if ok else "FAIL"
        print(f"[{prefix}] {name}: {detail}")
        if not ok:
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
