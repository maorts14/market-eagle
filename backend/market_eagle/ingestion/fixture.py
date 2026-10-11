"""Load the explicitly fictional synthetic-v1 fixture into application PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import psycopg

from .store import ingest_page, publish_catalog, read_csv


def load_fixture(
    conn: psycopg.Connection, fixture_dir: Path, page_size: int = 500
) -> dict[str, int]:
    if os.environ.get("MARKET_EAGLE_RUNTIME") == "production":
        raise RuntimeError("production cannot load synthetic fixture data")
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["fixture_version"] != 1 or manifest["fictional"] is not True:
        raise ValueError("expected the fictional synthetic-v1 fixture")
    catalog = read_csv(fixture_dir / "catalog.csv")
    sessions = read_csv(fixture_dir / "sessions.csv")
    bars = read_csv(fixture_dir / "bars.csv")
    if (
        len(catalog) != manifest["stock_count"]
        or len(sessions) != manifest["session_count"]
        or len(bars) != manifest["bar_count"]
    ):
        raise ValueError("fixture row counts differ from the manifest")
    publish_catalog(
        conn,
        catalog,
        source="synthetic-v1",
        taxonomy="synthetic-v1",
        exchange="SYNTHETIC",
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "INSERT INTO data_source (source, feed, rights_version, provider, synthetic) "
            "VALUES ('synthetic-v1', 'fictional', 'fixture-v1', 'fixture', true) "
            "ON CONFLICT (source, feed) DO NOTHING"
        )
        cur.executemany(
            "INSERT INTO trading_session (exchange, session_date, session_type) "
            "VALUES ('SYNTHETIC', %s, 'synthetic') ON CONFLICT DO NOTHING",
            [(row["session_date"],) for row in sessions],
        )
    inserted = 0
    rejected = 0
    for offset in range(0, len(bars), page_size):
        page = bars[offset : offset + page_size]
        result = ingest_page(
            conn,
            page,
            collection_run_id="synthetic-v1",
            endpoint="fixture/synthetic-v1/bars.csv",
            requested_symbols=[row["ticker"] for row in catalog],
            requested_start=date.fromisoformat(manifest["comparison_session"]),
            requested_end=date.fromisoformat(manifest["last_session"]),
            source=manifest["source"],
            feed=manifest["feed"],
            price_basis=manifest["price_basis"],
            exchange="SYNTHETIC",
        )
        inserted += result["inserted"]
        rejected += len(result["rejected"])
    if rejected:
        raise ValueError(f"fixture contained {rejected} rejected bars")
    return {
        "catalog_members": len(catalog),
        "sessions": len(sessions),
        "bars_inserted": inserted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-dir", type=Path, default=Path("fixtures/synthetic-v1")
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    with psycopg.connect(args.database_url) as conn:
        print(json.dumps(load_fixture(conn, args.fixture_dir)))


if __name__ == "__main__":
    main()
