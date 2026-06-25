"""REPLAY-001 non-authoritative first-100 replay manifest contract."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .training_trace import (
    MATERIALIZATION_STATUS_NOT_MATERIALIZED,
    NO_LIVE_AUTHORITY,
    TRACE_STATUS_MINIMAL_POINTER_WRITTEN,
    TRAINING_TRACE_MINIMAL_SCHEMA_VERSION,
    canonical_json,
    validate_minimal_training_trace,
)


REPLAY_MANIFEST_TABLE = "v2_replay_manifests"
REPLAY_RESULT_TABLE = "v2_replay_result_records"
REPLAY_MANIFEST_SCHEMA_VERSION = "v2-replay-manifest/v1"
REPLAY_RESULT_SCHEMA_VERSION = "v2-replay-result-record/v1"
FIRST100_REPLAY_SCOPE = "first_100_direct_cutover"
FIRST100_COHORT_LIMIT = 100
REPLAY_STATUS_QUEUED = "queued"
REPLAY_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "009_replay_records.sql"

REPLAY_RESULT_STATUSES = (
    "replay_completed",
    "replay_failed",
    "replay_blocked",
    "outcome_pending",
    "scoring_ref_pending",
    "scoring_ref_available",
)

REPLAY_ALLOWED_USES = (
    "offline_replay",
    "result_record_join",
    "session6_maturity_input_pointer",
)
REPLAY_FORBIDDEN_USES = (
    "production_forecast_write",
    "probability_replacement",
    "calibration_policy_promotion",
    "base_policy_rewrite",
    "inline_full_trace_materialization",
)
REPLAY_RESULT_ALLOWED_USES = (
    "offline_replay_audit",
    "outcome_ref_join",
    "scorecard_ref_join",
    "session6_maturity_input_pointer",
)
REPLAY_RESULT_FORBIDDEN_USES = REPLAY_FORBIDDEN_USES + (
    "outcome_scoring_computation",
    "brier_clearance",
)

FORBIDDEN_REPLAY_AUTHORITY_FIELDS = frozenset(
    {
        "probability",
        "probability_estimate",
        "forecast_probability",
        "forecast_prob",
        "production_forecast_prob",
        "canonical_probability",
        "raw_ledger_probability",
        "post_ledger_probability",
        "debt_adjusted_probability",
        "replacement_probability",
        "probability_override",
        "fair_value",
        "interval",
        "confidence_interval",
        "decision_recommendation",
        "recommended_decision",
        "active_policy_pointer",
        "calibration_policy_pointer",
        "policy_promotion",
        "promote_policy_pointer",
        "base_policy_rewrite",
    }
)
FORBIDDEN_REPLAY_SCORING_FIELDS = frozenset(
    {
        "outcome",
        "resolved_outcome",
        "resolution_payload",
        "prediction_brier",
        "market_brier",
        "brier_edge",
        "brier_score",
        "log_loss",
        "reliability_bucket",
        "calibration_debt_cleared",
        "debt_clearance_status",
    }
)
FORBIDDEN_REPLAY_METADATA_KEYS = (
    FORBIDDEN_REPLAY_AUTHORITY_FIELDS
    | FORBIDDEN_REPLAY_SCORING_FIELDS
    | {
        "raw_payload",
        "payload",
        "raw_content",
        "content",
        "body",
        "html",
        "page_text",
        "stdout",
        "stderr",
        "traceback",
        "browser_log",
    }
)
MAX_SAFE_METADATA_BYTES = 8192
MAX_SAFE_METADATA_STRING_BYTES = 4096
MAX_SAFE_MESSAGE_BYTES = 1024

REPLAY_MANIFEST_COMPAT_COLUMNS = {
    "replay_manifest_id": "TEXT",
    "schema_version": "TEXT",
    "replay_cohort_id": "TEXT",
    "cohort_sequence": "INTEGER",
    "cohort_limit": "INTEGER",
    "replay_scope": "TEXT",
    "trace_id": "TEXT",
    "case_id": "TEXT",
    "case_key": "TEXT",
    "dispatch_id": "TEXT",
    "run_id": "TEXT",
    "forecast_timestamp": "TEXT",
    "trace_artifact_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
    "trace_artifact_hashes": "TEXT NOT NULL DEFAULT '{}'",
    "replay_status": "TEXT",
    "replay_command": "TEXT",
    "live_authority": "TEXT",
    "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
    "production_write_authority": "INTEGER NOT NULL DEFAULT 0",
    "calibration_policy_promotion_authority": "INTEGER NOT NULL DEFAULT 0",
    "full_trace_materialization_authority": "INTEGER NOT NULL DEFAULT 0",
    "allowed_uses": "TEXT NOT NULL DEFAULT '[]'",
    "forbidden_uses": "TEXT NOT NULL DEFAULT '[]'",
    "metadata": "TEXT NOT NULL DEFAULT '{}'",
    "updated_at": "TEXT",
}
REPLAY_RESULT_COMPAT_COLUMNS = {
    "replay_result_id": "TEXT",
    "schema_version": "TEXT",
    "replay_manifest_id": "TEXT",
    "replay_cohort_id": "TEXT",
    "trace_id": "TEXT",
    "replay_attempt_id": "TEXT",
    "result_status": "TEXT",
    "replay_started_at": "TEXT",
    "replay_completed_at": "TEXT",
    "replay_output_artifact_ref": "TEXT",
    "replay_output_hash": "TEXT",
    "outcome_ref": "TEXT",
    "scoring_record_ref": "TEXT",
    "scorecard_artifact_ref": "TEXT",
    "safe_message": "TEXT",
    "live_authority": "TEXT",
    "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
    "production_write_authority": "INTEGER NOT NULL DEFAULT 0",
    "probability_replacement_authority": "INTEGER NOT NULL DEFAULT 0",
    "calibration_policy_promotion_authority": "INTEGER NOT NULL DEFAULT 0",
    "allowed_uses": "TEXT NOT NULL DEFAULT '[]'",
    "forbidden_uses": "TEXT NOT NULL DEFAULT '[]'",
    "metadata": "TEXT NOT NULL DEFAULT '{}'",
    "updated_at": "TEXT",
}


class ReplayContractError(ValueError):
    """Raised when a REPLAY-001 manifest or result record is unsafe."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise ReplayContractError(f"{field} is required")
    return value


