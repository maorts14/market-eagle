"""Reconnectable conversation API backed by Temporal workflow IDs."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from temporalio.client import Client, WorkflowAlreadyStartedError, WorkflowFailureError
from temporalio.service import RPCError

from .models import Limits
from .store import AgentStore, BusyConversation
from .workflow import AgentTurnWorkflow


class SubmitBody(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)


def workflow_id(turn_id: str) -> str:
    return f"agent-turn-{turn_id}"


def create_agent_router(
    store: AgentStore,
    temporal: Client,
    limits: Limits,
    reference_date: Callable[[], date] = date.today,
    task_queue: str = "market-eagle-agent",
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/agent")

    @router.post("/conversations")
    def create_conversation():
        return {"conversation_id": store.create_conversation()}

    @router.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str):
        try:
            current = store.conversation(conversation_id)
        except KeyError:
            raise HTTPException(404, "Conversation not found") from None
        return {
            "conversation_id": conversation_id,
            "active_turn_id": current["active_turn_id"],
            "turns": [
                public_turn(store, turn)
                for turn in reversed(store.original_turns(conversation_id, limit=None))
            ],
        }

    @router.post("/conversations/{conversation_id}/turns")
    async def submit(conversation_id: str, body: SubmitBody):
        try:
            turn = store.submit(
                conversation_id,
                body.request_id,
                body.question,
                reference_date().isoformat(),
            )
        except KeyError:
            raise HTTPException(404, "Conversation not found") from None
        except BusyConversation:
            raise HTTPException(409, "Conversation has an active turn") from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if turn["status"] == "running":
            try:
                await temporal.start_workflow(
                    AgentTurnWorkflow.run,
                    turn["id"],
                    limits.max_repair_attempts,
                    limits.max_tool_calls,
                    id=workflow_id(turn["id"]),
                    task_queue=task_queue,
                )
            except WorkflowAlreadyStartedError:
                pass
            except Exception as error:
                store.finish(
                    turn["id"],
                    "failed",
                    error=f"Workflow start failed: {type(error).__name__}",
                )
                raise HTTPException(503, "Could not start agent turn") from error
        return public_turn(store, store.turn(turn["id"]))

    @router.get("/turns/{turn_id}")
    def get_turn(turn_id: str):
        try:
            return public_turn(store, store.turn(turn_id))
        except KeyError:
            raise HTTPException(404, "Turn not found") from None

    @router.get("/turns/{turn_id}/trace")
    def get_trace(turn_id: str):
        try:
            store.turn(turn_id)
            return {"turn_id": turn_id, "events": store.trace_for_turn(turn_id)}
        except KeyError:
            raise HTTPException(404, "Turn not found") from None

    @router.get("/evidence/{evidence_id}")
    def get_evidence(evidence_id: str):
        try:
            return store.evidence(evidence_id)
        except KeyError:
            raise HTTPException(404, "Evidence not found") from None

    async def cancel_active(turn_id: str) -> None:
        turn = store.turn(turn_id)
        if turn["status"] in {"running", "cancel_requested"}:
            store.request_cancel(turn_id)
            handle = temporal.get_workflow_handle(workflow_id(turn_id))
            try:
                await handle.cancel()
            except RPCError:
                if store.turn(turn_id)["status"] not in {
                    "completed",
                    "needs_clarification",
                    "unsupported",
                    "failed",
                }:
                    raise
            try:
                await handle.result()
            except WorkflowFailureError:
                pass
            store.finish(turn_id, "cancelled")

    @router.post("/turns/{turn_id}/cancel")
    async def cancel(turn_id: str):
        try:
            await cancel_active(turn_id)
            return public_turn(store, store.turn(turn_id))
        except KeyError:
            raise HTTPException(404, "Turn not found") from None

    @router.delete("/conversations/{conversation_id}")
    async def delete(conversation_id: str):
        try:
            current = store.conversation(conversation_id)
            if current["active_turn_id"]:
                await cancel_active(current["active_turn_id"])
            store.delete_conversation(conversation_id)
        except KeyError:
            raise HTTPException(404, "Conversation not found") from None
        return {"deleted": True}

    return router


def public_turn(store: AgentStore, turn: dict) -> dict:
    evidence = store.evidence(turn["evidence_id"]) if turn["evidence_id"] else None
    trusted = None
    if evidence is not None:
        trusted = {
            key: evidence[key]
            for key in (
                "request_version",
                "metric_version",
                "requested_window",
                "resolved_window",
                "catalog",
                "data",
                "market",
                "eligible_count",
                "matched_count",
                "exclusions",
                "rows",
                "calculated_at",
            )
        }
    return {
        "turn_id": turn["id"],
        "conversation_id": turn["conversation_id"],
        "question": turn["question"],
        "status": turn["status"],
        "decision": json.loads(turn["decision_json"])
        if turn["decision_json"]
        else None,
        "trusted_result": trusted,
        "evidence_id": turn["evidence_id"],
        "agent_explanation": turn["explanation"],
        "error": turn["error"],
    }
