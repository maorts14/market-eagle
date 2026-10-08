"""Transactional application-store writes for catalogs and daily bars."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("provider_as_of must include a UTC offset")
    return parsed


def _bar_values(row: dict[str, str]) -> tuple[Decimal, Decimal, Decimal, Decimal, int, Decimal | None, Decimal | None]:
    try:
        prices = tuple(Decimal(row[field]) for field in ("open", "high", "low", "close"))
        volume = int(row["volume"])
        vwap = Decimal(row["vwap"]) if row["vwap"] else None
        notional = Decimal(row["traded_notional"]) if row["traded_notional"] else None
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid numeric bar field") from exc
    opened, high, low, close = prices
    if not all(price.is_finite() for price in prices):
        raise ValueError("non-finite price")
    if vwap is not None and not vwap.is_finite() or notional is not None and not notional.is_finite():
        raise ValueError("non-finite VWAP or notional")
    if min(prices) <= 0 or high < max(opened, low, close) or low > min(opened, high, close):
        raise ValueError("inconsistent OHLC prices")
    if volume < 0 or (vwap is not None and vwap <= 0) or (notional is not None and notional < 0):
        raise ValueError("invalid volume, VWAP, or notional")
    return opened, high, low, close, volume, vwap, notional


def publish_catalog(
    conn: psycopg.Connection,
    rows: list[dict[str, str]],
    *,
    source: str,
    taxonomy: str,
    exchange: str,
) -> str:
    """Publish a complete validated snapshot, or leave the previous pointer intact."""
    if not rows:
        raise ValueError("empty catalog")
    snapshot_id = rows[0]["snapshot_id"]
    as_of = rows[0]["catalog_as_of"]
    published_at = rows[0]["published_at"]
    if any(row["snapshot_id"] != snapshot_id or row["catalog_as_of"] != as_of or row["published_at"] != published_at for row in rows):
        raise ValueError("catalog rows disagree on snapshot metadata")
    stock_ids = [row["stock_id"] for row in rows]
    tickers = [row["ticker"] for row in rows]
    if len(set(stock_ids)) != len(rows) or len(set(tickers)) != len(rows):
        raise ValueError("duplicate stock or ticker in catalog")
    if any(not row["sector_code"] or not row["sector_name"] or not row["name"] for row in rows):
        raise ValueError("catalog contains an unclassified or unnamed stock")
    canonical = json.dumps(sorted(rows, key=lambda row: row["stock_id"]), sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode()).hexdigest()
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT source_checksum FROM universe_snapshot WHERE snapshot_id = %s", (snapshot_id,))
            existing = cur.fetchone()
            if existing:
                if existing[0] != checksum:
                    raise ValueError("snapshot ID already names different contents")
                return snapshot_id
            for row in rows:
                cur.execute(
                    "INSERT INTO security (stock_id, name) VALUES (%s, %s) "
                    "ON CONFLICT (stock_id) DO UPDATE SET name = EXCLUDED.name",
                    (row["stock_id"], row["name"]),
                )
                cur.execute(
                    "INSERT INTO security_symbol (stock_id, ticker, exchange, valid_from, source) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (stock_id, ticker, exchange, valid_from, source) DO NOTHING",
                    (row["stock_id"], row["ticker"], exchange, row["listed_from"], source),
                )
                cur.execute(
                    "INSERT INTO listing_period (stock_id, exchange, valid_from, source) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (row["stock_id"], exchange, row["listed_from"], source),
                )
                cur.execute(
                    "INSERT INTO sector (taxonomy, sector_code, sector_name) VALUES (%s, %s, %s) "
                    "ON CONFLICT (taxonomy, sector_code) DO UPDATE SET sector_name = EXCLUDED.sector_name",
                    (taxonomy, row["sector_code"], row["sector_name"]),
                )
            cur.execute(
                "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, captured_at, published_at, "
                "source_checksum, validation_state) VALUES (%s, %s, %s, %s, %s, %s, %s, 'published')",
                (snapshot_id, source, taxonomy, as_of, _timestamp(published_at), _timestamp(published_at), checksum),
            )
            for row in rows:
                cur.execute(
                    "INSERT INTO universe_member (snapshot_id, stock_id, source_ticker, taxonomy, sector_code) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (snapshot_id, row["stock_id"], row["ticker"], taxonomy, row["sector_code"]),
                )
            cur.execute(
                "INSERT INTO catalog_current (singleton, snapshot_id) VALUES (true, %s) "
                "ON CONFLICT (singleton) DO UPDATE SET snapshot_id = EXCLUDED.snapshot_id",
                (snapshot_id,),
            )
    return snapshot_id


def ingest_page(
    conn: psycopg.Connection,
    rows: list[dict[str, str]],
    *,
    collection_run_id: str,
    endpoint: str,
    requested_symbols: list[str],
    requested_start: date,
    requested_end: date,
    source: str,
    feed: str,
    price_basis: str,
    exchange: str,
) -> dict[str, object]:
    """Validate and save one provider page in one transaction; return bounded counts."""
    if not requested_symbols or len(requested_symbols) > 5 or requested_start > requested_end:
        raise ValueError("a page request needs one to five symbols and a valid window")
    fetched_at = datetime.now(timezone.utc)
    accepted: list[tuple] = []
    rejected: list[dict[str, str]] = []
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, stock_id, valid_from, valid_to FROM security_symbol "
                "WHERE source = %s AND exchange = %s AND ticker = ANY(%s) "
                "AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)",
                (source, exchange, requested_symbols, requested_end, requested_start),
            )
            symbols = cur.fetchall()
            cur.execute(
                "SELECT session_date FROM trading_session WHERE exchange = %s "
                "AND session_date BETWEEN %s AND %s",
                (exchange, requested_start, requested_end),
            )
            sessions = {item[0] for item in cur.fetchall()}
            cur.execute(
                "SELECT stock_id, session_date, open, high, low, close, volume, vwap, traded_notional, "
                "observation_status FROM selected_daily_bar WHERE source = %s AND feed = %s "
                "AND price_basis = %s AND session_date BETWEEN %s AND %s AND stock_id = ANY(%s)",
                (source, feed, price_basis, requested_start, requested_end,
                 list({item[1] for item in symbols})),
            )
            current_values = {(item[0], item[1]): item[2:] for item in cur.fetchall()}
            for row in rows:
                try:
                    session = date.fromisoformat(row["session_date"])
                    if session not in sessions:
                        raise ValueError("unknown trading session")
                    matches = [item[1] for item in symbols if item[0] == row["ticker"] and item[2] <= session and (item[3] is None or item[3] >= session)]
                    if len(matches) != 1:
                        raise ValueError("ticker/date does not resolve to one stock")
                    if row["source"] != source or row["feed"] != feed or row["price_basis"] != price_basis:
                        raise ValueError("source, feed, or basis mismatch")
                    status = row["status"]
                    if status not in ("historical", "provisional"):
                        raise ValueError("invalid observation status")
                    as_of_kind = row.get("as_of_kind", "provider")
                    if as_of_kind not in ("provider", "fetched"):
                        raise ValueError("invalid as-of kind")
                    values = _bar_values(row)
                    as_of = _timestamp(row["provider_as_of"])
                    identity = (matches[0], session.isoformat(), source, feed, price_basis,
                                *[str(value) if value is not None else None for value in values],
                                as_of.isoformat() if as_of_kind == "provider" else collection_run_id,
                                as_of_kind, status)
                    content_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
                    accepted.append((matches[0], session, *values, as_of, as_of_kind, status, content_key))
                except (KeyError, ValueError) as exc:
                    rejected.append({"ticker": row.get("ticker", ""), "session_date": row.get("session_date", ""), "reason": str(exc)})
            batch_id = uuid4()
            cur.execute(
                "INSERT INTO ingest_batch (batch_id, collection_run_id, source, feed, endpoint, "
                "requested_symbols, requested_start, requested_end, price_basis, fetched_at, provider_as_of, "
                "parser_version, accepted_count, rejected_count) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '1', %s, %s)",
                (batch_id, collection_run_id, source, feed, endpoint, Jsonb(requested_symbols),
                 requested_start, requested_end, price_basis, fetched_at,
                 max((item[9] for item in accepted), default=None), len(accepted), len(rejected)),
            )
            inserted = 0
            for stock_id, session, opened, high, low, close, volume, vwap, notional, as_of, as_of_kind, status, content_key in accepted:
                values = (opened, high, low, close, volume, vwap, notional, status)
                if as_of_kind == "fetched" and current_values.get((stock_id, session)) == values:
                    cur.execute(
                        "UPDATE daily_bar_current SET last_checked_at = greatest(last_checked_at, %s) "
                        "WHERE stock_id = %s AND session_date = %s AND source = %s AND feed = %s "
                        "AND price_basis = %s",
                        (as_of, stock_id, session, source, feed, price_basis),
                    )
                    continue
                revision_id = uuid4()
                cur.execute(
                    "INSERT INTO daily_bar_revision (revision_id, stock_id, session_date, source, feed, price_basis, "
                    "open, high, low, close, volume, vwap, traded_notional, provider_as_of, observation_status, "
                    "as_of_kind, fetched_at, batch_id, content_key) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (content_key) DO NOTHING RETURNING revision_id",
                    (revision_id, stock_id, session, source, feed, price_basis, opened, high, low, close,
                     volume, vwap, notional, as_of, status, as_of_kind, fetched_at, batch_id, content_key),
                )
                if cur.fetchone() is None:
                    continue
                inserted += 1
                cur.execute(
                    "INSERT INTO daily_bar_current (stock_id, session_date, source, feed, price_basis, "
                    "revision_id, selected_provider_as_of, last_checked_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (stock_id, session_date, source, feed, price_basis) DO UPDATE SET "
                    "revision_id = EXCLUDED.revision_id, selected_provider_as_of = EXCLUDED.selected_provider_as_of, "
                    "last_checked_at = EXCLUDED.last_checked_at "
                    "WHERE daily_bar_current.selected_provider_as_of <= EXCLUDED.selected_provider_as_of",
                    (stock_id, session, source, feed, price_basis, revision_id, as_of, fetched_at),
                )
                if cur.rowcount:
                    current_values[(stock_id, session)] = values
    return {"accepted": len(accepted), "inserted": inserted, "rejected": rejected}


def missing_pairs(
    conn: psycopg.Connection, snapshot_id: str, stock_ids: list[str], start: date, end: date,
    source: str, feed: str, price_basis: str, exchange: str, limit: int = 100,
) -> dict[str, object]:
    """Derive missing requested pairs; listing evidence only excludes known pre-listing dates."""
    if limit < 1 or limit > 1000:
        raise ValueError("repair-plan limit must be between 1 and 1000")
    with conn.cursor() as cur:
        cur.execute(
            "WITH expected AS (SELECT m.stock_id, s.session_date FROM universe_member m "
            "JOIN trading_session s ON s.exchange = %s AND s.session_date BETWEEN %s AND %s "
            "WHERE m.snapshot_id = %s AND m.stock_id = ANY(%s) "
            "AND NOT EXISTS (SELECT 1 FROM listing_period l WHERE l.stock_id = m.stock_id "
            "AND l.source = %s AND s.session_date < l.valid_from)), missing AS ("
            "SELECT e.stock_id, e.session_date FROM expected e LEFT JOIN daily_bar_current c "
            "ON c.stock_id = e.stock_id AND c.session_date = e.session_date AND c.source = %s "
            "AND c.feed = %s AND c.price_basis = %s WHERE c.revision_id IS NULL) "
            "SELECT (SELECT count(*) FROM expected), (SELECT count(*) FROM missing), "
            "coalesce((SELECT jsonb_agg(to_jsonb(p)) FROM (SELECT stock_id, session_date "
            "FROM missing ORDER BY stock_id, session_date LIMIT %s) p), '[]'::jsonb)",
            (exchange, start, end, snapshot_id, stock_ids, source, source, feed, price_basis, limit),
        )
        expected, missing, sample = cur.fetchone()
    return {"expected": expected, "missing": missing, "repair_sample": sample}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))