def require_optional_string(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ReplayContractError(f"{field} must be a non-empty string when present")
    return value


def require_list(field: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ReplayContractError(f"{field} must be a list of non-empty strings")
    return list(value)


def require_mapping(field: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ReplayContractError(f"{field} must be an object")
    return dict(value)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_no_forbidden_replay_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ReplayContractError(f"{path} contains an invalid key")
            lowered = key.lower()
            if lowered in FORBIDDEN_REPLAY_AUTHORITY_FIELDS:
                raise ReplayContractError(f"{path}.{key} may not author or replace forecast probability")
            if lowered in FORBIDDEN_REPLAY_SCORING_FIELDS:
                raise ReplayContractError(f"{path}.{key} may not store outcome scoring or Brier clearance")
            ensure_no_forbidden_replay_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_forbidden_replay_fields(child, f"{path}[{idx}]")


def ensure_safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = require_mapping("metadata", metadata)

    def check(value: Any, path: str = "metadata") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise ReplayContractError(f"{path} contains an invalid key")
                if key.lower() in FORBIDDEN_REPLAY_METADATA_KEYS:
                    raise ReplayContractError(f"{path}.{key} is forbidden in REPLAY-001 metadata")
                check(child, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                check(child, f"{path}[{idx}]")
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_SAFE_METADATA_STRING_BYTES:
                raise ReplayContractError(f"{path} string is too large")
        elif value is None or isinstance(value, (bool, int, float)):
            return
        else:
            raise ReplayContractError(f"{path} contains unsupported metadata type {type(value).__name__}")

    check(metadata)
    if len(canonical_json(metadata).encode("utf-8")) > MAX_SAFE_METADATA_BYTES:
        raise ReplayContractError("metadata is too large")
    return metadata


def ensure_sha256(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    require_non_empty(field, value)
    if not value.startswith("sha256:"):
        raise ReplayContractError(f"{field} must start with sha256:")
    return value


def normalize_trace_pointer(trace_pointer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trace_pointer, dict):
        raise ReplayContractError("trace_pointer must be an object")
    if trace_pointer.get("schema_version") == TRAINING_TRACE_MINIMAL_SCHEMA_VERSION:
        try:
            validate_minimal_training_trace(trace_pointer)
        except ValueError as exc:
            raise ReplayContractError(str(exc)) from exc

    ensure_no_forbidden_replay_fields(trace_pointer, "trace_pointer")
    trace_id = require_non_empty("trace_pointer.trace_id", trace_pointer.get("trace_id"))
    case_id = require_non_empty("trace_pointer.case_id", trace_pointer.get("case_id"))
    dispatch_id = require_non_empty("trace_pointer.dispatch_id", trace_pointer.get("dispatch_id"))
    run_id = require_non_empty("trace_pointer.run_id", trace_pointer.get("run_id"))
    forecast_timestamp = require_non_empty(
        "trace_pointer.forecast_timestamp",
        trace_pointer.get("forecast_timestamp"),
    )
    case_key = trace_pointer.get("case_key")
    if case_key is not None and not isinstance(case_key, str):
        raise ReplayContractError("trace_pointer.case_key must be a string when present")

    artifact_manifest_ids = require_list("trace_pointer.artifact_manifest_ids", trace_pointer.get("artifact_manifest_ids"))
    if not artifact_manifest_ids:
        raise ReplayContractError("trace_pointer.artifact_manifest_ids are required")
    artifact_hashes = require_mapping("trace_pointer.artifact_hashes", trace_pointer.get("artifact_hashes"))
    if set(artifact_hashes) != set(artifact_manifest_ids):
        raise ReplayContractError("trace_pointer artifact hashes must match artifact manifest IDs")
    for artifact_id, artifact_hash in artifact_hashes.items():
        require_non_empty("trace_pointer artifact hash key", artifact_id)
        ensure_sha256(f"trace_pointer.artifact_hashes[{artifact_id}]", artifact_hash)

    if trace_pointer.get("trace_status") != TRACE_STATUS_MINIMAL_POINTER_WRITTEN:
        raise ReplayContractError("trace_pointer must be a written minimal pointer")
    if trace_pointer.get("live_authority") != NO_LIVE_AUTHORITY:
        raise ReplayContractError("trace_pointer must have no live authority")
    if trace_pointer.get("live_forecast_authority") not in (False, 0):
        raise ReplayContractError("trace_pointer cannot have live forecast authority")
    if trace_pointer.get("materialization_status") != MATERIALIZATION_STATUS_NOT_MATERIALIZED:
        raise ReplayContractError("trace_pointer must not be a full trace materialization")

    return {
        "trace_id": trace_id,
        "case_id": case_id,
        "case_key": case_key,
        "dispatch_id": dispatch_id,
        "run_id": run_id,
        "forecast_timestamp": forecast_timestamp,
        "artifact_manifest_ids": artifact_manifest_ids,
        "artifact_hashes": artifact_hashes,
    }


def make_replay_manifest_id(replay_cohort_id: str, trace_id: str, cohort_sequence: int) -> str:
    seed = canonical_json(
        {
            "replay_cohort_id": replay_cohort_id,
            "trace_id": trace_id,
            "cohort_sequence": cohort_sequence,
            "scope": FIRST100_REPLAY_SCOPE,
        }
    )
    return "replay-manifest:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_first100_replay_manifest(
    *,
    trace_pointer: dict[str, Any],
    replay_cohort_id: str,
    cohort_sequence: int,
    replay_manifest_id: str | None = None,
    replay_command: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    replay_cohort_id = require_non_empty("replay_cohort_id", replay_cohort_id)
    if not isinstance(cohort_sequence, int) or cohort_sequence < 1 or cohort_sequence > FIRST100_COHORT_LIMIT:
        raise ReplayContractError("cohort_sequence must be between 1 and 100")
    replay_command = require_optional_string("replay_command", replay_command)
    trace = normalize_trace_pointer(trace_pointer)
    record = {
        "schema_version": REPLAY_MANIFEST_SCHEMA_VERSION,
        "table": REPLAY_MANIFEST_TABLE,
        "replay_manifest_id": replay_manifest_id
        or make_replay_manifest_id(replay_cohort_id, trace["trace_id"], cohort_sequence),
        "replay_cohort_id": replay_cohort_id,
        "cohort_sequence": cohort_sequence,
        "cohort_limit": FIRST100_COHORT_LIMIT,
        "replay_scope": FIRST100_REPLAY_SCOPE,
        "trace_id": trace["trace_id"],
        "case_id": trace["case_id"],
        "case_key": trace["case_key"],
        "dispatch_id": trace["dispatch_id"],
        "run_id": trace["run_id"],
        "forecast_timestamp": trace["forecast_timestamp"],
        "trace_artifact_manifest_ids": trace["artifact_manifest_ids"],
        "trace_artifact_hashes": trace["artifact_hashes"],
        "replay_status": REPLAY_STATUS_QUEUED,
        "replay_command": replay_command,
        "live_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "production_write_authority": False,
        "calibration_policy_promotion_authority": False,
        "full_trace_materialization_authority": False,
        "allowed_uses": list(REPLAY_ALLOWED_USES),
        "forbidden_uses": list(REPLAY_FORBIDDEN_USES),
        "metadata": ensure_safe_metadata(metadata),
        "created_at": created_at or utc_now_iso(),
    }
    validate_replay_manifest(record)
    return record


def build_first100_replay_manifests(
    *,
    trace_pointers: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    replay_cohort_id: str,
    replay_command: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(trace_pointers, (list, tuple)) or not trace_pointers:
        raise ReplayContractError("trace_pointers must contain at least one minimal trace pointer")
    if len(trace_pointers) > FIRST100_COHORT_LIMIT:
        raise ReplayContractError("first-100 replay manifests cannot contain more than 100 trace pointers")
    return [
        build_first100_replay_manifest(
            trace_pointer=trace_pointer,
            replay_cohort_id=replay_cohort_id,
            cohort_sequence=idx,
            replay_command=replay_command,
            created_at=created_at,
            metadata=metadata,
        )
        for idx, trace_pointer in enumerate(trace_pointers, start=1)
    ]


def validate_replay_manifest(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise ReplayContractError("replay manifest must be an object")
    ensure_no_forbidden_replay_fields(record)
    required = {
        "schema_version",
        "table",
        "replay_manifest_id",
        "replay_cohort_id",
        "cohort_sequence",
        "cohort_limit",
        "replay_scope",
        "trace_id",
        "case_id",
        "dispatch_id",
        "run_id",
        "forecast_timestamp",
        "trace_artifact_manifest_ids",
        "trace_artifact_hashes",
        "replay_status",
        "live_authority",
        "live_forecast_authority",
        "production_write_authority",
        "calibration_policy_promotion_authority",
        "full_trace_materialization_authority",
        "allowed_uses",
        "forbidden_uses",
        "metadata",
        "created_at",
    }
    allowed = required | {"case_key", "replay_command"}
    for field in record:
        if field not in allowed:
            raise ReplayContractError(f"unexpected replay manifest field: {field}")
    for field in required:
        if field not in record:
            raise ReplayContractError(f"{field} is required")
    if record["schema_version"] != REPLAY_MANIFEST_SCHEMA_VERSION:
        raise ReplayContractError(f"schema_version must be {REPLAY_MANIFEST_SCHEMA_VERSION}")
    if record["table"] != REPLAY_MANIFEST_TABLE:
        raise ReplayContractError(f"table must be {REPLAY_MANIFEST_TABLE}")
    for field in (
        "replay_manifest_id",
        "replay_cohort_id",
        "replay_scope",
        "trace_id",
        "case_id",
        "dispatch_id",
        "run_id",
        "forecast_timestamp",
        "replay_status",
        "live_authority",
        "created_at",
    ):
        require_non_empty(field, record[field])
    if record.get("case_key") is not None and not isinstance(record["case_key"], str):
        raise ReplayContractError("case_key must be a string when present")
    if record.get("replay_command") is not None:
        require_optional_string("replay_command", record["replay_command"])
    if record["cohort_limit"] != FIRST100_COHORT_LIMIT:
        raise ReplayContractError("cohort_limit must be 100 for REPLAY-001")
    if not isinstance(record["cohort_sequence"], int) or record["cohort_sequence"] < 1 or record["cohort_sequence"] > FIRST100_COHORT_LIMIT:
        raise ReplayContractError("cohort_sequence must be between 1 and 100")
    if record["replay_scope"] != FIRST100_REPLAY_SCOPE:
        raise ReplayContractError(f"replay_scope must be {FIRST100_REPLAY_SCOPE}")
    if record["replay_status"] != REPLAY_STATUS_QUEUED:
        raise ReplayContractError(f"replay_status must be {REPLAY_STATUS_QUEUED}")
    artifact_ids = require_list("trace_artifact_manifest_ids", record["trace_artifact_manifest_ids"])
    artifact_hashes = require_mapping("trace_artifact_hashes", record["trace_artifact_hashes"])
    if set(artifact_hashes) != set(artifact_ids):
        raise ReplayContractError("trace artifact hashes must match trace artifact manifest IDs")
    for artifact_id, artifact_hash in artifact_hashes.items():
        require_non_empty("trace artifact hash key", artifact_id)
        ensure_sha256(f"trace_artifact_hashes[{artifact_id}]", artifact_hash)
    if record["live_authority"] != NO_LIVE_AUTHORITY:
        raise ReplayContractError("replay manifest has no live authority")
    for field in (
        "live_forecast_authority",
        "production_write_authority",
        "calibration_policy_promotion_authority",
        "full_trace_materialization_authority",
    ):
        if record[field] not in (False, 0):
            raise ReplayContractError(f"{field} must be false")
    allowed_uses = require_list("allowed_uses", record["allowed_uses"])
    forbidden_uses = require_list("forbidden_uses", record["forbidden_uses"])
    if set(allowed_uses) != set(REPLAY_ALLOWED_USES):
        raise ReplayContractError("allowed_uses must match the REPLAY-001 manifest contract")
    if set(forbidden_uses) != set(REPLAY_FORBIDDEN_USES):
        raise ReplayContractError("forbidden_uses must match the REPLAY-001 manifest contract")
    ensure_safe_metadata(record["metadata"])


def make_replay_result_id(replay_manifest_id: str, replay_attempt_id: str) -> str:
    seed = canonical_json(
        {
            "replay_manifest_id": replay_manifest_id,
            "replay_attempt_id": replay_attempt_id,
            "schema_version": REPLAY_RESULT_SCHEMA_VERSION,
        }
    )
    return "replay-result:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_replay_result_record(
    *,
    replay_manifest: dict[str, Any],
    replay_attempt_id: str,
    result_status: str,
    replay_result_id: str | None = None,
    replay_started_at: str | None = None,
    replay_completed_at: str | None = None,
    replay_output_artifact_ref: str | None = None,
    replay_output_hash: str | None = None,
    outcome_ref: str | None = None,
    scoring_record_ref: str | None = None,
    scorecard_artifact_ref: str | None = None,
    safe_message: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_replay_manifest(replay_manifest)
    replay_attempt_id = require_non_empty("replay_attempt_id", replay_attempt_id)
    if result_status not in REPLAY_RESULT_STATUSES:
        raise ReplayContractError(f"unknown replay result status: {result_status}")
    if safe_message is not None:
        require_optional_string("safe_message", safe_message)
        if len(safe_message.encode("utf-8")) > MAX_SAFE_MESSAGE_BYTES:
            raise ReplayContractError("safe_message is too large")
    if result_status == "scoring_ref_available" and not (scoring_record_ref or scorecard_artifact_ref):
        raise ReplayContractError("scoring_ref_available requires a scoring or scorecard ref")
    record = {
        "schema_version": REPLAY_RESULT_SCHEMA_VERSION,
        "table": REPLAY_RESULT_TABLE,
        "replay_result_id": replay_result_id
        or make_replay_result_id(replay_manifest["replay_manifest_id"], replay_attempt_id),
        "replay_manifest_id": replay_manifest["replay_manifest_id"],
        "replay_cohort_id": replay_manifest["replay_cohort_id"],
        "trace_id": replay_manifest["trace_id"],
        "replay_attempt_id": replay_attempt_id,
        "result_status": result_status,
        "replay_started_at": require_optional_string("replay_started_at", replay_started_at),
        "replay_completed_at": require_optional_string("replay_completed_at", replay_completed_at),
        "replay_output_artifact_ref": require_optional_string(
            "replay_output_artifact_ref",
            replay_output_artifact_ref,
        ),
        "replay_output_hash": ensure_sha256("replay_output_hash", replay_output_hash),
        "outcome_ref": require_optional_string("outcome_ref", outcome_ref),
        "scoring_record_ref": require_optional_string("scoring_record_ref", scoring_record_ref),
        "scorecard_artifact_ref": require_optional_string("scorecard_artifact_ref", scorecard_artifact_ref),
        "safe_message": safe_message,
        "live_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "production_write_authority": False,
        "probability_replacement_authority": False,
        "calibration_policy_promotion_authority": False,
        "allowed_uses": list(REPLAY_RESULT_ALLOWED_USES),
        "forbidden_uses": list(REPLAY_RESULT_FORBIDDEN_USES),
        "metadata": ensure_safe_metadata(metadata),
        "created_at": created_at or utc_now_iso(),
    }
    validate_replay_result_record(record)
    return record


def validate_replay_result_record(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise ReplayContractError("replay result record must be an object")
    ensure_no_forbidden_replay_fields(record)
    required = {
        "schema_version",
        "table",
        "replay_result_id",
        "replay_manifest_id",
        "replay_cohort_id",
        "trace_id",
        "replay_attempt_id",
        "result_status",
        "live_authority",
        "live_forecast_authority",
        "production_write_authority",
        "probability_replacement_authority",
        "calibration_policy_promotion_authority",
        "allowed_uses",
        "forbidden_uses",
        "metadata",
        "created_at",
    }
    allowed = required | {
        "replay_started_at",
        "replay_completed_at",
        "replay_output_artifact_ref",
        "replay_output_hash",
        "outcome_ref",
        "scoring_record_ref",
        "scorecard_artifact_ref",
        "safe_message",
    }
    for field in record:
        if field not in allowed:
            raise ReplayContractError(f"unexpected replay result field: {field}")
    for field in required:
        if field not in record:
            raise ReplayContractError(f"{field} is required")
    if record["schema_version"] != REPLAY_RESULT_SCHEMA_VERSION:
        raise ReplayContractError(f"schema_version must be {REPLAY_RESULT_SCHEMA_VERSION}")
    if record["table"] != REPLAY_RESULT_TABLE:
        raise ReplayContractError(f"table must be {REPLAY_RESULT_TABLE}")
    for field in (
        "replay_result_id",
        "replay_manifest_id",
        "replay_cohort_id",
        "trace_id",
        "replay_attempt_id",
        "result_status",
        "live_authority",
        "created_at",
    ):
        require_non_empty(field, record[field])
    if record["result_status"] not in REPLAY_RESULT_STATUSES:
        raise ReplayContractError(f"unknown replay result status: {record['result_status']}")
    for field in (
        "replay_started_at",
        "replay_completed_at",
        "replay_output_artifact_ref",
        "outcome_ref",
        "scoring_record_ref",
        "scorecard_artifact_ref",
        "safe_message",
    ):
        require_optional_string(field, record.get(field))
    ensure_sha256("replay_output_hash", record.get("replay_output_hash"))
    if record.get("safe_message") is not None and len(record["safe_message"].encode("utf-8")) > MAX_SAFE_MESSAGE_BYTES:
        raise ReplayContractError("safe_message is too large")
    if record["result_status"] == "scoring_ref_available" and not (
        record.get("scoring_record_ref") or record.get("scorecard_artifact_ref")
    ):
        raise ReplayContractError("scoring_ref_available requires a scoring or scorecard ref")
    if record["live_authority"] != NO_LIVE_AUTHORITY:
        raise ReplayContractError("replay result has no live authority")
    for field in (
        "live_forecast_authority",
        "production_write_authority",
        "probability_replacement_authority",
        "calibration_policy_promotion_authority",
    ):
        if record[field] not in (False, 0):
            raise ReplayContractError(f"{field} must be false")
    allowed_uses = require_list("allowed_uses", record["allowed_uses"])
    forbidden_uses = require_list("forbidden_uses", record["forbidden_uses"])
    if set(allowed_uses) != set(REPLAY_RESULT_ALLOWED_USES):
        raise ReplayContractError("allowed_uses must match the REPLAY-001 result contract")
    if set(forbidden_uses) != set(REPLAY_RESULT_FORBIDDEN_USES):
        raise ReplayContractError("forbidden_uses must match the REPLAY-001 result contract")
    ensure_safe_metadata(record["metadata"])


def ensure_replay_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(REPLAY_MIGRATION.read_text(encoding="utf-8"))
    for table, columns in (
        (REPLAY_MANIFEST_TABLE, REPLAY_MANIFEST_COMPAT_COLUMNS),
        (REPLAY_RESULT_TABLE, REPLAY_RESULT_COMPAT_COLUMNS),
    ):
        existing = table_columns(conn, table)
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.executescript(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_replay_manifests_replay_manifest_id
          ON {REPLAY_MANIFEST_TABLE}(replay_manifest_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_replay_results_replay_result_id
          ON {REPLAY_RESULT_TABLE}(replay_result_id);
        """
    )


def write_replay_manifest(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_replay_manifest(record)
    ensure_replay_schema(conn)
    values = {
        "replay_manifest_id": record["replay_manifest_id"],
        "schema_version": record["schema_version"],
        "replay_cohort_id": record["replay_cohort_id"],
        "cohort_sequence": record["cohort_sequence"],
        "cohort_limit": record["cohort_limit"],
        "replay_scope": record["replay_scope"],
        "trace_id": record["trace_id"],
        "case_id": record["case_id"],
        "case_key": record.get("case_key"),
        "dispatch_id": record["dispatch_id"],
        "run_id": record["run_id"],
        "forecast_timestamp": record["forecast_timestamp"],
        "trace_artifact_manifest_ids": canonical_json(record["trace_artifact_manifest_ids"]),
        "trace_artifact_hashes": canonical_json(record["trace_artifact_hashes"]),
        "replay_status": record["replay_status"],
        "replay_command": record.get("replay_command"),
        "live_authority": record["live_authority"],
        "live_forecast_authority": 1 if record["live_forecast_authority"] else 0,
        "production_write_authority": 1 if record["production_write_authority"] else 0,
        "calibration_policy_promotion_authority": 1 if record["calibration_policy_promotion_authority"] else 0,
        "full_trace_materialization_authority": 1 if record["full_trace_materialization_authority"] else 0,
        "allowed_uses": canonical_json(record["allowed_uses"]),
        "forbidden_uses": canonical_json(record["forbidden_uses"]),
        "metadata": canonical_json(record["metadata"]),
        "created_at": record["created_at"],
    }
    insert_columns = [column for column in values if column in table_columns(conn, REPLAY_MANIFEST_TABLE)]
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [column for column in insert_columns if column not in {"replay_manifest_id", "created_at"}]
    if "updated_at" in table_columns(conn, REPLAY_MANIFEST_TABLE):
        update_columns.append("updated_at")
    update_clause = ",\n          ".join(
        "updated_at=CURRENT_TIMESTAMP" if column == "updated_at" else f"{column}=excluded.{column}"
        for column in update_columns
    )
    conn.execute(
        f"""
        INSERT INTO {REPLAY_MANIFEST_TABLE} ({", ".join(insert_columns)})
        VALUES ({placeholders})
        ON CONFLICT(replay_manifest_id) DO UPDATE SET
          {update_clause}
        """,
        tuple(values[column] for column in insert_columns),
    )
    return record["replay_manifest_id"]


def write_replay_result_record(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_replay_result_record(record)
    ensure_replay_schema(conn)
    values = {
        "replay_result_id": record["replay_result_id"],
        "schema_version": record["schema_version"],
        "replay_manifest_id": record["replay_manifest_id"],
        "replay_cohort_id": record["replay_cohort_id"],
        "trace_id": record["trace_id"],
        "replay_attempt_id": record["replay_attempt_id"],
        "result_status": record["result_status"],
        "replay_started_at": record.get("replay_started_at"),
        "replay_completed_at": record.get("replay_completed_at"),
        "replay_output_artifact_ref": record.get("replay_output_artifact_ref"),
        "replay_output_hash": record.get("replay_output_hash"),
        "outcome_ref": record.get("outcome_ref"),
        "scoring_record_ref": record.get("scoring_record_ref"),
        "scorecard_artifact_ref": record.get("scorecard_artifact_ref"),
        "safe_message": record.get("safe_message"),
        "live_authority": record["live_authority"],
        "live_forecast_authority": 1 if record["live_forecast_authority"] else 0,
        "production_write_authority": 1 if record["production_write_authority"] else 0,
        "probability_replacement_authority": 1 if record["probability_replacement_authority"] else 0,
        "calibration_policy_promotion_authority": 1 if record["calibration_policy_promotion_authority"] else 0,
        "allowed_uses": canonical_json(record["allowed_uses"]),
        "forbidden_uses": canonical_json(record["forbidden_uses"]),
        "metadata": canonical_json(record["metadata"]),
        "created_at": record["created_at"],
    }
    insert_columns = [column for column in values if column in table_columns(conn, REPLAY_RESULT_TABLE)]
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [column for column in insert_columns if column not in {"replay_result_id", "created_at"}]
    if "updated_at" in table_columns(conn, REPLAY_RESULT_TABLE):
        update_columns.append("updated_at")
    update_clause = ",\n          ".join(
        "updated_at=CURRENT_TIMESTAMP" if column == "updated_at" else f"{column}=excluded.{column}"
        for column in update_columns
    )
    conn.execute(
        f"""
        INSERT INTO {REPLAY_RESULT_TABLE} ({", ".join(insert_columns)})
        VALUES ({placeholders})
        ON CONFLICT(replay_result_id) DO UPDATE SET
          {update_clause}
        """,
        tuple(values[column] for column in insert_columns),
    )
    return record["replay_result_id"]
