# Agent integration

The agent package binds `AnalyticalRequest` v1 to `AnalyticsService.execute`. The
model receives a typed decision schema and cannot submit SQL or select a tool
outside the read-only analytical service. `validate_request` caps the date span
and output rows; Temporal caps retries and tool calls. The worker process must
receive an `AnalyticsRepository` whose production adapter uses the read-only
database role and a database statement timeout. The repository has no such
production adapter yet; the committed fixture adapter is for verification.

Install `requirements.txt` in the backend environment. Create one shared
`AgentStore(Path(...))` for the API and worker, on a persistent local volume.
Create a Temporal `Client` and mount `create_agent_router(store, client, Limits())`
in the app. Run `run_worker(client, store, repository,
OpenAIResearchModel(model_name), Limits())` on its own agent task queue. Supply
the OpenAI key only to the worker process. Configure the worker and API with the
same SQLite file, Temporal namespace, queue, and limits. SQLite writes are
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
path resumes a pending cancellation. A transient Temporal start error leaves
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
