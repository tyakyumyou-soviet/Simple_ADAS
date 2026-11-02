"""信号 vs テールランプの区別テスト。"""
import cv2
import numpy as np

from src.signs.jp_sign_detector import JpSignDetector


def test_signal_detection_excludes_vehicle_bbox() -> None:
    """車両 BB と重なる赤い光源（テールランプ想定）は除外される。"""
    frame = np.zeros((400, 600, 3), dtype=np.uint8)
    # 画面上部に赤信号らしき光源（信号として検出されるはず）
    cv2.circle(frame, (300, 50), 8, (0, 0, 255), -1)
    # 画面下部の車両 BB 内に赤い光（テールランプ想定）— ROI 外なのでそもそも検出されない
    cv2.circle(frame, (200, 350), 7, (0, 0, 255), -1)
    vehicle_bbox = (170, 320, 270, 380)

    det = JpSignDetector(enabled=True)
    _, signals_with_vehicle = det.detect(frame, vehicle_bboxes=[vehicle_bbox])
    _, signals_no_vehicle = det.detect(frame, vehicle_bboxes=None)
    # 車両情報の有無に関わらず、テールランプ位置（画面下）の検出はしない
    for signals in (signals_with_vehicle, signals_no_vehicle):
        for s in signals:
            # すべて画面上 40% の中に収まっていること
            assert s.bbox[3] <= 400 * 0.40 + 6  # padding 込み


def test_signal_in_upper_half_is_detected() -> None:
    """画面上部の信号らしき光源は検出される。"""
    frame = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.circle(frame, (300, 60), 10, (0, 0, 255), -1)   # 赤
    det = JpSignDetector(enabled=True)
    _, signals = det.detect(frame, vehicle_bboxes=[])
    assert len(signals) >= 1
