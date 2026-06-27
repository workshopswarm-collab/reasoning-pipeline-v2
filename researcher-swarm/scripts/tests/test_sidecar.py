#!/usr/bin/env python3

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.classification import (  # noqa: E402
    RESEARCHER_LEAF_NLI_MODEL_LANE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
    build_researcher_sidecar_v2,
    compute_classification_matrix_digest,
    compute_researcher_sidecar_digest,
    validate_researcher_sidecar_against_retrieval_packet,
    validate_researcher_sidecar_v2,
)
from researcher_swarm.model_context import resolve_researcher_leaf_nli_model_context  # noqa: E402


def _sha(char: str) -> str:
    return "sha256:" + char * 64


class ResearcherSidecarV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.qdt = {
            "schema_version": "question-decomposition/v1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "market_reality_constraints_digest": _sha("a"),
            "required_leaf_questions": [
                {
                    "leaf_id": "leaf-1",
                    "parent_branch_id": "branch-1",
                    "leaf_condition_scope": "unconditional",
                },
                {
                    "leaf_id": "leaf-2",
                    "parent_branch_id": "branch-1",
                    "leaf_condition_scope": "unconditional",
                },
            ],
        }
        self.model_context = resolve_researcher_leaf_nli_model_context()
        self.assertEqual(self.model_context["model_lane_id"], RESEARCHER_LEAF_NLI_MODEL_LANE_ID)
        self.assertEqual(self.model_context["prompt_template_id"], RESEARCHER_NLI_PROMPT_TEMPLATE_ID)
        self.assertEqual(self.model_context["prompt_template_sha256"], RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256)

    def _evidence_ref(self, leaf_id: str) -> str:
        return f"retrieval-evidence:{leaf_id}:primary"

    def _classification(self, leaf_id: str) -> dict[str, Any]:
        return {
            "leaf_id": leaf_id,
            "parent_branch_id": "branch-1",
            "leaf_condition_scope": "unconditional",
            "evidence_ref": self._evidence_ref(leaf_id),
            "research_sufficiency_certificate_ref": f"research-sufficiency:{leaf_id}",
            "coverage_proof_ref": f"coverage-proof:{leaf_id}",
            "impact_direction": "supports_yes",
            "evidence_strength": "strong",
            "classification_confidence": "high",
            "answer_value_extraction": {
                "field_name": "status",
                "value": "confirmed",
                "normalization_status": "parsed",
            },
            "evidence_quality_dimensions": {
                "source_authority": "high",
                "directness": "direct",
                "recency": "fresh",
                "specificity": "specific",
            },
            "provenance_refs": [f"retrieval-provenance:{leaf_id}"],
        }

    def _unanswerable_classification(self, leaf_id: str) -> dict[str, Any]:
        item = self._classification(leaf_id)
        item.pop("evidence_ref")
        item.update(
            {
                "supplemental_evidence_refs": [f"supplemental-evidence:{leaf_id}:gap-proof"],
                "impact_direction": "insufficient",
                "evidence_strength": "none",
                "classification_confidence": "medium",
                "classification_quality": "medium",
                "classification_acceptance_status": "blocked",
                "evidence_delta_eligible_for_scae": False,
                "answer_value_extraction": {
                    "field_name": "status",
                    "value": "",
                    "normalization_status": "not_applicable",
                },
                "evidence_quality_dimensions": {
                    "source_authority": "unknown",
                    "directness": "unknown",
                    "recency": "unknown",
                    "specificity": "ambiguous",
                },
                "provenance_refs": [f"research-sufficiency:{leaf_id}", f"retrieval-expansion:{leaf_id}"],
                "unanswerability": {
                    "rationale": "Required protected source remained absent after targeted expansion.",
                    "provenance_refs": [f"research-sufficiency:{leaf_id}"],
                    "source_gap_flags": ["protected_primary_absent"],
                    "exhausted_expansion_refs": [f"retrieval-expansion:{leaf_id}"],
                },
            }
        )
        return item

    def _coverage(self, leaf_id: str, *, unanswerable: bool = False) -> dict[str, Any]:
        reviewed_ref = (
            f"supplemental-evidence:{leaf_id}:gap-proof"
            if unanswerable
            else self._evidence_ref(leaf_id)
        )
        return {
            "coverage_proof_id": f"coverage-proof:{leaf_id}",
            "leaf_id": leaf_id,
            "research_sufficiency_certificate_ref": f"research-sufficiency:{leaf_id}",
            "retrieval_breadth_coverage_ref": f"breadth-coverage:{leaf_id}",
            "evidence_refs_assigned": [reviewed_ref],
            "evidence_refs_reviewed": [reviewed_ref],
            "source_class_ids_reviewed": ["official_or_primary"],
            "claim_family_ids_reviewed": [f"claim-family:{leaf_id}"],
            "source_family_ids_reviewed": [f"source-family:{leaf_id}"],
            "requirements_reviewed": [f"requirement:{leaf_id}"],
            "requirements_answered": [] if unanswerable else [f"requirement:{leaf_id}"],
            "requirements_unanswered": [f"requirement:{leaf_id}"] if unanswerable else [],
            "required_value_fields_extracted": [] if unanswerable else ["status"],
            "required_negative_checks_completed": ["no_official_contradiction"],
            "source_gap_flags": ["protected_primary_absent"] if unanswerable else [],
            "structural_unanswerability_acknowledged": unanswerable,
            "machine_readability_status": "schema_valid",
        }

    def _sidecar(self, *, unanswerable_leaf_2: bool = False) -> dict[str, Any]:
        classifications = [self._classification("leaf-1")]
        proofs = [self._coverage("leaf-1")]
        if unanswerable_leaf_2:
            classifications.append(self._unanswerable_classification("leaf-2"))
            proofs.append(self._coverage("leaf-2", unanswerable=True))
        else:
            classifications.append(self._classification("leaf-2"))
            proofs.append(self._coverage("leaf-2"))
        return build_researcher_sidecar_v2(
            qdt=self.qdt,
            required_question_classifications=classifications,
            coverage_proofs=proofs,
            model_execution_context_ref="artifact:model-execution-context:researcher-leaf-nli",
            model_execution_context=self.model_context,
        )

    def _refresh_digests(self, sidecar: dict[str, Any]) -> None:
        sidecar["classification_matrix_digest"] = compute_classification_matrix_digest(
            sidecar["required_question_classifications"]
        )
        sidecar["sidecar_digest"] = compute_researcher_sidecar_digest(sidecar)

    def test_valid_sidecar_is_deterministic_and_schema_valid(self) -> None:
        first = self._sidecar()
        second = self._sidecar()

        self.assertEqual(first["sidecar_id"], second["sidecar_id"])
        self.assertEqual(first["classification_matrix_digest"], second["classification_matrix_digest"])
        self.assertEqual(first["sidecar_digest"], second["sidecar_digest"])

        result = validate_researcher_sidecar_v2(first, self.qdt)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(first["feature_id"], "CLS-002")
        self.assertEqual(first["schema_version"], "researcher-sidecar/v2")

    def test_forbidden_probability_replacement_and_confidence_fields_rejected(self) -> None:
        cases = {
            "own_probability": ("required_question_classifications", 0, "own_probability", 0.6),
            "replacement_probability": ("top", None, "replacement_probability", 0.51),
            "confidence": ("required_question_classifications", 0, "confidence", 0.9),
        }
        for expected, mutation in cases.items():
            with self.subTest(expected=expected):
                sidecar = self._sidecar()
                container, idx, key, value = mutation
                if container == "top":
                    sidecar[key] = value
                else:
                    sidecar[container][idx][key] = value
                    self._refresh_digests(sidecar)
                if container == "top":
                    self._refresh_digests(sidecar)

                result = validate_researcher_sidecar_v2(sidecar, self.qdt)

                self.assertFalse(result.valid)
                self.assertIn(expected, "; ".join(result.errors))

    def test_missing_required_leaf_is_rejected(self) -> None:
        sidecar = self._sidecar()
        sidecar["required_question_classifications"] = sidecar["required_question_classifications"][:1]
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("classification_coverage_missing: leaf-2", "; ".join(result.errors))

    def test_retrieval_aware_validation_rejects_unadmitted_evidence_refs(self) -> None:
        sidecar = self._sidecar()
        sidecar["required_question_classifications"][0]["evidence_ref"] = "retrieval-evidence:leaf-1:unadmitted"
        sidecar["coverage_proofs"][0]["evidence_refs_reviewed"] = ["retrieval-evidence:leaf-1:unadmitted"]
        self._refresh_digests(sidecar)
        retrieval_packet = {
            "leaf_evidence_dockets": [
                {
                    "leaf_id": "leaf-1",
                    "admitted_evidence_refs": [self._evidence_ref("leaf-1")],
                },
                {
                    "leaf_id": "leaf-2",
                    "admitted_evidence_refs": [self._evidence_ref("leaf-2")],
                },
            ],
            "supplemental_evidence_admission_results": [],
        }

        base = validate_researcher_sidecar_v2(sidecar, self.qdt)
        retrieval_aware = validate_researcher_sidecar_against_retrieval_packet(
            sidecar,
            self.qdt,
            retrieval_packet,
        )

        self.assertTrue(base.valid, base.errors)
        self.assertFalse(retrieval_aware.valid)
        self.assertIn("not admitted by retrieval docket", "; ".join(retrieval_aware.errors))

    def test_retrieval_aware_validation_rejects_unadmitted_supplemental_refs(self) -> None:
        sidecar = self._sidecar()
        supplemental_ref = "supplemental:leaf-1:proposal"
        sidecar["required_question_classifications"][0].pop("evidence_ref")
        sidecar["required_question_classifications"][0]["supplemental_evidence_ref"] = supplemental_ref
        sidecar["coverage_proofs"][0]["evidence_refs_reviewed"] = [supplemental_ref]
        sidecar["coverage_proofs"][0]["supplemental_evidence_refs_reviewed"] = [supplemental_ref]
        self._refresh_digests(sidecar)
        retrieval_packet = {
            "leaf_evidence_dockets": [
                {
                    "leaf_id": "leaf-1",
                    "admitted_evidence_refs": [self._evidence_ref("leaf-1")],
                },
                {
                    "leaf_id": "leaf-2",
                    "admitted_evidence_refs": [self._evidence_ref("leaf-2")],
                },
            ],
            "supplemental_evidence_admission_results": [],
        }

        base = validate_researcher_sidecar_v2(sidecar, self.qdt)
        retrieval_aware = validate_researcher_sidecar_against_retrieval_packet(
            sidecar,
            self.qdt,
            retrieval_packet,
        )

        self.assertTrue(base.valid, base.errors)
        self.assertFalse(retrieval_aware.valid)
        self.assertIn("not admitted by retrieval docket", "; ".join(retrieval_aware.errors))

    def test_missing_coverage_proof_is_rejected(self) -> None:
        sidecar = self._sidecar()
        sidecar["coverage_proofs"] = sidecar["coverage_proofs"][1:]
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("coverage_proof_ref does not match", "; ".join(result.errors))

    def test_missing_sufficiency_certificate_ref_is_rejected(self) -> None:
        sidecar = self._sidecar()
        sidecar["required_question_classifications"][0]["research_sufficiency_certificate_ref"] = ""
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("research_sufficiency_certificate_ref is required", "; ".join(result.errors))

    def test_insufficient_classification_requires_rationale_provenance_and_insufficient_direction(self) -> None:
        valid = self._sidecar(unanswerable_leaf_2=True)
        valid_result = validate_researcher_sidecar_v2(valid, self.qdt)
        self.assertTrue(valid_result.valid, valid_result.errors)

        missing_rationale = copy.deepcopy(valid)
        missing_rationale["required_question_classifications"][1]["unanswerability"]["rationale"] = ""
        self._refresh_digests(missing_rationale)
        result = validate_researcher_sidecar_v2(missing_rationale, self.qdt)
        self.assertFalse(result.valid)
        self.assertIn("unanswerability.rationale is required", "; ".join(result.errors))

        directional = copy.deepcopy(valid)
        directional["required_question_classifications"][1]["impact_direction"] = "supports_yes"
        self._refresh_digests(directional)
        result = validate_researcher_sidecar_v2(directional, self.qdt)
        self.assertFalse(result.valid)
        self.assertIn("impact_direction must be insufficient", "; ".join(result.errors))

    def test_phase8_acceptance_rules_reject_low_quality_accepted_rows(self) -> None:
        sidecar = self._sidecar()
        sidecar["required_question_classifications"][0]["classification_quality"] = "low"
        sidecar["required_question_classifications"][0]["classification_acceptance_status"] = "accepted_for_verification"
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("classification_quality cannot pass to verification", "; ".join(result.errors))

    def test_mixed_classification_requires_supporting_and_opposing_evidence_refs(self) -> None:
        sidecar = self._sidecar()
        first = sidecar["required_question_classifications"][0]
        first["impact_direction"] = "mixed"
        first["evidence_refs"] = [self._evidence_ref("leaf-1"), "retrieval-evidence:leaf-1:opposing"]
        first.pop("evidence_ref", None)
        first["supporting_evidence_refs"] = [self._evidence_ref("leaf-1")]
        first["opposing_evidence_refs"] = ["retrieval-evidence:leaf-1:opposing"]
        sidecar["coverage_proofs"][0]["evidence_refs_assigned"].append("retrieval-evidence:leaf-1:opposing")
        sidecar["coverage_proofs"][0]["evidence_refs_reviewed"].append("retrieval-evidence:leaf-1:opposing")
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)
        self.assertTrue(result.valid, result.errors)

        broken = copy.deepcopy(sidecar)
        broken["required_question_classifications"][0]["opposing_evidence_refs"] = []
        self._refresh_digests(broken)
        result = validate_researcher_sidecar_v2(broken, self.qdt)
        self.assertFalse(result.valid)
        self.assertIn("opposing_evidence_refs are required", "; ".join(result.errors))

    def test_irrelevant_and_insufficient_rows_are_not_evidence_delta_eligible(self) -> None:
        sidecar = self._sidecar()
        first = sidecar["required_question_classifications"][0]
        first["impact_direction"] = "irrelevant"
        first["evidence_strength"] = "none"
        first["classification_acceptance_status"] = "non_scoreable"
        first["evidence_delta_eligible_for_scae"] = True
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("evidence_delta_eligible_for_scae must be false for irrelevant", "; ".join(result.errors))

    def test_invalid_impact_direction_is_rejected(self) -> None:
        sidecar = self._sidecar()
        sidecar["required_question_classifications"][0]["impact_direction"] = "boosts_yes_probability"
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("impact_direction is invalid", "; ".join(result.errors))

    def test_missing_model_execution_context_is_rejected(self) -> None:
        sidecar = self._sidecar()
        del sidecar["required_question_classifications"][0]["model_execution_context"]
        self._refresh_digests(sidecar)

        result = validate_researcher_sidecar_v2(sidecar, self.qdt)

        self.assertFalse(result.valid)
        self.assertIn("model_execution_context must be an object", "; ".join(result.errors))

    def test_required_market_matrix_and_sidecar_digests_are_enforced(self) -> None:
        sidecar = self._sidecar()
        missing = copy.deepcopy(sidecar)
        missing["market_constraints_digest"] = ""
        missing["classification_matrix_digest"] = ""
        missing["sidecar_digest"] = ""

        result = validate_researcher_sidecar_v2(missing, self.qdt)

        self.assertFalse(result.valid)
        joined = "; ".join(result.errors)
        self.assertIn("market_constraints_digest is required", joined)
        self.assertIn("classification_matrix_digest must be a sha256 ref", joined)
        self.assertIn("sidecar_digest must be a sha256 ref", joined)


if __name__ == "__main__":
    unittest.main()
