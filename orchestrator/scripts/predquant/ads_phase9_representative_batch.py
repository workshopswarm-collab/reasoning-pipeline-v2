"""Phase 9 representative clone-batch report helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PHASE9_REPRESENTATIVE_BATCH_SCHEMA_VERSION = "ads-phase9-representative-batch/v1"
DEFAULT_REQUIRED_REPRESENTATIVE_TAGS = (
    "boi_central_bank_rate_decision",
    "protected_primary_binary_market",
    "market_family_sibling_context",
    "unresolved_pre_resolution_qdt",
)
DEFAULT_MAX_RETRY_ATTEMPTS_PER_CASE = 24
DEFAULT_MAX_RETRY_BACKOFF_SECONDS = 300
BLOCKED_CLASSIFICATIONS = {
    "structured_non_scoreable_insufficiency",
    "structural_unanswerability",
}
ALLOWED_RETRY_EXHAUSTED_CLASSIFICATIONS = BLOCKED_CLASSIFICATIONS | {"retryable_stage_failure"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number_list(value: Any) -> list[float]:
    result = []
    for item in _as_list(value):
        if isinstance(item, (int, float)):
            result.append(float(item))
    return result


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item not in (None, "")]


def _report_from_case_spec(case_spec: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(
        case_spec.get("real_runtime_report")
        or case_spec.get("report")
        or case_spec.get("real_runtime_canary_report")
        or case_spec
    )


def _retry_summary(report: dict[str, Any], phase9_case: dict[str, Any]) -> dict[str, Any]:
    for value in (
        report.get("retry_summary"),
        phase9_case.get("retry_summary"),
        _as_dict(report.get("current_audit_gap_summary")).get("retry_summary"),
    ):
        if isinstance(value, dict):
            return value
    return {
        "retry_attempt_count": 0,
        "retryable_failure_count": 0,
        "non_retryable_failure_count": 0,
        "terminal_retry_exhausted_count": 0,
        "stage_retry_scheduled_count": 0,
        "qdt_model_transport_retry_count": 0,
        "retry_backoff_seconds": [],
        "retry_policy_refs": [],
        "components": [],
        "final_retry_outcome": "no_retries_recorded",
    }


def load_phase9_case_spec(path: Path | str) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"phase9 case report must be a JSON object: {path}")
    loaded.setdefault("source_path", str(path))
    return loaded


def build_phase9_case_summary(
    case_spec: dict[str, Any],
    *,
    case_index: int,
    max_retry_attempts_per_case: int = DEFAULT_MAX_RETRY_ATTEMPTS_PER_CASE,
    max_retry_backoff_seconds: int = DEFAULT_MAX_RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    report = _report_from_case_spec(case_spec)
    phase9_case = _as_dict(report.get("phase9_representative_case"))
    prediction_delta = _as_dict(report.get("prediction_delta_evidence"))
    active_work = _as_dict(report.get("active_work"))
    handoff = _as_dict(report.get("handoff_report"))
    retry = _retry_summary(report, phase9_case)
    classification = str(phase9_case.get("classification") or "missing_phase9_classification")
    scoreable_requirements = _as_dict(phase9_case.get("scoreable_success_requirements"))
    tags = _string_list(case_spec.get("representative_tags") or phase9_case.get("representative_tags"))
    live_db_mutation = str(report.get("live_db_mutation") or phase9_case.get("live_db_mutation") or "unknown_or_live")
    clone_only = (
        live_db_mutation == "clone_only"
        and report.get("clone_only") is True
        and phase9_case.get("clone_only") is True
    )
    retry_backoff_seconds = _number_list(retry.get("retry_backoff_seconds"))
    retry_attempt_count = _int_value(retry.get("retry_attempt_count"))
    retry_bounded = (
        retry_attempt_count <= max_retry_attempts_per_case
        and all(value <= max_retry_backoff_seconds for value in retry_backoff_seconds)
    )
    retry_exhausted_count = _int_value(retry.get("terminal_retry_exhausted_count"))
    retry_exhausted_explicit = retry_exhausted_count == 0 or classification in ALLOWED_RETRY_EXHAUSTED_CLASSIFICATIONS
    blocked_case = classification in BLOCKED_CLASSIFICATIONS
    no_scoreable_write_when_blocked = bool(phase9_case.get("no_scoreable_write_when_blocked"))
    market_prediction_delta = _int_value(prediction_delta.get("market_predictions_delta"))
    issues = []
    if not tags:
        issues.append("missing_representative_tags")
    if not clone_only:
        issues.append("case_not_explicit_clone_only")
    if classification == "unexpected_failure":
        issues.append("case_unexpected_failure")
    if classification == "scoreable_success":
        if not scoreable_requirements or not all(bool(value) for value in scoreable_requirements.values()):
            issues.append("scoreable_success_requirements_not_passed")
        if market_prediction_delta <= 0:
            issues.append("scoreable_success_market_prediction_missing")
    if blocked_case and not no_scoreable_write_when_blocked:
        issues.append("blocked_case_wrote_scoreable_prediction")
    if _int_value(active_work.get("active_runs")) or _int_value(active_work.get("active_leases")):
        issues.append("active_work_not_drained")
    if handoff.get("ok") is not True:
        issues.append("handoff_unresolved")
    if not retry_bounded:
        issues.append("retry_attempts_or_backoff_exceed_policy")
    if not retry_exhausted_explicit:
        issues.append("retry_exhausted_not_explicit")
    if blocked_case and market_prediction_delta:
        issues.append("blocked_case_market_prediction_delta_nonzero")
    return {
        "case_index": case_index,
        "selector": case_spec.get("selector") or phase9_case.get("selector") or report.get("pipeline_run_id"),
        "source_path": case_spec.get("source_path"),
        "pipeline_run_id": report.get("pipeline_run_id"),
        "classification": classification,
        "reason_codes": sorted(set(_string_list(phase9_case.get("reason_codes")))),
        "representative_tags": sorted(set(tags)),
        "live_db_mutation": live_db_mutation,
        "clone_only": clone_only,
        "no_scoreable_write_when_blocked": no_scoreable_write_when_blocked,
        "scoreable_success_requirements": scoreable_requirements,
        "market_predictions_delta": market_prediction_delta,
        "active_work": {
            "active_runs": _int_value(active_work.get("active_runs")),
            "active_leases": _int_value(active_work.get("active_leases")),
        },
        "handoff_ok": handoff.get("ok") is True,
        "retry_summary": retry,
        "retry_attempt_count": retry_attempt_count,
        "retry_backoff_seconds": retry_backoff_seconds,
        "retry_bounded": retry_bounded,
        "retry_exhausted_explicit": retry_exhausted_explicit,
        "issues": sorted(set(issues)),
    }


def build_phase9_representative_batch_report(
    case_specs: list[dict[str, Any]],
    *,
    required_representative_tags: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_REPRESENTATIVE_TAGS,
    min_case_count: int = 4,
    max_retry_attempts_per_case: int = DEFAULT_MAX_RETRY_ATTEMPTS_PER_CASE,
    max_retry_backoff_seconds: int = DEFAULT_MAX_RETRY_BACKOFF_SECONDS,
) -> dict[str, Any]:
    case_summaries = [
        build_phase9_case_summary(
            case_spec,
            case_index=index,
            max_retry_attempts_per_case=max_retry_attempts_per_case,
            max_retry_backoff_seconds=max_retry_backoff_seconds,
        )
        for index, case_spec in enumerate(case_specs, start=1)
    ]
    classification_counts = {
        classification: sum(1 for item in case_summaries if item["classification"] == classification)
        for classification in sorted({item["classification"] for item in case_summaries})
    }
    covered_tags = sorted({tag for item in case_summaries for tag in item["representative_tags"]})
    missing_tags = sorted(set(required_representative_tags) - set(covered_tags))
    issues = []
    if len(case_summaries) < min_case_count:
        issues.append("representative_batch_too_small")
    if missing_tags:
        issues.append("representative_tags_missing")
    if not any(item["classification"] == "scoreable_success" for item in case_summaries):
        issues.append("missing_scoreable_success")
    if any(item["classification"] == "unexpected_failure" for item in case_summaries):
        issues.append("unexpected_failure_case")
    if any(not item["clone_only"] for item in case_summaries):
        issues.append("non_clone_only_case")
    if any("blocked_case_wrote_scoreable_prediction" in item["issues"] for item in case_summaries):
        issues.append("blocked_case_wrote_scoreable_prediction")
    if any("blocked_case_market_prediction_delta_nonzero" in item["issues"] for item in case_summaries):
        issues.append("blocked_case_market_prediction_delta_nonzero")
    if any("scoreable_success_requirements_not_passed" in item["issues"] for item in case_summaries):
        issues.append("scoreable_success_requirements_not_passed")
    if any("scoreable_success_market_prediction_missing" in item["issues"] for item in case_summaries):
        issues.append("scoreable_success_market_prediction_missing")
    if any(item["active_work"]["active_runs"] or item["active_work"]["active_leases"] for item in case_summaries):
        issues.append("active_work_not_drained")
    if any(not item["handoff_ok"] for item in case_summaries):
        issues.append("handoff_unresolved")
    if any(not item["retry_bounded"] for item in case_summaries):
        issues.append("retry_attempts_or_backoff_exceed_policy")
    if any(not item["retry_exhausted_explicit"] for item in case_summaries):
        issues.append("retry_exhausted_not_explicit")
    return {
        "schema_version": PHASE9_REPRESENTATIVE_BATCH_SCHEMA_VERSION,
        "ok": not issues,
        "status": "passed" if not issues else "blocked",
        "issues": sorted(set(issues)),
        "case_count": len(case_summaries),
        "min_case_count": min_case_count,
        "required_representative_tags": list(required_representative_tags),
        "covered_representative_tags": covered_tags,
        "missing_representative_tags": missing_tags,
        "classification_counts": classification_counts,
        "scoreable_success_count": classification_counts.get("scoreable_success", 0),
        "unexpected_failure_count": classification_counts.get("unexpected_failure", 0),
        "clone_only_case_count": sum(1 for item in case_summaries if item["clone_only"]),
        "blocked_case_count": sum(1 for item in case_summaries if item["classification"] in BLOCKED_CLASSIFICATIONS),
        "retry_policy": {
            "max_retry_attempts_per_case": max_retry_attempts_per_case,
            "max_retry_backoff_seconds": max_retry_backoff_seconds,
        },
        "case_summaries": case_summaries,
    }


__all__ = [
    "DEFAULT_REQUIRED_REPRESENTATIVE_TAGS",
    "PHASE9_REPRESENTATIVE_BATCH_SCHEMA_VERSION",
    "build_phase9_case_summary",
    "build_phase9_representative_batch_report",
    "load_phase9_case_spec",
]
