"""Typed boundary between selected observations and analytical calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass(frozen=True)
class CatalogMember:
    stock_id: str
    ticker: str
    name: str
    sector_code: str
    sector_name: str
    listed_from: date | None


@dataclass(frozen=True)
class Bar:
    stock_id: str
    session_date: date
    close: Decimal
    volume: int
    vwap: Decimal | None
    traded_notional: Decimal | None
    provider_as_of: datetime
    status: str


@dataclass(frozen=True)
class AnalyticsDataset:
    snapshot_id: str
    catalog_as_of: date
    published_at: datetime | None
    members: tuple[CatalogMember, ...]
    sessions: tuple[date, ...]
    bars: tuple[Bar, ...]
    source: str
    feed: str
    price_basis: str
    synthetic: bool


class AnalyticsRepository(Protocol):
    """One pinned catalog and one selected source/feed/basis per batch read.

    The implementation must return all sessions through ``end`` (including the
    preceding comparison session), and selected accepted bars for the resolved
    window and comparison session. It must never mix revision candidates.
    """

    def load(self, start: date, end: date) -> AnalyticsDataset: ...


class DateWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> DateWindow:
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        return self


class DailyCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["daily_dollar_volume", "close", "volume"]
    operator: Literal["=", "<", "<=", ">", ">=", "in"]
    value: Decimal | list[Decimal]
    unit: Literal["USD", "shares", "price"]

    @model_validator(mode="after")
    def compatible(self) -> DailyCondition:
        expected = {"daily_dollar_volume": "USD", "close": "price", "volume": "shares"}[self.field]
        if self.unit != expected:
            raise ValueError(f"{self.field} requires unit {expected}")
        if self.operator == "in":
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 20:
                raise ValueError("in requires 1 to 20 values")
        elif isinstance(self.value, list):
            raise ValueError("comparison requires one value")
        return self


class FrequencyReduction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure: Literal["qualifying_days", "qualifying_fraction"]
    operator: Literal["=", "<", "<=", ">", ">="]
    value: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def valid_fraction(self) -> FrequencyReduction:
        if self.measure == "qualifying_fraction" and self.value > 1:
            raise ValueError("fraction cannot exceed 1")
        if self.measure == "qualifying_days" and self.value != self.value.to_integral_value():
            raise ValueError("day count must be an integer")
        return self


class StockPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal["stock_id", "ticker", "sector_code"]
    operator: Literal["=", "in"]
    value: str | list[str]

    @model_validator(mode="after")
    def valid_value(self) -> StockPredicate:
        if self.operator == "in":
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 100:
                raise ValueError("in requires 1 to 100 identifiers")
        elif not isinstance(self.value, str) or not self.value:
            raise ValueError("= requires one identifier")
        return self


class SortSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure: Literal["period_return", "excess_vs_sector", "breadth", "sector_return", "qualifying_fraction", "qualifying_days"]
    direction: Literal["asc", "desc"] = "desc"


class AnalyticalRequest(BaseModel):
    """Allowlisted analytical operations, with no SQL or free-form expressions."""

    model_config = ConfigDict(extra="forbid")

    request_version: Literal[1]
    universe: Literal["latest_published_catalog"]
    window: DateWindow
    grain: Literal["stock", "sector"]
    measures: list[Literal["period_return", "excess_vs_sector", "breadth", "sector_return", "market_return", "qualifying_days", "qualifying_fraction", "observed_usable_days", "requested_sessions"]] = Field(min_length=1)
    daily_conditions: list[DailyCondition] = Field(default_factory=list, max_length=5)
    reduction: FrequencyReduction | None = None
    predicates: list[StockPredicate] = Field(default_factory=list, max_length=5)
    group_by: list[Literal["stock_id", "sector_code"]] = Field(default_factory=list, max_length=1)
    sort: SortSpec
    limit: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def compatible(self) -> AnalyticalRequest:
        if self.reduction and not self.daily_conditions:
            raise ValueError("frequency reduction requires daily conditions")
        frequency_measures = {"qualifying_days", "qualifying_fraction"}
        if not self.daily_conditions and (frequency_measures.intersection(self.measures) or self.sort.measure in frequency_measures):
            raise ValueError("qualifying measures require daily conditions")
        if self.grain == "stock":
            if self.group_by not in ([], ["stock_id"]):
                raise ValueError("stock grain groups by stock_id")
            if self.sort.measure in {"breadth", "sector_return"}:
                raise ValueError("sort measure is incompatible with stock grain")
        else:
            if self.group_by not in ([], ["sector_code"]):
                raise ValueError("sector grain groups by sector_code")
            if self.daily_conditions or self.reduction:
                raise ValueError("daily frequency requires stock grain")
            if self.sort.measure not in {"breadth", "sector_return"}:
                raise ValueError("sort measure is incompatible with sector grain")
        if self.sort.measure not in self.measures:
            raise ValueError("sort measure must be selected")
        if self.grain == "sector" and any(m in self.measures for m in ("period_return", "excess_vs_sector", "qualifying_days", "qualifying_fraction", "observed_usable_days")):
            raise ValueError("stock measures require stock grain")
        if self.grain == "stock" and "breadth" in self.measures:
            raise ValueError("breadth requires sector grain")
        return self
