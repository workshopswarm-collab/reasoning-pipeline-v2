#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "researcher-swarm" / "scripts"))
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import build_fixture_qdt_candidate, select_qdt_candidate  # noqa: E402
from researcher_swarm.assignments import (  # noqa: E402
    DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS,
    LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION,
    LeafResearchAssignmentError,
    build_leaf_research_assignments,
    compute_leaf_research_assignment_digest,
    validate_leaf_research_assignment,
)
from researcher_swarm.classification import (  # noqa: E402
    FORBIDDEN_OUTPUT_FIELDS,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
)
from researcher_swarm.model_context import (  # noqa: E402
    RESEARCHER_MODEL_ID,
    RESEARCHER_MODEL_LANE_ID,
    RESEARCHER_PROVIDER_ROUTE,
    RESEARCHER_PROVIDER_MODEL_KEY,
    RESEARCHER_RUNTIME_AGENT_ID,
)
from researcher_swarm.openclaw_runtime import parse_openclaw_researcher_swarm_stdout  # noqa: E402
from researcher_swarm.retrieval import (  # noqa: E402
    build_evidence_chunk,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
)
from researcher_swarm.subagents import (  # noqa: E402
    build_leaf_research_barrier,
    build_leaf_researcher_spawn_plan,
    build_leaf_subagent_result,
    build_researcher_swarm_runtime_bundle,
    compute_leaf_subagent_result_digest,
    validate_leaf_research_barrier,
    validate_leaf_researcher_spawn_plan,
    validate_leaf_subagent_result,
    validate_researcher_swarm_runtime_bundle,
)


