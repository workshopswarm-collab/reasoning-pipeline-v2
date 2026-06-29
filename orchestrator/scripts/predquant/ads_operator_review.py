"""ADS operator review report with alert severities and trace refs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predquant.ads_handoff import ensure_artifact_manifest_schema
from predquant.ads_handoff_report import build_handoff_report
from predquant.ads_pipeline_runner import (
    PIPELINE_RUN_TABLE,
    ensure_pipeline_runner_schema,
    read_pipeline_control_state,
)
from predquant.ads_stage_logging import ensure_stage_logging_schema
from predquant.ads_storage_maintenance import build_storage_maintenance_plan
from predquant.amrg import build_amrg_operator_report
from predquant.sqlite_store import brier_score_report, ensure_schema, parse_market_time


ADS_OPERATOR_REVIEW_SCHEMA_VERSION = "ads-operator-review-report/v1"
SCAE_PROBABILITY_SOURCE = "SCAE-012.production_forecast_prob"
SCAE_MARKET_PREDICTION_SOURCE = "scae.production_forecast_prob"
DEFAULT_ACTIVE_LEASE_BLOCK_SECONDS = 60 * 60
DEFAULT_ACTIVE_RUN_BLOCK_SECONDS = 90 * 60
DEFAULT_WAL_WARNING_BYTES = 512 * 1024 * 1024
DEFAULT_WAL_BLOCK_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_SOURCE_FRESHNESS_WARNING_FRACTION = 0.8
TRUE_PRODUCTION_HANDLER = "predquant.ads_production_handlers"
PRODUCTION_PILOT_HANDLER = "predquant.ads_production_pilot_handlers"
PRODUCTION_READINESS_HANDLER = "predquant.ads_production_readiness_handlers"
PILOT_QDT_ADAPTER_MODES = {
    "deterministic_decomposer_contract_adapter",
    "pilot_fixture_decomposer_contract_adapter",
}
WEAK_AMRG_STATUSES = {
    "weak_context_only",
    "timing_mismatch_weak_context_only",
    "model_assisted_weak_context_only",
}
RESEARCH_SUFFICIENCY_BLOCKED_CODES = {
    "research_sufficiency_not_certified",
    "retrieval_sufficiency_not_certified",
    "blocked_insufficient_research",
    "blocked_until_certified_retrieval",
}
TRUE_RUNTIME_CUTOVER_STATUSES = {
    "ready",
    "blocked_stage_failure",
    "blocked_missing_retrieval_cert",
    "blocked_missing_researcher_model_execution",
    "blocked_missing_scae_ledger",
    "blocked_missing_strict_canary",
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _age_seconds(timestamp: str | None) -> float | None:
    parsed = parse_market_time(timestamp)
    if parsed is None:
        return None
    return (_utcnow() - parsed).total_seconds()


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
    return str(row["pipeline_run_id"]) if row else None


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for field, fallback in (
        ("metadata", {}),
        ("stage_order", []),
        ("idle_policy", {}),
        ("safe_metadata", {}),
        ("input_manifest_ids", []),
        ("validation_result_refs", []),
        ("trace_artifact_manifest_ids", []),
        ("trace_artifact_hashes", {}),
        ("replay_manifest_refs", []),
        ("allowed_uses", []),
        ("forbidden_uses", []),
    ):
        if field in result:
            result[field] = _decode_json(result[field], fallback)
    return result


def _run_row(conn: sqlite3.Connection, pipeline_run_id: str | None) -> dict[str, Any] | None:
    if not pipeline_run_id or not _table_exists(conn, PIPELINE_RUN_TABLE):
        return None
    row = conn.execute(
        f"SELECT * FROM {PIPELINE_RUN_TABLE} WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    ).fetchone()
    return _row_dict(row)


def _run_age_seconds(run: dict[str, Any]) -> float | None:
    if run.get("status") not in {"starting", "running", "draining"}:
        return None
    return _age_seconds(str(run.get("started_at") or ""))


def _lease_rows(conn: sqlite3.Connection, pipeline_run_id: str | None) -> list[dict[str, Any]]:
    if not pipeline_run_id or not _table_exists(conn, "ads_case_leases"):
        return []
    rows = conn.execute(
        """
        SELECT *
        FROM ads_case_leases
        WHERE pipeline_run_id = ?
        ORDER BY lease_acquired_at, rowid
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [_row_dict(row) or {} for row in rows]


def _active_lease_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "ads_case_leases"):
        return []
    rows = conn.execute(
        """
        SELECT *
        FROM ads_case_leases
        WHERE lease_status = 'leased'
        ORDER BY lease_acquired_at, rowid
        """
    ).fetchall()
    result = []
    for row in rows:
        item = _row_dict(row) or {}
        item["lease_age_seconds"] = _age_seconds(item.get("lease_acquired_at"))
        result.append(item)
    return result


def _active_run_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, PIPELINE_RUN_TABLE):
        return []
    rows = conn.execute(
        f"""
        SELECT *
        FROM {PIPELINE_RUN_TABLE}
        WHERE status IN ('starting', 'running', 'draining')
        ORDER BY started_at, rowid
        """
    ).fetchall()
    result = []
    for row in rows:
        item = _row_dict(row) or {}
        item["run_age_seconds"] = _run_age_seconds(item)
        result.append(item)
    return result


