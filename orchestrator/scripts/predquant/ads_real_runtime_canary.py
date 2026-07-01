"""ADS real-runtime canary criteria and operator report helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predquant.ads_case_selector import CASE_LEASE_TABLE
from predquant.ads_handoff_report import build_handoff_report
from predquant.ads_pipeline_runner import (
    PIPELINE_RUN_TABLE,
    ensure_pipeline_runner_schema,
    read_pipeline_control_state,
)
from predquant.ads_stage_logging import PIPELINE_ERROR_EVENT_TABLE, ensure_stage_logging_schema
from predquant.ads_storage_maintenance import build_storage_maintenance_plan
from predquant.amrg import build_amrg_operator_report
from predquant.calibration_debt import build_calibration_debt_clearance_report
from predquant.sqlite_store import brier_score_report, ensure_schema


REAL_RUNTIME_CANARY_REPORT_SCHEMA_VERSION = "ads-real-runtime-canary-report/v1"
REAL_RUNTIME_CANARY_CRITERIA_SCHEMA_VERSION = "ads-real-runtime-canary-criteria/v1"
REQUIRED_RUNTIME_MODEL_ID = "gpt-5.5-high"
REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS = {
    REQUIRED_RUNTIME_MODEL_ID,
    "openai/gpt-5.5-high",
}
SCAE_PROBABILITY_SOURCE = "SCAE-012.production_forecast_prob"
SCAE_MARKET_PREDICTION_SOURCE = "scae.production_forecast_prob"
DEFAULT_WAL_WARNING_BYTES = 512 * 1024 * 1024
DEFAULT_WAL_BLOCK_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_CASE_WARNING_SECONDS = 30 * 60
DEFAULT_CASE_BLOCK_SECONDS = 60 * 60
MARKET_SOURCE_CLASSES = {
    "market_rules_or_resolution_source",
    "market_price_or_orderbook",
}
UNKNOWN_SOURCE_FAMILY_IDS = {"", "source-family-unknown"}
GENERIC_QDT_LEAF_IDS = {"leaf-source-of-truth", "leaf-direct-evidence", "leaf-resolution-mechanics"}
MEANINGFUL_SNIPPET_MIN_CHARS = 280
EXPANSION_EXHAUSTED_STATUSES = {
    "expansion_exhausted_no_admissible_candidates",
    "expansion_exhausted_transport_unavailable",
}
QDT_UNRESOLVED_DISPATCHABLE_ROLES = {
    "pre_resolution_forecast_driver",
    "current_status",
    "resolution_mechanics",
    "material_unknown",
}
REQUIRED_UNRESOLVED_QDT_COVERAGE_DIMENSIONS = {
    "resolution_mechanics",
    "current_direct_evidence",
    "key_drivers",
    "counterevidence_negative_checks",
    "source_quality",
    "material_unknowns",
    "timing_deadline_constraints",
}
SEARCH_CAP_SKIP_REASON_CODES = {
    "search_call_limit_reached",
    "search_call_cap_zero",
    "skipped_global_case_cap",
    "skipped_leaf_cap",
}
SEARCH_ELAPSED_SKIP_REASON_CODES = {"search_elapsed_budget_exhausted", "skipped_elapsed_budget"}
FORBIDDEN_QDT_FIELD_NAMES = {
    "bayesian_weighting",
    "probability",
    "probability_estimate",
    "probability_yes",
    "probability_no",
    "forecast_probability",
    "production_forecast_prob",
    "fair_value",
    "numeric_weight",
    "bayesian_edge",
    "log_odds_delta",
    "scae_delta",
    "trade_decision",
    "decision_recommendation",
    "final_forecast",
}
FORBIDDEN_QDT_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "bayesian",
    "log_odds",
    "scae_delta",
    "trade_decision",
    "final_forecast",
)
QDT_RUNTIME_STATE_LIVE_ACCEPTED = "live_qdt_call_executed_output_accepted"
QDT_RUNTIME_STATE_LIVE_REJECTED = "live_qdt_call_executed_output_rejected"
QDT_RUNTIME_STATE_DETERMINISTIC = "qdt_fixture_or_deterministic_path"
QDT_LIVE_OUTPUT_REJECTED_EXECUTION_STATUSES = {
    "failed_schema_validation",
    "failed_forbidden_output",
    "failed_forbidden_output_after_repair",
}
RETRIEVAL_STATE_SOURCE_POPULATED_NOT_CERTIFIED = "retrieval_source_populated_but_not_certified"
RETRIEVAL_STATE_CERTIFIED = "retrieval_certified"
RETRIEVAL_STATE_NOT_SOURCE_POPULATED = "retrieval_not_source_populated"
NATIVE_RESEARCH_STATE_EXECUTED_NO_CANDIDATES = "native_research_executed_no_candidates"
NATIVE_RESEARCH_STATE_CANDIDATES_PRESENT = "native_research_candidate_urls_present"
NATIVE_RESEARCH_STATE_NOT_EXECUTED_OR_USEFUL = "native_research_not_executed_or_useful"


def _decode_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _latest_run_id(conn: sqlite3.Connection) -> str | None:
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


def _active_work_counts(conn: sqlite3.Connection) -> dict[str, int]:
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


def _run_row(conn: sqlite3.Connection, pipeline_run_id: str | None) -> dict[str, Any] | None:
    if not pipeline_run_id or not _table_exists(conn, PIPELINE_RUN_TABLE):
        return None
    row = conn.execute(
        f"SELECT * FROM {PIPELINE_RUN_TABLE} WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["stage_order"] = _decode_json(result.get("stage_order"), [])
    result["idle_policy"] = _decode_json(result.get("idle_policy"), {})
    result["metadata"] = _decode_json(result.get("metadata"), {})
    return result


def _run_duration_seconds(run: dict[str, Any] | None) -> float | None:
    if not run or not run.get("started_at") or not run.get("stopped_at"):
        return None
    started = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
    stopped = datetime.fromisoformat(str(run["stopped_at"]).replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if stopped.tzinfo is None:
        stopped = stopped.replace(tzinfo=timezone.utc)
    return max(0.0, (stopped.astimezone(timezone.utc) - started.astimezone(timezone.utc)).total_seconds())


def _stage_error_events(
    conn: sqlite3.Connection,
    pipeline_run_id: str | None,
    *,
    allowed_failure_classes: tuple[str, ...],
) -> dict[str, Any]:
    ensure_stage_logging_schema(conn)
    if not _table_exists(conn, PIPELINE_ERROR_EVENT_TABLE):
        return {
            "count": 0,
            "unexpected_count": 0,
            "events": [],
            "allowed_failure_classes": list(allowed_failure_classes),
        }
    if pipeline_run_id:
        rows = conn.execute(
            f"""
            SELECT error_event_id, stage, failure_class, retryability, safe_message, safe_metadata
            FROM {PIPELINE_ERROR_EVENT_TABLE}
            WHERE pipeline_run_id = ?
            ORDER BY id
            """,
            (pipeline_run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT error_event_id, stage, failure_class, retryability, safe_message, safe_metadata
            FROM {PIPELINE_ERROR_EVENT_TABLE}
            ORDER BY id
            """
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["safe_metadata"] = _decode_json(item.get("safe_metadata"), {})
        item["expected"] = item["failure_class"] in allowed_failure_classes
        events.append(item)
    return {
        "count": len(events),
        "unexpected_count": sum(1 for event in events if not event["expected"]),
        "events": events,
        "allowed_failure_classes": list(allowed_failure_classes),
    }


