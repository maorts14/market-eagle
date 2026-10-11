"""Read one published catalog and its selected daily observations from PostgreSQL."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .models import (
    AnalyticsDataset,
    Bar,
    CatalogMember,
    DailyCondition,
    DailyStockStats,
)

SQL_DIR = Path(__file__).resolve().parent / "helpers" / "db" / "sql"
ENDPOINT_SQL = (SQL_DIR / "explorer_endpoints.sql").read_text(encoding="utf-8")
FREQUENCY_SQL = (SQL_DIR / "daily_frequency.sql").read_text(encoding="utf-8")

DAILY_FIELDS = {
    "close": "b.close",
    "volume": "b.volume",
    "daily_dollar_volume": (
        "coalesce(b.traded_notional, b.volume * b.vwap, b.volume * b.close)"
    ),
}
COMPARISONS = {"=", "<", "<=", ">", ">="}


def daily_predicate(conditions: list[DailyCondition]) -> tuple[str, list]:
    clauses = []
    values = []
    for condition in conditions:
        field = DAILY_FIELDS[condition.field]
        if condition.operator == "in":
            clauses.append(f"{field} = ANY(%s::numeric[])")
        else:
            if condition.operator not in COMPARISONS:
                raise ValueError("unsupported daily comparison")
            clauses.append(f"{field} {condition.operator} %s")
        values.append(condition.value)
    return (" AND ".join(clauses) if clauses else "false"), values


class PostgresAnalyticsRepository:
    def __init__(
        self,
        database_url: str,
        *,
        source: str,
        feed: str,
        price_basis: str,
        exchange: str,
        statement_timeout_ms: int = 30_000,
    ) -> None:
        self.database_url = database_url
        self.source = source
        self.feed = feed
        self.price_basis = price_basis
        self.exchange = exchange
        if statement_timeout_ms < 1:
            raise ValueError("statement timeout must be positive")
        self.statement_timeout_ms = statement_timeout_ms

    def load(self, start: date, end: date) -> AnalyticsDataset:
        return self._load(start, end, None)

    def load_with_daily_stats(
        self, start: date, end: date, daily_conditions: list[DailyCondition]
    ) -> AnalyticsDataset:
        return self._load(start, end, daily_conditions)

    def _load(
        self,
        start: date,
        end: date,
        daily_conditions: list[DailyCondition] | None = None,
    ) -> AnalyticsDataset:
        with (
            psycopg.connect(
                self.database_url, autocommit=True, row_factory=dict_row
            ) as conn,
            conn.transaction(),
        ):
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self.statement_timeout_ms),),
            )
            snapshot = conn.execute(
                """SELECT s.snapshot_id, s.as_of, s.published_at
                       FROM catalog_current c
                       JOIN universe_snapshot s ON s.snapshot_id = c.snapshot_id
                       WHERE c.singleton AND s.validation_state = 'published'"""
            ).fetchone()
            if snapshot is None:
                return AnalyticsDataset(
                    snapshot_id="",
                    catalog_as_of=end,
                    published_at=None,
                    members=(),
                    sessions=(),
                    bars=(),
                    source=self.source,
                    feed=self.feed,
                    price_basis=self.price_basis,
                    synthetic=False,
                )

            source_row = conn.execute(
                "SELECT synthetic FROM data_source WHERE source = %s AND feed = %s",
                (self.source, self.feed),
            ).fetchone()
            members = conn.execute(
                """SELECT m.stock_id, m.source_ticker AS ticker, s.name,
                              m.sector_code, sector.sector_name,
                              first_listing.listed_from
                       FROM universe_member m
                       JOIN security s ON s.stock_id = m.stock_id
                       JOIN sector ON sector.taxonomy = m.taxonomy
                                  AND sector.sector_code = m.sector_code
                       LEFT JOIN LATERAL (
                           SELECT min(valid_from) AS listed_from
                           FROM listing_period lp
                           WHERE lp.stock_id = m.stock_id AND lp.exchange = %s
                       ) first_listing ON true
                       WHERE m.snapshot_id = %s
                       ORDER BY m.stock_id""",
                (self.exchange, snapshot["snapshot_id"]),
            ).fetchall()
            sessions = conn.execute(
                """SELECT session_date FROM trading_session
                       WHERE exchange = %s AND (session_date BETWEEN %s AND %s
                         OR session_date = (SELECT max(session_date) FROM trading_session
                                            WHERE exchange = %s AND session_date < %s))
                       ORDER BY session_date""",
                (self.exchange, start, end, self.exchange, start),
            ).fetchall()
            comparison = next(
                (
                    row["session_date"]
                    for row in reversed(sessions)
                    if row["session_date"] < start
                ),
                None,
            )
            final = next(
                (
                    row["session_date"]
                    for row in reversed(sessions)
                    if start <= row["session_date"] <= end
                ),
                None,
            )
            endpoint_dates = [day for day in (comparison, final) if day is not None]
            bars = (
                conn.execute(
                    ENDPOINT_SQL,
                    (
                        snapshot["snapshot_id"],
                        self.source,
                        self.feed,
                        self.price_basis,
                        endpoint_dates,
                    ),
                ).fetchall()
                if endpoint_dates
                else []
            )
            daily_stats = None
            if daily_conditions is not None:
                predicate, values = daily_predicate(daily_conditions)
                rows = conn.execute(
                    FREQUENCY_SQL.replace("/* DAILY_CONDITION */", predicate),
                    (
                        *values,
                        self.source,
                        self.feed,
                        self.price_basis,
                        start,
                        end,
                        snapshot["snapshot_id"],
                    ),
                ).fetchall()
                dollar_condition = any(
                    condition.field == "daily_dollar_volume"
                    for condition in daily_conditions
                )
                daily_stats = tuple(
                    DailyStockStats(
                        stock_id=row["stock_id"],
                        observed_usable_days=row["observed_usable_days"],
                        qualifying_days=row["qualifying_days"],
                        dollar_volume_inputs=tuple(
                            name
                            for present, name in (
                                (row["has_reported_notional"], "reported_notional"),
                                (row["has_vwap_estimate"], "volume_x_vwap_estimate"),
                                (row["has_close_estimate"], "volume_x_close_estimate"),
                            )
                            if dollar_condition and present
                        ),
                        data_as_of=row["data_as_of"],
                        as_of_kinds=frozenset(
                            kind
                            for present, kind in (
                                (row["has_provider_as_of"], "provider"),
                                (row["has_fetched_as_of"], "fetched"),
                            )
                            if present
                        ),
                        provisional=bool(row["provisional"]),
                    )
                    for row in rows
                )

        return AnalyticsDataset(
            snapshot_id=snapshot["snapshot_id"],
            catalog_as_of=snapshot["as_of"],
            published_at=snapshot["published_at"],
            members=tuple(CatalogMember(**row) for row in members),
            sessions=tuple(row["session_date"] for row in sessions),
            bars=tuple(
                Bar(
                    stock_id=row["stock_id"],
                    session_date=row["session_date"],
                    close=row["close"],
                    volume=row["volume"],
                    vwap=row["vwap"],
                    traded_notional=row["traded_notional"],
                    provider_as_of=row["provider_as_of"],
                    as_of_kind=row["as_of_kind"],
                    status=row["observation_status"],
                )
                for row in bars
            ),
            source=self.source if source_row else "",
            feed=self.feed if source_row else "",
            price_basis=self.price_basis,
            synthetic=bool(source_row and source_row["synthetic"]),
            daily_stats=daily_stats,
        )
