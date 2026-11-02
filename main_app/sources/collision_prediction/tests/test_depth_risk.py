from collections import deque
from types import SimpleNamespace

import numpy as np
import cv2

from src.alert.alert_manager import AlertManager
from src.prediction.depth_risk import DepthRiskAnalyzer, fuse_depth_alerts, path_relation, region_expansion
from src.types import Alert, LaneInfo, TrackedObject


def scene(t, box=None, dark=False):
    rng = np.random.default_rng(10)
    frame = np.zeros((120, 160, 3), np.uint8) if dark else rng.integers(50, 180, (120, 160, 3), dtype=np.uint8)
    tracks = [] if box is None else [TrackedObject(1, box, 'car', .9, (0, 0), deque(), 10, None)]
    return SimpleNamespace(timestamp=t, image=frame, tracks=tracks,
                           lanes=LaneInfo(None, None, np.array([[48, 119], [60, 40], [100, 40], [112, 119]]), None))


def depth(box=None):
    z = np.repeat(np.linspace(-2, 0, 120, dtype=np.float32)[:, None], 160, axis=1)
    if box:
        x1, y1, x2, y2 = map(int, box)
        z[y1:y2, x1:x2] = 2
    return z


def test_vehicle_depth_trends_require_drift_and_fresh_matching_track(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    box = (65, 45, 95, 85)
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    analyzer.analyze(scene(0, box), depth(box), updated=True, max_age=1.5, interval=.6)
    analyzer.analyze(scene(.6, box), depth(box), updated=True, max_age=1.5, interval=.6)
    assert analyzer.vehicle_depth_trends(scene(.6, box), 1.5) == {}
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, .01))
    analyzer.analyze(scene(1.2, box), depth(box), updated=True, max_age=1.5, interval=.6)
    assert 1 in analyzer.vehicle_depth_trends(scene(1.2, box), 1.5)
    assert not analyzer.vehicle_depth_trends(scene(3, box), 1.5)
    assert not analyzer.vehicle_depth_trends(scene(1.2, (1, 1, 20, 20)), 1.5)
    analyzer._motion_unstable = True
    assert not analyzer.vehicle_depth_trends(scene(1.2, box), 1.5)


def test_equal_depth_warning_preserves_following_label():
    following = Alert('following', 2, 1, '車間注意', (0, 0, 10, 10), '正面')
    depth_alert = Alert('ai_depth_collision', 2, 1, '接近注意', (0, 0, 10, 10), '正面')
    assert fuse_depth_alerts([following], [depth_alert]) == [following]


