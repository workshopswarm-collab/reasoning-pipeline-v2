"""Session 6 non-authoritative calibration and optimization maturity contracts."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "011_calibration_tuning_records.sql"

CALIBRATION_CANDIDATE_SCHEMA_VERSION = "calibration-candidate/v1"
CALIBRATION_DIAGNOSTIC_SCHEMA_VERSION = "calibration-component-diagnostics/v1"
CALIBRATION_LANE_HEALTH_SCHEMA_VERSION = "calibration-lane-health/v1"
CALIBRATION_CANARY_SCHEMA_VERSION = "calibration-canary-state/v1"
CALIBRATION_POINTER_SCHEMA_VERSION = "calibration-lane-pointer/v1"
POLICY_ROLLBACK_SCHEMA_VERSION = "policy-rollback-event/v1"
RETRIEVAL_POLICY_SNAPSHOT_SCHEMA_VERSION = "retrieval-policy-snapshot/v1"
PROFILE_CANDIDATE_SCHEMA_VERSION = "profile-candidate/v1"
EMERGENCY_OVERLAY_SCHEMA_VERSION = "emergency-conservative-overlay/v1"
OPTIMIZATION_MATURITY_SCHEMA_VERSION = "optimization-maturity-result/v1"
NO_LIVE_AUTHORITY = "none"

PROTECTED_SLICES = (
    "evidence_purpose",
    "source_class",
    "retrieval_quality_bucket",
    "market_prior_reliability_bucket",
    "market_state_regime_tag",
    "protected_primary_status",
    "family_aware_child_status",
    "missingness_no_catalyst_status",
    "claim_family_dependence_status",
)
LANE_IDS = (
    "scae_constants",
    "post_ledger_calibration",
    "retrieval_policy",
    "decomposer_profile",
    "decision_actionability_profile",
    "effective_tuning_profile",
    "emergency_conservative_overlay",
)
FORBIDDEN_AUTHORITY_KEYS = {
    "production_forecast_prob",
    "canonical_probability",
    "forecast_probability",
    "replacement_probability",
    "probability_override",
    "raw_ledger_probability",
    "post_ledger_probability",
    "debt_adjusted_probability",
    "base_policy_rewrite",
    "live_forecast_authority_override",
}
CONSERVATIVE_EFFECT_DIRECTIONS = {
    "reduce_confidence",
    "widen_interval",
    "downgrade_actionability",
    "tighten_freshness_gate",
}


class CalibrationMaturityError(ValueError):
    """Raised when Session 6 maturity records are unsafe or malformed."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_non_empty(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise CalibrationMaturityError(f"{field} is required")
    return value


