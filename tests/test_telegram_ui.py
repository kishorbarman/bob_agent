import unittest

from telegram_ui import (
    make_callback,
    model_keyboard,
    parse_callback_data,
    render_card,
    style_keyboard,
)


class TelegramUiTests(unittest.TestCase):
    def test_callback_roundtrip(self):
        data = make_callback("summarize", "42")
        parsed = parse_callback_data(data)
        self.assertEqual(parsed["action"], "summarize")
        self.assertEqual(parsed["v"], "1")
        self.assertEqual(parsed["ctx"], "42")

    def test_render_card(self):
        self.assertTrue(render_card("weather", "abc").startswith("Weather Update"))
        self.assertTrue(render_card("news", "abc").startswith("News Brief"))

    def test_model_keyboard(self):
        kb = model_keyboard("models/gemini-3.1-pro-preview")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("Pro ✓", labels)

    def test_style_keyboard(self):
        kb = style_keyboard("normal")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("Normal (current)", labels)


if __name__ == "__main__":
    unittest.main()
