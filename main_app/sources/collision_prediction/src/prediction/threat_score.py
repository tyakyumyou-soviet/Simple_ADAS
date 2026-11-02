"""統合危険度スコアの算出。

入力:
    distance_m: 距離 (m)
    ttc_s: TTC (s) — None なら NaN扱い
    heading: "approaching"/"leaving"/"lateral"/"static"/"unknown"
    facing: "front"/"rear"/"side"/"unknown"
    relative_closing_mps: 相対接近速度 (m/s) — 自車速度 - 相手車絶対前進速度
    in_ego_lane: 自車レーン内か
    dwell_seconds: 自車レーン連続滞在時間（秒）

出力: 0-1 のスコア
    < 0.3 : 安全 (警告なし)
    0.3-0.6: warn
    0.6-1.0: critical

スコアは加点・減点の合成。
"""
from __future__ import annotations

import math


def threat_score(
    distance_m: float | None,
    ttc_s: float | None,
    heading: str,
    facing: str,
    relative_closing_mps: float,
    in_ego_lane: bool,
    dwell_seconds: float,
) -> float:
    s = 0.0
    # 距離項: 近いほど高い (5m=1.0, 30m=0.0)
    if distance_m is not None:
        s += max(0.0, min(1.0, (30.0 - distance_m) / 25.0)) * 0.30
    # TTC 項: 短いほど高い (1s=1.0, 5s=0.0)
    if ttc_s is not None and not math.isnan(ttc_s):
        s += max(0.0, min(1.0, (5.0 - ttc_s) / 4.0)) * 0.30
    # heading 項: approaching で +0.15, leaving で -0.20
    if heading == "approaching":
        s += 0.15
    elif heading == "leaving":
        s -= 0.20
    elif heading == "lateral":
        s += 0.05
    # facing 項: front で +0.15, rear で -0.10
    if facing == "front":
        s += 0.15
    elif facing == "rear":
        s -= 0.10
    # 相対接近速度: +mps なら危険、-なら安全
    if relative_closing_mps > 0:
        s += min(0.20, relative_closing_mps / 30.0 * 0.20)
    elif relative_closing_mps < -2.0:
        s -= 0.10
    # 自車レーン内かつ連続滞在で boost
    if in_ego_lane:
        s += 0.10
        if dwell_seconds >= 0.25:
            s += 0.10
    return max(0.0, min(1.0, s))


def threat_level(score: float) -> int:
    """スコアから警告レベルを決定。

    0: 警告なし (< 0.3)
    1: info (0.3-0.45)
    2: warn (0.45-0.65)
    3: critical (>= 0.65)
    """
    if score < 0.30:
        return 0
    if score < 0.45:
        return 1
    if score < 0.65:
        return 2
    return 3
