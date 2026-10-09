"""Compose the explorer and optional research-agent API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client

from .agent.api import create_agent_router
from .agent.models import Limits
from .agent.postgres_store import PostgresAgentStore
from .agent.store import AgentStore
from .analytics.api import create_explorer_router, install_analytics_errors
from .analytics.fixture_repository import SyntheticFixtureRepository
from .analytics.models import AnalyticsRepository

ROOT = Path(__file__).resolve().parents[2]


def selected_repository() -> AnalyticsRepository:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return SyntheticFixtureRepository(ROOT / "fixtures" / "synthetic-v1")

    from .analytics.postgres_repository import PostgresAnalyticsRepository

    required = (
        "MARKET_EAGLE_SOURCE",
        "MARKET_EAGLE_FEED",
        "MARKET_EAGLE_PRICE_BASIS",
        "MARKET_EAGLE_EXCHANGE",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Database mode requires " + ", ".join(missing))
    return PostgresAnalyticsRepository(
        database_url.replace("postgresql+psycopg://", "postgresql://", 1),
        source=os.environ["MARKET_EAGLE_SOURCE"],
        feed=os.environ["MARKET_EAGLE_FEED"],
        price_basis=os.environ["MARKET_EAGLE_PRICE_BASIS"],
        exchange=os.environ["MARKET_EAGLE_EXCHANGE"],
    )


def create_app(
    repository: AnalyticsRepository | None = None,
    *,
    agent_store: AgentStore | PostgresAgentStore | None = None,
    temporal: Client | None = None,
    agent_enabled: bool | None = None,
) -> FastAPI:
    enabled = (
        agent_enabled
        if agent_enabled is not None
        else bool(
            agent_store
            or temporal
            or os.environ.get("MARKET_EAGLE_AGENT_ENABLED") == "1"
        )
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if enabled and temporal is None:
            application.state.temporal = await Client.connect(
                os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
                namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
            )
        yield

    app = FastAPI(title="Market Eagle", version="0.1.0", lifespan=lifespan)
    if temporal is not None:
        app.state.temporal = temporal
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    install_analytics_errors(app)
    app.include_router(create_explorer_router(repository or selected_repository()))
    if enabled:
        store = agent_store
        if store is None:
            agent_database_url = os.environ.get("AGENT_DATABASE_URL")
            if not agent_database_url:
                raise RuntimeError("Agent API requires AGENT_DATABASE_URL")
            store = PostgresAgentStore(agent_database_url)
        app.include_router(
            create_agent_router(store, lambda: app.state.temporal, Limits())
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
