from __future__ import annotations

from pathlib import Path
import sys
import subprocess
import re
import threading
import time
from collections import deque

import cv2
import numpy as np


class CameraSource:
    @staticmethod
    def supported_sizes(index: int) -> list[tuple[int, int]]:
        if not sys.platform.startswith("linux"):
            return []
        try:
            result = subprocess.run(['v4l2-ctl', '-d', f'/dev/video{int(index)}', '--list-formats-ext'],
                                    capture_output=True, text=True, timeout=2, check=True)
        except (OSError, subprocess.SubprocessError):
            return []
        return sorted({(int(w), int(h)) for w, h in re.findall(r'Size:\s*Discrete\s+(\d+)x(\d+)', result.stdout)}, reverse=True)

    def __init__(self, index: int = 0, width: int = 0, height: int = 0, fps: float = 0, buffers: int = 4):
        self.index = index
        self.requested_width = max(0, int(width))
        self.requested_height = max(0, int(height))
        self.requested_fps = max(0.0, float(fps))
        self.requested_buffers = max(1, int(buffers))
        self._cap: cv2.VideoCapture | None = None
        self._capture_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_ready = threading.Condition()
        self._latest_frame: np.ndarray | None = None
        self._latest_timestamp = 0.0
        self._opened_at = 0.0
        self._latest_sequence = 0
        self._last_read_sequence = 0
        self._dropped_frames = 0
        self._capture_failed = False
        self._capture_times: deque[float] = deque(maxlen=60)

    def open(self) -> None:
        backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_V4L2
        self._cap = cv2.VideoCapture(self.index, backend)
        if not self._cap.isOpened():
            self._cap.release()
            self._cap = cv2.VideoCapture(self.index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera: {self.index}")
        if self.requested_width and self.requested_height:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_height)
        if self.requested_fps:
            self._cap.set(cv2.CAP_PROP_FPS, self.requested_fps)
        try:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, self.requested_buffers)
        except Exception:
            pass
        self._stop_event.clear()
        self._capture_failed = False
        self._latest_frame = None
        self._latest_timestamp = 0.0
        self._opened_at = time.monotonic()
        self._latest_sequence = 0
        self._last_read_sequence = 0
        self._dropped_frames = 0
        self._capture_times.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"camera-{self.index}-capture",
            daemon=True,
        )
        self._capture_thread.start()

    def read(self) -> tuple[bool, np.ndarray]:
        if self._cap is None:
            raise RuntimeError("Camera source is not opened")
        deadline = time.monotonic() + 1.0
        with self._frame_ready:
            while self._latest_sequence <= self._last_read_sequence and not self._capture_failed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, np.empty((0, 0, 3), dtype=np.uint8)
                self._frame_ready.wait(timeout=remaining)
            if self._latest_frame is None:
                return False, np.empty((0, 0, 3), dtype=np.uint8)
            skipped = self._latest_sequence - self._last_read_sequence - 1
            self._dropped_frames += max(0, skipped)
            self._last_read_sequence = self._latest_sequence
            return True, self._latest_frame

    def close(self) -> None:
        self._stop_event.set()
        with self._frame_ready:
            self._frame_ready.notify_all()
        thread = self._capture_thread
        if thread is not None:
            thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._capture_thread = None
        self._cap = None

    def _capture_loop(self) -> None:
        assert self._cap is not None
        while not self._stop_event.is_set():
            ok, frame = self._cap.read()
            if not ok:
                self._capture_failed = True
                with self._frame_ready:
                    self._frame_ready.notify_all()
                return
            with self._frame_ready:
                self._latest_frame = frame
                self._latest_timestamp = time.monotonic() - self._opened_at
                self._capture_times.append(self._latest_timestamp)
                self._latest_sequence += 1
                self._frame_ready.notify_all()

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
        return None

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def measured_fps(self) -> float | None:
        with self._frame_ready:
            if len(self._capture_times) < 2:
                return None
            elapsed = self._capture_times[-1] - self._capture_times[0]
            return (len(self._capture_times) - 1) / elapsed if elapsed > 0 else None

    @property
    def timestamp(self) -> float:
        return self._latest_timestamp

    def read_with_metadata(self) -> tuple[bool, np.ndarray, float, int]:
        """Read a frame and its matching capture timestamp and sequence atomically."""
        if self._cap is None:
            raise RuntimeError("Camera source is not opened")
        deadline = time.monotonic() + 1.0
        with self._frame_ready:
            while self._latest_sequence <= self._last_read_sequence and not self._capture_failed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, np.empty((0, 0, 3), dtype=np.uint8), 0.0, 0
                self._frame_ready.wait(timeout=remaining)
            if self._latest_frame is None:
                return False, np.empty((0, 0, 3), dtype=np.uint8), 0.0, 0
            self._dropped_frames += max(0, self._latest_sequence - self._last_read_sequence - 1)
            self._last_read_sequence = self._latest_sequence
            return True, self._latest_frame, self._opened_at + self._latest_timestamp, self._latest_sequence

    def seek(self, frame_idx: int) -> bool:
        return False

    @staticmethod
    def list_devices(max_index: int = 4) -> list[int]:
        """連続して 2 つ失敗したら打ち切る (OpenCV のノイズ警告を抑制)。"""
        if sys.platform.startswith("linux"):
            # Reading sysfs never opens or steals an active camera stream.
            devices = []
            for node in Path('/sys/class/video4linux').glob('video*'):
                try:
                    if (node / 'index').read_text().strip() == '0' and 'usb' in str(node.resolve()):
                        devices.append(int(node.name[5:]))
                except (OSError, ValueError):
                    continue
            return sorted(devices)
        found: list[int] = []
        consecutive_misses = 0
        for index in range(max_index):
            cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
            ok = cap.isOpened()
            if not ok:
                cap.release()
                cap = cv2.VideoCapture(index)
                ok = cap.isOpened()
            cap.release()
            if ok:
                found.append(index)
                consecutive_misses = 0
            else:
                consecutive_misses += 1
                if consecutive_misses >= 2 and found:
                    break
        return found