def test_failed_unknown_tracking_has_direction_and_no_alert(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    analyzer.analyze(scene(0), depth((45, 30, 115, 90)), updated=True, max_age=1.5, interval=.6)
    assert analyzer.regions
    for region in analyzer.regions.values():
        region.track_valid = False
    assert analyzer.analyze(scene(.1), None, updated=False, max_age=1.5, interval=.6) == []
    assert all(item['direction'] in ('左前', '正面', '右前') and item['level'] == 0
               for item in analyzer.diagnostics)


def test_obstacle_component_mask_excludes_unrelated_box_pixels():
    near = np.zeros((120, 160), np.float32)
    near[30:90, 40:50] = .95
    near[80:90, 40:100] = .95
    components = DepthRiskAnalyzer._obstacles(near, [], 1., 1., (160, 120), include_masks=True)
    assert len(components) == 1
    box, mask = components[0]
    assert mask[35, 45] and not mask[35, 90]
    assert box == (40., 30., 100., 90.)


def test_vehicle_polygon_preserves_low_obstacle_outside_car():
    analyzer = DepthRiskAnalyzer([[.35, .8], [.65, .8], [.65, 1.], [.35, 1.]])
    mask = analyzer._vehicle_mask((120, 160))
    assert mask[110, 80] and not mask[110, 15]
    near = np.zeros((120, 160), np.float32)
    near[95:118, 5:30] = .95
    boxes = analyzer._obstacles(near, [], 1., 1., (160, 120), exclusion_mask=mask)
    assert boxes and boxes[0][3] > 96


def test_missing_unknown_retains_history_without_warning_then_recovers(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    box = (45, 30, 115, 90)
    analyzer.analyze(scene(0), depth(box), updated=True, max_age=1.5, interval=.6)
    rid = next(iter(analyzer.regions))
    assert analyzer.analyze(scene(.6), depth(), updated=True, max_age=1.5, interval=.6) == []
    assert rid in analyzer.regions and not analyzer.regions[rid].observed
    analyzer.analyze(scene(1.2), depth(box), updated=True, max_age=1.5, interval=.6)
    assert rid in analyzer.regions and analyzer.regions[rid].observed


def test_depth_and_looming_create_collision_alert_without_legacy_warning(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    alerts = []
    for t, box in [(0, (65, 45, 95, 85)), (.2, (61, 40, 99, 90)), (.4, (57, 35, 103, 95))]:
        alerts = analyzer.analyze(scene(t, box), depth(box), updated=True, max_age=1.5, interval=.2)
    assert any(a.level == 3 and a.kind == 'ai_depth_collision' and a.direction == '正面' for a in alerts)


def test_stationary_side_obstacle_does_not_become_collision(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    box = (4, 40, 28, 90)
    for t in (0, .2, .4):
        alerts = analyzer.analyze(scene(t, box), depth(box), updated=True, max_age=1.5, interval=.2)
    assert not any(a.level >= 2 for a in alerts)
    assert analyzer.diagnostics[0]['direction'] == '左前'


def test_unstable_camera_motion_cannot_trigger_approach_warning(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    analyzer._motion_unstable = True
    for t, box in [(0, (65, 45, 95, 85)), (.2, (61, 40, 99, 90)), (.4, (57, 35, 103, 95))]:
        alerts = analyzer.analyze(scene(t, box), depth(box), updated=True, max_age=1.5, interval=.2)
    assert analyzer.status == '旋回・揺れのため接近判定を保留'
    assert not any(a.level >= 2 for a in alerts)


def test_relative_depth_changes_warning_for_same_looming_track(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    for t, box in [(0, (65, 45, 95, 85)), (.2, (61, 40, 99, 90)), (.4, (57, 35, 103, 95))]:
        z = depth()
        x1, y1, x2, y2 = box
        z[y1:y2, x1:x2] = -2
        alerts = analyzer.analyze(scene(t, box), z, updated=True, max_age=1.5, interval=.2)
    assert not any(a.kind == 'ai_depth_collision' for a in alerts)


def test_global_depth_scale_drift_does_not_create_approach():
    analyzer = DepthRiskAnalyzer()
    box = (55, 35, 105, 95)
    base = depth(box)
    inverse = 10/(1+np.exp(-base))+.009
    for t, scale in [(0, .7), (.2, .8), (.4, .9)]:
        probability = np.clip((inverse*scale-.009)/10, 1e-5, 1-1e-5)
        logits = np.log(probability/(1-probability))
        alerts = analyzer.analyze(scene(t, box), logits, updated=True, max_age=1.5, interval=.2)
    assert not any(a.level >= 2 for a in alerts)
    assert not analyzer.diagnostics[0]['approaching']


def test_unknown_obstacle_needs_real_image_motion_not_depth_mask_growth(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    for t, box in [(0, (60, 35, 100, 90)), (.2, (55, 30, 105, 100)), (.4, (50, 25, 110, 105))]:
        alerts = analyzer.analyze(scene(t), depth(box), updated=True, max_age=1.5, interval=.2)
    assert analyzer.diagnostics
    assert all(not d['known'] and not d['approaching'] for d in analyzer.diagnostics)
    assert not any(a.level >= 2 for a in alerts)


def test_unknown_wall_approach_creates_directional_warning(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: ((None, None), None))
    monkeypatch.setattr('src.prediction.depth_risk.region_expansion', lambda *args: .4)
    for t in (0, .2, .4):
        alerts = analyzer.analyze(scene(t), depth((45, 30, 115, 105)), updated=True, max_age=1.5, interval=.2)
    assert any(a.kind == 'ai_depth_obstacle' and a.target_id < 0 and a.direction == '正面' and a.level >= 2 for a in alerts)
    assert all(a.message == '正面障害物' for a in alerts if a.kind == 'ai_depth_obstacle')


def test_unknown_obstacle_labels_include_direction_without_extra_words(monkeypatch):
    monkeypatch.setattr('src.prediction.depth_risk.region_expansion', lambda *args: .4)
    for direction in ('左前', '正面', '右前'):
        analyzer = DepthRiskAnalyzer()
        monkeypatch.setattr(analyzer, '_motion', lambda *args: ((None, None), None))
        monkeypatch.setattr('src.prediction.depth_risk.path_relation', lambda *args, d=direction: (1., d))
        for t in (0, .2, .4):
            alerts = analyzer.analyze(scene(t), depth((45, 30, 115, 105)), updated=True, max_age=1.5, interval=.2)
        assert any(a.message == f'{direction}障害物' for a in alerts)


def test_unknown_obstacle_preview_label_is_concise(monkeypatch):
    from src.render.renderer import Renderer
    renderer = Renderer()
    for name in ('_draw_lanes', '_draw_reference_zone', '_draw_roi_rect', '_draw_tracks',
                 '_draw_alert_panel', '_draw_blind_banner', '_draw_status'):
        monkeypatch.setattr(renderer, name, lambda *args: None)
    labels = []
    monkeypatch.setattr(renderer, '_draw_label', lambda image, label, origin, color: labels.append(label))
    monkeypatch.setattr(renderer, '_draw_ai_depth_preview', lambda *args: True)
    ctx = SimpleNamespace(enhanced=np.zeros((120, 160, 3), np.uint8), signals=[], tracks=[])
    region = {'bbox': (10, 20, 60, 90), 'level': 2, 'direction': '左前', 'known': False,
              'reason': '接近', 'target_id': -10000, 'depth_age_s': .2}
    renderer.render(ctx, [], {'show_ai_depth_preview': True, 'ai_depth_regions': [region],
                               'ai_depth_values': np.zeros((2, 2))})
    assert labels == ['左前障害物']


def test_unknown_obstacle_is_visible_when_depth_preview_is_off(monkeypatch):
    from src.render.renderer import Renderer
    renderer = Renderer()
    for name in ('_draw_lanes', '_draw_reference_zone', '_draw_roi_rect', '_draw_tracks',
                 '_draw_alert_panel', '_draw_blind_banner', '_draw_status'):
        monkeypatch.setattr(renderer, name, lambda *args: None)
    labels = []
    monkeypatch.setattr(renderer, '_draw_label', lambda image, label, origin, color: labels.append(label))
    ctx = SimpleNamespace(enhanced=np.zeros((120, 160, 3), np.uint8), signals=[], tracks=[])
    region = {'bbox': (10, 20, 60, 90), 'level': 2, 'direction': '正面', 'known': False}
    image = renderer.render(ctx, [], {'show_ai_depth_preview': False, 'ai_depth_regions': [region]})
    assert labels == ['正面障害物']
    assert image[20, 10].any()
    labels.clear()
    region['level'] = 0
    renderer.render(ctx, [], {'show_ai_depth_preview': False, 'ai_depth_regions': [region]})
    assert labels == []


def test_floor_gradient_has_no_unknown_obstacles():
    analyzer = DepthRiskAnalyzer()
    analyzer.analyze(scene(0), depth(), updated=True, max_age=1.5, interval=1)
    assert not analyzer.diagnostics


def test_ground_is_not_a_wall_when_inverse_depth_transform_saturates():
    analyzer = DepthRiskAnalyzer()
    ground = np.repeat(np.linspace(-2, 8, 120, dtype=np.float32)[:, None], 160, axis=1)
    analyzer.analyze(scene(0), ground, updated=True, max_age=1.5, interval=.2)
    assert not analyzer.diagnostics


def test_dashboard_region_straddling_bottom_fifth_is_not_an_obstacle():
    near = np.repeat(np.linspace(0, .45, 120, dtype=np.float32)[:, None], 160, axis=1)
    near[80:108, 25:145] = .95
    assert DepthRiskAnalyzer._obstacles(near, [], 1., 1., (160, 120)) == []


def test_tall_wall_crossing_bottom_fifth_is_retained_above_exclusion():
    near = np.repeat(np.linspace(0, .45, 120, dtype=np.float32)[:, None], 160, axis=1)
    near[30:108, 45:115] = .95
    boxes = DepthRiskAnalyzer._obstacles(near, [], 1., 1., (160, 120))
    assert any(box[1] < 40 and box[3] <= 96 for box in boxes)


def test_known_yolo_target_at_bottom_is_not_removed_by_hood_filter():
    analyzer = DepthRiskAnalyzer()
    box = (50, 78, 110, 118)
    analyzer.analyze(scene(0, box), depth(box), updated=True, max_age=1.5, interval=.6)
    assert any(item['known'] and item['target_id'] == 1 for item in analyzer.diagnostics)


def test_tracking_cannot_restore_obstacles_inside_hood_zone(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    analyzer.analyze(scene(0), depth((45, 30, 115, 105)), updated=True, max_age=1.5, interval=1)
    region = next(iter(analyzer.regions.values()))
    monkeypatch.setattr(analyzer, '_advance_unknown', lambda ctx: setattr(region, 'bbox', (45, 90, 115, 115)))
    analyzer.analyze(scene(.1), None, updated=False, max_age=1.5, interval=1)
    assert not analyzer.diagnostics
    monkeypatch.setattr(analyzer, '_advance_unknown', lambda ctx: setattr(region, 'bbox', (45, 30, 115, 110)))
    analyzer.analyze(scene(.2), None, updated=False, max_age=1.5, interval=1)
    assert analyzer.diagnostics[0]['bbox'][3] == 96


def test_dark_uniform_invalid_and_expired_inputs_clear_evidence(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    box = (55, 35, 105, 95)
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    for t in (0, .2):
        analyzer.analyze(scene(t, box), depth(box), updated=True, max_age=1.5, interval=.2)
    assert analyzer.diagnostics
    assert analyzer.analyze(scene(2, box), depth(box), updated=False, max_age=1.5, interval=.2) == []
    assert not analyzer.diagnostics
    analyzer.analyze(scene(3, box, dark=True), depth(box), updated=True, max_age=1.5, interval=.2)
    assert '判定困難' in analyzer.status
    analyzer.analyze(scene(4, box), np.ones((120, 160)), updated=True, max_age=1.5, interval=.2)
    assert '判定困難' in analyzer.status
    analyzer.analyze(scene(5, box), np.full((120, 160), np.nan), updated=True, max_age=1.5, interval=.2)
    assert not analyzer.regions


def test_changed_track_does_not_reuse_depth_from_old_box(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    box = (55, 35, 105, 95)
    analyzer.analyze(scene(0, box), depth(box), updated=True, max_age=1.5, interval=1)
    assert analyzer.analyze(scene(.1, (0, 0, 20, 20)), depth(box), updated=False, max_age=1.5, interval=1) == []
    assert not analyzer.diagnostics


def test_unknown_sparse_tracking_moves_box_without_refreshing_depth_age(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    analyzer.analyze(scene(0), depth((45, 30, 115, 105)), updated=True, max_age=1.5, interval=.2)
    old = next(iter(analyzer.regions.values())).bbox
    current = scene(.1)
    current.image = cv2.warpAffine(current.image, np.float32([[1, 0, 2], [0, 1, 0]]), (160, 120))
    analyzer.analyze(current, None, updated=False, max_age=1.5, interval=.2)
    assert analyzer.diagnostics
    new = analyzer.diagnostics[0]
    assert 1 < new['bbox'][0]-old[0] < 3
    assert new['depth_age_s'] == .1


def test_sudden_dark_frame_clears_cached_evidence_before_next_depth(monkeypatch):
    analyzer = DepthRiskAnalyzer()
    monkeypatch.setattr(analyzer, '_motion', lambda *args: (None, None))
    analyzer.analyze(scene(0), depth((45, 30, 115, 105)), updated=True, max_age=1.5, interval=1)
    assert analyzer.regions
    assert analyzer.analyze(scene(.1, dark=True), None, updated=False, max_age=1.5, interval=1) == []
    assert not analyzer.regions


def test_depth_fusion_keeps_stronger_legacy_and_merges_same_target():
    old = Alert('collision', 3, 1, 'old', None)
    weak = Alert('ai_depth_collision', 2, 1, 'depth', None)
    strong = Alert('ai_depth_collision', 3, 1, 'depth', None)
    assert fuse_depth_alerts([old], [weak]) == [old]
    assert fuse_depth_alerts([old], [strong]) == [strong]


def test_stale_depth_alert_is_removed_from_alert_manager_immediately():
    manager = AlertManager()
    alert = Alert('ai_depth_obstacle', 2, -1, 'depth', None)
    assert manager.update([alert], 0)
    assert not manager.update([], .1)


def test_seek_back_does_not_show_warnings_from_future_frames():
    manager = AlertManager()
    alert = Alert('collision', 3, 1, 'old', None)
    assert manager.update([alert], 20)
    assert manager.update([], 0) == []


def test_path_and_flow_are_directional_and_ignore_rigid_translation():
    polygon = scene(0).lanes.ego_lane_polygon
    assert path_relation((0, 40, 30, 90), polygon, (120, 160))[1] == '左前'
    assert path_relation((130, 40, 160, 90), polygon, (120, 160))[1] == '右前'
    points = np.array([[x, y] for x in (20, 40, 60) for y in (20, 40, 60)], np.float32)
    assert abs(region_expansion((points, np.ones_like(points)*5), (0, 0, 80, 80), 1, 1)) < 1e-5
    assert abs(region_expansion((points, points*.2), (0, 0, 80, 80), 1, 1)-.2) < 1e-5
