"""Visible vehicle face from paired lamp appearance, or unknown.

Image velocity is deliberately excluded: approaching vehicles can show either face.
Lamp cues are heuristic, not a calibrated orientation classifier.
"""
from __future__ import annotations

import cv2
import numpy as np


def estimate_facing(frame: np.ndarray, bbox: tuple[float, float, float, float],
                    vy: float) -> str:
    """車両の向きを総合判定。"""
    x1, y1, x2, y2 = (int(v) for v in bbox)
    bw, bh = x2-x1, y2-y1
    if bw < 20 or bh < 20:
        return "unknown"
    if bw / max(bh, 1) > 2.5:
        return "side"
    # Image velocity is not evidence of which physical side is visible.
    return _lamp_hint(frame, x1, y1, x2, y2) or "unknown"


def _lamp_hint(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> str | None:
    """BB 左右端の下部だけを見て、対称ペアでランプ色判定する。

    - 中央 1/2 領域は無視（車体色を除外）
    - 左 1/4 と右 1/4 の **両方** で赤が一定値以上なら rear
    - 同様に明白 (ヘッドライト) があれば front
    - 大きすぎる赤領域は車体色とみなして無効
    """
    bw = x2 - x1
    bh = y2 - y1
    if bw < 20 or bh < 20:
        return None
    cut_y = y1 + bh * 2 // 3
    h_start = max(0, cut_y)
    h_end = min(frame.shape[0], y2)
    left_x1, left_x2 = max(0, x1), min(frame.shape[1], x1 + bw // 4)
    right_x1, right_x2 = max(0, x2 - bw // 4), min(frame.shape[1], x2)
    left_crop = frame[h_start:h_end, left_x1:left_x2]
    right_crop = frame[h_start:h_end, right_x1:right_x2]
    if left_crop.size == 0 or right_crop.size == 0:
        return None

    def _ratios(crop: np.ndarray) -> tuple[float, float]:
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        red1 = cv2.inRange(hsv, (0, 120, 80), (10, 255, 255))
        red2 = cv2.inRange(hsv, (170, 120, 80), (180, 255, 255))
        red = cv2.bitwise_or(red1, red2)
        bright = cv2.inRange(hsv, (0, 0, 220), (180, 60, 255))
        red_r = float(red.sum() / 255) / max(red.size, 1)
        bright_r = float(bright.sum() / 255) / max(bright.size, 1)
        return red_r, bright_r

    left_red, left_bright = _ratios(left_crop)
    right_red, right_bright = _ratios(right_crop)

    # 大きすぎる赤 = 車体色とみなして却下（左右どちらかが 60% 以上赤いなら無効）
    if left_red > 0.60 or right_red > 0.60:
        # 車体色が赤い → 色判定は信頼しない
        # ただしヘッドライト白は車体色と無関係なので判定可能
        if left_bright > 0.10 and right_bright > 0.10:
            return "front"
        return None

    # テールランプ判定: 左右両端で赤が 5% 以上、かつ片側が極端でない（対称）
    if left_red > 0.05 and right_red > 0.05 and min(left_red, right_red) > 0.4 * max(left_red, right_red):
        return "rear"
    # ヘッドライト判定: 左右両端で明白が 8% 以上、かつ対称
    if left_bright > 0.08 and right_bright > 0.08 and min(left_bright, right_bright) > 0.4 * max(left_bright, right_bright):
        return "front"
    return None


def combine_collision_risk(facing: str, heading: str) -> float:
    """衝突リスク係数 (0-1)。1.0 = 高リスク。"""
    if facing == "front" and heading == "approaching":
        return 1.0
    if facing == "rear" and heading == "leaving":
        return 0.0
    if facing == "rear" and heading == "approaching":
        return 0.5
    if facing == "front" and heading == "leaving":
        return 0.3
    if facing == "front":
        return 0.7
    if facing == "rear":
        return 0.2
    if heading == "approaching":
        return 0.6
    if heading == "leaving":
        return 0.1
    return 0.5
