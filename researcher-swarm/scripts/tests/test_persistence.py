#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.assignments import (  # noqa: E402
    CLS_006_ASSIGNMENT_BUILDER_VERSION,
    DEFAULT_CONTEXT_ISOLATION_POLICY_ID,
    DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS,
    LEAF_RESEARCH_ASSIGNMENT_ARTIFACT_TYPE,
    LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION,
    compute_leaf_research_assignment_digest,
)
from researcher_swarm.classification import (  # noqa: E402
    FORBIDDEN_OUTPUT_FIELDS,
    RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
    RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
    RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
    RESEARCHER_SIDECAR_SCHEMA_VERSION,
)
from researcher_swarm.escalation import (  # noqa: E402
    CLS_007_ESCALATION_BUILDER_VERSION,
    MAX_ASSIGNMENTS_PER_LEAF,
    MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE,
    RESEARCHER_ESCALATION_DECISION_ARTIFACT_TYPE,
    RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION,
    compute_researcher_escalation_decision_digest,
)
from researcher_swarm.isolation import build_researcher_context_isolation_audit  # noqa: E402
from researcher_swarm.persistence import (  # noqa: E402
    ResearcherPersistenceError,
    ensure_researcher_verification_persistence_schema,
    write_classification_provenance_slices,
    write_direction_verification_slices,
    write_evidence_quality_verification_slices,
    write_leaf_research_assignments,
    write_normalized_supplemental_evidence,
    write_research_sufficiency_reconciliation,
    write_researcher_classifications,
    write_researcher_context_isolation_audits,
    write_researcher_coverage_proofs,
    write_researcher_escalation_decisions,
    write_researcher_prompt_artifact,
    write_scae_readiness_reconciliation,
    write_verification_slices,
)
from researcher_swarm.supplemental import normalize_supplemental_evidence  # noqa: E402


SHA = "sha256:" + "1" * 64


class ResearcherPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_researcher_verification_persistence_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _assignment(self) -> dict:
        assignment = {
            "artifact_type": LEAF_RESEARCH_ASSIGNMENT_ARTIFACT_TYPE,
            "schema_version": LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION,
            "feature_id": "CLS-006",
            "builder_version": CLS_006_ASSIGNMENT_BUILDER_VERSION,
            "assignment_id": "leaf-assignment-fixture",
            "attempt_index": 0,
            "assignment_role": "primary",
            "escalation_decision_ref": None,
            "trigger_codes": [],
            "assigned_lens": "baseline",
            "context_isolation": {
                "isolation_policy_id": DEFAULT_CONTEXT_ISOLATION_POLICY_ID,
                "isolation_audit_ref": "researcher-context-isolation:leaf-assignment-fixture",
                "peer_context_allowed": False,
                "visible_artifact_ref_allowlist": [
                    "artifact:leaf-research-assignment/leaf-assignment-fixture",
                    "artifact:question-decomposition/qdt-1",
                    "artifact:retrieval-snippet/snippet-1",
                    "evidence-1",
                    "prompt-template:researcher-leaf-nli/v1",
                    "schema:researcher-sidecar/v2",
                ],
                "forbidden_artifact_ref_patterns": list(DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS),
            },
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "leaf_ref": {
                "artifact_ref": "artifact:question-decomposition/qdt-1",
                "leaf_json_pointer": "/required_leaf_questions/0",
                "leaf_digest": SHA,
            },
            "condition_scope": "unconditional",
            "sufficiency_requirement_refs": ["requirement-1"],
            "research_sufficiency_certificate_ref": "research-sufficiency-1",
            "retrieval_breadth_profile_ref": "breadth-profile-1",
            "retrieval_breadth_coverage_ref": "breadth-coverage-1",
            "assigned_evidence_refs": [
                {
                    "evidence_ref": "evidence-1",
                    "claim_family_id": "claim-family-1",
                    "source_family_id": "source-family-1",
                    "source_class": "official_or_primary",
                    "snippet_ref": "artifact:retrieval-snippet/snippet-1",
                    "snippet_sha256": SHA,
                }
            ],
            "required_value_field_ids": ["value-field-1"],
            "required_negative_check_ids": ["negative-check-1"],
            "output_contract": {
                "sidecar_schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
                "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
                "coverage_proof_schema_version": RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
                "coverage_proof_required": True,
                "forbidden_fields": list(FORBIDDEN_OUTPUT_FIELDS),
            },
            "model_execution_context": {
                "model_lane_id": "researcher_leaf_nli_classification",
                "resolved_model_id": "gpt-5.5-high",
                "model_policy_ref": "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json",
                "model_policy_sha256": SHA,
                "prompt_template_id": RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
                "model_context_digest": "sha256:" + "2" * 64,
            },
            "budget": {
                "max_input_tokens": 12000,
                "max_output_tokens": 2500,
                "deadline_seconds": 900,
                "retry_budget": 1,
            },
            "artifact_outputs": {
                "assignment_artifact_ref": "artifact:leaf-research-assignment/leaf-assignment-fixture",
                "sidecar_artifact_ref": "artifact:researcher-sidecar/sidecar-1",
                "coverage_proof_ref": "coverage-proof-1",
            },
        }
        assignment["assignment_digest"] = compute_leaf_research_assignment_digest(assignment)
        return assignment

    def _classification_rows(self) -> tuple[dict, dict]:
        classification = {
            "artifact_type": "classification_lane_evidence_classification_slice",
            "schema_version": "classification-lane-evidence-classification-slice/v1",
            "slice_id": "classification-slice-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "sidecar_id": "sidecar-1",
            "sidecar_digest": SHA,
            "researcher_run_id": "researcher-run-1",
            "persona_id": "researcher-1",
            "classification_id": "classification-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "question_id": "leaf-1",
            "condition_scope": "unconditional",
            "evidence_ref": "evidence-1",
            "source_ref": "source-1",
            "canonical_source_id": "source-1",
            "source_class": "official_or_primary",
            "source_family_id": "source-family-1",
            "claim_family_id": "claim-family-1",
            "claim_family_resolution_ref": "claim-resolution-1",
            "impact_direction": "supports_yes",
            "evidence_strength": "strong",
            "classification_confidence": "high",
            "answer_value_extraction": {"field_name": "status", "value": "confirmed", "normalization_status": "parsed"},
            "evidence_quality_dimensions": {
                "source_authority": "high",
                "directness": "direct",
                "recency": "fresh",
                "specificity": "specific",
            },
            "research_sufficiency_certificate_ref": "research-sufficiency-1",
            "coverage_proof_ref": "coverage-proof-1",
            "retrieval_breadth_coverage_ref": "breadth-coverage-1",
            "provenance_slice_ref": "classification-provenance-slice-1",
            "model_execution_context_ref": "model-context-1",
            "model_execution_context_sha256": SHA,
            "classification_slice_digest": SHA,
            "matrix_digest": "sha256:" + "3" * 64,
            "materializer_version": "ads-cls-003-classification-matrix-materializer/v1",
        }
        provenance = {
            "artifact_type": "classification_lane_evidence_provenance_slice",
            "schema_version": "classification-lane-evidence-provenance-slice/v1",
            "slice_id": "classification-provenance-slice-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "sidecar_id": "sidecar-1",
            "classification_slice_ref": "classification-slice-1",
            "classification_id": "classification-1",
            "leaf_id": "leaf-1",
            "condition_scope": "unconditional",
            "evidence_ref": "evidence-1",
            "retrieval_evidence_provenance_ref": "retrieval-provenance-1",
            "source_ref": "source-1",
            "source_class": "official_or_primary",
            "source_family_id": "source-family-1",
            "claim_family_id": "claim-family-1",
            "claim_family_resolution_ref": "claim-resolution-1",
            "research_sufficiency_certificate_ref": "research-sufficiency-1",
            "coverage_proof_ref": "coverage-proof-1",
            "retrieval_breadth_coverage_ref": "breadth-coverage-1",
            "provenance_refs": ["retrieval-provenance-1", "claim-resolution-1"],
            "content_sha256": SHA,
            "provenance_slice_digest": SHA,
            "matrix_digest": "sha256:" + "3" * 64,
            "materializer_version": "ads-cls-003-classification-matrix-materializer/v1",
        }
        return classification, provenance

    def _coverage_proof(self) -> dict:
        return {
            "schema_version": "researcher-evidence-review-coverage-proof/v1",
            "proof_id": "researcher-coverage-proof-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "assignment_id": "leaf-assignment-fixture",
            "assignment_digest": SHA,
            "isolation_audit_ref": "researcher-context-isolation:leaf-assignment-fixture",
            "isolation_audit_digest": SHA,
            "sidecar_id": "sidecar-1",
            "sidecar_digest": SHA,
            "coverage_proof_ref": "coverage-proof-1",
            "coverage_proof_slice_ref": "coverage-slice-1",
            "classification_matrix_id": "matrix-1",
            "classification_matrix_digest": "sha256:" + "3" * 64,
            "research_sufficiency_certificate_ref": "research-sufficiency-1",
            "certificate_status": "certified_high_certainty",
            "retrieval_breadth_coverage_ref": "breadth-coverage-1",
            "coverage_status": "complete",
            "assigned_evidence_refs": ["evidence-1"],
            "reviewed_evidence_refs": ["evidence-1"],
            "certificate_evidence_refs": ["evidence-1"],
            "classified_evidence_refs": ["evidence-1"],
            "requirements_reviewed": ["requirement-1"],
            "requirements_answered": ["requirement-1"],
            "requirements_unanswered": [],
            "required_value_fields": ["value-field-1"],
            "required_value_fields_extracted": ["value-field-1"],
            "required_negative_checks": ["negative-check-1"],
            "required_negative_checks_completed": ["negative-check-1"],
            "proof_digest": SHA,
        }

    def _escalation_decision(self) -> dict:
        decision = {
            "artifact_type": RESEARCHER_ESCALATION_DECISION_ARTIFACT_TYPE,
            "schema_version": RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION,
            "feature_id": "CLS-007",
            "builder_version": CLS_007_ESCALATION_BUILDER_VERSION,
            "decision_id": "researcher-escalation-fixture",
            "decision_ref": "researcher-escalation-decision:researcher-escalation-fixture",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "base_assignment_id": "leaf-assignment-fixture",
            "trigger_codes": [],
            "trigger_evidence_refs": [],
            "retrieval_quality_ref": "retrieval-quality-1",
            "classification_ids": ["classification-1"],
            "verification_slice_refs": ["direction-verification-1", "quality-verification-1"],
            "pre_scae_leverage_proxy": {
                "bucket": "low",
                "input_refs": ["leaf-1"],
                "reason_codes": ["no_escalation_triggers"],
                "probability_fields_forbidden": True,
            },
            "escalation_required": False,
            "additional_assignment_count": 0,
            "max_assignments_for_leaf": MAX_ASSIGNMENTS_PER_LEAF,
            "max_concurrent_leaf_researchers_per_case": MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE,
            "current_assignments_for_leaf": 1,
            "current_active_leaf_researchers_for_case": 1,
            "escalation_assignment_refs": [],
            "escalation_assignment_descriptors": [],
            "completion_status": "not_required",
        }
        decision["decision_digest"] = compute_researcher_escalation_decision_digest(decision)
        return decision

    def _verification_rows(self) -> tuple[dict, dict]:
        direction = {
            "artifact_type": "evidence_direction_verification_slice",
            "schema_version": "evidence-direction-verification-slice/v1",
            "verification_slice_id": "direction-verification-1",
            "classification_slice_ref": "classification-slice-1",
            "classification_id": "classification-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "claimed_direction": "supports_yes",
            "verified_direction": "supports_yes",
            "side_mapping_digest": SHA,
            "market_constraints_digest": SHA,
            "method_status": "verified",
            "verification_status": "accepted",
            "accepted_for_scae": True,
            "reason_codes": ["direction_verified"],
            "direction_verification_slice_digest": SHA,
            "direction_verification_digest": "sha256:" + "4" * 64,
        }
        quality = {
            "artifact_type": "evidence_quality_verification_slice",
            "schema_version": "evidence-quality-verification-slice/v1",
            "quality_verification_slice_id": "quality-verification-1",
            "classification_slice_ref": "classification-slice-1",
            "classification_id": "classification-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "claimed_quality_fields": {"source_authority": "high"},
            "machine_normalized_quality_fields": {"source_authority": "high"},
            "accepted_quality_fields": {
                "source_authority": "high",
                "directness": "direct",
                "recency": "fresh",
                "specificity": "specific",
                "classification_confidence": "high",
            },
            "raw_quality_multiplier": 1.0,
            "quality_correlation_groups": ["source-family:source-family-1"],
            "correlated_quality_floor_applied": False,
            "final_quality_multiplier": 1.0,
            "quality_status": "accepted",
            "accepted_for_scae": True,
            "reason_codes": ["quality_verified"],
            "quality_verification_slice_digest": SHA,
            "quality_verification_digest": "sha256:" + "5" * 64,
        }
        return direction, quality

    def _supplemental(self) -> dict:
        return normalize_supplemental_evidence(
            {
                "supplemental_evidence_ref": "supplemental:example",
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "leaf_id": "leaf-1",
                "url": "https://independent.example/report",
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
            },
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )

    def _readiness(self) -> dict:
        row = {
            "readiness_row_id": "scae-readiness-row-1",
            "classification_slice_ref": "classification-slice-1",
            "classification_id": "classification-1",
            "leaf_id": "leaf-1",
            "readiness_status": "ready_for_scae",
            "readiness_row_digest": "sha256:" + "6" * 64,
        }
        return {
            "artifact_type": "scae_readiness_reconciliation",
            "schema_version": "scae-readiness-reconciliation/v1",
            "reconciliation_id": "scae-readiness-reconciliation-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "source_classification_matrix_id": "matrix-1",
            "source_classification_matrix_digest": "sha256:" + "3" * 64,
            "source_direction_verification_digest": "sha256:" + "4" * 64,
            "source_quality_verification_digest": "sha256:" + "5" * 64,
            "source_coverage_proof_bundle_digest": SHA,
            "readiness_rows": [row],
            "leaf_readiness": [
                {
                    "leaf_id": "leaf-1",
                    "scae_readiness_status": "ready_for_scae",
                    "research_sufficiency_reconciliation_ref": "research-sufficiency-reconciliation:research-sufficiency-reconcile-1",
                }
            ],
            "ready_for_scae": True,
            "ready_classification_slice_refs": ["classification-slice-1"],
            "excluded_deadlock_safe_classification_slice_refs": [],
            "blockers": [],
            "blocker_codes": [],
            "readiness_digest": "sha256:" + "7" * 64,
        }

    def _research_sufficiency(self) -> dict:
        return {
            "artifact_type": "research_sufficiency_reconciliation_bundle",
            "schema_version": "research-sufficiency-reconciliation-bundle/v1",
            "reconciliation_digest": "sha256:" + "8" * 64,
            "research_sufficiency_reconciliation_slices": [
                {
                    "artifact_type": "research_sufficiency_reconciliation_slice",
                    "schema_version": "research-sufficiency-reconciliation/v1",
                    "research_sufficiency_reconciliation_id": "research-sufficiency-reconcile-1",
                    "case_id": "case-1",
                    "dispatch_id": "dispatch-1",
                    "leaf_id": "leaf-1",
                    "parent_branch_id": "branch-1",
                    "condition_scope": "unconditional",
                    "certificate_ref": "research-sufficiency-1",
                    "certificate_status": "certified_high_certainty",
                    "retrieval_breadth_coverage_ref": "breadth-coverage-1",
                    "coverage_proof_refs": ["coverage-proof-1"],
                    "classification_slice_refs": ["classification-slice-1"],
                    "required_escalation_decision_refs": [],
                    "completed_escalation_decision_refs": [],
                    "required_value_fields": ["value-field-1"],
                    "required_negative_checks": ["negative-check-1"],
                    "reconciled_status": "scae_ready_high_certainty",
                    "research_sufficiency_reconciliation_status": "scae_ready_high_certainty",
                    "missing_requirement_codes": [],
                    "blocking_reason_codes": [],
                    "reason_codes": ["research_sufficiency_reconciliation_checks_applied"],
                    "scae_ready": True,
                    "scae_consumable_under_policy": True,
                    "reconciliation_slice_digest": "sha256:" + "9" * 64,
                }
            ],
        }

    def test_writes_all_mig006_surfaces_compactly_and_idempotently(self) -> None:
        assignment = self._assignment()
        audit = build_researcher_context_isolation_audit(assignment)
        classification, provenance = self._classification_rows()
        direction, quality = self._verification_rows()

        prompt_id = write_researcher_prompt_artifact(
            self.conn,
            {
                "schema_version": RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION,
                "prompt_contract_id": "prompt-contract-1",
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "prompt_template_id": RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
                "prompt_text": "full prompt text is not persisted",
                "prompt_text_sha256": SHA,
                "prompt_contract_digest": SHA,
                "output_contract_refs": {"sidecar_contract_ref": "schema:researcher-sidecar/v2"},
            },
            artifact_ref="artifact:researcher-prompt/prompt-contract-1",
        )
        self.assertEqual(prompt_id, "prompt-contract-1")

        self.assertEqual(write_leaf_research_assignments(self.conn, [assignment]), ["leaf-assignment-fixture"])
        self.assertEqual(
            write_researcher_context_isolation_audits(
                self.conn,
                [audit],
                assignments_by_id={assignment["assignment_id"]: assignment},
            ),
            [audit["isolation_audit_id"]],
        )
        self.assertEqual(
            write_researcher_classifications(
                self.conn,
                {"classification_slices": [classification], "provenance_slices": [provenance]},
            ),
            {
                "classification_slice_ids": ["classification-slice-1"],
                "provenance_slice_ids": ["classification-provenance-slice-1"],
            },
        )
        self.assertEqual(write_researcher_coverage_proofs(self.conn, [self._coverage_proof()]), ["researcher-coverage-proof-1"])
        self.assertEqual(write_researcher_escalation_decisions(self.conn, [self._escalation_decision()]), ["researcher-escalation-fixture"])
        supplemental_id = write_normalized_supplemental_evidence(self.conn, [self._supplemental()])[0]
        self.assertTrue(supplemental_id.startswith("normalized-supplemental-"))
        self.assertEqual(write_direction_verification_slices(self.conn, [direction]), ["direction-verification-1"])
        self.assertEqual(write_evidence_quality_verification_slices(self.conn, [quality]), ["quality-verification-1"])
        self.assertEqual(
            write_verification_slices(
                self.conn,
                direction_verification_slices=[direction],
                quality_verification_slices=[quality],
                normalized_supplemental_evidence=[self._supplemental()],
            )["direction_verification_slice_ids"],
            ["direction-verification-1"],
        )
        self.assertEqual(write_scae_readiness_reconciliation(self.conn, self._readiness()), "scae-readiness-reconciliation-1")
        self.assertEqual(write_research_sufficiency_reconciliation(self.conn, self._research_sufficiency()), ["research-sufficiency-reconcile-1"])

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM leaf_research_assignments").fetchone()["n"],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT prompt_artifact_ref FROM researcher_prompt_artifacts").fetchone()["prompt_artifact_ref"],
            "artifact:researcher-prompt/prompt-contract-1",
        )
        assignment_row = self.conn.execute("SELECT assigned_evidence_refs FROM leaf_research_assignments").fetchone()
        stored_evidence = json.loads(assignment_row["assigned_evidence_refs"])
        self.assertEqual(stored_evidence[0]["evidence_ref"], "evidence-1")
        self.assertNotIn("evidence_body", stored_evidence[0])

    def test_rejects_full_payloads_and_forbidden_authority_fields(self) -> None:
        bad_assignment = self._assignment()
        bad_assignment["assigned_evidence_refs"][0]["evidence_body"] = "full evidence body"
        bad_assignment["assignment_digest"] = compute_leaf_research_assignment_digest(bad_assignment)
        with self.assertRaises(ResearcherPersistenceError):
            write_leaf_research_assignments(self.conn, [bad_assignment])

        classification, _ = self._classification_rows()
        bad_classification = copy.deepcopy(classification)
        bad_classification["scae_delta"] = 0.2
        with self.assertRaises(ResearcherPersistenceError):
            write_researcher_classifications(
                self.conn,
                {"classification_slices": [bad_classification], "provenance_slices": []},
            )

    def test_scae_readiness_persists_refs_not_full_row_bodies(self) -> None:
        write_scae_readiness_reconciliation(self.conn, self._readiness())

        row = self.conn.execute(
            """
            SELECT readiness_row_count, readiness_row_digests, leaf_readiness_refs
            FROM scae_readiness_reconciliation_refs
            WHERE reconciliation_id = ?
            """,
            ("scae-readiness-reconciliation-1",),
        ).fetchone()
        self.assertEqual(row["readiness_row_count"], 1)
        self.assertEqual(json.loads(row["readiness_row_digests"]), ["sha256:" + "6" * 64])
        leaf_refs = json.loads(row["leaf_readiness_refs"])
        self.assertEqual(leaf_refs[0]["leaf_id"], "leaf-1")
        self.assertNotIn("readiness_rows", row.keys())


if __name__ == "__main__":
    unittest.main()
