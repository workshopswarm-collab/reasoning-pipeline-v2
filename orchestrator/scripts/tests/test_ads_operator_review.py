#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_operator_review import _build_alerts, _retrieval_summary, _true_runtime_cutover_status


class AdsOperatorReviewTest(unittest.TestCase):
    def test_retrieval_summary_treats_null_lists_as_empty(self):
        with tempfile.TemporaryDirectory() as tempdir:
            artifact_path = Path(tempdir) / "retrieval.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "adapter_mode": "live_retrieval_runtime",
                        "research_sufficiency_summary": None,
                        "leaf_evidence_dockets": None,
                        "browser_retrieval_attempts": None,
                        "native_research_transport_diagnostics": None,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            summary = _retrieval_summary(
                [
                    {
                        "stage": "retrieval",
                        "artifact_id": "retrieval-manifest:1",
                        "artifact_path": str(artifact_path),
                    }
                ]
            )

        self.assertEqual(summary["artifact_id"], "retrieval-manifest:1")
        self.assertFalse(summary["all_required_leaves_certified"])
        self.assertEqual(summary["leaf_certificate_refs"], [])
        self.assertEqual(summary["native_research_transport_diagnostics"], [])
        self.assertEqual(summary["browser_retrieval_attempt_count"], 0)
        self.assertEqual(summary["leaf_evidence_docket_count"], 0)
        self.assertEqual(summary["admitted_evidence_ref_count"], 0)

    def test_retrieval_summary_exposes_gap_diagnostics(self):
        with tempfile.TemporaryDirectory() as tempdir:
            artifact_path = Path(tempdir) / "retrieval.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "adapter_mode": "live_retrieval_runtime",
                        "retrieval_runtime_summary": {
                            "search_candidate_url_count": 0,
                            "duplicate_canonical_url_omissions": 1,
                        },
                        "research_sufficiency_summary": {
                            "classification_dispatch_status": "blocked_insufficient_research",
                        },
                        "search_candidate_urls": [],
                        "retrieval_expansion_attempts": [
                            {"attempt_status": "planned_not_executed"},
                        ],
                        "leaf_evidence_dockets": [
                            {
                                "leaf_id": "leaf-a",
                                "admitted_evidence_refs": ["evidence:short"],
                            }
                        ],
                        "leaf_retrieval_results": [
                            {
                                "leaf_id": "leaf-a",
                                "admitted_evidence_refs": ["evidence:short"],
                            }
                        ],
                        "evidence_chunks": [
                            {
                                "evidence_ref": "evidence:short",
                                "excerpt_policy": "hash_only",
                                "excerpt_char_count": 12,
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            summary = _retrieval_summary(
                [
                    {
                        "stage": "retrieval",
                        "artifact_id": "retrieval-manifest:1",
                        "artifact_path": str(artifact_path),
                    }
                ]
            )

        self.assertEqual(summary["planned_not_executed_expansion_count"], 1)
        self.assertEqual(summary["search_candidates_materialized_count"], 0)
        self.assertEqual(summary["hash_only_admitted_count"], 1)
        self.assertEqual(summary["short_chunk_admitted_count"], 1)
        self.assertEqual(summary["meaningful_snippet_admitted_count"], 0)
        self.assertEqual(summary["canonical_fetch_duplicate_count"], 1)

    def test_true_production_non_scoreable_alerts_are_warnings(self):
        alerts = self._true_production_alerts_for_run(
            {
                "runner_mode": "non_executing_canary",
                "metadata": {
                    "handler_factory": "predquant.ads_production_handlers",
                    "purpose": "strict_non_scoreable_canary",
                },
            }
        )

        by_code = {alert["code"]: alert for alert in alerts}
        self.assertNotIn("operator_review_no_alerts", by_code)
        self.assertEqual(by_code["true_production_retrieval_not_certified"]["severity"], "warning")
        self.assertEqual(by_code["true_production_zero_admitted_evidence_refs"]["severity"], "warning")
        self.assertEqual(
            by_code["true_production_browser_retrieval_missing_native_unavailable"]["severity"],
            "warning",
        )
        self.assertEqual(by_code["true_production_researcher_runtime_missing"]["severity"], "warning")
        self.assertEqual(
            by_code["true_production_scae_invalid_research_sufficiency_blocked"]["severity"],
            "warning",
        )

    def test_true_runtime_cutover_status_prioritizes_missing_retrieval_cert(self):
        status = _true_runtime_cutover_status(
            run={
                "runner_mode": "non_executing_canary",
                "status": "stopped",
                "terminal_reason": "auto003_single_case_complete",
                "metadata": {"handler_factory": "predquant.ads_production_handlers"},
            },
            run_kind="true_production",
            cases=[
                {
                    "retrieval_sufficiency": {
                        "all_required_leaves_certified": False,
                        "admitted_evidence_ref_count": 0,
                    },
                    "researcher_model_provenance": {"model_executed_count": 0},
                    "scae_readiness": {"artifact_id": None},
                }
            ],
        )

        self.assertEqual(status, "blocked_missing_retrieval_cert")

    def test_true_runtime_cutover_status_blocks_failed_stage(self):
        status = _true_runtime_cutover_status(
            run={
                "runner_mode": "calibration_debt_production",
                "status": "failed",
                "terminal_reason": "auto003_stage_failed",
                "metadata": {"handler_factory": "predquant.ads_production_handlers"},
            },
            run_kind="true_production",
            cases=[],
        )

        self.assertEqual(status, "blocked_stage_failure")

    def test_true_runtime_cutover_status_blocks_missing_researcher_model(self):
        status = _true_runtime_cutover_status(
            run={
                "runner_mode": "calibration_debt_production",
                "status": "stopped",
                "terminal_reason": "auto003_single_case_complete",
                "metadata": {"handler_factory": "predquant.ads_production_handlers"},
            },
            run_kind="true_production",
            cases=[
                {
                    "retrieval_sufficiency": {
                        "all_required_leaves_certified": True,
                        "admitted_evidence_ref_count": 2,
                    },
                    "researcher_model_provenance": {"model_executed_count": 0},
                    "scae_readiness": {
                        "artifact_id": "artifact:scae-ledger:1",
                        "forecast_validity_status": "valid_for_forecast",
                    },
                }
            ],
        )

        self.assertEqual(status, "blocked_missing_researcher_model_execution")

    def test_true_runtime_cutover_status_blocks_missing_scae_ledger(self):
        status = _true_runtime_cutover_status(
            run={
                "runner_mode": "calibration_debt_production",
                "status": "stopped",
                "terminal_reason": "auto003_single_case_complete",
                "metadata": {"handler_factory": "predquant.ads_production_handlers"},
            },
            run_kind="true_production",
            cases=[
                {
                    "retrieval_sufficiency": {
                        "all_required_leaves_certified": True,
                        "admitted_evidence_ref_count": 2,
                    },
                    "researcher_model_provenance": {"model_executed_count": 1},
                    "scae_readiness": {"artifact_id": None},
                }
            ],
        )

        self.assertEqual(status, "blocked_missing_scae_ledger")

    def test_true_runtime_cutover_status_ready_for_complete_full_run(self):
        status = _true_runtime_cutover_status(
            run={
                "runner_mode": "calibration_debt_production",
                "status": "stopped",
                "terminal_reason": "auto003_single_case_complete",
                "metadata": {"handler_factory": "predquant.ads_production_handlers"},
            },
            run_kind="true_production",
            cases=[
                {
                    "retrieval_sufficiency": {
                        "all_required_leaves_certified": True,
                        "admitted_evidence_ref_count": 2,
                    },
                    "researcher_model_provenance": {"model_executed_count": 1},
                    "scae_readiness": {
                        "artifact_id": "artifact:scae-ledger:1",
                        "forecast_validity_status": "valid_for_forecast",
                    },
                }
            ],
        )

        self.assertEqual(status, "ready")

    def test_true_production_release_alerts_are_blockers(self):
        alerts = self._true_production_alerts_for_run(
            {
                "runner_mode": "calibration_debt_production",
                "metadata": {"handler_factory": "predquant.ads_production_handlers", "purpose": "cutover"},
            }
        )

        by_code = {alert["code"]: alert for alert in alerts}
        self.assertEqual(by_code["true_production_retrieval_not_certified"]["severity"], "blocker")
        self.assertEqual(by_code["true_production_zero_admitted_evidence_refs"]["severity"], "blocker")
        self.assertEqual(
            by_code["true_production_browser_retrieval_missing_native_unavailable"]["severity"],
            "blocker",
        )
        self.assertEqual(by_code["true_production_researcher_runtime_missing"]["severity"], "blocker")
        self.assertEqual(
            by_code["true_production_scae_invalid_research_sufficiency_blocked"]["severity"],
            "blocker",
        )

    def _true_production_alerts_for_run(self, run):
        return _build_alerts(
            pipeline_run_id="ads-pipeline-run:test",
            run_kind="true_production",
            run=run,
            active_runs=[],
            active_leases=[],
            handoff_report={"ok": True, "unresolved_output_manifest_refs": []},
            storage={"wal_size_bytes": 0, "retention_candidates": []},
            freshness={"market_snapshot": {"age_seconds": None}, "resolution_sync": {"age_seconds": None}},
            cases=[
                {
                    "case_id": "case:test",
                    "case_key": "polymarket:test",
                    "dispatch_id": "dispatch:test",
                    "qdt_model_provenance": {"model_executed": True},
                    "amrg_consumed_hints": [],
                    "retrieval_sufficiency": {
                        "artifact_id": "retrieval-manifest:1",
                        "all_required_leaves_certified": False,
                        "admitted_evidence_ref_count": 0,
                        "browser_retrieval_attempt_count": 0,
                        "native_research_transport_diagnostics": [
                            {"availability_status": "unavailable"}
                        ],
                    },
                    "researcher_model_provenance": {
                        "model_executed_count": 0,
                        "classification_artifacts": [{"artifact_id": "classification-manifest:1"}],
                    },
                    "verification_readiness": {
                        "reason_codes": ["research_sufficiency_not_certified"],
                        "reconciliation_statuses": ["blocked_insufficient_research"],
                    },
                    "scae_readiness": {
                        "artifact_id": "scae-manifest:1",
                        "forecast_validity_status": "invalid_for_forecast",
                        "reason_codes": ["research_sufficiency_not_certified"],
                        "scoreable_forecast_output": False,
                        "evidence_delta_ref_count": 0,
                    },
                    "decision_and_prediction": {
                        "forecast_decision_records": [],
                        "market_predictions": [],
                    },
                }
            ],
            active_lease_block_seconds=3600,
            active_run_block_seconds=5400,
            wal_warning_bytes=512 * 1024 * 1024,
            wal_block_bytes=2 * 1024 * 1024 * 1024,
            max_market_snapshot_age_seconds=3600.0,
            max_resolution_sync_age_seconds=5400.0,
            source_freshness_warning_fraction=0.8,
        )


if __name__ == "__main__":
    unittest.main()
