from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from loguru import logger

from src.types import Detection
from src.utils.config import resolve_device


COCO_NAME = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


class YoloDetector:
    def __init__(
        self,
        weights: str = "yolo11n.pt",
        device: str = "auto",
        conf: float = 0.35,
        iou: float = 0.5,
        imgsz: int = 640,
        max_det: int = 100,
        classes: list[int] | None = None,
        enabled: bool = True,
    ):
        self.weights = weights
        self.device = _resolve_detector_device(device, weights)
        self.conf = conf
        self.iou = iou
        self.imgsz = imgsz
        self.max_det = max_det
        self.classes = classes or list(COCO_NAME)
        self.enabled = enabled
        self._model = None
        self._failed = False

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if not self.enabled or self._failed:
            return []
        model = self._load_model()
        if model is None:
            return []
        try:
            result = model.predict(
                frame,
                device=self.device,
                conf=self.conf,
                iou=self.iou,
                imgsz=self.imgsz,
                max_det=self.max_det,
                classes=self.classes,
                verbose=False,
            )[0]
        except Exception as exc:
            if self.device != "cpu":
                logger.warning("YOLO failed on {}; retrying on cpu: {}", self.device, exc)
                self.device = "cpu"
                return self.detect(frame)
            logger.warning("YOLO detection disabled after failure: {}", exc)
            self._failed = True
            return []
        out: list[Detection] = []
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            out.append(Detection((x1, y1, x2, y2), COCO_NAME.get(cls_id, result.names.get(cls_id, str(cls_id))), conf))
        return out

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            _configure_ultralytics_dir()
            from ultralytics import YOLO

            self._model = YOLO(self.weights)
        except Exception as exc:
            logger.warning("YOLO model could not be loaded: {}", exc)
            self._failed = True
            return None
        return self._model


def _is_tflite(weights: str) -> bool:
    return str(weights).lower().endswith(".tflite")


def _resolve_detector_device(device: str | None, weights: str) -> str:
    # TFLite (INT8 CPU / Edge TPU 版とも) は MPS 非対応。Ultralytics は edgetpu の
    # ファイル名から TPU delegate を自動選択するので、ここでは MPS を CPU に落とすだけでよい。
    if _is_tflite(weights):
        resolved = resolve_device(device)
        return "cpu" if resolved == "mps" else resolved
    return resolve_device(device)


def _configure_ultralytics_dir() -> None:
    path = Path("outputs/ultralytics")
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(path.resolve()))
