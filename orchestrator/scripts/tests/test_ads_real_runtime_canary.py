#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_real_runtime_canary import (
    _model_runtime_evidence,
    _retrieval_runtime_evidence,
    build_current_audit_gap_summary,
    classify_qdt_runtime_state,
    classify_recent_run_failure,
)


def _write_json(root: Path, name: str, payload: dict) -> Path:
    path = root / name
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _runtime_payload(
    *,
    execution_status: str,
    reason_codes: list[str],
    repair_count: int = 0,
    schema_repair_diagnostics=None,
) -> dict:
    return {
        "schema_version": "model-runtime-call-summary/v1",
        "runtime_call_id": "runtime-call:qdt-live",
        "resolved_model_id": "gpt-5.5-high",
        "mode": "live",
        "fixture_mode": False,
        "model_call_performed": True,
        "model_executed": execution_status in {"succeeded", "accepted"},
        "execution_status": execution_status,
        "repair_count": repair_count,
        "retry_count": 0,
        "schema_repair_diagnostics": list(schema_repair_diagnostics or []),
        "runtime_reason_codes": reason_codes,
    }


class AdsRealRuntimeCanaryTest(unittest.TestCase):
    def test_boi_live_qdt_schema_semantic_drift_is_reported_as_live_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime_path = _write_json(
                root,
                "boi-qdt-runtime-rejected.json",
                _runtime_payload(
                    execution_status="failed_schema_validation",
                    reason_codes=[
                        "schema_repair_skipped_non_repairable_validation",
                        "invalid_required_evidence_purpose",
                        "invalid_leaf_purpose",
                        "missing_structural_validation_answerability_status",
                        "invalid_leaf_condition_scope",
                        "terminal_verification_leaf_misclassified",
                    ],
                ),
            )

            qdt_evidence = _model_runtime_evidence(
                [
                    {
                        "artifact_id": "artifact:boi-runtime",
                        "artifact_type": "model-runtime-call",
                        "path": str(runtime_path),
                    }
                ]
            )

        self.assertEqual(classify_qdt_runtime_state(qdt_evidence), "live_qdt_call_executed_output_rejected")
        summary = build_current_audit_gap_summary(qdt_evidence=qdt_evidence, retrieval_evidence={})
        taxonomy = summary["recent_run_failure_taxonomy"]
        self.assertEqual(taxonomy["qdt_runtime_state"], "live_qdt_call_executed_output_rejected")
        self.assertEqual(qdt_evidence["qdt_live_model_call_attempted_count"], 1)
        self.assertEqual(qdt_evidence["qdt_live_model_call_executed_count"], 1)
        self.assertEqual(qdt_evidence["qdt_live_output_schema_rejected_count"], 1)
        self.assertEqual(qdt_evidence["qdt_live_output_rejected_count"], 1)
        self.assertEqual(qdt_evidence["qdt_live_output_accepted_count"], 0)
        self.assertEqual(qdt_evidence["qdt_fixture_or_deterministic_count"], 0)
        self.assertEqual(taxonomy["qdt_live_model_call_attempted_count"], 1)
        self.assertEqual(taxonomy["qdt_live_model_call_executed_count"], 1)
        self.assertEqual(taxonomy["qdt_live_output_schema_rejected_count"], 1)
        self.assertEqual(taxonomy["qdt_live_output_rejected_count"], 1)
        self.assertEqual(taxonomy["qdt_live_output_accepted_count"], 0)
        self.assertEqual(taxonomy["qdt_fixture_or_deterministic_count"], 0)
        self.assertIn("terminal_verification_leaf_misclassified", taxonomy["qdt_runtime_reason_codes"])

    def test_deterministic_qdt_path_counts_as_fixture_or_deterministic(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            qdt_path = _write_json(
                root,
                "deterministic-qdt.json",
                {
                    "adapter_mode": "deterministic_decomposer_contract_adapter",
                    "required_leaf_questions": [
                        {
                            "leaf_id": "leaf-current-evidence",
                            "leaf_question": "What current evidence resolves the market?",
                        }
                    ],
                },
            )

            qdt_evidence = _model_runtime_evidence(
                [
                    {
                        "artifact_id": "artifact:deterministic-qdt",
                        "artifact_type": "question-decomposition",
                        "path": str(qdt_path),
                    }
                ]
            )

        taxonomy = build_current_audit_gap_summary(
            qdt_evidence=qdt_evidence,
            retrieval_evidence={},
        )["recent_run_failure_taxonomy"]
        self.assertEqual(classify_qdt_runtime_state(qdt_evidence), "qdt_fixture_or_deterministic_path")
        self.assertEqual(qdt_evidence["qdt_live_model_call_attempted_count"], 0)
        self.assertEqual(qdt_evidence["qdt_live_model_call_executed_count"], 0)
        self.assertEqual(qdt_evidence["qdt_live_output_schema_rejected_count"], 0)
        self.assertEqual(qdt_evidence["qdt_live_output_accepted_count"], 0)
        self.assertEqual(qdt_evidence["qdt_fixture_or_deterministic_count"], 1)
        self.assertEqual(taxonomy["qdt_runtime_state"], "qdt_fixture_or_deterministic_path")
        self.assertEqual(taxonomy["qdt_fixture_or_deterministic_count"], 1)

    def test_rbnz_analyst_consensus_temporal_role_drift_is_preserved(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime_path = _write_json(
                root,
                "rbnz-qdt-runtime-rejected.json",
                _runtime_payload(
                    execution_status="failed_schema_validation",
                    repair_count=1,
                    reason_codes=["analyst_consensus_leaf_wrong_temporal_role"],
                    schema_repair_diagnostics=[
                        {
                            "schema_version": "model-runtime-schema-repair-diagnostic/v1",
                            "repair_attempted": True,
                            "repair_decision": "mechanical_schema_repair_available",
                            "remaining_error_counts": {"terminal_temporal_role": 1},
                        }
                    ],
                ),
            )

            qdt_evidence = _model_runtime_evidence(
                [
                    {
                        "artifact_id": "artifact:rbnz-runtime",
                        "artifact_type": "model-runtime-call",
                        "path": str(runtime_path),
                    }
                ]
            )

        taxonomy = build_current_audit_gap_summary(
            qdt_evidence=qdt_evidence,
            retrieval_evidence={},
        )["recent_run_failure_taxonomy"]
        self.assertEqual(taxonomy["qdt_runtime_state"], "live_qdt_call_executed_output_rejected")
        self.assertIn("analyst_consensus_leaf_wrong_temporal_role", taxonomy["qdt_runtime_reason_codes"])
        self.assertEqual(taxonomy["qdt_runtime_execution_statuses"], ["failed_schema_validation"])
        self.assertEqual(
            qdt_evidence["runtime_results"][0]["schema_repair_diagnostics"][0]["repair_decision"],
            "mechanical_schema_repair_available",
        )

    def test_boi_source_populated_retrieval_without_certified_evidence_is_taxonomized(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            qdt_path = _write_json(
                root,
                "boi-qdt-accepted.json",
                {
                    "adapter_mode": "decomposer_model_runtime_live",
                    "runtime_call_ref": "runtime-call:qdt-live",
                    "model_execution_context": {
                        "resolved_model_id": "gpt-5.5-high",
                        "runtime_call_ref": "runtime-call:qdt-live",
                        "model_call_performed": True,
                        "model_executed": True,
                        "execution_status": "succeeded",
                    },
                    "research_coverage_graph": {
                        "market_temporal_state": "unresolved",
                        "coverage_dimensions": ["current_direct_evidence", "source_quality"],
                    },
                    "required_leaf_questions": [
                        {
                            "leaf_id": "leaf-boi-source-quality",
                            "leaf_question": "What current BOI source-quality evidence is available?",
                            "leaf_temporal_role": "pre_resolution_forecast_driver",
                            "purpose": "source_of_truth",
                            "required_evidence_fields": ["source_timestamp", "publisher_authority"],
                        }
                    ],
                },
            )
            runtime_path = _write_json(
                root,
                "boi-qdt-runtime-succeeded.json",
                _runtime_payload(execution_status="succeeded", reason_codes=[]),
            )
            retrieval_path = _write_json(
                root,
                "boi-retrieval-insufficient.json",
                {
                    "adapter_mode": "source_populated_live_retrieval_runtime",
                    "retrieval_runtime_summary": {
                        "runtime_mode": "live_retrieval_runtime",
                        "browser_search_executed": True,
                        "browser_search_status": "executed_with_candidates",
                        "search_candidate_url_count": 1,
                        "native_research_model_executed": True,
                        "native_candidate_url_count": 0,
                        "native_research_status": "executed_no_candidates",
                    },
                    "ads_retrieval_transport_diagnostics": {
                        "search_call_count": 1,
                        "search_candidate_url_count": 1,
                        "browser_search_executed": True,
                        "native_research_model_executed": True,
                        "native_research_status": "executed_no_candidates",
                    },
                    "search_candidate_urls": [{"url": "https://boi.org.il/en/markets/schedule"}],
                    "browser_retrieval_attempts": [
                        {"navigation_mode": "web_search", "url": "https://boi.org.il/en/markets/schedule"}
                    ],
                    "research_sufficiency_summary": {
                        "classification_dispatch_status": "blocked_insufficient_research",
                        "all_required_leaves_certified": False,
                    },
                    "retrieval_outcome_state": {
                        "retrieval_outcome": "insufficient_evidence",
                        "classification_dispatch_status": "blocked_insufficient_research",
                        "terminal_blocked": True,
                    },
                    "leaf_query_contexts": [
                        {
                            "leaf_id": "leaf-boi-source-quality",
                            "coverage_dimension": "source_quality",
                            "breadth_targets": {
                                "protected_primary_required": True,
                                "min_temporally_fresh_sources": 1,
                            },
                        }
                    ],
                    "leaf_retrieval_results": [
                        {
                            "leaf_id": "leaf-boi-source-quality",
                            "admitted_evidence_refs": ["evidence:boi-short"],
                            "selected_evidence_refs": ["evidence:boi-short"],
                        }
                    ],
                    "leaf_evidence_dockets": [
                        {
                            "leaf_id": "leaf-boi-source-quality",
                            "admitted_evidence_refs": ["evidence:boi-short"],
                        }
                    ],
                    "evidence_chunks": [
                        {
                            "evidence_ref": "evidence:boi-short",
                            "excerpt_policy": "redacted_snippet",
                            "excerpt_char_count": 140,
                        }
                    ],
                    "retrieval_evidence_provenance_slices": [
                        {
                            "evidence_ref": "evidence:boi-short",
                            "claim_family_ids": [],
                            "unknown_reason_codes": ["claim_family_unknown_not_counted"],
                        }
                    ],
                    "retrieval_breadth_coverage_slices": [],
                },
            )

            qdt_evidence = _model_runtime_evidence(
                [
                    {
                        "artifact_id": "artifact:boi-qdt",
                        "artifact_type": "question-decomposition",
                        "path": str(qdt_path),
                    },
                    {
                        "artifact_id": "artifact:boi-runtime",
                        "artifact_type": "model-runtime-call",
                        "path": str(runtime_path),
                    },
                ]
            )
            retrieval_evidence = _retrieval_runtime_evidence(
                [
                    {
                        "artifact_id": "artifact:boi-retrieval",
                        "artifact_type": "retrieval-packet",
                        "path": str(retrieval_path),
                    }
                ]
            )

        report = {
            "model_runtime_evidence": qdt_evidence,
            "retrieval_runtime_evidence": retrieval_evidence,
        }
        taxonomy = classify_recent_run_failure(report)
        self.assertEqual(taxonomy["qdt_runtime_state"], "live_qdt_call_executed_output_accepted")
        self.assertEqual(taxonomy["qdt_live_model_call_attempted_count"], 1)
        self.assertEqual(taxonomy["qdt_live_model_call_executed_count"], 1)
        self.assertEqual(taxonomy["qdt_live_output_schema_rejected_count"], 0)
        self.assertEqual(taxonomy["qdt_live_output_rejected_count"], 0)
        self.assertEqual(taxonomy["qdt_live_output_accepted_count"], 1)
        self.assertEqual(taxonomy["qdt_fixture_or_deterministic_count"], 0)
        self.assertEqual(taxonomy["retrieval_state"], "retrieval_source_populated_but_not_certified")
        self.assertEqual(taxonomy["native_state"], "native_research_executed_no_candidates")
        self.assertEqual(retrieval_evidence["source_populated_count"], 1)
        self.assertFalse(retrieval_evidence["live_acceptance_ok"])
        self.assertEqual(retrieval_evidence["meaningful_snippet_admitted_count"], 0)


if __name__ == "__main__":
    unittest.main()
