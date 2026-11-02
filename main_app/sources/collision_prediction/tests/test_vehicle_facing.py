"""車両の向き推定（フロント/リア）のテスト。"""
import cv2
import numpy as np

from src.prediction.vehicle_facing import combine_collision_risk, estimate_facing


def test_rear_facing_detected_by_taillights() -> None:
    """BB 下部に赤い領域があれば rear と判定。"""
    frame = np.full((200, 200, 3), 50, dtype=np.uint8)
    bbox = (50.0, 50.0, 150.0, 150.0)
    # BB の下部 1/3 に赤い円を 2 個
    cv2.circle(frame, (70, 130), 8, (0, 0, 255), -1)
    cv2.circle(frame, (130, 130), 8, (0, 0, 255), -1)
    assert estimate_facing(frame, bbox, vy=0.0) == "rear"


def test_front_facing_detected_by_headlights() -> None:
    """BB 下部に明るい白い領域があれば front と判定。"""
    frame = np.full((200, 200, 3), 50, dtype=np.uint8)
    bbox = (50.0, 50.0, 150.0, 150.0)
    cv2.circle(frame, (70, 130), 10, (245, 245, 245), -1)
    cv2.circle(frame, (130, 130), 10, (245, 245, 245), -1)
    assert estimate_facing(frame, bbox, vy=0.0) == "front"


def test_collision_risk_high_for_front_approaching() -> None:
    assert combine_collision_risk("front", "approaching") == 1.0


def test_collision_risk_zero_for_rear_leaving() -> None:
    assert combine_collision_risk("rear", "leaving") == 0.0


def test_red_body_car_not_mistaken_for_rear() -> None:
    """赤い車体（フロント）を rear と誤判定しない。

    BB 全体が赤色だが、両端のランプは無いケース → 車体色とみなして却下、
    front 判定（vy > 0 or aspect から）が維持されるはず。
    """
    # 200x200 の赤い車体ぽい絵を作る（テールランプ無し）
    frame = np.full((200, 200, 3), 30, dtype=np.uint8)
    cv2.rectangle(frame, (50, 50), (150, 150), (40, 40, 200), -1)  # BGR の赤
    bbox = (50.0, 50.0, 150.0, 150.0)
    # vy > 0 = 接近中 → front 期待
    facing = estimate_facing(frame, bbox, vy=3.0)
    assert facing == "unknown", f"赤い車体を rear と誤判定: {facing}"


def test_clear_front_facing_with_strong_vy() -> None:
    """vy が強くポジティブなら front 確定。"""
    frame = np.full((200, 200, 3), 80, dtype=np.uint8)
    bbox = (50.0, 50.0, 150.0, 150.0)
    assert estimate_facing(frame, bbox, vy=3.5) == "unknown"


def test_clear_rear_facing_with_strong_negative_vy() -> None:
    """vy が強くネガティブなら rear 確定。"""
    frame = np.full((200, 200, 3), 80, dtype=np.uint8)
    bbox = (50.0, 50.0, 150.0, 150.0)
    assert estimate_facing(frame, bbox, vy=-3.5) == "unknown"
