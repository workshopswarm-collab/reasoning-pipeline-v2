#!/usr/bin/env python3
"""Print an operator report for an ADS pipeline handoff chain."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff_report import build_handoff_report  # noqa: E402
from predquant.ads_operator_review import build_ads_operator_review_report  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--pipeline-run-id", help="Pipeline run to inspect. Defaults to latest run.")
    parser.add_argument("--operator-review", action="store_true", help="Include the Phase 12 operator review report.")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_handoff_report(Path(args.db_path), pipeline_run_id=args.pipeline_run_id)
    if args.operator_review:
        report["operator_review_report"] = build_ads_operator_review_report(
            Path(args.db_path),
            pipeline_run_id=args.pipeline_run_id,
        )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