def _manifest_items(handoff_report: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for stage in handoff_report.get("stages", []):
        for manifest in stage.get("output_manifests", []):
            if manifest.get("resolved") and not manifest.get("non_manifest_ref"):
                items.append(manifest)
    return items


def _load_manifest_payload(manifest: dict[str, Any]) -> dict[str, Any] | None:
    path = manifest.get("path") or manifest.get("artifact_path")
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalized_qdt_key(value: Any) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _forbidden_qdt_field_paths(value: Any, path: str = "qdt") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_qdt_key(key)
            if normalized in FORBIDDEN_QDT_FIELD_NAMES or any(
                fragment in normalized for fragment in FORBIDDEN_QDT_KEY_FRAGMENTS
            ):
                paths.append(f"{path}.{key}")
            paths.extend(_forbidden_qdt_field_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            paths.extend(_forbidden_qdt_field_paths(child, f"{path}[{idx}]"))
    return paths


def _qdt_leaf_requirement_issues(leaf: dict[str, Any]) -> list[str]:
    leaf_id = str(leaf.get("leaf_id") or "unknown-leaf")
    issues: list[str] = []
    required_strings = (
        "leaf_id",
        "leaf_question",
        "leaf_temporal_role",
        "coverage_dimension",
        "research_factor",
        "missingness_interpretation",
    )
    for field in required_strings:
        if not isinstance(leaf.get(field), str) or not str(leaf.get(field)).strip():
            issues.append(f"{leaf_id}:missing_{field}")
    required_lists = (
        "required_evidence_fields",
        "evidence_requirements",
        "classification_targets",
        "forbidden_outputs",
    )
    for field in required_lists:
        if not isinstance(leaf.get(field), list) or not leaf.get(field):
            issues.append(f"{leaf_id}:missing_{field}")
    required_objects = ("research_sufficiency_requirements", "sufficiency_criteria")
    for field in required_objects:
        if not isinstance(leaf.get(field), dict) or not leaf.get(field):
            issues.append(f"{leaf_id}:missing_{field}")
    return issues


def _qdt_end_to_end_quality(payload: dict[str, Any]) -> dict[str, Any]:
    leaves = [
        leaf for leaf in payload.get("required_leaf_questions", [])
        if isinstance(leaf, dict) and isinstance(leaf.get("leaf_id"), str) and leaf.get("leaf_id")
    ]
    leaves_by_id = {str(leaf["leaf_id"]): leaf for leaf in leaves}
    leaf_ids = set(leaves_by_id)
    generic_leaf_ids = sorted(leaf_ids & GENERIC_QDT_LEAF_IDS)
    graph = payload.get("research_coverage_graph") if isinstance(payload.get("research_coverage_graph"), dict) else {}
    market_temporal_state = graph.get("market_temporal_state")
    dispatchable_ids = [
        str(leaf_id)
        for leaf_id in graph.get("dispatchable_pre_resolution_leaf_ids", [])
        if isinstance(leaf_id, str) and leaf_id
    ] if isinstance(graph.get("dispatchable_pre_resolution_leaf_ids"), list) else []
    terminal_ids = [
        str(leaf_id)
        for leaf_id in graph.get("terminal_verification_leaf_ids", [])
        if isinstance(leaf_id, str) and leaf_id
    ] if isinstance(graph.get("terminal_verification_leaf_ids"), list) else []

    question_specificity = (
        payload.get("question_specificity_check")
        if isinstance(payload.get("question_specificity_check"), dict)
        else {}
    )
    research_coverage = (
        payload.get("research_coverage_check")
        if isinstance(payload.get("research_coverage_check"), dict)
        else {}
    )
    coverage_dimensions = [
        str(item)
        for item in (
            research_coverage.get("coverage_dimensions")
            if isinstance(research_coverage.get("coverage_dimensions"), list)
            else graph.get("coverage_dimensions")
            if isinstance(graph.get("coverage_dimensions"), list)
            else []
        )
        if isinstance(item, str) and item
    ]
    required_coverage_dimensions = sorted(
        REQUIRED_UNRESOLVED_QDT_COVERAGE_DIMENSIONS
        if market_temporal_state == "unresolved"
        else set()
    )
    missing_coverage_dimensions = sorted(set(required_coverage_dimensions) - set(coverage_dimensions))
    specificity_passed = question_specificity.get("status") == "passed"
    coverage_passed = research_coverage.get("status") == "passed"
    forbidden_paths = _forbidden_qdt_field_paths(payload)
    missing_requirement_issues = [
        issue for leaf in leaves for issue in _qdt_leaf_requirement_issues(leaf)
    ]

    issues: list[str] = []
    if not specificity_passed:
        issues.append("question_specificity_check_failed")
    if not coverage_passed:
        issues.append("research_coverage_check_failed")
    if generic_leaf_ids:
        issues.append("generic_template_leaf_ids_present")
    if forbidden_paths:
        issues.append("forbidden_qdt_fields_present")
    if missing_requirement_issues:
        issues.append("leaf_requirements_not_meaningful")
    if not leaves:
        issues.append("missing_required_leaf_questions")
    if not graph:
        issues.append("missing_research_coverage_graph")

    unknown_dispatch_ids = sorted(set(dispatchable_ids) - leaf_ids)
    unknown_terminal_ids = sorted(set(terminal_ids) - leaf_ids)
    if unknown_dispatch_ids:
        issues.append("dispatchable_pre_resolution_leaf_ids_reference_unknown_leaves")
    if unknown_terminal_ids:
        issues.append("terminal_verification_leaf_ids_reference_unknown_leaves")

    terminal_not_typed = sorted(
        leaf_id
        for leaf_id in terminal_ids
        if leaf_id in leaves_by_id and leaves_by_id[leaf_id].get("leaf_temporal_role") != "terminal_verification"
    )
    if terminal_not_typed:
        issues.append("terminal_verification_leaf_ids_not_typed_terminal")

    terminal_dispatch_ids = sorted(set(terminal_ids) & set(dispatchable_ids))
    dispatchable_roles = {
        str(leaves_by_id[leaf_id].get("leaf_temporal_role"))
        for leaf_id in dispatchable_ids
        if leaf_id in leaves_by_id
    }
    if market_temporal_state == "unresolved":
        if not dispatchable_ids:
            issues.append("missing_dispatchable_pre_resolution_leaf_ids")
        if terminal_dispatch_ids:
            issues.append("terminal_verification_leaf_dispatched_for_unresolved_market")
        invalid_roles = sorted(dispatchable_roles - QDT_UNRESOLVED_DISPATCHABLE_ROLES)
        if invalid_roles:
            issues.append("invalid_unresolved_dispatchable_leaf_temporal_roles")
        if "pre_resolution_forecast_driver" not in dispatchable_roles:
            issues.append("missing_pre_resolution_forecast_driver_leaf")

    return {
        "ok": not issues,
        "issue_codes": sorted(set(issues)),
        "question_specificity_status": question_specificity.get("status"),
        "research_coverage_status": research_coverage.get("status"),
        "market_temporal_state": market_temporal_state,
        "coverage_dimensions": sorted(set(coverage_dimensions)),
        "required_coverage_dimensions": required_coverage_dimensions,
        "missing_coverage_dimensions": missing_coverage_dimensions,
        "leaf_count": len(leaves),
        "generic_leaf_ids_present": generic_leaf_ids,
        "dispatchable_pre_resolution_leaf_count": len(dispatchable_ids),
        "dispatchable_pre_resolution_leaf_ids": dispatchable_ids,
        "dispatchable_temporal_roles": sorted(dispatchable_roles),
        "terminal_verification_leaf_count": len(terminal_ids),
        "terminal_verification_leaf_ids": terminal_ids,
        "terminal_dispatch_leaf_ids": terminal_dispatch_ids,
        "forbidden_field_paths": forbidden_paths,
        "missing_requirement_issues": missing_requirement_issues,
    }


def _runtime_model_call_performed(runtime: dict[str, Any]) -> bool:
    performed = runtime.get("model_call_performed")
    if performed is not None:
        return performed is True
    return runtime.get("execution_status") in {
        "succeeded",
        "accepted",
        "failed_schema_validation",
        "failed_forbidden_output",
        "failed_forbidden_output_after_repair",
    }


def _live_qdt_runtime_call_executed(runtime: dict[str, Any]) -> bool:
    return (
        runtime.get("resolved_model_id") == REQUIRED_RUNTIME_MODEL_ID
        and runtime.get("mode") == "live"
        and runtime.get("fixture_mode") is False
        and _runtime_model_call_performed(runtime)
    )


def _live_qdt_runtime_call_attempted(runtime: dict[str, Any]) -> bool:
    return (
        runtime.get("resolved_model_id") == REQUIRED_RUNTIME_MODEL_ID
        and runtime.get("mode") == "live"
        and runtime.get("fixture_mode") is False
    )


def _rejected_live_qdt_runtime_call(runtime: dict[str, Any]) -> bool:
    return (
        _live_qdt_runtime_call_executed(runtime)
        and runtime.get("execution_status") in QDT_LIVE_OUTPUT_REJECTED_EXECUTION_STATUSES
    )


def _accepted_live_qdt_result(qdt_result: dict[str, Any]) -> bool:
    return (
        qdt_result.get("adapter_mode") == "decomposer_model_runtime_live"
        and qdt_result.get("runtime_call_ref") not in {None, ""}
        and qdt_result.get("resolved_model_id") == REQUIRED_RUNTIME_MODEL_ID
    )


def qdt_runtime_counters(qdt_evidence: dict[str, Any]) -> dict[str, int]:
    qdt_results = _list_of_dicts(qdt_evidence.get("qdt_results"))
    runtime_results = _list_of_dicts(qdt_evidence.get("runtime_results"))
    live_attempted = [
        runtime
        for runtime in runtime_results
        if _live_qdt_runtime_call_attempted(runtime)
    ]
    live_executed = [runtime for runtime in live_attempted if _runtime_model_call_performed(runtime)]
    live_rejected = [runtime for runtime in live_attempted if _rejected_live_qdt_runtime_call(runtime)]
    live_accepted = [result for result in qdt_results if _accepted_live_qdt_result(result)]
    fixture_or_deterministic = [
        result
        for result in qdt_results
        if not _accepted_live_qdt_result(result)
    ]
    return {
        "qdt_live_model_call_attempted_count": len(live_attempted),
        "qdt_live_model_call_executed_count": len(live_executed),
        "qdt_live_output_schema_rejected_count": len(live_rejected),
        "qdt_live_output_rejected_count": max(0, len(live_executed) - len(live_accepted)),
        "qdt_live_output_accepted_count": len(live_accepted),
        "qdt_fixture_or_deterministic_count": len(fixture_or_deterministic),
    }


def classify_qdt_runtime_state(qdt_evidence: dict[str, Any]) -> str:
    """Classify live QDT execution separately from accepted artifact persistence."""

    counters = qdt_runtime_counters(qdt_evidence)
    if counters["qdt_live_output_accepted_count"]:
        return QDT_RUNTIME_STATE_LIVE_ACCEPTED
    if counters["qdt_live_model_call_executed_count"]:
        return QDT_RUNTIME_STATE_LIVE_REJECTED
    return QDT_RUNTIME_STATE_DETERMINISTIC


def _runtime_reason_codes(qdt_evidence: dict[str, Any]) -> list[str]:
    return sorted(
        {
            code
            for runtime in _list_of_dicts(qdt_evidence.get("runtime_results"))
            for code in _string_list(runtime.get("runtime_reason_codes"))
        }
    )


def build_recent_run_failure_taxonomy(
    *,
    qdt_evidence: dict[str, Any],
    retrieval_evidence: dict[str, Any],
) -> dict[str, Any]:
    qdt_runtime_state = classify_qdt_runtime_state(qdt_evidence)
    counters = qdt_runtime_counters(qdt_evidence)
    source_populated_count = _int_value(retrieval_evidence.get("source_populated_count"))
    native_model_executed_count = _int_value(retrieval_evidence.get("native_research_model_executed_count"))
    native_candidate_url_count = _int_value(retrieval_evidence.get("native_candidate_url_count"))
    if source_populated_count > 0 and not retrieval_evidence.get("live_acceptance_ok"):
        retrieval_state = RETRIEVAL_STATE_SOURCE_POPULATED_NOT_CERTIFIED
    elif retrieval_evidence.get("live_acceptance_ok"):
        retrieval_state = RETRIEVAL_STATE_CERTIFIED
    else:
        retrieval_state = RETRIEVAL_STATE_NOT_SOURCE_POPULATED
    if native_model_executed_count > 0 and native_candidate_url_count == 0:
        native_state = NATIVE_RESEARCH_STATE_EXECUTED_NO_CANDIDATES
    elif native_candidate_url_count > 0:
        native_state = NATIVE_RESEARCH_STATE_CANDIDATES_PRESENT
    else:
        native_state = NATIVE_RESEARCH_STATE_NOT_EXECUTED_OR_USEFUL
    return {
        "schema_version": "ads-recent-run-failure-taxonomy/v1",
        "qdt_runtime_state": qdt_runtime_state,
        **counters,
        "qdt_runtime_execution_statuses": sorted(
            {
                str(runtime.get("execution_status"))
                for runtime in _list_of_dicts(qdt_evidence.get("runtime_results"))
                if runtime.get("execution_status")
            }
        ),
        "qdt_runtime_reason_codes": _runtime_reason_codes(qdt_evidence),
        "retrieval_state": retrieval_state,
        "source_populated_count": source_populated_count,
        "retrieval_live_acceptance_ok": bool(retrieval_evidence.get("live_acceptance_ok")),
        "native_state": native_state,
        "native_research_model_executed_count": native_model_executed_count,
        "native_candidate_url_count": native_candidate_url_count,
    }


def classify_recent_run_failure(report: dict[str, Any]) -> dict[str, Any]:
    return build_recent_run_failure_taxonomy(
        qdt_evidence=report.get("model_runtime_evidence") if isinstance(report.get("model_runtime_evidence"), dict) else {},
        retrieval_evidence=(
            report.get("retrieval_runtime_evidence")
            if isinstance(report.get("retrieval_runtime_evidence"), dict)
            else {}
        ),
    )


def _model_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    qdt_manifests = [item for item in manifests if item.get("artifact_type") == "question-decomposition"]
    runtime_manifests = [item for item in manifests if item.get("artifact_type") == "model-runtime-call"]
    qdt_results = []
    runtime_results = []
    for manifest in qdt_manifests:
        payload = _load_manifest_payload(manifest) or {}
        model_context = (
            payload.get("model_execution_context")
            if isinstance(payload.get("model_execution_context"), dict)
            else {}
        )
        runtime_context = (
            model_context.get("runtime")
            if isinstance(model_context.get("runtime"), dict)
            else {}
        )
        leaf_ids = [
            str(leaf.get("leaf_id"))
            for leaf in payload.get("required_leaf_questions", [])
            if isinstance(leaf, dict) and leaf.get("leaf_id")
        ]
        generic_leaf_ids = sorted(GENERIC_QDT_LEAF_IDS & set(leaf_ids))
        question_specific = bool(leaf_ids) and not bool(generic_leaf_ids)
        quality = _qdt_end_to_end_quality(payload)
        model_runtime_ok = (
            payload.get("adapter_mode") == "decomposer_model_runtime_live"
            and bool(payload.get("runtime_call_ref"))
            and question_specific
        )
        qdt_results.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "adapter_mode": payload.get("adapter_mode"),
                "runtime_call_ref": payload.get("runtime_call_ref"),
                "resolved_model_id": model_context.get("resolved_model_id"),
                "model_call_performed": model_context.get(
                    "model_call_performed",
                    runtime_context.get("model_call_performed"),
                ),
                "model_executed": model_context.get("model_executed", runtime_context.get("model_executed")),
                "execution_status": model_context.get("execution_status", runtime_context.get("execution_status")),
                "leaf_count": len(leaf_ids),
                "generic_leaf_ids_present": generic_leaf_ids,
                "question_specific": question_specific,
                "question_specificity_status": quality["question_specificity_status"],
                "research_coverage_status": quality["research_coverage_status"],
                "market_temporal_state": quality["market_temporal_state"],
                "coverage_dimensions": quality["coverage_dimensions"],
                "required_coverage_dimensions": quality["required_coverage_dimensions"],
                "missing_coverage_dimensions": quality["missing_coverage_dimensions"],
                "dispatchable_pre_resolution_leaf_count": quality["dispatchable_pre_resolution_leaf_count"],
                "terminal_verification_leaf_count": quality["terminal_verification_leaf_count"],
                "forbidden_field_count": len(quality["forbidden_field_paths"]),
                "missing_requirement_issue_count": len(quality["missing_requirement_issues"]),
                "quality_issue_codes": quality["issue_codes"],
                "qdt_quality": quality,
                "qdt_quality_ok": quality["ok"],
                "ok": model_runtime_ok,
            }
        )
    for manifest in runtime_manifests:
        payload = _load_manifest_payload(manifest) or {}
        runtime_results.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "resolved_model_id": payload.get("resolved_model_id"),
                "mode": payload.get("mode"),
                "fixture_mode": payload.get("fixture_mode"),
                "model_call_performed": payload.get("model_call_performed"),
                "model_executed": payload.get("model_executed"),
                "execution_status": payload.get("execution_status"),
                "retry_count": _int_value(payload.get("retry_count")),
                "transport_retry_policy": payload.get("transport_retry_policy")
                if isinstance(payload.get("transport_retry_policy"), dict)
                else {},
                "retry_diagnostics": _list_of_dicts(payload.get("retry_diagnostics")),
                "schema_repair_diagnostics": _list_of_dicts(payload.get("schema_repair_diagnostics")),
                "runtime_reason_codes": [
                    str(code)
                    for code in payload.get("runtime_reason_codes", [])
                    if isinstance(code, str) and code
                ]
                if isinstance(payload.get("runtime_reason_codes"), list)
                else [],
                "ok": (
                    payload.get("resolved_model_id") == REQUIRED_RUNTIME_MODEL_ID
                    and payload.get("mode") == "live"
                    and payload.get("fixture_mode") is False
                    and payload.get("execution_status") in {"succeeded", "accepted"}
                ),
            }
        )
    model_runtime_ok = bool(qdt_results) and all(item["ok"] for item in qdt_results) and bool(runtime_results) and all(
        item["ok"] for item in runtime_results
    )
    qdt_quality_ok = bool(qdt_results) and all(item["qdt_quality_ok"] for item in qdt_results)
    qdt_runtime_evidence = {"qdt_results": qdt_results, "runtime_results": runtime_results}
    qdt_counters = qdt_runtime_counters(qdt_runtime_evidence)
    return {
        "required_model_id": REQUIRED_RUNTIME_MODEL_ID,
        "qdt_count": len(qdt_results),
        "qdt_model_executed_count": sum(1 for item in qdt_results if item["ok"]),
        "qdt_end_to_end_quality_count": sum(1 for item in qdt_results if item["qdt_quality_ok"]),
        "qdt_question_specificity_passed_count": sum(
            1 for item in qdt_results if item["question_specificity_status"] == "passed"
        ),
        "qdt_research_coverage_passed_count": sum(
            1 for item in qdt_results if item["research_coverage_status"] == "passed"
        ),
        "qdt_pre_resolution_dispatchable_count": sum(
            1
            for item in qdt_results
            if item["qdt_quality"]["dispatchable_pre_resolution_leaf_count"] > 0
            and "pre_resolution_forecast_driver" in item["qdt_quality"]["dispatchable_temporal_roles"]
        ),
        "qdt_terminal_verification_gated_count": sum(
            1 for item in qdt_results if not item["qdt_quality"]["terminal_dispatch_leaf_ids"]
        ),
        "qdt_forbidden_field_clean_count": sum(1 for item in qdt_results if item["forbidden_field_count"] == 0),
        "qdt_meaningful_leaf_requirements_count": sum(
            1 for item in qdt_results if item["missing_requirement_issue_count"] == 0
        ),
        "runtime_call_count": len(runtime_results),
        "runtime_call_model_executed_count": sum(1 for item in runtime_results if item["ok"]),
        "qdt_runtime_state": classify_qdt_runtime_state(qdt_runtime_evidence),
        **qdt_counters,
        "qdt_runtime_reason_codes": _runtime_reason_codes(qdt_runtime_evidence),
        "qdt_results": qdt_results,
        "runtime_results": runtime_results,
        "model_runtime_ok": model_runtime_ok,
        "qdt_end_to_end_quality_ok": qdt_quality_ok,
        "ok": model_runtime_ok,
    }


