"""Read-only Alpaca entitlement probe; emits summaries and never emits credentials."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def credentials(path: Path) -> tuple[str, str]:
    values = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
                  if line and not line.startswith("#") and "=" in line)
    return values["ALPACA_API_KEY_ID"], values["ALPACA_API_SECRET_KEY"]


def fetch(path: str, params: dict[str, str], key_id: str, secret: str) -> tuple[dict, dict]:
    url = "https://data.alpaca.markets" + path + "?" + urlencode(params)
    request = Request(url, headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            metadata = {"status": response.status, "bytes": len(raw),
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                        "remaining": response.headers.get("X-Ratelimit-Remaining")}
            return json.loads(raw), metadata
    except HTTPError as error:
        body = error.read(512)
        try:
            message = json.loads(body).get("message", "HTTP error")
        except (ValueError, UnicodeDecodeError):
            message = "HTTP error"
        return {}, {"status": error.code, "latency_ms": round((time.perf_counter() - started) * 1000),
                    "message": message}
    except URLError as error:
        return {}, {"status": "network_error", "message": str(error.reason)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path("infra/.env"))
    args = parser.parse_args()
    key_id, secret = credentials(args.env)
    now = datetime.now(timezone.utc)
    symbols = "AAPL,MSFT,AMZN,GOOG,JPM"
    end = now - timedelta(minutes=20)
    historical, historical_meta = fetch("/v2/stocks/bars", {
        "symbols": symbols, "timeframe": "1Day", "feed": "sip", "adjustment": "raw",
        "start": (now - timedelta(days=365 * 5 + 3)).date().isoformat(),
        "end": end.isoformat().replace("+00:00", "Z"), "limit": "10000",
    }, key_id, secret)
    bars = historical.get("bars", {})
    print(json.dumps({"probe": "five_year_history", **historical_meta,
                      "counts": {symbol: len(bars.get(symbol, [])) for symbol in symbols.split(",")},
                      "next_page": bool(historical.get("next_page_token"))}))
    today, today_meta = fetch("/v2/stocks/bars", {
        "symbols": symbols, "timeframe": "1Day", "feed": "sip", "adjustment": "raw",
        "start": now.date().isoformat(), "end": end.isoformat().replace("+00:00", "Z"),
        "limit": "10000",
    }, key_id, secret)
    print(json.dumps({"probe": "today_historical", **today_meta,
                      "symbols_with_daily_bar": sorted(today.get("bars", {})),
                      "bar_fields": sorted({key for series in today.get("bars", {}).values()
                                            for bar in series for key in bar})}))
    snapshots, snapshot_meta = fetch("/v2/stocks/snapshots", {
        "symbols": symbols, "feed": "delayed_sip",
    }, key_id, secret)
    print(json.dumps({"probe": "delayed_snapshots", **snapshot_meta,
                      "symbols": sorted(symbol for symbol in snapshots if symbol in symbols.split(",")),
                      "daily_bar_count": sum(bool(item.get("dailyBar")) for item in snapshots.values()
                                             if isinstance(item, dict))}))
    if today_meta["status"] == 200 and snapshot_meta["status"] == 200:
        comparisons = {}
        for symbol in symbols.split(","):
            history_bar = (today.get("bars", {}).get(symbol) or [None])[-1]
            snapshot = snapshots.get(symbol, {})
            snapshot_bar = snapshot.get("dailyBar")
            comparisons[symbol] = {
                "history_time": history_bar.get("t") if history_bar else None,
                "snapshot_time": snapshot_bar.get("t") if snapshot_bar else None,
                "same_volume": (history_bar or {}).get("v") == (snapshot_bar or {}).get("v"),
                "same_close": (history_bar or {}).get("c") == (snapshot_bar or {}).get("c"),
                "latest_trade_time": (snapshot.get("latestTrade") or {}).get("t"),
            }
        print(json.dumps({"probe": "today_comparison", "observed_at": now.isoformat(),
                          "comparisons": comparisons}))


if __name__ == "__main__":
    main()
