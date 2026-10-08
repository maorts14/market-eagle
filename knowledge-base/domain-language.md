# Stock analysis language

This glossary contains settled business terms for the rebuild. Open meanings are tracked in [decision-tree.md](decision-tree.md).

## Language

**Stock**:
A listed equity security whose daily market observations the product tracks. The initial universe is drawn from the S&P 500.
_Avoid_: Instrument, when referring specifically to a stock.

**Ticker**:
A market symbol used for a stock during a stated period. A ticker can change, so it is not the stock's enduring identity.

**Current Catalog Snapshot**:
A dated, published list of the stocks currently tracked and each one's current sector. A research calculation uses one snapshot throughout. “Current” refers to when the catalog was published, not to the dates of the price window.

**Daily Bar**:
One stock's open, high, low, close, and volume observations for a trading date.
_Avoid_: Daily performance, when referring to the underlying observation rather than a calculated return.

**Observed Usable Day**:
A trading date in the requested range for which the selected source, feed, and price basis provide an accepted Daily Bar with the values needed for the requested daily condition. Relative day-frequency calculations use the number of these days as their denominator. A missing day is not counted as either satisfying or failing the condition; the result also shows how much of the requested range was observed.

**Provisional Daily Bar**:
The current trading date's Daily Bar while the provider still updates it, including possible after-hours volume changes. Its values can change at each refresh until the provider's finality policy is satisfied.
_Avoid_: Hourly Bar, because the initial product refreshes one whole-day candle rather than storing separate one-hour candles.

**Daily Dollar Trading Volume**:
The dollar value of shares traded for one stock on one trading date. This differs from Daily Bar share volume. The current rule uses provider-reported traded notional when available; otherwise estimate share volume × daily VWAP, falling back to share volume × daily close if VWAP is unavailable. Label an estimated value and disclose its price input and formula. Review the proxy after provider verification in [GitHub issue #4](https://github.com/maorts14/market-eagle/issues/4).

**Price Basis**:
The rule used to represent historical prices in a return calculation, including how splits and potentially dividends are handled. The first basis is not selected yet. All stocks in one ranking must use the same basis.

**Market-Data Feed**:
The provider's specific stream or dataset from which a Daily Bar came. Delayed SIP and IEX are different feeds even if delivered by the same provider.

**Collection Run**:
One attempt to obtain or repair a defined set of catalog rows or market observations. A run can finish processing while still leaving coverage gaps.

**Coverage Gap**:
An expected stock/trading-session observation that is missing or rejected. A date before a stock was listed is not a provider coverage gap.

**Sector**:
A sourced classification associated with a stock for a stated effective period. Official GICS is preferred if its usage terms fit. First-release rankings use the current sector from the latest published catalog snapshot, even for historical price windows; the result shows the catalog as-of date.
_Avoid_: Sector ETF, when referring to the stock's classification.

**Sector Breadth**:
The percentage of eligible tracked stocks in a sector whose return was greater than zero over a selected time window. The first analytical slice ranks sectors by this measure.
_Avoid_: Sector Return, which is a distinct measure needed for stock outperformance comparisons.

**Sector Return**:
The equal-weight average period return of eligible tracked stocks in a sector. It is the comparison baseline for Stock Excess Return, not the sector leadership ranking measure.

**Market Return**:
The equal-weight average period return of eligible tracked stocks across the current S&P 500 universe. It is a product comparison measure, not the official S&P 500 index return.

**Stock Excess Return**:
A stock's period return minus its Sector Return for the same time window, measured in percentage points.

**Design Partner**:
A trader who works with the creator to evaluate and shape the product before broader release.

**Agent Conversation**:
A separate sequence of user questions, agent actions, and answers. Follow-up questions can use context from earlier turns in that same conversation. A new conversation starts fresh. The product can contain multiple conversations; before authentication, all app visitors can view and explicitly delete them.

**Agent Turn**:
One user question and the agent's response within an Agent Conversation, including any read-only analytical steps used to prepare the answer.

**Analytical Request**:
A structured description of what to measure, over which stocks and dates, with which conditions, grouping, and ranking. It describes the intended calculation without database query syntax.

## Legacy terminology

The former root glossary described a Sector as a grouping represented by a sector ETF and included Relationship, Analysis Run, Brief, and Research Session. Those terms describe the reference prototype. Agent Conversation is the accepted term for the rebuilt product's conversation container.
