"""Fixed-model checks for objective synthetic agent facts and boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from market_eagle.agent.activities import AgentActivities
from market_eagle.agent.api import public_turn
from market_eagle.agent.evaluation_records import build_input_record, load_cases
from market_eagle.agent.models import Decision, Limits
from market_eagle.agent.store import AgentStore
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.models import AnalyticalRequest
from market_eagle.analytics.service import AnalyticsService

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"
DATASET_VERSION, CASES = load_cases()
WINDOW = {"start": "2025-12-01", "end": "2025-12-31"}
BASE_REQUEST = {
    "request_version": 1,
    "universe": "latest_published_catalog",
    "window": WINDOW,
}
QUERY_FIELDS = {
    "gain-dollar-frequency-previous-month": {
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
        "reduction": {
            "measure": "qualifying_fraction",
            "operator": ">=",
            "value": "0.8",
        },
        "sort": {"measure": "period_return", "direction": "desc"},
        "limit": 1,
    },
    "simple-stock-return-december": {
        "grain": "stock",
        "measures": ["period_return"],
        "sort": {"measure": "period_return", "direction": "desc"},
        "limit": 1,
    },
    "sector-breadth-december": {
        "grain": "sector",
        "measures": ["breadth"],
        "sort": {"measure": "breadth", "direction": "desc"},
        "limit": 3,
    },
    "sector-return-december": {
        "grain": "sector",
        "measures": ["sector_return"],
        "sort": {"measure": "sector_return", "direction": "desc"},
        "limit": 2,
    },
    "market-return-december": {
        "grain": "stock",
        "measures": ["period_return", "market_return"],
        "sort": {"measure": "period_return", "direction": "desc"},
        "limit": 1,
    },
    "stock-excess-december": {
        "grain": "stock",
        "measures": ["excess_vs_sector"],
        "sort": {"measure": "excess_vs_sector", "direction": "desc"},
        "limit": 1,
    },
    "absolute-volume-days-december": {
        "grain": "stock",
        "measures": ["qualifying_days", "observed_usable_days"],
        "daily_conditions": [
            {
                "field": "daily_dollar_volume",
                "operator": ">",
                "value": "100000",
                "unit": "USD",
            }
        ],
        "reduction": {
            "measure": "qualifying_days",
            "operator": ">=",
            "value": "20",
        },
        "sort": {"measure": "qualifying_days", "direction": "desc"},
        "limit": 5,
    },
}


class FixedModel:
    def __init__(self, decision: Decision):
        self.decision = decision

    def interpret(self, _context: dict, *, feedback: str | None = None) -> Decision:
        return self.decision

    def explain(self, _question: str, _result: dict, _assumptions: list[str]) -> str:
        return "These calculations apply to the eligible observations shown."

    def summarize(self, _turns: list[dict]) -> str:
        return ""


def core_failures(case: dict, record: dict) -> list[str]:
    """Check literal fixture facts; free-text semantics still need human review."""
    failures = []
    expected_status = case.get(
        "expected_status", case.get("expected_status_without_context")
    )
    if expected_status and record["status"] != expected_status:
        failures.append(f"status: {record['status']} != {expected_status}")

    result = record["trusted_result"]
    if case.get("expected_no_evidence") and result is not None:
        failures.append("unexpected trusted evidence")
    if case.get("required_evidence") and result is None:
        failures.append("missing trusted evidence")
    if result is not None:
        for field in case.get("required_evidence", []):
            if field not in result:
                failures.append(f"missing evidence field: {field}")
        if (
            result["data"]["source"] != "synthetic-v1"
            or not result["data"]["synthetic"]
        ):
            failures.append("result is not from the synthetic fixture")
        if "expected_window" in case:
            actual = list(result["requested_window"].values())
            if actual != case["expected_window"]:
                failures.append(f"window: {actual} != {case['expected_window']}")
        expected_counts = {
            "expected_eligible_stocks": result["eligible_count"],
            "expected_matched_stocks": result["matched_count"],
            "expected_requested_stocks": result["catalog"]["tracked_count"],
        }
        for expected_field, actual in expected_counts.items():
            if expected_field in case and actual != case[expected_field]:
                failures.append(f"{expected_field}: {actual} != {case[expected_field]}")
        coverage = (
            f"Evaluated {result['eligible_count']} of "
            f"{result['catalog']['tracked_count']} tracked stocks"
        )
        if result["coverage_label"] != coverage:
            failures.append("coverage label disagrees with trusted counts")
        rows = result["rows"]
        if rows:
            first = rows[0]
            for expected_field, row_field in (
                ("expected_winner", "ticker"),
                ("expected_sector", "sector_code"),
                ("expected_period_return", "period_return"),
                ("expected_excess_vs_sector", "excess_vs_sector"),
                ("expected_breadth", "breadth"),
                ("expected_sector_return", "sector_return"),
                ("expected_market_return", "market_return"),
            ):
                if expected_field in case and str(first.get(row_field)) != str(
                    case[expected_field]
                ):
                    failures.append(
                        f"{row_field}: {first.get(row_field)} != {case[expected_field]}"
                    )
            if "expected_winners" in case:
                actual = [row["ticker"] for row in rows]
                if actual != case["expected_winners"]:
                    failures.append(f"winners: {actual} != {case['expected_winners']}")
            for expected_field, row_field in (
                ("expected_qualifying_days", "qualifying_days"),
                ("expected_observed_days", "observed_usable_days"),
            ):
                if expected_field in case:
                    actual = [row[row_field] for row in rows]
                    if actual != [case[expected_field]] * len(rows):
                        failures.append(
                            f"{row_field}: {actual} != {case[expected_field]}"
                        )
        elif any(
            key in case
            for key in ("expected_winner", "expected_winners", "expected_sector")
        ):
            failures.append("missing expected result row")

    if (
        case.get("expected_explanation_unavailable")
        and record["agent_explanation"] is not None
    ):
        failures.append("expected no model explanation")
    prose = " ".join(
        str(value)
        for value in (
            record.get("agent_explanation"),
            (record.get("model_decision") or {}).get("message"),
        )
        if value
    ).casefold()
    for phrase in case.get("forbidden_claims", []):
        if phrase.casefold() in prose:
            failures.append(f"forbidden claim: {phrase}")
    context = json.dumps(record.get("conversation_context", []), default=str)
    for marker in case.get("forbidden_context_markers", []):
        if marker in context:
            failures.append(f"cross-conversation context leaked: {marker}")
    if case.get("expected_no_evidence") and any(
        event["stage"] == "tool_verified" for event in record.get("trace_stages", [])
    ):
        failures.append("tool ran for a no-evidence decision")
    return failures


def fixed_query_record(tmp_path: Path, case_id: str) -> dict:
    case = CASES[case_id]
    decision = Decision.model_validate(
        {
            "kind": "query",
            "request": BASE_REQUEST | QUERY_FIELDS[case_id],
            "assumptions": [],
        }
    )
    store = AgentStore(tmp_path / "agent.sqlite")
    activities = AgentActivities(
        store,
        AnalyticsService(SyntheticFixtureRepository(FIXTURE)),
        FixedModel(decision),
        Limits(),
    )
    turn = store.submit(
        store.create_conversation(), case_id, case["question"], case["reference_date"]
    )
    context = activities.load_context(turn["id"])
    raw_decision = activities.interpret(turn["id"], context, None)
    outcome = activities.execute(turn["id"], raw_decision)
    assert outcome["kind"] == "verified", outcome
    explanation = activities.explain(turn["id"], raw_decision, outcome["evidence_id"])
    activities.finish(
        turn["id"], "completed", raw_decision, outcome["evidence_id"], explanation, None
    )
    return build_input_record(
        store,
        case,
        dataset_version=DATASET_VERSION,
        run_id="fixed-core",
        model_id="fixed-test-model",
        turn_id=turn["id"],
    )


@pytest.mark.parametrize("case_id", list(QUERY_FIELDS))
def test_fixed_model_query_core_facts(tmp_path, case_id):
    record = fixed_query_record(tmp_path, case_id)
    failures = core_failures(CASES[case_id], record)
    assert not failures, "\n".join(failures)


def test_core_checks_reject_wrong_coverage_and_unsupported_claims(tmp_path):
    case = CASES["gain-dollar-frequency-previous-month"]
    record = fixed_query_record(tmp_path, case["id"])
    wrong_count = deepcopy(record)
    wrong_count["trusted_result"]["eligible_count"] = 5
    assert any(
        "expected_eligible_stocks" in failure
        for failure in core_failures(case, wrong_count)
    )

    wrong_prose = deepcopy(record)
    wrong_prose["agent_explanation"] = (
        "EPSI led all five stocks because it was caused by news."
    )
    failures = core_failures(case, wrong_prose)
    assert "forbidden claim: led all five stocks" in failures
    assert "forbidden claim: caused by news" in failures


@pytest.mark.parametrize("case_id", ["unsupported-causal", "unsupported-forecast"])
def test_fixed_model_unsupported_cases_have_no_tool_evidence(tmp_path, case_id):
    case = CASES[case_id]
    store = AgentStore(tmp_path / "agent.sqlite")
    decision = Decision(
        kind="unsupported",
        request=None,
        message="Retained data cannot establish that claim",
    )
    activities = AgentActivities(
        store,
        AnalyticsService(SyntheticFixtureRepository(FIXTURE)),
        FixedModel(decision),
        Limits(),
    )
    turn = store.submit(
        store.create_conversation(), case_id, case["question"], "2026-01-08"
    )
    raw_decision = activities.interpret(
        turn["id"], activities.load_context(turn["id"]), None
    )
    activities.finish(
        turn["id"], "unsupported", raw_decision, None, decision.message, None
    )
    record = build_input_record(
        store,
        case,
        dataset_version=DATASET_VERSION,
        run_id="fixed-core",
        model_id="fixed-test-model",
        turn_id=turn["id"],
    )
    assert not core_failures(case, record)
    assert record["trusted_result"] is None
    assert [event["stage"] for event in record["trace_stages"]] == ["interpretation"]

    bad = deepcopy(record)
    bad["agent_explanation"] = (
        "The price was caused by news"
        if case_id == "unsupported-causal"
        else "This stock will rise"
    )
    assert any("forbidden claim" in failure for failure in core_failures(case, bad))


def test_follow_up_context_isolated_from_other_conversation(tmp_path):
    case = CASES["isolated-follow-up"]
    store = AgentStore(tmp_path / "agent.sqlite")
    other_conversation = store.create_conversation()
    other = store.submit(
        other_conversation, "other", "OTHER_CONVERSATION_ONLY", "2026-01-08"
    )
    other_result = AnalyticsService(SyntheticFixtureRepository(FIXTURE)).execute(
        AnalyticalRequest.model_validate(
            BASE_REQUEST | QUERY_FIELDS["simple-stock-return-december"]
        )
    )
    other_evidence_id = store.save_evidence(other["id"], other_result)
    store.finish(
        other["id"],
        "completed",
        evidence_id=other_evidence_id,
        explanation="Only the other conversation knows EPSI",
    )

    selected_conversation = store.create_conversation()
    prior = store.submit(
        selected_conversation, "prior", "Different local question", "2026-01-08"
    )
    store.finish(prior["id"], "unsupported", explanation="No stock selected")
    follow = store.submit(
        selected_conversation, "follow", case["question"], "2026-01-08"
    )
    context = store.context(follow["id"])
    assert [turn["question"] for turn in context["recent_turns"]] == [
        "Different local question"
    ]
    assert "EPSI" not in json.dumps(context)
    decision = Decision(
        kind="clarification", request=None, message="Which stock do you mean?"
    )
    store.finish(
        follow["id"],
        "needs_clarification",
        decision=decision.model_dump(mode="json"),
        explanation=decision.message,
    )
    record = build_input_record(
        store,
        case,
        dataset_version=DATASET_VERSION,
        run_id="fixed-core",
        model_id="fixed-test-model",
        turn_id=follow["id"],
    )
    assert not core_failures(case, record)
    assert public_turn(store, store.turn(follow["id"]))["trusted_result"] is None
