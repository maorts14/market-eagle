"""Production refuses fictional prices and the isolated validation catalog."""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from datetime import date

import pytest
from market_eagle.analytics.postgres_repository import PostgresAnalyticsRepository
from market_eagle.analytics.service import AnalyticsError
from market_eagle.ingestion.alpaca_sample_cli import main as sample_main
from market_eagle.ingestion.fixture import load_fixture
from market_eagle.ingestion.worker import publish_catalog_snapshot
from temporalio.exceptions import ApplicationError


def repository(**overrides) -> PostgresAnalyticsRepository:
    options = {
        "source": "alpaca",
        "feed": "sip",
        "price_basis": "raw",
        "exchange": "US_EQUITY",
        "production": True,
    }
    options.update(overrides)
    return PostgresAnalyticsRepository("postgresql://unused", **options)


@pytest.mark.parametrize(
    "override",
    [
        {"source": "synthetic-v1"},
        {"feed": "fictional"},
        {"exchange": "SYNTHETIC"},
        {"private_sample_snapshot_id": "alpaca-sample-v1-reviewed"},
    ],
)
def test_production_rejects_test_selection_at_startup(override) -> None:
    with pytest.raises(ValueError, match="production cannot select test market data"):
        repository(**override)


def test_production_api_requires_database(monkeypatch) -> None:
    app_module = importlib.import_module("market_eagle.app")
    monkeypatch.setenv("MARKET_EAGLE_RUNTIME", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="requires a market database"):
        app_module.selected_repository()


@pytest.mark.parametrize(
    "catalog_source, source_synthetic, member_count, expected_code",
    [
        ("synthetic-v1", False, 0, "test_catalog_unavailable"),
        ("alpaca-sample-v1", False, 0, "test_catalog_unavailable"),
        ("unknown-source", False, 0, "test_catalog_unavailable"),
        ("fmp-sp500", True, 0, "synthetic_data_unavailable"),
        ("fmp-sp500", None, 0, "synthetic_data_unavailable"),
        ("fmp-sp500", False, 5, "incomplete_catalog"),
        ("public-sp500-provisional-v1", True, 0, "synthetic_data_unavailable"),
        ("public-sp500-provisional-v1", False, 5, "incomplete_catalog"),
    ],
)
def test_production_rejects_test_rows_in_database(
    monkeypatch, catalog_source, source_synthetic, member_count, expected_code
) -> None:
    module = importlib.import_module("market_eagle.analytics.postgres_repository")

    class Cursor:
        def __init__(self, row=None, rows=None):
            self.row = row
            self.rows = rows

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def transaction(self):
            return nullcontext()

        def execute(self, query, _values=None):
            if "FROM catalog_current" in query:
                return Cursor({"source": catalog_source, "snapshot_id": "reviewed"})
            if "FROM data_source" in query:
                return Cursor(
                    {"synthetic": source_synthetic}
                    if source_synthetic is not None
                    else None
                )
            if "FROM universe_member m" in query:
                return Cursor(rows=[{}] * member_count)
            return Cursor()

    monkeypatch.setattr(
        module.psycopg, "connect", lambda *_args, **_kwargs: Connection()
    )
    with pytest.raises(AnalyticsError) as error:
        repository().load(date(2025, 1, 1), date(2025, 1, 31))
    assert error.value.code == expected_code


def test_production_ingestion_refuses_test_data(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_EAGLE_RUNTIME", "production")
    with pytest.raises(RuntimeError, match="synthetic fixture"):
        load_fixture(None, None)
    with pytest.raises(RuntimeError, match="five-stock test sample"):
        sample_main()
    with pytest.raises(ApplicationError, match="synthetic catalog"):
        publish_catalog_snapshot({"source": "synthetic-v1"})
