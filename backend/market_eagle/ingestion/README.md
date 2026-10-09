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

## FMP constituent staging and review

The [FMP current constituent endpoint](https://site.financialmodelingprep.com/developer/docs/stable/sp-500) supplies source symbols, names, sectors, sub-sectors, CIKs, and index-addition dates. It does not supply an exchange or a provider publication time. The FMP sector taxonomy is recorded as `fmp-sector-unverified-v1`, never as official GICS. `dateFirstAdded` is index membership evidence, not a listing date. CIK is company-level review evidence and does not merge distinct share lines into one stock ID.

Set `FMP_API_KEY` from an FMP account and `DATABASE_URL` for the application database. Do not commit the key or approval file. Apply the migration runner first; it applies both `001` and `002` exactly once with checksum checks.

```powershell
$env:PYTHONPATH = "backend"
python -m market_eagle.ingestion.migrate
python -m market_eagle.ingestion.fmp_catalog probe
python -m market_eagle.ingestion.fmp_catalog stage
python -m market_eagle.ingestion.fmp_catalog review STAGE_ID
python -m market_eagle.ingestion.fmp_catalog publish path/to/approval.json
```

`probe` makes one 20-second request, caps the response at 2 MB and 700 rows, and prints only counts, checksum, fetch time, and rate headers. `stage` stores normalized rows in a held candidate. A response below 450 rows can be inspected but cannot be published. Duplicate symbols, missing sectors, and malformed response shapes fail before staging. The Temporal catalog activity accepts `{"source": "fmp-sp500"}` and returns a held stage ID; it never publishes FMP membership.

Inspect `review` for additions, removals, sector changes, and unresolved symbols. FMP aliases are reused only when an exact dated FMP mapping already exists. The endpoint does not provide exchange identity, so approved aliases use `UNVERIFIED` until a separate mapping is checked. For each unresolved symbol, a reviewer must choose an existing `stock_id` or the literal `"new"`. Even two symbols with one CIK require separate stock IDs. Publication requires a checksum-bound approval file:

```json
{
  "stage_id": "STAGE_ID",
  "checksum": "CHECKSUM_FROM_REVIEW",
  "reviewer": "reviewer name",
  "review_note": "Membership, share lines, sectors, and changes checked against a dated independent source",
  "decisions": {"UNRESOLVED_SYMBOL": "new"}
}
```

The explicit `publish` command writes securities, dated FMP aliases, source-labeled sectors, an immutable snapshot, and the current pointer in one transaction. If validation or identity resolution fails, the previous catalog remains current. FMP Basic endpoint entitlement, complete share-line coverage, independent membership comparison, and display or redistribution rights still require an authenticated account probe and human review. [FMP pricing and licensing](https://site.financialmodelingprep.com/developer/docs/pricing) does not clear those rights through an API response alone.

The lead's 2026-10-08 read-only paper-account probe confirmed five-year raw SIP daily bars for five symbols (1,257 each, one page), a current-day historical `1Day` bar, and a `delayed_sip` snapshot `dailyBar`. `SessionRefreshWorkflow` uses the observed current-day historical `1Day` path with a 15-minute cutoff, marks its observations provisional, and reports returned count. It does not mix the `delayed_sip` snapshot feed into SIP history. Account rights for wider display or redistribution and the final scheduling/rate policy remain unresolved.

For Alpaca bars, `as_of_kind='fetched'` records when the response was observed; the bar's `t` is a session anchor, not a publication timestamp. Synthetic rows use `as_of_kind='provider'` from the fixture. The selected view also exposes `last_checked_at` when an identical fetched bar was seen again. A fetched timestamp must not be described as provider finality.

Temporal uses its own databases. Workflow history carries request IDs, bounded group counts and repair samples; page rows and credentials remain in the worker. Operational schedules and automatic targeted repair rounds are not wired yet; the explicit `PriceRepairWorkflow` supports bounded manual repairs. Wider provider usage rights and production rate budgets need confirmation before live scheduling.
