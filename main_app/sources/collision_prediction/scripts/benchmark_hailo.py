"""Compare Hailo models on identical camera or video frames without saving images."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.detection.hailo_detector import HailoDetector
from src.input.camera import CameraSource
from src.input.video_file import VideoFileSource
from src.pipeline import Pipeline
from src.utils.config import load_config
from src.utils.frame import resize_for_processing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/custom3_ai_hat.yaml")
    parser.add_argument("--video", help="Video file; omit to capture frames from the camera")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--frames", type=int, default=36)
    parser.add_argument("--warmup", type=int, default=7)
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args()
    if args.frames < 1 or args.warmup < 0:
        parser.error("--frames must be positive and --warmup nonnegative")

    cfg = load_config(args.config)
    source = VideoFileSource(args.video) if args.video else CameraSource(args.camera)
    frames = []
    source.open()
    try:
        fps = source.fps
        for _ in range(args.frames + args.warmup):
            ok, frame = source.read()
            if not ok:
                break
            frame, _ = resize_for_processing(frame, int(cfg.get("ui", {}).get("max_process_width", 0)))
            frames.append(frame.copy())
    finally:
        source.close()
    if len(frames) <= args.warmup:
        raise RuntimeError("Not enough frames were captured for the measurement")

    report = {"source": args.video or f"camera:{args.camera}", "source_fps": fps,
              "frame_count": len(frames), "models": []}
    for size in ("n", "s", "m"):
        model_cfg = copy.deepcopy(cfg)
        model_cfg.setdefault("detector", {})["weights"] = f"models/hailo8/yolo26{size}.hef"
        pipeline = Pipeline(model_cfg)
        try:
            backend = pipeline.tracker._external
            if not isinstance(backend, HailoDetector):
                raise RuntimeError("Hailo detector was not selected")
            times, stage_times, infer_times = [], [], []
            display_width = int(model_cfg.get("ui", {}).get("display_max_width", 0) or 0)
            for idx, frame in enumerate(frames):
                display_size = ((display_width, max(1, round(display_width * frame.shape[0] / frame.shape[1])))
                                if display_width else None)
                before_count = backend.inference_count
                start = time.perf_counter()
                _, meta = pipeline.process(frame, idx, fps, display_size=display_size)
                elapsed = (time.perf_counter() - start) * 1000
                if idx >= args.warmup:
                    times.append(elapsed)
                    stage_times.append(meta["stage_ms"])
                    if backend.inference_count > before_count:
                        infer_times.append(backend.last_hw_time_ms)
            if not infer_times:
                raise RuntimeError("No Hailo inference occurred in the measured frames")
            report["models"].append({
                "model": size, "measured_frames": len(times), "hailo_calls": len(infer_times),
                "hailort_infer_ms_median": round(float(np.median(infer_times)), 2),
                "pipeline_ms_mean": round(float(np.mean(times)), 2),
                "pipeline_ms_p95": round(float(np.percentile(times, 95)), 2),
                "stage_ms_mean": {name: round(float(np.mean([row[name] for row in stage_times])), 2)
                                  for name in stage_times[0]},
                "detector_interval_frames": pipeline.detector_every_n_frames,
            })
        finally:
            pipeline.close()
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(result + "\n", encoding="utf-8")
    print(result)


if __name__ == "__main__":
    main()
