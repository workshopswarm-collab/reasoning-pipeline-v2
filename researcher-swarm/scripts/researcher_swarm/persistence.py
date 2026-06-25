"""MIG-006 researcher/verification persistence helpers.

These helpers persist compact Session 4 records only. They store refs, digests,
statuses, and bounded metadata, leaving evidence bodies, QDT leaf payloads,
researcher transcripts, forecasts, probabilities, intervals, SCAE deltas, and
decision recommendations outside the researcher-swarm persistence surface.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .assignments import validate_leaf_research_assignment
from .classification import validate_researcher_nli_prompt_contract
from .coverage import validate_researcher_evidence_review_coverage_proof_bundle
from .escalation import validate_researcher_escalation_decision
from .isolation import validate_researcher_context_isolation_audit
from .supplemental import validate_normalized_supplemental_evidence


MIG_006_RESEARCHER_VERIFICATION_MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "006_researcher_verification_persistence.sql"
)
RESEARCHER_PERSISTENCE_VERSION = "ads-mig-006-researcher-verification-persistence/v1"
RESEARCHER_MODEL_LANE = "researcher_leaf_nli_classification"


FORBIDDEN_PERSISTENCE_FIELD_NAMES = {
    "own_probability",
    "leaf_probability",
    "researcher_reassembled_probability",
    "researcher_macro_probability",
    "macro_probability",
    "final_macro_probability",
    "forecast_probability",
    "production_probability",
    "probability",
    "probability_estimate",
    "probability_yes",
    "probability_no",
    "probability_interval",
    "replacement_probability",
    "replacement_forecast",
    "replacement_decision",
    "fair_value",
    "fair_value_low",
    "fair_value_mid",
    "fair_value_high",
    "interval",
    "odds",
    "log_odds",
    "scae_delta",
    "scae_probability_delta",
    "scae_evidence_delta",
    "decision_recommendation",
    "decision_output",
    "trade_recommendation",
    "researcher_transcript",
    "researcher_transcript_body",
}
FORBIDDEN_PERSISTENCE_KEY_FRAGMENTS = (
    "probability_estimate",
    "fair_value",
    "log_odds",
    "scae_delta",
    "decision_recommendation",
)
FORBIDDEN_RAW_PAYLOAD_FIELDS = {
    "full_leaf",
    "leaf_blob",
    "qdt_leaf",
    "required_leaf_questions",
    "branch_questions",
    "evidence_body",
    "evidence_text",
    "full_text",
    "document_text",
    "raw_text",
    "html",
    "markdown",
    "article_body",
    "page_text",
    "body",
    "content",
    "transcript",
    "research_report",
    "narrative_report",
    "prompt_text",
}
ALLOWED_FALSE_AUTHORITY_FIELDS = {
    "probability_fields_forbidden",
    "probability_authority",
    "researcher_probability_authority",
    "researcher_forecast_authority",
    "forecast_probability_authority",
    "model_outputs_may_author_probability",
    "numeric_estimate_authority",
    "pricing_authority",
    "range_estimate_authority",
    "market_action_authority",
    "downstream_ledger_authority",
    "forecast_authority",
    "decision_authority",
    "persistence_authority",
    "writes_scae_ledger_rows",
    "scae_numeric_authority",
    "research_sufficiency_authority",
}


class ResearcherPersistenceError(ValueError):
    """Raised when a MIG-006 record is unsafe or cannot be persisted."""


def ensure_researcher_verification_persistence_schema(conn: sqlite3.Connection) -> None:
    """Create Session 4 MIG-006 destination tables when absent."""

    conn.executescript(MIG_006_RESEARCHER_VERIFICATION_MIGRATION.read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json(value: Any) -> str:
    if value is None:
        value = {} if isinstance(value, dict) else []
    return _canonical_json(value)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _bool_int(value: Any) -> int:
    return 1 if value is True else 0


def _normalized_field_name(value: Any) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _collect_forbidden_persistence_paths(value: Any, path: str = "record") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if normalized in ALLOWED_FALSE_AUTHORITY_FIELDS and child in {False, True}:
                if normalized == "probability_fields_forbidden" and child is not True:
                    errors.append(f"{path}.{key} must remain true")
                elif normalized != "probability_fields_forbidden" and child is not False:
                    errors.append(f"{path}.{key} must remain false")
            elif normalized in FORBIDDEN_PERSISTENCE_FIELD_NAMES:
                errors.append(f"{path}.{key} is forbidden in MIG-006 persistence")
            elif normalized in FORBIDDEN_RAW_PAYLOAD_FIELDS:
                errors.append(f"{path}.{key} embeds payload content forbidden in MIG-006 persistence")
            elif any(fragment in normalized for fragment in FORBIDDEN_PERSISTENCE_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in MIG-006 persistence")
            elif normalized.endswith("_probability") or normalized.endswith("_odds"):
                errors.append(f"{path}.{key} is forbidden in MIG-006 persistence")
            elif "decision" in normalized and normalized not in {
                "decision_id",
                "decision_ref",
                "decision_digest",
                "escalation_decision_ref",
                "required_escalation_decision_refs",
                "completed_escalation_decision_refs",
                "escalation_decisions",
                "decision_authority",
            }:
                errors.append(f"{path}.{key} is forbidden in MIG-006 persistence")
            errors.extend(_collect_forbidden_persistence_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            errors.extend(_collect_forbidden_persistence_paths(child, f"{path}[{idx}]"))
    return errors


def _reject_forbidden_persistence_payload(value: Any, path: str = "record") -> None:
    errors = _collect_forbidden_persistence_paths(value, path)
    if errors:
        raise ResearcherPersistenceError("; ".join(sorted(set(errors))))


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in _table_columns(conn, table)


def _upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any], conflict_columns: Iterable[str]) -> None:
    columns = list(row)
    conflicts = list(conflict_columns)
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    conflict_sql = ", ".join(conflicts)
    updates = ", ".join(
        f"{column}=excluded.{column}" for column in columns if column not in set(conflicts) and column != "created_at"
    )
    sql = f"""
        INSERT INTO {table} ({column_sql})
        VALUES ({placeholders})
        ON CONFLICT({conflict_sql}) DO UPDATE SET
          {updates}
    """
    conn.execute(sql, tuple(row[column] for column in columns))


def _records_from(value: Any, key: str | None = None, attr: str | None = None) -> list[dict[str, Any]]:
    if attr and hasattr(value, attr):
        value = getattr(value, attr)
    if isinstance(value, dict) and key:
        value = value.get(key, [])
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise ResearcherPersistenceError("records must be an object or list")
    if not all(isinstance(item, dict) for item in value):
        raise ResearcherPersistenceError("records must contain objects")
    return list(value)


def _required_str(record: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = record.get(field)
        if _is_non_empty_string(value):
            return str(value)
    raise ResearcherPersistenceError(f"missing required field: {'/'.join(fields)}")


def _optional_str(record: dict[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = record.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _quality_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("evidence_quality_dimensions")
    return fields if isinstance(fields, dict) else {}


def _answer_value(record: dict[str, Any]) -> str | None:
    extraction = record.get("answer_value_extraction")
    if not isinstance(extraction, dict):
        return None
    for field in ("value", "normalized_value", "text"):
        if _is_non_empty_string(extraction.get(field)):
            return str(extraction[field])
    return None


def write_researcher_prompt_artifact(
    conn: sqlite3.Connection,
    prompt_artifact: dict[str, Any],
    *,
    artifact_ref: str | None = None,
    artifact_path: str | None = None,
) -> str:
    """Persist a prompt artifact ref/hash row without storing prompt text."""

    ensure_researcher_verification_persistence_schema(conn)
    if not isinstance(prompt_artifact, dict):
        raise ResearcherPersistenceError("prompt_artifact must be an object")
    if prompt_artifact.get("artifact_type") == "researcher_nli_prompt_contract":
        validation = validate_researcher_nli_prompt_contract(prompt_artifact)
        if not validation.valid:
            raise ResearcherPersistenceError("prompt contract invalid: " + "; ".join(validation.errors))
    compact = copy.deepcopy(prompt_artifact)
    compact.pop("prompt_text", None)
    _reject_forbidden_persistence_payload(compact, "prompt_artifact")

    template = prompt_artifact.get("prompt_template") if isinstance(prompt_artifact.get("prompt_template"), dict) else {}
    context = prompt_artifact.get("context_payload") if isinstance(prompt_artifact.get("context_payload"), dict) else {}
    model_context = (
        context.get("model_execution_context") if isinstance(context.get("model_execution_context"), dict) else {}
    )
    output_refs = (
        context.get("output_sidecar_contract_refs")
        if isinstance(context.get("output_sidecar_contract_refs"), dict)
        else prompt_artifact.get("output_contract_refs", {})
    )
    prompt_contract_id = _required_str(prompt_artifact, "prompt_contract_id", "prompt_artifact_id")
    row = {
        "prompt_contract_id": prompt_contract_id,
        "schema_version": _required_str(prompt_artifact, "schema_version"),
        "case_id": _required_str(prompt_artifact, "case_id"),
        "dispatch_id": _required_str(prompt_artifact, "dispatch_id"),
        "prompt_template_id": _required_str(template or prompt_artifact, "prompt_template_id"),
        "prompt_template_sha256": _required_str(template or prompt_artifact, "prompt_template_sha256"),
        "prompt_text_sha256": _required_str(prompt_artifact, "prompt_text_sha256"),
        "prompt_contract_digest": _required_str(prompt_artifact, "prompt_contract_digest"),
        "model_execution_context_ref": _optional_str(model_context or prompt_artifact, "model_execution_context_ref"),
        "model_execution_context_sha256": _optional_str(model_context or prompt_artifact, "model_context_digest", "model_execution_context_sha256"),
        "output_contract_refs": _json(output_refs if isinstance(output_refs, dict) else {}),
        "prompt_artifact_ref": artifact_ref or _optional_str(prompt_artifact, "prompt_artifact_ref", "artifact_ref"),
        "prompt_artifact_path": artifact_path or _optional_str(prompt_artifact, "prompt_artifact_path", "artifact_path"),
        "updated_at": "CURRENT_TIMESTAMP",
    }
    # Avoid using a SQL function as a bound value in the row above.
    row.pop("updated_at")
    _upsert(conn, "researcher_prompt_artifacts", row, ["prompt_contract_id"])
    return prompt_contract_id


def write_leaf_research_assignments(conn: sqlite3.Connection, assignments: dict[str, Any] | list[dict[str, Any]]) -> list[str]:
    """Persist compact leaf-research-assignment/v1 rows."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _records_from(assignments)
    written: list[str] = []
    for assignment in rows:
        validation = validate_leaf_research_assignment(assignment)
        if not validation.valid:
            raise ResearcherPersistenceError("leaf assignment invalid: " + "; ".join(validation.errors))
        _reject_forbidden_persistence_payload(assignment, "assignment")
        leaf_ref = assignment["leaf_ref"]
        model_context = assignment["model_execution_context"]
        context = assignment["context_isolation"]
        row = {
            "assignment_id": assignment["assignment_id"],
            "schema_version": assignment["schema_version"],
            "case_id": assignment["case_id"],
            "dispatch_id": assignment["dispatch_id"],
            "leaf_id": assignment["leaf_id"],
            "parent_branch_id": assignment.get("parent_branch_id"),
            "assignment_role": assignment["assignment_role"],
            "attempt_index": assignment["attempt_index"],
            "assigned_lens": assignment["assigned_lens"],
            "escalation_decision_ref": assignment.get("escalation_decision_ref"),
            "trigger_codes": _json(assignment.get("trigger_codes", [])),
            "leaf_artifact_ref": leaf_ref["artifact_ref"],
            "leaf_json_pointer": leaf_ref["leaf_json_pointer"],
            "leaf_digest": leaf_ref["leaf_digest"],
            "condition_scope": assignment["condition_scope"],
            "sufficiency_requirement_refs": _json(assignment.get("sufficiency_requirement_refs", [])),
            "research_sufficiency_certificate_ref": assignment["research_sufficiency_certificate_ref"],
            "retrieval_breadth_profile_ref": assignment["retrieval_breadth_profile_ref"],
            "retrieval_breadth_coverage_ref": assignment["retrieval_breadth_coverage_ref"],
            "assigned_evidence_refs": _json(assignment.get("assigned_evidence_refs", [])),
            "required_value_field_ids": _json(assignment.get("required_value_field_ids", [])),
            "required_negative_check_ids": _json(assignment.get("required_negative_check_ids", [])),
            "context_isolation_ref": context["isolation_audit_ref"],
            "model_lane_id": model_context["model_lane_id"],
            "resolved_model_id": model_context["resolved_model_id"],
            "prompt_template_id": model_context["prompt_template_id"],
            "prompt_template_sha256": model_context["prompt_template_sha256"],
            "model_policy_ref": model_context["model_policy_ref"],
            "model_context_sha256": model_context["model_context_digest"],
            "budget": _json(assignment.get("budget", {})),
            "artifact_outputs": _json(assignment.get("artifact_outputs", {})),
            "assignment_digest": assignment["assignment_digest"],
        }
        _upsert(conn, "leaf_research_assignments", row, ["assignment_id"])
        written.append(assignment["assignment_id"])
    return written


