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
from src.utils.performance import summarize_performance  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile ADAS pipeline stage timings over a video.")
    parser.add_argument("video", help="Input video path")
    parser.add_argument("--config", default="config/realtime_cpu.yaml")
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--warmup-frames", type=int, default=10,
                        help="Exclude initial model loading and warmup frames from statistics.")
    parser.add_argument("--output", default="outputs/logs/pipeline_profile.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    capture = cv2.VideoCapture(args.video)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {args.video}")
    cfg = load_config(args.config)
    pipeline = Pipeline(cfg)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    max_width = int(cfg.get("ui", {}).get("max_process_width", 0) or 0)
    samples: list[dict] = []
    frame_idx = 0
    total_frames = max(0, args.warmup_frames) + max(1, args.max_frames)
    while frame_idx < total_frames:
        ok, frame = capture.read()
        if not ok:
            break
        process_frame, _ = resize_for_processing(frame, max_width)
        _, meta = pipeline.process(process_frame, frame_idx, fps)
        if frame_idx >= args.warmup_frames:
            samples.append(meta)
        frame_idx += 1
    capture.release()

    report = {
        "video": str(Path(args.video)),
        "config": str(Path(args.config)),
        "input_fps": fps,
        "warmup_frames": args.warmup_frames,
        **summarize_performance(samples),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
