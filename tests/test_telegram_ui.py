import unittest

from telegram_ui import make_callback, parse_callback_data, quick_actions_keyboard, render_card


class TelegramUiTests(unittest.TestCase):
    def test_callback_roundtrip(self):
        data = make_callback("summarize", "42")
        parsed = parse_callback_data(data)
        self.assertEqual(parsed["action"], "summarize")
        self.assertEqual(parsed["v"], "1")
        self.assertEqual(parsed["ctx"], "42")

    def test_quick_action_keyboard_shape(self):
        kb = quick_actions_keyboard("99")
        self.assertEqual(len(kb.inline_keyboard), 2)
        self.assertEqual(len(kb.inline_keyboard[0]), 3)
        self.assertEqual(len(kb.inline_keyboard[1]), 3)

    def test_render_card(self):
        self.assertTrue(render_card("weather", "abc").startswith("Weather Update"))
        self.assertTrue(render_card("news", "abc").startswith("News Brief"))


if __name__ == "__main__":
    unittest.main()
