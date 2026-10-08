"""Agent-owned durable state. One SQLite transaction guards each conversation turn."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import TERMINAL


class BusyConversation(Exception):
    pass


class AgentStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, active_turn_id TEXT, summary TEXT,
                    summary_through_turn_id TEXT, summary_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, question TEXT NOT NULL,
                    reference_date TEXT NOT NULL, status TEXT NOT NULL,
                    decision_json TEXT, evidence_id TEXT, explanation TEXT, error TEXT,
                    created_at TEXT NOT NULL, finished_at TEXT,
                    UNIQUE(conversation_id, request_id),
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                );
                CREATE INDEX IF NOT EXISTS turns_by_conversation
                    ON turns(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY, turn_id TEXT NOT NULL UNIQUE,
                    result_json TEXT NOT NULL,
                    FOREIGN KEY(turn_id) REFERENCES turns(id)
                );
                CREATE TABLE IF NOT EXISTS turn_trace (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, turn_id TEXT NOT NULL,
                    stage TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(turn_id) REFERENCES turns(id)
                );
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        return db

    def create_conversation(self) -> str:
        conversation_id = str(uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO conversations(id) VALUES (?)", (conversation_id,))
        return conversation_id

    def submit(
        self, conversation_id: str, request_id: str, question: str, reference_date: str
    ) -> dict:
        if not question.strip():
            raise ValueError("question is required")
        if len(question) > 4000:
            raise ValueError("question exceeds 4000 characters")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM turns WHERE conversation_id=? AND request_id=?",
                (conversation_id, request_id),
            ).fetchone()
            if existing:
                if existing["question"] != question:
                    raise ValueError("request ID was reused with a different question")
                return dict(existing)
            conversation = db.execute(
                "SELECT active_turn_id FROM conversations WHERE id=?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            if conversation["active_turn_id"]:
                raise BusyConversation(conversation_id)
            turn_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO turns(id, conversation_id, request_id, question, reference_date, status, created_at)
                          VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (turn_id, conversation_id, request_id, question, reference_date, now),
            )
            db.execute(
                "UPDATE conversations SET active_turn_id=? WHERE id=?",
                (turn_id, conversation_id),
            )
            return dict(
                db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            )

    def turn(self, turn_id: str) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            if row is None:
                raise KeyError(turn_id)
            return dict(row)

    def conversation(self, conversation_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            return dict(row)

    def context(self, turn_id: str, recent_count: int = 8) -> dict:
        turn = self.turn(turn_id)
        with self._connect() as db:
            conversation = db.execute(
                "SELECT * FROM conversations WHERE id=?", (turn["conversation_id"],)
            ).fetchone()
            rows = db.execute(
                """SELECT id, question, status, explanation, evidence_id FROM turns
                                 WHERE conversation_id=? AND created_at < ?
                                 ORDER BY created_at DESC LIMIT ?""",
                (turn["conversation_id"], turn["created_at"], recent_count),
            ).fetchall()
            recent = []
            for row in reversed(rows):
                item = dict(row)
                if item["evidence_id"]:
                    evidence = db.execute(
                        "SELECT result_json FROM evidence WHERE id=?",
                        (item["evidence_id"],),
                    ).fetchone()
                    result = json.loads(evidence["result_json"])
                    item["trusted_result"] = {
                        key: result[key]
                        for key in (
                            "resolved_window",
                            "catalog",
                            "data",
                            "market",
                            "eligible_count",
                            "matched_count",
                            "rows",
                            "exclusions",
                        )
                    }
                recent.append(item)
        return {
            "question": turn["question"],
            "reference_date": turn["reference_date"],
            "summary": conversation["summary"],
            "summary_through_turn_id": conversation["summary_through_turn_id"],
            "recent_turns": recent,
        }

    def original_turns(
        self,
        conversation_id: str,
        before_turn_id: str | None = None,
        limit: int | None = 20,
    ) -> list[dict]:
        row_limit = limit if limit is not None else -1
        with self._connect() as db:
            if before_turn_id:
                before = self.turn(before_turn_id)["created_at"]
                rows = db.execute(
                    """SELECT * FROM turns WHERE conversation_id=? AND created_at < ?
                                     ORDER BY created_at DESC LIMIT ?""",
                    (conversation_id, before, row_limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM turns WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
                    (conversation_id, row_limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def save_summary(
        self, conversation_id: str, text: str, through_turn_id: str, version: int = 1
    ) -> None:
        if len(text) > 4000:
            raise ValueError("summary exceeds context bound")
        with self._connect() as db:
            db.execute(
                """UPDATE conversations SET summary=?, summary_through_turn_id=?, summary_version=?
                          WHERE id=?""",
                (text, through_turn_id, version, conversation_id),
            )

    def save_evidence(self, turn_id: str, result: dict) -> str:
        evidence_id = f"evidence-{turn_id}"
        encoded = json.dumps(result, default=str)
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO evidence(id, turn_id, result_json) VALUES (?, ?, ?)",
                (evidence_id, turn_id, encoded),
            )
            db.execute(
                "UPDATE turns SET evidence_id=? WHERE id=? AND status='running'",
                (evidence_id, turn_id),
            )
        return evidence_id

    def trace(self, turn_id: str, stage: str, detail: dict) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO turn_trace(turn_id, stage, detail_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    turn_id,
                    stage,
                    json.dumps(detail, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def trace_for_turn(self, turn_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT stage, detail_json, created_at FROM turn_trace WHERE turn_id=? ORDER BY id",
                (turn_id,),
            ).fetchall()
        return [
            {
                "stage": row["stage"],
                "detail": json.loads(row["detail_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def evidence(self, evidence_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT result_json FROM evidence WHERE id=?", (evidence_id,)
            ).fetchone()
            if row is None:
                raise KeyError(evidence_id)
            return json.loads(row["result_json"])

    def request_cancel(self, turn_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE turns SET status='cancel_requested' WHERE id=? AND status='running'",
                (turn_id,),
            )

    def finish(
        self,
        turn_id: str,
        status: str,
        *,
        decision: dict | None = None,
        evidence_id: str | None = None,
        explanation: str | None = None,
        error: str | None = None,
    ) -> dict:
        if status not in TERMINAL:
            raise ValueError("status must be terminal")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT * FROM turns WHERE id=?", (turn_id,)
            ).fetchone()
            if current is None:
                raise KeyError(turn_id)
            if current["status"] in TERMINAL:
                return dict(current)
            if current["status"] == "cancel_requested" and status != "cancelled":
                return dict(current)
            db.execute(
                """UPDATE turns SET status=?, decision_json=?, evidence_id=COALESCE(?, evidence_id),
                          explanation=?, error=?, finished_at=? WHERE id=?""",
                (
                    status,
                    json.dumps(decision, default=str) if decision else None,
                    evidence_id,
                    explanation,
                    error,
                    datetime.now(timezone.utc).isoformat(),
                    turn_id,
                ),
            )
            db.execute(
                "UPDATE conversations SET active_turn_id=NULL WHERE id=? AND active_turn_id=?",
                (current["conversation_id"], turn_id),
            )
            return dict(
                db.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            )

    def delete_conversation(self, conversation_id: str) -> None:
        if self.conversation(conversation_id)["active_turn_id"]:
            raise BusyConversation(conversation_id)
        with self._connect() as db:
            db.execute(
                "DELETE FROM turn_trace WHERE turn_id IN (SELECT id FROM turns WHERE conversation_id=?)",
                (conversation_id,),
            )
            db.execute(
                "DELETE FROM evidence WHERE turn_id IN (SELECT id FROM turns WHERE conversation_id=?)",
                (conversation_id,),
            )
            db.execute("DELETE FROM turns WHERE conversation_id=?", (conversation_id,))
            db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
