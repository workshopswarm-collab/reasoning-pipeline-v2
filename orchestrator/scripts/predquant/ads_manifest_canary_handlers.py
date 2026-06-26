"""Manifest-backed ADS canary handlers.

This factory is intentionally a bounded handoff canary, not a production
specialist implementation. Unlike the older scoreable canary, every downstream
stage returns persisted `case_artifact_manifest` IDs so the runner can exercise
strict manifest handoff enforcement end to end.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from predquant.ads_case_contract import CaseContractPolicy, materialize_ads_case_contract
from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    build_validation_result,
    canonical_json,
    write_artifact_manifest,
)
from predquant.ads_handoff_resolver import (
    ManifestRequirement,
    load_manifest_payload,
    resolve_artifact_manifest,
    resolve_stage_output_manifest,
)
from predquant.ads_pipeline_runner import ADS_PIPELINE_STAGE_ORDER, StageHandlerResult
from predquant.ads_scoreable_canary_handlers import _decision_handler as _scoreable_decision_handler
from predquant.amrg import materialize_related_live_market_context
from predquant.evidence_packet import materialize_evidence_packet_v2
from predquant.tuning_profile import materialize_effective_profile_context
from predquant.ads_pipeline_runner import utc_now_iso


GENERIC_HANDOFF_SCHEMA_VERSION = "ads-stage-handoff-artifact/v1"
GENERIC_HANDOFF_VALIDATOR_VERSION = "ads-manifest-canary-stage/v1"
HANDLER_SCOPE = "manifest_backed_operational_canary"

STAGE_ARTIFACT_TYPES = {
    "decomposition": "question-decomposition-handoff-canary",
    "retrieval": "retrieval-packet-handoff-canary",
    "researcher_classification": "researcher-classification-handoff-canary",
    "classification_verification": "classification-verification-handoff-canary",
    "scae": "scae-ledger-handoff-canary",
    "synthesis": "synthesis-annotation-handoff-canary",
    "decision": "decision-gate-handoff-canary",
    "training_trace": "training-trace-handoff-canary",
    "replay_record": "replay-record-handoff-canary",
}

PREVIOUS_STAGE = {
    stage: ADS_PIPELINE_STAGE_ORDER[idx - 1]
    for idx, stage in enumerate(ADS_PIPELINE_STAGE_ORDER)
    if idx > 1
}


def _stage_artifact_dir(base_dir: Path, context: Any, lease: dict[str, Any]) -> Path:
    return base_dir / str(context.pipeline_run_id) / str(lease["case_id"])


def _forecast_timestamp(configured: str | None, lease: dict[str, Any]) -> str:
    return configured or lease.get("forecast_timestamp") or lease.get("selected_snapshot_observed_at") or utc_now_iso()


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    return path


def _validation_ref(conn: sqlite3.Connection, manifest: dict[str, Any]) -> str:
    validation = build_validation_result(
        artifact_id=manifest["artifact_id"],
        status="valid",
        validator_version=GENERIC_HANDOFF_VALIDATOR_VERSION,
        reason_codes=["manifest_canary_payload_written", "upstream_manifest_refs_validated"],
        validation_messages=["manifest-backed canary stage payload materialized"],
        metadata={"handler_scope": HANDLER_SCOPE, "stage": manifest["stage"]},
    )
    write_artifact_manifest(conn, manifest, validation_results=[validation])
    return validation["validation_result_id"]


def _write_generic_stage_artifact(
    conn: sqlite3.Connection,
    *,
    context: Any,
    lease: dict[str, Any],
    artifact_dir: Path,
    stage: str,
    input_manifest_ids: list[str],
    forecast_timestamp: str | None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    forecast_at = _forecast_timestamp(forecast_timestamp, lease)
    payload = {
        "artifact_type": STAGE_ARTIFACT_TYPES[stage],
        "schema_version": GENERIC_HANDOFF_SCHEMA_VERSION,
        "case_id": lease["case_id"],
        "case_key": lease["case_key"],
        "dispatch_id": lease["dispatch_id"],
        "stage": stage,
        "pipeline_run_id": context.pipeline_run_id,
        "forecast_timestamp": forecast_at,
        "source_cutoff_timestamp": lease["selected_snapshot_observed_at"],
        "input_manifest_ids": input_manifest_ids,
        "handoff_contract_status": "manifest_validated",
        "handler_scope": HANDLER_SCOPE,
        "metadata": metadata or {},
    }
    path = _write_json(artifact_dir / f"{stage}.json", payload)
    manifest = build_artifact_manifest(
        context=ArtifactManifestContext(
            case_id=lease["case_id"],
            case_key=lease["case_key"],
            dispatch_id=lease["dispatch_id"],
            stage=stage,
            producer="orchestrator-manifest-canary",
            forecast_timestamp=forecast_at,
            source_cutoff_timestamp=lease["selected_snapshot_observed_at"],
            pipeline_run_id=context.pipeline_run_id,
        ),
        artifact_type=STAGE_ARTIFACT_TYPES[stage],
        artifact_schema_version=GENERIC_HANDOFF_SCHEMA_VERSION,
        path=path,
        input_manifest_ids=input_manifest_ids,
        validation_status="valid",
        validator_version=GENERIC_HANDOFF_VALIDATOR_VERSION,
        temporal_isolation_status="pass",
        metadata={"handler_scope": HANDLER_SCOPE, "stage": stage, **(metadata or {})},
    )
    validation_id = _validation_ref(conn, manifest)
    resolved = resolve_artifact_manifest(conn, manifest["artifact_id"])
    return manifest["artifact_id"], validation_id, resolved


def _fetch_snapshot(conn: sqlite3.Connection, lease: dict[str, Any]) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM market_snapshots WHERE id = ? AND market_id = ?",
        (lease["selected_snapshot_id"], lease["market_id"]),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"missing selected snapshot row {lease['selected_snapshot_id']}")
    return row


def _active_market_index(conn: sqlite3.Connection, selected_market_id: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, platform, external_market_id, slug, title, description,
               category, status, outcome_type, closes_at, resolves_at,
               current_price, metadata
        FROM markets
        WHERE status = 'open' AND id != ?
        ORDER BY id
        LIMIT 50
        """,
        (selected_market_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _result(
    stage: str,
    artifact_id: str,
    validation_id: str | None,
    lease: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return StageHandlerResult(
        output_artifact_refs=(artifact_id,),
        validation_result_refs=(validation_id,) if validation_id else (),
        safe_metadata={
            "stage": stage,
            "handler_scope": HANDLER_SCOPE,
            "case_id": lease["case_id"],
            **metadata,
        },
    ).to_record(stage)


def build_stage_handlers(
    *,
    db_path: Path | str | None = None,
    runner_mode: str = "fixture",
    forecast_timestamp: str | None = None,
    max_cases: int = 1,
    metadata: dict[str, Any] | None = None,
    artifact_dir: Path | str | None = None,
    persist_scoreable_prediction: bool = True,
) -> dict[str, Callable[..., Any]]:
    if artifact_dir:
        base_dir = Path(artifact_dir).expanduser().resolve()
    else:
        db_parent = Path(db_path or ".").expanduser().resolve().parent
        base_dir = db_parent / "ads_artifacts" / "manifest_canary"
    ordinal_state = {"value": 0}
    factory_metadata = {
        "handler_factory": "predquant.ads_manifest_canary_handlers",
        "runner_mode": runner_mode,
        "max_cases": max_cases,
        **(metadata or {}),
    }

    def evidence_packet(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_dir = _stage_artifact_dir(base_dir, context, lease)
        contract_result = materialize_ads_case_contract(
            conn,
            market_id=lease["market_id"],
            forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
            artifact_dir=stage_dir,
            policy=CaseContractPolicy(),
        )
        snapshot = _fetch_snapshot(conn, lease)
        evidence_result = materialize_evidence_packet_v2(
            conn,
            case_contract=contract_result["contract"],
            case_contract_ref=contract_result["artifact_id"],
            market_snapshot=snapshot,
            artifact_dir=stage_dir,
        )
        resolve_artifact_manifest(
            conn,
            evidence_result["artifact_id"],
            ManifestRequirement(
                role="evidence_packet",
                artifact_type="evidence-packet-v2",
                artifact_schema_version="evidence-packet/v2",
                stage="evidence_packet",
            ),
        )
        return _result(
            "evidence_packet",
            evidence_result["artifact_id"],
            "",
            lease,
            {
                **factory_metadata,
                "case_contract_artifact_id": contract_result["artifact_id"],
            },
        )

    def policy_context(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        evidence_manifest = resolve_stage_output_manifest(conn, stage_outputs, "evidence_packet")
        evidence_payload = load_manifest_payload(evidence_manifest)
        profile_result = materialize_effective_profile_context(
            conn,
            evidence_packet=evidence_payload,
            evidence_packet_ref=evidence_manifest["artifact_id"],
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
        )
        return _result(
            "policy_context",
            profile_result["artifact_id"],
            "",
            lease,
            {**factory_metadata, "evidence_packet_ref": evidence_manifest["artifact_id"]},
        )

    def related_market_context(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        evidence_manifest = resolve_stage_output_manifest(conn, stage_outputs, "evidence_packet")
        profile_manifest = resolve_stage_output_manifest(conn, stage_outputs, "policy_context")
        related_result = materialize_related_live_market_context(
            conn,
            evidence_packet=load_manifest_payload(evidence_manifest),
            evidence_packet_ref=evidence_manifest["artifact_id"],
            profile_context_ref=profile_manifest["artifact_id"],
            active_market_index=_active_market_index(conn, lease["market_id"]),
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
        )
        return _result(
            "related_market_context",
            related_result["artifact_id"],
            "",
            lease,
            {
                **factory_metadata,
                "evidence_packet_ref": evidence_manifest["artifact_id"],
                "profile_context_ref": profile_manifest["artifact_id"],
            },
        )

    def generic(stage: str) -> Callable[..., dict[str, Any]]:
        def handler(**kwargs: Any) -> dict[str, Any]:
            conn = kwargs["conn"]
            context = kwargs["context"]
            lease = kwargs["lease"]
            stage_outputs = kwargs["stage_outputs"]
            previous = PREVIOUS_STAGE.get(stage)
            input_manifest_ids: list[str] = []
            if previous:
                previous_manifest = resolve_stage_output_manifest(conn, stage_outputs, previous)
                input_manifest_ids.append(previous_manifest["artifact_id"])
            artifact_id, validation_id, _manifest = _write_generic_stage_artifact(
                conn,
                context=context,
                lease=lease,
                artifact_dir=_stage_artifact_dir(base_dir, context, lease),
                stage=stage,
                input_manifest_ids=input_manifest_ids,
                forecast_timestamp=forecast_timestamp,
                metadata=factory_metadata,
            )
            result = _result(stage, artifact_id, validation_id, lease, dict(factory_metadata))
            if stage == "decision" and persist_scoreable_prediction:
                decision_result = _scoreable_decision_handler(
                    db_path=Path(db_path) if db_path else Path(":memory:"),
                    configured_forecast_timestamp=forecast_timestamp,
                    metadata=factory_metadata,
                    ordinal_state=ordinal_state,
                    conn=conn,
                    context=context,
                    lease=lease,
                    stage_outputs=stage_outputs,
                )
                result.update(
                    {
                        "forecast_decision_record_id": decision_result.get("forecast_decision_record_id"),
                        "forecast_decision_record_ref": decision_result.get("forecast_decision_record_ref"),
                        "forecast_artifact_id": decision_result.get("forecast_artifact_id"),
                        "market_prediction_id": decision_result.get("market_prediction_id"),
                    }
                )
                result["safe_metadata"] = {
                    **result["safe_metadata"],
                    "scoreable_bridge": decision_result.get("safe_metadata", {}),
                }
            return result

        return handler

    handlers: dict[str, Callable[..., Any]] = {
        "evidence_packet": evidence_packet,
        "policy_context": policy_context,
        "related_market_context": related_market_context,
    }
    for stage in ADS_PIPELINE_STAGE_ORDER[4:]:
        handlers[stage] = generic(stage)
    return handlers


__all__ = ["build_stage_handlers"]
