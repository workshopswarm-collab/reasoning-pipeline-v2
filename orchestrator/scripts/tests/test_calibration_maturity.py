#!/usr/bin/env python3
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.calibration_maturity import (
    CalibrationMaturityError,
    build_calibration_candidate,
    build_decision_actionability_candidate,
    build_decomposer_profile_candidate,
    build_emergency_conservative_overlay,
    build_retrieval_policy_candidate,
    default_lane_registry,
    optimization_maturity_gate,
    promote_policy_pointer,
    resolve_lane_registry,
    score_candidate,
    start_candidate_canary,
    validate_candidate_bounds,
    validate_profile_candidate_non_degradation,
    validate_shared_reuse_temporal_safety,
    write_calibration_candidate,
    write_calibration_component_diagnostics,
    write_calibration_lane_health,
    write_decision_actionability_candidate,
    write_decomposer_profile_candidate,
    write_emergency_conservative_overlay,
    write_optimization_maturity_result,
    write_retrieval_policy_snapshot,
)


class CalibrationMaturityTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def change(self, parameter_id="identity_calibration_enabled", lane_id="post_ledger_calibration", value=1.0):
        return {"parameter_id": parameter_id, "owner_lane": lane_id, "value": value}

    def candidate(self, **overrides):
        values = {
            "lane_id": "post_ledger_calibration",
            "changed_parameters": [self.change()],
            "component_diagnostics_ref": "cal-diagnostic:1",
            "protected_slice_non_degradation_status": "passed",
            "holdout_status": "passed",
            "canary_status": "passed",
            "metadata": {"fixture": "session6"},
        }
        values.update(overrides)
        return build_calibration_candidate(**values)

    def slices(self, **overrides):
        values = {
            "evidence_purpose": "primary",
            "source_class": "official",
            "retrieval_quality_bucket": "good",
            "market_prior_reliability_bucket": "fresh_liquid",
            "market_state_regime_tag": "open_fresh_snapshot",
            "protected_primary_status": "satisfied",
            "family_aware_child_status": "not_applicable",
            "missingness_no_catalyst_status": "not_applicable",
            "claim_family_dependence_status": "independent",
        }
        values.update(overrides)
        return values

    def replay_cohort(self):
        return {
            "cohort_id": "cohort:resolved",
            "resolved_cases": [
                {
                    "resolved": True,
                    "outcome": 1.0,
                    "baseline_probability": 0.80,
                    "candidate_probability": 0.85,
                    "slices": self.slices(source_class="official"),
                },
                {
                    "resolved": True,
                    "outcome": 0.0,
                    "baseline_probability": 0.30,
                    "candidate_probability": 0.20,
                    "slices": self.slices(source_class="independent_media"),
                },
            ],
        }

    def retrieval_results(self, **overrides):
        values = {
            "cohort_id": "cohort:retrieval",
            "baseline_protected_primary_coverage": 0.80,
            "candidate_protected_primary_coverage": 0.85,
            "protected_primary_failure_rate": 0.10,
            "generic_missingness_rate": 0.20,
            "resolved_cases": [
                {
                    "retrieval_quality_bucket": "thin",
                    "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                    "source_observed_at": "2026-06-24T11:00:00+00:00",
                },
                {
                    "retrieval_quality_bucket": "thin",
                    "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                    "source_observed_at": "2026-06-24T11:30:00+00:00",
                },
            ],
        }
        values.update(overrides)
        return values

    def test_lane_registry_rejects_unknown_wrong_owner_and_out_of_bounds(self):
        self.assertIn("identity_calibration_enabled", resolve_lane_registry())

        with self.assertRaisesRegex(CalibrationMaturityError, "unknown tunable"):
            validate_candidate_bounds({"lane_id": "post_ledger_calibration", "changed_parameters": [self.change("unknown")]})

        with self.assertRaisesRegex(CalibrationMaturityError, "belongs to"):
            validate_candidate_bounds(
                {
                    "lane_id": "post_ledger_calibration",
                    "changed_parameters": [self.change("thin_retrieval_penalty", "post_ledger_calibration", 0.2)],
                }
            )

        with self.assertRaisesRegex(CalibrationMaturityError, "out of bounds"):
            validate_candidate_bounds({"lane_id": "post_ledger_calibration", "changed_parameters": [self.change(value=2.0)]})

        broken = default_lane_registry()
        del broken["lanes"]["post_ledger_calibration"][0]["rollback_semantics"]
        with self.assertRaisesRegex(CalibrationMaturityError, "rollback semantics"):
            resolve_lane_registry(broken)

    def test_component_diagnostics_protect_slices_and_require_resolved_cases(self):
        candidate = self.candidate()
        diagnostic = score_candidate(candidate, self.replay_cohort())
        self.assertIn("adaptive_calibration_error", diagnostic["metrics_json"])
        self.assertIn("brier_decomposition", diagnostic["metrics_json"])
        self.assertEqual(diagnostic["protected_slice_non_degradation_status"], "passed")
        diagnostic_id = write_calibration_component_diagnostics(self.conn, diagnostic)
        self.assertEqual(diagnostic_id, diagnostic["diagnostic_id"])

        missing = self.replay_cohort()
        del missing["resolved_cases"][0]["slices"]["source_class"]
        with self.assertRaisesRegex(CalibrationMaturityError, "missing protected slice"):
            score_candidate(candidate, missing)

        unresolved = self.replay_cohort()
        unresolved["resolved_cases"][0]["resolved"] = False
        with self.assertRaisesRegex(CalibrationMaturityError, "unresolved cases"):
            score_candidate(candidate, unresolved)

    def test_protected_slice_degradation_blocks_promotion_even_when_recorded(self):
        candidate = self.candidate()
        cohort = self.replay_cohort()
        cohort["resolved_cases"][0]["candidate_probability"] = 0.10
        diagnostic = score_candidate(candidate, cohort, {"max_protected_slice_degradation": 0.0})
        self.assertEqual(diagnostic["protected_slice_non_degradation_status"], "failed")

        failed = dict(candidate)
        failed["protected_slice_non_degradation_status"] = "failed"
        failed["component_diagnostics_ref"] = diagnostic["diagnostic_id"]
        with self.assertRaisesRegex(CalibrationMaturityError, "without diagnostics"):
            promote_policy_pointer(self.conn, failed, {"active_policy_snapshot_ref": "sha256:" + "a" * 64})

    def test_promotion_requires_diagnostics_holdout_canary_and_records_rollback(self):
        with self.assertRaisesRegex(CalibrationMaturityError, "without diagnostics"):
            promote_policy_pointer(
                self.conn,
                self.candidate(component_diagnostics_ref=None),
                {"active_policy_snapshot_ref": "sha256:" + "a" * 64},
            )
        with self.assertRaisesRegex(CalibrationMaturityError, "failed holdout"):
            start_candidate_canary(self.candidate(holdout_status="failed"))
        with self.assertRaisesRegex(CalibrationMaturityError, "failed canary"):
            promote_policy_pointer(
                self.conn,
                self.candidate(canary_status="failed"),
                {"active_policy_snapshot_ref": "sha256:" + "a" * 64},
            )

        pointer = promote_policy_pointer(
            self.conn,
            self.candidate(),
            {"active_policy_snapshot_ref": "sha256:" + "a" * 64},
        )
        self.assertEqual(pointer["pointer_status"], "active")
        self.assertFalse(pointer["live_forecast_authority"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM policy_rollback_events").fetchone()[0],
            1,
        )

    def test_unhealthy_retrieval_lane_does_not_invalidate_scae_pointer(self):
        write_calibration_lane_health(
            self.conn,
            {"lane_id": "retrieval_policy", "health_status": "blocked", "reason_codes": ["thin_bucket_underpowered"]},
        )
        scae = build_calibration_candidate(
            lane_id="scae_constants",
            changed_parameters=[self.change("per_update_log_odds_cap", "scae_constants", 0.2)],
            component_diagnostics_ref="cal-diagnostic:scae",
            protected_slice_non_degradation_status="passed",
            holdout_status="passed",
            canary_status="passed",
        )
        pointer = promote_policy_pointer(self.conn, scae, {"active_policy_snapshot_ref": "sha256:" + "a" * 64})
        self.assertEqual(pointer["lane_id"], "scae_constants")

    def test_retrieval_policy_lane_guards_temporal_and_protected_primary_metrics(self):
        candidate = build_retrieval_policy_candidate(self.retrieval_results())
        snapshot_id = write_retrieval_policy_snapshot(
            self.conn,
            candidate,
            {"thin_case_count": 2, "stale_evidence_case_count": 0},
        )
        row = self.conn.execute(
            "SELECT protected_primary_diagnostics FROM retrieval_policy_snapshot_records WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        diagnostics = json.loads(row[0])
        self.assertNotEqual(diagnostics["protected_primary_failure_rate"], diagnostics["generic_missingness_rate"])

        with self.assertRaisesRegex(CalibrationMaturityError, "enough resolved cases"):
            build_retrieval_policy_candidate(self.retrieval_results(resolved_cases=self.retrieval_results()["resolved_cases"][:1]))

        future = self.retrieval_results()
        future["resolved_cases"][0]["source_observed_at"] = "2026-06-24T12:01:00+00:00"
        with self.assertRaisesRegex(CalibrationMaturityError, "post-forecast"):
            build_retrieval_policy_candidate(future)

        with self.assertRaisesRegex(CalibrationMaturityError, "protected-primary coverage"):
            build_retrieval_policy_candidate(self.retrieval_results(candidate_protected_primary_coverage=0.50))

    def test_profile_lanes_capture_decomposer_miss_and_reject_probability_or_degradation(self):
        decomposer = build_decomposer_profile_candidate(
            {"branch_count": 3, "leaf_count": 8},
            [{"label_type": "missed_branch", "reason_code": "missing_protected_primary_leaf"}],
        )
        write_decomposer_profile_candidate(self.conn, decomposer)
        row = self.conn.execute("SELECT qdt_shape_summary FROM decomposer_profile_candidate_records").fetchone()
        self.assertEqual(json.loads(row[0])["leaf_count"], 8)

        with self.assertRaisesRegex(CalibrationMaturityError, "production_forecast_prob"):
            build_decision_actionability_candidate({"production_forecast_prob": 0.61})

        actionability = build_decision_actionability_candidate({"route": "watch_only"})
        write_decision_actionability_candidate(self.conn, actionability)

        with self.assertRaisesRegex(CalibrationMaturityError, "degrades protected slice"):
            validate_profile_candidate_non_degradation({"family_aware_child_status": 0.01})

    def test_emergency_overlay_is_conservative_expiring_and_non_authoritative(self):
        overlay = build_emergency_conservative_overlay(
            {"kind": "catastrophic_tail_check", "reason_codes": ["tail_failure"]},
            [{"direction": "widen_interval", "value": 0.5}],
            expires_at="2026-06-25T12:00:00+00:00",
        )
        overlay_id = write_emergency_conservative_overlay(self.conn, overlay)
        self.assertEqual(overlay_id, overlay["overlay_id"])
        self.assertFalse(overlay["live_forecast_authority"])

        with self.assertRaisesRegex(CalibrationMaturityError, "conservative only"):
            build_emergency_conservative_overlay(
                {"kind": "tail"},
                [{"direction": "tighten_interval", "value": 0.2}],
                expires_at="2026-06-25T12:00:00+00:00",
            )

        with self.assertRaisesRegex(CalibrationMaturityError, "canonical_probability"):
            build_emergency_conservative_overlay(
                {"kind": "tail"},
                [{"direction": "widen_interval", "canonical_probability": 0.5}],
                expires_at="2026-06-25T12:00:00+00:00",
            )

    def test_shared_reuse_temporal_safety_rejects_unsafe_cached_records(self):
        rejected = validate_shared_reuse_temporal_safety(
            {
                "temporal_eligibility_status": "passed",
                "max_underlying_source_timestamp": "2026-06-24T12:01:00+00:00",
            },
            consuming_forecast_timestamp="2026-06-24T12:00:00+00:00",
        )
        self.assertEqual(rejected["reuse_status"], "rejected")

        accepted = validate_shared_reuse_temporal_safety(
            {
                "temporal_eligibility_status": "passed",
                "max_underlying_source_timestamp": "2026-06-24T11:59:00+00:00",
            },
            consuming_forecast_timestamp="2026-06-24T12:00:00+00:00",
        )
        self.assertEqual(accepted["reuse_status"], "accepted")

    def test_optimization_maturity_gate_blocks_until_all_checks_pass_without_authority(self):
        blocked = optimization_maturity_gate(
            {
                "full_trace_completion": 1.0,
                "registry_coverage": "complete",
                "pointer_stability_window": 0,
                "catastrophic_tail_failures": 0,
                "all_active_lanes_have_component_diagnostics": True,
                "all_active_lanes_have_rollback_pointers": True,
            },
            {"min_stability_window": 2},
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["live_forecast_authority"])

        passed = optimization_maturity_gate(
            {
                "full_trace_completion": 1.0,
                "registry_coverage": "complete",
                "pointer_stability_window": 2,
                "catastrophic_tail_failures": 0,
                "all_active_lanes_have_component_diagnostics": True,
                "all_active_lanes_have_rollback_pointers": True,
            },
            {"min_stability_window": 2},
        )
        self.assertEqual(passed["status"], "passed")
        result_id = write_optimization_maturity_result(self.conn, passed)
        self.assertEqual(result_id, passed["maturity_result_id"])


if __name__ == "__main__":
    unittest.main()
