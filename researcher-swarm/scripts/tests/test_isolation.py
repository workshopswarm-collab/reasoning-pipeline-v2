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
from researcher_swarm.assignments import (  # noqa: E402
    build_leaf_research_assignments,
    compute_leaf_research_assignment_digest,
    validate_leaf_research_assignment,
)
from researcher_swarm.isolation import (  # noqa: E402
    RESEARCHER_CONTEXT_ISOLATION_SCHEMA_VERSION,
    build_researcher_context_isolation_audit,
    compute_researcher_context_isolation_audit_digest,
    validate_researcher_context_isolation_audit,
    validate_researcher_context_isolation_request,
)
from researcher_swarm.retrieval import (  # noqa: E402
    build_evidence_chunk,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)


class ResearcherContextIsolationAuditTest(unittest.TestCase):
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
        return build_retrieval_evidence_item(
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

    def _certifiable_packet(self) -> dict[str, Any]:
        contexts = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)
        selected = []
        chunks = []
        for context in contexts:
            official = self._evidence(
                context,
                attempt_ref=f"{context['leaf_id']}-official",
                canonical_url=f"https://example.com/official/{context['leaf_id']}",
                source_class="official_or_primary",
                source_family_id=f"source-family-{context['leaf_id']}-official",
                claim_family_id=f"claim-family-{context['leaf_id']}-official",
            )
            official["deterministic_source_class_proof"] = True
            official["source_class_resolution_method"] = "manual_fixture"
            secondary = self._evidence(
                context,
                attempt_ref=f"{context['leaf_id']}-secondary",
                canonical_url=f"https://independent.example/{context['leaf_id']}",
                source_class="independent_secondary",
                source_family_id=f"source-family-{context['leaf_id']}-secondary",
                claim_family_id=f"claim-family-{context['leaf_id']}-secondary",
            )
            selected.extend([official, secondary])
        for item in selected:
            text = f"Isolation certified excerpt for {item['transport_attempt_ref']}"
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
        return finalize_retrieval_packet_for_dispatch(packet)

    def _assignment(self, *, attempt_index: int = 0) -> dict[str, Any]:
        return build_leaf_research_assignments(
            qdt=self.qdt,
            retrieval_packet=self._certifiable_packet(),
            attempt_index=attempt_index,
        )[0]

    def test_builds_launch_allowed_prelaunch_audit(self) -> None:
        assignment = self._assignment()

        audit = build_researcher_context_isolation_audit(assignment)

        self.assertEqual(audit["schema_version"], RESEARCHER_CONTEXT_ISOLATION_SCHEMA_VERSION)
        self.assertEqual(audit["feature_id"], "CLS-008")
        self.assertTrue(audit["fresh_context"])
        self.assertFalse(audit["runtime_launch_performed"])
        self.assertTrue(audit["launch_allowed"], audit["reason_codes"])
        self.assertEqual(audit["reason_codes"], [])
        self.assertEqual(
            audit["visible_artifact_refs"],
            sorted(assignment["context_isolation"]["visible_artifact_ref_allowlist"]),
        )
        self.assertIn("prompt-template:researcher-leaf-nli/v1", audit["allowed_shared_refs"])
        self.assertIn("schema:researcher-sidecar/v2", audit["allowed_shared_refs"])
        self.assertTrue(all(value is False for value in audit["forbidden_ref_scan"].values()))
        self.assertEqual(audit["peer_output_exclusion_proof"]["visible_peer_output_overlap_count"], 0)
        self.assertEqual(audit["audit_digest"], compute_researcher_context_isolation_audit_digest(audit))

        request_result = validate_researcher_context_isolation_request(assignment)
        self.assertTrue(request_result.valid, request_result.errors)
        audit_result = validate_researcher_context_isolation_audit(audit, assignment=assignment)
        self.assertTrue(audit_result.valid, audit_result.errors)

    def test_rejects_forbidden_visible_refs_from_context_allowlist(self) -> None:
        assignment = self._assignment()
        forbidden_cases = {
            "sibling assignment": (
                "artifact:leaf-research-assignment/leaf-assignment-peer",
                "sibling_assignment_refs_present",
                "forbidden_sibling_assignment_ref",
            ),
            "peer sidecar": (
                "artifact:researcher-sidecar/peer",
                "peer_sidecar_refs_present",
                "forbidden_peer_sidecar_ref",
            ),
            "peer output": (
                "artifact:researcher-classification/peer",
                "peer_output_refs_present",
                "forbidden_peer_output_ref",
            ),
            "aggregate summary": (
                "artifact:aggregate-research-summary/case-1",
                "aggregate_summary_refs_present",
                "forbidden_aggregate_summary_ref",
            ),
            "scae ref": ("scae-ledger:case-1", "scae_refs_present", "forbidden_scae_ref"),
            "prediction ref": (
                "market-prediction:case-1",
                "prediction_scoring_refs_present",
                "forbidden_prediction_forecast_replay_scoring_ref",
            ),
            "forecast ref": (
                "forecast:case-1",
                "prediction_scoring_refs_present",
                "forbidden_prediction_forecast_replay_scoring_ref",
            ),
            "replay ref": (
                "replay-result:case-1",
                "prediction_scoring_refs_present",
                "forbidden_prediction_forecast_replay_scoring_ref",
            ),
            "scoring ref": (
                "artifact:research-scoring/peer",
                "prediction_scoring_refs_present",
                "forbidden_prediction_forecast_replay_scoring_ref",
            ),
            "outcome ref": (
                "outcome-scoring:market-1",
                "outcome_refs_present",
                "forbidden_outcome_ref",
            ),
        }

        for name, (ref, scan_field, reason_code) in forbidden_cases.items():
            with self.subTest(name=name):
                broken = copy.deepcopy(assignment)
                broken["context_isolation"]["visible_artifact_ref_allowlist"].append(ref)
                broken["context_isolation"]["visible_artifact_ref_allowlist"].sort()
                broken["assignment_digest"] = compute_leaf_research_assignment_digest(broken)
                self.assertTrue(validate_leaf_research_assignment(broken).valid)

                audit = build_researcher_context_isolation_audit(broken)
                request_result = validate_researcher_context_isolation_request(broken)

                self.assertFalse(audit["launch_allowed"])
                self.assertTrue(audit["forbidden_ref_scan"][scan_field])
                self.assertIn(reason_code, audit["reason_codes"])
                self.assertFalse(request_result.valid)
                self.assertIn(reason_code, request_result.errors)
                self.assertTrue(
                    validate_researcher_context_isolation_audit(audit, assignment=broken).valid,
                    audit["reason_codes"],
                )

    def test_blocks_launch_when_context_is_not_fresh(self) -> None:
        assignment = self._assignment()

        audit = build_researcher_context_isolation_audit(assignment, fresh_context=False)

        self.assertFalse(audit["fresh_context"])
        self.assertFalse(audit["launch_allowed"])
        self.assertIn("fresh_context_required", audit["reason_codes"])
        self.assertFalse(validate_researcher_context_isolation_request(assignment, fresh_context=False).valid)
        self.assertTrue(validate_researcher_context_isolation_audit(audit, assignment=assignment).valid)

        truthy_audit = build_researcher_context_isolation_audit(assignment, fresh_context="true")  # type: ignore[arg-type]
        self.assertFalse(truthy_audit["fresh_context"])
        self.assertFalse(truthy_audit["launch_allowed"])

    def test_two_researchers_same_leaf_have_independent_audits_without_peer_sidecars(self) -> None:
        primary = self._assignment(attempt_index=0)
        confirmation = self._assignment(attempt_index=1)
        self.assertEqual(primary["leaf_id"], confirmation["leaf_id"])
        self.assertNotEqual(primary["assignment_id"], confirmation["assignment_id"])

        primary_peer_sidecar = confirmation["artifact_outputs"]["sidecar_artifact_ref"]
        confirmation_peer_sidecar = primary["artifact_outputs"]["sidecar_artifact_ref"]
        primary_audit = build_researcher_context_isolation_audit(
            primary,
            peer_output_refs=[primary_peer_sidecar],
        )
        confirmation_audit = build_researcher_context_isolation_audit(
            confirmation,
            peer_output_refs=[confirmation_peer_sidecar],
        )

        self.assertTrue(primary_audit["launch_allowed"], primary_audit["reason_codes"])
        self.assertTrue(confirmation_audit["launch_allowed"], confirmation_audit["reason_codes"])
        self.assertNotEqual(primary_audit["isolation_audit_id"], confirmation_audit["isolation_audit_id"])
        self.assertNotEqual(primary_audit["audit_digest"], confirmation_audit["audit_digest"])
        self.assertNotIn(primary_peer_sidecar, primary_audit["visible_artifact_refs"])
        self.assertNotIn(confirmation_peer_sidecar, confirmation_audit["visible_artifact_refs"])
        self.assertEqual(primary_audit["peer_output_exclusion_proof"]["visible_peer_output_overlap_count"], 0)
        self.assertEqual(confirmation_audit["peer_output_exclusion_proof"]["visible_peer_output_overlap_count"], 0)

        contaminated_refs = primary["context_isolation"]["visible_artifact_ref_allowlist"] + [primary_peer_sidecar]
        contaminated = build_researcher_context_isolation_audit(
            primary,
            visible_artifact_refs=contaminated_refs,
            peer_output_refs=[primary_peer_sidecar],
        )
        self.assertFalse(contaminated["launch_allowed"])
        self.assertTrue(contaminated["forbidden_ref_scan"]["peer_output_refs_present"])
        self.assertIn("forbidden_peer_output_ref", contaminated["reason_codes"])


if __name__ == "__main__":
    unittest.main()
