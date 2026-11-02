from __future__ import annotations

import cv2
import numpy as np


def resize_for_processing(frame: np.ndarray, max_width: int | None, *, upscale: bool = False) -> tuple[np.ndarray, float]:
    if not max_width or max_width <= 0:
        return frame, 1.0
    height, width = frame.shape[:2]
    if width == max_width or (width < max_width and not upscale):
        return frame, 1.0
    scale = max_width / width
    interpolation = cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA
    resized = cv2.resize(frame, (max_width, max(1, int(height * scale))), interpolation=interpolation)
    return resized, scale
