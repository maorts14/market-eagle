"""Integration checks against an isolated PostgreSQL database with synthetic-v1 loaded."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from .fixture import load_fixture
from .store import ingest_page, missing_pairs, read_csv

pytestmark = pytest.mark.synthetic_integration


@pytest.fixture(scope="module")
def conn():
    url = os.environ.get("INGESTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "set INGESTION_TEST_DATABASE_URL to a disposable PostgreSQL database"
        )
    schema = f"ingestion_test_{uuid4().hex}"
    migration = Path("database/migrations/001_market_data.sql").read_text(
        encoding="utf-8"
    )
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            connection.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
            )
            connection.execute(migration)
            load_fixture(connection, Path("fixtures/synthetic-v1"))
            yield connection
        finally:
            connection.execute("SET search_path TO public")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def test_fixture_is_idempotent_and_exposes_missing_endpoints(conn):
    assert load_fixture(conn, Path("fixtures/synthetic-v1"))["bars_inserted"] == 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM daily_bar_revision")
        assert cur.fetchone()[0] == 2347
        cur.execute("SELECT count(*) FROM daily_bar_current")
        assert cur.fetchone()[0] == 2347
        cur.execute("SELECT snapshot_id FROM catalog_current")
        assert cur.fetchone()[0] == "synthetic-catalog-v1"
    coverage = missing_pairs(
        conn,
        "synthetic-catalog-v1",
        ["stock-epsi"],
        date(2024, 1, 1),
        date(2024, 12, 31),
        "synthetic-v1",
        "fictional",
        "synthetic_raw",
        "SYNTHETIC",
    )
    assert coverage == {"expected": 0, "missing": 0, "repair_sample": []}
    gap = missing_pairs(
        conn,
        "synthetic-catalog-v1",
        ["stock-delt"],
        date(2025, 12, 1),
        date(2025, 12, 31),
        "synthetic-v1",
        "fictional",
        "synthetic_raw",
        "SYNTHETIC",
    )
    assert gap["expected"] == 23
    assert gap["missing"] > 0


def test_correction_and_rejection_are_safe(conn):
    original = next(
        row
        for row in read_csv(Path("fixtures/synthetic-v1/bars.csv"))
        if row["stock_id"] == "stock-alfa" and row["session_date"] == "2025-12-31"
    )
    corrected = {
        **original,
        "close": str(Decimal(original["close"]) + Decimal("1.00")),
        "high": str(Decimal(original["high"]) + Decimal("1.00")),
        "provider_as_of": "2026-01-02T00:00:00Z",
    }
    invalid = {**original, "ticker": "UNKNOWN"}
    options = {
        "collection_run_id": "correction-test",
        "endpoint": "test",
        "requested_symbols": ["ALFA"],
        "requested_start": date(2025, 12, 31),
        "requested_end": date(2025, 12, 31),
        "source": "synthetic-v1",
        "feed": "fictional",
        "price_basis": "synthetic_raw",
        "exchange": "SYNTHETIC",
    }
    first = ingest_page(conn, [corrected, invalid], **options)
    assert first["inserted"] == 1
    assert first["accepted"] == 1
    assert first["rejected"][0]["reason"] == "ticker/date does not resolve to one stock"
    assert ingest_page(conn, [corrected], **options)["inserted"] == 0
    assert ingest_page(conn, [original], **options)["inserted"] == 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close, provider_as_of FROM selected_daily_bar WHERE stock_id = 'stock-alfa' "
            "AND session_date = '2025-12-31' AND source = 'synthetic-v1' "
            "AND feed = 'fictional' AND price_basis = 'synthetic_raw'"
        )
        close, as_of = cur.fetchone()
    assert close == Decimal(corrected["close"])
    assert as_of.isoformat() == "2026-01-02T00:00:00+00:00"


def test_fetched_bar_recheck_and_reversal(conn):
    original = next(
        row
        for row in read_csv(Path("fixtures/synthetic-v1/bars.csv"))
        if row["stock_id"] == "stock-beta" and row["session_date"] == "2025-12-31"
    )
    options = {
        "endpoint": "test",
        "requested_symbols": ["BETA"],
        "requested_start": date(2025, 12, 31),
        "requested_end": date(2025, 12, 31),
        "source": "synthetic-v1",
        "feed": "fictional",
        "price_basis": "synthetic_raw",
        "exchange": "SYNTHETIC",
    }
    unchanged = {
        **original,
        "as_of_kind": "fetched",
        "provider_as_of": "2026-01-03T00:00:00Z",
    }
    assert (
        ingest_page(conn, [unchanged], collection_run_id="fetch-a", **options)[
            "inserted"
        ]
        == 0
    )
    changed = {
        **unchanged,
        "close": str(Decimal(original["close"]) + Decimal("0.10")),
        "high": str(Decimal(original["high"]) + Decimal("0.10")),
    }
    assert (
        ingest_page(conn, [changed], collection_run_id="fetch-b", **options)["inserted"]
        == 1
    )
    assert (
        ingest_page(conn, [changed], collection_run_id="fetch-b", **options)["inserted"]
        == 0
    )
    assert (
        ingest_page(conn, [changed], collection_run_id="fetch-c", **options)["inserted"]
        == 0
    )
    reverted = {**unchanged, "provider_as_of": "2026-01-04T00:00:00Z"}
    assert (
        ingest_page(conn, [reverted], collection_run_id="fetch-d", **options)[
            "inserted"
        ]
        == 1
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close FROM selected_daily_bar WHERE stock_id = 'stock-beta' "
            "AND session_date = '2025-12-31' AND source = 'synthetic-v1' "
            "AND feed = 'fictional' AND price_basis = 'synthetic_raw'"
        )
        assert cur.fetchone()[0] == Decimal(original["close"])
