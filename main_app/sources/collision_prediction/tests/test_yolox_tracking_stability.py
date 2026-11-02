import numpy as np

from src.detection.external_detector import ExternalDetectorBase
from src.tracking.byte_tracker import YoloTracker
from src.types import Detection


class SequenceDetector(ExternalDetectorBase):
    def __init__(self, sequence: list[list[Detection]]) -> None:
        self.sequence = sequence
        self.index = 0

    def detect(self, frame: np.ndarray) -> list[Detection]:
        detections = self.sequence[min(self.index, len(self.sequence) - 1)]
        self.index += 1
        return detections


def car(x: float) -> Detection:
    return Detection((x, 100.0, x + 40.0, 150.0), "car", 0.9)


def test_external_velocity_uses_real_frame_gap_and_confirms_track() -> None:
    tracker = YoloTracker(weights="yolox_tiny.onnx", enabled=True, conf_per_class={"car": 0.2})
    tracker._external = SequenceDetector([[car(100.0)], [car(112.0)]])

    first = tracker.track(np.zeros((240, 320, 3), dtype=np.uint8), frame_idx=0)[0]
    second = tracker.track(np.zeros((240, 320, 3), dtype=np.uint8), frame_idx=6)[0]

    assert first.track_id == second.track_id
    assert not first.confirmed
    assert second.confirmed
    assert 0.1 < second.velocity[0] < 3.0
    assert second.motion_valid


def test_large_unexpected_jump_starts_new_track() -> None:
    tracker = YoloTracker(weights="yolox_tiny.onnx", enabled=True, conf_per_class={"car": 0.2})
    tracker._external = SequenceDetector([[car(100.0)], [car(112.0)], [car(360.0)]])
    blank = np.zeros((240, 320, 3), dtype=np.uint8)

    first = tracker.track(blank, frame_idx=0)[0]
    tracker.track(blank, frame_idx=6)
    jumped = tracker.track(blank, frame_idx=12)[0]

    assert jumped.track_id != first.track_id
    assert not jumped.confirmed
