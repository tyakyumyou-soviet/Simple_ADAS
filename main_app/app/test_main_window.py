"""Run with QT_QPA_PLATFORM=offscreen python -m unittest test_main_window."""
import unittest
from PySide6.QtWidgets import QApplication
from main_window import ASSETS, MainWindow


class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()

    def test_disconnected_controls_and_status(self):
        self.assertFalse(self.window.event_button.isEnabled())
        self.assertFalse(self.window.transfer_button.isEnabled())
        self.assertIn("未接続", self.window.status_label.text())
        for name in ("home", "event", "reverse", "settings"):
            self.assertGreater((ASSETS / f"{name}.png").stat().st_size, 0)

    def test_reverse_and_settings_navigation(self):
        self.assertFalse(self.window.reverse_button.isChecked())
        self.assertEqual(self.window.reverse_button.accessibleName(), "リバース画面に切り替える")
        front_icon = self.window.reverse_button.icon().pixmap(34, 34).toImage()
        self.window.reverse_button.click()
        self.assertTrue(self.window.reverse_button.isChecked())
        self.assertEqual(self.window.reverse_button.accessibleName(), "フロント画面に戻す")
        self.assertNotEqual(front_icon, self.window.reverse_button.icon().pixmap(34, 34).toImage())
        self.assertIn("リア映像：未接続", self.window.video_label.text())
        self.window.reverse_button.click()
        self.assertIn("フロント映像：未接続", self.window.video_label.text())
        self.assertFalse(self.window.reverse_button.isChecked())
        self.assertEqual(self.window.reverse_button.accessibleName(), "リバース画面に切り替える")
        self.window.settings_button.click()
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertEqual(self.window.settings_button.accessibleName(), "映像画面に戻る")
        self.window.settings_button.click()
        self.assertEqual(self.window.pages.currentIndex(), 0)

    def test_touch_targets_fit_small_display(self):
        for width, height in ((1024, 600), (800, 480)):
            self.window.resize(width, height)
            self.window.show()
            self.app.processEvents()
            self.assertEqual((self.window.width(), self.window.height()), (width, height))
            buttons = (self.window.reverse_button, self.window.event_button, self.window.settings_button)
            for button in buttons:
                self.assertGreaterEqual(button.height(), 48)
                self.assertLessEqual(button.height(), 52)
                self.assertGreaterEqual(button.width(), 100)
                self.assertTrue(button.isVisible())
                self.assertEqual(button.text(), "")
                self.assertFalse(button.icon().isNull())
                self.assertTrue(button.accessibleName())
                self.assertLess(button.mapTo(self.window, button.rect().bottomRight()).y(),
                                self.window.pages.mapTo(self.window, self.window.pages.rect().topLeft()).y())
                self.assertLessEqual(button.mapTo(self.window, button.rect().bottomRight()).x(), width)
            self.assertIs(self.window.status_label.parentWidget(), self.window.video_label)
            self.assertTrue(self.window.status_label.isVisible())
            self.window.show_settings()
            self.app.processEvents()
            self.assertTrue(self.window.settings_button.isVisible())
            self.assertGreaterEqual(self.window.open_video_button.height(), 48)
            self.assertGreaterEqual(self.window.transfer_button.height(), 48)
            self.assertGreaterEqual(self.window.shutdown_button.height(), 48)
            self.assertFalse(self.window.shutdown_button.isEnabled())
            self.window.show_home()


if __name__ == "__main__":
    unittest.main()
