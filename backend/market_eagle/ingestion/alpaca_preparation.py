"""Reviewed bridge from published share lines to Alpaca collection inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from uuid import UUID, uuid5

import psycopg

NAMESPACE = UUID("989b9793-f8df-44ed-a226-22ea94f4f65a")
CALENDAR_EXCHANGE = "US_EQUITY"
ALLOWED_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "NYSEARCA"}
PRODUCTION_CATALOG_SOURCES = {"fmp-sp500", "public-sp500-provisional-v1"}


def _checksum(assets: list[dict], sessions: list[dict]) -> str:
    raw = json.dumps(
        {"assets": assets, "sessions": sessions}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def stage_preparation(
    conn: psycopg.Connection,
    *,
    snapshot_id: str,
    requested_start: date,
    requested_end: date,
    assets: list[dict],
    sessions: list[dict],
    fetched_at: datetime,
) -> dict:
    """Hold a bounded asset/calendar observation beside one reviewed snapshot."""
    if (
        requested_start > requested_end
        or (requested_end - requested_start).days > 2_192
    ):
        raise ValueError("invalid or over-six-year collection window")
    prior = [
        date.fromisoformat(row["date"])
        for row in sessions
        if row["date"] < requested_start.isoformat()
    ]
    included = [
        date.fromisoformat(row["date"])
        for row in sessions
        if requested_start.isoformat() <= row["date"] <= requested_end.isoformat()
    ]
    if not prior or not included:
        raise ValueError(
            "calendar lacks a preceding close or requested trading sessions"
        )
    comparison = max(prior)
    checksum = _checksum(assets, sessions)
    preparation_id = uuid5(
        NAMESPACE, f"{snapshot_id}:{requested_start}:{requested_end}:{checksum}"
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT s.source, c.snapshot_id IS NOT NULL FROM universe_snapshot s "
            "LEFT JOIN catalog_current c ON c.snapshot_id = s.snapshot_id "
            "WHERE s.snapshot_id = %s AND s.validation_state = 'published'",
            (snapshot_id,),
        )
        catalog = cur.fetchone()
        if catalog is None or not (
            catalog[0] == "alpaca-sample-v1"
            or (catalog[0] in PRODUCTION_CATALOG_SOURCES and catalog[1])
        ):
            raise ValueError(
                "preparation requires a current reviewed catalog or private sample snapshot"
            )
        cur.execute(
            "SELECT status FROM alpaca_collection_preparation WHERE preparation_id = %s",
            (preparation_id,),
        )
        existing = cur.fetchone()
        if existing:
            return {
                "preparation_id": str(preparation_id),
                "status": existing[0],
                "checksum": checksum,
                "comparison_session": comparison.isoformat(),
            }
        cur.execute(
            "INSERT INTO alpaca_collection_preparation (preparation_id, snapshot_id, source_checksum, "
            "fetched_at, requested_start, requested_end, comparison_session, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'held')",
            (
                preparation_id,
                snapshot_id,
                checksum,
                fetched_at,
                requested_start,
                requested_end,
                comparison,
            ),
        )
        cur.executemany(
            "INSERT INTO alpaca_preparation_asset (preparation_id, asset_id, symbol, exchange, "
            "name, asset_status, asset_class) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    preparation_id,
                    row["id"],
                    row["symbol"],
                    row["exchange"],
                    row["name"],
                    row["status"],
                    row["class"],
                )
                for row in assets
            ],
        )
        cur.executemany(
            "INSERT INTO alpaca_preparation_session (preparation_id, session_date, open_at, close_at, "
            "session_type) VALUES (%s, %s, %s, %s, %s)",
            [
                (
                    preparation_id,
                    row["date"],
                    row["open_at"],
                    row["close_at"],
                    row["type"],
                )
                for row in sessions
            ],
        )
    return {
        "preparation_id": str(preparation_id),
        "status": "held",
        "checksum": checksum,
        "comparison_session": comparison.isoformat(),
        "asset_count": len(assets),
        "session_count": len(sessions),
    }


def review_preparation(conn: psycopg.Connection, preparation_id: str) -> dict:
    """Return candidates and a blank approval draft; never infer share-line identity."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_id, source_checksum, fetched_at, requested_start, requested_end, "
            "comparison_session, status FROM alpaca_collection_preparation WHERE preparation_id = %s",
            (preparation_id,),
        )
        stage = cur.fetchone()
        if stage is None:
            raise ValueError("collection preparation not found")
        cur.execute(
            "SELECT stock_id, source_ticker FROM universe_member WHERE snapshot_id = %s ORDER BY stock_id",
            (stage[0],),
        )
        members = cur.fetchall()
        cur.execute(
            "SELECT asset_id, symbol, exchange, name FROM alpaca_preparation_asset "
            "WHERE preparation_id = %s ORDER BY symbol, exchange",
            (preparation_id,),
        )
        assets = cur.fetchall()
    by_symbol = {}
    for asset_id, symbol, exchange, name in assets:
        by_symbol.setdefault(symbol, []).append(
            {
                "asset_id": str(asset_id),
                "symbol": symbol,
                "exchange": exchange,
                "name": name,
            }
        )
    candidates = [
        {
            "stock_id": stock_id,
            "catalog_symbol": symbol,
            "alpaca_candidates": by_symbol.get(symbol, []),
        }
        for stock_id, symbol in members
    ]
    return {
        "preparation_id": preparation_id,
        "snapshot_id": stage[0],
        "checksum": stage[1],
        "fetched_at": stage[2].isoformat(),
        "requested_start": stage[3].isoformat(),
        "requested_end": stage[4].isoformat(),
        "comparison_session": stage[5].isoformat(),
        "status": stage[6],
        "member_count": len(members),
        "missing_exact_symbol_count": sum(
            not item["alpaca_candidates"] for item in candidates
        ),
        "ambiguous_exact_symbol_count": sum(
            len(item["alpaca_candidates"]) > 1 for item in candidates
        ),
        "candidates": candidates,
    }


