from collections import deque

import numpy as np

from src.prediction.risk_analyzer import RiskAnalyzer
from src.types import EgoMotionState, LaneInfo, SceneContext, TrackedObject


def make_track(
    track_id: int,
    cls: str,
    bbox: tuple[float, float, float, float],
    velocity: tuple[float, float] = (0.0, 0.0),
    age: int = 10,
    distance_m: float | None = 20.0,
    history: deque[tuple[float, float]] | None = None,
) -> TrackedObject:
    if history is None:
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        history = deque([(cx - velocity[0] * i, cy - velocity[1] * i) for i in range(4, -1, -1)], maxlen=30)
    return TrackedObject(track_id, bbox, cls, 0.9, velocity, history, age, distance_m)


def make_context(tracks: list[TrackedObject], road_mask: np.ndarray | None = None, timestamp: float = 0.0) -> SceneContext:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    polygon = np.array([(95, 239), (145, 110), (175, 110), (225, 239)], dtype=np.int32)
    return SceneContext(
        frame_idx=int(timestamp * 30),
        timestamp=timestamp,
        image=image,
        enhanced=image,
        detections=[],
        tracks=tracks,
        road_mask=road_mask,
        lanes=LaneInfo(None, None, polygon, None),
        depth_map=None,
        signs=[],
        signals=[],
    )


def test_sidewalk_person_is_excluded() -> None:
    mask = np.ones((240, 320), dtype=np.uint8)
    mask[:, :] = 1
    mask[180:240, 40:120] = 2
    track = make_track(1, "person", (60, 150, 90, 220), distance_m=5.0)

    alerts = RiskAnalyzer().analyze(make_context([track], mask))

    assert not alerts


def test_person_in_ego_lane_warns() -> None:
    """自車レーンに連続滞在した歩行者は警告対象。横切りだけでは警告しない。"""
    analyzer = RiskAnalyzer()
    track = make_track(1, "person", (145, 145, 175, 220), distance_m=5.0)
    # 滞在判定: 連続 5 フレーム以上で発火するので、複数回呼ぶ
    alerts: list = []
    for i in range(10):
        alerts = analyzer.analyze(make_context([track], timestamp=i / 30))

    assert any(alert.kind == "person_collision" for alert in alerts)


def test_person_lane_dwell_uses_elapsed_time_not_frame_count() -> None:
    analyzer = RiskAnalyzer()
    track = make_track(20, "person", (145, 145, 175, 220), distance_m=5.0)

    # 高頻度で処理しても、0.25秒未満では発火しない。
    for timestamp in (0.0, 0.02, 0.08, 0.16, 0.24):
        alerts = analyzer.analyze(make_context([track], timestamp=timestamp))
        assert not any(alert.kind == "person_collision" for alert in alerts)

    alerts = analyzer.analyze(make_context([track], timestamp=0.25))
    assert any(alert.kind == "person_collision" for alert in alerts)


def test_following_closing_uses_meters_per_second() -> None:
    analyzer = RiskAnalyzer(following_closing_mps=0.8)
    track = make_track(21, "car", (140, 145, 190, 220), distance_m=14.0)
    # 2m/sで接近: サンプル間隔が不均一でもm/s基準で判定する。
    for timestamp, distance in ((0.0, 14.0), (0.1, 13.8), (0.4, 13.2), (0.7, 12.6)):
        current = make_track(21, "car", track.bbox, distance_m=distance)
        analyzer.analyze(make_context([current], timestamp=timestamp))

    assert analyzer._is_getting_closer(21)


