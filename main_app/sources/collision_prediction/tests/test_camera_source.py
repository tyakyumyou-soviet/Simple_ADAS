import time

import numpy as np

from src.input.camera import CameraSource


class _FakeCapture:
    def __init__(self, *_args):
        self.sequence = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def read(self):
        if self.released:
            return False, None
        self.sequence += 1
        time.sleep(0.002)
        frame = np.full((4, 4, 3), self.sequence % 255, dtype=np.uint8)
        return True, frame

    def set(self, *_args) -> bool:
        return True

    def get(self, *_args) -> float:
        return 30.0

    def release(self) -> None:
        self.released = True


def test_camera_source_returns_latest_frame_and_counts_skips(monkeypatch) -> None:
    monkeypatch.setattr("src.input.camera.cv2.VideoCapture", _FakeCapture)
    source = CameraSource(0)
    source.open()
    try:
        ok, first = source.read()
        assert ok
        first_timestamp = source.timestamp
        time.sleep(0.025)
        ok, latest = source.read()
        assert ok
        assert int(latest[0, 0, 0]) > int(first[0, 0, 0])
        assert source.timestamp > first_timestamp
        assert source.dropped_frames > 0
    finally:
        source.close()
