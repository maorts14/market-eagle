"""Private, reviewed five-stock catalog for validating Alpaca SIP ingestion."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid5

import psycopg

from .alpaca_preparation import (
    _checksum,
    approve_preparation,
    collection_request,
    stage_preparation,
)

SOURCE = "alpaca-sample-v1"
TAXONOMY = "sample-unclassified-v1"
SECTOR = "UNCLASSIFIED"
NAMESPACE = UUID("2cd867f3-bfc8-4c8b-b43d-51c07fc796bc")


def sample_stock_id(asset_id: str) -> str:
    """Keep a sample share line stable across repeated observations and ticker changes."""
    return f"sample:alpaca:{UUID(asset_id)}"


def stage_sample(
    conn: psycopg.Connection,
    *,
    symbols: list[str],
    requested_start: date,
    requested_end: date,
    assets: list[dict],
    sessions: list[dict],
    fetched_at: datetime,
) -> dict:
    """Hold exactly five current assets and roughly two years of sessions for review."""
    if (
        len(symbols) != 5
        or len(set(symbols)) != 5
        or any(not symbol or symbol != symbol.strip().upper() for symbol in symbols)
    ):
        raise ValueError("sample requires five distinct uppercase Alpaca symbols")
    days = (requested_end - requested_start).days
    if not 725 <= days <= 735:
        raise ValueError("sample window must span two years")
    selected = [asset for asset in assets if asset["symbol"] in symbols]
    if len(selected) != 5 or {asset["symbol"] for asset in selected} != set(symbols):
        raise ValueError("each sample symbol needs one current Alpaca asset")
    if any(
        asset["status"] != "active" or asset["class"] != "us_equity"
        for asset in selected
    ):
        raise ValueError("sample assets must be active US equities")
    sessions = sorted(sessions, key=lambda item: item["date"])
    preceding = [
        date.fromisoformat(item["date"])
        for item in sessions
        if item["date"] < requested_start.isoformat()
    ]
    included = [
        item
        for item in sessions
        if requested_start.isoformat() <= item["date"] <= requested_end.isoformat()
    ]
    if not preceding or not 450 <= len(included) <= 550:
        raise ValueError(
            "sample calendar needs a preceding close and two years of sessions"
        )
    comparison = max(preceding)
    if (
        requested_start - comparison > timedelta(days=7)
        or date.fromisoformat(included[0]["date"]) - requested_start > timedelta(days=7)
        or requested_end - date.fromisoformat(included[-1]["date"]) > timedelta(days=7)
    ):
        raise ValueError("sample calendar does not reach both window boundaries")
    selected.sort(key=lambda item: item["symbol"])
    checksum = _checksum(selected, sessions)
    stage_id = uuid5(NAMESPACE, f"{requested_start}:{requested_end}:{checksum}")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM alpaca_sample_stage WHERE stage_id = %s", (stage_id,)
        )
        existing = cur.fetchone()
        if existing:
            return {
                "stage_id": str(stage_id),
                "status": existing[0],
                "checksum": checksum,
            }
        cur.execute(
            "INSERT INTO alpaca_sample_stage (stage_id, source_checksum, fetched_at, "
            "requested_start, requested_end, comparison_session, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'held')",
            (
                stage_id,
                checksum,
                fetched_at,
                requested_start,
                requested_end,
                comparison,
            ),
        )
        cur.executemany(
            "INSERT INTO alpaca_sample_asset (stage_id, asset_id, stock_id, symbol, exchange, name) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [
                (
                    stage_id,
                    item["id"],
                    sample_stock_id(item["id"]),
                    item["symbol"],
                    item["exchange"],
                    item["name"],
                )
                for item in selected
            ],
        )
        cur.executemany(
            "INSERT INTO alpaca_sample_session (stage_id, session_date, open_at, close_at, session_type) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (
                    stage_id,
                    item["date"],
                    item["open_at"],
                    item["close_at"],
                    item["type"],
                )
                for item in sessions
            ],
        )
    return {
        "stage_id": str(stage_id),
        "status": "held",
        "checksum": checksum,
        "source": SOURCE,
        "comparison_session": comparison.isoformat(),
        "session_count": len(included),
    }


def review_sample(conn: psycopg.Connection, stage_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_checksum, fetched_at, requested_start, requested_end, "
            "comparison_session, status, snapshot_id, preparation_id "
            "FROM alpaca_sample_stage WHERE stage_id = %s",
            (stage_id,),
        )
        stage = cur.fetchone()
        if stage is None:
            raise ValueError("sample stage not found")
        cur.execute(
            "SELECT stock_id, asset_id, symbol, exchange, name FROM alpaca_sample_asset "
            "WHERE stage_id = %s ORDER BY symbol",
            (stage_id,),
        )
        assets = cur.fetchall()
        cur.execute(
            "SELECT count(*) FROM alpaca_sample_session WHERE stage_id = %s "
            "AND session_date BETWEEN %s AND %s",
            (stage_id, stage[2], stage[3]),
        )
        session_count = cur.fetchone()[0]
    return {
        "stage_id": stage_id,
        "checksum": stage[0],
        "fetched_at": stage[1].isoformat(),
        "requested_start": stage[2].isoformat(),
        "requested_end": stage[3].isoformat(),
        "comparison_session": stage[4].isoformat(),
        "status": stage[5],
        "snapshot_id": stage[6],
        "preparation_id": str(stage[7]) if stage[7] else None,
        "source": SOURCE,
        "sector_taxonomy": TAXONOMY,
        "membership_claim": "five-stock private validation sample; not S&P 500",
        "session_count": session_count,
        "assets": [
            {
                "stock_id": row[0],
                "asset_id": str(row[1]),
                "symbol": row[2],
                "exchange": row[3],
                "name": row[4],
            }
            for row in assets
        ],
    }


def approve_sample(
    conn: psycopg.Connection,
    *,
    stage_id: str,
    expected_checksum: str,
    reviewer: str,
    review_note: str,
    aliases: list[dict],
) -> dict:
    """Publish the isolated sample and its collection preparation atomically."""
    if not reviewer.strip() or not review_note.strip():
        raise ValueError("reviewer and review note are required")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext('market-eagle-sample-publication'))"
        )
        cur.execute(
            "SELECT source_checksum, fetched_at, requested_start, requested_end, "
            "status, preparation_id FROM alpaca_sample_stage WHERE stage_id = %s FOR UPDATE",
            (stage_id,),
        )
        stage = cur.fetchone()
        if stage is None:
            raise ValueError("sample stage not found")
        checksum, fetched_at, start, end, status, preparation_id = stage
        if checksum != expected_checksum:
            raise ValueError("reviewed checksum does not match staged sample")
        if status == "published":
            return collection_request(conn, str(preparation_id))
        cur.execute(
            "SELECT asset_id, stock_id, symbol, exchange, name FROM alpaca_sample_asset "
            "WHERE stage_id = %s ORDER BY symbol",
            (stage_id,),
        )
        assets = cur.fetchall()
        if len(assets) != 5 or len(aliases) != 5:
            raise ValueError("sample approval requires all five assets")
        if any(
            stock_id != sample_stock_id(str(asset_id))
            for asset_id, stock_id, *_ in assets
        ):
            raise ValueError("sample stock ID differs from its staged Alpaca asset ID")
        expected = {row[1]: (str(row[0]), row[2], row[3]) for row in assets}
        if {
            item["stock_id"]: (item["asset_id"], item["symbol"], item["exchange"])
            for item in aliases
        } != expected:
            raise ValueError(
                "sample approval must match every staged asset and stock ID"
            )
        cur.execute(
            "SELECT session_date, open_at, close_at, session_type FROM alpaca_sample_session "
            "WHERE stage_id = %s ORDER BY session_date",
            (stage_id,),
        )
        sessions = [
            {
                "date": row[0].isoformat(),
                "open_at": row[1].isoformat(),
                "close_at": row[2].isoformat(),
                "type": row[3],
            }
            for row in cur.fetchall()
        ]
        staged_assets = [
            {
                "id": str(row[0]),
                "symbol": row[2],
                "exchange": row[3],
                "name": row[4],
                "status": "active",
                "class": "us_equity",
            }
            for row in assets
        ]
        if _checksum(staged_assets, sessions) != checksum:
            raise ValueError("stored sample contents differ from reviewed checksum")
        snapshot_id = f"alpaca-sample-v1-{stage_id}"
        observed_on = fetched_at.astimezone(timezone.utc).date()
        cur.execute(
            "INSERT INTO sector (taxonomy, sector_code, sector_name) "
            "VALUES (%s, %s, 'Unclassified private sample') "
            "ON CONFLICT (taxonomy, sector_code) DO NOTHING",
            (TAXONOMY, SECTOR),
        )
        cur.execute(
            "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, captured_at, "
            "published_at, source_checksum, validation_state) "
            "VALUES (%s, %s, %s, %s, %s, now(), %s, 'published')",
            (snapshot_id, SOURCE, TAXONOMY, observed_on, fetched_at, checksum),
        )
        for asset_id, stock_id, symbol, exchange, name in assets:
            cur.execute(
                "INSERT INTO security (stock_id, name) VALUES (%s, %s) "
                "ON CONFLICT (stock_id) DO NOTHING",
                (stock_id, name),
            )
            cur.execute(
                "INSERT INTO universe_member (snapshot_id, stock_id, source_ticker, taxonomy, sector_code) "
                "VALUES (%s, %s, %s, %s, %s)",
                (snapshot_id, stock_id, symbol, TAXONOMY, SECTOR),
            )
        prepared = stage_preparation(
            conn,
            snapshot_id=snapshot_id,
            requested_start=start,
            requested_end=end,
            assets=staged_assets,
            sessions=sessions,
            fetched_at=fetched_at,
        )
        request = approve_preparation(
            conn,
            preparation_id=prepared["preparation_id"],
            expected_checksum=prepared["checksum"],
            reviewer=reviewer,
            review_note=review_note,
            aliases=aliases,
        )
        cur.execute(
            "UPDATE alpaca_sample_stage SET status = 'published', reviewed_by = %s, "
            "review_note = %s, reviewed_at = now(), snapshot_id = %s, preparation_id = %s "
            "WHERE stage_id = %s",
            (reviewer, review_note, snapshot_id, prepared["preparation_id"], stage_id),
        )
    return request
