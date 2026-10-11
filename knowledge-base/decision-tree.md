# Design decision tree

This records accepted choices, explicitly deferred questions, and checks to perform after the definition is pushed. It is not a request for another broad design interview. Decisions move to the other knowledge-base files when resolved.

## Settled

- Audience path: creator first; traders as design partners later; production-grade destination.
- Initial universe: S&P 500 stocks.
- Universe semantics for the first release: current members only; historical membership is deferred to [collect more stocks](https://github.com/maorts14/market-eagle/issues/1).
- Base observation: daily OHLCV for each stock, with sector association.
- Initial backfill: five years.
- Intraday refresh goal: about hourly during the US trading session, then continue checking the same day's bar after close. Label today's bar provisional and retain source/as-of time. Refetch prior sessions to catch late updates; do not require proof of an exact provider-final time.
- Intraday representation: update one provisional whole-day OHLCV candle; no separate hourly candles in the first slice.
- If a requested range includes today, include an available current-day provisional bar in calculations and rankings; show its provisional status and provider as-of time. A range for "last month" means the previous completed calendar month, so it does not include today.
- Daily-bar convention: use the provider's same-day candle as it updates. Its volume may include extended-hours trades after the regular close; do not describe that volume as regular-session-only. Keep one candle for the date and show its source/as-of time.
- Sector classification: sourced and effective-dated; official GICS if permitted.
- First-release historical-window grouping uses each tracked stock's **current sector in the latest published catalog snapshot at query time**, even when the selected price window is in the past. Show the sector snapshot/as-of date. Historical sector grouping is deferred.
- Data budget: $0/month during creator development, to be reconsidered with trader design partners.
- Initial hosting: the creator's homelab PC. Raw Docker versus local Kubernetes is undecided.
- The initial private homelab deployment will not run backups. Backup design and restore practice are deferred until a later stage.
- Initial access: creator's devices via Tailscale; public web publishing is deferred. Backend runs on the homelab, frontend location is undecided.
- Trader horizon: swing and long term.
- Intended research job: find market trends and drill into them. Candidate questions are recorded in [analysis-scope.md](analysis-scope.md).
- First analytical slice: sector leadership and leading stocks within sectors, over flexible time windows.
- Sector leadership metric: percentage of tracked stocks in the sector that rose over the window (Sector Breadth).
- Stock leadership: show the stock's own return and rank by its excess return versus the equal-weight average return of eligible tracked stocks in its sector.
- Window input: arbitrary start and end dates within retained history; common periods can be UI shortcuts.
- Window comparison: previous trading close before the selected start through the final trading close on or before the selected end; this includes the first date's trading change.
- In the first gain-plus-volume agent example, the daily threshold is **dollar trading volume**, not share count. The current rule is provider-reported traded notional when available; otherwise estimate share volume × daily VWAP, falling back to share volume × daily close if VWAP is unavailable. Label and disclose either estimate. Revisit this rule after provider verification in [GitHub issue #4](https://github.com/maorts14/market-eagle/issues/4).
- Missing prices: exclude a stock without both comparison prices and show the eligible count for each sector. A positive return means strictly greater than zero.
- Query results are derived from stored observations for the requested question; the product cannot pre-store every possible free-text result. Caching policy is undecided.
- Agent direction: query construction from user intent, with predefined options acceptable initially; see [agent-design.md](agent-design.md).
- The agent's first data scope is the product's retained data; it should answer flexible analytical questions, use multiple read-only steps when useful, and aim for one query when one suffices. It cannot directly execute model-generated SQL or use unapproved/write actions. News is a later source.
- The agent carries context within a conversation; a new conversation starts fresh. The app supports multiple conversations; before authentication all app visitors can view and permanently delete them through an explicit action, and after authentication access becomes per-user.
- The first agent must handle the gain-plus-volume-frequency example in [agent-design.md](agent-design.md), along with broader decision, tool, and end-to-end tests. It makes a reasonable interpretation when possible and discloses its assumptions; it asks when no defensible interpretation exists.
- Causal “why” questions are outside the first agent's scope. It may describe measured trends and patterns in stored data, but not claim a cause. Supporting evidence belongs in a collapsed section that can be opened; it should be relevant to the question rather than arbitrary sample rows from a large aggregate.
- The agent composes typed Analytical Requests from reusable metrics, fields, time windows, filters, aggregation, and ranking. Trusted code validates and compiles them; examples are test cases, not one-off prompt paths. It makes and discloses a defensible interpretation of free text and asks only when none is available.
- The first analytical vocabulary combines daily OHLCV, period return, comparisons, counts, percentages, averages, sector grouping, and ranking; trader-focused research informed the accepted capability set. Each agent turn runs as a Temporal workflow and continues after browser disconnection. Full conversations remain visible until explicit deletion; the model uses recent turns, a summary of older turns, and can retrieve original turns when needed.
- The agent and harness design interview reached shared understanding; [agent-harness-contract.md](agent-harness-contract.md) is the confirmed implementation handoff. Provider-specific metric settings, homelab limits, and the broader answer-quality threshold are implementation and release calibration dependencies.
- Absolute day-count conditions require that many observed qualifying days. Relative day-frequency conditions divide qualifying days by the stock's observed usable days in the requested range, even for a recent listing or incomplete provider coverage. Show the qualifying/observed counts and observed coverage. There is no fixed minimum sample floor initially; reconsider it if usage demonstrates a problem. One active turn is allowed per conversation. Other conversations can run concurrently with isolated context.
- The first-release analytical capability set from trader-vocabulary research is accepted; exact metric policies still depend on provider and data verification. The user can cancel an active agent turn and then send another message in that conversation once cancellation completes.
- The agent may answer from eligible stocks despite missing observations, stating the eligible count and percentage of the requested universe and scoping its claim to that evaluated set. It must not claim a winner across all requested stocks when missing stocks could change the result. Decision, tool-boundary, and end-to-end tests gate release. The operator may manually override the release test gate; runtime read-only and allowed-action boundaries stay enforced.
- At a turn budget limit, the agent gives a verified scoped partial result if available; otherwise it explains the limit and offers to narrow or retry. Wrong calculations and broken runtime boundaries fail the release test gate. Answer quality is evaluated through grounded facts, completeness, clarity, and correct conversation use, with human-calibrated grading. A manual release override records operator, reason, test version, and failed checks.
- Free-text answer quality uses code checks for structured facts, a separate rubric-driven model evaluator for semantic claims, and human-labeled cases to calibrate the evaluator. Core factual and coverage checks block release. The evaluator must accept valid rewordings and reject fluent but unsupported answers.
- Build initial evaluation cases before launch from synthetic fixtures and representative questions. After launch, use reviewed real questions, traces, and feedback to expand the suite. A case joins the release gate only after its expected behavior is labeled.
- Sector ranking remains by breadth; Sector Return and Market Return appear alongside it as context.
- Market Return is the equal-weight average period return of eligible tracked S&P 500 stocks, not an external index return.
- Stock evidence shows stock, sector, and market returns. Every answer includes resolved window, eligible coverage, data source, and as-of time.
- First usable interaction: sector/stock explorer with arbitrary date selection and drilldown. Free-text agent interaction follows over the same calculation layer.
- Delivery priority: understand and probe a fitting market-data API before building the calculation and explorer slices.
- Alpaca Free is the leading private-development OHLCV candidate; a slow initial backfill is acceptable. Its delayed SIP access is acceptable for now, subject to authenticated verification.
- Temporal is the workflow foundation for collection and each agent turn; the explorer remains a direct API/query path.
- The historical backfill uses one Temporal workflow with activities, without a child workflow or workflow per stock in the first design. The default activity requests five stocks over five years, with narrower activities for specific failures.
- PostgreSQL is selected as the first market-data store and analytical SQL engine. Iceberg may be reconsidered if the workload grows.
- Do not retain full raw provider API responses in the first system. Retain normalized observations, their revisions, and source/request/parser provenance.
- Exact replay of a previously displayed answer after a provider price correction is deferred. Use current validated observations for new calculations; revisit per-answer revision pinning if corrections become a practical problem.

## Current frontier

1. **Full-universe market-data verification**: the 2026-10-08 authenticated Alpaca paper-account probe confirmed five-year raw SIP daily bars for five symbols and a current-day historical `1Day` bar with a delayed cutoff. This is evidence for the isolated validation path, not proof of full-universe alias coverage, sustained rate capacity, after-close update behavior, or display rights. FMP constituent/sector access and historical share-line review remain open. See [scheduled-collection-contract.md](scheduled-collection-contract.md) before any automatic collection.
2. **Unresolved calculation inputs**: the implementation persists and selects provisional current-day revisions and labels them; inclusion of an available provisional bar for a range containing today remains settled. The production price adjustment/dividend basis, freshness and coverage thresholds, and provider-specific finality behavior remain open. New calculations use selected accepted revisions and later rechecks; exact historical answer replay is deferred. See [data-model.md](data-model.md) and [workflows.md](workflows.md).
3. **Deployment sizing**: [homelab-inventory.sh](homelab-inventory.sh) measured 6 cores/12 threads, 15 GiB RAM, NVMe root, and a separate 3.6 TB HDD on 2026-10-06. A local 500-stock analytical benchmark is recorded in [GitHub issue #21](https://github.com/maorts14/market-eagle/issues/21); it is not a deployed mixed-load capacity result. Measure the host with PostgreSQL, Temporal, API, agent, and collection workers together before setting production limits.
4. **Scheduled execution and provider budget**: [workflows.md](workflows.md) records the accepted five-stock/five-year default activity and narrower repair path. The five-symbol probe exercised the 10,000-bar historical request; full-catalog pagination, identity mapping, shared rate budget, bounded refresh fan-out, schedule registration, and automatic repair still need implementation and measurement. The [schedule control proposal](scheduled-collection-contract.md) identifies the approval and safety gates.
5. **Agent implementation dependencies**: [agent-harness-contract.md](agent-harness-contract.md) is confirmed. Precise metric versions depend on provider and shared data-policy verification; numeric limits depend on homelab measurements; the broader response-quality threshold depends on human-labeled baseline cases. These do not reopen the settled agent/harness behavior.

## Deferred or waiting on research

- **Historical sector reconstruction**: a stock's sector can change; [S&P DJI describes Visa and Mastercard moving from Information Technology to Financials](https://www.spglobal.com/spdji/en/documents/education/education-an-overview-of-gics-and-sp-500-sector-industry-indices.pdf). The first release groups by current sector. Revisit historical sector grouping only if the research need and source history justify it.
- **Freshness and fallback**: delayed SIP is acceptable for now. The selected bar records fetch time, not a provider finality timestamp. Set stale-data thresholds and failure behavior after observing full-universe regular and after-close updates.
- **Price basis**: raw OHLCV, split-adjusted series, and dividend-aware returns remain undecided. The user explicitly deferred the specific question of whether Stock Return accounts for stock splits on 2026-10-08; track it in [GitHub issue #3](https://github.com/maorts14/market-eagle/issues/3). Do not infer a split policy from the current return formula. Dividend treatment is a separate later question.
- **Data source verification and priority**: [market-data-api-evaluation.md](market-data-api-evaluation.md) identifies Alpaca Free as the private-development candidate. Five-symbol account behavior was probed; full-universe capacity, usage rights, and FMP constituent/sector access remain unverified.
- **Constituent and sector maintenance**: who validates current-member and effective-dated sector updates, and how frequently? This depends partly on source feasibility.
- **Agent operating values**: the agent turn runs durably in Temporal with read-only bounded activities. The remaining numeric limits and broader answer-quality threshold are calibration tasks during implementation; the plan vocabulary, turn status, cancellation, and conversation concurrency are recorded in the handoff.
- **Provisional-day operating policy**: the current implementation stores revisions and selects an available provisional whole-day bar. Keep provisional status and fetched-at time visible. The automatic regular/after-close schedule, stale threshold, and full-universe provider behavior remain open; see [scheduled-collection-contract.md](scheduled-collection-contract.md).
- **Future analytical engine**: revisit Iceberg, Trino, Spark, or others only when measured volume, latency, or query complexity calls for it. [storage-rationale.md](storage-rationale.md) records the comparison.
- **Future raw response archive**: reconsider only if exact replay or audit needs emerge; the first system omits it.
- **Backup and restore**: no backup process in the first private deployment. Before depending on the system for important retained research or opening it to traders, decide the backup destination, schedule, retention, and restore verification.

## Downstream, waiting on the frontier

- Retrieval corpus, agent/tool boundaries, evidence citations, and evaluation cases depend on the question contract.
- Provider adapters, exact bar constraints, refresh/recheck cadence, and fallback behavior depend on source feasibility. The service boundaries and first PostgreSQL engine are already proposed/selected as recorded above.
- Raw Docker versus local Kubernetes depends on homelab operational needs and available resources.
- User accounts, access control, operational targets, and commercial distribution depend on the design-partner rollout plan.
