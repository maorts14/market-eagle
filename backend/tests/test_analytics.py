from __future__ import annotations

import json
import sys
from dataclasses import replace
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
from market_eagle.analytics.service import AnalyticsError, AnalyticsService

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


@pytest.mark.parametrize(
    "label,start,end",
    [
        ("full_2025", "2025-01-01", "2025-12-31"),
        ("december_2025", "2025-12-01", "2025-12-31"),
    ],
)
def test_explorer_matches_independent_fixture(client, label, start, end):
    response = client.get("/api/v1/explorer", params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    actual = response.json()
    expected = EXPECTED["explorer"][label]
    assert actual["contract_version"] == 1
    assert actual["metric_version"] == "return-v1"
    assert actual["resolved_window"] == {
        key: expected[key]
        for key in ("comparison_session", "first_session", "last_session")
    }
    assert actual["catalog"]["tracked_count"] == expected["tracked_count"]
    assert actual["market"]["eligible_count"] == expected["eligible_count"]
    assert (
        actual["market"]["excluded_count"]
        == expected["tracked_count"] - expected["eligible_count"]
    )
    assert actual["exclusions"] == [
        {"stock_id": f"stock-{item['ticker'].lower()}", **item}
        for item in expected["exclusions"]
    ]
    assert actual["market"]["return"] == pytest.approx(
        expected["market_return"], abs=1e-12
    )
    assert actual["data"]["source"] == "synthetic-v1"
    assert actual["data"]["feed"] == "fictional"
    assert actual["data"]["price_basis"] == "synthetic_raw"
    assert actual["data"]["synthetic"] is True
    assert actual["data"]["return_rankings_trusted"] is False
    assert [sector["sector_code"] for sector in actual["sectors"]] == expected[
        "sector_order"
    ]
    for sector in actual["sectors"]:
        exp = expected["sectors"][sector["sector_code"]]
        for key in ("tracked_count", "eligible_count", "excluded_count", "up_count"):
            assert sector[key] == exp[key]
        for actual_key, expected_key in (
            ("breadth", "breadth"),
            ("return", "return"),
            ("excess_vs_market", "excess_vs_market"),
        ):
            assert sector[actual_key] == pytest.approx(exp[expected_key], abs=1e-12)
        assert [stock["ticker"] for stock in sector["stocks"]] == expected[
            "stock_order"
        ][sector["sector_code"]]
        for stock in sector["stocks"]:
            assert stock["return"] == pytest.approx(
                expected["stocks"][stock["ticker"]]["return"], abs=1e-12
            )
            assert stock["excess_vs_sector"] == pytest.approx(
                expected["stocks"][stock["ticker"]]["excess_vs_sector"], abs=1e-12
            )
            assert stock["final_observation_status"] == "historical"
            assert stock["data_as_of"].endswith("+00:00")


def test_typed_gain_and_dollar_volume_composition(repository):
    request = AnalyticalRequest.model_validate(
        {
            "request_version": 1,
            "universe": "latest_published_catalog",
            "window": {"start": "2025-12-01", "end": "2025-12-31"},
            "grain": "stock",
            "measures": [
                "period_return",
                "qualifying_days",
                "qualifying_fraction",
                "observed_usable_days",
                "requested_sessions",
            ],
            "daily_conditions": [
                {
                    "field": "daily_dollar_volume",
                    "operator": ">",
                    "value": "100000",
                    "unit": "USD",
                }
            ],
            "reduction": {
                "measure": "qualifying_fraction",
                "operator": ">=",
                "value": "0.80",
            },
            "sort": {"measure": "period_return", "direction": "desc"},
            "limit": 1,
        }
    )
    result = AnalyticsService(repository).execute(request)
    expected = EXPECTED["gain_plus_volume_last_month_as_of_2026_01_08"]
    assert result["catalog"]["tracked_count"] == expected["requested_stock_count"]
    assert result["eligible_count"] == expected["evaluated_stock_count"]
    assert result["market"]["excluded_count"] == expected["excluded_stock_count"]
    assert result["exclusions"] == [
        {"stock_id": f"stock-{item['ticker'].lower()}", **item}
        for item in expected["exclusions"]
    ]
    assert result["matched_count"] == len(expected["qualifying_ranked_candidates"])
    winner = result["rows"][0]
    for key in (
        "ticker",
        "qualifying_days",
        "observed_usable_days",
        "requested_sessions",
        "dollar_volume_inputs",
    ):
        assert winner[key] == expected["winner"][key]
    assert winner["period_return"] == pytest.approx(
        Decimal(str(expected["winner"]["return"])), abs=Decimal("0.000000000001")
    )
    assert winner["qualifying_fraction"] == Decimal(1)
    assert winner["requested_coverage"] == Decimal(1)
    assert winner["dollar_volume_formulas"] == [
        {
            "input": "reported_notional",
            "formula": "provider reported traded notional",
            "estimated": False,
        }
    ]


def test_daily_volume_fallbacks_and_observed_denominators(repository):
    request = AnalyticalRequest.model_validate(
        {
            "request_version": 1,
            "universe": "latest_published_catalog",
            "window": {"start": "2025-12-01", "end": "2025-12-31"},
            "grain": "stock",
            "measures": [
                "period_return",
                "qualifying_days",
                "qualifying_fraction",
                "observed_usable_days",
            ],
            "daily_conditions": [
                {
                    "field": "daily_dollar_volume",
                    "operator": ">",
                    "value": "100000",
                    "unit": "USD",
                }
            ],
            "sort": {"measure": "period_return", "direction": "desc"},
            "limit": 5,
        }
    )
    result = AnalyticsService(repository).execute(request)
    expected = EXPECTED["gain_plus_volume_last_month_as_of_2026_01_08"][
        "frequency_by_stock"
    ]
    assert result["eligible_count"] == 4
    for row in result["rows"]:
        reference = expected[row["ticker"]]
        for key in (
            "qualifying_days",
            "observed_usable_days",
            "requested_sessions",
            "dollar_volume_inputs",
        ):
            assert row[key] == reference[key]
        assert row["qualifying_fraction"] == pytest.approx(
            Decimal(str(reference["fraction"])), abs=Decimal("0.000000000001")
        )
    by_ticker = {row["ticker"]: row for row in result["rows"]}
    assert by_ticker["BETA"]["dollar_volume_formulas"][0]["estimated"] is True
    assert (
        by_ticker["GAMM"]["dollar_volume_formulas"][0]["formula"]
        == "share volume × daily close"
    )


def test_frequency_only_keeps_stock_missing_return_endpoint(repository):
    base = {
        "request_version": 1,
        "universe": "latest_published_catalog",
        "window": {"start": "2025-12-01", "end": "2025-12-31"},
        "grain": "stock",
        "measures": ["qualifying_fraction", "qualifying_days", "observed_usable_days"],
        "daily_conditions": [
            {
                "field": "daily_dollar_volume",
                "operator": ">",
                "value": "100000",
                "unit": "USD",
            }
        ],
        "sort": {"measure": "qualifying_fraction", "direction": "desc"},
        "limit": 5,
    }
    service = AnalyticsService(repository)
    frequency = service.execute(AnalyticalRequest.model_validate(base))
    assert frequency["metric_version"] == "daily-frequency-v1"
    assert frequency["data"]["as_of_kind"] == "provider"
    assert frequency["eligible_count"] == 5
    assert frequency["market"] == {
        "eligible_count": 5,
        "excluded_count": 0,
        "return": None,
    }
    assert frequency["exclusions"] == []
    delt = next(row for row in frequency["rows"] if row["ticker"] == "DELT")
    assert delt["observed_usable_days"] == 22
    assert delt["requested_sessions"] == 23
    assert delt["qualifying_fraction"] == Decimal(0)
    assert delt["period_return"] is None

    mixed = service.execute(
        AnalyticalRequest.model_validate(
            base
            | {
                "measures": [*base["measures"], "period_return"],
            }
        )
    )
    assert mixed["metric_version"] == "return-v1"
    assert mixed["eligible_count"] == 4
    assert mixed["market"]["excluded_count"] == 1
    assert mixed["exclusions"] == [
        {"stock_id": "stock-delt", "ticker": "DELT", "reason": "missing_final_close"}
    ]
    assert "DELT" not in {row["ticker"] for row in mixed["rows"]}

    full_year = base | {"window": {"start": "2025-01-01", "end": "2025-12-31"}}
    full_frequency = service.execute(AnalyticalRequest.model_validate(full_year))
    assert "EPSI" in {row["ticker"] for row in full_frequency["rows"]}
    full_mixed = service.execute(
        AnalyticalRequest.model_validate(
            full_year
            | {
                "measures": [*base["measures"], "period_return"],
            }
        )
    )
    assert {item["ticker"]: item["reason"] for item in full_mixed["exclusions"]}[
        "EPSI"
    ] == "missing_comparison_close"


def test_frequency_only_does_not_require_preceding_comparison_session(repository):
    base = {
        "request_version": 1,
        "universe": "latest_published_catalog",
        "window": {"start": "2023-12-29", "end": "2023-12-29"},
        "grain": "stock",
        "measures": ["qualifying_fraction"],
        "daily_conditions": [
            {"field": "volume", "operator": ">", "value": 0, "unit": "shares"}
        ],
        "sort": {"measure": "qualifying_fraction"},
        "limit": 5,
    }
    result = AnalyticsService(repository).execute(
        AnalyticalRequest.model_validate(base)
    )
    assert result["resolved_window"]["comparison_session"] is None
    assert result["eligible_count"] == 4
    assert result["exclusions"] == [
        {
            "stock_id": "stock-epsi",
            "ticker": "EPSI",
            "reason": "missing_usable_daily_observations",
        }
    ]
    assert all(row["qualifying_fraction"] == Decimal(1) for row in result["rows"])
    with pytest.raises(AnalyticsError) as error:
        AnalyticsService(repository).execute(
            AnalyticalRequest.model_validate(
                base
                | {
                    "measures": ["qualifying_fraction", "period_return"],
                }
            )
        )
    assert error.value.code == "no_comparison_session"


def test_rejects_incompatible_units_and_grain():
    common = {
        "request_version": 1,
        "universe": "latest_published_catalog",
        "window": {"start": "2025-12-01", "end": "2025-12-31"},
        "grain": "stock",
        "measures": ["period_return"],
        "sort": {"measure": "period_return"},
        "limit": 1,
    }
    with pytest.raises(ValidationError):
        AnalyticalRequest.model_validate(
            common
            | {
                "daily_conditions": [
                    {
                        "field": "daily_dollar_volume",
                        "operator": ">",
                        "value": 100000,
                        "unit": "shares",
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        AnalyticalRequest.model_validate(common | {"grain": "sector"})


def test_sector_grain_only_accepts_sector_predicates(repository):
    base = {
        "request_version": 1,
        "universe": "latest_published_catalog",
        "window": {"start": "2025-12-01", "end": "2025-12-31"},
        "grain": "sector",
        "measures": ["breadth"],
        "sort": {"measure": "breadth"},
        "limit": 10,
    }
    for field, value in (("ticker", "ALFA"), ("stock_id", "stock-alfa")):
        with pytest.raises(ValidationError, match="sector_code predicates"):
            AnalyticalRequest.model_validate(
                base
                | {"predicates": [{"field": field, "operator": "=", "value": value}]}
            )
    request = AnalyticalRequest.model_validate(
        base
        | {"predicates": [{"field": "sector_code", "operator": "=", "value": "TECH"}]}
    )
    result = AnalyticsService(repository).execute(request)
    assert [row["sector_code"] for row in result["rows"]] == ["TECH"]


def test_absolute_count_and_observed_fraction_are_distinct(repository):
    base = {
        "request_version": 1,
        "universe": "latest_published_catalog",
        "window": {"start": "2025-01-03", "end": "2025-01-03"},
        "grain": "stock",
        "measures": ["period_return", "qualifying_days", "qualifying_fraction"],
        "daily_conditions": [
            {"field": "volume", "operator": ">", "value": 0, "unit": "shares"}
        ],
        "predicates": [{"field": "stock_id", "operator": "=", "value": "stock-epsi"}],
        "sort": {"measure": "period_return"},
        "limit": 1,
    }
    service = AnalyticsService(repository)
    count = AnalyticalRequest.model_validate(
        base
        | {"reduction": {"measure": "qualifying_days", "operator": ">=", "value": 2}}
    )
    fraction = AnalyticalRequest.model_validate(
        base
        | {
            "reduction": {
                "measure": "qualifying_fraction",
                "operator": ">=",
                "value": "0.50",
            }
        }
    )
    assert service.execute(count)["matched_count"] == 0
    result = service.execute(fraction)
    assert result["matched_count"] == 1
    assert result["rows"][0]["qualifying_days"] == 1
    assert result["rows"][0]["observed_usable_days"] == 1
    assert result["rows"][0]["qualifying_fraction"] == Decimal(1)


def test_explorer_errors_are_typed(client):
    invalid = client.get(
        "/api/v1/explorer", params={"start": "2025-12-31", "end": "2025-12-01"}
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_range"
    no_sessions = client.get(
        "/api/v1/explorer", params={"start": "2025-12-27", "end": "2025-12-28"}
    )
    assert no_sessions.status_code == 422
    assert no_sessions.json()["error"]["code"] == "no_sessions"


def test_no_eligible_bars_is_a_coverage_result(repository):
    class NoComparisonBars:
        def load(self, start, end):
            dataset = repository.load(start, end)
            return replace(
                dataset,
                bars=tuple(
                    bar
                    for bar in dataset.bars
                    if bar.session_date != date(2025, 11, 28)
                ),
            )

    result = AnalyticsService(NoComparisonBars()).explorer(
        date(2025, 12, 1), date(2025, 12, 31)
    )
    assert result["market"] == {
        "eligible_count": 0,
        "excluded_count": 5,
        "return": None,
    }
    assert result["data"]["as_of"] is None
    assert result["data"]["provisional"] is False
    assert all(
        sector["breadth"] is None and sector["return"] is None
        for sector in result["sectors"]
    )


def test_global_freshness_uses_oldest_eligible_final_bar(repository):
    class MixedFreshness:
        def load(self, start, end):
            dataset = repository.load(start, end)
            bars = tuple(
                replace(bar, provider_as_of=bar.provider_as_of.replace(hour=17))
                if bar.stock_id == "stock-alfa"
                and bar.session_date == date(2025, 12, 31)
                else replace(bar, status="provisional")
                if bar.stock_id == "stock-beta"
                and bar.session_date == date(2025, 12, 15)
                else bar
                for bar in dataset.bars
            )
            return replace(dataset, bars=bars)

    result = AnalyticsService(MixedFreshness()).explorer(
        date(2025, 12, 1), date(2025, 12, 31)
    )
    assert result["data"]["as_of"].hour == 17
    assert result["data"]["provisional"] is False
