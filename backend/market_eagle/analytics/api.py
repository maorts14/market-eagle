"""Explorer HTTP route; the application injects its selected read-only repository."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import AnalyticsRepository
from .service import AnalyticsError, AnalyticsService


def create_explorer_router(repository: AnalyticsRepository) -> APIRouter:
    router = APIRouter()
    service = AnalyticsService(repository)

    @router.get("/api/v1/explorer")
    def explorer(start: date, end: date):
        return service.explorer(start, end)

    return router


def install_analytics_errors(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_error(_request: Request, error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "unsupported_requested_value",
                    "message": "Invalid explorer request",
                    "details": {
                        "fields": [
                            ".".join(map(str, issue["loc"])) for issue in error.errors()
                        ]
                    },
                }
            },
        )

    @app.exception_handler(AnalyticsError)
    async def analytics_error(_request: Request, error: AnalyticsError):
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            },
        )
