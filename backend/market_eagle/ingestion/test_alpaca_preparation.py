"""Reviewed mixed-exchange collection plan against disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from . import alpaca_collect, worker
from .alpaca_collect import approved_backfill_request, start_backfill
from .alpaca_preparation import (
    approve_preparation,
    collection_request,
    review_preparation,
    stage_preparation,
    validate_collection_group,
)
from .ongoing_collection import (
    approve_ongoing_collection,
    ongoing_collection_request,
    validate_ongoing_collection_group,
)
from .ongoing_reference import (
    calendar_status,
    maintain_ongoing_reference,
    record_reference_failure,
    require_reference_check,
)
from .store import ingest_page

pytestmark = pytest.mark.synthetic_integration


def _ongoing_full_catalog(conn):
    """Seed a reviewed full universe without invoking a provider or backfill."""
    preparation_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO data_source (source, feed, rights_version, provider, synthetic, "
            "private_use_approved) VALUES "
            "('alpaca', 'sip', 'private-use-reviewed-v1', 'alpaca', false, true)"
        )
        cur.executemany(
            "INSERT INTO security (stock_id, name) VALUES (%s, %s)",
            [(f"stock-{number:03d}", f"Stock {number}") for number in range(448)],
        )
        cur.executemany(
            "INSERT INTO universe_member (snapshot_id, stock_id, source_ticker, "
            "taxonomy, sector_code) VALUES ('fmp-reviewed', %s, %s, "
            "'fmp-sector-unverified-v1', 'Technology')",
            [(f"stock-{number:03d}", f"S{number:03d}") for number in range(448)],
        )
        cur.execute(
            "INSERT INTO alpaca_collection_preparation (preparation_id, snapshot_id, "
            "source_checksum, fetched_at, requested_start, requested_end, "
            "comparison_session, status, reviewed_by, review_note) VALUES "
            "(%s, 'fmp-reviewed', 'reviewed', '2024-01-03T22:00:00Z', "
            "'2024-01-02', '2024-01-03', '2023-12-29', 'prepared', 'reviewer', 'checked')",
            (preparation_id,),
        )
        members = [("stock-alfa", "ALFA", "NYSE"), ("stock-beta", "BETA", "NASDAQ")]
        members += [
            (f"stock-{number:03d}", f"S{number:03d}", "NYSE") for number in range(448)
        ]
        assets = [
            (stock, symbol, exchange, str(uuid4()))
            for stock, symbol, exchange in members
        ]
        cur.executemany(
            "INSERT INTO alpaca_preparation_asset (preparation_id, asset_id, symbol, "
            "exchange, name, asset_status, asset_class) "
            "VALUES (%s, %s, %s, %s, %s, 'active', 'us_equity')",
            [
                (preparation_id, asset_id, symbol, exchange, stock)
                for stock, symbol, exchange, asset_id in assets
            ],
        )
        cur.executemany(
            "INSERT INTO alpaca_alias_approval (preparation_id, stock_id, asset_id, "
            "symbol, exchange, verified_from, evidence) "
            "VALUES (%s, %s, %s, %s, %s, '2023-12-29', 'reviewed')",
            [
                (preparation_id, stock, asset_id, symbol, exchange)
                for stock, symbol, exchange, asset_id in assets
            ],
        )
        cur.executemany(
            "INSERT INTO security_symbol (stock_id, ticker, exchange, valid_from, source) "
            "VALUES (%s, %s, %s, '2023-12-29', 'alpaca')",
            members,
        )
        cur.executemany(
            "INSERT INTO trading_session (exchange, session_date, session_type, "
            "open_at, close_at, calendar_source) VALUES ('US_EQUITY', %s, 'regular', "
            "%s, %s, 'alpaca-trading-calendar')",
            [
                ("2024-01-04", "2024-01-04T14:30:00Z", "2024-01-04T21:00:00Z"),
                ("2024-01-05", "2024-01-05T14:30:00Z", "2024-01-05T21:00:00Z"),
            ],
        )
    return preparation_id


def _reference_assets(conn, preparation_id):
    rows = conn.execute(
        "SELECT asset_id, symbol, exchange, name FROM alpaca_preparation_asset "
        "WHERE preparation_id = %s",
        (preparation_id,),
    ).fetchall()
    return [
        {
            "id": str(asset_id),
            "symbol": symbol,
            "exchange": exchange,
            "name": name,
            "status": "active",
            "class": "us_equity",
        }
        for asset_id, symbol, exchange, name in rows
    ]


def _reference_sessions():
    return [
        {
            "date": day,
            "open_at": f"{day}T14:30:00+00:00",
            "close_at": f"{day}T21:00:00+00:00",
            "type": "regular",
        }
        for day in ("2024-01-04", "2024-01-05", "2024-01-08")
    ] + [
        {
            "date": "2024-01-09",
            "open_at": "2024-01-09T14:30:00+00:00",
            "close_at": "2024-01-09T18:00:00+00:00",
            "type": "half_day",
        }
    ]


def test_ongoing_approval_admits_later_reviewed_sessions_without_renewal(conn):
    preparation_id = _ongoing_full_catalog(conn)
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="fmp-sp500",
        reviewer="operator",
        review_note="reviewed full mappings and ongoing use",
    )
    for target in (date(2024, 1, 4), date(2024, 1, 5)):
        request = ongoing_collection_request(
            conn,
            approval_id,
            target,
            f"refresh:{target}:open+60m:fmp-reviewed:alpaca:sip:raw",
        )
        assert len(request["stock_ids"]) == 450
        assert request["start"] == request["end"] == target.isoformat()
        request["stock_ids"] = request["stock_ids"][:5]
        assert len(validate_ongoing_collection_group(conn, request)) == 5
    with pytest.raises(ValueError, match="window"):
        validate_collection_group(
            conn,
            {**request, "preparation_id": preparation_id, "symbol_asof": "2024-01-03"},
        )


def test_ongoing_admission_holds_on_catalog_mapping_or_calendar_drift(conn):
    preparation_id = _ongoing_full_catalog(conn)
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="fmp-sp500",
        reviewer="operator",
        review_note="reviewed",
    )
    target = date(2024, 1, 4)
    request = ongoing_collection_request(conn, approval_id, target, "stable-run")
    request["stock_ids"] = request["stock_ids"][:5]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE trading_session SET calendar_source = 'unreviewed' "
            "WHERE exchange = 'US_EQUITY' AND session_date = %s",
            (target,),
        )
    with pytest.raises(ValueError, match="session"):
        validate_ongoing_collection_group(conn, request)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE trading_session SET calendar_source = 'alpaca-trading-calendar' "
            "WHERE exchange = 'US_EQUITY' AND session_date = %s",
            (target,),
        )
        cur.execute(
            "UPDATE security_symbol SET valid_to = '2024-01-03' "
            "WHERE stock_id = 'stock-447' AND source = 'alpaca'"
        )
    with pytest.raises(ValueError, match="mappings"):
        validate_ongoing_collection_group(conn, request)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE security_symbol SET valid_to = NULL "
            "WHERE stock_id = 'stock-447' AND source = 'alpaca'"
        )
        cur.execute(
            "INSERT INTO security_symbol (stock_id, ticker, exchange, valid_from, source) "
            "VALUES ('stock-447', 'OTHER', 'NYSE', '2024-01-01', 'alpaca')"
        )
    with pytest.raises(ValueError, match="mappings"):
        validate_ongoing_collection_group(conn, request)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM security_symbol WHERE stock_id = 'stock-447' AND ticker = 'OTHER'"
        )
        cur.execute(
            "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, "
            "captured_at, published_at, source_checksum, validation_state) VALUES "
            "('new-catalog', 'fmp-sp500', 'fmp-sector-unverified-v1', '2024-01-04', "
            "'2024-01-04T22:00:00Z', '2024-01-04T22:00:00Z', 'new', 'published')"
        )
        cur.execute(
            "UPDATE catalog_current SET snapshot_id = 'new-catalog' WHERE singleton"
        )
    with pytest.raises(ValueError, match="catalog"):
        validate_ongoing_collection_group(conn, request)


def test_ongoing_admission_rejects_unpinned_tuple_and_held_approval(conn):
    preparation_id = _ongoing_full_catalog(conn)
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="fmp-sp500",
        reviewer="operator",
        review_note="reviewed",
    )
    request = ongoing_collection_request(
        conn, approval_id, date(2024, 1, 4), "stable-run"
    )
    request["stock_ids"] = request["stock_ids"][:5]
    with pytest.raises(ValueError, match="source or catalog"):
        validate_ongoing_collection_group(conn, {**request, "feed": "iex"})
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE data_source SET private_use_approved = false "
            "WHERE source = 'alpaca' AND feed = 'sip'"
        )
    with pytest.raises(ValueError, match="held"):
        validate_ongoing_collection_group(conn, request)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE data_source SET private_use_approved = true "
            "WHERE source = 'alpaca' AND feed = 'sip'"
        )
        cur.execute(
            "UPDATE data_source SET rights_version = 'changed-rights' "
            "WHERE source = 'alpaca' AND feed = 'sip'"
        )
    with pytest.raises(ValueError, match="held"):
        validate_ongoing_collection_group(conn, request)
    assert (
        approve_ongoing_collection(
            conn,
            preparation_id=preparation_id,
            catalog_source="fmp-sp500",
            reviewer="operator",
            review_note="reviewed changed account rights",
        )
        == approval_id
    )
    assert len(validate_ongoing_collection_group(conn, request)) == 5
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ongoing_collection_approval SET status = 'held' WHERE approval_id = %s",
            (approval_id,),
        )
    with pytest.raises(ValueError, match="held"):
        validate_ongoing_collection_group(conn, request)


def test_ongoing_approval_rejects_incomplete_full_catalog(conn):
    preparation_id = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alpaca_collection_preparation (preparation_id, snapshot_id, "
            "source_checksum, fetched_at, requested_start, requested_end, "
            "comparison_session, status) VALUES (%s, 'fmp-reviewed', 'reviewed', "
            "'2024-01-03T22:00:00Z', '2024-01-02', '2024-01-03', '2023-12-29', 'prepared')",
            (preparation_id,),
        )
    with pytest.raises(ValueError, match="full-catalog"):
        approve_ongoing_collection(
            conn,
            preparation_id=preparation_id,
            catalog_source="fmp-sp500",
            reviewer="operator",
            review_note="reviewed",
        )


def test_ongoing_approval_pins_explicit_provisional_source_and_rejects_sample(conn):
    preparation_id = _ongoing_full_catalog(conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE universe_snapshot SET source = 'public-sp500-provisional-v1' "
            "WHERE snapshot_id = 'fmp-reviewed'"
        )
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="public-sp500-provisional-v1",
        reviewer="operator",
        review_note="dated public list and share lines checked",
    )
    assert ongoing_collection_request(conn, approval_id, date(2024, 1, 4), "stable-run")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE universe_snapshot SET source = 'alpaca-sample-v1' "
            "WHERE snapshot_id = 'fmp-reviewed'"
        )
    with pytest.raises(ValueError, match="held"):
        ongoing_collection_request(conn, approval_id, date(2024, 1, 4), "stable-run")


def test_reference_maintenance_adds_sessions_and_distinguishes_closed_from_unknown(
    conn,
):
    preparation_id = _ongoing_full_catalog(conn)
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="fmp-sp500",
        reviewer="operator",
        review_note="reviewed",
    )
    checked_at = datetime(2024, 1, 4, 12, tzinfo=timezone.utc)
    assets = _reference_assets(conn, preparation_id)
    sessions = _reference_sessions()
    assert calendar_status(conn, approval_id, date(2024, 1, 6), checked_at) == {
        "status": "unknown"
    }
    result = maintain_ongoing_reference(
        conn,
        approval_id=approval_id,
        coverage_start=date(2024, 1, 4),
        coverage_end=date(2024, 1, 9),
        checked_at=checked_at,
        assets=assets,
        sessions=sessions,
    )
    assert result["matched_assets"] == 450
    assert result["sessions_added"] == 2
    assert calendar_status(conn, approval_id, date(2024, 1, 6), checked_at) == {
        "status": "closed"
    }
    assert calendar_status(conn, approval_id, date(2024, 1, 10), checked_at) == {
        "status": "unknown"
    }
    assert calendar_status(conn, approval_id, date(2024, 1, 9), checked_at) == {
        "status": "session",
        "session": {
            "date": "2024-01-09",
            "open_at": "2024-01-09T14:30:00+00:00",
            "close_at": "2024-01-09T18:00:00+00:00",
            "type": "half_day",
        },
    }
    require_reference_check(conn, approval_id, date(2024, 1, 4), checked_at)
    assert (
        maintain_ongoing_reference(
            conn,
            approval_id=approval_id,
            coverage_start=date(2024, 1, 4),
            coverage_end=date(2024, 1, 9),
            checked_at=checked_at,
            assets=assets,
            sessions=sessions,
        )["sessions_added"]
        == 0
    )


def test_reference_drift_or_failed_probe_holds_price_admission(conn):
    preparation_id = _ongoing_full_catalog(conn)
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="fmp-sp500",
        reviewer="operator",
        review_note="reviewed",
    )
    checked_at = datetime(2024, 1, 4, 12, tzinfo=timezone.utc)
    assets = _reference_assets(conn, preparation_id)
    sessions = _reference_sessions()
    changed = [*assets]
    changed[0] = {**changed[0], "symbol": "CHANGED"}
    with pytest.raises(ValueError, match="identity"):
        maintain_ongoing_reference(
            conn,
            approval_id=approval_id,
            coverage_start=date(2024, 1, 4),
            coverage_end=date(2024, 1, 9),
            checked_at=checked_at,
            assets=changed,
            sessions=sessions,
        )
    assert (
        conn.execute("SELECT count(*) FROM ongoing_reference_check").fetchone()[0] == 0
    )
    with pytest.raises(ValueError, match="calendar"):
        maintain_ongoing_reference(
            conn,
            approval_id=approval_id,
            coverage_start=date(2024, 1, 4),
            coverage_end=date(2024, 1, 9),
            checked_at=checked_at,
            assets=assets,
            sessions=[row for row in sessions if row["date"] != "2024-01-05"],
        )
    maintain_ongoing_reference(
        conn,
        approval_id=approval_id,
        coverage_start=date(2024, 1, 4),
        coverage_end=date(2024, 1, 9),
        checked_at=checked_at,
        assets=assets,
        sessions=sessions,
    )
    record_reference_failure(conn, approval_id, checked_at.replace(minute=1))
    with pytest.raises(ValueError, match="reference check"):
        require_reference_check(conn, approval_id, date(2024, 1, 4), checked_at)
    assert calendar_status(conn, approval_id, date(2024, 1, 6), checked_at) == {
        "status": "unknown"
    }
    with pytest.raises(ValueError, match="reference check"):
        require_reference_check(
            conn, approval_id, date(2024, 1, 4), checked_at + timedelta(days=1)
        )


def test_reference_activity_records_failed_check_without_live_provider(
    conn, monkeypatch
):
    preparation_id = _ongoing_full_catalog(conn)
    approval_id = approve_ongoing_collection(
        conn,
        preparation_id=preparation_id,
        catalog_source="fmp-sp500",
        reviewer="operator",
        review_note="reviewed",
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz):
            return datetime(2024, 1, 4, 12, tzinfo=tz)

    assets = _reference_assets(conn, preparation_id)
    assets[0]["exchange"] = "CHANGED"
    monkeypatch.setattr(worker, "datetime", FixedDateTime)
    schema = conn.execute("SELECT current_schema()").fetchone()[0]
    connect = psycopg.connect

    def connect_in_test_schema(_url):
        separate = connect(os.environ["INGESTION_TEST_DATABASE_URL"])
        separate.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
        )
        separate.commit()
        return separate

    monkeypatch.setattr(worker.psycopg, "connect", connect_in_test_schema)
    monkeypatch.setattr(worker, "_pace_provider", lambda: None)
    monkeypatch.setattr(worker, "fetch_assets", lambda *_args: assets)
    monkeypatch.setattr(worker, "fetch_calendar", lambda *_args: _reference_sessions())
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")
    with pytest.raises(ApplicationError, match="identity"):
        worker.refresh_ongoing_reference({"approval_id": approval_id})
    assert (
        conn.execute(
            "SELECT status FROM ongoing_reference_check WHERE approval_id = %s",
            (approval_id,),
        ).fetchone()[0]
        == "failed"
    )


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
    with pytest.raises(ValueError, match="current reviewed full catalog"):
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
