"""Shared explorer and typed analytical calculations over one pinned batch."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .models import (
    AnalyticalRequest,
    AnalyticsDataset,
    AnalyticsRepository,
    Bar,
    DailyCondition,
    DailyStockStats,
    DateWindow,
)


class AnalyticsError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code, self.message, self.status, self.details = (
            code,
            message,
            status,
            details or {},
        )


def _compare(
    left: Decimal | str, operator: str, right: Decimal | str | list[Decimal] | list[str]
) -> bool:
    if operator == "in":
        return left in right
    if operator == "=":
        return left == right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    return left >= right


def _daily_value(bar: Bar, field: str) -> tuple[Decimal, str | None]:
    if field == "close":
        return bar.close, None
    if field == "volume":
        return Decimal(bar.volume), None
    if bar.traded_notional is not None:
        return bar.traded_notional, "reported_notional"
    if bar.vwap is not None:
        return Decimal(bar.volume) * bar.vwap, "volume_x_vwap_estimate"
    return Decimal(bar.volume) * bar.close, "volume_x_close_estimate"


class AnalyticsService:
    def __init__(self, repository: AnalyticsRepository):
        self.repository = repository

    def _context(
        self,
        window: DateWindow,
        *,
        require_comparison: bool = True,
        daily_conditions: list[DailyCondition] | None = None,
    ) -> tuple[
        AnalyticsDataset, dict[str, Any], dict[tuple[str, date], Bar], list[date]
    ]:
        daily_loader = getattr(self.repository, "load_with_daily_stats", None)
        dataset = (
            daily_loader(window.start, window.end, daily_conditions)
            if daily_conditions is not None and daily_loader is not None
            else self.repository.load(window.start, window.end)
        )
        if not dataset.members:
            raise AnalyticsError(
                "no_published_catalog", "No published catalog is available", 404
            )
        if not dataset.source or not dataset.feed or not dataset.price_basis:
            raise AnalyticsError(
                "selected_data_unavailable",
                "Selected source, feed, or price basis is unavailable",
                503,
            )
        sessions = sorted(set(dataset.sessions))
        included = [day for day in sessions if window.start <= day <= window.end]
        if not included:
            raise AnalyticsError(
                "no_sessions", "No trading sessions fall in the requested window", 422
            )
        prior = [day for day in sessions if day < included[0]]
        if require_comparison and not prior:
            raise AnalyticsError(
                "no_comparison_session",
                "No preceding comparison session is available",
                422,
            )
        comparison = prior[-1] if require_comparison else None
        selected = {(bar.stock_id, bar.session_date): bar for bar in dataset.bars}
        resolved = {
            "comparison_session": comparison,
            "first_session": included[0],
            "last_session": included[-1],
        }
        return dataset, resolved, selected, included

    def _calculate(
        self,
        window: DateWindow,
        daily_conditions: list[DailyCondition] | None = None,
    ) -> tuple[
        dict[str, Any],
        dict[tuple[str, date], Bar],
        list[date],
        tuple[DailyStockStats, ...] | None,
    ]:
        dataset, resolved, selected, sessions = self._context(
            window, daily_conditions=daily_conditions
        )
        comparison, final = resolved["comparison_session"], resolved["last_session"]
        stock_rows: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
        tracked_by_sector: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        for member in dataset.members:
            tracked_by_sector[member.sector_code] += 1
            names[member.sector_code] = member.sector_name
            first_bar = selected.get((member.stock_id, comparison))
            last_bar = selected.get((member.stock_id, final))
            if (
                first_bar is None
                or last_bar is None
                or first_bar.close <= 0
                or last_bar.close <= 0
            ):
                missing = []
                if first_bar is None or (first_bar and first_bar.close <= 0):
                    missing.append("comparison_close")
                if last_bar is None or (last_bar and last_bar.close <= 0):
                    missing.append("final_close")
                excluded.append(
                    {
                        "stock_id": member.stock_id,
                        "ticker": member.ticker,
                        "reason": "missing_" + "_and_".join(missing),
                    }
                )
                continue
            stock_return = last_bar.close / first_bar.close - 1
            row = {
                "stock_id": member.stock_id,
                "ticker": member.ticker,
                "name": member.name,
                "sector_code": member.sector_code,
                "return": stock_return,
                "comparison_close": first_bar.close,
                "final_close": last_bar.close,
                "final_observation_status": last_bar.status,
                "data_as_of": last_bar.provider_as_of,
                "data_as_of_kind": last_bar.as_of_kind,
                "listed_from": member.listed_from,
            }
            stock_rows.append(row)
            by_sector[member.sector_code].append(row)
        market_return = (
            sum((row["return"] for row in stock_rows), Decimal(0)) / len(stock_rows)
            if stock_rows
            else None
        )
        sectors = []
        for code, tracked_count in tracked_by_sector.items():
            members = by_sector[code]
            count = len(members)
            sector_return = (
                sum((row["return"] for row in members), Decimal(0)) / count
                if count
                else None
            )
            for row in members:
                row["excess_vs_sector"] = row["return"] - sector_return
            sectors.append(
                {
                    "sector_code": code,
                    "sector_name": names[code],
                    "tracked_count": tracked_count,
                    "eligible_count": count,
                    "excluded_count": tracked_count - count,
                    "up_count": sum(row["return"] > 0 for row in members),
                    "breadth": Decimal(sum(row["return"] > 0 for row in members))
                    / count
                    if count
                    else None,
                    "return": sector_return,
                    "excess_vs_market": sector_return - market_return
                    if count and market_return is not None
                    else None,
                    "stocks": sorted(
                        members,
                        key=lambda row: (-row["excess_vs_sector"], row["ticker"]),
                    ),
                }
            )
        sectors.sort(
            key=lambda row: (
                row["breadth"] is None,
                -(row["breadth"] or Decimal(0)),
                row["sector_code"],
            )
        )
        as_of = min((row["data_as_of"] for row in stock_rows), default=None)
        as_of_kinds = {row["data_as_of_kind"] for row in stock_rows}
        result = {
            "contract_version": 1,
            "metric_version": "return-v1",
            "requested_window": window.model_dump(),
            "resolved_window": resolved,
            "catalog": {
                "snapshot_id": dataset.snapshot_id,
                "as_of": dataset.catalog_as_of,
                "published_at": dataset.published_at,
                "tracked_count": len(dataset.members),
                **(
                    {"scope": "private_five_stock_sample"}
                    if dataset.catalog_source == "alpaca-sample-v1"
                    else {}
                ),
            },
            "data": {
                "source": dataset.source,
                "feed": dataset.feed,
                "price_basis": dataset.price_basis,
                "as_of": as_of,
                "as_of_kind": next(iter(as_of_kinds))
                if len(as_of_kinds) == 1
                else "mixed"
                if as_of_kinds
                else None,
                "provisional": any(
                    row["final_observation_status"] == "provisional"
                    for row in stock_rows
                ),
                "synthetic": dataset.synthetic,
                "return_rankings_trusted": False,
            },
            "market": {
                "eligible_count": len(stock_rows),
                "excluded_count": len(excluded),
                "return": market_return,
            },
            "sectors": sectors,
            "exclusions": excluded,
            "calculated_at": datetime.now(timezone.utc),
        }
        return result, selected, sessions, dataset.daily_stats

    def _frequency_calculate(
        self, window: DateWindow, daily_conditions: list[DailyCondition]
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        dict[tuple[str, date], Bar],
        list[date],
        tuple[DailyStockStats, ...] | None,
    ]:
        dataset, resolved, selected, sessions = self._context(
            window, require_comparison=False, daily_conditions=daily_conditions
        )
        stats_by_stock = (
            {item.stock_id: item for item in dataset.daily_stats}
            if dataset.daily_stats is not None
            else None
        )
        stock_rows: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        usable_bars: list[Bar] = []
        for member in dataset.members:
            usable = (
                None
                if stats_by_stock is not None
                else [
                    bar
                    for day in sessions
                    if (bar := selected.get((member.stock_id, day))) is not None
                    and bar.close > 0
                    and bar.volume >= 0
                ]
            )
            observed_count = (
                stats_by_stock[member.stock_id].observed_usable_days
                if stats_by_stock is not None
                else len(usable)
            )
            if not observed_count:
                excluded.append(
                    {
                        "stock_id": member.stock_id,
                        "ticker": member.ticker,
                        "reason": "missing_usable_daily_observations",
                    }
                )
                continue
            if usable is not None:
                usable_bars.extend(usable)
            stock_rows.append(
                {
                    "stock_id": member.stock_id,
                    "ticker": member.ticker,
                    "name": member.name,
                    "sector_code": member.sector_code,
                    "return": None,
                    "excess_vs_sector": None,
                    "sector_return": None,
                    "market_return": None,
                    "listed_from": member.listed_from,
                }
            )
        as_of_kinds = (
            set().union(*(item.as_of_kinds for item in dataset.daily_stats))
            if dataset.daily_stats is not None
            else {bar.as_of_kind for bar in usable_bars}
        )
        result = {
            "metric_version": "daily-frequency-v1",
            "requested_window": window.model_dump(),
            "resolved_window": resolved,
            "catalog": {
                "snapshot_id": dataset.snapshot_id,
                "as_of": dataset.catalog_as_of,
                "published_at": dataset.published_at,
                "tracked_count": len(dataset.members),
                **(
                    {"scope": "private_five_stock_sample"}
                    if dataset.catalog_source == "alpaca-sample-v1"
                    else {}
                ),
            },
            "data": {
                "source": dataset.source,
                "feed": dataset.feed,
                "price_basis": dataset.price_basis,
                "as_of": (
                    min(
                        (
                            item.data_as_of
                            for item in dataset.daily_stats
                            if item.data_as_of is not None
                        ),
                        default=None,
                    )
                    if dataset.daily_stats is not None
                    else min((bar.provider_as_of for bar in usable_bars), default=None)
                ),
                "as_of_kind": next(iter(as_of_kinds))
                if len(as_of_kinds) == 1
                else "mixed"
                if as_of_kinds
                else None,
                "provisional": (
                    any(item.provisional for item in dataset.daily_stats)
                    if dataset.daily_stats is not None
                    else any(bar.status == "provisional" for bar in usable_bars)
                ),
                "synthetic": dataset.synthetic,
                "return_rankings_trusted": False,
            },
            "market": {
                "eligible_count": len(stock_rows),
                "excluded_count": len(excluded),
                "return": None,
            },
            "exclusions": excluded,
            "calculated_at": datetime.now(timezone.utc),
        }
        return result, stock_rows, selected, sessions, dataset.daily_stats

    def explorer(self, start: date, end: date) -> dict[str, Any]:
        try:
            window = DateWindow(start=start, end=end)
        except ValueError as error:
            raise AnalyticsError(
                "invalid_range", "start must be on or before end", 400
            ) from error
        result, _, _, _ = self._calculate(window)
        for sector in result["sectors"]:
            for stock in sector["stocks"]:
                stock.pop("sector_code")
                stock.pop("listed_from")
        return result

    def execute(self, request: AnalyticalRequest) -> dict[str, Any]:
        return_measures = {
            "period_return",
            "excess_vs_sector",
            "sector_return",
            "market_return",
            "breadth",
        }
        requires_return = request.grain == "sector" or bool(
            return_measures.intersection(request.measures)
        )
        if requires_return:
            result, selected, sessions, daily_stats = self._calculate(
                request.window, request.daily_conditions
            )
            stock_rows = [
                dict(
                    stock,
                    sector_code=sector["sector_code"],
                    sector_return=sector["return"],
                    market_return=result["market"]["return"],
                )
                for sector in result["sectors"]
                for stock in sector["stocks"]
            ]
        else:
            result, stock_rows, selected, sessions, daily_stats = (
                self._frequency_calculate(request.window, request.daily_conditions)
            )
        stats_by_stock = (
            {item.stock_id: item for item in daily_stats}
            if daily_stats is not None
            else None
        )
        filtered = []
        for row in stock_rows:
            if not all(
                _compare(row[p.field], p.operator, p.value) for p in request.predicates
            ):
                continue
            if stats_by_stock is not None:
                stock_stats = stats_by_stock[row["stock_id"]]
                observed_count = stock_stats.observed_usable_days
                qualifying = stock_stats.qualifying_days
                provenance = set(stock_stats.dollar_volume_inputs)
            else:
                usable = [
                    selected[(row["stock_id"], day)]
                    for day in sessions
                    if (row["stock_id"], day) in selected
                ]
                usable = [bar for bar in usable if bar.close > 0 and bar.volume >= 0]
                observed_count = len(usable)
                qualifying = 0
                provenance: set[str] = set()
                for bar in usable:
                    matches = []
                    for condition in request.daily_conditions:
                        value, origin = _daily_value(bar, condition.field)
                        if origin:
                            provenance.add(origin)
                        matches.append(
                            _compare(value, condition.operator, condition.value)
                        )
                    qualifying += bool(matches) and all(matches)
            fraction = Decimal(qualifying) / observed_count if observed_count else None
            if request.reduction:
                metric = (
                    Decimal(qualifying)
                    if request.reduction.measure == "qualifying_days"
                    else fraction
                )
                if metric is None or not _compare(
                    metric, request.reduction.operator, request.reduction.value
                ):
                    continue
            listed_sessions = sum(
                row["listed_from"] is None or day >= row["listed_from"]
                for day in sessions
            )
            filtered.append(
                {
                    "stock_id": row["stock_id"],
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "sector_code": row["sector_code"],
                    "period_return": row["return"],
                    "excess_vs_sector": row["excess_vs_sector"],
                    "sector_return": row["sector_return"],
                    "market_return": row["market_return"],
                    "qualifying_days": qualifying if request.daily_conditions else None,
                    "observed_usable_days": observed_count,
                    "qualifying_fraction": fraction
                    if request.daily_conditions
                    else None,
                    "requested_sessions": len(sessions),
                    "known_listing_sessions": listed_sessions,
                    "requested_coverage": Decimal(observed_count) / len(sessions),
                    "known_listing_coverage": Decimal(observed_count) / listed_sessions
                    if listed_sessions
                    else None,
                    "dollar_volume_inputs": sorted(provenance),
                    "dollar_volume_formulas": [
                        {
                            "input": origin,
                            "formula": formula,
                            "estimated": origin != "reported_notional",
                        }
                        for origin, formula in (
                            ("reported_notional", "provider reported traded notional"),
                            ("volume_x_vwap_estimate", "share volume × daily VWAP"),
                            ("volume_x_close_estimate", "share volume × daily close"),
                        )
                        if origin in provenance
                    ],
                }
            )
        if request.grain == "stock":
            key = request.sort.measure
            rows = sorted(
                filtered,
                key=lambda row: (
                    row[key] is None,
                    -(row[key] or 0)
                    if request.sort.direction == "desc"
                    else row[key] or 0,
                    row["ticker"],
                ),
            )
        else:
            sector_codes = (
                {row["sector_code"] for row in filtered}
                if request.predicates
                else {sector["sector_code"] for sector in result["sectors"]}
            )
            rows = [
                {
                    "sector_code": sector["sector_code"],
                    "breadth": sector["breadth"],
                    "sector_return": sector["return"],
                    "market_return": result["market"]["return"],
                    "eligible_count": sector["eligible_count"],
                    "tracked_count": sector["tracked_count"],
                }
                for sector in result["sectors"]
                if sector["sector_code"] in sector_codes
            ]
            key = request.sort.measure
            rows.sort(
                key=lambda row: (
                    row[key] is None,
                    -(row[key] or 0)
                    if request.sort.direction == "desc"
                    else row[key] or 0,
                    row["sector_code"],
                )
            )
        return {
            "request_version": 1,
            "metric_version": result["metric_version"],
            "requested_window": result["requested_window"],
            "resolved_window": result["resolved_window"],
            "catalog": result["catalog"],
            "data": result["data"],
            "market": result["market"],
            "grain": request.grain,
            "selected_measures": request.measures,
            "eligible_count": len(stock_rows),
            "matched_count": len(rows),
            "exclusions": result["exclusions"],
            "rows": rows[: request.limit],
            "calculated_at": result["calculated_at"],
        }
