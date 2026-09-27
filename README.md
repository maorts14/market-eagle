# Market Eagle

Market Eagle is an evidence-first market intelligence workspace. It retains daily price history, measures sector rotation and lead/lag relationships, produces a daily brief, and lets a research agent answer questions using the stored data.

It is a research tool, not investment advice. Every relationship is labeled with the time window and statistic used; correlation is never presented as causation or a forecast.

## Architecture

```text
Provider / demo feed ──> Temporal collection workflows ──> Bronze Iceberg
                                      │                           │
                                      └──> Silver + Gold Iceberg ─┼──> Trino ──> FastAPI ──> React UI
                                                                  │
PostgreSQL <──────────────────────── audit state, research sessions, instrument catalog
```

All long-running work is a Temporal workflow: historical backfill, daily collection, daily analyst brief, and the tool-using research-agent loop.

## Run locally

1. Copy `.env.example` to `.env` (the committed defaults are safe for local use).
2. Run `docker compose up --build`.
3. Open http://localhost:5173 (workspace), http://localhost:8000/docs (API), and http://localhost:8233 (Temporal UI).
4. In the workspace, run **Build history** once. The default local source is a deterministic demo feed; set `MARKET_EAGLE_DATA_MODE=live` only after configuring a production-grade data provider.

The initial universe is 11 liquid U.S. sector ETFs plus 11 representative stocks, classified by an auditable curated sector catalog. Sector ETFs drive the relationship graph; stocks provide a concrete watchlist. Live data comes from Stooq's daily CSV endpoint; it needs no API key. The demo provider exists only for local demonstrations and is selected explicitly.

Questions about news, catalysts, macro conditions, or events invoke the external-event research tool. It stores dated GDELT article titles, source domains, and canonical URLs alongside the relationship scan that prompted the lookup. Those links are context for investigation, never evidence that an event caused a price move.

## Agent runtime

The research agent is a bounded Temporal state machine, not an in-process chat loop. Each OpenRouter model decision and each allowlisted tool call is persisted independently, so a worker crash resumes from the next unfinished step. Configure `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` in `.env`; the default model is `openai/gpt-4.1-mini` through OpenRouter. The API exposes per-run model calls, tool calls, latency, token use, guard rejections, and deterministic grounding checks at `GET /api/research/{session_id}`.

## Services

- `web` — Vite/React/Tailwind interface using shadcn-style primitives
- `api` — FastAPI read API and Temporal workflow trigger surface
- `worker` — Temporal worker for collection, analysis, and agent workflows
- `scheduler` — creates an idempotent weekday Temporal Schedule for the daily pipeline
- `object-store` — LocalStack S3 emulator holding Iceberg table files
- `iceberg-rest` — durable local Iceberg catalog; its metadata volume is separate from object data
- `trino` — analytical SQL query plane over Bronze/Silver/Gold
- `market-db` — application Postgres data store, never the price-history warehouse
- `temporal` / `temporal-ui` / `temporal-db` — orchestration runtime

## Important routes

- `POST /api/pipelines/backfill` starts the historical-data workflow.
- `POST /api/pipelines/daily` starts a current-data + analysis workflow.
- `POST /api/research` starts the Temporal research-agent loop.
- `GET /api/relationships` exposes the calculated sector relationship graph.
- `GET /api/event-links` exposes sourced external context connected to the latest relationship scan.

## Verification

```powershell
docker compose up --build
curl http://localhost:8000/health
curl http://localhost:8000/api/overview
```

Run backend unit tests inside the worker image with `docker compose run --rm worker pytest`.
