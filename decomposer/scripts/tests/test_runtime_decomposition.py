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
sys.path.insert(0, str(ROOT / "decomposer" / "scripts" / "bin"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from ads_decomposer.model_runtime import (  # noqa: E402
    MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
    ModelRuntimeError,
)
from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import (  # noqa: E402
    ALLOWED_ANSWERABILITY_STATUSES,
    ALLOWED_CONDITION_SCOPES,
    ALLOWED_LEAF_TEMPORAL_ROLES,
    ALLOWED_PURPOSES,
    REQUIRED_LEAF_FIELDS,
    validate_question_decomposition,
)
from run_decomposition import (  # noqa: E402
    build_decomposition_prompt_payload,
    build_question_decomposition_from_handoff,
    build_question_specific_fixture_response,
    build_qdt_schema_crib,
)


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
                "provider_route": "openclaw_codex_oauth/decomposer",
                "oauth_route_required": True,
                "runtime_agent_id": "decomposer",
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
        self.assertEqual(qdt["research_coverage_check"]["status"], "passed")
        self.assertIn("research_coverage_graph", qdt)

    def test_prompt_payload_contains_phase3_temporal_contract(self) -> None:
        payload = build_decomposition_prompt_payload(self._handoff(), payloads={})
        instruction_text = json.dumps(payload["instruction_blocks"], sort_keys=True)

        self.assertEqual(payload["prompt_schema_version"], "decomposer-qdt-prompt-input/v1")
        self.assertEqual(payload["market_temporal_state"], "unresolved")
        self.assertEqual(payload["source_cutoff_timestamp"], self._handoff()["source_cutoff_timestamp"])
        self.assertIn("pre-resolution forecast research", instruction_text)
        self.assertIn("terminal_verification", instruction_text)
        self.assertIn("weak_context_only=true", instruction_text)
        self.assertIn("Schema repair may normalize shape", instruction_text)
        self.assertEqual(
            payload["instructions"]["required_leaf_partitions"],
            [
                "contract_guard_leaf_ids",
                "material_question_leaf_ids",
                "material_unknowns",
                "overlap_groups",
                "terminal_verification_leaf_ids",
                "dispatchable_pre_resolution_leaf_ids",
            ],
        )

    def test_prompt_payload_embeds_validator_schema_crib(self) -> None:
        payload = build_decomposition_prompt_payload(self._handoff(), payloads={})
        crib = payload["qdt_schema_crib"]
        direct_crib = build_qdt_schema_crib()
        block_ids = {block["block_id"] for block in payload["instruction_blocks"]}

        self.assertEqual(crib, direct_crib)
        self.assertEqual(crib["allowed_purposes"], sorted(ALLOWED_PURPOSES))
        self.assertEqual(crib["allowed_required_evidence_purposes"], sorted(ALLOWED_PURPOSES))
        self.assertEqual(crib["allowed_leaf_condition_scopes"], sorted(ALLOWED_CONDITION_SCOPES))
        self.assertEqual(crib["allowed_leaf_temporal_roles"], sorted(ALLOWED_LEAF_TEMPORAL_ROLES))
        self.assertEqual(crib["allowed_answerability_statuses"], sorted(ALLOWED_ANSWERABILITY_STATUSES))
        self.assertEqual(crib["required_leaf_fields"], sorted(REQUIRED_LEAF_FIELDS))
        self.assertIn("answerability_status", crib["required_leaf_structural_validation_fields"])
        self.assertIn("qdt_schema_crib_contract", block_ids)
        self.assertEqual(payload["instructions"]["schema_crib_ref"], "qdt_schema_crib")

    def test_live_transport_builds_question_specific_qdt_without_fixture_mode(self) -> None:
        handoff = self._handoff()
        model_response = build_question_specific_fixture_response(handoff)
        requests: list[dict] = []

        def transport(payload: dict) -> dict:
            requests.append(payload)
            self.assertEqual(payload["provider_route"], "openclaw_codex_oauth/decomposer")
            self.assertEqual(payload["prompt_template_id"], DECOMPOSER_PROMPT_TEMPLATE_ID)
            self.assertEqual(payload["request_payload"]["macro_question"], handoff["macro_question"])
            return {
                "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
                "response_payload": model_response,
                "token_usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
                "provider_status": {"finish_reason": "stop"},
            }

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="live",
            transport=transport,
        )

        self.assertEqual(len(requests), 1)
        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(qdt["adapter_mode"], "decomposer_model_runtime_live")
        self.assertFalse(qdt["model_execution_context"]["fixture_mode"])
        self.assertTrue(qdt["model_execution_context"]["model_executed"])
        self.assertEqual(qdt["model_execution_context"]["resolved_model_id"], "gpt-5.5-high")
        self.assertEqual(qdt["model_execution_context"]["token_usage"]["total_tokens"], 30)
        self.assertEqual(runtime["mode"], "live")
        self.assertFalse(runtime["fixture_mode"])
        self.assertIn("live_transport_called", runtime["runtime_reason_codes"])

    def test_schema_repair_is_bounded_before_qdt_materialization(self) -> None:
        handoff = self._handoff()
        repairable = build_question_specific_fixture_response(handoff)
        repairable["leaves"] = repairable.pop("required_leaf_questions")

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=repairable,
        )

        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(runtime["repair_count"], 1)
        self.assertEqual(qdt["model_execution_context"]["repair_count"], 1)

    def test_runtime_accepts_large_response_for_canonical_leaf_budget_validation(self) -> None:
        handoff = self._handoff()
        response = build_question_specific_fixture_response(handoff)
        base_leaf = response["required_leaf_questions"][0]
        base_branch = response["branches"][0]
        additional_questions = [
            (
                "Which unresolved engineering blockers could prevent Acme from shipping the Atlas update "
                "before July 2026?"
            ),
            (
                "What public launch communications from Acme currently support or weaken a before-July "
                "Atlas update release?"
            ),
            (
                "How do dependency, vendor, or platform milestones affect the remaining Atlas update "
                "delivery window?"
            ),
            (
                "Which beta, release-candidate, or customer rollout signals show progress toward an Atlas "
                "update launch?"
            ),
            (
                "What explicit counterevidence indicates Acme may delay the Atlas update beyond the market "
                "deadline?"
            ),
            (
                "How have Acme's comparable roadmap commitments performed when similar release windows were "
                "announced?"
            ),
            (
                "Which source-quality gaps remain after checking Acme-owned sources and credible external "
                "coverage?"
            ),
        ]
        for offset, question in enumerate(additional_questions, start=1):
            next_index = len(response["required_leaf_questions"]) + 1
            leaf = dict(base_leaf)
            leaf["leaf_id"] = f"leaf-extra-pre-resolution-{offset}"
            leaf["question_text"] = question
            leaf["leaf_question"] = leaf["question_text"]
            leaf["coverage_dimension"] = f"additional_driver_{next_index}"
            leaf["research_factor"] = f"driver_signal_{next_index}"
            leaf["market_component_terms"] = ["Acme", "Atlas update", f"driver {next_index}"]
            leaf["classification_targets"] = [f"driver_{next_index}_signal_strength"]
            leaf["evidence_requirements"] = [f"current evidence about driver {next_index}"]
            leaf["sufficiency_criteria"] = [f"driver {next_index} evidence is current and source-backed"]
            leaf["specificity_evidence"] = {
                "market_terms_used": ["Acme", "Atlas update"],
                "why_this_must_be_investigated": f"Driver {next_index} could change pre-resolution delivery odds.",
            }
            response["required_leaf_questions"].append(leaf)
            base_branch.setdefault("leaf_ids", []).append(leaf["leaf_id"])

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=response,
        )

        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertGreater(len(qdt["required_leaf_questions"]), 10)
        budget = qdt["leaf_budget_decision"]
        self.assertGreater(budget["effective_leaf_budget"], budget["compact_default_leaf_budget"])
        self.assertTrue(budget["hierarchical_branch_ledger_required"])
        self.assertEqual(runtime["execution_status"], "succeeded")

    def test_schema_repair_does_not_convert_semantic_invalid_output(self) -> None:
        handoff = self._handoff()
        bad_response = build_question_specific_fixture_response(handoff)
        for leaf in bad_response["required_leaf_questions"]:
            question = (
                "What did the final official result say about whether Acme shipped "
                "the Atlas update before July 2026?"
            )
            leaf["question_text"] = question
            leaf["leaf_question"] = question

        with self.assertRaises(ModelRuntimeError) as raised:
            build_question_decomposition_from_handoff(
                handoff,
                runtime_mode="fixture",
                fixture_response=bad_response,
            )

        runtime = raised.exception.runtime_call
        self.assertIsInstance(runtime, dict)
        self.assertEqual(runtime["execution_status"], "failed_schema_validation")
        self.assertEqual(runtime["repair_count"], 0)
        self.assertIn("schema_repair_skipped_non_repairable_validation", runtime["runtime_reason_codes"])
        diagnostic = runtime["schema_repair_diagnostics"][0]
        self.assertFalse(diagnostic["repair_attempted"])
        self.assertEqual(diagnostic["repair_skipped_reason"], "no_mechanical_schema_errors")
        self.assertGreater(diagnostic["pre_repair_error_counts"]["terminal_temporal_role"], 0)
        self.assertIn(
            "terminal_verification_dominates_unresolved_forecast_qdt",
            "; ".join(runtime["runtime_reason_codes"]),
        )

    def test_mixed_schema_and_terminal_semantic_errors_repair_once_then_fail_closed(self) -> None:
        handoff = self._handoff()
        bad_response = build_question_specific_fixture_response(handoff)
        bad_response["branches"][0]["required_evidence_purposes"] = ["official_resolution"]
        first_leaf = bad_response["required_leaf_questions"][0]
        first_leaf["purpose"] = "official_resolution"
        first_leaf["leaf_condition_scope"] = "if_candidate_files"
        first_leaf["structural_validation"].pop("answerability_status")
        for leaf in bad_response["required_leaf_questions"]:
            question = (
                "What did the final official result say about whether Acme shipped "
                "the Atlas update before July 2026?"
            )
            leaf["question_text"] = question
            leaf["leaf_question"] = question

        with self.assertRaises(ModelRuntimeError) as raised:
            build_question_decomposition_from_handoff(
                handoff,
                runtime_mode="fixture",
                fixture_response=bad_response,
            )

        runtime = raised.exception.runtime_call
        self.assertIsInstance(runtime, dict)
        self.assertEqual(runtime["execution_status"], "failed_schema_validation")
        self.assertEqual(runtime["repair_count"], 1)
        self.assertIn("schema_repair_attempted", runtime["runtime_reason_codes"])
        self.assertIn("schema_repair_remaining_terminal_temporal_role", runtime["runtime_reason_codes"])
        diagnostic = runtime["schema_repair_diagnostics"][0]
        self.assertTrue(diagnostic["repair_attempted"])
        self.assertGreater(diagnostic["pre_repair_error_counts"]["mechanical_schema"], 0)
        self.assertGreater(diagnostic["pre_repair_error_counts"]["terminal_temporal_role"], 0)
        self.assertEqual(diagnostic["remaining_error_counts"]["mechanical_schema"], 0)
        self.assertGreater(diagnostic["remaining_error_counts"]["terminal_temporal_role"], 0)
        self.assertTrue(
            any(path.endswith(".purpose") for path in diagnostic["repaired_fields"]),
            diagnostic["repaired_fields"],
        )

    def test_unresolved_election_fixture_stays_pre_resolution_dispatchable(self) -> None:
        handoff = self._handoff()
        handoff["case_id"] = "case-victor-marx-runtime"
        handoff["case_key"] = "polymarket:825858"
        handoff["dispatch_id"] = "dispatch-victor-marx-runtime"
        handoff["macro_question"] = (
            "Will Victor Marx win the 2026 Colorado Governor Republican primary election?"
        )
        model_response = build_question_specific_fixture_response(handoff)

        qdt, _runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=model_response,
        )

        graph = qdt["research_coverage_graph"]
        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(qdt["research_coverage_check"]["status"], "passed")
        self.assertEqual(graph["market_temporal_state"], "unresolved")
        self.assertFalse(graph["terminal_verification_leaf_ids"])
        self.assertEqual(
            sorted(graph["dispatchable_pre_resolution_leaf_ids"]),
            sorted(leaf["leaf_id"] for leaf in qdt["required_leaf_questions"]),
        )

    def test_schema_repair_normalizes_model_enum_and_structural_drift(self) -> None:
        handoff = self._handoff()
        repairable = build_question_specific_fixture_response(handoff)
        repairable["branches"][0]["required_evidence_purposes"] = [
            "official_resolution",
            "candidate_status",
        ]
        repairable["required_leaf_questions"][0]["purpose"] = "official_resolution"
        repairable["required_leaf_questions"][0]["structural_validation"].pop("answerability_status")
        repairable["required_leaf_questions"][1]["purpose"] = "candidate_status"
        repairable["required_leaf_questions"][1]["leaf_condition_scope"] = "if_candidate_files"
        repairable["required_leaf_questions"][1]["structural_validation"].pop("answerability_status")
        for leaf in repairable["required_leaf_questions"]:
            leaf["research_sufficiency_requirements"] = ["model emitted a list instead of the contract object"]

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=repairable,
        )

        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(runtime["repair_count"], 1)
        purposes = {leaf["purpose"] for leaf in qdt["required_leaf_questions"]}
        self.assertIn("source_of_truth", purposes)
        self.assertIn("direct_evidence", purposes)
        self.assertTrue(
            all(
                leaf["structural_validation"]["answerability_status"] == "answerable"
                for leaf in qdt["required_leaf_questions"]
            )
        )

    def test_boi_recent_schema_drift_fixture_repairs_to_contract(self) -> None:
        handoff = self._handoff()
        handoff["case_id"] = "case-boi-runtime"
        handoff["case_key"] = "polymarket:boi-2026"
        handoff["macro_question"] = "Will the BOI candidate formally file before the market deadline?"
        repairable = build_question_specific_fixture_response(handoff)
        repairable["branches"][0]["required_evidence_purposes"] = [
            "official_resolution",
            "candidate_status",
        ]
        repairable["required_leaf_questions"][0]["purpose"] = "official_resolution"
        repairable["required_leaf_questions"][0]["structural_validation"].pop("answerability_status")
        repairable["required_leaf_questions"][1]["purpose"] = "candidate_status"
        repairable["required_leaf_questions"][1]["leaf_condition_scope"] = "if_candidate_files"
        repairable["required_leaf_questions"][1]["structural_validation"].pop("answerability_status")

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=repairable,
        )

        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(runtime["repair_count"], 1)
        self.assertTrue(
            set(qdt["branches"][0]["required_evidence_purposes"]).issubset(ALLOWED_PURPOSES)
        )
        for leaf in qdt["required_leaf_questions"]:
            self.assertIn(leaf["purpose"], ALLOWED_PURPOSES)
            self.assertIn(leaf["leaf_condition_scope"], ALLOWED_CONDITION_SCOPES)
            self.assertIn(
                leaf["structural_validation"]["answerability_status"],
                ALLOWED_ANSWERABILITY_STATUSES,
            )
            self.assertIsInstance(leaf["research_sufficiency_requirements"], dict)

    def test_rbnz_analyst_consensus_temporal_role_fixture_repairs_to_source_quality(self) -> None:
        handoff = self._handoff()
        handoff["case_id"] = "case-rbnz-runtime"
        handoff["case_key"] = "polymarket:rbnz-july-ocr"
        handoff["macro_question"] = "Will the RBNZ cut the OCR at the July 2026 meeting?"
        repairable = build_question_specific_fixture_response(handoff)
        leaf = repairable["required_leaf_questions"][0]
        question = (
            "What is the analyst consensus or economist survey expectation for the "
            "RBNZ July OCR decision before cutoff?"
        )
        leaf["question_text"] = question
        leaf["leaf_question"] = question
        leaf["purpose"] = "resolution_mechanics"
        leaf["coverage_dimension"] = "resolution_mechanics"
        leaf["leaf_temporal_role"] = "resolution_mechanics"
        leaf["required_evidence_fields"] = ["analyst_consensus", "economist_survey_expectation"]
        leaf.pop("research_sufficiency_requirements", None)

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=repairable,
        )

        repaired_leaf = next(item for item in qdt["required_leaf_questions"] if item["leaf_id"] == leaf["leaf_id"])
        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(runtime["repair_count"], 1)
        self.assertEqual(repaired_leaf["purpose"], "direct_evidence")
        self.assertEqual(repaired_leaf["coverage_dimension"], "source_quality")
        self.assertEqual(repaired_leaf["leaf_temporal_role"], "pre_resolution_forecast_driver")

    def test_invalid_related_context_usage_status_falls_back_to_handoff(self) -> None:
        handoff = self._handoff()
        repairable = build_question_specific_fixture_response(handoff)
        repairable["related_market_context_usage"] = {
            "usage_status": "used_as_weak_context",
            "related_context_artifact_ref": "artifact:model-drift-ref",
            "amrg_usage_refs": [],
            "weak_context_only": True,
            "anchor_dependency_status": "model_declared",
        }
        repairable["related_market_context_usage"]["amrg_usage_refs"] = ["hint-a"]

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=repairable,
        )

        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(runtime["execution_status"], "succeeded")
        usage = qdt["related_market_context_usage"]
        self.assertEqual(usage["usage_status"], "related_context_used")
        self.assertEqual(usage["related_context_artifact_ref"], "artifact:amrg-runtime-1")
        self.assertEqual(usage["amrg_usage_refs"], ["hint-a"])

    def test_schema_repair_unwraps_nested_model_candidate_payload(self) -> None:
        handoff = self._handoff()
        nested = {
            "qdt_candidate": build_question_specific_fixture_response(handoff),
            "notes": "model wrapped the compact candidate",
        }

        qdt, runtime = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode="fixture",
            fixture_response=nested,
        )

        self.assertTrue(validate_question_decomposition(qdt).valid)
        self.assertEqual(runtime["repair_count"], 1)
        self.assertEqual(qdt["adapter_mode"], "decomposer_model_runtime_fixture")

    def test_cli_live_mode_accepts_transport_response_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            handoff = self._handoff()
            handoff_path = temp / "handoff.json"
            qdt_path = temp / "question-decomposition.json"
            runtime_path = temp / "model-runtime-call.json"
            transport_path = temp / "transport-response.json"
            handoff_path.write_text(json.dumps(handoff, sort_keys=True), encoding="utf-8")
            transport_path.write_text(
                json.dumps(
                    {
                        "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
                        "response_payload": build_question_specific_fixture_response(handoff),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

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
                    "live",
                    "--transport-response",
                    str(transport_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            qdt = json.loads(qdt_path.read_text(encoding="utf-8"))
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))

        self.assertEqual(qdt["adapter_mode"], "decomposer_model_runtime_live")
        self.assertFalse(qdt["model_execution_context"]["fixture_mode"])
        self.assertEqual(runtime["mode"], "live")
        self.assertFalse(runtime["fixture_mode"])

    def test_amrg_operator_metadata_uses_schema_stable_slices(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            related_path = temp / "related-context.json"
            related_path.write_text(
                json.dumps(
                    {
                        "artifact_type": "related_live_market_context",
                        "amrg_decomposer_context": {
                            "schema_version": "amrg-decomposer-context/v1",
                            "context_ref": "artifact:amrg-runtime-1",
                            "hints": [
                                {
                                    "hint_ref": "hint-1",
                                    "hint_category": "weak_context_hint",
                                    "source_market_ref": "polymarket:related-1",
                                    "relation_type": "entity_match",
                                    "effect_status": "weak_context_only",
                                    "allowed_use": ["decomposition_context_hint"],
                                    "prohibited_use": [
                                        "qdt_selection",
                                        "qdt_repair",
                                        "probability_authority",
                                        "scae_delta",
                                    ],
                                    "freshness_status": "current",
                                    "candidate_leaf_relevance": "diagnostic_only",
                                },
                                {
                                    "hint_ref": "hint-2",
                                    "hint_category": "weak_context_hint",
                                    "source_market_ref": "polymarket:related-2",
                                    "relation_type": "generic_theme",
                                    "effect_status": "weak_context_only",
                                    "allowed_use": ["decomposition_context_hint"],
                                    "prohibited_use": [
                                        "qdt_selection",
                                        "qdt_repair",
                                        "probability_authority",
                                        "scae_delta",
                                    ],
                                    "freshness_status": "current",
                                    "candidate_leaf_relevance": "diagnostic_only",
                                }
                            ],
                            "operator_metadata": {
                                "forbidden_qdt_uses": [
                                    "probability_authority",
                                    "qdt_selection",
                                    "qdt_repair",
                                    "scae_delta",
                                ]
                            },
                            "authority": "context_hints_only_no_forecast_or_selection_authority",
                        },
                        "relationship_edges": [{"edge_id": "hint-1"}, {"edge_id": "hint-2"}],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            handoff = self._handoff()
            handoff["artifact_refs"]["related_market_context"]["path"] = str(related_path)
            model_response = build_question_specific_fixture_response(handoff)
            model_response["required_leaf_questions"][0]["leaf_id"] = "leaf-current-decision-status"
            model_response["branches"][0]["leaf_ids"][0] = "leaf-current-decision-status"
            model_response["required_leaf_questions"][0]["amrg_usage_refs"] = ["hint-1"]
            model_response["branches"][0]["amrg_usage_refs"] = ["hint-1"]
            qdt, _runtime = build_question_decomposition_from_handoff(
                handoff,
                runtime_mode="fixture",
                fixture_response=model_response,
            )

        metadata = qdt["amrg_operator_metadata"]
        self.assertNotIn("leaf_hint_refs", metadata)
        self.assertNotIn("branch_hint_refs", metadata)
        self.assertIn("leaf_hint_ref_slices", metadata)
        self.assertTrue(
            all("leaf-current-decision-status" == item["leaf_id"] for item in metadata["leaf_hint_ref_slices"])
        )
        consumption = {item["hint_ref"]: item for item in metadata["hint_consumption_slices"]}
        self.assertTrue(consumption["hint-1"]["decomposer_consumed"])
        self.assertEqual(consumption["hint-1"]["consumed_by_leaf_ids"], ["leaf-current-decision-status"])
        self.assertEqual(consumption["hint-1"]["consumed_by_branch_ids"], [qdt["branches"][0]["branch_id"]])
        self.assertEqual(consumption["hint-1"]["ignored_reason_codes"], [])
        self.assertEqual(consumption["hint-1"]["effect_status"], "context_only_no_authority")
        self.assertFalse(consumption["hint-2"]["decomposer_consumed"])
        self.assertEqual(
            consumption["hint-2"]["ignored_reason_codes"],
            ["not_referenced_by_qdt_branch_or_leaf"],
        )
        self.assertIn("probability_authority", consumption["hint-2"]["forbidden_effects"])


if __name__ == "__main__":
    unittest.main()
