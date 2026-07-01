"""Shared ADS stage-health vocabulary for operator-facing reports."""

from __future__ import annotations

from typing import Any


STAGE_HEALTH_SCHEMA_VERSION = "ads-stage-health/v1"
ATTEMPTED_AND_ACCEPTED = "attempted_and_accepted"
ATTEMPTED_AND_FAILED = "attempted_and_failed"
ATTEMPTED_AND_NOT_CERTIFIED = "attempted_and_not_certified"
ATTEMPTED_AND_TIMED_OUT = "attempted_and_timed_out"
NOT_ATTEMPTED = "not_attempted"
NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK = "not_attempted_due_upstream_block"
BLOCKED_BY_UPSTREAM_QDT = "blocked_by_upstream_qdt"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _reason_for_blocker(stage: str | None) -> str | None:
    if stage == "decomposition":
        return BLOCKED_BY_UPSTREAM_QDT
    if stage:
        return f"blocked_by_upstream_{stage}"
    return None


def _is_readiness_block_manifest(manifest: dict[str, Any]) -> bool:
    artifact_type = str(manifest.get("artifact_type") or "").replace("-", "_")
    schema_version = str(
        manifest.get("artifact_schema_version") or manifest.get("schema_version") or ""
    ).replace("-", "_")
    return artifact_type.endswith("_readiness_block") or schema_version.endswith("_readiness_block/v1")


def stage_health_record(
    *,
    stage: str,
    health: str,
    attempted: bool,
    accepted_downstream: bool,
    blocked_by: str | None = None,
    reason_codes: list[str] | None = None,
    status: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": STAGE_HEALTH_SCHEMA_VERSION,
        "stage": stage,
        "health": health,
        "attempted": attempted,
        "accepted_downstream": accepted_downstream,
        "blocked_by": blocked_by,
        "reason_codes": [str(code) for code in (reason_codes or []) if code],
        "status": status,
        "detail": detail or {},
    }


