from __future__ import annotations

import cv2
import numpy as np


Point = tuple[int, int]


def line_intersection(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> Point | None:
    x1, y1 = a1
    x2, y2 = a2
    x3, y3 = b1
    x4, y4 = b2
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-6:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return int(px), int(py)


def point_in_polygon(point: tuple[float, float], polygon: np.ndarray | None) -> bool:
    if polygon is None or len(polygon) < 3:
        return False
    return cv2.pointPolygonTest(polygon.astype(np.float32), point, False) >= 0


def fallback_ego_lane_polygon(
    width: int,
    height: int,
    center_x_ratio: float = 0.5,
    top_y_ratio: float = 0.45,
    bottom_width_ratio: float = 0.40,
    top_width_ratio: float = 0.10,
    top_offset_ratio: float = 0.0,
) -> np.ndarray:
    center = int(width * np.clip(center_x_ratio, 0.25, 0.75))
    top_center = center + int(width * np.clip(top_offset_ratio, -0.25, 0.25))
    bottom_half = int(width * np.clip(bottom_width_ratio, 0.10, 0.80) / 2)
    top_half = int(width * np.clip(top_width_ratio, 0.02, 0.50) / 2)
    top_y = int(height * np.clip(top_y_ratio, 0.15, 0.85))
    return np.array(
        [
            (center - bottom_half, height - 1),
            (top_center - top_half, top_y),
            (top_center + top_half, top_y),
            (center + bottom_half, height - 1),
        ],
        dtype=np.int32,
    )


def danger_zone_from_lane(width: int, height: int, lane_polygon: np.ndarray | None) -> np.ndarray:
    if lane_polygon is None:
        return fallback_ego_lane_polygon(width, height)
    polygon = lane_polygon.astype(np.int32)
    if polygon.shape[0] < 4:
        return fallback_ego_lane_polygon(width, height)
    return polygon
