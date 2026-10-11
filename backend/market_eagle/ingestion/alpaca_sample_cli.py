"""Stage, review, and privately collect a five-stock Alpaca validation sample."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import psycopg

from .alpaca_preparation import collection_request
from .alpaca_reference import fetch_assets, fetch_calendar
from .alpaca_sample import approve_sample, review_sample, stage_sample


def summarize_bar_coverage(
    sessions: list[dict], start: date, end: date, observed: dict[str, list[str]]
) -> dict:
    """Compare session dates, including the preceding close, without exposing prices."""
    comparison = comparison_session(sessions, start)
    expected = {
        item["date"]
        for item in sessions
        if comparison <= item["date"] <= end.isoformat()
    }
    by_symbol = {}
    for symbol, dates in observed.items():
        counts = Counter(dates)
        actual = set(counts)
        by_symbol[symbol] = {
            "bar_count": len(dates),
            "missing_sessions": sorted(expected - actual),
            "unexpected_dates": sorted(actual - expected),
            "duplicate_date_count": sum(count - 1 for count in counts.values()),
        }
    return {
        "comparison_session": comparison,
        "expected_session_count": len(expected),
        "symbols": by_symbol,
        "complete": all(
            not item["missing_sessions"]
            and not item["unexpected_dates"]
            and item["duplicate_date_count"] == 0
            for item in by_symbol.values()
        ),
    }


def comparison_session(sessions: list[dict], start: date) -> str:
    prior = [item["date"] for item in sessions if item["date"] < start.isoformat()]
    if not prior:
        raise ValueError("calendar lacks a preceding comparison session")
    return max(prior)


def main() -> None:
    if os.environ.get("MARKET_EAGLE_RUNTIME") == "production":
        raise RuntimeError("production cannot run the five-stock test sample")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--symbols", nargs=5, required=True)
        command.add_argument("--start", type=date.fromisoformat, required=True)
        command.add_argument("--end", type=date.fromisoformat, required=True)
        if name == "probe":
            command.add_argument("--bars", action="store_true")
            command.add_argument("--asof", type=date.fromisoformat)
    for name in ("review", "draft", "request", "collect"):
        command = commands.add_parser(name)
        command.add_argument("stage_id")
        if name == "draft":
            command.add_argument("--output", type=Path, required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("approval_file", type=Path)
    args = parser.parse_args()

    if args.command in ("probe", "stage", "collect"):
        key_id = os.environ.get("ALPACA_API_KEY_ID")
        secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not secret:
            parser.error("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are required")
    if args.command in ("probe", "stage"):
        with httpx.Client() as client:
            all_assets = fetch_assets(client, key_id, secret)
            sessions = fetch_calendar(client, key_id, secret, args.start, args.end)
        assets = [item for item in all_assets if item["symbol"] in args.symbols]
        if len(assets) != 5 or len({item["symbol"] for item in assets}) != 5:
            raise ValueError("each of the five symbols needs one current Alpaca asset")
        if args.command == "probe":
            result = {
                "source": "alpaca-sample-v1",
                "membership_claim": "private five-stock sample; not S&P 500",
                "symbols": [item["symbol"] for item in assets],
                "asset_count": len(assets),
                "calendar_session_count": len(sessions),
            }
            if args.bars:
                from .alpaca import historical_pages
                from .worker import _pace_provider

                observed = {symbol: [] for symbol in args.symbols}
                comparison = comparison_session(sessions, args.start)
                symbol_asof = args.asof or datetime.now(timezone.utc).date()
                pages = 0
                with httpx.Client() as client:
                    for payload, _observed_at in historical_pages(
                        client,
                        key_id=key_id,
                        secret_key=secret,
                        symbols=args.symbols,
                        start=date.fromisoformat(comparison),
                        end=args.end,
                        feed="sip",
                        adjustment="raw",
                        max_pages=3,
                        asof=symbol_asof,
                        before_request=_pace_provider,
                    ):
                        pages += 1
                        for symbol, rows in payload["bars"].items():
                            if symbol not in observed:
                                raise ValueError(
                                    "Alpaca returned a symbol outside the sample"
                                )
                            observed[symbol].extend(row["t"][:10] for row in rows)
                result["historical_probe"] = {
                    "feed": "sip",
                    "price_basis": "raw",
                    "pages": pages,
                    "symbol_asof": symbol_asof.isoformat(),
                    **summarize_bar_coverage(sessions, args.start, args.end, observed),
                }
            print(json.dumps(result, indent=2))
            return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    with psycopg.connect(database_url) as conn:
        if args.command == "stage":
            result = stage_sample(
                conn,
                symbols=args.symbols,
                requested_start=args.start,
                requested_end=args.end,
                assets=assets,
                sessions=sessions,
                fetched_at=datetime.now(timezone.utc),
            )
        elif args.command == "review":
            result = review_sample(conn, args.stage_id)
        elif args.command == "draft":
            report = review_sample(conn, args.stage_id)
            result = {
                "stage_id": args.stage_id,
                "checksum": report["checksum"],
                "reviewer": "",
                "review_note": "",
                "identity_assumption": "",
                "aliases": [
                    {
                        "stock_id": item["stock_id"],
                        "asset_id": item["asset_id"],
                        "symbol": item["symbol"],
                        "exchange": item["exchange"],
                        "verified_from": "",
                        "verified_to": None,
                        "evidence": "",
                    }
                    for item in report["assets"]
                ],
            }
            args.output.write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps({"draft_written": str(args.output), "alias_count": 5}))
            return
        elif args.command == "approve":
            approval = json.loads(args.approval_file.read_text(encoding="utf-8"))
            result = approve_sample(
                conn,
                stage_id=approval["stage_id"],
                expected_checksum=approval["checksum"],
                reviewer=approval["reviewer"],
                review_note=approval["review_note"],
                identity_assumption=approval["identity_assumption"],
                aliases=approval["aliases"],
            )
        else:
            report = review_sample(conn, args.stage_id)
            if report["status"] != "published":
                raise ValueError("sample must be approved before collection")
            result = collection_request(conn, report["preparation_id"])
    if args.command == "collect":
        from .worker import check_coverage, collect_group

        collected = collect_group(result)
        coverage = check_coverage(result)
        result = {"collection": collected, "coverage": coverage}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
