"""SCAE-003/SCAE-004 evidence delta candidate mapping.

This module converts verified Session 4 classification rows into bounded
signed log-odds candidate records, including the SCAE-004 correlated-quality
guard and first cap-stack stage. It does not aggregate a ledger or author any
production probability.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from scae.policy import default_scae_policy


SCAE_EVIDENCE_DELTA_CANDIDATE_SCHEMA_VERSION = "scae-evidence-delta-candidate/v1"
SCAE_EVIDENCE_DELTA_BUNDLE_SCHEMA_VERSION = "scae-evidence-delta-candidate-bundle/v1"
SCAE_LOG_ODDS_UPDATE_SURFACE = "scae_log_odds_update_slices"
SCAE_EVIDENCE_MAPPER_VERSION = "ads-scae-004-phase9-verified-evidence-mapping/v1"
NO_LIVE_AUTHORITY = "candidate_ledger_input_only_no_live_forecast_authority"
CAP_STACK_FIELDS = [
    "per_update_log_odds_cap",
    "per_cluster_log_odds_cap",
    "per_branch_log_odds_cap",
    "total_evidence_log_odds_cap",
    "debt_mode_total_evidence_log_odds_cap",
]

ACCEPTED_CANDIDATE_STATUSES = {
    "accepted_candidate",
}
REJECTED_CANDIDATE_STATUSES = {
    "rejected_direction_verification",
    "rejected_quality_verification",
    "rejected_classification_not_accepted",
    "rejected_low_certainty_or_quality",
}
SIGNED_DIRECTIONS = {"supports_yes", "supports_no"}
NO_DELTA_DIRECTIONS = {"neutral", "irrelevant", "insufficient"}
BRANCH_NETTING_DIRECTIONS = {"mixed"}
CLASSIFICATION_ACCEPTED_STATUS = "accepted_for_verification"


class ScaeEvidenceDeltaError(ValueError):
    """Raised when SCAE-003 evidence mapping cannot safely continue."""


@dataclass(frozen=True)
class EvidenceDeltaCandidateResult:
    candidate_slices: list[dict[str, Any]]
    candidate_bundle_digest: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _rows_from(value: Any, field_name: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        rows = value.get(field_name)
    else:
        rows = value
    if not isinstance(rows, list):
        raise ScaeEvidenceDeltaError(f"{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaeEvidenceDeltaError(f"{field_name} must contain objects")
        normalized.append(row)
    return normalized


def _classification_key(row: dict[str, Any]) -> str:
    for field in ("slice_id", "classification_slice_ref", "classification_slice_id", "classification_id"):
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    raise ScaeEvidenceDeltaError("classification row is missing slice_id/classification_id")


def _verification_key(row: dict[str, Any]) -> str | None:
    for field in ("classification_slice_ref", "classification_slice_id", "slice_id", "classification_id"):
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _index_verifications(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _verification_key(row)
        if not key:
            raise ScaeEvidenceDeltaError(f"{label} row is missing classification reference")
        if key in indexed:
            raise ScaeEvidenceDeltaError(f"duplicate {label} row for classification {key}")
        indexed[key] = row
    return indexed


def _index_assimilation(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        evidence_ref = row.get("evidence_ref")
        if not _is_non_empty_string(evidence_ref):
            raise ScaeEvidenceDeltaError("market assimilation context is missing evidence_ref")
        key = str(evidence_ref)
        if key in indexed:
            raise ScaeEvidenceDeltaError(f"duplicate market assimilation context for evidence {key}")
        indexed[key] = row
    return indexed


def _numeric_multiplier(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeEvidenceDeltaError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(str(value))
        except (TypeError, ValueError) as exc:
            raise ScaeEvidenceDeltaError(f"{field_name} must be numeric") from exc
    if number < 0.0:
        raise ScaeEvidenceDeltaError(f"{field_name} must be non-negative")
    return number


def _quality_correlation_groups(row: dict[str, Any]) -> list[str]:
    groups = row.get("quality_correlation_groups") or []
    if not isinstance(groups, list):
        raise ScaeEvidenceDeltaError("quality_correlation_groups must be a list")
    normalized: list[str] = []
    for group in groups:
        if not _is_non_empty_string(group):
            raise ScaeEvidenceDeltaError("quality_correlation_groups must contain non-empty strings")
        normalized.append(str(group))
    return sorted(set(normalized))


def _is_quality_accepted(row: dict[str, Any]) -> bool:
    return row.get("accepted_for_scae") is True and row.get("quality_status") == "accepted"


def _quality_correlation_group_counts(
    classifications: list[dict[str, Any]],
    quality_by_classification: dict[str, dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for classification in classifications:
        quality_row = quality_by_classification.get(_classification_key(classification))
        if quality_row is None or not _is_quality_accepted(quality_row):
            continue
        for group in _quality_correlation_groups(quality_row):
            counts[group] = counts.get(group, 0) + 1
    return counts


def _cap_stack_context(cap_stack: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cap_stack, dict):
        raise ScaeEvidenceDeltaError("cap_stack must be an object")
    context = {field: _numeric_multiplier(cap_stack.get(field), field) for field in CAP_STACK_FIELDS}
    selector = cap_stack.get("representative_selector")
    if not _is_non_empty_string(selector):
        raise ScaeEvidenceDeltaError("cap_stack.representative_selector must be a non-empty string")
    context["representative_selector"] = str(selector)
    context["applied_stage"] = "candidate_per_update_cap_only"
    context["later_cap_stages_not_applied"] = [
        "per_cluster_log_odds_cap",
        "per_branch_log_odds_cap",
        "total_evidence_log_odds_cap",
        "debt_mode_total_evidence_log_odds_cap",
    ]
    return context


def _correlated_quality_guard_policy(cap_stack: dict[str, Any]) -> dict[str, Any]:
    guard = cap_stack.get("correlated_quality_guard")
    if not isinstance(guard, dict):
        raise ScaeEvidenceDeltaError("cap_stack.correlated_quality_guard must be an object")
    if not isinstance(guard.get("enabled"), bool):
        raise ScaeEvidenceDeltaError("correlated_quality_guard.enabled must be a boolean")
    min_count = guard.get("repeated_group_min_count")
    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 2:
        raise ScaeEvidenceDeltaError("correlated_quality_guard.repeated_group_min_count must be an integer >= 2")
    ceiling = _numeric_multiplier(guard.get("multiplier_ceiling"), "correlated_quality_guard.multiplier_ceiling")
    if ceiling <= 0.0 or ceiling > 1.0:
        raise ScaeEvidenceDeltaError("correlated_quality_guard.multiplier_ceiling must be in (0, 1]")
    return {
        "enabled": guard["enabled"],
        "repeated_group_min_count": min_count,
        "multiplier_ceiling": ceiling,
    }


def _apply_correlated_quality_guard(
    *,
    verified_quality_multiplier: float,
    quality_correlation_groups: list[str],
    group_counts: dict[str, int],
    guard_policy: dict[str, Any],
) -> dict[str, Any]:
    if not guard_policy["enabled"]:
        return {
            "multiplier": verified_quality_multiplier,
            "applied": False,
            "status": "disabled_by_policy",
            "repeated_groups": [],
            "group_counts": {group: group_counts.get(group, 0) for group in quality_correlation_groups},
        }

    repeated_groups = [
        group
        for group in quality_correlation_groups
        if group_counts.get(group, 0) >= guard_policy["repeated_group_min_count"]
    ]
    local_counts = {group: group_counts.get(group, 0) for group in quality_correlation_groups}
    if not quality_correlation_groups:
        status = "no_quality_correlation_groups"
    elif not repeated_groups:
        status = "passed_no_repeated_quality_correlation_group"
    else:
        status = "repeated_quality_correlation_group_within_cap"

    guarded = verified_quality_multiplier
    if repeated_groups:
        guarded = min(verified_quality_multiplier, guard_policy["multiplier_ceiling"])
        if guarded < verified_quality_multiplier:
            status = "capped_repeated_quality_correlation_group"

    return {
        "multiplier": round(guarded, 9),
        "applied": guarded < verified_quality_multiplier,
        "status": status,
        "repeated_groups": repeated_groups,
        "group_counts": local_counts,
    }


def _cap_signed_delta(value: float, cap: float) -> tuple[float, bool]:
    bounded = max(-cap, min(cap, value))
    return round(bounded, 9), bounded != value


def _normalized_enum(value: Any, allowed: set[str], default: str) -> str:
    if _is_non_empty_string(value):
        text = str(value).strip().lower()
        if text in allowed:
            return text
    return default


def _discount_from_policy(mapping: dict[str, Any], key: str, field_name: str) -> float:
    if key not in mapping:
        raise ScaeEvidenceDeltaError(f"{field_name}.{key} is missing")
    value = _numeric_multiplier(mapping[key], f"{field_name}.{key}")
    if value > 1.0:
        raise ScaeEvidenceDeltaError(f"{field_name}.{key} must be in [0, 1]")
    return value


def _classification_scoreability(classification: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    acceptance_status = classification.get("classification_acceptance_status")
    if _is_non_empty_string(acceptance_status) and acceptance_status != CLASSIFICATION_ACCEPTED_STATUS:
        reasons.append(f"classification_acceptance_status_{acceptance_status}")
    if classification.get("evidence_delta_eligible_for_scae") is False:
        reasons.append("evidence_delta_not_eligible_for_scae")
    if classification.get("included_for_scae", classification.get("ledger_ready", True)) is not True:
        reasons.append("classification_not_included_for_scae")
    return not reasons, sorted(set(reasons))


def _classification_confidence(
    classification: dict[str, Any],
    quality_row: dict[str, Any],
) -> str:
    accepted = quality_row.get("accepted_quality_fields") if isinstance(quality_row.get("accepted_quality_fields"), dict) else {}
    return _normalized_enum(
        classification.get("classification_confidence") or accepted.get("classification_confidence"),
        {"high", "medium", "low"},
        "low",
    )


def _classification_quality(
    classification: dict[str, Any],
    quality_row: dict[str, Any],
) -> str:
    accepted = quality_row.get("accepted_quality_fields") if isinstance(quality_row.get("accepted_quality_fields"), dict) else {}
    return _normalized_enum(
        classification.get("classification_quality") or accepted.get("classification_quality"),
        {"high", "medium", "low", "unusable"},
        "unusable",
    )


def _candidate_status(
    *,
    claimed_direction: str,
    verified_direction: str,
    direction_accepted: bool,
    quality_accepted: bool,
    classification_scoreable: bool,
    classification_reasons: list[str],
    strength_log_odds: float,
    confidence_discount: float,
    quality_discount: float,
    market_assimilation_multiplier: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if claimed_direction in NO_DELTA_DIRECTIONS or verified_direction in NO_DELTA_DIRECTIONS:
        return "no_delta_classification", [f"{claimed_direction or verified_direction}_direction_no_delta"]
    if claimed_direction in BRANCH_NETTING_DIRECTIONS or verified_direction in BRANCH_NETTING_DIRECTIONS:
        if not classification_scoreable:
            return "rejected_classification_not_accepted", classification_reasons
        if not quality_accepted:
            return "rejected_quality_verification", ["quality_verification_not_accepted"]
        if not direction_accepted or verified_direction != "mixed":
            return "rejected_direction_verification", ["mixed_direction_not_verified"]
        if confidence_discount == 0.0 or quality_discount == 0.0:
            return "rejected_low_certainty_or_quality", ["phase9_confidence_or_quality_discount_zero"]
        return "mixed_branch_netting_candidate", ["mixed_direction_branch_netting_required"]
    if not classification_scoreable:
        return "rejected_classification_not_accepted", classification_reasons
    if not quality_accepted:
        return "rejected_quality_verification", ["quality_verification_not_accepted"]
    if not direction_accepted or verified_direction not in SIGNED_DIRECTIONS:
        reasons.append("non_neutral_direction_not_verified")
        return "rejected_direction_verification", reasons
    if strength_log_odds == 0.0:
        return "zero_strength_delta", ["evidence_strength_maps_to_zero"]
    if confidence_discount == 0.0 or quality_discount == 0.0:
        return "rejected_low_certainty_or_quality", ["phase9_confidence_or_quality_discount_zero"]
    if market_assimilation_multiplier == 0.0:
        return "zero_market_assimilation_delta", ["market_assimilation_zero_delta"]
    return "accepted_candidate", []


def build_evidence_delta_candidate_slices(
    classification_matrix: dict[str, Any] | list[dict[str, Any]],
    *,
    direction_verification_slices: list[dict[str, Any]] | dict[str, Any],
    quality_verification_slices: list[dict[str, Any]] | dict[str, Any],
    market_assimilation_contexts: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> EvidenceDeltaCandidateResult:
    """Build guarded SCAE signed log-odds candidate slices from verified rows."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    delta_policy = active_policy["evidence_delta_mapping"]
    strength_map = delta_policy["strength_log_odds"]
    direction_multipliers = delta_policy["direction_multipliers"]
    confidence_discounts = delta_policy["classification_confidence_discounts"]
    quality_discounts = delta_policy["classification_quality_discounts"]
    cap_stack = active_policy["cap_stack"]
    cap_stack_context = _cap_stack_context(cap_stack)
    per_update_cap = cap_stack_context["per_update_log_odds_cap"]
    guard_policy = _correlated_quality_guard_policy(cap_stack)

    classifications = _rows_from(classification_matrix, "classification_slices")
    direction_by_classification = _index_verifications(
        _rows_from(direction_verification_slices, "direction_verification_slices"),
        "direction verification",
    )
    quality_by_classification = _index_verifications(
        _rows_from(quality_verification_slices, "quality_verification_slices"),
        "quality verification",
    )
    assimilation_by_evidence = _index_assimilation(market_assimilation_contexts)
    quality_group_counts = _quality_correlation_group_counts(classifications, quality_by_classification)

    candidate_slices: list[dict[str, Any]] = []
    for classification in classifications:
        classification_key = _classification_key(classification)
        direction_row = direction_by_classification.get(classification_key)
        if direction_row is None:
            raise ScaeEvidenceDeltaError(f"missing direction verification for classification {classification_key}")
        quality_row = quality_by_classification.get(classification_key)
        if quality_row is None:
            raise ScaeEvidenceDeltaError(f"missing quality verification for classification {classification_key}")

        claimed_direction = str(classification.get("impact_direction") or "")
        evidence_strength = str(classification.get("evidence_strength") or "")
        if evidence_strength not in strength_map:
            raise ScaeEvidenceDeltaError(f"unsupported evidence_strength {evidence_strength!r}")
        classification_scoreable, classification_reasons = _classification_scoreability(classification)
        verified_direction = str(direction_row.get("verified_direction") or "")
        direction_accepted = (
            direction_row.get("accepted_for_scae") is True
            and direction_row.get("verification_status") == "accepted"
        )
        quality_accepted = (
            _is_quality_accepted(quality_row)
        )

        raw_quality_multiplier = _numeric_multiplier(
            quality_row.get("raw_quality_multiplier"),
            "raw_quality_multiplier",
        )
        final_quality_multiplier = _numeric_multiplier(
            quality_row.get("final_quality_multiplier"),
            "final_quality_multiplier",
        )
        quality_correlation_groups = _quality_correlation_groups(quality_row)
        guard_result = _apply_correlated_quality_guard(
            verified_quality_multiplier=final_quality_multiplier,
            quality_correlation_groups=quality_correlation_groups,
            group_counts=quality_group_counts,
            guard_policy=guard_policy,
        )
        guarded_quality_multiplier = float(guard_result["multiplier"])
        evidence_ref = classification.get("evidence_ref")
        assimilation_context = assimilation_by_evidence.get(str(evidence_ref)) if _is_non_empty_string(evidence_ref) else None
        if assimilation_context is not None:
            market_assimilation_multiplier = _numeric_multiplier(
                assimilation_context.get("suggested_signed_delta_multiplier"),
                "suggested_signed_delta_multiplier",
            )
        else:
            market_assimilation_multiplier = 1.0

        strength_log_odds = float(strength_map[evidence_strength])
        classification_confidence = _classification_confidence(classification, quality_row)
        classification_quality = _classification_quality(classification, quality_row)
        confidence_discount = _discount_from_policy(
            confidence_discounts,
            classification_confidence,
            "classification_confidence_discounts",
        )
        quality_discount = _discount_from_policy(
            quality_discounts,
            classification_quality,
            "classification_quality_discounts",
        )
        phase9_discount_multiplier = round(confidence_discount * quality_discount, 9)
        effective_quality_multiplier = round(guarded_quality_multiplier * phase9_discount_multiplier, 9)
        status, rejection_reason_codes = _candidate_status(
            claimed_direction=claimed_direction,
            verified_direction=verified_direction,
            direction_accepted=direction_accepted,
            quality_accepted=quality_accepted,
            classification_scoreable=classification_scoreable,
            classification_reasons=classification_reasons,
            strength_log_odds=strength_log_odds,
            confidence_discount=confidence_discount,
            quality_discount=quality_discount,
            market_assimilation_multiplier=market_assimilation_multiplier,
        )
        direction_multiplier = float(direction_multipliers.get(verified_direction, 0.0))
        pre_cap_delta = 0.0
        bounded_delta = 0.0
        bounded_by_cap = False
        if status in ACCEPTED_CANDIDATE_STATUSES:
            pre_cap_delta = strength_log_odds * direction_multiplier * effective_quality_multiplier * market_assimilation_multiplier
            bounded_delta, bounded_by_cap = _cap_signed_delta(pre_cap_delta, per_update_cap)

        seed = {
            "classification_slice_ref": classification_key,
            "direction_verification_ref": direction_row.get("verification_slice_id"),
            "quality_verification_ref": quality_row.get("quality_verification_slice_id"),
            "evidence_strength": evidence_strength,
            "verified_direction": verified_direction,
            "classification_scoreable": classification_scoreable,
            "classification_confidence": classification_confidence,
            "classification_quality": classification_quality,
            "phase9_discount_multiplier": phase9_discount_multiplier,
            "quality_multiplier_after_correlated_guard": guarded_quality_multiplier,
            "correlated_quality_guard_status": guard_result["status"],
            "correlated_quality_group_counts": guard_result["group_counts"],
            "candidate_status": status,
        }
        candidate = {
            "artifact_type": "scae_evidence_delta_candidate",
            "schema_version": SCAE_EVIDENCE_DELTA_CANDIDATE_SCHEMA_VERSION,
            "surface_name": SCAE_LOG_ODDS_UPDATE_SURFACE,
            "feature_id": "SCAE-003",
            "candidate_slice_id": _sha_id("scae-delta-candidate", seed),
            "case_id": classification.get("case_id"),
            "dispatch_id": classification.get("dispatch_id"),
            "leaf_id": classification.get("leaf_id"),
            "parent_branch_id": classification.get("parent_branch_id"),
            "condition_scope": classification.get("condition_scope"),
            "classification_slice_ref": classification.get("slice_id"),
            "classification_id": classification.get("classification_id"),
            "evidence_ref": evidence_ref,
            "source_ref": classification.get("source_ref"),
            "source_class": classification.get("source_class"),
            "source_family_id": classification.get("source_family_id"),
            "claim_family_id": classification.get("claim_family_id"),
            "retrieval_breadth_coverage_ref": classification.get("retrieval_breadth_coverage_ref"),
            "research_sufficiency_certificate_ref": classification.get("research_sufficiency_certificate_ref"),
            "claimed_impact_direction": claimed_direction,
            "verified_direction": verified_direction,
            "classification_acceptance_status": classification.get("classification_acceptance_status"),
            "evidence_delta_eligible_for_scae": classification.get("evidence_delta_eligible_for_scae"),
            "included_for_scae": classification.get("included_for_scae", classification.get("ledger_ready")),
            "classification_scoreable_for_scae": classification_scoreable,
            "classification_scoreability_reason_codes": classification_reasons,
            "direction_verification_slice_ref": direction_row.get("verification_slice_id"),
            "direction_verification_status": direction_row.get("verification_status"),
            "direction_multiplier": direction_multiplier,
            "evidence_strength": evidence_strength,
            "strength_log_odds": strength_log_odds,
            "classification_confidence": classification_confidence,
            "classification_quality": classification_quality,
            "phase9_confidence_discount": confidence_discount,
            "phase9_quality_discount": quality_discount,
            "phase9_discount_multiplier": phase9_discount_multiplier,
            "quality_verification_slice_ref": quality_row.get("quality_verification_slice_id"),
            "quality_status": quality_row.get("quality_status"),
            "accepted_quality_fields": copy.deepcopy(quality_row.get("accepted_quality_fields") or {}),
            "quality_correlation_groups": quality_correlation_groups,
            "raw_quality_multiplier": raw_quality_multiplier,
            "verified_quality_multiplier": final_quality_multiplier,
            "quality_multiplier_before_correlated_guard": final_quality_multiplier,
            "quality_multiplier_after_correlated_guard": guarded_quality_multiplier,
            "effective_quality_multiplier_after_phase9_discounts": effective_quality_multiplier,
            "correlated_quality_guard_applied": bool(guard_result["applied"]),
            "correlated_quality_guard_status": guard_result["status"],
            "correlated_quality_guard_repeated_groups": guard_result["repeated_groups"],
            "correlated_quality_group_counts": guard_result["group_counts"],
            "correlated_quality_guard_policy": copy.deepcopy(guard_policy),
            "market_assimilation_context_ref": assimilation_context.get("evidence_ref") if assimilation_context else None,
            "market_assimilation_multiplier": market_assimilation_multiplier,
            "market_assimilation_reason_codes": copy.deepcopy((assimilation_context or {}).get("reason_codes") or []),
            "pre_cap_signed_log_odds_delta": round(pre_cap_delta, 9),
            "per_update_log_odds_cap": per_update_cap,
            "cap_stack": copy.deepcopy(cap_stack_context),
            "signed_log_odds_delta": bounded_delta,
            "bounded_by_per_update_cap": bounded_by_cap,
            "candidate_status": status,
            "accepted_for_ledger_input": status in ACCEPTED_CANDIDATE_STATUSES,
            "requires_branch_netting": status == "mixed_branch_netting_candidate",
            "direct_single_delta_eligible": status in ACCEPTED_CANDIDATE_STATUSES,
            "supporting_evidence_refs": copy.deepcopy(classification.get("supporting_evidence_refs") or []),
            "opposing_evidence_refs": copy.deepcopy(classification.get("opposing_evidence_refs") or []),
            "rejection_reason_codes": rejection_reason_codes,
            "ledger_input_authority": NO_LIVE_AUTHORITY,
            "live_forecast_authority": False,
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
            "allowed_downstream_effect": "scae_ledger_input_candidate_only",
            "not_implemented_scope": [
                "SCAE-005_cluster_netting",
                "SCAE-006_cross_leaf_dependence",
                "SCAE-007_branch_subledgers",
                "SCAE-011_final_probability_fields",
            ],
            "implemented_feature_ids": ["SCAE-003", "SCAE-004"],
            "mapper_version": SCAE_EVIDENCE_MAPPER_VERSION,
        }
        candidate["candidate_slice_digest"] = _prefixed_sha256(candidate)
        candidate_slices.append(candidate)

    candidate_slices.sort(key=lambda item: (str(item["candidate_slice_id"]), _canonical_json(item)))
    bundle_digest = _prefixed_sha256(
        {
            "schema_version": "scae-evidence-delta-candidate-digest/v1",
            "candidate_slice_schema_version": SCAE_EVIDENCE_DELTA_CANDIDATE_SCHEMA_VERSION,
            "candidate_slices": candidate_slices,
        }
    )
    for candidate in candidate_slices:
        candidate["candidate_bundle_digest"] = bundle_digest
    return EvidenceDeltaCandidateResult(candidate_slices, bundle_digest)


