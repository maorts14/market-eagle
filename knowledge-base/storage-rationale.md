# Market-data storage decision: PostgreSQL versus Iceberg

Status: **decision accepted for the first system**. PostgreSQL stores market data and executes analytical SQL. Iceberg is a later growth option if measurements justify it.

## Workload to design for

The first retained dataset is about 630,000 five-year daily OHLCV rows for current S&P 500 members, plus revisions. During a session the changing whole-day bar is refreshed hourly for roughly 500 securities. The first explorer resolves two endpoint closes for each eligible security, joins sector membership, and aggregates breadth/returns. Later agent questions may introduce broad scans, correlations, and indicators, so the analytical boundary must be able to change engines.

| Question | PostgreSQL | S3-compatible storage + Iceberg + engine |
| --- | --- | --- |
| What performs SQL? | PostgreSQL itself. | Iceberg is a table format, so an engine such as Trino, Spark, or another compatible engine executes SQL. A catalog and object store are also needed. |
| Frequent small corrections/current-day updates | Unique-key upserts and indexed reads are direct. | Supported, but repeated small commits/updates require file and metadata maintenance; batch publication is a better fit. |
| Flexible scans and many datasets | Works at current size; scaling limit must be measured. | Strong fit when data becomes much larger, columnar scans dominate, or several engines share the same datasets. |
| Result consistency | Pin one catalog snapshot and select validated bar revisions within a request. Exact replay of an older answer after corrections is deferred. | Native table snapshots and time travel, with a retention policy. |
| Homelab operations | One data server already needed for catalog/application state and Temporal persistence. | Adds object storage, a catalog, a query engine, compaction/expiration jobs, and their monitoring. PostgreSQL may still be needed for application and Temporal state. |

Iceberg's snapshots are a real advantage for reproducible research, and its table format supports multiple engines. Its maintenance documentation describes compaction of small files. Trino's Iceberg connector requires a catalog and supported filesystem/object storage. [Iceberg specification](https://iceberg.apache.org/spec/), [Iceberg maintenance](https://iceberg.apache.org/docs/latest/maintenance/), [Trino Iceberg connector](https://trino.io/docs/current/connector/iceberg.html).

**Accepted path:** start with PostgreSQL for the canonical daily bar table and catalog, while preserving a typed analytical request contract and provider-neutral normalized schema. Measure the actual two-close sector query, a whole-universe history scan, and the first correlation query on the homelab. If scans/concurrency materially outgrow PostgreSQL, evaluate publishing batched Parquet/Iceberg data for a separate analytical engine while retaining PostgreSQL for application state. No dual storage is planned now.

## What “raw archive” means

One archive object would contain the **exact response body** received from a market-data or constituent API for a specific request/page. A small manifest records provider, endpoint, requested symbol/date range, fetch time, response checksum, parser version, and object location. Credentials and authorization headers are never archived. This is different from the normalized `daily_bar` rows that serve queries.

Example: an Alpaca multi-symbol page is fetched; the response bytes are optionally saved; ingestion parses bars into security/date/OHLCV rows; the manifest links those rows to that fetch. If parsing or symbol mapping later proves wrong, we can replay the saved response through a corrected parser. It also helps explain a provider correction or investigate a gap. Alpaca's historical bar API has adjustment and symbol-mapping parameters, which are important to record whether or not response bodies are retained. [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars).

**Accepted decision:** omit full raw response retention from the first system. Keep source/feed, request parameters, adjustment basis, provider/fetch timestamps, parser version, and revision history of accepted bars. A provider refetch may be enough for development; it cannot always reconstruct exactly what the provider returned at an earlier time. If exact replay later becomes valuable, reconsider archive retention then. An archive would not be a backup or analytical query engine.
