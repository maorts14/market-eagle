# Analytics integration boundary

`AnalyticsService` powers both the explorer and the typed analytical request. The
application includes `create_explorer_router(repository)` and
`install_analytics_errors(app)`; the agent harness calls `execute(request)` with
an `AnalyticalRequest`. The fixture adapter is only for synthetic integration.

The production data adapter implements `AnalyticsRepository.load(start, end)`.
It returns one latest published catalog snapshot, one selected source/feed/price
basis, the calendar sessions through `end`, and selected accepted bars for the
window plus the session immediately preceding its first session. This read must
pin a consistent snapshot of the catalog and selected bar revisions. Fetch bars
for all tracked stock IDs in a set-based query; do not issue one query per stock.
The service makes exactly one repository call per explorer or typed request and
performs no writes. A slow batch read delays explorer page load and agent turns.

The adapter owns the current-day provisional selection rule and must include an
available provisional bar when the requested window contains today. It must not
mix source, feed, or price basis. An unavailable catalog or selected data must
raise a typed `AnalyticsError` or map to one before reaching the route.

`return_rankings_trusted` stays false while the production return price basis
is unresolved. Synthetic fixture values are fictional. The service reports the
selected basis, observation status, provider as-of time, coverage, and excluded
stock IDs for every calculation.

Run the focused checks with `python -m pytest backend/tests/test_analytics.py`.
