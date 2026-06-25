"""AUTO-006 durable manual ADS pipeline enablement controls."""

from __future__ import annotations

import sqlite3
from typing import Any

from predquant.ads_pipeline_runner import (
    DEFAULT_DISABLE_ACTIONS,
    RUNNER_MODES,
    PipelineRunnerContractError,
    build_pipeline_control_state,
    read_pipeline_control_state,
    write_pipeline_control_state,
)


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
    "RUNNER_MODES",
    "acknowledge_pipeline_control_state",
    "get_pipeline_control_state",
    "set_pipeline_enabled",
]