def write_researcher_context_isolation_audits(
    conn: sqlite3.Connection,
    audits: dict[str, Any] | list[dict[str, Any]],
    *,
    assignments_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Persist compact context-isolation audits."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _records_from(audits)
    written: list[str] = []
    for audit in rows:
        assignment = (assignments_by_id or {}).get(str(audit.get("assignment_id")))
        validation = validate_researcher_context_isolation_audit(audit, assignment=assignment)
        if not validation.valid:
            raise ResearcherPersistenceError("context isolation audit invalid: " + "; ".join(validation.errors))
        _reject_forbidden_persistence_payload(audit, "isolation_audit")
        row = {
            "isolation_audit_id": audit["isolation_audit_id"],
            "schema_version": audit["schema_version"],
            "case_id": audit["case_id"],
            "dispatch_id": audit["dispatch_id"],
            "assignment_id": audit["assignment_id"],
            "leaf_id": audit["leaf_id"],
            "subagent_session_ref": audit["subagent_session_ref"],
            "fresh_context": _bool_int(audit["fresh_context"]),
            "visible_artifact_refs": _json(audit.get("visible_artifact_refs", [])),
            "visible_artifact_refs_digest": audit["visible_artifact_refs_digest"],
            "forbidden_ref_scan": _json(audit.get("forbidden_ref_scan", {})),
            "peer_output_exclusion_proof": _json(audit.get("peer_output_exclusion_proof", {})),
            "allowed_shared_refs": _json(audit.get("allowed_shared_refs", [])),
            "launch_allowed": _bool_int(audit["launch_allowed"]),
            "reason_codes": _json(audit.get("reason_codes", [])),
            "audit_digest": audit["audit_digest"],
        }
        _upsert(conn, "researcher_context_isolation_audits", row, ["isolation_audit_id"])
        written.append(audit["isolation_audit_id"])
    return written


def _rich_classification_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "slice_id": record["slice_id"],
        "schema_version": record["schema_version"],
        "case_id": record["case_id"],
        "dispatch_id": record["dispatch_id"],
        "sidecar_id": record.get("sidecar_id"),
        "researcher_run_id": record.get("researcher_run_id"),
        "persona_id": record.get("persona_id"),
        "classification_id": record["classification_id"],
        "leaf_id": record["leaf_id"],
        "parent_branch_id": record.get("parent_branch_id"),
        "question_id": record.get("question_id") or record["leaf_id"],
        "condition_scope": record["condition_scope"],
        "condition_ref": record.get("condition_ref"),
        "evidence_ref": record["evidence_ref"],
        "source_ref": record.get("source_ref"),
        "canonical_source_id": record.get("canonical_source_id"),
        "source_class": record["source_class"],
        "source_family_id": record["source_family_id"],
        "claim_family_id": record["claim_family_id"],
        "claim_family_resolution_ref": record.get("claim_family_resolution_ref"),
        "impact_direction": record["impact_direction"],
        "evidence_strength": record["evidence_strength"],
        "classification_confidence": record["classification_confidence"],
        "answer_value_extraction": _json(record.get("answer_value_extraction", {})),
        "evidence_quality_dimensions": _json(record.get("evidence_quality_dimensions", {})),
        "research_sufficiency_certificate_ref": record["research_sufficiency_certificate_ref"],
        "coverage_proof_ref": record["coverage_proof_ref"],
        "retrieval_breadth_coverage_ref": record.get("retrieval_breadth_coverage_ref"),
        "provenance_slice_ref": record.get("provenance_slice_ref"),
        "model_execution_context_ref": record.get("model_execution_context_ref"),
        "model_execution_context_sha256": record.get("model_execution_context_sha256"),
        "normalized_supplemental_evidence_ref": record.get("normalized_supplemental_evidence_ref"),
        "classification_slice_digest": record["classification_slice_digest"],
        "matrix_digest": record.get("matrix_digest"),
        "materializer_version": record.get("materializer_version"),
    }


