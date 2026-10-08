# Data model and storage ownership

Status: **proposed logical model**, not final SQL DDL. Provider behavior, price basis, listing history, and provisional-day policy can change fields or constraints. The first market-data system of record and query engine is application PostgreSQL; Temporal owns separate default and visibility databases.

## How to read the model

- **Stock identity is stable.** A ticker is an alias valid for dates and exchanges, not the primary key for a stock.
- **A published catalog snapshot is the query universe.** It contains current S&P 500 member stock IDs and one current sector per member. A request pins one snapshot. The snapshot can change between requests; old price windows still use the sector in the snapshot pinned for that request.
- **A daily bar is an observation.** A provider may correct it, so accepted versions are revisions. One selected current validated revision per stock/session/source/feed/basis is what a new query reads.
- **A ranking is calculated.** It is derived from selected observations, not stored for every date window. Exact replay of an old answer after corrections is deferred.

## Catalog in application PostgreSQL

| Entity | Proposed key and fields | Meaning and relationships |
| --- | --- | --- |
| security | stock ID (UUID), company/name, share-class identity | One listed share line; a company with two tracked share classes has two stock IDs. |
| security_symbol | stock ID, ticker, exchange, valid-from/to, source | Maps a provider ticker **at a trading date** to a stock ID. Historical aliases remain after a rename. Overlapping active ticker/exchange claims are held for review. |
| universe_snapshot | snapshot ID, source, captured-at, published-at, source checksum, validation state | Immutable catalog publication. “Latest published” is a pointer to one snapshot, changed only after validation. |
| universe_member | snapshot ID + stock ID, source ticker, **sector code in this snapshot** | The exact tracked membership and current sector that one request uses. This makes first-release current-sector grouping reproducible within a request. |
| sector | taxonomy/version + sector code, display name | Defines what a sector code means for the source/taxonomy used. |
| sector_assignment | stock ID, sector code, effective-from/to, source snapshot | Retains observed classification changes. Historical sector reconstruction is deferred; the first query joins universe_member instead. |
| listing_period | stock ID, exchange, valid-from/to, source | Proposed evidence that a stock was actually listed/tradable; needed to distinguish pre-listing dates from missing provider bars. Source feasibility is open. |
| trading_session | exchange + session date, open/close UTC, session type | Calendar for valid dates, half days, schedule timing, and comparison-close resolution. |

Publication is transactional: write all validated member-sector rows, then change the “latest published” pointer. An incomplete or held catalog cannot be queried as current. The catalog provider and change-review thresholds remain open.

## Market observations in application PostgreSQL

| Entity | Proposed key and fields | Meaning and relationships |
| --- | --- | --- |
| data_source | source ID, provider, market-data feed, rights/configuration version | Identifies the actual source used, such as delayed SIP versus IEX. Rankings must not silently combine feeds. |
| ingest_batch | batch ID, collection run ID, source ID, endpoint, requested symbols/dates, provider adjustment setting, fetched-at, provider-as-of, parser version, row counts | Provenance of one bounded request/page or batch. No credentials, authorization headers, or full response body. |
| daily_bar_revision | revision ID; stock ID, session date, source ID, price basis, open/high/low/close/volume, optional provider VWAP/traded notional, provider-as-of, fetched-at, ingest batch ID, validation and provisional/final status | A normalized accepted observation or corrected version. Session, price ordering, and volume constraints apply. Optional source values support the current dollar-volume rule; provider availability remains to be verified. The basis records the provider's adjustment setting; its use for returns is unresolved. |
| daily_bar_current | stock ID + session + source/feed + basis, selected revision ID | New finalized-history queries read the selected validated revision. Selection changes only after a revision and its provenance commit. How to select the latest accepted provisional value is still open; queries covering today must include an available provisional value. |

The price provider returns ticker/date/OHLCV values. Ingestion maps ticker/date → stock ID using security_symbol, checks trading_session and value rules, records an ingest_batch and daily_bar_revision, and advances daily_bar_current after validation. The full provider response is not archived. Repeated ingestion of the same provider observation needs an idempotency key so a Temporal retry does not create duplicate revisions.

