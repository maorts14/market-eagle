from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_eagle.analytics.api import create_explorer_router, install_analytics_errors
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.models import AnalyticalRequest
from market_eagle.analytics.service import AnalyticsService


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"
EXPECTED = json.loads((FIXTURE / "expected-results.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repository():
    return SyntheticFixtureRepository(FIXTURE)


@pytest.fixture(scope="module")
def client(repository):
    app = FastAPI()
    install_analytics_errors(app)
    app.include_router(create_explorer_router(repository))
    return TestClient(app)


@pytest.mark.parametrize("label,start,end", [
    ("full_2025", "2025-01-01", "2025-12-31"),
    ("december_2025", "2025-12-01", "2025-12-31"),
])
def test_explorer_matches_independent_fixture(client, label, start, end):
    response = client.get("/api/v1/explorer", params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    actual = response.json()
    expected = EXPECTED["explorer"][label]
    assert actual["contract_version"] == 1
    assert actual["metric_version"] == "return-v1"
    assert actual["resolved_window"] == {key: expected[key] for key in ("comparison_session", "first_session", "last_session")}
    assert actual["catalog"]["tracked_count"] == expected["tracked_count"]
    assert actual["market"]["eligible_count"] == expected["eligible_count"]
    assert actual["market"]["excluded_count"] == expected["tracked_count"] - expected["eligible_count"]
    assert actual["market"]["return"] == pytest.approx(expected["market_return"], abs=1e-12)
    assert actual["data"]["source"] == "synthetic-v1"
    assert actual["data"]["feed"] == "fictional"
    assert actual["data"]["price_basis"] == "synthetic_raw"
    assert actual["data"]["synthetic"] is True
    assert actual["data"]["return_rankings_trusted"] is False
    for sector in actual["sectors"]:
        exp = expected["sectors"][sector["sector_code"]]
        for key in ("eligible_count", "up_count"):
            assert sector[key] == exp[key]
        for actual_key, expected_key in (("breadth", "breadth"), ("return", "return")):
            assert sector[actual_key] == pytest.approx(exp[expected_key], abs=1e-12)
        assert sector["excluded_count"] == sector["tracked_count"] - sector["eligible_count"]
        for stock in sector["stocks"]:
            assert stock["return"] == pytest.approx(expected["stocks"][stock["ticker"]]["return"], abs=1e-12)
            assert stock["final_observation_status"] == "historical"
            assert stock["data_as_of"].endswith("+00:00")


def test_typed_gain_and_dollar_volume_composition(repository):
    request = AnalyticalRequest.model_validate({
        "request_version": 1, "universe": "latest_published_catalog",
        "window": {"start": "2025-12-01", "end": "2025-12-31"},
        "grain": "stock", "measures": ["period_return", "qualifying_days", "qualifying_fraction", "observed_usable_days", "requested_sessions"],
        "daily_conditions": [{"field": "daily_dollar_volume", "operator": ">", "value": "100000", "unit": "USD"}],
        "reduction": {"measure": "qualifying_fraction", "operator": ">=", "value": "0.80"},
        "sort": {"measure": "period_return", "direction": "desc"}, "limit": 1,
    })
    result = AnalyticsService(repository).execute(request)
    expected = EXPECTED["gain_plus_volume_last_month_as_of_2026_01_08"]
    assert result["matched_count"] == len(expected["qualifying_ranked_candidates"])
    winner = result["rows"][0]
    for key in ("ticker", "qualifying_days", "observed_usable_days", "requested_sessions", "dollar_volume_inputs"):
        assert winner[key] == expected["winner"][key]
    assert winner["period_return"] == pytest.approx(Decimal(str(expected["winner"]["return"])), abs=Decimal("0.000000000001"))
    assert winner["qualifying_fraction"] == Decimal("1")
    assert winner["requested_coverage"] == Decimal("1")
    assert winner["dollar_volume_formulas"] == [{"input": "reported_notional", "formula": "provider reported traded notional", "estimated": False}]


def test_rejects_incompatible_units_and_grain():
    common = {"request_version": 1, "universe": "latest_published_catalog", "window": {"start": "2025-12-01", "end": "2025-12-31"},
              "grain": "stock", "measures": ["period_return"], "sort": {"measure": "period_return"}, "limit": 1}
    with pytest.raises(ValidationError):
        AnalyticalRequest.model_validate(common | {"daily_conditions": [{"field": "daily_dollar_volume", "operator": ">", "value": 100000, "unit": "shares"}]})
    with pytest.raises(ValidationError):
        AnalyticalRequest.model_validate(common | {"grain": "sector"})


def test_absolute_count_and_observed_fraction_are_distinct(repository):
    base = {
        "request_version": 1, "universe": "latest_published_catalog",
        "window": {"start": "2025-01-03", "end": "2025-01-03"},
        "grain": "stock", "measures": ["period_return", "qualifying_days", "qualifying_fraction"],
        "daily_conditions": [{"field": "volume", "operator": ">", "value": 0, "unit": "shares"}],
        "predicates": [{"field": "stock_id", "operator": "=", "value": "stock-epsi"}],
        "sort": {"measure": "period_return"}, "limit": 1,
    }
    service = AnalyticsService(repository)
    count = AnalyticalRequest.model_validate(base | {"reduction": {"measure": "qualifying_days", "operator": ">=", "value": 2}})
    fraction = AnalyticalRequest.model_validate(base | {"reduction": {"measure": "qualifying_fraction", "operator": ">=", "value": "0.50"}})
    assert service.execute(count)["matched_count"] == 0
    result = service.execute(fraction)
    assert result["matched_count"] == 1
    assert result["rows"][0]["qualifying_days"] == 1
    assert result["rows"][0]["observed_usable_days"] == 1
    assert result["rows"][0]["qualifying_fraction"] == Decimal("1")


def test_explorer_errors_are_typed(client):
    invalid = client.get("/api/v1/explorer", params={"start": "2025-12-31", "end": "2025-12-01"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_range"
    no_sessions = client.get("/api/v1/explorer", params={"start": "2025-12-27", "end": "2025-12-28"})
    assert no_sessions.status_code == 422
    assert no_sessions.json()["error"]["code"] == "no_sessions"
