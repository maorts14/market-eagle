import asyncio
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker
from .activities import calculate_relationships, collect_symbol, complete_pipeline_run, complete_research_session, create_research_session, decide_agent_action, execute_agent_tool, register_universe, write_daily_brief
from .config import settings
from .database import init_database
from .workflows import DailyCollectionWorkflow, HistoricalBackfillWorkflow, ResearchAgentWorkflow


async def main() -> None:
    init_database()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(client, task_queue=settings.task_queue, activity_executor=ThreadPoolExecutor(max_workers=8),
                    workflows=[HistoricalBackfillWorkflow, DailyCollectionWorkflow, ResearchAgentWorkflow],
                    activities=[register_universe, collect_symbol, calculate_relationships, write_daily_brief, complete_pipeline_run,
                                create_research_session, decide_agent_action, execute_agent_tool, complete_research_session])
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
