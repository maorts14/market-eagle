from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from market_eagle.analytics.models import AnalyticalRequest


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["query", "clarification", "unsupported"]
    request: AnalyticalRequest | None = None
    message: str | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=8)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An inclusive five-calendar-year window can contain two leap days.
    max_window_days: int = Field(default=5 * 365 + 2, ge=1)
    max_rows: int = Field(default=25, ge=1, le=100)
    max_tool_calls: int = Field(default=2, ge=1, le=5)
    max_repair_attempts: int = Field(default=1, ge=0, le=2)
    query_timeout_seconds: int = Field(default=30, ge=1)


def previous_completed_month(reference_date: date) -> tuple[date, date]:
    first_this_month = reference_date.replace(day=1)
    last_previous_month = first_this_month - timedelta(days=1)
    return last_previous_month.replace(day=1), last_previous_month


def validate_request(request: AnalyticalRequest, limits: Limits) -> None:
    if (request.window.end - request.window.start).days + 1 > limits.max_window_days:
        raise ValueError("requested window exceeds the configured limit")
    if request.limit > limits.max_rows:
        raise ValueError("requested row count exceeds the configured limit")


TERMINAL = frozenset(
    {"completed", "needs_clarification", "unsupported", "failed", "cancelled"}
)
