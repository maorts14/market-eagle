"""Database-backed approval and admission for recurring Alpaca sessions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID, uuid5

import psycopg

from .alpaca_preparation import CALENDAR_EXCHANGE, PRODUCTION_CATALOG_SOURCES

APPROVAL_NAMESPACE = UUID("b65e5439-26f2-491a-968e-a6b60d293517")
MIN_FULL_CATALOG = 450
FULL_MAPPINGS_SQL = (
    Path(__file__).parent / "helpers/db/sql/ongoing_collection/full_mappings.sql"
).read_text(encoding="utf-8")


def _check_full_mappings(
    cur: psycopg.Cursor, preparation_id: str, snapshot_id: str, target: date
) -> int:
    cur.execute(
        FULL_MAPPINGS_SQL,
        {
            "target": target,
            "preparation_id": preparation_id,
            "snapshot_id": snapshot_id,
        },
    )
    members, mapped = cur.fetchone()
    if members < MIN_FULL_CATALOG or mapped != members:
        raise ValueError(
            "ongoing collection requires complete current full-catalog mappings"
        )
    return members


def approve_ongoing_collection(
    conn: psycopg.Connection,
    *,
    preparation_id: str,
    catalog_source: str,
    reviewer: str,
    review_note: str,
) -> str:
    """Record a distinct recurring approval over reviewed open-ended mappings."""
    if not reviewer.strip() or not review_note.strip():
        raise ValueError("reviewer and review note are required")
    approval_id = uuid5(APPROVAL_NAMESPACE, preparation_id)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT p.snapshot_id, p.requested_end, p.status, s.source, "
            "s.validation_state, c.snapshot_id, d.rights_version, "
            "d.private_use_approved, d.synthetic "
            "FROM alpaca_collection_preparation p "
            "JOIN universe_snapshot s ON s.snapshot_id = p.snapshot_id "
            "LEFT JOIN catalog_current c ON c.singleton = true "
            "LEFT JOIN data_source d ON d.source = 'alpaca' AND d.feed = 'sip' "
            "WHERE p.preparation_id = %s",
            (preparation_id,),
        )
        row = cur.fetchone()
        if (
            row is None
            or catalog_source not in PRODUCTION_CATALOG_SOURCES
            or row[2:6] != ("prepared", catalog_source, "published", row[0])
            or row[6] is None
            or row[7:] != (True, False)
        ):
            raise ValueError(
                "ongoing approval requires the current published full-catalog preparation"
            )
        snapshot_id, reviewed_end = row[:2]
        _check_full_mappings(cur, preparation_id, snapshot_id, reviewed_end)
        cur.execute(
            "INSERT INTO ongoing_collection_approval (approval_id, preparation_id, "
            "snapshot_id, catalog_source, source, feed, price_basis, rights_version, "
            "status, reviewed_by, review_note) "
            "VALUES (%s, %s, %s, %s, 'alpaca', 'sip', 'raw', %s, 'active', %s, %s) "
            "ON CONFLICT (approval_id) DO UPDATE SET "
            "rights_version = EXCLUDED.rights_version, status = 'active', "
            "reviewed_by = EXCLUDED.reviewed_by, "
            "review_note = EXCLUDED.review_note, reviewed_at = now() "
            "WHERE ongoing_collection_approval.preparation_id = EXCLUDED.preparation_id "
            "AND ongoing_collection_approval.snapshot_id = EXCLUDED.snapshot_id "
            "AND ongoing_collection_approval.catalog_source = EXCLUDED.catalog_source "
            "RETURNING approval_id",
            (
                approval_id,
                preparation_id,
                snapshot_id,
                catalog_source,
                row[6],
                reviewer,
                review_note,
            ),
        )
        if cur.fetchone() is None:
            raise ValueError("ongoing approval changed catalog identity")
    return str(approval_id)


def _admit_target(
    cur: psycopg.Cursor, approval_id: str, target: date
) -> tuple[str, str]:
    cur.execute(
        "SELECT a.preparation_id, a.snapshot_id, a.status, a.source, a.feed, "
        "a.price_basis, p.status, s.source, s.validation_state, c.snapshot_id, "
        "p.snapshot_id, a.catalog_source, a.rights_version, d.rights_version, "
        "d.private_use_approved, d.synthetic "
        "FROM ongoing_collection_approval a "
        "JOIN alpaca_collection_preparation p ON p.preparation_id = a.preparation_id "
        "JOIN universe_snapshot s ON s.snapshot_id = a.snapshot_id "
        "LEFT JOIN catalog_current c ON c.singleton = true "
        "LEFT JOIN data_source d ON d.source = a.source AND d.feed = a.feed "
        "WHERE a.approval_id = %s",
        (approval_id,),
    )
    row = cur.fetchone()
    if (
        row is None
        or row[2:]
        != (
            "active",
            "alpaca",
            "sip",
            "raw",
            "prepared",
            row[11],
            "published",
            row[1],
            row[1],
            row[7],
            row[12],
            row[12],
            True,
            False,
        )
        or row[11] not in PRODUCTION_CATALOG_SOURCES
    ):
        raise ValueError("ongoing collection approval or current catalog is held")
    preparation_id, snapshot_id = str(row[0]), row[1]
    _check_full_mappings(cur, preparation_id, snapshot_id, target)
    cur.execute(
        "SELECT open_at, close_at FROM trading_session WHERE exchange = %s "
        "AND session_date = %s AND calendar_source = 'alpaca-trading-calendar' "
        "AND session_type IN ('regular', 'half_day') AND open_at < close_at",
        (CALENDAR_EXCHANGE, target),
    )
    if cur.fetchone() is None:
        raise ValueError("target date lacks a reviewed stored US equity session")
    return preparation_id, snapshot_id


def ongoing_collection_request(
    conn: psycopg.Connection, approval_id: str, target: date, business_id: str
) -> dict:
    """Build a pinned one-session request; no workflow or provider action occurs."""
    with conn.cursor() as cur:
        _, snapshot_id = _admit_target(cur, approval_id, target)
        cur.execute(
            "SELECT stock_id FROM universe_member WHERE snapshot_id = %s ORDER BY stock_id",
            (snapshot_id,),
        )
        stock_ids = [row[0] for row in cur.fetchall()]
    return {
        "approval_id": approval_id,
        "snapshot_id": snapshot_id,
        "start": target.isoformat(),
        "end": target.isoformat(),
        "symbol_asof": target.isoformat(),
        "stock_ids": stock_ids,
        "source": "alpaca",
        "feed": "sip",
        "price_basis": "raw",
        "exchange": CALENDAR_EXCHANGE,
        "collection_run_id": business_id,
    }


def validate_ongoing_collection_group(
    conn: psycopg.Connection, request: dict
) -> list[tuple[str, str, str]]:
    """Recheck the ongoing approval and all mappings before a provider group."""
    target = date.fromisoformat(request["start"])
    if request["end"] != request["start"] or request["symbol_asof"] != request["start"]:
        raise ValueError("ongoing collection must target one session")
    stock_ids = request["stock_ids"]
    if not 1 <= len(stock_ids) <= 5 or len(set(stock_ids)) != len(stock_ids):
        raise ValueError("collection group must contain one to five distinct stocks")
    with conn.cursor() as cur:
        preparation_id, snapshot_id = _admit_target(cur, request["approval_id"], target)
        if (
            request["snapshot_id"],
            request["source"],
            request["feed"],
            request["price_basis"],
            request["exchange"],
        ) != (snapshot_id, "alpaca", "sip", "raw", CALENDAR_EXCHANGE):
            raise ValueError("ongoing request differs from approved source or catalog")
        cur.execute(
            "SELECT a.stock_id, a.symbol, a.exchange FROM alpaca_alias_approval a "
            "JOIN universe_member m ON m.snapshot_id = %s AND m.stock_id = a.stock_id "
            "WHERE a.preparation_id = %s AND a.stock_id = ANY(%s) "
            "AND a.verified_from <= %s AND (a.verified_to IS NULL OR a.verified_to >= %s)",
            (snapshot_id, preparation_id, stock_ids, target, target),
        )
        mappings = cur.fetchall()
    if len(mappings) != len(stock_ids):
        raise ValueError("collection group lacks approved current mappings")
    return mappings
