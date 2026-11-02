"""Metrics for comparing camera output with application throughput."""
from __future__ import annotations

import math


def camera_follow_ratio(rate: float, capture_fps: float | None) -> float | None:
    """Return throughput relative to measured input, or None until measurable."""
    if capture_fps is None or not math.isfinite(capture_fps) or capture_fps <= 0:
        return None
    if not math.isfinite(rate) or rate <= 0:
        return None
    # Independently sampled windows can differ slightly even when all frames keep up.
    return min(1.0, rate / capture_fps)
