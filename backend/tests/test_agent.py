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
from temporalio import workflow

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_eagle.agent.activities import AgentActivities
from market_eagle.agent.api import public_turn, reconcile_turn
from market_eagle.agent.models import Decision, Limits, previous_completed_month
from market_eagle.agent.store import AgentStore, BusyConversation
from market_eagle.agent.workflow import AgentTurnWorkflow
from market_eagle.analytics.fixture_repository import SyntheticFixtureRepository
from market_eagle.analytics.models import AnalyticalRequest
from market_eagle.analytics.service import AnalyticsService

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic-v1"


@workflow.defn(sandboxed=False)
class WaitingForCancel:
    @workflow.run
    async def run(self):
        await workflow.sleep(3600)


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
        return " | ".join(
            item.get("prior_summary") or item["question"] for item in turns
        )[-4000:]


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
    rendered = public_turn(store, store.turn(turn["id"]))
    assert rendered["trusted_result"]["ranking_scope"] == "eligible_stocks_only"
    assert (
        rendered["trusted_result"]["coverage_label"]
        == "Evaluated 4 of 5 tracked stocks"
    )
    assert rendered["trusted_result"]["eligible_count"] == 4
    assert rendered["trusted_result"]["catalog"]["tracked_count"] == 5
    assert rendered["trusted_result"]["data"]["return_rankings_trusted"] is False
    assert "all five" not in rendered["agent_explanation"].lower()
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
                    # The store commit happened above. Simulate the API dying before start.
                    await reconcile_turn(
                        store, environment.client, turn["id"], Limits(), "agent-test"
                    )
                    await reconcile_turn(
                        store, environment.client, turn["id"], Limits(), "agent-test"
                    )
                    reconnected = environment.client.get_workflow_handle(
                        f"agent-turn-{turn['id']}"
                    )
                    await reconnected.result()

    asyncio.run(run())
    assert store.turn(turn["id"])["status"] == "completed"


def test_cancel_requested_reconciles_after_crash(setup):
    from temporalio.service import RPCError, RPCStatusCode
    from temporalio.testing import WorkflowEnvironment

    store, _, _ = setup
    conversation = store.create_conversation()
    turn = store.submit(conversation, "cancel-crash", "Research this", "2026-01-08")
    store.request_cancel(turn["id"])

    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as environment:
            await reconcile_turn(
                store, environment.client, turn["id"], Limits(), "agent-cancel-test"
            )
            await reconcile_turn(
                store, environment.client, turn["id"], Limits(), "agent-cancel-test"
            )
            handle = environment.client.get_workflow_handle(f"agent-turn-{turn['id']}")
            with pytest.raises(RPCError) as missing:
                await handle.describe()
            assert missing.value.status == RPCStatusCode.NOT_FOUND

    asyncio.run(run())
    assert store.turn(turn["id"])["status"] == "cancelled"
    assert store.conversation(conversation)["active_turn_id"] is None


def test_cancel_requested_reconciles_existing_workflow(setup):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    store, _, _ = setup
    conversation = store.create_conversation()
    turn = store.submit(conversation, "cancel-running", "Research this", "2026-01-08")

    async def run():
        async with (
            await WorkflowEnvironment.start_time_skipping() as environment,
            Worker(
                environment.client,
                task_queue="agent-existing-cancel-test",
                workflows=[WaitingForCancel],
            ),
        ):
            await environment.client.start_workflow(
                WaitingForCancel.run,
                id=f"agent-turn-{turn['id']}",
                task_queue="agent-existing-cancel-test",
            )
            store.request_cancel(turn["id"])
            await reconcile_turn(
                store,
                environment.client,
                turn["id"],
                Limits(),
                "agent-existing-cancel-test",
            )

    asyncio.run(run())
    assert store.turn(turn["id"])["status"] == "cancelled"
    assert store.conversation(conversation)["active_turn_id"] is None


def test_transient_start_failure_keeps_turn_recoverable(setup):
    store, _, _ = setup
    conversation = store.create_conversation()
    turn = store.submit(conversation, "offline", "Research this", "2026-01-08")

    class OfflineTemporal:
        async def start_workflow(self, *args, **kwargs):
            raise OSError("Temporal connection unavailable")

    with pytest.raises(OSError):
        asyncio.run(
            reconcile_turn(store, OfflineTemporal(), turn["id"], Limits(), "agent-test")
        )
    assert store.turn(turn["id"])["status"] == "running"
    assert store.conversation(conversation)["active_turn_id"] == turn["id"]


def test_grounded_follow_up_uses_prior_trusted_result(setup):
    store, _, activities = setup
    conversation = store.create_conversation()
    first = store.submit(
        conversation, "first", "Find the leader last month", "2026-01-08"
    )
    decision = gain_volume_decision(date(2026, 1, 8)).model_dump(mode="json")
    evidence_id = activities.execute(first["id"], decision)["evidence_id"]
    activities.finish(
        first["id"],
        "completed",
        decision,
        evidence_id,
        "EPSI led among eligible stocks",
        None,
    )
    follow = store.submit(
        conversation, "follow", "How did that stock perform?", "2026-01-08"
    )
    context = activities.load_context(follow["id"])
    prior = context["recent_turns"][-1]
    assert prior["trusted_result"]["rows"][0]["ticker"] == "EPSI"
    assert prior["trusted_result"]["eligible_count"] == 4

    class FollowingModel(FakeModel):
        def interpret(self, context, *, feedback=None):
            trusted = context["recent_turns"][-1]["trusted_result"]
            return Decision.model_validate(
                {
                    "kind": "query",
                    "request": {
                        "request_version": 1,
                        "universe": "latest_published_catalog",
                        "window": {"start": "2025-12-01", "end": "2025-12-31"},
                        "grain": "stock",
                        "measures": ["period_return"],
                        "predicates": [
                            {
                                "field": "ticker",
                                "operator": "=",
                                "value": trusted["rows"][0]["ticker"],
                            }
                        ],
                        "sort": {"measure": "period_return", "direction": "desc"},
                        "limit": 1,
                    },
                }
            )

    activities.model = FollowingModel(gain_volume_decision(date(2026, 1, 8)))
    follow_decision = activities.interpret(follow["id"], context, None)
    assert follow_decision["request"]["predicates"][0]["value"] == "EPSI"
    result = store.evidence(
        activities.execute(follow["id"], follow_decision)["evidence_id"]
    )
    assert result["rows"][0]["ticker"] == "EPSI"
    assert (
        result["rows"][0]["period_return"]
        == prior["trusted_result"]["rows"][0]["period_return"]
    )


def test_summary_carries_context_beyond_thirty_turns(setup):
    store, _, activities = setup
    conversation = store.create_conversation()
    for index in range(40):
        turn = store.submit(
            conversation, f"request-{index}", f"question-{index}", "2026-01-08"
        )
        store.finish(turn["id"], "unsupported", explanation="No calculation")
        activities.refresh_summary(turn["id"])
    summary = store.conversation(conversation)["summary"]
    assert "question-0" in summary
    assert "question-31" in summary
    assert len(store.original_turns(conversation, limit=None)) == 40
