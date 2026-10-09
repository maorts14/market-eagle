"""Apply versioned application migrations once, with checksum verification."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    directory = Path(__file__).resolve().parents[3] / "database" / "migrations"
    with psycopg.connect(args.database_url) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('market-eagle-schema'))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migration "
            "(version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for migration in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
            source = migration.read_text(encoding="utf-8")
            checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
            previous = conn.execute(
                "SELECT checksum FROM schema_migration WHERE version = %s",
                (migration.name,),
            ).fetchone()
            if previous is not None:
                if previous[0] != checksum:
                    raise RuntimeError(
                        "Applied migration checksum differs from the source file"
                    )
                continue
            conn.execute(source)
            conn.execute(
                "INSERT INTO schema_migration (version, checksum) VALUES (%s, %s)",
                (migration.name, checksum),
            )


if __name__ == "__main__":
    main()
