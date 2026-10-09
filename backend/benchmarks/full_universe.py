"""Measure a disposable PostgreSQL explorer query at a chosen universe size.

This is an operator benchmark, not part of CI and not a market-data fixture.
It creates a unique schema in BENCHMARK_DATABASE_URL and drops that schema on exit.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import tracemalloc
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from market_eagle.analytics.postgres_repository import PostgresAnalyticsRepository
from market_eagle.analytics.service import AnalyticsService

SEED = (
    BACKEND
    / "market_eagle"
    / "analytics"
    / "helpers"
    / "db"
    / "sql"
    / "benchmark_seed.sql"
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def run_benchmark(url: str, stocks: int, start: date, end: date, repeats: int) -> dict:
    if not 1 <= stocks <= 1000 or repeats < 1 or start > end:
        raise ValueError("invalid benchmark universe, repeat count, or date window")
    schema = f"me_bench_{uuid4().hex}"
    seed_started = time.perf_counter()
    with psycopg.connect(url, autocommit=True) as setup:
        setup.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            setup.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
            )
            for path in sorted(
                (ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql")
            ):
                setup.execute(path.read_text(encoding="utf-8"))
            for setting, value in (
                ("market_eagle.benchmark_stocks", str(stocks)),
                ("market_eagle.benchmark_start", start.isoformat()),
                ("market_eagle.benchmark_end", end.isoformat()),
            ):
                setup.execute("SELECT set_config(%s, %s, false)", (setting, value))
            setup.execute(SEED.read_text(encoding="utf-8"))
            seeded_bars = setup.execute(
                "SELECT count(*) FROM daily_bar_current"
            ).fetchone()[0]
            sessions = setup.execute(
                "SELECT count(*) FROM trading_session WHERE session_date BETWEEN %s AND %s",
                (start, end),
            ).fetchone()[0]
            seed_seconds = time.perf_counter() - seed_started

            scoped_url = make_conninfo(url, options=f"-c search_path={schema},public")
            service = AnalyticsService(
                PostgresAnalyticsRepository(
                    scoped_url,
                    source="benchmark",
                    feed="synthetic",
                    price_basis="raw",
                    exchange="BENCHMARK",
                )
            )
            timings = []
            for _ in range(repeats):
                started = time.perf_counter()
                result = service.explorer(start, end)
                timings.append(time.perf_counter() - started)
            if result["market"]["eligible_count"] != stocks:
                raise RuntimeError(
                    "benchmark did not evaluate the full generated universe"
                )
            tracemalloc.start()
            service.explorer(start, end)
            _, python_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            return {
                "stocks": stocks,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "sessions": sessions,
                "seeded_bars": seeded_bars,
                "seed_seconds": round(seed_seconds, 3),
                "query_seconds": [round(value, 3) for value in timings],
                "query_p50_seconds": round(percentile(timings, 0.5), 3),
                "query_p95_seconds": round(percentile(timings, 0.95), 3),
                "python_peak_mib_lower_bound": round(python_peak / 1024**2, 1),
                "memory_note": "tracemalloc excludes native allocations and PostgreSQL memory",
            }
        finally:
            setup.execute("SET search_path TO public")
            setup.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stocks", type=int, default=5)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    url = os.environ.get("BENCHMARK_DATABASE_URL")
    if not url:
        parser.error("BENCHMARK_DATABASE_URL is required; use a disposable database")
    print(
        json.dumps(
            run_benchmark(url, args.stocks, args.start, args.end, args.repeats),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
