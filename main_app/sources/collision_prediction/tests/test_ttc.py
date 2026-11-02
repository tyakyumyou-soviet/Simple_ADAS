from src.prediction.ttc import TTCEstimator


def test_ttc_for_closing_object() -> None:
    estimator = TTCEstimator()
    assert estimator.update(1, 0.0, 10.0) is None
    assert estimator.update(1, 1.0, 8.0) is None
    ttc = estimator.update(1, 2.0, 6.0)
    assert ttc is not None
    assert 2.9 < ttc < 3.1
