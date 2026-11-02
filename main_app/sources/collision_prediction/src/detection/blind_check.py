"""カメラ異常 (検出不能状態) 判定器。

ハイブリッド方式:
  ① 直近 N 秒間検出ゼロ (時間条件)
  ② 画像品質が悪い (画素条件: 単色 / ボケ / 真っ暗 / 真っ白)
  ① AND ② で初めて「検出不能」と判定。
誤通知 (深夜の田舎道 = 検出ゼロだが視覚は正常) を避ける狙い。
"""
from __future__ import annotations

import cv2
import numpy as np


class BlindnessDetector:
    DOWNSAMPLE = (160, 90)  # 評価用に小さくする (コスト削減)

    def __init__(self,
                 no_detect_seconds: float = 2.0,
                 brightness_min: float = 12.0,
                 brightness_max: float = 230.0,
                 contrast_min: float = 10.0,
                 sharpness_min: float = 12.0):
        self.no_detect_seconds = no_detect_seconds
        self.brightness_min = brightness_min
        self.brightness_max = brightness_max
        self.contrast_min = contrast_min
        self.sharpness_min = sharpness_min
        self._last_detection_time: float | None = None
        self._initial_time: float | None = None

    def reset(self) -> None:
        self._last_detection_time = None
        self._initial_time = None

    def update(self, frame: np.ndarray, has_detections: bool,
               timestamp: float) -> tuple[bool, str | None]:
        """1 フレーム評価。(is_blind, reason) を返す。

        reason は通知文 ("画面真っ暗", "ボケ" 等)、is_blind=False なら None。
        """
        if self._initial_time is None:
            self._initial_time = timestamp
        if has_detections:
            self._last_detection_time = timestamp
            return False, None
        # 起動直後で一度も検出してない場合: ウォームアップ扱い
        baseline = self._last_detection_time if self._last_detection_time is not None else self._initial_time
        if timestamp - baseline < self.no_detect_seconds:
            return False, None
        # 時間条件成立 → 画質チェック
        reason = self._check_image_quality(frame)
        if reason is None:
            return False, None  # 画質は正常 = 単に物体がいない可能性
        return True, reason

    def _check_image_quality(self, frame: np.ndarray) -> str | None:
        """画質悪化の理由を返す。正常なら None。"""
        small = cv2.resize(frame, self.DOWNSAMPLE, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        mean = float(gray.mean())
        std = float(gray.std())
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if mean < self.brightness_min and std < self.contrast_min and lap_var < self.sharpness_min:
            return f"画面真っ暗 (mean={mean:.0f})"
        if mean > self.brightness_max:
            return f"画面真っ白 (mean={mean:.0f})"
        if mean < 35.0:
            return None
        if std < self.contrast_min:
            return f"画面が単色 / レンズ遮蔽 (std={std:.1f})"
        if lap_var < self.sharpness_min:
            return f"画面が完全にボケ / 霧 (sharpness={lap_var:.1f})"
        return None
