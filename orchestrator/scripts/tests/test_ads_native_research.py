#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))

from ads_decomposer.model_runtime import (  # noqa: E402
    MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
    ModelRuntimeError,
)
from predquant.ads_native_research import NativeResearchCandidateProvider  # noqa: E402


class AdsNativeResearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "leaf_id": "leaf-native",
            "parent_branch_id": "branch-native",
            "query_context_ref": "query-context:native",
            "question_text": "Find source URLs for the native research leaf.",
            "purpose": "direct_evidence",
        }
        self.variant = {
            "query_variant_id": "query-variant:native",
            "query_role": "primary_leaf_retrieval",
            "query_text": "native research source URL",
            "query_text_sha256": "sha256:native",
        }

    def test_native_provider_uses_model_runtime_retry_diagnostics(self) -> None:
        calls: list[dict] = []
        sleep_calls: list[float] = []

        def transport(request: dict) -> dict:
            calls.append(request)
            if len(calls) == 1:
                raise TimeoutError("temporary native research timeout")
            return {
                "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
                "response_payload": {
                    "native_research_candidates": [
                        {
                            "url": "https://native.example/source",
                            "source_label": "Native source",
                            "why_it_may_matter": "May contain direct evidence.",
                            "candidate_claim_text": "Candidate claim only.",
                        }
                    ]
                },
                "provider_status": {"status": "completed"},
            }

        provider = NativeResearchCandidateProvider(transport=transport, sleep_fn=sleep_calls.append)

        result = provider(self.context, self.variant)

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(sleep_calls), 1)
        self.assertEqual(result["native_research_candidates"][0]["url"], "https://native.example/source")
        runtime = result["model_runtime_call"]
        self.assertEqual(runtime["model_lane_id"], "native_research_candidate_discovery")
        self.assertEqual(runtime["resolved_model_id"], "gpt-5.5-high")
        self.assertEqual(runtime["execution_status"], "succeeded")
        self.assertEqual(runtime["retry_count"], 1)
        self.assertEqual(
            [item["event"] for item in runtime["retry_diagnostics"]],
            ["local_retry", "retry_succeeded"],
        )

    def test_native_provider_repairs_single_candidate_object(self) -> None:
        provider = NativeResearchCandidateProvider(
            mode="fixture",
            fixture_response={
                "url": "https://native.example/repaired",
                "source_label": "Native source",
                "source_type_hint": "official_site_or_independent_reporting",
                "reason": "May contain source material for this leaf.",
                "candidate_claim_text": "Candidate claim only.",
            },
        )

        result = provider(self.context, self.variant)

        self.assertEqual(result["native_research_candidates"][0]["url"], "https://native.example/repaired")
        runtime = result["model_runtime_call"]
        self.assertEqual(runtime["execution_status"], "succeeded")
        self.assertEqual(runtime["repair_count"], 1)
        self.assertIn("schema_repair_attempted", runtime["runtime_reason_codes"])
        self.assertTrue(runtime["schema_repair_diagnostics"][0]["repair_attempted"])
        self.assertEqual(runtime["schema_repair_diagnostics"][0]["remaining_errors"], [])

    def test_native_provider_rejects_forbidden_authority_fields(self) -> None:
        provider = NativeResearchCandidateProvider(
            mode="fixture",
            fixture_response={
                "native_research_candidates": [
                    {
                        "url": "https://native.example/source",
                        "source_class": "official_or_primary",
                    }
                ]
            },
        )

        with self.assertRaises(ModelRuntimeError) as caught:
            provider(self.context, self.variant)

        runtime = caught.exception.runtime_call
        self.assertIsNotNone(runtime)
        self.assertEqual(runtime["execution_status"], "failed_schema_validation")
        self.assertIn("source_class", " ".join(runtime["runtime_reason_codes"]))


if __name__ == "__main__":
    unittest.main()
