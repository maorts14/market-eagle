# System architecture blueprint

Status: **definition baseline**, with accepted choices and still-proposed mechanisms marked in the text. The retired reference prototype remains in earlier Git history. The [editable architecture workbook](diagrams/market-eagle-architecture.drawio) shows the same boundaries and flows.

## Read the system in two paths

**Data path:** catalog source and price provider → ingestion activities → application PostgreSQL → analytical query service → application API → research workspace. Market data moves along this path. The first explorer uses the analytical service directly; a later agent calls the same service through bounded tools.

**Control path:** Temporal schedules and workflows → ingestion worker activities. Temporal starts work, waits, retries, and records execution status. It does not sit between the provider and market-data tables, transform bars itself, or hold the canonical stock history. Its own PostgreSQL databases contain workflow history and visibility data.

| Boundary | Responsibility | Data crossing it |
| --- | --- | --- |
| Catalog source → catalog ingestion | For the first private version, import a dated public constituent list, cross-check ETF holdings and official change notices, and manually review it. | Dated source rows: ticker, company name, sector, source/review metadata, provisional label. |
| Price provider → bar ingestion | Obtain five years of provider daily OHLCV and refresh the current cumulative day bar, including after-close updates to the same bar where available. Alpaca Basic is a candidate, not selected. | Requested symbols/dates/feed/adjustment; returned bar pages and provider timestamps. |
| Ingestion → application PostgreSQL | Resolve provider ticker and trading date to a stable stock ID; validate values; save normalized observations and provenance. | Catalog snapshots, daily bar revisions, and selected current bars. Full response bodies are not retained. |
| Application PostgreSQL → analytical service | Read one pinned current catalog snapshot and a consistent selection of validated bars for the requested source and price basis. | Member/sector rows, two comparison closes per eligible stock, coverage and freshness metadata. |
| Analytical service → API → workspace | Calculate and present sector breadth, sector/market returns, stock excess returns, and evidence. | Typed request and response; no generated SQL exposed to the client. |
| Later agent → analytical service | Interpret a question as a bounded typed analytical plan and call read-only tools. | Validated plan and evidence-backed result, not database credentials. |

The analytical service is a **logical boundary**. It may share the API process initially. Ingestion and later agent workers are separate processes because their workloads and permissions differ. React/TypeScript is the proposed workspace; FastAPI/Pydantic are the proposed API and contract stack. PydanticAI is only an agent candidate.

## Logical order of work

1. **Build the catalog.** Fetch a dated constituent/sector source, resolve each ticker to a stable stock identity, validate membership and sector changes, then publish an immutable snapshot. Only a published snapshot is used in research. The first release uses the latest published snapshot at query time, including its **current sector for historical price windows**.
2. **Backfill prices.** Pin the catalog snapshot, plan bounded symbol/date requests covering five years **plus the prior comparison close**, fetch all provider pages, resolve each returned ticker/date to a stock ID, validate OHLCV and the provider's feed/adjustment setting, then write provenance and normalized revisions. A SQL completeness query compares expected trading sessions against stored bars and returns omitted pairs to Temporal for retry. No separate gap table is saved.
3. **Refresh the current day.** During regular US trading hours, request one cumulative current-day bar about hourly, and continue checking it after close while the provider still updates that day's candle. Retain its provider as-of time. An available provisional bar participates in calculations and rankings for a requested range containing today, with provisional status shown. Persistence, after-hours availability/cadence, and query-selection mechanics remain open pending provider verification.
4. **Reconcile and repair.** On the following New York calendar day, refetch the prior trading session and select its latest accepted revision; periodically recheck recent sessions for later corrections. The product does not claim an exact provider-final time. A workflow finishing does not imply complete data; a completeness query checks the stored prices.
5. **Answer an explorer request.** Validate dates, pin the current catalog snapshot and a single source/feed/price basis, resolve the first included trading session and final session, read the close immediately before the first session and the final close, exclude stocks missing either close, calculate the agreed metrics, then return counts, resolved dates, source, basis, and data/catalog as-of times.
6. **Answer a later free-text request.** The agent proposes a typed plan; application validation checks scope and limits; the same analytical service calculates the answer. The model may explain evidence but cannot run arbitrary SQL or access database credentials.

The workflow topology is shown on page 7 of the [editable architecture workbook](diagrams/market-eagle-architecture.drawio): one historical backfill workflow controls five-stock/five-year activities and narrower repairs, without a workflow for each stock. Activity retry behavior is detailed in [workflows.md](workflows.md). Table relationships and write/read paths are in [data-model.md](data-model.md). Metric definitions are in [analysis-scope.md](analysis-scope.md).

## Data ownership and placement

| Store | Owns | Does not own |
| --- | --- | --- |
| Application PostgreSQL | Stable stock identity and ticker history, published current-universe snapshots with sector per member, trading calendar, source/request metadata, normalized daily bar revisions and current selection, and research records | Temporal history, saved gap records, or full raw API responses |
| Temporal persistence (separate default and visibility databases) | Workflow histories, timers, retries, schedules, and status search | Canonical market bars, catalog, or analytical results |

The accepted first analytical store and SQL engine is PostgreSQL. The estimated five-year daily-bar volume is roughly 630,000 base rows for about 500 stocks before revisions; actual query and write latency must be measured. Application and Temporal databases may share one PostgreSQL server on the homelab while retaining separate credentials and schemas. An Iceberg/Trino/Spark path is deferred until measured needs justify it. See [storage-rationale.md](storage-rationale.md).

## First host and later gates

The first backend runs privately on the creator's homelab through Tailscale. Docker Compose is a recommendation, while local Kubernetes remains an open choice. Active PostgreSQL data belongs on NVMe in the current proposal. **No backup process is planned for the first private deployment.** Backup and restore are a later gate before dependence on retained research or trader access. Public access also requires identity, authorization, HTTPS ingress, rate limits, licensed data rights, and an operational plan. See [operations-and-load.md](operations-and-load.md).

## Unresolved contracts that affect implementation

- Authenticated behavior and rights of the price provider, plus source terms and accuracy limits for the private public-list catalog.
- Price adjustment basis and corporate-action return semantics. A ranking must never silently mix bases or feeds.
- Persistence and query-selection mechanics for provisional current-day bars, plus freshness/fallback thresholds. Inclusion for a range containing today is settled.
- Catalog change review policy and the source of valid listing dates for coverage reconciliation.
- Agent planning/tool limits, deployment runtime, and public rollout controls.

These are marked as open in [decision-tree.md](decision-tree.md). The diagrams describe the proposed boundaries without presenting these choices as settled.
