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
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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
from ads_decomposer.persistence import (  # noqa: E402
    write_decomposition_run,
    write_qdt_research_sufficiency_requirements,
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
    build_live_retrieval_packet_from_candidates,
    build_retrieval_evidence_item,
    build_retrieval_packet,
    dump_retrieval_packet,
    finalize_retrieval_packet_for_dispatch,
)
from researcher_swarm.assignments import build_leaf_research_assignments  # noqa: E402
from researcher_swarm.subagents import build_leaf_research_barrier, build_leaf_researcher_spawn_plan  # noqa: E402
from scae.intervals import build_pre_debt_ledger_output  # noqa: E402
from scae.ledger import apply_research_sufficiency_guard, finalize_scae_probability_fields  # noqa: E402
from scae.persistence import write_scae_market_prediction  # noqa: E402
from scae.prior import build_prior_context  # noqa: E402


HANDLER_FACTORY_REF = "predquant.ads_production_readiness_handlers"
HANDLER_SCOPE = "production_readiness_fail_closed"
VALIDATOR_VERSION = "ads-production-readiness-handler/v1"
ARTIFACT_DIR_NAME = "production_readiness"
PRODUCTION_PILOT_HANDLER_FACTORY_REF = "predquant.ads_production_pilot_handlers"
PRODUCTION_PILOT_HANDLER_SCOPE = "production_pilot_structured_market_metadata"
PILOT_QDT_ADAPTER_MODE = "pilot_fixture_decomposer_contract_adapter"
TRUE_PRODUCTION_HANDLER_FACTORY_REF = "predquant.ads_production_handlers"
TRUE_PRODUCTION_HANDLER_SCOPE = "true_production_specialist_runtime"

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


def _iso_before_cutoff(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value)
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    observed = parsed.astimezone(timezone.utc) - timedelta(seconds=1)
    return observed.isoformat()


def _market_url(case_contract: dict[str, Any]) -> str:
    identity = case_contract.get("market_identity") if isinstance(case_contract, dict) else {}
    if not isinstance(identity, dict):
        identity = {}
    slug = str(identity.get("slug") or "").strip().strip("/")
    external = str(identity.get("external_market_id") or identity.get("internal_market_id") or "unknown").strip()
    if slug:
        return f"https://polymarket.com/event/{slug}"
    return f"https://polymarket.com/market/{external}"


