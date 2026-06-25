#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.calibration_debt import (
    CAL001_STATUS_BLOCKED,
    CAL001_STATUS_CLEARED,
    GATE_SCORECARD_BRIER_EVIDENCE,
    CalibrationDebtClearancePolicy,
    build_calibration_debt_clearance_report,
)
from predquant.sqlite_store import (
    record_prediction_with_snapshot,
    write_resolution_score,
)


class Cal001CalibrationDebtTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"
        self.policy = CalibrationDebtClearancePolicy(
            min_resolved_cases=1,
            min_tail_slice_cases=1,
            min_regime_slices=1,
            min_protected_component_slices=1,
            min_pointer_stability_windows=1,
            max_tail_absolute_calibration_error=0.10,
            max_log_loss_degradation=0.0,
            max_protected_component_degradation=0.0,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def payload(self, external_market_id="market-cal001"):
        return {
            "platform": "polymarket",
            "external_market_id": external_market_id,
            "slug": external_market_id,
            "title": "Will CAL-001 pass?",
            "status": "open",
            "snapshot": {
                "observed_at": "2026-01-01T00:00:00+00:00",
                "best_bid": 0.4,
                "best_ask": 0.5,
                "raw_payload": {"book": external_market_id},
            },
        }

    def record_prediction(self, external_market_id="market-cal001"):
        return record_prediction_with_snapshot(
            db_path=self.db_path,
            payload=self.payload(external_market_id),
            predicted_probability=0.65,
            prediction_run_id=f"run-{external_market_id}",
            forecast_artifact_id=f"forecast-{external_market_id}",
            case_key=f"polymarket:{external_market_id}",
            case_id=f"case-{external_market_id}",
            dispatch_id=f"dispatch-{external_market_id}",
            engine_stage="scae",
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
            predicted_at="2026-01-01T00:01:00+00:00",
            input_artifact_path="artifacts/scae-ledger.json",
            input_artifact_sha256="sha256:ledger",
            prediction_artifact_path="artifacts/forecast-decision.json",
            prediction_artifact_sha256="sha256:decision",
            metadata={"forecast_decision_id": f"decision-{external_market_id}"},
        )

    def passing_tail(self):
        return [
            {
                "slice_id": "tail:p90_100",
                "case_count": 1,
                "status": "pass",
                "absolute_calibration_error": 0.02,
                "log_loss_degradation": 0.0,
                "catastrophic_tail_failures": 0,
            }
        ]

    def passing_regime(self):
        return [
            {
                "regime_id": "regime:liquid-open",
                "case_count": 1,
                "status": "pass",
                "absolute_calibration_error": 0.02,
            }
        ]

    def passing_protected_components(self):
        return [
            {
                "component_id": "protected:source-of-truth",
                "case_count": 1,
                "status": "pass",
                "max_brier_degradation": 0.0,
            }
        ]

    def passing_pointer(self):
        return {
            "status": "passed",
            "active_policy_pointer_ref": "policy-pointer:baseline",
            "stable_window_count": 1,
            "window_started_at": "2026-01-01T00:00:00+00:00",
            "window_completed_at": "2026-01-08T00:00:00+00:00",
        }

    def complete_report_kwargs(self):
        return {
            "db_path": self.db_path,
            "first100_trace_complete": True,
            "trace_manifest_count": 100,
            "tail_slice_diagnostics": self.passing_tail(),
            "regime_diagnostics": self.passing_regime(),
            "protected_component_diagnostics": self.passing_protected_components(),
            "pointer_stability_evidence": self.passing_pointer(),
            "policy": self.policy,
            "prediction_source": "ads_pipeline",
            "prediction_label": "v2_scae",
        }

    def test_first100_trace_completeness_alone_does_not_clear_debt(self):
        report = build_calibration_debt_clearance_report(
            db_path=self.db_path,
            first100_trace_complete=True,
            trace_manifest_count=100,
            policy=self.policy,
        )

        self.assertEqual(report["status"], CAL001_STATUS_BLOCKED)
        self.assertFalse(report["clears_calibration_debt"])
        self.assertFalse(report["production_forecast_write_authority"])
        self.assertFalse(report["scae_probability_rewrite_authority"])
        self.assertFalse(report["calibration_policy_promotion_authority"])
        self.assertIn(
            "trace completeness is required but cannot clear calibration debt by itself",
            report["gates"][0]["evidence"]["sufficiency_note"],
        )
        blocked_gate_ids = {
            gate["gate_id"]
            for gate in report["gates"]
            if gate["status"] == "blocked"
        }
        self.assertIn(GATE_SCORECARD_BRIER_EVIDENCE, blocked_gate_ids)

    def test_unscored_prediction_and_missing_scorecard_evidence_block_clearance(self):
        self.record_prediction()

        report = build_calibration_debt_clearance_report(**self.complete_report_kwargs())

        self.assertEqual(report["status"], CAL001_STATUS_BLOCKED)
        self.assertFalse(report["clears_calibration_debt"])
        scorecard_gate = next(
            gate for gate in report["gates"] if gate["gate_id"] == GATE_SCORECARD_BRIER_EVIDENCE
        )
        self.assertEqual(scorecard_gate["evidence"]["resolved_cases"], 0)
        self.assertEqual(scorecard_gate["evidence"]["scorecards"], 0)

    def test_scorecard_brier_tail_regime_protected_and_pointer_gates_clear(self):
        self.record_prediction()
        write_resolution_score(
            db_path=self.db_path,
            external_market_id="market-cal001",
            outcome=1.0,
            resolved_at="2026-01-02T00:00:00+00:00",
            resolution_source="polymarket-resolution-sync",
            resolution_payload={"result": "yes", "source_id": "resolution-fixture"},
            resolution_method="api",
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
        )

        report = build_calibration_debt_clearance_report(**self.complete_report_kwargs())

        self.assertEqual(report["status"], CAL001_STATUS_CLEARED)
        self.assertTrue(report["clears_calibration_debt"])
        self.assertTrue(all(gate["status"] == "passed" for gate in report["gates"]))
        scorecard_gate = next(
            gate for gate in report["gates"] if gate["gate_id"] == GATE_SCORECARD_BRIER_EVIDENCE
        )
        self.assertEqual(scorecard_gate["evidence"]["resolved_cases"], 1)
        self.assertEqual(scorecard_gate["evidence"]["scorecards"], 1)
        self.assertEqual(len(report["session6_handoff"]["scorecard_refs"]), 1)
        self.assertIn(
            "production_forecast_write",
            report["session6_handoff"]["forbidden_uses"],
        )

    def test_pointer_or_protected_component_failures_remain_explicitly_blocked(self):
        self.record_prediction()
        write_resolution_score(
            db_path=self.db_path,
            external_market_id="market-cal001",
            outcome=1.0,
            resolved_at="2026-01-02T00:00:00+00:00",
            resolution_source="polymarket-resolution-sync",
            resolution_payload={"result": "yes", "source_id": "resolution-fixture"},
            resolution_method="api",
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
        )
        kwargs = self.complete_report_kwargs()
        kwargs["pointer_stability_evidence"] = {
            "status": "blocked",
            "blocked_reason": "active pointer moved during window",
        }
        kwargs["protected_component_diagnostics"] = [
            {
                "component_id": "protected:source-of-truth",
                "case_count": 1,
                "status": "pass",
                "max_brier_degradation": 0.01,
            }
        ]

        report = build_calibration_debt_clearance_report(**kwargs)

        self.assertEqual(report["status"], CAL001_STATUS_BLOCKED)
        self.assertFalse(report["clears_calibration_debt"])
        self.assertTrue(
            any("explicit blocked status" in reason for reason in report["blocked_reasons"])
        )
        self.assertTrue(
            any("protected components degraded" in reason for reason in report["blocked_reasons"])
        )


if __name__ == "__main__":
    unittest.main()
