#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import build_fixture_qdt_candidate, select_qdt_candidate  # noqa: E402
from predquant.ads_handoff import validate_artifact_manifest  # noqa: E402
from researcher_swarm.assignments import (  # noqa: E402
    LeafResearchAssignmentError,
    build_leaf_research_assignments,
)
from researcher_swarm.browser_provider import BrowserProviderAdapter, ConfiguredBrowserProvider, build_provider  # noqa: E402
from researcher_swarm.retrieval import (  # noqa: E402
    RetrievalPacketError,
    attach_native_research_transport_diagnostics,
    attach_retrieval_expansion_and_fallback_plan,
    attach_source_metadata_classifier_unavailable,
    attach_source_access_and_missingness,
    build_atomic_claim_candidate,
    build_atomic_claim_candidates_from_classifier_slice,
    build_browser_retrieval_attempt,
    build_claim_family_resolution,
    build_compact_source_candidate_packet,
    build_evidence_chunk,
    build_evidence_span,
    build_live_retrieval_packet_from_candidates,
    build_native_research_attempt,
    build_retrieval_candidate_record,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_packet_manifest,
    build_retrieval_query_contexts,
    build_retrieval_fallback_state,
    build_search_candidate_url,
    build_native_research_candidate_discovery,
    finalize_retrieval_packet_for_dispatch,
    build_source_metadata_classifier_slice,
    build_source_metadata_resolution_placeholder,
    normalize_retrieval_provenance,
    resolve_claim_families,
    resolve_source_metadata_classifier_lane,
    validate_temporal_eligibility,
    dump_retrieval_packet,
    validate_retrieval_packet,
)


