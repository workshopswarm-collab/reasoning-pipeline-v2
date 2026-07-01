"""ADS source-retrieval Phase 10 clone-batch closure helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SOURCE_RETRIEVAL_PHASE10_CLOSURE_SCHEMA_VERSION = "ads-source-retrieval-phase10-closure/v1"
SOURCE_RETRIEVAL_PHASE10_CLEANUP_PROOF_SCHEMA_VERSION = "ads-source-retrieval-phase10-cleanup-proof/v1"
DEFAULT_REQUIRED_REPRESENTATIVE_TAGS = (
    "boi_central_bank_rate_decrease",
    "central_bank_macro_policy",
    "non_central_bank_source_adapter",
    "valid_non_scoreable_insufficiency",
)
BLOCKED_CLASSIFICATIONS = {
    "structured_non_scoreable_insufficiency",
    "structural_unanswerability",
}
SCOREABLE_CLASSIFICATION = "scoreable_success"


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


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if item not in (None, "")]


def _report_from_case_spec(case_spec: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(
        case_spec.get("real_runtime_report")
        or case_spec.get("report")
        or case_spec.get("real_runtime_canary_report")
        or case_spec
    )


def _prediction_delta_evidence(report: dict[str, Any]) -> dict[str, Any]:
    prediction_delta = _as_dict(report.get("prediction_delta_evidence"))
    if prediction_delta:
        return prediction_delta
    health = _as_dict(report.get("pipeline_health_summary"))
    protected = _as_dict(health.get("protected_write_deltas"))
    return protected


def _case_expected_classification(case_spec: dict[str, Any], tags: list[str], classification: str) -> str | None:
    expected = case_spec.get("expected_classification")
    if isinstance(expected, str) and expected:
        return expected
    if "valid_non_scoreable_insufficiency" in tags:
        return "structured_non_scoreable_insufficiency"
    if classification:
        return classification
    return None


def _case_expected_market_predictions(case_spec: dict[str, Any], expected_classification: str | None) -> int:
    for key in ("expected_market_predictions", "expected_market_predictions_delta"):
        if key in case_spec:
            return _int_value(case_spec.get(key))
    return 1 if expected_classification == SCOREABLE_CLASSIFICATION else 0


def _case_expected_forecast_decisions(case_spec: dict[str, Any]) -> int | None:
    for key in ("expected_forecast_decision_records", "expected_forecast_decision_records_delta"):
        if key in case_spec:
            return _int_value(case_spec.get(key))
    return None


def _retrieval_packets(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(retrieval.get("retrieval_packets")) if isinstance(item, dict)]


def _certified_retrieval_leaf_count(retrieval: dict[str, Any], health: dict[str, Any]) -> int:
    health_count = _int_value(health.get("certified_retrieval_leaf_count"))
    if health_count:
        return health_count
    total = 0
    for packet in _retrieval_packets(retrieval):
        total += sum(
            1
            for row in _as_list(packet.get("leaf_retrieval_statuses"))
            if isinstance(row, dict) and row.get("classification_dispatch_allowed") is True
        )
    return total


def _direct_adapter_success_count(retrieval: dict[str, Any]) -> int:
    packet_success = sum(
        1
        for packet in _retrieval_packets(retrieval)
        if _int_value(packet.get("direct_url_candidate_count")) > 0
        or packet.get("direct_url_capture_executed") is True
    )
    return max(packet_success, _int_value(retrieval.get("direct_url_capture_executed_count")))


def _native_provider_counts(retrieval: dict[str, Any]) -> dict[str, int]:
    packets = _retrieval_packets(retrieval)
    success_count = sum(1 for packet in packets if _int_value(packet.get("native_candidate_url_count")) > 0)
    if not success_count:
        success_count = _int_value(retrieval.get("native_candidate_url_count"))
    executed_no_candidates_count = sum(
        1
        for packet in packets
        if packet.get("native_research_model_executed") is True
        and _int_value(packet.get("native_candidate_url_count")) == 0
    )
    executed_count = _int_value(retrieval.get("native_research_model_executed_count")) or sum(
        1 for packet in packets if packet.get("native_research_model_executed") is True
    )
    failure_count = max(0, executed_count - success_count)
    statuses = {
        str(status)
        for status in _as_list(retrieval.get("native_research_statuses"))
        if status not in (None, "")
    }
    statuses.update(
        str(packet.get("native_research_status"))
        for packet in packets
        if packet.get("native_research_status") not in (None, "")
    )
    safe_failure_count = executed_no_candidates_count if statuses else 0
    return {
        "native_provider_success_count": success_count,
        "native_provider_failure_count": failure_count,
        "native_provider_safe_failure_count": safe_failure_count,
        "native_provider_unclassified_failure_count": failure_count - safe_failure_count,
    }


def load_phase10_case_spec(path: Path | str) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"phase10 case report must be a JSON object: {path}")
    loaded.setdefault("source_path", str(path))
    return loaded


def build_phase10_case_summary(case_spec: dict[str, Any], *, case_index: int) -> dict[str, Any]:
    report = _report_from_case_spec(case_spec)
    phase9_case = _as_dict(report.get("phase9_representative_case"))
    qdt = _as_dict(report.get("model_runtime_evidence"))
    taxonomy = _as_dict(report.get("source_retrieval_pipeline_health_taxonomy"))
    retrieval = _as_dict(report.get("retrieval_runtime_evidence"))
    researcher = _as_dict(report.get("researcher_runtime_evidence"))
    scae = _as_dict(report.get("scae_runtime_evidence"))
    health = _as_dict(report.get("pipeline_health_summary"))
    active_work = _as_dict(report.get("active_work"))
    handoff = _as_dict(report.get("handoff_report"))
    prediction_delta = _prediction_delta_evidence(report)

    tags = sorted(set(_string_list(case_spec.get("representative_tags") or phase9_case.get("representative_tags"))))
    classification = str(phase9_case.get("classification") or case_spec.get("classification") or "missing_classification")
    expected_classification = _case_expected_classification(case_spec, tags, classification)
    expected_market_predictions = _case_expected_market_predictions(case_spec, expected_classification)
    expected_forecast_decisions = _case_expected_forecast_decisions(case_spec)
    live_db_mutation = str(report.get("live_db_mutation") or phase9_case.get("live_db_mutation") or "unknown_or_live")
    clone_only = live_db_mutation == "clone_only" and report.get("clone_only") is True and phase9_case.get("clone_only") is True

    qdt_live_accepted_count = max(
        _int_value(qdt.get("qdt_live_output_accepted_count")),
        _int_value(taxonomy.get("qdt_live_output_accepted_count")),
    )
    native_counts = _native_provider_counts(retrieval)
    official_direct_adapter_success_count = _direct_adapter_success_count(retrieval)
    certified_retrieval_leaf_count = _certified_retrieval_leaf_count(retrieval, health)
    classification_slice_count = max(
        _int_value(researcher.get("classification_slice_count")),
        _int_value(health.get("classification_slice_count")),
    )
    scae_valid_forecast_count = _int_value(scae.get("valid_forecast_count"))
    scae_ledger_count = _int_value(scae.get("ledger_count"))
    scae_invalid_forecast_count = max(0, scae_ledger_count - scae_valid_forecast_count)
    forecast_delta = _int_value(prediction_delta.get("forecast_decision_records_delta"))
    market_prediction_delta = _int_value(prediction_delta.get("market_predictions_delta"))

    issues: list[str] = []
    if not tags:
        issues.append("missing_representative_tags")
    if not clone_only:
        issues.append("case_not_explicit_clone_only")
    if qdt_live_accepted_count <= 0:
        issues.append("qdt_live_acceptance_missing")
    if classification == "unexpected_failure":
        issues.append("case_unexpected_failure")
    if expected_classification and classification != expected_classification:
        issues.append("case_classification_mismatch")
    if expected_classification == SCOREABLE_CLASSIFICATION:
        if certified_retrieval_leaf_count <= 0:
            issues.append("scoreable_case_missing_certified_retrieval")
        if classification_slice_count <= 0:
            issues.append("scoreable_case_missing_researcher_classification")
        if scae_valid_forecast_count <= 0:
            issues.append("scoreable_case_missing_valid_scae")
    if expected_classification in BLOCKED_CLASSIFICATIONS and market_prediction_delta:
        issues.append("blocked_case_market_prediction_delta_nonzero")
    if market_prediction_delta != expected_market_predictions:
        issues.append("market_prediction_delta_mismatch")
    if expected_forecast_decisions is not None and forecast_delta != expected_forecast_decisions:
        issues.append("forecast_decision_delta_mismatch")
    if _int_value(active_work.get("active_runs")) or _int_value(active_work.get("active_leases")):
        issues.append("active_work_not_drained")
    if handoff and handoff.get("ok") is not True:
        issues.append("handoff_unresolved")
    if native_counts["native_provider_unclassified_failure_count"] > 0:
        issues.append("native_provider_failure_without_safe_status")

    return {
        "case_index": case_index,
        "selector": case_spec.get("selector") or phase9_case.get("selector") or report.get("pipeline_run_id"),
        "source_path": case_spec.get("source_path"),
        "pipeline_run_id": report.get("pipeline_run_id"),
        "classification": classification,
        "expected_classification": expected_classification,
        "reason_codes": sorted(set(_string_list(phase9_case.get("reason_codes")))),
        "representative_tags": tags,
        "live_db_mutation": live_db_mutation,
        "clone_only": clone_only,
        "qdt_live_accepted_count": qdt_live_accepted_count,
        "official_direct_adapter_success_count": official_direct_adapter_success_count,
        "certified_retrieval_leaf_count": certified_retrieval_leaf_count,
        "researcher_classification_slice_count": classification_slice_count,
        "scae_valid_forecast_count": scae_valid_forecast_count,
        "scae_invalid_forecast_count": scae_invalid_forecast_count,
        "protected_write_deltas": {
            "forecast_decision_records_delta": forecast_delta,
            "market_predictions_delta": market_prediction_delta,
            "expected_forecast_decision_records_delta": expected_forecast_decisions,
            "expected_market_predictions_delta": expected_market_predictions,
        },
        "active_work": {
            "active_runs": _int_value(active_work.get("active_runs")),
            "active_leases": _int_value(active_work.get("active_leases")),
        },
        "handoff_ok": not handoff or handoff.get("ok") is True,
        **native_counts,
        "issues": sorted(set(issues)),
    }


def _cleanup_summary(cleanup_proof: dict[str, Any] | None) -> dict[str, Any]:
    proof = _as_dict(cleanup_proof)
    issues: list[str] = []
    if not proof:
        issues.append("cleanup_proof_missing")
    temp_dirs_removed = proof.get("temp_dirs_removed") is True
    generated_artifacts_staged = proof.get("generated_artifacts_staged") is True
    one_off_scripts_deleted = proof.get("one_off_scripts_deleted") is True
    live_db_mutation_detected = proof.get("live_db_mutation_detected") is True
    active_runs_left = _int_value(proof.get("active_runs_left"))
    active_leases_left = _int_value(proof.get("active_leases_left"))
    if proof and not temp_dirs_removed:
        issues.append("temp_dirs_not_removed")
    if generated_artifacts_staged:
        issues.append("generated_artifacts_staged")
    if proof and not one_off_scripts_deleted:
        issues.append("one_off_scripts_not_deleted")
    if live_db_mutation_detected:
        issues.append("live_db_mutation_detected")
    if active_runs_left or active_leases_left:
        issues.append("active_work_left_after_batch")
    return {
        "schema_version": SOURCE_RETRIEVAL_PHASE10_CLEANUP_PROOF_SCHEMA_VERSION,
        "ok": not issues,
        "issues": sorted(set(issues)),
        "temp_dirs_removed": temp_dirs_removed,
        "generated_artifacts_staged": generated_artifacts_staged,
        "one_off_scripts_deleted": one_off_scripts_deleted,
        "live_db_mutation_detected": live_db_mutation_detected,
        "active_runs_left": active_runs_left,
        "active_leases_left": active_leases_left,
    }


def build_source_retrieval_phase10_closure_report(
    case_specs: list[dict[str, Any]],
    *,
    cleanup_proof: dict[str, Any] | None = None,
    required_representative_tags: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_REPRESENTATIVE_TAGS,
    min_case_count: int = 4,
) -> dict[str, Any]:
    case_summaries = [
        build_phase10_case_summary(case_spec, case_index=index)
        for index, case_spec in enumerate(case_specs, start=1)
    ]
    cleanup = _cleanup_summary(cleanup_proof)
    classification_counts = {
        classification: sum(1 for item in case_summaries if item["classification"] == classification)
        for classification in sorted({item["classification"] for item in case_summaries})
    }
    covered_tags = sorted({tag for item in case_summaries for tag in item["representative_tags"]})
    missing_tags = sorted(set(required_representative_tags) - set(covered_tags))
    protected_write_delta_summary = {
        "forecast_decision_records_delta": sum(
            int(item["protected_write_deltas"]["forecast_decision_records_delta"])
            for item in case_summaries
        ),
        "market_predictions_delta": sum(
            int(item["protected_write_deltas"]["market_predictions_delta"])
            for item in case_summaries
        ),
        "expected_market_predictions_delta": sum(
            int(item["protected_write_deltas"]["expected_market_predictions_delta"])
            for item in case_summaries
        ),
    }
    aggregate_counters = {
        "qdt_live_accepted_count": sum(int(item["qdt_live_accepted_count"]) for item in case_summaries),
        "native_provider_success_count": sum(int(item["native_provider_success_count"]) for item in case_summaries),
        "native_provider_failure_count": sum(int(item["native_provider_failure_count"]) for item in case_summaries),
        "native_provider_safe_failure_count": sum(int(item["native_provider_safe_failure_count"]) for item in case_summaries),
        "official_direct_adapter_success_count": sum(
            int(item["official_direct_adapter_success_count"]) for item in case_summaries
        ),
        "certified_retrieval_leaf_count": sum(
            int(item["certified_retrieval_leaf_count"]) for item in case_summaries
        ),
        "researcher_classification_slice_count": sum(
            int(item["researcher_classification_slice_count"]) for item in case_summaries
        ),
        "scae_valid_forecast_count": sum(int(item["scae_valid_forecast_count"]) for item in case_summaries),
        "scae_invalid_forecast_count": sum(int(item["scae_invalid_forecast_count"]) for item in case_summaries),
    }
    issues: list[str] = []
    if len(case_summaries) < min_case_count:
        issues.append("representative_batch_too_small")
    if missing_tags:
        issues.append("representative_tags_missing")
    if classification_counts.get(SCOREABLE_CLASSIFICATION, 0) <= 0:
        issues.append("missing_scoreable_success")
    if classification_counts.get("structured_non_scoreable_insufficiency", 0) <= 0:
        issues.append("missing_valid_non_scoreable_insufficiency")
    if classification_counts.get("unexpected_failure", 0) > 0:
        issues.append("unexpected_failure_case")
    if any(not item["clone_only"] for item in case_summaries):
        issues.append("non_clone_only_case")
    if any(item["issues"] for item in case_summaries):
        issues.append("case_issues_present")
    if aggregate_counters["qdt_live_accepted_count"] <= 0:
        issues.append("no_qdt_live_accepted")
    if aggregate_counters["official_direct_adapter_success_count"] <= 0:
        issues.append("no_official_direct_adapter_success")
    if aggregate_counters["certified_retrieval_leaf_count"] <= 0:
        issues.append("no_certified_retrieval_leaves")
    if aggregate_counters["researcher_classification_slice_count"] <= 0:
        issues.append("no_researcher_classification_slices")
    if protected_write_delta_summary["market_predictions_delta"] != protected_write_delta_summary["expected_market_predictions_delta"]:
        issues.append("protected_market_prediction_delta_mismatch")
    if not cleanup["ok"]:
        issues.extend(f"cleanup:{issue}" for issue in cleanup["issues"])

    return {
        "schema_version": SOURCE_RETRIEVAL_PHASE10_CLOSURE_SCHEMA_VERSION,
        "ok": not issues,
        "status": "passed" if not issues else "blocked",
        "issues": sorted(set(issues)),
        "case_count": len(case_summaries),
        "min_case_count": min_case_count,
        "required_representative_tags": list(required_representative_tags),
        "covered_representative_tags": covered_tags,
        "missing_representative_tags": missing_tags,
        "classification_counts": classification_counts,
        "aggregate_counters": aggregate_counters,
        "protected_write_delta_summary": protected_write_delta_summary,
        "cleanup_proof": cleanup,
        "case_summaries": case_summaries,
    }


__all__ = [
    "DEFAULT_REQUIRED_REPRESENTATIVE_TAGS",
    "SOURCE_RETRIEVAL_PHASE10_CLEANUP_PROOF_SCHEMA_VERSION",
    "SOURCE_RETRIEVAL_PHASE10_CLOSURE_SCHEMA_VERSION",
    "build_phase10_case_summary",
    "build_source_retrieval_phase10_closure_report",
    "load_phase10_case_spec",
]
