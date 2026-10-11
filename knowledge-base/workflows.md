# System workflows and handoffs

Status: **one Temporal workflow with activities for the backfill is accepted**. The default historical activity requests **five stocks across the five-year window**, with narrower repair activities for specific failures. Concurrency, retry numbers, and provisional-day behavior still need an authenticated provider probe. The first explorer is a synchronous API/query path, not a Temporal workflow.

## Two meanings of “workflow”

A **business flow** is the ordered movement of data from a source to a usable answer. A **Temporal workflow** is the durable controller for long-running work. Temporal decides when to start, retry, pause, and finish an activity; ingestion workers perform network calls, parsing, validation, and application-database writes. Temporal stores small IDs and progress, not market bars or provider payload pages. External calls and database I/O run in activities so Temporal workflow replay remains deterministic. [Temporal workflow definition](https://docs.temporal.io/workflow-definition).

## Workflow topology for the first release

**Accepted: one Temporal workflow coordinates the historical backfill through activities, without a workflow per stock or child workflows initially.** Its default activity requests five tracked stocks over the five-year window, so about 500 stocks produce roughly 100 activities before repairs. The actual member count may be above 500 because an index can contain multiple share lines. The workflow awaits its activities and reports its outcome. [Temporal recommends starting with one bounded workflow and activities](https://docs.temporal.io/child-workflows); child workflows are useful if measured event-history growth later warrants partitioning.

| Workflow | Start and ID | Activities it coordinates | End condition |
| --- | --- | --- | --- |
| `CatalogPublishWorkflow` | Manual first run; later schedule undecided. ID includes catalog source and source date. | Fetch source, map identities, review change report, publish snapshot. | Published snapshot or held for review; never publish a partial catalog. |
| `HistoricalBackfillWorkflow` | Manual once per requested catalog snapshot/window/source/feed/basis. One active workflow for the same request. | Group stock IDs by five, run one fetch/validate/save activity per group for five years, check completeness, request narrower repairs when needed. | Every group checked, then complete or explicitly incomplete. |
| `SessionRefreshWorkflow` | One schedule tick during an open US session and bounded checks after close for updates to the same dated bar; ID includes session date and scheduled tick. | Fetch cumulative provisional bars, check freshness/returned-symbol count and after-hours volume revisions. | Freshness and provisional coverage reported; no historical completeness claim. |
| `SessionReconcileWorkflow` | One scheduled run on the following New York calendar day; ID includes session date/source/feed/basis. | Refetch the prior session's daily bars, write revisions, query completeness, repair omissions; later lookback runs catch corrections. | Latest accepted observations selected or incompleteness reported; no claim that the provider can never revise a bar. |
| `PriceRepairWorkflow` | Manual or targeted later run for an explicit stock/date range; ID includes repair request ID. | Reuse the same fetch/validate/save and completeness activities. | Repaired or incomplete; no duplicate records on retry. |

The first workflow definitions share the same ingestion activities, not separate copies of market-data logic. Workflow IDs prevent accidental overlapping executions of the same logical job; a deliberate new run uses a new request ID. Temporal history holds workflow status, attempts, and small counts. PostgreSQL holds catalog and prices. The operator can inspect Temporal for run progress, while the explorer derives eligible counts from the current database.

The [scheduled collection contract](scheduled-collection-contract.md) proposes the calendar gate, finite reviewed authorization, tick offsets, overlap/catchup behavior, and provider budget required before these session workflows are registered automatically. It is a proposal, not an enabled schedule or a change to manual catalog publication.

### Accepted grouping and retry boundaries

The earlier **25 stocks × one year** was a sizing guess. The accepted default is **five stocks × five years per activity**: about 5 × 5 × 252 = 6,300 daily bars. Request `limit=10000` on Alpaca's [multi-symbol endpoint](https://docs.alpaca.markets/us/v1.1/reference/stockbars); all bars can fit in one response, but the provider may return fewer, so the activity must follow every `next_page_token`. It saves each received page in a short, idempotent database transaction and returns only small counts/status to the workflow.

| Unit | What it groups | Failure/retry effect |
| --- | --- | --- |
| Default backfill activity | Five stock IDs and the five-year window; may contain multiple provider pages. | A transient activity failure can repeat this group's fetch. Prior committed pages remain safe because writes are idempotent. |
| Database transaction | One received provider page, even if the activity receives multiple pages. | A failed write rolls back only that page's transaction. |
| Narrow repair activity | One affected stock or a narrower stock/date range identified from a specific rejection or missing-data check. | Other stocks in the default group are not fetched again for that repair. |

A malformed bar for one stock is a **row-level result**, not a reason to fail and replay the whole group. Save valid rows, report the rejected row, and let the repair path address it. If the provider rejects the entire five-stock request because of one symbol, split the request to identify and retry the affected stock; authentication or request-format errors fail rather than triggering blind per-stock retries.

### Why this size

Five stocks × five years contains roughly 6,300 daily bars, so it can fit under a 10,000-bar response limit when the provider returns all requested bars. About 500 stocks require roughly 100 default activities. This avoids thousands of single-stock activities while limiting a group-level failure to five stocks. The provider can still paginate; the activity must follow all page tokens. A transient activity retry may repeat the five-stock request, while a **specific bad or missing stock/date** gets a narrower repair activity. The authenticated probe will tune concurrency, timeouts, and any provider-specific split needed for ticker changes; it does not reopen the accepted default grouping without evidence that the provider cannot support it.

### Backfill execution contract

1. Pin the published catalog snapshot, source/feed/basis, and exact date window before work begins. Include the trading close before the earliest selectable date. Partition the stock IDs deterministically into groups of five. Each default activity covers its five stocks over the five-year window, with the final group smaller if needed. Split provider calls at ticker-history boundaries only if the provider's verified mapping requires it.
2. Schedule a bounded number of group activities in parallel, subject to one shared provider rate limit and priority for refresh/reconciliation. Each activity requests `limit=10000`, follows all page tokens, validates rows, and commits each page plus provenance in a short idempotent transaction. Return small counts/status, never the price rows. Concurrency remains open until measured.
3. After a group's last page is committed, run a SQL completeness activity for that group. It compares requested, expected stock/session pairs with accepted stored bars for the same feed/basis. Listing exclusions require reliable listing dates; without them, historical absences remain **unclassified**, not asserted to be provider failures. Return a bounded count/repair plan, not thousands of raw rows in Temporal history.
4. A transient failure retries the **five-stock activity** with backoff; previously committed pages are safe to process again. A malformed bar records that row's rejection while valid rows remain saved. A whole-group provider rejection caused by one symbol triggers narrower requests to isolate it. If a successful paginated request omitted data, target only the missing stock/date pairs for repair; the repair-round limit remains to be verified.
5. Wait for all groups. Report `complete` only when every expected pair is present under the known listing policy and no unresolved rejection remains. Otherwise return an `incomplete` business result with counts and affected group IDs, even though the Temporal execution itself may close as Completed. An infrastructure failure that prevents this determination fails the Temporal execution. Cancellation stops new activities and leaves already committed bars available for a later idempotent restart.

The group activity is **at least once**: it can rerun after a worker crash or timeout. Each page's database write is idempotent by source/feed/basis, stock/date, provider observation identity or stable content key, so a repeated group does not create duplicate revisions or change the chosen price incorrectly. Source corrections create a new revision. [Temporal activity retry behavior](https://docs.temporal.io/tasks).

## 1. Publish the current stock catalog

**Trigger:** manual first publication; later a schedule, frequency undecided. **Input:** a dated constituent/sector source response. **Output:** one immutable, published universe snapshot whose member rows each identify a stock and its current sector.

| Order | Owner | Step | Writes / outcome |
| --- | --- | --- | --- |
| 1 | Temporal controller | Start a catalog run and dispatch a fetch activity. | Workflow/run ID only. |
| 2 | Catalog ingestion activity | Fetch source rows with source time and request metadata. | Temporary response in worker memory; no raw archive. |
| 3 | Catalog ingestion activity | Normalize ticker/exchange/name; match each source row to a stable stock ID or flag a new/ambiguous stock. Check duplicate share lines and missing sectors. | Proposed security and ticker-history changes. |
| 4 | Catalog validation activity | Compare membership and sectors with the last published snapshot. Report additions, removals, ticker changes, and missing/ambiguous mappings. | Validation report; publication policy is open. |
| 5 | Catalog publication activity | In one application-DB transaction, write the immutable snapshot and member-sector rows, then point “latest published” at it. | New catalog snapshot available to queries, or held for review. |

The query path uses the current sector recorded **in the pinned published snapshot**, even if its price window is historical. Effective-dated sector history can be retained, but first-release rankings do not reconstruct past sector membership. Source access and change-review thresholds are unresolved.

## 2. Backfill daily prices

**Trigger:** operator starts the initial five-year load. **Input:** published snapshot ID, requested history window, price provider/feed/adjustment setting. **Output:** normalized bars and a completeness check derived from stored data.

| Order | Owner | Step | Writes / outcome |
| --- | --- | --- | --- |
| 1 | Temporal controller | Pin the catalog snapshot and partition stock IDs into five-stock groups for the five-year window. Include the trading close before the earliest selectable date. | Run ID and group IDs. |
| 2 | Group ingestion activity | Request provider daily bars for five stocks over five years with `limit=10000`; follow every page token and obey the shared provider rate limit. The daily volume may include extended-hours trades. | Provider pages in worker memory, not Temporal history. |
| 3 | Same group activity | Resolve each returned ticker/date to the stable stock ID. Report ambiguous/unmapped or malformed rows individually. Validate session, numeric OHLCV, feed, adjustment setting, and provider timestamp. | Accepted rows plus individual rejection counts/reasons. |
| 4 | Same group activity | Commit each page's ingest batch, bar revisions, and selected current accepted bars in a short transaction. Use stable idempotency keys so a group retry does not duplicate revisions. | Application PostgreSQL observations and provenance. |
| 5 | Completeness query activity on an ingestion worker | After the last page of a request group is committed, query application PostgreSQL for requested stock × regular trading-session pairs without a stored bar for the configured source/feed/basis. Exclude pre-listing dates only when reliable listing dates exist. Return a bounded repair plan to Temporal; do not save a gap table. | Derived counts and affected group ID. |

The five-stock/five-year group and requested 10,000-bar page limit are the accepted default. Activity concurrency and provider-specific handling require an authenticated probe. Temporal records attempts and retries; a workflow can finish with an `incomplete` outcome after its repair limit while some prices remain absent. Explorer availability requires an explicit coverage policy that is still open. The collector does not retain full raw API response bodies.

The completeness query is part of backfill and post-close reconciliation, not a continuous service or a step in every explorer request. An hourly provisional refresh reports missing/stale updates separately; its completeness policy is still open. If a provider call fails, Temporal retries that call directly. The SQL query handles a different case: the call succeeded but omitted a requested stock/date. After the repair limit, the workflow reports the group as incomplete rather than fabricating a price.

“**Map security**” means convert a provider's ticker **on that session date** into the stable stock ID; a ticker string alone is not an identity. “**Validate OHLCV**” means check date/session, numeric prices, price ordering and nonnegative volume before selection. “**Price basis**” means the provider adjustment/corporate-action setting recorded on the request and bar; which basis rankings use is still undecided.

## 3. Refresh the current session

**Trigger:** about-hourly Temporal Schedule ticks during regular US trading hours, followed by bounded checks after close for changes to that day's bar. The exchange calendar and session date use `America/New_York`; choose the bounded after-close window from available endpoint behavior and rate limits, without treating its end as proof of provider finality. The next-day reconciliation and later lookback can capture delayed changes. Skip a tick if the previous refresh is still running; the next tick obtains the latest cumulative bar. **Input:** latest published catalog snapshot and a configured provider/feed/basis. **Output:** one updated cumulative whole-day bar per returned stock, with source and as-of metadata.

This is **one workflow per tick**, not 500 workflows. Its worker fetches the tracked universe in bounded requests, maps tickers, validates observations, and reports source-as-of time and returned/expected counts. A provider failure gets bounded activity retries; a missed tick raises schedule/lag monitoring, with no replay of every missed hourly snapshot. The worker requests a cumulative current-day daily bar (or, if the API probe shows this is unavailable, tests whether minute-bar aggregation can reproduce the accepted same-day price and volume convention within the plan's limits). An available provisional bar participates in a ranking whose requested range includes today, with provisional status and source-as-of time shown. Storage and query-selection mechanics remain open: revisions and a separate provisional pointer are a proposal, not a decision. The first system does not store independent hourly bars. A stale or missing update must be visible; exact freshness thresholds await a provider probe.

## 4. Reconcile and repair a session

**Trigger:** one Temporal Schedule action on the New York calendar day after each trading date, plus periodic lookback checks of recent sessions. This schedule is an operational recheck, not a statement about provider publication timing. Skip dates without a prior trading session. Later targeted repairs start `PriceRepairWorkflow` separately. **Input:** session date, catalog snapshot, source/feed/basis. **Output:** latest accepted prices, completeness status, and correction history.

This is **one workflow for the session**, reusing the bounded fetch/save and completeness activities from backfill for the one-day window. The worker refetches daily bars, validates them by the same rules as backfill, appends changed observations as revisions, and selects the latest accepted value. The completeness query can be rerun to find omitted prices and direct up to two targeted repair rounds. The workflow reports `complete`, `incomplete`, or `failed`; `complete` means the requested recheck finished with the expected observations, not that the provider will never issue a later correction. Exact freshness thresholds remain an implementation setting.

## 5. Answer the first explorer query

**Trigger:** an API request, not Temporal. **Input:** requested start/end dates and scope. **Output:** sector/stock ranking with the calculation evidence.

1. The API checks the date range and scope and invokes the analytical service.
2. The analytical service pins the latest published catalog snapshot and one configured provider/feed/price basis for the request.
3. It resolves the first trading session on or after the requested start, the final session on or before the requested end, and the session immediately before the first. A range with no valid endpoint returns an explicit error.
4. In set-based SQL, it reads both comparison closes for every tracked stock from the selected validated bar view. Stocks without either close are excluded; counts are retained.
5. It calculates stock returns, the strictly-positive count and eligible count per current sector, equal-weight sector and tracked-universe market returns, and each stock's excess return over its sector.
6. It returns rankings plus requested/resolved dates, eligible/total counts, catalog as-of, market-data source/feed/basis, and data as-of time. It reports insufficient coverage rather than silently changing the universe.

The date and metric rules are in [analysis-scope.md](analysis-scope.md). The analytical service owns calculations for both this explorer and later agent tools.

## 6. Answer a later free-text question

The API records the question and starts one Temporal workflow for the Agent Turn. It continues after the browser disconnects. The workflow coordinates bounded interpretation, validation, analytical tool calls, and answer construction; model calls and database I/O run in activities so workflow replay is deterministic. An agent proposes a typed analytical plan; application validation constrains dates, universe, metrics, row count, and tool budget. A read-only analytical tool executes through the same service as the explorer, returning evidence. The agent then explains the result or asks for clarification. It has no database credentials and cannot submit unchecked SQL. The exact activity breakdown and agent framework remain to be chosen. See [agent-harness-contract.md](agent-harness-contract.md).

## Shared failure and execution rules

- Separate task queues and worker capacity for session refresh/reconciliation, backfill, and later agent work. Refresh has priority over historical loading. Bound in-flight five-stock backfill activities and leave capacity for scheduled session work; set the concurrency limit after the provider probe.
- Provider calls use one shared rate limiter across all collection workflows. Transient timeouts/5xx/429 get bounded activity retries and backoff; permanent request/auth/schema errors fail without repeated calls. Honor provider `Retry-After` when available. Exact timeouts, retry delays, and rate budgets come from the authenticated API probe.
- Keep provider-call failures and rejected-row reasons in Temporal activity outcomes; derive missing expected prices with SQL against the catalog, trading calendar, and stored bars. Do not persist a separate gap table.
- Provider credentials and model keys stay out of workflow payloads and logs.
- The private first deployment has no backup process; backup/restore design is deferred.