def approve_preparation(
    conn: psycopg.Connection,
    *,
    preparation_id: str,
    expected_checksum: str,
    reviewer: str,
    review_note: str,
    aliases: list[dict],
) -> dict:
    """Register all aliases, calendar, and SIP source in one reviewed transaction."""
    if not reviewer.strip() or not review_note.strip():
        raise ValueError("reviewer and review note are required")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext('market-eagle-collection-preparation'))"
        )
        cur.execute(
            "SELECT snapshot_id, source_checksum, requested_end, comparison_session, "
            "status FROM alpaca_collection_preparation WHERE preparation_id = %s FOR UPDATE",
            (preparation_id,),
        )
        stage = cur.fetchone()
        if stage is None:
            raise ValueError("collection preparation not found")
        snapshot_id, checksum, end, comparison, status = stage
        if checksum != expected_checksum:
            raise ValueError(
                "reviewed checksum does not match prepared assets and calendar"
            )
        if status == "prepared":
            return collection_request(conn, preparation_id)
        cur.execute(
            "SELECT source FROM universe_snapshot WHERE snapshot_id = %s AND validation_state = 'published'",
            (snapshot_id,),
        )
        catalog = cur.fetchone()
        if catalog is None or catalog[0] not in (
            *PRODUCTION_CATALOG_SOURCES,
            "alpaca-sample-v1",
        ):
            raise ValueError("prepared catalog is no longer published")
        if catalog[0] in PRODUCTION_CATALOG_SOURCES:
            cur.execute(
                "SELECT snapshot_id FROM catalog_current WHERE singleton = true"
            )
            current = cur.fetchone()
            if current is None or current[0] != snapshot_id:
                raise ValueError("current catalog changed after preparation was staged")
        cur.execute(
            "SELECT stock_id, source_ticker FROM universe_member WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        members = dict(cur.fetchall())
        if len(aliases) != len(members) or {
            item["stock_id"] for item in aliases
        } != set(members):
            raise ValueError("approval must resolve every distinct snapshot stock ID")
        cur.execute(
            "SELECT asset_id, symbol, exchange FROM alpaca_preparation_asset WHERE preparation_id = %s "
            "AND asset_status = 'active' AND asset_class = 'us_equity'",
            (preparation_id,),
        )
        available = {str(item[0]): (item[1], item[2]) for item in cur.fetchall()}
        approved_symbols = set()
        approved_assets = set()
        for item in aliases:
            stock_id, asset_id = item["stock_id"], item["asset_id"]
            actual = available.get(asset_id)
            if (
                actual != (item["symbol"], item["exchange"])
                or item["exchange"] not in ALLOWED_EXCHANGES
            ):
                raise ValueError(
                    f"{stock_id} has no eligible matching staged Alpaca asset"
                )
            if asset_id in approved_assets or item["symbol"] in approved_symbols:
                raise ValueError("two share lines reuse one Alpaca asset or symbol")
            verified_from = date.fromisoformat(item["verified_from"])
            verified_to = (
                date.fromisoformat(item["verified_to"])
                if item.get("verified_to")
                else None
            )
            if (
                verified_from > comparison
                or verified_to is not None
                and verified_to < end
            ):
                raise ValueError(
                    f"{stock_id} alias does not span the requested history"
                )
            if not item["evidence"].strip():
                raise ValueError(f"{stock_id} needs dated alias/share-line evidence")
            if (
                item["symbol"] != members[stock_id]
                and not item.get("symbol_difference_reason", "").strip()
            ):
                raise ValueError(
                    f"{stock_id} ticker differs from FMP without a reviewed reason"
                )
            cur.execute(
                "SELECT ticker, exchange, valid_from, valid_to FROM security_symbol "
                "WHERE stock_id = %s AND source = 'alpaca' AND ticker = %s AND exchange = %s",
                (stock_id, item["symbol"], item["exchange"]),
            )
            existing = cur.fetchall()
            if existing:
                if (
                    len(existing) != 1
                    or existing[0][2] > verified_from
                    or (existing[0][3] is not None and existing[0][3] < end)
                ):
                    raise ValueError(
                        f"{stock_id} existing Alpaca alias needs separate history review"
                    )
            else:
                cur.execute(
                    "INSERT INTO security_symbol (stock_id, ticker, exchange, valid_from, valid_to, source) "
                    "VALUES (%s, %s, %s, %s, %s, 'alpaca')",
                    (
                        stock_id,
                        item["symbol"],
                        item["exchange"],
                        verified_from,
                        verified_to,
                    ),
                )
            cur.execute(
                "INSERT INTO alpaca_alias_approval (preparation_id, stock_id, asset_id, symbol, "
                "exchange, verified_from, verified_to, evidence) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    preparation_id,
                    stock_id,
                    asset_id,
                    item["symbol"],
                    item["exchange"],
                    verified_from,
                    verified_to,
                    item["evidence"],
                ),
            )
            approved_assets.add(asset_id)
            approved_symbols.add(item["symbol"])
        cur.execute(
            "SELECT session_date, open_at, close_at, session_type FROM alpaca_preparation_session "
            "WHERE preparation_id = %s ORDER BY session_date",
            (preparation_id,),
        )
        sessions = cur.fetchall()
        cur.execute(
            "SELECT session_date, open_at, close_at, session_type, calendar_source "
            "FROM trading_session WHERE exchange = %s AND session_date BETWEEN %s AND %s",
            (CALENDAR_EXCHANGE, comparison, end),
        )
        existing_sessions = {row[0]: row[1:] for row in cur.fetchall()}
        for session_date, opened, closed, session_type in sessions:
            if session_date < comparison or session_date > end:
                continue
            prior = existing_sessions.get(session_date)
            if prior is not None:
                if prior != (opened, closed, session_type, "alpaca-trading-calendar"):
                    raise ValueError(
                        "stored US equity calendar conflicts with reviewed Alpaca calendar"
                    )
            else:
                cur.execute(
                    "INSERT INTO trading_session (exchange, session_date, session_type, open_at, close_at, "
                    "calendar_source) VALUES (%s, %s, %s, %s, %s, 'alpaca-trading-calendar')",
                    (CALENDAR_EXCHANGE, session_date, session_type, opened, closed),
                )
        cur.execute(
            "INSERT INTO data_source (source, feed, rights_version, provider, synthetic) "
            "VALUES ('alpaca', 'sip', 'paper-basic-private-probe-rights-unconfirmed', 'alpaca', false) "
            "ON CONFLICT (source, feed) DO NOTHING"
        )
        cur.execute(
            "UPDATE alpaca_collection_preparation SET status = 'prepared', reviewed_by = %s, "
            "review_note = %s, reviewed_at = now() WHERE preparation_id = %s",
            (reviewer, review_note, preparation_id),
        )
    return collection_request(conn, preparation_id)


