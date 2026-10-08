"""Generate a deterministic fictional market history for integration tests.

Sessions are weekdays, not an exchange holiday calendar. No external packages or
market-data service are used. Run from any directory with ``python generate.py``.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIRST = date(2023, 12, 29)  # comparison close before the first selectable session
LAST = date(2025, 12, 31)
STOCKS = (
    ("stock-alfa", "ALFA", "Alpha Fiction", "TECH", "Technology", "2023-12-29", "100", "0.07", "reported"),
    ("stock-beta", "BETA", "Beta Fiction", "TECH", "Technology", "2023-12-29", "80", "-0.02", "vwap"),
    ("stock-gamm", "GAMM", "Gamma Fiction", "IND", "Industrials", "2023-12-29", "60", "0.04", "close"),
    ("stock-delt", "DELT", "Delta Fiction", "IND", "Industrials", "2023-12-29", "40", "-0.04", "vwap"),
    ("stock-epsi", "EPSI", "Epsilon Fiction", "IND", "Industrials", "2025-01-02", "30", "0.10", "reported"),
)
CENT = Decimal("0.01")


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def write_csv(name: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with (HERE / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    sessions: list[date] = []
    day = FIRST
    while day <= LAST:
        if day.weekday() < 5:
            sessions.append(day)
        day += timedelta(days=1)

    write_csv("sessions.csv", ["session_date"], [{"session_date": day.isoformat()} for day in sessions])
    write_csv(
        "catalog.csv",
        ["snapshot_id", "catalog_as_of", "published_at", "stock_id", "ticker", "name", "sector_code", "sector_name", "listed_from"],
        [
            {
                "snapshot_id": "synthetic-catalog-v1",
                "catalog_as_of": "2025-12-31",
                "published_at": "2026-01-01T00:00:00Z",
                "stock_id": stock_id,
                "ticker": ticker,
                "name": name,
                "sector_code": sector_code,
                "sector_name": sector_name,
                "listed_from": listed_from,
            }
            for stock_id, ticker, name, sector_code, sector_name, listed_from, *_ in STOCKS
        ],
    )

    rows: list[dict[str, str]] = []
    for stock_position, (stock_id, ticker, _name, _sector_code, _sector_name, listed_from, base, drift, volume_kind) in enumerate(STOCKS):
        active_index = 0
        for session in sessions:
            if session < date.fromisoformat(listed_from):
                continue
            # DELT lacks the final endpoint; GAMM lacks occasional interior days.
            # This makes endpoint eligibility and observed-day coverage differ.
            if ticker == "DELT" and session == LAST:
                continue
            if ticker == "GAMM" and session.year == 2025 and session.day == 15:
                continue
            close = Decimal(base) + Decimal(drift) * active_index
            opening = close - Decimal("0.20")
            high = close + Decimal("0.50")
            low = opening - Decimal("0.50")
            volume = 2400 + (active_index % 17) * 31 if ticker == "EPSI" else 850 + (active_index % 17) * 31 + stock_position * 67
            vwap = close - Decimal("0.05")
            reported = Decimal(volume) * vwap if volume_kind == "reported" else None
            rows.append(
                {
                    "stock_id": stock_id,
                    "ticker": ticker,
                    "session_date": session.isoformat(),
                    "open": money(opening),
                    "high": money(high),
                    "low": money(low),
                    "close": money(close),
                    "volume": str(volume),
                    "vwap": money(vwap) if volume_kind != "close" else "",
                    "traded_notional": money(reported) if reported is not None else "",
                    "source": "synthetic-v1",
                    "feed": "fictional",
                    "price_basis": "synthetic_raw",
                    "provider_as_of": datetime.combine(session, datetime.min.time(), timezone.utc).replace(hour=23).isoformat().replace("+00:00", "Z"),
                    "status": "historical",
                }
            )
            active_index += 1

    write_csv(
        "bars.csv",
        ["stock_id", "ticker", "session_date", "open", "high", "low", "close", "volume", "vwap", "traded_notional", "source", "feed", "price_basis", "provider_as_of", "status"],
        rows,
    )
    (HERE / "manifest.json").write_text(
        json.dumps(
            {
                "fixture_version": 1,
                "fictional": True,
                "calendar": "weekdays-only; not an exchange calendar",
                "comparison_session": FIRST.isoformat(),
                "first_selectable_session": sessions[1].isoformat(),
                "last_session": LAST.isoformat(),
                "session_count": len(sessions),
                "stock_count": len(STOCKS),
                "bar_count": len(rows),
                "source": "synthetic-v1",
                "feed": "fictional",
                "price_basis": "synthetic_raw",
                "reference_date_for_last_month": "2026-01-08",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
