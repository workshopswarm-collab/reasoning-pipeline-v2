"""ADS pipeline runner contract, controls, and AUTO-003 dispatch state machine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from predquant.ads_stage_logging import (
    StageContext,
    build_pipeline_error_event,
    build_stage_execution_event,
    build_stage_status_snapshot,
    command_sha256,
    ensure_stage_logging_schema,
    write_pipeline_error_event,
    write_stage_execution_event,
    write_stage_status_snapshot,
)
from predquant.ads_handoff_resolver import resolve_artifact_manifest

PIPELINE_CONTROL_STATE_TABLE = "ads_pipeline_control_state"
PIPELINE_RUN_TABLE = "ads_pipeline_runs"
PIPELINE_LOOP_ITERATION_TABLE = "ads_pipeline_loop_iterations"
PIPELINE_STOP_SIGNAL_TABLE = "ads_pipeline_stop_signals"
PIPELINE_CONTROL_STATE_ID = "ads-pipeline-control-current"
PIPELINE_CONTROL_SCHEMA_VERSION = "ads-pipeline-control/v1"
PIPELINE_RUN_SCHEMA_VERSION = "ads-pipeline-run/v1"
PIPELINE_LOOP_ITERATION_SCHEMA_VERSION = "ads-pipeline-loop-iteration/v1"
PIPELINE_STOP_SIGNAL_SCHEMA_VERSION = "ads-pipeline-stop-signal/v1"
PIPELINE_RUNNER_RESULT_SCHEMA_VERSION = "ads-pipeline-runner-result/v1"
PIPELINE_RUNNER_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "008_pipeline_runner_contract.sql"
)
PIPELINE_AUTOMATION_RECORDS_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "013_pipeline_automation_records.sql"
)

RUNNER_MODES = ("fixture", "non_executing_canary", "calibration_debt_production")
RUN_STATUSES = ("starting", "running", "draining", "stopped", "failed")
STOP_POLICIES = ("none", "stop_before_next_case", "stop_after_current_case", "safe_drain_now")
DEFAULT_DISABLE_ACTIONS = ("no_new_leases", "stop_after_current_case", "safe_drain_now")
STOP_SIGNAL_STATUSES = ("pending", "acknowledged")
DEPENDENCY_GATE_MODES = (
    "fixture",
    "runtime_integration",
    "calibration_debt_clearance",
    "autonomous_optimization_maturity",
)
IDLE_NO_CASE_POLICIES = ("sleep", "exit")

DEFAULT_RUNNER_MODE = "non_executing_canary"
DEFAULT_DISABLE_ACTION = "no_new_leases"
DEFAULT_DEPENDENCY_GATE_MODE = "runtime_integration"
TERMINAL_REASON_DISABLED = "pipeline_disabled"
TERMINAL_REASON_NON_EXECUTING = "auto001_non_executing_runner_skeleton"
TERMINAL_REASON_NO_ELIGIBLE_CASE = "no_eligible_case"
TERMINAL_REASON_AUTO003_COMPLETE = "auto003_single_case_complete"
TERMINAL_REASON_AUTO003_FAILED = "auto003_stage_failed"
TERMINAL_REASON_STOP_BEFORE_NEXT = "stop_before_next_case"
TERMINAL_REASON_STOP_AFTER_CURRENT = "stopped_after_current_case"
TERMINAL_REASON_SAFE_DRAIN = "safe_drain_now"
TERMINAL_REASON_RETRY_SCHEDULED = "auto004_retry_scheduled"
TERMINAL_REASON_STUCK_LEASE_RECOVERED = "auto004_stuck_lease_recovered"
TERMINAL_REASON_AUTO005_MAX_CASES = "auto005_max_cases_complete"

ADS_PIPELINE_STAGE_ORDER = (
    "case_selection",
    "evidence_packet",
    "policy_context",
    "related_market_context",
    "decomposition",
    "retrieval",
    "researcher_classification",
    "classification_verification",
    "scae",
    "synthesis",
    "decision",
    "training_trace",
    "replay_record",
)
AUTO003_HANDLER_STAGES = ADS_PIPELINE_STAGE_ORDER[1:]
AUTO003_REQUIRED_FORECAST_PERSISTENCE_STAGE = "decision"
RUNNER_SCRIPT_PATH = "/Users/agent2/.openclaw/orchestrator/scripts/bin/run_ads_pipeline_loop.py"
RUNNER_REPLAY_COMMAND = "python3 run_ads_pipeline_loop.py --execute-one-case"
RUNNER_COMMAND_SHA256 = command_sha256(RUNNER_REPLAY_COMMAND)

STAGE_COMPONENT_REFS = {
    "case_selection": "orchestrator",
    "evidence_packet": "orchestrator",
    "policy_context": "orchestrator",
    "related_market_context": "orchestrator",
    "decomposition": "decomposer",
    "retrieval": "researcher-swarm",
    "researcher_classification": "researcher-swarm",
    "classification_verification": "researcher-swarm",
    "scae": "scae",
    "synthesis": "orchestrator",
    "decision": "orchestrator",
    "training_trace": "orchestrator",
    "replay_record": "orchestrator",
    "terminal": "orchestrator",
}

FORBIDDEN_RUNNER_METADATA_KEYS = {
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
    "forecast_probability",
    "production_forecast_prob",
    "probability_override",
}
MAX_SAFE_METADATA_BYTES = 8192
MAX_SAFE_METADATA_STRING_BYTES = 4096


class PipelineRunnerContractError(ValueError):
    """Raised when the runner/control contract is unsafe or invalid."""


class RetryableStageError(PipelineRunnerContractError):
    """Raised when a stage should be retried after AUTO-004 backoff."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
        retry_policy_ref: str = "auto004-transient-stage-retry/v1",
    ):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.retry_policy_ref = retry_policy_ref


class NonRetryableStageError(PipelineRunnerContractError):
    """Raised when a stage failure should quarantine the leased case."""


@dataclass(frozen=True)
class IdlePolicy:
    on_no_eligible_case: str = "exit"
    idle_sleep_seconds: int = 60
    max_idle_cycles: int | None = None

    def to_record(self) -> dict[str, Any]:
        if self.on_no_eligible_case not in IDLE_NO_CASE_POLICIES:
            raise PipelineRunnerContractError("idle_policy.on_no_eligible_case is invalid")
        if not isinstance(self.idle_sleep_seconds, int) or self.idle_sleep_seconds < 0:
            raise PipelineRunnerContractError("idle_policy.idle_sleep_seconds must be a non-negative integer")
        if self.max_idle_cycles is not None and (
            not isinstance(self.max_idle_cycles, int) or self.max_idle_cycles < 0
        ):
            raise PipelineRunnerContractError("idle_policy.max_idle_cycles must be a non-negative integer")
        return {
            "on_no_eligible_case": self.on_no_eligible_case,
            "idle_sleep_seconds": self.idle_sleep_seconds,
            "max_idle_cycles": self.max_idle_cycles,
        }


@dataclass(frozen=True)
class PipelineRunnerPolicy:
    runner_mode: str = DEFAULT_RUNNER_MODE
    stop_policy: str = "none"
    max_cases: int | None = None
    idle_policy: IdlePolicy = field(default_factory=IdlePolicy)
    dependency_gate_mode: str = DEFAULT_DEPENDENCY_GATE_MODE
    allow_downstream_execution: bool = False
    allow_forecast_persistence: bool = False
    retry_backoff_seconds: int = 60
    require_manifest_handoffs: bool = False


@dataclass(frozen=True)
class StageHandlerResult:
    output_artifact_refs: tuple[str, ...] = ()
    validation_result_refs: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = field(default_factory=dict)
    script_path: str = RUNNER_SCRIPT_PATH
    command: str = RUNNER_REPLAY_COMMAND
    agent_or_component_ref: str | None = None
    forecast_decision_record_id: str | None = None
    forecast_decision_record_ref: str | None = None
    forecast_artifact_id: str | None = None
    market_prediction_id: str | None = None

    def to_record(self, stage: str) -> dict[str, Any]:
        output_refs = require_string_tuple("output_artifact_refs", self.output_artifact_refs)
        validation_refs = require_string_tuple("validation_result_refs", self.validation_result_refs)
        metadata = ensure_safe_metadata(self.safe_metadata)
        if self.forecast_decision_record_id is not None:
            require_non_empty("forecast_decision_record_id", self.forecast_decision_record_id)
        if self.forecast_decision_record_ref is not None:
            require_non_empty("forecast_decision_record_ref", self.forecast_decision_record_ref)
        if self.forecast_artifact_id is not None:
            require_non_empty("forecast_artifact_id", self.forecast_artifact_id)
        if self.market_prediction_id is not None:
            require_non_empty("market_prediction_id", self.market_prediction_id)
        return {
            "output_artifact_refs": output_refs,
            "validation_result_refs": validation_refs,
            "safe_metadata": metadata,
            "script_path": require_non_empty("script_path", self.script_path),
            "command": require_non_empty("command", self.command),
            "agent_or_component_ref": self.agent_or_component_ref or STAGE_COMPONENT_REFS[stage],
            "forecast_decision_record_id": self.forecast_decision_record_id,
            "forecast_decision_record_ref": self.forecast_decision_record_ref,
            "forecast_artifact_id": self.forecast_artifact_id,
            "market_prediction_id": self.market_prediction_id,
        }


