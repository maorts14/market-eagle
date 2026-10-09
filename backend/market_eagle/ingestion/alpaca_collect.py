"""Prepare a reviewed Alpaca alias/calendar plan for a published FMP catalog."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import psycopg

from .alpaca_preparation import (
    approve_preparation,
    collection_request,
    review_preparation,
    stage_preparation,
)
from .alpaca_reference import fetch_assets, fetch_calendar


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--start", type=date.fromisoformat, required=True)
        command.add_argument("--end", type=date.fromisoformat, required=True)
        if name == "stage":
            command.add_argument("--snapshot-id", required=True)
    for name in ("review", "request", "draft"):
        command = commands.add_parser(name)
        command.add_argument("preparation_id")
        if name == "draft":
            command.add_argument("--output", type=Path, required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("approval_file", type=Path)
    args = parser.parse_args()

    if args.command in ("probe", "stage"):
        key_id = os.environ.get("ALPACA_API_KEY_ID")
        secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not secret:
            parser.error("ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are required")
        with httpx.Client() as client:
            assets = fetch_assets(client, key_id, secret)
            sessions = fetch_calendar(client, key_id, secret, args.start, args.end)
        observed_at = datetime.now(timezone.utc)
        result = {
            "asset_count": len(assets),
            "calendar_session_count": len(sessions),
            "fetched_at": observed_at.isoformat(),
            "requested_start": args.start.isoformat(),
            "requested_end": args.end.isoformat(),
        }
        if args.command == "probe":
            print(json.dumps(result, indent=2))
            return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    with psycopg.connect(database_url) as conn:
        if args.command == "stage":
            result.update(
                stage_preparation(
                    conn,
                    snapshot_id=args.snapshot_id,
                    requested_start=args.start,
                    requested_end=args.end,
                    assets=assets,
                    sessions=sessions,
                    fetched_at=observed_at,
                )
            )
        elif args.command == "review":
            result = review_preparation(conn, args.preparation_id)
        elif args.command == "request":
            result = collection_request(conn, args.preparation_id)
        elif args.command == "draft":
            report = review_preparation(conn, args.preparation_id)
            aliases = []
            for item in report["candidates"]:
                candidate = (
                    item["alpaca_candidates"][0]
                    if len(item["alpaca_candidates"]) == 1
                    else {}
                )
                aliases.append(
                    {
                        "stock_id": item["stock_id"],
                        "asset_id": candidate.get("asset_id", ""),
                        "symbol": candidate.get("symbol", ""),
                        "exchange": candidate.get("exchange", ""),
                        "verified_from": "",
                        "verified_to": None,
                        "evidence": "",
                        "symbol_difference_reason": "",
                    }
                )
            result = {
                "preparation_id": args.preparation_id,
                "checksum": report["checksum"],
                "reviewer": "",
                "review_note": "",
                "aliases": aliases,
            }
            args.output.write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {"draft_written": str(args.output), "alias_count": len(aliases)}
                )
            )
            return
        else:
            approval = json.loads(args.approval_file.read_text(encoding="utf-8"))
            result = approve_preparation(
                conn,
                preparation_id=approval["preparation_id"],
                expected_checksum=approval["checksum"],
                reviewer=approval["reviewer"],
                review_note=approval["review_note"],
                aliases=approval["aliases"],
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
