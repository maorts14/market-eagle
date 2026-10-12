"""Stage membership, inspect changes, and publish only after explicit review."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.types.json import Jsonb

from .fmp import ENDPOINT, FmpFetch, checksum_rows

SOURCE = "fmp-sp500"
TAXONOMY = "fmp-sector-unverified-v1"
PROVISIONAL_SOURCE = "public-sp500-provisional-v1"
PROVISIONAL_TAXONOMY = "community-sector-provisional-v1"
CATALOG_TAXONOMIES = {
    SOURCE: TAXONOMY,
    PROVISIONAL_SOURCE: PROVISIONAL_TAXONOMY,
}
EXCHANGE = "UNVERIFIED"
STAGE_NAMESPACE = UUID("1a9c15b1-e445-4135-8ccb-f0736b8861f5")


def stage_constituents(
    conn: psycopg.Connection,
    fetched: FmpFetch,
    minimum_count: int = 450,
    *,
    source: str = SOURCE,
    endpoint: str = ENDPOINT,
) -> dict:
    """Persist a normalized candidate and existing exact-alias suggestions, not a publication."""
    if not 1 <= minimum_count <= 700:
        raise ValueError("minimum_count must be between 1 and 700")
    if source not in CATALOG_TAXONOMIES:
        raise ValueError("unsupported reviewed catalog source")
    if not endpoint:
        raise ValueError("catalog source location is required")
    if fetched.checksum != checksum_rows(fetched.rows):
        raise ValueError("staged checksum does not match rows")
    observed_on = fetched.fetched_at.astimezone(timezone.utc).date()
    stage_id = uuid5(STAGE_NAMESPACE, f"{source}:{observed_on}:{fetched.checksum}")
    issues = (
        []
        if len(fetched.rows) >= minimum_count
        else [f"only {len(fetched.rows)} rows; minimum is {minimum_count}"]
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT status FROM catalog_stage WHERE stage_id = %s", (stage_id,))
        existing = cur.fetchone()
        if existing:
            return {
                "stage_id": str(stage_id),
                "status": existing[0],
                "checksum": fetched.checksum,
            }
        cur.execute("SELECT snapshot_id FROM catalog_current WHERE singleton = true")
        baseline_row = cur.fetchone()
        baseline_snapshot_id = baseline_row[0] if baseline_row else None
        cur.execute(
            "SELECT ticker, stock_id FROM security_symbol WHERE source = %s AND exchange = %s "
            "AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)",
            (source, EXCHANGE, observed_on, observed_on),
        )
        aliases = dict(cur.fetchall())
        cur.execute(
            "INSERT INTO catalog_stage (stage_id, source, endpoint, fetched_at, source_checksum, "
            "baseline_snapshot_id, row_count, minimum_count, status, validation_issues) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'held', %s)",
            (
                stage_id,
                source,
                endpoint,
                fetched.fetched_at,
                fetched.checksum,
                baseline_snapshot_id,
                len(fetched.rows),
                minimum_count,
                Jsonb(issues),
            ),
        )
        cur.executemany(
            "INSERT INTO catalog_stage_member (stage_id, symbol, name, sector_label, "
            "sub_sector, cik, date_first_added, suggested_stock_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    stage_id,
                    row["symbol"],
                    row["name"],
                    row["sector"],
                    row["subSector"],
                    row["cik"],
                    row["dateFirstAdded"],
                    aliases.get(row["symbol"]),
                )
                for row in fetched.rows
            ],
        )
    return {
        "stage_id": str(stage_id),
        "status": "held",
        "checksum": fetched.checksum,
        "row_count": len(fetched.rows),
        "issues": issues,
    }


def review_stage(conn: psycopg.Connection, stage_id: str) -> dict:
    """Return a bounded review report; never change the current catalog."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_checksum, fetched_at, row_count, minimum_count, status, "
            "validation_issues, published_snapshot_id, baseline_snapshot_id, source, endpoint "
            "FROM catalog_stage WHERE stage_id = %s",
            (stage_id,),
        )
        stage = cur.fetchone()
        if stage is None:
            raise ValueError("catalog stage not found")
        cur.execute(
            "SELECT symbol, name, sector_label, sub_sector, cik, date_first_added, "
            "suggested_stock_id FROM catalog_stage_member WHERE stage_id = %s ORDER BY symbol",
            (stage_id,),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT source_ticker, stock_id, sector_code FROM universe_member "
            "WHERE snapshot_id = %s",
            (stage[7],),
        )
        previous = {item[0]: (item[1], item[2]) for item in cur.fetchall()}
    new = {item[0]: item for item in rows}
    additions = sorted(set(new) - set(previous))
    removals = sorted(set(previous) - set(new))
    sector_changes = [
        item[0]
        for item in rows
        if item[0] in previous and item[2] != previous[item[0]][1]
    ]
    unresolved = [item[0] for item in rows if item[6] is None]
    return {
        "stage_id": stage_id,
        "status": stage[4],
        "checksum": stage[0],
        "fetched_at": stage[1].isoformat(),
        "row_count": stage[2],
        "minimum_count": stage[3],
        "validation_issues": stage[5],
        "published_snapshot_id": stage[6],
        "baseline_snapshot_id": stage[7],
        "source": stage[8],
        "source_location": stage[9],
        "sector_taxonomy": CATALOG_TAXONOMIES[stage[8]],
        "provider_publication_time": None,
        "additions": additions,
        "removals": removals,
        "sector_changes": sector_changes,
        "unresolved_symbols": unresolved,
        "members": [
            {
                "symbol": item[0],
                "name": item[1],
                "sector": item[2],
                "sub_sector": item[3],
                "cik": item[4],
                "date_first_added": item[5].isoformat() if item[5] else None,
                "suggested_stock_id": item[6],
            }
            for item in rows
        ],
    }


