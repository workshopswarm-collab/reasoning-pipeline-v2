#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_operational_canary import OperationalCanaryConfig, run_one_case_canary, validate_preflight
from predquant.ads_pipeline_runner import ADS_PIPELINE_STAGE_ORDER, PipelineRunnerContractError
from predquant.ads_manifest_canary_handlers import build_stage_handlers as build_manifest_stage_handlers
from predquant.ads_production_handlers import (
    ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID,
    ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION,
    build_stage_handlers as build_true_production_handlers,
    wrap_production_stage_handler,
)
from predquant.ads_production_pilot_handlers import build_stage_handlers as build_production_pilot_handlers
from predquant.ads_production_readiness_handlers import (
    _verified_evidence_delta_context,
    build_stage_handlers as build_production_readiness_handlers,
)
from predquant.ads_handoff_report import build_handoff_report
from predquant.ads_operator_review import build_ads_operator_review_report
from predquant.ads_real_runtime_canary import (
    _build_runtime_criteria,
    _first_failing_gate,
    _model_runtime_evidence,
    _retrieval_runtime_evidence,
    build_current_audit_gap_summary,
    build_real_runtime_canary_report,
)
from predquant.ads_retrieval_transport import RetrievalProviderPolicy
from predquant.ads_scoreable_canary_handlers import build_stage_handlers
from predquant.sqlite_store import SCHEMA
from researcher_swarm.classification import build_researcher_sidecar_v2
from researcher_swarm.isolation import build_researcher_context_isolation_audit
from researcher_swarm.model_context import RESEARCHER_PROVIDER_MODEL_KEY, resolve_researcher_leaf_nli_model_context
from researcher_swarm.subagents import build_leaf_subagent_result, build_researcher_swarm_runtime_bundle


def _provenance_by_evidence_ref(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in [
        *packet.get("retrieval_provenance_records", []),
        *packet.get("retrieval_evidence_provenance_slices", []),
    ]:
        if isinstance(item, dict) and item.get("evidence_ref"):
            rows[str(item["evidence_ref"])] = item
    return rows


class _ConfiguredEmptyRetrievalProvider:
    provider_id = "configured-empty-test-provider"
    fetch_configured = True
    search_configured = True

    def fetch_url(self, url: str) -> dict[str, Any]:
        return {"url": url, "extraction_status": "rejected", "reason_codes": ["unit_test_empty_fetch"]}

    def search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: Any = None,
    ) -> list[dict[str, Any]]:
        return []

    def provider_diagnostics(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "fetch_configured": self.fetch_configured,
            "search_configured": self.search_configured,
        }


class _EmptyNativeCandidateProvider:
    def __call__(self, _query_context: dict[str, Any], _query_variant: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "unit-test-native-provider-result/v1",
            "native_research_candidates": [],
            "model_runtime_call": {
                "schema_version": "native-research-runtime-call-summary/v1",
                "runtime_call_id": "model-runtime-call:native-unit-test",
                "model_lane_id": "native_research_candidate_discovery",
                "resolved_model_id": "gpt-5.5-high",
                "execution_status": "succeeded",
                "mode": "fixture",
                "retry_count": 0,
                "retry_diagnostics": [],
                "runtime_reason_codes": ["unit_test_native_provider"],
            },
        }


class _SearchProofRetrievalProvider:
    provider_id = "search-proof-test-provider"
    fetch_configured = True
    search_configured = True

    _domains = (
        "ir.tesla.com",
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "ft.com",
        "cnbc.com",
        "bbc.com",
    )

    def __init__(self) -> None:
        self._url_content: dict[str, dict[str, Any]] = {}

    def _relative_source_times(self, searched_at: Any) -> dict[str, str]:
        timestamp = str(searched_at or "2100-01-01T00:00:00+00:00")
        try:
            base = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            base = datetime(2100, 1, 1, tzinfo=timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        base = base.astimezone(timezone.utc)
        return {
            "source_published_at": (base - timedelta(days=1)).isoformat(),
            "source_updated_at": (base - timedelta(hours=1)).isoformat(),
            "captured_at": (base - timedelta(minutes=5)).isoformat(),
        }

    def search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: Any = None,
    ) -> list[dict[str, Any]]:
        leaf_id = str(query_context["leaf_id"])
        required_count = 2 if query_context.get("purpose") == "resolution_mechanics" else 5
        domains = list(self._domains)
        if query_context.get("purpose") == "catalyst":
            domains = ["ir.tesla.com", "reuters.com", "gartner.com", "apnews.com", "bloomberg.com"]
        records: list[dict[str, Any]] = []
        source_times = self._relative_source_times(searched_at)
        for index, domain in enumerate(domains[:required_count], start=1):
            path_leaf = leaf_id.replace("_", "-")
            url = f"https://{domain}/ads-search-proof/{path_leaf}/{index}"
            produced = 10_000 + (index * 101)
            delivered = 9_000 + (index * 103)
            content = (
                f"Tesla produced {produced} vehicles and delivered {delivered} vehicles in Q4 2099. "
                f"Search proof source {index} for {leaf_id}. "
                "The fetched page contains enough bounded source detail for researcher classification, "
                "claim extraction, and certified snippet assignment without exposing unbounded page text. "
                * 4
            )
            self._url_content[url] = {
                "content": content,
                **source_times,
            }
            records.append(
                {
                    "leaf_id": leaf_id,
                    "query_variant_id": query_variant["query_variant_id"],
                    "query_role": query_variant.get("query_role", "primary_leaf_retrieval"),
                    "rank": index,
                    "url": url,
                    "title": f"Search proof source {index}",
                    "snippet": content,
                    "provider_id": self.provider_id,
                    "searched_at": searched_at,
                    "result_source": "unit_test_configured_search_provider",
                }
            )
        return records

    def fetch_url(self, url: str) -> dict[str, Any]:
        payload = self._url_content.get(url)
        if payload is None:
            return {"url": url, "extraction_status": "rejected", "reason_codes": ["unit_test_url_not_discovered"]}
        return {
            "url": url,
            "final_url": url,
            "extraction_status": "accepted",
            "web_fetch_role": "url_fetch_extraction_only",
            **payload,
        }

    def provider_diagnostics(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "fetch_configured": self.fetch_configured,
            "search_configured": self.search_configured,
            "web_fetch_role": "url_fetch_extraction_only",
            "web_fetch_must_not_be_used_as_search": True,
        }


