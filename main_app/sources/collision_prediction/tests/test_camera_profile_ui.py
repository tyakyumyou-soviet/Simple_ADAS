import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PySide6.QtWidgets import QApplication

from src.input.camera import CameraSource
from src.ui.inference_thread import InferenceThread
from src.ui.main_window import MainWindow
from src.utils.config import load_config


class _Signal:
    def connect(self, _callback):
        pass


class _Thread:
    def __init__(self, source, cfg):
        self.source = source
        self.cfg = copy.deepcopy(cfg)
        self.frame_ready = _Signal()
        self.error = _Signal()
        self.finished_signal = _Signal()
        self.running = False
        self.paused = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.running = False

    def wait(self, _timeout):
        return True

    def apply_settings(self, cfg):
        self.cfg = copy.deepcopy(cfg)

    def pause(self):
        self.paused = True


class CameraProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        cfg = load_config("config/default.yaml")
        self.one = copy.deepcopy(cfg)
        self.two = copy.deepcopy(cfg)
        self.one['hailo_scene'] = {'depth_enabled': False, 'depth_update_hz': 1.0}
        self.two['hailo_scene'] = {'depth_enabled': False, 'depth_update_hz': 1.0}
        self.one["detector"]["every_n_frames"] = 6
        self.one["lane"]["every_n_frames"] = 2
        self.one["lane"]["auto_depth"] = False
        self.one["detector"]["weights"] = "models/hailo8/yolo26n.hef"
        self.two["detector"]["every_n_frames"] = 3
        self.two["lane"]["every_n_frames"] = 7
        self.two["lane"]["auto_depth"] = True
        self.two["detector"]["weights"] = "models/hailo8/yolo26s.hef"
        self.paths = [root / "one.yaml", root / "two.yaml"]
        for path, data in zip(self.paths, (self.one, self.two)):
            path.write_text(yaml.safe_dump(data))
        self.list_patch = patch.object(MainWindow, "_build_profile_list",
                                       return_value=[("one", str(self.paths[0])), ("two", str(self.paths[1]))])
        self.thread_patch = patch("src.ui.main_window.InferenceThread", _Thread)
        self.sizes_patch = patch.object(CameraSource, "supported_sizes", return_value=[])
        self.sizes_patch.start()
        self.list_patch.start()
        self.thread_patch.start()
        self.window = MainWindow(self.paths[0].resolve())

    def tearDown(self):
        self.window.close()
        self.thread_patch.stop()
        self.sizes_patch.stop()
        self.list_patch.stop()
        self.temp.cleanup()

    def test_curve_checkbox_is_off_by_default_and_updates_settings(self):
        w = self.window
        self.assertFalse(w.chk_curves.isChecked())
        w.chk_curves.setChecked(True)
        self.assertTrue(w.cfg['ui']['curve_lanes'])
        w.chk_curves.setChecked(False)
        self.assertFalse(w.cfg['ui']['curve_lanes'])

    def test_camera_supported_sizes_replace_generic_options(self):
        self.sizes_patch.stop()
        with patch.object(CameraSource, 'supported_sizes', return_value=[(1280, 720), (640, 480), (352, 288), (320, 240)]):
            window = MainWindow(self.paths[0].resolve())
            self.assertEqual([window.quality_combo.itemText(i) for i in range(window.quality_combo.count())],
                             ['1280×720', '640×480', '352×288', '320×240'])
            window.close()
        self.sizes_patch.start()

    def test_processing_width_restarts_camera_with_matching_capture_request(self):
        w = self.window
        w._last_source_factory = lambda: CameraSource(0)
        w._start_source()
        old = w.thread
        index = next(i for i, (_, width) in enumerate(w._quality_options) if width == 960)
        w.quality_combo.setCurrentIndex(index)
        self.assertIsNot(w.thread, old)
        self.assertEqual((w.thread.source.requested_width, w.thread.source.requested_height), (960, 540))
        index = next(i for i, (_, width) in enumerate(w._quality_options) if width == 320)
        w.quality_combo.setCurrentIndex(index)
        self.assertEqual((w.thread.source.requested_width, w.thread.source.requested_height), (320, 240))

    def test_camera_uses_complete_profile_and_restarts_on_profile_change(self):
        w = self.window
        self.assertEqual(w.profile_combo.currentText(), "one")
        w._last_source_factory = lambda: CameraSource(0)
        w._start_source()
        old = w.thread
        expected_one = copy.deepcopy(self.one)
        expected_one['hailo_scene'] = {'depth_enabled': False, 'depth_update_hz': 1.0}
        self.assertEqual(old.cfg, expected_one)
        w.profile_combo.setCurrentIndex(1)
        self.assertFalse(old.running)
        self.assertIsNot(w.thread, old)
        self.assertTrue(w.thread.running)
        expected_two = copy.deepcopy(self.two)
        expected_two['hailo_scene'] = {'depth_enabled': False, 'depth_update_hz': 1.0}
        self.assertEqual(w.thread.cfg, expected_two)
        self.assertEqual(w.depth_mode_combo.currentIndex(), 0)
        self.assertEqual(w.yolo_combo.currentText(), "Hailo-8 YOLO26s (AI HAT+)")

    def test_one_control_does_not_overwrite_other_profile_values(self):
        w = self.window
        w.chk_lanes.setChecked(not w.chk_lanes.isChecked())
        self.assertEqual(w.cfg["lane"]["every_n_frames"], 2)
        self.assertEqual(w.cfg["detector"]["every_n_frames"], 6)
        self.assertFalse(w.cfg["lane"]["auto_depth"])

    def test_depth_interval_live_update_and_profile_switch_loads_saved_setting(self):
        w = self.window
        w._last_source_factory = lambda: CameraSource(0)
        w._start_source()
        combo = w.ai_depth_interval_combo
        self.assertEqual([combo.itemData(i) for i in range(5)], [.2, .4, .6, .8, 1.])
        combo.setCurrentIndex(0)
        w.chk_ai_depth.setChecked(True)
        self.assertEqual(w.thread.cfg['hailo_scene']['depth_update_hz'], 5.)
        self.assertTrue(w.thread.cfg['hailo_scene']['depth_enabled'])
        w.profile_combo.setCurrentIndex(1)
        self.assertEqual(w.ai_depth_interval_combo.currentData(), 1.)
        self.assertEqual(w.thread.cfg['hailo_scene']['depth_update_hz'], 1.)

    def test_save_selected_profile_is_independent_and_survives_switch(self):
        w = self.window
        w.ai_depth_interval_combo.setCurrentIndex(0)
        w.chk_ai_depth.setChecked(True)
        w.yolo_combo.setCurrentIndex(3)
        w.btn_save_profile.click()
        saved_one = load_config(self.paths[0])
        self.assertEqual(saved_one['detector']['weights'], 'models/hailo8/yolo26m.hef')
        self.assertEqual(saved_one['hailo_scene']['depth_update_hz'], 5.)
        self.assertEqual(load_config(self.paths[1]), self.two)
        w.profile_combo.setCurrentIndex(1)
        w.ai_depth_interval_combo.setCurrentIndex(2)
        w.btn_save_profile.click()
        w.profile_combo.setCurrentIndex(0)
        self.assertEqual(w.yolo_combo.currentIndex(), 3)
        self.assertEqual(w.ai_depth_interval_combo.currentData(), .2)
        w.profile_combo.setCurrentIndex(1)
        self.assertEqual(w.ai_depth_interval_combo.currentData(), .6)

    def test_only_four_hailo_models_are_available(self):
        self.assertEqual([weight for _, weight in self.window._yolo_options], [
            'models/hailo8/yolov8m.hef', 'models/hailo8/yolo26n.hef',
            'models/hailo8/yolo26s.hef', 'models/hailo8/yolo26m.hef'])
        self.assertEqual(self.window.btn_save_profile.text(), 'このプロファイルに保存')

    def test_real_profile_list_contains_only_the_two_pi_profiles(self):
        self.list_patch.stop()
        try:
            profiles = self.window._build_profile_list()
            self.assertEqual([label for label, _ in profiles],
                             ['Pi 高速 (AI HAT+)', 'Pi 高速2 (AI HAT+)'])
        finally:
            self.list_patch.start()

    def test_inference_thread_uses_settings_snapshot(self):
        cfg = copy.deepcopy(self.one)
        thread = InferenceThread(CameraSource(0), cfg)
        cfg["detector"]["weights"] = "changed"
        self.assertNotEqual(thread.cfg["detector"]["weights"], "changed")
        thread.apply_settings(cfg)
        cfg["detector"]["weights"] = "changed again"
        self.assertEqual(thread._pending_settings["detector"]["weights"], "changed")


if __name__ == "__main__":
    unittest.main()
