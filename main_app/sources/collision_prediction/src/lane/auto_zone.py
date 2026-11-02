"""台形ゾーンを「奥行きだけ自動、他は手動」で構築する。

理由: 左右の振れ幅・カーブ寄せは将来 OBD2 からのステアリング情報で制御予定。
それまでは手動スライダー値を尊重し、見やすさだけ自動化する（奥行き = 上頂点 y）。

奥行きは消失点があれば消失点の少し下に、なければ画像の 45% に置く。
"""
from __future__ import annotations

from collections import deque

import numpy as np

from src.types import LaneInfo


class AutoZoneController:
    """台形ゾーンの上頂点 y（奥行き）のみ自動算出。

    入力:
        height, width: 画像サイズ
        lanes: 検出されていれば消失点取得に使う
        vanishing_point: 消失点 (ego_motion or lane)
        manual_offset: 手動スライダー由来の値（dict）
            - center_x_ratio: 0.0-1.0 (デフォルト 0.5)
            - zone_bottom_width_ratio: 0.0-1.0 (デフォルト 0.40)
            - zone_top_width_ratio: 0.0-1.0 (デフォルト 0.10)
            - zone_top_offset_ratio: -0.25-0.25 (デフォルト 0.0、将来 OBD2 で動かす)
            - zone_top_y_offset: -0.2-0.2 (デフォルト 0.0、自動値への微調整)
    出力:
        polygon: np.ndarray shape (4, 2) int32
        meta: 描画用各種比率
    """

    def __init__(self, smooth_window: int = 10):
        self._top_y_hist: deque[float] = deque(maxlen=smooth_window)

    def compute(
        self,
        height: int,
        width: int,
        lanes: LaneInfo | None,
        vanishing_point: tuple[int, int] | None,
        manual_offset: dict | None = None,
    ) -> tuple[np.ndarray, dict]:
        m = manual_offset or {}
        center_x_ratio = float(np.clip(m.get("center_x_ratio", 0.5), 0.2, 0.8))
        bottom_w_ratio = float(np.clip(m.get("zone_bottom_width_ratio", 0.40), 0.1, 0.8))
        top_w_ratio = float(np.clip(m.get("zone_top_width_ratio", 0.10), 0.02, 0.5))
        top_offset_ratio = float(np.clip(m.get("zone_top_offset_ratio", 0.0), -0.25, 0.25))
        top_y_user_offset = float(np.clip(m.get("zone_top_y_offset", 0.0), -0.2, 0.2))
        auto_depth = bool(m.get("auto_depth", True))
        manual_top_y_ratio = float(np.clip(m.get("zone_top_y_ratio", 0.45), 0.20, 0.85))

        if auto_depth:
            # 上頂点 y を自動算出（消失点ベース）+ 履歴平滑化
            auto_top_y = self._auto_top_y(height, vanishing_point, lanes)
            self._top_y_hist.append(float(auto_top_y))
            smoothed_top_y = float(np.median(self._top_y_hist))
            top_y = int(np.clip(smoothed_top_y + height * top_y_user_offset, height * 0.20, height * 0.85))
        else:
            # 固定モード: スライダー値そのまま
            auto_top_y = int(height * manual_top_y_ratio)
            top_y = auto_top_y
            self._top_y_hist.clear()

        # 台形の他の点は手動スライダー値から算出
        center_x = int(width * center_x_ratio)
        bottom_half = int(width * bottom_w_ratio / 2)
        top_half = int(width * top_w_ratio / 2)
        top_cx = center_x + int(width * top_offset_ratio)

        polygon = np.array(
            [
                (center_x - bottom_half, height - 1),
                (top_cx - top_half, top_y),
                (top_cx + top_half, top_y),
                (center_x + bottom_half, height - 1),
            ],
            dtype=np.int32,
        )
        meta = {
            "center_x_ratio": center_x_ratio,
            "zone_top_y_ratio": top_y / max(height, 1),
            "zone_bottom_width_ratio": bottom_w_ratio,
            "zone_top_width_ratio": top_w_ratio,
            "zone_top_offset_ratio": top_offset_ratio,
            "auto_top_y": auto_top_y,
        }
        return polygon, meta

    def _auto_top_y(
        self,
        height: int,
        vp: tuple[int, int] | None,
        lanes: LaneInfo | None,
    ) -> int:
        """奥行きの自動推定。

        優先順:
          1. 消失点 y + 25px（消失点が信頼できる時）
          2. 検出された自車レーンの最遠点（左右レーン上頂点の y 平均）
          3. デフォルト: 画像の 45%
        """
        if vp is not None:
            return int(np.clip(vp[1] + 25, height * 0.25, height * 0.80))
        if lanes is not None and lanes.left_lane is not None and lanes.right_lane is not None:
            top_y_lane = (int(lanes.left_lane[0][1]) + int(lanes.right_lane[0][1])) / 2
            return int(np.clip(top_y_lane, height * 0.25, height * 0.80))
        return int(height * 0.45)
