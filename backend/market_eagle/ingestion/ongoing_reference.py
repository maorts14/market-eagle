"""Maintain reviewed session coverage and today's Alpaca asset check."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import psycopg

from .alpaca_preparation import CALENDAR_EXCHANGE
from .ongoing_collection import _approved_reference_context

NEW_YORK = ZoneInfo("America/New_York")
CALENDAR_SOURCE = "alpaca-trading-calendar"


def _checked_on(checked_at: datetime) -> date:
    if checked_at.utcoffset() is None:
        raise ValueError("reference check time must be timezone aware")
    return checked_at.astimezone(NEW_YORK).date()


def validate_reference_approval(
    conn: psycopg.Connection, approval_id: str, checked_at: datetime
) -> None:
    """Check catalog, rights, and mappings before any reference provider call."""
    with conn.cursor() as cur:
        _approved_reference_context(cur, approval_id, _checked_on(checked_at))


def maintain_ongoing_reference(
    conn: psycopg.Connection,
    *,
    approval_id: str,
    coverage_start: date,
    coverage_end: date,
    checked_at: datetime,
    assets: list[dict],
    sessions: list[dict],
) -> dict:
    """Atomically accept unchanged assets and calendar, then record coverage."""
    checked_on = _checked_on(checked_at)
    if (
        coverage_start > checked_on
        or checked_on > coverage_end
        or (coverage_end - coverage_start).days > 31
    ):
        raise ValueError("reference calendar coverage must include the check date")
    assets_by_id = {row["id"]: row for row in assets}
    if len(assets_by_id) != len(assets):
        raise ValueError("Alpaca asset reference repeats an asset ID")
    incoming = {}
    for row in sessions:
        session_date = date.fromisoformat(row["date"])
        if not coverage_start <= session_date <= coverage_end:
            continue
        opened = datetime.fromisoformat(row["open_at"])
        closed = datetime.fromisoformat(row["close_at"])
        if (
            opened.utcoffset() is None
            or closed.utcoffset() is None
            or opened >= closed
            or opened.astimezone(NEW_YORK).date() != session_date
            or closed.astimezone(NEW_YORK).date() != session_date
            or row["type"] not in ("regular", "half_day")
            or session_date in incoming
        ):
            raise ValueError("Alpaca calendar has a conflicting session")
        incoming[session_date] = (
            opened.astimezone(timezone.utc),
            closed.astimezone(timezone.utc),
            row["type"],
            CALENDAR_SOURCE,
        )
    if not incoming:
        raise ValueError("Alpaca calendar lacks sessions inside reviewed coverage")
    with conn.transaction(), conn.cursor() as cur:
        preparation_id, snapshot_id = _approved_reference_context(
            cur, approval_id, checked_on
        )
        cur.execute(
            "SELECT a.asset_id, a.symbol, a.exchange FROM alpaca_alias_approval a "
            "JOIN universe_member m ON m.snapshot_id = %s AND m.stock_id = a.stock_id "
            "WHERE a.preparation_id = %s",
            (snapshot_id, preparation_id),
        )
        mappings = cur.fetchall()
        for asset_id, symbol, exchange in mappings:
            current = assets_by_id.get(str(asset_id))
            if current is None or (
                current["symbol"],
                current["exchange"],
                current["status"],
                current["class"],
            ) != (symbol, exchange, "active", "us_equity"):
                raise ValueError("current Alpaca asset identity differs from approval")
        cur.execute(
            "SELECT session_date, open_at, close_at, session_type, calendar_source "
            "FROM trading_session WHERE exchange = %s "
            "AND session_date BETWEEN %s AND %s",
            (CALENDAR_EXCHANGE, coverage_start, coverage_end),
        )
        existing = {row[0]: row[1:] for row in cur.fetchall()}
        if any(incoming.get(day) != stored for day, stored in existing.items()):
            raise ValueError(
                "stored US equity calendar conflicts with Alpaca reference"
            )
        new_sessions = [
            (CALENDAR_EXCHANGE, day, values[2], values[0], values[1], values[3])
            for day, values in incoming.items()
            if day not in existing
        ]
        if new_sessions:
            cur.executemany(
                "INSERT INTO trading_session (exchange, session_date, session_type, "
                "open_at, close_at, calendar_source) VALUES (%s, %s, %s, %s, %s, %s)",
                new_sessions,
            )
        cur.execute(
            "INSERT INTO ongoing_reference_check (approval_id, checked_on, checked_at, "
            "coverage_start, coverage_end, matched_assets, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'passed') "
            "ON CONFLICT (approval_id, checked_on) DO UPDATE SET "
            "checked_at = EXCLUDED.checked_at, coverage_start = EXCLUDED.coverage_start, "
            "coverage_end = EXCLUDED.coverage_end, "
            "matched_assets = EXCLUDED.matched_assets, status = 'passed' "
            "WHERE ongoing_reference_check.checked_at <= EXCLUDED.checked_at "
            "RETURNING approval_id",
            (
                approval_id,
                checked_on,
                checked_at,
                coverage_start,
                coverage_end,
                len(mappings),
            ),
        )
        if cur.fetchone() is None:
            raise ValueError("stale Alpaca reference observation")
    return {
        "checked_on": checked_on.isoformat(),
        "coverage_start": coverage_start.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "matched_assets": len(mappings),
        "sessions_added": len(new_sessions),
    }


def record_reference_failure(
    conn: psycopg.Connection, approval_id: str, checked_at: datetime
) -> None:
    """Invalidate an earlier check on this New York day after a failed probe."""
    checked_on = _checked_on(checked_at)
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ongoing_reference_check (approval_id, checked_on, checked_at, "
            "coverage_start, coverage_end, matched_assets, status) "
            "VALUES (%s, %s, %s, %s, %s, 0, 'failed') "
            "ON CONFLICT (approval_id, checked_on) DO UPDATE SET "
            "checked_at = EXCLUDED.checked_at, coverage_start = EXCLUDED.coverage_start, "
            "coverage_end = EXCLUDED.coverage_end, matched_assets = 0, status = 'failed' "
            "WHERE ongoing_reference_check.checked_at <= EXCLUDED.checked_at",
            (approval_id, checked_on, checked_at, checked_on, checked_on),
        )


def require_reference_check(
    conn: psycopg.Connection, approval_id: str, target: date, checked_at: datetime
) -> None:
    """Require today's successful full-universe check covering the target date."""
    checked_on = _checked_on(checked_at)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ongoing_reference_check WHERE approval_id = %s "
            "AND checked_on = %s AND status = 'passed' "
            "AND coverage_start <= %s AND coverage_end >= %s",
            (approval_id, checked_on, target, target),
        )
        if cur.fetchone() is None:
            raise ValueError(
                "today's Alpaca reference check or calendar coverage is missing"
            )


