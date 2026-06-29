"""MIG-003 QDT/decomposition persistence helpers.

These writers persist decomposer-owned structure, refs, validation status, and
research sufficiency requirements only. They reject probability, SCAE,
synthesis, forecast, and decision authority fields.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .qdt import (
    ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION,
    QUESTION_DECOMPOSITION_ARTIFACT_TYPE,
    QDT_SCHEMA_VALIDATOR_VERSION,
    validate_question_decomposition,
)


QUESTION_DECOMPOSITION_MANIFEST_ARTIFACT_TYPES = {
    QUESTION_DECOMPOSITION_ARTIFACT_TYPE,
    QUESTION_DECOMPOSITION_ARTIFACT_TYPE.replace("_", "-"),
}


def _add_orchestrator_scripts_to_path() -> None:
    configured = os.environ.get("ADS_ORCHESTRATOR_SCRIPTS")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(__file__).resolve().parents[3] / "orchestrator" / "scripts")
    for candidate in candidates:
        if candidate.is_dir():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            return


_add_orchestrator_scripts_to_path()

from predquant.ads_handoff import (  # noqa: E402
    canonical_json,
    ensure_artifact_manifest_schema,
    validate_artifact_manifest,
    write_artifact_manifest,
)


MIG_003_QDT_PERSISTENCE_MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "003_qdt_decomposition_persistence.sql"
)
QDT_PERSISTENCE_SCHEMA_VERSION = "ads-mig-003-qdt-persistence/v1"
QDT_DECOMPOSITION_RUNS_TABLE = "qdt_decomposition_runs"
QDT_REQUIRED_RESEARCH_QUESTIONS_TABLE = "qdt_required_research_questions"
QDT_LEAF_RESEARCH_SUFFICIENCY_REQUIREMENTS_TABLE = "qdt_leaf_research_sufficiency_requirements"
QDT_AMRG_ANCHOR_DEPENDENCY_SLICES_TABLE = "qdt_amrg_anchor_dependency_slices"

STATIC_INFORMATION_WEIGHT_VALUES = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.5,
    "low": 0.25,
}

FORBIDDEN_PERSISTENCE_FIELD_NAMES = {
    "probability",
    "probability_estimate",
    "probability_yes",
    "probability_no",
    "forecast_probability",
    "production_forecast_prob",
    "production_probability",
    "final_forecast",
    "final_probability",
    "canonical_probability",
    "debt_adjusted_probability",
    "fair_value",
    "log_odds",
    "odds",
    "scae_delta",
    "scae_evidence_delta",
    "synthesis_conclusion",
    "synthesis_output",
    "decision_instruction",
    "decision_recommendation",
    "decision_output",
    "trade_recommendation",
}
FORBIDDEN_PERSISTENCE_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "log_odds",
    "scae_delta",
    "forecast_probability",
    "production_forecast",
    "synthesis_conclusion",
    "decision_instruction",
    "decision_recommendation",
    "trade_recommendation",
)
ALLOWED_FALSE_AUTHORITY_FIELDS = {
    "probability_authority",
    "forecast_authority",
    "scae_delta_authority",
    "synthesis_authority",
    "decision_authority",
    "writes_scae_ledger_rows",
    "writes_production_forecast",
    "writes_forecast_persistence",
}


class QDTPersistenceError(ValueError):
    """Raised when MIG-003 persistence input is invalid or unsafe."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_column_not_null(conn: sqlite3.Connection, table: str, column: str) -> bool:
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if str(row[1]) == column:
            return bool(row[3])
    return False


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    for column, definition in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