@dataclass(frozen=True)
class PipelineRunnerResult:
    started: bool
    terminal_status: str
    pipeline_run_id: str | None
    runner_mode: str
    stage_order: tuple[str, ...]
    downstream_execution_enabled: bool
    forecast_persistence_enabled: bool
    reason: str
    case_lease_id: str | None = None
    completed_stage_count: int = 0
    forecast_decision_record_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_RUNNER_RESULT_SCHEMA_VERSION,
            "started": self.started,
            "terminal_status": self.terminal_status,
            "pipeline_run_id": self.pipeline_run_id,
            "runner_mode": self.runner_mode,
            "stage_order": list(self.stage_order),
            "downstream_execution_enabled": self.downstream_execution_enabled,
            "forecast_persistence_enabled": self.forecast_persistence_enabled,
            "reason": self.reason,
            "case_lease_id": self.case_lease_id,
            "completed_stage_count": self.completed_stage_count,
            "forecast_decision_record_id": self.forecast_decision_record_id,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_timestamp(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_seconds(timestamp: str, seconds: int) -> str:
    if not isinstance(seconds, int) or seconds < 0:
        raise PipelineRunnerContractError("seconds must be a non-negative integer")
    return (_parse_iso_timestamp(timestamp) + timedelta(seconds=seconds)).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise PipelineRunnerContractError(f"{field} is required")
    return value


def require_string_tuple(field: str, value: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise PipelineRunnerContractError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def require_choice(field: str, value: str, choices: tuple[str, ...]) -> str:
    require_non_empty(field, value)
    if value not in choices:
        raise PipelineRunnerContractError(f"{field} must be one of {', '.join(choices)}")
    return value


def ensure_safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise PipelineRunnerContractError("metadata must be an object")

    def check(value: Any, path: str = "metadata") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise PipelineRunnerContractError(f"{path} contains an invalid key")
                if key.lower() in FORBIDDEN_RUNNER_METADATA_KEYS:
                    raise PipelineRunnerContractError(f"{path}.{key} is forbidden in runner metadata")
                check(child, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                check(child, f"{path}[{idx}]")
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_SAFE_METADATA_STRING_BYTES:
                raise PipelineRunnerContractError(f"{path} string is too large for safe metadata")
        elif value is None or isinstance(value, (bool, int, float)):
            return
        else:
            raise PipelineRunnerContractError(f"{path} contains unsupported metadata type {type(value).__name__}")

    result = dict(metadata)
    check(result)
    if len(canonical_json(result).encode("utf-8")) > MAX_SAFE_METADATA_BYTES:
        raise PipelineRunnerContractError("metadata is too large")
    return result


def ensure_pipeline_runner_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(PIPELINE_RUNNER_MIGRATION.read_text(encoding="utf-8"))
    conn.executescript(PIPELINE_AUTOMATION_RECORDS_MIGRATION.read_text(encoding="utf-8"))


def validate_stage_order(stage_order: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    stages = tuple(stage_order)
    if stages != ADS_PIPELINE_STAGE_ORDER:
        raise PipelineRunnerContractError("stage_order must match the AUTO-001 ADS stage order contract")
    if len(set(stages)) != len(stages):
        raise PipelineRunnerContractError("stage_order may not contain duplicates")
    return stages


def make_pipeline_run_id(runner_mode: str, started_at: str) -> str:
    seed = canonical_json({"runner_mode": runner_mode, "started_at": started_at, "nonce": uuid.uuid4().hex})
    return "ads-pipeline-run:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    return f"{prefix}:" + hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()[:length]


def build_pipeline_control_state(
    *,
    pipeline_enabled: bool = False,
    desired_runner_mode: str = DEFAULT_RUNNER_MODE,
    updated_by: str = "system",
    reason: str = "no_live_autostart_default",
    default_disable_action: str = DEFAULT_DISABLE_ACTION,
    acknowledged_by_run_id: str | None = None,
    updated_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(pipeline_enabled, bool):
        raise PipelineRunnerContractError("pipeline_enabled must be boolean")
    record = {
        "schema_version": PIPELINE_CONTROL_SCHEMA_VERSION,
        "table": PIPELINE_CONTROL_STATE_TABLE,
        "control_state_id": PIPELINE_CONTROL_STATE_ID,
        "pipeline_enabled": pipeline_enabled,
        "desired_runner_mode": require_choice("desired_runner_mode", desired_runner_mode, RUNNER_MODES),
        "updated_at": updated_at or utc_now_iso(),
        "updated_by": require_non_empty("updated_by", updated_by),
        "reason": require_non_empty("reason", reason),
        "default_disable_action": require_choice(
            "default_disable_action",
            default_disable_action,
            DEFAULT_DISABLE_ACTIONS,
        ),
        "acknowledged_by_run_id": acknowledged_by_run_id,
        "metadata": ensure_safe_metadata(metadata),
    }
    validate_pipeline_control_state(record)
    return record


def validate_pipeline_control_state(record: dict[str, Any]) -> None:
    if record.get("schema_version") != PIPELINE_CONTROL_SCHEMA_VERSION:
        raise PipelineRunnerContractError(f"schema_version must be {PIPELINE_CONTROL_SCHEMA_VERSION}")
    if record.get("table") != PIPELINE_CONTROL_STATE_TABLE:
        raise PipelineRunnerContractError(f"table must be {PIPELINE_CONTROL_STATE_TABLE}")
    if record.get("control_state_id") != PIPELINE_CONTROL_STATE_ID:
        raise PipelineRunnerContractError(f"control_state_id must be {PIPELINE_CONTROL_STATE_ID}")
    if not isinstance(record.get("pipeline_enabled"), bool):
        raise PipelineRunnerContractError("pipeline_enabled must be boolean")
    require_choice("desired_runner_mode", record.get("desired_runner_mode"), RUNNER_MODES)
    require_non_empty("updated_at", record.get("updated_at"))
    require_non_empty("updated_by", record.get("updated_by"))
    require_non_empty("reason", record.get("reason"))
    require_choice("default_disable_action", record.get("default_disable_action"), DEFAULT_DISABLE_ACTIONS)
    if record.get("acknowledged_by_run_id") is not None:
        require_non_empty("acknowledged_by_run_id", record.get("acknowledged_by_run_id"))
    ensure_safe_metadata(record.get("metadata"))


def write_pipeline_control_state(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_pipeline_control_state(record)
    ensure_pipeline_runner_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {PIPELINE_CONTROL_STATE_TABLE} (
          control_state_id, schema_version, pipeline_enabled, desired_runner_mode,
          updated_at, updated_by, reason, default_disable_action,
          acknowledged_by_run_id, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(control_state_id) DO UPDATE SET
          schema_version = excluded.schema_version,
          pipeline_enabled = excluded.pipeline_enabled,
          desired_runner_mode = excluded.desired_runner_mode,
          updated_at = excluded.updated_at,
          updated_by = excluded.updated_by,
          reason = excluded.reason,
          default_disable_action = excluded.default_disable_action,
          acknowledged_by_run_id = excluded.acknowledged_by_run_id,
          metadata = excluded.metadata
        """,
        (
            record["control_state_id"],
            record["schema_version"],
            1 if record["pipeline_enabled"] else 0,
            record["desired_runner_mode"],
            record["updated_at"],
            record["updated_by"],
            record["reason"],
            record["default_disable_action"],
            record["acknowledged_by_run_id"],
            canonical_json(record["metadata"]),
        ),
    )
    return record["control_state_id"]


def _row_to_control_state(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    values = tuple(row)
    record = {
        "schema_version": values[0],
        "table": PIPELINE_CONTROL_STATE_TABLE,
        "control_state_id": values[1],
        "pipeline_enabled": bool(values[2]),
        "desired_runner_mode": values[3],
        "updated_at": values[4],
        "updated_by": values[5],
        "reason": values[6],
        "default_disable_action": values[7],
        "acknowledged_by_run_id": values[8],
        "metadata": json.loads(values[9] or "{}"),
    }
    validate_pipeline_control_state(record)
    return record


def read_pipeline_control_state(conn: sqlite3.Connection, *, create_default: bool = True) -> dict[str, Any]:
    ensure_pipeline_runner_schema(conn)
    row = conn.execute(
        f"""
        SELECT schema_version, control_state_id, pipeline_enabled, desired_runner_mode,
               updated_at, updated_by, reason, default_disable_action,
               acknowledged_by_run_id, metadata
        FROM {PIPELINE_CONTROL_STATE_TABLE}
        WHERE control_state_id = ?
        """,
        (PIPELINE_CONTROL_STATE_ID,),
    ).fetchone()
    if row is None:
        if not create_default:
            raise PipelineRunnerContractError("pipeline control state has not been initialized")
        default_record = build_pipeline_control_state()
        write_pipeline_control_state(conn, default_record)
        return default_record
    return _row_to_control_state(row)


def validate_pipeline_runner_policy(policy: PipelineRunnerPolicy) -> None:
    require_choice("runner_mode", policy.runner_mode, RUNNER_MODES)
    require_choice("stop_policy", policy.stop_policy, STOP_POLICIES)
    require_choice("dependency_gate_mode", policy.dependency_gate_mode, DEPENDENCY_GATE_MODES)
    if policy.max_cases is not None and (not isinstance(policy.max_cases, int) or policy.max_cases < 0):
        raise PipelineRunnerContractError("max_cases must be a non-negative integer")
    if not isinstance(policy.retry_backoff_seconds, int) or policy.retry_backoff_seconds < 0:
        raise PipelineRunnerContractError("retry_backoff_seconds must be a non-negative integer")
    if not isinstance(policy.require_manifest_handoffs, bool):
        raise PipelineRunnerContractError("require_manifest_handoffs must be boolean")
    policy.idle_policy.to_record()
    if policy.allow_forecast_persistence and not policy.allow_downstream_execution:
        raise PipelineRunnerContractError("forecast persistence requires downstream stage execution")


def validate_auto003_policy(
    policy: PipelineRunnerPolicy,
    downstream_stage_handlers: dict[str, Callable[..., Any]] | None,
) -> dict[str, Callable[..., Any]]:
    validate_pipeline_runner_policy(policy)
    if not policy.allow_downstream_execution:
        raise PipelineRunnerContractError("AUTO-003 requires downstream stage execution to be explicitly enabled")
    if not policy.allow_forecast_persistence:
        raise PipelineRunnerContractError(
            "AUTO-003 downstream stage execution requires forecast persistence to be explicitly enabled"
        )
    if policy.max_cases not in (None, 1):
        raise PipelineRunnerContractError("AUTO-003 executes exactly one leased case; AUTO-005 owns multi-case loops")
    if not downstream_stage_handlers:
        raise PipelineRunnerContractError("AUTO-003 requires downstream stage execution handlers")
    unknown = sorted(set(downstream_stage_handlers) - set(AUTO003_HANDLER_STAGES))
    if unknown:
        raise PipelineRunnerContractError("unknown AUTO-003 stage handlers: " + ", ".join(unknown))
    missing = [stage for stage in AUTO003_HANDLER_STAGES if stage not in downstream_stage_handlers]
    if missing:
        raise PipelineRunnerContractError("missing AUTO-003 stage handlers: " + ", ".join(missing))
    return dict(downstream_stage_handlers)


def validate_auto005_policy(
    policy: PipelineRunnerPolicy,
    downstream_stage_handlers: dict[str, Callable[..., Any]] | None,
) -> dict[str, Callable[..., Any]]:
    handlers = validate_auto003_policy(
        PipelineRunnerPolicy(
            runner_mode=policy.runner_mode,
            stop_policy=policy.stop_policy,
            max_cases=1,
            idle_policy=policy.idle_policy,
            dependency_gate_mode=policy.dependency_gate_mode,
            allow_downstream_execution=policy.allow_downstream_execution,
            allow_forecast_persistence=policy.allow_forecast_persistence,
            retry_backoff_seconds=policy.retry_backoff_seconds,
            require_manifest_handoffs=policy.require_manifest_handoffs,
        ),
        downstream_stage_handlers,
    )
    if not isinstance(policy.max_cases, int) or policy.max_cases < 2:
        raise PipelineRunnerContractError("AUTO-005 requires max_cases to be at least 2")
    return handlers


def build_pipeline_run(
    *,
    policy: PipelineRunnerPolicy,
    status: str = "stopped",
    pipeline_run_id: str | None = None,
    started_at: str | None = None,
    stopped_at: str | None = None,
    terminal_reason: str | None = TERMINAL_REASON_NON_EXECUTING,
    active_case_lease_id: str | None = None,
    last_iteration_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_pipeline_runner_policy(policy)
    require_choice("status", status, RUN_STATUSES)
    started_at = started_at or utc_now_iso()
    is_auto003 = policy.allow_downstream_execution or policy.allow_forecast_persistence
    metadata_record = {
        "auto001_contract_only": not is_auto003,
        "auto003_state_machine": is_auto003,
        "live_stage_execution": bool(policy.allow_downstream_execution),
    }
    metadata_record.update(ensure_safe_metadata(metadata))
    record = {
        "schema_version": PIPELINE_RUN_SCHEMA_VERSION,
        "table": PIPELINE_RUN_TABLE,
        "pipeline_run_id": pipeline_run_id or make_pipeline_run_id(policy.runner_mode, started_at),
        "runner_mode": policy.runner_mode,
        "status": status,
        "stage_order": list(validate_stage_order(ADS_PIPELINE_STAGE_ORDER)),
        "started_at": started_at,
        "stopped_at": stopped_at,
        "stop_policy": policy.stop_policy,
        "max_cases": policy.max_cases,
        "idle_policy": policy.idle_policy.to_record(),
        "dependency_gate_mode": policy.dependency_gate_mode,
        "active_case_lease_id": active_case_lease_id,
        "last_iteration_id": last_iteration_id,
        "no_live_autostart": True,
        "downstream_execution_enabled": bool(policy.allow_downstream_execution),
        "forecast_persistence_enabled": bool(policy.allow_forecast_persistence),
        "terminal_reason": terminal_reason,
        "metadata": metadata_record,
    }
    validate_pipeline_run(record)
    return record


def validate_pipeline_run(record: dict[str, Any]) -> None:
    if record.get("schema_version") != PIPELINE_RUN_SCHEMA_VERSION:
        raise PipelineRunnerContractError(f"schema_version must be {PIPELINE_RUN_SCHEMA_VERSION}")
    if record.get("table") != PIPELINE_RUN_TABLE:
        raise PipelineRunnerContractError(f"table must be {PIPELINE_RUN_TABLE}")
    require_non_empty("pipeline_run_id", record.get("pipeline_run_id"))
    require_choice("runner_mode", record.get("runner_mode"), RUNNER_MODES)
    require_choice("status", record.get("status"), RUN_STATUSES)
    validate_stage_order(record.get("stage_order", []))
    require_non_empty("started_at", record.get("started_at"))
    if record.get("stopped_at") is not None:
        require_non_empty("stopped_at", record.get("stopped_at"))
    require_choice("stop_policy", record.get("stop_policy"), STOP_POLICIES)
    max_cases = record.get("max_cases")
    if max_cases is not None and (not isinstance(max_cases, int) or max_cases < 0):
        raise PipelineRunnerContractError("max_cases must be a non-negative integer")
    IdlePolicy(**record.get("idle_policy", {})).to_record()
    require_choice("dependency_gate_mode", record.get("dependency_gate_mode"), DEPENDENCY_GATE_MODES)
    metadata = ensure_safe_metadata(record.get("metadata"))
    auto003_enabled = bool(metadata.get("auto003_state_machine"))
    if record.get("active_case_lease_id") is not None:
        require_non_empty("active_case_lease_id", record.get("active_case_lease_id"))
        if not auto003_enabled:
            raise PipelineRunnerContractError("AUTO-001 may not attach an active case lease")
    if record.get("last_iteration_id") is not None:
        require_non_empty("last_iteration_id", record.get("last_iteration_id"))
        if not auto003_enabled:
            raise PipelineRunnerContractError("AUTO-001 may not write loop iteration state")
    if record.get("no_live_autostart") is not True:
        raise PipelineRunnerContractError("no_live_autostart must be true")
    if record.get("downstream_execution_enabled") is not False and not auto003_enabled:
        raise PipelineRunnerContractError("AUTO-001 may not enable downstream stage execution")
    if record.get("forecast_persistence_enabled") is not False and not auto003_enabled:
        raise PipelineRunnerContractError("AUTO-001 may not enable forecast persistence")
    if record.get("forecast_persistence_enabled") and not record.get("downstream_execution_enabled"):
        raise PipelineRunnerContractError("forecast persistence requires downstream stage execution")
    if record.get("terminal_reason") is not None:
        require_non_empty("terminal_reason", record.get("terminal_reason"))


def write_pipeline_run(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_pipeline_run(record)
    ensure_pipeline_runner_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {PIPELINE_RUN_TABLE} (
          pipeline_run_id, schema_version, runner_mode, status, stage_order,
          started_at, stopped_at, stop_policy, max_cases, idle_policy,
          dependency_gate_mode, active_case_lease_id, last_iteration_id,
          no_live_autostart, downstream_execution_enabled,
          forecast_persistence_enabled, terminal_reason, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pipeline_run_id) DO UPDATE SET
          status = excluded.status,
          stage_order = excluded.stage_order,
          stopped_at = excluded.stopped_at,
          stop_policy = excluded.stop_policy,
          max_cases = excluded.max_cases,
          idle_policy = excluded.idle_policy,
          dependency_gate_mode = excluded.dependency_gate_mode,
          active_case_lease_id = excluded.active_case_lease_id,
          last_iteration_id = excluded.last_iteration_id,
          no_live_autostart = excluded.no_live_autostart,
          downstream_execution_enabled = excluded.downstream_execution_enabled,
          forecast_persistence_enabled = excluded.forecast_persistence_enabled,
          terminal_reason = excluded.terminal_reason,
          metadata = excluded.metadata,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            record["pipeline_run_id"],
            record["schema_version"],
            record["runner_mode"],
            record["status"],
            canonical_json(record["stage_order"]),
            record["started_at"],
            record["stopped_at"],
            record["stop_policy"],
            record["max_cases"],
            canonical_json(record["idle_policy"]),
            record["dependency_gate_mode"],
            record["active_case_lease_id"],
            record["last_iteration_id"],
            1 if record["no_live_autostart"] else 0,
            1 if record["downstream_execution_enabled"] else 0,
            1 if record["forecast_persistence_enabled"] else 0,
            record["terminal_reason"],
            canonical_json(record["metadata"]),
        ),
    )
    return record["pipeline_run_id"]


def read_pipeline_run(conn: sqlite3.Connection, pipeline_run_id: str) -> dict[str, Any]:
    ensure_pipeline_runner_schema(conn)
    row = conn.execute(
        f"""
        SELECT pipeline_run_id, schema_version, runner_mode, status, stage_order,
               started_at, stopped_at, stop_policy, max_cases, idle_policy,
               dependency_gate_mode, active_case_lease_id, last_iteration_id,
               no_live_autostart, downstream_execution_enabled,
               forecast_persistence_enabled, terminal_reason, metadata
        FROM {PIPELINE_RUN_TABLE}
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    if row is None:
        raise PipelineRunnerContractError(f"unknown pipeline_run_id: {pipeline_run_id}")
    values = tuple(row)
    record = {
        "pipeline_run_id": values[0],
        "schema_version": values[1],
        "table": PIPELINE_RUN_TABLE,
        "runner_mode": values[2],
        "status": values[3],
        "stage_order": json.loads(values[4] or "[]"),
        "started_at": values[5],
        "stopped_at": values[6],
        "stop_policy": values[7],
        "max_cases": values[8],
        "idle_policy": json.loads(values[9] or "{}"),
        "dependency_gate_mode": values[10],
        "active_case_lease_id": values[11],
        "last_iteration_id": values[12],
        "no_live_autostart": bool(values[13]),
        "downstream_execution_enabled": bool(values[14]),
        "forecast_persistence_enabled": bool(values[15]),
        "terminal_reason": values[16],
        "metadata": json.loads(values[17] or "{}"),
    }
    validate_pipeline_run(record)
    return record


def build_pipeline_loop_iteration(
    *,
    pipeline_run_id: str,
    iteration_number: int,
    terminal_status: str,
    loop_iteration_id: str | None = None,
    case_lease_id: str | None = None,
    case_id: str | None = None,
    case_key: str | None = None,
    dispatch_id: str | None = None,
    selected_case_key: str | None = None,
    stage_order: tuple[str, ...] | list[str] = ADS_PIPELINE_STAGE_ORDER,
    completed_stage_count: int = 0,
    forecast_decision_record_id: str | None = None,
    forecast_artifact_id: str | None = None,
    market_prediction_id: str | None = None,
    error_event_refs: list[str] | tuple[str, ...] | None = None,
    retry_summary: dict[str, Any] | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_non_empty("pipeline_run_id", pipeline_run_id)
    if not isinstance(iteration_number, int) or iteration_number < 1:
        raise PipelineRunnerContractError("iteration_number must be a positive integer")
    require_non_empty("terminal_status", terminal_status)
    if completed_stage_count < 0:
        raise PipelineRunnerContractError("completed_stage_count must be non-negative")
    refs = require_string_tuple("error_event_refs", error_event_refs)
    retry = ensure_safe_metadata(retry_summary)
    metadata_record = ensure_safe_metadata(metadata)
    resolved_started_at = started_at or utc_now_iso()
    record = {
        "schema_version": PIPELINE_LOOP_ITERATION_SCHEMA_VERSION,
        "table": PIPELINE_LOOP_ITERATION_TABLE,
        "loop_iteration_id": loop_iteration_id
        or stable_id("ads-loop-iteration", pipeline_run_id, case_lease_id or "no-lease", iteration_number),
        "pipeline_run_id": pipeline_run_id,
        "iteration_number": iteration_number,
        "case_lease_id": case_lease_id,
        "case_id": case_id,
        "case_key": case_key,
        "dispatch_id": dispatch_id,
        "selected_case_key": selected_case_key or case_key,
        "stage_order": list(validate_stage_order(stage_order)),
        "terminal_status": terminal_status,
        "completed_stage_count": int(completed_stage_count),
        "forecast_decision_record_id": forecast_decision_record_id,
        "forecast_artifact_id": forecast_artifact_id,
        "market_prediction_id": market_prediction_id,
        "error_event_refs": list(refs),
        "retry_summary": retry,
        "started_at": resolved_started_at,
        "completed_at": completed_at,
        "metadata": metadata_record,
    }
    validate_pipeline_loop_iteration(record)
    return record


def validate_pipeline_loop_iteration(record: dict[str, Any]) -> None:
    if record.get("schema_version") != PIPELINE_LOOP_ITERATION_SCHEMA_VERSION:
        raise PipelineRunnerContractError(f"schema_version must be {PIPELINE_LOOP_ITERATION_SCHEMA_VERSION}")
    if record.get("table") != PIPELINE_LOOP_ITERATION_TABLE:
        raise PipelineRunnerContractError(f"table must be {PIPELINE_LOOP_ITERATION_TABLE}")
    require_non_empty("loop_iteration_id", record.get("loop_iteration_id"))
    require_non_empty("pipeline_run_id", record.get("pipeline_run_id"))
    if not isinstance(record.get("iteration_number"), int) or record["iteration_number"] < 1:
        raise PipelineRunnerContractError("iteration_number must be a positive integer")
    require_non_empty("terminal_status", record.get("terminal_status"))
    if not isinstance(record.get("completed_stage_count"), int) or record["completed_stage_count"] < 0:
        raise PipelineRunnerContractError("completed_stage_count must be non-negative")
    validate_stage_order(record.get("stage_order", []))
    require_string_tuple("error_event_refs", record.get("error_event_refs"))
    ensure_safe_metadata(record.get("retry_summary"))
    ensure_safe_metadata(record.get("metadata"))
    for field_name in [
        "case_lease_id",
        "case_id",
        "case_key",
        "dispatch_id",
        "selected_case_key",
        "forecast_decision_record_id",
        "forecast_artifact_id",
        "market_prediction_id",
        "completed_at",
    ]:
        if record.get(field_name) is not None:
            require_non_empty(field_name, record.get(field_name))
    require_non_empty("started_at", record.get("started_at"))


def write_pipeline_loop_iteration(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_pipeline_loop_iteration(record)
    ensure_pipeline_runner_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {PIPELINE_LOOP_ITERATION_TABLE} (
          loop_iteration_id, schema_version, pipeline_run_id, iteration_number,
          case_lease_id, case_id, case_key, dispatch_id, selected_case_key,
          stage_order, terminal_status, completed_stage_count,
          forecast_decision_record_id, forecast_artifact_id, market_prediction_id,
          error_event_refs, retry_summary, started_at, completed_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(loop_iteration_id) DO UPDATE SET
          schema_version = excluded.schema_version,
          terminal_status = excluded.terminal_status,
          completed_stage_count = excluded.completed_stage_count,
          forecast_decision_record_id = excluded.forecast_decision_record_id,
          forecast_artifact_id = excluded.forecast_artifact_id,
          market_prediction_id = excluded.market_prediction_id,
          error_event_refs = excluded.error_event_refs,
          retry_summary = excluded.retry_summary,
          completed_at = excluded.completed_at,
          metadata = excluded.metadata,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            record["loop_iteration_id"],
            record["schema_version"],
            record["pipeline_run_id"],
            record["iteration_number"],
            record["case_lease_id"],
            record["case_id"],
            record["case_key"],
            record["dispatch_id"],
            record["selected_case_key"],
            canonical_json(record["stage_order"]),
            record["terminal_status"],
            record["completed_stage_count"],
            record["forecast_decision_record_id"],
            record["forecast_artifact_id"],
            record["market_prediction_id"],
            canonical_json(record["error_event_refs"]),
            canonical_json(record["retry_summary"]),
            record["started_at"],
            record["completed_at"],
            canonical_json(record["metadata"]),
        ),
    )
    return record["loop_iteration_id"]


def read_pipeline_loop_iteration(conn: sqlite3.Connection, loop_iteration_id: str) -> dict[str, Any]:
    ensure_pipeline_runner_schema(conn)
    row = conn.execute(
        f"""
        SELECT loop_iteration_id, schema_version, pipeline_run_id, iteration_number,
               case_lease_id, case_id, case_key, dispatch_id, selected_case_key,
               stage_order, terminal_status, completed_stage_count,
               forecast_decision_record_id, forecast_artifact_id, market_prediction_id,
               error_event_refs, retry_summary, started_at, completed_at, metadata
        FROM {PIPELINE_LOOP_ITERATION_TABLE}
        WHERE loop_iteration_id = ?
        """,
        (loop_iteration_id,),
    ).fetchone()
    if row is None:
        raise PipelineRunnerContractError(f"unknown loop_iteration_id: {loop_iteration_id}")
    values = tuple(row)
    record = {
        "loop_iteration_id": values[0],
        "schema_version": values[1],
        "table": PIPELINE_LOOP_ITERATION_TABLE,
        "pipeline_run_id": values[2],
        "iteration_number": values[3],
        "case_lease_id": values[4],
        "case_id": values[5],
        "case_key": values[6],
        "dispatch_id": values[7],
        "selected_case_key": values[8],
        "stage_order": json.loads(values[9] or "[]"),
        "terminal_status": values[10],
        "completed_stage_count": values[11],
        "forecast_decision_record_id": values[12],
        "forecast_artifact_id": values[13],
        "market_prediction_id": values[14],
        "error_event_refs": json.loads(values[15] or "[]"),
        "retry_summary": json.loads(values[16] or "{}"),
        "started_at": values[17],
        "completed_at": values[18],
        "metadata": json.loads(values[19] or "{}"),
    }
    validate_pipeline_loop_iteration(record)
    return record


def build_pipeline_stop_signal_record(
    *,
    stop_policy: str,
    reason: str,
    requested_by: str = "manual",
    requested_at: str | None = None,
    pipeline_run_id: str | None = None,
    stop_signal_id: str | None = None,
    source: str = "manual",
    signal_status: str = "pending",
    acknowledged_by_run_id: str | None = None,
    acknowledged_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stop_policy not in STOP_POLICIES or stop_policy == "none":
        raise PipelineRunnerContractError("stop_policy must be a concrete stop signal policy")
    require_non_empty("reason", reason)
    require_non_empty("requested_by", requested_by)
    requested_at = requested_at or utc_now_iso()
    metadata_record = ensure_safe_metadata(metadata)
    record = {
        "schema_version": PIPELINE_STOP_SIGNAL_SCHEMA_VERSION,
        "table": PIPELINE_STOP_SIGNAL_TABLE,
        "stop_signal_id": stop_signal_id
        or stable_id("ads-pipeline-stop-signal", requested_at, requested_by, stop_policy, pipeline_run_id or "", reason),
        "pipeline_run_id": pipeline_run_id,
        "stop_policy": stop_policy,
        "requested_at": requested_at,
        "requested_by": requested_by,
        "reason": reason,
        "source": require_non_empty("source", source),
        "signal_status": require_choice("signal_status", signal_status, STOP_SIGNAL_STATUSES),
        "acknowledged_by_run_id": acknowledged_by_run_id,
        "acknowledged_at": acknowledged_at,
        "metadata": metadata_record,
    }
    validate_pipeline_stop_signal(record)
    return record


def validate_pipeline_stop_signal(record: dict[str, Any]) -> None:
    if record.get("schema_version") != PIPELINE_STOP_SIGNAL_SCHEMA_VERSION:
        raise PipelineRunnerContractError(f"schema_version must be {PIPELINE_STOP_SIGNAL_SCHEMA_VERSION}")
    if record.get("table") != PIPELINE_STOP_SIGNAL_TABLE:
        raise PipelineRunnerContractError(f"table must be {PIPELINE_STOP_SIGNAL_TABLE}")
    require_non_empty("stop_signal_id", record.get("stop_signal_id"))
    stop_policy = record.get("stop_policy")
    if stop_policy not in STOP_POLICIES or stop_policy == "none":
        raise PipelineRunnerContractError("stop_policy must be a concrete stop signal policy")
    require_non_empty("requested_at", record.get("requested_at"))
    require_non_empty("requested_by", record.get("requested_by"))
    require_non_empty("reason", record.get("reason"))
    require_non_empty("source", record.get("source"))
    require_choice("signal_status", record.get("signal_status"), STOP_SIGNAL_STATUSES)
    if record.get("pipeline_run_id") is not None:
        require_non_empty("pipeline_run_id", record.get("pipeline_run_id"))
    if record.get("acknowledged_by_run_id") is not None:
        require_non_empty("acknowledged_by_run_id", record.get("acknowledged_by_run_id"))
    if record.get("acknowledged_at") is not None:
        require_non_empty("acknowledged_at", record.get("acknowledged_at"))
    if record.get("signal_status") == "acknowledged":
        require_non_empty("acknowledged_by_run_id", record.get("acknowledged_by_run_id"))
        require_non_empty("acknowledged_at", record.get("acknowledged_at"))
    ensure_safe_metadata(record.get("metadata"))


def write_pipeline_stop_signal(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_pipeline_stop_signal(record)
    ensure_pipeline_runner_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {PIPELINE_STOP_SIGNAL_TABLE} (
          stop_signal_id, schema_version, pipeline_run_id, stop_policy,
          requested_at, requested_by, reason, source, signal_status,
          acknowledged_by_run_id, acknowledged_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stop_signal_id) DO UPDATE SET
          schema_version = excluded.schema_version,
          pipeline_run_id = excluded.pipeline_run_id,
          stop_policy = excluded.stop_policy,
          requested_at = excluded.requested_at,
          requested_by = excluded.requested_by,
          reason = excluded.reason,
          source = excluded.source,
          signal_status = excluded.signal_status,
          acknowledged_by_run_id = excluded.acknowledged_by_run_id,
          acknowledged_at = excluded.acknowledged_at,
          metadata = excluded.metadata,
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            record["stop_signal_id"],
            record["schema_version"],
            record["pipeline_run_id"],
            record["stop_policy"],
            record["requested_at"],
            record["requested_by"],
            record["reason"],
            record["source"],
            record["signal_status"],
            record["acknowledged_by_run_id"],
            record["acknowledged_at"],
            canonical_json(record["metadata"]),
        ),
    )
    return record["stop_signal_id"]


def read_pipeline_stop_signal(conn: sqlite3.Connection, stop_signal_id: str) -> dict[str, Any]:
    ensure_pipeline_runner_schema(conn)
    row = conn.execute(
        f"""
        SELECT stop_signal_id, schema_version, pipeline_run_id, stop_policy,
               requested_at, requested_by, reason, source, signal_status,
               acknowledged_by_run_id, acknowledged_at, metadata
        FROM {PIPELINE_STOP_SIGNAL_TABLE}
        WHERE stop_signal_id = ?
        """,
        (stop_signal_id,),
    ).fetchone()
    if row is None:
        raise PipelineRunnerContractError(f"unknown stop_signal_id: {stop_signal_id}")
    values = tuple(row)
    record = {
        "stop_signal_id": values[0],
        "schema_version": values[1],
        "table": PIPELINE_STOP_SIGNAL_TABLE,
        "pipeline_run_id": values[2],
        "stop_policy": values[3],
        "requested_at": values[4],
        "requested_by": values[5],
        "reason": values[6],
        "source": values[7],
        "signal_status": values[8],
        "acknowledged_by_run_id": values[9],
        "acknowledged_at": values[10],
        "metadata": json.loads(values[11] or "{}"),
    }
    validate_pipeline_stop_signal(record)
    return record


def acknowledge_pipeline_stop_signal(
    conn: sqlite3.Connection,
    *,
    stop_signal_id: str,
    pipeline_run_id: str,
    acknowledged_at: str | None = None,
) -> dict[str, Any]:
    current = read_pipeline_stop_signal(conn, stop_signal_id)
    record = dict(current)
    record["signal_status"] = "acknowledged"
    record["acknowledged_by_run_id"] = pipeline_run_id
    record["acknowledged_at"] = acknowledged_at or utc_now_iso()
    write_pipeline_stop_signal(conn, record)
    return read_pipeline_stop_signal(conn, stop_signal_id)


def run_ads_pipeline_loop(
    conn: sqlite3.Connection,
    policy: PipelineRunnerPolicy | None = None,
    *,
    downstream_stage_handlers: dict[str, Callable[..., Any]] | None = None,
    case_selection_policy: Any | None = None,
) -> PipelineRunnerResult:
    """Run the ADS pipeline.

    The default path preserves AUTO-001: it writes only a safe non-executing
    runner record. When both execution flags and all stage handlers are supplied,
    AUTO-003 executes exactly one leased case through forecast-decision
    persistence and releases the lease. AUTO-005 owns bounded multi-case fixture
    loops when ``max_cases`` is greater than one.
    """

    policy = policy or PipelineRunnerPolicy()
    if policy.allow_downstream_execution or policy.allow_forecast_persistence:
        if policy.max_cases is not None and policy.max_cases > 1:
            return _run_auto005_continuous_fixture(
                conn,
                policy,
                downstream_stage_handlers=downstream_stage_handlers,
                case_selection_policy=case_selection_policy,
            )
        return _run_auto003_single_case(
            conn,
            policy,
            downstream_stage_handlers=downstream_stage_handlers,
            case_selection_policy=case_selection_policy,
        )
    if downstream_stage_handlers:
        raise PipelineRunnerContractError("AUTO-001 runner may not receive downstream stage execution handlers")
    validate_pipeline_runner_policy(policy)
    control = read_pipeline_control_state(conn)
    if not control["pipeline_enabled"]:
        return PipelineRunnerResult(
            started=False,
            terminal_status=TERMINAL_REASON_DISABLED,
            pipeline_run_id=None,
            runner_mode=policy.runner_mode,
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=False,
            forecast_persistence_enabled=False,
            reason=TERMINAL_REASON_DISABLED,
        )
    if policy.runner_mode != control["desired_runner_mode"]:
        raise PipelineRunnerContractError("runner_mode must match pipeline control desired_runner_mode")

    started_at = utc_now_iso()
    run_record = build_pipeline_run(
        policy=policy,
        status="stopped",
        started_at=started_at,
        stopped_at=utc_now_iso(),
        terminal_reason=TERMINAL_REASON_NON_EXECUTING,
    )
    write_pipeline_run(conn, run_record)
    return PipelineRunnerResult(
        started=True,
        terminal_status="stopped",
        pipeline_run_id=run_record["pipeline_run_id"],
        runner_mode=run_record["runner_mode"],
        stage_order=ADS_PIPELINE_STAGE_ORDER,
        downstream_execution_enabled=False,
        forecast_persistence_enabled=False,
        reason=TERMINAL_REASON_NON_EXECUTING,
    )


def _active_inflight_work_exists(conn: sqlite3.Connection) -> bool:
    ensure_pipeline_runner_schema(conn)
    row = conn.execute(
        f"""
        SELECT 1
        FROM {PIPELINE_RUN_TABLE}
        WHERE status IN ('starting', 'running', 'draining')
          AND active_case_lease_id IS NOT NULL
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        return True
    row = conn.execute(
        """
        SELECT 1
        FROM ads_case_leases
        WHERE lease_status = 'leased'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def recover_stuck_case_leases(
    conn: sqlite3.Connection,
    *,
    recovered_at: str | None = None,
) -> list[dict[str, Any]]:
    """Expire leased cases whose lease window elapsed and clear active runner refs."""

    from predquant.ads_case_selector import read_case_lease, release_case_lease

    ensure_pipeline_runner_schema(conn)
    recovered_at = recovered_at or utc_now_iso()
    recovered_dt = _parse_iso_timestamp(recovered_at)
    rows = conn.execute(
        """
        SELECT case_lease_id, lease_expires_at
        FROM ads_case_leases
        WHERE lease_status = 'leased'
        ORDER BY lease_expires_at, case_lease_id
        """
    ).fetchall()
    recovered: list[dict[str, Any]] = []
    for case_lease_id, lease_expires_at in rows:
        if _parse_iso_timestamp(lease_expires_at) > recovered_dt:
            continue
        lease = release_case_lease(
            conn,
            case_lease_id=case_lease_id,
            lease_status="expired",
            release_reason=TERMINAL_REASON_STUCK_LEASE_RECOVERED,
            released_at=recovered_at,
        )
        run_rows = conn.execute(
            f"""
            SELECT pipeline_run_id
            FROM {PIPELINE_RUN_TABLE}
            WHERE status IN ('starting', 'running', 'draining')
              AND active_case_lease_id = ?
            """,
            (case_lease_id,),
        ).fetchall()
        cleared_runs: list[str] = []
        for (pipeline_run_id,) in run_rows:
            run = read_pipeline_run(conn, pipeline_run_id)
            _update_pipeline_run(
                conn,
                run,
                status="failed",
                stopped_at=recovered_at,
                terminal_reason=TERMINAL_REASON_STUCK_LEASE_RECOVERED,
                active_case_lease_id=None,
                metadata_updates={
                    "feature_id": "AUTO-004",
                    "recovered_case_lease_id": case_lease_id,
                    "recovered_at": recovered_at,
                },
            )
            cleared_runs.append(pipeline_run_id)
        recovered.append({**read_case_lease(conn, case_lease_id), "cleared_pipeline_run_ids": cleared_runs})
        if lease["case_lease_id"] != case_lease_id:
            raise PipelineRunnerContractError("stuck lease recovery read back unexpected lease id")
    return recovered


def _update_pipeline_run(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    *,
    status: str | None = None,
    stopped_at: str | None = None,
    terminal_reason: str | None = None,
    active_case_lease_id: str | None | object = ...,
    last_iteration_id: str | None | object = ...,
    metadata_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = dict(record)
    if status is not None:
        updated["status"] = status
    if stopped_at is not None:
        updated["stopped_at"] = stopped_at
    if terminal_reason is not None:
        updated["terminal_reason"] = terminal_reason
    if active_case_lease_id is not ...:
        updated["active_case_lease_id"] = active_case_lease_id
    if last_iteration_id is not ...:
        updated["last_iteration_id"] = last_iteration_id
    if metadata_updates:
        metadata = dict(updated.get("metadata") or {})
        metadata.update(metadata_updates)
        updated["metadata"] = metadata
    write_pipeline_run(conn, updated)
    return updated


def _write_pipeline_loop_iteration(
    conn: sqlite3.Connection,
    run_record: dict[str, Any],
    *,
    terminal_status: str,
    iteration_number: int = 1,
    lease: dict[str, Any] | None = None,
    loop_iteration_id: str | None = None,
    completed_stage_count: int = 0,
    forecast_decision_record_id: str | None = None,
    forecast_artifact_id: str | None = None,
    market_prediction_id: str | None = None,
    error_event_refs: tuple[str, ...] = (),
    retry_summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = build_pipeline_loop_iteration(
        loop_iteration_id=loop_iteration_id,
        pipeline_run_id=run_record["pipeline_run_id"],
        iteration_number=iteration_number,
        case_lease_id=lease["case_lease_id"] if lease else None,
        case_id=lease["case_id"] if lease else None,
        case_key=lease["case_key"] if lease else None,
        dispatch_id=lease["dispatch_id"] if lease else None,
        selected_case_key=lease["case_key"] if lease else None,
        terminal_status=terminal_status,
        completed_stage_count=completed_stage_count,
        forecast_decision_record_id=forecast_decision_record_id,
        forecast_artifact_id=forecast_artifact_id,
        market_prediction_id=market_prediction_id,
        error_event_refs=error_event_refs,
        retry_summary=retry_summary,
        started_at=run_record["started_at"],
        completed_at=utc_now_iso(),
        metadata={"feature_id": "MIG-013", **(metadata or {})},
    )
    write_pipeline_loop_iteration(conn, record)
    if run_record.get("last_iteration_id") != record["loop_iteration_id"]:
        return _update_pipeline_run(
            conn,
            run_record,
            last_iteration_id=record["loop_iteration_id"],
            metadata_updates={"loop_iteration_id": record["loop_iteration_id"]},
        )
    return run_record


def _stage_context(lease: dict[str, Any], *, pipeline_run_id: str, stage: str) -> StageContext:
    return StageContext(
        case_id=lease["case_id"],
        case_key=lease["case_key"],
        dispatch_id=lease["dispatch_id"],
        stage=stage,
        stage_attempt_id=stable_id("stage-attempt", pipeline_run_id, lease["case_lease_id"], stage, 1),
        pipeline_run_id=pipeline_run_id,
        case_lease_id=lease["case_lease_id"],
    )


def _stage_event_id(context: StageContext, event_type: str) -> str:
    return stable_id("stage-exec-event", context.pipeline_run_id, context.case_lease_id, context.stage, event_type)


def _stage_replay_command(stage: str, context: StageContext) -> str:
    return (
        f"{RUNNER_REPLAY_COMMAND} --stage {stage} --case-id {context.case_id} "
        f"--dispatch-id {context.dispatch_id}"
    )


def _record_stage_started(conn: sqlite3.Connection, context: StageContext) -> str:
    event_id = _stage_event_id(context, "stage_started")
    replay_command = _stage_replay_command(context.stage, context)
    event = build_stage_execution_event(
        execution_event_id=event_id,
        context=context,
        event_type="stage_started",
        event_status="info",
        started_at=utc_now_iso(),
        attempt_number=1,
        max_attempts=1,
        runner_ref=f"ads-runner:{context.pipeline_run_id}",
        agent_or_component_ref=STAGE_COMPONENT_REFS[context.stage],
        script_path=RUNNER_SCRIPT_PATH,
        command_sha256_value=RUNNER_COMMAND_SHA256,
        no_log_reason="auto003_stage_invocation_has_no_raw_log",
        redaction_status="not_needed",
        replay_command=replay_command,
        safe_metadata={"feature_id": "AUTO-003"},
    )
    write_stage_execution_event(conn, event)
    status = build_stage_status_snapshot(
        context=context,
        status="running",
        started_at=event["started_at"],
        latest_execution_event_ids=[event_id],
        replay_command=replay_command,
        metadata={"feature_id": "AUTO-003"},
    )
    write_stage_status_snapshot(conn, status)
    return event_id


def _record_stage_completed(
    conn: sqlite3.Connection,
    context: StageContext,
    *,
    started_event_id: str,
    result: dict[str, Any],
) -> str:
    event_id = _stage_event_id(context, "stage_completed")
    replay_command = _stage_replay_command(context.stage, context)
    metadata = dict(result["safe_metadata"])
    if result.get("forecast_decision_record_id"):
        metadata["forecast_decision_record_id"] = result["forecast_decision_record_id"]
    if result.get("forecast_artifact_id"):
        metadata["forecast_artifact_id"] = result["forecast_artifact_id"]
    if result.get("market_prediction_id"):
        metadata["market_prediction_id"] = result["market_prediction_id"]
    event = build_stage_execution_event(
        execution_event_id=event_id,
        context=context,
        event_type="stage_completed",
        event_status="info",
        started_at=utc_now_iso(),
        completed_at=utc_now_iso(),
        duration_ms=0,
        attempt_number=1,
        max_attempts=1,
        runner_ref=f"ads-runner:{context.pipeline_run_id}",
        agent_or_component_ref=result["agent_or_component_ref"],
        script_path=result["script_path"],
        command_sha256_value=command_sha256(result["command"]),
        output_artifact_refs=result["output_artifact_refs"],
        validation_result_refs=result["validation_result_refs"],
        no_log_reason="auto003_stage_completed_without_raw_log",
        redaction_status="not_needed",
        replay_command=replay_command,
        safe_metadata=metadata,
    )
    write_stage_execution_event(conn, event)
    status = build_stage_status_snapshot(
        context=context,
        status="complete",
        completed_at=event["completed_at"],
        duration_ms=0,
        output_artifacts=result["output_artifact_refs"],
        latest_execution_event_ids=[started_event_id, event_id],
        replay_command=replay_command,
        metadata=metadata,
    )
    write_stage_status_snapshot(conn, status)
    return event_id


def _record_stage_failed(
    conn: sqlite3.Connection,
    context: StageContext,
    *,
    started_event_id: str,
    exc: BaseException,
) -> str:
    failed_event_id = _stage_event_id(context, "stage_failed")
    error_event_id = stable_id("pipeline-error", context.pipeline_run_id, context.case_lease_id, context.stage)
    replay_command = _stage_replay_command(context.stage, context)
    error = build_pipeline_error_event(
        error_event_id=error_event_id,
        execution_event_id=failed_event_id,
        context=context,
        failure_class="missing_required_artifact",
        failure_grouping_key=f"{context.stage}:auto003_stage_failed:{exc.__class__.__name__}",
        retryability="terminal",
        safe_message=str(exc)[:512] or exc.__class__.__name__,
        safe_metadata={"feature_id": "AUTO-003"},
        replay_command=replay_command,
    )
    event = build_stage_execution_event(
        execution_event_id=failed_event_id,
        context=context,
        event_type="stage_failed",
        event_status="error",
        completed_at=utc_now_iso(),
        duration_ms=0,
        attempt_number=1,
        max_attempts=1,
        runner_ref=f"ads-runner:{context.pipeline_run_id}",
        agent_or_component_ref=STAGE_COMPONENT_REFS[context.stage],
        script_path=RUNNER_SCRIPT_PATH,
        command_sha256_value=RUNNER_COMMAND_SHA256,
        error_event_id=error_event_id,
        failure_class="missing_required_artifact",
        safe_exception_class=exc.__class__.__name__,
        safe_exception_message=str(exc)[:512] or exc.__class__.__name__,
        no_log_reason="auto003_stage_failed_without_raw_log",
        redaction_status="not_needed",
        replay_command=replay_command,
        safe_metadata={"feature_id": "AUTO-003"},
    )
    write_stage_execution_event(conn, event)
    write_pipeline_error_event(conn, error)
    status = build_stage_status_snapshot(
        context=context,
        status="failed",
        completed_at=event["completed_at"],
        duration_ms=0,
        latest_execution_event_ids=[started_event_id, failed_event_id],
        error_event_ids=[error_event_id],
        reason_codes=["auto003_stage_failed"],
        replay_command=replay_command,
        metadata={"feature_id": "AUTO-003", "safe_exception_class": exc.__class__.__name__},
    )
    write_stage_status_snapshot(conn, status)
    return error_event_id


def _record_stage_retry_scheduled(
    conn: sqlite3.Connection,
    context: StageContext,
    *,
    started_event_id: str,
    exc: RetryableStageError,
    policy: PipelineRunnerPolicy,
) -> dict[str, Any]:
    retry_after_seconds = (
        policy.retry_backoff_seconds
        if exc.retry_after_seconds is None
        else exc.retry_after_seconds
    )
    if not isinstance(retry_after_seconds, int) or retry_after_seconds < 0:
        raise PipelineRunnerContractError("retry_after_seconds must be a non-negative integer")
    retry_event_id = _stage_event_id(context, "retry_scheduled")
    error_event_id = stable_id("pipeline-error", context.pipeline_run_id, context.case_lease_id, context.stage, "retry")
    replay_command = _stage_replay_command(context.stage, context)
    next_retry_at = add_seconds(utc_now_iso(), retry_after_seconds)
    safe_message = str(exc)[:512] or exc.__class__.__name__
    metadata = {
        "feature_id": "AUTO-004",
        "retry_policy_ref": exc.retry_policy_ref,
        "retry_after_seconds": retry_after_seconds,
        "started_execution_event_id": started_event_id,
    }
    error = build_pipeline_error_event(
        error_event_id=error_event_id,
        execution_event_id=retry_event_id,
        context=context,
        failure_class="dependency_not_ready",
        failure_grouping_key=f"{context.stage}:auto004_retry_scheduled:{exc.__class__.__name__}",
        retryability="retryable",
        safe_message=safe_message,
        safe_metadata=metadata,
        replay_command=replay_command,
    )
    event = build_stage_execution_event(
        execution_event_id=retry_event_id,
        context=context,
        event_type="retry_scheduled",
        event_status="warning",
        completed_at=utc_now_iso(),
        duration_ms=0,
        attempt_number=1,
        max_attempts=1,
        runner_ref=f"ads-runner:{context.pipeline_run_id}",
        agent_or_component_ref=STAGE_COMPONENT_REFS[context.stage],
        script_path=RUNNER_SCRIPT_PATH,
        command_sha256_value=RUNNER_COMMAND_SHA256,
        error_event_id=error_event_id,
        failure_class="dependency_not_ready",
        safe_exception_class=exc.__class__.__name__,
        safe_exception_message=safe_message,
        no_log_reason="auto004_retry_scheduled_without_raw_log",
        redaction_status="not_needed",
        retry_policy_ref=exc.retry_policy_ref,
        next_retry_at=next_retry_at,
        replay_command=replay_command,
        safe_metadata=metadata,
    )
    write_stage_execution_event(conn, event)
    write_pipeline_error_event(conn, error)
    status = build_stage_status_snapshot(
        context=context,
        status="blocked",
        completed_at=event["completed_at"],
        duration_ms=0,
        latest_execution_event_ids=[started_event_id, retry_event_id],
        error_event_ids=[error_event_id],
        reason_codes=[TERMINAL_REASON_RETRY_SCHEDULED],
        replay_command=replay_command,
        metadata={**metadata, "next_retry_at": next_retry_at},
    )
    write_stage_status_snapshot(conn, status)
    return {
        "retry_event_id": retry_event_id,
        "error_event_id": error_event_id,
        "next_retry_at": next_retry_at,
        "retry_policy_ref": exc.retry_policy_ref,
        "retry_after_seconds": retry_after_seconds,
    }


def _control_stop_signal(control: dict[str, Any]) -> dict[str, Any] | None:
    signal = dict(control.get("metadata", {}).get("stop_signal") or {})
    policy = signal.get("stop_policy")
    if policy in STOP_POLICIES and policy != "none":
        return signal
    if not control.get("pipeline_enabled"):
        action = control.get("default_disable_action")
        if action == "stop_after_current_case":
            return {"stop_policy": "stop_after_current_case", "source": "default_disable_action"}
        if action == "safe_drain_now":
            return {"stop_policy": "safe_drain_now", "source": "default_disable_action"}
        return {"stop_policy": "stop_before_next_case", "source": "default_disable_action"}
    return None


def _acknowledge_control_stop(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str,
    reason: str,
) -> None:
    control = read_pipeline_control_state(conn)
    metadata = dict(control.get("metadata") or {})
    signal = dict(metadata.get("stop_signal") or {})
    if control["pipeline_enabled"] and not signal:
        return
    if signal:
        signal["acknowledged_by_run_id"] = pipeline_run_id
        signal["acknowledged_at"] = utc_now_iso()
        signal["signal_status"] = "acknowledged"
        metadata["stop_signal"] = signal
        if signal.get("stop_signal_id"):
            acknowledge_pipeline_stop_signal(
                conn,
                stop_signal_id=signal["stop_signal_id"],
                pipeline_run_id=pipeline_run_id,
                acknowledged_at=signal["acknowledged_at"],
            )
    record = build_pipeline_control_state(
        pipeline_enabled=control["pipeline_enabled"],
        desired_runner_mode=control["desired_runner_mode"],
        updated_by="system",
        reason=reason,
        default_disable_action=control["default_disable_action"],
        acknowledged_by_run_id=pipeline_run_id,
        metadata=metadata,
    )
    write_pipeline_control_state(conn, record)


def _stop_without_case_lease(
    conn: sqlite3.Connection,
    *,
    policy: PipelineRunnerPolicy,
    terminal_reason: str,
    metadata: dict[str, Any] | None = None,
) -> PipelineRunnerResult:
    started_at = utc_now_iso()
    run_record = build_pipeline_run(
        policy=policy,
        status="stopped",
        started_at=started_at,
        stopped_at=utc_now_iso(),
        terminal_reason=terminal_reason,
        metadata={"feature_id": "AUTO-004", **(metadata or {})},
    )
    write_pipeline_run(conn, run_record)
    run_record = _write_pipeline_loop_iteration(
        conn,
        run_record,
        terminal_status=terminal_reason,
        metadata=metadata,
    )
    _acknowledge_control_stop(
        conn,
        pipeline_run_id=run_record["pipeline_run_id"],
        reason=terminal_reason,
    )
    return PipelineRunnerResult(
        started=True,
        terminal_status=terminal_reason,
        pipeline_run_id=run_record["pipeline_run_id"],
        runner_mode=run_record["runner_mode"],
        stage_order=ADS_PIPELINE_STAGE_ORDER,
        downstream_execution_enabled=True,
        forecast_persistence_enabled=True,
        reason=terminal_reason,
    )


def _coerce_stage_result(stage: str, value: Any) -> dict[str, Any]:
    if value is None:
        value = StageHandlerResult()
    if isinstance(value, StageHandlerResult):
        return value.to_record(stage)
    if not isinstance(value, dict):
        raise PipelineRunnerContractError(f"{stage} handler must return a result object")
    result = StageHandlerResult(
        output_artifact_refs=tuple(value.get("output_artifact_refs") or value.get("output_artifacts") or ()),
        validation_result_refs=tuple(value.get("validation_result_refs") or ()),
        safe_metadata=dict(value.get("safe_metadata") or value.get("metadata") or {}),
        script_path=value.get("script_path", RUNNER_SCRIPT_PATH),
        command=value.get("command", RUNNER_REPLAY_COMMAND),
        agent_or_component_ref=value.get("agent_or_component_ref"),
        forecast_decision_record_id=value.get("forecast_decision_record_id"),
        forecast_decision_record_ref=value.get("forecast_decision_record_ref"),
        forecast_artifact_id=value.get("forecast_artifact_id"),
        market_prediction_id=value.get("market_prediction_id"),
    )
    return result.to_record(stage)


def _call_stage_handler(
    handler: Callable[..., Any],
    *,
    conn: sqlite3.Connection,
    context: StageContext,
    lease: dict[str, Any],
    stage_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return _coerce_stage_result(
        context.stage,
        handler(
            conn=conn,
            context=context,
            lease=lease,
            stage_outputs=stage_outputs,
        ),
    )


def _validate_stage_manifest_handoffs(
    conn: sqlite3.Connection,
    *,
    stage: str,
    result: dict[str, Any],
    require_manifest_handoffs: bool,
) -> None:
    if not require_manifest_handoffs:
        return
    refs = result.get("output_artifact_refs") or ()
    if not refs:
        raise PipelineRunnerContractError(f"{stage} must return at least one artifact manifest ref")
    for artifact_id in refs:
        try:
            manifest = resolve_artifact_manifest(conn, artifact_id)
        except Exception as exc:
            raise PipelineRunnerContractError(
                f"{stage} output_artifact_refs must be persisted artifact manifests: {artifact_id}"
            ) from exc
        if manifest["case_id"] != result.get("safe_metadata", {}).get("case_id", manifest["case_id"]):
            raise PipelineRunnerContractError(f"{stage} artifact manifest case_id mismatch")


def _run_auto003_single_case(
    conn: sqlite3.Connection,
    policy: PipelineRunnerPolicy,
    *,
    downstream_stage_handlers: dict[str, Callable[..., Any]] | None,
    case_selection_policy: Any | None,
) -> PipelineRunnerResult:
    from predquant.ads_case_selector import CaseSelectionPolicy, acquire_next_case_lease, release_case_lease

    handlers = validate_auto003_policy(policy, downstream_stage_handlers)
    ensure_stage_logging_schema(conn)
    recovered_leases = recover_stuck_case_leases(conn)
    control = read_pipeline_control_state(conn)
    if not control["pipeline_enabled"]:
        signal = _control_stop_signal(control)
        if signal and control.get("metadata", {}).get("stop_signal"):
            stop_policy = signal["stop_policy"]
            terminal_reason = (
                TERMINAL_REASON_SAFE_DRAIN
                if stop_policy == "safe_drain_now"
                else TERMINAL_REASON_STOP_AFTER_CURRENT
                if stop_policy == "stop_after_current_case"
                else TERMINAL_REASON_STOP_BEFORE_NEXT
            )
            return _stop_without_case_lease(
                conn,
                policy=policy,
                terminal_reason=terminal_reason,
                metadata={"stop_signal": signal, "recovered_lease_count": len(recovered_leases)},
            )
        return PipelineRunnerResult(
            started=False,
            terminal_status=TERMINAL_REASON_DISABLED,
            pipeline_run_id=None,
            runner_mode=policy.runner_mode,
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=False,
            forecast_persistence_enabled=False,
            reason=TERMINAL_REASON_DISABLED,
        )
    if policy.runner_mode != control["desired_runner_mode"]:
        raise PipelineRunnerContractError("runner_mode must match pipeline control desired_runner_mode")
    if _active_inflight_work_exists(conn):
        raise PipelineRunnerContractError("AUTO-003 refuses to start while another case lease is in flight")
    if policy.stop_policy == "stop_before_next_case":
        return _stop_without_case_lease(
            conn,
            policy=policy,
            terminal_reason=TERMINAL_REASON_STOP_BEFORE_NEXT,
            metadata={"policy_stop": policy.stop_policy, "recovered_lease_count": len(recovered_leases)},
        )
    if policy.stop_policy == "safe_drain_now":
        return _stop_without_case_lease(
            conn,
            policy=policy,
            terminal_reason=TERMINAL_REASON_SAFE_DRAIN,
            metadata={"policy_stop": policy.stop_policy, "recovered_lease_count": len(recovered_leases)},
        )

    started_at = utc_now_iso()
    run_record = build_pipeline_run(
        policy=policy,
        status="running",
        started_at=started_at,
        terminal_reason="auto003_running",
        metadata={"feature_id": "AUTO-003", "recovered_lease_count": len(recovered_leases)},
    )
    write_pipeline_run(conn, run_record)

    lease = acquire_next_case_lease(
        conn,
        pipeline_run_id=run_record["pipeline_run_id"],
        policy=case_selection_policy or CaseSelectionPolicy(metadata={"feature_id": "AUTO-003"}),
    )
    if lease is None:
        run_record = _update_pipeline_run(
            conn,
            run_record,
            status="stopped",
            stopped_at=utc_now_iso(),
            terminal_reason=TERMINAL_REASON_NO_ELIGIBLE_CASE,
        )
        run_record = _write_pipeline_loop_iteration(
            conn,
            run_record,
            terminal_status=TERMINAL_REASON_NO_ELIGIBLE_CASE,
            metadata={"empty_queue": True},
        )
        return PipelineRunnerResult(
            started=True,
            terminal_status=TERMINAL_REASON_NO_ELIGIBLE_CASE,
            pipeline_run_id=run_record["pipeline_run_id"],
            runner_mode=run_record["runner_mode"],
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=True,
            forecast_persistence_enabled=True,
            reason=TERMINAL_REASON_NO_ELIGIBLE_CASE,
        )

    loop_iteration_id = stable_id("ads-loop-iteration", run_record["pipeline_run_id"], lease["case_lease_id"], 1)
    run_record = _update_pipeline_run(
        conn,
        run_record,
        active_case_lease_id=lease["case_lease_id"],
        last_iteration_id=loop_iteration_id,
        metadata_updates={"case_lease_id": lease["case_lease_id"], "loop_iteration_id": loop_iteration_id},
    )

    stage_outputs: dict[str, dict[str, Any]] = {}
    forecast_decision_record_id: str | None = None
    forecast_artifact_id: str | None = None
    market_prediction_id: str | None = None
    completed_stage_count = 0
    error_event_refs: tuple[str, ...] = ()
    stop_after_current_requested = policy.stop_policy == "stop_after_current_case"
    stop_after_current_reason = TERMINAL_REASON_STOP_AFTER_CURRENT
    try:
        context = _stage_context(lease, pipeline_run_id=run_record["pipeline_run_id"], stage="case_selection")
        started_event_id = _record_stage_started(conn, context)
        case_result = StageHandlerResult(
            output_artifact_refs=(lease["case_lease_id"],),
            safe_metadata={
                "selected_snapshot_id": lease["selected_snapshot_id"],
                "selection_policy_ref": lease["selection_policy_ref"],
            },
        ).to_record("case_selection")
        _record_stage_completed(conn, context, started_event_id=started_event_id, result=case_result)
        stage_outputs["case_selection"] = case_result
        completed_stage_count += 1

        for stage in AUTO003_HANDLER_STAGES:
            context = _stage_context(lease, pipeline_run_id=run_record["pipeline_run_id"], stage=stage)
            started_event_id = _record_stage_started(conn, context)
            try:
                result = _call_stage_handler(
                    handlers[stage],
                    conn=conn,
                    context=context,
                    lease=lease,
                    stage_outputs=stage_outputs,
                )
                _validate_stage_manifest_handoffs(
                    conn,
                    stage=stage,
                    result=result,
                    require_manifest_handoffs=policy.require_manifest_handoffs,
                )
                record_id = result.get("forecast_decision_record_id")
                if record_id:
                    if stage != AUTO003_REQUIRED_FORECAST_PERSISTENCE_STAGE:
                        raise PipelineRunnerContractError(
                            "forecast decision persistence must be reported by the decision stage"
                        )
                    if forecast_decision_record_id is not None:
                        raise PipelineRunnerContractError("duplicate forecast decision persistence for leased case")
                    forecast_decision_record_id = record_id
                    forecast_artifact_id = result.get("forecast_artifact_id")
                    market_prediction_id = result.get("market_prediction_id")
                _record_stage_completed(conn, context, started_event_id=started_event_id, result=result)
                stage_outputs[stage] = result
                completed_stage_count += 1
                latest_control = read_pipeline_control_state(conn)
                signal = _control_stop_signal(latest_control)
                if signal:
                    requested_policy = signal["stop_policy"]
                    if requested_policy == "safe_drain_now" or signal.get("source") == "default_disable_action":
                        release_case_lease(
                            conn,
                            case_lease_id=lease["case_lease_id"],
                            release_reason=TERMINAL_REASON_SAFE_DRAIN,
                            lease_status="expired",
                        )
                        run_record = _update_pipeline_run(
                            conn,
                            run_record,
                            status="stopped",
                            stopped_at=utc_now_iso(),
                            terminal_reason=TERMINAL_REASON_SAFE_DRAIN,
                            active_case_lease_id=None,
                            metadata_updates={
                                "completed_stage_count": completed_stage_count,
                                "stop_signal": signal,
                                "safe_drained_after_stage": stage,
                            },
                        )
                        _acknowledge_control_stop(
                            conn,
                            pipeline_run_id=run_record["pipeline_run_id"],
                            reason=TERMINAL_REASON_SAFE_DRAIN,
                        )
                        _write_pipeline_loop_iteration(
                            conn,
                            run_record,
                            terminal_status=TERMINAL_REASON_SAFE_DRAIN,
                            lease=lease,
                            loop_iteration_id=loop_iteration_id,
                            completed_stage_count=completed_stage_count,
                            forecast_decision_record_id=forecast_decision_record_id,
                            forecast_artifact_id=forecast_artifact_id,
                            market_prediction_id=market_prediction_id,
                            metadata={"safe_drained_after_stage": stage},
                        )
                        return PipelineRunnerResult(
                            started=True,
                            terminal_status=TERMINAL_REASON_SAFE_DRAIN,
                            pipeline_run_id=run_record["pipeline_run_id"],
                            runner_mode=run_record["runner_mode"],
                            stage_order=ADS_PIPELINE_STAGE_ORDER,
                            downstream_execution_enabled=True,
                            forecast_persistence_enabled=True,
                            reason=TERMINAL_REASON_SAFE_DRAIN,
                            case_lease_id=lease["case_lease_id"],
                            completed_stage_count=completed_stage_count,
                            forecast_decision_record_id=forecast_decision_record_id,
                        )
                    stop_after_current_requested = True
                    stop_after_current_reason = (
                        TERMINAL_REASON_STOP_BEFORE_NEXT
                        if requested_policy == "stop_before_next_case"
                        else TERMINAL_REASON_STOP_AFTER_CURRENT
                    )
            except RetryableStageError as exc:
                retry = _record_stage_retry_scheduled(
                    conn,
                    context,
                    started_event_id=started_event_id,
                    exc=exc,
                    policy=policy,
                )
                run_record = _update_pipeline_run(
                    conn,
                    run_record,
                    status="draining",
                    terminal_reason=TERMINAL_REASON_RETRY_SCHEDULED,
                    metadata_updates={
                        "completed_stage_count": completed_stage_count,
                        "retry_stage": stage,
                        "next_retry_at": retry["next_retry_at"],
                        "retry_policy_ref": retry["retry_policy_ref"],
                    },
                )
                _write_pipeline_loop_iteration(
                    conn,
                    run_record,
                    terminal_status=TERMINAL_REASON_RETRY_SCHEDULED,
                    lease=lease,
                    loop_iteration_id=loop_iteration_id,
                    completed_stage_count=completed_stage_count,
                    error_event_refs=(retry["error_event_id"],),
                    retry_summary={
                        "retry_stage": stage,
                        "next_retry_at": retry["next_retry_at"],
                        "retry_policy_ref": retry["retry_policy_ref"],
                        "retry_after_seconds": retry["retry_after_seconds"],
                    },
                )
                return PipelineRunnerResult(
                    started=True,
                    terminal_status=TERMINAL_REASON_RETRY_SCHEDULED,
                    pipeline_run_id=run_record["pipeline_run_id"],
                    runner_mode=run_record["runner_mode"],
                    stage_order=ADS_PIPELINE_STAGE_ORDER,
                    downstream_execution_enabled=True,
                    forecast_persistence_enabled=True,
                    reason=TERMINAL_REASON_RETRY_SCHEDULED,
                    case_lease_id=lease["case_lease_id"],
                    completed_stage_count=completed_stage_count,
                    forecast_decision_record_id=forecast_decision_record_id,
                )
            except Exception as exc:
                error_event_id = _record_stage_failed(conn, context, started_event_id=started_event_id, exc=exc)
                error_event_refs = (error_event_id,)
                raise

        if forecast_decision_record_id is None:
            exc = PipelineRunnerContractError("AUTO-003 requires one PERSIST-001 forecast decision record")
            context = _stage_context(lease, pipeline_run_id=run_record["pipeline_run_id"], stage="terminal")
            started_event_id = _record_stage_started(conn, context)
            error_event_id = _record_stage_failed(conn, context, started_event_id=started_event_id, exc=exc)
            error_event_refs = (error_event_id,)
            raise exc

        release_case_lease(
            conn,
            case_lease_id=lease["case_lease_id"],
            release_reason=(
                "auto004_stop_after_current_case"
                if stop_after_current_requested
                else "auto003_single_case_complete"
            ),
        )
        terminal_reason = stop_after_current_reason if stop_after_current_requested else TERMINAL_REASON_AUTO003_COMPLETE
        run_record = _update_pipeline_run(
            conn,
            run_record,
            status="stopped",
            stopped_at=utc_now_iso(),
            terminal_reason=terminal_reason,
            active_case_lease_id=None,
            metadata_updates={
                "completed_stage_count": completed_stage_count,
                "forecast_decision_record_id": forecast_decision_record_id,
                "stop_after_current_requested": stop_after_current_requested,
            },
        )
        if stop_after_current_requested:
            _acknowledge_control_stop(
                conn,
                pipeline_run_id=run_record["pipeline_run_id"],
                reason=terminal_reason,
            )
        _write_pipeline_loop_iteration(
            conn,
            run_record,
            terminal_status=terminal_reason,
            lease=lease,
            loop_iteration_id=loop_iteration_id,
            completed_stage_count=completed_stage_count,
            forecast_decision_record_id=forecast_decision_record_id,
            forecast_artifact_id=forecast_artifact_id,
            market_prediction_id=market_prediction_id,
            metadata={"stop_after_current_requested": stop_after_current_requested},
        )
        return PipelineRunnerResult(
            started=True,
            terminal_status=terminal_reason,
            pipeline_run_id=run_record["pipeline_run_id"],
            runner_mode=run_record["runner_mode"],
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=True,
            forecast_persistence_enabled=True,
            reason=terminal_reason,
            case_lease_id=lease["case_lease_id"],
            completed_stage_count=completed_stage_count,
            forecast_decision_record_id=forecast_decision_record_id,
        )

    except NonRetryableStageError:
        release_case_lease(
            conn,
            case_lease_id=lease["case_lease_id"],
            release_reason="auto004_non_retryable_stage_failed",
            lease_status="quarantined",
        )
        _update_pipeline_run(
            conn,
            run_record,
            status="failed",
            stopped_at=utc_now_iso(),
            terminal_reason=TERMINAL_REASON_AUTO003_FAILED,
            active_case_lease_id=None,
            metadata_updates={
                "completed_stage_count": completed_stage_count,
                "non_retryable_failure": True,
            },
        )
        _write_pipeline_loop_iteration(
            conn,
            run_record,
            terminal_status=TERMINAL_REASON_AUTO003_FAILED,
            lease=lease,
            loop_iteration_id=loop_iteration_id,
            completed_stage_count=completed_stage_count,
            error_event_refs=error_event_refs,
            metadata={"non_retryable_failure": True},
        )
        return PipelineRunnerResult(
            started=True,
            terminal_status=TERMINAL_REASON_AUTO003_FAILED,
            pipeline_run_id=run_record["pipeline_run_id"],
            runner_mode=run_record["runner_mode"],
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=True,
            forecast_persistence_enabled=True,
            reason=TERMINAL_REASON_AUTO003_FAILED,
            case_lease_id=lease["case_lease_id"],
            completed_stage_count=completed_stage_count,
            forecast_decision_record_id=forecast_decision_record_id,
        )
    except Exception:
        release_case_lease(
            conn,
            case_lease_id=lease["case_lease_id"],
            release_reason="auto003_stage_failed",
            lease_status="quarantined",
        )
        _update_pipeline_run(
            conn,
            run_record,
            status="failed",
            stopped_at=utc_now_iso(),
            terminal_reason=TERMINAL_REASON_AUTO003_FAILED,
            active_case_lease_id=None,
            metadata_updates={"completed_stage_count": completed_stage_count},
        )
        _write_pipeline_loop_iteration(
            conn,
            run_record,
            terminal_status=TERMINAL_REASON_AUTO003_FAILED,
            lease=lease,
            loop_iteration_id=loop_iteration_id,
            completed_stage_count=completed_stage_count,
            error_event_refs=error_event_refs,
        )
        return PipelineRunnerResult(
            started=True,
            terminal_status=TERMINAL_REASON_AUTO003_FAILED,
            pipeline_run_id=run_record["pipeline_run_id"],
            runner_mode=run_record["runner_mode"],
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=True,
            forecast_persistence_enabled=True,
            reason=TERMINAL_REASON_AUTO003_FAILED,
            case_lease_id=lease["case_lease_id"],
            completed_stage_count=completed_stage_count,
            forecast_decision_record_id=forecast_decision_record_id,
        )


def _run_auto005_continuous_fixture(
    conn: sqlite3.Connection,
    policy: PipelineRunnerPolicy,
    *,
    downstream_stage_handlers: dict[str, Callable[..., Any]] | None,
    case_selection_policy: Any | None,
) -> PipelineRunnerResult:
    from predquant.ads_case_selector import CaseSelectionPolicy, acquire_next_case_lease, release_case_lease

    handlers = validate_auto005_policy(policy, downstream_stage_handlers)
    ensure_stage_logging_schema(conn)
    recovered_leases = recover_stuck_case_leases(conn)
    control = read_pipeline_control_state(conn)
    if not control["pipeline_enabled"]:
        signal = _control_stop_signal(control)
        if signal and control.get("metadata", {}).get("stop_signal"):
            stop_policy = signal["stop_policy"]
            terminal_reason = (
                TERMINAL_REASON_SAFE_DRAIN
                if stop_policy == "safe_drain_now"
                else TERMINAL_REASON_STOP_AFTER_CURRENT
                if stop_policy == "stop_after_current_case"
                else TERMINAL_REASON_STOP_BEFORE_NEXT
            )
            return _stop_without_case_lease(
                conn,
                policy=policy,
                terminal_reason=terminal_reason,
                metadata={"feature_id": "AUTO-005", "stop_signal": signal, "recovered_lease_count": len(recovered_leases)},
            )
        return PipelineRunnerResult(
            started=False,
            terminal_status=TERMINAL_REASON_DISABLED,
            pipeline_run_id=None,
            runner_mode=policy.runner_mode,
            stage_order=ADS_PIPELINE_STAGE_ORDER,
            downstream_execution_enabled=False,
            forecast_persistence_enabled=False,
            reason=TERMINAL_REASON_DISABLED,
        )
    if policy.runner_mode != control["desired_runner_mode"]:
        raise PipelineRunnerContractError("runner_mode must match pipeline control desired_runner_mode")
    if _active_inflight_work_exists(conn):
        raise PipelineRunnerContractError("AUTO-005 refuses to start while another case lease is in flight")
    if policy.stop_policy == "stop_before_next_case":
        return _stop_without_case_lease(
            conn,
            policy=policy,
            terminal_reason=TERMINAL_REASON_STOP_BEFORE_NEXT,
            metadata={"feature_id": "AUTO-005", "policy_stop": policy.stop_policy, "recovered_lease_count": len(recovered_leases)},
        )
    if policy.stop_policy == "safe_drain_now":
        return _stop_without_case_lease(
            conn,
            policy=policy,
            terminal_reason=TERMINAL_REASON_SAFE_DRAIN,
            metadata={"feature_id": "AUTO-005", "policy_stop": policy.stop_policy, "recovered_lease_count": len(recovered_leases)},
        )

    started_at = utc_now_iso()
    run_record = build_pipeline_run(
        policy=policy,
        status="running",
        started_at=started_at,
        terminal_reason="auto005_running",
        metadata={
            "feature_id": "AUTO-005",
            "auto005_continuous_fixture": True,
            "recovered_lease_count": len(recovered_leases),
        },
    )
    write_pipeline_run(conn, run_record)

    processed_case_count = 0
    completed_case_lease_ids: list[str] = []
    completed_case_keys: list[str] = []
    forecast_decision_record_ids: list[str] = []
    forecast_artifact_ids: list[str] = []
    market_prediction_ids: list[str] = []
    latest_case_lease_id: str | None = None
    latest_forecast_decision_record_id: str | None = None
    latest_completed_stage_count = 0

    while processed_case_count < policy.max_cases:
        iteration_number = processed_case_count + 1
        latest_control = read_pipeline_control_state(conn)
        signal = _control_stop_signal(latest_control)
        if signal:
            stop_policy = signal["stop_policy"]
            terminal_reason = (
                TERMINAL_REASON_SAFE_DRAIN
                if stop_policy == "safe_drain_now"
                else TERMINAL_REASON_STOP_AFTER_CURRENT
                if stop_policy == "stop_after_current_case"
                else TERMINAL_REASON_STOP_BEFORE_NEXT
            )
            run_record = _update_pipeline_run(
                conn,
                run_record,
                status="stopped",
                stopped_at=utc_now_iso(),
                terminal_reason=terminal_reason,
                active_case_lease_id=None,
                metadata_updates={
                    "processed_case_count": processed_case_count,
                    "completed_case_lease_ids": completed_case_lease_ids,
                    "completed_case_keys": completed_case_keys,
                    "forecast_decision_record_ids": forecast_decision_record_ids,
                    "forecast_artifact_ids": forecast_artifact_ids,
                    "market_prediction_ids": market_prediction_ids,
                    "stop_signal": signal,
                    "stopped_before_next_case": True,
                },
            )
            run_record = _write_pipeline_loop_iteration(
                conn,
                run_record,
                terminal_status=terminal_reason,
                iteration_number=iteration_number,
                metadata={"feature_id": "AUTO-005", "stop_signal": signal, "stopped_before_next_case": True},
            )
            _acknowledge_control_stop(
                conn,
                pipeline_run_id=run_record["pipeline_run_id"],
                reason=terminal_reason,
            )
            return PipelineRunnerResult(
                started=True,
                terminal_status=terminal_reason,
                pipeline_run_id=run_record["pipeline_run_id"],
                runner_mode=run_record["runner_mode"],
                stage_order=ADS_PIPELINE_STAGE_ORDER,
                downstream_execution_enabled=True,
                forecast_persistence_enabled=True,
                reason=terminal_reason,
                case_lease_id=latest_case_lease_id,
                completed_stage_count=latest_completed_stage_count,
                forecast_decision_record_id=latest_forecast_decision_record_id,
            )

        lease = acquire_next_case_lease(
            conn,
            pipeline_run_id=run_record["pipeline_run_id"],
            policy=case_selection_policy or CaseSelectionPolicy(metadata={"feature_id": "AUTO-005"}),
        )
        if lease is None:
            run_record = _update_pipeline_run(
                conn,
                run_record,
                status="stopped",
                stopped_at=utc_now_iso(),
                terminal_reason=TERMINAL_REASON_NO_ELIGIBLE_CASE,
                active_case_lease_id=None,
                metadata_updates={
                    "processed_case_count": processed_case_count,
                    "completed_case_lease_ids": completed_case_lease_ids,
                    "completed_case_keys": completed_case_keys,
                    "forecast_decision_record_ids": forecast_decision_record_ids,
                    "forecast_artifact_ids": forecast_artifact_ids,
                    "market_prediction_ids": market_prediction_ids,
                },
            )
            run_record = _write_pipeline_loop_iteration(
                conn,
                run_record,
                terminal_status=TERMINAL_REASON_NO_ELIGIBLE_CASE,
                iteration_number=iteration_number,
                metadata={"feature_id": "AUTO-005", "empty_queue": True},
            )
            return PipelineRunnerResult(
                started=True,
                terminal_status=TERMINAL_REASON_NO_ELIGIBLE_CASE,
                pipeline_run_id=run_record["pipeline_run_id"],
                runner_mode=run_record["runner_mode"],
                stage_order=ADS_PIPELINE_STAGE_ORDER,
                downstream_execution_enabled=True,
                forecast_persistence_enabled=True,
                reason=TERMINAL_REASON_NO_ELIGIBLE_CASE,
                case_lease_id=latest_case_lease_id,
                completed_stage_count=latest_completed_stage_count,
                forecast_decision_record_id=latest_forecast_decision_record_id,
            )

        loop_iteration_id = stable_id(
            "ads-loop-iteration",
            run_record["pipeline_run_id"],
            lease["case_lease_id"],
            iteration_number,
        )
        run_record = _update_pipeline_run(
            conn,
            run_record,
            status="running",
            terminal_reason="auto005_running",
            active_case_lease_id=lease["case_lease_id"],
            last_iteration_id=loop_iteration_id,
            metadata_updates={
                "active_iteration_number": iteration_number,
                "case_lease_id": lease["case_lease_id"],
                "loop_iteration_id": loop_iteration_id,
            },
        )

        stage_outputs: dict[str, dict[str, Any]] = {}
        forecast_decision_record_id: str | None = None
        forecast_artifact_id: str | None = None
        market_prediction_id: str | None = None
        completed_stage_count = 0
        error_event_refs: tuple[str, ...] = ()
        stop_after_current_requested = policy.stop_policy == "stop_after_current_case"
        stop_after_current_reason = TERMINAL_REASON_STOP_AFTER_CURRENT
        try:
            context = _stage_context(lease, pipeline_run_id=run_record["pipeline_run_id"], stage="case_selection")
            started_event_id = _record_stage_started(conn, context)
            case_result = StageHandlerResult(
                output_artifact_refs=(lease["case_lease_id"],),
                safe_metadata={
                    "selected_snapshot_id": lease["selected_snapshot_id"],
                    "selection_policy_ref": lease["selection_policy_ref"],
                    "iteration_number": iteration_number,
                },
            ).to_record("case_selection")
            _record_stage_completed(conn, context, started_event_id=started_event_id, result=case_result)
            stage_outputs["case_selection"] = case_result
            completed_stage_count += 1

            for stage in AUTO003_HANDLER_STAGES:
                context = _stage_context(lease, pipeline_run_id=run_record["pipeline_run_id"], stage=stage)
                started_event_id = _record_stage_started(conn, context)
                try:
                    result = _call_stage_handler(
                        handlers[stage],
                        conn=conn,
                        context=context,
                        lease=lease,
                        stage_outputs=stage_outputs,
                    )
                    _validate_stage_manifest_handoffs(
                        conn,
                        stage=stage,
                        result=result,
                        require_manifest_handoffs=policy.require_manifest_handoffs,
                    )
                    record_id = result.get("forecast_decision_record_id")
                    if record_id:
                        if stage != AUTO003_REQUIRED_FORECAST_PERSISTENCE_STAGE:
                            raise PipelineRunnerContractError(
                                "forecast decision persistence must be reported by the decision stage"
                            )
                        if forecast_decision_record_id is not None:
                            raise PipelineRunnerContractError("duplicate forecast decision persistence for leased case")
                        if record_id in forecast_decision_record_ids:
                            raise PipelineRunnerContractError("duplicate forecast decision persistence across AUTO-005 cases")
                        forecast_decision_record_id = record_id
                        forecast_artifact_id = result.get("forecast_artifact_id")
                        market_prediction_id = result.get("market_prediction_id")
                        if forecast_artifact_id and forecast_artifact_id in forecast_artifact_ids:
                            raise PipelineRunnerContractError("duplicate forecast artifact persistence across AUTO-005 cases")
                        if market_prediction_id and market_prediction_id in market_prediction_ids:
                            raise PipelineRunnerContractError("duplicate market prediction persistence across AUTO-005 cases")
                    _record_stage_completed(conn, context, started_event_id=started_event_id, result=result)
                    stage_outputs[stage] = result
                    completed_stage_count += 1
                    latest_control = read_pipeline_control_state(conn)
                    signal = _control_stop_signal(latest_control)
                    if signal:
                        requested_policy = signal["stop_policy"]
                        if requested_policy == "safe_drain_now" or signal.get("source") == "default_disable_action":
                            release_case_lease(
                                conn,
                                case_lease_id=lease["case_lease_id"],
                                release_reason=TERMINAL_REASON_SAFE_DRAIN,
                                lease_status="expired",
                            )
                            run_record = _update_pipeline_run(
                                conn,
                                run_record,
                                status="stopped",
                                stopped_at=utc_now_iso(),
                                terminal_reason=TERMINAL_REASON_SAFE_DRAIN,
                                active_case_lease_id=None,
                                metadata_updates={
                                    "completed_stage_count": completed_stage_count,
                                    "processed_case_count": processed_case_count,
                                    "completed_case_lease_ids": completed_case_lease_ids,
                                    "completed_case_keys": completed_case_keys,
                                    "forecast_decision_record_ids": forecast_decision_record_ids,
                                    "forecast_artifact_ids": forecast_artifact_ids,
                                    "market_prediction_ids": market_prediction_ids,
                                    "stop_signal": signal,
                                    "safe_drained_after_stage": stage,
                                },
                            )
                            _acknowledge_control_stop(
                                conn,
                                pipeline_run_id=run_record["pipeline_run_id"],
                                reason=TERMINAL_REASON_SAFE_DRAIN,
                            )
                            _write_pipeline_loop_iteration(
                                conn,
                                run_record,
                                terminal_status=TERMINAL_REASON_SAFE_DRAIN,
                                iteration_number=iteration_number,
                                lease=lease,
                                loop_iteration_id=loop_iteration_id,
                                completed_stage_count=completed_stage_count,
                                forecast_decision_record_id=forecast_decision_record_id,
                                forecast_artifact_id=forecast_artifact_id,
                                market_prediction_id=market_prediction_id,
                                metadata={"feature_id": "AUTO-005", "safe_drained_after_stage": stage},
                            )
                            return PipelineRunnerResult(
                                started=True,
                                terminal_status=TERMINAL_REASON_SAFE_DRAIN,
                                pipeline_run_id=run_record["pipeline_run_id"],
                                runner_mode=run_record["runner_mode"],
                                stage_order=ADS_PIPELINE_STAGE_ORDER,
                                downstream_execution_enabled=True,
                                forecast_persistence_enabled=True,
                                reason=TERMINAL_REASON_SAFE_DRAIN,
                                case_lease_id=lease["case_lease_id"],
                                completed_stage_count=completed_stage_count,
                                forecast_decision_record_id=forecast_decision_record_id,
                            )
                        stop_after_current_requested = True
                        stop_after_current_reason = (
                            TERMINAL_REASON_STOP_BEFORE_NEXT
                            if requested_policy == "stop_before_next_case"
                            else TERMINAL_REASON_STOP_AFTER_CURRENT
                        )
                except RetryableStageError as exc:
                    retry = _record_stage_retry_scheduled(
                        conn,
                        context,
                        started_event_id=started_event_id,
                        exc=exc,
                        policy=policy,
                    )
                    run_record = _update_pipeline_run(
                        conn,
                        run_record,
                        status="draining",
                        terminal_reason=TERMINAL_REASON_RETRY_SCHEDULED,
                        metadata_updates={
                            "completed_stage_count": completed_stage_count,
                            "processed_case_count": processed_case_count,
                            "completed_case_lease_ids": completed_case_lease_ids,
                            "completed_case_keys": completed_case_keys,
                            "forecast_decision_record_ids": forecast_decision_record_ids,
                            "forecast_artifact_ids": forecast_artifact_ids,
                            "market_prediction_ids": market_prediction_ids,
                            "retry_stage": stage,
                            "next_retry_at": retry["next_retry_at"],
                            "retry_policy_ref": retry["retry_policy_ref"],
                        },
                    )
                    _write_pipeline_loop_iteration(
                        conn,
                        run_record,
                        terminal_status=TERMINAL_REASON_RETRY_SCHEDULED,
                        iteration_number=iteration_number,
                        lease=lease,
                        loop_iteration_id=loop_iteration_id,
                        completed_stage_count=completed_stage_count,
                        error_event_refs=(retry["error_event_id"],),
                        retry_summary={
                            "retry_stage": stage,
                            "next_retry_at": retry["next_retry_at"],
                            "retry_policy_ref": retry["retry_policy_ref"],
                            "retry_after_seconds": retry["retry_after_seconds"],
                        },
                    )
                    return PipelineRunnerResult(
                        started=True,
                        terminal_status=TERMINAL_REASON_RETRY_SCHEDULED,
                        pipeline_run_id=run_record["pipeline_run_id"],
                        runner_mode=run_record["runner_mode"],
                        stage_order=ADS_PIPELINE_STAGE_ORDER,
                        downstream_execution_enabled=True,
                        forecast_persistence_enabled=True,
                        reason=TERMINAL_REASON_RETRY_SCHEDULED,
                        case_lease_id=lease["case_lease_id"],
                        completed_stage_count=completed_stage_count,
                        forecast_decision_record_id=forecast_decision_record_id,
                    )
                except Exception as exc:
                    error_event_id = _record_stage_failed(conn, context, started_event_id=started_event_id, exc=exc)
                    error_event_refs = (error_event_id,)
                    raise

            if forecast_decision_record_id is None:
                exc = PipelineRunnerContractError("AUTO-005 requires one PERSIST-001 forecast decision record per case")
                context = _stage_context(lease, pipeline_run_id=run_record["pipeline_run_id"], stage="terminal")
                started_event_id = _record_stage_started(conn, context)
                error_event_id = _record_stage_failed(conn, context, started_event_id=started_event_id, exc=exc)
                error_event_refs = (error_event_id,)
                raise exc

            release_case_lease(
                conn,
                case_lease_id=lease["case_lease_id"],
                release_reason=(
                    "auto004_stop_after_current_case"
                    if stop_after_current_requested
                    else "auto005_iteration_complete"
                ),
            )
            terminal_reason = (
                stop_after_current_reason
                if stop_after_current_requested
                else TERMINAL_REASON_AUTO003_COMPLETE
            )
            completed_case_lease_ids.append(lease["case_lease_id"])
            completed_case_keys.append(lease["case_key"])
            forecast_decision_record_ids.append(forecast_decision_record_id)
            if forecast_artifact_id:
                forecast_artifact_ids.append(forecast_artifact_id)
            if market_prediction_id:
                market_prediction_ids.append(market_prediction_id)
            processed_case_count += 1
            latest_case_lease_id = lease["case_lease_id"]
            latest_forecast_decision_record_id = forecast_decision_record_id
            latest_completed_stage_count = completed_stage_count
            should_stop = stop_after_current_requested
            run_record = _update_pipeline_run(
                conn,
                run_record,
                status="stopped" if should_stop else "running",
                stopped_at=utc_now_iso() if should_stop else None,
                terminal_reason=terminal_reason if should_stop else "auto005_running",
                active_case_lease_id=None,
                metadata_updates={
                    "completed_stage_count": completed_stage_count,
                    "processed_case_count": processed_case_count,
                    "completed_case_lease_ids": completed_case_lease_ids,
                    "completed_case_keys": completed_case_keys,
                    "forecast_decision_record_ids": forecast_decision_record_ids,
                    "forecast_artifact_ids": forecast_artifact_ids,
                    "market_prediction_ids": market_prediction_ids,
                    "forecast_decision_record_id": forecast_decision_record_id,
                    "forecast_artifact_id": forecast_artifact_id,
                    "market_prediction_id": market_prediction_id,
                    "stop_after_current_requested": stop_after_current_requested,
                },
            )
            if should_stop:
                _acknowledge_control_stop(
                    conn,
                    pipeline_run_id=run_record["pipeline_run_id"],
                    reason=terminal_reason,
                )
            _write_pipeline_loop_iteration(
                conn,
                run_record,
                terminal_status=terminal_reason,
                iteration_number=iteration_number,
                lease=lease,
                loop_iteration_id=loop_iteration_id,
                completed_stage_count=completed_stage_count,
                forecast_decision_record_id=forecast_decision_record_id,
                forecast_artifact_id=forecast_artifact_id,
                market_prediction_id=market_prediction_id,
                metadata={
                    "feature_id": "AUTO-005",
                    "processed_case_count": processed_case_count,
                    "stop_after_current_requested": stop_after_current_requested,
                },
            )
            if should_stop:
                return PipelineRunnerResult(
                    started=True,
                    terminal_status=terminal_reason,
                    pipeline_run_id=run_record["pipeline_run_id"],
                    runner_mode=run_record["runner_mode"],
                    stage_order=ADS_PIPELINE_STAGE_ORDER,
                    downstream_execution_enabled=True,
                    forecast_persistence_enabled=True,
                    reason=terminal_reason,
                    case_lease_id=lease["case_lease_id"],
                    completed_stage_count=completed_stage_count,
                    forecast_decision_record_id=forecast_decision_record_id,
                )
        except NonRetryableStageError:
            release_case_lease(
                conn,
                case_lease_id=lease["case_lease_id"],
                release_reason="auto004_non_retryable_stage_failed",
                lease_status="quarantined",
            )
            _update_pipeline_run(
                conn,
                run_record,
                status="failed",
                stopped_at=utc_now_iso(),
                terminal_reason=TERMINAL_REASON_AUTO003_FAILED,
                active_case_lease_id=None,
                metadata_updates={
                    "completed_stage_count": completed_stage_count,
                    "processed_case_count": processed_case_count,
                    "completed_case_lease_ids": completed_case_lease_ids,
                    "completed_case_keys": completed_case_keys,
                    "forecast_decision_record_ids": forecast_decision_record_ids,
                    "forecast_artifact_ids": forecast_artifact_ids,
                    "market_prediction_ids": market_prediction_ids,
                    "non_retryable_failure": True,
                },
            )
            _write_pipeline_loop_iteration(
                conn,
                run_record,
                terminal_status=TERMINAL_REASON_AUTO003_FAILED,
                iteration_number=iteration_number,
                lease=lease,
                loop_iteration_id=loop_iteration_id,
                completed_stage_count=completed_stage_count,
                error_event_refs=error_event_refs,
                metadata={"feature_id": "AUTO-005", "non_retryable_failure": True},
            )
            return PipelineRunnerResult(
                started=True,
                terminal_status=TERMINAL_REASON_AUTO003_FAILED,
                pipeline_run_id=run_record["pipeline_run_id"],
                runner_mode=run_record["runner_mode"],
                stage_order=ADS_PIPELINE_STAGE_ORDER,
                downstream_execution_enabled=True,
                forecast_persistence_enabled=True,
                reason=TERMINAL_REASON_AUTO003_FAILED,
                case_lease_id=lease["case_lease_id"],
                completed_stage_count=completed_stage_count,
                forecast_decision_record_id=forecast_decision_record_id,
            )
        except Exception:
            release_case_lease(
                conn,
                case_lease_id=lease["case_lease_id"],
                release_reason="auto005_stage_failed",
                lease_status="quarantined",
            )
            _update_pipeline_run(
                conn,
                run_record,
                status="failed",
                stopped_at=utc_now_iso(),
                terminal_reason=TERMINAL_REASON_AUTO003_FAILED,
                active_case_lease_id=None,
                metadata_updates={
                    "completed_stage_count": completed_stage_count,
                    "processed_case_count": processed_case_count,
                    "completed_case_lease_ids": completed_case_lease_ids,
                    "completed_case_keys": completed_case_keys,
                    "forecast_decision_record_ids": forecast_decision_record_ids,
                    "forecast_artifact_ids": forecast_artifact_ids,
                    "market_prediction_ids": market_prediction_ids,
                },
            )
            _write_pipeline_loop_iteration(
                conn,
                run_record,
                terminal_status=TERMINAL_REASON_AUTO003_FAILED,
                iteration_number=iteration_number,
                lease=lease,
                loop_iteration_id=loop_iteration_id,
                completed_stage_count=completed_stage_count,
                error_event_refs=error_event_refs,
                metadata={"feature_id": "AUTO-005"},
            )
            return PipelineRunnerResult(
                started=True,
                terminal_status=TERMINAL_REASON_AUTO003_FAILED,
                pipeline_run_id=run_record["pipeline_run_id"],
                runner_mode=run_record["runner_mode"],
                stage_order=ADS_PIPELINE_STAGE_ORDER,
                downstream_execution_enabled=True,
                forecast_persistence_enabled=True,
                reason=TERMINAL_REASON_AUTO003_FAILED,
                case_lease_id=lease["case_lease_id"],
                completed_stage_count=completed_stage_count,
                forecast_decision_record_id=forecast_decision_record_id,
            )

    run_record = _update_pipeline_run(
        conn,
        run_record,
        status="stopped",
        stopped_at=utc_now_iso(),
        terminal_reason=TERMINAL_REASON_AUTO005_MAX_CASES,
        active_case_lease_id=None,
        metadata_updates={
            "processed_case_count": processed_case_count,
            "completed_case_lease_ids": completed_case_lease_ids,
            "completed_case_keys": completed_case_keys,
            "forecast_decision_record_ids": forecast_decision_record_ids,
            "forecast_artifact_ids": forecast_artifact_ids,
            "market_prediction_ids": market_prediction_ids,
        },
    )
    return PipelineRunnerResult(
        started=True,
        terminal_status=TERMINAL_REASON_AUTO005_MAX_CASES,
        pipeline_run_id=run_record["pipeline_run_id"],
        runner_mode=run_record["runner_mode"],
        stage_order=ADS_PIPELINE_STAGE_ORDER,
        downstream_execution_enabled=True,
        forecast_persistence_enabled=True,
        reason=TERMINAL_REASON_AUTO005_MAX_CASES,
        case_lease_id=latest_case_lease_id,
        completed_stage_count=latest_completed_stage_count,
        forecast_decision_record_id=latest_forecast_decision_record_id,
    )
