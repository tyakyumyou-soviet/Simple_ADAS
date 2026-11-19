"""前後カメラの連続録画サービス。標準入力でE/A/Fを受け付ける。"""
from __future__ import annotations

import argparse
import csv
import fcntl
import re
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from event_coordinator import EventCoordinator
from recording_store import RecordingStore
from segment_capture import SegmentCapture
from transfer_service import finalized
from preview_writer import PreviewWriter
from lens_settings import lens_from_environment


def default_microphone() -> str:
    pactl = shutil.which('pactl')
    if not pactl:
        raise RuntimeError('マイクの検出に必要なpactlが見つかりません')
    try:
        result = subprocess.run([pactl, 'get-default-source'], capture_output=True,
                                text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('マイクの取得に失敗しました') from exc
    source = result.stdout.strip()
    if not source or source.endswith('.monitor') or source in {'auto_null', '@DEFAULT_MONITOR@'}:
        raise RuntimeError('使用できるマイクが検出されません')
    return source


class DashcamService:
    def __init__(self, root: Path, devices: dict[str, str], *, segment_seconds: float = 600,
                 fps: float = 30, size: str = '1280x720', preview_dir: Path | None = None,
                 test_source: bool = False, audio_source: str | None = None,
                 video_role: str | None = None, video_path: Path | None = None):
        self.store = RecordingStore(root)
        self.devices = devices
        self.test_source = test_source
        self.video_role = video_role
        self.stop_requested = threading.Event()
        self.video_finished = threading.Event()
        self.errors = queue.Queue()
        self.frames = {role: threading.Event() for role in ('front', 'rear')}
        self.preview_dir = Path(preview_dir) if preview_dir else None
        self.preview_writer = None
        self._print_lock = threading.Lock()
        self.captures = {}
        self.coordinator = None
        if test_source:
            audio_args = None
        else:
            source = audio_source or default_microphone()
            if source.endswith('.monitor'):
                raise RuntimeError('スピーカーのモニターはマイクとして使用できません')
            audio_args = ['-f', 'pulse', '-channels', '1', '-sample_rate', '48000',
                          '-fragment_size', '960', '-i', source]
        if video_role not in (None, 'front', 'rear') or bool(video_role) != bool(video_path):
            raise ValueError('動画入力の設定が不正です')
        if video_path and not Path(video_path).is_file():
            raise ValueError('動画ファイルが見つかりません')
        for role in ('front', 'rear'):
            role_width = int(os.environ.get('ADAS_' + role.upper() + '_WIDTH', size.split('x')[0]))
            role_height = int(os.environ.get('ADAS_' + role.upper() + '_HEIGHT', size.split('x')[1]))
            role_fps = float(os.environ.get('ADAS_' + role.upper() + '_FPS', fps))
            role_format = os.environ.get('ADAS_' + role.upper() + '_FORMAT', 'mjpeg')
            if test_source:
                role_width, role_height = map(int, size.split('x'))
                role_fps = fps
            if role == video_role:
                args = ['-re', '-i', str(video_path)]
            elif test_source:
                args = ['-re', '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={fps}']
            else:
                args = ['-f', 'v4l2', '-input_format', role_format, '-framerate', str(role_fps),
                        '-video_size', f'{role_width}x{role_height}', '-i', devices[role]]
            self.captures[role] = SegmentCapture(
                self.store.root / role / 'continuous', args,
                lambda segment, role=role: self._finished(role, segment),
                lambda error, role=role: self._failed(role, error), role=role,
                segment_seconds=segment_seconds, fps=role_fps,
                on_preview=lambda image, role=role: self._preview(role, image), preview_fps=min(role_fps, 30),
                audio_args=audio_args, wallclock_input=not test_source and role != video_role,
                preview_width=int(os.environ.get("ADAS_PREVIEW_WIDTH", "320")),
                    lens_correction=lens_from_environment(role, os.environ) if role != video_role else None,
                    expected_eof=role == video_role, on_eof=self.video_finished.set)
        self.coordinator = EventCoordinator(self.store, self.captures, self.message,
                                            on_fatal=lambda reason: self._failed('storage', reason))

    def message(self, text: str) -> None:
        with self._print_lock:
            print(text, flush=True)

    def _preview(self, role: str, image: bytes) -> None:
        self.frames[role].set()
        if self.preview_writer:
            self.preview_writer.write(role, image)

    def _finished(self, role, segment):
        self.message(f'[{role}録画完了] {segment.path}')
        self.coordinator.segment_finished(role, segment)

    def _failed(self, role, reason):
        self.errors.put(f'{role}: {reason}')
        self.stop_requested.set()

    def _commands(self):
        for line in sys.stdin:
            parts = line.strip().upper().split()
            if not parts:
                continue
            command = parts[0]
            if command in ('F', 'STOP'):
                self.stop_requested.set()
                return
            if command in ('E', 'MANUAL', 'A', 'ACCIDENT'):
                try:
                    if len(parts) > 2:
                        raise ValueError('発生時刻の形式が不正です')
                    stamp = int(parts[1]) if len(parts) == 2 else time.time_ns()
                    event = self.coordinator.trigger('event' if command in ('A', 'ACCIDENT') else 'manual', trigger_ns=stamp)
                    self.message(f'[イベント受付] {event}')
                except Exception as exc:
                    self.message(f'[イベント受付失敗] {exc}')
        self.stop_requested.set()

    def _recover_finalized(self) -> dict[str, list[Path]]:
        """完成一覧に登録済みかつMP4確定済みの過去ラップのみ復元する。"""
        result = {role: [] for role in ('front', 'rear')}
        for role in ('front', 'rear'):
            directory = self.store.root / role / 'continuous'
            for listing in directory.glob(f'.{role}_*.csv'):
                if listing.is_symlink():
                    self.message(f'[録画復元警告] 不正な一覧: {listing.name}')
                    continue
                prefix = listing.name[1:-4]
                if not re.fullmatch(role + r'_\d+_[0-9a-f]{12}', prefix):
                    continue
                try:
                    with listing.open(newline='', encoding='utf-8') as source:
                        rows = list(csv.reader(source))
                except (OSError, csv.Error) as exc:
                    self.message(f'[録画復元警告] {listing.name}: {exc}')
                    continue
                for row in rows:
                    if len(row) != 3 or not re.fullmatch(re.escape(prefix) + r'_\d{9}\.mp4', row[0]):
                        continue
                    path = directory / row[0]
                    if not path.is_symlink() and path.is_file() and finalized(path):
                        result[role].append(path)
            # 旧録画アプリが作った確定済みラップも容量管理に含める。
            for path in directory.glob(role + '_video_*.mp4'):
                if (re.fullmatch(role + r'_video_\d{8}_\d{6}\.mp4', path.name)
                        and not path.is_symlink() and path.is_file() and finalized(path)):
                    result[role].append(path)
        return result

    def run(self) -> int:
        if not shutil.which('ffmpeg'):
            raise RuntimeError('ffmpegが見つかりません')
        if not self.test_source and any(not self.devices.get(role) and role != self.video_role
                                        for role in ('front', 'rear')):
            raise RuntimeError('前後のカメラを指定してください')
        threads = threading.Thread(target=self._commands, name='dashcam-commands', daemon=True)
        lock_path = self.store.state_dir / 'service.lock'
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        lock_fd = os.open(lock_path, flags, 0o600)
        acquired = False
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError as exc:
                raise RuntimeError('録画サービスは既に起動しています') from exc
            if self.preview_dir:
                self.preview_writer = PreviewWriter(self.preview_dir)
            imported = self.store.import_complete_legacy_events()
            if imported:
                self.message(f'[録画復元] 旧形式のイベント {len(imported)} 件を容量管理に引き継ぎました')
            self.coordinator.recover(self._recover_finalized())
            for role in ('front', 'rear'):
                capture = self.captures[role]
                first = capture.directory / f'{capture.session}_000000000.mp4'
                moved = self.store.rebind_missing_next(role, first)
                if moved:
                    self.message(f'[イベント復旧] {role}: 録画停止を挟んだ次ラップの予約 {len(moved)} 件を再開します')
            for role in ('front', 'rear'):
                self.captures[role].start()
            threads.start()
            announced = set()
            startup_deadline = time.monotonic() + 20
            while not self.stop_requested.wait(0.1):
                if self.video_finished.is_set(): break
                for role in ('front', 'rear'):
                    if role not in announced and self.frames[role].is_set():
                        label = 'フロント' if role == 'front' else 'リア'
                        self.message(f'[{label}録画開始] 最初のフレームを受信しました')
                        announced.add(role)
                if len(announced) != 2 and time.monotonic() >= startup_deadline:
                    self.errors.put('前後カメラの最初のフレームを取得できません')
                    self.stop_requested.set()
        finally:
            for role, capture in self.captures.items():
                try:
                    capture.stop()
                except Exception as exc:
                    self.errors.put(f'{role}録画停止失敗: {exc}')
            self.coordinator.close()
            os.close(lock_fd)
            if acquired and self.preview_writer:
                try:
                    self.preview_writer.close()
                except OSError as exc:
                    self.errors.put(f'プレビュー片付け失敗: {exc}')
        if not self.errors.empty():
            while not self.errors.empty():
                self.message('[録画エラー] ' + self.errors.get())
            return 1
        if self.video_finished.is_set() and not self.stop_requested.is_set():
            self.message('[動画検証終了] ファイルの末尾です')
        self.message('[ドラレコ] 停止しました')
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--media-dir', type=Path, default=Path(os.environ.get('DASHCAM_MEDIA_DIR', 'videos')))
    parser.add_argument('--segment-seconds', type=float, default=600)
    parser.add_argument('--fps', type=float, default=30)
    parser.add_argument('--size', default='1280x720')
    parser.add_argument('--preview-dir', type=Path)
    parser.add_argument('--audio-source', default=None)
    parser.add_argument('--test-source', action='store_true')
    args = parser.parse_args()
    devices = {'front': os.environ.get('FRONT_DEVICE', ''), 'rear': os.environ.get('REAR_DEVICE', '')}
    if not args.test_source:
        if not all(Path(device).exists() for device in devices.values() if device) or not all(devices.values()):
            print('[録画エラー] 前後カメラを確認してください', flush=True)
            return 1
        if Path(devices['front']).resolve() == Path(devices['rear']).resolve():
            print('[録画エラー] 前後には別のカメラが必要です', flush=True)
            return 1
    try:
        service = DashcamService(args.media_dir, devices, segment_seconds=args.segment_seconds,
                                 fps=args.fps, size=args.size, preview_dir=args.preview_dir,
                                 test_source=args.test_source, audio_source=args.audio_source,
                                 video_role=os.environ.get("VIDEO_ROLE") or None,
                                 video_path=Path(os.environ["VIDEO_PATH"]) if os.environ.get("VIDEO_PATH") else None)
        return service.run()
    except Exception as exc:
        print(f'[録画エラー] {exc}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
