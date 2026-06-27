"""RET browser provider facade for OpenClaw browser/web_fetch retrieval."""

from __future__ import annotations

import json
import os
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            stripped = " ".join(data.split())
            if stripped:
                self.parts.append(stripped)

    def text(self) -> str:
        return " ".join(self.parts)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        text = parser.text()
    except Exception:
        text = ""
    return text or re.sub(r"<[^>]+>", " ", value)


def _header_mapping(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            return {str(key).lower(): str(value) for key, value in headers.items()}
        except Exception:
            pass
    getheaders = getattr(response, "getheaders", None)
    if callable(getheaders):
        return {str(key).lower(): str(value) for key, value in getheaders()}
    return {}


def _http_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


class ConfiguredBrowserProvider(BrowserProviderAdapter):
    """Configured search and direct-fetch provider with fail-closed defaults."""

    def __init__(
        self,
        *,
        provider_id: str = OPENCLAW_BROWSER_PROVIDER_ID,
        search_api_key: str | None = None,
        brave_search_endpoint: str = "https://api.search.brave.com/res/v1/web/search",
        search_limit: int = 5,
        fetch_timeout_seconds: float = 20.0,
        max_fetch_chars: int = 16_000,
        user_agent: str = "OpenClaw ADS retrieval transport/1.0",
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        super().__init__(provider_id=provider_id)
        self.search_api_key = search_api_key
        self.brave_search_endpoint = brave_search_endpoint
        self.search_limit = max(1, min(10, int(search_limit or 5)))
        self.fetch_timeout_seconds = max(1.0, float(fetch_timeout_seconds or 20.0))
        self.max_fetch_chars = max(1000, int(max_fetch_chars or 16_000))
        self.user_agent = user_agent
        self.opener = opener
        self.fetch_configured = True
        self.search_configured = bool(search_api_key)
        self.last_search_error: str | None = None
        self.last_fetch_error: str | None = None

    def search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: str | None = None,
    ) -> list[dict[str, Any]]:
        self.last_search_error = None
        if not self.search_api_key:
            self.last_search_error = "brave_search_api_key_not_configured"
            return []
        query = str(query_variant.get("query_text") or "").strip()
        if not query:
            return []
        params = urlencode({"q": query, "count": str(self.search_limit)})
        request = Request(
            f"{self.brave_search_endpoint}?{params}",
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
                "X-Subscription-Token": self.search_api_key,
            },
        )
        try:
            with self.opener(request, timeout=self.fetch_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.last_search_error = str(exc)[:500] or exc.__class__.__name__
            return []
        raw_results = payload.get("web", {}).get("results", [])
        records: list[dict[str, Any]] = []
        for index, result in enumerate(raw_results, start=1):
            if not isinstance(result, dict):
                continue
            url = str(result.get("url") or "").strip()
            if not url:
                continue
            records.append(
                build_search_candidate_url(
                    query_context,
                    query_variant,
                    rank=index,
                    url=url,
                    title=str(result.get("title") or ""),
                    snippet=str(result.get("description") or result.get("snippet") or ""),
                    provider_id=self.provider_id,
                    searched_at=searched_at,
                    result_source="brave_search_api",
                    query_role=str(query_variant.get("query_role") or "primary_leaf_retrieval"),
                )
            )
        return records

    def fetch_url(self, url: str) -> dict[str, Any]:
        self.last_fetch_error = None
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html, text/plain;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with self.opener(request, timeout=self.fetch_timeout_seconds) as response:
                final_url = getattr(response, "url", None) or url
                headers = _header_mapping(response)
                raw = response.read(self.max_fetch_chars * 4)
        except Exception as exc:
            self.last_fetch_error = str(exc)[:500] or exc.__class__.__name__
            return {
                "url": url,
                "final_url": url,
                "extraction_status": "rejected",
                "reason_codes": ["http_fetch_failed"],
                "web_fetch_role": "url_fetch_extraction_only",
                "provider_error": self.last_fetch_error,
            }
        content_type = headers.get("content-type", "")
        text = raw.decode("utf-8", errors="replace")
        content = _html_to_text(text) if "html" in content_type.lower() else " ".join(text.split())
        content = content[: self.max_fetch_chars]
        if not content:
            return {
                "url": url,
                "final_url": final_url,
                "extraction_status": "rejected",
                "reason_codes": ["http_fetch_empty_content"],
                "web_fetch_role": "url_fetch_extraction_only",
            }
        fetched = {
            "url": url,
            "final_url": final_url,
            "extraction_status": "accepted",
            "content": content,
            "source_published_at": _http_datetime(headers.get("last-modified")),
            "source_updated_at": _http_datetime(headers.get("last-modified")),
            "captured_at": _http_datetime(headers.get("date")),
            "web_fetch_role": "url_fetch_extraction_only",
        }
        return {key: value for key, value in fetched.items() if value not in (None, "")}

    def provider_diagnostics(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "adapter": "configured_browser_provider",
            "search_provider": "brave_search_api",
            "search_configured": bool(self.search_api_key),
            "fetch_configured": True,
            "last_search_error": self.last_search_error,
            "last_fetch_error": self.last_fetch_error,
            "web_fetch_role": "url_fetch_extraction_only",
            "web_fetch_must_not_be_used_as_search": True,
            "authority_boundary": {
                "certifies_source_class": False,
                "certifies_claim_family": False,
                "certifies_temporal_safety": False,
                "certifies_research_sufficiency": False,
                "certifies_probability": False,
            },
        }


def build_provider() -> ConfiguredBrowserProvider:
    """Build the scheduler-loadable configured browser/search provider."""

    return ConfiguredBrowserProvider(
        search_api_key=os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("ADS_BRAVE_SEARCH_API_KEY"),
        brave_search_endpoint=os.getenv(
            "ADS_BRAVE_SEARCH_ENDPOINT",
            "https://api.search.brave.com/res/v1/web/search",
        ),
        search_limit=int(os.getenv("ADS_BROWSER_SEARCH_LIMIT", "5")),
        fetch_timeout_seconds=float(os.getenv("ADS_BROWSER_FETCH_TIMEOUT_SECONDS", "20")),
        max_fetch_chars=int(os.getenv("ADS_BROWSER_FETCH_MAX_CHARS", "16000")),
        user_agent=os.getenv("ADS_BROWSER_PROVIDER_USER_AGENT", "OpenClaw ADS retrieval transport/1.0"),
    )


__all__ = [
    "BrowserProviderAdapter",
    "ConfiguredBrowserProvider",
    "BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION",
    "OPENCLAW_BROWSER_PROVIDER_ID",
    "SEARCH_CANDIDATE_URL_SCHEMA_VERSION",
    "build_provider",
    "build_browser_search_provider_diagnostic",
    "build_search_candidate_url",
]