def publish_reviewed_stage(
    conn: psycopg.Connection,
    *,
    stage_id: str,
    expected_checksum: str,
    reviewer: str,
    review_note: str,
    decisions: dict[str, str],
) -> str:
    """Atomically publish only an explicitly reviewed, fully resolved candidate."""
    if not reviewer.strip() or not review_note.strip():
        raise ValueError("reviewer and review note are required")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext('market-eagle-catalog-publication'))"
        )
        cur.execute(
            "SELECT source_checksum, fetched_at, row_count, minimum_count, validation_issues, "
            "status, published_snapshot_id, baseline_snapshot_id, source "
            "FROM catalog_stage WHERE stage_id = %s FOR UPDATE",
            (stage_id,),
        )
        stage = cur.fetchone()
        if stage is None:
            raise ValueError("catalog stage not found")
        (
            checksum,
            fetched_at,
            count,
            minimum,
            issues,
            status,
            published_id,
            baseline_id,
            source,
        ) = stage
        if source not in CATALOG_TAXONOMIES:
            raise ValueError("unsupported reviewed catalog source")
        taxonomy = CATALOG_TAXONOMIES[source]
        if checksum != expected_checksum:
            raise ValueError("reviewed checksum does not match staged contents")
        if status == "published":
            return published_id
        cur.execute(
            "SELECT snapshot_id FROM catalog_current WHERE singleton = true FOR UPDATE"
        )
        current_row = cur.fetchone()
        if (current_row[0] if current_row else None) != baseline_id:
            raise ValueError("current catalog changed after this stage was captured")
        if count < minimum or issues:
            raise ValueError("catalog stage failed validation and cannot be published")
        cur.execute(
            "SELECT symbol, name, sector_label, suggested_stock_id FROM catalog_stage_member "
            "WHERE stage_id = %s ORDER BY symbol",
            (stage_id,),
        )
        members = cur.fetchall()
        symbols = {item[0] for item in members}
        if set(decisions) - symbols:
            raise ValueError("review decisions include unknown symbols")
        resolved = {}
        new_symbols = []
        for symbol, _name, _sector, suggested in members:
            decision = decisions.get(symbol)
            if suggested:
                if decision is not None and decision != suggested:
                    raise ValueError(
                        f"{symbol} conflicts with its established catalog alias"
                    )
                resolved[symbol] = suggested
            elif decision == "new":
                resolved[symbol] = str(uuid4())
                new_symbols.append(symbol)
            elif decision:
                resolved[symbol] = decision
            else:
                raise ValueError(f"{symbol} needs an explicit stock identity decision")
        if len(set(resolved.values())) != len(members):
            raise ValueError("two constituent symbols resolve to one stock ID")
        mapped_ids = [
            resolved[symbol] for symbol in resolved if symbol not in new_symbols
        ]
        cur.execute(
            "SELECT stock_id FROM security WHERE stock_id = ANY(%s)", (mapped_ids,)
        )
        if set(mapped_ids) != {item[0] for item in cur.fetchall()}:
            raise ValueError("a reviewed stock ID does not exist")
        observed_on = fetched_at.astimezone(timezone.utc).date()
        snapshot_id = f"{source}-{observed_on}-{checksum[:12]}"
        cur.execute(
            "INSERT INTO universe_snapshot (snapshot_id, source, taxonomy, as_of, captured_at, "
            "published_at, source_checksum, validation_state) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'published')",
            (
                snapshot_id,
                source,
                taxonomy,
                observed_on,
                fetched_at,
                datetime.now(timezone.utc),
                checksum,
            ),
        )
        for symbol, name, sector_label, _suggested in members:
            stock_id = resolved[symbol]
            cur.execute(
                "INSERT INTO security (stock_id, name) VALUES (%s, %s) "
                "ON CONFLICT (stock_id) DO UPDATE SET name = EXCLUDED.name",
                (stock_id, name),
            )
            if symbol not in new_symbols:
                cur.execute(
                    "UPDATE security_symbol SET valid_to = %s WHERE stock_id = %s "
                    "AND source = %s AND exchange = %s AND ticker <> %s AND valid_to IS NULL "
                    "AND valid_from < %s",
                    (
                        observed_on - timedelta(days=1),
                        stock_id,
                        source,
                        EXCHANGE,
                        symbol,
                        observed_on,
                    ),
                )
            cur.execute(
                "INSERT INTO security_symbol (stock_id, ticker, exchange, valid_from, source) "
                "SELECT %s, %s, %s, %s, %s WHERE NOT EXISTS ("
                "SELECT 1 FROM security_symbol WHERE stock_id = %s AND ticker = %s "
                "AND exchange = %s AND source = %s AND valid_from <= %s "
                "AND (valid_to IS NULL OR valid_to >= %s))",
                (
                    stock_id,
                    symbol,
                    EXCHANGE,
                    observed_on,
                    source,
                    stock_id,
                    symbol,
                    EXCHANGE,
                    source,
                    observed_on,
                    observed_on,
                ),
            )
            cur.execute(
                "INSERT INTO sector (taxonomy, sector_code, sector_name) VALUES (%s, %s, %s) "
                "ON CONFLICT (taxonomy, sector_code) DO NOTHING",
                (taxonomy, sector_label, sector_label),
            )
            cur.execute(
                "INSERT INTO universe_member (snapshot_id, stock_id, source_ticker, taxonomy, sector_code) "
                "VALUES (%s, %s, %s, %s, %s)",
                (snapshot_id, stock_id, symbol, taxonomy, sector_label),
            )
        cur.execute(
            "INSERT INTO catalog_current (singleton, snapshot_id) VALUES (true, %s) "
            "ON CONFLICT (singleton) DO UPDATE SET snapshot_id = EXCLUDED.snapshot_id",
            (snapshot_id,),
        )
        cur.execute(
            "UPDATE catalog_stage SET status = 'published', reviewed_by = %s, review_note = %s, "
            "reviewed_at = now(), published_snapshot_id = %s WHERE stage_id = %s",
            (reviewer, review_note, snapshot_id, stage_id),
        )
    return snapshot_id
