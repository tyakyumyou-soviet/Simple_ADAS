"""台形ゾーン自動コントローラのテスト（奥行きのみ自動、他は手動値）。"""

from src.lane.auto_zone import AutoZoneController
from src.types import LaneInfo


def test_auto_zone_uses_manual_values_for_xy() -> None:
    """中心と幅は手動値どおりに反映される。"""
    ctrl = AutoZoneController()
    poly, meta = ctrl.compute(
        480, 640,
        lanes=LaneInfo(None, None, None, None),
        vanishing_point=None,
        manual_offset={
            "center_x_ratio": 0.6,
            "zone_bottom_width_ratio": 0.30,
            "zone_top_width_ratio": 0.08,
            "zone_top_offset_ratio": 0.0,
        },
    )
    # center=0.6, bottom_w=0.30 → 底辺は 0.45-0.75
    assert abs(meta["center_x_ratio"] - 0.6) < 1e-6
    assert abs(meta["zone_bottom_width_ratio"] - 0.30) < 1e-6


def test_auto_zone_top_y_uses_vanishing_point() -> None:
    """消失点があれば、上頂点 y を消失点付近に自動配置。"""
    ctrl = AutoZoneController()
    # 消失点 y=200 → 上頂点 y ≈ 225
    poly, meta = ctrl.compute(480, 640, LaneInfo(None, None, None, None), (320, 200))
    auto_y = meta["auto_top_y"]
    assert 200 < auto_y < 260


def test_auto_zone_fallback_top_y_without_vp() -> None:
    """消失点・レーン無しなら画像の 45% に上頂点 y を置く。"""
    ctrl = AutoZoneController()
    _, meta = ctrl.compute(480, 640, LaneInfo(None, None, None, None), None)
    assert abs(meta["auto_top_y"] - 480 * 0.45) < 1


def test_auto_zone_top_offset_kept_manual() -> None:
    """top_offset_ratio は将来 OBD2 用。手動値そのまま反映。"""
    ctrl = AutoZoneController()
    _, meta = ctrl.compute(480, 640, LaneInfo(None, None, None, None), None,
                            manual_offset={"zone_top_offset_ratio": 0.15})
    assert abs(meta["zone_top_offset_ratio"] - 0.15) < 1e-6
