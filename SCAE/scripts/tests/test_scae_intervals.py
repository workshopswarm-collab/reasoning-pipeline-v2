import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.intervals import (  # noqa: E402
    INTERVAL_COVERAGE_TARGET,
    LOGIT_UNCERTAINTY_WIDTH_VERSION,
    PRE_DEBT_LEDGER_AUTHORITY,
    SCAE_LOGIT_UNCERTAINTY_INTERVAL_SCHEMA_VERSION,
    SCAE_PRE_DEBT_LEDGER_OUTPUT_SCHEMA_VERSION,
    ScaeIntervalError,
    build_logit_uncertainty_interval,
    build_pre_debt_ledger_output,
)
from scae.policy import default_scae_policy  # noqa: E402
from scae.prior import logit, sigmoid  # noqa: E402


class ScaeIntervalTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()
        self.epsilon = self.policy["prior_reliability"]["epsilon"]

    def prior_context(self, probability=0.55):
        return {
            "prior_context_id": "prior-context:case-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "adjusted_prior_probability": probability,
            "adjusted_prior_log_odds": logit(probability, self.epsilon),
        }

    def evidence_delta(self, delta, *, accepted=True, candidate_id="candidate-1"):
        return {
            "artifact_type": "scae_log_odds_update_candidate_slice",
            "schema_version": "scae-log-odds-update-candidate-slice/v1",
            "feature_id": "SCAE-004",
            "candidate_slice_id": candidate_id,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "signed_log_odds_delta": delta,
            "accepted_for_ledger_input": accepted,
            "ledger_input_authority": "candidate_ledger_input_only_no_live_forecast_authority",
        }

    def branch_delta(self, delta, *, accepted=True, slice_id="branch-subledger:1"):
        return {
            "artifact_type": "scae_branch_subledger_slice",
            "schema_version": "scae-branch-subledger-slice/v1",
            "feature_id": "SCAE-007",
            "branch_subledger_slice_id": slice_id,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "parent_branch_id": "branch-1",
            "branch_subledger_signed_log_odds_delta": delta,
            "accepted_for_candidate_ledger_input": accepted,
            "ledger_input_authority": "candidate_ledger_input_only_no_live_forecast_authority",
        }

    def conditional_summary(self, probability):
        return {
            "artifact_type": "scae_conditional_branch_summary",
            "schema_version": "scae-conditional-branch-summary/v1",
            "feature_id": "SCAE-010",
            "summary_id": "conditional-summary:1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "conditional_recombination_status": "built",
            "conditional_recombined_probability_candidate": probability,
            "ledger_input_authority": "conditional_math_candidate_only_no_live_forecast_authority",
        }

    def test_identity_calibration_preserves_raw_probability(self):
        prior = self.prior_context(0.55)
        output = build_pre_debt_ledger_output(
            prior,
            evidence_delta_slices=[self.evidence_delta(0.12)],
            branch_subledger_slices=[self.branch_delta(-0.04)],
            policy=self.policy,
        )

        posterior_log_odds = round(prior["adjusted_prior_log_odds"] + 0.08, 9)
        expected_probability = round(sigmoid(posterior_log_odds), 9)

        self.assertEqual(output["schema_version"], SCAE_PRE_DEBT_LEDGER_OUTPUT_SCHEMA_VERSION)
        self.assertEqual(output["authority"], PRE_DEBT_LEDGER_AUTHORITY)
        self.assertEqual(output["raw_ledger_probability"], expected_probability)
        self.assertEqual(output["post_ledger_probability"], expected_probability)
        self.assertEqual(output["calibration_context"]["post_ledger_calibration_method"], "identity")
        self.assertFalse(output["calibration_context"]["non_identity_calibration_applied"])
        self.assertFalse(output["writes_production_forecast"])
        self.assertFalse(output["writes_persistence"])

        serialized = json.dumps(output, sort_keys=True)
        for forbidden_field in [
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
            "forecast_validity_status",
            "execution_authority_status",
        ]:
            self.assertNotIn(forbidden_field, serialized)

    def test_interval_widens_from_retrieval_and_dependence_penalties(self):
        narrow = build_logit_uncertainty_interval(post_logit=logit(0.50, self.epsilon), policy=self.policy)
        wider = build_logit_uncertainty_interval(
            post_logit=logit(0.50, self.epsilon),
            width_components=[
                {
                    "component_id": "retrieval-quality:leaf-1",
                    "component_type": "retrieval_quality",
                    "half_width_logit": 0.20,
                    "reason_codes": ["low_retrieval_quality"],
                    "source_refs": ["ret-coverage:leaf-1"],
                },
                {
                    "component_id": "dependence-family:mechanism-1",
                    "component_type": "dependence_penalty",
                    "half_width_logit": 0.15,
                    "reason_codes": ["same_mechanism_distinct_claims"],
                    "source_refs": ["scae-cross-leaf:1"],
                },
            ],
            policy=self.policy,
        )

        narrow_span = narrow["upper_probability"] - narrow["lower_probability"]
        wider_span = wider["upper_probability"] - wider["lower_probability"]
        self.assertEqual(wider["schema_version"], SCAE_LOGIT_UNCERTAINTY_INTERVAL_SCHEMA_VERSION)
        self.assertEqual(wider["interval_width_version"], LOGIT_UNCERTAINTY_WIDTH_VERSION)
        self.assertEqual(wider["coverage_target"], INTERVAL_COVERAGE_TARGET)
        self.assertEqual(wider["total_half_width_logit"], 0.35)
        self.assertGreater(wider_span, narrow_span)
        reason_codes = {
            code
            for component in wider["width_components"]
            for code in component["reason_codes"]
        }
        self.assertIn("low_retrieval_quality", reason_codes)
        self.assertIn("same_mechanism_distinct_claims", reason_codes)
        self.assertTrue(all(component["can_tighten_interval"] is False for component in wider["width_components"]))

    def test_total_cap_bounds_probability_fields_and_records_cap_stack(self):
        policy = default_scae_policy()
        policy["cap_stack"]["total_evidence_log_odds_cap"] = 0.50
        output = build_pre_debt_ledger_output(
            self.prior_context(0.50),
            evidence_delta_slices=[
                self.evidence_delta(0.60, candidate_id="candidate-large"),
                self.evidence_delta(0.80, accepted=False, candidate_id="candidate-rejected"),
            ],
            branch_subledger_slices=[self.branch_delta(0.40)],
            width_components=[{"component_id": "debug-width", "half_width_logit": 0.25}],
            policy=policy,
        )

        self.assertEqual(output["pre_cap_total_evidence_log_odds_delta"], 1.0)
        self.assertEqual(output["total_evidence_log_odds_delta"], 0.5)
        self.assertTrue(output["bounded_by_total_evidence_cap"])
        self.assertEqual(output["cap_stack_snapshot"]["total_evidence_log_odds_cap"], 0.5)
        self.assertEqual(output["excluded_delta_input_refs"]["evidence"], ["candidate-rejected"])
        for field_name in ("raw_ledger_probability", "post_ledger_probability"):
            self.assertGreaterEqual(output[field_name], 0.0)
            self.assertLessEqual(output[field_name], 1.0)
        interval = output["interval"]
        self.assertGreaterEqual(interval["lower_probability"], 0.0)
        self.assertLessEqual(interval["upper_probability"], 1.0)

    def test_conditional_candidate_can_supply_pre_debt_delta_without_production_authority(self):
        prior = self.prior_context(0.50)
        output = build_pre_debt_ledger_output(
            prior,
            conditional_delta_slices=[self.conditional_summary(0.60)],
            policy=self.policy,
        )

        expected_delta = round(logit(0.60, self.epsilon) - prior["adjusted_prior_log_odds"], 9)
        self.assertEqual(output["conditional_signed_log_odds_delta"], expected_delta)
        self.assertEqual(
            output["accepted_delta_inputs"][0]["delta_derivation"],
            "conditional_probability_candidate_minus_adjusted_prior",
        )
        self.assertFalse(output["live_forecast_authority"])

    def test_non_identity_post_ledger_calibration_fails_closed(self):
        policy = default_scae_policy()
        policy["post_ledger_calibration"]["default_method"] = "beta"

        with self.assertRaisesRegex(ScaeIntervalError, "identity"):
            build_pre_debt_ledger_output(self.prior_context(0.50), policy=policy)


if __name__ == "__main__":
    unittest.main()
