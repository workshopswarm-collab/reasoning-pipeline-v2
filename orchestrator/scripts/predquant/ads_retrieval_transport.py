"""ADS source-populated retrieval transport adapter.

This module gathers candidate URLs and fetched browser content for the live
retrieval packet builder. It deliberately does not certify source class, claim
family, temporal safety, or research sufficiency from provider output.
"""

from __future__ import annotations

import copy
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from predquant.ads_native_research import (
    native_candidate_list as _native_candidate_payload_list,
    native_candidate_payload_errors,
    native_runtime_call_summary,
)

SOURCE_AUTHORITY_FIELDS = {
    "source_class",
    "source_family_id",
    "source_family",
    "claim_family_id",
    "claim_family_ids",
    "claim_family_resolution_ref",
    "claim_family_resolution_refs",
    "validated_atomic_claim_candidates",
    "atomic_claim_candidates",
    "claim_candidates",
    "claim_candidate_authority_boundary",
    "temporal_gate_status",
    "temporal_safety_status",
    "research_sufficiency",
    "research_sufficiency_certification",
    "sufficiency_certification",
    "admission_status",
}

DETERMINISTIC_SOURCE_CLASS_URL_REGISTRY = (
    {
        "registry_id": "ads-static-secondary-source-registry/reuters",
        "domain_suffixes": ("reuters.com",),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/apnews",
        "domain_suffixes": ("apnews.com", "ap.org"),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/bloomberg",
        "domain_suffixes": ("bloomberg.com",),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/financial-times",
        "domain_suffixes": ("ft.com",),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/wall-street-journal",
        "domain_suffixes": ("wsj.com",),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/cnbc",
        "domain_suffixes": ("cnbc.com",),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/bbc",
        "domain_suffixes": ("bbc.com", "bbc.co.uk"),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-specialist-source-registry/gartner",
        "domain_suffixes": ("gartner.com",),
        "source_class": "expert_or_specialist",
    },
    {
        "registry_id": "ads-static-secondary-source-registry/associated-press-hosted",
        "domain_suffixes": ("hosted.ap.org",),
        "source_class": "independent_secondary",
    },
    {
        "registry_id": "ads-static-official-source-registry/tesla-investor-relations",
        "domain_suffixes": ("ir.tesla.com",),
        "source_class": "official_or_primary",
    },
)
BOI_OFFICIAL_DOMAIN_SUFFIXES = ("boi.org.il",)
BOI_OFFICIAL_PATH_PREFIXES = (
    "/en/",
    "/he/",
    "/markets",
    "/monetary-policy",
    "/communication-and-publications",
    "/research",
    "/statistics",
)
BOI_CONTEXT_TERMS = (
    "bank of israel",
    "boi",
    "israeli central bank",
    "israel interest",
    "israel inflation",
    "israel monetary",
)

NATIVE_ALLOWED_FIELDS = {
    "url",
    "canonical_url",
    "source_label",
    "title",
    "why_it_may_matter",
    "why_may_matter",
    "related_leaf_id",
    "leaf_id",
    "query_variant_id",
    "native_research_attempt_ref",
    "attempt_ref",
    "resolved_model_id",
    "candidate_claim_text",
    "claim_text",
    "uncertainty_notes",
}

AMRG_RETRIEVAL_EFFECTS = {
    "retrieval_query_hint",
    "retrieval_hint",
    "source_hint",
    "source_hint_only_requires_fresh_retrieval_or_classification",
    "shared_retrieval_classification_cache_reuse",
}

