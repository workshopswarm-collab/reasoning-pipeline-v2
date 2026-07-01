#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_source_retrieval_phase10_closure import (
    build_source_retrieval_phase10_closure_report,
)


def _cleanup_proof(**overrides) -> dict:
    proof = {
        "schema_version": "ads-source-retrieval-phase10-cleanup-proof/v1",
        "temp_dirs_removed": True,
        "generated_artifacts_staged": False,
        "one_off_scripts_deleted": True,
        "live_db_mutation_detected": False,
        "active_runs_left": 0,
        "active_leases_left": 0,
    }
    proof.update(overrides)
    return proof


def _report(
    *,
    tag: str,
    pipeline_run_id: str,
    classification: str,
    expected_classification: str | None = None,
    clone_only: bool = True,
    qdt_live_accepted_count: int = 1,
    direct_adapter_success_count: int = 1,
    native_success_count: int = 1,
    native_failure_count: int = 0,
    certified_leaf_count: int = 2,
    classification_slice_count: int = 2,
    scae_valid_count: int = 1,
    scae_ledger_count: int = 1,
    market_predictions_delta: int = 1,
) -> dict:
    live_db_mutation = "clone_only" if clone_only else "unknown_or_live"
    expected_classification = expected_classification or classification
    return {
        "selector": tag,
        "representative_tags": [tag],
        "expected_classification": expected_classification,
        "expected_market_predictions_delta": 1 if expected_classification == "scoreable_success" else 0,
        "real_runtime_report": {
            "pipeline_run_id": pipeline_run_id,
            "live_db_mutation": live_db_mutation,
            "clone_only": clone_only,
            "active_work": {"active_runs": 0, "active_leases": 0},
            "handoff_report": {"ok": True},
            "model_runtime_evidence": {
                "qdt_live_output_accepted_count": qdt_live_accepted_count,
                "qdt_end_to_end_quality_ok": qdt_live_accepted_count > 0,
            },
            "source_retrieval_pipeline_health_taxonomy": {
                "qdt_live_output_accepted_count": qdt_live_accepted_count,
            },
            "retrieval_runtime_evidence": {
                "direct_url_capture_executed_count": direct_adapter_success_count,
                "native_candidate_url_count": native_success_count,
                "native_research_model_executed_count": native_success_count + native_failure_count,
                "native_research_statuses": ["candidate_urls_present" if native_success_count else "executed_no_candidates"],
                "retrieval_packets": [
                    {
                        "direct_url_candidate_count": direct_adapter_success_count,
                        "direct_url_capture_executed": direct_adapter_success_count > 0,
                        "native_candidate_url_count": native_success_count,
                        "native_research_model_executed": (native_success_count + native_failure_count) > 0,
                        "native_research_status": "candidate_urls_present"
                        if native_success_count
                        else "executed_no_candidates",
                        "leaf_retrieval_statuses": [
                            {"classification_dispatch_allowed": True}
                            for _ in range(certified_leaf_count)
                        ],
                    }
                ],
            },
            "researcher_runtime_evidence": {
                "model_executed_count": 1 if classification_slice_count else 0,
                "classification_slice_count": classification_slice_count,
            },
            "scae_runtime_evidence": {
                "ledger_count": scae_ledger_count,
                "valid_forecast_count": scae_valid_count,
                "delta_ref_count": scae_valid_count,
            },
            "prediction_delta_evidence": {
                "forecast_decision_records_delta": 1,
                "market_predictions_delta": market_predictions_delta,
            },
            "pipeline_health_summary": {
                "certified_retrieval_leaf_count": certified_leaf_count,
                "classification_slice_count": classification_slice_count,
                "scae_delta_ref_count": scae_valid_count,
                "protected_write_deltas": {
                    "forecast_decision_records_delta": 1,
                    "market_predictions_delta": market_predictions_delta,
                },
            },
            "phase9_representative_case": {
                "classification": classification,
                "reason_codes": ["unit_test"],
                "clone_only": clone_only,
                "live_db_mutation": live_db_mutation,
            },
        },
    }


def _passing_cases() -> list[dict]:
    return [
        _report(
            tag="boi_central_bank_rate_decrease",
            pipeline_run_id="run:boi",
            classification="scoreable_success",
        ),
        _report(
            tag="central_bank_macro_policy",
            pipeline_run_id="run:central-bank",
            classification="scoreable_success",
            native_success_count=0,
            native_failure_count=1,
        ),
        _report(
            tag="non_central_bank_source_adapter",
            pipeline_run_id="run:non-central-bank",
            classification="scoreable_success",
        ),
        _report(
            tag="valid_non_scoreable_insufficiency",
            pipeline_run_id="run:valid-insufficiency",
            classification="structured_non_scoreable_insufficiency",
            native_success_count=0,
            certified_leaf_count=0,
            classification_slice_count=0,
            scae_valid_count=0,
            scae_ledger_count=1,
            market_predictions_delta=0,
        ),
    ]


