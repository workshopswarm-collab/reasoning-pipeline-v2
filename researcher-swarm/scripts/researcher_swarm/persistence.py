"""MIG-004 and MIG-006 researcher-swarm persistence helpers.

These helpers persist compact retrieval, researcher, and verification records.
They store refs, digests, statuses, and bounded metadata, leaving page bodies,
browser transcripts, QDT leaf payloads, prompt text, researcher transcripts,
forecasts, probabilities, intervals, SCAE deltas, and decision recommendations
outside the researcher-swarm persistence surface.
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
from .retrieval import (
    ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION,
    BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION,
    BROWSER_RETRIEVAL_ATTEMPT_SCHEMA_VERSION,
    CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION,
    CONTRADICTION_SEARCH_ATTEMPT_SCHEMA_VERSION,
    EXPECTED_SOURCE_MISSINGNESS_CANDIDATE_SCHEMA_VERSION,
    NATIVE_RESEARCH_ATTEMPT_SCHEMA_VERSION,
    NEGATIVE_CHECK_ATTEMPT_SCHEMA_VERSION,
    PROTECTED_PRIMARY_ACCESS_FAILURE_SCHEMA_VERSION,
    RESEARCH_SUFFICIENCY_CERTIFICATE_SCHEMA_VERSION,
    RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION,
    RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION,
    RETRIEVAL_EVIDENCE_CHUNK_SCHEMA_VERSION,
    RETRIEVAL_EVIDENCE_PROVENANCE_SCHEMA_VERSION,
    RETRIEVAL_EVIDENCE_SCHEMA_VERSION,
    RETRIEVAL_EXPANSION_ATTEMPT_SCHEMA_VERSION,
    RETRIEVAL_FALLBACK_STATE_SCHEMA_VERSION,
    RETRIEVAL_METADATA_FILL_DIAGNOSTIC_SCHEMA_VERSION,
    RETRIEVAL_PACKET_ARTIFACT_TYPE,
    RETRIEVAL_PACKET_SCHEMA_VERSION,
    SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION,
    SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION,
    validate_contradiction_search_attempt,
    validate_evidence_provenance_slice,
    validate_negative_check_attempt,
    validate_research_sufficiency_certificate,
    validate_retrieval_breadth_coverage_slice,
    validate_retrieval_evidence_item,
    validate_retrieval_metadata_fill_diagnostic,
    validate_retrieval_packet,
    validate_source_metadata_classifier_slice,
    validate_source_metadata_resolution,
)
from .retrieval_quality import validate_retrieval_quality_slice
from .supplemental import validate_normalized_supplemental_evidence
from .subagents import validate_leaf_research_barrier


MIG_004_RETRIEVAL_PERSISTENCE_MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "004_retrieval_evidence_persistence.sql"
)
MIG_006_RESEARCHER_VERIFICATION_MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "006_researcher_verification_persistence.sql"
)
RETRIEVAL_PERSISTENCE_VERSION = "ads-mig-004-retrieval-evidence-persistence/v1"
RESEARCHER_PERSISTENCE_VERSION = "ads-mig-006-researcher-verification-persistence/v1"
RESEARCHER_MODEL_LANE = "researcher_leaf_nli_classification"
RETRIEVAL_PACKET_ARTIFACTS_TABLE = "retrieval_packet_artifacts"


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
    "synthesis_conclusion",
    "synthesis_output",
    "final_forecast",
    "forecast_decision",
    "scoreable_prediction",
    "outcome_score",
    "calibration_output",
    "calibration_update",
    "calibration_debt",
    "live_llm_authority",
    "llm_forecast_authority",
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
    "synthesis_conclusion",
    "forecast_decision",
    "scoreable_prediction",
    "calibration_debt",
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


def _collect_forbidden_persistence_paths(
    value: Any,
    path: str = "record",
    *,
    allowed_true_authority_fields: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    allowed_true_authority_fields = allowed_true_authority_fields or set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if normalized in ALLOWED_FALSE_AUTHORITY_FIELDS and child in {False, True}:
                if normalized in allowed_true_authority_fields:
                    pass
                elif normalized == "probability_fields_forbidden" and child is not True:
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
            errors.extend(
                _collect_forbidden_persistence_paths(
                    child,
                    f"{path}.{key}",
                    allowed_true_authority_fields=allowed_true_authority_fields,
                )
            )
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            errors.extend(
                _collect_forbidden_persistence_paths(
                    child,
                    f"{path}[{idx}]",
                    allowed_true_authority_fields=allowed_true_authority_fields,
                )
            )
    return errors


def _reject_forbidden_persistence_payload(
    value: Any,
    path: str = "record",
    *,
    allowed_true_authority_fields: set[str] | None = None,
) -> None:
    errors = _collect_forbidden_persistence_paths(
        value,
        path,
        allowed_true_authority_fields=allowed_true_authority_fields,
    )
    if errors:
        raise ResearcherPersistenceError("; ".join(sorted(set(errors))))


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in _table_columns(conn, table)


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    for column, definition in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_retrieval_persistence_schema(conn: sqlite3.Connection) -> None:
    """Create or upgrade Session 3 MIG-004 retrieval/evidence tables."""

    conn.executescript(MIG_004_RETRIEVAL_PERSISTENCE_MIGRATION.read_text(encoding="utf-8"))
    _ensure_columns(
        conn,
        "missingness_signal_slices",
        {
            "query_context_ref": "TEXT",
            "expected_source_class": "TEXT",
            "expected_source_ref": "TEXT NOT NULL DEFAULT '{}'",
            "missingness_status": "TEXT",
            "missingness_basis": "TEXT",
            "evidence_refs_checked": "TEXT NOT NULL DEFAULT '[]'",
            "attempt_refs_checked": "TEXT NOT NULL DEFAULT '[]'",
            "distinct_absence_mechanism_proof_ref": "TEXT",
            "candidate_tracking_only": "INTEGER NOT NULL DEFAULT 1",
        },
    )


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


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:24]


def _retrieval_packet_id(packet: dict[str, Any], *, artifact_ref: str | None = None) -> str:
    for field in ("retrieval_packet_id", "packet_id", "artifact_id"):
        if _is_non_empty_string(packet.get(field)):
            return str(packet[field])
    if _is_non_empty_string(artifact_ref):
        return str(artifact_ref)
    return _stable_id(
        "retrieval-packet",
        {
            "case_id": packet.get("case_id"),
            "dispatch_id": packet.get("dispatch_id"),
            "question_decomposition_artifact_id": packet.get("question_decomposition_artifact_id"),
            "source_cutoff_timestamp": packet.get("source_cutoff_timestamp"),
        },
    )


def _packet_context(value: Any, *, packet_id: str | None = None) -> dict[str, str | None]:
    if isinstance(value, dict) and value.get("artifact_type") == RETRIEVAL_PACKET_ARTIFACT_TYPE:
        return {
            "case_id": str(value.get("case_id") or ""),
            "dispatch_id": str(value.get("dispatch_id") or ""),
            "retrieval_packet_id": packet_id or _retrieval_packet_id(value),
        }
    return {"case_id": None, "dispatch_id": None, "retrieval_packet_id": packet_id}


def _context_str(record: dict[str, Any], context: dict[str, str | None], field: str) -> str:
    value = record.get(field) or context.get(field)
    if _is_non_empty_string(value):
        return str(value)
    raise ResearcherPersistenceError(f"missing required field: {field}")


def _context_optional(record: dict[str, Any], context: dict[str, str | None], field: str) -> str | None:
    value = record.get(field) or context.get(field)
    return str(value) if _is_non_empty_string(value) else None


def _records_for_key(value: Any, key: str, *, artifact_type: str | None = None) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("artifact_type") == RETRIEVAL_PACKET_ARTIFACT_TYPE:
        raw = value.get(key, [])
        if not isinstance(raw, list):
            raise ResearcherPersistenceError(f"{key} must be a list")
        return [item for item in raw if isinstance(item, dict)]
    if artifact_type and isinstance(value, dict) and value.get("artifact_type") == artifact_type:
        return [value]
    return _records_from(value, key)


def _selected_evidence_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("artifact_type") == RETRIEVAL_PACKET_ARTIFACT_TYPE:
        selected: list[dict[str, Any]] = []
        for result in value.get("leaf_retrieval_results", []):
            if not isinstance(result, dict):
                continue
            records = result.get("selected_evidence", [])
            if isinstance(records, list):
                selected.extend(item for item in records if isinstance(item, dict))
        return selected
    return _records_for_key(value, "retrieval_evidence_items", artifact_type="retrieval_evidence")


def _mixed_source_access_records(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(value, dict) and value.get("artifact_type") == RETRIEVAL_PACKET_ARTIFACT_TYPE:
        failures = _records_for_key(value, "protected_primary_access_failures")
        missingness = _records_for_key(value, "missingness_candidates")
        return failures, missingness
    records = _records_from(value)
    failures = [item for item in records if item.get("artifact_type") == "protected_primary_access_failure"]
    missingness = [item for item in records if item.get("artifact_type") == "expected_source_missingness_candidate"]
    if len(failures) + len(missingness) != len(records):
        raise ResearcherPersistenceError("source access records must be access failures or missingness candidates")
    return failures, missingness


def _validate_retrieval_record(record: dict[str, Any], validator: Any, path: str) -> None:
    errors: list[str] = []
    validator(record, path, errors)
    if errors:
        raise ResearcherPersistenceError(f"{path} invalid: " + "; ".join(errors))


def _validate_simple_artifact(
    record: dict[str, Any],
    *,
    artifact_type: str,
    schema_version: str,
    id_field: str,
    path: str,
) -> None:
    if record.get("artifact_type") != artifact_type:
        raise ResearcherPersistenceError(f"{path}.artifact_type must be {artifact_type}")
    if record.get("schema_version") != schema_version:
        raise ResearcherPersistenceError(f"{path}.schema_version must be {schema_version}")
    _required_str(record, id_field)


def _retrieval_reject(record: Any, path: str, *, allow_sufficiency_authority: bool = False) -> None:
    allowed = {"research_sufficiency_authority"} if allow_sufficiency_authority else None
    _reject_forbidden_persistence_payload(
        record,
        path,
        allowed_true_authority_fields=allowed,
    )


def write_retrieval_packet(
    conn: sqlite3.Connection,
    retrieval_packet: dict[str, Any],
    *,
    artifact_ref: str | None = None,
    artifact_path: str | None = None,
) -> str:
    """Persist a compact retrieval-packet artifact row without storing the packet body."""

    ensure_retrieval_persistence_schema(conn)
    if not isinstance(retrieval_packet, dict):
        raise ResearcherPersistenceError("retrieval_packet must be an object")
    validation = validate_retrieval_packet(retrieval_packet)
    if not validation.valid:
        raise ResearcherPersistenceError("retrieval packet invalid: " + "; ".join(validation.errors))
    _retrieval_reject(retrieval_packet, "retrieval_packet", allow_sufficiency_authority=True)
    packet_id = _retrieval_packet_id(retrieval_packet, artifact_ref=artifact_ref)
    leaf_results = [
        result for result in retrieval_packet.get("leaf_retrieval_results", []) if isinstance(result, dict)
    ]
    evidence_count = sum(
        len(result.get("selected_evidence", []))
        for result in leaf_results
        if isinstance(result.get("selected_evidence", []), list)
    )
    omitted_count = sum(
        len(result.get("omitted_candidates", []))
        for result in leaf_results
        if isinstance(result.get("omitted_candidates", []), list)
    )
    summary = retrieval_packet.get("research_sufficiency_summary", {})
    if not isinstance(summary, dict):
        summary = {}
    row = {
        "retrieval_packet_id": packet_id,
        "schema_version": retrieval_packet["schema_version"],
        "case_id": _required_str(retrieval_packet, "case_id"),
        "case_key": retrieval_packet.get("case_key"),
        "dispatch_id": _required_str(retrieval_packet, "dispatch_id"),
        "question_decomposition_artifact_id": retrieval_packet.get("question_decomposition_artifact_id"),
        "forecast_timestamp": retrieval_packet.get("forecast_timestamp"),
        "source_cutoff_timestamp": retrieval_packet.get("source_cutoff_timestamp"),
        "temporal_isolation_status": retrieval_packet["temporal_isolation_status"],
        "policy_context_ref": retrieval_packet.get("policy_context_ref"),
        "artifact_ref": artifact_ref or retrieval_packet.get("artifact_ref"),
        "artifact_path": artifact_path or retrieval_packet.get("artifact_path"),
        "packet_sha256": retrieval_packet.get("packet_sha256") or _prefixed_sha256(retrieval_packet),
        "leaf_count": len(leaf_results),
        "evidence_count": evidence_count,
        "omitted_candidate_count": omitted_count,
        "quality_summary_ref": retrieval_packet.get("retrieval_quality_summary_ref"),
        "research_sufficiency_status": summary.get("certificate_status"),
        "classification_dispatch_status": summary.get("classification_dispatch_status"),
        "leaf_certificate_refs": _json(summary.get("leaf_certificate_refs", [])),
        "schema_feature_gates": _json(retrieval_packet.get("schema_feature_gates", {})),
        "validation_summary": _json(retrieval_packet.get("validation_summary", {})),
    }
    _upsert(conn, RETRIEVAL_PACKET_ARTIFACTS_TABLE, row, ["retrieval_packet_id"])
    return packet_id


def write_retrieval_evidence_items(conn: sqlite3.Connection, evidence_items: Any) -> list[str]:
    """Persist compact retrieval-evidence/v1 rows."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(evidence_items)
    rows = _selected_evidence_records(evidence_items)
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_retrieval_evidence_item, "retrieval_evidence")
        _retrieval_reject(record, "retrieval_evidence")
        row = {
            "evidence_ref": record["evidence_ref"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "parent_branch_id": record.get("parent_branch_id"),
            "retrieval_transport": record["retrieval_transport"],
            "transport_attempt_ref": record["transport_attempt_ref"],
            "requested_url": record.get("requested_url"),
            "final_url": record.get("final_url"),
            "canonical_url": record.get("canonical_url"),
            "canonical_source_id": record.get("canonical_source_id"),
            "source_metadata_resolution_ref": record.get("source_metadata_resolution_ref"),
            "claim_family_resolution_refs": _json(record.get("claim_family_resolution_refs", [])),
            "source_family_id": record.get("source_family_id"),
            "source_class": record["source_class"],
            "independence_status": record["independence_status"],
            "temporal_gate_status": record["temporal_gate_status"],
            "source_published_at": record.get("source_published_at"),
            "source_updated_at": record.get("source_updated_at"),
            "source_observed_at": record.get("source_observed_at"),
            "source_authored_at": record.get("source_authored_at"),
            "captured_at": record.get("captured_at"),
            "artifact_generated_at": record.get("artifact_generated_at"),
            "retrieval_capture_for_dispatch": _bool_int(record.get("retrieval_capture_for_dispatch")),
            "pre_dispatch_input_ref": record.get("pre_dispatch_input_ref"),
            "content_sha256": record["content_sha256"],
            "chunk_refs": _json(record.get("chunk_refs", [])),
            "retrieval_score": float(record.get("retrieval_score", 0.0)),
            "admission_status": record["admission_status"],
            "admission_reason_codes": _json(record.get("admission_reason_codes", [])),
        }
        _upsert(conn, "retrieval_evidence_items", row, ["evidence_ref"])
        written.append(record["evidence_ref"])
    return written


def write_retrieval_evidence_chunk_slices(conn: sqlite3.Connection, chunk_slices: Any) -> list[str]:
    """Persist bounded chunk/span refs without storing excerpt text."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(chunk_slices)
    rows = _records_for_key(chunk_slices, "evidence_chunks", artifact_type="retrieval_evidence_chunk")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="retrieval_evidence_chunk",
            schema_version=RETRIEVAL_EVIDENCE_CHUNK_SCHEMA_VERSION,
            id_field="chunk_ref",
            path="retrieval_evidence_chunk",
        )
        _retrieval_reject(record, "retrieval_evidence_chunk")
        row = {
            "chunk_ref": record["chunk_ref"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "evidence_ref": record["evidence_ref"],
            "content_artifact_ref": record["content_artifact_ref"],
            "chunk_index": int(record["chunk_index"]),
            "char_start": int(record["char_start"]),
            "char_end": int(record["char_end"]),
            "text_sha256": record["text_sha256"],
            "excerpt_char_count": int(record.get("excerpt_char_count", 0)),
            "excerpt_policy": record["excerpt_policy"],
            "contains_claim_candidate_ids": _json(record.get("contains_claim_candidate_ids", [])),
        }
        _upsert(conn, "retrieval_evidence_chunk_slices", row, ["chunk_ref"])
        written.append(record["chunk_ref"])
    return written


def write_native_research_attempts(conn: sqlite3.Connection, attempts: Any) -> list[str]:
    """Persist compact GPT-native research transport attempt records."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(attempts)
    rows = _records_for_key(attempts, "native_research_attempts", artifact_type="native_research_attempt")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="native_research_attempt",
            schema_version=NATIVE_RESEARCH_ATTEMPT_SCHEMA_VERSION,
            id_field="attempt_id",
            path="native_research_attempt",
        )
        _retrieval_reject(record, "native_research_attempt")
        proposed_metadata = record.get("model_proposed_source_metadata", {})
        row = {
            "attempt_id": record["attempt_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_variant_id": record.get("query_variant_id"),
            "model_lane_id": record["model_lane_id"],
            "resolved_model_id": record["resolved_model_id"],
            "prompt_template_id": record["prompt_template_id"],
            "query_manifest_sha256": record["query_manifest_sha256"],
            "research_transport": record["research_transport"],
            "candidate_citation_refs": _json(record.get("candidate_citation_refs", [])),
            "candidate_claim_refs": _json(record.get("candidate_claim_refs", [])),
            "contradiction_candidate_refs": _json(record.get("contradiction_candidate_refs", [])),
            "negative_check_candidate_refs": _json(record.get("negative_check_candidate_refs", [])),
            "model_proposed_source_metadata_sha256": _prefixed_sha256(proposed_metadata),
            "candidate_output_schema_version": record.get("candidate_output_schema_version"),
            "attempt_status": record["attempt_status"],
            "native_transport_availability_status": record["native_transport_availability_status"],
            "failure_reason_codes": _json(record.get("failure_reason_codes", [])),
            "diagnostic_only_when_unavailable": _bool_int(record.get("diagnostic_only_when_unavailable")),
            "non_blocking_when_alternative_transport_satisfies_requirements": _bool_int(
                record.get("non_blocking_when_alternative_transport_satisfies_requirements")
            ),
            "resolver_required_for_accepted_metadata": record.get("resolver_required_for_accepted_metadata"),
            "feature_gate_status": record.get("feature_gate_status"),
        }
        _upsert(conn, "native_research_attempts", row, ["attempt_id"])
        written.append(record["attempt_id"])
    return written


def write_browser_retrieval_attempts(conn: sqlite3.Connection, attempts: Any) -> list[str]:
    """Persist compact OpenClaw browser retrieval attempts."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(attempts)
    rows = _records_for_key(attempts, "browser_retrieval_attempts", artifact_type="browser_retrieval_attempt")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="browser_retrieval_attempt",
            schema_version=BROWSER_RETRIEVAL_ATTEMPT_SCHEMA_VERSION,
            id_field="attempt_id",
            path="browser_retrieval_attempt",
        )
        _retrieval_reject(record, "browser_retrieval_attempt")
        row = {
            "attempt_id": record["attempt_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_variant_id": record.get("query_variant_id"),
            "query_text_sha256": record.get("query_text_sha256"),
            "browser_session_ref": record.get("browser_session_ref"),
            "browser_provider_id": record["browser_provider_id"],
            "openclaw_transport_ref": record.get("openclaw_transport_ref"),
            "provider_capabilities": _json(record.get("provider_capabilities", [])),
            "provider_availability_status": record.get("provider_availability_status"),
            "news_feed_api_enabled": _bool_int(record.get("news_feed_api_enabled")),
            "navigation_mode": record["navigation_mode"],
            "direct_url_source_ref": record.get("direct_url_source_ref"),
            "search_engine_or_navigation_source": record.get("search_engine_or_navigation_source"),
            "result_rank": int(record.get("result_rank", 0)),
            "requested_url": record.get("requested_url"),
            "final_url": record.get("final_url"),
            "canonical_url": record.get("canonical_url"),
            "normalized_domain": record.get("normalized_domain"),
            "page_title_sha256": record.get("page_title_sha256"),
            "captured_at": record.get("captured_at"),
            "published_at": record.get("published_at"),
            "published_at_extraction_method": record.get("published_at_extraction_method"),
            "rendered_text_sha256": record.get("rendered_text_sha256"),
            "extracted_text_sha256": record.get("extracted_text_sha256"),
            "screenshot_artifact_ref": record.get("screenshot_artifact_ref"),
            "content_artifact_ref": record.get("content_artifact_ref"),
            "extraction_status": record["extraction_status"],
            "feature_gate_status": record.get("feature_gate_status"),
        }
        _upsert(conn, "browser_retrieval_attempts", row, ["attempt_id"])
        written.append(record["attempt_id"])
    return written


def write_browser_search_provider_diagnostics(conn: sqlite3.Connection, diagnostics: Any) -> list[str]:
    """Persist browser/search provider availability diagnostics."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(diagnostics)
    rows = _records_for_key(
        diagnostics,
        "browser_search_provider_diagnostics",
        artifact_type="browser_search_provider_diagnostic",
    )
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="browser_search_provider_diagnostic",
            schema_version=BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION,
            id_field="provider_id",
            path="browser_search_provider_diagnostic",
        )
        _retrieval_reject(record, "browser_search_provider_diagnostic")
        diagnostic_id = record.get("provider_diagnostic_id") or _stable_id(
            "browser-provider-diagnostic",
            {
                "provider_id": record.get("provider_id"),
                "case_id": context.get("case_id"),
                "dispatch_id": context.get("dispatch_id"),
                "checked_at": record.get("checked_at"),
                "availability_status": record.get("availability_status"),
            },
        )
        row = {
            "provider_diagnostic_id": diagnostic_id,
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "provider_id": record["provider_id"],
            "provider_refs": _json(record.get("provider_refs", [])),
            "capabilities": _json(record.get("capabilities", [])),
            "availability_status": record["availability_status"],
            "news_feed_api_enabled": _bool_int(record.get("news_feed_api_enabled")),
            "direct_url_priority": record.get("direct_url_priority"),
            "unavailable_reason": record.get("unavailable_reason"),
            "checked_at": record.get("checked_at"),
            "feature_gate_status": record.get("feature_gate_status"),
            "diagnostic_sha256": _prefixed_sha256(record),
        }
        _upsert(conn, "browser_search_provider_diagnostics", row, ["provider_diagnostic_id"])
        written.append(diagnostic_id)
    return written


