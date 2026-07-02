#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_live_market_e2e_phase8_closure import (
    build_live_market_e2e_phase8_closure_report,
)


def _cleanup_proof(**overrides) -> dict:
    proof = {
        "schema_version": "ads-live-market-e2e-phase8-cleanup-proof/v1",
        "temp_dirs_removed": True,
        "generated_artifacts_staged": False,
        "one_off_scripts_deleted": True,
        "live_db_mutation_detected": False,
        "live_db_protected_count_deltas": {
            "ads_case_leases": 0,
            "ads_pipeline_runs": 0,
            "forecast_decision_records": 0,
            "market_predictions": 0,
            "scae_ledger_outputs": 0,
        },
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
    qdt_accepted_count: int = 1,
    qdt_fixture_or_deterministic_count: int = 0,
    retrieval_terminal: bool = True,
    retrieval_timeout_count: int = 0,
    retrieval_certified: bool = True,
    retrieval_insufficient: bool = False,
    browser_timeout: bool = False,
    native_timeout: bool = False,
    researcher_model_count: int = 1,
    scae_valid_count: int = 1,
    scae_ledger_count: int = 1,
    market_predictions_delta: int = 1,
) -> dict:
    live_db_mutation = "clone_only" if clone_only else "unknown_or_live"
    expected_classification = expected_classification or classification
    blocked = classification in {
        "structured_non_scoreable_insufficiency",
        "structural_unanswerability",
    }
    qdt_quality_count = max(qdt_accepted_count, qdt_fixture_or_deterministic_count)
    terminal_acceptance = retrieval_terminal and retrieval_certified and not retrieval_insufficient
    return {
        "selector": tag,
        "representative_tags": [tag],
        "expected_classification": expected_classification,
        "expected_market_predictions_delta": 1 if expected_classification == "scoreable_success" else 0,
        "real_runtime_report": {
            "ok": True,
            "issues": [],
            "pipeline_run_id": pipeline_run_id,
            "live_db_mutation": live_db_mutation,
            "clone_only": clone_only,
            "active_work": {"active_runs": 0, "active_leases": 0},
            "handoff_report": {"ok": True},
            "model_runtime_evidence": {
                "qdt_live_output_accepted_count": qdt_accepted_count,
                "qdt_fixture_or_deterministic_count": qdt_fixture_or_deterministic_count,
                "qdt_end_to_end_quality_count": qdt_quality_count,
                "qdt_end_to_end_quality_ok": qdt_quality_count > 0,
            },
            "source_retrieval_pipeline_health_taxonomy": {
                "qdt_live_output_accepted_count": qdt_accepted_count,
                "qdt_fixture_or_deterministic_count": qdt_fixture_or_deterministic_count,
            },
            "retrieval_runtime_evidence": {
                "retrieval_packet_count": 1,
                "live_acceptance_ok": terminal_acceptance,
                "bounded_timeout_block_ok": retrieval_timeout_count > 0 and blocked,
                "retrieval_stage_timeout_count": retrieval_timeout_count,
                "blocked_when_acceptance_unmet_count": 1 if retrieval_insufficient or retrieval_timeout_count else 0,
                "acceptance_unmet_not_blocked_count": 0,
                "retrieval_packets": [
                    {
                        "retrieval_stage_timeout": retrieval_timeout_count > 0,
                        "browser_search_status": "timeout" if browser_timeout else "executed",
                        "search_candidate_discovery_status": "timeout" if browser_timeout else "executed",
                        "native_research_status": "timeout" if native_timeout else "configured_not_needed",
                        "classification_dispatch_allowed": retrieval_certified,
                        "retrieval_terminal_acceptance_met": terminal_acceptance,
                        "blocked_when_acceptance_unmet": retrieval_insufficient or retrieval_timeout_count > 0,
                        "acceptance_unmet_not_blocked": False,
                        "structural_unanswerability_certified": classification == "structural_unanswerability",
                        "leaf_retrieval_statuses": [
                            {
                                "classification_dispatch_allowed": retrieval_certified,
                                "retrieval_terminal_acceptance_met": terminal_acceptance,
                            }
                        ]
                        if retrieval_certified
                        else [],
                    }
                ],
            },
            "researcher_runtime_evidence": {
                "model_executed_count": researcher_model_count,
                "runtime_bundle_count": researcher_model_count,
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
                "certified_retrieval_leaf_count": 1 if retrieval_certified else 0,
                "classification_slice_count": researcher_model_count,
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
            tag="boi_rate_decrease_market",
            pipeline_run_id="run:boi",
            classification="scoreable_success",
        ),
        _report(
            tag="central_bank_macro_market",
            pipeline_run_id="run:central-bank",
            classification="structured_non_scoreable_insufficiency",
            qdt_accepted_count=0,
            qdt_fixture_or_deterministic_count=1,
            retrieval_certified=False,
            retrieval_insufficient=True,
            researcher_model_count=0,
            scae_valid_count=0,
            scae_ledger_count=1,
            market_predictions_delta=0,
        ),
        _report(
            tag="non_central_bank_market",
            pipeline_run_id="run:non-central-bank",
            classification="structural_unanswerability",
            retrieval_certified=False,
            retrieval_insufficient=True,
            researcher_model_count=0,
            scae_valid_count=0,
            scae_ledger_count=1,
            market_predictions_delta=0,
        ),
        _report(
            tag="expected_insufficiency_case",
            pipeline_run_id="run:expected-insufficiency",
            classification="structured_non_scoreable_insufficiency",
            retrieval_timeout_count=1,
            retrieval_certified=False,
            browser_timeout=True,
            native_timeout=True,
            researcher_model_count=0,
            scae_valid_count=0,
            scae_ledger_count=1,
            market_predictions_delta=0,
        ),
    ]


class AdsLiveMarketE2EPhase8ClosureTest(unittest.TestCase):
    def test_closure_report_passes_representative_clone_batch(self):
        report = build_live_market_e2e_phase8_closure_report(
            _passing_cases(),
            cleanup_proof=_cleanup_proof(),
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["case_count"], 4)
        self.assertEqual(report["missing_representative_tags"], [])
        self.assertEqual(report["classification_counts"]["scoreable_success"], 1)
        self.assertEqual(report["classification_counts"]["structured_non_scoreable_insufficiency"], 2)
        self.assertEqual(report["aggregate_counters"]["qdt_accepted_count"], 4)
        self.assertEqual(report["aggregate_counters"]["qdt_live_output_accepted_count"], 3)
        self.assertEqual(report["aggregate_counters"]["qdt_fixture_or_deterministic_count"], 1)
        self.assertEqual(report["aggregate_counters"]["qdt_quality_ok_case_count"], 4)
        self.assertEqual(report["aggregate_counters"]["retrieval_terminal_case_count"], 4)
        self.assertEqual(report["aggregate_counters"]["retrieval_certified_case_count"], 1)
        self.assertEqual(report["aggregate_counters"]["retrieval_insufficient_case_count"], 2)
        self.assertEqual(report["aggregate_counters"]["retrieval_timeout_count"], 1)
        self.assertEqual(report["aggregate_counters"]["browser_provider_timeout_count"], 1)
        self.assertEqual(report["aggregate_counters"]["native_provider_timeout_count"], 1)
        self.assertEqual(report["aggregate_counters"]["researcher_model_executed_count"], 1)
        self.assertEqual(report["aggregate_counters"]["scae_valid_forecast_count"], 1)
        self.assertEqual(report["aggregate_counters"]["scae_invalid_forecast_count"], 3)
        self.assertEqual(report["protected_write_delta_summary"]["market_predictions_delta"], 1)
        self.assertTrue(report["cleanup_proof"]["ok"])

    def test_closure_report_blocks_missing_required_tag(self):
        cases = _passing_cases()
        cases.pop(2)

        report = build_live_market_e2e_phase8_closure_report(cases, cleanup_proof=_cleanup_proof())

        self.assertFalse(report["ok"])
        self.assertIn("representative_tags_missing", report["issues"])
        self.assertIn("non_central_bank_market", report["missing_representative_tags"])

    def test_closure_report_blocks_unclear_terminal_outcome(self):
        cases = _passing_cases()
        cases[0] = _report(
            tag="boi_rate_decrease_market",
            pipeline_run_id="run:boi",
            classification="unexpected_failure",
            expected_classification="scoreable_success",
            retrieval_terminal=False,
        )

        report = build_live_market_e2e_phase8_closure_report(cases, cleanup_proof=_cleanup_proof())

        self.assertFalse(report["ok"])
        self.assertIn("terminal_outcome_unclear", report["issues"])
        self.assertIn("retrieval_terminal_outcome_missing", report["issues"])
        self.assertIn("case_terminal_outcome_unclear", report["case_summaries"][0]["issues"])

    def test_closure_report_blocks_market_prediction_without_valid_scae(self):
        cases = _passing_cases()
        cases[1] = _report(
            tag="central_bank_macro_market",
            pipeline_run_id="run:bad-central-bank",
            classification="structured_non_scoreable_insufficiency",
            retrieval_certified=False,
            retrieval_insufficient=True,
            researcher_model_count=0,
            scae_valid_count=0,
            scae_ledger_count=1,
            market_predictions_delta=1,
        )

        report = build_live_market_e2e_phase8_closure_report(cases, cleanup_proof=_cleanup_proof())

        self.assertFalse(report["ok"])
        self.assertIn("protected_market_prediction_delta_mismatch", report["issues"])
        self.assertIn("blocked_case_market_prediction_delta_nonzero", report["case_summaries"][1]["issues"])
        self.assertIn("market_prediction_without_valid_scae", report["case_summaries"][1]["issues"])

    def test_closure_report_blocks_live_mutation_in_cleanup_proof(self):
        report = build_live_market_e2e_phase8_closure_report(
            _passing_cases(),
            cleanup_proof=_cleanup_proof(live_db_protected_count_deltas={"market_predictions": 1}),
        )

        self.assertFalse(report["ok"])
        self.assertIn("cleanup:live_db_mutation_detected", report["issues"])
        self.assertFalse(report["cleanup_proof"]["ok"])

    def test_closure_report_blocks_failed_real_runtime_criteria(self):
        cases = _passing_cases()
        report_payload = cases[1]["real_runtime_report"]
        report_payload["ok"] = False
        report_payload["issues"] = ["qdt_end_to_end_quality_not_verified"]
        report_payload["model_runtime_evidence"]["qdt_end_to_end_quality_ok"] = False

        report = build_live_market_e2e_phase8_closure_report(cases, cleanup_proof=_cleanup_proof())

        self.assertFalse(report["ok"])
        self.assertIn("real_runtime_report_not_ok", report["issues"])
        self.assertIn("qdt_end_to_end_quality_not_verified", report["issues"])
        self.assertIn("real_runtime_report_not_ok", report["case_summaries"][1]["issues"])
        self.assertIn("qdt_end_to_end_quality_not_verified", report["case_summaries"][1]["issues"])

    def test_cli_reports_phase8_closure_status(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "report_ads_live_market_e2e_phase8_closure.py"
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
        self.assertEqual(report["schema_version"], "ads-live-market-e2e-phase8-closure/v1")


if __name__ == "__main__":
    unittest.main()
