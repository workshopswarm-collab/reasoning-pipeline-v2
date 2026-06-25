"""CAL-001 explicit calibration-debt clearance gate contract."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sqlite_store import (
    CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    brier_score_report,
    ensure_schema,
)


CAL001_CLEARANCE_SCHEMA_VERSION = "cal-001-calibration-debt-clearance/v1"
CAL001_FEATURE_ID = "CAL-001"
CAL001_STATUS_CLEARED = "cleared"
CAL001_STATUS_BLOCKED = "blocked"

GATE_FIRST100_TRACE_COMPLETENESS = "first100_trace_completeness"
GATE_SCORECARD_BRIER_EVIDENCE = "scorecard_brier_evidence"
GATE_TAIL_SLICE_DIAGNOSTICS = "tail_slice_diagnostics"
GATE_REGIME_DIAGNOSTICS = "regime_diagnostics"
GATE_PROTECTED_COMPONENT_DIAGNOSTICS = "protected_component_diagnostics"
GATE_POINTER_STABILITY = "pointer_stability"

REQUIRED_CLEARANCE_GATES = (
    GATE_FIRST100_TRACE_COMPLETENESS,
    GATE_SCORECARD_BRIER_EVIDENCE,
    GATE_TAIL_SLICE_DIAGNOSTICS,
    GATE_REGIME_DIAGNOSTICS,
    GATE_PROTECTED_COMPONENT_DIAGNOSTICS,
    GATE_POINTER_STABILITY,
)

CAL001_ALLOWED_USES = (
    "calibration_debt_clearance_audit",
    "session6_evaluator_tuning_handoff",
)
CAL001_FORBIDDEN_USES = (
    "production_forecast_write",
    "scae_probability_rewrite",
    "calibration_policy_promotion",
    "base_policy_rewrite",
)


class CalibrationDebtClearanceError(ValueError):
    """Raised when a CAL-001 clearance report is malformed or over-authoritative."""


@dataclass(frozen=True)
class CalibrationDebtClearancePolicy:
    min_resolved_cases: int = 100
    min_scorecards: int | None = None
    min_tail_slice_cases: int = 10
    min_regime_slices: int = 1
    min_protected_component_slices: int = 1
    min_pointer_stability_windows: int = 1
    max_tail_absolute_calibration_error: float = 0.10
    max_log_loss_degradation: float = 0.0
    max_protected_component_degradation: float = 0.0

    def required_scorecards(self) -> int:
        return self.min_resolved_cases if self.min_scorecards is None else self.min_scorecards


def _as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(value)


def _status_is_pass(value: Any) -> bool:
    return str(value or "").lower() in {"pass", "passed", "ok", "clear", "cleared"}


def _gate(gate_id: str, passed: bool, reason: str | None, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": "passed" if passed else "blocked",
        "reason": None if passed else reason,
        "evidence": evidence,
    }


def _fetch_scorecard_rows(
    db_path: Path,
    evaluation_cluster_id: str,
) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        return conn.execute(
            """
            SELECT *
            FROM evaluator_scorecards
            WHERE evaluation_cluster_id = ?
            ORDER BY created_at, scorecard_id
            """,
            (evaluation_cluster_id,),
        ).fetchall()
    finally:
        conn.close()


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _scorecard_evidence_gate(
    *,
    db_path: Path,
    policy: CalibrationDebtClearancePolicy,
    prediction_source: str | None,
    prediction_label: str | None,
    evaluation_cluster_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report = brier_score_report(
        db_path,
        prediction_source=prediction_source,
        prediction_label=prediction_label,
        evaluation_cluster_id=evaluation_cluster_id,
    )
    overall = report["overall"]
    scorecards = report["scorecards"]
    scorecard_rows = _fetch_scorecard_rows(db_path, evaluation_cluster_id)

    valid_scorecards = 0
    invalid_reasons: list[str] = []
    required_metadata_fields = (
        "prediction_id",
        "market_snapshot_id",
        "prediction_run_id",
        "forecast_artifact_id",
        "market_probability_method",
        "scoring_version",
        "resolution_source",
        "resolution_payload_hash",
    )
    for row in scorecard_rows:
        row_reasons: list[str] = []
        metadata = _json_object(row["metadata"])
        for field in required_metadata_fields:
            if metadata.get(field) in (None, ""):
                row_reasons.append(f"metadata.{field} missing")
        for field in ("prediction_brier", "market_brier", "log_loss"):
            if row[field] is None:
                row_reasons.append(f"{field} missing")
        if not row["reliability_bucket"]:
            row_reasons.append("reliability_bucket missing")
        if row["diagnostic_status"] not in {"scoreable", "pass", "passed"}:
            row_reasons.append(f"diagnostic_status={row['diagnostic_status']}")
        for authority_field in (
            "production_forecast_write_authority",
            "calibration_policy_promotion_authority",
            "scae_probability_rewrite_authority",
        ):
            if metadata.get(authority_field) is not False:
                row_reasons.append(f"metadata.{authority_field} must be false")
        forbidden_uses = metadata.get("forbidden_uses") or []
        for forbidden in (
            "production_forecast_write",
            "calibration_policy_promotion",
            "scae_probability_rewrite",
        ):
            if forbidden not in forbidden_uses:
                row_reasons.append(f"metadata.forbidden_uses missing {forbidden}")
        if row_reasons:
            invalid_reasons.append(f"{row['scorecard_id']}: " + ", ".join(row_reasons))
        else:
            valid_scorecards += 1

    required_scorecards = policy.required_scorecards()
    resolved_cases = _as_int(overall["scoreable_resolution_records"])
    scored_with_baseline = _as_int(overall["scored_predictions_with_market_baseline"])
    scorecard_count = _as_int(scorecards["scorecards"])
    passed = (
        resolved_cases >= policy.min_resolved_cases
        and scored_with_baseline >= policy.min_resolved_cases
        and scorecard_count >= required_scorecards
        and valid_scorecards >= required_scorecards
        and overall["avg_prediction_brier"] is not None
        and overall["avg_market_brier"] is not None
    )

    reasons = []
    if resolved_cases < policy.min_resolved_cases:
        reasons.append(
            f"scoreable_resolution_records {resolved_cases} < {policy.min_resolved_cases}"
        )
    if scored_with_baseline < policy.min_resolved_cases:
        reasons.append(
            f"scored_predictions_with_market_baseline {scored_with_baseline} < {policy.min_resolved_cases}"
        )
    if scorecard_count < required_scorecards:
        reasons.append(f"scorecards {scorecard_count} < {required_scorecards}")
    if valid_scorecards < required_scorecards:
        reasons.append(f"valid_scorecards {valid_scorecards} < {required_scorecards}")
    if overall["avg_prediction_brier"] is None or overall["avg_market_brier"] is None:
        reasons.append("Brier report lacks prediction and market-baseline averages")
    reasons.extend(invalid_reasons)

    evidence = {
        "resolved_cases": resolved_cases,
        "scored_predictions_with_market_baseline": scored_with_baseline,
        "scorecards": scorecard_count,
        "valid_scorecards": valid_scorecards,
        "scorecard_ids": [row["scorecard_id"] for row in scorecard_rows],
        "avg_prediction_brier": overall["avg_prediction_brier"],
        "avg_market_brier": overall["avg_market_brier"],
        "avg_brier_edge": overall["avg_brier_edge"],
        "scoring_versions": overall["scoring_versions"],
    }
    return _gate(
        GATE_SCORECARD_BRIER_EVIDENCE,
        passed,
        "; ".join(reasons) if reasons else None,
        evidence,
    ), report


def _first100_gate(first100_trace_complete: bool, trace_manifest_count: int | None) -> dict[str, Any]:
    count = _as_int(trace_manifest_count)
    passed = bool(first100_trace_complete) and count >= 100
    reason = None if passed else "first-100 trace/replay manifest completeness is required"
    return _gate(
        GATE_FIRST100_TRACE_COMPLETENESS,
        passed,
        reason,
        {
            "first100_trace_complete": bool(first100_trace_complete),
            "trace_manifest_count": count,
            "sufficiency_note": "trace completeness is required but cannot clear calibration debt by itself",
        },
    )


def _tail_slice_gate(
    diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    policy: CalibrationDebtClearancePolicy,
) -> dict[str, Any]:
    records = list(diagnostics or [])
    total_cases = sum(_as_int(record.get("case_count")) for record in records)
    ace_values = [
        _as_float(record.get("absolute_calibration_error", record.get("max_ace")), 1.0)
        for record in records
    ]
    log_loss_degradations = [
        _as_float(
            record.get("log_loss_degradation", record.get("max_log_loss_degradation")),
            policy.max_log_loss_degradation + 1.0,
        )
        for record in records
    ]
    catastrophic_failures = sum(
        _as_int(record.get("catastrophic_tail_failures")) for record in records
    )
    status_failures = [
        record.get("slice_id", f"tail_slice[{idx}]")
        for idx, record in enumerate(records)
        if not _status_is_pass(record.get("status"))
    ]
    max_ace = max(ace_values) if ace_values else None
    max_log_loss_degradation = (
        max(log_loss_degradations) if log_loss_degradations else None
    )
    passed = (
        bool(records)
        and total_cases >= policy.min_tail_slice_cases
        and max_ace is not None
        and max_ace <= policy.max_tail_absolute_calibration_error
        and max_log_loss_degradation is not None
        and max_log_loss_degradation <= policy.max_log_loss_degradation
        and catastrophic_failures == 0
        and not status_failures
    )
    reasons = []
    if not records:
        reasons.append("tail-slice diagnostics are required")
    if total_cases < policy.min_tail_slice_cases:
        reasons.append(f"tail_slice_cases {total_cases} < {policy.min_tail_slice_cases}")
    if max_ace is None or max_ace > policy.max_tail_absolute_calibration_error:
        reasons.append("tail absolute calibration error exceeds policy")
    if max_log_loss_degradation is None or max_log_loss_degradation > policy.max_log_loss_degradation:
        reasons.append("tail log-loss degradation exceeds policy")
    if catastrophic_failures:
        reasons.append(f"catastrophic_tail_failures {catastrophic_failures} != 0")
    if status_failures:
        reasons.append("tail slices not passed: " + ", ".join(status_failures))
    return _gate(
        GATE_TAIL_SLICE_DIAGNOSTICS,
        passed,
        "; ".join(reasons) if reasons else None,
        {
            "tail_slice_records": len(records),
            "tail_slice_cases": total_cases,
            "max_absolute_calibration_error": max_ace,
            "max_log_loss_degradation": max_log_loss_degradation,
            "catastrophic_tail_failures": catastrophic_failures,
        },
    )


def _regime_gate(
    diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    policy: CalibrationDebtClearancePolicy,
) -> dict[str, Any]:
    records = list(diagnostics or [])
    status_failures = [
        record.get("regime_id", f"regime[{idx}]")
        for idx, record in enumerate(records)
        if not _status_is_pass(record.get("status"))
    ]
    zero_case_regimes = [
        record.get("regime_id", f"regime[{idx}]")
        for idx, record in enumerate(records)
        if _as_int(record.get("case_count")) <= 0
    ]
    passed = (
        len(records) >= policy.min_regime_slices
        and not status_failures
        and not zero_case_regimes
    )
    reasons = []
    if len(records) < policy.min_regime_slices:
        reasons.append(f"regime_slices {len(records)} < {policy.min_regime_slices}")
    if status_failures:
        reasons.append("regime slices not passed: " + ", ".join(status_failures))
    if zero_case_regimes:
        reasons.append("regime slices missing cases: " + ", ".join(zero_case_regimes))
    return _gate(
        GATE_REGIME_DIAGNOSTICS,
        passed,
        "; ".join(reasons) if reasons else None,
        {
            "regime_slices": len(records),
            "regime_ids": [record.get("regime_id") for record in records],
        },
    )


def _protected_component_gate(
    diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    policy: CalibrationDebtClearancePolicy,
) -> dict[str, Any]:
    records = list(diagnostics or [])
    status_failures = [
        record.get("component_id", f"protected_component[{idx}]")
        for idx, record in enumerate(records)
        if not _status_is_pass(record.get("status"))
    ]
    degrading_components = [
        record.get("component_id", f"protected_component[{idx}]")
        for idx, record in enumerate(records)
        if _as_float(record.get("max_brier_degradation", record.get("degradation")), 0.0)
        > policy.max_protected_component_degradation
    ]
    passed = (
        len(records) >= policy.min_protected_component_slices
        and not status_failures
        and not degrading_components
    )
    reasons = []
    if len(records) < policy.min_protected_component_slices:
        reasons.append(
            "protected_component_slices "
            f"{len(records)} < {policy.min_protected_component_slices}"
        )
    if status_failures:
        reasons.append("protected components not passed: " + ", ".join(status_failures))
    if degrading_components:
        reasons.append(
            "protected components degraded: " + ", ".join(degrading_components)
        )
    return _gate(
        GATE_PROTECTED_COMPONENT_DIAGNOSTICS,
        passed,
        "; ".join(reasons) if reasons else None,
        {
            "protected_component_slices": len(records),
            "component_ids": [record.get("component_id") for record in records],
        },
    )


def _pointer_stability_gate(
    evidence: dict[str, Any] | None,
    policy: CalibrationDebtClearancePolicy,
) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        return _gate(
            GATE_POINTER_STABILITY,
            False,
            "pointer stability evidence or explicit blocked status is required",
            {},
        )
    status = str(evidence.get("status") or "").lower()
    stable_windows = _as_int(evidence.get("stable_window_count"))
    active_pointer = evidence.get("active_policy_pointer_ref")
    if status in {"blocked", "failed", "not_passed"}:
        reason = evidence.get("blocked_reason") or evidence.get("reason") or "pointer stability explicitly blocked"
        return _gate(
            GATE_POINTER_STABILITY,
            False,
            f"explicit blocked status: {reason}",
            dict(evidence),
        )
    passed = (
        status in {"pass", "passed", "stable", "cleared"}
        and bool(active_pointer)
        and stable_windows >= policy.min_pointer_stability_windows
    )
    reasons = []
    if status not in {"pass", "passed", "stable", "cleared"}:
        reasons.append("pointer stability status must be passed or blocked")
    if not active_pointer:
        reasons.append("active_policy_pointer_ref is required")
    if stable_windows < policy.min_pointer_stability_windows:
        reasons.append(
            f"stable_window_count {stable_windows} < {policy.min_pointer_stability_windows}"
        )
    return _gate(
        GATE_POINTER_STABILITY,
        passed,
        "; ".join(reasons) if reasons else None,
        dict(evidence),
    )


def build_calibration_debt_clearance_report(
    *,
    db_path: Path,
    first100_trace_complete: bool,
    trace_manifest_count: int | None = None,
    tail_slice_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    regime_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    protected_component_diagnostics: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    pointer_stability_evidence: dict[str, Any] | None = None,
    policy: CalibrationDebtClearancePolicy | None = None,
    prediction_source: str | None = None,
    prediction_label: str | None = None,
    evaluation_cluster_id: str = CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
) -> dict[str, Any]:
    policy = policy or CalibrationDebtClearancePolicy()
    scorecard_gate, score_report = _scorecard_evidence_gate(
        db_path=db_path,
        policy=policy,
        prediction_source=prediction_source,
        prediction_label=prediction_label,
        evaluation_cluster_id=evaluation_cluster_id,
    )
    gates = [
        _first100_gate(first100_trace_complete, trace_manifest_count),
        scorecard_gate,
        _tail_slice_gate(tail_slice_diagnostics, policy),
        _regime_gate(regime_diagnostics, policy),
        _protected_component_gate(protected_component_diagnostics, policy),
        _pointer_stability_gate(pointer_stability_evidence, policy),
    ]
    blocked_reasons = [
        f"{gate['gate_id']}: {gate['reason']}"
        for gate in gates
        if gate["status"] != "passed"
    ]
    clears_debt = not blocked_reasons
    status = CAL001_STATUS_CLEARED if clears_debt else CAL001_STATUS_BLOCKED
    scorecard_refs = scorecard_gate["evidence"].get("scorecard_ids", [])
    report = {
        "schema_version": CAL001_CLEARANCE_SCHEMA_VERSION,
        "feature_id": CAL001_FEATURE_ID,
        "status": status,
        "clears_calibration_debt": clears_debt,
        "gates": gates,
        "blocked_reasons": blocked_reasons,
        "brier_score_report": score_report,
        "session6_handoff": {
            "handoff_type": "session6_evaluator_tuning_input",
            "calibration_debt_status": status,
            "scorecard_refs": scorecard_refs,
            "active_policy_pointer_ref": (
                pointer_stability_evidence or {}
            ).get("active_policy_pointer_ref"),
            "allowed_uses": ["full_trace_materialization", "candidate_policy_evaluation"],
            "forbidden_uses": ["production_forecast_write", "base_policy_rewrite"],
        },
        "allowed_uses": list(CAL001_ALLOWED_USES),
        "forbidden_uses": list(CAL001_FORBIDDEN_USES),
        "production_forecast_write_authority": False,
        "calibration_policy_promotion_authority": False,
        "scae_probability_rewrite_authority": False,
        "live_forecast_authority": False,
    }
    validate_calibration_debt_clearance_report(report)
    return report


def validate_calibration_debt_clearance_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise CalibrationDebtClearanceError("CAL-001 report must be an object")
    if report.get("schema_version") != CAL001_CLEARANCE_SCHEMA_VERSION:
        raise CalibrationDebtClearanceError(
            f"schema_version must be {CAL001_CLEARANCE_SCHEMA_VERSION}"
        )
    if report.get("feature_id") != CAL001_FEATURE_ID:
        raise CalibrationDebtClearanceError("feature_id must be CAL-001")
    if report.get("status") not in {CAL001_STATUS_CLEARED, CAL001_STATUS_BLOCKED}:
        raise CalibrationDebtClearanceError("status must be cleared or blocked")
    for authority_field in (
        "production_forecast_write_authority",
        "calibration_policy_promotion_authority",
        "scae_probability_rewrite_authority",
        "live_forecast_authority",
    ):
        if report.get(authority_field) is not False:
            raise CalibrationDebtClearanceError(f"{authority_field} must be false")
    if any(forbidden in report.get("allowed_uses", []) for forbidden in CAL001_FORBIDDEN_USES):
        raise CalibrationDebtClearanceError("forbidden authority cannot appear in allowed_uses")
    gates = report.get("gates")
    if not isinstance(gates, list):
        raise CalibrationDebtClearanceError("gates must be a list")
    gate_by_id = {gate.get("gate_id"): gate for gate in gates if isinstance(gate, dict)}
    missing_gates = [gate_id for gate_id in REQUIRED_CLEARANCE_GATES if gate_id not in gate_by_id]
    if missing_gates:
        raise CalibrationDebtClearanceError("missing clearance gates: " + ", ".join(missing_gates))
    passed = all(gate_by_id[gate_id].get("status") == "passed" for gate_id in REQUIRED_CLEARANCE_GATES)
    if bool(report.get("clears_calibration_debt")) != passed:
        raise CalibrationDebtClearanceError("clears_calibration_debt must match all hard gate statuses")
    expected_status = CAL001_STATUS_CLEARED if passed else CAL001_STATUS_BLOCKED
    if report.get("status") != expected_status:
        raise CalibrationDebtClearanceError("status must match hard gate result")
