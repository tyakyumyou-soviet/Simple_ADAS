from __future__ import annotations

import numpy as np


class IPMFallbackDepth:
    def __init__(self, cam_height_m: float = 1.2):
        self.cam_height_m = cam_height_m

    def estimate_distance(self, bbox: tuple[float, float, float, float], frame_shape: tuple[int, int, int]) -> float:
        height = frame_shape[0]
        x1, y1, x2, y2 = bbox
        box_h = max(y2 - y1, 1.0)
        bottom_ratio = np.clip((height - y2) / max(height, 1), 0.0, 1.0)
        perspective_distance = 3.0 + bottom_ratio * 55.0
        size_distance = 900.0 / box_h
        return float(np.clip((perspective_distance + size_distance) / 2.0, 1.0, 120.0))

    def dense_depth(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        y = np.linspace(60.0, 2.0, height, dtype=np.float32)[:, None]
        return np.repeat(y, width, axis=1)


def bbox_to_distance(bbox: tuple[float, float, float, float], frame_height: int,
                     cam_height_m: float = 1.2, cam_pitch_deg: float = 0.0) -> float:
    """BB 底辺 y から路面ホモグラフィで縦方向距離 (m) を概算。

    cam_pitch_deg は未使用（将来拡張用）。
    """
    _, _, _, y2 = bbox
    bottom_ratio = float(np.clip((frame_height - y2) / max(frame_height, 1), 0.0, 1.0))
    # cam_height_m を反映した簡易モデル
    return float(np.clip(3.0 + bottom_ratio * 55.0 * (cam_height_m / 1.2), 1.0, 120.0))
