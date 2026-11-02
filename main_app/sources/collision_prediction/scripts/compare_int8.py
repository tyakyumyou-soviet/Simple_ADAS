"""PyTorch (.pt) と INT8 TFLite (.tflite) の検出結果を同一映像で比較する。

目的: INT8 量子化による検出率の劣化、特に遠方の人/自転車の取りこぼしを
      Coral 実機なしで Mac 上で評価し、「INT8 が実用に耐えるか」を判断する。

使い方:
    PYTHONPATH=. python scripts/compare_int8.py \
        --video data/videos/test.mp4 \
        --pt models/yolo11n.pt \
        --tflite models/yolo11n_full_integer_quant.tflite \
        --imgsz 320 --max-frames 200

出力: クラス別の総検出数 / フレーム平均 / バウンディングボックス面積帯別の検出数。
      小さい BB (遠方ターゲット) の取りこぼし傾向が分かるよう面積帯で層別する。
"""
from __future__ import annotations

import argparse
from collections import defaultdict

import cv2

from src.detection.yolo_detector import YoloDetector
from src.types import Detection


# BB 面積 (画像比) の帯。遠方ほど面積が小さい
AREA_BANDS = [
    ("tiny  (<0.2%)", 0.000, 0.002),
    ("small (0.2-1%)", 0.002, 0.010),
    ("mid   (1-5%)", 0.010, 0.050),
    ("large (>5%)", 0.050, 1.001),
]


def area_band(det: Detection, frame_area: float) -> str:
    x1, y1, x2, y2 = det.bbox
    ratio = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1)) / frame_area
    for name, lo, hi in AREA_BANDS:
        if lo <= ratio < hi:
            return name
    return AREA_BANDS[-1][0]


def run_backend(weights: str, video: str, imgsz: int, conf: float, max_frames: int):
    det = YoloDetector(weights=weights, device="auto", conf=conf, imgsz=imgsz, max_det=120)
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit(f"動画を開けません: {video}")

    # 動画全体から均等サンプリング (冒頭への偏りを避ける)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    step = max(1, total // max_frames) if total > 0 else 1

    by_class: dict[str, int] = defaultdict(int)
    by_band: dict[str, int] = defaultdict(int)
    by_class_band: dict[tuple[str, str], int] = defaultdict(int)
    n_frames = 0
    idx = 0
    while n_frames < max_frames:
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        n_frames += 1
        idx += step
        frame_area = float(frame.shape[0] * frame.shape[1])
        for d in det.detect(frame):
            by_class[d.cls] += 1
            band = area_band(d, frame_area)
            by_band[band] += 1
            by_class_band[(d.cls, band)] += 1
        if total > 0 and idx >= total:
            break
    cap.release()
    return {
        "weights": weights,
        "device": det.device,
        "n_frames": n_frames,
        "by_class": dict(by_class),
        "by_band": dict(by_band),
        "by_class_band": dict(by_class_band),
    }


def print_report(pt: dict, tf: dict) -> None:
    classes = sorted(set(pt["by_class"]) | set(tf["by_class"]))
    print("\n================ INT8 精度比較 ================")
    print(f"frames: pt={pt['n_frames']} (device={pt['device']}) / "
          f"tflite={tf['n_frames']} (device={tf['device']})")

    print("\n--- クラス別 総検出数 (pt -> tflite, 残存率) ---")
    for cls in classes:
        a = pt["by_class"].get(cls, 0)
        b = tf["by_class"].get(cls, 0)
        rate = (b / a * 100) if a else float("nan")
        print(f"  {cls:12s}: {a:6d} -> {b:6d}  ({rate:5.1f}%)")

    print("\n--- BB 面積帯別 総検出数 (遠方=tiny/small ほど劣化が問題) ---")
    for name, _, _ in AREA_BANDS:
        a = pt["by_band"].get(name, 0)
        b = tf["by_band"].get(name, 0)
        rate = (b / a * 100) if a else float("nan")
        print(f"  {name:16s}: {a:6d} -> {b:6d}  ({rate:5.1f}%)")

    print("\n--- 人/自転車 × 面積帯 (最重要: 遠方の歩行者/自転車) ---")
    for cls in ("person", "bicycle"):
        print(f"  [{cls}]")
        for name, _, _ in AREA_BANDS:
            a = pt["by_class_band"].get((cls, name), 0)
            b = tf["by_class_band"].get((cls, name), 0)
            rate = (b / a * 100) if a else float("nan")
            print(f"    {name:16s}: {a:6d} -> {b:6d}  ({rate:5.1f}%)")
    print("\n注: 残存率が低い帯ほど INT8 で取りこぼしが多い。"
          "tiny/small の person/bicycle が大きく落ちる場合は imgsz 引き上げを検討。")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--pt", default="models/yolo11n.pt")
    ap.add_argument("--tflite", default="models/yolo11n_full_integer_quant.tflite")
    ap.add_argument("--imgsz", type=int, default=320)
    ap.add_argument("--conf", type=float, default=0.18)
    ap.add_argument("--max-frames", type=int, default=200)
    args = ap.parse_args()

    print(f"[1/2] PyTorch 基準を計測: {args.pt}")
    pt = run_backend(args.pt, args.video, args.imgsz, args.conf, args.max_frames)
    print(f"[2/2] INT8 TFLite を計測: {args.tflite}")
    tf = run_backend(args.tflite, args.video, args.imgsz, args.conf, args.max_frames)
    print_report(pt, tf)


if __name__ == "__main__":
    main()
