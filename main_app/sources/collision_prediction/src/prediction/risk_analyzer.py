from __future__ import annotations

from collections import defaultdict, deque

import cv2
import numpy as np

from src.prediction.intrusion import classify_vehicle_heading, is_cut_in_vehicle, is_pedestrian_rush
from src.prediction.threat_score import threat_level, threat_score
from src.prediction.ttc import TTCEstimator, bbox_area
from src.prediction.vehicle_facing import combine_collision_risk, estimate_facing
from src.types import Alert, SceneContext, TrackedObject
from src.utils.geometry import point_in_polygon


class RiskAnalyzer:
    """要件:
    - 自車レーン内滞在が一定時間以上のときだけ警告（横切り誤判定を防ぐ）
    - 物体が自車レーンを「出て行く軌跡」なら警告を出さない（横断完了は安全）
    """

    EGO_LANE_DWELL_SECONDS = 0.25
    FOLLOWING_CLOSING_MPS = 0.8

    def __init__(
        self,
        ttc_critical_s: float = 1.5,
        ttc_warn_s: float = 3.0,
        ego_lane_dwell_s: float = EGO_LANE_DWELL_SECONDS,
        following_closing_mps: float = FOLLOWING_CLOSING_MPS,
    ):
        self.ttc_critical_s = ttc_critical_s
        self.ttc_warn_s = ttc_warn_s
        self.ttc = TTCEstimator()
        self._speed_history: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=8))
        self._distance_history: dict[int, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=8))
        self._was_stopped: set[int] = set()
        self._facing_history = {}
        self._vehicle_sizes = defaultdict(lambda: deque(maxlen=8))
        self.ego_lane_dwell_s = ego_lane_dwell_s
        self.following_closing_mps = following_closing_mps
        # 自車レーンに入った時刻。フレームレートではなく実時間で滞在を判定する。
        self._ego_lane_entered_at: dict[int, float] = {}
        self._path_hits: dict[int, int] = {}
        self._path_last_frame: dict[int, int] = {}
        # 絶対速度推定器（Pipeline から後で注入される）
        self.absolute_velocity = None
        self._current_fps: float = 30.0
        self._absolute_cache: dict = {}
        # 描画用: フレーム毎の track_id → facing/heading ラベル
        self.last_labels: dict[int, dict] = {}

    def analyze(self, ctx: SceneContext, *, depth_trends: dict[int, float] | None = None) -> list[Alert]:
        alerts: list[Alert] = []
        frame_width = ctx.image.shape[1]
        frame_height = ctx.image.shape[0]
        present_ids: set[int] = set()
        # 絶対速度を一括計算してキャッシュ
        self._absolute_cache = {}
        self.last_labels = {}
        self._depth_trends = depth_trends or {}
        if self.absolute_velocity is not None:
            for track in ctx.tracks:
                self._absolute_cache[track.track_id] = self.absolute_velocity.estimate(
                    track, self._current_fps,
                    frame_height, frame_width, ctx.ego_motion,
                )
        for track in ctx.tracks:
            present_ids.add(track.track_id)
            if track.cls in {"car", "truck", "bus"}:
                self._vehicle_sizes[track.track_id].append((ctx.timestamp, .5*np.log(max(1., bbox_area(track.bbox)))))
            # 自車エゴモーション補正後の「真の相対速度」を使う
            rel_vx, rel_vy = self._relative_velocity(track, ctx)
            speed_px = float(np.hypot(rel_vx, rel_vy))
            self._speed_history[track.track_id].append(speed_px)
            if track.distance_m is not None:
                self._distance_history[track.track_id].append((ctx.timestamp, track.distance_m))
            # 滞在時間更新（自車レーン内に居る連続時間）
            self._update_dwell(track, ctx)
            if self._is_sidewalk_person(track, ctx.road_mask) and not self._is_side_entry_risk(track, ctx, (rel_vx, rel_vy)):
                continue
            # 真に静止している物体（背景フローとほぼ一致）は警告対象外
            if self._is_background_static(track, rel_vx, rel_vy, ctx):
                continue
            alerts.extend(self._pedestrian_alerts(track, ctx, frame_width, (rel_vx, rel_vy)))
            alerts.extend(self._vehicle_alerts(track, ctx, (rel_vx, rel_vy)))
            # 前車発進は自車が停車中のときだけ判定（自車前進中の誤発火を抑制）
            self_stopped = (ctx.ego_motion is not None and not ctx.ego_motion.is_moving
                            and ctx.ego_motion.confidence >= .5)
            if self_stopped:
                front_start = self._front_start(track, ctx)
                if front_start is not None:
                    alerts.append(front_start)
            else:
                self._was_stopped.discard(track.track_id)
        # 居なくなったトラックの滞在カウンタを掃除
        for tid in list(self._ego_lane_entered_at):
            if tid not in present_ids:
                self._ego_lane_entered_at.pop(tid, None)
                self._distance_history.pop(tid, None)
                self._speed_history.pop(tid, None)
                self._path_hits.pop(tid, None)
                self._path_last_frame.pop(tid, None)
        self._vehicle_sizes = defaultdict(lambda: deque(maxlen=8), {k: v for k, v in self._vehicle_sizes.items() if k in present_ids})
        self._was_stopped.intersection_update(present_ids)
        self._facing_history = {k: v for k, v in self._facing_history.items() if k in present_ids}
        return alerts

    def _update_dwell(self, track: TrackedObject, ctx: SceneContext) -> None:
        bottom = self._bottom_center(track.bbox)
        if point_in_polygon(bottom, ctx.lanes.ego_lane_polygon):
            entered_at = self._ego_lane_entered_at.get(track.track_id)
            if entered_at is None or ctx.timestamp < entered_at:
                self._ego_lane_entered_at[track.track_id] = ctx.timestamp
        else:
            self._ego_lane_entered_at.pop(track.track_id, None)

    def _dwell_seconds(self, track_id: int, timestamp: float) -> float:
        entered_at = self._ego_lane_entered_at.get(track_id)
        return max(0.0, timestamp - entered_at) if entered_at is not None else 0.0

    def _is_dwelling(self, track_id: int, timestamp: float) -> bool:
        return self._dwell_seconds(track_id, timestamp) >= self.ego_lane_dwell_s

    @staticmethod
    def _is_leaving_lane(track: TrackedObject, ego_lane_polygon, rel_v: tuple[float, float]) -> bool:
        """物体が自車レーンから外側へ向かっているか。横断完了は安全とみなす。"""
        if ego_lane_polygon is None:
            return False
        lane_center_x = float(np.mean(ego_lane_polygon[:, 0]))
        bx = (track.bbox[0] + track.bbox[2]) / 2
        # 左右どちら寄りにいて、その方向にさらに移動中なら「離れて行く」
        if bx < lane_center_x and rel_v[0] < -2.0:
            return True
        if bx > lane_center_x and rel_v[0] > 2.0:
            return True
        return False

    def _relative_velocity(self, track: TrackedObject, ctx: SceneContext) -> tuple[float, float]:
        """物体の画面速度から、その位置の背景フローを差し引いた相対速度を返す。"""
        if ctx.ego_motion is None or not ctx.ego_motion.is_moving:
            return track.velocity
        cx = (track.bbox[0] + track.bbox[2]) / 2
        cy = (track.bbox[1] + track.bbox[3]) / 2
        local_flow = getattr(ctx.ego_motion, "local_background_flow_at", None)
        if local_flow is None:
            return track.velocity
        background = local_flow(cx, cy)
        if background is None:
            return track.velocity
        bg_vx = float(np.clip(background[0], -3.0, 3.0))
        bg_vy = float(np.clip(background[1], -4.0, 4.0))
        return (track.velocity[0] - bg_vx, track.velocity[1] - bg_vy)

    @staticmethod
    def _estimated_background_flow(x: float, y: float, ctx: SceneContext) -> tuple[float, float]:
        """消失点と自車前進量から、(x, y) における背景フローを線形モデルで推定する。

        自車が前進すると、画像上のあらゆる点は「消失点から放射状に外向き」に流れる。
        点 p の背景フロー方向 = (p - vp) / |p - vp|、大きさは |p - vp| に比例（簡易モデル）。
        """
        ego = ctx.ego_motion
        if ego is None or ego.vanishing_point is None:
            return (0.0, 0.0)
        vp_x, vp_y = ego.vanishing_point
        dx, dy = x - vp_x, y - vp_y
        dist = float(np.hypot(dx, dy))
        if dist < 1e-3:
            return (0.0, 0.0)
        # 路面前進フロー (forward_flow_px) は消失点から下方向遠点（画像中心下端）の流速のスケール
        h = ctx.image.shape[0]
        ref_distance = max(1.0, h - vp_y)
        radial = ego.forward_flow_px * (dist / ref_distance)
        return (radial * dx / dist + ego.lateral_flow_px, radial * dy / dist)

    @staticmethod
    def _is_background_static(track: TrackedObject, rel_vx: float, rel_vy: float, ctx: SceneContext) -> bool:
        """相対速度が小さく、自車が動いている場合のみ「背景と同じ動き=静止物」と判定する。"""
        if ctx.ego_motion is None or not ctx.ego_motion.is_moving:
            return False
        # 物体クラスが人/車なら静止物判定はしない（駐車車両は別途処理してもよいが今は素通し）
        if track.cls in {"person", "bicycle", "motorcycle"}:
            return False
        rel_speed = float(np.hypot(rel_vx, rel_vy))
        # 自車前進速度の 25% 未満 → 背景と同じ動き → 静止物とみなす
        return rel_speed < max(0.5, 0.25 * ctx.ego_motion.forward_flow_px)

    def _pedestrian_alerts(self, track: TrackedObject, ctx: SceneContext, frame_width: int,
                            relative_velocity: tuple[float, float]) -> list[Alert]:
        if track.cls not in {"person", "bicycle"}:
            return []
        alerts: list[Alert] = []
        # 滞在判定: 連続 N フレーム自車レーン内に居続けたときだけ「衝突注意」
        dwelling = self._is_dwelling(track.track_id, ctx.timestamp)
        leaving = self._is_leaving_lane(track, ctx.lanes.ego_lane_polygon, relative_velocity)
        # 飛び出し判定は強化版（相対速度ベース + 出現直後 + 急加速）
        rel_track = TrackedObject(
            track_id=track.track_id, bbox=track.bbox, cls=track.cls, conf=track.conf,
            velocity=relative_velocity, history=track.history, age=track.age, distance_m=track.distance_m,
            confirmed=track.confirmed, motion_valid=track.motion_valid, match_quality=track.match_quality,
        )
        rushing = is_pedestrian_rush(rel_track, ctx.lanes.ego_lane_polygon, frame_width)
        side_entry = self._is_side_entry_risk(track, ctx, relative_velocity)
        # 自転車は専用ラベル、それ以外は歩行者ラベル
        subject = "自転車" if track.cls == "bicycle" else "歩行者"
        if dwelling and not leaving:
            alerts.append(self._track_alert(f"{track.cls}_collision", 3, track, ctx, f"{subject}衝突注意"))
        elif rushing or side_entry:
            alerts.append(self._track_alert(f"{track.cls}_rush", 3, track, ctx, f"{subject}飛び出し注意"))
        return alerts

    @staticmethod
    def _is_side_entry_risk(track: TrackedObject, ctx: SceneContext,
                            rel_v: tuple[float, float]) -> bool:
        """レーン外の端から自車レーンへ入る歩行者/自転車を早めに拾う。"""
        if track.cls not in {"person", "bicycle"} or ctx.lanes.ego_lane_polygon is None:
            return False
        polygon = ctx.lanes.ego_lane_polygon
        frame_h, frame_w = ctx.image.shape[:2]
        x1, y1, x2, y2 = track.bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        bottom = ((x1 + x2) / 2, y2)
        if point_in_polygon(bottom, polygon):
            return False

        intersections = []
        sample_y = float(np.clip(bottom[1], np.min(polygon[:, 1])+1e-3, np.max(polygon[:, 1])-1e-3))
        for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
            if (a[1] <= sample_y < b[1]) or (b[1] <= sample_y < a[1]):
                intersections.append(float(a[0] + (sample_y-a[1])*(b[0]-a[0])/(b[1]-a[1])))
        if len(intersections) < 2:
            return False
        lane_left, lane_right = min(intersections), max(intersections)
        lane_top = float(np.min(polygon[:, 1]))
        vx, vy = rel_v
        speed = float(np.hypot(vx, vy))
        from_left = cx < lane_left and vx > 0
        from_right = cx > lane_right and vx < 0
        if not (from_left or from_right):
            return False

        # 画面上部の歩行者候補は距離感が不確かなので、路面ゾーン付近だけ早期警告する。
        if y2 < lane_top - frame_h * 0.08:
            return False

        gap = lane_left - cx if from_left else cx - lane_right
        if gap < 0:
            return False
        edge_margin = frame_w * 0.16
        near_screen_edge = x1 <= edge_margin or x2 >= frame_w - edge_margin
        close_enough = gap <= max(48.0, frame_w * 0.38) or near_screen_edge
        speed_threshold = 0.7 if track.cls == "bicycle" else 0.9
        if speed < speed_threshold or abs(vx) < speed_threshold:
            return False

        horizon = 30.0 if track.cls == "bicycle" else 24.0
        projected_center = (cx + vx * horizon, cy + vy * horizon)
        projected_bottom = (bottom[0] + vx * horizon, bottom[1] + vy * horizon)
        will_enter = (
            point_in_polygon(projected_center, polygon)
            or point_in_polygon(projected_bottom, polygon)
            or (from_left and projected_center[0] >= lane_left)
            or (from_right and projected_center[0] <= lane_right)
        )
        if not track.confirmed or not track.motion_valid or track.match_quality < .5:
            return False
        return close_enough and (will_enter or near_screen_edge)

    @staticmethod
    def _is_rush_relative(track: TrackedObject, rel_v: tuple[float, float],
                          ego_lane_polygon: np.ndarray | None, frame_width: int) -> bool:
        if ego_lane_polygon is None:
            return False
        rel_speed = float(np.hypot(*rel_v))
        if rel_speed < 6.0:
            return False
        # 自車レーンの中心方向に向かっているか
        cx = float(np.mean(ego_lane_polygon[:, 0]))
        bx = (track.bbox[0] + track.bbox[2]) / 2
        if (cx - bx) * rel_v[0] <= 0:
            return False
        return True

    def _vehicle_alerts(self, track: TrackedObject, ctx: SceneContext,
                        relative_velocity: tuple[float, float]) -> list[Alert]:
        if track.cls not in {"car", "truck", "bus", "motorcycle", "candidate"}:
            return []
        alerts: list[Alert] = []
        bottom = self._bottom_center(track.bbox)
        in_ego_lane = point_in_polygon(bottom, ctx.lanes.ego_lane_polygon)
        motion_reliable = track.confirmed and track.motion_valid
        # 進行方向の質的ラベル
        heading = classify_vehicle_heading(track, ctx.lanes.ego_lane_polygon)
        # 相手車の向きは「自車レーン内 or BB が画面下 70% 以内（近距離）」のみで推定（負荷削減）
        bbox_cy = (track.bbox[1] + track.bbox[3]) / 2
        is_near_or_in_lane = in_ego_lane or bbox_cy > ctx.enhanced.shape[0] * 0.5
        facing = estimate_facing(ctx.enhanced, track.bbox, relative_velocity[1]) if is_near_or_in_lane else "unknown"
        previous = self._facing_history.get(track.track_id)
        if previous is None or ctx.timestamp < previous[1] or ctx.timestamp-previous[1] > .6:
            previous = ("unknown", ctx.timestamp, 0)
        hits = previous[2] + 1 if facing == previous[0] else 1
        self._facing_history[track.track_id] = (facing, ctx.timestamp, hits)
        if facing == "rear" and hits < 2:
            facing = "unknown"
        # 描画用にキャッシュ（ユーザーが画面で向きを確認できる）
        self.last_labels[track.track_id] = {"facing": facing, "heading": heading}
        risk_factor = combine_collision_risk(facing, heading)
        # リスク係数が非常に低い（リア向き + 離反など）なら警告対象外
        if risk_factor < 0.15:
            return alerts
        # 離反車（leaving）でも fronting がはっきりしてれば警告（バック車）
        if heading == "leaving" and facing != "front":
            return alerts
        # cut_in 判定も相対速度で（直進対向車を誤判定しないため）
        rel_track = TrackedObject(
            track_id=track.track_id, bbox=track.bbox, cls=track.cls, conf=track.conf,
            velocity=relative_velocity, history=track.history, age=track.age, distance_m=track.distance_m,
            confirmed=track.confirmed, motion_valid=track.motion_valid, match_quality=track.match_quality,
        )
        entering_path = (
            motion_reliable
            and (track.distance_m is None or track.distance_m <= 32.0)
            and bottom[1] >= ctx.image.shape[0] * 0.48
            and is_cut_in_vehicle(rel_track, ctx.lanes.ego_lane_polygon)
        )
        if entering_path:
            last_frame = self._path_last_frame.get(track.track_id)
            if last_frame is not None and ctx.frame_idx == last_frame + 1:
                self._path_hits[track.track_id] = self._path_hits.get(track.track_id, 0) + 1
            else:
                self._path_hits[track.track_id] = 1
            self._path_last_frame[track.track_id] = ctx.frame_idx
        else:
            self._path_hits.pop(track.track_id, None)
            self._path_last_frame.pop(track.track_id, None)
        stable_legacy_track = track.match_quality >= 0.9 and track.age >= 5
        if entering_path and (self._path_hits.get(track.track_id, 0) >= 2 or stable_legacy_track):
            alerts.append(self._track_alert("cut_in", 3, track, ctx, "対向車右左折侵入注意"))
        # 自車レーン内に「連続滞在」している車両のみ衝突対象
        if not in_ego_lane or not self._is_dwelling(track.track_id, ctx.timestamp):
            return alerts
        if not motion_reliable:
            return alerts
        if self._is_leaving_lane(track, ctx.lanes.ego_lane_polygon, relative_velocity):
            return alerts

        ttc_value = self.ttc.update(track.track_id, ctx.timestamp, track.distance_m, bbox_area(track.bbox))
        # 絶対速度が信頼できる時、純粋な相対接近速度を算出
        absv = self._absolute_cache.get(track.track_id)
        relative_closing = 0.0
        if absv is not None and absv.confidence > 0.4:
            ego_kmh = self.absolute_velocity.speed_source.get_speed_kmh()
            ego_mps = (ego_kmh / 3.6) if ego_kmh is not None else 0.0
            relative_closing = ego_mps - absv.longitudinal
        # 統合危険度スコア算出
        dwell_seconds = self._dwell_seconds(track.track_id, ctx.timestamp)
        score = threat_score(
            distance_m=track.distance_m, ttc_s=ttc_value,
            heading=heading, facing=facing,
            relative_closing_mps=relative_closing,
            in_ego_lane=in_ego_lane, dwell_seconds=dwell_seconds,
        )
        level = threat_level(score)
        lead = facing == "rear" and self._stable_lead(track, ctx, relative_velocity)
        depth_trend = self._depth_trends.get(track.track_id)
        size_rate = self._size_rate(track.track_id)
        closing = size_rate > .08 or (size_rate > .04 and depth_trend is not None and depth_trend > .06)
        if level >= 3:
            ttc_str = f" TTC {ttc_value:.1f}s" if ttc_value is not None else ""
            alerts.append(self._track_alert("collision", 3, track, ctx, f"衝突注意 (脅威度{int(score*100)}){ttc_str}"))
        elif level == 2:
            ttc_str = f" TTC {ttc_value:.1f}s" if ttc_value is not None else ""
            if lead and closing:
                alerts.append(self._track_alert("following", 2, track, ctx, "車間注意"))
            else:
                alerts.append(self._track_alert("collision", 2, track, ctx, "前方接近注意"))

        following = self._following_distance_alert(track, ctx) if lead and closing else None
        if lead and closing and track.distance_m is None and depth_trend is not None and depth_trend > .06:
            following = self._track_alert("following", 2, track, ctx, "車間注意")
        if following is not None:
            alerts.append(following)
        return alerts

    def _following_distance_alert(self, track: TrackedObject, ctx: SceneContext) -> Alert | None:
        """車間警告は AND 条件で:
          - 距離 < 8m (絶対) → 警告
          - 距離 < 15m AND 距離縮小 (closing) → 警告
        """
        if track.distance_m is None:
            return None
        # 絶対的に近すぎる
        if track.distance_m < 8.0:
            return self._track_alert("following_distance", 2, track, ctx, f"車間距離注意 {track.distance_m:.1f}m")
        # 接近中（時系列回帰で一定以上のm/sで縮まっている）
        if self._is_getting_closer(track.track_id) and track.distance_m < 15.0:
            return self._track_alert("following_distance", 2, track, ctx, f"車間接近 {track.distance_m:.1f}m")
        return None

    def _is_getting_closer(self, track_id: int) -> bool:
        """距離が連続的に縮んでいるか（FPSに依存しない時系列回帰）。"""
        hist = self._distance_history[track_id]
        if len(hist) < 4:
            return False
        data = np.asarray(list(hist)[-4:], dtype=np.float32)
        times = data[:, 0] - data[0, 0]
        if float(times[-1]) <= 0:
            return False
        slope = float(np.polyfit(times, data[:, 1], 1)[0])
        return slope < -self.following_closing_mps

    def _size_rate(self, tid):
        samples = list(self._vehicle_sizes.get(tid, ()))
        if len(samples) < 3 or samples[-1][0]-samples[0][0] < .12:
            return 0.
        data = np.asarray(samples)
        return float(np.polyfit(data[:, 0]-data[0, 0], data[:, 1], 1)[0])

    def _stable_lead(self, track, ctx, relative_velocity):
        """Position supports a rear observation; it never establishes facing itself."""
        polygon = ctx.lanes.ego_lane_polygon
        if polygon is None or not track.confirmed or not track.motion_valid or track.match_quality < .7:
            return False
        x, y = self._bottom_center(track.bbox)
        if not point_in_polygon((x, y), polygon) or self._dwell_seconds(track.track_id, ctx.timestamp) < .25:
            return False
        if abs(relative_velocity[0]) > max(1.5, ctx.image.shape[1] * .025):
            return False
        crossings = []
        for a, b in zip(polygon, np.roll(polygon, -1, axis=0)):
            if (a[1] <= y < b[1]) or (b[1] <= y < a[1]):
                crossings.append(float(a[0] + (y-a[1]) * (b[0]-a[0]) / (b[1]-a[1])))
        if len(crossings) < 2:
            return False
        left, right = min(crossings), max(crossings)
        return abs(x - (left+right)/2) <= .4 * (right-left)

    def _front_start(self, track: TrackedObject, ctx: SceneContext) -> Alert | None:
        if (not track.confirmed or not track.motion_valid or track.match_quality < .7
                or self.last_labels.get(track.track_id, {}).get("facing") != "rear"
                or not self._stable_lead(track, ctx, self._relative_velocity(track, ctx))):
            self._was_stopped.discard(track.track_id)
            return None
        eligible = [t for t in ctx.tracks if t.cls in {"car", "truck", "bus"}
                    and t.confirmed and point_in_polygon(self._bottom_center(t.bbox), ctx.lanes.ego_lane_polygon)]
        if not eligible or max(eligible, key=lambda t: t.bbox[3]).track_id != track.track_id:
            return None
        if track.cls not in {"car", "truck", "bus"} or not point_in_polygon(self._bottom_center(track.bbox), ctx.lanes.ego_lane_polygon):
            return None
        hist = self._speed_history[track.track_id]
        if len(hist) < 8:
            return None
        recent = list(hist)[-8:]
        current = recent[-1]
        # まず: 過去 6 フレームの最大値が小さければ stopped 状態として記録
        if max(recent[:6]) < 0.5:
            self._was_stopped.add(track.track_id)
        # 既に stopped 認定済 + 現在が急発進速度 (>3.0) → 警告
        depth_trend = self._depth_trends.get(track.track_id)
        size_rate = self._size_rate(track.track_id)
        leaving = size_rate < -.08 or (size_rate < -.04 and depth_trend is not None and depth_trend < -.06)
        if track.track_id in self._was_stopped and current > 3.0 and leaving:
            self._was_stopped.discard(track.track_id)
            return self._track_alert("front_start", 1, track, ctx, "前車発進")
        return None

    def _track_alert(self, kind: str, level: int, track: TrackedObject, ctx: SceneContext, message: str) -> Alert:
        direction = self._direction_for_track(track, ctx)
        return Alert(kind, level, track.track_id, f"【{direction}】{message}", track.bbox, direction)

    @staticmethod
    def _direction_for_track(track: TrackedObject, ctx: SceneContext) -> str:
        """自車レーン/走行台形の同じ奥行きにおける左右幅で方向を判定する。"""
        polygon = ctx.lanes.ego_lane_polygon
        x, y = RiskAnalyzer._bottom_center(track.bbox)
        if polygon is None or len(polygon) < 3:
            center = ctx.image.shape[1] / 2.0
            half_width = ctx.image.shape[1] * 0.22
        else:
            ys = polygon[:, 1]
            y = float(np.clip(y, float(np.min(ys)) + 1.0, float(np.max(ys)) - 1.0))
            intersections: list[float] = []
            for start, end in zip(polygon, np.roll(polygon, -1, axis=0)):
                x1, y1 = float(start[0]), float(start[1])
                x2, y2 = float(end[0]), float(end[1])
                if (y1 <= y < y2) or (y2 <= y < y1):
                    ratio = (y - y1) / (y2 - y1)
                    intersections.append(x1 + ratio * (x2 - x1))
            if len(intersections) >= 2:
                left, right = min(intersections), max(intersections)
                center = (left + right) / 2.0
                half_width = max(12.0, (right - left) / 2.0)
            else:
                center = float(np.mean(polygon[:, 0]))
                half_width = max(12.0, (float(np.max(polygon[:, 0])) - float(np.min(polygon[:, 0])))/2.0)
        # 中央30%を中央扱いにして、わずかな検出揺れで左右ラベルが反転しないようにする。
        offset = x - center
        center_band = half_width * 0.30
        if offset < -center_band:
            return "左"
        if offset > center_band:
            return "右"
        return "中央"

    @staticmethod
    def _is_sidewalk_person(track: TrackedObject, road_mask: np.ndarray | None) -> bool:
        if track.cls != "person" or road_mask is None:
            return False
        x, y = RiskAnalyzer._bottom_center(track.bbox)
        h, w = road_mask.shape[:2]
        xi = int(np.clip(x, 0, w - 1))
        yi = int(np.clip(y, 0, h - 1))
        if road_mask[yi, xi] == 2:
            kernel = road_mask[max(0, yi - 5) : min(h, yi + 6), max(0, xi - 5) : min(w, xi + 6)]
            return not np.any(kernel == 1)
        return False

    @staticmethod
    def _bottom_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
        x1, _, x2, y2 = bbox
        return (x1 + x2) / 2, y2

def zone_mask(shape: tuple[int, int], polygon: np.ndarray | None) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if polygon is not None:
        cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
    return mask
