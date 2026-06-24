"""ADS v2 stage vocabulary and stage-event record contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE_STATUS_TABLE = "v2_stage_status_snapshots"
STAGE_EXECUTION_EVENT_TABLE = "v2_stage_execution_events"
STAGE_STATUS_SCHEMA_VERSION = "v2-stage-status-snapshot/v1"
STAGE_EXECUTION_EVENT_SCHEMA_VERSION = "v2-stage-execution-event/v1"

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
RAW_LOG_FIELDS = ("stdout", "stderr", "traceback", "browser_log", "raw_log")


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
        "safe_metadata": require_mapping("safe_metadata", safe_metadata),
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