class AdsSourceRetrievalPhase10ClosureTest(unittest.TestCase):
    def test_closure_report_passes_representative_clone_batch(self):
        report = build_source_retrieval_phase10_closure_report(
            _passing_cases(),
            cleanup_proof=_cleanup_proof(),
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["case_count"], 4)
        self.assertEqual(report["missing_representative_tags"], [])
        self.assertEqual(report["classification_counts"]["scoreable_success"], 3)
        self.assertEqual(report["classification_counts"]["structured_non_scoreable_insufficiency"], 1)
        self.assertEqual(report["aggregate_counters"]["qdt_live_accepted_count"], 4)
        self.assertEqual(report["aggregate_counters"]["native_provider_success_count"], 2)
        self.assertEqual(report["aggregate_counters"]["native_provider_failure_count"], 1)
        self.assertEqual(report["aggregate_counters"]["native_provider_safe_failure_count"], 1)
        self.assertEqual(report["aggregate_counters"]["official_direct_adapter_success_count"], 4)
        self.assertEqual(report["aggregate_counters"]["certified_retrieval_leaf_count"], 6)
        self.assertEqual(report["aggregate_counters"]["researcher_classification_slice_count"], 6)
        self.assertEqual(report["aggregate_counters"]["scae_valid_forecast_count"], 3)
        self.assertEqual(report["aggregate_counters"]["scae_invalid_forecast_count"], 1)
        self.assertEqual(report["protected_write_delta_summary"]["market_predictions_delta"], 3)
        self.assertTrue(report["cleanup_proof"]["ok"])

    def test_closure_report_blocks_missing_required_tag(self):
        cases = _passing_cases()
        cases.pop(2)

        report = build_source_retrieval_phase10_closure_report(cases, cleanup_proof=_cleanup_proof())

        self.assertFalse(report["ok"])
        self.assertIn("representative_tags_missing", report["issues"])
        self.assertIn("non_central_bank_source_adapter", report["missing_representative_tags"])

    def test_closure_report_blocks_live_mutation_and_protected_write_mismatch(self):
        cases = _passing_cases()
        cases[3] = _report(
            tag="valid_non_scoreable_insufficiency",
            pipeline_run_id="run:bad-insufficiency",
            classification="structured_non_scoreable_insufficiency",
            clone_only=False,
            certified_leaf_count=0,
            classification_slice_count=0,
            scae_valid_count=0,
            scae_ledger_count=1,
            market_predictions_delta=1,
        )

        report = build_source_retrieval_phase10_closure_report(cases, cleanup_proof=_cleanup_proof())

        self.assertFalse(report["ok"])
        self.assertIn("non_clone_only_case", report["issues"])
        self.assertIn("protected_market_prediction_delta_mismatch", report["issues"])
        bad_case = report["case_summaries"][3]
        self.assertIn("case_not_explicit_clone_only", bad_case["issues"])
        self.assertIn("blocked_case_market_prediction_delta_nonzero", bad_case["issues"])

    def test_closure_report_blocks_cleanup_failures(self):
        report = build_source_retrieval_phase10_closure_report(
            _passing_cases(),
            cleanup_proof=_cleanup_proof(temp_dirs_removed=False, generated_artifacts_staged=True),
        )

        self.assertFalse(report["ok"])
        self.assertIn("cleanup:temp_dirs_not_removed", report["issues"])
        self.assertIn("cleanup:generated_artifacts_staged", report["issues"])

    def test_cli_reports_phase10_closure_status(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "report_ads_source_retrieval_phase10_closure.py"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            cleanup_path = root / "cleanup.json"
            cleanup_path.write_text(json.dumps(_cleanup_proof(), sort_keys=True), encoding="utf-8")
            paths = []
            for index, case in enumerate(_passing_cases(), start=1):
                path = root / f"case-{index}.json"
                path.write_text(json.dumps(case, sort_keys=True), encoding="utf-8")
                paths.append(path)
            command = [sys.executable, str(script), "--cleanup-proof-json", str(cleanup_path)]
            for path in paths:
                command.extend(["--case-report", str(path)])
            completed = subprocess.run(command, check=True, capture_output=True, text=True)

        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["schema_version"], "ads-source-retrieval-phase10-closure/v1")


if __name__ == "__main__":
    unittest.main()
