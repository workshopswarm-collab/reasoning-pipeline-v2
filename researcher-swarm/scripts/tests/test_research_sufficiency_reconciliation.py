#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.verification import (  # noqa: E402
    VerificationError,
    build_research_sufficiency_reconciliation,
)


def _qdt(*, weight: str = "medium", protected_primary_required: bool = False) -> dict[str, Any]:
    return {
        "required_leaf_questions": [
            {
                "leaf_id": "leaf-1",
                "parent_branch_id": "branch-1",
                "leaf_condition_scope": "unconditional",
                "purpose": "source_of_truth" if protected_primary_required else "direct_evidence",
                "bayesian_weighting": {"static_information_weight": weight},
                "research_sufficiency_requirements": {
                    "requirement_id": "requirement-leaf-1",
                    "required_value_fields": ["event_status"],
                    "required_negative_checks": ["no_official_contradiction"],
                    "protected_primary_required": protected_primary_required,
                },
            }
        ]
    }


def _certificate(*, status: str = "certified_high_certainty") -> dict[str, Any]:
    structural = status == "structurally_unanswerable"
    return {
        "artifact_type": "research_sufficiency_certificate",
        "schema_version": "research-sufficiency-certificate/v1",
        "certificate_id": "research-sufficiency-leaf-1",
        "leaf_id": "leaf-1",
        "requirement_ref": "requirement-leaf-1",
        "status": status,
        "classification_dispatch_allowed": status
        in {"certified_high_certainty", "structurally_unanswerable", "watch_only_non_live_blocker"},
        "evidence_refs": [] if structural else ["evidence-1"],
        "breadth_coverage_ref": "breadth-coverage-leaf-1",
        "breadth_certified": status == "certified_high_certainty",
        "expansion_attempt_refs": ["expansion-1"] if structural else [],
        "fallback_state_ref": None,
        "structural_unanswerability_proof_ref": "artifact:structural-proof-1" if structural else None,
        "temporal_validation_status": "pass",
        "freshness_status": "not_applicable_structural_unanswerability" if structural else "freshness_window_satisfied",
        "macro_fallback_sufficiency_status": "not_applicable_structural_unanswerability" if structural else "not_requested",
        "unsatisfied_requirement_codes": [] if status == "certified_high_certainty" else ["source_class:official_or_primary"],
        "blocking_reason_codes": [] if status in {"certified_high_certainty", "structurally_unanswerable"} else ["breadth_not_certified"],
    }


def _retrieval_packet(*, certificate_status: str = "certified_high_certainty") -> dict[str, Any]:
    cert = _certificate(status=certificate_status)
    return {
        "artifact_type": "retrieval_packet",
        "schema_version": "retrieval-packet/v1",
        "case_id": "case-1",
        "dispatch_id": "dispatch-1",
        "retrieval_packet_digest": "sha256:" + "1" * 64,
        "leaf_research_sufficiency_certificates": [cert],
        "retrieval_breadth_coverage_slices": [
            {
                "artifact_type": "retrieval_breadth_coverage",
                "schema_version": "retrieval-breadth-coverage/v1",
                "coverage_id": "breadth-coverage-leaf-1",
                "leaf_id": "leaf-1",
                "breadth_certified": certificate_status == "certified_high_certainty",
                "unsatisfied_breadth_dimensions": []
                if certificate_status == "certified_high_certainty"
                else ["source_class:official_or_primary"],
                "expansion_requirement_codes": []
                if certificate_status == "certified_high_certainty"
                else ["source_class:official_or_primary"],
            }
        ],
    }


