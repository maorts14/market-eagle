"""Compose the direct explorer API around one selected analytical repository."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


def create_app(repository: AnalyticsRepository | None = None) -> FastAPI:
    app = FastAPI(title="Market Eagle", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    install_analytics_errors(app)
    app.include_router(create_explorer_router(repository or selected_repository()))

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
