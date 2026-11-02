from __future__ import annotations

from collections import defaultdict, deque

import numpy as np


class TTCEstimator:
    """距離ベース TTC + looming(BB拡大率) TTC のフォールバック融合。

    使い方:
        ttc.update(track_id, timestamp, distance_m, bbox_area)
    """

    def __init__(self, history_len: int = 12):
        self._dist_hist: dict[int, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=history_len))
        self._area_hist: dict[int, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=history_len))

    def update(self, track_id: int, timestamp: float,
               distance_m: float | None, bbox_area: float | None = None) -> float | None:
        ttc_distance = self._distance_ttc(track_id, timestamp, distance_m)
        ttc_looming = self._looming_ttc(track_id, timestamp, bbox_area)
        # 両方あれば小さい方を採用（より緊急のものを優先）
        # 片方だけならそれを採用
        candidates = [v for v in (ttc_distance, ttc_looming) if v is not None]
        if not candidates:
            return None
        return min(candidates)

    def _distance_ttc(self, track_id: int, timestamp: float, distance_m: float | None) -> float | None:
        if distance_m is None:
            return None
        hist = self._dist_hist[track_id]
        hist.append((timestamp, distance_m))
        if len(hist) < 3:
            return None
        data = np.array(hist, dtype=np.float32)
        times = data[:, 0] - data[0, 0]
        distances = data[:, 1]
        if float(times[-1]) <= 0:
            return None
        slope = float(np.polyfit(times, distances, 1)[0])
        closing_speed = -slope
        if closing_speed <= 0.1:
            return None
        return float(distances[-1] / closing_speed)

    def _looming_ttc(self, track_id: int, timestamp: float, bbox_area: float | None) -> float | None:
        """BB 面積の拡大率から TTC を推定する。距離が無くても TTC を出せる。

        TTC ≈ 2 * A / (dA/dt)  (相似拡大のとき、面積は距離の二乗に反比例)
        """
        if bbox_area is None or bbox_area <= 0:
            return None
        hist = self._area_hist[track_id]
        hist.append((timestamp, float(bbox_area)))
        if len(hist) < 3:
            return None
        data = np.array(hist, dtype=np.float32)
        times = data[:, 0] - data[0, 0]
        areas = data[:, 1]
        if float(times[-1]) <= 0:
            return None
        slope = float(np.polyfit(times, areas, 1)[0])
        if slope <= 0:
            return None  # 面積が縮小 = 物体が遠ざかっている
        return float(2.0 * areas[-1] / slope)


def bbox_area(bbox: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, (x2 - x1) * (y2 - y1))
