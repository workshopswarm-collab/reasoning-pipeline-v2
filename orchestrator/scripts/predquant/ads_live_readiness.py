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
CANARY_HANDLER_MARKERS = (
    "ads_scoreable_canary_handlers",
    "ads_manifest_canary_handlers",
)


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
    allow_canary_handler: bool = False,
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
    if require_scoreable_live:
        if module_ref == PRODUCTION_READINESS_HANDLER:
            issues.append("production_readiness_handler_is_non_scoreable")
        if not calibration.get("clears_calibration_debt"):
            issues.append("calibration_debt_not_cleared")
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
        "allow_canary_handler": allow_canary_handler,
        "health_report": health,
        "active_work": active,
        "pipeline_control": control,
        "storage_maintenance_plan": storage,
        "calibration_debt_report": calibration,
    }


__all__ = ["LIVE_READINESS_SCHEMA_VERSION", "build_live_readiness_report"]
