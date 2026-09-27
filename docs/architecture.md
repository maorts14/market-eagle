# Market Eagle lakehouse architecture

Market Eagle has three independent persistence responsibilities:

| Concern | Technology | Why |
| --- | --- | --- |
| Market data | Iceberg tables on LocalStack S3-compatible object storage | Immutable raw landing, schema evolution, snapshots, and analytical table semantics. |
| Iceberg catalog | REST catalog with a durable local SQLite volume | Maps table names and snapshots to object-store metadata; deliberately separate from application data. |
| Analytical reads | Trino | SQL query plane over Iceberg; the API and research tools do not treat Postgres as a warehouse. |
| Application and workflow state | PostgreSQL | Pipeline audit records, instrument catalog, research sessions, and Temporal's durable history. |

## Data contracts

- `bronze.market_price_payloads`: immutable source payloads with fetch metadata.
- `silver.daily_bars`: normalized, idempotently upserted end-of-day bars keyed by `(symbol, trading_date)`.
- `gold.sector_relationships`: materialized lead/lag calculations associated with an analysis run.
- `gold.daily_briefs`: durable analyst output with serialized evidence.
- `bronze.event_article_payloads`: raw dated external-news records, retaining source URL and provider payload.
- `gold.event_market_links`: auditable contextual links between a saved relationship scan and relevant dated articles. These are explicitly not causal assertions.

Every Temporal ingestion workflow first lands the provider response in Bronze, then updates Silver. The analysis workflow consumes Silver and materializes Gold. The research-agent workflow only reads Gold/Silver through the analytical query boundary and writes session/audit state to Postgres.

The local catalog volume is an emulator choice. A deployed environment should swap it for a managed Iceberg REST catalog backed by a durable relational catalog, without changing table contracts or query clients.
