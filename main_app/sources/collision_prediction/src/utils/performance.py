from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def summarize_performance(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Pipeline が返す処理時間を、比較可能なp50/p95統計へ集約する。"""
    process_values = [float(sample["process_ms"]) for sample in samples if "process_ms" in sample]
    stage_values: dict[str, list[float]] = defaultdict(list)
    frame_age_values = [float(sample["frame_age_ms"]) for sample in samples if "frame_age_ms" in sample]
    for sample in samples:
        for name, value in sample.get("stage_ms", {}).items():
            stage_values[name].append(float(value))
    lane_detected = [bool(sample.get("lane_detected", False)) for sample in samples if "lane_detected" in sample]
    return {
        "frames": len(samples),
        "process_ms": _summary(process_values),
        "stage_ms": {name: _summary(values) for name, values in sorted(stage_values.items())},
        "frame_age_ms": _summary(frame_age_values),
        "lane_detected_ratio": float(sum(lane_detected) / len(lane_detected)) if lane_detected else 0.0,
        "lane_state_counts": _counts(sample.get("lane_state", "unknown") for sample in samples),
    }


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0}
    data = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(data.mean()),
        "p50": float(np.percentile(data, 50)),
        "p95": float(np.percentile(data, 95)),
    }


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return dict(sorted(counts.items()))
