#!/usr/bin/env python3
"""Run non-authoritative ADS scoring and optional CAL-001 debt-gate reporting."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_operator_review import build_ads_operator_review_report  # noqa: E402
from predquant.calibration_debt import build_calibration_debt_clearance_report  # noqa: E402
from predquant.sqlite_store import (  # noqa: E402
    DEFAULT_DB_PATH,
    brier_score_report,
    write_evaluator_scorecards,
)


def load_json(path: Path | None, default):
    if path is None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--prediction-source")
    parser.add_argument("--prediction-label")
    parser.add_argument("--evaluation-cluster-id", default="calibration-debt-clearance")
    parser.add_argument("--write-scorecards", action="store_true")
    parser.add_argument("--calibration-debt-report", action="store_true")
    parser.add_argument("--first100-trace-complete", action="store_true")
    parser.add_argument("--trace-manifest-count", type=int)
    parser.add_argument("--tail-slice-diagnostics-json", type=Path)
    parser.add_argument("--regime-diagnostics-json", type=Path)
    parser.add_argument("--protected-component-diagnostics-json", type=Path)
    parser.add_argument("--pointer-stability-evidence-json", type=Path)
    parser.add_argument("--operator-review", action="store_true", help="Include Phase 12 operator review.")
    parser.add_argument("--pipeline-run-id")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    result = {
        "schema_version": "ads-scoring-calibration-loop/v1",
        "production_forecast_write_authority": False,
        "calibration_policy_promotion_authority": False,
    }
    if args.write_scorecards:
        result["scorecard_write"] = write_evaluator_scorecards(
            db_path,
            prediction_source=args.prediction_source,
            prediction_label=args.prediction_label,
            evaluation_cluster_id=args.evaluation_cluster_id,
            metadata={"source": "run_ads_scoring_calibration_loop"},
        )
    result["brier_score_report"] = brier_score_report(
        db_path,
        prediction_source=args.prediction_source,
        prediction_label=args.prediction_label,
        evaluation_cluster_id=args.evaluation_cluster_id,
    )
    if args.calibration_debt_report:
        result["calibration_debt_report"] = build_calibration_debt_clearance_report(
            db_path=db_path,
            first100_trace_complete=args.first100_trace_complete,
            trace_manifest_count=args.trace_manifest_count,
            tail_slice_diagnostics=load_json(args.tail_slice_diagnostics_json, []),
            regime_diagnostics=load_json(args.regime_diagnostics_json, []),
            protected_component_diagnostics=load_json(args.protected_component_diagnostics_json, []),
            pointer_stability_evidence=load_json(args.pointer_stability_evidence_json, {}),
            prediction_source=args.prediction_source,
            prediction_label=args.prediction_label,
            evaluation_cluster_id=args.evaluation_cluster_id,
        )
    if args.operator_review:
        result["operator_review_report"] = build_ads_operator_review_report(
            db_path,
            pipeline_run_id=args.pipeline_run_id,
            prediction_source=args.prediction_source,
            prediction_label=args.prediction_label,
            evaluation_cluster_id=args.evaluation_cluster_id,
        )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
