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
    parser.add_argument("--runner-mode", choices=RUNNER_MODES, default="non_executing_canary")
    parser.add_argument("--handler-factory")
    parser.add_argument("--require-scoreable-live", action="store_true")
    parser.add_argument(
        "--scoreable-readiness-mode",
        choices=("pilot_scoreable_readiness", "true_scoreable_live_readiness"),
    )
    parser.add_argument("--qdt-adapter-mode")
    parser.add_argument("--researcher-runtime-mode")
    parser.add_argument("--research-input-mode")
    parser.add_argument("--allow-canary-handler", action="store_true")
    parser.add_argument("--allow-calibration-debt-scoreable-canary", action="store_true")
    parser.add_argument("--requested-max-cases", type=int)
    parser.add_argument("--max-calibration-debt-canary-cases", type=int, default=2)
    parser.add_argument("--prediction-source", default="ads_pipeline")
    parser.add_argument("--prediction-label", default="v2_scae")
    parser.add_argument("--evaluation-cluster-id", default="calibration-debt-clearance")
    parser.add_argument("--first100-trace-complete", action="store_true")
    parser.add_argument("--trace-manifest-count", type=int)
    parser.add_argument("--tail-slice-diagnostics-json", type=Path)
    parser.add_argument("--regime-diagnostics-json", type=Path)
    parser.add_argument("--protected-component-diagnostics-json", type=Path)
    parser.add_argument("--pointer-stability-evidence-json", type=Path)
    parser.add_argument("--amrg-refresh-status")
    parser.add_argument("--amrg-model-assist-status")
    parser.add_argument("--amrg-assist-requested-by-policy", action="store_true")
    parser.add_argument("--scae-evidence-delta-ref", action="append", default=[])
    parser.add_argument("--strict-non-scoreable-canary-report-json", type=Path)
    parser.add_argument("--require-fresh-storage-maintenance-plan", action="store_true")
    parser.add_argument("--operator-review", action="store_true", help="Include Phase 12 operator review for latest or selected run.")
    parser.add_argument("--operator-review-pipeline-run-id")
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
        scoreable_readiness_mode=args.scoreable_readiness_mode,
        qdt_adapter_mode=args.qdt_adapter_mode,
        researcher_runtime_mode=args.researcher_runtime_mode,
        research_input_mode=args.research_input_mode,
        allow_canary_handler=args.allow_canary_handler,
        allow_calibration_debt_scoreable_canary=args.allow_calibration_debt_scoreable_canary,
        requested_max_cases=args.requested_max_cases,
        max_calibration_debt_canary_cases=args.max_calibration_debt_canary_cases,
        prediction_source=args.prediction_source,
        prediction_label=args.prediction_label,
        evaluation_cluster_id=args.evaluation_cluster_id,
        first100_trace_complete=args.first100_trace_complete,
        trace_manifest_count=args.trace_manifest_count,
        tail_slice_diagnostics=load_json(args.tail_slice_diagnostics_json, None),
        regime_diagnostics=load_json(args.regime_diagnostics_json, None),
        protected_component_diagnostics=load_json(args.protected_component_diagnostics_json, None),
        pointer_stability_evidence=load_json(args.pointer_stability_evidence_json, None),
        amrg_refresh_status=args.amrg_refresh_status,
        amrg_model_assist_status=args.amrg_model_assist_status,
        amrg_assist_requested_by_policy=args.amrg_assist_requested_by_policy or None,
        scae_evidence_delta_refs=tuple(args.scae_evidence_delta_ref),
        strict_non_scoreable_canary_report=load_json(args.strict_non_scoreable_canary_report_json, None),
        require_fresh_storage_maintenance_plan=args.require_fresh_storage_maintenance_plan,
        include_operator_review=args.operator_review,
        operator_review_pipeline_run_id=args.operator_review_pipeline_run_id,
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
