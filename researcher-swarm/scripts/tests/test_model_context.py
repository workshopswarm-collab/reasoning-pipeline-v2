#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.classification import (  # noqa: E402
    RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
    RESEARCHER_SIDECAR_SCHEMA_VERSION,
)
from researcher_swarm.model_context import (  # noqa: E402
    MODEL_LANE_POLICY_REF,
    RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION,
    RESEARCHER_MODEL_ID,
    RESEARCHER_MODEL_LANE_ID,
    ResearcherModelContextError,
    resolve_researcher_leaf_nli_model_context,
    validate_researcher_model_execution_context,
)


POLICY_PATH = ROOT / "orchestrator" / "plans" / "autonomous-decomposition-swarm-model-lane-policy.json"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class ResearcherModelContextTest(unittest.TestCase):
    def _policy(self) -> dict:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def _write_policy(self, policy: dict) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "model-lane-policy.json"
        path.write_text(_canonical_json(policy) + "\n", encoding="utf-8")
        return path

    def test_resolves_researcher_leaf_nli_default_model_context(self) -> None:
        context = resolve_researcher_leaf_nli_model_context()
        validation = validate_researcher_model_execution_context(context)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(context["schema_version"], RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(context["feature_id"], "MODEL-003")
        self.assertEqual(context["model_lane_id"], RESEARCHER_MODEL_LANE_ID)
        self.assertEqual(context["resolved_model_id"], RESEARCHER_MODEL_ID)
        self.assertEqual(context["model_policy_ref"], MODEL_LANE_POLICY_REF)
        self.assertEqual(context["prompt_template_id"], RESEARCHER_NLI_PROMPT_TEMPLATE_ID)
        self.assertEqual(context["prompt_template_sha256"], RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256)
        self.assertEqual(context["sidecar_schema_version"], RESEARCHER_SIDECAR_SCHEMA_VERSION)
        self.assertEqual(
            context["classification_output_schema_version"],
            RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
        )
        self.assertEqual(
            context["schema_metadata"]["classification_output_schema_version"],
            RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
        )
        self.assertFalse(context["runtime"]["model_call_performed"])
        self.assertIn("metadata_only_no_model_call", context["runtime_reason_codes"])
        self.assertIn("policy_default_model_selected", context["runtime_reason_codes"])
        self.assertEqual(context["fallback_reason_codes"], ["no_fallback_required"])
        self.assertIn("own_probability", context["forbidden_outputs"])
        self.assertIn("probability_interval", context["forbidden_outputs"])

    def test_disallowed_requested_model_falls_back_to_policy_default_with_reason_code(self) -> None:
        context = resolve_researcher_leaf_nli_model_context(requested_model_id="gpt-5.4-high")

        self.assertEqual(context["resolved_model_id"], RESEARCHER_MODEL_ID)
        self.assertIn(
            "requested_model_not_allowed_policy_default_used",
            context["runtime_reason_codes"],
        )
        self.assertEqual(context["fallback_reason_codes"], ["requested_model_not_allowed"])
        self.assertTrue(validate_researcher_model_execution_context(context).valid)

    def test_wrong_default_model_is_rejected(self) -> None:
        policy = self._policy()
        policy["lanes"][RESEARCHER_MODEL_LANE_ID]["default_model_id"] = "gpt-5.4-high"

        with self.assertRaisesRegex(ResearcherModelContextError, "default_model_id"):
            resolve_researcher_leaf_nli_model_context(model_lane_policy_path=self._write_policy(policy))

    def test_missing_required_artifact_fields_are_rejected(self) -> None:
        policy = self._policy()
        fields = policy["lanes"][RESEARCHER_MODEL_LANE_ID]["required_artifact_fields"]
        policy["lanes"][RESEARCHER_MODEL_LANE_ID]["required_artifact_fields"] = [
            field for field in fields if field != "classification_output_schema_version"
        ]

        with self.assertRaisesRegex(ResearcherModelContextError, "required artifact fields"):
            resolve_researcher_leaf_nli_model_context(model_lane_policy_path=self._write_policy(policy))

    def test_validation_rejects_model_call_or_digest_drift(self) -> None:
        context = resolve_researcher_leaf_nli_model_context()
        broken = copy.deepcopy(context)
        broken["runtime"]["model_call_performed"] = True

        validation = validate_researcher_model_execution_context(broken)

        self.assertFalse(validation.valid)
        joined = "; ".join(validation.errors)
        self.assertIn("model_call_performed", joined)
        self.assertIn("model_context_digest", joined)


if __name__ == "__main__":
    unittest.main()
