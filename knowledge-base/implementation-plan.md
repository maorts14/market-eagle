# Implementation coordination

This is the delivery plan for the rebuild defined in this knowledge base. The `definition` branch preserves the documentation-only baseline. Create `dev` from its cleanup commit; create every implementation branch from `dev` and merge reviewed changes back into `dev`. Keep code changes out of `definition`.

## Agent responsibilities

| Responsibility | Scope |
| --- | --- |
| Lead/integrator | Own shared contracts, stage boundaries, reviews, integration tests, and merges into `dev`. |
| Data and ingestion agent | Stable stock identity, catalog snapshots, daily-bar revisions, provider adapters, and Temporal collection workflows. |
| Analytics agent | Shared metric definitions, typed analytical request validation/compiler, evidence, and synthetic calculation fixtures. |
| Interface agent | Sector explorer and stock drilldown against the agreed API contract. |
| AI agent expert | Temporal turn workflow, conversation behavior, analytical-tool use, and evaluation suite after the analytical service is usable. |
| Infrastructure and CI/CD agent | Reproducible local services, configuration and secret boundaries, automated checks, and private deployment pipeline. Measure the homelab before fixing worker and database limits. |

The architect and trader review architecture and calculation behavior at relevant milestones. Decisions are recorded in Markdown; batch role updates when a handoff actually changes their work.

## Stages

1. The lead establishes the repo structure, shared API/metric contracts, and a representative synthetic history (for example, five stocks over two years) with expected calculations.
2. Data, analytics, and infrastructure work can proceed in separate worktrees against those contracts. Integrate a vertical slice that computes sector breadth, returns, coverage, and the required gain-plus-dollar-volume question from synthetic observations.
3. Build the explorer against that integrated API. Validate authenticated provider behavior during ingestion implementation, without requiring an exact bar-publication time.
4. Add the agent harness over the same analytical service, then run the required factual, permission, and conversation evaluations. Choose the return price basis before treating live return rankings as trusted.

Each stage is reviewed and merged into `dev` before dependent work relies on it. Provider access, operating limits, and release gates are in [README.md](README.md); deferred choices are in [decision-tree.md](decision-tree.md).

The five-stock history is a deterministic **test environment**, not the actual app's market data. CI and local hands-on testing use the committed fictional fixture and its expected results. Keep its database separate from the real deployment and reject synthetic or isolated five-stock validation catalogs in the real app. The reviewed real catalog and provider policy are separate release gates; an isolated Alpaca sample can validate ingestion without becoming a user-facing universe. See [implementation-contract-v1.md](implementation-contract-v1.md#synthetic-data-contract).
