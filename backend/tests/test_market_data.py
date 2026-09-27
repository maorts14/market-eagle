from datetime import date
from app.market_data import fetch_daily_bars


def test_demo_feed_is_deterministic_and_weekday_only() -> None:
    rows = fetch_daily_bars("XLK", date(2025, 1, 1), date(2025, 1, 10), "demo")
    assert len(rows) == 8
    assert rows[0]["source"] == "demo"
    assert all(row["trading_date"].weekday() < 5 for row in rows)
