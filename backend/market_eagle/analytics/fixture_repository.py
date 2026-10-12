"""Deterministic fixture adapter for local integration and numeric verification."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .models import AnalyticsDataset, Bar, CatalogMember


class SyntheticFixtureRepository:
    def __init__(self, directory: Path):
        with (directory / "catalog.csv").open(newline="", encoding="utf-8") as stream:
            catalog = list(csv.DictReader(stream))
        with (directory / "bars.csv").open(newline="", encoding="utf-8") as stream:
            bars = list(csv.DictReader(stream))
        with (directory / "sessions.csv").open(newline="", encoding="utf-8") as stream:
            sessions = list(csv.DictReader(stream))
        self.manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        self.members = tuple(
            CatalogMember(
                stock_id=row["stock_id"],
                ticker=row["ticker"],
                name=row["name"],
                sector_code=row["sector_code"],
                sector_name=row["sector_name"],
                listed_from=date.fromisoformat(row["listed_from"])
                if row["listed_from"]
                else None,
            )
            for row in catalog
        )
        self.snapshot_id = catalog[0]["snapshot_id"]
        self.catalog_as_of = date.fromisoformat(catalog[0]["catalog_as_of"])
        self.published_at = datetime.fromisoformat(catalog[0]["published_at"])
        self.sessions = tuple(
            date.fromisoformat(row["session_date"]) for row in sessions
        )
        self.bars = tuple(
            Bar(
                stock_id=row["stock_id"],
                session_date=date.fromisoformat(row["session_date"]),
                close=Decimal(row["close"]),
                volume=int(row["volume"]),
                vwap=Decimal(row["vwap"]) if row["vwap"] else None,
                traded_notional=Decimal(row["traded_notional"])
                if row["traded_notional"]
                else None,
                provider_as_of=datetime.fromisoformat(row["provider_as_of"]),
                as_of_kind="provider",
                status=row["status"],
            )
            for row in bars
        )

    def load(self, start: date, end: date) -> AnalyticsDataset:
        included = [day for day in self.sessions if start <= day <= end]
        preceding = (
            [day for day in self.sessions if day < included[0]] if included else []
        )
        selected_dates = set(included)
        if preceding:
            selected_dates.add(preceding[-1])
        return AnalyticsDataset(
            snapshot_id=self.snapshot_id,
            catalog_as_of=self.catalog_as_of,
            published_at=self.published_at,
            members=self.members,
            sessions=tuple(day for day in self.sessions if day <= end),
            bars=tuple(bar for bar in self.bars if bar.session_date in selected_dates),
            source=self.manifest["source"],
            feed=self.manifest["feed"],
            price_basis=self.manifest["price_basis"],
            synthetic=True,
            catalog_source="synthetic-v1",
        )
