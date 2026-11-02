"""統合危険度スコアのテスト。"""
from src.prediction.threat_score import threat_level, threat_score


def test_high_threat_when_front_approaching_close() -> None:
    """近距離・接近・フロント向き → 高スコア (critical)。"""
    s = threat_score(
        distance_m=6.0, ttc_s=1.5,
        heading="approaching", facing="front",
        relative_closing_mps=8.0,
        in_ego_lane=True, dwell_seconds=0.4,
    )
    assert s > 0.65
    assert threat_level(s) == 3


def test_low_threat_when_rear_leaving() -> None:
    """遠ざかる・リア向き → 低スコア (警告なし)。"""
    s = threat_score(
        distance_m=20.0, ttc_s=None,
        heading="leaving", facing="rear",
        relative_closing_mps=-5.0,
        in_ego_lane=False, dwell_seconds=0.0,
    )
    assert s < 0.30
    assert threat_level(s) == 0


def test_warn_for_moderate_approach() -> None:
    """中距離・少し接近 → warn 以上 (level >= 2)。"""
    s = threat_score(
        distance_m=15.0, ttc_s=3.0,
        heading="approaching", facing="unknown",
        relative_closing_mps=2.0,
        in_ego_lane=True, dwell_seconds=0.4,
    )
    assert s >= 0.45
    assert threat_level(s) >= 2


def test_lateral_lane_in_dwell_warn() -> None:
    """自車レーン内に長期間滞在 → warn 以上。"""
    s = threat_score(
        distance_m=10.0, ttc_s=None,
        heading="static", facing="rear",
        relative_closing_mps=0.0,
        in_ego_lane=True, dwell_seconds=0.5,
    )
    assert threat_level(s) >= 1
