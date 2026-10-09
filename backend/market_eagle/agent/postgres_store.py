"""PostgreSQL research state shared by the API and Temporal worker."""

from __future__ import annotations

import json
from datetime import date, datetime
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .models import TERMINAL
from .store import BusyConversation


def _record(row: dict) -> dict:
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in row.items()
    }


class PostgresAgentStore:
    def __init__(self, database_url: str):
        self.database_url = database_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def create_conversation(self) -> str:
        conversation_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO agent_conversation(id) VALUES (%s)", (conversation_id,)
            )
        return conversation_id

    def list_conversations(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT c.id AS conversation_id, c.active_turn_id, c.updated_at,
                          COALESCE(first_turn.question, 'New conversation') AS title
                   FROM agent_conversation c
                   LEFT JOIN LATERAL (
                       SELECT question FROM agent_turn t
                       WHERE t.conversation_id = c.id
                       ORDER BY t.sequence_id LIMIT 1
                   ) first_turn ON true
                   ORDER BY c.updated_at DESC, c.id DESC"""
            ).fetchall()
        return [_record(row) for row in rows]

    def submit(
        self, conversation_id: str, request_id: str, question: str, reference_date: str
    ) -> dict:
        if not question.strip():
            raise ValueError("question is required")
        if len(question) > 4000:
            raise ValueError("question exceeds 4000 characters")
        with self._connect() as db:
            conversation = db.execute(
                "SELECT active_turn_id FROM agent_conversation WHERE id=%s FOR UPDATE",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)
            existing = db.execute(
                "SELECT * FROM agent_turn WHERE conversation_id=%s AND request_id=%s",
                (conversation_id, request_id),
            ).fetchone()
            if existing:
                if existing["question"] != question:
                    raise ValueError("request ID was reused with a different question")
                return _record(existing)
            if conversation["active_turn_id"]:
                raise BusyConversation(conversation_id)
            turn_id = str(uuid4())
            turn = db.execute(
                """INSERT INTO agent_turn
                   (id, conversation_id, request_id, question, reference_date, status)
                   VALUES (%s, %s, %s, %s, %s, 'running') RETURNING *""",
                (turn_id, conversation_id, request_id, question, reference_date),
            ).fetchone()
            db.execute(
                """UPDATE agent_conversation
                   SET active_turn_id=%s, updated_at=clock_timestamp() WHERE id=%s""",
                (turn_id, conversation_id),
            )
            return _record(turn)

    def turn(self, turn_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM agent_turn WHERE id=%s", (turn_id,)
            ).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return _record(row)

    def conversation(self, conversation_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM agent_conversation WHERE id=%s", (conversation_id,)
            ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        return _record(row)

    def context(self, turn_id: str, recent_count: int = 8) -> dict:
        with self._connect() as db:
            turn = db.execute(
                """SELECT t.question, t.reference_date, t.conversation_id,
                          t.sequence_id, c.summary, c.summary_through_turn_id
                   FROM agent_turn t JOIN agent_conversation c ON c.id=t.conversation_id
                   WHERE t.id=%s""",
                (turn_id,),
            ).fetchone()
            if turn is None:
                raise KeyError(turn_id)
            rows = db.execute(
                """SELECT t.id, t.question, t.status, t.explanation, t.evidence_id,
                          e.result_json
                   FROM agent_turn t LEFT JOIN agent_evidence e ON e.id=t.evidence_id
                   WHERE t.conversation_id=%s AND t.sequence_id < %s
                   ORDER BY t.sequence_id DESC LIMIT %s""",
                (turn["conversation_id"], turn["sequence_id"], recent_count),
            ).fetchall()
        recent = []
        for row in reversed(rows):
            result_json = row.pop("result_json")
            if result_json:
                result = json.loads(result_json)
                row["trusted_result"] = {
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
            recent.append(row)
        return {
            "question": turn["question"],
            "reference_date": turn["reference_date"].isoformat(),
            "summary": turn["summary"],
            "summary_through_turn_id": turn["summary_through_turn_id"],
            "recent_turns": recent,
        }

    def original_turns(
        self,
        conversation_id: str,
        before_turn_id: str | None = None,
        limit: int | None = 20,
    ) -> list[dict]:
        with self._connect() as db:
            query = "SELECT * FROM agent_turn WHERE conversation_id=%s"
            parameters: list = [conversation_id]
            if before_turn_id:
                before = db.execute(
                    "SELECT sequence_id FROM agent_turn WHERE id=%s",
                    (before_turn_id,),
                ).fetchone()
                if before is None:
                    raise KeyError(before_turn_id)
                query += " AND sequence_id < %s"
                parameters.append(before["sequence_id"])
            query += " ORDER BY sequence_id DESC"
            if limit is not None:
                query += " LIMIT %s"
                parameters.append(limit)
            rows = db.execute(query, parameters).fetchall()
        return [_record(row) for row in rows]

    def save_summary(
        self, conversation_id: str, text: str, through_turn_id: str, version: int = 1
    ) -> None:
        if len(text) > 4000:
            raise ValueError("summary exceeds context bound")
        with self._connect() as db:
            db.execute(
                """UPDATE agent_conversation SET summary=%s,
                   summary_through_turn_id=%s, summary_version=%s WHERE id=%s""",
                (text, through_turn_id, version, conversation_id),
            )

    def save_evidence(self, turn_id: str, result: dict) -> str:
        evidence_id = f"evidence-{turn_id}"
        with self._connect() as db:
            db.execute(
                """INSERT INTO agent_evidence(id, turn_id, result_json)
                   VALUES (%s, %s, %s) ON CONFLICT (turn_id) DO NOTHING""",
                (evidence_id, turn_id, json.dumps(result, default=str)),
            )
            db.execute(
                """UPDATE agent_turn SET evidence_id=%s
                   WHERE id=%s AND status='running'""",
                (evidence_id, turn_id),
            )
        return evidence_id

    def trace(self, turn_id: str, stage: str, detail: dict) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO agent_turn_trace(turn_id, stage, detail_json)
                   VALUES (%s, %s, %s)""",
                (turn_id, stage, json.dumps(detail, default=str)),
            )

    def trace_for_turn(self, turn_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT stage, detail_json, created_at FROM agent_turn_trace
                   WHERE turn_id=%s ORDER BY id""",
                (turn_id,),
            ).fetchall()
        return [
            {
                "stage": row["stage"],
                "detail": json.loads(row["detail_json"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def evidence(self, evidence_id: str) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT result_json FROM agent_evidence WHERE id=%s", (evidence_id,)
            ).fetchone()
        if row is None:
            raise KeyError(evidence_id)
        return json.loads(row["result_json"])

    def request_cancel(self, turn_id: str) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE agent_turn SET status='cancel_requested'
                   WHERE id=%s AND status='running'""",
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
            owner = db.execute(
                "SELECT conversation_id FROM agent_turn WHERE id=%s", (turn_id,)
            ).fetchone()
            if owner is None:
                raise KeyError(turn_id)
            db.execute(
                "SELECT id FROM agent_conversation WHERE id=%s FOR UPDATE",
                (owner["conversation_id"],),
            )
            current = db.execute(
                "SELECT * FROM agent_turn WHERE id=%s FOR UPDATE", (turn_id,)
            ).fetchone()
            if current is None:
                raise KeyError(turn_id)
            if current["status"] in TERMINAL:
                return _record(current)
            if current["status"] == "cancel_requested" and status != "cancelled":
                return _record(current)
            updated = db.execute(
                """UPDATE agent_turn SET status=%s, decision_json=%s,
                   evidence_id=COALESCE(%s, evidence_id), explanation=%s, error=%s,
                   finished_at=clock_timestamp() WHERE id=%s RETURNING *""",
                (
                    status,
                    json.dumps(decision, default=str) if decision else None,
                    evidence_id,
                    explanation,
                    error,
                    turn_id,
                ),
            ).fetchone()
            db.execute(
                """UPDATE agent_conversation SET active_turn_id=NULL,
                   updated_at=clock_timestamp()
                   WHERE id=%s AND active_turn_id=%s""",
                (owner["conversation_id"], turn_id),
            )
            return _record(updated)

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT active_turn_id FROM agent_conversation WHERE id=%s FOR UPDATE",
                (conversation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            if row["active_turn_id"]:
                raise BusyConversation(conversation_id)
            db.execute("DELETE FROM agent_conversation WHERE id=%s", (conversation_id,))
