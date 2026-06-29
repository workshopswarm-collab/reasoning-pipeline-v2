#!/usr/bin/env python3

from __future__ import annotations

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
    materialize_classification_matrix,
)
from researcher_swarm.model_context import resolve_researcher_leaf_nli_model_context  # noqa: E402
from researcher_swarm.retrieval import (  # noqa: E402
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)
from researcher_swarm.supplemental import (  # noqa: E402
    normalize_supplemental_evidence,
    normalize_supplemental_evidence_batch,
    validate_normalized_supplemental_evidence,
)


DISPATCH_CONTEXT = {
    "case_id": "case-1",
    "dispatch_id": "dispatch-1",
    "forecast_timestamp": "2026-06-24T12:00:00+00:00",
    "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
}


def _base_raw_ref(**overrides: Any) -> dict[str, Any]:
    raw = {
        "supplemental_evidence_ref": "supplemental:example",
        "case_id": "case-1",
        "dispatch_id": "dispatch-1",
        "leaf_id": "leaf-1",
        "parent_branch_id": "branch-1",
        "url": "https://independent.example/report?utm_source=ignore&b=1",
        "content": "Independent report says the example status is confirmed.",
        "source_class": "independent_secondary",
        "source_published_at": "2026-06-24T11:00:00+00:00",
        "claim_tuple": {
            "subject": "example",
            "predicate": "status",
            "object_or_value": "confirmed",
            "event_time": "2026-06-24",
            "entity_or_jurisdiction": "global",
            "condition_scope": "unconditional",
            "polarity": "affirmed",
        },
    }
    raw.update(overrides)
    return raw


class SupplementalEvidenceNormalizationTest(unittest.TestCase):
    def test_post_cutoff_supplemental_source_is_rejected(self) -> None:
        record = normalize_supplemental_evidence(
            _base_raw_ref(source_published_at="2026-06-24T12:30:00+00:00"),
            DISPATCH_CONTEXT,
        )

        self.assertEqual(record["normalization_status"], "rejected")
        self.assertEqual(record["temporal_gate_status"], "fail")
        self.assertIn("temporal_isolation_failed", record["rejection_reason_codes"])
        self.assertIn("source_after_cutoff", record["rejection_reason_codes"])
        self.assertTrue(validate_normalized_supplemental_evidence(record).valid)

    def test_protected_primary_access_failure_has_dedicated_status(self) -> None:
        record = normalize_supplemental_evidence(
            _base_raw_ref(
                supplemental_evidence_ref="supplemental:official-blocked",
                fetch_status="protected_primary_access_blocked",
                is_protected_primary=True,
                source_class="official_or_primary",
                content=None,
            ),
            DISPATCH_CONTEXT,
        )

        self.assertEqual(record["normalization_status"], "protected_primary_access_blocked")
        self.assertEqual(record["source_access_status"], "protected_primary_access_blocked")
        self.assertEqual(record["admission_status"], "omitted")
        self.assertIn("protected_primary_access_blocked", record["blockers"])
        self.assertTrue(validate_normalized_supplemental_evidence(record).valid)

    def test_degraded_noncritical_fetch_failure_is_capped_and_not_counted(self) -> None:
        record = normalize_supplemental_evidence(
            _base_raw_ref(
                supplemental_evidence_ref="supplemental:transient",
                fetch_status="timeout",
                content=None,
            ),
            DISPATCH_CONTEXT,
        )

        self.assertEqual(record["normalization_status"], "degraded")
        self.assertEqual(record["source_class"], "unknown")
        self.assertEqual(record["source_family_id"], "source-family-unknown")
        self.assertEqual(record["claim_family_id"], "claim-family-unknown")
        self.assertFalse(record["counts_toward_breadth"])
        self.assertIn("degraded_source_class_capped_unknown", record["blockers"])
        self.assertTrue(validate_normalized_supplemental_evidence(record).valid)

    def test_critical_or_source_of_truth_degraded_path_is_rejected(self) -> None:
        record = normalize_supplemental_evidence(
            _base_raw_ref(
                supplemental_evidence_ref="supplemental:critical-timeout",
                fetch_status="timeout",
                criticality="critical",
                content=None,
            ),
            DISPATCH_CONTEXT,
        )

        self.assertEqual(record["normalization_status"], "rejected")
        self.assertIn(
            "degraded_path_for_critical_or_source_of_truth_forbidden",
            record["rejection_reason_codes"],
        )
        self.assertTrue(validate_normalized_supplemental_evidence(record).valid)

    def test_batch_marks_repeated_claim_or_source_family_non_independent(self) -> None:
        batch = normalize_supplemental_evidence_batch(
            [
                _base_raw_ref(
                    supplemental_evidence_ref="supplemental:first",
                    source_family_id="source-family:shared",
                ),
                _base_raw_ref(
                    supplemental_evidence_ref="supplemental:second",
                    source_family_id="source-family:shared",
                    content="Independent follow-up says the example status is confirmed.",
                ),
            ],
            DISPATCH_CONTEXT,
        )

        self.assertEqual(batch["normalization_summary"]["normalized"], 2)
        self.assertEqual(batch["records"][0]["independence_status"], "independent")
        self.assertEqual(batch["records"][1]["independence_status"], "same_claim_family")
        duplicate_content = normalize_supplemental_evidence_batch(
            [
                _base_raw_ref(
                    supplemental_evidence_ref="supplemental:content-first",
                    source_family_id="source-family:first",
                ),
                _base_raw_ref(
                    supplemental_evidence_ref="supplemental:content-second",
                    source_family_id="source-family:second",
                    claim_tuple={
                        "subject": "example",
                        "predicate": "status",
                        "object_or_value": "pending",
                        "event_time": "2026-06-24",
                        "entity_or_jurisdiction": "global",
                        "condition_scope": "unconditional",
                        "polarity": "uncertain",
                    },
                ),
            ],
            DISPATCH_CONTEXT,
        )
        self.assertEqual(duplicate_content["records"][1]["independence_status"], "syndicated_copy")


