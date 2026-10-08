from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_eagle.agent.activities import AgentActivities
from market_eagle.agent.models import Decision, Limits, previous_completed_month
from market_eagle.agent.store import AgentStore, BusyConversation
from market_eagle.agent.workflow import AgentTurnWorkflow
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.models import AnalyticalRequest
from market_eagle.analytics.service import AnalyticsService

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"
EVALUATION = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "market_eagle"
        / "agent"
        / "evaluation-v1.json"
    ).read_text(encoding="utf-8")
)


def gain_volume_decision(reference: date) -> Decision:
    start, end = previous_completed_month(reference)
    return Decision.model_validate(
        {
            "kind": "query",
            "assumptions": ["last month means the previous completed calendar month"],
            "request": {
                "request_version": 1,
                "universe": "latest_published_catalog",
                "window": {"start": start, "end": end},
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
                    "value": "0.80",
                },
                "sort": {"measure": "period_return", "direction": "desc"},
                "limit": 1,
            },
        }
    )


class FakeModel:
    def __init__(self, decision: Decision):
        self.decision = decision
        self.seen_contexts = []

    def interpret(self, context, *, feedback=None):
        self.seen_contexts.append(context)
        return self.decision

    def explain(self, question, result, assumptions):
        return (
            "The leader is scoped to stocks with enough comparison prices. "
            + assumptions[0]
        )

    def summarize(self, turns):
        return "Earlier research about " + turns[0]["question"]


@pytest.fixture
def setup(tmp_path):
    store = AgentStore(tmp_path / "agent.sqlite")
    model = FakeModel(gain_volume_decision(date(2026, 1, 8)))
    activities = AgentActivities(
        store, AnalyticsService(SyntheticFixtureRepository(FIXTURE)), model, Limits()
    )
    return store, model, activities


def test_gain_and_dollar_volume_previous_calendar_month_end_to_end(setup):
    store, model, activities = setup
    case = EVALUATION["cases"][0]
    conversation = store.create_conversation()
    turn = store.submit(
        conversation,
        "req-1",
        case["question"],
        case["reference_date"],
    )
    context = activities.load_context(turn["id"])
    decision = activities.interpret(turn["id"], context, None)
    assert list(decision["request"]["window"].values()) == case["expected_window"]
    outcome = activities.execute(turn["id"], decision)
    assert outcome["kind"] == "verified"
    evidence = store.evidence(outcome["evidence_id"])
    assert evidence["rows"][0]["ticker"] == case["expected_winner"]
    assert evidence["rows"][0]["qualifying_days"] == case["expected_qualifying_days"]
    assert evidence["rows"][0]["observed_usable_days"] == case["expected_observed_days"]
    assert evidence["catalog"]["tracked_count"] == case["expected_requested_stocks"]
    assert evidence["eligible_count"] == case["expected_eligible_stocks"]
    assert set(case["required_evidence"]) <= set(evidence)
    assert evidence["data"]["source"] == "synthetic-v1"
    explanation = activities.explain(turn["id"], decision, outcome["evidence_id"])
    activities.finish(
        turn["id"], "completed", decision, outcome["evidence_id"], explanation, None
    )
    assert store.turn(turn["id"])["status"] == "completed"
    assert store.conversation(conversation)["active_turn_id"] is None
    assert model.seen_contexts[0]["recent_turns"] == []
    assert [entry["stage"] for entry in store.trace_for_turn(turn["id"])] == [
        "interpretation",
        "tool_verified",
    ]


def test_validation_rejects_sql_and_excessive_window_without_running_tool(setup):
    store, _, activities = setup
    turn = store.submit(store.create_conversation(), "r", "question", "2026-01-08")
    valid = gain_volume_decision(date(2026, 1, 8)).model_dump(mode="json")
    injected = valid | {"request": valid["request"] | {"sql": "DROP TABLE bars"}}
    assert activities.execute(turn["id"], injected)["kind"] == "rejected"
    oversized = valid | {"request": valid["request"] | {"limit": 100}}
    assert activities.execute(turn["id"], oversized)["kind"] == "rejected"
    assert store.turn(turn["id"])["evidence_id"] is None


def test_idempotency_busy_cancel_and_follow_up_context(setup):
    store, _, activities = setup
    first_conversation = store.create_conversation()
    other_conversation = store.create_conversation()
    first = store.submit(first_conversation, "same", "First question", "2026-01-08")
    assert (
        store.submit(first_conversation, "same", "First question", "2026-01-08")["id"]
        == first["id"]
    )
    with pytest.raises(BusyConversation):
        store.submit(first_conversation, "next", "Follow-up", "2026-01-08")
    with pytest.raises(ValueError):
        store.submit(first_conversation, "same", "Different text", "2026-01-08")
    second = store.submit(
        other_conversation, "same", "Other conversation", "2026-01-08"
    )
    assert activities.load_context(second["id"])["recent_turns"] == []
    store.request_cancel(first["id"])
    assert store.finish(first["id"], "completed")["status"] == "cancel_requested"
    assert store.finish(first["id"], "cancelled")["status"] == "cancelled"
    follow_up = store.submit(
        first_conversation, "next", "What about that stock?", "2026-01-08"
    )
    context = activities.load_context(follow_up["id"])
    assert [row["question"] for row in context["recent_turns"]] == ["First question"]
    assert "Other conversation" not in str(context)


