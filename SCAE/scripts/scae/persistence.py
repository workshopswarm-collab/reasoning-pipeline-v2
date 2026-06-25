"""SCAE persistence surfaces for ledger audit and forecast decisions.

MIG-007 stores SCAE-owned ledger artifacts and diagnostic slices. PERSIST-001
adds the SCAE-only forecast decision record. It does not bridge to
market_predictions, scoring, replay, or calibration tuning surfaces.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


MIG007_SCHEMA_VERSION = "scae-ledger-probability-audit-persistence/v1"
PERSIST001_SCHEMA_VERSION = "scae-forecast-decision-persistence/v1"
SCAE_LEDGER_OUTPUT_TABLE = "scae_ledger_outputs"
FORECAST_DECISION_TABLE = "forecast_decision_records"
SCAE_LOG_ODDS_UPDATE_TABLE = "scae_log_odds_update_slices"
SCAE_CROSS_LEAF_DEPENDENCY_TABLE = "scae_cross_leaf_dependency_slices"
SCAE_BRANCH_SUBLEDGER_TABLE = "scae_branch_subledger_slices"
SCAE_CONDITIONAL_BRANCH_TABLE = "scae_conditional_branch_slices"
SCAE_CALIBRATION_DIAGNOSTIC_TABLE = "scae_calibration_diagnostic_slices"
SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE = "scae_mechanism_family_assignment_slices"
SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE = "scae_research_sufficiency_input_slices"
MISSINGNESS_SIGNAL_TABLE = "missingness_signal_slices"
RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE = "research_sufficiency_reconciliation_slices"

MIG007_TABLES = (
    SCAE_LEDGER_OUTPUT_TABLE,
    SCAE_LOG_ODDS_UPDATE_TABLE,
    SCAE_CROSS_LEAF_DEPENDENCY_TABLE,
    SCAE_BRANCH_SUBLEDGER_TABLE,
    SCAE_CONDITIONAL_BRANCH_TABLE,
    SCAE_CALIBRATION_DIAGNOSTIC_TABLE,
    SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE,
    SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE,
    MISSINGNESS_SIGNAL_TABLE,
    RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE,
)

SCAE_LEDGER_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "007_scae_ledger_probability_audit.sql"
)

VALIDITY_INVALID = "invalid_for_forecast"
VALIDITY_READY = "valid_for_forecast"
VALIDITY_WATCH_ONLY = "valid_for_forecast_watch_only"
FINAL_READY_STATUS = "final_probability_fields_ready"
FINAL_BLOCKED_STATUS = "blocked_invalid_for_forecast"
FORECAST_DECISION_PERSISTED_STATUS = "production_forecast_persisted_from_scae"
FORECAST_DECISION_BLOCKED_STATUS = "blocked_invalid_scae_forecast"
FINAL_PROBABILITY_FIELDS = (
    "debt_adjusted_probability",
    "production_forecast_prob",
    "canonical_probability",
)
PROTECTED_DOWNSTREAM_TABLES = (
    "forecast_decision_records",
    "market_predictions",
    "outcome_scoring_records",
    "evaluator_scorecards",
    "calibration_candidate_records",
    "calibration_lane_pointer_records",
    "v2_replay_manifests",
    "v2_replay_result_records",
    "training_trace_minimal_pointers",
    "training_trace_full_materializations",
)
PERSIST001_PROTECTED_TABLES = (
    "market_predictions",
    "outcome_scoring_records",
    "evaluator_scorecards",
    "calibration_candidate_records",
    "calibration_lane_pointer_records",
    "v2_replay_manifests",
    "v2_replay_result_records",
)

FORECAST_VALIDITY_RANK = {
    VALIDITY_INVALID: 0,
    VALIDITY_WATCH_ONLY: 1,
    VALIDITY_READY: 2,
}
EXECUTION_AUTHORITY_RANK = {
    "forbidden": 0,
    "needs_refresh": 1,
    "watch_only": 2,
    "low_size_only": 3,
    "normal_execution_allowed": 4,
}
MAX_EXECUTION_BY_VALIDITY = {
    VALIDITY_INVALID: "forbidden",
    VALIDITY_WATCH_ONLY: "watch_only",
    VALIDITY_READY: "normal_execution_allowed",
}
ACTIONABILITY_RANK = {
    "non_actionable": 0,
    "refresh_required": 1,
    "watch_only": 2,
    "actionable_low_size": 3,
    "actionable": 4,
}
DEFAULT_ACTIONABILITY_BY_EXECUTION = {
    "forbidden": "non_actionable",
    "needs_refresh": "refresh_required",
    "watch_only": "watch_only",
    "low_size_only": "actionable_low_size",
    "normal_execution_allowed": "actionable",
}
FORBIDDEN_DECISION_AUTHORITY_FIELDS = {
    "brier",
    "brier_score",
    "calibration_debt_cleared",
    "calibration_debt_clearance",
    "canonical_probability",
    "clear_calibration_debt",
    "confidence_interval",
    "debt_adjusted_probability",
    "decision_probability",
    "desired_probability",
    "fair_value",
    "fair_value_probability",
    "forecast_interval",
    "forecast_prob",
    "forecast_probability",
    "interval",
    "interval_override",
    "market_prediction",
    "market_predictions",
    "market_predictions_row",
    "persist_forecast",
    "persistence_write",
    "post_ledger_probability",
    "predicted_probability",
    "prediction_brier",
    "probability",
    "probability_estimate",
    "probability_interval",
    "probability_override",
    "probability_range",
    "probability_recommendation",
    "probability_signal",
    "production_forecast_prob",
    "raw_ledger_probability",
    "replacement_probability",
    "scae_delta",
    "scae_log_odds_delta",
    "scoreable_forecast_output",
    "scoreable_prediction",
    "target_probability",
    "write_forecast_decision",
    "writes_market_prediction",
    "writes_production_forecast",
}
FORBIDDEN_DECISION_AUTHORITY_KEYS = {
    re.sub(r"[^a-z0-9]", "", name.lower()) for name in FORBIDDEN_DECISION_AUTHORITY_FIELDS
}
FORBIDDEN_NUMERIC_TEXT_PATTERN = re.compile(
    r"(?i)\b(?:probability|fair\s*value|forecast\s*prob|canonical\s*probability|production\s*forecast)"
    r"\b[^.\n]{0,80}(?:\d{1,3}(?:\.\d+)?\s*%|\b0\.\d+\b)"
)

GENERIC_SLICE_TABLES = frozenset(MIG007_TABLES) - {SCAE_LEDGER_OUTPUT_TABLE}
GENERIC_SLICE_ID_FIELDS = (
    "slice_id",
    "candidate_slice_id",
    "update_slice_id",
    "cluster_slice_id",
    "cross_leaf_dependency_slice_id",
    "branch_subledger_slice_id",
    "conditional_branch_slice_id",
    "mechanism_family_diagnostic_id",
    "calibration_diagnostic_slice_id",
    "research_sufficiency_input_slice_id",
    "missingness_signal_slice_id",
    "research_sufficiency_reconciliation_id",
    "research_sufficiency_reconciliation_ref",
    "delta_input_ref",
    "summary_id",
)
SIGNED_DELTA_FIELDS = (
    "signed_log_odds_delta",
    "netted_signed_log_odds_delta",
    "cross_leaf_guarded_signed_log_odds_delta",
    "branch_subledger_signed_log_odds_delta",
    "conditional_signed_log_odds_delta",
    "conditional_recombined_signed_log_odds_delta",
    "conditional_recombined_log_odds_delta",
)


class ScaePersistenceError(ValueError):
    """Raised when MIG-007 persistence would violate the SCAE contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _bool_int(value: Any) -> int:
    return 1 if value is True else 0


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ScaePersistenceError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ScaePersistenceError(f"{field_name} must be numeric") from exc


