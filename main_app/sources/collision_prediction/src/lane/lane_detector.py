from __future__ import annotations

from collections import deque

import numpy as np

from src.lane.classical import ClassicalLaneDetector
from src.lane.ipm import IPMLaneDetector
from src.types import Alert, LaneInfo


class LaneDetector:
    """ClassicalLaneDetector に時間平滑化と confidence を加えた高水準API。

    生活道路など白線が薄い・無い場合でも、過去 N フレームの平均で安定化する。
    全フレームで信頼できない場合はフォールバック台形を使う（既存挙動）。
    """

    def __init__(
        self,
        ldw_threshold_px: int = 25,
        ldw_release_px: int = 45,
        center_x_ratio: float = 0.5,
        zone_top_y_ratio: float = 0.45,
        zone_bottom_width_ratio: float = 0.40,
        zone_top_width_ratio: float = 0.10,
        zone_top_offset_ratio: float = 0.0,
        dashed_support: bool = True,
        hough_threshold: int = 20,
        min_line_length: int = 14,
        max_line_gap: int = 220,
        smoothing_window: int = 15,
        min_confidence: float = 0.3,
        method: str = "classical",
        ipm_source_top_y_ratio: float = 0.48,
        ipm_source_bottom_width_ratio: float = 0.90,
        ipm_source_top_width_ratio: float = 0.18,
        ipm_track_margin_px: int = 24,
        ipm_min_lane_pixels: int = 28,
        ipm_processing_scale: float = 0.50,
        camera_matrix: list[float] | None = None,
        distortion_coeffs: list[float] | None = None,
        acquire_frames: int = 2,
        max_result_age_ms: int = 120,
        ipm_classical_fallback: bool = True,
        ipm_fallback_min_confidence: float = 0.45,
        ipm_max_center_jump_ratio: float = 0.20,
        ipm_max_width_change_ratio: float = 0.50,
        ldw_max_offset_ratio: float = 3.00,
    ):
        self.center_x_ratio = center_x_ratio
        self.classical = ClassicalLaneDetector(
            center_x_ratio=center_x_ratio,
            zone_top_y_ratio=zone_top_y_ratio,
            zone_bottom_width_ratio=zone_bottom_width_ratio,
            zone_top_width_ratio=zone_top_width_ratio,
            zone_top_offset_ratio=zone_top_offset_ratio,
            dashed_support=dashed_support,
            hough_threshold=hough_threshold,
            min_line_length=min_line_length,
            max_line_gap=max_line_gap,
        )
        self.ldw_threshold_px = ldw_threshold_px
        self.ldw_release_px = ldw_release_px
        self._ldw_active = False
        # LDW 連続フレームカウンタ（瞬間ノイズ除去）
        self._ldw_warn_streak: int = 0
        self._ldw_critical_streak: int = 0
        # レーン位置履歴（左右の上下点座標を保存して平滑化）
        self._left_hist: deque[np.ndarray] = deque(maxlen=smoothing_window)
        self._right_hist: deque[np.ndarray] = deque(maxlen=smoothing_window)
        self._confidence_hist: deque[float] = deque(maxlen=smoothing_window)
        self.min_confidence = min_confidence
        self._last_confidence: float = 0.0
        self.method = method
        self.acquire_frames = max(1, acquire_frames)
        self.max_result_age_s = max(0.01, max_result_age_ms / 1000.0)
        self._last_result_timestamp: float | None = None
        self._acquire_count = 0
        self._missed_ipm_detections = 0
        self._last_accepted_geometry: tuple[float, float] | None = None
        self._ldw_ready = method != "ipm"
        self.state = "search"
        self.ipm_classical_fallback = ipm_classical_fallback
        self.ipm_fallback_min_confidence = ipm_fallback_min_confidence
        self.ipm_max_center_jump_ratio = ipm_max_center_jump_ratio
        self.ipm_max_width_change_ratio = ipm_max_width_change_ratio
        self.ldw_max_offset_ratio = ldw_max_offset_ratio
        self.ipm = IPMLaneDetector(
            center_x_ratio=center_x_ratio,
            source_top_y_ratio=ipm_source_top_y_ratio,
            source_bottom_width_ratio=ipm_source_bottom_width_ratio,
            source_top_width_ratio=ipm_source_top_width_ratio,
            track_margin_px=ipm_track_margin_px,
            min_lane_pixels=ipm_min_lane_pixels,
            min_confidence=min_confidence,
            processing_scale=ipm_processing_scale,
            camera_matrix=camera_matrix,
            distortion_coeffs=distortion_coeffs,
        )

    def detect(
        self,
        frame: np.ndarray,
        road_mask: np.ndarray | None = None,
        timestamp: float | None = None,
        **_kwargs,
    ) -> LaneInfo:
        """車線を検出して LaneInfo を返す。

        まず古典手法（白/黄線、Hough）で実線・点線を試す。
        両側とも検出できず履歴も足りない場合、路面マスクの左右輪郭から
        仮レーンを構築するフォールバックを試みる（白線なし道路向け）。
        """
        if self.method == "ipm" or getattr(self, "curve_enabled", False):
            return self._detect_ipm(
                frame, timestamp, _kwargs.get("vehicle_bboxes"), _kwargs.get("reference_polygon"),
            )

        info, confidence = self.classical.detect(frame)
        self._last_confidence = confidence

        # 白線なし道フォールバック: classical で両側とも検出できず履歴も少ない時のみ
        if (info.left_lane is None and info.right_lane is None
                and len(self._left_hist) < 3 and road_mask is not None):
            road_info = _road_mask_to_lane(road_mask, frame.shape[1], frame.shape[0])
            if road_info is not None:
                info = road_info
                confidence = 0.20   # 古典より低めの信頼度
                self._last_confidence = confidence

        # 信頼できる検出のみ履歴に積む
        # 左右レーンの交差ガード: 上下どちらでも左の x が右の x を超えていたら無効化
        if confidence >= self.min_confidence and info.left_lane is not None and info.right_lane is not None:
            ll, rl = info.left_lane, info.right_lane
            crossed = (ll[0][0] >= rl[0][0]) or (ll[1][0] >= rl[1][0])
            if not crossed:
                self._left_hist.append(ll.astype(np.float32))
                self._right_hist.append(rl.astype(np.float32))
                self._confidence_hist.append(confidence)
            else:
                # 交差した検出は信頼性ゼロ扱い、今回 confidence も下げる
                self._last_confidence = max(0.0, confidence - 0.5)
                confidence = self._last_confidence

        # 平滑化結果がまだ無ければ、今回の生検出 or フォールバック
        if not self._left_hist or not self._right_hist:
            return info

        # 平滑化（重み付き平均: 信頼度で重み付け）
        left_smoothed = self._weighted_average(self._left_hist, list(self._confidence_hist))
        right_smoothed = self._weighted_average(self._right_hist, list(self._confidence_hist))
        # 台形ゾーンの中心 (center_x_ratio) を自動調整: 自車レーン底辺中点を採用
        if self._last_confidence >= self.min_confidence:
            lane_center_x = (left_smoothed[1][0] + right_smoothed[1][0]) / 2
            frame_width = frame.shape[1]
            auto_center = float(lane_center_x / max(frame_width, 1))
            # 既存値と急変しないよう緩やか追従
            self.center_x_ratio = 0.7 * self.center_x_ratio + 0.3 * float(np.clip(auto_center, 0.3, 0.7))
        polygon = np.array(
            [left_smoothed[-1], left_smoothed[0], right_smoothed[0], right_smoothed[-1]],
            dtype=np.int32,
        )
        from src.utils.geometry import line_intersection
        vp = line_intersection(
            tuple(left_smoothed[0]), tuple(left_smoothed[-1]),
            tuple(right_smoothed[0]), tuple(right_smoothed[-1]),
        )
        return LaneInfo(
            left_lane=left_smoothed.astype(np.int32),
            right_lane=right_smoothed.astype(np.int32),
            ego_lane_polygon=polygon,
            vanishing_point=vp,
        )

    def _detect_ipm(
        self,
        frame: np.ndarray,
        timestamp: float | None,
        vehicle_bboxes: list[tuple[float, float, float, float]] | None,
        reference_polygon: np.ndarray | None,
    ) -> LaneInfo:
        """IPM mode never substitutes a road mask or a static trapezoid for a lane."""
        info, confidence = self.ipm.detect(
            frame, vehicle_bboxes=vehicle_bboxes, reference_polygon=reference_polygon,
        )
        if (confidence >= self.min_confidence
                and self._is_plausible_ipm_lane(info, frame.shape[1], reference_polygon)):
            return self._accept_ipm_lane(info, confidence, timestamp, self.ipm.last_mode, frame.shape[1])

        # This is an image-based fallback, not a road-mask or fixed-trapezoid
        # substitute. It raises recall for faint markings without claiming a
        # lane exists on an unmarked road.
        if self.ipm_classical_fallback and not getattr(self, "curve_enabled", False):
            fallback_info, fallback_confidence = self.classical.detect(frame)
            if (fallback_confidence >= max(self.min_confidence, self.ipm_fallback_min_confidence)
                    and self._is_plausible_ipm_lane(fallback_info, frame.shape[1], reference_polygon)):
                return self._accept_ipm_lane(
                    fallback_info, fallback_confidence, timestamp, "acquire", frame.shape[1],
                )

        self._reject_ipm_lane()
        return LaneInfo(None, None, None, None)

    def _accept_ipm_lane(
        self,
        info: LaneInfo,
        confidence: float,
        timestamp: float | None,
        mode: str,
        frame_width: int,
    ) -> LaneInfo:
        self._last_confidence = confidence
        self._last_result_timestamp = timestamp
        self._missed_ipm_detections = 0
        self._last_accepted_geometry = self._lane_geometry(info, frame_width)
        if mode == "acquire":
            self._acquire_count += 1
            self.state = "acquire"
        else:
            self._acquire_count = max(self.acquire_frames, self._acquire_count)
            self.state = "track"
        self._ldw_ready = self._acquire_count >= self.acquire_frames
        return info

    def _reject_ipm_lane(self) -> None:
        self._last_confidence = 0.0
        self._acquire_count = 0
        self._ldw_ready = False
        self._missed_ipm_detections += 1
        self.state = "lost" if self._last_result_timestamp is not None else "search"
        if self._missed_ipm_detections >= 3:
            self._last_accepted_geometry = None
            self._last_result_timestamp = None
            self.state = "search"

    def _is_plausible_ipm_lane(
        self,
        info: LaneInfo,
        frame_width: int,
        reference_polygon: np.ndarray | None = None,
    ) -> bool:
        if info.left_lane is None or info.right_lane is None:
            return False
        geometry = self._lane_geometry(info, frame_width)
        if geometry is None:
            return False
        center, lane_width = geometry
        if not 0.20 <= center <= 0.80 or not 0.18 <= lane_width <= 0.86:
            return False
        if self._reference_alignment(info, reference_polygon, frame_width) < 0.18:
            return False
        previous = self._last_accepted_geometry
        if previous is None:
            return True
        previous_center, previous_width = previous
        if abs(center - previous_center) > self.ipm_max_center_jump_ratio:
            return False
        return abs(lane_width - previous_width) <= previous_width * self.ipm_max_width_change_ratio

    @staticmethod
    def _reference_alignment(
        info: LaneInfo,
        reference_polygon: np.ndarray | None,
        frame_width: int,
    ) -> float:
        if reference_polygon is None or len(reference_polygon) < 4:
            return 1.0
        geometry = LaneDetector._lane_geometry(info, frame_width)
        if geometry is None:
            return 0.0
        center, lane_width = geometry
        ref_left = float(reference_polygon[0][0]) / frame_width
        ref_right = float(reference_polygon[3][0]) / frame_width
        reference_center = (ref_left + ref_right) / 2
        reference_width = max(ref_right - ref_left, 0.10)
        center_error = abs(center - reference_center) / reference_width
        width_error = abs(np.log(max(lane_width, 1e-3) / reference_width))
        return float(np.exp(-0.5 * (center_error / 0.45) ** 2 - 0.5 * (width_error / 0.90) ** 2))

    @staticmethod
    def _lane_geometry(info: LaneInfo, frame_width: float) -> tuple[float, float] | None:
        if info.left_lane is None or info.right_lane is None or frame_width <= 0:
            return None
        left_bottom = float(info.left_lane[-1][0])
        right_bottom = float(info.right_lane[-1][0])
        lane_width = (right_bottom - left_bottom) / frame_width
        if lane_width <= 0:
            return None
        return ((left_bottom + right_bottom) / 2 / frame_width, lane_width)

    @staticmethod
    def _weighted_average(hist: deque[np.ndarray], weights: list[float]) -> np.ndarray:
        stack = np.stack(list(hist))   # (N, 2, 2)
        w = np.array(weights, dtype=np.float32).reshape(-1, 1, 1)
        return (stack * w).sum(axis=0) / max(w.sum(), 1e-6)

    @property
    def last_confidence(self) -> float:
        return self._last_confidence

    @property
    def ldw_ready(self) -> bool:
        return self._ldw_ready

    def is_result_fresh(self, timestamp: float | None) -> bool:
        if self.method != "ipm":
            return True
        if timestamp is None or self._last_result_timestamp is None:
            return False
        return 0.0 <= timestamp - self._last_result_timestamp <= self.max_result_age_s

    def analyze_ldw(self, lanes: LaneInfo, frame_width: int, timestamp: float | None = None) -> Alert | None:
        """車線逸脱を「自車レーン中心からの偏差率」で判定する。

        - 自車位置 = 画像中央 (frame_width / 2)
        - 自車レーン中心 = 左右レーン底辺 x の中点
        - 偏差率 = |自車x - レーン中心x| / 車線半幅
          - < 0.6  → 正常
          - 0.6-0.9 → warn (車線寄り)
          - ≥ 0.9   → critical (車線外れた)
        - 連続 3 フレーム以上同じ判定が続いた時のみ発火（瞬間ノイズ除去）
        """
        # 検出信頼度が低い時は LDW を出さない（誤発火防止）
        if (self._last_confidence < self.min_confidence
                or not self._ldw_ready
                or not self.is_result_fresh(timestamp)):
            self._ldw_active = False
            self._ldw_warn_streak = 0
            self._ldw_critical_streak = 0
            return None
        if lanes.ego_lane_polygon is None or len(lanes.ego_lane_polygon) < 4:
            return None

        # ego_lane_polygon の構成: [左下, 左上, 右上, 右下]
        left_bottom_x = float(lanes.ego_lane_polygon[0][0])
        right_bottom_x = float(lanes.ego_lane_polygon[-1][0])
        lane_center_x = (left_bottom_x + right_bottom_x) / 2
        lane_half_width = (right_bottom_x - left_bottom_x) / 2
        if lane_half_width < 8:   # 車線幅が小さすぎる → 信頼できない
            self._ldw_active = False
            return None

        ego_x = frame_width / 2
        offset = ego_x - lane_center_x
        ratio = abs(offset) / lane_half_width
        direction = "右" if offset > 0 else "左"

        # A valid ego lane cannot jump far enough to create a multi-lane-width
        # offset in one observation. Fail closed instead of reporting nonsense.
        if ratio > self.ldw_max_offset_ratio:
            self._ldw_active = False
            self._ldw_warn_streak = 0
            self._ldw_critical_streak = 0
            return None

        # 連続フレームカウンタを更新
        if ratio >= 0.9:
            self._ldw_critical_streak += 1
            self._ldw_warn_streak = 0
        elif ratio >= 0.6:
            self._ldw_warn_streak += 1
            self._ldw_critical_streak = 0
        else:
            self._ldw_warn_streak = 0
            self._ldw_critical_streak = 0
            self._ldw_active = False
            return None

        # 連続 3 フレーム以上で発火
        if self._ldw_critical_streak >= 3:
            self._ldw_active = True
            return Alert("ldw", 3, None,
                          f"⚠ 車線逸脱 ({direction}方向 {int(ratio*100)}%)",
                          None, direction)
        if self._ldw_warn_streak >= 3:
            self._ldw_active = True
            return Alert("ldw", 2, None,
                          f"車線寄り注意 ({direction}側 {int(ratio*100)}%)",
                          None, direction)
        return None


