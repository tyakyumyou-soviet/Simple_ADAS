import cv2
import numpy as np

from src.lane.lane_detector import LaneDetector
from src.types import LaneInfo


def _detector() -> LaneDetector:
    return LaneDetector(
        method="ipm",
        min_confidence=0.05,
        ipm_min_lane_pixels=10,
        acquire_frames=2,
    )


def _lane_frame() -> np.ndarray:
    frame = np.zeros((203, 360, 3), dtype=np.uint8)
    cv2.line(frame, (40, 202), (145, 98), (255, 255, 255), 4)
    cv2.line(frame, (320, 202), (215, 98), (255, 255, 255), 4)
    return frame


def _reference_polygon() -> np.ndarray:
    return np.array([(40, 202), (145, 98), (215, 98), (320, 202)], dtype=np.int32)


def test_ipm_lane_acquires_then_tracks_without_fixed_history_average() -> None:
    detector = _detector()
    first = detector.detect(_lane_frame(), timestamp=0.0)
    assert first.left_lane is not None
    assert first.right_lane is not None
    assert detector.state == "acquire"
    assert not detector.ldw_ready

    second = detector.detect(_lane_frame(), timestamp=1 / 30)
    assert second.ego_lane_polygon is not None
    assert detector.state == "track"
    assert detector.ldw_ready


def test_ipm_lane_absence_clears_lane_and_disables_ldw() -> None:
    detector = _detector()
    detector.detect(_lane_frame(), timestamp=0.0)
    detector.detect(_lane_frame(), timestamp=1 / 30)

    missing = detector.detect(np.zeros((203, 360, 3), dtype=np.uint8), timestamp=2 / 30)
    assert missing.ego_lane_polygon is None
    assert detector.state == "lost"
    assert not detector.ldw_ready
    assert detector.analyze_ldw(missing, frame_width=360, timestamp=2 / 30) is None


def test_ipm_lane_result_expires_before_stale_ldw_can_be_used() -> None:
    detector = _detector()
    detector.detect(_lane_frame(), timestamp=0.0)
    lanes = detector.detect(_lane_frame(), timestamp=1 / 30)
    assert detector.is_result_fresh(0.10)
    assert not detector.is_result_fresh(0.20)
    assert detector.analyze_ldw(lanes, frame_width=360, timestamp=0.20) is None


def test_ipm_detects_faded_lane_markings() -> None:
    frame = np.full((203, 360, 3), 55, dtype=np.uint8)
    cv2.line(frame, (40, 202), (145, 98), (94, 94, 94), 3)
    cv2.line(frame, (320, 202), (215, 98), (94, 94, 94), 3)
    detector = _detector()

    lanes = detector.detect(frame, timestamp=0.0)

    assert lanes.left_lane is not None
    assert lanes.right_lane is not None


def test_ipm_rejects_lane_that_jumps_far_from_recent_center() -> None:
    detector = _detector()
    detector.detect(_lane_frame(), timestamp=0.0)
    detected = detector.detect(_lane_frame(), timestamp=1 / 30)
    assert detected.ego_lane_polygon is not None
    false_left = np.array([(250, 100), (250, 202)], dtype=np.int32)
    false_right = np.array([(350, 100), (350, 202)], dtype=np.int32)
    false_lane = LaneInfo(
        false_left,
        false_right,
        np.array([false_left[1], false_left[0], false_right[0], false_right[1]], dtype=np.int32),
        None,
    )

    assert not detector._is_plausible_ipm_lane(false_lane, frame_width=360)


def test_ipm_uses_reference_trapezoid_to_select_ego_lane() -> None:
    detector = _detector()
    lanes = detector.detect(_lane_frame(), timestamp=0.0, reference_polygon=_reference_polygon())

    assert lanes.ego_lane_polygon is not None
    assert detector.ipm.last_reference_score > 0.8


def test_reference_trapezoid_rejects_outside_lane_candidate() -> None:
    detector = _detector()
    false_left = np.array([(245, 100), (245, 202)], dtype=np.int32)
    false_right = np.array([(340, 100), (340, 202)], dtype=np.int32)
    false_lane = LaneInfo(
        false_left,
        false_right,
        np.array([false_left[1], false_left[0], false_right[0], false_right[1]], dtype=np.int32),
        None,
    )

    assert not detector._is_plausible_ipm_lane(false_lane, 360, _reference_polygon())


def test_curve_projection_retains_multiple_points():
    from types import SimpleNamespace
    import numpy as np
    from src.lane.ipm import IPMLaneDetector
    detector = IPMLaneDetector()
    detector.curve_enabled = True
    maps = SimpleNamespace(output_shape=(120, 160), inverse=np.eye(3, dtype=np.float32))
    info = detector._to_image_lane(np.array([.001, -.1, 40.]), np.array([.001, -.1, 110.]), maps, 160, 120)
    assert info is not None
    assert len(info.left_lane) == 24 and len(info.ego_lane_polygon) == 48
    assert np.array_equal(info.ego_lane_polygon[0], info.left_lane[-1])
    assert np.array_equal(info.ego_lane_polygon[-1], info.right_lane[-1])