QDT_DECOMPOSITION_RUN_COMPATIBILITY_COLUMNS = {
    "decomposition_run_id": "TEXT",
    "schema_version": "TEXT",
    "case_key": "TEXT",
    "qdt_artifact_id": "TEXT",
    "qdt_artifact_ref": "TEXT",
    "artifact_path": "TEXT",
    "artifact_sha256": "TEXT",
    "prompt_template_id": "TEXT",
    "prompt_template_sha256": "TEXT",
    "model_lane_id": "TEXT",
    "resolved_model_id": "TEXT",
    "model_policy_ref": "TEXT",
    "model_execution_context_sha256": "TEXT",
    "input_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
    "output_schema_version": "TEXT",
    "branch_ids": "TEXT NOT NULL DEFAULT '[]'",
    "dependency_group_ids": "TEXT NOT NULL DEFAULT '[]'",
    "related_market_context_usage": "TEXT NOT NULL DEFAULT '{}'",
    "amrg_anchor_dependency_contract_refs": "TEXT NOT NULL DEFAULT '[]'",
    "candidate_selection_audit": "TEXT NOT NULL DEFAULT '{}'",
    "validation_summary": "TEXT NOT NULL DEFAULT '{}'",
    "qdt_digest": "TEXT",
    "updated_at": "TEXT",
}

QDT_REQUIRED_RESEARCH_QUESTION_COMPATIBILITY_COLUMNS = {
    "decomposition_run_id": "TEXT",
    "schema_version": "TEXT",
    "case_key": "TEXT",
    "qdt_artifact_id": "TEXT",
    "leaf_id": "TEXT",
    "leaf_json_pointer": "TEXT",
    "leaf_digest": "TEXT",
    "static_information_weight": "TEXT",
    "weight_reason_codes": "TEXT NOT NULL DEFAULT '[]'",
    "required_evidence_fields": "TEXT NOT NULL DEFAULT '[]'",
    "required_sufficiency_requirement_id": "TEXT",
    "retrieval_breadth_profile_ref": "TEXT",
    "required_source_classes": "TEXT NOT NULL DEFAULT '[]'",
    "required_value_fields": "TEXT NOT NULL DEFAULT '[]'",
    "required_negative_checks": "TEXT NOT NULL DEFAULT '[]'",
    "market_component_terms": "TEXT NOT NULL DEFAULT '[]'",
    "structural_validation": "TEXT NOT NULL DEFAULT '{}'",
    "question_digest": "TEXT",
    "updated_at": "TEXT",
}


def _ensure_legacy_qdt_compatibility_columns(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, QDT_DECOMPOSITION_RUNS_TABLE):
        _ensure_columns(
            conn,
            QDT_DECOMPOSITION_RUNS_TABLE,
            QDT_DECOMPOSITION_RUN_COMPATIBILITY_COLUMNS,
        )
    if _table_exists(conn, QDT_REQUIRED_RESEARCH_QUESTIONS_TABLE):
        _ensure_columns(
            conn,
            QDT_REQUIRED_RESEARCH_QUESTIONS_TABLE,
            QDT_REQUIRED_RESEARCH_QUESTION_COMPATIBILITY_COLUMNS,
        )