def collection_request(conn: psycopg.Connection, preparation_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_id, comparison_session, requested_end, fetched_at, status "
            "FROM alpaca_collection_preparation WHERE preparation_id = %s",
            (preparation_id,),
        )
        stage = cur.fetchone()
        if stage is None or stage[4] != "prepared":
            raise ValueError("collection preparation is not approved")
        cur.execute(
            "SELECT stock_id FROM alpaca_alias_approval WHERE preparation_id = %s ORDER BY stock_id",
            (preparation_id,),
        )
        stock_ids = [row[0] for row in cur.fetchall()]
    return {
        "preparation_id": preparation_id,
        "snapshot_id": stage[0],
        "start": stage[1].isoformat(),
        "end": stage[2].isoformat(),
        "symbol_asof": stage[3].date().isoformat(),
        "stock_ids": stock_ids,
        "source": "alpaca",
        "feed": "sip",
        "price_basis": "raw",
        "exchange": CALENDAR_EXCHANGE,
        "collection_run_id": f"alpaca-backfill:{preparation_id}",
    }


def validate_collection_group(
    conn: psycopg.Connection, request: dict
) -> list[tuple[str, str, str]]:
    """Ensure a worker request is a subset of a reviewed, date-spanning preparation."""
    preparation_id = request.get("preparation_id")
    if not preparation_id:
        raise ValueError("Alpaca collection requires a reviewed preparation ID")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot_id, comparison_session, requested_end, status, fetched_at FROM "
            "alpaca_collection_preparation WHERE preparation_id = %s",
            (preparation_id,),
        )
        stage = cur.fetchone()
        if stage is None or stage[3] != "prepared":
            raise ValueError("Alpaca collection preparation is not approved")
        if (
            request["snapshot_id"],
            request["source"],
            request["feed"],
            request["price_basis"],
            request["exchange"],
        ) != (stage[0], "alpaca", "sip", "raw", CALENDAR_EXCHANGE):
            raise ValueError(
                "collection request differs from approved source or catalog"
            )
        if request.get("symbol_asof") != stage[4].date().isoformat():
            raise ValueError("collection symbol as-of differs from reviewed assets")
        start, end = (
            date.fromisoformat(request["start"]),
            date.fromisoformat(request["end"]),
        )
        if start < stage[1] or end > stage[2] or start > end:
            raise ValueError("collection window exceeds reviewed preparation")
        stock_ids = request["stock_ids"]
        if not 1 <= len(stock_ids) <= 5 or len(set(stock_ids)) != len(stock_ids):
            raise ValueError(
                "collection group must contain one to five distinct stocks"
            )
        cur.execute(
            "SELECT stock_id, symbol, exchange FROM alpaca_alias_approval "
            "WHERE preparation_id = %s AND stock_id = ANY(%s) AND verified_from <= %s "
            "AND (verified_to IS NULL OR verified_to >= %s)",
            (preparation_id, stock_ids, start, end),
        )
        mappings = cur.fetchall()
        cur.execute(
            "SELECT ticker, stock_id, exchange FROM security_symbol WHERE source = 'alpaca' "
            "AND ticker = ANY(%s) AND valid_from <= %s "
            "AND (valid_to IS NULL OR valid_to >= %s)",
            ([row[1] for row in mappings], end, start),
        )
        active_aliases = cur.fetchall()
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM alpaca_preparation_session s LEFT JOIN trading_session t "
            "ON t.exchange = %s AND t.session_date = s.session_date "
            "AND t.open_at = s.open_at AND t.close_at = s.close_at "
            "AND t.session_type = s.session_type "
            "AND t.calendar_source = 'alpaca-trading-calendar' "
            "WHERE s.preparation_id = %s AND s.session_date BETWEEN %s AND %s "
            "AND t.session_date IS NULL)",
            (CALENDAR_EXCHANGE, preparation_id, start, end),
        )
        calendar_missing = cur.fetchone()[0]
    if len(mappings) != len(stock_ids) or len({row[1] for row in mappings}) != len(
        stock_ids
    ):
        raise ValueError(
            "collection group has incomplete or ambiguous approved Alpaca aliases"
        )
    if set(active_aliases) != {(row[1], row[0], row[2]) for row in mappings}:
        raise ValueError("approved Alpaca alias conflicts with current symbol history")
    if calendar_missing:
        raise ValueError("approved Alpaca calendar is missing from trading sessions")
    return mappings
