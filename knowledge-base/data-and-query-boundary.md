# Data and query boundary

## Settled product constraint

Users should be able to ask for sector and stock leadership across arbitrary supported time windows. The system cannot pre-store every possible free-text query result. Sector Breadth, Sector Return, and Stock Excess Return are derived for the requested question from retained market observations.

## Concepts to keep distinct

- **Base observation**: an OHLCV Daily Bar associated with a stock, trading date, source, and status. The latest accepted historical observations form the reusable input data; a later provider correction creates a new revision.
- **Provisional observation**: the current day's changing whole-day candle while the provider still updates it, potentially after the regular close. An available value is used for a requested range containing today and labeled provisional; whether it is persisted, fetched on demand, or both is undecided.
- **Derived result**: a ranking or calculation for a chosen universe and time window. It can be computed when asked; an optional cache may later speed repeated questions.
- **Answer**: the explanation and evidence presented to the user. It should identify the input window, eligible coverage, calculation, and data as-of time.

PostgreSQL is the accepted first store for normalized observations and the first analytical SQL engine. Result caching remains optional and is not required to support arbitrary windows.

The agent is expected to choose or formulate the analytical query from the user's intent. PostgreSQL is selected for the first deployed analytical engine. Its performance will be measured on the homelab; Iceberg/Trino/Spark are later growth options if query load and data volume justify them. The current prototype's Trino use does not determine the rebuild.

The chosen return-window rule needs a close from the trading session immediately before the requested start date. Backfill or query boundaries must account for that extra observation.
