"""Probe, stage, inspect, and explicitly publish an FMP constituent snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx
import psycopg

from .fmp import FmpRequestError, FmpTransportError, fetch_constituents
from .fmp_stage import SOURCE, publish_reviewed_stage, review_stage, stage_constituents


def approval_draft(report: dict) -> dict:
    """Leave unresolved share lines and reviewer attestation for manual review."""
    if report["status"] != "held":
        raise ValueError("approval draft requires a held catalog stage")
    if report["validation_issues"] or report["row_count"] < report["minimum_count"]:
        raise ValueError("catalog stage failed validation and cannot be published")
    return {
        "stage_id": report["stage_id"],
        "checksum": report["checksum"],
        "reviewer": "",
        "review_note": "",
        "decisions": {symbol: "" for symbol in report["unresolved_symbols"]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "probe", help="one bounded read-only request; report metadata only"
    )
    subcommands.add_parser(
        "stage", help="fetch and hold a normalized candidate for review"
    )
    review = subcommands.add_parser(
        "review", help="show staged changes and identity gaps"
    )
    review.add_argument("stage_id")
    draft = subcommands.add_parser(
        "draft", help="write an unsigned approval draft for a held stage"
    )
    draft.add_argument("stage_id")
    draft.add_argument("--output", type=Path, required=True)
    publish = subcommands.add_parser(
        "publish", help="publish with an explicit reviewed approval file"
    )
    publish.add_argument("approval_file", type=Path)
    args = parser.parse_args()

    if args.command in ("probe", "stage"):
        key = os.environ.get("FMP_API_KEY")
        if not key:
            parser.error("FMP_API_KEY is required for an authenticated probe or stage")
        try:
            with httpx.Client() as client:
                fetched = fetch_constituents(client, key)
        except (FmpRequestError, FmpTransportError) as error:
            parser.error(str(error))
        result = {
            "endpoint": "stable/sp500-constituent",
            "fetched_at": fetched.fetched_at.isoformat(),
            "row_count": len(fetched.rows),
            "byte_count": fetched.byte_count,
            "checksum": fetched.checksum,
            "rate_headers": fetched.rate_headers,
            "provider_publication_time": None,
        }
        if args.command == "probe":
            print(json.dumps(result, indent=2))
            return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required for staging, review, or publication")
    with psycopg.connect(database_url) as conn:
        if args.command == "stage":
            result.update(stage_constituents(conn, fetched))
        elif args.command in ("review", "draft"):
            result = review_stage(conn, args.stage_id)
            if result["source"] != SOURCE:
                raise ValueError("stage is not an FMP catalog")
            if args.command == "draft":
                draft = approval_draft(result)
                args.output.write_text(
                    json.dumps(draft, indent=2) + "\n", encoding="utf-8"
                )
                result = {
                    "draft_written": str(args.output),
                    "unresolved_symbol_count": len(draft["decisions"]),
                }
        else:
            approval = json.loads(args.approval_file.read_text(encoding="utf-8"))
            report = review_stage(conn, approval["stage_id"])
            if report["source"] != SOURCE:
                raise ValueError("stage is not an FMP catalog")
            snapshot_id = publish_reviewed_stage(
                conn,
                stage_id=approval["stage_id"],
                expected_checksum=approval["checksum"],
                reviewer=approval["reviewer"],
                review_note=approval["review_note"],
                decisions=approval["decisions"],
            )
            result = {"status": "published", "snapshot_id": snapshot_id}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
