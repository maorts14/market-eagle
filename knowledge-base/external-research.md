# External research

Checked on 2026-10-05 and 2026-10-06. These are constraints and options, not provider selections.

## S&P 500 membership and sectors

- [S&P U.S. Indices Methodology](https://www.spglobal.com/spdji/en/methodology/article/sp-us-indices-methodology/) describes the S&P 500 as 500 constituent companies. It also distinguishes company membership from individual listings and refers to GICS sector classification. The proposed [data model](data-model.md) gives each tracked share line its own stable stock ID.
- [S&P DJI data and index licensing](https://www.spglobal.com/spdji/en/about-us/data-index-licensing/) offers constituent and corporate-action data packages and licenses index data for defined uses. Before trader-facing distribution, the permitted source and usage terms need to be chosen explicitly.

## Daily bars and adjustments

- [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/) distinguishes raw daily OHLCV from its premium daily-adjusted endpoint, which adds adjusted close, split events, and dividends. This illustrates why “daily OHLCV” alone does not settle how returns across splits and dividends will be calculated.

## Free-tier feasibility for the new scope

- [Massive pricing](https://massive.com/pricing) lists two years of history and end-of-day access for its $0 Stocks Basic tier. Five-year history and delayed intraday data are listed on paid tiers.
- [FMP pricing](https://site.financialmodelingprep.com/developer/docs/pricing) lists 250 calls per day and end-of-day history on its free Basic tier; its page states that data display or redistribution needs a separate agreement.
- [Alpha Vantage support](https://www.alphavantage.co/support/) lists 25 requests per day on the standard free API and says US real-time and 15-minute-delayed market data is premium.
- These examples do not establish that no suitable free source exists. They show that a five-year, roughly 500-security, hourly intraday requirement cannot be assumed feasible at $0. The provider investigation is tracked in [research data api](https://github.com/maorts14/market-eagle/issues/2).
- A broader provider comparison on 2026-10-06 identified Alpaca Free as the best documented private-development candidate, with an authenticated probe and usage-rights review still required. See [market-data-api-evaluation.md](market-data-api-evaluation.md).

## Questions this research creates

- What market-data and index-data licensing is acceptable for the design-partner and later commercial stages?
- Which source can meet the hourly and five-year requirements at the stated development budget, or what staged compromise should be made explicit?
