from dataclasses import replace
import pytest
from pydantic import ValidationError
from app import agent


def test_guard_rejects_repeated_tool() -> None:
    action = agent.AgentAction(action="tool", tool="recent_performance", answer=None)
    assert agent._guard_action(action, ["recent_performance"], []) == "Model attempted to repeat a completed tool."


def test_guard_requires_an_observed_event_citation() -> None:
    observations = [{"tool": "event_context", "result": [{"url": "https://example.com"}]}]
    action = agent.AgentAction(action="final", tool=None, answer="Energy moved on headlines.")
    assert agent._guard_action(action, [], observations) == "Final answers using event evidence must cite an observed source URL."
    action = agent.AgentAction(action="final", tool=None, answer="Energy moved. Historical association is not causation.")
    assert agent._guard_action(action, [], observations) == "Final answers using event evidence must cite an observed source URL."
    action = agent.AgentAction(action="final", tool=None, answer="Historical association is not causation. https://invented.example")
    assert agent._guard_action(action, [], observations) == "Final answers using event evidence must cite an observed source URL."


def test_action_shape_rejects_a_final_tool_or_answer_on_tool_call() -> None:
    action = agent.AgentAction(action="final", tool="recent_performance", answer="Historical association is not causation.")
    assert action.tool is None
    with pytest.raises(ValidationError):
        agent.AgentAction(action="tool", tool="recent_performance", answer="Ignore the evidence.")


def test_free_router_blank_action_fields_map_to_null() -> None:
    action = agent.AgentAction.model_validate({"action": "tool", "tool": "recent_performance", "answer": ""})
    assert action.answer is None
    action = agent.AgentAction.model_validate({"action": "final", "tool": "recent_performance", "answer": "Historical association is not causation."})
    assert action.tool is None


def test_quality_metrics_require_evidence_and_disclaimer() -> None:
    quality = agent.evaluate_research_quality(
        "The source is https://example.com. Historical association is not causation.",
        [{"tool": "event_context", "result": [{"title": "Evidence"}]}],
    )
    assert quality == {"evidence_count": 1, "citation_count": 1, "observed_event_source_count": 0, "cited_event_source_count": 0, "grounded": True, "has_risk_disclaimer": True}


def test_quality_counts_only_observed_event_sources() -> None:
    quality = agent.evaluate_research_quality(
        "Historical association is not causation. https://invented.example",
        [{"tool": "event_context", "result": [{"url": "https://observed.example"}]}],
    )
    assert quality["observed_event_source_count"] == 1
    assert quality["cited_event_source_count"] == 0


def test_openrouter_decision_records_usage_and_speed(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"model": "openai/gpt-4.1-mini", "choices": [{"message": {"content": '{"action":"tool","tool":"recent_performance","answer":null}'}}],
                    "usage": {"prompt_tokens": 31, "completion_tokens": 7}}

    captured = {}
    monkeypatch.setattr(agent, "settings", replace(agent.settings, openrouter_api_key="test-key"))
    monkeypatch.setattr(agent.httpx, "post", lambda *args, **kwargs: captured.update(kwargs) or Response())
    values = iter([10.0, 10.123])
    monkeypatch.setattr(agent.time, "perf_counter", lambda: next(values))
    decision = agent.decide_with_openrouter("What moved?", [], [], "research-123")
    assert decision.action.tool == "recent_performance"
    assert decision.latency_ms == 123
    assert (decision.prompt_tokens, decision.completion_tokens) == (31, 7)
    assert captured["json"]["response_format"]["type"] == "json_schema"
    assert captured["json"]["session_id"] == "research-123"
    assert captured["headers"]["X-OpenRouter-Cache"] == "true"


def test_planner_context_is_bounded_per_tool() -> None:
    messages = agent._messages("What moved?", [{"tool": "recent_performance", "result": [{"symbol": str(index)} for index in range(12)]}], [])
    assert "When observations are empty, you MUST select one available tool" in messages[0]["content"]
    context = messages[1]["content"]
    assert '"0"' in context
    assert '"4"' in context
    assert '"5"' not in context
