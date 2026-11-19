from pathlib import Path


def validate_settings(cfg, project):
    detector = cfg.get('detector', {})
    if cfg.get('ui', {}).get('enable_detection', True) and detector.get('enabled', True):
        model = Path(detector.get('weights', ''))
        if not model.is_absolute(): model = Path(project) / model
        if not model.is_file(): raise ValueError('選択した検出モデルがありません：' + str(model))
    risk = cfg.get('risk', {})
    if float(risk.get('ttc_critical_s', 1.5)) >= float(risk.get('ttc_warn_s', 3.0)):
        raise ValueError('TTC危険の秒数は、TTC注意の秒数より小さくしてください')
    rect = cfg.get('ui', {}).get('roi_rect', {})
    if cfg.get('ui', {}).get('roi_mode') == 'rectangle':
        for axis, extent in [('x_ratio', 'w_ratio'), ('y_ratio', 'h_ratio')]:
            origin, length = float(rect.get(axis, 0)), float(rect.get(extent, 1))
            if origin < 0 or length <= 0 or origin + length > 1.000001:
                raise ValueError('矩形の推論範囲が画像からはみ出しています')


def display_interval_ms(cfg):
    ui = cfg.get('ui', {})
    fps = max(1, min(60, int(ui.get('display_fps', 30))))
    every = max(1, min(10, int(ui.get('display_every_n_frames', 1))))
    return max(1, round(1000 * every / fps))
