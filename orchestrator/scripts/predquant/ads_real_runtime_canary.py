"""ADS real-runtime canary criteria and operator report helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predquant.ads_case_selector import CASE_LEASE_TABLE
from predquant.ads_handoff_report import build_handoff_report
from predquant.ads_pipeline_runner import (
    PIPELINE_RUN_TABLE,
    ensure_pipeline_runner_schema,
    read_pipeline_control_state,
)
from predquant.ads_stage_logging import PIPELINE_ERROR_EVENT_TABLE, ensure_stage_logging_schema
from predquant.ads_storage_maintenance import build_storage_maintenance_plan
from predquant.amrg import build_amrg_operator_report
from predquant.calibration_debt import build_calibration_debt_clearance_report
from predquant.sqlite_store import brier_score_report, ensure_schema


REAL_RUNTIME_CANARY_REPORT_SCHEMA_VERSION = "ads-real-runtime-canary-report/v1"
REAL_RUNTIME_CANARY_CRITERIA_SCHEMA_VERSION = "ads-real-runtime-canary-criteria/v1"
REQUIRED_RUNTIME_MODEL_ID = "gpt-5.5-high"
REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS = {
    REQUIRED_RUNTIME_MODEL_ID,
    "openai/gpt-5.5-high",
}
SCAE_PROBABILITY_SOURCE = "SCAE-012.production_forecast_prob"
SCAE_MARKET_PREDICTION_SOURCE = "scae.production_forecast_prob"
DEFAULT_WAL_WARNING_BYTES = 512 * 1024 * 1024
DEFAULT_WAL_BLOCK_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_CASE_WARNING_SECONDS = 30 * 60
DEFAULT_CASE_BLOCK_SECONDS = 60 * 60


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


def _active_work_counts(conn: sqlite3.Connection) -> dict[str, int]:
    ensure_pipeline_runner_schema(conn)
    active_runs = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {PIPELINE_RUN_TABLE}
            WHERE status IN ('starting', 'running', 'draining')
            """
        ).fetchone()[0]
    )
    active_leases = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {CASE_LEASE_TABLE}
            WHERE lease_status = 'leased'
            """
        ).fetchone()[0]
    )
    return {"active_runs": active_runs, "active_leases": active_leases}


def _run_row(conn: sqlite3.Connection, pipeline_run_id: str | None) -> dict[str, Any] | None:
    if not pipeline_run_id or not _table_exists(conn, PIPELINE_RUN_TABLE):
        return None
    row = conn.execute(
        f"SELECT * FROM {PIPELINE_RUN_TABLE} WHERE pipeline_run_id = ?",
        (pipeline_run_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["stage_order"] = _decode_json(result.get("stage_order"), [])
    result["idle_policy"] = _decode_json(result.get("idle_policy"), {})
    result["metadata"] = _decode_json(result.get("metadata"), {})
    return result


def _run_duration_seconds(run: dict[str, Any] | None) -> float | None:
    if not run or not run.get("started_at") or not run.get("stopped_at"):
        return None
    started = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
    stopped = datetime.fromisoformat(str(run["stopped_at"]).replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if stopped.tzinfo is None:
        stopped = stopped.replace(tzinfo=timezone.utc)
    return max(0.0, (stopped.astimezone(timezone.utc) - started.astimezone(timezone.utc)).total_seconds())


def _stage_error_events(
    conn: sqlite3.Connection,
    pipeline_run_id: str | None,
    *,
    allowed_failure_classes: tuple[str, ...],
) -> dict[str, Any]:
    ensure_stage_logging_schema(conn)
    if not _table_exists(conn, PIPELINE_ERROR_EVENT_TABLE):
        return {
            "count": 0,
            "unexpected_count": 0,
            "events": [],
            "allowed_failure_classes": list(allowed_failure_classes),
        }
    if pipeline_run_id:
        rows = conn.execute(
            f"""
            SELECT error_event_id, stage, failure_class, retryability, safe_message, safe_metadata
            FROM {PIPELINE_ERROR_EVENT_TABLE}
            WHERE pipeline_run_id = ?
            ORDER BY id
            """,
            (pipeline_run_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT error_event_id, stage, failure_class, retryability, safe_message, safe_metadata
            FROM {PIPELINE_ERROR_EVENT_TABLE}
            ORDER BY id
            """
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["safe_metadata"] = _decode_json(item.get("safe_metadata"), {})
        item["expected"] = item["failure_class"] in allowed_failure_classes
        events.append(item)
    return {
        "count": len(events),
        "unexpected_count": sum(1 for event in events if not event["expected"]),
        "events": events,
        "allowed_failure_classes": list(allowed_failure_classes),
    }


