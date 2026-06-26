"""Manifest-backed ADS production-readiness stage handlers.

These handlers exercise the real ADS handoff contracts and SCAE fail-closed
forecast path without claiming live research sufficiency. They are intended for
bounded cloned/live readiness runs before the external specialist adapters are
allowed to produce scoreable forecasts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
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
from predquant.ads_manifest_canary_handlers import _active_market_index
from predquant.ads_pipeline_runner import ADS_PIPELINE_STAGE_ORDER, StageHandlerResult, utc_now_iso
from predquant.amrg import materialize_related_live_market_context
from predquant.evidence_packet import materialize_evidence_packet_v2
from predquant.tuning_profile import materialize_effective_profile_context

REPO_ROOT = Path(__file__).resolve().parents[3]
DECOMPOSER_SCRIPTS = REPO_ROOT / "decomposer" / "scripts"
RESEARCHER_SCRIPTS = REPO_ROOT / "researcher-swarm" / "scripts"
SCAE_SCRIPTS = REPO_ROOT / "SCAE" / "scripts"
for script_dir in (DECOMPOSER_SCRIPTS, RESEARCHER_SCRIPTS, SCAE_SCRIPTS):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_HANDOFF_ARTIFACT_TYPE,
    DECOMPOSER_HANDOFF_SCHEMA_VERSION,
    build_decomposer_handoff,
)
from ads_decomposer.qdt import (  # noqa: E402
    QUESTION_DECOMPOSITION_ARTIFACT_TYPE,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
    build_fixture_qdt_candidate,
    dump_question_decomposition,
    select_qdt_candidate,
)
from researcher_swarm.retrieval import (  # noqa: E402
    RETRIEVAL_PACKET_MANIFEST_ARTIFACT_TYPE,
    RETRIEVAL_PACKET_SCHEMA_VERSION,
    build_retrieval_packet,
    dump_retrieval_packet,
    finalize_retrieval_packet_for_dispatch,
)
from scae.intervals import build_pre_debt_ledger_output  # noqa: E402
from scae.ledger import apply_research_sufficiency_guard, finalize_scae_probability_fields  # noqa: E402
from scae.persistence import write_scae_market_prediction  # noqa: E402
from scae.prior import build_prior_context  # noqa: E402


HANDLER_FACTORY_REF = "predquant.ads_production_readiness_handlers"
HANDLER_SCOPE = "production_readiness_fail_closed"
VALIDATOR_VERSION = "ads-production-readiness-handler/v1"
ARTIFACT_DIR_NAME = "production_readiness"

STAGE_ARTIFACT_TYPES = {
    "researcher_classification": "researcher-classification-readiness-block",
    "classification_verification": "classification-verification-readiness-block",
    "scae": "scae-final-probability-ledger",
    "synthesis": "synthesis-annotation",
    "decision": "decision-execution-gate",
    "training_trace": "training-trace-readiness-record",
    "replay_record": "replay-record-readiness-record",
}

STAGE_SCHEMA_VERSIONS = {
    "researcher_classification": "researcher-classification-readiness-block/v1",
    "classification_verification": "classification-verification-readiness-block/v1",
    "scae": "scae-final-probability-ledger/v1",
    "synthesis": "synthesis-annotation/v1",
    "decision": "decision-execution-gate/v1",
    "training_trace": "training-trace-readiness-record/v1",
    "replay_record": "replay-record-readiness-record/v1",
}

PREVIOUS_STAGE = {
    stage: ADS_PIPELINE_STAGE_ORDER[idx - 1]
    for idx, stage in enumerate(ADS_PIPELINE_STAGE_ORDER)
    if idx > 1
}


def _forecast_timestamp(configured: str | None, lease: dict[str, Any]) -> str:
    return configured or lease.get("forecast_timestamp") or lease.get("selected_snapshot_observed_at") or utc_now_iso()


def _stage_artifact_dir(base_dir: Path, context: Any, lease: dict[str, Any]) -> Path:
    return base_dir / str(context.pipeline_run_id) / str(lease["case_id"])


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    return path


def _write_payload_manifest(
    conn: sqlite3.Connection,
    *,
    context: Any,
    lease: dict[str, Any],
    artifact_dir: Path,
    stage: str,
    file_name: str,
    payload: dict[str, Any],
    artifact_type: str,
    artifact_schema_version: str,
    forecast_timestamp: str | None,
    input_manifest_ids: list[str],
    producer: str,
    reason_codes: list[str],
    metadata: dict[str, Any],
    temporal_isolation_status: str = "pass",
) -> tuple[dict[str, Any], str]:
    forecast_at = _forecast_timestamp(forecast_timestamp, lease)
    source_cutoff = lease["selected_snapshot_observed_at"]
    path = _write_json(artifact_dir / file_name, payload)
    manifest = build_artifact_manifest(
        context=ArtifactManifestContext(
            case_id=lease["case_id"],
            case_key=lease["case_key"],
            dispatch_id=lease["dispatch_id"],
            stage=stage,
            producer=producer,
            forecast_timestamp=forecast_at,
            source_cutoff_timestamp=source_cutoff,
            pipeline_run_id=context.pipeline_run_id,
        ),
        artifact_type=artifact_type,
        artifact_schema_version=artifact_schema_version,
        path=path,
        input_manifest_ids=input_manifest_ids,
        validation_status="valid",
        validator_version=VALIDATOR_VERSION,
        temporal_isolation_status=temporal_isolation_status,
        metadata={
            "handler_scope": HANDLER_SCOPE,
            "handler_factory": HANDLER_FACTORY_REF,
            "stage": stage,
            **metadata,
        },
    )
    validation = build_validation_result(
        artifact_id=manifest["artifact_id"],
        status="valid",
        validator_version=VALIDATOR_VERSION,
        reason_codes=reason_codes,
        validation_messages=["production-readiness artifact materialized"],
        metadata={"handler_scope": HANDLER_SCOPE, "stage": stage},
    )
    write_artifact_manifest(conn, manifest, validation_results=[validation])
    return resolve_artifact_manifest(conn, manifest["artifact_id"]), validation["validation_result_id"]


def _result(
    stage: str,
    artifact_ids: list[str],
    validation_ids: list[str],
    lease: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return StageHandlerResult(
        output_artifact_refs=tuple(artifact_ids),
        validation_result_refs=tuple(validation_ids),
        safe_metadata={
            "stage": stage,
            "handler_scope": HANDLER_SCOPE,
            "case_id": lease["case_id"],
            **metadata,
        },
    ).to_record(stage)


def _fetch_snapshot(conn: sqlite3.Connection, lease: dict[str, Any]) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM market_snapshots WHERE id = ? AND market_id = ?",
        (lease["selected_snapshot_id"], lease["market_id"]),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"missing selected snapshot row {lease['selected_snapshot_id']}")
    return row


def _selected_case_contract_manifest(
    conn: sqlite3.Connection,
    stage_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    evidence_output = stage_outputs.get("evidence_packet") or {}
    metadata = evidence_output.get("safe_metadata") or {}
    case_contract_ref = metadata.get("case_contract_artifact_id")
    if not isinstance(case_contract_ref, str) or not case_contract_ref:
        raise RuntimeError("evidence_packet output is missing case_contract_artifact_id")
    return resolve_artifact_manifest(
        conn,
        case_contract_ref,
        ManifestRequirement(
            role="ads_case_contract",
            artifact_type="ads-case-contract",
            artifact_schema_version="ads-case-contract/v1",
        ),
    )


def _blocked_reconciliation_rows(qdt: dict[str, Any], verification_manifest_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for leaf in qdt.get("required_leaf_questions", []):
        if not isinstance(leaf, dict) or not leaf.get("leaf_id"):
            continue
        leaf_id = str(leaf["leaf_id"])
        rows.append(
            {
                "artifact_type": "research_sufficiency_reconciliation_slice",
                "schema_version": "research-sufficiency-reconciliation-slice/v1",
                "research_sufficiency_reconciliation_id": (
                    f"research-sufficiency-reconciliation:production-readiness:{leaf_id}"
                ),
                "leaf_id": leaf_id,
                "research_sufficiency_reconciliation_status": "blocked_insufficient_research",
                "reconciled_status": "blocked_insufficient_research",
                "blocking_reason_codes": [
                    "live_retrieval_not_certified",
                    "classification_dispatch_blocked",
                    "verification_no_high_certainty_reconciliation",
                ],
                "reason_codes": ["production_readiness_fail_closed"],
                "research_sufficiency_certificate_ref": None,
                "retrieval_breadth_profile_ref": None,
                "retrieval_breadth_coverage_ref": None,
                "retrieval_breadth_certified": False,
                "required_escalation_decision_refs": [],
                "completed_escalation_decision_refs": [],
                "verification_manifest_ref": verification_manifest_id,
            }
        )
    return rows


def _case_probability_from_contract(case_contract: dict[str, Any]) -> float:
    baseline = case_contract.get("prediction_time_market_baseline")
    if not isinstance(baseline, dict):
        return 0.5
    value = baseline.get("market_probability")
    if isinstance(value, bool) or value is None:
        return 0.5
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return 0.5
    if 0.0 <= probability <= 1.0:
        return probability
    return 0.5


def _build_scae_ledger(
    *,
    lease: dict[str, Any],
    context: Any,
    case_contract: dict[str, Any],
    qdt: dict[str, Any],
    sufficiency_rows: list[dict[str, Any]],
    verification_manifest_id: str,
    forecast_timestamp: str,
) -> dict[str, Any]:
    contract_case_id = case_contract["case_id"]
    contract_case_key = case_contract["case_key"]
    contract_dispatch_id = case_contract["dispatch_id"]
    baseline = case_contract.get("prediction_time_market_baseline") or {}
    probability = _case_probability_from_contract(case_contract)
    prior_context = build_prior_context(
        market_prior={
            "source": "market_live_probability",
            "probability": probability,
            "valid": True,
        },
        prior_reliability_inputs={
            "reason_code_candidates": [{"code": "selected_snapshot_prior_only"}],
            "rolling_microstructure": {
                "market_snapshot_freshness": {"status": "fresh"},
                "market_priced_through_timestamp": baseline.get("source_fetched_at"),
                "bid_ask_spread_latest": baseline.get("bid_ask_spread"),
            },
            "quote_observation_refs": [
                {
                    "ref_id": str(case_contract.get("intake_source", {}).get("market_snapshot_id")),
                    "source": "prediction_time_market_baseline",
                }
            ],
        },
    )
    prior_context.update(
        {
            "case_id": contract_case_id,
            "case_key": contract_case_key,
            "dispatch_id": contract_dispatch_id,
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": forecast_timestamp,
            "prior_context_ref": f"scae-prior-context:production-readiness:{contract_case_id}",
        }
    )
    pre_debt = build_pre_debt_ledger_output(prior_context)
    pre_debt.update(
        {
            "case_key": contract_case_key,
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": forecast_timestamp,
            "verification_manifest_ref": verification_manifest_id,
            "adapter_mode": "prior_only_until_research_sufficiency_certified",
        }
    )
    guarded = apply_research_sufficiency_guard(
        pre_debt,
        qdt=qdt,
        sufficiency_reconciliations=sufficiency_rows,
    )
    finalized = finalize_scae_probability_fields(guarded)
    finalized.update(
        {
            "case_id": contract_case_id,
            "case_key": contract_case_key,
            "dispatch_id": contract_dispatch_id,
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": forecast_timestamp,
            "adapter_mode": "production_readiness_fail_closed",
            "scoreable_forecast_output": False,
            "market_prediction_write_expected": False,
        }
    )
    return finalized


def _build_synthesis_annotation(
    *,
    lease: dict[str, Any],
    context: Any,
    scae_ledger: dict[str, Any],
    scae_manifest: dict[str, Any],
    forecast_timestamp: str,
) -> dict[str, Any]:
    payload = {
        "artifact_type": "synthesis_annotation",
        "schema_version": STAGE_SCHEMA_VERSIONS["synthesis"],
        "case_id": scae_ledger["case_id"],
        "case_key": scae_ledger["case_key"],
        "dispatch_id": scae_ledger["dispatch_id"],
        "run_id": context.pipeline_run_id,
        "forecast_timestamp": forecast_timestamp,
        "scae_ledger_ref": scae_ledger["final_probability_ledger_id"],
        "scae_ledger_manifest_ref": scae_manifest["artifact_id"],
        "scae_ledger_digest": scae_ledger["final_probability_ledger_digest"],
        "forecast_validity_status": scae_ledger.get("forecast_validity_status"),
        "execution_authority_status": scae_ledger.get("execution_authority_status"),
        "synthesis_status": "blocked_by_research_sufficiency",
        "reason_codes": ["scae_forecast_invalid_for_production_readiness_run"],
        "writes_production_forecast": False,
        "writes_persistence": False,
    }
    payload["synthesis_annotation_ref"] = f"synthesis-annotation:production-readiness:{scae_ledger['case_id']}"
    payload["synthesis_annotation_digest"] = "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


def _build_decision_gate(
    *,
    lease: dict[str, Any],
    context: Any,
    scae_ledger: dict[str, Any],
    scae_manifest: dict[str, Any],
    synthesis: dict[str, Any],
    forecast_timestamp: str,
) -> dict[str, Any]:
    payload = {
        "artifact_type": "decision_execution_gate",
        "schema_version": STAGE_SCHEMA_VERSIONS["decision"],
        "feature_id": "DEC-001",
        "case_id": scae_ledger["case_id"],
        "case_key": scae_ledger["case_key"],
        "dispatch_id": scae_ledger["dispatch_id"],
        "run_id": context.pipeline_run_id,
        "forecast_timestamp": forecast_timestamp,
        "decision_gate_id": f"decision-gate:production-readiness:{scae_ledger['case_id']}",
        "probability_authority": False,
        "replacement_probability_authority": False,
        "synthesis_upgrade_authority": False,
        "persistence_authority": False,
        "market_prediction_authority": False,
        "scoring_authority": False,
        "calibration_debt_clearance_authority": False,
        "writes_production_forecast": False,
        "writes_persistence": False,
        "writes_market_prediction": False,
        "scoreable_forecast_output": False,
        "clears_calibration_debt": False,
        "forecast_validity_status": scae_ledger.get("forecast_validity_status"),
        "execution_authority_status": scae_ledger.get("execution_authority_status"),
        "actionability_status": "non_actionable",
        "scae_context": {
            "scae_ledger_ref": scae_ledger["final_probability_ledger_id"],
            "scae_ledger_digest": scae_ledger["final_probability_ledger_digest"],
            "scae_manifest_ref": scae_manifest["artifact_id"],
            "case_id": scae_ledger["case_id"],
            "case_key": scae_ledger["case_key"],
            "dispatch_id": scae_ledger["dispatch_id"],
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": forecast_timestamp,
            "forecast_validity_status": scae_ledger.get("forecast_validity_status"),
            "execution_authority_status": scae_ledger.get("execution_authority_status"),
        },
        "synthesis_context": {
            "synthesis_annotation_ref": synthesis["synthesis_annotation_ref"],
            "synthesis_annotation_digest": synthesis["synthesis_annotation_digest"],
        },
    }
    payload["decision_gate_digest"] = "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload


def build_stage_handlers(
    *,
    db_path: Path | str | None = None,
    runner_mode: str = "fixture",
    forecast_timestamp: str | None = None,
    max_cases: int = 1,
    metadata: dict[str, Any] | None = None,
    artifact_dir: Path | str | None = None,
) -> dict[str, Callable[..., Any]]:
    if artifact_dir:
        base_dir = Path(artifact_dir).expanduser().resolve()
    else:
        db_parent = Path(db_path or ".").expanduser().resolve().parent
        base_dir = db_parent / "ads_artifacts" / ARTIFACT_DIR_NAME
    db_file = Path(db_path) if db_path else Path(":memory:")
    factory_metadata = {
        "handler_factory": HANDLER_FACTORY_REF,
        "runner_mode": runner_mode,
        "max_cases": max_cases,
        "forecast_authority_policy": "scae_only",
        "scoreable_forecast_policy": "blocked_until_research_sufficiency_certified",
        **(metadata or {}),
    }

    def evidence_packet(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_dir = _stage_artifact_dir(base_dir, context, lease)
        forecast_at = _forecast_timestamp(forecast_timestamp, lease)
        contract_result = materialize_ads_case_contract(
            conn,
            market_id=lease["market_id"],
            forecast_timestamp=forecast_at,
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
        return _result(
            "evidence_packet",
            [evidence_result["artifact_id"]],
            [],
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
        profile_result = materialize_effective_profile_context(
            conn,
            evidence_packet=load_manifest_payload(evidence_manifest),
            evidence_packet_ref=evidence_manifest["artifact_id"],
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
        )
        return _result(
            "policy_context",
            [profile_result["artifact_id"]],
            [],
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
            [related_result["artifact_id"]],
            [],
            lease,
            {
                **factory_metadata,
                "evidence_packet_ref": evidence_manifest["artifact_id"],
                "profile_context_ref": profile_manifest["artifact_id"],
            },
        )

    def decomposition(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        stage_dir = _stage_artifact_dir(base_dir, context, lease)
        case_manifest = _selected_case_contract_manifest(conn, stage_outputs)
        evidence_manifest = resolve_stage_output_manifest(conn, stage_outputs, "evidence_packet")
        profile_manifest = resolve_stage_output_manifest(conn, stage_outputs, "policy_context")
        related_manifest = resolve_stage_output_manifest(conn, stage_outputs, "related_market_context")
        handoff = build_decomposer_handoff(
            ads_case_contract_manifest=case_manifest,
            evidence_packet_manifest=evidence_manifest,
            effective_profile_context_manifest=profile_manifest,
            related_market_context_manifest=related_manifest,
        )
        handoff_manifest, handoff_validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=stage_dir,
            stage="decomposition",
            file_name="decomposer-handoff.json",
            payload=handoff,
            artifact_type=DECOMPOSER_HANDOFF_ARTIFACT_TYPE.replace("_", "-"),
            artifact_schema_version=DECOMPOSER_HANDOFF_SCHEMA_VERSION,
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=list(handoff["input_manifest_ids"]),
            producer="decomposer-production-readiness-adapter",
            reason_codes=["decomposer_handoff_validated"],
            metadata=factory_metadata,
        )
        candidate = build_fixture_qdt_candidate(handoff)
        candidate["market_id"] = str(
            handoff.get("market_context", {}).get("market_id") or lease["market_id"]
        )
        qdt = select_qdt_candidate([candidate])
        qdt["adapter_mode"] = "deterministic_decomposer_contract_adapter"
        qdt["input_manifest_ids"] = [handoff_manifest["artifact_id"]]
        qdt_path = stage_dir / "question-decomposition.json"
        _write_json(qdt_path, json.loads(dump_question_decomposition(qdt)))
        qdt_manifest = build_artifact_manifest(
            context=ArtifactManifestContext(
                case_id=lease["case_id"],
                case_key=lease["case_key"],
                dispatch_id=lease["dispatch_id"],
                stage="decomposition",
                producer="decomposer-production-readiness-adapter",
                forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
                source_cutoff_timestamp=lease["selected_snapshot_observed_at"],
                pipeline_run_id=context.pipeline_run_id,
            ),
            artifact_type=QUESTION_DECOMPOSITION_ARTIFACT_TYPE.replace("_", "-"),
            artifact_schema_version=QUESTION_DECOMPOSITION_SCHEMA_VERSION,
            path=qdt_path,
            input_manifest_ids=[handoff_manifest["artifact_id"]],
            validation_status="valid",
            validator_version=VALIDATOR_VERSION,
            temporal_isolation_status="pass",
            metadata={
                "handler_scope": HANDLER_SCOPE,
                "handler_factory": HANDLER_FACTORY_REF,
                "adapter_mode": "deterministic_decomposer_contract_adapter",
            },
        )
        qdt_validation = build_validation_result(
            artifact_id=qdt_manifest["artifact_id"],
            status="valid",
            validator_version=VALIDATOR_VERSION,
            reason_codes=["question_decomposition_valid", "deterministic_contract_adapter"],
            validation_messages=["QDT selected from deterministic production-readiness adapter"],
            metadata={"handler_scope": HANDLER_SCOPE, "stage": "decomposition"},
        )
        write_artifact_manifest(conn, qdt_manifest, validation_results=[qdt_validation])
        qdt_manifest = resolve_artifact_manifest(conn, qdt_manifest["artifact_id"])
        return _result(
            "decomposition",
            [qdt_manifest["artifact_id"], handoff_manifest["artifact_id"]],
            [qdt_validation["validation_result_id"], handoff_validation_id],
            lease,
            {
                **factory_metadata,
                "qdt_adapter_mode": "deterministic_contract_adapter",
                "decomposer_handoff_ref": handoff_manifest["artifact_id"],
            },
        )

    def retrieval(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        stage_dir = _stage_artifact_dir(base_dir, context, lease)
        qdt_manifest = resolve_stage_output_manifest(conn, stage_outputs, "decomposition")
        evidence_manifest = resolve_stage_output_manifest(conn, stage_outputs, "evidence_packet")
        profile_manifest = resolve_stage_output_manifest(conn, stage_outputs, "policy_context")
        related_manifest = resolve_stage_output_manifest(conn, stage_outputs, "related_market_context")
        packet = build_retrieval_packet(
            load_manifest_payload(qdt_manifest),
            evidence_packet=load_manifest_payload(evidence_manifest),
            amrg_context=load_manifest_payload(related_manifest),
            question_decomposition_artifact_id=qdt_manifest["artifact_id"],
            policy_context_ref=profile_manifest["artifact_id"],
            forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
            source_cutoff_timestamp=lease["selected_snapshot_observed_at"],
            pre_dispatch_input_whitelist_refs=[
                qdt_manifest["artifact_id"],
                evidence_manifest["artifact_id"],
                profile_manifest["artifact_id"],
                related_manifest["artifact_id"],
            ],
            live_retrieval_allowlist=["browser", "native_gpt_research", "structured_feed"],
        )
        packet = finalize_retrieval_packet_for_dispatch(packet)
        packet["adapter_mode"] = "query_plan_only_until_live_retrieval_transport_returns_evidence"
        packet_manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=stage_dir,
            stage="retrieval",
            file_name="retrieval-packet.json",
            payload=json.loads(dump_retrieval_packet(packet)),
            artifact_type=RETRIEVAL_PACKET_MANIFEST_ARTIFACT_TYPE,
            artifact_schema_version=RETRIEVAL_PACKET_SCHEMA_VERSION,
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[
                qdt_manifest["artifact_id"],
                evidence_manifest["artifact_id"],
                profile_manifest["artifact_id"],
                related_manifest["artifact_id"],
            ],
            producer="researcher-swarm-production-readiness-adapter",
            reason_codes=["retrieval_packet_valid", "classification_dispatch_blocked_until_certified"],
            metadata=factory_metadata,
        )
        summary = packet.get("research_sufficiency_summary") or {}
        return _result(
            "retrieval",
            [packet_manifest["artifact_id"]],
            [validation_id],
            lease,
            {
                **factory_metadata,
                "classification_dispatch_status": summary.get("classification_dispatch_status"),
                "all_required_leaves_certified": bool(summary.get("all_required_leaves_certified")),
            },
        )

    def researcher_classification(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        retrieval_manifest = resolve_stage_output_manifest(conn, stage_outputs, "retrieval")
        packet = load_manifest_payload(retrieval_manifest)
        payload = {
            "artifact_type": "researcher_classification_readiness_block",
            "schema_version": STAGE_SCHEMA_VERSIONS["researcher_classification"],
            "case_id": lease["case_id"],
            "case_key": lease["case_key"],
            "dispatch_id": lease["dispatch_id"],
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
            "retrieval_packet_ref": retrieval_manifest["artifact_id"],
            "classification_dispatch_status": (packet.get("research_sufficiency_summary") or {}).get(
                "classification_dispatch_status"
            ),
            "classification_status": "blocked_until_certified_retrieval",
            "reason_codes": ["retrieval_sufficiency_not_certified"],
            "researcher_probability_authority": False,
            "writes_scae_delta": False,
        }
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="researcher_classification",
            file_name="researcher-classification-readiness-block.json",
            payload=payload,
            artifact_type=STAGE_ARTIFACT_TYPES["researcher_classification"],
            artifact_schema_version=STAGE_SCHEMA_VERSIONS["researcher_classification"],
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[retrieval_manifest["artifact_id"]],
            producer="researcher-swarm-production-readiness-adapter",
            reason_codes=["classification_block_valid"],
            metadata=factory_metadata,
        )
        return _result(
            "researcher_classification",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {**factory_metadata, "classification_status": "blocked_until_certified_retrieval"},
        )

    def classification_verification(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        qdt_manifest = resolve_stage_output_manifest(conn, stage_outputs, "decomposition")
        retrieval_manifest = resolve_stage_output_manifest(conn, stage_outputs, "retrieval")
        classification_manifest = resolve_stage_output_manifest(conn, stage_outputs, "researcher_classification")
        qdt = load_manifest_payload(qdt_manifest)
        rows = _blocked_reconciliation_rows(qdt, "classification-verification-production-readiness")
        payload = {
            "artifact_type": "classification_verification_readiness_block",
            "schema_version": STAGE_SCHEMA_VERSIONS["classification_verification"],
            "case_id": lease["case_id"],
            "case_key": lease["case_key"],
            "dispatch_id": lease["dispatch_id"],
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
            "qdt_ref": qdt_manifest["artifact_id"],
            "retrieval_packet_ref": retrieval_manifest["artifact_id"],
            "classification_ref": classification_manifest["artifact_id"],
            "verification_status": "blocked_no_researcher_classifications",
            "research_sufficiency_reconciliation_slices": rows,
            "reason_codes": ["classification_dispatch_blocked"],
            "writes_scae_delta": False,
        }
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="classification_verification",
            file_name="classification-verification-readiness-block.json",
            payload=payload,
            artifact_type=STAGE_ARTIFACT_TYPES["classification_verification"],
            artifact_schema_version=STAGE_SCHEMA_VERSIONS["classification_verification"],
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[
                qdt_manifest["artifact_id"],
                retrieval_manifest["artifact_id"],
                classification_manifest["artifact_id"],
            ],
            producer="researcher-swarm-production-readiness-adapter",
            reason_codes=["verification_block_valid"],
            metadata=factory_metadata,
        )
        return _result(
            "classification_verification",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {**factory_metadata, "verification_status": "blocked_no_researcher_classifications"},
        )

    def scae(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        qdt_manifest = resolve_stage_output_manifest(conn, stage_outputs, "decomposition")
        verification_manifest = resolve_stage_output_manifest(conn, stage_outputs, "classification_verification")
        case_manifest = _selected_case_contract_manifest(conn, stage_outputs)
        qdt = load_manifest_payload(qdt_manifest)
        verification_payload = load_manifest_payload(verification_manifest)
        ledger = _build_scae_ledger(
            lease=lease,
            context=context,
            case_contract=load_manifest_payload(case_manifest),
            qdt=qdt,
            sufficiency_rows=verification_payload.get("research_sufficiency_reconciliation_slices") or [],
            verification_manifest_id=verification_manifest["artifact_id"],
            forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
        )
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="scae",
            file_name="scae-final-probability-ledger.json",
            payload=ledger,
            artifact_type=STAGE_ARTIFACT_TYPES["scae"],
            artifact_schema_version=STAGE_SCHEMA_VERSIONS["scae"],
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[qdt_manifest["artifact_id"], case_manifest["artifact_id"], verification_manifest["artifact_id"]],
            producer="scae-production-readiness-adapter",
            reason_codes=["scae_ledger_valid", "production_probability_blocked_by_sufficiency"],
            metadata=factory_metadata,
        )
        return _result(
            "scae",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {
                **factory_metadata,
                "forecast_validity_status": ledger.get("forecast_validity_status"),
                "final_probability_fields_status": ledger.get("final_probability_fields_status"),
                "scoreable_forecast_output": False,
            },
        )

    def synthesis(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        scae_manifest = resolve_stage_output_manifest(conn, stage_outputs, "scae")
        ledger = load_manifest_payload(scae_manifest)
        payload = _build_synthesis_annotation(
            lease=lease,
            context=context,
            scae_ledger=ledger,
            scae_manifest=scae_manifest,
            forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
        )
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="synthesis",
            file_name="synthesis-annotation.json",
            payload=payload,
            artifact_type=STAGE_ARTIFACT_TYPES["synthesis"],
            artifact_schema_version=STAGE_SCHEMA_VERSIONS["synthesis"],
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[scae_manifest["artifact_id"]],
            producer="orchestrator-production-readiness-adapter",
            reason_codes=["synthesis_block_annotation_valid"],
            metadata=factory_metadata,
        )
        return _result(
            "synthesis",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {**factory_metadata, "synthesis_status": payload["synthesis_status"]},
        )

    def decision(**kwargs: Any) -> dict[str, Any]:
        conn = kwargs["conn"]
        context = kwargs["context"]
        lease = kwargs["lease"]
        stage_outputs = kwargs["stage_outputs"]
        scae_manifest = resolve_stage_output_manifest(conn, stage_outputs, "scae")
        synthesis_manifest = resolve_stage_output_manifest(conn, stage_outputs, "synthesis")
        case_manifest = _selected_case_contract_manifest(conn, stage_outputs)
        ledger = load_manifest_payload(scae_manifest)
        synthesis_payload = load_manifest_payload(synthesis_manifest)
        gate = _build_decision_gate(
            lease=lease,
            context=context,
            scae_ledger=ledger,
            scae_manifest=scae_manifest,
            synthesis=synthesis_payload,
            forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
        )
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="decision",
            file_name="decision-gate.json",
            payload=gate,
            artifact_type=STAGE_ARTIFACT_TYPES["decision"],
            artifact_schema_version=STAGE_SCHEMA_VERSIONS["decision"],
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[scae_manifest["artifact_id"], synthesis_manifest["artifact_id"]],
            producer="orchestrator-production-readiness-adapter",
            reason_codes=["decision_gate_valid", "market_prediction_write_blocked"],
            metadata=factory_metadata,
        )
        persisted = write_scae_market_prediction(
            db_file,
            ledger,
            gate,
            load_manifest_payload(case_manifest),
            metadata={
                "forecast_decision_artifact_path": manifest["path"],
                "scae_ledger_artifact_path": scae_manifest["path"],
                "handler_scope": HANDLER_SCOPE,
                "non_scoreable_reason": "research_sufficiency_not_certified",
                **factory_metadata,
            },
        )
        result = _result(
            "decision",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {
                **factory_metadata,
                "market_prediction_written": bool(persisted["market_prediction_written"]),
                "scoreable_forecast_output": bool(persisted["scoreable_forecast_output"]),
                "block_reason_code": persisted.get("block_reason_code"),
            },
        )
        result["forecast_decision_record_id"] = persisted["forecast_decision_id"]
        result["forecast_artifact_id"] = persisted.get("forecast_artifact_id")
        if persisted.get("prediction_id") is not None:
            result["market_prediction_id"] = str(persisted["prediction_id"])
        return result

    def terminal_record(stage: str) -> Callable[..., dict[str, Any]]:
        def handler(**kwargs: Any) -> dict[str, Any]:
            conn = kwargs["conn"]
            context = kwargs["context"]
            lease = kwargs["lease"]
            stage_outputs = kwargs["stage_outputs"]
            previous = PREVIOUS_STAGE[stage]
            previous_manifest = resolve_stage_output_manifest(conn, stage_outputs, previous)
            payload = {
                "artifact_type": STAGE_ARTIFACT_TYPES[stage].replace("-", "_"),
                "schema_version": STAGE_SCHEMA_VERSIONS[stage],
                "case_id": lease["case_id"],
                "case_key": lease["case_key"],
                "dispatch_id": lease["dispatch_id"],
                "run_id": context.pipeline_run_id,
                "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
                "input_manifest_ids": [previous_manifest["artifact_id"]],
                "record_status": "recorded_non_scoreable_readiness_run",
                "scoreable_forecast_output": False,
                "writes_production_forecast": False,
                "reason_codes": ["non_scoreable_readiness_run"],
            }
            manifest, validation_id = _write_payload_manifest(
                conn,
                context=context,
                lease=lease,
                artifact_dir=_stage_artifact_dir(base_dir, context, lease),
                stage=stage,
                file_name=f"{stage}.json",
                payload=payload,
                artifact_type=STAGE_ARTIFACT_TYPES[stage],
                artifact_schema_version=STAGE_SCHEMA_VERSIONS[stage],
                forecast_timestamp=forecast_timestamp,
                input_manifest_ids=[previous_manifest["artifact_id"]],
                producer="orchestrator-production-readiness-adapter",
                reason_codes=["terminal_readiness_record_valid"],
                metadata=factory_metadata,
            )
            return _result(
                stage,
                [manifest["artifact_id"]],
                [validation_id],
                lease,
                {**factory_metadata, "record_status": payload["record_status"]},
            )

        return handler

    handlers: dict[str, Callable[..., Any]] = {
        "evidence_packet": evidence_packet,
        "policy_context": policy_context,
        "related_market_context": related_market_context,
        "decomposition": decomposition,
        "retrieval": retrieval,
        "researcher_classification": researcher_classification,
        "classification_verification": classification_verification,
        "scae": scae,
        "synthesis": synthesis,
        "decision": decision,
        "training_trace": terminal_record("training_trace"),
        "replay_record": terminal_record("replay_record"),
    }
    return handlers


__all__ = ["build_stage_handlers"]
