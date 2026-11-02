from __future__ import annotations

import cv2
import numpy as np

from src.types import Detection


class FallbackVehicleDetector:
    """Lightweight visual fallback so the UI still shows candidates when YOLO is unavailable."""

    def detect(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]
        roi_y = int(height * 0.42)
        roi = frame[roi_y:, :]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 45, 120)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        saturated = cv2.inRange(hsv, (0, 45, 35), (180, 255, 255))
        color_detections = self._detections_from_color_mask(saturated, roi_y, width, height)
        if color_detections:
            return color_detections
        dark = cv2.inRange(hsv, (0, 0, 0), (180, 255, 75))
        appearance = cv2.bitwise_or(saturated, dark)
        appearance = cv2.morphologyEx(appearance, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        appearance = cv2.morphologyEx(appearance, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 7)), iterations=2)
        candidates_mask = cv2.bitwise_or(closed, appearance)
        contours, _ = cv2.findContours(candidates_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        min_area = max(250, int(width * height * 0.0008))
        max_area = int(width * height * 0.18)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < min_area or area > max_area:
                continue
            aspect = w / max(h, 1)
            if not 0.55 <= aspect <= 4.8:
                continue
            if y + h < roi.shape[0] * 0.20:
                continue
            x1, y1, x2, y2 = float(x), float(y + roi_y), float(x + w), float(y + h + roi_y)
            label = "person" if aspect < 0.9 and h > w else "car"
            detections.append(Detection((x1, y1, x2, y2), label, 0.20))
        detections = sorted(detections, key=lambda det: (det.bbox[2] - det.bbox[0]) * (det.bbox[3] - det.bbox[1]), reverse=True)[:12]
        return detections

    @staticmethod
    def _detections_from_color_mask(mask: np.ndarray, roi_y: int, width: int, height: int) -> list[Detection]:
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 5)))
        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        min_area = max(180, int(width * height * 0.0006))
        max_area = int(width * height * 0.08)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < min_area or area > max_area:
                continue
            aspect = w / max(h, 1)
            if not 0.35 <= aspect <= 3.8:
                continue
            if w > width * 0.38 or h > height * 0.40:
                continue
            if y + h < mask.shape[0] * 0.20:
                continue
            x1, y1, x2, y2 = float(x), float(y + roi_y), float(x + w), float(y + h + roi_y)
            label = "person" if aspect < 0.75 and h > w * 1.3 else "car"
            detections.append(Detection((x1, y1, x2, y2), label, 0.18))
        return sorted(detections, key=lambda det: (det.bbox[2] - det.bbox[0]) * (det.bbox[3] - det.bbox[1]), reverse=True)[:12]

