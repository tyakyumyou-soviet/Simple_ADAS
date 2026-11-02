from __future__ import annotations

from collections import deque
from dataclasses import replace

import cv2
import numpy as np

from src.types import TrackedObject


class BBoxFlowInterpolator:
    """検出スキップフレームで Lucas-Kanade を使い BB を追従する。

    各 BB 内に均等格子サンプル点を撒き、前フレームの gray と現フレームの gray で
    LK を計算。中央値の移動量と点群の広がりから中心・スケールを更新する。
    """

    LK_PARAMS = dict(winSize=(15, 15), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))

    def __init__(self, samples_per_bbox: int = 9):
        self.samples_per_bbox = samples_per_bbox
        self._prev_gray: np.ndarray | None = None

    def remember(self, frame: np.ndarray) -> None:
        self._prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def interpolate(self, tracks: list[TrackedObject], frame: np.ndarray) -> list[TrackedObject]:
        if not tracks or self._prev_gray is None:
            self.remember(frame)
            return tracks
        cur_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = cur_gray.shape
        # 全 BB の格子点を 1 つの配列にまとめて 1 回の LK で処理
        bbox_ranges: list[tuple[int, int]] = []
        all_pts: list[np.ndarray] = []
        for t in tracks:
            pts = self._sample_points(t.bbox, w, h)
            start = sum(p.shape[0] for p in all_pts)
            bbox_ranges.append((start, start + pts.shape[0]))
            all_pts.append(pts)
        if not all_pts:
            self._prev_gray = cur_gray
            return tracks
        pts_arr = np.concatenate(all_pts, axis=0).reshape(-1, 1, 2).astype(np.float32)
        nxt, status, _ = cv2.calcOpticalFlowPyrLK(self._prev_gray, cur_gray, pts_arr, None, **self.LK_PARAMS)
        if nxt is None:
            self._prev_gray = cur_gray
            return tracks
        delta = (nxt - pts_arr).reshape(-1, 2)
        ok = status.reshape(-1).astype(bool)
        out: list[TrackedObject] = []
        for t, (s, e) in zip(tracks, bbox_ranges):
            mask = ok[s:e]
            if mask.sum() < 2:
                out.append(t)
                continue
            old_pts = pts_arr.reshape(-1, 2)[s:e][mask]
            new_pts = nxt.reshape(-1, 2)[s:e][mask]
            dx = float(np.median(delta[s:e, 0][mask]))
            dy = float(np.median(delta[s:e, 1][mask]))
            scale = self._estimate_scale(old_pts, new_pts)
            x1, y1, x2, y2 = t.bbox
            cx = (x1 + x2) / 2 + dx
            cy = (y1 + y2) / 2 + dy
            half_w = max(1.0, (x2 - x1) * scale / 2)
            half_h = max(1.0, (y2 - y1) * scale / 2)
            new_bbox = (
                float(np.clip(cx - half_w, 0, w - 1)),
                float(np.clip(cy - half_h, 0, h - 1)),
                float(np.clip(cx + half_w, 0, w - 1)),
                float(np.clip(cy + half_h, 0, h - 1)),
            )
            history = deque(t.history, maxlen=t.history.maxlen or 30)
            history.append(((new_bbox[0] + new_bbox[2]) / 2, (new_bbox[1] + new_bbox[3]) / 2))
            out.append(replace(
                t,
                bbox=new_bbox,
                history=history,
                velocity=self._velocity(history),
                age=t.age + 1,
            ))
        self._prev_gray = cur_gray
        return out

    @staticmethod
    def _estimate_scale(old_pts: np.ndarray, new_pts: np.ndarray) -> float:
        if len(old_pts) < 4:
            return 1.0
        old_center = np.median(old_pts, axis=0)
        new_center = np.median(new_pts, axis=0)
        old_radius = np.linalg.norm(old_pts - old_center, axis=1)
        new_radius = np.linalg.norm(new_pts - new_center, axis=1)
        valid = old_radius > 1.0
        if valid.sum() < 3:
            return 1.0
        ratio = float(np.median(new_radius[valid] / old_radius[valid]))
        return float(np.clip(ratio, 0.95, 1.05))

    @staticmethod
    def _velocity(history: deque[tuple[float, float]]) -> tuple[float, float]:
        if len(history) < 2:
            return (0.0, 0.0)
        pts = np.asarray(list(history)[-5:], dtype=np.float32)
        t = np.arange(len(pts), dtype=np.float32)
        return (
            float(np.polyfit(t, pts[:, 0], 1)[0]),
            float(np.polyfit(t, pts[:, 1], 1)[0]),
        )

    def _sample_points(self, bbox: tuple[float, float, float, float], w: int, h: int) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        n = int(np.sqrt(self.samples_per_bbox))
        xs = np.linspace(x1 + (x2 - x1) * 0.15, x2 - (x2 - x1) * 0.15, n)
        ys = np.linspace(y1 + (y2 - y1) * 0.15, y2 - (y2 - y1) * 0.15, n)
        gx, gy = np.meshgrid(xs, ys)
        pts = np.stack([gx.ravel(), gy.ravel()], axis=1)
        pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)
        return pts.astype(np.float32)