Here, **validated** means the ingestion checks accepted that individual bar: its ticker and date map to a tracked stock and trading session, its price and volume values pass the defined consistency rules, and its source/feed and price basis are recorded. Validation does not prove the provider's price is correct or that every expected stock/date has been collected; the displayed coverage counts show that separately. Usually the first accepted price is the one calculations use. If the provider later corrects that same stock's price for that date, we keep the old record for traceability and use the corrected one in new calculations.

There is no separate saved gap table. Temporal records run and retry status. After all pages of a bounded backfill or post-close finalization request group are fetched and accepted prices committed, an ingestion worker queries application PostgreSQL for requested stock/trading-session pairs without a stored bar for the configured source/feed/basis. It excludes dates before a stock was listed only if reliable listing dates are available. Missing pairs can trigger targeted stock/date repairs; the query can be rerun instead of persisting its result. Hourly provisional refresh has a separate, still-open completeness policy.

The current-day cumulative bar is **provisional** while the provider still updates it, including possible after-hours volume changes to the same dated bar. A query whose requested range includes today uses an available provisional value and shows its status and provider as-of time. Whether that value is persisted or fetched on demand, how the latest accepted value is selected, and when the provider can be considered final remain open. If persisted, use separate provisional selection or explicit status filtering so a changing value cannot silently replace finalized history for other requests.

## Research data in application PostgreSQL

| Entity | Proposed key and fields | Meaning and relationships |
| --- | --- | --- |
| analysis_request | request ID, actor, requested/resolved dates, pinned snapshot ID, metric version, source/feed/basis, filters, created-at | Optional record of a calculation request and its inputs. The explorer need not persist every request. |
| analysis_result | request ID, computed-at, evidence/coverage, expiry | Optional short-lived cache or saved output. Arbitrary windows remain calculated on demand. This is not guaranteed exact replay after provider corrections. |
| agent_conversation | conversation ID, created/updated times, title/state, active turn ID | One conversation with its own linear turn context. Atomically reserve/release its active turn so no second message is accepted until that turn is terminal. Before authentication, all app visitors can list/read and explicitly delete conversations; later each belongs to an authenticated user. Deletion permanently removes its turns and conversation-specific saved answers/evidence, but not shared market observations. |
| agent_turn | turn ID, conversation ID, client request ID, question, validated plan, answer, evidence references, model/cost metadata, Temporal workflow ID/status | One turn within a conversation. Client request ID makes a repeated submission idempotent. The Temporal workflow continues after browser disconnection and can be explicitly cancelled. The full visible conversation and turns remain until explicit deletion. |
| agent_context_summary | conversation ID, through turn ID, summary version, text, created-at | Derived cache for model context; original turns remain authoritative and retrievable. Replace or regenerate when old turns or summarization policy change. Never shared across conversations. |

The analytical service reads through a read-only role. It pins one published snapshot and one source/feed/basis, resolves the two comparison sessions, reads endpoint closes in a set query, then calculates breadth and equal-weight returns. It does not issue a separate database query per stock. The agent has only bounded analytical tools, never application-DB credentials or an unchecked SQL path.

## Query identity and evidence

Each analytical result retains the following evidence so the agent can display what is relevant to its answer:

1. Requested dates and resolved first/final trading sessions, including the previous comparison session.
2. Pinned current catalog snapshot ID and its as-of/published time.
3. Price source, feed, price basis, and market-data as-of time.
4. Eligible and tracked counts per sector and for the whole tracked universe; excluded missing-endpoint counts.
5. Metric version and calculation time.

The accepted metric rules are in [analysis-scope.md](analysis-scope.md). Exact per-answer revision pinning after provider corrections is deferred by user decision; a newly run query uses then-current validated revisions.

## Storage and operational boundary

Application, Temporal default, and Temporal visibility may share one PostgreSQL server but use separate databases/credentials. Temporal tables are not a market-data store. Active data is proposed for NVMe on the first homelab host. The first private deployment has no backup process. A later backup design must cover application and Temporal data and verify restoration.
