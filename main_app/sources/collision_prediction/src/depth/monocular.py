from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from loguru import logger
from PIL import Image

from src.depth.ipm_fallback import IPMFallbackDepth


class MonocularDepthEstimator:
    def __init__(self, model: str, every_n_frames: int = 2, cam_height_m: float = 1.2, enabled: bool = True, device: str = "cpu"):
        self.model_name = model
        self.every_n_frames = max(1, every_n_frames)
        self.enabled = enabled
        self.device = device
        self.fallback = IPMFallbackDepth(cam_height_m)
        self._last_depth: np.ndarray | None = None
        self._processor = None
        self._model = None
        self._failed = False

    def predict(self, frame: np.ndarray, frame_idx: int) -> np.ndarray:
        if self._last_depth is not None and frame_idx % self.every_n_frames != 0:
            return self._last_depth
        self._last_depth = self._model_depth(frame) if self.enabled else self.fallback.dense_depth(frame)
        return self._last_depth

    def estimate_bbox_distance(self, bbox: tuple[float, float, float, float], frame: np.ndarray) -> float:
        if self._last_depth is not None:
            x1, y1, x2, y2 = map(int, bbox)
            h, w = self._last_depth.shape[:2]
            x1 = int(np.clip(x1, 0, w - 1))
            x2 = int(np.clip(x2, x1 + 1, w))
            y1 = int(np.clip(y1, 0, h - 1))
            y2 = int(np.clip(y2, y1 + 1, h))
            patch = self._last_depth[y1:y2, x1:x2]
            if patch.size:
                return float(np.clip(np.median(patch), 1.0, 120.0))
        return self.fallback.estimate_distance(bbox, frame.shape)

    def _model_depth(self, frame: np.ndarray) -> np.ndarray:
        if self._failed:
            return self.fallback.dense_depth(frame)
        if not self._load_model():
            return self.fallback.dense_depth(frame)
        try:
            rgb = frame[:, :, ::-1]
            image = Image.fromarray(rgb)
            inputs = self._processor(images=image, return_tensors="pt")
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with torch.no_grad():
                predicted_depth = self._model(**inputs).predicted_depth
            depth = torch.nn.functional.interpolate(
                predicted_depth.unsqueeze(1),
                size=frame.shape[:2],
                mode="bicubic",
                align_corners=False,
            ).squeeze()
            depth_np = depth.cpu().numpy().astype(np.float32)
            mn = float(depth_np.min())
            mx = float(depth_np.max())
            if mx - mn < 1e-6:
                return self.fallback.dense_depth(frame)
            relative = (depth_np - mn) / (mx - mn)
            return 2.0 + (1.0 - relative) * 58.0
        except Exception as exc:
            logger.warning("Depth Anything failed; using IPM fallback: {}", exc)
            self._failed = True
            return self.fallback.dense_depth(frame)

    def _load_model(self) -> bool:
        if self._model is not None and self._processor is not None:
            return True
        if self._failed:
            return False
        # ローカルモデル指定が無い場合はHubのリトライを避け、IPMへ即時フォールバックする。
        if self.model_name.startswith("models/") and not Path(self.model_name).exists():
            logger.warning("Depth model unavailable; using IPM fallback: {}", self.model_name)
            self._failed = True
            return False
        try:
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation

            self._processor = AutoImageProcessor.from_pretrained(self.model_name)
            self._model = AutoModelForDepthEstimation.from_pretrained(self.model_name).to(self.device)
            self._model.eval()
            return True
        except Exception as exc:
            logger.warning("Depth model could not be loaded; using IPM fallback: {}", exc)
            self._failed = True
            return False