def _structured_market_metadata_evidence(
    *,
    qdt: dict[str, Any],
    case_contract: dict[str, Any],
    source_cutoff_timestamp: str,
) -> list[dict[str, Any]]:
    """Build narrow deterministic evidence from market metadata and snapshot state.

    This does not perform external web research. It is a production-pilot lane
    for proving SCAE/PERSIST scoreable mechanics from structured market inputs
    while calibration-debt controls remain active.
    """

    identity = case_contract.get("market_identity") if isinstance(case_contract, dict) else {}
    baseline = case_contract.get("prediction_time_market_baseline") if isinstance(case_contract, dict) else {}
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(baseline, dict):
        baseline = {}
    observed_at = _iso_before_cutoff(str(baseline.get("source_fetched_at") or source_cutoff_timestamp))
    canonical_url = _market_url(case_contract)
    title = str(identity.get("title") or qdt.get("macro_question") or "market question")
    description = str(identity.get("description") or "")
    selected: list[dict[str, Any]] = []
    for leaf in qdt.get("required_leaf_questions", []):
        if not isinstance(leaf, dict) or not leaf.get("leaf_id"):
            continue
        leaf_id = str(leaf["leaf_id"])
        parent_branch_id = str(leaf.get("parent_branch_id") or "branch-resolution")
        common = {
            "case_id": str(qdt.get("case_id") or case_contract["case_id"]),
            "dispatch_id": str(qdt.get("dispatch_id") or case_contract["dispatch_id"]),
            "leaf_id": leaf_id,
            "parent_branch_id": parent_branch_id,
            "retrieval_transport": "structured_feed",
            "requested_url": canonical_url,
            "final_url": canonical_url,
            "canonical_url": canonical_url,
            "temporal_gate_status": "pass",
            "source_published_at": observed_at,
            "source_observed_at": observed_at,
            "retrieval_score": 1.0,
            "admission_status": "admitted",
            "admission_reason_codes": ["structured_market_metadata_pilot"],
        }
        selected.append(
            build_retrieval_evidence_item(
                **common,
                transport_attempt_ref=f"structured-feed:market-metadata:{leaf_id}:primary",
                canonical_source_id="source:polymarket-market-metadata",
                source_family_id=f"source-family:polymarket-market-metadata:{leaf_id}",
                source_class="official_or_primary",
                independence_status="independent",
                claim_family_resolution_refs=[f"claim-family-resolution:market-rules:{leaf_id}"],
                content_sha256="sha256:"
                + hashlib.sha256(
                    canonical_json(
                        {
                            "title": title,
                            "description": description,
                            "leaf_id": leaf_id,
                            "source": "market_metadata",
                        }
                    ).encode("utf-8")
                ).hexdigest(),
            )
        )
        selected[-1]["deterministic_source_class_proof"] = True
        selected[-1]["source_class_resolution_method"] = "structured_market_metadata_primary_source"
        selected[-1]["source_family_resolution_method"] = "structured_market_metadata_feed"
        selected[-1]["claim_family_ids"] = [f"claim-family:market-rules:{leaf_id}"]
        selected.append(
            build_retrieval_evidence_item(
                **common,
                transport_attempt_ref=f"structured-feed:market-snapshot:{leaf_id}:secondary",
                canonical_source_id="source:predquant-market-snapshot",
                source_family_id=f"source-family:predquant-market-snapshot:{leaf_id}",
                source_class="independent_secondary",
                independence_status="independent",
                claim_family_resolution_refs=[f"claim-family-resolution:market-state:{leaf_id}"],
                content_sha256="sha256:"
                + hashlib.sha256(
                    canonical_json(
                        {
                            "market_probability": baseline.get("market_probability"),
                            "method": baseline.get("market_probability_method"),
                            "snapshot": baseline.get("market_snapshot_id"),
                            "leaf_id": leaf_id,
                            "source": "market_snapshot",
                        }
                    ).encode("utf-8")
                ).hexdigest(),
            )
        )
        selected[-1]["source_class_resolution_method"] = "structured_market_snapshot_feed"
        selected[-1]["source_family_resolution_method"] = "structured_market_snapshot_feed"
        selected[-1]["claim_family_ids"] = [f"claim-family:market-state:{leaf_id}"]
    return selected


def _live_fixture_direct_candidates(
    *,
    qdt: dict[str, Any],
    case_contract: dict[str, Any],
    source_cutoff_timestamp: str,
) -> list[dict[str, Any]]:
    """Build live-shaped browser candidate records for the Phase 3 retrieval executor."""

    observed_at = _iso_before_cutoff(source_cutoff_timestamp)
    canonical_url = _market_url(case_contract)
    candidates: list[dict[str, Any]] = []
    for leaf in qdt.get("required_leaf_questions", []):
        if not isinstance(leaf, dict) or not leaf.get("leaf_id"):
            continue
        leaf_id = str(leaf["leaf_id"])
        parent_branch_id = str(leaf.get("parent_branch_id") or "branch-runtime")
        purpose = str(leaf.get("purpose") or "other")
        minimum = 2 if purpose == "resolution_mechanics" else 5
        for idx in range(minimum):
            if idx == 0:
                source_class = "official_or_primary"
                source_family_id = f"source-family:runtime-fixture-official:{leaf_id}"
                url = canonical_url
                method = "live_fixture_direct_official_url"
                navigation_mode = "direct_url"
            else:
                source_class = "independent_secondary"
                source_family_id = f"source-family:runtime-fixture-secondary-{idx}:{leaf_id}"
                url = f"https://evidence-fixture.example/{leaf_id}/{idx}"
                method = "live_fixture_independent_source"
                navigation_mode = "web_search"
            candidates.append(
                {
                    "leaf_id": leaf_id,
                    "parent_branch_id": parent_branch_id,
                    "retrieval_transport": "browser",
                    "navigation_mode": navigation_mode,
                    "requested_url": url,
                    "final_url": url,
                    "canonical_url": url,
                    "source_family_id": source_family_id,
                    "source_class": source_class,
                    "independence_status": "independent",
                    "temporal_gate_status": "pass",
                    "source_published_at": observed_at,
                    "source_observed_at": observed_at,
                    "captured_at": observed_at,
                    "retrieval_score": 1.0,
                    "admission_status": "admitted",
                    "admission_reason_code": "live_fixture_direct_evidence",
                    "claim_family_id": f"claim-family:runtime-fixture:{leaf_id}:{idx % 3}",
                    "deterministic_source_class_proof": True,
                    "source_class_resolution_method": method,
                    "source_family_resolution_method": method,
                    "result_rank": idx + 1,
                    "direct_url_source_ref": "case_contract.market_url" if idx == 0 else None,
                    "content": canonical_json(
                        {
                            "leaf_id": leaf_id,
                            "purpose": purpose,
                            "source_index": idx,
                            "source_class": source_class,
                            "question_text": leaf.get("question_text"),
                        }
                    ),
                }
            )
    return candidates


