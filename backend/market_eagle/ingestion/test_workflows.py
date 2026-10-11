"""Deterministic workflow dispatch tests; no Temporal server or provider calls."""

from __future__ import annotations

import asyncio

import pytest

from . import workflows


@pytest.mark.parametrize("configured_limit, expected_limit", [(None, 2), (1, 1)])
def test_session_refresh_bounds_group_dispatch_and_preserves_counts(
    monkeypatch, configured_limit, expected_limit
):
    stock_ids = [f"stock-{index}" for index in range(12)]
    request = {"stock_ids": stock_ids}
    if configured_limit is not None:
        request["max_in_flight"] = configured_limit
    ready = asyncio.Event()
    release = asyncio.Event()
    started = []
    active = peak = 0
    counts = {
        "stock-0": (5, 0, "2026-10-08T15:00:00+00:00"),
        "stock-5": (4, 1, "2026-10-08T15:01:00+00:00"),
        "stock-10": (2, 0, "2026-10-08T15:02:00+00:00"),
    }

    async def collect_group(name, scoped, **kwargs):
        nonlocal active, peak
        assert name == "collect_group"
        assert kwargs["task_queue"] == "market-session"
        assert scoped["mode"] == "provisional"
        assert 1 <= len(scoped["stock_ids"]) <= 5
        active += 1
        peak = max(peak, active)
        started.append(scoped["stock_ids"][0])
        if len(started) == expected_limit:
            ready.set()
        await release.wait()
        active -= 1
        returned, rejected, observed_at = counts[scoped["stock_ids"][0]]
        return {
            "returned": returned,
            "rejected": rejected,
            "observed_at": observed_at,
        }

    monkeypatch.setattr(workflows.workflow, "execute_activity", collect_group)

    async def run():
        task = asyncio.create_task(workflows.SessionRefreshWorkflow().run(request))
        await ready.wait()
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(started) == expected_limit
        release.set()
        return await task

    result = asyncio.run(run())
    assert peak == expected_limit
    assert sorted(started) == sorted(counts)
    assert result == {
        "status": "incomplete",
        "returned": 11,
        "expected": 12,
        "rejected": 1,
        "observed_at": "2026-10-08T15:02:00+00:00",
    }


def test_session_refresh_rejects_zero_in_flight():
    with pytest.raises(ValueError, match="max_in_flight must be positive"):
        asyncio.run(
            workflows.SessionRefreshWorkflow().run(
                {"stock_ids": ["stock-0"], "max_in_flight": 0}
            )
        )
