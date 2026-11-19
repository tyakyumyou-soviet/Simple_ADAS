"""連続録画の完成通知とイベント保護予約を結び付ける。"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from recording_store import RecordingStore, ROLES, StoreError
from segment_capture import Segment, SegmentCapture


class EventCoordinator:
    def __init__(self, store: RecordingStore, captures: dict[str, SegmentCapture],
                 notify: Callable[[str], None], on_fatal: Callable[[str], None] | None = None):
        if set(captures) != set(ROLES):
            raise ValueError("前後両方の録画セッションが必要です")
        self.store = store
        self.captures = captures
        self.notify = notify
        self.on_fatal = on_fatal
        self._lock = threading.RLock()
        self._queued = set()
        self._finalized = {role: set() for role in ROLES}
        self._cleanup_queued = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-save")
        self._closed = False

    @staticmethod
    def _neighbour(capture: SegmentCapture, current: Path, delta: int) -> Path | None:
        match = re.fullmatch(re.escape(capture.session) + r"_(\d{9})\.mp4", current.name)
        if not match:
            raise StoreError("現在のラップ名が不正です")
        number = int(match.group(1)) + delta
        if number < 0:
            return None
        if number > 999_999_999:
            raise StoreError("録画ラップ番号の上限です")
        return current.with_name(f"{capture.session}_{number:09d}.mp4")

    def trigger(self, kind: str, *, trigger_ns: int | None = None) -> str:
        if kind not in ("manual", "event"):
            raise ValueError("不正なイベント種別")
        trigger_ns = time.time_ns() if trigger_ns is None else int(trigger_ns)
        now_wall_ns = time.time_ns()
        now_monotonic_ns = time.monotonic_ns()
        if trigger_ns > now_wall_ns + 100_000_000:
            raise StoreError("イベント時刻が現在より未来です")
        with self._lock:
            if self._closed:
                raise StoreError("録画は停止しています")
            sources = {}
            for role, capture in self.captures.items():
                if capture.started_wall_ns is None or capture.started_monotonic_ns is None:
                    raise StoreError(f"{role}録画の開始時刻を確認できません")
                expected_wall = capture.started_wall_ns + (now_monotonic_ns - capture.started_monotonic_ns)
                if abs(now_wall_ns - expected_wall) > 500_000_000:
                    raise StoreError("システム時刻の変化を検出したため、イベントのラップを確定できません")
                segments = capture.completed_segments()
                completed = {segment.path for segment in segments}
                current = None
                # CSVの境界は撮影フレームに付いた実時刻。終了時刻は次ラップの開始時刻。
                for index, segment in enumerate(segments):
                    start_ns = (getattr(capture, "input_start_ns", None) or capture.started_wall_ns) if index == 0 else int(round(segment.start * 1_000_000_000))
                    end_ns = int(round(segment.end * 1_000_000_000))
                    if start_ns <= trigger_ns < end_ns:
                        current = segment.path
                        break
                if current is None:
                    latest_end = (int(round(segments[-1].end * 1_000_000_000))
                                  if segments else (getattr(capture, "input_start_ns", None) or capture.started_wall_ns))
                    if trigger_ns < latest_end:
                        raise StoreError(f"{role}のイベント時刻に対応するラップがありません")
                    current = capture.current_segment_path()
                    if current is None:
                        raise StoreError(f"{role}の現在ラップを確認できません。録画状態を確認してください")
                previous = self._neighbour(capture, current, -1)
                if previous not in completed:
                    previous = None
                following = self._neighbour(capture, current, 1)
                sources[role] = {"previous": previous, "current": current, "next": following}
            event_id = self.store.begin_event_with_sources(kind, sources, trigger_ns)
            # 発生と境界の競合でこの間に確定したラップも取りこぼさない。
            for capture in self.captures.values():
                for segment in capture.completed_segments():
                    self._schedule_clip(segment.path)
            self.notify(f"イベント保存予約: {event_id}")
            return event_id

    def segment_finished(self, role: str, segment: Segment) -> None:
        if role not in self.captures:
            raise ValueError("不正なカメラ")
        with self._lock:
            if self._closed:
                return
            self._finalized[role].add(segment.path)
            self._schedule_clip(segment.path)
            self._schedule_cleanup()

    def recover(self, finalized: dict[str, list[Path]]) -> None:
        """前回の正常確定済みラップを復元し、未処理の予約を再試行する。"""
        with self._lock:
            if self._closed:
                raise StoreError("録画は停止しています")
            for role in ROLES:
                for path in finalized.get(role, []):
                    path = Path(path)
                    if path.is_file():
                        self._finalized[role].add(path)
                        self._schedule_clip(path)
            self._schedule_cleanup()

    def _schedule_cleanup(self) -> None:
        if not self._cleanup_queued:
            self._cleanup_queued = True
            self._pool.submit(self._cleanup)

    def _cleanup(self) -> None:
        try:
            with self._lock:
                # 各カメラの直近完成ラップは、直後のイベントの前ラップとして残す。
                existing = {role: {path for path in self._finalized[role] if path.is_file()} for role in ROLES}
                protected = set()
                for paths in existing.values():
                    if paths:
                        protected.add(max(paths, key=lambda path: (path.stat().st_mtime_ns, str(path))))
                deleted = self.store.cleanup_continuous(
                    [path for paths in existing.values() for path in paths], active=protected)
                for paths in self._finalized.values():
                    paths.difference_update(deleted)
        except Exception as exc:
            message = f"通常録画の容量整理失敗: {exc}"
            self.notify(message)
            if self.on_fatal is not None:
                self.on_fatal(message)
        finally:
            with self._lock:
                self._cleanup_queued = False

    def _schedule_clip(self, path: Path) -> None:
        for item in self.store.events_for_completed_clip(path):
            if item in self._queued:
                continue
            self._queued.add(item)
            self._pool.submit(self._copy, item)

    def _copy(self, item: tuple[str, str, str]) -> None:
        event_id, role, slot = item
        try:
            self.store.copy_reserved(event_id, role, slot)
            state = self.store.settle_event(event_id)
            if state == "complete":
                self.notify(f"イベント保存完了: {event_id}")
            elif state == "incomplete":
                self.notify(f"イベント保存は一部欠落: {event_id}")
        except Exception as exc:
            self.notify(f"イベント保存失敗 {event_id} {role}/{slot}: {exc}")
        finally:
            with self._lock:
                self._queued.discard(item)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=True)