def _researcher_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    sidecar_artifact_types = {"researcher-sidecar", "researcher_sidecar"}
    bundle_artifact_types = {"researcher-swarm-runtime-bundle", "researcher_swarm_runtime_bundle"}
    classification_artifact_types = {
        "leaf-research-barrier",
        "researcher-classification-readiness-block",
        "researcher-classification-production-pilot",
    }
    sidecars = []
    bundles = []
    classifications = []
    for manifest in manifests:
        artifact_type = str(manifest.get("artifact_type") or "")
        payload = _load_manifest_payload(manifest) or {}
        if artifact_type in sidecar_artifact_types or payload.get("artifact_type") == "researcher_sidecar":
            context = payload.get("model_execution_context") if isinstance(payload.get("model_execution_context"), dict) else {}
            runtime = context.get("runtime") if isinstance(context.get("runtime"), dict) else {}
            sidecars.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "resolved_model_id": context.get("resolved_model_id"),
                    "model_executed": runtime.get("model_executed"),
                    "execution_status": runtime.get("execution_status"),
                    "ok": (
                        context.get("resolved_model_id") in REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS
                        and runtime.get("model_executed") is True
                        and runtime.get("execution_status") in {"succeeded", "accepted"}
                    ),
                }
            )
        elif artifact_type in bundle_artifact_types or payload.get("artifact_type") == "researcher_swarm_runtime_bundle":
            leaf_runtime_status = payload.get("leaf_runtime_status") if isinstance(payload.get("leaf_runtime_status"), list) else []
            bundle_ok = bool(leaf_runtime_status) and all(
                isinstance(row, dict)
                and row.get("model_executed") is True
                and row.get("resolved_model_id") in REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS
                for row in leaf_runtime_status
            )
            bundles.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "leaf_runtime_count": len(leaf_runtime_status),
                    "ok": bundle_ok,
                }
            )
        elif artifact_type in classification_artifact_types:
            classifications.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "artifact_type": artifact_type,
                    "classification_status": payload.get("classification_status"),
                    "reason_codes": list(payload.get("reason_codes") or []),
                }
            )
    model_executed_count = sum(1 for item in sidecars if item["ok"]) + sum(1 for item in bundles if item["ok"])
    blocked_statuses = {
        "blocked_until_certified_retrieval",
        "blocked_leaf_research_barrier",
    }
    blocked_non_scoreable = bool(classifications) and all(
        item.get("classification_status") in blocked_statuses for item in classifications
    )
    return {
        "required_model_id": REQUIRED_RUNTIME_MODEL_ID,
        "accepted_researcher_runtime_model_ids": sorted(REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS),
        "sidecar_count": len(sidecars),
        "runtime_bundle_count": len(bundles),
        "model_executed_count": model_executed_count,
        "sidecars": sidecars,
        "runtime_bundles": bundles,
        "classification_artifacts": classifications,
        "blocked_non_scoreable": blocked_non_scoreable,
        "ok": model_executed_count > 0 and all(item["ok"] for item in sidecars) and all(item["ok"] for item in bundles),
    }


def _evidence_refs_from(value: Any) -> set[str]:
    refs: set[str] = set()
    if not isinstance(value, list):
        return refs
    for item in value:
        if isinstance(item, str) and item:
            refs.add(item)
        elif isinstance(item, dict):
            ref = item.get("evidence_ref") or item.get("ref")
            if ref:
                refs.add(str(ref))
    return refs


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _safe_excerpt(value: Any, *, limit: int = 500) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text[:limit]


def summarize_retrieval_transport_diagnostics(packet: dict[str, Any]) -> dict[str, Any]:
    runtime_summary = (
        packet.get("retrieval_runtime_summary")
        if isinstance(packet.get("retrieval_runtime_summary"), dict)
        else {}
    )
    transport = (
        packet.get("ads_retrieval_transport_diagnostics")
        if isinstance(packet.get("ads_retrieval_transport_diagnostics"), dict)
        else {}
    )
    search_failures = _list_of_dicts(transport.get("search_failure_diagnostics"))
    search_skips = _list_of_dicts(transport.get("search_skipped_diagnostics"))
    search_call_count = max(
        _int_value(transport.get("search_call_count")),
        _int_value(runtime_summary.get("browser_search_call_count")),
    )
    search_failure_count = max(_int_value(transport.get("search_failure_count")), len(search_failures))
    search_skipped_count = max(_int_value(transport.get("search_call_skipped_count")), len(search_skips))
    provider_failures = []
    for item in search_failures:
        summary = {
            "leaf_id": item.get("leaf_id"),
            "query_variant_id": item.get("query_variant_id"),
            "reason_code": item.get("reason_code"),
            "error_class": item.get("error_class"),
            "elapsed_seconds": item.get("elapsed_seconds"),
            "return_code": item.get("return_code"),
            "safe_detail_ref": item.get("bounded_log_artifact_ref") or item.get("safe_detail_ref"),
        }
        excerpt = _safe_excerpt(item.get("detail") or item.get("safe_detail_excerpt"))
        if excerpt:
            summary["safe_detail_excerpt"] = excerpt
        provider_failures.append(summary)

    cap_skips = [
        item for item in search_skips if str(item.get("reason_code") or "") in SEARCH_CAP_SKIP_REASON_CODES
    ]
    elapsed_skips = [
        item for item in search_skips if str(item.get("reason_code") or "") in SEARCH_ELAPSED_SKIP_REASON_CODES
    ]
    provenance_rows = _list_of_dicts(packet.get("retrieval_evidence_provenance_slices"))
    claim_attempted_count = 0
    claim_accepted_count = 0
    accepted_claim_family_ids: set[str] = set()
    for row in provenance_rows:
        claim_ids = _string_list(row.get("claim_family_ids")) or _string_list(
            row.get("claim_family_resolution_refs")
        )
        unknown_codes = set(_string_list(row.get("unknown_reason_codes")))
        if claim_ids or "claim_family_unknown_not_counted" in unknown_codes or "claim_extraction_not_attempted" in unknown_codes:
            claim_attempted_count += 1
        if claim_ids:
            claim_accepted_count += 1
            accepted_claim_family_ids.update(claim_ids)

    return {
        "search_call_count": search_call_count,
        "search_succeeded_count": max(0, search_call_count - search_failure_count),
        "search_failure_count": search_failure_count,
        "search_call_skipped_count": search_skipped_count,
        "search_skipped_by_cap_count": len(cap_skips),
        "search_skipped_by_elapsed_budget_count": len(elapsed_skips),
        "search_failure_diagnostics": search_failures,
        "search_skipped_diagnostics": search_skips,
        "provider_failure_summaries": provider_failures,
        "native_research_status": str(
            transport.get("native_research_status")
            or runtime_summary.get("native_research_status")
            or "not_executed"
        ),
        "native_research_call_count": max(
            _int_value(transport.get("native_research_call_count")),
            _int_value(runtime_summary.get("native_research_call_count")),
        ),
        "claim_family_extraction_attempted_count": claim_attempted_count,
        "claim_family_accepted_count": claim_accepted_count,
        "accepted_claim_family_count": len(accepted_claim_family_ids),
        "accepted_claim_family_ids": sorted(accepted_claim_family_ids),
    }


def _expansion_status_counts(packet: dict[str, Any], *, leaf_id: str | None = None) -> dict[str, int]:
    attempts = [
        attempt
        for attempt in _list_of_dicts(packet.get("retrieval_expansion_attempts"))
        if leaf_id is None or str(attempt.get("leaf_id") or "") == leaf_id
    ]
    exhausted = [
        attempt
        for attempt in attempts
        if str(attempt.get("attempt_status") or "") in EXPANSION_EXHAUSTED_STATUSES
        or attempt.get("expansion_exhausted") is True
    ]
    return {
        "expansion_attempt_count": len(attempts),
        "expansion_executed_count": sum(1 for item in attempts if item.get("attempt_status") == "executed"),
        "expansion_exhausted_count": len(exhausted),
        "expansion_exhausted_transport_unavailable_count": sum(
            1 for item in attempts if item.get("attempt_status") == "expansion_exhausted_transport_unavailable"
        ),
        "expansion_exhausted_no_admissible_candidates_count": sum(
            1 for item in attempts if item.get("attempt_status") == "expansion_exhausted_no_admissible_candidates"
        ),
        "planned_not_executed_expansion_count": sum(
            1 for item in attempts if item.get("attempt_status") == "planned_not_executed"
        ),
    }


def summarize_retrieval_gap(
    packet: dict[str, Any],
    *,
    admitted_refs: set[str] | None = None,
) -> dict[str, int]:
    """Return compact counters for ADS live retrieval insufficiency diagnostics."""

    runtime_summary = (
        packet.get("retrieval_runtime_summary")
        if isinstance(packet.get("retrieval_runtime_summary"), dict)
        else {}
    )
    transport = (
        packet.get("ads_retrieval_transport_diagnostics")
        if isinstance(packet.get("ads_retrieval_transport_diagnostics"), dict)
        else {}
    )
    if admitted_refs is None:
        admitted_refs = set()
        for row in _list_of_dicts(packet.get("leaf_retrieval_results")):
            admitted_refs.update(_evidence_refs_from(row.get("admitted_evidence_refs")))
        for row in _list_of_dicts(packet.get("leaf_evidence_dockets")):
            admitted_refs.update(_evidence_refs_from(row.get("admitted_evidence_refs")))

    admitted_chunks = [
        chunk
        for chunk in _list_of_dicts(packet.get("evidence_chunks"))
        if str(chunk.get("evidence_ref") or "") in admitted_refs
    ]
    meaningful_snippet_admitted_count = sum(
        1
        for chunk in admitted_chunks
        if str(chunk.get("excerpt_policy") or "") != "hash_only"
        and _int_value(chunk.get("excerpt_char_count")) >= MEANINGFUL_SNIPPET_MIN_CHARS
    )
    hash_only_admitted_count = sum(
        1 for chunk in admitted_chunks if str(chunk.get("excerpt_policy") or "") == "hash_only"
    )
    short_chunk_admitted_count = sum(
        1
        for chunk in admitted_chunks
        if _int_value(chunk.get("excerpt_char_count")) < MEANINGFUL_SNIPPET_MIN_CHARS
    )
    canonical_fetch_duplicate_count = max(
        _int_value(runtime_summary.get("duplicate_canonical_url_omissions")),
        sum(
            1
            for item in _list_of_dicts(packet.get("omitted_candidates"))
            if "duplicate_canonical_url"
            in [
                str(code)
                for code in (
                    item.get("omission_reason_codes")
                    if isinstance(item.get("omission_reason_codes"), list)
                    else []
                )
                if code
            ]
        ),
    )
    return {
        **_expansion_status_counts(packet),
        "meaningful_snippet_admitted_count": meaningful_snippet_admitted_count,
        "hash_only_admitted_count": hash_only_admitted_count,
        "short_chunk_admitted_count": short_chunk_admitted_count,
        "search_candidates_materialized_count": max(
            len(_list_of_dicts(packet.get("search_candidate_urls"))),
            _int_value(runtime_summary.get("search_candidate_url_count")),
            _int_value(transport.get("search_candidate_url_count")),
        ),
        "canonical_fetch_duplicate_count": canonical_fetch_duplicate_count,
    }


def _known_source_family_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    family_id = value.strip()
    if not family_id or family_id in UNKNOWN_SOURCE_FAMILY_IDS or "unknown" in family_id:
        return None
    return family_id


def _leaf_contexts_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for item in _list_of_dicts(payload.get("leaf_query_contexts")):
        leaf_id = item.get("leaf_id")
        if isinstance(leaf_id, str) and leaf_id:
            contexts[leaf_id] = item
    return contexts


def _selected_evidence_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for result in _list_of_dicts(payload.get("leaf_retrieval_results")):
        selected.extend(_list_of_dicts(result.get("selected_evidence")))
    return selected


def _certified_coverage_family_ids(coverage_slices: list[dict[str, Any]]) -> set[str]:
    family_ids: set[str] = set()
    for coverage in coverage_slices:
        for family_id in coverage.get("independent_source_family_ids", []):
            known = _known_source_family_id(family_id)
            if known:
                family_ids.add(known)
    return family_ids


def _independent_non_market_source_family_ids(
    payload: dict[str, Any],
    coverage_slices: list[dict[str, Any]],
) -> list[str]:
    certified_family_ids = _certified_coverage_family_ids(coverage_slices)
    family_ids: set[str] = set()
    for item in _selected_evidence_items(payload):
        family_id = _known_source_family_id(item.get("source_family_id"))
        source_class = str(item.get("source_class") or "unknown")
        if family_id is None or family_id not in certified_family_ids:
            continue
        if source_class in MARKET_SOURCE_CLASSES or source_class == "unknown":
            continue
        if item.get("counts_toward_breadth") is not True:
            continue
        if item.get("independence_status") not in {"independent", "derived_from_primary"}:
            continue
        family_ids.add(family_id)
    return sorted(family_ids)


