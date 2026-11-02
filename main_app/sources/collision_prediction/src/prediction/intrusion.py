"""侵入/飛び出し判定。

`is_cut_in_vehicle`: 自車レーンに「外から侵入してくる」車。直進対向車は除外。
`is_pedestrian_rush`: 飛び出し歩行者（自車側に急に動いてくる）。
`classify_vehicle_heading`: 車両の進行方向ラベル（approaching / leaving / lateral / unknown）。
"""
from __future__ import annotations

from collections import deque

import numpy as np

from src.prediction.trajectory import trajectory_intersects_polygon
from src.types import TrackedObject
from src.utils.geometry import point_in_polygon


def is_cut_in_vehicle(track: TrackedObject, ego_lane_polygon: np.ndarray | None) -> bool:
    """対向車/側方車が自車レーンに侵入する軌跡か。"""
    if track.cls not in {"car", "truck", "bus", "motorcycle"}:
        return False
    vx, vy = track.velocity
    # 直進ぽい（横方向速度がほぼ無い）対向車は侵入と判定しない
    if abs(vx) < 2.5:
        return False
    center = _center(track.bbox)
    if point_in_polygon(center, ego_lane_polygon):
        return False
    # 軌跡延長が ego lane に交差し、かつ離反軌跡でないこと
    if not trajectory_intersects_polygon(track.history, ego_lane_polygon):
        return False
    # 自車レーン中心への接近方向か（vx の符号で判定）
    if ego_lane_polygon is None:
        return False
    lane_cx = float(np.mean(ego_lane_polygon[:, 0]))
    if center[0] < lane_cx and vx <= 0:
        return False
    if center[0] > lane_cx and vx >= 0:
        return False
    return True


def is_pedestrian_rush(track: TrackedObject, ego_lane_polygon: np.ndarray | None,
                      frame_width: int, relaxed: bool = True) -> bool:
    """飛び出し歩行者判定。

    relaxed=True で 3 条件のいずれか満たせば発火（敏感）：
      - age が小さい（出現直後）+ 自車レーン方向への動き
      - 急加速（直近2フレームで速度が急増）
      - 自車レーン軌跡交差
    """
    if track.cls not in {"person", "bicycle"}:
        return False
    vx, vy = track.velocity
    speed = float(np.hypot(vx, vy))
    center = _center(track.bbox)
    if ego_lane_polygon is None:
        lane_cx = frame_width / 2
    else:
        lane_cx = float(np.mean(ego_lane_polygon[:, 0]))
    moving_to_lane = (center[0] < lane_cx and vx > 0) or (center[0] > lane_cx and vx < 0)

    # 自転車は速く動くので人より敏感に判定
    is_bicycle = track.cls == "bicycle"
    speed_th_appear = 2.5 if is_bicycle else 3.0
    speed_th_traj = 3.5 if is_bicycle else 4.5
    speed_th_fast = 4.5 if is_bicycle else 5.5
    age_limit = 16 if is_bicycle else 12

    # 1) 出現直後 + 自車レーン方向（条件ゆるめ）
    if track.age <= age_limit and moving_to_lane and speed > speed_th_appear:
        return True
    # 2) 急加速（直近2フレームで急変）
    if _has_sudden_acceleration(track.history) and moving_to_lane:
        return True
    # 3) 軌跡が自車レーンを交差
    if speed > speed_th_traj and trajectory_intersects_polygon(track.history, ego_lane_polygon):
        return True
    # 4) 自車レーン中心方向への速い動き（自転車は閾値低め）
    if moving_to_lane and speed > speed_th_fast:
        return True
    if not relaxed:
        return False
    return False


def classify_vehicle_heading(track: TrackedObject, ego_lane_polygon: np.ndarray | None) -> str:
    """車両進行方向の質的ラベル。

    Returns:
        "approaching": 自車に近づいてくる（衝突リスク高）
        "leaving"   : 自車から離れる（衝突リスク低、警告対象外）
        "lateral"   : 横方向に流れる（cut_in 候補）
        "static"    : 動いていない
        "unknown"   : 履歴不足
    """
    if len(track.history) < 4:
        return "unknown"
    vx, vy = track.velocity
    speed = float(np.hypot(vx, vy))
    if speed < 0.8:
        return "static"
    # 画面下方向 (vy > 0) は自車に近づいている（路面が画面下に流れるのと同じ向き）
    if vy > 1.5:
        return "approaching"
    if vy < -1.5:
        return "leaving"
    if abs(vx) > 1.5:
        return "lateral"
    return "static"


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2


def _has_sudden_acceleration(history: deque) -> bool:
    if len(history) < 5:
        return False
    pts = np.array(list(history)[-5:], dtype=np.float32)
    speeds = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    if len(speeds) < 4:
        return False
    return float(speeds[-1]) > 1.8 * float(np.mean(speeds[:-1]) + 1e-6) and float(speeds[-1]) > 5.0
