"""Static canonical machine-artifact checks for ADS v2."""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
for relative in (
    "decomposer/scripts",
    "researcher-swarm/scripts",
    "orchestrator/scripts",
    "SCAE/scripts",
):
    candidate = str(REPO_ROOT / relative)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
)
from ads_decomposer.qdt import (  # noqa: E402
    build_fixture_qdt_candidate,
    select_qdt_candidate,
    validate_question_decomposition,
)
from researcher_swarm.assignments import (  # noqa: E402
    build_leaf_research_assignments,
    validate_leaf_research_assignment,
)
from researcher_swarm.classification import (  # noqa: E402
    build_researcher_sidecar_v2,
    compute_classification_matrix_digest,
    compute_researcher_sidecar_digest,
    validate_researcher_sidecar_v2,
)
from researcher_swarm.classification_matrix import materialize_classification_matrix  # noqa: E402
from researcher_swarm.coverage import (  # noqa: E402
    build_researcher_evidence_review_coverage_proof_bundle,
    validate_researcher_evidence_review_coverage_proof_bundle,
)
from researcher_swarm.isolation import (  # noqa: E402
    build_researcher_context_isolation_audit,
    validate_researcher_context_isolation_audit,
)
from researcher_swarm.model_context import resolve_researcher_leaf_nli_model_context  # noqa: E402
from researcher_swarm.retrieval import (  # noqa: E402
    build_evidence_chunk,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    build_retrieval_query_contexts,
    finalize_retrieval_packet_for_dispatch,
    validate_retrieval_packet,
)

from predquant.model_provenance_trace import (  # noqa: E402
    build_model_provenance_trace,
    prefixed_sha256,
    validate_model_provenance_trace,
)
from predquant.decision_gate import (  # noqa: E402
    build_decision_gate,
    validate_decision_gate_artifact,
)
from predquant.synthesis_annotation import (  # noqa: E402
    build_synthesis_annotation,
    validate_synthesis_annotation,
)
from scae.persistence import write_forecast_decision  # noqa: E402


CANONICAL_MACHINE_ARTIFACT_SCAN_SCHEMA_VERSION = "ads-canonical-machine-artifact-scan/v1"
CANONICAL_MACHINE_ARTIFACT_FIXTURE_ID = "FIX-031"
CANONICAL_MACHINE_ARTIFACT_BLOCKER_ID = "BLK-027"
NON_SCAE_AUTHORITY_SCAN_SCHEMA_VERSION = "ads-non-scae-authority-scan/v1"
NON_SCAE_AUTHORITY_BLOCKER_ID = "BLK-001"

ACTIVE_AUTHORITY_KEYS = {
    "own_probability",
    "leaf_probability",
    "macro_probability",
    "final_macro_probability",
    "forecast_probability",
    "fair_value",
    "probability_interval",
    "decision_recommendation",
    "researcher_reassembled_probability",
    "scae_delta",
}