def _coverage_requirement_counts(
    payload: dict[str, Any],
    coverage_slices: list[dict[str, Any]],
) -> dict[str, Any]:
    contexts = _leaf_contexts_by_id(payload)
    protected_required = 0
    protected_satisfied = 0
    freshness_required = 0
    freshness_satisfied = 0
    unsatisfied: set[str] = set()
    covered_leaf_ids: set[str] = set()
    for coverage in coverage_slices:
        leaf_id = str(coverage.get("leaf_id") or "")
        if leaf_id:
            covered_leaf_ids.add(leaf_id)
        context = contexts.get(leaf_id, {})
        targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
        codes = {
            str(code)
            for code in coverage.get("unsatisfied_breadth_dimensions", [])
            if isinstance(code, str) and code
        }
        unsatisfied.update(codes)

        protected_target = bool(targets.get("protected_primary_required"))
        protected_status = str(coverage.get("protected_primary_status") or "unknown")
        if protected_target or protected_status not in {"not_required", ""}:
            protected_required += 1
            if protected_status == "satisfied":
                protected_satisfied += 1

        min_fresh_sources = _int_value(targets.get("min_temporally_fresh_sources"))
        if min_fresh_sources > 0 or "freshness" in codes:
            freshness_required += 1
            if coverage.get("fresh_source_count", 0) >= min_fresh_sources and "freshness" not in codes:
                freshness_satisfied += 1
    for leaf_id, context in contexts.items():
        if leaf_id in covered_leaf_ids:
            continue
        targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
        if targets:
            unsatisfied.add("missing_breadth_coverage")
        if targets.get("protected_primary_required"):
            protected_required += 1
            unsatisfied.add("protected_primary_blocked")
        if _int_value(targets.get("min_temporally_fresh_sources")) > 0:
            freshness_required += 1
            unsatisfied.add("freshness")
    return {
        "protected_primary_required_count": protected_required,
        "protected_primary_satisfied_count": protected_satisfied,
        "freshness_required_count": freshness_required,
        "freshness_satisfied_count": freshness_satisfied,
        "coverage_unsatisfied_breadth_dimensions": sorted(unsatisfied),
    }


