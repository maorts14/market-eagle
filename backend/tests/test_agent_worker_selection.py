"""The API and agent worker must select the same private sample."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "sample_snapshot, production",
    [(None, False), ("alpaca-sample-v1-reviewed", False), (None, True)],
)
def test_worker_passes_market_selection(
    monkeypatch, sample_snapshot, production
) -> None:
    worker_entry = importlib.import_module("market_eagle.agent.__main__")
    source, feed, basis, exchange = (
        ("alpaca", "sip", "raw", "US_EQUITY")
        if sample_snapshot or production
        else ("synthetic-v1", "fictional", "synthetic_raw", "SYNTHETIC")
    )
    for key, value in {
        "DATABASE_URL": "postgresql://reader@localhost/market_eagle",
        "AGENT_DATABASE_URL": "postgresql://agent@localhost/market_eagle",
        "MARKET_EAGLE_SOURCE": source,
        "MARKET_EAGLE_FEED": feed,
        "MARKET_EAGLE_PRICE_BASIS": basis,
        "MARKET_EAGLE_EXCHANGE": exchange,
        "OPENROUTER_API_KEY": "test-key",
        "OPENROUTER_MODEL": "test-model",
    }.items():
        monkeypatch.setenv(key, value)
    if sample_snapshot:
        monkeypatch.setenv("MARKET_EAGLE_PRIVATE_SAMPLE_SNAPSHOT_ID", sample_snapshot)
    else:
        monkeypatch.delenv("MARKET_EAGLE_PRIVATE_SAMPLE_SNAPSHOT_ID", raising=False)
    monkeypatch.setenv(
        "MARKET_EAGLE_RUNTIME", "production" if production else "development"
    )

    async def connect(*_args, **_kwargs):
        return object()

    selected = {}

    async def run_worker(_temporal, _store, repository, _model, _limits):
        selected["repository"] = repository

    monkeypatch.setattr(worker_entry, "Client", SimpleNamespace(connect=connect))
    monkeypatch.setattr(worker_entry, "PostgresAgentStore", lambda _url: object())
    monkeypatch.setattr(
        worker_entry, "OpenRouterResearchModel", lambda **_kwargs: object()
    )
    monkeypatch.setattr(worker_entry, "run_worker", run_worker)

    asyncio.run(worker_entry.main())

    repository = selected["repository"]
    assert repository.private_sample_snapshot_id == sample_snapshot
    assert repository.production is production
    assert (
        repository.source,
        repository.feed,
        repository.price_basis,
        repository.exchange,
    ) == (source, feed, basis, exchange)
