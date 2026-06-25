#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.verification import (  # noqa: E402
    build_direction_verification_slices,
    build_quality_verification_slices,
    build_researcher_verification_bundle,
)


class ResearcherVerificationTest(unittest.TestCase):
    def _classification(
        self,
        *,
        slice_id: str = "classification-slice-1",
        classification_id: str = "classification-1",
        leaf_id: str = "leaf-1",
        impact_direction: str = "supports_yes",
        value: str = "market_resolves_yes",
        source_class: str = "official_or_primary",
        temporal_gate_status: str = "pass",
        evidence_strength: str = "strong",
        classification_confidence: str = "high",
        quality: dict[str, str] | None = None,
        ledger_ready: bool = True,
    ) -> dict[str, Any]:
        return {
            "slice_id": slice_id,
            "classification_id": classification_id,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": leaf_id,
            "condition_scope": "unconditional",
            "evidence_ref": f"evidence-{classification_id}",
            "source_class": source_class,
            "source_family_id": f"source-family-{classification_id}",
            "claim_family_id": f"claim-family-{classification_id}",
            "impact_direction": impact_direction,
            "evidence_strength": evidence_strength,
            "classification_confidence": classification_confidence,
            "answer_value_extraction": {
                "field_name": "outcome",
                "value": value,
                "normalization_status": "parsed",
            },
            "evidence_quality_dimensions": quality
            or {
                "source_authority": "high",
                "directness": "direct",
                "recency": "fresh",
                "specificity": "specific",
            },
            "temporal_gate_status": temporal_gate_status,
            "ledger_ready": ledger_ready,
        }

    def _matrix(self, classifications: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "artifact_type": "researcher_classification_matrix",
            "matrix_id": "matrix-1",
            "matrix_digest": "sha256:" + "1" * 64,
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "classification_slices": classifications,
            "provenance_slices": [
                {
                    "slice_id": f"provenance-{item['slice_id']}",
                    "classification_slice_ref": item["slice_id"],
                    "source_class": item.get("source_class"),
                    "source_family_id": item.get("source_family_id"),
                    "claim_family_id": item.get("claim_family_id"),
                    "canonical_source_id": f"source-{item['classification_id']}",
                }
                for item in classifications
            ],
        }

    def _binary_constraints(self) -> dict[str, Any]:
        return {
            "contract_structure": "binary",
            "side_mapping": {
                "yes": {"outcome": "yes", "resolves_to": "market_resolves_yes"},
                "no": {"outcome": "no", "resolves_to": "market_resolves_no"},
            },
        }

    def test_neutral_direction_passthrough_without_sign(self) -> None:
        matrix = self._matrix(
            [
                self._classification(
                    impact_direction="neutral",
                    value="background",
                )
            ]
        )

        result = build_direction_verification_slices(matrix)

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "neutral")
        self.assertEqual(row["method_status"], "verified")
        self.assertTrue(row["accepted_for_scae"])
        self.assertIn("neutral_passthrough", row["reason_codes"])

    def test_side_map_contradiction_is_excluded(self) -> None:
        constraints = self._binary_constraints()
        constraints["side_mapping"]["no"]["resolves_to"] = "market_resolves_yes"

        result = build_direction_verification_slices(
            self._matrix([self._classification()]),
            market_reality_constraints=constraints,
        )

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "excluded")
        self.assertEqual(row["method_status"], "excluded")
        self.assertEqual(row["verification_status"], "excluded")
        self.assertIn("side_mapping_conflict", row["reason_codes"])

    def test_ambiguous_direction_is_quarantined(self) -> None:
        constraints = {
            "contract_structure": "other",
            "side_mapping": {
                "primary": {"outcome": "primary", "resolves_to": "market_primary_outcome"},
            },
        }

        result = build_direction_verification_slices(
            self._matrix([self._classification()]),
            market_reality_constraints=constraints,
        )

        row = result.direction_verification_slices[0]
        self.assertEqual(row["verified_direction"], "ambiguous")
        self.assertEqual(row["method_status"], "quarantined")
        self.assertEqual(row["verification_status"], "quarantined")
        self.assertIn("direction_ambiguous", row["reason_codes"])

    def test_coverage_after_exclusion_is_recorded(self) -> None:
        accepted = self._classification(
            slice_id="classification-slice-accepted",
            classification_id="classification-accepted",
            leaf_id="leaf-1",
            impact_direction="supports_yes",
            value="market_resolves_yes",
        )
        contradicted = self._classification(
            slice_id="classification-slice-contradicted",
            classification_id="classification-contradicted",
            leaf_id="leaf-1",
            impact_direction="supports_yes",
            value="market_resolves_no",
        )

        result = build_direction_verification_slices(
            self._matrix([accepted, contradicted]),
            market_reality_constraints=self._binary_constraints(),
        )

        row_by_id = {
            row["classification_id"]: row
            for row in result.direction_verification_slices
        }
        excluded = row_by_id["classification-contradicted"]
        self.assertEqual(excluded["verification_status"], "excluded")
        self.assertEqual(excluded["coverage_after_exclusion_status"], "covered_after_exclusion")
        self.assertTrue(excluded["deadlock_safe_exclusion"])
        self.assertIn("deadlock_safe_exclusion_with_remaining_coverage", excluded["reason_codes"])

    def test_all_non_neutral_rows_receive_direction_verification(self) -> None:
        matrix = self._matrix(
            [
                self._classification(slice_id="classification-slice-1", classification_id="classification-1"),
                self._classification(
                    slice_id="classification-slice-2",
                    classification_id="classification-2",
                    impact_direction="supports_no",
                    value="market_resolves_no",
                ),
            ]
        )

        result = build_direction_verification_slices(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )

        self.assertEqual(len(result.direction_verification_slices), 2)
        self.assertTrue(all(row["method_status"] == "verified" for row in result.direction_verification_slices))

    def test_stale_evidence_normalizes_recency_lower_than_claimed(self) -> None:
        row = self._classification(temporal_gate_status="fail")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["claimed_quality_fields"]["recency"], "fresh")
        self.assertEqual(quality["machine_normalized_quality_fields"]["recency"], "stale")
        self.assertEqual(quality["accepted_quality_fields"]["recency"], "stale")
        self.assertIn("recency_claim_downgraded", quality["reason_codes"])

    def test_unknown_source_authority_cannot_be_high_by_claim_alone(self) -> None:
        row = self._classification(source_class="unknown")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["claimed_quality_fields"]["source_authority"], "high")
        self.assertEqual(quality["machine_normalized_quality_fields"]["source_authority"], "unknown")
        self.assertEqual(quality["accepted_quality_fields"]["source_authority"], "unknown")
        self.assertIn("source_authority_claim_downgraded", quality["reason_codes"])

    def test_directness_disagreement_produces_reason_code(self) -> None:
        row = self._classification(evidence_strength="weak")

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertEqual(quality["machine_normalized_quality_fields"]["directness"], "background")
        self.assertEqual(quality["accepted_quality_fields"]["directness"], "background")
        self.assertIn("directness_claim_downgraded", quality["reason_codes"])

    def test_raw_quality_multiplier_is_bounded(self) -> None:
        row = self._classification(
            source_class="unknown",
            evidence_strength="none",
            classification_confidence="low",
            quality={
                "source_authority": "unknown",
                "directness": "unknown",
                "recency": "unknown",
                "specificity": "unknown",
            },
        )
        row["answer_value_extraction"] = {"normalization_status": "failed"}
        row["temporal_gate_status"] = "unknown_not_counted"

        result = build_quality_verification_slices(self._matrix([row]))

        quality = result.quality_verification_slices[0]
        self.assertGreaterEqual(quality["raw_quality_multiplier"], 0.05)
        self.assertLessEqual(quality["raw_quality_multiplier"], 1.0)
        self.assertEqual(quality["final_quality_multiplier"], quality["raw_quality_multiplier"])

    def test_every_included_classification_receives_quality_verification(self) -> None:
        matrix = self._matrix(
            [
                self._classification(slice_id="classification-slice-1", classification_id="classification-1"),
                self._classification(
                    slice_id="classification-slice-2",
                    classification_id="classification-2",
                    impact_direction="supports_no",
                    value="market_resolves_no",
                    source_class="independent_secondary",
                    classification_confidence="medium",
                ),
            ]
        )

        result = build_quality_verification_slices(matrix)

        self.assertEqual(len(result.quality_verification_slices), len(matrix["classification_slices"]))
        self.assertTrue(
            all(
                "raw_quality_multiplier_inputs" in row
                and row["quality_correlation_groups"]
                and row["quality_status"] == "accepted"
                for row in result.quality_verification_slices
            )
        )

    def test_combined_bundle_marks_only_ver001_and_ver002_scope(self) -> None:
        matrix = self._matrix([self._classification()])

        bundle = build_researcher_verification_bundle(
            matrix,
            market_reality_constraints=self._binary_constraints(),
        )

        self.assertEqual(bundle["scope_boundaries"]["implements"], ["VER-001", "VER-002"])
        self.assertIn("SCAE", bundle["scope_boundaries"]["not_implemented"])
        self.assertFalse(bundle["scope_boundaries"]["writes_scae_ledger_rows"])
        self.assertEqual(len(bundle["direction_verification_slices"]), 1)
        self.assertEqual(len(bundle["quality_verification_slices"]), 1)


if __name__ == "__main__":
    unittest.main()
