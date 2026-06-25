import copy
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.policy import (
    ScaePolicyError,
    default_scae_policy,
    resolve_probability_taxonomy,
    validate_decision_authority,
    validate_probability_taxonomy,
    validate_scae_policy,
)


class ScaePolicyTest(unittest.TestCase):
    def test_default_policy_uses_identity_post_ledger_calibration(self):
        policy = default_scae_policy()

        self.assertEqual(policy["post_ledger_calibration"]["default_method"], "identity")
        self.assertEqual(policy["authority_boundary"]["live_numeric_forecast_authority"], "scae")
        self.assertFalse(policy["authority_boundary"]["decision_may_replace_probability"])
        validate_scae_policy(policy)

    def test_calibration_debt_active_uses_debt_adjusted_production_probability(self):
        fields = resolve_probability_taxonomy(
            raw_ledger_probability=0.58,
            post_ledger_probability=0.61,
            debt_adjusted_probability=0.55,
            calibration_debt_active=True,
        )

        self.assertEqual(fields["production_forecast_prob"], 0.55)
        self.assertEqual(fields["canonical_probability"], 0.55)

    def test_calibration_debt_cleared_uses_post_ledger_production_probability(self):
        fields = resolve_probability_taxonomy(
            raw_ledger_probability=0.58,
            post_ledger_probability=0.61,
            debt_adjusted_probability=0.55,
            calibration_debt_active=False,
        )

        self.assertEqual(fields["production_forecast_prob"], 0.61)
        self.assertEqual(fields["canonical_probability"], 0.61)

    def test_canonical_probability_must_alias_production_probability(self):
        taxonomy = resolve_probability_taxonomy(
            raw_ledger_probability=0.50,
            post_ledger_probability=0.52,
            debt_adjusted_probability=0.51,
            calibration_debt_active=True,
        )
        taxonomy["canonical_probability"] = 0.52

        with self.assertRaisesRegex(ScaePolicyError, "canonical_probability"):
            validate_probability_taxonomy(taxonomy, calibration_debt_active=True)

    def test_decision_cannot_upgrade_scae_validity_or_execution_authority(self):
        with self.assertRaisesRegex(ScaePolicyError, "cannot upgrade"):
            validate_decision_authority(
                scae_forecast_validity_status="invalid_for_forecast",
                decision_forecast_validity_status="valid_for_forecast",
                execution_authority_status="forbidden",
            )

        with self.assertRaisesRegex(ScaePolicyError, "execution authority"):
            validate_decision_authority(
                scae_forecast_validity_status="valid_for_forecast_watch_only",
                decision_forecast_validity_status="valid_for_forecast_watch_only",
                execution_authority_status="normal_execution_allowed",
            )

        constrained = validate_decision_authority(
            scae_forecast_validity_status="valid_for_forecast",
            decision_forecast_validity_status="valid_for_forecast_watch_only",
            execution_authority_status="watch_only",
        )
        self.assertEqual(constrained["forecast_validity_status"], "valid_for_forecast_watch_only")
        self.assertEqual(constrained["execution_authority_status"], "watch_only")

    def test_policy_schema_validation_rejects_unsafe_authority_and_debt_shapes(self):
        policy = default_scae_policy()

        unsafe_authority = copy.deepcopy(policy)
        unsafe_authority["authority_boundary"]["synthesis_may_author_probability"] = True
        with self.assertRaisesRegex(ScaePolicyError, "synthesis_may_author_probability"):
            validate_scae_policy(unsafe_authority)

        unsafe_calibration = copy.deepcopy(policy)
        unsafe_calibration["post_ledger_calibration"]["default_method"] = "beta"
        with self.assertRaisesRegex(ScaePolicyError, "identity"):
            validate_scae_policy(unsafe_calibration)

        unsafe_debt = copy.deepcopy(policy)
        unsafe_debt["calibration_debt"]["active"] = "true"
        with self.assertRaisesRegex(ScaePolicyError, "active must be a boolean"):
            validate_scae_policy(unsafe_debt)

        unsafe_family = copy.deepcopy(policy)
        unsafe_family["family_diagnostics"]["allow_sibling_softmax_reallocation"] = True
        with self.assertRaisesRegex(ScaePolicyError, "allow_sibling_softmax_reallocation"):
            validate_scae_policy(unsafe_family)

        unsafe_guard = copy.deepcopy(policy)
        unsafe_guard["cap_stack"]["correlated_quality_guard"]["multiplier_ceiling"] = 1.25
        with self.assertRaisesRegex(ScaePolicyError, "correlated_quality_guard"):
            validate_scae_policy(unsafe_guard)


if __name__ == "__main__":
    unittest.main()
