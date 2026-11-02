"""自車エゴモーション推定。

Lucas-Kanade スパースオプティカルフローで路面領域のキーポイントを追跡し、
自車の前進量・横ずれ・消失点を推定する。
路面マスクが無い場合は画像下半分を路面とみなす（フォールバック）。
"""
from __future__ import annotations

import cv2
import numpy as np

from src.types import EgoMotionState


class EgoMotionEstimator:
    """フレーム毎に呼び出して自車の運動状態を返す。

    使い方:
        ego = EgoMotionEstimator()
        state = ego.update(frame, road_mask=road_mask)
        # state.background_flow_at(x, y) で任意点の背景フローを取得
    """

    SPEED_LEVELS = (
        # (上限px/frame, ラベル)
        (0.6, "stop"),
        (3.0, "slow"),
        (8.0, "moderate"),
        (float("inf"), "fast"),
    )

    def __init__(self, max_corners: int = 200, quality: float = 0.02, min_distance: int = 12):
        self.max_corners = max_corners
        self.quality = quality
        self.min_distance = min_distance
        self._prev_gray: np.ndarray | None = None
        self._prev_pts: np.ndarray | None = None
        # 直近フロー（背景流速の推定に再利用）
        self._last_flow: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self._last_vp: tuple[int, int] | None = None

    def update(self, frame: np.ndarray, road_mask: np.ndarray | None = None,
               lane_vanishing_point: tuple[int, int] | None = None) -> EgoMotionState:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape

        # 路面マスクを作る（なければ画像下 55% をデフォルト ROI に）
        mask = self._build_road_mask(road_mask, height, width)

        # 初期化（最初のフレーム）
        if self._prev_gray is None or self._prev_pts is None or len(self._prev_pts) < 8:
            self._prev_gray = gray
            self._prev_pts = self._detect_corners(gray, mask)
            self._last_flow = []
            return EgoMotionState.stationary(confidence=0.0)

        # Lucas-Kanade で追跡
        next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
            self._prev_gray, gray, self._prev_pts, None,
            winSize=(21, 21), maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.03),
        )

        good_old, good_new = [], []
        if next_pts is not None and status is not None:
            for old, new, st in zip(self._prev_pts, next_pts, status.flatten()):
                if st == 1:
                    ox, oy = old.ravel()
                    nx, ny = new.ravel()
                    good_old.append((float(ox), float(oy)))
                    good_new.append((float(nx), float(ny)))

        # 次フレーム用にコーナーを再検出（量が減っていれば）
        if len(good_new) < self.max_corners // 3:
            self._prev_pts = self._detect_corners(gray, mask)
        else:
            self._prev_pts = np.array(good_new, dtype=np.float32).reshape(-1, 1, 2)
        self._prev_gray = gray

        # フロー無し
        if len(good_new) < 8:
            self._last_flow = []
            return EgoMotionState.stationary(confidence=0.0)

        # フローベクトル
        flow_vectors = [(o, n) for o, n in zip(good_old, good_new)]
        self._last_flow = flow_vectors

        dxs = np.array([n[0] - o[0] for o, n in flow_vectors])
        dys = np.array([n[1] - o[1] for o, n in flow_vectors])
        magnitudes = np.hypot(dxs, dys)

        # 外れ値除去（中央値 ± 2σ）
        med = float(np.median(magnitudes))
        mad = float(np.median(np.abs(magnitudes - med))) + 1e-6
        keep = np.abs(magnitudes - med) < 3.0 * mad
        if keep.sum() < 6:
            return EgoMotionState.stationary(confidence=0.0)

        dxs, dys, magnitudes = dxs[keep], dys[keep], magnitudes[keep]
        forward = float(np.median(np.abs(dys)))   # 路面は下に流れるので |dy|
        lateral = float(np.median(dxs))           # 横移動成分
        signed_forward = float(np.median(dys))    # 進行方向は dy>0 (画像下に流れる) で前進

        # 消失点推定 — フローを直線とみなし最小二乗で収束点
        vp = self._estimate_vanishing_point(flow_vectors, width, height, lane_vanishing_point)
        self._last_vp = vp

        # 速度レベル分類
        speed_level = next(label for limit, label in self.SPEED_LEVELS if forward < limit)
        is_moving = speed_level != "stop"

        return EgoMotionState(
            is_moving=is_moving,
            speed_level=speed_level,
            forward_flow_px=forward if signed_forward >= 0 else -forward,
            lateral_flow_px=lateral,
            vanishing_point=vp,
            speed_kmh=None,
            confidence=float(min(1.0, keep.sum() / 30.0)),
        )

    def background_flow_at(self, x: float, y: float) -> tuple[float, float]:
        """直近フレームの (x, y) 付近の背景フローを推定する。

        近傍フロー点の重み付き平均（IDW: 距離反比例）で値を返す。
        フロー点が無ければ (0, 0)。
        """
        if not self._last_flow:
            return (0.0, 0.0)
        # 近傍 8 点でフィット
        distances, vectors = [], []
        for (ox, oy), (nx, ny) in self._last_flow:
            d = (ox - x) ** 2 + (oy - y) ** 2
            distances.append(d + 1e-3)
            vectors.append((nx - ox, ny - oy))
        idx = np.argsort(distances)[:8]
        weights = np.array([1.0 / distances[i] for i in idx])
        weights /= weights.sum()
        vx = float(sum(weights[k] * vectors[idx[k]][0] for k in range(len(idx))))
        vy = float(sum(weights[k] * vectors[idx[k]][1] for k in range(len(idx))))
        return (vx, vy)

    def local_background_flow_at(self, x: float, y: float, max_distance: float = 120.0) -> tuple[float, float] | None:
        """物体近傍の実測フローだけを返す。遠い点で補間しない。"""
        if not self._last_flow:
            return None
        values: list[tuple[float, tuple[float, float]]] = []
        for (ox, oy), (nx, ny) in self._last_flow:
            distance = float(np.hypot(ox - x, oy - y))
            if distance <= max_distance:
                values.append((distance, (nx - ox, ny - oy)))
        if not values:
            return None
        values.sort(key=lambda item: item[0])
        values = values[:8]
        weights = np.asarray([1.0 / (distance + 1.0) for distance, _ in values], dtype=np.float32)
        weights /= weights.sum()
        return (
            float(sum(weight * vector[0] for weight, (_, vector) in zip(weights, values))),
            float(sum(weight * vector[1] for weight, (_, vector) in zip(weights, values))),
        )

    # ----- internal helpers -----

    def _detect_corners(self, gray: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
        pts = cv2.goodFeaturesToTrack(
            gray, maxCorners=self.max_corners, qualityLevel=self.quality,
            minDistance=self.min_distance, mask=mask, blockSize=7,
        )
        return pts

    @staticmethod
    def _build_road_mask(road_mask: np.ndarray | None, height: int, width: int) -> np.ndarray:
        if road_mask is not None and road_mask.shape == (height, width):
            # road_mask: 0=other, 1=road, 2=sidewalk → 路面のみキーポイント候補
            return (road_mask == 1).astype(np.uint8) * 255
        # フォールバック: 画像下 45-90% の縦帯
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[int(height * 0.45):int(height * 0.92), int(width * 0.05):int(width * 0.95)] = 255
        return mask

    @staticmethod
    def _estimate_vanishing_point(
        flow_vectors: list[tuple[tuple[float, float], tuple[float, float]]],
        width: int, height: int,
        lane_vp: tuple[int, int] | None,
    ) -> tuple[int, int] | None:
        """フロー直線の収束点を最小二乗で求める。車線消失点があれば加重平均で統合。"""
        rows_a, rows_b = [], []
        for (ox, oy), (nx, ny) in flow_vectors:
            dx, dy = nx - ox, ny - oy
            if dx * dx + dy * dy < 0.25:
                continue
            # 直線: 法線 (dy, -dx)・点 (ox, oy)  →  dy*x - dx*y = dy*ox - dx*oy
            rows_a.append([dy, -dx])
            rows_b.append(dy * ox - dx * oy)
        if len(rows_a) < 6:
            return lane_vp
        A = np.array(rows_a, dtype=np.float64)
        b = np.array(rows_b, dtype=np.float64)
        try:
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        except np.linalg.LinAlgError:
            return lane_vp
        vx, vy = int(sol[0]), int(sol[1])
        # 画像内に収めない / 上空に飛んだ消失点は不採用
        if not (0 <= vx < width and int(height * 0.1) <= vy <= int(height * 0.85)):
            return lane_vp
        if lane_vp is not None:
            # 70% フロー / 30% 車線 で統合
            vx = int(0.7 * vx + 0.3 * lane_vp[0])
            vy = int(0.7 * vy + 0.3 * lane_vp[1])
        return (vx, vy)