def _latest_stage_rows(stages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in stages:
        stage = str(row.get("stage") or "")
        if stage:
            latest[stage] = row
    return latest


def build_stage_health_from_handoff(
    *,
    stage_order: list[str] | tuple[str, ...],
    stages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest = _latest_stage_rows(stages)
    records: list[dict[str, Any]] = []
    first_blocker: str | None = None
    for stage in stage_order:
        row = latest.get(stage)
        if row is None:
            if first_blocker:
                reason = _reason_for_blocker(first_blocker)
                records.append(
                    stage_health_record(
                        stage=stage,
                        health=NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK,
                        attempted=False,
                        accepted_downstream=False,
                        blocked_by=first_blocker,
                        reason_codes=[reason] if reason else [],
                    )
                )
            else:
                records.append(
                    stage_health_record(
                        stage=stage,
                        health=NOT_ATTEMPTED,
                        attempted=False,
                        accepted_downstream=False,
                    )
                )
            continue

        status = str(row.get("status") or "")
        manifests = [_as_dict(item) for item in _as_list(row.get("output_manifests"))]
        readiness_block = any(_is_readiness_block_manifest(manifest) for manifest in manifests)
        reason_codes = [
            str(code)
            for code in _as_list(row.get("reason_codes"))
            if isinstance(code, str) and code
        ]
        detail = {
            "output_manifest_count": len(manifests),
            "readiness_block": readiness_block,
            "stage_attempt_id": row.get("stage_attempt_id"),
        }
        if status == "failed":
            health = ATTEMPTED_AND_FAILED
            accepted = False
        elif any("timeout" in code for code in reason_codes):
            health = ATTEMPTED_AND_TIMED_OUT
            accepted = False
        elif readiness_block or status == "blocked":
            health = ATTEMPTED_AND_NOT_CERTIFIED
            accepted = False
        elif status == "complete":
            health = ATTEMPTED_AND_ACCEPTED
            accepted = True
        elif status in {"running", "waived", "terminal"}:
            health = ATTEMPTED_AND_NOT_CERTIFIED
            accepted = False
        else:
            health = NOT_ATTEMPTED
            accepted = False

        records.append(
            stage_health_record(
                stage=stage,
                health=health,
                attempted=health != NOT_ATTEMPTED,
                accepted_downstream=accepted,
                reason_codes=reason_codes,
                status=status,
                detail=detail,
            )
        )
        if health in {ATTEMPTED_AND_FAILED, ATTEMPTED_AND_TIMED_OUT, ATTEMPTED_AND_NOT_CERTIFIED} and first_blocker is None:
            first_blocker = stage
    return records


def _append_or_blocked(
    records: list[dict[str, Any]],
    *,
    stage: str,
    first_blocker: str | None,
    health: str,
    attempted: bool,
    accepted_downstream: bool,
    reason_codes: list[str] | None = None,
    detail: dict[str, Any] | None = None,
) -> str | None:
    if first_blocker:
        reason = _reason_for_blocker(first_blocker)
        records.append(
            stage_health_record(
                stage=stage,
                health=NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK,
                attempted=False,
                accepted_downstream=False,
                blocked_by=first_blocker,
                reason_codes=[reason] if reason else [],
                detail=detail,
            )
        )
        return first_blocker
    records.append(
        stage_health_record(
            stage=stage,
            health=health,
            attempted=attempted,
            accepted_downstream=accepted_downstream,
            reason_codes=reason_codes,
            detail=detail,
        )
    )
    if health in {ATTEMPTED_AND_FAILED, ATTEMPTED_AND_TIMED_OUT, ATTEMPTED_AND_NOT_CERTIFIED}:
        return stage
    return None


def build_stage_health_from_runtime_evidence(
    *,
    qdt_evidence: dict[str, Any],
    retrieval_evidence: dict[str, Any],
    researcher_evidence: dict[str, Any],
    verification_evidence: dict[str, Any] | None = None,
    scae_evidence: dict[str, Any] | None = None,
    prediction_deltas: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    qdt = _as_dict(qdt_evidence)
    retrieval = _as_dict(retrieval_evidence)
    researcher = _as_dict(researcher_evidence)
    verification = _as_dict(verification_evidence)
    scae = _as_dict(scae_evidence)
    deltas = _as_dict(prediction_deltas)
    records: list[dict[str, Any]] = []

    qdt_attempted = bool(
        _int_value(qdt.get("qdt_count"))
        or _int_value(qdt.get("runtime_call_count"))
        or _int_value(qdt.get("qdt_live_model_call_attempted_count"))
        or _int_value(qdt.get("qdt_live_model_call_executed_count"))
    )
    qdt_accepted = bool(qdt.get("ok") and qdt.get("qdt_end_to_end_quality_ok", qdt.get("ok")))
    if qdt_accepted:
        records.append(
            stage_health_record(
                stage="decomposition",
                health=ATTEMPTED_AND_ACCEPTED,
                attempted=True,
                accepted_downstream=True,
                detail={"qdt_runtime_state": qdt.get("qdt_runtime_state")},
            )
        )
        first_blocker = None
    elif qdt_attempted:
        qdt_reason = (
            "qdt_end_to_end_quality_not_verified"
            if qdt.get("ok")
            else "qdt_model_runtime_not_verified"
        )
        records.append(
            stage_health_record(
                stage="decomposition",
                health=ATTEMPTED_AND_FAILED,
                attempted=True,
                accepted_downstream=False,
                reason_codes=[qdt_reason],
                detail={"qdt_runtime_state": qdt.get("qdt_runtime_state")},
            )
        )
        first_blocker = "decomposition"
    else:
        records.append(
            stage_health_record(
                stage="decomposition",
                health=NOT_ATTEMPTED,
                attempted=False,
                accepted_downstream=False,
            )
        )
        first_blocker = "decomposition"

    retrieval_attempted = bool(
        _int_value(retrieval.get("retrieval_packet_count"))
        or _int_value(retrieval.get("real_candidate_count"))
        or _int_value(retrieval.get("search_call_count"))
        or _int_value(retrieval.get("retrieval_stage_timeout_count"))
    )
    if first_blocker and not retrieval_attempted:
        first_blocker = _append_or_blocked(
            records,
            stage="retrieval",
            first_blocker=first_blocker,
            health=NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK,
            attempted=False,
            accepted_downstream=False,
            detail={"retrieval_packet_count": _int_value(retrieval.get("retrieval_packet_count"))},
        )
    else:
        if _int_value(retrieval.get("retrieval_stage_timeout_count")):
            retrieval_health = ATTEMPTED_AND_TIMED_OUT
            retrieval_accepted = False
            retrieval_reasons = ["retrieval_stage_timeout"]
        elif retrieval.get("ok"):
            retrieval_health = ATTEMPTED_AND_ACCEPTED
            retrieval_accepted = True
            retrieval_reasons = []
        elif retrieval_attempted:
            retrieval_health = ATTEMPTED_AND_NOT_CERTIFIED
            retrieval_accepted = False
            retrieval_reasons = ["retrieval_not_certified"]
        else:
            retrieval_health = NOT_ATTEMPTED
            retrieval_accepted = False
            retrieval_reasons = []
        maybe_blocker = _append_or_blocked(
            records,
            stage="retrieval",
            first_blocker=None,
            health=retrieval_health,
            attempted=retrieval_attempted,
            accepted_downstream=retrieval_accepted,
            reason_codes=retrieval_reasons,
            detail={
                "retrieval_packet_count": _int_value(retrieval.get("retrieval_packet_count")),
                "retrieval_stage_timeout_count": _int_value(retrieval.get("retrieval_stage_timeout_count")),
            },
        )
        if first_blocker is None:
            first_blocker = maybe_blocker

    researcher_attempted = bool(
        _int_value(researcher.get("model_executed_count"))
        or _int_value(researcher.get("runtime_bundle_count"))
        or _int_value(researcher.get("classification_slice_count"))
    )
    researcher_health = ATTEMPTED_AND_ACCEPTED if researcher.get("ok") else ATTEMPTED_AND_FAILED if researcher_attempted else NOT_ATTEMPTED
    first_blocker = _append_or_blocked(
        records,
        stage="researcher_classification",
        first_blocker=first_blocker,
        health=researcher_health,
        attempted=researcher_attempted,
        accepted_downstream=bool(researcher.get("ok")),
        reason_codes=[] if researcher.get("ok") else ["researcher_model_runtime_not_verified"] if researcher_attempted else [],
        detail={
            "model_executed_count": _int_value(researcher.get("model_executed_count")),
            "runtime_bundle_count": _int_value(researcher.get("runtime_bundle_count")),
        },
    ) or first_blocker

    verification_attempted = bool(
        _int_value(verification.get("verification_artifact_count"))
        or _int_value(verification.get("reconciliation_slice_count"))
    )
    verification_health = (
        ATTEMPTED_AND_ACCEPTED
        if verification.get("ok")
        else ATTEMPTED_AND_NOT_CERTIFIED
        if verification_attempted
        else NOT_ATTEMPTED
    )
    first_blocker = _append_or_blocked(
        records,
        stage="classification_verification",
        first_blocker=first_blocker,
        health=verification_health,
        attempted=verification_attempted,
        accepted_downstream=bool(verification.get("ok")),
        reason_codes=["classification_verification_not_certified"] if verification_attempted and not verification.get("ok") else [],
    ) or first_blocker

    scae_attempted = bool(_int_value(scae.get("ledger_count")) or _int_value(scae.get("valid_forecast_count")))
    scae_health = (
        ATTEMPTED_AND_ACCEPTED
        if scae.get("ok")
        else ATTEMPTED_AND_NOT_CERTIFIED
        if scae_attempted
        else NOT_ATTEMPTED
    )
    first_blocker = _append_or_blocked(
        records,
        stage="scae",
        first_blocker=first_blocker,
        health=scae_health,
        attempted=scae_attempted,
        accepted_downstream=bool(scae.get("ok")),
        reason_codes=["scae_delta_refs_missing"] if scae_attempted and not scae.get("ok") else [],
        detail={
            "ledger_count": _int_value(scae.get("ledger_count")),
            "delta_ref_count": _int_value(scae.get("delta_ref_count")),
        },
    ) or first_blocker

    decision_attempted = bool(_int_value(deltas.get("forecast_decision_records_delta")))
    _append_or_blocked(
        records,
        stage="decision",
        first_blocker=first_blocker,
        health=ATTEMPTED_AND_ACCEPTED if decision_attempted else NOT_ATTEMPTED,
        attempted=decision_attempted,
        accepted_downstream=decision_attempted,
        detail={
            "forecast_decision_records_delta": _int_value(deltas.get("forecast_decision_records_delta")),
            "market_predictions_delta": _int_value(deltas.get("market_predictions_delta")),
        },
    )
    return records


def summarize_stage_health(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    first_blocker = None
    for record in records:
        health = str(record.get("health") or "unknown")
        counts[health] = counts.get(health, 0) + 1
        if first_blocker is None and health in {
            ATTEMPTED_AND_FAILED,
            ATTEMPTED_AND_TIMED_OUT,
            ATTEMPTED_AND_NOT_CERTIFIED,
        }:
            first_blocker = record.get("stage")
    return {
        "schema_version": "ads-stage-health-summary/v1",
        "counts_by_health": counts,
        "first_blocking_stage": first_blocker,
        "blocked_downstream_stage_count": counts.get(NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK, 0),
    }


__all__ = [
    "ATTEMPTED_AND_ACCEPTED",
    "ATTEMPTED_AND_FAILED",
    "ATTEMPTED_AND_NOT_CERTIFIED",
    "ATTEMPTED_AND_TIMED_OUT",
    "BLOCKED_BY_UPSTREAM_QDT",
    "NOT_ATTEMPTED",
    "NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK",
    "STAGE_HEALTH_SCHEMA_VERSION",
    "build_stage_health_from_handoff",
    "build_stage_health_from_runtime_evidence",
    "stage_health_record",
    "summarize_stage_health",
]
