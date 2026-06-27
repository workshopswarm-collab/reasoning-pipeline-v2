#!/usr/bin/env python3
"""Print the ADS operator review report for a pipeline run."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    parser.add_argument("--max-market-snapshot-age-seconds", type=float, default=3600.0)
    parser.add_argument("--max-resolution-sync-age-seconds", type=float, default=5400.0)
    parser.add_argument("--storage-retention-days", type=int, default=90)
    parser.add_argument("--prediction-source", default="ads_pipeline")
    parser.add_argument("--prediction-label", default="v2_scae")
    parser.add_argument("--evaluation-cluster-id", default="calibration-debt-clearance")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_ads_operator_review_report(
        Path(args.db_path),
        pipeline_run_id=args.pipeline_run_id,
        max_market_snapshot_age_seconds=args.max_market_snapshot_age_seconds,
        max_resolution_sync_age_seconds=args.max_resolution_sync_age_seconds,
        storage_retention_days=args.storage_retention_days,
        prediction_source=args.prediction_source,
        prediction_label=args.prediction_label,
        evaluation_cluster_id=args.evaluation_cluster_id,
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