def _coverage_record(
    *,
    role: str = "primary",
    status: str = "certified_high_certainty",
    ref_suffix: str = "primary",
) -> dict[str, Any]:
    structural = status == "structurally_unanswerable"
    return {
        "proof_id": f"proof-{ref_suffix}",
        "coverage_proof_ref": f"coverage-proof-{ref_suffix}",
        "leaf_id": "leaf-1",
        "assignment_id": f"assignment-{ref_suffix}",
        "assignment_role": role,
        "research_sufficiency_certificate_ref": "research-sufficiency-leaf-1",
        "certificate_status": status,
        "retrieval_breadth_coverage_ref": "breadth-coverage-leaf-1",
        "reviewed_evidence_refs": [] if structural else ["evidence-1"],
        "certificate_evidence_refs": [] if structural else ["evidence-1"],
        "classified_evidence_refs": [] if structural else ["evidence-1"],
        "requirements_reviewed": ["requirement-leaf-1"],
        "requirements_answered": [] if structural else ["requirement-leaf-1"],
        "requirements_unanswered": ["requirement-leaf-1"] if structural else [],
        "required_value_fields": ["event_status"],
        "required_value_fields_extracted": [] if structural else ["event_status"],
        "required_negative_checks": ["no_official_contradiction"],
        "required_negative_checks_completed": [] if structural else ["no_official_contradiction"],
        "coverage_status": "complete",
        "reason_codes": [],
    }


def _coverage_bundle(
    *,
    certificate_status: str = "certified_high_certainty",
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "artifact_type": "researcher_evidence_review_coverage_proof_bundle",
        "schema_version": "researcher-evidence-review-coverage-proof-bundle/v1",
        "feature_id": "CLS-005",
        "bundle_digest": "sha256:" + "2" * 64,
        "coverage_proofs": records
        if records is not None
        else [_coverage_record(status=certificate_status)],
        "coverage_summary": {
            "all_assigned_evidence_reviewed": True,
            "all_certificate_evidence_reviewed": True,
            "all_required_outputs_addressed": True,
            "all_context_isolation_audits_launch_allowed": True,
        },
    }


def _matrix() -> dict[str, Any]:
    return {
        "artifact_type": "researcher_classification_matrix",
        "schema_version": "researcher-classification-matrix/v1",
        "matrix_id": "matrix-1",
        "matrix_digest": "sha256:" + "3" * 64,
        "case_id": "case-1",
        "dispatch_id": "dispatch-1",
        "classification_slices": [
            {
                "slice_id": "classification-slice-1",
                "classification_id": "classification-1",
                "leaf_id": "leaf-1",
                "condition_scope": "unconditional",
                "evidence_ref": "evidence-1",
                "claim_family_id": "claim-family-1",
                "source_family_id": "source-family-1",
                "coverage_proof_ref": "coverage-proof-primary",
                "research_sufficiency_certificate_ref": "research-sufficiency-leaf-1",
                "ledger_ready": True,
            }
        ],
    }


def _complete_structural_escalation() -> list[dict[str, Any]]:
    return [
        {
            "leaf_id": "leaf-1",
            "decision_id": "researcher-escalation-1",
            "decision_ref": "researcher-escalation-decision:researcher-escalation-1",
            "trigger_codes": ["structural_unanswerability_claimed"],
            "escalation_required": True,
            "additional_assignment_count": 1,
            "completion_status": "required_complete",
            "escalation_assignment_refs": ["artifact:leaf-research-assignment/assignment-confirmation"],
            "escalation_assignment_descriptors": [
                {
                    "assignment_ref": "artifact:leaf-research-assignment/assignment-confirmation",
                    "delivery_status": "completed",
                }
            ],
        }
    ]