RETRIEVAL_DIAGNOSTIC_FORBIDDEN_KEY_FRAGMENTS = (
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

LEGACY_DEFAULT_MAX_TOTAL_SEARCH_CALLS = 2
BROWSER_SEARCH_RETRY_POLICY_REF = "ads-browser-search-retry/v1"
BROWSER_SEARCH_RETRY_DIAGNOSTIC_SCHEMA_VERSION = "ads-browser-search-retry-diagnostic/v1"
NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION = "ads-native-research-transport-diagnostic/v1"


@dataclass(frozen=True)
class RetrievalProviderPolicy:
    max_direct_urls: int = 6
    max_total_direct_fetches: int = 6
    max_search_variants_per_leaf: int = 1
    max_search_results_per_variant: int = 5
    max_total_search_calls: int = 2
    max_total_search_elapsed_seconds: float = 90.0
    max_total_search_result_fetches: int = 4
    broad_search_enabled: bool = True
    native_enabled: bool = False
    deterministic_direct_url_source_classes: bool = True
    leaf_aware_default_search_budget: bool = True
    default_leaf_search_call_cap: int = 2
    high_priority_leaf_search_call_cap: int = 2
    protected_primary_leaf_search_call_cap: int = 3
    max_browser_search_attempts_per_query: int = 3
    browser_search_base_backoff_seconds: float = 2.0
    browser_search_max_backoff_seconds: float = 15.0
    browser_search_jitter_fraction: float = 0.25
    max_native_research_calls: int = 4
    max_native_candidate_fetches: int = 4


@dataclass
class RetrievalTransportResult:
    fetched_candidates: list[dict[str, Any]] = field(default_factory=list)
    search_candidate_urls: list[dict[str, Any]] = field(default_factory=list)
    native_research_candidates: list[dict[str, Any]] = field(default_factory=list)
    omitted_candidates: list[dict[str, Any]] = field(default_factory=list)
    supplemental_candidates: list[dict[str, Any]] = field(default_factory=list)
    direct_url_candidates: list[dict[str, Any]] = field(default_factory=list)
    transport_diagnostics: dict[str, Any] = field(default_factory=dict)


def _hash_suffix(value: Any, length: int = 24) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()[:length]


def _canonical_fetch_key(url: Any, source_cutoff_timestamp: str) -> tuple[str, str] | None:
    canonical_url = _canonicalize_url(url)
    if not canonical_url:
        return None
    return (canonical_url, source_cutoff_timestamp)


def _canonical_fetch_ref(canonical_url: str, source_cutoff_timestamp: str) -> str:
    return "canonical-fetch-" + _hash_suffix(
        {
            "canonical_url": canonical_url,
            "source_cutoff_timestamp": source_cutoff_timestamp,
        }
    )


def _browser_search_status(
    *,
    policy: RetrievalProviderPolicy,
    browser_search_configured: bool,
    search_call_count: int,
    search_failure_count: int,
) -> str:
    if not policy.broad_search_enabled:
        return "disabled"
    if not browser_search_configured:
        return "not_configured"
    if search_call_count <= 0:
        return "not_executed"
    if search_failure_count > 0:
        return "executed_with_failures"
    return "executed"


def _search_candidate_discovery_status(
    *,
    policy: RetrievalProviderPolicy,
    browser_search_configured: bool,
    search_call_count: int,
    search_failure_count: int,
    search_candidate_url_count: int,
) -> str:
    if not policy.broad_search_enabled:
        return "disabled"
    if not browser_search_configured:
        return "search_transport_unavailable"
    if search_call_count <= 0:
        return "not_executed"
    if search_failure_count > 0:
        return "executed_with_failures"
    if search_candidate_url_count > 0:
        return "executed_with_candidates"
    return "executed_no_candidates"


def _native_research_status(
    *,
    policy: RetrievalProviderPolicy,
    native_candidate_provider: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
    native_research_call_count: int,
    native_research_failure_count: int = 0,
    native_research_candidate_count: int = 0,
) -> str:
    if not policy.native_enabled:
        return "disabled"
    if native_candidate_provider is None:
        return "not_configured"
    if native_research_call_count <= 0:
        return "configured_not_needed"
    if native_research_failure_count > 0 and native_research_candidate_count <= 0:
        return "executed_with_failures"
    if native_research_candidate_count > 0:
        return "executed_with_candidates"
    return "executed_no_candidates"


def collect_live_retrieval_candidates(
    *,
    qdt: dict[str, Any],
    evidence_packet: dict[str, Any],
    case_contract: dict[str, Any],
    amrg_context: dict[str, Any] | None,
    source_cutoff_timestamp: str,
    forecast_timestamp: str,
    provider_policy: RetrievalProviderPolicy | None = None,
    browser_provider: Any | None = None,
    native_candidate_provider: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> RetrievalTransportResult:
    """Collect live retrieval candidate inputs without granting evidence authority."""

    from researcher_swarm.retrieval import build_retrieval_query_contexts

    policy = provider_policy or RetrievalProviderPolicy()
    browser_provider_diagnostics = _provider_diagnostics(browser_provider)
    browser_fetch_configured = _provider_capability_configured(
        browser_provider,
        "fetch_url",
        browser_provider_diagnostics,
        "fetch_configured",
    )
    browser_search_configured = _provider_capability_configured(
        browser_provider,
        "search_candidate_urls",
        browser_provider_diagnostics,
        "search_configured",
    )
    contexts = build_retrieval_query_contexts(
        qdt,
        evidence_packet=evidence_packet,
        amrg_context=amrg_context,
        forecast_timestamp=forecast_timestamp,
        source_cutoff_timestamp=source_cutoff_timestamp,
    )
    direct_urls = _collect_direct_url_hints(case_contract, evidence_packet, amrg_context)[: policy.max_direct_urls]
    result = RetrievalTransportResult(direct_url_candidates=direct_urls)
    direct_fetch_count = 0
    direct_fetch_skipped_count = 0
    direct_fetch_cache_hit_count = 0
    search_call_count = 0
    search_primary_call_count = 0
    search_retry_attempt_count = 0
    search_call_skipped_count = 0
    search_failure_diagnostics: list[dict[str, Any]] = []
    search_skipped_diagnostics: list[dict[str, Any]] = []
    search_retry_diagnostics: list[dict[str, Any]] = []
    search_transport_failed_leaf_ids: set[str] = set()
    search_result_fetch_count = 0
    search_result_fetch_skipped_count = 0
    search_result_fetch_cache_hit_count = 0
    native_research_call_count = 0
    native_candidate_fetch_count = 0
    native_candidate_fetch_skipped_count = 0
    native_research_failure_diagnostics: list[dict[str, Any]] = []
    native_research_skip_diagnostics: list[dict[str, Any]] = []
    native_research_runtime_calls: list[dict[str, Any]] = []
    native_research_trigger_diagnostics: list[dict[str, Any]] = []
    fetch_cache: dict[tuple[str, str], dict[str, Any]] = {}
    collection_started_at = time.monotonic()
    direct_fetch_started_at = collection_started_at

    for context in contexts:
        for rank, hint in enumerate(direct_urls, start=1):
            cache_key = _canonical_fetch_key(hint.get("url"), source_cutoff_timestamp)
            cache_hit = cache_key is not None and cache_key in fetch_cache
            if not cache_hit and direct_fetch_count >= max(0, policy.max_total_direct_fetches):
                direct_fetch_skipped_count += 1
                continue
            candidate = _fetch_candidate(
                context=context,
                hint=hint,
                rank=rank,
                source_cutoff_timestamp=source_cutoff_timestamp,
                browser_provider=browser_provider,
                navigation_mode="direct_url",
                search_candidate_url_ref=None,
                deterministic_direct_url_source_classes=policy.deterministic_direct_url_source_classes,
                fetch_cache=fetch_cache,
            )
            if candidate.get("canonical_fetch_cache_status") == "hit":
                direct_fetch_cache_hit_count += 1
            elif candidate.get("canonical_fetch_cache_status") == "miss":
                direct_fetch_count += 1
            result.fetched_candidates.append(candidate)

    direct_url_elapsed_seconds = max(0.0, time.monotonic() - direct_fetch_started_at)
    max_total_search_elapsed_seconds = max(0.0, float(policy.max_total_search_elapsed_seconds or 0.0))
    search_started_at = time.monotonic()
    search_deadline = search_started_at + max_total_search_elapsed_seconds if max_total_search_elapsed_seconds else None
    search_budget = _search_budget_for_case(contexts, policy)
    leaf_search_call_counts: dict[str, int] = {}
    sleep = sleep_fn or time.sleep

    if policy.broad_search_enabled:
        for context in contexts:
            variants = context.get("query_variants") if isinstance(context.get("query_variants"), list) else []
            leaf_id = str(context.get("leaf_id") or "")
            leaf_cap = _leaf_search_call_cap(context, policy)
            for variant_index, variant in enumerate(variants[: policy.max_search_variants_per_leaf]):
                if not browser_search_configured:
                    search_call_skipped_count += 1
                    search_skipped_diagnostics.append(
                        _search_query_diagnostic(
                            context,
                            variant,
                            reason_code="search_transport_unavailable",
                            detail="browser_search_provider_not_configured",
                        )
                    )
                    continue
                if leaf_id in search_transport_failed_leaf_ids:
                    search_call_skipped_count += 1
                    search_skipped_diagnostics.append(
                        _search_query_diagnostic(
                            context,
                            variant,
                            reason_code="skipped_after_provider_failure",
                            detail="provider_failure_retry_exhausted_for_leaf",
                        )
                    )
                    continue
                skip_reason = _search_skip_reason(
                    case_search_call_count=search_primary_call_count,
                    max_total_search_calls=search_budget["absolute_case_search_cap"],
                    leaf_search_call_count=leaf_search_call_counts.get(leaf_id, 0),
                    leaf_search_call_cap=leaf_cap,
                    search_deadline=search_deadline,
                )
                if skip_reason:
                    search_call_skipped_count += 1
                    elapsed_seconds = max(0.0, time.monotonic() - search_started_at)
                    search_skipped_diagnostics.append(
                        _search_query_diagnostic(
                            context,
                            variant,
                            reason_code=skip_reason,
                            detail="search_elapsed_budget_exhausted_before_leaf"
                            if skip_reason == "skipped_elapsed_budget"
                            else None,
                            elapsed_seconds=elapsed_seconds
                            if skip_reason == "skipped_elapsed_budget"
                            else None,
                            budget_seconds=max_total_search_elapsed_seconds
                            if skip_reason == "skipped_elapsed_budget"
                            else None,
                        )
                    )
                    continue
                search_primary_call_count += 1
                leaf_search_call_counts[leaf_id] = leaf_search_call_counts.get(leaf_id, 0) + 1
                search_records, attempt_failures, attempt_retry_events = _search_candidate_urls_with_retry(
                    browser_provider=browser_provider,
                    context=context,
                    variants=variants,
                    start_variant_index=variant_index,
                    searched_at=forecast_timestamp,
                    policy=policy,
                    sleep_fn=sleep,
                )
                search_call_count += 1 + sum(
                    1 for item in attempt_retry_events if item.get("event") == "local_retry"
                )
                search_retry_attempt_count += sum(
                    1 for item in attempt_retry_events if item.get("event") == "local_retry"
                )
                search_failure_diagnostics.extend(attempt_failures)
                search_retry_diagnostics.extend(attempt_retry_events)
                if any(item.get("event") == "retry_exhausted" for item in attempt_retry_events):
                    search_transport_failed_leaf_ids.add(leaf_id)
                    if not (policy.native_enabled and native_candidate_provider is not None):
                        search_retry_diagnostics.append(
                            _search_retry_diagnostic(
                                context,
                                variant,
                                event="retryable_stage_error_candidate",
                                attempt=len(attempt_retry_events),
                                max_attempts=_browser_search_max_attempts(policy),
                                failure={
                                    "retryable": True,
                                    "failure_class": "browser_search_retry_exhausted",
                                    "exception_type": None,
                                },
                                final_retry_outcome="retryable_retrieval_stage_error_candidate",
                            )
                        )
                    else:
                        search_retry_diagnostics.append(
                            _search_retry_diagnostic(
                                context,
                                variant,
                                event="deferred_to_native_discovery",
                                attempt=len(attempt_retry_events),
                                max_attempts=_browser_search_max_attempts(policy),
                                failure={
                                    "retryable": True,
                                    "failure_class": "browser_search_retry_exhausted",
                                    "exception_type": None,
                                },
                                final_retry_outcome="deferred_to_native_discovery",
                            )
                        )
                search_records = search_records[: policy.max_search_results_per_variant]
                result.search_candidate_urls.extend(search_records)
                for search_rank, record in enumerate(search_records, start=1):
                    url = record.get("url") or record.get("canonical_url")
                    cache_key = _canonical_fetch_key(url, source_cutoff_timestamp)
                    cache_hit = cache_key is not None and cache_key in fetch_cache
                    if not cache_hit and search_result_fetch_count >= max(0, policy.max_total_search_result_fetches):
                        search_result_fetch_skipped_count += 1
                        continue
                    hint = {
                        "url": url,
                        "source_ref": record.get("search_candidate_url_id") or record.get("candidate_url_ref"),
                        "source_class": None,
                        "source_class_resolution_method": None,
                        "deterministic_source_class_proof": False,
                    }
                    candidate = _fetch_candidate(
                        context=context,
                        hint=hint,
                        rank=int(record.get("rank") or search_rank),
                        source_cutoff_timestamp=source_cutoff_timestamp,
                        browser_provider=browser_provider,
                        navigation_mode="web_search",
                        search_candidate_url_ref=record.get("search_candidate_url_id") or record.get("candidate_url_ref"),
                        deterministic_direct_url_source_classes=False,
                        fetch_cache=fetch_cache,
                    )
                    if candidate.get("canonical_fetch_cache_status") == "hit":
                        search_result_fetch_cache_hit_count += 1
                    elif candidate.get("canonical_fetch_cache_status") == "miss":
                        search_result_fetch_count += 1
                    result.fetched_candidates.append(candidate)

    if policy.native_enabled:
        for context in contexts:
            variants = context.get("query_variants") if isinstance(context.get("query_variants"), list) else []
            if not variants:
                continue
            trigger_reasons = _native_discovery_trigger_reasons(
                context,
                fetched_candidates=result.fetched_candidates,
                search_transport_failed_leaf_ids=search_transport_failed_leaf_ids,
                leaf_search_call_counts=leaf_search_call_counts,
                policy=policy,
            )
            if not trigger_reasons:
                native_research_skip_diagnostics.append(
                    _native_research_diagnostic(
                        context,
                        variants[0],
                        event="native_discovery_not_needed",
                        reason_codes=["retrieval_candidates_already_present"],
                    )
                )
                continue
            if native_candidate_provider is None:
                native_research_skip_diagnostics.append(
                    _native_research_diagnostic(
                        context,
                        variants[0],
                        event="native_discovery_skipped",
                        reason_codes=["native_research_transport_not_configured", *trigger_reasons],
                    )
                )
                continue
            if native_research_call_count >= max(0, int(policy.max_native_research_calls or 0)):
                native_research_skip_diagnostics.append(
                    _native_research_diagnostic(
                        context,
                        variants[0],
                        event="native_discovery_skipped",
                        reason_codes=["skipped_native_case_cap", *trigger_reasons],
                    )
                )
                continue
            native_research_call_count += 1
            native_research_trigger_diagnostics.append(
                _native_research_diagnostic(
                    context,
                    variants[0],
                    event="native_discovery_triggered",
                    reason_codes=trigger_reasons,
                )
            )
            try:
                raw_native = native_candidate_provider(context, variants[0])
            except Exception as exc:  # noqa: BLE001 - transport boundary records safe class only
                runtime_summary = native_runtime_call_summary(getattr(exc, "runtime_call", None))
                if runtime_summary is not None:
                    native_research_runtime_calls.append(runtime_summary)
                native_research_failure_diagnostics.append(
                    _native_research_diagnostic(
                        context,
                        variants[0],
                        event="native_discovery_failed",
                        reason_codes=["native_research_transport_failed", *trigger_reasons],
                        detail=str(exc)[:500] or exc.__class__.__name__,
                        error_class=exc.__class__.__name__,
                        runtime_call=runtime_summary,
                    )
                )
                continue
            runtime_summary = _native_runtime_summary_from_provider_result(raw_native)
            if runtime_summary is not None:
                native_research_runtime_calls.append(runtime_summary)
            validation_errors = native_candidate_payload_errors(raw_native)
            if validation_errors:
                native_research_failure_diagnostics.append(
                    _native_research_diagnostic(
                        context,
                        variants[0],
                        event="native_discovery_failed",
                        reason_codes=["native_research_forbidden_or_invalid_output", *trigger_reasons],
                        detail="; ".join(validation_errors[:5]),
                        error_class="NativeResearchOutputValidationError",
                        runtime_call=runtime_summary,
                    )
                )
                continue
            native_candidates = _native_candidate_list(raw_native)
            if native_candidates:
                attempt_ref = _native_attempt_ref(raw_native, runtime_summary)
                sanitized_candidates = [
                    _sanitize_native_candidate(item, context["leaf_id"])
                    for item in native_candidates
                ]
                result.native_research_candidates.append(
                    {
                        "leaf_id": context["leaf_id"],
                        "query_variant_id": variants[0]["query_variant_id"],
                        "candidate_urls": sanitized_candidates,
                        "native_research_attempt_ref": attempt_ref,
                        "resolved_model_id": _native_resolved_model_id(raw_native, runtime_summary),
                        "discovered_at": forecast_timestamp,
                    }
                )
                for native_rank, native_candidate in enumerate(sanitized_candidates, start=1):
                    if native_candidate_fetch_count >= max(0, int(policy.max_native_candidate_fetches or 0)):
                        native_candidate_fetch_skipped_count += 1
                        continue
                    url = native_candidate.get("url") or native_candidate.get("canonical_url")
                    hint = {
                        "url": url,
                        "source_ref": attempt_ref,
                        "source_class": None,
                        "source_class_resolution_method": None,
                        "deterministic_source_class_proof": False,
                    }
                    candidate = _fetch_candidate(
                        context=context,
                        hint=hint,
                        rank=native_rank,
                        source_cutoff_timestamp=source_cutoff_timestamp,
                        browser_provider=browser_provider,
                        navigation_mode="native_gpt_research",
                        search_candidate_url_ref=None,
                        deterministic_direct_url_source_classes=False,
                        fetch_cache=fetch_cache,
                        retrieval_transport="native_gpt_research",
                        native_research_attempt_ref=attempt_ref,
                    )
                    if candidate.get("canonical_fetch_cache_status") != "hit":
                        native_candidate_fetch_count += 1
                    result.fetched_candidates.append(candidate)

    result.omitted_candidates = [
        candidate
        for candidate in result.fetched_candidates
        if candidate.get("candidate_status") in {"omitted", "rejected"}
        or candidate.get("admission_status") in {"omitted", "rejected"}
        or candidate.get("extraction_status") != "accepted"
    ]
    final_browser_provider_diagnostics = _provider_diagnostics(browser_provider)
    packet_safe_browser_provider_diagnostics = _packet_safe_provider_diagnostics(
        final_browser_provider_diagnostics
    )
    search_candidate_discovery_status = _search_candidate_discovery_status(
        policy=policy,
        browser_search_configured=browser_search_configured,
        search_call_count=search_call_count,
        search_failure_count=len(search_failure_diagnostics),
        search_candidate_url_count=len(result.search_candidate_urls),
    )
    search_failure_blocks_sufficiency = bool(
        policy.broad_search_enabled
        and (
            search_failure_diagnostics
            or (
                len(result.search_candidate_urls) <= 0
                and (
                    not browser_search_configured
                    or search_call_count > 0
                    or search_call_skipped_count > 0
                )
            )
        )
    )
    result.transport_diagnostics = {
        "schema_version": "ads-retrieval-transport-diagnostics/v1",
        "browser_provider_status": "available"
        if browser_fetch_configured or browser_search_configured
        else "unavailable",
        "browser_provider_unavailable_reason": None
        if browser_fetch_configured or browser_search_configured
        else "browser_provider_not_configured",
        "browser_fetch_configured": browser_fetch_configured,
        "browser_search_configured": browser_search_configured,
        "direct_url_candidate_count": len(result.direct_url_candidates),
        "fetched_candidate_count": len(result.fetched_candidates),
        "omitted_candidate_count": len(result.omitted_candidates),
        "search_candidate_url_count": len(result.search_candidate_urls),
        "native_research_candidate_count": len(result.native_research_candidates),
        "native_candidate_url_count": sum(
            len(item.get("candidate_urls") or [])
            for item in result.native_research_candidates
            if isinstance(item, dict)
        ),
        "native_candidate_fetch_attempt_count": native_candidate_fetch_count,
        "native_candidate_fetch_skipped_count": native_candidate_fetch_skipped_count,
        "direct_url_capture_executed": bool(result.direct_url_candidates),
        "direct_url_capture_status": "executed" if result.direct_url_candidates else "not_executed",
        "browser_search_executed": search_call_count > 0,
        "browser_search_status": _browser_search_status(
            policy=policy,
            browser_search_configured=browser_search_configured,
            search_call_count=search_call_count,
            search_failure_count=len(search_failure_diagnostics),
        ),
        "search_candidate_discovery_status": search_candidate_discovery_status,
        "search_failure_blocks_sufficiency": search_failure_blocks_sufficiency,
        "native_research_model_executed": native_research_call_count > 0,
        "native_research_status": _native_research_status(
            policy=policy,
            native_candidate_provider=native_candidate_provider,
            native_research_call_count=native_research_call_count,
            native_research_failure_count=len(native_research_failure_diagnostics),
            native_research_candidate_count=len(result.native_research_candidates),
        ),
        "native_research_call_count": native_research_call_count,
        "native_research_failure_count": len(native_research_failure_diagnostics),
        "native_research_trigger_diagnostics": native_research_trigger_diagnostics,
        "native_research_failure_diagnostics": native_research_failure_diagnostics,
        "native_research_skip_diagnostics": native_research_skip_diagnostics,
        "native_research_runtime_calls": native_research_runtime_calls,
        "native_research_transport_diagnostics": _native_transport_diagnostics(
            policy=policy,
            native_candidate_provider=native_candidate_provider,
            native_research_call_count=native_research_call_count,
            native_research_failure_diagnostics=native_research_failure_diagnostics,
            native_research_runtime_calls=native_research_runtime_calls,
            checked_at=forecast_timestamp,
        ),
        "bounded_retrieval_policy": {
            "max_direct_urls": policy.max_direct_urls,
            "max_total_direct_fetches": policy.max_total_direct_fetches,
            "max_search_variants_per_leaf": policy.max_search_variants_per_leaf,
            "max_search_results_per_variant": policy.max_search_results_per_variant,
            "max_total_search_calls": policy.max_total_search_calls,
            "effective_case_search_call_cap": search_budget["absolute_case_search_cap"],
            "leaf_aware_default_search_budget": search_budget["leaf_aware_default_search_budget"],
            "default_leaf_search_call_cap": policy.default_leaf_search_call_cap,
            "high_priority_leaf_search_call_cap": policy.high_priority_leaf_search_call_cap,
            "protected_primary_leaf_search_call_cap": policy.protected_primary_leaf_search_call_cap,
            "browser_search_retry_policy_ref": BROWSER_SEARCH_RETRY_POLICY_REF,
            "max_browser_search_attempts_per_query": _browser_search_max_attempts(policy),
            "provider_failure_retry_cap": _browser_search_max_attempts(policy) - 1,
            "browser_search_base_backoff_seconds": policy.browser_search_base_backoff_seconds,
            "browser_search_max_backoff_seconds": policy.browser_search_max_backoff_seconds,
            "max_total_search_elapsed_seconds": max_total_search_elapsed_seconds,
            "max_total_search_result_fetches": policy.max_total_search_result_fetches,
            "max_native_research_calls": policy.max_native_research_calls,
            "max_native_candidate_fetches": policy.max_native_candidate_fetches,
        },
        "direct_url_fetch_attempt_count": direct_fetch_count,
        "direct_url_fetch_skipped_count": direct_fetch_skipped_count,
        "search_call_count": search_call_count,
        "search_primary_call_count": search_primary_call_count,
        "search_retry_attempt_count": search_retry_attempt_count,
        "search_call_skipped_count": search_call_skipped_count,
        "direct_url_elapsed_seconds": round(direct_url_elapsed_seconds, 3),
        "search_elapsed_seconds": round(max(0.0, time.monotonic() - search_started_at), 3),
        "total_collection_elapsed_seconds": round(max(0.0, time.monotonic() - collection_started_at), 3),
        "search_failure_count": len(search_failure_diagnostics),
        "search_failure_diagnostics": search_failure_diagnostics,
        "search_retry_diagnostics": search_retry_diagnostics,
        "search_retry_exhausted_count": sum(
            1 for item in search_retry_diagnostics if item.get("event") == "retry_exhausted"
        ),
        "search_transport_failed_leaf_ids": sorted(search_transport_failed_leaf_ids),
        "search_skipped_diagnostics": search_skipped_diagnostics,
        "search_leaf_budgets": [
            {
                "leaf_id": str(context.get("leaf_id") or ""),
                "leaf_search_call_cap": _leaf_search_call_cap(context, policy),
                "primary_search_call_count": leaf_search_call_counts.get(str(context.get("leaf_id") or ""), 0),
                "protected_primary_required": _context_requires_protected_primary(context),
                "high_priority": _context_is_high_priority(context),
            }
            for context in contexts
        ],
        "search_result_fetch_attempt_count": search_result_fetch_count,
        "search_result_fetch_skipped_count": search_result_fetch_skipped_count,
        "canonical_fetch_cache": {
            "schema_version": "canonical-fetch-cache-summary/v1",
            "cache_key": "canonical_url_plus_cutoff",
            "unique_fetch_count": len(fetch_cache),
            "direct_url_cache_hit_count": direct_fetch_cache_hit_count,
            "search_result_cache_hit_count": search_result_fetch_cache_hit_count,
            "cache_hit_count": direct_fetch_cache_hit_count + search_result_fetch_cache_hit_count,
            "cached_fetch_refs": [
                _canonical_fetch_ref(canonical_url, cutoff)
                for canonical_url, cutoff in sorted(fetch_cache)
            ],
        },
        "bounded_retrieval_reason_codes": _bounded_reason_codes(
            direct_fetch_skipped_count=direct_fetch_skipped_count,
            search_call_skipped_count=search_call_skipped_count,
            search_skipped_diagnostics=search_skipped_diagnostics,
            search_failure_count=len(search_failure_diagnostics),
            search_result_fetch_skipped_count=search_result_fetch_skipped_count,
            browser_provider_diagnostics=final_browser_provider_diagnostics,
        ),
        "browser_fetch_authority": "url_fetch_extraction_only",
        "deterministic_admission_authority": "build_live_retrieval_packet_from_candidates",
    }
    if packet_safe_browser_provider_diagnostics:
        result.transport_diagnostics["browser_provider_diagnostics"] = packet_safe_browser_provider_diagnostics
    return result


def _native_discovery_trigger_reasons(
    context: dict[str, Any],
    *,
    fetched_candidates: list[dict[str, Any]],
    search_transport_failed_leaf_ids: set[str],
    leaf_search_call_counts: dict[str, int],
    policy: RetrievalProviderPolicy,
) -> list[str]:
    leaf_id = str(context.get("leaf_id") or "")
    reasons: list[str] = []
    if leaf_id in search_transport_failed_leaf_ids:
        reasons.append("browser_search_failed")
    if not _leaf_has_meaningful_fetched_candidate(fetched_candidates, leaf_id):
        reasons.append("meaningful_snippet_count_zero")
    if _context_requires_protected_primary(context) and not _leaf_has_protected_primary_candidate(fetched_candidates, leaf_id):
        reasons.append("protected_primary_missing")
    if (
        leaf_search_call_counts.get(leaf_id, 0) >= _leaf_search_call_cap(context, policy)
        and not _leaf_has_meaningful_fetched_candidate(fetched_candidates, leaf_id)
    ):
        reasons.append("leaf_search_budget_exhausted_without_source_diversity")
    return sorted(set(reasons))


def _leaf_has_meaningful_fetched_candidate(candidates: list[dict[str, Any]], leaf_id: str) -> bool:
    for candidate in candidates:
        if str(candidate.get("leaf_id") or "") != leaf_id:
            continue
        if candidate.get("extraction_status") != "accepted":
            continue
        content = " ".join(str(candidate.get("content") or "").split())
        if len(content) >= 80:
            return True
    return False


def _leaf_has_protected_primary_candidate(candidates: list[dict[str, Any]], leaf_id: str) -> bool:
    for candidate in candidates:
        if str(candidate.get("leaf_id") or "") != leaf_id:
            continue
        if candidate.get("extraction_status") != "accepted":
            continue
        if candidate.get("source_class") == "official_or_primary" or candidate.get("official_source_hints"):
            return True
    return False


def _native_research_diagnostic(
    context: dict[str, Any],
    variant: dict[str, Any],
    *,
    event: str,
    reason_codes: list[str],
    detail: str | None = None,
    error_class: str | None = None,
    runtime_call: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "schema_version": NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION,
        "event": event,
        "component": "native_research_candidate_discovery",
        "leaf_id": context.get("leaf_id"),
        "parent_branch_id": context.get("parent_branch_id"),
        "query_context_ref": context.get("query_context_ref"),
        "query_variant_id": variant.get("query_variant_id"),
        "query_role": variant.get("query_role"),
        "reason_codes": list(reason_codes),
        "authority_boundary": {
            "candidate_discovery_only": True,
            "source_metadata_final_authority": False,
            "claim_family_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
            "forecast_authority": False,
        },
    }
    if detail:
        diagnostic["detail"] = detail[:500]
    if error_class:
        diagnostic["error_class"] = str(error_class)[:160]
    if runtime_call is not None:
        diagnostic["runtime_call"] = runtime_call
    return diagnostic


def _native_runtime_summary_from_provider_result(raw_native: Any) -> dict[str, Any] | None:
    if not isinstance(raw_native, dict):
        return None
    runtime = raw_native.get("model_runtime_call") or raw_native.get("native_research_runtime_call")
    return native_runtime_call_summary(runtime if isinstance(runtime, dict) else None)


def _native_attempt_ref(raw_native: Any, runtime_summary: dict[str, Any] | None) -> str | None:
    if runtime_summary and runtime_summary.get("runtime_call_id"):
        return str(runtime_summary["runtime_call_id"])
    if isinstance(raw_native, dict):
        for key in ("native_research_attempt_ref", "attempt_ref"):
            if raw_native.get(key):
                return str(raw_native[key])
    return None


def _native_resolved_model_id(raw_native: Any, runtime_summary: dict[str, Any] | None) -> str:
    if runtime_summary and runtime_summary.get("resolved_model_id"):
        return str(runtime_summary["resolved_model_id"])
    if isinstance(raw_native, dict) and raw_native.get("resolved_model_id"):
        return str(raw_native["resolved_model_id"])
    return "gpt-5.5-high"


def _native_transport_diagnostics(
    *,
    policy: RetrievalProviderPolicy,
    native_candidate_provider: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
    native_research_call_count: int,
    native_research_failure_diagnostics: list[dict[str, Any]],
    native_research_runtime_calls: list[dict[str, Any]],
    checked_at: str,
) -> list[dict[str, Any]]:
    if not policy.native_enabled:
        return []
    availability_status = "available" if native_candidate_provider is not None else "unavailable"
    unavailable_reason = None if native_candidate_provider is not None else "native_research_transport_not_configured"
    if native_research_failure_diagnostics and native_research_call_count > 0:
        availability_status = "partial"
    return [
        {
            "schema_version": NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION,
            "artifact_type": "native_research_transport_diagnostic",
            "availability_status": availability_status,
            "unavailable_reason": unavailable_reason,
            "checked_at": checked_at,
            "model_lane_id": "native_research_candidate_discovery",
            "resolved_model_id": "gpt-5.5-high",
            "research_transport": "native_gpt_research",
            "native_research_call_count": native_research_call_count,
            "native_research_failure_count": len(native_research_failure_diagnostics),
            "runtime_call_refs": [
                str(item.get("runtime_call_id"))
                for item in native_research_runtime_calls
                if item.get("runtime_call_id")
            ],
            "candidate_discovery_role": "fallback_url_discovery_only",
            "native_output_authority": {
                "candidate_discovery": True,
                "source_metadata_final_authority": False,
                "claim_family_final_authority": False,
                "temporal_safety_final_authority": False,
                "research_sufficiency_authority": False,
                "forecast_authority": False,
            },
        }
    ]


def _bounded_reason_codes(
    *,
    direct_fetch_skipped_count: int,
    search_call_skipped_count: int,
    search_skipped_diagnostics: list[dict[str, Any]],
    search_failure_count: int,
    search_result_fetch_skipped_count: int,
    browser_provider_diagnostics: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if direct_fetch_skipped_count:
        reasons.append("direct_url_fetch_limit_reached")
    if search_call_skipped_count:
        skipped_reasons = [
            str(item.get("reason_code"))
            for item in search_skipped_diagnostics
            if isinstance(item, dict) and item.get("reason_code")
        ]
        skipped_reasons.extend(
            str(item.get("legacy_reason_code"))
            for item in search_skipped_diagnostics
            if isinstance(item, dict) and item.get("legacy_reason_code")
        )
        reasons.extend(skipped_reasons or ["search_call_limit_reached"])
    if search_failure_count:
        reasons.append("search_provider_failure_recorded")
    if search_result_fetch_skipped_count:
        reasons.append("search_result_fetch_limit_reached")
    if browser_provider_diagnostics.get("last_search_error"):
        reasons.append("search_provider_error_recorded")
    if browser_provider_diagnostics.get("last_fetch_error"):
        reasons.append("fetch_provider_error_recorded")
    return reasons


def _packet_safe_provider_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Keep provider diagnostics in RET packets free of authority assertions."""

    safe: dict[str, Any] = {}
    for key, value in diagnostics.items():
        if key == "authority_boundary":
            safe["provider_authority_status"] = "non_authoritative_transport_only"
            continue
        lowered = key.lower()
        if any(fragment in lowered for fragment in ("authority", "certifies_", "probability", "scae_delta")):
            continue
        safe[key] = value
    return safe


def _collect_direct_url_hints(
    case_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    amrg_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for path in (
        ("official_source_hints",),
        ("protected_primary_source_hints",),
        ("source_of_truth_hints",),
        ("source_of_truth_urls",),
        ("market_reality_constraints", "source_of_truth_hints"),
        ("market_reality_constraints", "protected_primary_source_hints"),
        ("source_registry",),
        ("expected_sources",),
    ):
        for url, source_ref in _urls_at_path(evidence_packet, path, "evidence_packet"):
            _add_hint(
                hints,
                url,
                source_ref=source_ref,
                source_class="official_or_primary",
                source_class_resolution_method="official_url_hint",
            )
    for root_name, root in (
        ("evidence_packet.market_rules", evidence_packet.get("market_rules")),
        ("case_contract.market_rules", case_contract.get("market_rules")),
        ("case_contract.resolution_rules", case_contract.get("resolution_rules")),
        ("case_contract.market_identity", case_contract.get("market_identity")),
        ("evidence_packet.market_identity", evidence_packet.get("market_identity")),
    ):
        for url, source_ref in _urls_from_resolution_fields(root, root_name):
            _add_hint(
                hints,
                url,
                source_ref=source_ref,
                source_class="market_rules_or_resolution_source",
                source_class_resolution_method="market_rules_resolution_url",
            )
    for root_name, root in (
        ("case_contract.market_identity", case_contract.get("market_identity")),
        ("case_contract.market_rules", case_contract.get("market_rules")),
        ("case_contract.resolution_rules", case_contract.get("resolution_rules")),
        ("evidence_packet.market_identity", evidence_packet.get("market_identity")),
        ("evidence_packet.market_rules", evidence_packet.get("market_rules")),
        ("evidence_packet.market_reality_constraints", evidence_packet.get("market_reality_constraints")),
    ):
        for url, source_ref in _urls_from_free_text(root, root_name):
            _add_hint(
                hints,
                url,
                source_ref=source_ref,
                source_class="market_rules_or_resolution_source",
                source_class_resolution_method="market_rules_resolution_url",
            )
    for url, source_ref in _amrg_url_hints(amrg_context):
        _add_hint(
            hints,
            url,
            source_ref=source_ref,
            source_class=None,
            source_class_resolution_method=None,
            deterministic_source_class_proof=False,
        )
    _add_hint(
        hints,
        _market_url(case_contract),
        source_ref="case_contract.market_url",
        source_class="market_rules_or_resolution_source",
        source_class_resolution_method="market_platform_resolution_url",
    )
    return _dedupe_hints(hints)


def _fetch_candidate(
    *,
    context: dict[str, Any],
    hint: dict[str, Any],
    rank: int,
    source_cutoff_timestamp: str,
    browser_provider: Any | None,
    navigation_mode: str,
    search_candidate_url_ref: str | None,
    deterministic_direct_url_source_classes: bool,
    fetch_cache: dict[tuple[str, str], dict[str, Any]] | None = None,
    retrieval_transport: str = "browser",
    native_research_attempt_ref: str | None = None,
) -> dict[str, Any]:
    url = str(hint.get("url") or "")
    canonical_url = _canonicalize_url(url)
    base = {
        "leaf_id": context["leaf_id"],
        "parent_branch_id": context.get("parent_branch_id"),
        "retrieval_transport": retrieval_transport,
        "navigation_mode": navigation_mode,
        "requested_url": url,
        "final_url": canonical_url or url,
        "canonical_url": canonical_url,
        "result_rank": rank,
        "direct_url_source_ref": hint.get("source_ref") if navigation_mode == "direct_url" else None,
        "search_candidate_url_ref": search_candidate_url_ref,
        "native_research_attempt_ref": native_research_attempt_ref
        if retrieval_transport == "native_gpt_research"
        else None,
    }
    if not _valid_http_url(url):
        return {
            **base,
            "final_url": "",
            "canonical_url": "",
            "extraction_status": "rejected",
            "candidate_status": "rejected",
            "admission_status": "rejected",
            "omission_reason_codes": ["malformed_url"],
            "temporal_gate_status": "unknown_not_counted",
        }
    cache_key = _canonical_fetch_key(canonical_url, source_cutoff_timestamp)
    cache_status = "disabled"
    if fetch_cache is not None and cache_key is not None and cache_key in fetch_cache:
        fetched = copy.deepcopy(fetch_cache[cache_key])
        cache_status = "hit"
    else:
        fetched = _provider_fetch(browser_provider, url)
        if fetch_cache is not None and cache_key is not None:
            fetch_cache[cache_key] = copy.deepcopy(fetched)
            cache_status = "miss"
    fetched = _strip_authority_fields(fetched)
    extraction_status = str(fetched.get("extraction_status") or fetched.get("status") or "accepted")
    if extraction_status not in {"accepted", "rejected", "paywalled", "blocked", "duplicate", "temporal_fail"}:
        extraction_status = "rejected"
    final_url = _canonicalize_url(fetched.get("final_url"), fetched.get("url"), canonical_url) or canonical_url
    fetched_content = _content_from_fetch(fetched)
    source_time = _source_timestamp(fetched)
    published_at = _first_source_timestamp(fetched, ("source_published_at", "published_at"))
    updated_at = _first_source_timestamp(fetched, ("source_updated_at", "source_authored_at"))
    observed_at = _first_source_timestamp(fetched, ("source_observed_at",))
    source_freshness_time = published_at or updated_at
    inferred_observed_at = None
    reason_codes = list(fetched.get("reason_codes") or fetched.get("omission_reason_codes") or [])
    if extraction_status == "accepted" and not fetched_content:
        extraction_status = "rejected"
        reason_codes.append("retrieved_source_text_missing")
    if extraction_status == "accepted" and not source_time:
        if _direct_hint_allows_inferred_source_time(
            hint,
            navigation_mode=navigation_mode,
            deterministic_direct_url_source_classes=deterministic_direct_url_source_classes,
        ):
            inferred_observed_at = _iso_before(source_cutoff_timestamp)
            source_time = inferred_observed_at
            reason_codes.append("source_time_inferred_from_pre_dispatch_direct_url_hint")
        else:
            extraction_status = "rejected"
            reason_codes.append("source_time_unknown_not_admitted_by_transport_adapter")
            if fetched_content:
                reason_codes.append("source_time_unknown_with_fetched_content")
    if extraction_status == "accepted" and _timestamp_at_or_after(source_time, source_cutoff_timestamp):
        extraction_status = "temporal_fail"
        reason_codes.append("post_cutoff_source_time")
    candidate = {
        **base,
        "final_url": final_url,
        "canonical_url": final_url,
        "canonical_fetch_ref": _canonical_fetch_ref(canonical_url, source_cutoff_timestamp),
        "canonical_fetch_cache_status": cache_status,
        "canonical_fetch_cache_key": "canonical_url_plus_cutoff",
        "extraction_status": extraction_status,
        "source_published_at": published_at,
        "source_observed_at": observed_at or inferred_observed_at,
        "source_updated_at": updated_at,
        "source_freshness_eligible": source_freshness_time is not None,
        "source_time_semantics": "publication_or_update"
        if source_freshness_time
        else "observed_or_inferred_only"
        if observed_at or inferred_observed_at
        else "unknown",
        "captured_at": fetched.get("captured_at") or _iso_before(source_cutoff_timestamp),
        "content": fetched_content,
        "content_artifact_ref": fetched.get("content_artifact_ref"),
        "content_sha256": fetched.get("content_sha256") or _content_sha256(fetched_content),
        "retrieval_score": float(fetched.get("retrieval_score") or 1.0),
        "transport_authority_boundary": {
            "browser_fetch_certifies_source_class": False,
            "browser_fetch_certifies_claim_family": False,
            "browser_fetch_certifies_temporal_safety": False,
            "browser_fetch_certifies_sufficiency": False,
            "native_research_certifies_source_class": False,
            "native_research_certifies_claim_family": False,
            "native_research_certifies_temporal_safety": False,
            "native_research_certifies_sufficiency": False,
        },
    }
    if extraction_status == "accepted":
        candidate["admission_status"] = "admitted"
        candidate["temporal_gate_status"] = "pass"
        if "source_time_inferred_from_pre_dispatch_direct_url_hint" in reason_codes:
            candidate["admission_reason_code"] = "pre_dispatch_direct_url_source_time_inferred"
        else:
            candidate["admission_reason_code"] = "transport_candidate_requires_deterministic_validation"
        boi_registry_match = _deterministic_boi_official_source_match(final_url, context)
        registry_match = _deterministic_source_class_registry_match(final_url)
        boi_non_matching_context = _is_boi_official_url(final_url) and boi_registry_match is None
        if boi_registry_match:
            candidate["source_class"] = boi_registry_match["source_class"]
            candidate["deterministic_source_class_proof"] = True
            candidate["source_class_resolution_method"] = "bank_of_israel_official_domain_path"
            candidate["source_class_registry_id"] = boi_registry_match["registry_id"]
            candidate["source_class_registry_match"] = boi_registry_match["matched_domain"]
            candidate["official_source_hints"] = [url]
        elif registry_match and registry_match["source_class"] == "official_or_primary":
            candidate["source_class"] = registry_match["source_class"]
            candidate["deterministic_source_class_proof"] = True
            candidate["source_class_resolution_method"] = "deterministic_url_registry"
            candidate["source_class_registry_id"] = registry_match["registry_id"]
            candidate["source_class_registry_match"] = registry_match["matched_domain"]
            candidate["official_source_hints"] = [url]
        elif deterministic_direct_url_source_classes and hint.get("source_class") and not boi_non_matching_context:
            candidate["source_class"] = hint["source_class"]
            candidate["deterministic_source_class_proof"] = True
            candidate["source_class_resolution_method"] = hint.get("source_class_resolution_method")
            candidate["official_source_hints"] = [url] if hint["source_class"] == "official_or_primary" else []
            candidate["market_resolution_url"] = url if hint["source_class"] == "market_rules_or_resolution_source" else None
        elif registry_match:
            candidate["source_class"] = registry_match["source_class"]
            candidate["deterministic_source_class_proof"] = True
            candidate["source_class_resolution_method"] = "deterministic_url_registry"
            candidate["source_class_registry_id"] = registry_match["registry_id"]
            candidate["source_class_registry_match"] = registry_match["matched_domain"]
    else:
        candidate["candidate_status"] = "omitted" if extraction_status == "duplicate" else "rejected"
        candidate["admission_status"] = "rejected"
        candidate["temporal_gate_status"] = "fail" if extraction_status == "temporal_fail" else "unknown_not_counted"
        candidate["omission_reason_codes"] = reason_codes or [f"extraction_{extraction_status}"]
    return candidate


def _direct_hint_allows_inferred_source_time(
    hint: dict[str, Any],
    *,
    navigation_mode: str,
    deterministic_direct_url_source_classes: bool,
) -> bool:
    if navigation_mode != "direct_url" or not deterministic_direct_url_source_classes:
        return False
    if hint.get("deterministic_source_class_proof") is False:
        return False
    if hint.get("source_class") not in {"official_or_primary", "market_rules_or_resolution_source"}:
        return False
    source_ref = str(hint.get("source_ref") or "")
    return source_ref.startswith(("case_contract.", "evidence_packet."))


def _provider_fetch(browser_provider: Any | None, url: str) -> dict[str, Any]:
    if browser_provider is None or not hasattr(browser_provider, "fetch_url"):
        return {
            "url": url,
            "extraction_status": "rejected",
            "reason_codes": ["browser_provider_not_configured"],
        }
    fetched = browser_provider.fetch_url(url)
    if not isinstance(fetched, dict):
        return {
            "url": url,
            "extraction_status": "rejected",
            "reason_codes": ["browser_provider_returned_non_object"],
        }
    return fetched


def _deterministic_source_class_registry_match(url: str) -> dict[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    for entry in DETERMINISTIC_SOURCE_CLASS_URL_REGISTRY:
        source_class = str(entry.get("source_class") or "")
        if source_class not in {
            "official_or_primary",
            "independent_secondary",
            "expert_or_specialist",
            "primary_reporting",
        }:
            continue
        for suffix in entry.get("domain_suffixes", ()):
            normalized_suffix = str(suffix).lower().removeprefix("www.")
            if host == normalized_suffix or host.endswith(f".{normalized_suffix}"):
                return {
                    "registry_id": str(entry["registry_id"]),
                    "matched_domain": normalized_suffix,
                    "source_class": source_class,
                }
    return None


def _is_boi_official_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in BOI_OFFICIAL_DOMAIN_SUFFIXES):
        return False
    path = parsed.path.lower() or "/"
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in BOI_OFFICIAL_PATH_PREFIXES)


def _context_requires_boi_fact(context: dict[str, Any]) -> bool:
    fields = context.get("required_evidence_fields") if isinstance(context.get("required_evidence_fields"), list) else []
    terms = context.get("market_component_terms") if isinstance(context.get("market_component_terms"), list) else []
    haystack = " ".join(
        str(value)
        for value in [
            context.get("leaf_question"),
            context.get("macro_question"),
            context.get("purpose"),
            *fields,
            *terms,
        ]
        if value
    ).lower()
    return any(term in haystack for term in BOI_CONTEXT_TERMS)


def _deterministic_boi_official_source_match(url: str, context: dict[str, Any]) -> dict[str, str] | None:
    if not _is_boi_official_url(url) or not _context_requires_boi_fact(context):
        return None
    return {
        "registry_id": "ads-static-official-source-registry/bank-of-israel",
        "matched_domain": "boi.org.il",
        "source_class": "official_or_primary",
    }


def _provider_diagnostics(browser_provider: Any | None) -> dict[str, Any]:
    if browser_provider is None or not hasattr(browser_provider, "provider_diagnostics"):
        return {}
    diagnostics = browser_provider.provider_diagnostics()
    return _sanitize_provider_diagnostics(diagnostics) if isinstance(diagnostics, dict) else {}


def _sanitize_provider_diagnostics(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in RETRIEVAL_DIAGNOSTIC_FORBIDDEN_KEY_FRAGMENTS):
                continue
            sanitized[key] = _sanitize_provider_diagnostics(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_provider_diagnostics(item) for item in value]
    return value


def _provider_capability_configured(
    browser_provider: Any | None,
    method_name: str,
    diagnostics: dict[str, Any],
    diagnostic_key: str,
) -> bool:
    if browser_provider is None or not hasattr(browser_provider, method_name):
        return False
    if diagnostic_key in diagnostics:
        return bool(diagnostics.get(diagnostic_key))
    return True


def _provider_last_search_error(browser_provider: Any | None) -> str | None:
    diagnostics = _provider_diagnostics(browser_provider)
    error = diagnostics.get("last_search_error")
    if error is None:
        error = getattr(browser_provider, "last_search_error", None)
    text = str(error or "").strip()
    return text[:500] if text else None


def _context_requires_protected_primary(context: dict[str, Any]) -> bool:
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    return bool(targets.get("protected_primary_required") is True)


def _context_is_high_priority(context: dict[str, Any]) -> bool:
    purpose = str(context.get("purpose") or "")
    role = str(context.get("leaf_temporal_role") or "")
    targets = context.get("breadth_targets") if isinstance(context.get("breadth_targets"), dict) else {}
    source_targets = targets.get("source_class_targets") if isinstance(targets.get("source_class_targets"), list) else []
    return (
        role == "pre_resolution_forecast_driver"
        or purpose in {"source_of_truth", "resolution_mechanics", "direct_evidence", "catalyst"}
        or "official_or_primary" in source_targets
    )


def _leaf_search_call_cap(context: dict[str, Any], policy: RetrievalProviderPolicy) -> int:
    default_cap = max(1, int(policy.default_leaf_search_call_cap or 1))
    if _context_requires_protected_primary(context):
        return max(default_cap, int(policy.protected_primary_leaf_search_call_cap or default_cap))
    if _context_is_high_priority(context):
        return max(default_cap, int(policy.high_priority_leaf_search_call_cap or default_cap))
    return default_cap


def _search_budget_for_case(
    contexts: list[dict[str, Any]],
    policy: RetrievalProviderPolicy,
) -> dict[str, Any]:
    explicit_cap = max(0, int(policy.max_total_search_calls or 0))
    use_dynamic_default = (
        bool(policy.leaf_aware_default_search_budget)
        and int(policy.max_total_search_calls or 0) == LEGACY_DEFAULT_MAX_TOTAL_SEARCH_CALLS
    )
    if use_dynamic_default:
        cap = min(24, max(8, len(contexts) * 2))
    else:
        cap = explicit_cap
    return {
        "absolute_case_search_cap": cap,
        "legacy_max_total_search_calls": explicit_cap,
        "leaf_aware_default_search_budget": use_dynamic_default,
    }


def _browser_search_max_attempts(policy: RetrievalProviderPolicy) -> int:
    configured = int(policy.max_browser_search_attempts_per_query or 1)
    return max(1, configured)


def _classify_browser_search_failure(exc: Exception | None = None, *, provider_error: str | None = None) -> dict[str, Any]:
    text = str(provider_error if provider_error is not None else exc or "").lower()
    exc_type = type(exc).__name__ if exc is not None else "ProviderReportedSearchError"
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return {"retryable": True, "failure_class": "timeout", "exception_type": exc_type}
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return {"retryable": True, "failure_class": "connection_reset", "exception_type": exc_type}
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return {"retryable": True, "failure_class": "rate_limit", "exception_type": exc_type}
    if any(marker in text for marker in ("temporar", "try again", "502", "503", "504", "gateway")):
        return {"retryable": True, "failure_class": "transient_provider_error", "exception_type": exc_type}
    if provider_error:
        return {"retryable": True, "failure_class": "provider_reported_search_error", "exception_type": exc_type}
    return {"retryable": False, "failure_class": "non_retryable_search_failure", "exception_type": exc_type}


def _browser_search_backoff(
    *,
    context: dict[str, Any],
    variant: dict[str, Any],
    attempt: int,
    failure_class: str,
    policy: RetrievalProviderPolicy,
) -> tuple[float, str, list[float]]:
    raw = min(
        float(policy.browser_search_max_backoff_seconds or 0.0),
        float(policy.browser_search_base_backoff_seconds or 0.0) * (2 ** max(0, attempt - 1)),
    )
    jitter_upper = max(0.0, raw * max(0.0, float(policy.browser_search_jitter_fraction or 0.0)))
    seed_material = {
        "policy_ref": BROWSER_SEARCH_RETRY_POLICY_REF,
        "leaf_id": context.get("leaf_id"),
        "query_variant_id": variant.get("query_variant_id"),
        "attempt": attempt,
        "failure_class": failure_class,
    }
    digest = hashlib.sha256(repr(seed_material).encode("utf-8")).hexdigest()
    unit = int(digest[:12], 16) / float(0xFFFFFFFFFFFF)
    backoff = raw + (unit * jitter_upper)
    return round(backoff, 3), digest[:16], [0.0, round(jitter_upper, 3)]


def _search_retry_diagnostic(
    context: dict[str, Any],
    variant: dict[str, Any],
    *,
    event: str,
    attempt: int,
    max_attempts: int,
    failure: dict[str, Any] | None = None,
    backoff_seconds: float | None = None,
    jitter_seed: str | None = None,
    jitter_range_seconds: list[float] | None = None,
    final_retry_outcome: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": BROWSER_SEARCH_RETRY_DIAGNOSTIC_SCHEMA_VERSION,
        "event": event,
        "component": "browser_search",
        "leaf_id": context.get("leaf_id"),
        "parent_branch_id": context.get("parent_branch_id"),
        "query_variant_id": variant.get("query_variant_id"),
        "query_role": variant.get("query_role"),
        "attempt": attempt,
        "max_attempts": max_attempts,
        "failure_retryable": bool(failure.get("retryable")) if isinstance(failure, dict) else False,
        "failure_class": failure.get("failure_class") if isinstance(failure, dict) else None,
        "exception_type": failure.get("exception_type") if isinstance(failure, dict) else None,
        "backoff_seconds": backoff_seconds,
        "jitter_seed": jitter_seed,
        "jitter_range_seconds": jitter_range_seconds or [0.0, 0.0],
        "retry_policy_ref": BROWSER_SEARCH_RETRY_POLICY_REF,
        "final_retry_outcome": final_retry_outcome,
    }


def _search_skip_reason(
    *,
    case_search_call_count: int,
    max_total_search_calls: int,
    leaf_search_call_count: int,
    leaf_search_call_cap: int,
    search_deadline: float | None,
) -> str | None:
    if max_total_search_calls <= 0:
        return "search_call_cap_zero"
    if search_deadline is not None and time.monotonic() >= search_deadline:
        return "skipped_elapsed_budget"
    if case_search_call_count >= max_total_search_calls:
        return "skipped_global_case_cap"
    if leaf_search_call_count >= leaf_search_call_cap:
        return "skipped_leaf_cap"
    return None


def _search_query_diagnostic(
    context: dict[str, Any],
    variant: dict[str, Any],
    *,
    reason_code: str,
    detail: str | None = None,
    elapsed_seconds: float | None = None,
    budget_seconds: float | None = None,
    error_class: str | None = None,
) -> dict[str, Any]:
    legacy_reason_aliases = {
        "skipped_global_case_cap": "search_call_limit_reached",
        "skipped_leaf_cap": "search_call_limit_reached",
        "skipped_elapsed_budget": "search_elapsed_budget_exhausted",
    }
    diagnostic = {
        "leaf_id": context.get("leaf_id"),
        "parent_branch_id": context.get("parent_branch_id"),
        "query_variant_id": variant.get("query_variant_id"),
        "query_role": variant.get("query_role"),
        "reason_code": reason_code,
    }
    if reason_code in legacy_reason_aliases:
        diagnostic["legacy_reason_code"] = legacy_reason_aliases[reason_code]
    if detail:
        diagnostic["detail"] = detail[:500]
    if error_class:
        diagnostic["error_class"] = str(error_class)[:160]
    if elapsed_seconds is not None:
        diagnostic["elapsed_seconds"] = round(float(elapsed_seconds), 3)
    if budget_seconds is not None:
        diagnostic["budget_seconds"] = round(float(budget_seconds), 3)
    return diagnostic


def _search_candidate_urls_with_retry(
    *,
    browser_provider: Any | None,
    context: dict[str, Any],
    variants: list[dict[str, Any]],
    start_variant_index: int,
    searched_at: str,
    policy: RetrievalProviderPolicy,
    sleep_fn: Callable[[float], None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    max_attempts = _browser_search_max_attempts(policy)
    failures: list[dict[str, Any]] = []
    retry_events: list[dict[str, Any]] = []
    if not variants:
        return [], failures, retry_events
    for attempt in range(1, max_attempts + 1):
        selected_variant = variants[min(start_variant_index + attempt - 1, len(variants) - 1)]
        call_started_at = time.monotonic()
        try:
            search_records = _search_candidate_urls(
                browser_provider,
                context,
                selected_variant,
                searched_at=searched_at,
            )
        except Exception as exc:
            search_records = []
            elapsed_seconds = max(0.0, time.monotonic() - call_started_at)
            failure = _classify_browser_search_failure(exc)
            failures.append(
                _search_query_diagnostic(
                    context,
                    selected_variant,
                    reason_code="browser_provider_search_exception",
                    detail=str(exc)[:500] or exc.__class__.__name__,
                    elapsed_seconds=elapsed_seconds,
                    error_class=exc.__class__.__name__,
                )
            )
        else:
            elapsed_seconds = max(0.0, time.monotonic() - call_started_at)
            provider_error = _provider_last_search_error(browser_provider)
            if provider_error and not search_records:
                failure = _classify_browser_search_failure(provider_error=provider_error)
                failures.append(
                    _search_query_diagnostic(
                        context,
                        selected_variant,
                        reason_code="browser_provider_search_failed",
                        detail=provider_error,
                        elapsed_seconds=elapsed_seconds,
                        error_class="ProviderReportedSearchError",
                    )
                )
            else:
                if attempt > 1:
                    retry_events.append(
                        _search_retry_diagnostic(
                            context,
                            selected_variant,
                            event="retry_succeeded",
                            attempt=attempt,
                            max_attempts=max_attempts,
                            final_retry_outcome="succeeded_after_retry",
                        )
                    )
                return search_records, failures, retry_events
        if not failure["retryable"] or attempt >= max_attempts:
            retry_events.append(
                _search_retry_diagnostic(
                    context,
                    selected_variant,
                    event="retry_exhausted" if failure["retryable"] else "retry_not_attempted",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    failure=failure,
                    final_retry_outcome="exhausted" if failure["retryable"] else "non_retryable_failure",
                )
            )
            return [], failures, retry_events
        backoff_seconds, jitter_seed, jitter_range_seconds = _browser_search_backoff(
            context=context,
            variant=selected_variant,
            attempt=attempt,
            failure_class=str(failure["failure_class"]),
            policy=policy,
        )
        retry_events.append(
            _search_retry_diagnostic(
                context,
                selected_variant,
                event="local_retry",
                attempt=attempt,
                max_attempts=max_attempts,
                failure=failure,
                backoff_seconds=backoff_seconds,
                jitter_seed=jitter_seed,
                jitter_range_seconds=jitter_range_seconds,
                final_retry_outcome="retry_scheduled",
            )
        )
        sleep_fn(backoff_seconds)
    return [], failures, retry_events


def _search_candidate_urls(browser_provider: Any | None, context: dict[str, Any], variant: dict[str, Any], *, searched_at: str) -> list[dict[str, Any]]:
    if browser_provider is None or not hasattr(browser_provider, "search_candidate_urls"):
        return []
    records = browser_provider.search_candidate_urls(context, variant, searched_at=searched_at)
    if not isinstance(records, list):
        return []
    return [
        _materialize_search_candidate_record(
            context,
            variant,
            record,
            fallback_rank=index,
            searched_at=searched_at,
            provider_id=_search_provider_id(browser_provider),
        )
        for index, record in enumerate(records, start=1)
        if isinstance(record, dict)
    ]


def _search_provider_id(browser_provider: Any | None) -> str:
    from researcher_swarm.retrieval import OPENCLAW_BROWSER_PROVIDER_ID

    diagnostics = _provider_diagnostics(browser_provider)
    provider_id = str(
        diagnostics.get("provider_id")
        or getattr(browser_provider, "provider_id", "")
        or OPENCLAW_BROWSER_PROVIDER_ID
    ).strip()
    return provider_id or OPENCLAW_BROWSER_PROVIDER_ID


def _materialize_search_candidate_record(
    context: dict[str, Any],
    variant: dict[str, Any],
    record: dict[str, Any],
    *,
    fallback_rank: int,
    searched_at: str,
    provider_id: str,
) -> dict[str, Any]:
    from researcher_swarm.retrieval import SEARCH_CANDIDATE_URL_SCHEMA_VERSION, build_search_candidate_url

    if record.get("schema_version") == SEARCH_CANDIDATE_URL_SCHEMA_VERSION:
        return dict(record)
    return build_search_candidate_url(
        context,
        variant,
        rank=int(record.get("rank") or record.get("result_rank") or fallback_rank),
        url=str(record.get("url") or record.get("canonical_url") or ""),
        title=str(record.get("title") or ""),
        snippet=str(record.get("snippet") or ""),
        provider_id=str(record.get("provider_id") or provider_id),
        searched_at=str(record.get("searched_at") or searched_at),
        result_source=str(record.get("result_source") or "configured_browser_search_provider"),
        query_role=str(record.get("query_role") or variant.get("query_role") or "primary_leaf_retrieval"),
    )


def _strip_authority_fields(value: dict[str, Any]) -> dict[str, Any]:
    stripped: dict[str, Any] = {}
    for key, item in value.items():
        if key in SOURCE_AUTHORITY_FIELDS:
            continue
        lowered = key.lower()
        if any(fragment in lowered for fragment in ("sufficiency", "forecast_probability", "scae_delta")):
            continue
        stripped[key] = item
    return stripped


def _sanitize_native_candidate(raw: dict[str, Any], leaf_id: str) -> dict[str, Any]:
    clean = {key: raw.get(key) for key in NATIVE_ALLOWED_FIELDS if key in raw}
    if not clean.get("url"):
        clean["url"] = clean.get("candidate_url") or clean.get("canonical_url")
    clean["related_leaf_id"] = str(clean.get("related_leaf_id") or leaf_id)
    return clean


def _native_candidate_list(raw_native: Any) -> list[dict[str, Any]]:
    return _native_candidate_payload_list(raw_native)


def _add_hint(
    hints: list[dict[str, Any]],
    url: Any,
    *,
    source_ref: str,
    source_class: str | None,
    source_class_resolution_method: str | None,
    deterministic_source_class_proof: bool = True,
) -> None:
    if not isinstance(url, str) or not url:
        return
    hints.append(
        {
            "url": url,
            "canonical_url": _canonicalize_url(url),
            "source_ref": source_ref,
            "source_class": source_class,
            "source_class_resolution_method": source_class_resolution_method,
            "deterministic_source_class_proof": deterministic_source_class_proof,
        }
    )


def _dedupe_hints(hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hint in hints:
        key = hint.get("canonical_url") or hint.get("url")
        if not key or key in seen:
            continue
        seen.add(str(key))
        deduped.append(hint)
    return deduped


def _urls_at_path(root: Any, path: tuple[str, ...], prefix: str) -> list[tuple[str, str]]:
    current = root
    for part in path:
        if not isinstance(current, dict):
            return []
        current = current.get(part)
    return _extract_urls(current, ".".join((prefix, *path)))


def _urls_from_resolution_fields(root: Any, prefix: str) -> list[tuple[str, str]]:
    if not isinstance(root, dict):
        return []
    matches: list[tuple[str, str]] = []
    for key, value in root.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("resolution", "resolve", "rules", "source_of_truth", "source_url")):
            matches.extend(_extract_urls(value, f"{prefix}.{key}"))
    return matches


def _urls_from_free_text(root: Any, prefix: str) -> list[tuple[str, str]]:
    if not isinstance(root, dict):
        return []
    matches: list[tuple[str, str]] = []
    for key, value in root.items():
        lowered = str(key).lower()
        if not any(token in lowered for token in ("description", "rule", "resolution", "source", "url")):
            continue
        matches.extend(_extract_urls(value, f"{prefix}.{key}"))
    return matches


def _extract_urls(value: Any, prefix: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        for match in re.finditer(r"https?://[^\s<>)\"']+", value):
            found.append((match.group(0).rstrip(".,;:"), prefix))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_extract_urls(item, f"{prefix}[{idx}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_extract_urls(item, f"{prefix}.{key}"))
    return found


def _amrg_url_hints(amrg_context: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not isinstance(amrg_context, dict):
        return []
    hints: list[tuple[str, str]] = []
    for collection_key in ("candidate_edges", "edge_records", "related_markets", "amrg_decomposer_context", "retrieval_query_hints"):
        collection = amrg_context.get(collection_key)
        if not isinstance(collection, list):
            continue
        for idx, item in enumerate(collection):
            if not isinstance(item, dict) or not _amrg_item_allows_retrieval(item):
                continue
            for key in ("source_url", "source_of_truth_url", "retrieval_url", "url", "resolution_url"):
                if isinstance(item.get(key), str):
                    hints.extend(_extract_urls(item[key], f"amrg_context.{collection_key}[{idx}].{key}"))
    return hints


def _amrg_item_allows_retrieval(item: dict[str, Any]) -> bool:
    raw_values: list[Any] = []
    for key in ("allowed_effects", "allowed_use", "allowed_qdt_uses"):
        value = item.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif isinstance(value, str):
            raw_values.append(value)
    return bool({str(value) for value in raw_values} & AMRG_RETRIEVAL_EFFECTS)


def _market_url(case_contract: dict[str, Any]) -> str:
    identity = case_contract.get("market_identity") if isinstance(case_contract, dict) else {}
    if not isinstance(identity, dict):
        identity = {}
    for field_name in ("market_url", "url", "external_url"):
        value = identity.get(field_name)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    slug = str(identity.get("slug") or "").strip().strip("/")
    external = str(identity.get("external_market_id") or identity.get("internal_market_id") or "unknown").strip()
    if slug:
        return f"https://polymarket.com/event/{slug}"
    return f"https://polymarket.com/market/{external}"


def _valid_http_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _canonicalize_url(*urls: Any) -> str:
    raw = ""
    for url in urls:
        if isinstance(url, str) and url:
            raw = url
            break
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(("utm_", "fbclid", "gclid"))
    ]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(sorted(query_pairs)), ""))


def _source_timestamp(fetched: dict[str, Any]) -> str | None:
    for field_name in ("source_published_at", "published_at", "source_updated_at", "source_authored_at", "source_observed_at"):
        value = fetched.get(field_name)
        if isinstance(value, str) and _parse_timestamp(value) is not None:
            return value
    return None


def _first_source_timestamp(fetched: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        value = fetched.get(field_name)
        if isinstance(value, str) and _parse_timestamp(value) is not None:
            return value
    return None


def _timestamp_at_or_after(value: Any, boundary: Any) -> bool:
    parsed = _parse_timestamp(value)
    parsed_boundary = _parse_timestamp(boundary)
    return bool(parsed and parsed_boundary and parsed >= parsed_boundary)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_before(value: str) -> str:
    parsed = _parse_timestamp(value) or datetime.now(timezone.utc)
    return (parsed - timedelta(seconds=1)).isoformat()


def _content_from_fetch(fetched: dict[str, Any]) -> str:
    for key in ("content", "extracted_text", "rendered_text", "markdown", "text"):
        value = fetched.get(key)
        if isinstance(value, str) and value:
            return value[:4000]
    return ""


def _content_sha256(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "RetrievalProviderPolicy",
    "RetrievalTransportResult",
    "collect_live_retrieval_candidates",
]
