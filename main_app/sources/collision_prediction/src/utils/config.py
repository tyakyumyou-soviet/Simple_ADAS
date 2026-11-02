from __future__ import annotations

from pathlib import Path
import os
import tempfile
from typing import Any

import torch
import yaml


def resolve_config_path(path: str | Path, launch_cwd: str | Path, project_root: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    launch_base = Path(launch_cwd)
    project_base = Path(project_root)
    from_launch_cwd = (launch_base / candidate).resolve()
    if from_launch_cwd.exists():
        return from_launch_cwd
    return (project_base / candidate).resolve()


def load_config(path: str | Path = "config/default.yaml") -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    base_path = data.pop("extends", None)
    if base_path:
        base = load_config(Path(path).parent / base_path)
        return deep_merge(base, data)
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


CUSTOM_PROFILE_PATH = Path("config/custom.yaml")
CUSTOM2_PROFILE_PATH = Path("config/custom2.yaml")


def save_custom_profile(cfg: dict[str, Any], path: str | Path = CUSTOM_PROFILE_PATH) -> Path:
    """現在の cfg を指定したカスタムプロファイルへ上書き保存する。

    `extends` を使わず独立した完全なプロファイルとして書き出す。
    default.yaml が将来変わっても保存したプロファイルの動作は不変。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in cfg.items() if k != "extends"}
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return target


def custom_profile_exists(path: str | Path = CUSTOM_PROFILE_PATH) -> bool:
    return Path(path).exists()


def resolve_device(device: str | None) -> str:
    if not device or device == "auto":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    if device == "mps" and not torch.backends.mps.is_available():
        return "cpu"
    return device