def _road_mask_to_lane(road_mask: np.ndarray, width: int, height: int) -> LaneInfo | None:
    """白線が無い道で、路面マスクの左右輪郭から仮レーンを作る。

    画像下半分で各 y 行ごとに路面領域 (==1) の最左・最右 x を取り、線形フィット。
    自車レーンとして「路面の中央寄り 1/2 幅」を採用（広すぎる道で2車線分にならないように）。
    """
    if road_mask is None or road_mask.shape != (height, width):
        return None
    half = height // 2
    bottom = road_mask[half:]
    if (bottom == 1).sum() < 200:
        return None
    left_xs: list[int] = []
    right_xs: list[int] = []
    ys: list[int] = []
    for y_local in range(0, bottom.shape[0], 5):
        row = bottom[y_local]
        idx = np.where(row == 1)[0]
        if len(idx) < 15:
            continue
        left_xs.append(int(idx[0]))
        right_xs.append(int(idx[-1]))
        ys.append(y_local + half)
    if len(ys) < 4:
        return None
    ys_arr = np.array(ys, dtype=np.float32)
    left_fit = np.polyfit(ys_arr, np.array(left_xs, dtype=np.float32), 1)
    right_fit = np.polyfit(ys_arr, np.array(right_xs, dtype=np.float32), 1)
    y_top = int(height * 0.62)
    y_bot = height - 1
    road_left_x_top = int(np.polyval(left_fit, y_top))
    road_left_x_bot = int(np.polyval(left_fit, y_bot))
    road_right_x_top = int(np.polyval(right_fit, y_top))
    road_right_x_bot = int(np.polyval(right_fit, y_bot))
    lane_w = road_right_x_bot - road_left_x_bot
    if lane_w < 30:
        return None
    cx = (road_left_x_bot + road_right_x_bot) / 2
    cx_top = (road_left_x_top + road_right_x_top) / 2
    # 自車レーン幅は路面幅の 1/2（路面が広くても自車レーンだけを推定）
    half_bot = min(lane_w * 0.5, width * 0.20)
    half_top = max(8.0, half_bot * 0.35)
    left_lane = np.array([
        (int(cx_top - half_top), y_top),
        (int(cx - half_bot), y_bot),
    ], dtype=np.int32)
    right_lane = np.array([
        (int(cx_top + half_top), y_top),
        (int(cx + half_bot), y_bot),
    ], dtype=np.int32)
    polygon = np.array([
        left_lane[1], left_lane[0], right_lane[0], right_lane[1],
    ], dtype=np.int32)
    from src.utils.geometry import line_intersection
    vp = line_intersection(
        tuple(left_lane[0]), tuple(left_lane[1]),
        tuple(right_lane[0]), tuple(right_lane[1]),
    )
    return LaneInfo(left_lane, right_lane, polygon, vp)
