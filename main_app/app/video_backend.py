"""既存の解析パイプラインへ動画ファイルを渡すMac向け確認用アダプター。"""
from __future__ import annotations

from pathlib import Path
import sys
import json


def make_video_worker(project: Path, video: Path, *, adas: bool = False):
    """モデル無しの表示専用設定を使う。カメラや録画装置は開かない。"""
    project = project.resolve()
    if not (project / "src" / "pipeline.py").is_file():
        raise FileNotFoundError(f"危険予知プログラムが見つかりません: {project}")
    if not video.is_file():
        raise FileNotFoundError(f"動画が見つかりません: {video}")
    sys.path.insert(0, str(project))
    from src.input.video_file import VideoFileSource
    from src.ui.inference_thread import InferenceThread
    from src.utils.config import load_config, deep_merge

    if adas:
        cfg = load_config(project / "config" / "pi_async_ai_hat_2.yaml")
        overrides = Path.home() / ".config/VehicleIntegration/adas-profile.json"
        if overrides.exists():
            cfg = deep_merge(cfg, json.loads(overrides.read_text(encoding="utf-8")))
        # モデルはCar Program 2を基準に解決し、アプリの作業ディレクトリに依存させない。
        def resolve_models(obj):
            if isinstance(obj, dict):
                return {key: resolve_models(value) for key, value in obj.items()}
            if isinstance(obj, list):
                return [resolve_models(value) for value in obj]
            if isinstance(obj, str) and obj.startswith("models/"):
                return str(project / obj)
            return obj
        cfg = resolve_models(cfg)
    else:
        cfg = load_config(project / "config" / "view_only.yaml")
        cfg.setdefault("ui", {}).update({"enable_detection": False, "enable_risk": False,
                                        "enable_lanes": False, "enable_signs": False})
        cfg.setdefault("detector", {})["enabled"] = False
        cfg.setdefault("hailo_scene", {}).update({"enabled": False, "depth_enabled": False})
    return InferenceThread(VideoFileSource(video), cfg)


def make_external_video_worker(project: Path, video: Path, python: Path):
    """Piの危険予知環境を別プロセスとして起動し、Hailo依存関係を共有する。"""
    import base64
    import subprocess
    import cv2
    import numpy as np
    from PySide6.QtCore import QThread, Signal

    class ExternalVideoWorker(QThread):
        frame_ready = Signal(np.ndarray, dict)
        error = Signal(str)

        def __init__(self):
            super().__init__()
            self.process = None
            self.stopping = False

        def run(self):
            try:
                self.process = subprocess.Popen([str(python), str(Path(__file__).with_name('video_process.py')),
                    str(project), str(video)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1)
                if self.stopping:
                    self.process.stdin.write('STOP\n')
                    self.process.stdin.flush()
                for line in self.process.stdout:
                    if line.startswith('FRAME '):
                        packet = json.loads(line[6:])
                        image = cv2.imdecode(np.frombuffer(base64.b64decode(packet.pop('jpeg')), dtype=np.uint8), cv2.IMREAD_COLOR)
                        if image is not None:
                            self.frame_ready.emit(image, packet)
                    elif line.startswith('VIDEO_ERROR '):
                        self.error.emit(line[12:].strip())
                code = self.process.wait()
                if code and not self.stopping:
                    self.error.emit(f'動画解析プロセスが異常終了しました ({code})')
            except Exception as exc:
                self.error.emit(str(exc))

        def stop(self):
            self.stopping = True
            if self.process and self.process.poll() is None:
                try:
                    self.process.stdin.write('STOP\n')
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass

    return ExternalVideoWorker()
