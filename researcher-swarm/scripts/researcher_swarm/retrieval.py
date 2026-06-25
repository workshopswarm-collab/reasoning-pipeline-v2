"""RET-001 retrieval packet schema and deterministic query planning helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION = "retrieval-breadth-profile/v1"
RETRIEVAL_VALIDATOR_VERSION = "ads-ret-001-retrieval-schema/v1"
RETRIEVAL_QUERY_PLANNER_VERSION = "ads-ret-001-query-planner/v1"
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
            "RET-002": "temporal_validator_pending",
            "RET-003": "quality_scoring_pending",
            "RET-004": "provenance_resolution_pending",
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


def build_source_metadata_resolution_placeholder(
    *,
    evidence_ref: str,
    transport_attempt_ref: str,
    canonical_url: str = "",
    source_class: str = "unknown",
) -> dict[str, Any]:
    if source_class not in ALLOWED_SOURCE_CLASSES:
        raise RetrievalPacketError(f"unknown source class: {source_class}")
    resolution_id = _sha_id(
        "source-metadata",
        {"evidence_ref": evidence_ref, "transport_attempt_ref": transport_attempt_ref, "canonical_url": canonical_url},
    )
    return {
        "artifact_type": "source_metadata_resolution",
        "schema_version": SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION,
        "resolution_id": resolution_id,
        "evidence_ref": evidence_ref,
        "transport_attempt_ref": transport_attempt_ref,
        "canonical_url": canonical_url,
        "registrable_domain": "",
        "source_class": source_class,
        "source_class_resolution_method": "unknown",
        "source_family_id": "source-family-unknown",
        "source_family_resolution_method": "unknown",
        "claim_family_resolution_refs": [],
        "claim_family_ids": [],
        "claim_family_resolution_method": "unknown",
        "temporal_safety_status": "unknown_not_counted",
        "published_at": None,
        "published_at_method": "unknown",
        "classifier_slice_ref": None,
        "classifier_acceptance_status": "not_used",
        "classifier_acceptance_reason_codes": [],
        "metadata_confidence": "unknown",
        "counts_toward_breadth": False,
        "unknown_reason_codes": ["ret_004_resolver_pending"],
        "feature_gate_status": "deterministic_resolution_pending_RET_004_RET_010_RET_011",
    }


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
    captured_at: str | None = None,
    artifact_generated_at: str | None = None,
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
        "captured_at": captured_at,
        "artifact_generated_at": artifact_generated_at,
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
        "contradiction_family_id": None,
        "counts_toward_claim_family_breadth": counts,
        "reason_codes": [] if counts else ["no_accepted_atomic_claim_candidate"],
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
            "RET-002": "temporal_validation_not_run",
            "RET-003": "quality_scoring_not_run",
            "RET-004": "provenance_resolution_not_run",
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

    selected = copy.deepcopy(selected_evidence or [])
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
        "temporal_isolation_status": "pass",
        "temporal_isolation_schema_gate": {
            "feature_id": "RET-002",
            "status": "strict_validator_not_implemented_in_RET_001",
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
        "source_metadata_resolutions": [],
        "atomic_claim_candidates": [],
        "claim_family_resolutions": [],
        "evidence_chunks": [],
        "evidence_spans": [],
        "policy_context_ref": policy_context_ref or "artifact:effective-profile-context-unregistered",
        "schema_feature_gates": {
            "RET-001": "implemented",
            "RET-002": "pending",
            "RET-003": "pending",
            "RET-004": "pending",
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
            "reason_codes": ["ret_001_schema_and_query_planning_only"],
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
    ):
        if not isinstance(packet.get(field), list):
            errors.append(f"{field} must be a list")
    if not isinstance(packet.get("research_sufficiency_summary"), dict):
        errors.append("research_sufficiency_summary must be an object")
    for idx, candidate in enumerate(packet.get("omitted_candidates", []) if isinstance(packet.get("omitted_candidates"), list) else []):
        validate_candidate_record(candidate, f"omitted_candidates[{idx}]", errors)
    if packet.get("schema_feature_gates", {}).get("RET-001") != "implemented":
        warnings.append("schema_feature_gates.RET-001 is not marked implemented")
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