def _manifest_items(handoff_report: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for stage in handoff_report.get("stages", []):
        for manifest in stage.get("output_manifests", []):
            if manifest.get("resolved") and not manifest.get("non_manifest_ref"):
                items.append(manifest)
    return items


def _load_manifest_payload(manifest: dict[str, Any]) -> dict[str, Any] | None:
    path = manifest.get("path") or manifest.get("artifact_path")
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _model_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    qdt_manifests = [item for item in manifests if item.get("artifact_type") == "question-decomposition"]
    runtime_manifests = [item for item in manifests if item.get("artifact_type") == "model-runtime-call"]
    qdt_results = []
    runtime_results = []
    for manifest in qdt_manifests:
        payload = _load_manifest_payload(manifest) or {}
        leaf_ids = [
            str(leaf.get("leaf_id"))
            for leaf in payload.get("required_leaf_questions", [])
            if isinstance(leaf, dict) and leaf.get("leaf_id")
        ]
        generic_leaf_ids = {"leaf-source-of-truth", "leaf-direct-evidence", "leaf-resolution-mechanics"}
        question_specific = bool(leaf_ids) and not bool(generic_leaf_ids & set(leaf_ids))
        qdt_results.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "adapter_mode": payload.get("adapter_mode"),
                "runtime_call_ref": payload.get("runtime_call_ref"),
                "leaf_count": len(leaf_ids),
                "question_specific": question_specific,
                "ok": (
                    payload.get("adapter_mode") == "decomposer_model_runtime_live"
                    and bool(payload.get("runtime_call_ref"))
                    and question_specific
                ),
            }
        )
    for manifest in runtime_manifests:
        payload = _load_manifest_payload(manifest) or {}
        runtime_results.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "resolved_model_id": payload.get("resolved_model_id"),
                "mode": payload.get("mode"),
                "fixture_mode": payload.get("fixture_mode"),
                "execution_status": payload.get("execution_status"),
                "ok": (
                    payload.get("resolved_model_id") == REQUIRED_RUNTIME_MODEL_ID
                    and payload.get("mode") == "live"
                    and payload.get("fixture_mode") is False
                    and payload.get("execution_status") in {"succeeded", "accepted"}
                ),
            }
        )
    return {
        "required_model_id": REQUIRED_RUNTIME_MODEL_ID,
        "qdt_count": len(qdt_results),
        "qdt_model_executed_count": sum(1 for item in qdt_results if item["ok"]),
        "runtime_call_count": len(runtime_results),
        "runtime_call_model_executed_count": sum(1 for item in runtime_results if item["ok"]),
        "qdt_results": qdt_results,
        "runtime_results": runtime_results,
        "ok": bool(qdt_results)
        and all(item["ok"] for item in qdt_results)
        and bool(runtime_results)
        and all(item["ok"] for item in runtime_results),
    }


def _researcher_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    sidecar_artifact_types = {"researcher-sidecar", "researcher_sidecar"}
    bundle_artifact_types = {"researcher-swarm-runtime-bundle", "researcher_swarm_runtime_bundle"}
    classification_artifact_types = {
        "leaf-research-barrier",
        "researcher-classification-readiness-block",
        "researcher-classification-production-pilot",
    }
    sidecars = []
    bundles = []
    classifications = []
    for manifest in manifests:
        artifact_type = str(manifest.get("artifact_type") or "")
        payload = _load_manifest_payload(manifest) or {}
        if artifact_type in sidecar_artifact_types or payload.get("artifact_type") == "researcher_sidecar":
            context = payload.get("model_execution_context") if isinstance(payload.get("model_execution_context"), dict) else {}
            runtime = context.get("runtime") if isinstance(context.get("runtime"), dict) else {}
            sidecars.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "resolved_model_id": context.get("resolved_model_id"),
                    "model_executed": runtime.get("model_executed"),
                    "execution_status": runtime.get("execution_status"),
                    "ok": (
                        context.get("resolved_model_id") in REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS
                        and runtime.get("model_executed") is True
                        and runtime.get("execution_status") in {"succeeded", "accepted"}
                    ),
                }
            )
        elif artifact_type in bundle_artifact_types or payload.get("artifact_type") == "researcher_swarm_runtime_bundle":
            leaf_runtime_status = payload.get("leaf_runtime_status") if isinstance(payload.get("leaf_runtime_status"), list) else []
            bundle_ok = bool(leaf_runtime_status) and all(
                isinstance(row, dict)
                and row.get("model_executed") is True
                and row.get("resolved_model_id") in REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS
                for row in leaf_runtime_status
            )
            bundles.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "leaf_runtime_count": len(leaf_runtime_status),
                    "ok": bundle_ok,
                }
            )
        elif artifact_type in classification_artifact_types:
            classifications.append(
                {
                    "artifact_id": manifest.get("artifact_id"),
                    "artifact_type": artifact_type,
                    "classification_status": payload.get("classification_status"),
                    "reason_codes": list(payload.get("reason_codes") or []),
                }
            )
    model_executed_count = sum(1 for item in sidecars if item["ok"]) + sum(1 for item in bundles if item["ok"])
    blocked_statuses = {
        "blocked_until_certified_retrieval",
        "blocked_leaf_research_barrier",
    }
    blocked_non_scoreable = bool(classifications) and all(
        item.get("classification_status") in blocked_statuses for item in classifications
    )
    return {
        "required_model_id": REQUIRED_RUNTIME_MODEL_ID,
        "accepted_researcher_runtime_model_ids": sorted(REQUIRED_RESEARCHER_RUNTIME_MODEL_IDS),
        "sidecar_count": len(sidecars),
        "runtime_bundle_count": len(bundles),
        "model_executed_count": model_executed_count,
        "sidecars": sidecars,
        "runtime_bundles": bundles,
        "classification_artifacts": classifications,
        "blocked_non_scoreable": blocked_non_scoreable,
        "ok": model_executed_count > 0 and all(item["ok"] for item in sidecars) and all(item["ok"] for item in bundles),
    }


def _evidence_refs_from(value: Any) -> set[str]:
    refs: set[str] = set()
    if not isinstance(value, list):
        return refs
    for item in value:
        if isinstance(item, str) and item:
            refs.add(item)
        elif isinstance(item, dict):
            ref = item.get("evidence_ref") or item.get("ref")
            if ref:
                refs.add(str(ref))
    return refs


