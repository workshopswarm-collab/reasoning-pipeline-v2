#!/usr/bin/env python3
"""Dry-run or apply conservative ADS SQLite storage maintenance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_storage_maintenance import apply_storage_maintenance, build_storage_maintenance_plan  # noqa: E402
from predquant.ads_operator_review import build_ads_operator_review_report  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--retention-days", type=int, default=90)
    parser.add_argument("--vacuum", action="store_true", help="Run VACUUM after pruning.")
    parser.add_argument("--apply", action="store_true", help="Apply deletes/checkpoint instead of dry-run planning.")
    parser.add_argument("--operator-review", action="store_true", help="Include Phase 12 operator review.")
    parser.add_argument("--pipeline-run-id")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.retention_days < 1:
        print(json.dumps({"ok": False, "error": "--retention-days must be positive"}), file=sys.stderr)
        return 2
    if args.apply:
        result = apply_storage_maintenance(
            Path(args.db_path),
            retention_days=args.retention_days,
            vacuum=args.vacuum,
        )
    else:
        result = build_storage_maintenance_plan(Path(args.db_path), retention_days=args.retention_days)
        result["dry_run"] = True
    if args.operator_review:
        result["operator_review_report"] = build_ads_operator_review_report(
            Path(args.db_path),
            pipeline_run_id=args.pipeline_run_id,
            storage_retention_days=args.retention_days,
        )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
