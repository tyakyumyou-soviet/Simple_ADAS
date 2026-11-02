"""自車速度の抽象化。視覚推定と OBD2 接続を差し替え可能にする。

使用側は SpeedSource インターフェースだけ知っていればよい。
将来 OBD2 配線時は ObdSpeedSource を差し込むだけで動く。
"""
from __future__ import annotations

from typing import Protocol

from src.types import EgoMotionState


class SpeedSource(Protocol):
    """速度情報の供給源。"""

    def get_speed_kmh(self) -> float | None:
        """実速度 km/h を返す。視覚推定では None になる場合あり。"""
        ...

    def get_speed_level(self) -> str:
        """質的レベル: 'stop' | 'slow' | 'moderate' | 'fast'."""
        ...

    def is_moving(self) -> bool:
        ...


class VisualSpeedSource:
    """EgoMotionState から速度情報を派生させる視覚推定実装。"""

    def __init__(self) -> None:
        self._state: EgoMotionState = EgoMotionState.stationary()

    def update(self, state: EgoMotionState) -> None:
        self._state = state

    def get_speed_kmh(self) -> float | None:
        return self._state.speed_kmh

    def get_speed_level(self) -> str:
        return self._state.speed_level

    def is_moving(self) -> bool:
        return self._state.is_moving


class ObdSpeedSource:
    """OBD2 接続時に使う実装スタブ。将来 python-obd 等を組み込む。"""

    LEVELS = ((1.0, "stop"), (15.0, "slow"), (45.0, "moderate"), (float("inf"), "fast"))

    def __init__(self) -> None:
        self._kmh: float | None = None

    def feed(self, kmh: float | None) -> None:
        """外部スレッド/コールバックから OBD2 値を流し込む。"""
        self._kmh = kmh

    def get_speed_kmh(self) -> float | None:
        return self._kmh

    def get_speed_level(self) -> str:
        if self._kmh is None:
            return "stop"
        for limit, label in self.LEVELS:
            if self._kmh < limit:
                return label
        return "fast"

    def is_moving(self) -> bool:
        return (self._kmh or 0.0) > 1.0
