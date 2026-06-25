#!/usr/bin/env python3
"""Report SCORE-001 SCAE Brier and market-baseline scorecards."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_SCRIPTS = REPO_ROOT / "orchestrator" / "scripts"
if str(ORCHESTRATOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_SCRIPTS))

from predquant.sqlite_store import (  # noqa: E402
    CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    DEFAULT_DB_PATH,
    brier_score_report,
    write_evaluator_scorecards,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report SCAE SCORE-001 Brier scores against prediction-time market baselines."
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    parser.add_argument(
        "--source",
        default="ads_pipeline",
        help="Prediction source to report; defaults to PERSIST-002 SCAE bridge rows.",
    )
    parser.add_argument(
        "--label",
        default="v2_scae",
        help="Prediction label to report; defaults to PERSIST-002 SCAE bridge rows.",
    )
    parser.add_argument(
        "--evaluation-cluster-id",
        default=CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
        help="Evaluator scorecard cluster to summarize.",
    )
    parser.add_argument(
        "--write-scorecards",
        action="store_true",
        help="Write idempotent evaluator scorecards for already-scored SCAE predictions.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
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
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