def _manifest_rows(conn: sqlite3.Connection, pipeline_run_id: str | None) -> list[dict[str, Any]]:
    if not pipeline_run_id or not _table_exists(conn, "case_artifact_manifest"):
        return []
    rows = conn.execute(
        """
        SELECT *
        FROM case_artifact_manifest
        WHERE pipeline_run_id = ?
        ORDER BY created_at, id
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [_row_dict(row) or {} for row in rows]


def _load_manifest_payload(manifest: dict[str, Any]) -> dict[str, Any] | None:
    path = manifest.get("artifact_path") or manifest.get("path")
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _latest_row_by_stage(manifests: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
    rows = [manifest for manifest in manifests if manifest.get("stage") == stage]
    return rows[-1] if rows else None


def _latest_payload_by_stage(manifests: list[dict[str, Any]], stage: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    manifest = _latest_row_by_stage(manifests, stage)
    return manifest, _load_manifest_payload(manifest) if manifest else None


def _forecast_decision_rows(conn: sqlite3.Connection, pipeline_run_id: str | None) -> list[dict[str, Any]]:
    if not pipeline_run_id or not _table_exists(conn, "forecast_decision_records"):
        return []
    rows = conn.execute(
        """
        SELECT *
        FROM forecast_decision_records
        WHERE run_id = ?
        ORDER BY id
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [_row_dict(row) or {} for row in rows]


def _market_prediction_rows(conn: sqlite3.Connection, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decision_ids = {
        str(row.get("forecast_decision_id"))
        for row in decisions
        if row.get("forecast_decision_id")
    }
    if not decision_ids or not _table_exists(conn, "market_predictions"):
        return []
    rows = conn.execute("SELECT * FROM market_predictions ORDER BY id").fetchall()
    result = []
    for row in rows:
        item = _row_dict(row) or {}
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if metadata.get("forecast_decision_id") in decision_ids:
            result.append(item)
    return result


def _trace_rows(conn: sqlite3.Connection, pipeline_run_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not pipeline_run_id:
        return [], [], []
    minimal = []
    full = []
    replay = []
    if _table_exists(conn, "training_trace_minimal_pointers"):
        minimal = [
            _row_dict(row) or {}
            for row in conn.execute(
                """
                SELECT *
                FROM training_trace_minimal_pointers
                WHERE run_id = ?
                ORDER BY created_at, rowid
                """,
                (pipeline_run_id,),
            ).fetchall()
        ]
    if _table_exists(conn, "training_trace_full_materializations"):
        full = [
            _row_dict(row) or {}
            for row in conn.execute(
                """
                SELECT *
                FROM training_trace_full_materializations
                WHERE run_id = ?
                ORDER BY created_at, rowid
                """,
                (pipeline_run_id,),
            ).fetchall()
        ]
    if _table_exists(conn, "v2_replay_manifests"):
        replay = [
            _row_dict(row) or {}
            for row in conn.execute(
                """
                SELECT *
                FROM v2_replay_manifests
                WHERE run_id = ?
                ORDER BY created_at, rowid
                """,
                (pipeline_run_id,),
            ).fetchall()
        ]
    return minimal, full, replay


def _latest_snapshot_status(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "market_snapshots"):
        return {"latest_snapshot_at": None, "age_seconds": None}
    latest = conn.execute("SELECT MAX(observed_at) FROM market_snapshots").fetchone()[0]
    return {"latest_snapshot_at": latest, "age_seconds": _age_seconds(latest)}


def _latest_resolution_status(conn: sqlite3.Connection) -> dict[str, Any]:
    latest_market = None
    latest_heartbeat = None
    if _table_exists(conn, "markets") and "resolution_checked_at" in _columns(conn, "markets"):
        latest_market = conn.execute(
            "SELECT MAX(resolution_checked_at) FROM markets WHERE resolution_checked_at IS NOT NULL"
        ).fetchone()[0]
    if _table_exists(conn, "polymarket_resolution_sync_heartbeats"):
        latest_heartbeat = conn.execute(
            "SELECT MAX(checked_at) FROM polymarket_resolution_sync_heartbeats WHERE dry_run = 0"
        ).fetchone()[0]
    latest = max([item for item in (latest_market, latest_heartbeat) if item], default=None)
    return {
        "latest_resolution_checked_at": latest,
        "latest_resolution_sync_heartbeat_at": latest_heartbeat,
        "age_seconds": _age_seconds(latest),
    }


def _case_key(case_id: str | None, dispatch_id: str | None) -> str:
    return f"{case_id or 'unknown'}|{dispatch_id or 'unknown'}"


def _infer_run_kind(run: dict[str, Any] | None, manifests: list[dict[str, Any]]) -> str:
    metadata_refs = []
    if run and isinstance(run.get("metadata"), dict):
        metadata_refs.extend(str(value) for value in run["metadata"].values())
    for manifest in manifests:
        metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
        metadata_refs.extend(str(value) for value in metadata.values())
    joined = " ".join(metadata_refs)
    if TRUE_PRODUCTION_HANDLER in joined or "true_production_specialist_runtime" in joined:
        return "true_production"
    if PRODUCTION_PILOT_HANDLER in joined or "production_pilot" in joined:
        return "pilot"
    if PRODUCTION_READINESS_HANDLER in joined or "production_readiness" in joined:
        return "readiness"
    if run and str(run.get("runner_mode") or "").endswith("canary"):
        return "pilot"
    return "unknown"


def _qdt_summary(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    qdt_manifest = next((m for m in manifests if m.get("artifact_type") == "question-decomposition"), None)
    qdt = _load_manifest_payload(qdt_manifest) if qdt_manifest else None
    runtime_manifests = [m for m in manifests if m.get("artifact_type") == "model-runtime-call"]
    runtime_payloads = {
        str((_load_manifest_payload(m) or {}).get("runtime_call_id")): (_load_manifest_payload(m) or {})
        for m in runtime_manifests
    }
    leaf_ids = []
    if isinstance(qdt, dict):
        leaf_ids = [
            str(leaf.get("leaf_id"))
            for leaf in qdt.get("required_leaf_questions", [])
            if isinstance(leaf, dict) and leaf.get("leaf_id")
        ]
    generic_leaf_ids = sorted(
        set(leaf_ids) & {"leaf-source-of-truth", "leaf-direct-evidence", "leaf-resolution-mechanics"}
    )
    runtime = runtime_payloads.get(str((qdt or {}).get("runtime_call_ref")))
    if runtime is None and runtime_payloads:
        runtime = next(iter(runtime_payloads.values()))
    model_executed = bool(
        runtime
        and runtime.get("resolved_model_id") == "gpt-5.5-high"
        and runtime.get("mode") == "live"
        and runtime.get("fixture_mode") is False
        and runtime.get("execution_status") in {"succeeded", "accepted"}
    )
    return {
        "artifact_id": qdt_manifest.get("artifact_id") if qdt_manifest else None,
        "adapter_mode": qdt.get("adapter_mode") if isinstance(qdt, dict) else None,
        "runtime_call_ref": qdt.get("runtime_call_ref") if isinstance(qdt, dict) else None,
        "resolved_model_id": runtime.get("resolved_model_id") if isinstance(runtime, dict) else None,
        "runtime_mode": runtime.get("mode") if isinstance(runtime, dict) else None,
        "fixture_mode": runtime.get("fixture_mode") if isinstance(runtime, dict) else None,
        "execution_status": runtime.get("execution_status") if isinstance(runtime, dict) else None,
        "leaf_count": len(leaf_ids),
        "generic_leaf_ids_present": generic_leaf_ids,
        "question_specific": bool(leaf_ids) and not generic_leaf_ids,
        "model_executed": model_executed,
    }


def _amrg_summaries(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qdt_manifest = next((m for m in manifests if m.get("artifact_type") == "question-decomposition"), None)
    qdt = _load_manifest_payload(qdt_manifest) if qdt_manifest else None
    summaries = []
    for manifest in manifests:
        if manifest.get("artifact_type") not in {"related-live-market-context", "no-related-context-waiver"}:
            continue
        payload = _load_manifest_payload(manifest)
        if not isinstance(payload, dict):
            summaries.append({"artifact_id": manifest.get("artifact_id"), "ok": False, "error": "payload_unreadable"})
            continue
        report = build_amrg_operator_report(payload, question_decomposition=qdt if isinstance(qdt, dict) else None)
        relationship_status_counts = {
            str(key or "missing"): value
            for key, value in (report.get("relationship_status_counts") or {}).items()
        }
        refresh_status_counts = {
            str(key or "missing"): value
            for key, value in (report.get("refresh_status_counts") or {}).items()
        }
        missing_refresh = []
        for edge in payload.get("relationship_edges", []):
            if not isinstance(edge, dict):
                continue
            lifecycle = edge.get("refresh_lifecycle_state") if isinstance(edge.get("refresh_lifecycle_state"), dict) else {}
            if edge.get("relationship_status") not in WEAK_AMRG_STATUSES and not lifecycle.get("refresh_status"):
                missing_refresh.append(edge.get("relationship_id") or edge.get("edge_id") or "unknown_edge")
        consumed = [
            hint for hint in report.get("hint_consumption", [])
            if isinstance(hint, dict) and hint.get("decomposer_consumed")
        ]
        summaries.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "candidate_set_id": report.get("candidate_set_id"),
                "artifact_type": report.get("artifact_type"),
                "vector_status": report.get("vector_status"),
                "candidate_count": report.get("candidate_count"),
                "consumed_hint_count": len(consumed),
                "relationship_status_counts": relationship_status_counts,
                "refresh_status_counts": refresh_status_counts,
                "missing_refresh_status_refs": missing_refresh,
                "hint_consumption": report.get("hint_consumption", []),
            }
        )
    return summaries


def _retrieval_summary(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    manifest, payload = _latest_payload_by_stage(manifests, "retrieval")
    payload = payload if isinstance(payload, dict) else {}
    summary = payload.get("research_sufficiency_summary")
    summary = summary if isinstance(summary, dict) else {}
    native = _as_list(payload.get("native_research_transport_diagnostics"))
    browser = _as_list(payload.get("browser_retrieval_attempts"))
    dockets = _as_list(payload.get("leaf_evidence_dockets"))
    admitted = sum(
        len(_as_list(docket.get("admitted_evidence_refs")))
        for docket in dockets
        if isinstance(docket, dict)
    )
    return {
        "artifact_id": manifest.get("artifact_id") if manifest else None,
        "adapter_mode": payload.get("adapter_mode"),
        "classification_dispatch_status": summary.get("classification_dispatch_status"),
        "all_required_leaves_certified": bool(summary.get("all_required_leaves_certified")),
        "leaf_certificate_refs": _as_list(summary.get("leaf_certificate_refs")),
        "native_research_transport_diagnostics": native,
        "browser_retrieval_attempt_count": len(browser),
        "leaf_evidence_docket_count": len(dockets),
        "admitted_evidence_ref_count": admitted,
    }


def _researcher_summary(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    sidecars = []
    bundles = []
    classifications = []
    for manifest in manifests:
        payload = _load_manifest_payload(manifest)
        artifact_type = str(manifest.get("artifact_type") or "")
        if not isinstance(payload, dict):
            continue
        if artifact_type in {"researcher-sidecar", "researcher_sidecar"} or payload.get("artifact_type") == "researcher_sidecar":
            context = payload.get("model_execution_context") if isinstance(payload.get("model_execution_context"), dict) else {}
            runtime = context.get("runtime") if isinstance(context.get("runtime"), dict) else {}
            sidecars.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "resolved_model_id": context.get("resolved_model_id"),
                    "model_executed": runtime.get("model_executed"),
                    "execution_status": runtime.get("execution_status"),
                }
            )
        elif artifact_type in {"researcher-swarm-runtime-bundle", "researcher_swarm_runtime_bundle"}:
            bundles.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "leaf_runtime_status": payload.get("leaf_runtime_status", []),
                }
            )
        elif artifact_type in {
            "leaf-research-barrier",
            "researcher-classification-readiness-block",
            "researcher-classification-production-pilot",
        }:
            classifications.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "artifact_type": artifact_type,
                    "classification_status": payload.get("classification_status"),
                    "classification_dispatch_status": payload.get("classification_dispatch_status"),
                    "reason_codes": list(payload.get("reason_codes") or []),
                    "researcher_probability_authority": payload.get("researcher_probability_authority"),
                }
            )
    bundle_model_executed = sum(
        1
        for bundle in bundles
        for row in bundle.get("leaf_runtime_status", [])
        if isinstance(row, dict)
        and row.get("model_executed") is True
        and row.get("resolved_model_id") == "gpt-5.5-high"
    )
    sidecar_model_executed = sum(
        1
        for sidecar in sidecars
        if sidecar.get("model_executed") is True
        and sidecar.get("resolved_model_id") == "gpt-5.5-high"
    )
    model_executed_count = sidecar_model_executed + bundle_model_executed
    metadata_only = bool(classifications) and model_executed_count == 0 and any(
        item.get("classification_status") == "structured_market_metadata_certified"
        or item.get("artifact_type") == "researcher-classification-production-pilot"
        for item in classifications
    )
    blocked = bool(classifications) and all(
        item.get("classification_status") in {
            "blocked_until_certified_retrieval",
            "blocked_leaf_research_barrier",
        }
        for item in classifications
    )
    return {
        "model_executed_count": model_executed_count,
        "metadata_only": metadata_only,
        "blocked_non_scoreable": blocked,
        "sidecars": sidecars,
        "runtime_bundles": bundles,
        "classification_artifacts": classifications,
    }


