#!/usr/bin/env python3
"""Materialize Workbench context-usage telemetry.

This script emits metadata-only evidence about Workbench context usage. It does
not make pruning decisions and is not consumed by the pruning engine until the
later integration phase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "workbench-context-usage-telemetry/v1"
DEFAULT_SOURCE_WINDOW_DAYS = 30
DEFAULT_COMPACT_SOURCE_WINDOW_DAYS = 14
DEFAULT_MAX_HOT_ENTRIES = 750
DEFAULT_SIGNAL_COUNTS: dict[str, int] = {
    "memory_search_hit": 1,
    "read": 1,
    "memory_get": 2,
    "final_citation": 3,
    "context_edit": 3,
}
STRONG_CONTEXT_SIGNALS = {"final_citation", "context_edit"}
FOLLOW_THROUGH_ORDER = {
    "final_citation": "citation",
    "context_edit": "edit",
    "memory_get": "get",
    "read": "same_session_read",
}

WORKBENCH_ROOT = Path(os.environ.get("WORKBENCH_ROOT", "/Users/agent2/.openclaw/workbench")).resolve()
WORKBENCH_CONTEXT_ROOT = WORKBENCH_ROOT / "context"
WORKBENCH_SESSION_LOG_ROOT = Path(
    os.environ.get("WORKBENCH_SESSION_LOG_ROOT", "/Users/agent2/.openclaw/agents/workbench/sessions")
).resolve()
WORKBENCH_SESSION_LOG_GLOB = "*.jsonl"
TELEMETRY_JSON_PATH = WORKBENCH_CONTEXT_ROOT / "state" / "context-usage-telemetry.json"
TELEMETRY_MARKDOWN_PATH = WORKBENCH_CONTEXT_ROOT / "state" / "context-usage-telemetry.md"
FINAL_CITATION_RE = re.compile(
    r"(?:Source:\s*)?(?P<path>context/[^\s`'\"()\[\]{},;:]+?\.md)#L(?P<start>\d+)(?:-L?(?P<end>\d+))?"
)
CONTENT_HASH_SOURCE = "current_context_span:v1"
COMPACT_HOT_ENTRY_FIELDS = (
    "path",
    "startLine",
    "endLine",
    "signalCount",
    "firstSeenAt",
    "lastSeenAt",
    "signalType",
    "evidenceTier",
    "spanKind",
    "protectsFromPrune",
    "followThrough",
    "tierReason",
    "contentHash",
    "sourceHash",
)


@dataclass(frozen=True)
class PendingReadCall:
    session_path: Path
    session_hash: str
    tool_call_id: str
    call_line: int
    timestamp: str
    rel_path: str
    offset: int | None
    limit: int | None


@dataclass(frozen=True)
class PendingMemoryGetCall:
    session_path: Path
    session_hash: str
    tool_call_id: str
    call_line: int
    timestamp: str
    rel_path: str
    from_line: int | None
    lines: int | None


@dataclass(frozen=True)
class PendingContextEditCall:
    session_path: Path
    session_hash: str
    tool_name: str
    tool_call_id: str
    call_line: int
    timestamp: str
    arguments: dict[str, Any]
    rel_paths: tuple[str, ...]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_iso(value: Any) -> str:
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return utc_now_iso()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha1_short(value: str, *, length: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def source_hash(*parts: Any) -> str:
    return "sha1:" + sha1_short("\u241f".join(str(part) for part in parts), length=16)


def utc_event_day(timestamp: str) -> str:
    parsed = parse_iso_datetime(timestamp)
    if parsed is None:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def earlier_iso(left: str, right: str) -> str:
    left_dt = parse_iso_datetime(left)
    right_dt = parse_iso_datetime(right)
    if left_dt is not None and right_dt is not None:
        if left_dt.tzinfo is None:
            left_dt = left_dt.replace(tzinfo=timezone.utc)
        if right_dt.tzinfo is None:
            right_dt = right_dt.replace(tzinfo=timezone.utc)
        return left if left_dt <= right_dt else right
    return min(left, right)


def later_iso(left: str, right: str) -> str:
    left_dt = parse_iso_datetime(left)
    right_dt = parse_iso_datetime(right)
    if left_dt is not None and right_dt is not None:
        if left_dt.tzinfo is None:
            left_dt = left_dt.replace(tzinfo=timezone.utc)
        if right_dt.tzinfo is None:
            right_dt = right_dt.replace(tzinfo=timezone.utc)
        return left if left_dt >= right_dt else right
    return max(left, right)


def normalize_context_markdown_path(raw_path: Any) -> str | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    expanded = Path(raw_path).expanduser()
    try:
        if expanded.is_absolute():
            absolute = expanded.resolve(strict=False)
            try:
                rel = absolute.relative_to(WORKBENCH_ROOT)
            except ValueError:
                return None
        else:
            rel = Path(raw_path)
    except OSError:
        return None

    rel = Path(*[part for part in rel.parts if part not in ("", ".")])
    if not rel.parts or rel.parts[0] != "context":
        return None
    if rel.suffix.lower() != ".md":
        return None
    if ".." in rel.parts:
        return None
    return rel.as_posix()


def parse_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "".join(parts)


def line_count_from_text(text: str) -> int | None:
    if text == "":
        return None
    # Count the returned excerpt lines without retaining raw result text.
    return len(text.splitlines()) or 1


def current_file_line_count(rel_path: str) -> int | None:
    path = WORKBENCH_ROOT / rel_path
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return None


def current_file_text(rel_path: str) -> str | None:
    path = WORKBENCH_ROOT / rel_path
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def normalized_span_text_hash(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def current_context_span_text(rel_path: str, start_line: int, end_line: int) -> str | None:
    rel = normalize_context_markdown_path(rel_path)
    start = parse_positive_int(start_line)
    end = parse_positive_int(end_line)
    if rel is None or start is None or end is None or end < start:
        return None
    file_text = current_file_text(rel)
    if file_text is None:
        return None
    lines = file_text.splitlines()
    if start > len(lines) or end > len(lines):
        return None
    return "\n".join(lines[start - 1 : end])


def current_context_span_hash(rel_path: str, start_line: int, end_line: int) -> str | None:
    span_text = current_context_span_text(rel_path, start_line, end_line)
    if span_text is None:
        return None
    return normalized_span_text_hash(span_text)


def infer_read_span(call: PendingReadCall, result_text: str) -> tuple[int, int, str | None]:
    start_line = call.offset or 1
    result_line_count = line_count_from_text(result_text)
    file_line_count = current_file_line_count(call.rel_path)

    if call.limit is not None:
        end_line = start_line + call.limit - 1
    elif result_line_count is not None:
        end_line = start_line + result_line_count - 1
    else:
        return 0, 0, "missing-result-text-for-unbounded-read"

    if file_line_count is not None:
        end_line = min(end_line, file_line_count)
    if end_line < start_line:
        return 0, 0, "invalid-read-line-span"
    return start_line, end_line, None


def cap_span_to_current_file(rel_path: str, start_line: int, end_line: int) -> tuple[int, int, str | None]:
    file_line_count = current_file_line_count(rel_path)
    if file_line_count is not None:
        end_line = min(end_line, file_line_count)
    if end_line < start_line:
        return 0, 0, "invalid-line-span"
    return start_line, end_line, None


def infer_memory_get_span(
    call: PendingMemoryGetCall | None,
    details: dict[str, Any],
    *,
    rel_path: str,
) -> tuple[int, int, str | None]:
    detail_from = parse_positive_int(details.get("from"))
    detail_lines = parse_positive_int(details.get("lines"))
    start_line = call.from_line if call and call.from_line is not None else detail_from
    line_count = call.lines if call and call.lines is not None else detail_lines
    if start_line is not None and line_count is not None:
        return cap_span_to_current_file(rel_path, start_line, start_line + line_count - 1)

    detail_start = parse_positive_int(details.get("startLine"))
    detail_end = parse_positive_int(details.get("endLine"))
    if detail_start is not None and detail_end is not None:
        return cap_span_to_current_file(rel_path, detail_start, detail_end)

    if start_line is not None:
        detail_text = details.get("text")
        result_line_count = line_count_from_text(detail_text) if isinstance(detail_text, str) else None
        if result_line_count is not None:
            return cap_span_to_current_file(rel_path, start_line, start_line + result_line_count - 1)

    return 0, 0, "missing-memory-get-line-span"


def memory_get_span_reason(reason: str) -> str:
    if reason == "invalid-line-span":
        return "invalid-memory-get-line-span"
    return reason


def line_span_for_unique_text(rel_path: str, text: Any) -> tuple[int, int, str | None]:
    if not isinstance(text, str) or text == "":
        return 0, 0, "missing-edit-newtext-span"
    file_text = current_file_text(rel_path)
    if file_text is None:
        return 0, 0, "missing-context-file-for-edit"
    matches: list[int] = []
    start = 0
    while True:
        index = file_text.find(text, start)
        if index < 0:
            break
        matches.append(index)
        if len(matches) > 1:
            return 0, 0, "ambiguous-edit-newtext-span"
        start = index + max(1, len(text))
    if not matches:
        return 0, 0, "edit-newtext-not-found"
    start_line = file_text[: matches[0]].count("\n") + 1
    changed_line_count = len(text.splitlines()) or 1
    return cap_span_to_current_file(rel_path, start_line, start_line + changed_line_count - 1)


def line_spans_from_tool_diff(diff_text: Any) -> list[tuple[int, int]]:
    """Extract post-change line spans from OpenClaw edit toolResult diffs.

    The edit tool result often includes compact display lines such as
    `+ 87 new text`. These spans remain useful after later edits, unlike
    matching `newText` against the current file. Raw diff content is never
    persisted; only bounded line spans are returned.
    """
    if not isinstance(diff_text, str) or not diff_text:
        return []
    line_numbers: list[int] = []
    for raw_line in diff_text.splitlines():
        match = re.match(r"^\+\s*(?P<line>\d+)\s", raw_line)
        if not match:
            continue
        line_number = parse_positive_int(match.group("line"))
        if line_number is not None:
            line_numbers.append(line_number)
    if not line_numbers:
        return []

    spans: list[tuple[int, int]] = []
    start = previous = line_numbers[0]
    for line_number in line_numbers[1:]:
        if line_number == previous + 1:
            previous = line_number
            continue
        spans.append((start, previous))
        start = previous = line_number
    spans.append((start, previous))
    return spans


def iter_primary_session_logs(*, cutoff: datetime | None = None) -> list[Path]:
    if not WORKBENCH_SESSION_LOG_ROOT.exists():
        return []
    paths: list[Path] = []
    for path in WORKBENCH_SESSION_LOG_ROOT.glob(WORKBENCH_SESSION_LOG_GLOB):
        name = path.name
        if ".trajectory" in name or ".checkpoint." in name:
            continue
        if cutoff is not None:
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified < cutoff:
                continue
        paths.append(path)
    return sorted(paths)


def is_recent_timestamp(value: str, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) >= cutoff


def warning_entry(kind: str, *, rel_path: str | None = None, source: str | None = None, reason: str) -> dict[str, Any]:
    warning: dict[str, Any] = {"kind": kind, "reason": reason}
    if rel_path:
        warning["path"] = rel_path
    if source:
        warning["sourceHash"] = source
    return warning


def content_hash_warning_reason(rel_path: str, start_line: int, end_line: int) -> str:
    start = parse_positive_int(start_line)
    end = parse_positive_int(end_line)
    if start is None or end is None or end < start:
        return "invalid-content-hash-line-span"
    file_line_count = current_file_line_count(rel_path)
    if file_line_count is None:
        return "missing-context-file-for-content-hash"
    if start > file_line_count or end > file_line_count:
        return "invalid-content-hash-line-span"
    return "content-hash-span-unresolved"


def content_hash_metadata(
    signal_type: str,
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    source: str,
    warnings: list[Any],
) -> dict[str, str]:
    content_hash = current_context_span_hash(rel_path, start_line, end_line)
    if content_hash is None:
        warnings.append(
            warning_entry(
                signal_type,
                rel_path=rel_path,
                source=source,
                reason=content_hash_warning_reason(rel_path, start_line, end_line),
            )
        )
        return {}
    return {"contentHash": content_hash, "contentHashSource": CONTENT_HASH_SOURCE}


def numeric_metadata(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def positive_line_span(start_line: Any, end_line: Any) -> int | None:
    start = parse_positive_int(start_line)
    end = parse_positive_int(end_line)
    if start is None or end is None or end < start:
        return None
    return end - start + 1


def span_kind_for_lines(span_lines: int | None) -> str:
    if span_lines is None:
        return "unknown"
    if span_lines > 80:
        return "broad"
    if span_lines > 40:
        return "medium"
    return "narrow"


def context_signal_taxonomy(signal_type: str, span_kind: str, follow_through: str) -> tuple[str, bool, str]:
    """Return report-only evidence tier metadata for a context telemetry signal."""
    if signal_type == "final_citation":
        return "strong", True, "final-citation"
    if signal_type == "context_edit":
        # An edit means a span was changed, not that it remains useful after the
        # normal recent-edit grace period. Treat it as strong provenance/coverage
        # metadata, but do not let routine development-log writebacks pin bloat.
        return "strong", False, "context-edit-not-usage"
    if signal_type == "memory_get":
        if span_kind == "broad":
            return "medium", False, "broad-memory-get"
        return "strong", True, "targeted-memory-get"
    if signal_type == "read":
        if span_kind == "broad":
            return "weak", False, "broad-read"
        return "medium", False, "targeted-read"
    if signal_type == "memory_search_hit":
        if follow_through not in {"", "none", "unknown"}:
            return "medium", False, f"search-follow-through:{follow_through}"
        return "weak", False, "raw-search-hit"
    return "invalid", False, f"unknown-signal:{signal_type}"


def refresh_entry_taxonomy(entry: dict[str, Any]) -> None:
    span_lines = positive_line_span(entry.get("startLine"), entry.get("endLine"))
    span_kind = span_kind_for_lines(span_lines)
    signal_type = str(entry.get("signalType") or "")
    follow_through = str(entry.get("followThrough") or "none")
    evidence_tier, protects, reason = context_signal_taxonomy(signal_type, span_kind, follow_through)
    entry["spanLines"] = span_lines
    entry["spanKind"] = span_kind
    entry["followThrough"] = follow_through
    entry["evidenceTier"] = evidence_tier
    entry["protectsFromPrune"] = protects
    entry["tierReason"] = reason


def line_spans_overlap(a1: int, a2: int, b1: int, b2: int) -> bool:
    return not (a2 < b1 or b2 < a1)


def entry_session_hashes(entry: dict[str, Any]) -> set[str]:
    values = entry.get("sessionHashes")
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and value}


def entry_follow_order(signal_type: str) -> int:
    order = ["final_citation", "context_edit", "memory_get", "read"]
    try:
        return order.index(signal_type)
    except ValueError:
        return len(order)


def annotate_search_follow_through(entries: dict[str, Any]) -> None:
    """Upgrade raw memory search hits to medium evidence when a same-session targeted signal follows through.

    This is report-only metadata. It does not change pruning behavior in Phase 2.
    """
    by_path: dict[str, list[dict[str, Any]]] = {}
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if isinstance(path, str) and path:
            by_path.setdefault(path, []).append(entry)

    for entry in entries.values():
        if not isinstance(entry, dict) or entry.get("signalType") != "memory_search_hit":
            continue
        start = parse_positive_int(entry.get("startLine"))
        end = parse_positive_int(entry.get("endLine"))
        if start is None or end is None:
            refresh_entry_taxonomy(entry)
            continue
        sessions = entry_session_hashes(entry)
        candidates: list[dict[str, Any]] = []
        for other in by_path.get(str(entry.get("path") or ""), []):
            signal_type = str(other.get("signalType") or "")
            if signal_type not in FOLLOW_THROUGH_ORDER:
                continue
            if sessions and entry_session_hashes(other).isdisjoint(sessions):
                continue
            other_start = parse_positive_int(other.get("startLine"))
            other_end = parse_positive_int(other.get("endLine"))
            if other_start is None or other_end is None:
                continue
            if not line_spans_overlap(start, end, other_start, other_end):
                continue
            search_ts = parse_iso_datetime(entry.get("firstSeenAt"))
            other_ts = parse_iso_datetime(other.get("firstSeenAt"))
            if search_ts is not None and other_ts is not None and other_ts < search_ts:
                continue
            candidates.append(other)
        if candidates:
            candidates.sort(key=lambda item: entry_follow_order(str(item.get("signalType") or "")))
            entry["followThrough"] = FOLLOW_THROUGH_ORDER[str(candidates[0].get("signalType"))]
        else:
            entry["followThrough"] = "none"
        refresh_entry_taxonomy(entry)


def upsert_signal_entry(
    entries: dict[str, Any],
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    signal_type: str,
    timestamp: str,
    source: str,
    session_hash: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    signal_count = DEFAULT_SIGNAL_COUNTS[signal_type]
    content_hash = metadata.get("contentHash") if isinstance(metadata, dict) else None
    if not isinstance(content_hash, str) or not content_hash:
        content_hash = None
    content_hash_source = metadata.get("contentHashSource") if isinstance(metadata, dict) else None
    if not isinstance(content_hash_source, str) or not content_hash_source:
        content_hash_source = None
    event_day = utc_event_day(timestamp)
    key_material = "\u241f".join(
        [rel_path, str(start_line), str(end_line), signal_type, event_day, session_hash]
    )
    key = f"{signal_type}:" + sha1_short(key_material, length=24)
    entry = entries.get(key)
    if entry is None:
        entry = {
            "path": rel_path,
            "startLine": start_line,
            "endLine": end_line,
            "signalType": signal_type,
            "signalCount": signal_count,
            "firstSeenAt": timestamp,
            "lastSeenAt": timestamp,
            "eventDay": event_day,
            "eventCount": 1,
            "sessionCount": 1,
            "sessionHashes": [session_hash],
            "sourceKinds": [signal_type],
            "sourceHashes": [source],
        }
        if content_hash is not None:
            entry["contentHash"] = content_hash
            if content_hash_source is not None:
                entry["contentHashSource"] = content_hash_source
        entries[key] = entry
    else:
        entry["firstSeenAt"] = earlier_iso(str(entry.get("firstSeenAt", timestamp)), timestamp)
        entry["lastSeenAt"] = later_iso(str(entry.get("lastSeenAt", timestamp)), timestamp)
        entry["eventCount"] = int(entry.get("eventCount") or 0) + 1
        source_hashes = entry.setdefault("sourceHashes", [])
        if isinstance(source_hashes, list) and source not in source_hashes:
            source_hashes.append(source)
        source_kinds = entry.setdefault("sourceKinds", [])
        if isinstance(source_kinds, list) and signal_type not in source_kinds:
            source_kinds.append(signal_type)
        session_hashes = entry.setdefault("sessionHashes", [])
        if isinstance(session_hashes, list) and session_hash not in session_hashes:
            session_hashes.append(session_hash)
        if content_hash is not None and not isinstance(entry.get("contentHash"), str):
            entry["contentHash"] = content_hash
            if content_hash_source is not None:
                entry["contentHashSource"] = content_hash_source
        elif content_hash is not None and entry.get("contentHash") == content_hash and content_hash_source is not None:
            entry.setdefault("contentHashSource", content_hash_source)

    if metadata:
        for field in ("score", "vectorScore", "textScore"):
            numeric = numeric_metadata(metadata.get(field))
            if numeric is None:
                continue
            existing = numeric_metadata(entry.get(field))
            entry[field] = numeric if existing is None else max(existing, numeric)
    refresh_entry_taxonomy(entry)


def add_read_entry(
    entries: dict[str, Any],
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    timestamp: str,
    source: str,
    session_hash: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    upsert_signal_entry(
        entries,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        signal_type="read",
        timestamp=timestamp,
        source=source,
        session_hash=session_hash,
        metadata=metadata,
    )


def add_memory_search_hit_entry(
    entries: dict[str, Any],
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    timestamp: str,
    source: str,
    session_hash: str,
    result: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    entry_metadata = dict(result)
    if metadata:
        entry_metadata.update(metadata)
    upsert_signal_entry(
        entries,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        signal_type="memory_search_hit",
        timestamp=timestamp,
        source=source,
        session_hash=session_hash,
        metadata=entry_metadata,
    )


def add_memory_get_entry(
    entries: dict[str, Any],
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    timestamp: str,
    source: str,
    session_hash: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    upsert_signal_entry(
        entries,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        signal_type="memory_get",
        timestamp=timestamp,
        source=source,
        session_hash=session_hash,
        metadata=metadata,
    )


def add_final_citation_entry(
    entries: dict[str, Any],
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    timestamp: str,
    source: str,
    session_hash: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    upsert_signal_entry(
        entries,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        signal_type="final_citation",
        timestamp=timestamp,
        source=source,
        session_hash=session_hash,
        metadata=metadata,
    )


def add_context_edit_entry(
    entries: dict[str, Any],
    *,
    rel_path: str,
    start_line: int,
    end_line: int,
    timestamp: str,
    source: str,
    session_hash: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    upsert_signal_entry(
        entries,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        signal_type="context_edit",
        timestamp=timestamp,
        source=source,
        session_hash=session_hash,
        metadata=metadata,
    )


def collect_direct_read_events(*, source_window_days: int, generated_at_utc: str) -> tuple[dict[str, Any], list[Any]]:
    generated_at = parse_iso_datetime(generated_at_utc) or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    cutoff = generated_at.astimezone(timezone.utc) - timedelta(days=source_window_days)

    entries: dict[str, Any] = {}
    warnings: list[Any] = []
    for session_path in iter_primary_session_logs(cutoff=cutoff):
        session_hash = source_hash(session_path.name)
        pending: dict[str, PendingReadCall] = {}
        try:
            handle = session_path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(warning_entry("session_log", source=session_hash, reason=f"open-failed:{type(exc).__name__}"))
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(warning_entry("session_log", source=session_hash, reason="invalid-json-line"))
                    continue
                if record.get("type") != "message":
                    continue
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                role = message.get("role")
                content = message.get("content")
                if role == "assistant" and isinstance(content, list):
                    timestamp = normalize_iso(record.get("timestamp") or message.get("timestamp"))
                    if not is_recent_timestamp(timestamp, cutoff):
                        continue
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "toolCall" or item.get("name") != "read":
                            continue
                        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                        rel_path = normalize_context_markdown_path(arguments.get("path"))
                        if rel_path is None:
                            continue
                        tool_call_id = item.get("id")
                        if not isinstance(tool_call_id, str) or not tool_call_id:
                            warnings.append(
                                warning_entry(
                                    "read",
                                    rel_path=rel_path,
                                    source=source_hash(session_path.name, line_number),
                                    reason="missing-tool-call-id",
                                )
                            )
                            continue
                        pending[tool_call_id] = PendingReadCall(
                            session_path=session_path,
                            session_hash=session_hash,
                            tool_call_id=tool_call_id,
                            call_line=line_number,
                            timestamp=timestamp,
                            rel_path=rel_path,
                            offset=parse_positive_int(arguments.get("offset")),
                            limit=parse_positive_int(arguments.get("limit")),
                        )
                elif role == "toolResult" and message.get("toolName") == "read":
                    tool_call_id = message.get("toolCallId")
                    if not isinstance(tool_call_id, str) or tool_call_id not in pending:
                        continue
                    call = pending.pop(tool_call_id)
                    source = source_hash(session_path.name, call.tool_call_id, call.call_line, line_number)
                    if message.get("isError"):
                        warnings.append(warning_entry("read", rel_path=call.rel_path, source=source, reason="read-tool-error"))
                        continue
                    result_text = extract_text_from_content(content)
                    start_line, end_line, reason = infer_read_span(call, result_text)
                    if reason:
                        warnings.append(warning_entry("read", rel_path=call.rel_path, source=source, reason=reason))
                        continue
                    add_read_entry(
                        entries,
                        rel_path=call.rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        timestamp=call.timestamp,
                        source=source,
                        session_hash=call.session_hash,
                        metadata=content_hash_metadata(
                            "read",
                            rel_path=call.rel_path,
                            start_line=start_line,
                            end_line=end_line,
                            source=source,
                            warnings=warnings,
                        ),
                    )
        for call in pending.values():
            source = source_hash(session_path.name, call.tool_call_id, call.call_line)
            warnings.append(warning_entry("read", rel_path=call.rel_path, source=source, reason="missing-tool-result"))
    return entries, warnings


def collect_memory_search_hit_events(*, source_window_days: int, generated_at_utc: str) -> tuple[dict[str, Any], list[Any]]:
    generated_at = parse_iso_datetime(generated_at_utc) or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    cutoff = generated_at.astimezone(timezone.utc) - timedelta(days=source_window_days)

    entries: dict[str, Any] = {}
    warnings: list[Any] = []
    for session_path in iter_primary_session_logs(cutoff=cutoff):
        session_hash = source_hash(session_path.name)
        try:
            handle = session_path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(warning_entry("session_log", source=session_hash, reason=f"open-failed:{type(exc).__name__}"))
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(warning_entry("session_log", source=session_hash, reason="invalid-json-line"))
                    continue
                if record.get("type") != "message":
                    continue
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                if message.get("role") != "toolResult" or message.get("toolName") != "memory_search":
                    continue
                timestamp = normalize_iso(record.get("timestamp") or message.get("timestamp"))
                if not is_recent_timestamp(timestamp, cutoff):
                    continue
                details = message.get("details") if isinstance(message.get("details"), dict) else {}
                results = details.get("results") if isinstance(details.get("results"), list) else []
                if not results:
                    continue
                tool_call_id = message.get("toolCallId") if isinstance(message.get("toolCallId"), str) else ""
                result_source = source_hash(session_path.name, tool_call_id, record.get("id", ""), line_number)
                seen_in_result: set[tuple[str, int, int]] = set()
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    rel_path = normalize_context_markdown_path(result.get("path"))
                    if rel_path is None:
                        continue
                    start_line = parse_positive_int(result.get("startLine"))
                    end_line = parse_positive_int(result.get("endLine"))
                    if start_line is None or end_line is None or end_line < start_line:
                        warnings.append(
                            warning_entry(
                                "memory_search_hit",
                                rel_path=rel_path,
                                source=result_source,
                                reason="invalid-result-line-span",
                            )
                        )
                        continue
                    dedupe_key = (rel_path, start_line, end_line)
                    if dedupe_key in seen_in_result:
                        continue
                    seen_in_result.add(dedupe_key)
                    add_memory_search_hit_entry(
                        entries,
                        rel_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        timestamp=timestamp,
                        source=result_source,
                        session_hash=session_hash,
                        result=result,
                        metadata=content_hash_metadata(
                            "memory_search_hit",
                            rel_path=rel_path,
                            start_line=start_line,
                            end_line=end_line,
                            source=result_source,
                            warnings=warnings,
                        ),
                    )
    return entries, warnings


def collect_memory_get_events(*, source_window_days: int, generated_at_utc: str) -> tuple[dict[str, Any], list[Any]]:
    generated_at = parse_iso_datetime(generated_at_utc) or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    cutoff = generated_at.astimezone(timezone.utc) - timedelta(days=source_window_days)

    entries: dict[str, Any] = {}
    warnings: list[Any] = []
    for session_path in iter_primary_session_logs(cutoff=cutoff):
        session_hash = source_hash(session_path.name)
        pending: dict[str, PendingMemoryGetCall] = {}
        try:
            handle = session_path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(warning_entry("session_log", source=session_hash, reason=f"open-failed:{type(exc).__name__}"))
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(warning_entry("session_log", source=session_hash, reason="invalid-json-line"))
                    continue
                if record.get("type") != "message":
                    continue
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                role = message.get("role")
                content = message.get("content")
                if role == "assistant" and isinstance(content, list):
                    timestamp = normalize_iso(record.get("timestamp") or message.get("timestamp"))
                    if not is_recent_timestamp(timestamp, cutoff):
                        continue
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "toolCall" or item.get("name") != "memory_get":
                            continue
                        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                        rel_path = normalize_context_markdown_path(arguments.get("path"))
                        if rel_path is None:
                            continue
                        tool_call_id = item.get("id")
                        if not isinstance(tool_call_id, str) or not tool_call_id:
                            warnings.append(
                                warning_entry(
                                    "memory_get",
                                    rel_path=rel_path,
                                    source=source_hash(session_path.name, line_number),
                                    reason="missing-tool-call-id",
                                )
                            )
                            continue
                        pending[tool_call_id] = PendingMemoryGetCall(
                            session_path=session_path,
                            session_hash=session_hash,
                            tool_call_id=tool_call_id,
                            call_line=line_number,
                            timestamp=timestamp,
                            rel_path=rel_path,
                            from_line=parse_positive_int(arguments.get("from")),
                            lines=parse_positive_int(arguments.get("lines")),
                        )
                elif role == "toolResult" and message.get("toolName") == "memory_get":
                    tool_call_id = message.get("toolCallId") if isinstance(message.get("toolCallId"), str) else ""
                    call = pending.pop(tool_call_id, None) if tool_call_id else None
                    details = message.get("details") if isinstance(message.get("details"), dict) else {}
                    rel_path = call.rel_path if call is not None else normalize_context_markdown_path(details.get("path"))
                    if rel_path is None:
                        continue
                    timestamp = call.timestamp if call is not None else normalize_iso(record.get("timestamp") or message.get("timestamp"))
                    if not is_recent_timestamp(timestamp, cutoff):
                        continue
                    source = (
                        source_hash(session_path.name, call.tool_call_id, call.call_line, line_number)
                        if call is not None
                        else source_hash(session_path.name, tool_call_id, record.get("id", ""), line_number)
                    )
                    if message.get("isError"):
                        warnings.append(
                            warning_entry("memory_get", rel_path=rel_path, source=source, reason="memory-get-tool-error")
                        )
                        continue
                    start_line, end_line, reason = infer_memory_get_span(call, details, rel_path=rel_path)
                    if reason:
                        warnings.append(
                            warning_entry(
                                "memory_get",
                                rel_path=rel_path,
                                source=source,
                                reason=memory_get_span_reason(reason),
                            )
                        )
                        continue
                    add_memory_get_entry(
                        entries,
                        rel_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        timestamp=timestamp,
                        source=source,
                        session_hash=call.session_hash if call is not None else session_hash,
                        metadata=content_hash_metadata(
                            "memory_get",
                            rel_path=rel_path,
                            start_line=start_line,
                            end_line=end_line,
                            source=source,
                            warnings=warnings,
                        ),
                    )
        for call in pending.values():
            source = source_hash(session_path.name, call.tool_call_id, call.call_line)
            warnings.append(
                warning_entry("memory_get", rel_path=call.rel_path, source=source, reason="missing-tool-result")
            )
    return entries, warnings



def context_paths_from_apply_patch(patch_text: Any) -> tuple[str, ...]:
    if not isinstance(patch_text, str):
        return ()
    rel_paths: list[str] = []
    seen: set[str] = set()
    for line in patch_text.splitlines():
        match = re.match(r"^\*\*\* (?:Update|Add|Delete) File:\s+(?P<path>.+?)\s*$", line)
        if not match:
            continue
        rel_path = normalize_context_markdown_path(match.group("path"))
        if rel_path is None or rel_path in seen:
            continue
        seen.add(rel_path)
        rel_paths.append(rel_path)
    return tuple(rel_paths)


def context_edit_paths(tool_name: str, arguments: dict[str, Any]) -> tuple[str, ...]:
    if tool_name in {"edit", "write"}:
        rel_path = normalize_context_markdown_path(arguments.get("path"))
        return (rel_path,) if rel_path is not None else ()
    if tool_name == "apply_patch":
        return context_paths_from_apply_patch(arguments.get("input"))
    return ()


def result_failed(message: dict[str, Any]) -> bool:
    if message.get("isError"):
        return True
    details = message.get("details")
    if isinstance(details, dict) and details.get("status") == "error":
        return True
    return False


def apply_patch_spans(patch_text: Any) -> tuple[dict[str, list[tuple[int, int]]], list[dict[str, Any]]]:
    spans_by_path: dict[str, list[tuple[int, int]]] = {}
    warnings: list[dict[str, Any]] = []
    if not isinstance(patch_text, str) or not patch_text:
        return spans_by_path, warnings

    current_rel_path: str | None = None
    touched_paths: set[str] = set()
    for line in patch_text.splitlines():
        file_match = re.match(r"^\*\*\* (?:Update|Add|Delete) File:\s+(?P<path>.+?)\s*$", line)
        if file_match:
            current_rel_path = normalize_context_markdown_path(file_match.group("path"))
            if current_rel_path is not None:
                touched_paths.add(current_rel_path)
            continue
        if current_rel_path is None:
            continue
        hunk_match = re.match(r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<start>\d+)(?:,(?P<count>\d+))?\s+@@", line)
        if not hunk_match:
            continue
        start_line = parse_positive_int(hunk_match.group("start"))
        count = int(hunk_match.group("count") or "1")
        if start_line is None or count <= 0:
            warnings.append(
                warning_entry(
                    "context_edit",
                    rel_path=current_rel_path,
                    reason="invalid-apply-patch-line-span",
                )
            )
            continue
        spans_by_path.setdefault(current_rel_path, []).append((start_line, start_line + count - 1))

    for rel_path in sorted(touched_paths):
        if not spans_by_path.get(rel_path):
            warnings.append(
                warning_entry(
                    "context_edit",
                    rel_path=rel_path,
                    reason="ambiguous-apply-patch-line-span",
                )
            )
    return spans_by_path, warnings


def iter_final_citations(text: str) -> list[tuple[str, int, int | None]]:
    citations: list[tuple[str, int, int | None]] = []
    for match in FINAL_CITATION_RE.finditer(text):
        rel_path = normalize_context_markdown_path(match.group("path"))
        if rel_path is None:
            continue
        start_line = parse_positive_int(match.group("start"))
        if start_line is None:
            continue
        end_line = parse_positive_int(match.group("end")) if match.group("end") else start_line
        citations.append((rel_path, start_line, end_line))
    return citations


def collect_final_citation_events(*, source_window_days: int, generated_at_utc: str) -> tuple[dict[str, Any], list[Any]]:
    generated_at = parse_iso_datetime(generated_at_utc) or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    cutoff = generated_at.astimezone(timezone.utc) - timedelta(days=source_window_days)

    entries: dict[str, Any] = {}
    warnings: list[Any] = []
    for session_path in iter_primary_session_logs(cutoff=cutoff):
        session_hash = source_hash(session_path.name)
        try:
            handle = session_path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(warning_entry("session_log", source=session_hash, reason=f"open-failed:{type(exc).__name__}"))
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(warning_entry("session_log", source=session_hash, reason="invalid-json-line"))
                    continue
                if record.get("type") != "message":
                    continue
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                if message.get("role") != "assistant":
                    continue
                timestamp = normalize_iso(record.get("timestamp") or message.get("timestamp"))
                if not is_recent_timestamp(timestamp, cutoff):
                    continue
                text = extract_text_from_content(message.get("content"))
                if not text:
                    continue
                source = source_hash(session_path.name, record.get("id", ""), line_number)
                seen_in_message: set[tuple[str, int, int]] = set()
                for rel_path, start_line, end_line in iter_final_citations(text):
                    if end_line is None or end_line < start_line:
                        warnings.append(
                            warning_entry(
                                "final_citation",
                                rel_path=rel_path,
                                source=source,
                                reason="invalid-final-citation-line-span",
                            )
                        )
                        continue
                    dedupe_key = (rel_path, start_line, end_line)
                    if dedupe_key in seen_in_message:
                        continue
                    seen_in_message.add(dedupe_key)
                    add_final_citation_entry(
                        entries,
                        rel_path=rel_path,
                        start_line=start_line,
                        end_line=end_line,
                        timestamp=timestamp,
                        source=source,
                        session_hash=session_hash,
                        metadata=content_hash_metadata(
                            "final_citation",
                            rel_path=rel_path,
                            start_line=start_line,
                            end_line=end_line,
                            source=source,
                            warnings=warnings,
                        ),
                    )
    return entries, warnings


def context_edit_span_reason(reason: str) -> str:
    if reason == "invalid-line-span":
        return "invalid-context-edit-line-span"
    return reason


def collect_context_edit_events(*, source_window_days: int, generated_at_utc: str) -> tuple[dict[str, Any], list[Any]]:
    generated_at = parse_iso_datetime(generated_at_utc) or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    cutoff = generated_at.astimezone(timezone.utc) - timedelta(days=source_window_days)

    entries: dict[str, Any] = {}
    warnings: list[Any] = []
    edit_tools = {"edit", "write", "apply_patch"}
    for session_path in iter_primary_session_logs(cutoff=cutoff):
        session_hash = source_hash(session_path.name)
        pending: dict[str, PendingContextEditCall] = {}
        try:
            handle = session_path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            warnings.append(warning_entry("session_log", source=session_hash, reason=f"open-failed:{type(exc).__name__}"))
            continue
        with handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(warning_entry("session_log", source=session_hash, reason="invalid-json-line"))
                    continue
                if record.get("type") != "message":
                    continue
                message = record.get("message") if isinstance(record.get("message"), dict) else {}
                role = message.get("role")
                content = message.get("content")
                if role == "assistant" and isinstance(content, list):
                    timestamp = normalize_iso(record.get("timestamp") or message.get("timestamp"))
                    if not is_recent_timestamp(timestamp, cutoff):
                        continue
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") != "toolCall" or item.get("name") not in edit_tools:
                            continue
                        tool_name = item.get("name")
                        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                        rel_paths = context_edit_paths(tool_name, arguments)
                        if not rel_paths:
                            continue
                        tool_call_id = item.get("id")
                        if not isinstance(tool_call_id, str) or not tool_call_id:
                            for rel_path in rel_paths:
                                warnings.append(
                                    warning_entry(
                                        "context_edit",
                                        rel_path=rel_path,
                                        source=source_hash(session_path.name, line_number),
                                        reason="missing-tool-call-id",
                                    )
                                )
                            continue
                        pending[tool_call_id] = PendingContextEditCall(
                            session_path=session_path,
                            session_hash=session_hash,
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            call_line=line_number,
                            timestamp=timestamp,
                            arguments=arguments,
                            rel_paths=rel_paths,
                        )
                elif role == "toolResult" and message.get("toolName") in edit_tools:
                    tool_call_id = message.get("toolCallId")
                    if not isinstance(tool_call_id, str) or tool_call_id not in pending:
                        continue
                    call = pending.pop(tool_call_id)
                    source = source_hash(session_path.name, call.tool_call_id, call.call_line, line_number)
                    if result_failed(message):
                        for rel_path in call.rel_paths:
                            warnings.append(
                                warning_entry(
                                    "context_edit",
                                    rel_path=rel_path,
                                    source=source,
                                    reason="context-edit-tool-error",
                                )
                            )
                        continue

                    result_details = message.get("details") if isinstance(message.get("details"), dict) else {}
                    if call.tool_name == "edit":
                        rel_path = call.rel_paths[0]
                        diff_spans = line_spans_from_tool_diff(result_details.get("diff"))
                        if diff_spans:
                            seen_spans: set[tuple[str, int, int]] = set()
                            for raw_start_line, raw_end_line in diff_spans:
                                start_line, end_line, reason = cap_span_to_current_file(rel_path, raw_start_line, raw_end_line)
                                if reason:
                                    warnings.append(
                                        warning_entry(
                                            "context_edit",
                                            rel_path=rel_path,
                                            source=source,
                                            reason=context_edit_span_reason(reason),
                                        )
                                    )
                                    continue
                                dedupe_key = (rel_path, start_line, end_line)
                                if dedupe_key in seen_spans:
                                    continue
                                seen_spans.add(dedupe_key)
                                add_context_edit_entry(
                                    entries,
                                    rel_path=rel_path,
                                    start_line=start_line,
                                    end_line=end_line,
                                    timestamp=call.timestamp,
                                    source=source,
                                    session_hash=call.session_hash,
                                    metadata=content_hash_metadata(
                                        "context_edit",
                                        rel_path=rel_path,
                                        start_line=start_line,
                                        end_line=end_line,
                                        source=source,
                                        warnings=warnings,
                                    ),
                                )
                            continue
                        edits = call.arguments.get("edits")
                        if not isinstance(edits, list) or not edits:
                            for rel_path in call.rel_paths:
                                warnings.append(
                                    warning_entry(
                                        "context_edit",
                                        rel_path=rel_path,
                                        source=source,
                                        reason="missing-edit-blocks",
                                    )
                                )
                            continue
                        seen_spans: set[tuple[str, int, int]] = set()
                        for edit_block in edits:
                            if not isinstance(edit_block, dict):
                                continue
                            rel_path = call.rel_paths[0]
                            start_line, end_line, reason = line_span_for_unique_text(rel_path, edit_block.get("newText"))
                            if reason:
                                warnings.append(
                                    warning_entry(
                                        "context_edit",
                                        rel_path=rel_path,
                                        source=source,
                                        reason=context_edit_span_reason(reason),
                                    )
                                )
                                continue
                            dedupe_key = (rel_path, start_line, end_line)
                            if dedupe_key in seen_spans:
                                continue
                            seen_spans.add(dedupe_key)
                            add_context_edit_entry(
                                entries,
                                rel_path=rel_path,
                                start_line=start_line,
                                end_line=end_line,
                                timestamp=call.timestamp,
                                source=source,
                                session_hash=call.session_hash,
                                metadata=content_hash_metadata(
                                    "context_edit",
                                    rel_path=rel_path,
                                    start_line=start_line,
                                    end_line=end_line,
                                    source=source,
                                    warnings=warnings,
                                ),
                            )
                    elif call.tool_name == "write":
                        for rel_path in call.rel_paths:
                            warnings.append(
                                warning_entry(
                                    "context_edit",
                                    rel_path=rel_path,
                                    source=source,
                                    reason="ambiguous-write-line-span",
                                )
                            )
                    elif call.tool_name == "apply_patch":
                        spans_by_path, patch_warnings = apply_patch_spans(call.arguments.get("input"))
                        for warning in patch_warnings:
                            warning = dict(warning)
                            warning["sourceHash"] = source
                            warnings.append(warning)
                        seen_spans: set[tuple[str, int, int]] = set()
                        for rel_path, spans in sorted(spans_by_path.items()):
                            for start_line, end_line in spans:
                                dedupe_key = (rel_path, start_line, end_line)
                                if dedupe_key in seen_spans:
                                    continue
                                seen_spans.add(dedupe_key)
                                add_context_edit_entry(
                                    entries,
                                    rel_path=rel_path,
                                    start_line=start_line,
                                    end_line=end_line,
                                    timestamp=call.timestamp,
                                    source=source,
                                    session_hash=call.session_hash,
                                    metadata=content_hash_metadata(
                                        "context_edit",
                                        rel_path=rel_path,
                                        start_line=start_line,
                                        end_line=end_line,
                                        source=source,
                                        warnings=warnings,
                                    ),
                                )
        for call in pending.values():
            source = source_hash(session_path.name, call.tool_call_id, call.call_line)
            for rel_path in call.rel_paths:
                warnings.append(
                    warning_entry("context_edit", rel_path=rel_path, source=source, reason="missing-tool-result")
                )
    return entries, warnings


def summarize_entries(entries: dict[str, Any], warnings: list[Any]) -> dict[str, Any]:
    signal_type_counts: Counter[str] = Counter()
    weighted_signal_counts: Counter[str] = Counter()
    raw_event_counts: Counter[str] = Counter()
    evidence_tier_counts: Counter[str] = Counter()
    span_kind_counts: Counter[str] = Counter()
    content_hash_by_signal_type: Counter[str] = Counter()
    warning_reason_counts: Counter[str] = Counter()
    covered_paths: set[str] = set()
    broad_read_count = 0
    raw_search_only_count = 0
    entries_with_content_hash = 0
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        signal_type = entry.get("signalType")
        evidence_tier = entry.get("evidenceTier")
        span_kind = entry.get("spanKind")
        if isinstance(path, str) and path:
            covered_paths.add(path)
        if isinstance(signal_type, str) and signal_type:
            signal_type_counts[signal_type] += 1
            weighted_signal_counts[signal_type] += int(entry.get("signalCount") or 0)
            raw_event_counts[signal_type] += int(entry.get("eventCount") or 0)
        has_content_hash = isinstance(entry.get("contentHash"), str) and bool(entry.get("contentHash"))
        if has_content_hash:
            entries_with_content_hash += 1
            if isinstance(signal_type, str) and signal_type:
                content_hash_by_signal_type[signal_type] += 1
        if isinstance(evidence_tier, str) and evidence_tier:
            evidence_tier_counts[evidence_tier] += 1
        if isinstance(span_kind, str) and span_kind:
            span_kind_counts[span_kind] += 1
        if signal_type == "read" and span_kind == "broad":
            broad_read_count += 1
        if signal_type == "memory_search_hit" and entry.get("followThrough") in {None, "", "none", "unknown"}:
            raw_search_only_count += 1
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        reason = warning.get("reason")
        if isinstance(reason, str) and reason:
            warning_reason_counts[reason] += 1
    return {
        "entry_count": len(entries),
        "covered_file_count": len(covered_paths),
        "signal_type_counts": dict(sorted(signal_type_counts.items())),
        "weighted_signal_counts": dict(sorted(weighted_signal_counts.items())),
        "raw_event_counts": dict(sorted(raw_event_counts.items())),
        "evidence_tier_counts": dict(sorted(evidence_tier_counts.items())),
        "span_kind_counts": dict(sorted(span_kind_counts.items())),
        "broad_read_count": broad_read_count,
        "raw_search_only_count": raw_search_only_count,
        "entries_with_content_hash": entries_with_content_hash,
        "entries_without_content_hash": len(entries) - entries_with_content_hash,
        "content_hash_by_signal_type": dict(sorted(content_hash_by_signal_type.items())),
        "warning_reason_counts": dict(sorted(warning_reason_counts.items())),
        "warning_count": len(warnings),
    }




def dedupe_warnings(warnings: list[Any]) -> list[Any]:
    """Return warnings with exact duplicate metadata collapsed.

    Session/tool logs can produce one unresolved span warning per edit block even
    when the same tool call/source has already established that the span cannot
    be resolved. Collapse exact duplicate warning records so warning counts track
    distinct telemetry problems rather than repeated blocks from the same call.
    """

    deduped: list[Any] = []
    seen: set[str] = set()
    for warning in warnings:
        if not isinstance(warning, dict):
            deduped.append(warning)
            continue
        key = json.dumps(warning, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped

def build_telemetry(*, source_window_days: int, generated_at_utc: str | None = None) -> dict[str, Any]:
    generated_at = generated_at_utc or utc_now_iso()
    read_entries, read_warnings = collect_direct_read_events(
        source_window_days=source_window_days, generated_at_utc=generated_at
    )
    search_entries, search_warnings = collect_memory_search_hit_events(
        source_window_days=source_window_days, generated_at_utc=generated_at
    )
    memory_get_entries, memory_get_warnings = collect_memory_get_events(
        source_window_days=source_window_days, generated_at_utc=generated_at
    )
    final_citation_entries, final_citation_warnings = collect_final_citation_events(
        source_window_days=source_window_days, generated_at_utc=generated_at
    )
    context_edit_entries, context_edit_warnings = collect_context_edit_events(
        source_window_days=source_window_days, generated_at_utc=generated_at
    )
    entries = {
        **read_entries,
        **search_entries,
        **memory_get_entries,
        **final_citation_entries,
        **context_edit_entries,
    }
    annotate_search_follow_through(entries)
    warnings = dedupe_warnings([
        *read_warnings,
        *search_warnings,
        *memory_get_warnings,
        *final_citation_warnings,
        *context_edit_warnings,
    ])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "source_window_days": source_window_days,
        "workspace_root": str(WORKBENCH_ROOT),
        "context_root": str(WORKBENCH_CONTEXT_ROOT),
        "entries": entries,
        "summary": summarize_entries(entries, warnings),
        "warnings": warnings,
    }


def compact_entry_source_hash(entry: dict[str, Any]) -> str | None:
    source_hash = entry.get("sourceHash")
    if isinstance(source_hash, str) and source_hash:
        return source_hash
    source_hashes = entry.get("sourceHashes")
    if isinstance(source_hashes, list):
        for value in source_hashes:
            if isinstance(value, str) and value:
                return value
    return None


def compact_telemetry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for field in COMPACT_HOT_ENTRY_FIELDS:
        if field == "sourceHash":
            source_hash = compact_entry_source_hash(entry)
            if source_hash is not None:
                compacted[field] = source_hash
            continue
        if field in entry:
            compacted[field] = entry[field]
    refresh_entry_taxonomy(compacted)
    source_hash = compact_entry_source_hash(entry)
    if source_hash is not None:
        compacted["sourceHash"] = source_hash
    return {field: value for field, value in compacted.items() if field in COMPACT_HOT_ENTRY_FIELDS}


def telemetry_entry_last_seen(entry: dict[str, Any]) -> datetime | None:
    parsed = parse_iso_datetime(entry.get("lastSeenAt")) or parse_iso_datetime(entry.get("firstSeenAt"))
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compact_entry_priority(entry: dict[str, Any]) -> tuple[int, int, int, str]:
    tier_rank = {"strong": 3, "medium": 2, "weak": 1, "invalid": 0}.get(str(entry.get("evidenceTier") or ""), 0)
    protected_rank = 1 if entry.get("protectsFromPrune") is True else 0
    last_seen = telemetry_entry_last_seen(entry)
    last_seen_epoch = int(last_seen.timestamp()) if last_seen is not None else 0
    return (protected_rank, tier_rank, last_seen_epoch, str(entry.get("path") or ""))


def compact_telemetry_hot_json(
    data: dict[str, Any],
    *,
    generated_at_utc: str | None = None,
    source_window_days: int = DEFAULT_COMPACT_SOURCE_WINDOW_DAYS,
    max_hot_entries: int = DEFAULT_MAX_HOT_ENTRIES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    generated_at = generated_at_utc or str(data.get("generated_at_utc") or utc_now_iso())
    reference_dt = parse_iso_datetime(generated_at) or datetime.now(timezone.utc)
    if reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=timezone.utc)
    cutoff = reference_dt.astimezone(timezone.utc) - timedelta(days=source_window_days)
    entries = data.get("entries") if isinstance(data.get("entries"), dict) else {}
    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []

    recent_entries: list[tuple[str, dict[str, Any]]] = []
    dropped_expired = 0
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        last_seen = telemetry_entry_last_seen(entry)
        if last_seen is not None and last_seen < cutoff:
            dropped_expired += 1
            continue
        recent_entries.append((str(key), entry))

    recent_entries.sort(key=lambda pair: compact_entry_priority(pair[1]), reverse=True)
    kept_pairs = recent_entries[:max_hot_entries]
    compact_entries = {key: compact_telemetry_entry(entry) for key, entry in sorted(kept_pairs)}
    removed_verbose_fields = 0
    for key, entry in kept_pairs:
        if isinstance(entry, dict):
            removed_verbose_fields += len([field for field in entry if field not in COMPACT_HOT_ENTRY_FIELDS])

    manifest = {
        "schema_version": "workbench-context-usage-telemetry-compaction/v1",
        "generated_at_utc": generated_at,
        "source_window_days": source_window_days,
        "max_hot_entries": max_hot_entries,
        "compact_hot_json": True,
        "entry_count_before": len(entries),
        "entry_count_after": len(compact_entries),
        "dropped_expired_entry_count": dropped_expired,
        "dropped_overflow_entry_count": max(0, len(recent_entries) - len(kept_pairs)),
        "removed_verbose_field_count": removed_verbose_fields,
        "allowed_entry_fields": list(COMPACT_HOT_ENTRY_FIELDS),
    }
    compacted = {
        **{key: value for key, value in data.items() if key not in {"entries", "summary"}},
        "generated_at_utc": generated_at,
        "source_window_days": source_window_days,
        "entries": compact_entries,
        "summary": summarize_entries(compact_entries, warnings),
        "compaction": manifest,
    }
    return compacted, manifest


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def load_telemetry(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"telemetry JSON not found: {path}; run `refresh` first") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"telemetry JSON is invalid: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"telemetry JSON root must be an object: {path}")
    return data


def render_markdown(data: dict[str, Any]) -> str:
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    signal_counts = summary.get("signal_type_counts") if isinstance(summary.get("signal_type_counts"), dict) else {}
    weighted_signal_counts = (
        summary.get("weighted_signal_counts") if isinstance(summary.get("weighted_signal_counts"), dict) else {}
    )
    raw_event_counts = summary.get("raw_event_counts") if isinstance(summary.get("raw_event_counts"), dict) else {}
    evidence_tier_counts = (
        summary.get("evidence_tier_counts") if isinstance(summary.get("evidence_tier_counts"), dict) else {}
    )
    span_kind_counts = summary.get("span_kind_counts") if isinstance(summary.get("span_kind_counts"), dict) else {}
    content_hash_by_signal_type = (
        summary.get("content_hash_by_signal_type") if isinstance(summary.get("content_hash_by_signal_type"), dict) else {}
    )
    warning_reason_counts = (
        summary.get("warning_reason_counts") if isinstance(summary.get("warning_reason_counts"), dict) else {}
    )
    signal_text = ", ".join(f"{key}={value}" for key, value in sorted(signal_counts.items())) or "none"
    weighted_signal_text = ", ".join(
        f"{key}={value}" for key, value in sorted(weighted_signal_counts.items())
    ) or "none"
    raw_event_text = ", ".join(f"{key}={value}" for key, value in sorted(raw_event_counts.items())) or "none"
    evidence_tier_text = ", ".join(f"{key}={value}" for key, value in sorted(evidence_tier_counts.items())) or "none"
    span_kind_text = ", ".join(f"{key}={value}" for key, value in sorted(span_kind_counts.items())) or "none"
    content_hash_text = ", ".join(
        f"{key}={value}" for key, value in sorted(content_hash_by_signal_type.items())
    ) or "none"
    warning_reason_text = ", ".join(
        f"{key}={value}" for key, value in sorted(warning_reason_counts.items())
    ) or "none"
    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
    lines = [
        "# Workbench Context Usage Telemetry",
        "",
        f"- schema: `{data.get('schema_version', '<missing>')}`",
        f"- generated: `{data.get('generated_at_utc', '<missing>')}`",
        f"- source window days: `{data.get('source_window_days', '<missing>')}`",
        f"- workspace root: `{data.get('workspace_root', '<missing>')}`",
        f"- context root: `{data.get('context_root', '<missing>')}`",
        f"- session log root: `{WORKBENCH_SESSION_LOG_ROOT}`",
        f"- entries: `{summary.get('entry_count', 0)}`",
        f"- covered files: `{summary.get('covered_file_count', 0)}`",
        f"- signal counts: {signal_text}",
        f"- weighted signal counts: {weighted_signal_text}",
        f"- raw event counts: {raw_event_text}",
        f"- evidence tier counts: {evidence_tier_text}",
        f"- span kind counts: {span_kind_text}",
        f"- broad read entries: `{summary.get('broad_read_count', 0)}`",
        f"- raw search-only entries: `{summary.get('raw_search_only_count', 0)}`",
        f"- entries with content hash: `{summary.get('entries_with_content_hash', 0)}`",
        f"- entries without content hash: `{summary.get('entries_without_content_hash', 0)}`",
        f"- content hash by signal type: {content_hash_text}",
        f"- warnings: `{summary.get('warning_count', len(warnings))}`",
        f"- warning reason counts: {warning_reason_text}",
        "",
    ]
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings[:20]:
            lines.append(f"- `{warning}`")
        if len(warnings) > 20:
            lines.append(f"- ... {len(warnings) - 20} more warnings omitted")
        lines.append("")
    else:
        lines.append("No telemetry warnings.")
        lines.append("")
    return "\n".join(lines)


def command_refresh(args: argparse.Namespace) -> int:
    source_window_days = args.source_window_days or args.window_days
    telemetry = build_telemetry(source_window_days=source_window_days)
    if args.compact_hot_json:
        telemetry, _manifest = compact_telemetry_hot_json(
            telemetry,
            source_window_days=source_window_days,
            max_hot_entries=args.max_hot_entries,
        )
    write_json_atomic(args.output_json, telemetry)
    if args.write_markdown:
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(render_markdown(telemetry), encoding="utf-8")
    summary = telemetry["summary"]
    compact = 1 if args.compact_hot_json else 0
    print(
        "CONTEXT_USAGE_TELEMETRY_REFRESH_OK "
        f"entries={summary['entry_count']} covered_files={summary['covered_file_count']} "
        f"warnings={summary['warning_count']} compact={compact} output={args.output_json}"
    )
    return 0


def command_report(args: argparse.Namespace) -> int:
    telemetry = load_telemetry(args.input_json)
    report = render_markdown(telemetry)
    if args.write_markdown:
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(report, encoding="utf-8")
        print(f"CONTEXT_USAGE_TELEMETRY_REPORT_OK output={args.output_markdown}")
    else:
        print(report, end="")
    return 0


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh and report Workbench context-usage telemetry metadata."
    )
    parser.add_argument(
        "--telemetry-json",
        type=Path,
        default=TELEMETRY_JSON_PATH,
        help=f"Telemetry JSON path (default: {TELEMETRY_JSON_PATH})",
    )
    parser.add_argument(
        "--telemetry-markdown",
        type=Path,
        default=TELEMETRY_MARKDOWN_PATH,
        help=f"Telemetry Markdown path (default: {TELEMETRY_MARKDOWN_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="Refresh context-usage telemetry JSON.")
    refresh.add_argument(
        "--window-days",
        type=positive_int,
        default=DEFAULT_SOURCE_WINDOW_DAYS,
        help=f"Source lookback window in days (default: {DEFAULT_SOURCE_WINDOW_DAYS})",
    )
    refresh.add_argument(
        "--source-window-days",
        type=positive_int,
        default=None,
        help="Source lookback window in days; preferred name for compact scheduled refreshes.",
    )
    refresh.add_argument(
        "--max-hot-entries",
        type=positive_int,
        default=DEFAULT_MAX_HOT_ENTRIES,
        help=f"Maximum compact hot telemetry entries to retain (default: {DEFAULT_MAX_HOT_ENTRIES})",
    )
    refresh.add_argument(
        "--compact-hot-json",
        action="store_true",
        help="Write compact hot JSON entries retaining only pruning-classifier fields.",
    )
    refresh.add_argument(
        "--write-markdown",
        action="store_true",
        help="Also write the current human-readable Markdown report.",
    )
    refresh.set_defaults(func=command_refresh)

    report = subparsers.add_parser("report", help="Render a compact report from telemetry JSON.")
    report.add_argument(
        "--write-markdown",
        action="store_true",
        help="Write the report to the telemetry Markdown path instead of stdout.",
    )
    report.set_defaults(func=command_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.output_json = args.telemetry_json
    args.input_json = args.telemetry_json
    args.output_markdown = args.telemetry_markdown
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