def _certified_reconciliation_rows(
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    verification_manifest_id: str,
) -> list[dict[str, Any]]:
    certificates = {
        str(item["leaf_id"]): item
        for item in retrieval_packet.get("leaf_research_sufficiency_certificates", [])
        if isinstance(item, dict) and item.get("leaf_id")
    }
    coverage = {
        str(item["coverage_id"]): item
        for item in retrieval_packet.get("retrieval_breadth_coverage_slices", [])
        if isinstance(item, dict) and item.get("coverage_id")
    }
    rows: list[dict[str, Any]] = []
    for leaf in qdt.get("required_leaf_questions", []):
        if not isinstance(leaf, dict) or not leaf.get("leaf_id"):
            continue
        leaf_id = str(leaf["leaf_id"])
        cert = certificates.get(leaf_id) or {}
        coverage_ref = cert.get("breadth_coverage_ref")
        coverage_row = coverage.get(str(coverage_ref)) if coverage_ref else {}
        status = (
            "scae_ready_high_certainty"
            if cert.get("status") == "certified_high_certainty"
            and cert.get("classification_dispatch_allowed") is True
            and cert.get("breadth_certified") is True
            else "blocked_insufficient_research"
        )
        blocking = [] if status == "scae_ready_high_certainty" else ["research_sufficiency_not_certified"]
        rows.append(
            {
                "artifact_type": "research_sufficiency_reconciliation_slice",
                "schema_version": "research-sufficiency-reconciliation-slice/v1",
                "research_sufficiency_reconciliation_id": (
                    f"research-sufficiency-reconciliation:production-pilot:{leaf_id}"
                ),
                "leaf_id": leaf_id,
                "research_sufficiency_reconciliation_status": status,
                "reconciled_status": status,
                "blocking_reason_codes": blocking,
                "reason_codes": ["structured_market_metadata_pilot_verified"],
                "research_sufficiency_certificate_ref": cert.get("certificate_id"),
                "retrieval_breadth_profile_ref": (coverage_row or {}).get("breadth_profile_ref")
                or (leaf.get("research_sufficiency_requirements") or {}).get("retrieval_breadth_profile_ref"),
                "retrieval_breadth_coverage_ref": coverage_ref,
                "retrieval_breadth_certified": bool(cert.get("breadth_certified") is True),
                "required_escalation_decision_refs": [],
                "completed_escalation_decision_refs": [],
                "verification_manifest_ref": verification_manifest_id,
            }
        )
    return rows


