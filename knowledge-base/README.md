# Knowledge base

This directory is the product and architecture baseline for the rebuild. The reference prototype was removed from the `definition` branch after this baseline was pushed; its code remains in earlier Git history. Documented provider, price-policy, and operating-value checks remain for implementation and release. No authenticated provider probe was required to publish this definition.

For the system's logical order, read [product-direction.md](product-direction.md) → [domain-language.md](domain-language.md) → [system-architecture.md](system-architecture.md) → [workflows.md](workflows.md) → [data-model.md](data-model.md) → [analysis-scope.md](analysis-scope.md). The [seven-page diagram](diagrams/market-eagle-architecture.drawio) follows the same paths. [decision-tree.md](decision-tree.md) separates accepted choices from unresolved ones.

| File | Purpose |
| --- | --- |
| [product-direction.md](product-direction.md) | Agreed goals, audience, and initial scope |
| [domain-language.md](domain-language.md) | Canonical domain vocabulary as terms are resolved |
| [analysis-scope.md](analysis-scope.md) | Trader research jobs, candidate questions, and open metric definitions |
| [interaction-proposal.md](interaction-proposal.md) | Accepted first workspace and drilldown interaction |
| [agent-design.md](agent-design.md) | Agent behavior goals and decisions to resolve in the separate design chat |
| [data-and-query-boundary.md](data-and-query-boundary.md) | Stored observations versus calculated analysis results |
| [prototype-assessment.md](prototype-assessment.md) | What the current code actually does and what it implies for the rebuild |
| [external-research.md](external-research.md) | Verified external facts and source links |
| [market-data-api-evaluation.md](market-data-api-evaluation.md) | Provider comparison, recommendation, rights, and required API probe |
| [decision-tree.md](decision-tree.md) | Open design decisions and their dependencies |
| [system-architecture.md](system-architecture.md) | Full-system architecture blueprint and service boundaries |
| [diagrams/market-eagle-architecture.drawio](diagrams/market-eagle-architecture.drawio) | Editable seven-page draw.io architecture workbook |
| [data-model.md](data-model.md) | Storage ownership, entities, keys, and query indexes |
| [storage-rationale.md](storage-rationale.md) | PostgreSQL versus Iceberg decision and raw archive explanation |
| [workflows.md](workflows.md) | Ordered catalog, price, explorer, and later agent flows with Temporal's control role |
| [scheduled-collection-contract.md](scheduled-collection-contract.md) | Proposed gates and cadence for automatic session refresh and reconciliation; not yet activated |
| [operations-and-load.md](operations-and-load.md) | Capacity, load controls, reliability, security, and deployment |
| [adr/0001-private-homelab-runtime.md](adr/0001-private-homelab-runtime.md) | Proposed first homelab deployment topology and implementation handoffs |
| [technology-tradeoffs.md](technology-tradeoffs.md) | Storage, query engine, workflow, deployment, and framework comparisons |
| [homelab-inventory.sh](homelab-inventory.sh) | Read-only Linux hardware and runtime inventory script |
| [implementation-plan.md](implementation-plan.md) | Branch flow, implementation stages, and agent responsibilities |
| [implementation-contract-v1.md](implementation-contract-v1.md) | First synthetic integration API, ownership, and fixture contract |

The accepted product behavior, analytical contract, and service boundaries are recorded here. Some storage, provider, and deployment mechanisms remain proposals and are labeled in their files. The removed root `README.md` and `docs/architecture.md` described the retired Iceberg/Trino prototype and remain available in earlier Git history.

## Handoff gates after the definition is pushed

- **Provider validation:** Alpaca Basic remains the private price candidate; FMP's S&P constituent endpoint returned HTTP 402 on the free account. The first private catalog uses a dated, manually checked public list with provisional membership/sector labels. Implement its distinct source and review gate before real full-universe collection. See [market-data-api-evaluation.md](market-data-api-evaluation.md); certified catalog licensing is [for later](https://github.com/maorts14/market-eagle/issues/57).
- **Market-data policy:** preserve source/feed/basis and as-of time in every observation and answer. Today's bar is provisional; older bars use the latest accepted revision and can still be corrected later. Implement bar selection, bounded after-close checks, and subsequent rechecks without claiming an exact provider-final time. Split treatment is intentionally deferred in [issue #3](https://github.com/maorts14/market-eagle/issues/3); do not present an unchosen return basis as a trusted final metric. The dollar-volume proxy is the current rule, with later review in [issue #4](https://github.com/maorts14/market-eagle/issues/4).
- **Operating and release values:** measure provider and homelab limits during implementation; choose broader answer-quality thresholds from a human-labeled baseline before release. The agent's core factual and permission tests are already required by [agent-harness-contract.md](agent-harness-contract.md). The pending human review input/output format is in [answer-quality-evaluation.md](answer-quality-evaluation.md).
