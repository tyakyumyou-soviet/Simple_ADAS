from __future__ import annotations

import time
from copy import deepcopy
from collections import deque
from typing import Any

import numpy as np
from PySide6.QtCore import QThread, Signal

from src.input.base import InputSource
from src.input.camera import CameraSource
from src.input.video_file import VideoFileSource
from src.pipeline import Pipeline
from src.utils.frame import resize_for_processing


class InferenceThread(QThread):
    """入力→解析→描画の素直なループ。毎フレーム解析し、結果（空でも空）を必ず反映する。"""

    frame_ready = Signal(np.ndarray, dict)
    error = Signal(str)
    finished_signal = Signal()

    def __init__(self, source: InputSource, cfg: dict[str, Any]):
        super().__init__()
        self.source = source
        self.cfg = deepcopy(cfg)
        self._running = True
        self._paused = False
        self._seek_to: int | None = None
        self._pending_settings: dict | None = None
        self._pipeline: Pipeline | None = None
        # 直近フレームのタイムスタンプを保持 → リアルタイム遅延率算出に使用
        self._recent_frames: deque[tuple[int, float]] = deque(maxlen=60)

    def run(self) -> None:
        pipeline = None
        try:
            self.source.open()
            pipeline = Pipeline(self.cfg)
            self._pipeline = pipeline

            frame_idx = 0
            source_fps = max(self.source.fps, 1.0)
            target_dt = 1.0 / source_fps
            started = time.perf_counter()
            displayed = 0
            pause_started = None
            average_started = None
            processed_frames = 0

            while self._running:
                if self._paused:
                    if pause_started is None:
                        pause_started = time.perf_counter()
                    self.msleep(20)
                    continue
                if pause_started is not None:
                    pause_duration = time.perf_counter() - pause_started
                    started += pause_duration
                    if average_started is not None:
                        average_started += pause_duration
                    pause_started = None
                if self._seek_to is not None:
                    if self.source.seek(self._seek_to):
                        frame_idx = self._seek_to
                        started = time.perf_counter() - frame_idx * target_dt
                        self._recent_frames.clear()
                    self._seek_to = None

                # Real-time video playback may skip old frames; full-frame mode never does.
                if isinstance(self.source, VideoFileSource) and self.cfg.get("input", {}).get("video_mode") == "realtime":
                    desired = int((time.perf_counter() - started) * source_fps)
                    if desired > frame_idx + 1:
                        if self.source.frame_count is not None:
                            desired = min(desired, self.source.frame_count - 1)
                        if self.source.seek(desired):
                            frame_idx = desired

                ok, frame = self.source.read()
                if not ok:
                    break
                capture_timestamp = getattr(self.source, "timestamp", None)

                # 設定変更がキューイングされていれば反映
                if self._pending_settings is not None:
                    settings = self._pending_settings
                    scene = settings.get("hailo_scene", {})
                    legacy = bool(scene.get("enabled", False))
                    depth_enabled = bool(scene.get("depth_enabled", legacy))
                    if depth_enabled != pipeline.hailo_depth_enabled:
                        pipeline.close()
                        pipeline = None
                        pipeline = Pipeline(settings)
                        self._pipeline = pipeline
                    else:
                        pipeline.update_settings(settings)
                    self._pending_settings = None

                # 処理解像度・表示間隔・表示解像度は self.cfg から毎フレーム読み取り（UI変更を即反映）
                ui_cfg = self.cfg.get("ui", {})
                max_process_width = int(ui_cfg.get("max_process_width", 0) or 0)
                display_every_n_frames = max(1, int(ui_cfg.get("display_every_n_frames", 1)))
                display_max_width = int(ui_cfg.get("display_max_width", 0) or 0)
                process_frame, scale = resize_for_processing(
                    frame, max_process_width
                )

                # display_size を計算: 指定なしなら元動画サイズ、指定ありならそれに合わせる
                if display_max_width > 0:
                    aspect = frame.shape[0] / frame.shape[1]
                    display_size = (display_max_width, max(1, int(display_max_width * aspect)))
                else:
                    display_size = (frame.shape[1], frame.shape[0])
                display, meta = pipeline.process(
                    process_frame, frame_idx, source_fps, display_size=display_size,
                    timestamp=capture_timestamp, render=(frame_idx % display_every_n_frames == 0),
                )

                # 直近フレームを記録（リアルタイム遅延率算出用）
                now = time.perf_counter()
                processed_frames += 1
                if average_started is None:
                    average_started = now
                self._recent_frames.append((frame_idx, now))
                meta = self._with_common_meta(
                    meta, frame_idx, frame, process_frame, scale,
                    source_fps, displayed, started, now, capture_timestamp,
                    processed_frames, average_started,
                )
                meta["display_size"] = (display.shape[1], display.shape[0])
                if isinstance(self.source, CameraSource):
                    meta["input_kind"] = "camera"
                    meta["camera_rate_kind"] = "processing"
                    meta["capture_fps"] = self.source.measured_fps
                if frame_idx % display_every_n_frames == 0:
                    self.frame_ready.emit(display, meta)
                    displayed += 1
                frame_idx += 1

                elapsed = time.perf_counter() - started
                sleep = frame_idx * target_dt - elapsed
                if sleep > 0:
                    self.msleep(int(sleep * 1000))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if pipeline is not None:
                pipeline.close()
            self.source.close()
            self.finished_signal.emit()

    def stop(self) -> None:
        self._running = False

    def apply_settings(self, cfg: dict[str, Any]) -> None:
        """UIから設定変更を通知する。次フレームで Pipeline に反映される。"""
        snapshot = deepcopy(cfg)
        self.cfg = snapshot
        self._pending_settings = snapshot

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def seek(self, frame_idx: int) -> None:
        self._seek_to = frame_idx

    @property
    def paused(self) -> bool:
        return self._paused

    def _with_common_meta(
        self,
        meta: dict[str, Any],
        frame_idx: int,
        frame: np.ndarray,
        process_frame: np.ndarray,
        scale: float,
        source_fps: float,
        displayed: int,
        started: float,
        now: float | None = None,
        capture_timestamp: float | None = None,
        processed_frames: int | None = None,
        average_started: float | None = None,
    ) -> dict[str, Any]:
        now = now if now is not None else time.perf_counter()
        elapsed = now - started
        # ---- リアルタイム遅延率: 直近 ~1 秒分のスライディングウィンドウで算出 ----
        # 累積 elapsed ベースだと過去の遅延を引きずるので、直近データだけで現在速度を測る
        recent = self._recent_frames
        if len(recent) >= 2:
            first_idx, first_t = recent[0]
            last_idx, last_t = recent[-1]
            dt = last_t - first_t
            d_frames = last_idx - first_idx
            current_fps = d_frames / dt if dt > 1e-6 else source_fps
        else:
            current_fps = displayed / max(elapsed, 1e-6)
        realtime_ratio = current_fps / max(source_fps, 1e-6)
        lag_percent = max(0.0, (1.0 - realtime_ratio) * 100.0)
        # 累積平均: 起動からの全 frame に対する平均速度
        average_elapsed = now - average_started if average_started is not None else 0.
        avg_realtime_ratio = ((processed_frames - 1) / average_elapsed / max(source_fps, 1e-6)
                              if processed_frames is not None and processed_frames > 1 and average_elapsed > 0 else None)
        avg_lag_percent = max(0.0, (1.0 - avg_realtime_ratio) * 100.0) if avg_realtime_ratio is not None else None
        meta.update(
            {
                "frame_idx": frame_idx,
                "input_size": (frame.shape[1], frame.shape[0]),
                "process_size": (process_frame.shape[1], process_frame.shape[0]),
                "process_scale": scale,
                "source_fps": source_fps,
                "fps": current_fps,
                "realtime_ratio": realtime_ratio,
                "lag_percent": lag_percent,
                "avg_realtime_ratio": avg_realtime_ratio,
                "avg_lag_percent": avg_lag_percent,
                "capture_dropped_frames": int(getattr(self.source, "dropped_frames", 0)),
                "frame_count": self.source.frame_count,
            }
        )
        if capture_timestamp is not None:
            # CameraSource timestamps are relative to open(), as is `started` here.
            meta["capture_timestamp"] = float(capture_timestamp)
            meta["frame_age_ms"] = max(0.0, (now - started - capture_timestamp) * 1000.0)
        return meta