def ensure_qdt_persistence_schema(conn: sqlite3.Connection) -> None:
    """Create or upgrade the Session 3 MIG-003 persistence destinations."""

    ensure_artifact_manifest_schema(conn)
    _ensure_legacy_qdt_compatibility_columns(conn)
    conn.executescript(MIG_003_QDT_PERSISTENCE_MIGRATION.read_text(encoding="utf-8"))
    _ensure_columns(
        conn,
        QDT_DECOMPOSITION_RUNS_TABLE,
        QDT_DECOMPOSITION_RUN_COMPATIBILITY_COLUMNS,
    )
    _ensure_columns(
        conn,
        QDT_REQUIRED_RESEARCH_QUESTIONS_TABLE,
        QDT_REQUIRED_RESEARCH_QUESTION_COMPATIBILITY_COLUMNS,
    )
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_run_id
          ON qdt_decomposition_runs(decomposition_run_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_qdt_required_questions_run_question
          ON qdt_required_research_questions(decomposition_run_id, question_id);
        CREATE INDEX IF NOT EXISTS idx_qdt_decomposition_runs_artifact
          ON qdt_decomposition_runs(qdt_artifact_id);
        CREATE INDEX IF NOT EXISTS idx_qdt_required_questions_run_leaf
          ON qdt_required_research_questions(decomposition_run_id, leaf_id);
        """
    )


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _normalized_field_name(value: Any) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _collect_forbidden_persistence_paths(value: Any, path: str = "record") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if normalized in ALLOWED_FALSE_AUTHORITY_FIELDS:
                if child is not False:
                    errors.append(f"{path}.{key} must remain false")
            elif normalized in FORBIDDEN_PERSISTENCE_FIELD_NAMES:
                errors.append(f"{path}.{key} is forbidden in MIG-003 persistence")
            elif any(fragment in normalized for fragment in FORBIDDEN_PERSISTENCE_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in MIG-003 persistence")
            elif "decision" in normalized and normalized not in {
                "leaf_budget_decision",
                "budget_decision",
            }:
                errors.append(f"{path}.{key} is forbidden in MIG-003 persistence")
            errors.extend(_collect_forbidden_persistence_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            errors.extend(_collect_forbidden_persistence_paths(child, f"{path}[{idx}]"))
    return errors


def _reject_forbidden_persistence_payload(value: Any, path: str = "record") -> None:
    errors = _collect_forbidden_persistence_paths(value, path)
    if errors:
        raise QDTPersistenceError("; ".join(sorted(set(errors))))


def _require_valid_qdt(qdt: dict[str, Any]) -> None:
    result = validate_question_decomposition(qdt, require_selected=True)
    if not result.valid:
        raise QDTPersistenceError("question decomposition invalid: " + "; ".join(result.errors))
    _reject_forbidden_persistence_payload(qdt, "question_decomposition")


def qdt_artifact_id_for(qdt: dict[str, Any]) -> str:
    return _stable_id("artifact:question-decomposition", _prefixed_sha256(qdt))


def decomposition_run_id_for(qdt: dict[str, Any]) -> str:
    return _stable_id(
        "qdt-run",
        qdt.get("case_id"),
        qdt.get("dispatch_id"),
        qdt.get("candidate_selection_audit", {}).get("selected_candidate_id") or qdt.get("candidate_id"),
        _prefixed_sha256(qdt),
    )


def _json(value: Any) -> str:
    return canonical_json(value)


def _bool_int(value: Any) -> int:
    return 1 if value is True else 0


def _weight_value(weight: str) -> float:
    return STATIC_INFORMATION_WEIGHT_VALUES.get(weight, 0.0)


def _market_complexity_class(score: Any) -> str:
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return "unknown"
    if float(score) >= 0.75:
        return "high"
    if float(score) >= 0.4:
        return "medium"
    return "low"


def _artifact_manifest_numeric_id(conn: sqlite3.Connection, artifact_id: str | None) -> int | None:
    if not artifact_id:
        return None
    row = conn.execute(
        "SELECT id FROM case_artifact_manifest WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def _manifest_context(
    conn: sqlite3.Connection,
    manifest: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None, int | None, str | None]:
    if manifest is None:
        return None, None, None, None, None
    validate_artifact_manifest(
        manifest,
        expected_artifact_schema_version="question-decomposition/v1",
    )
    if manifest.get("artifact_type") not in QUESTION_DECOMPOSITION_MANIFEST_ARTIFACT_TYPES:
        raise QDTPersistenceError("artifact manifest must be for question_decomposition")
    artifact_id = write_artifact_manifest(conn, manifest)
    numeric_id = _artifact_manifest_numeric_id(conn, artifact_id)
    return artifact_id, str(manifest["path"]), str(manifest["sha256"]), numeric_id, manifest.get("generated_at")


def _upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any], conflict_columns: Iterable[str]) -> None:
    columns = list(row)
    conflicts = list(conflict_columns)
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in set(conflicts) and column != "created_at"
    )
    if "updated_at" in columns and "updated_at" not in conflicts:
        updates = updates.replace("updated_at=excluded.updated_at", "updated_at=CURRENT_TIMESTAMP")
    conn.execute(
        f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT({", ".join(conflicts)}) DO UPDATE SET
          {updates}
        """,
        tuple(row[column] for column in columns),
    )