def test_decision_and_frequency_semantics(setup):
    store, _, activities = setup
    assert previous_completed_month(date(2026, 1, 8)) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )
    turn = store.submit(store.create_conversation(), "r", "question", "2026-01-08")
    decision = gain_volume_decision(date(2026, 1, 8)).model_dump(mode="json")
    decision["request"]["limit"] = 5
    activities.limits = Limits(max_rows=5)
    result = store.evidence(activities.execute(turn["id"], decision)["evidence_id"])
    assert result["matched_count"] >= 1
    assert result["rows"][0]["qualifying_fraction"] == "1"
    assert result["rows"][0]["dollar_volume_formulas"][0]["estimated"] is False


def test_absolute_100_days_and_relative_30_of_50_are_distinct():
    fixture = SyntheticFixtureRepository(FIXTURE)
    sessions = [
        day for day in fixture.sessions if date(2025, 1, 1) <= day <= date(2025, 12, 31)
    ][:50]

    class FiftyObservedDays:
        def load(self, start, end):
            dataset = fixture.load(start, end)
            selected = set(sessions)
            qualifying = set(sessions[:30])
            bars = tuple(
                replace(bar, volume=1 if bar.session_date in qualifying else 0)
                if bar.stock_id == "stock-alfa" and bar.session_date in selected
                else bar
                for bar in dataset.bars
                if bar.stock_id != "stock-alfa"
                or bar.session_date in selected
                or bar.session_date < sessions[0]
            )
            return replace(dataset, bars=bars)

    base = {
        "request_version": 1,
        "universe": "latest_published_catalog",
        "window": {"start": sessions[0], "end": sessions[-1]},
        "grain": "stock",
        "measures": [
            "period_return",
            "qualifying_days",
            "qualifying_fraction",
            "observed_usable_days",
        ],
        "daily_conditions": [
            {"field": "volume", "operator": ">", "value": 0, "unit": "shares"}
        ],
        "predicates": [{"field": "stock_id", "operator": "=", "value": "stock-alfa"}],
        "sort": {"measure": "period_return"},
        "limit": 1,
    }
    service = AnalyticsService(FiftyObservedDays())
    absolute = AnalyticalRequest.model_validate(
        base
        | {
            "reduction": {
                "measure": "qualifying_days",
                "operator": ">=",
                "value": 100,
            }
        }
    )
    relative = AnalyticalRequest.model_validate(
        base
        | {
            "reduction": {
                "measure": "qualifying_fraction",
                "operator": ">=",
                "value": "0.50",
            }
        }
    )
    assert service.execute(absolute)["matched_count"] == 0
    result = service.execute(relative)
    row = result["rows"][0]
    assert (
        row["qualifying_days"],
        row["observed_usable_days"],
        row["requested_sessions"],
    ) == (30, 50, 50)
    assert row["qualifying_fraction"] == Decimal("0.6")


def test_unsupported_and_clarification_are_terminal_without_evidence(setup):
    store, _, _ = setup
    conversation = store.create_conversation()
    causal = store.submit(conversation, "why", "Why did it rise?", "2026-01-08")
    unsupported = Decision(
        kind="unsupported",
        message="Causal explanations need sources outside retained bars",
    )
    store.finish(
        causal["id"],
        "unsupported",
        decision=unsupported.model_dump(mode="json"),
        explanation=unsupported.message,
    )
    assert store.turn(causal["id"])["evidence_id"] is None
    vague = store.submit(conversation, "vague", "What about that?", "2026-01-08")
    store.finish(
        vague["id"], "needs_clarification", explanation="Which metric do you mean?"
    )
    assert store.conversation(conversation)["active_turn_id"] is None


def test_temporal_turn_survives_client_detachment(setup):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    store, _, activities = setup
    conversation = store.create_conversation()
    turn = store.submit(
        conversation,
        "durable",
        "Find the gain and dollar volume leader last month",
        "2026-01-08",
    )

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(
                    environment.client,
                    task_queue="agent-test",
                    workflows=[AgentTurnWorkflow],
                    activities=[
                        activities.load_context,
                        activities.interpret,
                        activities.execute,
                        activities.explain,
                        activities.finish,
                        activities.refresh_summary,
                    ],
                    activity_executor=executor,
                ):
                    handle = await environment.client.start_workflow(
                        AgentTurnWorkflow.run,
                        turn["id"],
                        id=f"agent-turn-{turn['id']}",
                        task_queue="agent-test",
                    )
                    # Reacquire by deterministic ID, as a reconnecting API process would.
                    reconnected = environment.client.get_workflow_handle(handle.id)
                    await reconnected.result()

    asyncio.run(run())
    assert store.turn(turn["id"])["status"] == "completed"
