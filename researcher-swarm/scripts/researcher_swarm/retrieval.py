"""RET-001 retrieval packet schema and deterministic query planning helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _add_orchestrator_scripts_to_path() -> None:
    configured = os.environ.get("ADS_ORCHESTRATOR_SCRIPTS")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(__file__).resolve().parents[3] / "orchestrator" / "scripts")
    for candidate in candidates:
        if candidate.is_dir():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            return


_add_orchestrator_scripts_to_path()

from predquant.ads_handoff import ArtifactManifestContext, build_artifact_manifest, canonical_json
from predquant.ads_stage_logging import (
    StageContext,
    build_stage_execution_event,
    build_stage_status_snapshot,
    validate_stage_execution_event,
    validate_stage_status_snapshot,
)


RETRIEVAL_PACKET_ARTIFACT_TYPE = "retrieval_packet"
RETRIEVAL_PACKET_MANIFEST_ARTIFACT_TYPE = "retrieval-packet"
RETRIEVAL_PACKET_SCHEMA_VERSION = "retrieval-packet/v1"
LEAF_QUERY_CONTEXT_SCHEMA_VERSION = "leaf-retrieval-query-context/v1"
LEAF_RETRIEVAL_RESULT_SCHEMA_VERSION = "leaf-retrieval-result/v1"
RETRIEVAL_EVIDENCE_SCHEMA_VERSION = "retrieval-evidence/v1"
RETRIEVAL_EVIDENCE_CHUNK_SCHEMA_VERSION = "retrieval-evidence-chunk/v1"
RETRIEVAL_EVIDENCE_SPAN_SCHEMA_VERSION = "retrieval-evidence-span/v1"
RETRIEVAL_CANDIDATE_RECORD_SCHEMA_VERSION = "retrieval-candidate-record/v1"
NATIVE_RESEARCH_ATTEMPT_SCHEMA_VERSION = "native-research-attempt/v1"
BROWSER_RETRIEVAL_ATTEMPT_SCHEMA_VERSION = "browser-retrieval-attempt/v1"
BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION = "browser-search-provider-diagnostic/v1"
SEARCH_CANDIDATE_URL_SCHEMA_VERSION = "search-candidate-url/v1"
SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION = "source-metadata-classifier/v1"
SOURCE_METADATA_CLASSIFIER_UNAVAILABLE_SCHEMA_VERSION = "source-metadata-classifier-unavailable/v1"
SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION = "source-metadata-resolution/v1"
ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION = "atomic-claim-candidate/v1"
CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION = "claim-family-resolution/v1"
RETRIEVAL_TEMPORAL_ELIGIBILITY_SCHEMA_VERSION = "retrieval-temporal-eligibility/v1"
RETRIEVAL_EVIDENCE_PROVENANCE_SCHEMA_VERSION = "retrieval-evidence-provenance/v1"
RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION = "retrieval-breadth-profile/v1"
RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION = "retrieval-breadth-coverage/v1"
CONTRADICTION_SEARCH_ATTEMPT_SCHEMA_VERSION = "contradiction-search-attempt/v1"
NEGATIVE_CHECK_ATTEMPT_SCHEMA_VERSION = "negative-check-attempt/v1"
RETRIEVAL_METADATA_FILL_DIAGNOSTIC_SCHEMA_VERSION = "retrieval-metadata-fill-diagnostic/v1"
PROTECTED_PRIMARY_ACCESS_FAILURE_SCHEMA_VERSION = "protected-primary-access-failure/v1"
EXPECTED_SOURCE_MISSINGNESS_CANDIDATE_SCHEMA_VERSION = "expected-source-missingness-candidate/v1"
RETRIEVAL_EXPANSION_ATTEMPT_SCHEMA_VERSION = "retrieval-expansion-attempt/v1"
RETRIEVAL_FALLBACK_STATE_SCHEMA_VERSION = "retrieval-fallback-state/v1"
RESEARCH_SUFFICIENCY_CERTIFICATE_SCHEMA_VERSION = "research-sufficiency-certificate/v1"
NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION = "native-research-candidate-discovery/v1"
NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION = "native-research-transport-diagnostic/v1"
RETRIEVAL_VALIDATOR_VERSION = "ads-ret-002-004-retrieval-schema/v1"
RETRIEVAL_QUERY_PLANNER_VERSION = "ads-ret-001-query-planner/v1"
RETRIEVAL_TEMPORAL_VALIDATOR_VERSION = "ads-ret-002-temporal-isolation/v1"
RETRIEVAL_PROVENANCE_NORMALIZER_VERSION = "ads-ret-004-provenance-normalizer/v1"
RETRIEVAL_SOURCE_ACCESS_TRACKER_VERSION = "ads-ret-005-source-access-missingness/v1"
RETRIEVAL_EXPANSION_FALLBACK_VERSION = "ads-ret-006-expansion-fallback/v1"
RETRIEVAL_BREADTH_EVALUATOR_VERSION = "ads-ret-009-breadth-profile-coverage/v1"
RESEARCH_SUFFICIENCY_CERTIFIER_VERSION = "ads-ret-008-research-sufficiency-dispatch-gate/v1"
NATIVE_RESEARCH_RESOLVER_VERSION = "ads-ret-010-native-diagnostic-resolver/v1"
SOURCE_METADATA_CLASSIFIER_VERSION = "ads-ret-011-source-metadata-classifier/v1"
OPENCLAW_BROWSER_PROVIDER_ID = "openclaw_web_fetch_browser"
SOURCE_METADATA_CLASSIFIER_LANE_ID = "source_metadata_classifier_assist"
SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE_ID = "source-metadata-classifier/v1"
SOURCE_METADATA_CLASSIFIER_MODEL_POLICY_REF = (
    "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json"
)
DEFAULT_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEY = "openai/gpt-5.4-mini"
DEFAULT_SOURCE_METADATA_CLASSIFIER_MODEL_ID = "gpt-5.4-mini"
ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS = (
    "openai/gpt-5.4-mini",
    "openai/gpt-5.4-nano",
    "openai/o4-mini",
    "openai/o3-mini",
)
SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE = (
    "Classify compact retrieval source metadata only. Return source class, "
    "source-family hints, syndication hints, visible date candidates, and "
    "atomic claim tuples; do not author probabilities, SCAE deltas, final "
    "protected-primary decisions, temporal-safety decisions, or research sufficiency."
)
SOURCE_METADATA_CLASSIFIER_FORBIDDEN_OUTPUTS = (
    "probability",
    "scae_evidence_delta",
    "research_sufficiency_certification",
    "claim_family_final_authority",
    "protected_primary_final_authority",
    "temporal_safety_final_authority",
    "decision_output",
)
NATIVE_RESEARCH_FORBIDDEN_OUTPUT_FRAGMENTS = (
    "probability",
    "forecast_probability",
    "fair_value",
    "scae_delta",
    "source_family_final_authority",
    "claim_family_final_authority",
    "temporal_safety_final_authority",
    "sufficiency_certification",
    "research_sufficiency",
    "decision_recommendation",
    "decision_output",
)
SEARCH_CANDIDATE_RANK_CAPS = {
    "primary_leaf_retrieval": 10,
    "contradiction_search": 6,
    "negative_check": 5,
}
NATIVE_RESEARCH_CANDIDATE_CAPS = {
    "critical_source_of_truth": 12,
    "high_direct_or_catalyst": 8,
    "normal_medium": 5,
    "mechanics_rules_only": 4,
}

ALLOWED_RETRIEVAL_TRANSPORTS = {
    "browser",
    "native_gpt_research",
    "structured_feed",
    "db",
    "manual_fixture",
}
ALLOWED_SOURCE_CLASSES = {
    "official_or_primary",
    "primary_reporting",
    "independent_secondary",
    "market_rules_or_resolution_source",
    "market_price_or_orderbook",
    "social_or_user_generated",
    "unknown",
}
ALLOWED_CONDITION_SCOPES = {
    "unconditional",
    "target_given_upstream",
    "target_given_not_upstream",
    "shared_context",
}
ALLOWED_INDEPENDENCE_STATUSES = {
    "independent",
    "same_source_family",
    "same_claim_family",
    "syndicated_copy",
    "derived_from_primary",
    "unknown_not_counted",
}
ALLOWED_TEMPORAL_GATE_STATUSES = {"pass", "fail", "unknown_not_counted"}
ALLOWED_ADMISSION_STATUSES = {"admitted", "omitted", "rejected"}
ALLOWED_CANDIDATE_STATUSES = {"selected", "omitted", "rejected", "pending"}
ALLOWED_BROWSER_EXTRACTION_STATUSES = {
    "accepted",
    "rejected",
    "paywalled",
    "blocked",
    "duplicate",
    "temporal_fail",
}
ALLOWED_NATIVE_ATTEMPT_STATUSES = {"accepted", "partial", "failed"}
ALLOWED_NATIVE_TRANSPORT_AVAILABILITY_STATUSES = {"available", "unavailable", "partial"}
ALLOWED_CLAIM_VALIDATION_STATUSES = {
    "accepted_for_normalization",
    "rejected_multi_claim",
    "rejected_no_span",
    "rejected_not_market_relevant",
    "rejected_temporal",
    "rejected_forbidden_output",
    "unknown_not_counted",
}
ALLOWED_CLASSIFIER_ACCEPTANCE_STATUSES = {
    "not_used",
    "accepted_source_class",
    "accepted_claim_tuple",
    "accepted_source_family_hint",
    "accepted_visible_date_candidate",
    "rejected",
    "contradicted",
    "classifier_unsupported",
    "unsupported_source_class",
    "unsupported",
}
ALLOWED_CLASSIFIER_CONFIDENCES = {"high", "medium", "low", "unknown"}
ALLOWED_CLASSIFIER_AVAILABILITY_STATUSES = {"available", "unavailable", "not_checked"}
ALLOWED_SYNDICATION_HINTS = {"reuters_copy", "ap_copy", "press_release_copy", "none", "unknown"}
ALLOWED_SOURCE_FAMILY_STATUSES = {
    "resolved",
    "same_source_family",
    "syndicated_copy",
    "mirrored_api_endpoint",
    "content_hash_dedupe",
    "unknown_not_counted",
}
ALLOWED_RESEARCH_SUFFICIENCY_STATUSES = {
    "certified_high_certainty",
    "blocked_insufficient_research",
    "blocked_missing_breadth",
    "blocked_stale",
    "blocked_temporal_invalid",
    "blocked_macro_fallback_only",
    "structurally_unanswerable",
}
ALLOWED_CLASSIFICATION_DISPATCH_STATUSES = {
    "blocked_until_certified",
    "allowed",
    "blocked_insufficient_research",
}
DEFAULT_LIVE_RETRIEVAL_TRANSPORT_ALLOWLIST = {
    "browser",
    "native_gpt_research",
    "structured_feed",
}
PROTECTED_SOURCE_CLASSES = {
    "official_or_primary",
    "market_rules_or_resolution_source",
    "market_price_or_orderbook",
}
DETERMINISTIC_SOURCE_CLASS_METHODS = {
    "manual_fixture",
    "official_url_hint",
    "market_rules_resolution_url",
    "source_registry",
    "structured_feed_registry",
    "db_registry",
    "deterministic_url_registry",
}
FORBIDDEN_RETRIEVAL_KEY_FRAGMENTS = (
    "probability",
    "forecast_probability",
    "production_forecast_prob",
    "fair_value",
    "scae_delta",
    "log_odds",
    "synthesis_conclusion",
    "decision_instruction",
    "replay_result",
    "replay_manifest",
    "replay_artifact",
    "outcome_scoring",
    "outcome_score",
    "resolved_outcome",
    "resolution_outcome",
    "market_prediction",
    "forecast_result",
    "raw_forecast_result",
    "prediction_result",
    "scorecard",
)
MAX_QUERY_VARIANTS = 7
MAX_QUERY_TEXT_CHARS = 360
MAX_REASON_CODE_LENGTH = 80


class RetrievalPacketError(ValueError):
    """Raised when a RET-001 retrieval packet or schema helper input is invalid."""


@dataclass(frozen=True)
class RetrievalValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": RETRIEVAL_VALIDATOR_VERSION,
        }


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_string(item) for item in value)


def _reason_codes_are_compact(value: Any) -> bool:
    return isinstance(value, list) and all(
        _is_non_empty_string(item) and len(item) <= MAX_REASON_CODE_LENGTH and " " not in item
        for item in value
    )


def _normalized_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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


def _timestamp_at_or_after(value: Any, boundary: Any) -> bool:
    parsed = _parse_timestamp(value)
    parsed_boundary = _parse_timestamp(boundary)
    if parsed is None or parsed_boundary is None:
        return False
    return parsed >= parsed_boundary


def _iso_or_none(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _iso_before_cutoff(value: Any) -> str:
    parsed = _parse_timestamp(value) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (parsed - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if _is_non_empty_string(value):
            return str(value).strip()
    return ""


def canonicalize_source_url(*urls: Any) -> str:
    raw = _first_non_empty(*urls)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "fbclid", "gclid"))
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


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


def _hash_suffix(value: Any, length: int = 24) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _content_sha256(candidate: dict[str, Any], canonical_url: str = "") -> str:
    existing = candidate.get("content_sha256")
    if _is_non_empty_string(existing):
        return str(existing)
    for field in ("content", "extracted_text", "rendered_text", "snippet"):
        if _is_non_empty_string(candidate.get(field)):
            return _prefixed_sha256(candidate[field])
    return _prefixed_sha256(
        {
            "canonical_url": canonical_url,
            "transport_attempt_ref": candidate.get("transport_attempt_ref"),
            "retrieval_transport": candidate.get("retrieval_transport"),
        }
    )


def _claim_contradiction_family_id(normalized: dict[str, Any]) -> str | None:
    polarity = normalized.get("polarity")
    if polarity not in {"affirmed", "negated"}:
        return None
    polarityless = dict(normalized)
    polarityless["polarity"] = "affirmed_or_negated"
    return "contradiction-family-" + _hash_suffix(polarityless)


def _bounded_query_text(value: str) -> str:
    value = _normalized_space(value)
    if len(value) <= MAX_QUERY_TEXT_CHARS:
        return value
    return value[: MAX_QUERY_TEXT_CHARS - 1].rstrip() + "..."


def _reject_forbidden_retrieval_keys(value: Any, errors: list[str], path: str = "retrieval") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_RETRIEVAL_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in RET-001 retrieval artifacts")
            _reject_forbidden_retrieval_keys(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_forbidden_retrieval_keys(child, errors, f"{path}[{idx}]")


def _ensure_no_forbidden_keys(value: Any, field: str) -> None:
    errors: list[str] = []
    _reject_forbidden_retrieval_keys(value, errors, field)
    if errors:
        raise RetrievalPacketError("; ".join(errors))


def _reject_forbidden_native_research_outputs(value: Any, errors: list[str], path: str = "native_research") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in NATIVE_RESEARCH_FORBIDDEN_OUTPUT_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in RET-010 native research candidate discovery")
            _reject_forbidden_native_research_outputs(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_forbidden_native_research_outputs(child, errors, f"{path}[{idx}]")


def _ensure_no_forbidden_native_research_outputs(value: Any, field: str) -> None:
    errors: list[str] = []
    _reject_forbidden_native_research_outputs(value, errors, field)
    _reject_forbidden_retrieval_keys(value, errors, field)
    if errors:
        raise RetrievalPacketError("; ".join(errors))


def _branch_index(qdt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    branches = qdt.get("branches")
    if not isinstance(branches, list):
        return {}
    return {branch.get("branch_id"): branch for branch in branches if isinstance(branch, dict)}


def _leaf_static_weight(leaf: dict[str, Any]) -> str:
    weighting = leaf.get("bayesian_weighting")
    if isinstance(weighting, dict) and isinstance(weighting.get("static_information_weight"), str):
        return weighting["static_information_weight"]
    return "medium"


def _volume_tier_for_leaf(leaf: dict[str, Any], requirements: dict[str, Any]) -> tuple[str, int, tuple[int, int], tuple[int, int], int]:
    purpose = leaf.get("purpose")
    weight = _leaf_static_weight(leaf)
    if purpose == "source_of_truth" or weight == "critical" or requirements.get("protected_primary_required") is True:
        return ("critical_source_of_truth", 5, (80, 120), (15, 25), 5)
    if weight == "high":
        return ("high", 4, (50, 80), (12, 16), 4)
    return ("normal", 3, (30, 50), (8, 12), 3)


def _source_class_targets(requirements: dict[str, Any]) -> list[str]:
    raw = requirements.get("required_source_classes", [])
    targets = []
    for item in raw if isinstance(raw, list) else []:
        if item == "market_or_exchange":
            targets.append("market_price_or_orderbook")
        elif item in ALLOWED_SOURCE_CLASSES:
            targets.append(item)
        else:
            targets.append("unknown")
    return sorted(set(targets)) or ["unknown"]


def _live_policy_thresholds_for_leaf(leaf: dict[str, Any], requirements: dict[str, Any]) -> dict[str, Any]:
    purpose = str(leaf.get("purpose") or "other")
    weight = _leaf_static_weight(leaf)
    protected = bool(requirements.get("protected_primary_required") or purpose == "source_of_truth")
    freshness_required = int(requirements.get("min_temporally_fresh_sources", 0) or 0) > 0
    if protected or weight == "critical":
        return {
            "tier": "critical_source_of_truth",
            "min_admitted_evidence_items": 5,
            "min_independent_source_families": 3,
            "min_independent_claim_families": 3,
            "min_temporally_fresh_sources": max(2 if freshness_required else 0, int(requirements.get("min_temporally_fresh_sources", 0) or 0)),
            "protected_primary_required": protected,
        }
    if purpose in {"direct_evidence", "catalyst"} or weight == "high":
        return {
            "tier": "high_direct_or_catalyst",
            "min_admitted_evidence_items": 5,
            "min_independent_source_families": 3,
            "min_independent_claim_families": 3,
            "min_temporally_fresh_sources": max(2 if freshness_required else 0, int(requirements.get("min_temporally_fresh_sources", 0) or 0)),
            "protected_primary_required": bool(requirements.get("protected_primary_required", False)),
        }
    if purpose == "resolution_mechanics":
        return {
            "tier": "mechanics_rules_only",
            "min_admitted_evidence_items": 2,
            "min_independent_source_families": 1,
            "min_independent_claim_families": 1,
            "min_temporally_fresh_sources": int(requirements.get("min_temporally_fresh_sources", 0) or 0),
            "protected_primary_required": bool(requirements.get("protected_primary_required", False)),
        }
    return {
        "tier": "normal_medium",
        "min_admitted_evidence_items": 3,
        "min_independent_source_families": 2,
        "min_independent_claim_families": 2,
        "min_temporally_fresh_sources": max(1 if freshness_required else 0, int(requirements.get("min_temporally_fresh_sources", 0) or 0)),
        "protected_primary_required": bool(requirements.get("protected_primary_required", False)),
    }


def _build_contradiction_queries(leaf: dict[str, Any], macro_question: str, market_terms: list[str]) -> list[str]:
    terms = " ".join(market_terms[:5])
    return [
        _bounded_query_text(
            f"{leaf.get('question_text', '')} contradiction contrary evidence no confirmation {terms} before cutoff"
        ),
        _bounded_query_text(
            f"{macro_question} conflicting reports dispute denial {terms} before cutoff"
        ),
    ]


def _build_negative_check_queries(leaf: dict[str, Any], checks: list[str], market_terms: list[str]) -> dict[str, list[str]]:
    variants: dict[str, list[str]] = {}
    terms = " ".join(market_terms[:5])
    for check in checks:
        variants[check] = [
            _bounded_query_text(f"{leaf.get('question_text', '')} {check} no confirmation {terms} before cutoff"),
        ]
    return variants


def build_retrieval_breadth_profile_placeholder(
    leaf: dict[str, Any],
    *,
    live_policy_overlay: bool = False,
) -> dict[str, Any]:
    requirements = copy.deepcopy(leaf.get("research_sufficiency_requirements", {}))
    source_targets = _source_class_targets(requirements)
    tier, variant_count, raw_range, admitted_range, max_expansion = _volume_tier_for_leaf(leaf, requirements)
    live_thresholds = _live_policy_thresholds_for_leaf(leaf, requirements) if live_policy_overlay else {}
    min_claim_families = int(requirements.get("min_independent_claim_families", 0))
    min_source_families = int(requirements.get("min_independent_source_families", 0))
    min_fresh_sources = int(requirements.get("min_temporally_fresh_sources", 0))
    protected_primary_required = bool(requirements.get("protected_primary_required", False))
    if live_thresholds:
        min_claim_families = max(min_claim_families, int(live_thresholds["min_independent_claim_families"]))
        min_source_families = max(min_source_families, int(live_thresholds["min_independent_source_families"]))
        min_fresh_sources = max(min_fresh_sources, int(live_thresholds["min_temporally_fresh_sources"]))
        protected_primary_required = protected_primary_required or bool(live_thresholds["protected_primary_required"])
    profile_id = requirements.get("retrieval_breadth_profile_ref")
    if not _is_non_empty_string(profile_id):
        profile_id = "retrieval-breadth-profile:" + _sha_id("leaf", leaf.get("leaf_id", "unknown"))
    return {
        "artifact_type": "retrieval_breadth_profile",
        "schema_version": RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "leaf_id": leaf.get("leaf_id"),
        "source_class_requirements": {
            "required": source_targets,
            "protected_primary_required": protected_primary_required,
        },
        "claim_family_requirements": {
            "min_independent_claim_families": min_claim_families,
            "duplicate_same_claim_counts_once": True,
        },
        "source_family_requirements": {
            "min_independent_source_families": min_source_families,
            "wire_or_api_syndication_counts_once": True,
        },
        "freshness_requirement": {
            "recency_window_seconds": int(requirements.get("recency_window_seconds", 0)),
            "min_fresh_sources": min_fresh_sources,
        },
        "admitted_evidence_requirement": {
            "min_admitted_evidence_items": int(live_thresholds.get("min_admitted_evidence_items", 0)),
            "policy_source": "live_policy_overlay" if live_thresholds else "canonical_qdt_requirements",
        },
        "contradiction_search": {
            "required": bool(requirements.get("contradiction_search_required", False)),
            "query_variants": [],
        },
        "negative_checks": {
            "required_checks": list(requirements.get("required_negative_checks", [])),
            "query_variants_by_check": {},
        },
        "retrieval_volume_tier": {
            "tier": tier,
            "query_variant_count": variant_count,
            "raw_candidate_target_range": list(raw_range),
            "admitted_evidence_target_range": list(admitted_range),
            "max_targeted_expansion_attempts": int(requirements.get("max_targeted_expansion_attempts", max_expansion)),
        },
        "feature_gate_status": {
            "feature_id": "RET-009",
            "status": "implemented",
            "certification_behavior": "breadth_profile_and_coverage_only",
            "research_sufficiency_certificate_status": "not_started_RET_008",
        },
        "effective_policy_overlay": {
            "enabled": bool(live_policy_overlay),
            "policy_id": "ads-live-retrieval-policy/v1" if live_policy_overlay else None,
            "threshold_tier": live_thresholds.get("tier"),
            "canonical_requirements_preserved": True,
        },
    }


def compose_query_variants(
    *,
    macro_question: str,
    leaf: dict[str, Any],
    branch: dict[str, Any] | None = None,
    market_terms: list[str] | None = None,
    required_evidence_fields: list[str] | None = None,
    source_class_targets: list[str] | None = None,
    amrg_retrieval_hints: list[str] | None = None,
    variant_count: int = 3,
) -> list[dict[str, Any]]:
    leaf_question = _normalized_space(str(leaf.get("question_text", "")))
    macro = _normalized_space(str(macro_question or ""))
    purpose = _normalized_space(str(leaf.get("purpose", "other"))).replace("_", " ")
    condition_scope = str(leaf.get("leaf_condition_scope", "unconditional"))
    terms = " ".join((market_terms or [])[:8])
    fields = " ".join((required_evidence_fields or [])[:8])
    source_targets = " ".join((source_class_targets or [])[:4]).replace("_", " ")
    amrg_hints = " ".join((amrg_retrieval_hints or [])[:4])
    branch_label = ""
    if isinstance(branch, dict) and _is_non_empty_string(branch.get("branch_question")):
        branch_label = str(branch["branch_question"])

    condition_clause = ""
    if condition_scope != "unconditional":
        condition_clause = f" condition scope {condition_scope.replace('_', ' ')}"

    raw_variants = [
        f"{leaf_question} {macro} {terms} before source cutoff",
        f"{leaf_question} {purpose} evidence {fields} {source_targets}{condition_clause}",
        f"{macro} {leaf_question} official primary independent source {terms}",
        f"{leaf_question} {branch_label} market rules resolution source {fields}{condition_clause}",
        f"{leaf_question} latest direct evidence timestamp source {terms} before cutoff",
        f"{macro} {leaf_question} source of truth official database record {terms}",
        f"{leaf_question} independent secondary corroboration {terms} {fields}",
        f"{leaf_question} related market retrieval hint {amrg_hints} {terms}",
    ]

    seen: set[str] = set()
    variants: list[dict[str, Any]] = []
    for raw in raw_variants:
        text = _bounded_query_text(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        variants.append(
            {
                "query_variant_id": _sha_id("query", {"leaf_id": leaf.get("leaf_id"), "text": text}),
                "query_text": text,
                "query_text_sha256": _prefixed_sha256(text),
                "query_role": "primary_leaf_retrieval",
            }
        )
        if len(variants) >= min(MAX_QUERY_VARIANTS, max(1, variant_count)):
            break
    return variants


def _extract_direct_url_hints(value: Any, prefix: str = "root", limit: int = 12) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(child: Any, path: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(child, dict):
            for key, item in child.items():
                visit(item, f"{path}.{key}")
        elif isinstance(child, list):
            for idx, item in enumerate(child):
                visit(item, f"{path}[{idx}]")
        elif isinstance(child, str) and child.startswith(("http://", "https://")):
            found.append(
                {
                    "url": child,
                    "source_ref": path,
                    "direct_url_priority": "official_or_resolution_urls_first",
                }
            )

    visit(value, prefix)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in found:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)
    return deduped


def allowed_amrg_hint_refs(amrg_context: dict[str, Any] | None, leaf: dict[str, Any]) -> list[dict[str, Any]]:
    if not amrg_context:
        return []
    _ensure_no_forbidden_keys(amrg_context, "amrg_context")
    leaf_id = leaf.get("leaf_id")
    refs: list[dict[str, Any]] = []
    for key in ("amrg_usage_refs", "related_market_refs", "candidate_refs"):
        raw = amrg_context.get(key)
        if isinstance(raw, list):
            for idx, item in enumerate(raw[:12]):
                if isinstance(item, str) and item:
                    refs.append(
                        {
                            "hint_ref": item,
                            "hint_source": key,
                            "leaf_id": leaf_id,
                            "query_authority": "context_hint_only",
                        }
                    )
                elif isinstance(item, dict) and _is_non_empty_string(item.get("artifact_id")):
                    refs.append(
                        {
                            "hint_ref": item["artifact_id"],
                            "hint_source": key,
                            "leaf_id": leaf_id,
                            "query_authority": "context_hint_only",
                        }
                    )
    return refs


def amrg_retrieval_hint_texts(amrg_context: dict[str, Any] | None, leaf: dict[str, Any], limit: int = 4) -> list[str]:
    if not isinstance(amrg_context, dict):
        return []
    leaf_refs = set(str(ref) for ref in leaf.get("amrg_usage_refs", []) if _is_non_empty_string(ref))
    hints: list[str] = []

    def add_hint(value: Any) -> None:
        if len(hints) >= limit:
            return
        if _is_non_empty_string(value):
            text = _bounded_query_text(str(value))
            if text and text not in hints:
                hints.append(text)

    for collection_key in ("amrg_decomposer_context", "candidate_edges", "edge_records", "related_markets"):
        collection = amrg_context.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if len(hints) >= limit:
                break
            if not isinstance(item, dict):
                continue
            item_refs = {
                str(item.get(field))
                for field in ("edge_id", "artifact_id", "candidate_id", "market_id")
                if _is_non_empty_string(item.get(field))
            }
            if leaf_refs and item_refs and not (leaf_refs & item_refs):
                continue
            allowed_effects = item.get("allowed_effects")
            allowed_qdt_uses = item.get("allowed_qdt_uses")
            if isinstance(allowed_effects, list) and "retrieval_query_hint" not in allowed_effects:
                continue
            if isinstance(allowed_qdt_uses, list) and "retrieval_hint" not in allowed_qdt_uses:
                continue
            add_hint(
                item.get("retrieval_hint")
                or item.get("retrieval_query_hint")
                or item.get("question_text")
                or item.get("market_question")
                or item.get("title")
            )
    direct_hints = amrg_context.get("retrieval_query_hints")
    if isinstance(direct_hints, list):
        for item in direct_hints:
            if isinstance(item, dict):
                add_hint(item.get("query_text") or item.get("text") or item.get("hint"))
            else:
                add_hint(item)
    return hints[:limit]


def build_leaf_retrieval_query_context(
    *,
    qdt: dict[str, Any],
    leaf: dict[str, Any],
    branch: dict[str, Any] | None = None,
    evidence_packet: dict[str, Any] | None = None,
    amrg_context: dict[str, Any] | None = None,
    forecast_timestamp: str | None = None,
    source_cutoff_timestamp: str | None = None,
) -> dict[str, Any]:
    _ensure_no_forbidden_keys(leaf, "leaf")
    requirements = copy.deepcopy(leaf.get("research_sufficiency_requirements", {}))
    breadth_profile = build_retrieval_breadth_profile_placeholder(leaf)
    market_terms = list(leaf.get("market_component_terms", []))
    required_fields = list(leaf.get("required_evidence_fields", []))
    source_targets = breadth_profile["source_class_requirements"]["required"]
    tier = breadth_profile["retrieval_volume_tier"]
    amrg_hint_texts = amrg_retrieval_hint_texts(amrg_context, leaf)
    query_variants = compose_query_variants(
        macro_question=str(qdt.get("macro_question", "")),
        leaf=leaf,
        branch=branch,
        market_terms=market_terms,
        required_evidence_fields=required_fields,
        source_class_targets=source_targets,
        amrg_retrieval_hints=amrg_hint_texts,
        variant_count=int(tier["query_variant_count"]),
    )
    contradiction_variants = []
    if breadth_profile["contradiction_search"]["required"]:
        contradiction_variants = [
            {
                "query_variant_id": _sha_id("query", {"leaf_id": leaf.get("leaf_id"), "contradiction": text}),
                "query_text": text,
                "query_text_sha256": _prefixed_sha256(text),
                "query_role": "contradiction_search",
            }
            for text in _build_contradiction_queries(leaf, str(qdt.get("macro_question", "")), market_terms)
        ]
    negative_queries = _build_negative_check_queries(
        leaf,
        list(requirements.get("required_negative_checks", [])),
        market_terms,
    )
    direct_url_candidates = _extract_direct_url_hints(evidence_packet or {}, "evidence_packet")
    query_context = {
        "artifact_type": "leaf_retrieval_query_context",
        "schema_version": LEAF_QUERY_CONTEXT_SCHEMA_VERSION,
        "query_context_ref": _sha_id(
            "leaf-query-context",
            {
                "case_id": qdt.get("case_id"),
                "dispatch_id": qdt.get("dispatch_id"),
                "leaf_id": leaf.get("leaf_id"),
            },
        ),
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "leaf_id": leaf.get("leaf_id"),
        "parent_branch_id": leaf.get("parent_branch_id"),
        "leaf_question": leaf.get("question_text"),
        "macro_question": qdt.get("macro_question"),
        "purpose": leaf.get("purpose"),
        "condition_scope": leaf.get("leaf_condition_scope"),
        "market_component_terms": market_terms,
        "market_reality_constraints_digest": qdt.get("market_reality_constraints_digest"),
        "required_evidence_fields": required_fields,
        "sufficiency_requirements": requirements,
        "breadth_profile_ref": breadth_profile["profile_id"],
        "breadth_targets": {
            "source_class_targets": source_targets,
            "min_independent_claim_families": breadth_profile["claim_family_requirements"][
                "min_independent_claim_families"
            ],
            "min_independent_source_families": breadth_profile["source_family_requirements"][
                "min_independent_source_families"
            ],
            "min_temporally_fresh_sources": breadth_profile["freshness_requirement"]["min_fresh_sources"],
            "protected_primary_required": breadth_profile["source_class_requirements"][
                "protected_primary_required"
            ],
        },
        "query_variants": query_variants,
        "contradiction_query_variants": contradiction_variants,
        "negative_check_query_variants": negative_queries,
        "direct_url_candidates": direct_url_candidates,
        "amrg_hint_refs": allowed_amrg_hint_refs(amrg_context, leaf),
        "amrg_retrieval_hint_text_sha256": [_prefixed_sha256(text) for text in amrg_hint_texts],
        "forecast_timestamp": forecast_timestamp,
        "source_cutoff_timestamp": source_cutoff_timestamp,
        "planner_version": RETRIEVAL_QUERY_PLANNER_VERSION,
        "feature_gate_status": {
            "RET-002": "temporal_validator_available",
            "RET-003": "quality_scoring_pending",
            "RET-004": "provenance_resolution_available",
            "RET-008": "sufficiency_certificate_pending",
            "RET-009": "breadth_certification_pending",
            "RET-010": "native_transport_pending",
            "RET-011": "classifier_assist_pending",
        },
    }
    _ensure_no_forbidden_keys(query_context, "query_context")
    return query_context


def build_retrieval_query_contexts(
    qdt: dict[str, Any],
    *,
    evidence_packet: dict[str, Any] | None = None,
    amrg_context: dict[str, Any] | None = None,
    forecast_timestamp: str | None = None,
    source_cutoff_timestamp: str | None = None,
) -> list[dict[str, Any]]:
    if qdt.get("schema_version") != "question-decomposition/v1":
        raise RetrievalPacketError("qdt must be question-decomposition/v1")
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list) or not leaves:
        raise RetrievalPacketError("qdt must contain required_leaf_questions")
    branches = _branch_index(qdt)
    contexts = []
    for leaf in leaves:
        branch = branches.get(leaf.get("parent_branch_id"))
        contexts.append(
            build_leaf_retrieval_query_context(
                qdt=qdt,
                leaf=leaf,
                branch=branch,
                evidence_packet=evidence_packet,
                amrg_context=amrg_context,
                forecast_timestamp=forecast_timestamp,
                source_cutoff_timestamp=source_cutoff_timestamp,
            )
        )
    return contexts


def build_browser_search_provider_diagnostic(
    *,
    availability_status: str = "unavailable",
    checked_at: str | None = None,
    unavailable_reason: str | None = "not_checked_in_RET_001_schema_phase",
) -> dict[str, Any]:
    return {
        "artifact_type": "browser_search_provider_diagnostic",
        "schema_version": BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION,
        "provider_id": OPENCLAW_BROWSER_PROVIDER_ID,
        "provider_refs": ["openclaw:web_fetch", "openclaw:browser_transport"],
        "capabilities": ["web_search", "direct_url", "direct_url_fetch", "url_extraction", "configured_search_provider"],
        "availability_status": availability_status,
        "news_feed_api_enabled": False,
        "web_fetch_role": "url_fetch_extraction_only",
        "web_fetch_must_not_be_used_as_search": True,
        "search_requires_configured_provider": True,
        "direct_url_priority": "official_or_resolution_urls_first",
        "unavailable_reason": unavailable_reason,
        "checked_at": checked_at,
        "feature_gate_status": "browser_provider_resolution_pending_RET_004_RET_009",
    }


def _search_rank_cap(query_role: str) -> int:
    return SEARCH_CANDIDATE_RANK_CAPS.get(query_role, SEARCH_CANDIDATE_RANK_CAPS["primary_leaf_retrieval"])


def build_search_candidate_url(
    query_context: dict[str, Any],
    query_variant: dict[str, Any],
    *,
    rank: int,
    url: str,
    title: str = "",
    snippet: str = "",
    provider_id: str = OPENCLAW_BROWSER_PROVIDER_ID,
    searched_at: str | None = None,
    result_source: str = "configured_browser_search_provider",
    query_role: str | None = None,
) -> dict[str, Any]:
    if not _is_non_empty_string(url):
        raise RetrievalPacketError("search candidate URL is required")
    role = str(query_role or query_variant.get("query_role") or "primary_leaf_retrieval")
    if role not in SEARCH_CANDIDATE_RANK_CAPS:
        role = "primary_leaf_retrieval"
    rank_int = int(rank)
    if rank_int < 1 or rank_int > _search_rank_cap(role):
        raise RetrievalPacketError(f"{role} search rank {rank_int} exceeds cap {_search_rank_cap(role)}")
    canonical_url = canonicalize_source_url(url)
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "query_role": role,
        "rank": rank_int,
        "canonical_url": canonical_url,
        "provider_id": provider_id,
    }
    return {
        "artifact_type": "search_candidate_url",
        "schema_version": SEARCH_CANDIDATE_URL_SCHEMA_VERSION,
        "search_candidate_url_id": _sha_id("search-candidate-url", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "query_role": role,
        "rank": rank_int,
        "url": url,
        "canonical_url": canonical_url,
        "title_sha256": _prefixed_sha256(_bounded_excerpt(title, max_chars=240)),
        "snippet_sha256": _prefixed_sha256(_bounded_excerpt(snippet, max_chars=480)),
        "provider_id": provider_id,
        "searched_at": searched_at,
        "result_source": result_source,
        "rank_cap": _search_rank_cap(role),
        "web_fetch_used_for_search": False,
        "fetch_required_before_admission": True,
        "feature_id": "RET-001",
    }


def _native_research_candidate_cap(query_context: dict[str, Any]) -> int:
    targets = query_context.get("breadth_targets") if isinstance(query_context.get("breadth_targets"), dict) else {}
    purpose = str(query_context.get("purpose") or "")
    protected = bool(targets.get("protected_primary_required"))
    min_sources = int(targets.get("min_independent_source_families", 0) or 0)
    if protected or purpose == "source_of_truth":
        tier = "critical_source_of_truth"
    elif purpose in {"direct_evidence", "catalyst"} or min_sources >= 3:
        tier = "high_direct_or_catalyst"
    elif purpose == "resolution_mechanics":
        tier = "mechanics_rules_only"
    else:
        tier = "normal_medium"
    return NATIVE_RESEARCH_CANDIDATE_CAPS[tier]


def _compact_native_candidate(raw: dict[str, Any], query_context: dict[str, Any]) -> dict[str, Any]:
    _ensure_no_forbidden_native_research_outputs(raw, "native_research_candidate")
    url = str(raw.get("url") or raw.get("candidate_url") or "").strip()
    if not url:
        raise RetrievalPacketError("native research candidate URL is required")
    related_leaf_id = str(raw.get("related_leaf_id") or raw.get("leaf_id") or query_context.get("leaf_id") or "")
    return {
        "url": url,
        "canonical_url": canonicalize_source_url(url),
        "source_label": _bounded_excerpt(raw.get("source_label") or raw.get("title") or "unknown", max_chars=160),
        "why_it_may_matter": _bounded_excerpt(raw.get("why_it_may_matter") or raw.get("why_may_matter"), max_chars=360),
        "related_leaf_id": related_leaf_id,
        "candidate_claim_text": _bounded_excerpt(raw.get("candidate_claim_text") or raw.get("claim_text"), max_chars=480),
        "uncertainty_notes": _bounded_excerpt(raw.get("uncertainty_notes") or "", max_chars=360),
    }


def build_native_research_candidate_discovery(
    query_context: dict[str, Any],
    query_variant: dict[str, Any],
    candidate_urls: list[dict[str, Any]],
    *,
    attempt_ref: str | None = None,
    resolved_model_id: str = "gpt-5.5-high",
    discovered_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate_urls, list):
        raise RetrievalPacketError("native research candidate_urls must be a list")
    cap = _native_research_candidate_cap(query_context)
    compact = [_compact_native_candidate(item, query_context) for item in candidate_urls[:cap] if isinstance(item, dict)]
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "attempt_ref": attempt_ref,
        "urls": [item["canonical_url"] for item in compact],
    }
    return {
        "artifact_type": "native_research_candidate_discovery",
        "schema_version": NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION,
        "discovery_id": _sha_id("native-research-candidate-discovery", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "native_research_attempt_ref": attempt_ref,
        "model_lane_id": "native_research_candidate_discovery",
        "resolved_model_id": resolved_model_id,
        "candidate_cap": cap,
        "candidate_urls": compact,
        "candidate_url_count": len(compact),
        "candidate_url_count_omitted_by_cap": max(0, len(candidate_urls) - cap),
        "discovered_at": discovered_at,
        "fetch_required_before_admission": True,
        "authority_boundary": {
            "candidate_discovery": True,
            "source_family_final_authority": False,
            "claim_family_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
            "forecast_authority": False,
        },
        "forbidden_output_fragments": list(NATIVE_RESEARCH_FORBIDDEN_OUTPUT_FRAGMENTS),
        "feature_id": "RET-010",
    }


def build_browser_retrieval_attempt(
    query_context: dict[str, Any],
    query_variant: dict[str, Any],
    *,
    navigation_mode: str = "web_search",
    requested_url: str = "",
    final_url: str = "",
    canonical_url: str = "",
    captured_at: str | None = None,
    extraction_status: str = "rejected",
    result_rank: int = 0,
    search_candidate_url_ref: str | None = None,
) -> dict[str, Any]:
    if extraction_status not in ALLOWED_BROWSER_EXTRACTION_STATUSES:
        raise RetrievalPacketError(f"unknown browser extraction status: {extraction_status}")
    attempt_seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "navigation_mode": navigation_mode,
        "requested_url": requested_url,
        "rank": result_rank,
    }
    return {
        "artifact_type": "browser_retrieval_attempt",
        "schema_version": BROWSER_RETRIEVAL_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": _sha_id("browser-attempt", attempt_seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "query_text_sha256": query_variant.get("query_text_sha256"),
        "browser_session_ref": None,
        "browser_provider_id": OPENCLAW_BROWSER_PROVIDER_ID,
        "openclaw_transport_ref": "openclaw:web_fetch",
        "provider_capabilities": ["web_search", "direct_url", "direct_url_fetch", "url_extraction", "configured_search_provider"],
        "provider_availability_status": "unavailable",
        "web_fetch_role": "url_fetch_extraction_only",
        "search_candidate_url_ref": search_candidate_url_ref,
        "news_feed_api_enabled": False,
        "navigation_mode": navigation_mode,
        "direct_url_source_ref": None,
        "search_engine_or_navigation_source": navigation_mode,
        "result_rank": int(result_rank),
        "requested_url": requested_url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "normalized_domain": "",
        "page_title_sha256": _prefixed_sha256(""),
        "captured_at": captured_at,
        "published_at": None,
        "published_at_extraction_method": "unknown",
        "rendered_text_sha256": _prefixed_sha256(""),
        "extracted_text_sha256": _prefixed_sha256(""),
        "screenshot_artifact_ref": None,
        "content_artifact_ref": None,
        "extraction_status": extraction_status,
        "feature_gate_status": "attempt_record_schema_only_RET_001",
    }


def build_native_research_attempt(
    query_context: dict[str, Any],
    query_variant: dict[str, Any],
    *,
    resolved_model_id: str = "gpt-5.5-high",
    attempt_status: str = "failed",
    transport_availability_status: str = "unavailable",
    failure_reason_codes: list[str] | None = None,
    candidate_citation_refs: list[str] | None = None,
    candidate_claim_refs: list[str] | None = None,
    contradiction_candidate_refs: list[str] | None = None,
    negative_check_candidate_refs: list[str] | None = None,
    model_proposed_source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if attempt_status not in ALLOWED_NATIVE_ATTEMPT_STATUSES:
        raise RetrievalPacketError(f"unknown native research attempt status: {attempt_status}")
    if transport_availability_status not in ALLOWED_NATIVE_TRANSPORT_AVAILABILITY_STATUSES:
        raise RetrievalPacketError(f"unknown native transport availability: {transport_availability_status}")
    proposed_metadata = copy.deepcopy(model_proposed_source_metadata or {})
    _ensure_no_forbidden_keys(proposed_metadata, "model_proposed_source_metadata")
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "query_sha": query_variant.get("query_text_sha256"),
        "transport_availability_status": transport_availability_status,
    }
    return {
        "artifact_type": "native_research_attempt",
        "schema_version": NATIVE_RESEARCH_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": _sha_id("native-research", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "model_lane_id": "native_research_candidate_discovery",
        "resolved_model_id": resolved_model_id,
        "prompt_template_id": "native-gpt-research/v1",
        "query_manifest_sha256": _prefixed_sha256(query_context),
        "research_transport": "native_gpt_research",
        "candidate_citation_refs": list(candidate_citation_refs or []),
        "candidate_claim_refs": list(candidate_claim_refs or []),
        "contradiction_candidate_refs": list(contradiction_candidate_refs or []),
        "negative_check_candidate_refs": list(negative_check_candidate_refs or []),
        "model_proposed_source_metadata": proposed_metadata,
        "candidate_output_schema_version": NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION,
        "attempt_status": attempt_status,
        "native_transport_availability_status": transport_availability_status,
        "failure_reason_codes": list(failure_reason_codes or ["native_transport_unavailable_not_blocking"]),
        "diagnostic_only_when_unavailable": transport_availability_status != "available",
        "non_blocking_when_alternative_transport_satisfies_requirements": True,
        "metadata_authority_boundary": {
            "source_class_final_authority": False,
            "source_family_final_authority": False,
            "claim_family_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
        },
        "resolver_required_for_accepted_metadata": "deterministic_source_metadata_resolver",
        "feature_gate_status": "ret_010_native_transport_diagnostic",
    }


def build_native_research_transport_diagnostic(
    *,
    availability_status: str = "unavailable",
    checked_at: str | None = None,
    unavailable_reason: str | None = "native_research_transport_not_exposed",
    resolved_model_id: str = "gpt-5.5-high",
) -> dict[str, Any]:
    if availability_status not in ALLOWED_NATIVE_TRANSPORT_AVAILABILITY_STATUSES:
        raise RetrievalPacketError(f"unknown native transport availability: {availability_status}")
    return {
        "artifact_type": "native_research_transport_diagnostic",
        "schema_version": NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_id": _sha_id(
            "native-research-diagnostic",
            {
                "availability_status": availability_status,
                "checked_at": checked_at,
                "resolved_model_id": resolved_model_id,
            },
        ),
        "model_lane_id": "native_research_candidate_discovery",
        "resolved_model_id": resolved_model_id,
        "research_transport": "native_gpt_research",
        "availability_status": availability_status,
        "unavailable_reason": unavailable_reason if availability_status != "available" else None,
        "checked_at": checked_at,
        "candidate_discovery_role": "optional_transport",
        "non_blocking_when_alternative_transport_satisfies_requirements": True,
        "native_output_authority": {
            "candidate_discovery": True,
            "source_metadata_final_authority": False,
            "claim_family_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
        },
        "deterministic_resolver_authority": [
            "source_class",
            "source_family",
            "claim_family",
            "temporal_safety",
        ],
        "feature_id": "RET-010",
        "diagnostic_version": NATIVE_RESEARCH_RESOLVER_VERSION,
    }


def _dispatch_temporal_context(dispatch_context: dict[str, Any] | None) -> dict[str, Any]:
    context = dispatch_context or {}
    allowlist = context.get("live_retrieval_allowlist") or context.get("allowed_live_retrieval_transports")
    if not isinstance(allowlist, list) or not allowlist:
        allowlist = sorted(DEFAULT_LIVE_RETRIEVAL_TRANSPORT_ALLOWLIST)
    whitelist = context.get("pre_dispatch_input_whitelist_refs") or context.get("input_manifest_ids") or []
    if not isinstance(whitelist, list):
        whitelist = []
    return {
        "case_id": context.get("case_id"),
        "dispatch_id": context.get("dispatch_id"),
        "forecast_timestamp": context.get("forecast_timestamp"),
        "source_cutoff_timestamp": context.get("source_cutoff_timestamp") or context.get("forecast_timestamp"),
        "live_retrieval_allowlist": set(str(item) for item in allowlist if _is_non_empty_string(item)),
        "pre_dispatch_input_whitelist_refs": set(str(item) for item in whitelist if _is_non_empty_string(item)),
    }


def _candidate_ref_is_pre_dispatch_whitelisted(candidate: dict[str, Any], context: dict[str, Any]) -> bool:
    refs = context["pre_dispatch_input_whitelist_refs"]
    if not refs:
        return False
    for field in (
        "pre_dispatch_input_ref",
        "input_manifest_id",
        "manifest_ref",
        "artifact_ref",
        "source_artifact_ref",
        "content_artifact_ref",
    ):
        value = candidate.get(field)
        if _is_non_empty_string(value) and str(value) in refs:
            return True
    return False


def _source_time_allowed_by_market_contract(candidate: dict[str, Any]) -> bool:
    if candidate.get("market_contract_source_time_allowed") is True:
        return True
    if candidate.get("source_time_allowlist_status") == "allowed_by_market_contract":
        return True
    return "market_contract_cutoff_allowlist" in (candidate.get("temporal_policy_tags") or [])


def validate_temporal_eligibility(
    candidate: dict[str, Any],
    dispatch_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate RET-002 temporal safety without treating filesystem mtime as authority."""

    if not isinstance(candidate, dict):
        raise RetrievalPacketError("candidate must be an object")
    context = _dispatch_temporal_context(dispatch_context)
    forecast = context["forecast_timestamp"]
    cutoff = context["source_cutoff_timestamp"]
    hard_rejections: list[str] = []
    warnings: list[str] = []
    reason_codes: list[str] = []

    if _parse_timestamp(forecast) is None:
        hard_rejections.append("forecast_timestamp_invalid")
    if _parse_timestamp(cutoff) is None:
        hard_rejections.append("source_cutoff_timestamp_invalid")

    retrieval_transport = str(candidate.get("retrieval_transport") or candidate.get("transport") or "")
    live_capture_requested = candidate.get("retrieval_capture_for_dispatch") is True
    live_transport_allowed = retrieval_transport in context["live_retrieval_allowlist"]
    post_dispatch_fields = [
        field
        for field in ("artifact_authored_at", "artifact_generated_at", "captured_at")
        if _timestamp_at_or_after(candidate.get(field), forecast)
    ]
    same_case = (
        (not context.get("case_id") or candidate.get("case_id") == context.get("case_id"))
        and (not context.get("dispatch_id") or candidate.get("dispatch_id") == context.get("dispatch_id"))
    )
    if post_dispatch_fields and not (live_capture_requested and live_transport_allowed):
        if same_case:
            hard_rejections.append("same_case_post_dispatch_artifact")
        else:
            hard_rejections.append("post_dispatch_artifact_not_from_live_retrieval")
    elif post_dispatch_fields:
        reason_codes.append("post_dispatch_live_capture_allowed")

    source_time_fields = (
        "source_published_at",
        "source_updated_at",
        "source_observed_at",
        "source_authored_at",
        "authored_at",
        "db_row_created_at",
        "published_at",
    )
    source_times = {field: candidate.get(field) for field in source_time_fields if _parse_timestamp(candidate.get(field))}
    after_cutoff_fields = [
        field for field, value in source_times.items() if _timestamp_at_or_after(value, cutoff)
    ]
    if after_cutoff_fields:
        if _source_time_allowed_by_market_contract(candidate):
            reason_codes.append("source_after_cutoff_allowed_by_market_contract")
        else:
            hard_rejections.append("source_after_cutoff")
    if not source_times:
        reason_codes.append("source_time_unknown")

    if _timestamp_at_or_after(candidate.get("filesystem_mtime"), forecast):
        warnings.append("mtime_after_forecast_timestamp")

    whitelist_required = (
        candidate.get("requires_pre_dispatch_whitelist") is True
        or candidate.get("pre_dispatch_input_whitelist_required") is True
    )
    if whitelist_required:
        if _candidate_ref_is_pre_dispatch_whitelisted(candidate, context):
            reason_codes.append("pre_dispatch_input_whitelisted")
        else:
            hard_rejections.append("pre_dispatch_input_not_whitelisted")

    if hard_rejections:
        status = "fail"
        counts_toward_temporal_freshness = False
    elif not source_times:
        status = "unknown_not_counted"
        counts_toward_temporal_freshness = False
    else:
        status = "pass"
        counts_toward_temporal_freshness = True

    validation_id = _sha_id(
        "temporal-validation",
        {
            "candidate": candidate.get("evidence_ref") or candidate.get("candidate_id") or candidate.get("transport_attempt_ref"),
            "forecast_timestamp": forecast,
            "source_cutoff_timestamp": cutoff,
            "status": status,
            "rejections": hard_rejections,
            "reason_codes": reason_codes,
        },
    )
    return {
        "artifact_type": "retrieval_temporal_eligibility",
        "schema_version": RETRIEVAL_TEMPORAL_ELIGIBILITY_SCHEMA_VERSION,
        "temporal_validation_id": validation_id,
        "evidence_ref": candidate.get("evidence_ref"),
        "candidate_id": candidate.get("candidate_id"),
        "transport_attempt_ref": candidate.get("transport_attempt_ref"),
        "retrieval_transport": retrieval_transport,
        "forecast_timestamp": forecast,
        "source_cutoff_timestamp": cutoff,
        "temporal_gate_status": status,
        "counts_toward_temporal_freshness": counts_toward_temporal_freshness,
        "rejection_reason_codes": hard_rejections,
        "reason_codes": reason_codes,
        "warning_reason_codes": warnings,
        "live_retrieval_allowlist_status": (
            "allowed" if live_capture_requested and live_transport_allowed else
            "not_allowed" if live_capture_requested else
            "not_requested"
        ),
        "pre_dispatch_whitelist_status": (
            "whitelisted" if _candidate_ref_is_pre_dispatch_whitelisted(candidate, context) else
            "required_missing" if whitelist_required else
            "not_required"
        ),
        "source_time_fields_present": sorted(source_times),
        "post_dispatch_timestamp_fields": sorted(post_dispatch_fields),
        "filesystem_mtime_warning_only": bool(warnings),
        "validator_version": RETRIEVAL_TEMPORAL_VALIDATOR_VERSION,
    }


