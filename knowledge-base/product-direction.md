# Product direction

## Agreed

- Build an agentic, retrieval-grounded stock analysis system from scratch, using the existing project only as a direction.
- Build step by step, with a fully sketched system architecture before implementation.
- The eventual users are traders. The creator will develop and use it first, then introduce it to traders as design partners.
- The trader workflow is to discover market trends and drill into them, with emphasis on swing and long-term analysis.
- The long-term goal is production grade, while each earlier stage should remain practical and close to that goal.
- Start with the S&P 500 stock universe.
- Collect daily stock open, high, low, close, and volume observations. Associate each stock with its sector.
- The first collection tracks current S&P 500 members. Historical membership and expansion to more stocks are deferred in [collect more stocks](https://github.com/maorts14/market-eagle/issues/1).
- Backfill five years of daily data for the initial tracked stocks.
- During regular US trading hours, refresh the **current day's single OHLCV candle** about hourly and continue checking it after close while the provider still updates that same bar, including its volume. It remains provisional until the provider's finality condition is met; do not store a separate hourly candle in the initial slice.
- Use a sourced sector classification with effective dates; prefer official GICS if its usage terms fit.
- Group historical price windows by each tracked stock's current sector from the latest published catalog snapshot at query time. Show the sector snapshot/as-of date; historical sector grouping is deferred.
- The development data budget is $0 per month. Revisit the budget when the first trader design partners arrive.
- The backend's first deployment will run on the creator's homelab PC. The creator will access it from their devices over Tailscale; public web publishing comes later. Frontend location and raw Docker versus local Kubernetes remain undecided.
- The initial private deployment will run without backups. Backup and restore design are marked for a later stage.
- The first thin analysis ranks sectors by the percentage of eligible stocks that rose, then ranks stocks by outperformance versus their sector's equal-weight average return. Both use arbitrary user-selected dates through reusable time-window aggregation. Later candidates include persistent leaders, immediate or delayed stock correlations, and indicators. See [analysis-scope.md](analysis-scope.md).
- Analysis results are calculated for each requested question from selected market observations; the system will not pre-store every possible free-text result. An available current-day candle is included when the requested range contains today, with provisional status and as-of time shown. Its storage and selection mechanics remain undecided in [data-and-query-boundary.md](data-and-query-boundary.md).
- The agent should grow toward constructing analytical queries from user intent. Predefined options are acceptable initially; behavior details are tracked in [agent-design.md](agent-design.md).
- Trader-facing comparisons show a stock's return beside sector and market equal-weight returns. Sector rankings remain by breadth, with sector and market returns shown alongside. Every answer includes its resolved window, eligible coverage, data source, and as-of time.
- The first usable interaction is a sector/stock explorer with arbitrary date selection and sector drilldown. Free-text questions follow over the same calculation layer; see [interaction-proposal.md](interaction-proposal.md).
- Keep project context in this `knowledge-base` directory.

## Not yet decided

- Authenticated validation of the recommended private-development market-data candidate and the current constituent/sector source, with usage rights for later trader access. See [market-data-api-evaluation.md](market-data-api-evaluation.md) and [research data api](https://github.com/maorts14/market-eagle/issues/2).
- Exact hourly refresh timing, source delay, and how an unavailable or stale provider response is displayed.
- Which requirement takes priority if no $0 source satisfies the full universe, five-year history, and hourly updates. The user deferred this choice pending data-provider research.
- Adjusted prices, corporate actions, and missing or corrected data.
- Detailed agent query behavior, including when it asks for clarification and how it limits and cites analytical tools. The first user interaction is already the sector/stock explorer.
- Homelab deployment method, frontend location, access control within Tailscale, availability, and operational targets. Backup design is deferred beyond the first private deployment.
- PostgreSQL is accepted as the initial market-data store and analytical query engine. Service and deployment choices remain under review in [system-architecture.md](system-architecture.md); the prototype's Trino choice is not binding.
