# First interaction proposal

Status: accepted as the first usable interaction. The specific visual styling and later free-text placement remain design details.

## Visual and interaction direction

A calm research workbench: dense, readable market data on a neutral surface, with one accent for the selected sector. The first screen starts with the working data, not a marketing hero or a grid of decorative cards.

The interface has three jobs: establish the selected date window and data freshness, compare sectors, and inspect the stocks behind one sector. Range changes update the comparison in place; selecting a sector changes the detail area; chart tooltips, if added, reveal exact dates and values without crowding the table.

## Proposed first screen

```text
Market research                                      Data as of: [time]
Window: [start date] → [end date]  [1M] [3M] [1Y]   Source: [provider]

MARKET RETURN (equal weight): +x.x%    ELIGIBLE STOCKS: n / tracked

SECTORS                                   SELECTED SECTOR: [name]
Rank  Sector       Up/Eligible  Breadth   Return  vs Market
 1    [sector]       nn / nn      xx%      +x.x%      +x.x pp
 2    [sector]       nn / nn      xx%      +x.x%      -x.x pp
 ...  ...

                                          LEADING STOCKS IN [SECTOR]
                                          Stock   Return  Sector  Market  Excess
                                          [AAA]   +x.x%   +x.x%   +x.x%  +x.x pp
                                          [BBB]   +x.x%   +x.x%   +x.x%  +x.x pp

Calculation: [resolved trading dates] · [price basis] · [coverage] · [source/data as-of] · [current sector catalog as-of]
```

The left table ranks by Sector Breadth. Sector Return and its difference from Market Return are context, not the ranking criterion. Selecting a sector updates the right side. The stock table ranks by Stock Excess Return and still shows the stock, sector, and market returns. The evidence line remains visible in both views. A small time-series chart can be added after its daily aggregation semantics are defined; the table works without it.

## Proposed click path

1. The trader chooses any start and end dates or uses a shortcut.
2. The sector list recalculates for that window and shows coverage and data as-of time.
3. The trader selects a sector to inspect leading stocks and compare stock, sector, and market returns.
4. The trader changes the window to test whether the same sector or stocks continue to lead.

## Free-text phase

Add a question input to the same workspace after the calculation layer and explorer are usable. For example: “Which sector had the broadest advance last quarter, and which three stocks beat its average most?” The agent interprets flexible questions into validated analytical requests, may run several read-only analyses when useful, and presents answers with relevant evidence in a collapsed section that can be opened. It should use one query when one query suffices. It makes and states reasonable assumptions; it asks when no defensible interpretation exists. Unsupported requests get an explicit response, not an invented calculation. The product supports multiple conversations with context within each; a new conversation starts fresh. Before authentication all app visitors can view and permanently delete all conversations through an explicit action, with per-user access later.

PostgreSQL is the accepted first analytical engine. The agent query boundary and deployment method remain under review. This proposal defines the user interaction, not those remaining technology choices.
