from __future__ import annotations

import time
import re
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.types import Alert, SceneContext, TrackedObject


CLASS_COLOR = {
    "person": (60, 220, 60),       # 緑
    "bicycle": (200, 100, 255),    # ピンク（自転車を区別しやすく）
    "motorcycle": (0, 200, 255),   # シアン
    "car": (255, 150, 40),         # 橙
    "truck": (255, 150, 40),
    "bus": (255, 150, 40),
    "candidate": (180, 180, 180),
}
ALERT_COLOR = {1: (255, 255, 80), 2: (0, 220, 255), 3: (0, 0, 255)}

# 描画パラメータの基準解像度。1280px で従来同等の見え方。
# Pipeline は元解像度フレーム (display_frame) に描画するため、ここの値は実フレーム幅基準。
REFERENCE_WIDTH = 1280


class Renderer:
    def __init__(self) -> None:
        self._s = 1.0  # フレーム幅基準のスケール係数（render 毎に再計算）
        self.overlay_scale = 1.0  # ユーザー指定の太さ倍率 (0.5=細い, 1=普通, 1.5=太い, 2=極太)

    def render(self, ctx: SceneContext, alerts: list[Alert], meta: dict) -> np.ndarray:
        image = ctx.enhanced.copy()
        self._update_scale(image)
        if meta.get("show_debug_mask") and ctx.road_mask is not None:
            image = self._draw_mask(image, ctx.road_mask)
        self._draw_lanes(image, ctx)
        self._draw_reference_zone(image, meta)
        self._draw_roi_rect(image, meta)
        self._draw_tracks(image, ctx.tracks, alerts, meta.get("track_labels", {}))
        for region in meta.get("ai_depth_regions", []):
            if region["known"] or region["level"] < 1:
                continue
            x1, y1, x2, y2 = map(int, region["bbox"])
            color = ALERT_COLOR.get(region["level"], (210, 180, 80))
            cv2.rectangle(image, (x1, y1), (x2, y2), color, self._t(2))
            self._draw_label(image, f"{region['direction']}障害物", (x1, max(self._p(20), y1)), color)
        if ctx.signals:
            self._draw_detections(image, ctx.signals)
        self._draw_alert_panel(image, alerts)
        self._draw_blind_banner(image, meta)
        self._draw_status(image, ctx, meta)
        if meta.get("show_ai_depth_preview"):
            for region in meta.get("ai_depth_regions", []):
                if not region["known"] or "direction" not in region:
                    continue
                x1, y1, x2, y2 = map(int, region["bbox"])
                color = ALERT_COLOR.get(region["level"], (210, 180, 80))
                cv2.rectangle(image, (x1, y1), (x2, y2), color, self._t(2))
                label = (f"{region['direction']} {region['reason']} #{region['target_id']} "
                         f"({region['depth_age_s']:.1f}秒前)")
                self._draw_label(image, label,
                                 (x1, max(self._p(20), y1)), color)
            values = meta.get("ai_depth_values")
            if values is None or not self._draw_ai_depth_preview(image, values):
                status = meta.get("ai_depth_error") or meta.get("ai_depth_status") or "推論待ち"
                self._draw_ai_depth_preview_status(image, str(status))
        return image

    def render_lightweight(self, frame: np.ndarray, alerts: list[Alert], meta: dict) -> np.ndarray:
        image = frame.copy()
        self._update_scale(image)
        self._draw_reference_zone(image, meta)
        self._draw_alert_panel(image, alerts)
        self._draw_simple_status(image, meta)
        return image

    # ---- スケール基盤 ----

    def _update_scale(self, image: np.ndarray) -> None:
        # フレーム幅に応じたベース倍率 × ユーザー指定の大きさ倍率
        # クランプは最小限にしてユーザー指定 (0.5x / 0.75x 等) が確実に反映されるようにする
        base = image.shape[1] / float(REFERENCE_WIDTH)
        self._s = base * max(0.2, float(self.overlay_scale))

    def _t(self, base: int) -> int:
        """太さ（線/枠）。物理 1px が下限。"""
        return max(1, int(round(base * self._s)))

    def _f(self, base: float) -> float:
        """フォント scale。cv2 が描画できる最小 0.15 まで許容。"""
        return max(0.15, base * self._s)

    def _p(self, base: int) -> int:
        """ピクセル数（パディング・半径・オフセット等）。"""
        return max(1, int(round(base * self._s)))

    # ---- 各描画 ----

    @staticmethod
    def _draw_mask(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        overlay = image.copy()
        overlay[mask == 1] = (40, 120, 40)
        overlay[mask == 2] = (120, 80, 40)
        return cv2.addWeighted(overlay, 0.25, image, 0.75, 0)

    def _draw_lanes(self, image: np.ndarray, ctx: SceneContext) -> None:
        lanes = ctx.lanes
        if lanes.ego_lane_polygon is not None:
            self._blend_polygon(image, lanes.ego_lane_polygon, (0, 0, 180), .15)
            cv2.polylines(image, [lanes.ego_lane_polygon.astype(np.int32)], True, (0, 80, 255), self._t(2))
        for lane in (lanes.left_lane, lanes.right_lane):
            if lane is not None:
                cv2.polylines(image, [lane.astype(np.int32)], False, (0, 255, 80), self._t(3))

    def _draw_ai_depth_preview(self, image: np.ndarray, values: np.ndarray) -> bool:
        """Draw a relative Hailo depth heatmap as a small upper-left inset."""
        values = np.asarray(values, dtype=np.float32)
        if values.ndim != 2 or values.size == 0 or not np.isfinite(values).all():
            return False
        low, high = np.percentile(values, (2, 98))
        if high - low < 1e-6:
            return False
        normalized = np.clip((values - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
        heatmap = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
        max_width = max(96, int(image.shape[1] * 0.30))
        preview_width = min(max_width, image.shape[1] - self._p(16))
        preview_height = max(1, int(preview_width * values.shape[0] / values.shape[1]))
        preview = cv2.resize(heatmap, (preview_width, preview_height), interpolation=cv2.INTER_LINEAR)
        x, y = self._p(8), self._p(8)
        x2 = min(image.shape[1], x + preview_width)
        y2 = min(image.shape[0], y + preview_height + self._p(24))
        image[y:y + preview_height, x:x2] = preview[:, :x2 - x]
        cv2.rectangle(image, (x, y), (x2 - 1, y2 - 1), (245, 245, 245), self._t(1))
        cv2.rectangle(image, (x, y), (x2 - 1, min(y2 - 1, y + self._p(22))), (20, 20, 20), -1)
        self._draw_unicode_text(image, "AI奥行き (相対)", (x + self._p(5), y + self._p(2)),
                                (255, 255, 255), max(10, self._p(13)))
        return True

    def _draw_ai_depth_preview_status(self, image: np.ndarray, status: str) -> None:
        """Show feedback instead of a blank inset while depth data is unavailable."""
        x, y = self._p(8), self._p(8)
        width = min(max(150, int(image.shape[1] * 0.42)), image.shape[1] - x - self._p(8))
        height = self._p(34)
        x2, y2 = x + max(1, width), y + height
        cv2.rectangle(image, (x, y), (x2, y2), (20, 20, 20), -1)
        cv2.rectangle(image, (x, y), (x2, y2), (245, 245, 245), self._t(1))
        label = f"AI奥行き: {status[:24]}"
        self._draw_unicode_text(image, label, (x + self._p(5), y + self._p(4)),
                                (255, 255, 255), max(10, self._p(13)))

    @staticmethod
    def _blend_polygon(image, polygon, color, alpha):
        points = np.asarray(polygon, np.int32)
        x, y, w, h = cv2.boundingRect(points)
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(image.shape[1], x+w), min(image.shape[0], y+h)
        if x2 <= x1 or y2 <= y1:
            return
        roi = image[y1:y2, x1:x2]
        overlay = roi.copy()
        key = tuple(map(tuple, (points - [x1, y1]).tolist()))
        mask = _polygon_mask(roi.shape[:2], key)
        overlay[mask] = color
        cv2.addWeighted(overlay, alpha, roi, 1-alpha, 0, dst=roi)

    def _draw_reference_zone(self, image: np.ndarray, meta: dict) -> None:
        center_x_ratio = float(meta.get("center_x_ratio", 0.5))
        x = int(image.shape[1] * np.clip(center_x_ratio, 0.25, 0.75))
        top_y = int(image.shape[0] * np.clip(float(meta.get("zone_top_y_ratio", 0.45)), 0.15, 0.85))
        top_center = x + int(image.shape[1] * np.clip(float(meta.get("zone_top_offset_ratio", 0.0)), -0.25, 0.25))
        bottom_half = int(image.shape[1] * np.clip(float(meta.get("zone_bottom_width_ratio", 0.40)), 0.10, 0.80) / 2)
        top_half = int(image.shape[1] * np.clip(float(meta.get("zone_top_width_ratio", 0.10)), 0.02, 0.50) / 2)
        polygon = np.array(
            [
                (x - bottom_half, image.shape[0] - 1),
                (top_center - top_half, top_y),
                (top_center + top_half, top_y),
                (x + bottom_half, image.shape[0] - 1),
            ],
            dtype=np.int32,
        )
        self._blend_polygon(image, polygon, (0, 0, 180), .12)
        cv2.polylines(image, [polygon], True, (0, 80, 255), self._t(2))

    def _draw_roi_rect(self, image: np.ndarray, meta: dict) -> None:
        """矩形 ROI をうっすら可視化（半透明の薄黄色塗り + 細い枠 + 小ラベル）。"""
        box = meta.get("roi_rect_box")
        if not box:
            return
        x1, y1, x2, y2 = box
        # 中の薄い塗りつぶし (alpha 0.10 程度)
        overlay = image.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 255), -1)
        cv2.addWeighted(overlay, 0.10, image, 0.90, 0, dst=image)
        # 細めの外枠 (1px、薄黄)
        cv2.rectangle(image, (x1, y1), (x2, y2), (80, 220, 220), self._t(1))
        # 4 隅にコーナーマーカー (位置/サイズが視認しやすくなる)
        corner = self._p(12)
        for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            sx = -1 if cx == x2 else 1
            sy = -1 if cy == y2 else 1
            cv2.line(image, (cx, cy), (cx + sx * corner, cy), (255, 255, 0), self._t(2))
            cv2.line(image, (cx, cy), (cx, cy + sy * corner), (255, 255, 0), self._t(2))
        # 小さなラベル (サイズと位置を表示)
        w, h = x2 - x1, y2 - y1
        label = f"ROI {w}x{h}px @ ({x1},{y1})"
        cv2.putText(image, label, (x1 + self._p(4), max(y1 - self._p(6), self._p(14))),
                    cv2.FONT_HERSHEY_SIMPLEX, self._f(0.45), (200, 230, 230), self._t(1), cv2.LINE_AA)

    def _draw_tracks(self, image: np.ndarray, tracks: list[TrackedObject], alerts: list[Alert],
                     track_labels: dict | None = None) -> None:
        alert_by_id = {}
        for alert in alerts:
            if alert.target_id is not None and (alert.target_id not in alert_by_id or alert.level > alert_by_id[alert.target_id].level):
                alert_by_id[alert.target_id] = alert
        blink = int(time.time() * 5) % 2 == 0
        labels = track_labels or {}
        occupied = []
        def priority(track):
            alert = alert_by_id.get(track.track_id)
            return (alert.level if alert and alert.level >= 2 else 0, *self._track_draw_priority(track))
        for track in sorted(tracks, key=priority):
            x1, y1, x2, y2 = map(int, track.bbox)
            alert = alert_by_id.get(track.track_id)
            color = ALERT_COLOR.get(alert.level, (0, 0, 255)) if alert and blink else CLASS_COLOR.get(track.cls, (220, 220, 220))
            detailed = alert is not None and alert.level >= 2
            box_thickness = self._t(4) if detailed else self._t(1)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, box_thickness)
            name = {"car": "車", "truck": "車", "bus": "車", "person": "人",
                    "bicycle": "自転車", "motorcycle": "二輪車", "candidate": "候補"}.get(track.cls, "対象")
            if not detailed:
                name = {"car": "車", "truck": "車", "bus": "車", "person": "人",
                        "bicycle": "自転車", "motorcycle": "二輪車", "candidate": "候補"}.get(track.cls, track.cls)
                size = max(10, int(round(22 * self._s)))
                tile, _ = _text_tile(name, color, size)
                tx = max(0, min(x1, image.shape[1]-tile.shape[1]))
                ty = max(0, min(y1-tile.shape[0], image.shape[0]-tile.shape[0]))
                rect = (tx, ty, tx+tile.shape[1], ty+tile.shape[0])
                if not any(rect[0] < b[2] and b[0] < rect[2] and rect[1] < b[3] and b[1] < rect[3] for b in occupied):
                    self._draw_unicode_text(image, name, (tx, ty), color, size)
                    occupied.append(rect)
                continue
            direction = alert.direction if alert.direction in {"左", "右", "中央", "左前", "右前", "正面"} else None
            label = f"{name} {direction}" if direction else name
            self._draw_label(image, label, (x1, max(self._p(20), y1 - self._p(8))), color)

    @staticmethod
    def _track_draw_priority(track: TrackedObject) -> tuple[int, int]:
        vehicle_priority = 1 if track.cls in {"car", "truck", "bus", "motorcycle"} else 0
        return vehicle_priority, track.track_id

    def _draw_label(self, image: np.ndarray, label: str, origin: tuple[int, int], color: tuple[int, int, int]) -> None:
        x, y = origin
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = self._f(0.58)
        thickness = self._t(2)
        pad_x = self._p(4)
        pad_y = self._p(6)
        unicode_label = not label.isascii()
        unicode_size = max(10, int(round(22 * self._s)))
        if unicode_label:
            bounds = _alert_font(unicode_size).getbbox(label)
            text_w, text_h = bounds[2] - bounds[0], bounds[3] - bounds[1]
            baseline = 0
        else:
            (text_w, text_h), baseline = cv2.getTextSize(label, font, scale, thickness)
        x = max(0, min(x, image.shape[1]-text_w-2*pad_x))
        y = min(image.shape[0]-baseline-pad_x-1, max(text_h + pad_y + 2, y))
        cv2.rectangle(image, (x, y - text_h - baseline - pad_y), (x + text_w + 2 * pad_x, y + baseline + pad_x), (15, 15, 15), -1)
        cv2.rectangle(image, (x, y - text_h - baseline - pad_y), (x + text_w + 2 * pad_x, y + baseline + pad_x), color, 1)
        if unicode_label:
            self._draw_unicode_text(image, label, (x + pad_x, y - text_h), color, unicode_size)
        else:
            cv2.putText(image, label, (x + pad_x, y), font, scale, color, thickness, cv2.LINE_AA)

    def _draw_history(self, image: np.ndarray, track: TrackedObject, color: tuple[int, int, int]) -> None:
        points = np.array(list(track.history), dtype=np.int32)
        if len(points) < 2:
            return
        cv2.polylines(image, [points], False, color, self._t(2))
        for point in points[-6:]:
            cv2.circle(image, tuple(point), self._p(3), color, -1)

    def _draw_motion_vector(self, image: np.ndarray, center: tuple[int, int], velocity: tuple[float, float]) -> None:
        vx, vy = velocity
        speed = float(np.hypot(vx, vy))
        if speed < 0.25:
            cv2.circle(image, center, self._p(5), (0, 255, 255), self._t(2))
            cv2.putText(image, "v 0.0", (center[0] + self._p(8), center[1] + self._p(18)),
                        cv2.FONT_HERSHEY_SIMPLEX, self._f(0.48), (0, 255, 255), self._t(2), cv2.LINE_AA)
            return
        unit = np.array([vx, vy], dtype=np.float32) / speed
        length = int(np.clip(speed * 12, 28, 95) * self._s)
        end = (int(center[0] + unit[0] * length), int(center[1] + unit[1] * length))
        cv2.arrowedLine(image, center, end, (0, 255, 255), self._t(3), tipLength=0.28)
        cv2.putText(
            image,
            f"v {speed:.1f}px/f",
            (end[0] + self._p(6), end[1] + self._p(6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            self._f(0.5),
            (0, 255, 255),
            self._t(2),
            cv2.LINE_AA,
        )

    def _draw_detections(self, image: np.ndarray, detections) -> None:
        for det in detections:
            x1, y1, x2, y2 = map(int, det.bbox)
            color = (80, 80, 255) if "red" in det.cls else (80, 255, 80)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, self._t(2))
            cv2.putText(image, det.cls, (x1, max(self._p(20), y1 - self._p(4))),
                        cv2.FONT_HERSHEY_SIMPLEX, self._f(0.48), color, self._t(1), cv2.LINE_AA)

    def _draw_alert_panel(self, image: np.ndarray, alerts: list[Alert]) -> None:
        if not alerts:
            return
        text_size = max(12, int(round(22 * self._s)))
        row_h = max(20, int(round(42 * self._s)))
        panel_w = max(160, int(round(430 * self._s)))
        x0 = max(self._p(10), image.shape[1] - panel_w)
        y0 = self._p(20)
        panel_h = row_h * len(alerts) + self._p(16)
        cv2.rectangle(image, (x0, y0), (image.shape[1] - self._p(16), y0 + panel_h), (20, 20, 20), -1)
        cv2.rectangle(image, (x0, y0), (image.shape[1] - self._p(16), y0 + panel_h), (80, 80, 80), 1)
        for idx, alert in enumerate(alerts):
            y = y0 + self._p(34) + idx * row_h
            color = ALERT_COLOR.get(alert.level, (255, 255, 255))
            cv2.circle(image, (x0 + self._p(22), y - self._p(7)), self._p(7), color, -1)
            self._draw_unicode_text(image, display_alert_message(alert.message), (x0 + self._p(42), y - int(text_size * 1.1)),
                                    (245, 245, 245), text_size)

    @staticmethod
    def _draw_unicode_text(image: np.ndarray, text: str, xy: tuple[int, int], color: tuple[int, int, int], size: int) -> None:
        tile, alpha = _text_tile(text, color, size)
        x, y = map(int, xy)
        h, w = tile.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(image.shape[1], x+w), min(image.shape[0], y+h)
        if x2 <= x1 or y2 <= y1:
            return
        patch = tile[y1-y:y2-y, x1-x:x2-x]
        weight = alpha[y1-y:y2-y, x1-x:x2-x]
        image[y1:y2, x1:x2] = patch * weight + image[y1:y2, x1:x2] * (1-weight)

    def _draw_blind_banner(self, image: np.ndarray, meta: dict) -> None:
        """カメラ異常検知時に画面上部に赤帯 + 警告メッセージを描画。"""
        if not meta.get("blind"):
            return
        h, w = image.shape[:2]
        bar_h = max(40, int(round(70 * self._s)))
        # 半透明赤帯
        overlay = image.copy()
        cv2.rectangle(overlay, (0, 0), (w, bar_h), (0, 0, 200), -1)
        cv2.addWeighted(overlay, 0.55, image, 0.45, 0, dst=image)
        # 上下にエッジ線
        cv2.line(image, (0, bar_h), (w, bar_h), (0, 0, 255), self._t(2))
        # 点滅 (1Hz)
        import time as _time
        if int(_time.time() * 2) % 2 == 0:
            reason = meta.get("blind_reason") or "原因不明"
            text = f"⚠ 検出不能 - カメラを確認してください  [{reason}]"
            font_size = max(18, int(round(28 * self._s)))
            self._draw_unicode_text(image, text,
                                     (self._p(20), bar_h // 2 - font_size // 2),
                                     (255, 255, 255), font_size)

    def _draw_status(self, image: np.ndarray, ctx: SceneContext, meta: dict) -> None:
        status = (
            f"FPS {meta.get('fps', 0):.1f} | フレーム {ctx.frame_idx} | "
            f"対象 {len(ctx.tracks)} | YOLO {meta.get('device', '-')} | "
            f"{meta.get('process_ms', 0):.0f} ms"
        )
        bar_h = max(22, int(round(34 * self._s)))
        cv2.rectangle(image, (0, image.shape[0] - bar_h), (image.shape[1], image.shape[0]), (0, 0, 0), -1)
        font_size = max(12, int(round(21 * self._s)))
        y = image.shape[0] - bar_h + max(0, (bar_h - font_size) // 2)
        self._draw_unicode_text(image, status, (self._p(14), y), (240, 240, 240), font_size)

    def _draw_simple_status(self, image: np.ndarray, meta: dict) -> None:
        skipped = " | skip" if meta.get("analysis_skipped") else ""
        status = f"FPS {meta.get('fps', 0):.1f} | フレーム {meta.get('frame_idx', 0)}{skipped}"
        bar_h = max(22, int(round(34 * self._s)))
        cv2.rectangle(image, (0, image.shape[0] - bar_h), (image.shape[1], image.shape[0]), (0, 0, 0), -1)
        font_size = max(12, int(round(21 * self._s)))
        y = image.shape[0] - bar_h + max(0, (bar_h - font_size) // 2)
        self._draw_unicode_text(image, status, (self._p(14), y), (240, 240, 240), font_size)


@lru_cache(maxsize=16)
def _alert_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


@lru_cache(maxsize=256)
def _text_tile(text, color, size):
    font = _alert_font(size)
    bounds = font.getbbox(text)
    width = max(1, bounds[2] + 2)
    height = max(1, bounds[3] + 2)
    tile = Image.new("RGBA", (width, height))
    ImageDraw.Draw(tile).text((0, 0), text, font=font, fill=(color[2], color[1], color[0], 255))
    rgba = np.asarray(tile)
    return rgba[:, :, :3][:, :, ::-1], rgba[:, :, 3:4].astype(np.float32)/255.


@lru_cache(maxsize=16)
def _polygon_mask(shape, points):
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.asarray(points, np.int32)], 1)
    return mask.astype(bool)


def display_alert_message(message: str) -> str:
    text = re.sub(r"\s*[（(]脅威度\s*\d+[）)]", "", str(message))
    text = re.sub(r"\s*TTC\s*[\d.]+\s*s", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[\d.]+\s*m\b", "", text, flags=re.IGNORECASE)
    return text.replace("トラック", "車").replace("バス", "車")
