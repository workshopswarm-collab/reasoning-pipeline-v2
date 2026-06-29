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
    validate_leaf_research_assignment,
)
from researcher_swarm.escalation import (  # noqa: E402
    MAX_ASSIGNMENTS_PER_LEAF,
    MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE,
    compute_researcher_escalation_decision_digest,
    evaluate_researcher_escalation,
    validate_researcher_escalation_decision,
)
from researcher_swarm.retrieval import (  # noqa: E402
    build_evidence_chunk,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)


def _leaf(
    *,
    leaf_id: str = "leaf-1",
    purpose: str = "direct_evidence",
    weight: str = "medium",
    protected_primary_required: bool = False,
    condition_scope: str = "unconditional",
) -> dict[str, Any]:
    return {
        "leaf_id": leaf_id,
        "parent_branch_id": "branch-1",
        "purpose": purpose,
        "leaf_condition_scope": condition_scope,
        "bayesian_weighting": {"static_information_weight": weight},
        "research_sufficiency_requirements": {
            "requirement_id": f"requirement-{leaf_id}",
            "static_information_weight": weight,
            "protected_primary_required": protected_primary_required,
        },
    }


def _certificate(*, leaf_id: str = "leaf-1", status: str = "certified_high_certainty") -> dict[str, Any]:
    certificate = {
        "certificate_id": f"research-sufficiency-{leaf_id}",
        "leaf_id": leaf_id,
        "status": status,
        "classification_dispatch_allowed": True,
        "evidence_refs": [f"evidence-{leaf_id}-1"],
        "breadth_coverage_ref": f"breadth-coverage-{leaf_id}",
        "breadth_certified": status == "certified_high_certainty",
        "unsatisfied_requirement_codes": [],
        "blocking_reason_codes": [],
    }
    if status == "structurally_unanswerable":
        certificate["structural_unanswerability_proof_ref"] = f"structural-proof-{leaf_id}"
        certificate["evidence_refs"] = []
    return certificate


def _base_assignment(*, leaf_id: str = "leaf-1") -> dict[str, Any]:
    return {
        "assignment_id": f"leaf-assignment-base-{leaf_id}",
        "case_id": "case-1",
        "dispatch_id": "dispatch-1",
        "leaf_id": leaf_id,
        "condition_scope": "unconditional",
    }


def _classification(
    *,
    classification_id: str = "classification-1",
    leaf_id: str = "leaf-1",
    direction: str = "supports_yes",
    confidence: str = "high",
    strength: str = "strong",
) -> dict[str, Any]:
    return {
        "slice_id": f"slice-{classification_id}",
        "classification_id": classification_id,
        "case_id": "case-1",
        "dispatch_id": "dispatch-1",
        "leaf_id": leaf_id,
        "evidence_ref": f"evidence-{classification_id}",
        "impact_direction": direction,
        "classification_confidence": confidence,
        "evidence_strength": strength,
    }


def _direction(
    *,
    classification_id: str = "classification-1",
    leaf_id: str = "leaf-1",
    direction: str = "supports_yes",
) -> dict[str, Any]:
    return {
        "verification_slice_id": f"direction-{classification_id}",
        "classification_id": classification_id,
        "leaf_id": leaf_id,
        "claimed_direction": direction,
        "verified_direction": direction,
        "verification_status": "accepted",
        "method_status": "verified",
    }


def _quality(
    *,
    classification_id: str = "classification-1",
    leaf_id: str = "leaf-1",
    confidence: str = "high",
    multiplier: float = 0.95,
) -> dict[str, Any]:
    return {
        "quality_verification_slice_id": f"quality-{classification_id}",
        "classification_id": classification_id,
        "leaf_id": leaf_id,
        "accepted_quality_fields": {"classification_confidence": confidence},
        "final_quality_multiplier": multiplier,
        "quality_status": "accepted",
    }


def _retrieval_quality(*, leaf_id: str = "leaf-1", status: str = "high", score: float = 0.95) -> dict[str, Any]:
    return {
        "slice_id": f"retrieval-quality-{leaf_id}",
        "leaf_id": leaf_id,
        "quality_status": status,
        "quality_score": score,
        "selected_evidence_refs": [f"evidence-{leaf_id}-1"],
    }


