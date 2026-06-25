import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.netting import (  # noqa: E402
    AMBIGUOUS_CLAIM_FAMILY_UNION_ID,
    CROSS_LEAF_REPRESENTATIVE_SELECTOR,
    NO_LIVE_AUTHORITY,
    REPRESENTATIVE_SELECTOR,
    SCAE_CLUSTER_NETTING_BUNDLE_SCHEMA_VERSION,
    SCAE_CROSS_LEAF_DEPENDENCE_BUNDLE_SCHEMA_VERSION,
    ScaeNettingError,
    build_cross_leaf_dependence_bundle,
    build_leaf_cluster_netting_bundle,
    build_leaf_cluster_netting_slices,
)
from scae.policy import default_scae_policy  # noqa: E402


class ScaeNettingTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def candidate(
        self,
        candidate_id,
        *,
        delta=0.18,
        quality=0.8,
        leaf_id="leaf-1",
        source_family_id="source-family-1",
        claim_family_id="claim-family-1",
        accepted=True,
        source_class="official_or_primary",
        mechanism_family_id=None,
        claim_family_status=None,
    ):
        candidate = {
            "artifact_type": "scae_log_odds_update_candidate_slice",
            "candidate_slice_id": candidate_id,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": leaf_id,
            "source_family_id": source_family_id,
            "claim_family_id": claim_family_id,
            "source_ref": f"source-{candidate_id}",
            "source_class": source_class,
            "evidence_ref": f"evidence-{candidate_id}",
            "signed_log_odds_delta": delta,
            "verified_quality_multiplier": quality,
            "accepted_for_ledger_input": accepted,
            "candidate_status": "accepted_candidate" if accepted else "rejected_quality_verification",
        }
        if mechanism_family_id is not None:
            candidate["mechanism_family_id"] = mechanism_family_id
        if claim_family_status is not None:
            candidate["claim_family_resolution_status"] = claim_family_status
        return candidate

    def test_repeated_same_claim_source_family_contributes_once_by_default(self):
        result = build_leaf_cluster_netting_slices(
            [
                self.candidate("candidate-a", delta=0.18, quality=0.8),
                self.candidate("candidate-b", delta=0.30, quality=0.8),
            ],
            policy=self.policy,
        )

        self.assertEqual(len(result.cluster_slices), 1)
        cluster = result.cluster_slices[0]
        self.assertEqual(cluster["positive_representative_candidate_ref"], "candidate-b")
        self.assertEqual(cluster["netted_signed_log_odds_delta"], 0.30)
        self.assertEqual(
            cluster["posterior_force_inputs"]["representative_candidate_refs"],
            ["candidate-b"],
        )
        self.assertEqual(
            cluster["posterior_force_inputs"]["non_representative_candidate_refs_excluded_from_force"],
            ["candidate-a"],
        )
        self.assertEqual(cluster["corroboration_metadata"]["same_claim_source_family_repeat_count"], 1)
        self.assertTrue(cluster["corroboration_metadata"]["separated_from_posterior_force"])

    def test_positive_and_negative_representatives_can_both_be_recorded(self):
        result = build_leaf_cluster_netting_slices(
            [
                self.candidate("candidate-positive", delta=0.25),
                self.candidate("candidate-negative", delta=-0.18),
            ],
            policy=self.policy,
        )

        cluster = result.cluster_slices[0]
        self.assertEqual(cluster["positive_representative_candidate_ref"], "candidate-positive")
        self.assertEqual(cluster["negative_representative_candidate_ref"], "candidate-negative")
        self.assertEqual(cluster["pre_cap_cluster_signed_log_odds_delta"], 0.07)
        self.assertEqual(cluster["netted_signed_log_odds_delta"], 0.07)
        self.assertTrue(cluster["contradiction_metadata"]["has_positive_and_negative_representatives"])

    def test_representative_selector_is_policy_defined_not_raw_max_absolute(self):
        result = build_leaf_cluster_netting_slices(
            [
                self.candidate("candidate-higher-quality", delta=0.20, quality=0.9),
                self.candidate("candidate-higher-delta", delta=0.30, quality=0.6),
            ],
            policy=self.policy,
        )

        cluster = result.cluster_slices[0]
        self.assertEqual(cluster["representative_selector"], REPRESENTATIVE_SELECTOR)
        self.assertEqual(cluster["positive_representative_candidate_ref"], "candidate-higher-quality")
        self.assertEqual(cluster["netted_signed_log_odds_delta"], 0.20)

    def test_distinct_claim_families_from_same_source_family_remain_separate(self):
        result = build_leaf_cluster_netting_slices(
            [
                self.candidate("candidate-claim-a", delta=0.18, claim_family_id="claim-family-a"),
                self.candidate("candidate-claim-b", delta=0.12, claim_family_id="claim-family-b"),
            ],
            policy=self.policy,
        )

        self.assertEqual(len(result.cluster_slices), 2)
        self.assertEqual(result.leaf_netting_summaries[0]["candidate_leaf_net_log_odds_delta"], 0.30)
        self.assertEqual(
            sorted(cluster["claim_family_id"] for cluster in result.cluster_slices),
            ["claim-family-a", "claim-family-b"],
        )

    def test_source_class_and_cluster_caps_are_candidate_only_with_no_probability_fields(self):
        policy = copy.deepcopy(self.policy)
        policy["cap_stack"]["per_cluster_log_odds_cap"] = 0.20
        policy["cap_stack"]["source_class_log_odds_caps"] = {"official_or_primary": 0.25}

        bundle = build_leaf_cluster_netting_bundle(
            [self.candidate("candidate-large", delta=0.32, quality=1.0)],
            policy=policy,
        )

        self.assertEqual(bundle["schema_version"], SCAE_CLUSTER_NETTING_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(bundle["authority"], NO_LIVE_AUTHORITY)
        self.assertFalse(bundle["writes_scae_ledger"])
        self.assertFalse(bundle["writes_production_forecast"])
        cluster = bundle["cluster_slices"][0]
        self.assertEqual(cluster["positive_representative_pre_source_cap_signed_log_odds_delta"], 0.32)
        self.assertEqual(cluster["positive_representative_signed_log_odds_delta"], 0.25)
        self.assertTrue(cluster["bounded_by_source_class_cap"])
        self.assertEqual(cluster["netted_signed_log_odds_delta"], 0.20)
        self.assertTrue(cluster["bounded_by_cluster_cap"])
        self.assertEqual(cluster["cap_application_scope"], "candidate_ledger_input_only")
        serialized = json.dumps(bundle, sort_keys=True)
        for forbidden_field in [
            "raw_ledger_probability",
            "post_ledger_probability",
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
        ]:
            self.assertNotIn(forbidden_field, serialized)

    def test_rejected_and_zero_delta_candidates_do_not_create_force_clusters(self):
        result = build_leaf_cluster_netting_slices(
            [
                self.candidate("candidate-rejected", delta=0.30, accepted=False),
                self.candidate("candidate-zero", delta=0.0),
            ],
            policy=self.policy,
        )

        self.assertEqual(result.cluster_slices, [])
        self.assertEqual(result.leaf_netting_summaries, [])
        self.assertEqual(result.excluded_candidate_refs, ["candidate-rejected"])
        self.assertEqual(result.zero_delta_candidate_refs, ["candidate-zero"])

    def test_missing_cluster_identity_fails_closed(self):
        candidate = self.candidate("candidate-missing-source-family")
        candidate.pop("source_family_id")

        with self.assertRaisesRegex(ScaeNettingError, "source_family_id"):
            build_leaf_cluster_netting_slices([candidate], policy=self.policy)

    def test_unsupported_representative_selector_fails_closed(self):
        policy = copy.deepcopy(self.policy)
        policy["cap_stack"]["representative_selector"] = "max_absolute_delta"

        with self.assertRaisesRegex(ScaeNettingError, "representative_selector"):
            build_leaf_cluster_netting_slices([self.candidate("candidate-a")], policy=policy)

    def test_same_claim_across_leaves_contributes_once_through_shared_claim_union(self):
        intra_leaf_bundle = build_leaf_cluster_netting_bundle(
            [
                self.candidate("candidate-leaf-a", delta=0.22, leaf_id="leaf-a"),
                self.candidate("candidate-leaf-b", delta=0.31, leaf_id="leaf-b"),
            ],
            policy=self.policy,
        )

        cross_leaf_bundle = build_cross_leaf_dependence_bundle(intra_leaf_bundle)

        self.assertEqual(
            cross_leaf_bundle["schema_version"],
            SCAE_CROSS_LEAF_DEPENDENCE_BUNDLE_SCHEMA_VERSION,
        )
        self.assertEqual(cross_leaf_bundle["authority"], NO_LIVE_AUTHORITY)
        self.assertFalse(cross_leaf_bundle["writes_scae_ledger"])
        self.assertFalse(cross_leaf_bundle["writes_production_forecast"])
        self.assertEqual(len(cross_leaf_bundle["cross_leaf_dependency_slices"]), 1)
        dependence = cross_leaf_bundle["cross_leaf_dependency_slices"][0]
        self.assertEqual(dependence["feature_id"], "SCAE-006")
        self.assertEqual(dependence["cross_leaf_representative_selector"], CROSS_LEAF_REPRESENTATIVE_SELECTOR)
        self.assertTrue(dependence["same_claim_union_applied"])
        self.assertEqual(dependence["raw_additive_signed_log_odds_delta"], 0.53)
        self.assertEqual(dependence["cross_leaf_guarded_signed_log_odds_delta"], 0.31)
        self.assertEqual(dependence["prevented_duplicate_or_dependent_signed_log_odds_delta"], 0.22)
        self.assertEqual(
            dependence["posterior_force_inputs"]["non_representative_cluster_refs_excluded_from_force"],
            [intra_leaf_bundle["cluster_slices"][0]["cluster_slice_id"]],
        )
        self.assertEqual(
            cross_leaf_bundle["cross_leaf_summary"]["cross_leaf_guarded_signed_log_odds_delta"],
            0.31,
        )

    def test_ambiguous_claim_family_defaults_conservative_not_independent(self):
        intra_leaf_bundle = build_leaf_cluster_netting_bundle(
            [
                self.candidate(
                    "candidate-ambiguous-a",
                    delta=0.20,
                    leaf_id="leaf-a",
                    claim_family_id="parser-proposed-family-a",
                    claim_family_status="unknown_not_counted",
                ),
                self.candidate(
                    "candidate-ambiguous-b",
                    delta=0.16,
                    leaf_id="leaf-b",
                    source_family_id="source-family-2",
                    claim_family_id="parser-proposed-family-b",
                    claim_family_status="spanless_model_proposal",
                ),
            ],
            policy=self.policy,
        )

        dependence = build_cross_leaf_dependence_bundle(intra_leaf_bundle)["cross_leaf_dependency_slices"][0]

        self.assertEqual(dependence["dependence_group_type"], "ambiguous_claim_family")
        self.assertEqual(dependence["dependence_group_id"], AMBIGUOUS_CLAIM_FAMILY_UNION_ID)
        self.assertTrue(dependence["ambiguous_claim_family_conservative_union_applied"])
        self.assertEqual(dependence["independent_corroboration_status"], "blocked_ambiguous_claim_family")
        self.assertEqual(dependence["raw_additive_signed_log_odds_delta"], 0.36)
        self.assertEqual(dependence["cross_leaf_guarded_signed_log_odds_delta"], 0.20)

    def test_mechanism_family_tags_are_diagnostic_and_cannot_increase_strength(self):
        intra_leaf_bundle = build_leaf_cluster_netting_bundle(
            [
                self.candidate(
                    "candidate-mechanism-a",
                    delta=0.12,
                    leaf_id="leaf-a",
                    claim_family_id="claim-family-a",
                    mechanism_family_id="official-source-silence",
                ),
                self.candidate(
                    "candidate-mechanism-b",
                    delta=0.14,
                    leaf_id="leaf-b",
                    claim_family_id="claim-family-b",
                    mechanism_family_id="official-source-silence",
                ),
            ],
            policy=self.policy,
        )

        cross_leaf_bundle = build_cross_leaf_dependence_bundle(intra_leaf_bundle)

        diagnostics = cross_leaf_bundle["mechanism_family_diagnostics"]
        self.assertEqual(len(diagnostics), 1)
        diagnostic = diagnostics[0]
        self.assertEqual(diagnostic["mechanism_family_id"], "official-source-silence")
        self.assertTrue(diagnostic["diagnostic_dependence_only"])
        self.assertFalse(diagnostic["can_increase_evidence_strength"])
        self.assertEqual(diagnostic["signed_log_odds_delta_added_by_mechanism_family"], 0.0)
        self.assertEqual(diagnostic["downstream_effect_scope"], "dependence_or_interval_only")

    def test_cross_leaf_bundle_has_no_probability_or_forecast_authority_fields(self):
        intra_leaf_bundle = build_leaf_cluster_netting_bundle(
            [
                self.candidate("candidate-leaf-a", delta=0.22, leaf_id="leaf-a"),
                self.candidate("candidate-leaf-b", delta=-0.13, leaf_id="leaf-b"),
            ],
            policy=self.policy,
        )

        cross_leaf_bundle = build_cross_leaf_dependence_bundle(intra_leaf_bundle)

        serialized = json.dumps(cross_leaf_bundle, sort_keys=True)
        for forbidden_field in [
            "raw_ledger_probability",
            "post_ledger_probability",
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
        ]:
            self.assertNotIn(forbidden_field, serialized)


if __name__ == "__main__":
    unittest.main()
