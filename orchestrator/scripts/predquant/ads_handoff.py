"""ADS v2 artifact manifest and handoff validation helpers."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARTIFACT_MANIFEST_TABLE = "case_artifact_manifest"
ARTIFACT_VALIDATION_RESULTS_TABLE = "artifact_validation_results"
ARTIFACT_MANIFEST_SCHEMA_VERSION = "artifact-manifest/v1"
ARTIFACT_VALIDATION_RESULT_SCHEMA_VERSION = "artifact-validation-result/v1"
ARTIFACT_MANIFEST_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "003_artifact_manifest_contract.sql"
)

VALIDATION_STATUSES = (
    "valid",
    "valid_with_warnings",
    "invalid_retryable",
    "invalid_terminal",
    "waived_by_policy",
    "not_applicable",
    "not_validated",
)

TEMPORAL_ISOLATION_STATUSES = ("pass", "fail", "not_applicable")
MAX_SAFE_METADATA_BYTES = 8192
MAX_SAFE_METADATA_STRING_BYTES = 4096
FORBIDDEN_METADATA_KEYS = {
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
OPTIONAL_MANIFEST_FIELDS = {
    "table",
    "stage_attempt_id",
    "pipeline_run_id",
    "validator_version",
}

ARTIFACT_MANIFEST_COMPAT_COLUMNS = {
    "artifact_id": "TEXT",
    "artifact_schema_version": "TEXT",
    "stage": "TEXT",
    "stage_attempt_id": "TEXT",
    "pipeline_run_id": "TEXT",
    "market_id": "TEXT",
    "feature_id": "TEXT",
    "producer": "TEXT",
    "producer_stage": "TEXT",
    "schema_id": "TEXT",
    "generated_at": "TEXT",
    "forecast_timestamp": "TEXT",
    "source_cutoff_timestamp": "TEXT",
    "input_manifest_ids": "TEXT NOT NULL DEFAULT '[]'",
    "validation_status": "TEXT",
    "validation_result_refs": "TEXT NOT NULL DEFAULT '[]'",
    "validator_version": "TEXT",
    "temporal_isolation_status": "TEXT",
    "sha256": "TEXT",
    "replay_command": "TEXT",
    "metadata": "TEXT NOT NULL DEFAULT '{}'",
    "updated_at": "TEXT",
}


class ArtifactManifestError(ValueError):
    """Raised when an artifact manifest or validation result is unsafe or invalid."""


@dataclass(frozen=True)
class ArtifactManifestContext:
    case_id: str
    case_key: str
    dispatch_id: str
    stage: str
    producer: str
    forecast_timestamp: str
    source_cutoff_timestamp: str
    generated_at: str | None = None
    stage_attempt_id: str | None = None
    pipeline_run_id: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactManifestError(f"{field} is required")
    return value


def require_list(field: str, value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise ArtifactManifestError(f"{field} must be a list of non-empty strings")
    return list(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_artifact_manifest_schema(conn: sqlite3.Connection) -> None:
    """Create or upgrade the ADS artifact manifest surfaces.

    Older Orchestrator bootstrap code created a compact legacy
    `case_artifact_manifest` table. This helper adds the Phase 3 columns and
    indexes in place so component migrations can safely reference it.
    """

    conn.execute("PRAGMA foreign_keys = ON")
    if not table_exists(conn, ARTIFACT_MANIFEST_TABLE):
        conn.executescript(ARTIFACT_MANIFEST_MIGRATION.read_text(encoding="utf-8"))

    existing = table_columns(conn, ARTIFACT_MANIFEST_TABLE)
    for column, definition in ARTIFACT_MANIFEST_COMPAT_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {ARTIFACT_MANIFEST_TABLE} ADD COLUMN {column} {definition}")

    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_case_artifact_manifest_artifact_id
          ON case_artifact_manifest(artifact_id);
        CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_case_dispatch
          ON case_artifact_manifest(case_id, dispatch_id, stage);
        CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_type_schema
          ON case_artifact_manifest(artifact_type, artifact_schema_version);
        CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_digest
          ON case_artifact_manifest(artifact_sha256);

        CREATE TABLE IF NOT EXISTS artifact_validation_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          validation_result_id TEXT NOT NULL UNIQUE,
          schema_version TEXT NOT NULL,
          artifact_id TEXT NOT NULL,
          status TEXT NOT NULL,
          validator_version TEXT NOT NULL,
          validated_at TEXT NOT NULL,
          reason_codes TEXT NOT NULL DEFAULT '[]',
          validation_messages TEXT NOT NULL DEFAULT '[]',
          metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (artifact_id) REFERENCES case_artifact_manifest(artifact_id)
        );

        CREATE INDEX IF NOT EXISTS idx_artifact_validation_results_artifact
          ON artifact_validation_results(artifact_id, status);
        """
    )


