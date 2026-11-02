from collections import deque

import cv2
import numpy as np

from src.tracking.bbox_flow import BBoxFlowInterpolator
from src.types import TrackedObject


def test_bbox_flow_updates_position_scale_and_history() -> None:
    rng = np.random.default_rng(7)
    previous = np.zeros((160, 200, 3), dtype=np.uint8)
    texture = rng.integers(40, 240, size=(60, 60, 3), dtype=np.uint8)
    previous[50:110, 60:120] = texture
    matrix = cv2.getRotationMatrix2D((90, 80), 0, 1.04)
    matrix[:, 2] += (5, 3)
    current = cv2.warpAffine(previous, matrix, (200, 160))

    history = deque([(90.0, 80.0)], maxlen=30)
    track = TrackedObject(1, (60.0, 50.0, 120.0, 110.0), "car", 0.9, (0.0, 0.0), history, 4, None)
    flow = BBoxFlowInterpolator()
    flow.remember(previous)

    updated = flow.interpolate([track], current)[0]

    old_width = track.bbox[2] - track.bbox[0]
    new_width = updated.bbox[2] - updated.bbox[0]
    assert updated.bbox[0] > track.bbox[0]
    assert updated.bbox[1] > track.bbox[1]
    assert new_width >= old_width
    assert len(updated.history) == 2
    assert updated.age == 5
    assert updated.velocity[0] > 0
