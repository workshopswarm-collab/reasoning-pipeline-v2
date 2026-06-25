import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.netting import (  # noqa: E402
    NO_LIVE_AUTHORITY,
    REPRESENTATIVE_SELECTOR,
    SCAE_CLUSTER_NETTING_BUNDLE_SCHEMA_VERSION,
    ScaeNettingError,
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
    ):
        return {
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


if __name__ == "__main__":
    unittest.main()