def _verification_summary(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    manifest, payload = _latest_payload_by_stage(manifests, "classification_verification")
    rows = payload.get("research_sufficiency_reconciliation_slices") if isinstance(payload, dict) else []
    rows = _as_list(rows)
    return {
        "artifact_id": manifest.get("artifact_id") if manifest else None,
        "verification_status": payload.get("verification_status") if isinstance(payload, dict) else None,
        "reason_codes": list(payload.get("reason_codes") or []) if isinstance(payload, dict) else [],
        "reconciliation_slice_count": len(rows),
        "reconciliation_statuses": [
            str(row.get("research_sufficiency_reconciliation_status"))
            for row in rows
            if isinstance(row, dict) and row.get("research_sufficiency_reconciliation_status")
        ],
    }


def _scae_summary(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    manifest, payload = _latest_payload_by_stage(manifests, "scae")
    payload = payload if isinstance(payload, dict) else {}
    evidence_refs = []
    for field in (
        "scae_evidence_delta_candidate_slice_refs",
        "scae_evidence_delta_classification_slice_refs",
        "scae_evidence_delta_direction_verification_slice_refs",
        "scae_evidence_delta_quality_verification_slice_refs",
    ):
        evidence_refs.extend(str(ref) for ref in _as_list(payload.get(field)) if ref)
    interval = (
        payload.get("probability_interval")
        or payload.get("confidence_interval")
        or payload.get("interval")
    )
    return {
        "artifact_id": manifest.get("artifact_id") if manifest else None,
        "forecast_validity_status": payload.get("forecast_validity_status"),
        "execution_authority_status": payload.get("execution_authority_status"),
        "final_probability_fields_status": payload.get("final_probability_fields_status"),
        "production_forecast_prob": payload.get("production_forecast_prob"),
        "canonical_probability": payload.get("canonical_probability"),
        "probability_interval": interval,
        "scoreable_forecast_output": bool(payload.get("scoreable_forecast_output")),
        "evidence_delta_ref_count": len(evidence_refs),
        "evidence_delta_refs": sorted(set(evidence_refs)),
        "reason_codes": _as_list(payload.get("reason_codes")),
        "research_sufficiency_context": (
            payload.get("research_sufficiency_context")
            if isinstance(payload.get("research_sufficiency_context"), dict)
            else {}
        ),
        "candidate_bundle_digest": payload.get("scae_evidence_delta_candidate_bundle_digest"),
        "netting_bundle_digest": payload.get("scae_leaf_cluster_netting_bundle_digest"),
    }


def _decision_summary(
    manifests: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    manifest, payload = _latest_payload_by_stage(manifests, "decision")
    decision_ids = {
        str(decision.get("forecast_decision_id"))
        for decision in decisions
        if decision.get("forecast_decision_id")
    }
    matched_predictions = []
    for prediction in predictions:
        metadata = prediction.get("metadata") if isinstance(prediction.get("metadata"), dict) else {}
        if metadata.get("forecast_decision_id") in decision_ids:
            matched_predictions.append(prediction)
    return {
        "artifact_id": manifest.get("artifact_id") if manifest else None,
        "decision_gate_id": payload.get("decision_gate_id") if isinstance(payload, dict) else None,
        "forecast_validity_status": payload.get("forecast_validity_status") if isinstance(payload, dict) else None,
        "execution_authority_status": payload.get("execution_authority_status") if isinstance(payload, dict) else None,
        "actionability_status": payload.get("actionability_status") if isinstance(payload, dict) else None,
        "writes_market_prediction": bool(payload.get("writes_market_prediction")) if isinstance(payload, dict) else False,
        "scoreable_forecast_output": bool(payload.get("scoreable_forecast_output")) if isinstance(payload, dict) else False,
        "forecast_decision_records": decisions,
        "market_predictions": matched_predictions,
    }


def _trace_summary(
    case_id: str | None,
    dispatch_id: str | None,
    traces: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
    manifests: list[dict[str, Any]],
) -> dict[str, Any]:
    minimal, full, replay = traces
    def matches(row: dict[str, Any]) -> bool:
        return row.get("case_id") == case_id and row.get("dispatch_id") == dispatch_id

    return {
        "trace_artifact_refs": [
            manifest.get("artifact_id")
            for manifest in manifests
            if manifest.get("stage") == "training_trace"
        ],
        "replay_artifact_refs": [
            manifest.get("artifact_id")
            for manifest in manifests
            if manifest.get("stage") == "replay_record"
        ],
        "minimal_trace_refs": [
            row.get("trace_id") or row.get("trace_pointer_id")
            for row in minimal
            if matches(row)
        ],
        "full_trace_refs": [
            row.get("trace_materialization_id") or row.get("trace_id")
            for row in full
            if matches(row)
        ],
        "replay_manifest_refs": [
            row.get("replay_manifest_id")
            for row in replay
            if matches(row)
        ],
    }


def _case_reports(
    leases: list[dict[str, Any]],
    manifests: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    traces: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    keys: dict[str, dict[str, Any]] = {}
    for lease in leases:
        keys[_case_key(lease.get("case_id"), lease.get("dispatch_id"))] = {
            "case_id": lease.get("case_id"),
            "case_key": lease.get("case_key"),
            "dispatch_id": lease.get("dispatch_id"),
            "market_id": lease.get("market_id"),
            "case_lease_id": lease.get("case_lease_id"),
            "selected_snapshot_id": lease.get("selected_snapshot_id"),
            "selected_snapshot_observed_at": lease.get("selected_snapshot_observed_at"),
        }
    for manifest in manifests:
        keys.setdefault(
            _case_key(manifest.get("case_id"), manifest.get("dispatch_id")),
            {
                "case_id": manifest.get("case_id"),
                "case_key": manifest.get("case_key"),
                "dispatch_id": manifest.get("dispatch_id"),
                "market_id": None,
                "case_lease_id": None,
                "selected_snapshot_id": None,
                "selected_snapshot_observed_at": None,
            },
        )
    reports = []
    for key, refs in sorted(keys.items()):
        case_id = refs.get("case_id")
        dispatch_id = refs.get("dispatch_id")
        case_manifests = [
            manifest
            for manifest in manifests
            if _case_key(manifest.get("case_id"), manifest.get("dispatch_id")) == key
        ]
        case_decisions = [
            decision
            for decision in decisions
            if _case_key(decision.get("case_id"), decision.get("dispatch_id")) == key
        ]
        reports.append(
            {
                **refs,
                "artifact_refs_by_stage": {
                    stage: [
                        manifest.get("artifact_id")
                        for manifest in case_manifests
                        if manifest.get("stage") == stage
                    ]
                    for stage in sorted({str(manifest.get("stage")) for manifest in case_manifests})
                },
                "qdt_model_provenance": _qdt_summary(case_manifests),
                "amrg_consumed_hints": _amrg_summaries(case_manifests),
                "retrieval_sufficiency": _retrieval_summary(case_manifests),
                "researcher_model_provenance": _researcher_summary(case_manifests),
                "verification_readiness": _verification_summary(case_manifests),
                "scae_readiness": _scae_summary(case_manifests),
                "decision_and_prediction": _decision_summary(case_manifests, case_decisions, predictions),
                "trace_replay_refs": _trace_summary(case_id, dispatch_id, traces, case_manifests),
            }
        )
    return reports


def _alert(
    severity: str,
    code: str,
    message: str,
    *,
    pipeline_run_id: str | None = None,
    case_id: str | None = None,
    case_key: str | None = None,
    dispatch_id: str | None = None,
    refs: list[str] | None = None,
    value: Any = None,
    threshold: Any = None,
    remediation: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "pipeline_run_id": pipeline_run_id,
        "case_id": case_id,
        "case_key": case_key,
        "dispatch_id": dispatch_id,
        "refs": refs or [],
        "value": value,
        "threshold": threshold,
        "remediation": remediation,
    }


def _alert_counts(alerts: list[dict[str, Any]]) -> dict[str, int]:
    return {
        severity: sum(1 for alert in alerts if alert.get("severity") == severity)
        for severity in ("blocker", "warning", "info")
    }


def _strict_true_production_alert_severity(run: dict[str, Any] | None) -> str:
    return "blocker" if _strict_true_production_required(run) else "warning"


def _strict_true_production_marker(value: Any) -> bool:
    text = str(value).lower()
    normalized = text.replace("-", "_")
    if "release" in text or "cutover" in text:
        return True
    if "scoreable" in normalized and "non_scoreable" not in normalized and "non scoreable" not in text:
        return True
    return False


def _strict_true_production_required(run: dict[str, Any] | None) -> bool:
    metadata = run.get("metadata") if isinstance(run, dict) and isinstance(run.get("metadata"), dict) else {}
    runner_mode = str((run or {}).get("runner_mode") or "")
    return (
        runner_mode == "calibration_debt_production"
        or any(_strict_true_production_marker(value) for value in metadata.values())
    )


def _run_stage_failed(run: dict[str, Any] | None) -> bool:
    if not isinstance(run, dict):
        return False
    status = str(run.get("status") or "").lower()
    terminal_reason = str(run.get("terminal_reason") or "").lower()
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    return (
        status == "failed"
        or "stage_failed" in terminal_reason
        or bool(metadata.get("non_retryable_failure"))
    )


def _true_runtime_cutover_status(
    *,
    run: dict[str, Any] | None,
    run_kind: str,
    cases: list[dict[str, Any]],
) -> str:
    if run_kind != "true_production" or not run:
        return "blocked_missing_strict_canary"
    if _run_stage_failed(run):
        return "blocked_stage_failure"
    if not cases:
        return "blocked_missing_strict_canary"
    for case in cases:
        retrieval = case.get("retrieval_sufficiency") or {}
        if not retrieval.get("all_required_leaves_certified") or int(retrieval.get("admitted_evidence_ref_count") or 0) == 0:
            return "blocked_missing_retrieval_cert"
    for case in cases:
        researcher = case.get("researcher_model_provenance") or {}
        if int(researcher.get("model_executed_count") or 0) == 0:
            return "blocked_missing_researcher_model_execution"
    for case in cases:
        scae = case.get("scae_readiness") or {}
        if not scae.get("artifact_id") or scae.get("forecast_validity_status") != "valid_for_forecast":
            return "blocked_missing_scae_ledger"
    return "ready"


def _scae_invalid_research_sufficiency_blocked(
    scae: dict[str, Any],
    verification: dict[str, Any],
) -> bool:
    if scae.get("forecast_validity_status") != "invalid_for_forecast":
        return False
    reason_codes = set(str(code) for code in _as_list(scae.get("reason_codes")))
    reason_codes.update(str(code) for code in _as_list(verification.get("reason_codes")))
    statuses = set(str(status) for status in _as_list(verification.get("reconciliation_statuses")))
    context = scae.get("research_sufficiency_context")
    if isinstance(context, dict):
        reason_codes.update(str(code) for code in _as_list(context.get("blocking_reason_codes")))
        statuses.add(str(context.get("status") or ""))
    return bool(reason_codes & RESEARCH_SUFFICIENCY_BLOCKED_CODES) or bool(
        statuses & {"blocked_insufficient_research", "research_sufficiency_not_certified"}
    )


def _build_alerts(
    *,
    pipeline_run_id: str | None,
    run_kind: str,
    active_runs: list[dict[str, Any]],
    active_leases: list[dict[str, Any]],
    handoff_report: dict[str, Any],
    run: dict[str, Any] | None,
    storage: dict[str, Any],
    freshness: dict[str, Any],
    cases: list[dict[str, Any]],
    active_lease_block_seconds: int,
    active_run_block_seconds: int,
    wal_warning_bytes: int,
    wal_block_bytes: int,
    max_market_snapshot_age_seconds: float,
    max_resolution_sync_age_seconds: float,
    source_freshness_warning_fraction: float,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if not pipeline_run_id:
        alerts.append(_alert(
            "blocker",
            "no_ads_pipeline_run_found",
            "No ADS pipeline run is available for operator review.",
            pipeline_run_id=pipeline_run_id,
            remediation="Run a bounded ADS canary or pass --pipeline-run-id for an existing run.",
        ))
    for active_run in active_runs:
        age = active_run.get("run_age_seconds")
        if age is not None and age > active_run_block_seconds:
            alerts.append(_alert(
                "blocker",
                "active_run_older_than_policy",
                "An ADS pipeline run is still active beyond the operator threshold.",
                pipeline_run_id=active_run.get("pipeline_run_id"),
                value=age,
                threshold=active_run_block_seconds,
                remediation="Inspect the run, then stop or drain with the ADS pipeline control CLI.",
            ))
    for lease in active_leases:
        age = lease.get("lease_age_seconds")
        if age is not None and age > active_lease_block_seconds:
            alerts.append(_alert(
                "blocker",
                "active_lease_older_than_policy",
                "An ADS case lease is still active beyond the operator threshold.",
                pipeline_run_id=lease.get("pipeline_run_id"),
                case_id=lease.get("case_id"),
                case_key=lease.get("case_key"),
                dispatch_id=lease.get("dispatch_id"),
                refs=[lease.get("case_lease_id")],
                value=age,
                threshold=active_lease_block_seconds,
                remediation="Release or quarantine the stale lease before allowing more scheduler work.",
            ))
    snapshot_age = (freshness.get("market_snapshot") or {}).get("age_seconds")
    if snapshot_age is not None and snapshot_age > max_market_snapshot_age_seconds:
        alerts.append(_alert(
            "blocker",
            "market_snapshots_stale",
            "Latest market snapshot is stale beyond policy.",
            pipeline_run_id=pipeline_run_id,
            value=snapshot_age,
            threshold=max_market_snapshot_age_seconds,
            remediation="Refresh market intake/snapshots before the scheduler continues.",
        ))
    elif (
        snapshot_age is not None
        and snapshot_age > max_market_snapshot_age_seconds * source_freshness_warning_fraction
    ):
        alerts.append(_alert(
            "warning",
            "source_freshness_barely_passes",
            "Latest market snapshot is close to the freshness limit.",
            pipeline_run_id=pipeline_run_id,
            value=snapshot_age,
            threshold=max_market_snapshot_age_seconds,
            remediation="Refresh market intake/snapshots soon.",
        ))
    resolution_age = (freshness.get("resolution_sync") or {}).get("age_seconds")
    if resolution_age is not None and resolution_age > max_resolution_sync_age_seconds:
        alerts.append(_alert(
            "blocker",
            "resolution_sync_stale",
            "Latest resolution sync is stale beyond policy.",
            pipeline_run_id=pipeline_run_id,
            value=resolution_age,
            threshold=max_resolution_sync_age_seconds,
            remediation="Run or repair the resolution sync before the scheduler continues.",
        ))
    unresolved = handoff_report.get("unresolved_output_manifest_refs") or []
    if unresolved:
        alerts.append(_alert(
            "blocker",
            "unresolved_manifest_refs",
            "One or more stage output refs do not resolve to artifact manifests.",
            pipeline_run_id=pipeline_run_id,
            refs=[str(item.get("artifact_id") or item.get("ref") or item) for item in unresolved],
            remediation="Run report_ads_handoffs.py for exact refs and repair the producing stage manifest.",
        ))
    elif handoff_report.get("ok") is False:
        alerts.append(_alert(
            "blocker",
            "handoff_report_not_ok",
            "The handoff report is not ok.",
            pipeline_run_id=pipeline_run_id,
            value=handoff_report.get("error"),
            remediation="Run report_ads_handoffs.py --pretty and repair the reported handoff issue.",
        ))
    true_production_issue_severity = _strict_true_production_alert_severity(run)
    if run_kind == "true_production" and _run_stage_failed(run):
        alerts.append(_alert(
            true_production_issue_severity,
            "true_production_stage_failed",
            "True-production run has a failed pipeline stage.",
            pipeline_run_id=pipeline_run_id,
            value=(run or {}).get("terminal_reason"),
            threshold="no stage failure",
            remediation="Inspect the stage error and rerun a strict clone canary before release or cutover.",
        ))
    wal_size = int(storage.get("wal_size_bytes") or 0)
    if wal_size > wal_block_bytes:
        alerts.append(_alert(
            "blocker",
            "db_wal_above_block_threshold",
            "SQLite WAL is above the blocking threshold.",
            pipeline_run_id=pipeline_run_id,
            value=wal_size,
            threshold=wal_block_bytes,
            remediation="Run maintain_ads_storage.py --apply after confirming no active writer is mid-run.",
        ))
    elif wal_size > wal_warning_bytes:
        alerts.append(_alert(
            "warning",
            "db_wal_above_warning_threshold",
            "SQLite WAL is above the warning threshold.",
            pipeline_run_id=pipeline_run_id,
            value=wal_size,
            threshold=wal_warning_bytes,
            remediation="Schedule storage maintenance/checkpointing.",
        ))
    candidate_rows = sum(
        int(item.get("candidate_rows") or 0)
        for item in storage.get("retention_candidates", [])
        if item.get("exists")
    )
    if candidate_rows > 0:
        alerts.append(_alert(
            "warning",
            "storage_maintenance_overdue",
            "Storage maintenance has retention candidates.",
            pipeline_run_id=pipeline_run_id,
            value=candidate_rows,
            threshold=0,
            remediation="Run maintain_ads_storage.py --apply when the pipeline is idle.",
        ))
    for case in cases:
        refs = {
            "pipeline_run_id": pipeline_run_id,
            "case_id": case.get("case_id"),
            "case_key": case.get("case_key"),
            "dispatch_id": case.get("dispatch_id"),
        }
        qdt = case.get("qdt_model_provenance") or {}
        if run_kind == "true_production" and (
            qdt.get("adapter_mode") in PILOT_QDT_ADAPTER_MODES
            or qdt.get("model_executed") is False
        ):
            alerts.append(_alert(
                "blocker",
                "true_production_deterministic_qdt",
                "True-production run lacks verified live model-executed QDT provenance.",
                refs=[qdt.get("artifact_id")] if qdt.get("artifact_id") else [],
                remediation="Use predquant.ads_production_handlers with decomposer_model_runtime_live.",
                **refs,
            ))
        researcher = case.get("researcher_model_provenance") or {}
        if run_kind == "true_production" and researcher.get("metadata_only"):
            alerts.append(_alert(
                "blocker",
                "true_production_metadata_only_researcher",
                "True-production run used metadata-only researcher output.",
                refs=[
                    item.get("artifact_id")
                    for item in researcher.get("classification_artifacts", [])
                    if item.get("artifact_id")
                ],
                remediation="Require model-executed researcher sidecars/runtime bundles before scoreable expansion.",
                **refs,
            ))
        if run_kind == "true_production" and int(researcher.get("model_executed_count") or 0) == 0:
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_researcher_runtime_missing",
                "True-production run has no verified researcher model executions.",
                refs=[
                    item.get("artifact_id")
                    for item in researcher.get("classification_artifacts", [])
                    if item.get("artifact_id")
                ],
                value=researcher.get("model_executed_count") or 0,
                threshold=">=1",
                remediation="Require model-executed researcher sidecars/runtime bundles before release or cutover.",
                **refs,
            ))
        for amrg in case.get("amrg_consumed_hints", []):
            if amrg.get("vector_status") == "unavailable":
                alerts.append(_alert(
                    "warning",
                    "amrg_vector_unavailable",
                    "AMRG vector runtime is unavailable for this case.",
                    refs=[amrg.get("artifact_id")],
                    remediation="Run AMRG vector preflight or accept weak-context-only operation explicitly.",
                    **refs,
                ))
            relationship_counts = amrg.get("relationship_status_counts") or {}
            weak_count = sum(int(relationship_counts.get(status, 0)) for status in WEAK_AMRG_STATUSES)
            if weak_count:
                alerts.append(_alert(
                    "warning",
                    "amrg_weak_context_only",
                    "AMRG supplied weak-context-only hints.",
                    refs=[amrg.get("artifact_id")],
                    value=weak_count,
                    remediation="Treat AMRG hints as decomposition context only; do not promote to probability authority.",
                    **refs,
                ))
            if amrg.get("missing_refresh_status_refs"):
                alerts.append(_alert(
                    "blocker",
                    "missing_amrg_refresh_status_for_promoted_effects",
                    "AMRG promoted-effect context is missing refresh lifecycle status.",
                    refs=[amrg.get("artifact_id"), *amrg.get("missing_refresh_status_refs", [])],
                    remediation="Refresh or downgrade promoted AMRG effects before scoreable live operation.",
                    **refs,
                ))
        retrieval = case.get("retrieval_sufficiency") or {}
        native_unavailable = any(
            isinstance(item, dict) and item.get("availability_status") == "unavailable"
            for item in retrieval.get("native_research_transport_diagnostics", [])
        )
        if run_kind == "true_production" and not retrieval.get("all_required_leaves_certified"):
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_retrieval_not_certified",
                "True-production retrieval did not certify all required leaves.",
                refs=[retrieval.get("artifact_id")] if retrieval.get("artifact_id") else [],
                value=retrieval.get("all_required_leaves_certified"),
                threshold=True,
                remediation="Repair retrieval sufficiency before release or cutover.",
                **refs,
            ))
        if run_kind == "true_production" and int(retrieval.get("admitted_evidence_ref_count") or 0) == 0:
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_zero_admitted_evidence_refs",
                "True-production retrieval admitted zero evidence refs.",
                refs=[retrieval.get("artifact_id")] if retrieval.get("artifact_id") else [],
                value=retrieval.get("admitted_evidence_ref_count") or 0,
                threshold=">=1",
                remediation="Populate certified retrieval evidence before release or cutover.",
                **refs,
            ))
        if (
            run_kind == "true_production"
            and int(retrieval.get("browser_retrieval_attempt_count") or 0) == 0
            and native_unavailable
        ):
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_browser_retrieval_missing_native_unavailable",
                "True-production retrieval had no browser attempts while native discovery was unavailable.",
                refs=[retrieval.get("artifact_id")] if retrieval.get("artifact_id") else [],
                value=retrieval.get("browser_retrieval_attempt_count") or 0,
                threshold=">=1",
                remediation="Enable browser retrieval fallback or restore native discovery before release or cutover.",
                **refs,
            ))
        if native_unavailable and retrieval.get("all_required_leaves_certified"):
            alerts.append(_alert(
                "warning",
                "native_research_unavailable_browser_retrieval_sufficient",
                "Native research is unavailable, but browser retrieval sufficiency passed.",
                refs=[retrieval.get("artifact_id")] if retrieval.get("artifact_id") else [],
                remediation="Keep this run watch-only unless browser evidence is explicitly accepted.",
                **refs,
            ))
        scae = case.get("scae_readiness") or {}
        verification = case.get("verification_readiness") or {}
        if run_kind == "true_production" and not scae.get("artifact_id"):
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_scae_ledger_missing",
                "True-production run has no SCAE ledger artifact for this case.",
                refs=[],
                value=scae.get("artifact_id"),
                threshold="scae ledger artifact",
                remediation="Run verification-to-SCAE integration or record a structured SCAE blocker before release or cutover.",
                **refs,
            ))
        if (
            run_kind == "true_production"
            and scae.get("artifact_id")
            and scae.get("forecast_validity_status") != "valid_for_forecast"
        ):
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_scae_ledger_not_valid_for_forecast",
                "True-production SCAE ledger is not valid for a scoreable forecast.",
                refs=[scae.get("artifact_id")],
                value=scae.get("forecast_validity_status"),
                threshold="valid_for_forecast",
                remediation="Repair verification-to-SCAE inputs or keep the run explicitly non-scoreable before release or cutover.",
                **refs,
            ))
        if run_kind == "true_production" and _scae_invalid_research_sufficiency_blocked(scae, verification):
            alerts.append(_alert(
                true_production_issue_severity,
                "true_production_scae_invalid_research_sufficiency_blocked",
                "True-production SCAE output is invalid for forecast because research sufficiency is blocked.",
                refs=[scae.get("artifact_id")] if scae.get("artifact_id") else [],
                value=scae.get("forecast_validity_status"),
                threshold="valid_for_forecast",
                remediation="Resolve research sufficiency blockers before release or cutover.",
                **refs,
            ))
        if scae.get("scoreable_forecast_output") and not scae.get("evidence_delta_ref_count"):
            alerts.append(_alert(
                "blocker",
                "missing_scae_evidence_delta_refs",
                "Scoreable SCAE output is missing evidence delta refs.",
                refs=[scae.get("artifact_id")] if scae.get("artifact_id") else [],
                remediation="Repair verification-to-SCAE evidence delta refs before scoreable persistence.",
                **refs,
            ))
        decision = case.get("decision_and_prediction") or {}
        for row in decision.get("forecast_decision_records", []):
            if row.get("probability_source") != SCAE_PROBABILITY_SOURCE:
                alerts.append(_alert(
                    "blocker",
                    "non_scae_probability_authority",
                    "Forecast decision row does not cite SCAE as probability authority.",
                    refs=[row.get("forecast_decision_id")],
                    value=row.get("probability_source"),
                    threshold=SCAE_PROBABILITY_SOURCE,
                    remediation="Quarantine the row and replay from the SCAE decision stage.",
                    **refs,
                ))
        for row in decision.get("market_predictions", []):
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if metadata.get("scoreable_prediction_source") != SCAE_MARKET_PREDICTION_SOURCE:
                alerts.append(_alert(
                    "blocker",
                    "non_scae_market_prediction_authority",
                    "Market prediction row does not cite SCAE as scoreable prediction source.",
                    refs=[str(row.get("id"))],
                    value=metadata.get("scoreable_prediction_source"),
                    threshold=SCAE_MARKET_PREDICTION_SOURCE,
                    remediation="Quarantine the prediction and replay from the SCAE decision stage.",
                    **refs,
                ))
    if not alerts:
        alerts.append(_alert(
            "info",
            "operator_review_no_alerts",
            "Operator review found no blockers or warnings.",
            pipeline_run_id=pipeline_run_id,
            remediation="No action required.",
        ))
    return alerts


