"""Check Hailo-8 YOLO and relative depth inference on the same video frames.

Run on a Pi with HailoRT and the required HEFs installed. The Hailo device must be
free. This diagnostic does not change app settings or make distance claims.
"""
from __future__ import annotations

import argparse
import json
import time
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--frames', type=int, default=12)
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.frames < 1:
        parser.error('--frames must be positive')
    from hailo_platform import (ConfigureParams, FormatType, HailoSchedulingAlgorithm,
                                HailoStreamInterface, HEF, InferVStreams,
                                InputVStreamParams, OutputVStreamParams, VDevice)
    cap = cv2.VideoCapture(args.video)
    frames = []
    try:
        while len(frames) < args.frames:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise RuntimeError('映像を読み込めませんでした')
    models = ['models/hailo8/yolo26n.hef', 'models/hailo8/scdepthv3.hef']
    if any(not Path(path).is_file() for path in models):
        raise FileNotFoundError('必要なHailoモデルがありません: ' + ', '.join(models))
    timings = [[] for _ in models]
    depth_ranges = []
    with ExitStack() as stack:
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
        device = stack.enter_context(VDevice(params))
        networks = []
        for path in models:
            hef = HEF(path)
            group = device.configure(hef, ConfigureParams.create_from_hef(hef, HailoStreamInterface.PCIe))[0]
            inputs = InputVStreamParams.make(group, format_type=FormatType.UINT8)
            outputs = OutputVStreamParams.make(group, format_type=FormatType.FLOAT32)
            infer = stack.enter_context(InferVStreams(group, inputs, outputs))
            networks.append((hef, infer))
        for frame in frames:
            for i, (hef, infer) in enumerate(networks):
                info = hef.get_input_vstream_infos()[0]
                h, w, _ = info.shape
                image = cv2.cvtColor(cv2.resize(frame, (w, h)), cv2.COLOR_BGR2RGB)
                start = time.perf_counter()
                result = infer.infer({info.name: image[None]})
                timings[i].append((time.perf_counter() - start) * 1000)
                if i == 1:
                    output = next(iter(result.values()))
                    if not np.isfinite(output).all():
                        raise ValueError('非有限の深度出力')
                    depth_ranges.append([float(output.min()), float(output.max())])
    report = {'video': args.video, 'frames': len(frames), 'models': [
        {'path': path, 'successful_inferences': len(t), 'mean_inference_ms': round(float(np.mean(t)), 2)}
        for path, t in zip(models, timings)], 'depth_output_ranges': depth_ranges,
        'note': '深度は相対値で、メートル単位の距離ではありません。'}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
