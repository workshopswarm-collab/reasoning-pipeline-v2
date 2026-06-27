"""Bounded ADS operational canary harness."""

from __future__ import annotations

import importlib
import importlib.util
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from predquant.ads_case_selector import CASE_LEASE_TABLE, CaseSelectionPolicy, select_eligible_case
from predquant.ads_pipeline_control import set_pipeline_enabled
from predquant.ads_pipeline_runner import (
    ADS_PIPELINE_STAGE_ORDER,
    PIPELINE_RUN_TABLE,
    RUNNER_MODES,
    TERMINAL_REASON_AUTO005_MAX_CASES,
    TERMINAL_REASON_STOP_AFTER_CURRENT,
    PipelineRunnerContractError,
    PipelineRunnerPolicy,
    ensure_pipeline_runner_schema,
    run_ads_pipeline_loop,
    validate_auto003_policy,
    validate_auto005_policy,
)
from predquant.ads_real_runtime_canary import build_real_runtime_canary_report

DEFAULT_PROTECTED_TABLES = (
    "market_predictions",
    "forecast_decision_records",
    "scae_ledger_outputs",
)


@dataclass(frozen=True)
class OperationalCanaryConfig:
    db_path: Path
    runner_mode: str = "fixture"
    forecast_timestamp: str | None = None
    max_cases: int = 1
    lease_duration_seconds: int = 900
    retry_backoff_seconds: int = 60
    updated_by: str = "manual"
    reason: str = "one-case ADS operational canary"
    require_scoreable_prediction: bool = True
    require_manifest_handoffs: bool = False
    skip_existing_ads_predictions: bool = False
    protected_tables: tuple[str, ...] = DEFAULT_PROTECTED_TABLES
    metadata: dict[str, Any] = field(default_factory=dict)
    handler_factory_kwargs: dict[str, Any] = field(default_factory=dict)
    require_real_runtime_canary_criteria: bool = False
    require_qdt_model_executed: bool = True
    require_researcher_model_executed: bool = False
    allowed_stage_failure_classes: tuple[str, ...] = ()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def active_work_counts(conn: sqlite3.Connection) -> dict[str, int]:
    ensure_pipeline_runner_schema(conn)
    active_runs = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {PIPELINE_RUN_TABLE}
            WHERE status IN ('starting', 'running', 'draining')
            """
        ).fetchone()[0]
    )
    active_leases = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {CASE_LEASE_TABLE}
            WHERE lease_status = 'leased'
            """
        ).fetchone()[0]
    )
    return {"active_runs": active_runs, "active_leases": active_leases}


def protected_counts(conn: sqlite3.Connection, tables: tuple[str, ...] = DEFAULT_PROTECTED_TABLES) -> dict[str, int]:
    return {table: table_count(conn, table) for table in tables}