def phase9_leaf_retrieval_statuses(
    payload: dict[str, Any],
    coverage_slices: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    contexts = _leaf_contexts_by_id(payload)
    results = {
        str(item.get("leaf_id")): item
        for item in _list_of_dicts(payload.get("leaf_retrieval_results"))
        if item.get("leaf_id")
    }
    dockets = {
        str(item.get("leaf_id")): item
        for item in _list_of_dicts(payload.get("leaf_evidence_dockets"))
        if item.get("leaf_id")
    }
    coverages = {
        str(item.get("leaf_id")): item
        for item in (coverage_slices if coverage_slices is not None else _list_of_dicts(payload.get("retrieval_breadth_coverage_slices")))
        if item.get("leaf_id")
    }
    certificates = {
        str(item.get("leaf_id")): item
        for item in _list_of_dicts(payload.get("leaf_research_sufficiency_certificates"))
        if item.get("leaf_id")
    }
    leaf_ids = sorted(set(contexts) | set(results) | set(dockets) | set(coverages) | set(certificates))
    rows: list[dict[str, Any]] = []
    for leaf_id in leaf_ids:
        context = contexts.get(leaf_id, {})
        result = results.get(leaf_id, {})
        docket = dockets.get(leaf_id, {})
        coverage = coverages.get(leaf_id, {})
        certificate = certificates.get(leaf_id, {})
        targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
        selected_refs = sorted(
            {
                str(item.get("evidence_ref"))
                for item in _list_of_dicts(result.get("selected_evidence"))
                if item.get("evidence_ref")
            }
        )
        admitted_refs = sorted(
            _evidence_refs_from(result.get("admitted_evidence_refs"))
            | _evidence_refs_from(docket.get("admitted_evidence_refs"))
        )
        unsatisfied = sorted(
            {
                str(code)
                for code in coverage.get("unsatisfied_breadth_dimensions", [])
                if isinstance(code, str) and code
            }
        )
        protected_required = bool(
            targets.get("protected_primary_required")
            or str(coverage.get("protected_primary_status") or "") not in {"", "not_required"}
        )
        protected_status = str(
            coverage.get("protected_primary_status")
            or ("not_required" if not protected_required else "missing")
        )
        min_fresh_sources = _int_value(targets.get("min_temporally_fresh_sources"))
        fresh_source_count = _int_value(coverage.get("fresh_source_count"))
        freshness_required = min_fresh_sources > 0 or "freshness" in unsatisfied
        if not freshness_required:
            freshness_status = "not_required"
        elif fresh_source_count >= min_fresh_sources and "freshness" not in unsatisfied:
            freshness_status = "satisfied"
        else:
            freshness_status = "blocked"
        source_status = "source_populated" if selected_refs or admitted_refs else "source_missing"
        if certificate.get("status") == "structurally_unanswerable_certified":
            source_status = "structural_unanswerability_certified"
        rows.append(
            {
                "leaf_id": leaf_id,
                "purpose": context.get("purpose"),
                "coverage_dimension": context.get("coverage_dimension"),
                "source_status": source_status,
                "selected_evidence_ref_count": len(selected_refs),
                "admitted_evidence_ref_count": len(admitted_refs),
                "selected_evidence_refs": selected_refs,
                "admitted_evidence_refs": admitted_refs,
                "protected_primary_required": protected_required,
                "protected_primary_status": protected_status,
                "protected_primary_resolution_basis": coverage.get("protected_primary_resolution_basis"),
                "freshness_required": freshness_required,
                "freshness_status": freshness_status,
                "fresh_source_count": fresh_source_count,
                "min_temporally_fresh_sources": min_fresh_sources,
                "freshness_policy": coverage.get("freshness_policy"),
                "source_family_count": _int_value(coverage.get("source_family_count")),
                "claim_family_count": _int_value(coverage.get("claim_family_count")),
                "unsatisfied_breadth_dimensions": unsatisfied,
                "classification_dispatch_allowed": certificate.get("classification_dispatch_allowed") is True,
                "certificate_status": certificate.get("status") or certificate.get("certificate_status"),
                "structural_unanswerability_certified": bool(
                    certificate.get("status") == "structurally_unanswerable_certified"
                    or certificate.get("certificate_status") == "structurally_unanswerable_certified"
                    or coverage.get("structural_unanswerability_proof_ref")
                ),
                **_expansion_status_counts(payload, leaf_id=leaf_id),
            }
        )
    return rows


def _retrieval_blocked_status(
    sufficiency: dict[str, Any],
    outcome_state: dict[str, Any],
) -> bool:
    status = str(sufficiency.get("classification_dispatch_status") or "")
    outcome = str(outcome_state.get("retrieval_outcome") or sufficiency.get("retrieval_outcome") or "")
    return bool(
        status in {"blocked_insufficient_research", "blocked_until_certified"}
        or outcome == "insufficient_evidence"
        or outcome_state.get("terminal_blocked") is True
    )


def _source_collation_acceptance(
    payload: dict[str, Any],
    *,
    real_candidate_count: int,
    fetched_attempt_count: int,
    admitted_ref_count: int,
    meaningful_snippet_admitted_count: int,
    sufficiency: dict[str, Any],
    structural_unanswerability_certified: bool,
    search_candidate_discovery_blocked: bool,
) -> dict[str, Any]:
    coverage_slices = _list_of_dicts(payload.get("retrieval_breadth_coverage_slices"))
    requirement_counts = _coverage_requirement_counts(payload, coverage_slices)
    non_market_family_ids = _independent_non_market_source_family_ids(payload, coverage_slices)
    outcome_state = (
        payload.get("retrieval_outcome_state")
        if isinstance(payload.get("retrieval_outcome_state"), dict)
        else {}
    )

    unmet: list[str] = []
    if real_candidate_count <= 0:
        unmet.append("candidate_discovery")
    if fetched_attempt_count <= 0:
        unmet.append("fetch_attempts")
    if admitted_ref_count <= 0:
        unmet.append("admitted_evidence")
    if admitted_ref_count > 0 and meaningful_snippet_admitted_count <= 0:
        unmet.append("meaningful_snippet")
    if search_candidate_discovery_blocked:
        unmet.append("search_candidate_discovery")
    if not non_market_family_ids:
        unmet.append("independent_non_market_source_family")
    if (
        requirement_counts["protected_primary_required_count"]
        > requirement_counts["protected_primary_satisfied_count"]
    ):
        unmet.append("protected_primary")
    if requirement_counts["freshness_required_count"] > requirement_counts["freshness_satisfied_count"]:
        unmet.append("freshness")
    unmet.extend(f"breadth:{code}" for code in requirement_counts["coverage_unsatisfied_breadth_dimensions"])
    unmet_codes = sorted(set(unmet))
    blocked = _retrieval_blocked_status(sufficiency, outcome_state)
    source_collation_acceptance_met = not unmet_codes and not structural_unanswerability_certified
    return {
        "source_collation_acceptance_met": source_collation_acceptance_met,
        "retrieval_terminal_acceptance_met": (
            source_collation_acceptance_met or structural_unanswerability_certified
        ),
        "blocked_when_acceptance_unmet": bool(unmet_codes and blocked),
        "acceptance_unmet_not_blocked": bool(unmet_codes and not blocked and not structural_unanswerability_certified),
        "acceptance_unmet_dimension_codes": unmet_codes,
        "coverage_slice_count": len(coverage_slices),
        "independent_non_market_source_family_count": len(non_market_family_ids),
        "independent_non_market_source_family_ids": non_market_family_ids,
        **requirement_counts,
    }


def _retrieval_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_packets = []
    for manifest in manifests:
        if manifest.get("artifact_type") != "retrieval-packet":
            continue
        payload = _load_manifest_payload(manifest) or {}
        runtime_summary = payload.get("retrieval_runtime_summary") if isinstance(payload.get("retrieval_runtime_summary"), dict) else {}
        adapter_mode = str(payload.get("adapter_mode") or "")
        structured_market_metadata_pilot = bool(
            adapter_mode == "structured_market_metadata_pilot_retrieval"
            or runtime_summary.get("runtime_mode") == "structured_market_metadata_pilot"
            or runtime_summary.get("structured_market_metadata_pilot") is True
            or (
                isinstance(payload.get("structured_market_metadata_pilot_proof_boundary"), dict)
                and payload["structured_market_metadata_pilot_proof_boundary"].get(
                    "counts_as_real_retrieval_canary_proof"
                )
                is False
            )
        )
        transport = (
            payload.get("ads_retrieval_transport_diagnostics")
            if isinstance(payload.get("ads_retrieval_transport_diagnostics"), dict)
            else {}
        )
        sufficiency = (
            payload.get("research_sufficiency_summary")
            if isinstance(payload.get("research_sufficiency_summary"), dict)
            else {}
        )
        leaf_results = payload.get("leaf_retrieval_results") if isinstance(payload.get("leaf_retrieval_results"), list) else []
        leaf_dockets = payload.get("leaf_evidence_dockets") if isinstance(payload.get("leaf_evidence_dockets"), list) else []
        certificates = (
            payload.get("leaf_research_sufficiency_certificates")
            if isinstance(payload.get("leaf_research_sufficiency_certificates"), list)
            else []
        )
        direct_url_candidates = payload.get("ads_retrieval_direct_url_candidates")
        if not isinstance(direct_url_candidates, list):
            direct_url_candidates = []
        browser_attempts = (
            payload.get("browser_retrieval_attempts")
            if isinstance(payload.get("browser_retrieval_attempts"), list)
            else []
        )
        search_candidate_urls = (
            payload.get("search_candidate_urls")
            if isinstance(payload.get("search_candidate_urls"), list)
            else []
        )
        native_discoveries = (
            payload.get("native_research_candidate_discoveries")
            if isinstance(payload.get("native_research_candidate_discoveries"), list)
            else []
        )
        metadata_classifier_slices = (
            payload.get("source_metadata_classifier_slices")
            if isinstance(payload.get("source_metadata_classifier_slices"), list)
            else []
        )
        metadata_classifier_unavailable = (
            payload.get("source_metadata_classifier_unavailable_diagnostics")
            if isinstance(payload.get("source_metadata_classifier_unavailable_diagnostics"), list)
            else []
        )
        source_attempt_count = sum(
            int(runtime_summary.get(field) or 0)
            for field in (
                "direct_url_attempt_count",
                "browser_attempt_count",
                "native_attempt_count",
                "structured_feed_attempt_count",
            )
        )
        source_attempt_count += int(transport.get("direct_url_candidate_count") or 0)
        source_attempt_count += len(direct_url_candidates)
        direct_url_candidate_count = max(
            len(direct_url_candidates),
            int(transport.get("direct_url_candidate_count") or 0),
        )
        search_candidate_url_count = max(
            len(search_candidate_urls),
            int(runtime_summary.get("search_candidate_url_count") or 0),
            int(transport.get("search_candidate_url_count") or 0),
        )
        native_candidate_url_count = max(
            int(runtime_summary.get("native_candidate_url_count") or 0),
            sum(
                len(item.get("candidate_urls", []))
                for item in native_discoveries
                if isinstance(item, dict) and isinstance(item.get("candidate_urls"), list)
            ),
        )
        fetched_attempt_count = max(
            len(browser_attempts),
            int(runtime_summary.get("direct_url_attempt_count") or 0)
            + int(runtime_summary.get("web_search_attempt_count") or 0),
            int(transport.get("fetched_candidate_count") or 0),
        )
        real_candidate_count = (
            direct_url_candidate_count
            + search_candidate_url_count
            + native_candidate_url_count
        )
        direct_url_capture_executed = bool(
            runtime_summary.get("direct_url_capture_executed") is True
            or transport.get("direct_url_capture_executed") is True
            or direct_url_candidate_count > 0
        )
        if "browser_search_executed" in transport or "browser_search_executed" in runtime_summary:
            browser_search_executed = bool(
                runtime_summary.get("browser_search_executed") is True
                or transport.get("browser_search_executed") is True
            )
        else:
            browser_search_executed = bool(int(transport.get("search_call_count") or 0) > 0)
        native_research_model_executed = bool(
            runtime_summary.get("native_research_model_executed") is True
            or transport.get("native_research_model_executed") is True
            or int(runtime_summary.get("native_research_call_count") or 0) > 0
            or int(transport.get("native_research_call_count") or 0) > 0
        )
        metadata_classifier_assist_executed = bool(
            runtime_summary.get("metadata_classifier_assist_executed") is True
            or metadata_classifier_slices
        )
        direct_url_capture_status = str(
            transport.get("direct_url_capture_status")
            or runtime_summary.get("direct_url_capture_status")
            or ("executed" if direct_url_capture_executed else "not_executed")
        )
        browser_search_status = str(
            transport.get("browser_search_status")
            or runtime_summary.get("browser_search_status")
            or ("executed" if browser_search_executed else "not_executed")
        )
        search_candidate_discovery_status = str(
            transport.get("search_candidate_discovery_status")
            or runtime_summary.get("search_candidate_discovery_status")
            or ("executed_with_candidates" if search_candidate_url_count > 0 else "not_executed")
        )
        search_candidate_discovery_blocked = bool(
            transport.get("search_failure_blocks_sufficiency")
            or runtime_summary.get("search_failure_blocks_sufficiency")
            or browser_search_status == "executed_with_failures"
            or search_candidate_discovery_status
            in {"search_transport_unavailable", "executed_with_failures", "executed_no_candidates"}
        )
        native_research_status = str(
            transport.get("native_research_status")
            or runtime_summary.get("native_research_status")
            or ("executed" if native_research_model_executed else "not_executed")
        )
        metadata_classifier_assist_status = str(
            runtime_summary.get("metadata_classifier_assist_status")
            or (
                "executed"
                if metadata_classifier_assist_executed
                else "unavailable"
                if metadata_classifier_unavailable
                else "not_executed"
            )
        )
        external_source_discovery_proven = bool(
            not structured_market_metadata_pilot
            and real_candidate_count > 0
            and (
                direct_url_capture_executed
                or browser_search_executed
                or native_research_model_executed
            )
        )
        if runtime_summary.get("external_source_discovery_proven") is True:
            external_source_discovery_proven = not structured_market_metadata_pilot
        leaf_result_admitted_refs: set[str] = set()
        selected_refs: set[str] = _evidence_refs_from(payload.get("selected_evidence_refs"))
        for row in leaf_results:
            if not isinstance(row, dict):
                continue
            leaf_result_admitted_refs.update(_evidence_refs_from(row.get("admitted_evidence_refs")))
            selected_refs.update(_evidence_refs_from(row.get("selected_evidence_refs")))
            selected_refs.update(_evidence_refs_from(row.get("selected_evidence")))
        docket_admitted_refs: set[str] = set()
        for row in leaf_dockets:
            if isinstance(row, dict):
                docket_admitted_refs.update(_evidence_refs_from(row.get("admitted_evidence_refs")))
        admitted_refs = set(leaf_result_admitted_refs)
        admitted_refs.update(docket_admitted_refs)
        reported_refs = set(admitted_refs)
        reported_refs.update(selected_refs)
        structural_unanswerable_count = sum(
            1
            for row in [*leaf_results, *certificates]
            if isinstance(row, dict)
            and (
                bool(row.get("structural_unanswerability_acknowledged"))
                or bool(row.get("structural_unanswerability_proof_ref"))
                or row.get("certificate_status") == "structurally_unanswerable_certified"
            )
        )
        structural_unanswerability_certified = (
            bool(leaf_results or certificates)
            and structural_unanswerable_count >= max(1, len(leaf_results))
        )
        dispatch_allowed = sufficiency.get("classification_dispatch_status") == "allowed"
        retrieval_has_real_candidates = real_candidate_count > 0
        retrieval_has_fetch_attempts = fetched_attempt_count > 0
        retrieval_has_admitted_evidence = len(admitted_refs) > 0
        retrieval_gap = summarize_retrieval_gap(payload, admitted_refs=admitted_refs)
        transport_gap = summarize_retrieval_transport_diagnostics(payload)
        leaf_retrieval_statuses = phase9_leaf_retrieval_statuses(payload)
        source_collation_acceptance = _source_collation_acceptance(
            payload,
            real_candidate_count=real_candidate_count,
            fetched_attempt_count=fetched_attempt_count,
            admitted_ref_count=len(admitted_refs),
            meaningful_snippet_admitted_count=int(retrieval_gap["meaningful_snippet_admitted_count"]),
            sufficiency=sufficiency,
            structural_unanswerability_certified=structural_unanswerability_certified,
            search_candidate_discovery_blocked=search_candidate_discovery_blocked,
        )
        source_populated_or_structural_unanswerability = bool(
            (
                retrieval_has_real_candidates
                and retrieval_has_fetch_attempts
                and retrieval_has_admitted_evidence
                and external_source_discovery_proven
            )
            or structural_unanswerability_certified
        )
        retrieval_packets.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "adapter_mode": adapter_mode,
                "runtime_mode": runtime_summary.get("runtime_mode"),
                "classification_dispatch_status": sufficiency.get("classification_dispatch_status"),
                "structured_market_metadata_pilot": structured_market_metadata_pilot,
                "external_source_discovery_proven": external_source_discovery_proven,
                "source_attempt_count": source_attempt_count,
                "direct_url_candidate_count": direct_url_candidate_count,
                "search_candidate_url_count": search_candidate_url_count,
                "native_candidate_url_count": native_candidate_url_count,
                "real_candidate_count": real_candidate_count,
                "fetched_attempt_count": fetched_attempt_count,
                "browser_search_executed": browser_search_executed,
                "browser_search_status": browser_search_status,
                "search_candidate_discovery_status": search_candidate_discovery_status,
                "search_candidate_discovery_blocked": search_candidate_discovery_blocked,
                "direct_url_capture_executed": direct_url_capture_executed,
                "direct_url_capture_status": direct_url_capture_status,
                "native_research_model_executed": native_research_model_executed,
                "native_research_status": native_research_status,
                "metadata_classifier_assist_executed": metadata_classifier_assist_executed,
                "metadata_classifier_assist_status": metadata_classifier_assist_status,
                "metadata_classifier_slice_count": len(metadata_classifier_slices),
                "metadata_classifier_unavailable_count": len(metadata_classifier_unavailable),
                **transport_gap,
                "admitted_evidence_ref_count": len(admitted_refs),
                "leaf_result_admitted_evidence_ref_count": len(leaf_result_admitted_refs),
                "docket_admitted_evidence_ref_count": len(docket_admitted_refs),
                "selected_evidence_ref_count": len(selected_refs),
                "reported_evidence_ref_count": len(reported_refs),
                **retrieval_gap,
                "leaf_retrieval_statuses": leaf_retrieval_statuses,
                "structural_unanswerability_certified": structural_unanswerability_certified,
                "classification_dispatch_allowed": dispatch_allowed,
                "retrieval_has_real_candidates": retrieval_has_real_candidates,
                "retrieval_has_fetch_attempts": retrieval_has_fetch_attempts,
                "retrieval_has_admitted_evidence": retrieval_has_admitted_evidence,
                "source_populated_or_structural_unanswerability": source_populated_or_structural_unanswerability,
                **source_collation_acceptance,
            }
        )
    source_populated_ok = bool(retrieval_packets) and all(
        item["source_populated_or_structural_unanswerability"] for item in retrieval_packets
    )
    live_acceptance_ok = bool(retrieval_packets) and all(
        item["retrieval_terminal_acceptance_met"] and not item["acceptance_unmet_not_blocked"]
        for item in retrieval_packets
    )
    return {
        "retrieval_packet_count": len(retrieval_packets),
        "source_populated_count": sum(
            1 for item in retrieval_packets if item["source_populated_or_structural_unanswerability"]
        ),
        "real_candidate_count": sum(int(item["real_candidate_count"]) for item in retrieval_packets),
        "fetched_attempt_count": sum(int(item["fetched_attempt_count"]) for item in retrieval_packets),
        "admitted_evidence_ref_count": sum(
            int(item["admitted_evidence_ref_count"]) for item in retrieval_packets
        ),
        "expansion_attempt_count": sum(
            int(item["expansion_attempt_count"]) for item in retrieval_packets
        ),
        "expansion_executed_count": sum(
            int(item["expansion_executed_count"]) for item in retrieval_packets
        ),
        "expansion_exhausted_count": sum(
            int(item["expansion_exhausted_count"]) for item in retrieval_packets
        ),
        "expansion_exhausted_transport_unavailable_count": sum(
            int(item["expansion_exhausted_transport_unavailable_count"]) for item in retrieval_packets
        ),
        "expansion_exhausted_no_admissible_candidates_count": sum(
            int(item["expansion_exhausted_no_admissible_candidates_count"]) for item in retrieval_packets
        ),
        "planned_not_executed_expansion_count": sum(
            int(item["planned_not_executed_expansion_count"]) for item in retrieval_packets
        ),
        "meaningful_snippet_admitted_count": sum(
            int(item["meaningful_snippet_admitted_count"]) for item in retrieval_packets
        ),
        "hash_only_admitted_count": sum(int(item["hash_only_admitted_count"]) for item in retrieval_packets),
        "short_chunk_admitted_count": sum(int(item["short_chunk_admitted_count"]) for item in retrieval_packets),
        "search_candidates_materialized_count": sum(
            int(item["search_candidates_materialized_count"]) for item in retrieval_packets
        ),
        "native_candidate_url_count": sum(int(item["native_candidate_url_count"]) for item in retrieval_packets),
        "search_call_count": sum(int(item["search_call_count"]) for item in retrieval_packets),
        "search_succeeded_count": sum(int(item["search_succeeded_count"]) for item in retrieval_packets),
        "search_failure_count": sum(int(item["search_failure_count"]) for item in retrieval_packets),
        "search_call_skipped_count": sum(int(item["search_call_skipped_count"]) for item in retrieval_packets),
        "search_skipped_by_cap_count": sum(
            int(item["search_skipped_by_cap_count"]) for item in retrieval_packets
        ),
        "search_skipped_by_elapsed_budget_count": sum(
            int(item["search_skipped_by_elapsed_budget_count"]) for item in retrieval_packets
        ),
        "provider_failure_summaries": [
            failure
            for item in retrieval_packets
            for failure in item["provider_failure_summaries"]
        ],
        "native_research_statuses": sorted(
            {
                str(item["native_research_status"])
                for item in retrieval_packets
                if item.get("native_research_status")
            }
        ),
        "claim_family_extraction_attempted_count": sum(
            int(item["claim_family_extraction_attempted_count"]) for item in retrieval_packets
        ),
        "claim_family_accepted_count": sum(
            int(item["claim_family_accepted_count"]) for item in retrieval_packets
        ),
        "accepted_claim_family_count": len(
            {
                claim_family_id
                for item in retrieval_packets
                for claim_family_id in item["accepted_claim_family_ids"]
            }
        ),
        "canonical_fetch_duplicate_count": sum(
            int(item["canonical_fetch_duplicate_count"]) for item in retrieval_packets
        ),
        "external_source_discovery_proven_count": sum(
            1 for item in retrieval_packets if item["external_source_discovery_proven"]
        ),
        "structured_market_metadata_pilot_packet_count": sum(
            1 for item in retrieval_packets if item["structured_market_metadata_pilot"]
        ),
        "browser_search_executed_count": sum(
            1 for item in retrieval_packets if item["browser_search_executed"]
        ),
        "direct_url_capture_executed_count": sum(
            1 for item in retrieval_packets if item["direct_url_capture_executed"]
        ),
        "native_research_model_executed_count": sum(
            1 for item in retrieval_packets if item["native_research_model_executed"]
        ),
        "metadata_classifier_assist_executed_count": sum(
            1 for item in retrieval_packets if item["metadata_classifier_assist_executed"]
        ),
        "source_collation_acceptance_proven_count": sum(
            1 for item in retrieval_packets if item["source_collation_acceptance_met"]
        ),
        "blocked_when_acceptance_unmet_count": sum(
            1 for item in retrieval_packets if item["blocked_when_acceptance_unmet"]
        ),
        "acceptance_unmet_not_blocked_count": sum(
            1 for item in retrieval_packets if item["acceptance_unmet_not_blocked"]
        ),
        "independent_non_market_source_family_count": sum(
            int(item["independent_non_market_source_family_count"]) for item in retrieval_packets
        ),
        "protected_primary_required_count": sum(
            int(item["protected_primary_required_count"]) for item in retrieval_packets
        ),
        "protected_primary_satisfied_count": sum(
            int(item["protected_primary_satisfied_count"]) for item in retrieval_packets
        ),
        "freshness_required_count": sum(int(item["freshness_required_count"]) for item in retrieval_packets),
        "freshness_satisfied_count": sum(int(item["freshness_satisfied_count"]) for item in retrieval_packets),
        "classification_dispatch_allowed": any(item["classification_dispatch_allowed"] for item in retrieval_packets),
        "retrieval_packets": retrieval_packets,
        "source_populated_ok": source_populated_ok,
        "live_acceptance_ok": live_acceptance_ok,
        "ok": source_populated_ok and live_acceptance_ok,
    }


