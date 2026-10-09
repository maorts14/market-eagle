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
`OPENAI_API_KEY` and `OPENAI_MODEL` in ignored `infra/.env`, then start
`python dev.py agent-worker` separately. Both processes use the same SQLite
file, Temporal namespace, task queue, and limits. Only the worker receives the
OpenAI key. SQLite writes are
transactional and WAL enabled; a future multi-host deployment should replace
this agent-owned store with a transactional shared store.

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
Recent model context includes trusted prior result fields. Older context is
summarized incrementally from original turns, with the summary's source span
recorded; full original turns and evidence remain retrievable until deletion.
