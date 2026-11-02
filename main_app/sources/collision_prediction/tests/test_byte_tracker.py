from pathlib import Path
from types import SimpleNamespace

import numpy as np

from src.tracking.byte_tracker import YoloTracker


class _FakeYoloModel:
    def __init__(self) -> None:
        self.kwargs = {}

    def track(self, frame, **kwargs):
        self.kwargs = kwargs
        return [SimpleNamespace(boxes=SimpleNamespace(id=None))]


def test_bytetrack_entry_threshold_uses_lowest_class_conf(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    model = _FakeYoloModel()
    tracker = YoloTracker(
        weights="models/yolo11n.pt",
        device="cpu",
        conf=0.20,
        conf_per_class={"person": 0.10, "car": 0.20},
    )
    tracker._model = model

    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    assert tracker._track_with_yolo(frame) == []

    assert model.kwargs["conf"] == 0.10
    tracker_yaml = Path(model.kwargs["tracker"])
    assert tracker_yaml.exists()
    text = tracker_yaml.read_text(encoding="utf-8")
    assert "track_high_thresh: 0.1000" in text
    assert "new_track_thresh: 0.1000" in text
