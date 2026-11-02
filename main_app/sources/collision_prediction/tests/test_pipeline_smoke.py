import numpy as np

from src.pipeline import Pipeline


def _no_model_cfg() -> dict:
    return {
        "detector": {"enabled": False, "device": "cpu"},
        "segmenter": {"enabled": False},
        "depth": {"model": "fallback"},
        "lane": {},
        "risk": {},
        "ui": {
            "enable_enhancement": False,
            "enable_detection": False,
            "enable_lanes": True,
            "enable_signs": False,
            "enable_risk": True,
            "show_debug_mask": False,
        },
    }


def test_pipeline_smoke_without_models() -> None:
    cfg = _no_model_cfg()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    display, meta = Pipeline(cfg).process(frame, 0, 30.0)
    assert display.shape == frame.shape
    assert meta["frame_idx"] == 0
    assert meta["timestamp"] == 0.0
    assert meta["process_ms"] >= 0
    assert set(meta["stage_ms"]) >= {
        "detection_tracking",
        "distance",
        "road_segmentation",
        "lane_detection",
        "ego_motion",
        "risk_analysis",
        "render",
    }
    assert meta['risk_mode'] == 'legacy'
    assert meta['ai_depth_regions'] == []


def test_ai_depth_can_generate_collision_without_a_legacy_alert():
    from collections import deque
    from src.types import TrackedObject
    cfg = _no_model_cfg()
    cfg['hailo_scene'] = {'depth_enabled': True, 'depth_update_hz': 5.}
    cfg['ui']['independent_schedule'] = True
    cfg['detector']['update_hz'] = 30.
    pipeline = Pipeline(cfg)
    pipeline.risk.analyze = lambda ctx: []
    rng = np.random.default_rng(3)
    frame = rng.integers(50, 180, (120, 160, 3), dtype=np.uint8)
    try:
        for i, box in enumerate([(65, 45, 95, 85), (61, 40, 99, 90), (57, 35, 103, 95)]):
            z = np.repeat(np.linspace(-2, 0, 120, dtype=np.float32)[:, None], 160, axis=1)
            x1, y1, x2, y2 = box
            z[y1:y2, x1:x2] = 2
            pipeline.hailo_scene.depth = lambda image, z=z: setattr(pipeline.hailo_scene, 'depth_values', z)
            pipeline.tracker.track = lambda image, frame_idx: [TrackedObject(1, box, 'car', .9, (0, 0), deque(), 10, None)]
            _, meta = pipeline.process(frame, i, 30., timestamp=i*.2, render=False)
        assert meta['risk_mode'] == 'ai_depth_fusion'
        assert any(a.kind == 'ai_depth_collision' and a.level >= 2 for a in meta['alerts'])
        assert meta['ai_depth_regions']
    finally:
        pipeline.close()


def test_pipeline_tracks_clear_when_detection_empty() -> None:
    """検出が空になったフレームでは tracks が空になり、古い枠が残らないこと。"""
    cfg = _no_model_cfg()
    p = Pipeline(cfg)
    # 検出は無効なので tracks は常に空
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    _, meta1 = p.process(frame, 0, 30.0)
    _, meta2 = p.process(frame, 1, 30.0)
    assert meta1["tracks"] == []
    assert meta2["tracks"] == []
    # _last_tracks も空であること
    assert p._last_tracks == []


def test_pipeline_uses_capture_timestamp_when_provided() -> None:
    cfg = _no_model_cfg()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    _, meta = Pipeline(cfg).process(frame, 2, 30.0, timestamp=1.75)
    assert meta["timestamp"] == 1.75


def test_realtime_lanes_not_starved_when_detector_due_every_frame() -> None:
    cfg = _no_model_cfg()
    cfg["ui"]["independent_schedule"] = True
    cfg["detector"].update({"update_hz": 10.0, "every_n_frames": 6})
    cfg["lane"].update({"update_hz": 10.0, "every_n_frames": 6})
    pipeline = Pipeline(cfg)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    for i in range(8):
        _, meta = pipeline.process(frame, i, 5.0, timestamp=1.0 + i * 0.2)
    assert meta["detector_runs"] == 8
    assert meta["lane_runs"] == 8


def test_realtime_schedule_keeps_target_rate_between_input_frames() -> None:
    cfg = _no_model_cfg()
    cfg["ui"]["independent_schedule"] = True
    cfg["detector"].update({"update_hz": 10.0, "every_n_frames": 6})
    cfg["lane"].update({"update_hz": 10.0, "every_n_frames": 6})
    pipeline = Pipeline(cfg)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    for i in range(61):
        _, meta = pipeline.process(frame, i, 15.0, timestamp=1.0 + i / 15.0)
    assert 38 <= meta["detector_runs"] <= 41
    assert 38 <= meta["lane_runs"] <= 41
