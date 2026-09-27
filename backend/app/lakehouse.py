"""Iceberg lakehouse boundary: data-plane writes use Iceberg; query-plane reads use Trino."""
from datetime import datetime, timezone
import json
from functools import lru_cache
import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchTableError
from pyiceberg.schema import Schema
from pyiceberg.types import DateType, DoubleType, LongType, NestedField, StringType, TimestampType
import trino
from .config import settings


RAW_SCHEMA = Schema(
    NestedField(1, "raw_id", StringType(), required=True), NestedField(2, "pipeline_run_id", StringType(), required=True),
    NestedField(3, "symbol", StringType(), required=True), NestedField(4, "provider", StringType(), required=True),
    NestedField(5, "fetched_at", TimestampType(), required=True), NestedField(6, "payload", StringType(), required=True),
)
BAR_SCHEMA = Schema(
    NestedField(1, "symbol", StringType(), required=True), NestedField(2, "trading_date", DateType(), required=True),
    NestedField(3, "open", DoubleType(), required=True), NestedField(4, "high", DoubleType(), required=True),
    NestedField(5, "low", DoubleType(), required=True), NestedField(6, "close", DoubleType(), required=True),
    NestedField(7, "volume", LongType(), required=True), NestedField(8, "source", StringType(), required=True),
    NestedField(9, "pipeline_run_id", StringType(), required=True), NestedField(10, "ingested_at", TimestampType(), required=True),
)
RELATIONSHIP_SCHEMA = Schema(
    NestedField(1, "analysis_run_id", StringType(), required=True), NestedField(2, "as_of_date", DateType(), required=True),
    NestedField(3, "leader_symbol", StringType(), required=True), NestedField(4, "follower_symbol", StringType(), required=True),
    NestedField(5, "lag_days", LongType(), required=True), NestedField(6, "correlation", DoubleType(), required=True),
    NestedField(7, "sample_size", LongType(), required=True), NestedField(8, "window_start", DateType(), required=True), NestedField(9, "window_end", DateType(), required=True),
)
BRIEF_SCHEMA = Schema(
    NestedField(1, "insight_id", StringType(), required=True), NestedField(2, "analysis_run_id", StringType(), required=True),
    NestedField(3, "as_of_date", DateType(), required=True), NestedField(4, "headline", StringType(), required=True),
    NestedField(5, "body", StringType(), required=True), NestedField(6, "evidence", StringType(), required=True), NestedField(7, "created_at", TimestampType(), required=True),
)
EVENT_ARTICLE_SCHEMA = Schema(
    NestedField(1, "event_id", StringType(), required=True), NestedField(2, "title", StringType(), required=True),
    NestedField(3, "url", StringType(), required=True), NestedField(4, "domain", StringType(), required=True),
    NestedField(5, "seen_at", TimestampType(), required=True), NestedField(6, "query", StringType(), required=True),
    NestedField(7, "source_payload", StringType(), required=True), NestedField(8, "fetched_at", TimestampType(), required=True),
)
EVENT_LINK_SCHEMA = Schema(
    NestedField(1, "link_id", StringType(), required=True), NestedField(2, "analysis_run_id", StringType(), required=True),
    NestedField(3, "leader_symbol", StringType(), required=True), NestedField(4, "follower_symbol", StringType(), required=True),
    NestedField(5, "event_id", StringType(), required=True), NestedField(6, "title", StringType(), required=True),
    NestedField(7, "url", StringType(), required=True), NestedField(8, "domain", StringType(), required=True),
    NestedField(9, "seen_at", TimestampType(), required=True), NestedField(10, "link_type", StringType(), required=True),
)


@lru_cache(maxsize=1)
def catalog():
    return load_catalog("market_echo", type="rest", uri=settings.iceberg_catalog_uri, warehouse="warehouse",
        **{"s3.endpoint": settings.s3_endpoint, "s3.access-key-id": "test", "s3.secret-access-key": "test", "s3.region": "us-east-1", "s3.path-style-access": "true", "rest.client.connection-timeout-ms": "5000", "rest.client.socket-timeout-ms": "30000"})


def ensure_lakehouse() -> None:
    lake = catalog()
    for namespace in ("bronze", "silver", "gold"):
        try:
            lake.create_namespace(namespace)
        except NamespaceAlreadyExistsError:
            pass
    for identifier, schema in (("bronze.market_price_payloads", RAW_SCHEMA), ("bronze.event_article_payloads", EVENT_ARTICLE_SCHEMA), ("silver.daily_bars", BAR_SCHEMA), ("gold.sector_relationships", RELATIONSHIP_SCHEMA), ("gold.daily_briefs", BRIEF_SCHEMA), ("gold.event_market_links", EVENT_LINK_SCHEMA)):
        try:
            lake.load_table(identifier)
        except NoSuchTableError:
            lake.create_table(identifier, schema=schema)


def append_raw_bars(pipeline_run_id: str, symbol: str, bars: list[dict]) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    payloads = [{"raw_id": f"{pipeline_run_id}:{symbol}:{bar['trading_date'].isoformat()}", "pipeline_run_id": pipeline_run_id, "symbol": symbol,
                 "provider": bar["source"], "fetched_at": now, "payload": json.dumps({**bar, "trading_date": bar["trading_date"].isoformat()})} for bar in bars]
    if payloads:
        catalog().load_table("bronze.market_price_payloads").append(pa.Table.from_pylist(payloads, schema=RAW_SCHEMA.as_arrow()))


def upsert_daily_bars(pipeline_run_id: str, symbol: str, bars: list[dict]) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [{"symbol": symbol, **bar, "pipeline_run_id": pipeline_run_id, "ingested_at": now} for bar in bars]
    if rows:
        table = catalog().load_table("silver.daily_bars")
        table.upsert(pa.Table.from_pylist(rows, schema=BAR_SCHEMA.as_arrow()), join_cols=("symbol", "trading_date"))


def load_daily_bars() -> list[dict]:
    return catalog().load_table("silver.daily_bars").scan().to_arrow().to_pylist()


def append_relationships(rows: list[dict]) -> None:
    if rows:
        catalog().load_table("gold.sector_relationships").append(pa.Table.from_pylist(rows, schema=RELATIONSHIP_SCHEMA.as_arrow()))


def append_brief(row: dict) -> None:
    # The daily brief is a materialized view keyed by date, so activity retries replace it.
    catalog().load_table("gold.daily_briefs").upsert(
        pa.Table.from_pylist([row], schema=BRIEF_SCHEMA.as_arrow()), join_cols=("insight_id",)
    )


def upsert_event_articles(rows: list[dict]) -> None:
    if rows:
        catalog().load_table("bronze.event_article_payloads").upsert(
            pa.Table.from_pylist(rows, schema=EVENT_ARTICLE_SCHEMA.as_arrow()), join_cols=("event_id",)
        )


def upsert_event_links(rows: list[dict]) -> None:
    if rows:
        catalog().load_table("gold.event_market_links").upsert(
            pa.Table.from_pylist(rows, schema=EVENT_LINK_SCHEMA.as_arrow()), join_cols=("link_id",)
        )


def trino_query(sql: str) -> list[dict]:
    connection = trino.dbapi.connect(host=settings.trino_host, port=8080, user="market_echo", catalog="iceberg")
    cursor = connection.cursor()
    cursor.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