class SupplementalMatrixIntegrationTest(unittest.TestCase):
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

    def test_normalized_supplemental_evidence_can_join_classification_matrix(self) -> None:
        packet = self._packet()
        sidecar = self._sidecar(packet)
        first = sidecar["required_question_classifications"][0]
        leaf = self._leaf_by_id()[first["leaf_id"]]
        supplemental_ref = f"supplemental:{first['leaf_id']}:manual"
        normalized = normalize_supplemental_evidence(
            _base_raw_ref(
                supplemental_evidence_ref=supplemental_ref,
                leaf_id=first["leaf_id"],
                parent_branch_id=leaf["parent_branch_id"],
                classification_id=first["classification_id"],
                url=f"https://independent.example/supplemental/{first['leaf_id']}",
            ),
            DISPATCH_CONTEXT,
        )
        self.assertEqual(normalized["normalization_status"], "normalized")

        first.pop("evidence_ref")
        first["supplemental_evidence_ref"] = supplemental_ref
        first["provenance_refs"] = [normalized["normalization_id"]]
        sidecar["coverage_proofs"][0]["supplemental_evidence_refs_reviewed"] = [supplemental_ref]
        self._refresh_sidecar_digests(sidecar)

        with self.assertRaisesRegex(ClassificationMatrixError, "requires CLS-004 normalization"):
            materialize_classification_matrix([sidecar], self.qdt, packet)

        matrix = materialize_classification_matrix(
            [sidecar],
            self.qdt,
            packet,
            normalized_supplemental_evidence=[normalized],
        )

        supplemental_rows = [
            row for row in matrix["classification_slices"]
            if row.get("evidence_source_type") == "supplemental"
        ]
        self.assertEqual(len(supplemental_rows), 1)
        self.assertEqual(supplemental_rows[0]["evidence_ref"], supplemental_ref)
        self.assertEqual(supplemental_rows[0]["normalized_supplemental_evidence_ref"], normalized["normalization_id"])
        self.assertEqual(matrix["normalized_supplemental_evidence_refs"], [supplemental_ref])
        self.assertIn("CLS-004", matrix["scope_boundaries"]["implements"])
        self.assertNotIn("CLS-004", matrix["scope_boundaries"]["not_implemented"])


if __name__ == "__main__":
    unittest.main()
