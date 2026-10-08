# Market data ingestion

Apply `database/migrations/001_market_data.sql` to the application PostgreSQL database, then load the committed fictional fixture:

```powershell
$env:PYTHONPATH = "backend"
$env:DATABASE_URL = "postgresql://user:password@localhost:5432/market_eagle"
python -m market_eagle.ingestion.migrate
python -m market_eagle.ingestion.fixture
```

The fixture loader is repeatable. Existing observations are matched by stable content keys; changed values append revisions. The `selected_daily_bar` view provides the current selected revision for one source/feed/basis. `catalog_current` points to one fully published snapshot.

`python -m market_eagle.ingestion.worker` starts Temporal workers for `market-backfill` and `market-session`. The adapter is limited to five symbols, 10,000 bars per page, a finite page count, and an explicitly configured feed and adjustment. It follows every Alpaca page token. Both queues share a conservative in-process request interval; run one provider worker process until a distributed limiter and account-specific budget are measured. Live collection requires `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, verified dated `security_symbol` rows with source `alpaca`, and a registered `data_source` row.

The worker also exposes a `market-catalog` queue. `CatalogPublishWorkflow` can publish the committed synthetic catalog transactionally; live catalog publication remains gated on a validated provider and a change-review policy.

The lead's 2026-10-08 read-only paper-account probe confirmed five-year raw SIP daily bars for five symbols (1,257 each, one page), a current-day historical `1Day` bar, and a `delayed_sip` snapshot `dailyBar`. `SessionRefreshWorkflow` uses the observed current-day historical `1Day` path with a 15-minute cutoff, marks its observations provisional, and reports returned count. It does not mix the `delayed_sip` snapshot feed into SIP history. Account rights for wider display or redistribution and the final scheduling/rate policy remain unresolved.

For Alpaca bars, `as_of_kind='fetched'` records when the response was observed; the bar's `t` is a session anchor, not a publication timestamp. Synthetic rows use `as_of_kind='provider'` from the fixture. The selected view also exposes `last_checked_at` when an identical fetched bar was seen again. A fetched timestamp must not be described as provider finality.

Temporal uses its own databases. Workflow history carries request IDs, bounded group counts and repair samples; page rows and credentials remain in the worker. Operational schedules and automatic targeted repair rounds are not wired yet; the explicit `PriceRepairWorkflow` supports bounded manual repairs. Wider provider usage rights and production rate budgets need confirmation before live scheduling.
