"""AUTO-001 safe pipeline runner contract and control-state helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PIPELINE_CONTROL_STATE_TABLE = "ads_pipeline_control_state"
PIPELINE_RUN_TABLE = "ads_pipeline_runs"
PIPELINE_CONTROL_STATE_ID = "ads-pipeline-control-current"
PIPELINE_CONTROL_SCHEMA_VERSION = "ads-pipeline-control/v1"
PIPELINE_RUN_SCHEMA_VERSION = "ads-pipeline-run/v1"
PIPELINE_RUNNER_RESULT_SCHEMA_VERSION = "ads-pipeline-runner-result/v1"
PIPELINE_RUNNER_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "008_pipeline_runner_contract.sql"
)

RUNNER_MODES = ("fixture", "non_executing_canary", "calibration_debt_production")
RUN_STATUSES = ("starting", "running", "draining", "stopped", "failed")
STOP_POLICIES = ("none", "stop_before_next_case", "stop_after_current_case", "safe_drain_now")
DEFAULT_DISABLE_ACTIONS = ("no_new_leases", "stop_after_current_case", "safe_drain_now")
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
    """Raised when the AUTO-001 runner/control contract is unsafe or invalid."""


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
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise PipelineRunnerContractError(f"{field} is required")
    return value


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
    policy.idle_policy.to_record()
    if policy.allow_downstream_execution:
        raise PipelineRunnerContractError("AUTO-001 runner may not enable downstream stage execution")
    if policy.allow_forecast_persistence:
        raise PipelineRunnerContractError("AUTO-001 runner may not enable forecast persistence")


def build_pipeline_run(
    *,
    policy: PipelineRunnerPolicy,
    status: str = "stopped",
    pipeline_run_id: str | None = None,
    started_at: str | None = None,
    stopped_at: str | None = None,
    terminal_reason: str | None = TERMINAL_REASON_NON_EXECUTING,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_pipeline_runner_policy(policy)
    require_choice("status", status, RUN_STATUSES)
    started_at = started_at or utc_now_iso()
    metadata_record = {"auto001_contract_only": True, "live_stage_execution": False}
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
        "active_case_lease_id": None,
        "last_iteration_id": None,
        "no_live_autostart": True,
        "downstream_execution_enabled": False,
        "forecast_persistence_enabled": False,
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
    if record.get("active_case_lease_id") is not None:
        raise PipelineRunnerContractError("AUTO-001 may not attach an active case lease")
    if record.get("last_iteration_id") is not None:
        raise PipelineRunnerContractError("AUTO-001 may not write loop iteration state")
    if record.get("no_live_autostart") is not True:
        raise PipelineRunnerContractError("no_live_autostart must be true")
    if record.get("downstream_execution_enabled") is not False:
        raise PipelineRunnerContractError("downstream_execution_enabled must be false")
    if record.get("forecast_persistence_enabled") is not False:
        raise PipelineRunnerContractError("forecast_persistence_enabled must be false")
    if record.get("terminal_reason") is not None:
        require_non_empty("terminal_reason", record.get("terminal_reason"))
    ensure_safe_metadata(record.get("metadata"))


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


def run_ads_pipeline_loop(
    conn: sqlite3.Connection,
    policy: PipelineRunnerPolicy | None = None,
    *,
    downstream_stage_handlers: dict[str, Callable[..., Any]] | None = None,
) -> PipelineRunnerResult:
    """Start the AUTO-001 runner skeleton without selecting cases or running stages."""

    policy = policy or PipelineRunnerPolicy()
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
