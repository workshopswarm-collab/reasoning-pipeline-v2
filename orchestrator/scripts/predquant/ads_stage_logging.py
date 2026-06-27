"""ADS v2 stage vocabulary, stage-event, and error-event contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE_STATUS_TABLE = "v2_stage_status_snapshots"
STAGE_EXECUTION_EVENT_TABLE = "v2_stage_execution_events"
PIPELINE_ERROR_EVENT_TABLE = "v2_pipeline_error_events"
FAILURE_PATTERN_GROUP_TABLE = "v2_failure_pattern_groups"
STAGE_STATUS_SCHEMA_VERSION = "v2-stage-status-snapshot/v1"
STAGE_EXECUTION_EVENT_SCHEMA_VERSION = "v2-stage-execution-event/v1"
PIPELINE_ERROR_EVENT_SCHEMA_VERSION = "v2-pipeline-error-event/v1"
STAGE_LOGGING_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "002_v2_stage_status_model.sql"
)

STAGES = (
    "case_selection",
    "evidence_packet",
    "policy_context",
    "related_market_context",
    "related_market_refresh",
    "decomposition",
    "retrieval",
    "researcher_classification",
    "classification_verification",
    "scae",
    "synthesis",
    "decision",
    "training_trace",
    "replay_record",
    "terminal",
)

STAGE_STATUSES = (
    "not_started",
    "running",
    "blocked",
    "failed",
    "complete",
    "waived",
    "terminal",
)

ALLOWED_STATUS_TRANSITIONS = {
    "not_started": ("running", "waived"),
    "running": ("complete", "failed", "blocked"),
    "blocked": ("running", "failed", "waived"),
    "failed": ("running", "terminal"),
    "complete": (),
    "waived": (),
    "terminal": (),
}

STAGE_EXECUTION_EVENT_TYPES = (
    "stage_started",
    "stage_completed",
    "stage_failed",
    "stage_blocked",
    "retry_scheduled",
    "artifact_validation_failed",
)

EVENT_STATUSES = ("info", "warning", "error")
REDACTION_STATUSES = ("not_needed", "redacted", "blocked_unsafe")
AGENT_OR_COMPONENT_REFS = ("orchestrator", "decomposer", "researcher-swarm", "scae")
FAILURE_CLASSES = (
    "schema_validation_failed",
    "dependency_not_ready",
    "temporal_isolation_failed",
    "forbidden_probability_field",
    "missing_required_artifact",
    "invalid_stage_transition",
    "unowned_inventory_update",
    "amrg_anchor_required_unrepairable",
    "scae_probability_authority_violation",
    "decision_probability_override_attempt",
    "retryable_transport",
    "retryable_model_transport",
    "invalid_artifact_terminal",
    "thin_evidence_watch_only",
    "policy_violation_quarantine",
    "fatal_operational",
)
RETRYABILITIES = ("retryable", "terminal", "blocked", "waived")
UNSAFE_SECRET_EXCLUSION_STATUSES = ("passed", "blocked")
RAW_LOG_FIELDS = ("stdout", "stderr", "traceback", "browser_log", "raw_log")
MAX_SAFE_MESSAGE_BYTES = 1024
MAX_SAFE_METADATA_BYTES = 8192
MAX_SAFE_METADATA_STRING_BYTES = 4096
FORBIDDEN_SAFE_METADATA_KEYS = {
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


class StageContractError(ValueError):
    """Raised when an ADS stage/status/event record violates the v2 contract."""


@dataclass(frozen=True)
class StageContext:
    case_id: str
    case_key: str
    dispatch_id: str
    stage: str
    stage_attempt_id: str
    pipeline_run_id: str | None = None
    case_lease_id: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_sha256(command: str) -> str:
    require_non_empty("command", command)
    return "sha256:" + hashlib.sha256(command.encode("utf-8")).hexdigest()


def require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise StageContractError(f"{field} is required")
    return value


def require_list(field: str, value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise StageContractError(f"{field} must be a list of non-empty strings")
    return list(value)


def require_mapping(field: str, value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StageContractError(f"{field} must be an object")
    return dict(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = require_mapping("safe_metadata", metadata)

    def check(value: Any, path: str = "safe_metadata") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise StageContractError(f"{path} contains an invalid key")
                if key.lower() in FORBIDDEN_SAFE_METADATA_KEYS:
                    raise StageContractError(f"{path}.{key} may not store raw payload/log content")
                check(child, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                check(child, f"{path}[{idx}]")
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_SAFE_METADATA_STRING_BYTES:
                raise StageContractError(f"{path} string is too large for safe metadata")
        elif value is None or isinstance(value, (bool, int, float)):
            return
        else:
            raise StageContractError(f"{path} contains unsupported metadata type {type(value).__name__}")

    check(metadata)
    if len(canonical_json(metadata).encode("utf-8")) > MAX_SAFE_METADATA_BYTES:
        raise StageContractError("safe_metadata is too large")
    return metadata


def ensure_stage_logging_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(STAGE_LOGGING_MIGRATION.read_text(encoding="utf-8"))


def validate_stage(stage: str) -> str:
    if stage not in STAGES:
        raise StageContractError(f"unknown stage: {stage}")
    return stage


def validate_status(status: str) -> str:
    if status not in STAGE_STATUSES:
        raise StageContractError(f"unknown stage status: {status}")
    return status


def validate_transition(current_status: str, next_status: str) -> None:
    validate_status(current_status)
    validate_status(next_status)
    if next_status not in ALLOWED_STATUS_TRANSITIONS[current_status]:
        raise StageContractError(f"illegal stage transition: {current_status} -> {next_status}")


def validate_event_type(event_type: str) -> str:
    if event_type not in STAGE_EXECUTION_EVENT_TYPES:
        raise StageContractError(f"unknown stage execution event type: {event_type}")
    return event_type


def validate_event_status(event_status: str) -> str:
    if event_status not in EVENT_STATUSES:
        raise StageContractError(f"unknown stage execution event status: {event_status}")
    return event_status


def validate_redaction_status(redaction_status: str) -> str:
    if redaction_status not in REDACTION_STATUSES:
        raise StageContractError(f"unknown redaction status: {redaction_status}")
    return redaction_status


def validate_failure_class(failure_class: str) -> str:
    if failure_class not in FAILURE_CLASSES:
        raise StageContractError(f"unknown failure_class: {failure_class}")
    return failure_class


def validate_retryability(retryability: str) -> str:
    if retryability not in RETRYABILITIES:
        raise StageContractError(f"unknown retryability: {retryability}")
    return retryability


def validate_unsafe_secret_exclusion_status(status: str) -> str:
    if status not in UNSAFE_SECRET_EXCLUSION_STATUSES:
        raise StageContractError(f"unknown unsafe_secret_exclusion_status: {status}")
    return status


def validate_context(context: StageContext) -> StageContext:
    require_non_empty("case_id", context.case_id)
    require_non_empty("case_key", context.case_key)
    require_non_empty("dispatch_id", context.dispatch_id)
    validate_stage(context.stage)
    require_non_empty("stage_attempt_id", context.stage_attempt_id)
    return context


def ensure_no_raw_log_fields(record: dict[str, Any]) -> None:
    present = sorted(field for field in RAW_LOG_FIELDS if field in record and record[field] is not None)
    if present:
        raise StageContractError("raw log fields are forbidden; use bounded artifact refs: " + ", ".join(present))


def build_stage_status_snapshot(
    *,
    context: StageContext,
    status: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    duration_ms: int | None = None,
    input_artifacts: list[str] | tuple[str, ...] | None = None,
    output_artifacts: list[str] | tuple[str, ...] | None = None,
    dependency_feature_ids: list[str] | tuple[str, ...] | None = None,
    blocking_feature_ids: list[str] | tuple[str, ...] | None = None,
    reason_codes: list[str] | tuple[str, ...] | None = None,
    latest_execution_event_ids: list[str] | tuple[str, ...] | None = None,
    error_event_ids: list[str] | tuple[str, ...] | None = None,
    replay_command: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = validate_context(context)
    validate_status(status)
    require_non_empty("replay_command", replay_command)
    if duration_ms is not None and duration_ms < 0:
        raise StageContractError("duration_ms must be non-negative")
    return {
        "schema_version": STAGE_STATUS_SCHEMA_VERSION,
        "table": STAGE_STATUS_TABLE,
        "case_id": context.case_id,
        "case_key": context.case_key,
        "dispatch_id": context.dispatch_id,
        "stage": context.stage,
        "status": status,
        "stage_attempt_id": context.stage_attempt_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "input_artifacts": require_list("input_artifacts", input_artifacts),
        "output_artifacts": require_list("output_artifacts", output_artifacts),
        "dependency_feature_ids": require_list("dependency_feature_ids", dependency_feature_ids),
        "blocking_feature_ids": require_list("blocking_feature_ids", blocking_feature_ids),
        "reason_codes": require_list("reason_codes", reason_codes),
        "latest_execution_event_ids": require_list("latest_execution_event_ids", latest_execution_event_ids),
        "error_event_ids": require_list("error_event_ids", error_event_ids),
        "replay_command": replay_command,
        "metadata": require_mapping("metadata", metadata),
    }


def validate_stage_status_snapshot(record: dict[str, Any]) -> None:
    required = (
        "schema_version",
        "case_id",
        "case_key",
        "dispatch_id",
        "stage",
        "status",
        "stage_attempt_id",
        "input_artifacts",
        "output_artifacts",
        "replay_command",
    )
    for field in required:
        if field not in record:
            raise StageContractError(f"{field} is required")
    if record["schema_version"] != STAGE_STATUS_SCHEMA_VERSION:
        raise StageContractError(f"schema_version must be {STAGE_STATUS_SCHEMA_VERSION}")
    validate_stage(record["stage"])
    validate_status(record["status"])
    require_list("input_artifacts", record["input_artifacts"])
    require_list("output_artifacts", record["output_artifacts"])
    require_non_empty("replay_command", record["replay_command"])


def build_stage_execution_event(
    *,
    execution_event_id: str,
    context: StageContext,
    event_type: str,
    event_status: str,
    event_at: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    duration_ms: int | None = None,
    attempt_number: int,
    max_attempts: int,
    runner_ref: str,
    agent_or_component_ref: str,
    script_path: str,
    command_sha256_value: str,
    input_artifact_refs: list[str] | tuple[str, ...] | None = None,
    output_artifact_refs: list[str] | tuple[str, ...] | None = None,
    validation_result_refs: list[str] | tuple[str, ...] | None = None,
    error_event_id: str | None = None,
    failure_class: str | None = None,
    safe_exception_class: str | None = None,
    safe_exception_message: str | None = None,
    traceback_sha256: str | None = None,
    stdout_artifact_ref: str | None = None,
    stderr_artifact_ref: str | None = None,
    bounded_log_artifact_ref: str | None = None,
    no_log_reason: str | None = None,
    redaction_status: str,
    resource_counters: dict[str, Any] | None = None,
    retry_policy_ref: str | None = None,
    next_retry_at: str | None = None,
    replay_command: str,
    safe_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = validate_context(context)
    require_non_empty("execution_event_id", execution_event_id)
    validate_event_type(event_type)
    validate_event_status(event_status)
    validate_redaction_status(redaction_status)
    require_non_empty("replay_command", replay_command)
    require_non_empty("runner_ref", runner_ref)
    if agent_or_component_ref not in AGENT_OR_COMPONENT_REFS:
        raise StageContractError(f"unknown agent_or_component_ref: {agent_or_component_ref}")
    require_non_empty("script_path", script_path)
    require_non_empty("command_sha256", command_sha256_value)
    if not command_sha256_value.startswith("sha256:"):
        raise StageContractError("command_sha256 must start with sha256:")
    if attempt_number < 1:
        raise StageContractError("attempt_number must be at least 1")
    if max_attempts < attempt_number:
        raise StageContractError("max_attempts must be greater than or equal to attempt_number")
    if duration_ms is not None and duration_ms < 0:
        raise StageContractError("duration_ms must be non-negative")
    if not any([stdout_artifact_ref, stderr_artifact_ref, bounded_log_artifact_ref, no_log_reason]):
        raise StageContractError("stage execution event requires a bounded log artifact ref or no_log_reason")

    event = {
        "execution_event_id": execution_event_id,
        "schema_version": STAGE_EXECUTION_EVENT_SCHEMA_VERSION,
        "table": STAGE_EXECUTION_EVENT_TABLE,
        "pipeline_run_id": context.pipeline_run_id,
        "case_lease_id": context.case_lease_id,
        "case_id": context.case_id,
        "case_key": context.case_key,
        "dispatch_id": context.dispatch_id,
        "stage": context.stage,
        "stage_attempt_id": context.stage_attempt_id,
        "event_type": event_type,
        "event_status": event_status,
        "event_at": event_at or utc_now_iso(),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "attempt_number": attempt_number,
        "max_attempts": max_attempts,
        "runner_ref": runner_ref,
        "agent_or_component_ref": agent_or_component_ref,
        "script_path": str(Path(script_path)),
        "command_sha256": command_sha256_value,
        "input_artifact_refs": require_list("input_artifact_refs", input_artifact_refs),
        "output_artifact_refs": require_list("output_artifact_refs", output_artifact_refs),
        "validation_result_refs": require_list("validation_result_refs", validation_result_refs),
        "error_event_id": error_event_id,
        "failure_class": failure_class,
        "safe_exception_class": safe_exception_class,
        "safe_exception_message": safe_exception_message,
        "traceback_sha256": traceback_sha256,
        "stdout_artifact_ref": stdout_artifact_ref,
        "stderr_artifact_ref": stderr_artifact_ref,
        "bounded_log_artifact_ref": bounded_log_artifact_ref,
        "no_log_reason": no_log_reason,
        "redaction_status": redaction_status,
        "resource_counters": require_mapping("resource_counters", resource_counters),
        "retry_policy_ref": retry_policy_ref,
        "next_retry_at": next_retry_at,
        "replay_command": replay_command,
        "safe_metadata": ensure_safe_metadata(safe_metadata),
    }
    ensure_no_raw_log_fields(event)
    return event


def validate_stage_execution_event(record: dict[str, Any]) -> None:
    required = (
        "execution_event_id",
        "schema_version",
        "case_id",
        "case_key",
        "dispatch_id",
        "stage",
        "stage_attempt_id",
        "event_type",
        "event_status",
        "event_at",
        "attempt_number",
        "max_attempts",
        "runner_ref",
        "agent_or_component_ref",
        "script_path",
        "command_sha256",
        "input_artifact_refs",
        "output_artifact_refs",
        "validation_result_refs",
        "redaction_status",
        "replay_command",
    )
    for field in required:
        if field not in record:
            raise StageContractError(f"{field} is required")
    if record["schema_version"] != STAGE_EXECUTION_EVENT_SCHEMA_VERSION:
        raise StageContractError(f"schema_version must be {STAGE_EXECUTION_EVENT_SCHEMA_VERSION}")
    validate_stage(record["stage"])
    validate_event_type(record["event_type"])
    validate_event_status(record["event_status"])
    validate_redaction_status(record["redaction_status"])
    require_list("input_artifact_refs", record["input_artifact_refs"])
    require_list("output_artifact_refs", record["output_artifact_refs"])
    require_list("validation_result_refs", record["validation_result_refs"])
    require_non_empty("replay_command", record["replay_command"])
    if not any(
        record.get(field)
        for field in ("stdout_artifact_ref", "stderr_artifact_ref", "bounded_log_artifact_ref", "no_log_reason")
    ):
        raise StageContractError("stage execution event requires a bounded log artifact ref or no_log_reason")
    ensure_no_raw_log_fields(record)


def build_pipeline_error_event(
    *,
    error_event_id: str,
    execution_event_id: str,
    context: StageContext,
    failure_class: str,
    failure_grouping_key: str,
    retryability: str,
    safe_message: str,
    safe_metadata: dict[str, Any] | None = None,
    replay_command: str,
    unsafe_secret_exclusion_status: str = "passed",
    bounded_log_artifact_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    context = validate_context(context)
    require_non_empty("error_event_id", error_event_id)
    require_non_empty("execution_event_id", execution_event_id)
    validate_failure_class(failure_class)
    require_non_empty("failure_grouping_key", failure_grouping_key)
    validate_retryability(retryability)
    safe_message = require_non_empty("safe_message", safe_message)
    if len(safe_message.encode("utf-8")) > MAX_SAFE_MESSAGE_BYTES:
        raise StageContractError("safe_message is too large")
    require_non_empty("replay_command", replay_command)
    validate_unsafe_secret_exclusion_status(unsafe_secret_exclusion_status)

    return {
        "error_event_id": error_event_id,
        "schema_version": PIPELINE_ERROR_EVENT_SCHEMA_VERSION,
        "table": PIPELINE_ERROR_EVENT_TABLE,
        "execution_event_id": execution_event_id,
        "pipeline_run_id": context.pipeline_run_id,
        "case_lease_id": context.case_lease_id,
        "case_id": context.case_id,
        "case_key": context.case_key,
        "dispatch_id": context.dispatch_id,
        "stage": context.stage,
        "stage_attempt_id": context.stage_attempt_id,
        "failure_class": failure_class,
        "failure_grouping_key": failure_grouping_key,
        "retryability": retryability,
        "safe_message": safe_message,
        "safe_metadata": ensure_safe_metadata(safe_metadata),
        "replay_command": replay_command,
        "unsafe_secret_exclusion_status": unsafe_secret_exclusion_status,
        "bounded_log_artifact_refs": require_list("bounded_log_artifact_refs", bounded_log_artifact_refs),
        "created_at": utc_now_iso(),
    }


def validate_pipeline_error_event(record: dict[str, Any]) -> None:
    required = (
        "error_event_id",
        "schema_version",
        "execution_event_id",
        "case_id",
        "case_key",
        "dispatch_id",
        "stage",
        "stage_attempt_id",
        "failure_class",
        "failure_grouping_key",
        "retryability",
        "safe_message",
        "safe_metadata",
        "replay_command",
        "unsafe_secret_exclusion_status",
        "bounded_log_artifact_refs",
    )
    for field in required:
        if field not in record:
            raise StageContractError(f"{field} is required")
    if record["schema_version"] != PIPELINE_ERROR_EVENT_SCHEMA_VERSION:
        raise StageContractError(f"schema_version must be {PIPELINE_ERROR_EVENT_SCHEMA_VERSION}")
    require_non_empty("error_event_id", record["error_event_id"])
    require_non_empty("execution_event_id", record["execution_event_id"])
    validate_stage(record["stage"])
    require_non_empty("stage_attempt_id", record["stage_attempt_id"])
    validate_failure_class(record["failure_class"])
    require_non_empty("failure_grouping_key", record["failure_grouping_key"])
    validate_retryability(record["retryability"])
    require_non_empty("safe_message", record["safe_message"])
    require_non_empty("replay_command", record["replay_command"])
    validate_unsafe_secret_exclusion_status(record["unsafe_secret_exclusion_status"])
    ensure_safe_metadata(record["safe_metadata"])
    require_list("bounded_log_artifact_refs", record["bounded_log_artifact_refs"])
    ensure_no_raw_log_fields(record)


def write_stage_status_snapshot(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    validate_stage_status_snapshot(record)
    ensure_stage_logging_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {STAGE_STATUS_TABLE} (
          schema_version, case_id, case_key, dispatch_id, stage, status,
          stage_attempt_id, started_at, completed_at, duration_ms,
          input_artifacts, output_artifacts, dependency_feature_ids,
          blocking_feature_ids, reason_codes, latest_execution_event_ids,
          error_event_ids, replay_command, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["schema_version"],
            record["case_id"],
            record["case_key"],
            record["dispatch_id"],
            record["stage"],
            record["status"],
            record["stage_attempt_id"],
            record.get("started_at"),
            record.get("completed_at"),
            record.get("duration_ms"),
            canonical_json(record.get("input_artifacts", [])),
            canonical_json(record.get("output_artifacts", [])),
            canonical_json(record.get("dependency_feature_ids", [])),
            canonical_json(record.get("blocking_feature_ids", [])),
            canonical_json(record.get("reason_codes", [])),
            canonical_json(record.get("latest_execution_event_ids", [])),
            canonical_json(record.get("error_event_ids", [])),
            record["replay_command"],
            canonical_json(record.get("metadata", {})),
        ),
    )


def write_stage_status(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    write_stage_status_snapshot(conn, record)


def write_stage_execution_event(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_stage_execution_event(record)
    ensure_stage_logging_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {STAGE_EXECUTION_EVENT_TABLE} (
          execution_event_id, schema_version, pipeline_run_id, case_lease_id,
          case_id, case_key, dispatch_id, stage, stage_attempt_id, event_type,
          event_status, event_at, started_at, completed_at, duration_ms,
          attempt_number, max_attempts, runner_ref, agent_or_component_ref,
          script_path, command_sha256, input_artifact_refs, output_artifact_refs,
          validation_result_refs, error_event_id, failure_class,
          safe_exception_class, safe_exception_message, traceback_sha256,
          stdout_artifact_ref, stderr_artifact_ref, bounded_log_artifact_ref,
          no_log_reason, redaction_status, resource_counters, retry_policy_ref,
          next_retry_at, replay_command, safe_metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(execution_event_id) DO UPDATE SET
          event_status=excluded.event_status,
          completed_at=excluded.completed_at,
          duration_ms=excluded.duration_ms,
          output_artifact_refs=excluded.output_artifact_refs,
          validation_result_refs=excluded.validation_result_refs,
          error_event_id=excluded.error_event_id,
          failure_class=excluded.failure_class,
          safe_exception_class=excluded.safe_exception_class,
          safe_exception_message=excluded.safe_exception_message,
          bounded_log_artifact_ref=excluded.bounded_log_artifact_ref,
          no_log_reason=excluded.no_log_reason,
          resource_counters=excluded.resource_counters,
          retry_policy_ref=excluded.retry_policy_ref,
          next_retry_at=excluded.next_retry_at,
          safe_metadata=excluded.safe_metadata
        """,
        (
            record["execution_event_id"],
            record["schema_version"],
            record.get("pipeline_run_id"),
            record.get("case_lease_id"),
            record["case_id"],
            record["case_key"],
            record["dispatch_id"],
            record["stage"],
            record["stage_attempt_id"],
            record["event_type"],
            record["event_status"],
            record["event_at"],
            record.get("started_at"),
            record.get("completed_at"),
            record.get("duration_ms"),
            record["attempt_number"],
            record["max_attempts"],
            record["runner_ref"],
            record["agent_or_component_ref"],
            record["script_path"],
            record["command_sha256"],
            canonical_json(record.get("input_artifact_refs", [])),
            canonical_json(record.get("output_artifact_refs", [])),
            canonical_json(record.get("validation_result_refs", [])),
            record.get("error_event_id"),
            record.get("failure_class"),
            record.get("safe_exception_class"),
            record.get("safe_exception_message"),
            record.get("traceback_sha256"),
            record.get("stdout_artifact_ref"),
            record.get("stderr_artifact_ref"),
            record.get("bounded_log_artifact_ref"),
            record.get("no_log_reason"),
            record["redaction_status"],
            canonical_json(record.get("resource_counters", {})),
            record.get("retry_policy_ref"),
            record.get("next_retry_at"),
            record["replay_command"],
            canonical_json(record.get("safe_metadata", {})),
        ),
    )
    return record["execution_event_id"]


