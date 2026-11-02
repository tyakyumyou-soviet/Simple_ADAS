from __future__ import annotations

import cv2
import numpy as np
import torch
from loguru import logger
from PIL import Image
from pathlib import Path


_SEGFORMER_MISSING_LOGGED = False


class RoadSegmenter:
    def __init__(
        self,
        model: str = "models/segformer-b0-cityscapes",
        every_n_frames: int = 3,
        input_size: int = 512,
        enabled: bool = False,
        device: str = "cpu",
    ):
        self.model_name = model
        self.every_n_frames = max(1, every_n_frames)
        self.input_size = input_size
        self.enabled = enabled
        self.device = device
        self._last_mask: np.ndarray | None = None
        self._processor = None
        self._model = None
        self._failed = False

    def predict(self, frame: np.ndarray, frame_idx: int = 0) -> np.ndarray:
        if self._last_mask is not None and frame_idx % self.every_n_frames != 0:
            return self._last_mask
        if self.enabled:
            self._last_mask = self._model_mask(frame)
        else:
            self._last_mask = self._heuristic_mask(frame)
        return self._last_mask

    def _model_mask(self, frame: np.ndarray) -> np.ndarray:
        if self._failed:
            return self._heuristic_mask(frame)
        if not self._load_model():
            return self._heuristic_mask(frame)
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            inputs = self._processor(images=image, return_tensors="pt")
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with torch.no_grad():
                logits = self._model(**inputs).logits
            logits = torch.nn.functional.interpolate(
                logits,
                size=frame.shape[:2],
                mode="bilinear",
                align_corners=False,
            )
            labels = logits.argmax(dim=1)[0].cpu().numpy().astype(np.uint8)
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            mask[labels == 0] = 1
            mask[labels == 1] = 2
            return mask
        except Exception as exc:
            logger.warning("SegFormer failed; using heuristic road mask: {}", exc)
            self._failed = True
            return self._heuristic_mask(frame)

    def _load_model(self) -> bool:
        if self._model is not None and self._processor is not None:
            return True
        if self._failed:
            return False
        # `models/...` はローカル資産として扱う。未配備時にHubへ接続して
        # 起動を待たせず、即座に軽量フォールバックへ切り替える。
        if self.model_name.startswith("models/") and not Path(self.model_name).exists():
            logger.info("SegFormer モデル未配置、ヒューリスティック路面マスクを使用 ({})", self.model_name)
            self._failed = True
            return False
        try:
            from transformers import AutoImageProcessor, SegformerForSemanticSegmentation

            self._processor = AutoImageProcessor.from_pretrained(self.model_name)
            self._model = SegformerForSemanticSegmentation.from_pretrained(self.model_name).to(self.device)
            self._model.eval()
            return True
        except Exception as exc:
            global _SEGFORMER_MISSING_LOGGED
            if not _SEGFORMER_MISSING_LOGGED:
                logger.info("SegFormer モデル未配置、ヒューリスティック路面マスクを使用 ({})", exc)
                _SEGFORMER_MISSING_LOGGED = True
            self._failed = True
            return False

    @staticmethod
    def _heuristic_mask(frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)
        road = np.array(
            [
                (int(width * 0.25), height - 1),
                (int(width * 0.43), int(height * 0.52)),
                (int(width * 0.57), int(height * 0.52)),
                (int(width * 0.75), height - 1),
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [road], 1)
        mask[:, : int(width * 0.18)] = 2
        mask[:, int(width * 0.82) :] = 2
        return mask
