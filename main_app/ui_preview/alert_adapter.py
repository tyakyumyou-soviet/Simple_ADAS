"""既存 Alert をUI向けに変換する。未知の方向や対象を推測しない。"""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class DisplayAlert:
    kind: str
    category: str
    level: int
    color: str
    direction: str
    message: str
    target_id: int | None


DIRECTIONS = {"左": "左", "左前": "左", "右": "右", "右前": "右", "中央": "中央", "正面": "中央"}
VEHICLES = {"car", "truck", "bus", "motorcycle"}


def adapt_alert(alert, target_classes: Mapping[int, str] | None = None) -> DisplayAlert:
    kind = str(alert.kind)
    target_id = alert.target_id
    target_class = (target_classes or {}).get(target_id, "")
    if kind == "ldw":
        category = "車線"
    elif kind.startswith("person_") or target_class == "person":
        category = "人"
    elif kind.startswith("bicycle_") or target_class == "bicycle":
        category = "自転車"
    elif target_class in VEHICLES:
        category = "車両"
    elif kind == "ai_depth_obstacle":
        category = "障害物"
    else:
        category = "不明"
    level = int(alert.level)
    color = {1: "情報", 2: "黄色", 3: "赤色"}.get(level, "不明")
    return DisplayAlert(kind, category, level, color,
                        DIRECTIONS.get(alert.direction, "不明"), str(alert.message), target_id)


def sides_for_alert(alert: DisplayAlert) -> frozenset[str]:
    """警告の対象側を返す。点灯・点滅の使い分けは別途決める。"""
    if alert.level not in (2, 3):
        return frozenset()
    return {"左": frozenset({"左"}), "右": frozenset({"右"}),
            "中央": frozenset({"左", "右"})}.get(alert.direction, frozenset())
