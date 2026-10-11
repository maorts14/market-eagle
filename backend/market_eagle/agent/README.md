# Agent integration

The agent package binds `AnalyticalRequest` v1 to `AnalyticsService.execute`. The
model receives a typed decision schema and cannot submit SQL or select a tool
outside the read-only analytical service. `validate_request` caps the date span
and output rows; Temporal caps retries and tool calls. The worker uses the
`PostgresAnalyticsRepository` with the same read-only database role and
statement timeout as the explorer. The committed fixture adapter remains for
deterministic verification.

Use `python dev.py integration` to load the fictional fixture and verify the
API, Temporal, and PostgreSQL path. Start `python dev.py api`; set
`OPENROUTER_API_KEY` in ignored `infra/.env` and keep `OPENROUTER_MODEL` set to
`nvidia/nemotron-3-super-120b-a12b:free`, then start
`python dev.py agent-worker` separately. Both processes use the same application
PostgreSQL agent tables, Temporal namespace, task queue, and limits. Only the worker receives the
OpenRouter key. The model slug is fixed so requests cannot silently route to a
paid or random model. The worker calls OpenRouter's Chat Completions endpoint
with a strict JSON schema for interpretation and validates the response again
with `Decision`; it does not use `responses.parse`. Provider routing requires
support for the requested structured-output parameter. `DATABASE_URL` remains
read-only for market calculations; `AGENT_DATABASE_URL` grants read/write access
only to the agent tables. Migration `003_agent_store.sql` creates those tables.
`AgentStore` remains a SQLite test fixture, not a runtime fallback.

For an existing local `local-data/agent.sqlite`, stop the API and worker, apply
the PostgreSQL migrations, and import into **empty** agent tables before starting
the new runtime:

```text
python dev.py migrate-agent-store
```

For other environments, run `python -m market_eagle.agent.migrate_sqlite
--source PATH` with `AGENT_DATABASE_URL` set. The import is transactional and
refuses to merge into a nonempty agent store. Keep the SQLite file until the
imported conversations and evidence have been checked.

The [selected free model](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b:free)
currently lists structured-output support. [OpenRouter's free plan](https://openrouter.ai/pricing)
lists 50 requests per day; a turn normally uses interpretation and explanation
calls, with possible repair or summary calls. Availability and supported
parameters can change, so a live request with the user's key is still required
before calling the provider integration verified. The selected model's page
also carries a notice about logging free-endpoint inputs; keep confidential or
personal data out of those prompts.

`POST /api/v1/agent/conversations` creates a conversation. Submit a turn with
`POST /api/v1/agent/conversations/{id}/turns` and a stable `request_id` plus
`question`. Reuse the same request ID to retrieve the existing turn. Poll
`GET /api/v1/agent/turns/{id}` after reconnect. `trusted_result` is copied from
the analytical service; `agent_explanation` is model prose. The evidence and
trace routes expose the underlying calculation and operational decisions.
Reconnect reads idempotently start an active turn by its deterministic Temporal
ID, repairing a crash between the store commit and workflow start. The same
path resolves a pending cancellation. When cancellation was recorded before a
workflow existed, it closes the turn without starting one. A transient Temporal start error leaves
the durable turn active so a later reconnect can retry it.
Cancellation marks `cancel_requested`, asks Temporal to cancel, then persists
`cancelled` before accepting a new turn in that conversation. Deletion first
cancels any active turn, then permanently removes its local records.

The synthetic fixture is fictional and its return rankings are marked
untrusted until the production price basis is settled. Numeric limits are
initial values to calibrate on the homelab. The core deterministic tests run
with `python -m pytest backend/tests/test_agent.py backend/tests/test_analytics.py`.
The Temporal test uses the SDK's local test server. Model answer quality still
needs human-labeled baseline cases before a broader release threshold can be
set.
`evaluation-v1.json` records the initial programmatic scenarios and rubric;
its prose cases are not human labels or a calibrated semantic release gate.
The [answer-quality evaluation handoff](../../../knowledge-base/answer-quality-evaluation.md)
defines the `python dev.py agent-evaluation` export, blank-review, and
validation workflow for that pending gate. It does not assign labels or a
release threshold.
Recent model context includes trusted prior result fields. Older context is
summarized incrementally from original turns, with the summary's source span
recorded; full original turns and evidence remain retrievable until deletion.
