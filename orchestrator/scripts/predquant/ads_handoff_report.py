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
        stages = _stage_rows(conn, selected_run_id)
        unresolved = [
            manifest
            for stage in stages
            for manifest in stage["output_manifests"]
            if not manifest.get("resolved")
        ]
        return {
            "schema_version": "ads-handoff-operator-report/v1",
            "ok": not unresolved,
            "pipeline_run": run,
            "loop_iterations": _loop_rows(conn, selected_run_id),
            "stages": stages,
            "unresolved_output_manifest_refs": unresolved,
            "manifest_counts_by_validation_status": _manifest_counts_for_stages(stages),
        }
    finally:
        conn.close()


__all__ = ["build_handoff_report"]