def _retrieval_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_packets = []
    for manifest in manifests:
        if manifest.get("artifact_type") != "retrieval-packet":
            continue
        payload = _load_manifest_payload(manifest) or {}
        runtime_summary = payload.get("retrieval_runtime_summary") if isinstance(payload.get("retrieval_runtime_summary"), dict) else {}
        adapter_mode = str(payload.get("adapter_mode") or "")
        structured_market_metadata_pilot = bool(
            adapter_mode == "structured_market_metadata_pilot_retrieval"
            or runtime_summary.get("runtime_mode") == "structured_market_metadata_pilot"
            or runtime_summary.get("structured_market_metadata_pilot") is True
            or (
                isinstance(payload.get("structured_market_metadata_pilot_proof_boundary"), dict)
                and payload["structured_market_metadata_pilot_proof_boundary"].get(
                    "counts_as_real_retrieval_canary_proof"
                )
                is False
            )
        )
        transport = (
            payload.get("ads_retrieval_transport_diagnostics")
            if isinstance(payload.get("ads_retrieval_transport_diagnostics"), dict)
            else {}
        )
        sufficiency = (
            payload.get("research_sufficiency_summary")
            if isinstance(payload.get("research_sufficiency_summary"), dict)
            else {}
        )
        leaf_results = payload.get("leaf_retrieval_results") if isinstance(payload.get("leaf_retrieval_results"), list) else []
        leaf_dockets = payload.get("leaf_evidence_dockets") if isinstance(payload.get("leaf_evidence_dockets"), list) else []
        certificates = (
            payload.get("leaf_research_sufficiency_certificates")
            if isinstance(payload.get("leaf_research_sufficiency_certificates"), list)
            else []
        )
        direct_url_candidates = payload.get("ads_retrieval_direct_url_candidates")
        if not isinstance(direct_url_candidates, list):
            direct_url_candidates = []
        browser_attempts = (
            payload.get("browser_retrieval_attempts")
            if isinstance(payload.get("browser_retrieval_attempts"), list)
            else []
        )
        search_candidate_urls = (
            payload.get("search_candidate_urls")
            if isinstance(payload.get("search_candidate_urls"), list)
            else []
        )
        native_discoveries = (
            payload.get("native_research_candidate_discoveries")
            if isinstance(payload.get("native_research_candidate_discoveries"), list)
            else []
        )
        metadata_classifier_slices = (
            payload.get("source_metadata_classifier_slices")
            if isinstance(payload.get("source_metadata_classifier_slices"), list)
            else []
        )
        metadata_classifier_unavailable = (
            payload.get("source_metadata_classifier_unavailable_diagnostics")
            if isinstance(payload.get("source_metadata_classifier_unavailable_diagnostics"), list)
            else []
        )
        source_attempt_count = sum(
            int(runtime_summary.get(field) or 0)
            for field in (
                "direct_url_attempt_count",
                "browser_attempt_count",
                "native_attempt_count",
                "structured_feed_attempt_count",
            )
        )
        source_attempt_count += int(transport.get("direct_url_candidate_count") or 0)
        source_attempt_count += len(direct_url_candidates)
        direct_url_candidate_count = max(
            len(direct_url_candidates),
            int(transport.get("direct_url_candidate_count") or 0),
        )
        search_candidate_url_count = max(
            len(search_candidate_urls),
            int(runtime_summary.get("search_candidate_url_count") or 0),
            int(transport.get("search_candidate_url_count") or 0),
        )
        native_candidate_url_count = max(
            int(runtime_summary.get("native_candidate_url_count") or 0),
            sum(
                len(item.get("candidate_urls", []))
                for item in native_discoveries
                if isinstance(item, dict) and isinstance(item.get("candidate_urls"), list)
            ),
        )
        fetched_attempt_count = max(
            len(browser_attempts),
            int(runtime_summary.get("direct_url_attempt_count") or 0)
            + int(runtime_summary.get("web_search_attempt_count") or 0),
            int(transport.get("fetched_candidate_count") or 0),
        )
        real_candidate_count = (
            direct_url_candidate_count
            + search_candidate_url_count
            + native_candidate_url_count
        )
        direct_url_capture_executed = bool(
            runtime_summary.get("direct_url_capture_executed") is True
            or transport.get("direct_url_capture_executed") is True
            or direct_url_candidate_count > 0
        )
        browser_search_executed = bool(
            runtime_summary.get("browser_search_executed") is True
            or transport.get("browser_search_executed") is True
            or int(transport.get("search_call_count") or 0) > 0
        )
        native_research_model_executed = bool(
            runtime_summary.get("native_research_model_executed") is True
            or transport.get("native_research_model_executed") is True
            or int(runtime_summary.get("native_research_call_count") or 0) > 0
            or int(transport.get("native_research_call_count") or 0) > 0
        )
        metadata_classifier_assist_executed = bool(
            runtime_summary.get("metadata_classifier_assist_executed") is True
            or metadata_classifier_slices
        )
        direct_url_capture_status = str(
            transport.get("direct_url_capture_status")
            or runtime_summary.get("direct_url_capture_status")
            or ("executed" if direct_url_capture_executed else "not_executed")
        )
        browser_search_status = str(
            transport.get("browser_search_status")
            or runtime_summary.get("browser_search_status")
            or ("executed" if browser_search_executed else "not_executed")
        )
        native_research_status = str(
            transport.get("native_research_status")
            or runtime_summary.get("native_research_status")
            or ("executed" if native_research_model_executed else "not_executed")
        )
        metadata_classifier_assist_status = str(
            runtime_summary.get("metadata_classifier_assist_status")
            or (
                "executed"
                if metadata_classifier_assist_executed
                else "unavailable"
                if metadata_classifier_unavailable
                else "not_executed"
            )
        )
        external_source_discovery_proven = bool(
            not structured_market_metadata_pilot
            and real_candidate_count > 0
            and (
                direct_url_capture_executed
                or browser_search_executed
                or native_research_model_executed
            )
        )
        if runtime_summary.get("external_source_discovery_proven") is True:
            external_source_discovery_proven = not structured_market_metadata_pilot
        leaf_result_admitted_refs: set[str] = set()
        selected_refs: set[str] = _evidence_refs_from(payload.get("selected_evidence_refs"))
        for row in leaf_results:
            if not isinstance(row, dict):
                continue
            leaf_result_admitted_refs.update(_evidence_refs_from(row.get("admitted_evidence_refs")))
            selected_refs.update(_evidence_refs_from(row.get("selected_evidence_refs")))
            selected_refs.update(_evidence_refs_from(row.get("selected_evidence")))
        docket_admitted_refs: set[str] = set()
        for row in leaf_dockets:
            if isinstance(row, dict):
                docket_admitted_refs.update(_evidence_refs_from(row.get("admitted_evidence_refs")))
        admitted_refs = set(leaf_result_admitted_refs)
        admitted_refs.update(docket_admitted_refs)
        reported_refs = set(admitted_refs)
        reported_refs.update(selected_refs)
        structural_unanswerable_count = sum(
            1
            for row in [*leaf_results, *certificates]
            if isinstance(row, dict)
            and (
                bool(row.get("structural_unanswerability_acknowledged"))
                or bool(row.get("structural_unanswerability_proof_ref"))
                or row.get("certificate_status") == "structurally_unanswerable_certified"
            )
        )
        structural_unanswerability_certified = (
            bool(leaf_results or certificates)
            and structural_unanswerable_count >= max(1, len(leaf_results))
        )
        dispatch_allowed = sufficiency.get("classification_dispatch_status") == "allowed"
        retrieval_has_real_candidates = real_candidate_count > 0
        retrieval_has_fetch_attempts = fetched_attempt_count > 0
        retrieval_has_admitted_evidence = len(admitted_refs) > 0
        retrieval_packets.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "adapter_mode": adapter_mode,
                "runtime_mode": runtime_summary.get("runtime_mode"),
                "classification_dispatch_status": sufficiency.get("classification_dispatch_status"),
                "structured_market_metadata_pilot": structured_market_metadata_pilot,
                "external_source_discovery_proven": external_source_discovery_proven,
                "source_attempt_count": source_attempt_count,
                "direct_url_candidate_count": direct_url_candidate_count,
                "search_candidate_url_count": search_candidate_url_count,
                "native_candidate_url_count": native_candidate_url_count,
                "real_candidate_count": real_candidate_count,
                "fetched_attempt_count": fetched_attempt_count,
                "browser_search_executed": browser_search_executed,
                "browser_search_status": browser_search_status,
                "direct_url_capture_executed": direct_url_capture_executed,
                "direct_url_capture_status": direct_url_capture_status,
                "native_research_model_executed": native_research_model_executed,
                "native_research_status": native_research_status,
                "metadata_classifier_assist_executed": metadata_classifier_assist_executed,
                "metadata_classifier_assist_status": metadata_classifier_assist_status,
                "metadata_classifier_slice_count": len(metadata_classifier_slices),
                "metadata_classifier_unavailable_count": len(metadata_classifier_unavailable),
                "admitted_evidence_ref_count": len(admitted_refs),
                "leaf_result_admitted_evidence_ref_count": len(leaf_result_admitted_refs),
                "docket_admitted_evidence_ref_count": len(docket_admitted_refs),
                "selected_evidence_ref_count": len(selected_refs),
                "reported_evidence_ref_count": len(reported_refs),
                "structural_unanswerability_certified": structural_unanswerability_certified,
                "classification_dispatch_allowed": dispatch_allowed,
                "retrieval_has_real_candidates": retrieval_has_real_candidates,
                "retrieval_has_fetch_attempts": retrieval_has_fetch_attempts,
                "retrieval_has_admitted_evidence": retrieval_has_admitted_evidence,
                "source_populated_or_structural_unanswerability": bool(
                    (
                        retrieval_has_real_candidates
                        and retrieval_has_fetch_attempts
                        and retrieval_has_admitted_evidence
                        and external_source_discovery_proven
                    )
                    or structural_unanswerability_certified
                ),
            }
        )
    return {
        "retrieval_packet_count": len(retrieval_packets),
        "source_populated_count": sum(
            1 for item in retrieval_packets if item["source_populated_or_structural_unanswerability"]
        ),
        "real_candidate_count": sum(int(item["real_candidate_count"]) for item in retrieval_packets),
        "fetched_attempt_count": sum(int(item["fetched_attempt_count"]) for item in retrieval_packets),
        "admitted_evidence_ref_count": sum(
            int(item["admitted_evidence_ref_count"]) for item in retrieval_packets
        ),
        "external_source_discovery_proven_count": sum(
            1 for item in retrieval_packets if item["external_source_discovery_proven"]
        ),
        "structured_market_metadata_pilot_packet_count": sum(
            1 for item in retrieval_packets if item["structured_market_metadata_pilot"]
        ),
        "browser_search_executed_count": sum(
            1 for item in retrieval_packets if item["browser_search_executed"]
        ),
        "direct_url_capture_executed_count": sum(
            1 for item in retrieval_packets if item["direct_url_capture_executed"]
        ),
        "native_research_model_executed_count": sum(
            1 for item in retrieval_packets if item["native_research_model_executed"]
        ),
        "metadata_classifier_assist_executed_count": sum(
            1 for item in retrieval_packets if item["metadata_classifier_assist_executed"]
        ),
        "classification_dispatch_allowed": any(item["classification_dispatch_allowed"] for item in retrieval_packets),
        "retrieval_packets": retrieval_packets,
        "ok": bool(retrieval_packets)
        and all(item["source_populated_or_structural_unanswerability"] for item in retrieval_packets),
    }