def build_evidence_delta_candidate_bundle(
    classification_matrix: dict[str, Any] | list[dict[str, Any]],
    *,
    direction_verification_slices: list[dict[str, Any]] | dict[str, Any],
    quality_verification_slices: list[dict[str, Any]] | dict[str, Any],
    market_assimilation_contexts: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the external candidate bundle artifact after SCAE-004 guards."""

    result = build_evidence_delta_candidate_slices(
        classification_matrix,
        direction_verification_slices=direction_verification_slices,
        quality_verification_slices=quality_verification_slices,
        market_assimilation_contexts=market_assimilation_contexts,
        policy=policy,
    )
    status_counts: dict[str, int] = {}
    for candidate in result.candidate_slices:
        status = str(candidate["candidate_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "artifact_type": "scae_evidence_delta_candidate_bundle",
        "schema_version": SCAE_EVIDENCE_DELTA_BUNDLE_SCHEMA_VERSION,
        "feature_id": "SCAE-003",
        "surface_name": SCAE_LOG_ODDS_UPDATE_SURFACE,
        "authority": NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "candidate_bundle_digest": result.candidate_bundle_digest,
        "candidate_slices": result.candidate_slices,
        "implemented_feature_ids": ["SCAE-003", "SCAE-004"],
        "mapper_version": SCAE_EVIDENCE_MAPPER_VERSION,
    }
