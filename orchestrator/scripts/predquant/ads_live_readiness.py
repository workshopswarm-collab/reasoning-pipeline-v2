"""ADS live-readiness reporting and scheduler gate helpers."""

from __future__ import annotations

import argparse
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from predquant.ads_operational_canary import active_work_counts
from predquant.ads_pipeline_runner import ensure_pipeline_runner_schema, read_pipeline_control_state
from predquant.ads_storage_maintenance import build_storage_maintenance_plan
from predquant.calibration_debt import build_calibration_debt_clearance_report
from predquant.sqlite_store import ensure_schema, initialize_database


LIVE_READINESS_SCHEMA_VERSION = "ads-live-readiness-report/v1"
PRODUCTION_READINESS_HANDLER = "predquant.ads_production_readiness_handlers"
PRODUCTION_PILOT_HANDLER = "predquant.ads_production_pilot_handlers"
TRUE_PRODUCTION_HANDLER = "predquant.ads_production_handlers"
PILOT_SCOREABLE_READINESS = "pilot_scoreable_readiness"
TRUE_SCOREABLE_LIVE_READINESS = "true_scoreable_live_readiness"
CANARY_HANDLER_MARKERS = (
    "ads_scoreable_canary_handlers",
    "ads_manifest_canary_handlers",
)
DEFAULT_MAX_CALIBRATION_DEBT_CANARY_CASES = 2


