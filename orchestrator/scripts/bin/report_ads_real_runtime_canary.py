#!/usr/bin/env python3
"""Report ADS real-runtime canary criteria status."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_real_runtime_canary import build_real_runtime_canary_report  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


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
    parser.add_argument("--pipeline-run-id")
    parser.add_argument("--expected-cases", type=int)
    parser.add_argument("--expected-forecast-decision-records", type=int)
    parser.add_argument("--expected-market-predictions", type=int)
    parser.add_argument("--require-scoreable-prediction", action="store_true")
    parser.add_argument("--skip-qdt-model-executed-check", action="store_true")
    parser.add_argument("--require-researcher-model-executed", action="store_true")
    parser.add_argument("--allow-stage-failure-class", action="append", default=[])
    parser.add_argument("--allow-pipeline-enabled", action="store_true")
    parser.add_argument("--prediction-source", default="ads_pipeline")
    parser.add_argument("--prediction-label", default="v2_scae")
    parser.add_argument("--evaluation-cluster-id", default="calibration-debt-clearance")
    parser.add_argument("--first100-trace-complete", action="store_true")
    parser.add_argument("--trace-manifest-count", type=int)
    parser.add_argument("--tail-slice-diagnostics-json", type=Path)
    parser.add_argument("--regime-diagnostics-json", type=Path)
    parser.add_argument("--protected-component-diagnostics-json", type=Path)
    parser.add_argument("--pointer-stability-evidence-json", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_real_runtime_canary_report(
        Path(args.db_path),
        pipeline_run_id=args.pipeline_run_id,
        expected_cases=args.expected_cases,
        expected_forecast_decision_records=args.expected_forecast_decision_records,
        expected_market_predictions=args.expected_market_predictions,
        require_scoreable_prediction=args.require_scoreable_prediction,
        require_qdt_model_executed=not args.skip_qdt_model_executed_check,
        require_researcher_model_executed=args.require_researcher_model_executed,
        allowed_stage_failure_classes=tuple(args.allow_stage_failure_class),
        enforce_pipeline_disabled=not args.allow_pipeline_enabled,
        prediction_source=args.prediction_source,
        prediction_label=args.prediction_label,
        evaluation_cluster_id=args.evaluation_cluster_id,
        first100_trace_complete=args.first100_trace_complete,
        trace_manifest_count=args.trace_manifest_count,
        tail_slice_diagnostics=load_json(args.tail_slice_diagnostics_json, None),
        regime_diagnostics=load_json(args.regime_diagnostics_json, None),
        protected_component_diagnostics=load_json(args.protected_component_diagnostics_json, None),
        pointer_stability_evidence=load_json(args.pointer_stability_evidence_json, None),
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
