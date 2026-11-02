"""外部モデル (YOLOX / NanoDet / EfficientDet-Lite) 用の Detector 群。

Ultralytics に含まれない検出器を統一インターフェースで扱う。
共通: `detect(frame) -> list[Detection]`
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from src.types import Detection


# COCO 80 クラスのうち本プロジェクトで使うクラス
PERSON_CLS_ID = 0
BICYCLE_CLS_ID = 1
CAR_CLS_ID = 2
MOTORCYCLE_CLS_ID = 3
BUS_CLS_ID = 5
TRUCK_CLS_ID = 7
COCO_NAME_BY_ID = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
    5: "bus", 7: "truck",
}
COCO_KEEP_IDS = set(COCO_NAME_BY_ID.keys())


class ExternalDetectorBase:
    """共通インターフェース。"""
    def detect(self, frame: np.ndarray) -> list[Detection]:
        raise NotImplementedError


# ============================================================
# YOLOX (Nano / Tiny)
# ============================================================

class YoloxDetector(ExternalDetectorBase):
    """YOLOX 系 ONNX モデル用。Nano / Tiny は同一の入出力形式。

    入力: BGR フレーム
    出力: list[Detection] (bbox は元フレーム座標系)
    """

    def __init__(self, weights: str, conf: float = 0.25, iou: float = 0.45,
                 input_size: int = 416, device: str = "auto"):
        self.weights = weights
        self.conf = conf
        self.iou = iou
        self.input_size = input_size
        self.device = device
        self._session = None
        self._input_name: str | None = None
        self._failed = False
        # YOLOX のストライド (Nano/Tiny ともに 8/16/32)
        self._strides = (8, 16, 32)
        # 事前計算: grid と stride マッピング (input_size に依存)
        self._grids: np.ndarray | None = None
        self._expanded_strides: np.ndarray | None = None

    def _build_grids(self) -> None:
        grids = []
        strides_arr = []
        for stride in self._strides:
            n = self.input_size // stride
            ys, xs = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
            grid = np.stack([xs, ys], axis=-1).reshape(-1, 2)
            grids.append(grid)
            strides_arr.append(np.full((n * n,), stride))
        self._grids = np.concatenate(grids, axis=0).astype(np.float32)
        self._expanded_strides = np.concatenate(strides_arr, axis=0).astype(np.float32)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._failed:
            return []
        session = self._load()
        if session is None:
            return []
        if self._grids is None:
            self._build_grids()
        try:
            blob, ratio = _preprocess_yolox(frame, self.input_size)
            outputs = session.run(None, {self._input_name: blob})[0]
            return _postprocess_yolox(outputs, ratio, self.conf, self.iou,
                                       self._grids, self._expanded_strides)
        except Exception as exc:
            logger.warning("YOLOX 推論失敗: {}", exc)
            self._failed = True
            return []

    def _load(self):
        if self._session is not None:
            return self._session
        try:
            import onnxruntime as ort
            providers = ["CPUExecutionProvider"]
            # CoreML が使えれば優先 (Mac)
            if self.device != "cpu" and "CoreMLExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "CoreMLExecutionProvider")
            self._session = ort.InferenceSession(self.weights, providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            logger.info("YOLOX loaded: {} (providers={})", Path(self.weights).name, providers)
        except Exception as exc:
            logger.warning("YOLOX ロード失敗: {}", exc)
            self._failed = True
            return None
        return self._session


def _preprocess_yolox(image: np.ndarray, input_size: int) -> tuple[np.ndarray, float]:
    """YOLOX 用の前処理: letterbox resize + uint8 のまま (YOLOX は正規化なし)。"""
    h, w = image.shape[:2]
    ratio = min(input_size / h, input_size / w)
    nh, nw = int(h * ratio), int(w * ratio)
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    padded = np.full((input_size, input_size, 3), 114, dtype=np.uint8)
    padded[:nh, :nw] = resized
    blob = padded.transpose(2, 0, 1)[None].astype(np.float32)  # NCHW
    return blob, ratio


def _postprocess_yolox(outputs: np.ndarray, ratio: float,
                       conf_thres: float, iou_thres: float,
                       grids: np.ndarray, expanded_strides: np.ndarray) -> list[Detection]:
    """YOLOX 出力 (1, N, 85) → Detection list。
    stride decode を明示的に行う (0.1.1rc0 ONNX は decode 内蔵していない)。

    出力形式: [cx_offset, cy_offset, w_log, h_log, obj_conf, cls0_conf, ...]
    """
    predictions = outputs[0].copy()  # (N, 85)
    # YOLOX stride decode
    predictions[:, 0:2] = (predictions[:, 0:2] + grids) * expanded_strides[:, None]
    predictions[:, 2:4] = np.exp(predictions[:, 2:4]) * expanded_strides[:, None]
    boxes_xywh = predictions[:, :4]
    obj_conf = predictions[:, 4:5]
    cls_conf = predictions[:, 5:]
    scores = obj_conf * cls_conf  # (N, 80)
    cls_ids = np.argmax(cls_conf, axis=1)
    cls_scores = np.max(scores, axis=1)

    # COCO の対象クラス + conf 閾値でフィルタ
    keep = (cls_scores > conf_thres) & np.isin(cls_ids, list(COCO_KEEP_IDS))
    if not np.any(keep):
        return []
    boxes_xywh = boxes_xywh[keep]
    cls_ids = cls_ids[keep]
    cls_scores = cls_scores[keep]

    # xywh → xyxy
    boxes = np.empty_like(boxes_xywh)
    boxes[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2
    # 元画像座標系へ
    boxes /= ratio

    # クラス毎 NMS (cv2.dnn.NMSBoxes)
    out: list[Detection] = []
    for cid in np.unique(cls_ids):
        idxs = np.where(cls_ids == cid)[0]
        bxs = boxes[idxs].tolist()
        scs = cls_scores[idxs].tolist()
        keep_idx = cv2.dnn.NMSBoxes(bxs, scs, conf_thres, iou_thres)
        if len(keep_idx) == 0:
            continue
        for ki in np.array(keep_idx).flatten():
            x1, y1, x2, y2 = boxes[idxs[ki]]
            out.append(Detection(
                bbox=(float(x1), float(y1), float(x2), float(y2)),
                cls=COCO_NAME_BY_ID.get(int(cid), str(int(cid))),
                conf=float(cls_scores[idxs[ki]]),
            ))
    return out


# ============================================================
# NanoDet-Plus
# ============================================================

class NanoDetDetector(ExternalDetectorBase):
    """NanoDet-Plus ONNX 用。中心点予測方式 (FCOS-like)。"""

    def __init__(self, weights: str, conf: float = 0.45, iou: float = 0.5,
                 input_size: int = 320):
        self.weights = weights
        self.conf = conf
        self.iou = iou
        self.input_size = input_size
        self._session = None
        self._input_name: str | None = None
        self._failed = False
        self._strides = (8, 16, 32, 64)  # NanoDet-Plus 4 段階
        self._reg_max = 7
        self._mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
        self._std = np.array([57.375, 57.12, 58.395], dtype=np.float32)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._failed:
            return []
        session = self._load()
        if session is None:
            return []
        try:
            blob, ratio = _preprocess_nanodet(frame, self.input_size, self._mean, self._std)
            outputs = session.run(None, {self._input_name: blob})
            return _postprocess_nanodet(outputs, ratio, self.input_size, self._strides,
                                         self._reg_max, self.conf, self.iou)
        except Exception as exc:
            logger.warning("NanoDet 推論失敗: {}", exc)
            self._failed = True
            return []

    def _load(self):
        if self._session is not None:
            return self._session
        try:
            import onnxruntime as ort
            providers = ["CPUExecutionProvider"]
            if "CoreMLExecutionProvider" in ort.get_available_providers():
                providers.insert(0, "CoreMLExecutionProvider")
            self._session = ort.InferenceSession(self.weights, providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            logger.info("NanoDet loaded: {}", Path(self.weights).name)
        except Exception as exc:
            logger.warning("NanoDet ロード失敗: {}", exc)
            self._failed = True
            return None
        return self._session


def _preprocess_nanodet(image: np.ndarray, input_size: int,
                        mean: np.ndarray, std: np.ndarray) -> tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    ratio = min(input_size / h, input_size / w)
    nh, nw = int(h * ratio), int(w * ratio)
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    padded = np.zeros((input_size, input_size, 3), dtype=np.uint8)
    padded[:nh, :nw] = resized
    img = padded.astype(np.float32)
    img = (img - mean) / std
    blob = img.transpose(2, 0, 1)[None].astype(np.float32)
    return blob, ratio


def _postprocess_nanodet(outputs, ratio: float, input_size: int,
                          strides: tuple[int, ...], reg_max: int,
                          conf_thres: float, iou_thres: float) -> list[Detection]:
    """NanoDet 出力を decode。出力は 80 (cls) + 32 (reg) = 112 ch / stride 段階。

    実装の簡略のため、output[0] が (1, N, 112) の連結形式と仮定する
    (NanoDet-Plus デフォルトエクスポート形式)。
    """
    pred = outputs[0]  # (1, total_points, 80+4*(reg_max+1))
    if pred.ndim == 3:
        pred = pred[0]
    num_classes = 80
    cls_scores = pred[:, :num_classes]
    box_dist = pred[:, num_classes:]  # 4 * (reg_max+1)

    # 各 stride のグリッド数
    grids = []
    expanded_strides = []
    for stride in strides:
        n = input_size // stride
        ys, xs = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        grid = np.stack([xs, ys], axis=-1).reshape(-1, 2)
        grids.append(grid)
        expanded_strides.append(np.full((n * n,), stride))
    grids = np.concatenate(grids, axis=0)
    expanded_strides = np.concatenate(expanded_strides, axis=0)

    if cls_scores.shape[0] != grids.shape[0]:
        # 形式違いの場合は安全に空返し
        return []

    # この NanoDet ONNX は cls 出力が既に sigmoid 済 (確率値) なので二重適用しない
    cls_ids = np.argmax(cls_scores, axis=1)
    cls_conf = np.max(cls_scores, axis=1)
    keep = (cls_conf > conf_thres) & np.isin(cls_ids, list(COCO_KEEP_IDS))
    if not np.any(keep):
        return []
    cls_ids = cls_ids[keep]
    cls_conf = cls_conf[keep]
    box_dist = box_dist[keep]
    grids = grids[keep]
    expanded_strides = expanded_strides[keep]

    # GFL の DFL decode: 4 サイド × (reg_max+1) bins → 期待値
    box_dist = box_dist.reshape(-1, 4, reg_max + 1)
    box_dist = _softmax(box_dist, axis=-1)
    dist = (box_dist * np.arange(reg_max + 1)).sum(axis=-1)  # (N, 4)
    dist = dist * expanded_strides[:, None]

    cx = (grids[:, 0] + 0.5) * expanded_strides
    cy = (grids[:, 1] + 0.5) * expanded_strides
    x1 = cx - dist[:, 0]
    y1 = cy - dist[:, 1]
    x2 = cx + dist[:, 2]
    y2 = cy + dist[:, 3]
    boxes = np.stack([x1, y1, x2, y2], axis=1) / ratio

    out: list[Detection] = []
    for cid in np.unique(cls_ids):
        idxs = np.where(cls_ids == cid)[0]
        bxs = boxes[idxs].tolist()
        scs = cls_conf[idxs].tolist()
        keep_idx = cv2.dnn.NMSBoxes(bxs, scs, conf_thres, iou_thres)
        if len(keep_idx) == 0:
            continue
        for ki in np.array(keep_idx).flatten():
            x1, y1, x2, y2 = boxes[idxs[ki]]
            out.append(Detection(
                bbox=(float(x1), float(y1), float(x2), float(y2)),
                cls=COCO_NAME_BY_ID.get(int(cid), str(int(cid))),
                conf=float(cls_conf[idxs[ki]]),
            ))
    return out


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _softmax(x: np.ndarray, axis: int) -> np.ndarray:
    e = np.exp(x - np.max(x, axis=axis, keepdims=True))
    return e / np.sum(e, axis=axis, keepdims=True)


# ============================================================
# EfficientDet-Lite0 (TFLite)
# ============================================================

class EfficientDetDetector(ExternalDetectorBase):
    """EfficientDet-Lite0 TFLite モデル用。

    COCO 90 クラス、入力 320x320、後処理は TFLite に組み込まれている形式が多い。
    """

    EFFICIENTDET_KEEP = {
        1: "person", 2: "bicycle", 3: "car", 4: "motorcycle",
        6: "bus", 8: "truck",
    }

    def __init__(self, weights: str, conf: float = 0.3, input_size: int = 320):
        self.weights = weights
        self.conf = conf
        self.input_size = input_size
        self._interpreter = None
        self._input_details = None
        self._output_details = None
        self._failed = False

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._failed:
            return []
        interp = self._load()
        if interp is None:
            return []
        try:
            h, w = frame.shape[:2]
            resized = cv2.resize(frame, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR)
            blob = resized[None].astype(np.uint8)  # quantized INT8 model
            interp.set_tensor(self._input_details[0]["index"], blob)
            interp.invoke()
            # 出力: 通常 boxes / classes / scores / num_detections の 4 つ
            boxes = interp.get_tensor(self._output_details[0]["index"])[0]
            classes = interp.get_tensor(self._output_details[1]["index"])[0]
            scores = interp.get_tensor(self._output_details[2]["index"])[0]
            return self._decode(boxes, classes, scores, w, h)
        except Exception as exc:
            logger.warning("EfficientDet 推論失敗: {}", exc)
            self._failed = True
            return []

    def _decode(self, boxes, classes, scores, w: int, h: int) -> list[Detection]:
        out: list[Detection] = []
        for i in range(len(scores)):
            if scores[i] < self.conf:
                continue
            cid = int(classes[i]) + 1  # TFLite は 0-indexed の場合あり、+1 で COCO ID に
            name = self.EFFICIENTDET_KEEP.get(cid)
            if name is None:
                continue
            # boxes は [ymin, xmin, ymax, xmax] 正規化座標
            ymin, xmin, ymax, xmax = boxes[i]
            out.append(Detection(
                bbox=(float(xmin * w), float(ymin * h), float(xmax * w), float(ymax * h)),
                cls=name, conf=float(scores[i]),
            ))
        return out

    def _load(self):
        if self._interpreter is not None:
            return self._interpreter
        try:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter
            self._interpreter = Interpreter(model_path=self.weights)
            self._interpreter.allocate_tensors()
            self._input_details = self._interpreter.get_input_details()
            self._output_details = self._interpreter.get_output_details()
            logger.info("EfficientDet loaded: {}", Path(self.weights).name)
        except Exception as exc:
            logger.warning("EfficientDet ロード失敗 (tflite-runtime 未インストール？): {}", exc)
            self._failed = True
            return None
        return self._interpreter


# ============================================================
# ファクトリ
# ============================================================

def make_external_detector(weights: str, device: str = "auto") -> ExternalDetectorBase | None:
    """ファイル名から適切な Detector を返す。対応外なら None。"""
    name = Path(weights).name.lower()
    if name.startswith("yolox"):
        # nano は 416, tiny は 416 で学習されている
        size = 416
        return YoloxDetector(weights, input_size=size, device=device)
    if name.startswith("nanodet"):
        # ファイル名末尾の _320 / _416 を取る簡易判定
        size = 320 if "320" in name else 416
        return NanoDetDetector(weights, input_size=size)
    if name.startswith("efficientdet"):
        return EfficientDetDetector(weights, input_size=320)
    return None