def _load_health_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "bin" / "check_pipeline_health.py"
    spec = importlib.util.spec_from_file_location("check_pipeline_health", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load health module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _health_args(
    *,
    max_market_snapshot_age_seconds: float,
    max_brier_age_seconds: float,
    max_resolution_sync_age_seconds: float,
) -> argparse.Namespace:
    return SimpleNamespace(
        max_market_snapshot_age_seconds=max_market_snapshot_age_seconds,
        max_brier_age_seconds=max_brier_age_seconds,
        max_resolution_sync_age_seconds=max_resolution_sync_age_seconds,
    )


def _handler_module(handler_factory: str | None) -> str | None:
    if not handler_factory:
        return None
    module_ref, _, _attr = handler_factory.partition(":")
    return module_ref


def build_live_readiness_report(
    db_path: Path | str,
    *,
    handler_factory: str | None = None,
    runner_mode: str = "non_executing_canary",
    require_scoreable_live: bool = False,
    scoreable_readiness_mode: str | None = None,
    allow_canary_handler: bool = False,
    allow_calibration_debt_scoreable_canary: bool = False,
    requested_max_cases: int | None = None,
    max_calibration_debt_canary_cases: int = DEFAULT_MAX_CALIBRATION_DEBT_CANARY_CASES,
    prediction_source: str | None = "ads_pipeline",
    prediction_label: str | None = "v2_scae",
    evaluation_cluster_id: str = "calibration-debt-clearance",
    first100_trace_complete: bool = False,
    trace_manifest_count: int | None = None,
    max_market_snapshot_age_seconds: float = 3600.0,
    max_brier_age_seconds: float = 172800.0,
    max_resolution_sync_age_seconds: float = 5400.0,
    storage_retention_days: int = 90,
    max_storage_retention_candidate_rows: int | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    initialize_database(path)
    health_module = _load_health_module()
    health = health_module.build_report(
        path,
        _health_args(
            max_market_snapshot_age_seconds=max_market_snapshot_age_seconds,
            max_brier_age_seconds=max_brier_age_seconds,
            max_resolution_sync_age_seconds=max_resolution_sync_age_seconds,
        ),
    )
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        ensure_pipeline_runner_schema(conn)
        active = active_work_counts(conn)
        control = read_pipeline_control_state(conn)
    finally:
        conn.close()

    storage = build_storage_maintenance_plan(path, retention_days=storage_retention_days)
    calibration = build_calibration_debt_clearance_report(
        db_path=path,
        first100_trace_complete=first100_trace_complete,
        trace_manifest_count=trace_manifest_count,
        tail_slice_diagnostics=[],
        regime_diagnostics=[],
        protected_component_diagnostics=[],
        pointer_stability_evidence={},
        prediction_source=prediction_source,
        prediction_label=prediction_label,
        evaluation_cluster_id=evaluation_cluster_id,
    )

    module_ref = _handler_module(handler_factory)
    issues: list[str] = []
    if not health.get("ok"):
        issues.extend(f"health:{issue}" for issue in health.get("issues", []))
        if not health.get("issues"):
            issues.append("health:not_ok")
    if active["active_runs"]:
        issues.append("active_ads_pipeline_runs")
    if active["active_leases"]:
        issues.append("active_ads_case_leases")
    if runner_mode == "calibration_debt_production" and not handler_factory:
        issues.append("production_runner_requires_handler_factory")
    if (
        handler_factory
        and not allow_canary_handler
        and any(marker in handler_factory for marker in CANARY_HANDLER_MARKERS)
    ):
        issues.append("canary_handler_factory_not_allowed")
    resolved_scoreable_readiness_mode = scoreable_readiness_mode
    if require_scoreable_live and not resolved_scoreable_readiness_mode:
        resolved_scoreable_readiness_mode = (
            PILOT_SCOREABLE_READINESS
            if allow_calibration_debt_scoreable_canary
            else TRUE_SCOREABLE_LIVE_READINESS
        )
    if resolved_scoreable_readiness_mode not in {None, PILOT_SCOREABLE_READINESS, TRUE_SCOREABLE_LIVE_READINESS}:
        issues.append("unknown_scoreable_readiness_mode")

    if require_scoreable_live:
        if module_ref == PRODUCTION_READINESS_HANDLER:
            issues.append("production_readiness_handler_is_non_scoreable")
        if resolved_scoreable_readiness_mode == TRUE_SCOREABLE_LIVE_READINESS:
            if module_ref == PRODUCTION_PILOT_HANDLER:
                issues.append("true_scoreable_live_readiness_rejects_production_pilot_handler")
            elif module_ref != TRUE_PRODUCTION_HANDLER:
                issues.append("true_scoreable_live_readiness_requires_true_production_handler")
            if allow_calibration_debt_scoreable_canary:
                issues.append("true_scoreable_live_readiness_rejects_calibration_debt_canary_bypass")
        if (
            not calibration.get("clears_calibration_debt")
            and not allow_calibration_debt_scoreable_canary
        ):
            issues.append("calibration_debt_not_cleared")
        if allow_calibration_debt_scoreable_canary and resolved_scoreable_readiness_mode != TRUE_SCOREABLE_LIVE_READINESS:
            if module_ref != PRODUCTION_PILOT_HANDLER:
                issues.append("calibration_debt_scoreable_canary_requires_production_pilot_handler")
            if requested_max_cases is None:
                issues.append("calibration_debt_scoreable_canary_requires_max_cases")
            elif requested_max_cases < 1:
                issues.append("calibration_debt_scoreable_canary_requires_positive_max_cases")
            elif requested_max_cases > max_calibration_debt_canary_cases:
                issues.append("calibration_debt_scoreable_canary_exceeds_case_limit")
    if max_storage_retention_candidate_rows is not None:
        candidate_rows = sum(
            int(item.get("candidate_rows", 0))
            for item in storage.get("retention_candidates", [])
            if item.get("exists")
        )
        if candidate_rows > max_storage_retention_candidate_rows:
            issues.append("storage_retention_candidates_exceed_limit")

    return {
        "schema_version": LIVE_READINESS_SCHEMA_VERSION,
        "ok": not issues,
        "status": "ready" if not issues else "blocked",
        "issues": issues,
        "db_path": str(path),
        "runner_mode": runner_mode,
        "handler_factory": handler_factory,
        "require_scoreable_live": require_scoreable_live,
        "scoreable_readiness_mode": resolved_scoreable_readiness_mode,
        "allow_canary_handler": allow_canary_handler,
        "allow_calibration_debt_scoreable_canary": allow_calibration_debt_scoreable_canary,
        "requested_max_cases": requested_max_cases,
        "max_calibration_debt_canary_cases": max_calibration_debt_canary_cases,
        "health_report": health,
        "active_work": active,
        "pipeline_control": control,
        "storage_maintenance_plan": storage,
        "calibration_debt_report": calibration,
    }


__all__ = [
    "DEFAULT_MAX_CALIBRATION_DEBT_CANARY_CASES",
    "LIVE_READINESS_SCHEMA_VERSION",
    "PILOT_SCOREABLE_READINESS",
    "TRUE_SCOREABLE_LIVE_READINESS",
    "build_live_readiness_report",
]
