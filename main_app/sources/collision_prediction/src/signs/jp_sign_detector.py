from __future__ import annotations

import cv2
import numpy as np

from src.signs.signal_color import classify_signal_color
from src.types import Detection


class JpSignDetector:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def detect(self, frame: np.ndarray, vehicle_bboxes: list | None = None
               ) -> tuple[list[Detection], list[Detection]]:
        """信号検出。vehicle_bboxes と重なる候補（テールランプ等）は除外する。"""
        if not self.enabled:
            return [], []
        signals = self._detect_signal_lights(frame)
        if vehicle_bboxes:
            signals = [s for s in signals if not _overlaps_any(s.bbox, vehicle_bboxes)]
        return [], signals

    def _detect_signal_lights(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]
        # ROI を画面上 40% に限定（信号は通常画面上部、テールランプは下部）
        upper_limit = int(height * 0.40)
        upper = frame[: upper_limit]
        hsv = cv2.cvtColor(upper, cv2.COLOR_BGR2HSV)
        masks = [
            cv2.inRange(hsv, (0, 90, 90), (10, 255, 255)),
            cv2.inRange(hsv, (170, 90, 90), (180, 255, 255)),
            cv2.inRange(hsv, (18, 90, 90), (38, 255, 255)),
            cv2.inRange(hsv, (45, 70, 70), (95, 255, 255)),
        ]
        mask = masks[0]
        for other in masks[1:]:
            mask = cv2.bitwise_or(mask, other)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 12 or area > width * height * 0.02:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if not (0.4 <= w / max(h, 1) <= 2.6):
                continue
            pad = 6
            y1 = max(0, y - pad)
            y2 = min(upper.shape[0], y + h + pad)
            x1 = max(0, x - pad)
            x2 = min(width, x + w + pad)
            label = classify_signal_color(upper[y1:y2, x1:x2])
            if label is not None:
                detections.append(Detection((float(x1), float(y1), float(x2), float(y2)), label, 0.5))
        return detections[:5]


def _overlaps_any(bbox: tuple[float, float, float, float],
                  others: list[tuple[float, float, float, float]],
                  iou_threshold: float = 0.05) -> bool:
    """bbox がいずれかの BB と少しでも重なれば True（IoU > threshold）。"""
    x1, y1, x2, y2 = bbox
    for ox1, oy1, ox2, oy2 in others:
        # 拡張: 車両 BB を 10% 上に伸ばす（テールランプは車両の上端付近にあるため誤検出されやすい）
        oy1 -= (oy2 - oy1) * 0.1
        iw = max(0.0, min(x2, ox2) - max(x1, ox1))
        ih = max(0.0, min(y2, oy2) - max(y1, oy1))
        inter = iw * ih
        if inter <= 0:
            continue
        union = (x2 - x1) * (y2 - y1) + (ox2 - ox1) * (oy2 - oy1) - inter
        if inter / max(union, 1e-6) > iou_threshold:
            return True
    return False
