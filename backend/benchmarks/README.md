# Disposable analytics load check

`full_universe.py` measures the current PostgreSQL repository plus explorer calculation over generated daily bars. It creates a unique `me_bench_*` schema in the database named by `BENCHMARK_DATABASE_URL`, then drops that schema on exit. Use a disposable PostgreSQL database with an owner role that can create schemas and apply the application migrations. It does not use or alter a published Market Eagle catalog in another schema.

Run a small smoke check first:

```powershell
$env:BENCHMARK_DATABASE_URL = '<disposable PostgreSQL connection URL>'
python backend/benchmarks/full_universe.py --stocks 5 --start 2025-12-01 --end 2025-12-31 --repeats 3
```

For the planned current-member/five-year envelope, run on the homelab with the same PostgreSQL placement and service load intended for deployment:

```powershell
python backend/benchmarks/full_universe.py --stocks 500 --start 2021-10-01 --end 2026-09-30 --repeats 10
```

The report gives seed time, selected bar count, individual query times, p50/p95, and a Python allocation peak. That peak excludes psycopg/native allocations and PostgreSQL memory. Record process RSS, PostgreSQL CPU/IO, swap, and concurrent worker load separately. These generated weekdays are **not** an exchange calendar or factual market data. A passing small run establishes that the measurement path works; it does not prove full-universe capacity. Compare the full run to an accepted operating target and document the result under [issue #21](https://github.com/maorts14/market-eagle/issues/21).
