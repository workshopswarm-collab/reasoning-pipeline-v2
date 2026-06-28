"""RET browser provider facade for OpenClaw browser/web_fetch retrieval."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
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


class _HTMLMetadataExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.json_ld_parts: list[str] = []
        self._json_ld_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = {str(key).lower(): str(value or "").strip() for key, value in attrs}
        lowered = tag.lower()
        if lowered == "meta":
            key = (
                attrs_by_name.get("property")
                or attrs_by_name.get("name")
                or attrs_by_name.get("itemprop")
            )
            content = attrs_by_name.get("content")
            if key and content:
                self.meta[key.lower()] = content
        elif lowered == "time":
            key = attrs_by_name.get("itemprop")
            content = attrs_by_name.get("datetime")
            if key and content:
                self.meta[key.lower()] = content
        elif lowered == "script" and "ld+json" in attrs_by_name.get("type", "").lower():
            self._json_ld_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self.json_ld_parts.append(data)


def _squash_text(value: Any, max_chars: int) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def _metadata_datetime(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _json_ld_date_values(payload: Any, keys: set[str]) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in keys and isinstance(value, str):
                values.append(value)
            elif isinstance(value, (dict, list)):
                values.extend(_json_ld_date_values(value, keys))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_json_ld_date_values(item, keys))
    return values


def _first_parsed_datetime(values: list[Any]) -> str | None:
    for value in values:
        parsed = _metadata_datetime(value)
        if parsed:
            return parsed
    return None


def _html_page_datetimes(html: str) -> dict[str, str]:
    parser = _HTMLMetadataExtractor()
    try:
        parser.feed(html)
    except Exception:
        return {}
    published_keys = {
        "article:published_time",
        "og:published_time",
        "publishdate",
        "pubdate",
        "date",
        "dc.date",
        "dc.date.issued",
        "dcterms.issued",
        "citation_publication_date",
        "datepublished",
    }
    updated_keys = {
        "article:modified_time",
        "og:updated_time",
        "lastmod",
        "last-modified",
        "dateupdated",
        "datemodified",
        "dcterms.modified",
    }
    json_ld_payloads: list[Any] = []
    for part in parser.json_ld_parts:
        try:
            json_ld_payloads.append(json.loads(part))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    published_values = [value for key, value in parser.meta.items() if key in published_keys]
    updated_values = [value for key, value in parser.meta.items() if key in updated_keys]
    for payload in json_ld_payloads:
        published_values.extend(_json_ld_date_values(payload, {"datepublished", "datecreated", "uploaddate"}))
        updated_values.extend(_json_ld_date_values(payload, {"datemodified", "dateupdated"}))
    metadata: dict[str, str] = {}
    published = _first_parsed_datetime(published_values)
    updated = _first_parsed_datetime(updated_values)
    if published:
        metadata["source_published_at"] = published
    if updated:
        metadata["source_updated_at"] = updated
    return metadata


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


def _json_object_from_stdout(stdout: str) -> Any:
    try:
        return json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("browser CLI returned non-JSON output") from exc


def _completed_error(completed: Any, default: str) -> str:
    detail = str(getattr(completed, "stderr", "") or getattr(completed, "stdout", "") or "").strip()
    return detail[:500] or default


def _nested_lookup(value: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(value, dict):
        return None
    for key in keys:
        if key in value:
            return value[key]
    for nested_key in ("result", "value", "data", "payload", "tab", "page"):
        nested = value.get(nested_key)
        found = _nested_lookup(nested, keys)
        if found not in (None, ""):
            return found
    return None


def _openclaw_browser_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for key in ("result", "value", "data", "payload"):
            nested = value.get(key)
            if isinstance(nested, dict) and any(
                candidate in nested for candidate in ("final_url", "href", "url", "body_text", "text", "title")
            ):
                return nested
        if any(candidate in value for candidate in ("final_url", "href", "url", "body_text", "text", "title")):
            return value
    return None


def _openclaw_browser_cli_rendered_fetch(
    url: str,
    timeout_seconds: float,
    max_chars: int,
    *,
    openclaw_cli: str | None = None,
    subprocess_run: Callable[..., Any] = subprocess.run,
    browser_profile: str | None = None,
) -> dict[str, Any]:
    resolved_cli = openclaw_cli or shutil.which("openclaw")
    if not resolved_cli:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_cli_not_available"],
        }
    timeout_ms = str(int(max(1.0, timeout_seconds) * 1000))
    command_prefix = [resolved_cli, "browser", "--json", "--timeout", timeout_ms]
    if browser_profile:
        command_prefix.extend(["--browser-profile", browser_profile])
    subprocess_timeout = max(2.0, timeout_seconds + 2.0)

    try:
        doctor = subprocess_run(
            [*command_prefix, "doctor"],
            check=False,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
        )
    except Exception as exc:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_cli_doctor_failed"],
            "provider_error": str(exc)[:500] or exc.__class__.__name__,
        }
    if getattr(doctor, "returncode", 1) != 0:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_cli_doctor_failed"],
            "provider_error": _completed_error(doctor, "openclaw browser doctor failed"),
        }
    try:
        doctor_payload = _json_object_from_stdout(getattr(doctor, "stdout", ""))
    except ValueError as exc:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_cli_doctor_invalid_json"],
            "provider_error": str(exc),
        }
    status = doctor_payload.get("status") if isinstance(doctor_payload, dict) else None
    if not isinstance(status, dict) or not status.get("running"):
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_not_running"],
        }

    tab_ref: str | None = None
    open_completed: Any | None = None
    try:
        open_completed = subprocess_run(
            [*command_prefix, "open", url],
            check=False,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
        )
        if getattr(open_completed, "returncode", 1) != 0:
            return {
                "extraction_status": "rejected",
                "reason_codes": ["openclaw_browser_navigation_failed"],
                "provider_error": _completed_error(open_completed, "openclaw browser navigation failed"),
            }
        open_payload = _json_object_from_stdout(getattr(open_completed, "stdout", ""))
        tab_ref_value = _nested_lookup(open_payload, ("ref", "tabRef", "tab_ref", "targetId", "target_id", "id"))
        tab_ref = str(tab_ref_value) if tab_ref_value not in (None, "") else None
        js = (
            "() => ({"
            "final_url: window.location.href,"
            "title: document.title || '',"
            "body_text: document.body ? document.body.innerText : '',"
            "head_html: document.head ? document.head.innerHTML : ''"
            "})"
        )
        evaluate_completed = subprocess_run(
            [*command_prefix, "evaluate", "--fn", js],
            check=False,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout,
        )
        if getattr(evaluate_completed, "returncode", 1) != 0:
            return {
                "extraction_status": "rejected",
                "reason_codes": ["openclaw_browser_evaluate_failed"],
                "provider_error": _completed_error(evaluate_completed, "openclaw browser evaluate failed"),
            }
        evaluate_payload = _json_object_from_stdout(getattr(evaluate_completed, "stdout", ""))
        payload = _openclaw_browser_payload(evaluate_payload)
        if payload is None:
            return {
                "extraction_status": "rejected",
                "reason_codes": ["openclaw_browser_evaluate_invalid_payload"],
            }
        return {
            "final_url": str(payload.get("final_url") or payload.get("href") or payload.get("url") or url),
            "title": str(payload.get("title") or ""),
            "body_text": _squash_text(payload.get("body_text") or payload.get("text") or "", max_chars),
            "head_html": _squash_text(payload.get("head_html") or "", max_chars),
        }
    except ValueError as exc:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_cli_invalid_json"],
            "provider_error": str(exc),
        }
    except Exception as exc:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["openclaw_browser_cli_failed"],
            "provider_error": str(exc)[:500] or exc.__class__.__name__,
        }
    finally:
        if open_completed is not None and getattr(open_completed, "returncode", 1) == 0:
            close_command = [*command_prefix, "close"]
            if tab_ref:
                close_command.append(tab_ref)
            try:
                subprocess_run(
                    close_command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=subprocess_timeout,
                )
            except Exception:
                pass


def _python_playwright_rendered_fetch(url: str, timeout_seconds: float, max_chars: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "extraction_status": "rejected",
            "reason_codes": ["python_playwright_not_available"],
            "provider_error": str(exc)[:500] or exc.__class__.__name__,
        }

    timeout_ms = int(max(1.0, timeout_seconds) * 1000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            payload = page.evaluate(
                """() => ({
                    final_url: window.location.href,
                    title: document.title || "",
                    body_text: document.body ? document.body.innerText : "",
                    head_html: document.head ? document.head.innerHTML : ""
                })"""
            )
        finally:
            browser.close()
    if not isinstance(payload, dict):
        return {
            "extraction_status": "rejected",
            "reason_codes": ["rendered_fetch_returned_non_object"],
        }
    payload["body_text"] = _squash_text(payload.get("body_text"), max_chars)
    payload["head_html"] = _squash_text(payload.get("head_html"), max_chars)
    return payload


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
        search_timeout_seconds: float = 45.0,
        search_subprocess_grace_seconds: float = 10.0,
        max_fetch_chars: int = 16_000,
        user_agent: str = "OpenClaw ADS retrieval transport/1.0",
        opener: Callable[..., Any] = urlopen,
        responses_client: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        subprocess_run: Callable[..., Any] = subprocess.run,
        rendered_fetch_enabled: bool = False,
        rendered_fetch_backend: str = "openclaw_browser_cli",
        rendered_fetcher: Callable[[str, float, int], dict[str, Any]] | None = None,
        rendered_fetch_timeout_seconds: float | None = None,
        rendered_fetch_openclaw_cli: str | None = None,
        rendered_fetch_browser_profile: str | None = None,
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
        self.search_timeout_seconds = max(1.0, float(search_timeout_seconds or 45.0))
        self.search_subprocess_grace_seconds = max(1.0, float(search_subprocess_grace_seconds or 10.0))
        self.max_fetch_chars = max(1000, int(max_fetch_chars or 16_000))
        self.user_agent = user_agent
        self.opener = opener
        self.responses_client = responses_client
        self.subprocess_run = subprocess_run
        self.rendered_fetch_enabled = bool(rendered_fetch_enabled)
        requested_rendered_backend = str(rendered_fetch_backend or "openclaw_browser_cli")
        self.rendered_fetch_openclaw_cli = rendered_fetch_openclaw_cli
        self.rendered_fetch_browser_profile = rendered_fetch_browser_profile
        if rendered_fetcher is not None:
            self.rendered_fetcher = rendered_fetcher
            self.rendered_fetch_backend = "injected"
        elif requested_rendered_backend == "python_playwright":
            self.rendered_fetcher = _python_playwright_rendered_fetch
            self.rendered_fetch_backend = "python_playwright"
        else:
            self.rendered_fetcher = lambda target_url, timeout_seconds, max_chars: _openclaw_browser_cli_rendered_fetch(
                target_url,
                timeout_seconds,
                max_chars,
                openclaw_cli=self.rendered_fetch_openclaw_cli or self.openclaw_cli,
                subprocess_run=self.subprocess_run,
                browser_profile=self.rendered_fetch_browser_profile,
            )
            self.rendered_fetch_backend = "openclaw_browser_cli"
        self.rendered_fetch_timeout_seconds = max(
            1.0,
            float(rendered_fetch_timeout_seconds or self.fetch_timeout_seconds),
        )
        self.fetch_configured = True
        self.search_configured = self._search_configured()
        self.last_search_error: str | None = None
        self.last_fetch_error: str | None = None
        self.last_rendered_fetch_error: str | None = None

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
                timeout=self.search_timeout_seconds + self.search_subprocess_grace_seconds,
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
        self.last_rendered_fetch_error = None
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
            if self.rendered_fetch_enabled:
                return self._rendered_fetch_url(url, direct_error=self.last_fetch_error)
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
        is_html = "html" in content_type.lower()
        page_metadata = _html_page_datetimes(text) if is_html else {}
        content = _html_to_text(text) if is_html else " ".join(text.split())
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
            "source_published_at": page_metadata.get("source_published_at")
            or _http_datetime(headers.get("last-modified")),
            "source_updated_at": page_metadata.get("source_updated_at")
            or _http_datetime(headers.get("last-modified")),
            "captured_at": _http_datetime(headers.get("date")),
            "web_fetch_role": "url_fetch_extraction_only",
        }
        return {key: value for key, value in fetched.items() if value not in (None, "")}

    def _rendered_fetch_url(self, url: str, *, direct_error: str) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "enabled": True,
            "backend": self.rendered_fetch_backend,
            "timeout_seconds": self.rendered_fetch_timeout_seconds,
            "max_chars": self.max_fetch_chars,
            "capture_boundary": "exact_requested_url_rendered_page_text_only",
            "direct_fetch_error": direct_error,
        }
        try:
            payload = self.rendered_fetcher(url, self.rendered_fetch_timeout_seconds, self.max_fetch_chars)
        except Exception as exc:
            self.last_rendered_fetch_error = str(exc)[:500] or exc.__class__.__name__
            diagnostic.update({"status": "rejected", "reason_codes": ["rendered_fetch_failed"]})
            return {
                "url": url,
                "final_url": url,
                "extraction_status": "rejected",
                "reason_codes": ["http_fetch_failed", "rendered_fetch_failed"],
                "web_fetch_role": "url_fetch_extraction_only",
                "provider_error": direct_error,
                "rendered_fetch_error": self.last_rendered_fetch_error,
                "rendered_fetch_diagnostic": diagnostic,
            }
        if not isinstance(payload, dict):
            self.last_rendered_fetch_error = "rendered_fetch_returned_non_object"
            diagnostic.update({"status": "rejected", "reason_codes": ["rendered_fetch_returned_non_object"]})
            return {
                "url": url,
                "final_url": url,
                "extraction_status": "rejected",
                "reason_codes": ["http_fetch_failed", "rendered_fetch_returned_non_object"],
                "web_fetch_role": "url_fetch_extraction_only",
                "provider_error": direct_error,
                "rendered_fetch_error": self.last_rendered_fetch_error,
                "rendered_fetch_diagnostic": diagnostic,
            }
        if payload.get("extraction_status") == "rejected":
            reason_codes = payload.get("reason_codes") if isinstance(payload.get("reason_codes"), list) else []
            rendered_reason_codes = [str(reason) for reason in reason_codes if reason] or ["rendered_fetch_failed"]
            self.last_rendered_fetch_error = str(payload.get("provider_error") or rendered_reason_codes[0])[:500]
            diagnostic.update({"status": "rejected", "reason_codes": rendered_reason_codes})
            return {
                "url": url,
                "final_url": str(payload.get("final_url") or payload.get("url") or url),
                "extraction_status": "rejected",
                "reason_codes": ["http_fetch_failed", *rendered_reason_codes],
                "web_fetch_role": "url_fetch_extraction_only",
                "provider_error": direct_error,
                "rendered_fetch_error": self.last_rendered_fetch_error,
                "rendered_fetch_diagnostic": diagnostic,
            }
        content = _squash_text(
            payload.get("content")
            or payload.get("markdown")
            or payload.get("body_text")
            or payload.get("text"),
            self.max_fetch_chars,
        )
        html_metadata = _html_page_datetimes(
            str(
                payload.get("html")
                or payload.get("document_html")
                or payload.get("head_html")
                or ""
            )
        )
        final_url = str(payload.get("final_url") or payload.get("url") or url)
        if not content:
            self.last_rendered_fetch_error = "rendered_fetch_empty_content"
            diagnostic.update({"status": "rejected", "reason_codes": ["rendered_fetch_empty_content"]})
            return {
                "url": url,
                "final_url": final_url,
                "extraction_status": "rejected",
                "reason_codes": ["http_fetch_failed", "rendered_fetch_empty_content"],
                "web_fetch_role": "url_fetch_extraction_only",
                "provider_error": direct_error,
                "rendered_fetch_error": self.last_rendered_fetch_error,
                "rendered_fetch_diagnostic": diagnostic,
            }
        diagnostic.update({"status": "accepted", "reason_codes": []})
        fetched = {
            "url": url,
            "final_url": final_url,
            "extraction_status": "accepted",
            "content": content,
            "source_published_at": html_metadata.get("source_published_at"),
            "source_updated_at": html_metadata.get("source_updated_at"),
            "web_fetch_role": "url_fetch_extraction_only",
            "extraction_method": "local_rendered_fetch_fallback",
            "rendered_fetch_diagnostic": diagnostic,
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
            "search_limit": self.search_limit,
            "search_timeout_seconds": self.search_timeout_seconds,
            "search_subprocess_grace_seconds": self.search_subprocess_grace_seconds,
            "rendered_fetch_enabled": self.rendered_fetch_enabled,
            "rendered_fetch_backend": self.rendered_fetch_backend if self.rendered_fetch_enabled else None,
            "rendered_fetch_browser_profile": self.rendered_fetch_browser_profile
            if self.rendered_fetch_enabled and self.rendered_fetch_backend == "openclaw_browser_cli"
            else None,
            "rendered_fetch_timeout_seconds": self.rendered_fetch_timeout_seconds
            if self.rendered_fetch_enabled
            else None,
            "last_search_error": self.last_search_error,
            "last_fetch_error": self.last_fetch_error,
            "last_rendered_fetch_error": self.last_rendered_fetch_error,
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
    default_search_limit = "2" if search_backend == "openclaw_oauth_web_search" else "5"
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
        search_limit=int(os.getenv("ADS_BROWSER_SEARCH_LIMIT", default_search_limit)),
        fetch_timeout_seconds=float(os.getenv("ADS_BROWSER_FETCH_TIMEOUT_SECONDS", "20")),
        search_timeout_seconds=float(os.getenv("ADS_BROWSER_SEARCH_TIMEOUT_SECONDS", "45")),
        search_subprocess_grace_seconds=float(os.getenv("ADS_BROWSER_SEARCH_SUBPROCESS_GRACE_SECONDS", "10")),
        max_fetch_chars=int(os.getenv("ADS_BROWSER_FETCH_MAX_CHARS", "16000")),
        user_agent=os.getenv("ADS_BROWSER_PROVIDER_USER_AGENT", "OpenClaw ADS retrieval transport/1.0"),
        rendered_fetch_enabled=_env_flag("ADS_BROWSER_RENDERED_FETCH_ENABLED", default=False),
        rendered_fetch_backend=os.getenv("ADS_BROWSER_RENDERED_FETCH_BACKEND", "openclaw_browser_cli"),
        rendered_fetch_timeout_seconds=float(
            os.getenv(
                "ADS_BROWSER_RENDERED_FETCH_TIMEOUT_SECONDS",
                os.getenv("ADS_BROWSER_FETCH_TIMEOUT_SECONDS", "20"),
            )
        ),
        rendered_fetch_openclaw_cli=os.getenv("ADS_BROWSER_RENDERED_FETCH_OPENCLAW_CLI"),
        rendered_fetch_browser_profile=os.getenv("ADS_BROWSER_RENDERED_FETCH_BROWSER_PROFILE"),
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
