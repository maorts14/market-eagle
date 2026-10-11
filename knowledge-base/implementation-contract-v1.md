# Implementation contract v1

This contract coordinates the first synthetic vertical slice. It implements the accepted behavior in [analysis-scope.md](analysis-scope.md), [agent-harness-contract.md](agent-harness-contract.md), and [interaction-proposal.md](interaction-proposal.md). `v1` is the initial wire and fixture version, not a claim that provider and price policies are settled.

## Ownership and layout

- `backend/market_eagle/ingestion/` and database migrations: data and ingestion owner.
- `backend/market_eagle/analytics/` and the explorer API route: analytics owner.
- `frontend/`: interface owner, after the explorer API is integrated.
- `infra/`, `.github/workflows/`, and root developer commands: infrastructure owner.
- `fixtures/`: lead-owned synthetic history; other owners may propose fixture changes through review.

The first service may be one FastAPI process with separate ingestion worker and Temporal processes. Use PostgreSQL for application data and separate Temporal databases. Keep worktree branches based on `dev`; reviewed branches merge into `dev`. Changes to this contract require lead review before dependent work changes.

## Synthetic data contract

`fixtures/synthetic-v1/` contains a reproducible, explicitly fictional five-security history covering the weekdays of 2024 and 2025. Its sessions are **synthetic weekdays**, not an NYSE holiday calendar or licensed market data. `catalog.csv` carries stable `stock_id`, ticker, and sector; `bars.csv` carries `stock_id`, ticker, session date, OHLCV, optional VWAP and traded notional, source/feed/basis, and provider as-of time. Ingestion links bars to securities by stable `stock_id`; analysis joins the pinned catalog snapshot by `stock_id` for current sector grouping. The preceding comparison close exists for the first selectable session. One stock begins later and another has omitted observations to exercise coverage. The generator is deterministic; the fixture is committed for every owner to use.

**Environment boundary:** This five-stock fixture belongs only in automated CI, disposable/local test databases, and an explicitly fictional hands-on test workspace. CI must load it and compare query results with committed expected calculations. A user may run the same test workspace to try the explorer and agent without real market data. The actual app deployment must use a separate database and reviewed real catalog; it must reject `synthetic-v1` and any five-stock validation snapshot as its selected catalog. Do not seed the production database with the fixture. A separate real Alpaca five-stock sample may be used for isolated ingestion validation, but it is not the app's market universe or a substitute for the production catalog.

Provider adapters must not treat fixture values as live prices. The synthetic basis is `synthetic_raw`. Production return rankings remain labeled untrusted until the price-basis decision in issue #3 is made. Daily dollar volume uses reported notional if present, otherwise volume × VWAP, otherwise volume × close; both fallbacks are estimates with their input and formula shown.

## Explorer HTTP contract

`GET /api/v1/explorer?start=YYYY-MM-DD&end=YYYY-MM-DD` accepts inclusive requested dates; `start <= end` is required. The server pins one latest published catalog snapshot and one source/feed/basis, resolves the first and final available trading sessions within that window, and uses the close **immediately before** the first included session as the return denominator. A window with no configured sessions or no preceding **calendar session** returns a typed validation/coverage error; it does not invent a zero return. If the preceding session exists but every stock lacks a usable comparison or final close, return a successful result with zero eligible stocks and null calculated measures. The backend returns decimal fractions, so `0.05` means 5%. Dates and timestamps are ISO 8601; times include UTC offset. All identifiers are strings.

The response is an object with:

| Field | Meaning |
| --- | --- |
| `contract_version`, `metric_version` | `1` and `return-v1`, respectively. |
| `requested_window`, `resolved_window` | Requested `start`/`end`; resolved `comparison_session`, `first_session`, `last_session`. |
| `catalog` | `snapshot_id`, `as_of`, `published_at`, `tracked_count`. Sectors are those in this current snapshot even for an old window. |
| `data` | `source`, `feed`, `price_basis`, `as_of`, `as_of_kind`, `provisional`, `synthetic`. `as_of` is the **oldest as-of timestamp among eligible final endpoint bars**, a conservative freshness floor; null if none are eligible. `as_of_kind` is `provider`, `fetched`, `mixed`, or null, so a collection time is never presented as a provider publication time. Individual stock timestamps and kinds remain available. One query never mixes sources, feeds, or bases. |
| `market` | `eligible_count`, `excluded_count`, `return`; null return when none are eligible. |
| `sectors[]` | `sector_code`, `sector_name`, `tracked_count`, `eligible_count`, `excluded_count`, `up_count`, `breadth`, `return`, `excess_vs_market`, `stocks[]`. Null calculated values when eligible count is zero. |
| `sectors[].stocks[]` | `stock_id`, `ticker`, `name`, `return`, `excess_vs_sector`, `comparison_close`, `final_close`, `final_observation_status`, `data_as_of`, `data_as_of_kind`. Only eligible stocks appear; there is no top-level `stocks` array. |

Sector order: breadth descending, then sector code ascending. Stock order within each sector: excess return descending, then ticker ascending. `up_count` counts strictly positive returns. Sector and market returns are arithmetic means over eligible stocks; excess is a difference of decimal returns. Tracked/eligible/excluded counts expose missing endpoints. A current-day request uses available provisional observations. `data.provisional` is true if any eligible final endpoint bar is provisional; each stock carries its own observation status. Absent provisional observations stay excluded.

Errors use `{ "error": { "code": string, "message": string, "details": object } }`, with HTTP 400 for invalid ranges, 422 for unsupported requested values, 404 for no published catalog, and 503 for unavailable selected data. The API must never return a success-shaped empty result for a failed dependency.

## Analytical request boundary

The agent phase calls a versioned, typed, read-only analytical request service, never raw SQL. The request contains registry IDs and typed values for universe, dates, measures, daily conditions, reductions, predicates, grouping, sort, and bounded limit. The first implementation must support the required previous-calendar-month question as a composition: `daily_dollar_volume > 100000 USD`, qualifying/observed usable days `>= 0.80`, period return descending, limit 1. It returns both counts, requested-session coverage, source/feed/basis, calculation time, and dollar-volume provenance. Do not create a one-off endpoint for that sentence. Until the full agent harness is built, the analytics owner should expose this via a callable service function and tests; the agent owner later binds it to tools and Temporal turns.

Inject the reference date for relative language in tests; `2026-01-08` resolves “last month” to `2025-12-01` through `2025-12-31` in the committed synthetic fixture.

## Integration gate

The first integration runs local PostgreSQL and Temporal, loads the synthetic fixture, calls the explorer route for at least two windows, verifies sector and stock arithmetic and coverage against committed expectations, and runs the typed gain-plus-volume query. The infrastructure owner makes this runnable with one documented local command and CI checks. Live provider access is a separate validation gate, not a prerequisite for synthetic integration.
