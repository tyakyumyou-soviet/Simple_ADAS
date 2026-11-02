from __future__ import annotations

from collections import deque

import cv2
import numpy as np


def trajectory_intersects_polygon(history: deque[tuple[float, float]], polygon: np.ndarray | None, horizon_px: float = 240.0) -> bool:
    if polygon is None or len(history) < 3:
        return False
    pts = np.array(history, dtype=np.float32)
    t = np.arange(len(pts), dtype=np.float32)
    vx = float(np.polyfit(t, pts[:, 0], 1)[0])
    vy = float(np.polyfit(t, pts[:, 1], 1)[0])
    start = pts[-1]
    end = start + np.array([vx, vy], dtype=np.float32) * max(10.0, horizon_px / max(np.linalg.norm([vx, vy]), 1.0))
    for ratio in np.linspace(0, 1, 20):
        point = start * (1 - ratio) + end * ratio
        if cv2.pointPolygonTest(polygon.astype(np.float32), (float(point[0]), float(point[1])), False) >= 0:
            return True
    return False
