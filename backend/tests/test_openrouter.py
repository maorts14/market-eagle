from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_eagle.agent.__main__ import main as worker_main
from market_eagle.agent.openrouter import (
    FREE_MODEL,
    OPENROUTER_BASE_URL,
    OpenRouterResearchModel,
)


def mock_model_response(content: str, *, finish_reason: str = "stop") -> dict:
    return {
        "id": "chat-test",
        "object": "chat.completion",
        "created": 1,
        "model": FREE_MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


def mocked_adapter(contents: list[str], *, finish_reason: str = "stop"):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json=mock_model_response(contents.pop(0), finish_reason=finish_reason)
        )

    client = OpenAI(
        api_key="test-key",
        base_url=OPENROUTER_BASE_URL,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        max_retries=0,
    )
    return OpenRouterResearchModel(
        api_key="test-key", model=FREE_MODEL, client=client
    ), requests


def test_chat_completion_uses_fixed_free_model_and_structured_decision():
    decision = {
        "kind": "clarification",
        "request": None,
        "message": "Which stock do you mean?",
        "assumptions": [],
    }
    adapter, requests = mocked_adapter(
        [json.dumps(decision), "A scoped explanation.", "Older context."]
    )
    context = {
        "question": "What about that stock?",
        "reference_date": "2026-01-08",
        "summary": None,
        "recent_turns": [],
    }
    actual = adapter.interpret(context, feedback="No referent in this conversation")
    assert actual.kind == "clarification"
    assert actual.message == "Which stock do you mean?"
    assert (
        adapter.explain("question", {"eligible_count": 4}, [])
        == "A scoped explanation."
    )
    assert adapter.summarize([{"question": "old"}]) == "Older context."

    assert all(request.url.path == "/api/v1/chat/completions" for request in requests)
    assert all(
        request.headers["authorization"] == "Bearer test-key" for request in requests
    )
    sent = [json.loads(request.content) for request in requests]
    assert all(item["model"] == FREE_MODEL for item in sent)
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert sent[0]["temperature"] == 0
    assert sent[0]["response_format"]["json_schema"]["strict"] is True
    schema = sent[0]["response_format"]["json_schema"]["schema"]
    system_instructions = sent[0]["messages"][0]["content"]
    assert "never ask the user to provide the schema" in system_instructions
    assert (
        json.loads(system_instructions.split("\nDecision JSON schema:\n", 1)[1])
        == schema
    )
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    request_schema = schema["$defs"]["AnalyticalRequest"]
    assert set(request_schema["required"]) == set(request_schema["properties"])
    assert "default" not in schema["$defs"]["SortSpec"]["properties"]["direction"]

    def patterns(node):
        if isinstance(node, dict):
            if "pattern" in node:
                yield node["pattern"]
            for value in node.values():
                yield from patterns(value)
        elif isinstance(node, list):
            for value in node:
                yield from patterns(value)

    assert all(
        marker not in pattern
        for pattern in patterns(schema)
        for marker in ("(?!", "(?=", "(?<=", "(?<!")
    )
    assert sent[0]["provider"] == {"require_parameters": True}
    assert "validation_feedback" in sent[0]["messages"][1]["content"]
    assert "response_format" not in sent[1]
    assert "response_format" not in sent[2]


def test_provider_json_still_passes_trusted_decision_validation():
    valid = {
        "kind": "query",
        "message": None,
        "assumptions": [],
        "request": {
            "request_version": 1,
            "universe": "latest_published_catalog",
            "window": {"start": "2025-12-01", "end": "2025-12-31"},
            "grain": "stock",
            "measures": ["period_return"],
            "sort": {"measure": "period_return", "direction": "desc"},
            "limit": 1,
        },
    }
    context = {
        "question": "Which stock gained most?",
        "reference_date": "2026-01-08",
        "summary": None,
        "recent_turns": [],
    }
    adapter, _ = mocked_adapter([json.dumps(valid)])
    assert adapter.interpret(context).request.sort.measure == "period_return"

    injected = valid | {"request": valid["request"] | {"sql": "DROP TABLE prices"}}
    adapter, _ = mocked_adapter([json.dumps(injected)])
    with pytest.raises(ValidationError):
        adapter.interpret(context)


def test_incomplete_or_invalid_provider_output_fails_closed():
    context = {
        "question": "question",
        "reference_date": "2026-01-08",
        "summary": None,
        "recent_turns": [],
    }
    adapter, _ = mocked_adapter(["not json"])
    with pytest.raises(ValidationError):
        adapter.interpret(context)
    adapter, _ = mocked_adapter(
        [json.dumps({"kind": "unsupported", "message": "reason"})],
        finish_reason="length",
    )
    with pytest.raises(ValueError, match="complete text response"):
        adapter.interpret(context)


@pytest.mark.parametrize("choices", [None, []])
def test_provider_response_without_choices_fails_closed(choices):
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=mock_model_response("unused") | {"choices": choices}
        )

    client = OpenAI(
        api_key="test-key",
        base_url=OPENROUTER_BASE_URL,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        max_retries=0,
    )
    adapter = OpenRouterResearchModel(
        api_key="test-key", model=FREE_MODEL, client=client
    )
    with pytest.raises(ValueError, match="no completion choices"):
        adapter.explain("question", {}, [])


def test_worker_requires_openrouter_key_and_explicit_free_slug(monkeypatch):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterResearchModel(api_key="", model=FREE_MODEL)
    with pytest.raises(ValueError, match="OPENROUTER_MODEL"):
        OpenRouterResearchModel(api_key="test-key", model="openrouter/free")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY, OPENROUTER_MODEL"):
        asyncio.run(worker_main())
