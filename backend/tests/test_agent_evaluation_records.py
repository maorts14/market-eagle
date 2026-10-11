"""Human-review exports contain only selected, bounded conversation evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from market_eagle.agent.evaluation_records import (
    build_input_record,
    export_inputs,
    load_cases,
    prepare_reviews,
    validate_reviews,
)
from market_eagle.agent.store import AgentStore
from pydantic import ValidationError


@pytest.fixture
def answered_turn(tmp_path):
    store = AgentStore(tmp_path / "agent.sqlite")
    _, cases = load_cases()
    case = cases["gain-dollar-frequency-previous-month"]
    conversation_id = store.create_conversation()
    prior = store.submit(conversation_id, "prior", "Earlier question", "2026-01-08")
    store.finish(prior["id"], "needs_clarification", explanation="Earlier answer")
    target = store.submit(conversation_id, "target", case["question"], "2026-01-08")
    unrelated = store.create_conversation()
    other = store.submit(unrelated, "other", "UNRELATED_PRIVATE_MARKER", "2026-01-08")
    store.finish(other["id"], "unsupported")
    result = {
        "request_version": 1,
        "metric_version": "synthetic-metric-v1",
        "requested_window": {"start": "2025-12-01", "end": "2025-12-31"},
        "resolved_window": {"start": "2025-12-01", "end": "2025-12-31"},
        "catalog": {"tracked_count": 5},
        "data": {"source": "synthetic-v1"},
        "market": {},
        "eligible_count": 4,
        "matched_count": 1,
        "exclusions": [],
        "rows": [{"ticker": "EPSI", "period_return": "0.12"}],
        "calculated_at": "2026-01-08T12:00:00+00:00",
    }
    evidence_id = store.save_evidence(target["id"], result)
    store.trace(
        target["id"],
        "tool_verified",
        {"evidence_id": evidence_id, "OPENROUTER_API_KEY": "sk-or-v1-private"},
    )
    store.finish(
        target["id"],
        "completed",
        decision={"kind": "query", "request": {"request_version": 1}},
        evidence_id=evidence_id,
        explanation="The eligible leader is EPSI.",
    )
    return store, case, target


def test_export_keeps_trusted_result_separate_and_scopes_context(
    answered_turn, tmp_path
):
    store, case, target = answered_turn
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "run_id": "operator-run-1",
                "model_id": "nvidia/nemotron-3-super-120b-a12b:free",
                "records": [{"case_id": case["id"], "turn_id": target["id"]}],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "inputs.jsonl"
    assert export_inputs(store, manifest, output) == 1
    raw = output.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert record["trusted_result"]["rows"][0]["ticker"] == "EPSI"
    assert record["agent_explanation"] == "The eligible leader is EPSI."
    assert record["metric_version"] == "synthetic-metric-v1"
    assert record["conversation_context"][0]["question"] == "Earlier question"
    assert record["trace_stages"][0]["stage"] == "tool_verified"
    assert record["expected_facts"]["expected_winner"] == "EPSI"
    assert "UNRELATED_PRIVATE_MARKER" not in raw
    assert "OPENROUTER_API_KEY" not in raw
    assert "sk-or-v1-private" not in raw
    with pytest.raises(FileExistsError):
        export_inputs(store, manifest, output)
    duplicate = json.loads(manifest.read_text(encoding="utf-8"))
    duplicate["records"].append(duplicate["records"][0])
    manifest.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="appears twice"):
        export_inputs(store, manifest, tmp_path / "duplicate.jsonl")


def test_export_rejects_wrong_or_unfinished_turn_and_possible_credentials(
    answered_turn, tmp_path
):
    store, case, target = answered_turn
    with pytest.raises(ValueError, match="does not match"):
        build_input_record(
            store,
            case | {"question": "Different question"},
            dataset_version="v1",
            run_id="r1",
            model_id="m1",
            turn_id=target["id"],
        )
    pending = store.submit(
        store.create_conversation(), "pending", case["question"], "2026-01-08"
    )
    with pytest.raises(ValueError, match="not terminal"):
        build_input_record(
            store,
            case,
            dataset_version="v1",
            run_id="r1",
            model_id="m1",
            turn_id=pending["id"],
        )
    secret_case = {"id": "secret", "question": "OPENROUTER_API_KEY=sk-or-v1-private"}
    secret = store.submit(
        store.create_conversation(), "secret", secret_case["question"], "2026-01-08"
    )
    store.finish(secret["id"], "unsupported")
    with pytest.raises(ValueError, match="possible credential"):
        build_input_record(
            store,
            secret_case,
            dataset_version="v1",
            run_id="r1",
            model_id="m1",
            turn_id=secret["id"],
        )


def test_blank_reviews_require_real_human_entries(answered_turn, tmp_path):
    store, case, target = answered_turn
    input_path = tmp_path / "inputs.jsonl"
    input_record = build_input_record(
        store,
        case,
        dataset_version="synthetic-agent-v1",
        run_id="run-1",
        model_id="fixed-free-model",
        turn_id=target["id"],
    )
    input_path.write_text(json.dumps(input_record) + "\n", encoding="utf-8")
    template_path = tmp_path / "blank-reviews.jsonl"
    assert prepare_reviews(input_path, template_path) == 1
    blank = json.loads(template_path.read_text(encoding="utf-8"))
    assert blank["reviewer_id"] is None
    assert blank["criteria"]["grounding"]["verdict"] is None
    with pytest.raises(ValidationError):
        validate_reviews(input_path, template_path)

    reviewed = blank | {
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-10-09T10:00:00+03:00",
        "criteria": {
            name: {
                "verdict": "pass",
                "reason": "Checked against evidence",
                "evidence": "EPSI",
            }
            for name in blank["criteria"]
        },
        "critical_failure": False,
    }
    reviews_path = tmp_path / "reviews.jsonl"
    reviews_path.write_text(json.dumps(reviewed) + "\n", encoding="utf-8")
    assert validate_reviews(input_path, reviews_path) == 1
    reviews_path.write_text((json.dumps(reviewed) + "\n") * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="same case twice"):
        validate_reviews(input_path, reviews_path)
    reviewed["criteria"]["grounding"]["evidence"] = "Bearer private-value"
    reviews_path.write_text(json.dumps(reviewed) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="possible credential"):
        validate_reviews(input_path, reviews_path)
    reviewed["criteria"]["grounding"]["evidence"] = None
    reviews_path.write_text(json.dumps(reviewed) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        validate_reviews(input_path, reviews_path)


def test_local_operator_command_prepares_blank_records(answered_turn, tmp_path):
    store, case, target = answered_turn
    inputs = tmp_path / "inputs.jsonl"
    inputs.write_text(
        json.dumps(
            build_input_record(
                store,
                case,
                dataset_version="synthetic-agent-v1",
                run_id="run-command",
                model_id="fixed-test-model",
                turn_id=target["id"],
            )
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "blank.jsonl"
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [
            sys.executable,
            str(root / "dev.py"),
            "agent-evaluation",
            "prepare-reviews",
            "--inputs",
            str(inputs),
            "--output",
            str(output),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    blank = json.loads(output.read_text(encoding="utf-8"))
    assert blank["case_id"] == case["id"]
    assert blank["criteria"]["grounding"]["verdict"] is None
