#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.synthesis_annotation import (  # noqa: E402
    SYNTHESIS_ANNOTATION_AUTHORITY,
    SYNTHESIS_ANNOTATION_SCHEMA_VERSION,
    SynthesisAnnotationError,
    build_synthesis_annotation,
    validate_synthesis_annotation,
)


class SynthesisAnnotationTest(unittest.TestCase):
    def scae_ledger(self):
        return {
            "artifact_type": "scae_ledger",
            "schema_version": "scae-ledger/v1",
            "case_id": "case-1",
            "case_key": "case:key:1",
            "dispatch_id": "dispatch-1",
            "run_id": "run-1",
            "forecast_timestamp": "2026-06-25T12:00:00+00:00",
            "final_probability_ledger_id": "scae-final-probability-ledger:1",
            "final_probability_ledger_digest": "sha256:" + "a" * 64,
            "forecast_validity_status": "valid_for_forecast",
            "execution_authority_status": "low_size_only",
            "final_probability_fields_status": "final_probability_fields_ready",
            "raw_ledger_probability": 0.56,
            "post_ledger_probability": 0.58,
            "debt_adjusted_probability": 0.58,
            "production_forecast_prob": 0.58,
            "canonical_probability": 0.58,
            "research_sufficiency_context": {
                "research_sufficiency_context_id": "research-sufficiency-context:1",
                "leaf_reconciliation_refs": ["research-sufficiency-reconciliation:1"],
            },
            "calibration_debt_context": {
                "calibration_debt_context_id": "calibration-debt-context:1",
            },
            "writes_production_forecast": False,
            "writes_persistence": False,
        }

    def classification_summary(self):
        return {
            "artifact_type": "classification-summary",
            "schema_version": "classification-summary/v1",
            "classification_summary_id": "classification-summary:1",
            "leaf_id": "leaf-1",
            "qualitative_summary": "Primary source confirms the event status remains unresolved.",
            "source_refs": ["source:1"],
            "reason_codes": ["official_source_context"],
        }

    def research_summary(self):
        return {
            "artifact_type": "research-summary",
            "schema_version": "research-summary/v1",
            "research_summary_id": "research-summary:1",
            "leaf_id": "leaf-1",
            "summary": "Research coverage found no unresolved critical contradiction.",
            "source_refs": ["researcher-sidecar:1"],
            "reason_codes": ["coverage_complete"],
        }

    def test_builds_qualitative_annotation_without_copying_scae_probability_values(self):
        annotation = build_synthesis_annotation(
            scae_ledger=self.scae_ledger(),
            classification_summaries=[self.classification_summary()],
            research_summaries=[self.research_summary()],
            qualitative_annotations=[
                {
                    "annotation_type": "key_evidence",
                    "summary": "Official-source coverage is the main qualitative leverage point.",
                    "leverage_direction": "supports_yes_qualitatively",
                    "source_refs": ["classification-summary:1", "research-summary:1"],
                    "reason_codes": ["qualitative_leverage_only"],
                }
            ],
            generated_at="2026-06-25T12:01:00+00:00",
        )

        validate_synthesis_annotation(annotation)
        self.assertEqual(annotation["schema_version"], SYNTHESIS_ANNOTATION_SCHEMA_VERSION)
        self.assertEqual(annotation["authority"], SYNTHESIS_ANNOTATION_AUTHORITY)
        self.assertEqual(annotation["scae_context"]["scae_ledger_ref"], "scae-final-probability-ledger:1")
        self.assertEqual(annotation["scae_context"]["forecast_validity_status"], "valid_for_forecast")
        self.assertFalse(annotation["live_forecast_authority"])
        self.assertFalse(annotation["decision_authority"])
        self.assertFalse(annotation["writes_production_forecast"])
        self.assertFalse(annotation["writes_persistence"])

        serialized = json.dumps(
            {
                key: value
                for key, value in annotation.items()
                if key not in {"scae_context", "forbidden_outputs"}
            },
            sort_keys=True,
        )
        for forbidden in (
            "production_forecast_prob",
            "canonical_probability",
            "debt_adjusted_probability",
            "raw_ledger_probability",
            "post_ledger_probability",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_rejects_synthesis_authored_probability_and_decision_fields(self):
        with self.assertRaisesRegex(SynthesisAnnotationError, "probability_range"):
            build_synthesis_annotation(
                scae_ledger=self.scae_ledger(),
                qualitative_annotations=[
                    {
                        "summary": "bad",
                        "probability_range": [0.4, 0.6],
                    }
                ],
            )

        with self.assertRaisesRegex(SynthesisAnnotationError, "decision_override"):
            build_synthesis_annotation(
                scae_ledger=self.scae_ledger(),
                metadata={"decision_override": "upgrade_to_trade"},
            )

        with self.assertRaisesRegex(SynthesisAnnotationError, "numeric probability"):
            build_synthesis_annotation(
                scae_ledger=self.scae_ledger(),
                qualitative_annotations=[
                    {
                        "summary": "I would set the probability to 61%.",
                    }
                ],
            )

        annotation = build_synthesis_annotation(scae_ledger=self.scae_ledger())
        annotation["production_forecast_prob"] = 0.61
        with self.assertRaisesRegex(SynthesisAnnotationError, "production_forecast_prob"):
            validate_synthesis_annotation(annotation)

    def test_rejects_probability_or_scae_delta_in_input_summaries(self):
        classification = self.classification_summary()
        classification["scae_delta"] = 0.2
        with self.assertRaisesRegex(SynthesisAnnotationError, "scae_delta"):
            build_synthesis_annotation(
                scae_ledger=self.scae_ledger(),
                classification_summaries=[classification],
            )

        research = self.research_summary()
        research["replacement_probability"] = 0.7
        with self.assertRaisesRegex(SynthesisAnnotationError, "replacement_probability"):
            build_synthesis_annotation(
                scae_ledger=self.scae_ledger(),
                research_summaries=[research],
            )

    def test_rejects_scae_input_with_persistence_write_claim(self):
        ledger = self.scae_ledger()
        ledger["writes_persistence"] = True
        with self.assertRaisesRegex(SynthesisAnnotationError, "persistence write authority"):
            build_synthesis_annotation(scae_ledger=ledger)

    def test_accepts_single_dict_summary_inputs(self):
        annotation = build_synthesis_annotation(
            scae_ledger=self.scae_ledger(),
            classification_summaries=self.classification_summary(),
            research_summaries=self.research_summary(),
        )

        self.assertEqual(annotation["classification_summary_inputs"][0]["summary_ref"], "classification-summary:1")
        self.assertEqual(annotation["research_summary_inputs"][0]["summary_ref"], "research-summary:1")

    def test_cli_writes_annotation_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_path = tmp_path / "ledger.json"
            classification_path = tmp_path / "classification.json"
            output_path = tmp_path / "synthesis.json"
            ledger_path.write_text(json.dumps(self.scae_ledger()), encoding="utf-8")
            classification_path.write_text(json.dumps(self.classification_summary()), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "bin" / "run_synthesis_annotation.py"),
                    "--scae-ledger",
                    str(ledger_path),
                    "--classification-summary",
                    str(classification_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
            )

            annotation = json.loads(output_path.read_text(encoding="utf-8"))
            validate_synthesis_annotation(annotation)
            self.assertEqual(annotation["feature_id"], "SYN-001")
            self.assertEqual(annotation["classification_summary_inputs"][0]["summary_ref"], "classification-summary:1")


if __name__ == "__main__":
    unittest.main()