class RetrievalPacketContractTest(unittest.TestCase):
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
        context: dict,
        *,
        attempt_ref: str,
        canonical_url: str,
        source_class: str = "independent_secondary",
        source_family_id: str | None = None,
        claim_family_id: str = "claim-family-default",
        source_published_at: str = "2026-06-24T11:30:00+00:00",
        temporal_gate_status: str = "pass",
    ) -> dict:
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
            temporal_gate_status=temporal_gate_status,
            source_published_at=source_published_at,
            captured_at="2026-06-24T12:01:00+00:00",
            artifact_generated_at="2026-06-24T12:01:00+00:00",
            retrieval_capture_for_dispatch=True,
            claim_family_resolution_refs=[claim_family_id],
            admission_reason_codes=["manual_fixture_selected"],
        )

    def _context_requires_source_class(self, context: dict, source_class: str) -> bool:
        requirements = context.get("sufficiency_requirements")
        return isinstance(requirements, dict) and source_class in set(
            requirements.get("required_source_classes") or []
        )

    def _certifiable_packet(self, qdt: dict | None = None) -> dict:
        qdt = copy.deepcopy(qdt or self.qdt)
        contexts = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)
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
            if self._context_requires_source_class(context, "expert_or_specialist"):
                selected.append(
                    self._evidence(
                        context,
                        attempt_ref=f"{context['leaf_id']}-specialist",
                        canonical_url=f"https://gartner.com/{context['leaf_id']}",
                        source_class="expert_or_specialist",
                        source_family_id=f"source-family-{context['leaf_id']}-specialist",
                        claim_family_id=f"claim-family-{context['leaf_id']}-specialist",
                    )
                )
        for item in selected:
            text = (
                f"Certified source excerpt for {item['transport_attempt_ref']} with enough bounded "
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
            qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        packet["evidence_chunks"] = chunks
        return packet

    def _live_candidate(
        self,
        context: dict,
        index: int,
        *,
        direct: bool = False,
        official: bool = False,
        source_class: str | None = None,
    ) -> dict:
        leaf_id = context["leaf_id"]
        if source_class is None:
            source_class = "official_or_primary" if official else "independent_secondary"
        if direct:
            url = f"https://example.com/official/{leaf_id}"
        elif source_class == "expert_or_specialist":
            url = f"https://gartner.com/{leaf_id}/{index}"
        else:
            url = f"https://independent{index}.example/{leaf_id}"
        supporting_text = f"Live-shaped candidate {index} for {leaf_id} supports the required evidence field."
        content = (
            supporting_text
            + " The fetched source contains bounded detail for researcher classification and claim extraction. " * 8
        )
        return {
            "leaf_id": leaf_id,
            "parent_branch_id": context["parent_branch_id"],
            "navigation_mode": "direct_url" if direct else "web_search",
            "requested_url": url,
            "final_url": url,
            "canonical_url": url,
            "source_class": source_class,
            "source_family_id": f"source-family-live-{leaf_id}-{index}",
            "claim_family_id": f"claim-family-live-{leaf_id}-{index % 3}",
            "source_published_at": "2026-06-24T11:30:00+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "deterministic_source_class_proof": official or source_class == "expert_or_specialist",
            "source_class_resolution_method": "manual_fixture" if official else "deterministic_url_registry",
            "source_family_resolution_method": "deterministic_url_registry",
            "result_rank": index + 1,
            "content": content,
            "validated_atomic_claim_candidates": [
                {
                    "subject": f"Live-shaped candidate {index}",
                    "predicate": "supports",
                    "object_or_value": leaf_id,
                    "event_time": "2026-06-24",
                    "entity_or_jurisdiction": "example",
                    "condition_scope": "unconditional",
                    "polarity": "affirmed",
                    "supporting_text": supporting_text,
                    "candidate_confidence": "high",
                }
            ],
        }

    def _live_candidates_for_context(self, context: dict, *, include_direct: bool = True, count: int = 5) -> list[dict]:
        candidates = []
        start = 0
        if include_direct:
            candidates.append(self._live_candidate(context, 0, direct=True, official=True))
            start = 1
        for index in range(start, count):
            candidates.append(self._live_candidate(context, index))
        if self._context_requires_source_class(context, "expert_or_specialist"):
            candidates.append(self._live_candidate(context, count, source_class="expert_or_specialist"))
        return candidates

    def _search_candidates_for_context(self, context: dict, candidates: list[dict]) -> list[dict]:
        variant = context["query_variants"][0]
        records = []
        for candidate in candidates:
            if candidate.get("navigation_mode") != "web_search":
                continue
            records.append(
                build_search_candidate_url(
                    context,
                    variant,
                    rank=int(candidate["result_rank"]),
                    url=candidate["canonical_url"],
                    title=f"Candidate {candidate['result_rank']}",
                    snippet=candidate["content"],
                    searched_at="2026-06-24T11:59:00+00:00",
                )
            )
        return records

    def _two_leaf_qdt(self) -> dict:
        qdt = copy.deepcopy(self.qdt)
        keep = {"leaf-source-of-truth", "leaf-direct-evidence"}
        qdt["required_leaf_questions"] = [
            leaf for leaf in qdt["required_leaf_questions"] if leaf["leaf_id"] in keep
        ]
        qdt["branches"] = [
            branch
            for branch in qdt["branches"]
            if set(branch.get("leaf_ids", [])) & keep
        ]
        return qdt

    def _shared_source_candidates(self, qdt: dict) -> list[dict]:
        contexts = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)
        candidates: list[dict] = []
        shared_content = (
            "Shared source content with enough bounded detail for researcher classification and "
            "claim extraction across every mapped leaf. "
            * 8
        )
        for index, context in enumerate(contexts):
            shared = self._live_candidate(context, index, direct=True, official=True)
            shared["canonical_url"] = "https://example.com/shared-source"
            shared["requested_url"] = shared["canonical_url"]
            shared["final_url"] = shared["canonical_url"]
            shared["content"] = shared_content
            secondary = self._live_candidate(context, index + 10, source_class="independent_secondary")
            candidates.extend([shared, secondary])
        return candidates

    def test_query_contexts_cover_every_leaf_with_sufficiency_and_breadth_targets(self) -> None:
        contexts = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)

        self.assertEqual(
            sorted(context["leaf_id"] for context in contexts),
            sorted(leaf["leaf_id"] for leaf in self.qdt["required_leaf_questions"]),
        )
        for context in contexts:
            self.assertIn("sufficiency_requirements", context)
            self.assertIn("breadth_profile_ref", context)
            self.assertIn("source_class_targets", context["breadth_targets"])
            self.assertIn("min_independent_claim_families", context["breadth_targets"])
            self.assertIn("min_independent_source_families", context["breadth_targets"])
            self.assertGreaterEqual(len(context["query_variants"]), 1)
            self.assertGreaterEqual(len(context["direct_url_candidates"]), 2)

    def test_contradiction_negative_check_and_condition_scope_are_in_query_context(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["leaf_condition_scope"] = "target_given_upstream"
        leaf["research_sufficiency_requirements"]["required_negative_checks"] = ["no_official_confirmation"]

        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]

        self.assertTrue(context["contradiction_query_variants"])
        self.assertIn("no_official_confirmation", context["negative_check_query_variants"])
        joined_query_text = " ".join(variant["query_text"] for variant in context["query_variants"])
        self.assertIn("condition scope target given upstream", joined_query_text)
        self.assertNotIn(context["parent_branch_id"], joined_query_text)

    def test_amrg_hints_reject_probability_or_scae_injection(self) -> None:
        with self.assertRaises(RetrievalPacketError):
            build_retrieval_query_contexts(
                self.qdt,
                evidence_packet=self.evidence_packet,
                amrg_context={"candidate_refs": ["amrg:1"], "probability": 0.9},
            )

    def test_active_retrieval_rejects_replay_outcome_and_scoring_surface_inputs(self) -> None:
        forbidden_amrg_inputs = [
            {"candidate_refs": ["amrg:1"], "replay_result_ref": "replay-result:case-1"},
            {"candidate_refs": ["amrg:1"], "outcome_scoring_ref": "outcome-scoring:market-1"},
            {"candidate_refs": ["amrg:1"], "market_prediction_ref": "market-prediction:case-1"},
            {"candidate_refs": ["amrg:1"], "raw_forecast_result_payload": {"probability": 0.7}},
        ]

        for amrg_context in forbidden_amrg_inputs:
            with self.subTest(amrg_context=amrg_context):
                with self.assertRaises(RetrievalPacketError):
                    build_retrieval_query_contexts(
                        self.qdt,
                        evidence_packet=self.evidence_packet,
                        amrg_context=amrg_context,
                    )

    def test_compact_candidate_packet_rejects_replay_outcome_and_scoring_surface_refs(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        candidate = build_retrieval_candidate_record(
            leaf_id=context["leaf_id"],
            query_context_ref=context["query_context_ref"],
            query_variant_id=variant["query_variant_id"],
            retrieval_transport="browser",
            transport_attempt_ref="browser-attempt:1",
            candidate_status="selected",
            requested_url="https://example.com/source",
            canonical_url="https://example.com/source",
            temporal_gate_status="pass",
        )
        candidate["scorecard_artifact_ref"] = "artifact:scorecard-1"

        with self.assertRaises(RetrievalPacketError):
            build_compact_source_candidate_packet(candidate)

    def test_packet_validation_rejects_replay_outcome_and_scoring_surface_refs(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        evidence = self._evidence(
            context,
            attempt_ref="browser-attempt:1",
            canonical_url="https://example.com/source",
        )
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet, selected_evidence=[evidence])
        packet["leaf_retrieval_results"][0]["selected_evidence"][0][
            "resolution_outcome_ref"
        ] = "outcome-scoring:market-1"

        result = validate_retrieval_packet(packet)

        self.assertFalse(result.valid)
        self.assertIn("resolution_outcome_ref is forbidden", "; ".join(result.errors))

    def test_packet_schema_contains_feature_gated_placeholders_without_marking_later_rows_ready(self) -> None:
        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        result = validate_retrieval_packet(packet)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(packet["schema_feature_gates"]["RET-001"], "implemented")
        self.assertEqual(packet["schema_feature_gates"]["RET-002"], "implemented")
        self.assertEqual(packet["schema_feature_gates"]["RET-004"], "implemented")
        self.assertEqual(packet["schema_feature_gates"]["RET-009"], "implemented")
        self.assertEqual(len(packet["retrieval_breadth_profiles"]), len(self.qdt["required_leaf_questions"]))
        self.assertEqual(len(packet["retrieval_breadth_coverage_slices"]), len(self.qdt["required_leaf_questions"]))
        for feature_id in ["RET-003", "RET-008", "RET-010", "RET-011"]:
            self.assertEqual(packet["schema_feature_gates"][feature_id], "pending")
        self.assertEqual(packet["temporal_isolation_schema_gate"]["status"], "strict_validator_implemented")
        self.assertEqual(packet["research_sufficiency_summary"]["classification_dispatch_status"], "blocked_until_certified")
        self.assertEqual(packet["browser_search_provider_diagnostics"][0]["provider_id"], "openclaw_web_fetch_browser")

    def test_live_policy_overlay_raises_effective_thresholds_without_mutating_qdt(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        packet = self._certifiable_packet(qdt=qdt)
        overlay_packet = build_retrieval_packet(
            qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=[
                evidence
                for result in packet["leaf_retrieval_results"]
                for evidence in result["selected_evidence"]
            ],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_policy_overlay=True,
        )
        finalized = finalize_retrieval_packet_for_dispatch(overlay_packet)

        self.assertEqual(
            finalized["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertTrue(
            any(
                "admitted_evidence_count" in slice_.get("unsatisfied_breadth_dimensions", [])
                for slice_ in finalized["retrieval_breadth_coverage_slices"]
            )
        )
        for profile in finalized["retrieval_breadth_profiles"]:
            self.assertTrue(profile["effective_policy_overlay"]["enabled"])
            self.assertEqual(profile["effective_policy_overlay"]["policy_id"], "ads-live-retrieval-policy/v1")
        self.assertNotIn("effective_policy_overlay", qdt["required_leaf_questions"][0])

    def test_finalized_packet_builds_leaf_evidence_dockets_for_dispatch(self) -> None:
        finalized = finalize_retrieval_packet_for_dispatch(self._certifiable_packet())

        self.assertEqual(len(finalized["leaf_evidence_dockets"]), len(self.qdt["required_leaf_questions"]))
        for docket in finalized["leaf_evidence_dockets"]:
            self.assertEqual(docket["schema_version"], "leaf-evidence-docket/v1")
            self.assertTrue(docket["admitted_evidence_refs"])
            self.assertEqual(docket["research_sufficiency_status"], "certified_high_certainty")
            self.assertTrue(docket["classification_dispatch_allowed"])
            self.assertTrue(docket["proceed_to_classification"])
            self.assertFalse(docket["classification_authority"])
            self.assertFalse(docket["scae_authority"])

    def test_same_source_fans_out_to_multiple_leaves_without_new_source_families(self) -> None:
        qdt = self._two_leaf_qdt()
        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=self._shared_source_candidates(qdt),
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_retrieval_allowlist=["browser"],
        )

        shared_mappings = [
            item
            for item in packet["source_relevance_mappings"]
            if item["canonical_url"] == "https://example.com/shared-source"
        ]
        self.assertEqual({item["leaf_id"] for item in shared_mappings}, {"leaf-source-of-truth", "leaf-direct-evidence"})
        self.assertEqual(len({item["canonical_fetch_ref"] for item in shared_mappings}), 1)
        self.assertEqual(len({item["source_content_artifact_ref"] for item in shared_mappings}), 1)
        self.assertEqual(len({item["source_family_id"] for item in shared_mappings}), 1)
        shared_family_id = shared_mappings[0]["source_family_id"]
        shared_family_evidence_count = sum(
            1
            for result in packet["leaf_retrieval_results"]
            for evidence in result["selected_evidence"]
            if evidence.get("source_family_id") == shared_family_id
        )
        self.assertEqual(shared_family_evidence_count, 2)

    def test_leaf_dockets_include_shared_source_relevance_refs(self) -> None:
        qdt = self._two_leaf_qdt()
        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=self._shared_source_candidates(qdt),
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_retrieval_allowlist=["browser"],
        )
        mapping_refs_by_leaf = {
            item["leaf_id"]: {
                mapping["source_relevance_ref"]
                for mapping in packet["source_relevance_mappings"]
                if mapping["leaf_id"] == item["leaf_id"]
            }
            for item in packet["leaf_evidence_dockets"]
        }

        for docket in packet["leaf_evidence_dockets"]:
            self.assertTrue(docket["source_relevance_mapping_refs"])
            self.assertTrue(set(docket["source_relevance_mapping_refs"]).issubset(mapping_refs_by_leaf[docket["leaf_id"]]))
            self.assertTrue(docket["canonical_fetch_refs"])

    def test_browser_and_native_attempt_records_are_refs_not_metadata_authority(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]

        browser_attempt = build_browser_retrieval_attempt(context, variant)
        native_attempt = build_native_research_attempt(context, variant)

        self.assertEqual(browser_attempt["schema_version"], "browser-retrieval-attempt/v1")
        self.assertEqual(browser_attempt["browser_provider_id"], "openclaw_web_fetch_browser")
        self.assertNotIn("source_class", browser_attempt)
        self.assertNotIn("claim_family_id", browser_attempt)
        self.assertEqual(native_attempt["model_lane_id"], "native_research_candidate_discovery")
        self.assertNotIn("source_family_id", native_attempt)
        self.assertEqual(native_attempt["attempt_status"], "failed")

    def test_selected_evidence_omitted_candidates_and_resolution_placeholders_validate(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        browser_attempt = build_browser_retrieval_attempt(
            context,
            variant,
            navigation_mode="direct_url",
            requested_url="https://example.com/official",
            final_url="https://example.com/official",
            canonical_url="https://example.com/official",
            extraction_status="accepted",
            result_rank=1,
        )
        evidence = build_retrieval_evidence_item(
            case_id="case-1",
            dispatch_id="dispatch-1",
            leaf_id=context["leaf_id"],
            parent_branch_id=context["parent_branch_id"],
            retrieval_transport="browser",
            transport_attempt_ref=browser_attempt["attempt_id"],
            requested_url=browser_attempt["requested_url"],
            final_url=browser_attempt["final_url"],
            canonical_url=browser_attempt["canonical_url"],
            temporal_gate_status="pass",
            source_published_at="2026-06-24T11:30:00+00:00",
            captured_at="2026-06-24T12:01:00+00:00",
            artifact_generated_at="2026-06-24T12:01:00+00:00",
            retrieval_capture_for_dispatch=True,
            admission_reason_codes=["manual_fixture_selected"],
        )
        chunk = build_evidence_chunk(
            evidence_ref=evidence["evidence_ref"],
            content_artifact_ref="artifact:browser-capture/example",
            chunk_index=0,
            char_start=0,
            char_end=12,
            text="Example text",
        )
        span = build_evidence_span(
            chunk_ref=chunk["chunk_ref"],
            char_start=0,
            char_end=7,
            text="Example",
        )
        claim_candidate = build_atomic_claim_candidate(
            evidence_ref=evidence["evidence_ref"],
            leaf_id=context["leaf_id"],
            chunk_refs=[chunk["chunk_ref"]],
            supporting_span_refs=[span["span_ref"]],
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
            evidence_ref=evidence["evidence_ref"],
            transport_attempt_ref=browser_attempt["attempt_id"],
            canonical_url=evidence["canonical_url"],
        )
        omitted = build_retrieval_candidate_record(
            leaf_id=context["leaf_id"],
            query_context_ref=context["query_context_ref"],
            query_variant_id=variant["query_variant_id"],
            retrieval_transport="browser",
            transport_attempt_ref=browser_attempt["attempt_id"],
            candidate_status="omitted",
            requested_url="https://example.com/duplicate",
            canonical_url="https://example.com/duplicate",
            omission_reason_codes=["duplicate_source_family"],
        )
        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=[evidence],
            omitted_candidates=[omitted],
        )
        packet["browser_retrieval_attempts"].append(browser_attempt)
        packet["evidence_chunks"].append(chunk)
        packet["evidence_spans"].append(span)
        packet["atomic_claim_candidates"].append(claim_candidate)
        packet["claim_family_resolutions"].append(claim_family)
        packet["source_metadata_resolutions"].append(source_metadata)

        result = validate_retrieval_packet(packet)

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(packet["retrieval_evidence_provenance_slices"][0]["temporal_gate_status"], "pass")
        self.assertTrue(claim_family["claim_family_id"].startswith("claim-family-"))
        self.assertEqual(claim_family["counts_toward_claim_family_breadth"], True)
        self.assertEqual(source_metadata["temporal_safety_status"], "unknown_not_counted")

    def test_breadth_coverage_attempts_and_metadata_fill_can_certify_leaf_breadth(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "source_of_truth"
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary", "independent_secondary"],
                "min_independent_claim_families": 2,
                "min_independent_source_families": 2,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "contradiction_search_required": True,
                "required_negative_checks": ["no_official_confirmation"],
                "protected_primary_required": True,
            }
        )
        evidence_packet = copy.deepcopy(self.evidence_packet)
        evidence_packet["market_rules"]["official_source_hints"] = ["https://example.com/official"]
        context = build_retrieval_query_contexts(qdt, evidence_packet=evidence_packet)[0]
        official = self._evidence(
            context,
            attempt_ref="official",
            canonical_url="https://example.com/official",
            source_class="official_or_primary",
            source_family_id="source-family-official",
            claim_family_id="claim-family-official",
        )
        secondary = self._evidence(
            context,
            attempt_ref="secondary",
            canonical_url="https://news.example.com/story",
            source_class="independent_secondary",
            source_family_id="source-family-secondary",
            claim_family_id="claim-family-secondary",
        )

        packet = build_retrieval_packet(qdt, evidence_packet=evidence_packet, selected_evidence=[official, secondary])
        coverage = next(
            item for item in packet["retrieval_breadth_coverage_slices"] if item["leaf_id"] == leaf["leaf_id"]
        )

        self.assertTrue(validate_retrieval_packet(packet).valid)
        self.assertEqual(packet["schema_feature_gates"]["RET-009"], "implemented")
        self.assertTrue(packet["contradiction_search_attempts"])
        self.assertTrue(packet["negative_check_attempts"])
        self.assertEqual(packet["negative_check_attempts"][0]["outcome_status"], "no_confirmation_found")
        self.assertTrue(coverage["breadth_certified"], coverage["unsatisfied_breadth_dimensions"])
        self.assertEqual(coverage["protected_primary_status"], "satisfied")
        self.assertEqual(coverage["raw_candidate_count"], 2)
        self.assertEqual(coverage["admitted_ref_count"], 2)
        self.assertEqual(coverage["claim_family_count"], 2)
        self.assertEqual(coverage["source_family_count"], 2)
        self.assertGreaterEqual(coverage["fresh_source_count"], 1)
        self.assertTrue(coverage["metadata_fill_diagnostic_refs"])
        diagnostic = packet["retrieval_metadata_fill_diagnostics"][0]
        self.assertEqual(diagnostic["leaf_id"], leaf["leaf_id"])
        self.assertEqual(diagnostic["admitted_ref_count"], 2)
        self.assertEqual(diagnostic["unknown_counts"]["source_class"], 0)
        self.assertEqual(packet["research_sufficiency_summary"]["certificate_status"], "not_run_schema_only")

    def test_duplicate_claim_or_source_family_does_not_satisfy_independent_breadth(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["independent_secondary"],
                "min_independent_claim_families": 2,
                "min_independent_source_families": 2,
                "min_temporally_fresh_sources": 0,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        same_claim = [
            self._evidence(
                context,
                attempt_ref=f"same-claim-{idx}",
                canonical_url=f"https://publisher-{idx}.example.com/story",
                source_family_id=f"source-family-{idx}",
                claim_family_id="claim-family-repeated",
            )
            for idx in range(5)
        ]
        same_source = [
            self._evidence(
                context,
                attempt_ref=f"same-source-{idx}",
                canonical_url=f"https://wire-{idx}.example.com/story",
                source_family_id="source-family-wire",
                claim_family_id=f"claim-family-{idx}",
            )
            for idx in range(5)
        ]
        same_publisher = [
            self._evidence(
                context,
                attempt_ref=f"same-publisher-{idx}",
                canonical_url=f"https://same-publisher.example.com/story-{idx}",
                source_family_id="source-family-unknown",
                claim_family_id=f"claim-family-publisher-{idx}",
            )
            for idx in range(5)
        ]
        duplicate_content = []
        for idx in range(2):
            item = self._evidence(
                context,
                attempt_ref=f"duplicate-content-{idx}",
                canonical_url=f"https://mirror-{idx}.test/story",
                source_family_id="source-family-unknown",
                claim_family_id=f"claim-family-duplicate-content-{idx}",
            )
            item["content_sha256"] = "sha256:" + "b" * 64
            item["chunk_refs"] = [f"chunk:duplicate-content-{idx}"]
            duplicate_content.append(item)

        same_claim_packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=same_claim)
        same_claim_coverage = next(
            item for item in same_claim_packet["retrieval_breadth_coverage_slices"] if item["leaf_id"] == leaf["leaf_id"]
        )
        same_source_packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=same_source)
        same_source_coverage = next(
            item for item in same_source_packet["retrieval_breadth_coverage_slices"] if item["leaf_id"] == leaf["leaf_id"]
        )
        same_publisher_packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=same_publisher)
        same_publisher_coverage = next(
            item for item in same_publisher_packet["retrieval_breadth_coverage_slices"] if item["leaf_id"] == leaf["leaf_id"]
        )
        duplicate_content_packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=duplicate_content)
        duplicate_content_coverage = next(
            item for item in duplicate_content_packet["retrieval_breadth_coverage_slices"] if item["leaf_id"] == leaf["leaf_id"]
        )

        self.assertEqual(same_claim_coverage["claim_family_count"], 1)
        self.assertFalse(same_claim_coverage["breadth_certified"])
        self.assertIn("claim_family_diversity", same_claim_coverage["unsatisfied_breadth_dimensions"])
        self.assertIn(
            "same_claim_family",
            {item["independence_status"] for item in same_claim_packet["retrieval_evidence_provenance_slices"]},
        )
        self.assertEqual(same_source_coverage["source_family_count"], 1)
        self.assertFalse(same_source_coverage["breadth_certified"])
        self.assertIn("source_family_diversity", same_source_coverage["unsatisfied_breadth_dimensions"])
        self.assertIn(
            "same_source_family",
            {item["independence_status"] for item in same_source_packet["retrieval_evidence_provenance_slices"]},
        )
        self.assertEqual(same_publisher_coverage["source_family_count"], 1)
        self.assertFalse(same_publisher_coverage["breadth_certified"])
        self.assertIn("source_family_diversity", same_publisher_coverage["unsatisfied_breadth_dimensions"])
        self.assertIn(
            "same_source_family",
            {item["independence_status"] for item in same_publisher_packet["retrieval_evidence_provenance_slices"]},
        )
        self.assertEqual(duplicate_content_coverage["source_family_count"], 1)
        self.assertFalse(duplicate_content_coverage["breadth_certified"])
        self.assertIn("source_family_diversity", duplicate_content_coverage["unsatisfied_breadth_dimensions"])
        self.assertIn(
            "syndicated_copy",
            {item["independence_status"] for item in duplicate_content_packet["retrieval_evidence_provenance_slices"]},
        )

    def test_unknown_metadata_and_protected_primary_gaps_block_breadth(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "source_of_truth"
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "protected_primary_required": True,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        unknown = self._evidence(
            context,
            attempt_ref="unknown",
            canonical_url="",
            source_class="unknown",
            source_family_id="source-family-unknown",
            claim_family_id="claim-family-unknown",
            temporal_gate_status="unknown_not_counted",
            source_published_at=None,
        )

        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=[unknown])
        coverage = next(
            item for item in packet["retrieval_breadth_coverage_slices"] if item["leaf_id"] == leaf["leaf_id"]
        )

        self.assertFalse(coverage["breadth_certified"])
        self.assertEqual(coverage["protected_primary_status"], "blocked")
        self.assertTrue(coverage["expansion_required"])
        self.assertIn("protected_primary_blocked", coverage["unsatisfied_breadth_dimensions"])
        self.assertIn("unknown_source_class_blocks_required_breadth", coverage["unsatisfied_breadth_dimensions"])
        self.assertIn("unknown_temporal_blocks_required_breadth", coverage["unsatisfied_breadth_dimensions"])

    def test_temporal_validator_rejects_post_cutoff_source_time(self) -> None:
        result = validate_temporal_eligibility(
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "retrieval_transport": "browser",
                "source_published_at": "2026-06-24T12:00:01+00:00",
            },
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )

        self.assertEqual(result["temporal_gate_status"], "fail")
        self.assertIn("source_after_cutoff", result["rejection_reason_codes"])

    def test_live_browser_capture_after_forecast_can_pass_with_pre_cutoff_source_time(self) -> None:
        result = validate_temporal_eligibility(
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "retrieval_transport": "browser",
                "retrieval_capture_for_dispatch": True,
                "captured_at": "2026-06-24T12:05:00+00:00",
                "artifact_generated_at": "2026-06-24T12:05:00+00:00",
                "source_published_at": "2026-06-24T11:55:00+00:00",
            },
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
                "live_retrieval_allowlist": ["browser"],
            },
        )

        self.assertEqual(result["temporal_gate_status"], "pass")
        self.assertEqual(result["live_retrieval_allowlist_status"], "allowed")

    def test_same_case_post_dispatch_artifact_without_live_capture_is_rejected(self) -> None:
        result = validate_temporal_eligibility(
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "retrieval_transport": "manual_fixture",
                "artifact_generated_at": "2026-06-24T12:01:00+00:00",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            {
                "case_id": "case-1",
                "dispatch_id": "dispatch-1",
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )

        self.assertEqual(result["temporal_gate_status"], "fail")
        self.assertIn("same_case_post_dispatch_artifact", result["rejection_reason_codes"])

    def test_unknown_source_time_is_unknown_not_counted_and_mtime_is_warning_only(self) -> None:
        result = validate_temporal_eligibility(
            {
                "retrieval_transport": "db",
                "filesystem_mtime": "2026-06-24T12:10:00+00:00",
            },
            {
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )

        self.assertEqual(result["temporal_gate_status"], "unknown_not_counted")
        self.assertIn("source_time_unknown", result["reason_codes"])
        self.assertIn("mtime_after_forecast_timestamp", result["warning_reason_codes"])

    def test_pre_dispatch_whitelist_allows_required_input(self) -> None:
        result = validate_temporal_eligibility(
            {
                "retrieval_transport": "db",
                "requires_pre_dispatch_whitelist": True,
                "pre_dispatch_input_ref": "artifact:evidence-packet-1",
                "artifact_generated_at": "2026-06-24T11:00:00+00:00",
                "source_published_at": "2026-06-24T10:00:00+00:00",
            },
            {
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
                "pre_dispatch_input_whitelist_refs": ["artifact:evidence-packet-1"],
            },
        )

        self.assertEqual(result["temporal_gate_status"], "pass")
        self.assertEqual(result["pre_dispatch_whitelist_status"], "whitelisted")

    def test_packet_validation_rejects_selected_evidence_claiming_pass_when_source_time_unknown(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        evidence = build_retrieval_evidence_item(
            case_id="case-1",
            dispatch_id="dispatch-1",
            leaf_id=context["leaf_id"],
            parent_branch_id=context["parent_branch_id"],
            retrieval_transport="browser",
            transport_attempt_ref="browser-attempt:1",
            temporal_gate_status="pass",
        )
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)
        packet["leaf_retrieval_results"][0]["selected_evidence"].append(evidence)

        result = validate_retrieval_packet(packet)

        self.assertFalse(result.valid)
        self.assertIn("declares pass but validator returned unknown_not_counted", "; ".join(result.errors))

    def test_native_unsupported_source_class_is_unknown_not_counted(self) -> None:
        provenance = normalize_retrieval_provenance(
            {
                "retrieval_transport": "native_gpt_research",
                "transport_attempt_ref": "native:1",
                "model_proposed_source_class": "rumor_blog",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )

        self.assertEqual(provenance["source_class"], "unknown")
        self.assertIn("unsupported_model_proposed_source_class", provenance["unknown_reason_codes"])
        self.assertFalse(provenance["counts_toward_breadth"])

    def test_classifier_accepted_source_class_records_slice_ref_and_reason_codes(self) -> None:
        provenance = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:1",
                "canonical_url": "https://news.example.com/story",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
            classifier_slice={
                "classifier_slice_id": "classifier:1",
                "proposed_source_class": "independent_secondary",
                "validator_acceptance_status": "accepted",
                "acceptance_reason_codes": ["domain_matches_reporter_registry"],
            },
        )

        self.assertEqual(provenance["source_class"], "independent_secondary")
        self.assertEqual(provenance["source_metadata_classifier_ref"], "classifier:1")
        self.assertEqual(provenance["classifier_acceptance_status"], "accepted_source_class")
        self.assertIn("domain_matches_reporter_registry", provenance["classifier_acceptance_reason_codes"])

    def test_classifier_protected_primary_without_deterministic_proof_does_not_count(self) -> None:
        provenance = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:2",
                "canonical_url": "https://news.example.com/story",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
            classifier_slice={
                "classifier_slice_id": "classifier:protected",
                "proposed_source_class": "official_or_primary",
                "protected_primary_proposed": True,
                "validator_acceptance_status": "accepted",
            },
        )

        self.assertEqual(provenance["source_class"], "unknown")
        self.assertEqual(provenance["classifier_acceptance_status"], "classifier_unsupported")
        self.assertFalse(provenance["counts_toward_breadth"])

    def test_browser_final_and_canonical_url_drive_source_identity(self) -> None:
        provenance = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:3",
                "requested_url": "https://search.example/?q=market",
                "final_url": "https://publisher.example.com/redirect?id=1",
                "canonical_url": "https://publisher.example.com/story",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )

        self.assertEqual(provenance["canonical_url"], "https://publisher.example.com/story")
        self.assertNotIn("search.example", provenance["canonical_source_id"])

    def test_source_family_syndication_mirrors_and_canonical_dedupe_are_deterministic(self) -> None:
        dispatch = {
            "forecast_timestamp": "2026-06-24T12:00:00+00:00",
            "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
        }
        wire_a = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:wire-a",
                "canonical_url": "https://publisher-a.example/wire-copy",
                "syndication_key": "wire:story-123",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        wire_b = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:wire-b",
                "canonical_url": "https://publisher-b.example/wire-copy",
                "syndication_key": "wire:story-123",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        api_a = normalize_retrieval_provenance(
            {
                "retrieval_transport": "structured_feed",
                "transport_attempt_ref": "api:a",
                "canonical_url": "https://api1.example.com/events/123",
                "mirrored_api_family_key": "event-api:123",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        api_b = normalize_retrieval_provenance(
            {
                "retrieval_transport": "structured_feed",
                "transport_attempt_ref": "api:b",
                "canonical_url": "https://api2.example.com/events/123",
                "mirrored_api_family_key": "event-api:123",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        direct = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:direct",
                "requested_url": "https://publisher.example.com/story?utm_source=search",
                "canonical_url": "https://publisher.example.com/story",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        search = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:search",
                "requested_url": "https://search.example/?q=story",
                "final_url": "https://publisher.example.com/story?utm_campaign=x",
                "canonical_url": "https://publisher.example.com/story",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        content_a = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:content-a",
                "canonical_url": "https://mirror-a.example/story",
                "content_sha256": "sha256:" + "a" * 64,
                "chunk_refs": ["retrieval-chunk:content-a"],
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )
        content_b = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser:content-b",
                "canonical_url": "https://mirror-b.example/story",
                "content_sha256": "sha256:" + "a" * 64,
                "chunk_refs": ["retrieval-chunk:content-b"],
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )

        self.assertEqual(wire_a["source_family_id"], wire_b["source_family_id"])
        self.assertEqual(wire_a["source_family_status"], "syndicated_copy")
        self.assertEqual(api_a["source_family_id"], api_b["source_family_id"])
        self.assertEqual(api_a["source_family_status"], "mirrored_api_endpoint")
        self.assertEqual(direct["source_family_id"], search["source_family_id"])
        self.assertNotEqual(content_a["source_family_id"], content_b["source_family_id"])
        self.assertEqual(
            content_a["source_metadata_resolution"]["source_family_resolution_method"],
            "registrable_domain",
        )
        self.assertEqual(
            content_b["source_metadata_resolution"]["source_family_resolution_method"],
            "registrable_domain",
        )
        self.assertEqual(content_a["content_duplicate_detection_hash"], "sha256:" + "a" * 64)

    def test_claim_family_identity_and_contradiction_family_are_deterministic(self) -> None:
        base_tuple = {
            "subject": "Example event",
            "predicate": "happened",
            "object_or_value": "yes",
            "event_time": "2026-06-24",
            "entity_or_jurisdiction": "example",
            "condition_scope": "unconditional",
            "polarity": "affirmed",
        }
        same_a = build_atomic_claim_candidate(
            evidence_ref="evidence:a",
            leaf_id="leaf:a",
            chunk_refs=["chunk:a"],
            proposed_tuple=base_tuple,
            validation_status="accepted_for_normalization",
        )
        same_b = build_atomic_claim_candidate(
            evidence_ref="evidence:b",
            leaf_id="leaf:b",
            chunk_refs=["chunk:b"],
            proposed_tuple=base_tuple,
            validation_status="accepted_for_normalization",
        )
        different = build_atomic_claim_candidate(
            evidence_ref="evidence:c",
            leaf_id="leaf:c",
            chunk_refs=["chunk:c"],
            proposed_tuple={**base_tuple, "object_or_value": "no"},
            validation_status="accepted_for_normalization",
        )
        negated = build_atomic_claim_candidate(
            evidence_ref="evidence:d",
            leaf_id="leaf:d",
            chunk_refs=["chunk:d"],
            proposed_tuple={**base_tuple, "polarity": "negated"},
            validation_status="accepted_for_normalization",
        )

        family_a = build_claim_family_resolution([same_a])
        family_b = build_claim_family_resolution([same_b])
        family_c = build_claim_family_resolution([different])
        family_d = build_claim_family_resolution([negated])

        self.assertEqual(family_a["claim_family_id"], family_b["claim_family_id"])
        self.assertNotEqual(family_a["claim_family_id"], family_c["claim_family_id"])
        self.assertNotEqual(family_a["claim_family_id"], family_d["claim_family_id"])
        self.assertEqual(family_a["contradiction_family_id"], family_d["contradiction_family_id"])

    def test_protected_primary_and_missingness_candidates_are_candidate_only(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "source_of_truth"
        leaf["research_sufficiency_requirements"]["protected_primary_required"] = True
        leaf["research_sufficiency_requirements"]["required_source_classes"] = [
            "official_or_primary",
            "independent_secondary",
        ]
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet)

        packet = attach_source_access_and_missingness(packet)

        self.assertTrue(validate_retrieval_packet(packet).valid)
        self.assertEqual(packet["schema_feature_gates"]["RET-005"], "implemented")
        self.assertEqual(len(packet["protected_primary_access_failures"]), 1)
        failure = packet["protected_primary_access_failures"][0]
        self.assertEqual(failure["access_status"], "missing")
        self.assertFalse(failure["authority_boundary"]["signed_missingness_authority"])
        missing_classes = {item["expected_source_class"] for item in packet["missingness_candidates"]}
        self.assertIn("official_or_primary", missing_classes)
        self.assertIn("independent_secondary", missing_classes)
        self.assertTrue(
            all(
                item["distinct_absence_mechanism_proof_ref"] is None
                and item["authority_boundary"]["scae_missingness_authority"] is False
                for item in packet["missingness_candidates"]
            )
        )

    def test_bounded_starvation_expansion_precedes_macro_fallback(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "source_of_truth"
        leaf["research_sufficiency_requirements"]["protected_primary_required"] = True
        leaf["research_sufficiency_requirements"]["max_targeted_expansion_attempts"] = 2
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet)

        packet = attach_retrieval_expansion_and_fallback_plan(packet, macro_fallback_requested=True)

        self.assertTrue(validate_retrieval_packet(packet).valid)
        self.assertEqual(packet["schema_feature_gates"]["RET-006"], "implemented")
        first_leaf_attempts = [
            item for item in packet["retrieval_expansion_attempts"] if item["leaf_id"] == leaf["leaf_id"]
        ]
        self.assertEqual([item["attempt_index"] for item in first_leaf_attempts], [1, 2])
        self.assertTrue(all(item["bounded_by_requirement_max"] for item in first_leaf_attempts))
        fallback = next(
            item for item in packet["retrieval_fallback_states"] if item["leaf_id"] == leaf["leaf_id"]
        )
        self.assertEqual(
            fallback["targeted_expansion_attempt_refs"],
            [item["attempt_id"] for item in first_leaf_attempts],
        )
        self.assertFalse(fallback["macro_fallback_used"])
        self.assertFalse(fallback["classification_dispatch_allowed_from_macro_fallback"])
        self.assertIn(
            "macro_fallback_not_sufficient_for_critical_or_source_of_truth",
            fallback["reason_codes"],
        )

    def test_macro_fallback_can_be_marked_discovery_only_for_noncritical_leaf(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        context = copy.deepcopy(context)
        context["purpose"] = "direct_evidence"
        context["breadth_targets"]["protected_primary_required"] = False
        context["sufficiency_requirements"]["research_priority"] = "medium"
        context["sufficiency_requirements"]["static_information_weight"] = "medium"
        context["sufficiency_requirements"]["allow_macro_fallback_for_leaf"] = True

        fallback = build_retrieval_fallback_state(
            context,
            ["retrieval-expansion-a", "retrieval-expansion-b"],
            macro_fallback_requested=True,
        )

        self.assertTrue(fallback["macro_fallback_used"])
        self.assertEqual(fallback["macro_fallback_policy"], "explicit_last_resort_discovery_only")
        self.assertEqual(fallback["macro_fallback_sufficiency_status"], "not_research_sufficiency_authority")
        self.assertFalse(fallback["authority_boundary"]["research_sufficiency_authority"])

    def test_ret_008_finalization_writes_required_leaf_certificates_and_allows_dispatch(self) -> None:
        packet = self._certifiable_packet()

        finalized = finalize_retrieval_packet_for_dispatch(packet)

        self.assertTrue(validate_retrieval_packet(finalized).valid)
        self.assertEqual(finalized["schema_feature_gates"]["RET-008"], "implemented")
        self.assertEqual(
            finalized["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )
        self.assertEqual(finalized["retrieval_outcome_state"]["retrieval_outcome"], "evidence_sufficient")
        self.assertEqual(
            finalized["retrieval_outcome_state"]["downstream_action"],
            "dispatch_researcher_classification",
        )
        self.assertTrue(finalized["research_sufficiency_summary"]["all_required_leaves_certified"])
        self.assertEqual(
            sorted(cert["leaf_id"] for cert in finalized["leaf_research_sufficiency_certificates"]),
            sorted(leaf["leaf_id"] for leaf in self.qdt["required_leaf_questions"]),
        )
        self.assertTrue(
            all(
                cert["classification_dispatch_allowed"]
                and cert["status"] == "certified_high_certainty"
                and cert["breadth_certified"]
                and cert["temporal_validation_status"] == "pass"
                for cert in finalized["leaf_research_sufficiency_certificates"]
            )
        )
        self.assertEqual(finalized["retrieval_stage_status_records"], [])
        self.assertEqual(finalized["retrieval_stage_execution_events"], [])

    def test_thin_leaf_expands_before_research_assignment(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "source_of_truth"
        leaf["leaf_temporal_role"] = "pre_resolution_forecast_driver"
        leaf["coverage_dimension"] = "key_drivers"
        leaf["research_factor"] = "thin_source_of_truth_driver_status"
        graph = qdt["research_coverage_graph"]
        graph["coverage_dimensions"] = ["key_drivers"]
        graph["research_factors"] = [
            {
                "leaf_id": leaf["leaf_id"],
                "coverage_dimension": leaf["coverage_dimension"],
                "research_factor": leaf["research_factor"],
                "leaf_temporal_role": leaf["leaf_temporal_role"],
            }
        ]
        graph["contract_guard_leaf_ids"] = []
        graph["material_question_leaf_ids"] = [leaf["leaf_id"]]
        graph["terminal_verification_leaf_ids"] = []
        graph["dispatchable_pre_resolution_leaf_ids"] = [leaf["leaf_id"]]
        graph["required_leaf_ids_by_dimension"] = {"key_drivers": [leaf["leaf_id"]]}
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary", "independent_secondary"],
                "min_independent_claim_families": 2,
                "min_independent_source_families": 2,
                "min_temporally_fresh_sources": 1,
                "protected_primary_required": True,
                "required_negative_checks": ["no_official_confirmation"],
                "max_targeted_expansion_attempts": 2,
            }
        )
        thin_packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet)

        blocked = finalize_retrieval_packet_for_dispatch(thin_packet)

        self.assertEqual(
            blocked["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertEqual(blocked["retrieval_outcome_state"]["retrieval_outcome"], "insufficient_evidence")
        self.assertEqual(
            blocked["retrieval_outcome_state"]["downstream_action"],
            "block_retrieval_until_upstream_expansion_or_unanswerability_proof",
        )
        self.assertTrue(blocked["retrieval_outcome_state"]["terminal_blocked"])
        self.assertTrue(blocked["retrieval_outcome_state"]["thin_retrieval_blocked"])
        missing_outcome = copy.deepcopy(blocked)
        missing_outcome.pop("retrieval_outcome_state", None)
        self.assertFalse(validate_retrieval_packet(missing_outcome).valid)
        self.assertFalse(
            blocked["leaf_research_sufficiency_certificates"][0]["classification_dispatch_allowed"]
        )
        self.assertIn(
            blocked["leaf_research_sufficiency_certificates"][0]["status"],
            {"blocked_insufficient_research", "blocked_stale"},
        )
        self.assertEqual(
            [attempt["attempt_index"] for attempt in blocked["retrieval_expansion_attempts"]],
            [1, 2],
        )
        self.assertEqual(
            {attempt["attempt_status"] for attempt in blocked["retrieval_expansion_attempts"]},
            {"expansion_exhausted_transport_unavailable"},
        )
        self.assertTrue(
            all(
                attempt["attempt_status"] != "planned_not_executed"
                for attempt in blocked["retrieval_expansion_attempts"]
            )
        )
        with self.assertRaisesRegex(LeafResearchAssignmentError, "blocked_insufficient_research"):
            build_leaf_research_assignments(qdt=qdt, retrieval_packet=blocked)

        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        official = self._evidence(
            context,
            attempt_ref="expanded-official",
            canonical_url="https://example.com/official/expanded",
            source_class="official_or_primary",
            source_family_id="source-family-expanded-official",
            claim_family_id="claim-family-expanded-official",
        )
        official["deterministic_source_class_proof"] = True
        official["source_class_resolution_method"] = "manual_fixture"
        secondary = self._evidence(
            context,
            attempt_ref="expanded-secondary",
            canonical_url="https://independent.example/expanded",
            source_class="independent_secondary",
            source_family_id="source-family-expanded-secondary",
            claim_family_id="claim-family-expanded-secondary",
        )
        expanded_chunks = []
        for item in (official, secondary):
            text = (
                f"Expanded certified excerpt for {item['transport_attempt_ref']} with enough bounded "
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
            expanded_chunks.append(chunk)
        expanded_packet = build_retrieval_packet(
            qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=[official, secondary],
        )
        expanded_packet["evidence_chunks"] = expanded_chunks

        certified = finalize_retrieval_packet_for_dispatch(expanded_packet)
        assignments = build_leaf_research_assignments(qdt=qdt, retrieval_packet=certified)

        self.assertEqual(
            certified["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )
        self.assertEqual(
            certified["leaf_research_sufficiency_certificates"][0]["status"],
            "certified_high_certainty",
        )
        self.assertEqual(len(assignments), 1)

    def test_unsatisfied_thin_evidence_marks_expansion_executed(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary", "independent_secondary"],
                "min_independent_claim_families": 2,
                "min_independent_source_families": 2,
                "protected_primary_required": True,
                "max_targeted_expansion_attempts": 2,
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        secondary = self._evidence(
            context,
            attempt_ref="thin-secondary",
            canonical_url="https://independent.example/thin",
            source_class="independent_secondary",
            source_family_id="source-family-thin-secondary",
            claim_family_id="claim-family-thin-secondary",
        )
        packet = build_retrieval_packet(
            qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=[secondary],
        )

        finalized = finalize_retrieval_packet_for_dispatch(packet)

        self.assertEqual(
            finalized["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertEqual(
            {attempt["attempt_status"] for attempt in finalized["retrieval_expansion_attempts"]},
            {"executed"},
        )
        self.assertTrue(
            all(
                secondary["evidence_ref"] in attempt["admitted_evidence_refs"]
                for attempt in finalized["retrieval_expansion_attempts"]
            )
        )
        self.assertEqual(
            finalized["retrieval_fallback_summary"]["targeted_expansion_executed_count"],
            2,
        )

    def test_hash_only_chunks_do_not_certify_research_sufficiency(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary", "independent_secondary"],
                "min_independent_claim_families": 2,
                "min_independent_source_families": 2,
                "min_temporally_fresh_sources": 0,
                "protected_primary_required": True,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        official = self._evidence(
            context,
            attempt_ref="hash-only-official",
            canonical_url="https://example.com/hash-only-official",
            source_class="official_or_primary",
            source_family_id="source-family-hash-official",
            claim_family_id="claim-family-hash-official",
        )
        official["deterministic_source_class_proof"] = True
        official["source_class_resolution_method"] = "manual_fixture"
        secondary = self._evidence(
            context,
            attempt_ref="hash-only-secondary",
            canonical_url="https://independent.example/hash-only-secondary",
            source_class="independent_secondary",
            source_family_id="source-family-hash-secondary",
            claim_family_id="claim-family-hash-secondary",
        )
        chunks = []
        for item in (official, secondary):
            text = "Hash-only diagnostic source text is long enough but not research usable. " * 6
            chunk = build_evidence_chunk(
                evidence_ref=item["evidence_ref"],
                content_artifact_ref=f"artifact:browser-capture/{item['transport_attempt_ref']}",
                chunk_index=0,
                char_start=0,
                char_end=len(text),
                text=text,
                excerpt_policy="hash_only",
            )
            item["chunk_refs"] = [chunk["chunk_ref"]]
            chunks.append(chunk)
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=[official, secondary])
        packet["evidence_chunks"] = chunks

        finalized = finalize_retrieval_packet_for_dispatch(packet)
        coverage = finalized["retrieval_breadth_coverage_slices"][0]
        certificate = finalized["leaf_research_sufficiency_certificates"][0]

        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "blocked_insufficient_research")
        self.assertTrue(coverage["research_usefulness_enforced"])
        self.assertEqual(coverage["diagnostic_admitted_ref_count"], 2)
        self.assertEqual(coverage["admitted_ref_count"], 0)
        self.assertFalse(certificate["evidence_refs"])
        self.assertIn("hash_only_excerpt_not_research_usable", coverage["unsatisfied_breadth_dimensions"])

    def test_short_chunks_do_not_certify_research_sufficiency(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["independent_secondary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 0,
                "protected_primary_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        secondary = self._evidence(
            context,
            attempt_ref="short-secondary",
            canonical_url="https://independent.example/short-secondary",
            source_class="independent_secondary",
            source_family_id="source-family-short-secondary",
            claim_family_id="claim-family-short-secondary",
        )
        text = "Too short for classification."
        chunk = build_evidence_chunk(
            evidence_ref=secondary["evidence_ref"],
            content_artifact_ref="artifact:browser-capture/short-secondary",
            chunk_index=0,
            char_start=0,
            char_end=len(text),
            text=text,
            excerpt_policy="bounded_excerpt",
        )
        secondary["chunk_refs"] = [chunk["chunk_ref"]]
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=[secondary])
        packet["evidence_chunks"] = [chunk]

        finalized = finalize_retrieval_packet_for_dispatch(packet)
        coverage = finalized["retrieval_breadth_coverage_slices"][0]

        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "blocked_insufficient_research")
        self.assertEqual(coverage["admitted_ref_count"], 0)
        self.assertIn("snippet_too_short_for_classification", coverage["unsatisfied_breadth_dimensions"])

    def test_claim_family_empty_evidence_blocks_claim_breadth(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["independent_secondary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 0,
                "protected_primary_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        secondary = self._evidence(
            context,
            attempt_ref="claim-empty-secondary",
            canonical_url="https://independent.example/claim-empty-secondary",
            source_class="independent_secondary",
            source_family_id="source-family-claim-empty-secondary",
            claim_family_id="",
        )
        text = "Claim-empty source has enough bounded text for classification but no extracted claim family. " * 6
        chunk = build_evidence_chunk(
            evidence_ref=secondary["evidence_ref"],
            content_artifact_ref="artifact:browser-capture/claim-empty-secondary",
            chunk_index=0,
            char_start=0,
            char_end=len(text),
            text=text,
            excerpt_policy="bounded_excerpt",
        )
        secondary["chunk_refs"] = [chunk["chunk_ref"]]
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet, selected_evidence=[secondary])
        packet["evidence_chunks"] = [chunk]

        finalized = finalize_retrieval_packet_for_dispatch(packet)
        coverage = finalized["retrieval_breadth_coverage_slices"][0]

        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "blocked_insufficient_research")
        self.assertEqual(coverage["claim_family_count"], 0)
        self.assertIn("claim_family_diversity", coverage["unsatisfied_breadth_dimensions"])
        self.assertIn("claim_extraction_not_attempted", coverage["unsatisfied_breadth_dimensions"])

    def test_transport_run_without_admissible_evidence_exhausts_expansion(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"]["max_targeted_expansion_attempts"] = 2
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        omitted = build_retrieval_candidate_record(
            leaf_id=context["leaf_id"],
            query_context_ref=context["query_context_ref"],
            query_variant_id=variant["query_variant_id"],
            retrieval_transport="browser",
            transport_attempt_ref="browser-attempt-empty-content",
            candidate_status="rejected",
            requested_url="https://independent.example/empty",
            canonical_url="https://independent.example/empty",
            omission_reason_codes=["retrieved_source_text_missing"],
        )
        packet = build_retrieval_packet(
            qdt,
            evidence_packet=self.evidence_packet,
            omitted_candidates=[omitted],
        )

        finalized = finalize_retrieval_packet_for_dispatch(packet)

        self.assertEqual(
            {attempt["attempt_status"] for attempt in finalized["retrieval_expansion_attempts"]},
            {"expansion_exhausted_no_admissible_candidates"},
        )
        self.assertTrue(
            all(
                omitted["candidate_id"] in attempt["candidate_refs"]
                for attempt in finalized["retrieval_expansion_attempts"]
            )
        )
        self.assertEqual(
            finalized["retrieval_fallback_summary"]["targeted_expansion_no_admissible_candidate_count"],
            2,
        )
        self.assertTrue(
            all(
                attempt["attempt_status"] != "planned_not_executed"
                for attempt in finalized["retrieval_expansion_attempts"]
            )
        )

    def test_browser_only_cutover_uses_direct_urls_and_yields_assignments(self) -> None:
        contexts = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)
        selected = []
        browser_attempts = []
        chunks = []
        spans = []
        attempt_refs_by_leaf = {}

        for index, context in enumerate(contexts):
            direct_candidates = context["direct_url_candidates"]
            direct = next(
                item for item in direct_candidates if "official_source_hints" in item["source_ref"]
            )
            self.assertEqual(direct["direct_url_priority"], "official_or_resolution_urls_first")
            variant = context["query_variants"][0]
            direct_attempt = build_browser_retrieval_attempt(
                context,
                variant,
                navigation_mode="direct_url",
                requested_url=direct["url"],
                final_url=direct["url"],
                canonical_url=direct["url"],
                extraction_status="accepted",
                result_rank=1,
            )
            search_attempt = build_browser_retrieval_attempt(
                context,
                variant,
                navigation_mode="web_search",
                requested_url=f"https://search.example/?q={context['leaf_id']}",
                final_url=f"https://independent.example/{context['leaf_id']}",
                canonical_url=f"https://independent.example/{context['leaf_id']}",
                extraction_status="accepted",
                result_rank=2,
            )
            browser_attempts.extend([direct_attempt, search_attempt])
            attempt_refs_by_leaf[context["leaf_id"]] = [
                direct_attempt["attempt_id"],
                search_attempt["attempt_id"],
            ]
            expert_attempt = None
            if self._context_requires_source_class(context, "expert_or_specialist"):
                expert_attempt = build_browser_retrieval_attempt(
                    context,
                    variant,
                    navigation_mode="web_search",
                    requested_url=f"https://search.example/?q={context['leaf_id']}+specialist",
                    final_url=f"https://gartner.com/{context['leaf_id']}",
                    canonical_url=f"https://gartner.com/{context['leaf_id']}",
                    extraction_status="accepted",
                    result_rank=3,
                )
                browser_attempts.append(expert_attempt)
                attempt_refs_by_leaf[context["leaf_id"]].append(expert_attempt["attempt_id"])

            official = self._evidence(
                context,
                attempt_ref=direct_attempt["attempt_id"],
                canonical_url=direct["url"],
                source_class="official_or_primary",
                source_family_id=f"source-family-{context['leaf_id']}-official",
                claim_family_id=f"claim-family-{context['leaf_id']}-official",
            )
            official["deterministic_source_class_proof"] = True
            official["source_class_resolution_method"] = "manual_fixture"
            secondary = self._evidence(
                context,
                attempt_ref=search_attempt["attempt_id"],
                canonical_url=f"https://independent.example/{context['leaf_id']}",
                source_class="independent_secondary",
                source_family_id=f"source-family-{context['leaf_id']}-secondary",
                claim_family_id=f"claim-family-{context['leaf_id']}-secondary",
            )
            evidence_items = [official, secondary]
            if expert_attempt is not None:
                expert = self._evidence(
                    context,
                    attempt_ref=expert_attempt["attempt_id"],
                    canonical_url=f"https://gartner.com/{context['leaf_id']}",
                    source_class="expert_or_specialist",
                    source_family_id=f"source-family-{context['leaf_id']}-specialist",
                    claim_family_id=f"claim-family-{context['leaf_id']}-specialist",
                )
                expert["deterministic_source_class_proof"] = True
                expert["source_class_resolution_method"] = "manual_fixture"
                evidence_items.append(expert)
            for offset, evidence in enumerate(evidence_items):
                text = (
                    f"Bounded browser evidence for {context['leaf_id']} {offset} with enough source "
                    "detail for researcher classification and certified snippet assignment. "
                    * 8
                )
                chunk = build_evidence_chunk(
                    evidence_ref=evidence["evidence_ref"],
                    content_artifact_ref=f"artifact:browser-capture/{index}-{offset}",
                    chunk_index=0,
                    char_start=0,
                    char_end=len(text),
                    text=text,
                    excerpt_policy="bounded_excerpt",
                )
                span = build_evidence_span(
                    chunk_ref=chunk["chunk_ref"],
                    char_start=0,
                    char_end=16,
                    text="Bounded browser",
                )
                evidence["chunk_refs"] = [chunk["chunk_ref"]]
                chunks.append(chunk)
                spans.append(span)
            selected.extend(evidence_items)

        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_retrieval_allowlist=["browser"],
        )
        packet["browser_retrieval_attempts"] = browser_attempts
        packet["evidence_chunks"] = chunks
        packet["evidence_spans"] = spans
        for result in packet["leaf_retrieval_results"]:
            result["browser_retrieval_attempt_refs"] = attempt_refs_by_leaf[result["leaf_id"]]

        finalized = finalize_retrieval_packet_for_dispatch(packet)
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=finalized)

        diagnostic = finalized["browser_search_provider_diagnostics"][0]
        self.assertEqual(diagnostic["provider_id"], "openclaw_web_fetch_browser")
        self.assertFalse(diagnostic["news_feed_api_enabled"])
        self.assertEqual(diagnostic["direct_url_priority"], "official_or_resolution_urls_first")
        self.assertIn("direct_url", diagnostic["capabilities"])
        self.assertIn("web_search", diagnostic["capabilities"])
        self.assertTrue(
            all(attempt["news_feed_api_enabled"] is False for attempt in finalized["browser_retrieval_attempts"])
        )
        self.assertEqual(
            [attempt["navigation_mode"] for attempt in finalized["browser_retrieval_attempts"][:2]],
            ["direct_url", "web_search"],
        )
        self.assertTrue(
            all(item["retrieval_transport"] == "browser" for item in finalized["retrieval_evidence_provenance_slices"])
        )
        transports = [
            item["retrieval_transport"]
            for item in finalized["retrieval_evidence_provenance_slices"]
        ]
        self.assertNotIn("structured_feed", transports)
        self.assertTrue(all(result["evidence_chunk_refs"] for result in finalized["leaf_retrieval_results"]))
        self.assertTrue(
            all(
                resolution["accepted_metadata_authority"] == "deterministic_source_metadata_resolver"
                and resolution["counts_toward_breadth"]
                for resolution in finalized["source_metadata_resolutions"]
            )
        )
        self.assertTrue(finalized["leaf_research_sufficiency_certificates"])
        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        self.assertEqual(len(assignments), len(self.qdt["required_leaf_questions"]))
        self.assertTrue(all(assignment["assigned_evidence_refs"] for assignment in assignments))

    def test_phase3_live_fixture_without_direct_sources_blocks_before_classification(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidates = self._live_candidates_for_context(context, include_direct=False, count=5)
        search_candidates = self._search_candidates_for_context(context, candidates)

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=candidates,
            search_candidate_urls=search_candidates,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertFalse(packet["leaf_evidence_dockets"][0]["proceed_to_classification"])
        self.assertIn(
            "protected_primary_missing",
            packet["leaf_research_sufficiency_certificates"][0]["unsatisfied_requirement_codes"],
        )

    def test_phase3_live_fixture_with_sufficient_direct_evidence_dispatches_admitted_refs(self) -> None:
        contexts = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)
        candidates = [
            candidate
            for context in contexts
            for candidate in self._live_candidates_for_context(context, include_direct=True, count=5)
        ]
        search_candidates = [
            search_candidate
            for context in contexts
            for search_candidate in self._search_candidates_for_context(
                context,
                [candidate for candidate in candidates if candidate["leaf_id"] == context["leaf_id"]],
            )
        ]

        packet = build_live_retrieval_packet_from_candidates(
            self.qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=candidates,
            search_candidate_urls=search_candidates,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            runtime_mode="live_fixture_candidate_retrieval_runtime",
        )
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)

        self.assertEqual(packet["retrieval_runtime_summary"]["runtime_mode"], "live_fixture_candidate_retrieval_runtime")
        self.assertGreater(packet["retrieval_runtime_summary"]["direct_url_attempt_count"], 0)
        self.assertEqual(packet["retrieval_runtime_summary"]["search_candidate_url_count"], len(search_candidates))
        self.assertEqual(packet["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        self.assertTrue(packet["leaf_evidence_dockets"])
        self.assertTrue(all(docket["admitted_evidence_refs"] for docket in packet["leaf_evidence_dockets"]))
        self.assertTrue(all(result["browser_retrieval_attempt_refs"] for result in packet["leaf_retrieval_results"]))
        self.assertTrue(all(result["evidence_chunk_refs"] for result in packet["leaf_retrieval_results"]))
        self.assertEqual(len(assignments), len(self.qdt["required_leaf_questions"]))
        self.assertTrue(all(assignment["assigned_evidence_refs"] for assignment in assignments))

    def test_direct_live_candidate_observed_before_cutoff_counts_without_published_time(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        candidate.pop("source_published_at", None)
        candidate["source_observed_at"] = "2026-06-24T11:30:00+00:00"

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]
        resolution = provenance["source_metadata_resolution"]

        self.assertEqual(provenance["temporal_gate_status"], "pass")
        self.assertTrue(provenance["counts_toward_breadth"])
        self.assertIsNone(resolution["published_at"])
        self.assertEqual(resolution["temporal_safety_status"], "pass")
        self.assertTrue(packet["leaf_evidence_dockets"][0]["admitted_evidence_refs"])

    def test_observed_time_does_not_satisfy_freshness_requirement(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "direct_evidence"
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "protected_primary_required": False,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        candidate.pop("source_published_at", None)
        candidate.pop("source_updated_at", None)
        candidate["source_observed_at"] = "2026-06-24T11:30:00+00:00"

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        coverage = packet["retrieval_breadth_coverage_slices"][0]

        self.assertEqual(coverage["fresh_source_count"], 0)
        self.assertIn("freshness", coverage["unsatisfied_breadth_dimensions"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_stable_boi_schedule_identity_satisfies_freshness_without_published_time(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "resolution_mechanics"
        leaf["leaf_temporal_role"] = "resolution_mechanics"
        leaf["question_text"] = "What is the Bank of Israel published decision schedule and rules?"
        leaf["required_evidence_fields"] = ["official_decision_schedule", "rules_text"]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "protected_primary_required": True,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        boi_url = "https://boi.org.il/en/markets/schedule"
        candidate.update(
            {
                "requested_url": boi_url,
                "final_url": boi_url,
                "canonical_url": boi_url,
                "source_observed_at": "2026-06-24T11:30:00+00:00",
            }
        )
        candidate.pop("source_published_at", None)
        candidate.pop("source_updated_at", None)

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_policy_overlay=False,
        )
        coverage = packet["retrieval_breadth_coverage_slices"][0]
        provenance = packet["retrieval_evidence_provenance_slices"][0]

        self.assertEqual(coverage["freshness_policy"], "stable_source_identity")
        self.assertEqual(coverage["fresh_source_count"], 1)
        self.assertNotIn("freshness", coverage["unsatisfied_breadth_dimensions"])
        self.assertEqual(provenance["source_family_id"], "source-family:bank_of_israel")
        self.assertEqual(
            provenance["source_metadata_resolution"]["source_family_resolution_method"],
            "bank_of_israel_official_domain_path",
        )
        self.assertIsNone(provenance["source_metadata_resolution"]["published_at"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )

    def test_current_boi_status_still_requires_publication_or_update_freshness(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "direct_evidence"
        leaf["leaf_temporal_role"] = "current_status"
        leaf["question_text"] = "What is the current Bank of Israel guidance and inflation status?"
        leaf["required_evidence_fields"] = ["current_guidance", "inflation_status"]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "protected_primary_required": True,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        boi_url = "https://boi.org.il/en/communication-and-publications"
        candidate.update(
            {
                "requested_url": boi_url,
                "final_url": boi_url,
                "canonical_url": boi_url,
                "source_observed_at": "2026-06-24T11:30:00+00:00",
            }
        )
        candidate.pop("source_published_at", None)
        candidate.pop("source_updated_at", None)

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_policy_overlay=False,
        )
        coverage = packet["retrieval_breadth_coverage_slices"][0]

        self.assertEqual(coverage["freshness_policy"], "publication_or_update")
        self.assertEqual(coverage["fresh_source_count"], 0)
        self.assertIn("freshness", coverage["unsatisfied_breadth_dimensions"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_boi_schedule_page_is_context_only_for_current_driver_leaf(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "direct_evidence"
        leaf["leaf_temporal_role"] = "current_status"
        leaf["question_text"] = "What is the current Bank of Israel inflation guidance?"
        leaf["required_evidence_fields"] = ["inflation_status", "current_guidance"]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "protected_primary_required": True,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        boi_url = "https://boi.org.il/en/markets/schedule"
        candidate.update(
            {
                "requested_url": boi_url,
                "final_url": boi_url,
                "canonical_url": boi_url,
                "source_class_resolution_method": "bank_of_israel_official_domain_path",
                "source_class_registry_match": "boi.org.il",
            }
        )

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_policy_overlay=False,
        )
        coverage = packet["retrieval_breadth_coverage_slices"][0]
        provenance = packet["retrieval_evidence_provenance_slices"][0]

        self.assertEqual(provenance["source_family_id"], "source-family:bank_of_israel")
        self.assertFalse(provenance["counts_toward_breadth"])
        self.assertIn(
            "boi_schedule_context_only_not_counted_for_driver_leaf",
            provenance["unknown_reason_codes"],
        )
        self.assertEqual(coverage["admitted_ref_count"], 0)
        self.assertEqual(coverage["protected_primary_status"], "blocked")
        self.assertIn(
            "boi_schedule_context_only_not_counted_for_driver_leaf",
            coverage["unsatisfied_breadth_dimensions"],
        )
        self.assertIn("protected_primary_blocked", coverage["unsatisfied_breadth_dimensions"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_live_candidate_without_validated_claim_family_does_not_count_toward_breadth(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        candidate.pop("claim_family_id", None)
        candidate.pop("claim_family_ids", None)
        candidate.pop("claim_family_resolution_ref", None)
        candidate.pop("claim_family_resolution_refs", None)
        candidate.pop("validated_atomic_claim_candidates", None)

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]
        cert = packet["leaf_research_sufficiency_certificates"][0]

        self.assertEqual(provenance["claim_family_ids"], [])
        self.assertIn("claim_family_unknown_not_counted", provenance["unknown_reason_codes"])
        self.assertFalse(provenance["counts_toward_breadth"])
        self.assertEqual(packet["research_sufficiency_summary"]["classification_dispatch_status"], "blocked_insufficient_research")
        self.assertIn("claim_family_diversity", cert["unsatisfied_requirement_codes"])

    def test_official_fetched_statement_creates_claim_family_from_supported_span(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "resolution_mechanics"
        leaf["leaf_temporal_role"] = "resolution_mechanics"
        leaf["question_text"] = "What schedule did the Bank of Israel publish?"
        leaf["required_evidence_fields"] = ["official_decision_schedule", "rules_text"]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary"],
                "min_independent_claim_families": 1,
                "min_independent_source_families": 1,
                "min_temporally_fresh_sources": 1,
                "recency_window_seconds": 3600,
                "protected_primary_required": True,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        statement = (
            "The Bank of Israel published the official decision schedule and deadline for "
            "the relevant monetary policy announcement."
        )
        candidate.update(
            {
                "requested_url": "https://boi.org.il/en/markets/schedule",
                "final_url": "https://boi.org.il/en/markets/schedule",
                "canonical_url": "https://boi.org.il/en/markets/schedule",
                "source_class_resolution_method": "bank_of_israel_official_domain_path",
                "content": statement + " Additional bounded official schedule context for researchers. " * 6,
            }
        )
        candidate.pop("validated_atomic_claim_candidates", None)
        candidate.pop("claim_family_id", None)
        candidate.pop("claim_family_ids", None)
        candidate.pop("claim_family_resolution_ref", None)
        candidate.pop("claim_family_resolution_refs", None)

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
            live_policy_overlay=False,
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]
        claim = packet["atomic_claim_candidates"][0]

        self.assertEqual(claim["validation_status"], "accepted_for_normalization")
        self.assertEqual(claim["supporting_span_refs"], [packet["evidence_chunks"][0]["chunk_ref"]])
        self.assertTrue(provenance["claim_family_ids"])
        self.assertNotIn("claim_family_unknown_not_counted", provenance["unknown_reason_codes"])

    def test_tesla_delivery_claim_families_are_extracted_from_exact_fetched_text(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidate = self._live_candidate(context, 0, direct=True, official=True)
        candidate["requested_url"] = "https://ir.tesla.com/press"
        candidate["final_url"] = "https://ir.tesla.com/press"
        candidate["canonical_url"] = "https://ir.tesla.com/press"
        candidate["content"] = (
            "Tesla Q2 2025 Vehicle Production & Deliveries. "
            "In Q2 2025, Tesla produced approximately 410,244 vehicles and delivered approximately 384,122 vehicles. "
            + "Additional bounded source detail supports researcher classification without exposing unbounded page text. " * 4
        )
        candidate.pop("claim_family_id", None)
        candidate.pop("claim_family_ids", None)
        candidate.pop("claim_family_resolution_ref", None)
        candidate.pop("claim_family_resolution_refs", None)
        candidate.pop("validated_atomic_claim_candidates", None)

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]
        methods = {item["extraction_method"] for item in packet["atomic_claim_candidates"]}

        self.assertEqual(len(packet["atomic_claim_candidates"]), 2)
        self.assertEqual(len(packet["claim_family_resolutions"]), 2)
        self.assertEqual(len(provenance["claim_family_ids"]), 2)
        self.assertEqual(methods, {"fetched_text_validated_tuple"})
        self.assertEqual(packet["retrieval_breadth_coverage_slices"][0]["claim_family_count"], 2)
        self.assertNotIn(
            "claim_family_unknown_not_counted",
            provenance["unknown_reason_codes"],
        )
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )

    def test_search_snippet_tesla_delivery_text_does_not_create_claim_family(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        search_candidate = build_search_candidate_url(
            context,
            variant,
            rank=1,
            url="https://www.reuters.com/world/tesla-deliveries",
            title="Tesla delivery report",
            snippet="In Q2 2025, Tesla produced approximately 410,244 vehicles and delivered approximately 384,122 vehicles.",
            searched_at="2026-06-24T11:59:00+00:00",
            result_source="openclaw_oauth_web_search",
        )
        fetched_candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "web_search",
            "requested_url": "https://www.reuters.com/world/tesla-deliveries",
            "final_url": "https://www.reuters.com/world/tesla-deliveries",
            "canonical_url": "https://www.reuters.com/world/tesla-deliveries",
            "search_candidate_url_ref": search_candidate["search_candidate_url_id"],
            "source_published_at": "2026-06-24T11:30:00+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "extraction_status": "accepted",
            "admission_status": "admitted",
            "content": "Fetched page text mentions Tesla but does not include delivery or production counts.",
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[fetched_candidate],
            search_candidate_urls=[search_candidate],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]

        self.assertEqual(packet["atomic_claim_candidates"], [])
        self.assertEqual(provenance["claim_family_ids"], [])
        self.assertIn("claim_family_unknown_not_counted", provenance["unknown_reason_codes"])
        self.assertIn("snippet_sha256", packet["search_candidate_urls"][0])
        self.assertNotIn("snippet", packet["search_candidate_urls"][0])

    def test_fetched_url_resolver_metadata_can_satisfy_breadth_and_freshness(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "resolution_mechanics"
        leaf["research_priority"] = "medium"
        leaf["priority_reason_codes"] = ["test_resolution_mechanics_medium_priority"]
        leaf["research_sufficiency_requirements"].update(
            {
                "required_source_classes": ["official_or_primary", "independent_secondary"],
                "leaf_purpose": "resolution_mechanics",
                "research_priority": "medium",
                "retrieval_breadth_profile_ref": "breadth-profile-template:resolution_mechanics:medium:unconditional",
                "protected_primary_required": False,
                "min_independent_claim_families": 2,
                "min_independent_source_families": 2,
                "min_temporally_fresh_sources": 2,
                "recency_window_seconds": 3600,
                "contradiction_search_required": False,
                "required_negative_checks": [],
            }
        )
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        official = self._live_candidate(context, 0, direct=True, official=True)
        official["source_class_resolution_method"] = "unknown"
        official["deterministic_source_class_proof"] = False
        secondary = self._live_candidate(context, 1)
        search_candidates = self._search_candidates_for_context(context, [secondary])
        evidence_packet = {
            **self.evidence_packet,
            "official_source_hints": [official["canonical_url"]],
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=evidence_packet,
            fetched_candidates=[official, secondary],
            search_candidate_urls=search_candidates,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        coverage = packet["retrieval_breadth_coverage_slices"][0]

        self.assertTrue(coverage["breadth_certified"], coverage["unsatisfied_breadth_dimensions"])
        self.assertEqual(coverage["claim_family_count"], 2)
        self.assertEqual(coverage["source_family_count"], 2)
        self.assertEqual(coverage["fresh_source_count"], 2)
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )
        self.assertTrue(packet["atomic_claim_candidates"])
        self.assertTrue(packet["claim_family_resolutions"])
        self.assertIn(
            "official_url_hint",
            {
                item["source_metadata_resolution"]["source_class_resolution_method"]
                for item in packet["retrieval_evidence_provenance_slices"]
            },
        )
        self.assertTrue(
            all(
                item["source_metadata_resolution"]["source_family_resolution_method"]
                in {"registrable_domain", "deterministic_candidate_source_metadata"}
                for item in packet["retrieval_evidence_provenance_slices"]
            )
        )

    def test_provider_authority_fields_without_resolver_metadata_do_not_count(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        search_candidate = build_search_candidate_url(
            context,
            variant,
            rank=1,
            url="https://source.example/search-discovered",
            title="Provider title",
            snippet="Provider summary",
            searched_at="2026-06-24T11:59:00+00:00",
            result_source="openclaw_oauth_web_search",
        )
        fetched_candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "web_search",
            "requested_url": "https://source.example/search-discovered",
            "final_url": "https://source.example/search-discovered",
            "canonical_url": "https://source.example/search-discovered",
            "search_candidate_url_ref": search_candidate["search_candidate_url_id"],
            "source_class": "independent_secondary",
            "source_family_id": "source-family-provider-supplied",
            "claim_family_id": "claim-family-provider-supplied",
            "source_published_at": "2026-06-24T11:30:00+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "extraction_status": "accepted",
            "admission_status": "admitted",
            "content": "Fetched page text exists, but provider metadata is not resolver metadata.",
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[fetched_candidate],
            search_candidate_urls=[search_candidate],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]

        self.assertEqual(provenance["source_class"], "unknown")
        self.assertEqual(provenance["claim_family_ids"], [])
        self.assertNotEqual(provenance["source_family_id"], "source-family-provider-supplied")
        self.assertFalse(provenance["counts_toward_breadth"])
        self.assertIn("source_class_unknown", provenance["unknown_reason_codes"])
        self.assertIn("claim_family_unknown_not_counted", provenance["unknown_reason_codes"])

    def test_claim_family_for_fetched_url_comes_from_validated_text_not_url(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        first = self._live_candidate(context, 0, direct=True, official=True)
        second = self._live_candidate(context, 1)
        second["validated_atomic_claim_candidates"][0]["subject"] = first["validated_atomic_claim_candidates"][0]["subject"]
        second["validated_atomic_claim_candidates"][0]["predicate"] = first["validated_atomic_claim_candidates"][0]["predicate"]
        second["validated_atomic_claim_candidates"][0]["object_or_value"] = first["validated_atomic_claim_candidates"][0]["object_or_value"]
        second["validated_atomic_claim_candidates"][0]["event_time"] = first["validated_atomic_claim_candidates"][0]["event_time"]
        second["validated_atomic_claim_candidates"][0]["entity_or_jurisdiction"] = first["validated_atomic_claim_candidates"][0]["entity_or_jurisdiction"]
        third = self._live_candidate(context, 2)
        third["canonical_url"] = "https://independent1.example/different-url"
        third["requested_url"] = third["canonical_url"]
        third["final_url"] = third["canonical_url"]
        third["content"] = "This fetched page has no matching support text for its proposed claim."
        search_candidates = self._search_candidates_for_context(context, [second, third])

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[first, second, third],
            search_candidate_urls=search_candidates,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        first_claims = [
            item["claim_family_ids"]
            for item in packet["retrieval_evidence_provenance_slices"]
            if item["canonical_url"] in {first["canonical_url"], second["canonical_url"]}
        ]
        unsupported = next(
            item
            for item in packet["retrieval_evidence_provenance_slices"]
            if item["canonical_url"] == third["canonical_url"]
        )

        self.assertEqual(first_claims[0], first_claims[1])
        self.assertNotEqual(first["canonical_url"], second["canonical_url"])
        self.assertEqual(unsupported["claim_family_ids"], [])
        self.assertIn("claim_family_unknown_not_counted", unsupported["unknown_reason_codes"])

    def test_tesla_delivery_claim_family_can_use_later_fetched_text_span(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        content = (
            "Skip to main content Tesla homepage Investor Relations "
            + ("Q2 2026 Delivery Consensus details. " * 30)
            + "Continue Reading Tesla First Quarter 2026 Production, Deliveries & Deployments "
            "BUSINESS WIRE Apr 2, 2026 AUSTIN, Texas, April 2, 2026 - In the first quarter, "
            "we produced over 408,000 vehicles, delivered over 358,000 vehicles and deployed "
            "8.8 GWh of energy storage products."
        )
        self.assertGreater(content.find("produced over 408,000 vehicles"), 1200)
        candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "direct_url",
            "requested_url": "https://ir.tesla.com/press",
            "final_url": "https://ir.tesla.com/press",
            "canonical_url": "https://ir.tesla.com/press",
            "source_class": "official_or_primary",
            "source_published_at": "2026-04-02T12:00:00+00:00",
            "source_observed_at": "2026-06-24T11:58:59+00:00",
            "captured_at": "2026-06-24T11:58:59+00:00",
            "deterministic_source_class_proof": True,
            "source_class_resolution_method": "deterministic_url_registry",
            "temporal_gate_status": "pass",
            "admission_status": "admitted",
            "extraction_status": "accepted",
            "result_rank": 1,
            "content": content,
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[candidate],
            search_candidate_urls=[],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        provenance = packet["retrieval_evidence_provenance_slices"][0]
        chunk = packet["evidence_chunks"][0]

        self.assertTrue(provenance["claim_family_ids"])
        self.assertNotIn("claim_family_unknown_not_counted", provenance["unknown_reason_codes"])
        self.assertGreater(chunk["excerpt_char_count"], 1200)
        self.assertEqual(chunk["excerpt_policy"], "bounded_excerpt")
        self.assertNotIn("text", chunk)

    def test_phase7_direct_url_priority_search_candidate_caps_and_dedupe(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        candidates = self._live_candidates_for_context(context, include_direct=True, count=5)
        duplicate = copy.deepcopy(candidates[-1])
        duplicate["result_rank"] = 6
        candidates.append(duplicate)
        search_candidates = self._search_candidates_for_context(context, candidates)
        rank_over_cap = {
            "leaf_id": context["leaf_id"],
            "query_variant_id": context["query_variants"][0]["query_variant_id"],
            "query_role": "primary_leaf_retrieval",
            "rank": 11,
            "url": "https://outside-cap.example/result",
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=candidates,
            search_candidate_urls=[*search_candidates, rank_over_cap],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        self.assertEqual(packet["browser_retrieval_attempts"][0]["navigation_mode"], "direct_url")
        self.assertTrue(packet["browser_retrieval_attempts"][0]["search_candidate_url_ref"] is None)
        self.assertTrue(
            all(
                attempt["search_candidate_url_ref"]
                for attempt in packet["browser_retrieval_attempts"]
                if attempt["navigation_mode"] == "web_search"
            )
        )
        self.assertEqual(packet["retrieval_runtime_summary"]["search_candidate_omission_count"], 2)
        self.assertEqual(packet["retrieval_runtime_summary"]["duplicate_canonical_url_omissions"], 1)
        self.assertEqual(
            packet["retrieval_runtime_summary"]["search_candidate_discovery_status"],
            "executed_with_candidates",
        )
        duplicate_omissions = [
            item
            for item in packet["search_candidate_url_omissions"]
            if "duplicate_search_candidate_url" in item.get("omission_reason_codes", [])
        ]
        self.assertEqual(len(duplicate_omissions), 1)
        duplicate_omission = duplicate_omissions[0]
        self.assertEqual(duplicate_omission["leaf_id"], context["leaf_id"])
        self.assertEqual(
            duplicate_omission["query_variant_id"],
            context["query_variants"][0]["query_variant_id"],
        )
        self.assertTrue(duplicate_omission["canonical_url"])
        self.assertIn(
            duplicate_omission["duplicate_of_search_candidate_url_ref"],
            {item["search_candidate_url_id"] for item in packet["search_candidate_urls"]},
        )
        self.assertTrue(packet["retrieval_runtime_summary"]["web_fetch_is_url_fetch_not_search"])
        with self.assertRaisesRegex(RetrievalPacketError, "exceeds cap"):
            build_search_candidate_url(
                context,
                context["query_variants"][0],
                rank=11,
                url="https://outside-cap.example/result",
            )

    def test_phase7_web_fetch_adapter_does_not_act_as_search(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        adapter = BrowserProviderAdapter(
            search_provider=lambda _context, _variant: [
                {"rank": 1, "url": "https://search.example/result", "title": "Search result"}
            ],
            web_fetch=lambda url: {"final_url": url, "extraction_status": "accepted"},
        )

        records = adapter.search_candidate_urls(context, context["query_variants"][0])
        fetched = adapter.fetch_url("https://search.example/result")

        self.assertEqual(records[0]["schema_version"], "search-candidate-url/v1")
        self.assertFalse(records[0]["web_fetch_used_for_search"])
        self.assertTrue(records[0]["fetch_required_before_admission"])
        self.assertEqual(fetched["web_fetch_role"], "url_fetch_extraction_only")

        fetch_calls: list[str] = []
        fetch_only_adapter = BrowserProviderAdapter(
            web_fetch=lambda url: fetch_calls.append(url) or {"final_url": url, "extraction_status": "accepted"},
        )

        self.assertEqual(fetch_only_adapter.search_candidate_urls(context, context["query_variants"][0]), [])
        self.assertEqual(fetch_calls, [])

    def test_phase7_search_summary_without_fetched_text_is_not_admitted_as_evidence(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        search_candidate = build_search_candidate_url(
            context,
            variant,
            rank=1,
            url="https://source.example/search-discovered",
            title="Search-discovered source",
            snippet="Search summary only, not retrieved page text.",
            searched_at="2026-06-24T11:59:00+00:00",
            result_source="openclaw_oauth_web_search",
        )
        fetched_candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "web_search",
            "requested_url": "https://source.example/search-discovered",
            "final_url": "https://source.example/search-discovered",
            "canonical_url": "https://source.example/search-discovered",
            "search_candidate_url_ref": search_candidate["search_candidate_url_id"],
            "source_class": "official_or_primary",
            "source_published_at": "2026-06-24T11:30:00+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "extraction_status": "accepted",
            "admission_status": "admitted",
            "temporal_gate_status": "pass",
            "snippet": "Search summary only, not retrieved page text.",
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[fetched_candidate],
            search_candidate_urls=[search_candidate],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        self.assertEqual(packet["retrieval_runtime_summary"]["search_candidate_url_count"], 1)
        self.assertEqual(packet["retrieval_runtime_summary"]["admitted_initial_evidence_count"], 0)
        self.assertFalse(packet["leaf_retrieval_results"][0]["selected_evidence"])
        self.assertFalse(packet["evidence_chunks"])
        self.assertIn(
            "retrieved_source_text_missing",
            packet["omitted_candidates"][0]["omission_reason_codes"],
        )

    def test_post_cutoff_live_fetched_candidate_is_omitted_before_evidence_materialization(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        variant = context["query_variants"][0]
        url = "https://source.example/post-cutoff"
        search_candidate = build_search_candidate_url(
            context,
            variant,
            rank=1,
            url=url,
            title="Post-cutoff source",
            snippet="Search result text is not evidence.",
            searched_at="2026-06-24T11:59:00+00:00",
            result_source="openclaw_oauth_web_search",
        )
        fetched_candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "web_search",
            "requested_url": url,
            "final_url": url,
            "canonical_url": url,
            "search_candidate_url_ref": search_candidate["search_candidate_url_id"],
            "source_class": "independent_secondary",
            "source_family_id": "source-family-post-cutoff",
            "claim_family_id": "claim-family-post-cutoff",
            "source_published_at": "2026-06-24T12:00:01+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "extraction_status": "accepted",
            "admission_status": "admitted",
            "temporal_gate_status": "pass",
            "deterministic_source_class_proof": True,
            "source_class_resolution_method": "deterministic_url_registry",
            "content": "URL-specific fetched text from https://source.example/post-cutoff.",
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[fetched_candidate],
            search_candidate_urls=[search_candidate],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        omitted = packet["omitted_candidates"][0]

        self.assertEqual(packet["retrieval_runtime_summary"]["admitted_initial_evidence_count"], 0)
        self.assertFalse(packet["leaf_retrieval_results"][0]["selected_evidence"])
        self.assertFalse(packet["evidence_chunks"])
        self.assertFalse(packet["evidence_spans"])
        self.assertFalse(packet["retrieval_evidence_provenance_slices"])
        self.assertEqual(omitted["candidate_status"], "rejected")
        self.assertEqual(omitted["temporal_gate_status"], "fail")
        self.assertIn("temporal_validation_failed", omitted["omission_reason_codes"])
        self.assertIn("source_after_cutoff", omitted["omission_reason_codes"])
        self.assertTrue(validate_retrieval_packet(packet).valid)

    def test_admission_rejected_candidate_preserves_specific_omission_reasons(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        url = "https://source.example/rejected-specific"
        fetched_candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "direct_url",
            "requested_url": url,
            "final_url": url,
            "canonical_url": url,
            "source_published_at": "2026-06-24T11:30:00+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "extraction_status": "blocked",
            "admission_status": "rejected",
            "temporal_gate_status": "unknown_not_counted",
            "omission_reason_codes": ["malformed_url"],
            "reason_codes": ["protected_primary_blocked"],
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[fetched_candidate],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        omitted = packet["omitted_candidates"][0]

        self.assertEqual(omitted["candidate_status"], "rejected")
        self.assertEqual(omitted["temporal_gate_status"], "unknown_not_counted")
        self.assertIn("malformed_url", omitted["omission_reason_codes"])
        self.assertIn("protected_primary_blocked", omitted["omission_reason_codes"])
        self.assertNotEqual(omitted["omission_reason_codes"], ["admission_rejected"])
        self.assertTrue(validate_retrieval_packet(packet).valid)

    def test_phase7_whitespace_only_fetched_text_is_not_admitted_as_evidence(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        fetched_candidate = {
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "navigation_mode": "direct_url",
            "requested_url": "https://example.com/official/empty",
            "final_url": "https://example.com/official/empty",
            "canonical_url": "https://example.com/official/empty",
            "source_class": "official_or_primary",
            "source_published_at": "2026-06-24T11:30:00+00:00",
            "captured_at": "2026-06-24T11:59:00+00:00",
            "extraction_status": "accepted",
            "admission_status": "admitted",
            "temporal_gate_status": "pass",
            "content": " \n\t ",
            "extracted_text": "\n ",
            "rendered_text": "\t",
            "markdown": "   ",
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=[fetched_candidate],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        self.assertEqual(packet["retrieval_runtime_summary"]["admitted_initial_evidence_count"], 0)
        self.assertFalse(packet["leaf_retrieval_results"][0]["selected_evidence"])
        self.assertFalse(packet["evidence_chunks"])
        self.assertFalse(packet["retrieval_evidence_provenance_slices"])
        self.assertEqual(packet["omitted_candidates"][0]["candidate_status"], "rejected")
        self.assertIn(
            "retrieved_source_text_missing",
            packet["omitted_candidates"][0]["omission_reason_codes"],
        )

    def test_configured_browser_provider_uses_openai_web_search_citations(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        payloads = []

        def responses_client(payload: dict) -> dict:
            payloads.append(payload)
            return {
                "output": [
                    {"type": "web_search_call", "status": "completed", "action": {"query": "example"}},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Use the official report and independent coverage.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://source.example/report",
                                        "title": "Source report",
                                        "start_index": 8,
                                        "end_index": 23,
                                    }
                                ],
                            }
                        ],
                    },
                ]
            }

        provider = ConfiguredBrowserProvider(responses_client=responses_client)
        records = provider.search_candidate_urls(context, context["query_variants"][0], searched_at="2026-06-24T12:00:00+00:00")

        self.assertEqual(records[0]["url"], "https://source.example/report")
        self.assertEqual(records[0]["result_source"], "openai_web_search")
        self.assertFalse(records[0]["web_fetch_used_for_search"])
        self.assertEqual(payloads[0]["model"], "gpt-5.5")
        self.assertEqual(payloads[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(payloads[0]["include"], ["web_search_call.action.sources"])
        self.assertEqual(payloads[0]["tool_choice"], "auto")
        self.assertFalse(payloads[0]["store"])
        self.assertIn("do not estimate probabilities", payloads[0]["input"])
        diagnostics = provider.provider_diagnostics()
        self.assertEqual(diagnostics["search_provider"], "openai_web_search")
        self.assertEqual(diagnostics["search_model"], "gpt-5.5")
        self.assertTrue(diagnostics["search_configured"])
        self.assertFalse(diagnostics["authority_boundary"]["certifies_research_sufficiency"])

    def test_configured_browser_provider_uses_openai_web_search_action_sources(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]

        def responses_client(_payload: dict) -> dict:
            return {
                "output": [
                    {
                        "type": "web_search_call",
                        "status": "completed",
                        "action": {
                            "type": "search",
                            "query": "example",
                            "sources": [
                                {
                                    "type": "source",
                                    "url": "https://source.example/full-source",
                                    "title": "Full consulted source",
                                    "snippet": "Source from web_search_call.action.sources.",
                                }
                            ],
                        },
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Short cited answer.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://source.example/annotation-only",
                                        "title": "Annotation-only source",
                                    }
                                ],
                            }
                        ],
                    },
                ]
            }

        provider = ConfiguredBrowserProvider(responses_client=responses_client)
        records = provider.search_candidate_urls(context, context["query_variants"][0])

        self.assertEqual(records[0]["url"], "https://source.example/full-source")
        self.assertEqual(records[0]["result_source"], "openai_web_search")
        self.assertEqual(records[1]["url"], "https://source.example/annotation-only")

    def test_configured_browser_provider_openai_http_path_uses_responses_api(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        calls = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "Result",
                                        "annotations": [
                                            {
                                                "type": "url_citation",
                                                "url": "https://source.example/http",
                                                "title": "HTTP result",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ).encode("utf-8")

        def opener(request, timeout):
            calls.append((request.full_url, dict(request.header_items()), json.loads(request.data.decode("utf-8")), timeout))
            return Response()

        provider = ConfiguredBrowserProvider(openai_api_key="test-openai-key", opener=opener)
        records = provider.search_candidate_urls(context, context["query_variants"][0])

        self.assertEqual(records[0]["url"], "https://source.example/http")
        self.assertEqual(calls[0][0], "https://api.openai.com/v1/responses")
        self.assertEqual(calls[0][2]["tools"], [{"type": "web_search"}])
        self.assertEqual(calls[0][2]["include"], ["web_search_call.action.sources"])
        self.assertEqual(calls[0][2]["model"], "gpt-5.5")
        self.assertIn("Authorization", calls[0][1])
        self.assertIn("Content-type", calls[0][1])

    def test_configured_browser_provider_no_openai_auth_fails_closed(self) -> None:
        provider = ConfiguredBrowserProvider(openai_api_key=None, responses_client=None)
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]

        records = provider.search_candidate_urls(context, context["query_variants"][0])

        self.assertEqual(records, [])
        self.assertEqual(provider.last_search_error, "openai_api_key_not_configured")
        self.assertFalse(provider.provider_diagnostics()["search_configured"])
        self.assertEqual(provider.provider_diagnostics()["search_provider"], "openai_web_search")

    def test_configured_browser_provider_uses_openclaw_oauth_web_search(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        calls = []

        def subprocess_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "reply": json.dumps(
                            {
                                "schema_version": "ads-browser-search-candidates/v1",
                                "candidates": [
                                    {
                                        "url": "https://source.example/openclaw",
                                        "title": "OpenClaw source",
                                        "snippet": "Discovered by hosted web search.",
                                    }
                                ],
                            }
                        )
                    }
                ),
                stderr="",
            )

        provider = ConfiguredBrowserProvider(
            search_backend="openclaw_oauth_web_search",
            openclaw_cli="/usr/local/bin/openclaw",
            openclaw_agent_id="workbench",
            openclaw_session_key_prefix="ads-test-search",
            openclaw_model="gpt-5.5",
            subprocess_run=subprocess_run,
        )

        records = provider.search_candidate_urls(context, context["query_variants"][0])

        self.assertEqual(records[0]["url"], "https://source.example/openclaw")
        self.assertEqual(records[0]["result_source"], "openclaw_oauth_web_search")
        self.assertFalse(records[0]["web_fetch_used_for_search"])
        command, kwargs = calls[0]
        self.assertEqual(command[:2], ["/usr/local/bin/openclaw", "agent"])
        self.assertIn("--json", command)
        self.assertIn("--message", command)
        self.assertIn("--model", command)
        self.assertIn("gpt-5.5", command)
        self.assertEqual(command[command.index("--timeout") + 1], "45")
        self.assertNotIn("--local", command)
        self.assertEqual(kwargs["capture_output"], True)
        self.assertEqual(kwargs["timeout"], 55.0)
        self.assertIn("Return exactly one JSON object", command[command.index("--message") + 1])
        diagnostics = provider.provider_diagnostics()
        self.assertEqual(diagnostics["search_provider"], "openclaw_oauth_web_search")
        self.assertEqual(diagnostics["openclaw_agent_id"], "workbench")
        self.assertTrue(diagnostics["search_configured"])
        self.assertEqual(diagnostics["search_timeout_seconds"], 45.0)
        self.assertEqual(diagnostics["search_subprocess_grace_seconds"], 10.0)
        self.assertFalse(diagnostics["authority_boundary"]["certifies_research_sufficiency"])

    def test_configured_browser_provider_openclaw_oauth_fails_closed_without_cli(self) -> None:
        provider = ConfiguredBrowserProvider(search_backend="openclaw_oauth_web_search", openclaw_cli=None)
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]

        with patch("researcher_swarm.browser_provider.shutil.which", return_value=None):
            records = provider.search_candidate_urls(context, context["query_variants"][0])
            diagnostics = provider.provider_diagnostics()

        self.assertEqual(records, [])
        self.assertEqual(provider.last_search_error, "openclaw_cli_not_configured")
        self.assertFalse(diagnostics["search_configured"])
        self.assertFalse(diagnostics["openclaw_cli_configured"])

    def test_configured_browser_provider_openclaw_oauth_invalid_reply_fails_closed(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]

        def subprocess_run(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"reply": "not json"}), stderr="")

        provider = ConfiguredBrowserProvider(
            search_backend="openclaw_oauth_web_search",
            openclaw_cli="/usr/local/bin/openclaw",
            subprocess_run=subprocess_run,
        )

        records = provider.search_candidate_urls(context, context["query_variants"][0])

        self.assertEqual(records, [])
        self.assertTrue(provider.last_search_error)

    def test_configured_browser_provider_openclaw_oauth_timeout_fails_closed(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]

        def subprocess_run(_command, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="openclaw agent", timeout=8)

        provider = ConfiguredBrowserProvider(
            search_backend="openclaw_oauth_web_search",
            openclaw_cli="/usr/local/bin/openclaw",
            search_timeout_seconds=5,
            search_subprocess_grace_seconds=3,
            subprocess_run=subprocess_run,
        )

        records = provider.search_candidate_urls(context, context["query_variants"][0])
        diagnostics = provider.provider_diagnostics()

        self.assertEqual(records, [])
        self.assertIn("timed out", provider.last_search_error)
        self.assertEqual(diagnostics["search_timeout_seconds"], 5.0)
        self.assertEqual(diagnostics["search_subprocess_grace_seconds"], 3.0)
        self.assertEqual(diagnostics["last_search_error"], provider.last_search_error)

    def test_configured_browser_provider_openai_without_citations_fails_closed(self) -> None:
        provider = ConfiguredBrowserProvider(responses_client=lambda _payload: {"output": [{"type": "message", "content": []}]})
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]

        records = provider.search_candidate_urls(context, context["query_variants"][0])

        self.assertEqual(records, [])
        self.assertEqual(provider.last_search_error, "openai_web_search_no_url_citations")

    def test_configured_browser_provider_uses_explicit_brave_search_boundary(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        calls = []

        class Response:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {"content-type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps(
                    {
                        "web": {
                            "results": [
                                {
                                    "url": "https://source.example/report",
                                    "title": "Source report",
                                    "description": "Independent source result.",
                                }
                            ]
                        }
                    }
                ).encode("utf-8")

        def opener(request, timeout):
            calls.append((request.full_url, dict(request.header_items()), timeout))
            return Response()

        provider = ConfiguredBrowserProvider(search_backend="brave_search_api", search_api_key="test-key", opener=opener)
        records = provider.search_candidate_urls(context, context["query_variants"][0], searched_at="2026-06-24T12:00:00+00:00")

        self.assertEqual(records[0]["url"], "https://source.example/report")
        self.assertEqual(records[0]["result_source"], "brave_search_api")
        self.assertFalse(records[0]["web_fetch_used_for_search"])
        self.assertIn("X-subscription-token", calls[0][1])
        self.assertTrue(provider.provider_diagnostics()["search_configured"])

    def test_configured_browser_provider_fetch_is_url_extraction_only(self) -> None:
        class Response:
            url = "https://source.example/final"
            headers = {
                "content-type": "text/html",
                "last-modified": "Wed, 24 Jun 2026 11:30:00 GMT",
                "date": "Wed, 24 Jun 2026 11:40:00 GMT",
            }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return b"<html><head><style>.x{}</style></head><body><h1>Official source</h1><script>x()</script><p>Evidence text.</p></body></html>"

        provider = ConfiguredBrowserProvider(openai_api_key=None, opener=lambda _request, timeout: Response())
        records = provider.search_candidate_urls(
            build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0],
            build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]["query_variants"][0],
        )
        fetched = provider.fetch_url("https://source.example/page")

        self.assertEqual(records, [])
        self.assertEqual(provider.last_search_error, "openai_api_key_not_configured")
        self.assertEqual(fetched["final_url"], "https://source.example/final")
        self.assertIn("Official source", fetched["content"])
        self.assertNotIn("x()", fetched["content"])
        self.assertNotIn("source_published_at", fetched)
        self.assertNotIn("source_updated_at", fetched)
        self.assertEqual(fetched["http_last_modified_at"], "2026-06-24T11:30:00+00:00")
        self.assertEqual(fetched["web_fetch_role"], "url_fetch_extraction_only")
        self.assertFalse(provider.provider_diagnostics()["authority_boundary"]["certifies_source_class"])

    def test_configured_browser_provider_extracts_page_bound_dates(self) -> None:
        class Response:
            url = "https://source.example/final"
            headers = {
                "content-type": "text/html; charset=utf-8",
                "last-modified": "Wed, 24 Jun 2026 08:00:00 GMT",
                "date": "Wed, 24 Jun 2026 11:40:00 GMT",
            }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return b"""
                <html>
                  <head>
                    <meta property="article:published_time" content="2026-06-24T11:20:00Z">
                    <script type="application/ld+json">
                      {"@type": "NewsArticle", "dateModified": "2026-06-24T11:35:00Z"}
                    </script>
                  </head>
                  <body><p>Fetched page text with page-bound publication metadata.</p></body>
                </html>
                """

        provider = ConfiguredBrowserProvider(openai_api_key=None, opener=lambda _request, timeout: Response())

        fetched = provider.fetch_url("https://source.example/page")

        self.assertEqual(fetched["source_published_at"], "2026-06-24T11:20:00+00:00")
        self.assertEqual(fetched["source_updated_at"], "2026-06-24T11:35:00+00:00")
        self.assertIn("page-bound publication metadata", fetched["content"])
        self.assertNotIn("source_class", fetched)
        self.assertNotIn("claim_family_id", fetched)

    def test_configured_browser_provider_fetch_failure_fails_closed_without_search_summary_content(self) -> None:
        def opener(_request, timeout):
            self.assertEqual(timeout, 20.0)
            raise RuntimeError("simulated 403")

        provider = ConfiguredBrowserProvider(
            search_backend="openclaw_oauth_web_search",
            openclaw_cli="/usr/local/bin/openclaw",
            opener=opener,
        )

        fetched = provider.fetch_url("https://source.example/protected")

        self.assertEqual(fetched["url"], "https://source.example/protected")
        self.assertEqual(fetched["final_url"], "https://source.example/protected")
        self.assertEqual(fetched["extraction_status"], "rejected")
        self.assertEqual(fetched["reason_codes"], ["http_fetch_failed"])
        self.assertEqual(fetched["web_fetch_role"], "url_fetch_extraction_only")
        self.assertIn("simulated 403", fetched["provider_error"])
        self.assertNotIn("content", fetched)
        self.assertNotIn("title", fetched)
        self.assertNotIn("snippet", fetched)
        self.assertEqual(provider.last_fetch_error, "simulated 403")

    def test_configured_browser_provider_rendered_fetch_fallback_is_url_specific(self) -> None:
        calls = []

        def opener(_request, _timeout):
            raise RuntimeError("simulated 403")

        def rendered_fetcher(url, timeout_seconds, max_chars):
            calls.append((url, timeout_seconds, max_chars))
            return {
                "final_url": "https://source.example/final",
                "body_text": "Rendered protected page text from the requested URL only.",
                "head_html": '<meta property="article:published_time" content="2026-06-24T11:25:00Z">',
                "source_class": "official_or_primary",
                "claim_family_id": "claim-family-forbidden",
            }

        provider = ConfiguredBrowserProvider(
            openai_api_key=None,
            opener=opener,
            max_fetch_chars=1200,
            rendered_fetch_enabled=True,
            rendered_fetch_timeout_seconds=3,
            rendered_fetcher=rendered_fetcher,
        )

        fetched = provider.fetch_url("https://source.example/protected")

        self.assertEqual(calls, [("https://source.example/protected", 3.0, 1200)])
        self.assertEqual(fetched["url"], "https://source.example/protected")
        self.assertEqual(fetched["final_url"], "https://source.example/final")
        self.assertEqual(fetched["extraction_status"], "accepted")
        self.assertEqual(fetched["extraction_method"], "local_rendered_fetch_fallback")
        self.assertEqual(fetched["web_fetch_role"], "url_fetch_extraction_only")
        self.assertEqual(fetched["source_published_at"], "2026-06-24T11:25:00+00:00")
        self.assertIn("Rendered protected page text", fetched["content"])
        self.assertEqual(
            fetched["rendered_fetch_diagnostic"]["capture_boundary"],
            "exact_requested_url_rendered_page_text_only",
        )
        self.assertEqual(fetched["rendered_fetch_diagnostic"]["status"], "accepted")
        self.assertNotIn("source_class", fetched)
        self.assertNotIn("claim_family_id", fetched)
        self.assertFalse(provider.provider_diagnostics()["authority_boundary"]["certifies_source_class"])

    def test_configured_browser_provider_rendered_fetch_disabled_by_default_after_http_failure(self) -> None:
        calls = []

        def opener(_request, _timeout):
            raise RuntimeError("simulated 403")

        def rendered_fetcher(url, timeout_seconds, max_chars):
            calls.append((url, timeout_seconds, max_chars))
            return {"body_text": "Should not be used."}

        provider = ConfiguredBrowserProvider(
            openai_api_key=None,
            opener=opener,
            rendered_fetcher=rendered_fetcher,
        )

        fetched = provider.fetch_url("https://source.example/protected")

        self.assertEqual(calls, [])
        self.assertEqual(fetched["extraction_status"], "rejected")
        self.assertEqual(fetched["reason_codes"], ["http_fetch_failed"])
        self.assertNotIn("rendered_fetch_diagnostic", fetched)
        self.assertFalse(provider.provider_diagnostics()["rendered_fetch_enabled"])

    def test_configured_browser_provider_rendered_fetch_empty_text_fails_closed(self) -> None:
        def opener(_request, _timeout):
            raise RuntimeError("simulated 403")

        provider = ConfiguredBrowserProvider(
            openai_api_key=None,
            opener=opener,
            rendered_fetch_enabled=True,
            rendered_fetcher=lambda _url, _timeout, _max_chars: {
                "final_url": "https://source.example/protected",
                "body_text": "   ",
            },
        )

        fetched = provider.fetch_url("https://source.example/protected")

        self.assertEqual(fetched["extraction_status"], "rejected")
        self.assertEqual(fetched["reason_codes"], ["http_fetch_failed", "rendered_fetch_empty_content"])
        self.assertEqual(fetched["web_fetch_role"], "url_fetch_extraction_only")
        self.assertNotIn("content", fetched)
        self.assertEqual(fetched["rendered_fetch_diagnostic"]["status"], "rejected")
        self.assertEqual(provider.last_rendered_fetch_error, "rendered_fetch_empty_content")

    def test_configured_browser_provider_openclaw_browser_cli_rendered_fetch_uses_requested_url_and_closes_tab(self) -> None:
        calls = []

        def opener(_request, _timeout):
            raise RuntimeError("simulated 403")

        def subprocess_run(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "doctor":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"ok": True, "status": {"running": True}}),
                    stderr="",
                )
            if command[-2:] == ["open", "https://source.example/protected"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"targetId": "t-rendered"}),
                    stderr="",
                )
            if "evaluate" in command:
                self.assertIn("--fn", command)
                fn = command[command.index("--fn") + 1]
                self.assertIn("window.location.href", fn)
                self.assertIn("document.body.innerText", fn)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(
                        {
                            "result": {
                                "final_url": "https://source.example/final",
                                "title": "Rendered page",
                                "body_text": "Rendered page text.",
                                "head_html": '<meta property="article:published_time" content="2026-06-24T11:26:00Z">',
                                "source_class": "official_or_primary",
                            }
                        }
                    ),
                    stderr="",
                )
            if command[-2:] == ["close", "t-rendered"]:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"ok": True}), stderr="")
            self.fail(f"unexpected command: {command}")

        provider = ConfiguredBrowserProvider(
            openai_api_key=None,
            opener=opener,
            openclaw_cli="/usr/local/bin/openclaw",
            rendered_fetch_enabled=True,
            rendered_fetch_timeout_seconds=4,
            rendered_fetch_backend="openclaw_browser_cli",
            subprocess_run=subprocess_run,
        )

        fetched = provider.fetch_url("https://source.example/protected")

        self.assertEqual(fetched["extraction_status"], "accepted")
        self.assertEqual(fetched["final_url"], "https://source.example/final")
        self.assertEqual(fetched["content"], "Rendered page text.")
        self.assertEqual(fetched["source_published_at"], "2026-06-24T11:26:00+00:00")
        self.assertEqual(fetched["rendered_fetch_diagnostic"]["backend"], "openclaw_browser_cli")
        self.assertNotIn("source_class", fetched)
        command_names = [
            "evaluate" if "evaluate" in command else command[-1]
            for command, _kwargs in calls
            if command[-1] != "https://source.example/protected"
        ]
        self.assertEqual(command_names, ["doctor", "evaluate", "t-rendered"])
        self.assertTrue(any(command[-2:] == ["open", "https://source.example/protected"] for command, _kwargs in calls))
        self.assertTrue(any("evaluate" in command for command, _kwargs in calls))
        self.assertTrue(all(kwargs["timeout"] == 6.0 for _command, kwargs in calls))
        self.assertTrue(all("--timeout" in command and "4000" in command for command, _kwargs in calls))

    def test_configured_browser_provider_openclaw_browser_cli_not_running_fails_closed(self) -> None:
        def opener(_request, _timeout):
            raise RuntimeError("simulated 403")

        def subprocess_run(command, **_kwargs):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"ok": False, "status": {"running": False}}),
                stderr="",
            )

        provider = ConfiguredBrowserProvider(
            openai_api_key=None,
            opener=opener,
            openclaw_cli="/usr/local/bin/openclaw",
            rendered_fetch_enabled=True,
            rendered_fetch_backend="openclaw_browser_cli",
            subprocess_run=subprocess_run,
        )

        fetched = provider.fetch_url("https://source.example/protected")

        self.assertEqual(fetched["extraction_status"], "rejected")
        self.assertEqual(fetched["reason_codes"], ["http_fetch_failed", "openclaw_browser_not_running"])
        self.assertNotIn("content", fetched)
        self.assertEqual(provider.last_rendered_fetch_error, "openclaw_browser_not_running")

    def test_default_configured_provider_factory_can_enable_rendered_fetch_by_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ADS_BROWSER_RENDERED_FETCH_ENABLED": "true",
                "ADS_BROWSER_RENDERED_FETCH_TIMEOUT_SECONDS": "6",
            },
            clear=True,
        ):
            with patch("researcher_swarm.browser_provider.shutil.which", return_value="/usr/local/bin/openclaw"):
                provider = build_provider()

        diagnostics = provider.provider_diagnostics()
        self.assertTrue(diagnostics["rendered_fetch_enabled"])
        self.assertEqual(diagnostics["rendered_fetch_backend"], "openclaw_browser_cli")
        self.assertEqual(diagnostics["rendered_fetch_timeout_seconds"], 6.0)

    def test_default_configured_provider_factory_can_select_python_rendered_fetch_backend(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ADS_BROWSER_RENDERED_FETCH_ENABLED": "true",
                "ADS_BROWSER_RENDERED_FETCH_BACKEND": "python_playwright",
                "ADS_BROWSER_RENDERED_FETCH_TIMEOUT_SECONDS": "6",
            },
            clear=True,
        ):
            with patch("researcher_swarm.browser_provider.shutil.which", return_value="/usr/local/bin/openclaw"):
                provider = build_provider()

        diagnostics = provider.provider_diagnostics()
        self.assertTrue(diagnostics["rendered_fetch_enabled"])
        self.assertEqual(diagnostics["rendered_fetch_backend"], "python_playwright")
        self.assertEqual(diagnostics["rendered_fetch_timeout_seconds"], 6.0)

    def test_default_configured_provider_factory_uses_openclaw_oauth_backend(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("researcher_swarm.browser_provider.shutil.which", return_value="/usr/local/bin/openclaw"):
                provider = build_provider()

        self.assertIsInstance(provider, ConfiguredBrowserProvider)
        self.assertIsNone(provider.search_api_key)
        self.assertTrue(provider.provider_diagnostics()["search_configured"])
        self.assertEqual(provider.provider_diagnostics()["search_provider"], "openclaw_oauth_web_search")
        self.assertEqual(provider.provider_diagnostics()["openclaw_agent_id"], "researcher-swarm")
        self.assertEqual(provider.provider_diagnostics()["search_limit"], 2)
        self.assertEqual(provider.provider_diagnostics()["search_timeout_seconds"], 45.0)

    def test_phase7_native_candidate_caps_forbidden_fields_and_nonblocking_unavailability(self) -> None:
        context = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)[0]
        candidates = [
            {
                "url": f"https://native.example/source-{idx}",
                "source_label": f"Native source {idx}",
                "why_it_may_matter": "May identify a source to fetch.",
                "related_leaf_id": context["leaf_id"],
                "candidate_claim_text": "A bounded claim candidate.",
                "uncertainty_notes": "Needs deterministic validation.",
            }
            for idx in range(20)
        ]
        discovery = build_native_research_candidate_discovery(
            context,
            context["query_variants"][0],
            candidates,
        )

        self.assertLessEqual(discovery["candidate_url_count"], discovery["candidate_cap"])
        self.assertGreater(discovery["candidate_url_count_omitted_by_cap"], 0)
        self.assertFalse(discovery["authority_boundary"]["research_sufficiency_authority"])
        with self.assertRaisesRegex(RetrievalPacketError, "forbidden"):
            build_native_research_candidate_discovery(
                context,
                context["query_variants"][0],
                [
                    {
                        "url": "https://native.example/bad",
                        "source_label": "Bad",
                        "why_it_may_matter": "Bad",
                        "related_leaf_id": context["leaf_id"],
                        "candidate_claim_text": "Bad",
                        "probability": 0.5,
                    }
                ],
            )

        certifiable = finalize_retrieval_packet_for_dispatch(self._certifiable_packet())
        with_diagnostic = attach_native_research_transport_diagnostics(
            certifiable,
            availability_status="unavailable",
            unavailable_reason="native_transport_not_configured",
        )
        self.assertEqual(with_diagnostic["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        self.assertEqual(with_diagnostic["native_research_transport_diagnostics"][0]["availability_status"], "unavailable")

    def test_phase3_supplemental_source_counts_only_after_deterministic_admission(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        initial = self._live_candidates_for_context(context, include_direct=False, count=4)
        search_candidates = self._search_candidates_for_context(context, initial)
        supplemental_ref = f"supplemental:{context['leaf_id']}:official"
        supplemental = {
            "supplemental_evidence_ref": supplemental_ref,
            "leaf_id": context["leaf_id"],
            "parent_branch_id": context["parent_branch_id"],
            "retrieval_transport": "browser",
            "fetch_status": "metadata_fixture",
            "url": "https://example.com/official/supplemental",
            "canonical_url": "https://example.com/official/supplemental",
            "source_class": "official_or_primary",
            "source_class_resolution_method": "manual_fixture",
            "deterministic_source_class_proof": True,
            "source_family_id": "source-family-live-supplemental-official",
            "source_family_resolution_method": "deterministic_url_registry",
            "claim_family_id": "claim-family-live-supplemental-official",
            "source_published_at": "2026-06-24T11:45:00+00:00",
            "content": (
                "Supplemental official source admitted after deterministic validation. "
                "It includes enough bounded detail for researcher classification and certified snippet assignment. "
                * 4
            ),
        }

        packet = build_live_retrieval_packet_from_candidates(
            qdt,
            evidence_packet=self.evidence_packet,
            fetched_candidates=initial,
            search_candidate_urls=search_candidates,
            supplemental_candidates=[supplemental],
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )
        self.assertEqual(packet["supplemental_evidence_admission_results"][0]["normalization_status"], "normalized")
        self.assertEqual(packet["supplemental_evidence_admission_results"][0]["admission_status"], "admitted")
        self.assertEqual(packet["leaf_evidence_dockets"][0]["supplemental_candidate_refs"], [supplemental_ref])
        self.assertTrue(packet["leaf_evidence_dockets"][0]["supplemental_admission_result_refs"])
        admitted_reasons = [
            reason
            for result in packet["leaf_retrieval_results"]
            for evidence in result["selected_evidence"]
            for reason in evidence["admission_reason_codes"]
        ]
        self.assertIn("supplemental_evidence_admitted_after_validation", admitted_reasons)

    def test_ret_008_missing_certificate_rejects_allowed_dispatch_status(self) -> None:
        packet = self._certifiable_packet()
        finalized = finalize_retrieval_packet_for_dispatch(packet)
        finalized["leaf_research_sufficiency_certificates"] = finalized["leaf_research_sufficiency_certificates"][:-1]
        finalized["research_sufficiency_summary"]["classification_dispatch_status"] = "allowed"
        finalized["research_sufficiency_summary"]["all_required_leaves_certified"] = True
        finalized["research_sufficiency_summary"]["leaf_certificate_refs"] = [
            cert["certificate_id"] for cert in finalized["leaf_research_sufficiency_certificates"]
        ]

        result = validate_retrieval_packet(finalized)

        self.assertFalse(result.valid)
        self.assertIn("missing certificates", "; ".join(result.errors))

    def test_ret_008_macro_fallback_only_blocks_critical_leaf_dispatch(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        leaf = qdt["required_leaf_questions"][0]
        leaf["purpose"] = "source_of_truth"
        leaf["research_sufficiency_requirements"]["protected_primary_required"] = True
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet)
        packet = attach_retrieval_expansion_and_fallback_plan(packet, macro_fallback_requested=True)

        finalized = finalize_retrieval_packet_for_dispatch(packet)

        self.assertEqual(
            finalized["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        blocked = next(
            cert for cert in finalized["leaf_research_sufficiency_certificates"] if cert["leaf_id"] == leaf["leaf_id"]
        )
        self.assertEqual(blocked["status"], "blocked_macro_fallback_only")
        self.assertIn(
            "macro_fallback_only_for_critical_or_source_of_truth",
            blocked["blocking_reason_codes"],
        )
        self.assertTrue(finalized["retrieval_stage_status_records"])
        self.assertEqual(finalized["retrieval_stage_execution_events"][0]["event_type"], "stage_blocked")

    def test_ret_008_stale_or_failed_breadth_blocks_dispatch_and_persists_expansion_codes(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][1]]
        context = build_retrieval_query_contexts(qdt, evidence_packet=self.evidence_packet)[0]
        official = self._evidence(
            context,
            attempt_ref="stale-official",
            canonical_url="https://example.com/official/stale",
            source_class="official_or_primary",
            source_family_id="source-family-stale-official",
            claim_family_id="claim-family-stale-official",
            source_published_at="2026-06-01T11:30:00+00:00",
        )
        official["deterministic_source_class_proof"] = True
        official["source_class_resolution_method"] = "manual_fixture"
        secondary = self._evidence(
            context,
            attempt_ref="stale-secondary",
            canonical_url="https://independent.example/stale",
            source_class="independent_secondary",
            source_family_id="source-family-stale-secondary",
            claim_family_id="claim-family-stale-secondary",
            source_published_at="2026-06-01T11:30:00+00:00",
        )
        packet = build_retrieval_packet(
            qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=[official, secondary],
        )

        finalized = finalize_retrieval_packet_for_dispatch(packet)

        cert = finalized["leaf_research_sufficiency_certificates"][0]
        self.assertEqual(cert["status"], "blocked_stale")
        self.assertFalse(cert["classification_dispatch_allowed"])
        self.assertIn("freshness", cert["unsatisfied_requirement_codes"])
        self.assertTrue(finalized["retrieval_expansion_attempts"])
        self.assertTrue(
            all(
                "unsatisfied_requirement_codes" in attempt
                for attempt in finalized["retrieval_expansion_attempts"]
            )
        )

    def test_ret_008_structural_unanswerability_after_bounded_expansion_can_certify_leaf(self) -> None:
        qdt = copy.deepcopy(self.qdt)
        qdt["required_leaf_questions"] = [qdt["required_leaf_questions"][0]]
        leaf = qdt["required_leaf_questions"][0]
        leaf["research_sufficiency_requirements"]["max_targeted_expansion_attempts"] = 2
        packet = build_retrieval_packet(qdt, evidence_packet=self.evidence_packet)
        packet["leaf_retrieval_results"][0]["structural_unanswerability_proof_ref"] = "artifact:unanswerable-proof-1"
        packet["retrieval_breadth_coverage_slices"] = []
        packet = attach_retrieval_expansion_and_fallback_plan(packet)

        finalized = finalize_retrieval_packet_for_dispatch(packet)

        cert = finalized["leaf_research_sufficiency_certificates"][0]
        self.assertEqual(cert["status"], "structurally_unanswerable")
        self.assertTrue(cert["classification_dispatch_allowed"])
        self.assertEqual(
            finalized["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )
        self.assertEqual(finalized["retrieval_outcome_state"]["retrieval_outcome"], "structural_unanswerability")
        self.assertEqual(
            finalized["retrieval_outcome_state"]["downstream_action"],
            "dispatch_unanswerability_confirmation",
        )
        self.assertEqual(
            finalized["retrieval_outcome_state"]["structural_unanswerability_proof_refs"],
            ["artifact:unanswerable-proof-1"],
        )

    def test_native_transport_unavailability_is_diagnostic_and_resolver_owns_metadata(self) -> None:
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)

        packet = attach_native_research_transport_diagnostics(
            packet,
            availability_status="unavailable",
            unavailable_reason="native_transport_not_configured",
        )

        self.assertTrue(validate_retrieval_packet(packet).valid)
        self.assertEqual(packet["schema_feature_gates"]["RET-010"], "implemented")
        diagnostic = packet["native_research_transport_diagnostics"][0]
        self.assertEqual(diagnostic["availability_status"], "unavailable")
        self.assertTrue(diagnostic["non_blocking_when_alternative_transport_satisfies_requirements"])
        self.assertFalse(diagnostic["native_output_authority"]["source_metadata_final_authority"])
        self.assertTrue(packet["native_research_attempts"])
        self.assertTrue(
            all(
                attempt["diagnostic_only_when_unavailable"]
                and attempt["metadata_authority_boundary"]["source_class_final_authority"] is False
                for attempt in packet["native_research_attempts"]
            )
        )
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_until_certified",
        )

        native_proposal_only = normalize_retrieval_provenance(
            {
                "retrieval_transport": "native_gpt_research",
                "transport_attempt_ref": "native:proposal",
                "model_proposed_source_class": "official_or_primary",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )
        self.assertEqual(native_proposal_only["source_class"], "unknown")
        self.assertIn(
            "native_research_proposed_metadata_not_final_authority",
            native_proposal_only["unknown_reason_codes"],
        )

        deterministic_official = normalize_retrieval_provenance(
            {
                "retrieval_transport": "native_gpt_research",
                "transport_attempt_ref": "native:official",
                "canonical_url": "https://example.com/official",
                "official_source_hints": ["https://example.com/official"],
                "source_class": "official_or_primary",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
        )
        resolution = deterministic_official["source_metadata_resolution"]
        self.assertEqual(deterministic_official["source_class"], "official_or_primary")
        self.assertEqual(resolution["accepted_metadata_authority"], "deterministic_source_metadata_resolver")
        self.assertIn("source_class", resolution["deterministic_resolver_accepted_fields"])
        self.assertFalse(resolution["model_proposed_metadata_counted"])

    def test_source_metadata_classifier_slice_records_oauth_lane_and_compact_packet(self) -> None:
        lane = resolve_source_metadata_classifier_lane(
            {
                "lanes": {
                    "source_metadata_classifier_assist": {
                        "provider": "openai",
                        "default_provider_model_key": "openai/gpt-5.4-mini",
                        "allowed_provider_model_keys": ["openai/gpt-5.4-mini", "openai/o4-mini"],
                        "oauth_route_required": True,
                    }
                }
            },
            available_provider_model_keys=["openai/gpt-5.4-mini"],
        )
        candidate_packet = build_compact_source_candidate_packet(
            {
                "candidate_id": "candidate-news",
                "leaf_id": "leaf-1",
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser-attempt-1",
                "canonical_url": "https://news.example.com/story?utm_source=search",
                "title": "Example publisher reports result",
                "snippet": "A bounded passage about the example event.",
                "publisher_metadata": {"name": "News Example"},
            }
        )
        classifier_slice = build_source_metadata_classifier_slice(
            candidate_packet,
            {
                "proposed_source_class": "primary_reporting",
                "source_class_confidence": "high",
                "proposed_source_family_hint": "news.example.com",
                "source_family_confidence": "high",
                "syndication_hint": "none",
                "reason_codes": ["ordinary_publisher_page"],
            },
            lane=lane,
        )

        self.assertEqual(classifier_slice["model_lane_id"], "source_metadata_classifier_assist")
        self.assertEqual(classifier_slice["provider_model_key"], "openai/gpt-5.4-mini")
        self.assertTrue(classifier_slice["input_candidate_sha256"].startswith("sha256:"))
        self.assertFalse(classifier_slice["authority_boundary"]["protected_primary_final_authority"])
        self.assertLessEqual(len(candidate_packet["snippet_excerpt"]), 1200)

        evidence = build_retrieval_evidence_item(
            case_id="case-1",
            dispatch_id="dispatch-1",
            leaf_id=self.qdt["required_leaf_questions"][0]["leaf_id"],
            parent_branch_id=self.qdt["required_leaf_questions"][0]["parent_branch_id"],
            retrieval_transport="browser",
            transport_attempt_ref="browser-attempt-1",
            canonical_url="https://news.example.com/story",
            source_published_at="2026-06-24T11:00:00+00:00",
            claim_family_resolution_refs=["claim-family-example"],
        )
        evidence["source_metadata_classifier_slice"] = classifier_slice
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet, selected_evidence=[evidence])

        self.assertTrue(validate_retrieval_packet(packet).valid)
        self.assertEqual(packet["schema_feature_gates"]["RET-011"], "implemented")
        self.assertEqual(packet["source_metadata_classifier_slices"][0]["classifier_slice_id"], classifier_slice["classifier_slice_id"])

    def test_classifier_source_class_acceptance_is_bounded_to_ordinary_sources(self) -> None:
        candidate_packet = build_compact_source_candidate_packet(
            {
                "candidate_id": "candidate-ordinary",
                "leaf_id": "leaf-1",
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser-attempt-ordinary",
                "canonical_url": "https://publisher.example.com/report",
                "snippet": "Publisher reports one market-relevant claim.",
            }
        )
        classifier_slice = build_source_metadata_classifier_slice(
            candidate_packet,
            {
                "proposed_source_class": "primary_reporting",
                "source_class_confidence": "high",
                "syndication_hint": "none",
            },
        )

        provenance = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser-attempt-ordinary",
                "canonical_url": "https://publisher.example.com/report",
                "source_published_at": "2026-06-24T11:00:00+00:00",
                "claim_family_resolution_refs": ["claim-family-example"],
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
            classifier_slice=classifier_slice,
        )

        self.assertEqual(provenance["source_class"], "primary_reporting")
        self.assertEqual(provenance["classifier_acceptance_status"], "accepted_source_class")
        self.assertIn("ordinary_source_class_not_protected", provenance["classifier_acceptance_reason_codes"])

        protected_slice = build_source_metadata_classifier_slice(
            candidate_packet,
            {
                "proposed_source_class": "official_or_primary",
                "source_class_confidence": "high",
            },
        )
        protected_provenance = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser-attempt-protected",
                "canonical_url": "https://publisher.example.com/report",
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
            classifier_slice=protected_slice,
        )

        self.assertEqual(protected_provenance["source_class"], "unknown")
        self.assertEqual(protected_provenance["classifier_acceptance_status"], "classifier_unsupported")
        self.assertIn("classifier_unsupported_for_protected_primary", protected_provenance["unknown_reason_codes"])

    def test_classifier_family_claim_and_visible_date_require_deterministic_validation(self) -> None:
        candidate_packet = build_compact_source_candidate_packet(
            {
                "candidate_id": "candidate-claim",
                "leaf_id": "leaf-1",
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser-attempt-claim",
                "snippet": "The event was confirmed on June 24.",
            }
        )
        classifier_slice = build_source_metadata_classifier_slice(
            candidate_packet,
            {
                "proposed_source_class": "unknown",
                "source_class_confidence": "unknown",
                "proposed_source_family_hint": "wire-service-example",
                "source_family_confidence": "high",
                "syndication_hint": "reuters_copy",
                "visible_date_candidates": [{"date_text": "2026-06-24T10:00:00+00:00"}],
                "atomic_claim_candidates": [
                    {
                        "subject": "Example event",
                        "predicate": "was confirmed",
                        "object_or_value": "yes",
                        "event_time": "2026-06-24",
                        "entity_or_jurisdiction": "example",
                        "condition_scope": "unconditional",
                        "polarity": "affirmed",
                        "supporting_span_refs": ["retrieval-span-1"],
                        "confidence": "high",
                    }
                ],
            },
        )

        unsupported_family = normalize_retrieval_provenance(
            {
                "retrieval_transport": "browser",
                "transport_attempt_ref": "browser-attempt-claim",
            },
            dispatch_context={
                "forecast_timestamp": "2026-06-24T12:00:00+00:00",
                "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            },
            classifier_slice=classifier_slice,
        )
        self.assertEqual(unsupported_family["source_family_id"], "source-family-unknown")
        self.assertEqual(unsupported_family["temporal_gate_status"], "pass")
        self.assertEqual(unsupported_family["classifier_acceptance_status"], "accepted_visible_date_candidate")
        self.assertIn(
            "classifier_source_family_hint_without_deterministic_support",
            unsupported_family["unknown_reason_codes"],
        )

        claim_candidates = build_atomic_claim_candidates_from_classifier_slice(
            evidence_ref="retrieval-evidence-claim",
            leaf_id="leaf-1",
            chunk_refs=["retrieval-chunk-1"],
            classifier_slice=classifier_slice,
        )
        claim_resolutions = resolve_claim_families(claim_candidates)
        self.assertEqual(claim_candidates[0]["validation_status"], "accepted_for_normalization")
        self.assertNotEqual(claim_resolutions[0]["claim_family_id"], "claim-family-unknown")
        self.assertEqual(claim_resolutions[0]["resolution_method"], "candidate_validated_then_deterministic_tuple_hash")

        no_span_slice = build_source_metadata_classifier_slice(
            candidate_packet,
            {
                "atomic_claim_candidates": [
                    {
                        "subject": "Example event",
                        "predicate": "was confirmed",
                        "object_or_value": "yes",
                    }
                ],
            },
        )
        no_span_candidates = build_atomic_claim_candidates_from_classifier_slice(
            evidence_ref="retrieval-evidence-claim",
            leaf_id="leaf-1",
            chunk_refs=["retrieval-chunk-1"],
            classifier_slice=no_span_slice,
        )
        self.assertEqual(no_span_candidates[0]["validation_status"], "rejected_no_span")

    def test_classifier_unavailable_is_non_blocking_diagnostic(self) -> None:
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)

        packet = attach_source_metadata_classifier_unavailable(
            packet,
            available_provider_model_keys=[],
            unavailable_reason="openai_oauth_classifier_route_unavailable",
        )

        self.assertTrue(validate_retrieval_packet(packet).valid)
        self.assertEqual(packet["schema_feature_gates"]["RET-011"], "implemented")
        diagnostic = packet["source_metadata_classifier_unavailable_diagnostics"][0]
        self.assertEqual(diagnostic["artifact_type"], "source_metadata_classifier_unavailable")
        self.assertTrue(diagnostic["non_blocking_when_alternative_transport_satisfies_requirements"])
        self.assertFalse(diagnostic["classifier_assist_authority"]["protected_primary_final_authority"])
        self.assertEqual(
            packet["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_until_certified",
        )

    def test_forbidden_probability_field_is_rejected(self) -> None:
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)
        packet["leaf_query_contexts"][0]["leaf_probability"] = 0.5

        result = validate_retrieval_packet(packet)

        self.assertFalse(result.valid)
        self.assertIn("leaf_probability", "; ".join(result.errors))

    def test_cli_builds_packet_and_manifest_uses_artifact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            qdt_path = Path(temp) / "question-decomposition.json"
            evidence_path = Path(temp) / "evidence-packet.json"
            packet_path = Path(temp) / "retrieval-packet.json"
            manifest_path = Path(temp) / "retrieval-packet.manifest.json"
            qdt_path.write_text(json.dumps(self.qdt), encoding="utf-8")
            evidence_path.write_text(json.dumps(self.evidence_packet), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "researcher-swarm" / "scripts" / "bin" / "build_retrieval_packet.py"),
                    str(qdt_path),
                    "--evidence-packet",
                    str(evidence_path),
                    "--output",
                    str(packet_path),
                    "--manifest-output",
                    str(manifest_path),
                    "--question-decomposition-artifact-id",
                    "artifact:qdt-1",
                    "--policy-context-ref",
                    "artifact:profile-1",
                ],
                check=False,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertTrue(validate_retrieval_packet(packet).valid)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_artifact_manifest(manifest)
            self.assertEqual(manifest["artifact_type"], "retrieval-packet")
            self.assertEqual(manifest["metadata"]["feature_id"], "RET-001")

    def test_manifest_helper_builds_safe_retrieval_packet_manifest(self) -> None:
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)
        with tempfile.TemporaryDirectory() as temp:
            packet_path = Path(temp) / "retrieval-packet.json"
            packet_path.write_text(dump_retrieval_packet(packet), encoding="utf-8")

            manifest = build_retrieval_packet_manifest(packet, path=packet_path)

            validate_artifact_manifest(manifest)
            self.assertEqual(manifest["artifact_schema_version"], "retrieval-packet/v1")
            self.assertEqual(manifest["temporal_isolation_status"], "pass")


if __name__ == "__main__":
    unittest.main()
