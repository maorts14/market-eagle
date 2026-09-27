from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from temporalio.common import RetryPolicy
    from .activities import (
        calculate_relationships, collect_symbol, complete_pipeline_run, complete_research_session,
        create_research_session, decide_agent_action, execute_agent_tool, register_universe, write_daily_brief,
    )
    from .agent import MAX_AGENT_STEPS
    from .universe import TRACKED_INSTRUMENTS


@workflow.defn
class HistoricalBackfillWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        run_id = request["run_id"]
        try:
            await workflow.execute_activity(register_universe, start_to_close_timeout=timedelta(minutes=1))
            results = []
            for symbol, _, _ in TRACKED_INSTRUMENTS:
                results.append(await workflow.execute_activity(
                    collect_symbol, {"symbol": symbol, "start": request["start"], "end": request["end"], "run_id": run_id, "workflow_type": "historical_backfill"},
                    start_to_close_timeout=timedelta(minutes=2), retry_policy=RetryPolicy(maximum_attempts=3),
                ))
            analysis = await workflow.execute_activity(calculate_relationships, {"run_id": f"analysis-{run_id}", "window_days": 60}, start_to_close_timeout=timedelta(minutes=2))
            brief = await workflow.execute_activity(write_daily_brief, analysis, start_to_close_timeout=timedelta(minutes=1))
            await workflow.execute_activity(complete_pipeline_run, {"run_id": run_id, "status": "completed", "detail": {"symbols": results, "analysis": analysis}}, start_to_close_timeout=timedelta(minutes=1))
            return {"collection": results, "analysis": analysis, "brief": brief}
        except Exception as error:
            await workflow.execute_activity(complete_pipeline_run, {"run_id": run_id, "status": "failed", "detail": {"error": str(error)}}, start_to_close_timeout=timedelta(minutes=1))
            raise


@workflow.defn
class DailyCollectionWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        # Scheduled executions omit an id so each day receives an independent audit record.
        run_id = request.get("run_id") or f"daily-{workflow.uuid4()}"
        end = request.get("end") or workflow.now().date().isoformat()
        start = request.get("start") or (workflow.now().date() - timedelta(days=7)).isoformat()
        try:
            await workflow.execute_activity(register_universe, start_to_close_timeout=timedelta(minutes=1))
            results = []
            for symbol, _, _ in TRACKED_INSTRUMENTS:
                results.append(await workflow.execute_activity(
                    collect_symbol, {"symbol": symbol, "start": start, "end": end, "run_id": run_id, "workflow_type": "daily_collection"},
                    start_to_close_timeout=timedelta(minutes=2), retry_policy=RetryPolicy(maximum_attempts=3),
                ))
            analysis = await workflow.execute_activity(calculate_relationships, {"run_id": f"analysis-{run_id}", "window_days": 60}, start_to_close_timeout=timedelta(minutes=2))
            brief = await workflow.execute_activity(write_daily_brief, analysis, start_to_close_timeout=timedelta(minutes=1))
            await workflow.execute_activity(complete_pipeline_run, {"run_id": run_id, "status": "completed", "detail": {"symbols": results, "analysis": analysis}}, start_to_close_timeout=timedelta(minutes=1))
            return {"collection": results, "analysis": analysis, "brief": brief}
        except Exception as error:
            await workflow.execute_activity(complete_pipeline_run, {"run_id": run_id, "status": "failed", "detail": {"error": str(error)}}, start_to_close_timeout=timedelta(minutes=1))
            raise


@workflow.defn
class ResearchAgentWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        """Durable agent state machine: each model decision and tool result is an activity boundary."""
        session_id, question = request["session_id"], request["question"]
        await workflow.execute_activity(create_research_session, {"session_id": session_id, "question": question}, start_to_close_timeout=timedelta(minutes=1))
        observations: list[dict] = []
        used_tools: list[str] = []
        for step_index in range(MAX_AGENT_STEPS):
            action = await workflow.execute_activity(
                decide_agent_action,
                {"session_id": session_id, "question": question, "observations": observations, "used_tools": used_tools, "step_index": step_index},
                start_to_close_timeout=timedelta(seconds=45), retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if action["action"] == "final":
                answer = await workflow.execute_activity(complete_research_session, {"session_id": session_id, "plan": used_tools, "observations": observations, "answer": action["answer"], "step_index": step_index}, start_to_close_timeout=timedelta(minutes=1))
                return {"session_id": session_id, "answer": answer, "observations": observations}
            tool = action["tool"]
            observation = await workflow.execute_activity(execute_agent_tool, {"session_id": session_id, "tool": tool, "step_index": step_index}, start_to_close_timeout=timedelta(minutes=1), retry_policy=RetryPolicy(maximum_attempts=3))
            observations.append(observation)
            used_tools.append(tool)
        answer = await workflow.execute_activity(complete_research_session, {"session_id": session_id, "plan": used_tools, "observations": observations, "answer": "The research step limit was reached before a final synthesis. No market conclusion was produced.", "step_index": MAX_AGENT_STEPS}, start_to_close_timeout=timedelta(minutes=1))
        return {"session_id": session_id, "answer": answer, "observations": observations}
