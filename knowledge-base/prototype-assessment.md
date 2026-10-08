# Reference prototype assessment

Reviewed on 2026-10-05. This records behavior of the reference prototype before its removal from the `definition` branch. The code paths below are historical and remain available in earlier Git history; they are not a decision to preserve that implementation.

## Present behavior

- `backend/app/universe.py` hardcodes 11 sector ETFs and 11 representative stocks with curated sectors. It does not cover the S&P 500.
- `backend/app/market_data.py` fetches daily CSV bars from Stooq in live mode or generates deterministic synthetic bars in demo mode. The Compose default is demo mode.
- `backend/app/workflows.py`, `backend/app/activities.py`, and `backend/app/scheduler.py` use Temporal for backfills, weekday collection, lead/lag sector calculations, briefs, and research sessions.
- `backend/app/lakehouse.py` and `docker-compose.yml` use Iceberg, LocalStack, a REST catalog, Trino, PostgreSQL, and Temporal services.
- `backend/app/main.py` exposes stock and sector views, pipeline triggers, relationship and event views, and research-session endpoints. Its stock performance view calculates a five-session return only after six bars exist.
- `backend/app/agent.py` limits the model to recent performance, sector relationships, and event context. There is no document index or vector retrieval, and its fixed tools do not take stock or date arguments.
- `web/src/main.tsx` is centered on sector rotation and lead/lag relationships; it includes sample display data.

## Implications for the rebuild

- The daily-bar concept and source metadata are useful reference points.
- The existing ingestion path and fixed stock catalog do not meet the stated S&P 500 scope.
- The existing research tools cannot yet answer arbitrary stock-specific questions reliably.
- The current multi-service stack carries operational complexity before the first narrow product workflow is defined.
- Synthetic demo bars must be visibly separate from real market observations in any trader-facing product.
