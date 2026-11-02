from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from loguru import logger

from src.detection.external_detector import ExternalDetectorBase, make_external_detector
from src.detection.yolo_detector import COCO_NAME, YoloDetector
from src.detection.yolo_detector import _configure_ultralytics_dir, _resolve_detector_device
from src.detection.fallback_detector import FallbackVehicleDetector
from src.detection.hailo_detector import HailoDetector
from src.types import Detection, TrackedObject


class YoloTracker:
    # クラス別の最小 conf。検出後フィルタで適用する
    DEFAULT_CONF_PER_CLASS = {
        "person": 0.18,
        "bicycle": 0.15,     # 自転車は遠方でも検出するため最も低く
        "motorcycle": 0.25,
        "car": 0.30,
        "bus": 0.30,
        "truck": 0.30,
    }

    def __init__(
        self,
        weights: str = "yolo11n.pt",
        device: str = "auto",
        conf: float = 0.18,
        iou: float = 0.5,
        imgsz: int = 640,
        max_det: int = 100,
        classes: list[int] | None = None,
        enabled: bool = True,
        fallback_enabled: bool = True,
        conf_per_class: dict | None = None,
        shared_networks=None,
    ):
        self.shared_networks = shared_networks
        self.weights = weights
        self._device_pref = device
        self.device = _resolve_detector_device(device, weights)
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.max_det = max_det
        self.classes = classes or list(COCO_NAME)
        self.enabled = enabled
        self.detector = YoloDetector(weights, device, conf, iou, imgsz, max_det, classes, enabled)
        self.fallback_enabled = fallback_enabled
        self.fallback_detector = FallbackVehicleDetector()
        self.conf_per_class = conf_per_class or dict(self.DEFAULT_CONF_PER_CLASS)
        self._model = None
        self._failed = False
        self._history: dict[int, deque[tuple[float, float]]] = {}
        self._timestamps: dict[int, deque[int]] = {}
        self._age: dict[int, int] = {}
        self._hits: dict[int, int] = {}
        self._last_bbox: dict[int, tuple[float, float, float, float]] = {}
        self._track_classes: dict[int, str] = {}
        self._last_velocity: dict[int, tuple[float, float]] = {}
        self._last_match_quality: dict[int, float] = {}
        self._last_frame_idx = -1
        self._call_frame_idx = 0
        self._next_id = 1
        self._tracker_yaml_cache: tuple[float, Path] | None = None
        # 外部 detector (YOLOX/NanoDet/EfficientDet): 拡張子が .onnx/.tflite の時のみ
        self._external: ExternalDetectorBase | HailoDetector | None = self._make_detector(weights)

    def _make_detector(self, weights: str):
        if str(weights).lower().endswith(".hef"):
            return HailoDetector(weights, self.shared_networks)
        return make_external_detector(weights, device=self._device_pref)

    def close(self) -> None:
        if isinstance(self._external, HailoDetector):
            self._external.close()

    @property
    def detector_device(self) -> str:
        return "Hailo-8" if isinstance(self._external, HailoDetector) else self.device

    def track(self, frame: np.ndarray, frame_idx: int | None = None) -> list[TrackedObject]:
        if not self.enabled:
            return []
        if frame_idx is None:
            self._call_frame_idx += 1
            frame_idx = self._call_frame_idx
        else:
            self._call_frame_idx = max(self._call_frame_idx, frame_idx)
        # 外部モデル (YOLOX / NanoDet / EfficientDet) は detect → 単純トラッキング
        if self._external is not None:
            if isinstance(self._external, HailoDetector):
                detections = self._external.detect(
                    frame, self._effective_model_conf(), self.iou, self.classes, self.max_det
                )
            else:
                detections = self._external.detect(frame)
            detections = self._apply_class_conf(detections)
            return self._simple_match(detections, frame_idx)
        if not self._failed:
            return self._track_with_yolo(frame)
        # YOLO がロード/推論失敗時のみ、軽量フォールバックでUIに何か出す
        if self.fallback_enabled:
            detections = self.fallback_detector.detect(frame)
            return self._simple_match(detections, frame_idx)
        return []

    def _apply_class_conf(self, detections: list[Detection]) -> list[Detection]:
        """conf_per_class でクラス別に再フィルタ。"""
        out = []
        for d in detections:
            if d.conf >= self.conf_per_class.get(d.cls, self.conf):
                out.append(d)
        return out

    def _track_with_yolo(self, frame: np.ndarray) -> list[TrackedObject]:
        model = self._load_model()
        if model is None:
            return []
        try:
            result = model.track(
                frame,
                persist=True,
                tracker=self._tracker_yaml(),
                device=self.device,
                conf=self._effective_model_conf(),
                iou=self.iou,
                imgsz=self.imgsz,
                max_det=self.max_det,
                classes=self.classes,
                verbose=False,
            )[0]
        except Exception as exc:
            if self.device != "cpu":
                logger.warning("ByteTrack failed on {}; retrying on cpu: {}", self.device, exc)
                self.device = "cpu"
                return self._track_with_yolo(frame)
            logger.warning("ByteTrack disabled after failure: {}", exc)
            self._failed = True
            return []
        if result.boxes.id is None:
            return []
        out: list[TrackedObject] = []
        seen: set[int] = set()
        for box in result.boxes:
            track_id = int(box.id[0])
            cls_id = int(box.cls[0])
            cls_name = result.names.get(cls_id, str(cls_id))
            conf = float(box.conf[0])
            # クラス別の conf 閾値で再フィルタ
            min_conf = self.conf_per_class.get(cls_name, self.conf)
            if conf < min_conf:
                continue
            seen.add(track_id)
            self._track_classes[track_id] = cls_name
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            hist = self._append_history(track_id, x1, y1, x2, y2, self._call_frame_idx)
            velocity = self._velocity(track_id)
            out.append(
                TrackedObject(
                    track_id=track_id,
                    bbox=(x1, y1, x2, y2),
                    cls=cls_name,
                    conf=conf,
                    velocity=velocity,
                    history=hist,
                    age=self._age[track_id],
                    distance_m=None,
                    confirmed=self._age[track_id] >= 2,
                    motion_valid=self._age[track_id] >= 2 and np.hypot(*velocity) < 35.0,
                    match_quality=1.0,
                )
            )
        self._forget_missing(seen)
        return out

    def _simple_match(self, detections: list[Detection], frame_idx: int) -> list[TrackedObject]:
        out: list[TrackedObject] = []
        seen: set[int] = set()
        candidates: list[tuple[float, int, int, float]] = []
        for det_idx, det in enumerate(detections):
            cx, cy = _center(det.bbox)
            for track_id, previous_bbox in self._last_bbox.items():
                if track_id in seen or not self._compatible_class(det.cls, self._class_by_track(track_id)):
                    continue
                last_frame = self._timestamps.get(track_id, deque([frame_idx - 1]))[-1]
                gap = max(1, frame_idx - last_frame)
                prev_center = _center(previous_bbox)
                velocity = self._last_velocity.get(track_id, (0.0, 0.0))
                predicted = (prev_center[0] + velocity[0] * gap, prev_center[1] + velocity[1] * gap)
                distance = float(np.hypot(cx - predicted[0], cy - predicted[1]))
                iou = self._bbox_iou(det.bbox, previous_bbox)
                max_distance = max(45.0, 2.0 * np.hypot(previous_bbox[2] - previous_bbox[0], previous_bbox[3] - previous_bbox[1]))
                max_distance += min(80.0, float(np.hypot(*velocity)) * gap * 1.5)
                if distance > max_distance and iou < 0.05:
                    continue
                area = max(1.0, (previous_bbox[2] - previous_bbox[0]) * (previous_bbox[3] - previous_bbox[1]))
                new_area = max(1.0, (det.bbox[2] - det.bbox[0]) * (det.bbox[3] - det.bbox[1]))
                if max(area, new_area) / min(area, new_area) > 4.0 and iou < 0.15:
                    continue
                cost = distance / max(max_distance, 1.0) + (1.0 - iou) * 0.5
                candidates.append((cost, det_idx, track_id, iou))
        assignments: dict[int, tuple[int, float]] = {}
        used_dets: set[int] = set()
        for cost, det_idx, track_id, iou in sorted(candidates):
            if det_idx in used_dets or track_id in seen:
                continue
            assignments[det_idx] = (track_id, float(np.clip(1.0 - cost, 0.0, 1.0)))
            used_dets.add(det_idx)
            seen.add(track_id)

        for det_idx, det in enumerate(detections):
            assignment = assignments.get(det_idx)
            if assignment is None:
                track_id = self._next_id
                self._next_id += 1
                match_quality = 0.0
            else:
                track_id, match_quality = assignment
            seen.add(track_id)
            self._track_classes[track_id] = det.cls
            x1, y1, x2, y2 = det.bbox
            hist = self._append_history(track_id, x1, y1, x2, y2, frame_idx)
            velocity = self._velocity(track_id)
            self._last_bbox[track_id] = det.bbox
            self._last_velocity[track_id] = velocity
            self._last_match_quality[track_id] = match_quality
            hits = self._hits[track_id]
            confirmed = hits >= 2
            out.append(TrackedObject(
                track_id, det.bbox, det.cls, det.conf, velocity, hist, self._age[track_id], None,
                confirmed=confirmed,
                motion_valid=confirmed and match_quality >= 0.35 and np.hypot(*velocity) < 35.0,
                match_quality=match_quality,
            ))
        self._last_frame_idx = frame_idx
        self._forget_missing(seen)
        return out

    def _append_history(self, track_id: int, x1: float, y1: float, x2: float, y2: float, frame_idx: int) -> deque[tuple[float, float]]:
        hist = self._history.setdefault(track_id, deque(maxlen=30))
        timestamps = self._timestamps.setdefault(track_id, deque(maxlen=30))
        hist.append(((x1 + x2) / 2, (y1 + y2) / 2))
        timestamps.append(frame_idx)
        self._age[track_id] = self._age.get(track_id, 0) + 1
        self._hits[track_id] = self._hits.get(track_id, 0) + 1
        return hist

    def _forget_missing(self, seen: set[int]) -> None:
        for track_id in list(self._history):
            if track_id not in seen:
                self._age[track_id] = max(0, self._age.get(track_id, 0) - 1)
                if self._age[track_id] == 0:
                    self._history.pop(track_id, None)
                    self._timestamps.pop(track_id, None)
                    self._hits.pop(track_id, None)
                    self._last_bbox.pop(track_id, None)
                    self._last_velocity.pop(track_id, None)
                    self._last_match_quality.pop(track_id, None)
                    self._track_classes.pop(track_id, None)
                    self._age.pop(track_id, None)

    def _velocity(self, track_id: int) -> tuple[float, float]:
        hist = self._history[track_id]
        timestamps = self._timestamps[track_id]
        if len(hist) < 2 or len(timestamps) != len(hist):
            return (0.0, 0.0)
        pts = np.array(list(hist)[-5:], dtype=np.float32)
        t = np.asarray(list(timestamps)[-len(pts):], dtype=np.float32)
        if t[-1] <= t[0]:
            return (0.0, 0.0)
        current = (
            float(np.polyfit(t, pts[:, 0], 1)[0]),
            float(np.polyfit(t, pts[:, 1], 1)[0]),
        )
        previous = self._last_velocity.get(track_id, current)
        return (
            0.65 * previous[0] + 0.35 * current[0],
            0.65 * previous[1] + 0.35 * current[1],
        )

    def _class_by_track(self, track_id: int) -> str | None:
        return getattr(self, "_track_classes", {}).get(track_id)

    @staticmethod
    def _compatible_class(current: str, previous: str | None) -> bool:
        if previous is None or current == previous:
            return True
        vehicles = {"car", "truck", "bus", "motorcycle", "candidate"}
        return current in vehicles and previous in vehicles

    @staticmethod
    def _bbox_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = max(1.0, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)
        return inter / union

    def set_weights(self, weights: str) -> None:
        """重みファイル差し替え。次の track 呼び出しで再ロードされる。"""
        if weights == self.weights:
            return
        self.close()
        self.weights = weights
        self.detector.weights = weights
        # .tflite へ切替時は MPS を CPU に落とす (Edge TPU/INT8 とも MPS 非対応)
        self.device = _resolve_detector_device(self._device_pref, weights)
        self.detector.device = _resolve_detector_device(self._device_pref, weights)
        self._model = None
        self.detector._model = None
        self._failed = False
        self.detector._failed = False
        self._history.clear()
        self._timestamps.clear()
        self._age.clear()
        self._hits.clear()
        self._last_bbox.clear()
        self._last_velocity.clear()
        self._last_match_quality.clear()
        self._track_classes.clear()
        self._age.clear()
        # 外部 detector も差し替え（YOLO11 系に戻したら None になる）
        self._external = self._make_detector(weights)

    def _effective_model_conf(self) -> float:
        """YOLO/ByteTrack の入口に渡す conf。

        クラス別 conf は後段で再フィルタするが、入口の conf が高いと
        person=0.10 のような設定が ByteTrack に届く前に落ちてしまう。
        """
        values = [float(self.conf)]
        if isinstance(self.conf_per_class, dict):
            for value in self.conf_per_class.values():
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
        return max(0.01, min(values))

    def _tracker_yaml(self) -> str:
        threshold = self._effective_model_conf()
        cached = self._tracker_yaml_cache
        if cached is not None and abs(cached[0] - threshold) < 1e-6 and cached[1].exists():
            return str(cached[1])

        path = Path("outputs/ultralytics/bytetrack_sensitive.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep ByteTrack's association behavior close to the Ultralytics default,
        # but let low-confidence pedestrian candidates start a track.
        track_low = min(0.10, threshold)
        payload = (
            "tracker_type: bytetrack\n"
            f"track_high_thresh: {threshold:.4f}\n"
            f"track_low_thresh: {track_low:.4f}\n"
            f"new_track_thresh: {threshold:.4f}\n"
            "track_buffer: 30\n"
            "match_thresh: 0.8\n"
            "fuse_score: true\n"
        )
        path.write_text(payload, encoding="utf-8")
        self._tracker_yaml_cache = (threshold, path)
        return str(path)

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            _configure_ultralytics_dir()
            from ultralytics import YOLO

            self._model = YOLO(self.weights)
        except Exception as exc:
            logger.warning("YOLO tracker model could not be loaded: {}", exc)
            self._failed = True
            return None
        return self._model


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2, (y1 + y2) / 2
