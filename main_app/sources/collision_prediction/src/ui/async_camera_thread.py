"""Independent live preview and bounded, single-worker analysis for a camera."""
from __future__ import annotations

import threading
import time
from copy import deepcopy
from dataclasses import replace
from collections import deque

import cv2

from src.pipeline import Pipeline, empty_lane_info
from src.enhancement.enhancer import FrameEnhancer
from src.input.camera import CameraSource
from src.render.renderer import Renderer
from src.ui.inference_thread import InferenceThread
from src.utils.frame import resize_for_processing


class AsyncCameraThread(InferenceThread):
    def __init__(self, source, cfg):
        super().__init__(source, cfg)
        self._condition = threading.Condition()
        self._pending_frame = None
        self._result = None
        self._worker_error = None
        self._ui_pending = False
        self._worker = None
        self._submitted = self._replaced = 0
        self._detector_times = deque(maxlen=60)
        self._lane_times = deque(maxlen=60)
        self._display_times = deque(maxlen=60)
        self._generation = 0

    def _analyse(self):
        pipeline = None
        try:
            pipeline = Pipeline(deepcopy(self.cfg))
            pipeline_generation = 0
            while True:
                with self._condition:
                    while self._running and (self._pending_frame is None or self._paused):
                        self._condition.wait(timeout=0.1)
                    if not self._running:
                        break
                    frame, capture_time, sequence, generation = self._pending_frame
                    self._pending_frame = None
                    settings = self._pending_settings
                    self._pending_settings = None
                if generation != pipeline_generation:
                    pipeline.close()
                    pipeline = Pipeline(deepcopy(self.cfg))
                    pipeline_generation = generation
                    self._detector_times.clear()
                    self._lane_times.clear()
                    self._seen_detector = self._seen_lane = 0
                if settings is not None:
                    scene_cfg = settings.get('hailo_scene', {})
                    legacy = bool(scene_cfg.get('enabled', False))
                    new_depth = bool(scene_cfg.get('depth_enabled', legacy))
                    if new_depth != pipeline.hailo_depth_enabled:
                        pipeline.close()
                        pipeline = None
                        with self._condition:
                            self._result = None
                        self._detector_times.clear()
                        self._lane_times.clear()
                        self._seen_detector = self._seen_lane = 0
                        pipeline = Pipeline(settings)
                    else:
                        pipeline.update_settings(settings)
                ui = self.cfg.get('ui', {})
                process_frame, _ = resize_for_processing(frame, int(ui.get('max_process_width', 0) or 0))
                display_width = int(ui.get('display_max_width', 0) or 0) or frame.shape[1]
                display_size = (display_width, max(1, int(display_width * frame.shape[0] / frame.shape[1])))
                effective_fps = self.source.measured_fps or self.source.fps
                _, meta = pipeline.process(process_frame, sequence - 1, effective_fps,
                                           display_size=display_size, timestamp=capture_time, render=False)
                for key, counter, times in (('detector_runs', '_seen_detector', self._detector_times),
                                             ('lane_runs', '_seen_lane', self._lane_times)):
                    count = int(meta.get(key, 0))
                    if count > getattr(self, counter, 0):
                        times.append(capture_time)
                        setattr(self, counter, count)
                def rate(times):
                    return (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
                meta['detector_hz_actual'] = rate(self._detector_times)
                meta['lane_hz_actual'] = rate(self._lane_times)
                ctx = meta.pop('_render_context')
                # Data is detached from the mutable tracking state before it crosses threads.
                result = (capture_time, deepcopy(ctx), deepcopy(meta), tuple(process_frame.shape[:2][::-1]))
                with self._condition:
                    if generation == self._generation and not self._paused:
                        self._result = result
        except Exception as exc:
            with self._condition:
                self._worker_error = str(exc)
                self._running = False
                self._condition.notify_all()
        finally:
            if pipeline is not None:
                pipeline.close()

    def run(self):
        renderer = Renderer()
        preview_enhancer = FrameEnhancer()
        preview_enhancement_enabled = False
        next_display = 0.0
        try:
            self.source.open()
            self._worker = threading.Thread(target=self._analyse, name='camera-analysis', daemon=False)
            self._worker.start()
            while self._running:
                if self._paused:
                    self.msleep(20)
                    continue
                if self._seek_to is not None:
                    position = self._seek_to
                    self._seek_to = None
                    if self.source.seek(position):
                        with self._condition:
                            self._generation += 1
                            self._pending_frame = None
                            self._result = None
                ok, frame, captured, sequence = self.source.read_with_metadata()
                if not ok:
                    break
                now = time.monotonic()
                with self._condition:
                    if self._pending_frame is not None:
                        self._replaced += 1
                    self._pending_frame = (frame, captured, sequence, self._generation)
                    self._submitted += 1
                    self._condition.notify()
                    result = self._result
                    pending_ui = self._ui_pending
                    display_times = tuple(self._display_times)
                cfg = self.cfg.get('ui', {})
                display_fps = max(1.0, float(cfg.get('display_fps', 30)))
                display_every = max(1, int(cfg.get('display_every_n_frames', 1)))
                if pending_ui or now + 0.002 < next_display or (sequence - 1) % display_every:
                    continue
                width = int(cfg.get('display_max_width', 0) or 0) or frame.shape[1]
                display_size = (width, max(1, int(width * frame.shape[0] / frame.shape[1])))
                image = cv2.resize(frame, display_size, interpolation=cv2.INTER_LINEAR)
                enhancement_enabled = bool(cfg.get('enable_enhancement', False))
                if enhancement_enabled:
                    if not preview_enhancement_enabled:
                        preview_enhancer = FrameEnhancer()
                    image, _ = preview_enhancer.process(image)
                preview_enhancement_enabled = enhancement_enabled
                age_ms = (now - result[0]) * 1000 if result else None
                stale = result is None or age_ms > max(0, float(cfg.get('result_max_age_ms', 500)))
                render_started = time.perf_counter()
                if result and not stale:
                    ctx, meta, process_size = result[1:]
                    if ctx.enhanced.shape[:2] == image.shape[:2]:
                        renderer.overlay_scale = float(cfg.get('overlay_size_scale', 1.0))
                        ctx = replace(ctx, image=image, enhanced=image)
                        image = renderer.render(ctx, meta.get('alerts', []), meta)
                    else:
                        stale = True
                if stale:
                    meta = {'device': '解析待ち', 'alerts': [], 'lane_state': 'stale', 'lane_detected': False}
                    process_width = int(cfg.get('max_process_width', 0) or 0) or frame.shape[1]
                    process_size = (process_width, max(1, int(frame.shape[0] * process_width / frame.shape[1])))
                else:
                    meta = dict(meta)
                meta["preview_render_ms"] = (time.perf_counter() - render_started) * 1000.0
                meta["capture_to_emit_ms"] = max(0., (time.monotonic() - captured) * 1000.)
                actual_fps = ((len(display_times) - 1) / (display_times[-1] - display_times[0])
                              if len(display_times) > 1 and display_times[-1] > display_times[0] else 0.0)
                meta.update({'frame_idx': sequence - 1, 'input_size': (frame.shape[1], frame.shape[0]),
                             'process_size': process_size, 'display_size': display_size,
                             'fps': actual_fps, 'source_fps': self.source.fps,
                             'input_kind': 'camera' if isinstance(self.source, CameraSource) else 'video',
                             'camera_rate_kind': 'display',
                             'realtime_ratio': actual_fps / max(self.source.fps, 1.0),
                             'lag_percent': max(0.0, (1.0 - actual_fps / max(self.source.fps, 1.0)) * 100),
                             'avg_realtime_ratio': actual_fps / max(self.source.fps, 1.0),
                             'avg_lag_percent': max(0.0, (1.0 - actual_fps / max(self.source.fps, 1.0)) * 100),
                             'frame_count': self.source.frame_count, 'result_age_ms': age_ms, 'result_stale': stale,
                             '_generation': self._generation,
                             'capture_dropped_frames': self.source.dropped_frames,
                             'capture_fps': self.source.measured_fps,
                             'analysis_replaced_frames': self._replaced,
                             'camera_requested_size': (self.source.requested_width, self.source.requested_height)})
                with self._condition:
                    self._ui_pending = True
                self.frame_ready.emit(image, meta)
                next_display = max(next_display + 1.0 / display_fps, now)
        except Exception as exc:
            self._worker_error = str(exc)
        finally:
            self._running = False
            with self._condition:
                self._condition.notify_all()
            if self._worker is not None:
                self._worker.join()
            self.source.close()
            if self._worker_error:
                self.error.emit(self._worker_error)
            self.finished_signal.emit()

    def acknowledge_frame(self):
        with self._condition:
            self._display_times.append(time.monotonic())
            self._ui_pending = False

    def stop(self):
        self._running = False
        with self._condition:
            self._condition.notify_all()

    def pause(self):
        with self._condition:
            self._paused = True
            self._pending_frame = None
            self._result = None
            self._display_times.clear()
            if hasattr(self.source, 'pause_clock'):
                self.source.pause_clock()

    def resume(self):
        if hasattr(self.source, 'resume_clock'):
            self.source.resume_clock()
        self._paused = False
        with self._condition:
            self._condition.notify_all()

    def apply_settings(self, cfg):
        snapshot = deepcopy(cfg)
        with self._condition:
            self.cfg = snapshot
            self._pending_settings = snapshot
