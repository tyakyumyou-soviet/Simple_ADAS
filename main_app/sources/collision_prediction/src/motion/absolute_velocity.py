"""他車の絶対速度ベクトル（実世界 m/s）推定。

目的: 単なる画面相対速度ではなく、できるだけ「絶対的」な速度を推定する。
将来 OBD2 が繋がれば自車速度は正確に取れるので、その時さらに精度が上がる。

アプローチ:
  1. 物体 BB の底辺中心を路面とみなし、IPM (逆透視変換) で実世界座標 (x, z) に投影
  2. 過去フレームの BB 底辺中心も同様に投影 → 移動量を得る
  3. これを fps で割って物体の「画面に対する実世界速度」を得る
     - この時点では「自車基準の相対速度」（自車が前進している分が引かれていない）
  4. 自車前進速度 (m/s) を加算して「絶対速度」に変換
  5. 信頼度は IPM の前提（カメラ高さ・ピッチ 0°）と物体が路面上にいる仮定の妥当性で決まる
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np

from src.depth.ipm_fallback import bbox_to_distance
from src.motion.speed_source import SpeedSource
from src.types import EgoMotionState, TrackedObject


@dataclass
class AbsoluteVelocity:
    """物体の絶対速度（実世界、m/s）。

    longitudinal: 自車進行方向の成分（+: 自車から遠ざかる、-: 自車に向かう）
    lateral: 横方向の成分（+: 自車から見て右、-: 左）
    speed: 大きさ
    confidence: 0-1 推定の信頼度
    """
    longitudinal: float
    lateral: float
    speed: float
    confidence: float


class AbsoluteVelocityEstimator:
    """IPM + 自車速度を統合し、各 track の絶対速度を推定する。

    使い方:
        est = AbsoluteVelocityEstimator(speed_source)
        absv = est.estimate(track, fps, frame_height, frame_width, ego_state)
    """

    def __init__(self, speed_source: SpeedSource, cam_height_m: float = 1.2,
                 cam_pitch_deg: float = 0.0, history_len: int = 6):
        self.speed_source = speed_source
        self.cam_height_m = cam_height_m
        self.cam_pitch_deg = cam_pitch_deg
        # track_id ごとの距離履歴（縦方向 m）
        self._long_hist: dict[int, deque] = defaultdict(lambda: deque(maxlen=history_len))
        self._lat_hist: dict[int, deque] = defaultdict(lambda: deque(maxlen=history_len))

    def estimate(self, track: TrackedObject, fps: float, frame_height: int, frame_width: int,
                 ego_state: EgoMotionState | None) -> AbsoluteVelocity:
        # 物体の縦方向距離 (m) を IPM で取得
        longitudinal_m = bbox_to_distance(track.bbox, frame_height, self.cam_height_m, self.cam_pitch_deg)
        # 横方向の m 換算（路面上の距離 → 焦点距離仮定で線形）
        cx = (track.bbox[0] + track.bbox[2]) / 2
        lateral_m = self._pixel_to_lateral_meter(cx, frame_width, longitudinal_m)

        self._long_hist[track.track_id].append(longitudinal_m)
        self._lat_hist[track.track_id].append(lateral_m)
        long_hist = self._long_hist[track.track_id]
        lat_hist = self._lat_hist[track.track_id]
        if len(long_hist) < 3:
            return AbsoluteVelocity(0.0, 0.0, 0.0, 0.0)

        # フレーム差分から相手車の自車基準の縦/横速度 (m/s) を推定
        # 線形回帰で安定化
        ys = np.array(long_hist, dtype=np.float32)
        xs = np.array(lat_hist, dtype=np.float32)
        ts = np.arange(len(ys), dtype=np.float32) / max(fps, 1.0)
        long_speed_rel = -float(np.polyfit(ts, ys, 1)[0])   # 距離が縮む = 接近 → +
        lat_speed_rel = float(np.polyfit(ts, xs, 1)[0])

        # 自車速度を加算 → 物体の絶対速度
        ego_kmh = self.speed_source.get_speed_kmh()
        ego_mps = (ego_kmh / 3.6) if ego_kmh is not None else self._estimate_ego_mps(ego_state, fps, frame_height)

        # 物体は自車前方 → 物体の絶対進行（地球座標系で前方向）= 自車速度 - 相手の接近速度
        # つまり、相手車が自車と同じ方向に走るなら接近速度 0、相手が止まっていれば接近速度=自車速度
        longitudinal_abs = ego_mps - long_speed_rel
        lateral_abs = lat_speed_rel   # 横方向は自車前進の影響を受けにくい（無視できる前提）

        speed = float(np.hypot(longitudinal_abs, lateral_abs))
        # 信頼度: IPM が成り立つ前提（路面上）+ 距離履歴の十分性
        confidence = 0.5 + 0.5 * min(1.0, len(long_hist) / 5.0)
        if longitudinal_m > 60.0:
            confidence *= 0.5   # 遠方は精度低下

        return AbsoluteVelocity(longitudinal_abs, lateral_abs, speed, confidence)

    @staticmethod
    def _pixel_to_lateral_meter(cx: float, frame_width: int, longitudinal_m: float) -> float:
        """画素 x から実世界横位置 m への概算。

        単純な線形モデル: 中央からのずれを焦点距離仮定で投影。
        距離が遠いほど 1pixel が広い実世界距離に対応。
        """
        center = frame_width / 2
        # 経験式: 1m 距離あたり 1 画素 ≒ 0.002m * longitudinal_m （カメラ視野角の簡易近似）
        offset_px = cx - center
        return float(offset_px * 0.002 * max(longitudinal_m, 1.0))

    @staticmethod
    def _estimate_ego_mps(ego_state: EgoMotionState | None, fps: float, frame_height: int) -> float:
        """OBD2 が無い時の自車速度推定（視覚ベース、粗い）。

        EgoMotionState.forward_flow_px は「路面が画面下に流れる速さ」(px/frame)。
        画面下端付近の 1px ≒ 0.05m を仮定（カメラ高さ 1.2m, ピッチ 0°）すると：
            forward_mps ≒ forward_flow_px * 0.05 * fps
        """
        if ego_state is None or ego_state.forward_flow_px <= 0:
            return 0.0
        return float(ego_state.forward_flow_px * 0.05 * max(fps, 1.0))
