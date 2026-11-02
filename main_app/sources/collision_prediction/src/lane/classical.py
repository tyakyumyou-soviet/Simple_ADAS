"""古典手法による車線検出。点線対応と自車レーン選別を強化版。

特徴:
- Canny エッジ + HSV 白/黄マスク（点線結合のため縦方向モルフォロジー）
- ROI を画像下半分に限定
- 検出した全直線から「画面中心に最も近い左右1ペア」を選び、自車レーンを構成
  → 道路全体ではなく自車レーンだけを返す
- 検出失敗時はフォールバック台形ゾーンを返す
- 結果に confidence を持たせる
"""
from __future__ import annotations

import cv2
import numpy as np

from src.types import LaneInfo
from src.utils.geometry import fallback_ego_lane_polygon, line_intersection


class ClassicalLaneDetector:
    def __init__(
        self,
        center_x_ratio: float = 0.5,
        zone_top_y_ratio: float = 0.45,
        zone_bottom_width_ratio: float = 0.40,
        zone_top_width_ratio: float = 0.10,
        zone_top_offset_ratio: float = 0.0,
        hough_threshold: int = 20,
        min_line_length: int = 14,
        max_line_gap: int = 220,
        dashed_support: bool = True,
        # 自車レーン幅の制約（画面幅比）
        min_lane_width_ratio: float = 0.18,
        max_lane_width_ratio: float = 0.55,
    ):
        self.center_x_ratio = center_x_ratio
        self.zone_top_y_ratio = zone_top_y_ratio
        self.zone_bottom_width_ratio = zone_bottom_width_ratio
        self.zone_top_width_ratio = zone_top_width_ratio
        self.zone_top_offset_ratio = zone_top_offset_ratio
        self.hough_threshold = hough_threshold
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap
        self.dashed_support = dashed_support
        self.min_lane_width_ratio = min_lane_width_ratio
        self.max_lane_width_ratio = max_lane_width_ratio

    def detect(self, frame: np.ndarray) -> tuple[LaneInfo, float]:
        """車線情報と検出信頼度 (0-1) を返す。"""
        height, width = frame.shape[:2]
        roi_y = height // 2
        roi = frame[roi_y:, :]
        edges = self._lane_edges(roi)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            self.hough_threshold,
            minLineLength=self.min_line_length,
            maxLineGap=self.max_line_gap,
        )
        if lines is None:
            return LaneInfo(None, None, self._fallback_polygon(width, height), None), 0.0

        # 左右の候補線分群を集める
        left: list[tuple[int, int, int, int, float]] = []   # (x1,y1,x2,y2,length)
        right: list[tuple[int, int, int, int, float]] = []
        for raw in lines[:, 0, :]:
            x1, y1, x2, y2 = map(int, raw)
            if x2 == x1:
                continue
            slope = (y2 - y1) / (x2 - x1)
            if abs(slope) < 0.25:   # ほぼ水平な線は除外
                continue
            length = float(np.hypot(x2 - x1, y2 - y1))
            line_with_len = (x1, y1 + roi_y, x2, y2 + roi_y, length)
            (left if slope < 0 else right).append(line_with_len)

        y_bottom = height
        y_top = int(height * 0.62)
        center_x = width * self.center_x_ratio

        # 各群を傾き × x切片でクラスタリングし、レーン候補を作る
        left_candidates = self._cluster_lanes(left, y_bottom, y_top)
        right_candidates = self._cluster_lanes(right, y_bottom, y_top)

        # 画面中心に最も近い左右ペアを選ぶ
        left_lane, right_lane, confidence = self._select_ego_pair(
            left_candidates, right_candidates, center_x, width, y_bottom
        )

        vanishing = None
        polygon = self._fallback_polygon(width, height)
        if left_lane is not None and right_lane is not None:
            vanishing = line_intersection(
                tuple(left_lane[0]), tuple(left_lane[-1]),
                tuple(right_lane[0]), tuple(right_lane[-1]),
            )
            polygon = np.array(
                [left_lane[-1], left_lane[0], right_lane[0], right_lane[-1]],
                dtype=np.int32,
            )
        return LaneInfo(left_lane, right_lane, polygon, vanishing), confidence

    def _cluster_lanes(
        self,
        lines: list[tuple[int, int, int, int, float]],
        y_bottom: int,
        y_top: int,
    ) -> list[tuple[np.ndarray, float]]:
        """傾き＋x切片で線分をクラスタ化し、各クラスタを (lane_polyline, weight) で返す。"""
        if len(lines) < 1:
            return []
        # 各線分の (x_bottom_intercept, slope) を計算
        feats = []
        for x1, y1, x2, y2, length in lines:
            dx = x2 - x1
            dy = y2 - y1
            if abs(dx) < 1 or abs(dy) < 1:
                continue
            slope = dy / dx   # dy/dx
            # y=y_bottom-1 における x
            x_at_bottom = x1 + (y_bottom - 1 - y1) * dx / dy
            feats.append((x_at_bottom, slope, length, x1, y1, x2, y2))
        if not feats:
            return []

        # 単純な x_at_bottom ベースのクラスタリング（解像度に応じて追従）
        cluster_gap = max(36.0, abs(y_bottom - y_top) * 0.35)
        feats.sort(key=lambda t: t[0])
        clusters: list[list[tuple]] = []
        for f in feats:
            if not clusters or abs(f[0] - clusters[-1][-1][0]) > cluster_gap:
                clusters.append([f])
            else:
                clusters[-1].append(f)

        candidates = []
        for cluster in clusters:
            xs, ys, weights = [], [], []
            total_weight = 0.0
            for x_at_bottom, slope, length, x1, y1, x2, y2 in cluster:
                xs.extend([x1, x2])
                ys.extend([y1, y2])
                w = length
                weights.extend([w, w])
                total_weight += length
            if total_weight < 18:  # 短すぎるクラスタは捨てる
                continue
            fit = np.polyfit(ys, xs, 1, w=np.array(weights))
            top_x = int(np.polyval(fit, y_top))
            bottom_x = int(np.polyval(fit, y_bottom - 1))
            poly = np.array([(top_x, y_top), (bottom_x, y_bottom - 1)], dtype=np.int32)
            candidates.append((poly, total_weight))
        return candidates

    def _select_ego_pair(
        self,
        left_cands: list[tuple[np.ndarray, float]],
        right_cands: list[tuple[np.ndarray, float]],
        center_x: float,
        width: int,
        y_bottom: int,
    ) -> tuple[np.ndarray | None, np.ndarray | None, float]:
        """画面中心に最も近い左右1ペアを返す。距離・幅の制約あり。

        Returns: (left_lane, right_lane, confidence)
        """
        if not left_cands or not right_cands:
            return None, None, 0.0
        min_w = int(width * self.min_lane_width_ratio)
        max_w = int(width * self.max_lane_width_ratio)
        best = None
        best_score = -1.0
        for lp, lw in left_cands:
            l_bottom_x = int(lp[1][0])
            if l_bottom_x >= center_x:   # 左候補なのに中心より右ならスキップ
                continue
            for rp, rw in right_cands:
                r_bottom_x = int(rp[1][0])
                if r_bottom_x <= center_x:
                    continue
                lane_w = r_bottom_x - l_bottom_x
                if not (min_w <= lane_w <= max_w):
                    continue
                # 中心からのずれが小さく、線分長が大きいほど高スコア
                pair_center = (l_bottom_x + r_bottom_x) / 2
                center_offset = abs(pair_center - center_x) / max(width / 2, 1)
                length_score = (lw + rw) / 200.0
                score = length_score - center_offset
                if score > best_score:
                    best_score = score
                    best = (lp, rp)
        if best is None:
            return None, None, 0.0
        # confidence: 0.3-1.0 にクリップ（line 長で正規化）
        confidence = float(np.clip(best_score / 3.0 + 0.3, 0.0, 1.0))
        return best[0], best[1], confidence

    def _fallback_polygon(self, width: int, height: int) -> np.ndarray:
        return fallback_ego_lane_polygon(
            width,
            height,
            self.center_x_ratio,
            self.zone_top_y_ratio,
            self.zone_bottom_width_ratio,
            self.zone_top_width_ratio,
            self.zone_top_offset_ratio,
        )

    def _lane_edges(self, roi: np.ndarray) -> np.ndarray:
        """低コントラスト対応エッジ + 白/黄マスクで点線にも強くする。"""
        hls = cv2.cvtColor(roi, cv2.COLOR_BGR2HLS)
        lightness = hls[:, :, 1]
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
        blur = cv2.GaussianBlur(enhanced, (5, 5), 0)
        median = float(np.median(blur))
        canny_low = int(max(25, 0.66 * median))
        canny_high = int(min(180, max(canny_low + 30, 1.33 * median)))
        edges = cv2.Canny(blur, canny_low, canny_high)

        # 車線は縦・斜め方向に伸びるため、横方向輝度勾配も弱い線の手掛かりにする。
        sobel_x = cv2.Sobel(blur, cv2.CV_16S, 1, 0, ksize=3)
        gradient = cv2.convertScaleAbs(sobel_x)
        _, gradient = cv2.threshold(gradient, 28, 255, cv2.THRESH_BINARY)
        edges = cv2.bitwise_or(edges, gradient)
        if not self.dashed_support:
            return edges

        # HLS は影や路面の明暗変化でも白線・黄線の色を分離しやすい。
        l_mean = float(lightness.mean())
        white_l_min = 95 if l_mean < 80 else 125
        white = cv2.inRange(hls, (0, white_l_min, 0), (180, 255, 120))
        yellow = cv2.inRange(hls, (12, 55, 45), (42, 255, 255))
        lane_mask = cv2.bitwise_or(white, yellow)
        # 縦方向に長い構造でモルフォロジー閉処理 → 破線断片を線分に結合
        kernel_height = int(np.clip(round(roi.shape[0] * 0.08), 9, 21))
        kernel_height += 1 - kernel_height % 2
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, kernel_height))
        lane_mask = cv2.morphologyEx(lane_mask, cv2.MORPH_CLOSE, vertical_kernel, iterations=2)
        # 細かいノイズを開いて消す
        small_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        lane_mask = cv2.morphologyEx(lane_mask, cv2.MORPH_OPEN, small_kernel)
        # 色マスク境界と輝度エッジを統合
        return cv2.bitwise_or(edges, cv2.Canny(lane_mask, 50, 150))