def _run_row(
    qdt: dict[str, Any],
    *,
    decomposition_run_id: str,
    qdt_artifact_id: str,
    qdt_artifact_ref: str,
    artifact_path: str | None,
    artifact_sha256: str | None,
    artifact_manifest_id: int | None,
    generated_at: str,
) -> dict[str, Any]:
    leaf_budget = qdt["leaf_budget_decision"]
    model_context = qdt["model_execution_context"]
    validation_summary = qdt["validation_summary"]
    branch_ids = [branch["branch_id"] for branch in qdt["branches"]]
    dependency_groups = sorted(
        {
            branch["dependency_group_id"]
            for branch in qdt["branches"]
            if isinstance(branch, dict) and branch.get("dependency_group_id")
        }
        | {
            leaf["leaf_dependency_group_id"]
            for leaf in qdt["required_leaf_questions"]
            if isinstance(leaf, dict) and leaf.get("leaf_dependency_group_id")
        }
    )
    anchor_refs = [
        contract["anchor_dependency_contract_id"]
        for contract in qdt.get("amrg_anchor_dependency_contracts", [])
        if isinstance(contract, dict) and contract.get("anchor_dependency_contract_id")
    ]
    return {
        "decomposition_run_id": decomposition_run_id,
        "schema_version": QDT_PERSISTENCE_SCHEMA_VERSION,
        "case_key": qdt.get("case_key"),
        "case_id": qdt["case_id"],
        "market_id": qdt["market_id"],
        "dispatch_id": qdt["dispatch_id"],
        "generated_at": generated_at,
        "policy_hash": model_context.get("model_policy_sha256") or _prefixed_sha256(model_context["model_policy_ref"]),
        "market_complexity_score": float(leaf_budget["market_complexity_score"]),
        "market_complexity_class": _market_complexity_class(leaf_budget["market_complexity_score"]),
        "selected_candidate_id": qdt["candidate_selection_audit"]["selected_candidate_id"],
        "validation_status": validation_summary["status"],
        "artifact_manifest_id": artifact_manifest_id,
        "qdt_artifact_id": qdt_artifact_id,
        "qdt_artifact_ref": qdt_artifact_ref,
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "prompt_template_id": model_context["prompt_template_id"],
        "prompt_template_sha256": model_context["prompt_template_sha256"],
        "model_lane_id": model_context["model_lane_id"],
        "resolved_model_id": model_context["resolved_model_id"],
        "model_policy_ref": model_context["model_policy_ref"],
        "model_execution_context_sha256": _prefixed_sha256(model_context),
        "input_manifest_ids": _json(model_context["input_manifest_ids"]),
        "output_schema_version": model_context["output_schema_version"],
        "branch_ids": _json(branch_ids),
        "dependency_group_ids": _json(dependency_groups),
        "related_market_context_usage": _json(qdt["related_market_context_usage"]),
        "amrg_anchor_dependency_contract_refs": _json(anchor_refs),
        "candidate_selection_audit": _json(qdt["candidate_selection_audit"]),
        "validation_summary": _json(validation_summary),
        "qdt_digest": _prefixed_sha256(qdt),
    }


