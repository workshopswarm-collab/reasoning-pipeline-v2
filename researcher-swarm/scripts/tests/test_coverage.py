#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import build_fixture_qdt_candidate, select_qdt_candidate  # noqa: E402
from researcher_swarm.assignments import (  # noqa: E402
    build_leaf_research_assignments,
    compute_leaf_research_assignment_digest,
)
from researcher_swarm.classification import (  # noqa: E402
    build_researcher_sidecar_v2,
    compute_classification_matrix_digest,
    compute_researcher_sidecar_digest,
)
from researcher_swarm.classification_matrix import (  # noqa: E402
    ClassificationMatrixError,
    materialize_classification_matrix,
)
from researcher_swarm.coverage import (  # noqa: E402
    RESEARCHER_EVIDENCE_REVIEW_COVERAGE_BUNDLE_SCHEMA_VERSION,
    ResearcherCoverageProofError,
    build_researcher_evidence_review_coverage_proof_bundle,
    compute_researcher_coverage_proof_bundle_digest,
    validate_researcher_evidence_review_coverage_proof_bundle,
)
from researcher_swarm.isolation import build_researcher_context_isolation_audit  # noqa: E402
from researcher_swarm.model_context import resolve_researcher_leaf_nli_model_context  # noqa: E402
from researcher_swarm.retrieval import (  # noqa: E402
    build_evidence_chunk,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)


def _contains_forbidden_authority_text(value: Any) -> bool:
    text = json.dumps(value, sort_keys=True)
    forbidden = ("probability", "fair_value", "fair-value", "interval", "decision", "scae")
    return any(term in text.lower() for term in forbidden)


