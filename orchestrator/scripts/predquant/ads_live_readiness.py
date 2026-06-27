"""ADS live-readiness reporting and scheduler gate helpers."""

from __future__ import annotations

import argparse
import json
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from predquant.ads_handoff import ensure_artifact_manifest_schema
from predquant.ads_operational_canary import active_work_counts
from predquant.ads_operator_review import build_ads_operator_review_report
from predquant.ads_pipeline_runner import PIPELINE_RUN_TABLE, ensure_pipeline_runner_schema, read_pipeline_control_state
from predquant.ads_storage_maintenance import build_storage_maintenance_plan
from predquant.calibration_debt import build_calibration_debt_clearance_report
from predquant.sqlite_store import ensure_schema, initialize_database


LIVE_READINESS_SCHEMA_VERSION = "ads-live-readiness-report/v1"
PRODUCTION_READINESS_HANDLER = "predquant.ads_production_readiness_handlers"
PRODUCTION_PILOT_HANDLER = "predquant.ads_production_pilot_handlers"
TRUE_PRODUCTION_HANDLER = "predquant.ads_production_handlers"
PILOT_SCOREABLE_READINESS = "pilot_scoreable_readiness"
TRUE_SCOREABLE_LIVE_READINESS = "true_scoreable_live_readiness"
PILOT_QDT_ADAPTER_MODES = {
    "deterministic_decomposer_contract_adapter",
    "pilot_fixture_decomposer_contract_adapter",
}
PILOT_RESEARCH_INPUT_MODES = {
    "structured_market_metadata_certified",
    "structured_market_metadata_pilot_retrieval",
    "structured_market_metadata_pilot_only",
}
CANARY_HANDLER_MARKERS = (
    "ads_scoreable_canary_handlers",
    "ads_manifest_canary_handlers",
)
DEFAULT_MAX_CALIBRATION_DEBT_CANARY_CASES = 2
SCAE_LEDGER_ARTIFACT_TYPE = "scae-final-probability-ledger"
SCAE_LEDGER_SCHEMA_VERSION = "scae-final-probability-ledger/v1"
SCAE_EVIDENCE_REF_FIELDS = (
    "scae_evidence_delta_candidate_slice_refs",
    "scae_evidence_delta_classification_slice_refs",
    "scae_evidence_delta_direction_verification_slice_refs",
    "scae_evidence_delta_quality_verification_slice_refs",
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


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _latest_pipeline_run_id(conn: sqlite3.Connection) -> str | None:
    if not _table_exists(conn, PIPELINE_RUN_TABLE):
        return None
    row = conn.execute(
        f"""
        SELECT pipeline_run_id
        FROM {PIPELINE_RUN_TABLE}
        ORDER BY COALESCE(stopped_at, started_at) DESC, rowid DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row["pipeline_run_id"]) if row else None


def _scae_delta_refs(payload: dict[str, Any]) -> list[str]:
    refs = []
    for field in SCAE_EVIDENCE_REF_FIELDS:
        refs.extend(str(ref) for ref in _as_list(payload.get(field)) if ref)
    return sorted(set(refs))


def _load_manifest_payload(row: sqlite3.Row) -> dict[str, Any]:
    path = row["artifact_path"] if "artifact_path" in row.keys() else None
    if not path and "path" in row.keys():
        path = row["path"]
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _valid_scae_manifest(row: sqlite3.Row) -> bool:
    artifact_schema_version = (
        row["artifact_schema_version"]
        if "artifact_schema_version" in row.keys()
        else row["schema_version"] if "schema_version" in row.keys() else None
    )
    return (
        row["artifact_type"] == SCAE_LEDGER_ARTIFACT_TYPE
        and artifact_schema_version == SCAE_LEDGER_SCHEMA_VERSION
    )


def _scae_evidence_signal_report(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str | None,
    supplied_refs: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    refs = tuple(str(ref) for ref in (supplied_refs or []) if ref)
    if not pipeline_run_id or not _table_exists(conn, "case_artifact_manifest"):
        return {
            "pipeline_run_id": pipeline_run_id,
            "manifest_ref_count": 0,
            "manifest_scae_evidence_delta_ref_count": 0,
            "accepted_supplied_ref_count": 0,
            "rejected_supplied_refs": list(refs),
            "accepted_supplied_refs": [],
            "current_run_scae_manifest_refs": [],
        }
    rows = conn.execute(
        """
        SELECT *
        FROM case_artifact_manifest
        WHERE pipeline_run_id = ?
        ORDER BY created_at, id
        """,
        (pipeline_run_id,),
    ).fetchall()
    current_by_id = {str(row["artifact_id"]): row for row in rows if row["artifact_id"]}
    scae_rows = [row for row in rows if _valid_scae_manifest(row)]
    manifest_delta_refs: list[str] = []
    scae_manifest_refs = []
    for row in scae_rows:
        payload = _load_manifest_payload(row)
        delta_refs = _scae_delta_refs(payload)
        if delta_refs:
            scae_manifest_refs.append(str(row["artifact_id"]))
            manifest_delta_refs.extend(delta_refs)

    accepted_supplied = []
    rejected_supplied = []
    for ref in refs:
        row = current_by_id.get(ref)
        if row is None or not _valid_scae_manifest(row):
            rejected_supplied.append(ref)
            continue
        payload = _load_manifest_payload(row)
        if not _scae_delta_refs(payload):
            rejected_supplied.append(ref)
            continue
        accepted_supplied.append(ref)

    return {
        "pipeline_run_id": pipeline_run_id,
        "manifest_ref_count": len(scae_manifest_refs),
        "manifest_scae_evidence_delta_ref_count": len(set(manifest_delta_refs)),
        "accepted_supplied_ref_count": len(accepted_supplied),
        "rejected_supplied_refs": rejected_supplied,
        "accepted_supplied_refs": accepted_supplied,
        "current_run_scae_manifest_refs": scae_manifest_refs,
    }


def build_live_readiness_report(
    db_path: Path | str,
    *,
    handler_factory: str | None = None,
    runner_mode: str = "non_executing_canary",
    require_scoreable_live: bool = False,
    scoreable_readiness_mode: str | None = None,
    qdt_adapter_mode: str | None = None,
    researcher_runtime_mode: str | None = None,
    research_input_mode: str | None = None,
    allow_canary_handler: bool = False,
    allow_calibration_debt_scoreable_canary: bool = False,
    requested_max_cases: int | None = None,
    max_calibration_debt_canary_cases: int = DEFAULT_MAX_CALIBRATION_DEBT_CANARY_CASES,
    prediction_source: str | None = "ads_pipeline",
    prediction_label: str | None = "v2_scae",
    evaluation_cluster_id: str = "calibration-debt-clearance",
    first100_trace_complete: bool = False,
    trace_manifest_count: int | None = None,
    tail_slice_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    regime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    protected_component_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    pointer_stability_evidence: dict[str, Any] | None = None,
    amrg_refresh_status: str | None = None,
    scae_evidence_delta_refs: list[str] | tuple[str, ...] | None = None,
    require_fresh_storage_maintenance_plan: bool = False,
    include_operator_review: bool = False,
    operator_review_pipeline_run_id: str | None = None,
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
        ensure_artifact_manifest_schema(conn)
        active = active_work_counts(conn)
        control = read_pipeline_control_state(conn)
        scae_evidence_signals = _scae_evidence_signal_report(
            conn,
            pipeline_run_id=operator_review_pipeline_run_id or _latest_pipeline_run_id(conn),
            supplied_refs=scae_evidence_delta_refs,
        )
    finally:
        conn.close()

    storage = build_storage_maintenance_plan(path, retention_days=storage_retention_days)
    calibration = build_calibration_debt_clearance_report(
        db_path=path,
        first100_trace_complete=first100_trace_complete,
        trace_manifest_count=trace_manifest_count,
        tail_slice_diagnostics=tail_slice_diagnostics,
        regime_diagnostics=regime_diagnostics,
        protected_component_diagnostics=protected_component_diagnostics,
        pointer_stability_evidence=pointer_stability_evidence,
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
            if qdt_adapter_mode in PILOT_QDT_ADAPTER_MODES:
                issues.append("true_scoreable_live_readiness_rejects_pilot_qdt_adapter_mode")
                issues.append("true_production_deterministic_qdt")
            if researcher_runtime_mode == "metadata_only":
                issues.append("true_scoreable_live_readiness_rejects_metadata_only_researcher_context")
                issues.append("true_production_metadata_only_researcher")
            if research_input_mode in PILOT_RESEARCH_INPUT_MODES:
                issues.append("true_scoreable_live_readiness_rejects_structured_market_metadata_only_research_input")
            if not amrg_refresh_status:
                issues.append("missing_amrg_refresh_status_for_promoted_effects")
            if scae_evidence_signals["rejected_supplied_refs"]:
                issues.append("invalid_scae_evidence_delta_refs")
            if (
                not scae_evidence_signals["manifest_scae_evidence_delta_ref_count"]
                and not scae_evidence_signals["accepted_supplied_ref_count"]
            ):
                issues.append("missing_scae_evidence_delta_refs")
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
    candidate_rows = sum(
        int(item.get("candidate_rows", 0))
        for item in storage.get("retention_candidates", [])
        if item.get("exists")
    )
    if require_fresh_storage_maintenance_plan and candidate_rows > 0:
        issues.append("stale_storage_maintenance_plan")

    operator_review = None
    if include_operator_review:
        operator_review = build_ads_operator_review_report(
            path,
            pipeline_run_id=operator_review_pipeline_run_id,
            max_market_snapshot_age_seconds=max_market_snapshot_age_seconds,
            max_resolution_sync_age_seconds=max_resolution_sync_age_seconds,
            storage_retention_days=storage_retention_days,
            prediction_source=prediction_source,
            prediction_label=prediction_label,
            evaluation_cluster_id=evaluation_cluster_id,
        )

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
        "reported_runtime_signals": {
            "qdt_adapter_mode": qdt_adapter_mode,
            "researcher_runtime_mode": researcher_runtime_mode,
            "research_input_mode": research_input_mode,
            "amrg_refresh_status": amrg_refresh_status,
            "scae_evidence_delta_ref_count": (
                scae_evidence_signals["manifest_scae_evidence_delta_ref_count"]
                or scae_evidence_signals["accepted_supplied_ref_count"]
            ),
            "supplied_scae_evidence_delta_ref_count": len(scae_evidence_delta_refs or []),
        },
        "scae_evidence_signal_report": scae_evidence_signals,
        "allow_canary_handler": allow_canary_handler,
        "allow_calibration_debt_scoreable_canary": allow_calibration_debt_scoreable_canary,
        "requested_max_cases": requested_max_cases,
        "max_calibration_debt_canary_cases": max_calibration_debt_canary_cases,
        "health_report": health,
        "active_work": active,
        "pipeline_control": control,
        "storage_maintenance_plan": storage,
        "calibration_debt_report": calibration,
        "operator_review_report": operator_review,
    }


__all__ = [
    "DEFAULT_MAX_CALIBRATION_DEBT_CANARY_CASES",
    "LIVE_READINESS_SCHEMA_VERSION",
    "PILOT_QDT_ADAPTER_MODES",
    "PILOT_RESEARCH_INPUT_MODES",
    "PILOT_SCOREABLE_READINESS",
    "TRUE_SCOREABLE_LIVE_READINESS",
    "build_live_readiness_report",
]
