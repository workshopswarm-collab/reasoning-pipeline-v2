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
    ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION,
    COMPACT_DEFAULT_LEAF_BUDGET,
    QDTError,
    build_anchor_dependency_contract,
    build_fixture_qdt_candidate,
    build_leaf_budget_decision,
    build_research_sufficiency_requirements,
    compute_qdt_quality_checks,
    dump_question_decomposition,
    repair_anchor_dependency_contracts,
    select_qdt_candidate,
    validate_anchor_dependency_contract,
    validate_question_decomposition,
    validate_question_decomposition_against_amrg_context,
)
from ads_decomposer.sufficiency_requirements import (  # noqa: E402
    RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION,
    RESEARCH_SUFFICIENCY_TEMPLATE_VERSION,
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

    def _refresh_leaf_sufficiency(self, leaf: dict) -> None:
        leaf["research_sufficiency_requirements"] = build_research_sufficiency_requirements(
            purpose=leaf["purpose"],
            research_priority=leaf["research_priority"],
            condition_scope=leaf["leaf_condition_scope"],
            required_value_fields=leaf["required_evidence_fields"],
        )

    def _condition_scoped_qdt_with_anchor_contract(self, *, edge_id: str, edge_status: str) -> dict:
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        scoped["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(scoped["required_leaf_questions"][1])
        scoped["branches"][0]["anchor_mode"] = "anchor_required"
        scoped["amrg_anchor_dependency_contracts"] = [
            build_anchor_dependency_contract(
                {"edge_id": edge_id, "status": edge_status},
                scoped["branches"][0],
                leaves=scoped["required_leaf_questions"],
                related_market_ref="artifact:amrg-1",
            )
        ]
        return scoped

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

    def test_selected_qdt_has_canonical_research_sufficiency_template_per_leaf(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])

        for leaf in selected["required_leaf_questions"]:
            requirements = leaf["research_sufficiency_requirements"]
            self.assertEqual(
                requirements["schema_version"],
                RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION,
            )
            self.assertEqual(requirements["template_version"], RESEARCH_SUFFICIENCY_TEMPLATE_VERSION)
            self.assertTrue(requirements["requirement_id"].startswith("qdt-sufficiency:"))
            self.assertEqual(requirements["leaf_purpose"], leaf["purpose"])
            self.assertEqual(
                requirements["research_priority"],
                leaf["research_priority"],
            )
            self.assertEqual(requirements["leaf_condition_scope"], leaf["leaf_condition_scope"])
            self.assertTrue(
                set(leaf["required_evidence_fields"]).issubset(requirements["required_value_fields"])
            )
            self.assertTrue(requirements["required_negative_checks"])
            self.assertTrue(requirements["classification_dispatch_requires_sufficiency_certificate"])

    def test_selected_qdt_has_no_legacy_weight_or_bayesian_keys(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])

        def assert_clean_keys(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = str(key).lower()
                    self.assertNotIn("bayesian", normalized)
                    self.assertNotIn("weight", normalized)
                    assert_clean_keys(child)
            elif isinstance(value, list):
                for child in value:
                    assert_clean_keys(child)

        assert_clean_keys(json.loads(dump_question_decomposition(selected)))

    def test_sufficiency_requirement_must_match_leaf_scope_and_priority(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        requirements = broken["required_leaf_questions"][1]["research_sufficiency_requirements"]
        requirements["leaf_condition_scope"] = "target_given_upstream"

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("leaf_condition_scope must match", "; ".join(result.errors))

    def test_sufficiency_requirement_must_include_leaf_required_evidence_fields(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        requirements = broken["required_leaf_questions"][1]["research_sufficiency_requirements"]
        requirements["required_value_fields"] = ["event_status"]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("required_evidence_fields", "; ".join(result.errors))

    def test_source_of_truth_sufficiency_requires_canonical_primary_source_classes(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        requirements = broken["required_leaf_questions"][0]["research_sufficiency_requirements"]
        requirements["required_source_classes"] = ["independent_secondary"]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("required_source_classes must match canonical purpose template", "; ".join(result.errors))

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
            "required_evidence_purposes": ["direct_evidence", "source_of_truth", "market_pricing"],
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
        self._refresh_leaf_sufficiency(broken["required_leaf_questions"][1])

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("requires valid anchor contract", "; ".join(result.errors))

    def test_condition_scoped_leaf_accepts_valid_anchor_contract_ref(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        leaf_id = scoped["required_leaf_questions"][1]["leaf_id"]
        scoped["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(scoped["required_leaf_questions"][1])
        scoped["branches"][0]["anchor_mode"] = "anchor_required"
        scoped["amrg_anchor_dependency_contracts"] = [
            build_anchor_dependency_contract(
                {"edge_id": "edge-1", "status": "validated_strict_precedence_anchor"},
                scoped["branches"][0],
                leaves=scoped["required_leaf_questions"],
                related_market_ref="artifact:amrg-1",
            )
        ]

        contract = scoped["amrg_anchor_dependency_contracts"][0]
        self.assertEqual(contract["schema_version"], ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION)
        self.assertEqual(contract["edge_id"], "edge-1")
        self.assertEqual(contract["anchor_mode"], "anchor_required")
        self.assertEqual(contract["condition_scoped_leaf_ids"], [leaf_id])
        self.assertTrue(contract["fallback_policy"])
        self.assertGreater(contract["max_anchor_repair_attempts"], 0)
        self.assertGreater(contract["max_anchor_repair_wall_clock_seconds"], 0)
        self.assertTrue(validate_question_decomposition(scoped).valid)

    def test_weak_amrg_edge_cannot_create_anchor_required_contract(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        scoped["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(scoped["required_leaf_questions"][1])
        scoped["branches"][0]["anchor_mode"] = "anchor_required"

        contract = build_anchor_dependency_contract(
            {"edge_id": "edge-weak", "relationship_status": "weak_context_only"},
            scoped["branches"][0],
            leaves=scoped["required_leaf_questions"],
            related_market_ref="artifact:amrg-1",
        )

        self.assertEqual(contract["anchor_mode"], "diagnostic_only")
        scoped["amrg_anchor_dependency_contracts"] = [contract]
        result = validate_question_decomposition(scoped)
        self.assertFalse(result.valid)
        self.assertIn("requires valid anchor contract", "; ".join(result.errors))

        forced_required = copy.deepcopy(contract)
        forced_required["anchor_mode"] = "anchor_required"
        forced_result = validate_anchor_dependency_contract(
            forced_required,
            leaves=scoped["required_leaf_questions"],
        )
        self.assertFalse(forced_result.valid)
        self.assertIn("cannot use weak", "; ".join(forced_result.errors))

    def test_amrg_usage_refs_must_match_actual_amrg_context(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        scoped["branches"][0]["amrg_usage_refs"] = ["edge-missing"]

        result = validate_question_decomposition_against_amrg_context(
            scoped,
            {
                "artifact_type": "related_live_market_context",
                "relationship_edges": [{"edge_id": "edge-present"}],
                "amrg_decomposer_context": {"hints": [{"hint_ref": "edge-present"}]},
            },
        )

        self.assertFalse(result.valid)
        self.assertIn("unknown AMRG hints", "; ".join(result.errors))

    def test_anchor_contract_cross_checks_actual_amrg_context_status(self):
        scoped = self._condition_scoped_qdt_with_anchor_contract(
            edge_id="edge-anchor-actual",
            edge_status="validated_strict_precedence_anchor",
        )
        self.assertTrue(validate_question_decomposition(scoped).valid)

        result = validate_question_decomposition_against_amrg_context(
            scoped,
            {
                "artifact_type": "related_live_market_context",
                "relationship_edges": [
                    {
                        "edge_id": "edge-anchor-actual",
                        "relationship_status": "weak_context_only",
                        "allowed_effects": ["decomposition_context_hint"],
                    }
                ],
                "amrg_decomposer_context": {"hints": [{"hint_ref": "edge-anchor-actual"}]},
            },
        )

        self.assertFalse(result.valid)
        self.assertIn("not a strict-precedence AMRG edge", "; ".join(result.errors))

    def test_anchor_contract_accepts_actual_strict_amrg_context_edge(self):
        scoped = self._condition_scoped_qdt_with_anchor_contract(
            edge_id="edge-anchor-actual",
            edge_status="validated_strict_precedence_anchor",
        )

        result = validate_question_decomposition_against_amrg_context(
            scoped,
            {
                "artifact_type": "related_live_market_context",
                "relationship_edges": [
                    {
                        "edge_id": "edge-anchor-actual",
                        "relationship_status": "validated_strict_precedence_anchor",
                        "allowed_effects": [
                            "decomposition_context_hint",
                            "qdt_anchor_dependency_hint",
                        ],
                    }
                ],
                "amrg_decomposer_context": {"hints": [{"hint_ref": "edge-anchor-actual"}]},
            },
        )

        self.assertTrue(result.valid, result.errors)

    def test_strict_precedence_candidate_creates_anchor_optional_contract(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        scoped["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_not_upstream"
        self._refresh_leaf_sufficiency(scoped["required_leaf_questions"][1])
        contract = build_anchor_dependency_contract(
            {"edge_id": "edge-candidate", "status": "strict_precedence_anchor_candidate"},
            scoped["branches"][0],
            leaves=scoped["required_leaf_questions"],
            related_market_ref="artifact:amrg-1",
        )

        self.assertEqual(contract["anchor_mode"], "anchor_optional")
        scoped["amrg_anchor_dependency_contracts"] = [contract]
        self.assertTrue(validate_question_decomposition(scoped).valid)

    def test_anchor_required_without_fallback_or_repair_policy_is_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        scoped = copy.deepcopy(selected)
        scoped["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(scoped["required_leaf_questions"][1])
        scoped["branches"][0]["anchor_mode"] = "anchor_required"
        contract = build_anchor_dependency_contract(
            {"edge_id": "edge-1", "status": "validated_strict_precedence_anchor"},
            scoped["branches"][0],
            leaves=scoped["required_leaf_questions"],
            related_market_ref="artifact:amrg-1",
        )

        for field in (
            "fallback_policy",
            "max_anchor_repair_attempts",
            "max_anchor_repair_wall_clock_seconds",
            "repair_exhaustion_policy",
        ):
            with self.subTest(field=field):
                broken = copy.deepcopy(scoped)
                broken_contract = copy.deepcopy(contract)
                broken_contract.pop(field)
                broken["amrg_anchor_dependency_contracts"] = [broken_contract]
                result = validate_question_decomposition(broken)
                self.assertFalse(result.valid)
                self.assertIn(field, "; ".join(result.errors))

    def test_repair_helper_adds_contract_for_condition_scoped_branch(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(broken["required_leaf_questions"][1])
        broken["branches"][0]["anchor_mode"] = "anchor_required"
        self.assertFalse(validate_question_decomposition(broken).valid)

        repaired = repair_anchor_dependency_contracts(
            broken,
            related_market_context={
                "relationship_edges": [
                    {
                        "edge_id": "edge-anchor-1",
                        "status": "validated_strict_precedence_anchor",
                        "candidate_id": "amrg-candidate-1",
                    }
                ]
            },
        )

        self.assertTrue(repaired["repair_summary"]["post_repair_valid"], repaired["repair_summary"])
        self.assertEqual(repaired["repair_summary"]["edge_ids_used"], ["edge-anchor-1"])
        artifact = repaired["artifact"]
        self.assertTrue(validate_question_decomposition(artifact).valid)
        self.assertEqual(artifact["related_market_context_usage"]["anchor_dependency_status"], "declared")
        self.assertEqual(artifact["related_market_context_usage"]["amrg_usage_refs"], ["edge-anchor-1"])

    def test_repair_cli_writes_valid_repaired_artifact(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(broken["required_leaf_questions"][1])
        broken["branches"][0]["anchor_mode"] = "anchor_required"
        with tempfile.TemporaryDirectory() as temp:
            qdt_path = Path(temp) / "question-decomposition.json"
            context_path = Path(temp) / "related-context.json"
            output_path = Path(temp) / "repaired-question-decomposition.json"
            qdt_path.write_text(json.dumps(broken), encoding="utf-8")
            context_path.write_text(
                json.dumps(
                    {
                        "relationship_edges": [
                            {
                                "edge_id": "edge-anchor-1",
                                "status": "validated_strict_precedence_anchor",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "decomposer" / "scripts" / "bin" / "repair_anchor_dependency.py"),
                    str(qdt_path),
                    "--related-market-context",
                    str(context_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            summary = json.loads(completed.stdout)
            self.assertTrue(summary["post_repair_valid"])
            repaired = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(validate_question_decomposition(repaired).valid)

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
        self.assertIn("research_priority", "; ".join(result.errors))

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

    def test_selected_qdt_has_research_coverage_graph_and_contract(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])

        self.assertIn("market_resolution_contract", selected)
        self.assertIn("research_coverage_graph", selected)
        self.assertEqual(selected["question_specificity_check"]["status"], "passed")
        self.assertEqual(selected["research_coverage_check"]["status"], "passed")
        graph = selected["research_coverage_graph"]
        self.assertEqual(graph["market_temporal_state"], "unresolved")
        self.assertIn("forecast_research_objective", graph)
        self.assertIn("terminal_verification_leaf_ids", graph)
        self.assertIn("dispatchable_pre_resolution_leaf_ids", graph)
        self.assertFalse(graph["terminal_verification_leaf_ids"])
        self.assertEqual(
            sorted(graph["dispatchable_pre_resolution_leaf_ids"]),
            sorted(leaf["leaf_id"] for leaf in selected["required_leaf_questions"]),
        )
        for dimension in (
            "resolution_mechanics",
            "current_direct_evidence",
            "key_drivers",
            "counterevidence_negative_checks",
            "timing_deadline_constraints",
            "source_quality",
            "material_unknowns",
        ):
            self.assertIn(dimension, graph["required_leaf_ids_by_dimension"])
        for leaf in selected["required_leaf_questions"]:
            self.assertIn("leaf_temporal_role", leaf)
            self.assertIn("coverage_dimension", leaf)
            self.assertIn("research_factor", leaf)
            self.assertIn("evidence_requirements", leaf)
            self.assertIn("classification_targets", leaf)
            self.assertIn("sufficiency_criteria", leaf)
            self.assertIn("why_this_must_be_investigated", leaf["specificity_evidence"])
            self.assertIn("probability", leaf["forbidden_outputs"])
            self.assertIn("final_forecast", leaf["forbidden_outputs"])

    def test_missing_leaf_temporal_role_is_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][0].pop("leaf_temporal_role")

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("leaf_temporal_role", "; ".join(result.errors))

    def test_terminal_verification_graph_refs_must_match_leaf_role(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        non_terminal_leaf_id = broken["required_leaf_questions"][0]["leaf_id"]
        broken["research_coverage_graph"]["terminal_verification_leaf_ids"] = [non_terminal_leaf_id]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("terminal_verification_leaf_ids references non-terminal leaf", "; ".join(result.errors))

    def test_unresolved_qdt_cannot_dispatch_terminal_verification_leaf(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        leaf = broken["required_leaf_questions"][0]
        leaf["leaf_temporal_role"] = "terminal_verification"
        leaf_id = leaf["leaf_id"]
        graph = broken["research_coverage_graph"]
        graph["terminal_verification_leaf_ids"] = [leaf_id]
        graph["dispatchable_pre_resolution_leaf_ids"] = list(
            {leaf_id, *graph["dispatchable_pre_resolution_leaf_ids"]}
        )

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("dispatchable_pre_resolution_leaf_ids contains terminal verification", "; ".join(result.errors))

    def test_generic_mad_lib_leaf_is_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][0]["question_text"] = (
            "What official or primary-source information can resolve the market question?"
        )
        broken["required_leaf_questions"][0]["leaf_question"] = broken["required_leaf_questions"][0]["question_text"]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("template_mad_lib_leaf", "; ".join(result.errors))

    def test_resolution_checklist_only_coverage_is_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        all_leaf_ids = [leaf["leaf_id"] for leaf in broken["required_leaf_questions"]]
        broken["research_coverage_graph"]["contract_guard_leaf_ids"] = all_leaf_ids
        broken["research_coverage_graph"]["material_question_leaf_ids"] = []

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("insufficient_material_leaf_count", "; ".join(result.errors))

    def test_missing_research_assignment_fields_are_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        for field, expected in (
            ("classification_targets", "classification_targets"),
            ("evidence_requirements", "evidence_requirements"),
            ("sufficiency_criteria", "sufficiency_criteria"),
        ):
            with self.subTest(field=field):
                broken = copy.deepcopy(selected)
                broken["required_leaf_questions"][0].pop(field)
                result = validate_question_decomposition(broken)
                self.assertFalse(result.valid)
                self.assertIn(expected, "; ".join(result.errors))

    def test_missing_specificity_purpose_is_rejected(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][0]["specificity_evidence"]["why_this_must_be_investigated"] = ""

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("why_this_must_be_investigated", "; ".join(result.errors))

    def test_leaf_forbidden_outputs_must_cover_no_forecast_authority(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        broken = copy.deepcopy(selected)
        broken["required_leaf_questions"][0]["forbidden_outputs"] = ["probability"]

        result = validate_question_decomposition(broken)

        self.assertFalse(result.valid)
        self.assertIn("forbidden_outputs missing", "; ".join(result.errors))

    def test_negative_semantic_market_requires_negative_yes_no_mapping(self):
        handoff = copy.deepcopy(self.handoff)
        handoff["macro_question"] = "No one announced as next James Bond?"

        selected = select_qdt_candidate([build_fixture_qdt_candidate(handoff)])

        self.assertTrue(validate_question_decomposition(selected).valid)
        mapping = json.dumps(selected["market_resolution_contract"]["yes_no_mapping"])
        self.assertIn("absence", mapping)
        self.assertIn("current_direct_evidence", selected["research_coverage_graph"]["required_leaf_ids_by_dimension"])

    def test_negative_market_without_explicit_yes_no_semantics_is_rejected(self):
        handoff = copy.deepcopy(self.handoff)
        handoff["macro_question"] = "No one announced as next James Bond?"
        selected = select_qdt_candidate([build_fixture_qdt_candidate(handoff)])
        broken = copy.deepcopy(selected)
        broken["market_resolution_contract"]["yes_no_mapping"] = {
            "yes_means": "The target event occurs under the market rules.",
            "no_means": "The target event does not occur under the market rules.",
            "mapping_confidence": "requires_case_contract_confirmation",
        }

        result = validate_question_decomposition(broken)
        checks = compute_qdt_quality_checks(broken)

        self.assertFalse(result.valid)
        self.assertIn("negative_market_mapping_not_decomposed", "; ".join(result.errors))
        self.assertEqual(checks["question_specificity_check"]["status"], "failed")

    def test_grouped_market_family_context_requires_contract_analysis(self):
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])
        evidence_packet = {"family_context": {"parent_market_id": "parent-market-1"}}

        result = validate_question_decomposition(selected, evidence_packet=evidence_packet)
        checks = compute_qdt_quality_checks(selected, evidence_packet=evidence_packet)

        self.assertFalse(result.valid)
        self.assertIn("market_family_context_not_analyzed", "; ".join(result.errors))
        self.assertEqual(checks["question_specificity_check"]["status"], "failed")

    def test_valid_research_coverage_graph_output_is_accepted(self):
        base = build_fixture_qdt_candidate(self.handoff)
        selected = select_qdt_candidate([base])

        self.assertTrue(validate_question_decomposition(selected).valid)
        self.assertGreaterEqual(
            len(selected["research_coverage_graph"]["material_question_leaf_ids"]),
            5,
        )

    def _victor_marx_handoff(self) -> dict:
        handoff = copy.deepcopy(self.handoff)
        handoff["case_id"] = "case-victor-marx"
        handoff["case_key"] = "polymarket:825858"
        handoff["dispatch_id"] = "dispatch-victor-marx"
        handoff["macro_question"] = (
            "Will Victor Marx win the 2026 Colorado Governor Republican primary election?"
        )
        handoff["market_context"] = {
            "market_id": "825858",
            "market_reality_constraints_digest": "sha256:" + "2" * 64,
            "closes_at": "2026-06-30T23:59:00+00:00",
            "platform_family_context": "polymarket-colorado-governor-primary-family",
        }
        return handoff

    def _victor_marx_result_verification_dominant_qdt(self) -> dict:
        selected = select_qdt_candidate([build_fixture_qdt_candidate(self._victor_marx_handoff())])
        replacement_questions = [
            "Did the 2026 Colorado Republican gubernatorial primary take place under rules relevant to this market?",
            "Was Victor Marx a candidate in the 2026 Colorado Republican gubernatorial primary covered by this market?",
            "What did the first official Colorado Republican Party announcement state about the winner of the 2026 Colorado gubernatorial Republican primary?",
            "Was Victor Marx the overall winner of the 2026 Colorado gubernatorial Republican primary, including any second round or run-off if applicable?",
            "If no 2026 Colorado gubernatorial Republican primary took place, does the market rule require resolution to Other rather than Victor Marx?",
            "If the Colorado Republican Party official announcement is unavailable or delayed, is there an overwhelming consensus of credible reporting on whether Victor Marx won the primary?",
        ]
        for leaf, question in zip(selected["required_leaf_questions"], replacement_questions):
            leaf["question_text"] = question
            leaf["leaf_question"] = question
            leaf["specificity_evidence"]["why_this_must_be_investigated"] = (
                "Captured from the audited Victor Marx live QDT baseline to prove "
                "that terminal result-verification wording is currently not rejected "
                "when the leaf is otherwise shaped like a material research leaf."
            )
            leaf["specificity_evidence"]["not_a_template_reason"] = (
                "References Victor Marx and the 2026 Colorado Republican gubernatorial primary."
            )
        return selected

    def test_unresolved_election_result_verification_dominant_qdt_is_rejected(self):
        qdt = self._victor_marx_result_verification_dominant_qdt()

        result = validate_question_decomposition(qdt)
        checks = compute_qdt_quality_checks(qdt)

        self.assertFalse(result.valid)
        self.assertIn("terminal_verification_dominates_unresolved_forecast_qdt", "; ".join(result.errors))
        self.assertEqual(checks["research_coverage_check"]["status"], "failed")
        self.assertIn(
            "terminal_verification_dominates_unresolved_forecast_qdt",
            "; ".join(checks["research_coverage_check"]["reason_codes"]),
        )
        self.assertEqual(checks["question_specificity_check"]["status"], "failed")
        self.assertIn(
            "terminal_verification_leaf_misclassified_as_pre_resolution",
            "; ".join(checks["question_specificity_check"]["reason_codes"]),
        )

    def test_unresolved_election_pre_resolution_forecast_driver_qdt_is_accepted(self):
        qdt = select_qdt_candidate([build_fixture_qdt_candidate(self._victor_marx_handoff())])
        replacements = {
            "leaf-direct-evidence": (
                "What pre-cutoff evidence shows Victor Marx's current ballot access, eligibility, "
                "and active campaign status in the Colorado Republican gubernatorial primary?"
            ),
            "leaf-key-driver-status": (
                "What polling, endorsements, fundraising, field strength, campaign activity, or "
                "local reporting bears on Victor Marx's chance of winning before resolution?"
            ),
            "leaf-negative-checks": (
                "What withdrawals, ballot-access problems, weak campaign signals, stronger opponents, "
                "or contradictory reporting reduce Victor Marx's chance before resolution?"
            ),
            "leaf-source-quality": (
                "Which current sources about Victor Marx's campaign strength are independent, timely, "
                "and high quality rather than repeated rumor or market chatter?"
            ),
            "leaf-material-unknowns": (
                "What material pre-resolution evidence about Victor Marx's primary chances remains "
                "unknown or structurally unavailable before the source cutoff?"
            ),
        }
        for leaf in qdt["required_leaf_questions"]:
            if leaf["leaf_id"] in replacements:
                leaf["question_text"] = replacements[leaf["leaf_id"]]
                leaf["leaf_question"] = replacements[leaf["leaf_id"]]
                leaf["specificity_evidence"]["why_this_must_be_investigated"] = (
                    "This is a pre-resolution forecast-driver leaf for the Victor Marx market."
                )

        result = validate_question_decomposition(qdt)
        checks = compute_qdt_quality_checks(qdt)

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(checks["question_specificity_check"]["status"], "passed")
        self.assertEqual(checks["research_coverage_check"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
