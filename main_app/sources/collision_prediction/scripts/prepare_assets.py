from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


def download_yolo_weight(name: str) -> Path:
    yolo_config = ROOT / "outputs" / "ultralytics"
    yolo_config.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(yolo_config))
    from ultralytics import YOLO

    target = MODELS / name
    if target.exists():
        return target
    YOLO(name)
    downloaded = ROOT / name
    if downloaded.exists():
        shutil.move(str(downloaded), target)
    if not target.exists():
        raise FileNotFoundError(f"Could not prepare {target}")
    return target


def download_hf_model(repo_id: str, local_name: str) -> Path:
    target = MODELS / local_name
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=target,
        local_dir_use_symlinks=False,
        allow_patterns=[
            "*.json",
            "*.txt",
            "*.md",
            "*.bin",
            "*.safetensors",
            "*.pth",
            "preprocessor_config.json",
        ],
    )
    return target


def main() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    assets = {
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
        "yolo_detect": str(download_yolo_weight("yolo11n.pt").relative_to(ROOT)),
        "yolo26_detect": str(download_yolo_weight("yolo26n.pt").relative_to(ROOT)),
        "yolo_train_base": str(download_yolo_weight("yolo11s.pt").relative_to(ROOT)),
        "segformer_cityscapes": str(
            download_hf_model("nvidia/segformer-b0-finetuned-cityscapes-1024-1024", "segformer-b0-cityscapes").relative_to(ROOT)
        ),
        "depth_anything_v2_small_hf": str(
            download_hf_model("depth-anything/Depth-Anything-V2-Small-hf", "depth-anything-v2-small-hf").relative_to(ROOT)
        ),
    }
    manifest = MODELS / "assets_manifest.json"
    manifest.write_text(json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(assets, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
