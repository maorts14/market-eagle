"""Synthetic fixture through PostgreSQL, the repository, and the HTTP route."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from market_eagle.agent.activities import AgentActivities
from market_eagle.agent.models import Decision, Limits
from market_eagle.agent.store import AgentStore
from market_eagle.agent.workflow import AgentTurnWorkflow
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.models import AnalyticalRequest
from market_eagle.analytics.postgres_repository import PostgresAnalyticsRepository
from market_eagle.analytics.service import AnalyticsService
from market_eagle.app import create_app
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

pytestmark = pytest.mark.synthetic_integration
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"


def test_postgres_explorer_matches_committed_fixture_windows() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("local PostgreSQL integration database is not configured")
    with psycopg.connect(database_url) as conn:
        reader, can_select, can_insert, can_read_revision = conn.execute(
            "SELECT current_user, has_table_privilege(current_user, 'security', 'SELECT'), "
            "has_table_privilege(current_user, 'security', 'INSERT'), "
            "has_table_privilege(current_user, 'daily_bar_revision', 'SELECT')"
        ).fetchone()
        assert reader == "market_eagle_reader"
        assert can_select is True
        assert can_insert is False
        assert can_read_revision is False
    postgres = PostgresAnalyticsRepository(
        database_url,
        source="synthetic-v1",
        feed="fictional",
        price_basis="synthetic_raw",
        exchange="SYNTHETIC",
    )
    fixture = SyntheticFixtureRepository(FIXTURE)
    database_api = TestClient(create_app(postgres))
    fixture_api = TestClient(create_app(fixture))
    for start, end in (("2025-12-01", "2025-12-31"), ("2024-01-02", "2025-12-31")):
        params = {"start": start, "end": end}
        stored = database_api.get("/api/v1/explorer", params=params)
        expected = fixture_api.get("/api/v1/explorer", params=params)
        assert stored.status_code == expected.status_code == 200
        stored_result = stored.json()
        expected_result = expected.json()
        stored_result.pop("calculated_at")
        expected_result.pop("calculated_at")
        assert stored_result == expected_result

    request = AnalyticalRequest.model_validate(
        {
            "request_version": 1,
            "universe": "latest_published_catalog",
            "window": {"start": "2025-12-01", "end": "2025-12-31"},
            "grain": "stock",
            "measures": [
                "period_return",
                "qualifying_days",
                "qualifying_fraction",
                "observed_usable_days",
                "requested_sessions",
            ],
            "daily_conditions": [
                {
                    "field": "daily_dollar_volume",
                    "operator": ">",
                    "value": "100000",
                    "unit": "USD",
                }
            ],
            "reduction": {
                "measure": "qualifying_fraction",
                "operator": ">=",
                "value": "0.80",
            },
            "sort": {"measure": "period_return", "direction": "desc"},
            "limit": 5,
        }
    )
    stored_analysis = AnalyticsService(postgres).execute(request)
    fixture_analysis = AnalyticsService(fixture).execute(request)
    stored_analysis.pop("calculated_at")
    fixture_analysis.pop("calculated_at")
    assert stored_analysis == fixture_analysis
    assert stored_analysis["eligible_count"] == 4
    assert stored_analysis["rows"][0]["ticker"] == "EPSI"


def test_postgres_agent_turn_through_http_and_temporal(tmp_path: Path) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("local PostgreSQL integration database is not configured")
    repository = PostgresAnalyticsRepository(
        database_url,
        source="synthetic-v1",
        feed="fictional",
        price_basis="synthetic_raw",
        exchange="SYNTHETIC",
    )
    store = AgentStore(tmp_path / "agent.sqlite")
    limits = Limits()

    class FixedModel:
        def interpret(self, context: dict, *, feedback: str | None = None) -> Decision:
            return Decision.model_validate(
                {
                    "kind": "query",
                    "assumptions": [
                        "last month means the previous completed calendar month"
                    ],
                    "request": {
                        "request_version": 1,
                        "universe": "latest_published_catalog",
                        "window": {"start": "2025-12-01", "end": "2025-12-31"},
                        "grain": "stock",
                        "measures": ["period_return", "qualifying_fraction"],
                        "daily_conditions": [
                            {
                                "field": "daily_dollar_volume",
                                "operator": ">",
                                "value": "100000",
                                "unit": "USD",
                            }
                        ],
                        "reduction": {
                            "measure": "qualifying_fraction",
                            "operator": ">=",
                            "value": "0.80",
                        },
                        "sort": {"measure": "period_return", "direction": "desc"},
                        "limit": 1,
                    },
                }
            )

        def explain(self, question: str, result: dict, assumptions: list[str]) -> str:
            return "Result is scoped to the eligible stocks."

        def summarize(self, turns: list[dict]) -> str:
            return "Summary"

    async def run() -> None:
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            activities = AgentActivities(
                store, AnalyticsService(repository), FixedModel(), limits
            )
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    environment.client,
                    task_queue="market-eagle-agent",
                    workflows=[AgentTurnWorkflow],
                    activities=[
                        activities.load_context,
                        activities.interpret,
                        activities.execute,
                        activities.explain,
                        activities.finish,
                        activities.refresh_summary,
                    ],
                    activity_executor=executor,
                ):
                    app = create_app(
                        repository,
                        agent_store=store,
                        temporal=environment.client,
                        agent_enabled=True,
                    )
                    transport = ASGITransport(app=app)
                    async with AsyncClient(
                        transport=transport, base_url="http://test"
                    ) as client:
                        created = await client.post("/api/v1/agent/conversations")
                        assert created.status_code == 200
                        conversation_id = created.json()["conversation_id"]
                        submitted = await client.post(
                            f"/api/v1/agent/conversations/{conversation_id}/turns",
                            json={
                                "request_id": "integration-one",
                                "question": "Which stock gained most last month with enough dollar volume?",
                            },
                        )
                        assert submitted.status_code == 200
                        turn_id = submitted.json()["turn_id"]
                        for _ in range(100):
                            current = await client.get(f"/api/v1/agent/turns/{turn_id}")
                            assert current.status_code == 200
                            if current.json()["status"] != "running":
                                break
                            await asyncio.sleep(0.05)
                        result = current.json()
                        assert result["status"] == "completed"
                        assert result["trusted_result"]["rows"][0]["ticker"] == "EPSI"
                        assert result["trusted_result"]["coverage_label"] == (
                            "Evaluated 4 of 5 tracked stocks"
                        )
                        assert result["agent_explanation"] == (
                            "Result is scoped to the eligible stocks."
                        )
                        evidence = await client.get(
                            f"/api/v1/agent/evidence/{result['evidence_id']}"
                        )
                        assert evidence.status_code == 200

    asyncio.run(run())