def build_retrieval_candidate_record(
    *,
    leaf_id: str,
    query_context_ref: str,
    query_variant_id: str,
    retrieval_transport: str,
    transport_attempt_ref: str,
    candidate_status: str,
    requested_url: str = "",
    canonical_url: str = "",
    evidence_ref: str | None = None,
    omission_reason_codes: list[str] | None = None,
    temporal_gate_status: str = "unknown_not_counted",
) -> dict[str, Any]:
    if retrieval_transport not in ALLOWED_RETRIEVAL_TRANSPORTS:
        raise RetrievalPacketError(f"unknown retrieval transport: {retrieval_transport}")
    if candidate_status not in ALLOWED_CANDIDATE_STATUSES:
        raise RetrievalPacketError(f"unknown candidate status: {candidate_status}")
    if temporal_gate_status not in ALLOWED_TEMPORAL_GATE_STATUSES:
        raise RetrievalPacketError(f"unknown temporal gate status: {temporal_gate_status}")
    seed = {
        "leaf_id": leaf_id,
        "query_context_ref": query_context_ref,
        "query_variant_id": query_variant_id,
        "transport_attempt_ref": transport_attempt_ref,
        "canonical_url": canonical_url,
        "candidate_status": candidate_status,
    }
    return {
        "artifact_type": "retrieval_candidate_record",
        "schema_version": RETRIEVAL_CANDIDATE_RECORD_SCHEMA_VERSION,
        "candidate_id": _sha_id("candidate", seed),
        "leaf_id": leaf_id,
        "query_context_ref": query_context_ref,
        "query_variant_id": query_variant_id,
        "retrieval_transport": retrieval_transport,
        "transport_attempt_ref": transport_attempt_ref,
        "requested_url": requested_url,
        "canonical_url": canonical_url,
        "source_metadata_resolution_ref": None,
        "evidence_ref": evidence_ref,
        "candidate_status": candidate_status,
        "omission_reason_codes": list(omission_reason_codes or []),
        "temporal_gate_status": temporal_gate_status,
        "feature_gate_status": {
            "RET-002": "temporal_validator_pending",
            "RET-004": "provenance_resolution_pending",
        },
    }


def _bounded_excerpt(value: Any, max_chars: int = 1200) -> str:
    if not _is_non_empty_string(value):
        return ""
    text = _normalized_space(str(value))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _compact_string_values(value: Any, *, max_items: int = 8, max_chars: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    compact: list[str] = []
    for item in value:
        if _is_non_empty_string(item):
            compact.append(_bounded_excerpt(item, max_chars=max_chars))
        elif isinstance(item, dict):
            text = item.get("text") or item.get("date_text") or item.get("url") or item.get("source_ref")
            if _is_non_empty_string(text):
                compact.append(_bounded_excerpt(text, max_chars=max_chars))
        if len(compact) >= max_items:
            break
    return compact


def _compact_metadata(value: Any, *, max_items: int = 8, max_chars: int = 160) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, str] = {}
    for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:max_items]:
        if not _is_non_empty_string(key):
            continue
        if isinstance(item, (dict, list)):
            rendered = canonical_json(item)
        else:
            rendered = str(item)
        compact[str(key)[:80]] = _bounded_excerpt(rendered, max_chars=max_chars)
    return compact


def build_compact_source_candidate_packet(
    candidate: dict[str, Any],
    *,
    max_excerpt_chars: int = 1200,
) -> dict[str, Any]:
    """Materialize the bounded RET-011 classifier input packet."""

    if not isinstance(candidate, dict):
        raise RetrievalPacketError("candidate must be an object")
    _ensure_no_forbidden_keys(candidate, "candidate")
    canonical_url = canonicalize_source_url(candidate.get("canonical_url"), candidate.get("final_url"), candidate.get("requested_url"))
    packet_seed = {
        "leaf_id": candidate.get("leaf_id"),
        "transport_attempt_ref": candidate.get("transport_attempt_ref"),
        "canonical_url": canonical_url,
        "content_sha256": _content_sha256(candidate, canonical_url),
    }
    publisher_metadata = candidate.get("publisher_metadata")
    if not isinstance(publisher_metadata, dict):
        publisher_metadata = {
            key: candidate.get(key)
            for key in ("publisher", "publisher_name", "site_name", "organization")
            if _is_non_empty_string(candidate.get(key))
        }
    return {
        "candidate_id": str(candidate.get("candidate_id") or _sha_id("candidate", packet_seed)),
        "leaf_id": str(candidate.get("leaf_id") or ""),
        "transport_attempt_ref": str(candidate.get("transport_attempt_ref") or ""),
        "canonical_url": canonical_url,
        "registrable_domain": _registrable_domain(canonical_url),
        "page_title_excerpt": _bounded_excerpt(
            candidate.get("page_title") or candidate.get("title") or candidate.get("html_title"),
            max_chars=240,
        ),
        "publisher_metadata": _compact_metadata(publisher_metadata),
        "byline_excerpt": _bounded_excerpt(candidate.get("byline") or candidate.get("author"), max_chars=240),
        "snippet_excerpt": _bounded_excerpt(
            candidate.get("snippet") or candidate.get("excerpt") or candidate.get("description"),
            max_chars=max_excerpt_chars,
        ),
        "visible_date_text_candidates": _compact_string_values(
            candidate.get("visible_date_text_candidates") or candidate.get("visible_date_candidates") or [],
            max_items=8,
            max_chars=160,
        ),
        "content_sha256": _content_sha256(candidate, canonical_url),
        "market_contract_source_hints": _compact_string_values(
            candidate.get("market_contract_source_hints") or candidate.get("official_source_hints") or [],
            max_items=8,
            max_chars=240,
        ),
        "forbidden_outputs": list(SOURCE_METADATA_CLASSIFIER_FORBIDDEN_OUTPUTS),
    }


def _model_id_from_provider_model_key(provider_model_key: str) -> str:
    if "/" in provider_model_key:
        return provider_model_key.split("/", 1)[1]
    return provider_model_key


def resolve_source_metadata_classifier_lane(
    model_lane_policy: dict[str, Any] | None = None,
    *,
    available_provider_model_keys: list[str] | None = None,
    model_policy_ref: str = SOURCE_METADATA_CLASSIFIER_MODEL_POLICY_REF,
) -> dict[str, Any]:
    lanes = (model_lane_policy or {}).get("lanes")
    lane = lanes.get(SOURCE_METADATA_CLASSIFIER_LANE_ID) if isinstance(lanes, dict) else {}
    if not isinstance(lane, dict):
        lane = {}

    allowed_keys = lane.get("allowed_provider_model_keys")
    if not isinstance(allowed_keys, list) or not allowed_keys:
        allowed_keys = list(ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS)
    allowed_keys = [str(key) for key in allowed_keys if str(key) in ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS]
    if not allowed_keys:
        allowed_keys = list(ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS)

    default_key = str(lane.get("default_provider_model_key") or DEFAULT_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEY)
    if default_key not in allowed_keys:
        default_key = allowed_keys[0]

    provider_model_key = default_key
    availability_status = "not_checked"
    unavailable_reason = None
    if available_provider_model_keys is not None:
        available = {str(key) for key in available_provider_model_keys}
        provider_model_key = next((key for key in allowed_keys if key in available), "")
        if provider_model_key:
            availability_status = "available"
        else:
            provider_model_key = default_key
            availability_status = "unavailable"
            unavailable_reason = "allowed_oauth_routed_small_model_unavailable"

    return {
        "model_lane_id": SOURCE_METADATA_CLASSIFIER_LANE_ID,
        "provider": str(lane.get("provider") or "openai"),
        "route_id": "openclaw_openai_oauth",
        "oauth_route_required": bool(lane.get("oauth_route_required", True)),
        "default_provider_model_key": default_key,
        "provider_model_key": provider_model_key,
        "resolved_model_id": _model_id_from_provider_model_key(provider_model_key),
        "allowed_provider_model_keys": allowed_keys,
        "availability_status": availability_status,
        "unavailable_reason": unavailable_reason,
        "model_policy_ref": model_policy_ref,
        "prompt_template_id": SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE_ID,
        "prompt_template_sha256": _prefixed_sha256(SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE),
        "classifier_output_schema_version": SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION,
        "forbidden_outputs": list(SOURCE_METADATA_CLASSIFIER_FORBIDDEN_OUTPUTS),
        "authority_scope": {
            "protected_primary_requires_deterministic_or_market_contract_proof": True,
            "temporal_safety_requires_deterministic_cutoff_validation": True,
            "source_family_final_requires_deterministic_evidence": True,
            "claim_family_final_requires_tuple_validation_and_hashing": True,
            "authors_research_sufficiency": False,
        },
    }


