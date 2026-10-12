"""Pure candidate-tick planning from reviewed US-equity session times."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
REFRESH_WINDOW = timedelta(minutes=30)
RECONCILE_WINDOW = timedelta(hours=2)


def _planned_slot(
    kind: str, session_date: str, slot: str, due_at: datetime, request: dict
) -> dict:
    return {
        "kind": kind,
        "session_date": session_date,
        "slot": slot,
        "due_at": due_at.astimezone(timezone.utc).isoformat(),
        "business_id": (
            f"{kind}:{session_date}:{slot}:{request['snapshot_id']}:"
            f"{request['source']}:{request['feed']}:{request['price_basis']}"
        ),
    }


def refresh_due_slot(session: dict, tick_at: datetime, request: dict) -> dict | None:
    """Return one due cumulative-bar slot from stored UTC opens and closes."""
    opened = datetime.fromisoformat(session["open_at"])
    closed = datetime.fromisoformat(session["close_at"])
    if (
        tick_at.utcoffset() is None
        or opened.utcoffset() is None
        or closed.utcoffset() is None
        or opened >= closed
    ):
        raise ValueError("refresh slot requires aware tick and valid session times")
    tick = tick_at.astimezone(timezone.utc)
    opened = opened.astimezone(timezone.utc)
    closed = closed.astimezone(timezone.utc)
    minutes = 60
    while (due := opened + timedelta(minutes=minutes)) < closed:
        if due <= tick < due + REFRESH_WINDOW:
            return _planned_slot(
                "refresh", session["date"], f"open+{minutes}m", due, request
            )
        minutes += 60
    for minutes in (30, 90, 180):
        due = closed + timedelta(minutes=minutes)
        if due <= tick < due + REFRESH_WINDOW:
            return _planned_slot(
                "refresh", session["date"], f"close+{minutes}m", due, request
            )
    return None


def next_day_reconcile_slot(
    sessions: list[dict], tick_at: datetime, request: dict
) -> dict | None:
    """Target yesterday's stored New York session during the 08:00 catchup window."""
    if tick_at.utcoffset() is None:
        raise ValueError("reconciliation tick requires an aware datetime")
    local_tick = tick_at.astimezone(NEW_YORK)
    due = datetime.combine(local_tick.date(), time(8), NEW_YORK)
    if not due <= local_tick < due + RECONCILE_WINDOW:
        return None
    yesterday = (local_tick.date() - timedelta(days=1)).isoformat()
    if not any(session["date"] == yesterday for session in sessions):
        return None
    return _planned_slot("reconcile", yesterday, "next-day", due, request)
