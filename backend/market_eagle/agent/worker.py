"""Run with a configured read-only AnalyticsRepository and activity-local model key."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from market_eagle.analytics.models import AnalyticsRepository
from market_eagle.analytics.service import AnalyticsService

from .activities import AgentActivities, ResearchModel
from .models import Limits
from .store import AgentStore
from .workflow import AgentTurnWorkflow


async def run_worker(
    temporal: Client,
    store: AgentStore,
    repository: AnalyticsRepository,
    model: ResearchModel,
    limits: Limits,
    task_queue: str = "market-eagle-agent",
) -> None:
    activities = AgentActivities(store, AnalyticsService(repository), model, limits)
    with ThreadPoolExecutor(max_workers=4) as executor:
        worker = Worker(
            temporal,
            task_queue=task_queue,
            workflows=[AgentTurnWorkflow],
            activities=[
                activities.load_context,
                activities.interpret,
                activities.execute,
                activities.explain,
                activities.finish,
                activities.refresh_summary,
            ],
            activity_executor=executor,
        )
        await worker.run()