def write_pipeline_error_event(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_pipeline_error_event(record)
    ensure_stage_logging_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {PIPELINE_ERROR_EVENT_TABLE} (
          error_event_id, schema_version, execution_event_id, pipeline_run_id,
          case_lease_id, case_id, case_key, dispatch_id, stage,
          stage_attempt_id, failure_class, failure_grouping_key, retryability,
          safe_message, safe_metadata, replay_command,
          unsafe_secret_exclusion_status, bounded_log_artifact_refs, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(error_event_id) DO UPDATE SET
          execution_event_id=excluded.execution_event_id,
          failure_class=excluded.failure_class,
          failure_grouping_key=excluded.failure_grouping_key,
          retryability=excluded.retryability,
          safe_message=excluded.safe_message,
          safe_metadata=excluded.safe_metadata,
          replay_command=excluded.replay_command,
          unsafe_secret_exclusion_status=excluded.unsafe_secret_exclusion_status,
          bounded_log_artifact_refs=excluded.bounded_log_artifact_refs
        """,
        (
            record["error_event_id"],
            record["schema_version"],
            record["execution_event_id"],
            record.get("pipeline_run_id"),
            record.get("case_lease_id"),
            record["case_id"],
            record["case_key"],
            record["dispatch_id"],
            record["stage"],
            record["stage_attempt_id"],
            record["failure_class"],
            record["failure_grouping_key"],
            record["retryability"],
            record["safe_message"],
            canonical_json(record.get("safe_metadata", {})),
            record["replay_command"],
            record["unsafe_secret_exclusion_status"],
            canonical_json(record.get("bounded_log_artifact_refs", [])),
            record.get("created_at") or utc_now_iso(),
        ),
    )
    conn.execute(
        f"""
        INSERT INTO {FAILURE_PATTERN_GROUP_TABLE} (
          failure_grouping_key, failure_class, stage, first_seen_at,
          last_seen_at, event_count, safe_metadata
        )
        VALUES (?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(failure_grouping_key) DO UPDATE SET
          last_seen_at=excluded.last_seen_at,
          event_count=event_count + 1,
          safe_metadata=excluded.safe_metadata
        """,
        (
            record["failure_grouping_key"],
            record["failure_class"],
            record["stage"],
            record.get("created_at") or utc_now_iso(),
            record.get("created_at") or utc_now_iso(),
            canonical_json({"latest_error_event_id": record["error_event_id"]}),
        ),
    )
    return record["error_event_id"]
