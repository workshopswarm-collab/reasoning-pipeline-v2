"""AUTO-006 durable manual ADS pipeline enablement controls."""

from __future__ import annotations

import sqlite3
from typing import Any

from predquant.ads_pipeline_runner import (
    DEFAULT_DISABLE_ACTIONS,
    PIPELINE_STOP_SIGNAL_SCHEMA_VERSION,
    RUNNER_MODES,
    STOP_POLICIES,
    PipelineRunnerContractError,
    build_pipeline_control_state,
    build_pipeline_stop_signal_record,
    read_pipeline_control_state,
    utc_now_iso,
    write_pipeline_control_state,
    write_pipeline_stop_signal,
)


STOP_SIGNAL_POLICIES = tuple(policy for policy in STOP_POLICIES if policy != "none")
STOP_POLICY_DISABLE_ACTIONS = {
    "stop_before_next_case": "no_new_leases",
    "stop_after_current_case": "stop_after_current_case",
    "safe_drain_now": "safe_drain_now",
}


def get_pipeline_control_state(conn: sqlite3.Connection, *, create_default: bool = True) -> dict[str, Any]:
    """Return the durable ADS pipeline control state, creating the disabled default if needed."""

    return read_pipeline_control_state(conn, create_default=create_default)


def set_pipeline_enabled(
    conn: sqlite3.Connection,
    *,
    pipeline_enabled: bool,
    reason: str,
    updated_by: str = "manual",
    desired_runner_mode: str | None = None,
    default_disable_action: str | None = None,
    acknowledged_by_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Durably enable or disable new ADS pipeline work."""

    if not isinstance(pipeline_enabled, bool):
        raise PipelineRunnerContractError("pipeline_enabled must be boolean")
    current = read_pipeline_control_state(conn)
    record = build_pipeline_control_state(
        pipeline_enabled=pipeline_enabled,
        desired_runner_mode=desired_runner_mode or current["desired_runner_mode"],
        updated_by=updated_by,
        reason=reason,
        default_disable_action=default_disable_action or current["default_disable_action"],
        acknowledged_by_run_id=acknowledged_by_run_id,
        metadata=current["metadata"] if metadata is None else metadata,
    )
    write_pipeline_control_state(conn, record)
    return read_pipeline_control_state(conn)


def build_pipeline_stop_signal(
    *,
    stop_policy: str,
    reason: str,
    requested_by: str = "manual",
    requested_at: str | None = None,
    pipeline_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the structured AUTO-004 stop/drain request stored in control metadata."""

    return build_pipeline_stop_signal_record(
        stop_policy=stop_policy,
        reason=reason,
        requested_by=requested_by,
        requested_at=requested_at or utc_now_iso(),
        pipeline_run_id=pipeline_run_id,
        metadata=metadata,
    )


def request_pipeline_stop(
    conn: sqlite3.Connection,
    *,
    stop_policy: str,
    reason: str,
    requested_by: str = "manual",
    pipeline_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Disable new work and record a structured stop/drain request for the runner."""

    current = read_pipeline_control_state(conn)
    control_metadata = dict(current["metadata"])
    signal = build_pipeline_stop_signal(
        stop_policy=stop_policy,
        reason=reason,
        requested_by=requested_by,
        pipeline_run_id=pipeline_run_id,
        metadata=metadata,
    )
    write_pipeline_stop_signal(conn, signal)
    control_metadata["stop_signal"] = signal
    record = build_pipeline_control_state(
        pipeline_enabled=False,
        desired_runner_mode=current["desired_runner_mode"],
        updated_by=requested_by,
        reason=reason,
        default_disable_action=STOP_POLICY_DISABLE_ACTIONS[stop_policy],
        acknowledged_by_run_id=current["acknowledged_by_run_id"],
        metadata=control_metadata,
    )
    write_pipeline_control_state(conn, record)
    return read_pipeline_control_state(conn)


def acknowledge_pipeline_control_state(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str,
    reason: str = "runner_acknowledged_pipeline_control_state",
    updated_by: str = "system",
) -> dict[str, Any]:
    """Record which runner last acknowledged the current durable control state."""

    current = read_pipeline_control_state(conn)
    record = build_pipeline_control_state(
        pipeline_enabled=current["pipeline_enabled"],
        desired_runner_mode=current["desired_runner_mode"],
        updated_by=updated_by,
        reason=reason,
        default_disable_action=current["default_disable_action"],
        acknowledged_by_run_id=pipeline_run_id,
        metadata=current["metadata"],
    )
    write_pipeline_control_state(conn, record)
    return read_pipeline_control_state(conn)


__all__ = [
    "DEFAULT_DISABLE_ACTIONS",
    "PIPELINE_STOP_SIGNAL_SCHEMA_VERSION",
    "RUNNER_MODES",
    "STOP_SIGNAL_POLICIES",
    "acknowledge_pipeline_control_state",
    "build_pipeline_stop_signal",
    "get_pipeline_control_state",
    "request_pipeline_stop",
    "set_pipeline_enabled",
]
