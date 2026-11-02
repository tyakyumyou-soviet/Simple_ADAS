from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class Detection:
    bbox: tuple[float, float, float, float]
    cls: str
    conf: float


@dataclass
class TrackedObject:
    track_id: int
    bbox: tuple[float, float, float, float]
    cls: str
    conf: float
    velocity: tuple[float, float]
    history: deque[tuple[float, float]]
    age: int
    distance_m: float | None
    # 外部検出器の安定追跡で使う状態。既存の生成コードとの互換性を保つため既定値を持つ。
    confirmed: bool = True
    motion_valid: bool = True
    match_quality: float = 1.0


@dataclass
class LaneInfo:
    left_lane: np.ndarray | None
    right_lane: np.ndarray | None
    ego_lane_polygon: np.ndarray | None
    vanishing_point: tuple[int, int] | None


@dataclass
class EgoMotionState:
    """自車の運動状態。OBD2 が無い段階では視覚推定値、後で OBD2 と差し替え可能。"""
    is_moving: bool
    speed_level: str          # "stop" | "slow" | "moderate" | "fast"
    forward_flow_px: float    # 路面の前進方向フロー大きさ (px/frame)
    lateral_flow_px: float    # 横方向（旋回成分）
    vanishing_point: tuple[int, int] | None
    speed_kmh: float | None   # 視覚推定では None。OBD2 接続時に値が入る
    confidence: float         # 0-1 推定の信頼度

    @staticmethod
    def stationary(confidence: float = 1.0) -> "EgoMotionState":
        return EgoMotionState(False, "stop", 0.0, 0.0, None, None, confidence)


@dataclass
class SceneContext:
    frame_idx: int
    timestamp: float
    image: np.ndarray
    enhanced: np.ndarray
    detections: list[Detection]
    tracks: list[TrackedObject]
    road_mask: np.ndarray | None
    lanes: LaneInfo
    depth_map: np.ndarray | None
    signs: list[Detection]
    signals: list[Detection]
    ego_motion: "EgoMotionState | None" = None


@dataclass
class Alert:
    kind: str
    level: int
    target_id: int | None
    message: str
    bbox: tuple[float, float, float, float] | None
    direction: str | None = None  # "左" | "中央" | "右"