def _first_assignment_evidence(
    packet: dict[str, Any],
    assignment: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence_ref = assignment["assigned_evidence_refs"][0]["evidence_ref"]
    return _assignment_evidence(packet, evidence_ref)


def _assignment_evidence(
    packet: dict[str, Any],
    evidence_ref: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provenance = _provenance_by_evidence_ref(packet)[evidence_ref]
    for result in packet.get("leaf_retrieval_results", []):
        if not isinstance(result, dict):
            continue
        for evidence in result.get("selected_evidence", []):
            if isinstance(evidence, dict) and evidence.get("evidence_ref") == evidence_ref:
                return evidence, provenance
    raise AssertionError(f"missing evidence fixture {evidence_ref}")


def _runtime_classification(
    qdt: dict[str, Any],
    packet: dict[str, Any],
    assignment: dict[str, Any],
    evidence_ref: Any = None,
) -> dict[str, Any]:
    leaves = {
        str(leaf["leaf_id"]): leaf
        for leaf in qdt.get("required_leaf_questions", [])
        if isinstance(leaf, dict) and leaf.get("leaf_id")
    }
    evidence, provenance = (
        _assignment_evidence(packet, evidence_ref)
        if evidence_ref
        else _first_assignment_evidence(packet, assignment)
    )
    leaf = leaves[assignment["leaf_id"]]
    return {
        "leaf_id": assignment["leaf_id"],
        "parent_branch_id": assignment["parent_branch_id"],
        "leaf_condition_scope": leaf.get("leaf_condition_scope", "unconditional"),
        "evidence_ref": evidence["evidence_ref"],
        "research_sufficiency_certificate_ref": assignment["research_sufficiency_certificate_ref"],
        "coverage_proof_ref": assignment["artifact_outputs"]["coverage_proof_ref"],
        "impact_direction": "supports_yes",
        "evidence_strength": "strong",
        "classification_confidence": "high",
        "answer_value_extraction": {
            "field_name": "outcome",
            "value": "market_resolves_yes",
            "normalization_status": "parsed",
        },
        "evidence_quality_dimensions": {
            "source_authority": "high",
            "directness": "direct",
            "recency": "fresh",
            "specificity": "specific",
        },
        "provenance_refs": [provenance["provenance_id"]],
    }


def _runtime_coverage(
    assignment: dict[str, Any],
    retrieval_packet: Any = None,
) -> dict[str, Any]:
    evidence_refs = [item["evidence_ref"] for item in assignment["assigned_evidence_refs"]]
    source_classes = set()
    source_family_ids = set()
    claim_family_ids = set()
    for item in assignment["assigned_evidence_refs"]:
        if retrieval_packet is not None and item.get("evidence_ref"):
            evidence, _ = _assignment_evidence(retrieval_packet, str(item["evidence_ref"]))
            if evidence.get("source_class"):
                source_classes.add(evidence["source_class"])
            if evidence.get("source_family_id"):
                source_family_ids.add(evidence["source_family_id"])
            for claim_family_id in evidence.get("claim_family_ids", []):
                if claim_family_id:
                    claim_family_ids.add(claim_family_id)
            continue
        if item.get("source_class"):
            source_classes.add(item["source_class"])
        if item.get("source_family_id"):
            source_family_ids.add(item["source_family_id"])
        if item.get("claim_family_id"):
            claim_family_ids.add(item["claim_family_id"])
    return {
        "coverage_proof_id": assignment["artifact_outputs"]["coverage_proof_ref"],
        "leaf_id": assignment["leaf_id"],
        "research_sufficiency_certificate_ref": assignment["research_sufficiency_certificate_ref"],
        "retrieval_breadth_coverage_ref": assignment["retrieval_breadth_coverage_ref"],
        "evidence_refs_assigned": list(evidence_refs),
        "evidence_refs_reviewed": list(evidence_refs),
        "source_class_ids_reviewed": sorted(source_classes),
        "claim_family_ids_reviewed": sorted(claim_family_ids),
        "source_family_ids_reviewed": sorted(source_family_ids),
        "requirements_reviewed": list(assignment["sufficiency_requirement_refs"]),
        "requirements_answered": list(assignment["sufficiency_requirement_refs"]),
        "requirements_unanswered": [],
        "required_value_fields_extracted": list(assignment["required_value_field_ids"]),
        "required_negative_checks_completed": list(assignment["required_negative_check_ids"]),
        "source_gap_flags": [],
        "structural_unanswerability_acknowledged": False,
        "machine_readability_status": "schema_valid",
    }


def _fake_researcher_runtime_bundle(
    *,
    assignments: list[dict[str, Any]],
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    true_production_mode: bool,
    max_concurrent: int,
    block_first_leaf: bool = True,
) -> dict[str, Any]:
    model_context = resolve_researcher_leaf_nli_model_context()
    assignments_by_leaf = {assignment["leaf_id"]: assignment for assignment in assignments}
    leaf_ids = [leaf["leaf_id"] for leaf in qdt["required_leaf_questions"]]
    sidecar = build_researcher_sidecar_v2(
        qdt=qdt,
        required_question_classifications=[
            _runtime_classification(qdt, retrieval_packet, assignments_by_leaf[leaf_id])
            for leaf_id in leaf_ids
        ],
        coverage_proofs=[_runtime_coverage(assignments_by_leaf[leaf_id]) for leaf_id in leaf_ids],
        model_execution_context_ref="artifact:model-execution-context:researcher-leaf-nli",
        model_execution_context=model_context,
    )
    audits = [
        build_researcher_context_isolation_audit(
            assignment,
            subagent_session_ref=f"openclaw-session:{idx}",
        )
        for idx, assignment in enumerate(assignments)
    ]
    results = []
    for idx, assignment in enumerate(assignments):
        status = "launch_blocked" if block_first_leaf and idx == 0 else "accepted_classification"
        results.append(
            build_leaf_subagent_result(
                assignment,
                terminal_status=status,
                subagent_session_ref=f"openclaw-session:{idx}",
                sidecar_refs=[sidecar["sidecar_id"]] if status == "accepted_classification" else [],
                classification_refs=[f"classification:{assignment['leaf_id']}"]
                if status == "accepted_classification"
                else [],
                isolation_audit_ref=assignment["context_isolation"]["isolation_audit_ref"],
                runtime_provenance={
                    "model_executed": True,
                    "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
                    "runtime_call_ref": f"model-runtime-call:researcher:{idx}",
                },
                reason_codes=[status],
            )
        )
    return build_researcher_swarm_runtime_bundle(
        assignments,
        qdt=qdt,
        retrieval_packet=retrieval_packet,
        sidecars=[sidecar],
        isolation_audits=audits,
        subagent_results=results,
        true_production_mode=true_production_mode,
        max_concurrent=max_concurrent,
    )


def _fake_researcher_runtime_bundle_all_accepted(**kwargs) -> dict[str, Any]:
    return _fake_researcher_runtime_bundle(**kwargs, block_first_leaf=False)


def _fake_researcher_runtime_bundle_all_evidence_accepted(
    *,
    assignments: list[dict[str, Any]],
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    true_production_mode: bool,
    max_concurrent: int,
) -> dict[str, Any]:
    model_context = resolve_researcher_leaf_nli_model_context()
    classifications = []
    coverage_proofs = []
    for assignment in assignments:
        for assigned in assignment.get("assigned_evidence_refs", []):
            if isinstance(assigned, dict) and assigned.get("evidence_ref"):
                classifications.append(
                    _runtime_classification(
                        qdt,
                        retrieval_packet,
                        assignment,
                        evidence_ref=str(assigned["evidence_ref"]),
                    )
                )
        coverage_proofs.append(_runtime_coverage(assignment, retrieval_packet))
    sidecar = build_researcher_sidecar_v2(
        qdt=qdt,
        required_question_classifications=classifications,
        coverage_proofs=coverage_proofs,
        model_execution_context_ref="artifact:model-execution-context:researcher-leaf-nli",
        model_execution_context=model_context,
    )
    audits = [
        build_researcher_context_isolation_audit(
            assignment,
            subagent_session_ref=f"openclaw-session:{idx}",
        )
        for idx, assignment in enumerate(assignments)
    ]
    results = [
        build_leaf_subagent_result(
            assignment,
            terminal_status="accepted_classification",
            subagent_session_ref=f"openclaw-session:{idx}",
            sidecar_refs=[sidecar["sidecar_id"]],
            classification_refs=[
                f"classification:{assignment['leaf_id']}:{evidence['evidence_ref']}"
                for evidence in assignment.get("assigned_evidence_refs", [])
                if isinstance(evidence, dict) and evidence.get("evidence_ref")
            ],
            isolation_audit_ref=assignment["context_isolation"]["isolation_audit_ref"],
            runtime_provenance={
                "model_executed": True,
                "resolved_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
                "runtime_call_ref": f"model-runtime-call:researcher:{idx}",
            },
            reason_codes=["accepted_classification"],
        )
        for idx, assignment in enumerate(assignments)
    ]
    return build_researcher_swarm_runtime_bundle(
        assignments,
        qdt=qdt,
        retrieval_packet=retrieval_packet,
        sidecars=[sidecar],
        isolation_audits=audits,
        subagent_results=results,
        true_production_mode=true_production_mode,
        max_concurrent=max_concurrent,
    )


class AdsOperationalCanaryTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seed_market()
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def _seed_market(
        self,
        *,
        external_market_id="operational-canary",
        slug="operational-canary",
        title="Will the operational canary complete?",
        best_bid=0.49,
        best_ask=0.53,
    ):
        market_id = self.conn.execute(
            """
            INSERT INTO markets (
              platform, external_market_id, slug, title, description, category,
              status, outcome_type, closes_at, resolves_at, metadata, current_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "polymarket",
                external_market_id,
                slug,
                title,
                "Synthetic canary market",
                "test",
                "open",
                "binary",
                "2100-01-01T00:00:00+00:00",
                "2100-01-02T00:00:00+00:00",
                "{}",
                0.51,
            ),
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO market_snapshots (
              market_id, observed_at, last_price, best_bid, best_ask, yes_price,
              no_price, volume, open_interest, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market_id,
                "2099-12-31T23:55:00+00:00",
                None,
                best_bid,
                best_ask,
                None,
                None,
                100.0,
                50.0,
                json.dumps({"source": "unit-test"}, sort_keys=True),
            ),
        )

    def config(
        self,
        *,
        require_scoreable_prediction=False,
        max_cases=1,
        require_manifest_handoffs=False,
        require_real_runtime_canary_criteria=False,
        require_researcher_model_executed=False,
    ):
        return OperationalCanaryConfig(
            db_path=self.db_path,
            runner_mode="fixture",
            forecast_timestamp="2100-01-01T00:00:00+00:00",
            max_cases=max_cases,
            updated_by="unit-test",
            reason="unit-test one-case canary",
            require_scoreable_prediction=require_scoreable_prediction,
            require_manifest_handoffs=require_manifest_handoffs,
            metadata={"test_scope": "operational_canary"},
            require_real_runtime_canary_criteria=require_real_runtime_canary_criteria,
            require_researcher_model_executed=require_researcher_model_executed,
        )

    def stage_handlers(self):
        def make_handler(stage):
            def handler(**_kwargs):
                result = {
                    "output_artifact_refs": [f"artifact:{stage}"],
                    "validation_result_refs": [f"validation:{stage}"],
                    "safe_metadata": {"stage": stage, "handler_scope": "operational_canary"},
                }
                if stage == "decision":
                    result["forecast_decision_record_id"] = "forecast-decision:operational-canary"
                return result

            return handler

        return {stage: make_handler(stage) for stage in ADS_PIPELINE_STAGE_ORDER[1:]}

    def test_verified_evidence_context_builds_netted_scae_inputs(self):
        classification = {
            "slice_id": "classification-slice-1",
            "classification_id": "classification-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "condition_scope": "unconditional",
            "evidence_ref": "evidence-1",
            "source_ref": "source-1",
            "source_class": "official_or_primary",
            "source_family_id": "source-family-1",
            "claim_family_id": "claim-family-1",
            "retrieval_breadth_coverage_ref": "breadth-coverage-1",
            "research_sufficiency_certificate_ref": "research-sufficiency-1",
            "certified_snippet_ref": "chunk-classification-slice-1",
            "certified_snippet_sha256": "sha256:" + "7" * 64,
            "certified_snippet_access_mode": "bounded_certified_snippet",
            "certified_snippet_content_artifact_ref": "artifact:browser-capture/classification-slice-1",
            "temporal_gate_status": "pass",
            "impact_direction": "supports_yes",
            "evidence_strength": "strong",
            "classification_confidence": "high",
            "classification_quality": "high",
            "classification_acceptance_status": "accepted_for_verification",
            "evidence_delta_eligible_for_scae": True,
            "ledger_ready": True,
            "included_for_scae": True,
        }
        payload = {
            "classification_matrix": {"classification_slices": [classification]},
            "direction_verification_slices": [
                {
                    "verification_slice_id": "direction-1",
                    "classification_slice_ref": "classification-slice-1",
                    "verified_direction": "supports_yes",
                    "verification_status": "accepted",
                    "accepted_for_scae": True,
                }
            ],
            "quality_verification_slices": [
                {
                    "quality_verification_slice_id": "quality-1",
                    "classification_slice_ref": "classification-slice-1",
                    "quality_status": "accepted",
                    "accepted_for_scae": True,
                    "accepted_quality_fields": {
                        "classification_confidence": "high",
                        "classification_quality": "high",
                    },
                    "quality_correlation_groups": ["source_family:source-family-1", "claim_family:claim-family-1"],
                    "raw_quality_multiplier": 1.0,
                    "final_quality_multiplier": 1.0,
                }
            ],
        }

        context = _verified_evidence_delta_context(payload)

        self.assertIsNotNone(context)
        self.assertEqual(context["netting_bundle"]["cluster_count"], 1)
        self.assertEqual(context["classification_slice_refs"], ["classification-slice-1"])
        self.assertEqual(context["direction_verification_slice_refs"], ["direction-1"])
        self.assertEqual(context["quality_verification_slice_refs"], ["quality-1"])
        self.assertEqual(len(context["ledger_evidence_delta_slices"]), 1)

    def _decomposer_live_response_path(self):
        path = Path(self.tempdir.name) / "decomposer-live-response.json"
        branch_resolution = "branch-operational-canary-resolution"
        branch_mechanics = "branch-operational-canary-mechanics"
        payload = {
            "schema_version": "model-runtime-transport-response/v1",
            "response_payload": {
                "candidate_id": "qdt-candidate-operational-canary",
                "market_complexity_score": 0.62,
                "branches": [
                    {
                        "branch_id": branch_resolution,
                        "branch_question": "Define research coverage for whether the operational canary completes.",
                        "branch_role": "question_specific_research_coverage",
                        "dependency_group_id": "dep-group-operational-canary-resolution",
                        "required_evidence_purposes": ["source_of_truth", "direct_evidence", "catalyst", "structural"],
                        "leaf_ids": [
                            "leaf-operational-canary-official-status",
                            "leaf-operational-canary-direct-status",
                            "leaf-operational-canary-driver-stage",
                            "leaf-operational-canary-negative-checks",
                            "leaf-operational-canary-source-quality",
                            "leaf-operational-canary-material-unknowns",
                        ],
                        "amrg_usage_refs": [],
                        "structural_validation": {"depth": 1},
                    },
                    {
                        "branch_id": branch_mechanics,
                        "branch_question": "Identify the operational canary market rules and timing window.",
                        "branch_role": "question_specific_resolution_mechanics",
                        "dependency_group_id": "dep-group-operational-canary-mechanics",
                        "required_evidence_purposes": ["resolution_mechanics"],
                        "leaf_ids": [
                            "leaf-operational-canary-rules-window",
                            "leaf-operational-canary-timing-constraints",
                        ],
                        "amrg_usage_refs": [],
                        "structural_validation": {"depth": 1},
                    },
                ],
                "required_leaf_questions": [
                    {
                        "leaf_id": "leaf-operational-canary-official-status",
                        "parent_branch_id": branch_resolution,
                        "question_text": "Which official source can establish whether the operational canary completes?",
                        "purpose": "source_of_truth",
                        "coverage_dimension": "resolution_mechanics",
                        "research_factor": "resolution_condition_and_authority",
                        "research_priority": "critical",
                        "priority_reason_codes": ["official_resolution_authority"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-resolution",
                        "leaf_condition_scope": "unconditional",
                        "required_evidence_fields": ["official_status", "resolution_criteria"],
                        "market_component_terms": ["operational canary", "official status"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-direct-status",
                        "parent_branch_id": branch_resolution,
                        "question_text": "What direct event evidence before the cutoff bears on operational canary completion?",
                        "purpose": "direct_evidence",
                        "coverage_dimension": "current_direct_evidence",
                        "research_factor": "current_target_event_status",
                        "research_priority": "high",
                        "priority_reason_codes": ["question_specific_event_status"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-resolution",
                        "leaf_condition_scope": "unconditional",
                        "required_evidence_fields": ["event_status", "event_timestamp"],
                        "market_component_terms": ["operational canary", "event status"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-driver-stage",
                        "parent_branch_id": branch_resolution,
                        "question_text": "Which operational milestone or process-stage signal would make completion observable before cutoff?",
                        "purpose": "catalyst",
                        "coverage_dimension": "key_drivers",
                        "research_factor": "process_stage_and_driver_status",
                        "research_priority": "high",
                        "priority_reason_codes": ["material_driver_status"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-resolution",
                        "leaf_condition_scope": "unconditional",
                        "required_evidence_fields": ["driver_status", "process_stage"],
                        "market_component_terms": ["operational canary", "driver", "process stage"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-negative-checks",
                        "parent_branch_id": branch_resolution,
                        "question_text": "What blockers, missing milestone evidence, or contradictions show the operational canary has not completed before cutoff?",
                        "purpose": "direct_evidence",
                        "coverage_dimension": "counterevidence_negative_checks",
                        "research_factor": "counterevidence_and_blockers",
                        "research_priority": "high",
                        "priority_reason_codes": ["negative_check_required"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-resolution",
                        "leaf_condition_scope": "unconditional",
                        "required_evidence_fields": ["negative_check_status", "contradiction_status"],
                        "market_component_terms": ["operational canary", "negative check", "blocker"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-source-quality",
                        "parent_branch_id": branch_resolution,
                        "question_text": "Are operational canary completion claims independent high-quality signals or repeated weak diagnostics?",
                        "purpose": "direct_evidence",
                        "coverage_dimension": "source_quality",
                        "research_factor": "claim_family_independence_and_source_quality",
                        "research_priority": "medium",
                        "priority_reason_codes": ["source_quality_required"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-resolution",
                        "leaf_condition_scope": "unconditional",
                        "required_evidence_fields": ["source_quality", "claim_family_independence"],
                        "market_component_terms": ["operational canary", "source quality", "claim family"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-rules-window",
                        "parent_branch_id": branch_mechanics,
                        "question_text": "Which rules and source hierarchy distinguish qualifying operational canary completion evidence from weak diagnostics?",
                        "purpose": "resolution_mechanics",
                        "coverage_dimension": "resolution_mechanics",
                        "research_factor": "source_hierarchy_and_qualifying_claim",
                        "research_priority": "medium",
                        "priority_reason_codes": ["market_specific_contract_terms"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-mechanics",
                        "leaf_condition_scope": "shared_context",
                        "required_evidence_fields": ["resolution_deadline", "rules_text"],
                        "market_component_terms": ["operational canary", "rules"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-timing-constraints",
                        "parent_branch_id": branch_mechanics,
                        "question_text": "Which deadline, cutoff, and observation-window constraints determine whether operational canary evidence can count?",
                        "purpose": "resolution_mechanics",
                        "coverage_dimension": "timing_deadline_constraints",
                        "research_factor": "deadline_and_cutoff_admissibility",
                        "research_priority": "medium",
                        "priority_reason_codes": ["contract_timing_terms"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-mechanics",
                        "leaf_condition_scope": "shared_context",
                        "required_evidence_fields": ["resolution_deadline", "cutoff_window"],
                        "market_component_terms": ["operational canary", "deadline", "cutoff"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                    {
                        "leaf_id": "leaf-operational-canary-material-unknowns",
                        "parent_branch_id": branch_resolution,
                        "question_text": "What material operational canary questions remain unanswered after retrieval, and are they answerable through more source discovery?",
                        "purpose": "structural",
                        "coverage_dimension": "material_unknowns",
                        "research_factor": "unanswered_material_questions",
                        "research_priority": "medium",
                        "priority_reason_codes": ["material_unknowns_required"],
                        "leaf_dependency_group_id": "dep-group-operational-canary-resolution",
                        "leaf_condition_scope": "unconditional",
                        "required_evidence_fields": ["unanswered_question_status", "answerability_status"],
                        "market_component_terms": ["operational canary", "material unknown", "answerability"],
                        "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                    },
                ],
            },
            "token_usage": {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60},
            "provider_status": {"finish_reason": "stop", "transport": "unit-test"},
        }
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return path

    def test_preflight_rejects_missing_handler_stage(self):
        handlers = self.stage_handlers()
        handlers.pop("decision")

        with self.assertRaisesRegex(PipelineRunnerContractError, "missing AUTO-003 stage handlers"):
            validate_preflight(self.conn, self.config(), handlers)

    def test_one_case_canary_runs_once_and_disables_pipeline(self):
        self.assertTrue(validate_preflight(self.conn, self.config(), self.stage_handlers())["eligible_case_available"])

        result = run_one_case_canary(self.config(), self.stage_handlers())

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["terminal_status"], "stopped_after_current_case")
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertFalse(result["control_after"]["pipeline_enabled"])
        self.assertEqual(result["active_after"], {"active_runs": 0, "active_leases": 0})
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 0)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ads_case_leases").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM ads_case_leases WHERE lease_status = 'released'").fetchone()[0],
                1,
            )

    def test_scoreable_requirement_fails_without_prediction_bridge_write(self):
        result = run_one_case_canary(self.config(require_scoreable_prediction=True), self.stage_handlers())

        self.assertFalse(result["ok"])
        self.assertIn("scoreable canary expected exactly 1 market_predictions row(s)", result["errors"])

    def test_scoreable_canary_factory_writes_one_prediction(self):
        config = self.config(require_scoreable_prediction=True)
        handlers = build_stage_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        with sqlite3.connect(self.db_path) as conn:
            prediction_source = conn.execute("SELECT prediction_source FROM market_predictions").fetchone()[0]
        self.assertEqual(prediction_source, "ads_pipeline")

    def test_scoreable_canary_factory_runs_bounded_batch(self):
        self._seed_market(
            external_market_id="operational-canary-b",
            slug="operational-canary-b",
            title="Will the second operational canary complete?",
            best_bid=0.58,
            best_ask=0.62,
        )
        self.conn.commit()
        config = self.config(require_scoreable_prediction=True, max_cases=2)
        handlers = build_stage_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["terminal_status"], "auto005_max_cases_complete")
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 2)
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 2)

    def test_manifest_canary_factory_satisfies_strict_handoff_mode(self):
        config = self.config(require_scoreable_prediction=True, require_manifest_handoffs=True)
        handlers = build_manifest_stage_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        with sqlite3.connect(self.db_path) as conn:
            manifest_count = conn.execute("SELECT COUNT(*) FROM case_artifact_manifest").fetchone()[0]
        self.assertGreaterEqual(manifest_count, len(ADS_PIPELINE_STAGE_ORDER))

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertEqual(
            report["manifest_counts_by_validation_status"],
            {"valid": len(ADS_PIPELINE_STAGE_ORDER) - 1},
        )
        self.assertEqual(
            {stage["stage"] for stage in report["stages"]},
            set(ADS_PIPELINE_STAGE_ORDER),
        )

    def test_production_readiness_factory_blocks_prediction_until_research_sufficiency(self):
        config = self.config(require_scoreable_prediction=False, require_manifest_handoffs=True)
        handlers = build_production_readiness_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 0)
        with sqlite3.connect(self.db_path) as conn:
            decision = conn.execute(
                """
                SELECT production_persistence_status, production_forecast_persisted,
                       scoreable_forecast_output, non_scoreable_reason_code
                FROM forecast_decision_records
                """
            ).fetchone()
            self.assertEqual(decision[0], "blocked_invalid_scae_forecast")
            self.assertEqual(decision[1], 0)
            self.assertEqual(decision[2], 0)
            self.assertEqual(decision[3], "forecast_validity_invalid_for_forecast")

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertGreaterEqual(report["manifest_counts_by_validation_status"].get("valid", 0), len(ADS_PIPELINE_STAGE_ORDER))

    def test_true_production_factory_clone_canary_blocks_at_leaf_research_barrier(self):
        config = self.config(
            require_scoreable_prediction=False,
            require_manifest_handoffs=True,
            require_real_runtime_canary_criteria=True,
        )
        handlers = build_true_production_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            decomposer_runtime_transport_response_path=self._decomposer_live_response_path(),
            retrieval_browser_provider=_ConfiguredEmptyRetrievalProvider(),
            native_candidate_provider=_EmptyNativeCandidateProvider(),
        )

        result = run_one_case_canary(config, handlers)

        self.assertFalse(result["ok"])
        self.assertIn(
            "real_runtime_canary:retrieval_runtime_not_source_populated_or_structurally_unanswerable",
            result["errors"],
        )
        criteria_report = result["real_runtime_canary_report"]
        self.assertFalse(criteria_report["ok"])
        self.assertIn(
            "retrieval_runtime_not_source_populated_or_structurally_unanswerable",
            criteria_report["issues"],
        )
        self.assertIn(
            "retrieval_live_acceptance_requirements_not_met",
            criteria_report["issues"],
        )
        self.assertEqual(criteria_report["criteria_schema_version"], "ads-real-runtime-canary-criteria/v1")
        self.assertEqual(criteria_report["active_work"], {"active_runs": 0, "active_leases": 0})
        self.assertEqual(criteria_report["prediction_delta_evidence"]["expected_market_predictions"], 0)
        self.assertEqual(criteria_report["model_runtime_evidence"]["qdt_model_executed_count"], 1)
        self.assertEqual(
            criteria_report["first_failing_gate"],
            "retrieval_source_populated_or_structural_unanswerability",
        )
        phase9_case = criteria_report["phase9_representative_case"]
        self.assertEqual(phase9_case["classification"], "structured_non_scoreable_insufficiency")
        self.assertTrue(phase9_case["no_scoreable_write_when_blocked"])
        self.assertIn("blocked_without_scoreable_prediction", phase9_case["reason_codes"])
        self.assertIn("retrieval_runtime_evidence", criteria_report)
        self.assertEqual(criteria_report["retrieval_runtime_evidence"]["source_populated_count"], 0)
        self.assertEqual(criteria_report["retrieval_runtime_evidence"]["admitted_evidence_ref_count"], 0)
        self.assertIn(
            "expansion_executed_count",
            criteria_report["retrieval_runtime_evidence"],
        )
        self.assertIn(
            "expansion_exhausted_count",
            criteria_report["retrieval_runtime_evidence"],
        )
        self.assertEqual(
            criteria_report["retrieval_runtime_evidence"]["planned_not_executed_expansion_count"],
            0,
        )
        self.assertTrue(criteria_report["retrieval_runtime_evidence"]["retrieval_packets"])
        blocked_packet = criteria_report["retrieval_runtime_evidence"]["retrieval_packets"][0]
        self.assertTrue(blocked_packet["leaf_retrieval_statuses"])
        self.assertIn("freshness_status", blocked_packet["leaf_retrieval_statuses"][0])
        self.assertIn("protected_primary_status", blocked_packet["leaf_retrieval_statuses"][0])
        runtime_gate_statuses = {
            item["gate"]: item["status"]
            for item in criteria_report["criteria"]["runtime_gates"]
        }
        self.assertEqual(
            runtime_gate_statuses["retrieval_source_populated_or_structural_unanswerability"],
            "failed",
        )
        self.assertEqual(runtime_gate_statuses["retrieval_live_acceptance_requirements"], "failed")
        self.assertEqual(
            runtime_gate_statuses["researcher_model_executed_if_dispatch_allowed"],
            "skipped",
        )
        self.assertTrue(criteria_report["researcher_runtime_evidence"]["blocked_non_scoreable"])
        standalone_report = build_real_runtime_canary_report(
            self.db_path,
            pipeline_run_id=result["result"]["pipeline_run_id"],
            expected_cases=1,
            expected_forecast_decision_records=1,
            expected_market_predictions=0,
        )
        self.assertFalse(standalone_report["ok"])
        self.assertIn(
            "retrieval_runtime_not_source_populated_or_structurally_unanswerable",
            standalone_report["issues"],
        )
        self.assertIn("retrieval_live_acceptance_requirements_not_met", standalone_report["issues"])
        self.assertEqual(
            standalone_report["prediction_delta_evidence"]["delta_source"],
            "pipeline_run_records",
        )
        self.assertEqual(
            standalone_report["criteria"]["first_failing_gate"],
            "retrieval_source_populated_or_structural_unanswerability",
        )
        operator_report = build_ads_operator_review_report(
            self.db_path,
            pipeline_run_id=result["result"]["pipeline_run_id"],
            max_market_snapshot_age_seconds=10_000_000_000,
            max_resolution_sync_age_seconds=10_000_000_000,
        )
        self.assertTrue(operator_report["ok"], operator_report["alerts"])
        self.assertTrue(operator_report["scheduler_may_continue"])
        self.assertEqual(operator_report["status"], "review_warned")
        self.assertEqual(
            operator_report["true_runtime_cutover_status"],
            "blocked_missing_retrieval_cert",
        )
        self.assertFalse(operator_report["true_runtime_cutover_ready"])
        self.assertEqual(operator_report["run_kind"], "true_production")
        self.assertEqual(operator_report["alert_counts_by_severity"]["blocker"], 0)
        self.assertEqual(len(operator_report["cases"]), 1)
        operator_case = operator_report["cases"][0]
        self.assertEqual(operator_case["qdt_model_provenance"]["resolved_model_id"], "gpt-5.5-high")
        self.assertTrue(operator_case["qdt_model_provenance"]["question_specific"])
        self.assertTrue(operator_case["retrieval_sufficiency"]["leaf_retrieval_statuses"])
        self.assertTrue(operator_case["researcher_model_provenance"]["blocked_non_scoreable"])
        self.assertEqual(
            operator_case["scae_readiness"]["forecast_validity_status"],
            "invalid_for_forecast",
        )
        self.assertEqual(
            len(operator_case["decision_and_prediction"]["forecast_decision_records"]),
            1,
        )
        self.assertTrue(operator_case["trace_replay_refs"]["trace_artifact_refs"])
        self.assertTrue(operator_case["trace_replay_refs"]["replay_artifact_refs"])
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 0)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            qdt_row = conn.execute(
                """
                SELECT artifact_id, artifact_path, input_manifest_ids, metadata
                FROM case_artifact_manifest
                WHERE artifact_type = 'question-decomposition'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            runtime_row = conn.execute(
                """
                SELECT artifact_id, artifact_path
                FROM case_artifact_manifest
                WHERE artifact_type = 'model-runtime-call'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            amrg_row = conn.execute(
                """
                SELECT artifact_id, artifact_path, metadata
                FROM case_artifact_manifest
                WHERE artifact_type IN ('related-live-market-context', 'no-related-context-waiver')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            retrieval_row = conn.execute(
                """
                SELECT artifact_id, artifact_path, input_manifest_ids
                FROM case_artifact_manifest
                WHERE artifact_type = 'retrieval-packet'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            classification_row = conn.execute(
                """
                SELECT artifact_id, artifact_path, input_manifest_ids
                FROM case_artifact_manifest
                WHERE artifact_type IN ('leaf-research-barrier', 'researcher-classification-readiness-block')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            decomposition_status = conn.execute(
                """
                SELECT metadata
                FROM v2_stage_status_snapshots
                WHERE stage = 'decomposition' AND status = 'complete'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            qdt_run_count = conn.execute("SELECT COUNT(*) FROM qdt_decomposition_runs").fetchone()[0]
            qdt_leaf_count = conn.execute("SELECT COUNT(*) FROM qdt_required_research_questions").fetchone()[0]
            qdt_sufficiency_count = conn.execute(
                "SELECT COUNT(*) FROM qdt_leaf_research_sufficiency_requirements"
            ).fetchone()[0]
            decision = conn.execute(
                """
                SELECT production_persistence_status, production_forecast_persisted,
                       scoreable_forecast_output, non_scoreable_reason_code
                FROM forecast_decision_records
                """
            ).fetchone()

        self.assertIsNotNone(qdt_row)
        self.assertIsNotNone(runtime_row)
        self.assertIsNotNone(amrg_row)
        self.assertIsNotNone(retrieval_row)
        self.assertIsNotNone(classification_row)
        self.assertIsNotNone(decomposition_status)
        qdt = json.loads(Path(qdt_row["artifact_path"]).read_text(encoding="utf-8"))
        runtime = json.loads(Path(runtime_row["artifact_path"]).read_text(encoding="utf-8"))
        amrg = json.loads(Path(amrg_row["artifact_path"]).read_text(encoding="utf-8"))
        retrieval = json.loads(Path(retrieval_row["artifact_path"]).read_text(encoding="utf-8"))
        classification_payload = json.loads(Path(classification_row["artifact_path"]).read_text(encoding="utf-8"))
        qdt_input_manifest_ids = set(json.loads(qdt_row["input_manifest_ids"]))
        classification_input_manifest_ids = set(json.loads(classification_row["input_manifest_ids"]))
        qdt_metadata = json.loads(qdt_row["metadata"])
        amrg_metadata = json.loads(amrg_row["metadata"])
        decomposition_status_metadata = json.loads(decomposition_status["metadata"])

        leaf_ids = {leaf["leaf_id"] for leaf in qdt["required_leaf_questions"]}
        self.assertFalse(
            {"leaf-source-of-truth", "leaf-direct-evidence", "leaf-resolution-mechanics"} & leaf_ids
        )
        self.assertEqual(qdt["adapter_mode"], "decomposer_model_runtime_live")
        self.assertEqual(qdt["runtime_call_ref"], runtime["runtime_call_id"])
        self.assertIn(runtime_row["artifact_id"], qdt_input_manifest_ids)
        self.assertEqual(qdt_metadata["handler_scope"], "true_production_specialist_runtime")
        self.assertEqual(
            qdt_metadata["handler_factory"],
            "predquant.ads_production_handlers",
        )
        self.assertFalse(qdt_metadata["scoreable_pilot"])
        self.assertTrue(qdt_metadata["decomposer_runtime"])
        self.assertEqual(
            decomposition_status_metadata["stage_failure_policy_schema_version"],
            ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION,
        )
        self.assertEqual(
            decomposition_status_metadata["stage_failure_policy_id"],
            ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID,
        )
        self.assertEqual(decomposition_status_metadata["scoreable_write_surface"], "decision_stage_only")
        self.assertEqual(decomposition_status_metadata["handler_scope"], "true_production_specialist_runtime")
        self.assertEqual(runtime["resolved_model_id"], "gpt-5.5-high")
        self.assertEqual(runtime["mode"], "live")
        self.assertFalse(runtime["fixture_mode"])
        self.assertEqual(runtime["execution_status"], "succeeded")
        self.assertEqual(amrg["vector_runtime"]["status"], "unavailable")
        self.assertEqual(
            amrg["vector_runtime"]["diagnostic_unavailable_reasons"],
            ["vector_candidate_descriptor_pool_empty"],
        )
        self.assertEqual(amrg_metadata["amrg_vector_status"], "unavailable")
        self.assertEqual(amrg["amrg_operator_report"]["schema_version"], "amrg-operator-report/v1")
        self.assertEqual(qdt_run_count, 1)
        self.assertEqual(qdt_leaf_count, len(qdt["required_leaf_questions"]))
        self.assertEqual(qdt_sufficiency_count, len(qdt["required_leaf_questions"]))
        self.assertEqual(retrieval["adapter_mode"], "source_populated_live_retrieval_runtime")
        self.assertEqual(retrieval["retrieval_runtime_summary"]["runtime_mode"], "live_retrieval_runtime")
        self.assertGreater(retrieval["retrieval_runtime_summary"]["direct_url_attempt_count"], 0)
        self.assertGreater(retrieval["ads_retrieval_transport_diagnostics"]["direct_url_candidate_count"], 0)
        self.assertTrue(retrieval["leaf_evidence_dockets"])
        self.assertTrue(retrieval["browser_retrieval_attempts"])
        self.assertFalse(all(docket["admitted_evidence_refs"] for docket in retrieval["leaf_evidence_dockets"]))
        self.assertEqual(
            retrieval["research_sufficiency_summary"]["classification_dispatch_status"],
            "blocked_insufficient_research",
        )
        self.assertEqual(
            retrieval["native_research_transport_diagnostics"][0]["availability_status"],
            "available",
        )
        self.assertEqual(retrieval["retrieval_runtime_summary"]["native_research_status"], "executed_no_candidates")
        self.assertIn(retrieval_row["artifact_id"], classification_input_manifest_ids)
        self.assertEqual(classification_payload["classification_status"], "blocked_until_certified_retrieval")
        self.assertEqual(classification_payload["reason_codes"], ["retrieval_sufficiency_not_certified"])
        self.assertEqual(decision["production_persistence_status"], "blocked_invalid_scae_forecast")
        self.assertEqual(decision["production_forecast_persisted"], 0)
        self.assertEqual(decision["scoreable_forecast_output"], 0)
        self.assertEqual(decision["non_scoreable_reason_code"], "forecast_validity_invalid_for_forecast")

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])

    def test_true_production_search_runtime_canary_proves_retrieval_to_scae_inputs(self):
        config = self.config(
            require_scoreable_prediction=True,
            require_manifest_handoffs=True,
            require_real_runtime_canary_criteria=True,
            require_researcher_model_executed=True,
        )
        handlers = build_true_production_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            decomposer_runtime_transport_response_path=self._decomposer_live_response_path(),
            retrieval_browser_provider=_SearchProofRetrievalProvider(),
            retrieval_provider_policy=RetrievalProviderPolicy(
                max_direct_urls=0,
                max_total_search_calls=10,
                max_search_results_per_variant=5,
                max_total_search_result_fetches=50,
            ),
            researcher_swarm_runtime_runner=_fake_researcher_runtime_bundle_all_evidence_accepted,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        criteria_report = result["real_runtime_canary_report"]
        self.assertTrue(criteria_report["ok"], criteria_report["issues"])
        self.assertIsNone(criteria_report["first_failing_gate"])
        phase9_case = criteria_report["phase9_representative_case"]
        self.assertEqual(phase9_case["classification"], "scoreable_success")
        self.assertIn("all_scoreable_runtime_gates_passed", phase9_case["reason_codes"])
        self.assertTrue(all(phase9_case["scoreable_success_requirements"].values()))
        self.assertGreater(
            phase9_case["reporting_counters"]["search_candidates_materialized_count"],
            0,
        )
        self.assertGreater(
            phase9_case["reporting_counters"]["scae_delta_ref_count"],
            0,
        )
        qdt_evidence = criteria_report["model_runtime_evidence"]
        self.assertTrue(qdt_evidence["model_runtime_ok"])
        self.assertTrue(qdt_evidence["qdt_end_to_end_quality_ok"])
        self.assertEqual(qdt_evidence["qdt_model_executed_count"], 1)
        self.assertEqual(qdt_evidence["qdt_end_to_end_quality_count"], 1)
        self.assertEqual(qdt_evidence["qdt_question_specificity_passed_count"], 1)
        self.assertEqual(qdt_evidence["qdt_research_coverage_passed_count"], 1)
        self.assertEqual(qdt_evidence["qdt_pre_resolution_dispatchable_count"], 1)
        self.assertEqual(qdt_evidence["qdt_terminal_verification_gated_count"], 1)
        self.assertEqual(qdt_evidence["qdt_forbidden_field_clean_count"], 1)
        self.assertEqual(qdt_evidence["qdt_meaningful_leaf_requirements_count"], 1)
        qdt_quality = qdt_evidence["qdt_results"][0]["qdt_quality"]
        self.assertEqual(qdt_quality["market_temporal_state"], "unresolved")
        self.assertEqual(qdt_quality["issue_codes"], [])
        self.assertGreater(qdt_quality["dispatchable_pre_resolution_leaf_count"], 0)
        self.assertIn("pre_resolution_forecast_driver", qdt_quality["dispatchable_temporal_roles"])
        self.assertEqual(qdt_quality["terminal_dispatch_leaf_ids"], [])
        runtime_gate_statuses = {
            item["gate"]: item["status"]
            for item in criteria_report["criteria"]["runtime_gates"]
        }
        self.assertEqual(runtime_gate_statuses["qdt_end_to_end_quality"], "passed")
        retrieval = criteria_report["retrieval_runtime_evidence"]
        self.assertGreater(retrieval["real_candidate_count"], 0)
        self.assertGreater(retrieval["fetched_attempt_count"], 0)
        self.assertGreater(retrieval["admitted_evidence_ref_count"], 0)
        self.assertEqual(retrieval["external_source_discovery_proven_count"], 1)
        self.assertEqual(retrieval["structured_market_metadata_pilot_packet_count"], 0)
        self.assertEqual(retrieval["browser_search_executed_count"], 1)
        self.assertEqual(retrieval["direct_url_capture_executed_count"], 0)
        self.assertEqual(retrieval["native_research_model_executed_count"], 0)
        self.assertEqual(retrieval["metadata_classifier_assist_executed_count"], 0)
        self.assertEqual(retrieval["source_collation_acceptance_proven_count"], 1)
        self.assertEqual(retrieval["blocked_when_acceptance_unmet_count"], 0)
        self.assertEqual(retrieval["acceptance_unmet_not_blocked_count"], 0)
        self.assertGreater(retrieval["independent_non_market_source_family_count"], 0)
        self.assertEqual(
            retrieval["protected_primary_required_count"],
            retrieval["protected_primary_satisfied_count"],
        )
        self.assertEqual(retrieval["freshness_required_count"], retrieval["freshness_satisfied_count"])
        self.assertTrue(retrieval["live_acceptance_ok"])
        self.assertTrue(retrieval["classification_dispatch_allowed"])
        packet = retrieval["retrieval_packets"][0]
        self.assertGreater(packet["search_candidate_url_count"], 0)
        self.assertGreater(packet["fetched_attempt_count"], 0)
        self.assertGreater(packet["admitted_evidence_ref_count"], 0)
        self.assertTrue(packet["external_source_discovery_proven"])
        self.assertFalse(packet["structured_market_metadata_pilot"])
        self.assertTrue(packet["browser_search_executed"])
        self.assertEqual(packet["browser_search_status"], "executed")
        self.assertFalse(packet["direct_url_capture_executed"])
        self.assertEqual(packet["direct_url_capture_status"], "not_executed")
        self.assertFalse(packet["native_research_model_executed"])
        self.assertEqual(packet["native_research_status"], "configured_not_needed")
        self.assertFalse(packet["metadata_classifier_assist_executed"])
        self.assertEqual(packet["metadata_classifier_assist_status"], "not_executed")
        self.assertTrue(packet["source_collation_acceptance_met"])
        self.assertTrue(packet["retrieval_terminal_acceptance_met"])
        self.assertFalse(packet["blocked_when_acceptance_unmet"])
        self.assertFalse(packet["acceptance_unmet_not_blocked"])
        self.assertEqual(packet["acceptance_unmet_dimension_codes"], [])
        self.assertGreater(packet["independent_non_market_source_family_count"], 0)
        self.assertEqual(
            packet["protected_primary_required_count"],
            packet["protected_primary_satisfied_count"],
        )
        self.assertEqual(packet["freshness_required_count"], packet["freshness_satisfied_count"])
        self.assertTrue(packet["leaf_retrieval_statuses"])
        self.assertTrue(all("freshness_status" in row for row in packet["leaf_retrieval_statuses"]))
        self.assertTrue(all("protected_primary_status" in row for row in packet["leaf_retrieval_statuses"]))
        researcher = criteria_report["researcher_runtime_evidence"]
        self.assertGreater(researcher["model_executed_count"], 0)
        self.assertGreater(researcher["runtime_bundle_count"], 0)
        verification = criteria_report["classification_verification_evidence"]
        self.assertTrue(verification["ok"], verification)
        self.assertGreater(verification["verification_artifact_count"], 0)
        scae = criteria_report["scae_runtime_evidence"]
        self.assertGreater(scae["valid_forecast_count"], 0)
        self.assertGreater(scae["delta_ref_count"], 0)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        operator_report = build_ads_operator_review_report(
            self.db_path,
            pipeline_run_id=result["result"]["pipeline_run_id"],
            max_market_snapshot_age_seconds=10_000_000_000,
            max_resolution_sync_age_seconds=10_000_000_000,
        )
        self.assertTrue(operator_report["cases"][0]["retrieval_sufficiency"]["leaf_retrieval_statuses"])

    def test_phase6_runtime_criteria_reports_first_failing_gate(self):
        base = {
            "require_qdt_model_executed": True,
            "require_researcher_model_executed": False,
            "require_scoreable_prediction": False,
            "qdt_evidence": {"ok": True, "qdt_model_executed_count": 1, "runtime_call_model_executed_count": 1},
            "retrieval_evidence": {
                "ok": True,
                "retrieval_packet_count": 1,
                "source_populated_count": 1,
                "classification_dispatch_allowed": False,
            },
            "researcher_evidence": {"ok": False, "model_executed_count": 0, "runtime_bundle_count": 0},
            "scae_evidence": {"ok": True, "valid_forecast_count": 0, "delta_ref_count": 0},
            "prediction_deltas": {"expected_market_predictions": 0, "market_predictions_delta": 0},
            "active": {"active_runs": 0, "active_leases": 0},
            "handoff_report": {"ok": True, "unresolved_output_manifest_refs": []},
            "errors": {"unexpected_count": 0, "allowed_failure_classes": []},
        }

        retrieval_failed = _build_runtime_criteria(
            **{
                **base,
                "retrieval_evidence": {
                    "ok": False,
                    "retrieval_packet_count": 1,
                    "source_populated_count": 0,
                    "classification_dispatch_allowed": False,
                },
            }
        )
        self.assertEqual(
            _first_failing_gate(retrieval_failed),
            "retrieval_source_populated_or_structural_unanswerability",
        )

        researcher_failed = _build_runtime_criteria(
            **{
                **base,
                "retrieval_evidence": {
                    "ok": True,
                    "retrieval_packet_count": 1,
                    "source_populated_count": 1,
                    "classification_dispatch_allowed": True,
                },
            }
        )
        self.assertEqual(
            _first_failing_gate(researcher_failed),
            "researcher_model_executed_if_dispatch_allowed",
        )

        scae_failed = _build_runtime_criteria(
            **{
                **base,
                "researcher_evidence": {"ok": True, "model_executed_count": 1, "runtime_bundle_count": 1},
                "scae_evidence": {"ok": False, "valid_forecast_count": 1, "delta_ref_count": 0},
            }
        )
        self.assertEqual(_first_failing_gate(scae_failed), "scae_delta_refs_if_valid_forecast")

        fully_certified = _build_runtime_criteria(
            **{
                **base,
                "researcher_evidence": {"ok": True, "model_executed_count": 1, "runtime_bundle_count": 1},
                "scae_evidence": {"ok": True, "valid_forecast_count": 1, "delta_ref_count": 2},
            }
        )
        self.assertIsNone(_first_failing_gate(fully_certified))

    def test_phase6_qdt_evidence_rejects_semantically_bad_live_artifact(self):
        qdt_path = Path(self.tempdir.name) / "bad-live-qdt.json"
        runtime_path = Path(self.tempdir.name) / "bad-live-runtime.json"
        qdt_path.write_text(
            json.dumps(
                {
                    "artifact_type": "question_decomposition",
                    "schema_version": "question-decomposition/v1",
                    "adapter_mode": "decomposer_model_runtime_live",
                    "runtime_call_ref": "runtime-call:qdt-bad",
                    "question_specificity_check": {
                        "status": "failed",
                        "reason_codes": ["terminal_verification_leaf_misclassified_as_pre_resolution"],
                    },
                    "research_coverage_check": {
                        "status": "failed",
                        "reason_codes": ["terminal_verification_dominates_unresolved_forecast_qdt"],
                    },
                    "research_coverage_graph": {
                        "market_temporal_state": "unresolved",
                        "coverage_dimensions": ["current_direct_evidence"],
                        "dispatchable_pre_resolution_leaf_ids": ["leaf-victor-final-result"],
                        "terminal_verification_leaf_ids": ["leaf-victor-final-result"],
                    },
                    "required_leaf_questions": [
                        {
                            "leaf_id": "leaf-victor-final-result",
                            "leaf_question": "What did the final official result say about whether Victor Marx won?",
                            "leaf_temporal_role": "terminal_verification",
                            "coverage_dimension": "current_direct_evidence",
                            "research_factor": "final_result_verification",
                            "required_evidence_fields": ["official_final_result"],
                            "evidence_requirements": [
                                {"required_evidence_field": "official_final_result", "pre_cutoff_required": True}
                            ],
                            "classification_targets": ["official_final_result"],
                            "research_sufficiency_requirements": {"requirement_id": "qdt-sufficiency:bad"},
                            "sufficiency_criteria": {
                                "classification_dispatch_requires_sufficiency_certificate": True
                            },
                            "missingness_interpretation": "final result unavailable before resolution",
                            "forbidden_outputs": ["probability", "final_forecast"],
                            "probability_estimate": 0.51,
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        runtime_path.write_text(
            json.dumps(
                {
                    "runtime_call_id": "runtime-call:qdt-bad",
                    "resolved_model_id": "gpt-5.5-high",
                    "mode": "live",
                    "fixture_mode": False,
                    "execution_status": "succeeded",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        evidence = _model_runtime_evidence(
            [
                {
                    "artifact_id": "artifact:qdt-bad",
                    "artifact_type": "question-decomposition",
                    "path": str(qdt_path),
                },
                {
                    "artifact_id": "artifact:runtime-bad",
                    "artifact_type": "model-runtime-call",
                    "path": str(runtime_path),
                },
            ]
        )
        criteria = _build_runtime_criteria(
            require_qdt_model_executed=True,
            require_researcher_model_executed=False,
            require_scoreable_prediction=False,
            qdt_evidence=evidence,
            retrieval_evidence={"ok": True, "source_populated_ok": True, "live_acceptance_ok": True},
            researcher_evidence={"ok": True, "model_executed_count": 1, "runtime_bundle_count": 1},
            scae_evidence={"ok": True, "valid_forecast_count": 1, "delta_ref_count": 1},
            prediction_deltas={"expected_market_predictions": 1, "market_predictions_delta": 1},
            active={"active_runs": 0, "active_leases": 0},
            handoff_report={"ok": True, "unresolved_output_manifest_refs": []},
            errors={"unexpected_count": 0, "allowed_failure_classes": []},
        )

        self.assertTrue(evidence["ok"])
        self.assertFalse(evidence["qdt_end_to_end_quality_ok"])
        qdt_quality = evidence["qdt_results"][0]["qdt_quality"]
        self.assertIn("question_specificity_check_failed", qdt_quality["issue_codes"])
        self.assertIn("research_coverage_check_failed", qdt_quality["issue_codes"])
        self.assertIn("terminal_verification_leaf_dispatched_for_unresolved_market", qdt_quality["issue_codes"])
        self.assertIn("forbidden_qdt_fields_present", qdt_quality["issue_codes"])
        self.assertIn("timing_deadline_constraints", qdt_quality["missing_coverage_dimensions"])
        self.assertIn("source_quality", qdt_quality["missing_coverage_dimensions"])
        self.assertEqual(_first_failing_gate(criteria), "qdt_end_to_end_quality")

    def test_current_audit_gap_summary_captures_qdt_retrieval_and_retry_shape(self):
        qdt_path = Path(self.tempdir.name) / "current-audit-qdt.json"
        runtime_path = Path(self.tempdir.name) / "current-audit-runtime.json"
        retrieval_path = Path(self.tempdir.name) / "current-audit-retrieval.json"
        qdt_path.write_text(
            json.dumps(
                {
                    "artifact_type": "question_decomposition",
                    "schema_version": "question-decomposition/v1",
                    "adapter_mode": "decomposer_model_runtime_live",
                    "runtime_call_ref": "runtime-call:qdt-current-audit",
                    "question_specificity_check": {"status": "passed", "reason_codes": []},
                    "research_coverage_check": {
                        "status": "failed",
                        "coverage_dimensions": ["current_direct_evidence", "source_quality"],
                        "reason_codes": ["required_coverage_dimension_missing:timing_deadline_constraints"],
                    },
                    "research_coverage_graph": {
                        "market_temporal_state": "unresolved",
                        "coverage_dimensions": ["current_direct_evidence", "source_quality"],
                        "dispatchable_pre_resolution_leaf_ids": ["leaf-boi-current"],
                        "terminal_verification_leaf_ids": [],
                    },
                    "required_leaf_questions": [
                        {
                            "leaf_id": "leaf-boi-current",
                            "leaf_question": "What current Bank of Israel evidence bears on the July rate decision?",
                            "leaf_temporal_role": "pre_resolution_forecast_driver",
                            "coverage_dimension": "current_direct_evidence",
                            "research_factor": "current_rate_decision_evidence",
                            "required_evidence_fields": ["current_direct_evidence"],
                            "evidence_requirements": [
                                {"required_evidence_field": "current_direct_evidence", "pre_cutoff_required": True}
                            ],
                            "classification_targets": ["current_direct_evidence"],
                            "research_sufficiency_requirements": {"requirement_id": "qdt-sufficiency:boi"},
                            "sufficiency_criteria": {
                                "classification_dispatch_requires_sufficiency_certificate": True
                            },
                            "missingness_interpretation": "current evidence may be insufficient before cutoff",
                            "forbidden_outputs": ["probability", "final_forecast"],
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        runtime_path.write_text(
            json.dumps(
                {
                    "runtime_call_id": "runtime-call:qdt-current-audit",
                    "resolved_model_id": "gpt-5.5-high",
                    "mode": "live",
                    "fixture_mode": False,
                    "execution_status": "succeeded",
                    "retry_count": 0,
                    "runtime_reason_codes": ["model_executed"],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        retrieval_path.write_text(
            json.dumps(
                {
                    "adapter_mode": "source_populated_live_retrieval_runtime",
                    "retrieval_runtime_summary": {
                        "runtime_mode": "live_retrieval_runtime",
                        "browser_search_executed": True,
                        "browser_search_status": "executed_with_failures",
                        "search_candidate_discovery_status": "executed_with_failures",
                        "search_failure_blocks_sufficiency": True,
                        "native_research_status": "not_configured",
                    },
                    "ads_retrieval_transport_diagnostics": {
                        "search_call_count": 2,
                        "search_failure_count": 1,
                        "search_call_skipped_count": 2,
                        "browser_search_status": "executed_with_failures",
                        "search_candidate_discovery_status": "executed_with_failures",
                        "search_failure_blocks_sufficiency": True,
                        "native_research_status": "not_configured",
                        "search_failure_diagnostics": [
                            {
                                "leaf_id": "leaf-boi-current",
                                "query_variant_id": "query:boi:2",
                                "reason_code": "browser_provider_search_exception",
                                "error_class": "TimeoutError",
                                "elapsed_seconds": 3.25,
                                "detail": "OpenClaw search subprocess timed out after 3.25s",
                            }
                        ],
                        "search_skipped_diagnostics": [
                            {
                                "leaf_id": "leaf-boi-timing",
                                "query_variant_id": "query:boi:3",
                                "reason_code": "search_call_limit_reached",
                            },
                            {
                                "leaf_id": "leaf-boi-staleness",
                                "query_variant_id": "query:boi:4",
                                "reason_code": "search_call_limit_reached",
                            },
                        ],
                    },
                    "search_candidate_urls": [{"url": "https://boi.org.il/en/markets/schedule"}],
                    "browser_retrieval_attempts": [
                        {"navigation_mode": "web_search", "url": "https://boi.org.il/en/markets/schedule"}
                    ],
                    "research_sufficiency_summary": {
                        "classification_dispatch_status": "blocked_insufficient_research",
                        "retrieval_outcome": "insufficient_evidence",
                    },
                    "retrieval_outcome_state": {
                        "retrieval_outcome": "insufficient_evidence",
                        "classification_dispatch_status": "blocked_insufficient_research",
                        "terminal_blocked": True,
                    },
                    "leaf_query_contexts": [
                        {
                            "leaf_id": "leaf-boi-current",
                            "coverage_dimension": "current_direct_evidence",
                            "breadth_targets": {"min_temporally_fresh_sources": 1},
                        },
                        {
                            "leaf_id": "leaf-boi-timing",
                            "coverage_dimension": "timing_deadline_constraints",
                            "breadth_targets": {"protected_primary_required": True},
                        },
                    ],
                    "leaf_retrieval_results": [
                        {
                            "leaf_id": "leaf-boi-current",
                            "admitted_evidence_refs": ["evidence:boi-short"],
                            "selected_evidence_refs": ["evidence:boi-short"],
                        }
                    ],
                    "leaf_evidence_dockets": [
                        {"leaf_id": "leaf-boi-current", "admitted_evidence_refs": ["evidence:boi-short"]}
                    ],
                    "retrieval_evidence_provenance_slices": [
                        {
                            "evidence_ref": "evidence:boi-short",
                            "claim_family_ids": [],
                            "unknown_reason_codes": ["claim_family_unknown_not_counted"],
                        }
                    ],
                    "evidence_chunks": [
                        {
                            "evidence_ref": "evidence:boi-short",
                            "excerpt_policy": "redacted_snippet",
                            "excerpt_char_count": 140,
                        }
                    ],
                    "retrieval_breadth_coverage_slices": [],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        qdt_evidence = _model_runtime_evidence(
            [
                {"artifact_id": "artifact:qdt", "artifact_type": "question-decomposition", "path": str(qdt_path)},
                {"artifact_id": "artifact:runtime", "artifact_type": "model-runtime-call", "path": str(runtime_path)},
            ]
        )
        retrieval_evidence = _retrieval_runtime_evidence(
            [
                {
                    "artifact_id": "artifact:retrieval",
                    "artifact_type": "retrieval-packet",
                    "path": str(retrieval_path),
                }
            ]
        )
        summary = build_current_audit_gap_summary(
            qdt_evidence=qdt_evidence,
            retrieval_evidence=retrieval_evidence,
            errors={
                "events": [
                    {
                        "stage": "retrieval",
                        "retryability": "retryable",
                        "safe_metadata": {
                            "retry_after_seconds": 60,
                            "retry_policy_ref": "auto004-transient-stage-retry/v1",
                        },
                    }
                ]
            },
        )

        self.assertIn("timing_deadline_constraints", summary["qdt_missing_coverage_dimensions"])
        self.assertEqual(summary["search_attempted_count"], 2)
        self.assertEqual(summary["search_succeeded_count"], 1)
        self.assertEqual(summary["search_failed_count"], 1)
        self.assertEqual(summary["search_skipped_by_cap_count"], 2)
        self.assertEqual(summary["native_research_statuses"], ["not_configured"])
        self.assertEqual(summary["short_chunk_admitted_count"], 1)
        self.assertEqual(summary["meaningful_snippet_admitted_count"], 0)
        self.assertEqual(summary["claim_family_extraction_attempted_count"], 1)
        self.assertEqual(summary["claim_family_accepted_count"], 0)
        self.assertFalse(summary["classification_dispatch_allowed"])
        self.assertEqual(summary["retry_summary"]["retry_attempt_count"], 1)
        self.assertEqual(summary["retry_summary"]["retry_backoff_seconds"], [60])
        self.assertEqual(summary["provider_failure_summaries"][0]["error_class"], "TimeoutError")
        self.assertIn("timed out", summary["provider_failure_summaries"][0]["safe_detail_excerpt"])
        self.assertTrue(
            any(
                item["leaf_id"] == "leaf-boi-timing"
                and "source_missing" in item["blocker_codes"]
                and "protected_primary" in item["blocker_codes"]
                for item in summary["per_leaf_sufficiency_blockers"]
            )
        )

    def test_current_audit_gap_summary_uses_qdt_retry_diagnostics(self):
        summary = build_current_audit_gap_summary(
            qdt_evidence={
                "qdt_results": [],
                "runtime_results": [
                    {
                        "retry_count": 1,
                        "retry_diagnostics": [
                            {
                                "event": "local_retry",
                                "component": "qdt_model_runtime",
                                "failure_retryable": True,
                                "failure_class": "timeout",
                                "backoff_seconds": 2.375,
                                "retry_policy_ref": "ads-model-transport-retry/v1",
                            },
                            {
                                "event": "retry_succeeded",
                                "component": "qdt_model_runtime",
                                "final_retry_outcome": "succeeded_after_retry",
                                "retry_policy_ref": "ads-model-transport-retry/v1",
                            },
                        ],
                    }
                ],
            },
            retrieval_evidence={},
            errors={"events": []},
        )

        retry = summary["retry_summary"]
        self.assertEqual(retry["retry_attempt_count"], 1)
        self.assertEqual(retry["retryable_failure_count"], 1)
        self.assertEqual(retry["terminal_retry_exhausted_count"], 0)
        self.assertEqual(retry["qdt_model_transport_retry_count"], 1)
        self.assertEqual(retry["retry_backoff_seconds"], [2.375])
        self.assertEqual(retry["retry_policy_refs"], ["ads-model-transport-retry/v1"])
        self.assertEqual(retry["components"], ["qdt_model_runtime"])
        self.assertEqual(retry["final_retry_outcome"], "retry_recorded")

    def test_real_runtime_report_counts_docket_and_selected_evidence_refs_without_certifying_retrieval(self):
        packet_path = Path(self.tempdir.name) / "retrieval-packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "adapter_mode": "source_populated_live_retrieval_runtime",
                    "retrieval_runtime_summary": {"runtime_mode": "live_retrieval_runtime"},
                    "research_sufficiency_summary": {
                        "classification_dispatch_status": "blocked_insufficient_research"
                    },
                    "leaf_retrieval_results": [
                        {
                            "leaf_id": "leaf-a",
                            "selected_evidence_refs": ["evidence:selected-a"],
                            "selected_evidence": [{"evidence_ref": "evidence:selected-b"}],
                        }
                    ],
                    "leaf_evidence_dockets": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": ["evidence:admitted-a", "evidence:selected-a"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        evidence = _retrieval_runtime_evidence(
            [
                {
                    "artifact_id": "artifact:retrieval",
                    "artifact_type": "retrieval-packet",
                    "path": str(packet_path),
                }
            ]
        )

        packet = evidence["retrieval_packets"][0]
        self.assertEqual(packet["admitted_evidence_ref_count"], 2)
        self.assertEqual(packet["docket_admitted_evidence_ref_count"], 2)
        self.assertEqual(packet["leaf_result_admitted_evidence_ref_count"], 0)
        self.assertEqual(packet["selected_evidence_ref_count"], 2)
        self.assertEqual(packet["reported_evidence_ref_count"], 3)
        self.assertFalse(packet["source_populated_or_structural_unanswerability"])
        self.assertFalse(evidence["ok"])

    def test_live_acceptance_fails_when_unmet_collation_dimensions_advance_unblocked(self):
        packet_path = Path(self.tempdir.name) / "retrieval-packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "adapter_mode": "source_populated_live_retrieval_runtime",
                    "retrieval_runtime_summary": {
                        "runtime_mode": "live_retrieval_runtime",
                        "browser_search_executed": True,
                        "search_candidate_url_count": 1,
                        "web_search_attempt_count": 1,
                    },
                    "search_candidate_urls": [
                        {"url": "https://reuters.com/test-source", "provider_id": "unit-test-search"}
                    ],
                    "browser_retrieval_attempts": [
                        {"url": "https://reuters.com/test-source", "extraction_status": "accepted"}
                    ],
                    "research_sufficiency_summary": {
                        "classification_dispatch_status": "allowed",
                        "retrieval_outcome": "evidence_sufficient",
                    },
                    "retrieval_outcome_state": {
                        "retrieval_outcome": "evidence_sufficient",
                        "classification_dispatch_status": "allowed",
                        "terminal_blocked": False,
                    },
                    "leaf_retrieval_results": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": ["evidence:thin-a"],
                            "selected_evidence_refs": ["evidence:thin-a"],
                            "selected_evidence": [
                                {
                                    "evidence_ref": "evidence:thin-a",
                                    "source_class": "independent_secondary",
                                    "source_family_id": "source-family:reuters.com",
                                    "independence_status": "independent",
                                    "counts_toward_breadth": True,
                                }
                            ],
                        }
                    ],
                    "leaf_evidence_dockets": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": ["evidence:thin-a"],
                        }
                    ],
                    "retrieval_breadth_coverage_slices": [],
                }
            ),
            encoding="utf-8",
        )

        evidence = _retrieval_runtime_evidence(
            [
                {
                    "artifact_id": "artifact:retrieval",
                    "artifact_type": "retrieval-packet",
                    "path": str(packet_path),
                }
            ]
        )

        packet = evidence["retrieval_packets"][0]
        self.assertTrue(packet["source_populated_or_structural_unanswerability"])
        self.assertFalse(packet["source_collation_acceptance_met"])
        self.assertFalse(packet["retrieval_terminal_acceptance_met"])
        self.assertFalse(packet["blocked_when_acceptance_unmet"])
        self.assertTrue(packet["acceptance_unmet_not_blocked"])
        self.assertIn("independent_non_market_source_family", packet["acceptance_unmet_dimension_codes"])
        self.assertEqual(evidence["source_populated_count"], 1)
        self.assertEqual(evidence["source_collation_acceptance_proven_count"], 0)
        self.assertEqual(evidence["acceptance_unmet_not_blocked_count"], 1)
        self.assertTrue(evidence["source_populated_ok"])
        self.assertFalse(evidence["live_acceptance_ok"])
        self.assertFalse(evidence["ok"])

    def test_retrieval_gap_diagnostics_capture_baseline_failure_shape(self):
        packet_path = Path(self.tempdir.name) / "retrieval-packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "adapter_mode": "source_populated_live_retrieval_runtime",
                    "retrieval_runtime_summary": {
                        "runtime_mode": "live_retrieval_runtime",
                        "direct_url_attempt_count": 1,
                        "web_search_attempt_count": 1,
                        "search_candidate_url_count": 0,
                        "browser_search_executed": True,
                        "browser_search_status": "executed_with_failures",
                        "search_candidate_discovery_status": "executed_with_failures",
                        "search_failure_blocks_sufficiency": True,
                        "direct_url_capture_executed": True,
                        "direct_url_capture_status": "executed",
                        "duplicate_canonical_url_omissions": 1,
                    },
                    "ads_retrieval_transport_diagnostics": {
                        "direct_url_candidate_count": 2,
                        "search_candidate_url_count": 0,
                        "browser_search_executed": True,
                        "browser_search_status": "executed_with_failures",
                        "search_candidate_discovery_status": "executed_with_failures",
                        "search_failure_blocks_sufficiency": True,
                    },
                    "ads_retrieval_direct_url_candidates": [
                        {"url": "https://boi.org.il/en/markets/schedule"},
                        {"url": "https://boi.org.il/en/markets/schedule?duplicate=1"},
                    ],
                    "search_candidate_urls": [],
                    "browser_retrieval_attempts": [
                        {
                            "navigation_mode": "direct_url",
                            "url": "https://boi.org.il/en/markets/schedule",
                            "extraction_status": "accepted",
                        },
                        {
                            "navigation_mode": "web_search",
                            "url": "https://search.invalid/empty",
                            "extraction_status": "rejected",
                        },
                    ],
                    "omitted_candidates": [
                        {
                            "canonical_url": "https://boi.org.il/en/markets/schedule",
                            "omission_reason_codes": ["duplicate_canonical_url"],
                        }
                    ],
                    "retrieval_expansion_attempts": [
                        {"leaf_id": "leaf-a", "attempt_status": "planned_not_executed"},
                        {"leaf_id": "leaf-b", "attempt_status": "planned_not_executed"},
                    ],
                    "research_sufficiency_summary": {
                        "classification_dispatch_status": "blocked_insufficient_research",
                        "retrieval_outcome": "insufficient_evidence",
                    },
                    "retrieval_outcome_state": {
                        "retrieval_outcome": "insufficient_evidence",
                        "classification_dispatch_status": "blocked_insufficient_research",
                        "terminal_blocked": True,
                    },
                    "leaf_retrieval_results": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": [
                                "evidence:hash-only",
                                "evidence:short",
                                "evidence:meaningful",
                            ],
                            "selected_evidence_refs": [
                                "evidence:hash-only",
                                "evidence:short",
                                "evidence:meaningful",
                            ],
                        }
                    ],
                    "leaf_evidence_dockets": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": [
                                "evidence:hash-only",
                                "evidence:short",
                                "evidence:meaningful",
                            ],
                        }
                    ],
                    "evidence_chunks": [
                        {
                            "evidence_ref": "evidence:hash-only",
                            "excerpt_policy": "hash_only",
                            "excerpt_char_count": 12,
                        },
                        {
                            "evidence_ref": "evidence:short",
                            "excerpt_policy": "redacted_snippet",
                            "excerpt_char_count": 96,
                        },
                        {
                            "evidence_ref": "evidence:meaningful",
                            "excerpt_policy": "redacted_snippet",
                            "excerpt_char_count": 320,
                        },
                    ],
                    "retrieval_breadth_coverage_slices": [],
                }
            ),
            encoding="utf-8",
        )

        evidence = _retrieval_runtime_evidence(
            [
                {
                    "artifact_id": "artifact:retrieval",
                    "artifact_type": "retrieval-packet",
                    "path": str(packet_path),
                }
            ]
        )

        packet = evidence["retrieval_packets"][0]
        self.assertTrue(packet["browser_search_executed"])
        self.assertEqual(packet["browser_search_status"], "executed_with_failures")
        self.assertEqual(packet["search_candidates_materialized_count"], 0)
        self.assertEqual(packet["planned_not_executed_expansion_count"], 2)
        self.assertEqual(packet["hash_only_admitted_count"], 1)
        self.assertEqual(packet["short_chunk_admitted_count"], 2)
        self.assertEqual(packet["meaningful_snippet_admitted_count"], 1)
        self.assertEqual(packet["canonical_fetch_duplicate_count"], 1)
        self.assertEqual(packet["classification_dispatch_status"], "blocked_insufficient_research")
        self.assertTrue(packet["blocked_when_acceptance_unmet"])
        self.assertIn("independent_non_market_source_family", packet["acceptance_unmet_dimension_codes"])
        self.assertIn("search_candidate_discovery", packet["acceptance_unmet_dimension_codes"])
        self.assertEqual(packet["search_candidate_discovery_status"], "executed_with_failures")
        self.assertTrue(packet["search_candidate_discovery_blocked"])
        self.assertEqual(evidence["search_candidates_materialized_count"], 0)
        self.assertEqual(evidence["planned_not_executed_expansion_count"], 2)
        self.assertEqual(evidence["hash_only_admitted_count"], 1)
        self.assertEqual(evidence["short_chunk_admitted_count"], 2)
        self.assertEqual(evidence["meaningful_snippet_admitted_count"], 1)
        self.assertEqual(evidence["canonical_fetch_duplicate_count"], 1)
        self.assertFalse(evidence["live_acceptance_ok"])
        self.assertFalse(evidence["ok"])

    def test_structured_metadata_pilot_does_not_prove_external_source_discovery(self):
        packet_path = Path(self.tempdir.name) / "retrieval-packet.json"
        packet_path.write_text(
            json.dumps(
                {
                    "adapter_mode": "structured_market_metadata_pilot_retrieval",
                    "retrieval_runtime_summary": {
                        "runtime_mode": "structured_market_metadata_pilot",
                        "structured_market_metadata_pilot": True,
                        "external_source_discovery_proven": False,
                    },
                    "research_sufficiency_summary": {
                        "classification_dispatch_status": "allowed"
                    },
                    "leaf_retrieval_results": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": ["evidence:pilot-a"],
                            "selected_evidence_refs": ["evidence:pilot-a"],
                        }
                    ],
                    "leaf_evidence_dockets": [
                        {
                            "leaf_id": "leaf-a",
                            "admitted_evidence_refs": ["evidence:pilot-a"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        evidence = _retrieval_runtime_evidence(
            [
                {
                    "artifact_id": "artifact:retrieval",
                    "artifact_type": "retrieval-packet",
                    "path": str(packet_path),
                }
            ]
        )

        packet = evidence["retrieval_packets"][0]
        self.assertTrue(packet["structured_market_metadata_pilot"])
        self.assertFalse(packet["external_source_discovery_proven"])
        self.assertTrue(packet["classification_dispatch_allowed"])
        self.assertEqual(packet["admitted_evidence_ref_count"], 1)
        self.assertFalse(packet["source_populated_or_structural_unanswerability"])
        self.assertEqual(evidence["structured_market_metadata_pilot_packet_count"], 1)
        self.assertEqual(evidence["external_source_discovery_proven_count"], 0)
        self.assertEqual(evidence["source_populated_count"], 0)
        self.assertFalse(evidence["ok"])

    def test_phase3_fixture_certified_retrieval_writes_runtime_bundle_manifest(self):
        config = self.config(require_scoreable_prediction=False, require_manifest_handoffs=True)
        handlers = build_production_readiness_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            live_fixture_retrieval=True,
            block_at_leaf_research_barrier=True,
            researcher_swarm_runtime_runner=_fake_researcher_runtime_bundle,
        )
        market = self.conn.execute(
            "SELECT id, platform, external_market_id FROM markets WHERE external_market_id = ?",
            ("operational-canary",),
        ).fetchone()
        snapshot = self.conn.execute(
            "SELECT id, observed_at FROM market_snapshots WHERE market_id = ?",
            (market[0],),
        ).fetchone()
        lease = {
            "case_id": "case-phase3-runtime",
            "case_key": f"{market[1]}:{market[2]}",
            "dispatch_id": "dispatch-phase3-runtime",
            "market_id": market[0],
            "selected_snapshot_id": snapshot[0],
            "selected_snapshot_observed_at": snapshot[1],
            "forecast_timestamp": config.forecast_timestamp,
        }
        context = SimpleNamespace(pipeline_run_id="pipeline-run-phase3-runtime")
        stage_outputs = {}
        for stage in (
            "evidence_packet",
            "policy_context",
            "related_market_context",
            "decomposition",
            "retrieval",
            "researcher_classification",
        ):
            stage_outputs[stage] = handlers[stage](
                conn=self.conn,
                context=context,
                lease=lease,
                stage_outputs=stage_outputs,
            )

        row = self.conn.execute(
            """
            SELECT artifact_path, metadata
            FROM case_artifact_manifest
            WHERE artifact_type = 'researcher-swarm-runtime-bundle'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        prediction_count = self.conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]

        self.assertIsNotNone(row)
        payload = json.loads(Path(row["artifact_path"]).read_text(encoding="utf-8"))
        metadata = json.loads(row["metadata"])
        self.assertEqual(payload["artifact_type"], "researcher_swarm_runtime_bundle")
        self.assertEqual(metadata["runtime_bundle_count"], 1)
        self.assertEqual(metadata["runtime_sidecar_count"], 1)
        self.assertGreater(metadata["runtime_model_executed_count"], 0)
        self.assertFalse(payload["proceed_to_verification_scae"])
        self.assertEqual(prediction_count, 0)

    def test_phase4_runtime_sidecars_feed_verified_scae_evidence_delta_refs(self):
        config = self.config(require_scoreable_prediction=False, require_manifest_handoffs=True)
        handlers = build_production_readiness_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            live_fixture_retrieval=True,
            block_at_leaf_research_barrier=True,
            researcher_swarm_runtime_runner=_fake_researcher_runtime_bundle_all_accepted,
        )
        market = self.conn.execute(
            "SELECT id, platform, external_market_id FROM markets WHERE external_market_id = ?",
            ("operational-canary",),
        ).fetchone()
        snapshot = self.conn.execute(
            "SELECT id, observed_at FROM market_snapshots WHERE market_id = ?",
            (market[0],),
        ).fetchone()
        lease = {
            "case_id": "case-phase4-runtime",
            "case_key": f"{market[1]}:{market[2]}",
            "dispatch_id": "dispatch-phase4-runtime",
            "market_id": market[0],
            "selected_snapshot_id": snapshot[0],
            "selected_snapshot_observed_at": snapshot[1],
            "forecast_timestamp": config.forecast_timestamp,
        }
        context = SimpleNamespace(pipeline_run_id="pipeline-run-phase4-runtime")
        stage_outputs = {}
        for stage in (
            "evidence_packet",
            "policy_context",
            "related_market_context",
            "decomposition",
            "retrieval",
            "researcher_classification",
            "classification_verification",
            "scae",
        ):
            stage_outputs[stage] = handlers[stage](
                conn=self.conn,
                context=context,
                lease=lease,
                stage_outputs=stage_outputs,
            )

        verification_row = self.conn.execute(
            """
            SELECT artifact_path
            FROM case_artifact_manifest
            WHERE stage = 'classification_verification'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        scae_row = self.conn.execute(
            """
            SELECT artifact_path
            FROM case_artifact_manifest
            WHERE stage = 'scae'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        prediction_count = self.conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]

        verification = json.loads(Path(verification_row["artifact_path"]).read_text(encoding="utf-8"))
        scae = json.loads(Path(scae_row["artifact_path"]).read_text(encoding="utf-8"))
        self.assertEqual(verification["artifact_type"], "classification_verification_runtime_bundle")
        self.assertEqual(verification["verification_status"], "runtime_bundle_scae_ready")
        self.assertGreater(len(verification["classification_matrix"]["classification_slices"]), 0)
        self.assertGreater(len(verification["direction_verification_slices"]), 0)
        self.assertGreater(len(verification["quality_verification_slices"]), 0)
        self.assertGreater(len(verification["research_sufficiency_reconciliation_slices"]), 0)
        self.assertTrue(verification["scae_readiness_reconciliation"]["ready_for_scae"])
        self.assertGreater(len(scae["scae_evidence_delta_candidate_slice_refs"]), 0)
        self.assertGreater(scae["scae_leaf_cluster_netting_cluster_count"], 0)
        self.assertEqual(scae["scoreable_forecast_output"], 0)
        self.assertEqual(prediction_count, 0)

    def test_phase3_failed_researcher_transport_is_retryable_and_writes_no_scae_ready_output(self):
        def failing_runtime(**_kwargs):
            raise RuntimeError("researcher model runtime failed: fake transport timeout")

        config = self.config(
            require_scoreable_prediction=False,
            require_manifest_handoffs=True,
        )
        handlers = build_production_readiness_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            live_fixture_retrieval=True,
            block_at_leaf_research_barrier=True,
            researcher_swarm_runtime_runner=failing_runtime,
        )
        handlers["researcher_classification"] = wrap_production_stage_handler(
            "researcher_classification",
            handlers["researcher_classification"],
        )

        result = run_one_case_canary(config, handlers)

        self.assertFalse(result["ok"])
        self.assertIn("terminal_status was 'auto004_retry_scheduled'", result["errors"])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            status = conn.execute(
                """
                SELECT status, reason_codes, metadata
                FROM v2_stage_status_snapshots
                WHERE stage = 'researcher_classification'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            retry_event = conn.execute(
                """
                SELECT event_type, failure_class, safe_exception_class, safe_metadata
                FROM v2_stage_execution_events
                WHERE stage = 'researcher_classification'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            runtime_bundle_count = conn.execute(
                "SELECT COUNT(*) FROM case_artifact_manifest WHERE artifact_type = 'researcher-swarm-runtime-bundle'"
            ).fetchone()[0]
            scae_count = conn.execute(
                "SELECT COUNT(*) FROM case_artifact_manifest WHERE stage = 'scae'"
            ).fetchone()[0]
            prediction_count = conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]

        self.assertIsNotNone(status)
        self.assertIsNotNone(retry_event)
        status_metadata = json.loads(status["metadata"])
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(json.loads(status["reason_codes"]), ["ads_production_retryable_model_transport"])
        self.assertEqual(status_metadata["safe_reason_code"], "ads_production_retryable_model_transport")
        self.assertEqual(retry_event["event_type"], "retry_scheduled")
        self.assertEqual(retry_event["failure_class"], "retryable_model_transport")
        self.assertEqual(retry_event["safe_exception_class"], "RetryableStageError")
        self.assertEqual(runtime_bundle_count, 0)
        self.assertEqual(scae_count, 0)
        self.assertEqual(prediction_count, 0)

    def test_real_runtime_criteria_requires_researcher_model_execution_when_requested(self):
        config = self.config(
            require_scoreable_prediction=False,
            require_manifest_handoffs=True,
            require_real_runtime_canary_criteria=True,
            require_researcher_model_executed=True,
        )
        handlers = build_true_production_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            decomposer_runtime_transport_response_path=self._decomposer_live_response_path(),
            retrieval_browser_provider=_ConfiguredEmptyRetrievalProvider(),
            native_candidate_provider=_EmptyNativeCandidateProvider(),
        )

        result = run_one_case_canary(config, handlers)

        self.assertFalse(result["ok"])
        self.assertIn("real_runtime_canary:researcher_model_runtime_not_verified", result["errors"])
        self.assertIn("researcher_model_runtime_not_verified", result["real_runtime_canary_report"]["issues"])

    def test_operator_review_blocks_non_scae_probability_authority(self):
        config = self.config(
            require_scoreable_prediction=False,
            require_manifest_handoffs=True,
            require_real_runtime_canary_criteria=False,
        )
        handlers = build_true_production_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
            decomposer_runtime_transport_response_path=self._decomposer_live_response_path(),
            retrieval_browser_provider=_ConfiguredEmptyRetrievalProvider(),
            native_candidate_provider=_EmptyNativeCandidateProvider(),
        )
        result = run_one_case_canary(config, handlers)
        self.assertTrue(result["ok"], result["errors"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE forecast_decision_records SET probability_source = ?",
                ("manual_override",),
            )
            conn.commit()

        report = build_ads_operator_review_report(
            self.db_path,
            pipeline_run_id=result["result"]["pipeline_run_id"],
            max_market_snapshot_age_seconds=10_000_000_000,
            max_resolution_sync_age_seconds=10_000_000_000,
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["scheduler_may_continue"])
        self.assertEqual(report["alert_counts_by_severity"]["blocker"], 1)
        self.assertIn("non_scae_probability_authority", {alert["code"] for alert in report["alerts"]})

    def test_production_pilot_factory_writes_scoreable_prediction_with_manifest_handoffs(self):
        config = self.config(require_scoreable_prediction=True, require_manifest_handoffs=True)
        handlers = build_production_pilot_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        with sqlite3.connect(self.db_path) as conn:
            decision = conn.execute(
                """
                SELECT production_persistence_status, production_forecast_persisted,
                       production_forecast_prob, non_scoreable_reason_code
                FROM forecast_decision_records
                """
            ).fetchone()
            prediction = conn.execute(
                """
                SELECT prediction_source, prediction_label, predicted_probability
                FROM market_predictions
                """
            ).fetchone()
            retrieval_row = conn.execute(
                """
                SELECT artifact_path
                FROM case_artifact_manifest
                WHERE artifact_type = 'retrieval-packet'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            self.assertEqual(decision[0], "production_forecast_persisted_from_scae")
            self.assertEqual(decision[1], 1)
            self.assertIsNotNone(decision[2])
            self.assertIsNone(decision[3])
            self.assertEqual(prediction[0], "ads_pipeline")
            self.assertEqual(prediction[1], "v2_scae")
            self.assertIsNotNone(prediction[2])
            self.assertIsNotNone(retrieval_row)

        retrieval_payload = json.loads(Path(retrieval_row[0]).read_text(encoding="utf-8"))
        boundary = retrieval_payload["structured_market_metadata_pilot_proof_boundary"]
        runtime_summary = retrieval_payload["retrieval_runtime_summary"]
        self.assertEqual(retrieval_payload["adapter_mode"], "structured_market_metadata_pilot_retrieval")
        self.assertFalse(boundary["external_source_discovery_proven"])
        self.assertFalse(boundary["counts_as_real_retrieval_canary_proof"])
        self.assertFalse(runtime_summary["external_source_discovery_proven"])
        self.assertEqual(runtime_summary["source_discovery_proof_status"], "not_proven_structured_market_metadata_pilot")
        self.assertEqual(
            retrieval_payload["research_sufficiency_summary"]["classification_dispatch_status"],
            "allowed",
        )
        material_unknowns_coverage = next(
            item
            for item in retrieval_payload["retrieval_breadth_coverage_slices"]
            if item["leaf_id"] == "leaf-material-unknowns"
        )
        self.assertTrue(material_unknowns_coverage["breadth_certified"])
        self.assertFalse(
            any("unknown" in source_id for source_id in material_unknowns_coverage["independent_source_family_ids"])
        )
        self.assertFalse(
            any("unknown" in claim_id for claim_id in material_unknowns_coverage["independent_claim_family_ids"])
        )

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertGreaterEqual(
            report["manifest_counts_by_validation_status"].get("valid", 0),
            len(ADS_PIPELINE_STAGE_ORDER),
        )

    def test_production_pilot_factory_runs_bounded_batch(self):
        self._seed_market(
            external_market_id="operational-pilot-b",
            slug="operational-pilot-b",
            title="Will the second production pilot complete?",
            best_bid=0.58,
            best_ask=0.62,
        )
        self.conn.commit()
        config = self.config(require_scoreable_prediction=True, max_cases=2, require_manifest_handoffs=True)
        handlers = build_production_pilot_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["terminal_status"], "auto005_max_cases_complete")
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 2)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 2)


if __name__ == "__main__":
    unittest.main()
