"""Scoreable ADS canary stage handlers.

These handlers are intentionally bounded operational canary adapters. They
exercise the ADS runner, case lease, decision persistence, and SCAE prediction
bridge without claiming to be the production specialist workspace adapters.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from predquant.ads_pipeline_runner import ADS_PIPELINE_STAGE_ORDER, StageHandlerResult, utc_now_iso

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAE_SCRIPTS = REPO_ROOT / "SCAE" / "scripts"
if str(SCAE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCAE_SCRIPTS))

from scae.persistence import write_scae_market_prediction  # noqa: E402


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_ref(*parts: Any) -> str:
    payload = ":".join(_canonical_json(part) if isinstance(part, (dict, list, tuple)) else str(part) for part in parts)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_age_seconds(source_fetched_at: str, forecast_timestamp: str) -> float:
    return (_parse_timestamp(forecast_timestamp) - _parse_timestamp(source_fetched_at)).total_seconds()


def _probability_from_snapshot(market: sqlite3.Row, snapshot: sqlite3.Row) -> tuple[float, str]:
    bid = snapshot["best_bid"]
    ask = snapshot["best_ask"]
    if bid is not None and ask is not None:
        return round((float(bid) + float(ask)) / 2, 6), "bid_ask_midpoint"
    for column, method in (
        ("yes_price", "yes_price"),
        ("last_price", "last_price"),
    ):
        if snapshot[column] is not None:
            return round(float(snapshot[column]), 6), method
    if market["current_price"] is not None:
        return round(float(market["current_price"]), 6), "current_price"
    return 0.5, "canary_default"


def _fetch_market_and_snapshot(conn: sqlite3.Connection, lease: dict[str, Any]) -> tuple[sqlite3.Row, sqlite3.Row]:
    market = conn.execute(
        """
        SELECT id, platform, external_market_id, title, current_price
        FROM markets
        WHERE id = ?
        """,
        (lease["market_id"],),
    ).fetchone()
    if market is None:
        raise RuntimeError(f"missing market row for canary lease: {lease['market_id']}")
    snapshot = conn.execute(
        """
        SELECT id, observed_at, best_bid, best_ask, yes_price, last_price, raw_payload
        FROM market_snapshots
        WHERE id = ? AND market_id = ?
        """,
        (lease["selected_snapshot_id"], lease["market_id"]),
    ).fetchone()
    if snapshot is None:
        raise RuntimeError(f"missing selected snapshot row for canary lease: {lease['selected_snapshot_id']}")
    return market, snapshot


def _base_stage_result(stage: str, lease: dict[str, Any], *, metadata: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = f"ads-canary-artifact:{stage}:{lease['case_id']}"
    validation_ref = f"ads-canary-validation:{stage}:{_sha256_ref(stage, lease['case_id'])[-16:]}"
    return StageHandlerResult(
        output_artifact_refs=(artifact_ref,),
        validation_result_refs=(validation_ref,),
        safe_metadata={
            "stage": stage,
            "handler_scope": "scoreable_operational_canary",
            "case_id": lease["case_id"],
            **metadata,
        },
    ).to_record(stage)


def _build_scae_ledger(
    lease: dict[str, Any],
    *,
    pipeline_run_id: str,
    forecast_timestamp: str,
    probability: float,
    ordinal: int,
) -> dict[str, Any]:
    return {
        "case_id": lease["case_id"],
        "case_key": lease["case_key"],
        "dispatch_id": lease["dispatch_id"],
        "run_id": pipeline_run_id,
        "forecast_timestamp": forecast_timestamp,
        "forecast_validity_status": "valid_for_forecast",
        "execution_authority_status": "normal_execution_allowed",
        "final_probability_fields_status": "final_probability_fields_ready",
        "production_forecast_prob": probability,
        "canonical_probability": probability,
        "writes_persistence": False,
        "writes_production_forecast": False,
        "scae_valid_forecast_requires_evidence_delta_refs": True,
        "scae_evidence_delta_ref_requirement_status": "satisfied",
        "scae_evidence_delta_ref_count": 1,
        "scae_evidence_delta_refs": [f"scae-evidence-delta:ads-canary:{ordinal}:{lease['case_id']}"],
        "scoreable_forecast_output": True,
        "market_prediction_write_expected": True,
        "final_probability_ledger_id": f"scae-final-probability-ledger:ads-canary:{ordinal}:{lease['case_id']}",
        "final_probability_ledger_digest": _sha256_ref("ads-canary-ledger", ordinal, lease["case_id"], probability),
    }


def _build_decision_gate(ledger: dict[str, Any], *, ordinal: int) -> dict[str, Any]:
    case_id = ledger["case_id"]
    return {
        "artifact_type": "decision_execution_gate",
        "feature_id": "DEC-001",
        "decision_gate_id": f"decision-gate:ads-canary:{ordinal}:{case_id}",
        "decision_gate_digest": _sha256_ref("ads-canary-decision-gate", ordinal, case_id),
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
        "forecast_validity_status": ledger["forecast_validity_status"],
        "execution_authority_status": ledger["execution_authority_status"],
        "actionability_status": "actionable",
        "scae_context": {
            "scae_ledger_ref": ledger["final_probability_ledger_id"],
            "scae_ledger_digest": ledger["final_probability_ledger_digest"],
            "case_id": case_id,
            "case_key": ledger["case_key"],
            "dispatch_id": ledger["dispatch_id"],
            "run_id": ledger["run_id"],
            "forecast_timestamp": ledger["forecast_timestamp"],
            "forecast_validity_status": ledger["forecast_validity_status"],
            "execution_authority_status": ledger["execution_authority_status"],
            "production_forecast_prob": ledger["production_forecast_prob"],
            "canonical_probability": ledger["canonical_probability"],
            "probability_source": "SCAE-012_final_probability_fields",
        },
        "synthesis_context": {
            "synthesis_annotation_ref": f"synthesis-annotation:ads-canary:{ordinal}:{case_id}",
            "synthesis_annotation_digest": _sha256_ref("ads-canary-synthesis", ordinal, case_id),
        },
    }


def _build_ads_case_contract(
    lease: dict[str, Any],
    market: sqlite3.Row,
    snapshot: sqlite3.Row,
    *,
    forecast_timestamp: str,
    probability: float,
    probability_method: str,
    ordinal: int,
) -> dict[str, Any]:
    source_payload = snapshot["raw_payload"] or _canonical_json(
        {
            "snapshot_id": snapshot["id"],
            "observed_at": snapshot["observed_at"],
            "best_bid": snapshot["best_bid"],
            "best_ask": snapshot["best_ask"],
            "yes_price": snapshot["yes_price"],
            "last_price": snapshot["last_price"],
        }
    )
    snapshot_age = _snapshot_age_seconds(snapshot["observed_at"], forecast_timestamp)
    return {
        "artifact_type": "ads_case_contract",
        "schema_version": "ads-case-contract/v1",
        "case_key": lease["case_key"],
        "case_id": lease["case_id"],
        "dispatch_id": lease["dispatch_id"],
        "prediction_run_id": f"prediction-run:ads-canary:{ordinal}:{lease['case_id']}",
        "forecast_artifact_id": f"forecast-artifact:ads-canary:{ordinal}:{lease['case_id']}",
        "forecast_timestamp": forecast_timestamp,
        "intake_source": {
            "market_row_id": lease["market_id"],
            "market_snapshot_id": lease["selected_snapshot_id"],
            "snapshot_observed_at": snapshot["observed_at"],
            "source_payload_hash": _sha256_ref(source_payload),
        },
        "market_identity": {
            "platform": market["platform"],
            "internal_market_id": lease["market_id"],
            "external_market_id": market["external_market_id"],
            "title": market["title"],
        },
        "prediction_time_market_baseline": {
            "market_snapshot_id": lease["selected_snapshot_id"],
            "source_fetched_at": snapshot["observed_at"],
            "snapshot_age_seconds_at_dispatch": snapshot_age,
            "max_snapshot_age_seconds": 3600,
            "market_probability": probability,
            "market_probability_method": probability_method,
            "source_payload_hash": _sha256_ref(source_payload),
        },
    }


def _decision_handler(
    *,
    db_path: Path,
    configured_forecast_timestamp: str | None,
    metadata: dict[str, Any],
    ordinal_state: dict[str, int],
    conn: sqlite3.Connection,
    context: Any,
    lease: dict[str, Any],
    **_kwargs: Any,
) -> dict[str, Any]:
    ordinal_state["value"] += 1
    ordinal = ordinal_state["value"]
    forecast_timestamp = configured_forecast_timestamp or utc_now_iso()
    market, snapshot = _fetch_market_and_snapshot(conn, lease)
    probability, probability_method = _probability_from_snapshot(market, snapshot)
    ledger = _build_scae_ledger(
        lease,
        pipeline_run_id=context.pipeline_run_id,
        forecast_timestamp=forecast_timestamp,
        probability=probability,
        ordinal=ordinal,
    )
    gate = _build_decision_gate(ledger, ordinal=ordinal)
    contract = _build_ads_case_contract(
        lease,
        market,
        snapshot,
        forecast_timestamp=forecast_timestamp,
        probability=probability,
        probability_method=probability_method,
        ordinal=ordinal,
    )
    persistence_metadata = {
        "forecast_decision_artifact_path": f"artifacts/ads-canary/{context.pipeline_run_id}/{ordinal}/forecast-decision.json",
        "scae_ledger_artifact_path": f"artifacts/ads-canary/{context.pipeline_run_id}/{ordinal}/scae-ledger.json",
        "handler_scope": "scoreable_operational_canary",
        "canary_probability_source": f"selected_snapshot_{probability_method}",
        **metadata,
    }
    persisted = write_scae_market_prediction(
        db_path,
        ledger,
        gate,
        contract,
        metadata=persistence_metadata,
    )
    result = _base_stage_result("decision", lease, metadata=metadata)
    result["forecast_decision_record_id"] = persisted["forecast_decision_id"]
    result["forecast_artifact_id"] = persisted.get("forecast_artifact_id")
    if persisted.get("prediction_id") is not None:
        result["market_prediction_id"] = str(persisted["prediction_id"])
    result["safe_metadata"] = {
        **result["safe_metadata"],
        "market_prediction_written": bool(persisted["market_prediction_written"]),
        "scoreable_forecast_output": bool(persisted["scoreable_forecast_output"]),
        "canary_probability_source": f"selected_snapshot_{probability_method}",
    }
    return result


def build_stage_handlers(
    *,
    db_path: Path | str,
    runner_mode: str,
    forecast_timestamp: str | None = None,
    max_cases: int = 1,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Callable[..., dict[str, Any]]]:
    del runner_mode, max_cases
    db_path = Path(db_path)
    safe_metadata = {
        "handler_factory": "predquant.ads_scoreable_canary_handlers",
        **(metadata or {}),
    }
    ordinal_state = {"value": 0}

    def make_handler(stage: str) -> Callable[..., dict[str, Any]]:
        def handler(**kwargs: Any) -> dict[str, Any]:
            lease = kwargs["lease"]
            if stage == "decision":
                return _decision_handler(
                    db_path=db_path,
                    configured_forecast_timestamp=forecast_timestamp,
                    metadata=safe_metadata,
                    ordinal_state=ordinal_state,
                    **kwargs,
                )
            return _base_stage_result(stage, lease, metadata=safe_metadata)

        return handler

    return {stage: make_handler(stage) for stage in ADS_PIPELINE_STAGE_ORDER[1:]}