class ResearcherEscalationContractTest(unittest.TestCase):
    def _evaluate(
        self,
        *,
        leaf: dict[str, Any] | None = None,
        certificate: dict[str, Any] | None = None,
        classifications: list[dict[str, Any]] | None = None,
        direction_slices: list[dict[str, Any]] | None = None,
        quality_slices: list[dict[str, Any]] | None = None,
        retrieval_quality: dict[str, Any] | None = None,
        base_assignment: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        leaf = leaf or _leaf()
        certificate = certificate or _certificate(leaf_id=leaf["leaf_id"])
        classifications = classifications or [_classification(leaf_id=leaf["leaf_id"])]
        direction_slices = direction_slices or [_direction(leaf_id=leaf["leaf_id"])]
        quality_slices = quality_slices or [_quality(leaf_id=leaf["leaf_id"])]
        retrieval_quality = retrieval_quality or _retrieval_quality(leaf_id=leaf["leaf_id"])
        base_assignment = base_assignment or _base_assignment(leaf_id=leaf["leaf_id"])
        result = evaluate_researcher_escalation(
            leaf=leaf,
            certificate=certificate,
            classifications=classifications,
            direction_slices=direction_slices,
            quality_slices=quality_slices,
            retrieval_quality=retrieval_quality,
            base_assignment=base_assignment,
            **kwargs,
        )
        validation = validate_researcher_escalation_decision(result.decision)
        self.assertTrue(validation.valid, validation.errors)
        return result.to_dict()

    def _handoff(self) -> dict[str, Any]:
        return {
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

    def _qdt_packet_and_assignments(self) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        qdt = select_qdt_candidate([build_fixture_qdt_candidate(self._handoff())])
        contexts = build_retrieval_query_contexts(
            qdt,
            evidence_packet={
                "artifact_type": "evidence_packet",
                "schema_version": "evidence-packet/v2",
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
                "market_rules": {"resolution_url": "https://example.com/rules"},
                "official_source_hints": ["https://example.com/official"],
            },
        )
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
        for item in selected:
            text = f"Escalation certified excerpt for {item['transport_attempt_ref']}"
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
            qdt,
            evidence_packet={
                "artifact_type": "evidence_packet",
                "schema_version": "evidence-packet/v2",
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
                "market_rules": {"resolution_url": "https://example.com/rules"},
                "official_source_hints": ["https://example.com/official"],
            },
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        packet["evidence_chunks"] = chunks
        packet = finalize_retrieval_packet_for_dispatch(packet)
        self.assertEqual(packet["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        assignments = build_leaf_research_assignments(qdt=qdt, retrieval_packet=packet)
        return qdt, packet, assignments

    def test_normal_leaf_does_not_create_extra_assignments(self) -> None:
        result = self._evaluate()

        decision = result["decision"]
        self.assertFalse(decision["escalation_required"])
        self.assertEqual(decision["additional_assignment_count"], 0)
        self.assertEqual(decision["completion_status"], "not_required")
        self.assertEqual(decision["escalation_assignment_refs"], [])

    def test_critical_source_of_truth_leaf_creates_confirmation_assignment_packet(self) -> None:
        qdt, packet, assignments = self._qdt_packet_and_assignments()
        source_leaf = next(leaf for leaf in qdt["required_leaf_questions"] if leaf["purpose"] == "source_of_truth")
        base_assignment = next(item for item in assignments if item["leaf_id"] == source_leaf["leaf_id"])
        certificate = next(
            item for item in packet["leaf_research_sufficiency_certificates"] if item["leaf_id"] == source_leaf["leaf_id"]
        )

        result = self._evaluate(
            leaf=source_leaf,
            certificate=certificate,
            classifications=[_classification(leaf_id=source_leaf["leaf_id"])],
            direction_slices=[_direction(leaf_id=source_leaf["leaf_id"])],
            quality_slices=[_quality(leaf_id=source_leaf["leaf_id"])],
            retrieval_quality=_retrieval_quality(leaf_id=source_leaf["leaf_id"]),
            base_assignment=base_assignment,
            qdt=qdt,
            retrieval_packet=packet,
        )

        decision = result["decision"]
        self.assertIn("critical_source_of_truth_leaf", decision["trigger_codes"])
        self.assertEqual(decision["additional_assignment_count"], 1)
        self.assertEqual(len(result["escalation_assignments"]), 1)
        assignment = result["escalation_assignments"][0]
        self.assertTrue(validate_leaf_research_assignment(assignment).valid)
        self.assertEqual(assignment["assignment_role"], "confirmation")
        self.assertEqual(assignment["assigned_lens"], "source_of_truth_check")
        self.assertEqual(assignment["escalation_decision_ref"], decision["decision_ref"])
        self.assertEqual(decision["escalation_assignment_refs"], [assignment["artifact_outputs"]["assignment_artifact_ref"]])

    def test_conflicting_evidence_creates_conflict_resolution_assignment(self) -> None:
        result = self._evaluate(
            classifications=[
                _classification(classification_id="classification-yes", direction="supports_yes"),
                _classification(classification_id="classification-no", direction="supports_no"),
            ],
            direction_slices=[
                _direction(classification_id="classification-yes", direction="supports_yes"),
                _direction(classification_id="classification-no", direction="supports_no"),
            ],
        )

        decision = result["decision"]
        self.assertIn("evidence_conflict", decision["trigger_codes"])
        self.assertEqual(decision["escalation_assignment_descriptors"][0]["assignment_role"], "escalation")
        self.assertEqual(decision["escalation_assignment_descriptors"][0]["assigned_lens"], "conflict_resolution")

    def test_low_retrieval_confidence_creates_extra_assignment(self) -> None:
        result = self._evaluate(retrieval_quality=_retrieval_quality(status="thin", score=0.55))

        decision = result["decision"]
        self.assertIn("low_retrieval_confidence", decision["trigger_codes"])
        self.assertEqual(decision["additional_assignment_count"], 1)

    def test_low_classification_confidence_creates_extra_assignment(self) -> None:
        result = self._evaluate(
            classifications=[_classification(confidence="low")],
            quality_slices=[_quality(confidence="low", multiplier=0.45)],
        )

        decision = result["decision"]
        self.assertIn("low_classification_confidence", decision["trigger_codes"])
        self.assertEqual(decision["additional_assignment_count"], 1)

    def test_high_pre_scae_leverage_proxy_creates_assignment_without_probability_outputs(self) -> None:
        result = self._evaluate(policy={"high_leverage_leaf_ids": ["leaf-1"]})

        decision = result["decision"]
        self.assertIn("high_scae_leverage_proxy", decision["trigger_codes"])
        self.assertEqual(decision["pre_scae_leverage_proxy"]["bucket"], "high")
        self.assertTrue(decision["pre_scae_leverage_proxy"]["probability_fields_forbidden"])
        serialized = json.dumps(decision, sort_keys=True)
        for forbidden in (
            "own_probability",
            "fair_value",
            "macro_probability",
            "forecast_probability",
            "log_odds",
            "scae_delta",
            "decision_recommendation",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_structural_unanswerability_requires_independent_confirmation(self) -> None:
        result = self._evaluate(
            certificate=_certificate(status="structurally_unanswerable"),
            classifications=[],
            direction_slices=[],
            quality_slices=[],
            retrieval_quality=_retrieval_quality(status="blocked", score=0.25),
        )

        decision = result["decision"]
        self.assertIn("structural_unanswerability_claimed", decision["trigger_codes"])
        self.assertEqual(decision["additional_assignment_count"], 1)
        self.assertEqual(decision["escalation_assignment_descriptors"][0]["assignment_role"], "confirmation")
        self.assertEqual(decision["escalation_assignment_descriptors"][0]["assigned_lens"], "unanswerability_confirmation")
        self.assertEqual(decision["completion_status"], "required_pending")

    def test_concurrency_cap_of_five_leaf_researchers_per_case_is_enforced(self) -> None:
        result = self._evaluate(
            classifications=[_classification(confidence="low")],
            current_case_active_leaf_researcher_count=MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE,
        )

        decision = result["decision"]
        self.assertIn("low_classification_confidence", decision["trigger_codes"])
        self.assertEqual(decision["additional_assignment_count"], 0)
        self.assertEqual(decision["completion_status"], "cap_reached")

    def test_max_assignments_per_leaf_is_enforced(self) -> None:
        existing = [
            {"assignment_id": "leaf-assignment-extra-1", "leaf_id": "leaf-1"},
            {"assignment_id": "leaf-assignment-extra-2", "leaf_id": "leaf-1"},
        ]

        result = self._evaluate(
            classifications=[_classification(confidence="low")],
            existing_leaf_assignments=existing,
        )

        decision = result["decision"]
        self.assertEqual(decision["current_assignments_for_leaf"], MAX_ASSIGNMENTS_PER_LEAF)
        self.assertEqual(decision["additional_assignment_count"], 0)
        self.assertEqual(decision["completion_status"], "cap_reached")

    def test_zero_delivered_or_active_assignments_cannot_mark_escalation_complete(self) -> None:
        result = self._evaluate(classifications=[_classification(confidence="low")])

        decision = result["decision"]
        self.assertEqual(decision["additional_assignment_count"], 1)
        self.assertEqual(decision["escalation_assignment_descriptors"][0]["delivery_status"], "planned_not_spawned")
        self.assertNotEqual(decision["completion_status"], "required_complete")

    def test_validator_rejects_probability_and_payload_fields(self) -> None:
        result = self._evaluate(policy={"high_leverage_leaf_ids": ["leaf-1"]})
        decision = copy.deepcopy(result["decision"])
        decision["pre_scae_leverage_proxy"]["fair_value"] = "forbidden"
        decision["decision_digest"] = compute_researcher_escalation_decision_digest(decision)

        validation = validate_researcher_escalation_decision(decision)

        self.assertFalse(validation.valid)
        self.assertIn("fair_value is forbidden", "; ".join(validation.errors))


if __name__ == "__main__":
    unittest.main()