class ResearchSufficiencyReconciliationTest(unittest.TestCase):
    def _build(
        self,
        *,
        certificate_status: str = "certified_high_certainty",
        qdt: dict[str, Any] | None = None,
        coverage_bundle: dict[str, Any] | None = None,
        classification_matrix: dict[str, Any] | None = None,
        escalation_decisions: list[dict[str, Any]] | None = None,
    ):
        return build_research_sufficiency_reconciliation(
            qdt=qdt or _qdt(),
            retrieval_packet=_retrieval_packet(certificate_status=certificate_status),
            coverage_proof_bundle=coverage_bundle
            or _coverage_bundle(certificate_status=certificate_status),
            classification_matrix=classification_matrix if classification_matrix is not None else _matrix(),
            escalation_decisions=escalation_decisions,
        )

    def test_high_certainty_certificate_and_complete_proof_yields_scae_ready(self) -> None:
        result = self._build()
        row = result.research_sufficiency_reconciliation_slices[0]

        self.assertEqual(row["reconciled_status"], "scae_ready_high_certainty")
        self.assertTrue(row["scae_ready"])
        self.assertEqual(result.scae_ready_leaf_ids, ["leaf-1"])
        self.assertEqual(result.reconciliation_bundle["bundle_status"], "scae_consumable")

    def test_thin_retrieval_cannot_become_clean_scae_ready_input(self) -> None:
        result = self._build(certificate_status="blocked_insufficient_research")
        row = result.research_sufficiency_reconciliation_slices[0]

        self.assertEqual(row["reconciled_status"], "blocked_insufficient_research")
        self.assertFalse(row["scae_ready"])
        self.assertIn("certificate_not_high_certainty", row["blocking_reason_codes"])

    def test_structural_unanswerability_requires_completed_confirmation(self) -> None:
        result = self._build(
            certificate_status="structurally_unanswerable",
            classification_matrix={"matrix_id": "matrix-1", "matrix_digest": "sha256:" + "3" * 64, "classification_slices": []},
        )
        row = result.research_sufficiency_reconciliation_slices[0]

        self.assertEqual(row["reconciled_status"], "blocked_insufficient_research")
        self.assertIn("structural_unanswerability_confirmation_missing", row["blocking_reason_codes"])

    def test_structural_unanswerability_with_completed_confirmation_is_consumable(self) -> None:
        records = [
            _coverage_record(status="structurally_unanswerable", ref_suffix="primary"),
            _coverage_record(
                role="confirmation",
                status="structurally_unanswerable",
                ref_suffix="confirmation",
            ),
        ]
        result = self._build(
            certificate_status="structurally_unanswerable",
            coverage_bundle=_coverage_bundle(certificate_status="structurally_unanswerable", records=records),
            classification_matrix={"matrix_id": "matrix-1", "matrix_digest": "sha256:" + "3" * 64, "classification_slices": []},
            escalation_decisions=_complete_structural_escalation(),
        )
        row = result.research_sufficiency_reconciliation_slices[0]

        self.assertEqual(row["reconciled_status"], "structurally_unanswerable")
        self.assertTrue(row["scae_ready"])
        self.assertEqual(result.structurally_unanswerable_leaf_ids, ["leaf-1"])

    def test_incomplete_required_escalation_blocks_high_certainty_leaf(self) -> None:
        result = self._build(
            escalation_decisions=[
                {
                    "leaf_id": "leaf-1",
                    "trigger_codes": ["low_classification_confidence"],
                    "escalation_required": True,
                    "additional_assignment_count": 1,
                    "completion_status": "required_pending",
                    "escalation_assignment_refs": ["artifact:leaf-research-assignment/escalation-1"],
                    "escalation_assignment_descriptors": [
                        {
                            "assignment_ref": "artifact:leaf-research-assignment/escalation-1",
                            "delivery_status": "planned_not_spawned",
                        }
                    ],
                }
            ]
        )
        row = result.research_sufficiency_reconciliation_slices[0]

        self.assertEqual(row["reconciled_status"], "blocked_insufficient_research")
        self.assertIn("researcher_escalation_incomplete", row["blocking_reason_codes"])

    def test_watch_only_non_live_blocker_is_not_marked_scae_ready(self) -> None:
        result = self._build(certificate_status="watch_only_non_live_blocker")
        row = result.research_sufficiency_reconciliation_slices[0]

        self.assertEqual(row["reconciled_status"], "watch_only_non_live_blocker")
        self.assertFalse(row["scae_ready"])
        self.assertEqual(result.watch_only_leaf_ids, ["leaf-1"])

    def test_forbidden_probability_authority_fields_are_rejected(self) -> None:
        matrix = _matrix()
        matrix["classification_slices"][0]["own_probability"] = 0.7

        with self.assertRaisesRegex(VerificationError, "forbidden researcher authority fields"):
            self._build(classification_matrix=matrix)


if __name__ == "__main__":
    unittest.main()