def _retry_summary(
    qdt_evidence: dict[str, Any],
    errors: dict[str, Any],
) -> dict[str, Any]:
    error_events = _list_of_dicts(errors.get("events"))
    retryable_events = [event for event in error_events if event.get("retryability") == "retryable"]
    terminal_events = [event for event in error_events if event.get("retryability") == "terminal"]
    qdt_runtime_results = _list_of_dicts(qdt_evidence.get("runtime_results"))
    qdt_retry_diagnostics = [
        event
        for item in qdt_runtime_results
        for event in _list_of_dicts(item.get("retry_diagnostics"))
    ]
    qdt_runtime_retry_count = sum(_int_value(item.get("retry_count")) for item in qdt_runtime_results)
    qdt_retry_attempt_events = [
        event
        for event in qdt_retry_diagnostics
        if event.get("event") in {"local_retry", "retry_scheduled"}
    ]
    qdt_retry_attempt_count = (
        len(qdt_retry_attempt_events) if qdt_retry_diagnostics else qdt_runtime_retry_count
    )
    qdt_retryable_failure_count = (
        sum(
            1
            for event in qdt_retry_diagnostics
            if event.get("failure_retryable") is True
            and event.get("event") in {"local_retry", "retry_scheduled", "retry_exhausted"}
        )
        if qdt_retry_diagnostics
        else qdt_runtime_retry_count
    )
    qdt_terminal_retry_exhausted_count = sum(
        1 for event in qdt_retry_diagnostics if event.get("event") == "retry_exhausted"
    )
    retry_backoff_seconds = []
    retry_policy_refs = []
    for event in retryable_events:
        metadata = event.get("safe_metadata") if isinstance(event.get("safe_metadata"), dict) else {}
        if "retry_after_seconds" in metadata:
            retry_backoff_seconds.append(_int_value(metadata.get("retry_after_seconds")))
        if metadata.get("retry_policy_ref"):
            retry_policy_refs.append(str(metadata["retry_policy_ref"]))
    for event in qdt_retry_attempt_events:
        if isinstance(event.get("backoff_seconds"), (int, float)):
            retry_backoff_seconds.append(event["backoff_seconds"])
        if event.get("retry_policy_ref"):
            retry_policy_refs.append(str(event["retry_policy_ref"]))
    components = sorted(
        {
            str(event.get("stage"))
            for event in error_events
            if event.get("stage")
        }
        | (
            {"qdt_model_runtime"}
            if qdt_runtime_retry_count > 0
            else set()
        )
        | {
            str(event.get("component"))
            for event in qdt_retry_diagnostics
            if event.get("component")
        }
    )
    if qdt_terminal_retry_exhausted_count:
        final_retry_outcome = "retry_exhausted"
    elif retryable_events or qdt_runtime_retry_count or qdt_retry_attempt_count:
        final_retry_outcome = "retry_recorded"
    else:
        final_retry_outcome = "no_retries_recorded"
    return {
        "retry_attempt_count": len(retryable_events) + qdt_retry_attempt_count,
        "retryable_failure_count": len(retryable_events) + qdt_retryable_failure_count,
        "non_retryable_failure_count": len(terminal_events),
        "terminal_retry_exhausted_count": qdt_terminal_retry_exhausted_count,
        "stage_retry_scheduled_count": len(retryable_events),
        "qdt_model_transport_retry_count": qdt_runtime_retry_count,
        "retry_backoff_seconds": retry_backoff_seconds,
        "retry_policy_refs": sorted(set(retry_policy_refs)),
        "components": components,
        "final_retry_outcome": final_retry_outcome,
    }


def _metadata_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _run_metadata(run: dict[str, Any] | None) -> dict[str, Any]:
    return _metadata_dict(run.get("metadata")) if isinstance(run, dict) else {}


def _canary_metadata(canary_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(canary_result, dict):
        return {}
    metadata = _metadata_dict(canary_result.get("metadata"))
    if metadata:
        return metadata
    result = _metadata_dict(canary_result.get("result"))
    return _metadata_dict(result.get("metadata"))


def _resolve_live_db_mutation(*metadata_sources: dict[str, Any]) -> str:
    for metadata in metadata_sources:
        if _metadata_dict(metadata).get("live_db_mutation") == "clone_only":
            return "clone_only"
    return "unknown_or_live"


def build_current_audit_gap_summary(
    *,
    qdt_evidence: dict[str, Any],
    retrieval_evidence: dict[str, Any],
    errors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qdt_results = _list_of_dicts(qdt_evidence.get("qdt_results"))
    required_dimensions = sorted(
        {
            dimension
            for result in qdt_results
            for dimension in _string_list(result.get("required_coverage_dimensions"))
        }
    )
    observed_dimensions = sorted(
        {
            dimension
            for result in qdt_results
            for dimension in _string_list(result.get("coverage_dimensions"))
        }
    )
    missing_dimensions = sorted(
        {
            dimension
            for result in qdt_results
            for dimension in _string_list(result.get("missing_coverage_dimensions"))
        }
    )
    per_leaf_blockers = []
    for packet in _list_of_dicts(retrieval_evidence.get("retrieval_packets")):
        for leaf in _list_of_dicts(packet.get("leaf_retrieval_statuses")):
            blockers = []
            if leaf.get("source_status") == "source_missing":
                blockers.append("source_missing")
            if leaf.get("protected_primary_status") not in {None, "", "not_required", "satisfied"}:
                blockers.append("protected_primary")
            if leaf.get("freshness_status") == "blocked":
                blockers.append("freshness")
            blockers.extend(
                f"breadth:{code}"
                for code in _string_list(leaf.get("unsatisfied_breadth_dimensions"))
            )
            blockers.extend(
                f"expansion:{code}"
                for code in (
                    "planned_not_executed_expansion_count",
                    "expansion_exhausted_count",
                    "expansion_exhausted_transport_unavailable_count",
                    "expansion_exhausted_no_admissible_candidates_count",
                )
                if _int_value(leaf.get(code)) > 0
            )
            if blockers:
                per_leaf_blockers.append(
                    {
                        "leaf_id": leaf.get("leaf_id"),
                        "coverage_dimension": leaf.get("coverage_dimension"),
                        "blocker_codes": sorted(set(blockers)),
                    }
                )
    return {
        "schema_version": "ads-current-audit-gap-summary/v1",
        "recent_run_failure_taxonomy": build_recent_run_failure_taxonomy(
            qdt_evidence=qdt_evidence,
            retrieval_evidence=retrieval_evidence,
        ),
        "qdt_required_coverage_dimensions": required_dimensions,
        "qdt_observed_coverage_dimensions": observed_dimensions,
        "qdt_missing_coverage_dimensions": missing_dimensions,
        "search_attempted_count": _int_value(retrieval_evidence.get("search_call_count")),
        "search_succeeded_count": _int_value(retrieval_evidence.get("search_succeeded_count")),
        "search_failed_count": _int_value(retrieval_evidence.get("search_failure_count")),
        "search_skipped_count": _int_value(retrieval_evidence.get("search_call_skipped_count")),
        "search_skipped_by_cap_count": _int_value(retrieval_evidence.get("search_skipped_by_cap_count")),
        "search_skipped_by_elapsed_budget_count": _int_value(
            retrieval_evidence.get("search_skipped_by_elapsed_budget_count")
        ),
        "retry_summary": _retry_summary(qdt_evidence, errors or {}),
        "provider_failure_summaries": _list_of_dicts(retrieval_evidence.get("provider_failure_summaries")),
        "native_research_statuses": _string_list(retrieval_evidence.get("native_research_statuses")),
        "native_research_model_executed_count": _int_value(
            retrieval_evidence.get("native_research_model_executed_count")
        ),
        "meaningful_snippet_admitted_count": _int_value(
            retrieval_evidence.get("meaningful_snippet_admitted_count")
        ),
        "short_chunk_admitted_count": _int_value(retrieval_evidence.get("short_chunk_admitted_count")),
        "hash_only_admitted_count": _int_value(retrieval_evidence.get("hash_only_admitted_count")),
        "claim_family_extraction_attempted_count": _int_value(
            retrieval_evidence.get("claim_family_extraction_attempted_count")
        ),
        "claim_family_accepted_count": _int_value(retrieval_evidence.get("claim_family_accepted_count")),
        "accepted_claim_family_count": _int_value(retrieval_evidence.get("accepted_claim_family_count")),
        "classification_dispatch_allowed": bool(retrieval_evidence.get("classification_dispatch_allowed")),
        "per_leaf_sufficiency_blockers": per_leaf_blockers,
    }


def _scae_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    ledgers = []
    for manifest in manifests:
        if manifest.get("artifact_type") not in {
            "scae-final-ledger",
            "scae-final-probability-ledger",
        }:
            continue
        payload = _load_manifest_payload(manifest) or {}
        delta_refs = payload.get("scae_evidence_delta_candidate_slice_refs")
        if not isinstance(delta_refs, list):
            delta_refs = []
        forecast_validity = str(payload.get("forecast_validity_status") or "unknown")
        valid_forecast = forecast_validity != "invalid_for_forecast"
        ledgers.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "forecast_validity_status": forecast_validity,
                "scoreable_forecast_output": bool(payload.get("scoreable_forecast_output")),
                "scae_evidence_delta_ref_count": len(delta_refs),
                "valid_forecast_requires_delta_refs": valid_forecast,
                "ok": (not valid_forecast) or bool(delta_refs),
            }
        )
    return {
        "ledger_count": len(ledgers),
        "valid_forecast_count": sum(1 for item in ledgers if item["valid_forecast_requires_delta_refs"]),
        "delta_ref_count": sum(int(item["scae_evidence_delta_ref_count"]) for item in ledgers),
        "ledgers": ledgers,
        "ok": all(item["ok"] for item in ledgers),
    }


def _classification_verification_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    verifications = []
    for manifest in manifests:
        if manifest.get("stage") != "classification_verification":
            continue
        payload = _load_manifest_payload(manifest) or {}
        rows = _list_of_dicts(payload.get("research_sufficiency_reconciliation_slices"))
        scae_ready_count = sum(
            1
            for row in rows
            if row.get("reconciled_status") == "scae_ready_high_certainty"
            or row.get("research_sufficiency_reconciliation_status") == "scae_ready_high_certainty"
        )
        verification_status = str(payload.get("verification_status") or "unknown")
        ok = bool(
            verification_status in {"runtime_bundle_scae_ready", "structured_market_metadata_certified"}
            or (rows and scae_ready_count == len(rows))
        )
        verifications.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "verification_status": verification_status,
                "reconciliation_slice_count": len(rows),
                "scae_ready_reconciliation_count": scae_ready_count,
                "ok": ok,
            }
        )
    return {
        "verification_artifact_count": len(verifications),
        "scae_ready_reconciliation_count": sum(
            int(item["scae_ready_reconciliation_count"]) for item in verifications
        ),
        "verifications": verifications,
        "ok": bool(verifications) and all(item["ok"] for item in verifications),
    }


