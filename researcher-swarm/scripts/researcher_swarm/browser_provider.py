"""RET browser provider facade for OpenClaw browser/web_fetch retrieval."""

from __future__ import annotations

from typing import Any, Callable

from .retrieval import (
    BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION,
    OPENCLAW_BROWSER_PROVIDER_ID,
    SEARCH_CANDIDATE_URL_SCHEMA_VERSION,
    build_browser_search_provider_diagnostic,
    build_search_candidate_url,
)


class BrowserProviderAdapter:
    """Small adapter that keeps URL fetching separate from search discovery."""

    def __init__(
        self,
        *,
        provider_id: str = OPENCLAW_BROWSER_PROVIDER_ID,
        search_provider: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]] | None = None,
        web_fetch: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.search_provider = search_provider
        self.web_fetch = web_fetch

    def search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.search_provider is None:
            return []
        records: list[dict[str, Any]] = []
        for index, result in enumerate(self.search_provider(query_context, query_variant), start=1):
            records.append(
                build_search_candidate_url(
                    query_context,
                    query_variant,
                    rank=int(result.get("rank") or index),
                    url=str(result.get("url") or result.get("canonical_url") or ""),
                    title=str(result.get("title") or ""),
                    snippet=str(result.get("snippet") or ""),
                    provider_id=self.provider_id,
                    searched_at=str(result.get("searched_at") or searched_at or ""),
                    result_source=str(result.get("result_source") or "configured_browser_search_provider"),
                    query_role=str(result.get("query_role") or query_variant.get("query_role") or "primary_leaf_retrieval"),
                )
            )
        return records

    def fetch_url(self, url: str) -> dict[str, Any]:
        if self.web_fetch is None:
            return {
                "url": url,
                "extraction_status": "rejected",
                "reason_codes": ["web_fetch_transport_not_configured"],
                "web_fetch_role": "url_fetch_extraction_only",
            }
        fetched = self.web_fetch(url)
        if not isinstance(fetched, dict):
            return {
                "url": url,
                "extraction_status": "rejected",
                "reason_codes": ["web_fetch_transport_returned_non_object"],
                "web_fetch_role": "url_fetch_extraction_only",
            }
        fetched.setdefault("url", url)
        fetched.setdefault("web_fetch_role", "url_fetch_extraction_only")
        return fetched


__all__ = [
    "BrowserProviderAdapter",
    "BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION",
    "OPENCLAW_BROWSER_PROVIDER_ID",
    "SEARCH_CANDIDATE_URL_SCHEMA_VERSION",
    "build_browser_search_provider_diagnostic",
    "build_search_candidate_url",
]