class ResearcherEvidenceReviewCoverageProofTest(unittest.TestCase):
    def setUp(self) -> None:
        handoff = {
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
                "output_schema_version": "question-decomposition/v1",
            },
        }
        self.qdt = select_qdt_candidate([build_fixture_qdt_candidate(handoff)])
        self.evidence_packet = {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "forecast_timestamp": "2026-06-24T12:00:00+00:00",
            "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            "market_rules": {"resolution_url": "https://example.com/rules"},
            "official_source_hints": ["https://example.com/official"],
        }
        self.model_context = resolve_researcher_leaf_nli_model_context()

    def _evidence(
        self,
        context: dict[str, Any],
        *,
        attempt_ref: str,
        canonical_url: str,
        source_class: str = "independent_secondary",
        source_family_id: str | None = None,
        claim_family_id: str = "claim-family-default",
    ) -> dict[str, Any]:
        item = build_retrieval_evidence_item(
            case_id="case-1",
            dispatch_id="dispatch-1",
            leaf_id=context["leaf_id"],
            parent_branch_id=context["parent_branch_id"],
            retrieval_transport="browser",
            transport_attempt_ref=attempt_ref,
            requested_url=canonical_url,
            final_url=canonical_url,
            canonical_url=canonical_url,
            source_family_id=source_family_id or f"source-family-{attempt_ref}",
            source_class=source_class,
            temporal_gate_status="pass",
            source_published_at="2026-06-24T11:30:00+00:00",
            captured_at="2026-06-24T12:01:00+00:00",
            artifact_generated_at="2026-06-24T12:01:00+00:00",
            retrieval_capture_for_dispatch=True,
            claim_family_resolution_refs=[claim_family_id],
            admission_reason_codes=["manual_fixture_selected"],
        )
        if source_class == "official_or_primary":
            item["deterministic_source_class_proof"] = True
            item["source_class_resolution_method"] = "manual_fixture"
        return item

    def _packet(self) -> dict[str, Any]:
        contexts = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)
        selected = []
        chunks = []
        for context in contexts:
            selected.append(
                self._evidence(
                    context,
                    attempt_ref=f"{context['leaf_id']}-official",
                    canonical_url=f"https://example.com/official/{context['leaf_id']}",
                    source_class="official_or_primary",
                    source_family_id=f"source-family-{context['leaf_id']}-official",
                    claim_family_id=f"claim-family-{context['leaf_id']}-official",
                )
            )
            selected.append(
                self._evidence(
                    context,
                    attempt_ref=f"{context['leaf_id']}-secondary",
                    canonical_url=f"https://independent.example/{context['leaf_id']}",
                    source_class="independent_secondary",
                    source_family_id=f"source-family-{context['leaf_id']}-secondary",
                    claim_family_id=f"claim-family-{context['leaf_id']}-secondary",
                )
            )
            if "expert_or_specialist" in context["sufficiency_requirements"].get("required_source_classes", []):
                selected.append(
                    self._evidence(
                        context,
                        attempt_ref=f"{context['leaf_id']}-expert",
                        canonical_url=f"https://expert.example/{context['leaf_id']}",
                        source_class="expert_or_specialist",
                        source_family_id=f"source-family-{context['leaf_id']}-expert",
                        claim_family_id=f"claim-family-{context['leaf_id']}-expert",
                    )
                )
        for item in selected:
            text = (
                f"Coverage certified excerpt for {item['transport_attempt_ref']} with enough bounded "
                "source detail for researcher classification. "
                * 8
            )
            chunk = build_evidence_chunk(
                evidence_ref=item["evidence_ref"],
                content_artifact_ref=f"artifact:browser-capture/{item['transport_attempt_ref']}",
                chunk_index=0,
                char_start=0,
                char_end=len(text),
                text=text,
                excerpt_policy="bounded_excerpt",
            )
            item["chunk_refs"] = [chunk["chunk_ref"]]
            chunks.append(chunk)
        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        packet["evidence_chunks"] = chunks
        finalized = finalize_retrieval_packet_for_dispatch(packet)
        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        return finalized

    def _leaf_by_id(self) -> dict[str, dict[str, Any]]:
        return {leaf["leaf_id"]: leaf for leaf in self.qdt["required_leaf_questions"]}

    def _provenance_by_evidence_ref(self, packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {item["evidence_ref"]: item for item in packet["retrieval_evidence_provenance_slices"]}

    def _certificate_by_id(self, packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            certificate["certificate_id"]: certificate
            for certificate in packet["leaf_research_sufficiency_certificates"]
        }

    def _assignment_by_leaf_id(self, assignments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {assignment["leaf_id"]: assignment for assignment in assignments}

    def _first_assignment_evidence(
        self,
        packet: dict[str, Any],
        assignment: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        evidence_ref = assignment["assigned_evidence_refs"][0]["evidence_ref"]
        provenance = self._provenance_by_evidence_ref(packet)[evidence_ref]
        for result in packet["leaf_retrieval_results"]:
            for evidence in result["selected_evidence"]:
                if evidence["evidence_ref"] == evidence_ref:
                    return evidence, provenance
        raise AssertionError(f"missing evidence fixture {evidence_ref}")

    def _classification(
        self,
        packet: dict[str, Any],
        assignment: dict[str, Any],
    ) -> dict[str, Any]:
        evidence, provenance = self._first_assignment_evidence(packet, assignment)
        leaf = self._leaf_by_id()[assignment["leaf_id"]]
        return {
            "leaf_id": assignment["leaf_id"],
            "parent_branch_id": assignment["parent_branch_id"],
            "leaf_condition_scope": leaf.get("leaf_condition_scope", "unconditional"),
            "evidence_ref": evidence["evidence_ref"],
            "research_sufficiency_certificate_ref": assignment["research_sufficiency_certificate_ref"],
            "coverage_proof_ref": assignment["artifact_outputs"]["coverage_proof_ref"],
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
            "provenance_refs": [provenance["provenance_id"]],
        }

    def _coverage(self, assignment: dict[str, Any]) -> dict[str, Any]:
        evidence_refs = [item["evidence_ref"] for item in assignment["assigned_evidence_refs"]]
        return {
            "coverage_proof_id": assignment["artifact_outputs"]["coverage_proof_ref"],
            "leaf_id": assignment["leaf_id"],
            "research_sufficiency_certificate_ref": assignment["research_sufficiency_certificate_ref"],
            "retrieval_breadth_coverage_ref": assignment["retrieval_breadth_coverage_ref"],
            "evidence_refs_assigned": list(evidence_refs),
            "evidence_refs_reviewed": list(evidence_refs),
            "source_class_ids_reviewed": sorted(
                {item["source_class"] for item in assignment["assigned_evidence_refs"]}
            ),
            "claim_family_ids_reviewed": sorted(
                {
                    item["claim_family_id"]
                    for item in assignment["assigned_evidence_refs"]
                    if item.get("claim_family_id")
                }
            ),
            "source_family_ids_reviewed": sorted(
                {item["source_family_id"] for item in assignment["assigned_evidence_refs"]}
            ),
            "requirements_reviewed": list(assignment["sufficiency_requirement_refs"]),
            "requirements_answered": list(assignment["sufficiency_requirement_refs"]),
            "requirements_unanswered": [],
            "required_value_fields_extracted": list(assignment["required_value_field_ids"]),
            "required_negative_checks_completed": list(assignment["required_negative_check_ids"]),
            "source_gap_flags": [],
            "structural_unanswerability_acknowledged": False,
            "machine_readability_status": "schema_valid",
        }

    def _sidecar(self, packet: dict[str, Any], assignments: list[dict[str, Any]]) -> dict[str, Any]:
        assignments_by_leaf = self._assignment_by_leaf_id(assignments)
        leaf_ids = [leaf["leaf_id"] for leaf in self.qdt["required_leaf_questions"]]
        return build_researcher_sidecar_v2(
            qdt=self.qdt,
            required_question_classifications=[
                self._classification(packet, assignments_by_leaf[leaf_id]) for leaf_id in leaf_ids
            ],
            coverage_proofs=[self._coverage(assignments_by_leaf[leaf_id]) for leaf_id in leaf_ids],
            model_execution_context_ref="artifact:model-execution-context:researcher-leaf-nli",
            model_execution_context=self.model_context,
        )

    def _refresh_sidecar_digests(self, sidecar: dict[str, Any]) -> None:
        sidecar["classification_matrix_digest"] = compute_classification_matrix_digest(
            sidecar["required_question_classifications"]
        )
        sidecar["sidecar_digest"] = compute_researcher_sidecar_digest(sidecar)

    def _inputs(self) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any],
        dict[str, Any],
    ]:
        packet = self._packet()
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)
        audits = [build_researcher_context_isolation_audit(assignment) for assignment in assignments]
        sidecar = self._sidecar(packet, assignments)
        matrix = materialize_classification_matrix([sidecar], self.qdt, packet)
        return packet, assignments, audits, sidecar, matrix

    def _bundle(
        self,
        packet: dict[str, Any],
        assignments: list[dict[str, Any]],
        audits: list[dict[str, Any]],
        sidecar: dict[str, Any],
        matrix: dict[str, Any],
    ) -> dict[str, Any]:
        return build_researcher_evidence_review_coverage_proof_bundle(
            qdt=self.qdt,
            sidecars=[sidecar],
            classification_matrix=matrix,
            assignments=assignments,
            isolation_audits=audits,
            retrieval_packet=packet,
        )

    def test_builds_deterministic_cls005_coverage_bundle(self) -> None:
        packet, assignments, audits, sidecar, matrix = self._inputs()

        bundle = self._bundle(packet, assignments, audits, sidecar, matrix)
        second = self._bundle(packet, assignments, audits, sidecar, matrix)

        self.assertEqual(bundle["schema_version"], RESEARCHER_EVIDENCE_REVIEW_COVERAGE_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(bundle["feature_id"], "CLS-005")
        self.assertEqual(bundle["bundle_digest"], second["bundle_digest"])
        self.assertEqual(bundle["bundle_digest"], compute_researcher_coverage_proof_bundle_digest(bundle))
        self.assertEqual(len(bundle["coverage_proofs"]), len(assignments))
        self.assertTrue(validate_researcher_evidence_review_coverage_proof_bundle(bundle).valid)
        self.assertFalse(_contains_forbidden_authority_text(bundle))

        first = bundle["coverage_proofs"][0]
        self.assertEqual(first["coverage_status"], "complete")
        self.assertEqual(first["reason_codes"], [])
        self.assertEqual(set(first["assigned_evidence_refs"]), set(first["reviewed_evidence_refs"]))
        self.assertEqual(set(first["certificate_evidence_refs"]), set(first["reviewed_evidence_refs"]))
        self.assertTrue(set(first["classified_evidence_refs"]) <= set(first["reviewed_evidence_refs"]))
        self.assertEqual(first["authority_boundary"]["numeric_estimate_authority"], False)
        self.assertEqual(first["authority_boundary"]["downstream_ledger_authority"], False)

    def test_reviewed_evidence_must_be_assigned_by_cls006(self) -> None:
        packet, assignments, audits, sidecar, matrix = self._inputs()
        broken = copy.deepcopy(assignments)
        broken[0]["assigned_evidence_refs"] = broken[0]["assigned_evidence_refs"][1:]
        broken[0]["assignment_digest"] = compute_leaf_research_assignment_digest(broken[0])
        broken_audits = [build_researcher_context_isolation_audit(assignment) for assignment in broken]

        with self.assertRaisesRegex(ResearcherCoverageProofError, "reviewed_unassigned_evidence"):
            self._bundle(packet, broken, broken_audits, sidecar, matrix)

    def test_unreviewed_extra_assignment_evidence_fails_closed(self) -> None:
        packet, assignments, audits, sidecar, matrix = self._inputs()
        broken = copy.deepcopy(assignments)
        extra = copy.deepcopy(broken[0]["assigned_evidence_refs"][0])
        extra["evidence_ref"] = "retrieval-evidence-extra"
        broken[0]["assigned_evidence_refs"].append(extra)
        broken[0]["assignment_digest"] = compute_leaf_research_assignment_digest(broken[0])
        broken_audits = [build_researcher_context_isolation_audit(assignment) for assignment in broken]

        with self.assertRaisesRegex(ResearcherCoverageProofError, "assigned_evidence_not_reviewed"):
            self._bundle(packet, broken, broken_audits, sidecar, matrix)

    def test_requirements_and_certificates_must_be_addressed(self) -> None:
        packet, assignments, audits, sidecar, matrix = self._inputs()
        broken = copy.deepcopy(assignments)
        broken[0]["sufficiency_requirement_refs"].append("qdt-sufficiency-requirement-extra")
        broken[0]["assignment_digest"] = compute_leaf_research_assignment_digest(broken[0])
        broken_audits = [build_researcher_context_isolation_audit(assignment) for assignment in broken]

        with self.assertRaisesRegex(ResearcherCoverageProofError, "assignment_requirement_not_reviewed"):
            self._bundle(packet, broken, broken_audits, sidecar, matrix)

    def test_skipped_evidence_or_negative_checks_fail_closed(self) -> None:
        packet, _assignments, _audits, sidecar, _matrix = self._inputs()
        mutations = {
            "missing reviewed refs": ("evidence_refs_reviewed", []),
            "required negative checks not completed": ("required_negative_checks_completed", []),
        }
        for expected, (field, value) in mutations.items():
            with self.subTest(expected=expected):
                broken = copy.deepcopy(sidecar)
                broken["coverage_proofs"][0][field] = value
                self._refresh_sidecar_digests(broken)

                with self.assertRaisesRegex(ClassificationMatrixError, expected):
                    materialize_classification_matrix([broken], self.qdt, packet)

    def test_missing_or_blocked_isolation_audit_fails_closed(self) -> None:
        packet, assignments, audits, sidecar, matrix = self._inputs()
        blocked_audits = list(audits)
        blocked_audits[0] = build_researcher_context_isolation_audit(assignments[0], fresh_context=False)

        with self.assertRaisesRegex(ResearcherCoverageProofError, "isolation audit is not launch allowed"):
            self._bundle(packet, assignments, blocked_audits, sidecar, matrix)

    def test_bundle_validator_rejects_forbidden_authority_terms(self) -> None:
        packet, assignments, audits, sidecar, matrix = self._inputs()
        bundle = self._bundle(packet, assignments, audits, sidecar, matrix)
        broken = copy.deepcopy(bundle)
        broken["coverage_proofs"][0]["macro_probability"] = 0.5

        result = validate_researcher_evidence_review_coverage_proof_bundle(broken)

        self.assertFalse(result.valid)
        self.assertIn("forbidden authority term", "; ".join(result.errors))


if __name__ == "__main__":
    unittest.main()
