"""CLS-004 supplemental evidence normalization boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .retrieval import (
    ALLOWED_INDEPENDENCE_STATUSES,
    ALLOWED_RETRIEVAL_TRANSPORTS,
    ALLOWED_SOURCE_CLASSES,
    ALLOWED_TEMPORAL_GATE_STATUSES,
    PROTECTED_SOURCE_CLASSES,
    canonicalize_source_url,
    normalize_claim_tuple,
    validate_temporal_eligibility,
)


NORMALIZED_SUPPLEMENTAL_EVIDENCE_SCHEMA_VERSION = "normalized-supplemental-evidence/v1"
NORMALIZED_SUPPLEMENTAL_EVIDENCE_BATCH_SCHEMA_VERSION = "normalized-supplemental-evidence-batch/v1"
CLS_004_SUPPLEMENTAL_NORMALIZER_VERSION = "ads-cls-004-supplemental-normalizer/v1"

ALLOWED_SUPPLEMENTAL_NORMALIZATION_STATUSES = {
    "normalized",
    "degraded",
    "protected_primary_access_blocked",
    "rejected",
}
ALLOWED_SUPPLEMENTAL_ACCESS_STATUSES = {
    "verified",
    "metadata_fixture",
    "transient_fetch_failed",
    "protected_primary_access_blocked",
    "rejected",
}
FETCH_OK_STATUSES = {"", "ok", "fetched", "available", "verified", "metadata_fixture"}
TRANSIENT_FETCH_FAILURE_STATUSES = {
    "transient_fetch_failed",
    "transient_failure",
    "timeout",
    "network_error",
    "rate_limited",
    "temporary_unavailable",
}
PROTECTED_PRIMARY_BLOCKED_STATUSES = {
    "protected_primary_access_blocked",
    "blocked",
    "paywalled",
    "forbidden",
    "login_required",
}
CRITICAL_SCOPE_VALUES = {"critical", "source_of_truth", "critical_source_of_truth"}
FORBIDDEN_SUPPLEMENTAL_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "replacement",
    "log_odds",
    "scae_delta",
    "decision_recommendation",
)
UNKNOWN_CAPPED_SOURCE_CLASS = "unknown"
UNKNOWN_SOURCE_FAMILY_ID = "source-family-unknown"
UNKNOWN_CLAIM_FAMILY_ID = "claim-family-unknown"


class SupplementalEvidenceError(ValueError):
    """Raised when supplemental evidence normalization input is malformed."""


@dataclass(frozen=True)
class SupplementalEvidenceValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_004_SUPPLEMENTAL_NORMALIZER_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _hash_suffix(value: Any, length: int = 24) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_string_list(value: Any) -> list[str]:
    if _is_non_empty_string(value):
        return [str(value)]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(item)]


def _is_sha256_ref(value: Any) -> bool:
    return (
        _is_non_empty_string(value)
        and str(value).startswith("sha256:")
        and len(str(value)) == 71
        and all(ch in "0123456789abcdef" for ch in str(value)[7:])
    )


def _registrable_domain(url: str) -> str:
    if not url:
        return ""
    host = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    return ".".join(labels[-2:])


def _normalized_field_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).lower())
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _collect_forbidden_keys(value: Any, errors: list[str], path: str = "raw_ref") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if any(fragment in normalized for fragment in FORBIDDEN_SUPPLEMENTAL_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in CLS-004 supplemental evidence metadata")
            _collect_forbidden_keys(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _collect_forbidden_keys(child, errors, f"{path}[{idx}]")


def _raw_payload(raw_ref: Any, metadata_by_ref: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    if _is_non_empty_string(raw_ref):
        payload = {"supplemental_evidence_ref": str(raw_ref)}
    elif isinstance(raw_ref, dict):
        payload = copy.deepcopy(raw_ref)
    else:
        raise SupplementalEvidenceError("raw supplemental evidence ref must be a string or object")
    ref = _supplemental_ref(payload)
    metadata = (metadata_by_ref or {}).get(ref)
    if isinstance(metadata, dict):
        merged = copy.deepcopy(metadata)
        merged.update(payload)
        payload = merged
    errors: list[str] = []
    _collect_forbidden_keys(payload, errors)
    if errors:
        raise SupplementalEvidenceError("; ".join(errors))
    return payload


def _supplemental_ref(raw: dict[str, Any]) -> str:
    for field in ("supplemental_evidence_ref", "normalized_supplemental_evidence_ref", "evidence_ref", "artifact_ref", "ref"):
        if _is_non_empty_string(raw.get(field)):
            return str(raw[field])
    seed = {
        "canonical_url": raw.get("canonical_url") or raw.get("url") or raw.get("requested_url"),
        "content_sha256": raw.get("content_sha256"),
        "leaf_id": raw.get("leaf_id"),
    }
    return _sha_id("supplemental-evidence", seed)


def _fetch_status(raw: dict[str, Any]) -> str:
    status = (
        raw.get("fetch_status")
        or raw.get("source_access_status")
        or raw.get("access_status")
        or raw.get("status")
        or ""
    )
    return str(status).strip().lower()


def _retrieval_transport(raw: dict[str, Any]) -> str:
    transport = str(raw.get("retrieval_transport") or raw.get("transport") or "manual_fixture")
    return transport if transport in ALLOWED_RETRIEVAL_TRANSPORTS else "manual_fixture"


def _source_class(raw: dict[str, Any]) -> tuple[str, str, list[str]]:
    source_class = str(raw.get("source_class") or raw.get("source_class_id") or "unknown")
    if source_class not in ALLOWED_SOURCE_CLASSES:
        return "unknown", "unknown", ["source_class_invalid"]
    method = str(raw.get("source_class_resolution_method") or "")
    has_proof = (
        raw.get("deterministic_source_class_proof") is True
        or method
        in {
            "manual_fixture",
            "official_url_hint",
            "market_rules_resolution_url",
            "source_registry",
            "structured_feed_registry",
            "db_registry",
            "deterministic_url_registry",
        }
        or _retrieval_transport(raw) == "manual_fixture"
    )
    if source_class in PROTECTED_SOURCE_CLASSES and not has_proof:
        return "unknown", "unknown", ["protected_primary_requires_deterministic_source_class_proof"]
    return source_class, method or ("manual_fixture" if has_proof else "supplied_metadata_fixture"), []


def _is_protected_primary(raw: dict[str, Any], source_class: str | None = None) -> bool:
    raw_source_class = raw.get("source_class") or raw.get("source_class_id")
    return (
        raw.get("is_protected_primary") is True
        or raw.get("protected_primary_required") is True
        or source_class in PROTECTED_SOURCE_CLASSES
        or raw_source_class in PROTECTED_SOURCE_CLASSES
    )


def _is_critical_or_source_of_truth(raw: dict[str, Any]) -> bool:
    requirements = raw.get("research_sufficiency_requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    values = {
        str(raw.get("criticality") or "").lower(),
        str(raw.get("leaf_static_weight") or "").lower(),
        str(raw.get("leaf_purpose") or raw.get("purpose") or "").lower(),
        str(raw.get("source_role") or raw.get("required_source_role") or "").lower(),
        str(requirements.get("static_information_weight") or "").lower(),
        str(requirements.get("leaf_purpose") or "").lower(),
    }
    return (
        raw.get("is_critical") is True
        or raw.get("is_source_of_truth") is True
        or raw.get("source_of_truth") is True
        or requirements.get("protected_primary_required") is True
        or bool(values & CRITICAL_SCOPE_VALUES)
    )


def _content_hash(
    raw: dict[str, Any],
    *,
    canonical_url: str,
    supplemental_ref: str,
    require_verified: bool,
) -> tuple[str | None, str]:
    if _is_sha256_ref(raw.get("content_sha256")):
        return str(raw["content_sha256"]), "supplied_content_sha256"
    for field in ("content", "extracted_text", "rendered_text", "snippet"):
        if _is_non_empty_string(raw.get(field)):
            return _prefixed_sha256(str(raw[field])), field
    if require_verified:
        return None, "missing_verified_content_hash"
    return (
        _prefixed_sha256(
            {
                "supplemental_evidence_ref": supplemental_ref,
                "canonical_url": canonical_url,
                "degraded_or_blocked": True,
            }
        ),
        "metadata_fixture_without_verified_content",
    )


def _source_family(raw: dict[str, Any], *, canonical_url: str, content_sha256: str) -> tuple[str, str, str]:
    explicit = raw.get("source_family_id")
    if _is_non_empty_string(explicit) and explicit != UNKNOWN_SOURCE_FAMILY_ID:
        return str(explicit), "supplied_metadata_fixture", "resolved"
    if _is_non_empty_string(raw.get("source_family_key")):
        return "source-family-" + _hash_suffix({"source_family_key": raw["source_family_key"]}), "source_family_key", "resolved"
    if _is_non_empty_string(raw.get("syndication_key")):
        return "source-family-" + _hash_suffix({"syndication": raw["syndication_key"]}), "syndication_key", "syndicated_copy"
    if _is_non_empty_string(raw.get("mirrored_api_family_key")):
        return "source-family-" + _hash_suffix({"api_mirror": raw["mirrored_api_family_key"]}), "mirrored_api_family_key", "mirrored_api_endpoint"
    if any(_is_non_empty_string(raw.get(field)) for field in ("content_sha256", "content", "extracted_text", "rendered_text", "snippet")):
        return "source-family-" + _hash_suffix({"content": content_sha256}), "content_sha256", "content_hash_dedupe"
    if canonical_url:
        return "source-family-" + _hash_suffix({"canonical_url": canonical_url}), "canonical_url", "resolved"
    domain = _registrable_domain(canonical_url)
    if domain:
        return "source-family-" + _hash_suffix({"domain": domain}), "registrable_domain", "resolved"
    return UNKNOWN_SOURCE_FAMILY_ID, "unknown", "unknown_not_counted"


def _canonical_source_id(source_family_id: str, canonical_url: str) -> str:
    return "source-" + _hash_suffix(
        {
            "source_family_id": source_family_id,
            "canonical_url": canonical_url,
            "registrable_domain": _registrable_domain(canonical_url),
        }
    )


def _event_source_family_id(raw: dict[str, Any], source_family_id: str) -> str:
    explicit = raw.get("event_source_family_id") or raw.get("event_family_id")
    if _is_non_empty_string(explicit):
        return str(explicit)
    return "event-source-family-" + _hash_suffix(
        {
            "source_family_id": source_family_id,
            "event_key": raw.get("event_key") or raw.get("leaf_id") or raw.get("claim_key"),
            "condition_scope": raw.get("condition_scope") or raw.get("leaf_condition_scope") or "unconditional",
        }
    )


def _claim_family(raw: dict[str, Any], *, supplemental_ref: str) -> tuple[str, str | None, str | None, dict[str, Any] | None, list[str]]:
    tuple_value = raw.get("claim_tuple") or raw.get("proposed_tuple") or raw.get("atomic_claim_tuple")
    if isinstance(tuple_value, dict):
        normalized = normalize_claim_tuple(tuple_value)
        normalized_sha = _prefixed_sha256(normalized)
        claim_family_id = "claim-family-" + normalized_sha.removeprefix("sha256:")[:24]
        polarityless = dict(normalized)
        contradiction_family_id = None
        if normalized.get("polarity") in {"affirmed", "negated"}:
            polarityless["polarity"] = "affirmed_or_negated"
            contradiction_family_id = "contradiction-family-" + _hash_suffix(polarityless)
        resolution = {
            "artifact_type": "supplemental_claim_family_resolution",
            "schema_version": "supplemental-claim-family-resolution/v1",
            "claim_family_resolution_id": _sha_id(
                "supplemental-claim-family-resolution",
                {"supplemental_evidence_ref": supplemental_ref, "tuple": normalized},
            ),
            "supplemental_evidence_ref": supplemental_ref,
            "claim_family_id": claim_family_id,
            "normalized_tuple": normalized,
            "normalized_tuple_sha256": normalized_sha,
            "contradiction_family_id": contradiction_family_id,
            "resolution_method": "deterministic_tuple_hash",
            "counts_toward_claim_family_breadth": True,
        }
        return claim_family_id, resolution["claim_family_resolution_id"], contradiction_family_id, resolution, []
    explicit = raw.get("claim_family_id")
    if _is_non_empty_string(explicit) and explicit != UNKNOWN_CLAIM_FAMILY_ID:
        resolution_id = _sha_id("supplemental-claim-family-resolution", {"ref": supplemental_ref, "claim_family_id": explicit})
        return str(explicit), resolution_id, None, None, ["claim_family_id_supplied_without_tuple"]
    return UNKNOWN_CLAIM_FAMILY_ID, None, None, None, ["claim_family_unknown_not_counted"]


def _independence_status(
    *,
    source_family_id: str,
    claim_family_id: str,
    source_family_status: str,
    seen_source_family_ids: set[str] | None,
    seen_claim_family_ids: set[str] | None,
) -> str:
    if source_family_id == UNKNOWN_SOURCE_FAMILY_ID or claim_family_id == UNKNOWN_CLAIM_FAMILY_ID:
        return "unknown_not_counted"
    if seen_claim_family_ids and claim_family_id in seen_claim_family_ids:
        return "same_claim_family"
    if seen_source_family_ids and source_family_id in seen_source_family_ids:
        return "same_source_family"
    if source_family_status in {"syndicated_copy", "mirrored_api_endpoint"}:
        return "same_source_family"
    return "independent"


def _dispatch_context(raw: dict[str, Any], dispatch_context: dict[str, Any] | None) -> dict[str, Any]:
    context = copy.deepcopy(dispatch_context or {})
    for field in ("case_id", "dispatch_id", "forecast_timestamp", "source_cutoff_timestamp"):
        if not context.get(field) and raw.get(field):
            context[field] = raw.get(field)
    return context


def _base_record(
    raw: dict[str, Any],
    *,
    supplemental_ref: str,
    canonical_url: str,
    source_access_status: str,
    normalization_status: str,
    admission_status: str,
    source_class: str = UNKNOWN_CAPPED_SOURCE_CLASS,
    source_class_resolution_method: str = "unknown",
    source_family_id: str = UNKNOWN_SOURCE_FAMILY_ID,
    source_family_resolution_method: str = "unknown",
    source_family_status: str = "unknown_not_counted",
    event_source_family_id: str | None = None,
    canonical_source_id: str = "source-unknown",
    claim_family_id: str = UNKNOWN_CLAIM_FAMILY_ID,
    claim_family_resolution_ref: str | None = None,
    claim_family_resolution: dict[str, Any] | None = None,
    contradiction_family_id: str | None = None,
    content_sha256: str | None = None,
    content_hash_basis: str = "unknown",
    temporal_gate_status: str = "unknown_not_counted",
    temporal_validation: dict[str, Any] | None = None,
    independence_status: str = "unknown_not_counted",
    counts_toward_breadth: bool = False,
    blockers: list[str] | None = None,
    rejection_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    seed = {
        "supplemental_evidence_ref": supplemental_ref,
        "canonical_url": canonical_url,
        "content_sha256": content_sha256,
        "normalization_status": normalization_status,
        "source_class": source_class,
        "source_family_id": source_family_id,
        "claim_family_id": claim_family_id,
    }
    normalization_id = _sha_id("normalized-supplemental", seed)
    source_metadata_resolution_ref = _sha_id(
        "supplemental-source-metadata",
        {
            "supplemental_evidence_ref": supplemental_ref,
            "canonical_url": canonical_url,
            "source_class": source_class,
            "source_family_id": source_family_id,
        },
    )
    row = {
        "artifact_type": "normalized_supplemental_evidence",
        "schema_version": NORMALIZED_SUPPLEMENTAL_EVIDENCE_SCHEMA_VERSION,
        "feature_id": "CLS-004",
        "normalizer_version": CLS_004_SUPPLEMENTAL_NORMALIZER_VERSION,
        "normalization_id": normalization_id,
        "supplemental_evidence_ref": supplemental_ref,
        "case_id": raw.get("case_id"),
        "dispatch_id": raw.get("dispatch_id"),
        "leaf_id": raw.get("leaf_id"),
        "parent_branch_id": raw.get("parent_branch_id"),
        "classification_id": raw.get("classification_id"),
        "normalization_status": normalization_status,
        "admission_status": admission_status,
        "source_access_status": source_access_status,
        "retrieval_transport": _retrieval_transport(raw),
        "requested_url": raw.get("requested_url") or raw.get("url") or raw.get("canonical_url") or "",
        "final_url": raw.get("final_url") or raw.get("url") or raw.get("canonical_url") or "",
        "canonical_url": canonical_url,
        "registrable_domain": _registrable_domain(canonical_url),
        "canonical_source_id": canonical_source_id,
        "source_metadata_resolution_ref": source_metadata_resolution_ref,
        "event_source_family_id": event_source_family_id or _event_source_family_id(raw, source_family_id),
        "source_family_id": source_family_id,
        "source_family_resolution_method": source_family_resolution_method,
        "source_family_status": source_family_status,
        "source_class": source_class,
        "source_class_resolution_method": source_class_resolution_method,
        "claim_family_id": claim_family_id,
        "claim_family_resolution_ref": claim_family_resolution_ref,
        "claim_family_resolution": claim_family_resolution,
        "contradiction_family_id": contradiction_family_id,
        "content_sha256": content_sha256,
        "content_hash_basis": content_hash_basis,
        "source_published_at": raw.get("source_published_at") or raw.get("published_at"),
        "source_updated_at": raw.get("source_updated_at"),
        "source_observed_at": raw.get("source_observed_at"),
        "temporal_gate_status": temporal_gate_status,
        "temporal_validation_ref": (temporal_validation or {}).get("temporal_validation_id"),
        "temporal_validation": temporal_validation,
        "independence_status": independence_status,
        "counts_toward_breadth": bool(counts_toward_breadth),
        "counts_toward_independence": independence_status == "independent" and temporal_gate_status == "pass",
        "blockers": sorted(set(blockers or [])),
        "rejection_reason_codes": sorted(set(rejection_reason_codes or [])),
        "degraded_path_policy": {
            "bounded_degraded_path": normalization_status == "degraded",
            "source_class_cap": UNKNOWN_CAPPED_SOURCE_CLASS if normalization_status == "degraded" else None,
            "critical_or_source_of_truth_allowed": False,
        },
        "authority_boundary": {
            "researcher_final_source_authority": False,
            "model_final_source_authority": False,
            "protected_primary_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
            "forecast_probability_authority": False,
            "scae_numeric_authority": False,
        },
    }
    row["normalization_digest"] = _prefixed_sha256(row)
    return row


def _rejected_record(
    raw: dict[str, Any],
    *,
    supplemental_ref: str,
    canonical_url: str,
    reasons: list[str],
    temporal_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = "fail" if temporal_validation and temporal_validation.get("temporal_gate_status") == "fail" else "unknown_not_counted"
    return _base_record(
        raw,
        supplemental_ref=supplemental_ref,
        canonical_url=canonical_url,
        source_access_status="rejected",
        normalization_status="rejected",
        admission_status="rejected",
        content_sha256=_content_hash(raw, canonical_url=canonical_url, supplemental_ref=supplemental_ref, require_verified=False)[0],
        content_hash_basis="rejected_metadata_fingerprint",
        temporal_gate_status=status,
        temporal_validation=temporal_validation,
        blockers=reasons,
        rejection_reason_codes=reasons,
    )


def normalize_supplemental_evidence(
    raw_ref: Any,
    dispatch_context: dict[str, Any] | None = None,
    *,
    metadata_by_ref: dict[str, dict[str, Any]] | None = None,
    seen_source_family_ids: set[str] | None = None,
    seen_claim_family_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Normalize one supplemental citation ref using supplied deterministic metadata."""

    raw = _raw_payload(raw_ref, metadata_by_ref)
    supplemental_ref = _supplemental_ref(raw)
    canonical_url = canonicalize_source_url(raw.get("canonical_url"), raw.get("final_url"), raw.get("requested_url"), raw.get("url"))
    fetch_status = _fetch_status(raw)
    source_class, source_class_method, source_class_errors = _source_class(raw)
    protected_primary = _is_protected_primary(raw, source_class)
    critical = _is_critical_or_source_of_truth(raw)

    if fetch_status in PROTECTED_PRIMARY_BLOCKED_STATUSES and protected_primary:
        content_sha256, basis = _content_hash(
            raw,
            canonical_url=canonical_url,
            supplemental_ref=supplemental_ref,
            require_verified=False,
        )
        return _base_record(
            raw,
            supplemental_ref=supplemental_ref,
            canonical_url=canonical_url,
            source_access_status="protected_primary_access_blocked",
            normalization_status="protected_primary_access_blocked",
            admission_status="omitted",
            source_class=source_class if source_class in PROTECTED_SOURCE_CLASSES else UNKNOWN_CAPPED_SOURCE_CLASS,
            source_class_resolution_method=source_class_method,
            content_sha256=content_sha256,
            content_hash_basis=basis,
            blockers=["protected_primary_access_blocked"],
        )

    if fetch_status in TRANSIENT_FETCH_FAILURE_STATUSES:
        if protected_primary:
            content_sha256, basis = _content_hash(
                raw,
                canonical_url=canonical_url,
                supplemental_ref=supplemental_ref,
                require_verified=False,
            )
            return _base_record(
                raw,
                supplemental_ref=supplemental_ref,
                canonical_url=canonical_url,
                source_access_status="protected_primary_access_blocked",
                normalization_status="protected_primary_access_blocked",
                admission_status="omitted",
                source_class=source_class if source_class in PROTECTED_SOURCE_CLASSES else UNKNOWN_CAPPED_SOURCE_CLASS,
                source_class_resolution_method=source_class_method,
                content_sha256=content_sha256,
                content_hash_basis=basis,
                blockers=["protected_primary_transient_fetch_blocked"],
            )
        if critical or raw.get("allow_degraded_path") is False:
            return _rejected_record(
                raw,
                supplemental_ref=supplemental_ref,
                canonical_url=canonical_url,
                reasons=["degraded_path_for_critical_or_source_of_truth_forbidden"],
            )
        content_sha256, basis = _content_hash(
            raw,
            canonical_url=canonical_url,
            supplemental_ref=supplemental_ref,
            require_verified=False,
        )
        return _base_record(
            raw,
            supplemental_ref=supplemental_ref,
            canonical_url=canonical_url,
            source_access_status="transient_fetch_failed",
            normalization_status="degraded",
            admission_status="omitted",
            source_class=UNKNOWN_CAPPED_SOURCE_CLASS,
            source_class_resolution_method="degraded_source_class_capped",
            content_sha256=content_sha256,
            content_hash_basis=basis,
            blockers=[
                "supplemental_fetch_transient_failed",
                "degraded_source_class_capped_unknown",
                "degraded_claim_family_unknown_not_counted",
            ],
        )

    if fetch_status not in FETCH_OK_STATUSES:
        return _rejected_record(
            raw,
            supplemental_ref=supplemental_ref,
            canonical_url=canonical_url,
            reasons=["supplemental_fetch_failed"],
        )

    if source_class_errors:
        return _rejected_record(
            raw,
            supplemental_ref=supplemental_ref,
            canonical_url=canonical_url,
            reasons=source_class_errors,
        )

    content_sha256, content_hash_basis = _content_hash(
        raw,
        canonical_url=canonical_url,
        supplemental_ref=supplemental_ref,
        require_verified=True,
    )
    if not content_sha256:
        return _rejected_record(
            raw,
            supplemental_ref=supplemental_ref,
            canonical_url=canonical_url,
            reasons=["content_hash_missing"],
        )

    temporal_validation = validate_temporal_eligibility(
        {
            **raw,
            "evidence_ref": supplemental_ref,
            "retrieval_transport": _retrieval_transport(raw),
            "canonical_url": canonical_url,
        },
        dispatch_context=_dispatch_context(raw, dispatch_context),
    )
    if temporal_validation.get("temporal_gate_status") == "fail":
        return _rejected_record(
            raw,
            supplemental_ref=supplemental_ref,
            canonical_url=canonical_url,
            reasons=["temporal_isolation_failed", *temporal_validation.get("rejection_reason_codes", [])],
            temporal_validation=temporal_validation,
        )

    source_family_id, source_family_method, source_family_status = _source_family(
        raw,
        canonical_url=canonical_url,
        content_sha256=content_sha256,
    )
    canonical_source_id = _canonical_source_id(source_family_id, canonical_url)
    claim_family_id, claim_family_resolution_ref, contradiction_family_id, claim_resolution, claim_blockers = _claim_family(
        raw,
        supplemental_ref=supplemental_ref,
    )
    independence_status = _independence_status(
        source_family_id=source_family_id,
        claim_family_id=claim_family_id,
        source_family_status=source_family_status,
        seen_source_family_ids=seen_source_family_ids,
        seen_claim_family_ids=seen_claim_family_ids,
    )
    blockers = list(claim_blockers)
    temporal_status = str(temporal_validation.get("temporal_gate_status"))
    if temporal_status != "pass":
        blockers.append(f"temporal_{temporal_status}")
    if source_class == "unknown":
        blockers.append("source_class_unknown_not_counted")
    if source_family_id == UNKNOWN_SOURCE_FAMILY_ID:
        blockers.append("source_family_unknown_not_counted")
    counts_toward_breadth = (
        source_class != "unknown"
        and source_family_id != UNKNOWN_SOURCE_FAMILY_ID
        and claim_family_id != UNKNOWN_CLAIM_FAMILY_ID
        and temporal_status == "pass"
        and independence_status == "independent"
    )
    return _base_record(
        raw,
        supplemental_ref=supplemental_ref,
        canonical_url=canonical_url,
        source_access_status="verified" if fetch_status != "metadata_fixture" else "metadata_fixture",
        normalization_status="normalized",
        admission_status="admitted",
        source_class=source_class,
        source_class_resolution_method=source_class_method,
        source_family_id=source_family_id,
        source_family_resolution_method=source_family_method,
        source_family_status=source_family_status,
        canonical_source_id=canonical_source_id,
        claim_family_id=claim_family_id,
        claim_family_resolution_ref=claim_family_resolution_ref,
        claim_family_resolution=claim_resolution,
        contradiction_family_id=contradiction_family_id,
        content_sha256=content_sha256,
        content_hash_basis=content_hash_basis,
        temporal_gate_status=temporal_status,
        temporal_validation=temporal_validation,
        independence_status=independence_status,
        counts_toward_breadth=counts_toward_breadth,
        blockers=blockers,
    )


