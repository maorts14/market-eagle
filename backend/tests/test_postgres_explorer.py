"""Synthetic fixture through PostgreSQL, the repository, and the HTTP route."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.postgres_repository import PostgresAnalyticsRepository
from market_eagle.app import create_app

pytestmark = pytest.mark.synthetic_integration
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"


def test_postgres_explorer_matches_committed_fixture_windows() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("local PostgreSQL integration database is not configured")
    with psycopg.connect(database_url) as conn:
        reader, can_select, can_insert = conn.execute(
            "SELECT current_user, has_table_privilege(current_user, 'security', 'SELECT'), "
            "has_table_privilege(current_user, 'security', 'INSERT')"
        ).fetchone()
        assert reader == "market_eagle_reader"
        assert can_select is True
        assert can_insert is False
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
