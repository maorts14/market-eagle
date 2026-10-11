"""Readiness reports dependency failures without exposing connection details."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository

app_module = importlib.import_module("market_eagle.app")
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"


class TemporalService:
    def __init__(self) -> None:
        self.available = True
        self.calls = 0

    async def describe_namespace(self, request):
        self.calls += 1
        assert request.namespace == "market-eagle-private"
        if not self.available:
            raise RuntimeError("secret Temporal diagnostic")


def test_readiness_checks_both_databases_and_temporal(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "market-url")
    monkeypatch.setenv("AGENT_DATABASE_URL", "agent-url")
    calls = []

    def check(url: str, relation: str) -> None:
        calls.append((url, relation))

    monkeypatch.setattr(app_module, "_check_database", check)
    service = TemporalService()
    temporal = SimpleNamespace(
        namespace="market-eagle-private", workflow_service=service
    )
    api = TestClient(
        app_module.create_app(
            SyntheticFixtureRepository(FIXTURE),
            agent_store=object(),
            temporal=temporal,
        )
    )

    response = api.get("/api/v1/ready")
    assert response.status_code == 200
    assert calls == [
        ("market-url", "selected_daily_bar"),
        ("agent-url", "agent_conversation"),
    ]
    assert service.calls == 1

    service.available = False
    response = api.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert api.get("/api/v1/health").status_code == 200


def test_readiness_fails_when_market_database_fails(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "market-url")

    def fail(_url: str, _relation: str) -> None:
        raise RuntimeError("secret PostgreSQL diagnostic")

    monkeypatch.setattr(app_module, "_check_database", fail)
    api = TestClient(
        app_module.create_app(SyntheticFixtureRepository(FIXTURE), agent_enabled=False)
    )
    response = api.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_production_readiness_requires_reviewed_market(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "market-url")
    monkeypatch.setenv("MARKET_EAGLE_RUNTIME", "production")
    monkeypatch.setenv("MARKET_EAGLE_SOURCE", "alpaca")
    monkeypatch.setenv("MARKET_EAGLE_FEED", "sip")
    monkeypatch.setattr(app_module, "_check_database", lambda *_args: None)
    calls = []

    def check_market(url: str, source: str, feed: str) -> None:
        calls.append((url, source, feed))
        raise RuntimeError("No reviewed catalog")

    monkeypatch.setattr(app_module, "_check_production_market", check_market)
    api = TestClient(
        app_module.create_app(SyntheticFixtureRepository(FIXTURE), agent_enabled=False)
    )
    response = api.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert calls == [("market-url", "alpaca", "sip")]
