#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.verification import (  # noqa: E402
    build_direction_verification_slices,
    build_quality_verification_slices,
    build_researcher_verification_bundle,
    build_scae_readiness_reconciliation,
)
from researcher_swarm.classification import validate_researcher_sidecar_v2  # noqa: E402


class ResearcherVerificationTest(unittest.TestCase):
    def test_probability_bearing_sidecar_is_rejected_before_scae(self) -> None:
        sidecar = {
            "artifact_type": "researcher_sidecar",
            "schema_version": "researcher-sidecar/v2",
            "sidecar_contract_ref": "schema:researcher-sidecar/v2",
            "classification_contract_ref": "schema:researcher-classification/v1",
            "coverage_contract_ref": "schema:researcher-coverage-proof/v1",
            "sidecar_id": "sidecar-probability",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "market_constraints_digest": "sha256:" + "1" * 64,
            "model_execution_context_ref": "artifact:model-context",
            "model_execution_context_sha256": "sha256:" + "2" * 64,
            "required_question_classifications": [
                {
                    "schema_version": "researcher-classification/v1",
                    "classification_id": "classification-probability",
                    "leaf_id": "leaf-1",
                    "probability": 0.73,
                }
            ],
            "coverage_proofs": [{"coverage_proof_id": "coverage-proof:leaf-1", "leaf_id": "leaf-1"}],
            "classification_matrix_digest": "sha256:" + "3" * 64,
            "sidecar_digest": "sha256:" + "4" * 64,
        }
        qdt = {
            "schema_version": "question-decomposition/v1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "market_reality_constraints_digest": "sha256:" + "1" * 64,
            "required_leaf_questions": [{"leaf_id": "leaf-1"}],
        }

        result = validate_researcher_sidecar_v2(sidecar, qdt)

        self.assertFalse(result.valid)
        self.assertTrue(any("probability is forbidden" in error for error in result.errors))

    def _classification(
        self,
        *,
        slice_id: str = "classification-slice-1",
        classification_id: str = "classification-1",
        leaf_id: str = "leaf-1",
        impact_direction: str = "supports_yes",
        value: str = "market_resolves_yes",
        source_class: str = "official_or_primary",
        temporal_gate_status: str = "pass",
        evidence_strength: str = "strong",
        classification_confidence: str = "high",
        classification_quality: str = "high",
        quality: dict[str, str] | None = None,
        ledger_ready: bool = True,
        included_for_scae: bool | None = None,
        classification_acceptance_status: str = "accepted_for_verification",
        evidence_delta_eligible_for_scae: bool | None = None,
        source_family_id: str | None = None,
        claim_family_id: str | None = None,
    ) -> dict[str, Any]:
        if included_for_scae is None:
            included_for_scae = ledger_ready
        if evidence_delta_eligible_for_scae is None:
            evidence_delta_eligible_for_scae = impact_direction in {"supports_yes", "supports_no", "mixed"}
        return {
            "slice_id": slice_id,
            "classification_id": classification_id,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": leaf_id,
            "condition_scope": "unconditional",
            "evidence_ref": f"evidence-{classification_id}",
            "source_class": source_class,
            "source_family_id": source_family_id or f"source-family-{classification_id}",
            "claim_family_id": claim_family_id or f"claim-family-{classification_id}",
            "impact_direction": impact_direction,
            "evidence_strength": evidence_strength,
            "classification_confidence": classification_confidence,
            "classification_quality": classification_quality,
            "classification_acceptance_status": classification_acceptance_status,
            "evidence_delta_eligible_for_scae": evidence_delta_eligible_for_scae,
            "answer_value_extraction": {
                "field_name": "outcome",
                "value": value,
                "normalization_status": "parsed",
            },
            "evidence_quality_dimensions": quality
            or {
                "source_authority": "high",
                "directness": "direct",
                "recency": "fresh",
                "specificity": "specific",
            },
            "temporal_gate_status": temporal_gate_status,
            "research_sufficiency_certificate_ref": f"research-sufficiency:{leaf_id}",
            "coverage_proof_ref": f"coverage-proof:{leaf_id}",
            "ledger_ready": ledger_ready,
            "included_for_scae": included_for_scae,
        }

    def _matrix(self, classifications: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "artifact_type": "researcher_classification_matrix",
            "matrix_id": "matrix-1",
            "matrix_digest": "sha256:" + "1" * 64,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "classification_slices": classifications,
            "provenance_slices": [
                {
                    "slice_id": f"provenance-{item['slice_id']}",
                    "classification_slice_ref": item["slice_id"],
                    "source_class": item.get("source_class"),
                    "leaf_id": item.get("leaf_id"),
                    "condition_scope": item.get("condition_scope"),
                    "evidence_ref": item.get("evidence_ref"),
                    "source_family_id": item.get("source_family_id"),
                    "claim_family_id": item.get("claim_family_id"),
                    "canonical_source_id": f"source-{item['classification_id']}",
                    "research_sufficiency_certificate_ref": item.get("research_sufficiency_certificate_ref"),
                    "coverage_proof_ref": item.get("coverage_proof_ref"),
                    "provenance_refs": [
                        item["evidence_ref"],
                        item["coverage_proof_ref"],
                        item["research_sufficiency_certificate_ref"],
                    ],
                }
                for item in classifications
            ],
        }

    def _qdt(self, leaf_ids: list[str] | None = None, *, static_weight: str = "medium") -> dict[str, Any]:
        return {
            "required_leaf_questions": [
                {
                    "leaf_id": leaf_id,
                    "bayesian_weighting": {"static_information_weight": static_weight},
                }
                for leaf_id in (leaf_ids or ["leaf-1"])
            ]
        }

    def _coverage_bundle(self, matrix: dict[str, Any], leaf_ids: list[str] | None = None) -> dict[str, Any]:
        return {
            "feature_id": "CLS-005",
            "bundle_digest": "sha256:" + "2" * 64,
            "source_matrix": {
                "matrix_id": matrix["matrix_id"],
                "matrix_digest": matrix["matrix_digest"],
            },
            "coverage_proofs": [
                {
                    "leaf_id": leaf_id,
                    "coverage_proof_ref": f"coverage-proof:{leaf_id}",
                    "coverage_status": "complete",
                }
                for leaf_id in (leaf_ids or ["leaf-1"])
            ],
            "coverage_summary": {
                "all_assigned_evidence_reviewed": True,
                "all_certificate_evidence_reviewed": True,
                "all_required_outputs_addressed": True,
                "all_context_isolation_audits_launch_allowed": True,
            },
        }

    def _sufficiency_reconciliation(self, leaf_ids: list[str] | None = None, *, status: str = "scae_ready_high_certainty") -> dict[str, Any]:
        return {
            "research_sufficiency_reconciliation_slices": [
                {
                    "leaf_id": leaf_id,
                    "research_sufficiency_reconciliation_ref": f"research-sufficiency-reconcile:{leaf_id}",
                    "research_sufficiency_reconciliation_status": status,
                    "research_sufficiency_certificate_ref": f"research-sufficiency:{leaf_id}",
                }
                for leaf_id in (leaf_ids or ["leaf-1"])
            ]
        }

    def _binary_constraints(self) -> dict[str, Any]:
        return {
            "contract_structure": "binary",
            "side_mapping": {
                "yes": {"outcome": "yes", "resolves_to": "market_resolves_yes"},
                "no": {"outcome": "no", "resolves_to": "market_resolves_no"},
            },
        }

    def test_neutral_direction_passthrough_without_sign(self) -> None:
        matrix = self._matrix(
            [
                self._classification(
                    impact_direction="neutral",
                    value="background",
                    ledger_ready=False,
                    included_for_scae=False,
                    classification_acceptance_status="non_scoreable",
                    evidence_delta_eligible_for_scae=False,
                )
            ]
        )

        result = build_direction_verification_slices(matrix)

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "neutral")
        self.assertEqual(row["method_status"], "verified")
        self.assertTrue(row["accepted_for_scae"])
        self.assertIn("neutral_passthrough", row["reason_codes"])

    def test_mixed_direction_becomes_branch_netting_candidate(self) -> None:
        row = self._classification(impact_direction="mixed")
        row["evidence_refs"] = ["evidence-support", "evidence-oppose"]
        row["supporting_evidence_refs"] = ["evidence-support"]
        row["opposing_evidence_refs"] = ["evidence-oppose"]
        matrix = self._matrix([row])

        result = build_direction_verification_slices(matrix)

        verified = result.direction_verification_slices[0]
        self.assertEqual(verified["verified_direction"], "mixed")
        self.assertEqual(verified["verification_status"], "accepted")
        self.assertIn("mixed_branch_netting_candidate", verified["reason_codes"])

    def test_mixed_direction_without_both_sides_is_quarantined(self) -> None:
        row = self._classification(impact_direction="mixed")
        row["evidence_refs"] = ["evidence-support"]
        row["supporting_evidence_refs"] = ["evidence-support"]
        matrix = self._matrix([row])

        result = build_direction_verification_slices(matrix)

        verified = result.direction_verification_slices[0]
        self.assertEqual(verified["verified_direction"], "ambiguous")
        self.assertEqual(verified["verification_status"], "quarantined")
        self.assertIn("mixed_evidence_refs_missing", verified["reason_codes"])

    def test_irrelevant_direction_is_verified_no_delta_passthrough(self) -> None:
        matrix = self._matrix(
            [
                self._classification(
                    impact_direction="irrelevant",
                    evidence_strength="none",
                    ledger_ready=False,
                    included_for_scae=False,
                    classification_acceptance_status="non_scoreable",
                    evidence_delta_eligible_for_scae=False,
                )
            ]
        )

        result = build_direction_verification_slices(matrix)

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "irrelevant")
        self.assertEqual(row["verification_status"], "accepted")
        self.assertIn("irrelevant_no_delta_passthrough", row["reason_codes"])

    def test_side_map_contradiction_is_excluded(self) -> None:
        constraints = self._binary_constraints()
        constraints["side_mapping"]["no"]["resolves_to"] = "market_resolves_yes"

        result = build_direction_verification_slices(
            self._matrix([self._classification()]),
            market_reality_constraints=constraints,
        )

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "excluded")
        self.assertEqual(row["method_status"], "excluded")
        self.assertEqual(row["verification_status"], "excluded")
        self.assertIn("side_mapping_conflict", row["reason_codes"])

    def test_ambiguous_direction_is_quarantined(self) -> None:
        constraints = {
            "contract_structure": "other",
            "side_mapping": {
                "primary": {"outcome": "primary", "resolves_to": "market_primary_outcome"},
            },
        }

        result = build_direction_verification_slices(
            self._matrix([self._classification()]),
            market_reality_constraints=constraints,
        )

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "ambiguous")
        self.assertEqual(row["method_status"], "quarantined")
        self.assertEqual(row["verification_status"], "quarantined")
        self.assertIn("direction_ambiguous", row["reason_codes"])

    def test_coverage_after_exclusion_is_recorded(self) -> None:
        accepted = self._classification(
            slice_id="classification-slice-accepted",
            classification_id="classification-accepted",
            leaf_id="leaf-1",
            impact_direction="supports_yes",
            value="market_resolves_yes",
        )
        contradicted = self._classification(
            slice_id="classification-slice-contradicted",
            classification_id="classification-contradicted",
            leaf_id="leaf-1",
            impact_direction="supports_yes",
            value="market_resolves_no",
        )

        result = build_direction_verification_slices(
            self._matrix([accepted, contradicted]),
            market_reality_constraints=self._binary_constraints(),
        )

        row_by_id = {
            row["classification_id"]: row
            for row in result.direction_verification_slices
        }
        excluded = row_by_id["classification-contradicted"]
        self.assertEqual(excluded["verification_status"], "excluded")
        self.assertEqual(excluded["coverage_after_exclusion_status"], "covered_after_exclusion")
        self.assertTrue(excluded["deadlock_safe_exclusion"])
        self.assertIn("deadlock_safe_exclusion_with_remaining_coverage", excluded["reason_codes"])

    def test_all_non_neutral_rows_receive_direction_verification(self) -> None:
        matrix = self._matrix(
            [
                self._classification(slice_id="classification-slice-1", classification_id="classification-1"),
                self._classification(
                    slice_id="classification-slice-2",
                    classification_id="classification-2",
                    impact_direction="supports_no",
                    value="market_resolves_no",
                ),
            ]
        )

        result = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )

        self.assertEqual(len(result.direction_verification_slices), 2)
        self.assertTrue(all(row["method_status"] == "verified" for row in result.direction_verification_slices))

    def test_stale_evidence_normalizes_recency_lower_than_claimed(self) -> None:
        row = self._classification(temporal_gate_status="fail")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["claimed_quality_fields"]["recency"], "fresh")
        self.assertEqual(quality["machine_normalized_quality_fields"]["recency"], "stale")
        self.assertEqual(quality["accepted_quality_fields"]["recency"], "stale")
        self.assertIn("recency_claim_downgraded", quality["reason_codes"])

    def test_unknown_source_authority_cannot_be_high_by_claim_alone(self) -> None:
        row = self._classification(source_class="unknown")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["claimed_quality_fields"]["source_authority"], "high")
        self.assertEqual(quality["machine_normalized_quality_fields"]["source_authority"], "unknown")
        self.assertEqual(quality["accepted_quality_fields"]["source_authority"], "unknown")
        self.assertIn("source_authority_claim_downgraded", quality["reason_codes"])

    def test_expert_source_authority_normalizes_to_medium(self) -> None:
        row = self._classification(source_class="expert_or_specialist")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["machine_normalized_quality_fields"]["source_authority"], "medium")
        self.assertEqual(quality["accepted_quality_fields"]["source_authority"], "medium")
        self.assertEqual(quality["quality_status"], "accepted")
        self.assertIn("source_authority_claim_downgraded", quality["reason_codes"])

    def test_directness_disagreement_produces_reason_code(self) -> None:
        row = self._classification(evidence_strength="weak")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["machine_normalized_quality_fields"]["directness"], "background")
        self.assertEqual(quality["accepted_quality_fields"]["directness"], "background")
        self.assertIn("directness_claim_downgraded", quality["reason_codes"])

    def test_raw_quality_multiplier_is_bounded(self) -> None:
        row = self._classification(
            source_class="unknown",
            evidence_strength="none",
            classification_confidence="low",
            classification_quality="low",
            ledger_ready=False,
            included_for_scae=False,
            classification_acceptance_status="non_scoreable",
            evidence_delta_eligible_for_scae=False,
            quality={
                "source_authority": "unknown",
                "directness": "unknown",
                "recency": "unknown",
                "specificity": "unknown",
            },
        )
        row["answer_value_extraction"] = {"normalization_status": "failed"}
        row["temporal_gate_status"] = "unknown_not_counted"

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertGreaterEqual(quality["raw_quality_multiplier"], 0.05)
        self.assertLessEqual(quality["raw_quality_multiplier"], 1.0)
        self.assertEqual(quality["final_quality_multiplier"], quality["raw_quality_multiplier"])

    def test_low_confidence_quality_is_excluded_from_scae_quality(self) -> None:
        row = self._classification(
            classification_confidence="low",
            classification_quality="high",
            classification_acceptance_status="non_scoreable",
        )

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["quality_status"], "excluded")
        self.assertIn("classification_confidence_low_no_scae_delta", quality["reason_codes"])

    def test_every_included_classification_receives_quality_verification(self) -> None:
        matrix = self._matrix(
            [
                self._classification(slice_id="classification-slice-1", classification_id="classification-1"),
                self._classification(
                    slice_id="classification-slice-2",
                    classification_id="classification-2",
                    impact_direction="supports_no",
                    value="market_resolves_no",
                    source_class="independent_secondary",
                    classification_confidence="medium",
                ),
            ]
        )

        result = build_quality_verification_slices(matrix)

        self.assertEqual(len(result.quality_verification_slices), len(matrix["classification_slices"]))
        self.assertTrue(
            all(
                "raw_quality_multiplier_inputs" in row
                and row["quality_correlation_groups"]
                and row["quality_status"] == "accepted"
                for row in result.quality_verification_slices
            )
        )

    def test_combined_bundle_marks_only_ver001_and_ver002_scope(self) -> None:
        matrix = self._matrix([self._classification()])

        bundle = build_researcher_verification_bundle(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )

        self.assertEqual(bundle["scope_boundaries"]["implements"], ["VER-001", "VER-002"])
        self.assertIn("SCAE", bundle["scope_boundaries"]["not_implemented"])
        self.assertFalse(bundle["scope_boundaries"]["writes_scae_ledger_rows"])
        self.assertEqual(len(bundle["direction_verification_slices"]), 1)
        self.assertEqual(len(bundle["quality_verification_slices"]), 1)

    def test_scae_readiness_accepts_verified_high_certainty_inputs(self) -> None:
        matrix = self._matrix([self._classification()])
        direction = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertTrue(result.ready_for_scae)
        payload = result.readiness_reconciliation
        self.assertEqual(payload["scope_boundaries"]["implements"], ["VER-003"])
        self.assertIn("VER-004", payload["scope_boundaries"]["not_implemented"])
        self.assertFalse(payload["authority_boundary"]["writes_scae_ledger_rows"])
        self.assertEqual(payload["ready_classification_slice_refs"], [matrix["classification_slices"][0]["slice_id"]])

    def test_scae_readiness_ignores_non_scoreable_no_delta_rows(self) -> None:
        ready = self._classification(slice_id="classification-ready", classification_id="classification-ready")
        irrelevant = self._classification(
            slice_id="classification-irrelevant",
            classification_id="classification-irrelevant",
            impact_direction="irrelevant",
            evidence_strength="none",
            ledger_ready=False,
            included_for_scae=False,
            classification_acceptance_status="non_scoreable",
            evidence_delta_eligible_for_scae=False,
        )
        matrix = self._matrix([ready, irrelevant])
        direction = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertTrue(result.ready_for_scae)
        rows = {
            row["classification_slice_ref"]: row
            for row in result.readiness_reconciliation["readiness_rows"]
        }
        self.assertEqual(rows[irrelevant["slice_id"]]["readiness_status"], "not_scae_bound")
        self.assertEqual(result.readiness_reconciliation["ready_classification_slice_refs"], [ready["slice_id"]])

    def test_scae_readiness_blocks_missing_direction_verification(self) -> None:
        matrix = self._matrix([self._classification()])
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            [],
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertFalse(result.ready_for_scae)
        self.assertIn("direction_verification_missing", result.readiness_reconciliation["blocker_codes"])

    def test_scae_readiness_allows_deadlock_safe_noncritical_exclusion(self) -> None:
        accepted = self._classification(
            slice_id="classification-slice-accepted",
            classification_id="classification-accepted",
            impact_direction="supports_yes",
            value="market_resolves_yes",
        )
        contradicted = self._classification(
            slice_id="classification-slice-contradicted",
            classification_id="classification-contradicted",
            impact_direction="supports_yes",
            value="market_resolves_no",
        )
        matrix = self._matrix([accepted, contradicted])
        direction = build_direction_verification_slices(
            matrix,
            qdt=self._qdt(),
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertTrue(result.ready_for_scae)
        rows_by_ref = {
            row["classification_slice_ref"]: row
            for row in result.readiness_reconciliation["readiness_rows"]
        }
        excluded = rows_by_ref[contradicted["slice_id"]]
        self.assertEqual(excluded["readiness_status"], "excluded_deadlock_safe")
        self.assertIn("deadlock_safe_exclusion_with_remaining_coverage", excluded["reason_codes"])

    def test_scae_readiness_blocks_missing_sufficiency_reconciliation(self) -> None:
        matrix = self._matrix([self._classification()])
        direction = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=None,
        )

        self.assertFalse(result.ready_for_scae)
        self.assertIn("research_sufficiency_reconciliation_missing", result.readiness_reconciliation["blocker_codes"])

    def test_scae_readiness_blocks_incomplete_required_escalation(self) -> None:
        matrix = self._matrix([self._classification()])
        direction = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
            escalation_decisions=[
                {
                    "leaf_id": "leaf-1",
                    "escalation_required": True,
                    "completion_status": "pending",
                    "additional_assignment_count": 1,
                    "delivered_assignment_count": 0,
                    "active_assignment_count": 0,
                }
            ],
        )

        self.assertFalse(result.ready_for_scae)
        self.assertIn("researcher_escalation_incomplete", result.readiness_reconciliation["blocker_codes"])

    def test_scae_readiness_blocks_unnormalized_supplemental_rows(self) -> None:
        row = self._classification()
        row["evidence_source_type"] = "supplemental"
        row["supplemental_evidence_ref"] = "supplemental:leaf-1"
        matrix = self._matrix([row])
        direction = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertFalse(result.ready_for_scae)
        self.assertIn("supplemental_normalization_missing", result.readiness_reconciliation["blocker_codes"])

    def test_scae_readiness_blocks_duplicate_ledger_grain(self) -> None:
        first = self._classification(
            slice_id="classification-slice-1",
            classification_id="classification-1",
            source_family_id="source-family-shared",
            claim_family_id="claim-family-shared",
        )
        second = self._classification(
            slice_id="classification-slice-2",
            classification_id="classification-2",
            source_family_id="source-family-shared",
            claim_family_id="claim-family-shared",
        )
        matrix = self._matrix([first, second])
        direction = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )
        quality = build_quality_verification_slices(matrix)

        result = build_scae_readiness_reconciliation(
            matrix,
            direction,
            quality,
            qdt=self._qdt(),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertFalse(result.ready_for_scae)
        self.assertIn("duplicate_ledger_readiness_grain", result.readiness_reconciliation["blocker_codes"])

    def test_scae_readiness_blocks_critical_structural_unanswerability(self) -> None:
        matrix = self._matrix([])
        matrix["coverage_proof_slices"] = [
            {
                "leaf_id": "leaf-1",
                "certificate_status": "structurally_unanswerable",
            }
        ]

        result = build_scae_readiness_reconciliation(
            matrix,
            [],
            [],
            qdt=self._qdt(static_weight="high"),
            coverage_proof_bundle=self._coverage_bundle(matrix),
            sufficiency_reconciliation=self._sufficiency_reconciliation(),
        )

        self.assertFalse(result.ready_for_scae)
        self.assertIn("critical_unanswerable_leaf_policy_consequence", result.readiness_reconciliation["blocker_codes"])


if __name__ == "__main__":
    unittest.main()
