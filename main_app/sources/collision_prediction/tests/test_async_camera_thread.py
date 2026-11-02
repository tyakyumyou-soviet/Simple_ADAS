import os
import time
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer

from src.types import LaneInfo, SceneContext
from src.ui.async_camera_thread import AsyncCameraThread

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class _Camera:
    fps = 30.0
    frame_count = None
    dropped_frames = 0
    measured_fps = 30.0
    requested_width = 320
    requested_height = 240

    def __init__(self):
        self.seq = 0

    def open(self):
        pass

    def close(self):
        pass

    def read_with_metadata(self):
        time.sleep(1 / 30)
        self.seq += 1
        return True, np.zeros((240, 320, 3), dtype=np.uint8), time.monotonic(), self.seq


class _SlowPipeline:
    count = 0
    def __init__(self, cfg):
        self.hailo_depth_enabled = False

    def process(self, frame, idx, fps, display_size, timestamp, render):
        time.sleep(0.15)
        type(self).count += 1
        canvas = np.zeros((display_size[1], display_size[0], 3), dtype=np.uint8)
        ctx = SceneContext(idx, timestamp, canvas, canvas, [], [], None,
                           LaneInfo(None, None, None, None), None, [], [], None)
        return canvas, {'_render_context': ctx, 'alerts': [], 'detector_runs': self.count}

    def update_settings(self, cfg):
        pass

    def close(self):
        pass


class AsyncCameraTests(unittest.TestCase):
    def test_preview_continues_while_analysis_is_slow(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        _SlowPipeline.count = 0
        cfg = {'ui': {'max_process_width': 320, 'display_max_width': 320,
                      'display_fps': 30, 'result_max_age_ms': 500}}
        events, errors = [], []
        with patch('src.ui.async_camera_thread.Pipeline', _SlowPipeline):
            thread = AsyncCameraThread(_Camera(), cfg)
            def receive(_image, meta):
                events.append(meta)
                thread.acknowledge_frame()
            thread.frame_ready.connect(receive)
            thread.error.connect(errors.append)
            thread.finished_signal.connect(app.quit)
            QTimer.singleShot(1800, thread.stop)
            thread.start()
            app.exec()
            self.assertTrue(thread.wait(3000))
        self.assertFalse(errors)
        self.assertGreater(len(events), _SlowPipeline.count * 2)
        self.assertGreater(events[-1]['analysis_replaced_frames'], 0)
        self.assertTrue(any(not event['result_stale'] for event in events))


if __name__ == '__main__':
    unittest.main()
