"""未接続のセンサーを後から追加するための、ハード非依存の受け口。"""
from __future__ import annotations

import math
import time
from typing import Protocol, Callable
from PySide6.QtCore import QObject, Signal


class SensorAdapter(Protocol):
    def start(self, emit: Callable[[dict], None]) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...


class SensorHub(QObject):
    status_changed = Signal(str)
    obstacle = Signal(str, object, int)
    impact = Signal(int)
    _received = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.adapter = None
        self.status = '未接続'
        self._received.connect(self._receive)

    def set_adapter(self, adapter: SensorAdapter | None) -> None:
        if self.is_running():
            raise RuntimeError('センサーを停止してから変更してください')
        self.adapter = adapter
        self._set_status('未接続' if adapter is None else '待機')

    def _set_status(self, status: str) -> None:
        self.status = status
        self.status_changed.emit(status)

    def is_running(self) -> bool:
        return self.adapter is not None and bool(self.adapter.is_running())

    def start(self) -> None:
        if self.adapter is None:
            self._set_status('未接続')
            return
        if self.is_running():
            return
        try:
            self._set_status('準備中')
            self.adapter.start(self.submit)
            if not self.is_running():
                raise RuntimeError('センサーの開始を確認できません')
            self._set_status('監視中')
        except Exception:
            self._set_status('異常')
            raise

    def stop(self) -> None:
        if self.adapter is None:
            self._set_status('未接続')
            return
        try:
            if self.is_running():
                self.adapter.stop()
            if self.is_running():
                raise RuntimeError('センサーの停止を確認できません')
            self._set_status('待機')
        except Exception:
            self._set_status('異常')
            raise

    def submit(self, event: dict) -> None:
        """アダプターのスレッドから呼べる。信号を介してメインスレッドで扱う。"""
        self._received.emit(event)

    def _receive(self, event) -> None:
        if not isinstance(event, dict):
            return
        if event.get('type') == 'obstacle':
            side = event.get('side')
            if side not in ('left', 'right'):
                return
            distance = event.get('distance_m')
            if distance is None:
                self.obstacle.emit(side, None, 0)
                return
            try:
                distance = float(distance)
                level = int(event.get('level', 2))
            except (TypeError, ValueError):
                return
            if not math.isfinite(distance) or distance < 0 or level not in (2, 3):
                return
            self.obstacle.emit(side, distance, level)
        elif event.get('type') == 'impact' and event.get('triggered') is True:
            try:
                timestamp = int(event.get('timestamp_ns', time.time_ns()))
            except (TypeError, ValueError):
                return
            if timestamp > 0:
                self.impact.emit(timestamp)
