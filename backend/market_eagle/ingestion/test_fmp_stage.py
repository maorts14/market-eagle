"""Catalog review gate against a disposable PostgreSQL schema."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from .fmp import FmpFetch, checksum_rows, normalize_constituents
from .fmp_catalog import approval_draft
from .fmp_stage import publish_reviewed_stage, review_stage, stage_constituents

pytestmark = pytest.mark.synthetic_integration


@pytest.fixture
def conn():
    url = os.environ.get("INGESTION_TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )
    if not url:
        pytest.skip(
            "set INGESTION_TEST_DATABASE_URL to a disposable PostgreSQL database"
        )
    schema = f"fmp_stage_test_{uuid4().hex}"
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


def _fetch(
    sector: str = "Technology",
    symbols: tuple[str, ...] = ("ALFA", "ALFB"),
    fetched_at: datetime = datetime(2026, 10, 9, 12, tzinfo=timezone.utc),
) -> FmpFetch:
    rows = normalize_constituents(
        [
            {
                "symbol": symbol,
                "name": f"{symbol} Co",
                "sector": sector,
                "subSector": "Test",
                "cik": "0000123456",
                "dateFirstAdded": "2020-01-01",
            }
            for symbol in symbols
        ]
    )
    return FmpFetch(rows, fetched_at, 100, checksum_rows(rows), {})


def test_manual_gate_and_stable_share_line_identity(conn):
    first = stage_constituents(conn, _fetch(), minimum_count=2)
    report = review_stage(conn, first["stage_id"])
    assert report["unresolved_symbols"] == ["ALFA", "ALFB"]
    assert approval_draft(report) == {
        "stage_id": first["stage_id"],
        "checksum": first["checksum"],
        "reviewer": "",
        "review_note": "",
        "decisions": {"ALFA": "", "ALFB": ""},
    }
    assert report["sector_taxonomy"] == "fmp-sector-unverified-v1"
    assert report["provider_publication_time"] is None
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM catalog_current")
        assert cur.fetchone()[0] == 0
    with pytest.raises(ValueError, match="ALFB needs"):
        publish_reviewed_stage(
            conn,
            stage_id=first["stage_id"],
            expected_checksum=first["checksum"],
            reviewer="test reviewer",
            review_note="checked two distinct share lines",
            decisions={"ALFA": "new"},
        )
    snapshot = publish_reviewed_stage(
        conn,
        stage_id=first["stage_id"],
        expected_checksum=first["checksum"],
        reviewer="test reviewer",
        review_note="checked two distinct share lines",
        decisions={"ALFA": "new", "ALFB": "new"},
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stock_id, sector_code FROM universe_member WHERE snapshot_id = %s ORDER BY source_ticker",
            (snapshot,),
        )
        members = cur.fetchall()
        assert members[0][0] != members[1][0]  # Shared CIK is not share-line identity.
        assert {item[1] for item in members} == {"Technology"}
        cur.execute("SELECT snapshot_id FROM catalog_current")
        assert cur.fetchone()[0] == snapshot

    second = stage_constituents(conn, _fetch("Industrials"), minimum_count=2)
    report = review_stage(conn, second["stage_id"])
    assert report["unresolved_symbols"] == []
    assert approval_draft(report)["decisions"] == {}
    assert report["sector_changes"] == ["ALFA", "ALFB"]
    next_snapshot = publish_reviewed_stage(
        conn,
        stage_id=second["stage_id"],
        expected_checksum=second["checksum"],
        reviewer="test reviewer",
        review_note="reviewed both sector changes",
        decisions={},
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stock_id FROM universe_member WHERE snapshot_id = %s ORDER BY source_ticker",
            (next_snapshot,),
        )
        assert [item[0] for item in cur.fetchall()] == [item[0] for item in members]

    renamed = stage_constituents(
        conn,
        _fetch(
            "Industrials",
            ("ALFB", "ALFC"),
            datetime(2026, 10, 10, 12, tzinfo=timezone.utc),
        ),
        minimum_count=2,
    )
    assert review_stage(conn, renamed["stage_id"])["unresolved_symbols"] == ["ALFC"]
    renamed_snapshot = publish_reviewed_stage(
        conn,
        stage_id=renamed["stage_id"],
        expected_checksum=renamed["checksum"],
        reviewer="test reviewer",
        review_note="verified ALFA to ALFC share-line rename",
        decisions={"ALFC": members[0][0]},
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stock_id FROM universe_member WHERE snapshot_id = %s AND source_ticker = 'ALFC'",
            (renamed_snapshot,),
        )
        assert cur.fetchone()[0] == members[0][0]
        cur.execute(
            "SELECT valid_to FROM security_symbol WHERE source = 'fmp-sp500' AND ticker = 'ALFA'"
        )
        assert cur.fetchone()[0].isoformat() == "2026-10-09"


def test_partial_candidate_stays_held(conn):
    candidate = stage_constituents(conn, _fetch(symbols=("ALFA",)), minimum_count=2)
    assert review_stage(conn, candidate["stage_id"])["validation_issues"]
    with pytest.raises(ValueError, match="failed validation"):
        publish_reviewed_stage(
            conn,
            stage_id=candidate["stage_id"],
            expected_checksum=candidate["checksum"],
            reviewer="reviewer",
            review_note="partial response",
            decisions={"ALFA": "new"},
        )
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM catalog_current")
        assert cur.fetchone()[0] == 0


def test_stale_review_cannot_replace_a_newer_catalog(conn):
    first = stage_constituents(conn, _fetch(), minimum_count=2)
    stale = stage_constituents(conn, _fetch("Industrials"), minimum_count=2)
    published = publish_reviewed_stage(
        conn,
        stage_id=first["stage_id"],
        expected_checksum=first["checksum"],
        reviewer="reviewer",
        review_note="approved first candidate",
        decisions={"ALFA": "new", "ALFB": "new"},
    )
    with pytest.raises(ValueError, match="changed after"):
        publish_reviewed_stage(
            conn,
            stage_id=stale["stage_id"],
            expected_checksum=stale["checksum"],
            reviewer="reviewer",
            review_note="stale approval",
            decisions={"ALFA": "new", "ALFB": "new"},
        )
    with conn.cursor() as cur:
        cur.execute("SELECT snapshot_id FROM catalog_current")
        assert cur.fetchone()[0] == published
