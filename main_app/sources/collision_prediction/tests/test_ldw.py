"""LDW (車線逸脱警告) のテスト。"""
import numpy as np

from src.lane.lane_detector import LaneDetector
from src.types import LaneInfo


def _make_lanes(left_bottom_x: int, right_bottom_x: int, height: int = 360) -> LaneInfo:
    """指定した左右底辺 x を持つ車線情報を作る。"""
    left = np.array([(left_bottom_x + 30, height // 2), (left_bottom_x, height - 1)], dtype=np.int32)
    right = np.array([(right_bottom_x - 30, height // 2), (right_bottom_x, height - 1)], dtype=np.int32)
    polygon = np.array(
        [(left_bottom_x, height - 1), (left_bottom_x + 30, height // 2),
         (right_bottom_x - 30, height // 2), (right_bottom_x, height - 1)],
        dtype=np.int32,
    )
    return LaneInfo(left, right, polygon, None)


def test_ldw_no_alert_when_centered() -> None:
    """車線中央にいれば警告なし。"""
    detector = LaneDetector(min_confidence=0.0)
    detector._last_confidence = 1.0   # 信頼度ゲートを通す
    lanes = _make_lanes(left_bottom_x=200, right_bottom_x=440)   # 中心 320、半幅 120
    # 自車中心(320) と車線中心(320) が一致 → ratio = 0
    for _ in range(5):
        alert = detector.analyze_ldw(lanes, frame_width=640)
    assert alert is None


def test_ldw_critical_when_outside_lane() -> None:
    """自車が車線外（ratio >= 0.9）→ critical 発火、方向情報を含む。"""
    detector = LaneDetector(min_confidence=0.0)
    detector._last_confidence = 1.0
    # 車線が右に大きく寄り、自車中心が車線中心から左に大きく外れる
    lanes = _make_lanes(left_bottom_x=420, right_bottom_x=540)   # 中心 480、半幅 60
    # 自車中心 320、レーン中心 480 → offset = -160、半幅 60 → ratio = 2.66 (>0.9)
    alert = None
    for _ in range(4):
        alert = detector.analyze_ldw(lanes, frame_width=640)
    assert alert is not None
    assert alert.level == 3
    assert alert.direction == "左"
    assert "左" in alert.message
    assert "車線逸脱" in alert.message


def test_ldw_warn_when_near_lane_edge() -> None:
    """車線寄り（0.6 <= ratio < 0.9）→ warn 発火。"""
    detector = LaneDetector(min_confidence=0.0)
    detector._last_confidence = 1.0
    # 車線中心が自車中心から 80px ずれ、半幅 120 → ratio ≒ 0.67
    lanes = _make_lanes(left_bottom_x=280, right_bottom_x=520)   # 中心 400、半幅 120
    alert = None
    for _ in range(4):
        alert = detector.analyze_ldw(lanes, frame_width=640)
    assert alert is not None
    assert alert.level == 2
    assert alert.direction == "左"
    assert "車線寄り" in alert.message


def test_ldw_right_direction_for_warning_and_critical() -> None:
    """右方向の車線寄り・逸脱も構造化された方向を返す。"""
    for left, right, expected_level in [(120, 360, 2), (100, 220, 3)]:
        detector = LaneDetector(min_confidence=0.0)
        detector._last_confidence = 1.0
        lanes = _make_lanes(left, right)
        for _ in range(3):
            alert = detector.analyze_ldw(lanes, frame_width=640)
        assert alert is not None
        assert alert.level == expected_level
        assert alert.direction == "右"


def test_ldw_requires_consecutive_frames() -> None:
    """1-2 フレーム瞬間的に偏っただけでは発火しない。"""
    detector = LaneDetector(min_confidence=0.0)
    detector._last_confidence = 1.0
    lanes_off = _make_lanes(left_bottom_x=420, right_bottom_x=540)
    # 1 フレーム目: 警告なし
    assert detector.analyze_ldw(lanes_off, frame_width=640) is None
    # 2 フレーム目: 警告なし
    assert detector.analyze_ldw(lanes_off, frame_width=640) is None
    # 3 フレーム目: 発火
    alert = detector.analyze_ldw(lanes_off, frame_width=640)
    assert alert is not None


def test_ldw_resets_when_back_to_center() -> None:
    """車線中心に戻ったら警告解除。"""
    detector = LaneDetector(min_confidence=0.0)
    detector._last_confidence = 1.0
    lanes_off = _make_lanes(left_bottom_x=420, right_bottom_x=540)
    lanes_center = _make_lanes(left_bottom_x=200, right_bottom_x=440)
    # 連続偏差で発火
    for _ in range(4):
        detector.analyze_ldw(lanes_off, frame_width=640)
    # 中央に戻ると警告なし
    alert = detector.analyze_ldw(lanes_center, frame_width=640)
    assert alert is None


def test_ldw_suppresses_implausible_multi_lane_offset() -> None:
    """誤検出レーンが400%逸脱のような不自然な警告を作らないこと。"""
    detector = LaneDetector(min_confidence=0.0, ldw_max_offset_ratio=3.0)
    detector._last_confidence = 1.0
    # 自車中心から3車線幅近く離れた候補は、逸脱ではなく誤検出として無視する。
    false_lane = _make_lanes(left_bottom_x=500, right_bottom_x=560)
    for _ in range(4):
        assert detector.analyze_ldw(false_lane, frame_width=640) is None
