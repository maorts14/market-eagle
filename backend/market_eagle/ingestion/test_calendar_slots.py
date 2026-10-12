"""Deterministic reviewed-calendar planning with no database or scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .calendar_slots import next_day_reconcile_slot, refresh_due_slot

REQUEST = {
    "snapshot_id": "fmp-reviewed",
    "source": "alpaca",
    "feed": "sip",
    "price_basis": "raw",
}


def _session(day: str, opened: str, closed: str) -> dict:
    return {"date": day, "open_at": opened, "close_at": closed}


def test_regular_session_has_six_intraday_and_three_after_close_slots():
    session = _session(
        "2026-10-08", "2026-10-08T13:30:00+00:00", "2026-10-08T20:00:00+00:00"
    )
    expected = [
        (
            f"open+{minutes}m",
            datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc)
            + timedelta(minutes=minutes),
        )
        for minutes in (60, 120, 180, 240, 300, 360)
    ] + [
        (
            f"close+{minutes}m",
            datetime(2026, 10, 8, 20, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        )
        for minutes in (30, 90, 180)
    ]
    for name, due in expected:
        slot = refresh_due_slot(session, due, REQUEST)
        assert slot == {
            "kind": "refresh",
            "session_date": session["date"],
            "slot": name,
            "due_at": due.isoformat(),
            "business_id": (f"refresh:2026-10-08:{name}:fmp-reviewed:alpaca:sip:raw"),
        }


def test_half_day_uses_stored_early_close():
    session = _session(
        "2026-11-27", "2026-11-27T14:30:00+00:00", "2026-11-27T18:00:00+00:00"
    )
    for hour, name in ((15, "open+60m"), (16, "open+120m"), (17, "open+180m")):
        assert (
            refresh_due_slot(
                session, datetime(2026, 11, 27, hour, 30, tzinfo=timezone.utc), REQUEST
            )["slot"]
            == name
        )
    assert (
        refresh_due_slot(
            session, datetime(2026, 11, 27, 18, tzinfo=timezone.utc), REQUEST
        )
        is None
    )
    assert (
        refresh_due_slot(
            session, datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc), REQUEST
        )["slot"]
        == "close+30m"
    )


def test_holiday_and_weekend_reconcile_only_yesterdays_stored_session():
    sessions = [
        _session("2026-07-02", "2026-07-02T13:30:00+00:00", "2026-07-02T20:00:00+00:00")
    ]
    due = datetime(2026, 7, 3, 12, tzinfo=timezone.utc)  # 08:00 New York.
    slot = next_day_reconcile_slot(sessions, due, REQUEST)
    assert slot == {
        "kind": "reconcile",
        "session_date": "2026-07-02",
        "slot": "next-day",
        "due_at": due.isoformat(),
        "business_id": "reconcile:2026-07-02:next-day:fmp-reviewed:alpaca:sip:raw",
    }
    assert (
        next_day_reconcile_slot(
            sessions, datetime(2026, 7, 5, 12, tzinfo=timezone.utc), REQUEST
        )
        is None
    )  # Yesterday was July 4, absent from the reviewed calendar.
    assert (
        next_day_reconcile_slot(
            sessions, datetime(2026, 7, 6, 12, tzinfo=timezone.utc), REQUEST
        )
        is None
    )  # Do not silently target the last available trading session.


def test_dst_uses_session_utc_times_and_new_york_0800():
    before = _session(
        "2026-03-06", "2026-03-06T14:30:00+00:00", "2026-03-06T21:00:00+00:00"
    )
    after = _session(
        "2026-03-09", "2026-03-09T13:30:00+00:00", "2026-03-09T20:00:00+00:00"
    )
    assert (
        refresh_due_slot(
            before, datetime(2026, 3, 6, 15, 30, tzinfo=timezone.utc), REQUEST
        )["slot"]
        == "open+60m"
    )
    assert (
        refresh_due_slot(
            after, datetime(2026, 3, 9, 14, 30, tzinfo=timezone.utc), REQUEST
        )["slot"]
        == "open+60m"
    )
    assert (
        next_day_reconcile_slot(
            [before], datetime(2026, 3, 7, 13, tzinfo=timezone.utc), REQUEST
        )["session_date"]
        == "2026-03-06"
    )
    assert (
        next_day_reconcile_slot(
            [after], datetime(2026, 3, 10, 12, tzinfo=timezone.utc), REQUEST
        )["session_date"]
        == "2026-03-09"
    )


def test_duplicate_ticks_share_business_id_and_late_ticks_are_rejected():
    session = _session(
        "2026-10-08", "2026-10-08T13:30:00+00:00", "2026-10-08T20:00:00+00:00"
    )
    due = datetime(2026, 10, 8, 14, 30, tzinfo=timezone.utc)
    first = refresh_due_slot(session, due, REQUEST)
    duplicate = refresh_due_slot(session, due + timedelta(minutes=29), REQUEST)
    assert duplicate["business_id"] == first["business_id"]
    assert refresh_due_slot(session, due - timedelta(minutes=1), REQUEST) is None
    assert refresh_due_slot(session, due + timedelta(minutes=30), REQUEST) is None

    next_day = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    first_recheck = next_day_reconcile_slot([session], next_day, REQUEST)
    duplicate_recheck = next_day_reconcile_slot(
        [session], next_day + timedelta(minutes=119), REQUEST
    )
    assert duplicate_recheck["business_id"] == first_recheck["business_id"]
    assert (
        next_day_reconcile_slot([session], next_day + timedelta(hours=2), REQUEST)
        is None
    )
