"""Private sample publication and collection plan against disposable PostgreSQL."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from .alpaca_preparation import validate_collection_group
from .alpaca_sample import approve_sample, review_sample, sample_stock_id, stage_sample
from .store import ingest_page

pytestmark = pytest.mark.synthetic_integration
START = date(2024, 10, 9)
END = date(2026, 10, 8)
SYMBOLS = ("AAPL", "AMZN", "JPM", "MSFT", "NVDA")


@pytest.fixture
def conn():
    url = os.environ.get("INGESTION_TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not url:
        pytest.skip("set INGESTION_TEST_DATABASE_URL to disposable PostgreSQL")
    schema = f"alpaca_sample_test_{uuid4().hex}"
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
            yield connection
        finally:
            connection.execute("SET search_path TO public")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def _assets() -> list[dict]:
    return [
        {
            "id": f"{index:08d}-1111-4111-8111-111111111111",
            "symbol": symbol,
            "exchange": "NYSE" if symbol == "JPM" else "NASDAQ",
            "name": f"{symbol} sample company",
            "status": "active",
            "class": "us_equity",
        }
        for index, symbol in enumerate(SYMBOLS, start=1)
    ]


def _sessions() -> list[dict]:
    first = START - timedelta(days=7)
    days = (END - first).days + 1
    return [
        {
            "date": day.isoformat(),
            "open_at": f"{day.isoformat()}T13:30:00+00:00",
            "close_at": f"{day.isoformat()}T20:00:00+00:00",
            "type": "regular",
        }
        for offset in range(days)
        if (day := first + timedelta(days=offset)).weekday() < 5
    ]


def _stage(conn) -> dict:
    return stage_sample(
        conn,
        symbols=list(SYMBOLS),
        requested_start=START,
        requested_end=END,
        assets=_assets(),
        sessions=_sessions(),
        fetched_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )


def _aliases() -> list[dict]:
    return [
        {
            "stock_id": sample_stock_id(asset["id"]),
            "asset_id": asset["id"],
            "symbol": asset["symbol"],
            "exchange": asset["exchange"],
            "verified_from": "2024-10-08",
            "verified_to": None,
            "evidence": "Synthetic test attestation of the dated share-line alias",
        }
        for asset in _assets()
    ]


def test_reviewed_sample_publishes_isolated_catalog_and_collection(conn):
    stage = _stage(conn)
    report = review_sample(conn, stage["stage_id"])
    assert report["status"] == "held"
    assert report["session_count"] >= 450
    assert "not S&P 500" in report["membership_claim"]
    assert {item["stock_id"] for item in report["assets"]} == {
        sample_stock_id(asset["id"]) for asset in _assets()
    }
    assert conn.execute("SELECT count(*) FROM universe_snapshot").fetchone()[0] == 0

    request = approve_sample(
        conn,
        stage_id=stage["stage_id"],
        expected_checksum=stage["checksum"],
        reviewer="test reviewer",
        review_note="checked five private sample share lines",
        aliases=_aliases(),
    )
    assert request["source"] == "alpaca"
    assert request["feed"] == "sip"
    assert request["exchange"] == "US_EQUITY"
    assert request["start"] == "2024-10-08"
    assert len(request["stock_ids"]) == 5
    assert {row[2] for row in validate_collection_group(conn, request)} == {
        "NASDAQ",
        "NYSE",
    }
    assert conn.execute("SELECT count(*) FROM catalog_current").fetchone()[0] == 0
    assert conn.execute(
        "SELECT source, taxonomy FROM universe_snapshot WHERE snapshot_id = %s",
        (request["snapshot_id"],),
    ).fetchone() == ("alpaca-sample-v1", "sample-unclassified-v1")
    assert conn.execute("SELECT count(*) FROM universe_member").fetchone()[0] == 5
    assert (
        "rights-unconfirmed"
        in conn.execute(
            "SELECT rights_version FROM data_source WHERE source = 'alpaca' AND feed = 'sip'"
        ).fetchone()[0]
    )
    assert (
        approve_sample(
            conn,
            stage_id=stage["stage_id"],
            expected_checksum=stage["checksum"],
            reviewer="test reviewer",
            review_note="checked five private sample share lines",
            aliases=_aliases(),
        )
        == request
    )

    bar = {
        "ticker": "JPM",
        "session_date": START.isoformat(),
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.5",
        "volume": "1000",
        "vwap": "100.2",
        "traded_notional": "",
        "source": "alpaca",
        "feed": "sip",
        "price_basis": "raw",
        "provider_as_of": "2026-10-09T00:00:00Z",
        "as_of_kind": "fetched",
        "status": "historical",
    }
    result = ingest_page(
        conn,
        [bar],
        collection_run_id="sample-test",
        endpoint="test",
        requested_symbols=["JPM"],
        requested_start=START,
        requested_end=START,
        source="alpaca",
        feed="sip",
        price_basis="raw",
        exchange="US_EQUITY",
    )
    assert result["accepted"] == 1
    assert conn.execute("SELECT stock_id FROM selected_daily_bar").fetchone()[
        0
    ] == sample_stock_id(_assets()[2]["id"])


def test_sample_review_rejects_unreviewed_or_changed_content(conn):
    stage = _stage(conn)
    with pytest.raises(ValueError, match="checksum"):
        approve_sample(
            conn,
            stage_id=stage["stage_id"],
            expected_checksum="wrong",
            reviewer="reviewer",
            review_note="checked",
            aliases=_aliases(),
        )
    with pytest.raises(ValueError, match="all five"):
        approve_sample(
            conn,
            stage_id=stage["stage_id"],
            expected_checksum=stage["checksum"],
            reviewer="reviewer",
            review_note="checked",
            aliases=_aliases()[:4],
        )
    conn.execute(
        "UPDATE alpaca_sample_asset SET name = 'changed' WHERE stage_id = %s AND symbol = 'JPM'",
        (stage["stage_id"],),
    )
    with pytest.raises(ValueError, match="stored sample contents"):
        approve_sample(
            conn,
            stage_id=stage["stage_id"],
            expected_checksum=stage["checksum"],
            reviewer="reviewer",
            review_note="checked",
            aliases=_aliases(),
        )
    assert conn.execute("SELECT count(*) FROM universe_snapshot").fetchone()[0] == 0