def test_person_just_crossing_does_not_warn() -> None:
    """自車レーンを 1-2 フレームだけ通過する歩行者は警告対象外。"""
    analyzer = RiskAnalyzer()
    # 通過する歩行者: 1 フレーム目はレーン内、その後外に出る
    inside = make_track(10, "person", (145, 145, 175, 220), distance_m=5.0)
    outside = make_track(10, "person", (30, 145, 60, 220), distance_m=5.0)

    a1 = analyzer.analyze(make_context([inside], timestamp=0.0))
    a2 = analyzer.analyze(make_context([outside], timestamp=1 / 30))
    a3 = analyzer.analyze(make_context([outside], timestamp=2 / 30))

    # 1-2フレームだけの滞在では警告しない
    for alerts in (a1, a2, a3):
        assert not any(alert.kind == "person_collision" for alert in alerts)


def test_side_person_entering_lane_warns_early() -> None:
    """端から自車レーン方向へ入る歩行者は、レーン内滞在前でも飛び出し警告にする。"""
    analyzer = RiskAnalyzer()
    track = make_track(11, "person", (40, 150, 70, 220), velocity=(4.0, 0.0), age=3)

    alerts = analyzer.analyze(make_context([track]))

    assert any(alert.kind == "person_rush" and alert.target_id == 11 for alert in alerts)


def test_far_edge_person_entering_lane_warns_early() -> None:
    """画面端から内向きに動く歩行者は、まだ台形から遠めでも早期警告にする。"""
    analyzer = RiskAnalyzer()
    track = make_track(13, "person", (0, 150, 24, 220), velocity=(1.1, 0.0), age=3)

    alerts = analyzer.analyze(make_context([track]))

    assert any(alert.kind == "person_rush" and alert.target_id == 13 for alert in alerts)


def test_side_person_leaving_lane_does_not_warn_early() -> None:
    analyzer = RiskAnalyzer()
    track = make_track(12, "person", (40, 150, 70, 220), velocity=(-4.0, 0.0), age=3)

    alerts = analyzer.analyze(make_context([track]))

    assert not any(alert.kind == "person_rush" for alert in alerts)


def test_cut_in_vehicle_warns_but_straight_oncoming_does_not() -> None:
    analyzer = RiskAnalyzer()
    cut_in_history = deque([(245, 130), (225, 150), (205, 170), (185, 190), (165, 210)], maxlen=30)
    cut_in = make_track(2, "car", (230, 150, 285, 210), velocity=(-8, 8), history=cut_in_history)
    straight = make_track(3, "car", (30, 130, 80, 200), velocity=(0, 8))

    alerts = analyzer.analyze(make_context([cut_in, straight]))

    assert any(alert.kind == "cut_in" and alert.target_id == 2 for alert in alerts)
    assert not any(alert.kind == "cut_in" and alert.target_id == 3 for alert in alerts)


def test_alert_direction_uses_ego_path_width_at_target_depth() -> None:
    analyzer = RiskAnalyzer()
    left = make_track(51, "car", (40, 150, 80, 220))
    center = make_track(52, "car", (140, 150, 180, 220))
    right = make_track(53, "car", (240, 150, 280, 220))
    ctx = make_context([left, center, right])

    assert analyzer._direction_for_track(left, ctx) == "左"
    assert analyzer._direction_for_track(center, ctx) == "中央"
    assert analyzer._direction_for_track(right, ctx) == "右"


def test_following_distance_warns(monkeypatch) -> None:
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    """前車が連続滞在していれば車間距離警告が出る。"""
    analyzer = RiskAnalyzer()
    track = make_track(4, "car", (140, 145, 190, 220), distance_m=6.5)
    alerts: list = []
    for i in range(10):
        track.bbox = (140-i, 145-i, 190+i, 220+i)
        alerts = analyzer.analyze(make_context([track], timestamp=i / 30))

    assert any(alert.kind == "following_distance" for alert in alerts)


