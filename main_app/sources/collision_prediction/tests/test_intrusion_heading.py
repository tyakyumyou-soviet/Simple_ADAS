"""車両進行方向分類のテスト。"""
from collections import deque

import numpy as np

from src.prediction.intrusion import classify_vehicle_heading, is_pedestrian_rush
from src.types import TrackedObject


def _track(track_id: int, cls: str, bbox: tuple, velocity: tuple,
           history: list, age: int = 10) -> TrackedObject:
    return TrackedObject(track_id, bbox, cls, 0.9, velocity, deque(history, maxlen=30),
                          age, None)


def test_classify_approaching_vehicle() -> None:
    """画面下方向に流れる車両は接近中と分類される。"""
    history = [(160, 100), (160, 110), (160, 120), (160, 132), (160, 145)]
    t = _track(1, "car", (140, 140, 180, 200), velocity=(0, 4), history=history)
    assert classify_vehicle_heading(t, None) == "approaching"


def test_classify_leaving_vehicle() -> None:
    """画面上方向に動く車両は離反と分類される（衝突対象外）。"""
    history = [(160, 200), (160, 190), (160, 180), (160, 168), (160, 155)]
    # 横長 BB (遠方車両の見え方)
    t = _track(2, "car", (140, 160, 200, 180), velocity=(0, -4), history=history)
    assert classify_vehicle_heading(t, None) == "leaving"


def test_classify_lateral_vehicle() -> None:
    """横方向に流れる車両は lateral と分類される。"""
    history = [(100, 160), (110, 160), (120, 160), (132, 160), (145, 160)]
    # 横長 BB
    t = _track(3, "car", (130, 150, 200, 175), velocity=(4, 0), history=history)
    assert classify_vehicle_heading(t, None) == "lateral"


def test_pedestrian_rush_age_relaxed() -> None:
    """age が小さい歩行者で自車レーン方向への動きがあれば飛び出し判定 True。"""
    history = [(50, 200), (60, 200), (75, 200), (95, 200), (120, 200)]
    track = _track(4, "person", (110, 180, 130, 220), velocity=(6, 0),
                   history=history, age=4)
    polygon = np.array([(120, 240), (140, 150), (180, 150), (200, 240)], dtype=np.int32)
    assert is_pedestrian_rush(track, polygon, frame_width=320) is True
