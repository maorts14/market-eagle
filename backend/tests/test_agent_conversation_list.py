"""The shared conversation index survives old local stores and API reloads."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_eagle.agent.api import create_agent_router
from market_eagle.agent.models import Limits
from market_eagle.agent.store import AgentStore


def test_conversation_list_shows_titles_and_deletions(tmp_path):
    store = AgentStore(tmp_path / "agent.sqlite")
    app = FastAPI()
    app.include_router(create_agent_router(store, None, Limits()))
    api = TestClient(app)

    first = api.post("/api/v1/agent/conversations").json()["conversation_id"]
    second = api.post("/api/v1/agent/conversations").json()["conversation_id"]
    store.submit(first, "request-1", "Which stock led last month?", "2026-10-09")

    rows = api.get("/api/v1/agent/conversations").json()["conversations"]
    assert [row["conversation_id"] for row in rows] == [first, second]
    assert rows[0]["title"] == "Which stock led last month?"
    assert rows[0]["active_turn_id"] is not None
    assert rows[0]["updated_at"]
    assert rows[1]["title"] == "New conversation"

    assert api.delete(f"/api/v1/agent/conversations/{second}").status_code == 200
    assert [
        row["conversation_id"]
        for row in api.get("/api/v1/agent/conversations").json()["conversations"]
    ] == [first]


def test_old_conversation_schema_migrates_with_original_turn_time(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE conversations (
                id TEXT PRIMARY KEY, active_turn_id TEXT, summary TEXT,
                summary_through_turn_id TEXT, summary_version INTEGER NOT NULL DEFAULT 1
            )"""
        )
        db.execute("INSERT INTO conversations(id) VALUES ('old-conversation')")

    store = AgentStore(path)
    rows = store.list_conversations()
    assert rows[0]["conversation_id"] == "old-conversation"
    assert rows[0]["title"] == "New conversation"
    assert rows[0]["updated_at"]
    assert AgentStore(path).list_conversations() == rows
