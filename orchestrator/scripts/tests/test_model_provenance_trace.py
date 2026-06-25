#!/usr/bin/env python3

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))

from ads_decomposer.handoff import resolve_decomposer_model_lane  # noqa: E402
from predquant.model_provenance_trace import (  # noqa: E402
    DECOMPOSER_MODEL_LANE_ID,
    EXPECTED_MODEL_ID,
    MODEL_PROVENANCE_TRACE_SCHEMA_VERSION,
    RESEARCHER_MODEL_LANE_ID,
    ModelProvenanceTraceError,
    build_model_provenance_trace,
    collect_model_execution_contexts,
    is_sha256_ref,
)
from predquant.training_trace import (  # noqa: E402
    TrainingTraceContext,
    TrainingTraceContractError,
    build_session5_minimal_training_trace,
)
from researcher_swarm.model_context import resolve_researcher_leaf_nli_model_context  # noqa: E402


def sha(char: str) -> str:
    return "sha256:" + char * 64


class ModelProvenanceTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.decomposer_context = resolve_decomposer_model_lane(
            input_manifest_ids=["artifact:case", "artifact:evidence"],
        )
        self.researcher_context = resolve_researcher_leaf_nli_model_context()
        self.decomposer_record = {
            "model_execution_context": self.decomposer_context,
            "input_artifact_hashes": {
                "artifact:case": sha("a"),
                "artifact:evidence": sha("b"),
            },
            "output_artifact_id": "artifact:qdt",
            "output_artifact_hash": sha("c"),
        }
        self.researcher_record = {
            "model_execution_context": self.researcher_context,
            "input_artifact_hashes": {
                "artifact:qdt": sha("c"),
                "artifact:retrieval": sha("d"),
            },
            "output_artifact_id": "artifact:researcher-sidecar",
            "output_artifact_hash": sha("e"),
            "output_schema_version": "researcher-sidecar/v2",
        }

    def session5_context(self) -> TrainingTraceContext:
        return TrainingTraceContext(
            case_id="case-1",
            case_key="case:key:1",
            dispatch_id="dispatch-1",
            run_id="run-1",
            forecast_timestamp="2026-06-25T12:00:00+00:00",
        )

    def session5_manifests(self) -> list[dict[str, str]]:
        return [
            {
                "artifact_id": "artifact:researcher-sidecar",
                "sha256": sha("e"),
                "stage": "researcher_classification",
                "artifact_type": "researcher-sidecar",
            },
            {
                "artifact_id": "artifact:scae",
                "sha256": sha("f"),
                "stage": "scae",
                "artifact_type": "scae-ledger",
            },
            {
                "artifact_id": "artifact:decision",
                "sha256": sha("0"),
                "stage": "decision",
                "artifact_type": "decision-context",
            },
        ]

    def test_builds_trace_for_decomposer_and_researcher_contexts(self) -> None:
        trace = build_model_provenance_trace(
            model_execution_contexts=[self.decomposer_record, self.researcher_record],
        )

        self.assertEqual(trace["schema_version"], MODEL_PROVENANCE_TRACE_SCHEMA_VERSION)
        self.assertEqual(trace["context_count"], 2)
        self.assertEqual(trace["resolved_model_ids"][DECOMPOSER_MODEL_LANE_ID], EXPECTED_MODEL_ID)
        self.assertEqual(trace["resolved_model_ids"][RESEARCHER_MODEL_LANE_ID], EXPECTED_MODEL_ID)
        self.assertEqual(trace["live_authority"], "none")
        self.assertFalse(trace["live_forecast_authority"])
        self.assertTrue(trace["no_probability_authority"])
        self.assertTrue(trace["no_model_call_performed_by_trace_helper"])
        self.assertTrue(is_sha256_ref(trace["model_provenance_trace_digest"]))

        by_lane = {item["model_lane_id"]: item for item in trace["model_execution_contexts"]}
        self.assertEqual(by_lane[DECOMPOSER_MODEL_LANE_ID]["source_feature_id"], "MODEL-002")
        self.assertEqual(by_lane[RESEARCHER_MODEL_LANE_ID]["source_feature_id"], "MODEL-003")
        self.assertEqual(
            by_lane[DECOMPOSER_MODEL_LANE_ID]["prompt_template_sha256"],
            self.decomposer_context["prompt_template_sha256"],
        )
        self.assertEqual(
            by_lane[RESEARCHER_MODEL_LANE_ID]["source_model_context_digest"],
            self.researcher_context["model_context_digest"],
        )
        self.assertEqual(
            by_lane[RESEARCHER_MODEL_LANE_ID]["schema_versions"]["sidecar_schema_version"],
            "researcher-sidecar/v2",
        )

    def test_session5_minimal_trace_can_embed_model_provenance_metadata(self) -> None:
        trace = build_session5_minimal_training_trace(
            context=self.session5_context(),
            artifact_manifests=self.session5_manifests(),
            model_execution_contexts=[self.decomposer_record, self.researcher_record],
        )

        provenance = trace["metadata"]["model_provenance_trace"]
        self.assertEqual(provenance["schema_version"], MODEL_PROVENANCE_TRACE_SCHEMA_VERSION)
        self.assertEqual(set(provenance["lane_ids"]), {DECOMPOSER_MODEL_LANE_ID, RESEARCHER_MODEL_LANE_ID})
        self.assertEqual(trace["live_authority"], "none")
        self.assertFalse(trace["live_forecast_authority"])

    def test_rejects_missing_or_non_sha256_prompt_template_hashes(self) -> None:
        missing = copy.deepcopy(self.decomposer_record)
        del missing["model_execution_context"]["prompt_template_sha256"]
        with self.assertRaisesRegex(ModelProvenanceTraceError, "prompt_template_sha256"):
            build_model_provenance_trace(model_execution_contexts=[missing])

        non_sha = copy.deepcopy(self.researcher_record)
        non_sha["model_execution_context"]["prompt_template_sha256"] = "sha1:" + "1" * 40
        with self.assertRaisesRegex(ModelProvenanceTraceError, "prompt_template_sha256"):
            build_model_provenance_trace(model_execution_contexts=[non_sha])

        short_sha = copy.deepcopy(self.researcher_record)
        short_sha["model_execution_context"]["prompt_template_sha256"] = "sha256:fixture"
        with self.assertRaisesRegex(TrainingTraceContractError, "prompt_template_sha256"):
            build_session5_minimal_training_trace(
                context=self.session5_context(),
                artifact_manifests=self.session5_manifests(),
                model_execution_contexts=[short_sha],
            )

    def test_rejects_live_model_calls_or_probability_authority(self) -> None:
        live_call = copy.deepcopy(self.researcher_record)
        live_call["model_execution_context"]["runtime"]["model_call_performed"] = True
        with self.assertRaisesRegex(ModelProvenanceTraceError, "model_call_performed"):
            build_model_provenance_trace(model_execution_contexts=[live_call])

        probability_authority = copy.deepcopy(self.researcher_record)
        probability_authority["model_execution_context"]["authority_boundary"][
            "model_outputs_may_author_probability"
        ] = True
        with self.assertRaisesRegex(ModelProvenanceTraceError, "model_outputs_may_author_probability"):
            build_model_provenance_trace(model_execution_contexts=[probability_authority])

        active_probability = copy.deepcopy(self.decomposer_record)
        active_probability["model_execution_context"]["leaf_probability"] = 0.5
        with self.assertRaisesRegex(ModelProvenanceTraceError, "leaf_probability"):
            build_model_provenance_trace(model_execution_contexts=[active_probability])

    def test_collects_known_model_execution_contexts_from_artifacts(self) -> None:
        artifacts = [
            {"artifact_type": "question_decomposition", "model_execution_context": self.decomposer_context},
            {"artifact_type": "researcher-sidecar", "payload": {"model_execution_context": self.researcher_context}},
            {"artifact_type": "unrelated", "model_execution_context": {"model_lane_id": "amrg_model_assist"}},
        ]

        contexts = collect_model_execution_contexts(artifacts)

        self.assertEqual(
            [context["model_lane_id"] for context in contexts],
            [DECOMPOSER_MODEL_LANE_ID, RESEARCHER_MODEL_LANE_ID],
        )


if __name__ == "__main__":
    unittest.main()
