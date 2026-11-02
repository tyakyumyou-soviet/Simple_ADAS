from __future__ import annotations

from pathlib import Path
from collections import deque

import cv2
import numpy as np


class VideoFileSource:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.path)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open video file: {self.path}")

    def read(self) -> tuple[bool, np.ndarray]:
        if self._cap is None:
            raise RuntimeError("Video source is not opened")
        return self._cap.read()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def fps(self) -> float:
        if self._cap is None:
            return 30.0
        return float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)

    @property
    def frame_size(self) -> tuple[int, int]:
        if self._cap is None:
            return (0, 0)
        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return (width, height)

    @property
    def frame_count(self) -> int | None:
        if self._cap is None:
            return None
        count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        return count if count > 0 else None

    def seek(self, frame_idx: int) -> bool:
        if self._cap is None:
            return False
        return bool(self._cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx)))


class RealtimeVideoSource(VideoFileSource):
    """Paced video source which discards overdue frames and carries timestamps."""
    requested_width = requested_height = 0
    dropped_frames = 0

    def __init__(self, path: str | Path):
        super().__init__(path)
        self._next_index = 0
        self._clock_start = 0.0
        self._pause_started = None
        self._read_times = deque(maxlen=60)

    def open(self) -> None:
        import time
        super().open()
        self._next_index = 0
        self.dropped_frames = 0
        self._read_times.clear()
        self._clock_start = time.monotonic()

    @property
    def measured_fps(self) -> float | None:
        if len(self._read_times) < 2:
            return None
        elapsed = self._read_times[-1] - self._read_times[0]
        return (len(self._read_times) - 1) / elapsed if elapsed > 0 else None

    def read_with_metadata(self):
        import time
        if self._cap is None:
            raise RuntimeError('Video source is not opened')
        fps = max(self.fps, 1.0)
        now = time.monotonic()
        due = self._clock_start + self._next_index / fps
        if due > now:
            time.sleep(min(due - now, 0.2))
            now = time.monotonic()
        desired = int(max(0.0, now - self._clock_start) * fps)
        if desired > self._next_index + 1:
            count = self.frame_count
            target = min(desired, count - 1) if count else desired
            # Skip a bounded number of frames sequentially. Repeated random seeks
            # in inter-frame codecs can be much slower than grabbing frames.
            for _ in range(min(4, max(0, target - self._next_index))):
                if not self._cap.grab():
                    break
                self._next_index += 1
                self.dropped_frames += 1
        index = self._next_index
        ok, frame = self.read()
        if ok:
            self._next_index += 1
        captured = time.monotonic()
        if ok:
            self._read_times.append(captured)
        return ok, frame, captured, index + 1

    def seek(self, frame_idx: int) -> bool:
        import time
        index = max(0, int(frame_idx))
        if super().seek(index):
            self._next_index = index
            self._clock_start = time.monotonic() - index / max(self.fps, 1.0)
            return True
        return False

    def pause_clock(self) -> None:
        import time
        if self._pause_started is None:
            self._pause_started = time.monotonic()

    def resume_clock(self) -> None:
        import time
        if self._pause_started is not None:
            self._clock_start += time.monotonic() - self._pause_started
            self._pause_started = None
