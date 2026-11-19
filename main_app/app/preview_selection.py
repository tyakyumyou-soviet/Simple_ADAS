"""解析描画の更新待ちでライブ映像を遅らせない。"""
from pathlib import Path


def freshest_preview(raw: Path, overlay: Path, now_ns: int, max_age_ns: int) -> Path:
    try:
        drawn = overlay.stat().st_mtime_ns
        # 有効な解析結果でも、現在の映像より遅れた画像は表示しない。
        # 通常の約60ms周期と解析・UIの位相差で生映像へ往復しない。
        # 描画は最大150msで打ち切り、停止・高負荷時の古い画像保持を防ぐ。
        if 0 <= now_ns - drawn < min(max_age_ns, 150_000_000) and raw.stat().st_mtime_ns - drawn <= 150_000_000:
            return overlay
    except OSError:
        pass
    return raw
