# Analytics integration boundary

`AnalyticsService` powers both the explorer and the typed analytical request. The
application includes `create_explorer_router(repository)` and
`install_analytics_errors(app)`; the agent harness calls `execute(request)` with
an `AnalyticalRequest`. The fixture adapter is only for synthetic integration.

The production data adapter implements `AnalyticsRepository.load(start, end)`.
It returns one latest published catalog snapshot, one selected source/feed/price
basis, the calendar sessions through `end`, and selected accepted bars for the
window plus the session immediately preceding its first session when available.
This read must pin a consistent snapshot of the catalog and selected bar revisions. Fetch bars
for all tracked stock IDs in a set-based query; do not issue one query per stock.
For a private five-stock Alpaca validation run, set
`MARKET_EAGLE_PRIVATE_SAMPLE_SNAPSHOT_ID` to the published
`alpaca-sample-v1-...` snapshot ID and select `alpaca/sip/raw` with exchange
`US_EQUITY`. This explicit read-only selection never changes `catalog_current`.
It refuses a missing, unpublished, or non-sample snapshot and labels the result
`private_five_stock_sample`, outside S&P 500 membership.
The service makes exactly one repository call per explorer or typed request and
performs no writes. A slow batch read delays explorer page load and agent turns.

For a stock request selecting only daily-frequency measures and sorting by a
frequency measure, eligibility requires at least one usable daily observation
in the requested window. Missing comparison or final return closes do not
exclude that stock. Its return fields are null, `comparison_session` is null,
and `metric_version` is `daily-frequency-v1`. The observed-day denominator and
requested-session coverage remain visible. Stocks with no usable daily bars are
excluded as `missing_usable_daily_observations`.

Selecting a return-based measure (even when sorting by frequency) uses return
eligibility: both comparison and final closes are required, and the result uses
`return-v1`. The explorer always uses this return rule. The `market` envelope's
eligible and excluded counts follow the measure set used for that request.

The adapter owns the current-day provisional selection rule and must include an
available provisional bar when the requested window contains today. It must not
mix source, feed, or price basis. An unavailable catalog or selected data must
raise a typed `AnalyticsError` or map to one before reaching the route.

`return_rankings_trusted` stays false while the production return price basis
is unresolved. Synthetic fixture values are fictional. The service reports the
selected basis, observation status, provider as-of time, coverage, and excluded
stock IDs for every calculation.

Run the focused checks with `python -m pytest backend/tests/test_analytics.py`.
