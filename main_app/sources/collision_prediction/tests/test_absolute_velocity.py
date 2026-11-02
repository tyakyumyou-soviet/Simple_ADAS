"""絶対速度推定のテスト。"""
from collections import deque

from src.motion.absolute_velocity import AbsoluteVelocityEstimator
from src.motion.speed_source import ObdSpeedSource
from src.types import TrackedObject


def _make_track(track_id: int, bbox: tuple, history: list) -> TrackedObject:
    return TrackedObject(track_id, bbox, "car", 0.9, (0.0, 0.0),
                          deque(history, maxlen=30), 10, None)


def test_absolute_velocity_with_obd_speed() -> None:
    """OBD2 から自車速度を入れた時、相手車絶対速度が算出される。"""
    obd = ObdSpeedSource()
    obd.feed(50.0)   # 自車 50 km/h = 13.9 m/s
    est = AbsoluteVelocityEstimator(obd)
    # 同じ位置の bbox を 4 フレーム → 相手車は自車と同速で前進中と見なされるはず
    history = [(150, 280), (150, 280), (150, 280), (150, 280)]
    t = _make_track(1, (130, 250, 170, 310), history)
    for _ in range(4):
        absv = est.estimate(t, fps=30.0, frame_height=480, frame_width=320, ego_state=None)
    # longitudinal は自車速度近辺（相手も同じ向きに走ってる前提）
    assert absv.confidence > 0.5
    # 距離が動いてないので相対速度ゼロ → 絶対速度 ≒ 自車速度
    assert 10.0 < absv.longitudinal < 17.0


def test_absolute_velocity_static_when_no_motion() -> None:
    """OBD2=0, 物体動かず → 絶対速度ほぼゼロ。"""
    obd = ObdSpeedSource()
    obd.feed(0.0)
    est = AbsoluteVelocityEstimator(obd)
    history = [(150, 280)] * 5
    t = _make_track(2, (130, 250, 170, 310), history)
    for _ in range(5):
        absv = est.estimate(t, fps=30.0, frame_height=480, frame_width=320, ego_state=None)
    assert abs(absv.longitudinal) < 0.5
    assert abs(absv.lateral) < 0.5
