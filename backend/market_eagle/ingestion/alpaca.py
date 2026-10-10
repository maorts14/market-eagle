"""Bounded historical Alpaca page reader; account entitlement remains unverified."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta, timezone

import httpx


class AlpacaRequestError(Exception):
    def __init__(self, status_code: int, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def historical_pages(
    client: httpx.Client,
    *,
    key_id: str,
    secret_key: str,
    symbols: list[str],
    start: date,
    end: date,
    feed: str,
    adjustment: str,
    max_pages: int = 20,
    end_at: datetime | None = None,
    asof: date | None = None,
    before_request: Callable[[], None] | None = None,
) -> Iterator[tuple[dict, datetime]]:
    """Read up to five symbols with 10,000 bars/page and follow every token."""
    if not 1 <= len(symbols) <= 5 or start > end or max_pages < 1:
        raise ValueError("invalid bounded historical request")
    if feed not in ("sip", "iex") or adjustment not in (
        "raw",
        "split",
        "dividend",
        "spin-off",
        "all",
    ):
        raise ValueError("unsupported feed or adjustment")
    # An exact UTC cutoff excludes the next session from SIP entitlement checks.
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start.isoformat(),
        "end": end_at.isoformat()
        if end_at
        else datetime.combine(
            end + timedelta(days=1), time.min, timezone.utc
        ).isoformat(),
        "limit": 10000,
        "feed": feed,
        "adjustment": adjustment,
        "sort": "asc",
    }
    if asof is not None:
        params["asof"] = asof.isoformat()
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
    seen_tokens: set[str] = set()
    for _ in range(max_pages):
        if before_request is not None:
            before_request()
        response = client.get(
            "https://data.alpaca.markets/v2/stocks/bars",
            params=params,
            headers=headers,
            timeout=30,
        )
        observed_at = datetime.now(timezone.utc)
        if response.status_code != 200:
            raise AlpacaRequestError(
                response.status_code,
                f"Alpaca historical bars returned HTTP {response.status_code}",
                response.headers.get("Retry-After"),
            )
        payload = response.json()
        if not isinstance(payload.get("bars"), dict):
            raise TypeError("Alpaca bars response has no bars object")
        yield payload, observed_at
        token = payload.get("next_page_token")
        if not token:
            return
        if token in seen_tokens:
            raise ValueError("Alpaca repeated a page token")
        seen_tokens.add(token)
        params["page_token"] = token
    raise ValueError("Alpaca page count exceeded the configured bound")


def page_rows(
    payload: dict,
    observed_at: datetime,
    source: str,
    feed: str,
    basis: str,
    status: str = "historical",
) -> list[dict[str, str]]:
    """Map documented daily-bar fields; observed_at is fetch time, not provider finality."""
    rows = []
    for ticker, bars in payload["bars"].items():
        for bar in bars:
            rows.append(
                {
                    "ticker": ticker,
                    "session_date": bar["t"][:10],
                    "open": str(bar["o"]),
                    "high": str(bar["h"]),
                    "low": str(bar["l"]),
                    "close": str(bar["c"]),
                    "volume": str(bar["v"]),
                    "vwap": str(bar["vw"]) if bar.get("vw") is not None else "",
                    "traded_notional": "",
                    "source": source,
                    "feed": feed,
                    "price_basis": basis,
                    "provider_as_of": observed_at.isoformat(),
                    "as_of_kind": "fetched",
                    "status": status,
                }
            )
    return rows
