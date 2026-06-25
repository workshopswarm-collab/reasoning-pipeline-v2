import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.missingness import (  # noqa: E402
    TEMPORAL_NO_LIVE_AUTHORITY,
    ScaeMissingnessError,
    build_temporal_missingness_candidate_bundle,
    build_temporal_missingness_candidate_slices,
    validate_temporal_missingness_candidate,
)
from scae.policy import ScaePolicyError, default_scae_policy, validate_scae_policy  # noqa: E402


class ScaeTemporalMissingnessTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def missingness(self, *, proof=True, direction="supports_no", mechanism="official-source-silence"):
        row = {
            "artifact_type": "missingness_signal_slice",
            "schema_version": "missingness-signal-slice/v1",
            "slice_id": "missingness-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "condition_scope": "unconditional",
            "source_ref": "source-1",
            "source_class": "official_or_primary",
            "source_family_id": "official-feed",
            "claim_family_id": "claim-family-1",
            "expected_source_class": "official_or_primary",
            "missingness_reason_code": "expected_source_absent_after_search",
            "absence_mechanism_family_id": mechanism,
            "explicit_mechanism_proof": proof,
            "missingness_mechanism_proof_status": "accepted" if proof else "missing",
            "signed_impact_direction": direction,
            "missingness_strength": "moderate",
        }
        if proof:
            row["missingness_mechanism_proof_ref"] = "mechanism-proof-1"
        return row

    def no_catalyst(self, *, mechanism="official-source-silence", hazard_family="continuous_arrival_hazard"):
        return {
            "slice_id": "no-catalyst-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "condition_scope": "unconditional",
            "source_ref": "source-1",
            "source_class": "official_or_primary",
            "source_family_id": "official-feed",
            "claim_family_id": "claim-family-1",
            "absence_mechanism_family_id": mechanism,
            "hazard_family": hazard_family,
            "hazard_schedule_ref": "hazard-schedule-1",
            "hazard_rate_per_day": 0.10,
            "market_priced_through_timestamp": "2026-06-24T00:00:00+00:00",
            "forecast_timestamp": "2026-06-25T00:00:00+00:00",
            "source_coverage_sufficient": True,
            "source_coverage_ref": "coverage-1",
            "signed_impact_direction": "supports_no",
        }

    def test_missingness_requires_explicit_mechanism_proof(self):
        result = build_temporal_missingness_candidate_slices(
            [self.missingness(proof=False)],
            policy=self.policy,
        )

        self.assertEqual(len(result.candidate_slices), 1)
        candidate = result.candidate_slices[0]
        self.assertEqual(candidate["candidate_status"], "rejected_missing_mechanism_proof")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])
        self.assertIn("explicit_mechanism_proof_required", candidate["rejection_reason_codes"])

    def test_proven_missingness_emits_bounded_candidate_only(self):
        candidate = build_temporal_missingness_candidate_slices(
            [self.missingness()],
            policy=self.policy,
        ).candidate_slices[0]

        self.assertEqual(candidate["candidate_status"], "accepted_missingness_candidate")
        self.assertEqual(candidate["ledger_input_authority"], TEMPORAL_NO_LIVE_AUTHORITY)
        self.assertLess(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["writes_scae_ledger"])
        self.assertFalse(candidate["writes_production_forecast"])
        self.assertFalse(candidate["live_forecast_authority"])
        validate_temporal_missingness_candidate(candidate)

    def test_no_catalyst_survival_requires_allowed_hazard_coverage_and_unpriced_interval(self):
        invalid_hazard = build_temporal_missingness_candidate_slices(
            no_catalyst_contexts=[self.no_catalyst(hazard_family="scheduled_point_deadline")],
            policy=self.policy,
        ).candidate_slices[0]
        self.assertEqual(invalid_hazard["candidate_status"], "rejected_no_catalyst_hazard_family")

        missing_coverage = self.no_catalyst()
        missing_coverage["source_coverage_sufficient"] = False
        missing_coverage["source_coverage_ref"] = None
        coverage_candidate = build_temporal_missingness_candidate_slices(
            no_catalyst_contexts=[missing_coverage],
            policy=self.policy,
        ).candidate_slices[0]
        self.assertEqual(coverage_candidate["candidate_status"], "rejected_no_catalyst_source_coverage")

        priced_interval = self.no_catalyst()
        priced_interval["forecast_timestamp"] = "2026-06-24T00:00:00+00:00"
        interval_candidate = build_temporal_missingness_candidate_slices(
            no_catalyst_contexts=[priced_interval],
            policy=self.policy,
        ).candidate_slices[0]
        self.assertEqual(interval_candidate["candidate_status"], "rejected_no_catalyst_unpriced_interval")

        accepted = build_temporal_missingness_candidate_slices(
            no_catalyst_contexts=[self.no_catalyst()],
            policy=self.policy,
        ).candidate_slices[0]
        self.assertEqual(accepted["candidate_status"], "accepted_no_catalyst_candidate")
        self.assertEqual(accepted["unpriced_elapsed_seconds"], 86400.0)
        self.assertLess(accepted["signed_log_odds_delta"], 0.0)

    def test_missingness_no_catalyst_same_mechanism_requires_distinct_proof(self):
        result = build_temporal_missingness_candidate_slices(
            [self.missingness(mechanism="same-absence-mechanism")],
            no_catalyst_contexts=[self.no_catalyst(mechanism="same-absence-mechanism")],
            policy=self.policy,
        )
        statuses = {candidate["candidate_kind"]: candidate["candidate_status"] for candidate in result.candidate_slices}

        self.assertEqual(statuses["explicit_mechanism_missingness"], "accepted_missingness_candidate")
        self.assertEqual(statuses["survival_no_catalyst"], "rejected_overlap_without_distinct_mechanism_proof")

    def test_distinct_mechanism_proof_allows_missingness_and_no_catalyst_candidates(self):
        no_catalyst = self.no_catalyst(mechanism="same-absence-mechanism")
        no_catalyst["distinct_absence_mechanism_proof_ref"] = "distinct-proof-1"
        no_catalyst["distinct_absence_mechanism_proof_status"] = "accepted"
        no_catalyst["distinct_absence_mechanism_family_id"] = "independent-arrival-process"

        result = build_temporal_missingness_candidate_slices(
            [self.missingness(mechanism="same-absence-mechanism")],
            no_catalyst_contexts=[no_catalyst],
            policy=self.policy,
        )
        statuses = {candidate["candidate_kind"]: candidate["candidate_status"] for candidate in result.candidate_slices}

        self.assertEqual(statuses["explicit_mechanism_missingness"], "accepted_missingness_candidate")
        self.assertEqual(statuses["survival_no_catalyst"], "accepted_no_catalyst_candidate")

    def test_bundle_is_diagnostic_candidate_only_and_has_no_probability_fields(self):
        bundle = build_temporal_missingness_candidate_bundle(
            [self.missingness()],
            no_catalyst_contexts=[self.no_catalyst(mechanism="independent-no-catalyst")],
            policy=self.policy,
        )

        self.assertEqual(bundle["authority"], TEMPORAL_NO_LIVE_AUTHORITY)
        self.assertFalse(bundle["writes_scae_ledger"])
        self.assertFalse(bundle["writes_production_forecast"])
        serialized = json.dumps(bundle, sort_keys=True)
        for forbidden_field in [
            "raw_ledger_probability",
            "post_ledger_probability",
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
            "forecast_probability",
        ]:
            self.assertNotIn(forbidden_field, serialized)

    def test_temporal_policy_validation_rejects_unsafe_shapes(self):
        validate_scae_policy(self.policy)

        unsafe_missingness = copy.deepcopy(self.policy)
        unsafe_missingness["temporal_missingness"]["missingness_requires_explicit_mechanism_proof"] = False
        with self.assertRaisesRegex(ScaePolicyError, "missingness_requires_explicit_mechanism_proof"):
            validate_scae_policy(unsafe_missingness)

        unsafe_double_count = copy.deepcopy(self.policy)
        unsafe_double_count["temporal_missingness"][
            "allow_missingness_no_catalyst_same_mechanism_double_count"
        ] = True
        with self.assertRaisesRegex(ScaePolicyError, "double count"):
            validate_scae_policy(unsafe_double_count)

        unsafe_candidate = build_temporal_missingness_candidate_slices([self.missingness()], policy=self.policy).candidate_slices[0]
        unsafe_candidate["canonical_probability"] = 0.5
        with self.assertRaisesRegex(ScaeMissingnessError, "forbidden"):
            validate_temporal_missingness_candidate(unsafe_candidate)


if __name__ == "__main__":
    unittest.main()
