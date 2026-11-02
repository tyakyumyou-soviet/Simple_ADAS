import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer
from src.input.video_file import VideoFileSource
from src.ui.inference_thread import InferenceThread


class FakeVideo(VideoFileSource):
    def __init__(self):
        super().__init__('fake')
        self.index = 0
    def open(self): pass
    def close(self): pass
    @property
    def fps(self): return 30.0
    @property
    def frame_count(self): return 24
    def read(self):
        if self.index >= self.frame_count:
            return False, np.empty((0, 0, 3), np.uint8)
        self.index += 1
        return True, np.zeros((20, 30, 3), np.uint8)
    def seek(self, index):
        self.index = index
        return True


class SlowPipeline:
    seen = []
    rendered = []
    def __init__(self, cfg): pass
    def process(self, frame, idx, fps, display_size, timestamp, render):
        time.sleep(0.06)
        self.seen.append(idx)
        if render: self.rendered.append(idx)
        return frame, {}
    def update_settings(self, cfg): pass
    def close(self): pass


class VideoModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
    def run_mode(self, mode):
        SlowPipeline.seen = []
        SlowPipeline.rendered = []
        cfg = {'input': {'video_mode': mode}, 'ui': {'display_every_n_frames': 3}}
        with patch('src.ui.inference_thread.Pipeline', SlowPipeline):
            thread = InferenceThread(FakeVideo(), cfg)
            errors = []
            thread.error.connect(errors.append)
            thread.finished_signal.connect(self.app.quit)
            timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(thread.stop); timer.start(6000)
            thread.start(); self.app.exec(); thread.wait(3000); timer.stop()
        self.assertFalse(errors)
        return list(SlowPipeline.seen), list(SlowPipeline.rendered)
    def test_all_frames_and_realtime_modes(self):
        full, rendered = self.run_mode('all_frames')
        realtime, _ = self.run_mode('realtime')
        self.assertEqual(full, list(range(24)))
        self.assertEqual(rendered, list(range(0, 24, 3)))
        self.assertLess(len(realtime), len(full))
        self.assertEqual(realtime[-1], 23)

    def test_average_uses_processed_count_not_skipped_or_seeked_frame_index(self):
        thread = InferenceThread(FakeVideo(), {})
        frame = np.zeros((20, 30, 3), np.uint8)
        meta = thread._with_common_meta({}, 300, frame, frame, 1.0, 30., 31,
                                        0., 2., None, 31, 0.)
        self.assertAlmostEqual(meta['avg_realtime_ratio'], .5)
        self.assertAlmostEqual(meta['avg_lag_percent'], 50.)


if __name__ == '__main__':
    unittest.main()
