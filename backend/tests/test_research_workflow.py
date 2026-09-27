import asyncio

from app import workflows


def test_research_workflow_persists_each_durable_agent_boundary(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    async def execute_activity(activity, payload, **_kwargs):
        calls.append((activity.__name__, payload))
        if activity.__name__ == "decide_agent_action":
            if payload["step_index"] == 0:
                return {"action": "tool", "tool": "recent_performance", "answer": None}
            return {"action": "final", "tool": None, "answer": "Historical association is not causation."}
        if activity.__name__ == "execute_agent_tool":
            return {"tool": "recent_performance", "result": [{"symbol": "XLK", "return_5d": 2.1}]}
        if activity.__name__ == "complete_research_session":
            return payload["answer"]
        return None

    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    result = asyncio.run(workflows.ResearchAgentWorkflow().run({"session_id": "research-test", "question": "What moved?"}))

    assert [name for name, _ in calls] == [
        "create_research_session", "decide_agent_action", "execute_agent_tool", "decide_agent_action", "complete_research_session",
    ]
    assert calls[3][1]["observations"] == [{"tool": "recent_performance", "result": [{"symbol": "XLK", "return_5d": 2.1}]}]
    assert result["answer"] == "Historical association is not causation."