def _leaf_rows(
    qdt: dict[str, Any],
    *,
    decomposition_run_id: str,
    qdt_artifact_id: str,
    artifact_manifest_id: int | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, leaf in enumerate(qdt["required_leaf_questions"]):
        requirements = leaf["research_sufficiency_requirements"]
        legacy_weighting = leaf.get("bayesian_weighting") if isinstance(leaf.get("bayesian_weighting"), dict) else {}
        priority = (
            leaf.get("research_priority")
            or requirements.get("research_priority")
            or legacy_weighting.get("research_priority")
            or legacy_weighting.get("static_information_weight")
            or "medium"
        )
        priority_reason_codes = leaf.get("priority_reason_codes")
        if not isinstance(priority_reason_codes, list):
            priority_reason_codes = legacy_weighting.get("priority_reason_codes") or legacy_weighting.get("weight_reason_codes") or []
        rows.append(
            {
                "decomposition_run_id": decomposition_run_id,
                "schema_version": QDT_PERSISTENCE_SCHEMA_VERSION,
                "case_key": qdt.get("case_key"),
                "case_id": qdt["case_id"],
                "market_id": qdt["market_id"],
                "dispatch_id": qdt["dispatch_id"],
                "qdt_artifact_id": qdt_artifact_id,
                "question_id": leaf["leaf_id"],
                "leaf_id": leaf["leaf_id"],
                "parent_branch_id": leaf["parent_branch_id"],
                "purpose": leaf["purpose"],
                "leaf_condition_scope": leaf["leaf_condition_scope"],
                "dependency_group_id": leaf["leaf_dependency_group_id"],
                "question": leaf["question_text"],
                "leaf_json_pointer": f"/required_leaf_questions/{idx}",
                "leaf_digest": _prefixed_sha256(leaf),
                "bayesian_weight_class": priority,
                "static_information_weight": priority,
                "information_weight": _weight_value(str(priority)),
                "weight_reason_codes": _json(priority_reason_codes),
                "required_evidence_fields": _json(leaf.get("required_evidence_fields", [])),
                "required_sufficiency_requirement_id": requirements["requirement_id"],
                "retrieval_breadth_profile_ref": requirements["retrieval_breadth_profile_ref"],
                "required_source_classes": _json(requirements["required_source_classes"]),
                "required_value_fields": _json(requirements["required_value_fields"]),
                "required_negative_checks": _json(requirements["required_negative_checks"]),
                "market_component_terms": _json(leaf.get("market_component_terms", [])),
                "structural_validation": _json(leaf.get("structural_validation", {})),
                "artifact_manifest_id": artifact_manifest_id,
                "question_digest": _prefixed_sha256(
                    {
                        "decomposition_run_id": decomposition_run_id,
                        "leaf": leaf,
                        "qdt_artifact_id": qdt_artifact_id,
                    }
                ),
            }
        )
    return rows


def _sufficiency_rows(
    qdt: dict[str, Any],
    *,
    decomposition_run_id: str,
    qdt_artifact_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for leaf in qdt["required_leaf_questions"]:
        requirements = leaf["research_sufficiency_requirements"]
        legacy_weighting = leaf.get("bayesian_weighting") if isinstance(leaf.get("bayesian_weighting"), dict) else {}
        priority = (
            leaf.get("research_priority")
            or requirements.get("research_priority")
            or legacy_weighting.get("research_priority")
            or legacy_weighting.get("static_information_weight")
            or "medium"
        )
        record_id = _stable_id(
            "qdt-sufficiency-record",
            decomposition_run_id,
            leaf["leaf_id"],
            requirements["requirement_id"],
        )
        rows.append(
            {
                "sufficiency_requirement_record_id": record_id,
                "schema_version": QDT_PERSISTENCE_SCHEMA_VERSION,
                "requirement_schema_version": requirements["schema_version"],
                "template_version": requirements["template_version"],
                "case_key": qdt.get("case_key"),
                "case_id": qdt["case_id"],
                "market_id": qdt["market_id"],
                "dispatch_id": qdt["dispatch_id"],
                "decomposition_run_id": decomposition_run_id,
                "qdt_artifact_id": qdt_artifact_id,
                "leaf_id": leaf["leaf_id"],
                "parent_branch_id": leaf["parent_branch_id"],
                "purpose": leaf["purpose"],
                "static_information_weight": priority,
                "leaf_condition_scope": leaf["leaf_condition_scope"],
                "requirement_id": requirements["requirement_id"],
                "sufficiency_profile_id": requirements["sufficiency_profile_id"],
                "target_answerability": requirements["target_answerability"],
                "retrieval_breadth_profile_ref": requirements["retrieval_breadth_profile_ref"],
                "required_source_classes": _json(requirements["required_source_classes"]),
                "protected_primary_required": _bool_int(requirements["protected_primary_required"]),
                "min_independent_claim_families": requirements["min_independent_claim_families"],
                "min_independent_source_families": requirements["min_independent_source_families"],
                "min_temporally_fresh_sources": requirements["min_temporally_fresh_sources"],
                "required_value_fields": _json(requirements["required_value_fields"]),
                "required_negative_checks": _json(requirements["required_negative_checks"]),
                "contradiction_search_required": _bool_int(requirements["contradiction_search_required"]),
                "recency_window_seconds": requirements["recency_window_seconds"],
                "max_targeted_expansion_attempts": requirements["max_targeted_expansion_attempts"],
                "allow_macro_fallback_for_leaf": _bool_int(requirements["allow_macro_fallback_for_leaf"]),
                "unanswerability_proof_required": _bool_int(requirements["unanswerability_proof_required"]),
                "classification_dispatch_requires_sufficiency_certificate": _bool_int(
                    requirements["classification_dispatch_requires_sufficiency_certificate"]
                ),
                "requirement_reason_codes": _json(requirements["requirement_reason_codes"]),
                "requirement_digest": _prefixed_sha256(requirements),
            }
        )
    return rows


def _anchor_rows(
    qdt: dict[str, Any],
    *,
    decomposition_run_id: str,
    qdt_artifact_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for contract in qdt.get("amrg_anchor_dependency_contracts", []):
        fallback = contract["fallback_policy"]
        slice_id = _stable_id(
            "qdt-anchor-dependency-slice",
            decomposition_run_id,
            contract["anchor_dependency_contract_id"],
        )
        rows.append(
            {
                "anchor_dependency_slice_id": slice_id,
                "schema_version": QDT_PERSISTENCE_SCHEMA_VERSION,
                "contract_schema_version": contract["schema_version"],
                "case_key": qdt.get("case_key"),
                "case_id": qdt["case_id"],
                "market_id": qdt["market_id"],
                "dispatch_id": qdt["dispatch_id"],
                "decomposition_run_id": decomposition_run_id,
                "qdt_artifact_id": qdt_artifact_id,
                "anchor_dependency_contract_id": contract["anchor_dependency_contract_id"],
                "edge_id": contract["edge_id"],
                "edge_status": contract["edge_status"],
                "related_market_ref": contract.get("related_market_ref"),
                "qdt_branch_id": contract.get("qdt_branch_id"),
                "conditional_branch_group_id": contract["conditional_branch_group_id"],
                "anchor_mode": contract["anchor_mode"],
                "condition_scoped_leaf_ids": _json(contract.get("condition_scoped_leaf_ids", [])),
                "required_before_leaf_ids": _json(contract.get("required_before_leaf_ids", [])),
                "fallback_policy_id": fallback["fallback_policy_id"],
                "fallback_mode": fallback["fallback_mode"],
                "fallback_leaf_ids": _json(fallback.get("fallback_leaf_ids", [])),
                "fallback_reason_codes": _json(fallback.get("fallback_reason_codes", [])),
                "max_anchor_repair_attempts": contract["max_anchor_repair_attempts"],
                "max_anchor_repair_wall_clock_seconds": contract["max_anchor_repair_wall_clock_seconds"],
                "repair_exhaustion_policy": contract["repair_exhaustion_policy"],
                "contract_digest": _prefixed_sha256(contract),
            }
        )
    return rows


def write_decomposition_run(
    conn: sqlite3.Connection,
    qdt: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
    qdt_artifact_id: str | None = None,
    qdt_artifact_ref: str | None = None,
    artifact_manifest_id: int | None = None,
    generated_at: str | None = None,
) -> str:
    """Persist the selected QDT run and required-leaf rows."""

    ensure_qdt_persistence_schema(conn)
    _require_valid_qdt(qdt)
    manifest_artifact_id, artifact_path, artifact_sha256, manifest_numeric_id, manifest_generated_at = _manifest_context(
        conn,
        manifest,
    )
    resolved_artifact_id = qdt_artifact_id or manifest_artifact_id or qdt_artifact_id_for(qdt)
    resolved_manifest_id = artifact_manifest_id if artifact_manifest_id is not None else manifest_numeric_id
    if (
        resolved_manifest_id is None
        and _table_column_not_null(conn, QDT_DECOMPOSITION_RUNS_TABLE, "artifact_manifest_id")
    ):
        raise QDTPersistenceError("artifact_manifest_id is required by existing qdt_decomposition_runs schema")
    decomposition_run_id = decomposition_run_id_for(qdt)
    run = _run_row(
        qdt,
        decomposition_run_id=decomposition_run_id,
        qdt_artifact_id=resolved_artifact_id,
        qdt_artifact_ref=qdt_artifact_ref or resolved_artifact_id,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        artifact_manifest_id=resolved_manifest_id,
        generated_at=generated_at or manifest_generated_at or utc_now_iso(),
    )
    _upsert(conn, QDT_DECOMPOSITION_RUNS_TABLE, run, ["decomposition_run_id"])
    for leaf_row in _leaf_rows(
        qdt,
        decomposition_run_id=decomposition_run_id,
        qdt_artifact_id=resolved_artifact_id,
        artifact_manifest_id=resolved_manifest_id,
    ):
        _upsert(
            conn,
            QDT_REQUIRED_RESEARCH_QUESTIONS_TABLE,
            leaf_row,
            ["decomposition_run_id", "question_id"],
        )
    return decomposition_run_id


def write_qdt_research_sufficiency_requirements(
    conn: sqlite3.Connection,
    qdt: dict[str, Any],
    *,
    decomposition_run_id: str | None = None,
    qdt_artifact_id: str | None = None,
) -> dict[str, list[str]]:
    """Persist per-leaf sufficiency requirement and QDT anchor dependency rows."""

    ensure_qdt_persistence_schema(conn)
    _require_valid_qdt(qdt)
    resolved_run_id = decomposition_run_id or decomposition_run_id_for(qdt)
    resolved_artifact_id = qdt_artifact_id or qdt_artifact_id_for(qdt)
    sufficiency_ids: list[str] = []
    for row in _sufficiency_rows(qdt, decomposition_run_id=resolved_run_id, qdt_artifact_id=resolved_artifact_id):
        _upsert(
            conn,
            QDT_LEAF_RESEARCH_SUFFICIENCY_REQUIREMENTS_TABLE,
            row,
            ["sufficiency_requirement_record_id"],
        )
        sufficiency_ids.append(row["sufficiency_requirement_record_id"])
    anchor_ids: list[str] = []
    for row in _anchor_rows(qdt, decomposition_run_id=resolved_run_id, qdt_artifact_id=resolved_artifact_id):
        if row["contract_schema_version"] != ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION:
            raise QDTPersistenceError("anchor dependency contract schema version is invalid")
        _upsert(
            conn,
            QDT_AMRG_ANCHOR_DEPENDENCY_SLICES_TABLE,
            row,
            ["anchor_dependency_slice_id"],
        )
        anchor_ids.append(row["anchor_dependency_slice_id"])
    return {
        "sufficiency_requirement_record_ids": sufficiency_ids,
        "anchor_dependency_slice_ids": anchor_ids,
    }


__all__ = [
    "MIG_003_QDT_PERSISTENCE_MIGRATION",
    "QDT_AMRG_ANCHOR_DEPENDENCY_SLICES_TABLE",
    "QDT_DECOMPOSITION_RUNS_TABLE",
    "QDT_LEAF_RESEARCH_SUFFICIENCY_REQUIREMENTS_TABLE",
    "QDT_PERSISTENCE_SCHEMA_VERSION",
    "QDT_REQUIRED_RESEARCH_QUESTIONS_TABLE",
    "QDTPersistenceError",
    "decomposition_run_id_for",
    "ensure_qdt_persistence_schema",
    "qdt_artifact_id_for",
    "write_decomposition_run",
    "write_qdt_research_sufficiency_requirements",
]
