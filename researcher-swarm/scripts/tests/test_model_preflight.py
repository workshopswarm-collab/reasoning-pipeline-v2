#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from researcher_swarm.model_preflight import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_RERANKER_MODEL_ID,
    build_local_model_preflight_contract,
    evaluate_local_model_preflight,
    load_model_lane_policy,
    validate_local_model_preflight_report,
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


class LocalModelPreflightContractTest(unittest.TestCase):
    def _passing_observed_state(self) -> dict[str, Any]:
        return {
            "routes": {
                "ollama/local": {"available": True},
                "local/reranker": {"available": True},
            },
            "models": {
                DEFAULT_EMBEDDING_MODEL_ID: {
                    "available": True,
                    "smoke_test_status": "pass",
                    "capabilities": ["embedding"],
                },
                DEFAULT_RERANKER_MODEL_ID: {
                    "available": True,
                    "smoke_test_status": "pass",
                    "capabilities": ["rerank"],
                },
            },
            "resource_snapshot": {
                "available_memory_mb": 8192,
                "declared_model_memory_mb": 4096,
                "configured_embedding_batch_size": 16,
                "configured_reranker_candidates": 25,
                "configured_context_tokens": 4096,
                "download_attempted": False,
                "model_invocation_attempted": False,
            },
        }

    def test_default_preflight_is_unavailable_not_downloaded_or_invoked(self) -> None:
        report = evaluate_local_model_preflight(checked_at="2026-06-24T12:00:00+00:00")

        validation = validate_local_model_preflight_report(report)

        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(report["preflight_summary"]["live_retrieval_gate"], "unavailable")
        self.assertEqual(report["preflight_summary"]["unavailable_lane_count"], 2)
        self.assertIn("model_unavailable", report["preflight_summary"]["reason_counts"])
        self.assertEqual(report["side_effect_policy"]["downloads_models"], False)
        self.assertEqual(report["side_effect_policy"]["runs_long_model_tasks"], False)
        self.assertFalse(_contains_forbidden_key(report))

    def test_observed_embedding_and_reranker_pass_when_caps_are_within_contract(self) -> None:
        report = evaluate_local_model_preflight(
            observed_state=self._passing_observed_state(),
            checked_at="2026-06-24T12:00:00+00:00",
        )

        self.assertEqual(report["preflight_summary"]["live_retrieval_gate"], "pass")
        self.assertEqual(report["preflight_summary"]["passed_lane_count"], 2)
        self.assertTrue(report["preflight_summary"]["all_required_lanes_pass"])
        self.assertEqual(
            {slice_value["preflight_status"] for slice_value in report["local_model_preflight_slices"]},
            {"pass"},
        )

    def test_smoke_failure_or_resource_cap_violation_blocks_live_retrieval(self) -> None:
        observed_state = self._passing_observed_state()
        observed_state["models"][DEFAULT_RERANKER_MODEL_ID]["smoke_test_status"] = "failed"
        observed_state["resource_snapshot"]["configured_reranker_candidates"] = 99

        report = evaluate_local_model_preflight(observed_state=observed_state)
        reranker_slice = next(
            item for item in report["local_model_preflight_slices"] if item["lane_role"] == "reranker"
        )

        self.assertEqual(report["preflight_summary"]["live_retrieval_gate"], "block")
        self.assertIn("smoke_test_failed", reranker_slice["reason_codes"])
        self.assertIn("reranker_candidate_count_exceeds_cap", reranker_slice["reason_codes"])
        self.assertEqual(report["side_effect_policy"]["modifies_global_model_defaults"], False)

    def test_contract_reads_existing_local_embedding_lane_from_model_policy(self) -> None:
        model_policy = load_model_lane_policy(
            ROOT / "orchestrator" / "plans" / "autonomous-decomposition-swarm-model-lane-policy.json"
        )

        contract = build_local_model_preflight_contract(model_lane_policy=model_policy)
        embedding_lane = next(item for item in contract["lanes"] if item["lane_role"] == "embedding")

        self.assertEqual(embedding_lane["resolved_model_id"], "BAAI/bge-base-en-v1.5")
        self.assertEqual(embedding_lane["policy_source_lane_id"], "amrg_vector_embedding")
        self.assertEqual(contract["side_effect_policy"]["downloads_models"], False)


if __name__ == "__main__":
    unittest.main()
