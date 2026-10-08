"""Produce independent expected facts for two explorer windows and the agent case."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path


HERE = Path(__file__).resolve().parent


def as_number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000000000001")))


def main() -> None:
    with (HERE / "bars.csv").open(newline="", encoding="utf-8") as stream:
        bars = list(csv.DictReader(stream))
    with (HERE / "catalog.csv").open(newline="", encoding="utf-8") as stream:
        catalog = list(csv.DictReader(stream))
    by_stock: dict[str, dict[date, dict[str, str]]] = defaultdict(dict)
    for bar in bars:
        by_stock[bar["ticker"]][date.fromisoformat(bar["session_date"])] = bar
    sessions = sorted({date.fromisoformat(bar["session_date"]) for bar in bars})

    windows = {}
    for label, first, last in (
        ("full_2025", date(2025, 1, 1), date(2025, 12, 31)),
        ("december_2025", date(2025, 12, 1), date(2025, 12, 31)),
    ):
        included = [session for session in sessions if first <= session <= last]
        previous = max(session for session in sessions if session < included[0])
        ending = included[-1]
        sector_returns: dict[str, list[Decimal]] = defaultdict(list)
        all_returns: list[Decimal] = []
        stocks = {}
        for member in catalog:
            ticker = member["ticker"]
            prior = by_stock[ticker].get(previous)
            final = by_stock[ticker].get(ending)
            if prior is None or final is None:
                continue
            result = Decimal(final["close"]) / Decimal(prior["close"]) - 1
            sector_returns[member["sector_code"]].append(result)
            all_returns.append(result)
            stocks[ticker] = {"return": as_number(result), "sector_code": member["sector_code"]}
        market_return = sum(all_returns) / len(all_returns)
        sectors = {
            code: {
                "eligible_count": len(values),
                "up_count": sum(value > 0 for value in values),
                "breadth": as_number(Decimal(sum(value > 0 for value in values)) / len(values)),
                "return": as_number(sum(values) / len(values)),
            }
            for code, values in sorted(sector_returns.items())
        }
        windows[label] = {
            "first_session": included[0].isoformat(),
            "last_session": ending.isoformat(),
            "comparison_session": previous.isoformat(),
            "tracked_count": len(catalog),
            "eligible_count": len(stocks),
            "market_return": as_number(market_return),
            "sectors": sectors,
            "stocks": stocks,
        }

    december = [session for session in sessions if date(2025, 12, 1) <= session <= date(2025, 12, 31)]
    volume_candidates = []
    for member in catalog:
        ticker = member["ticker"]
        observed = [by_stock[ticker][session] for session in december if session in by_stock[ticker]]
        qualifying = 0
        inputs = set()
        for bar in observed:
            if bar["traded_notional"]:
                dollar_volume = Decimal(bar["traded_notional"])
                inputs.add("reported_notional")
            elif bar["vwap"]:
                dollar_volume = Decimal(bar["volume"]) * Decimal(bar["vwap"])
                inputs.add("volume_x_vwap_estimate")
            else:
                dollar_volume = Decimal(bar["volume"]) * Decimal(bar["close"])
                inputs.add("volume_x_close_estimate")
            qualifying += dollar_volume > Decimal("100000")
        fraction = Decimal(qualifying) / len(observed) if observed else Decimal(0)
        if fraction >= Decimal("0.80") and ticker in windows["december_2025"]["stocks"]:
            volume_candidates.append(
                {
                    "ticker": ticker,
                    "qualifying_days": qualifying,
                    "observed_usable_days": len(observed),
                    "requested_sessions": len(december),
                    "fraction": as_number(fraction),
                    "return": windows["december_2025"]["stocks"][ticker]["return"],
                    "dollar_volume_inputs": sorted(inputs),
                }
            )
    volume_candidates.sort(key=lambda row: (-row["return"], row["ticker"]))
    expected = {
        "note": "Fictional data. Fractions are rounded to 12 decimal places for fixture comparison.",
        "explorer": windows,
        "gain_plus_volume_last_month_as_of_2026_01_08": {
            "requested_start": "2025-12-01",
            "requested_end": "2025-12-31",
            "threshold_usd": 100000,
            "required_fraction": 0.8,
            "qualifying_ranked_candidates": volume_candidates,
            "winner": volume_candidates[0] if volume_candidates else None,
        },
    }
    (HERE / "expected-results.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