def build_ads_operator_review_report(
    db_path: Path | str,
    *,
    pipeline_run_id: str | None = None,
    max_market_snapshot_age_seconds: float = 3600.0,
    max_resolution_sync_age_seconds: float = 5400.0,
    storage_retention_days: int = 90,
    prediction_source: str | None = "ads_pipeline",
    prediction_label: str | None = "v2_scae",
    evaluation_cluster_id: str = "calibration-debt-clearance",
    active_lease_block_seconds: int = DEFAULT_ACTIVE_LEASE_BLOCK_SECONDS,
    active_run_block_seconds: int = DEFAULT_ACTIVE_RUN_BLOCK_SECONDS,
    wal_warning_bytes: int = DEFAULT_WAL_WARNING_BYTES,
    wal_block_bytes: int = DEFAULT_WAL_BLOCK_BYTES,
    source_freshness_warning_fraction: float = DEFAULT_SOURCE_FRESHNESS_WARNING_FRACTION,
) -> dict[str, Any]:
    path = Path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        ensure_pipeline_runner_schema(conn)
        ensure_stage_logging_schema(conn)
        ensure_artifact_manifest_schema(conn)
        resolved_run_id = pipeline_run_id or _latest_run_id(conn)
        run = _run_row(conn, resolved_run_id)
        leases = _lease_rows(conn, resolved_run_id)
        manifests = _manifest_rows(conn, resolved_run_id)
        decisions = _forecast_decision_rows(conn, resolved_run_id)
        predictions = _market_prediction_rows(conn, decisions)
        traces = _trace_rows(conn, resolved_run_id)
        active_runs = _active_run_rows(conn)
        active_leases = _active_lease_rows(conn)
        freshness = {
            "market_snapshot": _latest_snapshot_status(conn),
            "resolution_sync": _latest_resolution_status(conn),
        }
        control = read_pipeline_control_state(conn)
    finally:
        conn.close()
    handoff = (
        build_handoff_report(path, pipeline_run_id=resolved_run_id)
        if resolved_run_id
        else {"ok": False, "error": "no ADS pipeline runs found", "unresolved_output_manifest_refs": []}
    )
    storage = build_storage_maintenance_plan(path, retention_days=storage_retention_days)
    scoring = brier_score_report(
        path,
        prediction_source=prediction_source,
        prediction_label=prediction_label,
        evaluation_cluster_id=evaluation_cluster_id,
    )
    run_kind = _infer_run_kind(run, manifests)
    cases = _case_reports(leases, manifests, decisions, predictions, traces)
    alerts = _build_alerts(
        pipeline_run_id=resolved_run_id,
        run_kind=run_kind,
        active_runs=active_runs,
        active_leases=active_leases,
        handoff_report=handoff,
        run=run,
        storage=storage,
        freshness=freshness,
        cases=cases,
        active_lease_block_seconds=active_lease_block_seconds,
        active_run_block_seconds=active_run_block_seconds,
        wal_warning_bytes=wal_warning_bytes,
        wal_block_bytes=wal_block_bytes,
        max_market_snapshot_age_seconds=max_market_snapshot_age_seconds,
        max_resolution_sync_age_seconds=max_resolution_sync_age_seconds,
        source_freshness_warning_fraction=source_freshness_warning_fraction,
    )
    counts = _alert_counts(alerts)
    true_runtime_cutover_status = _true_runtime_cutover_status(
        run=run,
        run_kind=run_kind,
        cases=cases,
    )
    review_status = (
        "blocked"
        if counts["blocker"]
        else "review_warned"
        if counts["warning"]
        else "review_passed"
    )
    return {
        "schema_version": ADS_OPERATOR_REVIEW_SCHEMA_VERSION,
        "ok": counts["blocker"] == 0,
        "scheduler_may_continue": counts["blocker"] == 0,
        "status": review_status,
        "true_runtime_cutover_status": true_runtime_cutover_status,
        "true_runtime_cutover_ready": true_runtime_cutover_status == "ready",
        "db_path": str(path),
        "pipeline_run_id": resolved_run_id,
        "run": run,
        "run_kind": run_kind,
        "pipeline_control": control,
        "alert_counts_by_severity": counts,
        "alerts": alerts,
        "active_work": {
            "active_runs": len(active_runs),
            "active_leases": len(active_leases),
            "active_run_refs": [row.get("pipeline_run_id") for row in active_runs],
            "active_lease_refs": [row.get("case_lease_id") for row in active_leases],
        },
        "freshness": freshness,
        "cases": cases,
        "handoff_report": handoff,
        "storage_maintenance_plan": storage,
        "brier_score_report": scoring,
    }


__all__ = [
    "ADS_OPERATOR_REVIEW_SCHEMA_VERSION",
    "build_ads_operator_review_report",
]
