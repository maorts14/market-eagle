"""Agent state is transactional across independent PostgreSQL connections."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from market_eagle.agent.migrate_sqlite import migrate_sqlite_store
from market_eagle.agent.postgres_store import PostgresAgentStore
from market_eagle.agent.store import AgentStore, BusyConversation

pytestmark = pytest.mark.synthetic_integration


@pytest.fixture
def store():
    database_url = os.environ.get("AGENT_DATABASE_URL")
    if not database_url:
        pytest.skip("disposable agent PostgreSQL database is not configured")
    with psycopg.connect(database_url) as db:
        user, agent_write, market_read = db.execute(
            """SELECT current_user,
                      has_table_privilege(current_user, 'agent_turn', 'INSERT'),
                      has_table_privilege(current_user, 'security', 'SELECT')"""
        ).fetchone()
    assert user == "market_eagle_agent"
    assert agent_write is True
    assert market_read is False
    return PostgresAgentStore(database_url)


def test_submission_serializes_and_replays_idempotently(store):
    conversation_id = store.create_conversation()
    other = PostgresAgentStore(store.database_url)

    def submit(index: int):
        try:
            return other.submit(
                conversation_id, f"request-{index}", "Which stock led?", "2026-10-09"
            )
        except BusyConversation:
            return None

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(submit, range(8)))
        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        first = winners[0]
        assert (
            store.submit(
                conversation_id, first["request_id"], first["question"], "2026-10-09"
            )["id"]
            == first["id"]
        )
        with pytest.raises(ValueError, match="request ID was reused"):
            store.submit(
                conversation_id, first["request_id"], "Different", "2026-10-09"
            )
        assert store.list_conversations()[0]["title"] == "Which stock led?"
        with pytest.raises(BusyConversation):
            store.delete_conversation(conversation_id)
        store.request_cancel(first["id"])
        assert store.turn(first["id"])["status"] == "cancel_requested"
        assert store.finish(first["id"], "completed")["status"] == "cancel_requested"
        assert store.finish(first["id"], "cancelled")["status"] == "cancelled"
        assert store.finish(first["id"], "failed")["status"] == "cancelled"
        assert store.conversation(conversation_id)["active_turn_id"] is None
    finally:
        active = store.conversation(conversation_id)["active_turn_id"]
        if active:
            store.finish(active, "cancelled")
        store.delete_conversation(conversation_id)


def test_evidence_context_trace_and_cascade_delete(store):
    conversation_id = store.create_conversation()
    first = store.submit(conversation_id, "one", "First question", "2026-10-09")
    evidence_id = f"evidence-{first['id']}"
    result = {
        "resolved_window": {},
        "catalog": {},
        "data": {},
        "market": {},
        "eligible_count": 1,
        "matched_count": 1,
        "rows": [],
        "exclusions": [],
    }
    try:
        assert store.save_evidence(first["id"], result) == evidence_id
        assert store.save_evidence(first["id"], result) == evidence_id
        store.trace(first["id"], "tool_verified", {"evidence_id": evidence_id})
        assert store.trace_for_turn(first["id"])[0]["detail"] == {
            "evidence_id": evidence_id
        }
        assert store.evidence(evidence_id) == result
        finished = store.finish(first["id"], "completed", evidence_id=evidence_id)
        assert finished["evidence_id"] == evidence_id
        second = store.submit(conversation_id, "two", "Follow-up", "2026-10-09")
        context = store.context(second["id"])
        assert context["recent_turns"][0]["trusted_result"] == result
        assert [turn["id"] for turn in store.original_turns(conversation_id)] == [
            second["id"],
            first["id"],
        ]
        assert [
            turn["id"]
            for turn in store.original_turns(
                conversation_id, before_turn_id=second["id"]
            )
        ] == [first["id"]]
        store.save_summary(conversation_id, "Earlier context", first["id"])
        assert store.context(second["id"])["summary"] == "Earlier context"
        store.finish(second["id"], "cancelled")
        store.delete_conversation(conversation_id)
        with pytest.raises(KeyError):
            store.evidence(evidence_id)
        with psycopg.connect(store.database_url) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM agent_turn_trace WHERE turn_id=%s",
                    (first["id"],),
                ).fetchone()[0]
                == 0
            )
    finally:
        try:
            active = store.conversation(conversation_id)["active_turn_id"]
        except KeyError:
            pass
        else:
            if active:
                store.finish(active, "cancelled")
            store.delete_conversation(conversation_id)


def test_imports_existing_sqlite_conversations_into_empty_postgres(store, tmp_path):
    source = AgentStore(tmp_path / "old-agent.sqlite")
    conversation_id = source.create_conversation()
    turn = source.submit(conversation_id, "old-request", "Older question", "2026-10-09")
    source.trace(turn["id"], "interpretation", {"kind": "clarification"})
    source.finish(turn["id"], "needs_clarification", explanation="Which stock?")

    try:
        assert migrate_sqlite_store(source.path, store.database_url) == 1
        assert store.conversation(conversation_id)["active_turn_id"] is None
        assert store.original_turns(conversation_id)[0]["question"] == "Older question"
        assert store.trace_for_turn(turn["id"])[0]["detail"] == {
            "kind": "clarification"
        }
        with pytest.raises(RuntimeError, match="must be empty"):
            migrate_sqlite_store(source.path, store.database_url)
    finally:
        store.delete_conversation(conversation_id)
