"""Deterministic Temporal coordinator; payloads contain IDs and bounded decisions."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, TemporalError


@workflow.defn
class AgentTurnWorkflow:
    @workflow.run
    async def run(
        self, turn_id: str, max_repair_attempts: int = 1, max_tool_calls: int = 2
    ) -> None:
        async def call(name: str, *args, seconds: int = 30):
            return await workflow.execute_activity(
                name,
                args=args,
                start_to_close_timeout=timedelta(seconds=seconds),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        decision = None
        evidence_id = None
        try:
            context = await call("agent_load_context", turn_id)
            feedback = None
            for attempt in range(max_repair_attempts + 1):
                decision = await call(
                    "agent_interpret", turn_id, context, feedback, seconds=60
                )
                kind = decision["kind"]
                if kind in ("clarification", "unsupported"):
                    status = (
                        "needs_clarification"
                        if kind == "clarification"
                        else "unsupported"
                    )
                    await call(
                        "agent_finish",
                        turn_id,
                        status,
                        decision,
                        None,
                        decision.get("message"),
                        None,
                    )
                    return
                if kind != "query":
                    feedback = (
                        "Decision kind must be query, clarification, or unsupported"
                    )
                    continue
                if attempt >= max_tool_calls:
                    break
                outcome = await call("agent_execute", turn_id, decision)
                if outcome["kind"] == "verified":
                    evidence_id = outcome["evidence_id"]
                    try:
                        explanation = await call(
                            "agent_explain", turn_id, decision, evidence_id, seconds=60
                        )
                    except ActivityError:
                        workflow.logger.warning(
                            "Narrative explanation unavailable for turn %s", turn_id
                        )
                        explanation = None
                    await call(
                        "agent_finish",
                        turn_id,
                        "completed",
                        decision,
                        evidence_id,
                        explanation,
                        None,
                    )
                    try:
                        await call("agent_refresh_summary", turn_id, seconds=60)
                    except TemporalError:
                        workflow.logger.warning(
                            "Conversation summary refresh failed for %s", turn_id
                        )
                    return
                if outcome["kind"] == "failed":
                    await call(
                        "agent_finish",
                        turn_id,
                        "failed",
                        decision,
                        None,
                        None,
                        outcome["reason"],
                    )
                    return
                feedback = outcome["reason"]
            await call(
                "agent_finish",
                turn_id,
                "failed",
                decision,
                evidence_id,
                None,
                "Could not validate a supported analytical request within the turn budget",
            )
        except Exception as error:
            await call(
                "agent_finish",
                turn_id,
                "failed",
                decision,
                evidence_id,
                None,
                str(error)[:300],
            )
            raise
