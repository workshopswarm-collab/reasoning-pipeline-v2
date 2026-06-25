#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.retrieval import (  # noqa: E402
    build_retrieval_evidence_item,
    build_retrieval_packet,
    validate_retrieval_packet,
)
from researcher_swarm.retrieval_quality import (  # noqa: E402
    attach_retrieval_quality_report,
    build_retrieval_quality_report,
    validate_retrieval_quality_report,
)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if "probability" in str(key).lower():
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


class RetrievalQualityScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.qdt = {
            "artifact_type": "question_decomposition",
            "schema_version": "question-decomposition/v1",
            "case_id": "case-quality-1",
            "case_key": "polymarket:quality-1",
            "dispatch_id": "dispatch-quality-1",
            "macro_question": "Will the example event resolve yes?",
            "branches": [
                {
                    "branch_id": "branch-quality-1",
                    "branch_question": "Did the example event occur?",
                }
            ],
            "required_leaf_questions": [
                {
                    "leaf_id": "leaf-quality-1",
                    "parent_branch_id": "branch-quality-1",
                    "question_text": "Did the official source confirm the example event?",
                    "purpose": "source_of_truth",
                    "leaf_condition_scope": "unconditional",
                    "market_component_terms": ["example", "event"],
                    "required_evidence_fields": ["official status", "timestamp"],
                    "research_sufficiency_requirements": {
                        "required_source_classes": ["official_or_primary"],
                        "protected_primary_required": True,
                        "min_independent_source_families": 2,
                        "min_independent_claim_families": 2,
                        "min_temporally_fresh_sources": 1,
                    },
                }
            ],
        }
        self.evidence_packet = {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            "case_id": "case-quality-1",
            "dispatch_id": "dispatch-quality-1",
            "forecast_timestamp": "2026-06-24T12:00:00+00:00",
            "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
        }

    def _evidence(
        self,
        suffix: str,
        *,
        source_class: str = "official_or_primary",
            source_family_id: str = "source-family-official",
            claim_family_ref: str = "claim-family-official",
            temporal_gate_status: str = "pass",
            independence_status: str = "independent",
            source_published_at: str | None = "2026-06-24T11:30:00+00:00",
        ) -> dict[str, Any]:
        return build_retrieval_evidence_item(
            case_id="case-quality-1",
            dispatch_id="dispatch-quality-1",
            leaf_id="leaf-quality-1",
            parent_branch_id="branch-quality-1",
            retrieval_transport="manual_fixture",
            transport_attempt_ref=f"manual-fixture:{suffix}",
            requested_url=f"https://example.test/{suffix}",
            final_url=f"https://example.test/{suffix}",
            canonical_url=f"https://example.test/{suffix}",
            canonical_source_id=f"source-{suffix}",
            claim_family_resolution_refs=[claim_family_ref],
            source_family_id=source_family_id,
            source_class=source_class,
            independence_status=independence_status,
            temporal_gate_status=temporal_gate_status,
            source_published_at=source_published_at,
            admission_reason_codes=["manual_fixture_selected"],
        )

    def test_empty_retrieval_quality_has_empty_protected_and_breadth_diagnostics(self) -> None:
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)

        report = build_retrieval_quality_report(packet)
        validation = validate_retrieval_quality_report(report)

        self.assertTrue(validation.valid, validation.errors)
        quality_slice = report["retrieval_quality_slices"][0]
        self.assertIn("empty_retrieval", quality_slice["diagnostic_codes"])
        self.assertIn("protected_primary_missing", quality_slice["diagnostic_codes"])
        self.assertIn("low_breadth_signal", quality_slice["diagnostic_codes"])
        self.assertLess(quality_slice["quality_score"], 0.35)
        self.assertEqual(quality_slice["authority_boundary"]["forecast_numeric_authority"], False)
        self.assertEqual(quality_slice["authority_boundary"]["authors_new_evidence"], False)
        self.assertFalse(_contains_forbidden_key(report))

    def test_complete_primary_and_breadth_inputs_score_high_without_authoring_evidence(self) -> None:
        selected = [
            self._evidence("official-a", source_family_id="source-family-a", claim_family_ref="claim-family-a"),
            self._evidence("official-b", source_family_id="source-family-b", claim_family_ref="claim-family-b"),
        ]
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet, selected_evidence=selected)

        report = build_retrieval_quality_report(packet)
        quality_slice = report["retrieval_quality_slices"][0]
        packet_with_quality = attach_retrieval_quality_report(packet, report)

        self.assertEqual(quality_slice["quality_status"], "high")
        self.assertEqual(quality_slice["quality_score"], 1.0)
        self.assertEqual(quality_slice["diagnostic_codes"], [])
        self.assertEqual(
            sorted(quality_slice["selected_evidence_refs"]),
            sorted(item["evidence_ref"] for item in selected),
        )
        self.assertTrue(validate_retrieval_packet(packet_with_quality).valid)
        self.assertEqual(packet_with_quality["schema_feature_gates"]["RET-003"], "implemented")

    def test_thin_stale_unknown_and_protected_primary_failures_lower_quality(self) -> None:
        selected = [
            self._evidence(
                "unknown-stale",
                source_class="unknown",
                source_family_id="source-family-unknown",
                claim_family_ref="claim-family-unknown",
                temporal_gate_status="fail",
                independence_status="unknown_not_counted",
                source_published_at="2026-06-24T12:00:01+00:00",
            )
        ]
        packet = build_retrieval_packet(self.qdt, evidence_packet=self.evidence_packet)
        packet["leaf_retrieval_results"][0]["selected_evidence"] = selected
        packet["protected_primary_access_failures"].append(
            {
                "leaf_id": "leaf-quality-1",
                "source_ref": "https://example.test/protected",
                "reason_codes": ["protected_primary_blocked"],
            }
        )

        quality_slice = build_retrieval_quality_report(packet)["retrieval_quality_slices"][0]

        self.assertIn("thin_retrieval", quality_slice["diagnostic_codes"])
        self.assertIn("stale_selected_sources", quality_slice["diagnostic_codes"])
        self.assertIn("unknown_metadata_signals", quality_slice["diagnostic_codes"])
        self.assertIn("protected_primary_access_failed", quality_slice["diagnostic_codes"])
        self.assertEqual(quality_slice["quality_status"], "blocked")
        self.assertGreaterEqual(quality_slice["dimensions"]["unknown_metadata_signal_count"], 3)


if __name__ == "__main__":
    unittest.main()
