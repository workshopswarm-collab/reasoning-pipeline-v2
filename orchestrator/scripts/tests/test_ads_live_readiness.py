#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff import ArtifactManifestContext, build_artifact_manifest, ensure_artifact_manifest_schema, write_artifact_manifest
from predquant.ads_live_readiness import build_live_readiness_report
from predquant.ads_pipeline_runner import PipelineRunnerPolicy, build_pipeline_run, ensure_pipeline_runner_schema, write_pipeline_run
from predquant.sqlite_store import SCHEMA, record_prediction_with_snapshot, write_resolution_score


class AdsLiveReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seed_market()
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def _seed_market(self):
        market_id = self.conn.execute(
            """
            INSERT INTO markets (
              platform, external_market_id, slug, title, description, category,
              status, outcome_type, closes_at, resolves_at, metadata, current_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "polymarket",
                "live-readiness",
                "live-readiness",
                "Will ADS live readiness pass?",
                "Synthetic readiness market",
                "test",
                "open",
                "binary",
                "2100-01-01T00:00:00+00:00",
                "2100-01-02T00:00:00+00:00",
                "{}",
                0.51,
            ),
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO market_snapshots (
              market_id, observed_at, last_price, best_bid, best_ask, yes_price,
              no_price, volume, open_interest, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market_id,
                "2099-12-31T23:55:00+00:00",
                None,
                0.49,
                0.53,
                None,
                None,
                100.0,
                50.0,
                json.dumps({"source": "unit-test"}, sort_keys=True),
            ),
        )

    def _prediction_payload(self, external_market_id: str) -> dict:
        return {
            "platform": "polymarket",
            "external_market_id": external_market_id,
            "slug": external_market_id,
            "title": f"Will {external_market_id} resolve yes?",
            "status": "open",
            "snapshot": {
                "observed_at": "2099-12-31T23:55:00+00:00",
                "best_bid": 0.49,
                "best_ask": 0.53,
                "raw_payload": {"source": "true-live-readiness-test", "market": external_market_id},
            },
        }

    def _true_runtime_prediction_metadata(self, external_market_id: str) -> dict:
        return {
            "forecast_decision_id": f"decision-{external_market_id}",
            "runtime_kind": "true_production",
            "scoreable_prediction_source": "scae.production_forecast_prob",
            "qdt_manifest_ref": f"artifact:qdt:{external_market_id}",
            "retrieval_packet_ref": f"artifact:retrieval:{external_market_id}",
            "researcher_runtime_bundle_ref": f"artifact:researcher-runtime:{external_market_id}",
            "classification_verification_ref": f"artifact:classification-verification:{external_market_id}",
            "scae_ledger_ref": f"artifact:scae-ledger:{external_market_id}",
            "trace_manifest_ref": f"artifact:trace:{external_market_id}",
            "replay_manifest_ref": f"artifact:replay:{external_market_id}",
            "scoreable_pilot": False,
            "clone_run": False,
            "non_executing_canary": False,
            "runner_mode": "calibration_debt_production",
            "handler_scope": "true_production",
        }

    def _passing_strict_non_scoreable_canary_report(self) -> dict:
        return {
            "schema_version": "ads-real-runtime-canary-report/v1",
            "ok": True,
            "issues": [],
            "first_failing_gate": None,
            "pipeline_run_id": "run:strict-non-scoreable",
            "criteria": {
                "expected_market_predictions": 0,
                "require_scoreable_prediction": False,
                "first_failing_gate": None,
            },
        }

    def _seed_calibration_debt_clearance_evidence(self, count: int = 100):
        self.conn.commit()
        for index in range(count):
            external_market_id = f"true-live-readiness-{index:03d}"
            record_prediction_with_snapshot(
                db_path=self.db_path,
                payload=self._prediction_payload(external_market_id),
                predicted_probability=0.65,
                prediction_run_id=f"run-{external_market_id}",
                forecast_artifact_id=f"forecast-{external_market_id}",
                case_key=f"polymarket:{external_market_id}",
                case_id=f"case-{external_market_id}",
                dispatch_id=f"dispatch-{external_market_id}",
                engine_stage="scae",
                prediction_source="ads_pipeline",
                prediction_label="v2_scae",
                predicted_at="2100-01-01T00:01:00+00:00",
                input_artifact_path="artifacts/scae-ledger.json",
                input_artifact_sha256="sha256:ledger",
                prediction_artifact_path="artifacts/forecast-decision.json",
                prediction_artifact_sha256="sha256:decision",
                metadata=self._true_runtime_prediction_metadata(external_market_id),
            )
            write_resolution_score(
                db_path=self.db_path,
                external_market_id=external_market_id,
                outcome=1.0,
                resolved_at="2100-01-02T00:00:00+00:00",
                resolution_source="polymarket-resolution-sync",
                resolution_payload={"result": "yes", "source_id": external_market_id},
                resolution_method="api",
                prediction_source="ads_pipeline",
                prediction_label="v2_scae",
                evaluation_cluster_id="calibration-debt-clearance",
            )

    def _passing_tail_diagnostics(self):
        return [
            {
                "slice_id": "tail:p90_100",
                "case_count": 100,
                "status": "pass",
                "absolute_calibration_error": 0.02,
                "log_loss_degradation": 0.0,
                "catastrophic_tail_failures": 0,
            }
        ]

    def _passing_regime_diagnostics(self):
        return [
            {
                "regime_id": "regime:liquid-open",
                "case_count": 100,
                "status": "pass",
                "absolute_calibration_error": 0.02,
            }
        ]

    def _passing_protected_component_diagnostics(self):
        return [
            {
                "component_id": "protected:source-of-truth",
                "case_count": 100,
                "status": "pass",
                "max_brier_degradation": 0.0,
            }
        ]

    def _passing_pointer_stability(self):
        return {
            "status": "passed",
            "active_policy_pointer_ref": "scae-policy:pointer:current",
            "stable_window_count": 1,
            "window_started_at": "2100-01-01T00:00:00+00:00",
            "window_completed_at": "2100-01-08T00:00:00+00:00",
        }

    def _seed_scae_ledger_manifest(self, *, pipeline_run_id: str = "run:true-live-readiness") -> str:
        ensure_pipeline_runner_schema(self.conn)
        ensure_artifact_manifest_schema(self.conn)
        write_pipeline_run(
            self.conn,
            build_pipeline_run(
                policy=PipelineRunnerPolicy(runner_mode="calibration_debt_production", max_cases=1),
                pipeline_run_id=pipeline_run_id,
                started_at="2100-01-01T00:00:00+00:00",
                stopped_at="2100-01-01T00:01:00+00:00",
                metadata={"handler_factory": "predquant.ads_production_handlers"},
            ),
        )
        payload = {
            "artifact_type": "scae-final-probability-ledger",
            "schema_version": "scae-final-probability-ledger/v1",
            "forecast_validity_status": "valid_for_forecast",
            "scoreable_forecast_output": True,
            "scae_evidence_delta_candidate_slice_refs": ["scae-candidate-slice:1"],
            "scae_evidence_delta_classification_slice_refs": ["classification-slice:1"],
            "scae_evidence_delta_direction_verification_slice_refs": ["direction-slice:1"],
            "scae_evidence_delta_quality_verification_slice_refs": ["quality-slice:1"],
        }
        artifact_path = Path(self.tempdir.name) / "scae-final-probability-ledger.json"
        artifact_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        manifest = build_artifact_manifest(
            context=ArtifactManifestContext(
                case_id="case:true-live-readiness",
                case_key="polymarket:true-live-readiness",
                dispatch_id="dispatch:true-live-readiness",
                stage="scae",
                producer="unit-test",
                pipeline_run_id=pipeline_run_id,
                forecast_timestamp="2100-01-01T00:00:00+00:00",
                source_cutoff_timestamp="2100-01-01T00:00:00+00:00",
            ),
            artifact_type="scae-final-probability-ledger",
            artifact_schema_version="scae-final-probability-ledger/v1",
            path=artifact_path,
            validation_status="valid",
        )
        artifact_id = write_artifact_manifest(self.conn, manifest)
        self.conn.commit()
        return artifact_id

    def test_production_readiness_handler_passes_non_scoreable_gate(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_readiness_handlers:build_stage_handlers",
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["require_scoreable_live"])
        self.assertFalse(report["calibration_debt_report"]["clears_calibration_debt"])

    def test_canary_handler_is_blocked_without_explicit_allowance(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_scoreable_canary_handlers:build_stage_handlers",
        )

        self.assertFalse(report["ok"])
        self.assertIn("canary_handler_factory_not_allowed", report["issues"])

    def test_scoreable_gate_blocks_non_scoreable_readiness_handler(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_readiness_handlers:build_stage_handlers",
            require_scoreable_live=True,
        )

        self.assertFalse(report["ok"])
        self.assertIn("production_readiness_handler_is_non_scoreable", report["issues"])
        self.assertIn("calibration_debt_not_cleared", report["issues"])

    def test_scoreable_gate_blocks_production_pilot_without_debt_canary_allowance(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            requested_max_cases=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("strict_true_runtime_canary_evidence_missing", report["issues"])
        self.assertIn("calibration_debt_not_cleared", report["issues"])

    def test_scoreable_gate_allows_bounded_true_production_debt_canary(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_handlers:build_stage_handlers",
            require_scoreable_live=True,
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=1,
            strict_non_scoreable_canary_report=self._passing_strict_non_scoreable_canary_report(),
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertTrue(report["allow_calibration_debt_scoreable_canary"])
        self.assertEqual(report["requested_max_cases"], 1)
        self.assertEqual(report["scoreable_readiness_mode"], "pilot_scoreable_readiness")
        self.assertEqual(
            report["strict_non_scoreable_canary_signal_report"]["status"],
            "passed",
        )

    def test_scoreable_gate_blocks_when_strict_canary_evidence_absent(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_handlers:build_stage_handlers",
            require_scoreable_live=True,
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("strict_true_runtime_canary_evidence_missing", report["issues"])
        self.assertEqual(
            report["strict_non_scoreable_canary_signal_report"]["status"],
            "missing",
        )

    def test_true_live_readiness_rejects_pilot_even_with_debt_canary_allowance(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            scoreable_readiness_mode="true_scoreable_live_readiness",
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("true_scoreable_live_readiness_rejects_production_pilot_handler", report["issues"])
        self.assertIn("true_scoreable_live_readiness_rejects_calibration_debt_canary_bypass", report["issues"])

    def test_true_live_readiness_rejects_reported_pilot_only_runtime_signals(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_handlers:build_stage_handlers",
            require_scoreable_live=True,
            scoreable_readiness_mode="true_scoreable_live_readiness",
            qdt_adapter_mode="pilot_fixture_decomposer_contract_adapter",
            researcher_runtime_mode="metadata_only",
            research_input_mode="structured_market_metadata_certified",
            first100_trace_complete=True,
            trace_manifest_count=100,
        )

        self.assertFalse(report["ok"])
        self.assertIn("true_scoreable_live_readiness_rejects_pilot_qdt_adapter_mode", report["issues"])
        self.assertIn("true_scoreable_live_readiness_rejects_metadata_only_researcher_context", report["issues"])
        self.assertIn("true_production_deterministic_qdt", report["issues"])
        self.assertIn("true_production_metadata_only_researcher", report["issues"])
        self.assertIn("missing_amrg_refresh_status_for_promoted_effects", report["issues"])
        self.assertIn("missing_scae_evidence_delta_refs", report["issues"])
        self.assertIn(
            "true_scoreable_live_readiness_rejects_structured_market_metadata_only_research_input",
            report["issues"],
        )
        self.assertEqual(
            report["reported_runtime_signals"],
            {
                "qdt_adapter_mode": "pilot_fixture_decomposer_contract_adapter",
                "researcher_runtime_mode": "metadata_only",
                "research_input_mode": "structured_market_metadata_certified",
                "amrg_refresh_status": None,
                "amrg_vector_status": "vector_unavailable_allowed_weak_context",
                "amrg_assist_status": "assist_not_requested_by_policy",
                "scae_evidence_delta_ref_count": 0,
                "supplied_scae_evidence_delta_ref_count": 0,
                "strict_non_scoreable_canary_status": "missing",
            },
        )

    def test_amrg_vector_optional_unavailable_is_non_blocking_readiness_signal(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_readiness_handlers:build_stage_handlers",
            amrg_vector_preflight={
                "ok": False,
                "provider": "ollama",
                "route_id": "ollama/local",
                "resolved_model_id": "BAAI/bge-base-en-v1.5",
                "embedding_dimension": 768,
                "unavailable_reason": "ollama_route_unavailable",
                "diagnostic": {
                    "schema_version": "amrg-vector-candidate-source-diagnostic/v1",
                    "reason_code": "amrg_vector_candidate_source_unavailable",
                    "unavailable_reason": "ollama_route_unavailable",
                    "candidate_source": "local_bge_vector_neighbor",
                    "non_blocking": True,
                    "does_not_block": ["QDT", "retrieval", "SCAE", "decision"],
                    "source_cutoff_timestamp": None,
                    "metadata": {},
                },
            },
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(
            report["amrg_dependency_readiness"]["vector_status"],
            "vector_unavailable_allowed_weak_context",
        )
        self.assertEqual(
            report["reported_runtime_signals"]["amrg_assist_status"],
            "assist_not_requested_by_policy",
        )

    def test_amrg_vector_required_unavailable_blocks_readiness(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_readiness_handlers:build_stage_handlers",
            amrg_vector_required=True,
            amrg_vector_preflight={
                "ok": False,
                "provider": "ollama",
                "route_id": "ollama/local",
                "resolved_model_id": "BAAI/bge-base-en-v1.5",
                "embedding_dimension": 768,
                "unavailable_reason": "ollama_route_unavailable",
            },
        )

        self.assertFalse(report["ok"])
        self.assertIn("amrg_vector_required_but_unavailable", report["issues"])
        self.assertEqual(
            report["amrg_dependency_readiness"]["vector_status"],
            "vector_required_but_unavailable",
        )

    def test_true_live_readiness_rejects_placeholder_scae_delta_refs(self):
        self._seed_calibration_debt_clearance_evidence()

        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_handlers:build_stage_handlers",
            require_scoreable_live=True,
            scoreable_readiness_mode="true_scoreable_live_readiness",
            qdt_adapter_mode="decomposer_model_runtime_live",
            researcher_runtime_mode="model_executed",
            research_input_mode="verified_researcher_scae_evidence",
            amrg_refresh_status="fresh_no_refresh_needed",
            scae_evidence_delta_refs=("classification-slice-1",),
            first100_trace_complete=True,
            trace_manifest_count=100,
            tail_slice_diagnostics=self._passing_tail_diagnostics(),
            regime_diagnostics=self._passing_regime_diagnostics(),
            protected_component_diagnostics=self._passing_protected_component_diagnostics(),
            pointer_stability_evidence=self._passing_pointer_stability(),
            strict_non_scoreable_canary_report=self._passing_strict_non_scoreable_canary_report(),
        )

        self.assertFalse(report["ok"])
        self.assertIn("invalid_scae_evidence_delta_refs", report["issues"])
        self.assertIn("missing_scae_evidence_delta_refs", report["issues"])
        self.assertEqual(report["scae_evidence_signal_report"]["rejected_supplied_refs"], ["classification-slice-1"])

    def test_true_live_readiness_accepts_true_production_handler_with_manifest_scae_inputs(self):
        self._seed_calibration_debt_clearance_evidence()
        scae_manifest_ref = self._seed_scae_ledger_manifest()

        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_handlers:build_stage_handlers",
            require_scoreable_live=True,
            scoreable_readiness_mode="true_scoreable_live_readiness",
            qdt_adapter_mode="decomposer_model_runtime_live",
            researcher_runtime_mode="model_executed",
            research_input_mode="verified_researcher_scae_evidence",
            amrg_refresh_status="fresh_no_refresh_needed",
            scae_evidence_delta_refs=(scae_manifest_ref,),
            first100_trace_complete=True,
            trace_manifest_count=100,
            tail_slice_diagnostics=self._passing_tail_diagnostics(),
            regime_diagnostics=self._passing_regime_diagnostics(),
            protected_component_diagnostics=self._passing_protected_component_diagnostics(),
            pointer_stability_evidence=self._passing_pointer_stability(),
            strict_non_scoreable_canary_report=self._passing_strict_non_scoreable_canary_report(),
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["require_scoreable_live"])
        self.assertEqual(report["scoreable_readiness_mode"], "true_scoreable_live_readiness")
        self.assertEqual(report["scae_evidence_signal_report"]["accepted_supplied_refs"], [scae_manifest_ref])
        self.assertEqual(report["reported_runtime_signals"]["scae_evidence_delta_ref_count"], 4)
        self.assertTrue(report["calibration_debt_report"]["clears_calibration_debt"])
        self.assertEqual(
            report["calibration_debt_report"]["brier_score_report"]["scorecards"]["scorecards"],
            100,
        )

    def test_readiness_operator_review_without_run_returns_structured_report(self):
        report = build_live_readiness_report(
            self.db_path,
            handler_factory="predquant.ads_production_handlers:build_stage_handlers",
            include_operator_review=True,
        )

        self.assertIn("operator_review_report", report)
        self.assertIsInstance(report["operator_review_report"], dict)
        self.assertIn("alerts", report["operator_review_report"])

    def test_scoreable_gate_blocks_overlarge_debt_canary_batch(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=3,
            max_calibration_debt_canary_cases=2,
        )

        self.assertFalse(report["ok"])
        self.assertIn("calibration_debt_scoreable_canary_exceeds_case_limit", report["issues"])


if __name__ == "__main__":
    unittest.main()
