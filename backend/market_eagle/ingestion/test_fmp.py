"""Offline FMP contract checks; no provider key or network request is needed."""

from datetime import date

import httpx
import pytest

from .fmp import (
    FmpRequestError,
    FmpTransportError,
    fetch_constituents,
    normalize_constituents,
)


def _row(symbol: str, sector: str = "Technology") -> dict:
    return {
        "symbol": symbol,
        "name": f"{symbol} Company",
        "sector": sector,
        "subSector": "Software",
        "cik": "0000123456",
        "dateFirstAdded": "2020-01-01",
    }


def test_fetch_uses_current_endpoint_and_bounded_response():
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[_row("ALFA"), _row("BETA")],
            headers={"X-RateLimit-Remaining": "249"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetched = fetch_constituents(client, "test-key")
    assert requests[0].url.path == "/stable/sp500-constituent"
    assert requests[0].url.params["apikey"] == "test-key"
    assert len(fetched.rows) == 2
    assert fetched.rate_headers["x-ratelimit-remaining"] == "249"
    assert fetched.rows[0]["dateFirstAdded"] == date(2020, 1, 1).isoformat()


def test_fetch_refuses_oversized_and_entitlement_errors_without_key_in_error():
    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "2000001"}, content=b"[]")

    with (
        httpx.Client(transport=httpx.MockTransport(oversized)) as client,
        pytest.raises(ValueError, match="2 MB"),
    ):
        fetch_constituents(client, "private-key")

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"Error Message": "Upgrade required"})

    with (
        httpx.Client(transport=httpx.MockTransport(forbidden)) as client,
        pytest.raises(FmpRequestError) as error,
    ):
        fetch_constituents(client, "private-key")
    assert error.value.status_code == 403
    assert "private-key" not in str(error.value)


def test_shape_rejects_duplicates_missing_sector_and_error_objects():
    with pytest.raises(ValueError, match="repeats"):
        normalize_constituents([_row("ALFA"), _row("ALFA")])
    with pytest.raises(ValueError, match="no sector"):
        normalize_constituents([_row("ALFA", "")])
    with pytest.raises(ValueError, match="1 to 700"):
        normalize_constituents({"Error Message": "Invalid API KEY"})


def test_network_error_does_not_echo_credential_url():
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(fail)) as client,
        pytest.raises(FmpTransportError) as error,
    ):
        fetch_constituents(client, "private-key")
    assert "private-key" not in str(error.value)
