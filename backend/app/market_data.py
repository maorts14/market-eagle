from datetime import date, timedelta
import csv
from io import StringIO
import math
import httpx


def fetch_daily_bars(symbol: str, start: date, end: date, mode: str) -> list[dict]:
    if mode == "demo":
        return _demo_bars(symbol, start, end)
    response = httpx.get(f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d", timeout=20)
    response.raise_for_status()
    rows = []
    for row in csv.DictReader(StringIO(response.text)):
        trading_date = date.fromisoformat(row["Date"])
        if start <= trading_date <= end and row["Close"] not in {"", "N/D"}:
            rows.append({
                "trading_date": trading_date, "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]), "volume": int(float(row["Volume"] or 0)), "source": "stooq",
            })
    return rows


def _demo_bars(symbol: str, start: date, end: date) -> list[dict]:
    seed = sum(ord(character) for character in symbol)
    price = 55 + seed % 85
    rows: list[dict] = []
    cursor = start
    index = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            market_wave = math.sin(index / 11) * 0.006
            sector_wave = math.sin((index + seed) / (7 + seed % 5)) * 0.011
            daily_return = market_wave + sector_wave + ((seed % 13) - 6) / 10000
            opening = price
            price = round(price * (1 + daily_return), 2)
            rows.append({"trading_date": cursor, "open": opening, "high": round(max(opening, price) * 1.008, 2),
                         "low": round(min(opening, price) * 0.992, 2), "close": price,
                         "volume": 1_200_000 + (seed * 471 + index * 3001) % 8_000_000, "source": "demo"})
            index += 1
        cursor += timedelta(days=1)
    return rows
