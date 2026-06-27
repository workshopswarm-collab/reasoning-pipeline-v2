"""ADS source-populated retrieval transport adapter.

This module gathers candidate URLs and fetched browser content for the live
retrieval packet builder. It deliberately does not certify source class, claim
family, temporal safety, or research sufficiency from provider output.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCE_AUTHORITY_FIELDS = {
    "source_class",
    "source_family_id",
    "source_family",
    "claim_family_id",
    "claim_family_ids",
    "claim_family_resolution_ref",
    "claim_family_resolution_refs",
    "temporal_gate_status",
    "temporal_safety_status",
    "research_sufficiency",
    "research_sufficiency_certification",
    "sufficiency_certification",
    "admission_status",
}

NATIVE_ALLOWED_FIELDS = {
    "url",
    "canonical_url",
    "source_label",
    "title",
    "why_it_may_matter",
    "why_may_matter",
    "related_leaf_id",
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


@dataclass(frozen=True)
class RetrievalProviderPolicy:
    max_direct_urls: int = 12
    max_search_variants_per_leaf: int = 1
    max_search_results_per_variant: int = 5
    broad_search_enabled: bool = True
    native_enabled: bool = False
    deterministic_direct_url_source_classes: bool = True


@dataclass
class RetrievalTransportResult:
    fetched_candidates: list[dict[str, Any]] = field(default_factory=list)
    search_candidate_urls: list[dict[str, Any]] = field(default_factory=list)
    native_research_candidates: list[dict[str, Any]] = field(default_factory=list)
    omitted_candidates: list[dict[str, Any]] = field(default_factory=list)
    supplemental_candidates: list[dict[str, Any]] = field(default_factory=list)
    direct_url_candidates: list[dict[str, Any]] = field(default_factory=list)
    transport_diagnostics: dict[str, Any] = field(default_factory=dict)


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
) -> RetrievalTransportResult:
    """Collect live retrieval candidate inputs without granting evidence authority."""

    from researcher_swarm.retrieval import build_retrieval_query_contexts

    policy = provider_policy or RetrievalProviderPolicy()
    browser_fetch_configured = browser_provider is not None and hasattr(browser_provider, "fetch_url")
    browser_search_configured = browser_provider is not None and hasattr(browser_provider, "search_candidate_urls")
    contexts = build_retrieval_query_contexts(
        qdt,
        evidence_packet=evidence_packet,
        amrg_context=amrg_context,
        forecast_timestamp=forecast_timestamp,
        source_cutoff_timestamp=source_cutoff_timestamp,
    )
    direct_urls = _collect_direct_url_hints(case_contract, evidence_packet, amrg_context)[: policy.max_direct_urls]
    result = RetrievalTransportResult(direct_url_candidates=direct_urls)

    for context in contexts:
        for rank, hint in enumerate(direct_urls, start=1):
            result.fetched_candidates.append(
                _fetch_candidate(
                    context=context,
                    hint=hint,
                    rank=rank,
                    source_cutoff_timestamp=source_cutoff_timestamp,
                    browser_provider=browser_provider,
                    navigation_mode="direct_url",
                    search_candidate_url_ref=None,
                    deterministic_direct_url_source_classes=policy.deterministic_direct_url_source_classes,
                )
            )

    if policy.broad_search_enabled:
        for context in contexts:
            variants = context.get("query_variants") if isinstance(context.get("query_variants"), list) else []
            for variant in variants[: policy.max_search_variants_per_leaf]:
                search_records = _search_candidate_urls(
                    browser_provider,
                    context,
                    variant,
                    searched_at=forecast_timestamp,
                )[: policy.max_search_results_per_variant]
                result.search_candidate_urls.extend(search_records)
                for search_rank, record in enumerate(search_records, start=1):
                    hint = {
                        "url": record.get("url") or record.get("canonical_url"),
                        "source_ref": record.get("candidate_url_ref"),
                        "source_class": None,
                        "source_class_resolution_method": None,
                        "deterministic_source_class_proof": False,
                    }
                    result.fetched_candidates.append(
                        _fetch_candidate(
                            context=context,
                            hint=hint,
                            rank=int(record.get("rank") or search_rank),
                            source_cutoff_timestamp=source_cutoff_timestamp,
                            browser_provider=browser_provider,
                            navigation_mode="web_search",
                            search_candidate_url_ref=record.get("candidate_url_ref"),
                            deterministic_direct_url_source_classes=False,
                        )
                    )

    if policy.native_enabled and native_candidate_provider is not None:
        for context in contexts:
            variants = context.get("query_variants") if isinstance(context.get("query_variants"), list) else []
            if not variants:
                continue
            raw_native = native_candidate_provider(context, variants[0])
            native_candidates = _native_candidate_list(raw_native)
            if native_candidates:
                result.native_research_candidates.append(
                    {
                        "leaf_id": context["leaf_id"],
                        "query_variant_id": variants[0]["query_variant_id"],
                        "candidate_urls": [_sanitize_native_candidate(item, context["leaf_id"]) for item in native_candidates],
                        "resolved_model_id": "gpt-5.5-high",
                        "discovered_at": forecast_timestamp,
                    }
                )

    result.omitted_candidates = [
        candidate
        for candidate in result.fetched_candidates
        if candidate.get("candidate_status") in {"omitted", "rejected"}
        or candidate.get("admission_status") in {"omitted", "rejected"}
        or candidate.get("extraction_status") != "accepted"
    ]
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
        "browser_fetch_authority": "url_fetch_extraction_only",
        "deterministic_admission_authority": "build_live_retrieval_packet_from_candidates",
    }
    return result


def _collect_direct_url_hints(
    case_contract: dict[str, Any],
    evidence_packet: dict[str, Any],
    amrg_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    _add_hint(
        hints,
        _market_url(case_contract),
        source_ref="case_contract.market_url",
        source_class="official_or_primary",
        source_class_resolution_method="official_url_hint",
    )
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
    ):
        for url, source_ref in _urls_from_resolution_fields(root, root_name):
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
) -> dict[str, Any]:
    url = str(hint.get("url") or "")
    canonical_url = _canonicalize_url(url)
    base = {
        "leaf_id": context["leaf_id"],
        "parent_branch_id": context.get("parent_branch_id"),
        "retrieval_transport": "browser",
        "navigation_mode": navigation_mode,
        "requested_url": url,
        "final_url": canonical_url or url,
        "canonical_url": canonical_url,
        "result_rank": rank,
        "direct_url_source_ref": hint.get("source_ref") if navigation_mode == "direct_url" else None,
        "search_candidate_url_ref": search_candidate_url_ref,
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
    fetched = _provider_fetch(browser_provider, url)
    fetched = _strip_authority_fields(fetched)
    extraction_status = str(fetched.get("extraction_status") or fetched.get("status") or "accepted")
    if extraction_status not in {"accepted", "rejected", "paywalled", "blocked", "duplicate", "temporal_fail"}:
        extraction_status = "rejected"
    final_url = _canonicalize_url(fetched.get("final_url"), fetched.get("url"), canonical_url) or canonical_url
    published_at = _source_timestamp(fetched)
    reason_codes = list(fetched.get("reason_codes") or fetched.get("omission_reason_codes") or [])
    if extraction_status == "accepted" and not published_at:
        extraction_status = "rejected"
        reason_codes.append("source_time_unknown_not_admitted_by_transport_adapter")
    if extraction_status == "accepted" and _timestamp_at_or_after(published_at, source_cutoff_timestamp):
        extraction_status = "temporal_fail"
        reason_codes.append("post_cutoff_source_time")
    candidate = {
        **base,
        "final_url": final_url,
        "canonical_url": final_url,
        "extraction_status": extraction_status,
        "source_published_at": published_at,
        "source_observed_at": fetched.get("source_observed_at"),
        "source_updated_at": fetched.get("source_updated_at"),
        "captured_at": fetched.get("captured_at") or _iso_before(source_cutoff_timestamp),
        "content": _content_from_fetch(fetched),
        "content_artifact_ref": fetched.get("content_artifact_ref"),
        "content_sha256": fetched.get("content_sha256") or _content_sha256(_content_from_fetch(fetched)),
        "retrieval_score": float(fetched.get("retrieval_score") or 1.0),
        "transport_authority_boundary": {
            "browser_fetch_certifies_source_class": False,
            "browser_fetch_certifies_claim_family": False,
            "browser_fetch_certifies_temporal_safety": False,
            "browser_fetch_certifies_sufficiency": False,
        },
    }
    if extraction_status == "accepted":
        candidate["admission_status"] = "admitted"
        candidate["temporal_gate_status"] = "pass"
        candidate["admission_reason_code"] = "transport_candidate_requires_deterministic_validation"
        if deterministic_direct_url_source_classes and hint.get("source_class"):
            candidate["source_class"] = hint["source_class"]
            candidate["deterministic_source_class_proof"] = True
            candidate["source_class_resolution_method"] = hint.get("source_class_resolution_method")
            candidate["official_source_hints"] = [url] if hint["source_class"] == "official_or_primary" else []
            candidate["market_resolution_url"] = url if hint["source_class"] == "market_rules_or_resolution_source" else None
    else:
        candidate["candidate_status"] = "omitted" if extraction_status == "duplicate" else "rejected"
        candidate["admission_status"] = "rejected"
        candidate["temporal_gate_status"] = "fail" if extraction_status == "temporal_fail" else "unknown_not_counted"
        candidate["omission_reason_codes"] = reason_codes or [f"extraction_{extraction_status}"]
    return candidate


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


def _search_candidate_urls(browser_provider: Any | None, context: dict[str, Any], variant: dict[str, Any], *, searched_at: str) -> list[dict[str, Any]]:
    if browser_provider is None or not hasattr(browser_provider, "search_candidate_urls"):
        return []
    records = browser_provider.search_candidate_urls(context, variant, searched_at=searched_at)
    return [record for record in records if isinstance(record, dict)]


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
    clean["related_leaf_id"] = str(clean.get("related_leaf_id") or leaf_id)
    return clean


def _native_candidate_list(raw_native: Any) -> list[dict[str, Any]]:
    if isinstance(raw_native, dict):
        raw_native = raw_native.get("native_research_candidates") or raw_native.get("candidate_urls") or []
    return [item for item in raw_native if isinstance(item, dict)] if isinstance(raw_native, list) else []


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


def _extract_urls(value: Any, prefix: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            found.append((value, prefix))
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
    for field_name in ("source_published_at", "published_at", "source_observed_at", "source_updated_at", "source_authored_at"):
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
    for key in ("content", "text", "markdown", "snippet", "title"):
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
