"""Import an old local agent SQLite store into an empty PostgreSQL agent store."""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import psycopg

from .store import AgentStore


def migrate_sqlite_store(source_path: Path, database_url: str) -> int:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    # Upgrades the older local conversation-index schema before the copy.
    AgentStore(source_path)
    with sqlite3.connect(source_path) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN IMMEDIATE")
        conversations = source.execute("SELECT * FROM conversations").fetchall()
        turns = source.execute(
            "SELECT * FROM turns ORDER BY created_at, rowid"
        ).fetchall()
        evidence = source.execute("SELECT * FROM evidence").fetchall()
        trace = source.execute("SELECT * FROM turn_trace ORDER BY id").fetchall()
        with psycopg.connect(
            database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as target:
            if target.execute("SELECT 1 FROM agent_conversation LIMIT 1").fetchone():
                raise RuntimeError("PostgreSQL agent store must be empty before import")
            for row in conversations:
                target.execute(
                    """INSERT INTO agent_conversation
                       (id, summary, summary_through_turn_id, summary_version,
                        created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        row["id"],
                        row["summary"],
                        row["summary_through_turn_id"],
                        row["summary_version"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
            for row in turns:
                target.execute(
                    """INSERT INTO agent_turn
                       (id, conversation_id, request_id, question, reference_date,
                        status, decision_json, evidence_id, explanation, error,
                        created_at, finished_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    tuple(
                        row[key]
                        for key in (
                            "id",
                            "conversation_id",
                            "request_id",
                            "question",
                            "reference_date",
                            "status",
                            "decision_json",
                            "evidence_id",
                            "explanation",
                            "error",
                            "created_at",
                            "finished_at",
                        )
                    ),
                )
            for row in evidence:
                target.execute(
                    """INSERT INTO agent_evidence(id, turn_id, result_json)
                       VALUES (%s, %s, %s)""",
                    (row["id"], row["turn_id"], row["result_json"]),
                )
            for row in trace:
                target.execute(
                    """INSERT INTO agent_turn_trace
                       (turn_id, stage, detail_json, created_at)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        row["turn_id"],
                        row["stage"],
                        row["detail_json"],
                        row["created_at"],
                    ),
                )
            for row in conversations:
                if row["active_turn_id"]:
                    target.execute(
                        "UPDATE agent_conversation SET active_turn_id=%s WHERE id=%s",
                        (row["active_turn_id"], row["id"]),
                    )
    return len(conversations)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("AGENT_DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("AGENT_DATABASE_URL or --database-url is required")
    count = migrate_sqlite_store(args.source, args.database_url)
    print(f"Imported {count} agent conversations")


if __name__ == "__main__":
    main()