def build_source_metadata_classifier_unavailable(
    lane: dict[str, Any] | None = None,
    *,
    checked_at: str | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    lane = lane or resolve_source_metadata_classifier_lane(available_provider_model_keys=[])
    reason = unavailable_reason or lane.get("unavailable_reason") or "source_metadata_classifier_unavailable"
    return {
        "artifact_type": "source_metadata_classifier_unavailable",
        "schema_version": SOURCE_METADATA_CLASSIFIER_UNAVAILABLE_SCHEMA_VERSION,
        "diagnostic_id": _sha_id(
            "source-classifier-unavailable",
            {
                "provider_model_key": lane.get("provider_model_key"),
                "checked_at": checked_at,
                "reason": reason,
            },
        ),
        "model_lane_id": SOURCE_METADATA_CLASSIFIER_LANE_ID,
        "provider": lane.get("provider", "openai"),
        "route_id": lane.get("route_id", "openclaw_openai_oauth"),
        "oauth_route_required": bool(lane.get("oauth_route_required", True)),
        "provider_model_key": lane.get("provider_model_key", DEFAULT_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEY),
        "resolved_model_id": lane.get("resolved_model_id", DEFAULT_SOURCE_METADATA_CLASSIFIER_MODEL_ID),
        "availability_status": "unavailable",
        "checked_at": checked_at,
        "unavailable_reason": reason,
        "fallback_provider_model_keys": [
            key
            for key in lane.get("allowed_provider_model_keys", ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS)
            if key != lane.get("provider_model_key")
        ],
        "non_blocking_when_alternative_transport_satisfies_requirements": True,
        "classifier_assist_authority": {
            "source_metadata_final_authority": False,
            "protected_primary_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
        },
        "reason_codes": [reason],
        "classifier_version": SOURCE_METADATA_CLASSIFIER_VERSION,
    }


def _classifier_confidence(value: Any) -> str:
    text = str(value or "unknown")
    return text if text in ALLOWED_CLASSIFIER_CONFIDENCES else "unknown"


def _classifier_reason_codes(value: Any) -> list[str]:
    if _reason_codes_are_compact(value):
        return sorted(set(str(item) for item in value))
    return []


def _classifier_claim_candidates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        _ensure_no_forbidden_keys(item, "classifier_atomic_claim_candidate")
        proposed_tuple = item.get("proposed_tuple") if isinstance(item.get("proposed_tuple"), dict) else item
        compact.append(
            {
                "proposed_tuple": {
                    "subject": _bounded_excerpt(proposed_tuple.get("subject"), max_chars=160),
                    "predicate": _bounded_excerpt(proposed_tuple.get("predicate"), max_chars=120),
                    "object_or_value": _bounded_excerpt(proposed_tuple.get("object_or_value"), max_chars=240),
                    "event_time": _bounded_excerpt(proposed_tuple.get("event_time"), max_chars=120),
                    "entity_or_jurisdiction": _bounded_excerpt(
                        proposed_tuple.get("entity_or_jurisdiction"),
                        max_chars=160,
                    ),
                    "condition_scope": proposed_tuple.get("condition_scope", "unconditional"),
                    "polarity": proposed_tuple.get("polarity", "uncertain"),
                },
                "candidate_confidence": _classifier_confidence(item.get("candidate_confidence") or item.get("confidence")),
                "supporting_span_refs": _compact_string_values(item.get("supporting_span_refs") or [], max_items=8),
            }
        )
    return compact


def _classifier_visible_date_candidates(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, str]] = []
    for item in value[:8]:
        if isinstance(item, dict):
            text = item.get("date_text") or item.get("text") or item.get("visible_text") or item.get("timestamp")
            normalized = item.get("normalized_timestamp") or item.get("timestamp") or item.get("iso_timestamp")
        else:
            text = item
            normalized = None
        if not _is_non_empty_string(text) and not _is_non_empty_string(normalized):
            continue
        compact.append(
            {
                "date_text": _bounded_excerpt(text or normalized, max_chars=160),
                "normalized_timestamp": _iso_or_none(normalized) or "",
            }
        )
    return compact


def build_source_metadata_classifier_slice(
    candidate_packet: dict[str, Any],
    classifier_output: dict[str, Any] | None = None,
    *,
    lane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate_packet, dict):
        raise RetrievalPacketError("candidate packet must be an object")
    output = copy.deepcopy(classifier_output or {})
    if not isinstance(output, dict):
        raise RetrievalPacketError("classifier output must be an object")
    _ensure_no_forbidden_keys(output, "classifier_output")
    lane = lane or resolve_source_metadata_classifier_lane()
    proposed_source_class = str(output.get("proposed_source_class") or output.get("source_class") or "unknown")
    if proposed_source_class not in ALLOWED_SOURCE_CLASSES:
        proposed_source_class = "unknown"
    syndication_hint = str(output.get("syndication_hint") or "unknown")
    if syndication_hint not in ALLOWED_SYNDICATION_HINTS:
        syndication_hint = "unknown"
    reason_codes = _classifier_reason_codes(output.get("reason_codes"))
    input_sha = _prefixed_sha256(candidate_packet)
    seed = {
        "candidate_id": candidate_packet.get("candidate_id"),
        "input_sha": input_sha,
        "provider_model_key": lane.get("provider_model_key"),
        "output": output,
    }
    return {
        "artifact_type": "source_metadata_classifier_slice",
        "schema_version": SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION,
        "classifier_slice_id": _sha_id("source-classifier", seed),
        "candidate_id": candidate_packet.get("candidate_id"),
        "leaf_id": candidate_packet.get("leaf_id"),
        "model_lane_id": SOURCE_METADATA_CLASSIFIER_LANE_ID,
        "resolved_model_id": lane.get("resolved_model_id", DEFAULT_SOURCE_METADATA_CLASSIFIER_MODEL_ID),
        "provider_model_key": lane.get("provider_model_key", DEFAULT_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEY),
        "model_policy_ref": lane.get("model_policy_ref", SOURCE_METADATA_CLASSIFIER_MODEL_POLICY_REF),
        "prompt_template_id": SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE_ID,
        "prompt_template_sha256": lane.get("prompt_template_sha256") or _prefixed_sha256(SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE),
        "input_candidate_sha256": input_sha,
        "classifier_output_schema_version": SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION,
        "proposed_source_class": proposed_source_class,
        "source_class_confidence": _classifier_confidence(output.get("source_class_confidence") or output.get("confidence")),
        "proposed_source_family_hint": _bounded_excerpt(output.get("proposed_source_family_hint") or "unknown", max_chars=160),
        "source_family_confidence": _classifier_confidence(output.get("source_family_confidence")),
        "syndication_hint": syndication_hint,
        "atomic_claim_candidates": _classifier_claim_candidates(output.get("atomic_claim_candidates")),
        "visible_date_candidates": _classifier_visible_date_candidates(output.get("visible_date_candidates")),
        "reason_codes": reason_codes,
        "forbidden_outputs": list(SOURCE_METADATA_CLASSIFIER_FORBIDDEN_OUTPUTS),
        "authority_boundary": {
            "source_class_final_authority": False,
            "source_family_final_authority": False,
            "claim_family_final_authority": False,
            "protected_primary_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
        },
        "classifier_version": SOURCE_METADATA_CLASSIFIER_VERSION,
    }