def _legacy_classification_row(record: dict[str, Any]) -> dict[str, Any]:
    quality = _quality_fields(record)
    return {
        "classification_id": record["slice_id"],
        "case_key": str(record.get("case_key") or record["case_id"]),
        "dispatch_id": record["dispatch_id"],
        "market_id": record.get("market_id"),
        "classification_lane": RESEARCHER_MODEL_LANE,
        "question_id": record.get("question_id") or record["leaf_id"],
        "parent_branch_id": record.get("parent_branch_id"),
        "leaf_dependency_group_id": record.get("claim_family_id") or record.get("parent_branch_id") or record["leaf_id"],
        "leaf_condition_scope": record["condition_scope"],
        "answer_value": _answer_value(record),
        "impact_direction": record["impact_direction"],
        "evidence_diagnosticity": record["evidence_strength"],
        "evidence_reliability": quality.get("source_authority", record.get("source_class", "unknown")),
        "classification_confidence": record["classification_confidence"],
        "classification_uncertainty_level": record["classification_confidence"],
        "classification_uncertainty_reason": None,
        "source_authority": quality.get("source_authority", "unknown"),
        "evidence_directness": quality.get("directness", "unknown"),
        "recency_status": quality.get("recency", "unknown"),
        "specificity": quality.get("specificity", "unknown"),
        "classification_status": "accepted",
        "unanswerable_reason": None,
        "uses_retrieval_packet_evidence": 0 if record.get("evidence_source_type") == "supplemental" else 1,
        "uses_supplemental_research": 1 if record.get("evidence_source_type") == "supplemental" else 0,
        "sidecar_schema_version": record.get("sidecar_schema_version", "researcher-sidecar/v2"),
        "sidecar_artifact_path": str(record.get("sidecar_id") or record.get("sidecar_artifact_ref") or "artifact:researcher-sidecar/unknown"),
        "sidecar_sha256": record.get("sidecar_digest") or record["classification_slice_digest"],
    }


