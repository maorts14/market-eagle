"""Start the research-agent Temporal worker with read-only market access."""

from __future__ import annotations

import asyncio
import os

from temporalio.client import Client

from market_eagle.analytics.postgres_repository import PostgresAnalyticsRepository

from .models import Limits
from .openrouter import OpenRouterResearchModel
from .postgres_store import PostgresAgentStore
from .worker import run_worker


async def main() -> None:
    required = (
        "DATABASE_URL",
        "AGENT_DATABASE_URL",
        "MARKET_EAGLE_SOURCE",
        "MARKET_EAGLE_FEED",
        "MARKET_EAGLE_PRICE_BASIS",
        "MARKET_EAGLE_EXCHANGE",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Agent worker requires " + ", ".join(missing))
    repository = PostgresAnalyticsRepository(
        os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1),
        source=os.environ["MARKET_EAGLE_SOURCE"],
        feed=os.environ["MARKET_EAGLE_FEED"],
        price_basis=os.environ["MARKET_EAGLE_PRICE_BASIS"],
        exchange=os.environ["MARKET_EAGLE_EXCHANGE"],
        private_sample_snapshot_id=os.environ.get(
            "MARKET_EAGLE_PRIVATE_SAMPLE_SNAPSHOT_ID"
        ),
        production=os.environ.get("MARKET_EAGLE_RUNTIME") == "production",
    )
    temporal = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    await run_worker(
        temporal,
        PostgresAgentStore(os.environ["AGENT_DATABASE_URL"]),
        repository,
        OpenRouterResearchModel(
            api_key=os.environ["OPENROUTER_API_KEY"],
            model=os.environ["OPENROUTER_MODEL"],
        ),
        Limits(),
    )


if __name__ == "__main__":
    asyncio.run(main())
