"""自転車検出・警告のテスト。"""
from collections import deque

import numpy as np

from src.prediction.intrusion import is_pedestrian_rush
from src.prediction.risk_analyzer import RiskAnalyzer
from src.types import LaneInfo, SceneContext, TrackedObject


def _make_track(cls: str, bbox: tuple, velocity: tuple, history: list,
                 age: int = 10) -> TrackedObject:
    return TrackedObject(99, bbox, cls, 0.7, velocity,
                          deque(history, maxlen=30), age, None)


def _make_ctx(tracks: list[TrackedObject], timestamp: float = 0.0) -> SceneContext:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    polygon = np.array([(95, 239), (145, 110), (175, 110), (225, 239)], dtype=np.int32)
    return SceneContext(
        frame_idx=int(timestamp * 30), timestamp=timestamp, image=image, enhanced=image,
        detections=[], tracks=tracks, road_mask=None,
        lanes=LaneInfo(None, None, polygon, None),
        depth_map=None, signs=[], signals=[],
    )


def test_bicycle_rush_threshold_lower_than_pedestrian() -> None:
    """自転車は人より低い speed 閾値で飛び出し判定。"""
    # speed = 3.0 (人だと閾値以下、自転車だと閾値以上)
    history = [(50, 200), (60, 200), (70, 200), (80, 200), (90, 200)]
    polygon = np.array([(120, 240), (140, 150), (180, 150), (200, 240)], dtype=np.int32)

    bicycle = _make_track("bicycle", (90, 180, 110, 220), velocity=(3.0, 0), history=history, age=5)
    person = _make_track("person", (90, 180, 110, 220), velocity=(3.0, 0), history=history, age=5)

    assert is_pedestrian_rush(bicycle, polygon, frame_width=320) is True
    # 同条件の人では発火しない（speed_th_appear=3.0 で >3.0 なので giderlich）
    # 人の場合 speed > 3.0 の条件なので 3.0 はギリ通らない
    assert is_pedestrian_rush(person, polygon, frame_width=320) is False


def test_bicycle_collision_message_uses_bicycle_label() -> None:
    """自転車が連続滞在で警告される時、メッセージは「自転車」を含む。"""
    analyzer = RiskAnalyzer()
    bicycle = _make_track("bicycle", (145, 145, 175, 220),
                            velocity=(0.0, 0.0), history=[(160, 180)] * 5)
    # 0.25秒以上レーン内に滞在
    alerts = []
    for i in range(10):
        alerts = analyzer.analyze(_make_ctx([bicycle], timestamp=i / 30))
    bicycle_alerts = [a for a in alerts if "自転車" in a.message]
    assert len(bicycle_alerts) >= 1
