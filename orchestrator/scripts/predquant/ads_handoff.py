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


def write_artifact_manifest(conn: sqlite3.Connection, manifest: dict[str, Any]) -> str:
    validate_artifact_manifest(manifest)
    conn.execute(
        """
        INSERT INTO case_artifact_manifest (
          artifact_id, schema_version, artifact_type, artifact_schema_version,
          case_id, case_key, dispatch_id, stage, stage_attempt_id, pipeline_run_id,
          producer, artifact_path, artifact_sha256, generated_at,
          forecast_timestamp, source_cutoff_timestamp, input_manifest_ids,
          validation_status, validation_result_refs, validator_version,
          temporal_isolation_status, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(artifact_id) DO UPDATE SET
          validation_status=excluded.validation_status,
          validation_result_refs=excluded.validation_result_refs,
          validator_version=excluded.validator_version,
          temporal_isolation_status=excluded.temporal_isolation_status,
          metadata=excluded.metadata,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            manifest["artifact_id"],
            manifest["schema_version"],
            manifest["artifact_type"],
            manifest["artifact_schema_version"],
            manifest["case_id"],
            manifest["case_key"],
            manifest["dispatch_id"],
            manifest["stage"],
            manifest.get("stage_attempt_id"),
            manifest.get("pipeline_run_id"),
            manifest["producer"],
            manifest["path"],
            manifest["sha256"],
            manifest["generated_at"],
            manifest["forecast_timestamp"],
            manifest["source_cutoff_timestamp"],
            canonical_json(manifest["input_manifest_ids"]),
            manifest["validation_status"],
            canonical_json(manifest["validation_result_refs"]),
            manifest.get("validator_version"),
            manifest["temporal_isolation_status"],
            canonical_json(manifest["metadata"]),
        ),
    )
    return manifest["artifact_id"]


def write_validation_result(conn: sqlite3.Connection, result: dict[str, Any]) -> str:
    validate_validation_result(result)
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
