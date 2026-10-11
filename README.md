# Market Eagle

This repository is the first implementation stage of Market Eagle. The
[knowledge base](knowledge-base/README.md) contains the accepted product and
architecture contracts; the committed `fixtures/synthetic-v1/` is fictional
test data.

## Local development

Install Python 3.12+, Node.js 24, and Docker with Compose. Set up the backend and frontend:

```text
python -m venv .venv
.venv/Scripts/python -m pip install -e "./backend[dev]"   # Windows
npm ci --prefix frontend
```

Use `.venv/bin/python` in place of `.venv/Scripts/python` on macOS or Linux. Then run:

```text
python dev.py up
```

This creates an ignored `infra/.env` from local development defaults, starts
PostgreSQL and Temporal, and checks both databases, Temporal's default
namespace, and the UI. The application database is at `localhost:55432`,
Temporal gRPC at `localhost:7233`, and the UI at
<http://localhost:8080>. Adjust the loopback ports in `infra/.env` if needed.

```text
.venv/Scripts/python dev.py check        # repeat health checks
.venv/Scripts/python dev.py verify       # fixture, formatting, and unit checks
.venv/Scripts/python dev.py integration  # services, migration, fixture, PostgreSQL/API checks
.venv/Scripts/python dev.py api          # serve the PostgreSQL-backed explorer on localhost:8000
.venv/Scripts/python dev.py agent-worker # run the research-agent Temporal worker
.venv/Scripts/python dev.py migrate-agent-store # one-time import of old local SQLite conversations
.venv/Scripts/python dev.py agent-evaluation # export stored turns for human review
.venv/Scripts/python dev.py agent-openrouter-smoke # one live model call against synthetic analytics
.venv/Scripts/python dev.py down         # stop services without deleting data
```

After `integration`, start `dev.py api` in one terminal and `npm --prefix frontend run dev` in another. To use the API rather than the browser's explicitly fictional fixture adapter, set `VITE_EXPLORER_MODE=api` for the frontend process. The API uses a separate read-only PostgreSQL role; its generated local password stays in ignored `infra/.env`. The fictional fixture is repeatable, and the integration gate compares two explorer windows through PostgreSQL and HTTP with the committed calculation results.

The API also mounts `/api/v1/agent` and stores conversations, evidence, and
traces in application PostgreSQL through a separate agent-only role. To run
free-text turns, add `OPENROUTER_API_KEY` to
ignored `infra/.env` and set `OPENROUTER_MODEL` to
`nvidia/nemotron-3-super-120b-a12b:free`, then start `dev.py agent-worker` in a
separate terminal. The API process receives no model or Alpaca credential; the
worker receives the model credential. Both processes use the read-only role
for market analysis and the agent-only role for conversation state. The Temporal
workflow and evaluation harness are in
`backend/market_eagle/agent/`. The integration check uses a fixed test model,
not a live model call. OpenRouter's free plan lists 50 requests per day; live
inference and structured-output behavior require a key-backed check. Live S&P
500 catalog publication and unrestricted
market-data display remain gated by the documented provider checks.

After a private five-stock Alpaca sample is reviewed and published, set
`MARKET_EAGLE_PRIVATE_SAMPLE_SNAPSHOT_ID` in ignored `infra/.env` to its
published snapshot ID before starting `dev.py api` and `dev.py agent-worker`.
This explicitly selects the private validation sample for the local app, labels
it as outside the S&P 500, and leaves `catalog_current` unchanged. Clear the
setting to return to the fictional development fixture. The sample path does
not resolve the production return price-basis or data-rights decisions.

With `OPENROUTER_API_KEY` set in the shell, `dev.py agent-openrouter-smoke`
asks one nonsensitive December 2025 ranking question and runs a valid query
through the synthetic analytics fixture. It prints only a JSON pass/fail summary,
not the key, prompt, or model response. A clarification or invalid request fails
the check; free-model output can vary between calls.

The local Compose stack is for development. It contains no provider or model
credentials and publishes services to host loopback. The first private
homelab deployment is a later reviewed stage after the application runtime
and measured capacity are available.
