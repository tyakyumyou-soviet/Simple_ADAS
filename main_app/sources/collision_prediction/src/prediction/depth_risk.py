"""Relative-depth risk evidence. No metric distance is inferred from SCDepth logits.

All history uses capture timestamps. Unknown regions require optical-flow evidence
for an approaching warning; a changing depth mask alone is not motion evidence.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from src.types import Alert, SceneContext


def overlap(a, b):
    intersection = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))
    area_a = max(1., (a[2]-a[0])*(a[3]-a[1]))
    area_b = max(1., (b[2]-b[0])*(b[3]-b[1]))
    return intersection / max(1., area_a + area_b - intersection)


def slope(samples):
    """Median pairwise slope: bounded history and robust against one noisy sample."""
    return float(np.median([(v2-v1)/(t2-t1) for i, (t1, v1) in enumerate(samples)
                            for t2, v2 in list(samples)[i+1:] if t2-t1 >= .12])) if (
        len(samples) > 1 and samples[-1][0]-samples[0][0] >= .12) else 0.


@dataclass
class Region:
    target_id: int
    bbox: tuple
    known: bool
    label: str
    history: deque = field(default_factory=lambda: deque(maxlen=5))
    seen_at: float = 0.
    first_seen: float = 0.
    near: float = 0.
    flow_expansion: float | None = None
    depth_closing: float = 0.
    depth_trend_valid: bool = False
    quality: float = 0.
    track_valid: bool = True
    observed: bool = True


class DepthRiskAnalyzer:
    def __init__(self, vehicle_exclusion_polygon=None):
        self.regions: dict[int, Region] = {}
        self._next_unknown = -10000
        self._previous = None
        self._sample_time = None
        self.status = "推論待ち"
        self.diagnostics = []
        self._motion_unstable = False
        self._image_quality = 1.
        self._tracking_gray = None
        self._tracking_time = None
        self._vehicle_polygon = vehicle_exclusion_polygon
        self._vehicle_mask_cache = None

    def _vehicle_mask(self, shape):
        if not self._vehicle_polygon:
            return None
        if self._vehicle_mask_cache is None or self._vehicle_mask_cache.shape != shape:
            points = np.asarray(self._vehicle_polygon, dtype=np.float32)
            if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
                raise ValueError('vehicle_exclusion_polygon must contain at least three normalized [x,y] points')
            h, w = shape
            mask = np.zeros(shape, np.uint8)
            cv2.fillPoly(mask, [np.rint(points * [w-1, h-1]).astype(np.int32)], 1)
            self._vehicle_mask_cache = mask.astype(bool)
        return self._vehicle_mask_cache

    def invalidate(self, status="奥行き取得不可"):
        self.regions.clear()
        self._previous = None
        self._sample_time = None
        self.status = status
        self.diagnostics = []
        self._tracking_gray = None
        self._tracking_time = None

    def vehicle_depth_trends(self, ctx, max_age):
        """Reliable relative inverse-depth trends, keyed by the same live track ID.

        Values are qualitative evidence only, never metres or a speed estimate.
        """
        if self._motion_unstable:
            return {}
        tracks = {track.track_id: track for track in ctx.tracks}
        result = {}
        for rid, region in self.regions.items():
            track = tracks.get(rid)
            age = ctx.timestamp - region.seen_at
            if (not region.known or not region.observed or not region.track_valid
                    or not region.depth_trend_valid or region.quality < .45
                    or not 0 <= age <= max_age or track is None
                    or track.cls not in {"car", "truck", "bus"}
                    or not track.confirmed or not track.motion_valid
                    or track.match_quality < .7 or overlap(region.bbox, track.bbox) < .25):
                continue
            result[rid] = region.depth_closing
        return result

    def analyze(self, ctx: SceneContext, logits, *, updated: bool, max_age: float,
                interval: float) -> list[Alert]:
        t = ctx.timestamp
        view = ctx.image[::8, ::8].mean(axis=2)
        if float(view.mean()) < 8 or float(view.std()) < 3:
            self.invalidate("暗さ・単色のため判定困難")
            return []
        expiry = min(max_age, max(.35, interval * 1.5 + .1))
        history_expiry = max(expiry, min(2 * interval + .1, 2.5))
        if self._sample_time is not None and (t < self._sample_time or t-self._sample_time > expiry):
            self.invalidate("奥行き結果が古いため判定困難")
        if updated:
            self._update(ctx, logits, expiry, history_expiry)
        if self._sample_time is None:
            return []
        if not updated:
            self._advance_unknown(ctx)
        tracks = {track.track_id: track for track in ctx.tracks}
        alerts, diagnostics = [], []
        for rid, region in list(self.regions.items()):
            if t-region.seen_at > (expiry if region.observed else history_expiry):
                del self.regions[rid]
                continue
            box = region.bbox
            if not region.observed:
                continue
            if not region.track_valid:
                _, direction = path_relation(box, ctx.lanes.ego_lane_polygon, ctx.image.shape)
                diagnostics.append({"target_id": rid, "bbox": tuple(box), "known": region.known,
                                    "direction": direction,
                                    "level": 0, "reason": "追跡失敗・判定保留",
                                    "depth_age_s": round(t-region.seen_at, 3)})
                continue
            if region.known:
                track = tracks.get(rid)
                if track is None or not track.confirmed or overlap(box, track.bbox) < .25:
                    continue
                box = track.bbox
            else:
                # The sparse tracker can move a candidate into the hood zone
                # between depth updates. Apply the same exclusion on every frame.
                if self._vehicle_polygon:
                    h, w = ctx.image.shape[:2]
                    mask = self._vehicle_mask((max(48, round(h * 160 / w)), 160))
                    mh, mw = mask.shape
                    x1, y1, x2, y2 = scaled_box(box, mw / w, mh / h, (mw, mh))
                    if mask[y1:y2, x1:x2].size and mask[y1:y2, x1:x2].mean() >= .35:
                        continue
                else:
                    bottom_edge = ctx.image.shape[0] * .80
                    height = max(1., box[3]-box[1])
                    if max(0., box[3]-max(box[1], bottom_edge))/height >= .35:
                        continue
                    box = (box[0], box[1], box[2], min(box[3], bottom_edge))
            path, direction = path_relation(box, ctx.lanes.ego_lane_polygon, ctx.image.shape)
            stable = len(region.history) >= 2 and region.seen_at-region.first_seen >= .15
            current_path = path
            if stable and (region.known or region.flow_expansion is not None) and not self._motion_unstable:
                # Short image-space projection only; no metric steering angle is assumed.
                vx = slope([(v[0], (v[4][0]+v[4][2])/2) for v in region.history])
                shift = float(np.clip(vx*.5, -ctx.image.shape[1]*.25, ctx.image.shape[1]*.25))
                future = (box[0]+shift, box[1], box[2]+shift, box[3])
                projected, _ = path_relation(future, ctx.lanes.ego_lane_polygon, ctx.image.shape)
                path = max(path, projected*.75)
            size_rate = slope([(v[0], v[2]) for v in region.history]) if region.known else 0.
            # A depth trend alone is never treated as a metric closing speed/TTC.
            expansion = max(0., size_rate, region.flow_expansion or 0.)
            approaching = not self._motion_unstable and (expansion > .045 or (region.known and region.depth_closing > .06))
            near = region.near
            quality = region.quality
            score = float(np.clip(.20*near + .25*path + .35*min(1., expansion/.25)
                                  + .20*min(1., quality) * stable, 0., 1.))
            level = 0
            if stable and quality >= .45 and near >= .55:
                if path >= .25 and approaching and score >= .55:
                    level = 2
                if approaching and path >= .6 and near >= .7 and expansion >= .30 and score >= .80 and len(region.history) >= 3:
                    level = 3
                if not level and path >= .5 and near >= .75:
                    level = 1
                # Side approaches get directional information, not a front collision alarm.
                if not level and path < .25 and approaching and near >= .75:
                    level = 1
            reason = "接近" if approaching else "近い領域"
            decision_reason = ("継続確認中" if not stable else
                               "入力品質不足" if quality < .45 else
                               "相対奥行き不足" if near < .55 else
                               "旋回・揺れのため接近判定保留" if self._motion_unstable and not level else
                               "警告条件未成立" if not level else reason)
            diagnostics.append({"target_id": rid, "bbox": tuple(box), "known": region.known,
                                "direction": direction, "relative_near": round(near, 3),
                                "path_overlap": round(path, 3), "approaching": approaching,
                                "current_path_overlap": round(current_path, 3),
                                "expansion_per_s": round(expansion, 3), "quality": round(quality, 3),
                                "depth_age_s": round(t-region.seen_at, 3), "risk_score": round(score, 3),
                                "level": level, "reason": decision_reason})
            if level:
                action = "衝突注意" if level == 3 else "接近注意" if level == 2 else "障害物の可能性"
                message = (f"【{direction}】{region.label}: {action}（AI奥行き・{reason}）"
                           if region.known else f"{direction}障害物")
                alerts.append(Alert("ai_depth_collision" if region.known else "ai_depth_obstacle",
                                    level, rid, message,
                                    tuple(box), direction))
        self.diagnostics = diagnostics
        return alerts

    def _update(self, ctx, logits, expiry, history_expiry):
        t = ctx.timestamp
        if logits is None or np.ndim(logits) != 2 or not np.isfinite(logits).all():
            self.invalidate("奥行き出力が不正・判定困難")
            return
        height, width = ctx.image.shape[:2]
        shape = (160, max(48, round(height * 160 / width)))
        gray = cv2.resize(cv2.cvtColor(ctx.image, cv2.COLOR_BGR2GRAY), shape)
        if float(gray.mean()) < 8 or float(gray.std()) < 3:
            self.invalidate("暗さ・単色のため判定困難")
            return
        self._image_quality = min(1., float(gray.mean())/20., float(gray.std())/8.)
        z = cv2.resize(np.asarray(logits, np.float32), shape)
        # Model Zoo SCDepth transform: inverse depth = sigmoid(logits)*10 + .009.
        inv = 10. / (1. + np.exp(-np.clip(z, -30, 30))) + .009
        low, high = np.percentile(inv, [5, 95])
        if high-low < max(.02, float(np.median(inv)) * .01):
            self.invalidate("奥行きの差が不十分・判定困難")
            return
        # Preserve vertical structure before sigmoid saturation, especially on
        # the bottom road surface. These are frame-relative scores, not ranges.
        z_low, z_high = np.percentile(z, [5, 95])
        near_map = np.clip((z-z_low)/max(1e-6, z_high-z_low), 0, 1)
        log_inv = np.log(inv)
        pairs, drift = self._motion(gray, log_inv, t)
        sx, sy = shape[0]/width, shape[1]/height
        seen = set()
        known_boxes = [tuple(track.bbox) for track in ctx.tracks]
        for track in ctx.tracks:
            if not track.confirmed or not track.motion_valid or track.age < 3 or track.match_quality < .5:
                continue
            box = tuple(track.bbox)
            x1, y1, x2, y2 = scaled_box(box, sx, sy, shape)
            px, py = max(1, (x2-x1)//5), max(1, (y2-y1)//5)
            patch = near_map[y1+py:y2-py, x1+px:x2-px]
            raw = log_inv[y1+py:y2-py, x1+px:x2-px]
            if patch.size < 6:
                continue
            label = {"car": "車両", "truck": "車", "bus": "車", "person": "歩行者",
                     "bicycle": "自転車", "motorcycle": "二輪車"}.get(track.cls, "検出対象")
            self._remember(track.track_id, box, True, label, float(np.median(patch)),
                           float(np.median(raw)), pairs, drift, sx, sy, t, expiry)
            self.regions[track.track_id].quality *= min(1., max(.4, track.conf/.5)) * track.match_quality
            seen.add(track.track_id)
        for box, component in self._obstacles(near_map, known_boxes, sx, sy, shape, include_masks=True,
                                               exclusion_mask=self._vehicle_mask(near_map.shape)):
            choices = [(overlap(box, r.bbox), rid) for rid, r in self.regions.items()
                       if not r.known and rid not in seen and t-r.seen_at <= history_expiry]
            match, rid = max(choices, default=(0., 0))
            if match < .25:
                rid = self._next_unknown
                self._next_unknown -= 1
            x1, y1, x2, y2 = scaled_box(box, sx, sy, shape)
            selected = component[y1:y2, x1:x2]
            self._remember(rid, box, False, "未分類障害物", float(np.median(near_map[y1:y2, x1:x2][selected])),
                           float(np.median(log_inv[y1:y2, x1:x2][selected])), pairs, drift, sx, sy, t, history_expiry)
            seen.add(rid)
        # Keep a briefly missing unknown region only for re-identification; it
        # must not produce a warning until a fresh depth observation matches it.
        for rid, region in self.regions.items():
            if rid not in seen:
                region.observed = False
        self.regions = {rid: r for rid, r in self.regions.items()
                        if rid in seen or (not r.known and t-r.seen_at <= history_expiry)}
        self._previous = (gray, log_inv, t)
        self._tracking_gray, self._tracking_time = gray, t
        self._sample_time = t
        self.status = "相対奥行きで危険判定中" if self._image_quality >= .8 else "低画質・判定の信頼性低下"
        if self._motion_unstable:
            self.status = "旋回・揺れのため接近判定を保留"

    def _remember(self, rid, box, known, label, near, raw, pairs, drift, sx, sy, t, expiry):
        region = self.regions.get(rid)
        if region is None or t-region.seen_at > expiry or overlap(box, region.bbox) < .15:
            region = Region(rid, box, known, label, first_seen=t)
            self.regions[rid] = region
        # Avoid inventing temporal depth continuity when a global scale change is unobservable.
        region.depth_closing = 0.
        region.depth_trend_valid = False
        if region.history and drift is not None:
            dt = t-region.history[-1][0]
            if .12 <= dt <= expiry:
                region.depth_closing = (raw-region.history[-1][3]-drift)/dt
                region.depth_trend_valid = True
        region.bbox, region.near, region.seen_at = box, near, t
        region.track_valid = True
        region.observed = True
        region.history.append((t, near, .5*np.log(max(1., (box[2]-box[0])*(box[3]-box[1]))), raw, box))
        region.flow_expansion = region_expansion(pairs, box, sx, sy)
        region.quality = .65 if known else .5
        if region.flow_expansion is not None:
            region.quality += .25
        region.quality *= self._image_quality

    def _advance_unknown(self, ctx):
        """Sparse image tracking up to 12.5 Hz; never refresh the depth timestamp."""
        unknown = [r for r in self.regions.values() if not r.known and r.track_valid and r.observed]
        if not unknown or self._tracking_gray is None:
            return
        dt = ctx.timestamp-self._tracking_time
        if dt < .08:
            return
        if dt > .4:
            for region in unknown:
                region.track_valid = False
            return
        old = self._tracking_gray
        h, w = old.shape
        gray = cv2.resize(cv2.cvtColor(ctx.image, cv2.COLOR_BGR2GRAY), (w, h))
        sx, sy = w/ctx.image.shape[1], h/ctx.image.shape[0]
        mask = np.zeros_like(old)
        for region in unknown:
            x1, y1, x2, y2 = scaled_box(region.bbox, sx, sy, (w, h))
            mask[y1:y2, x1:x2] = 255
        points = cv2.goodFeaturesToTrack(old, 120, .02, 4, mask=mask)
        if points is None:
            for region in unknown:
                region.track_valid = False
            return
        nxt, ok, _ = cv2.calcOpticalFlowPyrLK(old, gray, points, None, winSize=(15, 15), maxLevel=2)
        back, back_ok, _ = cv2.calcOpticalFlowPyrLK(gray, old, nxt, None, winSize=(15, 15), maxLevel=2) if nxt is not None else (None, None, None)
        if back is None:
            for region in unknown:
                region.track_valid = False
            return
        p, q = points.reshape(-1, 2), nxt.reshape(-1, 2)
        good = ok.ravel().astype(bool) & back_ok.ravel().astype(bool) & (np.linalg.norm(back.reshape(-1, 2)-p, axis=1) < 1.)
        for region in unknown:
            x1, y1, x2, y2 = scaled_box(region.bbox, sx, sy, (w, h))
            inside = good & (p[:, 0] >= x1) & (p[:, 0] <= x2) & (p[:, 1] >= y1) & (p[:, 1] <= y2)
            if inside.sum() < 5:
                region.track_valid = False
                continue
            affine, hits = cv2.estimateAffinePartial2D(p[inside], q[inside], method=cv2.RANSAC, ransacReprojThreshold=1.5)
            scale = np.hypot(affine[0, 0], affine[1, 0]) if affine is not None else 0
            if affine is None or hits is None or hits.mean() < .6 or not .85 < scale < 1.15:
                region.track_valid = False
                continue
            corners = np.array([[x1, y1], [x2, y1], [x1, y2], [x2, y2]], np.float32) @ affine[:, :2].T + affine[:, 2]
            region.bbox = (float(np.clip(corners[:, 0].min(), 0, w-1)/sx),
                           float(np.clip(corners[:, 1].min(), 0, h-1)/sy),
                           float(np.clip(corners[:, 0].max(), 1, w)/sx),
                           float(np.clip(corners[:, 1].max(), 1, h)/sy))
        self._tracking_gray, self._tracking_time = gray, ctx.timestamp

    def _motion(self, gray, depth, t):
        self._motion_unstable = False
        if self._previous is None or gray.shape != self._previous[0].shape:
            return None, None
        old, old_depth, old_t = self._previous
        dt = t-old_t
        if not .12 <= dt <= 2.:
            return None, None
        pts = cv2.goodFeaturesToTrack(old, maxCorners=160, qualityLevel=.02, minDistance=5)
        if pts is None or len(pts) < 8:
            return None, None
        nxt, ok, _ = cv2.calcOpticalFlowPyrLK(old, gray, pts, None, winSize=(15, 15), maxLevel=2)
        if nxt is None:
            return None, None
        back, back_ok, _ = cv2.calcOpticalFlowPyrLK(gray, old, nxt, None, winSize=(15, 15), maxLevel=2)
        if back is None:
            return None, None
        p, q = pts.reshape(-1, 2), nxt.reshape(-1, 2)
        valid = ok.ravel().astype(bool) & back_ok.ravel().astype(bool) & (np.linalg.norm(back.reshape(-1, 2)-p, axis=1) < 1.5)
        h, w = gray.shape
        valid &= (q[:, 0] >= 0) & (q[:, 0] < w) & (q[:, 1] >= 0) & (q[:, 1] < h)
        p, q = p[valid], q[valid]
        if len(p) < 8:
            return None, None
        affine, inliers = cv2.estimateAffinePartial2D(p, q, method=cv2.RANSAC, ransacReprojThreshold=2.)
        if affine is None or inliers is None or inliers.sum() < 8:
            return None, None
        scale = float(np.hypot(affine[0, 0], affine[1, 0]))
        angle = abs(float(np.arctan2(affine[1, 0], affine[0, 0])))
        if scale < .7 or scale > 1.4 or angle > .12:
            self._motion_unstable = True
            return None, None
        # Remove rotation/translation, preserve expansion (including a full-width wall).
        rotation = affine[:, :2] / max(scale, 1e-6)
        motion = (q - (p @ rotation.T + affine[:, 2])) / dt
        drift = None
        if abs(scale-1.) < .015 and inliers.mean() >= .6:
            a, b = p[inliers.ravel() > 0].astype(int), q[inliers.ravel() > 0].astype(int)
            drift = float(np.median(depth[b[:, 1], b[:, 0]]-old_depth[a[:, 1], a[:, 0]]))
        return (q, motion), drift

    @staticmethod
    def _obstacles(near, known_boxes, sx, sy, shape, include_masks=False, exclusion_mask=None):
        h, w = near.shape
        # An expected ground trend grows towards the bottom. Flat upright patches
        # above it are candidates; do not trust the heuristic road mask as a veto.
        row_floor = np.percentile(near, 25, axis=1)
        yy = np.arange(h)/h
        start = int(h*.35)
        fit = np.polyfit(yy[start:], row_floor[start:], 1)
        expected = np.clip(np.polyval(fit, yy), 0, 1)[:, None]
        grad = cv2.Sobel(near, cv2.CV_32F, 0, 1, ksize=3)/8.
        upright = np.abs(grad) < max(.008, max(0., fit[0])/h * .55)
        mask = ((near > .65) & ((near-expected > .12) | upright)).astype(np.uint8)
        mask[:int(h*.20)] = 0
        if exclusion_mask is None:
            mask[int(h*.90):] = 0
        if exclusion_mask is not None:
            mask[exclusion_mask] = 0
        for box in known_boxes:
            x1, y1, x2, y2 = scaled_box(box, sx, sy, shape)
            mask[max(0, y1-2):min(h, y2+2), max(0, x1-2):min(w, x2+2)] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        boxes = []
        bottom_edge = int(h * .80)
        ranked = sorted(range(1, count), key=lambda i: stats[i, 4], reverse=True)
        for component_id in ranked:
            x, y, bw, bh, area = stats[component_id]
            if area < h*w*.008 or bh < h*.10 or bw < w*.025 or area/(bw*bh) < .3:
                continue
            # Hood/dashboard candidates often straddle the cut-off; rejecting
            # only pixels below it would leave a misleading upper fragment.
            bottom_height = max(0, y+bh-max(y, bottom_edge))
            if exclusion_mask is None and bottom_height / max(1, bh) >= .35:
                continue
            top_end = min(y+bh, bottom_edge) if exclusion_mask is None else y+bh
            if top_end-y < h*.10:
                continue
            box = (float(x/sx), float(y/sy), float((x+bw)/sx), float(top_end/sy))
            boxes.append((box, labels == component_id) if include_masks else box)
            if len(boxes) >= 12:
                break
        return boxes


def scaled_box(box, sx, sy, shape):
    w, h = shape
    return (int(np.clip(box[0]*sx, 0, w-1)), int(np.clip(box[1]*sy, 0, h-1)),
            int(np.clip(box[2]*sx, 1, w)), int(np.clip(box[3]*sy, 1, h)))


def region_expansion(pairs, box, sx, sy):
    if pairs is None:
        return None
    points, velocities = pairs
    x1, y1, x2, y2 = box[0]*sx, box[1]*sy, box[2]*sx, box[3]*sy
    keep = (points[:, 0] >= x1) & (points[:, 0] <= x2) & (points[:, 1] >= y1) & (points[:, 1] <= y2)
    if keep.sum() < 6:
        return None
    p, v = points[keep], velocities[keep]
    p, v = p-p.mean(axis=0), v-v.mean(axis=0)
    denom = float((p*p).sum())
    if denom < 20:
        return None
    expansion = float((p*v).sum()/denom)
    residual = np.linalg.norm(v-expansion*p, axis=1)
    return expansion if float(np.median(residual)) < 8. and abs(expansion) < 2. else None


def path_relation(box, polygon, shape):
    h, w = shape[:2]
    x, y = (box[0]+box[2])/2, min(h-1., box[3])
    left, right = w*.28, w*.72
    if polygon is not None and len(polygon) >= 3:
        y = float(np.clip(y, np.min(polygon[:, 1])+1e-3, np.max(polygon[:, 1])-1e-3))
        xs = []
        for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
            if (a[1] <= y < b[1]) or (b[1] <= y < a[1]):
                xs.append(float(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])))
        if len(xs) >= 2:
            left, right = min(xs), max(xs)
    band = max(5., (right-left)*.15)
    center = (left+right)/2
    direction = "左前" if x < center-band else "右前" if x > center+band else "正面"
    fraction = max(0., min(box[2], right)-max(box[0], left))/max(1., box[2]-box[0])
    return float(fraction), direction


def fuse_depth_alerts(legacy, depth):
    """One collision-family warning per known target; preserve unrelated warnings."""
    merged = list(legacy)
    family = {"collision", "following", "following_distance", "person_collision", "bicycle_collision", "motorcycle_collision"}
    for alert in depth:
        duplicates = [a for a in merged if a.target_id == alert.target_id and a.kind in family]
        if duplicates:
            strongest = max(duplicates, key=lambda a: a.level)
            if strongest.level > alert.level or (strongest.level == alert.level and strongest.kind in {"following", "following_distance"}):
                continue
            merged = [a for a in merged if a not in duplicates]
        merged.append(alert)
    return merged
