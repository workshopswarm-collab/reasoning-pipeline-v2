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
from researcher_swarm.classification import (  # noqa: E402
    FORBIDDEN_CONTEXT_REF_PATTERNS,
    FORBIDDEN_OUTPUT_FIELDS,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
    ClassificationPromptContractError,
    build_researcher_nli_prompt_contract,
    validate_researcher_nli_prompt_contract,
)
from researcher_swarm.model_context import (  # noqa: E402
    MODEL_LANE_POLICY_REF,
    RESEARCHER_MODEL_ID,
    RESEARCHER_MODEL_LANE_ID,
)
from researcher_swarm.retrieval import (  # noqa: E402
    build_evidence_chunk,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)


def _contains_key(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return any(str(key) == target or _contains_key(child, target) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


class ResearcherClassificationPromptContractTest(unittest.TestCase):
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
            if "expert_or_specialist" in context["sufficiency_requirements"].get("required_source_classes", []):
                expert = self._evidence(
                    context,
                    attempt_ref=f"{context['leaf_id']}-expert",
                    canonical_url=f"https://expert.example/{context['leaf_id']}",
                    source_class="expert_or_specialist",
                    source_family_id=f"source-family-{context['leaf_id']}-expert",
                    claim_family_id=f"claim-family-{context['leaf_id']}-expert",
                )
                selected.append(expert)
        for item in selected:
            text = (
                f"Prompt contract certified excerpt for {item['transport_attempt_ref']} with enough bounded "
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
            self.qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        packet["evidence_chunks"] = chunks
        finalized = finalize_retrieval_packet_for_dispatch(packet)
        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        return finalized

    def test_prompt_contract_renders_required_cls001_context(self) -> None:
        packet = self._certifiable_packet()

        contract = build_researcher_nli_prompt_contract(qdt=self.qdt, retrieval_packet=packet)
        validation = validate_researcher_nli_prompt_contract(contract)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(contract["feature_id"], "CLS-001")
        self.assertEqual(contract["prompt_template"]["prompt_template_id"], RESEARCHER_NLI_PROMPT_TEMPLATE_ID)
        self.assertEqual(contract["prompt_template"]["prompt_template_sha256"], RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256)
        self.assertEqual(contract["schema_metadata"]["sidecar_schema_version"], "researcher-sidecar/v2")
        self.assertEqual(contract["schema_metadata"]["classification_schema_version"], "researcher-classification/v1")
        self.assertIn("MODEL-003", contract["scope_boundaries"]["implements"])
        self.assertNotIn("MODEL-003", contract["scope_boundaries"]["not_implemented"])

        payload = contract["context_payload"]
        self.assertEqual(payload["macro_question"], "Will example happen?")
        self.assertTrue(payload["market_constraints"]["read_only"])
        self.assertEqual(payload["retrieval_dispatch_gate"]["classification_dispatch_status"], "allowed")
        self.assertEqual(payload["model_execution_context"], contract["model_execution_context"])
        self.assertEqual(payload["forbidden_output_fields"], list(FORBIDDEN_OUTPUT_FIELDS))
        self.assertEqual(payload["forbidden_context_ref_patterns"], list(FORBIDDEN_CONTEXT_REF_PATTERNS))
        self.assertFalse(payload["authority_boundary"]["probability_authority"])
        self.assertFalse(payload["authority_boundary"]["fair_value_authority"])
        self.assertFalse(payload["authority_boundary"]["interval_authority"])
        self.assertFalse(payload["authority_boundary"]["decision_authority"])

        model_context = contract["model_execution_context"]
        self.assertEqual(model_context["feature_id"], "MODEL-003")
        self.assertEqual(model_context["model_lane_id"], RESEARCHER_MODEL_LANE_ID)
        self.assertEqual(model_context["resolved_model_id"], RESEARCHER_MODEL_ID)
        self.assertEqual(model_context["model_policy_ref"], MODEL_LANE_POLICY_REF)
        self.assertEqual(model_context["prompt_template_id"], RESEARCHER_NLI_PROMPT_TEMPLATE_ID)
        self.assertEqual(model_context["prompt_template_sha256"], RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256)
        self.assertEqual(model_context["sidecar_schema_version"], "researcher-sidecar/v2")
        self.assertEqual(model_context["classification_output_schema_version"], "researcher-classification/v1")
        self.assertFalse(model_context["runtime"]["model_call_performed"])
        self.assertIn("metadata_only_no_model_call", model_context["runtime_reason_codes"])
        self.assertEqual(model_context["fallback_reason_codes"], ["no_fallback_required"])

        leaves = payload["flattened_required_leaves"]
        self.assertEqual(
            sorted(leaf["leaf_id"] for leaf in leaves),
            sorted(leaf["leaf_id"] for leaf in self.qdt["required_leaf_questions"]),
        )
        for leaf in leaves:
            self.assertIn("question_text", leaf)
            self.assertIn("condition_scope", leaf)
            self.assertIn("retrieval_sufficiency_certificate_ref", leaf)
            self.assertEqual(leaf["retrieval_breadth_profile_status"], "present")
            self.assertEqual(leaf["retrieval_breadth_coverage_status"], "present")
            self.assertTrue(leaf["sufficiency_requirements"]["required_value_field_ids"])
            self.assertTrue(leaf["sufficiency_requirements"]["required_negative_check_ids"])
            self.assertTrue(leaf["assigned_evidence_refs"])
            self.assertEqual(leaf["required_output_refs"]["sidecar_contract_ref"], "schema:researcher-sidecar/v2")

        self.assertIn("evidence classification", contract["prompt_text"])
        self.assertIn("Do not forecast", contract["prompt_text"])
        self.assertIn("scae-ledger:*", contract["prompt_text"])

    def test_prompt_contract_fails_closed_when_retrieval_dispatch_is_not_allowed(self) -> None:
        packet = self._certifiable_packet()
        blocked = copy.deepcopy(packet)
        blocked["research_sufficiency_summary"]["classification_dispatch_status"] = "blocked_insufficient_research"

        with self.assertRaisesRegex(ClassificationPromptContractError, "classification dispatch is not allowed"):
            build_researcher_nli_prompt_contract(qdt=self.qdt, retrieval_packet=blocked)

        not_finalized = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        with self.assertRaisesRegex(ClassificationPromptContractError, "blocked_until_certified"):
            build_researcher_nli_prompt_contract(qdt=self.qdt, retrieval_packet=not_finalized)

    def test_contract_is_deterministic_ref_oriented_and_records_model_lane_resolution(self) -> None:
        packet = self._certifiable_packet()

        first = build_researcher_nli_prompt_contract(qdt=self.qdt, retrieval_packet=packet)
        second = build_researcher_nli_prompt_contract(qdt=self.qdt, retrieval_packet=packet)

        self.assertEqual(first["prompt_contract_id"], second["prompt_contract_id"])
        self.assertEqual(first["prompt_contract_digest"], second["prompt_contract_digest"])
        self.assertEqual(first["prompt_text_sha256"], second["prompt_text_sha256"])
        self.assertEqual(first["model_execution_context"], second["model_execution_context"])
        self.assertEqual(
            first["model_execution_context"]["resolved_model_id"],
            RESEARCHER_MODEL_ID,
        )
        self.assertEqual(
            first["model_execution_context"]["model_context_digest"],
            second["model_execution_context"]["model_context_digest"],
        )
        for leaf in first["context_payload"]["flattened_required_leaves"]:
            for evidence_ref in leaf["assigned_evidence_refs"]:
                self.assertIn("evidence_ref", evidence_ref)
                self.assertNotIn("requested_url", evidence_ref)
                self.assertNotIn("final_url", evidence_ref)
                self.assertNotIn("canonical_url", evidence_ref)


if __name__ == "__main__":
    unittest.main()
