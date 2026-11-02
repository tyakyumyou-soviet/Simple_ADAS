"""Run a video to EOF with bounded memory and report errors and throughput."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import Pipeline
from src.utils.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--config', default='config/pi_async_ai_hat.yaml')
    args = parser.parse_args()
    cfg = load_config(args.config)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError('Could not open video')
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.
    expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    pipeline = Pipeline(cfg)
    count = 0
    started = time.monotonic()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            width = int(cfg.get('ui', {}).get('max_process_width', 320)) or frame.shape[1]
            frame = cv2.resize(frame, (width, max(1, round(frame.shape[0] * width / frame.shape[1]))))
            _, meta = pipeline.process(frame, count, fps, timestamp=count/fps, render=True)
            if meta.get('ai_depth_error'):
                raise RuntimeError(meta['ai_depth_error'])
            count += 1
    finally:
        pipeline.close()
        cap.release()
    elapsed = time.monotonic() - started
    print(json.dumps({'frames': count, 'expected_frames': expected, 'elapsed_s': elapsed,
                      'processing_fps_with_render': count / elapsed}))
    if expected and count < expected - 1:
        raise RuntimeError('Video ended before the reported final frame')


if __name__ == '__main__':
    main()
