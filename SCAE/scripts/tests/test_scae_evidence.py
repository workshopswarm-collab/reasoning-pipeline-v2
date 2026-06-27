import copy
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.evidence import (  # noqa: E402
    NO_LIVE_AUTHORITY,
    ScaeEvidenceDeltaError,
    build_evidence_delta_candidate_bundle,
    build_evidence_delta_candidate_slices,
)
from scae.policy import default_scae_policy, validate_scae_policy  # noqa: E402


class ScaeEvidenceDeltaTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def classification(
        self,
        *,
        direction="supports_yes",
        strength="strong",
        slice_id="classification-slice-1",
        confidence="high",
        quality="high",
        acceptance_status="accepted_for_verification",
        delta_eligible=None,
    ):
        if delta_eligible is None:
            delta_eligible = direction in {"supports_yes", "supports_no", "mixed"}
        return {
            "slice_id": slice_id,
            "classification_id": f"classification-{slice_id}",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "condition_scope": "unconditional",
            "evidence_ref": f"evidence-{slice_id}",
            "source_ref": "source-1",
            "source_class": "official_or_primary",
            "source_family_id": "source-family-1",
            "claim_family_id": "claim-family-1",
            "retrieval_breadth_coverage_ref": "coverage-1",
            "research_sufficiency_certificate_ref": "certificate-1",
            "impact_direction": direction,
            "evidence_strength": strength,
            "classification_confidence": confidence,
            "classification_quality": quality,
            "classification_acceptance_status": acceptance_status,
            "evidence_delta_eligible_for_scae": delta_eligible,
            "ledger_ready": acceptance_status == "accepted_for_verification" and delta_eligible is True,
            "included_for_scae": acceptance_status == "accepted_for_verification" and delta_eligible is True,
        }

    def direction(self, classification, *, verified_direction=None, accepted=True):
        return {
            "verification_slice_id": f"direction-{classification['slice_id']}",
            "classification_slice_ref": classification["slice_id"],
            "classification_id": classification["classification_id"],
            "verified_direction": verified_direction or classification["impact_direction"],
            "verification_status": "accepted" if accepted else "quarantined",
            "accepted_for_scae": accepted,
        }

    def quality(self, classification, *, multiplier=0.8, accepted=True):
        return {
            "quality_verification_slice_id": f"quality-{classification['slice_id']}",
            "classification_slice_ref": classification["slice_id"],
            "classification_id": classification["classification_id"],
            "accepted_quality_fields": {
                "source_authority": "high",
                "directness": "direct",
                "recency": "fresh",
                "specificity": "specific",
                "classification_confidence": "high",
                "classification_quality": "high",
            },
            "quality_correlation_groups": ["source_family:source-family-1", "claim_family:claim-family-1"],
            "raw_quality_multiplier": multiplier,
            "final_quality_multiplier": multiplier,
            "quality_status": "accepted" if accepted else "excluded",
            "accepted_for_scae": accepted,
        }

    def build_one(self, classification, direction=None, quality=None, market_assimilation_contexts=None):
        result = build_evidence_delta_candidate_slices(
            {"classification_slices": [classification]},
            direction_verification_slices=[direction or self.direction(classification)],
            quality_verification_slices=[quality or self.quality(classification)],
            market_assimilation_contexts=market_assimilation_contexts,
            policy=self.policy,
        )
        self.assertEqual(len(result.candidate_slices), 1)
        return result.candidate_slices[0]

    def test_verified_direction_strength_and_quality_map_to_bounded_candidate(self):
        classification = self.classification(strength="strong")

        candidate = self.build_one(classification, quality=self.quality(classification, multiplier=1.0))

        self.assertEqual(candidate["candidate_status"], "accepted_candidate")
        self.assertEqual(candidate["strength_log_odds"], self.policy["evidence_delta_mapping"]["strength_log_odds"]["strong"])
        self.assertEqual(candidate["pre_cap_signed_log_odds_delta"], 0.35)
        self.assertEqual(candidate["signed_log_odds_delta"], self.policy["cap_stack"]["per_update_log_odds_cap"])
        self.assertFalse(candidate["bounded_by_per_update_cap"])
        self.assertFalse(candidate["correlated_quality_guard_applied"])
        self.assertEqual(candidate["correlated_quality_guard_status"], "passed_no_repeated_quality_correlation_group")
        self.assertEqual(candidate["quality_multiplier_after_correlated_guard"], 1.0)
        self.assertEqual(candidate["phase9_confidence_discount"], 1.0)
        self.assertEqual(candidate["phase9_quality_discount"], 1.0)
        self.assertEqual(candidate["effective_quality_multiplier_after_phase9_discounts"], 1.0)
        self.assertEqual(candidate["cap_stack"]["applied_stage"], "candidate_per_update_cap_only")
        self.assertEqual(
            candidate["cap_stack"]["per_cluster_log_odds_cap"],
            self.policy["cap_stack"]["per_cluster_log_odds_cap"],
        )
        self.assertIn("per_branch_log_odds_cap", candidate["cap_stack"]["later_cap_stages_not_applied"])
        self.assertEqual(candidate["ledger_input_authority"], NO_LIVE_AUTHORITY)
        self.assertFalse(candidate["writes_scae_ledger"])
        self.assertFalse(candidate["writes_production_forecast"])

    def test_runtime_sidecar_materialized_row_creates_candidate_with_no_probability_authority(self):
        classification = self.classification(strength="moderate")
        classification["sidecar_id"] = "researcher-sidecar-runtime-1"
        classification["sidecar_digest"] = "sha256:" + "5" * 64
        classification["runtime_bundle_ref"] = "artifact:runtime-bundle-1"

        candidate = self.build_one(classification, quality=self.quality(classification, multiplier=1.0))

        self.assertEqual(candidate["candidate_status"], "accepted_candidate")
        self.assertEqual(candidate["sidecar_id"], "researcher-sidecar-runtime-1")
        self.assertEqual(candidate["sidecar_digest"], "sha256:" + "5" * 64)
        self.assertEqual(candidate["runtime_bundle_ref"], "artifact:runtime-bundle-1")
        self.assertEqual(candidate["ledger_input_authority"], NO_LIVE_AUTHORITY)
        self.assertFalse(candidate["live_forecast_authority"])
        self.assertFalse(candidate["writes_production_forecast"])

    def test_correlated_quality_guard_lowers_repeated_group_multiplier(self):
        first = self.classification(strength="strong", slice_id="classification-slice-1")
        second = self.classification(strength="strong", slice_id="classification-slice-2")

        result = build_evidence_delta_candidate_slices(
            {"classification_slices": [first, second]},
            direction_verification_slices=[self.direction(first), self.direction(second)],
            quality_verification_slices=[
                self.quality(first, multiplier=1.0),
                self.quality(second, multiplier=1.0),
            ],
            policy=self.policy,
        )

        ceiling = self.policy["cap_stack"]["correlated_quality_guard"]["multiplier_ceiling"]
        by_classification = {candidate["classification_slice_ref"]: candidate for candidate in result.candidate_slices}
        for classification in (first, second):
            candidate = by_classification[classification["slice_id"]]
            self.assertEqual(candidate["candidate_status"], "accepted_candidate")
            self.assertEqual(candidate["quality_multiplier_before_correlated_guard"], 1.0)
            self.assertEqual(candidate["quality_multiplier_after_correlated_guard"], ceiling)
            self.assertTrue(candidate["correlated_quality_guard_applied"])
            self.assertEqual(candidate["correlated_quality_guard_status"], "capped_repeated_quality_correlation_group")
            self.assertIn("source_family:source-family-1", candidate["correlated_quality_guard_repeated_groups"])
            self.assertEqual(candidate["correlated_quality_group_counts"]["source_family:source-family-1"], 2)
            self.assertEqual(candidate["pre_cap_signed_log_odds_delta"], round(0.35 * ceiling, 9))
            self.assertFalse(candidate["bounded_by_per_update_cap"])

    def test_verified_direction_controls_sign_after_claimed_impact(self):
        classification = self.classification(direction="supports_yes", strength="strong")
        direction = self.direction(classification, verified_direction="supports_no", accepted=True)

        candidate = self.build_one(classification, direction=direction, quality=self.quality(classification, multiplier=1.0))

        self.assertEqual(candidate["verified_direction"], "supports_no")
        self.assertEqual(candidate["direction_multiplier"], -1.0)
        self.assertLess(candidate["signed_log_odds_delta"], 0.0)

    def test_unverified_non_neutral_row_is_rejected_without_force(self):
        classification = self.classification(direction="supports_yes")
        direction = self.direction(classification, verified_direction="ambiguous", accepted=False)

        candidate = self.build_one(classification, direction=direction)

        self.assertEqual(candidate["candidate_status"], "rejected_direction_verification")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])
        self.assertIn("non_neutral_direction_not_verified", candidate["rejection_reason_codes"])

    def test_missing_direction_verification_fails_closed(self):
        classification = self.classification(direction="supports_yes")

        with self.assertRaisesRegex(ScaeEvidenceDeltaError, "missing direction verification"):
            build_evidence_delta_candidate_slices(
                {"classification_slices": [classification]},
                direction_verification_slices=[],
                quality_verification_slices=[self.quality(classification)],
                policy=self.policy,
            )

    def test_missing_quality_verification_fails_closed(self):
        classification = self.classification(direction="supports_yes")

        with self.assertRaisesRegex(ScaeEvidenceDeltaError, "missing quality verification"):
            build_evidence_delta_candidate_slices(
                {"classification_slices": [classification]},
                direction_verification_slices=[self.direction(classification)],
                quality_verification_slices=[],
                policy=self.policy,
            )

    def test_neutral_verified_row_is_zero_delta_candidate(self):
        classification = self.classification(
            direction="neutral",
            strength="none",
            acceptance_status="non_scoreable",
            delta_eligible=False,
        )

        candidate = self.build_one(classification)

        self.assertEqual(candidate["candidate_status"], "no_delta_classification")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])

    def test_market_assimilation_zero_multiplier_preserves_zero_delta_context(self):
        classification = self.classification(direction="supports_yes", strength="strong")

        candidate = self.build_one(
            classification,
            market_assimilation_contexts=[
                {
                    "evidence_ref": classification["evidence_ref"],
                    "suggested_signed_delta_multiplier": 0.0,
                    "reason_codes": ["base_rate_overlap_zero_signed_delta"],
                }
            ],
        )

        self.assertEqual(candidate["candidate_status"], "zero_market_assimilation_delta")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])
        self.assertIn("base_rate_overlap_zero_signed_delta", candidate["market_assimilation_reason_codes"])

    def test_quality_verification_rejection_yields_rejected_candidate(self):
        classification = self.classification(direction="supports_yes")

        candidate = self.build_one(classification, quality=self.quality(classification, accepted=False))

        self.assertEqual(candidate["candidate_status"], "rejected_quality_verification")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])

    def test_medium_confidence_and_quality_apply_phase9_discounts(self):
        classification = self.classification(confidence="medium", quality="medium")
        quality = self.quality(classification, multiplier=1.0)
        quality["accepted_quality_fields"]["classification_confidence"] = "medium"
        quality["accepted_quality_fields"]["classification_quality"] = "medium"

        candidate = self.build_one(classification, quality=quality)

        self.assertEqual(candidate["candidate_status"], "accepted_candidate")
        self.assertEqual(candidate["phase9_confidence_discount"], 0.6)
        self.assertEqual(candidate["phase9_quality_discount"], 0.7)
        self.assertEqual(candidate["pre_cap_signed_log_odds_delta"], 0.147)

    def test_low_confidence_or_quality_is_not_scoreable(self):
        classification = self.classification(confidence="low", quality="high")
        quality = self.quality(classification, multiplier=1.0)
        quality["accepted_quality_fields"]["classification_confidence"] = "low"

        candidate = self.build_one(classification, quality=quality)

        self.assertEqual(candidate["candidate_status"], "rejected_low_certainty_or_quality")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])

    def test_mixed_classification_becomes_branch_netting_candidate_only(self):
        classification = self.classification(direction="mixed")
        classification["supporting_evidence_refs"] = ["evidence-support"]
        classification["opposing_evidence_refs"] = ["evidence-oppose"]
        direction = self.direction(classification, verified_direction="mixed", accepted=True)

        candidate = self.build_one(classification, direction=direction, quality=self.quality(classification, multiplier=1.0))

        self.assertEqual(candidate["candidate_status"], "mixed_branch_netting_candidate")
        self.assertTrue(candidate["requires_branch_netting"])
        self.assertFalse(candidate["direct_single_delta_eligible"])
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])

    def test_irrelevant_or_insufficient_rows_are_no_delta_watch_only(self):
        classification = self.classification(
            direction="irrelevant",
            strength="none",
            acceptance_status="non_scoreable",
            delta_eligible=False,
        )
        direction = self.direction(classification, verified_direction="irrelevant", accepted=True)

        candidate = self.build_one(classification, direction=direction, quality=self.quality(classification, accepted=False))

        self.assertEqual(candidate["candidate_status"], "no_delta_classification")
        self.assertEqual(candidate["signed_log_odds_delta"], 0.0)
        self.assertFalse(candidate["accepted_for_ledger_input"])

    def test_bundle_is_candidate_only_and_has_no_probability_fields(self):
        classification = self.classification(direction="supports_yes", strength="weak")

        bundle = build_evidence_delta_candidate_bundle(
            {"classification_slices": [classification]},
            direction_verification_slices=[self.direction(classification)],
            quality_verification_slices=[self.quality(classification)],
            policy=self.policy,
        )

        self.assertEqual(bundle["authority"], NO_LIVE_AUTHORITY)
        self.assertFalse(bundle["writes_scae_ledger"])
        self.assertFalse(bundle["writes_production_forecast"])
        serialized = repr(bundle)
        for forbidden_field in [
            "raw_ledger_probability",
            "post_ledger_probability",
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
        ]:
            self.assertNotIn(forbidden_field, serialized)

    def test_policy_schema_accepts_scae003_delta_mapping(self):
        validate_scae_policy(self.policy)

        unsafe = copy.deepcopy(self.policy)
        unsafe["evidence_delta_mapping"]["direction_multipliers"]["supports_no"] = 1.0
        with self.assertRaisesRegex(Exception, "direction_multipliers"):
            validate_scae_policy(unsafe)


if __name__ == "__main__":
    unittest.main()
