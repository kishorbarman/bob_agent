import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage
from preferences import get_user_preferences, set_language, set_response_style, set_timezone
from storage import init_storage


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


if __name__ == "__main__":
    unittest.main()
