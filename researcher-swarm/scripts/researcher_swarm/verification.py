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
VERIFICATION_BUNDLE_SCHEMA_VERSION = "researcher-verification-bundle/v1"
DIRECTION_VERIFIER_VERSION = "ads-ver-001-direction-verifier/v1"
QUALITY_VERIFIER_VERSION = "ads-ver-002-quality-verifier/v1"

DIRECTION_VERIFICATION_SURFACE = "evidence_direction_verification_slices"
QUALITY_VERIFICATION_SURFACE = "evidence_quality_verification_slices"

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