def write_researcher_classification_slices(
    conn: sqlite3.Connection,
    classification_slices: dict[str, Any] | list[dict[str, Any]],
) -> list[str]:
    """Persist classification slices to the configured destination surface."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _records_from(classification_slices, "classification_slices")
    written: list[str] = []
    rich = _has_column(conn, "classification_lane_evidence_classification_slices", "slice_id")
    for record in rows:
        _reject_forbidden_persistence_payload(record, "classification_slice")
        if rich:
            _upsert(
                conn,
                "classification_lane_evidence_classification_slices",
                _rich_classification_row(record),
                ["slice_id"],
            )
        else:
            _upsert(
                conn,
                "classification_lane_evidence_classification_slices",
                _legacy_classification_row(record),
                ["case_key", "dispatch_id", "classification_id"],
            )
        written.append(record["slice_id"])
    return written


def _rich_provenance_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "slice_id": record["slice_id"],
        "schema_version": record["schema_version"],
        "case_id": record["case_id"],
        "dispatch_id": record["dispatch_id"],
        "sidecar_id": record.get("sidecar_id"),
        "classification_slice_ref": record["classification_slice_ref"],
        "classification_id": record["classification_id"],
        "leaf_id": record["leaf_id"],
        "condition_scope": record.get("condition_scope"),
        "evidence_ref": record["evidence_ref"],
        "retrieval_evidence_provenance_ref": record.get("retrieval_evidence_provenance_ref"),
        "source_ref": record.get("source_ref"),
        "source_class": record["source_class"],
        "source_family_id": record["source_family_id"],
        "claim_family_id": record["claim_family_id"],
        "claim_family_resolution_ref": record.get("claim_family_resolution_ref"),
        "research_sufficiency_certificate_ref": record.get("research_sufficiency_certificate_ref"),
        "coverage_proof_ref": record.get("coverage_proof_ref"),
        "retrieval_breadth_coverage_ref": record.get("retrieval_breadth_coverage_ref"),
        "provenance_refs": _json(record.get("provenance_refs", [])),
        "content_sha256": record.get("content_sha256"),
        "normalized_supplemental_evidence_ref": record.get("normalized_supplemental_evidence_ref"),
        "provenance_slice_digest": record["provenance_slice_digest"],
        "matrix_digest": record.get("matrix_digest"),
        "materializer_version": record.get("materializer_version"),
    }


def _legacy_provenance_row(record: dict[str, Any]) -> dict[str, Any]:
    source_id = record.get("canonical_source_id") or record.get("source_ref") or record.get("source_family_id")
    claim_id = record.get("claim_family_id") or "claim-family-unknown"
    return {
        "provenance_slice_id": record["slice_id"],
        "classification_id": record.get("classification_slice_ref") or record["classification_id"],
        "case_key": str(record.get("case_key") or record["case_id"]),
        "dispatch_id": record["dispatch_id"],
        "market_id": record.get("market_id"),
        "classification_lane": RESEARCHER_MODEL_LANE,
        "question_id": record.get("question_id") or record["leaf_id"],
        "leaf_dependency_group_id": claim_id,
        "event_source_family": record.get("source_family_id") or "source-family-unknown",
        "claim_family_id": claim_id,
        "canonical_source_id": source_id,
        "canonical_source_key": source_id,
        "claim_fingerprint": claim_id,
        "content_sha256": record.get("content_sha256"),
        "chunk_sha256": None,
        "source": record.get("source_ref"),
        "source_type": record.get("source_class"),
        "evidence_origin": "supplemental" if record.get("evidence_source_type") == "supplemental" else "retrieval_packet",
        "canonicalization_status": "accepted",
        "source_class_for_discounting": record.get("source_class", "unknown"),
        "source_class_cap_scope": "none",
        "forecast_time_eligible": 1,
        "published_at": None,
        "observed_at": None,
        "retrieved_at": None,
        "artifact_ref": record.get("evidence_ref"),
        "snippet_sha256": record.get("content_sha256"),
        "retrieval_quality_status": None,
        "retrieval_quality_score": None,
        "source_family_status": "resolved",
        "independence_status": None,
        "claim_equivalence_status": "resolved",
    }


def write_classification_provenance_slices(
    conn: sqlite3.Connection,
    provenance_slices: dict[str, Any] | list[dict[str, Any]],
) -> list[str]:
    """Persist classification provenance slices."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _records_from(provenance_slices, "provenance_slices")
    written: list[str] = []
    rich = _has_column(conn, "classification_lane_evidence_provenance_slices", "slice_id")
    for record in rows:
        _reject_forbidden_persistence_payload(record, "classification_provenance_slice")
        if rich:
            _upsert(
                conn,
                "classification_lane_evidence_provenance_slices",
                _rich_provenance_row(record),
                ["slice_id"],
            )
        else:
            _upsert(
                conn,
                "classification_lane_evidence_provenance_slices",
                _legacy_provenance_row(record),
                ["provenance_slice_id"],
            )
        written.append(record["slice_id"])
    return written


