"""Evaluate lane detection against lightweight per-frame lane annotations.

Annotation format:
{
  "frames": {
    "0": {"left": [[x_top, y_top], [x_bottom, y_bottom]],
          "right": [[x_top, y_top], [x_bottom, y_bottom]]}
  }
}
Only annotated frames are evaluated. Coordinates refer to the resized processing
frame, so create annotations at the profile's `max_process_width`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lane.lane_detector import LaneDetector  # noqa: E402
from src.utils.config import load_config  # noqa: E402
from src.utils.frame import resize_for_processing  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate lane detection against annotated video frames.")
    parser.add_argument("video", help="Input video path")
    parser.add_argument("annotations", help="JSON annotation path")
    parser.add_argument("--config", default="config/custom.yaml")
    parser.add_argument("--output", default="outputs/logs/lane_evaluation.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    annotations = json.loads(Path(args.annotations).read_text(encoding="utf-8")).get("frames", {})
    if not annotations:
        raise ValueError("annotations.frames must contain at least one frame")
    cfg = load_config(args.config)
    lane_cfg = cfg.get("lane", {})
    detector = LaneDetector(
        method=str(lane_cfg.get("method", "classical")),
        center_x_ratio=float(lane_cfg.get("center_x_ratio", 0.5)),
        dashed_support=bool(lane_cfg.get("dashed_support", True)),
        hough_threshold=int(lane_cfg.get("hough_threshold", 24)),
        min_line_length=int(lane_cfg.get("min_line_length", 18)),
        max_line_gap=int(lane_cfg.get("max_line_gap", 180)),
        ipm_source_top_y_ratio=float(lane_cfg.get("ipm_source_top_y_ratio", 0.48)),
        ipm_source_bottom_width_ratio=float(lane_cfg.get("ipm_source_bottom_width_ratio", 0.90)),
        ipm_source_top_width_ratio=float(lane_cfg.get("ipm_source_top_width_ratio", 0.18)),
        ipm_track_margin_px=int(lane_cfg.get("ipm_track_margin_px", 24)),
        ipm_min_lane_pixels=int(lane_cfg.get("ipm_min_lane_pixels", 28)),
        ipm_processing_scale=float(lane_cfg.get("ipm_processing_scale", 0.50)),
        acquire_frames=int(lane_cfg.get("acquire_frames", 2)),
        max_result_age_ms=int(lane_cfg.get("max_result_age_ms", 120)),
    )
    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    max_width = int(cfg.get("ui", {}).get("max_process_width", 0) or 0)
    wanted = {int(key): value for key, value in annotations.items()}
    frame_idx = 0
    hits = 0
    center_errors: list[float] = []
    while wanted:
        ok, frame = capture.read()
        if not ok:
            break
        annotation = wanted.pop(frame_idx, None)
        if annotation is not None:
            process_frame, _ = resize_for_processing(frame, max_width)
            lanes = detector.detect(process_frame, timestamp=frame_idx / fps)
            if lanes.left_lane is not None and lanes.right_lane is not None:
                hits += 1
                expected_center = _bottom_center(annotation)
                detected_center = (float(lanes.left_lane[-1][0]) + float(lanes.right_lane[-1][0])) / 2
                center_errors.append(abs(detected_center - expected_center))
        frame_idx += 1
    capture.release()
    evaluated = len(annotations) - len(wanted)
    report = {
        "video": str(Path(args.video)),
        "annotations": str(Path(args.annotations)),
        "config": str(Path(args.config)),
        "evaluated_frames": evaluated,
        "detected_frames": hits,
        "detection_rate": hits / evaluated if evaluated else 0.0,
        "bottom_center_error_px": _summary(center_errors),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _bottom_center(annotation: dict) -> float:
    left = np.asarray(annotation["left"], dtype=np.float64)
    right = np.asarray(annotation["right"], dtype=np.float64)
    left_bottom = left[np.argmax(left[:, 1]), 0]
    right_bottom = right[np.argmax(right[:, 1]), 0]
    return float((left_bottom + right_bottom) / 2)


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    data = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(data.mean()),
        "p50": float(np.percentile(data, 50)),
        "p95": float(np.percentile(data, 95)),
    }


if __name__ == "__main__":
    main()
