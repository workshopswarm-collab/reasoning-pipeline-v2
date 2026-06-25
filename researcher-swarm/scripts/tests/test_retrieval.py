#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
from researcher_swarm.retrieval import (  # noqa: E402
    RetrievalPacketError,
    build_atomic_claim_candidate,
    build_browser_retrieval_attempt,
    build_claim_family_resolution,
    build_evidence_chunk,
    build_evidence_span,
    build_native_research_attempt,
    build_retrieval_candidate_record,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_packet_manifest,
    build_retrieval_query_contexts,
    build_source_metadata_resolution_placeholder,
    normalize_retrieval_provenance,
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
        for feature_id in ["RET-003", "RET-008", "RET-009", "RET-010", "RET-011"]:
            self.assertEqual(packet["schema_feature_gates"][feature_id], "pending")
        self.assertEqual(packet["temporal_isolation_schema_gate"]["status"], "strict_validator_implemented")
        self.assertEqual(packet["research_sufficiency_summary"]["classification_dispatch_status"], "blocked_until_certified")
        self.assertEqual(packet["browser_search_provider_diagnostics"][0]["provider_id"], "openclaw_web_fetch_browser")

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
        self.assertEqual(provenance["classifier_acceptance_status"], "accepted")
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
                "source_published_at": "2026-06-24T11:00:00+00:00",
            },
            dispatch_context=dispatch,
        )

        self.assertEqual(wire_a["source_family_id"], wire_b["source_family_id"])
        self.assertEqual(wire_a["source_family_status"], "syndicated_copy")
        self.assertEqual(api_a["source_family_id"], api_b["source_family_id"])
        self.assertEqual(api_a["source_family_status"], "mirrored_api_endpoint")
        self.assertEqual(direct["source_family_id"], search["source_family_id"])
        self.assertEqual(content_a["source_family_id"], content_b["source_family_id"])
        self.assertEqual(content_a["source_family_status"], "content_hash_dedupe")

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
