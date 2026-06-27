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
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))

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
    ensure_retrieval_persistence_schema,
    ensure_researcher_verification_persistence_schema,
    write_atomic_claim_candidate_slices,
    write_browser_retrieval_attempts,
    write_browser_search_provider_diagnostics,
    write_classification_provenance_slices,
    write_claim_family_resolution_slices,
    write_contradiction_search_attempts,
    write_direction_verification_slices,
    write_evidence_provenance_slices,
    write_evidence_quality_verification_slices,
    write_leaf_research_assignments,
    write_leaf_research_barrier,
    write_metadata_fill_diagnostics,
    write_native_research_attempts,
    write_negative_check_attempts,
    write_normalized_supplemental_evidence,
    write_research_sufficiency_certificate,
    write_research_sufficiency_reconciliation,
    write_researcher_classifications,
    write_researcher_context_isolation_audits,
    write_researcher_coverage_proofs,
    write_researcher_escalation_decisions,
    write_researcher_prompt_artifact,
    write_retrieval_breadth_coverage_slices,
    write_retrieval_breadth_profile,
    write_retrieval_evidence_chunk_slices,
    write_retrieval_evidence_items,
    write_retrieval_expansion_attempts,
    write_retrieval_fallback_state,
    write_retrieval_packet,
    write_retrieval_quality_slices,
    write_scae_readiness_reconciliation,
    write_source_access_and_missingness_slices,
    write_source_metadata_classifier_slices,
    write_source_metadata_resolution_slices,
    write_verification_slices,
)
from researcher_swarm.retrieval import (  # noqa: E402
    build_atomic_claim_candidate,
    build_browser_retrieval_attempt,
    build_claim_family_resolution,
    build_compact_source_candidate_packet,
    build_evidence_chunk,
    build_expected_source_missingness_candidate,
    build_native_research_attempt,
    build_protected_primary_access_failure,
    build_retrieval_evidence_item,
    build_retrieval_expansion_attempt,
    build_retrieval_fallback_state,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    build_source_metadata_classifier_slice,
    build_source_metadata_resolution_placeholder,
    finalize_retrieval_packet_for_dispatch,
)
from researcher_swarm.retrieval_quality import build_retrieval_quality_report  # noqa: E402
from researcher_swarm.supplemental import normalize_supplemental_evidence  # noqa: E402
from researcher_swarm.subagents import build_leaf_research_barrier  # noqa: E402
from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import build_fixture_qdt_candidate, select_qdt_candidate  # noqa: E402


SHA = "sha256:" + "1" * 64


class RetrievalPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_retrieval_persistence_schema(self.conn)
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
                "prompt_template_sha256": SHA,
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

    def tearDown(self) -> None:
        self.conn.close()

    def _evidence(
        self,
        context: dict,
        *,
        attempt_ref: str,
        canonical_url: str,
        source_class: str,
        source_family_id: str,
        claim_family_id: str,
    ) -> dict:
        evidence = build_retrieval_evidence_item(
            case_id="case-1",
            dispatch_id="dispatch-1",
            leaf_id=context["leaf_id"],
            parent_branch_id=context["parent_branch_id"],
            retrieval_transport="browser",
            transport_attempt_ref=attempt_ref,
            requested_url=canonical_url,
            final_url=canonical_url,
            canonical_url=canonical_url,
            source_family_id=source_family_id,
            source_class=source_class,
            temporal_gate_status="pass",
            source_published_at="2026-06-24T11:30:00+00:00",
            captured_at="2026-06-24T12:01:00+00:00",
            artifact_generated_at="2026-06-24T12:01:00+00:00",
            retrieval_capture_for_dispatch=True,
            claim_family_resolution_refs=[claim_family_id],
            admission_reason_codes=["manual_fixture_selected"],
        )
        evidence["deterministic_source_class_proof"] = source_class == "official_or_primary"
        evidence["source_class_resolution_method"] = "manual_fixture"
        return evidence

    def _packet_with_all_surfaces(self) -> dict:
        qdt = copy.deepcopy(self.qdt)
        contexts = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)
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
            qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        first_context = contexts[0]
        first_variant = first_context["query_variants"][0]
        browser_attempt = build_browser_retrieval_attempt(
            first_context,
            first_variant,
            navigation_mode="direct_url",
            requested_url="https://example.com/official",
            final_url="https://example.com/official",
            canonical_url="https://example.com/official",
            extraction_status="accepted",
            result_rank=1,
        )
        native_attempt = build_native_research_attempt(first_context, first_variant)
        first_evidence = packet["leaf_retrieval_results"][0]["selected_evidence"][0]
        chunk = build_evidence_chunk(
            evidence_ref=first_evidence["evidence_ref"],
            content_artifact_ref="artifact:browser-capture/example",
            chunk_index=0,
            char_start=0,
            char_end=12,
            text="Example text",
            excerpt_policy="bounded_for_classifier",
        )
        candidate_packet = build_compact_source_candidate_packet(first_evidence)
        classifier_slice = build_source_metadata_classifier_slice(
            candidate_packet,
            {
                "source_class": "independent_secondary",
                "source_class_confidence": "high",
                "proposed_source_family_hint": "independent.example",
                "reason_codes": ["ordinary_source_class_accepted"],
            },
        )
        claim_candidate = build_atomic_claim_candidate(
            evidence_ref=first_evidence["evidence_ref"],
            leaf_id=first_context["leaf_id"],
            chunk_refs=[chunk["chunk_ref"]],
            proposed_tuple={
                "subject": "Example event",
                "predicate": "happened",
                "object_or_value": "yes",
                "event_time": "2026-06-24",
                "entity_or_jurisdiction": "example",
                "condition_scope": "unconditional",
                "polarity": "affirmed",
            },
            validation_status="accepted_for_normalization",
            candidate_confidence="high",
        )
        claim_family = build_claim_family_resolution([claim_candidate])
        source_metadata = build_source_metadata_resolution_placeholder(
            evidence_ref=first_evidence["evidence_ref"],
            transport_attempt_ref=first_evidence["transport_attempt_ref"],
            canonical_url=first_evidence["canonical_url"],
        )
        packet["browser_retrieval_attempts"].append(browser_attempt)
        packet["native_research_attempts"].append(native_attempt)
        packet["evidence_chunks"].append(chunk)
        packet["source_metadata_classifier_slices"].append(classifier_slice)
        packet["atomic_claim_candidates"].append(claim_candidate)
        packet["claim_family_resolutions"].append(claim_family)
        packet["source_metadata_resolutions"].append(source_metadata)
        packet["protected_primary_access_failures"].append(
            build_protected_primary_access_failure(first_context, packet["leaf_retrieval_results"][0])
        )
        packet["missingness_candidates"].append(
            build_expected_source_missingness_candidate(
                first_context,
                packet["leaf_retrieval_results"][0],
                expected_source_class="official_or_primary",
                expected_source_ref={"source_ref": "official:example"},
            )
        )
        packet = finalize_retrieval_packet_for_dispatch(packet)
        expansion = build_retrieval_expansion_attempt(
            first_context,
            attempt_index=1,
            unsatisfied_requirement_codes=["fixture_targeted_expansion_probe"],
        )
        fallback = build_retrieval_fallback_state(first_context, [expansion["attempt_id"]])
        packet["retrieval_expansion_attempts"].append(expansion)
        packet["retrieval_fallback_states"].append(fallback)
        quality = build_retrieval_quality_report(packet)
        packet["retrieval_quality_slices"] = quality["retrieval_quality_slices"]
        packet["retrieval_quality_summary"] = quality["quality_summary"]
        return packet

    def test_writes_all_mig004_surfaces_compactly_and_idempotently(self) -> None:
        packet = self._packet_with_all_surfaces()
        packet_id = write_retrieval_packet(
            self.conn,
            packet,
            artifact_ref="artifact:retrieval-packet/retrieval-1",
        )
        self.assertEqual(packet_id, "artifact:retrieval-packet/retrieval-1")
        self.assertTrue(write_retrieval_evidence_items(self.conn, packet))
        self.assertEqual(write_retrieval_evidence_chunk_slices(self.conn, packet), [packet["evidence_chunks"][0]["chunk_ref"]])
        self.assertEqual(write_native_research_attempts(self.conn, packet), [packet["native_research_attempts"][0]["attempt_id"]])
        self.assertEqual(write_browser_retrieval_attempts(self.conn, packet), [packet["browser_retrieval_attempts"][0]["attempt_id"]])
        self.assertEqual(len(write_browser_search_provider_diagnostics(self.conn, packet)), 1)
        self.assertEqual(
            write_source_metadata_classifier_slices(self.conn, packet),
            [packet["source_metadata_classifier_slices"][0]["classifier_slice_id"]],
        )
        self.assertTrue(write_source_metadata_resolution_slices(self.conn, packet))
        self.assertEqual(write_atomic_claim_candidate_slices(self.conn, packet), [packet["atomic_claim_candidates"][0]["claim_candidate_id"]])
        self.assertEqual(write_claim_family_resolution_slices(self.conn, packet), [packet["claim_family_resolutions"][0]["claim_family_resolution_id"]])
        self.assertTrue(write_metadata_fill_diagnostics(self.conn, packet))
        self.assertTrue(write_retrieval_quality_slices(self.conn, packet))
        self.assertTrue(write_evidence_provenance_slices(self.conn, packet))
        self.assertTrue(write_retrieval_breadth_profile(self.conn, packet))
        self.assertTrue(write_retrieval_breadth_coverage_slices(self.conn, packet))
        self.assertTrue(write_contradiction_search_attempts(self.conn, packet))
        self.assertTrue(write_negative_check_attempts(self.conn, packet))
        access = write_source_access_and_missingness_slices(self.conn, packet)
        self.assertEqual(len(access["source_access_failure_ids"]), 1)
        self.assertEqual(len(access["missingness_signal_ids"]), 1)
        self.assertTrue(write_retrieval_fallback_state(self.conn, packet))
        self.assertTrue(write_retrieval_expansion_attempts(self.conn, packet))
        self.assertTrue(write_research_sufficiency_certificate(self.conn, packet))

        write_retrieval_packet(self.conn, packet, artifact_ref="artifact:retrieval-packet/retrieval-1")
        write_retrieval_evidence_items(self.conn, packet)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM retrieval_packet_artifacts").fetchone()["n"],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM retrieval_evidence_items").fetchone()["n"],
            sum(len(result["selected_evidence"]) for result in packet["leaf_retrieval_results"]),
        )
        chunk_row = self.conn.execute("SELECT text_sha256, content_artifact_ref FROM retrieval_evidence_chunk_slices").fetchone()
        self.assertEqual(chunk_row["content_artifact_ref"], "artifact:browser-capture/example")
        self.assertTrue(chunk_row["text_sha256"].startswith("sha256:"))
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(retrieval_evidence_chunk_slices)").fetchall()
        }
        self.assertNotIn("text", columns)

    def test_rejects_raw_payloads_and_forbidden_authority_fields(self) -> None:
        packet = self._packet_with_all_surfaces()
        bad_packet = copy.deepcopy(packet)
        bad_packet["leaf_retrieval_results"][0]["selected_evidence"][0]["page_text"] = "full rendered body"
        with self.assertRaises(ResearcherPersistenceError):
            write_retrieval_packet(self.conn, bad_packet)

        bad_evidence = copy.deepcopy(packet["leaf_retrieval_results"][0]["selected_evidence"][0])
        bad_evidence["scae_delta"] = 0.1
        with self.assertRaises(ResearcherPersistenceError):
            write_retrieval_evidence_items(self.conn, [bad_evidence])

        bad_certificate = copy.deepcopy(packet["leaf_research_sufficiency_certificates"][0])
        bad_certificate["authority_boundary"]["forecast_authority"] = True
        with self.assertRaises(ResearcherPersistenceError):
            write_research_sufficiency_certificate(
                self.conn,
                [bad_certificate],
            )

    def test_missingness_schema_adds_retrieval_columns_to_existing_scae_shape(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.executescript(
                """
                CREATE TABLE missingness_signal_slices (
                  slice_id TEXT PRIMARY KEY,
                  schema_version TEXT NOT NULL,
                  artifact_type TEXT,
                  case_id TEXT,
                  dispatch_id TEXT,
                  leaf_id TEXT,
                  parent_branch_id TEXT,
                  condition_scope TEXT,
                  feature_id TEXT,
                  surface_name TEXT NOT NULL DEFAULT 'missingness_signal_slices',
                  source_ref TEXT,
                  source_family_id TEXT,
                  claim_family_id TEXT,
                  mechanism_family_id TEXT,
                  dependency_group_id TEXT,
                  signed_log_odds_delta REAL,
                  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
                  diagnostic_only INTEGER NOT NULL DEFAULT 1,
                  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
                  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
                  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
                  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
                  reason_codes TEXT NOT NULL DEFAULT '[]',
                  source_refs TEXT NOT NULL DEFAULT '[]',
                  payload_json TEXT NOT NULL,
                  payload_sha256 TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            ensure_retrieval_persistence_schema(conn)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(missingness_signal_slices)")}
            self.assertIn("expected_source_class", columns)
            self.assertIn("attempt_refs_checked", columns)
        finally:
            conn.close()


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
                "provider_model_key": "openai/gpt-5.5-high",
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
                "follow_up_research": {
                    "max_direct_url_fetches": 5,
                    "max_native_candidate_urls": 4,
                    "max_supplemental_evidence_refs": 3,
                    "allowed_transports": [
                        "assigned_evidence_refs",
                        "direct_url_from_assigned_evidence",
                        "browser_retrieval",
                    ],
                    "supplemental_evidence_requires_deterministic_admission": True,
                },
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
        barrier = build_leaf_research_barrier([assignment])
        self.assertEqual(write_leaf_research_barrier(self.conn, barrier, assignments=[assignment]), barrier["barrier_id"])
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
        barrier_row = self.conn.execute("SELECT blocker_reason_codes FROM leaf_research_barriers").fetchone()
        self.assertEqual(json.loads(barrier_row["blocker_reason_codes"]), ["missing_leaf_subagent_result"])

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