def calendar_status(
    conn: psycopg.Connection, approval_id: str, target: date, checked_at: datetime
) -> dict:
    """Return session, closed, or unknown for a reviewed New York date."""
    checked_on = _checked_on(checked_at)
    with conn.cursor() as cur:
        _approved_reference_context(cur, approval_id, checked_on)
        cur.execute(
            "SELECT 1 FROM ongoing_reference_check WHERE approval_id = %s "
            "AND checked_on = %s AND status = 'passed' "
            "AND coverage_start <= %s AND coverage_end >= %s",
            (approval_id, checked_on, target, target),
        )
        if cur.fetchone() is None:
            return {"status": "unknown"}
        cur.execute(
            "SELECT session_type, open_at, close_at, calendar_source "
            "FROM trading_session WHERE exchange = %s AND session_date = %s",
            (CALENDAR_EXCHANGE, target),
        )
        session = cur.fetchone()
    if session is None:
        return {"status": "closed"}
    session_type, opened, closed, source = session
    if (
        source != CALENDAR_SOURCE
        or session_type not in ("regular", "half_day")
        or opened >= closed
    ):
        raise ValueError("stored US equity session conflicts with reviewed calendar")
    return {
        "status": "session",
        "session": {
            "date": target.isoformat(),
            "open_at": opened.astimezone(timezone.utc).isoformat(),
            "close_at": closed.astimezone(timezone.utc).isoformat(),
            "type": session_type,
        },
    }
