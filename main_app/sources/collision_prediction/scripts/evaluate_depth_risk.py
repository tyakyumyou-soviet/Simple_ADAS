"""Local-only ON/OFF runtime comparison; not an accuracy or safety benchmark."""
from __future__ import annotations

import argparse
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import Pipeline
from src.utils.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video')
    parser.add_argument('--config', default='config/pi_async_ai_hat.yaml')
    parser.add_argument('--start', type=float, default=0.)
    parser.add_argument('--frames', type=int, default=90)
    parser.add_argument('--interval', type=float, default=.2)
    parser.add_argument('--output', required=True)
    parser.add_argument('--preview', help='Optional local PNG of the last depth-ON frame')
    args = parser.parse_args()
    if args.frames < 1 or args.interval <= 0 or args.start < 0:
        parser.error('frames/interval must be positive and start nonnegative')
    cfg = load_config(args.config)
    cap = cv2.VideoCapture(args.video)
    frames = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.
        first = int(args.start*fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        for _ in range(args.frames):
            ok, frame = cap.read()
            if not ok:
                break
            width = int(cfg.get('ui', {}).get('max_process_width', 320)) or frame.shape[1]
            frames.append(cv2.resize(frame, (width, max(1, round(frame.shape[0]*width/frame.shape[1])))))
    finally:
        cap.release()
    if not frames:
        raise RuntimeError('No video frames could be read')
    reports = []
    for enabled in (False, True):
        settings = deepcopy(cfg)
        settings.setdefault('hailo_scene', {}).update(depth_enabled=enabled, depth_update_hz=1/args.interval)
        settings.setdefault('ui', {}).update(independent_schedule=True, show_ai_depth_preview=enabled)
        pipeline = Pipeline(settings)
        samples = []
        started = time.perf_counter()
        try:
            for i, frame in enumerate(frames):
                _, meta = pipeline.process(frame, first+i, fps, timestamp=(first+i)/fps, render=False)
                samples.append({key: meta.get(key) for key in (
                    'timestamp', 'risk_mode', 'device', 'ai_depth_status', 'ai_depth_error',
                    'ai_depth_age_s', 'hailo_depth_ms', 'ai_depth_analysis_ms', 'process_ms', 'stage_ms')})
                samples[-1]['regions'] = meta.get('ai_depth_regions', [])
                samples[-1]['alerts'] = [{'kind': a.kind, 'level': a.level, 'direction': a.direction,
                                          'target_id': a.target_id, 'message': a.message} for a in meta['alerts']]
            elapsed = time.perf_counter()-started
            if enabled and args.preview:
                image = pipeline.renderer.render(meta['_render_context'], meta['alerts'], meta)
                if not cv2.imwrite(args.preview, image):
                    raise RuntimeError('Could not save preview')
        finally:
            pipeline.close()
        cpu = [s['ai_depth_analysis_ms'] for s in samples]
        processing = [s['process_ms'] for s in samples]
        reasons = Counter(region.get('reason', '不明') for sample in samples for region in sample['regions'])
        warning_frames = sum(any(a['kind'] == 'ai_depth_obstacle' for a in sample['alerts']) for sample in samples)
        depth_ages = [s['ai_depth_age_s'] for s in samples if s['ai_depth_age_s'] is not None]
        report = {'depth_enabled': enabled, 'frames': len(samples), 'elapsed_s': elapsed,
                  'processing_fps_without_display': len(samples)/elapsed,
                  'process_ms_p50_p95': np.percentile(processing, [50, 95]).tolist(),
                  'depth_cpu_ms_p50_p95': np.percentile(cpu, [50, 95]).tolist(),
                  'depth_age_s_p50_p95': np.percentile(depth_ages, [50, 95]).tolist() if depth_ages else None,
                  'unknown_warning_frames': warning_frames, 'region_reason_frames': dict(reasons),
                  'samples': samples}
        reports.append(report)
    Path(args.output).write_text(json.dumps({'interval_s': args.interval, 'source_fps': fps,
        'note': 'Local video runtime smoke only; no obstacle ground truth; no measured detection accuracy.',
        'reports': reports}, ensure_ascii=False, indent=2), encoding='utf-8')
    on = reports[1]['samples']
    if any(s['ai_depth_error'] for s in on) or not any(s['hailo_depth_ms'] is not None for s in on):
        raise RuntimeError('Depth HEF inference failed; see output report')
    if not all(s['device'] == 'Hailo-8' for s in on):
        raise RuntimeError('Detector did not consistently use Hailo-8')
    print(json.dumps([{key: value for key, value in report.items() if key != 'samples'}
                      for report in reports], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
