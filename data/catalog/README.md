# Provisional private-use constituent candidate

`public_sp500_2026-10-12.csv` is a dated, 503-share-line candidate for a first private Market Eagle catalog. It is **not** an official or certified S&P DJI feed. Membership and sectors remain provisional in the API and UI. The file does not publish itself: the operator must stage it, inspect the review report, resolve stock identities, and publish a checksum-bound approval.

## Source and independent check

- Source: [datasets/s-and-p-500-companies at commit `36472b5`](https://github.com/datasets/s-and-p-500-companies/blob/36472b57910842f4025e8ca8303b93a692d2bbae/data/constituents.csv), derived from Wikipedia. Retrieved October 12, 2026. Raw file SHA-256: `a8045f043ea7e68d4254a07470a5e95ca5759ded4656657eac514162e6e82e06`. The [upstream README](https://github.com/datasets/s-and-p-500-companies) states that its data is under ODC PDDL. Source names and GICS labels are reproduced as observations, not claimed as licensed index data.
- Compared symbols with [iShares IVV holdings for October 9, 2026](https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf/latest-holdings.csv). After normalizing spaces and dots in share-class symbols, all 503 candidate symbols occurred among 504 IVV equity holdings. IVV alone also showed `HOLX`.
- [S&P DJI's April 6, 2026 change notice](https://press.spglobal.com/2026-04-06-Caseys-General-Stores-Set-to-Join-S-P-500-DigitalOcean-Holdings-to-Join-S-P-MidCap-400-Broadstone-Net-Lease-to-Join-S-P-SmallCap-600) says `HOLX` was deleted effective April 9. We therefore did not add it based on the ETF position.
- Of the 503 shared symbols, sector names matched IVV holdings after treating IVV's `Communication` as the candidate's `Communication Services`. This comparison checks consistency; an ETF portfolio is not the index's official membership or sector license.

The candidate covers current membership only. It does not establish historical membership, historical ticker identity, or the Alpaca alias dates needed for a multi-year backfill.

## Stage and review

Set `PYTHONPATH=backend` and `DATABASE_URL` for the application DB, then apply migrations. Use the pinned source URL for provenance:

```powershell
python -m market_eagle.ingestion.migrate
python -m market_eagle.ingestion.public_catalog probe --file data/catalog/public_sp500_2026-10-12.csv --observed-on 2026-10-12 --source-url https://github.com/datasets/s-and-p-500-companies/blob/36472b57910842f4025e8ca8303b93a692d2bbae/data/constituents.csv
python -m market_eagle.ingestion.public_catalog stage --file data/catalog/public_sp500_2026-10-12.csv --observed-on 2026-10-12 --source-url https://github.com/datasets/s-and-p-500-companies/blob/36472b57910842f4025e8ca8303b93a692d2bbae/data/constituents.csv
python -m market_eagle.ingestion.public_catalog review STAGE_ID
python -m market_eagle.ingestion.public_catalog draft STAGE_ID --output C:/private/public-catalog-approval.json
python -m market_eagle.ingestion.public_catalog publish C:/private/public-catalog-approval.json
```

The draft leaves reviewer, note, and unresolved stock ID decisions blank. The reviewer must choose an existing stock ID or `"new"` for each unresolved share line and document the dated cross-check in the note. Keep approval files outside Git. Later catalog changes require another snapshot and explicit review; the app must continue to show this catalog as provisional until an authoritative feed and use rights replace it.
