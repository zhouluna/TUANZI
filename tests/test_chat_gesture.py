"""Double-click opens chat. Sleep stays on the menu."""

import os
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from desktop_pet.app import HELP_TEXT, PetWindow


class FakeMouse:
    def __init__(self, button):
        self._button = button

    def button(self):
        return self._button

    def accept(self):
        return None


class ChatGestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("TUANZI_API_URL", None)
        cls.app = QApplication.instance() or QApplication([])
        cls.window = PetWindow()

    def test_help_points_double_click_at_chat(self):
        self.assertIn("双击：和团子说话", HELP_TEXT)
        self.assertNotIn("双击：休息", HELP_TEXT)
        self.assertIn("休息一下", HELP_TEXT)

    def test_double_click_opens_chat_without_sleeping(self):
        window = self.window
        window.sleeping = False
        window.mouseReleaseEvent(FakeMouse(Qt.MouseButton.LeftButton))
        self.assertTrue(window.click_timer.isActive())
        window.mouseDoubleClickEvent(FakeMouse(Qt.MouseButton.LeftButton))
        self.assertFalse(window.click_timer.isActive())
        self.assertFalse(window.sleeping)
        self.assertIsNotNone(window.chat)
        self.assertTrue(window.chat.isVisible())
        labels = [action.text() for action in window.build_menu().actions()]
        self.assertIn("休息一下", labels)
        self.assertIn("和团子说话", labels)

    def test_remote_plan_is_preferred_when_the_clip_exists(self):
        window = self.window
        window.remote.plan = {"clip": "groom", "pause_ms": 5300}
        chosen = window.resolve_activity()
        self.assertEqual(chosen, "groom")
        self.assertAlmostEqual(window.planned_pause, 5.3)
        window.planned_pause = None


if __name__ == "__main__":
    unittest.main()
