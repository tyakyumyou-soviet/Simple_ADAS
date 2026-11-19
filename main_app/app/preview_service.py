"""録画オフ時に、設定されたカメラから最新プレビューのみを配信する。"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
from pathlib import Path

from preview_writer import PreviewWriter
from lens_settings import lens_from_environment
from segment_capture import SegmentCapture


class PreviewService:
    def __init__(self, directory: Path, devices: dict[str, str], *, test_source=False, video_role=None, video_path=None):
        self.writer = PreviewWriter(directory)
        self.devices = devices
        self.test_source = test_source
        self.video_role = video_role
        self.video_path = Path(video_path).resolve() if video_path else None
        if video_role not in (None, "front", "rear") or bool(video_role) != bool(video_path):
            raise ValueError("動画入力の設定が不正です")
        if self.video_path and not self.video_path.is_file():
            raise ValueError("動画ファイルが見つかりません")
        self.stop_requested = threading.Event()
        self.video_finished = threading.Event()
        self.errors = queue.Queue()
        self.frames = {role: threading.Event() for role in ('front', 'rear')}
        self.captures = {}
        self.output_lock = threading.Lock()

    def emit(self, payload):
        with self.output_lock:
            print('PREVIEW_JSON ' + json.dumps(payload, ensure_ascii=False), flush=True)

    def _preview(self, role, data):
        self.writer.write(role, data)
        self.frames[role].set()

    def _error(self, role, message):
        self.errors.put((role, message))
        self.stop_requested.set()

    def _commands(self):
        for line in sys.stdin:
            if line.strip().upper() in ('STOP', 'F', 'Q'):
                self.stop_requested.set()
                return
        self.stop_requested.set()

    def run(self) -> int:
        try:
            active = {role: device for role, device in self.devices.items() if device}
            if self.video_role:
                active[self.video_role] = str(self.video_path)
            if self.test_source and not active:
                active = {'front': 'synthetic'}
            if not active:
                raise RuntimeError('カメラが指定されていません')
            if not self.test_source:
                if any(not Path(path).exists() for path in active.values()):
                    raise RuntimeError('指定したカメラが接続されていません')
                if len(active) == 2 and Path(active['front']).resolve() == Path(active['rear']).resolve():
                    raise RuntimeError('前後には別のカメラを指定してください')
            camera_width = int(os.environ.get('ADAS_CAMERA_WIDTH', '640'))
            camera_height = int(os.environ.get('ADAS_CAMERA_HEIGHT', '480'))
            camera_fps = float(os.environ.get('ADAS_CAMERA_FPS', '15'))
            for role, device in active.items():
                role_width = int(os.environ.get('ADAS_' + role.upper() + '_WIDTH', camera_width))
                role_height = int(os.environ.get('ADAS_' + role.upper() + '_HEIGHT', camera_height))
                role_fps = float(os.environ.get('ADAS_' + role.upper() + '_FPS', camera_fps))
                role_format = os.environ.get('ADAS_' + role.upper() + '_FORMAT', 'mjpeg')
                args = (['-re', '-i', str(self.video_path)]
                        if role == self.video_role else
                        ['-re', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=10']
                        if self.test_source else
                        ['-f', 'v4l2', '-input_format', role_format, '-framerate', str(role_fps),
                         '-video_size', f'{role_width}x{role_height}', '-i', device])
                capture = SegmentCapture(self.writer.directory, args, lambda _: None,
                    lambda message, role=role: self._error(role, message), role=role, fps=role_fps,
                    on_preview=lambda image, role=role: self._preview(role, image),
                    preview_fps=min(role_fps, 30), preview_only=True,
                    preview_width=int(os.environ.get("ADAS_PREVIEW_WIDTH", "320")),
                    lens_correction=lens_from_environment(role, os.environ) if role != self.video_role else None,
                    expected_eof=role == self.video_role, on_eof=self.video_finished.set)
                self.captures[role] = capture
                capture.start()
            threading.Thread(target=self._commands, daemon=True).start()
            announced = set()
            while not self.stop_requested.wait(0.1):
                if self.video_finished.is_set(): break
                for role in active:
                    if role not in announced and self.frames[role].is_set():
                        announced.add(role)
                        self.emit({'status': 'running', 'camera': role})
        except Exception as exc:
            self.errors.put(('system', str(exc)))
        finally:
            for role, capture in self.captures.items():
                try:
                    capture.stop()
                except Exception as exc:
                    self.errors.put((role, str(exc)))
            self.writer.close()
        while not self.errors.empty():
            role, message = self.errors.get()
            self.emit({'status': 'error', 'camera': role, 'message': message})
            return 1
        if self.video_finished.is_set() and not self.stop_requested.is_set():
            self.emit({'status': 'video_ended', 'camera': self.video_role})
        self.emit({'status': 'stopped'})
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview-dir', required=True, type=Path)
    parser.add_argument('--test-source', action='store_true')
    parser.add_argument('--video-role', choices=('front', 'rear'))
    parser.add_argument('--video-path', type=Path)
    args = parser.parse_args()
    devices = {'front': os.environ.get('FRONT_DEVICE', ''), 'rear': os.environ.get('REAR_DEVICE', '')}
    try:
        return PreviewService(args.preview_dir, devices, test_source=args.test_source, video_role=args.video_role, video_path=args.video_path).run()
    except Exception as exc:
        print('PREVIEW_JSON ' + json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
