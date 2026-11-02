"""既存の解析パイプラインへ動画ファイルを渡すMac向け確認用アダプター。"""
from __future__ import annotations

from pathlib import Path
import sys


def make_video_worker(project: Path, video: Path):
    """モデル無しの表示専用設定を使う。カメラや録画装置は開かない。"""
    project = project.resolve()
    if not (project / "src" / "pipeline.py").is_file():
        raise FileNotFoundError(f"危険予知プログラムが見つかりません: {project}")
    if not video.is_file():
        raise FileNotFoundError(f"動画が見つかりません: {video}")
    sys.path.insert(0, str(project))
    from src.input.video_file import VideoFileSource
    from src.ui.inference_thread import InferenceThread
    from src.utils.config import load_config

    cfg = load_config(project / "config" / "view_only.yaml")
    # These options are explicit even if a parent profile changes later.
    cfg.setdefault("ui", {}).update({"enable_detection": False, "enable_risk": False,
                                    "enable_lanes": False, "enable_signs": False})
    cfg.setdefault("detector", {})["enabled"] = False
    cfg.setdefault("hailo_scene", {}).update({"enabled": False, "depth_enabled": False})
    return InferenceThread(VideoFileSource(video), cfg)
