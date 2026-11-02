"""Hailo-8 YOLOv8 and YOLO26 HEF detectors used by the AI HAT+ profile."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from src.types import Detection


COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

def decode_yolo26(outputs: dict, width: int, height: int) -> list[tuple[int, float, float, float, float, float]]:
    """Decode Hailo Model Zoo v2.18 YOLO26 raw heads using one-to-one top-k selection."""
    boxes_by_size, scores_by_size = {}, {}
    for output in outputs.values():
        array = np.asarray(output)
        if array.ndim != 4 or array.shape[0] != 1:
            raise ValueError(f"YOLO26の出力形状が不正です: {array.shape}")
        key = array.shape[1:3]
        target = boxes_by_size if array.shape[-1] == 4 else scores_by_size if array.shape[-1] == 80 else None
        if target is None or key in target:
            raise ValueError(f"YOLO26の出力が不正または重複しています: {array.shape}")
        target[key] = array[0]
    expected = {(height // stride, width // stride) for stride in (8, 16, 32)}
    if set(boxes_by_size) != expected or set(scores_by_size) != expected:
        raise ValueError("YOLO26の出力ヘッドが3組ありません")
    all_boxes, all_scores, all_classes = [], [], []
    for (h, w), box in sorted(boxes_by_size.items(), reverse=True):
        logits = scores_by_size[(h, w)].reshape(-1, 80)
        class_ids = np.argmax(logits, axis=1)
        max_logits = logits[np.arange(len(logits)), class_ids]
        scores = 1.0 / (1.0 + np.exp(-np.clip(max_logits, -80, 80)))
        yy, xx = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
        reg = box.reshape(-1, 4)
        cx, cy = xx.reshape(-1) + 0.5, yy.reshape(-1) + 0.5
        decoded = np.column_stack(((cy - reg[:, 1]) / h, (cx - reg[:, 0]) / w,
                                   (cy + reg[:, 3]) / h, (cx + reg[:, 2]) / w))
        all_boxes.append(decoded)
        all_scores.append(scores)
        all_classes.append(class_ids)
    boxes = np.concatenate(all_boxes)
    scores = np.concatenate(all_scores)
    classes = np.concatenate(all_classes)
    top = np.argsort(scores)[::-1][:300]
    return [(int(classes[i]), *map(float, boxes[i]), float(scores[i])) for i in top]


class HailoDetector:
    """Run one RGB image at a time using HailoRT."""

    def __init__(self, weights: str, shared_networks=None):
        self.weights = weights
        self.shared_networks = shared_networks
        self._stack: ExitStack | None = None
        self._infer = None
        self._thresholds: tuple[float, float] | None = None
        self.last_hw_time_ms: float | None = None
        self.inference_count = 0

    def _open(self) -> None:
        if self._infer is not None:
            return
        path = Path(self.weights)
        if not path.is_file():
            raise RuntimeError(f"AI HAT+のモデルが見つかりません: {path}")
        stack = ExitStack()
        try:
            from hailo_platform import (
                ConfigureParams, FormatType, HailoStreamInterface, HEF,
                InferVStreams, InputVStreamParams, OutputVStreamParams, VDevice,
            )
            hef = HEF(str(path))
            inputs = hef.get_input_vstream_infos()
            outputs = hef.get_output_vstream_infos()
            self._is_yolo26 = path.stem.lower() in {"yolo26n", "yolo26s", "yolo26m"}
            if len(inputs) != 1 or len(outputs) != (6 if self._is_yolo26 else 1) or len(inputs[0].shape) != 3:
                raise ValueError("対応するYOLOモデルの入出力ではありません")
            self._height, self._width, channels = inputs[0].shape
            if channels != 3:
                raise ValueError("3チャンネルの入力が必要です")
            self._input_name = inputs[0].name
            self._output_name = outputs[0].name if not self._is_yolo26 else None
            if self.shared_networks is not None:
                hef, infer = self.shared_networks.open(str(path))
            else:
                device = stack.enter_context(VDevice())
                params = ConfigureParams.create_from_hef(hef, HailoStreamInterface.PCIe)
                group = device.configure(hef, params)[0]
                input_params = InputVStreamParams.make(group, format_type=FormatType.UINT8)
                output_params = OutputVStreamParams.make(group, format_type=FormatType.FLOAT32)
                infer = stack.enter_context(InferVStreams(group, input_params, output_params))
                stack.enter_context(group.activate())
            self._infer, self._stack = infer, stack
            logger.info("AI HAT+ Hailo-8 detector loaded: {}", path)
        except Exception as exc:
            stack.close()
            raise RuntimeError(f"AI HAT+の初期化に失敗しました: {exc}") from exc

    def detect(self, frame: np.ndarray, conf: float, iou: float,
               classes: list[int], max_det: int) -> list[Detection]:
        self._open()
        try:
            thresholds = (max(0.01, min(float(conf), 1.0)), max(0.01, min(float(iou), 1.0)))
            if not self._is_yolo26 and thresholds != self._thresholds:
                self._infer.set_nms_score_threshold(thresholds[0])
                self._infer.set_nms_iou_threshold(thresholds[1])
                self._thresholds = thresholds
            h, w = frame.shape[:2]
            scale = min(self._width / w, self._height / h)
            nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
            xpad, ypad = (self._width - nw) // 2, (self._height - nh) // 2
            image = np.full((self._height, self._width, 3), 114, dtype=np.uint8)
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
            image[ypad:ypad + nh, xpad:xpad + nw] = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            outputs = self._infer.infer({self._input_name: image[None]})
            self.last_hw_time_ms = self._infer.get_hw_time() * 1000.0
            self.inference_count += 1
            if self._is_yolo26:
                rows = decode_yolo26(outputs, self._width, self._height)
            else:
                output = outputs[self._output_name]
                if len(output) != 1:
                    raise ValueError("Hailo出力のバッチ数が1ではありません")
                rows = [(cls_id, *map(float, box[:5]))
                        for cls_id, boxes in enumerate(output[0]) for box in boxes]
            detections = []
            for cls_id, ymin, xmin, ymax, xmax, score in rows:
                if cls_id not in classes or cls_id not in COCO_NAMES:
                    continue
                if not np.isfinite([ymin, xmin, ymax, xmax, score]).all() or score < thresholds[0]:
                    continue
                x1 = float(np.clip((xmin * self._width - xpad) * w / nw, 0, w))
                x2 = float(np.clip((xmax * self._width - xpad) * w / nw, 0, w))
                y1 = float(np.clip((ymin * self._height - ypad) * h / nh, 0, h))
                y2 = float(np.clip((ymax * self._height - ypad) * h / nh, 0, h))
                if x2 > x1 and y2 > y1:
                    detections.append(Detection((x1, y1, x2, y2), COCO_NAMES[cls_id], score))
            detections.sort(key=lambda detection: detection.conf, reverse=True)
            return detections[:max_det]
        except Exception as exc:
            self.close()
            raise RuntimeError(f"AI HAT+の推論に失敗しました: {exc}") from exc

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
        self._stack = None
        self._infer = None
        self._thresholds = None
