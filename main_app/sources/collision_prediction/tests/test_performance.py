from src.utils.performance import summarize_performance


def test_summarize_performance_reports_process_and_stage_percentiles() -> None:
    report = summarize_performance([
        {"process_ms": 10.0, "stage_ms": {"detection": 4.0, "render": 1.0}},
        {"process_ms": 20.0, "stage_ms": {"detection": 12.0, "render": 2.0}},
    ])

    assert report["frames"] == 2
    assert report["process_ms"]["mean"] == 15.0
    assert report["stage_ms"]["detection"]["p50"] == 8.0
    assert report["stage_ms"]["render"]["p95"] > 1.0


def test_summarize_performance_reports_lane_state_and_frame_age() -> None:
    report = summarize_performance([
        {"process_ms": 10.0, "frame_age_ms": 12.0, "lane_detected": True, "lane_state": "track"},
        {"process_ms": 12.0, "frame_age_ms": 18.0, "lane_detected": False, "lane_state": "lost"},
    ])
    assert report["frame_age_ms"]["p95"] >= 12.0
    assert report["lane_detected_ratio"] == 0.5
    assert report["lane_state_counts"] == {"lost": 1, "track": 1}
