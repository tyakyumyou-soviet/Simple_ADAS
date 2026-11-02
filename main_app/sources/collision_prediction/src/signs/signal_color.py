from __future__ import annotations

import cv2
import numpy as np


def classify_signal_color(crop: np.ndarray) -> str | None:
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, (0, 80, 80), (10, 255, 255))
    red2 = cv2.inRange(hsv, (170, 80, 80), (180, 255, 255))
    yellow = cv2.inRange(hsv, (18, 80, 80), (38, 255, 255))
    green = cv2.inRange(hsv, (45, 60, 60), (95, 255, 255))
    scores = {
        "red_signal": int(red1.sum() + red2.sum()),
        "yellow_signal": int(yellow.sum()),
        "green_signal": int(green.sum()),
    }
    label, score = max(scores.items(), key=lambda item: item[1])
    if score < 255 * 8:
        return None
    return label
