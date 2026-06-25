import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.intervals import build_pre_debt_ledger_output  # noqa: E402
from scae.ledger import (  # noqa: E402
    CONTEXT_INVALID,
    CONTEXT_READY,
    CONTEXT_WATCH_ONLY,
    RESEARCH_SUFFICIENCY_GUARD_AUTHORITY,
    SCAE_RESEARCH_SUFFICIENCY_CONTEXT_SCHEMA_VERSION,
    ScaeLedgerError,
    apply_research_sufficiency_guard,
    build_research_sufficiency_context,
)
from scae.policy import default_scae_policy  # noqa: E402


class ScaeLedgerResearchSufficiencyTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def qdt(self, leaf_ids=None):
        return {
            "required_leaf_questions": [
                {
                    "leaf_id": leaf_id,
                    "parent_branch_id": "branch-1",
                    "leaf_condition_scope": "unconditional",
                    "research_sufficiency_requirements": {
                        "requirement_id": f"requirement:{leaf_id}",
                        "retrieval_breadth_profile_ref": f"breadth-profile:{leaf_id}",
                    },
                }
                for leaf_id in (leaf_ids or ["leaf-1"])
            ]
        }

    def ledger(self):
        return build_pre_debt_ledger_output(
            {
                "prior_context_id": "prior-context:case-1",
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "adjusted_prior_probability": 0.5,
            },
            policy=self.policy,
        )

    def reconciliation(
        self,
        leaf_id="leaf-1",
        *,
        status="scae_ready_high_certainty",
        breadth_profile_ref=None,
        breadth_coverage_ref=None,
        breadth_certified=True,
        required_escalation_refs=None,
        completed_escalation_refs=None,
        reason_codes=None,
        blocking_reason_codes=None,
    ):
        if breadth_profile_ref is None:
            breadth_profile_ref = f"breadth-profile:{leaf_id}"
        if breadth_coverage_ref is None:
            breadth_coverage_ref = f"breadth-coverage:{leaf_id}"
        return {
            "artifact_type": "research_sufficiency_reconciliation_slice",
            "schema_version": "research-sufficiency-reconciliation/v1",
            "feature_id": "VER-004",
            "research_sufficiency_reconciliation_id": f"reconciliation:{leaf_id}",
            "research_sufficiency_reconciliation_ref": f"research-sufficiency-reconciliation:{leaf_id}",
            "leaf_id": leaf_id,
            "research_sufficiency_certificate_ref": f"research-sufficiency:{leaf_id}",
            "retrieval_breadth_profile_ref": breadth_profile_ref,
            "retrieval_breadth_coverage_ref": breadth_coverage_ref,
            "retrieval_breadth_certified": breadth_certified,
            "required_escalation_decision_refs": required_escalation_refs or [],
            "completed_escalation_decision_refs": completed_escalation_refs or [],
            "reconciled_status": status,
            "research_sufficiency_reconciliation_status": status,
            "reason_codes": reason_codes or ["high_certainty_research_sufficiency_verified"],
            "blocking_reason_codes": blocking_reason_codes or [],
            "scae_ready": status in {"scae_ready_high_certainty", "structurally_unanswerable"},
        }

    def test_missing_ver_004_reconciliation_marks_ledger_invalid(self):
        guarded = apply_research_sufficiency_guard(
            self.ledger(),
            qdt=self.qdt(),
            sufficiency_reconciliations=[],
            policy=self.policy,
        )

        context = guarded["research_sufficiency_context"]
        self.assertEqual(context["schema_version"], SCAE_RESEARCH_SUFFICIENCY_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(context["bundle_status"], CONTEXT_INVALID)
        self.assertEqual(guarded["forecast_validity_status"], "invalid_for_forecast")
        self.assertFalse(guarded["calibration_debt_finalization_ready"])
        self.assertEqual(context["blocked_leaf_ids"], ["leaf-1"])
        self.assertIn(
            "research_sufficiency_reconciliation_missing",
            context["leaf_details"][0]["reason_codes"],
        )

    def test_blocked_insufficient_research_prevents_valid_forecast_and_is_debug_only(self):
        blocked = self.reconciliation(
            status="blocked_insufficient_research",
            breadth_certified=False,
            blocking_reason_codes=["retrieval_breadth_not_certified"],
        )
        guarded = apply_research_sufficiency_guard(
            self.ledger(),
            qdt=self.qdt(),
            sufficiency_reconciliations={"research_sufficiency_reconciliation_slices": [blocked]},
            policy=self.policy,
        )

        context = guarded["research_sufficiency_context"]
        self.assertEqual(context["bundle_status"], CONTEXT_INVALID)
        self.assertEqual(guarded["forecast_validity_status"], "invalid_for_forecast")
        component = context["insufficiency_interval_debug_components"][0]
        self.assertEqual(component["signed_log_odds_delta"], 0.0)
        self.assertFalse(component["accepted_for_ledger_input"])
        self.assertFalse(context["uncertified_thin_research_converted_to_evidence"])
        self.assertEqual(guarded["accepted_delta_inputs"], [])
        self.assertIn("retrieval_breadth_not_certified", component["reason_codes"])

    def test_structurally_unanswerable_requires_policy_permission_for_watch_only(self):
        structural = self.reconciliation(
            status="structurally_unanswerable",
            breadth_certified=False,
            required_escalation_refs=["researcher-escalation-decision:1"],
            completed_escalation_refs=["researcher-escalation-decision:1"],
            reason_codes=["structural_unanswerability_verified_with_required_confirmation"],
        )

        disallowed = build_research_sufficiency_context(
            qdt=self.qdt(),
            sufficiency_reconciliations=[structural],
            policy=self.policy,
        )
        self.assertEqual(disallowed["bundle_status"], CONTEXT_INVALID)
        self.assertIn(
            "structural_unanswerability_watch_only_not_permitted",
            disallowed["leaf_details"][0]["reason_codes"],
        )

        policy = copy.deepcopy(self.policy)
        policy["research_sufficiency"] = {"allow_watch_only_structural_unanswerability": True}
        allowed = build_research_sufficiency_context(
            qdt=self.qdt(),
            sufficiency_reconciliations=[structural],
            policy=policy,
        )
        self.assertEqual(allowed["bundle_status"], CONTEXT_WATCH_ONLY)
        self.assertEqual(allowed["forecast_validity_status"], "valid_for_forecast_watch_only")
        self.assertEqual(allowed["structurally_unanswerable_leaf_ids"], ["leaf-1"])

    def test_high_certainty_bundle_records_refs_and_permits_later_debt_finalization(self):
        row = self.reconciliation(
            required_escalation_refs=["researcher-escalation-decision:1"],
            completed_escalation_refs=["researcher-escalation-decision:1"],
        )
        guarded = apply_research_sufficiency_guard(
            self.ledger(),
            qdt=self.qdt(),
            sufficiency_reconciliations=[row],
            policy=self.policy,
        )

        context = guarded["research_sufficiency_context"]
        self.assertEqual(context["bundle_status"], CONTEXT_READY)
        self.assertEqual(guarded["forecast_validity_status"], "valid_for_forecast")
        self.assertTrue(guarded["calibration_debt_finalization_ready"])
        self.assertEqual(context["leaf_certificate_refs"], ["research-sufficiency:leaf-1"])
        self.assertEqual(context["leaf_reconciliation_refs"], ["research-sufficiency-reconciliation:leaf-1"])
        self.assertEqual(context["leaf_breadth_profile_refs"], ["breadth-profile:leaf-1"])
        self.assertEqual(context["leaf_breadth_coverage_refs"], ["breadth-coverage:leaf-1"])
        self.assertEqual(context["leaf_escalation_decision_refs"], ["researcher-escalation-decision:1"])
        self.assertEqual(guarded["sufficiency_guard_authority"], RESEARCH_SUFFICIENCY_GUARD_AUTHORITY)

        serialized = json.dumps(guarded, sort_keys=True)
        for forbidden_field in [
            "debt_adjusted_probability",
            "production_forecast_prob",
            "canonical_probability",
            "execution_authority_status",
        ]:
            self.assertNotIn(forbidden_field, serialized)

    def test_high_certainty_leaf_without_breadth_refs_fails_closed(self):
        row = self.reconciliation(breadth_profile_ref="", breadth_coverage_ref="", breadth_certified=False)
        qdt = self.qdt()
        qdt["required_leaf_questions"][0]["research_sufficiency_requirements"].pop(
            "retrieval_breadth_profile_ref"
        )
        context = build_research_sufficiency_context(
            qdt=qdt,
            sufficiency_reconciliations=[row],
            policy=self.policy,
        )

        self.assertEqual(context["bundle_status"], CONTEXT_INVALID)
        self.assertEqual(context["blocked_leaf_ids"], ["leaf-1"])
        reason_codes = context["leaf_details"][0]["reason_codes"]
        self.assertIn("retrieval_breadth_profile_ref_missing", reason_codes)
        self.assertIn("retrieval_breadth_coverage_ref_missing", reason_codes)
        self.assertIn("retrieval_breadth_not_certified", reason_codes)

    def test_incomplete_required_escalation_blocks_leaf(self):
        row = self.reconciliation(
            required_escalation_refs=["researcher-escalation-decision:1"],
            completed_escalation_refs=[],
        )
        context = build_research_sufficiency_context(
            qdt=self.qdt(),
            sufficiency_reconciliations=[row],
            policy=self.policy,
        )

        self.assertEqual(context["bundle_status"], CONTEXT_INVALID)
        self.assertIn("researcher_escalation_incomplete", context["leaf_details"][0]["reason_codes"])

    def test_guard_rejects_already_final_probability_fields(self):
        ledger = self.ledger()
        ledger["production_forecast_prob"] = ledger["post_ledger_probability"]

        with self.assertRaisesRegex(ScaeLedgerError, "already-final probability"):
            apply_research_sufficiency_guard(
                ledger,
                qdt=self.qdt(),
                sufficiency_reconciliations=[self.reconciliation()],
                policy=self.policy,
            )


if __name__ == "__main__":
    unittest.main()
