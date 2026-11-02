from __future__ import annotations

from dataclasses import replace

from src.types import Alert


class AlertManager:
    def __init__(self):
        self._last_emit: dict[tuple[int | None, str], float] = {}
        self._cooldown = {
            "collision": 0.5,
            "ldw": 1.0,
            "front_start": 5.0,
            "following": 1.0,
            "pedestrian": 0.8,
            "cut_in": 0.8,
            "red_signal": 1.0,
        }
        self._active: list[tuple[float, Alert]] = []
        self.last_emitted: list[Alert] = []

    def update(self, alerts: list[Alert], timestamp: float, present_ids=None) -> list[Alert]:
        emitted: list[Alert] = []
        if present_ids is not None:
            self._active = [(ts, a) for ts, a in self._active
                            if a.kind not in {"front_start", "following", "following_distance"} or a.target_id in present_ids]
        self._last_emit = {key: ts for key, ts in self._last_emit.items() if 0 <= timestamp-ts <= 60}
        depth_keys = {(a.target_id, a.kind) for a in alerts if a.kind.startswith("ai_depth_")}
        self._active = [(ts, a) for ts, a in self._active
                        if not a.kind.startswith("ai_depth_") or (a.target_id, a.kind) in depth_keys]
        for alert in sorted(alerts, key=lambda item: item.level, reverse=True):
            key = (alert.target_id, alert.kind)
            self._active = [(ts, alert if (a.target_id, a.kind) == key else a) for ts, a in self._active]
            cooldown = self._cooldown.get(alert.kind, 1.0)
            if timestamp - self._last_emit.get(key, -999.0) >= cooldown:
                self._last_emit[key] = timestamp
                emitted.append(alert)
                self._active = [(ts, a) for ts, a in self._active if (a.target_id, a.kind) != key]
                self._active.append((timestamp, alert))
        self.last_emitted = emitted
        self._active = [(ts, alert) for ts, alert in self._active if 0 <= timestamp - ts <= 1.5]
        current = [replace(alert) for _, alert in self._active]
        return sorted(current, key=lambda item: item.level, reverse=True)[:5]
