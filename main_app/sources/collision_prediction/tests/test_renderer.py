from collections import deque

import numpy as np

from src.render.renderer import Renderer
from src.types import TrackedObject


def test_renderer_draws_track_label_and_motion_vector() -> None:
    image = np.zeros((180, 240, 3), dtype=np.uint8)
    history = deque([(70, 100), (80, 102), (92, 105), (105, 108)], maxlen=30)
    track = TrackedObject(
        track_id=7,
        bbox=(70, 70, 130, 130),
        cls="car",
        conf=0.87,
        velocity=(8.0, 1.5),
        history=history,
        age=4,
        distance_m=12.0,
    )

    renderer = Renderer()
    renderer._update_scale(image)
    renderer._draw_tracks(image, [track], [])

    assert np.count_nonzero(image) > 0


def test_roi_polygon_blend_matches_full_image_blend():
    import cv2
    import numpy as np
    from src.render.renderer import Renderer
    rng = np.random.default_rng(7)
    image = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
    polygon = np.array([[20, 110], [60, 40], [100, 40], [140, 110]], np.int32)
    expected = image.copy()
    overlay = image.copy()
    cv2.fillPoly(overlay, [polygon], (0, 0, 180))
    cv2.addWeighted(overlay, .15, expected, .85, 0, dst=expected)
    Renderer._blend_polygon(image, polygon, (0, 0, 180), .15)
    assert np.array_equal(image, expected)


def test_only_caution_tracks_keep_details_and_are_drawn_last(monkeypatch):
    from src.types import Alert
    renderer = Renderer()
    image = np.zeros((180, 240, 3), np.uint8)
    tracks = [TrackedObject(i, (20*i, 40, 20*i+30, 100), 'car', .9, (1, 0), deque(), 4, None)
              for i in (1, 2, 3)]
    details, histories, vectors = [], [], []
    monkeypatch.setattr(renderer, '_draw_label', lambda im, label, *args: details.append(label))
    monkeypatch.setattr(renderer, '_draw_history', lambda im, track, *args: histories.append(track.track_id))
    monkeypatch.setattr(renderer, '_draw_motion_vector', lambda *args: vectors.append(True))
    renderer._draw_tracks(image, tracks, [Alert('collision', 2, 1, '注意', tracks[0].bbox, '正面')])
    assert details == ['車 正面']
    assert histories == [] and vectors == []
    assert np.count_nonzero(image) > 0


def test_alert_text_hides_numeric_metrics():
    from src.render.renderer import display_alert_message
    assert display_alert_message("【正面】衝突注意 (脅威度80) TTC 1.2s") == "【正面】衝突注意"
    assert display_alert_message("車間距離注意 6.5m") == "車間距離注意"
