"""Bounded reader for FMP's documented current S&P 500 constituent endpoint."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx

ENDPOINT = "https://financialmodelingprep.com/stable/sp500-constituent"
MAX_RESPONSE_BYTES = 2_000_000
MAX_MEMBERS = 700


class FmpRequestError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None):
        super().__init__(f"FMP constituent request returned HTTP {status_code}")
        self.status_code = status_code
        self.retry_after = retry_after


class FmpTransportError(Exception):
    """A network failure whose message omits the credential-bearing request URL."""


@dataclass(frozen=True)
class FmpFetch:
    rows: list[dict]
    fetched_at: datetime
    byte_count: int
    checksum: str
    rate_headers: dict[str, str]


def normalize_constituents(payload: object) -> list[dict]:
    """Validate the published response shape without inventing security identities."""
    if not isinstance(payload, list) or not 0 < len(payload) <= MAX_MEMBERS:
        raise ValueError("FMP response must contain 1 to 700 constituents")
    rows = []
    symbols = set()
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("FMP constituent is not an object")
        symbol = item["symbol"]
        name = item["name"]
        sector = item["sector"]
        if not isinstance(symbol, str) or not re.fullmatch(
            r"[A-Z0-9][A-Z0-9.\-]{0,15}", symbol
        ):
            raise ValueError("FMP constituent has an invalid symbol")
        if symbol in symbols:
            raise ValueError(f"FMP response repeats symbol {symbol}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"FMP constituent {symbol} has no name")
        if not isinstance(sector, str) or not sector.strip():
            raise ValueError(f"FMP constituent {symbol} has no sector")
        sub_sector = item.get("subSector")
        cik = item.get("cik")
        added = item.get("dateFirstAdded")
        if sub_sector is not None and not isinstance(sub_sector, str):
            raise TypeError(f"FMP constituent {symbol} has an invalid subSector")
        if cik is not None and (
            not isinstance(cik, str) or not re.fullmatch(r"\d{1,10}", cik)
        ):
            raise ValueError(f"FMP constituent {symbol} has an invalid CIK")
        if added is not None:
            date.fromisoformat(added)
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "subSector": sub_sector,
                "cik": cik,
                "dateFirstAdded": added,
            }
        )
        symbols.add(symbol)
    return sorted(rows, key=lambda row: row["symbol"])


def checksum_rows(rows: list[dict]) -> str:
    serialized = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def fetch_constituents(client: httpx.Client, api_key: str) -> FmpFetch:
    """Make one authenticated request with a strict response-size limit."""
    if not api_key:
        raise ValueError("FMP_API_KEY is required")
    try:
        with client.stream(
            "GET", ENDPOINT, params={"apikey": api_key}, timeout=20
        ) as response:
            fetched_at = datetime.now(timezone.utc)
            if response.status_code != 200:
                raise FmpRequestError(
                    response.status_code, response.headers.get("Retry-After")
                )
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
                raise ValueError("FMP response exceeds 2 MB")
            chunks = []
            size = 0
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("FMP response exceeds 2 MB")
                chunks.append(chunk)
            rate_headers = {
                name: value
                for name, value in response.headers.items()
                if name.lower()
                in {"x-ratelimit-limit", "x-ratelimit-remaining", "retry-after"}
            }
    except httpx.RequestError:
        raise FmpTransportError(
            "FMP constituent request failed before a usable response"
        ) from None
    rows = normalize_constituents(json.loads(b"".join(chunks)))
    return FmpFetch(rows, fetched_at, size, checksum_rows(rows), rate_headers)