def _scae_runtime_evidence(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    ledgers = []
    for manifest in manifests:
        if manifest.get("artifact_type") not in {
            "scae-final-ledger",
            "scae-final-probability-ledger",
        }:
            continue
        payload = _load_manifest_payload(manifest) or {}
        delta_refs = payload.get("scae_evidence_delta_candidate_slice_refs")
        if not isinstance(delta_refs, list):
            delta_refs = []
        forecast_validity = str(payload.get("forecast_validity_status") or "unknown")
        valid_forecast = forecast_validity != "invalid_for_forecast"
        ledgers.append(
            {
                "artifact_id": manifest.get("artifact_id"),
                "forecast_validity_status": forecast_validity,
                "scoreable_forecast_output": bool(payload.get("scoreable_forecast_output")),
                "scae_evidence_delta_ref_count": len(delta_refs),
                "valid_forecast_requires_delta_refs": valid_forecast,
                "ok": (not valid_forecast) or bool(delta_refs),
            }
        )
    return {
        "ledger_count": len(ledgers),
        "valid_forecast_count": sum(1 for item in ledgers if item["valid_forecast_requires_delta_refs"]),
        "delta_ref_count": sum(int(item["scae_evidence_delta_ref_count"]) for item in ledgers),
        "ledgers": ledgers,
        "ok": all(item["ok"] for item in ledgers),
    }


def _forecast_decisions_for_run(conn: sqlite3.Connection, pipeline_run_id: str | None) -> list[dict[str, Any]]:
    if not pipeline_run_id or not _table_exists(conn, "forecast_decision_records"):
        return []
    rows = conn.execute(
        """
        SELECT forecast_decision_id, case_id, case_key, dispatch_id, run_id,
               production_persistence_status, production_forecast_persisted,
               scoreable_forecast_output, writes_market_prediction,
               probability_source, non_scoreable_reason_code
        FROM forecast_decision_records
        WHERE run_id = ?
        ORDER BY id
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _market_predictions_for_decisions(conn: sqlite3.Connection, decision_ids: set[str]) -> list[dict[str, Any]]:
    if not decision_ids or not _table_exists(conn, "market_predictions"):
        return []
    rows = conn.execute(
        """
        SELECT id, market_id, case_key, case_id, dispatch_id, prediction_source,
               prediction_label, prediction_run_id, forecast_artifact_id, metadata
        FROM market_predictions
        ORDER BY id
        """
    ).fetchall()
    matched = []
    for row in rows:
        item = dict(row)
        metadata = _decode_json(item.get("metadata"), {})
        if metadata.get("forecast_decision_id") in decision_ids:
            item["metadata"] = metadata
            matched.append(item)
    return matched


def _prediction_delta_evidence(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str | None,
    canary_result: dict[str, Any] | None,
    expected_cases: int | None,
    expected_forecast_decision_records: int | None,
    expected_market_predictions: int | None,
) -> dict[str, Any]:
    deltas = dict((canary_result or {}).get("protected_count_deltas") or {})
    decisions = _forecast_decisions_for_run(conn, pipeline_run_id)
    decision_ids = {str(row["forecast_decision_id"]) for row in decisions}
    matched_predictions = _market_predictions_for_decisions(conn, decision_ids)
    forecast_delta = deltas.get("forecast_decision_records", len(decisions))
    prediction_delta = deltas.get("market_predictions", len(matched_predictions))
    delta_source = "protected_count_deltas" if deltas else "pipeline_run_records"
    duplicate_keys: dict[str, int] = {}
    for row in matched_predictions:
        key = "|".join(
            str(row.get(field) or "")
            for field in ("market_id", "case_key", "case_id", "dispatch_id")
        )
        duplicate_keys[key] = duplicate_keys.get(key, 0) + 1
    duplicate_prediction_keys = {
        key: count for key, count in duplicate_keys.items() if count > 1
    }
    non_scae_decisions = [
        row["forecast_decision_id"]
        for row in decisions
        if row.get("probability_source") != SCAE_PROBABILITY_SOURCE
    ]
    non_scae_predictions = [
        row["id"]
        for row in matched_predictions
        if row.get("metadata", {}).get("scoreable_prediction_source") != SCAE_MARKET_PREDICTION_SOURCE
    ]
    non_scoreable_prediction_ids = []
    decision_by_id = {row["forecast_decision_id"]: row for row in decisions}
    for row in matched_predictions:
        decision = decision_by_id.get(row.get("metadata", {}).get("forecast_decision_id"))
        if decision and not bool(decision.get("scoreable_forecast_output")):
            non_scoreable_prediction_ids.append(row["id"])
    return {
        "expected_cases": expected_cases,
        "expected_forecast_decision_records": expected_forecast_decision_records,
        "expected_market_predictions": expected_market_predictions,
        "protected_count_deltas": deltas,
        "delta_source": delta_source,
        "forecast_decision_records_delta": forecast_delta,
        "market_predictions_delta": prediction_delta,
        "forecast_decision_records_for_run": len(decisions),
        "market_predictions_for_run_decisions": len(matched_predictions),
        "duplicate_prediction_keys": duplicate_prediction_keys,
        "non_scae_decision_ids": non_scae_decisions,
        "non_scae_prediction_ids": non_scae_predictions,
        "non_scoreable_prediction_ids": non_scoreable_prediction_ids,
        "decision_status_counts": _counts(row.get("production_persistence_status") for row in decisions),
        "non_scoreable_reason_counts": _counts(row.get("non_scoreable_reason_code") for row in decisions),
    }


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value or "none")
        result[key] = result.get(key, 0) + 1
    return result


def _amrg_reports(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    qdt_payloads = [
        _load_manifest_payload(item)
        for item in manifests
        if item.get("artifact_type") == "question-decomposition"
    ]
    qdt_payload = next((payload for payload in qdt_payloads if isinstance(payload, dict)), None)
    reports = []
    for manifest in manifests:
        if manifest.get("artifact_type") not in {"related-live-market-context", "no-related-context-waiver"}:
            continue
        payload = _load_manifest_payload(manifest)
        if not isinstance(payload, dict):
            reports.append({"artifact_id": manifest.get("artifact_id"), "ok": False, "error": "payload_unreadable"})
            continue
        try:
            report = build_amrg_operator_report(payload, question_decomposition=qdt_payload)
            reports.append({"artifact_id": manifest.get("artifact_id"), "ok": True, "report": report})
        except Exception as exc:
            reports.append({"artifact_id": manifest.get("artifact_id"), "ok": False, "error": str(exc)})
    return reports


def _calibration_report(
    db_path: Path,
    *,
    first100_trace_complete: bool,
    trace_manifest_count: int | None,
    tail_slice_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    regime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    protected_component_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    pointer_stability_evidence: dict[str, Any] | None,
    prediction_source: str | None,
    prediction_label: str | None,
    evaluation_cluster_id: str,
) -> dict[str, Any]:
    return build_calibration_debt_clearance_report(
        db_path=db_path,
        first100_trace_complete=first100_trace_complete,
        trace_manifest_count=trace_manifest_count,
        tail_slice_diagnostics=tail_slice_diagnostics,
        regime_diagnostics=regime_diagnostics,
        protected_component_diagnostics=protected_component_diagnostics,
        pointer_stability_evidence=pointer_stability_evidence,
        prediction_source=prediction_source,
        prediction_label=prediction_label,
        evaluation_cluster_id=evaluation_cluster_id,
    )


def _criterion(gate: str, ok: bool, *, required: bool = True, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    status = "passed" if ok else ("failed" if required else "skipped")
    return {
        "gate": gate,
        "required": required,
        "status": status,
        "ok": bool(ok or not required),
        "detail": detail or {},
    }


def _first_failing_gate(criteria: list[dict[str, Any]]) -> str | None:
    for item in criteria:
        if item.get("required") and not item.get("ok"):
            return str(item.get("gate"))
    return None


def _build_runtime_criteria(
    *,
    require_qdt_model_executed: bool,
    require_researcher_model_executed: bool,
    require_scoreable_prediction: bool,
    qdt_evidence: dict[str, Any],
    retrieval_evidence: dict[str, Any],
    researcher_evidence: dict[str, Any],
    scae_evidence: dict[str, Any],
    prediction_deltas: dict[str, Any],
    active: dict[str, int],
    handoff_report: dict[str, Any],
    errors: dict[str, Any],
) -> list[dict[str, Any]]:
    researcher_required = bool(
        require_researcher_model_executed or retrieval_evidence.get("classification_dispatch_allowed")
    )
    expected_market_predictions = prediction_deltas.get("expected_market_predictions")
    non_executing_expected = expected_market_predictions == 0 and not require_scoreable_prediction
    return [
        _criterion(
            "qdt_model_executed",
            bool(qdt_evidence.get("ok")),
            required=require_qdt_model_executed,
            detail={
                "qdt_model_executed_count": qdt_evidence.get("qdt_model_executed_count", 0),
                "runtime_call_model_executed_count": qdt_evidence.get("runtime_call_model_executed_count", 0),
            },
        ),
        _criterion(
            "retrieval_source_populated_or_structural_unanswerability",
            bool(retrieval_evidence.get("ok")),
            detail={
                "retrieval_packet_count": retrieval_evidence.get("retrieval_packet_count", 0),
                "source_populated_count": retrieval_evidence.get("source_populated_count", 0),
                "external_source_discovery_proven_count": retrieval_evidence.get(
                    "external_source_discovery_proven_count",
                    0,
                ),
                "structured_market_metadata_pilot_packet_count": retrieval_evidence.get(
                    "structured_market_metadata_pilot_packet_count",
                    0,
                ),
            },
        ),
        _criterion(
            "researcher_model_executed_if_dispatch_allowed",
            bool(researcher_evidence.get("ok")),
            required=researcher_required,
            detail={
                "classification_dispatch_allowed": bool(retrieval_evidence.get("classification_dispatch_allowed")),
                "model_executed_count": researcher_evidence.get("model_executed_count", 0),
                "runtime_bundle_count": researcher_evidence.get("runtime_bundle_count", 0),
            },
        ),
        _criterion(
            "scae_delta_refs_if_valid_forecast",
            bool(scae_evidence.get("ok")),
            detail={
                "valid_forecast_count": scae_evidence.get("valid_forecast_count", 0),
                "delta_ref_count": scae_evidence.get("delta_ref_count", 0),
            },
        ),
        _criterion(
            "no_scoreable_prediction_in_non_executing_mode",
            prediction_deltas.get("market_predictions_delta") == 0,
            required=non_executing_expected,
            detail={
                "expected_market_predictions": expected_market_predictions,
                "market_predictions_delta": prediction_deltas.get("market_predictions_delta"),
            },
        ),
        _criterion(
            "clean_drain",
            not active.get("active_runs") and not active.get("active_leases"),
            detail=dict(active),
        ),
        _criterion(
            "manifest_handoffs_resolved",
            bool(handoff_report.get("ok")),
            detail={
                "unresolved_output_manifest_refs": handoff_report.get("unresolved_output_manifest_refs", []),
            },
        ),
        _criterion(
            "stage_errors_allowed",
            int(errors.get("unexpected_count") or 0) == 0,
            detail={
                "unexpected_count": errors.get("unexpected_count", 0),
                "allowed_failure_classes": errors.get("allowed_failure_classes", []),
            },
        ),
    ]


def build_real_runtime_canary_report(
    db_path: Path | str,
    *,
    canary_result: dict[str, Any] | None = None,
    pipeline_run_id: str | None = None,
    expected_cases: int | None = None,
    expected_forecast_decision_records: int | None = None,
    expected_market_predictions: int | None = None,
    require_qdt_model_executed: bool = True,
    require_researcher_model_executed: bool = False,
    require_scoreable_prediction: bool = False,
    allowed_stage_failure_classes: list[str] | tuple[str, ...] | None = None,
    enforce_pipeline_disabled: bool = True,
    wal_warning_bytes: int = DEFAULT_WAL_WARNING_BYTES,
    wal_block_bytes: int = DEFAULT_WAL_BLOCK_BYTES,
    case_wall_time_warning_seconds: int = DEFAULT_CASE_WARNING_SECONDS,
    case_wall_time_block_seconds: int = DEFAULT_CASE_BLOCK_SECONDS,
    storage_retention_days: int = 90,
    prediction_source: str | None = "ads_pipeline",
    prediction_label: str | None = "v2_scae",
    evaluation_cluster_id: str = "calibration-debt-clearance",
    first100_trace_complete: bool = False,
    trace_manifest_count: int | None = None,
    tail_slice_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    regime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    protected_component_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    pointer_stability_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    expected_cases = expected_cases if expected_cases is not None else _expected_cases_from_result(canary_result)
    if expected_forecast_decision_records is None and expected_cases is not None:
        expected_forecast_decision_records = expected_cases
    if expected_market_predictions is None and expected_cases is not None:
        expected_market_predictions = expected_cases if require_scoreable_prediction else 0
    allowed_failure_classes = tuple(allowed_stage_failure_classes or ())
    resolved_run_id = pipeline_run_id or _pipeline_run_id_from_result(canary_result)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        ensure_pipeline_runner_schema(conn)
        ensure_stage_logging_schema(conn)
        if resolved_run_id is None:
            resolved_run_id = _latest_run_id(conn)
        run = _run_row(conn, resolved_run_id)
        active = _active_work_counts(conn)
        control = read_pipeline_control_state(conn)
        errors = _stage_error_events(conn, resolved_run_id, allowed_failure_classes=allowed_failure_classes)
        prediction_deltas = _prediction_delta_evidence(
            conn,
            pipeline_run_id=resolved_run_id,
            canary_result=canary_result,
            expected_cases=expected_cases,
            expected_forecast_decision_records=expected_forecast_decision_records,
            expected_market_predictions=expected_market_predictions,
        )
    finally:
        conn.close()

    handoff_report = build_handoff_report(path, pipeline_run_id=resolved_run_id) if resolved_run_id else {"ok": False, "error": "no_pipeline_run_id"}
    manifests = _manifest_items(handoff_report)
    qdt_evidence = _model_runtime_evidence(manifests)
    retrieval_evidence = _retrieval_runtime_evidence(manifests)
    researcher_evidence = _researcher_runtime_evidence(manifests)
    scae_evidence = _scae_runtime_evidence(manifests)
    storage = build_storage_maintenance_plan(path, retention_days=storage_retention_days)
    scoring = brier_score_report(path, prediction_source=prediction_source, prediction_label=prediction_label, evaluation_cluster_id=evaluation_cluster_id)
    calibration = _calibration_report(
        path,
        first100_trace_complete=first100_trace_complete,
        trace_manifest_count=trace_manifest_count,
        tail_slice_diagnostics=tail_slice_diagnostics,
        regime_diagnostics=regime_diagnostics,
        protected_component_diagnostics=protected_component_diagnostics,
        pointer_stability_evidence=pointer_stability_evidence,
        prediction_source=prediction_source,
        prediction_label=prediction_label,
        evaluation_cluster_id=evaluation_cluster_id,
    )
    run_duration = _run_duration_seconds(run)
    issues: list[str] = []
    warnings: list[str] = []
    if canary_result and canary_result.get("ok") is False:
        issues.append("canary_result_not_ok")
    if active["active_runs"]:
        issues.append("active_ads_pipeline_runs")
    if active["active_leases"]:
        issues.append("active_ads_case_leases")
    if enforce_pipeline_disabled and control.get("pipeline_enabled"):
        issues.append("pipeline_control_enabled_after_canary")
    if not handoff_report.get("ok"):
        issues.append("handoff_report_not_ok")
    if errors["unexpected_count"]:
        issues.append("unexpected_stage_error_events")
    if require_qdt_model_executed and not qdt_evidence["ok"]:
        issues.append("qdt_model_runtime_not_verified")
    if not retrieval_evidence["ok"]:
        issues.append("retrieval_runtime_not_source_populated_or_structurally_unanswerable")
    if (
        require_researcher_model_executed or retrieval_evidence["classification_dispatch_allowed"]
    ) and not researcher_evidence["ok"]:
        issues.append("researcher_model_runtime_not_verified")
    if not scae_evidence["ok"]:
        issues.append("scae_valid_forecast_missing_evidence_delta_refs")
    _check_prediction_deltas(prediction_deltas, issues)
    _check_resource_gates(
        storage,
        run_duration,
        issues,
        warnings,
        wal_warning_bytes=wal_warning_bytes,
        wal_block_bytes=wal_block_bytes,
        case_wall_time_warning_seconds=case_wall_time_warning_seconds,
        case_wall_time_block_seconds=case_wall_time_block_seconds,
    )
    runtime_criteria = _build_runtime_criteria(
        require_qdt_model_executed=require_qdt_model_executed,
        require_researcher_model_executed=require_researcher_model_executed,
        require_scoreable_prediction=require_scoreable_prediction,
        qdt_evidence=qdt_evidence,
        retrieval_evidence=retrieval_evidence,
        researcher_evidence=researcher_evidence,
        scae_evidence=scae_evidence,
        prediction_deltas=prediction_deltas,
        active=active,
        handoff_report=handoff_report,
        errors=errors,
    )
    first_failing_gate = _first_failing_gate(runtime_criteria)
    criteria_summary = {
        "first_failing_gate": first_failing_gate,
        "passed_count": sum(1 for item in runtime_criteria if item.get("status") == "passed"),
        "failed_count": sum(1 for item in runtime_criteria if item.get("status") == "failed"),
        "skipped_count": sum(1 for item in runtime_criteria if item.get("status") == "skipped"),
        "gate_order": [str(item.get("gate")) for item in runtime_criteria],
    }
    return {
        "schema_version": REAL_RUNTIME_CANARY_REPORT_SCHEMA_VERSION,
        "criteria_schema_version": REAL_RUNTIME_CANARY_CRITERIA_SCHEMA_VERSION,
        "ok": not issues,
        "issues": issues,
        "first_failing_gate": first_failing_gate,
        "warnings": warnings,
        "db_path": str(path),
        "pipeline_run_id": resolved_run_id,
        "criteria": {
            "expected_cases": expected_cases,
            "expected_forecast_decision_records": expected_forecast_decision_records,
            "expected_market_predictions": expected_market_predictions,
            "require_qdt_model_executed": require_qdt_model_executed,
            "require_researcher_model_executed": require_researcher_model_executed,
            "require_scoreable_prediction": require_scoreable_prediction,
            "allowed_stage_failure_classes": list(allowed_failure_classes),
            "wal_warning_bytes": wal_warning_bytes,
            "wal_block_bytes": wal_block_bytes,
            "case_wall_time_warning_seconds": case_wall_time_warning_seconds,
            "case_wall_time_block_seconds": case_wall_time_block_seconds,
            "runtime_gates": runtime_criteria,
            "first_failing_gate": first_failing_gate,
            "summary": criteria_summary,
        },
        "run": run,
        "run_duration_seconds": run_duration,
        "active_work": active,
        "pipeline_control": control,
        "stage_error_events": errors,
        "handoff_report": handoff_report,
        "amrg_reports": _amrg_reports(manifests),
        "model_runtime_evidence": qdt_evidence,
        "retrieval_runtime_evidence": retrieval_evidence,
        "researcher_runtime_evidence": researcher_evidence,
        "scae_runtime_evidence": scae_evidence,
        "prediction_delta_evidence": prediction_deltas,
        "storage_maintenance_plan": storage,
        "brier_score_report": scoring,
        "calibration_debt_report": calibration,
    }


def _expected_cases_from_result(canary_result: dict[str, Any] | None) -> int | None:
    if not canary_result:
        return None
    result = canary_result.get("result")
    if not isinstance(result, dict):
        return None
    return 1 if result.get("case_lease_id") else None


def _pipeline_run_id_from_result(canary_result: dict[str, Any] | None) -> str | None:
    if not canary_result:
        return None
    result = canary_result.get("result")
    if isinstance(result, dict) and result.get("pipeline_run_id"):
        return str(result["pipeline_run_id"])
    return None


def _check_prediction_deltas(evidence: dict[str, Any], issues: list[str]) -> None:
    expected_forecast = evidence.get("expected_forecast_decision_records")
    expected_predictions = evidence.get("expected_market_predictions")
    if (
        expected_forecast is not None
        and evidence.get("forecast_decision_records_delta") != expected_forecast
    ):
        issues.append("forecast_decision_record_delta_mismatch")
    if (
        expected_predictions is not None
        and evidence.get("market_predictions_delta") != expected_predictions
    ):
        issues.append("market_prediction_delta_mismatch")
    if evidence.get("duplicate_prediction_keys"):
        issues.append("duplicate_market_predictions_for_case")
    if evidence.get("non_scae_decision_ids"):
        issues.append("non_scae_forecast_decision_authority")
    if evidence.get("non_scae_prediction_ids"):
        issues.append("non_scae_market_prediction_authority")
    scoreable_predictions_expected = expected_predictions not in (None, 0)
    if evidence.get("non_scoreable_prediction_ids") and not scoreable_predictions_expected:
        issues.append("non_scoreable_decision_wrote_market_prediction")


def _check_resource_gates(
    storage: dict[str, Any],
    run_duration: float | None,
    issues: list[str],
    warnings: list[str],
    *,
    wal_warning_bytes: int,
    wal_block_bytes: int,
    case_wall_time_warning_seconds: int,
    case_wall_time_block_seconds: int,
) -> None:
    wal_size = int(storage.get("wal_size_bytes") or 0)
    if wal_size > wal_block_bytes:
        issues.append("db_wal_growth_block_threshold_exceeded")
    elif wal_size > wal_warning_bytes:
        warnings.append("db_wal_growth_warning_threshold_exceeded")
    if run_duration is None:
        return
    if run_duration > case_wall_time_block_seconds:
        issues.append("case_wall_time_block_threshold_exceeded")
    elif run_duration > case_wall_time_warning_seconds:
        warnings.append("case_wall_time_warning_threshold_exceeded")


__all__ = [
    "REAL_RUNTIME_CANARY_CRITERIA_SCHEMA_VERSION",
    "REAL_RUNTIME_CANARY_REPORT_SCHEMA_VERSION",
    "build_real_runtime_canary_report",
]
