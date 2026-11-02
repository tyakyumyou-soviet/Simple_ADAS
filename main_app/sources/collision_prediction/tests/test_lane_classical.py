import cv2
import numpy as np

from src.lane.classical import ClassicalLaneDetector


def test_dashed_lane_segments_are_merged() -> None:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    for y in range(210, 350, 34):
        cv2.line(frame, (260 - (y - 210) // 5, y), (250 - (y - 210) // 5, y + 18), (245, 245, 245), 4)
        cv2.line(frame, (380 + (y - 210) // 5, y), (390 + (y - 210) // 5, y + 18), (245, 245, 245), 4)

    lanes, confidence = ClassicalLaneDetector().detect(frame)

    assert lanes.left_lane is not None
    assert lanes.right_lane is not None
    assert lanes.ego_lane_polygon is not None
    assert confidence > 0.0


def test_lane_detection_handles_reversed_line_segments() -> None:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    # OpenCV の HoughLinesP は線分端点の向きが揃わないことがある。
    cv2.line(frame, (250, 350), (285, 210), (230, 230, 230), 4)
    cv2.line(frame, (390, 350), (355, 210), (230, 230, 230), 4)

    lanes, confidence = ClassicalLaneDetector().detect(frame)

    assert lanes.left_lane is not None
    assert lanes.right_lane is not None
    assert confidence > 0.0


def test_low_contrast_lanes_are_detected_at_small_resolution() -> None:
    frame = np.full((180, 320, 3), 58, dtype=np.uint8)
    cv2.line(frame, (108, 179), (145, 105), (96, 96, 96), 3)
    cv2.line(frame, (212, 179), (175, 105), (96, 96, 96), 3)

    lanes, confidence = ClassicalLaneDetector(
        hough_threshold=12,
        min_line_length=10,
        max_line_gap=80,
    ).detect(frame)

    assert lanes.left_lane is not None
    assert lanes.right_lane is not None
    assert confidence > 0.0
