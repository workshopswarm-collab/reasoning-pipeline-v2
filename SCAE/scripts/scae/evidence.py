"""SCAE-003 evidence delta candidate mapping.

This module converts verified Session 4 classification rows into bounded
signed log-odds candidate records. It does not aggregate a ledger, apply the
SCAE-004 correlated-quality guard, or author any production probability.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from scae.policy import default_scae_policy


SCAE_EVIDENCE_DELTA_CANDIDATE_SCHEMA_VERSION = "scae-log-odds-update-candidate-slice/v1"
SCAE_EVIDENCE_DELTA_BUNDLE_SCHEMA_VERSION = "scae-evidence-delta-candidate-bundle/v1"
SCAE_LOG_ODDS_UPDATE_SURFACE = "scae_log_odds_update_slices"
SCAE_003_MAPPER_VERSION = "ads-scae-003-evidence-delta-mapper/v1"
NO_LIVE_AUTHORITY = "candidate_ledger_input_only_no_live_forecast_authority"

ACCEPTED_CANDIDATE_STATUSES = {
    "accepted_candidate",
    "neutral_zero_delta",
    "zero_strength_delta",
    "zero_market_assimilation_delta",
}
REJECTED_CANDIDATE_STATUSES = {
    "rejected_direction_verification",
    "rejected_quality_verification",
}
SIGNED_DIRECTIONS = {"supports_yes", "supports_no"}


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


def _cap_signed_delta(value: float, cap: float) -> tuple[float, bool]:
    bounded = max(-cap, min(cap, value))
    return round(bounded, 9), bounded != value


def _candidate_status(
    *,
    claimed_direction: str,
    verified_direction: str,
    direction_accepted: bool,
    quality_accepted: bool,
    strength_log_odds: float,
    market_assimilation_multiplier: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not quality_accepted:
        return "rejected_quality_verification", ["quality_verification_not_accepted"]
    if claimed_direction != "neutral" and (not direction_accepted or verified_direction not in SIGNED_DIRECTIONS):
        reasons.append("non_neutral_direction_not_verified")
        return "rejected_direction_verification", reasons
    if claimed_direction == "neutral" or verified_direction == "neutral":
        return "neutral_zero_delta", ["neutral_direction_zero_delta"]
    if strength_log_odds == 0.0:
        return "zero_strength_delta", ["evidence_strength_maps_to_zero"]
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
    """Build SCAE-003 signed log-odds candidate slices from verified rows."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    delta_policy = active_policy["evidence_delta_mapping"]
    strength_map = delta_policy["strength_log_odds"]
    direction_multipliers = delta_policy["direction_multipliers"]
    per_update_cap = _numeric_multiplier(active_policy["cap_stack"]["per_update_log_odds_cap"], "per_update_log_odds_cap")

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
        verified_direction = str(direction_row.get("verified_direction") or "")
        direction_accepted = (
            direction_row.get("accepted_for_scae") is True
            and direction_row.get("verification_status") == "accepted"
        )
        quality_accepted = (
            quality_row.get("accepted_for_scae") is True
            and quality_row.get("quality_status") == "accepted"
        )

        raw_quality_multiplier = _numeric_multiplier(
            quality_row.get("raw_quality_multiplier"),
            "raw_quality_multiplier",
        )
        final_quality_multiplier = _numeric_multiplier(
            quality_row.get("final_quality_multiplier"),
            "final_quality_multiplier",
        )
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
        status, rejection_reason_codes = _candidate_status(
            claimed_direction=claimed_direction,
            verified_direction=verified_direction,
            direction_accepted=direction_accepted,
            quality_accepted=quality_accepted,
            strength_log_odds=strength_log_odds,
            market_assimilation_multiplier=market_assimilation_multiplier,
        )
        direction_multiplier = float(direction_multipliers.get(verified_direction, 0.0))
        pre_cap_delta = 0.0
        bounded_delta = 0.0
        bounded_by_cap = False
        if status in ACCEPTED_CANDIDATE_STATUSES:
            pre_cap_delta = strength_log_odds * direction_multiplier * final_quality_multiplier * market_assimilation_multiplier
            bounded_delta, bounded_by_cap = _cap_signed_delta(pre_cap_delta, per_update_cap)

        seed = {
            "classification_slice_ref": classification_key,
            "direction_verification_ref": direction_row.get("verification_slice_id"),
            "quality_verification_ref": quality_row.get("quality_verification_slice_id"),
            "evidence_strength": evidence_strength,
            "verified_direction": verified_direction,
            "candidate_status": status,
        }
        candidate = {
            "artifact_type": "scae_log_odds_update_candidate_slice",
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
            "direction_verification_slice_ref": direction_row.get("verification_slice_id"),
            "direction_verification_status": direction_row.get("verification_status"),
            "direction_multiplier": direction_multiplier,
            "evidence_strength": evidence_strength,
            "strength_log_odds": strength_log_odds,
            "quality_verification_slice_ref": quality_row.get("quality_verification_slice_id"),
            "quality_status": quality_row.get("quality_status"),
            "accepted_quality_fields": copy.deepcopy(quality_row.get("accepted_quality_fields") or {}),
            "quality_correlation_groups": copy.deepcopy(quality_row.get("quality_correlation_groups") or []),
            "raw_quality_multiplier": raw_quality_multiplier,
            "verified_quality_multiplier": final_quality_multiplier,
            "correlated_quality_guard_applied": False,
            "correlated_quality_guard_status": "not_applied_scae004_not_implemented",
            "market_assimilation_context_ref": assimilation_context.get("evidence_ref") if assimilation_context else None,
            "market_assimilation_multiplier": market_assimilation_multiplier,
            "market_assimilation_reason_codes": copy.deepcopy((assimilation_context or {}).get("reason_codes") or []),
            "pre_cap_signed_log_odds_delta": round(pre_cap_delta, 9),
            "per_update_log_odds_cap": per_update_cap,
            "signed_log_odds_delta": bounded_delta,
            "bounded_by_per_update_cap": bounded_by_cap,
            "candidate_status": status,
            "accepted_for_ledger_input": status in ACCEPTED_CANDIDATE_STATUSES,
            "rejection_reason_codes": rejection_reason_codes,
            "ledger_input_authority": NO_LIVE_AUTHORITY,
            "live_forecast_authority": False,
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
            "allowed_downstream_effect": "scae_ledger_input_candidate_only",
            "not_implemented_scope": [
                "SCAE-004_correlated_quality_guard_and_cap_stack",
                "SCAE-005_cluster_netting",
                "SCAE-006_cross_leaf_dependence",
                "SCAE-011_final_probability_fields",
            ],
            "mapper_version": SCAE_003_MAPPER_VERSION,
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
    """Return the external SCAE-003 candidate bundle artifact."""

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
        "mapper_version": SCAE_003_MAPPER_VERSION,
    }