def write_source_metadata_classifier_slices(conn: sqlite3.Connection, classifier_slices: Any) -> list[str]:
    """Persist compact RET-011 classifier assist slices without model output bodies."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(classifier_slices)
    rows = _records_for_key(
        classifier_slices,
        "source_metadata_classifier_slices",
        artifact_type="source_metadata_classifier_slice",
    )
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_source_metadata_classifier_slice, "source_metadata_classifier_slice")
        _retrieval_reject(record, "source_metadata_classifier_slice")
        row = {
            "classifier_slice_id": record["classifier_slice_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "candidate_id": record.get("candidate_id"),
            "leaf_id": record.get("leaf_id"),
            "model_lane_id": record["model_lane_id"],
            "resolved_model_id": record["resolved_model_id"],
            "provider_model_key": record["provider_model_key"],
            "model_policy_ref": record.get("model_policy_ref"),
            "prompt_template_id": record["prompt_template_id"],
            "prompt_template_sha256": record["prompt_template_sha256"],
            "input_candidate_sha256": record["input_candidate_sha256"],
            "classifier_output_schema_version": record["classifier_output_schema_version"],
            "proposed_source_class": record.get("proposed_source_class"),
            "source_class_confidence": record.get("source_class_confidence"),
            "proposed_source_family_hint_sha256": _prefixed_sha256(record.get("proposed_source_family_hint")),
            "source_family_confidence": record.get("source_family_confidence"),
            "syndication_hint": record.get("syndication_hint"),
            "atomic_claim_candidate_count": len(record.get("atomic_claim_candidates", [])),
            "visible_date_candidate_count": len(record.get("visible_date_candidates", [])),
            "reason_codes": _json(record.get("reason_codes", [])),
            "classifier_version": record.get("classifier_version"),
        }
        _upsert(conn, "source_metadata_classifier_slices", row, ["classifier_slice_id"])
        written.append(record["classifier_slice_id"])
    return written


def write_source_metadata_resolution_slices(conn: sqlite3.Connection, resolution_slices: Any) -> list[str]:
    """Persist deterministic source metadata resolver slices."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(resolution_slices)
    rows = _records_for_key(
        resolution_slices,
        "source_metadata_resolutions",
        artifact_type="source_metadata_resolution",
    )
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_source_metadata_resolution, "source_metadata_resolution")
        _retrieval_reject(record, "source_metadata_resolution")
        row = {
            "resolution_id": record["resolution_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "evidence_ref": record["evidence_ref"],
            "transport_attempt_ref": record["transport_attempt_ref"],
            "requested_url": record.get("requested_url"),
            "final_url": record.get("final_url"),
            "canonical_url": record.get("canonical_url"),
            "registrable_domain": record.get("registrable_domain"),
            "canonical_source_id": record.get("canonical_source_id"),
            "content_sha256": record.get("content_sha256"),
            "source_class": record["source_class"],
            "source_class_resolution_method": record.get("source_class_resolution_method"),
            "source_family_id": record.get("source_family_id"),
            "source_family_resolution_method": record.get("source_family_resolution_method"),
            "source_family_status": record.get("source_family_status"),
            "claim_family_resolution_refs": _json(record.get("claim_family_resolution_refs", [])),
            "claim_family_ids": _json(record.get("claim_family_ids", [])),
            "claim_family_resolution_method": record.get("claim_family_resolution_method"),
            "temporal_safety_status": record["temporal_safety_status"],
            "published_at": record.get("published_at"),
            "published_at_method": record.get("published_at_method"),
            "classifier_slice_ref": record.get("classifier_slice_ref"),
            "classifier_acceptance_status": record.get("classifier_acceptance_status"),
            "classifier_acceptance_reason_codes": _json(record.get("classifier_acceptance_reason_codes", [])),
            "metadata_confidence": record.get("metadata_confidence"),
            "counts_toward_breadth": _bool_int(record.get("counts_toward_breadth")),
            "unknown_reason_codes": _json(record.get("unknown_reason_codes", [])),
            "accepted_metadata_authority": record["accepted_metadata_authority"],
            "deterministic_resolver_accepted_fields": _json(record.get("deterministic_resolver_accepted_fields", [])),
            "model_proposed_metadata_counted": _bool_int(record.get("model_proposed_metadata_counted")),
            "normalizer_version": record.get("normalizer_version"),
            "ret_010_resolver_version": record.get("ret_010_resolver_version"),
        }
        _upsert(conn, "source_metadata_resolution_slices", row, ["resolution_id"])
        written.append(record["resolution_id"])
    return written


def write_atomic_claim_candidate_slices(conn: sqlite3.Connection, candidates: Any) -> list[str]:
    """Persist atomic claim candidates as refs/hashes without tuple bodies."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(candidates)
    rows = _records_for_key(candidates, "atomic_claim_candidates", artifact_type="atomic_claim_candidate")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="atomic_claim_candidate",
            schema_version=ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION,
            id_field="claim_candidate_id",
            path="atomic_claim_candidate",
        )
        _retrieval_reject(record, "atomic_claim_candidate")
        row = {
            "claim_candidate_id": record["claim_candidate_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "evidence_ref": record["evidence_ref"],
            "leaf_id": record["leaf_id"],
            "chunk_refs": _json(record.get("chunk_refs", [])),
            "extraction_method": record["extraction_method"],
            "model_lane_id": record.get("model_lane_id"),
            "prompt_template_id": record.get("prompt_template_id"),
            "proposed_tuple_sha256": _prefixed_sha256(record.get("proposed_tuple", {})),
            "supporting_span_refs": _json(record.get("supporting_span_refs", [])),
            "candidate_confidence": record.get("candidate_confidence"),
            "validation_status": record["validation_status"],
            "validator_reason_codes": _json(record.get("validator_reason_codes", [])),
        }
        _upsert(conn, "atomic_claim_candidate_slices", row, ["claim_candidate_id"])
        written.append(record["claim_candidate_id"])
    return written


def write_claim_family_resolution_slices(conn: sqlite3.Connection, resolutions: Any) -> list[str]:
    """Persist claim-family resolution refs and tuple hashes."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(resolutions)
    rows = _records_for_key(resolutions, "claim_family_resolutions", artifact_type="claim_family_resolution")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="claim_family_resolution",
            schema_version=CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION,
            id_field="claim_family_resolution_id",
            path="claim_family_resolution",
        )
        _retrieval_reject(record, "claim_family_resolution")
        row = {
            "claim_family_resolution_id": record["claim_family_resolution_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "claim_family_id": record["claim_family_id"],
            "claim_candidate_refs": _json(record.get("claim_candidate_refs", [])),
            "normalized_tuple_sha256": record.get("normalized_tuple_sha256") or _prefixed_sha256(
                record.get("normalized_tuple", {})
            ),
            "resolution_method": record["resolution_method"],
            "equivalence_status": record["equivalence_status"],
            "contradiction_family_id": record.get("contradiction_family_id"),
            "counts_toward_claim_family_breadth": _bool_int(record.get("counts_toward_claim_family_breadth")),
            "reason_codes": _json(record.get("reason_codes", [])),
        }
        _upsert(conn, "claim_family_resolution_slices", row, ["claim_family_resolution_id"])
        written.append(record["claim_family_resolution_id"])
    return written


def write_metadata_fill_diagnostics(conn: sqlite3.Connection, diagnostics: Any) -> list[str]:
    """Persist retrieval metadata fill-rate diagnostics."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(diagnostics)
    rows = _records_for_key(
        diagnostics,
        "retrieval_metadata_fill_diagnostics",
        artifact_type="retrieval_metadata_fill_diagnostic",
    )
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_retrieval_metadata_fill_diagnostic, "retrieval_metadata_fill_diagnostic")
        _retrieval_reject(record, "retrieval_metadata_fill_diagnostic")
        row = {
            "diagnostic_id": record["diagnostic_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "retrieval_transport": record["retrieval_transport"],
            "raw_candidate_count": int(record.get("raw_candidate_count", 0)),
            "admitted_ref_count": int(record.get("admitted_ref_count", 0)),
            "field_fill_counts": _json(record.get("field_fill_counts", {})),
            "unknown_counts": _json(record.get("unknown_counts", {})),
            "fill_rates": _json(record.get("fill_rates", {})),
            "diagnostic_authority": record["diagnostic_authority"],
            "evaluator_version": record.get("evaluator_version"),
        }
        _upsert(conn, "retrieval_metadata_fill_diagnostics", row, ["diagnostic_id"])
        written.append(record["diagnostic_id"])
    return written


def write_retrieval_quality_slices(conn: sqlite3.Connection, quality_slices: Any) -> list[str]:
    """Persist RET-003 retrieval quality slices."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(quality_slices)
    rows = _records_for_key(quality_slices, "retrieval_quality_slices", artifact_type="retrieval_quality_slice")
    written: list[str] = []
    for record in rows:
        validation = validate_retrieval_quality_slice(record)
        if not validation.valid:
            raise ResearcherPersistenceError("retrieval quality slice invalid: " + "; ".join(validation.errors))
        _retrieval_reject(record, "retrieval_quality_slice")
        row = {
            "slice_id": record["slice_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "selected_evidence_refs": _json(record.get("selected_evidence_refs", [])),
            "quality_score": float(record["quality_score"]),
            "quality_status": record["quality_status"],
            "penalty_points": float(record["penalty_points"]),
            "diagnostic_codes": _json(record.get("diagnostic_codes", [])),
            "low_breadth_reason_codes": _json(record.get("low_breadth_reason_codes", [])),
            "dimensions": _json(record.get("dimensions", {})),
            "scorer_version": record.get("scorer_version"),
        }
        _upsert(conn, "retrieval_quality_slices", row, ["slice_id"])
        written.append(record["slice_id"])
    return written


def write_evidence_provenance_slices(conn: sqlite3.Connection, provenance_slices: Any) -> list[str]:
    """Persist retrieval provenance refs without nested resolver or temporal payload bodies."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(provenance_slices)
    rows = _records_for_key(
        provenance_slices,
        "retrieval_evidence_provenance_slices",
        artifact_type="retrieval_evidence_provenance",
    )
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_evidence_provenance_slice, "retrieval_evidence_provenance")
        _retrieval_reject(record, "retrieval_evidence_provenance")
        row = {
            "provenance_id": record["provenance_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "evidence_ref": record["evidence_ref"],
            "candidate_id": record.get("candidate_id"),
            "retrieval_transport": record["retrieval_transport"],
            "transport_attempt_ref": record.get("transport_attempt_ref"),
            "browser_attempt_ref": record.get("browser_attempt_ref"),
            "native_research_attempt_ref": record.get("native_research_attempt_ref"),
            "source_metadata_resolution_ref": record["source_metadata_resolution_ref"],
            "source_metadata_classifier_ref": record.get("source_metadata_classifier_ref"),
            "atomic_claim_candidate_refs": _json(record.get("atomic_claim_candidate_refs", [])),
            "claim_family_resolution_refs": _json(record.get("claim_family_resolution_refs", [])),
            "claim_family_ids": _json(record.get("claim_family_ids", [])),
            "classifier_acceptance_status": record.get("classifier_acceptance_status"),
            "classifier_acceptance_reason_codes": _json(record.get("classifier_acceptance_reason_codes", [])),
            "metadata_confidence": record.get("metadata_confidence"),
            "unknown_reason_codes": _json(record.get("unknown_reason_codes", [])),
            "requested_url": record.get("requested_url"),
            "final_url": record.get("final_url"),
            "canonical_url": record.get("canonical_url"),
            "url_identity_basis": record.get("url_identity_basis"),
            "captured_at": record.get("captured_at"),
            "artifact_generated_at": record.get("artifact_generated_at"),
            "source_published_at": record.get("source_published_at"),
            "source_updated_at": record.get("source_updated_at"),
            "source_observed_at": record.get("source_observed_at"),
            "published_at_extraction_method": record.get("published_at_extraction_method"),
            "canonical_source_id": record.get("canonical_source_id"),
            "source_class": record["source_class"],
            "source_family_id": record.get("source_family_id"),
            "source_family_status": record.get("source_family_status"),
            "independence_status": record.get("independence_status"),
            "content_sha256": record.get("content_sha256"),
            "temporal_gate_status": record.get("temporal_gate_status"),
            "temporal_validation_ref": record.get("temporal_validation_ref"),
            "temporal_validation_sha256": _prefixed_sha256(record.get("temporal_validation", {})),
            "counts_toward_breadth": _bool_int(record.get("counts_toward_breadth")),
            "normalizer_version": record.get("normalizer_version"),
        }
        _upsert(conn, "retrieval_evidence_provenance_slices", row, ["provenance_id"])
        written.append(record["provenance_id"])
    return written


def write_retrieval_breadth_profile(conn: sqlite3.Connection, profiles: Any) -> list[str]:
    """Persist compact RET-009 breadth profiles."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(profiles)
    rows = _records_for_key(profiles, "retrieval_breadth_profiles", artifact_type="retrieval_breadth_profile")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="retrieval_breadth_profile",
            schema_version=RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION,
            id_field="profile_id",
            path="retrieval_breadth_profile",
        )
        _retrieval_reject(record, "retrieval_breadth_profile")
        row = {
            "profile_id": record["profile_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "source_class_requirements": _json(record.get("source_class_requirements", {})),
            "claim_family_requirements": _json(record.get("claim_family_requirements", {})),
            "source_family_requirements": _json(record.get("source_family_requirements", {})),
            "freshness_requirement": _json(record.get("freshness_requirement", {})),
            "contradiction_search": _json(record.get("contradiction_search", {})),
            "negative_checks": _json(record.get("negative_checks", {})),
            "retrieval_volume_tier": _json(record.get("retrieval_volume_tier", {})),
            "feature_gate_status": _json(record.get("feature_gate_status", {})),
        }
        _upsert(conn, "retrieval_breadth_profiles", row, ["profile_id"])
        written.append(record["profile_id"])
    return written


def write_retrieval_breadth_coverage_slices(conn: sqlite3.Connection, coverage_slices: Any) -> list[str]:
    """Persist RET-009 breadth coverage slices."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(coverage_slices)
    rows = _records_for_key(
        coverage_slices,
        "retrieval_breadth_coverage_slices",
        artifact_type="retrieval_breadth_coverage",
    )
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_retrieval_breadth_coverage_slice, "retrieval_breadth_coverage")
        _retrieval_reject(record, "retrieval_breadth_coverage")
        row = {
            "coverage_id": record["coverage_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "breadth_profile_ref": record["breadth_profile_ref"],
            "source_class_coverage": _json(record.get("source_class_coverage", {})),
            "claim_family_count": int(record.get("claim_family_count", 0)),
            "source_family_count": int(record.get("source_family_count", 0)),
            "fresh_source_count": int(record.get("fresh_source_count", 0)),
            "contradiction_attempt_refs": _json(record.get("contradiction_attempt_refs", [])),
            "negative_check_attempt_refs": _json(record.get("negative_check_attempt_refs", [])),
            "protected_primary_status": record["protected_primary_status"],
            "protected_primary_resolution_basis": record.get("protected_primary_resolution_basis"),
            "structural_unanswerability_proof_ref": record.get("structural_unanswerability_proof_ref"),
            "raw_candidate_count": int(record.get("raw_candidate_count", 0)),
            "admitted_ref_count": int(record.get("admitted_ref_count", 0)),
            "independent_claim_family_ids": _json(record.get("independent_claim_family_ids", [])),
            "independent_source_family_ids": _json(record.get("independent_source_family_ids", [])),
            "metadata_fill_diagnostic_refs": _json(record.get("metadata_fill_diagnostic_refs", [])),
            "unknown_field_counts": _json(record.get("unknown_field_counts", {})),
            "blocking_unknown_fields": _json(record.get("blocking_unknown_fields", [])),
            "expansion_required": _bool_int(record.get("expansion_required")),
            "expansion_requirement_codes": _json(record.get("expansion_requirement_codes", [])),
            "unsatisfied_breadth_dimensions": _json(record.get("unsatisfied_breadth_dimensions", [])),
            "breadth_certified": _bool_int(record.get("breadth_certified")),
            "evaluator_version": record.get("evaluator_version"),
        }
        _upsert(conn, "retrieval_breadth_coverage_slices", row, ["coverage_id"])
        written.append(record["coverage_id"])
    return written


def write_contradiction_search_attempts(conn: sqlite3.Connection, attempts: Any) -> list[str]:
    """Persist contradiction-search attempt refs/statuses."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(attempts)
    rows = _records_for_key(attempts, "contradiction_search_attempts", artifact_type="contradiction_search_attempt")
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_contradiction_search_attempt, "contradiction_search_attempt")
        _retrieval_reject(record, "contradiction_search_attempt")
        row = {
            "attempt_id": record["attempt_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "query_variant_id": record.get("query_variant_id"),
            "query_text_sha256": record.get("query_text_sha256"),
            "source_refs_checked": _json(record.get("source_refs_checked", [])),
            "contradiction_found": _bool_int(record.get("contradiction_found")),
            "outcome_status": record["outcome_status"],
            "attempt_authority": record["attempt_authority"],
            "evaluator_version": record.get("evaluator_version"),
        }
        _upsert(conn, "contradiction_search_attempts", row, ["attempt_id"])
        written.append(record["attempt_id"])
    return written


def write_negative_check_attempts(conn: sqlite3.Connection, attempts: Any) -> list[str]:
    """Persist negative-check attempt refs/statuses."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(attempts)
    rows = _records_for_key(attempts, "negative_check_attempts", artifact_type="negative_check_attempt")
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_negative_check_attempt, "negative_check_attempt")
        _retrieval_reject(record, "negative_check_attempt")
        row = {
            "attempt_id": record["attempt_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "negative_check": record["negative_check"],
            "query_text_sha256": record["query_text_sha256"],
            "source_refs_checked": _json(record.get("source_refs_checked", [])),
            "outcome_status": record["outcome_status"],
            "no_confirmation_found": _bool_int(record.get("no_confirmation_found")),
            "attempt_authority": record["attempt_authority"],
            "evaluator_version": record.get("evaluator_version"),
        }
        _upsert(conn, "negative_check_attempts", row, ["attempt_id"])
        written.append(record["attempt_id"])
    return written


def write_source_access_and_missingness_slices(conn: sqlite3.Connection, records: Any) -> dict[str, list[str]]:
    """Persist RET-005 protected-source access failures and missingness candidates."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(records)
    failures, missingness = _mixed_source_access_records(records)
    failure_ids: list[str] = []
    missingness_ids: list[str] = []
    for record in failures:
        _validate_simple_artifact(
            record,
            artifact_type="protected_primary_access_failure",
            schema_version=PROTECTED_PRIMARY_ACCESS_FAILURE_SCHEMA_VERSION,
            id_field="failure_id",
            path="protected_primary_access_failure",
        )
        _retrieval_reject(record, "protected_primary_access_failure")
        row = {
            "failure_id": record["failure_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "required_source_classes": _json(record.get("required_source_classes", [])),
            "expected_source_refs": _json(record.get("expected_source_refs", [])),
            "observed_attempt_refs": _json(record.get("observed_attempt_refs", [])),
            "admitted_evidence_refs": _json(record.get("admitted_evidence_refs", [])),
            "access_status": record["access_status"],
            "reason_codes": _json(record.get("reason_codes", [])),
            "candidate_tracking_only": _bool_int(record.get("candidate_tracking_only")),
            "tracker_version": record.get("tracker_version"),
        }
        _upsert(conn, "source_access_failure_slices", row, ["failure_id"])
        failure_ids.append(record["failure_id"])
    for record in missingness:
        _validate_simple_artifact(
            record,
            artifact_type="expected_source_missingness_candidate",
            schema_version=EXPECTED_SOURCE_MISSINGNESS_CANDIDATE_SCHEMA_VERSION,
            id_field="candidate_id",
            path="expected_source_missingness_candidate",
        )
        _retrieval_reject(record, "expected_source_missingness_candidate")
        slice_id = record["candidate_id"]
        payload = {
            "expected_source_class": record.get("expected_source_class"),
            "missingness_status": record.get("missingness_status"),
            "missingness_basis": record.get("missingness_basis"),
            "candidate_tracking_only": bool(record.get("candidate_tracking_only")),
        }
        row = {
            "slice_id": slice_id,
            "schema_version": record["schema_version"],
            "artifact_type": record["artifact_type"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "leaf_id": record.get("leaf_id"),
            "parent_branch_id": record.get("parent_branch_id"),
            "condition_scope": record.get("condition_scope"),
            "feature_id": "RET-005",
            "surface_name": "missingness_signal_slices",
            "source_ref": None,
            "source_family_id": None,
            "claim_family_id": None,
            "mechanism_family_id": None,
            "dependency_group_id": None,
            "signed_log_odds_delta": None,
            "accepted_for_ledger_input": 0,
            "diagnostic_only": 1,
            "can_increase_evidence_strength": 0,
            "live_forecast_authority": 0,
            "writes_scae_ledger": 0,
            "writes_production_forecast": 0,
            "reason_codes": _json(record.get("reason_codes", [])),
            "source_refs": _json(record.get("expected_source_ref", [])),
            "payload_json": _json(payload),
            "payload_sha256": _prefixed_sha256(payload),
            "query_context_ref": record.get("query_context_ref"),
            "expected_source_class": record.get("expected_source_class"),
            "expected_source_ref": _json(record.get("expected_source_ref", {})),
            "missingness_status": record.get("missingness_status"),
            "missingness_basis": record.get("missingness_basis"),
            "evidence_refs_checked": _json(record.get("evidence_refs_checked", [])),
            "attempt_refs_checked": _json(record.get("attempt_refs_checked", [])),
            "distinct_absence_mechanism_proof_ref": record.get("distinct_absence_mechanism_proof_ref"),
            "candidate_tracking_only": _bool_int(record.get("candidate_tracking_only")),
        }
        _upsert(conn, "missingness_signal_slices", row, ["slice_id"])
        missingness_ids.append(slice_id)
    return {"source_access_failure_ids": failure_ids, "missingness_signal_ids": missingness_ids}


def write_retrieval_fallback_state(conn: sqlite3.Connection, fallback_states: Any) -> list[str]:
    """Persist RET-006 fallback state records."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(fallback_states)
    rows = _records_for_key(fallback_states, "retrieval_fallback_states", artifact_type="retrieval_fallback_state")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="retrieval_fallback_state",
            schema_version=RETRIEVAL_FALLBACK_STATE_SCHEMA_VERSION,
            id_field="fallback_state_id",
            path="retrieval_fallback_state",
        )
        _retrieval_reject(record, "retrieval_fallback_state")
        row = {
            "fallback_state_id": record["fallback_state_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "targeted_expansion_attempt_refs": _json(record.get("targeted_expansion_attempt_refs", [])),
            "targeted_expansion_required_before_macro_fallback": _bool_int(
                record.get("targeted_expansion_required_before_macro_fallback")
            ),
            "macro_fallback_requested": _bool_int(record.get("macro_fallback_requested")),
            "macro_fallback_used": _bool_int(record.get("macro_fallback_used")),
            "macro_fallback_policy": record["macro_fallback_policy"],
            "macro_fallback_sufficiency_status": record["macro_fallback_sufficiency_status"],
            "classification_dispatch_allowed_from_macro_fallback": _bool_int(
                record.get("classification_dispatch_allowed_from_macro_fallback")
            ),
            "reason_codes": _json(record.get("reason_codes", [])),
            "planner_version": record.get("planner_version"),
        }
        _upsert(conn, "retrieval_fallback_state_records", row, ["fallback_state_id"])
        written.append(record["fallback_state_id"])
    return written


def write_retrieval_expansion_attempts(conn: sqlite3.Connection, attempts: Any) -> list[str]:
    """Persist RET-006 targeted retrieval expansion attempts."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(attempts)
    rows = _records_for_key(attempts, "retrieval_expansion_attempts", artifact_type="retrieval_expansion_attempt")
    written: list[str] = []
    for record in rows:
        _validate_simple_artifact(
            record,
            artifact_type="retrieval_expansion_attempt",
            schema_version=RETRIEVAL_EXPANSION_ATTEMPT_SCHEMA_VERSION,
            id_field="attempt_id",
            path="retrieval_expansion_attempt",
        )
        _retrieval_reject(record, "retrieval_expansion_attempt")
        row = {
            "attempt_id": record["attempt_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "attempt_index": int(record["attempt_index"]),
            "max_attempts": int(record["max_attempts"]),
            "expansion_strategy": record["expansion_strategy"],
            "attempt_status": record["attempt_status"],
            "unsatisfied_requirement_codes": _json(record.get("unsatisfied_requirement_codes", [])),
            "query_variant_refs": _json(record.get("query_variant_refs", [])),
            "expansion_query_text_sha256": record["expansion_query_text_sha256"],
            "candidate_refs": _json(record.get("candidate_refs", [])),
            "admitted_evidence_refs": _json(record.get("admitted_evidence_refs", [])),
            "bounded_by_requirement_max": _bool_int(record.get("bounded_by_requirement_max")),
            "macro_fallback_phase": _bool_int(record.get("macro_fallback_phase")),
            "planner_version": record.get("planner_version"),
        }
        _upsert(conn, "retrieval_expansion_attempt_slices", row, ["attempt_id"])
        written.append(record["attempt_id"])
    return written


def write_research_sufficiency_certificate(conn: sqlite3.Connection, certificates: Any) -> list[str]:
    """Persist compact RET-008 research sufficiency certificates."""

    ensure_retrieval_persistence_schema(conn)
    context = _packet_context(certificates)
    rows = _records_for_key(
        certificates,
        "leaf_research_sufficiency_certificates",
        artifact_type="research_sufficiency_certificate",
    )
    written: list[str] = []
    for record in rows:
        _validate_retrieval_record(record, validate_research_sufficiency_certificate, "research_sufficiency_certificate")
        _retrieval_reject(record, "research_sufficiency_certificate", allow_sufficiency_authority=True)
        row = {
            "certificate_id": record["certificate_id"],
            "schema_version": record["schema_version"],
            "case_id": _context_str(record, context, "case_id"),
            "dispatch_id": _context_str(record, context, "dispatch_id"),
            "retrieval_packet_id": _context_optional(record, context, "retrieval_packet_id"),
            "leaf_id": record["leaf_id"],
            "query_context_ref": record.get("query_context_ref"),
            "requirement_ref": record.get("requirement_ref"),
            "sufficiency_profile_id": record["sufficiency_profile_id"],
            "status": record["status"],
            "classification_dispatch_allowed": _bool_int(record.get("classification_dispatch_allowed")),
            "evidence_refs": _json(record.get("evidence_refs", [])),
            "breadth_coverage_ref": record.get("breadth_coverage_ref"),
            "breadth_certified": _bool_int(record.get("breadth_certified")),
            "expansion_attempt_refs": _json(record.get("expansion_attempt_refs", [])),
            "fallback_state_ref": record.get("fallback_state_ref"),
            "structural_unanswerability_proof_ref": record.get("structural_unanswerability_proof_ref"),
            "temporal_validation_status": record["temporal_validation_status"],
            "freshness_status": record["freshness_status"],
            "macro_fallback_sufficiency_status": record["macro_fallback_sufficiency_status"],
            "unsatisfied_requirement_codes": _json(record.get("unsatisfied_requirement_codes", [])),
            "blocking_reason_codes": _json(record.get("blocking_reason_codes", [])),
            "certifier_version": record.get("certifier_version"),
        }
        _upsert(conn, "research_sufficiency_certificates", row, ["certificate_id"])
        written.append(record["certificate_id"])
    return written


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


def write_leaf_research_barrier(
    conn: sqlite3.Connection,
    barrier: dict[str, Any],
    *,
    assignments: list[dict[str, Any]] | None = None,
) -> str:
    """Persist the compact leaf-research-barrier/v1 handoff artifact."""

    ensure_researcher_verification_persistence_schema(conn)
    validation = validate_leaf_research_barrier(barrier, assignments=assignments)
    if not validation.valid:
        raise ResearcherPersistenceError("leaf research barrier invalid: " + "; ".join(validation.errors))
    _reject_forbidden_persistence_payload(barrier, "leaf_research_barrier")
    case_id = None
    dispatch_id = None
    if assignments:
        first = assignments[0]
        case_id = first.get("case_id")
        dispatch_id = first.get("dispatch_id")
    row = {
        "barrier_id": barrier["barrier_id"],
        "schema_version": barrier["schema_version"],
        "case_id": case_id,
        "dispatch_id": dispatch_id,
        "assignment_refs": _json(barrier.get("assignment_refs", [])),
        "leaf_count": len(barrier.get("terminal_state_by_leaf", [])),
        "terminal_state_by_leaf": _json(barrier.get("terminal_state_by_leaf", [])),
        "all_leaves_terminal": _bool_int(barrier.get("all_leaves_terminal")),
        "proceed_to_verification_scae": _bool_int(barrier.get("proceed_to_verification_scae")),
        "blocker_reason_codes": _json(barrier.get("blocker_reason_codes", [])),
        "result_validation_errors": _json(barrier.get("result_validation_errors", [])),
        "true_production_mode": _bool_int(barrier.get("true_production_mode")),
        "barrier_policy": _json(barrier.get("barrier_policy", {})),
        "barrier_digest": barrier["barrier_digest"],
    }
    _upsert(conn, "leaf_research_barriers", row, ["barrier_id"])
    return barrier["barrier_id"]


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
    "MIG_004_RETRIEVAL_PERSISTENCE_MIGRATION",
    "MIG_006_RESEARCHER_VERIFICATION_MIGRATION",
    "RETRIEVAL_PERSISTENCE_VERSION",
    "RESEARCHER_PERSISTENCE_VERSION",
    "ResearcherPersistenceError",
    "ensure_retrieval_persistence_schema",
    "ensure_researcher_verification_persistence_schema",
    "write_atomic_claim_candidate_slices",
    "write_browser_retrieval_attempts",
    "write_browser_search_provider_diagnostics",
    "write_classification_provenance_slices",
    "write_claim_family_resolution_slices",
    "write_contradiction_search_attempts",
    "write_direction_verification_slices",
    "write_evidence_provenance_slices",
    "write_evidence_quality_verification_slices",
    "write_leaf_research_assignments",
    "write_leaf_research_barrier",
    "write_metadata_fill_diagnostics",
    "write_native_research_attempts",
    "write_negative_check_attempts",
    "write_normalized_supplemental_evidence",
    "write_research_sufficiency_certificate",
    "write_research_sufficiency_reconciliation",
    "write_researcher_classification_slices",
    "write_researcher_classifications",
    "write_researcher_context_isolation_audits",
    "write_researcher_coverage_proofs",
    "write_researcher_escalation_decisions",
    "write_researcher_prompt_artifact",
    "write_retrieval_breadth_coverage_slices",
    "write_retrieval_breadth_profile",
    "write_retrieval_evidence_chunk_slices",
    "write_retrieval_evidence_items",
    "write_retrieval_expansion_attempts",
    "write_retrieval_fallback_state",
    "write_retrieval_packet",
    "write_retrieval_quality_slices",
    "write_scae_readiness_reconciliation",
    "write_source_access_and_missingness_slices",
    "write_source_metadata_classifier_slices",
    "write_source_metadata_resolution_slices",
    "write_verification_slices",
]
