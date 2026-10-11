# Market Eagle research interface

The first research workbench implements the accepted sector breadth comparison and selected-sector stock drilldown. It uses React, TypeScript, Vite, Tailwind CSS, and checked-in shadcn/ui components. The interface follows the neutral, data-first direction in `knowledge-base/interaction-proposal.md`.

## Run

```sh
cd frontend
npm ci
npm run dev
```

The default mode reads copied files from `public/fixtures/`. They are the explicitly fictional `fixtures/synthetic-v1` history. The sample shortcuts end on 2025-12-31; custom dates are calculated from the same CSV observations. The sample calendar contains weekdays, including exchange holidays. The UI labels all results as synthetic.

To use the v1 explorer route, set `VITE_EXPLORER_MODE=api` before starting Vite. The dev server proxies `/api` to `http://127.0.0.1:8000`; a deployed frontend needs an equivalent same-origin route. In API mode, the shortcuts use the current UTC date. `src/lib/explorer.ts` is the adapter boundary, and `ExplorerResponse` mirrors the v1 response. The backend service can return additional fields such as exclusions and `return_rankings_trusted` without affecting the UI.

When the API explicitly selects a published private Alpaca validation snapshot,
the workbench labels it as a five-stock sample outside the S&P 500 catalog.
Those stocks are grouped as unclassified, so this view checks real-data
calculation and presentation without claiming a sector taxonomy. That mode is
for an isolated test runtime; the actual app deployment must not select it.
For a hands-on test without real prices, use the fictional fixture adapter or
the local PostgreSQL `synthetic-v1` fixture.

## Checks

```sh
npm run test
npm run build
npm run lint
```

The adapter tests compare both committed windows with `fixtures/synthetic-v1/expected-results.json`. The screen reports requested and resolved sessions, comparison close, coverage, source/feed, price basis, data as-of time, catalog as-of date, and provisional status when present. Production return rankings remain untrusted until the price adjustment basis is decided.

## Research agent conversation

The workbench includes a collapsible conversation panel. It supports one active turn per conversation, follow-up questions, reconnectable progress, cancellation, clarification, unsupported and failed answers, and expandable calculation evidence. Primary numbers and source facts come from `trusted_result`; model prose is rendered separately as interpretation. Deletion requires an explicit inline confirmation that turns and evidence are permanent and the initial deployment has no backup.

The default `VITE_AGENT_MODE=fixture` is a clearly labeled, deterministic UI demonstration. It replays the documented December 2025 gain-plus-dollar-volume case and one follow-up from `fixtures/synthetic-v1/expected-results.json`; other questions return a fixture limitation, not a fabricated answer. `src/lib/agent.ts` also provides the real HTTP adapter. Set `VITE_AGENT_MODE=api` when the agent store, Temporal client, and worker are configured. The backend mounts `/api/v1/agent` when the agent is enabled; `python dev.py api` starts that configuration. The development proxy forwards `/api` to port 8000.

The selector loads the shared pre-authentication conversation list from `GET /api/v1/agent/conversations` on mount and refreshes it after create, submit, delete, and reconnect. All app visitors can list, read, and delete those conversations. The fixture adapter offers the same list behavior with browser-local data. The list endpoint is a backend integration dependency for API mode.

## Design notes

This is an operating surface for repeated trader research. The left table ranks sectors only by breadth; return and market difference remain context. The right table ranks eligible stocks by excess over the selected sector. Selection uses a single muted green accent. Tables scroll horizontally on narrow screens and remain keyboard focusable. Dates, source, and coverage stay visible above the tables, with full calculation evidence below.
