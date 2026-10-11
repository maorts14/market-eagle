"""Reviewed mixed-exchange collection plan against disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from . import alpaca_collect
from .alpaca_collect import approved_backfill_request, start_backfill
from .alpaca_preparation import (
    approve_preparation,
    collection_request,
    review_preparation,
    stage_preparation,
    validate_collection_group,
)
from .store import ingest_page

pytestmark = pytest.mark.synthetic_integration


@pytest.fixture
def conn():
    url = os.environ.get("INGESTION_TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not url:
        pytest.skip("set INGESTION_TEST_DATABASE_URL to disposable PostgreSQL")
    schema = f"alpaca_prep_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            connection.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
            )
            for migration in sorted(
                Path("database/migrations").glob("[0-9][0-9][0-9]_*.sql")
            ):
                connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO security (stock_id, name) VALUES ('stock-alfa', 'Alpha'), ('stock-beta', 'Beta')"
            )
            connection.execute(
                "INSERT INTO sector (taxonomy, sector_code, sector_name) VALUES ('fmp-sector-unverified-v1', 'Technology', 'Technology')"
            )
            connection.execute(
                "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, captured_at, "
                "published_at, source_checksum, validation_state) VALUES "
                "('fmp-reviewed', 'fmp-sp500', 'fmp-sector-unverified-v1', '2024-01-03', "
                "'2024-01-03T20:00:00Z', '2024-01-03T20:00:00Z', 'reviewed', 'published')"
            )
            connection.execute(
                "INSERT INTO universe_member (snapshot_id, stock_id, source_ticker, taxonomy, sector_code) "
                "VALUES ('fmp-reviewed', 'stock-alfa', 'ALFA', 'fmp-sector-unverified-v1', 'Technology'), "
                "('fmp-reviewed', 'stock-beta', 'BETA', 'fmp-sector-unverified-v1', 'Technology')"
            )
            connection.execute(
                "INSERT INTO catalog_current (singleton, snapshot_id) VALUES (true, 'fmp-reviewed')"
            )
            yield connection
        finally:
            connection.execute("SET search_path TO public")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def _assets() -> list[dict]:
    return [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "symbol": "ALFA",
            "exchange": "NYSE",
            "name": "Alpha",
            "status": "active",
            "class": "us_equity",
        },
        {
            "id": "22222222-2222-4222-8222-222222222222",
            "symbol": "BETA",
            "exchange": "NASDAQ",
            "name": "Beta",
            "status": "active",
            "class": "us_equity",
        },
    ]


def _sessions() -> list[dict]:
    return [
        {
            "date": day,
            "open_at": f"{day}T14:30:00+00:00",
            "close_at": f"{day}T21:00:00+00:00",
            "type": "regular",
        }
        for day in ("2023-12-29", "2024-01-02", "2024-01-03")
    ]


def _approval() -> list[dict]:
    return [
        {
            "stock_id": "stock-alfa",
            "asset_id": _assets()[0]["id"],
            "symbol": "ALFA",
            "exchange": "NYSE",
            "verified_from": "2023-12-29",
            "verified_to": None,
            "evidence": "Reviewed Alpaca asset ID and dated share-line symbol history",
        },
        {
            "stock_id": "stock-beta",
            "asset_id": _assets()[1]["id"],
            "symbol": "BETA",
            "exchange": "NASDAQ",
            "verified_from": "2023-12-29",
            "verified_to": None,
            "evidence": "Reviewed Alpaca asset ID and dated share-line symbol history",
        },
    ]


def test_reviewed_plan_registers_mixed_exchange_aliases_and_calendar(conn):
    staged = stage_preparation(
        conn,
        snapshot_id="fmp-reviewed",
        requested_start=date(2024, 1, 1),
        requested_end=date(2024, 1, 3),
        assets=_assets(),
        sessions=_sessions(),
        fetched_at=datetime(2024, 1, 3, 22, tzinfo=timezone.utc),
    )
    report = review_preparation(conn, staged["preparation_id"])
    assert report["comparison_session"] == "2023-12-29"
    assert report["missing_exact_symbol_count"] == 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM security_symbol WHERE source = 'alpaca'")
        assert cur.fetchone()[0] == 0
    with pytest.raises(ValueError, match="every distinct"):
        approve_preparation(
            conn,
            preparation_id=staged["preparation_id"],
            expected_checksum=staged["checksum"],
            reviewer="reviewer",
            review_note="checked",
            aliases=_approval()[:1],
        )
    too_short = _approval()
    too_short[0]["verified_from"] = "2024-01-01"
    with pytest.raises(ValueError, match="span"):
        approve_preparation(
            conn,
            preparation_id=staged["preparation_id"],
            expected_checksum=staged["checksum"],
            reviewer="reviewer",
            review_note="checked",
            aliases=too_short,
        )
    request = approve_preparation(
        conn,
        preparation_id=staged["preparation_id"],
        expected_checksum=staged["checksum"],
        reviewer="reviewer",
        review_note="verified two share lines and five-year alias evidence",
        aliases=_approval(),
    )
    assert request == collection_request(conn, staged["preparation_id"])
    assert request == approved_backfill_request(conn, staged["preparation_id"])
    assert request["start"] == "2023-12-29"
    assert {row[2] for row in validate_collection_group(conn, request)} == {
        "NYSE",
        "NASDAQ",
    }
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trading_session WHERE exchange = 'US_EQUITY'")
        assert cur.fetchone()[0] == 3
        cur.execute(
            "SELECT rights_version FROM data_source WHERE source = 'alpaca' AND feed = 'sip'"
        )
        assert "rights-unconfirmed" in cur.fetchone()[0]

    bars = [
        {
            "ticker": ticker,
            "session_date": "2024-01-02",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10.5",
            "volume": "100",
            "vwap": "10.2",
            "traded_notional": "",
            "source": "alpaca",
            "feed": "sip",
            "price_basis": "raw",
            "provider_as_of": "2024-01-03T00:00:00Z",
            "as_of_kind": "fetched",
            "status": "historical",
        }
        for ticker in ("ALFA", "BETA")
    ]
    result = ingest_page(
        conn,
        bars,
        collection_run_id="mixed-exchange-test",
        endpoint="test",
        requested_symbols=["ALFA", "BETA"],
        requested_start=date(2024, 1, 2),
        requested_end=date(2024, 1, 2),
        source="alpaca",
        feed="sip",
        price_basis="raw",
        exchange="US_EQUITY",
    )
    assert result["accepted"] == 2


def test_stale_or_unapproved_preparation_cannot_collect(conn):
    staged = stage_preparation(
        conn,
        snapshot_id="fmp-reviewed",
        requested_start=date(2024, 1, 1),
        requested_end=date(2024, 1, 3),
        assets=_assets(),
        sessions=_sessions(),
        fetched_at=datetime(2024, 1, 3, 22, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="not approved"):
        collection_request(conn, staged["preparation_id"])
    with pytest.raises(ValueError, match="not approved"):
        approved_backfill_request(conn, staged["preparation_id"])
    conn.execute(
        "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, captured_at, "
        "published_at, source_checksum, validation_state) VALUES "
        "('fmp-next', 'fmp-sp500', 'fmp-sector-unverified-v1', '2024-01-04', "
        "'2024-01-04T20:00:00Z', '2024-01-04T20:00:00Z', 'next', 'published')"
    )
    conn.execute(
        "UPDATE catalog_current SET snapshot_id = 'fmp-next' WHERE singleton = true"
    )
    with pytest.raises(ValueError, match="changed after"):
        approve_preparation(
            conn,
            preparation_id=staged["preparation_id"],
            expected_checksum=staged["checksum"],
            reviewer="reviewer",
            review_note="stale catalog",
            aliases=_approval(),
        )


def test_manual_backfill_rejects_preparation_after_catalog_replacement(conn):
    staged = stage_preparation(
        conn,
        snapshot_id="fmp-reviewed",
        requested_start=date(2024, 1, 1),
        requested_end=date(2024, 1, 3),
        assets=_assets(),
        sessions=_sessions(),
        fetched_at=datetime(2024, 1, 3, 22, tzinfo=timezone.utc),
    )
    approve_preparation(
        conn,
        preparation_id=staged["preparation_id"],
        expected_checksum=staged["checksum"],
        reviewer="reviewer",
        review_note="checked share lines",
        aliases=_approval(),
    )
    conn.execute(
        "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, captured_at, "
        "published_at, source_checksum, validation_state) VALUES "
        "('fmp-next', 'fmp-sp500', 'fmp-sector-unverified-v1', '2024-01-04', "
        "'2024-01-04T20:00:00Z', '2024-01-04T20:00:00Z', 'next', 'published')"
    )
    conn.execute(
        "UPDATE catalog_current SET snapshot_id = 'fmp-next' WHERE singleton = true"
    )
    with pytest.raises(ValueError, match="current reviewed FMP catalog"):
        approved_backfill_request(conn, staged["preparation_id"])


def test_manual_backfill_uses_pinned_request_and_reuses_workflow_id(monkeypatch):
    request = {
        "preparation_id": "approved-preparation",
        "snapshot_id": "fmp-reviewed",
        "stock_ids": ["stock-alfa", "stock-beta"],
        "collection_run_id": "alpaca-backfill:approved-preparation",
    }
    calls = []
    handle = SimpleNamespace(
        describe=lambda: describe(),
    )

    async def describe():
        return SimpleNamespace(run_id="run-one", status=WorkflowExecutionStatus.RUNNING)

    class FakeClient:
        async def start_workflow(self, workflow, received, **kwargs):
            calls.append((workflow, received, kwargs))
            if len(calls) == 2:
                raise WorkflowAlreadyStartedError(
                    kwargs["id"], "HistoricalBackfillWorkflow"
                )
            return handle

        def get_workflow_handle(self, workflow_id):
            assert workflow_id == request["collection_run_id"]
            return handle

    async def connect(address, *, namespace):
        assert address == "localhost:7233"
        assert namespace == "default"
        return FakeClient()

    monkeypatch.setattr(alpaca_collect, "Client", SimpleNamespace(connect=connect))
    first = asyncio.run(start_backfill(request))
    retry = asyncio.run(start_backfill(request))
    assert (
        first
        == retry
        == {
            "workflow_id": request["collection_run_id"],
            "run_id": "run-one",
            "status": "running",
            "preparation_id": request["preparation_id"],
            "snapshot_id": request["snapshot_id"],
            "stock_count": 2,
        }
    )
    assert len(calls) == 2
    for workflow, received, options in calls:
        assert workflow is alpaca_collect.HistoricalBackfillWorkflow.run
        assert received is request
        assert options == {
            "id": request["collection_run_id"],
            "task_queue": "market-backfill",
            "id_reuse_policy": WorkflowIDReusePolicy.REJECT_DUPLICATE,
            "id_conflict_policy": WorkflowIDConflictPolicy.USE_EXISTING,
        }