def write_researcher_classifications(conn: sqlite3.Connection, classification_matrix: dict[str, Any]) -> dict[str, list[str]]:
    """Persist classification and provenance slices from a materialized matrix."""

    if not isinstance(classification_matrix, dict):
        raise ResearcherPersistenceError("classification_matrix must be an object")
    classification_ids = write_researcher_classification_slices(
        conn,
        classification_matrix.get("classification_slices", []),
    )
    provenance_ids = write_classification_provenance_slices(
        conn,
        classification_matrix.get("provenance_slices", []),
    )
    return {"classification_slice_ids": classification_ids, "provenance_slice_ids": provenance_ids}


def write_researcher_coverage_proofs(
    conn: sqlite3.Connection,
    coverage_proof_bundle: dict[str, Any] | list[dict[str, Any]],
) -> list[str]:
    """Persist compact CLS-005 coverage proof records."""

    ensure_researcher_verification_persistence_schema(conn)
    if isinstance(coverage_proof_bundle, dict) and coverage_proof_bundle.get("artifact_type") == "researcher_evidence_review_coverage_proof_bundle":
        validation = validate_researcher_evidence_review_coverage_proof_bundle(coverage_proof_bundle)
        if not validation.valid:
            raise ResearcherPersistenceError("coverage proof bundle invalid: " + "; ".join(validation.errors))
    rows = _records_from(coverage_proof_bundle, "coverage_proofs")
    written: list[str] = []
    for record in rows:
        _reject_forbidden_persistence_payload(record, "coverage_proof")
        row = {
            "proof_id": record["proof_id"],
            "schema_version": record["schema_version"],
            "case_id": record["case_id"],
            "dispatch_id": record["dispatch_id"],
            "leaf_id": record["leaf_id"],
            "assignment_id": record["assignment_id"],
            "assignment_digest": record["assignment_digest"],
            "isolation_audit_ref": record["isolation_audit_ref"],
            "isolation_audit_digest": record["isolation_audit_digest"],
            "sidecar_id": record["sidecar_id"],
            "sidecar_digest": record["sidecar_digest"],
            "coverage_proof_ref": record["coverage_proof_ref"],
            "coverage_proof_slice_ref": record["coverage_proof_slice_ref"],
            "classification_matrix_id": record["classification_matrix_id"],
            "classification_matrix_digest": record["classification_matrix_digest"],
            "research_sufficiency_certificate_ref": record["research_sufficiency_certificate_ref"],
            "certificate_status": record["certificate_status"],
            "retrieval_breadth_coverage_ref": record["retrieval_breadth_coverage_ref"],
            "coverage_status": record["coverage_status"],
            "assigned_evidence_refs": _json(record.get("assigned_evidence_refs", [])),
            "reviewed_evidence_refs": _json(record.get("reviewed_evidence_refs", [])),
            "certificate_evidence_refs": _json(record.get("certificate_evidence_refs", [])),
            "classified_evidence_refs": _json(record.get("classified_evidence_refs", [])),
            "requirements_reviewed": _json(record.get("requirements_reviewed", [])),
            "requirements_answered": _json(record.get("requirements_answered", [])),
            "requirements_unanswered": _json(record.get("requirements_unanswered", [])),
            "required_value_fields": _json(record.get("required_value_fields", [])),
            "required_value_fields_extracted": _json(record.get("required_value_fields_extracted", [])),
            "required_negative_checks": _json(record.get("required_negative_checks", [])),
            "required_negative_checks_completed": _json(record.get("required_negative_checks_completed", [])),
            "proof_digest": record["proof_digest"],
        }
        _upsert(conn, "researcher_leaf_coverage_proofs", row, ["proof_id"])
        written.append(record["proof_id"])
    return written


