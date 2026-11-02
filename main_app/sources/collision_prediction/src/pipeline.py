from __future__ import annotations

import time
from dataclasses import replace

import cv2
import numpy as np

from src.alert.alert_manager import AlertManager
from src.depth.monocular import MonocularDepthEstimator
from src.detection.blind_check import BlindnessDetector
from src.detection.hailo_multimodel import HailoDepthAnalysis, HailoNetworks
from src.enhancement.enhancer import FrameEnhancer
from src.lane.auto_zone import AutoZoneController
from src.lane.lane_detector import LaneDetector
from src.motion.absolute_velocity import AbsoluteVelocityEstimator
from src.motion.ego_motion import EgoMotionEstimator
from src.motion.speed_source import VisualSpeedSource
from src.prediction.risk_analyzer import RiskAnalyzer
from src.prediction.depth_risk import DepthRiskAnalyzer, fuse_depth_alerts
from src.render.renderer import Renderer
from src.segmentation.road_segmenter import RoadSegmenter
from src.signs.jp_sign_detector import JpSignDetector
from src.tracking.bbox_flow import BBoxFlowInterpolator
from src.tracking.byte_tracker import YoloTracker
from src.types import LaneInfo, SceneContext
from src.utils.config import resolve_device
from src.utils.geometry import fallback_ego_lane_polygon


