"""RET-003 deterministic retrieval quality scoring over retrieval-packet/v1."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


RETRIEVAL_QUALITY_SLICE_SCHEMA_VERSION = "retrieval-quality-slice/v1"
RETRIEVAL_QUALITY_REPORT_SCHEMA_VERSION = "retrieval-quality-report/v1"
RETRIEVAL_QUALITY_SCORER_VERSION = "ads-ret-003-retrieval-quality/v1"
RETRIEVAL_PACKET_SCHEMA_VERSION = "retrieval-packet/v1"

FORBIDDEN_RETRIEVAL_KEY_FRAGMENTS = (
    "probability",
    "forecast_probability",
    "production_forecast_prob",
    "fair_value",
    "scae_delta",
    "log_odds",
    "synthesis_conclusion",
    "decision_instruction",
)

PRIMARY_SOURCE_CLASSES = {
    "official_or_primary",
    "market_rules_or_resolution_source",
    "market_price_or_orderbook",
}

DEFAULT_QUALITY_POLICY = {
    "empty_penalty": 0.55,
    "thin_penalty": 0.22,
    "stale_penalty": 0.18,
    "unknown_metadata_penalty": 0.16,
    "protected_primary_penalty": 0.28,
    "low_breadth_penalty": 0.18,
    "min_selected_evidence": 2,
    "stale_ratio_threshold": 0.25,
    "unknown_signal_ratio_threshold": 0.0,
}


class RetrievalQualityError(ValueError):
    """Raised when a retrieval quality report cannot be built or validated."""


@dataclass(frozen=True)
class RetrievalQualityValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": RETRIEVAL_QUALITY_SCORER_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _reject_forbidden_keys(value: Any, errors: list[str], path: str = "retrieval_quality") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_RETRIEVAL_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in RET-003 retrieval quality artifacts")
            _reject_forbidden_keys(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_forbidden_keys(child, errors, f"{path}[{idx}]")


def _round_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _compact_reason_codes(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item) and len(item) <= 80 and " " not in item
        for item in value
    )


def _result_by_leaf(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = packet.get("leaf_retrieval_results", [])
    if not isinstance(results, list):
        return {}
    return {result.get("leaf_id"): result for result in results if isinstance(result, dict)}


def _source_metadata_by_ref(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resolutions = packet.get("source_metadata_resolutions", [])
    if not isinstance(resolutions, list):
        return {}
    by_ref: dict[str, dict[str, Any]] = {}
    for resolution in resolutions:
        if not isinstance(resolution, dict):
            continue
        for field in ("resolution_id", "source_metadata_resolution_ref"):
            ref = resolution.get(field)
            if isinstance(ref, str) and ref:
                by_ref[ref] = resolution
    return by_ref


def _protected_primary_failures_by_leaf(packet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    failures = packet.get("protected_primary_access_failures", [])
    if not isinstance(failures, list):
        return {}
    by_leaf: dict[str, list[dict[str, Any]]] = {}
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        leaf_id = failure.get("leaf_id")
        if isinstance(leaf_id, str) and leaf_id:
            by_leaf.setdefault(leaf_id, []).append(failure)
    return by_leaf


def _expected_min_selected(context: dict[str, Any], policy: dict[str, Any]) -> int:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    minimum = int(policy.get("min_selected_evidence", 2))
    for field in (
        "min_independent_source_families",
        "min_independent_claim_families",
        "min_temporally_fresh_sources",
    ):
        value = targets.get(field, 0)
        if isinstance(value, int) and not isinstance(value, bool):
            minimum = max(minimum, value)
    if targets.get("protected_primary_required") is True:
        minimum = max(minimum, 1)
    return minimum


def _selected_evidence(result: dict[str, Any]) -> list[dict[str, Any]]:
    selected = result.get("selected_evidence", [])
    if not isinstance(selected, list):
        return []
    return [item for item in selected if isinstance(item, dict)]


def _omitted_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    omitted = result.get("omitted_candidates", [])
    if not isinstance(omitted, list):
        return []
    return [item for item in omitted if isinstance(item, dict)]


def _source_family_ids(selected: list[dict[str, Any]]) -> set[str]:
    families: set[str] = set()
    for item in selected:
        family_id = item.get("source_family_id")
        if isinstance(family_id, str) and family_id and family_id != "source-family-unknown":
            families.add(family_id)
    return families


def _claim_family_refs(selected: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for item in selected:
        raw_refs = item.get("claim_family_resolution_refs", [])
        if not isinstance(raw_refs, list):
            continue
        for ref in raw_refs:
            if isinstance(ref, str) and ref and "unknown" not in ref:
                refs.add(ref)
    return refs


def _unknown_signal_count(
    selected: list[dict[str, Any]],
    source_metadata_by_ref: dict[str, dict[str, Any]],
) -> int:
    count = 0
    for item in selected:
        if item.get("source_class") == "unknown":
            count += 1
        if item.get("source_family_id") in (None, "", "source-family-unknown"):
            count += 1
        if item.get("independence_status") == "unknown_not_counted":
            count += 1
        if item.get("temporal_gate_status") == "unknown_not_counted":
            count += 1
        resolution = source_metadata_by_ref.get(item.get("source_metadata_resolution_ref"))
        if resolution and (
            resolution.get("source_class") == "unknown"
            or resolution.get("metadata_confidence") == "unknown"
            or resolution.get("temporal_safety_status") == "unknown_not_counted"
        ):
            count += 1
    return count


def _required_source_classes_missing(context: dict[str, Any], selected: list[dict[str, Any]]) -> list[str]:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    required = targets.get("source_class_targets", [])
    if not isinstance(required, list):
        return []
    present = {item.get("source_class") for item in selected}
    missing = [
        item
        for item in required
        if isinstance(item, str) and item != "unknown" and item not in present
    ]
    return sorted(set(missing))


def _protected_primary_admitted(selected: list[dict[str, Any]]) -> bool:
    return any(
        item.get("source_class") in PRIMARY_SOURCE_CLASSES and item.get("temporal_gate_status") == "pass"
        for item in selected
    )


def _breadth_diagnostics(
    context: dict[str, Any],
    selected: list[dict[str, Any]],
    dimensions: dict[str, Any],
) -> list[str]:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    codes: list[str] = []
    if dimensions["required_source_classes_missing"]:
        codes.append("required_source_class_missing")
    if dimensions["source_family_count"] < int(targets.get("min_independent_source_families", 0) or 0):
        codes.append("source_family_breadth_low")
    if dimensions["claim_family_ref_count"] < int(targets.get("min_independent_claim_families", 0) or 0):
        codes.append("claim_family_breadth_low")
    if dimensions["fresh_selected_count"] < int(targets.get("min_temporally_fresh_sources", 0) or 0):
        codes.append("freshness_breadth_low")
    return codes


def _diagnostic(code: str, penalty: float, severity: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "penalty_points": _round_score(penalty),
    }


def score_leaf_retrieval_quality(
    packet: dict[str, Any],
    query_context: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one RET-003 quality slice for a leaf result."""

    if not isinstance(packet, dict) or packet.get("schema_version") != RETRIEVAL_PACKET_SCHEMA_VERSION:
        raise RetrievalQualityError("packet must be retrieval-packet/v1")
    if not isinstance(query_context, dict):
        raise RetrievalQualityError("query_context must be an object")

    merged_policy = {**DEFAULT_QUALITY_POLICY, **(policy or {})}
    result = result or _result_by_leaf(packet).get(query_context.get("leaf_id"), {})
    selected = _selected_evidence(result if isinstance(result, dict) else {})
    omitted = _omitted_candidates(result if isinstance(result, dict) else {})
    leaf_id = str(query_context.get("leaf_id"))
    expected_min = _expected_min_selected(query_context, merged_policy)
    selected_count = len(selected)
    stale_count = sum(1 for item in selected if item.get("temporal_gate_status") == "fail")
    stale_ratio = stale_count / selected_count if selected_count else 0.0
    fresh_count = sum(1 for item in selected if item.get("temporal_gate_status") == "pass")
    source_metadata = _source_metadata_by_ref(packet)
    unknown_count = _unknown_signal_count(selected, source_metadata)
    unknown_denominator = max(1, selected_count * 4)
    unknown_ratio = unknown_count / unknown_denominator
    source_families = _source_family_ids(selected)
    claim_refs = _claim_family_refs(selected)
    protected_failures = _protected_primary_failures_by_leaf(packet).get(leaf_id, [])
    protected_required = bool(
        isinstance(query_context.get("breadth_targets"), dict)
        and query_context["breadth_targets"].get("protected_primary_required") is True
    )
    dimensions = {
        "selected_evidence_count": selected_count,
        "omitted_candidate_count": len(omitted),
        "expected_min_selected_evidence": expected_min,
        "stale_selected_count": stale_count,
        "stale_selected_ratio": _round_score(stale_ratio),
        "unknown_metadata_signal_count": unknown_count,
        "unknown_metadata_signal_ratio": _round_score(unknown_ratio),
        "source_family_count": len(source_families),
        "claim_family_ref_count": len(claim_refs),
        "fresh_selected_count": fresh_count,
        "required_source_classes_missing": _required_source_classes_missing(query_context, selected),
        "protected_primary_required": protected_required,
        "protected_primary_access_failed": bool(protected_failures),
        "protected_primary_admitted": _protected_primary_admitted(selected),
    }
    low_breadth_codes = _breadth_diagnostics(query_context, selected, dimensions)

    diagnostics: list[dict[str, Any]] = []
    if selected_count == 0:
        diagnostics.append(_diagnostic("empty_retrieval", merged_policy["empty_penalty"], "blocker"))
    elif selected_count < expected_min:
        diagnostics.append(_diagnostic("thin_retrieval", merged_policy["thin_penalty"], "warning"))
    if stale_ratio > float(merged_policy["stale_ratio_threshold"]):
        diagnostics.append(_diagnostic("stale_selected_sources", merged_policy["stale_penalty"], "warning"))
    if selected_count and unknown_ratio > float(merged_policy["unknown_signal_ratio_threshold"]):
        diagnostics.append(_diagnostic("unknown_metadata_signals", merged_policy["unknown_metadata_penalty"], "warning"))
    if protected_required and not dimensions["protected_primary_admitted"]:
        diagnostics.append(
            _diagnostic("protected_primary_missing", merged_policy["protected_primary_penalty"], "blocker")
        )
    if protected_failures:
        diagnostics.append(
            _diagnostic("protected_primary_access_failed", merged_policy["protected_primary_penalty"], "blocker")
        )
    if low_breadth_codes:
        diagnostics.append(_diagnostic("low_breadth_signal", merged_policy["low_breadth_penalty"], "warning"))

    penalty_points = _round_score(sum(item["penalty_points"] for item in diagnostics))
    quality_score = _round_score(1.0 - penalty_points)
    if quality_score >= 0.9 and not diagnostics:
        quality_status = "high"
    elif quality_score >= 0.7:
        quality_status = "usable"
    elif quality_score >= 0.35:
        quality_status = "thin"
    else:
        quality_status = "blocked"

    slice_value = {
        "artifact_type": "retrieval_quality_slice",
        "schema_version": RETRIEVAL_QUALITY_SLICE_SCHEMA_VERSION,
        "slice_id": _sha_id(
            "retrieval-quality",
            {
                "case_id": packet.get("case_id"),
                "dispatch_id": packet.get("dispatch_id"),
                "leaf_id": leaf_id,
                "selected_refs": [item.get("evidence_ref") for item in selected],
                "diagnostics": [item["code"] for item in diagnostics],
            },
        ),
        "case_id": packet.get("case_id"),
        "dispatch_id": packet.get("dispatch_id"),
        "leaf_id": leaf_id,
        "query_context_ref": query_context.get("query_context_ref"),
        "selected_evidence_refs": [item.get("evidence_ref") for item in selected if item.get("evidence_ref")],
        "quality_score": quality_score,
        "quality_status": quality_status,
        "penalty_points": penalty_points,
        "diagnostic_codes": sorted({item["code"] for item in diagnostics} | set(low_breadth_codes)),
        "diagnostics": diagnostics,
        "low_breadth_reason_codes": sorted(low_breadth_codes),
        "dimensions": dimensions,
        "authority_boundary": {
            "forecast_numeric_authority": False,
            "authors_new_evidence": False,
            "classification_dispatch_authority": False,
        },
        "scorer_version": RETRIEVAL_QUALITY_SCORER_VERSION,
    }
    result_validation = validate_retrieval_quality_slice(slice_value)
    if not result_validation.valid:
        raise RetrievalQualityError("; ".join(result_validation.errors))
    return slice_value