def write_researcher_escalation_decisions(
    conn: sqlite3.Connection,
    decisions: dict[str, Any] | list[dict[str, Any]],
) -> list[str]:
    """Persist compact CLS-007 escalation decisions."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _records_from(decisions, "escalation_decisions")
    written: list[str] = []
    for decision in rows:
        if decision.get("schema_version") == "researcher-escalation-decision/v1":
            validation = validate_researcher_escalation_decision(decision)
            if not validation.valid:
                raise ResearcherPersistenceError("escalation decision invalid: " + "; ".join(validation.errors))
        _reject_forbidden_persistence_payload(decision, "escalation_decision")
        row = {
            "decision_id": decision["decision_id"],
            "schema_version": decision["schema_version"],
            "case_id": decision["case_id"],
            "dispatch_id": decision["dispatch_id"],
            "leaf_id": decision["leaf_id"],
            "base_assignment_id": decision["base_assignment_id"],
            "trigger_codes": _json(decision.get("trigger_codes", [])),
            "trigger_evidence_refs": _json(decision.get("trigger_evidence_refs", [])),
            "retrieval_quality_ref": decision.get("retrieval_quality_ref"),
            "classification_ids": _json(decision.get("classification_ids", [])),
            "verification_slice_refs": _json(decision.get("verification_slice_refs", [])),
            "pre_scae_leverage_proxy": _json(decision.get("pre_scae_leverage_proxy", {})),
            "escalation_required": _bool_int(decision.get("escalation_required")),
            "additional_assignment_count": int(decision.get("additional_assignment_count", 0)),
            "max_assignments_for_leaf": int(decision.get("max_assignments_for_leaf", 0)),
            "max_concurrent_leaf_researchers_per_case": int(decision.get("max_concurrent_leaf_researchers_per_case", 0)),
            "escalation_assignment_refs": _json(decision.get("escalation_assignment_refs", [])),
            "completion_status": decision["completion_status"],
            "decision_digest": decision["decision_digest"],
        }
        _upsert(conn, "researcher_escalation_decisions", row, ["decision_id"])
        written.append(decision["decision_id"])
    return written


def write_normalized_supplemental_evidence(
    conn: sqlite3.Connection,
    normalized_records: dict[str, Any] | list[dict[str, Any]],
) -> list[str]:
    """Persist normalized supplemental evidence records."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _records_from(normalized_records, "normalized_supplemental_evidence")
    written: list[str] = []
    for record in rows:
        validation = validate_normalized_supplemental_evidence(record)
        if not validation.valid:
            raise ResearcherPersistenceError("normalized supplemental evidence invalid: " + "; ".join(validation.errors))
        _reject_forbidden_persistence_payload(record, "normalized_supplemental_evidence")
        row = {
            "normalization_id": record["normalization_id"],
            "schema_version": record["schema_version"],
            "case_id": record.get("case_id"),
            "dispatch_id": record.get("dispatch_id"),
            "leaf_id": record.get("leaf_id"),
            "classification_id": record.get("classification_id"),
            "supplemental_evidence_ref": record["supplemental_evidence_ref"],
            "normalization_status": record["normalization_status"],
            "admission_status": record["admission_status"],
            "source_access_status": record["source_access_status"],
            "canonical_source_id": record["canonical_source_id"],
            "event_source_family_id": record["event_source_family_id"],
            "source_family_id": record["source_family_id"],
            "source_class": record["source_class"],
            "claim_family_id": record["claim_family_id"],
            "claim_family_resolution_ref": record.get("claim_family_resolution_ref"),
            "content_sha256": record["content_sha256"],
            "temporal_gate_status": record["temporal_gate_status"],
            "temporal_validation_ref": record.get("temporal_validation_ref"),
            "independence_status": record["independence_status"],
            "counts_toward_breadth": _bool_int(record["counts_toward_breadth"]),
            "blockers": _json(record.get("blockers", [])),
            "rejection_reason_codes": _json(record.get("rejection_reason_codes", [])),
            "normalization_digest": record["normalization_digest"],
        }
        _upsert(conn, "normalized_supplemental_evidence", row, ["normalization_id"])
        written.append(record["normalization_id"])
    return written


def _direction_rows_from(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "direction_verification_slices"):
        value = value.direction_verification_slices
    return _records_from(value, "direction_verification_slices")


def _rich_direction_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "verification_slice_id": record["verification_slice_id"],
        "schema_version": record["schema_version"],
        "case_id": record["case_id"],
        "dispatch_id": record["dispatch_id"],
        "classification_id": record["classification_id"],
        "classification_slice_ref": record.get("classification_slice_ref"),
        "leaf_id": record["leaf_id"],
        "claimed_direction": record["claimed_direction"],
        "verified_direction": record["verified_direction"],
        "method_status": record["method_status"],
        "verification_status": record["verification_status"],
        "side_mapping_digest": record.get("side_mapping_digest"),
        "market_constraints_digest": record.get("market_constraints_digest"),
        "coverage_after_exclusion_status": record.get("coverage_after_exclusion_status"),
        "reason_codes": _json(record.get("reason_codes", [])),
        "direction_verification_slice_digest": record["direction_verification_slice_digest"],
        "direction_verification_digest": record.get("direction_verification_digest"),
    }


def _legacy_direction_row(record: dict[str, Any]) -> dict[str, Any]:
    verified = record.get("verified_direction")
    multiplier = 0.0 if verified in {"ambiguous", "excluded"} else 1.0
    return {
        "verification_slice_id": record["verification_slice_id"],
        "classification_id": record.get("classification_slice_ref") or record["classification_id"],
        "case_key": str(record.get("case_key") or record["case_id"]),
        "dispatch_id": record["dispatch_id"],
        "market_id": record.get("market_id"),
        "question_id": record.get("question_id") or record["leaf_id"],
        "proposed_direction": record["claimed_direction"],
        "verified_direction": verified,
        "verified_directional_multiplier": multiplier,
        "verification_status": record["verification_status"],
        "verifier_reason_codes": _json(record.get("reason_codes", [])),
        "confidence_status": "accepted" if record["verification_status"] == "accepted" else record["method_status"],
        "ambiguity_flag": 1 if verified == "ambiguous" else 0,
        "side_mapping_ref": record.get("side_mapping_digest"),
        "market_constraints_sha256": record.get("market_constraints_digest"),
    }


