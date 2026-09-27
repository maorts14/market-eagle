from types import SimpleNamespace

from app.main import _latency_metrics


def test_latency_metrics_use_nearest_rank_percentiles() -> None:
    result = _latency_metrics([SimpleNamespace(latency_ms=value) for value in [90, 10, 30, 50, 70]])
    assert result == {"total_ms": 250, "p50_ms": 50, "p95_ms": 90}
