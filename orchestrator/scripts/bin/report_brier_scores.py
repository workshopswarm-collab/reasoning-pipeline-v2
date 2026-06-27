#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import (
    CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    DEFAULT_DB_PATH,
    brier_score_report,
    write_evaluator_scorecards,
)
from predquant.ads_operator_review import build_ads_operator_review_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report pipeline Brier scores against prediction-time market baselines"
    )
    parser.add_argument("--source", help="Optional prediction_source filter")
    parser.add_argument("--label", help="Optional prediction_label filter")
    parser.add_argument(
        "--evaluation-cluster-id",
        default=CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
        help="Evaluator scorecard cluster to summarize.",
    )
    parser.add_argument(
        "--write-scorecards",
        action="store_true",
        help="Write idempotent evaluator scorecards for scored predictions before reporting.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    parser.add_argument("--operator-review", action="store_true", help="Include Phase 12 operator review.")
    parser.add_argument("--pipeline-run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        scorecards = None
        if args.write_scorecards:
            scorecards = write_evaluator_scorecards(
                db_path=Path(args.db_path),
                prediction_source=args.source,
                prediction_label=args.label,
                evaluation_cluster_id=args.evaluation_cluster_id,
            )
        result = brier_score_report(
            db_path=Path(args.db_path),
            prediction_source=args.source,
            prediction_label=args.label,
            evaluation_cluster_id=args.evaluation_cluster_id,
        )
        if scorecards is not None:
            result["scorecard_write"] = scorecards
        if args.operator_review:
            result["operator_review_report"] = build_ads_operator_review_report(
                Path(args.db_path),
                pipeline_run_id=args.pipeline_run_id,
                prediction_source=args.source,
                prediction_label=args.label,
                evaluation_cluster_id=args.evaluation_cluster_id,
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