def write_direction_verification_slices(conn: sqlite3.Connection, direction_slices: Any) -> list[str]:
    """Persist VER-001 direction verification slices."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _direction_rows_from(direction_slices)
    rich = _has_column(conn, "evidence_direction_verification_slices", "schema_version")
    written: list[str] = []
    for record in rows:
        _reject_forbidden_persistence_payload(record, "direction_verification_slice")
        if rich:
            _upsert(conn, "evidence_direction_verification_slices", _rich_direction_row(record), ["verification_slice_id"])
        else:
            _upsert(conn, "evidence_direction_verification_slices", _legacy_direction_row(record), ["verification_slice_id"])
        written.append(record["verification_slice_id"])
    return written


def _quality_rows_from(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "quality_verification_slices"):
        value = value.quality_verification_slices
    return _records_from(value, "quality_verification_slices")


def _rich_quality_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "quality_verification_slice_id": record["quality_verification_slice_id"],
        "schema_version": record["schema_version"],
        "case_id": record["case_id"],
        "dispatch_id": record["dispatch_id"],
        "classification_id": record["classification_id"],
        "classification_slice_ref": record.get("classification_slice_ref"),
        "leaf_id": record["leaf_id"],
        "verification_status": record.get("quality_status") or record.get("verification_status"),
        "claimed_quality_fields": _json(record.get("claimed_quality_fields", {})),
        "machine_normalized_quality_fields": _json(record.get("machine_normalized_quality_fields", {})),
        "accepted_quality_fields": _json(record.get("accepted_quality_fields", {})),
        "raw_quality_multiplier": float(record["raw_quality_multiplier"]),
        "quality_correlation_groups": _json(record.get("quality_correlation_groups", [])),
        "correlated_quality_floor_applied": _bool_int(record.get("correlated_quality_floor_applied")),
        "final_quality_multiplier": float(record["final_quality_multiplier"]),
        "reason_codes": _json(record.get("reason_codes", [])),
        "quality_verification_slice_digest": record["quality_verification_slice_digest"],
        "quality_verification_digest": record.get("quality_verification_digest"),
    }


def _legacy_quality_row(record: dict[str, Any]) -> dict[str, Any]:
    accepted = record.get("accepted_quality_fields", {})
    return {
        "quality_verification_slice_id": record["quality_verification_slice_id"],
        "classification_id": record.get("classification_slice_ref") or record["classification_id"],
        "case_key": str(record.get("case_key") or record["case_id"]),
        "dispatch_id": record["dispatch_id"],
        "market_id": record.get("market_id"),
        "question_id": record.get("question_id") or record["leaf_id"],
        "verification_status": record.get("quality_status") or record.get("verification_status"),
        "verified_source_authority": accepted.get("source_authority", "unknown"),
        "verified_evidence_directness": accepted.get("directness", "unknown"),
        "verified_recency_status": accepted.get("recency", "unknown"),
        "verified_specificity": accepted.get("specificity", "unknown"),
        "verified_classification_confidence": accepted.get("classification_confidence", "unknown"),
        "verifier_reason_codes": _json(record.get("reason_codes", [])),
        "caveat_flag": 0 if record.get("quality_status") == "accepted" else 1,
    }


def write_evidence_quality_verification_slices(conn: sqlite3.Connection, quality_slices: Any) -> list[str]:
    """Persist VER-002 evidence-quality verification slices."""

    ensure_researcher_verification_persistence_schema(conn)
    rows = _quality_rows_from(quality_slices)
    rich = _has_column(conn, "evidence_quality_verification_slices", "schema_version")
    written: list[str] = []
    for record in rows:
        _reject_forbidden_persistence_payload(record, "quality_verification_slice")
        if rich:
            _upsert(conn, "evidence_quality_verification_slices", _rich_quality_row(record), ["quality_verification_slice_id"])
        else:
            _upsert(conn, "evidence_quality_verification_slices", _legacy_quality_row(record), ["quality_verification_slice_id"])
        written.append(record["quality_verification_slice_id"])
    return written


def write_verification_slices(
    conn: sqlite3.Connection,
    *,
    direction_verification_slices: Any | None = None,
    quality_verification_slices: Any | None = None,
    normalized_supplemental_evidence: Any | None = None,
) -> dict[str, list[str]]:
    """Persist all MIG-006 verification-adjacent slices supplied by caller."""

    written = {"direction_verification_slice_ids": [], "quality_verification_slice_ids": [], "normalized_supplemental_ids": []}
    if direction_verification_slices is not None:
        written["direction_verification_slice_ids"] = write_direction_verification_slices(conn, direction_verification_slices)
    if quality_verification_slices is not None:
        written["quality_verification_slice_ids"] = write_evidence_quality_verification_slices(conn, quality_verification_slices)
    if normalized_supplemental_evidence is not None:
        written["normalized_supplemental_ids"] = write_normalized_supplemental_evidence(conn, normalized_supplemental_evidence)
    return written


def write_scae_readiness_reconciliation(
    conn: sqlite3.Connection,
    readiness_reconciliation: Any,
    *,
    artifact_ref: str | None = None,
    artifact_path: str | None = None,
) -> str:
    """Persist a VER-003 readiness ref row without duplicating readiness row bodies."""

    ensure_researcher_verification_persistence_schema(conn)
    if hasattr(readiness_reconciliation, "readiness_reconciliation"):
        readiness_reconciliation = readiness_reconciliation.readiness_reconciliation
    if not isinstance(readiness_reconciliation, dict):
        raise ResearcherPersistenceError("readiness_reconciliation must be an object")
    _reject_forbidden_persistence_payload(
        {
            key: value
            for key, value in readiness_reconciliation.items()
            if key not in {"readiness_rows", "leaf_readiness", "blockers", "scope_boundaries"}
        },
        "scae_readiness_reconciliation",
    )
    readiness_rows = readiness_reconciliation.get("readiness_rows", [])
    leaf_readiness = readiness_reconciliation.get("leaf_readiness", [])
    if not isinstance(readiness_rows, list):
        raise ResearcherPersistenceError("readiness_rows must be a list")
    row_digests = [
        str(row.get("readiness_row_digest") or _prefixed_sha256(row))
        for row in readiness_rows
        if isinstance(row, dict)
    ]
    leaf_refs = [
        {
            "leaf_id": row.get("leaf_id"),
            "scae_readiness_status": row.get("scae_readiness_status"),
            "research_sufficiency_reconciliation_ref": row.get("research_sufficiency_reconciliation_ref"),
        }
        for row in leaf_readiness
        if isinstance(row, dict)
    ]
    row = {
        "reconciliation_id": readiness_reconciliation["reconciliation_id"],
        "schema_version": readiness_reconciliation["schema_version"],
        "case_id": readiness_reconciliation["case_id"],
        "dispatch_id": readiness_reconciliation["dispatch_id"],
        "source_classification_matrix_id": readiness_reconciliation.get("source_classification_matrix_id"),
        "source_classification_matrix_digest": readiness_reconciliation.get("source_classification_matrix_digest"),
        "source_direction_verification_digest": readiness_reconciliation.get("source_direction_verification_digest"),
        "source_quality_verification_digest": readiness_reconciliation.get("source_quality_verification_digest"),
        "source_coverage_proof_bundle_digest": readiness_reconciliation.get("source_coverage_proof_bundle_digest"),
        "ready_for_scae": _bool_int(readiness_reconciliation.get("ready_for_scae")),
        "ready_classification_slice_refs": _json(readiness_reconciliation.get("ready_classification_slice_refs", [])),
        "excluded_deadlock_safe_classification_slice_refs": _json(
            readiness_reconciliation.get("excluded_deadlock_safe_classification_slice_refs", [])
        ),
        "blocker_codes": _json(readiness_reconciliation.get("blocker_codes", [])),
        "readiness_row_count": len(readiness_rows),
        "readiness_row_digests": _json(row_digests),
        "leaf_readiness_refs": _json(leaf_refs),
        "readiness_digest": readiness_reconciliation["readiness_digest"],
        "artifact_ref": artifact_ref or readiness_reconciliation.get("artifact_ref"),
        "artifact_path": artifact_path or readiness_reconciliation.get("artifact_path"),
    }
    _upsert(conn, "scae_readiness_reconciliation_refs", row, ["reconciliation_id"])
    return readiness_reconciliation["reconciliation_id"]


def write_research_sufficiency_reconciliation(conn: sqlite3.Connection, reconciliation: Any) -> list[str]:
    """Persist VER-004 per-leaf research sufficiency reconciliation slices."""

    ensure_researcher_verification_persistence_schema(conn)
    bundle_digest: str | None = None
    if hasattr(reconciliation, "reconciliation_bundle"):
        bundle_digest = reconciliation.reconciliation_digest
        reconciliation = reconciliation.reconciliation_bundle
    if isinstance(reconciliation, dict) and "reconciliation_digest" in reconciliation:
        bundle_digest = reconciliation.get("reconciliation_digest")
    rows = _records_from(reconciliation, "research_sufficiency_reconciliation_slices")
    written: list[str] = []
    for record in rows:
        _reject_forbidden_persistence_payload(
            {
                key: value
                for key, value in record.items()
                if key not in {"authority_boundary", "scope_boundaries", "source_refs"}
            },
            "research_sufficiency_reconciliation",
        )
        row = {
            "research_sufficiency_reconciliation_id": record["research_sufficiency_reconciliation_id"],
            "schema_version": record["schema_version"],
            "case_id": record.get("case_id"),
            "dispatch_id": record.get("dispatch_id"),
            "leaf_id": record["leaf_id"],
            "parent_branch_id": record.get("parent_branch_id"),
            "condition_scope": record.get("condition_scope"),
            "certificate_ref": record.get("certificate_ref") or record.get("research_sufficiency_certificate_ref"),
            "certificate_status": record.get("certificate_status"),
            "retrieval_breadth_coverage_ref": record.get("retrieval_breadth_coverage_ref"),
            "coverage_proof_refs": _json(record.get("coverage_proof_refs", [])),
            "classification_slice_refs": _json(record.get("classification_slice_refs", [])),
            "required_escalation_decision_refs": _json(record.get("required_escalation_decision_refs", [])),
            "completed_escalation_decision_refs": _json(record.get("completed_escalation_decision_refs", [])),
            "required_value_fields": _json(record.get("required_value_fields", [])),
            "required_negative_checks": _json(record.get("required_negative_checks", [])),
            "reconciled_status": record["reconciled_status"],
            "research_sufficiency_reconciliation_status": record["research_sufficiency_reconciliation_status"],
            "missing_requirement_codes": _json(record.get("missing_requirement_codes", [])),
            "blocking_reason_codes": _json(record.get("blocking_reason_codes", [])),
            "reason_codes": _json(record.get("reason_codes", [])),
            "scae_ready": _bool_int(record.get("scae_ready")),
            "scae_consumable_under_policy": _bool_int(record.get("scae_consumable_under_policy")),
            "reconciliation_slice_digest": record["reconciliation_slice_digest"],
            "reconciliation_digest": bundle_digest or record.get("reconciliation_digest"),
        }
        _upsert(conn, "research_sufficiency_reconciliation_slices", row, ["research_sufficiency_reconciliation_id"])
        written.append(record["research_sufficiency_reconciliation_id"])
    return written


__all__ = [
    "MIG_006_RESEARCHER_VERIFICATION_MIGRATION",
    "RESEARCHER_PERSISTENCE_VERSION",
    "ResearcherPersistenceError",
    "ensure_researcher_verification_persistence_schema",
    "write_classification_provenance_slices",
    "write_direction_verification_slices",
    "write_evidence_quality_verification_slices",
    "write_leaf_research_assignments",
    "write_normalized_supplemental_evidence",
    "write_research_sufficiency_reconciliation",
    "write_researcher_classification_slices",
    "write_researcher_classifications",
    "write_researcher_context_isolation_audits",
    "write_researcher_coverage_proofs",
    "write_researcher_escalation_decisions",
    "write_researcher_prompt_artifact",
    "write_scae_readiness_reconciliation",
    "write_verification_slices",
]