def _required_float(value: Any, field_name: str) -> float:
    number = _optional_float(value, field_name)
    if number is None:
        raise ScaePersistenceError(f"{field_name} is required")
    return number


def _required_string(field_name: str, value: Any) -> str:
    if not _is_non_empty_string(value):
        raise ScaePersistenceError(f"{field_name} is required")
    return str(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not _is_non_empty_string(value):
        raise ScaePersistenceError("optional string fields must be non-empty strings")
    return str(value)


def _assert_no_decision_probability_authority(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ScaePersistenceError(f"{path} contains an invalid key")
            if _normalize_key(key) in FORBIDDEN_DECISION_AUTHORITY_KEYS:
                raise ScaePersistenceError(f"{path}.{key} is forbidden for PERSIST-001")
            _assert_no_decision_probability_authority(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _assert_no_decision_probability_authority(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        if FORBIDDEN_NUMERIC_TEXT_PATTERN.search(value):
            raise ScaePersistenceError(f"{path} appears to author a numeric probability")
    elif value is None or isinstance(value, (bool, int, float)):
        return
    else:
        raise ScaePersistenceError(f"{path} contains unsupported type {type(value).__name__}")


def _first_non_empty(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_scae_ledger_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCAE_LEDGER_MIGRATION.read_text(encoding="utf-8"))


def ensure_forecast_decision_schema(conn: sqlite3.Connection) -> None:
    """Create the PERSIST-001 forecast decision table."""

    conn.executescript(
        f"""
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS {FORECAST_DECISION_TABLE} (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          forecast_decision_id TEXT NOT NULL UNIQUE,
          schema_version TEXT NOT NULL,
          case_id TEXT NOT NULL,
          case_key TEXT,
          dispatch_id TEXT NOT NULL,
          run_id TEXT,
          forecast_timestamp TEXT,
          scae_ledger_id TEXT NOT NULL,
          scae_ledger_digest TEXT NOT NULL,
          decision_gate_id TEXT NOT NULL,
          decision_gate_digest TEXT NOT NULL,
          synthesis_annotation_ref TEXT,
          synthesis_annotation_digest TEXT,
          production_forecast_prob REAL,
          canonical_probability REAL,
          forecast_validity_status TEXT NOT NULL,
          execution_authority_status TEXT NOT NULL,
          actionability_status TEXT NOT NULL,
          final_probability_fields_status TEXT NOT NULL,
          production_persistence_status TEXT NOT NULL,
          production_forecast_persisted INTEGER NOT NULL DEFAULT 0,
          scoreable_forecast_output INTEGER NOT NULL DEFAULT 0,
          writes_market_prediction INTEGER NOT NULL DEFAULT 0,
          probability_source TEXT NOT NULL,
          decision_effect_status TEXT NOT NULL,
          non_scoreable_reason_code TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{{}}',
          artifact_payload_json TEXT NOT NULL,
          artifact_sha256 TEXT NOT NULL,
          scae_ledger_payload_sha256 TEXT NOT NULL,
          decision_gate_payload_sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_forecast_decision_case
          ON {FORECAST_DECISION_TABLE}(case_id, dispatch_id);
        CREATE INDEX IF NOT EXISTS idx_forecast_decision_scae
          ON {FORECAST_DECISION_TABLE}(scae_ledger_id, decision_gate_id);
        CREATE INDEX IF NOT EXISTS idx_forecast_decision_status
          ON {FORECAST_DECISION_TABLE}(forecast_validity_status, actionability_status);
        """
    )


def _rows_from(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    rows = value.get(field_name) if isinstance(value, dict) else value
    if rows is None:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ScaePersistenceError(f"{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaePersistenceError(f"{field_name} must contain objects")
        normalized.append(copy.deepcopy(row))
    return normalized


def _slice_id(row: dict[str, Any], *, table: str) -> str:
    value = _first_non_empty(row, GENERIC_SLICE_ID_FIELDS)
    if value:
        return value
    return _sha_id(table.rstrip("s"), row)


def _signed_delta(row: dict[str, Any]) -> float | None:
    for field_name in SIGNED_DELTA_FIELDS:
        if field_name in row:
            return _optional_float(row[field_name], field_name)
    return None


def _accepted_for_ledger(row: dict[str, Any]) -> bool:
    return any(
        row.get(field_name) is True
        for field_name in (
            "accepted_for_ledger_input",
            "accepted_for_candidate_ledger_input",
            "accepted_for_pre_debt_ledger_input",
            "accepted_for_conditional_recombination",
        )
    )


def _diagnostic_only(row: dict[str, Any], table: str) -> bool:
    if row.get("diagnostic_only") is True:
        return True
    if row.get("interval_debug_only") is True:
        return True
    if table in {
        SCAE_CALIBRATION_DIAGNOSTIC_TABLE,
        SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE,
        SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE,
        MISSINGNESS_SIGNAL_TABLE,
        RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE,
    }:
        return True
    return False


def _mechanism_family_id(row: dict[str, Any]) -> str | None:
    value = _first_non_empty(
        row,
        (
            "mechanism_family_id",
            "absence_mechanism_family_id",
            "missingness_mechanism_family_id",
            "no_catalyst_mechanism_family_id",
        ),
    )
    if value:
        return value
    values = row.get("mechanism_family_ids")
    if isinstance(values, list) and values:
        return str(sorted(str(item) for item in values if _is_non_empty_string(item))[0])
    return None


def _dependency_group_id(row: dict[str, Any]) -> str | None:
    return _first_non_empty(
        row,
        (
            "dependence_group_id",
            "dependency_group_id",
            "conditional_branch_group_id",
            "anchor_dependency_contract_id",
        ),
    )


def _source_refs(row: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for field_name in (
        "candidate_slice_refs",
        "cluster_slice_refs",
        "source_dependency_slice_refs",
        "branch_subledger_slice_refs",
        "conditional_branch_slice_refs",
        "leaf_reconciliation_refs",
        "leaf_certificate_refs",
        "leaf_breadth_profile_refs",
        "leaf_breadth_coverage_refs",
    ):
        value = row.get(field_name)
        if isinstance(value, list):
            refs.extend(str(item) for item in value if _is_non_empty_string(item))
    for field_name in (
        "candidate_slice_id",
        "cluster_slice_id",
        "cross_leaf_dependency_slice_id",
        "branch_subledger_slice_id",
        "conditional_branch_slice_id",
        "source_ref",
        "evidence_ref",
        "research_sufficiency_reconciliation_ref",
        "research_sufficiency_certificate_ref",
    ):
        value = row.get(field_name)
        if _is_non_empty_string(value):
            refs.append(str(value))
    return sorted(set(refs))


def _reason_codes(row: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for field_name in ("reason_codes", "rejection_reason_codes", "blocking_reason_codes"):
        value = row.get(field_name)
        if isinstance(value, list):
            codes.extend(str(item) for item in value if _is_non_empty_string(item))
    return sorted(set(codes))


def _assert_slice_authority(row: dict[str, Any], *, table: str) -> None:
    if row.get("live_forecast_authority") is True:
        raise ScaePersistenceError(f"{table} row {_slice_id(row, table=table)} has live forecast authority")
    if row.get("writes_production_forecast") is True:
        raise ScaePersistenceError(f"{table} row {_slice_id(row, table=table)} writes production forecast")
    if row.get("can_increase_evidence_strength") is True and _diagnostic_only(row, table):
        raise ScaePersistenceError(f"{table} diagnostic row cannot increase evidence strength")


def _common_slice_values(row: dict[str, Any], *, table: str) -> dict[str, Any]:
    _assert_slice_authority(row, table=table)
    payload = copy.deepcopy(row)
    slice_id = _slice_id(payload, table=table)
    surface_name = payload.get("surface_name") or table
    return {
        "slice_id": slice_id,
        "schema_version": _required_string("schema_version", payload.get("schema_version")),
        "artifact_type": payload.get("artifact_type"),
        "case_id": payload.get("case_id"),
        "dispatch_id": payload.get("dispatch_id"),
        "leaf_id": payload.get("leaf_id"),
        "parent_branch_id": payload.get("parent_branch_id"),
        "condition_scope": payload.get("condition_scope"),
        "feature_id": payload.get("feature_id"),
        "surface_name": surface_name,
        "source_ref": payload.get("source_ref") or payload.get("evidence_ref"),
        "source_family_id": payload.get("source_family_id"),
        "claim_family_id": payload.get("claim_family_id"),
        "mechanism_family_id": _mechanism_family_id(payload),
        "dependency_group_id": _dependency_group_id(payload),
        "signed_log_odds_delta": _signed_delta(payload),
        "accepted_for_ledger_input": _bool_int(_accepted_for_ledger(payload)),
        "diagnostic_only": _bool_int(_diagnostic_only(payload, table)),
        "can_increase_evidence_strength": _bool_int(payload.get("can_increase_evidence_strength")),
        "live_forecast_authority": _bool_int(payload.get("live_forecast_authority")),
        "writes_scae_ledger": _bool_int(payload.get("writes_scae_ledger")),
        "writes_production_forecast": _bool_int(payload.get("writes_production_forecast")),
        "reason_codes": canonical_json(_reason_codes(payload)),
        "source_refs": canonical_json(_source_refs(payload)),
        "payload_json": canonical_json(payload),
        "payload_sha256": _prefixed_sha256(payload),
    }


def _insert_or_update(conn: sqlite3.Connection, table: str, values: dict[str, Any], conflict_column: str) -> None:
    available = table_columns(conn, table)
    insert_columns = [column for column in values if column in available]
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [column for column in insert_columns if column not in {conflict_column, "created_at"}]
    if "updated_at" in available and "updated_at" not in update_columns:
        update_columns.append("updated_at")
    update_clause = ",\n          ".join(
        "updated_at=CURRENT_TIMESTAMP" if column == "updated_at" else f"{column}=excluded.{column}"
        for column in update_columns
    )
    conn.execute(
        f"""
        INSERT INTO {table} ({", ".join(insert_columns)})
        VALUES ({placeholders})
        ON CONFLICT({conflict_column}) DO UPDATE SET
          {update_clause}
        """,
        tuple(values[column] for column in insert_columns),
    )


def _write_generic_slices(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> list[str]:
    if table not in GENERIC_SLICE_TABLES:
        raise ScaePersistenceError(f"{table} is not a MIG-007 slice table")
    ensure_scae_ledger_schema(conn)
    row_ids: list[str] = []
    for row in rows:
        values = _common_slice_values(row, table=table)
        _insert_or_update(conn, table, values, "slice_id")
        row_ids.append(str(values["slice_id"]))
    return row_ids


def write_scae_log_odds_update_slices(
    conn: sqlite3.Connection,
    slices: list[dict[str, Any]] | dict[str, Any],
) -> list[str]:
    rows = _rows_from(slices, "scae_log_odds_update_slices")
    if not rows and isinstance(slices, dict):
        rows = _rows_from(slices, "candidate_slices")
    return _write_generic_slices(conn, SCAE_LOG_ODDS_UPDATE_TABLE, rows)


def _context_to_research_sufficiency_input_slice(
    ledger: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "artifact_type": "scae_research_sufficiency_input_slice",
        "schema_version": "scae-research-sufficiency-input-slice/v1",
        "surface_name": SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE,
        "feature_id": "MIG-007",
        "case_id": ledger.get("case_id") or context.get("case_id"),
        "dispatch_id": ledger.get("dispatch_id") or context.get("dispatch_id"),
        "research_sufficiency_context_id": context.get("research_sufficiency_context_id"),
        "bundle_status": context.get("bundle_status"),
        "forecast_validity_status": context.get("forecast_validity_status"),
        "leaf_reconciliation_refs": copy.deepcopy(context.get("leaf_reconciliation_refs") or []),
        "leaf_certificate_refs": copy.deepcopy(context.get("leaf_certificate_refs") or []),
        "leaf_breadth_profile_refs": copy.deepcopy(context.get("leaf_breadth_profile_refs") or []),
        "leaf_breadth_coverage_refs": copy.deepcopy(context.get("leaf_breadth_coverage_refs") or []),
        "leaf_escalation_decision_refs": copy.deepcopy(context.get("leaf_escalation_decision_refs") or []),
        "blocked_leaf_ids": copy.deepcopy(context.get("blocked_leaf_ids") or []),
        "structurally_unanswerable_leaf_ids": copy.deepcopy(
            context.get("structurally_unanswerable_leaf_ids") or []
        ),
        "accepted_for_ledger_input": False,
        "diagnostic_only": True,
        "can_increase_evidence_strength": False,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
    }
    payload["research_sufficiency_input_slice_id"] = _sha_id("scae-sufficiency-input", payload)
    return payload


def write_scae_research_sufficiency_inputs(
    conn: sqlite3.Connection,
    research_sufficiency_inputs: list[dict[str, Any]] | dict[str, Any],
) -> list[str]:
    if isinstance(research_sufficiency_inputs, dict) and "research_sufficiency_context" in research_sufficiency_inputs:
        ledger = research_sufficiency_inputs
        context = ledger.get("research_sufficiency_context")
        if not isinstance(context, dict):
            raise ScaePersistenceError("ledger.research_sufficiency_context must be an object")
        rows = [_context_to_research_sufficiency_input_slice(ledger, context)]
    else:
        rows = _rows_from(research_sufficiency_inputs, SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE)
    return _write_generic_slices(conn, SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE, rows)


def _ledger_id(ledger: dict[str, Any]) -> str:
    value = _first_non_empty(
        ledger,
        (
            "final_probability_ledger_id",
            "scae_ledger_id",
            "ledger_id",
            "research_sufficiency_guarded_ledger_id",
            "pre_debt_ledger_id",
        ),
    )
    if value:
        return value
    return _sha_id("scae-ledger-output", ledger)


def _case_id(ledger: dict[str, Any]) -> str:
    value = ledger.get("case_id")
    if not _is_non_empty_string(value) and isinstance(ledger.get("prior_context"), dict):
        value = ledger["prior_context"].get("case_id")
    return _required_string("case_id", value)


def _dispatch_id(ledger: dict[str, Any]) -> str:
    value = ledger.get("dispatch_id")
    if not _is_non_empty_string(value) and isinstance(ledger.get("prior_context"), dict):
        value = ledger["prior_context"].get("dispatch_id")
    return _required_string("dispatch_id", value)


def validate_scae_ledger_for_persistence(ledger: dict[str, Any]) -> None:
    if not isinstance(ledger, dict):
        raise ScaePersistenceError("ledger must be an object")
    _case_id(ledger)
    _dispatch_id(ledger)
    _required_float(ledger.get("raw_ledger_probability"), "raw_ledger_probability")
    _required_float(ledger.get("post_ledger_probability"), "post_ledger_probability")
    validity = _required_string("forecast_validity_status", ledger.get("forecast_validity_status"))
    final_status = _required_string(
        "final_probability_fields_status",
        ledger.get("final_probability_fields_status"),
    )
    if ledger.get("writes_production_forecast") is True:
        raise ScaePersistenceError("MIG-007 cannot write production forecasts")
    if ledger.get("writes_persistence") is True:
        raise ScaePersistenceError("SCAE ledger artifact must not claim persistence write authority")
    present_final_fields = [field for field in FINAL_PROBABILITY_FIELDS if field in ledger]
    if validity == VALIDITY_INVALID:
        if present_final_fields:
            raise ScaePersistenceError("invalid forecast ledgers must not contain final probability fields")
        if final_status != FINAL_BLOCKED_STATUS:
            raise ScaePersistenceError("invalid forecast ledgers must be blocked finalization rows")
    elif final_status == FINAL_READY_STATUS:
        missing = [field for field in FINAL_PROBABILITY_FIELDS if field not in ledger]
        if missing:
            raise ScaePersistenceError("ready final ledgers missing final probability fields: " + ", ".join(missing))
        for field in FINAL_PROBABILITY_FIELDS:
            probability = _required_float(ledger.get(field), field)
            if not 0.0 <= probability <= 1.0:
                raise ScaePersistenceError(f"{field} must be in [0, 1]")
    if "research_sufficiency_context" not in ledger:
        raise ScaePersistenceError("ledger.research_sufficiency_context is required for MIG-007")
    if "calibration_debt_context" not in ledger:
        raise ScaePersistenceError("ledger.calibration_debt_context is required for MIG-007")


def _ledger_values(ledger: dict[str, Any]) -> dict[str, Any]:
    validate_scae_ledger_for_persistence(ledger)
    payload = copy.deepcopy(ledger)
    research_context = payload.get("research_sufficiency_context") or {}
    debt_context = payload.get("calibration_debt_context") or {}
    interval = payload.get("interval") or {}
    prior_context = payload.get("prior_context") or {}
    return {
        "scae_ledger_id": _ledger_id(payload),
        "schema_version": payload.get("schema_version") or MIG007_SCHEMA_VERSION,
        "case_id": _case_id(payload),
        "case_key": payload.get("case_key") or prior_context.get("case_key"),
        "dispatch_id": _dispatch_id(payload),
        "run_id": payload.get("run_id"),
        "forecast_timestamp": payload.get("forecast_timestamp"),
        "policy_snapshot_id": (
            payload.get("policy_snapshot_id")
            or debt_context.get("policy_snapshot_id")
            or research_context.get("policy_snapshot_id")
        ),
        "raw_ledger_probability": _required_float(payload.get("raw_ledger_probability"), "raw_ledger_probability"),
        "post_ledger_probability": _required_float(payload.get("post_ledger_probability"), "post_ledger_probability"),
        "debt_adjusted_probability": _optional_float(payload.get("debt_adjusted_probability"), "debt_adjusted_probability"),
        "production_forecast_prob": _optional_float(payload.get("production_forecast_prob"), "production_forecast_prob"),
        "canonical_probability": _optional_float(payload.get("canonical_probability"), "canonical_probability"),
        "forecast_validity_status": payload["forecast_validity_status"],
        "execution_authority_status": _required_string(
            "execution_authority_status",
            payload.get("execution_authority_status"),
        ),
        "final_probability_fields_status": payload["final_probability_fields_status"],
        "production_forecast_authority": _bool_int(payload.get("production_forecast_authority")),
        "writes_production_forecast": _bool_int(payload.get("writes_production_forecast")),
        "writes_persistence": _bool_int(payload.get("writes_persistence")),
        "prior_context_id": prior_context.get("prior_context_id"),
        "prior_context_json": canonical_json(prior_context),
        "market_prior_assimilation_context_json": canonical_json(
            payload.get("market_prior_assimilation_context") or {}
        ),
        "research_sufficiency_context_id": research_context.get("research_sufficiency_context_id"),
        "research_sufficiency_context_json": canonical_json(research_context),
        "calibration_context_json": canonical_json(payload.get("calibration_context") or {}),
        "calibration_debt_context_json": canonical_json(debt_context),
        "interval_json": canonical_json(interval),
        "cap_stack_json": canonical_json(payload.get("cap_stack") or payload.get("cap_stack_snapshot") or {}),
        "accepted_delta_input_refs": canonical_json(
            sorted(
                str(item.get("delta_input_ref"))
                for item in payload.get("accepted_delta_inputs", [])
                if isinstance(item, dict) and _is_non_empty_string(item.get("delta_input_ref"))
            )
        ),
        "artifact_payload_json": canonical_json(payload),
        "artifact_sha256": _prefixed_sha256(payload),
    }


def _forecast_probability_fields(ledger: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        raise ScaePersistenceError("scae_ledger must be an object")
    _case_id(ledger)
    _dispatch_id(ledger)
    validity = _required_string("forecast_validity_status", ledger.get("forecast_validity_status"))
    if validity not in FORECAST_VALIDITY_RANK:
        raise ScaePersistenceError(f"unknown forecast_validity_status {validity}")
    execution = _required_string("execution_authority_status", ledger.get("execution_authority_status"))
    if execution not in EXECUTION_AUTHORITY_RANK:
        raise ScaePersistenceError(f"unknown execution_authority_status {execution}")
    max_execution = MAX_EXECUTION_BY_VALIDITY[validity]
    if EXECUTION_AUTHORITY_RANK[execution] > EXECUTION_AUTHORITY_RANK[max_execution]:
        raise ScaePersistenceError("SCAE execution authority exceeds forecast validity")
    if ledger.get("writes_persistence") is True:
        raise ScaePersistenceError("SCAE ledger input must not claim persistence write authority")
    if ledger.get("writes_production_forecast") is True:
        raise ScaePersistenceError("SCAE ledger input must not claim production forecast write authority")

    final_status = _required_string(
        "final_probability_fields_status",
        ledger.get("final_probability_fields_status"),
    )
    if validity == VALIDITY_INVALID:
        forbidden_present = sorted(field for field in FINAL_PROBABILITY_FIELDS if field in ledger)
        if forbidden_present:
            raise ScaePersistenceError(
                "invalid SCAE forecast must not carry final probability fields: "
                + ", ".join(forbidden_present)
            )
        if final_status != FINAL_BLOCKED_STATUS:
            raise ScaePersistenceError("invalid SCAE forecast must have blocked final probability status")
        return {
            "forecast_validity_status": validity,
            "execution_authority_status": execution,
            "final_probability_fields_status": final_status,
            "production_forecast_prob": None,
            "canonical_probability": None,
        }

    if validity not in {VALIDITY_READY, VALIDITY_WATCH_ONLY}:
        raise ScaePersistenceError(f"unknown forecast_validity_status {validity}")
    if final_status != FINAL_READY_STATUS:
        raise ScaePersistenceError("valid SCAE forecasts must have ready final probability status")
    production = _required_float(ledger.get("production_forecast_prob"), "production_forecast_prob")
    canonical = _required_float(ledger.get("canonical_probability"), "canonical_probability")
    if not 0.0 <= production <= 1.0:
        raise ScaePersistenceError("production_forecast_prob must be in [0, 1]")
    if not 0.0 <= canonical <= 1.0:
        raise ScaePersistenceError("canonical_probability must be in [0, 1]")
    if round(production, 9) != round(canonical, 9):
        raise ScaePersistenceError("canonical_probability must equal SCAE production_forecast_prob")
    return {
        "forecast_validity_status": validity,
        "execution_authority_status": execution,
        "final_probability_fields_status": final_status,
        "production_forecast_prob": round(production, 9),
        "canonical_probability": round(canonical, 9),
    }


def _decision_gate_id(decision_gate: dict[str, Any]) -> str:
    value = _first_non_empty(decision_gate, ("decision_gate_id", "forecast_decision_id", "artifact_id"))
    if value:
        return value
    return _sha_id("decision-gate", decision_gate)


def _decision_gate_digest(decision_gate: dict[str, Any]) -> str:
    value = _first_non_empty(decision_gate, ("decision_gate_digest", "artifact_sha256"))
    if value:
        return value
    return _prefixed_sha256(decision_gate)


def _scae_ledger_digest(ledger: dict[str, Any]) -> str:
    value = _first_non_empty(
        ledger,
        (
            "final_probability_ledger_digest",
            "artifact_sha256",
            "scae_ledger_digest",
            "research_sufficiency_guarded_ledger_digest",
            "pre_debt_ledger_output_digest",
        ),
    )
    if value:
        return value
    return _prefixed_sha256(ledger)


def _synthesis_ref(decision_gate: dict[str, Any]) -> str | None:
    context = decision_gate.get("synthesis_context")
    if not isinstance(context, dict):
        return None
    return _optional_string(context.get("synthesis_annotation_ref"))


def _synthesis_digest(decision_gate: dict[str, Any]) -> str | None:
    context = decision_gate.get("synthesis_context")
    if not isinstance(context, dict):
        return None
    return _optional_string(context.get("synthesis_annotation_digest"))


def _assert_decision_gate_false_flags(decision_gate: dict[str, Any]) -> None:
    false_fields = (
        "probability_authority",
        "replacement_probability_authority",
        "synthesis_upgrade_authority",
        "persistence_authority",
        "market_prediction_authority",
        "scoring_authority",
        "calibration_debt_clearance_authority",
        "writes_production_forecast",
        "writes_persistence",
        "writes_market_prediction",
        "scoreable_forecast_output",
        "clears_calibration_debt",
    )
    for field_name in false_fields:
        if decision_gate.get(field_name) not in (False, 0):
            raise ScaePersistenceError(f"decision_gate.{field_name} must be false for PERSIST-001")


def _validate_decision_gate_for_persistence(
    decision_gate: dict[str, Any],
    *,
    ledger: dict[str, Any],
    forecast_fields: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(decision_gate, dict):
        raise ScaePersistenceError("decision_gate must be an object")
    if decision_gate.get("artifact_type") != "decision_execution_gate":
        raise ScaePersistenceError("decision_gate must be a DEC-001 artifact")
    if decision_gate.get("feature_id") != "DEC-001":
        raise ScaePersistenceError("decision_gate.feature_id must be DEC-001")
    _assert_decision_gate_false_flags(decision_gate)
    for key, child in decision_gate.items():
        if key in {"scae_context", "forbidden_outputs", "allowed_outputs"}:
            continue
        if key in {
            "probability_authority",
            "replacement_probability_authority",
            "synthesis_upgrade_authority",
            "persistence_authority",
            "market_prediction_authority",
            "scoring_authority",
            "calibration_debt_clearance_authority",
            "writes_production_forecast",
            "writes_persistence",
            "writes_market_prediction",
            "scoreable_forecast_output",
            "clears_calibration_debt",
        }:
            continue
        if _normalize_key(key) in FORBIDDEN_DECISION_AUTHORITY_KEYS:
            raise ScaePersistenceError(f"decision_gate.{key} is forbidden for PERSIST-001")
        _assert_no_decision_probability_authority(child, f"decision_gate.{key}")

    context = decision_gate.get("scae_context")
    if not isinstance(context, dict):
        raise ScaePersistenceError("decision_gate.scae_context must be an object")
    if context.get("case_id") not in (None, ledger.get("case_id")):
        raise ScaePersistenceError("decision_gate.scae_context.case_id does not match SCAE ledger")
    if context.get("dispatch_id") not in (None, ledger.get("dispatch_id")):
        raise ScaePersistenceError("decision_gate.scae_context.dispatch_id does not match SCAE ledger")
    if context.get("scae_ledger_ref") not in (None, _ledger_id(ledger)):
        raise ScaePersistenceError("decision_gate.scae_context.scae_ledger_ref does not match SCAE ledger")
    if context.get("scae_ledger_digest") not in (None, _scae_ledger_digest(ledger)):
        raise ScaePersistenceError("decision_gate.scae_context.scae_ledger_digest does not match SCAE ledger")

    scae_validity = forecast_fields["forecast_validity_status"]
    decision_validity = _required_string(
        "decision_gate.forecast_validity_status",
        decision_gate.get("forecast_validity_status"),
    )
    if decision_validity not in FORECAST_VALIDITY_RANK:
        raise ScaePersistenceError(f"unknown decision forecast_validity_status {decision_validity}")
    if FORECAST_VALIDITY_RANK[decision_validity] > FORECAST_VALIDITY_RANK[scae_validity]:
        raise ScaePersistenceError("decision gate cannot upgrade SCAE forecast validity")
    if context.get("forecast_validity_status") not in (None, scae_validity):
        raise ScaePersistenceError("decision_gate.scae_context forecast validity does not match SCAE ledger")

    scae_execution = forecast_fields["execution_authority_status"]
    decision_execution = _required_string(
        "decision_gate.execution_authority_status",
        decision_gate.get("execution_authority_status"),
    )
    if decision_execution not in EXECUTION_AUTHORITY_RANK:
        raise ScaePersistenceError(f"unknown decision execution_authority_status {decision_execution}")
    max_execution_rank = min(
        EXECUTION_AUTHORITY_RANK[scae_execution],
        EXECUTION_AUTHORITY_RANK[MAX_EXECUTION_BY_VALIDITY[decision_validity]],
    )
    if EXECUTION_AUTHORITY_RANK[decision_execution] > max_execution_rank:
        raise ScaePersistenceError("decision gate cannot upgrade SCAE execution authority")
    if context.get("execution_authority_status") not in (None, scae_execution):
        raise ScaePersistenceError("decision_gate.scae_context execution authority does not match SCAE ledger")

    actionability = _required_string("actionability_status", decision_gate.get("actionability_status"))
    if actionability not in ACTIONABILITY_RANK:
        raise ScaePersistenceError(f"unknown actionability_status {actionability}")
    default_actionability = DEFAULT_ACTIONABILITY_BY_EXECUTION[decision_execution]
    if ACTIONABILITY_RANK[actionability] > ACTIONABILITY_RANK[default_actionability]:
        raise ScaePersistenceError("actionability cannot exceed selected execution authority")

    production = forecast_fields["production_forecast_prob"]
    canonical = forecast_fields["canonical_probability"]
    if scae_validity == VALIDITY_INVALID:
        if "production_forecast_prob" in context or "canonical_probability" in context:
            raise ScaePersistenceError("invalid DEC/SCAE context must not carry production probability fields")
        if decision_validity != VALIDITY_INVALID or decision_execution != "forbidden" or actionability != "non_actionable":
            raise ScaePersistenceError("invalid SCAE forecasts must remain non-actionable")
    else:
        context_production = _required_float(context.get("production_forecast_prob"), "decision_gate.scae_context.production_forecast_prob")
        context_canonical = _required_float(context.get("canonical_probability"), "decision_gate.scae_context.canonical_probability")
        if round(context_production, 9) != production:
            raise ScaePersistenceError("decision gate cannot replace SCAE production_forecast_prob")
        if round(context_canonical, 9) != canonical:
            raise ScaePersistenceError("decision gate cannot replace SCAE canonical_probability")

    return {
        "decision_gate_id": _decision_gate_id(decision_gate),
        "decision_gate_digest": _decision_gate_digest(decision_gate),
        "forecast_validity_status": decision_validity,
        "execution_authority_status": decision_execution,
        "actionability_status": actionability,
        "synthesis_annotation_ref": _synthesis_ref(decision_gate),
        "synthesis_annotation_digest": _synthesis_digest(decision_gate),
    }


def _metadata_json(metadata: dict[str, Any] | None) -> str:
    value = copy.deepcopy(metadata or {})
    if not isinstance(value, dict):
        raise ScaePersistenceError("metadata must be an object")
    _assert_no_decision_probability_authority(value, "metadata")
    return canonical_json(value)


def _decision_effect_status(
    *,
    forecast_fields: dict[str, Any],
    decision_values: dict[str, Any],
) -> str:
    if forecast_fields["forecast_validity_status"] == VALIDITY_INVALID:
        return "blocked_invalid_scae_forecast"
    if (
        decision_values["forecast_validity_status"] != forecast_fields["forecast_validity_status"]
        or decision_values["execution_authority_status"] != forecast_fields["execution_authority_status"]
        or decision_values["actionability_status"]
        != DEFAULT_ACTIONABILITY_BY_EXECUTION[forecast_fields["execution_authority_status"]]
    ):
        return "decision_downgraded_execution_or_actionability"
    return "decision_preserved_scae_execution"


def _forecast_decision_values(
    ledger: dict[str, Any],
    decision_gate: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forecast_fields = _forecast_probability_fields(ledger)
    decision_values = _validate_decision_gate_for_persistence(
        decision_gate,
        ledger=ledger,
        forecast_fields=forecast_fields,
    )
    should_persist_probability = forecast_fields["forecast_validity_status"] != VALIDITY_INVALID
    payload = {
        "artifact_type": "forecast_decision_record",
        "schema_version": PERSIST001_SCHEMA_VERSION,
        "feature_id": "PERSIST-001",
        "case_id": _case_id(ledger),
        "case_key": ledger.get("case_key"),
        "dispatch_id": _dispatch_id(ledger),
        "run_id": ledger.get("run_id"),
        "forecast_timestamp": ledger.get("forecast_timestamp"),
        "scae_ledger_id": _ledger_id(ledger),
        "scae_ledger_digest": _scae_ledger_digest(ledger),
        "decision_gate_id": decision_values["decision_gate_id"],
        "decision_gate_digest": decision_values["decision_gate_digest"],
        "synthesis_annotation_ref": decision_values["synthesis_annotation_ref"],
        "synthesis_annotation_digest": decision_values["synthesis_annotation_digest"],
        "production_forecast_prob": (
            forecast_fields["production_forecast_prob"] if should_persist_probability else None
        ),
        "canonical_probability": forecast_fields["canonical_probability"] if should_persist_probability else None,
        "forecast_validity_status": decision_values["forecast_validity_status"],
        "execution_authority_status": decision_values["execution_authority_status"],
        "actionability_status": decision_values["actionability_status"],
        "final_probability_fields_status": forecast_fields["final_probability_fields_status"],
        "production_persistence_status": (
            FORECAST_DECISION_PERSISTED_STATUS if should_persist_probability else FORECAST_DECISION_BLOCKED_STATUS
        ),
        "production_forecast_persisted": should_persist_probability,
        "scoreable_forecast_output": False,
        "writes_market_prediction": False,
        "probability_source": "SCAE-012.production_forecast_prob",
        "decision_effect_status": _decision_effect_status(
            forecast_fields=forecast_fields,
            decision_values=decision_values,
        ),
        "non_scoreable_reason_code": (
            "forecast_validity_invalid_for_forecast" if not should_persist_probability else None
        ),
        "metadata": copy.deepcopy(metadata or {}),
    }
    payload["forecast_decision_id"] = _sha_id(
        "forecast-decision",
        {
            "scae_ledger_id": payload["scae_ledger_id"],
            "decision_gate_id": payload["decision_gate_id"],
            "feature_id": "PERSIST-001",
        },
    )
    payload["forecast_decision_digest"] = _prefixed_sha256(payload)
    return {
        "forecast_decision_id": payload["forecast_decision_id"],
        "schema_version": PERSIST001_SCHEMA_VERSION,
        "case_id": payload["case_id"],
        "case_key": payload["case_key"],
        "dispatch_id": payload["dispatch_id"],
        "run_id": payload["run_id"],
        "forecast_timestamp": payload["forecast_timestamp"],
        "scae_ledger_id": payload["scae_ledger_id"],
        "scae_ledger_digest": payload["scae_ledger_digest"],
        "decision_gate_id": payload["decision_gate_id"],
        "decision_gate_digest": payload["decision_gate_digest"],
        "synthesis_annotation_ref": payload["synthesis_annotation_ref"],
        "synthesis_annotation_digest": payload["synthesis_annotation_digest"],
        "production_forecast_prob": payload["production_forecast_prob"],
        "canonical_probability": payload["canonical_probability"],
        "forecast_validity_status": payload["forecast_validity_status"],
        "execution_authority_status": payload["execution_authority_status"],
        "actionability_status": payload["actionability_status"],
        "final_probability_fields_status": payload["final_probability_fields_status"],
        "production_persistence_status": payload["production_persistence_status"],
        "production_forecast_persisted": _bool_int(payload["production_forecast_persisted"]),
        "scoreable_forecast_output": 0,
        "writes_market_prediction": 0,
        "probability_source": payload["probability_source"],
        "decision_effect_status": payload["decision_effect_status"],
        "non_scoreable_reason_code": payload["non_scoreable_reason_code"],
        "metadata_json": _metadata_json(metadata),
        "artifact_payload_json": canonical_json(payload),
        "artifact_sha256": _prefixed_sha256(payload),
        "scae_ledger_payload_sha256": _prefixed_sha256(ledger),
        "decision_gate_payload_sha256": _prefixed_sha256(decision_gate),
    }


def write_forecast_decision(
    conn: sqlite3.Connection,
    scae_ledger: dict[str, Any],
    decision_gate: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the PERSIST-001 SCAE-only forecast decision record."""

    ensure_forecast_decision_schema(conn)
    values = _forecast_decision_values(scae_ledger, decision_gate, metadata=metadata)
    _insert_or_update(conn, FORECAST_DECISION_TABLE, values, "forecast_decision_id")
    return {
        "forecast_decision_id": values["forecast_decision_id"],
        "schema_version": PERSIST001_SCHEMA_VERSION,
        "production_persistence_status": values["production_persistence_status"],
        "production_forecast_prob": values["production_forecast_prob"],
        "forecast_validity_status": values["forecast_validity_status"],
        "execution_authority_status": values["execution_authority_status"],
        "actionability_status": values["actionability_status"],
        "scoreable_forecast_output": False,
        "protected_downstream_tables_not_written": list(PERSIST001_PROTECTED_TABLES),
    }


def _derived_calibration_diagnostics(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name in ("calibration_context", "calibration_debt_context"):
        context = ledger.get(field_name)
        if not isinstance(context, dict) or not context:
            continue
        row = {
            "artifact_type": "scae_calibration_diagnostic_slice",
            "schema_version": "scae-calibration-diagnostic-slice/v1",
            "surface_name": SCAE_CALIBRATION_DIAGNOSTIC_TABLE,
            "feature_id": "MIG-007",
            "case_id": ledger.get("case_id"),
            "dispatch_id": ledger.get("dispatch_id"),
            "calibration_context_kind": field_name,
            "source_ref": context.get(f"{field_name}_id") or context.get("calibration_debt_context_id"),
            "diagnostic_only": True,
            "can_increase_evidence_strength": False,
            "live_forecast_authority": False,
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
            "payload": copy.deepcopy(context),
        }
        row["calibration_diagnostic_slice_id"] = _sha_id("scae-calibration-diagnostic", row)
        rows.append(row)
    return rows


def write_scae_ledger(
    conn: sqlite3.Connection,
    ledger: dict[str, Any],
    *,
    log_odds_update_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    cross_leaf_dependency_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    branch_subledger_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    conditional_branch_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    calibration_diagnostic_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    mechanism_family_assignment_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    research_sufficiency_input_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    missingness_signal_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    research_sufficiency_reconciliation_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a final SCAE ledger output and its MIG-007 audit slices."""

    ensure_scae_ledger_schema(conn)
    values = _ledger_values(ledger)
    _insert_or_update(conn, SCAE_LEDGER_OUTPUT_TABLE, values, "scae_ledger_id")

    surface_inputs: dict[str, list[dict[str, Any]]] = {
        SCAE_LOG_ODDS_UPDATE_TABLE: _rows_from(
            log_odds_update_slices if log_odds_update_slices is not None else ledger,
            SCAE_LOG_ODDS_UPDATE_TABLE,
        ),
        SCAE_CROSS_LEAF_DEPENDENCY_TABLE: _rows_from(
            cross_leaf_dependency_slices if cross_leaf_dependency_slices is not None else ledger,
            SCAE_CROSS_LEAF_DEPENDENCY_TABLE,
        ),
        SCAE_BRANCH_SUBLEDGER_TABLE: _rows_from(
            branch_subledger_slices if branch_subledger_slices is not None else ledger,
            SCAE_BRANCH_SUBLEDGER_TABLE,
        ),
        SCAE_CONDITIONAL_BRANCH_TABLE: _rows_from(
            conditional_branch_slices if conditional_branch_slices is not None else ledger,
            SCAE_CONDITIONAL_BRANCH_TABLE,
        ),
        SCAE_CALIBRATION_DIAGNOSTIC_TABLE: _rows_from(
            calibration_diagnostic_slices if calibration_diagnostic_slices is not None else ledger,
            SCAE_CALIBRATION_DIAGNOSTIC_TABLE,
        )
        or _derived_calibration_diagnostics(ledger),
        SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE: _rows_from(
            mechanism_family_assignment_slices if mechanism_family_assignment_slices is not None else ledger,
            SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE,
        ),
        SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE: (
            _rows_from(research_sufficiency_input_slices, SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE)
            if research_sufficiency_input_slices is not None
            else [_context_to_research_sufficiency_input_slice(ledger, ledger["research_sufficiency_context"])]
        ),
        MISSINGNESS_SIGNAL_TABLE: _rows_from(
            missingness_signal_slices if missingness_signal_slices is not None else ledger,
            MISSINGNESS_SIGNAL_TABLE,
        ),
        RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE: _rows_from(
            research_sufficiency_reconciliation_slices
            if research_sufficiency_reconciliation_slices is not None
            else ledger,
            RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE,
        ),
    }

    surface_row_ids = {
        table: _write_generic_slices(conn, table, rows)
        for table, rows in surface_inputs.items()
    }
    return {
        "scae_ledger_id": values["scae_ledger_id"],
        "schema_version": MIG007_SCHEMA_VERSION,
        "surface_row_ids": surface_row_ids,
        "surface_write_counts": {table: len(row_ids) for table, row_ids in surface_row_ids.items()},
        "protected_downstream_tables_not_written": list(PROTECTED_DOWNSTREAM_TABLES),
    }
