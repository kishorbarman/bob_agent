import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage
from preferences import get_user_preferences, set_language, set_response_style, set_timezone
from storage import (
    append_conversation_message,
    clear_conversation,
    init_storage,
    load_recent_conversation,
    trim_conversation,
)


class StoragePreferenceTests(unittest.TestCase):
    def test_preferences_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with patch.object(storage, "DB_PATH", db_path):
                init_storage()
                user_id = 123

                p1 = get_user_preferences(user_id)
                self.assertEqual(p1.timezone, "America/Los_Angeles")
                self.assertEqual(p1.language, "en")
                self.assertEqual(p1.response_style, "normal")

                set_timezone(user_id, "UTC")
                set_language(user_id, "es")
                set_response_style(user_id, "short")

                p2 = get_user_preferences(user_id)
                self.assertEqual(p2.timezone, "UTC")
                self.assertEqual(p2.language, "es")
                self.assertEqual(p2.response_style, "short")

    def test_conversation_persistence_and_trim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            with patch.object(storage, "DB_PATH", db_path):
                init_storage()
                user_id = 999
                append_conversation_message(user_id, "user", {"text": "hello"})
                append_conversation_message(user_id, "model", {"text": "hi"})
                append_conversation_message(user_id, "user", {"text": "how are you"})

                rows = load_recent_conversation(user_id, limit=10)
                self.assertEqual(len(rows), 3)
                self.assertEqual(rows[0]["content"]["text"], "hello")
                self.assertEqual(rows[-1]["content"]["text"], "how are you")

                trim_conversation(user_id, keep_last=2)
                rows = load_recent_conversation(user_id, limit=10)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["content"]["text"], "hi")
                self.assertEqual(rows[1]["content"]["text"], "how are you")

                clear_conversation(user_id)
                rows = load_recent_conversation(user_id, limit=10)
                self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
