# Technology choices and tradeoffs

Status: Temporal is a user-selected architecture direction. PostgreSQL for initial market data and omission of raw response archive are accepted. Other choices remain recommendations for review.

| Concern | Recommendation | Why / revisit condition |
| --- | --- | --- |
| Durable workflows | **Temporal** for catalog, backfill, refresh, and repair; agent-turn use remains a candidate | Temporal provides durable collection control but adds server, persistence, and worker operations to the homelab. The first explorer is a synchronous API/query path. [Self-hosted guide](https://docs.temporal.io/self-hosted-guide). |
| Analytical SQL and market store | **PostgreSQL accepted for first system** | First retained scope is about 630k daily bars and set-based return queries. Measure performance after deployment; reconsider Iceberg as data and query load grows. [storage-rationale.md](storage-rationale.md). |
| Workflow persistence | PostgreSQL databases separate from application database | Temporal owns history/visibility and manages its schemas. Separate credentials and restore units. [Temporal persistence configuration](https://docs.temporal.io/references/service-configuration). |
| Raw payload archive | **Omit initially** | Persist normalized revisions and provenance metadata; revisit exact-response replay only when it has clear value. |
| API | Python FastAPI + Pydantic contracts | Typed public boundary and shared Python domain code; separate process from workers. |
| Agent model provider | **OpenRouter first, with a fixed free model** | The Temporal worker calls Chat Completions and validates structured decisions in trusted code. The free plan's 50 requests per day and variable availability limit local use; live key-backed behavior still needs verification. [Model support](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b:free), [pricing](https://openrouter.ai/pricing). |
| Web | React + TypeScript | Explorer with interactive date range, sector ranking and drilldown; final frontend hosting open. |
| First physical deployment | Docker Compose on one host, subject to a deployed baseline measurement | Preserves service separation without requiring a cluster. The host inventory is complete; local Kubernetes remains a viable choice if its operational needs justify it. [Compose production guide](https://docs.docker.com/compose/how-tos/production/). |

The full logical architecture is in [system-architecture.md](system-architecture.md). Data, workflow, and operations detail are split into [data-model.md](data-model.md), [workflows.md](workflows.md), and [operations-and-load.md](operations-and-load.md).
