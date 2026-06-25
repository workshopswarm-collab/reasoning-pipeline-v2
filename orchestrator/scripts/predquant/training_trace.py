"""Minimal non-authoritative training trace pointer contract for ADS v2."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model_provenance_trace import ModelProvenanceTraceError, build_model_provenance_trace


TRAINING_TRACE_MINIMAL_TABLE = "training_trace_minimal_pointers"
TRAINING_TRACE_MINIMAL_SCHEMA_VERSION = "training-trace-minimal-pointer/v1"
TRAINING_TRACE_MINIMAL_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "007_training_trace_minimal_pointer.sql"
)

TRACE_STATUS_MINIMAL_POINTER_WRITTEN = "minimal_pointer_written"
MATERIALIZATION_STATUS_NOT_MATERIALIZED = "not_materialized"
NO_LIVE_AUTHORITY = "none"
SESSION5_TRACE_HANDOFF_SCHEMA_VERSION = "session5-minimal-trace-handoff/v1"
SESSION5_TRACE_REQUIRED_ARTIFACT_ROLES = ("research", "scae", "decision")

FORBIDDEN_TRACE_AUTHORITY_FIELDS = frozenset(
    {
        "probability",
        "probability_estimate",
        "forecast_probability",
        "forecast_prob",
        "production_forecast_prob",
        "replacement_probability",
        "fair_value",
        "interval",
        "confidence_interval",
        "reassembly",
        "decision_recommendation",
        "recommended_decision",
        "probability_override",
        "upgraded_scae_validity",
        "scae_validity_override",
    }
)

FORBIDDEN_TRACE_METADATA_KEYS = FORBIDDEN_TRACE_AUTHORITY_FIELDS | {
    "raw_payload",
    "payload",
    "raw_content",
    "content",
    "body",
    "html",
    "page_text",
    "stdout",
    "stderr",
    "traceback",
    "browser_log",
}

TRACE_REQUIRED_FIELDS = (
    "schema_version",
    "table",
    "trace_id",
    "case_id",
    "case_key",
    "dispatch_id",
    "run_id",
    "forecast_timestamp",
    "artifact_manifest_ids",
    "artifact_hashes",
    "trace_status",
    "live_authority",
    "live_forecast_authority",
    "materialization_status",
    "created_at",
    "metadata",
)

TRACE_ALLOWED_FIELDS = set(TRACE_REQUIRED_FIELDS)
TRACE_ALLOWED_FIELDS.update(
    {
        "trace_pointer_id",
        "pointer_artifact_id",
        "forecast_authority",
        "stage_status_snapshot_ids",
    }
)

TRACE_COMPAT_COLUMNS = {
    "trace_id": "TEXT",
    "schema_version": "TEXT",
    "case_key": "TEXT",
    "dispatch_id": "TEXT",
    "forecast_timestamp": "TEXT",
    "artifact_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
    "artifact_hashes": "TEXT NOT NULL DEFAULT '{}'",
    "trace_status": "TEXT",
    "live_authority": "TEXT",
    "live_forecast_authority": "INTEGER NOT NULL DEFAULT 0",
    "updated_at": "TEXT",
}


class TrainingTraceContractError(ValueError):
    """Raised when a minimal training trace pointer is unsafe or invalid."""


@dataclass(frozen=True)
class TrainingTraceContext:
    case_id: str
    case_key: str | None
    dispatch_id: str
    run_id: str
    forecast_timestamp: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise TrainingTraceContractError(f"{field} is required")
    return value


def require_list(field: str, value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise TrainingTraceContractError(f"{field} must be a list of non-empty strings")
    return list(value)


def require_mapping(field: str, value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TrainingTraceContractError(f"{field} must be an object")
    return dict(value)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_no_forbidden_trace_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_TRACE_AUTHORITY_FIELDS:
                raise TrainingTraceContractError(f"{path}.{key} may not author or replace forecast probability")
            ensure_no_forbidden_trace_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_forbidden_trace_fields(child, f"{path}[{idx}]")


def ensure_safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = require_mapping("metadata", metadata)

    def check(value: Any, path: str = "metadata") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise TrainingTraceContractError(f"{path} contains an invalid key")
                if key.lower() in FORBIDDEN_TRACE_METADATA_KEYS:
                    raise TrainingTraceContractError(f"{path}.{key} is forbidden in a minimal trace pointer")
                check(child, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                check(child, f"{path}[{idx}]")
        elif value is None or isinstance(value, (bool, int, float, str)):
            return
        else:
            raise TrainingTraceContractError(f"{path} contains unsupported metadata type {type(value).__name__}")

    check(metadata)
    if len(canonical_json(metadata).encode("utf-8")) > 8192:
        raise TrainingTraceContractError("metadata is too large")
    return metadata


def normalize_artifact_manifests(artifact_manifests: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> tuple[list[str], dict[str, str]]:
    if not isinstance(artifact_manifests, (list, tuple)) or not artifact_manifests:
        raise TrainingTraceContractError("artifact_manifests must contain at least one manifest pointer")

    artifact_ids: list[str] = []
    artifact_hashes: dict[str, str] = {}
    for idx, manifest in enumerate(artifact_manifests):
        if not isinstance(manifest, dict):
            raise TrainingTraceContractError(f"artifact_manifests[{idx}] must be an object")
        artifact_id = require_non_empty(
            f"artifact_manifests[{idx}].artifact_id",
            manifest.get("artifact_id"),
        )
        artifact_hash = require_non_empty(
            f"artifact_manifests[{idx}].sha256",
            manifest.get("sha256") or manifest.get("artifact_sha256"),
        )
        if not artifact_hash.startswith("sha256:"):
            raise TrainingTraceContractError(f"artifact_manifests[{idx}].sha256 must start with sha256:")
        if artifact_id in artifact_hashes:
            raise TrainingTraceContractError(f"duplicate artifact manifest pointer: {artifact_id}")
        artifact_ids.append(artifact_id)
        artifact_hashes[artifact_id] = artifact_hash
    return artifact_ids, artifact_hashes


def infer_session5_trace_artifact_role(manifest: dict[str, Any]) -> str | None:
    explicit_role = manifest.get("trace_role") or manifest.get("artifact_role") or manifest.get("role")
    if explicit_role:
        role = str(explicit_role).lower().replace("_", "-")
        if role in {"research", "research-artifact", "research-handoff", "researcher"}:
            return "research"
        if role in {"scae", "scae-ledger", "scae-artifact"}:
            return "scae"
        if role in {"decision", "decision-gate", "forecast-decision"}:
            return "decision"
        raise TrainingTraceContractError(f"unknown Session 5 trace artifact role: {explicit_role}")

    for field in ("stage", "artifact_type"):
        value = manifest.get(field)
        if not value:
            continue
        text = str(value).lower().replace("_", "-")
        if "scae" in text:
            return "scae"
        if "decision" in text:
            return "decision"
        if any(token in text for token in ("research", "retrieval", "evidence", "classification", "verification")):
            return "research"
    return None


def session5_artifact_role_refs(
    artifact_manifests: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> dict[str, list[dict[str, str]]]:
    """Validate the bounded Session 5 trace handoff surface.

    This adapter keeps the FND-007 trace pointer contract authoritative while
    adding Session 5's synchronous handoff requirement that research, SCAE, and
    decision artifacts are represented by manifest IDs and hashes.
    """

    ensure_no_forbidden_trace_fields(artifact_manifests, "artifact_manifests")
    _, artifact_hashes = normalize_artifact_manifests(artifact_manifests)
    role_refs: dict[str, list[dict[str, str]]] = {role: [] for role in SESSION5_TRACE_REQUIRED_ARTIFACT_ROLES}
    for idx, manifest in enumerate(artifact_manifests):
        artifact_id = require_non_empty(f"artifact_manifests[{idx}].artifact_id", manifest.get("artifact_id"))
        role = infer_session5_trace_artifact_role(manifest)
        if role in role_refs:
            role_refs[role].append({"artifact_id": artifact_id, "sha256": artifact_hashes[artifact_id]})

    missing = [role for role in SESSION5_TRACE_REQUIRED_ARTIFACT_ROLES if not role_refs[role]]
    if missing:
        raise TrainingTraceContractError(
            "Session 5 minimal trace pointer missing required artifact roles: " + ", ".join(missing)
        )
    return role_refs


def build_session5_minimal_training_trace(
    *,
    context: TrainingTraceContext,
    artifact_manifests: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    trace_id: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    model_execution_contexts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    role_refs = session5_artifact_role_refs(artifact_manifests)
    base_metadata = ensure_safe_metadata(metadata)
    trace_metadata: dict[str, Any] = {
        "session5_handoff": {
            "schema_version": SESSION5_TRACE_HANDOFF_SCHEMA_VERSION,
            "trace_scope": "synchronous_minimal_trace_pointer",
            "required_artifact_roles": list(SESSION5_TRACE_REQUIRED_ARTIFACT_ROLES),
            "artifact_role_refs": role_refs,
            "non_authoritative": True,
            "no_live_authority": True,
            "no_production_probability_authoring": True,
            "no_replay_scoring_or_calibration_writes": True,
        }
    }
    if model_execution_contexts is not None:
        try:
            trace_metadata["model_provenance_trace"] = build_model_provenance_trace(
                model_execution_contexts=model_execution_contexts
            )
        except ModelProvenanceTraceError as exc:
            raise TrainingTraceContractError(str(exc)) from exc
    if base_metadata:
        trace_metadata["caller_metadata"] = base_metadata
    return build_minimal_training_trace(
        context=context,
        artifact_manifests=artifact_manifests,
        trace_id=trace_id,
        created_at=created_at,
        metadata=trace_metadata,
    )


def write_session5_minimal_training_trace(
    conn: sqlite3.Connection,
    *,
    context: TrainingTraceContext,
    artifact_manifests: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    trace_id: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    model_execution_contexts: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> str:
    trace = build_session5_minimal_training_trace(
        context=context,
        artifact_manifests=artifact_manifests,
        trace_id=trace_id,
        created_at=created_at,
        metadata=metadata,
        model_execution_contexts=model_execution_contexts,
    )
    return write_minimal_training_trace(conn, trace)


def make_trace_id(context: TrainingTraceContext, artifact_hashes: dict[str, str]) -> str:
    seed = canonical_json(
        {
            "case_id": context.case_id,
            "dispatch_id": context.dispatch_id,
            "run_id": context.run_id,
            "forecast_timestamp": context.forecast_timestamp,
            "artifact_hashes": artifact_hashes,
        }
    )
    return "training-trace:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_minimal_training_trace(
    *,
    context: TrainingTraceContext,
    artifact_manifests: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    trace_id: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_non_empty("case_id", context.case_id)
    require_non_empty("dispatch_id", context.dispatch_id)
    require_non_empty("run_id", context.run_id)
    require_non_empty("forecast_timestamp", context.forecast_timestamp)
    artifact_manifest_ids, artifact_hashes = normalize_artifact_manifests(artifact_manifests)
    trace = {
        "schema_version": TRAINING_TRACE_MINIMAL_SCHEMA_VERSION,
        "table": TRAINING_TRACE_MINIMAL_TABLE,
        "trace_id": trace_id or make_trace_id(context, artifact_hashes),
        "case_id": context.case_id,
        "case_key": context.case_key,
        "dispatch_id": context.dispatch_id,
        "run_id": context.run_id,
        "forecast_timestamp": context.forecast_timestamp,
        "artifact_manifest_ids": artifact_manifest_ids,
        "artifact_hashes": artifact_hashes,
        "trace_status": TRACE_STATUS_MINIMAL_POINTER_WRITTEN,
        "live_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "materialization_status": MATERIALIZATION_STATUS_NOT_MATERIALIZED,
        "created_at": created_at or utc_now_iso(),
        "metadata": ensure_safe_metadata(metadata),
    }
    validate_minimal_training_trace(trace)
    return trace


def validate_minimal_training_trace(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise TrainingTraceContractError("training trace pointer must be an object")
    ensure_no_forbidden_trace_fields(record)
    for field in record:
        if field not in TRACE_ALLOWED_FIELDS:
            raise TrainingTraceContractError(f"unexpected training trace field: {field}")
    for field in TRACE_REQUIRED_FIELDS:
        if field not in record:
            raise TrainingTraceContractError(f"{field} is required")
    if record["schema_version"] != TRAINING_TRACE_MINIMAL_SCHEMA_VERSION:
        raise TrainingTraceContractError(f"schema_version must be {TRAINING_TRACE_MINIMAL_SCHEMA_VERSION}")
    if record["table"] != TRAINING_TRACE_MINIMAL_TABLE:
        raise TrainingTraceContractError(f"table must be {TRAINING_TRACE_MINIMAL_TABLE}")
    for field in ("trace_id", "case_id", "dispatch_id", "run_id", "forecast_timestamp", "created_at"):
        require_non_empty(field, record[field])
    if record["case_key"] is not None and not isinstance(record["case_key"], str):
        raise TrainingTraceContractError("case_key must be a string when present")

    artifact_manifest_ids = require_list("artifact_manifest_ids", record["artifact_manifest_ids"])
    if not artifact_manifest_ids:
        raise TrainingTraceContractError("artifact_manifest_ids are required")
    artifact_hashes = require_mapping("artifact_hashes", record["artifact_hashes"])
    if set(artifact_hashes) != set(artifact_manifest_ids):
        raise TrainingTraceContractError("artifact_hashes must match artifact_manifest_ids exactly")
    for artifact_id, artifact_hash in artifact_hashes.items():
        require_non_empty("artifact_hashes key", artifact_id)
        require_non_empty(f"artifact_hashes[{artifact_id}]", artifact_hash)
        if not artifact_hash.startswith("sha256:"):
            raise TrainingTraceContractError(f"artifact_hashes[{artifact_id}] must start with sha256:")

    if record["trace_status"] != TRACE_STATUS_MINIMAL_POINTER_WRITTEN:
        raise TrainingTraceContractError(f"trace_status must be {TRACE_STATUS_MINIMAL_POINTER_WRITTEN}")
    if record["live_authority"] != NO_LIVE_AUTHORITY:
        raise TrainingTraceContractError("minimal trace pointer has no live authority")
    if record["live_forecast_authority"] not in (False, 0):
        raise TrainingTraceContractError("minimal trace pointer cannot have live forecast authority")
    if record["materialization_status"] != MATERIALIZATION_STATUS_NOT_MATERIALIZED:
        raise TrainingTraceContractError(f"materialization_status must be {MATERIALIZATION_STATUS_NOT_MATERIALIZED}")
    ensure_safe_metadata(record["metadata"])


def ensure_training_trace_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TRAINING_TRACE_MINIMAL_MIGRATION.read_text(encoding="utf-8"))
    existing = table_columns(conn, TRAINING_TRACE_MINIMAL_TABLE)
    for column, definition in TRACE_COMPAT_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {TRAINING_TRACE_MINIMAL_TABLE} ADD COLUMN {column} {definition}")
    conn.executescript(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_training_trace_minimal_trace_id
          ON {TRAINING_TRACE_MINIMAL_TABLE}(trace_id);
        CREATE INDEX IF NOT EXISTS idx_training_trace_minimal_case_dispatch
          ON {TRAINING_TRACE_MINIMAL_TABLE}(case_id, dispatch_id, run_id);
        CREATE INDEX IF NOT EXISTS idx_training_trace_minimal_status
          ON {TRAINING_TRACE_MINIMAL_TABLE}(trace_status, materialization_status);
        """
    )