def build_retrieval_quality_report(
    packet: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score all leaf result slices in a retrieval-packet/v1."""

    if not isinstance(packet, dict) or packet.get("schema_version") != RETRIEVAL_PACKET_SCHEMA_VERSION:
        raise RetrievalQualityError("packet must be retrieval-packet/v1")
    contexts = packet.get("leaf_query_contexts")
    if not isinstance(contexts, list) or not contexts:
        raise RetrievalQualityError("packet.leaf_query_contexts must be a non-empty list")
    by_leaf = _result_by_leaf(packet)
    slices = [
        score_leaf_retrieval_quality(packet, context, by_leaf.get(context.get("leaf_id")), policy=policy)
        for context in contexts
        if isinstance(context, dict)
    ]
    diagnostic_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for slice_value in slices:
        status_counts[slice_value["quality_status"]] = status_counts.get(slice_value["quality_status"], 0) + 1
        for code in slice_value["diagnostic_codes"]:
            diagnostic_counts[code] = diagnostic_counts.get(code, 0) + 1
    scores = [slice_value["quality_score"] for slice_value in slices]
    selected_total = sum(slice_value["dimensions"]["selected_evidence_count"] for slice_value in slices)
    summary = {
        "feature_id": "RET-003",
        "quality_scoring_status": "completed",
        "scorer_version": RETRIEVAL_QUALITY_SCORER_VERSION,
        "leaf_count": len(slices),
        "selected_evidence_count": selected_total,
        "mean_quality_score": _round_score(sum(scores) / len(scores) if scores else 0.0),
        "lowest_quality_score": _round_score(min(scores) if scores else 0.0),
        "quality_status_counts": dict(sorted(status_counts.items())),
        "diagnostic_counts": dict(sorted(diagnostic_counts.items())),
        "empty_leaf_count": diagnostic_counts.get("empty_retrieval", 0),
        "protected_primary_blocked_leaf_count": (
            diagnostic_counts.get("protected_primary_missing", 0)
            + diagnostic_counts.get("protected_primary_access_failed", 0)
        ),
        "low_breadth_leaf_count": diagnostic_counts.get("low_breadth_signal", 0),
        "authority_boundary": {
            "forecast_numeric_authority": False,
            "authors_new_evidence": False,
            "classification_dispatch_authority": False,
        },
    }
    report = {
        "artifact_type": "retrieval_quality_report",
        "schema_version": RETRIEVAL_QUALITY_REPORT_SCHEMA_VERSION,
        "feature_id": "RET-003",
        "case_id": packet.get("case_id"),
        "dispatch_id": packet.get("dispatch_id"),
        "retrieval_packet_schema_version": packet.get("schema_version"),
        "scorer_version": RETRIEVAL_QUALITY_SCORER_VERSION,
        "quality_policy": {**DEFAULT_QUALITY_POLICY, **(policy or {})},
        "retrieval_quality_slices": slices,
        "quality_summary": summary,
    }
    validation = validate_retrieval_quality_report(report)
    if not validation.valid:
        raise RetrievalQualityError("; ".join(validation.errors))
    return report


def attach_retrieval_quality_report(
    packet: dict[str, Any],
    report: dict[str, Any] | None = None,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of the packet with RET-003 slices and summary attached."""

    packet_copy = copy.deepcopy(packet)
    report = report or build_retrieval_quality_report(packet_copy, policy=policy)
    validation = validate_retrieval_quality_report(report)
    if not validation.valid:
        raise RetrievalQualityError("; ".join(validation.errors))
    packet_copy["retrieval_quality_summary"] = copy.deepcopy(report["quality_summary"])
    packet_copy["retrieval_quality_slices"] = copy.deepcopy(report["retrieval_quality_slices"])
    packet_copy.setdefault("schema_feature_gates", {})["RET-003"] = "implemented"
    packet_copy.setdefault("validation_summary", {}).setdefault("reason_codes", []).append("ret_003_quality_scored")
    return packet_copy


def validate_retrieval_quality_slice(slice_value: Any) -> RetrievalQualityValidationResult:
    errors: list[str] = []
    if not isinstance(slice_value, dict):
        return RetrievalQualityValidationResult(False, ("slice must be an object",))
    _reject_forbidden_keys(slice_value, errors, "retrieval_quality_slice")
    for field in (
        "artifact_type",
        "schema_version",
        "slice_id",
        "case_id",
        "dispatch_id",
        "leaf_id",
        "query_context_ref",
        "quality_score",
        "quality_status",
        "penalty_points",
        "diagnostic_codes",
        "dimensions",
        "authority_boundary",
        "scorer_version",
    ):
        if field not in slice_value:
            errors.append(f"slice missing {field}")
    if slice_value.get("artifact_type") != "retrieval_quality_slice":
        errors.append("slice.artifact_type must be retrieval_quality_slice")
    if slice_value.get("schema_version") != RETRIEVAL_QUALITY_SLICE_SCHEMA_VERSION:
        errors.append(f"slice.schema_version must be {RETRIEVAL_QUALITY_SLICE_SCHEMA_VERSION}")
    score = slice_value.get("quality_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0.0 <= float(score) <= 1.0:
        errors.append("slice.quality_score must be between 0 and 1")
    if slice_value.get("quality_status") not in {"high", "usable", "thin", "blocked"}:
        errors.append("slice.quality_status is invalid")
    if not _compact_reason_codes(slice_value.get("diagnostic_codes")):
        errors.append("slice.diagnostic_codes must be compact reason codes")
    boundary = slice_value.get("authority_boundary")
    if not isinstance(boundary, dict) or any(boundary.get(field) is not False for field in (
        "forecast_numeric_authority",
        "authors_new_evidence",
        "classification_dispatch_authority",
    )):
        errors.append("slice.authority_boundary must deny forecast, evidence, and dispatch authority")
    return RetrievalQualityValidationResult(not errors, tuple(errors))


def validate_retrieval_quality_report(report: Any) -> RetrievalQualityValidationResult:
    errors: list[str] = []
    if not isinstance(report, dict):
        return RetrievalQualityValidationResult(False, ("report must be an object",))
    _reject_forbidden_keys(report, errors, "retrieval_quality_report")
    for field in (
        "artifact_type",
        "schema_version",
        "feature_id",
        "case_id",
        "dispatch_id",
        "retrieval_packet_schema_version",
        "retrieval_quality_slices",
        "quality_summary",
    ):
        if field not in report:
            errors.append(f"report missing {field}")
    if report.get("artifact_type") != "retrieval_quality_report":
        errors.append("report.artifact_type must be retrieval_quality_report")
    if report.get("schema_version") != RETRIEVAL_QUALITY_REPORT_SCHEMA_VERSION:
        errors.append(f"report.schema_version must be {RETRIEVAL_QUALITY_REPORT_SCHEMA_VERSION}")
    if report.get("feature_id") != "RET-003":
        errors.append("report.feature_id must be RET-003")
    slices = report.get("retrieval_quality_slices")
    if not isinstance(slices, list) or not slices:
        errors.append("report.retrieval_quality_slices must be a non-empty list")
    else:
        for idx, slice_value in enumerate(slices):
            validation = validate_retrieval_quality_slice(slice_value)
            errors.extend(f"retrieval_quality_slices[{idx}]: {error}" for error in validation.errors)
    summary = report.get("quality_summary")
    if not isinstance(summary, dict):
        errors.append("report.quality_summary must be an object")
    elif summary.get("quality_scoring_status") != "completed":
        errors.append("report.quality_summary.quality_scoring_status must be completed")
    return RetrievalQualityValidationResult(not errors, tuple(errors))
