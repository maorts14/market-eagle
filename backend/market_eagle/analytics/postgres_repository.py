"""Read one published catalog and its selected daily observations from PostgreSQL."""

from __future__ import annotations

from datetime import date

import psycopg
from psycopg.rows import dict_row

from .models import AnalyticsDataset, Bar, CatalogMember


class PostgresAnalyticsRepository:
    def __init__(
        self,
        database_url: str,
        *,
        source: str,
        feed: str,
        price_basis: str,
        exchange: str,
    ) -> None:
        self.database_url = database_url
        self.source = source
        self.feed = feed
        self.price_basis = price_basis
        self.exchange = exchange

    def load(self, start: date, end: date) -> AnalyticsDataset:
        with (
            psycopg.connect(
                self.database_url, autocommit=True, row_factory=dict_row
            ) as conn,
            conn.transaction(),
        ):
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
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
                       WHERE exchange = %s AND session_date <= %s
                       ORDER BY session_date""",
                (self.exchange, end),
            ).fetchall()
            comparison = next(
                (
                    row["session_date"]
                    for row in reversed(sessions)
                    if row["session_date"] < start
                ),
                start,
            )
            bars = conn.execute(
                """SELECT b.stock_id, b.session_date, b.close, b.volume, b.vwap,
                              b.traded_notional, b.provider_as_of,
                              b.observation_status
                       FROM selected_daily_bar b
                       JOIN universe_member m ON m.stock_id = b.stock_id
                       WHERE m.snapshot_id = %s AND b.source = %s AND b.feed = %s
                         AND b.price_basis = %s
                         AND b.session_date >= %s AND b.session_date <= %s
                       ORDER BY b.stock_id, b.session_date""",
                (
                    snapshot["snapshot_id"],
                    self.source,
                    self.feed,
                    self.price_basis,
                    comparison,
                    end,
                ),
            ).fetchall()

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
                    status=row["observation_status"],
                )
                for row in bars
            ),
            source=self.source if source_row else "",
            feed=self.feed if source_row else "",
            price_basis=self.price_basis,
            synthetic=bool(source_row and source_row["synthetic"]),
        )
