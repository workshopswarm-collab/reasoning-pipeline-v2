"""ADS live-market E2E Phase 0 diagnostic taxonomy helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LIVE_MARKET_E2E_PHASE0_SCHEMA_VERSION = "ads-live-market-e2e-phase0-report/v1"
LIVE_MARKET_E2E_PHASE0_TAXONOMY_SCHEMA_VERSION = "ads-live-market-e2e-phase0-taxonomy/v1"

QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE = (
    "qdt_schema_repair_remaining_terminal_temporal_role"
)
BLOCKED_BY_UPSTREAM_QDT = "blocked_by_upstream_qdt"
RETRIEVAL_STAGE_TIMEOUT = "retrieval_stage_timeout"
RETRIEVAL_CHILD_PROCESS_ORPHANED = "retrieval_child_process_orphaned"
ACTIVE_WORK_LEFT_AFTER_TIMEOUT = "active_work_left_after_timeout"
NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK = "not_attempted_due_upstream_block"
UNCLASSIFIED_LIVE_MARKET_FAILURE = "unclassified_live_market_failure"

TERMINAL_TEMPORAL_ROLE_REASON_CODES = {
    "schema_repair_remaining_terminal_temporal_role",
    "terminal_verification_leaf_misclassified",
    "terminal_verification_leaf_misclassified_as_pre_resolution",
    "material_unknown_leaf_role_drift",
}
TERMINAL_STAGE_EVENT_NAMES = {
    "cancelled",
    "completed",
    "error",
    "failed",
    "stage_cancelled",
    "stage_completed",
    "stage_error",
    "stage_failed",
    "stage_timeout",
    "succeeded",
    "timed_out",
    "timeout",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item not in (None, "")]


def _event_stage(event: dict[str, Any]) -> str:
    return str(event.get("stage") or event.get("stage_name") or "")


def _event_name(event: dict[str, Any]) -> str:
    return str(event.get("event") or event.get("event_name") or event.get("status") or "")


def _stage_events(events: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    return [event for event in events if _event_stage(event) == stage]


def _stage_absent(events: list[dict[str, Any]], stage: str) -> bool:
    return not _stage_events(events, stage)


def _stage_started_without_terminal_event(events: list[dict[str, Any]], stage: str) -> bool:
    rows = _stage_events(events, stage)
    if not rows:
        return False
    started = any(_event_name(row) in {"started", "stage_started", "running"} for row in rows)
    terminal = any(_event_name(row) in TERMINAL_STAGE_EVENT_NAMES for row in rows)
    return started and not terminal


def _failed_stage(run: dict[str, Any]) -> str:
    for key in ("failed_stage", "stage_failed", "failed_at_stage", "terminal_stage"):
        if run.get(key):
            return str(run[key])
    metadata = _as_dict(run.get("metadata"))
    for key in ("failed_stage", "stage_failed", "failed_at_stage", "terminal_stage"):
        if metadata.get(key):
            return str(metadata[key])
    return ""


def _runtime_model_called_or_executed(runtime_call: dict[str, Any]) -> bool:
    return runtime_call.get("model_executed") is True or runtime_call.get("model_call_performed") is True


def _schema_repair_attempted(runtime_call: dict[str, Any]) -> bool:
    if _int_value(runtime_call.get("repair_count")) > 0:
        return True
    if "schema_repair_attempted" in _string_list(runtime_call.get("runtime_reason_codes")):
        return True
    return any(item.get("repair_attempted") is True for item in _dicts(runtime_call.get("schema_repair_diagnostics")))


def _remaining_terminal_temporal_role(runtime_call: dict[str, Any]) -> bool:
    reason_codes = set(_string_list(runtime_call.get("runtime_reason_codes")))
    if reason_codes & TERMINAL_TEMPORAL_ROLE_REASON_CODES:
        return True
    if any("terminal_temporal_role" in code for code in reason_codes):
        return True
    for diagnostic in _dicts(runtime_call.get("schema_repair_diagnostics")):
        remaining_counts = _as_dict(diagnostic.get("remaining_error_counts"))
        if _int_value(remaining_counts.get("terminal_temporal_role")) > 0:
            return True
    return False


def _scoreable_write_count(fixture: dict[str, Any]) -> int:
    deltas = _as_dict(fixture.get("protected_write_deltas") or fixture.get("prediction_deltas"))
    return _int_value(deltas.get("forecast_decision_records_delta")) + _int_value(
        deltas.get("market_predictions_delta")
    )


def classify_live_market_audit(
    *,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    runtime_call: dict[str, Any],
    protected_write_deltas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the primary true-live diagnostic without requiring external calls."""

    status_codes: list[str] = []
    stage_statuses: dict[str, str] = {}
    if (
        _runtime_model_called_or_executed(runtime_call)
        and runtime_call.get("execution_status") == "failed_schema_validation"
        and _schema_repair_attempted(runtime_call)
        and _remaining_terminal_temporal_role(runtime_call)
    ):
        status_codes.append(QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE)
        stage_statuses["decomposition"] = QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE

    if _failed_stage(run) == "decomposition" and _stage_absent(events, "retrieval"):
        status_codes.append(BLOCKED_BY_UPSTREAM_QDT)
        stage_statuses["retrieval"] = NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK

    if "decomposition" not in stage_statuses:
        stage_statuses["decomposition"] = UNCLASSIFIED_LIVE_MARKET_FAILURE

    scoreable_write_count = _int_value(_as_dict(protected_write_deltas).get("forecast_decision_records_delta"))
    scoreable_write_count += _int_value(_as_dict(protected_write_deltas).get("market_predictions_delta"))
    return {
        "schema_version": LIVE_MARKET_E2E_PHASE0_TAXONOMY_SCHEMA_VERSION,
        "pipeline_run_id": run.get("pipeline_run_id"),
        "primary_qdt_blocker": stage_statuses["decomposition"],
        "status_codes": sorted(set(status_codes)),
        "stage_statuses": stage_statuses,
        "qdt_runtime_execution_status": runtime_call.get("execution_status"),
        "qdt_runtime_reason_codes": sorted(set(_string_list(runtime_call.get("runtime_reason_codes")))),
        "qdt_schema_repair_attempted": _schema_repair_attempted(runtime_call),
        "scoreable_write_observed": scoreable_write_count > 0,
    }