def test_front_start_warns_after_stopped_history(monkeypatch) -> None:
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    """前車が長時間停止 → 急発進 で警告（履歴 8 フレーム以上必要）。"""
    analyzer = RiskAnalyzer()
    stopped = make_track(5, "car", (140, 145, 190, 220), velocity=(0, 0))
    # 8 フレーム以上停止
    for idx in range(8):
        ctx = make_context([stopped], timestamp=idx / 30)
        ctx.ego_motion = EgoMotionState.stationary()
        analyzer.analyze(ctx)
    # 急発進 (>3.0)
    moving = make_track(5, "car", (145, 140, 185, 200), velocity=(0, -4))

    ctx = make_context([moving], timestamp=9 / 30)
    ctx.ego_motion = EgoMotionState.stationary()
    alerts = analyzer.analyze(ctx)

    assert any(alert.kind == "front_start" for alert in alerts)


def test_unknown_self_motion_never_emits_front_start(monkeypatch):
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    analyzer = RiskAnalyzer()
    for idx in range(12):
        track = make_track(5, "car", (140, 145, 190, 220), velocity=(0, 0))
        analyzer.analyze(make_context([track], timestamp=idx / 30))
    moving = make_track(5, "car", (145, 140, 185, 200), velocity=(0, -4))
    alerts = analyzer.analyze(make_context([moving], timestamp=.5))
    assert not any(a.kind == "front_start" for a in alerts)


def test_depth_corroborates_closing_but_not_unknown_facing(monkeypatch):
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    analyzer = RiskAnalyzer()
    monkeypatch.setattr(analyzer, "_size_rate", lambda tid: .05)
    track = make_track(5, "car", (140, 145, 180, 220), distance_m=None)
    for i in range(12):
        alerts = analyzer.analyze(make_context([track], timestamp=i / 30), depth_trends={5: .1})
    assert any(a.kind == "following" for a in alerts)
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "unknown")
    alerts = analyzer.analyze(make_context([track], timestamp=.5), depth_trends={5: .1})
    assert not any(a.kind in {"following", "following_distance"} for a in alerts)


def test_depth_alone_does_not_establish_closing(monkeypatch):
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    analyzer = RiskAnalyzer()
    track = make_track(5, "car", (140, 145, 180, 220), distance_m=None)
    for i in range(12):
        alerts = analyzer.analyze(make_context([track], timestamp=i / 30), depth_trends={5: .5})
    assert not any(a.kind in {"following", "following_distance"} for a in alerts)


def test_depth_can_corroborate_front_start(monkeypatch):
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    for depth_trends, expected in (({5: -.1}, True), ({}, False), ({5: .1}, False)):
        analyzer = RiskAnalyzer()
        monkeypatch.setattr(analyzer, "_size_rate", lambda tid: -.05)
        for idx in range(12):
            track = make_track(5, "car", (140, 145, 180, 220), velocity=(0, 0))
            ctx = make_context([track], timestamp=idx / 30)
            ctx.ego_motion = EgoMotionState.stationary()
            analyzer.analyze(ctx, depth_trends=depth_trends)
        moving = make_track(5, "car", (140, 140, 180, 210), velocity=(0, -4))
        ctx = make_context([moving], timestamp=13 / 30)
        ctx.ego_motion = EgoMotionState.stationary()
        alerts = analyzer.analyze(ctx, depth_trends=depth_trends)
        assert any(a.kind == "front_start" for a in alerts) is expected


def test_unknown_vehicle_does_not_raise_following(monkeypatch):
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "unknown")
    analyzer = RiskAnalyzer()
    track = make_track(4, "car", (140, 145, 190, 220), distance_m=6.5)
    for i in range(10):
        alerts = analyzer.analyze(make_context([track], timestamp=i/30))
    assert not any(a.kind in {"following", "following_distance"} for a in alerts)


def test_static_rear_does_not_warn_following(monkeypatch):
    monkeypatch.setattr("src.prediction.risk_analyzer.estimate_facing", lambda *args: "rear")
    analyzer = RiskAnalyzer()
    track = make_track(4, "car", (140, 145, 190, 220), distance_m=6.5)
    for i in range(10):
        alerts = analyzer.analyze(make_context([track], timestamp=i/30))
    assert not any(a.kind in {"following", "following_distance", "front_start"} for a in alerts)
