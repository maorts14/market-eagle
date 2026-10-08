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

## Checks

```sh
npm run test
npm run build
npm run lint
```

The adapter tests compare both committed windows with `fixtures/synthetic-v1/expected-results.json`. The screen reports requested and resolved sessions, comparison close, coverage, source/feed, price basis, data as-of time, catalog as-of date, and provisional status when present. Production return rankings remain untrusted until the price adjustment basis is decided.

## Design notes

This is an operating surface for repeated trader research. The left table ranks sectors only by breadth; return and market difference remain context. The right table ranks eligible stocks by excess over the selected sector. Selection uses a single muted green accent. Tables scroll horizontally on narrow screens and remain keyboard focusable. Dates, source, and coverage stay visible above the tables, with full calculation evidence below.
