#!/usr/bin/env python3

from __future__ import annotations

import copy
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
from researcher_swarm.classification import (  # noqa: E402
    build_researcher_sidecar_v2,
    compute_classification_matrix_digest,
    compute_researcher_sidecar_digest,
)
from researcher_swarm.classification_matrix import (  # noqa: E402
    ClassificationMatrixError,
    compute_materialized_classification_matrix_digest,
    materialize_classification_matrix,
)
from researcher_swarm.model_context import resolve_researcher_leaf_nli_model_context  # noqa: E402
from researcher_swarm.retrieval import (  # noqa: E402
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)


class ClassificationMatrixMaterializationTest(unittest.TestCase):
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
        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        finalized = finalize_retrieval_packet_for_dispatch(packet)
        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        return finalized

    def _leaf_by_id(self) -> dict[str, dict[str, Any]]:
        return {leaf["leaf_id"]: leaf for leaf in self.qdt["required_leaf_questions"]}

    def _provenance_by_evidence_ref(self, packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            item["evidence_ref"]: item
            for item in packet["retrieval_evidence_provenance_slices"]
        }

    def _result_by_leaf_id(self, packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {result["leaf_id"]: result for result in packet["leaf_retrieval_results"]}

    def _certificate_by_leaf_id(self, packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            certificate["leaf_id"]: certificate
            for certificate in packet["leaf_research_sufficiency_certificates"]
        }

    def _classification(self, packet: dict[str, Any], leaf_id: str) -> dict[str, Any]:
        result = self._result_by_leaf_id(packet)[leaf_id]
        evidence = result["selected_evidence"][0]
        provenance = self._provenance_by_evidence_ref(packet)[evidence["evidence_ref"]]
        certificate = self._certificate_by_leaf_id(packet)[leaf_id]
        leaf = self._leaf_by_id()[leaf_id]
        return {
            "leaf_id": leaf_id,
            "parent_branch_id": leaf["parent_branch_id"],
            "leaf_condition_scope": leaf.get("leaf_condition_scope", "unconditional"),
            "evidence_ref": evidence["evidence_ref"],
            "research_sufficiency_certificate_ref": certificate["certificate_id"],
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
            "provenance_refs": [provenance["provenance_id"]],
        }

    def _coverage(self, packet: dict[str, Any], leaf_id: str) -> dict[str, Any]:
        result = self._result_by_leaf_id(packet)[leaf_id]
        evidence_refs = [item["evidence_ref"] for item in result["selected_evidence"]]
        source_classes = sorted({item["source_class"] for item in result["selected_evidence"]})
        claim_families = sorted(
            {
                claim_family_id
                for item in result["selected_evidence"]
                for claim_family_id in item["claim_family_ids"]
            }
        )
        source_families = sorted({item["source_family_id"] for item in result["selected_evidence"]})
        certificate = self._certificate_by_leaf_id(packet)[leaf_id]
        requirements = self._leaf_by_id()[leaf_id]["research_sufficiency_requirements"]
        return {
            "coverage_proof_id": f"coverage-proof:{leaf_id}",
            "leaf_id": leaf_id,
            "research_sufficiency_certificate_ref": certificate["certificate_id"],
            "retrieval_breadth_coverage_ref": certificate["breadth_coverage_ref"],
            "evidence_refs_assigned": list(evidence_refs),
            "evidence_refs_reviewed": list(evidence_refs),
            "source_class_ids_reviewed": source_classes,
            "claim_family_ids_reviewed": claim_families,
            "source_family_ids_reviewed": source_families,
            "requirements_reviewed": [certificate["requirement_ref"]],
            "requirements_answered": [certificate["requirement_ref"]],
            "requirements_unanswered": [],
            "required_value_fields_extracted": list(requirements["required_value_fields"]),
            "required_negative_checks_completed": list(requirements["required_negative_checks"]),
            "source_gap_flags": [],
            "structural_unanswerability_acknowledged": False,
            "machine_readability_status": "schema_valid",
        }

    def _sidecar(self, packet: dict[str, Any]) -> dict[str, Any]:
        leaf_ids = [leaf["leaf_id"] for leaf in self.qdt["required_leaf_questions"]]
        return build_researcher_sidecar_v2(
            qdt=self.qdt,
            required_question_classifications=[
                self._classification(packet, leaf_id) for leaf_id in leaf_ids
            ],
            coverage_proofs=[self._coverage(packet, leaf_id) for leaf_id in leaf_ids],
            model_execution_context_ref="artifact:model-execution-context:researcher-leaf-nli",
            model_execution_context=self.model_context,
        )

    def _refresh_sidecar_digests(self, sidecar: dict[str, Any]) -> None:
        sidecar["classification_matrix_digest"] = compute_classification_matrix_digest(
            sidecar["required_question_classifications"]
        )
        sidecar["sidecar_digest"] = compute_researcher_sidecar_digest(sidecar)

    def test_valid_sidecar_yields_classification_provenance_and_coverage_slices(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)

        matrix = materialize_classification_matrix([sidecar], self.qdt, packet)

        self.assertEqual(matrix["feature_id"], "CLS-003")
        self.assertEqual(len(matrix["classification_slices"]), len(self.qdt["required_leaf_questions"]))
        self.assertEqual(len(matrix["provenance_slices"]), len(matrix["classification_slices"]))
        self.assertEqual(len(matrix["coverage_proof_slices"]), len(self.qdt["required_leaf_questions"]))
        self.assertEqual(
            matrix["matrix_digest"],
            compute_materialized_classification_matrix_digest(
                matrix["classification_slices"],
                matrix["provenance_slices"],
                matrix["coverage_proof_slices"],
            ),
        )

        first = matrix["classification_slices"][0]
        self.assertTrue(first["ledger_ready"])
        self.assertEqual(first["surface_name"], "classification_lane_evidence_classification_slices")
        self.assertEqual(first["spec_surface_name"], "persona_evidence_classification_slices")
        self.assertIn(first["leaf_id"], self._leaf_by_id())
        self.assertEqual(first["condition_scope"], self._leaf_by_id()[first["leaf_id"]]["leaf_condition_scope"])
        self.assertTrue(first["evidence_ref"].startswith("retrieval-evidence-"))
        self.assertTrue(first["source_family_id"].startswith("source-family-"))
        self.assertTrue(first["claim_family_id"].startswith("claim-family-"))
        self.assertEqual(first["research_sufficiency_certificate_ref"], self._certificate_by_leaf_id(packet)[first["leaf_id"]]["certificate_id"])
        self.assertEqual(first["coverage_proof_ref"], f"coverage-proof:{first['leaf_id']}")
        self.assertEqual(first["model_execution_context_ref"], sidecar["model_execution_context_ref"])
        self.assertEqual(first["model_execution_context_sha256"], sidecar["model_execution_context_sha256"])
        self.assertEqual(first["evidence_quality_dimensions"]["source_authority"], "high")

        coverage = matrix["coverage_proof_slices"][0]
        self.assertTrue(coverage["does_not_mark_cls005_ready"])
        self.assertEqual(coverage["coverage_feature_scope"], "cls003_matrix_completeness_support_only")
        self.assertEqual(matrix["scope_boundaries"]["implements"], ["CLS-003"])
        self.assertIn("CLS-005", matrix["scope_boundaries"]["not_implemented"])

    def test_provenance_refs_are_required_and_resolvable(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)
        sidecar["required_question_classifications"][0]["provenance_refs"] = []
        self._refresh_sidecar_digests(sidecar)

        with self.assertRaisesRegex(ClassificationMatrixError, "accepted classifications require provenance_refs"):
            materialize_classification_matrix([sidecar], self.qdt, packet)

        sidecar = self._sidecar(packet)
        sidecar["required_question_classifications"][0]["provenance_refs"] = ["retrieval-provenance:missing"]
        self._refresh_sidecar_digests(sidecar)

        with self.assertRaisesRegex(ClassificationMatrixError, "provenance_refs not resolvable"):
            materialize_classification_matrix([sidecar], self.qdt, packet)

    def test_composite_multi_claim_evidence_splits_or_rejects_deterministically(self) -> None:
        packet = self._packet()
        first_leaf_id = self.qdt["required_leaf_questions"][0]["leaf_id"]
        first_evidence = self._result_by_leaf_id(packet)[first_leaf_id]["selected_evidence"][0]
        first_evidence["claim_family_ids"] = ["claim-family:aaa", "claim-family:bbb"]
        sidecar = self._sidecar(packet)

        matrix = materialize_classification_matrix([sidecar], self.qdt, packet)
        split_rows = [
            row for row in matrix["classification_slices"]
            if row["leaf_id"] == first_leaf_id and row["evidence_ref"] == first_evidence["evidence_ref"]
        ]
        self.assertEqual([row["claim_family_id"] for row in split_rows], ["claim-family:aaa", "claim-family:bbb"])
        self.assertTrue(all(row["claim_split_status"] == "split_from_evidence_claim_families" for row in split_rows))

        with self.assertRaisesRegex(ClassificationMatrixError, "composite_multi_claim_classification"):
            materialize_classification_matrix(
                [sidecar],
                self.qdt,
                packet,
                composite_claim_policy="reject",
            )

    def test_condition_scoped_classification_retains_scope(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)
        sidecar["required_question_classifications"][0]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_sidecar_digests(sidecar)

        matrix = materialize_classification_matrix([sidecar], self.qdt, packet)

        row = next(
            item for item in matrix["classification_slices"]
            if item["classification_id"] == sidecar["required_question_classifications"][0]["classification_id"]
        )
        self.assertEqual(row["condition_scope"], "target_given_upstream")

    def test_coverage_proof_cannot_claim_unassigned_evidence(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)
        sidecar["coverage_proofs"][0]["evidence_refs_reviewed"].append("retrieval-evidence:unassigned")
        self._refresh_sidecar_digests(sidecar)

        with self.assertRaisesRegex(ClassificationMatrixError, "reviewed_unassigned_evidence"):
            materialize_classification_matrix([sidecar], self.qdt, packet)

    def test_coverage_proof_must_address_certificate_requirement(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)
        sidecar["coverage_proofs"][0]["requirements_reviewed"] = []
        self._refresh_sidecar_digests(sidecar)

        with self.assertRaisesRegex(ClassificationMatrixError, "research_requirement_not_reviewed"):
            materialize_classification_matrix([sidecar], self.qdt, packet)

    def test_invalid_sidecar_is_rejected_before_materialization(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)
        broken = copy.deepcopy(sidecar)
        broken["required_question_classifications"][0]["impact_direction"] = "probability_up"
        self._refresh_sidecar_digests(broken)

        with self.assertRaisesRegex(ClassificationMatrixError, "researcher sidecar invalid"):
            materialize_classification_matrix([broken], self.qdt, packet)


if __name__ == "__main__":
    unittest.main()