def classify_partial_retrieval(
    *,
    events: list[dict[str, Any]],
    active_counts: dict[str, Any],
    child_processes: list[dict[str, Any]],
) -> list[str]:
    """Classify a retrieval stage that started but never emitted a terminal event."""

    if not _stage_started_without_terminal_event(events, "retrieval"):
        return []
    status_codes = [RETRIEVAL_STAGE_TIMEOUT]
    if child_processes:
        status_codes.append(RETRIEVAL_CHILD_PROCESS_ORPHANED)
    if _int_value(active_counts.get("active_runs")) or _int_value(active_counts.get("active_leases")):
        status_codes.append(ACTIVE_WORK_LEFT_AFTER_TIMEOUT)
    return status_codes


def classify_downstream_isolation_audit(fixture: dict[str, Any]) -> dict[str, Any]:
    events = _dicts(fixture.get("events"))
    active_counts = _as_dict(fixture.get("active_counts"))
    child_processes = _dicts(fixture.get("child_processes"))
    status_codes = classify_partial_retrieval(
        events=events,
        active_counts=active_counts,
        child_processes=child_processes,
    )
    return {
        "schema_version": LIVE_MARKET_E2E_PHASE0_TAXONOMY_SCHEMA_VERSION,
        "pipeline_run_id": fixture.get("pipeline_run_id"),
        "retrieval_hang_state": RETRIEVAL_STAGE_TIMEOUT if RETRIEVAL_STAGE_TIMEOUT in status_codes else None,
        "status_codes": sorted(set(status_codes)),
        "stage_statuses": {
            "decomposition": "accepted",
            "retrieval": RETRIEVAL_STAGE_TIMEOUT if RETRIEVAL_STAGE_TIMEOUT in status_codes else "unclassified",
        },
        "active_counts": {
            "active_runs": _int_value(active_counts.get("active_runs")),
            "active_leases": _int_value(active_counts.get("active_leases")),
        },
        "child_process_count": len(child_processes),
        "scoreable_write_observed": _scoreable_write_count(fixture) > 0,
    }


def load_live_market_phase0_fixture(path: Path | str) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected fixture JSON object: {path}")
    loaded.setdefault("source_path", str(path))
    return loaded


def build_live_market_phase0_report(
    *,
    primary_fixture: dict[str, Any],
    downstream_fixture: dict[str, Any],
) -> dict[str, Any]:
    primary_run = _as_dict(primary_fixture.get("run"))
    primary_taxonomy = classify_live_market_audit(
        run=primary_run,
        events=_dicts(primary_fixture.get("events")),
        runtime_call=_as_dict(primary_fixture.get("runtime_call")),
        protected_write_deltas=_as_dict(primary_fixture.get("protected_write_deltas")),
    )
    downstream_taxonomy = classify_downstream_isolation_audit(downstream_fixture)
    taxonomy_values = sorted(
        set(primary_taxonomy["status_codes"])
        | set(primary_taxonomy["stage_statuses"].values())
        | set(downstream_taxonomy["status_codes"])
    )
    expected_values = {
        QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE,
        BLOCKED_BY_UPSTREAM_QDT,
        NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK,
        RETRIEVAL_STAGE_TIMEOUT,
        RETRIEVAL_CHILD_PROCESS_ORPHANED,
    }
    missing_values = sorted(expected_values - set(taxonomy_values))
    issues: list[str] = []
    if missing_values:
        issues.append("expected_taxonomy_values_missing")
    if primary_taxonomy["scoreable_write_observed"]:
        issues.append("primary_scoreable_write_observed")
    if downstream_taxonomy["scoreable_write_observed"]:
        issues.append("downstream_scoreable_write_observed")

    return {
        "schema_version": LIVE_MARKET_E2E_PHASE0_SCHEMA_VERSION,
        "ok": not issues,
        "issues": issues,
        "missing_taxonomy_values": missing_values,
        "taxonomy_values": taxonomy_values,
        "primary_true_live": primary_taxonomy,
        "downstream_isolation": downstream_taxonomy,
        "primary_qdt_blocker": primary_taxonomy["primary_qdt_blocker"],
        "downstream_retrieval_hang": downstream_taxonomy["retrieval_hang_state"],
        "scoreable_write_observed": (
            primary_taxonomy["scoreable_write_observed"] or downstream_taxonomy["scoreable_write_observed"]
        ),
    }


__all__ = [
    "ACTIVE_WORK_LEFT_AFTER_TIMEOUT",
    "BLOCKED_BY_UPSTREAM_QDT",
    "LIVE_MARKET_E2E_PHASE0_SCHEMA_VERSION",
    "NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK",
    "QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE",
    "RETRIEVAL_CHILD_PROCESS_ORPHANED",
    "RETRIEVAL_STAGE_TIMEOUT",
    "build_live_market_phase0_report",
    "classify_downstream_isolation_audit",
    "classify_live_market_audit",
    "classify_partial_retrieval",
    "load_live_market_phase0_fixture",
]
