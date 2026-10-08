# Analysis scope

## Intended research job

Traders should be able to identify trends occurring across the market and drill into them. The product is aimed at swing and long-term analysis rather than intraday trading decisions. The first usable slice may be thinner than the full list below.

## First analytical slice

- Rank sectors by **breadth**: the percentage of tracked stocks in each sector whose return was positive over the requested time window.
- Within a sector, show each stock's own return and rank stocks by its excess return over the **equal-weight average return** of eligible tracked stocks in that sector. Express excess return in percentage points.
- Accept arbitrary start and end dates within the retained history. Common periods may be UI shortcuts, but the calculation must use the same reusable time-window aggregation layer.
- Include the first requested date's trading change: compare the close immediately before the first included trading date with the close on the final included trading date. Resolve non-trading date inputs to trading sessions.
- Exclude stocks without both comparison prices from the calculation and show the eligible stock count beside sector results.
- Group stocks by their current sector in the latest published catalog snapshot when the query runs, including for past price windows. Show that catalog's as-of date so users do not mistake the grouping for historical sector membership.

For an eligible stock, "rose" means its period return is strictly greater than zero. Sector Breadth is the number that rose divided by the eligible stock count. The price adjustment basis remains open. In particular, whether Stock Return accounts for splits was explicitly deferred and is tracked in [GitHub issue #3](https://github.com/maorts14/market-eagle/issues/3); the formula below does not settle that choice. If the requested range includes today, use an available in-progress daily bar and label the result provisional with its provider as-of time. If a stock lacks a usable current-day bar, show that missing coverage rather than silently treating it as final.

For each eligible stock, **Stock Return = (final comparison close ÷ preceding close) − 1**. Sector Breadth = eligible stocks with Stock Return > 0 ÷ eligible stocks in that current sector. Sector Return = arithmetic mean of eligible Stock Returns in that sector. Market Return = arithmetic mean of eligible Stock Returns across the tracked universe. Stock Excess Return = Stock Return − Sector Return, displayed in percentage points. For example, a 10% stock return against a 6% sector return is +4 percentage points of excess return. A stock needs both closes to enter any of these averages.

## Evidence requested by the user

- For a stock leader, show the stock's return beside the equal-weight sector and market returns over the same window.
- For a sector leader, keep Sector Breadth as the ranking measure and show Sector Return beside Market Return as context.
- The stock leaderboard still uses excess return over the sector's equal-weight average return, as previously agreed.
- Every answer shows the resolved date window, eligible stock counts, data source, and data as-of time.

Market Return means the equal-weight average return of eligible tracked S&P 500 stocks over the same window. It is a comparison measure, not an official S&P 500 index return. The displayed eligible count makes this distinction inspectable.

## Later candidate questions and capabilities

- Which stocks led their sector for the longest time?
- Which stocks or shares show contemporaneous or delayed correlation?
- Which indicators help explain or inspect a trend?

These are candidate capabilities, not accepted first-release requirements. "Longest," "correlation," "delay," and "indicator" need exact definitions before implementation. A measured association must not be described as causation or a forecast.

## Remaining calculation decisions

The first interaction is the sector/stock explorer in [interaction-proposal.md](interaction-proposal.md). Price adjustment basis and the storage/selection mechanics for in-progress bars remain open. An available in-progress bar participates in rankings whose requested range includes today. Requested aggregates are calculated from selected observations; there is no table of every possible result.
