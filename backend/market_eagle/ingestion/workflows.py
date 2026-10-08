"""Temporal controllers keep only request IDs and small counts in history."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

ACTIVITY_TIMEOUT = timedelta(minutes=10)
RETRY_POLICY = RetryPolicy(maximum_attempts=3)


@workflow.defn
class CatalogPublishWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        return await workflow.execute_activity(
            "publish_catalog_snapshot",
            request,
            task_queue="market-catalog",
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )


async def _collect_and_check(
    request: dict, groups: list[list[str]], queue: str
) -> dict:
    semaphore = asyncio.Semaphore(request.get("max_in_flight", 2))

    async def run_group(group: list[str]) -> dict:
        async with semaphore:
            scoped = {**request, "stock_ids": group}
            collected = await workflow.execute_activity(
                "collect_group",
                scoped,
                task_queue=queue,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
            coverage = await workflow.execute_activity(
                "check_coverage",
                scoped,
                task_queue=queue,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
            return {"collected": collected, "coverage": coverage}

    results = await asyncio.gather(*(run_group(group) for group in groups))
    missing = sum(item["coverage"]["missing"] for item in results)
    rejected = sum(item["collected"]["rejected"] for item in results)
    return {
        "status": "complete" if missing == 0 and rejected == 0 else "incomplete",
        "missing": missing,
        "rejected": rejected,
        "groups": results,
    }


@workflow.defn
class HistoricalBackfillWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        stock_ids = request["stock_ids"]
        groups = [stock_ids[index : index + 5] for index in range(0, len(stock_ids), 5)]
        return await _collect_and_check(request, groups, "market-backfill")


@workflow.defn
class SessionReconcileWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        stock_ids = request["stock_ids"]
        groups = [stock_ids[index : index + 5] for index in range(0, len(stock_ids), 5)]
        return await _collect_and_check(request, groups, "market-session")


@workflow.defn
class PriceRepairWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        if len(request["stock_ids"]) > 5:
            raise ValueError("repair request exceeds five stocks")
        return await _collect_and_check(
            request, [request["stock_ids"]], "market-backfill"
        )


@workflow.defn
class SessionRefreshWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        stock_ids = request["stock_ids"]
        groups = [stock_ids[index : index + 5] for index in range(0, len(stock_ids), 5)]
        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    "collect_group",
                    {**request, "stock_ids": group, "mode": "provisional"},
                    task_queue="market-session",
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_POLICY,
                )
                for group in groups
            )
        )
        returned = sum(item["returned"] for item in results)
        rejected = sum(item["rejected"] for item in results)
        observed = [item["observed_at"] for item in results if item["observed_at"]]
        return {
            "status": "observed"
            if returned == len(stock_ids) and rejected == 0
            else "incomplete",
            "returned": returned,
            "expected": len(stock_ids),
            "rejected": rejected,
            "observed_at": max(observed) if observed else None,
        }
