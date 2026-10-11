# Market data ingestion

Apply the repository migrations to the application PostgreSQL database, then load the committed fictional fixture:

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

Set `FMP_API_KEY` from an FMP account and `DATABASE_URL` for the application database. Do not commit the key or approval file. Apply the migration runner first; it applies each numbered migration exactly once with checksum checks.

```powershell
$env:PYTHONPATH = "backend"
python -m market_eagle.ingestion.migrate
python -m market_eagle.ingestion.fmp_catalog probe
python -m market_eagle.ingestion.fmp_catalog stage
python -m market_eagle.ingestion.fmp_catalog review STAGE_ID
python -m market_eagle.ingestion.fmp_catalog draft STAGE_ID --output C:/private/fmp-approval.json
python -m market_eagle.ingestion.fmp_catalog publish path/to/approval.json
```

`probe` makes one 20-second request, caps the response at 2 MB and 700 rows, and prints only counts, checksum, fetch time, and rate headers. `stage` stores normalized rows in a held candidate. A response below 450 rows can be inspected but cannot be published. Duplicate symbols, missing sectors, and malformed response shapes fail before staging. The Temporal catalog activity accepts `{"source": "fmp-sp500"}` and returns a held stage ID; it never publishes FMP membership.

Inspect `review` for additions, removals, sector changes, and unresolved symbols. `draft` reads the held stage and writes a checksum-bound approval file outside the repository; it makes no provider request or database change. Reviewer and review note are blank, and every unresolved symbol has a blank decision. FMP aliases are reused only when an exact dated FMP mapping already exists. The endpoint does not provide exchange identity, so approved aliases use `UNVERIFIED` until a separate mapping is checked. For each unresolved symbol, a reviewer must choose an existing `stock_id` or the literal `"new"`. Even two symbols with one CIK require separate stock IDs. Publication requires a checksum-bound approval file:

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

## Prepare a live Alpaca collection universe

For a private five-stock, two-year validation before FMP catalog access, follow the [sample operator runbook](ALPACA_SAMPLE_RUNBOOK.md). Its `alpaca-sample-v1` snapshot is explicitly separate from S&P membership and does not replace the current catalog.

FMP's `UNVERIFIED` exchange aliases are insufficient for price collection. Alpaca's [asset list](https://docs.alpaca.markets/us/reference/get-v2-assets-1) supplies current asset IDs, symbols, exchange, class, and status; its [trading calendar](https://docs.alpaca.markets/us/reference/legacycalendar) supplies session dates and regular open/close times. Neither proves a ticker's five-year history or that an FMP share line matches an Alpaca asset. The operator must review those claims using dated evidence before a collection plan is usable.

For a published FMP snapshot, use the paper credentials in local environment variables and choose the full requested window. The preparation fetches the preceding trading session too, to supply the comparison close. `probe` and `stage` make one bounded asset request and one bounded calendar request. They do not change current membership or start collection.

```powershell
python -m market_eagle.ingestion.alpaca_collect probe --start 2021-01-01 --end 2025-12-31
python -m market_eagle.ingestion.alpaca_collect stage --snapshot-id FMP_SNAPSHOT_ID --start 2021-01-01 --end 2025-12-31
python -m market_eagle.ingestion.alpaca_collect review PREPARATION_ID
python -m market_eagle.ingestion.alpaca_collect draft PREPARATION_ID --output C:/private/alpaca-approval.json
```

The draft suggests exact symbol matches only. It leaves `verified_from` and `evidence` blank. Review every FMP stock ID against the Alpaca asset ID and exchange, including separate share classes; fill one approval entry per stock. Each approved alias must cover the comparison session through the requested end date. A ticker difference needs a written reason. Current asset metadata cannot certify historical alias coverage; stocks with unresolved renames or uncertain share-line identity must remain held until that evidence is available. An approval file has this shape:

```json
{
  "preparation_id": "PREPARATION_ID",
  "checksum": "CHECKSUM_FROM_REVIEW",
  "reviewer": "reviewer name",
  "review_note": "Reviewed the asset list, share lines, alias dates, and market calendar",
  "aliases": [{
    "stock_id": "STABLE_STOCK_ID",
    "asset_id": "ALPACA_ASSET_UUID",
    "symbol": "PROVIDER_SYMBOL",
    "exchange": "NYSE",
    "verified_from": "2020-12-31",
    "verified_to": null,
    "evidence": "dated source or checked provider history for this share line"
  }]
}
```

`approve` rejects partial membership, duplicate assets or symbols, OTC/unknown exchanges, aliases that do not span the window, and a catalog that changed after staging. It atomically registers reviewed Alpaca aliases, `US_EQUITY` sessions and their source, and the `alpaca/sip` data source with rights explicitly unconfirmed. It returns a pinned workflow request. `request` reprints that request later; it does not start Temporal.

```powershell
python -m market_eagle.ingestion.alpaca_collect approve C:/private/alpaca-approval.json
python -m market_eagle.ingestion.alpaca_collect request PREPARATION_ID
```

The worker requires the approved preparation ID and checks every five-stock group before contacting Alpaca. Stock aliases keep their reviewed NYSE/NASDAQ/etc. exchange; daily bars use the separate `US_EQUITY` trading calendar. A comparison close or session missing from the approved calendar prevents preparation. This is a private collection path, not clearance for redistributed prices or a trusted live return basis.

The lead's 2026-10-08 read-only paper-account probe confirmed five-year raw SIP daily bars for five symbols (1,257 each, one page), a current-day historical `1Day` bar, and a `delayed_sip` snapshot `dailyBar`. `SessionRefreshWorkflow` uses the observed current-day historical `1Day` path with a 15-minute cutoff, marks its observations provisional, and reports returned count. It does not mix the `delayed_sip` snapshot feed into SIP history. Account rights for wider display or redistribution and the final scheduling/rate policy remain unresolved.

For Alpaca bars, `as_of_kind='fetched'` records when the response was observed; the bar's `t` is a session anchor, not a publication timestamp. Synthetic rows use `as_of_kind='provider'` from the fixture. The selected view also exposes `last_checked_at` when an identical fetched bar was seen again. A fetched timestamp must not be described as provider finality.

Temporal uses its own databases. Workflow history carries request IDs, bounded group counts and repair samples; page rows and credentials remain in the worker. Operational schedules and automatic targeted repair rounds are not wired yet; the explicit `PriceRepairWorkflow` supports bounded manual repairs. Wider provider usage rights and production rate budgets need confirmation before live scheduling.
