"""RET browser provider facade for OpenClaw browser/web_fetch retrieval."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit
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


def _annotation_snippet(annotation: dict[str, Any], text: str) -> str:
    snippet = str(annotation.get("snippet") or annotation.get("text") or "").strip()
    if snippet:
        return snippet[:500]
    try:
        start = int(annotation.get("start_index"))
        end = int(annotation.get("end_index"))
    except (TypeError, ValueError):
        return ""
    if start < 0 or end <= start:
        return ""
    return text[max(0, start - 80) : min(len(text), end + 80)].strip()[:500]


def _collect_openai_url_citations(payload: Any) -> list[dict[str, str]]:
    """Extract URLs from Responses API web-search sources and annotations."""

    citations: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(annotation: dict[str, Any], text: str = "") -> None:
        annotation_type = str(annotation.get("type") or "")
        url = str(annotation.get("url") or annotation.get("uri") or annotation.get("link") or "").strip()
        if not url or url in seen:
            return
        if annotation_type and annotation_type not in {"url_citation", "citation", "source"}:
            return
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return
        seen.add(url)
        citations.append(
            {
                "url": url,
                "title": str(annotation.get("title") or annotation.get("source_title") or annotation.get("name") or "").strip(),
                "snippet": _annotation_snippet(annotation, text),
            }
        )

    output = payload.get("output") if isinstance(payload, dict) else None
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            if item.get("type") == "web_search_call" and isinstance(action, dict):
                sources = action.get("sources")
                if isinstance(sources, list):
                    for source in sources:
                        if isinstance(source, dict):
                            add(source)
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = str(part.get("text") or part.get("output_text") or "")
                annotations = part.get("annotations")
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if isinstance(annotation, dict):
                        add(annotation, text)
    return citations


def _openai_search_prompt(query_context: dict[str, Any], query_variant: dict[str, Any], search_limit: int) -> str:
    market_question = str(query_context.get("market_question") or query_context.get("macro_question") or "").strip()
    leaf_question = str(query_context.get("leaf_question") or query_context.get("question_text") or "").strip()
    query_text = str(query_variant.get("query_text") or "").strip()
    return "\n".join(
        part
        for part in (
            "Find source URLs for ADS retrieval. Use hosted web search and cite relevant pages.",
            "Return only source discovery context; do not estimate probabilities, SCAE deltas, source classes, "
            "claim families, temporal eligibility, or research sufficiency.",
            f"Limit to at most {search_limit} useful URLs.",
            f"Market question: {market_question}" if market_question else "",
            f"Leaf question: {leaf_question}" if leaf_question else "",
            f"Search query: {query_text}",
        )
        if part
    )


def _extract_json_object_text(value: str) -> str | None:
    start = value.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index, ch in enumerate(value[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return None


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            extracted = _extract_json_object_text(stripped)
            if extracted is None:
                raise
            return json.loads(extracted)
    return value


def _extract_openclaw_reply_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = [_extract_openclaw_reply_text(item) for item in value]
        joined = "\n".join(text for text in texts if text)
        return joined or None
    if not isinstance(value, dict):
        return None
    for key in (
        "reply",
        "response",
        "message",
        "content",
        "text",
        "output",
        "stdout",
        "payloads",
        "finalAssistantVisibleText",
        "finalAssistantRawText",
    ):
        text = _extract_openclaw_reply_text(value.get(key))
        if text:
            return text
    return _extract_openclaw_reply_text(value.get("result"))


def _parse_openclaw_agent_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = stdout
    text = _extract_openclaw_reply_text(parsed)
    if not text:
        raise ValueError("OpenClaw agent response did not contain reply text")
    payload = _json_payload(text)
    if not isinstance(payload, dict):
        raise ValueError("OpenClaw agent reply did not parse to a JSON object")
    return payload


def _openclaw_search_prompt(query_context: dict[str, Any], query_variant: dict[str, Any], search_limit: int) -> str:
    market_question = str(query_context.get("market_question") or query_context.get("macro_question") or "").strip()
    leaf_question = str(query_context.get("leaf_question") or query_context.get("question_text") or "").strip()
    query_text = str(query_variant.get("query_text") or "").strip()
    request = {
        "schema_version": "ads-openclaw-oauth-web-search-request/v1",
        "task": "source_url_discovery_only",
        "search_limit": search_limit,
        "market_question": market_question,
        "leaf_question": leaf_question,
        "search_query": query_text,
        "required_response_schema": {
            "schema_version": "ads-browser-search-candidates/v1",
            "candidates": [
                {
                    "url": "https://example.com/source",
                    "title": "Source title",
                    "snippet": "Why this source may be relevant.",
                }
            ],
        },
        "authority_boundary": {
            "certifies_source_class": False,
            "certifies_claim_family": False,
            "certifies_temporal_safety": False,
            "certifies_research_sufficiency": False,
            "certifies_probability": False,
        },
    }
    return (
        "Use GPT hosted web search through the OpenClaw Gateway to discover source URLs for ADS retrieval.\n"
        "Return exactly one JSON object and no Markdown. Do not estimate probabilities, SCAE deltas, "
        "source classes, claim families, temporal eligibility, decisions, or research sufficiency. "
        "Do not include page text as evidence; URL content will be fetched separately by deterministic transport.\n\n"
        "Request JSON:\n"
        + json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    )


def _candidate_records_from_openclaw_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        candidates = payload.get("urls")
    if not isinstance(candidates, list):
        return []
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in candidates:
        if isinstance(item, str):
            candidate = {"url": item}
        elif isinstance(item, dict):
            candidate = item
        else:
            continue
        url = str(candidate.get("url") or candidate.get("canonical_url") or "").strip()
        if not url or url in seen:
            continue
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        seen.add(url)
        records.append(
            {
                "url": url,
                "title": str(candidate.get("title") or candidate.get("source_title") or "").strip(),
                "snippet": str(
                    candidate.get("snippet")
                    or candidate.get("description")
                    or candidate.get("why_it_may_matter")
                    or ""
                ).strip()[:500],
            }
        )
    return records


class ConfiguredBrowserProvider(BrowserProviderAdapter):
    """Configured search and direct-fetch provider with fail-closed defaults."""

    def __init__(
        self,
        *,
        provider_id: str = OPENCLAW_BROWSER_PROVIDER_ID,
        search_backend: str = "openai_web_search",
        openai_api_key: str | None = None,
        openai_responses_endpoint: str = "https://api.openai.com/v1/responses",
        search_model: str = "gpt-5.5",
        search_api_key: str | None = None,
        brave_search_endpoint: str = "https://api.search.brave.com/res/v1/web/search",
        openclaw_cli: str | None = None,
        openclaw_agent_id: str = "researcher-swarm",
        openclaw_model: str | None = None,
        openclaw_session_key_prefix: str = "ads-browser-search",
        search_limit: int = 5,
        fetch_timeout_seconds: float = 20.0,
        search_timeout_seconds: float = 120.0,
        max_fetch_chars: int = 16_000,
        user_agent: str = "OpenClaw ADS retrieval transport/1.0",
        opener: Callable[..., Any] = urlopen,
        responses_client: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        subprocess_run: Callable[..., Any] = subprocess.run,
    ) -> None:
        super().__init__(provider_id=provider_id)
        self.search_backend = search_backend
        self.openai_api_key = openai_api_key
        self.openai_responses_endpoint = openai_responses_endpoint
        self.search_model = search_model
        self.search_api_key = search_api_key
        self.brave_search_endpoint = brave_search_endpoint
        self.openclaw_cli = openclaw_cli
        self.openclaw_agent_id = openclaw_agent_id
        self.openclaw_model = openclaw_model
        self.openclaw_session_key_prefix = openclaw_session_key_prefix
        self.search_limit = max(1, min(10, int(search_limit or 5)))
        self.fetch_timeout_seconds = max(1.0, float(fetch_timeout_seconds or 20.0))
        self.search_timeout_seconds = max(1.0, float(search_timeout_seconds or 120.0))
        self.max_fetch_chars = max(1000, int(max_fetch_chars or 16_000))
        self.user_agent = user_agent
        self.opener = opener
        self.responses_client = responses_client
        self.subprocess_run = subprocess_run
        self.fetch_configured = True
        self.search_configured = self._search_configured()
        self.last_search_error: str | None = None
        self.last_fetch_error: str | None = None

    def _search_configured(self) -> bool:
        if self.search_backend == "openai_web_search":
            return bool(self.openai_api_key or self.responses_client)
        if self.search_backend == "openclaw_oauth_web_search":
            return bool(self.openclaw_cli or shutil.which("openclaw"))
        if self.search_backend == "brave_search_api":
            return bool(self.search_api_key)
        return False

    def search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: str | None = None,
    ) -> list[dict[str, Any]]:
        self.last_search_error = None
        if self.search_backend == "openai_web_search":
            return self._openai_search_candidate_urls(query_context, query_variant, searched_at=searched_at)
        if self.search_backend == "openclaw_oauth_web_search":
            return self._openclaw_oauth_search_candidate_urls(query_context, query_variant, searched_at=searched_at)
        if self.search_backend == "brave_search_api":
            return self._brave_search_candidate_urls(query_context, query_variant, searched_at=searched_at)
        self.last_search_error = f"unsupported_search_backend:{self.search_backend}"
        return []

    def _openai_search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: str | None,
    ) -> list[dict[str, Any]]:
        if not self.openai_api_key and self.responses_client is None:
            self.last_search_error = "openai_api_key_not_configured"
            return []
        query = str(query_variant.get("query_text") or "").strip()
        if not query:
            return []
        request_payload: dict[str, Any] = {
            "model": self.search_model,
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "include": ["web_search_call.action.sources"],
            "input": _openai_search_prompt(query_context, query_variant, self.search_limit),
            "store": False,
        }
        try:
            if self.responses_client is not None:
                payload = self.responses_client(request_payload)
            else:
                request = Request(
                    self.openai_responses_endpoint,
                    data=json.dumps(request_payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": self.user_agent,
                    },
                    method="POST",
                )
                with self.opener(request, timeout=self.fetch_timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.last_search_error = str(exc)[:500] or exc.__class__.__name__
            return []
        if not isinstance(payload, dict):
            self.last_search_error = "openai_responses_returned_non_object"
            return []
        citations = _collect_openai_url_citations(payload)
        if not citations:
            self.last_search_error = "openai_web_search_no_url_citations"
            return []
        records: list[dict[str, Any]] = []
        for index, citation in enumerate(citations[: self.search_limit], start=1):
            records.append(
                build_search_candidate_url(
                    query_context,
                    query_variant,
                    rank=index,
                    url=citation["url"],
                    title=citation["title"],
                    snippet=citation["snippet"],
                    provider_id=self.provider_id,
                    searched_at=searched_at,
                    result_source="openai_web_search",
                    query_role=str(query_variant.get("query_role") or "primary_leaf_retrieval"),
                )
            )
        return records

    def _openclaw_oauth_search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: str | None,
    ) -> list[dict[str, Any]]:
        resolved_cli = self.openclaw_cli or shutil.which("openclaw")
        if not resolved_cli:
            self.last_search_error = "openclaw_cli_not_configured"
            return []
        query = str(query_variant.get("query_text") or "").strip()
        if not query:
            return []
        leaf_id = str(query_context.get("leaf_id") or "leaf")
        query_role = str(query_variant.get("query_role") or "primary_leaf_retrieval")
        session_key = f"{self.openclaw_session_key_prefix}-{leaf_id}-{query_role}".replace(":", "-")
        command = [
            resolved_cli,
            "agent",
            "--agent",
            self.openclaw_agent_id,
            "--session-key",
            session_key,
            "--message",
            _openclaw_search_prompt(query_context, query_variant, self.search_limit),
            "--json",
            "--timeout",
            str(int(self.search_timeout_seconds)),
        ]
        if self.openclaw_model:
            command.extend(["--model", self.openclaw_model])
        try:
            completed = self.subprocess_run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.search_timeout_seconds + 30,
            )
        except Exception as exc:
            self.last_search_error = str(exc)[:500] or exc.__class__.__name__
            return []
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            self.last_search_error = f"openclaw_agent_failed:{detail[:450]}"
            return []
        try:
            payload = _parse_openclaw_agent_stdout(completed.stdout)
        except Exception as exc:
            self.last_search_error = str(exc)[:500] or exc.__class__.__name__
            return []
        candidates = _candidate_records_from_openclaw_payload(payload)
        if not candidates:
            self.last_search_error = "openclaw_oauth_web_search_no_url_candidates"
            return []
        records: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates[: self.search_limit], start=1):
            records.append(
                build_search_candidate_url(
                    query_context,
                    query_variant,
                    rank=index,
                    url=candidate["url"],
                    title=candidate["title"],
                    snippet=candidate["snippet"],
                    provider_id=self.provider_id,
                    searched_at=searched_at,
                    result_source="openclaw_oauth_web_search",
                    query_role=query_role,
                )
            )
        return records

    def _brave_search_candidate_urls(
        self,
        query_context: dict[str, Any],
        query_variant: dict[str, Any],
        *,
        searched_at: str | None,
    ) -> list[dict[str, Any]]:
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
            "search_provider": self.search_backend,
            "search_model": self.search_model if self.search_backend == "openai_web_search" else None,
            "openclaw_model": self.openclaw_model if self.search_backend == "openclaw_oauth_web_search" else None,
            "openclaw_agent_id": self.openclaw_agent_id if self.search_backend == "openclaw_oauth_web_search" else None,
            "openclaw_cli_configured": bool(self.openclaw_cli or shutil.which("openclaw"))
            if self.search_backend == "openclaw_oauth_web_search"
            else None,
            "search_configured": self._search_configured(),
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

    search_backend = os.getenv("ADS_BROWSER_SEARCH_BACKEND", "openclaw_oauth_web_search")
    return ConfiguredBrowserProvider(
        search_backend=search_backend,
        openai_api_key=os.getenv("OPENAI_API_KEY") or os.getenv("ADS_OPENAI_API_KEY"),
        openai_responses_endpoint=os.getenv("ADS_OPENAI_RESPONSES_ENDPOINT", "https://api.openai.com/v1/responses"),
        search_model=os.getenv("ADS_OPENAI_SEARCH_MODEL") or os.getenv("ADS_BROWSER_SEARCH_MODEL", "gpt-5.5"),
        search_api_key=os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("ADS_BRAVE_SEARCH_API_KEY"),
        brave_search_endpoint=os.getenv(
            "ADS_BRAVE_SEARCH_ENDPOINT",
            "https://api.search.brave.com/res/v1/web/search",
        ),
        openclaw_cli=os.getenv("ADS_OPENCLAW_CLI"),
        openclaw_agent_id=os.getenv("ADS_BROWSER_SEARCH_OPENCLAW_AGENT_ID", "researcher-swarm"),
        openclaw_model=os.getenv("ADS_BROWSER_SEARCH_OPENCLAW_MODEL"),
        openclaw_session_key_prefix=os.getenv("ADS_BROWSER_SEARCH_OPENCLAW_SESSION_KEY_PREFIX", "ads-browser-search"),
        search_limit=int(os.getenv("ADS_BROWSER_SEARCH_LIMIT", "5")),
        fetch_timeout_seconds=float(os.getenv("ADS_BROWSER_FETCH_TIMEOUT_SECONDS", "20")),
        search_timeout_seconds=float(os.getenv("ADS_BROWSER_SEARCH_TIMEOUT_SECONDS", "120")),
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
