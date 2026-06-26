"""Strict ADS artifact-manifest resolution for runtime handoffs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from predquant.ads_handoff import (
    ARTIFACT_MANIFEST_TABLE,
    ArtifactManifestError,
    ensure_artifact_manifest_schema,
    validate_artifact_manifest,
)


@dataclass(frozen=True)
class ManifestRequirement:
    role: str
    artifact_type: str | None = None
    artifact_schema_version: str | None = None
    stage: str | None = None
    accepted_validation_statuses: tuple[str, ...] = ("valid", "valid_with_warnings")
    accepted_temporal_statuses: tuple[str, ...] = ("pass", "not_applicable")


def _json_array(value: Any, field: str) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ArtifactManifestError(f"{field} is not valid JSON") from exc
    else:
        parsed = value
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item for item in parsed):
        raise ArtifactManifestError(f"{field} must decode to a list of strings")
    return parsed


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ArtifactManifestError(f"{field} is not valid JSON") from exc
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ArtifactManifestError(f"{field} must decode to an object")
    return parsed


def manifest_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Normalize a persisted manifest row into the in-memory manifest shape."""

    keys = set(row.keys()) if isinstance(row, sqlite3.Row) else set(row)

    def get(*names: str) -> Any:
        for name in names:
            if name in keys:
                return row[name]
        return None

    manifest = {
        "schema_version": get("schema_version"),
        "artifact_id": get("artifact_id"),
        "artifact_type": get("artifact_type"),
        "artifact_schema_version": get("artifact_schema_version", "schema_id"),
        "case_id": get("case_id"),
        "case_key": get("case_key"),
        "dispatch_id": get("dispatch_id"),
        "stage": get("stage", "producer_stage"),
        "stage_attempt_id": get("stage_attempt_id"),
        "pipeline_run_id": get("pipeline_run_id"),
        "producer": get("producer"),
        "path": get("path", "artifact_path"),
        "sha256": get("sha256", "artifact_sha256"),
        "generated_at": get("generated_at"),
        "forecast_timestamp": get("forecast_timestamp"),
        "source_cutoff_timestamp": get("source_cutoff_timestamp"),
        "input_manifest_ids": _json_array(get("input_manifest_ids"), "input_manifest_ids"),
        "validation_status": get("validation_status"),
        "validation_result_refs": _json_array(get("validation_result_refs"), "validation_result_refs"),
        "validator_version": get("validator_version"),
        "temporal_isolation_status": get("temporal_isolation_status"),
        "metadata": _json_object(get("metadata"), "metadata"),
    }
    return {key: value for key, value in manifest.items() if value is not None}


def fetch_artifact_manifest(conn: sqlite3.Connection, artifact_id: str) -> dict[str, Any]:
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ArtifactManifestError("artifact_id is required")
    ensure_artifact_manifest_schema(conn)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        f"SELECT * FROM {ARTIFACT_MANIFEST_TABLE} WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ArtifactManifestError(f"artifact manifest not found: {artifact_id}")
    return manifest_from_row(row)


def resolve_artifact_manifest(
    conn: sqlite3.Connection,
    artifact_id: str,
    requirement: ManifestRequirement | None = None,
) -> dict[str, Any]:
    manifest = fetch_artifact_manifest(conn, artifact_id)
    expected_schema = requirement.artifact_schema_version if requirement else None
    validate_artifact_manifest(
        manifest,
        expected_artifact_schema_version=expected_schema,
        check_digest=True,
    )
    if requirement:
        if requirement.artifact_type and manifest["artifact_type"] != requirement.artifact_type:
            raise ArtifactManifestError(
                f"{requirement.role} artifact_type must be {requirement.artifact_type}"
            )
        if requirement.stage and manifest["stage"] != requirement.stage:
            raise ArtifactManifestError(f"{requirement.role} stage must be {requirement.stage}")
        if manifest["validation_status"] not in requirement.accepted_validation_statuses:
            raise ArtifactManifestError(
                f"{requirement.role} validation_status {manifest['validation_status']} is not accepted"
            )
        if manifest["temporal_isolation_status"] not in requirement.accepted_temporal_statuses:
            raise ArtifactManifestError(
                f"{requirement.role} temporal_isolation_status "
                f"{manifest['temporal_isolation_status']} is not accepted"
            )
    return manifest


def load_manifest_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    path = Path(manifest.get("path") or "")
    if not path.is_absolute():
        raise ArtifactManifestError("artifact manifest path must be absolute")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactManifestError(f"artifact payload is not valid JSON: {manifest['artifact_id']}") from exc
    if not isinstance(payload, dict):
        raise ArtifactManifestError("artifact payload must be a JSON object")
    return payload


def resolve_stage_output_manifest(
    conn: sqlite3.Connection,
    stage_outputs: dict[str, dict[str, Any]],
    stage: str,
    requirement: ManifestRequirement | None = None,
    *,
    output_index: int = 0,
) -> dict[str, Any]:
    result = stage_outputs.get(stage)
    if not isinstance(result, dict):
        raise ArtifactManifestError(f"stage output is missing: {stage}")
    refs = result.get("output_artifact_refs") or []
    if not isinstance(refs, (list, tuple)) or output_index >= len(refs):
        raise ArtifactManifestError(f"stage output has no artifact ref at index {output_index}: {stage}")
    return resolve_artifact_manifest(conn, refs[output_index], requirement)


def require_stage_output_manifests(
    conn: sqlite3.Connection,
    *,
    stage_outputs: dict[str, dict[str, Any]],
    required: dict[str, ManifestRequirement],
) -> dict[str, dict[str, Any]]:
    return {
        stage: resolve_stage_output_manifest(conn, stage_outputs, stage, requirement)
        for stage, requirement in required.items()
    }


__all__ = [
    "ManifestRequirement",
    "fetch_artifact_manifest",
    "load_manifest_payload",
    "manifest_from_row",
    "require_stage_output_manifests",
    "resolve_artifact_manifest",
    "resolve_stage_output_manifest",
]
