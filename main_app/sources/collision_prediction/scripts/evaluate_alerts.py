from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline import Pipeline  # noqa: E402
from src.utils.config import load_config  # noqa: E402
from src.utils.frame import resize_for_processing  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ADAS pipeline over a video and export alert events.")
    parser.add_argument("video", help="Input video path")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--output", default="outputs/logs/alerts.jsonl")
    parser.add_argument("--annotated-output", default="", help="Optional annotated MP4 output path")
    parser.add_argument("--max-frames", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    cfg = load_config(args.config)
    pipeline = Pipeline(cfg)
    max_process_width = int(cfg.get("ui", {}).get("max_process_width", 0) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    analysis_fps = float(cfg.get("ui", {}).get("analysis_fps", 0) or 0)
    analysis_interval = 1 if analysis_fps <= 0 else max(1, round(max(fps, 1.0) / analysis_fps))
    writer = None
    writer_size = None
    if args.annotated_output:
        annotated = Path(args.annotated_output)
        annotated.parent.mkdir(parents=True, exist_ok=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok or (args.max_frames and idx >= args.max_frames):
                break
            process_frame, scale = resize_for_processing(frame, max_process_width)
            if idx % analysis_interval == 0:
                display, meta = pipeline.process(process_frame, idx, fps)
            else:
                display = process_frame
                meta = {"emitted_alerts": []}
            meta["process_scale"] = scale
            if args.annotated_output and writer is None:
                writer_size = (display.shape[1], display.shape[0])
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(annotated), fourcc, fps, writer_size)
            if writer is not None:
                writer.write(display)
            for alert in meta.get("emitted_alerts", []):
                handle.write(
                    json.dumps(
                        {
                            "frame_idx": idx,
                            "time_s": idx / max(fps, 1.0),
                            "level": alert.level,
                            "kind": alert.kind,
                            "target_id": alert.target_id,
                            "message": alert.message,
                            "bbox": alert.bbox,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            idx += 1
    cap.release()
    if writer is not None:
        writer.release()


if __name__ == "__main__":
    main()
