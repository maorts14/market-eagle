"""Apply the initial application market-data schema to an empty PostgreSQL database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    migration = Path(__file__).resolve().parents[3] / "database" / "migrations" / "001_market_data.sql"
    with psycopg.connect(args.database_url) as conn:
        with conn.transaction():
            conn.execute(migration.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