def _fixture_handoff() -> dict[str, Any]:
    return {
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


def _fixture_evidence_packet() -> dict[str, Any]:
    return {
        "artifact_type": "evidence_packet",
        "schema_version": "evidence-packet/v2",
        "case_id": "case-1",
        "dispatch_id": "dispatch-1",
        "forecast_timestamp": "2026-06-24T12:00:00+00:00",
        "source_cutoff_timestamp": "2026-06-24T12:00:00+00:00",
        "market_rules": {"resolution_url": "https://example.com/rules"},
        "official_source_hints": ["https://example.com/official"],
    }


def _evidence(context: dict[str, Any], *, suffix: str, source_class: str) -> dict[str, Any]:
    family_suffix = f"{context['leaf_id']}-{suffix}"
    item = build_retrieval_evidence_item(
        case_id="case-1",
        dispatch_id="dispatch-1",
        leaf_id=context["leaf_id"],
        parent_branch_id=context["parent_branch_id"],
        retrieval_transport="browser",
        transport_attempt_ref=f"browser:{family_suffix}",
        requested_url=f"https://{suffix}.example/{context['leaf_id']}",
        final_url=f"https://{suffix}.example/{context['leaf_id']}",
        canonical_url=f"https://{suffix}.example/{context['leaf_id']}",
        source_family_id=f"source-family-{family_suffix}",
        source_class=source_class,
        temporal_gate_status="pass",
        source_published_at="2026-06-24T11:30:00+00:00",
        captured_at="2026-06-24T12:01:00+00:00",
        artifact_generated_at="2026-06-24T12:01:00+00:00",
        retrieval_capture_for_dispatch=True,
        claim_family_resolution_refs=[f"claim-family-{family_suffix}"],
        independence_status="independent",
        admission_reason_codes=["canonical_machine_fixture"],
    )
    item["claim_family_ids"] = [f"claim-family-{family_suffix}"]
    item["claim_family_resolution_method"] = "manual_fixture"
    item["counts_toward_breadth"] = True
    if source_class == "official_or_primary":
        item["deterministic_source_class_proof"] = True
        item["source_class_resolution_method"] = "manual_fixture"
    return item


def _build_qdt() -> dict[str, Any]:
    return select_qdt_candidate([build_fixture_qdt_candidate(_fixture_handoff())])


def _attach_fixture_chunks(packet: dict[str, Any]) -> None:
    chunks: list[dict[str, Any]] = []
    for result in packet.get("leaf_retrieval_results", []):
        if not isinstance(result, dict):
            continue
        for evidence in result.get("selected_evidence", []):
            if not isinstance(evidence, dict) or not evidence.get("evidence_ref"):
                continue
            text = (
                f"Canonical fixture snippet for {evidence['leaf_id']} from "
                f"{evidence['source_class']} source {evidence['source_family_id']}. "
                "The bounded fixture source includes enough detail for researcher classification, "
                "claim extraction, and certified snippet assignment without exposing unbounded page text. "
                * 4
            )
            chunk = build_evidence_chunk(
                evidence_ref=str(evidence["evidence_ref"]),
                content_artifact_ref=f"artifact:canonical-content:{evidence['evidence_ref']}",
                chunk_index=0,
                char_start=0,
                char_end=len(text),
                text=text,
                excerpt_policy="bounded_excerpt",
            )
            evidence["chunk_refs"] = [chunk["chunk_ref"]]
            chunks.append(chunk)
    packet["evidence_chunks"] = chunks


def _build_retrieval_packet(qdt: dict[str, Any], evidence_packet: dict[str, Any]) -> dict[str, Any]:
    selected = []
    for context in build_retrieval_query_contexts(qdt, evidence_packet=evidence_packet):
        selected.append(_evidence(context, suffix="official", source_class="official_or_primary"))
        selected.append(_evidence(context, suffix="independent", source_class="independent_secondary"))
    packet = build_retrieval_packet(
        qdt,
        evidence_packet=evidence_packet,
        selected_evidence=selected,
        question_decomposition_artifact_id="artifact:qdt-1",
        policy_context_ref="artifact:profile-1",
    )
    _attach_fixture_chunks(packet)
    return finalize_retrieval_packet_for_dispatch(packet)


def _provenance_by_evidence_ref(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["evidence_ref"]: item for item in packet["retrieval_evidence_provenance_slices"]}


def _first_assignment_evidence(
    packet: dict[str, Any],
    assignment: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence_ref = assignment["assigned_evidence_refs"][0]["evidence_ref"]
    provenance = _provenance_by_evidence_ref(packet)[evidence_ref]
    for result in packet["leaf_retrieval_results"]:
        for evidence in result["selected_evidence"]:
            if evidence["evidence_ref"] == evidence_ref:
                return evidence, provenance
    raise ValueError(f"missing selected evidence for {evidence_ref}")


def _leaf_by_id(qdt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {leaf["leaf_id"]: leaf for leaf in qdt["required_leaf_questions"]}


def _classification(qdt: dict[str, Any], packet: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    evidence, provenance = _first_assignment_evidence(packet, assignment)
    leaf = _leaf_by_id(qdt)[assignment["leaf_id"]]
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
            "field_name": "status",
            "value": "confirmed",
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


def _coverage(assignment: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = [item["evidence_ref"] for item in assignment["assigned_evidence_refs"]]
    return {
        "coverage_proof_id": assignment["artifact_outputs"]["coverage_proof_ref"],
        "leaf_id": assignment["leaf_id"],
        "research_sufficiency_certificate_ref": assignment["research_sufficiency_certificate_ref"],
        "retrieval_breadth_coverage_ref": assignment["retrieval_breadth_coverage_ref"],
        "evidence_refs_assigned": list(evidence_refs),
        "evidence_refs_reviewed": list(evidence_refs),
        "source_class_ids_reviewed": sorted({item["source_class"] for item in assignment["assigned_evidence_refs"]}),
        "claim_family_ids_reviewed": sorted(
            item["claim_family_id"] for item in assignment["assigned_evidence_refs"] if item.get("claim_family_id")
        ),
        "source_family_ids_reviewed": sorted({item["source_family_id"] for item in assignment["assigned_evidence_refs"]}),
        "requirements_reviewed": list(assignment["sufficiency_requirement_refs"]),
        "requirements_answered": list(assignment["sufficiency_requirement_refs"]),
        "requirements_unanswered": [],
        "required_value_fields_extracted": list(assignment["required_value_field_ids"]),
        "required_negative_checks_completed": list(assignment["required_negative_check_ids"]),
        "source_gap_flags": [],
        "structural_unanswerability_acknowledged": False,
        "machine_readability_status": "schema_valid",
    }


def _build_researcher_artifacts(
    qdt: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    assignments = build_leaf_research_assignments(qdt=qdt, retrieval_packet=packet)
    audits = [build_researcher_context_isolation_audit(assignment) for assignment in assignments]
    assignments_by_leaf = {assignment["leaf_id"]: assignment for assignment in assignments}
    leaf_ids = [leaf["leaf_id"] for leaf in qdt["required_leaf_questions"]]
    model_context = resolve_researcher_leaf_nli_model_context()
    sidecar = build_researcher_sidecar_v2(
        qdt=qdt,
        required_question_classifications=[
            _classification(qdt, packet, assignments_by_leaf[leaf_id]) for leaf_id in leaf_ids
        ],
        coverage_proofs=[_coverage(assignments_by_leaf[leaf_id]) for leaf_id in leaf_ids],
        model_execution_context_ref="artifact:model-execution-context:researcher-leaf-nli",
        model_execution_context=model_context,
    )
    sidecar["classification_matrix_digest"] = compute_classification_matrix_digest(
        sidecar["required_question_classifications"]
    )
    sidecar["sidecar_digest"] = compute_researcher_sidecar_digest(sidecar)
    matrix = materialize_classification_matrix([sidecar], qdt, packet)
    coverage_bundle = build_researcher_evidence_review_coverage_proof_bundle(
        qdt=qdt,
        sidecars=[sidecar],
        classification_matrix=matrix,
        assignments=assignments,
        isolation_audits=audits,
        retrieval_packet=packet,
    )
    return {
        "assignments": assignments,
        "isolation_audits": audits,
        "sidecar": sidecar,
        "classification_matrix": matrix,
        "coverage_bundle": coverage_bundle,
        "researcher_model_execution_context": model_context,
    }


def _trace_model_record(
    context: dict[str, Any],
    *,
    output_artifact_id: str,
    output_artifact_hash: str,
    input_artifact_hashes: dict[str, str],
) -> dict[str, Any]:
    record = copy.deepcopy(context)
    record["input_artifact_hashes"] = dict(input_artifact_hashes)
    record["output_artifact_hash"] = output_artifact_hash
    record["output_artifact_id"] = output_artifact_id
    return {"model_execution_context": record}


def _build_model_trace(
    qdt: dict[str, Any],
    sidecar: dict[str, Any],
    researcher_model_context: dict[str, Any],
) -> dict[str, Any]:
    qdt_hash = prefixed_sha256(qdt)
    sidecar_hash = prefixed_sha256(sidecar)
    decomposer_inputs = {
        artifact_id: "sha256:" + str(index + 1) * 64
        for index, artifact_id in enumerate(qdt["model_execution_context"]["input_manifest_ids"])
    }
    researcher_inputs = {
        "artifact:qdt-1": qdt_hash,
        "artifact:retrieval-packet-1": "sha256:" + "8" * 64,
    }
    return build_model_provenance_trace(
        model_execution_contexts=[
            _trace_model_record(
                qdt["model_execution_context"],
                output_artifact_id="artifact:qdt-1",
                output_artifact_hash=qdt_hash,
                input_artifact_hashes=decomposer_inputs,
            ),
            _trace_model_record(
                researcher_model_context,
                output_artifact_id=sidecar["sidecar_id"],
                output_artifact_hash=sidecar_hash,
                input_artifact_hashes=researcher_inputs,
            ),
        ]
    )


def _active_forbidden_key_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower()
            if not normalized.startswith("forbidden_") and normalized in ACTIVE_AUTHORITY_KEYS:
                paths.append(f"{path}.{key_text}")
            paths.extend(_active_forbidden_key_paths(child, f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_active_forbidden_key_paths(child, f"{path}[{index}]"))
    return paths


def _check_result(name: str, valid: bool, errors: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if valid else "failed",
        "errors": list(errors or []),
    }


def _fixture_scae_ledger() -> dict[str, Any]:
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


def _fixture_synthesis(scae_ledger: dict[str, Any]) -> dict[str, Any]:
    return build_synthesis_annotation(
        scae_ledger=scae_ledger,
        qualitative_annotations=[
            {
                "annotation_type": "key_evidence",
                "summary": "Official-source coverage is the main qualitative leverage point.",
                "leverage_direction": "supports_yes_qualitatively",
                "source_refs": ["researcher-sidecar:1"],
                "reason_codes": ["qualitative_leverage_only"],
            }
        ],
        generated_at="2026-06-25T12:01:00+00:00",
    )


def _expect_rejection(name: str, expected_fragment: str, callback) -> dict[str, Any]:
    try:
        callback()
    except Exception as exc:  # noqa: BLE001 - scan reports expected validator failures.
        if expected_fragment in str(exc):
            return _check_result(name, True)
        return _check_result(name, False, [f"unexpected rejection: {exc}"])
    return _check_result(name, False, [f"expected rejection containing {expected_fragment!r}"])


def _write_forecast_decision_with_replacement_context(
    scae_ledger: dict[str, Any],
    decision_gate: dict[str, Any],
) -> None:
    with sqlite3.connect(":memory:") as conn:
        write_forecast_decision(conn, scae_ledger, decision_gate)


def build_canonical_machine_artifact_report() -> dict[str, Any]:
    """Build a deterministic static scan report for canonical ADS machine artifacts."""

    checks: list[dict[str, Any]] = []
    qdt = _build_qdt()
    evidence_packet = _fixture_evidence_packet()
    retrieval_packet = _build_retrieval_packet(qdt, evidence_packet)
    researcher = _build_researcher_artifacts(qdt, retrieval_packet)
    model_trace = _build_model_trace(
        qdt,
        researcher["sidecar"],
        researcher["researcher_model_execution_context"],
    )

    qdt_validation = validate_question_decomposition(qdt)
    checks.append(_check_result("question_decomposition_schema", qdt_validation.valid, qdt_validation.errors))
    retrieval_validation = validate_retrieval_packet(retrieval_packet)
    checks.append(_check_result("retrieval_packet_schema", retrieval_validation.valid, retrieval_validation.errors))
    for index, assignment in enumerate(researcher["assignments"]):
        validation = validate_leaf_research_assignment(assignment)
        checks.append(_check_result(f"leaf_assignment_{index}", validation.valid, validation.errors))
    for index, audit in enumerate(researcher["isolation_audits"]):
        validation = validate_researcher_context_isolation_audit(audit)
        checks.append(_check_result(f"context_isolation_audit_{index}", validation.valid, validation.errors))
    sidecar_validation = validate_researcher_sidecar_v2(researcher["sidecar"], qdt)
    checks.append(_check_result("researcher_sidecar_schema", sidecar_validation.valid, sidecar_validation.errors))
    coverage_validation = validate_researcher_evidence_review_coverage_proof_bundle(researcher["coverage_bundle"])
    checks.append(_check_result("researcher_coverage_bundle", coverage_validation.valid, coverage_validation.errors))
    try:
        validate_model_provenance_trace(model_trace)
        checks.append(_check_result("model_provenance_trace", True))
    except Exception as exc:  # pragma: no cover - failure path is reported, not re-raised.
        checks.append(_check_result("model_provenance_trace", False, [str(exc)]))

    scanned_artifacts = {
        "question_decomposition": qdt,
        "retrieval_packet": retrieval_packet,
        "leaf_research_assignments": researcher["assignments"],
        "context_isolation_audits": researcher["isolation_audits"],
        "researcher_sidecar": researcher["sidecar"],
        "classification_matrix": researcher["classification_matrix"],
        "coverage_bundle": researcher["coverage_bundle"],
        "model_provenance_trace": model_trace,
    }
    forbidden_paths = _active_forbidden_key_paths(scanned_artifacts)
    if forbidden_paths:
        checks.append(_check_result("active_authority_key_scan", False, forbidden_paths))
    else:
        checks.append(_check_result("active_authority_key_scan", True))

    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {
        "schema_version": CANONICAL_MACHINE_ARTIFACT_SCAN_SCHEMA_VERSION,
        "fixture_id": CANONICAL_MACHINE_ARTIFACT_FIXTURE_ID,
        "blocker_id": CANONICAL_MACHINE_ARTIFACT_BLOCKER_ID,
        "status": status,
        "check_count": len(checks),
        "checks": checks,
        "artifact_summary": {
            "required_leaf_count": len(qdt["required_leaf_questions"]),
            "assignment_count": len(researcher["assignments"]),
            "coverage_proof_count": len(researcher["coverage_bundle"]["coverage_proofs"]),
            "model_trace_context_count": model_trace["context_count"],
            "classification_matrix_digest": researcher["classification_matrix"]["matrix_digest"],
            "coverage_bundle_digest": researcher["coverage_bundle"]["bundle_digest"],
            "model_provenance_trace_digest": model_trace["model_provenance_trace_digest"],
        },
        "scan_authority": "static_fixture_diagnostic",
        "live_cutover_ready": status == "passed",
    }


def build_non_scae_probability_authority_report() -> dict[str, Any]:
    """Build a static report proving non-SCAE surfaces cannot author probability."""

    checks: list[dict[str, Any]] = []
    qdt = _build_qdt()
    evidence_packet = _fixture_evidence_packet()
    retrieval_packet = _build_retrieval_packet(qdt, evidence_packet)
    researcher = _build_researcher_artifacts(qdt, retrieval_packet)
    scae_ledger = _fixture_scae_ledger()
    synthesis = _fixture_synthesis(scae_ledger)
    decision = build_decision_gate(
        scae_ledger=scae_ledger,
        synthesis_annotation=synthesis,
        decision_request={"reason_codes": ["authority_boundary_fixture"]},
        generated_at="2026-06-25T12:02:00+00:00",
    )

    validate_synthesis_annotation(synthesis)
    validate_decision_gate_artifact(decision)

    sidecar_with_probability = copy.deepcopy(researcher["sidecar"])
    sidecar_with_probability["replacement_probability"] = 0.51
    sidecar_validation = validate_researcher_sidecar_v2(sidecar_with_probability, qdt)
    checks.append(
        _check_result(
            "researcher_sidecar_rejects_replacement_probability",
            not sidecar_validation.valid
            and any("replacement_probability" in err for err in sidecar_validation.errors),
            sidecar_validation.errors if sidecar_validation.valid else [],
        )
    )

    assignment_with_fair_value = copy.deepcopy(researcher["assignments"][0])
    assignment_with_fair_value["fair_value"] = 0.54
    assignment_validation = validate_leaf_research_assignment(assignment_with_fair_value)
    checks.append(
        _check_result(
            "researcher_assignment_rejects_fair_value",
            not assignment_validation.valid
            and any("fair_value" in err for err in assignment_validation.errors),
            assignment_validation.errors if assignment_validation.valid else [],
        )
    )

    checks.append(
        _expect_rejection(
            "synthesis_rejects_probability_range",
            "probability_range",
            lambda: build_synthesis_annotation(
                scae_ledger=scae_ledger,
                qualitative_annotations=[{"summary": "bad", "probability_range": [0.4, 0.6]}],
            ),
        )
    )
    checks.append(
        _expect_rejection(
            "synthesis_rejects_replacement_probability_summary",
            "replacement_probability",
            lambda: build_synthesis_annotation(
                scae_ledger=scae_ledger,
                research_summaries={"summary": "bad", "replacement_probability": 0.7},
            ),
        )
    )
    checks.append(
        _expect_rejection(
            "decision_rejects_replacement_probability",
            "replacement_probability",
            lambda: build_decision_gate(
                scae_ledger=scae_ledger,
                decision_request={"replacement_probability": 0.72},
            ),
        )
    )
    checks.append(
        _expect_rejection(
            "decision_rejects_numeric_probability_language",
            "numeric probability",
            lambda: build_decision_gate(
                scae_ledger=scae_ledger,
                decision_request={"rationale": "I would set the probability to 61%."},
            ),
        )
    )

    persistence_gate = copy.deepcopy(decision)
    persistence_gate["scae_context"]["production_forecast_prob"] = 0.72
    checks.append(
        _expect_rejection(
            "persistence_rejects_decision_probability_replacement",
            "replace SCAE production_forecast_prob",
            lambda: _write_forecast_decision_with_replacement_context(scae_ledger, persistence_gate),
        )
    )

    with sqlite3.connect(":memory:") as conn:
        forecast_decision = write_forecast_decision(
            conn,
            scae_ledger,
            decision,
            metadata={"forecast_artifact_id": "forecast:authority-boundary"},
        )
        row = conn.execute(
            """
            SELECT production_forecast_prob, canonical_probability, probability_source,
                   scoreable_forecast_output, writes_market_prediction
            FROM forecast_decision_records
            """
        ).fetchone()
    checks.append(
        _check_result(
            "persistence_writes_only_scae_probability_source",
            row
            == (
                scae_ledger["production_forecast_prob"],
                scae_ledger["canonical_probability"],
                "SCAE-012.production_forecast_prob",
                0,
                0,
            )
            and forecast_decision["scoreable_forecast_output"] is False,
        )
    )

    scanned_artifacts = {
        "researcher_sidecar": researcher["sidecar"],
        "leaf_research_assignments": researcher["assignments"],
        "synthesis_annotation": synthesis,
        "decision_gate": decision,
        "forecast_decision_result": forecast_decision,
    }
    forbidden_paths = _active_forbidden_key_paths(scanned_artifacts)
    if forbidden_paths:
        checks.append(_check_result("clean_non_scae_active_authority_key_scan", False, forbidden_paths))
    else:
        checks.append(_check_result("clean_non_scae_active_authority_key_scan", True))

    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {
        "schema_version": NON_SCAE_AUTHORITY_SCAN_SCHEMA_VERSION,
        "blocker_id": NON_SCAE_AUTHORITY_BLOCKER_ID,
        "status": status,
        "check_count": len(checks),
        "checks": checks,
        "scan_authority": "static_fixture_diagnostic",
        "covered_surfaces": [
            "researcher_sidecar",
            "leaf_research_assignment",
            "synthesis_annotation",
            "decision_gate",
            "forecast_decision_records",
        ],
        "live_cutover_ready": status == "passed",
    }


def main() -> int:
    report = build_canonical_machine_artifact_report()
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
