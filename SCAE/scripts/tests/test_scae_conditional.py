import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.conditional import (  # noqa: E402
    NO_LIVE_AUTHORITY,
    SCAE_CONDITIONAL_BRANCH_BUNDLE_SCHEMA_VERSION,
    ScaeConditionalBranchError,
    build_conditional_branch_recombination_bundle,
)
from scae.policy import default_scae_policy  # noqa: E402
from scae.prior import logit, sigmoid  # noqa: E402


class ScaeConditionalBranchTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def branch_slice(
        self,
        branch_id,
        leaf_id,
        *,
        delta,
        prior_probability,
        selected_market_prior_used=False,
    ):
        return {
            "artifact_type": "scae_branch_subledger_slice",
            "schema_version": "scae-branch-subledger-slice/v1",
            "feature_id": "SCAE-007",
            "branch_subledger_slice_id": f"branch-subledger:{branch_id}",
            "parent_branch_id": branch_id,
            "leaf_ids": [leaf_id],
            "branch_metadata": {
                "conditional_prior_probability": prior_probability,
                "conditional_prior_source": f"conditional-prior-source:{branch_id}",
                "branch_prior_derivation_method": "qdt_condition_scoped_prior_fixture",
                "branch_prior_source_ref": f"prior-ref:{branch_id}",
                "selected_market_prior_used_in_branch": selected_market_prior_used,
            },
            "branch_subledger_signed_log_odds_delta": delta,
            "accepted_for_candidate_ledger_input": True,
            "ledger_input_authority": "candidate_ledger_input_only_no_live_forecast_authority",
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
        }

    def contract(self, *, edge_status="validated_strict_precedence_anchor", condition_scoped_leaf_ids=None):
        if condition_scoped_leaf_ids is None:
            condition_scoped_leaf_ids = ["leaf-up", "leaf-not-up"]
        return {
            "schema_version": "amrg-anchor-dependency-contract/v1",
            "anchor_dependency_contract_id": "anchor-contract:edge-1",
            "edge_id": "edge-1",
            "edge_status": edge_status,
            "conditional_branch_group_id": "conditional-branch-group:edge-1",
            "anchor_mode": "anchor_required",
            "condition_scoped_leaf_ids": condition_scoped_leaf_ids,
            "fallback_policy": {
                "fallback_policy_id": "fallback:edge-1",
                "fallback_mode": "use_unconditional_fallback_leaf",
                "fallback_leaf_ids": ["leaf-fallback"],
                "fallback_reason_codes": ["qdt_anchor_fallback_policy"],
            },
            "max_anchor_repair_attempts": 1,
            "max_anchor_repair_wall_clock_seconds": 60,
            "repair_exhaustion_policy": "fail_dispatch_preparation",
        }

    def qdt(self, *, contract=None, up_scope="target_given_upstream", not_up_scope="target_given_not_upstream"):
        return {
            "artifact_type": "question_decomposition",
            "schema_version": "question-decomposition/v1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "branches": [
                {"branch_id": "branch-up"},
                {"branch_id": "branch-not-up"},
                {"branch_id": "branch-fallback"},
            ],
            "required_leaf_questions": [
                {"leaf_id": "leaf-up", "parent_branch_id": "branch-up", "leaf_condition_scope": up_scope},
                {
                    "leaf_id": "leaf-not-up",
                    "parent_branch_id": "branch-not-up",
                    "leaf_condition_scope": not_up_scope,
                },
                {"leaf_id": "leaf-fallback", "parent_branch_id": "branch-fallback", "leaf_condition_scope": "unconditional"},
            ],
            "amrg_anchor_dependency_contracts": [copy.deepcopy(contract or self.contract())],
        }

    def amrg_anchor(self, *, validation_status="validated", relationship_status=None, reason_codes=None):
        anchor = {
            "prior_anchor_slice_id": "amrg-prior-anchor:edge-1",
            "edge_id": "edge-1",
            "anchor_dependency_contract_id": "anchor-contract:edge-1",
            "validation_status": validation_status,
            "allowed_use": "condition_scoped_anchor_validation_input"
            if validation_status == "validated"
            else "validation_audit_only",
            "adjusted_upstream_probability": 0.4,
            "upstream_probability_source": "scae_upstream_prior_context",
            "upstream_probability_as_of": "2026-06-25T12:00:00+00:00",
            "upstream_prior_reliability_context": {
                "prior_reliability_score": 0.7,
                "prior_reliability_class": "usable_market",
                "authority": "scae_prior_context_only_no_evidence_delta",
            },
            "reason_codes": reason_codes or ["strict_precedence_anchor_validated"],
        }
        if relationship_status is not None:
            anchor["relationship_status"] = relationship_status
        return anchor

    def branch_slices(self, *, selected_market_prior_used=False):
        return [
            self.branch_slice(
                "branch-up",
                "leaf-up",
                delta=0.10,
                prior_probability=0.70,
                selected_market_prior_used=selected_market_prior_used,
            ),
            self.branch_slice(
                "branch-not-up",
                "leaf-not-up",
                delta=-0.05,
                prior_probability=0.20,
                selected_market_prior_used=False,
            ),
        ]

    def test_validated_anchor_recombines_condition_scoped_branch_probabilities(self):
        bundle = build_conditional_branch_recombination_bundle(
            self.branch_slices(),
            qdt=self.qdt(),
            amrg_anchor=self.amrg_anchor(),
            policy=self.policy,
        )

        epsilon = self.policy["prior_reliability"]["epsilon"]
        up = round(sigmoid(logit(0.70, epsilon) + 0.10), 9)
        not_up = round(sigmoid(logit(0.20, epsilon) - 0.05), 9)
        expected = round(up * 0.4 + not_up * 0.6, 9)

        self.assertEqual(bundle["schema_version"], SCAE_CONDITIONAL_BRANCH_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(bundle["authority"], NO_LIVE_AUTHORITY)
        self.assertFalse(bundle["writes_scae_ledger"])
        self.assertFalse(bundle["writes_production_forecast"])
        self.assertEqual(bundle["conditional_branch_count"], 2)
        summary = bundle["conditional_branch_summary"]
        self.assertEqual(summary["conditional_recombination_status"], "built")
        self.assertEqual(summary["target_given_upstream_branch_probability_candidate"], up)
        self.assertEqual(summary["target_given_not_upstream_branch_probability_candidate"], not_up)
        self.assertEqual(summary["conditional_recombined_probability_candidate"], expected)
        serialized = json.dumps(bundle, sort_keys=True)
        for forbidden_field in [
            "raw_ledger_probability",
            "post_ledger_probability",
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
        ]:
            self.assertNotIn(forbidden_field, serialized)

    def test_weak_context_anchor_is_rejected_without_recombination(self):
        weak_contract = self.contract(edge_status="weak_context_only")
        anchor = self.amrg_anchor(
            validation_status="rejected",
            relationship_status="weak_context_only",
            reason_codes=["edge_not_strict_precedence_anchor_candidate"],
        )

        bundle = build_conditional_branch_recombination_bundle(
            self.branch_slices(),
            qdt=self.qdt(contract=weak_contract),
            amrg_anchor=anchor,
            policy=self.policy,
        )

        summary = bundle["conditional_branch_summary"]
        self.assertEqual(bundle["conditional_branch_count"], 0)
        self.assertEqual(summary["conditional_recombined_probability_candidate"], None)
        self.assertIn("qdt_anchor_edge_not_validated_strict_precedence", summary["reason_codes"])
        self.assertTrue(summary["conditional_recombination_status"].startswith("rejected_"))
        self.assertFalse(summary["fallback_audit"]["repair_loop_allowed"])

    def test_concurrent_anchor_rejection_remains_audit_only(self):
        anchor = self.amrg_anchor(
            validation_status="rejected",
            relationship_status="timing_mismatch_weak_context_only",
            reason_codes=["concurrent_event_time"],
        )

        bundle = build_conditional_branch_recombination_bundle(
            self.branch_slices(),
            qdt=self.qdt(),
            amrg_anchor=anchor,
            policy=self.policy,
        )

        summary = bundle["conditional_branch_summary"]
        self.assertEqual(summary["conditional_recombined_probability_candidate"], None)
        self.assertIn("concurrent_event_time", summary["reason_codes"])
        self.assertEqual(summary["fallback_audit"]["fallback_status"], summary["conditional_recombination_status"])

    def test_missing_condition_scoped_leaves_are_rejected(self):
        contract = self.contract(condition_scoped_leaf_ids=[])

        bundle = build_conditional_branch_recombination_bundle(
            self.branch_slices(),
            qdt=self.qdt(contract=contract, up_scope="unconditional", not_up_scope="shared_context"),
            amrg_anchor=self.amrg_anchor(),
            policy=self.policy,
        )

        summary = bundle["conditional_branch_summary"]
        self.assertEqual(bundle["conditional_branch_count"], 0)
        self.assertIn("missing_qdt_condition_scoped_leaf_support", summary["reason_codes"])
        self.assertIn("missing_target_given_upstream_branch_subledger", summary["reason_codes"])
        self.assertIn("missing_target_given_not_upstream_branch_subledger", summary["reason_codes"])

    def test_selected_market_prior_reuse_is_rejected(self):
        with self.assertRaisesRegex(ScaeConditionalBranchError, "selected market prior"):
            build_conditional_branch_recombination_bundle(
                self.branch_slices(selected_market_prior_used=True),
                qdt=self.qdt(),
                amrg_anchor=self.amrg_anchor(),
                policy=self.policy,
            )

    def test_repair_budget_exhaustion_follows_qdt_policy_without_looping(self):
        contract = self.contract()
        contract["repair_exhaustion_policy"] = "watch_only_if_forecastable"
        contract["fallback_policy"]["fallback_mode"] = "watch_only_if_forecastable"
        anchor = self.amrg_anchor(
            validation_status="rejected",
            relationship_status="timing_mismatch_weak_context_only",
            reason_codes=["concurrent_event_time"],
        )

        bundle = build_conditional_branch_recombination_bundle(
            self.branch_slices(),
            qdt=self.qdt(contract=contract),
            amrg_anchor=anchor,
            policy=self.policy,
            repair_state={"repair_attempts_used": 1},
        )

        fallback = bundle["conditional_branch_summary"]["fallback_audit"]
        self.assertEqual(fallback["fallback_status"], "rejected_watch_only_if_forecastable")
        self.assertTrue(fallback["repair_budget_exhausted"])
        self.assertFalse(fallback["repair_loop_allowed"])
        self.assertEqual(fallback["repair_attempts_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