class Pipeline:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        detector_cfg = cfg.get("detector", {})
        lane_cfg = cfg.get("lane", {})
        segmenter_cfg = cfg.get("segmenter", {})
        depth_cfg = cfg.get("depth", {})
        risk_cfg = cfg.get("risk", {})
        ui_cfg = cfg.get("ui", {})
        scene_cfg = cfg.get("hailo_scene", {})
        legacy_scene_enabled = bool(scene_cfg.get("enabled", False))
        self.hailo_depth_enabled = bool(scene_cfg.get("depth_enabled", legacy_scene_enabled))
        self.hailo_networks = HailoNetworks() if self.hailo_depth_enabled else None
        self.hailo_scene = HailoDepthAnalysis(
            self.hailo_networks,
            scene_cfg.get("depth_model", "models/hailo8/scdepthv3.hef"),
        ) if self.hailo_networks else None
        self.hailo_scene_interval = max(6, int(scene_cfg.get("every_n_frames", 12)))
        self.device = resolve_device(detector_cfg.get("device", "auto"))
        self.tracker = YoloTracker(
            weights=detector_cfg.get("weights", "yolo11n.pt"),
            device=self.device,
            conf=float(detector_cfg.get("conf", 0.18)),
            iou=float(detector_cfg.get("iou", 0.5)),
            imgsz=int(detector_cfg.get("imgsz", 640)),
            max_det=int(detector_cfg.get("max_det", 120)),
            classes=detector_cfg.get("classes"),
            enabled=bool(ui_cfg.get("enable_detection", True) and detector_cfg.get("enabled", True)),
            fallback_enabled=bool(detector_cfg.get("fallback_enabled", True)),
            conf_per_class=detector_cfg.get("conf_per_class"),
            shared_networks=self.hailo_networks,
        )
        self.detector_every_n_frames = max(1, int(detector_cfg.get("every_n_frames", 1)))
        self.detector_phase = int(detector_cfg.get("phase", 1))
        self._last_tracks = []
        self.segmenter = RoadSegmenter(
            model=segmenter_cfg.get("model", "models/segformer-b0-cityscapes"),
            every_n_frames=int(segmenter_cfg.get("every_n_frames", 3)),
            input_size=int(segmenter_cfg.get("input_size", 512)),
            enabled=bool(segmenter_cfg.get("enabled", False)),
            device=self.device,
        )
        self.lane_detector = LaneDetector(
            ldw_threshold_px=int(lane_cfg.get("ldw_threshold_px", 30)),
            ldw_release_px=int(lane_cfg.get("ldw_release_px", 50)),
            center_x_ratio=float(lane_cfg.get("center_x_ratio", 0.5)),
            zone_top_y_ratio=float(lane_cfg.get("zone_top_y_ratio", 0.45)),
            zone_bottom_width_ratio=float(lane_cfg.get("zone_bottom_width_ratio", 0.40)),
            zone_top_width_ratio=float(lane_cfg.get("zone_top_width_ratio", 0.10)),
            zone_top_offset_ratio=float(lane_cfg.get("zone_top_offset_ratio", 0.0)),
            dashed_support=bool(lane_cfg.get("dashed_support", True)),
            hough_threshold=int(lane_cfg.get("hough_threshold", 24)),
            min_line_length=int(lane_cfg.get("min_line_length", 18)),
            max_line_gap=int(lane_cfg.get("max_line_gap", 180)),
            method=str(lane_cfg.get("method", "classical")),
            ipm_source_top_y_ratio=float(lane_cfg.get("ipm_source_top_y_ratio", 0.48)),
            ipm_source_bottom_width_ratio=float(lane_cfg.get("ipm_source_bottom_width_ratio", 0.90)),
            ipm_source_top_width_ratio=float(lane_cfg.get("ipm_source_top_width_ratio", 0.18)),
            ipm_track_margin_px=int(lane_cfg.get("ipm_track_margin_px", 24)),
            ipm_min_lane_pixels=int(lane_cfg.get("ipm_min_lane_pixels", 28)),
            ipm_processing_scale=float(lane_cfg.get("ipm_processing_scale", 0.50)),
            camera_matrix=lane_cfg.get("camera_matrix"),
            distortion_coeffs=lane_cfg.get("distortion_coeffs"),
            acquire_frames=int(lane_cfg.get("acquire_frames", 2)),
            max_result_age_ms=int(lane_cfg.get("max_result_age_ms", 120)),
            ipm_classical_fallback=bool(lane_cfg.get("ipm_classical_fallback", True)),
            ipm_fallback_min_confidence=float(lane_cfg.get("ipm_fallback_min_confidence", 0.45)),
            ipm_max_center_jump_ratio=float(lane_cfg.get("ipm_max_center_jump_ratio", 0.20)),
            ipm_max_width_change_ratio=float(lane_cfg.get("ipm_max_width_change_ratio", 0.50)),
            ldw_max_offset_ratio=float(lane_cfg.get("ldw_max_offset_ratio", 3.00)),
        )
        self.center_x_ratio = float(lane_cfg.get("center_x_ratio", 0.5))
        self.zone_meta = {
            "center_x_ratio": float(lane_cfg.get("center_x_ratio", 0.5)),
            "zone_top_y_ratio": float(lane_cfg.get("zone_top_y_ratio", 0.45)),
            "zone_bottom_width_ratio": float(lane_cfg.get("zone_bottom_width_ratio", 0.40)),
            "zone_top_width_ratio": float(lane_cfg.get("zone_top_width_ratio", 0.10)),
            "zone_top_offset_ratio": float(lane_cfg.get("zone_top_offset_ratio", 0.0)),
        }
        self.lane_detector.curve_enabled = bool(ui_cfg.get("curve_lanes", False))
        self.lane_detector.ipm.curve_enabled = self.lane_detector.curve_enabled
        self.lane_every_n_frames = max(1, int(lane_cfg.get("every_n_frames", 1)))
        self.lane_phase = int(lane_cfg.get("phase", 0))
        self.use_lane_reference_zone = bool(lane_cfg.get("use_reference_zone", True))
        self._last_lanes = empty_lane_info()
        self._lane_deferred = False
        self._realtime_schedule = bool(ui_cfg.get("independent_schedule", False))
        self._last_detector_time = None
        self._last_lane_time = None
        self._last_ai_depth_time = None
        self._ai_depth_error = None
        self.depth_risk = DepthRiskAnalyzer(scene_cfg.get("vehicle_exclusion_polygon"))
        self.detector_runs = 0
        self.lane_runs = 0
        self.depth = MonocularDepthEstimator(
            model=depth_cfg.get("model", "depth-anything/Depth-Anything-V2-Small"),
            every_n_frames=int(depth_cfg.get("every_n_frames", 2)),
            cam_height_m=float(depth_cfg.get("cam_height_m", 1.2)),
            enabled=bool(depth_cfg.get("enabled", True)),
            device=self.device,
        )
        self.risk = RiskAnalyzer(
            ttc_critical_s=float(risk_cfg.get("ttc_critical_s", 1.5)),
            ttc_warn_s=float(risk_cfg.get("ttc_warn_s", 3.0)),
            ego_lane_dwell_s=float(risk_cfg.get("ego_lane_dwell_s", 0.25)),
            following_closing_mps=float(risk_cfg.get("following_closing_mps", 0.8)),
        )
        self.risk.absolute_velocity = None   # 後でセット（self ができてから）
        self.alert_manager = AlertManager()
        self.renderer = Renderer()
        self.renderer.overlay_scale = float(ui_cfg.get("overlay_size_scale", 1.0))
        self.show_debug_mask = bool(ui_cfg.get("show_debug_mask", False))
        self.enable_lanes = bool(ui_cfg.get("enable_lanes", True))
        self.enable_risk = bool(ui_cfg.get("enable_risk", True))
        self.enable_enhancement = bool(ui_cfg.get("enable_enhancement", False))
        self.enable_signs = bool(ui_cfg.get("enable_signs", False))
        self.signs_every_n_frames = max(1, int(ui_cfg.get("signs_every_n_frames", 2)))
        # ROI モード: off / trapezoid / rectangle
        # 後方互換: 旧 enable_roi_crop=True → trapezoid とみなす
        legacy_roi = bool(ui_cfg.get("enable_roi_crop", False))
        self.roi_mode = str(ui_cfg.get("roi_mode", "trapezoid" if legacy_roi else "off"))
        rect_cfg = ui_cfg.get("roi_rect", {}) or {}
        self.roi_rect = {
            "x_ratio": float(rect_cfg.get("x_ratio", 0.05)),
            "y_ratio": float(rect_cfg.get("y_ratio", 0.30)),
            "w_ratio": float(rect_cfg.get("w_ratio", 0.90)),
            "h_ratio": float(rect_cfg.get("h_ratio", 0.65)),
        }
        self.enable_distance = bool(ui_cfg.get("enable_distance", True))
        # カメラ異常検知 (検出不能状態)
        self.enable_blind_check = bool(ui_cfg.get("enable_blind_check", False))
        self.blind_check_seconds = float(ui_cfg.get("blind_check_seconds", 2.0))
        self.blind_detector = BlindnessDetector(no_detect_seconds=self.blind_check_seconds)
        self.enhancer = FrameEnhancer()
        self.bbox_flow = BBoxFlowInterpolator()
        self.sign_detector = JpSignDetector(enabled=self.enable_signs)
        self._last_signals: list = []
        # エゴモーション推定（自車の動きを毎フレーム推定）
        self.ego_motion = EgoMotionEstimator()
        self.speed_source = VisualSpeedSource()
        self.enable_ego_motion = bool(ui_cfg.get("enable_ego_motion", True))
        # 絶対速度ベクトル推定（自車速度+IPMで実世界 m/s）
        self.absolute_velocity = AbsoluteVelocityEstimator(self.speed_source)
        self.risk.absolute_velocity = self.absolute_velocity
        # 台形ゾーン自動コントローラ
        self.auto_zone = AutoZoneController()

    def close(self) -> None:
        self.tracker.close()
        if self.hailo_networks:
            self.hailo_networks.close()

    def update_settings(self, cfg: dict) -> None:
        """UIスライダー/チェックボックス変更を再生中に反映する。

        モデルの再ロードは行わず、フラグと閾値だけ差し替える。
        """
        ui_cfg = cfg.get("ui", {})
        lane_cfg = cfg.get("lane", {})
        detector_cfg = cfg.get("detector", {})
        # YOLO 重みの差し替え（ファイルパスが変わったら再ロード）
        new_weights = detector_cfg.get("weights")
        if new_weights and hasattr(self.tracker, "set_weights") and new_weights != getattr(self.tracker, "weights", None):
            self.tracker.set_weights(new_weights)
        # 検出パラメータのライブ反映
        if "conf" in detector_cfg:
            self.tracker.conf = float(detector_cfg["conf"])
            self.tracker.detector.conf = self.tracker.conf
        if "iou" in detector_cfg:
            self.tracker.iou = float(detector_cfg["iou"])
            self.tracker.detector.iou = self.tracker.iou
        if "imgsz" in detector_cfg:
            self.tracker.imgsz = int(detector_cfg["imgsz"])
            self.tracker.detector.imgsz = self.tracker.imgsz
        if "max_det" in detector_cfg:
            self.tracker.max_det = int(detector_cfg["max_det"])
            self.tracker.detector.max_det = self.tracker.max_det
        if isinstance(detector_cfg.get("conf_per_class"), dict):
            self.tracker.conf_per_class = dict(detector_cfg["conf_per_class"])
        curve_enabled = bool(ui_cfg.get("curve_lanes", False))
        if curve_enabled != getattr(self.lane_detector, "curve_enabled", False):
            self.lane_detector.ipm = type(self.lane_detector.ipm)()
            self._last_lanes = empty_lane_info()
            self.lane_detector._left_hist.clear()
            self.lane_detector._right_hist.clear()
            self.lane_detector._confidence_hist.clear()
            self.lane_detector._reject_ipm_lane()
        self.lane_detector.curve_enabled = curve_enabled
        self.lane_detector.ipm.curve_enabled = curve_enabled
        # 車線パラメータのライブ反映
        if hasattr(self.lane_detector, "classical"):
            cls = self.lane_detector.classical
            for k in ("hough_threshold", "min_line_length", "max_line_gap", "dashed_support"):
                if k in lane_cfg and hasattr(cls, k):
                    setattr(cls, k, lane_cfg[k])
        if "ldw_threshold_px" in lane_cfg and hasattr(self.lane_detector, "ldw_threshold_px"):
            self.lane_detector.ldw_threshold_px = int(lane_cfg["ldw_threshold_px"])
        if "ldw_release_px" in lane_cfg and hasattr(self.lane_detector, "ldw_release_px"):
            self.lane_detector.ldw_release_px = int(lane_cfg["ldw_release_px"])
        # 危険判定のライブ反映
        risk_cfg = cfg.get("risk", {})
        if "ttc_critical_s" in risk_cfg and hasattr(self.risk, "ttc_critical_s"):
            self.risk.ttc_critical_s = float(risk_cfg["ttc_critical_s"])
        if "ttc_warn_s" in risk_cfg and hasattr(self.risk, "ttc_warn_s"):
            self.risk.ttc_warn_s = float(risk_cfg["ttc_warn_s"])
        if "ego_lane_dwell_s" in risk_cfg:
            self.risk.ego_lane_dwell_s = float(risk_cfg["ego_lane_dwell_s"])
        if "following_closing_mps" in risk_cfg:
            self.risk.following_closing_mps = float(risk_cfg["following_closing_mps"])
        # セグメンタ / 深度 のライブ ON/OFF
        seg_cfg = cfg.get("segmenter", {})
        if "enabled" in seg_cfg and hasattr(self.segmenter, "enabled"):
            self.segmenter.enabled = bool(seg_cfg["enabled"])
        if "every_n_frames" in seg_cfg and hasattr(self.segmenter, "every_n_frames"):
            self.segmenter.every_n_frames = max(1, int(seg_cfg["every_n_frames"]))
        depth_cfg = cfg.get("depth", {})
        if "enabled" in depth_cfg and hasattr(self.depth, "enabled"):
            self.depth.enabled = bool(depth_cfg["enabled"])
        if "every_n_frames" in depth_cfg and hasattr(self.depth, "every_n_frames"):
            self.depth.every_n_frames = max(1, int(depth_cfg["every_n_frames"]))
        # 処理間隔（フレームスキップ）をライブ更新
        self.detector_every_n_frames = max(1, int(detector_cfg.get("every_n_frames", self.detector_every_n_frames)))
        self.lane_every_n_frames = max(1, int(lane_cfg.get("every_n_frames", self.lane_every_n_frames)))
        self.detector_phase = int(detector_cfg.get("phase", self.detector_phase))
        self.lane_phase = int(lane_cfg.get("phase", self.lane_phase))
        self.signs_every_n_frames = max(1, int(ui_cfg.get("signs_every_n_frames", self.signs_every_n_frames)))
        # cfg 自体も差し替え（process() から参照される）
        self.cfg = cfg
        # 機能トグル
        self.enable_lanes = bool(ui_cfg.get("enable_lanes", self.enable_lanes))
        self.enable_risk = bool(ui_cfg.get("enable_risk", self.enable_risk))
        self.enable_enhancement = bool(ui_cfg.get("enable_enhancement", self.enable_enhancement))
        self.enable_signs = bool(ui_cfg.get("enable_signs", self.enable_signs))
        if "roi_mode" in ui_cfg:
            self.roi_mode = str(ui_cfg["roi_mode"])
        elif "enable_roi_crop" in ui_cfg:
            self.roi_mode = "trapezoid" if bool(ui_cfg["enable_roi_crop"]) else "off"
        rect_cfg = ui_cfg.get("roi_rect")
        if isinstance(rect_cfg, dict):
            for k in ("x_ratio", "y_ratio", "w_ratio", "h_ratio"):
                if k in rect_cfg:
                    self.roi_rect[k] = float(rect_cfg[k])
        self.enable_distance = bool(ui_cfg.get("enable_distance", self.enable_distance))
        if "enable_blind_check" in ui_cfg:
            self.enable_blind_check = bool(ui_cfg["enable_blind_check"])
        if "blind_check_seconds" in ui_cfg:
            self.blind_check_seconds = float(ui_cfg["blind_check_seconds"])
            self.blind_detector.no_detect_seconds = self.blind_check_seconds
        self.show_debug_mask = bool(ui_cfg.get("show_debug_mask", self.show_debug_mask))
        if "overlay_size_scale" in ui_cfg:
            self.renderer.overlay_scale = float(ui_cfg["overlay_size_scale"])
        self.enable_ego_motion = bool(ui_cfg.get("enable_ego_motion", self.enable_ego_motion))
        # 検出/追跡 ON/OFF
        if hasattr(self.tracker, "enabled"):
            self.tracker.enabled = bool(ui_cfg.get("enable_detection", self.tracker.enabled))
        # 信号検出
        self.sign_detector.enabled = self.enable_signs
        # レーン台形パラメータ
        self.lane_detector.center_x_ratio = float(lane_cfg.get("center_x_ratio", self.lane_detector.center_x_ratio))
        self.lane_detector.classical.center_x_ratio = self.lane_detector.center_x_ratio
        self.lane_detector.classical.zone_top_y_ratio = float(lane_cfg.get("zone_top_y_ratio", self.lane_detector.classical.zone_top_y_ratio))
        self.lane_detector.classical.zone_bottom_width_ratio = float(lane_cfg.get("zone_bottom_width_ratio", self.lane_detector.classical.zone_bottom_width_ratio))
        self.lane_detector.classical.zone_top_width_ratio = float(lane_cfg.get("zone_top_width_ratio", self.lane_detector.classical.zone_top_width_ratio))
        self.lane_detector.classical.zone_top_offset_ratio = float(lane_cfg.get("zone_top_offset_ratio", self.lane_detector.classical.zone_top_offset_ratio))
        # zone_meta も更新（描画用）
        self.zone_meta = {
            "center_x_ratio": self.lane_detector.classical.center_x_ratio,
            "zone_top_y_ratio": self.lane_detector.classical.zone_top_y_ratio,
            "zone_bottom_width_ratio": self.lane_detector.classical.zone_bottom_width_ratio,
            "zone_top_width_ratio": self.lane_detector.classical.zone_top_width_ratio,
            "zone_top_offset_ratio": self.lane_detector.classical.zone_top_offset_ratio,
        }
        self.enable_ego_motion = bool(ui_cfg.get("enable_ego_motion", self.enable_ego_motion))

    def process(self, frame: np.ndarray, frame_idx: int, fps: float,
                display_size: tuple[int, int] | None = None,
                timestamp: float | None = None, render: bool = True) -> tuple[np.ndarray, dict]:
        """検出/追跡は `frame` (処理用、小さい) で実行し、描画は `display_size`
        (width, height) のキャンバスに行う。

        - canvas のピクセルは process_frame を引き伸ばしたもの (= 処理解像度の見た目)
        - overlays (BB/矢印/文字) のみ display_size の高解像度座標で描画 (= 綺麗)
        display_size が None または同サイズなら従来通り frame サイズで描画。
        """
        timestamp = timestamp if timestamp is not None else frame_idx / max(fps, 1.0)
        start = time.perf_counter()
        stage_started = start
        stage_ms: dict[str, float] = {}

        def finish_stage(name: str) -> None:
            nonlocal stage_started
            now = time.perf_counter()
            stage_ms[name] = (now - stage_started) * 1000
            stage_started = now

        enhanced = frame
        depth_updated = False
        enhancement_meta = {"night": False, "hdr": False}
        if self.enable_enhancement:
            enhanced, enhancement_meta = self.enhancer.process(frame)
        finish_stage("enhancement")
        if self.hailo_scene:
            scene_cfg = self.cfg.get("hailo_scene", {})
            depth_due = frame_idx % self.hailo_scene_interval == 3
            if "depth_update_hz" in scene_cfg:
                depth_hz = max(0.1, float(scene_cfg.get("depth_update_hz", 1.0)))
                depth_due = self._last_ai_depth_time is None or timestamp < self._last_ai_depth_time or timestamp - self._last_ai_depth_time >= 1.0 / depth_hz
            if self.hailo_depth_enabled and depth_due:
                self._last_ai_depth_time = timestamp
                try:
                    self.hailo_scene.depth(enhanced)
                    self._ai_depth_error = None
                    depth_updated = True
                except Exception as exc:
                    self._ai_depth_error = str(exc)
                    self.hailo_scene.depth_values = None
        finish_stage("ai_depth_inference")
        detector_due = (frame_idx - self.detector_phase) % self.detector_every_n_frames == 0
        lane_due = (frame_idx - self.lane_phase) % self.lane_every_n_frames == 0
        if self._realtime_schedule:
            detector_hz = max(0.1, float(self.cfg.get("detector", {}).get("update_hz", 5.0)))
            lane_hz = max(0.1, float(self.cfg.get("lane", {}).get("update_hz", 5.0)))
            detector_due = self._last_detector_time is None or timestamp - self._last_detector_time >= 1.0 / detector_hz
            lane_due = self._last_lane_time is None or timestamp - self._last_lane_time >= 1.0 / lane_hz
        # The live worker has a bounded latest-frame queue: when both tasks are
        # due, run both instead of capping lane updates at half the input rate.
        lane_run = lane_due and not detector_due
        if self._realtime_schedule:
            lane_run = lane_due
            self._lane_deferred = False
        elif detector_due and lane_due and not (
            self.detector_every_n_frames == 1 and self.lane_every_n_frames == 1
        ):
            self._lane_deferred = True
        elif self._lane_deferred and not detector_due:
            lane_run = True
            self._lane_deferred = False

        if detector_due:
            if self._realtime_schedule and self._last_detector_time is not None:
                self._last_detector_time = max(self._last_detector_time + 1.0 / detector_hz,
                                               timestamp - 1.0 / detector_hz)
            else:
                self._last_detector_time = timestamp
            self.detector_runs += 1
            roi_crop_box = self._compute_roi_crop_box(enhanced)
            if roi_crop_box is not None:
                x1, y1, x2, y2 = roi_crop_box
                cropped = enhanced[y1:y2, x1:x2]
                raw_tracks = self.tracker.track(cropped, frame_idx=frame_idx)
                tracks = [_shift_track(t, roi_crop_box) for t in raw_tracks]
            else:
                tracks = self.tracker.track(enhanced, frame_idx=frame_idx)
            self._last_tracks = tracks
            self.bbox_flow.remember(enhanced)
        else:
            # 検出スキップフレーム: LK で前回 BB を平行移動させる
            tracks = self.bbox_flow.interpolate(self._last_tracks, enhanced)
            self._last_tracks = tracks
        finish_stage("detection_tracking")
        if self.hailo_depth_enabled:
            depth_map = None
            tracks = [replace(track, distance_m=None) for track in tracks]
        elif self.enable_distance:
            depth_map = self.depth.predict(enhanced, frame_idx)
            tracks = [replace(track, distance_m=self.depth.estimate_bbox_distance(track.bbox, enhanced)) for track in tracks]
        else:
            depth_map = None
            tracks = [replace(track, distance_m=None) for track in tracks]
        finish_stage("distance")
        road_mask = self.segmenter.predict(enhanced, frame_idx)
        finish_stage("road_segmentation")
        if self.enable_lanes and lane_run:
            if self._realtime_schedule and self._last_lane_time is not None:
                self._last_lane_time = max(self._last_lane_time + 1.0 / lane_hz,
                                           timestamp - 1.0 / lane_hz)
            else:
                self._last_lane_time = timestamp
            self.lane_runs += 1
            vehicle_boxes_for_lane = [t.bbox for t in tracks if t.cls in {"car", "truck", "bus", "motorcycle"}]
            reference_polygon = self._lane_reference_polygon(enhanced) if self.use_lane_reference_zone else None
            self._last_lanes = self.lane_detector.detect(
                enhanced, road_mask=road_mask, timestamp=timestamp,
                vehicle_bboxes=vehicle_boxes_for_lane, reference_polygon=reference_polygon,
            )
        scene_cfg = self.cfg.get("hailo_scene", {})
        depth_age = timestamp - self._last_ai_depth_time if self._last_ai_depth_time is not None else None
        depth_max_age = float(scene_cfg.get("depth_max_age_s", 1.5))
        lanes = self._last_lanes if self.enable_lanes else empty_lane_info()
        has_detected_lane = bool(
            lanes.ego_lane_polygon is not None
            and self.lane_detector.last_confidence >= self.lane_detector.min_confidence
            and self.lane_detector.is_result_fresh(timestamp)
            )
        display_lanes = lanes if has_detected_lane else empty_lane_info()
        finish_stage("lane_detection")
        signs: list = []
        if self.enable_signs and frame_idx % self.signs_every_n_frames == 0:
            # 車両 BB と重なる「光源候補」（テールランプ等）は信号検出から除外
            vehicle_bboxes = [t.bbox for t in tracks if t.cls in {"car", "truck", "bus", "motorcycle"}]
            _, signals_now = self.sign_detector.detect(enhanced, vehicle_bboxes=vehicle_bboxes)
            self._last_signals = signals_now
        signals = self._last_signals if self.enable_signs else []
        finish_stage("sign_detection")

        # エゴモーション推定（背景フローと消失点を取得）
        ego_state = None
        if self.enable_ego_motion:
            lane_vp = lanes.vanishing_point if lanes is not None else None
            ego_state = self.ego_motion.update(enhanced, road_mask=road_mask, lane_vanishing_point=lane_vp)
            self.speed_source.update(ego_state)
        finish_stage("ego_motion")

        # 台形ゾーンの上頂点 y（奥行き）だけ自動、それ以外は手動スライダー値
        zone_vp = ego_state.vanishing_point if ego_state is not None and ego_state.vanishing_point else (lanes.vanishing_point if lanes else None)
        lane_cfg = self.cfg.get("lane", {})
        manual_offset = {
            "center_x_ratio": float(lane_cfg.get("center_x_ratio", 0.5)),
            "zone_bottom_width_ratio": float(lane_cfg.get("zone_bottom_width_ratio", 0.40)),
            "zone_top_width_ratio": float(lane_cfg.get("zone_top_width_ratio", 0.10)),
            "zone_top_offset_ratio": float(lane_cfg.get("zone_top_offset_ratio", 0.0)),
            "zone_top_y_offset": float(lane_cfg.get("zone_top_y_offset", 0.0)),
            "zone_top_y_ratio": float(lane_cfg.get("zone_top_y_ratio", 0.45)),
            "auto_depth": bool(lane_cfg.get("auto_depth", True)),
        }
        zone_polygon, zone_meta = self.auto_zone.compute(
            height=enhanced.shape[0], width=enhanced.shape[1],
            lanes=lanes, vanishing_point=zone_vp, manual_offset=manual_offset,
        )
        self.zone_meta = {**zone_meta, "polygon": zone_polygon}
        # 自車レーン polygon が未検出のとき auto_zone polygon を使う
        if lanes.ego_lane_polygon is None or self.lane_detector.last_confidence < 0.3:
            lanes = LaneInfo(lanes.left_lane, lanes.right_lane, zone_polygon, lanes.vanishing_point)
        finish_stage("auto_zone")

        # ROI 矩形の可視化用 (display_size 座標系に upscale して meta に格納)
        roi_rect_box_render = None
        if self.roi_mode == "rectangle":
            rb = self._roi_box_from_rect(enhanced)
            roi_rect_box_render = rb  # まず process 座標
        # ---- 描画用キャンバスの準備 ----
        # 動画ピクセル自体は **処理解像度のまま** (上にリサイズして拡大すると元の精細さは戻らない)
        # ただし overlays (枠/矢印/文字) は display_size のサイズで描画して高画質にする
        if display_size is not None and display_size[0] != frame.shape[1]:
            disp_w, disp_h = display_size
            upscale = disp_w / frame.shape[1]
            canvas = cv2.resize(enhanced, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
            render_tracks = [_scale_track_xy(t, upscale) for t in tracks]
            render_lanes = _scale_lane_info(display_lanes, upscale)
            render_road_mask = cv2.resize(road_mask, (disp_w, disp_h), interpolation=cv2.INTER_NEAREST) if road_mask is not None else None
            if roi_rect_box_render is not None:
                rx1, ry1, rx2, ry2 = roi_rect_box_render
                roi_rect_box_render = (int(rx1 * upscale), int(ry1 * upscale), int(rx2 * upscale), int(ry2 * upscale))
        else:
            render_tracks = tracks
            render_lanes = display_lanes
            render_road_mask = road_mask
            canvas = enhanced

        ctx = SceneContext(
            frame_idx=frame_idx,
            timestamp=timestamp,
            image=canvas,
            enhanced=canvas,
            detections=[],
            tracks=render_tracks,
            road_mask=render_road_mask,
            lanes=render_lanes,
            depth_map=depth_map,
            signs=signs,
            signals=signals,
            ego_motion=ego_state,
        )
        # 解析は処理サイズ (frame) ベースで行う（誤判定回避のため）
        analysis_ctx = SceneContext(
            frame_idx=frame_idx, timestamp=timestamp, image=frame, enhanced=enhanced,
            detections=[], tracks=tracks, road_mask=road_mask, lanes=lanes,
            depth_map=depth_map, signs=signs, signals=signals, ego_motion=ego_state,
        )
        self.risk._current_fps = fps
        depth_fresh = (self.hailo_depth_enabled and depth_age is not None and
                       0 <= depth_age <= depth_max_age and not self._ai_depth_error
                       and self.hailo_scene.depth_values is not None)
        depth_started = time.perf_counter()
        if self.hailo_depth_enabled and self.enable_risk and depth_fresh:
            hz = max(.1, float(scene_cfg.get("depth_update_hz", 1.0)))
            ai_alerts = self.depth_risk.analyze(
                analysis_ctx, self.hailo_scene.depth_values, updated=depth_updated,
                max_age=depth_max_age, interval=1.0/hz,
            )
        else:
            ai_alerts = []
            status = ("OFF" if not self.hailo_depth_enabled else "危険判定OFF" if not self.enable_risk
                      else "奥行き取得不可・判定困難" if self._ai_depth_error else "奥行き更新待ち")
            self.depth_risk.invalidate(status)
        depth_analysis_ms = (time.perf_counter()-depth_started)*1000
        depth_trends = self.depth_risk.vehicle_depth_trends(analysis_ctx, depth_max_age) if depth_fresh and self.enable_risk else {}
        alerts = self.risk.analyze(analysis_ctx, depth_trends=depth_trends) if self.enable_risk else []
        alerts = fuse_depth_alerts(alerts, ai_alerts)
        regions = self.depth_risk.diagnostics
        fronts = [r for r in regions if r["known"] and r["path_overlap"] >= .5]
        ai_front_id = max(fronts, key=lambda r: r["relative_near"])["target_id"] if fronts else None
        if self.enable_lanes and self.enable_risk:
            ldw = self.lane_detector.analyze_ldw(lanes, frame.shape[1], timestamp=timestamp)
            if ldw is not None:
                alerts.append(ldw)
        active_alerts = self.alert_manager.update(alerts, timestamp, {t.track_id for t in tracks})
        active_alerts = fuse_depth_alerts(
            [a for a in active_alerts if not a.kind.startswith("ai_depth_")],
            [a for a in active_alerts if a.kind.startswith("ai_depth_")],
        )
        finish_stage("risk_analysis")
        meta = {
            "frame_idx": frame_idx,
            "timestamp": timestamp,
            "fps": fps,
            "process_ms": (time.perf_counter() - start) * 1000,
            "stage_ms": stage_ms,
            "alerts": active_alerts,
            "emitted_alerts": self.alert_manager.last_emitted,
            "tracks": render_tracks,
            "device": getattr(self.tracker, "detector_device", self.device),
            "detector_enabled": bool(getattr(self.tracker, "enabled", True)),
            "detector_runs": self.detector_runs,
            "lane_runs": self.lane_runs,
            "enhancement": enhancement_meta,
            "show_debug_mask": self.show_debug_mask,
            "ego_motion": ego_state,
            "lane_state": self.lane_detector.state,
            "lane_confidence": self.lane_detector.last_confidence,
            "lane_detected": has_detected_lane,
            "lane_ldw_ready": self.lane_detector.ldw_ready,
            "lane_reference_score": getattr(self.lane_detector.ipm, "last_reference_score", 1.0),
            "track_labels": getattr(self.risk, "last_labels", {}),
            "roi_rect_box": roi_rect_box_render,
            **self.zone_meta,
        }
        backend = getattr(self.tracker, "_external", None)
        if self.hailo_scene:
            meta["ai_depth_age_s"] = depth_age
            meta["ai_depth_error"] = self._ai_depth_error
            meta["ai_front_target"] = ai_front_id
            meta["hailo_depth_ms"] = self.hailo_scene.depth_ms
        meta["show_ai_depth_preview"] = bool(self.cfg.get("ui", {}).get("show_ai_depth_preview", False))
        meta["ai_depth_values"] = self.hailo_scene.depth_values if depth_fresh and meta["show_ai_depth_preview"] else None
        meta["ai_depth_status"] = self.depth_risk.status
        meta["ai_depth_analysis_ms"] = depth_analysis_ms
        render_scale = canvas.shape[1]/enhanced.shape[1]
        meta["ai_depth_regions"] = [dict(r, bbox=tuple(v*render_scale for v in r["bbox"])) for r in regions]
        meta["risk_mode"] = "ai_depth_fusion" if self.hailo_depth_enabled else "legacy"
        if getattr(self.tracker, "detector_device", self.device) == "Hailo-8":
            meta["detector_model"] = str(getattr(self.tracker, "weights", "")).rsplit("/", 1)[-1]
            meta["hailo_hw_ms"] = getattr(backend, "last_hw_time_ms", None)
        # カメラ異常検知 (時間条件 + 画質条件の AND)
        blind = False
        blind_reason = None
        if self.enable_blind_check:
            blind, blind_reason = self.blind_detector.update(
                frame, has_detections=len(tracks) > 0, timestamp=timestamp,
            )
        meta["blind"] = blind
        meta["blind_reason"] = blind_reason
        finish_stage("blind_check")
        if not render:
            meta["_render_context"] = ctx
        rendered = self.renderer.render(ctx, active_alerts, meta) if render else canvas
        finish_stage("render")
        meta["process_ms"] = (time.perf_counter() - start) * 1000
        return rendered, meta

    def _lane_reference_polygon(self, frame: np.ndarray) -> np.ndarray:
        """Use the user-adjusted red trapezoid as a soft ego-lane prior."""
        lane_cfg = self.cfg.get("lane", {})
        return fallback_ego_lane_polygon(
            frame.shape[1], frame.shape[0],
            float(lane_cfg.get("center_x_ratio", 0.5)),
            float(lane_cfg.get("zone_top_y_ratio", 0.45)),
            float(lane_cfg.get("zone_bottom_width_ratio", 0.40)),
            float(lane_cfg.get("zone_top_width_ratio", 0.10)),
            float(lane_cfg.get("zone_top_offset_ratio", 0.0)),
        )

    def _compute_roi_crop_box(self, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        """ROI モードに従って crop 矩形 (x1,y1,x2,y2) を返す。OFF なら None。"""
        if self.roi_mode == "trapezoid":
            return self._roi_box_from_trapezoid(frame)
        if self.roi_mode == "rectangle":
            return self._roi_box_from_rect(frame)
        return None

    def _roi_box_from_trapezoid(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        """台形ゾーン (車線推定で更新される) の bounding rect。未確定時は画面下 65%×中央 90%。"""
        h, w = frame.shape[:2]
        polygon = self.zone_meta.get("polygon") if isinstance(self.zone_meta, dict) else None
        if polygon is not None and len(polygon) >= 3:
            pts = np.asarray(polygon).reshape(-1, 2)
            x1 = int(max(0, pts[:, 0].min() - 20))
            x2 = int(min(w, pts[:, 0].max() + 20))
            y1 = int(max(0, pts[:, 1].min() - 30))
            y2 = int(min(h, pts[:, 1].max() + 20))
        else:
            x1, y1 = int(w * 0.05), int(h * 0.35)
            x2, y2 = int(w * 0.95), h
        if x2 - x1 < 64 or y2 - y1 < 64:
            return (0, 0, w, h)
        return (x1, y1, x2, y2)

    def _roi_box_from_rect(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        """ユーザー指定の長方形 (比率) から crop box を計算。"""
        h, w = frame.shape[:2]
        x_r = float(np.clip(self.roi_rect["x_ratio"], 0.0, 0.95))
        y_r = float(np.clip(self.roi_rect["y_ratio"], 0.0, 0.95))
        w_r = float(np.clip(self.roi_rect["w_ratio"], 0.05, 1.0))
        h_r = float(np.clip(self.roi_rect["h_ratio"], 0.05, 1.0))
        x1 = int(w * x_r)
        y1 = int(h * y_r)
        x2 = int(min(w, x1 + w * w_r))
        y2 = int(min(h, y1 + h * h_r))
        if x2 - x1 < 64 or y2 - y1 < 64:
            return (0, 0, w, h)
        return (x1, y1, x2, y2)


def _sample_ai_depth(values, tracks, shape):
    if values is None or values.ndim != 2:
        return {}
    h, w = shape[:2]
    dh, dw = values.shape
    scores = {}
    for track in tracks:
        x1, y1, x2, y2 = track.bbox
        # Inset box to reduce contamination from surrounding road/background.
        xa, xb = int((x1 + (x2-x1)*0.2) * dw / w), int((x2 - (x2-x1)*0.2) * dw / w)
        ya, yb = int((y1 + (y2-y1)*0.2) * dh / h), int((y2 - (y2-y1)*0.2) * dh / h)
        xa, xb = max(0, xa), min(dw, xb)
        ya, yb = max(0, ya), min(dh, yb)
        if xb <= xa or yb <= ya:
            continue
        patch = values[ya:yb, xa:xb]
        if patch.size >= 9 and np.isfinite(patch).all():
            scores[track.track_id] = (float(np.median(patch)), tuple(track.bbox))
    return scores


def _bbox_matches(old, new):
    x1, y1 = max(old[0], new[0]), max(old[1], new[1])
    x2, y2 = min(old[2], new[2]), min(old[3], new[3])
    intersection = max(0, x2-x1) * max(0, y2-y1)
    area1 = max(0, old[2]-old[0]) * max(0, old[3]-old[1])
    area2 = max(0, new[2]-new[0]) * max(0, new[3]-new[1])
    union = area1 + area2 - intersection
    return union > 0 and intersection / union >= 0.7


def _scale_track_xy(track, scale: float):
    """track の bbox と history を scale 倍する（描画用、解析には影響させない）。"""
    from collections import deque
    from dataclasses import replace
    x1, y1, x2, y2 = track.bbox
    new_bbox = (x1 * scale, y1 * scale, x2 * scale, y2 * scale)
    new_history = deque(((px * scale, py * scale) for px, py in track.history), maxlen=track.history.maxlen)
    # velocity も px/frame 単位なのでスケール
    vx, vy = track.velocity
    return replace(track, bbox=new_bbox, history=new_history, velocity=(vx * scale, vy * scale))


def _scale_lane_info(lanes: LaneInfo, scale: float) -> LaneInfo:
    def _scale(arr):
        return (arr.astype(np.float32) * scale).astype(np.int32) if arr is not None else None
    vp = lanes.vanishing_point
    new_vp = (int(vp[0] * scale), int(vp[1] * scale)) if vp is not None else None
    return LaneInfo(
        left_lane=_scale(lanes.left_lane),
        right_lane=_scale(lanes.right_lane),
        ego_lane_polygon=_scale(lanes.ego_lane_polygon),
        vanishing_point=new_vp,
    )


def _shift_track(track, crop_box: tuple[int, int, int, int]):
    """ROI crop 上の track BB を元画像座標に戻す。"""
    x_off, y_off, _, _ = crop_box
    x1, y1, x2, y2 = track.bbox
    new_bbox = (x1 + x_off, y1 + y_off, x2 + x_off, y2 + y_off)
    # history も同じシフト
    from collections import deque
    new_history = deque(((px + x_off, py + y_off) for px, py in track.history), maxlen=track.history.maxlen)
    from dataclasses import replace
    return replace(track, bbox=new_bbox, history=new_history)


def empty_lane_info() -> LaneInfo:
    return LaneInfo(None, None, None, None)