def count_deltas(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {table: after.get(table, 0) - before.get(table, 0) for table in sorted(set(before) | set(after))}


def validate_preflight(
    conn: sqlite3.Connection,
    config: OperationalCanaryConfig,
    handlers: dict[str, Callable[..., Any]],
) -> dict[str, Any]:
    if config.runner_mode not in RUNNER_MODES:
        raise PipelineRunnerContractError("runner_mode is invalid")
    if not isinstance(config.max_cases, int) or config.max_cases < 1:
        raise PipelineRunnerContractError("max_cases must be a positive integer")
    stop_policy = "stop_after_current_case" if config.max_cases == 1 else "none"
    policy = PipelineRunnerPolicy(
        runner_mode=config.runner_mode,
        stop_policy=stop_policy,
        max_cases=config.max_cases,
        dependency_gate_mode="calibration_debt_clearance",
        allow_downstream_execution=True,
        allow_forecast_persistence=True,
        retry_backoff_seconds=config.retry_backoff_seconds,
        require_manifest_handoffs=config.require_manifest_handoffs,
    )
    if config.max_cases == 1:
        validate_auto003_policy(policy, handlers)
    else:
        validate_auto005_policy(policy, handlers)
    active = active_work_counts(conn)
    errors: list[str] = []
    if active["active_runs"]:
        errors.append("active ADS pipeline runs exist")
    if active["active_leases"]:
        errors.append("active ADS case leases exist")
    case_policy = build_operational_case_selection_policy(config)
    eligible_case = select_eligible_case(conn, case_policy)
    if eligible_case is None:
        errors.append("no eligible ADS case available for canary forecast timestamp and snapshot-age policy")
    control = set_pipeline_enabled(
        conn,
        pipeline_enabled=False,
        desired_runner_mode=config.runner_mode,
        updated_by=config.updated_by,
        reason="operational canary preflight keeps pipeline disabled",
        default_disable_action="no_new_leases",
        metadata={"purpose": "operational_canary_preflight", **config.metadata},
    )
    return {
        "ok": not errors,
        "errors": errors,
        "active": active,
        "eligible_case_available": eligible_case is not None,
        "eligible_case": _eligible_case_summary(eligible_case),
        "control": control,
        "protected_counts": protected_counts(conn, config.protected_tables),
    }


def build_operational_case_selection_policy(config: OperationalCanaryConfig) -> CaseSelectionPolicy:
    return CaseSelectionPolicy(
        forecast_timestamp=config.forecast_timestamp,
        lease_duration_seconds=config.lease_duration_seconds,
        skip_existing_ads_predictions=config.skip_existing_ads_predictions,
        metadata={
            "purpose": "ads_operational_canary",
            "max_cases": config.max_cases,
            "skip_existing_ads_predictions": config.skip_existing_ads_predictions,
            **config.metadata,
        },
    )


def _case_selection_policy(config: OperationalCanaryConfig) -> CaseSelectionPolicy:
    return build_operational_case_selection_policy(config)


def _eligible_case_summary(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "market_id": candidate["market_id"],
        "case_key": candidate["case_key"],
        "case_id": candidate["case_id"],
        "selected_snapshot_id": candidate["selected_snapshot_id"],
        "selected_snapshot_observed_at": candidate["selected_snapshot_observed_at"],
        "snapshot_age_seconds": candidate["snapshot_age_seconds"],
    }


def run_one_case_canary(
    config: OperationalCanaryConfig,
    handlers: dict[str, Callable[..., Any]],
) -> dict[str, Any]:
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    result_record: dict[str, Any] | None = None
    disable_error: str | None = None
    try:
        preflight = validate_preflight(conn, config, handlers)
        if not preflight["ok"]:
            return {"ok": False, "phase": "preflight", **preflight}
        before = protected_counts(conn, config.protected_tables)
        set_pipeline_enabled(
            conn,
            pipeline_enabled=True,
            desired_runner_mode=config.runner_mode,
            updated_by=config.updated_by,
            reason=config.reason,
            default_disable_action="stop_after_current_case",
            metadata={"purpose": "ads_operational_canary", "max_cases": config.max_cases, **config.metadata},
        )
        stop_policy = "stop_after_current_case" if config.max_cases == 1 else "none"
        policy = PipelineRunnerPolicy(
            runner_mode=config.runner_mode,
            stop_policy=stop_policy,
            max_cases=config.max_cases,
            dependency_gate_mode="calibration_debt_clearance",
            allow_downstream_execution=True,
            allow_forecast_persistence=True,
            retry_backoff_seconds=config.retry_backoff_seconds,
            require_manifest_handoffs=config.require_manifest_handoffs,
        )
        result = run_ads_pipeline_loop(
            conn,
            policy,
            downstream_stage_handlers=handlers,
            case_selection_policy=_case_selection_policy(config),
        )
        result_record = result.to_record()
    finally:
        try:
            set_pipeline_enabled(
                conn,
                pipeline_enabled=False,
                desired_runner_mode=config.runner_mode,
                updated_by=config.updated_by,
                reason="one-case ADS operational canary complete; disabled by harness",
                default_disable_action="no_new_leases",
                metadata={"purpose": "post_operational_canary_disable", **config.metadata},
            )
        except Exception as exc:  # pragma: no cover - reported to operator, original result still useful.
            disable_error = str(exc)

    after = protected_counts(conn, config.protected_tables)
    active_after = active_work_counts(conn)
    control_after = set_pipeline_enabled(
        conn,
        pipeline_enabled=False,
        desired_runner_mode=config.runner_mode,
        updated_by=config.updated_by,
        reason="one-case ADS operational canary postflight verified disabled state",
        default_disable_action="no_new_leases",
        metadata={"purpose": "post_operational_canary_postflight", **config.metadata},
    )
    conn.close()

    errors: list[str] = []
    if result_record is None:
        errors.append("runner did not produce a result")
    else:
        expected_terminal_status = (
            TERMINAL_REASON_STOP_AFTER_CURRENT if config.max_cases == 1 else TERMINAL_REASON_AUTO005_MAX_CASES
        )
        if result_record["terminal_status"] != expected_terminal_status:
            errors.append(f"terminal_status was {result_record['terminal_status']!r}")
        if result_record["case_lease_id"] is None:
            errors.append("no case lease was processed")
        if result_record["completed_stage_count"] != len(ADS_PIPELINE_STAGE_ORDER):
            errors.append("not all ADS stages completed")
    if active_after["active_runs"]:
        errors.append("active ADS pipeline runs remain after canary")
    if active_after["active_leases"]:
        errors.append("active ADS case leases remain after canary")
    deltas = count_deltas(before, after)
    if config.require_scoreable_prediction and deltas.get("market_predictions", 0) != config.max_cases:
        errors.append(f"scoreable canary expected exactly {config.max_cases} market_predictions row(s)")
    if config.require_scoreable_prediction and deltas.get("forecast_decision_records", 0) != config.max_cases:
        errors.append(f"scoreable canary expected exactly {config.max_cases} forecast_decision_records row(s)")
    if control_after["pipeline_enabled"]:
        errors.append("pipeline control state remains enabled after canary")
    if disable_error:
        errors.append(f"failed to disable pipeline in finally block: {disable_error}")

    record = {
        "ok": not errors,
        "phase": "postflight",
        "errors": errors,
        "result": result_record,
        "protected_counts_before": before,
        "protected_counts_after": after,
        "protected_count_deltas": deltas,
        "active_after": active_after,
        "control_after": control_after,
    }
    criteria_report = build_real_runtime_canary_report(
        config.db_path,
        canary_result=record,
        expected_cases=config.max_cases,
        require_scoreable_prediction=config.require_scoreable_prediction,
        require_qdt_model_executed=config.require_qdt_model_executed,
        require_researcher_model_executed=config.require_researcher_model_executed,
        allowed_stage_failure_classes=config.allowed_stage_failure_classes,
    )
    record["real_runtime_canary_report"] = criteria_report
    if config.require_real_runtime_canary_criteria and not criteria_report["ok"]:
        errors.extend(f"real_runtime_canary:{issue}" for issue in criteria_report["issues"])
        record["ok"] = False
        record["errors"] = errors
    return record


def load_handler_factory(spec: str) -> Callable[..., dict[str, Callable[..., Any]]]:
    module_ref, _, attr = spec.partition(":")
    if not module_ref:
        raise PipelineRunnerContractError("handler factory module is required")
    attr = attr or "build_stage_handlers"
    if module_ref.endswith(".py") or "/" in module_ref:
        path = Path(module_ref).expanduser().resolve()
        module_spec = importlib.util.spec_from_file_location(path.stem, path)
        if module_spec is None or module_spec.loader is None:
            raise PipelineRunnerContractError(f"cannot load handler module: {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_ref)
    factory = getattr(module, attr, None)
    if not callable(factory):
        raise PipelineRunnerContractError(f"handler factory is not callable: {spec}")
    return factory


def build_handlers_from_factory(
    factory: Callable[..., dict[str, Callable[..., Any]]],
    config: OperationalCanaryConfig,
) -> dict[str, Callable[..., Any]]:
    handlers = factory(
        db_path=config.db_path,
        runner_mode=config.runner_mode,
        forecast_timestamp=config.forecast_timestamp,
        max_cases=config.max_cases,
        metadata=dict(config.metadata),
        **dict(config.handler_factory_kwargs),
    )
    if not isinstance(handlers, dict):
        raise PipelineRunnerContractError("handler factory must return a dict")
    return handlers
