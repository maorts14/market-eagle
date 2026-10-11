"""Run one live, nonsensitive model decision through the synthetic analytics fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path

from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.service import AnalyticsService

from .models import Limits, validate_request
from .openrouter import FREE_MODEL, OpenRouterResearchModel

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic-v1"
QUESTION = (
    "Among stocks in the latest published catalog, rank by period return from "
    "2025-12-01 through 2025-12-31, descending, and return the top 1 stock."
)


def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print(
            json.dumps({"ok": False, "stage": "configuration", "error": "missing_key"})
        )
        return 2

    stage = "interpretation"
    try:
        decision = OpenRouterResearchModel(api_key=api_key, model=FREE_MODEL).interpret(
            {
                "question": QUESTION,
                "reference_date": "2026-01-08",
                "summary": None,
                "recent_turns": [],
            }
        )
        if decision.kind != "query" or decision.request is None:
            print(
                json.dumps(
                    {"ok": False, "stage": stage, "decision_kind": decision.kind}
                )
            )
            return 1

        request = decision.request
        if not (
            request.window.start.isoformat() == "2025-12-01"
            and request.window.end.isoformat() == "2025-12-31"
            and request.grain == "stock"
            and request.measures == ["period_return"]
            and not request.daily_conditions
            and request.reduction is None
            and not request.predicates
            and request.sort.measure == "period_return"
            and request.sort.direction == "desc"
            and request.limit == 1
        ):
            print(json.dumps({"ok": False, "stage": "request_contract"}))
            return 1
        validate_request(request, Limits())

        stage = "analytics"
        evidence = AnalyticsService(SyntheticFixtureRepository(FIXTURE)).execute(
            request
        )
        if not (
            evidence["data"]["synthetic"]
            and len(evidence["rows"]) == 1
            and evidence["rows"][0]["ticker"] == "EPSI"
        ):
            print(json.dumps({"ok": False, "stage": "evidence_contract"}))
            return 1
    except Exception as error:  # noqa: BLE001 - keep provider text out of CLI output
        print(
            json.dumps(
                {"ok": False, "stage": stage, "error_type": type(error).__name__}
            )
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "decision_kind": "query",
                "analytics_executed": True,
                "fixture_winner_matches": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
