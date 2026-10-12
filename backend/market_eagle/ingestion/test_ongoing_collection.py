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
