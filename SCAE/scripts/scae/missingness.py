"""SCAE-008 temporal missingness and no-catalyst candidate diagnostics.

This module consumes RET-005 missingness/access diagnostics and explicit
no-catalyst context. It can emit bounded candidate-only signed log-odds slices,
but it does not aggregate the SCAE ledger, persist forecasts, or author any
probability field.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from scae.policy import PROBABILITY_FIELDS, default_scae_policy


SCAE_TEMPORAL_MISSINGNESS_CANDIDATE_SCHEMA_VERSION = "scae-temporal-missingness-candidate-slice/v1"
SCAE_TEMPORAL_MISSINGNESS_BUNDLE_SCHEMA_VERSION = "scae-temporal-missingness-candidate-bundle/v1"
SCAE_TEMPORAL_MISSINGNESS_SURFACE = "scae_temporal_missingness_candidate_slices"
SCAE_008_MAPPER_VERSION = "ads-scae-008-temporal-missingness/v1"
TEMPORAL_NO_LIVE_AUTHORITY = "temporal_candidate_diagnostics_only_no_live_forecast_authority"

SIGNED_DIRECTIONS = {"supports_yes", "supports_no"}
ACCEPTED_TEMPORAL_STATUSES = {
    "accepted_missingness_candidate",
    "accepted_no_catalyst_candidate",
    "zero_missingness_strength_delta",
    "zero_no_catalyst_hazard_delta",
}

FORBIDDEN_AUTHORING_FIELDS = set(PROBABILITY_FIELDS) | {
    "posterior_probability",
    "forecast_probability",
    "probability_update",
    "production_probability",
    "forecast_interval",
    "decision",
    "recommendation",
}


class ScaeMissingnessError(ValueError):
    """Raised when temporal missingness inputs are malformed or unsafe."""


@dataclass(frozen=True)
class TemporalMissingnessCandidateResult:
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


def _first_non_empty(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _rows_from(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    rows = value.get(field_name) if isinstance(value, dict) else value
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ScaeMissingnessError(f"{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaeMissingnessError(f"{field_name} must contain objects")
        normalized.append(row)
    return normalized


def _numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeMissingnessError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(str(value))
        except (TypeError, ValueError) as exc:
            raise ScaeMissingnessError(f"{field_name} must be numeric") from exc
    if number < 0.0:
        raise ScaeMissingnessError(f"{field_name} must be non-negative")
    return number


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not value:
        raise ScaeMissingnessError(f"{field_name} is required")
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ScaeMissingnessError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _direction_multiplier(direction: str) -> float:
    if direction == "supports_yes":
        return 1.0
    if direction == "supports_no":
        return -1.0
    return 0.0


def _mechanism_proof(row: dict[str, Any]) -> dict[str, Any]:
    proof_ref = _first_non_empty(
        row,
        (
            "missingness_mechanism_proof_ref",
            "absence_mechanism_proof_ref",
            "mechanism_proof_ref",
        ),
    )
    proof_status = _first_non_empty(
        row,
        (
            "missingness_mechanism_proof_status",
            "absence_mechanism_proof_status",
            "mechanism_proof_status",
        ),
    )
    mechanism_family_id = _first_non_empty(
        row,
        (
            "absence_mechanism_family_id",
            "missingness_mechanism_family_id",
            "mechanism_family_id",
        ),
    )
    explicit_flag = row.get("explicit_mechanism_proof")
    accepted = (
        bool(proof_ref)
        and proof_status == "accepted"
        and bool(mechanism_family_id)
        and (explicit_flag is True or explicit_flag is None)
    )
    return {
        "proof_ref": proof_ref,
        "proof_status": proof_status,
        "mechanism_family_id": mechanism_family_id,
        "accepted": accepted,
    }


def _distinct_absence_proof(row: dict[str, Any], current_mechanism_family_id: str | None) -> dict[str, Any]:
    proof_ref = _first_non_empty(row, ("distinct_absence_mechanism_proof_ref", "distinct_mechanism_proof_ref"))
    proof_status = _first_non_empty(
        row,
        (
            "distinct_absence_mechanism_proof_status",
            "distinct_mechanism_proof_status",
        ),
    )
    mechanism_family_id = _first_non_empty(
        row,
        (
            "distinct_absence_mechanism_family_id",
            "distinct_mechanism_family_id",
        ),
    )
    accepted = (
        bool(proof_ref)
        and proof_status == "accepted"
        and bool(mechanism_family_id)
        and mechanism_family_id != current_mechanism_family_id
    )
    return {
        "proof_ref": proof_ref,
        "proof_status": proof_status,
        "mechanism_family_id": mechanism_family_id,
        "accepted": accepted,
    }


def _source_coverage_sufficient(row: dict[str, Any]) -> bool:
    if row.get("source_coverage_sufficient") is True:
        return True
    return row.get("source_coverage_status") == "sufficient"


def _source_coverage_ref(row: dict[str, Any]) -> str | None:
    return _first_non_empty(
        row,
        (
            "source_coverage_ref",
            "retrieval_breadth_coverage_ref",
            "research_sufficiency_certificate_ref",
        ),
    )


def _base_candidate(row: dict[str, Any], *, candidate_kind: str, source_ref_field: str) -> dict[str, Any]:
    return {
        "artifact_type": "scae_temporal_missingness_candidate_slice",
        "schema_version": SCAE_TEMPORAL_MISSINGNESS_CANDIDATE_SCHEMA_VERSION,
        "surface_name": SCAE_TEMPORAL_MISSINGNESS_SURFACE,
        "feature_id": "SCAE-008",
        "candidate_kind": candidate_kind,
        "case_id": row.get("case_id"),
        "dispatch_id": row.get("dispatch_id"),
        "leaf_id": row.get("leaf_id"),
        "parent_branch_id": row.get("parent_branch_id"),
        "condition_scope": row.get("condition_scope"),
        "source_ref": row.get("source_ref"),
        "source_class": row.get("source_class"),
        "source_family_id": row.get("source_family_id"),
        "claim_family_id": row.get("claim_family_id"),
        source_ref_field: row.get("slice_id") or row.get(source_ref_field),
    }


def _overlap_key(candidate: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    return (
        candidate.get("case_id"),
        candidate.get("dispatch_id"),
        candidate.get("leaf_id"),
        candidate.get("absence_mechanism_family_id"),
    )


def _build_missingness_candidate(
    row: dict[str, Any],
    *,
    temporal_policy: dict[str, Any],
) -> dict[str, Any]:
    proof = _mechanism_proof(row)
    direction = str(row.get("signed_impact_direction") or row.get("impact_direction") or "")
    strength = str(row.get("missingness_strength") or row.get("evidence_strength") or "weak")
    strength_map = temporal_policy["missingness_strength_log_odds"]

    status = "accepted_missingness_candidate"
    reasons: list[str] = []
    signed_delta = 0.0
    if temporal_policy["missingness_requires_explicit_mechanism_proof"] and not proof["accepted"]:
        status = "rejected_missing_mechanism_proof"
        reasons.append("explicit_mechanism_proof_required")
    elif direction not in SIGNED_DIRECTIONS:
        status = "rejected_missingness_direction"
        reasons.append("signed_missingness_direction_required")
    elif strength not in strength_map:
        status = "rejected_missingness_strength"
        reasons.append("unsupported_missingness_strength")
    else:
        magnitude = min(
            float(strength_map[strength]),
            float(temporal_policy["max_missingness_log_odds_delta"]),
        )
        signed_delta = round(magnitude * _direction_multiplier(direction), 9)
        if magnitude == 0.0:
            status = "zero_missingness_strength_delta"
            reasons.append("missingness_strength_maps_to_zero")

    seed = {
        "candidate_kind": "explicit_mechanism_missingness",
        "missingness_signal_ref": row.get("slice_id") or row.get("missingness_signal_ref"),
        "mechanism_proof_ref": proof["proof_ref"],
        "absence_mechanism_family_id": proof["mechanism_family_id"],
        "direction": direction,
        "status": status,
    }
    candidate = {
        **_base_candidate(row, candidate_kind="explicit_mechanism_missingness", source_ref_field="missingness_signal_ref"),
        "candidate_slice_id": _sha_id("scae-temporal-candidate", seed),
        "missingness_signal_schema_version": row.get("schema_version"),
        "missingness_reason_code": row.get("missingness_reason_code"),
        "expected_source_class": row.get("expected_source_class"),
        "mechanism_proof_ref": proof["proof_ref"],
        "mechanism_proof_status": proof["proof_status"],
        "absence_mechanism_family_id": proof["mechanism_family_id"],
        "signed_impact_direction": direction,
        "missingness_strength": strength,
        "signed_log_odds_delta": signed_delta,
        "candidate_status": status,
        "accepted_for_ledger_input": status in ACCEPTED_TEMPORAL_STATUSES,
        "rejection_reason_codes": reasons,
        "ledger_input_authority": TEMPORAL_NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "allowed_downstream_effect": "scae_temporal_candidate_diagnostic_only",
        "not_implemented_scope": [
            "SCAE-006_cross_leaf_dependence",
            "SCAE-007_branch_subledgers",
            "SCAE-011_final_interval_and_probability_fields",
        ],
        "mapper_version": SCAE_008_MAPPER_VERSION,
    }
    candidate["candidate_slice_digest"] = _prefixed_sha256(candidate)
    validate_temporal_missingness_candidate(candidate)
    return candidate


def _build_no_catalyst_candidate(
    row: dict[str, Any],
    *,
    temporal_policy: dict[str, Any],
    accepted_missingness_keys: set[tuple[str | None, str | None, str | None, str | None]],
) -> dict[str, Any]:
    hazard_family = str(row.get("hazard_family") or row.get("hazard_family_id") or "")
    mechanism_family_id = _first_non_empty(
        row,
        (
            "absence_mechanism_family_id",
            "no_catalyst_mechanism_family_id",
            "mechanism_family_id",
        ),
    )
    direction = str(row.get("signed_impact_direction") or "supports_no")
    status = "accepted_no_catalyst_candidate"
    reasons: list[str] = []
    signed_delta = 0.0
    unpriced_elapsed_seconds: float | None = None
    hazard_rate_per_day: float | None = None

    try:
        hazard_rate_per_day = _numeric(row.get("hazard_rate_per_day"), "hazard_rate_per_day")
        priced_through = _parse_timestamp(row.get("market_priced_through_timestamp"), "market_priced_through_timestamp")
        forecast_time = _parse_timestamp(row.get("forecast_timestamp"), "forecast_timestamp")
        unpriced_elapsed_seconds = (forecast_time - priced_through).total_seconds()
    except ScaeMissingnessError as exc:
        status = "rejected_no_catalyst_unpriced_interval"
        reasons.append(str(exc))

    overlap_candidate = {
        "case_id": row.get("case_id"),
        "dispatch_id": row.get("dispatch_id"),
        "leaf_id": row.get("leaf_id"),
        "absence_mechanism_family_id": mechanism_family_id,
    }
    distinct_proof = _distinct_absence_proof(row, mechanism_family_id)

    if status == "accepted_no_catalyst_candidate":
        if hazard_family not in temporal_policy["allowed_no_catalyst_hazard_families"]:
            status = "rejected_no_catalyst_hazard_family"
            reasons.append("hazard_family_not_allowed_for_no_catalyst_survival")
        elif direction not in SIGNED_DIRECTIONS:
            status = "rejected_no_catalyst_direction"
            reasons.append("signed_no_catalyst_direction_required")
        elif temporal_policy["no_catalyst_requires_source_coverage"] and (
            not _source_coverage_sufficient(row) or not _source_coverage_ref(row)
        ):
            status = "rejected_no_catalyst_source_coverage"
            reasons.append("source_coverage_sufficient_ref_required")
        elif temporal_policy["no_catalyst_requires_unpriced_interval"] and (
            unpriced_elapsed_seconds is None or unpriced_elapsed_seconds <= 0.0
        ):
            status = "rejected_no_catalyst_unpriced_interval"
            reasons.append("positive_unpriced_interval_required")
        elif (
            temporal_policy["no_catalyst_requires_distinct_absence_mechanism_proof"]
            and _overlap_key(overlap_candidate) in accepted_missingness_keys
            and not distinct_proof["accepted"]
        ):
            status = "rejected_overlap_without_distinct_mechanism_proof"
            reasons.append("missingness_no_catalyst_same_mechanism_without_distinct_proof")
        else:
            days = float(unpriced_elapsed_seconds or 0.0) / 86400.0
            magnitude = min(
                float(hazard_rate_per_day or 0.0) * days,
                float(temporal_policy["max_no_catalyst_log_odds_delta"]),
            )
            signed_delta = round(magnitude * _direction_multiplier(direction), 9)
            if magnitude == 0.0:
                status = "zero_no_catalyst_hazard_delta"
                reasons.append("hazard_rate_or_unpriced_interval_maps_to_zero")

    seed = {
        "candidate_kind": "survival_no_catalyst",
        "no_catalyst_context_ref": row.get("slice_id") or row.get("no_catalyst_context_ref"),
        "hazard_family": hazard_family,
        "mechanism_family_id": mechanism_family_id,
        "direction": direction,
        "status": status,
    }
    candidate = {
        **_base_candidate(row, candidate_kind="survival_no_catalyst", source_ref_field="no_catalyst_context_ref"),
        "candidate_slice_id": _sha_id("scae-temporal-candidate", seed),
        "hazard_family": hazard_family,
        "hazard_schedule_ref": row.get("hazard_schedule_ref"),
        "hazard_rate_per_day": hazard_rate_per_day,
        "market_priced_through_timestamp": row.get("market_priced_through_timestamp"),
        "forecast_timestamp": row.get("forecast_timestamp"),
        "unpriced_elapsed_seconds": unpriced_elapsed_seconds,
        "source_coverage_sufficient": _source_coverage_sufficient(row),
        "source_coverage_ref": _source_coverage_ref(row),
        "absence_mechanism_family_id": mechanism_family_id,
        "distinct_absence_mechanism_proof_ref": distinct_proof["proof_ref"],
        "distinct_absence_mechanism_proof_status": distinct_proof["proof_status"],
        "distinct_absence_mechanism_family_id": distinct_proof["mechanism_family_id"],
        "signed_impact_direction": direction,
        "signed_log_odds_delta": signed_delta,
        "candidate_status": status,
        "accepted_for_ledger_input": status in ACCEPTED_TEMPORAL_STATUSES,
        "rejection_reason_codes": reasons,
        "ledger_input_authority": TEMPORAL_NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "allowed_downstream_effect": "scae_temporal_candidate_diagnostic_only",
        "not_implemented_scope": [
            "SCAE-006_cross_leaf_dependence",
            "SCAE-007_branch_subledgers",
            "SCAE-011_final_interval_and_probability_fields",
        ],
        "mapper_version": SCAE_008_MAPPER_VERSION,
    }
    candidate["candidate_slice_digest"] = _prefixed_sha256(candidate)
    validate_temporal_missingness_candidate(candidate)
    return candidate


def build_temporal_missingness_candidate_slices(
    missingness_signal_slices: dict[str, Any] | list[dict[str, Any]] | None = None,
    *,
    no_catalyst_contexts: dict[str, Any] | list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> TemporalMissingnessCandidateResult:
    """Build SCAE-008 missingness/no-catalyst candidate diagnostics."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    temporal_policy = active_policy["temporal_missingness"]
    missingness_rows = _rows_from(missingness_signal_slices, "missingness_signal_slices")
    no_catalyst_rows = _rows_from(no_catalyst_contexts, "no_catalyst_contexts")

    candidate_slices: list[dict[str, Any]] = []
    accepted_missingness_keys: set[tuple[str | None, str | None, str | None, str | None]] = set()
    for row in missingness_rows:
        candidate = _build_missingness_candidate(row, temporal_policy=temporal_policy)
        if candidate["candidate_status"] == "accepted_missingness_candidate":
            accepted_missingness_keys.add(_overlap_key(candidate))
        candidate_slices.append(candidate)

    for row in no_catalyst_rows:
        candidate_slices.append(
            _build_no_catalyst_candidate(
                row,
                temporal_policy=temporal_policy,
                accepted_missingness_keys=accepted_missingness_keys,
            )
        )

    candidate_slices.sort(key=lambda item: (str(item["candidate_slice_id"]), _canonical_json(item)))
    bundle_digest = _prefixed_sha256(
        {
            "schema_version": "scae-temporal-missingness-candidate-digest/v1",
            "candidate_slice_schema_version": SCAE_TEMPORAL_MISSINGNESS_CANDIDATE_SCHEMA_VERSION,
            "candidate_slices": candidate_slices,
        }
    )
    for candidate in candidate_slices:
        candidate["candidate_bundle_digest"] = bundle_digest
    return TemporalMissingnessCandidateResult(candidate_slices, bundle_digest)


