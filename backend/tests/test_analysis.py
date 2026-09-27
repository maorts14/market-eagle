from app.activities import _correlation


def test_correlation_requires_matching_sample_sizes() -> None:
    assert _correlation([0.01] * 15, [0.01] * 14) is None


def test_correlation_detects_perfect_positive_relationship() -> None:
    values = [index / 100 for index in range(20)]
    assert _correlation(values, values) == 1.0
