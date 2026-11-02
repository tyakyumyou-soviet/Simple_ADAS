from __future__ import annotations

import cv2
import numpy as np


class FrameEnhancer:
    """軽量視認性補正: 暗いシーンで gamma LUT による明るさ／露出ブーストのみ。

    YOLO が暗所で対象を見落とさないようにするのが目的なので、
    LAB/CLAHE/デノイズ/HDR は持たず、単一の `cv2.LUT` で済ませる。
    """

    def __init__(
        self,
        enabled: bool = True,
        gamma: float = 0.6,
        dark_threshold: float = 70.0,
        detect_every_n: int = 8,
    ):
        self.enabled = enabled
        self.dark_threshold = dark_threshold
        self.detect_every_n = max(1, detect_every_n)
        self._lut = self._build_gamma_lut(gamma)
        self._frame_counter = 0
        self._cached_dark = False

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, dict[str, bool]]:
        if not self.enabled:
            return frame, {"night": False, "hdr": False}
        if self._frame_counter % self.detect_every_n == 0:
            self._cached_dark = self._is_low_light(frame)
        self._frame_counter += 1
        if not self._cached_dark:
            return frame, {"night": False, "hdr": False}
        return cv2.LUT(frame, self._lut), {"night": True, "hdr": False}

    def _is_low_light(self, frame: np.ndarray) -> bool:
        small = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) < self.dark_threshold

    @staticmethod
    def _build_gamma_lut(gamma: float) -> np.ndarray:
        values = np.arange(256, dtype=np.float32) / 255.0
        return np.clip((values ** gamma) * 255.0, 0, 255).astype(np.uint8)
