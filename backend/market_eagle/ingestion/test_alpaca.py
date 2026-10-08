from datetime import date, datetime, timezone

import httpx
import pytest

from .alpaca import AlpacaRequestError, historical_pages, page_rows


def test_historical_reader_follows_all_page_tokens():
    tokens = []

    def respond(request: httpx.Request) -> httpx.Response:
        tokens.append(request.url.params.get("page_token"))
        if len(tokens) == 1:
            return httpx.Response(
                200,
                json={
                    "bars": {
                        "ALFA": [
                            {
                                "t": "2025-12-30T04:00:00Z",
                                "o": 1,
                                "h": 2,
                                "l": 1,
                                "c": 2,
                                "v": 100,
                                "vw": 1.5,
                            }
                        ]
                    },
                    "next_page_token": "next",
                },
            )
        return httpx.Response(200, json={"bars": {"BETA": []}, "next_page_token": None})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        pages = list(
            historical_pages(
                client,
                key_id="test",
                secret_key="test",
                symbols=["ALFA", "BETA"],
                start=date(2025, 12, 1),
                end=date(2025, 12, 31),
                feed="sip",
                adjustment="raw",
            )
        )
    assert tokens == [None, "next"]
    assert len(pages) == 2
    rows = page_rows(*pages[0], source="alpaca", feed="sip", basis="raw")
    assert rows[0]["session_date"] == "2025-12-30"
    assert rows[0]["as_of_kind"] == "fetched"


def test_historical_reader_reports_rate_limit_without_secrets():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3"})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as client,
        pytest.raises(AlpacaRequestError) as error,
    ):
        list(
            historical_pages(
                client,
                key_id="private-key",
                secret_key="private-secret",
                symbols=["ALFA"],
                start=date(2025, 1, 1),
                end=date(2025, 1, 2),
                feed="sip",
                adjustment="raw",
            )
        )
    assert error.value.status_code == 429
    assert error.value.retry_after == "3"
    assert "private" not in str(error.value)


def test_current_day_cutoff_is_sent_and_labeled_provisional():
    cutoff = datetime(2026, 10, 8, 19, 45, tzinfo=timezone.utc)
    ends = []

    def respond(request: httpx.Request) -> httpx.Response:
        ends.append(request.url.params["end"])
        return httpx.Response(
            200,
            json={
                "bars": {
                    "ALFA": [
                        {
                            "t": "2026-10-08T04:00:00Z",
                            "o": 10,
                            "h": 11,
                            "l": 9,
                            "c": 10.5,
                            "v": 1000,
                            "vw": 10.3,
                        }
                    ]
                },
                "next_page_token": None,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        page, observed = next(
            historical_pages(
                client,
                key_id="test",
                secret_key="test",
                symbols=["ALFA"],
                start=date(2026, 10, 8),
                end=date(2026, 10, 8),
                feed="sip",
                adjustment="raw",
                end_at=cutoff,
            )
        )
    assert ends == [cutoff.isoformat()]
    rows = page_rows(page, observed, "alpaca", "sip", "raw", status="provisional")
    assert rows[0]["status"] == "provisional"
    assert rows[0]["as_of_kind"] == "fetched"
