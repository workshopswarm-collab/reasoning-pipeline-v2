#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.decision_gate import (  # noqa: E402
    DECISION_GATE_AUTHORITY,
    DECISION_GATE_SCHEMA_VERSION,
    DecisionGateError,
    build_decision_gate,
    validate_decision_gate_artifact,
)
from predquant.synthesis_annotation import build_synthesis_annotation  # noqa: E402


class DecisionGateTest(unittest.TestCase):
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
            "execution_authority_status": "normal_execution_allowed",
            "final_probability_fields_status": "final_probability_fields_ready",
            "raw_ledger_probability": 0.56,
            "post_ledger_probability": 0.58,
            "debt_adjusted_probability": 0.58,
            "production_forecast_prob": 0.58,
            "canonical_probability": 0.58,
            "writes_production_forecast": False,
            "writes_persistence": False,
        }

    def synthesis_annotation(self):
        return build_synthesis_annotation(
            scae_ledger=self.scae_ledger(),
            qualitative_annotations=[
                {
                    "annotation_type": "key_evidence",
                    "summary": "Qualitative evidence context favors the yes side.",
                    "leverage_direction": "supports_yes_qualitatively",
                    "source_refs": ["classification-summary:1"],
                    "reason_codes": ["qualitative_context_only"],
                }
            ],
            generated_at="2026-06-25T12:01:00+00:00",
        )

    def test_builds_decision_gate_from_scae_probability_context_only(self):
        artifact = build_decision_gate(
            scae_ledger=self.scae_ledger(),
            synthesis_annotation=self.synthesis_annotation(),
            decision_request={"rationale": "Use SCAE numeric output and keep normal execution.", "reason_codes": ["baseline"]},
            generated_at="2026-06-25T12:02:00+00:00",
        )

        validate_decision_gate_artifact(artifact)
        self.assertEqual(artifact["schema_version"], DECISION_GATE_SCHEMA_VERSION)
        self.assertEqual(artifact["authority"], DECISION_GATE_AUTHORITY)
        self.assertEqual(artifact["forecast_validity_status"], "valid_for_forecast")
        self.assertEqual(artifact["execution_authority_status"], "normal_execution_allowed")
        self.assertEqual(artifact["actionability_status"], "actionable")
        self.assertEqual(artifact["scae_context"]["production_forecast_prob"], 0.58)
        self.assertEqual(artifact["scae_context"]["canonical_probability"], 0.58)
        self.assertFalse(artifact["probability_authority"])
        self.assertFalse(artifact["writes_persistence"])
        self.assertFalse(artifact["writes_market_prediction"])
        self.assertFalse(artifact["clears_calibration_debt"])

        serialized = json.dumps(
            {
                key: value
                for key, value in artifact.items()
                if key not in {"scae_context", "forbidden_outputs"}
            },
            sort_keys=True,
        )
        self.assertNotIn("production_forecast_prob", serialized)
        self.assertNotIn("canonical_probability", serialized)

    def test_rejects_replacement_probability_fields_and_numeric_language(self):
        with self.assertRaisesRegex(DecisionGateError, "replacement_probability"):
            build_decision_gate(
                scae_ledger=self.scae_ledger(),
                decision_request={"replacement_probability": 0.72},
            )

        with self.assertRaisesRegex(DecisionGateError, "probability_range"):
            build_decision_gate(
                scae_ledger=self.scae_ledger(),
                decision_request={"nested": {"probability_range": [0.5, 0.7]}},
            )

        with self.assertRaisesRegex(DecisionGateError, "numeric probability"):
            build_decision_gate(
                scae_ledger=self.scae_ledger(),
                decision_request={"rationale": "I would set the probability to 61%."},
            )

    def test_decision_can_downgrade_execution_and_actionability(self):
        artifact = build_decision_gate(
            scae_ledger=self.scae_ledger(),
            decision_request={
                "forecast_validity_status": "valid_for_forecast_watch_only",
                "execution_authority_status": "watch_only",
                "actionability_status": "non_actionable",
                "reason_codes": ["liquidity_pause"],
            },
        )

        self.assertEqual(artifact["forecast_validity_status"], "valid_for_forecast_watch_only")
        self.assertEqual(artifact["execution_authority_status"], "watch_only")
        self.assertEqual(artifact["actionability_status"], "non_actionable")
        self.assertTrue(artifact["downgrade_context"]["forecast_validity_downgraded"])
        self.assertTrue(artifact["downgrade_context"]["execution_authority_downgraded"])
        self.assertTrue(artifact["downgrade_context"]["actionability_downgraded"])

    def test_invalid_and_watch_only_scae_states_cannot_be_upgraded(self):
        invalid = self.scae_ledger()
        invalid["forecast_validity_status"] = "invalid_for_forecast"
        invalid["execution_authority_status"] = "forbidden"
        invalid.pop("production_forecast_prob")
        invalid.pop("canonical_probability")
        invalid.pop("final_probability_fields_status")
        with self.assertRaisesRegex(DecisionGateError, "upgrade SCAE forecast validity"):
            build_decision_gate(
                scae_ledger=invalid,
                decision_request={"forecast_validity_status": "valid_for_forecast_watch_only"},
            )

        watch = self.scae_ledger()
        watch["forecast_validity_status"] = "valid_for_forecast_watch_only"
        watch["execution_authority_status"] = "watch_only"
        with self.assertRaisesRegex(DecisionGateError, "upgrade SCAE forecast validity"):
            build_decision_gate(
                scae_ledger=watch,
                decision_request={"forecast_validity_status": "valid_for_forecast"},
            )
        with self.assertRaisesRegex(DecisionGateError, "upgrade SCAE execution authority"):
            build_decision_gate(
                scae_ledger=watch,
                decision_request={"execution_authority_status": "normal_execution_allowed"},
            )

    def test_invalid_scae_state_is_non_actionable_without_final_probability(self):
        invalid = self.scae_ledger()
        invalid["forecast_validity_status"] = "invalid_for_forecast"
        invalid["execution_authority_status"] = "forbidden"
        invalid.pop("production_forecast_prob")
        invalid.pop("canonical_probability")
        invalid.pop("final_probability_fields_status")

        artifact = build_decision_gate(scae_ledger=invalid)

        self.assertEqual(artifact["forecast_validity_status"], "invalid_for_forecast")
        self.assertEqual(artifact["execution_authority_status"], "forbidden")
        self.assertEqual(artifact["actionability_status"], "non_actionable")
        self.assertNotIn("production_forecast_prob", artifact["scae_context"])
        self.assertFalse(artifact["writes_production_forecast"])

    def test_rejects_malformed_synthesis_context_with_numeric_authority(self):
        synthesis = self.synthesis_annotation()
        synthesis["production_forecast_prob"] = 0.62
        with self.assertRaisesRegex(Exception, "production_forecast_prob"):
            build_decision_gate(
                scae_ledger=self.scae_ledger(),
                synthesis_annotation=synthesis,
            )

    def test_cli_writes_decision_gate_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ledger_path = tmp_path / "ledger.json"
            synthesis_path = tmp_path / "synthesis.json"
            request_path = tmp_path / "request.json"
            output_path = tmp_path / "decision.json"
            ledger_path.write_text(json.dumps(self.scae_ledger()), encoding="utf-8")
            synthesis_path.write_text(json.dumps(self.synthesis_annotation()), encoding="utf-8")
            request_path.write_text(
                json.dumps({"execution_authority_status": "low_size_only", "reason_codes": ["size_cap"]}),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    "orchestrator/scripts/bin/run_decision_gate.py",
                    "--scae-ledger",
                    str(ledger_path),
                    "--synthesis-annotation",
                    str(synthesis_path),
                    "--decision-request",
                    str(request_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
            )

            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            validate_decision_gate_artifact(artifact)
            self.assertEqual(artifact["feature_id"], "DEC-001")
            self.assertEqual(artifact["execution_authority_status"], "low_size_only")


if __name__ == "__main__":
    unittest.main()
