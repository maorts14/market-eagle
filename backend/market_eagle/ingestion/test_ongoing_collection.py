"""Provider activity must stop at the ongoing database admission gate."""

from __future__ import annotations

from contextlib import nullcontext

import pytest
from temporalio.exceptions import ApplicationError

from . import worker


def test_ongoing_group_rejection_precedes_provider_call(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setattr(worker.psycopg, "connect", lambda _: nullcontext(object()))

    def reject(_conn, _request):
        raise ValueError("ongoing catalog changed")

    def unexpected(*_args, **_kwargs):
        pytest.fail("provider or historical validator called before ongoing admission")

    monkeypatch.setattr(worker, "validate_ongoing_collection_group", reject)
    monkeypatch.setattr(worker, "validate_collection_group", unexpected)
    monkeypatch.setattr(worker, "historical_pages", unexpected)
    request = {
        "approval_id": "reviewed",
        "source": "alpaca",
        "feed": "sip",
        "start": "2024-01-04",
        "end": "2024-01-04",
        "stock_ids": ["stock-alfa"],
    }
    with pytest.raises(ApplicationError, match="ongoing catalog changed") as error:
        worker.collect_group(request)
    assert error.value.non_retryable


def test_today_reference_check_precedes_price_provider_call(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setattr(worker.psycopg, "connect", lambda _: nullcontext(object()))
    monkeypatch.setattr(
        worker,
        "validate_ongoing_collection_group",
        lambda _conn, _request: [("stock-alfa", "ALFA", "NYSE")],
    )

    def missing(_conn, _approval_id, _target, _checked_at):
        raise ValueError("today's Alpaca reference check is missing")

    monkeypatch.setattr(worker, "require_reference_check", missing)
    monkeypatch.setattr(
        worker,
        "historical_pages",
        lambda *_args, **_kwargs: pytest.fail(
            "price provider called without reference"
        ),
    )
    request = {
        "approval_id": "reviewed",
        "source": "alpaca",
        "feed": "sip",
        "start": "2024-01-04",
        "end": "2024-01-04",
        "stock_ids": ["stock-alfa"],
    }
    with pytest.raises(ApplicationError, match="reference check"):
        worker.collect_group(request)


def test_reference_activity_checks_approval_before_provider(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")
    monkeypatch.setattr(worker.psycopg, "connect", lambda _: nullcontext(object()))

    def reject(_conn, _approval_id, _checked_at):
        raise ValueError("approval held")

    monkeypatch.setattr(worker, "validate_reference_approval", reject)
    monkeypatch.setattr(
        worker,
        "fetch_assets",
        lambda *_args: pytest.fail("asset provider called for held approval"),
    )
    with pytest.raises(ApplicationError, match="approval held"):
        worker.refresh_ongoing_reference({"approval_id": "reviewed"})