def build_atomic_claim_candidates_from_classifier_slice(
    *,
    evidence_ref: str,
    leaf_id: str,
    chunk_refs: list[str],
    classifier_slice: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(classifier_slice, dict):
        return []
    candidates = []
    for proposed in classifier_slice.get("atomic_claim_candidates", []):
        if not isinstance(proposed, dict):
            continue
        span_refs = [
            str(ref)
            for ref in proposed.get("supporting_span_refs", [])
            if _is_non_empty_string(ref)
        ]
        tuple_value = proposed.get("proposed_tuple") if isinstance(proposed.get("proposed_tuple"), dict) else {}
        if not span_refs:
            status = "rejected_no_span"
        elif not all(_is_non_empty_string(tuple_value.get(field)) for field in ("subject", "predicate", "object_or_value")):
            status = "rejected_not_market_relevant"
        else:
            status = "accepted_for_normalization"
        candidates.append(
            build_atomic_claim_candidate(
                evidence_ref=evidence_ref,
                leaf_id=leaf_id,
                chunk_refs=chunk_refs,
                extraction_method="model_assisted_bounded_passage",
                proposed_tuple=tuple_value,
                supporting_span_refs=span_refs,
                candidate_confidence=str(proposed.get("candidate_confidence") or "unknown"),
                validation_status=status,
            )
        )
    return candidates


def _matches_any_url(candidate_url: str, urls: list[Any]) -> bool:
    if not candidate_url:
        return False
    canonical = canonicalize_source_url(candidate_url)
    return any(canonical and canonical == canonicalize_source_url(url) for url in urls if _is_non_empty_string(url))


def _deterministic_source_class_proof(
    candidate: dict[str, Any],
    source_class: str,
    *,
    market_rules: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    method = str(candidate.get("source_class_resolution_method") or "")
    if candidate.get("deterministic_source_class_proof") is True or method in DETERMINISTIC_SOURCE_CLASS_METHODS:
        return True, method or "deterministic_candidate_field"
    if candidate.get("retrieval_transport") == "manual_fixture":
        return True, "manual_fixture"
    canonical_url = canonicalize_source_url(candidate.get("canonical_url"), candidate.get("final_url"), candidate.get("requested_url"))
    rules = market_rules or {}
    official_hints = list(candidate.get("official_source_hints") or [])
    if isinstance(rules.get("official_source_hints"), list):
        official_hints.extend(rules["official_source_hints"])
    if source_class == "market_rules_or_resolution_source" and _matches_any_url(
        canonical_url,
        [rules.get("resolution_url"), candidate.get("market_resolution_url")],
    ):
        return True, "market_rules_resolution_url"
    if source_class == "official_or_primary" and _matches_any_url(canonical_url, official_hints):
        return True, "official_url_hint"
    return False, "no_deterministic_proof"


def _deterministic_source_class_or_unknown(
    candidate: dict[str, Any],
    *,
    market_rules: dict[str, Any] | None = None,
) -> tuple[str, str, bool]:
    source_class = str(candidate.get("source_class") or "unknown")
    if source_class not in ALLOWED_SOURCE_CLASSES or source_class == "unknown":
        return "unknown", "unknown", False
    has_proof, proof_method = _deterministic_source_class_proof(
        candidate,
        source_class,
        market_rules=market_rules,
    )
    if not has_proof:
        return "unknown", "unknown", False
    return source_class, proof_method, True


def _classifier_slice_ref(classifier_slice: dict[str, Any] | None) -> str | None:
    if not classifier_slice:
        return None
    for field in ("classifier_slice_id", "classifier_slice_ref", "slice_id"):
        if _is_non_empty_string(classifier_slice.get(field)):
            return str(classifier_slice[field])
    return _sha_id("source-classifier", classifier_slice)


def _resolve_classifier_source_class(
    candidate: dict[str, Any],
    classifier_slice: dict[str, Any] | None,
    *,
    market_rules: dict[str, Any] | None = None,
) -> tuple[str, str, list[str]]:
    if not classifier_slice:
        return "not_used", "unknown", []
    proposed = str(
        classifier_slice.get("proposed_source_class")
        or classifier_slice.get("source_class")
        or candidate.get("model_proposed_source_class")
        or "unknown"
    )
    if proposed not in ALLOWED_SOURCE_CLASSES:
        return "unsupported_source_class", "unknown", ["unsupported_classifier_source_class"]
    if proposed == "unknown":
        return "not_used", "unknown", ["classifier_source_class_unknown_not_counted"]
    explicit = str(candidate.get("source_class") or "unknown")
    if explicit in ALLOWED_SOURCE_CLASSES and explicit != "unknown" and explicit != proposed:
        explicit_has_proof, explicit_proof = _deterministic_source_class_proof(
            candidate,
            explicit,
            market_rules=market_rules,
        )
        if explicit not in PROTECTED_SOURCE_CLASSES or explicit_has_proof:
            return "contradicted", "unknown", [
                "classifier_contradicted_by_deterministic_source_class",
                explicit_proof if explicit_has_proof else "candidate_field",
            ]
    protected_primary = bool(classifier_slice.get("protected_primary_proposed")) or proposed in PROTECTED_SOURCE_CLASSES
    has_proof, proof_method = _deterministic_source_class_proof(candidate, proposed, market_rules=market_rules)
    if protected_primary and not has_proof:
        return "classifier_unsupported", "unknown", ["classifier_unsupported_for_protected_primary"]
    confidence = _classifier_confidence(classifier_slice.get("source_class_confidence") or classifier_slice.get("confidence"))
    validator_accepted = (
        classifier_slice.get("deterministic_acceptance_status") == "accepted"
        or classifier_slice.get("validator_acceptance_status") == "accepted"
    )
    if confidence != "high" and not validator_accepted:
        return "rejected", "unknown", ["classifier_source_class_confidence_not_high"]
    if proposed not in PROTECTED_SOURCE_CLASSES or has_proof:
        reason_codes = list(classifier_slice.get("acceptance_reason_codes") or [])
        if proof_method != "no_deterministic_proof":
            reason_codes.append(proof_method)
        reason_codes.append(
            "validator_accepted_classifier_source_class"
            if validator_accepted
            else "high_confidence_classifier_source_class"
        )
        if proposed not in PROTECTED_SOURCE_CLASSES:
            reason_codes.append("ordinary_source_class_not_protected")
        return "accepted_source_class", proposed, sorted(set(reason_codes))
    return "rejected", "unknown", ["classifier_not_accepted_by_validator"]


def _resolve_source_class(
    candidate: dict[str, Any],
    classifier_slice: dict[str, Any] | None,
    *,
    market_rules: dict[str, Any] | None = None,
) -> tuple[str, str, str, list[str]]:
    explicit = str(candidate.get("source_class") or "unknown")
    if explicit in ALLOWED_SOURCE_CLASSES and explicit != "unknown":
        has_proof, proof_method = _deterministic_source_class_proof(candidate, explicit, market_rules=market_rules)
        if explicit not in PROTECTED_SOURCE_CLASSES or has_proof:
            if classifier_slice:
                proposed = str(classifier_slice.get("proposed_source_class") or classifier_slice.get("source_class") or "unknown")
                if proposed in ALLOWED_SOURCE_CLASSES and proposed not in {"unknown", explicit}:
                    return explicit, proof_method if has_proof else "candidate_field", "contradicted", [
                        "classifier_contradicted_by_deterministic_source_class",
                        proof_method if has_proof else "candidate_field",
                    ]
            return explicit, proof_method if has_proof else "candidate_field", "not_used", []
    proposed_native = candidate.get("model_proposed_source_class")
    if _is_non_empty_string(proposed_native) and str(proposed_native) not in ALLOWED_SOURCE_CLASSES:
        return "unknown", "unknown", "unsupported_source_class", ["unsupported_model_proposed_source_class"]
    if _is_non_empty_string(proposed_native):
        return "unknown", "unknown", "not_used", ["native_research_proposed_metadata_not_final_authority"]
    classifier_status, classifier_class, classifier_reasons = _resolve_classifier_source_class(
        candidate,
        classifier_slice,
        market_rules=market_rules,
    )
    if classifier_status == "accepted_source_class" and classifier_class != "unknown":
        return classifier_class, "classifier_assist_validated", classifier_status, classifier_reasons
    return "unknown", "unknown", classifier_status, classifier_reasons or ["source_class_unknown"]


def _resolve_source_family(
    candidate: dict[str, Any],
    *,
    canonical_url: str,
    content_sha256: str,
) -> tuple[str, str, str]:
    explicit = candidate.get("source_family_id")
    if _is_non_empty_string(explicit) and explicit != "source-family-unknown":
        return str(explicit), str(candidate.get("source_family_resolution_method") or "candidate_field"), "resolved"
    if _is_non_empty_string(candidate.get("syndication_key")):
        return "source-family-" + _hash_suffix({"syndication": candidate["syndication_key"]}), "syndication_key", "syndicated_copy"
    if _is_non_empty_string(candidate.get("mirrored_api_family_key")):
        return "source-family-" + _hash_suffix({"api_mirror": candidate["mirrored_api_family_key"]}), "mirrored_api_family_key", "mirrored_api_endpoint"
    explicit_content_hash = _is_non_empty_string(candidate.get("content_sha256")) or any(
        _is_non_empty_string(candidate.get(field)) for field in ("content", "extracted_text", "rendered_text", "snippet")
    )
    if explicit_content_hash and content_sha256:
        return "source-family-" + _hash_suffix({"content": content_sha256}), "content_sha256", "content_hash_dedupe"
    if canonical_url:
        return "source-family-" + _hash_suffix({"canonical_url": canonical_url}), "canonical_url", "resolved"
    domain = _registrable_domain(canonical_url)
    if domain:
        return "source-family-" + _hash_suffix({"domain": domain}), "registrable_domain", "resolved"
    return "source-family-unknown", "unknown", "unknown_not_counted"


def _resolve_independence_status(
    *,
    source_family_id: str,
    claim_family_ids: list[str],
    source_family_status: str,
    seen_source_family_ids: set[str] | None = None,
    seen_claim_family_ids: set[str] | None = None,
) -> str:
    if source_family_id == "source-family-unknown" or not claim_family_ids:
        return "unknown_not_counted"
    if seen_claim_family_ids and any(claim_id in seen_claim_family_ids for claim_id in claim_family_ids):
        return "same_claim_family"
    if seen_source_family_ids and source_family_id in seen_source_family_ids:
        return "same_source_family"
    return "independent"


def _accepted_classifier_visible_date(
    classifier_slice: dict[str, Any] | None,
    *,
    source_cutoff_timestamp: str | None,
) -> tuple[str | None, list[str]]:
    if not classifier_slice:
        return None, []
    for candidate in classifier_slice.get("visible_date_candidates", []):
        if not isinstance(candidate, dict):
            continue
        raw = candidate.get("normalized_timestamp") or candidate.get("date_text")
        parsed = _iso_or_none(raw)
        if not parsed:
            continue
        if source_cutoff_timestamp and _timestamp_at_or_after(parsed, source_cutoff_timestamp):
            return None, ["classifier_visible_date_after_cutoff_not_accepted"]
        return parsed, ["classifier_visible_date_deterministically_parsed"]
    return None, []


def _classifier_source_family_hint_status(
    classifier_slice: dict[str, Any] | None,
    *,
    canonical_url: str,
    source_family_id: str,
    source_family_status: str,
) -> tuple[str | None, list[str]]:
    if not classifier_slice:
        return None, []
    hint = str(classifier_slice.get("proposed_source_family_hint") or "")
    confidence = _classifier_confidence(classifier_slice.get("source_family_confidence"))
    if not hint or hint == "unknown" or confidence != "high":
        return None, []
    if source_family_id == "source-family-unknown":
        return None, ["classifier_source_family_hint_without_deterministic_support"]
    normalized_hint = hint.lower()
    domain = _registrable_domain(canonical_url)
    syndication_hint = str(classifier_slice.get("syndication_hint") or "unknown")
    if domain and (domain in normalized_hint or normalized_hint in domain):
        return "accepted_source_family_hint", ["classifier_source_family_hint_supported_by_domain"]
    if source_family_status == "syndicated_copy" and syndication_hint not in {"none", "unknown"}:
        return "accepted_source_family_hint", ["classifier_syndication_hint_supported_by_syndication_key"]
    return None, ["classifier_source_family_hint_not_used_for_final_family"]


def _merge_classifier_acceptance(
    source_class_status: str,
    source_class_reasons: list[str],
    *,
    family_hint_status: str | None = None,
    family_hint_reasons: list[str] | None = None,
    visible_date_accepted: bool = False,
    visible_date_reasons: list[str] | None = None,
) -> tuple[str, list[str]]:
    reasons = list(source_class_reasons or [])
    reasons.extend(family_hint_reasons or [])
    reasons.extend(visible_date_reasons or [])
    if source_class_status in {"classifier_unsupported", "unsupported_source_class", "contradicted"}:
        return source_class_status, sorted(set(reasons))
    if source_class_status == "accepted_source_class":
        return source_class_status, sorted(set(reasons))
    if family_hint_status:
        return family_hint_status, sorted(set(reasons))
    if visible_date_accepted:
        return "accepted_visible_date_candidate", sorted(set(reasons))
    return source_class_status, sorted(set(reasons))


def build_source_metadata_resolution(
    *,
    evidence_ref: str,
    transport_attempt_ref: str,
    requested_url: str = "",
    final_url: str = "",
    canonical_url: str = "",
    source_class: str = "unknown",
    canonical_source_id: str = "source-unknown",
    source_family_id: str = "source-family-unknown",
    source_family_resolution_method: str = "unknown",
    source_family_status: str = "unknown_not_counted",
    claim_family_resolution_refs: list[str] | None = None,
    claim_family_ids: list[str] | None = None,
    temporal_safety_status: str = "unknown_not_counted",
    published_at: str | None = None,
    published_at_method: str = "unknown",
    classifier_slice_ref: str | None = None,
    classifier_acceptance_status: str = "not_used",
    classifier_acceptance_reason_codes: list[str] | None = None,
    source_class_resolution_method: str = "unknown",
    metadata_confidence: str = "unknown",
    counts_toward_breadth: bool = False,
    unknown_reason_codes: list[str] | None = None,
    content_sha256: str | None = None,
) -> dict[str, Any]:
    if source_class not in ALLOWED_SOURCE_CLASSES:
        raise RetrievalPacketError(f"unknown source class: {source_class}")
    if temporal_safety_status not in ALLOWED_TEMPORAL_GATE_STATUSES:
        raise RetrievalPacketError(f"unknown temporal safety status: {temporal_safety_status}")
    if classifier_acceptance_status not in ALLOWED_CLASSIFIER_ACCEPTANCE_STATUSES:
        raise RetrievalPacketError(f"unknown classifier acceptance status: {classifier_acceptance_status}")
    if source_family_status not in ALLOWED_SOURCE_FAMILY_STATUSES:
        raise RetrievalPacketError(f"unknown source family status: {source_family_status}")
    resolution_id = _sha_id(
        "source-metadata",
        {
            "evidence_ref": evidence_ref,
            "transport_attempt_ref": transport_attempt_ref,
            "canonical_url": canonical_url,
            "source_class": source_class,
            "source_family_id": source_family_id,
        },
    )
    return {
        "artifact_type": "source_metadata_resolution",
        "schema_version": SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION,
        "resolution_id": resolution_id,
        "evidence_ref": evidence_ref,
        "transport_attempt_ref": transport_attempt_ref,
        "requested_url": requested_url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "registrable_domain": _registrable_domain(canonical_url),
        "canonical_source_id": canonical_source_id,
        "content_sha256": content_sha256,
        "source_class": source_class,
        "source_class_resolution_method": source_class_resolution_method,
        "source_family_id": source_family_id,
        "source_family_resolution_method": source_family_resolution_method,
        "source_family_status": source_family_status,
        "claim_family_resolution_refs": list(claim_family_resolution_refs or []),
        "claim_family_ids": list(claim_family_ids or []),
        "claim_family_resolution_method": "unknown",
        "temporal_safety_status": temporal_safety_status,
        "published_at": published_at,
        "published_at_method": published_at_method,
        "classifier_slice_ref": classifier_slice_ref,
        "classifier_acceptance_status": classifier_acceptance_status,
        "classifier_acceptance_reason_codes": list(classifier_acceptance_reason_codes or []),
        "metadata_confidence": metadata_confidence,
        "counts_toward_breadth": bool(counts_toward_breadth),
        "unknown_reason_codes": list(unknown_reason_codes or []),
        "accepted_metadata_authority": "deterministic_source_metadata_resolver",
        "deterministic_resolver_accepted_fields": [
            field
            for field, accepted in (
                ("source_class", source_class != "unknown"),
                ("source_family", source_family_id != "source-family-unknown"),
                ("claim_family", bool(claim_family_ids)),
                ("temporal_safety", temporal_safety_status == "pass"),
            )
            if accepted
        ],
        "model_proposed_metadata_counted": False,
        "authority_boundary": {
            "native_research_final_authority": False,
            "classifier_source_family_final_authority": False,
            "classifier_claim_family_final_authority": False,
            "classifier_protected_primary_final_authority": False,
            "classifier_temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
        },
        "feature_gate_status": "ret_004_deterministic_resolution",
        "normalizer_version": RETRIEVAL_PROVENANCE_NORMALIZER_VERSION,
        "ret_010_resolver_version": NATIVE_RESEARCH_RESOLVER_VERSION,
    }


def build_source_metadata_resolution_placeholder(
    *,
    evidence_ref: str,
    transport_attempt_ref: str,
    canonical_url: str = "",
    source_class: str = "unknown",
) -> dict[str, Any]:
    return build_source_metadata_resolution(
        evidence_ref=evidence_ref,
        transport_attempt_ref=transport_attempt_ref,
        canonical_url=canonical_url,
        source_class=source_class,
        unknown_reason_codes=["ret_004_resolver_pending"],
        source_family_status="unknown_not_counted",
    )


def build_retrieval_evidence_item(
    *,
    case_id: str,
    dispatch_id: str,
    leaf_id: str,
    parent_branch_id: str,
    retrieval_transport: str,
    transport_attempt_ref: str,
    requested_url: str = "",
    final_url: str = "",
    canonical_url: str = "",
    canonical_source_id: str = "source-unknown",
    source_metadata_resolution_ref: str | None = None,
    claim_family_resolution_refs: list[str] | None = None,
    source_family_id: str = "source-family-unknown",
    source_class: str = "unknown",
    independence_status: str = "unknown_not_counted",
    temporal_gate_status: str = "unknown_not_counted",
    source_published_at: str | None = None,
    source_updated_at: str | None = None,
    source_observed_at: str | None = None,
    source_authored_at: str | None = None,
    db_row_created_at: str | None = None,
    captured_at: str | None = None,
    artifact_generated_at: str | None = None,
    artifact_authored_at: str | None = None,
    filesystem_mtime: str | None = None,
    retrieval_capture_for_dispatch: bool = False,
    pre_dispatch_input_ref: str | None = None,
    content_sha256: str | None = None,
    chunk_refs: list[str] | None = None,
    retrieval_score: float = 0.0,
    admission_status: str = "admitted",
    admission_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    if retrieval_transport not in ALLOWED_RETRIEVAL_TRANSPORTS:
        raise RetrievalPacketError(f"unknown retrieval transport: {retrieval_transport}")
    if source_class not in ALLOWED_SOURCE_CLASSES:
        raise RetrievalPacketError(f"unknown source class: {source_class}")
    if independence_status not in ALLOWED_INDEPENDENCE_STATUSES:
        raise RetrievalPacketError(f"unknown independence status: {independence_status}")
    if temporal_gate_status not in ALLOWED_TEMPORAL_GATE_STATUSES:
        raise RetrievalPacketError(f"unknown temporal gate status: {temporal_gate_status}")
    if admission_status not in ALLOWED_ADMISSION_STATUSES:
        raise RetrievalPacketError(f"unknown admission status: {admission_status}")
    seed = {
        "case_id": case_id,
        "dispatch_id": dispatch_id,
        "leaf_id": leaf_id,
        "transport_attempt_ref": transport_attempt_ref,
        "canonical_url": canonical_url,
        "content_sha256": content_sha256,
    }
    evidence_ref = _sha_id("retrieval-evidence", seed)
    item = {
        "artifact_type": "retrieval_evidence",
        "schema_version": RETRIEVAL_EVIDENCE_SCHEMA_VERSION,
        "evidence_ref": evidence_ref,
        "case_id": case_id,
        "dispatch_id": dispatch_id,
        "leaf_id": leaf_id,
        "parent_branch_id": parent_branch_id,
        "retrieval_transport": retrieval_transport,
        "transport_attempt_ref": transport_attempt_ref,
        "requested_url": requested_url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "canonical_source_id": canonical_source_id,
        "source_metadata_resolution_ref": source_metadata_resolution_ref or _sha_id(
            "source-metadata",
            {"evidence_ref": evidence_ref, "transport_attempt_ref": transport_attempt_ref},
        ),
        "claim_family_resolution_refs": list(claim_family_resolution_refs or []),
        "source_family_id": source_family_id,
        "source_class": source_class,
        "independence_status": independence_status,
        "temporal_gate_status": temporal_gate_status,
        "source_published_at": source_published_at,
        "source_updated_at": source_updated_at,
        "source_observed_at": source_observed_at,
        "source_authored_at": source_authored_at,
        "db_row_created_at": db_row_created_at,
        "captured_at": captured_at,
        "artifact_generated_at": artifact_generated_at,
        "artifact_authored_at": artifact_authored_at,
        "filesystem_mtime": filesystem_mtime,
        "retrieval_capture_for_dispatch": bool(retrieval_capture_for_dispatch),
        "pre_dispatch_input_ref": pre_dispatch_input_ref,
        "content_sha256": content_sha256 or _prefixed_sha256(
            {"canonical_url": canonical_url, "transport_attempt_ref": transport_attempt_ref}
        ),
        "chunk_refs": list(chunk_refs or []),
        "retrieval_score": float(retrieval_score),
        "admission_status": admission_status,
        "admission_reason_codes": list(admission_reason_codes or []),
    }
    _ensure_no_forbidden_keys(item, "retrieval_evidence")
    return item


def build_evidence_chunk(
    *,
    evidence_ref: str,
    content_artifact_ref: str,
    chunk_index: int,
    char_start: int = 0,
    char_end: int = 0,
    text: str = "",
    excerpt_policy: str = "hash_only",
    contains_claim_candidate_ids: list[str] | None = None,
) -> dict[str, Any]:
    if chunk_index < 0 or char_start < 0 or char_end < char_start:
        raise RetrievalPacketError("chunk indexes and offsets must be non-negative")
    return {
        "artifact_type": "retrieval_evidence_chunk",
        "schema_version": RETRIEVAL_EVIDENCE_CHUNK_SCHEMA_VERSION,
        "chunk_ref": _sha_id(
            "retrieval-chunk",
            {"evidence_ref": evidence_ref, "chunk_index": chunk_index, "char_start": char_start, "char_end": char_end},
        ),
        "evidence_ref": evidence_ref,
        "content_artifact_ref": content_artifact_ref,
        "chunk_index": int(chunk_index),
        "char_start": int(char_start),
        "char_end": int(char_end),
        "text_sha256": _prefixed_sha256(text),
        "excerpt_char_count": len(text),
        "excerpt_policy": excerpt_policy,
        "contains_claim_candidate_ids": list(contains_claim_candidate_ids or []),
    }


def build_evidence_span(
    *,
    chunk_ref: str,
    char_start: int,
    char_end: int,
    text: str = "",
    span_role: str = "claim_support",
) -> dict[str, Any]:
    if char_start < 0 or char_end < char_start:
        raise RetrievalPacketError("span offsets must be non-negative")
    return {
        "artifact_type": "retrieval_evidence_span",
        "schema_version": RETRIEVAL_EVIDENCE_SPAN_SCHEMA_VERSION,
        "span_ref": _sha_id("retrieval-span", {"chunk_ref": chunk_ref, "char_start": char_start, "char_end": char_end}),
        "chunk_ref": chunk_ref,
        "char_start": int(char_start),
        "char_end": int(char_end),
        "text_sha256": _prefixed_sha256(text),
        "span_role": span_role,
        "feature_gate_status": "span_binding_validation_pending_RET_004",
    }


def _normalize_tuple_value(value: Any) -> str:
    return _normalized_space(str(value or "")).lower()


def normalize_claim_tuple(proposed_tuple: dict[str, Any]) -> dict[str, Any]:
    condition_scope = proposed_tuple.get("condition_scope", "unconditional")
    if condition_scope not in ALLOWED_CONDITION_SCOPES:
        condition_scope = "unconditional"
    polarity = proposed_tuple.get("polarity", "uncertain")
    if polarity not in {"affirmed", "negated", "uncertain"}:
        polarity = "uncertain"
    return {
        "subject_id": _normalize_tuple_value(proposed_tuple.get("subject")),
        "predicate_id": _normalize_tuple_value(proposed_tuple.get("predicate")),
        "object_or_value_normalized": _normalize_tuple_value(proposed_tuple.get("object_or_value")),
        "event_time_normalized": _normalize_tuple_value(proposed_tuple.get("event_time")),
        "entity_or_jurisdiction_id": _normalize_tuple_value(proposed_tuple.get("entity_or_jurisdiction")),
        "condition_scope": condition_scope,
        "polarity": polarity,
    }


def build_atomic_claim_candidate(
    *,
    evidence_ref: str,
    leaf_id: str,
    chunk_refs: list[str],
    extraction_method: str = "manual_fixture",
    proposed_tuple: dict[str, Any] | None = None,
    supporting_span_refs: list[str] | None = None,
    candidate_confidence: str = "unknown",
    validation_status: str = "unknown_not_counted",
) -> dict[str, Any]:
    if validation_status not in ALLOWED_CLAIM_VALIDATION_STATUSES:
        raise RetrievalPacketError(f"unknown claim validation status: {validation_status}")
    proposed = proposed_tuple or {
        "subject": "",
        "predicate": "",
        "object_or_value": "",
        "event_time": "",
        "entity_or_jurisdiction": "",
        "condition_scope": "unconditional",
        "polarity": "uncertain",
    }
    _ensure_no_forbidden_keys(proposed, "proposed_tuple")
    return {
        "artifact_type": "atomic_claim_candidate",
        "schema_version": ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION,
        "claim_candidate_id": _sha_id(
            "claim-candidate",
            {"evidence_ref": evidence_ref, "leaf_id": leaf_id, "tuple": proposed, "chunks": chunk_refs},
        ),
        "evidence_ref": evidence_ref,
        "leaf_id": leaf_id,
        "chunk_refs": list(chunk_refs),
        "extraction_method": extraction_method,
        "model_lane_id": "source_metadata_classifier_assist" if extraction_method == "model_assisted_bounded_passage" else None,
        "prompt_template_id": "source-metadata-classifier/v1" if extraction_method == "model_assisted_bounded_passage" else None,
        "proposed_tuple": proposed,
        "supporting_span_refs": list(supporting_span_refs or []),
        "candidate_confidence": candidate_confidence,
        "validation_status": validation_status,
        "validator_reason_codes": [],
    }


def build_claim_family_resolution(
    claim_candidates: list[dict[str, Any]],
    *,
    resolution_method: str = "manual_fixture",
) -> dict[str, Any]:
    accepted = [
        candidate
        for candidate in claim_candidates
        if candidate.get("validation_status") == "accepted_for_normalization"
    ]
    if accepted:
        normalized = normalize_claim_tuple(accepted[0].get("proposed_tuple", {}))
        normalized_sha = _prefixed_sha256(normalized)
        claim_family_id = "claim-family-" + normalized_sha.removeprefix("sha256:")[:24]
        contradiction_family_id = _claim_contradiction_family_id(normalized)
        equivalence_status = "new_family"
        counts = True
    else:
        normalized = {
            "subject_id": "",
            "predicate_id": "",
            "object_or_value_normalized": "",
            "event_time_normalized": "",
            "entity_or_jurisdiction_id": "",
            "condition_scope": "unconditional",
            "polarity": "uncertain",
        }
        normalized_sha = _prefixed_sha256(normalized)
        claim_family_id = "claim-family-unknown"
        contradiction_family_id = None
        equivalence_status = "unknown_not_counted"
        counts = False
    return {
        "artifact_type": "claim_family_resolution",
        "schema_version": CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION,
        "claim_family_resolution_id": _sha_id(
            "claim-family-resolution",
            {"candidates": [c.get("claim_candidate_id") for c in claim_candidates], "tuple": normalized},
        ),
        "claim_family_id": claim_family_id,
        "claim_candidate_refs": [c.get("claim_candidate_id") for c in claim_candidates],
        "normalized_tuple": normalized,
        "normalized_tuple_sha256": normalized_sha,
        "resolution_method": resolution_method,
        "equivalence_status": equivalence_status,
        "contradiction_family_id": contradiction_family_id,
        "counts_toward_claim_family_breadth": counts,
        "reason_codes": [] if counts else ["no_accepted_atomic_claim_candidate"],
    }


def resolve_claim_families(
    claim_candidates: list[dict[str, Any]],
    *,
    resolution_method: str = "candidate_validated_then_deterministic_tuple_hash",
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    unknown: list[dict[str, Any]] = []
    for candidate in claim_candidates:
        if candidate.get("validation_status") != "accepted_for_normalization":
            unknown.append(candidate)
            continue
        normalized = normalize_claim_tuple(candidate.get("proposed_tuple", {}))
        groups.setdefault(_prefixed_sha256(normalized), []).append(candidate)
    resolutions = [
        build_claim_family_resolution(candidates, resolution_method=resolution_method)
        for _, candidates in sorted(groups.items())
    ]
    if unknown:
        resolutions.append(build_claim_family_resolution(unknown, resolution_method=resolution_method))
    return resolutions


def normalize_retrieval_provenance(
    candidate: dict[str, Any],
    *,
    dispatch_context: dict[str, Any] | None = None,
    classifier_slice: dict[str, Any] | None = None,
    claim_candidates: list[dict[str, Any]] | None = None,
    claim_family_resolutions: list[dict[str, Any]] | None = None,
    market_rules: dict[str, Any] | None = None,
    seen_source_family_ids: set[str] | None = None,
    seen_claim_family_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise RetrievalPacketError("candidate must be an object")
    retrieval_transport = str(candidate.get("retrieval_transport") or candidate.get("transport") or "")
    if retrieval_transport not in ALLOWED_RETRIEVAL_TRANSPORTS:
        raise RetrievalPacketError(f"unknown retrieval transport: {retrieval_transport}")

    requested_url = str(candidate.get("requested_url") or "")
    final_url = str(candidate.get("final_url") or "")
    canonical_url = canonicalize_source_url(candidate.get("canonical_url"), final_url, requested_url)
    content_hash = _content_sha256(candidate, canonical_url)
    source_class, source_class_method, classifier_status, classifier_reason_codes = _resolve_source_class(
        {**candidate, "canonical_url": canonical_url},
        classifier_slice,
        market_rules=market_rules,
    )
    source_family_id, source_family_method, source_family_status = _resolve_source_family(
        candidate,
        canonical_url=canonical_url,
        content_sha256=content_hash,
    )
    family_hint_status, family_hint_reasons = _classifier_source_family_hint_status(
        classifier_slice,
        canonical_url=canonical_url,
        source_family_id=source_family_id,
        source_family_status=source_family_status,
    )
    canonical_source_id = "source-" + _hash_suffix(
        {
            "source_family_id": source_family_id,
            "canonical_url": canonical_url,
            "registrable_domain": _registrable_domain(canonical_url),
        }
    )
    cutoff = (dispatch_context or {}).get("source_cutoff_timestamp")
    classifier_visible_published_at, visible_date_reason_codes = _accepted_classifier_visible_date(
        classifier_slice,
        source_cutoff_timestamp=str(cutoff) if cutoff else None,
    )
    candidate_for_temporal = {**candidate, "retrieval_transport": retrieval_transport, "canonical_url": canonical_url}
    if classifier_visible_published_at and not any(
        _is_non_empty_string(candidate.get(field))
        for field in ("source_published_at", "published_at", "source_updated_at", "source_observed_at", "source_authored_at")
    ):
        candidate_for_temporal["source_published_at"] = classifier_visible_published_at
    temporal_validation = validate_temporal_eligibility(
        candidate_for_temporal,
        dispatch_context=dispatch_context,
    )
    classifier_status, classifier_reason_codes = _merge_classifier_acceptance(
        classifier_status,
        classifier_reason_codes,
        family_hint_status=family_hint_status,
        family_hint_reasons=family_hint_reasons,
        visible_date_accepted=bool(classifier_visible_published_at),
        visible_date_reasons=visible_date_reason_codes,
    )
    resolutions = list(claim_family_resolutions or resolve_claim_families(claim_candidates or []))
    claim_family_ids = [
        resolution["claim_family_id"]
        for resolution in resolutions
        if resolution.get("counts_toward_claim_family_breadth") and resolution.get("claim_family_id") != "claim-family-unknown"
    ]
    if not claim_family_ids and isinstance(candidate.get("claim_family_resolution_refs"), list):
        claim_family_ids = [
            str(ref)
            for ref in candidate["claim_family_resolution_refs"]
            if _is_non_empty_string(ref) and "unknown" not in str(ref)
        ]
    if not claim_family_ids and isinstance(candidate.get("claim_family_ids"), list):
        claim_family_ids = [
            str(claim_id)
            for claim_id in candidate["claim_family_ids"]
            if _is_non_empty_string(claim_id) and "unknown" not in str(claim_id)
        ]
    independence_status = _resolve_independence_status(
        source_family_id=source_family_id,
        claim_family_ids=claim_family_ids,
        source_family_status=source_family_status,
        seen_source_family_ids=seen_source_family_ids,
        seen_claim_family_ids=seen_claim_family_ids,
    )
    counts_toward_breadth = (
        source_class != "unknown"
        and source_family_id != "source-family-unknown"
        and temporal_validation["temporal_gate_status"] == "pass"
        and independence_status in {"independent", "derived_from_primary"}
    )
    unknown_reason_codes = []
    if source_class == "unknown":
        unknown_reason_codes.extend(classifier_reason_codes or ["source_class_unknown"])
    if source_family_id == "source-family-unknown":
        unknown_reason_codes.append("source_family_unknown")
    if not claim_family_ids:
        unknown_reason_codes.append("claim_family_unknown_not_counted")
    if temporal_validation["temporal_gate_status"] != "pass":
        unknown_reason_codes.append(f"temporal_{temporal_validation['temporal_gate_status']}")

    classifier_ref = _classifier_slice_ref(classifier_slice)
    published_at = _iso_or_none(
        candidate.get("source_published_at")
        or candidate.get("published_at")
        or classifier_visible_published_at
    )
    published_at_method = str(candidate.get("published_at_extraction_method") or "unknown")
    if published_at == classifier_visible_published_at and published_at_method == "unknown":
        published_at_method = "classifier_visible_date_deterministically_parsed"
    elif visible_date_reason_codes and "classifier_visible_date_after_cutoff_not_accepted" in visible_date_reason_codes:
        unknown_reason_codes.append("classifier_visible_date_after_cutoff_not_accepted")
    if family_hint_reasons and family_hint_status is None:
        unknown_reason_codes.extend(family_hint_reasons)
    metadata_confidence = (
        "medium"
        if counts_toward_breadth
        else "low"
        if classifier_status in {"classifier_unsupported", "contradicted", "unsupported_source_class"}
        else "unknown"
    )
    metadata_resolution = build_source_metadata_resolution(
        evidence_ref=str(candidate.get("evidence_ref") or ""),
        transport_attempt_ref=str(candidate.get("transport_attempt_ref") or ""),
        requested_url=requested_url,
        final_url=final_url,
        canonical_url=canonical_url,
        canonical_source_id=canonical_source_id,
        source_class=source_class,
        source_class_resolution_method=source_class_method,
        source_family_id=source_family_id,
        source_family_resolution_method=source_family_method,
        source_family_status=source_family_status,
        claim_family_resolution_refs=[resolution["claim_family_resolution_id"] for resolution in resolutions],
        claim_family_ids=claim_family_ids,
        temporal_safety_status=temporal_validation["temporal_gate_status"],
        published_at=published_at,
        published_at_method=published_at_method,
        classifier_slice_ref=classifier_ref,
        classifier_acceptance_status=classifier_status,
        classifier_acceptance_reason_codes=classifier_reason_codes,
        metadata_confidence=metadata_confidence,
        counts_toward_breadth=counts_toward_breadth,
        unknown_reason_codes=sorted(set(unknown_reason_codes)),
        content_sha256=content_hash,
    )
    provenance_seed = {
        "evidence_ref": candidate.get("evidence_ref"),
        "candidate_id": candidate.get("candidate_id"),
        "transport_attempt_ref": candidate.get("transport_attempt_ref"),
        "canonical_url": canonical_url,
        "content_sha256": content_hash,
        "claim_family_ids": claim_family_ids,
    }
    return {
        "artifact_type": "retrieval_evidence_provenance",
        "schema_version": RETRIEVAL_EVIDENCE_PROVENANCE_SCHEMA_VERSION,
        "provenance_id": _sha_id("retrieval-provenance", provenance_seed),
        "evidence_ref": candidate.get("evidence_ref"),
        "candidate_id": candidate.get("candidate_id"),
        "retrieval_transport": retrieval_transport,
        "transport_attempt_ref": candidate.get("transport_attempt_ref"),
        "browser_attempt_ref": candidate.get("browser_attempt_ref") or (
            candidate.get("transport_attempt_ref") if retrieval_transport == "browser" else None
        ),
        "native_research_attempt_ref": candidate.get("native_research_attempt_ref") or (
            candidate.get("transport_attempt_ref") if retrieval_transport == "native_gpt_research" else None
        ),
        "source_metadata_resolution_ref": metadata_resolution["resolution_id"],
        "source_metadata_resolution": metadata_resolution,
        "source_metadata_classifier_ref": classifier_ref,
        "atomic_claim_candidate_refs": [candidate.get("claim_candidate_id") for candidate in claim_candidates or []],
        "claim_family_resolution_refs": [resolution["claim_family_resolution_id"] for resolution in resolutions],
        "claim_family_ids": claim_family_ids,
        "classifier_acceptance_status": classifier_status,
        "classifier_acceptance_reason_codes": classifier_reason_codes,
        "metadata_confidence": metadata_resolution["metadata_confidence"],
        "unknown_reason_codes": metadata_resolution["unknown_reason_codes"],
        "requested_url": requested_url,
        "final_url": final_url,
        "canonical_url": canonical_url,
        "url_identity_basis": "canonical_url" if canonical_url else "content_sha256",
        "captured_at": candidate.get("captured_at"),
        "artifact_generated_at": candidate.get("artifact_generated_at"),
        "source_published_at": candidate.get("source_published_at") or candidate.get("published_at"),
        "source_updated_at": candidate.get("source_updated_at"),
        "source_observed_at": candidate.get("source_observed_at"),
        "published_at_extraction_method": candidate.get("published_at_extraction_method") or "unknown",
        "canonical_source_id": canonical_source_id,
        "source_class": source_class,
        "source_family_id": source_family_id,
        "source_family_status": source_family_status,
        "independence_status": independence_status,
        "content_sha256": content_hash,
        "temporal_gate_status": temporal_validation["temporal_gate_status"],
        "temporal_validation_ref": temporal_validation["temporal_validation_id"],
        "temporal_validation": temporal_validation,
        "counts_toward_breadth": counts_toward_breadth,
        "normalizer_version": RETRIEVAL_PROVENANCE_NORMALIZER_VERSION,
    }


def _timestamps_from_inputs(
    qdt: dict[str, Any],
    evidence_packet: dict[str, Any] | None,
    forecast_timestamp: str | None,
    source_cutoff_timestamp: str | None,
) -> tuple[str, str]:
    forecast = (
        forecast_timestamp
        or (evidence_packet or {}).get("forecast_timestamp")
        or (evidence_packet or {}).get("market_context", {}).get("forecast_timestamp")
        or qdt.get("forecast_timestamp")
        or "1970-01-01T00:00:00+00:00"
    )
    cutoff = (
        source_cutoff_timestamp
        or (evidence_packet or {}).get("source_cutoff_timestamp")
        or (evidence_packet or {}).get("market_context", {}).get("source_cutoff_timestamp")
        or forecast
    )
    return str(forecast), str(cutoff)


def build_leaf_retrieval_result(
    query_context: dict[str, Any],
    *,
    selected_evidence: list[dict[str, Any]] | None = None,
    omitted_candidates: list[dict[str, Any]] | None = None,
    browser_attempt_refs: list[str] | None = None,
    native_research_attempt_refs: list[str] | None = None,
) -> dict[str, Any]:
    leaf_id = query_context["leaf_id"]
    selected = [item for item in selected_evidence or [] if item.get("leaf_id") == leaf_id]
    omitted = [item for item in omitted_candidates or [] if item.get("leaf_id") == leaf_id]
    return {
        "artifact_type": "leaf_retrieval_result",
        "schema_version": LEAF_RETRIEVAL_RESULT_SCHEMA_VERSION,
        "leaf_id": leaf_id,
        "parent_branch_id": query_context["parent_branch_id"],
        "query_context_ref": query_context["query_context_ref"],
        "selected_evidence_refs": [item["evidence_ref"] for item in selected],
        "selected_evidence": selected,
        "omitted_candidate_refs": [item["candidate_id"] for item in omitted],
        "omitted_candidates": omitted,
        "browser_retrieval_attempt_refs": list(browser_attempt_refs or []),
        "native_research_attempt_refs": list(native_research_attempt_refs or []),
        "source_metadata_resolution_refs": [
            item["source_metadata_resolution_ref"] for item in selected if item.get("source_metadata_resolution_ref")
        ],
        "evidence_chunk_refs": [chunk for item in selected for chunk in item.get("chunk_refs", [])],
        "atomic_claim_candidate_refs": [],
        "claim_family_resolution_refs": [
            ref for item in selected for ref in item.get("claim_family_resolution_refs", [])
        ],
        "result_status": "schema_only_pending_retrieval_execution" if not selected else "schema_only_with_supplied_evidence",
        "feature_gate_status": {
            "RET-002": "temporal_validation_enforced_for_selected_evidence",
            "RET-003": "quality_scoring_not_run",
            "RET-004": "provenance_resolution_normalized_for_selected_evidence",
            "RET-008": "sufficiency_certificate_not_run",
        },
    }


def _contexts_by_leaf(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contexts = packet.get("leaf_query_contexts", [])
    if not isinstance(contexts, list):
        return {}
    return {
        context.get("leaf_id"): context
        for context in contexts
        if isinstance(context, dict) and _is_non_empty_string(context.get("leaf_id"))
    }


def _results_by_leaf(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = packet.get("leaf_retrieval_results", [])
    if not isinstance(results, list):
        return {}
    return {
        result.get("leaf_id"): result
        for result in results
        if isinstance(result, dict) and _is_non_empty_string(result.get("leaf_id"))
    }


def _selected_from_result(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    selected = (result or {}).get("selected_evidence", [])
    if not isinstance(selected, list):
        return []
    return [item for item in selected if isinstance(item, dict)]


def _profile_by_leaf(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = packet.get("retrieval_breadth_profiles", [])
    if not isinstance(profiles, list):
        return {}
    return {
        profile.get("leaf_id"): profile
        for profile in profiles
        if isinstance(profile, dict) and _is_non_empty_string(profile.get("leaf_id"))
    }


def _attempts_by_leaf(attempts: list[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts or []:
        if isinstance(attempt, dict) and _is_non_empty_string(attempt.get("leaf_id")):
            grouped.setdefault(str(attempt["leaf_id"]), []).append(attempt)
    return grouped


def _metadata_field_known(item: dict[str, Any], field: str) -> bool:
    value = item.get(field)
    if field == "claim_family_ids":
        return isinstance(value, list) and any(_is_non_empty_string(claim_id) for claim_id in value)
    return _is_non_empty_string(value) and "unknown" not in str(value)


def build_retrieval_metadata_fill_diagnostic(
    leaf_id: str,
    retrieval_transport: str,
    *,
    selected: list[dict[str, Any]],
    omitted: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_count = len(selected) + len(omitted or [])
    admitted_count = len(selected)
    source_class_count = sum(1 for item in selected if _metadata_field_known(item, "source_class"))
    source_family_count = sum(1 for item in selected if _metadata_field_known(item, "source_family_id"))
    claim_family_count = sum(1 for item in selected if _metadata_field_known(item, "claim_family_ids"))
    temporal_count = sum(1 for item in selected if item.get("temporal_gate_status") == "pass")
    unknown_source_class_count = sum(1 for item in selected if item.get("source_class") == "unknown")
    unknown_source_family_count = sum(
        1 for item in selected if item.get("source_family_id") in {None, "", "source-family-unknown"}
    )
    unknown_claim_family_count = sum(1 for item in selected if not _metadata_field_known(item, "claim_family_ids"))
    unknown_temporal_count = sum(1 for item in selected if item.get("temporal_gate_status") != "pass")
    seed = {
        "leaf_id": leaf_id,
        "retrieval_transport": retrieval_transport,
        "selected_refs": [item.get("evidence_ref") for item in selected],
        "omitted_refs": [item.get("candidate_id") for item in omitted or []],
    }
    denominator = max(1, admitted_count)
    return {
        "artifact_type": "retrieval_metadata_fill_diagnostic",
        "schema_version": RETRIEVAL_METADATA_FILL_DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_id": _sha_id("metadata-fill", seed),
        "leaf_id": leaf_id,
        "retrieval_transport": retrieval_transport,
        "raw_candidate_count": raw_count,
        "admitted_ref_count": admitted_count,
        "field_fill_counts": {
            "source_class": source_class_count,
            "source_family": source_family_count,
            "claim_family": claim_family_count,
            "temporal": temporal_count,
        },
        "unknown_counts": {
            "source_class": unknown_source_class_count,
            "source_family": unknown_source_family_count,
            "claim_family": unknown_claim_family_count,
            "temporal": unknown_temporal_count,
        },
        "fill_rates": {
            "source_class": source_class_count / denominator,
            "source_family": source_family_count / denominator,
            "claim_family": claim_family_count / denominator,
            "temporal": temporal_count / denominator,
        },
        "diagnostic_authority": "metadata_fill_only_not_sufficiency",
        "evaluator_version": RETRIEVAL_BREADTH_EVALUATOR_VERSION,
    }


def build_retrieval_metadata_fill_diagnostics(packet: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for result in packet.get("leaf_retrieval_results", []) if isinstance(packet.get("leaf_retrieval_results"), list) else []:
        if not isinstance(result, dict):
            continue
        leaf_id = str(result.get("leaf_id") or "")
        selected = _selected_from_result(result)
        omitted = [item for item in result.get("omitted_candidates", []) if isinstance(item, dict)]
        transports = sorted(
            {
                str(item.get("retrieval_transport"))
                for item in [*selected, *omitted]
                if _is_non_empty_string(item.get("retrieval_transport"))
            }
            or {"none"}
        )
        for transport in transports:
            selected_for_transport = [
                item for item in selected if str(item.get("retrieval_transport") or "none") == transport
            ]
            omitted_for_transport = [
                item for item in omitted if str(item.get("retrieval_transport") or "none") == transport
            ]
            diagnostics.append(
                build_retrieval_metadata_fill_diagnostic(
                    leaf_id,
                    transport,
                    selected=selected_for_transport,
                    omitted=omitted_for_transport,
                )
            )
    return diagnostics


def build_contradiction_search_attempt(
    query_context: dict[str, Any],
    query_variant: dict[str, Any],
    *,
    source_refs: list[str] | None = None,
    outcome_status: str = "attempted_no_contradiction_found",
) -> dict[str, Any]:
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "source_refs": source_refs or [],
        "outcome_status": outcome_status,
    }
    return {
        "artifact_type": "contradiction_search_attempt",
        "schema_version": CONTRADICTION_SEARCH_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": _sha_id("contradiction-attempt", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "query_text": query_variant.get("query_text"),
        "query_text_sha256": query_variant.get("query_text_sha256"),
        "source_refs_checked": list(source_refs or []),
        "contradiction_found": False,
        "outcome_status": outcome_status,
        "attempt_authority": "retrieval_diagnostic_only",
        "evaluator_version": RETRIEVAL_BREADTH_EVALUATOR_VERSION,
    }


def build_negative_check_attempt(
    query_context: dict[str, Any],
    check_name: str,
    query_text: str,
    *,
    source_refs: list[str] | None = None,
    outcome_status: str = "no_confirmation_found",
) -> dict[str, Any]:
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "check_name": check_name,
        "query_text": query_text,
        "source_refs": source_refs or [],
        "outcome_status": outcome_status,
    }
    return {
        "artifact_type": "negative_check_attempt",
        "schema_version": NEGATIVE_CHECK_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": _sha_id("negative-check", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "negative_check": check_name,
        "query_text": query_text,
        "query_text_sha256": _prefixed_sha256(query_text),
        "source_refs_checked": list(source_refs or []),
        "outcome_status": outcome_status,
        "no_confirmation_found": outcome_status == "no_confirmation_found",
        "attempt_authority": "retrieval_diagnostic_only",
        "evaluator_version": RETRIEVAL_BREADTH_EVALUATOR_VERSION,
    }


def build_required_contradiction_and_negative_attempts(packet: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contradiction_attempts: list[dict[str, Any]] = []
    negative_attempts: list[dict[str, Any]] = []
    results = _results_by_leaf(packet)
    for context in packet.get("leaf_query_contexts", []) if isinstance(packet.get("leaf_query_contexts"), list) else []:
        if not isinstance(context, dict):
            continue
        result = results.get(context.get("leaf_id"))
        source_refs = [item.get("evidence_ref") for item in _selected_from_result(result) if item.get("evidence_ref")]
        for variant in context.get("contradiction_query_variants", []):
            if isinstance(variant, dict):
                contradiction_attempts.append(
                    build_contradiction_search_attempt(context, variant, source_refs=source_refs)
                )
        negative_variants = context.get("negative_check_query_variants", {})
        if isinstance(negative_variants, dict):
            for check_name, query_texts in sorted(negative_variants.items()):
                if isinstance(query_texts, list):
                    for query_text in query_texts:
                        if _is_non_empty_string(query_text):
                            negative_attempts.append(
                                build_negative_check_attempt(
                                    context,
                                    str(check_name),
                                    str(query_text),
                                    source_refs=source_refs,
                                )
                            )
    return contradiction_attempts, negative_attempts


def build_leaf_evidence_dockets(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Build per-leaf evidence dockets before classification/sidecar dispatch."""

    certificates = {
        str(item.get("leaf_id")): item
        for item in packet.get("leaf_research_sufficiency_certificates", [])
        if isinstance(item, dict) and _is_non_empty_string(item.get("leaf_id"))
    }
    dockets: list[dict[str, Any]] = []
    for result in packet.get("leaf_retrieval_results", []) if isinstance(packet.get("leaf_retrieval_results"), list) else []:
        if not isinstance(result, dict) or not _is_non_empty_string(result.get("leaf_id")):
            continue
        leaf_id = str(result["leaf_id"])
        selected = _selected_from_result(result)
        omitted = [item for item in result.get("omitted_candidates", []) if isinstance(item, dict)]
        cert = certificates.get(leaf_id, {})
        supplemental_candidates = [
            item
            for item in packet.get("supplemental_evidence_candidates", [])
            if isinstance(item, dict) and str(item.get("leaf_id") or "") == leaf_id
        ] if isinstance(packet.get("supplemental_evidence_candidates"), list) else []
        supplemental_admissions = [
            item
            for item in packet.get("supplemental_evidence_admission_results", [])
            if isinstance(item, dict) and str(item.get("leaf_id") or "") == leaf_id
        ] if isinstance(packet.get("supplemental_evidence_admission_results"), list) else []
        docket_seed = {
            "leaf_id": leaf_id,
            "selected": [item.get("evidence_ref") for item in selected],
            "omitted": [item.get("candidate_id") for item in omitted],
            "certificate": cert.get("certificate_id"),
            "supplemental": [item.get("supplemental_evidence_ref") or item.get("evidence_ref") for item in supplemental_candidates],
        }
        proceed = cert.get("classification_dispatch_allowed") is True and cert.get("status") == "certified_high_certainty"
        dockets.append(
            {
                "artifact_type": "leaf_evidence_docket",
                "schema_version": "leaf-evidence-docket/v1",
                "docket_id": _sha_id("leaf-evidence-docket", docket_seed),
                "leaf_id": leaf_id,
                "query_context_ref": result.get("query_context_ref"),
                "admitted_evidence_refs": [item["evidence_ref"] for item in selected if _is_non_empty_string(item.get("evidence_ref"))],
                "rejected_or_omitted_candidate_refs": [
                    item["candidate_id"] for item in omitted if _is_non_empty_string(item.get("candidate_id"))
                ],
                "supplemental_candidate_refs": [
                    str(item.get("supplemental_evidence_ref") or item.get("evidence_ref"))
                    for item in supplemental_candidates
                    if _is_non_empty_string(item.get("supplemental_evidence_ref") or item.get("evidence_ref"))
                ],
                "supplemental_admission_result_refs": [
                    str(item.get("admission_result_ref") or item.get("normalized_supplemental_evidence_ref"))
                    for item in supplemental_admissions
                    if _is_non_empty_string(item.get("admission_result_ref") or item.get("normalized_supplemental_evidence_ref"))
                ],
                "research_sufficiency_certificate_ref": cert.get("certificate_id"),
                "research_sufficiency_status": cert.get("status", "not_certified"),
                "classification_dispatch_allowed": bool(cert.get("classification_dispatch_allowed") is True),
                "proceed_to_classification": bool(proceed),
                "proceed_block_reason_codes": [] if proceed else list(cert.get("blocking_reason_codes", []) or ["research_sufficiency_not_certified"]),
                "evidence_admission_authority": "deterministic_retrieval_resolvers_only",
                "classification_authority": False,
                "scae_authority": False,
            }
        )
    return dockets


def _fresh_source_count(selected: list[dict[str, Any]], profile: dict[str, Any], source_cutoff_timestamp: str | None) -> int:
    requirement = profile.get("freshness_requirement") if isinstance(profile.get("freshness_requirement"), dict) else {}
    window_seconds = int(requirement.get("recency_window_seconds", 0) or 0)
    if window_seconds <= 0:
        return sum(1 for item in selected if item.get("temporal_gate_status") == "pass")
    cutoff = _parse_timestamp(source_cutoff_timestamp)
    if cutoff is None:
        return 0
    threshold = cutoff - timedelta(seconds=window_seconds)
    count = 0
    for item in selected:
        if item.get("temporal_gate_status") != "pass":
            continue
        published = _parse_timestamp(
            item.get("source_published_at")
            or item.get("published_at")
            or item.get("source_updated_at")
            or item.get("source_observed_at")
        )
        if published is not None and threshold <= published <= cutoff:
            count += 1
    return count


def _independent_selected(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in selected
        if item.get("counts_toward_breadth") is True
        and item.get("independence_status") in {"independent", "derived_from_primary"}
    ]


def build_retrieval_breadth_coverage_slice(
    query_context: dict[str, Any],
    profile: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    contradiction_attempts: list[dict[str, Any]],
    negative_check_attempts: list[dict[str, Any]],
    metadata_fill_diagnostics: list[dict[str, Any]],
    source_cutoff_timestamp: str | None,
) -> dict[str, Any]:
    selected = _selected_from_result(result)
    omitted = [item for item in (result or {}).get("omitted_candidates", []) if isinstance(item, dict)]
    independent = _independent_selected(selected)
    source_class_coverage: dict[str, dict[str, Any]] = {}
    for item in selected:
        source_class = str(item.get("source_class") or "unknown")
        bucket = source_class_coverage.setdefault(
            source_class,
            {"admitted_count": 0, "independent_count": 0, "evidence_refs": []},
        )
        bucket["admitted_count"] += 1
        if item in independent:
            bucket["independent_count"] += 1
            if item.get("evidence_ref"):
                bucket["evidence_refs"].append(item["evidence_ref"])
    claim_family_ids = sorted(
        {
            str(claim_id)
            for item in independent
            for claim_id in item.get("claim_family_ids", [])
            if _is_non_empty_string(claim_id)
        }
    )
    source_family_ids = sorted(
        {
            str(item.get("source_family_id"))
            for item in independent
            if _is_non_empty_string(item.get("source_family_id")) and item.get("source_family_id") != "source-family-unknown"
        }
    )
    fresh_source_count = _fresh_source_count(selected, profile, source_cutoff_timestamp)
    required_source_classes = [
        item
        for item in profile.get("source_class_requirements", {}).get("required", [])
        if item in ALLOWED_SOURCE_CLASSES and item != "unknown"
    ]
    min_claim_families = int(
        profile.get("claim_family_requirements", {}).get("min_independent_claim_families", 0) or 0
    )
    min_source_families = int(
        profile.get("source_family_requirements", {}).get("min_independent_source_families", 0) or 0
    )
    min_fresh_sources = int(profile.get("freshness_requirement", {}).get("min_fresh_sources", 0) or 0)
    min_admitted_evidence = int(
        profile.get("admitted_evidence_requirement", {}).get("min_admitted_evidence_items", 0) or 0
    )
    contradiction_refs = [attempt["attempt_id"] for attempt in contradiction_attempts]
    negative_refs = [attempt["attempt_id"] for attempt in negative_check_attempts]
    protected_required = bool(profile.get("source_class_requirements", {}).get("protected_primary_required"))
    protected_satisfied = any(
        item.get("source_class") in PROTECTED_SOURCE_CLASSES and item.get("temporal_gate_status") == "pass"
        for item in selected
    )
    requirements = (
        query_context.get("sufficiency_requirements")
        if isinstance(query_context.get("sufficiency_requirements"), dict)
        else {}
    )
    structural_unanswerability_proof_ref = (
        requirements.get("structural_unanswerability_proof_ref")
        or (result or {}).get("structural_unanswerability_proof_ref")
    )
    protected_status = "not_required"
    protected_basis = "not_required"
    if protected_required:
        if protected_satisfied:
            protected_status = "satisfied"
            protected_basis = "admitted_protected_primary"
        elif _is_non_empty_string(structural_unanswerability_proof_ref):
            protected_status = "satisfied"
            protected_basis = "structural_unanswerability_proof"
        else:
            protected_status = "blocked"
            protected_basis = "missing_protected_primary"

    unknown_counts = {
        "source_class": sum(1 for item in selected if item.get("source_class") == "unknown"),
        "source_family": sum(1 for item in selected if item.get("source_family_id") in {None, "", "source-family-unknown"}),
        "claim_family": sum(1 for item in selected if not _metadata_field_known(item, "claim_family_ids")),
        "temporal": sum(1 for item in selected if item.get("temporal_gate_status") != "pass"),
    }
    unsatisfied: list[str] = []
    for source_class in required_source_classes:
        if source_class_coverage.get(source_class, {}).get("independent_count", 0) < 1:
            unsatisfied.append(f"source_class:{source_class}")
    if len(claim_family_ids) < min_claim_families:
        unsatisfied.append("claim_family_diversity")
    if len(source_family_ids) < min_source_families:
        unsatisfied.append("source_family_diversity")
    if fresh_source_count < min_fresh_sources:
        unsatisfied.append("freshness")
    if len(selected) < min_admitted_evidence:
        unsatisfied.append("admitted_evidence_count")
    if profile.get("contradiction_search", {}).get("required") and not contradiction_refs:
        unsatisfied.append("contradiction_search_attempt_missing")
    required_negative_checks = profile.get("negative_checks", {}).get("required_checks", [])
    present_negative_checks = {attempt.get("negative_check") for attempt in negative_check_attempts}
    for check in required_negative_checks if isinstance(required_negative_checks, list) else []:
        if check not in present_negative_checks:
            unsatisfied.append(f"negative_check:{check}")
    if protected_status == "blocked":
        unsatisfied.append("protected_primary_blocked")

    blocking_unknown_fields: list[str] = []
    if unknown_counts["source_class"] and any(item.startswith("source_class:") for item in unsatisfied):
        blocking_unknown_fields.append("source_class")
    if unknown_counts["source_family"] and "source_family_diversity" in unsatisfied:
        blocking_unknown_fields.append("source_family")
    if unknown_counts["claim_family"] and "claim_family_diversity" in unsatisfied:
        blocking_unknown_fields.append("claim_family")
    if unknown_counts["temporal"] and "freshness" in unsatisfied:
        blocking_unknown_fields.append("temporal")
    for field in blocking_unknown_fields:
        unsatisfied.append(f"unknown_{field}_blocks_required_breadth")

    metadata_refs = [
        diagnostic["diagnostic_id"]
        for diagnostic in metadata_fill_diagnostics
        if diagnostic.get("leaf_id") == query_context.get("leaf_id")
    ]
    coverage_seed = {
        "leaf_id": query_context.get("leaf_id"),
        "profile_id": profile.get("profile_id"),
        "selected_refs": [item.get("evidence_ref") for item in selected],
        "contradiction_refs": contradiction_refs,
        "negative_refs": negative_refs,
    }
    return {
        "artifact_type": "retrieval_breadth_coverage",
        "schema_version": RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION,
        "coverage_id": _sha_id("breadth-coverage", coverage_seed),
        "leaf_id": query_context.get("leaf_id"),
        "breadth_profile_ref": profile.get("profile_id"),
        "source_class_coverage": source_class_coverage,
        "claim_family_count": len(claim_family_ids),
        "source_family_count": len(source_family_ids),
        "fresh_source_count": fresh_source_count,
        "contradiction_attempt_refs": contradiction_refs,
        "negative_check_attempt_refs": negative_refs,
        "protected_primary_status": protected_status,
        "protected_primary_resolution_basis": protected_basis,
        "structural_unanswerability_proof_ref": structural_unanswerability_proof_ref,
        "raw_candidate_count": len(selected) + len(omitted),
        "admitted_ref_count": len(selected),
        "min_admitted_evidence_items": min_admitted_evidence,
        "independent_claim_family_ids": claim_family_ids,
        "independent_source_family_ids": source_family_ids,
        "metadata_fill_diagnostic_refs": metadata_refs,
        "unknown_field_counts": unknown_counts,
        "blocking_unknown_fields": sorted(set(blocking_unknown_fields)),
        "expansion_required": bool(unsatisfied),
        "expansion_requirement_codes": sorted(set(unsatisfied)),
        "unsatisfied_breadth_dimensions": sorted(set(unsatisfied)),
        "breadth_certified": not unsatisfied,
        "evaluator_version": RETRIEVAL_BREADTH_EVALUATOR_VERSION,
    }


def build_retrieval_breadth_coverage_slices(packet: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = _profile_by_leaf(packet)
    results = _results_by_leaf(packet)
    contradiction_by_leaf = _attempts_by_leaf(packet.get("contradiction_search_attempts", []))
    negative_by_leaf = _attempts_by_leaf(packet.get("negative_check_attempts", []))
    metadata_fill = packet.get("retrieval_metadata_fill_diagnostics", [])
    if not isinstance(metadata_fill, list):
        metadata_fill = []
    coverage: list[dict[str, Any]] = []
    for context in packet.get("leaf_query_contexts", []) if isinstance(packet.get("leaf_query_contexts"), list) else []:
        if not isinstance(context, dict):
            continue
        leaf_id = context.get("leaf_id")
        profile = profiles.get(leaf_id)
        if not isinstance(profile, dict):
            continue
        coverage.append(
            build_retrieval_breadth_coverage_slice(
                context,
                profile,
                results.get(leaf_id),
                contradiction_attempts=contradiction_by_leaf.get(str(leaf_id), []),
                negative_check_attempts=negative_by_leaf.get(str(leaf_id), []),
                metadata_fill_diagnostics=metadata_fill,
                source_cutoff_timestamp=packet.get("source_cutoff_timestamp"),
            )
        )
    return coverage


def _required_source_classes_from_context(context: dict[str, Any]) -> list[str]:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    raw = targets.get("source_class_targets", [])
    if not isinstance(raw, list):
        return []
    return sorted({str(item) for item in raw if item in ALLOWED_SOURCE_CLASSES and item != "unknown"})


def _selected_source_classes(selected: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("source_class"))
        for item in selected
        if item.get("temporal_gate_status") == "pass" and item.get("source_class") in ALLOWED_SOURCE_CLASSES
    }


def _protected_primary_required(context: dict[str, Any]) -> bool:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    return bool(targets.get("protected_primary_required") is True)


def _protected_primary_admitted_for_context(selected: list[dict[str, Any]]) -> bool:
    return any(
        item.get("source_class") in PROTECTED_SOURCE_CLASSES and item.get("temporal_gate_status") == "pass"
        for item in selected
    )


def _leaf_static_weight_from_context(context: dict[str, Any]) -> str:
    requirements = context.get("sufficiency_requirements")
    if isinstance(requirements, dict) and _is_non_empty_string(requirements.get("static_information_weight")):
        return str(requirements["static_information_weight"])
    return "medium"


def _leaf_is_critical_or_source_of_truth(context: dict[str, Any]) -> bool:
    return (
        context.get("purpose") == "source_of_truth"
        or _leaf_static_weight_from_context(context) == "critical"
        or _protected_primary_required(context)
    )


def _minimum_selected_for_context(context: dict[str, Any]) -> int:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    minimum = 1
    for field in (
        "min_independent_source_families",
        "min_independent_claim_families",
        "min_temporally_fresh_sources",
    ):
        value = targets.get(field, 0)
        if isinstance(value, int) and not isinstance(value, bool):
            minimum = max(minimum, value)
    return minimum


def _expected_source_refs(context: dict[str, Any]) -> list[dict[str, Any]]:
    refs = context.get("direct_url_candidates", [])
    if not isinstance(refs, list):
        return []
    compact = []
    for item in refs[:8]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "url": item.get("url"),
                "source_ref": item.get("source_ref"),
                "direct_url_priority": item.get("direct_url_priority"),
            }
        )
    return compact


def build_protected_primary_access_failure(
    query_context: dict[str, Any],
    result: dict[str, Any] | None = None,
    *,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    selected = _selected_from_result(result)
    browser_attempt_refs = list((result or {}).get("browser_retrieval_attempt_refs") or [])
    native_attempt_refs = list((result or {}).get("native_research_attempt_refs") or [])
    observed_attempt_refs = browser_attempt_refs + native_attempt_refs
    reasons = list(reason_codes or [])
    if not reasons:
        reasons.append("no_admitted_protected_primary")
    if observed_attempt_refs:
        reasons.append("protected_primary_not_admitted_after_attempts")
    else:
        reasons.append("protected_primary_not_attempted")
    if not _expected_source_refs(query_context):
        reasons.append("expected_protected_source_unknown")
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "reasons": sorted(set(reasons)),
        "selected": [item.get("evidence_ref") for item in selected],
    }
    return {
        "artifact_type": "protected_primary_access_failure",
        "schema_version": PROTECTED_PRIMARY_ACCESS_FAILURE_SCHEMA_VERSION,
        "failure_id": _sha_id("protected-primary-failure", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "required_source_classes": [
            item for item in _required_source_classes_from_context(query_context) if item in PROTECTED_SOURCE_CLASSES
        ],
        "expected_source_refs": _expected_source_refs(query_context),
        "observed_attempt_refs": observed_attempt_refs,
        "admitted_evidence_refs": [
            item.get("evidence_ref")
            for item in selected
            if item.get("source_class") in PROTECTED_SOURCE_CLASSES and item.get("temporal_gate_status") == "pass"
        ],
        "access_status": "missing" if not observed_attempt_refs else "attempted_without_admitted_primary",
        "reason_codes": sorted(set(reasons)),
        "candidate_tracking_only": True,
        "authority_boundary": {
            "authors_new_evidence": False,
            "signed_missingness_authority": False,
            "classification_dispatch_authority": False,
            "research_sufficiency_authority": False,
        },
        "tracker_version": RETRIEVAL_SOURCE_ACCESS_TRACKER_VERSION,
    }


def build_expected_source_missingness_candidate(
    query_context: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    expected_source_class: str,
    reason_codes: list[str] | None = None,
    expected_source_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = _selected_from_result(result)
    reasons = list(reason_codes or ["required_source_class_absent"])
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "expected_source_class": expected_source_class,
        "expected_source_ref": expected_source_ref,
        "selected": [item.get("evidence_ref") for item in selected],
        "reasons": sorted(set(reasons)),
    }
    return {
        "artifact_type": "expected_source_missingness_candidate",
        "schema_version": EXPECTED_SOURCE_MISSINGNESS_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": _sha_id("missingness-candidate", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "expected_source_class": expected_source_class,
        "expected_source_ref": expected_source_ref,
        "missingness_status": "candidate_unresolved",
        "missingness_basis": "expected_source_not_admitted",
        "evidence_refs_checked": [item.get("evidence_ref") for item in selected if item.get("evidence_ref")],
        "attempt_refs_checked": list((result or {}).get("browser_retrieval_attempt_refs") or [])
        + list((result or {}).get("native_research_attempt_refs") or []),
        "distinct_absence_mechanism_proof_ref": None,
        "reason_codes": sorted(set(reasons)),
        "candidate_tracking_only": True,
        "authority_boundary": {
            "authors_new_evidence": False,
            "signed_missingness_authority": False,
            "scae_missingness_authority": False,
            "classification_dispatch_authority": False,
            "research_sufficiency_authority": False,
        },
        "tracker_version": RETRIEVAL_SOURCE_ACCESS_TRACKER_VERSION,
    }


def build_source_access_and_missingness_report(packet: dict[str, Any]) -> dict[str, Any]:
    contexts = _contexts_by_leaf(packet)
    results = _results_by_leaf(packet)
    failures: list[dict[str, Any]] = []
    missingness: list[dict[str, Any]] = []
    for leaf_id, context in sorted(contexts.items()):
        result = results.get(leaf_id, {})
        selected = _selected_from_result(result)
        present_classes = _selected_source_classes(selected)
        missing_classes = [
            source_class
            for source_class in _required_source_classes_from_context(context)
            if source_class not in present_classes
        ]
        if _protected_primary_required(context) and not _protected_primary_admitted_for_context(selected):
            failures.append(build_protected_primary_access_failure(context, result))
        for source_class in missing_classes:
            missingness.append(
                build_expected_source_missingness_candidate(
                    context,
                    result,
                    expected_source_class=source_class,
                    reason_codes=[
                        "required_source_class_absent",
                        "protected_primary_missing" if source_class in PROTECTED_SOURCE_CLASSES else "expected_source_class_missing",
                    ],
                )
            )
        for expected in _expected_source_refs(context):
            url = canonicalize_source_url(expected.get("url"))
            if not url:
                continue
            if any(
                canonicalize_source_url(item.get("canonical_url"), item.get("final_url"), item.get("requested_url")) == url
                for item in selected
            ):
                continue
            missingness.append(
                build_expected_source_missingness_candidate(
                    context,
                    result,
                    expected_source_class="unknown",
                    expected_source_ref=expected,
                    reason_codes=["direct_expected_source_not_admitted"],
                )
            )
    return {
        "feature_id": "RET-005",
        "tracker_version": RETRIEVAL_SOURCE_ACCESS_TRACKER_VERSION,
        "protected_primary_access_failures": failures,
        "missingness_candidates": missingness,
        "summary": {
            "leaf_count": len(contexts),
            "protected_primary_failure_count": len(failures),
            "missingness_candidate_count": len(missingness),
            "candidate_tracking_only": True,
        },
    }


def attach_source_access_and_missingness(packet: dict[str, Any]) -> dict[str, Any]:
    packet_copy = copy.deepcopy(packet)
    report = build_source_access_and_missingness_report(packet_copy)
    packet_copy["protected_primary_access_failures"] = report["protected_primary_access_failures"]
    packet_copy["missingness_candidates"] = report["missingness_candidates"]
    packet_copy["source_access_missingness_summary"] = report["summary"]
    packet_copy.setdefault("schema_feature_gates", {})["RET-005"] = "implemented"
    packet_copy.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        "ret_005_source_access_missingness_tracked"
    )
    result = validate_retrieval_packet(packet_copy)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    return packet_copy


def _unsatisfied_requirement_codes_for_expansion(context: dict[str, Any], result: dict[str, Any] | None) -> list[str]:
    selected = _selected_from_result(result)
    selected_count = len(selected)
    minimum = _minimum_selected_for_context(context)
    codes: list[str] = []
    if selected_count == 0:
        codes.append("empty_retrieval")
    elif selected_count < minimum:
        codes.append("thin_retrieval")
    present_classes = _selected_source_classes(selected)
    if any(source_class not in present_classes for source_class in _required_source_classes_from_context(context)):
        codes.append("required_source_class_missing")
    if _protected_primary_required(context) and not _protected_primary_admitted_for_context(selected):
        codes.append("protected_primary_missing")
    return sorted(set(codes))


def build_retrieval_expansion_attempt(
    query_context: dict[str, Any],
    *,
    attempt_index: int,
    unsatisfied_requirement_codes: list[str],
    attempt_status: str = "planned_not_executed",
) -> dict[str, Any]:
    requirements = query_context.get("sufficiency_requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    max_attempts = int(requirements.get("max_targeted_expansion_attempts", 1) or 1)
    if attempt_index < 1 or attempt_index > max_attempts:
        raise RetrievalPacketError("attempt_index must be within max_targeted_expansion_attempts")
    base_terms = " ".join(query_context.get("market_component_terms", [])[:6])
    unsatisfied = " ".join(unsatisfied_requirement_codes).replace("_", " ")
    query_text = _bounded_query_text(
        f"{query_context.get('leaf_question', '')} targeted expansion {attempt_index} {unsatisfied} {base_terms} before cutoff"
    )
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "attempt_index": attempt_index,
        "unsatisfied": sorted(set(unsatisfied_requirement_codes)),
    }
    return {
        "artifact_type": "retrieval_expansion_attempt",
        "schema_version": RETRIEVAL_EXPANSION_ATTEMPT_SCHEMA_VERSION,
        "attempt_id": _sha_id("retrieval-expansion", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "attempt_index": int(attempt_index),
        "max_attempts": max_attempts,
        "expansion_strategy": "targeted_requirement_expansion",
        "attempt_status": attempt_status,
        "unsatisfied_requirement_codes": sorted(set(unsatisfied_requirement_codes)),
        "query_variant_refs": [
            item.get("query_variant_id")
            for item in query_context.get("query_variants", [])
            if isinstance(item, dict) and item.get("query_variant_id")
        ],
        "expansion_query_text_sha256": _prefixed_sha256(query_text),
        "candidate_refs": [],
        "admitted_evidence_refs": [],
        "bounded_by_requirement_max": True,
        "macro_fallback_phase": False,
        "authority_boundary": {
            "authors_new_evidence": False,
            "classification_dispatch_authority": False,
            "research_sufficiency_authority": False,
        },
        "planner_version": RETRIEVAL_EXPANSION_FALLBACK_VERSION,
    }


def build_retrieval_fallback_state(
    query_context: dict[str, Any],
    expansion_attempt_refs: list[str],
    *,
    macro_fallback_requested: bool = False,
) -> dict[str, Any]:
    requirements = query_context.get("sufficiency_requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    critical_or_source = _leaf_is_critical_or_source_of_truth(query_context)
    allowed_by_leaf = bool(requirements.get("allow_macro_fallback_for_leaf") is True)
    macro_fallback_used = bool(macro_fallback_requested and allowed_by_leaf and not critical_or_source)
    reason_codes = ["macro_fallback_last_resort_discovery_only"]
    if critical_or_source:
        reason_codes.append("macro_fallback_not_sufficient_for_critical_or_source_of_truth")
    if not allowed_by_leaf:
        reason_codes.append("macro_fallback_not_allowed_by_leaf_requirements")
    if not expansion_attempt_refs:
        reason_codes.append("targeted_expansion_required_before_macro_fallback")
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "expansion_attempt_refs": expansion_attempt_refs,
        "macro_fallback_requested": macro_fallback_requested,
        "macro_fallback_used": macro_fallback_used,
    }
    return {
        "artifact_type": "retrieval_fallback_state",
        "schema_version": RETRIEVAL_FALLBACK_STATE_SCHEMA_VERSION,
        "fallback_state_id": _sha_id("retrieval-fallback", seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "targeted_expansion_attempt_refs": list(expansion_attempt_refs),
        "targeted_expansion_required_before_macro_fallback": True,
        "macro_fallback_requested": bool(macro_fallback_requested),
        "macro_fallback_used": macro_fallback_used,
        "macro_fallback_policy": "explicit_last_resort_discovery_only",
        "macro_fallback_sufficiency_status": (
            "not_sufficient_for_critical_or_source_of_truth"
            if critical_or_source
            else "not_research_sufficiency_authority"
        ),
        "classification_dispatch_allowed_from_macro_fallback": False,
        "reason_codes": sorted(set(reason_codes)),
        "authority_boundary": {
            "authors_new_evidence": False,
            "critical_or_source_of_truth_sufficiency_authority": False,
            "classification_dispatch_authority": False,
            "research_sufficiency_authority": False,
        },
        "planner_version": RETRIEVAL_EXPANSION_FALLBACK_VERSION,
    }


def build_retrieval_expansion_and_fallback_plan(
    packet: dict[str, Any],
    *,
    macro_fallback_requested: bool = False,
) -> dict[str, Any]:
    contexts = _contexts_by_leaf(packet)
    results = _results_by_leaf(packet)
    attempts: list[dict[str, Any]] = []
    fallback_states: list[dict[str, Any]] = []
    for leaf_id, context in sorted(contexts.items()):
        result = results.get(leaf_id, {})
        unsatisfied = _unsatisfied_requirement_codes_for_expansion(context, result)
        if not unsatisfied:
            continue
        requirements = context.get("sufficiency_requirements")
        max_attempts = 1
        if isinstance(requirements, dict):
            max_attempts = int(requirements.get("max_targeted_expansion_attempts", 1) or 1)
        leaf_attempts = [
            build_retrieval_expansion_attempt(
                context,
                attempt_index=attempt_index,
                unsatisfied_requirement_codes=unsatisfied,
            )
            for attempt_index in range(1, max_attempts + 1)
        ]
        attempts.extend(leaf_attempts)
        fallback_states.append(
            build_retrieval_fallback_state(
                context,
                [attempt["attempt_id"] for attempt in leaf_attempts],
                macro_fallback_requested=macro_fallback_requested,
            )
        )
    return {
        "feature_id": "RET-006",
        "planner_version": RETRIEVAL_EXPANSION_FALLBACK_VERSION,
        "retrieval_expansion_attempts": attempts,
        "retrieval_fallback_states": fallback_states,
        "summary": {
            "leaf_count": len(contexts),
            "starved_leaf_count": len(fallback_states),
            "targeted_expansion_attempt_count": len(attempts),
            "macro_fallback_state_count": len(fallback_states),
            "macro_fallback_discovery_only": True,
        },
    }


def attach_retrieval_expansion_and_fallback_plan(
    packet: dict[str, Any],
    *,
    macro_fallback_requested: bool = False,
) -> dict[str, Any]:
    packet_copy = copy.deepcopy(packet)
    plan = build_retrieval_expansion_and_fallback_plan(
        packet_copy,
        macro_fallback_requested=macro_fallback_requested,
    )
    packet_copy["retrieval_expansion_attempts"] = plan["retrieval_expansion_attempts"]
    packet_copy["retrieval_fallback_states"] = plan["retrieval_fallback_states"]
    packet_copy["retrieval_fallback_summary"] = plan["summary"]
    packet_copy.setdefault("schema_feature_gates", {})["RET-006"] = "implemented"
    packet_copy.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        "ret_006_expansion_fallback_planned"
    )
    result = validate_retrieval_packet(packet_copy)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    return packet_copy


def _coverage_by_leaf(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    coverage = packet.get("retrieval_breadth_coverage_slices", [])
    if not isinstance(coverage, list):
        return {}
    return {
        item.get("leaf_id"): item
        for item in coverage
        if isinstance(item, dict) and _is_non_empty_string(item.get("leaf_id"))
    }


def _fallback_by_leaf(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    states = packet.get("retrieval_fallback_states", [])
    if not isinstance(states, list):
        return {}
    return {
        item.get("leaf_id"): item
        for item in states
        if isinstance(item, dict) and _is_non_empty_string(item.get("leaf_id"))
    }


def _expansion_attempts_by_leaf(packet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    attempts = packet.get("retrieval_expansion_attempts", [])
    if not isinstance(attempts, list):
        return {}
    return _attempts_by_leaf(attempts)


def _max_expansion_attempts(context: dict[str, Any]) -> int:
    requirements = context.get("sufficiency_requirements")
    if not isinstance(requirements, dict):
        return 1
    value = requirements.get("max_targeted_expansion_attempts", 1)
    if isinstance(value, bool):
        return 1
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _structural_unanswerability_proof_ref(
    context: dict[str, Any],
    result: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
) -> str | None:
    requirements = context.get("sufficiency_requirements")
    candidates = []
    if isinstance(requirements, dict):
        candidates.append(requirements.get("structural_unanswerability_proof_ref"))
    candidates.append((result or {}).get("structural_unanswerability_proof_ref"))
    candidates.append((coverage or {}).get("structural_unanswerability_proof_ref"))
    for candidate in candidates:
        if _is_non_empty_string(candidate):
            return str(candidate)
    return None


def _freshness_status(
    context: dict[str, Any],
    coverage: dict[str, Any] | None,
    unsatisfied: set[str],
) -> str:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    minimum = targets.get("min_temporally_fresh_sources", 0)
    try:
        minimum_value = int(minimum)
    except (TypeError, ValueError):
        minimum_value = 0
    if minimum_value <= 0:
        return "not_required"
    if "freshness" in unsatisfied:
        return "stale_or_missing_fresh_source"
    if not isinstance(coverage, dict):
        return "unknown_not_certified"
    if coverage.get("fresh_source_count", 0) >= minimum_value:
        return "freshness_window_satisfied"
    return "stale_or_missing_fresh_source"


def certify_leaf_research_sufficiency(
    query_context: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    packet: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    expansion_attempts: list[dict[str, Any]] | None = None,
    fallback_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requirements = query_context.get("sufficiency_requirements")
    if not isinstance(requirements, dict):
        requirements = {}
    selected = _selected_from_result(result)
    expansion_attempts = expansion_attempts or []
    expansion_refs = [
        item["attempt_id"]
        for item in expansion_attempts
        if isinstance(item, dict) and _is_non_empty_string(item.get("attempt_id"))
    ]
    unsatisfied: set[str] = set()
    blocking: set[str] = set()
    breadth_coverage_ref = None
    breadth_certified = False
    if isinstance(coverage, dict):
        breadth_coverage_ref = coverage.get("coverage_id")
        breadth_certified = bool(coverage.get("breadth_certified") is True)
        for code in coverage.get("unsatisfied_breadth_dimensions", []):
            if _is_non_empty_string(code):
                unsatisfied.add(str(code))
        for code in coverage.get("expansion_requirement_codes", []):
            if _is_non_empty_string(code):
                unsatisfied.add(str(code))
    else:
        unsatisfied.add("missing_breadth_coverage")
        blocking.add("missing_breadth_coverage")
    for attempt in expansion_attempts:
        if not isinstance(attempt, dict):
            continue
        for code in attempt.get("unsatisfied_requirement_codes", []):
            if _is_non_empty_string(code):
                unsatisfied.add(str(code))

    temporal_invalid = packet.get("temporal_isolation_status") == "fail" or any(
        item.get("temporal_gate_status") != "pass" for item in selected
    )
    if temporal_invalid:
        blocking.add("temporally_invalid_evidence")

    freshness = _freshness_status(query_context, coverage, unsatisfied)
    if freshness == "stale_or_missing_fresh_source":
        blocking.add("stale_evidence_or_freshness_not_met")

    critical_or_source = _leaf_is_critical_or_source_of_truth(query_context)
    fallback_ref = None
    macro_fallback_only = False
    if isinstance(fallback_state, dict):
        fallback_ref = fallback_state.get("fallback_state_id")
        fallback_requested = bool(fallback_state.get("macro_fallback_requested") or fallback_state.get("macro_fallback_used"))
        macro_fallback_only = critical_or_source and fallback_requested and not breadth_certified
    if macro_fallback_only:
        blocking.add("macro_fallback_only_for_critical_or_source_of_truth")

    proof_ref = _structural_unanswerability_proof_ref(query_context, result, coverage)
    proof_allowed = (
        _is_non_empty_string(proof_ref)
        and bool(requirements.get("unanswerability_proof_required") is True)
        and len(expansion_refs) >= _max_expansion_attempts(query_context)
        and not temporal_invalid
        and not macro_fallback_only
    )
    if proof_ref and not proof_allowed:
        blocking.add("structural_unanswerability_proof_not_policy_valid")
    if proof_allowed:
        freshness = "not_applicable_structural_unanswerability"

    if not breadth_certified and not proof_allowed:
        blocking.add("breadth_not_certified")
    classification_allowed = not blocking or proof_allowed
    if proof_allowed:
        status = "structurally_unanswerable"
        classification_allowed = True
    elif temporal_invalid:
        status = "blocked_temporal_invalid"
    elif macro_fallback_only:
        status = "blocked_macro_fallback_only"
    elif freshness == "stale_or_missing_fresh_source":
        status = "blocked_stale"
    elif not isinstance(coverage, dict):
        status = "blocked_missing_breadth"
    elif not breadth_certified:
        status = "blocked_insufficient_research"
    else:
        status = "certified_high_certainty"
        classification_allowed = True

    if status == "certified_high_certainty" and not selected:
        status = "blocked_insufficient_research"
        classification_allowed = False
        blocking.add("no_admitted_evidence")
        unsatisfied.add("empty_retrieval")

    certificate_seed = {
        "leaf_id": query_context.get("leaf_id"),
        "requirement_ref": requirements.get("requirement_id"),
        "coverage_ref": breadth_coverage_ref,
        "expansion_refs": expansion_refs,
        "proof_ref": proof_ref,
        "status": status,
    }
    return {
        "artifact_type": "research_sufficiency_certificate",
        "schema_version": RESEARCH_SUFFICIENCY_CERTIFICATE_SCHEMA_VERSION,
        "certificate_id": _sha_id("research-sufficiency", certificate_seed),
        "leaf_id": query_context.get("leaf_id"),
        "query_context_ref": query_context.get("query_context_ref"),
        "requirement_ref": requirements.get("requirement_id"),
        "sufficiency_profile_id": requirements.get("sufficiency_profile_id", "high-certainty-default/v1"),
        "status": status,
        "classification_dispatch_allowed": bool(classification_allowed),
        "evidence_refs": [item["evidence_ref"] for item in selected if _is_non_empty_string(item.get("evidence_ref"))],
        "breadth_coverage_ref": breadth_coverage_ref,
        "breadth_certified": bool(breadth_certified),
        "expansion_attempt_refs": expansion_refs,
        "fallback_state_ref": fallback_ref,
        "structural_unanswerability_proof_ref": proof_ref,
        "temporal_validation_status": "invalid" if temporal_invalid else "pass",
        "freshness_status": freshness,
        "macro_fallback_sufficiency_status": (
            fallback_state.get("macro_fallback_sufficiency_status")
            if isinstance(fallback_state, dict)
            else "not_requested"
        ),
        "unsatisfied_requirement_codes": sorted(unsatisfied),
        "blocking_reason_codes": sorted(blocking),
        "authority_boundary": {
            "classification_dispatch_authority": True,
            "research_sufficiency_authority": True,
            "forecast_authority": False,
            "scae_authority": False,
        },
        "certifier_version": RESEARCH_SUFFICIENCY_CERTIFIER_VERSION,
    }


def _retrieval_replay_command(packet: dict[str, Any]) -> str:
    qdt_ref = packet.get("question_decomposition_artifact_id", "artifact:question-decomposition")
    return (
        "python3 researcher-swarm/scripts/bin/build_retrieval_packet.py "
        f"--question-decomposition {qdt_ref} --case-id {packet.get('case_id')} "
        f"--dispatch-id {packet.get('dispatch_id')}"
    )


def build_blocked_retrieval_stage_contract_records(
    packet: dict[str, Any],
    *,
    reason_codes: list[str],
    certificate_refs: list[str],
    replay_command: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    replay = replay_command or _retrieval_replay_command(packet)
    stage_attempt_id = _sha_id(
        "stage-attempt",
        {"case_id": packet.get("case_id"), "dispatch_id": packet.get("dispatch_id"), "stage": "retrieval"},
    )
    context = StageContext(
        case_id=str(packet.get("case_id")),
        case_key=str(packet.get("case_key") or packet.get("case_id")),
        dispatch_id=str(packet.get("dispatch_id")),
        stage="retrieval",
        stage_attempt_id=stage_attempt_id,
    )
    event_id = _sha_id(
        "stage-exec-event",
        {
            "case_id": packet.get("case_id"),
            "dispatch_id": packet.get("dispatch_id"),
            "reason_codes": sorted(set(reason_codes)),
            "certificate_refs": certificate_refs,
        },
    )
    event = build_stage_execution_event(
        execution_event_id=event_id,
        context=context,
        event_type="stage_blocked",
        event_status="warning",
        attempt_number=1,
        max_attempts=1,
        runner_ref="ads_retrieval_sufficiency_dispatch_gate",
        agent_or_component_ref="researcher-swarm",
        script_path="researcher-swarm/scripts/researcher_swarm/retrieval.py",
        command_sha256_value=_prefixed_sha256(replay),
        input_artifact_refs=[packet.get("question_decomposition_artifact_id")],
        output_artifact_refs=certificate_refs,
        validation_result_refs=[],
        failure_class="dependency_not_ready",
        safe_exception_class="ResearchSufficiencyNotMet",
        safe_exception_message="retrieval research sufficiency not met",
        no_log_reason="ret_008_structured_packet_diagnostics",
        redaction_status="not_needed",
        replay_command=replay,
        safe_metadata={
            "feature_id": "RET-008",
            "reason_codes": sorted(set(reason_codes)),
            "certificate_refs": certificate_refs,
        },
    )
    status = build_stage_status_snapshot(
        context=context,
        status="blocked",
        input_artifacts=[packet.get("question_decomposition_artifact_id")],
        output_artifacts=certificate_refs,
        dependency_feature_ids=["RET-008"],
        blocking_feature_ids=["RET-008"],
        reason_codes=sorted(set(reason_codes)),
        latest_execution_event_ids=[event_id],
        replay_command=replay,
        metadata={
            "feature_id": "RET-008",
            "classification_dispatch_status": "blocked_insufficient_research",
        },
    )
    return {
        "retrieval_stage_status_records": [status],
        "retrieval_stage_execution_events": [event],
    }


def finalize_retrieval_packet_for_dispatch(
    packet: dict[str, Any],
    *,
    replay_command: str | None = None,
) -> dict[str, Any]:
    packet_copy = copy.deepcopy(packet)
    if not packet_copy.get("retrieval_breadth_coverage_slices"):
        packet_copy["retrieval_breadth_coverage_slices"] = build_retrieval_breadth_coverage_slices(packet_copy)
    if not packet_copy.get("retrieval_expansion_attempts"):
        expansion_plan = build_retrieval_expansion_and_fallback_plan(packet_copy)
        packet_copy["retrieval_expansion_attempts"] = expansion_plan["retrieval_expansion_attempts"]
        if not packet_copy.get("retrieval_fallback_states"):
            packet_copy["retrieval_fallback_states"] = expansion_plan["retrieval_fallback_states"]
        packet_copy["retrieval_fallback_summary"] = expansion_plan["summary"]

    contexts = _contexts_by_leaf(packet_copy)
    results = _results_by_leaf(packet_copy)
    coverage = _coverage_by_leaf(packet_copy)
    expansion = _expansion_attempts_by_leaf(packet_copy)
    fallback = _fallback_by_leaf(packet_copy)
    certificates = [
        certify_leaf_research_sufficiency(
            context,
            results.get(leaf_id),
            packet=packet_copy,
            coverage=coverage.get(leaf_id),
            expansion_attempts=expansion.get(str(leaf_id), []),
            fallback_state=fallback.get(leaf_id),
        )
        for leaf_id, context in sorted(contexts.items())
    ]
    additional_attempts: list[dict[str, Any]] = []
    additional_fallback_states: list[dict[str, Any]] = []
    for cert in certificates:
        leaf_id = cert.get("leaf_id")
        context = contexts.get(leaf_id)
        if not isinstance(context, dict) or expansion.get(str(leaf_id)):
            continue
        unsatisfied = [
            code
            for code in cert.get("unsatisfied_requirement_codes", [])
            if _is_non_empty_string(code)
        ]
        if not unsatisfied or cert.get("classification_dispatch_allowed") is True:
            continue
        leaf_attempts = [
            build_retrieval_expansion_attempt(
                context,
                attempt_index=attempt_index,
                unsatisfied_requirement_codes=unsatisfied,
            )
            for attempt_index in range(1, _max_expansion_attempts(context) + 1)
        ]
        additional_attempts.extend(leaf_attempts)
        if str(leaf_id) not in fallback:
            additional_fallback_states.append(
                build_retrieval_fallback_state(
                    context,
                    [attempt["attempt_id"] for attempt in leaf_attempts],
                )
            )
    if additional_attempts:
        packet_copy.setdefault("retrieval_expansion_attempts", []).extend(additional_attempts)
        packet_copy.setdefault("retrieval_fallback_states", []).extend(additional_fallback_states)
        expansion = _expansion_attempts_by_leaf(packet_copy)
        fallback = _fallback_by_leaf(packet_copy)
        certificates = [
            certify_leaf_research_sufficiency(
                context,
                results.get(leaf_id),
                packet=packet_copy,
                coverage=coverage.get(leaf_id),
                expansion_attempts=expansion.get(str(leaf_id), []),
                fallback_state=fallback.get(leaf_id),
            )
            for leaf_id, context in sorted(contexts.items())
        ]
    cert_refs = [cert["certificate_id"] for cert in certificates]
    blocked_codes = sorted(
        {
            code
            for cert in certificates
            for code in cert.get("blocking_reason_codes", [])
            if _is_non_empty_string(code)
        }
    )
    all_allowed = bool(certificates) and all(cert.get("classification_dispatch_allowed") is True for cert in certificates)
    packet_copy["leaf_research_sufficiency_certificates"] = certificates
    packet_copy["research_sufficiency_summary"] = {
        "all_required_leaves_certified": all_allowed,
        "classification_dispatch_status": "allowed" if all_allowed else "blocked_insufficient_research",
        "leaf_certificate_refs": cert_refs,
        "feature_id": "RET-008",
        "certificate_status": "complete" if all_allowed else "blocked",
        "unsatisfied_requirement_codes": sorted(
            {
                code
                for cert in certificates
                for code in cert.get("unsatisfied_requirement_codes", [])
                if _is_non_empty_string(code)
            }
        ),
        "blocking_reason_codes": blocked_codes or ([] if all_allowed else ["research_sufficiency_not_met"]),
        "certifier_version": RESEARCH_SUFFICIENCY_CERTIFIER_VERSION,
    }
    packet_copy.setdefault("schema_feature_gates", {})["RET-008"] = "implemented"
    packet_copy.setdefault("schema_feature_gates", {})["RET-006"] = "implemented"
    packet_copy.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        "ret_008_research_sufficiency_dispatch_gate_evaluated"
    )
    if all_allowed:
        packet_copy["retrieval_stage_status_records"] = []
        packet_copy["retrieval_stage_execution_events"] = []
    else:
        stage_records = build_blocked_retrieval_stage_contract_records(
            packet_copy,
            reason_codes=blocked_codes or ["research_sufficiency_not_met"],
            certificate_refs=cert_refs,
            replay_command=replay_command,
        )
        packet_copy.update(stage_records)
    packet_copy["leaf_evidence_dockets"] = build_leaf_evidence_dockets(packet_copy)

    result = validate_retrieval_packet(packet_copy)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    return packet_copy


def _candidate_navigation_sort_key(candidate: dict[str, Any]) -> tuple[int, int, str]:
    mode = str(candidate.get("navigation_mode") or "")
    status = str(candidate.get("candidate_role") or "")
    priority = 0 if mode == "direct_url" or status == "direct_url" else 1
    rank = int(candidate.get("result_rank", 0) or 0)
    return (priority, rank, str(candidate.get("canonical_url") or candidate.get("url") or ""))


def _candidate_query_variant(context: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    requested = str(candidate.get("query_variant_id") or "")
    variants = []
    if isinstance(context.get("query_variants"), list):
        variants.extend(context["query_variants"])
    if isinstance(context.get("contradiction_query_variants"), list):
        variants.extend(context["contradiction_query_variants"])
    negative = context.get("negative_check_query_variants")
    if isinstance(negative, dict):
        for values in negative.values():
            if isinstance(values, list):
                variants.extend(item for item in values if isinstance(item, dict))
    for variant in variants:
        if isinstance(variant, dict) and variant.get("query_variant_id") == requested:
            return variant
    if variants:
        return variants[0]
    raise RetrievalPacketError(f"leaf {context.get('leaf_id')} has no query variants")


def _candidate_text(candidate: dict[str, Any]) -> str:
    return _bounded_excerpt(
        candidate.get("content")
        or candidate.get("extracted_text")
        or candidate.get("rendered_text")
        or candidate.get("markdown")
        or "",
        max_chars=4000,
    )


def _candidate_has_retrieved_source_text(candidate: dict[str, Any]) -> bool:
    return bool(_candidate_text(candidate))


def _resolved_claim_candidates_from_fetched_text(
    candidate: dict[str, Any],
    *,
    evidence_ref: str,
    leaf_id: str,
    chunk_ref: str,
    text: str,
) -> list[dict[str, Any]]:
    raw_candidates = candidate.get("validated_atomic_claim_candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = _deterministic_claim_candidates_from_fetched_text(text)
    claim_candidates: list[dict[str, Any]] = []
    for raw in raw_candidates[:8]:
        if not isinstance(raw, dict):
            continue
        _ensure_no_forbidden_keys(raw, "validated_atomic_claim_candidate")
        proposed_tuple = raw.get("proposed_tuple") if isinstance(raw.get("proposed_tuple"), dict) else raw
        supporting_text = _normalized_space(
            str(raw.get("supporting_text") or raw.get("supporting_excerpt") or raw.get("span_text") or "")
        )
        supporting_span_refs: list[str] = []
        validation_status = "rejected_no_span"
        if supporting_text:
            normalized_text = _normalized_space(text)
            if supporting_text in normalized_text:
                supporting_span_refs = [chunk_ref]
                if all(
                    _is_non_empty_string(proposed_tuple.get(field))
                    for field in ("subject", "predicate", "object_or_value")
                ):
                    validation_status = "accepted_for_normalization"
                else:
                    validation_status = "rejected_not_market_relevant"
        claim_candidates.append(
            build_atomic_claim_candidate(
                evidence_ref=evidence_ref,
                leaf_id=leaf_id,
                chunk_refs=[chunk_ref],
                extraction_method="fetched_text_validated_tuple",
                proposed_tuple=proposed_tuple,
                supporting_span_refs=supporting_span_refs,
                candidate_confidence=str(raw.get("candidate_confidence") or raw.get("confidence") or "unknown"),
                validation_status=validation_status,
            )
        )
    return claim_candidates


def _deterministic_claim_candidates_from_fetched_text(text: str) -> list[dict[str, Any]]:
    if not _looks_like_tesla_delivery_source_text(text):
        return []
    candidates: list[dict[str, Any]] = []
    for sentence in _tesla_delivery_candidate_sentences(text):
        event_time = _tesla_delivery_event_time(sentence)
        produced = _tesla_vehicle_count(sentence, "produc")
        delivered = _tesla_vehicle_count(sentence, "deliver")
        if produced:
            candidates.append(
                {
                    "subject": "Tesla vehicle production",
                    "predicate": "produced vehicles",
                    "object_or_value": produced,
                    "event_time": event_time,
                    "entity_or_jurisdiction": "Tesla",
                    "condition_scope": "unconditional",
                    "polarity": "affirmed",
                    "supporting_text": sentence,
                    "candidate_confidence": "high",
                }
            )
        if delivered:
            candidates.append(
                {
                    "subject": "Tesla vehicle deliveries",
                    "predicate": "delivered vehicles",
                    "object_or_value": delivered,
                    "event_time": event_time,
                    "entity_or_jurisdiction": "Tesla",
                    "condition_scope": "unconditional",
                    "polarity": "affirmed",
                    "supporting_text": sentence,
                    "candidate_confidence": "high",
                }
            )
    return candidates[:8]


def _looks_like_tesla_delivery_source_text(text: str) -> bool:
    lowered = text.lower()
    return (
        ("tesla" in lowered or "vehicle production & deliveries" in lowered)
        and "deliver" in lowered
        and "vehicle" in lowered
        and ("produc" in lowered or "deliveries" in lowered)
    )


def _tesla_delivery_candidate_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for match in re.finditer(r"[^.!?\n]*(?:produc\w+|deliver\w+)[^.!?\n]*vehicles?[^.!?\n]*[.!?]", text, re.IGNORECASE):
        sentence = _normalized_space(match.group(0))
        lowered = sentence.lower()
        if len(sentence) > 500:
            continue
        if "vehicle" not in lowered or "deliver" not in lowered:
            continue
        if "tesla" not in lowered and not re.search(r"\b(q[1-4]|quarter)\b", lowered):
            continue
        sentences.append(sentence)
    return sentences


def _tesla_delivery_event_time(sentence: str) -> str:
    quarter = re.search(r"\b(Q[1-4])\b(?:\s*(20\d{2}))?", sentence, re.IGNORECASE)
    if quarter:
        return _normalized_space(" ".join(part for part in quarter.groups() if part))
    ordinal = re.search(
        r"\b(first|second|third|fourth)\s+quarter\b(?:\s*(?:of)?\s*(20\d{2}))?",
        sentence,
        re.IGNORECASE,
    )
    if ordinal:
        return _normalized_space(" ".join(part for part in ordinal.groups() if part))
    year = re.search(r"\b(20\d{2})\b", sentence)
    return year.group(1) if year else "unspecified reporting period"


def _tesla_vehicle_count(sentence: str, stem: str) -> str | None:
    match = re.search(
        rf"\b{stem}\w*\s+(?:approximately|about|over|more than|nearly)?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(thousand|million)?\s+vehicles?\b",
        sentence,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1)
    scale = match.group(2)
    return _normalized_space(f"{value} {scale or ''} vehicles")


def _materialize_candidate_evidence(
    *,
    qdt: dict[str, Any],
    context: dict[str, Any],
    candidate: dict[str, Any],
    attempt: dict[str, Any],
    source_cutoff_timestamp: str,
    evidence_source: str,
    allow_candidate_source_metadata: bool = False,
    allow_candidate_source_family_metadata: bool = False,
    allow_candidate_claim_family_ids: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    leaf_id = str(context["leaf_id"])
    text = _candidate_text(candidate)
    content_artifact_ref = candidate.get("content_artifact_ref") or _sha_id(
        "browser-content",
        {
            "leaf_id": leaf_id,
            "attempt_id": attempt["attempt_id"],
            "canonical_url": attempt.get("canonical_url"),
            "text": text,
        },
    )
    source_class = str(candidate.get("source_class") or "unknown")
    if source_class not in ALLOWED_SOURCE_CLASSES or not allow_candidate_source_metadata:
        source_class = "unknown"
    if allow_candidate_source_family_metadata:
        source_family_id = str(candidate.get("source_family_id") or "source-family-unknown")
        source_family_method = str(
            candidate.get("source_family_resolution_method") or "deterministic_candidate_source_metadata"
        )
    elif canonicalize_source_url(attempt.get("canonical_url"), candidate.get("canonical_url"), candidate.get("final_url")):
        source_family_id = "source-family-" + _hash_suffix(
            {
                "canonical_url": canonicalize_source_url(
                    attempt.get("canonical_url"),
                    candidate.get("canonical_url"),
                    candidate.get("final_url"),
                )
            }
        )
        source_family_method = "canonical_url"
    else:
        source_family_id = "source-family-unknown"
        source_family_method = "unknown"
    claim_family_ids = _candidate_claim_family_ids(candidate) if allow_candidate_claim_family_ids else []
    evidence = build_retrieval_evidence_item(
        case_id=str(qdt.get("case_id") or context.get("case_id")),
        dispatch_id=str(qdt.get("dispatch_id") or context.get("dispatch_id")),
        leaf_id=leaf_id,
        parent_branch_id=str(context.get("parent_branch_id") or candidate.get("parent_branch_id") or "branch-runtime"),
        retrieval_transport=str(candidate.get("retrieval_transport") or "browser"),
        transport_attempt_ref=str(candidate.get("transport_attempt_ref") or attempt["attempt_id"]),
        requested_url=str(attempt.get("requested_url") or candidate.get("requested_url") or candidate.get("url") or ""),
        final_url=str(attempt.get("final_url") or candidate.get("final_url") or candidate.get("url") or ""),
        canonical_url=str(attempt.get("canonical_url") or candidate.get("canonical_url") or candidate.get("url") or ""),
        canonical_source_id=str(candidate.get("canonical_source_id") or f"source:{source_family_id}"),
        source_family_id=source_family_id,
        source_class=source_class,
        independence_status=str(candidate.get("independence_status") or "independent"),
        temporal_gate_status=str(candidate.get("temporal_gate_status") or "pass"),
        source_published_at=candidate.get("source_published_at") or candidate.get("published_at"),
        source_updated_at=candidate.get("source_updated_at"),
        source_observed_at=candidate.get("source_observed_at") or candidate.get("captured_at"),
        captured_at=candidate.get("captured_at") or _iso_before_cutoff(source_cutoff_timestamp),
        artifact_generated_at=candidate.get("artifact_generated_at") or _iso_before_cutoff(source_cutoff_timestamp),
        retrieval_capture_for_dispatch=True,
        content_sha256=candidate.get("content_sha256"),
        retrieval_score=float(candidate.get("retrieval_score", 1.0) or 1.0),
        admission_reason_codes=[
            str(candidate.get("admission_reason_code") or evidence_source),
            "deterministic_retrieval_admission",
        ],
        claim_family_resolution_refs=claim_family_ids,
    )
    evidence["deterministic_source_class_proof"] = bool(candidate.get("deterministic_source_class_proof", False))
    evidence["source_class_resolution_method"] = str(
        candidate.get("source_class_resolution_method") or "unknown"
    )
    evidence["source_family_resolution_method"] = str(
        source_family_method
    )
    evidence["claim_family_ids"] = claim_family_ids
    chunk = build_evidence_chunk(
        evidence_ref=evidence["evidence_ref"],
        content_artifact_ref=str(content_artifact_ref),
        chunk_index=0,
        char_start=0,
        char_end=len(text),
        text=text,
    )
    span = build_evidence_span(
        chunk_ref=chunk["chunk_ref"],
        char_start=0,
        char_end=min(len(text), max(1, len(text))),
        text=text,
    )
    evidence["chunk_refs"] = [chunk["chunk_ref"]]
    evidence["atomic_claim_candidates"] = _resolved_claim_candidates_from_fetched_text(
        candidate,
        evidence_ref=evidence["evidence_ref"],
        leaf_id=leaf_id,
        chunk_ref=chunk["chunk_ref"],
        text=text,
    )
    return evidence, chunk, span


def _candidate_claim_family_ids(candidate: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    raw_values = [
        candidate.get("claim_family_id"),
        candidate.get("claim_family_resolution_ref"),
    ]
    for field in ("claim_family_ids", "claim_family_resolution_refs"):
        value = candidate.get(field)
        if isinstance(value, list):
            raw_values.extend(value)
    for value in raw_values:
        if not _is_non_empty_string(value):
            continue
        claim_id = str(value)
        if "unknown" in claim_id or claim_id in ids:
            continue
        ids.append(claim_id)
    return ids


def _compact_supplemental_admission_result(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_type": "supplemental_evidence_admission_result",
        "schema_version": "supplemental-evidence-admission-result/v1",
        "admission_result_ref": record.get("normalization_id"),
        "normalized_supplemental_evidence_ref": record.get("normalization_id"),
        "supplemental_evidence_ref": record.get("supplemental_evidence_ref"),
        "case_id": record.get("case_id"),
        "dispatch_id": record.get("dispatch_id"),
        "leaf_id": record.get("leaf_id"),
        "normalization_status": record.get("normalization_status"),
        "admission_status": record.get("admission_status"),
        "source_access_status": record.get("source_access_status"),
        "canonical_url": record.get("canonical_url"),
        "source_class": record.get("source_class"),
        "source_family_id": record.get("source_family_id"),
        "claim_family_id": record.get("claim_family_id"),
        "temporal_gate_status": record.get("temporal_gate_status"),
        "independence_status": record.get("independence_status"),
        "counts_toward_breadth": bool(record.get("counts_toward_breadth")),
        "blockers": list(record.get("blockers") or []),
        "rejection_reason_codes": list(record.get("rejection_reason_codes") or []),
        "admission_authority": "deterministic_supplemental_evidence_normalizer",
    }


def _context_query_variant_by_id(context: dict[str, Any], query_variant_id: str) -> dict[str, Any]:
    return _candidate_query_variant(context, {"query_variant_id": query_variant_id})


def _search_candidate_url_ref_by_key(records: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    refs: dict[tuple[str, str], str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = (str(record.get("leaf_id") or ""), canonicalize_source_url(record.get("canonical_url"), record.get("url")))
        if key[0] and key[1]:
            refs[key] = str(record.get("search_candidate_url_id") or "")
    return refs


def _materialize_search_candidate_url_records(
    contexts_by_leaf: dict[str, dict[str, Any]],
    search_candidate_urls: list[dict[str, Any]] | None,
    *,
    searched_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen_by_variant: dict[str, set[str]] = {}
    for raw in search_candidate_urls or []:
        if not isinstance(raw, dict):
            raise RetrievalPacketError("search_candidate_urls must contain objects")
        leaf_id = str(raw.get("leaf_id") or "")
        context = contexts_by_leaf.get(leaf_id)
        if not context:
            raise RetrievalPacketError(f"search candidate leaf_id is not dispatchable: {leaf_id}")
        variant = _context_query_variant_by_id(context, str(raw.get("query_variant_id") or ""))
        role = str(raw.get("query_role") or variant.get("query_role") or "primary_leaf_retrieval")
        if role not in SEARCH_CANDIDATE_RANK_CAPS:
            role = "primary_leaf_retrieval"
        rank = int(raw.get("rank") or raw.get("result_rank") or 0)
        if rank < 1:
            raise RetrievalPacketError("search candidate rank must be positive")
        variant_key = str(variant.get("query_variant_id"))
        if rank > _search_rank_cap(role):
            diagnostics.append(
                {
                    "schema_version": "search-candidate-url-omission/v1",
                    "leaf_id": leaf_id,
                    "query_variant_id": variant_key,
                    "query_role": role,
                    "rank": rank,
                    "url": raw.get("url"),
                    "omission_reason_codes": ["search_rank_cap_exceeded"],
                }
            )
            continue
        canonical_url = canonicalize_source_url(raw.get("canonical_url"), raw.get("url"))
        seen_urls = seen_by_variant.setdefault(variant_key, set())
        if canonical_url in seen_urls:
            diagnostics.append(
                {
                    "schema_version": "search-candidate-url-omission/v1",
                    "leaf_id": leaf_id,
                    "query_variant_id": variant_key,
                    "query_role": role,
                    "rank": rank,
                    "url": raw.get("url"),
                    "canonical_url": canonical_url,
                    "omission_reason_codes": ["duplicate_search_candidate_url"],
                }
            )
            continue
        seen_urls.add(canonical_url)
        if raw.get("schema_version") == SEARCH_CANDIDATE_URL_SCHEMA_VERSION:
            records.append(copy.deepcopy(raw))
            continue
        records.append(
            build_search_candidate_url(
                context,
                variant,
                rank=rank,
                url=str(raw.get("url") or raw.get("canonical_url") or ""),
                title=str(raw.get("title") or ""),
                snippet=str(raw.get("snippet") or ""),
                provider_id=str(raw.get("provider_id") or OPENCLAW_BROWSER_PROVIDER_ID),
                searched_at=str(raw.get("searched_at") or searched_at),
                result_source=str(raw.get("result_source") or "configured_browser_search_provider"),
                query_role=role,
            )
        )
    return records, diagnostics


def _materialize_native_candidate_discoveries(
    contexts_by_leaf: dict[str, dict[str, Any]],
    native_research_candidates: list[dict[str, Any]] | None,
    *,
    discovered_at: str,
) -> list[dict[str, Any]]:
    discoveries: list[dict[str, Any]] = []
    for raw in native_research_candidates or []:
        if not isinstance(raw, dict):
            raise RetrievalPacketError("native_research_candidates must contain objects")
        leaf_id = str(raw.get("leaf_id") or raw.get("related_leaf_id") or "")
        context = contexts_by_leaf.get(leaf_id)
        if not context:
            raise RetrievalPacketError(f"native research candidate leaf_id is not dispatchable: {leaf_id}")
        variant = _context_query_variant_by_id(context, str(raw.get("query_variant_id") or ""))
        candidate_urls = raw.get("candidate_urls") if isinstance(raw.get("candidate_urls"), list) else [raw]
        discoveries.append(
            build_native_research_candidate_discovery(
                context,
                variant,
                candidate_urls,
                attempt_ref=raw.get("native_research_attempt_ref") or raw.get("attempt_ref"),
                resolved_model_id=str(raw.get("resolved_model_id") or "gpt-5.5-high"),
                discovered_at=str(raw.get("discovered_at") or discovered_at),
            )
        )
    return discoveries


def _source_resolution_rules(evidence_packet: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evidence_packet, dict):
        return {}
    rules = copy.deepcopy(evidence_packet.get("market_rules") or {})
    if not isinstance(rules, dict):
        rules = {}
    hints: list[Any] = []
    if isinstance(rules.get("official_source_hints"), list):
        hints.extend(rules["official_source_hints"])
    if isinstance(evidence_packet.get("official_source_hints"), list):
        hints.extend(evidence_packet["official_source_hints"])
    if hints:
        rules["official_source_hints"] = hints
    return rules


def build_live_retrieval_packet_from_candidates(
    qdt: dict[str, Any],
    *,
    evidence_packet: dict[str, Any] | None = None,
    amrg_context: dict[str, Any] | None = None,
    fetched_candidates: list[dict[str, Any]] | None = None,
    search_candidate_urls: list[dict[str, Any]] | None = None,
    native_research_candidates: list[dict[str, Any]] | None = None,
    supplemental_candidates: list[dict[str, Any]] | None = None,
    question_decomposition_artifact_id: str | None = None,
    policy_context_ref: str | None = None,
    forecast_timestamp: str | None = None,
    source_cutoff_timestamp: str | None = None,
    pre_dispatch_input_whitelist_refs: list[str] | None = None,
    live_retrieval_allowlist: list[str] | None = None,
    live_policy_overlay: bool = True,
    finalize_for_dispatch: bool = True,
    runtime_mode: str = "live_retrieval_runtime",
) -> dict[str, Any]:
    """Materialize live-shaped browser/supplemental candidates through deterministic retrieval validators."""

    _ensure_no_forbidden_keys(qdt, "qdt")
    forecast, cutoff = _timestamps_from_inputs(qdt, evidence_packet, forecast_timestamp, source_cutoff_timestamp)
    contexts = build_retrieval_query_contexts(
        qdt,
        evidence_packet=evidence_packet,
        amrg_context=amrg_context,
        forecast_timestamp=forecast,
        source_cutoff_timestamp=cutoff,
    )
    contexts_by_leaf = {str(context["leaf_id"]): context for context in contexts}
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    browser_attempts: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    attempt_refs_by_leaf: dict[str, list[str]] = {leaf_id: [] for leaf_id in contexts_by_leaf}
    search_candidate_records, search_candidate_omissions = _materialize_search_candidate_url_records(
        contexts_by_leaf,
        search_candidate_urls,
        searched_at=forecast,
    )
    search_ref_by_leaf_url = _search_candidate_url_ref_by_key(search_candidate_records)
    native_candidate_discoveries = _materialize_native_candidate_discoveries(
        contexts_by_leaf,
        native_research_candidates,
        discovered_at=forecast,
    )
    source_resolution_rules = _source_resolution_rules(evidence_packet)
    seen_canonical_urls_by_leaf: dict[str, set[str]] = {leaf_id: set() for leaf_id in contexts_by_leaf}

    for candidate in sorted(fetched_candidates or [], key=_candidate_navigation_sort_key):
        if not isinstance(candidate, dict):
            raise RetrievalPacketError("fetched_candidates must contain objects")
        leaf_id = str(candidate.get("leaf_id") or "")
        context = contexts_by_leaf.get(leaf_id)
        if not context:
            raise RetrievalPacketError(f"candidate leaf_id is not dispatchable: {leaf_id}")
        variant = _candidate_query_variant(context, candidate)
        requested_url = str(candidate.get("requested_url") or candidate.get("url") or candidate.get("canonical_url") or "")
        final_url = str(candidate.get("final_url") or requested_url)
        canonical_url = canonicalize_source_url(candidate.get("canonical_url"), final_url, requested_url)
        navigation_mode = str(candidate.get("navigation_mode") or ("direct_url" if candidate.get("direct_url") else "web_search"))
        extraction_status = str(candidate.get("extraction_status") or "accepted")
        search_candidate_ref = candidate.get("search_candidate_url_ref") or search_ref_by_leaf_url.get(
            (leaf_id, canonical_url)
        )
        if navigation_mode != "direct_url" and not search_candidate_ref and candidate.get("retrieval_transport") != "native_gpt_research":
            omitted.append(
                build_retrieval_candidate_record(
                    leaf_id=leaf_id,
                    query_context_ref=str(context["query_context_ref"]),
                    query_variant_id=str(variant["query_variant_id"]),
                    retrieval_transport=str(candidate.get("retrieval_transport") or "browser"),
                    transport_attempt_ref=str(candidate.get("transport_attempt_ref") or _sha_id("unfetched-search-candidate", candidate)),
                    candidate_status="rejected",
                    requested_url=requested_url,
                    canonical_url=canonical_url,
                    omission_reason_codes=["web_search_candidate_missing_search_candidate_url_ref"],
                    temporal_gate_status="unknown_not_counted",
                )
            )
            continue
        if canonical_url and canonical_url in seen_canonical_urls_by_leaf.setdefault(leaf_id, set()):
            omitted.append(
                build_retrieval_candidate_record(
                    leaf_id=leaf_id,
                    query_context_ref=str(context["query_context_ref"]),
                    query_variant_id=str(variant["query_variant_id"]),
                    retrieval_transport=str(candidate.get("retrieval_transport") or "browser"),
                    transport_attempt_ref=str(candidate.get("transport_attempt_ref") or _sha_id("duplicate-candidate", candidate)),
                    candidate_status="omitted",
                    requested_url=requested_url,
                    canonical_url=canonical_url,
                    omission_reason_codes=["duplicate_canonical_url"],
                    temporal_gate_status=str(candidate.get("temporal_gate_status") or "unknown_not_counted"),
                )
            )
            continue
        attempt = build_browser_retrieval_attempt(
            context,
            variant,
            navigation_mode=navigation_mode,
            requested_url=requested_url,
            final_url=final_url,
            canonical_url=canonical_url,
            captured_at=candidate.get("captured_at") or _iso_before_cutoff(cutoff),
            extraction_status=extraction_status,
            result_rank=int(candidate.get("result_rank", len(attempt_refs_by_leaf[leaf_id]) + 1) or 0),
            search_candidate_url_ref=search_candidate_ref,
        )
        attempt["provider_availability_status"] = "available"
        attempt["normalized_domain"] = _registrable_domain(canonical_url)
        attempt["direct_url_source_ref"] = candidate.get("direct_url_source_ref")
        browser_attempts.append(attempt)
        attempt_refs_by_leaf[leaf_id].append(attempt["attempt_id"])
        if canonical_url:
            seen_canonical_urls_by_leaf.setdefault(leaf_id, set()).add(canonical_url)
        if extraction_status == "accepted" and candidate.get("admission_status", "admitted") == "admitted":
            if not _candidate_has_retrieved_source_text(candidate):
                omitted.append(
                    build_retrieval_candidate_record(
                        leaf_id=leaf_id,
                        query_context_ref=str(context["query_context_ref"]),
                        query_variant_id=str(variant["query_variant_id"]),
                        retrieval_transport=str(candidate.get("retrieval_transport") or "browser"),
                        transport_attempt_ref=attempt["attempt_id"],
                        candidate_status="rejected",
                        requested_url=requested_url,
                        canonical_url=canonical_url,
                        omission_reason_codes=["retrieved_source_text_missing"],
                        temporal_gate_status=str(candidate.get("temporal_gate_status") or "unknown_not_counted"),
                    )
                )
                continue
            resolved_source_class, resolved_source_class_method, has_source_class_proof = (
                _deterministic_source_class_or_unknown(
                    {**candidate, "canonical_url": canonical_url, "final_url": final_url, "requested_url": requested_url},
                    market_rules=source_resolution_rules,
                )
            )
            evidence_candidate = {
                **candidate,
                "canonical_url": canonical_url,
                "source_class": resolved_source_class,
                "source_class_resolution_method": resolved_source_class_method,
                "deterministic_source_class_proof": has_source_class_proof,
            }
            evidence, chunk, span = _materialize_candidate_evidence(
                qdt=qdt,
                context=context,
                candidate=evidence_candidate,
                attempt=attempt,
                source_cutoff_timestamp=cutoff,
                evidence_source="live_retrieval_candidate_admitted",
                allow_candidate_source_metadata=has_source_class_proof,
                allow_candidate_claim_family_ids=False,
            )
            selected.append(evidence)
            chunks.append(chunk)
            spans.append(span)
        else:
            omitted.append(
                build_retrieval_candidate_record(
                    leaf_id=leaf_id,
                    query_context_ref=str(context["query_context_ref"]),
                    query_variant_id=str(variant["query_variant_id"]),
                    retrieval_transport=str(candidate.get("retrieval_transport") or "browser"),
                    transport_attempt_ref=attempt["attempt_id"],
                    candidate_status=str(candidate.get("candidate_status") or "rejected"),
                    requested_url=requested_url,
                    canonical_url=canonical_url,
                    omission_reason_codes=list(candidate.get("omission_reason_codes") or [f"extraction_{extraction_status}"]),
                    temporal_gate_status=str(candidate.get("temporal_gate_status") or "unknown_not_counted"),
                )
            )

    supplemental_records: list[dict[str, Any]] = []
    if supplemental_candidates:
        from .supplemental import normalize_supplemental_evidence, validate_normalized_supplemental_evidence

        seen_source_family_ids = {
            str(item.get("source_family_id"))
            for item in selected
            if _is_non_empty_string(item.get("source_family_id")) and item.get("source_family_id") != "source-family-unknown"
        }
        seen_claim_family_ids = {
            str(claim_id)
            for item in selected
            for claim_id in item.get("claim_family_ids", [])
            if _is_non_empty_string(claim_id)
        }
        dispatch_context = {
            "case_id": qdt.get("case_id"),
            "dispatch_id": qdt.get("dispatch_id"),
            "forecast_timestamp": forecast,
            "source_cutoff_timestamp": cutoff,
            "live_retrieval_allowlist": list(live_retrieval_allowlist or sorted(DEFAULT_LIVE_RETRIEVAL_TRANSPORT_ALLOWLIST)),
            "pre_dispatch_input_whitelist_refs": list(pre_dispatch_input_whitelist_refs or []),
        }
        for raw in supplemental_candidates:
            if not isinstance(raw, dict):
                raise RetrievalPacketError("supplemental_candidates must contain objects")
            leaf_id = str(raw.get("leaf_id") or "")
            context = contexts_by_leaf.get(leaf_id)
            if not context:
                raise RetrievalPacketError(f"supplemental candidate leaf_id is not dispatchable: {leaf_id}")
            enriched = {
                **raw,
                "case_id": raw.get("case_id") or qdt.get("case_id"),
                "dispatch_id": raw.get("dispatch_id") or qdt.get("dispatch_id"),
                "parent_branch_id": raw.get("parent_branch_id") or context.get("parent_branch_id"),
            }
            record = normalize_supplemental_evidence(
                enriched,
                dispatch_context,
                seen_source_family_ids=seen_source_family_ids,
                seen_claim_family_ids=seen_claim_family_ids,
            )
            validation = validate_normalized_supplemental_evidence(record)
            if not validation.valid:
                raise RetrievalPacketError("; ".join(validation.errors))
            supplemental_records.append(_compact_supplemental_admission_result(record))
            if record.get("normalization_status") == "normalized":
                if _is_non_empty_string(record.get("source_family_id")):
                    seen_source_family_ids.add(str(record["source_family_id"]))
                if _is_non_empty_string(record.get("claim_family_id")):
                    seen_claim_family_ids.add(str(record["claim_family_id"]))
                evidence, chunk, span = _materialize_candidate_evidence(
                    qdt=qdt,
                    context=context,
                    candidate={
                        **record,
                        "url": record.get("canonical_url"),
                        "source_published_at": record.get("source_published_at"),
                        "admission_reason_code": "supplemental_evidence_admitted_after_validation",
                        "source_class_resolution_method": record.get("source_class_resolution_method"),
                        "source_family_resolution_method": record.get("source_family_resolution_method"),
                    },
                    attempt={
                        "attempt_id": str(record["supplemental_evidence_ref"]),
                        "requested_url": record.get("requested_url"),
                        "final_url": record.get("final_url"),
                        "canonical_url": record.get("canonical_url"),
                    },
                source_cutoff_timestamp=cutoff,
                evidence_source="supplemental_evidence_admitted_after_validation",
                allow_candidate_source_metadata=True,
                allow_candidate_source_family_metadata=True,
                allow_candidate_claim_family_ids=True,
            )
                selected.append(evidence)
                chunks.append(chunk)
                spans.append(span)

    packet = build_retrieval_packet(
        qdt,
        evidence_packet=evidence_packet,
        amrg_context=amrg_context,
        question_decomposition_artifact_id=question_decomposition_artifact_id,
        policy_context_ref=policy_context_ref,
        selected_evidence=selected,
        omitted_candidates=omitted,
        forecast_timestamp=forecast,
        source_cutoff_timestamp=cutoff,
        pre_dispatch_input_whitelist_refs=pre_dispatch_input_whitelist_refs,
        live_retrieval_allowlist=live_retrieval_allowlist,
        live_policy_overlay=live_policy_overlay,
    )
    packet["browser_retrieval_attempts"] = browser_attempts
    packet["search_candidate_urls"] = search_candidate_records
    packet["search_candidate_url_omissions"] = search_candidate_omissions
    packet["native_research_candidate_discoveries"] = native_candidate_discoveries
    packet["browser_search_provider_diagnostics"] = [
        build_browser_search_provider_diagnostic(
            availability_status="available" if browser_attempts else "unavailable",
            checked_at=forecast,
            unavailable_reason=None if browser_attempts else "no_browser_candidates_supplied",
        )
    ]
    packet["evidence_chunks"] = chunks
    packet["evidence_spans"] = spans
    packet["supplemental_evidence_candidates"] = copy.deepcopy(supplemental_candidates or [])
    packet["supplemental_evidence_admission_results"] = supplemental_records
    packet["retrieval_runtime_summary"] = {
        "schema_version": "retrieval-runtime-summary/v1",
        "runtime_mode": runtime_mode,
        "direct_url_attempt_count": sum(1 for item in browser_attempts if item.get("navigation_mode") == "direct_url"),
        "web_search_attempt_count": sum(1 for item in browser_attempts if item.get("navigation_mode") == "web_search"),
        "search_candidate_url_count": len(search_candidate_records),
        "search_candidate_omission_count": len(search_candidate_omissions),
        "native_candidate_discovery_count": len(native_candidate_discoveries),
        "native_candidate_url_count": sum(len(item.get("candidate_urls", [])) for item in native_candidate_discoveries),
        "admitted_initial_evidence_count": len(selected) - sum(
            1 for item in supplemental_records if item.get("normalization_status") == "normalized"
        ),
        "admitted_supplemental_evidence_count": sum(
            1 for item in supplemental_records if item.get("normalization_status") == "normalized"
        ),
        "omitted_or_rejected_candidate_count": len(omitted),
        "web_fetch_is_url_fetch_not_search": True,
        "deterministic_admission_authority": "retrieval_source_claim_temporal_breadth_validators",
        "direct_url_priority_enforced": True,
        "duplicate_canonical_url_omissions": sum(
            1 for item in omitted if "duplicate_canonical_url" in item.get("omission_reason_codes", [])
        ),
    }
    packet.setdefault("schema_feature_gates", {})["RET-001"] = "implemented"
    packet.setdefault("schema_feature_gates", {})["RET-004"] = "implemented"
    packet.setdefault("schema_feature_gates", {})["RET-008"] = "pending"
    packet.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        "phase_3_live_retrieval_runtime_candidates_materialized"
    )
    for result in packet["leaf_retrieval_results"]:
        result["browser_retrieval_attempt_refs"] = attempt_refs_by_leaf.get(str(result.get("leaf_id")), [])
        result["evidence_chunk_refs"] = [
            chunk for item in result.get("selected_evidence", []) for chunk in item.get("chunk_refs", [])
        ]
        result["result_status"] = "live_retrieval_runtime_materialized"
    if not finalize_for_dispatch:
        validation = validate_retrieval_packet(packet)
        if not validation.valid:
            raise RetrievalPacketError("; ".join(validation.errors))
        return packet
    return finalize_retrieval_packet_for_dispatch(packet)


def attach_native_research_transport_diagnostics(
    packet: dict[str, Any],
    *,
    availability_status: str = "unavailable",
    unavailable_reason: str | None = "native_research_transport_not_exposed",
    resolved_model_id: str = "gpt-5.5-high",
) -> dict[str, Any]:
    packet_copy = copy.deepcopy(packet)
    diagnostic = build_native_research_transport_diagnostic(
        availability_status=availability_status,
        checked_at=packet_copy.get("forecast_timestamp"),
        unavailable_reason=unavailable_reason,
        resolved_model_id=resolved_model_id,
    )
    attempts: list[dict[str, Any]] = []
    if availability_status != "available":
        for context in packet_copy.get("leaf_query_contexts", []):
            if not isinstance(context, dict) or not context.get("query_variants"):
                continue
            variant = context["query_variants"][0]
            attempt = build_native_research_attempt(
                context,
                variant,
                resolved_model_id=resolved_model_id,
                attempt_status="failed",
                transport_availability_status=availability_status,
                failure_reason_codes=[unavailable_reason or "native_research_transport_unavailable"],
            )
            attempts.append(attempt)
    packet_copy["native_research_transport_diagnostics"] = [diagnostic]
    packet_copy["native_research_attempts"] = attempts
    attempt_refs_by_leaf: dict[str, list[str]] = {}
    for attempt in attempts:
        attempt_refs_by_leaf.setdefault(str(attempt.get("leaf_id")), []).append(attempt["attempt_id"])
    for result in packet_copy.get("leaf_retrieval_results", []):
        if isinstance(result, dict):
            result["native_research_attempt_refs"] = attempt_refs_by_leaf.get(str(result.get("leaf_id")), [])
    packet_copy.setdefault("schema_feature_gates", {})["RET-010"] = "implemented"
    packet_copy.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        "ret_010_native_transport_diagnostic_recorded"
    )
    result = validate_retrieval_packet(packet_copy)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    return packet_copy


def attach_source_metadata_classifier_unavailable(
    packet: dict[str, Any],
    *,
    model_lane_policy: dict[str, Any] | None = None,
    available_provider_model_keys: list[str] | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    packet_copy = copy.deepcopy(packet)
    lane = resolve_source_metadata_classifier_lane(
        model_lane_policy,
        available_provider_model_keys=available_provider_model_keys or [],
    )
    diagnostic = build_source_metadata_classifier_unavailable(
        lane,
        checked_at=packet_copy.get("forecast_timestamp"),
        unavailable_reason=unavailable_reason,
    )
    packet_copy["source_metadata_classifier_unavailable_diagnostics"] = [diagnostic]
    packet_copy.setdefault("source_metadata_classifier_slices", [])
    packet_copy.setdefault("schema_feature_gates", {})["RET-011"] = "implemented"
    packet_copy.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        "ret_011_classifier_unavailable_diagnostic_recorded"
    )
    result = validate_retrieval_packet(packet_copy)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    return packet_copy


def build_retrieval_packet(
    qdt: dict[str, Any],
    *,
    evidence_packet: dict[str, Any] | None = None,
    amrg_context: dict[str, Any] | None = None,
    question_decomposition_artifact_id: str | None = None,
    policy_context_ref: str | None = None,
    selected_evidence: list[dict[str, Any]] | None = None,
    omitted_candidates: list[dict[str, Any]] | None = None,
    forecast_timestamp: str | None = None,
    source_cutoff_timestamp: str | None = None,
    pre_dispatch_input_whitelist_refs: list[str] | None = None,
    live_retrieval_allowlist: list[str] | None = None,
    live_policy_overlay: bool = False,
) -> dict[str, Any]:
    _ensure_no_forbidden_keys(qdt, "qdt")
    forecast, cutoff = _timestamps_from_inputs(qdt, evidence_packet, forecast_timestamp, source_cutoff_timestamp)
    contexts = build_retrieval_query_contexts(
        qdt,
        evidence_packet=evidence_packet,
        amrg_context=amrg_context,
        forecast_timestamp=forecast,
        source_cutoff_timestamp=cutoff,
    )
    breadth_profiles = []
    leaves_by_id = {leaf.get("leaf_id"): leaf for leaf in qdt.get("required_leaf_questions", [])}
    for context in contexts:
        profile = build_retrieval_breadth_profile_placeholder(
            leaves_by_id[context["leaf_id"]],
            live_policy_overlay=live_policy_overlay,
        )
        profile["contradiction_search"]["query_variants"] = [
            item["query_text"] for item in context["contradiction_query_variants"]
        ]
        profile["negative_checks"]["query_variants_by_check"] = context["negative_check_query_variants"]
        breadth_profiles.append(profile)

    dispatch_context = {
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "forecast_timestamp": forecast,
        "source_cutoff_timestamp": cutoff,
        "pre_dispatch_input_whitelist_refs": list(pre_dispatch_input_whitelist_refs or []),
        "live_retrieval_allowlist": list(live_retrieval_allowlist or sorted(DEFAULT_LIVE_RETRIEVAL_TRANSPORT_ALLOWLIST)),
    }
    source_resolution_rules = _source_resolution_rules(evidence_packet)
    selected = copy.deepcopy(selected_evidence or [])
    provenance_slices = []
    source_metadata_resolutions = []
    source_metadata_classifier_slices = []
    atomic_claim_candidates = []
    claim_family_resolutions = []
    seen_source_family_ids_by_leaf: dict[str, set[str]] = {}
    seen_claim_family_ids_by_leaf: dict[str, set[str]] = {}
    for item in selected:
        leaf_id = str(item.get("leaf_id") or "")
        seen_source_family_ids = seen_source_family_ids_by_leaf.setdefault(leaf_id, set())
        seen_claim_family_ids = seen_claim_family_ids_by_leaf.setdefault(leaf_id, set())
        classifier_slice = item.get("source_metadata_classifier_slice")
        if isinstance(classifier_slice, dict):
            source_metadata_classifier_slices.append(classifier_slice)
        item_claim_candidates = [
            candidate
            for candidate in item.get("atomic_claim_candidates", [])
            if isinstance(candidate, dict)
        ] if isinstance(item.get("atomic_claim_candidates"), list) else []
        item_claim_family_resolutions = resolve_claim_families(item_claim_candidates) if item_claim_candidates else []
        provenance = normalize_retrieval_provenance(
            item,
            dispatch_context=dispatch_context,
            classifier_slice=classifier_slice if isinstance(classifier_slice, dict) else None,
            claim_candidates=item_claim_candidates,
            claim_family_resolutions=item_claim_family_resolutions,
            market_rules=source_resolution_rules,
            seen_source_family_ids=seen_source_family_ids,
            seen_claim_family_ids=seen_claim_family_ids,
        )
        atomic_claim_candidates.extend(item_claim_candidates)
        claim_family_resolutions.extend(item_claim_family_resolutions)
        if provenance.get("source_family_id") != "source-family-unknown":
            seen_source_family_ids.add(str(provenance["source_family_id"]))
        for claim_family_id in provenance.get("claim_family_ids", []):
            if _is_non_empty_string(claim_family_id):
                seen_claim_family_ids.add(str(claim_family_id))
        provenance_slices.append(provenance)
        source_metadata_resolutions.append(provenance["source_metadata_resolution"])
        item["source_metadata_resolution_ref"] = provenance["source_metadata_resolution_ref"]
        item["canonical_source_id"] = provenance["canonical_source_id"]
        item["source_family_id"] = provenance["source_family_id"]
        item["source_class"] = provenance["source_class"]
        item["independence_status"] = provenance["independence_status"]
        item["temporal_gate_status"] = provenance["temporal_gate_status"]
        item["content_sha256"] = provenance["content_sha256"]
        item["claim_family_ids"] = list(provenance["claim_family_ids"])
        item["counts_toward_breadth"] = bool(provenance["counts_toward_breadth"])
        item["metadata_unknown_reason_codes"] = list(provenance["unknown_reason_codes"])
    omitted = copy.deepcopy(omitted_candidates or [])
    packet = {
        "artifact_type": RETRIEVAL_PACKET_ARTIFACT_TYPE,
        "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
        "case_id": qdt.get("case_id"),
        "case_key": qdt.get("case_key"),
        "dispatch_id": qdt.get("dispatch_id"),
        "question_decomposition_artifact_id": question_decomposition_artifact_id or qdt.get("artifact_id") or "artifact:question-decomposition-unregistered",
        "forecast_timestamp": forecast,
        "source_cutoff_timestamp": cutoff,
        "pre_dispatch_input_whitelist_refs": list(pre_dispatch_input_whitelist_refs or []),
        "live_retrieval_allowlist": list(live_retrieval_allowlist or sorted(DEFAULT_LIVE_RETRIEVAL_TRANSPORT_ALLOWLIST)),
        "temporal_isolation_status": "pass",
        "temporal_isolation_schema_gate": {
            "feature_id": "RET-002",
            "status": "strict_validator_implemented",
            "validator_version": RETRIEVAL_TEMPORAL_VALIDATOR_VERSION,
        },
        "leaf_query_contexts": contexts,
        "leaf_retrieval_results": [
            build_leaf_retrieval_result(
                context,
                selected_evidence=selected,
                omitted_candidates=omitted,
            )
            for context in contexts
        ],
        "retrieval_quality_summary": {
            "feature_id": "RET-003",
            "quality_scoring_status": "not_run_schema_only",
        },
        "retrieval_breadth_profiles": breadth_profiles,
        "retrieval_breadth_coverage_slices": [],
        "retrieval_metadata_fill_diagnostics": [],
        "research_sufficiency_summary": {
            "all_required_leaves_certified": False,
            "classification_dispatch_status": "blocked_until_certified",
            "leaf_certificate_refs": [],
            "feature_id": "RET-008",
            "certificate_status": "not_run_schema_only",
        },
        "omitted_candidates": omitted,
        "contradiction_search_attempts": [],
        "negative_check_attempts": [],
        "retrieval_expansion_attempts": [],
        "retrieval_fallback_states": [],
        "leaf_research_sufficiency_certificates": [],
        "retrieval_stage_status_records": [],
        "retrieval_stage_execution_events": [],
        "protected_primary_access_failures": [],
        "missingness_candidates": [],
        "browser_search_provider_diagnostics": [
            build_browser_search_provider_diagnostic(checked_at=forecast)
        ],
        "search_candidate_urls": [],
        "search_candidate_url_omissions": [],
        "native_research_attempts": [],
        "native_research_candidate_discoveries": [],
        "native_research_transport_diagnostics": [],
        "browser_retrieval_attempts": [],
        "source_metadata_classifier_slices": source_metadata_classifier_slices,
        "source_metadata_classifier_unavailable_diagnostics": [],
        "source_metadata_resolutions": source_metadata_resolutions,
        "atomic_claim_candidates": atomic_claim_candidates,
        "claim_family_resolutions": claim_family_resolutions,
        "retrieval_evidence_provenance_slices": provenance_slices,
        "evidence_chunks": [],
        "evidence_spans": [],
        "policy_context_ref": policy_context_ref or "artifact:effective-profile-context-unregistered",
        "schema_feature_gates": {
            "RET-001": "implemented",
            "RET-002": "implemented",
            "RET-003": "pending",
            "RET-004": "implemented",
            "RET-005": "pending",
            "RET-006": "pending",
            "RET-007": "pending",
            "RET-008": "pending",
            "RET-009": "implemented",
            "RET-010": "pending",
            "RET-011": "implemented" if source_metadata_classifier_slices else "pending",
        },
        "validation_summary": {
            "status": "schema_constructed",
            "validator_version": RETRIEVAL_VALIDATOR_VERSION,
            "reason_codes": [
                "ret_001_schema",
                "ret_002_temporal_validator",
                "ret_004_provenance_normalizer",
                "ret_009_breadth_coverage_evaluated",
            ],
        },
    }
    contradiction_attempts, negative_attempts = build_required_contradiction_and_negative_attempts(packet)
    packet["contradiction_search_attempts"] = contradiction_attempts
    packet["negative_check_attempts"] = negative_attempts
    packet["retrieval_metadata_fill_diagnostics"] = build_retrieval_metadata_fill_diagnostics(packet)
    packet["retrieval_breadth_coverage_slices"] = build_retrieval_breadth_coverage_slices(packet)
    result = validate_retrieval_packet(packet)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    return packet


def validate_query_context(context: Any, path: str, errors: list[str]) -> None:
    if not isinstance(context, dict):
        errors.append(f"{path} must be an object")
        return
    required = (
        "artifact_type",
        "schema_version",
        "query_context_ref",
        "case_id",
        "dispatch_id",
        "leaf_id",
        "parent_branch_id",
        "leaf_question",
        "purpose",
        "condition_scope",
        "sufficiency_requirements",
        "breadth_profile_ref",
        "breadth_targets",
        "query_variants",
        "contradiction_query_variants",
        "negative_check_query_variants",
    )
    for field in required:
        if field not in context:
            errors.append(f"{path} missing {field}")
    if context.get("artifact_type") != "leaf_retrieval_query_context":
        errors.append(f"{path}.artifact_type must be leaf_retrieval_query_context")
    if context.get("schema_version") != LEAF_QUERY_CONTEXT_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {LEAF_QUERY_CONTEXT_SCHEMA_VERSION}")
    for field in ("query_context_ref", "case_id", "dispatch_id", "leaf_id", "parent_branch_id", "leaf_question"):
        if not _is_non_empty_string(context.get(field)):
            errors.append(f"{path}.{field} is required")
    if context.get("condition_scope") not in ALLOWED_CONDITION_SCOPES:
        errors.append(f"{path}.condition_scope is invalid")
    if not isinstance(context.get("sufficiency_requirements"), dict):
        errors.append(f"{path}.sufficiency_requirements must be an object")
    if not isinstance(context.get("breadth_targets"), dict):
        errors.append(f"{path}.breadth_targets must be an object")
    variants = context.get("query_variants")
    if not isinstance(variants, list) or not variants:
        errors.append(f"{path}.query_variants must be a non-empty list")
    else:
        for idx, variant in enumerate(variants):
            if not isinstance(variant, dict):
                errors.append(f"{path}.query_variants[{idx}] must be an object")
                continue
            for field in ("query_variant_id", "query_text", "query_text_sha256", "query_role"):
                if not _is_non_empty_string(variant.get(field)):
                    errors.append(f"{path}.query_variants[{idx}].{field} is required")
    if not isinstance(context.get("contradiction_query_variants"), list):
        errors.append(f"{path}.contradiction_query_variants must be a list")
    if not isinstance(context.get("negative_check_query_variants"), dict):
        errors.append(f"{path}.negative_check_query_variants must be an object")


def validate_retrieval_evidence_item(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    required = (
        "artifact_type",
        "schema_version",
        "evidence_ref",
        "case_id",
        "dispatch_id",
        "leaf_id",
        "parent_branch_id",
        "retrieval_transport",
        "transport_attempt_ref",
        "canonical_source_id",
        "source_metadata_resolution_ref",
        "claim_family_resolution_refs",
        "source_family_id",
        "source_class",
        "independence_status",
        "temporal_gate_status",
        "content_sha256",
        "chunk_refs",
        "retrieval_score",
        "admission_status",
        "admission_reason_codes",
    )
    for field in required:
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "retrieval_evidence":
        errors.append(f"{path}.artifact_type must be retrieval_evidence")
    if item.get("schema_version") != RETRIEVAL_EVIDENCE_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RETRIEVAL_EVIDENCE_SCHEMA_VERSION}")
    if item.get("retrieval_transport") not in ALLOWED_RETRIEVAL_TRANSPORTS:
        errors.append(f"{path}.retrieval_transport is invalid")
    if item.get("source_class") not in ALLOWED_SOURCE_CLASSES:
        errors.append(f"{path}.source_class is invalid")
    if item.get("independence_status") not in ALLOWED_INDEPENDENCE_STATUSES:
        errors.append(f"{path}.independence_status is invalid")
    if item.get("temporal_gate_status") not in ALLOWED_TEMPORAL_GATE_STATUSES:
        errors.append(f"{path}.temporal_gate_status is invalid")
    if item.get("admission_status") not in ALLOWED_ADMISSION_STATUSES:
        errors.append(f"{path}.admission_status is invalid")
    if not isinstance(item.get("retrieval_score"), (int, float)) or isinstance(item.get("retrieval_score"), bool):
        errors.append(f"{path}.retrieval_score must be numeric")
    if not isinstance(item.get("chunk_refs"), list):
        errors.append(f"{path}.chunk_refs must be a list")
    if not _reason_codes_are_compact(item.get("admission_reason_codes")):
        errors.append(f"{path}.admission_reason_codes must be compact reason codes")


def validate_candidate_record(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "candidate_id",
        "leaf_id",
        "query_context_ref",
        "query_variant_id",
        "retrieval_transport",
        "transport_attempt_ref",
        "candidate_status",
        "omission_reason_codes",
        "temporal_gate_status",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "retrieval_candidate_record":
        errors.append(f"{path}.artifact_type must be retrieval_candidate_record")
    if item.get("schema_version") != RETRIEVAL_CANDIDATE_RECORD_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RETRIEVAL_CANDIDATE_RECORD_SCHEMA_VERSION}")
    if item.get("candidate_status") not in ALLOWED_CANDIDATE_STATUSES:
        errors.append(f"{path}.candidate_status is invalid")
    if item.get("retrieval_transport") not in ALLOWED_RETRIEVAL_TRANSPORTS:
        errors.append(f"{path}.retrieval_transport is invalid")
    if item.get("temporal_gate_status") not in ALLOWED_TEMPORAL_GATE_STATUSES:
        errors.append(f"{path}.temporal_gate_status is invalid")
    if not _reason_codes_are_compact(item.get("omission_reason_codes")):
        errors.append(f"{path}.omission_reason_codes must be compact reason codes")


def validate_search_candidate_url(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "search_candidate_url_id",
        "leaf_id",
        "query_context_ref",
        "query_variant_id",
        "query_role",
        "rank",
        "url",
        "canonical_url",
        "provider_id",
        "result_source",
        "rank_cap",
        "web_fetch_used_for_search",
        "fetch_required_before_admission",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "search_candidate_url":
        errors.append(f"{path}.artifact_type must be search_candidate_url")
    if item.get("schema_version") != SEARCH_CANDIDATE_URL_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {SEARCH_CANDIDATE_URL_SCHEMA_VERSION}")
    role = str(item.get("query_role") or "")
    if role not in SEARCH_CANDIDATE_RANK_CAPS:
        errors.append(f"{path}.query_role is invalid")
    else:
        rank = int(item.get("rank") or 0)
        if rank < 1 or rank > _search_rank_cap(role):
            errors.append(f"{path}.rank exceeds {role} cap")
        if item.get("rank_cap") != _search_rank_cap(role):
            errors.append(f"{path}.rank_cap is invalid")
    if item.get("web_fetch_used_for_search") is not False:
        errors.append(f"{path}.web_fetch_used_for_search must be false")
    if item.get("fetch_required_before_admission") is not True:
        errors.append(f"{path}.fetch_required_before_admission must be true")
    if not _is_non_empty_string(item.get("canonical_url")):
        errors.append(f"{path}.canonical_url is required")


def validate_native_research_candidate_discovery(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "discovery_id",
        "leaf_id",
        "query_context_ref",
        "query_variant_id",
        "model_lane_id",
        "resolved_model_id",
        "candidate_cap",
        "candidate_urls",
        "candidate_url_count",
        "fetch_required_before_admission",
        "authority_boundary",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "native_research_candidate_discovery":
        errors.append(f"{path}.artifact_type must be native_research_candidate_discovery")
    if item.get("schema_version") != NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION}")
    if item.get("model_lane_id") != "native_research_candidate_discovery":
        errors.append(f"{path}.model_lane_id is invalid")
    candidates = item.get("candidate_urls")
    if not isinstance(candidates, list):
        errors.append(f"{path}.candidate_urls must be a list")
        candidates = []
    if int(item.get("candidate_url_count") or 0) != len(candidates):
        errors.append(f"{path}.candidate_url_count must match candidate_urls")
    cap = int(item.get("candidate_cap") or 0)
    if cap <= 0 or len(candidates) > cap:
        errors.append(f"{path}.candidate_urls exceeds candidate_cap")
    for idx, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"{path}.candidate_urls[{idx}] must be an object")
            continue
        candidate_errors: list[str] = []
        _reject_forbidden_native_research_outputs(candidate, candidate_errors, f"{path}.candidate_urls[{idx}]")
        if candidate_errors:
            errors.extend(candidate_errors)
        for field in ("url", "source_label", "why_it_may_matter", "related_leaf_id", "candidate_claim_text", "uncertainty_notes"):
            if field not in candidate:
                errors.append(f"{path}.candidate_urls[{idx}] missing {field}")
        if not _is_non_empty_string(candidate.get("url")):
            errors.append(f"{path}.candidate_urls[{idx}].url is required")
    boundary = item.get("authority_boundary")
    if not isinstance(boundary, dict):
        errors.append(f"{path}.authority_boundary must be an object")
    else:
        for field in (
            "source_family_final_authority",
            "claim_family_final_authority",
            "temporal_safety_final_authority",
            "research_sufficiency_authority",
            "forecast_authority",
        ):
            if boundary.get(field) is not False:
                errors.append(f"{path}.authority_boundary.{field} must be false")
    if item.get("fetch_required_before_admission") is not True:
        errors.append(f"{path}.fetch_required_before_admission must be true")


def validate_source_metadata_classifier_slice(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "classifier_slice_id",
        "candidate_id",
        "model_lane_id",
        "resolved_model_id",
        "provider_model_key",
        "prompt_template_id",
        "prompt_template_sha256",
        "input_candidate_sha256",
        "classifier_output_schema_version",
        "proposed_source_class",
        "source_class_confidence",
        "proposed_source_family_hint",
        "source_family_confidence",
        "syndication_hint",
        "atomic_claim_candidates",
        "visible_date_candidates",
        "reason_codes",
        "authority_boundary",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "source_metadata_classifier_slice":
        errors.append(f"{path}.artifact_type must be source_metadata_classifier_slice")
    if item.get("schema_version") != SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION}")
    if item.get("model_lane_id") != SOURCE_METADATA_CLASSIFIER_LANE_ID:
        errors.append(f"{path}.model_lane_id must be {SOURCE_METADATA_CLASSIFIER_LANE_ID}")
    if item.get("provider_model_key") not in ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS:
        errors.append(f"{path}.provider_model_key is not an allowed OAuth-routed classifier model")
    if item.get("prompt_template_id") != SOURCE_METADATA_CLASSIFIER_PROMPT_TEMPLATE_ID:
        errors.append(f"{path}.prompt_template_id is invalid")
    if item.get("classifier_output_schema_version") != SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION:
        errors.append(f"{path}.classifier_output_schema_version is invalid")
    if item.get("proposed_source_class") not in ALLOWED_SOURCE_CLASSES:
        errors.append(f"{path}.proposed_source_class is invalid")
    if item.get("source_class_confidence") not in ALLOWED_CLASSIFIER_CONFIDENCES:
        errors.append(f"{path}.source_class_confidence is invalid")
    if item.get("source_family_confidence") not in ALLOWED_CLASSIFIER_CONFIDENCES:
        errors.append(f"{path}.source_family_confidence is invalid")
    if item.get("syndication_hint") not in ALLOWED_SYNDICATION_HINTS:
        errors.append(f"{path}.syndication_hint is invalid")
    if not isinstance(item.get("atomic_claim_candidates"), list):
        errors.append(f"{path}.atomic_claim_candidates must be a list")
    if not isinstance(item.get("visible_date_candidates"), list):
        errors.append(f"{path}.visible_date_candidates must be a list")
    if not _reason_codes_are_compact(item.get("reason_codes")):
        errors.append(f"{path}.reason_codes must be compact reason codes")
    boundary = item.get("authority_boundary")
    if not isinstance(boundary, dict):
        errors.append(f"{path}.authority_boundary must be an object")
    else:
        for field in (
            "source_class_final_authority",
            "source_family_final_authority",
            "claim_family_final_authority",
            "protected_primary_final_authority",
            "temporal_safety_final_authority",
            "research_sufficiency_authority",
        ):
            if boundary.get(field) is not False:
                errors.append(f"{path}.authority_boundary.{field} must be false")


def validate_source_metadata_classifier_unavailable(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "diagnostic_id",
        "model_lane_id",
        "provider_model_key",
        "availability_status",
        "unavailable_reason",
        "non_blocking_when_alternative_transport_satisfies_requirements",
        "classifier_assist_authority",
        "reason_codes",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "source_metadata_classifier_unavailable":
        errors.append(f"{path}.artifact_type must be source_metadata_classifier_unavailable")
    if item.get("schema_version") != SOURCE_METADATA_CLASSIFIER_UNAVAILABLE_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {SOURCE_METADATA_CLASSIFIER_UNAVAILABLE_SCHEMA_VERSION}")
    if item.get("model_lane_id") != SOURCE_METADATA_CLASSIFIER_LANE_ID:
        errors.append(f"{path}.model_lane_id must be {SOURCE_METADATA_CLASSIFIER_LANE_ID}")
    if item.get("provider_model_key") not in ALLOWED_SOURCE_METADATA_CLASSIFIER_PROVIDER_MODEL_KEYS:
        errors.append(f"{path}.provider_model_key is invalid")
    if item.get("availability_status") != "unavailable":
        errors.append(f"{path}.availability_status must be unavailable")
    if item.get("non_blocking_when_alternative_transport_satisfies_requirements") is not True:
        errors.append(f"{path}.non_blocking_when_alternative_transport_satisfies_requirements must be true")
    if not _reason_codes_are_compact(item.get("reason_codes")):
        errors.append(f"{path}.reason_codes must be compact reason codes")
    authority = item.get("classifier_assist_authority")
    if not isinstance(authority, dict):
        errors.append(f"{path}.classifier_assist_authority must be an object")
    else:
        for field in (
            "source_metadata_final_authority",
            "protected_primary_final_authority",
            "temporal_safety_final_authority",
            "research_sufficiency_authority",
        ):
            if authority.get(field) is not False:
                errors.append(f"{path}.classifier_assist_authority.{field} must be false")


def validate_source_metadata_resolution(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "resolution_id",
        "evidence_ref",
        "transport_attempt_ref",
        "canonical_url",
        "canonical_source_id",
        "source_class",
        "source_family_id",
        "source_family_status",
        "temporal_safety_status",
        "classifier_acceptance_status",
        "counts_toward_breadth",
        "unknown_reason_codes",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "source_metadata_resolution":
        errors.append(f"{path}.artifact_type must be source_metadata_resolution")
    if item.get("schema_version") != SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION}")
    if item.get("source_class") not in ALLOWED_SOURCE_CLASSES:
        errors.append(f"{path}.source_class is invalid")
    if item.get("source_family_status") not in ALLOWED_SOURCE_FAMILY_STATUSES:
        errors.append(f"{path}.source_family_status is invalid")
    if item.get("temporal_safety_status") not in ALLOWED_TEMPORAL_GATE_STATUSES:
        errors.append(f"{path}.temporal_safety_status is invalid")
    if item.get("classifier_acceptance_status") not in ALLOWED_CLASSIFIER_ACCEPTANCE_STATUSES:
        errors.append(f"{path}.classifier_acceptance_status is invalid")
    if not isinstance(item.get("counts_toward_breadth"), bool):
        errors.append(f"{path}.counts_toward_breadth must be boolean")
    if not _reason_codes_are_compact(item.get("unknown_reason_codes")):
        errors.append(f"{path}.unknown_reason_codes must be compact reason codes")


def validate_evidence_provenance_slice(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "provenance_id",
        "retrieval_transport",
        "source_metadata_resolution_ref",
        "requested_url",
        "final_url",
        "canonical_url",
        "canonical_source_id",
        "source_class",
        "source_family_id",
        "independence_status",
        "content_sha256",
        "temporal_gate_status",
        "temporal_validation",
        "counts_toward_breadth",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "retrieval_evidence_provenance":
        errors.append(f"{path}.artifact_type must be retrieval_evidence_provenance")
    if item.get("schema_version") != RETRIEVAL_EVIDENCE_PROVENANCE_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RETRIEVAL_EVIDENCE_PROVENANCE_SCHEMA_VERSION}")
    if item.get("retrieval_transport") not in ALLOWED_RETRIEVAL_TRANSPORTS:
        errors.append(f"{path}.retrieval_transport is invalid")
    if item.get("source_class") not in ALLOWED_SOURCE_CLASSES:
        errors.append(f"{path}.source_class is invalid")
    if item.get("independence_status") not in ALLOWED_INDEPENDENCE_STATUSES:
        errors.append(f"{path}.independence_status is invalid")
    if item.get("temporal_gate_status") not in ALLOWED_TEMPORAL_GATE_STATUSES:
        errors.append(f"{path}.temporal_gate_status is invalid")
    if not isinstance(item.get("counts_toward_breadth"), bool):
        errors.append(f"{path}.counts_toward_breadth must be boolean")
    temporal = item.get("temporal_validation")
    if isinstance(temporal, dict):
        if temporal.get("schema_version") != RETRIEVAL_TEMPORAL_ELIGIBILITY_SCHEMA_VERSION:
            errors.append(f"{path}.temporal_validation.schema_version is invalid")
        if temporal.get("temporal_gate_status") != item.get("temporal_gate_status"):
            errors.append(f"{path}.temporal_validation.temporal_gate_status must match temporal_gate_status")
    else:
        errors.append(f"{path}.temporal_validation must be an object")


def validate_retrieval_metadata_fill_diagnostic(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "diagnostic_id",
        "leaf_id",
        "retrieval_transport",
        "raw_candidate_count",
        "admitted_ref_count",
        "field_fill_counts",
        "unknown_counts",
        "fill_rates",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "retrieval_metadata_fill_diagnostic":
        errors.append(f"{path}.artifact_type must be retrieval_metadata_fill_diagnostic")
    if item.get("schema_version") != RETRIEVAL_METADATA_FILL_DIAGNOSTIC_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RETRIEVAL_METADATA_FILL_DIAGNOSTIC_SCHEMA_VERSION}")
    for count_field in ("raw_candidate_count", "admitted_ref_count"):
        if not isinstance(item.get(count_field), int) or item.get(count_field) < 0:
            errors.append(f"{path}.{count_field} must be a non-negative integer")
    for dict_field in ("field_fill_counts", "unknown_counts", "fill_rates"):
        if not isinstance(item.get(dict_field), dict):
            errors.append(f"{path}.{dict_field} must be an object")


def validate_contradiction_search_attempt(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "attempt_id",
        "leaf_id",
        "query_context_ref",
        "query_variant_id",
        "query_text",
        "query_text_sha256",
        "source_refs_checked",
        "contradiction_found",
        "outcome_status",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "contradiction_search_attempt":
        errors.append(f"{path}.artifact_type must be contradiction_search_attempt")
    if item.get("schema_version") != CONTRADICTION_SEARCH_ATTEMPT_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {CONTRADICTION_SEARCH_ATTEMPT_SCHEMA_VERSION}")
    if not isinstance(item.get("source_refs_checked"), list):
        errors.append(f"{path}.source_refs_checked must be a list")
    if not isinstance(item.get("contradiction_found"), bool):
        errors.append(f"{path}.contradiction_found must be boolean")


def validate_negative_check_attempt(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "attempt_id",
        "leaf_id",
        "query_context_ref",
        "negative_check",
        "query_text",
        "query_text_sha256",
        "source_refs_checked",
        "outcome_status",
        "no_confirmation_found",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "negative_check_attempt":
        errors.append(f"{path}.artifact_type must be negative_check_attempt")
    if item.get("schema_version") != NEGATIVE_CHECK_ATTEMPT_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {NEGATIVE_CHECK_ATTEMPT_SCHEMA_VERSION}")
    if not isinstance(item.get("source_refs_checked"), list):
        errors.append(f"{path}.source_refs_checked must be a list")
    if not isinstance(item.get("no_confirmation_found"), bool):
        errors.append(f"{path}.no_confirmation_found must be boolean")


def validate_retrieval_breadth_coverage_slice(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "coverage_id",
        "leaf_id",
        "breadth_profile_ref",
        "source_class_coverage",
        "claim_family_count",
        "source_family_count",
        "fresh_source_count",
        "contradiction_attempt_refs",
        "negative_check_attempt_refs",
        "protected_primary_status",
        "raw_candidate_count",
        "admitted_ref_count",
        "metadata_fill_diagnostic_refs",
        "unknown_field_counts",
        "unsatisfied_breadth_dimensions",
        "breadth_certified",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "retrieval_breadth_coverage":
        errors.append(f"{path}.artifact_type must be retrieval_breadth_coverage")
    if item.get("schema_version") != RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION}")
    if item.get("protected_primary_status") not in {"satisfied", "not_required", "blocked", "missing"}:
        errors.append(f"{path}.protected_primary_status is invalid")
    for count_field in (
        "claim_family_count",
        "source_family_count",
        "fresh_source_count",
        "raw_candidate_count",
        "admitted_ref_count",
    ):
        if not isinstance(item.get(count_field), int) or item.get(count_field) < 0:
            errors.append(f"{path}.{count_field} must be a non-negative integer")
    for list_field in (
        "contradiction_attempt_refs",
        "negative_check_attempt_refs",
        "metadata_fill_diagnostic_refs",
        "unsatisfied_breadth_dimensions",
    ):
        if not isinstance(item.get(list_field), list):
            errors.append(f"{path}.{list_field} must be a list")
    for dict_field in ("source_class_coverage", "unknown_field_counts"):
        if not isinstance(item.get(dict_field), dict):
            errors.append(f"{path}.{dict_field} must be an object")
    if not isinstance(item.get("breadth_certified"), bool):
        errors.append(f"{path}.breadth_certified must be boolean")


def validate_research_sufficiency_certificate(item: Any, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "artifact_type",
        "schema_version",
        "certificate_id",
        "leaf_id",
        "query_context_ref",
        "requirement_ref",
        "sufficiency_profile_id",
        "status",
        "classification_dispatch_allowed",
        "evidence_refs",
        "breadth_coverage_ref",
        "breadth_certified",
        "expansion_attempt_refs",
        "fallback_state_ref",
        "temporal_validation_status",
        "freshness_status",
        "macro_fallback_sufficiency_status",
        "unsatisfied_requirement_codes",
        "blocking_reason_codes",
        "authority_boundary",
        "certifier_version",
    ):
        if field not in item:
            errors.append(f"{path} missing {field}")
    if item.get("artifact_type") != "research_sufficiency_certificate":
        errors.append(f"{path}.artifact_type must be research_sufficiency_certificate")
    if item.get("schema_version") != RESEARCH_SUFFICIENCY_CERTIFICATE_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RESEARCH_SUFFICIENCY_CERTIFICATE_SCHEMA_VERSION}")
    if item.get("status") not in ALLOWED_RESEARCH_SUFFICIENCY_STATUSES:
        errors.append(f"{path}.status is invalid")
    if not isinstance(item.get("classification_dispatch_allowed"), bool):
        errors.append(f"{path}.classification_dispatch_allowed must be boolean")
    if item.get("classification_dispatch_allowed") is True and item.get("status") not in {
        "certified_high_certainty",
        "structurally_unanswerable",
    }:
        errors.append(f"{path}.classification_dispatch_allowed requires a certified status")
    if item.get("classification_dispatch_allowed") is False and item.get("status") in {
        "certified_high_certainty",
        "structurally_unanswerable",
    }:
        errors.append(f"{path}.certified status must allow classification dispatch")
    if item.get("status") == "certified_high_certainty" and item.get("breadth_certified") is not True:
        errors.append(f"{path}.certified_high_certainty requires breadth_certified true")
    if item.get("temporal_validation_status") not in {"pass", "invalid"}:
        errors.append(f"{path}.temporal_validation_status is invalid")
    for list_field in (
        "evidence_refs",
        "expansion_attempt_refs",
        "unsatisfied_requirement_codes",
        "blocking_reason_codes",
    ):
        if not isinstance(item.get(list_field), list):
            errors.append(f"{path}.{list_field} must be a list")
    if not _reason_codes_are_compact(item.get("unsatisfied_requirement_codes")):
        errors.append(f"{path}.unsatisfied_requirement_codes must be compact reason codes")
    if not _reason_codes_are_compact(item.get("blocking_reason_codes")):
        errors.append(f"{path}.blocking_reason_codes must be compact reason codes")
    if not isinstance(item.get("authority_boundary"), dict):
        errors.append(f"{path}.authority_boundary must be an object")
    elif item["authority_boundary"].get("forecast_authority") is not False:
        errors.append(f"{path}.authority_boundary.forecast_authority must be false")


def validate_retrieval_stage_contract_records(packet: dict[str, Any], errors: list[str]) -> None:
    for idx, record in enumerate(
        packet.get("retrieval_stage_status_records", [])
        if isinstance(packet.get("retrieval_stage_status_records"), list)
        else []
    ):
        if not isinstance(record, dict):
            errors.append(f"retrieval_stage_status_records[{idx}] must be an object")
            continue
        try:
            validate_stage_status_snapshot(record)
        except Exception as exc:  # pragma: no cover - exact contract exception belongs to Session 1
            errors.append(f"retrieval_stage_status_records[{idx}] invalid: {exc}")
    for idx, record in enumerate(
        packet.get("retrieval_stage_execution_events", [])
        if isinstance(packet.get("retrieval_stage_execution_events"), list)
        else []
    ):
        if not isinstance(record, dict):
            errors.append(f"retrieval_stage_execution_events[{idx}] must be an object")
            continue
        try:
            validate_stage_execution_event(record)
        except Exception as exc:  # pragma: no cover - exact contract exception belongs to Session 1
            errors.append(f"retrieval_stage_execution_events[{idx}] invalid: {exc}")


def validate_research_sufficiency_dispatch_gate(packet: dict[str, Any], errors: list[str]) -> None:
    summary = packet.get("research_sufficiency_summary")
    if not isinstance(summary, dict):
        return
    status = summary.get("classification_dispatch_status")
    if status not in ALLOWED_CLASSIFICATION_DISPATCH_STATUSES:
        errors.append("research_sufficiency_summary.classification_dispatch_status is invalid")
    leaf_ids = {
        context.get("leaf_id")
        for context in packet.get("leaf_query_contexts", [])
        if isinstance(context, dict) and _is_non_empty_string(context.get("leaf_id"))
    }
    certificates = {
        cert.get("leaf_id"): cert
        for cert in packet.get("leaf_research_sufficiency_certificates", [])
        if isinstance(cert, dict) and _is_non_empty_string(cert.get("leaf_id"))
    }
    missing_leaf_ids = sorted(str(leaf_id) for leaf_id in leaf_ids if leaf_id not in certificates)
    cert_refs = [
        cert.get("certificate_id")
        for cert in packet.get("leaf_research_sufficiency_certificates", [])
        if isinstance(cert, dict) and _is_non_empty_string(cert.get("certificate_id"))
    ]
    if status == "allowed":
        if missing_leaf_ids:
            errors.append(
                "research_sufficiency_summary.classification_dispatch_status allowed with missing certificates: "
                + ",".join(missing_leaf_ids)
            )
        for leaf_id, cert in certificates.items():
            if cert.get("classification_dispatch_allowed") is not True:
                errors.append(f"certificate for {leaf_id} does not allow classification dispatch")
            if cert.get("status") in {
                "blocked_insufficient_research",
                "blocked_missing_breadth",
                "blocked_stale",
                "blocked_temporal_invalid",
                "blocked_macro_fallback_only",
            }:
                errors.append(f"certificate for {leaf_id} has blocked status {cert.get('status')}")
            if cert.get("temporal_validation_status") != "pass":
                errors.append(f"certificate for {leaf_id} is temporally invalid")
            if cert.get("freshness_status") == "stale_or_missing_fresh_source":
                errors.append(f"certificate for {leaf_id} is stale")
            if "macro_fallback_only_for_critical_or_source_of_truth" in cert.get("blocking_reason_codes", []):
                errors.append(f"certificate for {leaf_id} is macro-fallback-only for critical/source-of-truth leaf")
    if status == "blocked_insufficient_research":
        if not isinstance(packet.get("retrieval_stage_status_records"), list) or not packet["retrieval_stage_status_records"]:
            errors.append("blocked retrieval requires retrieval_stage_status_records")
        if not isinstance(packet.get("retrieval_stage_execution_events"), list) or not packet["retrieval_stage_execution_events"]:
            errors.append("blocked retrieval requires retrieval_stage_execution_events")
    if summary.get("all_required_leaves_certified") is True and status != "allowed":
        errors.append("all_required_leaves_certified true requires classification_dispatch_status allowed")
    if status == "allowed" and summary.get("all_required_leaves_certified") is not True:
        errors.append("classification_dispatch_status allowed requires all_required_leaves_certified true")
    if status in {"allowed", "blocked_insufficient_research"}:
        if sorted(summary.get("leaf_certificate_refs", [])) != sorted(cert_refs):
            errors.append("research_sufficiency_summary.leaf_certificate_refs must match certificate ids")


def validate_retrieval_packet(packet: dict[str, Any]) -> RetrievalValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(packet, dict):
        return RetrievalValidationResult(False, ("packet must be an object",))
    _reject_forbidden_retrieval_keys(packet, errors, "packet")
    required = (
        "artifact_type",
        "schema_version",
        "case_id",
        "dispatch_id",
        "question_decomposition_artifact_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "pre_dispatch_input_whitelist_refs",
        "live_retrieval_allowlist",
        "temporal_isolation_status",
        "leaf_query_contexts",
        "leaf_retrieval_results",
        "retrieval_quality_summary",
        "retrieval_breadth_profiles",
        "retrieval_breadth_coverage_slices",
        "retrieval_metadata_fill_diagnostics",
        "research_sufficiency_summary",
        "omitted_candidates",
        "contradiction_search_attempts",
        "negative_check_attempts",
        "retrieval_expansion_attempts",
        "retrieval_fallback_states",
        "leaf_research_sufficiency_certificates",
        "retrieval_stage_status_records",
        "retrieval_stage_execution_events",
        "protected_primary_access_failures",
        "missingness_candidates",
        "search_candidate_urls",
        "search_candidate_url_omissions",
        "native_research_attempts",
        "native_research_candidate_discoveries",
        "native_research_transport_diagnostics",
        "source_metadata_classifier_slices",
        "source_metadata_classifier_unavailable_diagnostics",
        "source_metadata_resolutions",
        "retrieval_evidence_provenance_slices",
        "policy_context_ref",
    )
    for field in required:
        if field not in packet:
            errors.append(f"packet missing {field}")
    if packet.get("artifact_type") != RETRIEVAL_PACKET_ARTIFACT_TYPE:
        errors.append(f"artifact_type must be {RETRIEVAL_PACKET_ARTIFACT_TYPE}")
    if packet.get("schema_version") != RETRIEVAL_PACKET_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RETRIEVAL_PACKET_SCHEMA_VERSION}")
    for field in ("case_id", "dispatch_id", "question_decomposition_artifact_id", "forecast_timestamp", "source_cutoff_timestamp"):
        if not _is_non_empty_string(packet.get(field)):
            errors.append(f"{field} is required")
    if packet.get("temporal_isolation_status") not in {"pass", "fail"}:
        errors.append("temporal_isolation_status must be pass or fail")
    if not isinstance(packet.get("pre_dispatch_input_whitelist_refs"), list):
        errors.append("pre_dispatch_input_whitelist_refs must be a list")
    if not isinstance(packet.get("live_retrieval_allowlist"), list):
        errors.append("live_retrieval_allowlist must be a list")
    dispatch_context = {
        "case_id": packet.get("case_id"),
        "dispatch_id": packet.get("dispatch_id"),
        "forecast_timestamp": packet.get("forecast_timestamp"),
        "source_cutoff_timestamp": packet.get("source_cutoff_timestamp"),
        "pre_dispatch_input_whitelist_refs": packet.get("pre_dispatch_input_whitelist_refs", []),
        "live_retrieval_allowlist": packet.get("live_retrieval_allowlist", []),
    }
    contexts = packet.get("leaf_query_contexts")
    if not isinstance(contexts, list) or not contexts:
        errors.append("leaf_query_contexts must be a non-empty list")
        contexts = []
    context_leaf_ids = []
    for idx, context in enumerate(contexts):
        validate_query_context(context, f"leaf_query_contexts[{idx}]", errors)
        if isinstance(context, dict):
            context_leaf_ids.append(context.get("leaf_id"))
    results = packet.get("leaf_retrieval_results")
    if not isinstance(results, list) or not results:
        errors.append("leaf_retrieval_results must be a non-empty list")
        results = []
    result_leaf_ids = []
    for idx, result in enumerate(results):
        if not isinstance(result, dict):
            errors.append(f"leaf_retrieval_results[{idx}] must be an object")
            continue
        result_leaf_ids.append(result.get("leaf_id"))
        if result.get("schema_version") != LEAF_RETRIEVAL_RESULT_SCHEMA_VERSION:
            errors.append(f"leaf_retrieval_results[{idx}].schema_version is invalid")
        selected = result.get("selected_evidence")
        if not isinstance(selected, list):
            errors.append(f"leaf_retrieval_results[{idx}].selected_evidence must be a list")
        else:
            for evidence_idx, evidence in enumerate(selected):
                validate_retrieval_evidence_item(
                    evidence,
                    f"leaf_retrieval_results[{idx}].selected_evidence[{evidence_idx}]",
                    errors,
                )
                if isinstance(evidence, dict):
                    temporal = validate_temporal_eligibility(evidence, dispatch_context)
                    for warning in temporal["warning_reason_codes"]:
                        warnings.append(
                            f"leaf_retrieval_results[{idx}].selected_evidence[{evidence_idx}]: {warning}"
                        )
                    declared = evidence.get("temporal_gate_status")
                    computed = temporal["temporal_gate_status"]
                    if declared == "pass" and computed != "pass":
                        errors.append(
                            f"leaf_retrieval_results[{idx}].selected_evidence[{evidence_idx}].temporal_gate_status "
                            f"declares pass but validator returned {computed}"
                        )
                    if computed == "fail":
                        errors.append(
                            f"leaf_retrieval_results[{idx}].selected_evidence[{evidence_idx}] failed temporal isolation: "
                            + ",".join(temporal["rejection_reason_codes"])
                        )
        omitted = result.get("omitted_candidates")
        if not isinstance(omitted, list):
            errors.append(f"leaf_retrieval_results[{idx}].omitted_candidates must be a list")
        else:
            for candidate_idx, candidate in enumerate(omitted):
                validate_candidate_record(
                    candidate,
                    f"leaf_retrieval_results[{idx}].omitted_candidates[{candidate_idx}]",
                    errors,
                )
    if sorted(context_leaf_ids) != sorted(result_leaf_ids):
        errors.append("leaf_retrieval_results must align one-to-one with leaf_query_contexts")
    for field in (
        "retrieval_breadth_profiles",
        "retrieval_breadth_coverage_slices",
        "retrieval_metadata_fill_diagnostics",
        "omitted_candidates",
        "contradiction_search_attempts",
        "negative_check_attempts",
        "retrieval_expansion_attempts",
        "retrieval_fallback_states",
        "leaf_research_sufficiency_certificates",
        "retrieval_stage_status_records",
        "retrieval_stage_execution_events",
        "protected_primary_access_failures",
        "missingness_candidates",
        "search_candidate_urls",
        "search_candidate_url_omissions",
        "native_research_attempts",
        "native_research_candidate_discoveries",
        "native_research_transport_diagnostics",
        "source_metadata_classifier_slices",
        "source_metadata_classifier_unavailable_diagnostics",
        "source_metadata_resolutions",
        "retrieval_evidence_provenance_slices",
    ):
        if not isinstance(packet.get(field), list):
            errors.append(f"{field} must be a list")
    if not isinstance(packet.get("research_sufficiency_summary"), dict):
        errors.append("research_sufficiency_summary must be an object")
    for idx, candidate in enumerate(packet.get("omitted_candidates", []) if isinstance(packet.get("omitted_candidates"), list) else []):
        validate_candidate_record(candidate, f"omitted_candidates[{idx}]", errors)
    for idx, item in enumerate(packet.get("search_candidate_urls", []) if isinstance(packet.get("search_candidate_urls"), list) else []):
        validate_search_candidate_url(item, f"search_candidate_urls[{idx}]", errors)
    for idx, item in enumerate(packet.get("native_research_candidate_discoveries", []) if isinstance(packet.get("native_research_candidate_discoveries"), list) else []):
        validate_native_research_candidate_discovery(
            item,
            f"native_research_candidate_discoveries[{idx}]",
            errors,
        )
    for idx, item in enumerate(packet.get("retrieval_metadata_fill_diagnostics", []) if isinstance(packet.get("retrieval_metadata_fill_diagnostics"), list) else []):
        validate_retrieval_metadata_fill_diagnostic(item, f"retrieval_metadata_fill_diagnostics[{idx}]", errors)
    for idx, item in enumerate(packet.get("contradiction_search_attempts", []) if isinstance(packet.get("contradiction_search_attempts"), list) else []):
        validate_contradiction_search_attempt(item, f"contradiction_search_attempts[{idx}]", errors)
    for idx, item in enumerate(packet.get("negative_check_attempts", []) if isinstance(packet.get("negative_check_attempts"), list) else []):
        validate_negative_check_attempt(item, f"negative_check_attempts[{idx}]", errors)
    for idx, item in enumerate(packet.get("retrieval_breadth_coverage_slices", []) if isinstance(packet.get("retrieval_breadth_coverage_slices"), list) else []):
        validate_retrieval_breadth_coverage_slice(item, f"retrieval_breadth_coverage_slices[{idx}]", errors)
    for idx, item in enumerate(packet.get("leaf_research_sufficiency_certificates", []) if isinstance(packet.get("leaf_research_sufficiency_certificates"), list) else []):
        validate_research_sufficiency_certificate(
            item,
            f"leaf_research_sufficiency_certificates[{idx}]",
            errors,
        )
    validate_retrieval_stage_contract_records(packet, errors)
    validate_research_sufficiency_dispatch_gate(packet, errors)
    for idx, item in enumerate(packet.get("source_metadata_classifier_slices", []) if isinstance(packet.get("source_metadata_classifier_slices"), list) else []):
        validate_source_metadata_classifier_slice(item, f"source_metadata_classifier_slices[{idx}]", errors)
    for idx, item in enumerate(packet.get("source_metadata_classifier_unavailable_diagnostics", []) if isinstance(packet.get("source_metadata_classifier_unavailable_diagnostics"), list) else []):
        validate_source_metadata_classifier_unavailable(
            item,
            f"source_metadata_classifier_unavailable_diagnostics[{idx}]",
            errors,
        )
    for idx, item in enumerate(packet.get("source_metadata_resolutions", []) if isinstance(packet.get("source_metadata_resolutions"), list) else []):
        validate_source_metadata_resolution(item, f"source_metadata_resolutions[{idx}]", errors)
    for idx, item in enumerate(packet.get("retrieval_evidence_provenance_slices", []) if isinstance(packet.get("retrieval_evidence_provenance_slices"), list) else []):
        validate_evidence_provenance_slice(item, f"retrieval_evidence_provenance_slices[{idx}]", errors)
    if packet.get("schema_feature_gates", {}).get("RET-001") != "implemented":
        warnings.append("schema_feature_gates.RET-001 is not marked implemented")
    if packet.get("schema_feature_gates", {}).get("RET-002") != "implemented":
        warnings.append("schema_feature_gates.RET-002 is not marked implemented")
    if packet.get("schema_feature_gates", {}).get("RET-004") != "implemented":
        warnings.append("schema_feature_gates.RET-004 is not marked implemented")
    if packet.get("schema_feature_gates", {}).get("RET-009") != "implemented":
        warnings.append("schema_feature_gates.RET-009 is not marked implemented")
    return RetrievalValidationResult(not errors, tuple(errors), tuple(warnings))


def dump_retrieval_packet(packet: dict[str, Any]) -> str:
    return json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def load_json_object(path: Path | str) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RetrievalPacketError(f"{path} must contain a JSON object")
    return loaded


def build_retrieval_packet_manifest(
    packet: dict[str, Any],
    *,
    path: Path | str,
    input_manifest_ids: list[str] | None = None,
    validation_status: str = "valid",
    validation_result_refs: list[str] | None = None,
) -> dict[str, Any]:
    result = validate_retrieval_packet(packet)
    if not result.valid:
        raise RetrievalPacketError("; ".join(result.errors))
    context = ArtifactManifestContext(
        case_id=packet["case_id"],
        case_key=packet.get("case_key") or packet["case_id"],
        dispatch_id=packet["dispatch_id"],
        stage="retrieval_packet",
        producer="ads_researcher_swarm",
        forecast_timestamp=packet["forecast_timestamp"],
        source_cutoff_timestamp=packet["source_cutoff_timestamp"],
    )
    return build_artifact_manifest(
        context=context,
        artifact_type=RETRIEVAL_PACKET_MANIFEST_ARTIFACT_TYPE,
        artifact_schema_version=RETRIEVAL_PACKET_SCHEMA_VERSION,
        path=path,
        input_manifest_ids=input_manifest_ids,
        validation_status=validation_status,
        validation_result_refs=validation_result_refs,
        validator_version=RETRIEVAL_VALIDATOR_VERSION,
        temporal_isolation_status=packet["temporal_isolation_status"],
        metadata={
            "feature_id": "RET-001",
            "leaf_count": len(packet.get("leaf_query_contexts", [])),
            "selected_evidence_count": sum(
                len(result.get("selected_evidence", [])) for result in packet.get("leaf_retrieval_results", [])
            ),
            "omitted_candidate_count": len(packet.get("omitted_candidates", [])),
        },
    )