def build_temporal_missingness_candidate_bundle(
    missingness_signal_slices: dict[str, Any] | list[dict[str, Any]] | None = None,
    *,
    no_catalyst_contexts: dict[str, Any] | list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the external SCAE-008 candidate-only temporal bundle artifact."""

    result = build_temporal_missingness_candidate_slices(
        missingness_signal_slices,
        no_catalyst_contexts=no_catalyst_contexts,
        policy=policy,
    )
    status_counts: dict[str, int] = {}
    for candidate in result.candidate_slices:
        status = str(candidate["candidate_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    bundle = {
        "artifact_type": "scae_temporal_missingness_candidate_bundle",
        "schema_version": SCAE_TEMPORAL_MISSINGNESS_BUNDLE_SCHEMA_VERSION,
        "feature_id": "SCAE-008",
        "surface_name": SCAE_TEMPORAL_MISSINGNESS_SURFACE,
        "authority": TEMPORAL_NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "candidate_bundle_digest": result.candidate_bundle_digest,
        "candidate_slices": result.candidate_slices,
        "mapper_version": SCAE_008_MAPPER_VERSION,
    }
    reject_forbidden_authoring_fields(bundle)
    return bundle


def reject_forbidden_authoring_fields(value: Any, path: str = "temporal_missingness") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_AUTHORING_FIELDS:
                raise ScaeMissingnessError(f"{path}.{key} is forbidden in temporal missingness candidates")
            reject_forbidden_authoring_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_forbidden_authoring_fields(child, f"{path}[{idx}]")


def validate_temporal_missingness_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version") != SCAE_TEMPORAL_MISSINGNESS_CANDIDATE_SCHEMA_VERSION:
        raise ScaeMissingnessError("temporal missingness candidate schema is invalid")
    reject_forbidden_authoring_fields(candidate)
    for field in ["live_forecast_authority", "writes_scae_ledger", "writes_production_forecast"]:
        if candidate.get(field) is not False:
            raise ScaeMissingnessError(f"{field} must be false")
    if candidate.get("ledger_input_authority") != TEMPORAL_NO_LIVE_AUTHORITY:
        raise ScaeMissingnessError("temporal missingness candidates must not have live authority")
    if candidate.get("candidate_status") in ACCEPTED_TEMPORAL_STATUSES:
        expected = True
    else:
        expected = False
    if candidate.get("accepted_for_ledger_input") is not expected:
        raise ScaeMissingnessError("accepted_for_ledger_input must match temporal candidate status")
