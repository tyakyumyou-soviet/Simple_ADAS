"""動画生成から実際の既存パイプラインまでを通す統合テスト。"""
import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from main_window import MainWindow

PROJECT = Path(os.environ.get('INTEGRATION_ADAS_PROJECT', Path(__file__).resolve().parent.parent / 'sources' / 'collision_prediction'))


class VideoIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_real_pipeline_displays_a_frame_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 'sample.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (160, 120))
            self.assertTrue(writer.isOpened())
            for i in range(30):
                writer.write(np.full((120, 160, 3), i * 5, dtype=np.uint8))
            writer.release()
            window = MainWindow(PROJECT)
            self.assertTrue(window.start_video(video))
            worker = window.worker
            loop = QEventLoop()
            frames, errors = [], []
            def on_frame(frame, meta):
                frames.append(frame)
                window.stop_video()
            worker.frame_ready.connect(on_frame)
            worker.error.connect(errors.append)
            worker.finished.connect(loop.quit)
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            if worker.isRunning():
                worker.stop()
                worker.wait(5000)
                self.fail('video pipeline timed out')
            self.app.processEvents()
            self.assertEqual(errors, [])
            self.assertGreater(len(frames), 0)
            self.assertEqual(frames[0].shape[2], 3)
            self.assertIsNone(window.worker)
            self.assertFalse(window.stop_video_button.isEnabled())
            self.assertTrue(window.open_video_button.isEnabled())
            window.close()

    def test_missing_file_does_not_start_worker(self):
        window = MainWindow(PROJECT)
        self.assertFalse(window.start_video(Path('/no/such/video.mp4')))
        self.assertIsNone(window.worker)
        self.assertIn('動画を開けません', window.video_label.text())
        window.close()
