"""RET-001 retrieval packet schema and deterministic query planning helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION = "source-metadata-resolution/v1"
ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION = "atomic-claim-candidate/v1"
CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION = "claim-family-resolution/v1"
RETRIEVAL_TEMPORAL_ELIGIBILITY_SCHEMA_VERSION = "retrieval-temporal-eligibility/v1"
RETRIEVAL_EVIDENCE_PROVENANCE_SCHEMA_VERSION = "retrieval-evidence-provenance/v1"
RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION = "retrieval-breadth-profile/v1"
RETRIEVAL_VALIDATOR_VERSION = "ads-ret-002-004-retrieval-schema/v1"
RETRIEVAL_QUERY_PLANNER_VERSION = "ads-ret-001-query-planner/v1"
RETRIEVAL_TEMPORAL_VALIDATOR_VERSION = "ads-ret-002-temporal-isolation/v1"
RETRIEVAL_PROVENANCE_NORMALIZER_VERSION = "ads-ret-004-provenance-normalizer/v1"
OPENCLAW_BROWSER_PROVIDER_ID = "openclaw_web_fetch_browser"

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
    "accepted",
    "rejected",
    "classifier_unsupported",
    "unsupported_source_class",
}
ALLOWED_SOURCE_FAMILY_STATUSES = {
    "resolved",
    "same_source_family",
    "syndicated_copy",
    "mirrored_api_endpoint",
    "content_hash_dedupe",
    "unknown_not_counted",
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


def build_retrieval_breadth_profile_placeholder(leaf: dict[str, Any]) -> dict[str, Any]:
    requirements = copy.deepcopy(leaf.get("research_sufficiency_requirements", {}))
    source_targets = _source_class_targets(requirements)
    tier, variant_count, raw_range, admitted_range, max_expansion = _volume_tier_for_leaf(leaf, requirements)
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
            "protected_primary_required": bool(requirements.get("protected_primary_required", False)),
        },
        "claim_family_requirements": {
            "min_independent_claim_families": int(requirements.get("min_independent_claim_families", 0)),
            "duplicate_same_claim_counts_once": True,
        },
        "source_family_requirements": {
            "min_independent_source_families": int(requirements.get("min_independent_source_families", 0)),
            "wire_or_api_syndication_counts_once": True,
        },
        "freshness_requirement": {
            "recency_window_seconds": int(requirements.get("recency_window_seconds", 0)),
            "min_fresh_sources": int(requirements.get("min_temporally_fresh_sources", 0)),
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
            "status": "schema_placeholder_only",
            "certification_behavior": "not_implemented_in_RET_001",
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
    variant_count: int = 3,
) -> list[dict[str, Any]]:
    leaf_question = _normalized_space(str(leaf.get("question_text", "")))
    macro = _normalized_space(str(macro_question or ""))
    purpose = _normalized_space(str(leaf.get("purpose", "other"))).replace("_", " ")
    condition_scope = str(leaf.get("leaf_condition_scope", "unconditional"))
    terms = " ".join((market_terms or [])[:8])
    fields = " ".join((required_evidence_fields or [])[:8])
    source_targets = " ".join((source_class_targets or [])[:4]).replace("_", " ")
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
    query_variants = compose_query_variants(
        macro_question=str(qdt.get("macro_question", "")),
        leaf=leaf,
        branch=branch,
        market_terms=market_terms,
        required_evidence_fields=required_fields,
        source_class_targets=source_targets,
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
        "capabilities": ["web_search", "direct_url", "site_search", "followed_link"],
        "availability_status": availability_status,
        "news_feed_api_enabled": False,
        "direct_url_priority": "official_or_resolution_urls_first",
        "unavailable_reason": unavailable_reason,
        "checked_at": checked_at,
        "feature_gate_status": "browser_provider_resolution_pending_RET_004_RET_009",
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
        "provider_capabilities": ["web_search", "direct_url"],
        "provider_availability_status": "unavailable",
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
) -> dict[str, Any]:
    if attempt_status not in ALLOWED_NATIVE_ATTEMPT_STATUSES:
        raise RetrievalPacketError(f"unknown native research attempt status: {attempt_status}")
    seed = {
        "leaf_id": query_context.get("leaf_id"),
        "query_variant_id": query_variant.get("query_variant_id"),
        "query_sha": query_variant.get("query_text_sha256"),
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
        "candidate_citation_refs": [],
        "candidate_claim_refs": [],
        "contradiction_candidate_refs": [],
        "negative_check_candidate_refs": [],
        "model_proposed_source_metadata": {},
        "candidate_output_schema_version": "native-research-candidates/v1",
        "attempt_status": attempt_status,
        "failure_reason_codes": ["not_executed_schema_only_RET_001"],
        "feature_gate_status": "native_transport_invocation_pending_RET_010",
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
    protected_primary = bool(classifier_slice.get("protected_primary_proposed")) or proposed in PROTECTED_SOURCE_CLASSES
    has_proof, proof_method = _deterministic_source_class_proof(candidate, proposed, market_rules=market_rules)
    if protected_primary and not has_proof:
        return "classifier_unsupported", "unknown", ["classifier_unsupported_for_protected_primary"]
    accepted = classifier_slice.get("deterministic_acceptance_status") == "accepted" or classifier_slice.get("validator_acceptance_status") == "accepted"
    if accepted or has_proof:
        reason_codes = list(classifier_slice.get("acceptance_reason_codes") or [])
        if proof_method != "no_deterministic_proof":
            reason_codes.append(proof_method)
        return "accepted", proposed, sorted(set(reason_codes or ["classifier_validated"]))
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
            return explicit, proof_method if has_proof else "candidate_field", "not_used", []
    proposed_native = candidate.get("model_proposed_source_class")
    if _is_non_empty_string(proposed_native) and str(proposed_native) not in ALLOWED_SOURCE_CLASSES:
        return "unknown", "unknown", "unsupported_source_class", ["unsupported_model_proposed_source_class"]
    classifier_status, classifier_class, classifier_reasons = _resolve_classifier_source_class(
        candidate,
        classifier_slice,
        market_rules=market_rules,
    )
    if classifier_status == "accepted" and classifier_class != "unknown":
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
        return str(explicit), "candidate_field", "resolved"
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
    if source_family_status == "syndicated_copy":
        return "syndicated_copy"
    if seen_claim_family_ids and any(claim_id in seen_claim_family_ids for claim_id in claim_family_ids):
        return "same_claim_family"
    if seen_source_family_ids and source_family_id in seen_source_family_ids:
        return "same_source_family"
    return "independent"


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
        "feature_gate_status": "ret_004_deterministic_resolution",
        "normalizer_version": RETRIEVAL_PROVENANCE_NORMALIZER_VERSION,
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
    canonical_source_id = "source-" + _hash_suffix(
        {
            "source_family_id": source_family_id,
            "canonical_url": canonical_url,
            "registrable_domain": _registrable_domain(canonical_url),
        }
    )
    temporal_validation = validate_temporal_eligibility(
        {**candidate, "retrieval_transport": retrieval_transport, "canonical_url": canonical_url},
        dispatch_context=dispatch_context,
    )
    resolutions = list(claim_family_resolutions or resolve_claim_families(claim_candidates or []))
    claim_family_ids = [
        resolution["claim_family_id"]
        for resolution in resolutions
        if resolution.get("counts_toward_claim_family_breadth") and resolution.get("claim_family_id") != "claim-family-unknown"
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
        and independence_status not in {"unknown_not_counted"}
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
        or (classifier_slice or {}).get("visible_published_at")
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
        published_at_method=str(candidate.get("published_at_extraction_method") or "unknown"),
        classifier_slice_ref=classifier_ref,
        classifier_acceptance_status=classifier_status,
        classifier_acceptance_reason_codes=classifier_reason_codes,
        metadata_confidence="medium" if counts_toward_breadth else "unknown",
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
        profile = build_retrieval_breadth_profile_placeholder(leaves_by_id[context["leaf_id"]])
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
    selected = copy.deepcopy(selected_evidence or [])
    provenance_slices = []
    source_metadata_resolutions = []
    for item in selected:
        provenance = normalize_retrieval_provenance(
            item,
            dispatch_context=dispatch_context,
            market_rules=(evidence_packet or {}).get("market_rules") if isinstance(evidence_packet, dict) else None,
        )
        provenance_slices.append(provenance)
        source_metadata_resolutions.append(provenance["source_metadata_resolution"])
        item["source_metadata_resolution_ref"] = provenance["source_metadata_resolution_ref"]
        item["canonical_source_id"] = provenance["canonical_source_id"]
        item["source_family_id"] = provenance["source_family_id"]
        item["source_class"] = provenance["source_class"]
        item["independence_status"] = provenance["independence_status"]
        item["temporal_gate_status"] = provenance["temporal_gate_status"]
        item["content_sha256"] = provenance["content_sha256"]
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
        "leaf_research_sufficiency_certificates": [],
        "protected_primary_access_failures": [],
        "missingness_candidates": [],
        "browser_search_provider_diagnostics": [
            build_browser_search_provider_diagnostic(checked_at=forecast)
        ],
        "native_research_attempts": [],
        "browser_retrieval_attempts": [],
        "source_metadata_resolutions": source_metadata_resolutions,
        "atomic_claim_candidates": [],
        "claim_family_resolutions": [],
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
            "RET-009": "pending",
            "RET-010": "pending",
            "RET-011": "pending",
        },
        "validation_summary": {
            "status": "schema_constructed",
            "validator_version": RETRIEVAL_VALIDATOR_VERSION,
            "reason_codes": ["ret_001_schema", "ret_002_temporal_validator", "ret_004_provenance_normalizer"],
        },
    }
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
        "research_sufficiency_summary",
        "omitted_candidates",
        "contradiction_search_attempts",
        "negative_check_attempts",
        "retrieval_expansion_attempts",
        "leaf_research_sufficiency_certificates",
        "protected_primary_access_failures",
        "missingness_candidates",
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
        "omitted_candidates",
        "contradiction_search_attempts",
        "negative_check_attempts",
        "retrieval_expansion_attempts",
        "leaf_research_sufficiency_certificates",
        "protected_primary_access_failures",
        "missingness_candidates",
        "source_metadata_resolutions",
        "retrieval_evidence_provenance_slices",
    ):
        if not isinstance(packet.get(field), list):
            errors.append(f"{field} must be a list")
    if not isinstance(packet.get("research_sufficiency_summary"), dict):
        errors.append("research_sufficiency_summary must be an object")
    for idx, candidate in enumerate(packet.get("omitted_candidates", []) if isinstance(packet.get("omitted_candidates"), list) else []):
        validate_candidate_record(candidate, f"omitted_candidates[{idx}]", errors)
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