def _contains_key(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return any(str(key) == target or _contains_key(child, target) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


class LeafResearchAssignmentContractTest(unittest.TestCase):
    def setUp(self) -> None:
        handoff = {
            "artifact_type": "decomposer_handoff",
            "schema_version": "decomposer-handoff/v1",
            "case_id": "case-1",
            "case_key": "polymarket:market-1",
            "dispatch_id": "dispatch-1",
            "macro_question": "Will example happen?",
            "market_context": {
                "market_id": "market-1",
                "market_reality_constraints_digest": "sha256:" + "0" * 64,
            },
            "artifact_refs": {
                "related_market_context": {
                    "artifact_id": "artifact:amrg-1",
                    "artifact_type": "related-live-market-context",
                },
            },
            "model_execution_context": {
                "model_lane_id": DECOMPOSER_MODEL_LANE_ID,
                "resolved_model_id": DECOMPOSER_MODEL_ID,
                "model_policy_ref": "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json",
                "prompt_template_id": DECOMPOSER_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": "sha256:" + "1" * 64,
                "input_manifest_ids": ["artifact:case", "artifact:evidence", "artifact:profile", "artifact:amrg"],
                "output_schema_version": "question-decomposition/v1",
            },
        }
        self.qdt = select_qdt_candidate([build_fixture_qdt_candidate(handoff)])
        self.evidence_packet = {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "forecast_timestamp": "2026-06-24T12:00:00+00:00",
            "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
            "market_rules": {"resolution_url": "https://example.com/rules"},
            "official_source_hints": ["https://example.com/official"],
        }

    def _evidence(
        self,
        context: dict[str, Any],
        *,
        attempt_ref: str,
        canonical_url: str,
        source_class: str = "independent_secondary",
        source_family_id: str | None = None,
        claim_family_id: str = "claim-family-default",
    ) -> dict[str, Any]:
        return build_retrieval_evidence_item(
            case_id="case-1",
            dispatch_id="dispatch-1",
            leaf_id=context["leaf_id"],
            parent_branch_id=context["parent_branch_id"],
            retrieval_transport="browser",
            transport_attempt_ref=attempt_ref,
            requested_url=canonical_url,
            final_url=canonical_url,
            canonical_url=canonical_url,
            source_family_id=source_family_id or f"source-family-{attempt_ref}",
            source_class=source_class,
            temporal_gate_status="pass",
            source_published_at="2026-06-24T11:30:00+00:00",
            captured_at="2026-06-24T12:01:00+00:00",
            artifact_generated_at="2026-06-24T12:01:00+00:00",
            retrieval_capture_for_dispatch=True,
            claim_family_resolution_refs=[claim_family_id],
            admission_reason_codes=["manual_fixture_selected"],
        )

    def _certifiable_packet(self) -> dict[str, Any]:
        contexts = build_retrieval_query_contexts(self.qdt, evidence_packet=self.evidence_packet)
        selected = []
        chunks = []
        for context in contexts:
            official = self._evidence(
                context,
                attempt_ref=f"{context['leaf_id']}-official",
                canonical_url=f"https://example.com/official/{context['leaf_id']}",
                source_class="official_or_primary",
                source_family_id=f"source-family-{context['leaf_id']}-official",
                claim_family_id=f"claim-family-{context['leaf_id']}-official",
            )
            official["deterministic_source_class_proof"] = True
            official["source_class_resolution_method"] = "manual_fixture"
            secondary = self._evidence(
                context,
                attempt_ref=f"{context['leaf_id']}-secondary",
                canonical_url=f"https://independent.example/{context['leaf_id']}",
                source_class="independent_secondary",
                source_family_id=f"source-family-{context['leaf_id']}-secondary",
                claim_family_id=f"claim-family-{context['leaf_id']}-secondary",
            )
            selected.extend([official, secondary])
        for item in selected:
            text = f"Certified source excerpt for {item['transport_attempt_ref']}"
            chunk = build_evidence_chunk(
                evidence_ref=item["evidence_ref"],
                content_artifact_ref=f"artifact:browser-capture/{item['transport_attempt_ref']}",
                chunk_index=0,
                char_start=0,
                char_end=len(text),
                text=text,
                excerpt_policy="bounded_excerpt",
            )
            item["chunk_refs"] = [chunk["chunk_ref"]]
            chunks.append(chunk)
        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            selected_evidence=selected,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )
        packet["evidence_chunks"] = chunks
        finalized = finalize_retrieval_packet_for_dispatch(packet)
        self.assertEqual(finalized["research_sufficiency_summary"]["classification_dispatch_status"], "allowed")
        return finalized

    def test_builds_compact_primary_assignment_for_each_dispatchable_leaf(self) -> None:
        packet = self._certifiable_packet()

        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)

        self.assertEqual(len(assignments), len(self.qdt["required_leaf_questions"]))
        self.assertEqual(
            sorted(item["leaf_id"] for item in assignments),
            sorted(leaf["leaf_id"] for leaf in self.qdt["required_leaf_questions"]),
        )
        for assignment in assignments:
            result = validate_leaf_research_assignment(assignment)
            self.assertTrue(result.valid, result.errors)
            self.assertEqual(assignment["schema_version"], LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION)
            self.assertEqual(assignment["feature_id"], "CLS-006")
            self.assertEqual(assignment["assignment_role"], "primary")
            self.assertIsNone(assignment["escalation_decision_ref"])
            self.assertEqual(assignment["trigger_codes"], [])
            self.assertTrue(assignment["leaf_ref"]["leaf_digest"].startswith("sha256:"))
            self.assertTrue(assignment["leaf_ref"]["leaf_json_pointer"].startswith("/required_leaf_questions/"))
            self.assertTrue(assignment["sufficiency_requirement_refs"])
            self.assertTrue(assignment["required_value_field_ids"])
            self.assertTrue(assignment["required_negative_check_ids"])
            self.assertTrue(assignment["assigned_evidence_refs"])
            certified_snippet = assignment["assigned_evidence_refs"][0]["certified_snippet"]
            self.assertEqual(certified_snippet["access_mode"], "bounded_certified_snippet")
            self.assertTrue(certified_snippet["content_artifact_ref"].startswith("artifact:browser-capture/"))
            self.assertEqual(assignment["output_contract"]["forbidden_fields"], list(FORBIDDEN_OUTPUT_FIELDS))
            self.assertFalse(assignment["context_isolation"]["peer_context_allowed"])
            self.assertEqual(
                sorted(assignment["context_isolation"]["forbidden_artifact_ref_patterns"]),
                sorted(DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS),
            )
            self.assertIn(
                assignment["assigned_evidence_refs"][0]["evidence_ref"],
                assignment["context_isolation"]["visible_artifact_ref_allowlist"],
            )
            self.assertIn(
                certified_snippet["content_artifact_ref"],
                assignment["context_isolation"]["visible_artifact_ref_allowlist"],
            )

            model_context = assignment["model_execution_context"]
            self.assertEqual(model_context["model_lane_id"], RESEARCHER_MODEL_LANE_ID)
            self.assertEqual(model_context["resolved_model_id"], RESEARCHER_MODEL_ID)
            self.assertEqual(model_context["provider_model_key"], RESEARCHER_PROVIDER_MODEL_KEY)
            self.assertEqual(model_context["provider_route"], RESEARCHER_PROVIDER_ROUTE)
            self.assertTrue(model_context["oauth_route_required"])
            self.assertEqual(model_context["runtime_agent_id"], RESEARCHER_RUNTIME_AGENT_ID)
            self.assertEqual(model_context["prompt_template_id"], RESEARCHER_NLI_PROMPT_TEMPLATE_ID)
            self.assertEqual(model_context["prompt_template_sha256"], RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256)
            self.assertNotIn("authority_boundary", model_context)
            self.assertNotIn("forbidden_outputs", model_context)
            self.assertIn("browser_retrieval", assignment["budget"]["follow_up_research"]["allowed_transports"])
            self.assertTrue(
                assignment["budget"]["follow_up_research"][
                    "supplemental_evidence_requires_deterministic_admission"
                ]
            )

            self.assertFalse(_contains_key(assignment, "question_text"))
            self.assertFalse(_contains_key(assignment, "research_sufficiency_requirements"))
            self.assertFalse(_contains_key(assignment, "canonical_url"))
            self.assertFalse(_contains_key(assignment, "evidence_body"))

    def test_fails_closed_when_certified_snippet_artifacts_are_missing(self) -> None:
        packet = self._certifiable_packet()
        missing_chunks = copy.deepcopy(packet)
        missing_chunks["evidence_chunks"] = []

        with self.assertRaisesRegex(LeafResearchAssignmentError, "certified bounded snippet"):
            build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=missing_chunks)

        assignment = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)[0]
        broken = copy.deepcopy(assignment)
        broken["assigned_evidence_refs"][0].pop("certified_snippet", None)
        broken["assignment_digest"] = compute_leaf_research_assignment_digest(broken)

        validation = validate_leaf_research_assignment(broken)
        self.assertFalse(validation.valid)
        self.assertIn("certified_snippet is required", "; ".join(validation.errors))

    def test_assignment_id_and_digest_are_stable(self) -> None:
        packet = self._certifiable_packet()

        first = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)
        second = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)

        self.assertEqual(
            [item["assignment_id"] for item in first],
            [item["assignment_id"] for item in second],
        )
        self.assertEqual(
            [item["assignment_digest"] for item in first],
            [item["assignment_digest"] for item in second],
        )
        broken = copy.deepcopy(first[0])
        broken["budget"]["deadline_seconds"] += 1
        result = validate_leaf_research_assignment(broken)
        self.assertFalse(result.valid)
        self.assertIn("assignment_digest does not match", "; ".join(result.errors))
        broken["assignment_digest"] = compute_leaf_research_assignment_digest(broken)
        self.assertTrue(validate_leaf_research_assignment(broken).valid)

    def test_fails_closed_when_ret008_dispatch_is_not_allowed(self) -> None:
        packet = build_retrieval_packet(
            self.qdt,
            evidence_packet=self.evidence_packet,
            question_decomposition_artifact_id="artifact:qdt-1",
            policy_context_ref="artifact:profile-1",
        )

        with self.assertRaisesRegex(LeafResearchAssignmentError, "blocked_until_certified"):
            build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=packet)

    def test_validator_rejects_probability_decision_fields_and_embedded_payloads(self) -> None:
        assignment = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())[0]
        mutations = {
            "own_probability": ("own_probability", "top", "own_probability", 0.5),
            "decision_recommendation": (
                "decision_recommendation",
                "model_execution_context",
                "decision_recommendation",
                "act",
            ),
            "evidence_body": (
                "embeds payload content",
                "assigned_evidence_refs",
                "evidence_body",
                "full copied evidence text",
            ),
            "full_leaf": ("embeds payload content", "leaf_ref", "full_leaf", {"leaf_id": assignment["leaf_id"]}),
        }
        for name, (expected, container, key, value) in mutations.items():
            with self.subTest(expected=expected):
                broken = copy.deepcopy(assignment)
                if container == "top":
                    broken[key] = value
                elif container == "assigned_evidence_refs":
                    broken["assigned_evidence_refs"][0][key] = value
                else:
                    broken[container][key] = value

                result = validate_leaf_research_assignment(broken)

                self.assertFalse(result.valid)
                self.assertIn(expected, "; ".join(result.errors), name)

    def test_escalation_confirmation_fields_are_shape_only(self) -> None:
        packet = self._certifiable_packet()
        trigger_codes = {
            leaf["leaf_id"]: ["structural_unanswerability_claimed"]
            for leaf in self.qdt["required_leaf_questions"]
        }
        lenses = {
            leaf["leaf_id"]: "unanswerability_confirmation"
            for leaf in self.qdt["required_leaf_questions"]
        }

        assignments = build_leaf_research_assignments(
            qdt=self.qdt,
            retrieval_packet=packet,
            attempt_index=1,
            assignment_role="confirmation",
            escalation_decision_ref="researcher-escalation:leaf-confirmation",
            trigger_codes_by_leaf=trigger_codes,
            assigned_lens_by_leaf=lenses,
        )

        for assignment in assignments:
            self.assertEqual(assignment["assignment_role"], "confirmation")
            self.assertEqual(assignment["escalation_decision_ref"], "researcher-escalation:leaf-confirmation")
            self.assertEqual(assignment["trigger_codes"], ["structural_unanswerability_claimed"])
            self.assertEqual(assignment["assigned_lens"], "unanswerability_confirmation")
            self.assertIn("CLS-007", assignment["scope_boundaries"]["not_implemented"])
            self.assertIn("CLS-008", assignment["scope_boundaries"]["not_implemented"])
            self.assertTrue(validate_leaf_research_assignment(assignment).valid)

    def test_spawn_plan_caps_parallel_leaf_launches_and_records_queue(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())

        plan = build_leaf_researcher_spawn_plan(assignments, max_concurrent=2)

        self.assertEqual(plan["runtime_owner"], "ADS Researcher Swarm")
        self.assertEqual(plan["launch_authority"], "control_plane_only")
        self.assertEqual(plan["execution_policy"]["max_concurrent_leaf_researchers_per_case"], 2)
        self.assertEqual(plan["execution_policy"]["required_runtime_provider_model_id"], RESEARCHER_PROVIDER_MODEL_KEY)
        self.assertEqual(plan["spawn_count"], len(assignments))
        self.assertEqual(len(plan["launch_queue"]), len(assignments))
        self.assertEqual(
            [row["launch_allowed"] for row in plan["launch_queue"]],
            [True, True, False],
        )
        self.assertEqual(plan["launch_queue"][0]["required_runtime_provider_model_id"], RESEARCHER_PROVIDER_MODEL_KEY)
        self.assertEqual(plan["launch_queue"][0]["assignment_input_ref"], assignments[0]["assignment_id"])
        self.assertIn("allowed_transports", plan["launch_queue"][0]["leaf_scoped_follow_up_research"])
        self.assertEqual(plan["queued_assignment_refs"], [assignments[2]["assignment_id"]])
        validation = validate_leaf_researcher_spawn_plan(plan, assignments)
        self.assertTrue(validation.valid, validation.errors)

    def test_spawn_plan_validator_rejects_ready_launch_without_launch_allowed(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        plan = build_leaf_researcher_spawn_plan(assignments, max_concurrent=2)
        broken = copy.deepcopy(plan)
        broken["launch_queue"][0]["launch_allowed"] = False

        validation = validate_leaf_researcher_spawn_plan(broken, assignments)

        self.assertFalse(validation.valid)
        self.assertIn("launch_allowed must reflect the concurrency cap", "; ".join(validation.errors))

    def test_leaf_research_barrier_blocks_until_all_subagent_results_exist(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())

        barrier = build_leaf_research_barrier(assignments, true_production_mode=True)

        self.assertFalse(barrier["all_leaves_terminal"])
        self.assertFalse(barrier["proceed_to_verification_scae"])
        self.assertEqual(barrier["blocker_reason_codes"], ["missing_leaf_subagent_result"])
        self.assertTrue(all(row["terminal_status"] == "missing" for row in barrier["terminal_state_by_leaf"]))
        validation = validate_leaf_research_barrier(barrier, assignments=assignments, true_production_mode=True)
        self.assertTrue(validation.valid, validation.errors)

    def test_leaf_research_barrier_passes_terminal_gpt55_results(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        results = [
            build_leaf_subagent_result(
                assignment,
                terminal_status="accepted_classification",
                subagent_session_ref=f"session:{idx}",
                sidecar_refs=[f"sidecar:{assignment['leaf_id']}"],
                classification_refs=[f"classification:{assignment['leaf_id']}"],
                runtime_provenance={
                    "model_executed": True,
                    "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
                    "runtime_call_ref": f"model-runtime-call:{idx}",
                },
                reason_codes=["classification_accepted"],
            )
            for idx, assignment in enumerate(assignments)
        ]
        for result, assignment in zip(results, assignments):
            validation = validate_leaf_subagent_result(
                result,
                assignment=assignment,
                true_production_mode=True,
            )
            self.assertTrue(validation.valid, validation.errors)

        barrier = build_leaf_research_barrier(
            assignments,
            subagent_results=results,
            true_production_mode=True,
        )

        self.assertTrue(barrier["all_leaves_terminal"])
        self.assertTrue(barrier["proceed_to_verification_scae"])
        self.assertEqual(barrier["blocker_reason_codes"], [])
        validation = validate_leaf_research_barrier(barrier, assignments=assignments, true_production_mode=True)
        self.assertTrue(validation.valid, validation.errors)

    def test_runtime_bundle_requires_accepted_sidecar_coverage_before_downstream_advance(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        results = [
            build_leaf_subagent_result(
                assignment,
                terminal_status="accepted_classification",
                subagent_session_ref=f"session:{idx}",
                sidecar_refs=[f"sidecar:{assignment['leaf_id']}"],
                classification_refs=[f"classification:{assignment['leaf_id']}"],
                runtime_provenance={
                    "model_executed": True,
                    "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
                    "runtime_call_ref": f"model-runtime-call:{idx}",
                },
            )
            for idx, assignment in enumerate(assignments)
        ]

        bundle = build_researcher_swarm_runtime_bundle(
            assignments,
            qdt=self.qdt,
            retrieval_packet=self._certifiable_packet(),
            subagent_results=results,
            true_production_mode=True,
        )

        self.assertFalse(bundle["proceed_to_verification_scae"])
        self.assertFalse(bundle["all_leaves_have_assignment_and_resolution"])
        self.assertTrue(all(row["reason_codes"] == ["leaf_unclassified"] for row in bundle["leaf_runtime_status"]))
        self.assertTrue(all(row["model_executed"] for row in bundle["leaf_runtime_status"]))
        self.assertTrue(
            all(row["resolved_model_id"] == RESEARCHER_PROVIDER_MODEL_KEY for row in bundle["leaf_runtime_status"])
        )
        validation = validate_researcher_swarm_runtime_bundle(bundle)
        self.assertTrue(validation.valid, validation.errors)

    def test_runtime_bundle_validation_rejects_probability_bearing_sidecars(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        bundle = build_researcher_swarm_runtime_bundle(
            assignments,
            qdt=self.qdt,
            retrieval_packet=self._certifiable_packet(),
            sidecars=[
                {
                    "artifact_type": "researcher_sidecar",
                    "schema_version": "researcher-sidecar/v2",
                    "sidecar_id": "researcher-sidecar:probability-bearing",
                    "probability": 0.62,
                }
            ],
            true_production_mode=True,
        )

        validation = validate_researcher_swarm_runtime_bundle(bundle)

        self.assertFalse(validation.valid)
        self.assertIn("probability", "; ".join(validation.errors))

    def test_openclaw_runtime_parser_accepts_gateway_reply_bundle(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        results = [
            build_leaf_subagent_result(
                assignment,
                terminal_status="insufficient_evidence_blocker",
                subagent_session_ref=f"session:{idx}",
                runtime_provenance={
                    "model_executed": True,
                    "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
                    "runtime_call_ref": f"model-runtime-call:{idx}",
                },
                reason_codes=["insufficient_evidence_blocker"],
            )
            for idx, assignment in enumerate(assignments)
        ]
        bundle = build_researcher_swarm_runtime_bundle(
            assignments,
            qdt=self.qdt,
            retrieval_packet=self._certifiable_packet(),
            subagent_results=results,
            true_production_mode=True,
        )
        stdout = json.dumps(
            {
                "runId": "run-1",
                "status": "ok",
                "result": {
                    "payloads": [{"text": json.dumps(bundle, sort_keys=True)}],
                    "finalAssistantVisibleText": "ignored",
                },
            },
            sort_keys=True,
        )

        parsed = parse_openclaw_researcher_swarm_stdout(stdout)

        self.assertEqual(parsed["runtime_bundle_id"], bundle["runtime_bundle_id"])
        self.assertTrue(all(row["model_executed"] for row in parsed["leaf_runtime_status"]))

    def test_leaf_research_barrier_rejects_non_executed_or_wrong_model_result(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        results = [
            build_leaf_subagent_result(
                assignment,
                terminal_status="accepted_classification",
                subagent_session_ref=f"session:{idx}",
                runtime_provenance={
                    "model_executed": idx != 0,
                    "resolved_model_id": "openai/gpt-5.4-high" if idx == 1 else RESEARCHER_PROVIDER_MODEL_KEY,
                },
            )
            for idx, assignment in enumerate(assignments)
        ]

        barrier = build_leaf_research_barrier(
            assignments,
            subagent_results=results,
            true_production_mode=True,
        )

        self.assertFalse(barrier["proceed_to_verification_scae"])
        self.assertIn("true_production_requires_model_executed", barrier["blocker_reason_codes"])
        self.assertIn("true_production_requires_openai_gpt_5_5_high", barrier["blocker_reason_codes"])

    def test_leaf_subagent_result_validator_requires_session_sidecar_and_digest(self) -> None:
        assignment = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())[0]
        result = build_leaf_subagent_result(
            assignment,
            terminal_status="accepted_classification",
            subagent_session_ref="session:leaf-1",
            sidecar_refs=["sidecar:leaf-1"],
            classification_refs=["classification:leaf-1"],
            runtime_provenance={"model_executed": True, "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY},
        )
        self.assertTrue(validate_leaf_subagent_result(result, assignment=assignment, true_production_mode=True).valid)

        broken = copy.deepcopy(result)
        broken["sidecar_refs"] = []
        broken["result_digest"] = compute_leaf_subagent_result_digest(broken)

        validation = validate_leaf_subagent_result(broken, assignment=assignment, true_production_mode=True)

        self.assertFalse(validation.valid)
        self.assertIn("accepted_classification requires sidecar_refs", validation.errors)

    def test_leaf_research_barrier_blocks_contaminated_result(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        results = []
        for idx, assignment in enumerate(assignments):
            if idx == 0:
                results.append(
                    build_leaf_subagent_result(
                        assignment,
                        terminal_status="contaminated",
                        subagent_session_ref=f"session:{idx}",
                        runtime_provenance={"model_executed": True, "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY},
                        reason_codes=["isolation_contaminated"],
                    )
                )
            else:
                results.append(
                    build_leaf_subagent_result(
                        assignment,
                        terminal_status="accepted_classification",
                        subagent_session_ref=f"session:{idx}",
                        sidecar_refs=[f"sidecar:{assignment['leaf_id']}"],
                        classification_refs=[f"classification:{assignment['leaf_id']}"],
                        runtime_provenance={"model_executed": True, "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY},
                    )
                )

        barrier = build_leaf_research_barrier(
            assignments,
            subagent_results=results,
            true_production_mode=True,
        )

        self.assertFalse(barrier["proceed_to_verification_scae"])
        self.assertIn("leaf_status_contaminated", barrier["blocker_reason_codes"])
        self.assertFalse(barrier["terminal_state_by_leaf"][0]["retry_state"]["retry_eligible"])
        self.assertIn(
            "never_retry_status_contaminated",
            barrier["terminal_state_by_leaf"][0]["retry_state"]["retry_blocked_reason_codes"],
        )
        validation = validate_leaf_research_barrier(barrier, assignments=assignments, true_production_mode=True)
        self.assertTrue(validation.valid, validation.errors)

    def test_leaf_research_barrier_blocks_unknown_duplicate_and_malformed_results(self) -> None:
        assignments = build_leaf_research_assignments(qdt=self.qdt, retrieval_packet=self._certifiable_packet())
        results = [
            build_leaf_subagent_result(
                assignment,
                terminal_status="accepted_classification",
                subagent_session_ref=f"session:{idx}",
                sidecar_refs=[f"sidecar:{assignment['leaf_id']}"],
                classification_refs=[f"classification:{assignment['leaf_id']}"],
                runtime_provenance={"model_executed": True, "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY},
            )
            for idx, assignment in enumerate(assignments)
        ]
        unknown = copy.deepcopy(results[0])
        unknown["assignment_ref"] = "leaf-assignment:unknown"

        barrier = build_leaf_research_barrier(
            assignments,
            subagent_results=[*results, copy.deepcopy(results[0]), unknown, "not-a-result"],  # type: ignore[list-item]
            true_production_mode=True,
        )

        self.assertFalse(barrier["proceed_to_verification_scae"])
        self.assertIn("duplicate_leaf_subagent_result", barrier["blocker_reason_codes"])
        self.assertIn("unknown_leaf_subagent_result", barrier["blocker_reason_codes"])
        self.assertIn("invalid_leaf_subagent_result", barrier["blocker_reason_codes"])
        self.assertEqual(len(barrier["result_validation_errors"]), 3)
        validation = validate_leaf_research_barrier(barrier, assignments=assignments, true_production_mode=True)
        self.assertTrue(validation.valid, validation.errors)


if __name__ == "__main__":
    unittest.main()
