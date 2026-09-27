import asyncio
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec
from temporalio.client import ScheduleAlreadyRunningError
from .config import settings
from .workflows import DailyCollectionWorkflow


async def main() -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    try:
        await client.create_schedule(
            "market-eagle-weekday-close",
            Schedule(
                action=ScheduleActionStartWorkflow(DailyCollectionWorkflow.run, id="market-eagle-weekday-close", task_queue=settings.task_queue,
                    args=[{}]),
                spec=ScheduleSpec(cron_expressions=["15 17 * * 1-5"], time_zone_name="America/New_York"),
            ),
        )
        print("Created weekday Temporal schedule.")
    except ScheduleAlreadyRunningError:
        print("Weekday Temporal schedule already exists.")


if __name__ == "__main__":
    asyncio.run(main())