def _forecast_decisions_for_run(conn: sqlite3.Connection, pipeline_run_id: str | None) -> list[dict[str, Any]]:
    if not pipeline_run_id or not _table_exists(conn, "forecast_decision_records"):
        return []
    rows = conn.execute(
        """
        SELECT forecast_decision_id, case_id, case_key, dispatch_id, run_id,
               production_persistence_status, production_forecast_persisted,
               scoreable_forecast_output, writes_market_prediction,
               probability_source, non_scoreable_reason_code
        FROM forecast_decision_records
        WHERE run_id = ?
        ORDER BY id
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _market_predictions_for_decisions(conn: sqlite3.Connection, decision_ids: set[str]) -> list[dict[str, Any]]:
    if not decision_ids or not _table_exists(conn, "market_predictions"):
        return []
    rows = conn.execute(
        """
        SELECT id, market_id, case_key, case_id, dispatch_id, prediction_source,
               prediction_label, prediction_run_id, forecast_artifact_id, metadata
        FROM market_predictions
        ORDER BY id
        """
    ).fetchall()
    matched = []
    for row in rows:
        item = dict(row)
        metadata = _decode_json(item.get("metadata"), {})
        if metadata.get("forecast_decision_id") in decision_ids:
            item["metadata"] = metadata
            matched.append(item)
    return matched


def _prediction_delta_evidence(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str | None,
    canary_result: dict[str, Any] | None,
    expected_cases: int | None,
    expected_forecast_decision_records: int | None,
    expected_market_predictions: int | None,
) -> dict[str, Any]:
    deltas = dict((canary_result or {}).get("protected_count_deltas") or {})
    decisions = _forecast_decisions_for_run(conn, pipeline_run_id)
    decision_ids = {str(row["forecast_decision_id"]) for row in decisions}
    matched_predictions = _market_predictions_for_decisions(conn, decision_ids)
    forecast_delta = deltas.get("forecast_decision_records", len(decisions))
    prediction_delta = deltas.get("market_predictions", len(matched_predictions))
    delta_source = "protected_count_deltas" if deltas else "pipeline_run_records"
    duplicate_keys: dict[str, int] = {}
    for row in matched_predictions:
        key = "|".join(
            str(row.get(field) or "")
            for field in ("market_id", "case_key", "case_id", "dispatch_id")
        )
        duplicate_keys[key] = duplicate_keys.get(key, 0) + 1
    duplicate_prediction_keys = {
        key: count for key, count in duplicate_keys.items() if count > 1
    }
    non_scae_decisions = [
        row["forecast_decision_id"]
        for row in decisions
        if row.get("probability_source") != SCAE_PROBABILITY_SOURCE
    ]
    non_scae_predictions = [
        row["id"]
        for row in matched_predictions
        if row.get("metadata", {}).get("scoreable_prediction_source") != SCAE_MARKET_PREDICTION_SOURCE
    ]
    non_scoreable_prediction_ids = []
    decision_by_id = {row["forecast_decision_id"]: row for row in decisions}
    for row in matched_predictions:
        decision = decision_by_id.get(row.get("metadata", {}).get("forecast_decision_id"))
        if decision and not bool(decision.get("scoreable_forecast_output")):
            non_scoreable_prediction_ids.append(row["id"])
    return {
        "expected_cases": expected_cases,
        "expected_forecast_decision_records": expected_forecast_decision_records,
        "expected_market_predictions": expected_market_predictions,
        "protected_count_deltas": deltas,
        "delta_source": delta_source,
        "forecast_decision_records_delta": forecast_delta,
        "market_predictions_delta": prediction_delta,
        "forecast_decision_records_for_run": len(decisions),
        "market_predictions_for_run_decisions": len(matched_predictions),
        "duplicate_prediction_keys": duplicate_prediction_keys,
        "non_scae_decision_ids": non_scae_decisions,
        "non_scae_prediction_ids": non_scae_predictions,
        "non_scoreable_prediction_ids": non_scoreable_prediction_ids,
        "decision_status_counts": _counts(row.get("production_persistence_status") for row in decisions),
        "non_scoreable_reason_counts": _counts(row.get("non_scoreable_reason_code") for row in decisions),
    }


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "none")
        result[key] = result.get(key, 0) + 1
    return result


def _amrg_reports(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qdt_payloads = [
        _load_manifest_payload(item)
        for item in manifests
        if item.get("artifact_type") == "question-decomposition"
    ]
    qdt_payload = next((payload for payload in qdt_payloads if isinstance(payload, dict)), None)
    reports = []
    for manifest in manifests:
        if manifest.get("artifact_type") not in {"related-live-market-context", "no-related-context-waiver"}:
            continue
        payload = _load_manifest_payload(manifest)
        if not isinstance(payload, dict):
            reports.append({"artifact_id": manifest.get("artifact_id"), "ok": False, "error": "payload_unreadable"})
            continue
        try:
            report = build_amrg_operator_report(payload, question_decomposition=qdt_payload)
            reports.append({"artifact_id": manifest.get("artifact_id"), "ok": True, "report": report})
        except Exception as exc:
            reports.append({"artifact_id": manifest.get("artifact_id"), "ok": False, "error": str(exc)})
    return reports


def _calibration_report(
    db_path: Path,
    *,
    first100_trace_complete: bool,
    trace_manifest_count: int | None,
    tail_slice_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    regime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    protected_component_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    pointer_stability_evidence: dict[str, Any] | None,
    prediction_source: str | None,
    prediction_label: str | None,
    evaluation_cluster_id: str,
) -> dict[str, Any]:
    return build_calibration_debt_clearance_report(
        db_path=db_path,
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


def _criterion(gate: str, ok: bool, *, required: bool = True, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    status = "passed" if ok else ("failed" if required else "skipped")
    return {
        "gate": gate,
        "required": required,
        "status": status,
        "ok": bool(ok or not required),
        "detail": detail or {},
    }


def _first_failing_gate(criteria: list[dict[str, Any]]) -> str | None:
    for item in criteria:
        if item.get("required") and not item.get("ok"):
            return str(item.get("gate"))
    return None


def _build_runtime_criteria(
    *,
    require_qdt_model_executed: bool,
    require_researcher_model_executed: bool,
    require_scoreable_prediction: bool,
    qdt_evidence: dict[str, Any],
    retrieval_evidence: dict[str, Any],
    researcher_evidence: dict[str, Any],
    scae_evidence: dict[str, Any],
    prediction_deltas: dict[str, Any],
    active: dict[str, int],
    handoff_report: dict[str, Any],
    errors: dict[str, Any],
) -> list[dict[str, Any]]:
    researcher_required = bool(
        require_researcher_model_executed or retrieval_evidence.get("classification_dispatch_allowed")
    )
    expected_market_predictions = prediction_deltas.get("expected_market_predictions")
    non_executing_expected = expected_market_predictions == 0 and not require_scoreable_prediction
    return [
        _criterion(
            "qdt_model_executed",
            bool(qdt_evidence.get("ok")),
            required=require_qdt_model_executed,
            detail={
                "qdt_model_executed_count": qdt_evidence.get("qdt_model_executed_count", 0),
                "runtime_call_model_executed_count": qdt_evidence.get("runtime_call_model_executed_count", 0),
                "qdt_live_model_call_attempted_count": qdt_evidence.get(
                    "qdt_live_model_call_attempted_count",
                    0,
                ),
                "qdt_live_model_call_executed_count": qdt_evidence.get(
                    "qdt_live_model_call_executed_count",
                    0,
                ),
                "qdt_live_output_schema_rejected_count": qdt_evidence.get(
                    "qdt_live_output_schema_rejected_count",
                    0,
                ),
                "qdt_live_output_rejected_count": qdt_evidence.get(
                    "qdt_live_output_rejected_count",
                    0,
                ),
                "qdt_live_output_accepted_count": qdt_evidence.get(
                    "qdt_live_output_accepted_count",
                    0,
                ),
                "qdt_fixture_or_deterministic_count": qdt_evidence.get(
                    "qdt_fixture_or_deterministic_count",
                    0,
                ),
            },
        ),
        _criterion(
            "qdt_end_to_end_quality",
            bool(qdt_evidence.get("qdt_end_to_end_quality_ok", qdt_evidence.get("ok"))),
            required=require_qdt_model_executed,
            detail={
                "qdt_end_to_end_quality_count": qdt_evidence.get("qdt_end_to_end_quality_count", 0),
                "qdt_question_specificity_passed_count": qdt_evidence.get(
                    "qdt_question_specificity_passed_count",
                    0,
                ),
                "qdt_research_coverage_passed_count": qdt_evidence.get(
                    "qdt_research_coverage_passed_count",
                    0,
                ),
                "qdt_pre_resolution_dispatchable_count": qdt_evidence.get(
                    "qdt_pre_resolution_dispatchable_count",
                    0,
                ),
                "qdt_terminal_verification_gated_count": qdt_evidence.get(
                    "qdt_terminal_verification_gated_count",
                    0,
                ),
                "qdt_forbidden_field_clean_count": qdt_evidence.get("qdt_forbidden_field_clean_count", 0),
                "qdt_meaningful_leaf_requirements_count": qdt_evidence.get(
                    "qdt_meaningful_leaf_requirements_count",
                    0,
                ),
            },
        ),
        _criterion(
            "retrieval_source_populated_or_structural_unanswerability",
            bool(retrieval_evidence.get("source_populated_ok", retrieval_evidence.get("ok"))),
            detail={
                "retrieval_packet_count": retrieval_evidence.get("retrieval_packet_count", 0),
                "source_populated_count": retrieval_evidence.get("source_populated_count", 0),
                "external_source_discovery_proven_count": retrieval_evidence.get(
                    "external_source_discovery_proven_count",
                    0,
                ),
                "structured_market_metadata_pilot_packet_count": retrieval_evidence.get(
                    "structured_market_metadata_pilot_packet_count",
                    0,
                ),
            },
        ),
        _criterion(
            "retrieval_live_acceptance_requirements",
            bool(retrieval_evidence.get("live_acceptance_ok", retrieval_evidence.get("ok"))),
            detail={
                "retrieval_packet_count": retrieval_evidence.get("retrieval_packet_count", 0),
                "source_collation_acceptance_proven_count": retrieval_evidence.get(
                    "source_collation_acceptance_proven_count",
                    0,
                ),
                "blocked_when_acceptance_unmet_count": retrieval_evidence.get(
                    "blocked_when_acceptance_unmet_count",
                    0,
                ),
                "acceptance_unmet_not_blocked_count": retrieval_evidence.get(
                    "acceptance_unmet_not_blocked_count",
                    0,
                ),
                "independent_non_market_source_family_count": retrieval_evidence.get(
                    "independent_non_market_source_family_count",
                    0,
                ),
                "protected_primary_required_count": retrieval_evidence.get("protected_primary_required_count", 0),
                "protected_primary_satisfied_count": retrieval_evidence.get("protected_primary_satisfied_count", 0),
                "freshness_required_count": retrieval_evidence.get("freshness_required_count", 0),
                "freshness_satisfied_count": retrieval_evidence.get("freshness_satisfied_count", 0),
            },
        ),
        _criterion(
            "researcher_model_executed_if_dispatch_allowed",
            bool(researcher_evidence.get("ok")),
            required=researcher_required,
            detail={
                "classification_dispatch_allowed": bool(retrieval_evidence.get("classification_dispatch_allowed")),
                "model_executed_count": researcher_evidence.get("model_executed_count", 0),
                "runtime_bundle_count": researcher_evidence.get("runtime_bundle_count", 0),
            },
        ),
        _criterion(
            "scae_delta_refs_if_valid_forecast",
            bool(scae_evidence.get("ok")),
            detail={
                "valid_forecast_count": scae_evidence.get("valid_forecast_count", 0),
                "delta_ref_count": scae_evidence.get("delta_ref_count", 0),
            },
        ),
        _criterion(
            "no_scoreable_prediction_in_non_executing_mode",
            prediction_deltas.get("market_predictions_delta") == 0,
            required=non_executing_expected,
            detail={
                "expected_market_predictions": expected_market_predictions,
                "market_predictions_delta": prediction_deltas.get("market_predictions_delta"),
            },
        ),
        _criterion(
            "clean_drain",
            not active.get("active_runs") and not active.get("active_leases"),
            detail=dict(active),
        ),
        _criterion(
            "manifest_handoffs_resolved",
            bool(handoff_report.get("ok")),
            detail={
                "unresolved_output_manifest_refs": handoff_report.get("unresolved_output_manifest_refs", []),
            },
        ),
        _criterion(
            "stage_errors_allowed",
            int(errors.get("unexpected_count") or 0) == 0,
            detail={
                "unexpected_count": errors.get("unexpected_count", 0),
                "allowed_failure_classes": errors.get("allowed_failure_classes", []),
            },
        ),
    ]


def build_real_runtime_canary_report(
    db_path: Path | str,
    *,
    canary_result: dict[str, Any] | None = None,
    pipeline_run_id: str | None = None,
    expected_cases: int | None = None,
    expected_forecast_decision_records: int | None = None,
    expected_market_predictions: int | None = None,
    require_qdt_model_executed: bool = True,
    require_researcher_model_executed: bool = False,
    require_scoreable_prediction: bool = False,
    allowed_stage_failure_classes: list[str] | tuple[str, ...] | None = None,
    enforce_pipeline_disabled: bool = True,
    wal_warning_bytes: int = DEFAULT_WAL_WARNING_BYTES,
    wal_block_bytes: int = DEFAULT_WAL_BLOCK_BYTES,
    case_wall_time_warning_seconds: int = DEFAULT_CASE_WARNING_SECONDS,
    case_wall_time_block_seconds: int = DEFAULT_CASE_BLOCK_SECONDS,
    storage_retention_days: int = 90,
    prediction_source: str | None = "ads_pipeline",
    prediction_label: str | None = "v2_scae",
    evaluation_cluster_id: str = "calibration-debt-clearance",
    first100_trace_complete: bool = False,
    trace_manifest_count: int | None = None,
    tail_slice_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    regime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    protected_component_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    pointer_stability_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    expected_cases = expected_cases if expected_cases is not None else _expected_cases_from_result(canary_result)
    if expected_forecast_decision_records is None and expected_cases is not None:
        expected_forecast_decision_records = expected_cases
    if expected_market_predictions is None and expected_cases is not None:
        expected_market_predictions = expected_cases if require_scoreable_prediction else 0
    allowed_failure_classes = tuple(allowed_stage_failure_classes or ())
    resolved_run_id = pipeline_run_id or _pipeline_run_id_from_result(canary_result)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        ensure_pipeline_runner_schema(conn)
        ensure_stage_logging_schema(conn)
        if resolved_run_id is None:
            resolved_run_id = _latest_run_id(conn)
        run = _run_row(conn, resolved_run_id)
        active = _active_work_counts(conn)
        control = read_pipeline_control_state(conn)
        errors = _stage_error_events(conn, resolved_run_id, allowed_failure_classes=allowed_failure_classes)
        prediction_deltas = _prediction_delta_evidence(
            conn,
            pipeline_run_id=resolved_run_id,
            canary_result=canary_result,
            expected_cases=expected_cases,
            expected_forecast_decision_records=expected_forecast_decision_records,
            expected_market_predictions=expected_market_predictions,
        )
    finally:
        conn.close()

    handoff_report = build_handoff_report(path, pipeline_run_id=resolved_run_id) if resolved_run_id else {"ok": False, "error": "no_pipeline_run_id"}
    manifests = _manifest_items(handoff_report)
    qdt_evidence = _model_runtime_evidence(manifests)
    retrieval_evidence = _retrieval_runtime_evidence(manifests)
    researcher_evidence = _researcher_runtime_evidence(manifests)
    verification_evidence = _classification_verification_evidence(manifests)
    scae_evidence = _scae_runtime_evidence(manifests)
    storage = build_storage_maintenance_plan(path, retention_days=storage_retention_days)
    scoring = brier_score_report(path, prediction_source=prediction_source, prediction_label=prediction_label, evaluation_cluster_id=evaluation_cluster_id)
    calibration = _calibration_report(
        path,
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
    run_duration = _run_duration_seconds(run)
    issues: list[str] = []
    warnings: list[str] = []
    if canary_result and canary_result.get("ok") is False:
        issues.append("canary_result_not_ok")
    if active["active_runs"]:
        issues.append("active_ads_pipeline_runs")
    if active["active_leases"]:
        issues.append("active_ads_case_leases")
    if enforce_pipeline_disabled and control.get("pipeline_enabled"):
        issues.append("pipeline_control_enabled_after_canary")
    if not handoff_report.get("ok"):
        issues.append("handoff_report_not_ok")
    if errors["unexpected_count"]:
        issues.append("unexpected_stage_error_events")
    if require_qdt_model_executed and not qdt_evidence["ok"]:
        issues.append("qdt_model_runtime_not_verified")
    if require_qdt_model_executed and not qdt_evidence.get("qdt_end_to_end_quality_ok", qdt_evidence["ok"]):
        issues.append("qdt_end_to_end_quality_not_verified")
    if not retrieval_evidence["source_populated_ok"]:
        issues.append("retrieval_runtime_not_source_populated_or_structurally_unanswerable")
    if not retrieval_evidence["live_acceptance_ok"]:
        issues.append("retrieval_live_acceptance_requirements_not_met")
    if (
        require_researcher_model_executed or retrieval_evidence["classification_dispatch_allowed"]
    ) and not researcher_evidence["ok"]:
        issues.append("researcher_model_runtime_not_verified")
    if not scae_evidence["ok"]:
        issues.append("scae_valid_forecast_missing_evidence_delta_refs")
    _check_prediction_deltas(prediction_deltas, issues)
    _check_resource_gates(
        storage,
        run_duration,
        issues,
        warnings,
        wal_warning_bytes=wal_warning_bytes,
        wal_block_bytes=wal_block_bytes,
        case_wall_time_warning_seconds=case_wall_time_warning_seconds,
        case_wall_time_block_seconds=case_wall_time_block_seconds,
    )
    runtime_criteria = _build_runtime_criteria(
        require_qdt_model_executed=require_qdt_model_executed,
        require_researcher_model_executed=require_researcher_model_executed,
        require_scoreable_prediction=require_scoreable_prediction,
        qdt_evidence=qdt_evidence,
        retrieval_evidence=retrieval_evidence,
        researcher_evidence=researcher_evidence,
        scae_evidence=scae_evidence,
        prediction_deltas=prediction_deltas,
        active=active,
        handoff_report=handoff_report,
        errors=errors,
    )
    first_failing_gate = _first_failing_gate(runtime_criteria)
    retry_summary = _retry_summary(qdt_evidence, errors)
    live_db_mutation = _resolve_live_db_mutation(_canary_metadata(canary_result), _run_metadata(run))
    criteria_summary = {
        "first_failing_gate": first_failing_gate,
        "passed_count": sum(1 for item in runtime_criteria if item.get("status") == "passed"),
        "failed_count": sum(1 for item in runtime_criteria if item.get("status") == "failed"),
        "skipped_count": sum(1 for item in runtime_criteria if item.get("status") == "skipped"),
        "gate_order": [str(item.get("gate")) for item in runtime_criteria],
    }
    phase9_case = _phase9_representative_case(
        run=run,
        qdt_evidence=qdt_evidence,
        retrieval_evidence=retrieval_evidence,
        researcher_evidence=researcher_evidence,
        verification_evidence=verification_evidence,
        scae_evidence=scae_evidence,
        prediction_deltas=prediction_deltas,
        active=active,
        handoff_report=handoff_report,
        errors=errors,
        live_db_mutation=live_db_mutation,
        retry_summary=retry_summary,
    )
    current_audit_gap_summary = build_current_audit_gap_summary(
        qdt_evidence=qdt_evidence,
        retrieval_evidence=retrieval_evidence,
        errors=errors,
    )
    return {
        "schema_version": REAL_RUNTIME_CANARY_REPORT_SCHEMA_VERSION,
        "criteria_schema_version": REAL_RUNTIME_CANARY_CRITERIA_SCHEMA_VERSION,
        "ok": not issues,
        "issues": issues,
        "first_failing_gate": first_failing_gate,
        "warnings": warnings,
        "db_path": str(path),
        "pipeline_run_id": resolved_run_id,
        "criteria": {
            "expected_cases": expected_cases,
            "expected_forecast_decision_records": expected_forecast_decision_records,
            "expected_market_predictions": expected_market_predictions,
            "require_qdt_model_executed": require_qdt_model_executed,
            "require_researcher_model_executed": require_researcher_model_executed,
            "require_scoreable_prediction": require_scoreable_prediction,
            "allowed_stage_failure_classes": list(allowed_failure_classes),
            "wal_warning_bytes": wal_warning_bytes,
            "wal_block_bytes": wal_block_bytes,
            "case_wall_time_warning_seconds": case_wall_time_warning_seconds,
            "case_wall_time_block_seconds": case_wall_time_block_seconds,
            "runtime_gates": runtime_criteria,
            "first_failing_gate": first_failing_gate,
            "summary": criteria_summary,
        },
        "run": run,
        "run_duration_seconds": run_duration,
        "live_db_mutation": live_db_mutation,
        "clone_only": live_db_mutation == "clone_only",
        "retry_summary": retry_summary,
        "recent_run_failure_taxonomy": current_audit_gap_summary["recent_run_failure_taxonomy"],
        "current_audit_gap_summary": current_audit_gap_summary,
        "phase9_representative_case": phase9_case,
        "active_work": active,
        "pipeline_control": control,
        "stage_error_events": errors,
        "handoff_report": handoff_report,
        "amrg_reports": _amrg_reports(manifests),
        "model_runtime_evidence": qdt_evidence,
        "retrieval_runtime_evidence": retrieval_evidence,
        "researcher_runtime_evidence": researcher_evidence,
        "classification_verification_evidence": verification_evidence,
        "scae_runtime_evidence": scae_evidence,
        "prediction_delta_evidence": prediction_deltas,
        "storage_maintenance_plan": storage,
        "brier_score_report": scoring,
        "calibration_debt_report": calibration,
    }


def _expected_cases_from_result(canary_result: dict[str, Any] | None) -> int | None:
    if not canary_result:
        return None
    result = canary_result.get("result")
    if not isinstance(result, dict):
        return None
    return 1 if result.get("case_lease_id") else None


def _pipeline_run_id_from_result(canary_result: dict[str, Any] | None) -> str | None:
    if not canary_result:
        return None
    result = canary_result.get("result")
    if isinstance(result, dict) and result.get("pipeline_run_id"):
        return str(result["pipeline_run_id"])
    return None


def _check_prediction_deltas(evidence: dict[str, Any], issues: list[str]) -> None:
    expected_forecast = evidence.get("expected_forecast_decision_records")
    expected_predictions = evidence.get("expected_market_predictions")
    if (
        expected_forecast is not None
        and evidence.get("forecast_decision_records_delta") != expected_forecast
    ):
        issues.append("forecast_decision_record_delta_mismatch")
    if (
        expected_predictions is not None
        and evidence.get("market_predictions_delta") != expected_predictions
    ):
        issues.append("market_prediction_delta_mismatch")
    if evidence.get("duplicate_prediction_keys"):
        issues.append("duplicate_market_predictions_for_case")
    if evidence.get("non_scae_decision_ids"):
        issues.append("non_scae_forecast_decision_authority")
    if evidence.get("non_scae_prediction_ids"):
        issues.append("non_scae_market_prediction_authority")
    scoreable_predictions_expected = expected_predictions not in (None, 0)
    if evidence.get("non_scoreable_prediction_ids") and not scoreable_predictions_expected:
        issues.append("non_scoreable_decision_wrote_market_prediction")


def _check_resource_gates(
    storage: dict[str, Any],
    run_duration: float | None,
    issues: list[str],
    warnings: list[str],
    *,
    wal_warning_bytes: int,
    wal_block_bytes: int,
    case_wall_time_warning_seconds: int,
    case_wall_time_block_seconds: int,
) -> None:
    wal_size = int(storage.get("wal_size_bytes") or 0)
    if wal_size > wal_block_bytes:
        issues.append("db_wal_growth_block_threshold_exceeded")
    elif wal_size > wal_warning_bytes:
        warnings.append("db_wal_growth_warning_threshold_exceeded")
    if run_duration is None:
        return
    if run_duration > case_wall_time_block_seconds:
        issues.append("case_wall_time_block_threshold_exceeded")
    elif run_duration > case_wall_time_warning_seconds:
        warnings.append("case_wall_time_warning_threshold_exceeded")


def _phase9_representative_case(
    *,
    run: dict[str, Any] | None,
    qdt_evidence: dict[str, Any],
    retrieval_evidence: dict[str, Any],
    researcher_evidence: dict[str, Any],
    verification_evidence: dict[str, Any],
    scae_evidence: dict[str, Any],
    prediction_deltas: dict[str, Any],
    active: dict[str, int],
    handoff_report: dict[str, Any],
    errors: dict[str, Any],
    live_db_mutation: str | None = None,
    retry_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    mutation = live_db_mutation or _resolve_live_db_mutation(_run_metadata(run))
    clone_only = mutation == "clone_only"
    unexpected_blockers = {
        "active_work_not_drained": bool(active.get("active_runs") or active.get("active_leases")),
        "unresolved_handoff_refs": not bool(handoff_report.get("ok")),
        "unexpected_stage_failures": int(errors.get("unexpected_count") or 0) > 0,
        "acceptance_unmet_not_blocked": int(retrieval_evidence.get("acceptance_unmet_not_blocked_count") or 0) > 0,
        "forecast_decision_delta_mismatch": (
            prediction_deltas.get("expected_forecast_decision_records") is not None
            and prediction_deltas.get("forecast_decision_records_delta")
            != prediction_deltas.get("expected_forecast_decision_records")
        ),
        "market_prediction_delta_mismatch": (
            prediction_deltas.get("expected_market_predictions") is not None
            and prediction_deltas.get("market_predictions_delta")
            != prediction_deltas.get("expected_market_predictions")
        ),
        "non_scae_decision_authority": bool(prediction_deltas.get("non_scae_decision_ids")),
        "non_scae_prediction_authority": bool(prediction_deltas.get("non_scae_prediction_ids")),
        "duplicate_market_predictions": bool(prediction_deltas.get("duplicate_prediction_keys")),
    }
    reason_codes.extend(code for code, failed in unexpected_blockers.items() if failed)
    scoreable_requirements = {
        "qdt_quality_passed": bool(qdt_evidence.get("qdt_end_to_end_quality_ok")),
        "retrieval_acceptance_passed": bool(retrieval_evidence.get("live_acceptance_ok")),
        "researcher_model_executed": int(researcher_evidence.get("model_executed_count") or 0) > 0,
        "classification_verification_passed": bool(verification_evidence.get("ok")),
        "scae_valid_forecast_has_delta_refs": (
            int(scae_evidence.get("valid_forecast_count") or 0) > 0
            and int(scae_evidence.get("delta_ref_count") or 0) > 0
            and bool(scae_evidence.get("ok"))
        ),
        "decision_authorized_prediction_persisted": (
            int(prediction_deltas.get("market_predictions_delta") or 0) > 0
            and not prediction_deltas.get("non_scae_decision_ids")
            and not prediction_deltas.get("non_scae_prediction_ids")
        ),
    }
    structural_unanswerability = any(
        packet.get("structural_unanswerability_certified") is True
        for packet in retrieval_evidence.get("retrieval_packets", [])
        if isinstance(packet, dict)
    )
    blocked_non_scoreable = bool(
        int(retrieval_evidence.get("blocked_when_acceptance_unmet_count") or 0) > 0
        or researcher_evidence.get("blocked_non_scoreable") is True
        or (
            int(scae_evidence.get("valid_forecast_count") or 0) == 0
            and int(prediction_deltas.get("market_predictions_delta") or 0) == 0
        )
    )
    if reason_codes:
        classification = "unexpected_failure"
    elif all(scoreable_requirements.values()):
        classification = "scoreable_success"
        reason_codes.append("all_scoreable_runtime_gates_passed")
    elif structural_unanswerability:
        classification = "structural_unanswerability"
        reason_codes.append("retrieval_structural_unanswerability_certified")
    elif blocked_non_scoreable:
        classification = "structured_non_scoreable_insufficiency"
        reason_codes.append("blocked_without_scoreable_prediction")
    else:
        classification = "unexpected_failure"
        reason_codes.append("phase9_outcome_unclassified")
    blocked_case = classification in {
        "structured_non_scoreable_insufficiency",
        "structural_unanswerability",
    }
    return {
        "schema_version": "ads-phase9-representative-case-classification/v1",
        "classification": classification,
        "reason_codes": sorted(set(reason_codes)),
        "clone_only": clone_only,
        "live_db_mutation": mutation,
        "retry_summary": retry_summary or _retry_summary(qdt_evidence, errors),
        "no_scoreable_write_when_blocked": (
            not blocked_case
            or (
                int(prediction_deltas.get("market_predictions_delta") or 0) == 0
                and not prediction_deltas.get("non_scoreable_prediction_ids")
            )
        ),
        "scoreable_success_requirements": scoreable_requirements,
        "unexpected_blockers": unexpected_blockers,
        "reporting_counters": {
            "search_candidates_materialized_count": retrieval_evidence.get(
                "search_candidates_materialized_count",
                0,
            ),
            "expansion_attempt_count": retrieval_evidence.get("expansion_attempt_count", 0),
            "expansion_executed_count": retrieval_evidence.get("expansion_executed_count", 0),
            "expansion_exhausted_count": retrieval_evidence.get("expansion_exhausted_count", 0),
            "meaningful_snippet_admitted_count": retrieval_evidence.get(
                "meaningful_snippet_admitted_count",
                0,
            ),
            "hash_only_admitted_count": retrieval_evidence.get("hash_only_admitted_count", 0),
            "short_chunk_admitted_count": retrieval_evidence.get("short_chunk_admitted_count", 0),
            "protected_primary_required_count": retrieval_evidence.get("protected_primary_required_count", 0),
            "protected_primary_satisfied_count": retrieval_evidence.get("protected_primary_satisfied_count", 0),
            "freshness_required_count": retrieval_evidence.get("freshness_required_count", 0),
            "freshness_satisfied_count": retrieval_evidence.get("freshness_satisfied_count", 0),
            "classification_dispatch_allowed": bool(retrieval_evidence.get("classification_dispatch_allowed")),
            "researcher_model_executed_count": researcher_evidence.get("model_executed_count", 0),
            "classification_verification_artifact_count": verification_evidence.get(
                "verification_artifact_count",
                0,
            ),
            "scae_ready_reconciliation_count": verification_evidence.get(
                "scae_ready_reconciliation_count",
                0,
            ),
            "scae_valid_forecast_count": scae_evidence.get("valid_forecast_count", 0),
            "scae_delta_ref_count": scae_evidence.get("delta_ref_count", 0),
        },
    }


__all__ = [
    "REAL_RUNTIME_CANARY_CRITERIA_SCHEMA_VERSION",
    "REAL_RUNTIME_CANARY_REPORT_SCHEMA_VERSION",
    "build_recent_run_failure_taxonomy",
    "classify_qdt_runtime_state",
    "classify_recent_run_failure",
    "qdt_runtime_counters",
    "build_current_audit_gap_summary",
    "build_real_runtime_canary_report",
    "phase9_leaf_retrieval_statuses",
    "summarize_retrieval_transport_diagnostics",
]
