import cv2
import numpy as np

from src.detection.fallback_detector import FallbackVehicleDetector


def test_fallback_detector_returns_vehicle_candidate() -> None:
    frame = np.full((240, 360, 3), 80, dtype=np.uint8)
    cv2.rectangle(frame, (145, 145), (220, 190), (60, 120, 220), -1)
    cv2.rectangle(frame, (155, 152), (210, 170), (30, 30, 40), -1)

    detections = FallbackVehicleDetector().detect(frame)

    assert detections
    assert detections[0].cls in {"car", "person"}


def test_fallback_detector_returns_empty_when_no_features() -> None:
    """検出特徴がない一様フレームでは何も返さない（偽検出禁止）。"""
    frame = np.full((240, 360, 3), 80, dtype=np.uint8)

    detections = FallbackVehicleDetector().detect(frame)

    assert detections == []
