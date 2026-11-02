"""白線なし道のフォールバック（路面マスクベース）のテスト。"""
import numpy as np

from src.lane.lane_detector import LaneDetector, _road_mask_to_lane


def _make_road_mask(height: int = 360, width: int = 640, road_w_ratio: float = 0.6) -> np.ndarray:
    """画像下半分にだけ路面 (=1)、左右は other (=0) のマスク。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    half = height // 2
    center = width // 2
    half_w = int(width * road_w_ratio / 2)
    mask[half:, center - half_w:center + half_w] = 1
    return mask


def test_road_mask_to_lane_works_on_uniform_mask() -> None:
    """路面が中央に広がる典型ケースで仮レーンが構築される。"""
    mask = _make_road_mask()
    info = _road_mask_to_lane(mask, width=640, height=360)
    assert info is not None
    assert info.left_lane is not None
    assert info.right_lane is not None
    # 自車レーンは画像中央寄りに配置
    cx_bot = (info.left_lane[1][0] + info.right_lane[1][0]) / 2
    assert 280 < cx_bot < 360


def test_road_mask_to_lane_none_for_empty_mask() -> None:
    """路面が無いマスクなら None。"""
    mask = np.zeros((360, 640), dtype=np.uint8)
    assert _road_mask_to_lane(mask, 640, 360) is None


def test_lane_detector_falls_back_when_classical_fails_and_mask_available() -> None:
    """古典手法で白線が見つからず路面マスクのみある場合、フォールバックが動く。"""
    detector = LaneDetector(min_confidence=0.3)
    # 一様な灰色画像 → 白線なし
    frame = np.full((360, 640, 3), 80, dtype=np.uint8)
    mask = _make_road_mask()
    info = detector.detect(frame, road_mask=mask)
    # フォールバックでレーン情報が得られる
    assert info.left_lane is not None and info.right_lane is not None
    assert detector.last_confidence > 0.0


def test_lane_detector_no_fallback_when_no_mask() -> None:
    """白線なし + 路面マスクなし → 何も返らない（既存挙動を維持）。"""
    detector = LaneDetector(min_confidence=0.3)
    frame = np.full((360, 640, 3), 80, dtype=np.uint8)
    info = detector.detect(frame)
    assert info.left_lane is None
    assert info.right_lane is None