def ensure_safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ArtifactManifestError("metadata must be an object")

    def check(value: Any, path: str = "metadata") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or not key:
                    raise ArtifactManifestError(f"{path} contains an invalid key")
                if key.lower() in FORBIDDEN_METADATA_KEYS:
                    raise ArtifactManifestError(f"{path}.{key} may not store raw payload/log content")
                check(child, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                check(child, f"{path}[{idx}]")
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > MAX_SAFE_METADATA_STRING_BYTES:
                raise ArtifactManifestError(f"{path} string is too large for safe metadata")
        elif value is None or isinstance(value, (bool, int, float)):
            return
        else:
            raise ArtifactManifestError(f"{path} contains unsupported metadata type {type(value).__name__}")

    check(metadata)
    if len(canonical_json(metadata).encode("utf-8")) > MAX_SAFE_METADATA_BYTES:
        raise ArtifactManifestError("metadata is too large for artifact manifest storage")
    return dict(metadata)


def file_sha256(path: Path | str) -> str:
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise ArtifactManifestError(f"artifact path is missing or not a file: {artifact_path}")
    digest = hashlib.sha256()
    with artifact_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def make_artifact_id(
    *,
    case_id: str,
    dispatch_id: str,
    artifact_type: str,
    artifact_path: str,
    artifact_sha256: str,
) -> str:
    seed = "|".join([case_id, dispatch_id, artifact_type, artifact_path, artifact_sha256])
    return "artifact:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def validate_validation_status(status: str) -> str:
    if status not in VALIDATION_STATUSES:
        raise ArtifactManifestError(f"unknown validation status: {status}")
    return status


def validate_temporal_isolation_status(status: str) -> str:
    if status not in TEMPORAL_ISOLATION_STATUSES:
        raise ArtifactManifestError(f"unknown temporal isolation status: {status}")
    return status


def build_artifact_manifest(
    *,
    context: ArtifactManifestContext,
    artifact_type: str,
    artifact_schema_version: str,
    path: Path | str,
    input_manifest_ids: list[str] | tuple[str, ...] | None = None,
    validation_status: str = "not_validated",
    validation_result_refs: list[str] | tuple[str, ...] | None = None,
    validator_version: str | None = None,
    temporal_isolation_status: str = "not_applicable",
    metadata: dict[str, Any] | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    artifact_path = str(Path(path))
    digest = file_sha256(path)
    case_id = require_non_empty("case_id", context.case_id)
    dispatch_id = require_non_empty("dispatch_id", context.dispatch_id)
    manifest = {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "table": ARTIFACT_MANIFEST_TABLE,
        "artifact_id": artifact_id
        or make_artifact_id(
            case_id=case_id,
            dispatch_id=dispatch_id,
            artifact_type=require_non_empty("artifact_type", artifact_type),
            artifact_path=artifact_path,
            artifact_sha256=digest,
        ),
        "artifact_type": require_non_empty("artifact_type", artifact_type),
        "artifact_schema_version": require_non_empty("artifact_schema_version", artifact_schema_version),
        "case_id": case_id,
        "case_key": require_non_empty("case_key", context.case_key),
        "dispatch_id": dispatch_id,
        "stage": require_non_empty("stage", context.stage),
        "stage_attempt_id": context.stage_attempt_id,
        "pipeline_run_id": context.pipeline_run_id,
        "producer": require_non_empty("producer", context.producer),
        "path": artifact_path,
        "sha256": digest,
        "generated_at": context.generated_at or utc_now_iso(),
        "forecast_timestamp": require_non_empty("forecast_timestamp", context.forecast_timestamp),
        "source_cutoff_timestamp": require_non_empty("source_cutoff_timestamp", context.source_cutoff_timestamp),
        "input_manifest_ids": require_list("input_manifest_ids", input_manifest_ids),
        "validation_status": validate_validation_status(validation_status),
        "validation_result_refs": require_list("validation_result_refs", validation_result_refs),
        "validator_version": validator_version,
        "temporal_isolation_status": validate_temporal_isolation_status(temporal_isolation_status),
        "metadata": ensure_safe_metadata(metadata),
    }
    validate_artifact_manifest(manifest)
    return manifest


def validate_artifact_manifest(
    manifest: dict[str, Any],
    *,
    expected_artifact_schema_version: str | None = None,
    expected_sha256: str | None = None,
    check_digest: bool = True,
) -> None:
    if not isinstance(manifest, dict):
        raise ArtifactManifestError("manifest must be an object")
    required = (
        "schema_version",
        "artifact_id",
        "artifact_type",
        "artifact_schema_version",
        "case_id",
        "case_key",
        "dispatch_id",
        "stage",
        "producer",
        "path",
        "sha256",
        "generated_at",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "input_manifest_ids",
        "validation_status",
        "validation_result_refs",
        "temporal_isolation_status",
        "metadata",
    )
    allowed = set(required) | OPTIONAL_MANIFEST_FIELDS
    for field in manifest:
        if field.lower() in FORBIDDEN_METADATA_KEYS:
            raise ArtifactManifestError(f"{field} may not store raw payload/log content")
        if field not in allowed:
            raise ArtifactManifestError(f"unexpected artifact manifest field: {field}")

    for field in required:
        if field not in manifest:
            raise ArtifactManifestError(f"{field} is required")

    if manifest["schema_version"] != ARTIFACT_MANIFEST_SCHEMA_VERSION:
        raise ArtifactManifestError(f"schema_version must be {ARTIFACT_MANIFEST_SCHEMA_VERSION}")
    for field in (
        "artifact_id",
        "artifact_type",
        "artifact_schema_version",
        "case_id",
        "case_key",
        "dispatch_id",
        "stage",
        "producer",
        "path",
        "sha256",
        "generated_at",
        "forecast_timestamp",
        "source_cutoff_timestamp",
    ):
        require_non_empty(field, manifest[field])
    if not manifest["sha256"].startswith("sha256:"):
        raise ArtifactManifestError("sha256 must start with sha256:")
    if expected_artifact_schema_version and manifest["artifact_schema_version"] != expected_artifact_schema_version:
        raise ArtifactManifestError("artifact schema version does not match expected value")
    if expected_sha256 and manifest["sha256"] != expected_sha256:
        raise ArtifactManifestError("artifact sha256 does not match expected value")
    if check_digest:
        actual_sha256 = file_sha256(manifest["path"])
        if actual_sha256 != manifest["sha256"]:
            raise ArtifactManifestError("artifact digest mismatch")
    require_list("input_manifest_ids", manifest["input_manifest_ids"])
    validate_validation_status(manifest["validation_status"])
    require_list("validation_result_refs", manifest["validation_result_refs"])
    validate_temporal_isolation_status(manifest["temporal_isolation_status"])
    ensure_safe_metadata(manifest["metadata"])


def build_validation_result(
    *,
    artifact_id: str,
    status: str,
    validator_version: str,
    reason_codes: list[str] | tuple[str, ...] | None = None,
    validation_messages: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
    validation_result_id: str | None = None,
    validated_at: str | None = None,
) -> dict[str, Any]:
    artifact_id = require_non_empty("artifact_id", artifact_id)
    status = validate_validation_status(status)
    result_id_seed = "|".join([artifact_id, status, require_non_empty("validator_version", validator_version)])
    result = {
        "schema_version": ARTIFACT_VALIDATION_RESULT_SCHEMA_VERSION,
        "table": ARTIFACT_VALIDATION_RESULTS_TABLE,
        "validation_result_id": validation_result_id
        or "artifact-validation:" + hashlib.sha256(result_id_seed.encode("utf-8")).hexdigest(),
        "artifact_id": artifact_id,
        "status": status,
        "validator_version": validator_version,
        "validated_at": validated_at or utc_now_iso(),
        "reason_codes": require_list("reason_codes", reason_codes),
        "validation_messages": require_list("validation_messages", validation_messages),
        "metadata": ensure_safe_metadata(metadata),
    }
    validate_validation_result(result)
    return result


def validate_validation_result(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ArtifactManifestError("validation result must be an object")
    required = (
        "schema_version",
        "validation_result_id",
        "artifact_id",
        "status",
        "validator_version",
        "validated_at",
        "reason_codes",
        "validation_messages",
        "metadata",
    )
    for field in result:
        if field.lower() in FORBIDDEN_METADATA_KEYS:
            raise ArtifactManifestError(f"{field} may not store raw payload/log content")
        if field not in required and field != "table":
            raise ArtifactManifestError(f"unexpected validation result field: {field}")

    for field in required:
        if field not in result:
            raise ArtifactManifestError(f"{field} is required")
    if result["schema_version"] != ARTIFACT_VALIDATION_RESULT_SCHEMA_VERSION:
        raise ArtifactManifestError(f"schema_version must be {ARTIFACT_VALIDATION_RESULT_SCHEMA_VERSION}")
    require_non_empty("validation_result_id", result["validation_result_id"])
    require_non_empty("artifact_id", result["artifact_id"])
    validate_validation_status(result["status"])
    require_non_empty("validator_version", result["validator_version"])
    require_non_empty("validated_at", result["validated_at"])
    require_list("reason_codes", result["reason_codes"])
    require_list("validation_messages", result["validation_messages"])
    ensure_safe_metadata(result["metadata"])


def write_artifact_manifest(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    validation_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> str:
    return write_artifact_manifest_with_validation(conn, manifest, validation_results)


def write_artifact_manifest_with_validation(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    validation_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> str:
    manifest_to_write = dict(manifest)
    validation_rows: list[dict[str, Any]] = []
    if validation_results is not None:
        if not isinstance(validation_results, (list, tuple)):
            raise ArtifactManifestError("validation_results must be a list of validation result objects")
        for result in validation_results:
            validate_validation_result(result)
            if result["artifact_id"] != manifest_to_write.get("artifact_id"):
                raise ArtifactManifestError("validation result artifact_id must match artifact manifest")
            validation_rows.append(dict(result))
        manifest_to_write["validation_result_refs"] = [
            result["validation_result_id"] for result in validation_rows
        ]
        if validation_rows:
            manifest_to_write["validation_status"] = validation_rows[-1]["status"]
            manifest_to_write["validator_version"] = validation_rows[-1]["validator_version"]

    validate_artifact_manifest(manifest_to_write)
    ensure_artifact_manifest_schema(conn)
    for result in validation_rows:
        existing_result = conn.execute(
            """
            SELECT artifact_id FROM artifact_validation_results
            WHERE validation_result_id = ?
            """,
            (result["validation_result_id"],),
        ).fetchone()
        if existing_result is not None and existing_result[0] != result["artifact_id"]:
            raise ArtifactManifestError("validation_result_id is already linked to another artifact")
    available = table_columns(conn, ARTIFACT_MANIFEST_TABLE)
    values = {
        "artifact_id": manifest_to_write["artifact_id"],
        "schema_version": manifest_to_write["schema_version"],
        "artifact_type": manifest_to_write["artifact_type"],
        "artifact_schema_version": manifest_to_write["artifact_schema_version"],
        "case_id": manifest_to_write["case_id"],
        "case_key": manifest_to_write["case_key"],
        "dispatch_id": manifest_to_write["dispatch_id"],
        "stage": manifest_to_write["stage"],
        "stage_attempt_id": manifest_to_write.get("stage_attempt_id"),
        "pipeline_run_id": manifest_to_write.get("pipeline_run_id"),
        "producer": manifest_to_write["producer"],
        "artifact_path": manifest_to_write["path"],
        "artifact_sha256": manifest_to_write["sha256"],
        "generated_at": manifest_to_write["generated_at"],
        "forecast_timestamp": manifest_to_write["forecast_timestamp"],
        "source_cutoff_timestamp": manifest_to_write["source_cutoff_timestamp"],
        "input_manifest_ids": canonical_json(manifest_to_write["input_manifest_ids"]),
        "validation_status": manifest_to_write["validation_status"],
        "validation_result_refs": canonical_json(manifest_to_write["validation_result_refs"]),
        "validator_version": manifest_to_write.get("validator_version"),
        "temporal_isolation_status": manifest_to_write["temporal_isolation_status"],
        "metadata": canonical_json(manifest_to_write["metadata"]),
    }
    legacy_values = {
        "schema_id": manifest_to_write["artifact_schema_version"],
        "producer_stage": manifest_to_write["stage"],
        "sha256": manifest_to_write["sha256"],
        "feature_id": manifest_to_write["stage"],
        "market_id": manifest_to_write["metadata"].get("market_id"),
        "replay_command": "",
    }
    values.update({key: value for key, value in legacy_values.items() if key in available})

    insert_columns = [column for column in values if column in available]
    placeholders = ", ".join("?" for _ in insert_columns)
    update_columns = [
        column
        for column in (
            "validation_status",
            "validation_result_refs",
            "validator_version",
            "temporal_isolation_status",
            "metadata",
            "artifact_path",
            "artifact_sha256",
            "sha256",
        )
        if column in insert_columns
    ]
    update_clause = ",\n          ".join(f"{column}=excluded.{column}" for column in update_columns)
    if "updated_at" in available:
        update_clause = (update_clause + ",\n          " if update_clause else "") + "updated_at=CURRENT_TIMESTAMP"
    conn.execute(
        f"""
        INSERT INTO {ARTIFACT_MANIFEST_TABLE} ({", ".join(insert_columns)})
        VALUES ({placeholders})
        ON CONFLICT(artifact_id) DO UPDATE SET
          {update_clause}
        """,
        tuple(values[column] for column in insert_columns),
    )
    for result in validation_rows:
        write_validation_result(conn, result)
    return manifest_to_write["artifact_id"]


def write_validation_result(conn: sqlite3.Connection, result: dict[str, Any]) -> str:
    validate_validation_result(result)
    ensure_artifact_manifest_schema(conn)
    existing_manifest = conn.execute(
        f"SELECT 1 FROM {ARTIFACT_MANIFEST_TABLE} WHERE artifact_id = ?",
        (result["artifact_id"],),
    ).fetchone()
    if existing_manifest is None:
        raise ArtifactManifestError("validation result references unknown artifact_id")
    existing_result = conn.execute(
        """
        SELECT artifact_id FROM artifact_validation_results
        WHERE validation_result_id = ?
        """,
        (result["validation_result_id"],),
    ).fetchone()
    if existing_result is not None and existing_result[0] != result["artifact_id"]:
        raise ArtifactManifestError("validation_result_id is already linked to another artifact")
    conn.execute(
        """
        INSERT INTO artifact_validation_results (
          validation_result_id, schema_version, artifact_id, status,
          validator_version, validated_at, reason_codes, validation_messages,
          metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(validation_result_id) DO UPDATE SET
          status=excluded.status,
          validator_version=excluded.validator_version,
          validated_at=excluded.validated_at,
          reason_codes=excluded.reason_codes,
          validation_messages=excluded.validation_messages,
          metadata=excluded.metadata
        """,
        (
            result["validation_result_id"],
            result["schema_version"],
            result["artifact_id"],
            result["status"],
            result["validator_version"],
            result["validated_at"],
            canonical_json(result["reason_codes"]),
            canonical_json(result["validation_messages"]),
            canonical_json(result["metadata"]),
        ),
    )
    return result["validation_result_id"]
