from __future__ import annotations

from typing import Protocol

import numpy as np


class InputSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> tuple[bool, np.ndarray]: ...

    def close(self) -> None: ...

    @property
    def fps(self) -> float: ...

    @property
    def frame_size(self) -> tuple[int, int]: ...

    @property
    def frame_count(self) -> int | None: ...

    def seek(self, frame_idx: int) -> bool: ...