def normalize_supplemental_evidence_batch(
    raw_refs: list[Any],
    dispatch_context: dict[str, Any] | None = None,
    *,
    metadata_by_ref: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a deterministic batch of supplemental evidence refs."""

    if not isinstance(raw_refs, list):
        raise SupplementalEvidenceError("raw_refs must be a list")
    records: list[dict[str, Any]] = []
    seen_source_family_ids: set[str] = set()
    seen_claim_family_ids: set[str] = set()
    for raw_ref in raw_refs:
        record = normalize_supplemental_evidence(
            raw_ref,
            dispatch_context,
            metadata_by_ref=metadata_by_ref,
            seen_source_family_ids=seen_source_family_ids,
            seen_claim_family_ids=seen_claim_family_ids,
        )
        records.append(record)
        if record.get("normalization_status") == "normalized":
            if _is_non_empty_string(record.get("source_family_id")) and record["source_family_id"] != UNKNOWN_SOURCE_FAMILY_ID:
                seen_source_family_ids.add(str(record["source_family_id"]))
            if _is_non_empty_string(record.get("claim_family_id")) and record["claim_family_id"] != UNKNOWN_CLAIM_FAMILY_ID:
                seen_claim_family_ids.add(str(record["claim_family_id"]))
    summary = {
        "normalized": sum(1 for item in records if item.get("normalization_status") == "normalized"),
        "degraded": sum(1 for item in records if item.get("normalization_status") == "degraded"),
        "protected_primary_access_blocked": sum(
            1 for item in records if item.get("normalization_status") == "protected_primary_access_blocked"
        ),
        "rejected": sum(1 for item in records if item.get("normalization_status") == "rejected"),
    }
    batch = {
        "artifact_type": "normalized_supplemental_evidence_batch",
        "schema_version": NORMALIZED_SUPPLEMENTAL_EVIDENCE_BATCH_SCHEMA_VERSION,
        "feature_id": "CLS-004",
        "normalizer_version": CLS_004_SUPPLEMENTAL_NORMALIZER_VERSION,
        "batch_id": _sha_id("normalized-supplemental-batch", {"records": [item["normalization_id"] for item in records]}),
        "records": records,
        "normalization_summary": summary,
        "scope_boundaries": {
            "implements": ["CLS-004"],
            "not_implemented": ["CLS-005", "CLS-007", "VER", "SCAE"],
        },
    }
    batch["batch_digest"] = _prefixed_sha256(batch)
    return batch


def validate_normalized_supplemental_evidence(record: Any) -> SupplementalEvidenceValidationResult:
    """Validate one normalized supplemental evidence record."""

    errors: list[str] = []
    if not isinstance(record, dict):
        return SupplementalEvidenceValidationResult(False, ("record must be an object",))
    for field in (
        "artifact_type",
        "schema_version",
        "normalization_id",
        "supplemental_evidence_ref",
        "normalization_status",
        "admission_status",
        "source_access_status",
        "canonical_source_id",
        "event_source_family_id",
        "source_family_id",
        "source_class",
        "claim_family_id",
        "content_sha256",
        "temporal_gate_status",
        "independence_status",
        "counts_toward_breadth",
        "blockers",
        "authority_boundary",
    ):
        if field not in record:
            errors.append(f"{field} is required")
    if record.get("artifact_type") != "normalized_supplemental_evidence":
        errors.append("artifact_type must be normalized_supplemental_evidence")
    if record.get("schema_version") != NORMALIZED_SUPPLEMENTAL_EVIDENCE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {NORMALIZED_SUPPLEMENTAL_EVIDENCE_SCHEMA_VERSION}")
    if record.get("feature_id") != "CLS-004":
        errors.append("feature_id must be CLS-004")
    status = record.get("normalization_status")
    if status not in ALLOWED_SUPPLEMENTAL_NORMALIZATION_STATUSES:
        errors.append("normalization_status is invalid")
    if record.get("source_access_status") not in ALLOWED_SUPPLEMENTAL_ACCESS_STATUSES:
        errors.append("source_access_status is invalid")
    if record.get("source_class") not in ALLOWED_SOURCE_CLASSES:
        errors.append("source_class is invalid")
    if record.get("temporal_gate_status") not in ALLOWED_TEMPORAL_GATE_STATUSES:
        errors.append("temporal_gate_status is invalid")
    if record.get("independence_status") not in ALLOWED_INDEPENDENCE_STATUSES:
        errors.append("independence_status is invalid")
    if not _is_sha256_ref(record.get("content_sha256")):
        errors.append("content_sha256 must be a sha256 ref")
    if not isinstance(record.get("counts_toward_breadth"), bool):
        errors.append("counts_toward_breadth must be boolean")
    if not isinstance(record.get("blockers"), list):
        errors.append("blockers must be a list")
    if status == "normalized":
        if record.get("admission_status") != "admitted":
            errors.append("normalized records must be admitted")
        if record.get("temporal_gate_status") == "fail":
            errors.append("normalized records cannot have temporal_gate_status fail")
    if status == "degraded":
        if record.get("admission_status") != "omitted":
            errors.append("degraded records must be omitted")
        if record.get("source_class") != UNKNOWN_CAPPED_SOURCE_CLASS:
            errors.append("degraded source_class must be capped to unknown")
        if record.get("source_family_id") != UNKNOWN_SOURCE_FAMILY_ID:
            errors.append("degraded source_family_id must be unknown")
        if record.get("claim_family_id") != UNKNOWN_CLAIM_FAMILY_ID:
            errors.append("degraded claim_family_id must be unknown")
        if record.get("counts_toward_breadth") is not False:
            errors.append("degraded records cannot count toward breadth")
    if status == "protected_primary_access_blocked":
        if record.get("source_access_status") != "protected_primary_access_blocked":
            errors.append("protected-primary blocked records must use protected_primary_access_blocked access status")
        if record.get("admission_status") != "omitted":
            errors.append("protected-primary blocked records must be omitted")
    if status == "rejected":
        if record.get("admission_status") != "rejected":
            errors.append("rejected records must have admission_status rejected")
        if not record.get("rejection_reason_codes"):
            errors.append("rejected records must include rejection_reason_codes")
    authority = record.get("authority_boundary")
    if not isinstance(authority, dict):
        errors.append("authority_boundary must be an object")
    else:
        for field in (
            "researcher_final_source_authority",
            "model_final_source_authority",
            "protected_primary_final_authority",
            "temporal_safety_final_authority",
            "research_sufficiency_authority",
            "forecast_probability_authority",
            "scae_numeric_authority",
        ):
            if authority.get(field) is not False:
                errors.append(f"authority_boundary.{field} must be false")
    digest = record.get("normalization_digest")
    if _is_sha256_ref(digest):
        payload = copy.deepcopy(record)
        payload.pop("normalization_digest", None)
        if digest != _prefixed_sha256(payload):
            errors.append("normalization_digest does not match record payload")
    else:
        errors.append("normalization_digest must be a sha256 ref")
    return SupplementalEvidenceValidationResult(not errors, tuple(errors))


def normalized_supplemental_records_by_ref(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return validated normalized supplemental records keyed by raw supplemental ref."""

    by_ref: dict[str, dict[str, Any]] = {}
    for idx, record in enumerate(records):
        validation = validate_normalized_supplemental_evidence(record)
        if not validation.valid:
            raise SupplementalEvidenceError(f"normalized_supplemental_evidence[{idx}] invalid: " + "; ".join(validation.errors))
        ref = str(record["supplemental_evidence_ref"])
        if ref in by_ref:
            raise SupplementalEvidenceError(f"duplicate normalized supplemental evidence ref: {ref}")
        by_ref[ref] = record
    return by_ref


def supplemental_record_as_classification_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Adapt an admitted supplemental record to the matrix evidence row shape."""

    validation = validate_normalized_supplemental_evidence(record)
    if not validation.valid:
        raise SupplementalEvidenceError("normalized supplemental evidence invalid: " + "; ".join(validation.errors))
    if record.get("normalization_status") != "normalized":
        raise SupplementalEvidenceError(
            f"{record.get('supplemental_evidence_ref')}: supplemental evidence is not normalized"
        )
    if record.get("temporal_gate_status") != "pass":
        raise SupplementalEvidenceError(
            f"{record.get('supplemental_evidence_ref')}: supplemental evidence temporal gate is not pass"
        )
    if record.get("source_class") == "unknown" or record.get("source_family_id") == UNKNOWN_SOURCE_FAMILY_ID:
        raise SupplementalEvidenceError(
            f"{record.get('supplemental_evidence_ref')}: supplemental evidence source metadata is not admissible"
        )
    if record.get("claim_family_id") == UNKNOWN_CLAIM_FAMILY_ID:
        raise SupplementalEvidenceError(
            f"{record.get('supplemental_evidence_ref')}: supplemental evidence claim family is not admissible"
        )
    return {
        "artifact_type": "supplemental_evidence_matrix_source",
        "schema_version": "supplemental-evidence-matrix-source/v1",
        "evidence_source_type": "supplemental",
        "evidence_ref": record["supplemental_evidence_ref"],
        "supplemental_evidence_ref": record["supplemental_evidence_ref"],
        "normalized_supplemental_evidence_ref": record["normalization_id"],
        "source_metadata_resolution_ref": record["source_metadata_resolution_ref"],
        "leaf_id": record.get("leaf_id"),
        "parent_branch_id": record.get("parent_branch_id"),
        "retrieval_transport": record.get("retrieval_transport"),
        "canonical_source_id": record.get("canonical_source_id"),
        "source_class": record.get("source_class"),
        "source_family_id": record.get("source_family_id"),
        "claim_family_ids": [record["claim_family_id"]],
        "claim_family_resolution_refs": [record["claim_family_resolution_ref"]]
        if _is_non_empty_string(record.get("claim_family_resolution_ref"))
        else [],
        "content_sha256": record.get("content_sha256"),
        "temporal_gate_status": record.get("temporal_gate_status"),
        "independence_status": record.get("independence_status"),
        "counts_toward_breadth": record.get("counts_toward_breadth"),
    }


def supplemental_record_as_provenance(record: dict[str, Any]) -> dict[str, Any]:
    """Adapt an admitted supplemental record to the matrix provenance row shape."""

    return {
        "artifact_type": "normalized_supplemental_evidence_provenance",
        "schema_version": "normalized-supplemental-evidence-provenance/v1",
        "provenance_id": record["normalization_id"],
        "evidence_ref": record["supplemental_evidence_ref"],
        "source_metadata_resolution_ref": record["source_metadata_resolution_ref"],
        "claim_family_resolution_refs": [record["claim_family_resolution_ref"]]
        if _is_non_empty_string(record.get("claim_family_resolution_ref"))
        else [],
    }
