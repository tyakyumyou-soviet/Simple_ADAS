"""Measure application preview throughput on the Pi without a display server.

This counts Qt-delivered frames, not physical display or sensor-to-screen latency.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QTimer
from src.input.camera import CameraSource
from src.input.video_file import RealtimeVideoSource, VideoFileSource
from src.ui.async_camera_thread import AsyncCameraThread
from src.ui.inference_thread import InferenceThread
from src.utils.config import load_config


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("camera", "video-realtime", "video-all"))
    p.add_argument("--video")
    p.add_argument("--seconds", type=int, default=12)
    p.add_argument("--detector-hz", type=float)
    p.add_argument("--lane-hz", type=float)
    args = p.parse_args()
    cfg = load_config("config/pi_async_ai_hat.yaml")
    if args.detector_hz is not None:
        cfg.setdefault("detector", {})["update_hz"] = args.detector_hz
    if args.lane_hz is not None:
        cfg.setdefault("lane", {})["update_hz"] = args.lane_hz
    if args.mode == "camera":
        i = cfg["input"]
        source = CameraSource(0, i["camera_width"], i["camera_height"], i["camera_fps"], i["camera_buffers"])
    else:
        if not args.video:
            p.error("--video is required")
        source = (RealtimeVideoSource if args.mode == "video-realtime" else VideoFileSource)(args.video)
    cfg["input"]["video_mode"] = "all_frames" if args.mode == "video-all" else "realtime"
    thread = (InferenceThread if args.mode == "video-all" else AsyncCameraThread)(source, cfg)
    app = QCoreApplication([])
    events, errors = [], []
    started = time.monotonic()
    def on_frame(_, meta):
        events.append((time.monotonic(), dict(meta)))
        if isinstance(thread, AsyncCameraThread):
            thread.acknowledge_frame()
    thread.frame_ready.connect(on_frame)
    thread.error.connect(errors.append)
    thread.finished_signal.connect(app.quit)
    QTimer.singleShot(args.seconds * 1000, thread.stop)
    thread.start()
    app.exec()
    thread.wait()
    duration = time.monotonic() - started
    last = events[-1][1] if events else {}
    stage_samples = {}
    for _, meta in events:
        for name, value in meta.get("stage_ms", {}).items():
            stage_samples.setdefault(name, []).append(float(value))
    stage_means = {name: round(sum(values) / len(values), 2)
                   for name, values in stage_samples.items()}
    print(json.dumps({"mode": args.mode, "video": args.video, "duration_s": round(duration, 2),
                      "delivered_fps": round(len(events) / max(duration, .001), 2),
                      "capture_fps": last.get("capture_fps"), "detector_hz": last.get("detector_hz_actual"),
                      "lane_hz": last.get("lane_hz_actual"), "device": last.get("device"),
                      "input_size": last.get("input_size"), "detector_target_hz": cfg["detector"]["update_hz"],
                      "lane_target_hz": cfg["lane"]["update_hz"], "stage_ms_mean": stage_means,
                      "errors": errors}, ensure_ascii=False))
    if errors or not events:
        sys.exit(1)


if __name__ == "__main__":
    main()