def write_minimal_training_trace(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    validate_minimal_training_trace(record)
    ensure_training_trace_schema(conn)
    available = table_columns(conn, TRAINING_TRACE_MINIMAL_TABLE)
    values = {
        "trace_id": record["trace_id"],
        "trace_pointer_id": record["trace_id"],
        "schema_version": record["schema_version"],
        "case_id": record["case_id"],
        "case_key": record["case_key"],
        "dispatch_id": record["dispatch_id"],
        "run_id": record["run_id"],
        "forecast_timestamp": record["forecast_timestamp"],
        "artifact_manifest_ids": canonical_json(record["artifact_manifest_ids"]),
        "artifact_hashes": canonical_json(record["artifact_hashes"]),
        "trace_status": record["trace_status"],
        "live_authority": record["live_authority"],
        "live_forecast_authority": 1 if record["live_forecast_authority"] else 0,
        "materialization_status": record["materialization_status"],
        "forecast_authority": record["live_authority"],
        "pointer_artifact_id": record["trace_id"],
        "stage_status_snapshot_ids": canonical_json([]),
        "created_at": record["created_at"],
        "metadata": canonical_json(record["metadata"]),
    }
    insert_columns = [column for column in values if column in available]
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [
        column
        for column in insert_columns
        if column not in {"trace_id", "trace_pointer_id", "created_at"}
    ]
    if "updated_at" in available:
        update_columns.append("updated_at")
    update_clause = ",\n          ".join(
        "updated_at=CURRENT_TIMESTAMP" if column == "updated_at" else f"{column}=excluded.{column}"
        for column in update_columns
    )
    conn.execute(
        f"""
        INSERT INTO {TRAINING_TRACE_MINIMAL_TABLE} ({", ".join(insert_columns)})
        VALUES ({placeholders})
        ON CONFLICT(trace_id) DO UPDATE SET
          {update_clause}
        """,
        tuple(values[column] for column in insert_columns),
    )
    return record["trace_id"]
