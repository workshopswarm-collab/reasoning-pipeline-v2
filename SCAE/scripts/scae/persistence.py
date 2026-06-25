"""MIG-007 SCAE ledger and probability audit persistence.

This module stores SCAE-owned ledger artifacts and diagnostic slices. It does
not bridge to forecast decisions, market_predictions, scoring, replay, or
calibration tuning surfaces.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


MIG007_SCHEMA_VERSION = "scae-ledger-probability-audit-persistence/v1"
SCAE_LEDGER_OUTPUT_TABLE = "scae_ledger_outputs"
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
FINAL_READY_STATUS = "final_probability_fields_ready"
FINAL_BLOCKED_STATUS = "blocked_invalid_for_forecast"
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
