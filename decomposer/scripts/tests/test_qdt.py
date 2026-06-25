#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
)
from ads_decomposer.qdt import (  # noqa: E402
    COMPACT_DEFAULT_LEAF_BUDGET,
    QDTError,
    build_fixture_qdt_candidate,
    build_leaf_budget_decision,
    dump_question_decomposition,
    select_qdt_candidate,
    validate_question_decomposition,
)


class QDTContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.handoff = {
            "artifact_type": "decomposer_handoff",
            "schema_version": "decomposer-handoff/v1",
            "case_id": "case-1",
            "case_key": "polymarket:market-1",
            "dispatch_id": "dispatch-1",
            "macro_question": "Will example happen?",
            "market_context": {
                "market_id": "market-1",
                "market_reality_constraints_digest": "sha256:" + "0" * 64,
            },
            "artifact_refs": {
                "related_market_context": {
                    "artifact_id": "artifact:amrg-1",
                    "artifact_type": "related-live-market-context",
                },
            },
            "model_execution_context": {
                "model_lane_id": DECOMPOSER_MODEL_LANE_ID,
                "resolved_model_id": DECOMPOSER_MODEL_ID,
                "model_policy_ref": "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json",
                "prompt_template_id": DECOMPOSER_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": "sha256:" + "1" * 64,
                "input_manifest_ids": ["artifact:case", "artifact:evidence", "artifact:profile", "artifact:amrg"],
                "output_schema_version": QUESTION_DECOMPOSITION_SCHEMA_VERSION,
            },
        }

    def test_selects_valid_candidate_and_records_rejection_audit(self):
        invalid = build_fixture_qdt_candidate(self.handoff, candidate_id="qdt-candidate-bad")
        del invalid["required_leaf_questions"][0]["research_sufficiency_requirements"]
        valid = build_fixture_qdt_candidate(self.handoff, candidate_id="qdt-candidate-good")

        selected = select_qdt_candidate([invalid, valid])

        self.assertEqual(selected["candidate_selection_audit"]["selection_status"], "selected")
        self.assertEqual(selected["candidate_selection_audit"]["selected_candidate_id"], "qdt-candidate-good")
        self.assertEqual(
            selected["candidate_selection_audit"]["rejected_candidates"][0]["rejection_status"],
            "rejected_schema_invalid",
        )
        self.assertTrue(validate_question_decomposition(selected).valid)

    def test_selected_qdt_has_depth_two_branch_leaf_contract_and_model_provenance(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])

        self.assertGreaterEqual(len(selected["branches"]), 1)
        self.assertGreaterEqual(len(selected["required_leaf_questions"]), 1)
        branch_ids = {branch["branch_id"] for branch in selected["branches"]}
        for leaf in selected["required_leaf_questions"]:
            self.assertIn(leaf["parent_branch_id"], branch_ids)
            self.assertIn("leaf_dependency_group_id", leaf)
            self.assertIn("research_sufficiency_requirements", leaf)
            self.assertEqual(leaf["structural_validation"]["answerability_status"], "answerable")
        model_context = selected["model_execution_context"]
        self.assertEqual(model_context["resolved_model_id"], DECOMPOSER_MODEL_ID)
        self.assertEqual(model_context["output_schema_version"], "question-decomposition/v1")
        self.assertTrue(model_context["prompt_template_sha256"].startswith("sha256:"))

    def test_depth_three_tree_is_rejected_without_waiver(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["branches"][0]["child_branches"] = [{"branch_id": "branch-nested"}]
        broken["required_leaf_questions"][0]["structural_validation"]["depth"] = 3

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("invalid_depth", "; ".join(result.errors))

    def test_missing_required_purpose_from_evidence_packet_is_rejected_or_policy_waived(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        evidence_packet = {
            "market_reality_constraints_digest": selected["market_reality_constraints_digest"],
            "required_evidence_purposes": ["direct_evidence", "source_of_truth", "catalyst"],
        }

        result = validate_question_decomposition(selected, evidence_packet=evidence_packet)

        self.assertFalse(result.valid)
        self.assertIn("required_purpose_coverage_missing", "; ".join(result.errors))

        waived = copy.deepcopy(selected)
        waived["validation_summary"]["purpose_coverage_waiver"] = {"waiver_status": "approved"}
        self.assertTrue(validate_question_decomposition(waived, evidence_packet=evidence_packet).valid)

    def test_market_reality_constraints_digest_must_match_evidence_packet(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        evidence_packet = {"market_reality_constraints_digest": "sha256:" + "9" * 64}

        result = validate_question_decomposition(selected, evidence_packet=evidence_packet)

        self.assertFalse(result.valid)
        self.assertIn("market_reality_constraints_digest", "; ".join(result.errors))

    def test_invalid_condition_scoped_leaf_requires_anchor_contract(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("requires valid anchor contract", "; ".join(result.errors))

    def test_condition_scoped_leaf_accepts_valid_anchor_contract_ref(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        leaf_id = scoped["required_leaf_questions"][1]["leaf_id"]
        scoped["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        scoped["amrg_anchor_dependency_contracts"] = [
            {
                "contract_id": "anchor-contract-1",
                "related_market_ref": "artifact:amrg-1",
                "anchor_role": "anchor_required",
                "required_before_leaf_ids": [leaf_id],
            }
        ]

        self.assertTrue(validate_question_decomposition(scoped).valid)

    def test_critical_or_source_of_truth_leaf_requires_primary_or_unanswerability_path(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        source_leaf = selected["required_leaf_questions"][0]
        requirements = source_leaf["research_sufficiency_requirements"]
        self.assertTrue(requirements["protected_primary_required"])
        self.assertTrue(requirements["unanswerability_proof_required"])

        broken = copy.deepcopy(selected)
        broken_requirements = broken["required_leaf_questions"][0]["research_sufficiency_requirements"]
        broken_requirements["protected_primary_required"] = False
        broken_requirements["unanswerability_proof_required"] = False

        result = validate_question_decomposition(broken)
        self.assertFalse(result.valid)
        self.assertIn("critical/source-of-truth", "; ".join(result.errors))

    def test_unanswerable_critical_leaf_requires_explicit_policy_consequence(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][0]["structural_validation"] = {
            "depth": 2,
            "answerability_status": "unanswerable_policy_candidate",
        }

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("unanswerable_policy_consequence", "; ".join(result.errors))

        fixed = copy.deepcopy(broken)
        fixed["required_leaf_questions"][0]["structural_validation"][
            "unanswerable_policy_consequence"
        ] = "requires_unanswerability_proof_before_dispatch"
        self.assertTrue(validate_question_decomposition(fixed).valid)

    def test_missing_research_sufficiency_requirements_are_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        del broken["required_leaf_questions"][1]["research_sufficiency_requirements"]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("research_sufficiency_requirements", "; ".join(result.errors))

    def test_critical_leaf_cannot_allow_macro_fallback_as_sufficient_research(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][0]["research_sufficiency_requirements"][
            "allow_macro_fallback_for_leaf"
        ] = True

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("macro fallback", "; ".join(result.errors))

    def test_schema_rejects_prose_only_leaf_without_machine_fields(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        prose_only = copy.deepcopy(selected)
        prose_only["required_leaf_questions"][0] = {
            "leaf_id": "leaf-prose-only",
            "parent_branch_id": "branch-resolution",
            "question_text": "Find enough evidence to answer the question.",
        }

        result = validate_question_decomposition(prose_only)

        self.assertFalse(result.valid)
        self.assertIn("research_sufficiency_requirements", "; ".join(result.errors))
        self.assertIn("bayesian_weighting", "; ".join(result.errors))

    def test_large_leaf_budget_requires_hierarchical_branch_ledger_flag(self):
        candidate = build_fixture_qdt_candidate(
            self.handoff,
            effective_leaf_budget=COMPACT_DEFAULT_LEAF_BUDGET + 2,
        )
        selected = select_qdt_candidate([candidate])
        self.assertTrue(selected["leaf_budget_decision"]["hierarchical_branch_ledger_required"])

        broken = copy.deepcopy(selected)
        broken["leaf_budget_decision"]["hierarchical_branch_ledger_required"] = False
        result = validate_question_decomposition(broken)
        self.assertFalse(result.valid)
        self.assertIn("hierarchical branch ledger", "; ".join(result.errors))

    def test_forbidden_probability_fair_value_interval_and_reassembly_fields_are_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        forbidden_examples = {
            "leaf_probability": 0.4,
            "fair_value": 0.5,
            "confidence_interval": [0.1, 0.9],
            "reassembly_plan": {},
        }
        for field, value in forbidden_examples.items():
            with self.subTest(field=field):
                broken = copy.deepcopy(selected)
                broken["required_leaf_questions"][0][field] = value
                self.assertFalse(validate_question_decomposition(broken).valid)

    def test_rejects_missing_model_provenance(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        del broken["model_execution_context"]["prompt_template_sha256"]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("prompt_template_sha256", "; ".join(result.errors))

    def test_rejects_when_no_valid_candidate_exists(self):
        invalid = build_fixture_qdt_candidate(self.handoff, candidate_id="qdt-candidate-bad")
        invalid["model_execution_context"]["resolved_model_id"] = "gpt-5.4-high"

        with self.assertRaisesRegex(QDTError, "no valid QDT candidates"):
            select_qdt_candidate([invalid])

    def test_cli_validates_selected_artifact(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "question-decomposition.json"
            path.write_text(dump_question_decomposition(selected), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "decomposer" / "scripts" / "bin" / "validate_question_decomposition.py"),
                    str(path),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        summary = json.loads(completed.stdout)
        self.assertTrue(summary["valid"])

    def test_cli_rejects_evidence_packet_digest_mismatch(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        with tempfile.TemporaryDirectory() as temp:
            qdt_path = Path(temp) / "question-decomposition.json"
            evidence_path = Path(temp) / "evidence-packet.json"
            qdt_path.write_text(dump_question_decomposition(selected), encoding="utf-8")
            evidence_path.write_text(
                json.dumps({"market_reality_constraints_digest": "sha256:" + "8" * 64}),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "decomposer" / "scripts" / "bin" / "validate_question_decomposition.py"),
                    str(qdt_path),
                    "--evidence-packet",
                    str(evidence_path),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(completed.returncode, 1, completed.stdout)
        summary = json.loads(completed.stdout)
        self.assertFalse(summary["valid"])

    def test_leaf_budget_helper_records_audit_fields(self):
        decision = build_leaf_budget_decision(
            market_complexity_score=0.2,
            effective_leaf_budget=4,
            selected_leaf_count=3,
        )

        self.assertEqual(decision["budget_audit"]["selected_leaf_count"], 3)
        self.assertFalse(decision["hierarchical_branch_ledger_required"])


if __name__ == "__main__":
    unittest.main()
