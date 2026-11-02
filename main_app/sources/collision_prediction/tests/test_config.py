from pathlib import Path

from src.utils.config import CUSTOM2_PROFILE_PATH, CUSTOM_PROFILE_PATH, load_config, resolve_config_path, save_custom_profile


def test_config_extends_default() -> None:
    cfg = load_config("config/realtime_cpu.yaml")
    assert cfg["detector"]["weights"] == "models/yolo11n.pt"
    assert cfg["detector"]["imgsz"] == 480
    assert cfg["detector"]["max_det"] == 120
    assert cfg["detector"]["conf_per_class"]["person"] == 0.18
    assert cfg["detector"]["conf_per_class"]["car"] == 0.32
    assert cfg["detector"]["every_n_frames"] == 1
    assert cfg["detector"]["device"] == "auto"
    assert cfg["segmenter"]["enabled"] is True
    assert cfg["segmenter"]["every_n_frames"] == 18
    assert cfg["ui"]["enable_detection"] is True
    assert cfg["ui"]["enable_lanes"] is True
    assert cfg["ui"]["enable_risk"] is True
    assert cfg["ui"]["show_debug_mask"] is True
    assert cfg["ui"]["enable_enhancement"] is False
    assert cfg["ui"]["enable_signs"] is False
    assert cfg["ui"]["max_process_width"] == 960
    assert cfg["ui"]["display_every_n_frames"] == 1


def test_turbo_config_extends_realtime_cpu() -> None:
    cfg = load_config("config/turbo_cpu.yaml")
    assert cfg["detector"]["weights"] == "models/yolo11n.pt"
    assert cfg["detector"]["imgsz"] == 320
    assert cfg["detector"]["max_det"] == 30
    assert cfg["ui"]["max_process_width"] == 540
    assert cfg["ui"]["enable_signs"] is False


def test_view_only_config_disables_analysis_modules() -> None:
    cfg = load_config("config/view_only.yaml")
    assert cfg["ui"]["enable_detection"] is False
    assert cfg["ui"]["enable_lanes"] is False
    assert cfg["ui"]["enable_signs"] is False
    assert cfg["ui"]["enable_risk"] is False
    assert cfg["segmenter"]["enabled"] is False
    assert cfg["depth"]["enabled"] is False


def test_resolve_config_path_falls_back_to_project_root(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    resolved = resolve_config_path("config/realtime_cpu.yaml", tmp_path, project_root)
    assert resolved == project_root / "config/realtime_cpu.yaml"


def test_resolve_config_path_prefers_launch_cwd_when_file_exists(tmp_path: Path) -> None:
    config_path = tmp_path / "custom.yaml"
    config_path.write_text("ui: {}\n", encoding="utf-8")
    project_root = Path(__file__).resolve().parents[1]
    resolved = resolve_config_path("custom.yaml", tmp_path, project_root)
    assert resolved == config_path


def test_custom_profile_slots_are_independent(tmp_path: Path) -> None:
    first = tmp_path / CUSTOM_PROFILE_PATH.name
    second = tmp_path / CUSTOM2_PROFILE_PATH.name
    save_custom_profile({"ui": {"max_process_width": 360}}, first)
    save_custom_profile({"ui": {"max_process_width": 540}}, second)

    assert load_config(first)["ui"]["max_process_width"] == 360
    assert load_config(second)["ui"]["max_process_width"] == 540
