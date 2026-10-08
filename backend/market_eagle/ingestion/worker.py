"""Temporal ingestion worker for verified historical data sources."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
import psycopg
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from .alpaca import AlpacaRequestError, historical_pages, page_rows
from .store import ingest_page, missing_pairs, publish_catalog, read_csv
from .workflows import CatalogPublishWorkflow, HistoricalBackfillWorkflow, PriceRepairWorkflow, SessionReconcileWorkflow, SessionRefreshWorkflow


_provider_lock = threading.Lock()
_next_provider_call = 0.0


def _pace_provider() -> None:
    """Share a conservative request interval between both queues in one worker process."""
    global _next_provider_call
    interval = float(os.environ.get("ALPACA_MIN_REQUEST_INTERVAL_SECONDS", "1"))
    if interval < 0.5:
        raise ValueError("provider request interval must be at least 0.5 seconds")
    with _provider_lock:
        now = time.monotonic()
        if now < _next_provider_call:
            time.sleep(_next_provider_call - now)
        _next_provider_call = time.monotonic() + interval


def _request_dates(request: dict) -> tuple[date, date]:
    start = date.fromisoformat(request["start"])
    end = date.fromisoformat(request["end"])
    if start > end:
        raise ValueError("invalid collection window")
    return start, end


def _retry_delay(value: str | None) -> timedelta | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return None
    return timedelta(seconds=max(1, min(seconds, 300)))


@activity.defn(name="publish_catalog_snapshot")
def publish_catalog_snapshot(request: dict) -> dict:
    if request["source"] != "synthetic-v1":
        raise ApplicationError("live catalog publication needs a validated provider and review policy", non_retryable=True)
    fixture_dir = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic-v1"
    rows = read_csv(fixture_dir / "catalog.csv")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        snapshot_id = publish_catalog(
            conn, rows, source="synthetic-v1", taxonomy="synthetic-v1", exchange="SYNTHETIC",
        )
    return {"status": "published", "snapshot_id": snapshot_id, "members": len(rows)}


@activity.defn(name="collect_group")
def collect_group(request: dict) -> dict:
    """Fetch five historical stocks, committing each provider page separately."""
    if request["source"] != "alpaca" or request["feed"] not in ("sip", "iex"):
        raise ApplicationError("historical worker supports an explicitly configured Alpaca source only", non_retryable=True)
    key_id = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key_id or not secret:
        raise ApplicationError("Alpaca credentials are required for live collection", non_retryable=True)
    start, end = _request_dates(request)
    stock_ids = request["stock_ids"]
    if not 1 <= len(stock_ids) <= 5:
        raise ApplicationError("collection group must contain one to five stocks", non_retryable=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT m.stock_id, s.ticker FROM universe_member m JOIN security_symbol s "
                "ON s.stock_id = m.stock_id AND s.source = 'alpaca' AND s.exchange = %s "
                "AND s.valid_from <= %s AND (s.valid_to IS NULL OR s.valid_to >= %s) "
                "WHERE m.snapshot_id = %s AND m.stock_id = ANY(%s)",
                (request["exchange"], start, end, request["snapshot_id"], stock_ids),
            )
            mappings = cur.fetchall()
        conn.commit()  # End the alias read so each following page has its own transaction.
        if len(mappings) != len(stock_ids) or len({item[1] for item in mappings}) != len(stock_ids):
            raise ApplicationError("stock IDs need verified Alpaca aliases covering the entire request window", non_retryable=True)
        symbols = [item[1] for item in mappings]
        accepted = inserted = rejected = pages = 0
        returned = set()
        last_observed_at = None
        rejections = []
        provisional = request.get("mode") == "provisional"
        if provisional and start != end:
            raise ApplicationError("a provisional refresh covers one session", non_retryable=True)
        end_at = datetime.now(timezone.utc) - timedelta(minutes=15) if provisional else None
        try:
            with httpx.Client() as client:
                for payload, observed_at in historical_pages(
                    client, key_id=key_id, secret_key=secret, symbols=symbols, start=start, end=end,
                    feed=request["feed"], adjustment=request["price_basis"], end_at=end_at,
                    before_request=_pace_provider,
                ):
                    last_observed_at = observed_at
                    rows = [row for row in page_rows(
                        payload, observed_at, "alpaca", request["feed"], request["price_basis"],
                        status="provisional" if provisional else "historical",
                    )
                            if start <= date.fromisoformat(row["session_date"]) <= end]
                    result = ingest_page(
                        conn, rows, collection_run_id=request["collection_run_id"],
                        endpoint="/v2/stocks/bars", requested_symbols=symbols,
                        requested_start=start, requested_end=end, source="alpaca", feed=request["feed"],
                        price_basis=request["price_basis"], exchange=request["exchange"],
                    )
                    accepted += result["accepted"]
                    inserted += result["inserted"]
                    rejected += len(result["rejected"])
                    returned.update(row["ticker"] for row in rows)
                    rejections.extend(result["rejected"][:max(0, 20 - len(rejections))])
                    pages += 1
        except AlpacaRequestError as exc:
            raise ApplicationError(
                str(exc), non_retryable=exc.status_code in (400, 401, 403),
                next_retry_delay=_retry_delay(exc.retry_after) if exc.status_code == 429 else None,
            ) from exc
        return {"pages": pages, "accepted": accepted, "inserted": inserted, "returned": len(returned),
                "rejected": rejected, "rejection_sample": rejections,
                "observed_at": last_observed_at.isoformat() if last_observed_at else None}


@activity.defn(name="check_coverage")
def check_coverage(request: dict) -> dict:
    start, end = _request_dates(request)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return missing_pairs(
            conn, request["snapshot_id"], request["stock_ids"], start, end,
            request["source"], request["feed"], request["price_basis"], request["exchange"],
            limit=50,
        )


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    client = await Client.connect(address, namespace=namespace)
    executor = ThreadPoolExecutor(max_workers=4)
    backfill = Worker(
        client, task_queue="market-backfill",
        workflows=[HistoricalBackfillWorkflow, PriceRepairWorkflow],
        activities=[collect_group, check_coverage], activity_executor=executor,
        max_concurrent_activities=2,
    )
    session = Worker(
        client, task_queue="market-session",
        workflows=[SessionReconcileWorkflow, SessionRefreshWorkflow],
        activities=[collect_group, check_coverage], activity_executor=executor,
        max_concurrent_activities=1,
    )
    catalog = Worker(
        client, task_queue="market-catalog", workflows=[CatalogPublishWorkflow],
        activities=[publish_catalog_snapshot], activity_executor=executor,
        max_concurrent_activities=1,
    )
    await asyncio.gather(backfill.run(), session.run(), catalog.run())


if __name__ == "__main__":
    asyncio.run(main())
