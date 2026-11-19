"""録画サービスが分配した最新フレームで既存の危険予知を実行する。"""
from __future__ import annotations

from types import SimpleNamespace
from collections import deque
import argparse
import dataclasses
import json
import os
import sys
import threading
import tempfile
import time
from pathlib import Path

from alert_adapter import adapt_alert
from shared_frame import RawFrame, read_frame, write_frame


def source_clock_discontinuity(previous_source_ns, source_ns, previous_monotonic_ns,
                               monotonic_ns, tolerance_ns=500_000_000):
    """V4L2取得時計の後退・大きな段差を単調時計と照合する。"""
    if previous_source_ns is None or previous_monotonic_ns is None:
        return False
    source_delta = source_ns - previous_source_ns
    monotonic_delta = monotonic_ns - previous_monotonic_ns
    return source_delta <= 0 or abs(source_delta - monotonic_delta) > tolerance_ns


class AdasService:
    def __init__(self, project: Path, config: Path, frame_dir: Path, initial_camera='front', overlay=False, overrides=None):
        self.project = project.resolve()
        self.config = config.resolve()
        self.frame_dir = frame_dir.resolve()
        self.overrides = overrides
        self._overlay = overlay
        self._camera = initial_camera
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._output_lock = threading.Lock()
        self._latest_render = None

    def emit(self, data: dict) -> None:
        with self._output_lock:
            print('ADAS_JSON ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')), flush=True)

    def commands(self) -> None:
        for line in sys.stdin:
            command = line.strip().upper()
            if command in ('STOP', 'Q'):
                self._stop.set()
                return
            if command in ('OVERLAY_ON', 'OVERLAY_OFF'):
                with self._lock:
                    self._overlay = command == 'OVERLAY_ON'
            if command in ('FRONT', 'REAR'):
                with self._lock:
                    self._camera = command.lower()
        self._stop.set()

    def _render_latest(self, cfg) -> None:
        """最新映像へ鮮度内の解析結果を重ね、解析処理と独立して表示する。"""
        import cv2
        import numpy as np
        from dataclasses import replace
        renderer = None
        max_age_ns = max(50, int(cfg.get('ui', {}).get('result_max_age_ms', 500))) * 1_000_000
        previous_key = None
        logged_error = False
        while not self._stop.is_set():
            with self._lock:
                role, enabled, result = self._camera, self._overlay, self._latest_render
            if not enabled or not result or result[0] != role:
                previous_key = None
                self._stop.wait(.01)
                continue
            _, result_time, context, meta = result
            if time.time_ns() - result_time > max_age_ns:
                self._stop.wait(.01)
                continue
            try:
                if renderer is None:
                    from src.render.renderer import Renderer
                    renderer = Renderer()
                    renderer.overlay_scale = float(cfg.get('ui', {}).get('overlay_size_scale', 1.0))
                shared = read_frame(self.frame_dir / (role + '.frame'))
                key = (role, shared.sequence, shared.timestamp_ns)
                if key == previous_key:
                    self._stop.wait(.002)
                    continue
                if time.time_ns() - shared.timestamp_ns > 1_000_000_000:
                    self._stop.wait(.01)
                    continue
                image = shared.bgr()
                height, width = context.enhanced.shape[:2]
                image = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
                ctx = replace(context, image=image, enhanced=image)
                rendered = renderer.render(ctx, meta.get('alerts', []), meta)
                rgb = cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB)
                with self._lock:
                    if role == self._camera and self._overlay and time.time_ns() - result_time <= max_age_ns:
                        write_frame(self.frame_dir / (role + '.adas.frame'),
                                    RawFrame(rgb.shape[1], rgb.shape[0], rgb.tobytes(), shared.timestamp_ns, shared.sequence))
                previous_key = key
                logged_error = False
            except (OSError, ValueError, TypeError, ImportError, cv2.error) as exc:
                if not logged_error:
                    print('[描画エラー] ' + str(exc), flush=True)
                    logged_error = True
                self._stop.wait(.03)

    def run(self) -> int:
        sys.path.insert(0, str(self.project))
        os.chdir(self.project)
        import cv2
        import numpy as np
        from src.pipeline import Pipeline
        from src.utils.config import load_config, deep_merge
        from src.utils.frame import resize_for_processing

        cfg = load_config(self.config)
        if self.overrides and self.overrides.exists():
            with self.overrides.open(encoding="utf-8") as handle:
                cfg = deep_merge(cfg, json.load(handle))
        threading.Thread(target=self.commands, name='adas-commands', daemon=True).start()
        render_thread = threading.Thread(target=self._render_latest, args=(cfg,), name='adas-render', daemon=True)
        render_thread.start()
        pipeline = None
        current_role = None
        last_key = None
        last_frame_time = time.monotonic()
        stale_announced = False
        result_stale_announced = False
        frame_count = 0
        started = time.monotonic()
        source_times = deque(maxlen=60)
        source_origin_ns = None
        last_source_ns = last_receive_monotonic_ns = None
        try:
            while not self._stop.is_set():
                with self._lock:
                    role = self._camera
                    overlay = self._overlay
                if role != current_role:
                    with self._lock:
                        self._latest_render = None
                    self.emit({'type': 'status', 'camera': role, 'status': 'switching', 'alerts': []})
                    if pipeline is not None:
                        pipeline.close()
                    pipeline = Pipeline(cfg)
                    current_role = role
                    last_key = None
                    last_frame_time = time.monotonic()
                    stale_announced = False
                    frame_count = 0
                    started = time.monotonic()
                    source_times.clear()
                    source_origin_ns = None
                    last_source_ns = last_receive_monotonic_ns = None
                path = self.frame_dir / (role + '.frame')
                try:
                    shared = read_frame(path)
                    stat = SimpleNamespace(st_mtime_ns=shared.timestamp_ns)
                    key = (shared.sequence, shared.timestamp_ns)
                    if key == last_key:
                        if time.monotonic() - last_frame_time > 2 and not stale_announced:
                            self.emit({'type': 'status', 'camera': role, 'status': 'stale', 'alerts': []})
                            stale_announced = True
                        self._stop.wait(0.002)
                        continue
                    wall_delta_ns = time.time_ns() - stat.st_mtime_ns
                    if wall_delta_ns > 2_000_000_000 or wall_delta_ns < -250_000_000:
                        if not stale_announced:
                            self.emit({'type': 'status', 'camera': role, 'status': 'stale', 'alerts': [],
                                       'message': 'カメラの取得時刻と端末時刻が一致しません'})
                            stale_announced = True
                        self._stop.wait(0.05)
                        continue
                    frame = shared.bgr()
                except (OSError, ValueError):
                    if time.monotonic() - last_frame_time > 2 and not stale_announced:
                        self.emit({'type': 'status', 'camera': role, 'status': 'stale', 'alerts': []})
                        stale_announced = True
                    self._stop.wait(0.05)
                    continue
                if stale_announced:
                    # 中断前の追跡・危険判定を新しい映像に引き継がない。
                    self.emit({'type': 'status', 'camera': role, 'status': 'switching', 'alerts': []})
                    pipeline.close()
                    pipeline = Pipeline(cfg)
                    frame_count = 0
                    started = time.monotonic()
                    last_frame_time = started
                    last_key = None
                    stale_announced = False
                    source_times.clear()
                    source_origin_ns = None
                    last_source_ns = last_receive_monotonic_ns = None
                    continue
                receive_monotonic_ns = time.monotonic_ns()
                if source_clock_discontinuity(last_source_ns, stat.st_mtime_ns,
                                              last_receive_monotonic_ns, receive_monotonic_ns):
                    self.emit({'type': 'status', 'camera': role, 'status': 'switching', 'alerts': [],
                               'message': 'カメラの取得時計が変化したため危険予知を再初期化します'})
                    pipeline.close()
                    pipeline = Pipeline(cfg)
                    source_times.clear()
                    source_origin_ns = stat.st_mtime_ns
                    last_source_ns = stat.st_mtime_ns
                    last_receive_monotonic_ns = receive_monotonic_ns
                    frame_count = 0
                    last_key = key
                    last_frame_time = time.monotonic()
                    continue
                last_source_ns = stat.st_mtime_ns
                last_receive_monotonic_ns = receive_monotonic_ns
                last_key = key
                last_frame_time = time.monotonic()
                ui_cfg = cfg.get('ui', {})
                processed, _ = resize_for_processing(frame, int(ui_cfg.get('max_process_width', 0) or 0))
                display_width = int(ui_cfg.get('display_max_width', 0) or 0)
                display_size = ((display_width, max(1, round(display_width * frame.shape[0] / frame.shape[1])))
                                if display_width > 0 else (frame.shape[1], frame.shape[0]))
                # 処理開始時刻ではなく入力画像の時刻で更新周期・滞在時間を評価する。
                if source_origin_ns is None:
                    source_origin_ns = stat.st_mtime_ns
                if not source_times or stat.st_mtime_ns > source_times[-1]:
                    source_times.append(stat.st_mtime_ns)
                elapsed = (source_times[-1] - source_times[0]) / 1e9
                source_fps = ((len(source_times)-1)/elapsed if elapsed > 0 else
                              float(cfg.get('input', {}).get('camera_fps', 30) or 30))
                analysis_started_ns = time.time_ns()
                _, meta = pipeline.process(processed, frame_count, source_fps,
                                           display_size=display_size,
                                           timestamp=(stat.st_mtime_ns-source_origin_ns)/1e9, render=False)
                frame_count += 1
                # 解析中にカメラ切替が要求された場合、古い結果を表示しない。
                with self._lock:
                    if role != self._camera:
                        continue
                    publish_overlay = overlay and self._overlay
                source_age_ms = max(0.0, (time.time_ns() - stat.st_mtime_ns) / 1_000_000)
                max_age_ms = max(50, int(ui_cfg.get('result_max_age_ms', 500)))
                if source_age_ms > max_age_ms:
                    if not result_stale_announced:
                        self.emit({'type': 'status', 'camera': role, 'status': 'stale', 'alerts': []})
                        result_stale_announced = True
                    continue
                result_stale_announced = False
                if publish_overlay and meta.get('_render_context') is not None:
                    with self._lock:
                        if role == self._camera and self._overlay:
                            self._latest_render = (role, stat.st_mtime_ns, meta['_render_context'], meta)
                classes = {track.track_id: track.cls for track in meta.get('tracks', [])}
                alerts = [dataclasses.asdict(adapt_alert(alert, classes, reverse_view=role == 'rear'))
                          for alert in meta.get('alerts', [])]
                self.emit({'type': 'result', 'camera': role, 'status': 'running',
                           'alerts': alerts, 'track_count': len(classes), 'device': str(meta.get('device', 'unknown')),
                           'process_ms': float(meta.get('process_ms', 0)),
                           'source_age_ms': source_age_ms,
                           'source_time_ns': stat.st_mtime_ns,
                           'emitted_time_ns': time.time_ns(),
                           'analysis_ms': (time.time_ns()-analysis_started_ns)/1e6,
                           'blind': bool(meta.get('blind', False)),
                           'blind_reason': meta.get('blind_reason'),
                           'enhancement': meta.get('enhancement', {}),
                           'input_to_analysis_ms': max(0, (analysis_started_ns-stat.st_mtime_ns)/1e6),
                           'source_fps': source_fps,
                           'input_size': [frame.shape[1], frame.shape[0]],
                           'process_size': [processed.shape[1], processed.shape[0]],
                           'display_size': list(display_size),
                           'detector_runs': meta.get('detector_runs', 0),
                           'lane_runs': meta.get('lane_runs', 0),
                           'stage_ms': meta.get('stage_ms', {})})
            return 0
        finally:
            self._stop.set()
            render_thread.join(timeout=3)
            if pipeline is not None:
                pipeline.close()
            self.emit({'type': 'status', 'camera': current_role, 'status': 'stopped', 'alerts': []})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--frame-dir', type=Path, required=True)
    parser.add_argument('--camera', choices=('front', 'rear'), default='front')
    parser.add_argument('--overlay', action='store_true')
    parser.add_argument('--overrides', type=Path)
    args = parser.parse_args()
    try:
        return AdasService(args.project, args.config, args.frame_dir, args.camera, args.overlay, args.overrides).run()
    except Exception as exc:
        print('ADAS_JSON ' + json.dumps({'type': 'error', 'message': str(exc), 'alerts': []}, ensure_ascii=False), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