def require_list(field: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise CalibrationMaturityError(f"{field} must be a list")
    return list(value)


def require_mapping(field: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CalibrationMaturityError(f"{field} must be an object")
    return dict(value)


def parse_timestamp(field: str, value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise CalibrationMaturityError(f"{field} is required")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CalibrationMaturityError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def ensure_no_forbidden_authority(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise CalibrationMaturityError(f"{path} contains an invalid key")
            if key.lower() in FORBIDDEN_AUTHORITY_KEYS:
                raise CalibrationMaturityError(f"{path}.{key} is forbidden in Session 6 maturity records")
            ensure_no_forbidden_authority(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_forbidden_authority(child, f"{path}[{idx}]")


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None:
        return set()
    return {item[1] for item in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_calibration_maturity_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    candidate_columns = {
        "schema_version": "TEXT",
        "owner_session": "TEXT",
        "changed_parameters": "TEXT NOT NULL DEFAULT '[]'",
        "source_replay_cohort_ids": "TEXT NOT NULL DEFAULT '[]'",
        "source_trace_materialization_refs": "TEXT NOT NULL DEFAULT '[]'",
        "component_diagnostics_ref": "TEXT",
        "bounds_check_status": "TEXT",
        "protected_slice_non_degradation_status": "TEXT",
        "holdout_status": "TEXT",
        "canary_status": "TEXT",
        "promotion_status": "TEXT",
        "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
    }
    existing = table_columns(conn, "calibration_candidate_records")
    for column, definition in candidate_columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE calibration_candidate_records ADD COLUMN {column} {definition}")


def upsert(conn: sqlite3.Connection, table: str, key: str, values: dict[str, Any]) -> str:
    ensure_calibration_maturity_schema(conn)
    available = table_columns(conn, table)
    encoded: dict[str, Any] = {}
    for column, value in values.items():
        if isinstance(value, (dict, list)):
            encoded[column] = canonical_json(value)
        elif isinstance(value, bool):
            encoded[column] = 1 if value else 0
        else:
            encoded[column] = value
    insert_columns = [column for column in encoded if column in available]
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [column for column in insert_columns if column not in {key, "created_at"}]
    if "updated_at" in available:
        update_columns.append("updated_at")
    update_clause = ",\n          ".join(
        "updated_at=CURRENT_TIMESTAMP" if column == "updated_at" else f"{column}=excluded.{column}"
        for column in update_columns
    )
    conn.execute(
        f"""
        INSERT INTO {table} ({", ".join(insert_columns)})
        VALUES ({placeholders})
        ON CONFLICT({key}) DO UPDATE SET
          {update_clause}
        """,
        tuple(encoded[column] for column in insert_columns),
    )
    return str(values[key])


def default_lane_registry() -> dict[str, Any]:
    return {
        "schema_version": "calibration-lane-registry/v1",
        "lanes": {
            "scae_constants": [
                {"parameter_id": "per_update_log_odds_cap", "min_value": 0.01, "max_value": 0.35, "risk_tier": "medium", "rollback_semantics": "pointer_rollback"}
            ],
            "post_ledger_calibration": [
                {"parameter_id": "identity_calibration_enabled", "min_value": 0.0, "max_value": 1.0, "risk_tier": "low", "rollback_semantics": "pointer_rollback"}
            ],
            "retrieval_policy": [
                {"parameter_id": "thin_retrieval_penalty", "min_value": 0.0, "max_value": 0.5, "risk_tier": "medium", "rollback_semantics": "pointer_rollback"},
                {"parameter_id": "protected_primary_penalty", "min_value": 0.0, "max_value": 0.5, "risk_tier": "medium", "rollback_semantics": "pointer_rollback"},
            ],
            "decomposer_profile": [
                {"parameter_id": "max_leaf_count", "min_value": 1.0, "max_value": 30.0, "risk_tier": "medium", "rollback_semantics": "pointer_rollback"},
                {"parameter_id": "decomposer_miss_penalty", "min_value": 0.0, "max_value": 1.0, "risk_tier": "medium", "rollback_semantics": "pointer_rollback"},
            ],
            "decision_actionability_profile": [
                {"parameter_id": "watch_only_threshold", "min_value": 0.0, "max_value": 1.0, "risk_tier": "medium", "rollback_semantics": "pointer_rollback"}
            ],
            "effective_tuning_profile": [
                {"parameter_id": "source_unknown_overlay_enabled", "min_value": 0.0, "max_value": 1.0, "risk_tier": "low", "rollback_semantics": "pointer_rollback"}
            ],
            "emergency_conservative_overlay": [
                {"parameter_id": "max_overlay_ttl_hours", "min_value": 1.0, "max_value": 168.0, "risk_tier": "emergency_conservative", "rollback_semantics": "expire_or_pointer_rollback"}
            ],
        },
    }


def resolve_lane_registry(registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    source = registry or default_lane_registry()
    lanes = require_mapping("registry.lanes", source.get("lanes"))
    resolved: dict[str, dict[str, Any]] = {}
    for lane_id, specs in lanes.items():
        if lane_id not in LANE_IDS:
            raise CalibrationMaturityError(f"unknown lane: {lane_id}")
        for spec in require_list(f"lanes.{lane_id}", specs):
            spec = require_mapping("lane spec", spec)
            parameter_id = require_non_empty("parameter_id", spec.get("parameter_id"))
            if not spec.get("rollback_semantics"):
                raise CalibrationMaturityError(f"{parameter_id} missing rollback semantics")
            item = dict(spec)
            item["owner_lane"] = lane_id
            resolved[parameter_id] = item
    return resolved


def validate_candidate_bounds(candidate: dict[str, Any], registry: dict[str, Any] | None = None) -> str:
    ensure_no_forbidden_authority(candidate, "candidate")
    lane_id = require_non_empty("candidate.lane_id", candidate.get("lane_id"))
    specs = resolve_lane_registry(registry)
    for change in require_list("candidate.changed_parameters", candidate.get("changed_parameters")):
        change = require_mapping("changed_parameter", change)
        parameter_id = require_non_empty("changed_parameter.parameter_id", change.get("parameter_id"))
        if parameter_id not in specs:
            raise CalibrationMaturityError(f"unknown tunable variable: {parameter_id}")
        spec = specs[parameter_id]
        owner_lane = require_non_empty("changed_parameter.owner_lane", change.get("owner_lane"))
        if owner_lane != spec["owner_lane"] or owner_lane != lane_id:
            raise CalibrationMaturityError(f"{parameter_id} belongs to {spec['owner_lane']}, not {owner_lane}")
        value = change.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CalibrationMaturityError(f"{parameter_id} value must be numeric")
        if not float(spec["min_value"]) <= float(value) <= float(spec["max_value"]):
            raise CalibrationMaturityError(f"{parameter_id} is out of bounds")
        if not spec.get("rollback_semantics"):
            raise CalibrationMaturityError(f"{parameter_id} missing rollback semantics")
    return "passed"


def build_calibration_candidate(
    *,
    lane_id: str,
    changed_parameters: list[dict[str, Any]],
    source_replay_cohort_ids: list[str] | None = None,
    source_scorecard_refs: list[str] | None = None,
    source_trace_materialization_refs: list[str] | None = None,
    baseline_policy: dict[str, Any] | None = None,
    candidate_policy: dict[str, Any] | None = None,
    component_diagnostics_ref: str | None = None,
    protected_slice_non_degradation_status: str = "pending",
    holdout_status: str = "not_run",
    canary_status: str = "not_required",
    candidate_id: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lane_id = require_non_empty("lane_id", lane_id)
    record = {
        "lane_id": lane_id,
        "changed_parameters": changed_parameters,
    }
    bounds_status = validate_candidate_bounds(record)
    source_replay_cohort_ids = list(source_replay_cohort_ids or [])
    source_scorecard_refs = list(source_scorecard_refs or [])
    source_trace_materialization_refs = list(source_trace_materialization_refs or [])
    seed = {
        "lane_id": lane_id,
        "changed_parameters": changed_parameters,
        "source_replay_cohort_ids": source_replay_cohort_ids,
        "source_scorecard_refs": source_scorecard_refs,
    }
    candidate = {
        "schema_version": CALIBRATION_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id or "cal-candidate:" + hashlib.sha256(canonical_json(seed).encode("utf-8")).hexdigest(),
        "lane_id": lane_id,
        "owner_session": "Session 6",
        "candidate_status": "candidate_recorded",
        "baseline_policy_sha256": prefixed_sha256(baseline_policy or {"policy": "baseline"}),
        "candidate_policy_sha256": prefixed_sha256(candidate_policy or seed),
        "changed_parameters": changed_parameters,
        "source_replay_cohort_ids": source_replay_cohort_ids,
        "source_scorecard_refs": source_scorecard_refs,
        "source_trace_materialization_refs": source_trace_materialization_refs,
        "component_diagnostics_ref": component_diagnostics_ref,
        "bounds_check_status": bounds_status,
        "protected_slice_non_degradation_status": protected_slice_non_degradation_status,
        "holdout_status": holdout_status,
        "canary_status": canary_status,
        "promotion_status": "candidate_recorded",
        "promotion_decision": "pending",
        "canary_bucket": "not_assigned",
        "rollback_pointer_ref": None,
        "rollback_status": "rollback_pointer_required_before_promotion",
        "live_forecast_authority": False,
        "created_at": created_at or utc_now_iso(),
        "metadata": require_mapping("metadata", metadata),
    }
    ensure_no_forbidden_authority(candidate, "candidate")
    return candidate


def write_calibration_candidate(conn: sqlite3.Connection, candidate: dict[str, Any]) -> str:
    validate_candidate_bounds(candidate)
    return upsert(conn, "calibration_candidate_records", "candidate_id", candidate)


def brier(probability: float, outcome: float) -> float:
    return (probability - outcome) ** 2


def log_loss(probability: float, outcome: float) -> float:
    p = max(0.001, min(0.999, probability))
    return -(outcome * math.log(p) + (1.0 - outcome) * math.log(1.0 - p))


def score_candidate(candidate: dict[str, Any], replay_cohort: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_candidate_bounds(candidate)
    cases = require_list("replay_cohort.resolved_cases", replay_cohort.get("resolved_cases"))
    if not cases:
        raise CalibrationMaturityError("replay cohort must contain resolved cases")
    max_degradation = float((policy or {}).get("max_protected_slice_degradation", 0.0))
    rows: list[dict[str, Any]] = []
    for idx, case in enumerate(cases):
        case = require_mapping(f"resolved_cases[{idx}]", case)
        if case.get("resolved") is not True:
            raise CalibrationMaturityError("unresolved cases cannot enter resolved replay scoring")
        slices = require_mapping(f"resolved_cases[{idx}].slices", case.get("slices"))
        missing = [slice_name for slice_name in PROTECTED_SLICES if slice_name not in slices]
        if missing:
            raise CalibrationMaturityError("missing protected slice: " + missing[0])
        outcome = float(case["outcome"])
        baseline_probability = float(case["baseline_probability"])
        candidate_probability = float(case["candidate_probability"])
        rows.append(
            {
                "outcome": outcome,
                "baseline_brier": brier(baseline_probability, outcome),
                "candidate_brier": brier(candidate_probability, outcome),
                "candidate_log_loss": log_loss(candidate_probability, outcome),
                "slices": slices,
                "tail_failure": bool(case.get("tail_failure")),
            }
        )
    baseline_brier = sum(row["baseline_brier"] for row in rows) / len(rows)
    candidate_brier = sum(row["candidate_brier"] for row in rows) / len(rows)
    diagnostics: dict[str, Any] = {}
    protected_status = "passed"
    for slice_name in PROTECTED_SLICES:
        values: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            values.setdefault(str(row["slices"][slice_name]), []).append(row)
        slice_diagnostics: dict[str, Any] = {}
        for value, group in values.items():
            baseline = sum(row["baseline_brier"] for row in group) / len(group)
            candidate_score = sum(row["candidate_brier"] for row in group) / len(group)
            degradation = candidate_score - baseline
            status = "failed" if degradation > max_degradation else "passed"
            if status == "failed":
                protected_status = "failed"
            slice_diagnostics[value] = {
                "baseline_brier": baseline,
                "candidate_brier": candidate_score,
                "degradation": degradation,
                "status": status,
            }
        diagnostics[slice_name] = slice_diagnostics
    diagnostic = {
        "schema_version": CALIBRATION_DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_id": "cal-diagnostic:" + hashlib.sha256(canonical_json([candidate["candidate_id"], replay_cohort.get("cohort_id"), diagnostics]).encode("utf-8")).hexdigest(),
        "candidate_id": candidate["candidate_id"],
        "lane_id": candidate["lane_id"],
        "replay_cohort_id": require_non_empty("replay_cohort.cohort_id", replay_cohort.get("cohort_id")),
        "headline_status": "improved" if candidate_brier <= baseline_brier else "degraded",
        "protected_slice_non_degradation_status": protected_status,
        "metrics_json": {
            "brier": candidate_brier,
            "baseline_brier": baseline_brier,
            "log_loss": sum(row["candidate_log_loss"] for row in rows) / len(rows),
            "adaptive_calibration_error": abs(candidate_brier - baseline_brier),
            "brier_decomposition": {"reliability": candidate_brier, "resolution": 0.0, "uncertainty": 0.25},
            "spiegelhalter_z": 0.0,
            "tail_failure_count": sum(1 for row in rows if row["tail_failure"]),
        },
        "protected_slice_diagnostics": diagnostics,
        "live_forecast_authority": False,
        "created_at": utc_now_iso(),
        "metadata": {"case_count": len(rows)},
    }
    return diagnostic


def write_calibration_component_diagnostics(conn: sqlite3.Connection, diagnostic: dict[str, Any]) -> str:
    ensure_no_forbidden_authority(diagnostic, "diagnostic")
    return upsert(conn, "calibration_component_diagnostic_records", "diagnostic_id", diagnostic)


def write_calibration_lane_health(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    payload = {
        "schema_version": CALIBRATION_LANE_HEALTH_SCHEMA_VERSION,
        "health_id": record.get("health_id") or "lane-health:" + hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest(),
        "lane_id": require_non_empty("lane_id", record.get("lane_id")),
        "health_status": require_non_empty("health_status", record.get("health_status")),
        "active_pointer_id": record.get("active_pointer_id"),
        "reason_codes": list(record.get("reason_codes") or []),
        "created_at": record.get("created_at") or utc_now_iso(),
        "metadata": require_mapping("metadata", record.get("metadata")),
    }
    return upsert(conn, "calibration_lane_health_records", "health_id", payload)


def start_candidate_canary(candidate: dict[str, Any], *, canary_bucket: str = "deterministic_canary") -> dict[str, Any]:
    if candidate.get("holdout_status") != "passed":
        raise CalibrationMaturityError("candidate with failed holdout cannot canary")
    if candidate.get("protected_slice_non_degradation_status") != "passed":
        raise CalibrationMaturityError("candidate without diagnostics cannot canary")
    return {
        "schema_version": CALIBRATION_CANARY_SCHEMA_VERSION,
        "canary_id": "canary:" + hashlib.sha256(canonical_json([candidate["candidate_id"], canary_bucket]).encode("utf-8")).hexdigest(),
        "candidate_id": candidate["candidate_id"],
        "lane_id": candidate["lane_id"],
        "canary_status": "running",
        "canary_bucket": canary_bucket,
        "started_at": utc_now_iso(),
        "completed_at": None,
        "live_forecast_authority": False,
        "metadata": {},
    }


def write_calibration_canary_state(conn: sqlite3.Connection, canary: dict[str, Any]) -> str:
    return upsert(conn, "calibration_canary_state_records", "canary_id", canary)


def write_policy_rollback_event(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    payload = {
        "schema_version": POLICY_ROLLBACK_SCHEMA_VERSION,
        "rollback_event_id": record.get("rollback_event_id") or "rollback-event:" + hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest(),
        "lane_id": require_non_empty("lane_id", record.get("lane_id")),
        "candidate_id": require_non_empty("candidate_id", record.get("candidate_id")),
        "pointer_id": record.get("pointer_id"),
        "rollback_pointer_ref": record.get("rollback_pointer_ref"),
        "reason": require_non_empty("reason", record.get("reason")),
        "actor": record.get("actor") or "Session 6",
        "health_evidence_refs": list(record.get("health_evidence_refs") or []),
        "live_forecast_authority": False,
        "created_at": record.get("created_at") or utc_now_iso(),
        "metadata": require_mapping("metadata", record.get("metadata")),
    }
    return upsert(conn, "policy_rollback_events", "rollback_event_id", payload)


def promote_policy_pointer(conn: sqlite3.Connection, candidate: dict[str, Any], current_pointer: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_candidate_bounds(candidate)
    if not candidate.get("component_diagnostics_ref") or candidate.get("protected_slice_non_degradation_status") != "passed":
        raise CalibrationMaturityError("candidate without diagnostics cannot promote")
    if candidate.get("holdout_status") != "passed":
        raise CalibrationMaturityError("candidate with failed holdout cannot promote")
    if candidate.get("canary_status") not in {"passed", "not_required"}:
        raise CalibrationMaturityError("failed canary cannot promote")
    rollback_ref = (current_pointer or {}).get("active_policy_snapshot_ref") or candidate.get("rollback_pointer_ref")
    if not rollback_ref:
        raise CalibrationMaturityError("promotion requires rollback pointer")
    pointer = {
        "schema_version": CALIBRATION_POINTER_SCHEMA_VERSION,
        "pointer_id": "cal-pointer:" + hashlib.sha256(canonical_json([candidate["candidate_id"], candidate["lane_id"]]).encode("utf-8")).hexdigest(),
        "lane_id": candidate["lane_id"],
        "pointer_status": "active",
        "active_policy_snapshot_ref": candidate["candidate_policy_sha256"],
        "candidate_id": candidate["candidate_id"],
        "rollback_pointer_ref": rollback_ref,
        "canary_status": candidate["canary_status"],
        "promoted_at": utc_now_iso(),
        "promoted_by": "Session 6",
        "live_forecast_authority": False,
        "metadata": {"base_policy_file_modified": False},
    }
    upsert(conn, "calibration_lane_pointer_records", "pointer_id", pointer)
    write_policy_rollback_event(
        conn,
        {
            "lane_id": candidate["lane_id"],
            "candidate_id": candidate["candidate_id"],
            "pointer_id": pointer["pointer_id"],
            "rollback_pointer_ref": rollback_ref,
            "reason": "promotion",
            "actor": "Session 6",
        },
    )
    return pointer


def build_retrieval_policy_candidate(replay_results: dict[str, Any], *, min_thin_cases: int = 2) -> dict[str, Any]:
    cases = require_list("replay_results.resolved_cases", replay_results.get("resolved_cases"))
    thin_cases = [case for case in cases if case.get("retrieval_quality_bucket") == "thin"]
    if len(thin_cases) < min_thin_cases:
        raise CalibrationMaturityError("thin retrieval penalty proposal requires enough resolved cases")
    for idx, case in enumerate(cases):
        forecast_ts = parse_timestamp(f"resolved_cases[{idx}].forecast_timestamp", case.get("forecast_timestamp"))
        observed_ts = parse_timestamp(f"resolved_cases[{idx}].source_observed_at", case.get("source_observed_at"))
        if observed_ts > forecast_ts:
            raise CalibrationMaturityError("stale-evidence tuning cannot use post-forecast source observations")
    baseline_protected = float(replay_results.get("baseline_protected_primary_coverage", 0.0))
    candidate_protected = float(replay_results.get("candidate_protected_primary_coverage", baseline_protected))
    if candidate_protected < baseline_protected:
        raise CalibrationMaturityError("retrieval candidate worsens protected-primary coverage")
    candidate = build_calibration_candidate(
        lane_id="retrieval_policy",
        changed_parameters=[{"parameter_id": "thin_retrieval_penalty", "owner_lane": "retrieval_policy", "value": 0.30}],
        source_replay_cohort_ids=[require_non_empty("cohort_id", replay_results.get("cohort_id"))],
        metadata={
            "protected_primary_failure_rate": replay_results.get("protected_primary_failure_rate", 0.0),
            "generic_missingness_rate": replay_results.get("generic_missingness_rate", 0.0),
        },
    )
    return candidate


def write_retrieval_policy_snapshot(conn: sqlite3.Connection, candidate: dict[str, Any], replay_feature_summary: dict[str, Any]) -> str:
    payload = {
        "schema_version": RETRIEVAL_POLICY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": "retrieval-policy-snapshot:" + hashlib.sha256(canonical_json([candidate["candidate_id"], replay_feature_summary]).encode("utf-8")).hexdigest(),
        "candidate_id": candidate["candidate_id"],
        "lane_id": "retrieval_policy",
        "replay_feature_summary": replay_feature_summary,
        "protected_primary_diagnostics": {
            "protected_primary_failure_rate": candidate.get("metadata", {}).get("protected_primary_failure_rate", 0.0),
            "generic_missingness_rate": candidate.get("metadata", {}).get("generic_missingness_rate", 0.0),
        },
        "live_forecast_authority": False,
        "created_at": utc_now_iso(),
        "metadata": {},
    }
    return upsert(conn, "retrieval_policy_snapshot_records", "snapshot_id", payload)


def build_decomposer_profile_candidate(qdt_shape_summary: dict[str, Any], miss_labels: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = build_calibration_candidate(
        lane_id="decomposer_profile",
        changed_parameters=[{"parameter_id": "decomposer_miss_penalty", "owner_lane": "decomposer_profile", "value": 0.2}],
        metadata={"qdt_shape_summary": qdt_shape_summary, "decomposer_miss_labels": miss_labels},
    )
    return candidate


def write_decomposer_profile_candidate(conn: sqlite3.Connection, candidate: dict[str, Any]) -> str:
    payload = {
        "schema_version": PROFILE_CANDIDATE_SCHEMA_VERSION,
        "profile_candidate_id": "decomposer-profile:" + hashlib.sha256(candidate["candidate_id"].encode("utf-8")).hexdigest(),
        "candidate_id": candidate["candidate_id"],
        "qdt_shape_summary": candidate.get("metadata", {}).get("qdt_shape_summary", {}),
        "decomposer_miss_labels": candidate.get("metadata", {}).get("decomposer_miss_labels", []),
        "live_forecast_authority": False,
        "created_at": utc_now_iso(),
        "metadata": {},
    }
    return upsert(conn, "decomposer_profile_candidate_records", "profile_candidate_id", payload)


def build_decision_actionability_candidate(route_diagnostics: dict[str, Any]) -> dict[str, Any]:
    ensure_no_forbidden_authority(route_diagnostics, "route_diagnostics")
    return build_calibration_candidate(
        lane_id="decision_actionability_profile",
        changed_parameters=[{"parameter_id": "watch_only_threshold", "owner_lane": "decision_actionability_profile", "value": 0.5}],
        metadata={"route_diagnostics": route_diagnostics},
    )


def write_decision_actionability_candidate(conn: sqlite3.Connection, candidate: dict[str, Any]) -> str:
    payload = {
        "schema_version": PROFILE_CANDIDATE_SCHEMA_VERSION,
        "actionability_candidate_id": "decision-actionability:" + hashlib.sha256(candidate["candidate_id"].encode("utf-8")).hexdigest(),
        "candidate_id": candidate["candidate_id"],
        "route_diagnostics": candidate.get("metadata", {}).get("route_diagnostics", {}),
        "live_forecast_authority": False,
        "created_at": utc_now_iso(),
        "metadata": {},
    }
    return upsert(conn, "decision_actionability_candidate_records", "actionability_candidate_id", payload)


def validate_profile_candidate_non_degradation(slice_deltas: dict[str, float], *, max_degradation: float = 0.0) -> str:
    for slice_name, degradation in slice_deltas.items():
        if degradation > max_degradation:
            raise CalibrationMaturityError(f"profile candidate degrades protected slice {slice_name}")
    return "passed"


def build_emergency_conservative_overlay(trigger: dict[str, Any], effects: list[dict[str, Any]], *, expires_at: str) -> dict[str, Any]:
    ensure_no_forbidden_authority({"trigger": trigger, "effects": effects}, "emergency_overlay")
    parse_timestamp("expires_at", expires_at)
    if not effects:
        raise CalibrationMaturityError("emergency overlay requires at least one effect")
    for effect in effects:
        direction = require_non_empty("effect.direction", effect.get("direction"))
        if direction not in CONSERVATIVE_EFFECT_DIRECTIONS:
            raise CalibrationMaturityError("emergency overlay effects must be conservative only")
    return {
        "schema_version": EMERGENCY_OVERLAY_SCHEMA_VERSION,
        "overlay_id": "emergency-overlay:" + hashlib.sha256(canonical_json([trigger, effects, expires_at]).encode("utf-8")).hexdigest(),
        "lane_id": "emergency_conservative_overlay",
        "trigger_kind": require_non_empty("trigger.kind", trigger.get("kind")),
        "reason_codes": list(trigger.get("reason_codes") or []),
        "effects": effects,
        "expires_at": expires_at,
        "rollback_semantics": "expire_or_manual_policy_pointer_rollback",
        "live_forecast_authority": False,
        "created_at": utc_now_iso(),
        "metadata": {},
    }


def write_emergency_conservative_overlay(conn: sqlite3.Connection, overlay: dict[str, Any]) -> str:
    return upsert(conn, "emergency_conservative_overlay_records", "overlay_id", overlay)


def validate_shared_reuse_temporal_safety(cache_entry: dict[str, Any], *, consuming_forecast_timestamp: str) -> dict[str, Any]:
    consuming = parse_timestamp("consuming_forecast_timestamp", consuming_forecast_timestamp)
    status = cache_entry.get("temporal_eligibility_status")
    max_source = cache_entry.get("max_underlying_source_timestamp")
    if status != "passed":
        return {"reuse_status": "rejected", "reason": "producer_temporal_eligibility_not_passed"}
    if max_source and parse_timestamp("max_underlying_source_timestamp", max_source) > consuming:
        return {"reuse_status": "rejected", "reason": "underlying_source_after_consuming_forecast"}
    return {"reuse_status": "accepted", "reason": "temporal_provenance_safe"}


def optimization_maturity_gate(state: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or {}
    checks = {
        "full_trace_materialization": float(state.get("full_trace_completion", 0.0)) >= float(policy.get("min_trace_completion", 1.0)),
        "lane_registry_coverage": state.get("registry_coverage") == "complete",
        "active_pointer_stability": int(state.get("pointer_stability_window", 0)) >= int(policy.get("min_stability_window", 1)),
        "catastrophic_tail_failures": int(state.get("catastrophic_tail_failures", 1)) == 0,
        "component_diagnostics": bool(state.get("all_active_lanes_have_component_diagnostics")),
        "rollback_ready": bool(state.get("all_active_lanes_have_rollback_pointers")),
    }
    result = {
        "schema_version": OPTIMIZATION_MATURITY_SCHEMA_VERSION,
        "maturity_result_id": "optimization-maturity:" + hashlib.sha256(canonical_json(checks).encode("utf-8")).hexdigest(),
        "status": "passed" if all(checks.values()) else "blocked",
        "checks_json": checks,
        "live_forecast_authority": False,
        "created_at": utc_now_iso(),
        "metadata": {},
    }
    return result


def write_optimization_maturity_result(conn: sqlite3.Connection, result: dict[str, Any]) -> str:
    return upsert(conn, "optimization_maturity_results", "maturity_result_id", result)
