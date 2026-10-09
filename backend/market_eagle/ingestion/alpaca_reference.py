"""Bounded, read-only Alpaca asset and US equity calendar probes."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

ASSET_URL = "https://paper-api.alpaca.markets/v2/assets"
CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
ASSET_LIMIT_BYTES = 16_000_000
CALENDAR_LIMIT_BYTES = 1_000_000
MAX_ASSETS = 30_000
MAX_SESSIONS = 2_000
NEW_YORK = ZoneInfo("America/New_York")


class AlpacaReferenceError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"Alpaca reference request returned HTTP {status_code}")
        self.status_code = status_code


class AlpacaReferenceTransportError(Exception):
    """Network failure with no credential-bearing request details."""


def _read_json(
    client: httpx.Client, url: str, params: dict, headers: dict, limit: int
) -> object:
    try:
        with client.stream(
            "GET", url, params=params, headers=headers, timeout=30
        ) as response:
            if response.status_code != 200:
                raise AlpacaReferenceError(response.status_code)
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise ValueError("Alpaca reference response exceeds its byte limit")
            chunks = []
            size = 0
            for chunk in response.iter_bytes(chunk_size=64 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Alpaca reference response exceeds its byte limit")
                chunks.append(chunk)
    except httpx.RequestError:
        raise AlpacaReferenceTransportError("Alpaca reference request failed") from None
    return json.loads(b"".join(chunks))


def fetch_assets(client: httpx.Client, key_id: str, secret: str) -> list[dict]:
    if not key_id or not secret:
        raise ValueError("Alpaca paper credentials are required")
    payload = _read_json(
        client,
        ASSET_URL,
        {"status": "active", "asset_class": "us_equity"},
        {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
        ASSET_LIMIT_BYTES,
    )
    if not isinstance(payload, list) or not 0 < len(payload) <= MAX_ASSETS:
        raise ValueError("Alpaca assets response has an invalid row count")
    rows = []
    seen_ids = set()
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("Alpaca asset is not an object")
        asset_id = str(UUID(item["id"]))
        symbol, exchange, name = item["symbol"], item["exchange"], item["name"]
        if not all(
            isinstance(value, str) and value for value in (symbol, exchange, name)
        ):
            raise ValueError("Alpaca asset has an invalid symbol, exchange, or name")
        if item["class"] != "us_equity" or item["status"] != "active":
            raise ValueError(
                "Alpaca assets response contains a non-active or non-equity row"
            )
        if asset_id in seen_ids:
            raise ValueError("Alpaca assets response repeats an asset ID")
        rows.append(
            {
                "id": asset_id,
                "symbol": symbol,
                "exchange": exchange,
                "name": name,
                "status": item["status"],
                "class": item["class"],
            }
        )
        seen_ids.add(asset_id)
    return sorted(rows, key=lambda row: (row["symbol"], row["exchange"], row["id"]))


def fetch_calendar(
    client: httpx.Client,
    key_id: str,
    secret: str,
    requested_start: date,
    requested_end: date,
) -> list[dict]:
    if not key_id or not secret or requested_start > requested_end:
        raise ValueError(
            "Alpaca paper credentials and a valid date window are required"
        )
    if (requested_end - requested_start).days > 2_192:
        raise ValueError("calendar request exceeds six years")
    payload = _read_json(
        client,
        CALENDAR_URL,
        {
            "start": (requested_start - timedelta(days=10)).isoformat(),
            "end": requested_end.isoformat(),
            "date_type": "TRADING",
        },
        {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
        CALENDAR_LIMIT_BYTES,
    )
    if not isinstance(payload, list) or not 0 < len(payload) <= MAX_SESSIONS:
        raise ValueError("Alpaca calendar response has an invalid session count")
    sessions = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("Alpaca calendar session is not an object")
        session_date = date.fromisoformat(item["date"])
        opened = datetime.combine(
            session_date, time.fromisoformat(item["open"]), NEW_YORK
        )
        closed = datetime.combine(
            session_date, time.fromisoformat(item["close"]), NEW_YORK
        )
        if session_date in seen or opened >= closed:
            raise ValueError("Alpaca calendar contains a duplicate or invalid session")
        duration = closed - opened
        sessions.append(
            {
                "date": session_date.isoformat(),
                "open_at": opened.astimezone(timezone.utc).isoformat(),
                "close_at": closed.astimezone(timezone.utc).isoformat(),
                "type": "half_day"
                if duration < timedelta(hours=6, minutes=30)
                else "regular",
            }
        )
        seen.add(session_date)
    return sorted(sessions, key=lambda row: row["date"])
