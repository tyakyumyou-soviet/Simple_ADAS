import cv2
import numpy as np

from src.detection.blind_check import BlindnessDetector


def test_dark_scene_with_visible_texture_is_not_blind() -> None:
    frame = np.full((180, 320, 3), 18, dtype=np.uint8)
    cv2.line(frame, (40, 170), (130, 60), (55, 55, 55), 3)
    cv2.line(frame, (280, 170), (190, 60), (55, 55, 55), 3)

    detector = BlindnessDetector(no_detect_seconds=0.5)
    detector.update(frame, has_detections=False, timestamp=0.0)
    blind, reason = detector.update(frame, has_detections=False, timestamp=1.0)

    assert blind is False
    assert reason is None


def test_nearly_black_flat_scene_is_blind() -> None:
    frame = np.full((180, 320, 3), 3, dtype=np.uint8)

    detector = BlindnessDetector(no_detect_seconds=0.5)
    detector.update(frame, has_detections=False, timestamp=0.0)
    blind, reason = detector.update(frame, has_detections=False, timestamp=1.0)

    assert blind is True
    assert reason is not None
