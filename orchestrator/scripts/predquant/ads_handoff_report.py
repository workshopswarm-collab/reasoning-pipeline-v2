"""Operator report for ADS pipeline handoff chains."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from predquant.ads_handoff import ensure_artifact_manifest_schema
from predquant.ads_handoff_resolver import resolve_artifact_manifest
from predquant.ads_pipeline_runner import (
    ADS_PIPELINE_STAGE_ORDER,
    PIPELINE_LOOP_ITERATION_TABLE,
    PIPELINE_RUN_TABLE,
    ensure_pipeline_runner_schema,
)
from predquant.ads_stage_logging import STAGE_STATUS_TABLE, ensure_stage_logging_schema
from predquant.ads_stage_logging import STAGE_EXECUTION_EVENT_TABLE


ACCEPTED_VALIDATION_STATUSES = {"valid", "valid_with_warnings"}
LINEAGE_ONLY_STAGES = {"case_selection", "training_trace", "replay_record"}
INTELLIGENCE_HANDOFF_STAGES = frozenset(
    stage for stage in ADS_PIPELINE_STAGE_ORDER if stage not in LINEAGE_ONLY_STAGES
)


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
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
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
    return row["pipeline_run_id"] if row else None


def _run_row(conn: sqlite3.Connection, pipeline_run_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT * FROM {PIPELINE_RUN_TABLE} WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["metadata"] = _decode_json(result.get("metadata"), {})
    result["stage_order"] = _decode_json(result.get("stage_order"), list(ADS_PIPELINE_STAGE_ORDER))
    return result


def _loop_rows(conn: sqlite3.Connection, pipeline_run_id: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, PIPELINE_LOOP_ITERATION_TABLE):
        return []
    rows = conn.execute(
        f"""
        SELECT *
        FROM {PIPELINE_LOOP_ITERATION_TABLE}
        WHERE pipeline_run_id = ?
        ORDER BY iteration_number, rowid
        """,
        (pipeline_run_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for field in ("error_event_refs", "metadata", "retry_summary"):
            if field in item:
                item[field] = _decode_json(item[field], [] if field == "error_event_refs" else {})
        result.append(item)
    return result


def _manifest_summary(conn: sqlite3.Connection, artifact_id: str, *, stage: str | None = None) -> dict[str, Any]:
    if stage == "case_selection" and artifact_id.startswith("ads-case-lease:"):
        return {
            "artifact_id": artifact_id,
            "resolved": True,
            "non_manifest_ref": True,
            "ref_type": "case_lease_id",
        }
    try:
        manifest = resolve_artifact_manifest(conn, artifact_id)
        return {
            "artifact_id": manifest["artifact_id"],
            "artifact_type": manifest["artifact_type"],
            "artifact_schema_version": manifest["artifact_schema_version"],
            "stage": manifest["stage"],
            "validation_status": manifest["validation_status"],
            "temporal_isolation_status": manifest["temporal_isolation_status"],
            "sha256": manifest["sha256"],
            "path": manifest["path"],
            "input_manifest_ids": manifest["input_manifest_ids"],
            "resolved": True,
        }
    except Exception as exc:
        return {"artifact_id": artifact_id, "resolved": False, "error": str(exc)}


def _normalized_token(value: Any) -> str:
    return str(value or "").replace("-", "_")


def _is_valid_manifest(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("validation_status") or "") in ACCEPTED_VALIDATION_STATUSES


def _is_readiness_block_artifact(manifest: dict[str, Any]) -> bool:
    normalized_type = _normalized_token(manifest.get("artifact_type"))
    normalized_schema = _normalized_token(
        manifest.get("artifact_schema_version") or manifest.get("schema_version")
    )
    return normalized_type.endswith("_readiness_block") or normalized_schema.endswith("_readiness_block/v1")


def _downstream_consumers_by_input(stages: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    consumers: dict[str, list[dict[str, str]]] = {}
    for stage in stages:
        stage_name = str(stage.get("stage") or "")
        for manifest in stage.get("output_manifests", []):
            artifact_id = str(manifest.get("artifact_id") or "")
            for input_ref in manifest.get("input_manifest_ids") or []:
                consumers.setdefault(str(input_ref), []).append(
                    {
                        "stage": stage_name,
                        "artifact_id": artifact_id,
                    }
                )
    return consumers


def _annotate_manifest_handoff(
    manifest: dict[str, Any],
    *,
    consumers_by_input: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    if manifest.get("non_manifest_ref"):
        manifest["artifact_exists"] = False
        manifest["artifact_valid"] = False
        manifest["readiness_block"] = False
        manifest["accepted_for_downstream"] = False
        manifest["downstream_consumers"] = []
        manifest["handoff_status"] = "non_manifest_reference"
        return manifest

    artifact_id = str(manifest.get("artifact_id") or "")
    consumers = consumers_by_input.get(artifact_id, [])
    artifact_exists = bool(manifest.get("resolved"))
    artifact_valid = artifact_exists and _is_valid_manifest(manifest)
    readiness_block = artifact_exists and _is_readiness_block_artifact(manifest)
    accepted_for_downstream = bool(artifact_valid and consumers and not readiness_block)

    if not artifact_exists:
        handoff_status = "missing_or_unresolved"
    elif readiness_block:
        handoff_status = (
            "valid_readiness_block_not_downstream_accepted"
            if artifact_valid
            else "readiness_block_not_valid"
        )
    elif not artifact_valid:
        handoff_status = "artifact_exists_not_valid"
    elif accepted_for_downstream:
        handoff_status = "valid_and_accepted"
    else:
        handoff_status = "valid_not_accepted"

    manifest["artifact_exists"] = artifact_exists
    manifest["artifact_valid"] = artifact_valid
    manifest["readiness_block"] = readiness_block
    manifest["accepted_for_downstream"] = accepted_for_downstream
    manifest["downstream_consumers"] = consumers
    manifest["handoff_status"] = handoff_status
    return manifest


def _annotate_handoff_semantics(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    consumers_by_input = _downstream_consumers_by_input(stages)
    for stage in stages:
        stage["handoff_status_counts"] = {}
        for manifest in stage.get("output_manifests", []):
            _annotate_manifest_handoff(manifest, consumers_by_input=consumers_by_input)
            status = str(manifest.get("handoff_status") or "unknown")
            stage["handoff_status_counts"][status] = stage["handoff_status_counts"].get(status, 0) + 1
    return stages


def _stage_rows(conn: sqlite3.Connection, pipeline_run_id: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, STAGE_STATUS_TABLE):
        return []
    rows = conn.execute(
        f"""
        SELECT s.*
        FROM {STAGE_STATUS_TABLE} s
        WHERE s.stage_attempt_id IN (
          SELECT DISTINCT stage_attempt_id
          FROM {STAGE_EXECUTION_EVENT_TABLE}
          WHERE pipeline_run_id = ?
        )
        ORDER BY s.id
        """,
        (pipeline_run_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        output_refs = _decode_json(item.get("output_artifact_refs") or item.get("output_artifacts"), [])
        validation_refs = _decode_json(item.get("validation_result_refs"), [])
        item["output_artifact_refs"] = output_refs
        item["validation_result_refs"] = validation_refs
        item["metadata"] = _decode_json(item.get("metadata"), {})
        item["output_manifests"] = [_manifest_summary(conn, ref, stage=item.get("stage")) for ref in output_refs]
        result.append(item)
    return result


def _stage_completion_count(stages: list[dict[str, Any]]) -> int:
    return sum(1 for stage in stages if str(stage.get("status") or "") == "complete")


def _manifest_counts_for_stages(stages: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stage in stages:
        for manifest in stage["output_manifests"]:
            if manifest.get("non_manifest_ref"):
                continue
            status = manifest.get("validation_status") if manifest.get("resolved") else "unresolved"
            status = status or "unknown"
            counts[status] = counts.get(status, 0) + 1
    return counts


def _handoff_status_counts_for_stages(stages: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stage in stages:
        for manifest in stage["output_manifests"]:
            status = str(manifest.get("handoff_status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
    return counts


def _accepted_intelligence_stage_count(stages: list[dict[str, Any]]) -> int:
    count = 0
    for stage in stages:
        if stage.get("stage") not in INTELLIGENCE_HANDOFF_STAGES:
            continue
        if any(
            manifest.get("accepted_for_downstream") and not manifest.get("readiness_block")
            for manifest in stage.get("output_manifests", [])
        ):
            count += 1
    return count


def _handoff_health_summary(
    *,
    stages: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
    readiness_block_count = sum(
        1
        for stage in stages
        for manifest in stage.get("output_manifests", [])
        if manifest.get("readiness_block")
    )
    accepted_manifest_count = sum(
        1
        for stage in stages
        for manifest in stage.get("output_manifests", [])
        if manifest.get("accepted_for_downstream")
    )
    return {
        "schema_version": "ads-handoff-health/v1",
        "stage_completion_count": _stage_completion_count(stages),
        "readiness_block_count": readiness_block_count,
        "accepted_intelligence_stage_count": _accepted_intelligence_stage_count(stages),
        "accepted_manifest_count": accepted_manifest_count,
        "unresolved_output_manifest_ref_count": len(unresolved),
        "handoff_counts_by_status": _handoff_status_counts_for_stages(stages),
        "manifest_counts_by_validation_status": _manifest_counts_for_stages(stages),
    }


def build_handoff_report(
    db_path: Path | str,
    *,
    pipeline_run_id: str | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_pipeline_runner_schema(conn)
        ensure_stage_logging_schema(conn)
        ensure_artifact_manifest_schema(conn)
        selected_run_id = pipeline_run_id or _latest_run_id(conn)
        if selected_run_id is None:
            return {
                "schema_version": "ads-handoff-operator-report/v1",
                "ok": False,
                "error": "no ADS pipeline runs found",
            }
        run = _run_row(conn, selected_run_id)
        if run is None:
            return {
                "schema_version": "ads-handoff-operator-report/v1",
                "ok": False,
                "error": f"pipeline run not found: {selected_run_id}",
            }
        stages = _annotate_handoff_semantics(_stage_rows(conn, selected_run_id))
        unresolved = [
            manifest
            for stage in stages
            for manifest in stage["output_manifests"]
            if not manifest.get("resolved")
        ]
        handoff_health = _handoff_health_summary(stages=stages, unresolved=unresolved)
        return {
            "schema_version": "ads-handoff-operator-report/v1",
            "ok": not unresolved,
            "pipeline_run": run,
            "loop_iterations": _loop_rows(conn, selected_run_id),
            "stages": stages,
            "unresolved_output_manifest_refs": unresolved,
            "stage_completion_count": handoff_health["stage_completion_count"],
            "readiness_block_count": handoff_health["readiness_block_count"],
            "accepted_intelligence_stage_count": handoff_health["accepted_intelligence_stage_count"],
            "handoff_counts_by_status": handoff_health["handoff_counts_by_status"],
            "manifest_counts_by_validation_status": handoff_health["manifest_counts_by_validation_status"],
            "handoff_health": handoff_health,
        }
    finally:
        conn.close()


__all__ = ["build_handoff_report"]
