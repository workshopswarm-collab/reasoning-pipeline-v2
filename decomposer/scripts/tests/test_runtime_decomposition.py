#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import validate_question_decomposition  # noqa: E402


class RuntimeDecompositionEntrypointTest(unittest.TestCase):
    def _handoff(self) -> dict:
        return {
            "artifact_type": "decomposer_handoff",
            "schema_version": "decomposer-handoff/v1",
            "case_id": "case-runtime-1",
            "case_key": "polymarket:runtime-1",
            "dispatch_id": "dispatch-runtime-1",
            "prediction_run_id": "prediction-run-runtime-1",
            "forecast_artifact_id": "forecast-artifact-runtime-1",
            "forecast_timestamp": "2026-06-24T12:00:00+00:00",
            "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            "macro_question": "Will Acme ship the Atlas update before July 2026?",
            "market_context": {
                "market_id": "runtime-1",
                "market_reality_constraints_digest": "sha256:" + "0" * 64,
            },
            "artifact_refs": {
                "related_market_context": {
                    "artifact_id": "artifact:amrg-runtime-1",
                    "artifact_type": "related-live-market-context",
                },
            },
            "input_manifest_ids": ["artifact:case", "artifact:evidence", "artifact:profile", "artifact:amrg"],
            "model_execution_context": {
                "model_lane_id": DECOMPOSER_MODEL_LANE_ID,
                "provider": "openai",
                "provider_route": "openai/gpt-5.5-high",
                "resolved_model_id": DECOMPOSER_MODEL_ID,
                "model_policy_ref": "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json",
                "prompt_template_id": DECOMPOSER_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": "sha256:" + "1" * 64,
                "input_manifest_ids": ["artifact:case", "artifact:evidence", "artifact:profile", "artifact:amrg"],
                "output_schema_version": "question-decomposition/v1",
            },
            "forbidden_refs": [
                "scae",
                "synthesis",
                "decision",
                "outcomes",
                "evaluator_labels",
                "replay",
                "scoring",
            ],
            "validation_summary": {"status": "valid"},
        }

    def test_cli_writes_question_specific_qdt_and_runtime_call(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            handoff_path = temp / "handoff.json"
            qdt_path = temp / "question-decomposition.json"
            runtime_path = temp / "model-runtime-call.json"
            handoff_path.write_text(json.dumps(self._handoff(), sort_keys=True), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "decomposer" / "scripts" / "bin" / "run_decomposition.py"),
                    "--handoff",
                    str(handoff_path),
                    "--output",
                    str(qdt_path),
                    "--runtime-call-output",
                    str(runtime_path),
                    "--runtime-mode",
                    "fixture",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            qdt = json.loads(qdt_path.read_text(encoding="utf-8"))
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))

        self.assertTrue(validate_question_decomposition(qdt).valid)
        leaf_ids = {leaf["leaf_id"] for leaf in qdt["required_leaf_questions"]}
        self.assertFalse(
            {"leaf-source-of-truth", "leaf-direct-evidence", "leaf-resolution-mechanics"} & leaf_ids
        )
        self.assertTrue(any("acme" in leaf_id and "ship" in leaf_id for leaf_id in leaf_ids))
        self.assertEqual(qdt["adapter_mode"], "decomposer_model_runtime_fixture")
        self.assertEqual(qdt["model_execution_context"]["runtime_call_ref"], runtime["runtime_call_id"])
        self.assertTrue(qdt["model_execution_context"]["model_executed"])
        self.assertEqual(qdt["model_execution_context"]["resolved_model_id"], "gpt-5.5-high")
        self.assertEqual(runtime["execution_status"], "succeeded")
        self.assertEqual(runtime["forbidden_output_scan"]["status"], "passed")
        self.assertTrue(qdt["question_specificity_check"]["generic_fixture_leaf_ids_absent"])


if __name__ == "__main__":
    unittest.main()
