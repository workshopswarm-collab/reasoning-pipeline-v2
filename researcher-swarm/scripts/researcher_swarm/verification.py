"""VER-001/VER-002 deterministic researcher verification slices."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


DIRECTION_VERIFICATION_SLICE_SCHEMA_VERSION = "evidence-direction-verification-slice/v1"
QUALITY_VERIFICATION_SLICE_SCHEMA_VERSION = "evidence-quality-verification-slice/v1"
SCAE_READINESS_RECONCILIATION_SCHEMA_VERSION = "scae-readiness-reconciliation/v1"
VERIFICATION_BUNDLE_SCHEMA_VERSION = "researcher-verification-bundle/v1"
DIRECTION_VERIFIER_VERSION = "ads-ver-001-direction-verifier/v1"
QUALITY_VERIFIER_VERSION = "ads-ver-002-quality-verifier/v1"
SCAE_READINESS_VALIDATOR_VERSION = "ads-ver-003-scae-readiness-validator/v1"

DIRECTION_VERIFICATION_SURFACE = "evidence_direction_verification_slices"
QUALITY_VERIFICATION_SURFACE = "evidence_quality_verification_slices"
SCAE_READINESS_SURFACE = "scae_readiness_reconciliation"

ALLOWED_IMPACT_DIRECTIONS = {"supports_yes", "supports_no", "neutral"}
VERIFIED_DIRECTIONS = {"supports_yes", "supports_no", "neutral", "ambiguous", "excluded"}
METHOD_STATUSES = {"verified", "ambiguous", "quarantined", "excluded"}

QUALITY_FIELDS = (
    "source_authority",
    "directness",
    "recency",
    "specificity",
    "classification_confidence",
)
QUALITY_VALUE_ORDER = {
    "source_authority": ("unknown", "low", "medium", "high"),
    "directness": ("unknown", "background", "indirect", "direct"),
    "recency": ("unknown", "stale", "timeless", "fresh"),
    "specificity": ("unknown", "ambiguous", "general", "specific"),
    "classification_confidence": ("unknown", "low", "medium", "high"),
}
QUALITY_MULTIPLIER_FACTORS = {
    "source_authority": {"high": 1.0, "medium": 0.82, "low": 0.55, "unknown": 0.35},
    "directness": {"direct": 1.0, "indirect": 0.75, "background": 0.45, "unknown": 0.35},
    "recency": {"fresh": 1.0, "timeless": 0.9, "stale": 0.55, "unknown": 0.4},
    "specificity": {"specific": 1.0, "general": 0.75, "ambiguous": 0.45, "unknown": 0.35},
    "classification_confidence": {"high": 1.0, "medium": 0.75, "low": 0.45, "unknown": 0.35},
}
HIGH_AUTHORITY_SOURCE_CLASSES = {
    "official_or_primary",
    "market_rules_or_resolution_source",
    "market_price_or_orderbook",
}
MEDIUM_AUTHORITY_SOURCE_CLASSES = {"primary_reporting", "independent_secondary"}
LOW_AUTHORITY_SOURCE_CLASSES = {"social_or_user_generated"}
NON_CRITICAL_WEIGHTS = {"low", "medium", "normal"}
HIGH_CERTAINTY_SUFFICIENCY_STATUSES = {"scae_ready_high_certainty"}
ESCALATION_COMPLETE_STATUSES = {"complete", "completed", "not_required", "not_applicable"}


class VerificationError(ValueError):
    """Raised when researcher verification cannot proceed."""


@dataclass(frozen=True)
class DirectionVerificationResult:
    direction_verification_slices: list[dict[str, Any]]
    direction_verification_digest: str


@dataclass(frozen=True)
class QualityVerificationResult:
    quality_verification_slices: list[dict[str, Any]]
    quality_verification_digest: str


@dataclass(frozen=True)
class ScaeReadinessResult:
    readiness_reconciliation: dict[str, Any]
    readiness_digest: str
    ready_for_scae: bool
    blockers: list[dict[str, Any]]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(item)]


def _parse_timestamp(value: Any) -> datetime | None:
    if not _is_non_empty_string(value):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _classification_slices_from(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        slices = value.get("classification_slices")
    else:
        slices = value
    if not isinstance(slices, list):
        raise VerificationError("classification_slices must be a list")
    normalized: list[dict[str, Any]] = []
    for item in slices:
        if not isinstance(item, dict):
            raise VerificationError("classification_slices must contain objects")
        normalized.append(item)
    return normalized


def _provenance_slices_from(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        slices = value.get("provenance_slices", [])
    else:
        slices = value or []
    if not isinstance(slices, list):
        raise VerificationError("provenance_slices must be a list")
    return [item for item in slices if isinstance(item, dict)]


def _lookup_qdt_leaves(qdt: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(qdt, dict):
        return {}
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list):
        return {}
    return {
        str(leaf["leaf_id"]): leaf
        for leaf in leaves
        if isinstance(leaf, dict) and _is_non_empty_string(leaf.get("leaf_id"))
    }


def _leaf_static_weight(leaf: dict[str, Any] | None) -> str:
    weighting = (leaf or {}).get("bayesian_weighting")
    if isinstance(weighting, dict) and _is_non_empty_string(weighting.get("static_information_weight")):
        return str(weighting["static_information_weight"])
    return "medium"


def _market_constraints_from(
    market_reality_constraints: dict[str, Any] | None = None,
    evidence_packet: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if isinstance(market_reality_constraints, dict):
        return market_reality_constraints
    if isinstance(evidence_packet, dict) and isinstance(evidence_packet.get("market_reality_constraints"), dict):
        return evidence_packet["market_reality_constraints"]
    return None


def _market_constraints_digest(
    *,
    qdt: dict[str, Any] | None,
    classification_matrix: dict[str, Any] | None,
    market_constraints: dict[str, Any] | None,
    evidence_packet: dict[str, Any] | None,
) -> str | None:
    if isinstance(qdt, dict) and _is_non_empty_string(qdt.get("market_reality_constraints_digest")):
        return str(qdt["market_reality_constraints_digest"])
    if isinstance(qdt, dict) and isinstance(qdt.get("market_context"), dict):
        digest = qdt["market_context"].get("market_reality_constraints_digest")
        if _is_non_empty_string(digest):
            return str(digest)
    if isinstance(evidence_packet, dict) and _is_non_empty_string(evidence_packet.get("market_reality_constraints_digest")):
        return str(evidence_packet["market_reality_constraints_digest"])
    if isinstance(classification_matrix, dict):
        digest = classification_matrix.get("market_constraints_digest")
        if _is_non_empty_string(digest):
            return str(digest)
    if isinstance(market_constraints, dict):
        return _prefixed_sha256(market_constraints)
    return None


def _validate_binary_side_mapping(side_mapping: Any, contract_structure: Any) -> tuple[bool, list[str]]:
    reason_codes: list[str] = []
    if not isinstance(side_mapping, dict) or not side_mapping:
        return False, ["side_mapping_missing"]
    normalized_structure = str(contract_structure or "binary")
    if normalized_structure != "binary":
        return False, ["non_binary_side_mapping_ambiguous"]
    if set(side_mapping) != {"yes", "no"}:
        return False, ["side_mapping_conflict"]
    yes = side_mapping.get("yes")
    no = side_mapping.get("no")
    if not isinstance(yes, dict) or not isinstance(no, dict):
        return False, ["side_mapping_conflict"]
    yes_resolves = yes.get("resolves_to")
    no_resolves = no.get("resolves_to")
    if not _is_non_empty_string(yes.get("outcome")) or not _is_non_empty_string(no.get("outcome")):
        reason_codes.append("side_mapping_conflict")
    if not _is_non_empty_string(yes_resolves) or not _is_non_empty_string(no_resolves) or yes_resolves == no_resolves:
        reason_codes.append("side_mapping_conflict")
    return not reason_codes, sorted(set(reason_codes))


def _extracted_direction(classification: dict[str, Any], side_mapping: dict[str, Any]) -> str | None:
    extraction = classification.get("answer_value_extraction")
    if not isinstance(extraction, dict):
        return None
    candidate_values = []
    for field in (
        "market_side",
        "normalized_side",
        "side",
        "supports_side",
        "outcome",
        "resolved_outcome",
        "resolves_to",
        "value",
        "normalized_value",
    ):
        value = extraction.get(field)
        if _is_non_empty_string(value):
            candidate_values.append(str(value).strip().lower())
    if not candidate_values:
        return None
    yes_mapping = side_mapping.get("yes", {}) if isinstance(side_mapping, dict) else {}
    no_mapping = side_mapping.get("no", {}) if isinstance(side_mapping, dict) else {}
    yes_tokens = {
        "yes",
        str(yes_mapping.get("outcome", "")).strip().lower(),
        str(yes_mapping.get("resolves_to", "")).strip().lower(),
        "market_resolves_yes",
    }
    no_tokens = {
        "no",
        str(no_mapping.get("outcome", "")).strip().lower(),
        str(no_mapping.get("resolves_to", "")).strip().lower(),
        "market_resolves_no",
    }
    yes_tokens.discard("")
    no_tokens.discard("")
    saw_yes = any(value in yes_tokens for value in candidate_values)
    saw_no = any(value in no_tokens for value in candidate_values)
    if saw_yes and saw_no:
        return "ambiguous"
    if saw_yes:
        return "supports_yes"
    if saw_no:
        return "supports_no"
    return None


def _direction_slice(
    *,
    classification: dict[str, Any],
    market_constraints_digest: str | None,
    side_mapping_digest: str | None,
    claimed_direction: str,
    verified_direction: str,
    method_status: str,
    verification_status: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    seed = {
        "classification_slice_id": classification.get("slice_id"),
        "classification_id": classification.get("classification_id"),
        "claimed_direction": claimed_direction,
        "market_constraints_digest": market_constraints_digest,
        "side_mapping_digest": side_mapping_digest,
    }
    row = {
        "artifact_type": "evidence_direction_verification_slice",
        "schema_version": DIRECTION_VERIFICATION_SLICE_SCHEMA_VERSION,
        "surface_name": DIRECTION_VERIFICATION_SURFACE,
        "feature_id": "VER-001",
        "verification_slice_id": _sha_id("direction-verification", seed),
        "classification_slice_ref": classification.get("slice_id"),
        "classification_id": classification.get("classification_id"),
        "case_id": classification.get("case_id"),
        "dispatch_id": classification.get("dispatch_id"),
        "leaf_id": classification.get("leaf_id"),
        "condition_scope": classification.get("condition_scope"),
        "evidence_ref": classification.get("evidence_ref"),
        "claimed_direction": claimed_direction,
        "verified_direction": verified_direction,
        "side_mapping_digest": side_mapping_digest,
        "market_constraints_digest": market_constraints_digest,
        "method_status": method_status,
        "verification_status": verification_status,
        "accepted_for_scae": verification_status == "accepted",
        "reason_codes": sorted(set(reason_codes)),
        "verifier_version": DIRECTION_VERIFIER_VERSION,
    }
    row["direction_verification_slice_digest"] = _prefixed_sha256(row)
    return row


def build_direction_verification_slices(
    classification_matrix: dict[str, Any] | list[dict[str, Any]],
    *,
    qdt: dict[str, Any] | None = None,
    evidence_packet: dict[str, Any] | None = None,
    market_reality_constraints: dict[str, Any] | None = None,
) -> DirectionVerificationResult:
    """Build VER-001 direction verification slices for materialized CLS-003 rows."""

    classification_slices = _classification_slices_from(classification_matrix)
    matrix_obj = classification_matrix if isinstance(classification_matrix, dict) else None
    constraints = _market_constraints_from(market_reality_constraints, evidence_packet)
    side_mapping = constraints.get("side_mapping") if isinstance(constraints, dict) else None
    side_mapping_digest = _prefixed_sha256(side_mapping) if isinstance(side_mapping, dict) else None
    constraints_digest = _market_constraints_digest(
        qdt=qdt,
        classification_matrix=matrix_obj,
        market_constraints=constraints,
        evidence_packet=evidence_packet,
    )
    computed_constraints_digest = _prefixed_sha256(constraints) if isinstance(constraints, dict) else None
    constraints_digest_mismatch = bool(
        constraints_digest and computed_constraints_digest and constraints_digest != computed_constraints_digest
    )
    contract_structure = constraints.get("contract_structure") if isinstance(constraints, dict) else "binary"
    valid_side_mapping, side_mapping_reason_codes = _validate_binary_side_mapping(side_mapping, contract_structure)
    leaves_by_id = _lookup_qdt_leaves(qdt)

    rows: list[dict[str, Any]] = []
    for classification in classification_slices:
        claimed_direction = str(classification.get("impact_direction") or "")
        if claimed_direction not in ALLOWED_IMPACT_DIRECTIONS:
            rows.append(
                _direction_slice(
                    classification=classification,
                    market_constraints_digest=constraints_digest,
                    side_mapping_digest=side_mapping_digest,
                    claimed_direction=claimed_direction,
                    verified_direction="excluded",
                    method_status="excluded",
                    verification_status="excluded",
                    reason_codes=["invalid_claimed_direction"],
                )
            )
            continue

        if claimed_direction == "neutral":
            reason_codes = ["neutral_passthrough"]
            rows.append(
                _direction_slice(
                    classification=classification,
                    market_constraints_digest=constraints_digest,
                    side_mapping_digest=side_mapping_digest,
                    claimed_direction=claimed_direction,
                    verified_direction="neutral",
                    method_status="verified",
                    verification_status="accepted",
                    reason_codes=reason_codes,
                )
            )
            continue

        if constraints_digest_mismatch:
            rows.append(
                _direction_slice(
                    classification=classification,
                    market_constraints_digest=constraints_digest,
                    side_mapping_digest=side_mapping_digest,
                    claimed_direction=claimed_direction,
                    verified_direction="excluded",
                    method_status="excluded",
                    verification_status="excluded",
                    reason_codes=["market_constraints_digest_mismatch"],
                )
            )
            continue

        if not valid_side_mapping:
            if "non_binary_side_mapping_ambiguous" in side_mapping_reason_codes or "side_mapping_missing" in side_mapping_reason_codes:
                rows.append(
                    _direction_slice(
                        classification=classification,
                        market_constraints_digest=constraints_digest,
                        side_mapping_digest=side_mapping_digest,
                        claimed_direction=claimed_direction,
                        verified_direction="ambiguous",
                        method_status="quarantined",
                        verification_status="quarantined",
                        reason_codes=list(side_mapping_reason_codes) + ["direction_ambiguous"],
                    )
                )
            else:
                rows.append(
                    _direction_slice(
                        classification=classification,
                        market_constraints_digest=constraints_digest,
                        side_mapping_digest=side_mapping_digest,
                        claimed_direction=claimed_direction,
                        verified_direction="excluded",
                        method_status="excluded",
                        verification_status="excluded",
                        reason_codes=list(side_mapping_reason_codes) + ["side_mapping_conflict"],
                    )
                )
            continue

        extracted_direction = _extracted_direction(classification, side_mapping if isinstance(side_mapping, dict) else {})
        if extracted_direction == "ambiguous":
            rows.append(
                _direction_slice(
                    classification=classification,
                    market_constraints_digest=constraints_digest,
                    side_mapping_digest=side_mapping_digest,
                    claimed_direction=claimed_direction,
                    verified_direction="ambiguous",
                    method_status="quarantined",
                    verification_status="quarantined",
                    reason_codes=["direction_ambiguous", "answer_value_side_ambiguous"],
                )
            )
            continue
        if extracted_direction and extracted_direction != claimed_direction:
            rows.append(
                _direction_slice(
                    classification=classification,
                    market_constraints_digest=constraints_digest,
                    side_mapping_digest=side_mapping_digest,
                    claimed_direction=claimed_direction,
                    verified_direction="excluded",
                    method_status="excluded",
                    verification_status="excluded",
                    reason_codes=["side_mapping_conflict", "answer_value_side_contradiction"],
                )
            )
            continue

        rows.append(
            _direction_slice(
                classification=classification,
                market_constraints_digest=constraints_digest,
                side_mapping_digest=side_mapping_digest,
                claimed_direction=claimed_direction,
                verified_direction=claimed_direction,
                method_status="verified",
                verification_status="accepted",
                reason_codes=["side_mapping_verified"],
            )
        )

    accepted_by_leaf: dict[str, int] = {}
    problem_by_leaf: dict[str, int] = {}
    for row in rows:
        leaf_id = str(row.get("leaf_id") or "")
        if not leaf_id:
            continue
        if row["verification_status"] == "accepted":
            accepted_by_leaf[leaf_id] = accepted_by_leaf.get(leaf_id, 0) + 1
        else:
            problem_by_leaf[leaf_id] = problem_by_leaf.get(leaf_id, 0) + 1

    for row in rows:
        leaf_id = str(row.get("leaf_id") or "")
        accepted_count = accepted_by_leaf.get(leaf_id, 0)
        problem_count = problem_by_leaf.get(leaf_id, 0)
        if accepted_count > 0 and problem_count > 0:
            coverage_status = "covered_after_exclusion"
        elif accepted_count > 0:
            coverage_status = "covered"
        else:
            coverage_status = "blocked_after_exclusion"
        leaf = leaves_by_id.get(leaf_id)
        static_weight = _leaf_static_weight(leaf)
        deadlock_safe = (
            row["verification_status"] in {"excluded", "quarantined"}
            and coverage_status == "covered_after_exclusion"
            and static_weight in NON_CRITICAL_WEIGHTS
        )
        row["coverage_after_exclusion_status"] = coverage_status
        row["accepted_direction_slice_count_for_leaf"] = accepted_count
        row["excluded_or_quarantined_direction_slice_count_for_leaf"] = problem_count
        row["leaf_static_information_weight"] = static_weight
        row["deadlock_safe_exclusion"] = deadlock_safe
        if deadlock_safe:
            row["reason_codes"] = sorted(
                set(row["reason_codes"] + ["deadlock_safe_exclusion_with_remaining_coverage"])
            )
        row["direction_verification_slice_digest"] = _prefixed_sha256(
            {key: value for key, value in row.items() if key != "direction_verification_slice_digest"}
        )

    rows.sort(key=lambda item: (str(item["verification_slice_id"]), _canonical_json(item)))
    digest = _prefixed_sha256(
        {
            "schema_version": "direction-verification-digest/v1",
            "direction_verification_slice_schema_version": DIRECTION_VERIFICATION_SLICE_SCHEMA_VERSION,
            "direction_verification_slices": rows,
        }
    )
    for row in rows:
        row["direction_verification_digest"] = digest
    return DirectionVerificationResult(rows, digest)


def _evidence_by_ref(retrieval_packet: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(retrieval_packet, dict):
        return {}
    by_ref: dict[str, dict[str, Any]] = {}
    for result in retrieval_packet.get("leaf_retrieval_results", []):
        if not isinstance(result, dict):
            continue
        for evidence in result.get("selected_evidence", []):
            if isinstance(evidence, dict) and _is_non_empty_string(evidence.get("evidence_ref")):
                by_ref[str(evidence["evidence_ref"])] = evidence
    return by_ref


def _provenance_by_slice_ref(provenance_slices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_ref: dict[str, dict[str, Any]] = {}
    for provenance in provenance_slices:
        ref = provenance.get("classification_slice_ref")
        if _is_non_empty_string(ref):
            by_ref[str(ref)] = provenance
    return by_ref


def _claimed_quality_fields(classification: dict[str, Any]) -> dict[str, str]:
    dimensions = classification.get("evidence_quality_dimensions")
    claimed = copy.deepcopy(dimensions) if isinstance(dimensions, dict) else {}
    claimed["classification_confidence"] = classification.get("classification_confidence")
    return {field: _normalize_quality_value(field, claimed.get(field)) for field in QUALITY_FIELDS}


def _normalize_quality_value(field: str, value: Any) -> str:
    if not _is_non_empty_string(value):
        return "unknown"
    text = str(value).strip().lower()
    return text if text in QUALITY_VALUE_ORDER[field] else "unknown"


def _source_authority_from_source_class(source_class: Any) -> str:
    if source_class in HIGH_AUTHORITY_SOURCE_CLASSES:
        return "high"
    if source_class in MEDIUM_AUTHORITY_SOURCE_CLASSES:
        return "medium"
    if source_class in LOW_AUTHORITY_SOURCE_CLASSES:
        return "low"
    return "unknown"


def _directness_from_classification(classification: dict[str, Any], provenance: dict[str, Any] | None) -> str:
    strength = classification.get("evidence_strength")
    extraction = classification.get("answer_value_extraction")
    parsed_value = isinstance(extraction, dict) and extraction.get("normalization_status") == "parsed"
    if strength in {"definitive", "strong"} and parsed_value:
        return "direct"
    if strength in {"definitive", "strong", "moderate"}:
        return "indirect"
    if strength in {"weak", "none"}:
        return "background"
    if strength == "unanswerable":
        return "unknown"
    if isinstance(provenance, dict) and _is_non_empty_string(provenance.get("claim_family_id")):
        return "indirect"
    return "unknown"


def _recency_from_evidence(classification: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    status = (evidence or classification).get("temporal_gate_status")
    if status == "pass":
        return "fresh"
    if status == "fail":
        return "stale"
    if status == "unknown_not_counted":
        return "unknown"

    published = _parse_timestamp((evidence or {}).get("source_published_at"))
    cutoff = _parse_timestamp((evidence or {}).get("source_cutoff_timestamp") or classification.get("source_cutoff_timestamp"))
    if published and cutoff:
        if published <= cutoff:
            return "fresh"
        return "stale"
    if (evidence or classification).get("source_class") == "market_rules_or_resolution_source":
        return "timeless"
    return "unknown"


def _specificity_from_classification(classification: dict[str, Any], provenance: dict[str, Any] | None) -> str:
    extraction = classification.get("answer_value_extraction")
    if isinstance(extraction, dict) and extraction.get("normalization_status") == "parsed":
        return "specific"
    if _is_non_empty_string(classification.get("claim_family_id")):
        return "specific"
    if isinstance(provenance, dict) and _is_non_empty_string(provenance.get("claim_family_id")):
        return "specific"
    if classification.get("claim_split_status") == "split_from_evidence_claim_families":
        return "general"
    return "unknown"


def _classification_confidence_from_classification(classification: dict[str, Any]) -> str:
    claimed = _normalize_quality_value("classification_confidence", classification.get("classification_confidence"))
    strength = classification.get("evidence_strength")
    if strength in {"weak", "none", "unanswerable"}:
        return "low"
    if strength == "moderate" and claimed == "high":
        return "medium"
    return claimed


def _machine_normalized_quality_fields(
    classification: dict[str, Any],
    provenance: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> dict[str, str]:
    source_class = classification.get("source_class") or (provenance or {}).get("source_class") or (evidence or {}).get("source_class")
    return {
        "source_authority": _source_authority_from_source_class(source_class),
        "directness": _directness_from_classification(classification, provenance),
        "recency": _recency_from_evidence(classification, evidence),
        "specificity": _specificity_from_classification(classification, provenance),
        "classification_confidence": _classification_confidence_from_classification(classification),
    }


def _quality_score(field: str, value: str) -> int:
    try:
        return QUALITY_VALUE_ORDER[field].index(value)
    except ValueError:
        return 0


def _accepted_quality_fields(
    claimed: dict[str, str],
    normalized: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    accepted: dict[str, str] = {}
    reason_codes: list[str] = []
    for field in QUALITY_FIELDS:
        claimed_value = _normalize_quality_value(field, claimed.get(field))
        normalized_value = _normalize_quality_value(field, normalized.get(field))
        if _quality_score(field, normalized_value) < _quality_score(field, claimed_value):
            accepted[field] = normalized_value
            reason_codes.append(f"{field}_claim_downgraded")
        else:
            accepted[field] = claimed_value
            if normalized_value != claimed_value:
                reason_codes.append(f"{field}_claim_conservative")
    return accepted, reason_codes


def _quality_multiplier_inputs(accepted: dict[str, str]) -> dict[str, float]:
    return {
        field: QUALITY_MULTIPLIER_FACTORS[field].get(accepted.get(field, "unknown"), QUALITY_MULTIPLIER_FACTORS[field]["unknown"])
        for field in QUALITY_FIELDS
    }


def _quality_multiplier(accepted: dict[str, str]) -> tuple[float, dict[str, float]]:
    inputs = _quality_multiplier_inputs(accepted)
    value = 1.0
    for factor in inputs.values():
        value *= factor
    return round(max(0.05, min(1.0, value)), 6), inputs


def _quality_correlation_groups(
    classification: dict[str, Any],
    provenance: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> list[str]:
    groups: list[str] = []
    for prefix, field in (
        ("source_family", "source_family_id"),
        ("claim_family", "claim_family_id"),
        ("source_class", "source_class"),
        ("canonical_source", "canonical_source_id"),
    ):
        value = classification.get(field)
        if not _is_non_empty_string(value) and isinstance(provenance, dict):
            value = provenance.get(field)
        if not _is_non_empty_string(value) and isinstance(evidence, dict):
            value = evidence.get(field)
        if _is_non_empty_string(value):
            groups.append(f"{prefix}:{value}")
    return sorted(set(groups))


def _quality_slice(
    *,
    classification: dict[str, Any],
    claimed: dict[str, str],
    normalized: dict[str, str],
    accepted: dict[str, str],
    raw_multiplier: float,
    multiplier_inputs: dict[str, float],
    correlation_groups: list[str],
    quality_status: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    seed = {
        "classification_slice_id": classification.get("slice_id"),
        "classification_id": classification.get("classification_id"),
        "accepted_quality_fields": accepted,
    }
    row = {
        "artifact_type": "evidence_quality_verification_slice",
        "schema_version": QUALITY_VERIFICATION_SLICE_SCHEMA_VERSION,
        "surface_name": QUALITY_VERIFICATION_SURFACE,
        "feature_id": "VER-002",
        "quality_verification_slice_id": _sha_id("quality-verification", seed),
        "classification_slice_ref": classification.get("slice_id"),
        "classification_id": classification.get("classification_id"),
        "case_id": classification.get("case_id"),
        "dispatch_id": classification.get("dispatch_id"),
        "leaf_id": classification.get("leaf_id"),
        "condition_scope": classification.get("condition_scope"),
        "evidence_ref": classification.get("evidence_ref"),
        "claimed_quality_fields": claimed,
        "machine_normalized_quality_fields": normalized,
        "accepted_quality_fields": accepted,
        "raw_quality_multiplier": raw_multiplier,
        "raw_quality_multiplier_inputs": multiplier_inputs,
        "quality_correlation_groups": correlation_groups,
        "correlated_quality_floor_applied": False,
        "final_quality_multiplier": raw_multiplier,
        "quality_status": quality_status,
        "accepted_for_scae": quality_status == "accepted",
        "reason_codes": sorted(set(reason_codes)),
        "verifier_version": QUALITY_VERIFIER_VERSION,
    }
    row["quality_verification_slice_digest"] = _prefixed_sha256(row)
    return row


def build_quality_verification_slices(
    classification_matrix: dict[str, Any] | list[dict[str, Any]],
    *,
    provenance_slices: list[dict[str, Any]] | None = None,
    retrieval_packet: dict[str, Any] | None = None,
) -> QualityVerificationResult:
    """Build VER-002 quality verification slices for materialized CLS-003 rows."""

    classification_slices = _classification_slices_from(classification_matrix)
    matrix_provenance = _provenance_slices_from(classification_matrix)
    all_provenance = _provenance_slices_from(provenance_slices) if provenance_slices is not None else matrix_provenance
    provenance_by_ref = _provenance_by_slice_ref(all_provenance)
    evidence_by_ref = _evidence_by_ref(retrieval_packet)

    rows: list[dict[str, Any]] = []
    for classification in classification_slices:
        provenance = provenance_by_ref.get(str(classification.get("slice_id")))
        evidence = evidence_by_ref.get(str(classification.get("evidence_ref")))
        claimed = _claimed_quality_fields(classification)
        normalized = _machine_normalized_quality_fields(classification, provenance, evidence)
        accepted, reason_codes = _accepted_quality_fields(claimed, normalized)
        raw_multiplier, multiplier_inputs = _quality_multiplier(accepted)
        correlation_groups = _quality_correlation_groups(classification, provenance, evidence)
        if not classification.get("ledger_ready", True):
            quality_status = "excluded"
            reason_codes.append("classification_not_ledger_ready")
        elif all(accepted[field] == "unknown" for field in QUALITY_FIELDS):
            quality_status = "excluded"
            reason_codes.append("quality_all_unknown")
        else:
            quality_status = "accepted"
        if not reason_codes:
            reason_codes.append("quality_fields_accepted")
        rows.append(
            _quality_slice(
                classification=classification,
                claimed=claimed,
                normalized=normalized,
                accepted=accepted,
                raw_multiplier=raw_multiplier,
                multiplier_inputs=multiplier_inputs,
                correlation_groups=correlation_groups,
                quality_status=quality_status,
                reason_codes=reason_codes,
            )
        )

    rows.sort(key=lambda item: (str(item["quality_verification_slice_id"]), _canonical_json(item)))
    digest = _prefixed_sha256(
        {
            "schema_version": "quality-verification-digest/v1",
            "quality_verification_slice_schema_version": QUALITY_VERIFICATION_SLICE_SCHEMA_VERSION,
            "quality_verification_slices": rows,
        }
    )
    for row in rows:
        row["quality_verification_digest"] = digest
    return QualityVerificationResult(rows, digest)


def _verification_rows_from(value: Any, field: str, attribute: str) -> list[dict[str, Any]]:
    if hasattr(value, attribute):
        rows = getattr(value, attribute)
    elif isinstance(value, dict):
        rows = value.get(field, [])
    else:
        rows = value or []
    if not isinstance(rows, list):
        raise VerificationError(f"{field} must be a list")
    return [row for row in rows if isinstance(row, dict)]


def _direction_rows_from(value: Any) -> list[dict[str, Any]]:
    return _verification_rows_from(value, "direction_verification_slices", "direction_verification_slices")


def _quality_rows_from(value: Any) -> list[dict[str, Any]]:
    return _verification_rows_from(value, "quality_verification_slices", "quality_verification_slices")


def _classification_key(row: dict[str, Any]) -> str | None:
    for field in ("classification_slice_ref", "slice_id", "classification_id"):
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _index_by_classification(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        for field in ("classification_slice_ref", "classification_id"):
            value = row.get(field)
            if _is_non_empty_string(value):
                indexed[str(value)] = row
    return indexed


def _blocker(
    code: str,
    *,
    leaf_id: Any = None,
    classification_slice_ref: Any = None,
    classification_id: Any = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "code": code,
        "severity": "blocker",
    }
    if _is_non_empty_string(leaf_id):
        row["leaf_id"] = str(leaf_id)
    if _is_non_empty_string(classification_slice_ref):
        row["classification_slice_ref"] = str(classification_slice_ref)
    if _is_non_empty_string(classification_id):
        row["classification_id"] = str(classification_id)
    if details:
        row["details"] = copy.deepcopy(details)
    return row


def _append_blocker(
    blockers: list[dict[str, Any]],
    code: str,
    *,
    leaf_id: Any = None,
    classification: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocker = _blocker(
        code,
        leaf_id=leaf_id if leaf_id is not None else (classification or {}).get("leaf_id"),
        classification_slice_ref=(classification or {}).get("slice_id"),
        classification_id=(classification or {}).get("classification_id"),
        details=details,
    )
    blockers.append(blocker)
    return blocker


def _blocker_sort_key(blocker: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(blocker.get("leaf_id") or ""),
        str(blocker.get("classification_slice_ref") or ""),
        str(blocker.get("code") or ""),
        _canonical_json(blocker.get("details") or {}),
    )


def _ledger_source_key(row: dict[str, Any]) -> str | None:
    for field in ("source_ref", "canonical_source_id", "source_family_id", "source_metadata_resolution_ref"):
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _ledger_grain_key(row: dict[str, Any]) -> dict[str, str | None]:
    return {
        "claim_family_id": str(row["claim_family_id"]) if _is_non_empty_string(row.get("claim_family_id")) else None,
        "source_key": _ledger_source_key(row),
        "question_id": str(row.get("question_id") or row.get("leaf_id")) if _is_non_empty_string(row.get("question_id") or row.get("leaf_id")) else None,
        "condition_scope": str(row["condition_scope"]) if _is_non_empty_string(row.get("condition_scope")) else None,
    }


def _ledger_grain_missing_fields(grain: dict[str, str | None]) -> list[str]:
    return sorted(key for key, value in grain.items() if not _is_non_empty_string(value))


def _is_supplemental_row(row: dict[str, Any]) -> bool:
    return row.get("evidence_source_type") == "supplemental" or _is_non_empty_string(row.get("supplemental_evidence_ref"))


def _provenance_for_classification(
    classification: dict[str, Any],
    provenance_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    slice_id = classification.get("slice_id")
    if _is_non_empty_string(slice_id) and str(slice_id) in provenance_by_ref:
        return provenance_by_ref[str(slice_id)]
    provenance_ref = classification.get("provenance_slice_ref")
    if _is_non_empty_string(provenance_ref):
        for provenance in provenance_by_ref.values():
            if provenance.get("slice_id") == provenance_ref:
                return provenance
    return None


def _provenance_completeness_errors(classification: dict[str, Any], provenance: dict[str, Any] | None) -> list[str]:
    if not isinstance(provenance, dict):
        return ["provenance_slice_missing"]
    errors: list[str] = []
    for field in (
        "classification_slice_ref",
        "leaf_id",
        "condition_scope",
        "evidence_ref",
        "source_family_id",
        "claim_family_id",
        "research_sufficiency_certificate_ref",
        "coverage_proof_ref",
    ):
        if not _is_non_empty_string(provenance.get(field)):
            errors.append(f"provenance_{field}_missing")
    refs = provenance.get("provenance_refs")
    if not isinstance(refs, list) or not any(_is_non_empty_string(ref) for ref in refs):
        errors.append("provenance_refs_missing")
    for field in ("leaf_id", "condition_scope", "evidence_ref", "source_family_id", "claim_family_id"):
        if (
            _is_non_empty_string(classification.get(field))
            and _is_non_empty_string(provenance.get(field))
            and str(classification[field]) != str(provenance[field])
        ):
            errors.append(f"provenance_{field}_mismatch")
    if _is_non_empty_string(classification.get("provenance_slice_ref")) and provenance.get("slice_id") != classification.get(
        "provenance_slice_ref"
    ):
        errors.append("provenance_slice_ref_mismatch")
    return sorted(set(errors))


def _sufficiency_records_from(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for field in (
            "research_sufficiency_reconciliation_slices",
            "sufficiency_reconciliation_slices",
            "leaf_reconciliations",
            "reconciliation_slices",
            "slices",
        ):
            rows = value.get(field)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
        if _is_non_empty_string(value.get("leaf_id")):
            return [value]
    raise VerificationError("sufficiency_reconciliation must be an object or list")


def _first_string(row: dict[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _sufficiency_ref(row: dict[str, Any]) -> str | None:
    return _first_string(
        row,
        "research_sufficiency_reconciliation_ref",
        "research_sufficiency_reconciliation_id",
        "sufficiency_reconciliation_ref",
        "sufficiency_reconciliation_id",
        "reconciliation_ref",
        "reconciliation_id",
    )


def _sufficiency_status(row: dict[str, Any]) -> str | None:
    return _first_string(
        row,
        "research_sufficiency_reconciliation_status",
        "scae_readiness_status",
        "sufficiency_status",
        "status",
    )


def _sufficiency_certificate_ref(row: dict[str, Any]) -> str | None:
    return _first_string(
        row,
        "research_sufficiency_certificate_ref",
        "certificate_ref",
        "certificate_id",
    )


def _index_sufficiency_records(value: Any) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in _sufficiency_records_from(value):
        leaf_id = row.get("leaf_id")
        if _is_non_empty_string(leaf_id):
            indexed[str(leaf_id)] = row
    return indexed


def _escalation_records_from(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for field in ("escalation_decisions", "researcher_escalation_decisions", "decisions", "items"):
            rows = value.get(field)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
        if _is_non_empty_string(value.get("leaf_id")):
            return [value]
    raise VerificationError("escalation_decisions must be an object or list")


def _escalation_required(record: dict[str, Any]) -> bool:
    for field in ("required", "escalation_required", "researcher_escalation_required"):
        if record.get(field) is True:
            return True
    status = _first_string(record, "required_escalation_status", "escalation_status", "status")
    if status in {"required", "triggered", "pending", "incomplete", "delivery_failed"}:
        return True
    trigger_codes = record.get("trigger_codes")
    if isinstance(trigger_codes, list) and trigger_codes and int(record.get("additional_assignment_count") or 0) > 0:
        return True
    return False


def _escalation_complete(record: dict[str, Any]) -> bool:
    for field in ("required_escalation_complete", "escalation_complete", "complete"):
        if record.get(field) is True:
            return True
    status = _first_string(record, "completion_status", "required_escalation_status", "escalation_status", "status")
    if status in ESCALATION_COMPLETE_STATUSES:
        return True
    expected = int(record.get("additional_assignment_count") or record.get("required_assignment_count") or 0)
    if expected > 0:
        delivered = int(record.get("delivered_assignment_count") or 0)
        active = int(record.get("active_assignment_count") or 0)
        completed = int(record.get("completed_assignment_count") or 0)
        return completed >= expected and (delivered + active + completed) > 0
    return False


def _incomplete_escalation_leaf_ids(value: Any) -> set[str]:
    incomplete: set[str] = set()
    for record in _escalation_records_from(value):
        leaf_id = record.get("leaf_id")
        if _is_non_empty_string(leaf_id) and _escalation_required(record) and not _escalation_complete(record):
            incomplete.add(str(leaf_id))
    return incomplete


def _coverage_bundle_blockers(
    coverage_proof_bundle: dict[str, Any] | None,
    classification_matrix: dict[str, Any],
) -> list[dict[str, Any]]:
    if coverage_proof_bundle is None:
        return [_blocker("classification_coverage_proof_bundle_missing")]
    if not isinstance(coverage_proof_bundle, dict):
        raise VerificationError("coverage_proof_bundle must be an object")
    blockers: list[dict[str, Any]] = []
    if coverage_proof_bundle.get("feature_id") != "CLS-005":
        blockers.append(_blocker("classification_coverage_proof_bundle_not_cls005"))
    source_matrix = coverage_proof_bundle.get("source_matrix")
    if not isinstance(source_matrix, dict):
        blockers.append(_blocker("classification_coverage_source_matrix_missing"))
    elif source_matrix.get("matrix_digest") != classification_matrix.get("matrix_digest"):
        blockers.append(
            _blocker(
                "classification_coverage_matrix_digest_mismatch",
                details={
                    "coverage_matrix_digest": source_matrix.get("matrix_digest"),
                    "classification_matrix_digest": classification_matrix.get("matrix_digest"),
                },
            )
        )
    summary = coverage_proof_bundle.get("coverage_summary")
    if not isinstance(summary, dict):
        blockers.append(_blocker("classification_coverage_summary_missing"))
    else:
        for field in (
            "all_assigned_evidence_reviewed",
            "all_certificate_evidence_reviewed",
            "all_required_outputs_addressed",
            "all_context_isolation_audits_launch_allowed",
        ):
            if summary.get(field) is not True:
                blockers.append(_blocker("classification_coverage_summary_incomplete", details={"field": field}))
    for idx, proof in enumerate(coverage_proof_bundle.get("coverage_proofs", []) if isinstance(coverage_proof_bundle.get("coverage_proofs"), list) else []):
        if isinstance(proof, dict) and proof.get("coverage_status") != "complete":
            blockers.append(
                _blocker(
                    "classification_coverage_proof_incomplete",
                    leaf_id=proof.get("leaf_id"),
                    details={"coverage_proof_ref": proof.get("coverage_proof_ref") or proof.get("proof_id") or idx},
                )
            )
    return blockers


def _coverage_slices_by_leaf(classification_matrix: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_leaf: dict[str, list[dict[str, Any]]] = {}
    for row in classification_matrix.get("coverage_proof_slices", []):
        if isinstance(row, dict) and _is_non_empty_string(row.get("leaf_id")):
            by_leaf.setdefault(str(row["leaf_id"]), []).append(row)
    return by_leaf


def _structural_unanswerable_leaf_ids(classification_matrix: dict[str, Any]) -> set[str]:
    leaf_ids: set[str] = set()
    for leaf_id, rows in _coverage_slices_by_leaf(classification_matrix).items():
        if any(row.get("certificate_status") == "structurally_unanswerable" for row in rows):
            leaf_ids.add(leaf_id)
    return leaf_ids


def _dedupe_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for blocker in sorted(blockers, key=_blocker_sort_key):
        digest = _canonical_json(blocker)
        if digest not in seen:
            seen.add(digest)
            deduped.append(blocker)
    return deduped


def build_scae_readiness_reconciliation(
    classification_matrix: dict[str, Any],
    direction_verification_slices: list[dict[str, Any]] | dict[str, Any] | DirectionVerificationResult,
    quality_verification_slices: list[dict[str, Any]] | dict[str, Any] | QualityVerificationResult,
    *,
    qdt: dict[str, Any] | None = None,
    coverage_proof_bundle: dict[str, Any] | None = None,
    sufficiency_reconciliation: dict[str, Any] | list[dict[str, Any]] | None = None,
    escalation_decisions: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> ScaeReadinessResult:
    """Build VER-003 SCAE-readiness reconciliation without writing SCAE ledger rows.

    VER-004 remains outside this implementation. This validator only requires
    future sufficiency reconciliation refs and high-certainty status inputs.
    """

    if not isinstance(classification_matrix, dict):
        raise VerificationError("classification_matrix must be an object")
    classification_slices = _classification_slices_from(classification_matrix)
    provenance_slices = _provenance_slices_from(classification_matrix)
    provenance_by_ref = _provenance_by_slice_ref(provenance_slices)
    direction_rows = _direction_rows_from(direction_verification_slices)
    quality_rows = _quality_rows_from(quality_verification_slices)
    direction_by_classification = _index_by_classification(direction_rows)
    quality_by_classification = _index_by_classification(quality_rows)
    sufficiency_by_leaf = _index_sufficiency_records(sufficiency_reconciliation)
    incomplete_escalation_leaf_ids = _incomplete_escalation_leaf_ids(escalation_decisions)
    qdt_leaves = _lookup_qdt_leaves(qdt)
    required_leaf_ids = set(qdt_leaves) or {
        str(row["leaf_id"]) for row in classification_slices if _is_non_empty_string(row.get("leaf_id"))
    }
    structural_unanswerable_leaf_ids = _structural_unanswerable_leaf_ids(classification_matrix)

    blockers: list[dict[str, Any]] = []
    blockers.extend(_coverage_bundle_blockers(coverage_proof_bundle, classification_matrix))
    classification_leaf_ids = {
        str(row["leaf_id"]) for row in classification_slices if _is_non_empty_string(row.get("leaf_id"))
    }
    missing_classification_leaf_ids = sorted(required_leaf_ids - classification_leaf_ids - structural_unanswerable_leaf_ids)
    for leaf_id in missing_classification_leaf_ids:
        _append_blocker(blockers, "leaf_classification_coverage_missing", leaf_id=leaf_id)

    for leaf_id in sorted(structural_unanswerable_leaf_ids & required_leaf_ids):
        if _leaf_static_weight(qdt_leaves.get(leaf_id)) not in NON_CRITICAL_WEIGHTS:
            _append_blocker(blockers, "critical_unanswerable_leaf_policy_consequence", leaf_id=leaf_id)

    readiness_rows: list[dict[str, Any]] = []
    candidate_rows_by_grain: dict[str, list[dict[str, Any]]] = {}

    for classification in classification_slices:
        row_blockers: list[dict[str, Any]] = []
        reason_codes: list[str] = []
        classification_ref = _classification_key(classification)
        if not classification_ref:
            raise VerificationError("classification row missing slice_id and classification_id")
        leaf_id = classification.get("leaf_id")
        ledger_grain = _ledger_grain_key(classification)
        missing_grain_fields = _ledger_grain_missing_fields(ledger_grain)
        if missing_grain_fields:
            _append_blocker(
                row_blockers,
                "ledger_readiness_grain_incomplete",
                classification=classification,
                details={"missing_fields": missing_grain_fields},
            )

        provenance = _provenance_for_classification(classification, provenance_by_ref)
        provenance_errors = _provenance_completeness_errors(classification, provenance)
        for code in provenance_errors:
            _append_blocker(row_blockers, code, classification=classification)

        if _is_supplemental_row(classification):
            if not _is_non_empty_string(classification.get("normalized_supplemental_evidence_ref")):
                _append_blocker(row_blockers, "supplemental_normalization_missing", classification=classification)
            else:
                reason_codes.append("supplemental_evidence_normalized")

        direction_row = direction_by_classification.get(classification_ref) or direction_by_classification.get(
            str(classification.get("classification_id") or "")
        )
        direction_excluded_deadlock_safe = False
        claimed_direction = str(classification.get("impact_direction") or "")
        if claimed_direction != "neutral":
            if not direction_row:
                _append_blocker(row_blockers, "direction_verification_missing", classification=classification)
            elif direction_row.get("verification_status") == "accepted" and direction_row.get("accepted_for_scae") is not False:
                reason_codes.append("direction_verification_accepted")
            elif direction_row.get("deadlock_safe_exclusion") is True:
                direction_excluded_deadlock_safe = True
                reason_codes.append("deadlock_safe_exclusion_with_remaining_coverage")
            else:
                _append_blocker(
                    row_blockers,
                    "direction_verification_not_accepted",
                    classification=classification,
                    details={
                        "verification_status": direction_row.get("verification_status"),
                        "reason_codes": direction_row.get("reason_codes", []),
                    },
                )

        explicitly_included = classification.get("included_for_scae", classification.get("ledger_ready", True)) is not False
        if classification.get("ledger_ready", True) is not True and not direction_excluded_deadlock_safe:
            _append_blocker(row_blockers, "classification_not_ledger_ready", classification=classification)

        quality_row = quality_by_classification.get(classification_ref) or quality_by_classification.get(
            str(classification.get("classification_id") or "")
        )
        if explicitly_included and not direction_excluded_deadlock_safe:
            if not quality_row:
                _append_blocker(row_blockers, "quality_verification_missing", classification=classification)
            elif quality_row.get("quality_status") == "accepted" and quality_row.get("accepted_for_scae") is not False:
                reason_codes.append("quality_verification_accepted")
            else:
                _append_blocker(
                    row_blockers,
                    "quality_verification_not_accepted",
                    classification=classification,
                    details={
                        "quality_status": quality_row.get("quality_status"),
                        "reason_codes": quality_row.get("reason_codes", []),
                    },
                )

            sufficiency = sufficiency_by_leaf.get(str(leaf_id)) if _is_non_empty_string(leaf_id) else None
            if not sufficiency:
                _append_blocker(row_blockers, "research_sufficiency_reconciliation_missing", classification=classification)
            else:
                sufficiency_ref = _sufficiency_ref(sufficiency)
                sufficiency_status = _sufficiency_status(sufficiency)
                certificate_ref = _sufficiency_certificate_ref(sufficiency)
                if not _is_non_empty_string(sufficiency_ref):
                    _append_blocker(row_blockers, "research_sufficiency_reconciliation_ref_missing", classification=classification)
                if sufficiency_status not in HIGH_CERTAINTY_SUFFICIENCY_STATUSES:
                    _append_blocker(
                        row_blockers,
                        "research_sufficiency_not_scae_ready",
                        classification=classification,
                        details={"research_sufficiency_reconciliation_status": sufficiency_status},
                    )
                if not _is_non_empty_string(certificate_ref):
                    _append_blocker(row_blockers, "research_sufficiency_certificate_ref_missing", classification=classification)
                elif (
                    _is_non_empty_string(classification.get("research_sufficiency_certificate_ref"))
                    and str(classification["research_sufficiency_certificate_ref"]) != certificate_ref
                ):
                    _append_blocker(
                        row_blockers,
                        "research_sufficiency_certificate_ref_mismatch",
                        classification=classification,
                        details={
                            "classification_ref": classification.get("research_sufficiency_certificate_ref"),
                            "sufficiency_input_ref": certificate_ref,
                        },
                    )
                if sufficiency_ref and sufficiency_status in HIGH_CERTAINTY_SUFFICIENCY_STATUSES:
                    reason_codes.append("research_sufficiency_high_certainty_ref_present")

        if _is_non_empty_string(leaf_id) and str(leaf_id) in incomplete_escalation_leaf_ids:
            _append_blocker(row_blockers, "researcher_escalation_incomplete", classification=classification)
        if classification.get("required_escalation_complete") is False or classification.get("researcher_escalation_incomplete") is True:
            _append_blocker(row_blockers, "researcher_escalation_incomplete", classification=classification)

        row_blockers = _dedupe_blockers(row_blockers)
        if row_blockers:
            readiness_status = "blocked"
        elif direction_excluded_deadlock_safe:
            readiness_status = "excluded_deadlock_safe"
        elif explicitly_included:
            readiness_status = "ready_for_scae"
        else:
            readiness_status = "not_scae_bound"
            reason_codes.append("classification_not_included_for_scae")

        readiness_row = {
            "readiness_row_id": _sha_id(
                "scae-readiness-row",
                {
                    "classification_slice_ref": classification.get("slice_id"),
                    "classification_id": classification.get("classification_id"),
                    "ledger_grain": ledger_grain,
                },
            ),
            "classification_slice_ref": classification.get("slice_id"),
            "classification_id": classification.get("classification_id"),
            "leaf_id": leaf_id,
            "condition_scope": classification.get("condition_scope"),
            "evidence_ref": classification.get("evidence_ref"),
            "claim_family_id": classification.get("claim_family_id"),
            "source_key": ledger_grain["source_key"],
            "question_id": ledger_grain["question_id"],
            "ledger_readiness_grain": ledger_grain,
            "one_ledger_row_per_claim_source_question_condition_scope": readiness_status == "ready_for_scae",
            "direction_verification_ref": (direction_row or {}).get("verification_slice_id"),
            "direction_verification_status": (direction_row or {}).get("verification_status"),
            "quality_verification_ref": (quality_row or {}).get("quality_verification_slice_id"),
            "quality_verification_status": (quality_row or {}).get("quality_status"),
            "research_sufficiency_reconciliation_ref": _sufficiency_ref(sufficiency_by_leaf.get(str(leaf_id), {}))
            if _is_non_empty_string(leaf_id)
            else None,
            "research_sufficiency_reconciliation_status": _sufficiency_status(sufficiency_by_leaf.get(str(leaf_id), {}))
            if _is_non_empty_string(leaf_id)
            else None,
            "coverage_proof_ref": classification.get("coverage_proof_ref"),
            "normalized_supplemental_evidence_ref": classification.get("normalized_supplemental_evidence_ref"),
            "readiness_status": readiness_status,
            "blocker_codes": sorted({blocker["code"] for blocker in row_blockers}),
            "blockers": row_blockers,
            "reason_codes": sorted(set(reason_codes or ["scae_readiness_checks_applied"])),
        }
        readiness_row["readiness_row_digest"] = _prefixed_sha256(readiness_row)
        readiness_rows.append(readiness_row)
        if readiness_status == "ready_for_scae":
            grain_digest = _canonical_json(ledger_grain)
            candidate_rows_by_grain.setdefault(grain_digest, []).append(readiness_row)

    for grain_digest, rows in sorted(candidate_rows_by_grain.items()):
        if len(rows) <= 1:
            continue
        duplicate_refs = sorted(str(row["classification_slice_ref"]) for row in rows)
        for row in rows:
            duplicate = _blocker(
                "duplicate_ledger_readiness_grain",
                leaf_id=row.get("leaf_id"),
                classification_slice_ref=row.get("classification_slice_ref"),
                classification_id=row.get("classification_id"),
                details={"ledger_grain": json.loads(grain_digest), "duplicate_classification_slice_refs": duplicate_refs},
            )
            row["blockers"] = _dedupe_blockers(row["blockers"] + [duplicate])
            row["blocker_codes"] = sorted({blocker["code"] for blocker in row["blockers"]})
            row["readiness_status"] = "blocked"
            row["one_ledger_row_per_claim_source_question_condition_scope"] = False
            row["readiness_row_digest"] = _prefixed_sha256(
                {key: value for key, value in row.items() if key != "readiness_row_digest"}
            )

    blockers.extend(blocker for row in readiness_rows for blocker in row["blockers"])
    blockers = _dedupe_blockers(blockers)
    readiness_rows.sort(key=lambda item: (str(item["readiness_row_id"]), _canonical_json(item)))

    leaf_ids = sorted(required_leaf_ids | {str(row["leaf_id"]) for row in readiness_rows if _is_non_empty_string(row.get("leaf_id"))})
    leaf_readiness: list[dict[str, Any]] = []
    ready_classification_slice_refs: list[str] = []
    excluded_deadlock_safe_refs: list[str] = []
    for leaf_id in leaf_ids:
        rows = [row for row in readiness_rows if row.get("leaf_id") == leaf_id]
        row_blockers = [blocker for blocker in blockers if blocker.get("leaf_id") == leaf_id]
        ready_rows = [row for row in rows if row["readiness_status"] == "ready_for_scae"]
        deadlock_rows = [row for row in rows if row["readiness_status"] == "excluded_deadlock_safe"]
        if ready_rows and not row_blockers:
            status = "ready_for_scae"
            ready_classification_slice_refs.extend(str(row["classification_slice_ref"]) for row in ready_rows)
        elif leaf_id in structural_unanswerable_leaf_ids and _leaf_static_weight(qdt_leaves.get(leaf_id)) in NON_CRITICAL_WEIGHTS:
            status = "watch_only_structural_unanswerability"
        else:
            status = "blocked"
        excluded_deadlock_safe_refs.extend(str(row["classification_slice_ref"]) for row in deadlock_rows)
        leaf_readiness.append(
            {
                "leaf_id": leaf_id,
                "scae_readiness_status": status,
                "ready_classification_slice_refs": sorted(str(row["classification_slice_ref"]) for row in ready_rows),
                "excluded_deadlock_safe_classification_slice_refs": sorted(
                    str(row["classification_slice_ref"]) for row in deadlock_rows
                ),
                "blocker_codes": sorted({blocker["code"] for blocker in row_blockers}),
                "research_sufficiency_reconciliation_ref": _sufficiency_ref(sufficiency_by_leaf.get(leaf_id, {})),
                "research_sufficiency_reconciliation_status": _sufficiency_status(sufficiency_by_leaf.get(leaf_id, {})),
            }
        )

    ready_for_scae = not blockers and bool(ready_classification_slice_refs or structural_unanswerable_leaf_ids)
    source_direction_digest = (
        direction_verification_slices.direction_verification_digest
        if hasattr(direction_verification_slices, "direction_verification_digest")
        else (direction_verification_slices or {}).get("direction_verification_digest")
        if isinstance(direction_verification_slices, dict)
        else None
    )
    source_quality_digest = (
        quality_verification_slices.quality_verification_digest
        if hasattr(quality_verification_slices, "quality_verification_digest")
        else (quality_verification_slices or {}).get("quality_verification_digest")
        if isinstance(quality_verification_slices, dict)
        else None
    )
    seed = {
        "case_id": classification_matrix.get("case_id"),
        "dispatch_id": classification_matrix.get("dispatch_id"),
        "source_classification_matrix_digest": classification_matrix.get("matrix_digest"),
        "ready_classification_slice_refs": sorted(ready_classification_slice_refs),
        "blockers": blockers,
    }
    reconciliation = {
        "artifact_type": "scae_readiness_reconciliation",
        "schema_version": SCAE_READINESS_RECONCILIATION_SCHEMA_VERSION,
        "surface_name": SCAE_READINESS_SURFACE,
        "feature_id": "VER-003",
        "validator_version": SCAE_READINESS_VALIDATOR_VERSION,
        "reconciliation_id": _sha_id("scae-readiness-reconciliation", seed),
        "case_id": classification_matrix.get("case_id"),
        "dispatch_id": classification_matrix.get("dispatch_id"),
        "source_classification_matrix_id": classification_matrix.get("matrix_id"),
        "source_classification_matrix_digest": classification_matrix.get("matrix_digest"),
        "source_direction_verification_digest": source_direction_digest,
        "source_quality_verification_digest": source_quality_digest,
        "source_coverage_proof_bundle_digest": (coverage_proof_bundle or {}).get("bundle_digest")
        if isinstance(coverage_proof_bundle, dict)
        else None,
        "readiness_rows": readiness_rows,
        "leaf_readiness": leaf_readiness,
        "ready_for_scae": ready_for_scae,
        "ready_classification_slice_refs": sorted(ready_classification_slice_refs),
        "excluded_deadlock_safe_classification_slice_refs": sorted(set(excluded_deadlock_safe_refs)),
        "blockers": blockers,
        "blocker_codes": sorted({blocker["code"] for blocker in blockers}),
        "sufficiency_reconciliation_dependency": {
            "feature_id": "VER-004",
            "required_as_input": True,
            "implemented_by_ver003": False,
            "required_statuses": sorted(HIGH_CERTAINTY_SUFFICIENCY_STATUSES),
            "input_leaf_ids": sorted(sufficiency_by_leaf),
        },
        "authority_boundary": {
            "writes_scae_ledger_rows": False,
            "numeric_estimate_authority": False,
            "forecast_authority": False,
            "persistence_authority": False,
        },
        "scope_boundaries": {
            "implements": ["VER-003"],
            "requires": ["CLS-005", "VER-001", "VER-002", "VER-004 input refs/statuses"],
            "not_implemented": ["CLS-007", "VER-004", "SCAE", "forecast", "replay", "scoring", "persistence"],
        },
    }
    reconciliation["readiness_digest"] = _prefixed_sha256(reconciliation)
    return ScaeReadinessResult(
        readiness_reconciliation=reconciliation,
        readiness_digest=reconciliation["readiness_digest"],
        ready_for_scae=ready_for_scae,
        blockers=blockers,
    )


def validate_scae_readiness(
    classification_matrix: dict[str, Any],
    direction_slices: list[dict[str, Any]] | dict[str, Any] | DirectionVerificationResult,
    quality_slices: list[dict[str, Any]] | dict[str, Any] | QualityVerificationResult,
    sufficiency_reconciliation: dict[str, Any] | list[dict[str, Any]] | None,
    escalation_decisions: dict[str, Any] | list[dict[str, Any]] | None,
    qdt: dict[str, Any] | None,
    *,
    coverage_proof_bundle: dict[str, Any] | None = None,
) -> ScaeReadinessResult:
    """Validate Phase 8 readiness using the pseudocode-compatible argument order."""

    return build_scae_readiness_reconciliation(
        classification_matrix,
        direction_slices,
        quality_slices,
        qdt=qdt,
        coverage_proof_bundle=coverage_proof_bundle,
        sufficiency_reconciliation=sufficiency_reconciliation,
        escalation_decisions=escalation_decisions,
    )


def build_researcher_verification_bundle(
    classification_matrix: dict[str, Any],
    *,
    qdt: dict[str, Any] | None = None,
    evidence_packet: dict[str, Any] | None = None,
    market_reality_constraints: dict[str, Any] | None = None,
    retrieval_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a combined VER-001/VER-002 artifact bundle without persistence or SCAE rows."""

    if not isinstance(classification_matrix, dict):
        raise VerificationError("classification_matrix must be an object")
    direction = build_direction_verification_slices(
        classification_matrix,
        qdt=qdt,
        evidence_packet=evidence_packet,
        market_reality_constraints=market_reality_constraints,
    )
    quality = build_quality_verification_slices(classification_matrix, retrieval_packet=retrieval_packet)
    seed = {
        "case_id": classification_matrix.get("case_id"),
        "dispatch_id": classification_matrix.get("dispatch_id"),
        "direction_verification_digest": direction.direction_verification_digest,
        "quality_verification_digest": quality.quality_verification_digest,
    }
    bundle = {
        "artifact_type": "researcher_verification_bundle",
        "schema_version": VERIFICATION_BUNDLE_SCHEMA_VERSION,
        "feature_id": "VER-001+VER-002",
        "bundle_id": _sha_id("researcher-verification-bundle", seed),
        "case_id": classification_matrix.get("case_id"),
        "dispatch_id": classification_matrix.get("dispatch_id"),
        "source_classification_matrix_id": classification_matrix.get("matrix_id"),
        "source_classification_matrix_digest": classification_matrix.get("matrix_digest"),
        "direction_verification_surface": DIRECTION_VERIFICATION_SURFACE,
        "quality_verification_surface": QUALITY_VERIFICATION_SURFACE,
        "direction_verification_slices": direction.direction_verification_slices,
        "quality_verification_slices": quality.quality_verification_slices,
        "direction_verification_digest": direction.direction_verification_digest,
        "quality_verification_digest": quality.quality_verification_digest,
        "scope_boundaries": {
            "implements": ["VER-001", "VER-002"],
            "not_implemented": ["VER-003", "VER-004", "CLS-005", "CLS-007", "SCAE"],
            "writes_scae_ledger_rows": False,
            "model_calls": False,
            "production_forecasts": False,
        },
    }
    bundle["verification_bundle_digest"] = _prefixed_sha256(bundle)
    return bundle
