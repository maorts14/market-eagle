"""Stage a dated public constituent CSV for explicit private-use review."""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path

import psycopg

from .fmp import FmpFetch, checksum_rows, normalize_constituents
from .fmp_catalog import approval_draft
from .fmp_stage import (
    PROVISIONAL_SOURCE,
    publish_reviewed_stage,
    review_stage,
    stage_constituents,
)

MAX_CSV_BYTES = 2_000_000
REQUIRED_COLUMNS = {
    "Symbol",
    "Security",
    "GICS Sector",
    "GICS Sub-Industry",
    "Date added",
    "CIK",
}


def read_candidate(path: Path, observed_on: date) -> FmpFetch:
    """Normalize a pinned local CSV without inferring identities or official status."""
    raw = path.read_bytes()
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("public catalog CSV exceeds 2 MB")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames or not REQUIRED_COLUMNS <= set(reader.fieldnames):
        raise ValueError("public catalog CSV has missing required columns")
    payload = []
    for item in reader:
        payload.append(
            {
                "symbol": item["Symbol"].strip(),
                "name": item["Security"].strip(),
                "sector": item["GICS Sector"].strip(),
                "subSector": item["GICS Sub-Industry"].strip() or None,
                "cik": item["CIK"].strip() or None,
                "dateFirstAdded": item["Date added"].strip() or None,
            }
        )
    rows = normalize_constituents(payload)
    if len(rows) < 450:
        raise ValueError("public catalog requires at least 450 share lines")
    captured_at = datetime.combine(observed_on, time.min, timezone.utc)
    return FmpFetch(rows, captured_at, len(raw), checksum_rows(rows), {})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--file", type=Path, required=True)
        command.add_argument("--observed-on", type=date.fromisoformat, required=True)
        command.add_argument("--source-url", required=True)
    for name in ("review", "draft"):
        command = commands.add_parser(name)
        command.add_argument("stage_id")
        if name == "draft":
            command.add_argument("--output", type=Path, required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("approval_file", type=Path)
    args = parser.parse_args()

    if args.command in ("probe", "stage"):
        fetched = read_candidate(args.file, args.observed_on)
        result = {
            "source": PROVISIONAL_SOURCE,
            "source_url": args.source_url,
            "observed_on": args.observed_on.isoformat(),
            "row_count": len(fetched.rows),
            "byte_count": fetched.byte_count,
            "checksum": fetched.checksum,
        }
        if args.command == "probe":
            print(json.dumps(result, indent=2))
            return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required for staging, review, or publication")
    with psycopg.connect(database_url) as conn:
        if args.command == "stage":
            result.update(
                stage_constituents(
                    conn, fetched, source=PROVISIONAL_SOURCE, endpoint=args.source_url
                )
            )
        elif args.command in ("review", "draft"):
            result = review_stage(conn, args.stage_id)
            if result["source"] != PROVISIONAL_SOURCE:
                raise ValueError("stage is not a provisional public catalog")
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
            if report["source"] != PROVISIONAL_SOURCE:
                raise ValueError("stage is not a provisional public catalog")
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
