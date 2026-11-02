from src.utils.geometry import fallback_ego_lane_polygon, point_in_polygon


def test_fallback_lane_contains_bottom_center() -> None:
    polygon = fallback_ego_lane_polygon(1000, 500)
    assert point_in_polygon((500, 450), polygon)
    assert not point_in_polygon((50, 450), polygon)