def _build_scae_ledger(
    *,
    lease: dict[str, Any],
    context: Any,
    case_contract: dict[str, Any],
    qdt: dict[str, Any],
    sufficiency_rows: list[dict[str, Any]],
    verification_manifest_id: str,
    forecast_timestamp: str,
    scoreable_pilot: bool = False,
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
            "adapter_mode": (
                "structured_market_metadata_pilot_prior_only"
                if scoreable_pilot
                else "prior_only_until_research_sufficiency_certified"
            ),
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
            "adapter_mode": (
                "production_pilot_structured_market_metadata"
                if scoreable_pilot
                else "production_readiness_fail_closed"
            ),
            "scoreable_forecast_output": bool(
                scoreable_pilot and finalized.get("forecast_validity_status") != "invalid_for_forecast"
            ),
            "market_prediction_write_expected": bool(
                scoreable_pilot and finalized.get("forecast_validity_status") != "invalid_for_forecast"
            ),
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
        "synthesis_status": (
            "ready_for_scoreable_pilot"
            if scae_ledger.get("forecast_validity_status") != "invalid_for_forecast"
            else "blocked_by_research_sufficiency"
        ),
        "reason_codes": (
            ["structured_market_metadata_pilot_synthesis_ready"]
            if scae_ledger.get("forecast_validity_status") != "invalid_for_forecast"
            else ["scae_forecast_invalid_for_production_readiness_run"]
        ),
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
    execution = str(scae_ledger.get("execution_authority_status") or "forbidden")
    actionability_by_execution = {
        "forbidden": "non_actionable",
        "needs_refresh": "refresh_required",
        "watch_only": "watch_only",
        "low_size_only": "actionable_low_size",
        "normal_execution_allowed": "actionable",
    }
    actionability = actionability_by_execution.get(execution, "non_actionable")
    scae_context = {
        "scae_ledger_ref": scae_ledger["final_probability_ledger_id"],
        "scae_ledger_digest": scae_ledger["final_probability_ledger_digest"],
        "scae_manifest_ref": scae_manifest["artifact_id"],
        "case_id": scae_ledger["case_id"],
        "case_key": scae_ledger["case_key"],
        "dispatch_id": scae_ledger["dispatch_id"],
        "run_id": context.pipeline_run_id,
        "forecast_timestamp": forecast_timestamp,
        "forecast_validity_status": scae_ledger.get("forecast_validity_status"),
        "execution_authority_status": execution,
    }
    if scae_ledger.get("forecast_validity_status") != "invalid_for_forecast":
        scae_context["production_forecast_prob"] = scae_ledger.get("production_forecast_prob")
        scae_context["canonical_probability"] = scae_ledger.get("canonical_probability")
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
        "execution_authority_status": execution,
        "actionability_status": actionability,
        "scae_context": scae_context,
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
    scoreable_pilot: bool = False,
    handler_factory_ref: str | None = None,
    handler_scope: str | None = None,
    decomposer_runtime: bool = False,
    decomposer_runtime_mode: str = "fixture",
    decomposer_runtime_transport_response_path: str | Path | None = None,
    live_policy_overlay: bool = False,
    live_fixture_retrieval: bool = False,
    block_at_leaf_research_barrier: bool = False,
) -> dict[str, Callable[..., Any]]:
    resolved_factory_ref = handler_factory_ref or HANDLER_FACTORY_REF
    resolved_handler_scope = handler_scope or HANDLER_SCOPE
    if artifact_dir:
        base_dir = Path(artifact_dir).expanduser().resolve()
    else:
        db_parent = Path(db_path or ".").expanduser().resolve().parent
        base_dir = db_parent / "ads_artifacts" / (
            "production_pilot" if scoreable_pilot else ARTIFACT_DIR_NAME
        )
    db_file = Path(db_path) if db_path else Path(":memory:")
    factory_metadata = {
        "handler_factory": resolved_factory_ref,
        "handler_scope": resolved_handler_scope,
        "runner_mode": runner_mode,
        "max_cases": max_cases,
        "forecast_authority_policy": "scae_only",
        "scoreable_forecast_policy": (
            "structured_market_metadata_scoreable_under_calibration_debt_controls"
            if scoreable_pilot
            else "blocked_until_research_sufficiency_certified"
        ),
        "scoreable_pilot": bool(scoreable_pilot),
        "decomposer_runtime": bool(decomposer_runtime),
        "decomposer_runtime_mode": decomposer_runtime_mode,
        "live_policy_overlay": bool(live_policy_overlay),
        "live_fixture_retrieval": bool(live_fixture_retrieval),
        "block_at_leaf_research_barrier": bool(block_at_leaf_research_barrier),
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
        qdt_path = stage_dir / "question-decomposition.json"
        qdt_input_manifest_ids = [handoff_manifest["artifact_id"]]
        runtime_manifest = None
        if decomposer_runtime:
            runtime_call_path = stage_dir / "model-runtime-call.json"
            handoff_path = Path(handoff_manifest["path"])
            command = [
                sys.executable,
                str(DECOMPOSER_SCRIPTS / "bin" / "run_decomposition.py"),
                "--handoff",
                str(handoff_path),
                "--output",
                str(qdt_path),
                "--runtime-call-output",
                str(runtime_call_path),
                "--runtime-mode",
                decomposer_runtime_mode,
            ]
            if decomposer_runtime_transport_response_path is not None:
                command.extend(["--transport-response", str(decomposer_runtime_transport_response_path)])
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            if completed.returncode != 0:
                raise RuntimeError(
                    "decomposer runtime failed: "
                    + (completed.stderr.strip() or completed.stdout.strip() or str(completed.returncode))
                )
            runtime_payload = json.loads(runtime_call_path.read_text(encoding="utf-8"))
            runtime_manifest, runtime_validation_id = _write_payload_manifest(
                conn,
                context=context,
                lease=lease,
                artifact_dir=stage_dir,
                stage="decomposition",
                file_name="model-runtime-call.json",
                payload=runtime_payload,
                artifact_type="model-runtime-call",
                artifact_schema_version="model-runtime-call/v1",
                forecast_timestamp=forecast_timestamp,
                input_manifest_ids=[handoff_manifest["artifact_id"]],
                producer="decomposer-model-runtime",
                reason_codes=["decomposer_model_runtime_call_valid"],
                metadata=factory_metadata,
            )
            qdt_input_manifest_ids.append(runtime_manifest["artifact_id"])
            qdt = json.loads(qdt_path.read_text(encoding="utf-8"))
        else:
            candidate = build_fixture_qdt_candidate(handoff)
            candidate["market_id"] = str(
                handoff.get("market_context", {}).get("market_id") or lease["market_id"]
            )
            qdt = select_qdt_candidate([candidate])
            qdt["adapter_mode"] = PILOT_QDT_ADAPTER_MODE
            qdt["input_manifest_ids"] = [handoff_manifest["artifact_id"]]
            _write_json(qdt_path, json.loads(dump_question_decomposition(qdt)))
        qdt_manifest = build_artifact_manifest(
            context=ArtifactManifestContext(
                case_id=lease["case_id"],
                case_key=lease["case_key"],
                dispatch_id=lease["dispatch_id"],
                stage="decomposition",
            producer="decomposer-model-runtime" if decomposer_runtime else "decomposer-production-readiness-adapter",
                forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
                source_cutoff_timestamp=lease["selected_snapshot_observed_at"],
                pipeline_run_id=context.pipeline_run_id,
            ),
            artifact_type=QUESTION_DECOMPOSITION_ARTIFACT_TYPE.replace("_", "-"),
            artifact_schema_version=QUESTION_DECOMPOSITION_SCHEMA_VERSION,
            path=qdt_path,
            input_manifest_ids=qdt_input_manifest_ids,
            validation_status="valid",
            validator_version=VALIDATOR_VERSION,
            temporal_isolation_status="pass",
            metadata={
                "handler_scope": resolved_handler_scope,
                "handler_factory": resolved_factory_ref,
                "adapter_mode": qdt.get("adapter_mode") or PILOT_QDT_ADAPTER_MODE,
                "scoreable_pilot": bool(scoreable_pilot),
                "decomposer_runtime": bool(decomposer_runtime),
            },
        )
        qdt_validation = build_validation_result(
            artifact_id=qdt_manifest["artifact_id"],
            status="valid",
            validator_version=VALIDATOR_VERSION,
            reason_codes=[
                "question_decomposition_valid",
                "decomposer_model_runtime_valid" if decomposer_runtime else "pilot_fixture_contract_adapter",
            ],
            validation_messages=[
                "QDT selected from Decomposer model runtime"
                if decomposer_runtime
                else "QDT selected from pilot fixture production-readiness adapter"
            ],
            metadata={"handler_scope": HANDLER_SCOPE, "stage": "decomposition"},
        )
        write_artifact_manifest(conn, qdt_manifest, validation_results=[qdt_validation])
        qdt_manifest = resolve_artifact_manifest(conn, qdt_manifest["artifact_id"])
        decomposition_run_id = write_decomposition_run(conn, qdt, manifest=qdt_manifest)
        persistence_result = write_qdt_research_sufficiency_requirements(
            conn,
            qdt,
            decomposition_run_id=decomposition_run_id,
            qdt_artifact_id=qdt_manifest["artifact_id"],
        )
        validation_ids = [qdt_validation["validation_result_id"], handoff_validation_id]
        artifact_ids = [qdt_manifest["artifact_id"], handoff_manifest["artifact_id"]]
        if runtime_manifest is not None:
            validation_ids.append(runtime_validation_id)
            artifact_ids.append(runtime_manifest["artifact_id"])
        return _result(
            "decomposition",
            artifact_ids,
            validation_ids,
            lease,
            {
                **factory_metadata,
                "qdt_adapter_mode": qdt.get("adapter_mode") or PILOT_QDT_ADAPTER_MODE,
                "decomposer_handoff_ref": handoff_manifest["artifact_id"],
                "runtime_call_ref": (runtime_manifest or {}).get("artifact_id"),
                "decomposition_run_id": decomposition_run_id,
                "sufficiency_requirement_record_count": len(
                    persistence_result["sufficiency_requirement_record_ids"]
                ),
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
        case_manifest = _selected_case_contract_manifest(conn, stage_outputs)
        qdt_payload = load_manifest_payload(qdt_manifest)
        case_contract = load_manifest_payload(case_manifest)
        source_cutoff = lease["selected_snapshot_observed_at"]
        if live_fixture_retrieval:
            fetched_candidates = _live_fixture_direct_candidates(
                qdt=qdt_payload,
                case_contract=case_contract,
                source_cutoff_timestamp=source_cutoff,
            )
            packet = build_live_retrieval_packet_from_candidates(
                qdt_payload,
                evidence_packet=load_manifest_payload(evidence_manifest),
                amrg_context=load_manifest_payload(related_manifest),
                fetched_candidates=fetched_candidates,
                question_decomposition_artifact_id=qdt_manifest["artifact_id"],
                policy_context_ref=profile_manifest["artifact_id"],
                forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
                source_cutoff_timestamp=source_cutoff,
                pre_dispatch_input_whitelist_refs=[
                    qdt_manifest["artifact_id"],
                    evidence_manifest["artifact_id"],
                    profile_manifest["artifact_id"],
                    related_manifest["artifact_id"],
                ],
                live_retrieval_allowlist=["browser", "native_gpt_research", "structured_feed"],
                live_policy_overlay=live_policy_overlay,
            )
        elif scoreable_pilot:
            selected_evidence = _structured_market_metadata_evidence(
                qdt=qdt_payload,
                case_contract=case_contract,
                source_cutoff_timestamp=source_cutoff,
            )
            packet = build_retrieval_packet(
                qdt_payload,
                evidence_packet=load_manifest_payload(evidence_manifest),
                amrg_context=load_manifest_payload(related_manifest),
                question_decomposition_artifact_id=qdt_manifest["artifact_id"],
                policy_context_ref=profile_manifest["artifact_id"],
                selected_evidence=selected_evidence,
                forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
                source_cutoff_timestamp=source_cutoff,
                pre_dispatch_input_whitelist_refs=[
                    qdt_manifest["artifact_id"],
                    evidence_manifest["artifact_id"],
                    profile_manifest["artifact_id"],
                    related_manifest["artifact_id"],
                ],
                live_retrieval_allowlist=["browser", "native_gpt_research", "structured_feed"],
                live_policy_overlay=live_policy_overlay,
            )
            packet = finalize_retrieval_packet_for_dispatch(packet)
        else:
            packet = build_retrieval_packet(
                qdt_payload,
                evidence_packet=load_manifest_payload(evidence_manifest),
                amrg_context=load_manifest_payload(related_manifest),
                question_decomposition_artifact_id=qdt_manifest["artifact_id"],
                policy_context_ref=profile_manifest["artifact_id"],
                selected_evidence=None,
                forecast_timestamp=_forecast_timestamp(forecast_timestamp, lease),
                source_cutoff_timestamp=source_cutoff,
                pre_dispatch_input_whitelist_refs=[
                    qdt_manifest["artifact_id"],
                    evidence_manifest["artifact_id"],
                    profile_manifest["artifact_id"],
                    related_manifest["artifact_id"],
                ],
                live_retrieval_allowlist=["browser", "native_gpt_research", "structured_feed"],
                live_policy_overlay=live_policy_overlay,
            )
            packet = finalize_retrieval_packet_for_dispatch(packet)
        if live_fixture_retrieval:
            packet["adapter_mode"] = "live_candidate_fixture_retrieval_runtime"
        elif scoreable_pilot:
            packet["adapter_mode"] = "structured_market_metadata_pilot_retrieval"
        else:
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
            reason_codes=[
                "retrieval_packet_valid",
                (
                    "live_candidate_fixture_retrieval_certified"
                    if live_fixture_retrieval
                    else
                    "structured_market_metadata_pilot_certified"
                    if scoreable_pilot
                    else "classification_dispatch_blocked_until_certified"
                ),
            ],
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
        qdt_manifest = resolve_stage_output_manifest(conn, stage_outputs, "decomposition")
        packet = load_manifest_payload(retrieval_manifest)
        qdt_payload = load_manifest_payload(qdt_manifest)
        summary = packet.get("research_sufficiency_summary") or {}
        if block_at_leaf_research_barrier and summary.get("classification_dispatch_status") == "allowed":
            assignments = build_leaf_research_assignments(qdt=qdt_payload, retrieval_packet=packet)
            spawn_plan = build_leaf_researcher_spawn_plan(assignments)
            barrier = build_leaf_research_barrier(assignments, true_production_mode=True)
            classification_status = "blocked_leaf_research_barrier"
            reason_codes = barrier.get("blocker_reason_codes") or ["leaf_research_barrier_not_terminal"]
            file_name = "leaf-research-barrier.json"
            payload = {
                "artifact_type": "leaf_research_barrier",
                "schema_version": "leaf-research-barrier/v1",
                "case_id": lease["case_id"],
                "case_key": lease["case_key"],
                "dispatch_id": lease["dispatch_id"],
                "run_id": context.pipeline_run_id,
                "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
                "qdt_ref": qdt_manifest["artifact_id"],
                "retrieval_packet_ref": retrieval_manifest["artifact_id"],
                "classification_dispatch_status": summary.get("classification_dispatch_status"),
                "classification_status": classification_status,
                "reason_codes": reason_codes,
                "assignments": assignments,
                "spawn_plan": spawn_plan,
                "leaf_research_barrier": barrier,
                "researcher_probability_authority": False,
                "writes_scae_delta": False,
                "selected_evidence_count": sum(
                    len(result.get("selected_evidence", []))
                    for result in packet.get("leaf_retrieval_results", [])
                    if isinstance(result, dict)
                ),
                "leaf_certificate_refs": list(summary.get("leaf_certificate_refs") or []),
            }
            manifest_artifact_type = "leaf-research-barrier"
            manifest_schema_version = "leaf-research-barrier/v1"
        elif scoreable_pilot and summary.get("classification_dispatch_status") == "allowed":
            classification_status = "structured_market_metadata_certified"
            reason_codes = ["structured_market_metadata_retrieval_certified"]
            file_name = "researcher-classification-production-pilot.json"
            payload = None
            manifest_artifact_type = STAGE_ARTIFACT_TYPES["researcher_classification"]
            manifest_schema_version = STAGE_SCHEMA_VERSIONS["researcher_classification"]
        else:
            classification_status = "blocked_until_certified_retrieval"
            reason_codes = ["retrieval_sufficiency_not_certified"]
            file_name = "researcher-classification-readiness-block.json"
            payload = None
            manifest_artifact_type = STAGE_ARTIFACT_TYPES["researcher_classification"]
            manifest_schema_version = STAGE_SCHEMA_VERSIONS["researcher_classification"]
        if payload is None:
            payload = {
                "artifact_type": (
                    "researcher_classification_production_pilot"
                    if classification_status == "structured_market_metadata_certified"
                    else "researcher_classification_readiness_block"
                ),
                "schema_version": STAGE_SCHEMA_VERSIONS["researcher_classification"],
                "case_id": lease["case_id"],
                "case_key": lease["case_key"],
                "dispatch_id": lease["dispatch_id"],
                "run_id": context.pipeline_run_id,
                "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
                "retrieval_packet_ref": retrieval_manifest["artifact_id"],
                "classification_dispatch_status": summary.get("classification_dispatch_status"),
                "classification_status": classification_status,
                "reason_codes": reason_codes,
                "researcher_probability_authority": False,
                "writes_scae_delta": False,
                "selected_evidence_count": sum(
                    len(result.get("selected_evidence", []))
                    for result in packet.get("leaf_retrieval_results", [])
                    if isinstance(result, dict)
                ),
                "leaf_certificate_refs": list(summary.get("leaf_certificate_refs") or []),
            }
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="researcher_classification",
            file_name=file_name,
            payload=payload,
            artifact_type=manifest_artifact_type,
            artifact_schema_version=manifest_schema_version,
            forecast_timestamp=forecast_timestamp,
            input_manifest_ids=[qdt_manifest["artifact_id"], retrieval_manifest["artifact_id"]],
            producer="researcher-swarm-production-readiness-adapter",
            reason_codes=[
                "leaf_research_barrier_block_valid"
                if classification_status == "blocked_leaf_research_barrier"
                else (
                    "classification_pilot_valid"
                    if classification_status == "structured_market_metadata_certified"
                    else "classification_block_valid"
                )
            ],
            metadata=factory_metadata,
        )
        return _result(
            "researcher_classification",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {**factory_metadata, "classification_status": classification_status},
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
        retrieval_packet = load_manifest_payload(retrieval_manifest)
        if scoreable_pilot:
            verification_ref = "classification-verification-production-pilot"
            rows = _certified_reconciliation_rows(qdt, retrieval_packet, verification_ref)
            verification_status = (
                "structured_market_metadata_certified"
                if rows and all(row.get("reconciled_status") == "scae_ready_high_certainty" for row in rows)
                else "blocked_insufficient_research"
            )
            reason_codes = (
                ["structured_market_metadata_reconciliation_certified"]
                if verification_status == "structured_market_metadata_certified"
                else ["structured_market_metadata_reconciliation_blocked"]
            )
            file_name = "classification-verification-production-pilot.json"
        else:
            rows = _blocked_reconciliation_rows(qdt, "classification-verification-production-readiness")
            verification_status = "blocked_no_researcher_classifications"
            reason_codes = ["classification_dispatch_blocked"]
            file_name = "classification-verification-readiness-block.json"
        payload = {
            "artifact_type": (
                "classification_verification_production_pilot"
                if scoreable_pilot
                else "classification_verification_readiness_block"
            ),
            "schema_version": STAGE_SCHEMA_VERSIONS["classification_verification"],
            "case_id": lease["case_id"],
            "case_key": lease["case_key"],
            "dispatch_id": lease["dispatch_id"],
            "run_id": context.pipeline_run_id,
            "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
            "qdt_ref": qdt_manifest["artifact_id"],
            "retrieval_packet_ref": retrieval_manifest["artifact_id"],
            "classification_ref": classification_manifest["artifact_id"],
            "verification_status": verification_status,
            "research_sufficiency_reconciliation_slices": rows,
            "reason_codes": reason_codes,
            "writes_scae_delta": False,
        }
        manifest, validation_id = _write_payload_manifest(
            conn,
            context=context,
            lease=lease,
            artifact_dir=_stage_artifact_dir(base_dir, context, lease),
            stage="classification_verification",
            file_name=file_name,
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
            reason_codes=[
                "verification_pilot_valid"
                if verification_status == "structured_market_metadata_certified"
                else "verification_block_valid"
            ],
            metadata=factory_metadata,
        )
        return _result(
            "classification_verification",
            [manifest["artifact_id"]],
            [validation_id],
            lease,
            {**factory_metadata, "verification_status": verification_status},
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
            scoreable_pilot=scoreable_pilot,
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
            reason_codes=[
                "scae_ledger_valid",
                (
                    "structured_market_metadata_probability_ready_under_debt_controls"
                    if scoreable_pilot and ledger.get("forecast_validity_status") != "invalid_for_forecast"
                    else "production_probability_blocked_by_sufficiency"
                ),
            ],
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
                "scoreable_forecast_output": bool(ledger.get("scoreable_forecast_output")),
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
                "handler_scope": resolved_handler_scope,
                **(
                    {}
                    if scoreable_pilot
                    else {"non_scoreable_reason": "research_sufficiency_not_certified"}
                ),
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
            decision_output = stage_outputs.get("decision") or {}
            decision_metadata = decision_output.get("safe_metadata") or {}
            scoreable = bool(decision_metadata.get("scoreable_forecast_output"))
            payload = {
                "artifact_type": STAGE_ARTIFACT_TYPES[stage].replace("-", "_"),
                "schema_version": STAGE_SCHEMA_VERSIONS[stage],
                "case_id": lease["case_id"],
                "case_key": lease["case_key"],
                "dispatch_id": lease["dispatch_id"],
                "run_id": context.pipeline_run_id,
                "forecast_timestamp": _forecast_timestamp(forecast_timestamp, lease),
                "input_manifest_ids": [previous_manifest["artifact_id"]],
                "record_status": (
                    "recorded_scoreable_production_pilot_run"
                    if scoreable
                    else "recorded_non_scoreable_readiness_run"
                ),
                "scoreable_forecast_output": scoreable,
                "writes_production_forecast": scoreable,
                "reason_codes": (
                    ["scoreable_production_pilot_run"]
                    if scoreable
                    else ["non_scoreable_readiness_run"]
                ),
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
