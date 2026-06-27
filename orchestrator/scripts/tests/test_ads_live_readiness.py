#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_live_readiness import build_live_readiness_report
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
                metadata={"forecast_decision_id": f"decision-{external_market_id}"},
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
        self.assertIn("calibration_debt_not_cleared", report["issues"])

    def test_scoreable_gate_allows_bounded_production_pilot_debt_canary(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=1,
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertTrue(report["allow_calibration_debt_scoreable_canary"])
        self.assertEqual(report["requested_max_cases"], 1)
        self.assertEqual(report["scoreable_readiness_mode"], "pilot_scoreable_readiness")

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
                "scae_evidence_delta_ref_count": 0,
            },
        )

    def test_true_live_readiness_accepts_true_production_handler_with_cal001_inputs(self):
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
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["require_scoreable_live"])
        self.assertEqual(report["scoreable_readiness_mode"], "true_scoreable_live_readiness")
        self.assertTrue(report["calibration_debt_report"]["clears_calibration_debt"])
        self.assertEqual(
            report["calibration_debt_report"]["brier_score_report"]["scorecards"]["scorecards"],
            100,
        )

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
