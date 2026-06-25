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
        for feature_id in ["RET-002", "RET-003", "RET-004", "RET-008", "RET-009", "RET-010", "RET-011"]:
            self.assertEqual(packet["schema_feature_gates"][feature_id], "pending")
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
        self.assertTrue(claim_family["claim_family_id"].startswith("claim-family-"))
        self.assertEqual(claim_family["counts_toward_claim_family_breadth"], True)
        self.assertEqual(source_metadata["temporal_safety_status"], "unknown_not_counted")

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
