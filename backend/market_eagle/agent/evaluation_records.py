"""Export bounded agent answers and prepare human review records."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .api import public_turn
from .models import TERMINAL
from .postgres_store import PostgresAgentStore
from .store import AgentStore

CASES = Path(__file__).with_name("evaluation-v1.json")
CRITERIA = ("grounding", "completeness", "clarity", "conversation_use")
SECRET_KEY = re.compile(
    r"(?:api.?key|password|secret|authorization|credential|token)", re.IGNORECASE
)
SECRET_VALUE = re.compile(
    r"(?:sk-or-v1-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|"
    r"(?:OPENROUTER_API_KEY|ALPACA_API_SECRET_KEY|APP_DB_PASSWORD|"
    r"AGENT_DATABASE_URL|DATABASE_URL)\s*[:=]|postgres(?:ql)?://[^\s@]+@)",
    re.IGNORECASE,
)


def _reject_credentials(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY.search(key):
                raise ValueError("export contains a credential field")
            _reject_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _reject_credentials(child)
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        raise ValueError("export contains a possible credential")


def load_cases(path: Path = CASES) -> tuple[str, dict[str, dict]]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in dataset["cases"]}
    if len(cases) != len(dataset["cases"]):
        raise ValueError("evaluation case IDs must be unique")
    return dataset["version"], cases


def build_input_record(
    store: AgentStore | PostgresAgentStore,
    case: dict,
    *,
    dataset_version: str,
    run_id: str,
    model_id: str,
    turn_id: str,
) -> dict:
    turn = store.turn(turn_id)
    if turn["question"] != case["question"]:
        raise ValueError(f"turn question does not match case {case['id']}")
    if case.get("reference_date") and turn["reference_date"] != case["reference_date"]:
        raise ValueError(f"turn reference date does not match case {case['id']}")
    if turn["status"] not in TERMINAL:
        raise ValueError(f"turn {turn_id} is not terminal")
    rendered = public_turn(store, turn)
    context = store.context(turn_id)
    trace = store.trace_for_turn(turn_id)
    expected = {
        key: value for key, value in case.items() if key.startswith("expected_")
    }
    record = {
        "case_id": case["id"],
        "dataset_version": dataset_version,
        "run_id": run_id,
        "model_id": model_id,
        "metric_version": (
            rendered["trusted_result"]["metric_version"]
            if rendered["trusted_result"] is not None
            else None
        ),
        "turn_id": turn_id,
        "status": turn["status"],
        "question": turn["question"],
        "conversation_context": context["recent_turns"],
        "trusted_result": rendered["trusted_result"],
        "model_decision": rendered["decision"],
        "agent_explanation": rendered["agent_explanation"],
        "expected_facts": expected,
        "required_evidence": case.get("required_evidence", []),
        "forbidden_claims": case.get("forbidden_claims", []),
        "rubric": case.get("rubric", {}),
        "trace_ref": f"/api/v1/agent/turns/{turn_id}/trace",
        "trace_stages": [
            {"stage": event["stage"], "created_at": event["created_at"]}
            for event in trace
        ],
    }
    _reject_credentials(record)
    return record


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def export_inputs(
    store: AgentStore | PostgresAgentStore,
    manifest_path: Path,
    output_path: Path,
    cases_path: Path = CASES,
) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = manifest["run_id"]
    model_id = manifest["model_id"]
    assignments = manifest["records"]
    if not run_id or not model_id or not assignments:
        raise ValueError("manifest requires run_id, model_id, and records")
    dataset_version, cases = load_cases(cases_path)
    seen = set()
    rows = []
    for assignment in assignments:
        case_id = assignment["case_id"]
        if case_id in seen:
            raise ValueError(f"case {case_id} appears twice in one run")
        seen.add(case_id)
        rows.append(
            build_input_record(
                store,
                cases[case_id],
                dataset_version=dataset_version,
                run_id=run_id,
                model_id=model_id,
                turn_id=assignment["turn_id"],
            )
        )
    _write_jsonl(output_path, rows)
    return len(rows)


def prepare_reviews(inputs_path: Path, output_path: Path) -> int:
    inputs = _read_jsonl(inputs_path)
    rows = [
        {
            "case_id": item["case_id"],
            "run_id": item["run_id"],
            "reviewer_id": None,
            "reviewed_at": None,
            "criteria": {
                name: {"verdict": None, "reason": None, "evidence": None}
                for name in CRITERIA
            },
            "critical_failure": None,
            "critical_reason": None,
        }
        for item in inputs
    ]
    _write_jsonl(output_path, rows)
    return len(rows)


class CriterionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "fail", "not_applicable"]
    reason: str = Field(min_length=1)
    evidence: str | None = None

    @model_validator(mode="after")
    def supporting_evidence(self):
        if self.verdict != "not_applicable" and not self.evidence:
            raise ValueError("applicable criteria require supporting evidence")
        return self


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    criteria: dict[str, CriterionReview]
    critical_failure: bool
    critical_reason: str | None = None

    @model_validator(mode="after")
    def complete_review(self):
        if self.reviewed_at.tzinfo is None:
            raise ValueError("reviewed_at requires a timezone")
        if set(self.criteria) != set(CRITERIA):
            raise ValueError("all four rubric criteria must be reviewed")
        if self.critical_failure and not self.critical_reason:
            raise ValueError("critical failure requires a reason")
        return self


def validate_reviews(inputs_path: Path, reviews_path: Path) -> int:
    inputs = _read_jsonl(inputs_path)
    expected = {(row["case_id"], row["run_id"]) for row in inputs}
    if len(expected) != len(inputs):
        raise ValueError("input records repeat a case and run")
    seen = set()
    covered = set()
    for raw in _read_jsonl(reviews_path):
        _reject_credentials(raw)
        review = HumanReview.model_validate(raw)
        key = (review.case_id, review.run_id)
        if key not in expected:
            raise ValueError("review does not match an exported input")
        reviewer_key = (*key, review.reviewer_id)
        if reviewer_key in seen:
            raise ValueError("reviewer submitted the same case twice")
        seen.add(reviewer_key)
        covered.add(key)
    if covered != expected:
        raise ValueError("at least one human review is required for every input")
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--manifest", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    template = commands.add_parser("prepare-reviews")
    template.add_argument("--inputs", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-reviews")
    validate.add_argument("--inputs", type=Path, required=True)
    validate.add_argument("--reviews", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        database_url = os.environ.get("AGENT_DATABASE_URL")
        if not database_url:
            parser.error("export requires AGENT_DATABASE_URL")
        count = export_inputs(
            PostgresAgentStore(database_url), args.manifest, args.output
        )
        print(f"Exported {count} unlabeled evaluation inputs")
    elif args.command == "prepare-reviews":
        count = prepare_reviews(args.inputs, args.output)
        print(f"Prepared {count} blank human-review records")
    else:
        count = validate_reviews(args.inputs, args.reviews)
        print(
            f"Validated {count} human-review records; no release threshold calculated"
        )


if __name__ == "__main__":
    main()
