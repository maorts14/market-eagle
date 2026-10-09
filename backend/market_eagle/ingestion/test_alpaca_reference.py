"""Offline checks for bounded Alpaca asset and trading-calendar reads."""

from datetime import date

import httpx
import pytest

from .alpaca_reference import fetch_assets, fetch_calendar


def test_assets_and_calendar_use_documented_paper_endpoints():
    paths = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v2/assets":
            assert request.url.params["status"] == "active"
            assert request.url.params["asset_class"] == "us_equity"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "symbol": "ALFA",
                        "exchange": "NYSE",
                        "name": "Alpha",
                        "class": "us_equity",
                        "status": "active",
                    }
                ],
            )
        assert request.url.params["date_type"] == "TRADING"
        return httpx.Response(
            200,
            json=[
                {"date": "2023-12-29", "open": "09:30", "close": "16:00"},
                {"date": "2024-01-02", "open": "09:30", "close": "13:00"},
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assets = fetch_assets(client, "test-key", "test-secret")
        sessions = fetch_calendar(
            client, "test-key", "test-secret", date(2024, 1, 1), date(2024, 1, 2)
        )
    assert paths == ["/v2/assets", "/v2/calendar"]
    assert assets[0]["exchange"] == "NYSE"
    assert sessions[0]["open_at"] == "2023-12-29T14:30:00+00:00"
    assert sessions[1]["type"] == "half_day"


def test_asset_response_rejects_wrong_class_and_calendar_duplicates():
    def wrong_asset(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "symbol": "ALFA",
                    "exchange": "NYSE",
                    "name": "Alpha",
                    "class": "crypto",
                    "status": "active",
                }
            ],
        )

    with (
        httpx.Client(transport=httpx.MockTransport(wrong_asset)) as client,
        pytest.raises(ValueError),
    ):
        fetch_assets(client, "key", "secret")

    def duplicate_session(request: httpx.Request) -> httpx.Response:
        row = {"date": "2024-01-02", "open": "09:30", "close": "16:00"}
        return httpx.Response(200, json=[row, row])

    with (
        httpx.Client(transport=httpx.MockTransport(duplicate_session)) as client,
        pytest.raises(ValueError),
    ):
        fetch_calendar(client, "key", "secret", date(2024, 1, 1), date(2024, 1, 2))
