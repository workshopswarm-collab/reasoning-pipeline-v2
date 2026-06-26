#!/usr/bin/env python3
"""Report ADS live-readiness gate status."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_live_readiness import build_live_readiness_report  # noqa: E402
from predquant.ads_pipeline_runner import RUNNER_MODES  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--runner-mode", choices=RUNNER_MODES, default="non_executing_canary")
    parser.add_argument("--handler-factory")
    parser.add_argument("--require-scoreable-live", action="store_true")
    parser.add_argument("--allow-canary-handler", action="store_true")
    parser.add_argument("--prediction-source", default="ads_pipeline")
    parser.add_argument("--prediction-label", default="v2_scae")
    parser.add_argument("--evaluation-cluster-id", default="calibration-debt-clearance")
    parser.add_argument("--first100-trace-complete", action="store_true")
    parser.add_argument("--trace-manifest-count", type=int)
    parser.add_argument("--max-market-snapshot-age-seconds", type=float, default=3600.0)
    parser.add_argument("--max-brier-age-seconds", type=float, default=172800.0)
    parser.add_argument("--max-resolution-sync-age-seconds", type=float, default=5400.0)
    parser.add_argument("--storage-retention-days", type=int, default=90)
    parser.add_argument("--max-storage-retention-candidate-rows", type=int)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_live_readiness_report(
        Path(args.db_path),
        handler_factory=args.handler_factory,
        runner_mode=args.runner_mode,
        require_scoreable_live=args.require_scoreable_live,
        allow_canary_handler=args.allow_canary_handler,
        prediction_source=args.prediction_source,
        prediction_label=args.prediction_label,
        evaluation_cluster_id=args.evaluation_cluster_id,
        first100_trace_complete=args.first100_trace_complete,
        trace_manifest_count=args.trace_manifest_count,
        max_market_snapshot_age_seconds=args.max_market_snapshot_age_seconds,
        max_brier_age_seconds=args.max_brier_age_seconds,
        max_resolution_sync_age_seconds=args.max_resolution_sync_age_seconds,
        storage_retention_days=args.storage_retention_days,
        max_storage_retention_candidate_rows=args.max_storage_retention_candidate_rows,
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
