# Private five-stock Alpaca validation

This path checks real SIP daily-bar ingestion before an FMP S&P 500 catalog is available. The five stocks form an operator-selected **private sample**, not an S&P 500 constituent list. It creates a published snapshot with source `alpaca-sample-v1` and taxonomy `sample-unclassified-v1`; it does not change `catalog_current`. Stock IDs are derived from Alpaca asset UUIDs, so repeat stages keep the same IDs. Price observations remain labeled `alpaca/sip/raw`, with collection time recorded as a fetched observation. The registered rights version says paper-account rights are unconfirmed. Keep the database and output private.

Use an application database intended for this validation, with the repository migrations applied. Set `DATABASE_URL`, `ALPACA_API_KEY_ID`, and `ALPACA_API_SECRET_KEY` in the local process environment. Do not put credentials or approval files in the repository. The example dates cover two years ending on the prior completed session; adjust them for the day you run it.

```powershell
$env:PYTHONPATH = "backend"
python -m market_eagle.ingestion.migrate
python -m market_eagle.ingestion.alpaca_sample_cli stage --symbols AAPL AMZN JPM MSFT NVDA --start 2024-10-09 --end 2026-10-08
python -m market_eagle.ingestion.alpaca_sample_cli review STAGE_ID
python -m market_eagle.ingestion.alpaca_sample_cli probe --symbols AAPL AMZN JPM MSFT NVDA --start 2024-10-09 --end 2026-10-08 --bars --asof STAGE_FETCHED_UTC_DATE
python -m market_eagle.ingestion.alpaca_sample_cli draft STAGE_ID --output C:/private/alpaca-sample-approval.json
```

`probe` reads the bounded active US-equity asset list and trading calendar. `--bars` also reads at most three historical pages for the five symbols, from the preceding comparison session through the requested end. Supply `--asof` with the UTC date of the held stage's `fetched_at`, which will be the collection request's pinned `symbol_asof`; without it, the probe uses today's UTC date. It reports the exact missing, unexpected, or duplicate bar dates against the calendar without printing prices. Require `complete: true` and retain the dated probe result privately. Historical requests use an exact exclusive UTC cutoff after the requested end date; a date-only cutoff can enter Alpaca's recent SIP entitlement window and return HTTP 403. `stage` holds the five current asset identities and the calendar; it neither publishes a catalog nor writes prices.

Review the staged checksum, five asset UUIDs, names, exchanges, separate share lines, date range, and session count. For each stock, use dated issuer or exchange records before the comparison session, within the window, and near its end to establish the common share class, ticker, and venue. Check for known symbol, listing, or share-class changes during the window; resolve any change before approval. Compare these records with the current staged Alpaca asset and the complete, pinned historical bar-date probe. Put specific sources, dates, and findings in each alias's `evidence`, and keep a dated private review memo. The draft leaves reviewer, review note, residual identity assumption, alias start dates, and evidence blank.

Set `verified_from` to the comparison session only when that whole interval has been reviewed under this standard. It marks the start of the approved collection alias span, **not** the security's listing inception or the creation date of its Alpaca UUID. Current Alpaca assets do not provide historical UUID ownership; historical bars can be relabeled by Alpaca's `asof` symbol mapping. Record the remaining assumption explicitly: the current Alpaca UUID represents the same common share line across the reviewed interval. Do not approve if issuer or exchange evidence conflicts, bar dates are incomplete, or a known identity change remains unresolved. This standard supports private ingestion validation; it does not certify historical UUID continuity or S&P 500 membership.

After review, the approval file has the following shape, with **five** alias entries:

```json
{
  "stage_id": "STAGE_ID",
  "checksum": "CHECKSUM_FROM_REVIEW",
  "reviewer": "name",
  "review_note": "dated issuer records and complete pinned bar-date probe checked; private validation only",
  "identity_assumption": "Current Alpaca asset UUID represents the same common share line throughout the reviewed interval; historical UUID ownership is not independently attested.",
  "aliases": [{
    "stock_id": "sample:alpaca:ASSET_UUID",
    "asset_id": "ASSET_UUID",
    "symbol": "AAPL",
    "exchange": "NASDAQ",
    "verified_from": "2024-10-08",
    "verified_to": null,
    "evidence": "dated issuer or exchange sources before, within, and near end of window; class, ticker, venue, no unresolved change; pinned bar-date probe"
  }]
}
```

The named reviewer completes the evidence and assumption after inspecting the private memo and probe. `approve` checks the stage checksum and all five identities and dated aliases, then atomically publishes the isolated sample snapshot, approved symbol history, `US_EQUITY` sessions from Alpaca's calendar, and a pinned collection preparation. The assumption is stored with the reviewed stage and preparation. A failed review leaves no partial catalog. `request` prints the resulting workflow input. `collect` synchronously uses the existing bounded five-symbol Alpaca worker and then reports coverage; it is an explicit private database write.

```powershell
python -m market_eagle.ingestion.alpaca_sample_cli approve C:/private/alpaca-sample-approval.json
python -m market_eagle.ingestion.alpaca_sample_cli request STAGE_ID
python -m market_eagle.ingestion.alpaca_sample_cli collect STAGE_ID
```

Treat a collection as validated only when `rejected` and coverage `missing` are both zero. The two-year calendar and provider bars may include a still-open session if the end date is today, so choose a completed end date. The sample is for private end-to-end testing; do not present its membership as the S&P 500 or display or redistribute live prices until account rights are confirmed.
