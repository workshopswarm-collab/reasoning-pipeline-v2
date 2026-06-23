#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import difflib
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

MAINTENANCE_ROOT = Path(__file__).resolve().parents[2]
if str(MAINTENANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_ROOT))

from lib.maintenance_run import (  # noqa: E402
    RunEnvelope,
    atomic_write_json,
    atomic_write_text,
    envelope_ref,
    make_run_id,
    preflight_path_exists,
    preflight_writable_dir,
)

WORKBENCH_ROOT = Path(os.environ.get("WORKBENCH_ROOT", "/Users/agent2/.openclaw/workbench"))
CONTEXT_ROOT = WORKBENCH_ROOT / "context"
STATE_PATH = CONTEXT_ROOT / "state" / "context-pruning-state.json"
REPORT_PATH = CONTEXT_ROOT / "state" / "context-pruning-report.md"
CONTEXT_TELEMETRY_PATH = CONTEXT_ROOT / "state" / "context-usage-telemetry.json"
ARCHIVE_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive" / "section-prune"
STATE_ARCHIVE_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive" / "state-prune"
STATE_REBASE_ARCHIVE_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive" / "state-rebase"
STATE_HISTORY_SHARD_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive" / "state-history-shards"
DECISIONS_CONSOLIDATION_ARCHIVE_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive" / "decisions-consolidation"
STATE_REBASE_PREVIEW_PATH = STATE_PATH.parent / "context-pruning-state-rebase-preview.json"
STATE_REBASE_MANIFEST_PATH = STATE_PATH.parent / "context-pruning-state.rebase-manifest.json"
STATE_COMPACTION_PREVIEW_PATH = STATE_PATH.parent / "context-pruning-state-compaction-preview.json"
STATE_COMPACTION_MANIFEST_PATH = STATE_PATH.parent / "context-pruning-state.compaction-manifest.json"
STATE_COMPACT_CURRENT_ENTRY_FIELDS = (
    "firstSeenAt",
    "seenRuns",
    "recallRuns",
    "unrecalledRuns",
    "lastCountedBucket",
    "identityKey",
)
STATE_COMPACT_RETAINED_ENTRY_FIELDS = (
    "lastMissingAt",
    "seenRuns",
    "unrecalledRuns",
)
RECALL_STORE_PATH = WORKBENCH_ROOT / "memory" / ".dreams" / "short-term-recall.json"
MODEL_LOCK_ROOT = Path.home() / ".openclaw" / "locks"
GENERATED_ROOT = MAINTENANCE_ROOT / "workbench-context-maintenance" / "generated"
RUNS_ROOT = GENERATED_ROOT / "runs"
DECISIONS_CONSOLIDATION_ROOT = GENERATED_ROOT / "decisions-consolidation"
DEFAULT_LOCAL_COMPRESS_MODEL = "qwen3.5:4b"
DEFAULT_OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_LOCAL_COMPRESS_LOCK_TIMEOUT_SECONDS = 600.0
MODEL_PRIORITY_STALE_SECONDS = 30 * 60

HOT_DOCS = [
    Path("context/bootstrap.md"),
    Path("context/active.md"),
    Path("context/decisions.md"),
    Path("context/projects/_index.md"),
    Path("context/projects/quant-pipeline.md"),
    Path("context/projects/workbench-context.md"),
]

APPLY_ALLOWED = {
    Path("context/active.md"),
    Path("context/projects/quant-pipeline.md"),
    Path("context/projects/workbench-context.md"),
}
QUANT_PIPELINE_PATH = Path("context/projects/quant-pipeline.md")
DEFAULT_MAX_FILE_SHRINK_RATIO = 0.35

DOC_PROFILES = {
    Path("context/active.md"): "active_hot_doc",
    Path("context/projects/quant-pipeline.md"): "project_spine",
}

NON_PRUNABLE = {
    Path("context/bootstrap.md"),
    Path("context/decisions.md"),
    Path("context/projects/_index.md"),
}

ACTIVE_LIVE_HEADINGS = {
    "Current focus",
    "Immediate next actions",
    "Watchouts",
    "Open questions",
}
ACTIVE_DATED_HEADING_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}\b")
ACTIVE_DOC_TARGET_BYTES = 20_000
ACTIVE_DOC_HARD_BYTES = 25_000
ACTIVE_LIVE_HEADING_SUMMARY_TOLERANCE_CHARS = 120
ACTIVE_RECENT_PROTECT_DAYS = 3
ACTIVE_REVIEW_AFTER_DAYS = 4
ACTIVE_COMPRESS_AFTER_DAYS = 11

HOT_CONTEXT_BUDGETS = {
    Path("context/bootstrap.md"): {"target_bytes": 5_000, "hard_bytes": 7_000, "mode": "autonomous_summary"},
    Path("context/active.md"): {"target_bytes": ACTIVE_DOC_TARGET_BYTES, "hard_bytes": ACTIVE_DOC_HARD_BYTES, "mode": "apply_allowed"},
    Path("context/projects/quant-pipeline.md"): {"target_bytes": 100_000, "hard_bytes": 125_000, "mode": "apply_allowed"},
    Path("context/projects/workbench-context.md"): {"target_bytes": 10_000, "hard_bytes": 12_000, "mode": "apply_allowed"},
    Path("context/decisions.md"): {"target_bytes": 15_000, "hard_bytes": 18_000, "mode": "autonomous_consolidation"},
}
STATE_FILE_BUDGETS = {
    Path("context/state/context-pruning-state.json"): {"target_bytes": 250_000, "hard_bytes": 500_000},
    Path("context/state/context-usage-telemetry.json"): {"target_bytes": 250_000, "hard_bytes": 500_000},
}
DECISIONS_PATH = Path("context/decisions.md")
DECISIONS_TARGET_BYTES = int(HOT_CONTEXT_BUDGETS[DECISIONS_PATH]["target_bytes"])
DECISIONS_HARD_BYTES = int(HOT_CONTEXT_BUDGETS[DECISIONS_PATH]["hard_bytes"])
DECISIONS_MEDIUM_SECTION_CHARS = 5_000
DECISIONS_HIGH_SECTION_CHARS = 8_000
DECISIONS_CONSOLIDATION_SCHEMA_VERSION = "workbench-decisions-consolidation-plan/v1"
DECISIONS_BACKLOG_SCHEMA_VERSION = "workbench-decisions-consolidation-backlog/v1"
DECISIONS_BACKLOG_REPEAT_THRESHOLD = 3
DECISIONS_BACKLOG_HISTORY_LIMIT = 50
ACTIVE_LIVE_HEADING_BUDGETS = {
    "Current focus": {"target_bytes": 10_000, "hard_bytes": 12_000, "summary_max_chars": 2_500, "mode": "active_live_heading_summary"},
    "Immediate next actions": {"target_bytes": 6_000, "hard_bytes": 8_000, "summary_max_chars": 1_500, "mode": "active_live_heading_summary"},
}
PROTECTED_BUDGET_DEBT_RECORD_LIMIT = 20
UNRESOLVED_MARKER_RE = re.compile(
    r"\b(unresolved|blocked|blocker|pending|open question|in progress|current|next action|todo|follow-?up|watchout)\b",
    re.I,
)
ACTIVE_LIVE_SUMMARY_REQUIRED_MARKER_RE = re.compile(
    r"\b(unresolved|blocked|blocker|pending|open question|in progress|next actions?|todo|follow(?:-| )?up|watchout)\b",
    re.I,
)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BULLET_RE = re.compile(r"^(\s*)([-*+]\s+|\d+\.\s+)(.*\S)?\s*$")
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
HISTORICAL_HEADING_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|histor|legacy|migration|reset|simplif|old\b|prior\b)\b", re.I)
KEEP_COMMENT_RE = re.compile(r"openclaw:prune:keep", re.I)

PROJECT_SPINE_STABLE_HEADINGS = {
    "role",
    "default folder / routing",
    "stable orientation",
    "objective function",
    "scope / layer boundary",
    "current architecture",
    "active pipeline path",
    "maturity / current posture",
    "operational invariants",
}

PROJECT_SPINE_PINNED_HEADINGS = PROJECT_SPINE_STABLE_HEADINGS | {
    # Legacy/local aliases retained so existing project-spine wording stays pinned
    # until the context file is normalized onto the stable heading contract.
    "default folder",
    "current maturity snapshot",
    "scope rule",
    "current live architecture",
    "pipeline invariants that matter",
    "top-level repo map",
    "update rule",
}

PROJECT_SPINE_VOLATILE_HEADINGS = {
    "current active implementation concerns",
    "known gaps / likely follow-ups",
}

PROJECT_SPINE_HARD_PRESSURE_CHARS = 50_000
PROJECT_SPINE_SOFT_TARGET_CHARS = 30_000
PROJECT_SPINE_DATED_SECTION_CHARS = 2_000
PROJECT_SPINE_VOLATILE_BULLET_CHARS = 500
PROJECT_SPINE_REVIEW_SECTION_CHARS = 8_000
PROJECT_SPINE_REVIEW_BULLET_CHARS = 1_200
PROJECT_SPINE_COMPRESSED_NOTE_LIMIT = 5
COMPRESSED_SUMMARY_MAX_CHARS = 220
COMPRESSED_NOTE_MAX_CHARS = 240
COMPRESSED_ITEM_PRUNE_DAYS = 7
LOCAL_COMPRESSED_SUMMARY_MAX_CHARS = 700
LOCAL_COMPRESSED_NOTE_MAX_CHARS = 950
LOCAL_COMPRESS_MAX_BLOCKS = 3
STATE_TOMBSTONE_RETENTION_DAYS = 14
STATE_HISTORY_SHARD_MAX_ENTRIES = 500
STATE_COMPACTION_DROPPED_SAMPLE_LIMIT = 20
HIGH_USAGE_RECALL_RUNS = 3
HIGH_USAGE_RECALL_SIGNALS = 5

LAST_RECALL_LOAD_STATS: dict[str, object] = {}
LAST_CONTEXT_TELEMETRY_HITS: dict[str, list[RecallHit]] = {}
LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX: object | None = None
LAST_CONTEXT_TELEMETRY_MATCH_STATS: dict[str, object] = {}

DEFAULT_STALE_DAYS = 8
DEFAULT_DORMANT_DAYS = 4
DEFAULT_RECENT_GRACE_DAYS = 3
DEFAULT_MIN_SEEN_RUNS_REVIEW = 2
DEFAULT_MIN_SEEN_RUNS_PRUNE = 3
DEFAULT_MIN_UNRECALLED_RUNS_REVIEW = 2
DEFAULT_MIN_UNRECALLED_RUNS_PRUNE = 3
DEFAULT_IDENTITY_MODE = "content-primary"
IDENTITY_MODES = ("content-primary", "line-legacy")
DEFAULT_CONTEXT_TELEMETRY_PROTECTIVE_MAX_AGE_DAYS = DEFAULT_STALE_DAYS
MIN_SECTION_CHARS = 500
MIN_BULLET_CHARS = 160
ACTIVE_STALE_SECTION_MIN_CHARS = MIN_SECTION_CHARS


@dataclass
class RecallHit:
    start_line: int
    end_line: int
    signal_count: int
    last_recalled_at: str | None


@dataclass
class ShadowTelemetryHit:
    start_line: int
    end_line: int
    signal_count: int
    last_seen_at: str | None
    signal_type: str
    evidence_tier: str
    span_kind: str


@dataclass
class TelemetryEvidenceHit:
    start_line: int
    end_line: int
    signal_count: int
    last_seen_at: str | None
    signal_type: str
    evidence_tier: str
    span_kind: str
    protects_from_prune: bool
    follow_through: str
    tier_reason: str
    content_hash: str | None
    entry_key: str = ""


@dataclass
class TelemetryEvidenceIndexes:
    by_path: dict[str, list[TelemetryEvidenceHit]]
    by_path_and_span: dict[tuple[str, int, int], list[TelemetryEvidenceHit]]
    by_path_and_content_hash: dict[tuple[str, str], list[TelemetryEvidenceHit]]


@dataclass
class ShadowEvidence:
    strong: int = 0
    medium: int = 0
    weak: int = 0
    invalid: int = 0
    unknown: int = 0
    broad_read: int = 0
    strong_medium_signal_count: int = 0
    total: int = 0

    def tier_counts(self) -> dict[str, int]:
        return {
            key: value
            for key, value in {
                "strong": self.strong,
                "medium": self.medium,
                "weak": self.weak,
                "invalid": self.invalid,
                "unknown": self.unknown,
            }.items()
            if value
        }


@dataclass
class ItemEvidence:
    dream_strong_hits: int = 0
    telemetry_strong_targeted: int = 0
    telemetry_medium_targeted: int = 0
    telemetry_weak_only: int = 0
    telemetry_broad_read_only: int = 0
    telemetry_invalid: int = 0
    telemetry_unknown: int = 0
    strong_signal_count: int = 0
    medium_signal_count: int = 0
    weak_signal_count: int = 0
    total_hits: int = 0
    telemetry_match_source: str = "none"
    content_hash_recovered_hits: int = 0
    content_hash_recovered_strong_hits: int = 0
    content_hash_recovered_strong_signal_count: int = 0
    ambiguous_content_hash_hits: int = 0

    @property
    def has_strong_targeted(self) -> bool:
        return self.dream_strong_hits > 0 or self.telemetry_strong_targeted > 0

    @property
    def has_only_weak_or_broad(self) -> bool:
        return (
            self.total_hits > 0
            and not self.has_strong_targeted
            and self.telemetry_medium_targeted == 0
            and (self.telemetry_weak_only > 0 or self.telemetry_broad_read_only > 0)
            and self.telemetry_invalid == 0
            and self.telemetry_unknown == 0
        )

    @property
    def has_medium_without_strong(self) -> bool:
        return self.telemetry_medium_targeted > 0 and not self.has_strong_targeted

    @property
    def evidence_class(self) -> str:
        if self.has_strong_targeted:
            return "strong_targeted"
        if self.telemetry_medium_targeted > 0:
            return "medium_targeted"
        if self.telemetry_weak_only > 0 or self.telemetry_broad_read_only > 0:
            return "weak_or_broad_only"
        if self.telemetry_invalid > 0 or self.telemetry_unknown > 0:
            return "invalid_or_unknown"
        return "none"


@dataclass
class AuditConfig:
    stale_days: int
    dormant_days: int
    recent_grace_days: int
    min_seen_runs_review: int
    min_seen_runs_prune: int
    min_unrecalled_runs_review: int
    min_unrecalled_runs_prune: int


@dataclass
class LocalCompressionConfig:
    enabled: bool
    model: str
    ollama_url: str
    max_blocks: int
    timeout_seconds: int
    lock_timeout_seconds: float
    max_summary_chars: int
    priority: bool = True


@dataclass
class Item:
    key: str
    kind: str
    path: str
    section_heading: str
    heading_level: int
    start_line: int
    end_line: int
    char_count: int
    text_hash: str
    explicit_dates: list[str]
    recall_hits: int
    recall_signal_count: int
    last_recalled_at: str | None
    age_days: float
    pinned: bool
    seen_runs: int
    recall_runs: int
    unrecalled_runs: int
    classification: str
    reason: str
    fingerprint: str = ""
    identity_key: str = ""
    identity_mode: str = ""
    evidence_class: str = "none"
    strong_evidence_hits: int = 0
    medium_evidence_hits: int = 0
    weak_broad_evidence_hits: int = 0
    telemetry_match_source: str = "none"
    content_hash_recovered_hits: int = 0


@dataclass
class StateRebaseCandidate:
    key: str
    kind: str
    path: str
    section_heading: str
    heading_level: int
    start_line: int
    end_line: int
    char_count: int
    text_hash: str
    fingerprint: str
    identity_key: str
    identity_mode: str
    exact_aliases: list[str]
    prefix_aliases: list[str]
    fingerprint_aliases: list[str]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_bucket_from_iso(value: str) -> str:
    return value[:10]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(v)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def days_between(a: datetime, b: datetime) -> float:
    return max(0.0, (a - b).total_seconds() / 86400.0)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def normalize_identity_mode(identity_mode: str | None) -> str:
    mode = identity_mode or DEFAULT_IDENTITY_MODE
    if mode not in IDENTITY_MODES:
        raise ValueError(f"unknown identity mode: {mode}")
    return mode


def normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return "\n".join(lines).strip()


def text_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def normalized_item_text_for_fingerprint(text: str) -> str:
    return normalize_text(text)


def normalized_path_for_fingerprint(path_rel: Path) -> str:
    return path_rel.as_posix()


def item_fingerprint(path_rel: Path, kind: str, heading: str, text: str) -> str:
    material = "\0".join(
        [
            "workbench-context-item-fingerprint-v1",
            normalized_path_for_fingerprint(path_rel),
            kind,
            slugify(heading),
            hashlib.sha1(normalized_item_text_for_fingerprint(text).encode("utf-8")).hexdigest()[:16],
        ]
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


def item_fingerprint_key(path_rel: Path, kind: str, heading: str, text: str) -> str:
    return (
        f"fingerprint:{normalized_path_for_fingerprint(path_rel)}:"
        f"{kind}:{slugify(heading)}:{item_fingerprint(path_rel, kind, heading, text)}"
    )


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "untitled"


def normalized_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def doc_profile(path_rel: Path) -> str:
    return DOC_PROFILES.get(path_rel, "default")


def is_active_doc(path_rel: Path) -> bool:
    return doc_profile(path_rel) == "active_hot_doc"


def is_active_live_heading(heading: str) -> bool:
    live = {normalized_heading(item) for item in ACTIVE_LIVE_HEADINGS}
    return normalized_heading(heading) in live


def active_live_heading_budget(heading: str) -> dict[str, object] | None:
    normalized = normalized_heading(heading)
    for budget_heading, budget in ACTIVE_LIVE_HEADING_BUDGETS.items():
        if normalized_heading(budget_heading) == normalized:
            return budget
    return None


def is_active_dated_heading(heading: str) -> bool:
    return bool(ACTIVE_DATED_HEADING_RE.match(heading.strip()))


def active_evidence_suffix(evidence: ItemEvidence) -> str:
    return "-weak-broad" if evidence.has_only_weak_or_broad else ""


def active_section_pressure_ready(
    *,
    path_rel: Path,
    kind: str,
    heading: str,
    text: str,
    doc_char_count: int,
    item_age_days: float,
    seen_runs: int,
    unrecalled_runs: int,
    evidence: ItemEvidence,
    config: AuditConfig,
    strong_current_evidence: bool | None = None,
) -> tuple[bool, str]:
    if not is_active_doc(path_rel):
        return False, "not-active-doc"
    if KEEP_COMMENT_RE.search(text):
        return False, "pinned"
    if is_active_live_heading(heading):
        return False, "active-hot-doc-live-heading-protected"
    if kind != "section":
        return False, "not-active-section"
    if not is_active_dated_heading(heading):
        return False, "not-active-dated-heading"
    if len(text) < ACTIVE_STALE_SECTION_MIN_CHARS:
        return False, "active-hot-doc-stale-dated-too-small"
    current_strong = evidence.has_strong_targeted if strong_current_evidence is None else strong_current_evidence
    if current_strong:
        return False, "active-hot-doc-strong-evidence-protected"
    if item_age_days <= ACTIVE_RECENT_PROTECT_DAYS:
        return False, "active-hot-doc-recent-protected"
    review_age_ready = item_age_days >= max(config.dormant_days, ACTIVE_REVIEW_AFTER_DAYS)
    review_history_ready = seen_runs >= config.min_seen_runs_review and unrecalled_runs >= config.min_unrecalled_runs_review
    if not (review_age_ready and review_history_ready):
        return False, "active-hot-doc-gathering-history"
    prune_history_ready = seen_runs >= config.min_seen_runs_prune and unrecalled_runs >= config.min_unrecalled_runs_prune
    if evidence.has_strong_targeted and not current_strong:
        return True, "active-hot-doc-stale-dated-review"
    if evidence.has_medium_without_strong:
        return True, "active-hot-doc-stale-dated-review"
    hard_pressure = doc_char_count >= ACTIVE_DOC_HARD_BYTES
    suffix = active_evidence_suffix(evidence)
    if prune_history_ready and (item_age_days >= ACTIVE_COMPRESS_AFTER_DAYS or hard_pressure):
        return True, f"active-hot-doc-stale-dated{suffix}-compress"
    return True, f"active-hot-doc-stale-dated{suffix}-review"


def active_live_heading_budget_ready(
    *,
    path_rel: Path,
    heading: str,
    text: str,
    doc_char_count: int,
    item_age_days: float,
    evidence: ItemEvidence,
) -> tuple[bool, str]:
    if not is_active_doc(path_rel):
        return False, "not-active-doc"
    if KEEP_COMMENT_RE.search(text):
        return False, "pinned"
    if not is_active_live_heading(heading):
        return False, "not-active-live-heading"
    budget = active_live_heading_budget(heading)
    if budget is None:
        return False, "active-hot-doc-live-heading-protected"
    if evidence.has_strong_targeted and item_age_days <= ACTIVE_RECENT_PROTECT_DAYS:
        return False, "active-hot-doc-strong-evidence-protected"
    byte_count = len(text.encode("utf-8"))
    target = int(budget["target_bytes"])
    hard = int(budget["hard_bytes"])
    file_target_ready = doc_char_count >= ACTIVE_DOC_TARGET_BYTES
    file_hard_ready = doc_char_count >= ACTIVE_DOC_HARD_BYTES
    if byte_count >= hard or file_hard_ready:
        return True, "active-hot-doc-live-heading-budget-summarize"
    if byte_count >= target and file_target_ready:
        return True, "active-hot-doc-live-heading-budget-review"
    return False, "active-hot-doc-live-heading-protected"


def is_project_spine(path_rel: Path) -> bool:
    return doc_profile(path_rel) == "project_spine"


def is_project_spine_stable_heading(heading: str) -> bool:
    return normalized_heading(heading) in PROJECT_SPINE_STABLE_HEADINGS


def is_project_spine_pinned_heading(heading: str) -> bool:
    return is_project_spine_stable_heading(heading) or normalized_heading(heading) in PROJECT_SPINE_PINNED_HEADINGS


def is_project_spine_volatile_heading(heading: str) -> bool:
    h = normalized_heading(heading)
    return h in PROJECT_SPINE_VOLATILE_HEADINGS or bool(re.match(r"^20\d{2}-\d{2}-\d{2}\b", h))


def is_project_spine_section_prunable(heading: str) -> bool:
    """Sections we may remove wholesale under pressure.

    `Current active implementation concerns` is volatile, but it can contain useful
    current-state bullets, so prune oversized bullets inside it rather than deleting
    the whole section automatically. `Known gaps / likely follow-ups` is also a
    high-level section: prune bulky bullets inside it, not the section container.
    """
    h = normalized_heading(heading)
    return bool(re.match(r"^20\d{2}-\d{2}-\d{2}\b", h))


def supports_compressed_replacement(item: "Item", removed_text: str) -> bool:
    """Return whether an apply candidate should leave a compact breadcrumb.

    Candidate selection remains the safety gate. For the quant-pipeline project
    spine, only volatile/datable sections should be compressed in place. For the
    smaller hot docs that are allowed to mutate, any prune candidate may leave a
    compact archived-detail note instead of disappearing entirely.
    """
    if item.reason in {"compressed-archive-note-cap", "compressed-archive-note-aged-unused"}:
        return False
    path = Path(item.path)
    if path not in APPLY_ALLOWED:
        return False
    if is_project_spine(path):
        return is_project_spine_volatile_heading(item.section_heading)
    return True


def is_project_spine_oversized_for_review(kind: str, text: str) -> bool:
    threshold = PROJECT_SPINE_REVIEW_SECTION_CHARS if kind == "section" else PROJECT_SPINE_REVIEW_BULLET_CHARS
    return len(text) >= threshold


def is_compressed_archive_line(line: str) -> bool:
    stripped = strip_markdown_marker(line)
    return stripped.startswith("Compressed archived detail (") or stripped.startswith("Compressed local summary (")


def is_compressed_archive_text(text: str) -> bool:
    for raw in text.splitlines():
        stripped = strip_markdown_marker(raw)
        if stripped:
            return is_compressed_archive_line(raw)
    return False


def is_compressed_archive_section_text(text: str) -> bool:
    """Return whether a section is just a heading plus a compressed note.

    Section replacements preserve the original heading and put the compressed
    breadcrumb beneath it. Treat that section as a new compressed item so it gets
    its own post-compression lifetime instead of inheriting the original block's
    age key.
    """
    seen_heading = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if not seen_heading and HEADING_RE.match(stripped):
            seen_heading = True
            continue
        return is_compressed_archive_line(raw)
    return False


def is_compressed_item_text(kind: str, text: str) -> bool:
    return is_compressed_archive_text(text) or (kind == "section" and is_compressed_archive_section_text(text))


def strip_markdown_marker(line: str) -> str:
    line = line.strip()
    heading = HEADING_RE.match(line)
    if heading:
        return heading.group(2).strip()
    bullet = BULLET_RE.match(line)
    if bullet:
        return (bullet.group(3) or "").strip()
    return line


def compressed_archive_body(text: str) -> str:
    for raw in text.splitlines():
        if is_compressed_archive_line(raw):
            return strip_markdown_marker(raw)
    for raw in text.splitlines():
        stripped = strip_markdown_marker(raw)
        if stripped and not HEADING_RE.match(raw.strip()):
            return stripped
    return ""


def compressed_note_max_chars(text: str) -> int:
    body = compressed_archive_body(text)
    if body.startswith("Compressed local summary ("):
        return LOCAL_COMPRESSED_NOTE_MAX_CHARS
    return COMPRESSED_NOTE_MAX_CHARS


def truncate_sentence(text: str, max_chars: int = COMPRESSED_SUMMARY_MAX_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip(" ,;:-") + "…"


def compact_summary(text: str, item: "Item") -> str:
    candidates: list[str] = []
    for raw in text.splitlines():
        stripped = strip_markdown_marker(raw)
        if not stripped or KEEP_COMMENT_RE.search(stripped):
            continue
        candidates.append(stripped)
        if len(candidates) >= 2:
            break
    if not candidates:
        candidates = [item.section_heading]
    return truncate_sentence("; ".join(candidates))


def compact_refs(text: str) -> str:
    return ", ".join(extract_refs(text)[:5])


def extract_refs(text: str) -> list[str]:
    refs: list[str] = []
    patterns = [
        r"case-20\d{6}-[a-z0-9]+",
        r"dispatch-case-20\d{6}-[a-z0-9]+-[0-9TZ]+",
        r"\b[0-9a-f]{7,12}\b",
        r"\b[a-zA-Z0-9_./-]+\.(?:py|mjs|sql|json|md)\b",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, text):
            if any(value in existing or existing in value for existing in refs):
                continue
            if value not in refs:
                refs.append(value)
    return refs


def model_lock_name(model: str) -> str:
    if "qwen" in model.lower():
        return "qwen.lock"
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-") or "local-model"
    return f"ollama-{slug}.lock"


def model_priority_path(model: str) -> Path:
    return MODEL_LOCK_ROOT / f"{model_lock_name(model)}.priority"


def parse_epoch(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def pid_is_running(value: object) -> bool:
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def priority_request_active(path: Path, *, stale_seconds: float = MODEL_PRIORITY_STALE_SECONDS) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if "pid" in payload and not pid_is_running(payload.get("pid")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return False
    created_at = parse_epoch(payload.get("created_at_epoch"))
    if created_at is None:
        try:
            created_at = path.stat().st_mtime
        except FileNotFoundError:
            return False
    if time.time() - created_at > stale_seconds:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return False
    return True


class LocalModelPriorityReservation:
    """Reserve the shared Qwen lane for a whole Workbench apply run."""

    def __init__(self, model: str, owner: str = "workbench-context-compression") -> None:
        self.model = model
        self.owner = owner
        self.path = model_priority_path(model)

    def __enter__(self):
        MODEL_LOCK_ROOT.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "pid": os.getpid(),
            "owner": self.owner,
            "created_at": now_iso(),
            "created_at_epoch": time.time(),
        }
        self.path.write_text(json.dumps(payload, sort_keys=True) + "\n")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            payload = json.loads(self.path.read_text() or "{}")
        except (FileNotFoundError, json.JSONDecodeError):
            return
        if payload.get("pid") == os.getpid() and payload.get("owner") == self.owner:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class LocalModelLock:
    def __init__(self, model: str, timeout_seconds: float, *, priority: bool = False) -> None:
        self.model = model
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.path = MODEL_LOCK_ROOT / model_lock_name(model)
        self.priority_path = model_priority_path(model)
        self.priority = priority
        self.handle = None

    def __enter__(self):
        MODEL_LOCK_ROOT.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        started = time.monotonic()
        while True:
            if not self.priority and priority_request_active(self.priority_path):
                if time.monotonic() - started >= self.timeout_seconds:
                    self.handle.close()
                    self.handle = None
                    raise TimeoutError(f"local model priority reservation active: {self.priority_path}")
                time.sleep(0.25)
                continue
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() - started >= self.timeout_seconds:
                    self.handle.close()
                    self.handle = None
                    raise TimeoutError(f"local model lock busy: {self.path}") from exc
                time.sleep(0.25)
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(json.dumps({"model": self.model, "pid": os.getpid(), "acquired_at": now_iso(), "priority": self.priority}) + "\n")
        self.handle.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None


def strip_model_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"^```(?:[a-zA-Z0-9_-]+)?\s*", "", text).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    return text


def normalize_local_summary(text: str, original_text: str, max_chars: int) -> str:
    summary = strip_model_thinking(text)
    summary = re.sub(r"\s+", " ", summary).strip()
    summary = re.sub(r"^[-*+]\s+", "", summary)
    if not summary:
        raise ValueError("local compression returned empty summary")
    lower_summary = summary.lower()
    if any(forbidden in lower_summary for forbidden in ["source of truth", "canonical truth"]):
        raise ValueError("local compression used forbidden truth-claim wording")
    reasoning_markers = [
        "thinking process",
        "analyze the request",
        "chain of thought",
        "step-by-step",
        "final answer:",
    ]
    if any(marker in lower_summary for marker in reasoning_markers):
        raise ValueError("local compression included reasoning/process text")
    original_refs = set(extract_refs(original_text))
    summary_refs = set(extract_refs(summary))
    new_refs = sorted(summary_refs - original_refs)
    if new_refs:
        raise ValueError(f"local compression introduced new refs: {', '.join(new_refs[:5])}")
    return truncate_sentence(summary, max_chars)


def build_local_compression_prompt(item: "Item", removed_text: str, max_chars: int) -> tuple[str, str]:
    system = (
        "You compress Workbench hot-context blocks for a development agent. "
        "Use only the source text. Do not invent case IDs, file paths, hashes, facts, decisions, or outcomes. "
        "Keep durable current-state value and discard implementation-diary detail. "
        "Drop transient/debug/scratch/local timestamp/command-rerun details unless they changed durable current state; "
        "do not describe discarded transient details. "
        "Return only the final compressed paragraph: no reasoning, no thinking process, no analysis, "
        "no markdown list marker, no JSON, no code fence."
    )
    user = (
        "/no_think\n"
        f"Compress this {item.kind} under heading `{item.section_heading}` to <= {max_chars} characters.\n"
        "Return only the final compressed paragraph. Do not explain your process.\n"
        "Discard transient/debug/scratch/command-rerun details; keep only durable current-state rules, decisions, refs, or blockers.\n"
        "Include important existing case IDs, commit hashes, table names, or file paths only if they appear in the source text and matter.\n"
        "Do not mention the surrounding hot-context document path unless it appears in the source text below.\n\n"
        "Source text:\n"
        f"{removed_text}"
    )
    return system, user


def call_local_compressor(removed_text: str, item: "Item", config: LocalCompressionConfig) -> str:
    system, prompt = build_local_compression_prompt(item, removed_text, config.max_summary_chars)
    req_payload = {
        "model": config.model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 280},
    }
    req = urllib.request.Request(
        config.ollama_url,
        data=json.dumps(req_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with LocalModelLock(config.model, config.lock_timeout_seconds, priority=config.priority):
        with urllib.request.urlopen(req, timeout=config.timeout_seconds) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    decoded = json.loads(raw)
    text = str(decoded.get("response") or "").strip()
    return normalize_local_summary(text, removed_text, config.max_summary_chars)


def can_local_compress(item: "Item", removed_text: str) -> bool:
    return (
        supports_compressed_replacement(item, removed_text)
        and not is_compressed_archive_text(removed_text)
        and item.char_count >= MIN_SECTION_CHARS
    )


def requires_active_live_heading_local_summary(item: "Item") -> bool:
    return (
        Path(item.path) == Path("context/active.md")
        and item.kind == "section"
        and item.reason == "active-hot-doc-live-heading-budget-summarize"
        and is_active_live_heading(item.section_heading)
    )


@dataclass(frozen=True)
class ActiveHeadingPreservationChecklist:
    current_focus: bool = False
    immediate_next_actions: bool = False
    watchouts: bool = False
    open_questions: bool = False
    dated_carryover: bool = False

    def required_categories(self) -> list[str]:
        return [
            name
            for name in [
                "current_focus",
                "immediate_next_actions",
                "watchouts",
                "open_questions",
                "dated_carryover",
            ]
            if getattr(self, name)
        ]


def active_live_summary_required_markers(text: str) -> set[str]:
    markers: set[str] = set()
    for match in ACTIVE_LIVE_SUMMARY_REQUIRED_MARKER_RE.finditer(text):
        value = match.group(1).lower().replace("-", " ")
        if value in {"blocked", "blocker"}:
            markers.add("block")
        elif value.startswith("follow"):
            markers.add("follow")
        elif value.startswith("next action"):
            markers.add("next action")
        else:
            markers.add(value)
    return markers


def build_active_heading_preservation_checklist(item: "Item", removed_text: str) -> ActiveHeadingPreservationChecklist:
    heading = normalized_heading(item.section_heading)
    text = removed_text.lower()
    action_re = re.compile(r"\b(next actions?|todo|to do|follow(?:-| )?up|finish|run|implement|repair|fix|continue|resume)\b", re.I)
    watchout_re = re.compile(r"\b(blocked|blocker|waiting|watchout|risk|failed?|failure|degraded|stale|timeout|regression)\b", re.I)
    open_question_re = re.compile(r"\b(unresolved|open question|pending|unknown|unclear|needs decision|needs review|remaining issue)\b", re.I)
    carryover_re = re.compile(r"\b(unresolved|blocked|pending|follow(?:-| )?up|in progress|timeout|still|remaining|carryover)\b", re.I)
    return ActiveHeadingPreservationChecklist(
        current_focus=heading == "current focus",
        immediate_next_actions=heading == "immediate next actions" or bool(action_re.search(text)),
        watchouts=bool(watchout_re.search(text)),
        open_questions=bool(open_question_re.search(text)),
        dated_carryover=bool(DATE_RE.search(removed_text) and carryover_re.search(text)),
    )


def active_heading_category_covered(category: str, replacement_text: str) -> bool:
    text = replacement_text.lower()
    coverage_patterns = {
        "current_focus": r"\b(current|focus|active work|working set|work remains)\b",
        "immediate_next_actions": r"\b(next|action|todo|to do|finish|run|implement|repair|fix|continue|resume|follow through)\b",
        "watchouts": r"\b(blocked|blocker|waiting|watchout|risk|failed?|failure|degraded|stale|timeout|guard|issue)\b",
        "open_questions": r"\b(unresolved|open|question|pending|unknown|unclear|needs|waiting|remaining issue|not decided)\b",
        "dated_carryover": r"\b(20\d{2}-\d{2}-\d{2}|carryover|still|remaining|since|from prior|older)\b",
    }
    pattern = coverage_patterns.get(category)
    return bool(pattern and re.search(pattern, text, re.I))


def score_active_heading_replacement(
    checklist: ActiveHeadingPreservationChecklist,
    replacement_text: str,
) -> tuple[bool, list[str]]:
    missing = [
        category
        for category in checklist.required_categories()
        if not active_heading_category_covered(category, replacement_text)
    ]
    return not missing, missing


def replacement_looks_empty_or_generic(replacement_lines: list[str]) -> bool:
    content_lines = [
        line.strip()
        for line in replacement_lines
        if line.strip() and not HEADING_RE.match(line.strip())
    ]
    content = re.sub(r"\bsha256:[a-f0-9]{12,64}\b", "", " ".join(content_lines), flags=re.I)
    content = re.sub(r"\bCompressed (?:local summary|archived detail)\b", "", content, flags=re.I)
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", content)
    generic_markers = {"summary", "details", "context", "active", "source", "archive", "chars", "dates"}
    meaningful_words = [word for word in words if word.lower() not in generic_markers]
    return len(meaningful_words) < 6


def active_heading_source_lines(removed_text: str, pattern: str | None = None, *, limit: int = 2) -> list[str]:
    matches: list[str] = []
    regex = re.compile(pattern, re.I) if pattern else None
    for raw_line in removed_text.splitlines():
        line = raw_line.strip()
        if not line or HEADING_RE.match(line):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        if regex and not regex.search(line):
            continue
        matches.append(truncate_sentence(line, 160))
        if len(matches) >= limit:
            break
    return matches


def deterministic_active_fallback_summary(item: "Item", removed_text: str) -> str:
    checklist = build_active_heading_preservation_checklist(item, removed_text)
    parts: list[str] = []
    if checklist.current_focus:
        snippets = active_heading_source_lines(removed_text, limit=1)
        parts.append("Current focus: " + (snippets[0] if snippets else "active work remains under maintenance."))
    if checklist.immediate_next_actions:
        snippets = active_heading_source_lines(removed_text, r"next actions?|todo|follow(?:-| )?up|finish|run|implement|repair|fix|continue|resume")
        if not snippets:
            snippets = active_heading_source_lines(removed_text, limit=1)
        parts.append("Next actions: " + "; ".join(snippets[:2]))
    if checklist.watchouts:
        snippets = active_heading_source_lines(removed_text, r"blocked|blocker|waiting|watchout|risk|failed?|failure|degraded|stale|timeout|regression")
        parts.append("Watchouts: " + ("; ".join(snippets[:2]) if snippets else "waiting or risk state remains."))
    if checklist.open_questions:
        snippets = active_heading_source_lines(removed_text, r"unresolved|open question|pending|unknown|unclear|needs decision|needs review|remaining issue")
        parts.append("Open questions: " + ("; ".join(snippets[:2]) if snippets else "remaining issue needs review."))
    if checklist.dated_carryover:
        dates = sorted(set(DATE_RE.findall(removed_text)))[:3]
        parts.append("Carryover: " + (", ".join(dates) if dates else "older unresolved work remains."))
    if not parts:
        snippets = active_heading_source_lines(removed_text, limit=2)
        parts.append("Current summary: " + ("; ".join(snippets) if snippets else "active heading content remains available in the archive."))
    return truncate_sentence(" ".join(parts), LOCAL_COMPRESSED_SUMMARY_MAX_CHARS)


def validate_active_live_heading_replacement(
    item: "Item",
    removed_text: str,
    replacement_lines: list[str],
    *,
    archive_hash: str,
) -> tuple[bool, str | None]:
    if not requires_active_live_heading_local_summary(item):
        return True, None
    if not replacement_lines:
        return False, "summary_unavailable"
    first_content = next((line.strip() for line in replacement_lines if line.strip()), "")
    match = HEADING_RE.match(first_content)
    if not match or match.group(2).strip() != item.section_heading:
        return False, "validation_failed:heading_changed"
    budget = active_live_heading_budget(item.section_heading)
    if not budget:
        return False, "validation_failed:missing_heading_budget"
    max_chars = int(budget["summary_max_chars"]) + ACTIVE_LIVE_HEADING_SUMMARY_TOLERANCE_CHARS
    replacement_text = "\n".join(replacement_lines)
    if len(replacement_text) > max_chars:
        return False, "validation_failed:summary_too_long"
    if len(replacement_text) >= len(removed_text):
        return False, "validation_failed:replacement_not_smaller"
    if replacement_looks_empty_or_generic(replacement_lines):
        return False, "validation_failed:generic_or_empty_summary"
    checklist = build_active_heading_preservation_checklist(item, removed_text)
    covered, missing_categories = score_active_heading_replacement(checklist, replacement_text)
    if not covered:
        return False, "validation_failed:missing_required_categories:" + ",".join(missing_categories[:5])
    if f"sha256:{archive_hash}" not in replacement_text:
        return False, "validation_failed:archive_hash_missing"
    return True, None


def compressed_replacement_lines(
    item: "Item",
    removed_text: str,
    *,
    local_summary: str | None = None,
    archive_hash: str | None = None,
) -> list[str]:
    if not supports_compressed_replacement(item, removed_text):
        return []
    if is_compressed_archive_text(removed_text):
        first_line = removed_text.splitlines()[0] if removed_text.splitlines() else ""
        m = BULLET_RE.match(first_line)
        indent = m.group(1) if m else ""
        return [f"{indent}- {truncate_sentence(compressed_archive_body(removed_text), compressed_note_max_chars(removed_text))}"]
    dates = ",".join(item.explicit_dates[:4]) if item.explicit_dates else "undated"
    refs = compact_refs(removed_text)
    refs_part = f"; refs: {refs}" if refs else ""
    archive_part = f"; archive: sha256:{archive_hash}" if archive_hash else ""
    summary = local_summary or compact_summary(removed_text, item)
    label = "Compressed local summary" if local_summary else "Compressed archived detail"
    note = f"{label} ({item.char_count} chars; dates: {dates}{refs_part}{archive_part}): {summary}"
    max_chars = LOCAL_COMPRESSED_NOTE_MAX_CHARS if local_summary else COMPRESSED_NOTE_MAX_CHARS
    if item.kind == "section":
        level = max(1, item.heading_level)
        return ["#" * level + f" {item.section_heading}", "", f"- {truncate_sentence(note, max_chars)}"]

    first_line = removed_text.splitlines()[0] if removed_text.splitlines() else ""
    m = BULLET_RE.match(first_line)
    indent = m.group(1) if m else ""
    return [f"{indent}- {truncate_sentence(note, max_chars)}"]


def replacement_shrinks_removed_text(removed_text: str, replacement_lines: list[str]) -> bool:
    if not replacement_lines:
        return False
    return len("\n".join(replacement_lines).encode("utf-8")) < len(removed_text.encode("utf-8"))


def bullet_anchor(text: str) -> str:
    first = normalize_text(text).splitlines()[0] if normalize_text(text) else "bullet"
    m = BULLET_RE.match(first)
    if m:
        first = m.group(3) or "bullet"
    return slugify(first)[:96] or "bullet"


def aggregate_state_matches(matches: list[tuple[str, dict]]) -> dict:
    if not matches:
        return {}

    def earliest(values: list[str | None]) -> str | None:
        parsed = [(parse_iso(v), v) for v in values if v]
        parsed = [(dt, raw) for dt, raw in parsed if dt]
        if not parsed:
            return None
        return min(parsed, key=lambda pair: pair[0])[1]

    def latest(values: list[str | None]) -> str | None:
        parsed = [(parse_iso(v), v) for v in values if v]
        parsed = [(dt, raw) for dt, raw in parsed if dt]
        if not parsed:
            return None
        return max(parsed, key=lambda pair: pair[0])[1]

    entries = [entry for _, entry in matches]
    out = dict(entries[0])
    out["firstSeenAt"] = earliest([entry.get("firstSeenAt") for entry in entries]) or out.get("firstSeenAt")
    out["lastSeenAt"] = latest([entry.get("lastSeenAt") for entry in entries]) or out.get("lastSeenAt")
    out["seenRuns"] = max(int(entry.get("seenRuns", 0)) for entry in entries)
    out["recallRuns"] = max(int(entry.get("recallRuns", 0)) for entry in entries)
    out["unrecalledRuns"] = max(int(entry.get("unrecalledRuns", 0)) for entry in entries)
    out["maxCharCount"] = max(int(entry.get("maxCharCount", 0)) for entry in entries)
    out["migratedFrom"] = [key for key, _ in matches[:10]]
    return out


def aggregate_state_entries(state: dict, *, exact_keys: list[str] | None = None, key_prefixes: list[str] | None = None) -> dict:
    item_state = state.get("items", {})
    matches: list[tuple[str, dict]] = []
    for key in exact_keys or []:
        entry = item_state.get(key)
        if entry:
            matches.append((key, entry))
    for prefix in key_prefixes or []:
        for key, entry in item_state.items():
            if key.startswith(prefix):
                matches.append((key, entry))
    return aggregate_state_matches(matches)


FINGERPRINT_AMBIGUITY_WARNED_KEY = "_fingerprintAmbiguousKeysWarned"


def increment_state_warning_counter(state: dict, key: str, amount: int = 1) -> None:
    counters = state.setdefault("warningCounters", {})
    if not isinstance(counters, dict):
        counters = {}
        state["warningCounters"] = counters
    counters[key] = int(counters.get(key, 0) or 0) + amount


def record_fingerprint_ambiguity(state: dict, fingerprint_keys: list[str] | set[str] | None) -> None:
    keys = sorted(key for key in (fingerprint_keys or {"unknown"}) if key) or ["unknown"]
    warned = state.setdefault(FINGERPRINT_AMBIGUITY_WARNED_KEY, [])
    if not isinstance(warned, list):
        warned = []
        state[FINGERPRINT_AMBIGUITY_WARNED_KEY] = warned
    for key in keys:
        if key in warned:
            continue
        warned.append(key)
        increment_state_warning_counter(state, "fingerprint_ambiguous")


def fingerprint_state_matches(state: dict, fingerprint_keys: list[str] | None = None) -> tuple[list[tuple[str, dict]], bool]:
    if not fingerprint_keys:
        return [], False
    item_state = state.get("items", {}) if isinstance(state.get("items"), dict) else {}
    fingerprint_index = state.get("fingerprints") if isinstance(state.get("fingerprints"), dict) else {}
    mapped_keys: list[str] = []
    ambiguous = False
    for fingerprint_key in fingerprint_keys:
        mapped = fingerprint_index.get(fingerprint_key)
        if isinstance(mapped, str):
            mapped_keys.append(mapped)
        elif isinstance(mapped, list):
            live_values = [value for value in mapped if isinstance(value, str)]
            if len(set(live_values)) == 1:
                mapped_keys.extend(live_values[:1])
            elif live_values:
                ambiguous = True
        elif mapped is not None:
            ambiguous = True
    if not mapped_keys:
        for key, entry in item_state.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("identityKey") in fingerprint_keys:
                mapped_keys.append(key)
    unique_keys = list(dict.fromkeys(mapped_keys))
    matches = [(key, item_state[key]) for key in unique_keys if isinstance(item_state.get(key), dict)]
    if len(matches) > 1:
        ambiguous = True
    return matches, ambiguous


def ensure_state_alias(
    state: dict,
    item_key: str,
    *,
    exact_keys: list[str] | None = None,
    fingerprint_keys: list[str] | None = None,
    ambiguous_fingerprint_keys: set[str] | None = None,
    key_prefixes: list[str] | None = None,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
) -> None:
    identity_mode = normalize_identity_mode(identity_mode)
    item_state = state.setdefault("items", {})
    if item_key in item_state:
        return
    exact_aggregate = aggregate_state_entries(state, exact_keys=exact_keys)
    if exact_aggregate:
        exact_aggregate["identityMatchedBy"] = "exact"
        item_state[item_key] = exact_aggregate
        return
    if identity_mode == "content-primary":
        fingerprint_live_ambiguous = bool(set(fingerprint_keys or []) & (ambiguous_fingerprint_keys or set()))
        fingerprint_matches, fingerprint_ambiguous = fingerprint_state_matches(state, fingerprint_keys)
        if fingerprint_live_ambiguous or fingerprint_ambiguous:
            record_fingerprint_ambiguity(state, fingerprint_keys)
            return
        if fingerprint_matches:
            fingerprint_aggregate = aggregate_state_matches(fingerprint_matches)
            fingerprint_aggregate["identityMatchedBy"] = "fingerprint"
            item_state[item_key] = fingerprint_aggregate
            return
    prefix_aggregate = aggregate_state_entries(state, key_prefixes=key_prefixes)
    if prefix_aggregate:
        prefix_aggregate["identityMatchedBy"] = "prefix"
        item_state[item_key] = prefix_aggregate


def item_keys(
    path_rel: Path,
    kind: str,
    heading: str,
    start_line: int,
    text: str,
    parent_section_key: str | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    h = text_hash(text)
    heading_slug = slugify(heading)
    fingerprint_aliases = [item_fingerprint_key(path_rel, kind, heading, text)]
    if kind == "section":
        legacy_key = f"section:{path_rel}:{heading_slug}:{h}"
        if is_compressed_archive_section_text(text):
            return f"section:{path_rel}:{heading_slug}:compressed:{h}", [], [], fingerprint_aliases
        if is_project_spine(path_rel) and is_project_spine_volatile_heading(heading):
            stable_key = f"section:{path_rel}:{heading_slug}"
            return stable_key, [legacy_key], [f"section:{path_rel}:{heading_slug}:"], fingerprint_aliases
        return legacy_key, [], [], fingerprint_aliases

    legacy_key = f"bullet:{path_rel}:{heading_slug}:{start_line}:{h}"
    if is_project_spine(path_rel) and is_project_spine_volatile_heading(heading):
        if is_compressed_archive_text(text):
            return f"bullet:{path_rel}:{heading_slug}:compressed:{h}", [], [], fingerprint_aliases
        stable_key = f"bullet:{path_rel}:{heading_slug}:{bullet_anchor(text)}"
        return stable_key, [legacy_key], [], fingerprint_aliases
    return legacy_key, [], [], fingerprint_aliases


def empty_recall_load_stats() -> dict[str, object]:
    return {
        "dream_entries_loaded": 0,
        "context_telemetry_entries_seen": 0,
        "context_telemetry_entries_loaded": 0,
        "context_telemetry_typed_entries_loaded": 0,
        "context_telemetry_expired_protective_entries": 0,
        "context_telemetry_covered_files": 0,
        "context_telemetry_typed_covered_files": 0,
        "context_telemetry_source_warnings": 0,
        "warnings": [],
    }


def empty_context_telemetry_match_stats() -> dict[str, object]:
    return {
        "telemetry_item_match_source_counts": {},
        "content_hash_recovered_hits": 0,
        "ambiguous_content_hash_matches": 0,
        "_stale_line_span_entry_keys": set(),
    }


def record_context_telemetry_match_stats(
    stats: dict[str, object] | None,
    *,
    match_source: str,
    content_hash_recovered_hits: int = 0,
    ambiguous_content_hash_matches: int = 0,
    stale_line_span_entry_keys: set[str] | None = None,
) -> None:
    if stats is None:
        return
    counts = stats.setdefault("telemetry_item_match_source_counts", {})
    if isinstance(counts, dict):
        counts[match_source] = int(counts.get(match_source, 0) or 0) + 1
    stats["content_hash_recovered_hits"] = int(stats.get("content_hash_recovered_hits", 0) or 0) + content_hash_recovered_hits
    stats["ambiguous_content_hash_matches"] = int(stats.get("ambiguous_content_hash_matches", 0) or 0) + ambiguous_content_hash_matches
    stale_keys = stats.setdefault("_stale_line_span_entry_keys", set())
    if isinstance(stale_keys, set) and stale_line_span_entry_keys:
        stale_keys.update(stale_line_span_entry_keys)


def recall_load_warning(stats: dict[str, object] | None, *, kind: str, reason: str, path: str | None = None) -> None:
    if stats is None:
        return
    warnings = stats.setdefault("warnings", [])
    if not isinstance(warnings, list):
        return
    warning: dict[str, str] = {"kind": kind, "reason": reason}
    if path:
        warning["path"] = path
    warnings.append(warning)


def positive_int(value: object, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalize_telemetry_hot_doc_path(raw_path: object) -> str | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    raw = raw_path.strip()
    try:
        path = Path(raw).expanduser()
    except RuntimeError:
        return None
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(WORKBENCH_ROOT.resolve())
        except (OSError, ValueError):
            return None
    else:
        path = Path(raw)
        if ".." in path.parts:
            return None
        if path.parts and path.parts[0] == ".":
            path = Path(*path.parts[1:])
    rel = Path(path.as_posix())
    if rel not in HOT_DOCS:
        return None
    return rel.as_posix()


def load_dream_recall_hits(*, stats: dict[str, object] | None = None) -> dict[str, list[RecallHit]]:
    store = load_json(RECALL_STORE_PATH, {"entries": {}})
    by_path: dict[str, list[RecallHit]] = {}
    for entry in store.get("entries", {}).values():
        path = entry.get("path")
        if not path:
            continue
        signal_count = int(entry.get("recallCount", 0)) + int(entry.get("dailyCount", 0)) + int(entry.get("groundedCount", 0))
        by_path.setdefault(path, []).append(
            RecallHit(
                start_line=max(1, int(entry.get("startLine", 1))),
                end_line=max(1, int(entry.get("endLine", entry.get("startLine", 1) or 1))),
                signal_count=max(1, signal_count),
                last_recalled_at=entry.get("lastRecalledAt"),
            )
        )
        if stats is not None:
            stats["dream_entries_loaded"] = int(stats.get("dream_entries_loaded", 0)) + 1
    return by_path


def telemetry_string(value: object, default: str = "") -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return default


def telemetry_content_hash(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def telemetry_hit_identity(hit: TelemetryEvidenceHit) -> str:
    if hit.entry_key:
        return hit.entry_key
    return "\u241f".join(
        [
            str(hit.start_line),
            str(hit.end_line),
            hit.signal_type,
            hit.evidence_tier,
            hit.span_kind,
            hit.content_hash or "",
            hit.last_seen_at or "",
        ]
    )


def build_telemetry_evidence_indexes(by_path: dict[str, list[TelemetryEvidenceHit]]) -> TelemetryEvidenceIndexes:
    by_path_and_span: dict[tuple[str, int, int], list[TelemetryEvidenceHit]] = {}
    by_path_and_content_hash: dict[tuple[str, str], list[TelemetryEvidenceHit]] = {}
    for rel_path, hits in by_path.items():
        for hit in hits:
            by_path_and_span.setdefault((rel_path, hit.start_line, hit.end_line), []).append(hit)
            content_hash = telemetry_content_hash(hit.content_hash)
            if content_hash is not None:
                by_path_and_content_hash.setdefault((rel_path, content_hash), []).append(hit)
    return TelemetryEvidenceIndexes(
        by_path=by_path,
        by_path_and_span=by_path_and_span,
        by_path_and_content_hash=by_path_and_content_hash,
    )


def load_context_telemetry_evidence_index(
    *,
    stats: dict[str, object] | None = None,
    now_dt: datetime | None = None,
    max_age_days: int = DEFAULT_CONTEXT_TELEMETRY_PROTECTIVE_MAX_AGE_DAYS,
) -> TelemetryEvidenceIndexes:
    return build_telemetry_evidence_indexes(
        load_context_telemetry_evidence_hits(stats=stats, now_dt=now_dt, max_age_days=max_age_days)
    )


def load_context_telemetry_evidence_hits(
    *,
    stats: dict[str, object] | None = None,
    now_dt: datetime | None = None,
    max_age_days: int = DEFAULT_CONTEXT_TELEMETRY_PROTECTIVE_MAX_AGE_DAYS,
) -> dict[str, list[TelemetryEvidenceHit]]:
    by_path: dict[str, list[TelemetryEvidenceHit]] = {}
    if not CONTEXT_TELEMETRY_PATH.exists():
        return by_path
    try:
        telemetry = json.loads(CONTEXT_TELEMETRY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        recall_load_warning(
            stats,
            kind="context_telemetry",
            path="context/state/context-usage-telemetry.json",
            reason=f"invalid-telemetry:{type(exc).__name__}",
        )
        return by_path
    if not isinstance(telemetry, dict):
        recall_load_warning(
            stats,
            kind="context_telemetry",
            path="context/state/context-usage-telemetry.json",
            reason="invalid-telemetry-root",
        )
        return by_path
    entries = telemetry.get("entries")
    if not isinstance(entries, dict):
        recall_load_warning(
            stats,
            kind="context_telemetry",
            path="context/state/context-usage-telemetry.json",
            reason="invalid-telemetry-entries",
        )
        return by_path

    source_warnings = telemetry.get("warnings")
    if stats is not None and isinstance(source_warnings, list):
        stats["context_telemetry_source_warnings"] = len(source_warnings)
    elif source_warnings is not None:
        recall_load_warning(
            stats,
            kind="context_telemetry",
            path="context/state/context-usage-telemetry.json",
            reason="invalid-telemetry-warnings",
        )

    covered_paths: set[str] = set()
    seen_count = 0
    loaded_count = 0
    reference_dt = now_dt or datetime.now(timezone.utc)
    for raw_entry_key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        entry_key = str(raw_entry_key)
        seen_count += 1
        rel_path = normalize_telemetry_hot_doc_path(entry.get("path"))
        if rel_path is None:
            continue
        start_line = positive_int(entry.get("startLine"))
        end_line = positive_int(entry.get("endLine"), start_line)
        if start_line is None or end_line is None:
            recall_load_warning(stats, kind="context_telemetry", path=rel_path, reason="invalid-telemetry-line-span")
            continue
        if end_line < start_line:
            start_line, end_line = end_line, start_line
        signal_type = telemetry_string(entry.get("signalType"), "unknown")
        span_kind = telemetry_string(entry.get("spanKind"), span_kind_from_lines(start_line, end_line))
        evidence_tier = telemetry_string(entry.get("evidenceTier"), legacy_evidence_tier(signal_type, span_kind))
        protects_from_prune = entry.get("protectsFromPrune") is True
        last_seen_at = entry.get("lastSeenAt") if isinstance(entry.get("lastSeenAt"), str) else None
        if protects_from_prune and last_seen_at and max_age_days > 0:
            last_seen_dt = parse_iso(last_seen_at)
            if last_seen_dt and days_between(reference_dt, last_seen_dt) > max_age_days:
                protects_from_prune = False
                if stats is not None:
                    stats["context_telemetry_expired_protective_entries"] = int(
                        stats.get("context_telemetry_expired_protective_entries", 0)
                    ) + 1
        signal_count = positive_int(entry.get("signalCount"), 1) or 1
        content_hash = telemetry_content_hash(entry.get("contentHash"))
        by_path.setdefault(rel_path, []).append(
            TelemetryEvidenceHit(
                start_line=start_line,
                end_line=end_line,
                signal_count=signal_count,
                last_seen_at=last_seen_at,
                signal_type=signal_type,
                evidence_tier=evidence_tier,
                span_kind=span_kind,
                protects_from_prune=protects_from_prune,
                follow_through=telemetry_string(entry.get("followThrough"), "unknown"),
                tier_reason=telemetry_string(entry.get("tierReason"), "unknown"),
                content_hash=content_hash,
                entry_key=entry_key,
            )
        )
        covered_paths.add(rel_path)
        loaded_count += 1

    if stats is not None:
        stats["context_telemetry_entries_seen"] = int(stats.get("context_telemetry_entries_seen", 0)) + seen_count
        stats["context_telemetry_typed_entries_loaded"] = int(stats.get("context_telemetry_typed_entries_loaded", 0)) + loaded_count
        stats["context_telemetry_typed_covered_files"] = len(covered_paths)
    return by_path


def protective_recall_hits_from_telemetry_evidence(
    typed_hits: dict[str, list[TelemetryEvidenceHit]],
    *,
    stats: dict[str, object] | None = None,
) -> dict[str, list[RecallHit]]:
    by_path: dict[str, list[RecallHit]] = {}
    covered_paths: set[str] = set()
    loaded_count = 0
    for rel_path, hits in typed_hits.items():
        for hit in hits:
            if not hit.protects_from_prune:
                continue
            by_path.setdefault(rel_path, []).append(
                RecallHit(
                    start_line=hit.start_line,
                    end_line=hit.end_line,
                    signal_count=hit.signal_count,
                    last_recalled_at=hit.last_seen_at,
                )
            )
            covered_paths.add(rel_path)
            loaded_count += 1
    if stats is not None:
        stats["context_telemetry_entries_loaded"] = int(stats.get("context_telemetry_entries_loaded", 0)) + loaded_count
        stats["context_telemetry_covered_files"] = len(covered_paths)
    return by_path


def load_context_telemetry_hits(
    *,
    stats: dict[str, object] | None = None,
    now_dt: datetime | None = None,
    max_age_days: int = DEFAULT_CONTEXT_TELEMETRY_PROTECTIVE_MAX_AGE_DAYS,
) -> dict[str, list[RecallHit]]:
    typed_hits = load_context_telemetry_evidence_hits(stats=stats, now_dt=now_dt, max_age_days=max_age_days)
    return protective_recall_hits_from_telemetry_evidence(typed_hits, stats=stats)


def legacy_evidence_tier(signal_type: str, span_kind: str) -> str:
    if signal_type in {"final_citation", "context_edit", "memory_get"}:
        return "strong"
    if signal_type == "read":
        return "weak" if span_kind == "broad" else "medium"
    if signal_type == "memory_search_hit":
        return "weak"
    return "unknown"


def span_kind_from_lines(start_line: int, end_line: int) -> str:
    span_lines = end_line - start_line + 1
    if span_lines > 80:
        return "broad"
    if span_lines > 40:
        return "medium"
    return "narrow"


def load_shadow_context_telemetry_hits() -> dict[str, list[ShadowTelemetryHit]]:
    """Load tier-aware telemetry for report-only shadow policy comparison.

    This intentionally does not feed the current pruning classifier. It only powers
    the Phase 3 dry-run report sections.
    """
    by_path: dict[str, list[ShadowTelemetryHit]] = {}
    for rel_path, hits in load_context_telemetry_evidence_hits(max_age_days=0).items():
        for hit in hits:
            by_path.setdefault(rel_path, []).append(
                ShadowTelemetryHit(
                    start_line=hit.start_line,
                    end_line=hit.end_line,
                    signal_count=hit.signal_count,
                    last_seen_at=hit.last_seen_at,
                    signal_type=hit.signal_type,
                    evidence_tier=hit.evidence_tier,
                    span_kind=hit.span_kind,
                )
            )
    return by_path


def item_evidence_for_span(
    path: str,
    start_line: int,
    end_line: int,
    dream_hits: dict[str, list[RecallHit]],
    telemetry_hits: dict[str, list[TelemetryEvidenceHit]],
    *,
    item_content_hash: str | None = None,
    telemetry_index: TelemetryEvidenceIndexes | None = None,
    ambiguous_content_hashes: set[tuple[str, str]] | None = None,
    match_stats: dict[str, object] | None = None,
) -> ItemEvidence:
    evidence = ItemEvidence()
    for hit in dream_hits.get(path, []):
        if not overlap(start_line, end_line, hit.start_line, hit.end_line):
            continue
        evidence.dream_strong_hits += 1
        evidence.strong_signal_count += hit.signal_count
        evidence.total_hits += 1

    path_hits = telemetry_hits.get(path, [])
    line_hits = [hit for hit in path_hits if overlap(start_line, end_line, hit.start_line, hit.end_line)]
    line_hit_ids = {telemetry_hit_identity(hit) for hit in line_hits}
    content_hash = telemetry_content_hash(item_content_hash)
    content_hash_candidates: list[TelemetryEvidenceHit] = []
    content_hash_only_hits: list[TelemetryEvidenceHit] = []
    ambiguous_hash_candidate_count = 0
    ambiguous_hash = False
    if content_hash is not None:
        if telemetry_index is not None:
            content_hash_candidates = telemetry_index.by_path_and_content_hash.get((path, content_hash), [])
        else:
            content_hash_candidates = [hit for hit in path_hits if telemetry_content_hash(hit.content_hash) == content_hash]
        stale_content_hash_candidates = [
            hit for hit in content_hash_candidates if not overlap(start_line, end_line, hit.start_line, hit.end_line)
        ]
        stale_candidate_ids = {telemetry_hit_identity(hit) for hit in stale_content_hash_candidates}
        ambiguous_hash = bool(stale_content_hash_candidates and (path, content_hash) in (ambiguous_content_hashes or set()))
        if ambiguous_hash:
            ambiguous_hash_candidate_count = len(stale_content_hash_candidates)
        else:
            content_hash_only_hits = [hit for hit in stale_content_hash_candidates if telemetry_hit_identity(hit) not in line_hit_ids]
    else:
        stale_candidate_ids = set()

    line_hit_has_matching_hash = bool(
        content_hash is not None and any(telemetry_content_hash(hit.content_hash) == content_hash for hit in line_hits)
    )
    if ambiguous_hash and not line_hits:
        match_source = "ambiguous_content_hash"
    elif line_hits and (line_hit_has_matching_hash or content_hash_only_hits):
        match_source = "both"
    elif line_hits:
        match_source = "line_span"
    elif content_hash_only_hits:
        match_source = "content_hash"
    else:
        match_source = "none"
    evidence.telemetry_match_source = match_source
    evidence.ambiguous_content_hash_hits = ambiguous_hash_candidate_count
    record_context_telemetry_match_stats(
        match_stats,
        match_source=match_source,
        content_hash_recovered_hits=len(content_hash_only_hits),
        ambiguous_content_hash_matches=ambiguous_hash_candidate_count,
        stale_line_span_entry_keys=stale_candidate_ids,
    )

    content_hash_only_ids = {telemetry_hit_identity(hit) for hit in content_hash_only_hits}
    matched_hits_by_id: dict[str, TelemetryEvidenceHit] = {}
    for hit in [*line_hits, *content_hash_only_hits]:
        matched_hits_by_id.setdefault(telemetry_hit_identity(hit), hit)

    for hit_id, hit in matched_hits_by_id.items():
        content_hash_recovered = hit_id in content_hash_only_ids
        if content_hash_recovered:
            evidence.content_hash_recovered_hits += 1
        evidence.total_hits += 1
        tier = hit.evidence_tier if hit.evidence_tier in {"strong", "medium", "weak", "invalid"} else "unknown"
        signal_type = hit.signal_type
        span_kind = hit.span_kind
        if signal_type == "context_edit":
            evidence.telemetry_unknown += 1
            continue
        if signal_type == "read" and span_kind == "broad":
            evidence.telemetry_broad_read_only += 1
            evidence.weak_signal_count += hit.signal_count
            continue
        if signal_type == "memory_get" and not hit.protects_from_prune:
            evidence.telemetry_unknown += 1
            continue
        if signal_type == "final_citation" and span_kind in {"narrow", "medium"}:
            evidence.telemetry_strong_targeted += 1
            evidence.strong_signal_count += hit.signal_count
            if content_hash_recovered:
                evidence.content_hash_recovered_strong_hits += 1
                evidence.content_hash_recovered_strong_signal_count += hit.signal_count
            continue
        if tier == "strong" and span_kind != "broad":
            evidence.telemetry_strong_targeted += 1
            evidence.strong_signal_count += hit.signal_count
            if content_hash_recovered:
                evidence.content_hash_recovered_strong_hits += 1
                evidence.content_hash_recovered_strong_signal_count += hit.signal_count
        elif tier == "medium":
            evidence.telemetry_medium_targeted += 1
            evidence.medium_signal_count += hit.signal_count
        elif tier == "weak":
            evidence.telemetry_weak_only += 1
            evidence.weak_signal_count += hit.signal_count
        elif tier == "invalid":
            evidence.telemetry_invalid += 1
        else:
            evidence.telemetry_unknown += 1
    return evidence


def shadow_evidence_from_item_evidence(evidence: ItemEvidence) -> ShadowEvidence:
    return ShadowEvidence(
        strong=evidence.dream_strong_hits + evidence.telemetry_strong_targeted,
        medium=evidence.telemetry_medium_targeted,
        weak=evidence.telemetry_weak_only + evidence.telemetry_broad_read_only,
        invalid=evidence.telemetry_invalid,
        unknown=evidence.telemetry_unknown,
        broad_read=evidence.telemetry_broad_read_only,
        strong_medium_signal_count=evidence.strong_signal_count + evidence.medium_signal_count,
        total=evidence.total_hits,
    )


def shadow_evidence_for_item(
    item: Item,
    telemetry_hits: dict[str, list[TelemetryEvidenceHit]],
    dream_hits: dict[str, list[RecallHit]],
) -> ShadowEvidence:
    item_evidence = item_evidence_for_span(item.path, item.start_line, item.end_line, dream_hits, telemetry_hits)
    return shadow_evidence_from_item_evidence(item_evidence)


def is_large_for_shadow_review(item: Item) -> bool:
    return item.char_count >= (MIN_SECTION_CHARS if item.kind == "section" else MIN_BULLET_CHARS)


# Diagnostic-only shadow policy: current tier-aware rules are known to
# over-demote current quant candidates, so this function must remain report-only.
# It must not feed Item.classification, update_state(...), candidate_ranges(...),
# or any apply path until a later slice explicitly promotes a revised policy.
def shadow_classification_for_item(
    item: Item,
    evidence: ShadowEvidence,
    state: dict,
    config: AuditConfig,
    run_bucket: str,
) -> tuple[str, str, int, int, int]:
    """Return the Phase 3 proposed class without changing current decisions.

    The shadow policy is deliberately conservative: strong evidence keeps an item;
    medium evidence can route stale large items to review but blocks prune; weak-only
    evidence does not reset recall and can only move large stale items to review.
    """
    proposed_recalled_now = evidence.strong > 0
    seen_runs, recall_runs, unrecalled_runs = state_metrics(item.key, state, proposed_recalled_now, run_bucket)
    large = is_large_for_shadow_review(item)
    stale_for_review = (
        large
        and seen_runs >= config.min_seen_runs_review
        and unrecalled_runs >= config.min_unrecalled_runs_review
        and item.age_days >= config.dormant_days
    )

    if item.pinned:
        return "keep", "shadow:pinned-or-stable-anchor", seen_runs, recall_runs, unrecalled_runs
    if evidence.strong > 0:
        return "keep", "shadow:strong-evidence-protects", seen_runs, recall_runs, unrecalled_runs
    if evidence.strong_medium_signal_count >= HIGH_USAGE_RECALL_SIGNALS:
        return "keep", "shadow:strong-medium-high-usage-protects", seen_runs, recall_runs, unrecalled_runs
    if evidence.medium > 0:
        if stale_for_review:
            return "review", "shadow:medium-evidence-review", seen_runs, recall_runs, unrecalled_runs
        return "keep", "shadow:medium-evidence-gathering-history", seen_runs, recall_runs, unrecalled_runs
    if evidence.weak > 0:
        if stale_for_review:
            return "review", "shadow:weak-only-review-before-prune", seen_runs, recall_runs, unrecalled_runs
        return "keep", "shadow:weak-only-not-protective-yet", seen_runs, recall_runs, unrecalled_runs

    if item.reason.startswith("recalled:"):
        if stale_for_review:
            return "review", "shadow:no-tiered-evidence-review", seen_runs, recall_runs, unrecalled_runs
        return "keep", "shadow:no-tiered-evidence-gathering-history", seen_runs, recall_runs, unrecalled_runs
    return item.classification, f"shadow:current-no-tiered-recall:{item.reason}", seen_runs, recall_runs, unrecalled_runs


def build_shadow_policy_comparison(
    items: list[Item],
    state: dict,
    config: AuditConfig,
    run_bucket: str,
) -> dict[str, object]:
    telemetry_hits = load_context_telemetry_evidence_hits(max_age_days=0)
    dream_hits = load_dream_recall_hits()
    current_counts = Counter(item.classification for item in items)
    proposed_counts: Counter[str] = Counter()
    tier_overlap_counts: Counter[str] = Counter()
    records: list[dict[str, object]] = []
    weak_only_protected: list[dict[str, object]] = []
    broad_read_only_protected: list[dict[str, object]] = []
    pinned_excluded: list[dict[str, object]] = []
    for item in items:
        evidence = shadow_evidence_for_item(item, telemetry_hits, dream_hits)
        proposed_class, proposed_reason, proposed_seen, proposed_recall, proposed_unrecalled = shadow_classification_for_item(
            item, evidence, state, config, run_bucket
        )
        proposed_counts[proposed_class] += 1
        if evidence.total:
            if evidence.strong:
                tier_overlap_counts["strong"] += 1
            elif evidence.medium:
                tier_overlap_counts["medium_only"] += 1
            elif evidence.weak:
                tier_overlap_counts["weak_only"] += 1
            else:
                tier_overlap_counts["unknown_or_invalid_only"] += 1
        record = {
            "item": item,
            "current_classification": item.classification,
            "current_reason": item.reason,
            "proposed_classification": proposed_class,
            "proposed_reason": proposed_reason,
            "proposed_seen_runs": proposed_seen,
            "proposed_recall_runs": proposed_recall,
            "proposed_unrecalled_runs": proposed_unrecalled,
            "evidence": evidence,
        }
        records.append(record)
        current_recall_protected = item.classification == "keep" and (
            item.reason.startswith("recalled:") or item.reason == "high-recall-protected"
        )
        if current_recall_protected and evidence.weak > 0 and evidence.strong == 0 and evidence.medium == 0:
            weak_only_protected.append(record)
            if evidence.broad_read == evidence.weak and evidence.weak > 0:
                broad_read_only_protected.append(record)
        if item.pinned and item.char_count >= MIN_SECTION_CHARS:
            pinned_excluded.append(record)
    return {
        "mode": "report_only",
        "current_counts": dict(sorted(current_counts.items())),
        "proposed_counts": dict(sorted(proposed_counts.items())),
        "tier_overlap_counts": dict(sorted(tier_overlap_counts.items())),
        "weak_only_protected": weak_only_protected,
        "broad_read_only_protected": broad_read_only_protected,
        "proposed_review": [record for record in records if record["proposed_classification"] == "review"],
        "proposed_prune": [record for record in records if record["proposed_classification"] == "prune_candidate"],
        "pinned_excluded": pinned_excluded,
    }


def merge_recall_hit_maps(*hit_maps: dict[str, list[RecallHit]]) -> dict[str, list[RecallHit]]:
    merged: dict[str, list[RecallHit]] = {}
    for hit_map in hit_maps:
        for path, hits in hit_map.items():
            merged.setdefault(path, []).extend(hits)
    return merged


def load_recall_and_evidence_hits(
    now_dt: datetime | None = None,
) -> tuple[dict[str, list[RecallHit]], dict[str, list[TelemetryEvidenceHit]], dict[str, list[RecallHit]]]:
    global LAST_CONTEXT_TELEMETRY_HITS, LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX, LAST_RECALL_LOAD_STATS
    stats = empty_recall_load_stats()
    dream_hits = load_dream_recall_hits(stats=stats)
    context_telemetry_index = load_context_telemetry_evidence_index(stats=stats, now_dt=now_dt)
    context_telemetry_evidence_hits = context_telemetry_index.by_path
    context_telemetry_hits = protective_recall_hits_from_telemetry_evidence(context_telemetry_evidence_hits, stats=stats)
    LAST_CONTEXT_TELEMETRY_HITS = context_telemetry_hits
    LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX = context_telemetry_index
    LAST_RECALL_LOAD_STATS = stats
    return dream_hits, context_telemetry_evidence_hits, merge_recall_hit_maps(dream_hits, context_telemetry_hits)


def load_all_recall_hits(now_dt: datetime | None = None) -> dict[str, list[RecallHit]]:
    _dream_hits, _context_telemetry_evidence_hits, recall_hits = load_recall_and_evidence_hits(now_dt)
    return recall_hits


def load_recall_hits() -> dict[str, list[RecallHit]]:
    return load_all_recall_hits()


def overlap(a1: int, a2: int, b1: int, b2: int) -> bool:
    return not (a2 < b1 or b2 < a1)


def collect_recall_metrics(path: str, start: int, end: int, hits_by_path: dict[str, list[RecallHit]]) -> tuple[int, int, str | None]:
    hits = 0
    signal_count = 0
    last_seen: datetime | None = None
    for hit in hits_by_path.get(path, []):
        if overlap(start, end, hit.start_line, hit.end_line):
            hits += 1
            signal_count += hit.signal_count
            ts = parse_iso(hit.last_recalled_at)
            if ts and (last_seen is None or ts > last_seen):
                last_seen = ts
    last_iso = last_seen.replace(microsecond=0).isoformat().replace("+00:00", "Z") if last_seen else None
    return hits, signal_count, last_iso


def count_items_with_hits(items: list[Item], hits_by_path: dict[str, list[RecallHit]]) -> int:
    count = 0
    for item in items:
        hits, signal_count, _last_seen = collect_recall_metrics(item.path, item.start_line, item.end_line, hits_by_path)
        if hits > 0 or signal_count > 0:
            count += 1
    return count


def hot_doc_paths() -> list[Path]:
    return [WORKBENCH_ROOT / rel for rel in HOT_DOCS if (WORKBENCH_ROOT / rel).exists()]


def current_hot_item_content_hash_counts() -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for path in hot_doc_paths():
        rel = path.relative_to(WORKBENCH_ROOT)
        rel_path = str(rel)
        lines = path.read_text(encoding="utf-8").splitlines()
        for heading, level, start, end in split_sections(lines):
            block = "\n".join(lines[start - 1 : end])
            counts[(rel_path, text_hash(block))] += 1
            for _b_heading, _b_level, _b_start, _b_end, b_text in extract_bullets(lines, heading, level, start, end):
                counts[(rel_path, text_hash(b_text))] += 1
    return counts


def current_state_rebase_candidates() -> list[StateRebaseCandidate]:
    candidates: list[StateRebaseCandidate] = []
    for path in hot_doc_paths():
        rel = path.relative_to(WORKBENCH_ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        for heading, level, start, end in split_sections(lines):
            block = "\n".join(lines[start - 1 : end])
            sec_key, sec_exact_aliases, sec_prefix_aliases, sec_fingerprint_aliases = item_keys(
                rel,
                "section",
                heading,
                start,
                block,
            )
            sec_fingerprint = item_fingerprint(rel, "section", heading, block)
            candidates.append(
                StateRebaseCandidate(
                    key=sec_key,
                    kind="section",
                    path=str(rel),
                    section_heading=heading,
                    heading_level=level,
                    start_line=start,
                    end_line=end,
                    char_count=len(block),
                    text_hash=text_hash(block),
                    fingerprint=sec_fingerprint,
                    identity_key=sec_fingerprint_aliases[0],
                    identity_mode="content-fingerprint",
                    exact_aliases=sec_exact_aliases,
                    prefix_aliases=sec_prefix_aliases,
                    fingerprint_aliases=sec_fingerprint_aliases,
                )
            )
            for b_heading, b_level, b_start, b_end, b_text in extract_bullets(lines, heading, level, start, end):
                b_key, b_exact_aliases, b_prefix_aliases, b_fingerprint_aliases = item_keys(
                    rel,
                    "bullet",
                    b_heading,
                    b_start,
                    b_text,
                    sec_key,
                )
                b_fingerprint = item_fingerprint(rel, "bullet", b_heading, b_text)
                candidates.append(
                    StateRebaseCandidate(
                        key=b_key,
                        kind="bullet",
                        path=str(rel),
                        section_heading=b_heading,
                        heading_level=b_level,
                        start_line=b_start,
                        end_line=b_end,
                        char_count=len(b_text),
                        text_hash=text_hash(b_text),
                        fingerprint=b_fingerprint,
                        identity_key=b_fingerprint_aliases[0],
                        identity_mode="content-fingerprint",
                        exact_aliases=b_exact_aliases,
                        prefix_aliases=b_prefix_aliases,
                        fingerprint_aliases=b_fingerprint_aliases,
                    )
                )
    return candidates


def is_compressed_archive_item(item: Item) -> bool:
    return item.kind == "bullet" and ":compressed:" in item.key


def latest_explicit_date(item: Item) -> str:
    return max(item.explicit_dates) if item.explicit_dates else "0000-00-00"


def enforce_project_spine_compressed_note_caps(items: list[Item]) -> list[Item]:
    grouped: dict[tuple[str, str], list[Item]] = {}
    for item in items:
        if not is_project_spine(Path(item.path)):
            continue
        if not is_project_spine_volatile_heading(item.section_heading):
            continue
        if not is_compressed_archive_item(item):
            continue
        grouped.setdefault((item.path, item.section_heading), []).append(item)

    for notes in grouped.values():
        if len(notes) <= PROJECT_SPINE_COMPRESSED_NOTE_LIMIT:
            continue
        keep = set(
            id(item)
            for item in sorted(notes, key=lambda i: (latest_explicit_date(i), i.start_line), reverse=True)[:PROJECT_SPINE_COMPRESSED_NOTE_LIMIT]
        )
        for item in notes:
            if id(item) in keep or item.pinned or item.recall_hits > 0 or item.recall_signal_count > 0:
                continue
            if item.age_days < COMPRESSED_ITEM_PRUNE_DAYS or item.seen_runs < DEFAULT_MIN_SEEN_RUNS_REVIEW:
                item.classification = "review"
                item.reason = "compressed-archive-note-cap-review"
                continue
            item.classification = "prune_candidate"
            item.reason = "compressed-archive-note-cap"
    return items


def split_sections(lines: list[str]) -> list[tuple[str, int, int, int]]:
    sections: list[tuple[str, int, int, int]] = []
    current_title = "(preamble)"
    current_level = 0
    current_start = 1
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if not m:
            continue
        if idx > current_start:
            sections.append((current_title, current_level, current_start, idx - 1))
        current_title = m.group(2)
        current_level = len(m.group(1))
        current_start = idx
    sections.append((current_title, current_level, current_start, len(lines)))
    return sections


def extract_bullets(lines: list[str], section_title: str, section_level: int, sec_start: int, sec_end: int) -> list[tuple[str, int, int, int, str]]:
    out = []
    i = sec_start
    while i <= sec_end:
        line = lines[i - 1]
        if KEEP_COMMENT_RE.search(line):
            i += 1
            continue
        m = BULLET_RE.match(line)
        if not m:
            i += 1
            continue
        start = i
        indent = len(m.group(1))
        j = i + 1
        while j <= sec_end:
            nxt = lines[j - 1]
            if HEADING_RE.match(nxt):
                break
            n_bullet = BULLET_RE.match(nxt)
            if n_bullet and len(n_bullet.group(1)) <= indent:
                break
            j += 1
        text = "\n".join(lines[start - 1 : j - 1])
        out.append((section_title, section_level, start, j - 1, text))
        i = j
    return out


def item_age_days(item_key: str, state: dict, now_dt: datetime, now_str: str) -> float:
    entry = state.get("items", {}).get(item_key, {})
    first_seen_at = parse_iso(entry.get("firstSeenAt", now_str))
    if not first_seen_at:
        return 0.0
    return days_between(now_dt, first_seen_at)


def is_item_pinned(path_rel: Path, kind: str, heading: str, text: str) -> bool:
    if path_rel in NON_PRUNABLE:
        return True
    if KEEP_COMMENT_RE.search(text):
        return True
    if is_project_spine(path_rel):
        return is_project_spine_pinned_heading(heading)
    if kind == "section" and normalized_heading(heading) in {
        "role",
        "goal",
        "intended shape",
        "retention model",
        "maintenance rule",
        "current config posture",
        "current live architecture",
        "pipeline invariants that matter",
        "current active implementation concerns",
        "update rule",
    }:
        return True
    return False


def state_metrics(item_key: str, state: dict, recalled_now: bool, run_bucket: str) -> tuple[int, int, int]:
    entry = state.get("items", {}).get(item_key, {})
    already_counted = entry.get("lastCountedBucket") == run_bucket
    seen_runs = int(entry.get("seenRuns", 0))
    recall_runs = int(entry.get("recallRuns", 0))
    unrecalled_runs = int(entry.get("unrecalledRuns", 0))
    if not already_counted:
        seen_runs += 1
        if recalled_now:
            recall_runs += 1
            unrecalled_runs = 0
        else:
            unrecalled_runs += 1
    return seen_runs, recall_runs, unrecalled_runs


def is_high_usage_item(recall_hits: int, recall_signal_count: int, recall_runs: int) -> bool:
    """Return whether recall telemetry says this item is too valuable to shrink.

    A single incidental recall should not pin something forever; repeated recall
    runs or a strong current signal means the item is genuinely useful and should
    stay uncompressed/unpruned unless VM pins/unpins or edits policy explicitly.
    """
    return recall_signal_count >= HIGH_USAGE_RECALL_SIGNALS or recall_runs >= HIGH_USAGE_RECALL_RUNS


def classify_item(
    *,
    path_rel: Path,
    kind: str,
    heading: str,
    text: str,
    item_key: str,
    doc_char_count: int,
    recall_hits: int,
    recall_signal_count: int,
    item_age_days: float,
    explicit_dates: list[str],
    evidence: ItemEvidence,
    now_dt: datetime,
    state: dict,
    config: AuditConfig,
    run_bucket: str,
) -> tuple[str, str, bool, int, int, int]:
    pinned = is_item_pinned(path_rel, kind, heading, text)
    recalled_now = recall_hits > 0 or recall_signal_count > 0
    seen_runs, recall_runs, unrecalled_runs = state_metrics(item_key, state, recalled_now, run_bucket)

    large_item = len(text) >= (MIN_SECTION_CHARS if kind == "section" else MIN_BULLET_CHARS)
    active_hot_doc = doc_profile(path_rel) == "active_hot_doc"
    project_spine = is_project_spine(path_rel)
    project_spine_hard_pressure = doc_char_count >= PROJECT_SPINE_HARD_PRESSURE_CHARS
    project_spine_soft_pressure = doc_char_count >= PROJECT_SPINE_SOFT_TARGET_CHARS
    project_spine_volatile = project_spine and is_project_spine_volatile_heading(heading)
    compressed_item = is_compressed_item_text(kind, text)
    project_spine_dated_section_pressure = (
        project_spine_volatile
        and kind == "section"
        and is_project_spine_section_prunable(heading)
        and len(text) >= PROJECT_SPINE_DATED_SECTION_CHARS
    )
    project_spine_pressure = project_spine_hard_pressure or project_spine_soft_pressure or project_spine_dated_section_pressure
    project_spine_pressure_section_ready = (
        project_spine_volatile
        and project_spine_pressure
        and kind == "section"
        and seen_runs >= config.min_seen_runs_prune
        and unrecalled_runs >= config.min_unrecalled_runs_prune
        and item_age_days >= config.dormant_days
        and large_item
    )
    project_spine_pressure_bullet_ready = (
        project_spine_volatile
        and (project_spine_hard_pressure or project_spine_soft_pressure)
        and kind == "bullet"
        and seen_runs >= config.min_seen_runs_review
        and unrecalled_runs >= config.min_unrecalled_runs_review
        and item_age_days >= config.dormant_days
        and len(text) >= PROJECT_SPINE_VOLATILE_BULLET_CHARS
    )

    strong_unresolved_evidence = evidence.has_strong_targeted and bool(UNRESOLVED_MARKER_RE.search(text))
    stale_strong_without_unresolved = evidence.has_strong_targeted and not recalled_now and not strong_unresolved_evidence
    medium_without_strong = evidence.has_medium_without_strong
    active_live_heading = active_hot_doc and kind == "section" and is_active_live_heading(heading)
    active_dated_section = active_hot_doc and kind == "section" and is_active_dated_heading(heading)
    active_current_protective_evidence = recalled_now or strong_unresolved_evidence

    if pinned:
        return "keep", "pinned", True, seen_runs, recall_runs, unrecalled_runs
    if compressed_item and kind == "bullet" and len(compressed_archive_body(text)) > compressed_note_max_chars(text):
        return "prune_candidate", "compressed-archive-note-trim", False, seen_runs, recall_runs, unrecalled_runs
    if active_live_heading:
        live_ready, live_reason = active_live_heading_budget_ready(
            path_rel=path_rel,
            heading=heading,
            text=text,
            doc_char_count=doc_char_count,
            item_age_days=item_age_days,
            evidence=evidence,
        )
        if live_ready:
            return "review", live_reason, False, seen_runs, recall_runs, unrecalled_runs
        return "keep", live_reason, False, seen_runs, recall_runs, unrecalled_runs
    if active_dated_section:
        active_ready, active_reason = active_section_pressure_ready(
            path_rel=path_rel,
            kind=kind,
            heading=heading,
            text=text,
            doc_char_count=doc_char_count,
            item_age_days=item_age_days,
            seen_runs=seen_runs,
            unrecalled_runs=unrecalled_runs,
            evidence=evidence,
            config=config,
            strong_current_evidence=active_current_protective_evidence,
        )
        if active_ready:
            active_classification = "prune_candidate" if active_reason.endswith("-compress") else "review"
            return active_classification, active_reason, False, seen_runs, recall_runs, unrecalled_runs
        return "keep", active_reason, False, seen_runs, recall_runs, unrecalled_runs
    # Project-spine pressure keeps current strong targeted evidence via the
    # existing protective recall path before any pressure-compression gate.
    if recalled_now:
        return "keep", f"recalled:{recall_hits}/{recall_signal_count}", False, seen_runs, recall_runs, unrecalled_runs
    if strong_unresolved_evidence:
        return "keep", "strong-targeted-unresolved", False, seen_runs, recall_runs, unrecalled_runs
    if compressed_item:
        if item_age_days < config.recent_grace_days:
            return "keep", "compressed-archive-note-recent", False, seen_runs, recall_runs, unrecalled_runs
        if seen_runs < config.min_seen_runs_review:
            return "keep", "compressed-archive-note-gathering-history", False, seen_runs, recall_runs, unrecalled_runs
        if (
            seen_runs >= config.min_seen_runs_prune
            and unrecalled_runs >= config.min_unrecalled_runs_prune
            and item_age_days >= COMPRESSED_ITEM_PRUNE_DAYS
        ):
            return "prune_candidate", "compressed-archive-note-aged-unused", False, seen_runs, recall_runs, unrecalled_runs
        if (
            seen_runs >= config.min_seen_runs_review
            and unrecalled_runs >= config.min_unrecalled_runs_review
            and item_age_days >= config.dormant_days
        ):
            return "review", "compressed-archive-note-unused-review", False, seen_runs, recall_runs, unrecalled_runs
        return "keep", "compressed-archive-note-retained", False, seen_runs, recall_runs, unrecalled_runs
    if (
        is_high_usage_item(recall_hits, recall_signal_count, recall_runs)
        and not stale_strong_without_unresolved
        and not (project_spine_volatile and project_spine_pressure and (project_spine_pressure_section_ready or project_spine_pressure_bullet_ready))
    ):
        return "keep", "high-recall-protected", False, seen_runs, recall_runs, unrecalled_runs
    if (
        project_spine_volatile
        and project_spine_pressure
        and not project_spine_pressure_section_ready
        and not project_spine_pressure_bullet_ready
        and (is_project_spine_oversized_for_review(kind, text) or project_spine_dated_section_pressure)
    ):
        if project_spine_dated_section_pressure and not (project_spine_hard_pressure or project_spine_soft_pressure):
            return "review", "project-spine-dated-section-pressure-review", False, seen_runs, recall_runs, unrecalled_runs
        return "review", "project-spine-pressure-oversized-review", False, seen_runs, recall_runs, unrecalled_runs
    if item_age_days < config.recent_grace_days:
        return "keep", "recently-edited", False, seen_runs, recall_runs, unrecalled_runs
    if seen_runs < config.min_seen_runs_review:
        return "keep", "gathering-history", False, seen_runs, recall_runs, unrecalled_runs

    old_dates = []
    for raw in explicit_dates:
        dt = parse_iso(raw + "T00:00:00+00:00")
        if not dt:
            continue
        if days_between(now_dt, dt) >= config.stale_days:
            old_dates.append(raw)

    historical_heading = bool(HISTORICAL_HEADING_RE.search(heading))
    historical_text = bool(HISTORICAL_HEADING_RE.search(text[:400]))

    if (
        active_hot_doc
        and seen_runs >= config.min_seen_runs_prune
        and unrecalled_runs >= config.min_unrecalled_runs_prune
        and item_age_days >= config.dormant_days
        and large_item
    ):
        if medium_without_strong:
            return "review", "medium-evidence-active-hot-doc-review", False, seen_runs, recall_runs, unrecalled_runs
        return "prune_candidate", "persistently-unused-active-hot-doc", False, seen_runs, recall_runs, unrecalled_runs

    # Medium/weak project-spine evidence stays explicit on Item.evidence_class
    # and apply range records; it does not demote mature pressure candidates.
    if (
        project_spine_volatile
        and project_spine_pressure
        and (project_spine_pressure_section_ready or project_spine_pressure_bullet_ready)
    ):
        if kind == "section":
            if is_project_spine_section_prunable(heading):
                return "prune_candidate", "project-spine-pressure-volatile-section-compress", False, seen_runs, recall_runs, unrecalled_runs
            return "review", "project-spine-pressure-volatile-section-review-only", False, seen_runs, recall_runs, unrecalled_runs
        return "prune_candidate", "project-spine-pressure-volatile-bullet-compress", False, seen_runs, recall_runs, unrecalled_runs

    if (
        seen_runs >= config.min_seen_runs_prune
        and unrecalled_runs >= config.min_unrecalled_runs_prune
        and item_age_days >= config.stale_days
        and large_item
        and (old_dates or historical_heading or (kind == "section" and historical_text))
    ):
        if medium_without_strong:
            return "review", "medium-evidence-blocks-hard-prune", False, seen_runs, recall_runs, unrecalled_runs
        return "prune_candidate", "persistently-unused-historical", False, seen_runs, recall_runs, unrecalled_runs

    if (
        seen_runs >= config.min_seen_runs_review
        and unrecalled_runs >= config.min_unrecalled_runs_review
        and item_age_days >= config.dormant_days
        and large_item
    ):
        return "review", "persistently-unused", False, seen_runs, recall_runs, unrecalled_runs

    return "keep", "small-or-benign", False, seen_runs, recall_runs, unrecalled_runs


def live_fingerprint_key_counts() -> Counter[str]:
    counts: Counter[str] = Counter()
    for candidate in current_state_rebase_candidates():
        counts.update(candidate.fingerprint_aliases)
    return counts


def build_items(
    now_dt: datetime,
    state: dict,
    config: AuditConfig,
    run_bucket: str,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
) -> list[Item]:
    identity_mode = normalize_identity_mode(identity_mode)
    global LAST_CONTEXT_TELEMETRY_MATCH_STATS
    dream_hits_by_path, telemetry_evidence_by_path, hits_by_path = load_recall_and_evidence_hits(now_dt)
    telemetry_evidence_index = (
        LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX
        if isinstance(LAST_CONTEXT_TELEMETRY_EVIDENCE_INDEX, TelemetryEvidenceIndexes)
        else build_telemetry_evidence_indexes(telemetry_evidence_by_path)
    )
    live_fingerprint_counts = live_fingerprint_key_counts() if identity_mode == "content-primary" else Counter()
    ambiguous_fingerprint_keys = {key for key, count in live_fingerprint_counts.items() if count > 1}
    live_content_hash_counts = current_hot_item_content_hash_counts()
    ambiguous_content_hashes = {key for key, count in live_content_hash_counts.items() if count > 1}
    telemetry_match_stats = empty_context_telemetry_match_stats()
    LAST_CONTEXT_TELEMETRY_MATCH_STATS = telemetry_match_stats
    now_str = now_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    items: list[Item] = []
    for path in hot_doc_paths():
        rel = path.relative_to(WORKBENCH_ROOT)
        text = path.read_text()
        doc_char_count = len(text)
        lines = text.splitlines()
        for heading, level, start, end in split_sections(lines):
            block = "\n".join(lines[start - 1 : end])
            dates = sorted(set(DATE_RE.findall(block)))
            sec_key, sec_exact_aliases, sec_prefix_aliases, sec_fingerprint_aliases = item_keys(
                rel,
                "section",
                heading,
                start,
                block,
            )
            ensure_state_alias(
                state,
                sec_key,
                exact_keys=sec_exact_aliases,
                fingerprint_keys=sec_fingerprint_aliases,
                ambiguous_fingerprint_keys=ambiguous_fingerprint_keys,
                key_prefixes=sec_prefix_aliases,
                identity_mode=identity_mode,
            )
            sec_text_hash = text_hash(block)
            sec_fingerprint = item_fingerprint(rel, "section", heading, block)
            sec_identity_key = sec_fingerprint_aliases[0]
            sec_age_days = item_age_days(sec_key, state, now_dt, now_str)
            sec_recall_hits, sec_signal_count, sec_last = collect_recall_metrics(str(rel), start, end, hits_by_path)
            sec_evidence = item_evidence_for_span(
                str(rel),
                start,
                end,
                dream_hits_by_path,
                telemetry_evidence_by_path,
                item_content_hash=sec_text_hash,
                telemetry_index=telemetry_evidence_index,
                ambiguous_content_hashes=ambiguous_content_hashes,
                match_stats=telemetry_match_stats,
            )
            sec_class, sec_reason, sec_pinned, sec_seen_runs, sec_recall_runs, sec_unrecalled_runs = classify_item(
                path_rel=rel,
                kind="section",
                heading=heading,
                text=block,
                item_key=sec_key,
                doc_char_count=doc_char_count,
                recall_hits=sec_recall_hits,
                recall_signal_count=sec_signal_count,
                item_age_days=sec_age_days,
                explicit_dates=dates,
                evidence=sec_evidence,
                now_dt=now_dt,
                state=state,
                config=config,
                run_bucket=run_bucket,
            )
            items.append(
                Item(
                    key=sec_key,
                    kind="section",
                    path=str(rel),
                    section_heading=heading,
                    heading_level=level,
                    start_line=start,
                    end_line=end,
                    char_count=len(block),
                    text_hash=sec_text_hash,
                    explicit_dates=dates,
                    recall_hits=sec_recall_hits,
                    recall_signal_count=sec_signal_count,
                    last_recalled_at=sec_last,
                    age_days=round(sec_age_days, 1),
                    pinned=sec_pinned,
                    seen_runs=sec_seen_runs,
                    recall_runs=sec_recall_runs,
                    unrecalled_runs=sec_unrecalled_runs,
                    classification=sec_class,
                    reason=sec_reason,
                    fingerprint=sec_fingerprint,
                    identity_key=sec_identity_key,
                    identity_mode="content-fingerprint",
                    evidence_class=sec_evidence.evidence_class,
                    strong_evidence_hits=sec_evidence.dream_strong_hits + sec_evidence.telemetry_strong_targeted,
                    medium_evidence_hits=sec_evidence.telemetry_medium_targeted,
                    weak_broad_evidence_hits=sec_evidence.telemetry_weak_only + sec_evidence.telemetry_broad_read_only,
                    telemetry_match_source=sec_evidence.telemetry_match_source,
                    content_hash_recovered_hits=sec_evidence.content_hash_recovered_hits,
                )
            )
            for b_heading, b_level, b_start, b_end, b_text in extract_bullets(lines, heading, level, start, end):
                b_dates = sorted(set(DATE_RE.findall(b_text)))
                b_key, b_exact_aliases, b_prefix_aliases, b_fingerprint_aliases = item_keys(
                    rel,
                    "bullet",
                    b_heading,
                    b_start,
                    b_text,
                    sec_key,
                )
                ensure_state_alias(
                    state,
                    b_key,
                    exact_keys=b_exact_aliases,
                    fingerprint_keys=b_fingerprint_aliases,
                    ambiguous_fingerprint_keys=ambiguous_fingerprint_keys,
                    key_prefixes=b_prefix_aliases,
                    identity_mode=identity_mode,
                )
                b_text_hash = text_hash(b_text)
                b_fingerprint = item_fingerprint(rel, "bullet", b_heading, b_text)
                b_identity_key = b_fingerprint_aliases[0]
                b_age_days = item_age_days(b_key, state, now_dt, now_str)
                b_hits, b_signal_count, b_last = collect_recall_metrics(str(rel), b_start, b_end, hits_by_path)
                b_evidence = item_evidence_for_span(
                    str(rel),
                    b_start,
                    b_end,
                    dream_hits_by_path,
                    telemetry_evidence_by_path,
                    item_content_hash=b_text_hash,
                    telemetry_index=telemetry_evidence_index,
                    ambiguous_content_hashes=ambiguous_content_hashes,
                    match_stats=telemetry_match_stats,
                )
                b_class, b_reason, b_pinned, b_seen_runs, b_recall_runs, b_unrecalled_runs = classify_item(
                    path_rel=rel,
                    kind="bullet",
                    heading=b_heading,
                    text=b_text,
                    item_key=b_key,
                    doc_char_count=doc_char_count,
                    recall_hits=b_hits,
                    recall_signal_count=b_signal_count,
                    item_age_days=b_age_days,
                    explicit_dates=b_dates,
                    evidence=b_evidence,
                    now_dt=now_dt,
                    state=state,
                    config=config,
                    run_bucket=run_bucket,
                )
                items.append(
                    Item(
                        key=b_key,
                        kind="bullet",
                        path=str(rel),
                        section_heading=b_heading,
                        heading_level=b_level,
                        start_line=b_start,
                        end_line=b_end,
                        char_count=len(b_text),
                        text_hash=b_text_hash,
                        explicit_dates=b_dates,
                        recall_hits=b_hits,
                        recall_signal_count=b_signal_count,
                        last_recalled_at=b_last,
                        age_days=round(b_age_days, 1),
                        pinned=b_pinned,
                        seen_runs=b_seen_runs,
                        recall_runs=b_recall_runs,
                        unrecalled_runs=b_unrecalled_runs,
                        classification=b_class,
                        reason=b_reason,
                        fingerprint=b_fingerprint,
                        identity_key=b_identity_key,
                        identity_mode="content-fingerprint",
                        evidence_class=b_evidence.evidence_class,
                        strong_evidence_hits=b_evidence.dream_strong_hits + b_evidence.telemetry_strong_targeted,
                        medium_evidence_hits=b_evidence.telemetry_medium_targeted,
                        weak_broad_evidence_hits=b_evidence.telemetry_weak_only + b_evidence.telemetry_broad_read_only,
                        telemetry_match_source=b_evidence.telemetry_match_source,
                        content_hash_recovered_hits=b_evidence.content_hash_recovered_hits,
                    )
                )
    items = enforce_project_spine_compressed_note_caps(items)
    budget_summary = build_hot_context_budget_summary(items)
    budget_summary["_now_iso"] = now_str
    return apply_project_spine_budget_pressure(items, budget_summary)


def load_state() -> dict:
    return load_json(STATE_PATH, {"version": 3, "identityMode": DEFAULT_IDENTITY_MODE, "items": {}, "fingerprints": {}})


def archive_state_tombstones(removed: dict[str, dict], now_str: str) -> str | None:
    if not removed:
        return None
    stamp = re.sub(r"[^0-9A-Za-z-]+", "-", now_str).strip("-")
    STATE_ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    archive_path = STATE_ARCHIVE_ROOT / f"context-pruning-state-tombstones-{stamp}.json"
    archive_path.write_text(
        json.dumps(
            {
                "removedAt": now_str,
                "retentionDays": STATE_TOMBSTONE_RETENTION_DAYS,
                "removedCount": len(removed),
                "removed": removed,
            },
            indent=2,
        )
        + "\n"
    )
    return str(archive_path)


def garbage_collect_state_tombstones(state: dict, now_dt: datetime, now_str: str) -> dict:
    item_state = state.setdefault("items", {})
    removed: dict[str, dict] = {}
    for key, entry in list(item_state.items()):
        missing_since_raw = entry.get("firstMissingAt") or entry.get("lastMissingAt")
        if not missing_since_raw:
            continue
        missing_since = parse_iso(missing_since_raw) or parse_iso(entry.get("lastSeenAt"))
        if not missing_since:
            continue
        if days_between(now_dt, missing_since) < STATE_TOMBSTONE_RETENTION_DAYS:
            continue
        removed[key] = entry
        del item_state[key]

    archive_path = archive_state_tombstones(removed, now_str)
    state["lastTombstoneGcAt"] = now_str
    state["lastTombstoneGcRemoved"] = len(removed)
    if archive_path:
        state["lastTombstoneArchive"] = archive_path
    return state


def update_state(
    state: dict,
    items: list[Item],
    now_str: str,
    run_bucket: str,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
) -> dict:
    identity_mode = normalize_identity_mode(identity_mode)
    now_dt = parse_iso(now_str)
    assert now_dt is not None
    state["version"] = 3
    state["identityMode"] = identity_mode
    item_state = state.setdefault("items", {})
    current_keys = {item.key for item in items}
    identity_key_counts = Counter(item.identity_key for item in items if item.identity_key)
    ambiguous_identity_keys = {key for key, count in identity_key_counts.items() if count > 1}
    if identity_mode == "content-primary":
        for identity_key in sorted(ambiguous_identity_keys):
            record_fingerprint_ambiguity(state, [identity_key])
    fingerprint_index: dict[str, str] = {}
    for item in items:
        entry = item_state.get(item.key, {})
        entry["kind"] = item.kind
        entry["path"] = item.path
        entry["section_heading"] = item.section_heading
        entry["docProfile"] = doc_profile(Path(item.path))
        entry["textHash"] = item.text_hash
        entry["fingerprint"] = item.fingerprint
        entry["identityKey"] = item.identity_key
        entry["identityMode"] = item.identity_mode
        entry["lastLineSpan"] = {"startLine": item.start_line, "endLine": item.end_line}
        entry["firstSeenAt"] = entry.get("firstSeenAt", now_str)
        entry["lastSeenAt"] = now_str
        entry["seenRuns"] = item.seen_runs
        entry["recallRuns"] = item.recall_runs
        entry["unrecalledRuns"] = item.unrecalled_runs
        if item.last_recalled_at:
            entry["firstRecalledAt"] = entry.get("firstRecalledAt", item.last_recalled_at)
            entry["lastRecalledAt"] = item.last_recalled_at
        entry["maxCharCount"] = max(int(entry.get("maxCharCount", 0)), item.char_count)
        entry["classification"] = item.classification
        entry["reason"] = item.reason
        entry["lastCountedBucket"] = run_bucket
        entry.pop("firstMissingAt", None)
        entry.pop("lastMissingAt", None)
        item_state[item.key] = entry
        if item.identity_key and item.identity_key not in ambiguous_identity_keys:
            fingerprint_index[item.identity_key] = item.key
    state["fingerprints"] = fingerprint_index
    for key, entry in item_state.items():
        if key not in current_keys:
            entry.setdefault("firstMissingAt", entry.get("lastSeenAt") or entry.get("lastMissingAt") or now_str)
            entry["lastMissingAt"] = now_str
    state["updatedAt"] = now_str
    state.pop(FINGERPRINT_AMBIGUITY_WARNED_KEY, None)
    return garbage_collect_state_tombstones(state, now_dt, now_str)


def candidate_state_metadata(candidate: StateRebaseCandidate) -> dict[str, object]:
    return {
        "kind": candidate.kind,
        "path": candidate.path,
        "section_heading": candidate.section_heading,
        "docProfile": doc_profile(Path(candidate.path)),
        "textHash": candidate.text_hash,
        "fingerprint": candidate.fingerprint,
        "identityKey": candidate.identity_key,
        "identityMode": candidate.identity_mode,
        "lastLineSpan": {"startLine": candidate.start_line, "endLine": candidate.end_line},
    }


def new_state_entry_for_candidate(candidate: StateRebaseCandidate, now_str: str) -> dict:
    return {
        **candidate_state_metadata(candidate),
        "firstSeenAt": now_str,
        "lastSeenAt": now_str,
        "seenRuns": 0,
        "recallRuns": 0,
        "unrecalledRuns": 0,
        "maxCharCount": candidate.char_count,
    }


def rebase_state_entry_from_matches(
    candidate: StateRebaseCandidate,
    matches: list[tuple[str, dict]],
    *,
    matched_by: str,
    now_str: str,
) -> dict:
    if not matches:
        return new_state_entry_for_candidate(candidate, now_str)
    entry = aggregate_state_matches(matches)
    migrated_from = [key for key, _entry in matches if key != candidate.key]
    if migrated_from:
        entry["migratedFrom"] = migrated_from[:10]
    else:
        entry.pop("migratedFrom", None)
    entry["identityMatchedBy"] = matched_by
    entry.update(candidate_state_metadata(candidate))
    entry["firstSeenAt"] = entry.get("firstSeenAt", now_str)
    entry["lastSeenAt"] = entry.get("lastSeenAt", now_str)
    entry["seenRuns"] = int(entry.get("seenRuns", 0) or 0)
    entry["recallRuns"] = int(entry.get("recallRuns", 0) or 0)
    entry["unrecalledRuns"] = int(entry.get("unrecalledRuns", 0) or 0)
    entry["maxCharCount"] = int(entry.get("maxCharCount", candidate.char_count) or candidate.char_count)
    entry.pop("firstMissingAt", None)
    entry.pop("lastMissingAt", None)
    return entry


def exact_rebase_matches(item_state: dict, candidate: StateRebaseCandidate) -> list[tuple[str, dict]]:
    matches: list[tuple[str, dict]] = []
    for key in [candidate.key, *candidate.exact_aliases]:
        entry = item_state.get(key)
        if isinstance(entry, dict) and key not in {match_key for match_key, _entry in matches}:
            matches.append((key, entry))
    return matches


def prefix_rebase_matches(item_state: dict, candidate: StateRebaseCandidate) -> list[tuple[str, dict]]:
    matches: list[tuple[str, dict]] = []
    for prefix in candidate.prefix_aliases:
        for key, entry in item_state.items():
            if isinstance(entry, dict) and key.startswith(prefix) and key not in {match_key for match_key, _entry in matches}:
                matches.append((key, entry))
    return matches


def fingerprint_rebase_matches(
    state: dict,
    candidate: StateRebaseCandidate,
    ambiguous_live_fingerprints: set[str],
) -> tuple[list[tuple[str, dict]], bool]:
    if set(candidate.fingerprint_aliases) & ambiguous_live_fingerprints:
        return [], True
    return fingerprint_state_matches(state, candidate.fingerprint_aliases)


def build_rebased_state(previous_state: dict, now_str: str, identity_mode: str = DEFAULT_IDENTITY_MODE) -> tuple[dict, dict]:
    identity_mode = normalize_identity_mode(identity_mode)
    item_state = previous_state.get("items") if isinstance(previous_state.get("items"), dict) else {}
    candidates = current_state_rebase_candidates()
    identity_counts = Counter(candidate.identity_key for candidate in candidates if candidate.identity_key)
    ambiguous_live_fingerprints = (
        {key for key, count in identity_counts.items() if count > 1}
        if identity_mode == "content-primary"
        else set()
    )
    new_items: dict[str, dict] = {}
    fingerprint_index: dict[str, str] = {}
    used_source_keys: set[str] = set()
    match_counts = Counter()
    ambiguous_fingerprints: set[str] = set(ambiguous_live_fingerprints)

    for candidate in candidates:
        exact_matches = [(key, entry) for key, entry in exact_rebase_matches(item_state, candidate) if key not in used_source_keys]
        if exact_matches:
            entry = rebase_state_entry_from_matches(candidate, exact_matches, matched_by="exact", now_str=now_str)
            used_source_keys.update(key for key, _entry in exact_matches)
            match_counts["exact"] += 1
        else:
            entry = None
            if identity_mode == "content-primary":
                fingerprint_matches, fingerprint_ambiguous = fingerprint_rebase_matches(
                    previous_state,
                    candidate,
                    ambiguous_live_fingerprints,
                )
                fingerprint_matches = [(key, entry) for key, entry in fingerprint_matches if key not in used_source_keys]
                if fingerprint_ambiguous:
                    ambiguous_fingerprints.update(candidate.fingerprint_aliases)
                    entry = new_state_entry_for_candidate(candidate, now_str)
                    match_counts["fresh"] += 1
                elif fingerprint_matches:
                    entry = rebase_state_entry_from_matches(
                        candidate,
                        fingerprint_matches,
                        matched_by="fingerprint",
                        now_str=now_str,
                    )
                    used_source_keys.update(key for key, _entry in fingerprint_matches)
                    match_counts["fingerprint"] += 1
            if entry is None:
                prefix_matches = [(key, entry) for key, entry in prefix_rebase_matches(item_state, candidate) if key not in used_source_keys]
                if prefix_matches:
                    entry = rebase_state_entry_from_matches(candidate, prefix_matches, matched_by="prefix", now_str=now_str)
                    used_source_keys.update(key for key, _entry in prefix_matches)
                    match_counts["prefix"] += 1
                else:
                    entry = new_state_entry_for_candidate(candidate, now_str)
                    match_counts["fresh"] += 1
        new_items[candidate.key] = entry
        if candidate.identity_key and candidate.identity_key not in ambiguous_live_fingerprints:
            fingerprint_index[candidate.identity_key] = candidate.key

    for key, entry in item_state.items():
        if key in used_source_keys or key in new_items:
            continue
        new_items[key] = dict(entry) if isinstance(entry, dict) else entry

    new_state = json.loads(json.dumps({key: value for key, value in previous_state.items() if key not in {"items", "fingerprints"}}))
    new_state.update(
        {
            "version": 3,
            "identityMode": identity_mode,
            "updatedAt": now_str,
            "items": new_items,
            "fingerprints": fingerprint_index,
        }
    )
    if ambiguous_fingerprints:
        warning_counters = new_state.setdefault("warningCounters", {})
        if isinstance(warning_counters, dict):
            warning_counters["fingerprint_ambiguous"] = int(warning_counters.get("fingerprint_ambiguous", 0) or 0) + len(ambiguous_fingerprints)
    new_state.pop(FINGERPRINT_AMBIGUITY_WARNED_KEY, None)
    manifest = {
        "old_version": previous_state.get("version", 0),
        "new_version": 3,
        "identityMode": identity_mode,
        "current_item_count": len(candidates),
        "previous_entry_count": len(item_state),
        "rebased_entry_count": len(new_items),
        "entries_preserved_by_exact_key": int(match_counts["exact"]),
        "entries_preserved_by_fingerprint": int(match_counts["fingerprint"]),
        "entries_preserved_by_prefix_alias": int(match_counts["prefix"]),
        "entries_started_fresh": int(match_counts["fresh"]),
        "unmatched_previous_entries_preserved": len([key for key in item_state if key not in used_source_keys]),
        "ambiguous_fingerprints": sorted(ambiguous_fingerprints),
        "ambiguous_fingerprint_count": len(ambiguous_fingerprints),
    }
    return new_state, manifest


def state_rebase_archive_path(stamp: str) -> Path:
    safe_stamp = re.sub(r"[^0-9A-Za-z._-]+", "-", stamp).strip("-_") or "state-rebase"
    return STATE_REBASE_ARCHIVE_ROOT / safe_stamp / "context-pruning-state.before.json"


def run_state_rebase(*, stamp: str, apply: bool, now_str: str, identity_mode: str = DEFAULT_IDENTITY_MODE) -> dict:
    identity_mode = normalize_identity_mode(identity_mode)
    previous_state = load_state()
    rebased_state, manifest = build_rebased_state(previous_state, now_str, identity_mode=identity_mode)
    manifest = {
        **manifest,
        "stamp": stamp,
        "dry_run": not apply,
        "state_path": str(STATE_PATH),
        "preview_path": str(STATE_REBASE_PREVIEW_PATH),
        "manifest_path": str(STATE_REBASE_MANIFEST_PATH),
        "archived_state_path": None,
    }
    if not apply:
        atomic_write_json(STATE_REBASE_PREVIEW_PATH, {"manifest": manifest, "proposed_state": rebased_state})
        return manifest

    archive_path = state_rebase_archive_path(stamp)
    if STATE_PATH.exists():
        archive_content = STATE_PATH.read_text(encoding="utf-8")
    else:
        archive_content = json.dumps(previous_state, indent=2, sort_keys=True) + "\n"
    atomic_write_text(archive_path, archive_content)
    manifest["archived_state_path"] = str(archive_path)
    atomic_write_json(STATE_PATH, rebased_state)
    atomic_write_json(STATE_REBASE_MANIFEST_PATH, manifest)
    return manifest


def json_payload_bytes(payload: object) -> int:
    return len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def compact_json_text(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"


def compact_json_payload_bytes(payload: object) -> int:
    return len(compact_json_text(payload).encode("utf-8"))


def atomic_write_compact_json(path: Path, payload: dict) -> None:
    atomic_write_text(path, compact_json_text(payload))


def state_compaction_archive_root(stamp: str) -> Path:
    safe_stamp = re.sub(r"[^0-9A-Za-z._-]+", "-", stamp).strip("-_") or "state-compaction"
    return STATE_ARCHIVE_ROOT / safe_stamp


def state_compaction_archive_path(stamp: str) -> Path:
    return state_compaction_archive_root(stamp) / "context-pruning-state.before-compaction.json"


def state_history_shard_root(stamp: str) -> Path:
    safe_stamp = re.sub(r"[^0-9A-Za-z._-]+", "-", stamp).strip("-_") or "state-compaction"
    return STATE_HISTORY_SHARD_ROOT / safe_stamp


def state_pruning_hard_budget_bytes() -> int:
    budget = STATE_FILE_BUDGETS.get(Path("context/state/context-pruning-state.json"), {})
    return int(budget.get("hard_bytes") or 500_000)


def compact_state_iso_day(value: object) -> object:
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        return value
    return parsed.astimezone(timezone.utc).date().isoformat()


def compact_state_entry(entry: dict, *, current: bool, identity_key: str | None = None) -> dict:
    fields = STATE_COMPACT_CURRENT_ENTRY_FIELDS if current else STATE_COMPACT_RETAINED_ENTRY_FIELDS
    compacted: dict[str, object] = {}
    for field in fields:
        if field == "identityKey" and identity_key:
            value = identity_key
        elif field == "lastMissingAt" and not current:
            value = entry.get("lastMissingAt") or entry.get("firstMissingAt") or entry.get("lastSeenAt")
        elif field in entry:
            value = entry[field]
        else:
            continue
        if field in {"firstSeenAt", "lastMissingAt"}:
            value = compact_state_iso_day(value)
        compacted[field] = value
    return compacted


def state_history_reference_dt(entry: dict) -> datetime | None:
    return parse_iso(entry.get("lastMissingAt") or entry.get("firstMissingAt") or entry.get("lastSeenAt") or entry.get("firstSeenAt"))


def state_history_drop_sort_key(record: dict[str, object]) -> tuple[object, ...]:
    entry = record.get("entry") if isinstance(record.get("entry"), dict) else {}
    ref_dt = record.get("reference_dt")
    ref_epoch = ref_dt.timestamp() if isinstance(ref_dt, datetime) else 0.0
    return (
        1 if int(entry.get("recallRuns", 0) or 0) > 0 else 0,
        int(entry.get("seenRuns", 0) or 0),
        ref_epoch,
        str(record.get("key") or ""),
    )


def state_history_archive_records(archived_items: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for key in sorted(archived_items):
        payload = archived_items[key]
        records.append(
            {
                "key": key,
                "reason": payload.get("reason") or "unknown",
                "archivedAt": payload.get("archivedAt"),
                "entry": payload.get("entry"),
            }
        )
    return records


def planned_state_history_shard_refs(archived_items: dict[str, dict[str, object]], *, stamp: str) -> list[dict[str, object]]:
    records = state_history_archive_records(archived_items)
    if not records:
        return []
    root = state_history_shard_root(stamp)
    refs: list[dict[str, object]] = []
    for index in range(0, len(records), STATE_HISTORY_SHARD_MAX_ENTRIES):
        shard_records = records[index : index + STATE_HISTORY_SHARD_MAX_ENTRIES]
        shard_no = len(refs) + 1
        path = root / f"context-pruning-history-{shard_no:04d}.jsonl"
        text = "".join(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n" for record in shard_records)
        refs.append(
            {
                "path": str(path),
                "entry_count": len(shard_records),
                "bytes": len(text.encode("utf-8")),
            }
        )
    return refs


def write_state_history_shards(archived_items: dict[str, dict[str, object]], *, stamp: str) -> list[dict[str, object]]:
    records = state_history_archive_records(archived_items)
    refs = planned_state_history_shard_refs(archived_items, stamp=stamp)
    if not records:
        return []
    for ref_index, ref in enumerate(refs):
        start = ref_index * STATE_HISTORY_SHARD_MAX_ENTRIES
        shard_records = records[start : start + STATE_HISTORY_SHARD_MAX_ENTRIES]
        text = "".join(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n" for record in shard_records)
        atomic_write_text(Path(str(ref["path"])), text)
    return refs


def finalize_compacted_state(compacted: dict, manifest: dict, *, before_bytes: int, hard_budget_bytes: int) -> tuple[dict, dict]:
    compacted["lastCompaction"] = manifest
    after_bytes = compact_json_payload_bytes(compacted)
    manifest["state_bytes_after_planned"] = after_bytes
    manifest["state_bytes_delta_planned"] = after_bytes - before_bytes
    manifest["state_budget_met"] = after_bytes <= hard_budget_bytes
    manifest["state_budget_status"] = "state_budget_met" if manifest["state_budget_met"] else "degraded_state_budget_unmet"
    manifest["state_bytes_over_hard"] = max(0, after_bytes - hard_budget_bytes)
    compacted["lastCompaction"] = manifest
    after_bytes = compact_json_payload_bytes(compacted)
    manifest["state_bytes_after_planned"] = after_bytes
    manifest["state_bytes_delta_planned"] = after_bytes - before_bytes
    manifest["state_budget_met"] = after_bytes <= hard_budget_bytes
    manifest["state_budget_status"] = "state_budget_met" if manifest["state_budget_met"] else "degraded_state_budget_unmet"
    manifest["state_bytes_over_hard"] = max(0, after_bytes - hard_budget_bytes)
    compacted["lastCompaction"] = manifest
    return compacted, manifest


def build_compacted_state_payload(
    *,
    state: dict,
    stamp: str,
    now: datetime,
    retained_items: dict[str, dict],
    retained_metadata: dict[str, dict[str, object]],
    archived_items: dict[str, dict[str, object]],
    keep_reasons: Counter[str],
    drop_reasons: Counter[str],
    before_bytes: int,
    previous_items_count: int,
    previous_fingerprints_count: int,
    hard_budget_bytes: int,
) -> tuple[dict, dict]:
    shard_refs = planned_state_history_shard_refs(archived_items, stamp=stamp)
    compact_fingerprints: dict[str, str] = {}
    current_count = sum(1 for record in retained_metadata.values() if bool(record.get("current")))
    history_count = len(retained_items) - current_count
    dropped_sample = [
        (
            key,
            {
                "reason": payload.get("reason"),
                "lastSeenAt": (payload.get("entry") if isinstance(payload.get("entry"), dict) else {}).get("lastSeenAt"),
                "firstMissingAt": (payload.get("entry") if isinstance(payload.get("entry"), dict) else {}).get("firstMissingAt"),
                "lastMissingAt": (payload.get("entry") if isinstance(payload.get("entry"), dict) else {}).get("lastMissingAt"),
                "identityKey": (payload.get("entry") if isinstance(payload.get("entry"), dict) else {}).get("identityKey"),
                "fingerprint": (payload.get("entry") if isinstance(payload.get("entry"), dict) else {}).get("fingerprint"),
            },
        )
        for key, payload in list(sorted(archived_items.items()))[:STATE_COMPACTION_DROPPED_SAMPLE_LIMIT]
    ]
    compacted = {
        "version": 3,
        "identityMode": state.get("identityMode") or DEFAULT_IDENTITY_MODE,
        "updatedAt": state.get("updatedAt"),
        "items": retained_items,
        "fingerprints": compact_fingerprints,
        "archivedHistoryShards": shard_refs,
        "droppedReasonCounts": dict(sorted(drop_reasons.items())),
    }
    manifest = {
        "schema_version": "workbench-context-pruning-state-compaction/v2",
        "stamp": stamp,
        "compacted_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "retention_days": STATE_TOMBSTONE_RETENTION_DAYS,
        "state_hard_budget_bytes": hard_budget_bytes,
        "entries_before": previous_items_count,
        "entries_after": len(retained_items),
        "entries_retained_current": current_count,
        "entries_retained_history": history_count,
        "entries_archived": len(archived_items),
        "entries_dropped": len(archived_items),
        "fingerprints_before": previous_fingerprints_count,
        "fingerprints_after": len(compact_fingerprints),
        "state_bytes_before": before_bytes,
        "state_bytes_after_planned": 0,
        "state_bytes_delta_planned": 0,
        "state_budget_met": False,
        "state_budget_status": "unknown",
        "state_bytes_over_hard": 0,
        "kept_by_reason": dict(sorted(keep_reasons.items())),
        "dropped_by_reason": dict(sorted(drop_reasons.items())),
        "dropped_reason_counts": dict(sorted(drop_reasons.items())),
        "archived_history_shards": shard_refs,
        "archived_history_shard_count": len(shard_refs),
        "dropped_entry_count": len(archived_items),
        "dropped_entries_sample": dropped_sample,
    }
    return finalize_compacted_state(compacted, manifest, before_bytes=before_bytes, hard_budget_bytes=hard_budget_bytes)


def compact_pruning_state(
    state: dict,
    current_items: list[Item],
    *,
    now: datetime,
    stamp: str,
    hard_budget_bytes: int | None = None,
    write_history_shards: bool = False,
) -> dict:
    hard_budget_bytes = int(hard_budget_bytes or state_pruning_hard_budget_bytes())
    previous_items = state.get("items") if isinstance(state.get("items"), dict) else {}
    previous_fingerprints = state.get("fingerprints") if isinstance(state.get("fingerprints"), dict) else {}
    current_keys = {item.key for item in current_items if item.key}
    current_identity_by_key = {item.key: item.identity_key for item in current_items if item.key and item.identity_key}
    current_identity_counts = Counter(item.identity_key for item in current_items if item.identity_key)
    current_identity_keys = {key for key, count in current_identity_counts.items() if count == 1}
    current_fingerprints = {item.fingerprint for item in current_items if item.fingerprint}
    current_fingerprint_mapped_keys: set[str] = set()
    for fingerprint in current_identity_keys:
        mapped = previous_fingerprints.get(fingerprint)
        if isinstance(mapped, str) and mapped:
            current_fingerprint_mapped_keys.add(mapped)
        elif isinstance(mapped, list):
            current_fingerprint_mapped_keys.update(value for value in mapped if isinstance(value, str) and value)

    retained_items: dict[str, dict] = {}
    retained_metadata: dict[str, dict[str, object]] = {}
    archived_items: dict[str, dict[str, object]] = {}
    keep_reasons: Counter[str] = Counter()
    drop_reasons: Counter[str] = Counter()
    archived_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for key, entry in previous_items.items():
        if not isinstance(entry, dict):
            drop_reasons["invalid_entry"] += 1
            archived_items[str(key)] = {"reason": "invalid_entry", "entry": entry, "archivedAt": archived_at}
            continue
        reason: str | None = None
        if key in current_keys:
            reason = "current_key"
        elif key in current_fingerprint_mapped_keys:
            reason = "current_fingerprint_index"
        elif entry.get("identityKey") in current_identity_keys or entry.get("fingerprint") in current_fingerprints:
            reason = "current_fingerprint_metadata"
        else:
            reference_dt = state_history_reference_dt(entry)
            if reference_dt is None:
                reason = "undated_orphan_retained"
            elif days_between(now, reference_dt) < STATE_TOMBSTONE_RETENTION_DAYS:
                reason = "recent_tombstone_or_alias"
            else:
                reason = "expired_orphan"
        if reason == "expired_orphan":
            drop_reasons[reason] += 1
            archived_items[str(key)] = {
                "reason": reason,
                "entry": entry,
                "archivedAt": archived_at,
            }
            continue
        is_current_retained = reason in {"current_key", "current_fingerprint_index", "current_fingerprint_metadata"}
        retained_items[str(key)] = compact_state_entry(
            entry,
            current=is_current_retained,
            identity_key=current_identity_by_key.get(str(key)) if is_current_retained else None,
        )
        retained_metadata[str(key)] = {
            "key": str(key),
            "entry": entry,
            "reason": reason or "unknown",
            "current": is_current_retained,
            "reference_dt": state_history_reference_dt(entry),
        }
        keep_reasons[reason or "unknown"] += 1

    before_bytes = json_payload_bytes(state)
    compacted, manifest = build_compacted_state_payload(
        state=state,
        stamp=stamp,
        now=now,
        retained_items=retained_items,
        retained_metadata=retained_metadata,
        archived_items=archived_items,
        keep_reasons=keep_reasons,
        drop_reasons=drop_reasons,
        before_bytes=before_bytes,
        previous_items_count=len(previous_items),
        previous_fingerprints_count=len(previous_fingerprints),
        hard_budget_bytes=hard_budget_bytes,
    )
    while not bool(manifest.get("state_budget_met")):
        drop_candidates = [
            record
            for record in retained_metadata.values()
            if not bool(record.get("current")) and str(record.get("key") or "") in retained_items
        ]
        if not drop_candidates:
            break
        candidate = sorted(drop_candidates, key=state_history_drop_sort_key)[0]
        candidate_key = str(candidate.get("key") or "")
        original_entry = candidate.get("entry") if isinstance(candidate.get("entry"), dict) else {}
        original_reason = str(candidate.get("reason") or "history")
        retained_items.pop(candidate_key, None)
        retained_metadata.pop(candidate_key, None)
        keep_reasons[original_reason] -= 1
        if keep_reasons[original_reason] <= 0:
            del keep_reasons[original_reason]
        drop_reason = f"budget_drop_{original_reason}"
        drop_reasons[drop_reason] += 1
        archived_items[candidate_key] = {
            "reason": drop_reason,
            "entry": original_entry,
            "archivedAt": archived_at,
        }
        compacted, manifest = build_compacted_state_payload(
            state=state,
            stamp=stamp,
            now=now,
            retained_items=retained_items,
            retained_metadata=retained_metadata,
            archived_items=archived_items,
            keep_reasons=keep_reasons,
            drop_reasons=drop_reasons,
            before_bytes=before_bytes,
            previous_items_count=len(previous_items),
            previous_fingerprints_count=len(previous_fingerprints),
            hard_budget_bytes=hard_budget_bytes,
        )
    if write_history_shards and archived_items:
        shard_refs = write_state_history_shards(archived_items, stamp=stamp)
        compacted["archivedHistoryShards"] = shard_refs
        manifest["archived_history_shards"] = shard_refs
        manifest["archived_history_shard_count"] = len(shard_refs)
        compacted, manifest = finalize_compacted_state(
            compacted,
            manifest,
            before_bytes=before_bytes,
            hard_budget_bytes=hard_budget_bytes,
        )
    return compacted


def run_state_compaction(*, stamp: str, apply: bool, now_str: str, identity_mode: str = DEFAULT_IDENTITY_MODE) -> dict:
    identity_mode = normalize_identity_mode(identity_mode)
    previous_state = load_state()
    now_dt = parse_iso(now_str)
    assert now_dt is not None
    run_bucket = run_bucket_from_iso(now_str)
    config = AuditConfig(
        stale_days=DEFAULT_STALE_DAYS,
        dormant_days=DEFAULT_DORMANT_DAYS,
        recent_grace_days=DEFAULT_RECENT_GRACE_DAYS,
        min_seen_runs_review=DEFAULT_MIN_SEEN_RUNS_REVIEW,
        min_seen_runs_prune=DEFAULT_MIN_SEEN_RUNS_PRUNE,
        min_unrecalled_runs_review=DEFAULT_MIN_UNRECALLED_RUNS_REVIEW,
        min_unrecalled_runs_prune=DEFAULT_MIN_UNRECALLED_RUNS_PRUNE,
    )
    current_items = build_items(now_dt, previous_state, config, run_bucket, identity_mode=identity_mode)
    archive_path = state_compaction_archive_path(stamp)
    real_hard_budget_bytes = state_pruning_hard_budget_bytes()
    manifest_overhead_reserve = max(
        1024,
        len(str(archive_path).encode("utf-8"))
        + len(str(STATE_COMPACTION_PREVIEW_PATH).encode("utf-8"))
        + len(str(STATE_COMPACTION_MANIFEST_PATH).encode("utf-8"))
        + 512,
    )
    planning_hard_budget_bytes = max(1, real_hard_budget_bytes - manifest_overhead_reserve)
    compacted_state = compact_pruning_state(
        previous_state,
        current_items,
        now=now_dt,
        stamp=stamp,
        hard_budget_bytes=planning_hard_budget_bytes,
        write_history_shards=apply,
    )
    compacted_state["identityMode"] = identity_mode
    manifest = dict(compacted_state.get("lastCompaction") if isinstance(compacted_state.get("lastCompaction"), dict) else {})
    state_bytes_before = STATE_PATH.stat().st_size if STATE_PATH.exists() else json_payload_bytes(previous_state)
    manifest["state_bytes_before"] = state_bytes_before
    manifest.update(
        {
            "identityMode": identity_mode,
            "dry_run": not apply,
            "state_hard_budget_bytes": real_hard_budget_bytes,
            "state_path": str(STATE_PATH),
            "preview_path": str(STATE_COMPACTION_PREVIEW_PATH),
            "manifest_path": str(STATE_COMPACTION_MANIFEST_PATH),
            "archived_state_path": None,
        }
    )
    compacted_state, manifest = finalize_compacted_state(
        compacted_state,
        manifest,
        before_bytes=state_bytes_before,
        hard_budget_bytes=real_hard_budget_bytes,
    )
    if not apply:
        atomic_write_compact_json(STATE_COMPACTION_PREVIEW_PATH, {"manifest": manifest, "proposed_state": compacted_state})
        return manifest

    if STATE_PATH.exists():
        archive_content = STATE_PATH.read_text(encoding="utf-8")
    else:
        archive_content = json.dumps(previous_state, indent=2, sort_keys=True) + "\n"
    atomic_write_text(archive_path, archive_content)
    manifest["archived_state_path"] = str(archive_path)
    compacted_state, manifest = finalize_compacted_state(
        compacted_state,
        manifest,
        before_bytes=state_bytes_before,
        hard_budget_bytes=real_hard_budget_bytes,
    )
    atomic_write_compact_json(STATE_PATH, compacted_state)
    atomic_write_json(STATE_COMPACTION_MANIFEST_PATH, manifest)
    return manifest


def byte_line_stats(path: Path) -> dict[str, object]:
    if not path.exists() or not path.is_file():
        return {"exists": False, "bytes": 0, "lines": 0}
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return {"exists": True, "bytes": len(data), "lines": len(text.splitlines())}


def pressure_level(byte_count: int, target_bytes: int | None, hard_bytes: int | None) -> str:
    if hard_bytes is not None and byte_count > hard_bytes:
        return "hard"
    if target_bytes is not None and byte_count > target_bytes:
        return "target"
    return "none"


def budget_record(path_rel: Path, budget: dict[str, object] | None, *, default_mode: str) -> dict[str, object]:
    stats = byte_line_stats(WORKBENCH_ROOT / path_rel)
    byte_count = int(stats["bytes"])
    target = budget.get("target_bytes") if budget else None
    hard = budget.get("hard_bytes") if budget else None
    target_int = int(target) if target is not None else None
    hard_int = int(hard) if hard is not None else None
    return {
        "path": str(path_rel),
        "exists": bool(stats["exists"]),
        "bytes": byte_count,
        "lines": int(stats["lines"]),
        "target_bytes": target_int,
        "hard_bytes": hard_int,
        "bytes_over_target": max(0, byte_count - target_int) if target_int is not None else 0,
        "bytes_over_hard": max(0, byte_count - hard_int) if hard_int is not None else 0,
        "pressure_level": pressure_level(byte_count, target_int, hard_int),
        "enforcement_mode": str(budget.get("mode") if budget and budget.get("mode") else default_mode),
    }


def markdown_section_text(text: str, heading: str) -> tuple[str, int | None, int | None]:
    lines = text.splitlines()
    wanted = normalized_heading(heading)
    start_idx: int | None = None
    start_level: int | None = None
    for idx, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match or normalized_heading(match.group(2)) != wanted:
            continue
        start_idx = idx
        start_level = len(match.group(1))
        break
    if start_idx is None or start_level is None:
        return "", None, None
    end_idx = len(lines)
    for idx in range(start_idx + 1, len(lines)):
        match = HEADING_RE.match(lines[idx])
        if match and len(match.group(1)) <= start_level:
            end_idx = idx
            break
    section_lines = lines[start_idx:end_idx]
    section_text = "\n".join(section_lines) + ("\n" if section_lines else "")
    return section_text, start_idx + 1, end_idx


def active_live_heading_budget_records() -> dict[str, dict[str, object]]:
    active_path = WORKBENCH_ROOT / "context/active.md"
    try:
        text = active_path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    records: dict[str, dict[str, object]] = {}
    for heading, budget in ACTIVE_LIVE_HEADING_BUDGETS.items():
        section_text, start_line, end_line = markdown_section_text(text, heading)
        byte_count = len(section_text.encode("utf-8"))
        target = int(budget["target_bytes"])
        hard = int(budget["hard_bytes"])
        records[heading] = {
            "path": "context/active.md",
            "heading": heading,
            "exists": start_line is not None,
            "start_line": start_line,
            "end_line": end_line,
            "bytes": byte_count,
            "lines": len(section_text.splitlines()),
            "target_bytes": target,
            "hard_bytes": hard,
            "summary_max_chars": int(budget.get("summary_max_chars") or 0),
            "bytes_over_target": max(0, byte_count - target),
            "bytes_over_hard": max(0, byte_count - hard),
            "pressure_level": pressure_level(byte_count, target, hard),
            "enforcement_mode": str(budget.get("mode") or "active_live_heading_summary"),
        }
    return records


def line_count(text: str) -> int:
    return len(text.splitlines())


def section_records_for_text(text: str) -> list[dict[str, object]]:
    lines = text.splitlines()
    records: list[dict[str, object]] = []
    for heading, level, start_line, end_line in split_sections(lines):
        if level <= 0:
            continue
        section_text = "\n".join(lines[start_line - 1 : end_line])
        records.append(
            {
                "heading": heading,
                "level": level,
                "start_line": start_line,
                "end_line": end_line,
                "lines": max(0, end_line - start_line + 1),
                "bytes": len((section_text + ("\n" if section_text else "")).encode("utf-8")),
                "chars": len(section_text),
            }
        )
    return records


def bullet_records_for_text(text: str) -> list[dict[str, object]]:
    lines = text.splitlines()
    bullets: list[dict[str, object]] = []
    for heading, level, start_line, end_line in split_sections(lines):
        for section_heading, _section_level, bullet_start, bullet_end, bullet_text in extract_bullets(lines, heading, level, start_line, end_line):
            bullets.append(
                {
                    "heading": section_heading,
                    "start_line": bullet_start,
                    "end_line": bullet_end,
                    "lines": max(0, bullet_end - bullet_start + 1),
                    "bytes": len((bullet_text + ("\n" if bullet_text else "")).encode("utf-8")),
                    "chars": len(bullet_text),
                    "text": bullet_text,
                }
            )
    return bullets


def normalized_bullet_text(text: str) -> str:
    return re.sub(r"\s+", " ", strip_markdown_marker(text).strip().lower())


def durable_rule_prefix(text: str) -> str:
    normalized = normalized_bullet_text(text)
    words = re.findall(r"[a-z0-9_/-]+", normalized)
    return " ".join(words[:8])


def likely_exact_duplicate_bullets(bullets: list[dict[str, object]], *, limit: int = 10) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for bullet in bullets:
        key = normalized_bullet_text(str(bullet.get("text") or ""))
        if key:
            grouped.setdefault(key, []).append(bullet)
    duplicates: list[dict[str, object]] = []
    for key, rows in grouped.items():
        if len(rows) <= 1:
            continue
        first = rows[0]
        duplicates.append(
            {
                "text_prefix": key[:160],
                "count": len(rows),
                "first_heading": first.get("heading"),
                "first_start_line": first.get("start_line"),
                "line_refs": [int(row.get("start_line") or 0) for row in rows[:limit]],
            }
        )
    duplicates.sort(key=lambda row: (-int(row.get("count", 0)), str(row.get("text_prefix", ""))))
    return duplicates[:limit]


def likely_same_prefix_durable_rules(bullets: list[dict[str, object]], *, limit: int = 10) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for bullet in bullets:
        prefix = durable_rule_prefix(str(bullet.get("text") or ""))
        if len(prefix.split()) >= 4:
            grouped.setdefault(prefix, []).append(bullet)
    records: list[dict[str, object]] = []
    for prefix, rows in grouped.items():
        distinct = {normalized_bullet_text(str(row.get("text") or "")) for row in rows}
        if len(rows) <= 1 or len(distinct) <= 1:
            continue
        records.append(
            {
                "prefix": prefix,
                "count": len(rows),
                "distinct_count": len(distinct),
                "line_refs": [int(row.get("start_line") or 0) for row in rows[:limit]],
            }
        )
    records.sort(key=lambda row: (-int(row.get("count", 0)), str(row.get("prefix", ""))))
    return records[:limit]


def top_sized_records(records: list[dict[str, object]], *, limit: int = 10) -> list[dict[str, object]]:
    cleaned: list[dict[str, object]] = []
    for record in sorted(records, key=lambda row: (-int(row.get("bytes") or 0), int(row.get("start_line") or 0)))[:limit]:
        cleaned.append({key: value for key, value in record.items() if key != "text"})
    return cleaned


def apply_status_for_non_prunable(path_rel: Path) -> str:
    if path_rel == DECISIONS_PATH:
        return "protected_autonomous_consolidation"
    if path_rel in HOT_CONTEXT_BUDGETS:
        return "protected_autonomous_summary"
    return "protected_no_budget"


def decisions_priority_bucket(byte_count: int, largest_section_chars: int) -> str:
    if byte_count >= DECISIONS_HARD_BYTES or largest_section_chars >= DECISIONS_HIGH_SECTION_CHARS:
        return "high"
    if byte_count >= DECISIONS_TARGET_BYTES or largest_section_chars >= DECISIONS_MEDIUM_SECTION_CHARS:
        return "medium"
    return "low"


def matching_lines(lines: list[str], patterns: list[str]) -> list[dict[str, object]]:
    regexes = [re.compile(pattern, re.I) for pattern in patterns]
    matches: list[dict[str, object]] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if any(regex.search(stripped) for regex in regexes):
            matches.append({"line": idx, "text": stripped[:220]})
    return matches[:20]


def decisions_invariant_inventory_for_text(text: str) -> dict:
    lines = text.splitlines()
    headings = [match.group(2).strip() for line in lines if (match := HEADING_RE.match(line))]
    return {
        "headings_present": headings,
        "explicit_keep_markers": [
            {"line": idx, "text": line.strip()[:220]}
            for idx, line in enumerate(lines, start=1)
            if KEEP_COMMENT_RE.search(line)
        ][:20],
        "safety_boundary_phrases": matching_lines(lines, [r"\bsafety\b", r"\bboundar", r"\bprivate\b", r"\bsecret", r"\bexfiltrat", r"\bdestructive\b", r"\bpermission\b", r"\bapproval\b"]),
        "file_role_rules": matching_lines(lines, [r"\bMEMORY\.md\b", r"\bactive\.md\b", r"\bdecisions\.md\b", r"\bcontext/projects\b", r"\bbootstrap\.md\b", r"\bmemory/YYYY-MM-DD\.md\b", r"\bbelongs\b", r"\bshould hold\b"]),
        "workspace_routing_rules": matching_lines(lines, [r"\bworkbench\b", r"\borchestrator\b", r"\bmaintenance\b", r"\bquant[- ]pipeline\b", r"\brouting\b", r"\bworkspace\b", r"\brepo root\b"]),
        "testing_rules": matching_lines(lines, [r"\btest", r"\bverification\b", r"\bdry-run\b", r"\bpy_compile\b", r"\bunittest\b", r"\bvalidation\b"]),
    }


def decisions_invariant_inventory(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    return decisions_invariant_inventory_for_text(text)


def non_prunable_size_debt(items: list[Item]) -> dict:
    by_path_items: dict[str, list[Item]] = {}
    for item in items:
        by_path_items.setdefault(item.path, []).append(item)

    records: dict[str, dict[str, object]] = {}
    total_bytes = 0
    for path_rel in sorted(NON_PRUNABLE & set(HOT_DOCS), key=lambda path: path.as_posix()):
        path = WORKBENCH_ROOT / path_rel
        try:
            text = path.read_text(encoding="utf-8")
            exists = True
        except OSError:
            text = ""
            exists = False
        byte_count = len(text.encode("utf-8"))
        sections = section_records_for_text(text)
        bullets = bullet_records_for_text(text)
        largest_section_chars = max((int(section.get("chars") or 0) for section in sections), default=0)
        budget = HOT_CONTEXT_BUDGETS.get(path_rel)
        target = int(budget["target_bytes"]) if isinstance(budget, dict) and budget.get("target_bytes") is not None else None
        hard = int(budget["hard_bytes"]) if isinstance(budget, dict) and budget.get("hard_bytes") is not None else None
        record: dict[str, object] = {
            "path": path_rel.as_posix(),
            "exists": exists,
            "bytes": byte_count,
            "lines": line_count(text),
            "section_count": len(sections),
            "bullet_count": len(bullets),
            "target_bytes": target,
            "hard_bytes": hard,
            "bytes_over_target": max(0, byte_count - target) if target is not None else 0,
            "bytes_over_hard": max(0, byte_count - hard) if hard is not None else 0,
            "pressure_level": pressure_level(byte_count, target, hard),
            "apply_status": apply_status_for_non_prunable(path_rel),
            "largest_sections": top_sized_records(sections),
            "largest_bullets": top_sized_records(bullets),
            "likely_exact_duplicate_bullets": likely_exact_duplicate_bullets(bullets),
            "likely_same_prefix_durable_rules": likely_same_prefix_durable_rules(bullets),
            "audited_item_count": len(by_path_items.get(path_rel.as_posix(), [])),
        }
        if path_rel == DECISIONS_PATH:
            priority = decisions_priority_bucket(byte_count, largest_section_chars)
            record["consolidation_priority_bucket"] = priority
            record["invariant_inventory"] = decisions_invariant_inventory(path)
        records[path_rel.as_posix()] = record
        total_bytes += byte_count

    decisions_record = records.get(DECISIONS_PATH.as_posix(), {})
    decisions_priority = str(decisions_record.get("consolidation_priority_bucket") or "low")
    return {
        "total_bytes": total_bytes,
        "records": records,
        "decisions_consolidation_priority_bucket": decisions_priority,
        "decisions_autonomous_consolidation_required": decisions_priority == "high",
    }


def decisions_consolidation_stamp_dir(stamp: str) -> Path:
    safe_stamp = re.sub(r"[^0-9A-Za-z._-]+", "-", stamp).strip("-_") or "decisions-consolidation"
    return DECISIONS_CONSOLIDATION_ROOT / safe_stamp


def decisions_normalized_rule_text(text: str) -> str:
    stripped = strip_markdown_marker(text)
    stripped = DATE_RE.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip().lower()
    return stripped


def decisions_rule_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_/-]+", decisions_normalized_rule_text(text))


def decisions_rule_prefix_key(text: str) -> str:
    tokens = decisions_rule_tokens(text)
    if len(tokens) < 8:
        return ""
    return " ".join(tokens[:8])


def decisions_rule_short_prefix_key(text: str, *, token_count: int = 4) -> str:
    tokens = decisions_rule_tokens(text)
    if len(tokens) < token_count:
        return ""
    return " ".join(tokens[:token_count])


def decisions_bullet_marker(line: str) -> str:
    match = BULLET_RE.match(line)
    if not match:
        return "- "
    return f"{match.group(1)}{match.group(2)}"


def token_span_end(text: str, token_count: int) -> int:
    end = 0
    for idx, match in enumerate(re.finditer(r"[A-Za-z0-9_/-]+", text), start=1):
        end = match.end()
        if idx >= token_count:
            return end
    return end


def common_token_prefix(rows: list[dict[str, object]]) -> list[str]:
    token_rows = [decisions_rule_tokens(str(row.get("text") or "")) for row in rows]
    if not token_rows:
        return []
    prefix = list(token_rows[0])
    for tokens in token_rows[1:]:
        keep = 0
        for left, right in zip(prefix, tokens):
            if left != right:
                break
            keep += 1
        prefix = prefix[:keep]
        if not prefix:
            break
    return prefix


def strongest_modal_rank(text: str) -> int:
    normalized = decisions_normalized_rule_text(text)
    if "do not" in normalized or "don't" in normalized or "never" in normalized:
        return 0
    if "must" in normalized or "require" in normalized or "required" in normalized:
        return 1
    if "should" in normalized:
        return 2
    if "prefer" in normalized:
        return 3
    if "may" in normalized:
        return 4
    return 5


def decisions_tail_after_prefix(text: str, prefix_token_count: int) -> str:
    stripped = strip_markdown_marker(text)
    end = token_span_end(stripped, prefix_token_count)
    tail = stripped[end:].strip()
    return tail.strip(" ;,.-")


def consolidated_decisions_bullet(rows: list[dict[str, object]]) -> str:
    ordered = sorted(rows, key=lambda row: (strongest_modal_rank(str(row.get("text") or "")), int(row.get("start_line") or 0)))
    base = ordered[0]
    first_source = min(rows, key=lambda row: int(row.get("start_line") or 0))
    marker = decisions_bullet_marker(str(first_source.get("first_line") or first_source.get("text") or "- "))
    prefix = common_token_prefix(rows)
    if len(prefix) < 8:
        return f"{marker}{strip_markdown_marker(str(base.get('text') or '')).strip()}"

    base_text = strip_markdown_marker(str(base.get("text") or "")).strip()
    prefix_end = token_span_end(base_text, len(prefix))
    phrase = base_text[:prefix_end].strip().rstrip(" ;,.-")
    tails: list[str] = []
    seen_tails: set[str] = set()
    for row in sorted(rows, key=lambda candidate: int(candidate.get("start_line") or 0)):
        tail = decisions_tail_after_prefix(str(row.get("text") or ""), len(prefix))
        if not tail:
            continue
        key = decisions_normalized_rule_text(tail)
        if key in seen_tails:
            continue
        seen_tails.add(key)
        tails.append(tail)
    if not tails:
        return f"{marker}{base_text}"
    separator = "; "
    return f"{marker}{phrase} {separator.join(tails)}."


def decisions_bullet_records_for_text(text: str) -> list[dict[str, object]]:
    lines = text.splitlines()
    records: list[dict[str, object]] = []
    for heading, level, start_line, end_line in split_sections(lines):
        for section_heading, _section_level, bullet_start, bullet_end, bullet_text in extract_bullets(lines, heading, level, start_line, end_line):
            normalized = decisions_normalized_rule_text(bullet_text)
            records.append(
                {
                    "heading": section_heading,
                    "section_level": level,
                    "start_line": bullet_start,
                    "end_line": bullet_end,
                    "text": bullet_text,
                    "first_line": lines[bullet_start - 1] if 0 < bullet_start <= len(lines) else bullet_text,
                    "normalized_text": normalized,
                    "similarity_key": decisions_rule_prefix_key(bullet_text),
                    "text_hash": text_hash(bullet_text),
                }
            )
    return records


def source_bullet_ref(row: dict[str, object]) -> dict[str, object]:
    return {
        "heading": row.get("heading"),
        "start_line": row.get("start_line"),
        "end_line": row.get("end_line"),
        "text_hash": row.get("text_hash"),
        "text": row.get("text"),
    }


def build_decisions_consolidation_groups(bullets: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[int, dict[str, object]]]:
    groups: list[dict[str, object]] = []
    operations: dict[int, dict[str, object]] = {}
    removed_lines: set[int] = set()

    by_normalized: dict[str, list[dict[str, object]]] = {}
    for bullet in bullets:
        key = str(bullet.get("normalized_text") or "")
        if key:
            by_normalized.setdefault(key, []).append(bullet)
    for idx, rows in enumerate(
        sorted((rows for rows in by_normalized.values() if len(rows) > 1), key=lambda group: int(group[0].get("start_line") or 0)),
        start=1,
    ):
        rows = sorted(rows, key=lambda row: int(row.get("start_line") or 0))
        keep = rows[0]
        removed = rows[1:]
        for row in removed:
            start = int(row.get("start_line") or 0)
            operations[start] = {
                "type": "remove",
                "start_line": start,
                "end_line": int(row.get("end_line") or start),
                "group_id": f"exact-{idx}",
            }
            removed_lines.add(start)
        groups.append(
            {
                "group_id": f"exact-{idx}",
                "group_type": "exact_duplicate",
                "action": "remove_duplicate_bullets",
                "retained_start_line": keep.get("start_line"),
                "removed_line_refs": [row.get("start_line") for row in removed],
                "source_bullets": [source_bullet_ref(row) for row in rows],
                "consolidated_text": keep.get("text"),
            }
        )

    by_prefix: dict[str, list[dict[str, object]]] = {}
    for bullet in bullets:
        if int(bullet.get("start_line") or 0) in removed_lines:
            continue
        key = str(bullet.get("similarity_key") or "")
        if key:
            by_prefix.setdefault(key, []).append(bullet)
    prefix_candidates = [
        rows
        for rows in by_prefix.values()
        if len(rows) > 1 and len({str(row.get("normalized_text") or "") for row in rows}) > 1
    ]
    for idx, rows in enumerate(sorted(prefix_candidates, key=lambda group: int(group[0].get("start_line") or 0)), start=1):
        rows = sorted(rows, key=lambda row: int(row.get("start_line") or 0))
        replacement_row = rows[0]
        replacement_line = consolidated_decisions_bullet(rows)
        replacement_start = int(replacement_row.get("start_line") or 0)
        replacement_end = int(replacement_row.get("end_line") or replacement_start)
        operations[replacement_start] = {
            "type": "replace",
            "start_line": replacement_start,
            "end_line": replacement_end,
            "replacement_lines": [replacement_line],
            "group_id": f"prefix-{idx}",
        }
        for row in rows[1:]:
            start = int(row.get("start_line") or 0)
            operations[start] = {
                "type": "remove",
                "start_line": start,
                "end_line": int(row.get("end_line") or start),
                "group_id": f"prefix-{idx}",
            }
        groups.append(
            {
                "group_id": f"prefix-{idx}",
                "group_type": "shared_prefix",
                "action": "replace_first_and_remove_group_members",
                "similarity_key": replacement_row.get("similarity_key"),
                "retained_start_line": replacement_start,
                "removed_line_refs": [row.get("start_line") for row in rows[1:]],
                "source_bullets": [source_bullet_ref(row) for row in rows],
                "consolidated_text": replacement_line,
            }
        )

    return groups, operations


def decisions_rejected_candidate_summary(
    bullets: list[dict[str, object]],
    groups: list[dict[str, object]],
    *,
    limit: int = 10,
) -> dict[str, object]:
    grouped_line_refs: set[int] = set()
    for group in groups:
        for row in group.get("source_bullets", []):
            if isinstance(row, dict):
                grouped_line_refs.add(int(row.get("start_line") or 0))

    normalized_groups: dict[str, list[dict[str, object]]] = {}
    for bullet in bullets:
        key = str(bullet.get("normalized_text") or "")
        if key:
            normalized_groups.setdefault(key, []).append(bullet)

    short_prefix_groups: dict[str, list[dict[str, object]]] = {}
    for bullet in bullets:
        key = decisions_rule_short_prefix_key(str(bullet.get("text") or ""))
        if key:
            short_prefix_groups.setdefault(key, []).append(bullet)

    near_matches: list[dict[str, object]] = []
    for prefix, rows in short_prefix_groups.items():
        distinct = {str(row.get("normalized_text") or "") for row in rows if str(row.get("normalized_text") or "")}
        if len(rows) <= 1 or len(distinct) <= 1:
            continue
        if all(int(row.get("start_line") or 0) in grouped_line_refs for row in rows):
            continue
        common_prefix_tokens = common_token_prefix(rows)
        if len(common_prefix_tokens) >= 8:
            reason = "eligible_shared_prefix_not_selected"
        else:
            reason = "shared_prefix_below_safe_threshold"
        near_matches.append(
            {
                "prefix": prefix,
                "reason": reason,
                "common_prefix_token_count": len(common_prefix_tokens),
                "count": len(rows),
                "distinct_count": len(distinct),
                "line_refs": [int(row.get("start_line") or 0) for row in rows[:limit]],
            }
        )
    near_matches.sort(
        key=lambda row: (
            -int(row.get("count") or 0),
            -int(row.get("common_prefix_token_count") or 0),
            str(row.get("prefix") or ""),
        )
    )

    return {
        "bullet_count": len(bullets),
        "accepted_grouped_bullet_count": len(grouped_line_refs),
        "unique_normalized_bullet_count": sum(1 for rows in normalized_groups.values() if len(rows) == 1),
        "exact_duplicate_candidate_count": sum(1 for rows in normalized_groups.values() if len(rows) > 1),
        "near_match_group_count": len(near_matches),
        "near_matches": near_matches[:limit],
    }


def apply_decisions_operations(lines: list[str], operations: dict[int, dict[str, object]]) -> list[str]:
    proposed: list[str] = []
    line = 1
    while line <= len(lines):
        operation = operations.get(line)
        if operation:
            if operation.get("type") == "replace":
                proposed.extend(str(item) for item in operation.get("replacement_lines", []) if str(item).strip())
            line = int(operation.get("end_line") or line) + 1
            continue
        proposed.append(lines[line - 1])
        line += 1
    return proposed


def decisions_unified_diff(before: str, after: str) -> str:
    if before == after:
        return ""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{DECISIONS_PATH.as_posix()}",
            tofile=f"b/{DECISIONS_PATH.as_posix()}",
        )
    )


def build_decisions_consolidation_plan(stamp: str) -> dict:
    source_path = WORKBENCH_ROOT / DECISIONS_PATH
    source_text = source_path.read_text(encoding="utf-8")
    source_lines = source_text.splitlines()
    sections = section_records_for_text(source_text)
    bullets = decisions_bullet_records_for_text(source_text)
    groups, operations = build_decisions_consolidation_groups(bullets)
    rejected_candidate_summary = decisions_rejected_candidate_summary(bullets, groups)
    proposed_lines = apply_decisions_operations(source_lines, operations)
    proposed_text = "\n".join(proposed_lines)
    if source_text.endswith("\n") or proposed_text:
        proposed_text += "\n"
    patch_text = decisions_unified_diff(source_text, proposed_text)
    bytes_before = len(source_text.encode("utf-8"))
    bytes_after = len(proposed_text.encode("utf-8"))
    target = DECISIONS_TARGET_BYTES
    summary = {
        "schema_version": DECISIONS_CONSOLIDATION_SCHEMA_VERSION,
        "stamp": stamp,
        "source_path": DECISIONS_PATH.as_posix(),
        "source_sha256": sha256_text(source_text),
        "source_mutated": False,
        "bytes_before": bytes_before,
        "bytes_after_planned": bytes_after,
        "bytes_delta_planned": bytes_after - bytes_before,
        "target_bytes": target,
        "hard_bytes": DECISIONS_HARD_BYTES,
        "budget_deficit_after_consolidation": max(0, bytes_after - target),
        "section_count": len(sections),
        "bullet_count": len(bullets),
        "consolidation_group_count": len(groups),
        "exact_duplicate_group_count": sum(1 for group in groups if group.get("group_type") == "exact_duplicate"),
        "shared_prefix_group_count": sum(1 for group in groups if group.get("group_type") == "shared_prefix"),
        "removed_bullet_count": sum(1 for operation in operations.values() if operation.get("type") == "remove"),
        "replacement_bullet_count": sum(1 for operation in operations.values() if operation.get("type") == "replace"),
        "touched_paths": [DECISIONS_PATH.as_posix()] if patch_text else [],
        "patch_touches_only_decisions": True,
        "invariant_inventory_before": decisions_invariant_inventory_for_text(source_text),
        "invariant_inventory_after_planned": decisions_invariant_inventory_for_text(proposed_text),
        "rejected_candidate_summary": rejected_candidate_summary,
        "groups": groups,
    }
    return {
        "summary": summary,
        "source_text": source_text,
        "proposed_text": proposed_text,
        "patch_text": patch_text,
        "sections": sections,
        "bullets": bullets,
        "groups": groups,
    }


def render_decisions_consolidation_plan_markdown(plan: dict) -> str:
    summary = plan["summary"]
    groups = plan["groups"]
    rejected = summary.get("rejected_candidate_summary") if isinstance(summary.get("rejected_candidate_summary"), dict) else {}
    near_matches = rejected.get("near_matches") if isinstance(rejected.get("near_matches"), list) else []
    lines = [
        "# Decisions Consolidation Plan",
        "",
        f"- stamp: `{summary['stamp']}`",
        f"- source: `{summary['source_path']}`",
        f"- source sha256: `sha256:{summary['source_sha256']}`",
        f"- bytes before/planned: {summary['bytes_before']} / {summary['bytes_after_planned']} ({summary['bytes_delta_planned']})",
        f"- target bytes: {summary['target_bytes']}",
        f"- budget deficit after consolidation: {summary['budget_deficit_after_consolidation']}",
        f"- consolidation groups: {summary['consolidation_group_count']}",
        f"- exact duplicate groups: {summary['exact_duplicate_group_count']}",
        f"- shared-prefix groups: {summary['shared_prefix_group_count']}",
        f"- source mutated: {str(summary['source_mutated']).lower()}",
        "",
        "## Invariant Inventory",
        "",
        f"- headings before: {summary['invariant_inventory_before'].get('headings_present', [])}",
        f"- headings after planned: {summary['invariant_inventory_after_planned'].get('headings_present', [])}",
        f"- explicit keep markers before/after: {len(summary['invariant_inventory_before'].get('explicit_keep_markers', []))}/{len(summary['invariant_inventory_after_planned'].get('explicit_keep_markers', []))}",
        "",
        "## Consolidation Groups",
        "",
    ]
    if not groups:
        lines.append("- none")
    else:
        for group in groups:
            lines.extend(
                [
                    f"### {group['group_id']} — {group['group_type']}",
                    "",
                    f"- action: `{group['action']}`",
                    f"- retained start line: {group.get('retained_start_line')}",
                    f"- removed line refs: {group.get('removed_line_refs', [])}",
                    f"- consolidated text: `{str(group.get('consolidated_text') or '').strip()[:240]}`",
                    "- source refs: "
                    + ", ".join(
                        f"{item.get('start_line')}-{item.get('end_line')}"
                        for item in group.get("source_bullets", [])
                        if isinstance(item, dict)
                    ),
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Rejected Candidates / Near Matches",
            "",
            f"- accepted grouped bullets: {rejected.get('accepted_grouped_bullet_count', 0)}",
            f"- unique normalized bullets: {rejected.get('unique_normalized_bullet_count', 0)}",
            f"- exact duplicate candidate groups: {rejected.get('exact_duplicate_candidate_count', 0)}",
            f"- near-match groups below/near safe threshold: {rejected.get('near_match_group_count', 0)}",
        ]
    )
    if not near_matches:
        lines.append("- near matches: none")
    else:
        lines.append("- near matches:")
        for item in near_matches[:10]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"  - reason={item.get('reason')} commonPrefixTokens={item.get('common_prefix_token_count')} "
                f"count={item.get('count')} lines={item.get('line_refs', [])} prefix={item.get('prefix')}"
            )
    return "\n".join(lines).rstrip() + "\n"


def write_decisions_consolidation_plan(stamp: str, plan: dict) -> dict:
    output_dir = decisions_consolidation_stamp_dir(stamp)
    summary_path = output_dir / "decisions-consolidation-summary.json"
    input_path = output_dir / "decisions-consolidation-input.json"
    plan_path = output_dir / "decisions-consolidation-plan.md"
    patch_path = output_dir / "decisions-consolidation.patch"
    summary = dict(plan["summary"])
    summary.update(
        {
            "output_dir": str(output_dir),
            "input_path": str(input_path),
            "plan_path": str(plan_path),
            "patch_path": str(patch_path),
            "summary_path": str(summary_path),
        }
    )
    input_payload = {
        "schema_version": DECISIONS_CONSOLIDATION_SCHEMA_VERSION,
        "stamp": stamp,
        "source_path": DECISIONS_PATH.as_posix(),
        "source_sha256": summary["source_sha256"],
        "sections": plan["sections"],
        "bullets": plan["bullets"],
        "invariant_inventory": summary["invariant_inventory_before"],
        "rejected_candidate_summary": summary["rejected_candidate_summary"],
    }
    atomic_write_json(input_path, input_payload)
    atomic_write_text(plan_path, render_decisions_consolidation_plan_markdown(plan))
    atomic_write_text(patch_path, plan["patch_text"])
    atomic_write_json(summary_path, summary)
    return summary


def run_decisions_consolidation_plan(*, stamp: str) -> dict:
    plan = build_decisions_consolidation_plan(stamp)
    return write_decisions_consolidation_plan(stamp, plan)


def decisions_consolidation_archive_path(stamp: str) -> Path:
    safe_stamp = re.sub(r"[^0-9A-Za-z._-]+", "-", stamp).strip("-_") or "decisions-consolidation"
    return DECISIONS_CONSOLIDATION_ARCHIVE_ROOT / safe_stamp / "decisions.before.md"


def decisions_backlog_history_path() -> Path:
    return DECISIONS_CONSOLIDATION_ROOT / "backlog-history.json"


def decisions_backlog_status_json_path() -> Path:
    return DECISIONS_CONSOLIDATION_ROOT / "backlog-status.json"


def decisions_backlog_status_markdown_path() -> Path:
    return DECISIONS_CONSOLIDATION_ROOT / "backlog-status.md"


def decisions_safe_candidate_count(result: dict) -> int:
    return max(0, int(result.get("consolidation_group_count") or 0))


def decisions_consolidation_reason(result: dict) -> str:
    no_op_reason = result.get("no_op_reason")
    if no_op_reason:
        return str(no_op_reason)
    failures = result.get("validation_failures") if isinstance(result.get("validation_failures"), list) else []
    if failures:
        return str(failures[0])
    status = result.get("validation_status")
    return str(status or "unknown")


def decisions_allowed_forward_lanes(result: dict) -> list[str]:
    lanes = ["manual_decisions_consolidation_review"]
    if decisions_safe_candidate_count(result) > 0:
        lanes.insert(0, "safe_deterministic_decisions_shrink")
    lanes.extend(["generic_context_prune_apply_ranges", "state_compaction"])
    return lanes


def decisions_backlog_recommended_action(result: dict) -> str:
    if decisions_safe_candidate_count(result) > 0:
        return "apply_or_stage_safe_deterministic_shrink"
    return "manual_decisions_consolidation_review"


def decisions_blocked_scope(result: dict) -> dict[str, object]:
    return {
        "source_path": str(result.get("source_path") or DECISIONS_PATH.as_posix()),
        "validation_status": str(result.get("validation_status") or "unknown"),
        "reason": decisions_consolidation_reason(result),
        "budget_deficit_after_consolidation": int(result.get("budget_deficit_after_consolidation") or 0),
        "min_shrink_bytes": int(result.get("min_shrink_bytes") or 0),
    }


def load_decisions_backlog_history() -> list[dict]:
    path = decisions_backlog_history_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict) and isinstance(payload.get("history"), list):
        records = payload["history"]
    else:
        return []
    return [record for record in records if isinstance(record, dict)]


def recent_decisions_noop_count(history: list[dict], reason: str) -> int:
    count = 0
    for record in reversed(history):
        if record.get("reason") != reason:
            break
        if record.get("status") != "noop":
            break
        count += 1
    return count


def render_decisions_backlog_status_markdown(status: dict) -> str:
    lines = [
        "# Decisions Consolidation Backlog",
        "",
        f"- status: `{status.get('status')}`",
        f"- reason: `{status.get('reason')}`",
        f"- repeated count: {status.get('repeated_count')}",
        f"- safe candidates: {status.get('safe_candidates')}",
        f"- recommended action: `{status.get('recommended_action')}`",
        "",
        "## Blocked Scope",
        "",
    ]
    blocked_scope = status.get("blocked_scope") if isinstance(status.get("blocked_scope"), dict) else {}
    if not blocked_scope:
        lines.append("- none")
    else:
        for key, value in sorted(blocked_scope.items()):
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Allowed Forward Lanes", ""])
    lanes = status.get("allowed_forward_lanes") if isinstance(status.get("allowed_forward_lanes"), list) else []
    if not lanes:
        lines.append("- none")
    else:
        for lane in lanes:
            lines.append(f"- `{lane}`")
    return "\n".join(lines).rstrip() + "\n"


def write_decisions_backlog_status(status: dict) -> None:
    atomic_write_json(decisions_backlog_status_json_path(), status)
    atomic_write_text(decisions_backlog_status_markdown_path(), render_decisions_backlog_status_markdown(status))


def record_decisions_consolidation_result(result: dict, *, timestamp: str | None = None) -> dict:
    now = timestamp or now_iso()
    validation_status = str(result.get("validation_status") or "unknown")
    status = "noop" if validation_status == "noop" else "applied" if bool(result.get("source_mutated")) else validation_status
    reason = decisions_consolidation_reason(result)
    safe_candidates = decisions_safe_candidate_count(result)
    blocked_scope = decisions_blocked_scope(result)
    allowed_forward_lanes = decisions_allowed_forward_lanes(result)
    record = {
        "timestamp": now,
        "status": status,
        "reason": reason,
        "bytes_before": int(result.get("bytes_before") or 0),
        "bytes_after": int(result.get("bytes_after_planned") or result.get("bytes_after") or 0),
        "bytes_after_planned": int(result.get("bytes_after_planned") or 0),
        "bytes_delta_planned": int(result.get("bytes_delta_planned") or 0),
        "safe_candidates": safe_candidates,
        "blocked_scope": blocked_scope,
        "allowed_forward_lanes": allowed_forward_lanes,
    }
    history = (load_decisions_backlog_history() + [record])[-DECISIONS_BACKLOG_HISTORY_LIMIT:]
    atomic_write_json(
        decisions_backlog_history_path(),
        {
            "schema_version": DECISIONS_BACKLOG_SCHEMA_VERSION,
            "updated_at": now,
            "history": history,
        },
    )
    repeated_count = recent_decisions_noop_count(history, "insufficient_safe_decisions_shrink")
    backlog_status = "monitoring"
    status_json_path = None
    status_markdown_path = None
    recommended_action = decisions_backlog_recommended_action(result)
    if validation_status == "passed" and bool(result.get("source_mutated")):
        backlog_status = "resolved"
        status_payload = {
            "schema_version": DECISIONS_BACKLOG_SCHEMA_VERSION,
            "updated_at": now,
            "status": backlog_status,
            "reason": "safe_decisions_consolidation_applied",
            "repeated_count": repeated_count,
            "safe_candidates": safe_candidates,
            "blocked_scope": blocked_scope,
            "allowed_forward_lanes": allowed_forward_lanes,
            "recommended_action": "continue_monitoring",
            "history_path": str(decisions_backlog_history_path()),
        }
        write_decisions_backlog_status(status_payload)
        status_json_path = str(decisions_backlog_status_json_path())
        status_markdown_path = str(decisions_backlog_status_markdown_path())
    elif reason == "insufficient_safe_decisions_shrink" and repeated_count >= DECISIONS_BACKLOG_REPEAT_THRESHOLD:
        backlog_status = "review_required"
        status_payload = {
            "schema_version": DECISIONS_BACKLOG_SCHEMA_VERSION,
            "updated_at": now,
            "status": backlog_status,
            "reason": "repeated_insufficient_safe_shrink",
            "repeated_count": repeated_count,
            "safe_candidates": safe_candidates,
            "blocked_scope": blocked_scope,
            "allowed_forward_lanes": allowed_forward_lanes,
            "recommended_action": recommended_action,
            "history_path": str(decisions_backlog_history_path()),
        }
        write_decisions_backlog_status(status_payload)
        status_json_path = str(decisions_backlog_status_json_path())
        status_markdown_path = str(decisions_backlog_status_markdown_path())
    return {
        "schema_version": DECISIONS_BACKLOG_SCHEMA_VERSION,
        "updated_at": now,
        "status": backlog_status,
        "reason": "repeated_insufficient_safe_shrink" if backlog_status == "review_required" else reason,
        "repeated_count": repeated_count,
        "safe_candidates": safe_candidates,
        "blocked_scope": blocked_scope,
        "allowed_forward_lanes": allowed_forward_lanes,
        "recommended_action": recommended_action if backlog_status != "resolved" else "continue_monitoring",
        "history_path": str(decisions_backlog_history_path()),
        "status_path": status_json_path,
        "markdown_path": status_markdown_path,
    }


def normalized_inventory_lines(records: object) -> set[str]:
    if not isinstance(records, list):
        return set()
    values: set[str] = set()
    for record in records:
        if isinstance(record, dict):
            text = str(record.get("text") or "")
        else:
            text = str(record)
        normalized = decisions_normalized_rule_text(text)
        if normalized:
            values.add(normalized)
    return values


def source_group_members(plan: dict) -> set[str]:
    members: set[str] = set()
    for group in plan.get("groups", []):
        if not isinstance(group, dict):
            continue
        for row in group.get("source_bullets", []):
            if not isinstance(row, dict):
                continue
            normalized = decisions_normalized_rule_text(str(row.get("text") or ""))
            if normalized:
                members.add(normalized)
    return members


def after_bullet_inventory(plan: dict) -> set[str]:
    return {
        decisions_normalized_rule_text(str(row.get("text") or ""))
        for row in decisions_bullet_records_for_text(str(plan.get("proposed_text") or ""))
        if decisions_normalized_rule_text(str(row.get("text") or ""))
    }


def grouped_rule_preserved_by_consolidation(normalized_before: str, plan: dict) -> bool:
    source_tokens = set(decisions_rule_tokens(normalized_before))
    if not source_tokens:
        return True
    for group in plan.get("groups", []):
        if not isinstance(group, dict):
            continue
        rows = group.get("source_bullets", [])
        row_texts = [
            decisions_normalized_rule_text(str(row.get("text") or ""))
            for row in rows
            if isinstance(row, dict)
        ]
        if normalized_before not in row_texts:
            continue
        consolidated = decisions_normalized_rule_text(str(group.get("consolidated_text") or ""))
        if group.get("group_type") == "exact_duplicate":
            return normalized_before == consolidated
        consolidated_tokens = set(decisions_rule_tokens(consolidated))
        return source_tokens.issubset(consolidated_tokens)
    return False


def validate_decisions_apply_plan(plan: dict, *, min_shrink_bytes: int) -> tuple[str, list[str]]:
    failures: list[str] = []
    summary = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    source_path = WORKBENCH_ROOT / DECISIONS_PATH
    current_text = source_path.read_text(encoding="utf-8")
    current_hash = sha256_text(current_text)
    planned_hash = str(summary.get("source_sha256") or "")
    if current_hash != planned_hash:
        failures.append("source_hash_mismatch")
    touched_paths = summary.get("touched_paths")
    touched = touched_paths if isinstance(touched_paths, list) else []
    if any(str(path) != DECISIONS_PATH.as_posix() for path in touched):
        failures.append("patch_touches_other_files")
    if not bool(summary.get("patch_touches_only_decisions", False)):
        failures.append("patch_touches_other_files")

    before_inventory = summary.get("invariant_inventory_before") if isinstance(summary.get("invariant_inventory_before"), dict) else {}
    after_inventory = summary.get("invariant_inventory_after_planned") if isinstance(summary.get("invariant_inventory_after_planned"), dict) else {}
    before_headings = [str(item) for item in before_inventory.get("headings_present", [])] if isinstance(before_inventory.get("headings_present"), list) else []
    after_headings = [str(item) for item in after_inventory.get("headings_present", [])] if isinstance(after_inventory.get("headings_present"), list) else []
    missing_headings = [heading for heading in before_headings if heading not in after_headings]
    if missing_headings:
        failures.append("required_headings_missing:" + ",".join(missing_headings[:5]))

    before_keep = normalized_inventory_lines(before_inventory.get("explicit_keep_markers"))
    after_keep = normalized_inventory_lines(after_inventory.get("explicit_keep_markers"))
    if not before_keep.issubset(after_keep):
        failures.append("explicit_keep_markers_missing")

    for key in ["safety_boundary_phrases", "file_role_rules", "workspace_routing_rules", "testing_rules"]:
        before_values = normalized_inventory_lines(before_inventory.get(key))
        after_values = normalized_inventory_lines(after_inventory.get(key))
        if not before_values.issubset(after_values | source_group_members(plan)):
            failures.append(f"invariant_inventory_missing:{key}")

    before_bullets = {
        decisions_normalized_rule_text(str(row.get("text") or ""))
        for row in decisions_bullet_records_for_text(str(plan.get("source_text") or ""))
        if decisions_normalized_rule_text(str(row.get("text") or ""))
    }
    after_bullets = after_bullet_inventory(plan)
    for normalized in before_bullets:
        if normalized in after_bullets:
            continue
        if not grouped_rule_preserved_by_consolidation(normalized, plan):
            failures.append("durable_rule_clause_missing")
            break

    if failures:
        return "validation_failed", failures

    bytes_before = int(summary.get("bytes_before") or 0)
    bytes_delta = int(summary.get("bytes_delta_planned") or 0)
    if bytes_before > DECISIONS_TARGET_BYTES and abs(bytes_delta) < min_shrink_bytes:
        return "noop", ["insufficient_safe_decisions_shrink"]
    if not str(plan.get("patch_text") or ""):
        reason = "already_under_target_no_changes" if bytes_before <= DECISIONS_TARGET_BYTES else "insufficient_safe_decisions_shrink"
        return "noop", [reason]
    return "passed", []


def run_decisions_consolidation_apply(*, stamp: str, min_shrink_bytes: int = 1000) -> dict:
    min_shrink_bytes = max(0, int(min_shrink_bytes))
    plan = build_decisions_consolidation_plan(stamp)
    summary = write_decisions_consolidation_plan(stamp, plan)
    validation_status, validation_failures = validate_decisions_apply_plan(plan, min_shrink_bytes=min_shrink_bytes)
    output_dir = decisions_consolidation_stamp_dir(stamp)
    apply_manifest_path = output_dir / "decisions-consolidation-apply-manifest.json"
    archive_path = decisions_consolidation_archive_path(stamp)
    manifest: dict[str, object] = {
        "schema_version": "workbench-decisions-consolidation-apply/v1",
        "stamp": stamp,
        "source_path": DECISIONS_PATH.as_posix(),
        "source_sha256": summary.get("source_sha256"),
        "plan_summary_path": summary.get("summary_path"),
        "plan_path": summary.get("plan_path"),
        "patch_path": summary.get("patch_path"),
        "apply_manifest_path": str(apply_manifest_path),
        "archive_path": None,
        "source_mutated": False,
        "validation_status": validation_status,
        "validation_failures": validation_failures,
        "no_op_reason": validation_failures[0] if validation_status == "noop" and validation_failures else None,
        "min_shrink_bytes": min_shrink_bytes,
        "bytes_before": summary.get("bytes_before"),
        "bytes_after_planned": summary.get("bytes_after_planned"),
        "bytes_delta_planned": summary.get("bytes_delta_planned"),
        "budget_deficit_after_consolidation": summary.get("budget_deficit_after_consolidation"),
        "consolidation_group_count": summary.get("consolidation_group_count"),
        "exact_duplicate_group_count": summary.get("exact_duplicate_group_count"),
        "shared_prefix_group_count": summary.get("shared_prefix_group_count"),
    }
    if validation_status == "passed":
        source_path = WORKBENCH_ROOT / DECISIONS_PATH
        atomic_write_text(archive_path, str(plan["source_text"]))
        atomic_write_text(source_path, str(plan["proposed_text"]))
        manifest["source_mutated"] = True
        manifest["archive_path"] = str(archive_path)
        manifest["source_sha256_after"] = sha256_text(str(plan["proposed_text"]))
    manifest["decisions_backlog"] = record_decisions_consolidation_result(manifest)
    atomic_write_json(apply_manifest_path, manifest)
    return manifest


def projected_apply_bytes(path_rel: str, ranges: list[tuple[int, int, str]]) -> dict[str, int] | None:
    src = WORKBENCH_ROOT / path_rel
    if not src.exists() or not src.is_file():
        return None
    original_text = src.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    keep: list[str] = []
    sorted_ranges = sorted(ranges)
    idx = 1
    range_iter = iter(sorted_ranges)
    current = next(range_iter, None)
    while idx <= len(lines):
        if current and current[0] <= idx <= current[1]:
            idx = current[1] + 1
            current = next(range_iter, None)
            continue
        keep.append(lines[idx - 1])
        idx += 1
    while keep and keep[-1] == "":
        keep.pop()
    projected_text = "\n".join(keep) + "\n"
    before = len(original_text.encode("utf-8"))
    after = len(projected_text.encode("utf-8"))
    return {
        "projected_bytes_before_apply": before,
        "projected_bytes_after_apply": after,
        "projected_bytes_delta_apply": after - before,
    }


def folder_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def build_apply_projection_file_map(ranges_by_path: dict[str, list[tuple[int, int, str]]]) -> dict[str, dict[str, int]]:
    projections: dict[str, dict[str, int]] = {}
    for path, ranges in ranges_by_path.items():
        if not ranges:
            continue
        projection = projected_apply_bytes(path, ranges)
        if projection is not None:
            projections[path] = projection
    return projections


def build_hot_context_budget_summary(items: list[Item]) -> dict:
    apply_plan = build_apply_plan(items)
    ranges_by_path = apply_plan["ranges_by_path"]
    non_prunable_debt = non_prunable_size_debt(items)
    hot_docs: dict[str, dict[str, object]] = {}
    for path_rel in HOT_DOCS:
        budget = HOT_CONTEXT_BUDGETS.get(path_rel)
        record = budget_record(path_rel, budget, default_mode="diagnostic_unbudgeted")
        ranges = ranges_by_path.get(str(path_rel), [])
        projection = projected_apply_bytes(str(path_rel), ranges) if ranges else None
        if projection:
            record.update(projection)
            projected_after = projection["projected_bytes_after_apply"]
            target = record.get("target_bytes")
            hard = record.get("hard_bytes")
            target_int = int(target) if target is not None else None
            hard_int = int(hard) if hard is not None else None
            record["projected_pressure_level_after_apply"] = pressure_level(projected_after, target_int, hard_int)
        non_prunable_record = non_prunable_debt.get("records", {}).get(path_rel.as_posix()) if isinstance(non_prunable_debt.get("records"), dict) else None
        if isinstance(non_prunable_record, dict) and path_rel == DECISIONS_PATH:
            record["consolidation_priority_bucket"] = non_prunable_record.get("consolidation_priority_bucket")
            record["decisions_autonomous_consolidation_required"] = non_prunable_record.get("consolidation_priority_bucket") == "high"
        hot_docs[str(path_rel)] = record

    state_files: dict[str, dict[str, object]] = {}
    for path_rel, budget in STATE_FILE_BUDGETS.items():
        state_files[str(path_rel)] = budget_record(path_rel, budget, default_mode="state_json_compaction")

    active_headings = active_live_heading_budget_records()
    hot_markdown_bytes_total = sum(int(record["bytes"]) for record in hot_docs.values())
    state_json_bytes_total = sum(int(record["bytes"]) for record in state_files.values())
    hot_markdown_budget_success = all(
        record["pressure_level"] == "none"
        for path, record in hot_docs.items()
        if Path(path) in HOT_CONTEXT_BUDGETS
    ) and all(record["pressure_level"] == "none" for record in active_headings.values())

    project_spine_budget_pressure = {
        key: apply_plan["summary"].get(key)
        for key in [
            "project_spine_budget_target_bytes",
            "project_spine_budget_projected_after_bytes",
            "project_spine_budget_deficit_after_planning",
            "project_spine_budget_escalated_candidate_count",
            "project_spine_budget_escalated_bytes",
            "project_spine_budget_blockers",
        ]
    }
    summary = {
        "hot_docs": hot_docs,
        "state_files": state_files,
        "active_live_headings": active_headings,
        "project_spine_budget_pressure": project_spine_budget_pressure,
        "apply_projection": {
            "candidate_summary": apply_plan["summary"],
            "range_records_count": len(apply_plan["range_records"]),
            "files": build_apply_projection_file_map(ranges_by_path),
        },
        "hot_markdown_bytes_total": hot_markdown_bytes_total,
        "context_folder_bytes_total": folder_bytes(CONTEXT_ROOT),
        "state_json_bytes_total": state_json_bytes_total,
        "hot_markdown_budget_success": hot_markdown_budget_success,
        "state_json_budget_success": all(record["pressure_level"] == "none" for record in state_files.values()),
        "non_prunable_size_debt": non_prunable_debt,
        "decisions_autonomous_consolidation_required": bool(non_prunable_debt.get("decisions_autonomous_consolidation_required")),
    }
    debt = build_protected_budget_debt(items, summary)
    summary["protected_budget_debt"] = debt
    summary["protected_budget_debt_bytes_total"] = debt["protected_budget_debt_bytes_total"]
    summary["protected_budget_debt_by_category"] = debt["protected_budget_debt_by_category"]
    summary["protected_budget_debt_routes"] = debt["protected_budget_debt_routes"]
    summary["budget_success"] = bool(
        summary["hot_markdown_budget_success"]
        and summary["state_json_budget_success"]
        and debt["protected_budget_debt_bytes_total"] == 0
    )
    return summary


def item_span_text(item: Item) -> str:
    path = WORKBENCH_ROOT / item.path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[item.start_line - 1 : item.end_line])


def span_bytes(path_rel: str, start_line: int | None, end_line: int | None) -> int:
    if start_line is None or end_line is None:
        return 0
    path = WORKBENCH_ROOT / path_rel
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return len(("\n".join(lines[start_line - 1 : end_line]) + "\n").encode("utf-8"))


def add_protected_debt_record(
    debt: dict[str, object],
    *,
    path: str,
    heading: str,
    start_line: int | None,
    end_line: int | None,
    protected_bytes: int,
    text_hash_value: str | None,
    reason: str,
    category: str,
    evidence_class: str,
    route: str,
) -> None:
    if protected_bytes <= 0:
        return
    by_category = debt["protected_budget_debt_by_category"]
    by_routes = debt["protected_budget_debt_routes"]
    assert isinstance(by_category, dict)
    assert isinstance(by_routes, dict)
    debt["protected_budget_debt_bytes_total"] = int(debt["protected_budget_debt_bytes_total"]) + protected_bytes
    by_category[category] = int(by_category.get(category, 0)) + protected_bytes
    by_routes[route] = int(by_routes.get(route, 0)) + protected_bytes
    spans = debt["top_protected_spans"]
    assert isinstance(spans, list)
    record = {
        "path": path,
        "heading": heading,
        "start_line": start_line,
        "end_line": end_line,
        "char_count": protected_bytes,
        "text_hash": text_hash_value,
        "reason": reason,
        "category": category,
        "evidence_class": evidence_class,
        "route": route,
    }
    spans.append(record)
    spans.sort(key=lambda row: (-int(row.get("char_count", 0)), str(row.get("path", "")), int(row.get("start_line") or 0)))
    del spans[PROTECTED_BUDGET_DEBT_RECORD_LIMIT:]


def add_stale_strong_evidence_record(debt: dict[str, object], item: Item, protected_bytes: int) -> None:
    if protected_bytes <= 0:
        return
    debt["stale_strong_evidence_overflow_bytes_total"] = int(debt["stale_strong_evidence_overflow_bytes_total"]) + protected_bytes
    records = debt["stale_strong_evidence_overflow_spans"]
    assert isinstance(records, list)
    records.append(
        {
            "path": item.path,
            "heading": item.section_heading,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "char_count": protected_bytes,
            "text_hash": item.text_hash,
            "reason": item.reason,
            "evidence_class": "stale_strong_evidence_without_unresolved_marker",
            "route": "phase_3_4_budget_pressure",
        }
    )
    records.sort(key=lambda row: (-int(row.get("char_count", 0)), str(row.get("path", "")), int(row.get("start_line") or 0)))
    del records[PROTECTED_BUDGET_DEBT_RECORD_LIMIT:]


def is_span_covered(covered: dict[str, list[tuple[int, int]]], path: str, start: int | None, end: int | None) -> bool:
    if start is None or end is None:
        return False
    return any(overlap(start, end, existing_start, existing_end) for existing_start, existing_end in covered.get(path, []))


def mark_span_covered(covered: dict[str, list[tuple[int, int]]], path: str, start: int | None, end: int | None) -> None:
    if start is None or end is None:
        return
    covered.setdefault(path, []).append((start, end))


def protected_category_for_item(item: Item, budget_summary: dict) -> tuple[str, str, str] | None:
    path_rel = Path(item.path)
    text = item_span_text(item)
    if KEEP_COMMENT_RE.search(text):
        return "explicit_keep_marker", "autonomous_keep_marker_compaction", "explicit_keep_marker"
    if is_project_spine(path_rel) and item.pinned and is_project_spine_pinned_heading(item.section_heading):
        return "stable_project_spine_anchor", "autonomous_anchor_summary", "stable_project_spine_anchor"
    if item.reason.startswith("recalled:") or item.reason == "high-recall-protected":
        if item.age_days < DEFAULT_RECENT_GRACE_DAYS or item.pinned or UNRESOLVED_MARKER_RE.search(text):
            return "strong_targeted_recent_or_unresolved", "defer_recent_content", "strong_targeted_recent_or_unresolved"
        return None
    if item.reason == "recently-edited" or item.age_days < DEFAULT_RECENT_GRACE_DAYS:
        return "recent_zero_to_three_day_content", "defer_recent_content", "recent_zero_to_three_day_content"
    active_headings = budget_summary.get("active_live_headings") if isinstance(budget_summary.get("active_live_headings"), dict) else {}
    heading_record = active_headings.get(item.section_heading) if isinstance(active_headings, dict) else None
    if path_rel == Path("context/active.md") and isinstance(heading_record, dict) and heading_record.get("pressure_level") != "none":
        return "active_live_heading_requires_summary", "auto_summarize_existing_active_live_heading_path", "active_live_heading_pressure"
    return None


def build_protected_budget_debt(items: list[Item], budget_summary: dict) -> dict:
    debt: dict[str, object] = {
        "protected_budget_debt_bytes_total": 0,
        "protected_budget_debt_by_category": {},
        "protected_budget_debt_routes": {},
        "top_protected_spans": [],
        "stale_strong_evidence_overflow_bytes_total": 0,
        "stale_strong_evidence_overflow_spans": [],
        "budget_success": bool(budget_summary.get("hot_markdown_budget_success") and budget_summary.get("state_json_budget_success")),
    }
    covered: dict[str, list[tuple[int, int]]] = {}
    hot_docs = budget_summary.get("hot_docs") if isinstance(budget_summary.get("hot_docs"), dict) else {}
    over_budget_hot_docs = {
        path
        for path, record in hot_docs.items()
        if isinstance(record, dict) and record.get("pressure_level") in {"target", "hard"}
    }

    active_headings = budget_summary.get("active_live_headings") if isinstance(budget_summary.get("active_live_headings"), dict) else {}
    for heading, record in active_headings.items():
        if not isinstance(record, dict) or record.get("pressure_level") == "none":
            continue
        path = str(record.get("path") or "context/active.md")
        protected_bytes = span_bytes(path, record.get("start_line"), record.get("end_line")) or int(record.get("bytes") or 0)
        add_protected_debt_record(
            debt,
            path=path,
            heading=str(heading),
            start_line=record.get("start_line") if isinstance(record.get("start_line"), int) else None,
            end_line=record.get("end_line") if isinstance(record.get("end_line"), int) else None,
            protected_bytes=protected_bytes,
            text_hash_value=None,
            reason="active-live-heading-over-budget",
            category="active_live_heading_requires_summary",
            evidence_class="active_live_heading_pressure",
            route="auto_summarize_existing_active_live_heading_path",
        )
        mark_span_covered(covered, path, record.get("start_line") if isinstance(record.get("start_line"), int) else None, record.get("end_line") if isinstance(record.get("end_line"), int) else None)

    if "context/decisions.md" in over_budget_hot_docs:
        record = hot_docs["context/decisions.md"]
        if isinstance(record, dict):
            add_protected_debt_record(
                debt,
                path="context/decisions.md",
                heading="context/decisions.md",
                start_line=1,
                end_line=int(record.get("lines") or 0) or None,
                protected_bytes=int(record.get("bytes") or 0),
                text_hash_value=None,
                reason="decisions-doc-over-budget",
                category="decisions_autonomous_consolidation",
                evidence_class="decisions_autonomous_consolidation",
                route="autonomous_decisions_consolidation_patch",
            )
            if int(record.get("lines") or 0):
                mark_span_covered(covered, "context/decisions.md", 1, int(record.get("lines") or 0))

    for item in sorted(items, key=lambda candidate: (candidate.path, candidate.start_line, -(candidate.end_line - candidate.start_line))):
        if item.path not in over_budget_hot_docs:
            continue
        if item.classification != "keep":
            continue
        if is_span_covered(covered, item.path, item.start_line, item.end_line):
            continue
        item_text = item_span_text(item)
        protected_bytes = len((item_text + ("\n" if item_text else "")).encode("utf-8")) or item.char_count
        category = protected_category_for_item(item, budget_summary)
        if category is None:
            if item.reason.startswith("recalled:") or item.reason == "high-recall-protected":
                add_stale_strong_evidence_record(debt, item, protected_bytes)
            continue
        category_name, route, evidence_class = category
        add_protected_debt_record(
            debt,
            path=item.path,
            heading=item.section_heading,
            start_line=item.start_line,
            end_line=item.end_line,
            protected_bytes=protected_bytes,
            text_hash_value=item.text_hash,
            reason=item.reason,
            category=category_name,
            evidence_class=evidence_class,
            route=route,
        )
        mark_span_covered(covered, item.path, item.start_line, item.end_line)

    state_files = budget_summary.get("state_files") if isinstance(budget_summary.get("state_files"), dict) else {}
    for path, record in state_files.items():
        if not isinstance(record, dict) or record.get("pressure_level") not in {"target", "hard"}:
            continue
        add_protected_debt_record(
            debt,
            path=str(path),
            heading=str(path),
            start_line=1,
            end_line=int(record.get("lines") or 0) or None,
            protected_bytes=int(record.get("bytes") or 0),
            text_hash_value=None,
            reason="state-history-over-budget",
            category="state_retained_history",
            evidence_class="state_retained_history",
            route="state_compaction_blocker",
        )

    debt["budget_success"] = bool(
        budget_summary.get("hot_markdown_budget_success")
        and budget_summary.get("state_json_budget_success")
        and int(debt["protected_budget_debt_bytes_total"]) == 0
    )
    return debt


def render_protected_budget_debt(debt: dict) -> list[str]:
    lines = [
        "## Protected budget debt",
        "",
        f"- protected debt bytes total: {debt.get('protected_budget_debt_bytes_total', 0)}",
        f"- budget success: {str(bool(debt.get('budget_success'))).lower()}",
        f"- protected debt by category: {debt.get('protected_budget_debt_by_category', {})}",
        f"- protected debt routes: {debt.get('protected_budget_debt_routes', {})}",
        f"- stale strong evidence overflow bytes: {debt.get('stale_strong_evidence_overflow_bytes_total', 0)}",
        "",
        "### Top protected spans",
        "",
    ]
    spans = debt.get("top_protected_spans") if isinstance(debt.get("top_protected_spans"), list) else []
    if not spans:
        lines.append("- none")
    else:
        for span in spans:
            if not isinstance(span, dict):
                continue
            lines.append(
                f"- `{span.get('path')}` lines {span.get('start_line')}-{span.get('end_line')} "
                f"under **{span.get('heading')}** — category={span.get('category')} "
                f"route={span.get('route')} reason={span.get('reason')} chars={span.get('char_count')}"
            )
    stale = debt.get("stale_strong_evidence_overflow_spans") if isinstance(debt.get("stale_strong_evidence_overflow_spans"), list) else []
    lines.extend(["", "### Stale strong evidence overflow", ""])
    if not stale:
        lines.append("- none")
    else:
        for span in stale:
            if not isinstance(span, dict):
                continue
            lines.append(
                f"- `{span.get('path')}` lines {span.get('start_line')}-{span.get('end_line')} "
                f"under **{span.get('heading')}** — route={span.get('route')} reason={span.get('reason')} chars={span.get('char_count')}"
            )
    lines.append("")
    return lines


def render_non_prunable_size_debt(debt: dict) -> list[str]:
    lines = [
        "## Non-prunable size debt",
        "",
        f"- total bytes: {debt.get('total_bytes', 0)}",
        f"- decisions autonomous consolidation required: {str(bool(debt.get('decisions_autonomous_consolidation_required'))).lower()}",
        f"- decisions consolidation priority: {debt.get('decisions_consolidation_priority_bucket', 'low')}",
        "",
    ]
    records = debt.get("records") if isinstance(debt.get("records"), dict) else {}
    for path in sorted(records):
        record = records[path]
        if not isinstance(record, dict):
            continue
        lines.append(
            f"### `{path}`"
        )
        lines.append("")
        lines.append(
            f"- bytes={record.get('bytes', 0)} lines={record.get('lines', 0)} "
            f"sections={record.get('section_count', 0)} bullets={record.get('bullet_count', 0)} "
            f"pressure={record.get('pressure_level')} applyStatus={record.get('apply_status')}"
        )
        if path == DECISIONS_PATH.as_posix():
            lines.append(f"- consolidation priority: {record.get('consolidation_priority_bucket', 'low')}")
            inventory = record.get("invariant_inventory") if isinstance(record.get("invariant_inventory"), dict) else {}
            lines.append(f"- headings present: {inventory.get('headings_present', [])}")
            lines.append(f"- explicit keep markers: {len(inventory.get('explicit_keep_markers', []) if isinstance(inventory.get('explicit_keep_markers'), list) else [])}")
            lines.append(f"- safety/boundary phrase matches: {len(inventory.get('safety_boundary_phrases', []) if isinstance(inventory.get('safety_boundary_phrases'), list) else [])}")
            lines.append(f"- file-role rule matches: {len(inventory.get('file_role_rules', []) if isinstance(inventory.get('file_role_rules'), list) else [])}")
            lines.append(f"- workspace/routing rule matches: {len(inventory.get('workspace_routing_rules', []) if isinstance(inventory.get('workspace_routing_rules'), list) else [])}")
            lines.append(f"- testing rule matches: {len(inventory.get('testing_rules', []) if isinstance(inventory.get('testing_rules'), list) else [])}")
        largest_sections = record.get("largest_sections") if isinstance(record.get("largest_sections"), list) else []
        lines.append("- largest sections:")
        if largest_sections:
            for section in largest_sections[:10]:
                if not isinstance(section, dict):
                    continue
                lines.append(
                    f"  - lines {section.get('start_line')}-{section.get('end_line')} "
                    f"heading={section.get('heading')} bytes={section.get('bytes', 0)}"
                )
        else:
            lines.append("  - none")
        largest_bullets = record.get("largest_bullets") if isinstance(record.get("largest_bullets"), list) else []
        lines.append("- largest bullets:")
        if largest_bullets:
            for bullet in largest_bullets[:10]:
                if not isinstance(bullet, dict):
                    continue
                lines.append(
                    f"  - lines {bullet.get('start_line')}-{bullet.get('end_line')} "
                    f"heading={bullet.get('heading')} bytes={bullet.get('bytes', 0)}"
                )
        else:
            lines.append("  - none")
        duplicates = record.get("likely_exact_duplicate_bullets") if isinstance(record.get("likely_exact_duplicate_bullets"), list) else []
        lines.append("- likely exact duplicate bullets:")
        if duplicates:
            for duplicate in duplicates[:10]:
                if not isinstance(duplicate, dict):
                    continue
                lines.append(
                    f"  - count={duplicate.get('count', 0)} firstLine={duplicate.get('first_start_line')} "
                    f"text={duplicate.get('text_prefix')}"
                )
        else:
            lines.append("  - none")
        prefixes = record.get("likely_same_prefix_durable_rules") if isinstance(record.get("likely_same_prefix_durable_rules"), list) else []
        lines.append("- likely same-prefix durable rules:")
        if prefixes:
            for prefix in prefixes[:10]:
                if not isinstance(prefix, dict):
                    continue
                lines.append(
                    f"  - count={prefix.get('count', 0)} distinct={prefix.get('distinct_count', 0)} "
                    f"prefix={prefix.get('prefix')}"
                )
        else:
            lines.append("  - none")
        lines.append("")
    return lines


def render_hot_context_budget_summary(summary: dict) -> list[str]:
    lines = [
        "## Hot context budget pressure",
        "",
        f"- hot markdown bytes total: {summary.get('hot_markdown_bytes_total', 0)}",
        f"- context folder bytes total: {summary.get('context_folder_bytes_total', 0)}",
        f"- state JSON bytes total: {summary.get('state_json_bytes_total', 0)}",
        f"- hot markdown budget success: {str(bool(summary.get('hot_markdown_budget_success'))).lower()}",
        "",
        "### Hot markdown files",
        "",
    ]
    hot_docs = summary.get("hot_docs") if isinstance(summary.get("hot_docs"), dict) else {}
    for path in sorted(hot_docs):
        record = hot_docs[path]
        if not isinstance(record, dict):
            continue
        target = record.get("target_bytes") if record.get("target_bytes") is not None else "none"
        hard = record.get("hard_bytes") if record.get("hard_bytes") is not None else "none"
        projected = ""
        if record.get("projected_bytes_after_apply") is not None:
            projected = f", projectedAfterApply={record.get('projected_bytes_after_apply')}"
        lines.append(
            f"- `{path}`: bytes={record.get('bytes', 0)} lines={record.get('lines', 0)} "
            f"target={target} hard={hard} pressure={record.get('pressure_level')} "
            f"mode={record.get('enforcement_mode')} overTarget={record.get('bytes_over_target', 0)} "
            f"overHard={record.get('bytes_over_hard', 0)}{projected}"
        )
    project_spine_pressure = summary.get("project_spine_budget_pressure") if isinstance(summary.get("project_spine_budget_pressure"), dict) else {}
    lines.extend(["", "### Project-spine budget closure", ""])
    lines.append(
        f"- target={project_spine_pressure.get('project_spine_budget_target_bytes', 0)} "
        f"projectedAfter={project_spine_pressure.get('project_spine_budget_projected_after_bytes', 0)} "
        f"deficit={project_spine_pressure.get('project_spine_budget_deficit_after_planning', 0)} "
        f"escalatedCandidates={project_spine_pressure.get('project_spine_budget_escalated_candidate_count', 0)} "
        f"escalatedBytes={project_spine_pressure.get('project_spine_budget_escalated_bytes', 0)}"
    )
    blockers = project_spine_pressure.get("project_spine_budget_blockers") if isinstance(project_spine_pressure.get("project_spine_budget_blockers"), list) else []
    if blockers:
        lines.append("- blockers:")
        for blocker in blockers[:PROJECT_SPINE_BUDGET_BLOCKER_LIMIT]:
            if not isinstance(blocker, dict):
                continue
            lines.append(
                f"  - reason={blocker.get('reason')} route={blocker.get('route')} "
                f"path={blocker.get('path')} lines={blocker.get('start_line')}-{blocker.get('end_line')} "
                f"heading={blocker.get('section_heading')} chars={blocker.get('char_count')}"
            )
    else:
        lines.append("- blockers: none")
    lines.extend(["", "### Active live-heading budgets", ""])
    active_headings = summary.get("active_live_headings") if isinstance(summary.get("active_live_headings"), dict) else {}
    for heading in sorted(active_headings):
        record = active_headings[heading]
        if not isinstance(record, dict):
            continue
        lines.append(
            f"- `{heading}`: bytes={record.get('bytes', 0)} lines={record.get('lines', 0)} "
            f"target={record.get('target_bytes')} hard={record.get('hard_bytes')} "
            f"pressure={record.get('pressure_level')} mode={record.get('enforcement_mode')} "
            f"overTarget={record.get('bytes_over_target', 0)} overHard={record.get('bytes_over_hard', 0)}"
        )
    lines.extend(["", "### State JSON files", ""])
    state_files = summary.get("state_files") if isinstance(summary.get("state_files"), dict) else {}
    for path in sorted(state_files):
        record = state_files[path]
        if not isinstance(record, dict):
            continue
        lines.append(
            f"- `{path}`: bytes={record.get('bytes', 0)} lines={record.get('lines', 0)} "
            f"target={record.get('target_bytes')} hard={record.get('hard_bytes')} "
            f"pressure={record.get('pressure_level')} mode={record.get('enforcement_mode')} "
            f"overTarget={record.get('bytes_over_target', 0)} overHard={record.get('bytes_over_hard', 0)}"
        )
    lines.append("")
    return lines


def apply_plan_no_op_reason(summary: dict[str, object]) -> str:
    candidate_count = int(summary.get("candidate_count_total", 0))
    allowlisted_count = int(summary.get("allowlisted_candidate_count", 0))
    range_count = int(summary.get("range_count_total", 0))
    nested_deduped_count = int(summary.get("nested_deduped_count", 0))
    empty_range_count = int(summary.get("empty_range_count", 0))
    if range_count > 0:
        return "none"
    if candidate_count == 0:
        return "no_prune_candidates"
    if allowlisted_count == 0:
        return "no_allowlisted_candidates"
    if nested_deduped_count > 0 or empty_range_count > 0:
        return "all_candidates_nested_or_empty"
    return "apply_ranges_empty"


def stable_project_spine_anchor_spans(items: list[Item]) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    seen: set[tuple[int, int, str]] = set()
    for item in items:
        if Path(item.path) != QUANT_PIPELINE_PATH or item.kind != "section":
            continue
        if not (item.pinned or is_project_spine_stable_heading(item.section_heading)):
            continue
        key = (item.start_line, item.end_line, item.section_heading)
        if key in seen:
            continue
        seen.add(key)
        spans.append(
            {
                "start_line": item.start_line,
                "end_line": item.end_line,
                "section_heading": item.section_heading,
                "stable_heading": is_project_spine_stable_heading(item.section_heading),
                "pinned": item.pinned,
            }
        )
    return spans


def hard_apply_range_blockers(items: list[Item], range_records: list[dict[str, object]]) -> list[dict[str, object]]:
    anchor_spans = stable_project_spine_anchor_spans(items)
    blockers: list[dict[str, object]] = []
    for record in range_records:
        path = Path(str(record.get("path") or ""))
        start_line = int(record.get("start_line") or 0)
        end_line = int(record.get("end_line") or 0)
        reasons: list[str] = []
        anchor_heading: str | None = None
        if path not in APPLY_ALLOWED:
            reasons.append("outside_apply_allowed")
        if path == Path("context/decisions.md"):
            reasons.append("decisions_apply_range")
        if path == QUANT_PIPELINE_PATH:
            for anchor in anchor_spans:
                if overlap(start_line, end_line, int(anchor["start_line"]), int(anchor["end_line"])):
                    reasons.append("stable_project_spine_anchor_range")
                    anchor_heading = str(anchor["section_heading"])
                    break
        if reasons:
            blockers.append(
                {
                    "path": str(path),
                    "kind": record.get("kind"),
                    "start_line": start_line,
                    "end_line": end_line,
                    "section_heading": record.get("section_heading"),
                    "anchor_heading": anchor_heading,
                    "reason": record.get("reason"),
                    "evidence_class": record.get("evidence_class"),
                    "blocker_reasons": reasons,
                }
            )
    return blockers


PROJECT_SPINE_BUDGET_ESCALATION_REASON_PREFIX = "project-spine-budget-pressure-"
PROJECT_SPINE_BUDGET_BLOCKER_LIMIT = 20


def project_spine_budget_target_bytes() -> int:
    budget = HOT_CONTEXT_BUDGETS.get(QUANT_PIPELINE_PATH, {})
    return int(budget.get("target_bytes") or 100_000)


def project_spine_budget_hard_bytes() -> int:
    budget = HOT_CONTEXT_BUDGETS.get(QUANT_PIPELINE_PATH, {})
    return int(budget.get("hard_bytes") or project_spine_budget_target_bytes())


def is_project_spine_budget_escalated_item(item: Item) -> bool:
    return item.reason.startswith(PROJECT_SPINE_BUDGET_ESCALATION_REASON_PREFIX)


def item_dated_age_days(item: Item, as_of_dt: datetime | None) -> float:
    if as_of_dt is None or not item.explicit_dates:
        return 0.0
    ages: list[float] = []
    for raw in item.explicit_dates:
        dt = parse_iso(raw + "T00:00:00+00:00")
        if dt:
            ages.append(days_between(as_of_dt, dt))
    return max(ages) if ages else 0.0


def project_spine_budget_pressure_base_eligible(item: Item) -> tuple[bool, str | None]:
    if Path(item.path) != QUANT_PIPELINE_PATH:
        return False, None
    if item.classification == "prune_candidate":
        return False, None
    if item.pinned or is_project_spine_pinned_heading(item.section_heading):
        return False, "stable_project_spine_anchor"
    if item.age_days <= ACTIVE_RECENT_PROTECT_DAYS:
        return False, "recent_zero_to_three_day_content"
    if item_has_strong_targeted_evidence(item):
        return False, "strong_targeted_current_or_unresolved"
    if Path(item.path) not in APPLY_ALLOWED:
        return False, "outside_apply_allowed"
    return True, None


def project_spine_budget_pressure_candidate_bucket(item: Item, as_of_dt: datetime | None) -> tuple[int, str] | None:
    eligible, _blocker = project_spine_budget_pressure_base_eligible(item)
    if not eligible:
        return None
    text = item_span_text(item)
    compressed_item = is_compressed_item_text(item.kind, text)
    dated_age = item_dated_age_days(item, as_of_dt)
    volatile = is_project_spine_volatile_heading(item.section_heading)
    evidence_allows_oversized = item.evidence_class in {"none", "weak_or_broad_only", "invalid_or_unknown"}
    if compressed_item and item.age_days >= COMPRESSED_ITEM_PRUNE_DAYS:
        return 1, "compressed-note-aged-unused"
    if item.kind == "section" and is_project_spine_section_prunable(item.section_heading) and dated_age >= 30:
        return 2, "dated-section-30d"
    if item.kind == "section" and is_project_spine_section_prunable(item.section_heading) and dated_age >= 11:
        return 3, "dated-section-11d"
    if volatile and evidence_allows_oversized and is_project_spine_oversized_for_review(item.kind, text):
        return 4, "oversized-volatile-weak-or-none"
    large_enough = item.char_count >= (MIN_SECTION_CHARS if item.kind == "section" else MIN_BULLET_CHARS)
    if volatile and item_has_medium_without_strong_evidence(item) and item.age_days >= 14 and large_enough:
        return 5, "medium-evidence-volatile-14d"
    return None


def project_spine_budget_pressure_candidate_sort_key(item: Item, as_of_dt: datetime | None) -> tuple[object, ...]:
    bucket = project_spine_budget_pressure_candidate_bucket(item, as_of_dt)
    assert bucket is not None
    bucket_order, _reason = bucket
    dated_age = item_dated_age_days(item, as_of_dt)
    kind_order = 0 if item.kind == "bullet" else 1
    return (
        bucket_order,
        -dated_age,
        -float(item.age_days),
        -int(item.char_count),
        kind_order,
        item.path,
        item.start_line,
        item.end_line,
        item.section_heading,
    )


def project_spine_budget_candidate_ranges(items: list[Item]) -> list[tuple[int, int, str]]:
    return [
        (item.start_line, item.end_line, item.kind)
        for item in items
        if Path(item.path) == QUANT_PIPELINE_PATH and item.classification == "prune_candidate"
    ]


def project_spine_projected_bytes_after(items: list[Item]) -> tuple[int, int]:
    projection = projected_apply_bytes(str(QUANT_PIPELINE_PATH), project_spine_budget_candidate_ranges(items))
    if projection:
        return int(projection.get("projected_bytes_before_apply", 0)), int(projection.get("projected_bytes_after_apply", 0))
    record = budget_record(QUANT_PIPELINE_PATH, HOT_CONTEXT_BUDGETS.get(QUANT_PIPELINE_PATH), default_mode="apply_allowed")
    before = int(record.get("bytes") or 0)
    return before, before


def project_spine_shrink_cap_after_bytes(source_bytes_before: int, max_file_shrink_ratio: float = DEFAULT_MAX_FILE_SHRINK_RATIO) -> int:
    if source_bytes_before <= 0:
        return 0
    max_shrink = int(source_bytes_before * max(0.0, max_file_shrink_ratio))
    return source_bytes_before - max_shrink


def apply_project_spine_budget_pressure(items: list[Item], budget_summary: dict) -> list[Item]:
    """Escalate old, non-strong project-spine items when baseline pruning misses target."""
    hot_docs = budget_summary.get("hot_docs") if isinstance(budget_summary.get("hot_docs"), dict) else {}
    record = hot_docs.get(str(QUANT_PIPELINE_PATH)) if isinstance(hot_docs, dict) else None
    if not isinstance(record, dict):
        return items
    source_bytes_before = int(record.get("bytes") or 0)
    target_bytes = int(record.get("target_bytes") or project_spine_budget_target_bytes())
    if source_bytes_before <= target_bytes:
        return items

    as_of_dt = parse_iso(str(budget_summary.get("_now_iso"))) if budget_summary.get("_now_iso") else None
    cap_after_bytes = project_spine_shrink_cap_after_bytes(source_bytes_before)
    _before, projected_after = project_spine_projected_bytes_after(items)
    if projected_after <= target_bytes:
        return items
    if projected_after < cap_after_bytes:
        return items

    candidates = [
        item
        for item in items
        if project_spine_budget_pressure_candidate_bucket(item, as_of_dt) is not None
    ]
    candidates.sort(key=lambda item: project_spine_budget_pressure_candidate_sort_key(item, as_of_dt))

    for item in candidates:
        if projected_after <= target_bytes:
            break
        bucket = project_spine_budget_pressure_candidate_bucket(item, as_of_dt)
        if bucket is None:
            continue
        _bucket_order, reason_suffix = bucket
        original_classification = item.classification
        original_reason = item.reason
        item.classification = "prune_candidate"
        item.reason = f"{PROJECT_SPINE_BUDGET_ESCALATION_REASON_PREFIX}{reason_suffix}"
        _candidate_before, candidate_after = project_spine_projected_bytes_after(items)
        if candidate_after < cap_after_bytes:
            item.classification = original_classification
            item.reason = original_reason
            break
        projected_after = candidate_after
    return items


def project_spine_budget_blocker_records(items: list[Item], projected_after: int, target_bytes: int, source_bytes_before: int) -> list[dict[str, object]]:
    if projected_after <= target_bytes:
        return []
    blockers: list[dict[str, object]] = []
    cap_after = project_spine_shrink_cap_after_bytes(source_bytes_before)
    if source_bytes_before > 0 and projected_after <= cap_after:
        blockers.append(
            {
                "reason": "large_shrink_cap",
                "path": str(QUANT_PIPELINE_PATH),
                "source_bytes_before": source_bytes_before,
                "projected_after_bytes": projected_after,
                "cap_after_bytes": cap_after,
                "max_file_shrink_ratio": DEFAULT_MAX_FILE_SHRINK_RATIO,
                "deficit_bytes": max(0, projected_after - target_bytes),
                "route": "split_across_future_capped_applies",
            }
        )
    eligible_remaining = [
        item
        for item in items
        if item.classification != "prune_candidate"
        and Path(item.path) == QUANT_PIPELINE_PATH
        and project_spine_budget_pressure_base_eligible(item)[0]
    ]
    if not eligible_remaining:
        blockers.append(
            {
                "reason": "no_eligible_project_spine_candidates",
                "path": str(QUANT_PIPELINE_PATH),
                "deficit_bytes": max(0, projected_after - target_bytes),
                "route": "manual_review_or_wait_for_more_items_to_mature",
            }
        )
    for item in sorted(items, key=lambda candidate: (candidate.path, candidate.start_line, candidate.end_line)):
        eligible, blocker = project_spine_budget_pressure_base_eligible(item)
        if eligible or blocker is None or Path(item.path) != QUANT_PIPELINE_PATH:
            continue
        if blocker == "stable_project_spine_anchor" and item.kind != "section":
            continue
        if blocker == "stable_project_spine_anchor":
            category = "stable_project_spine_anchor"
            route = "autonomous_anchor_summary"
        elif blocker == "strong_targeted_current_or_unresolved":
            category = "strong_targeted_recent_or_unresolved"
            route = "defer_recent_content"
        elif blocker == "recent_zero_to_three_day_content":
            category = "recent_zero_to_three_day_content"
            route = "defer_recent_content"
        else:
            category = blocker
            route = "manual_review"
        blockers.append(
            {
                "reason": blocker,
                "category": category,
                "route": route,
                "path": item.path,
                "kind": item.kind,
                "section_heading": item.section_heading,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "char_count": item.char_count,
                "evidence_class": item.evidence_class,
            }
        )
        if len(blockers) >= PROJECT_SPINE_BUDGET_BLOCKER_LIMIT:
            break
    return blockers[:PROJECT_SPINE_BUDGET_BLOCKER_LIMIT]


def project_spine_budget_pressure_fields(items: list[Item], apply_summary: dict[str, object]) -> dict[str, object]:
    source_bytes_before = int(apply_summary.get("quant_pipeline_source_bytes_before") or 0)
    projected_after = int(apply_summary.get("quant_pipeline_source_bytes_after_planned") or source_bytes_before)
    target_bytes = project_spine_budget_target_bytes()
    escalated_items = [item for item in items if is_project_spine_budget_escalated_item(item)]
    blockers = project_spine_budget_blocker_records(items, projected_after, target_bytes, source_bytes_before)
    return {
        "project_spine_budget_target_bytes": target_bytes,
        "project_spine_budget_projected_after_bytes": projected_after,
        "project_spine_budget_deficit_after_planning": max(0, projected_after - target_bytes),
        "project_spine_budget_escalated_candidate_count": len(escalated_items),
        "project_spine_budget_escalated_bytes": sum(int(item.char_count) for item in escalated_items),
        "project_spine_budget_blockers": blockers,
    }


def build_apply_plan(items: list[Item], *, include_active_live_heading_summaries: bool = False) -> dict:
    prune_candidates = [item for item in items if item.classification == "prune_candidate"]
    active_live_summary_candidates = [
        item
        for item in items
        if include_active_live_heading_summaries and item.classification == "review" and requires_active_live_heading_local_summary(item)
    ]
    ranges_by_path: dict[str, list[tuple[int, int, str]]] = {}
    range_records_by_path: dict[str, list[dict[str, object]]] = {}
    path_summary: dict[str, dict[str, int]] = {}

    def summary_for(path: str) -> dict[str, int]:
        return path_summary.setdefault(
            path,
            {
                "candidate_count": 0,
                "allowlisted_candidate_count": 0,
                "not_allowlisted_candidate_count": 0,
                "section_candidate_count": 0,
                "bullet_candidate_count": 0,
                "active_live_heading_summary_candidate_count": 0,
                "active_live_heading_summary_allowlisted_count": 0,
                "active_live_heading_summary_not_allowlisted_count": 0,
                "requires_local_summary_range_count": 0,
                "range_count": 0,
                "nested_deduped_count": 0,
            },
        )

    allowlisted_candidates: list[Item] = []
    active_live_summary_allowlisted: list[Item] = []
    active_live_summary_not_allowlisted_count = 0
    not_allowlisted_count = 0
    section_candidate_count = 0
    bullet_candidate_count = 0
    for item in prune_candidates:
        item_summary = summary_for(item.path)
        item_summary["candidate_count"] += 1
        if item.kind == "section":
            section_candidate_count += 1
            item_summary["section_candidate_count"] += 1
        elif item.kind == "bullet":
            bullet_candidate_count += 1
            item_summary["bullet_candidate_count"] += 1
        if Path(item.path) in APPLY_ALLOWED:
            allowlisted_candidates.append(item)
            item_summary["allowlisted_candidate_count"] += 1
        else:
            not_allowlisted_count += 1
            item_summary["not_allowlisted_candidate_count"] += 1

    for item in active_live_summary_candidates:
        item_summary = summary_for(item.path)
        item_summary["active_live_heading_summary_candidate_count"] += 1
        if Path(item.path) in APPLY_ALLOWED:
            active_live_summary_allowlisted.append(item)
            item_summary["active_live_heading_summary_allowlisted_count"] += 1
        else:
            active_live_summary_not_allowlisted_count += 1
            item_summary["active_live_heading_summary_not_allowlisted_count"] += 1

    section_ranges = [item for item in allowlisted_candidates if item.kind == "section"] + active_live_summary_allowlisted
    bullet_ranges = [item for item in allowlisted_candidates if item.kind == "bullet"]

    def add_range(item: Item) -> None:
        requires_local_summary = requires_active_live_heading_local_summary(item)
        ranges_by_path.setdefault(item.path, []).append((item.start_line, item.end_line, item.kind))
        if requires_local_summary:
            summary_for(item.path)["requires_local_summary_range_count"] += 1
        range_records_by_path.setdefault(item.path, []).append(
            {
                "path": item.path,
                "kind": item.kind,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "section_heading": item.section_heading,
                "reason": item.reason,
                "evidence_class": item.evidence_class,
                "requires_local_summary": requires_local_summary,
                "char_count": item.char_count,
                "text_hash": item.text_hash,
            }
        )

    nested_deduped_count = 0
    for item in section_ranges:
        add_range(item)
    for item in bullet_ranges:
        covered = False
        for section in section_ranges:
            if section.path == item.path and overlap(item.start_line, item.end_line, section.start_line, section.end_line):
                covered = True
                break
        if covered:
            nested_deduped_count += 1
            summary_for(item.path)["nested_deduped_count"] += 1
            continue
        add_range(item)

    range_records: list[dict[str, object]] = []
    for path, ranges in ranges_by_path.items():
        records = range_records_by_path[path]
        combined = sorted(zip(ranges, records), key=lambda pair: pair[0])
        sorted_ranges = [range_tuple for range_tuple, _record in combined]
        sorted_records = [record for _range_tuple, record in combined]
        ranges_by_path[path] = sorted_ranges
        path_summary[path]["range_count"] = len(sorted_ranges)
        range_records.extend(sorted_records)

    empty_range_count = sum(1 for ranges in ranges_by_path.values() for start, end, _kind in ranges if end < start)
    requires_local_summary_range_count = sum(1 for record in range_records if record.get("requires_local_summary") is True)
    range_reason_counts = Counter(str(record.get("reason") or "unknown") for record in range_records)
    quant_path = str(QUANT_PIPELINE_PATH)
    quant_projection = projected_apply_bytes(quant_path, ranges_by_path.get(quant_path, []))
    quant_before = int(quant_projection.get("projected_bytes_before_apply", 0)) if quant_projection else 0
    quant_after = int(quant_projection.get("projected_bytes_after_apply", quant_before)) if quant_projection else quant_before
    hard_blockers = hard_apply_range_blockers(items, range_records)
    hard_blocker_reasons = Counter(reason for blocker in hard_blockers for reason in blocker.get("blocker_reasons", []))
    summary = {
        "candidate_count_total": len(prune_candidates),
        "allowlisted_candidate_count": len(allowlisted_candidates),
        "not_allowlisted_candidate_count": not_allowlisted_count,
        "section_candidate_count": section_candidate_count,
        "bullet_candidate_count": bullet_candidate_count,
        "active_live_heading_summary_candidate_count": len(active_live_summary_candidates),
        "active_live_heading_summary_allowlisted_count": len(active_live_summary_allowlisted),
        "active_live_heading_summary_not_allowlisted_count": active_live_summary_not_allowlisted_count,
        "requires_local_summary_range_count": requires_local_summary_range_count,
        "range_count_total": sum(len(ranges) for ranges in ranges_by_path.values()),
        "range_reason_counts": dict(sorted(range_reason_counts.items())),
        "nested_deduped_count": nested_deduped_count,
        "empty_range_count": empty_range_count,
        "quant_pipeline_source_bytes_before": quant_before,
        "quant_pipeline_source_bytes_after_planned": quant_after,
        "quant_pipeline_source_bytes_delta_planned": quant_after - quant_before,
        "quant_pipeline_apply_range_count": len(ranges_by_path.get(quant_path, [])),
        "quant_pipeline_prune_candidate_count": sum(1 for item in prune_candidates if Path(item.path) == QUANT_PIPELINE_PATH),
        "quant_pipeline_stable_anchor_range_count": int(hard_blocker_reasons.get("stable_project_spine_anchor_range", 0)),
        "unsafe_apply_range_count": len(hard_blockers),
        "unsafe_apply_range_reasons": dict(sorted(hard_blocker_reasons.items())),
        "per_path": {path: path_summary[path] for path in sorted(path_summary)},
    }
    summary.update(project_spine_budget_pressure_fields(items, summary))
    return {
        "summary": summary,
        "ranges_by_path": ranges_by_path,
        "range_records": range_records,
    }


def candidate_ranges(items: list[Item]) -> dict[str, list[tuple[int, int, str]]]:
    return build_apply_plan(items)["ranges_by_path"]


def default_local_compression_config() -> LocalCompressionConfig:
    return LocalCompressionConfig(
        enabled=True,
        model=DEFAULT_LOCAL_COMPRESS_MODEL,
        ollama_url=DEFAULT_OLLAMA_GENERATE_URL,
        max_blocks=LOCAL_COMPRESS_MAX_BLOCKS,
        timeout_seconds=180,
        lock_timeout_seconds=DEFAULT_LOCAL_COMPRESS_LOCK_TIMEOUT_SECONDS,
        max_summary_chars=LOCAL_COMPRESSED_SUMMARY_MAX_CHARS,
    )


def should_reserve_local_priority(items: list[Item], ranges_by_path: dict[str, list[tuple[int, int, str]]], local_config: LocalCompressionConfig) -> bool:
    if not local_config.enabled or not local_config.priority or local_config.max_blocks <= 0:
        return False
    items_by_identity = {(item.path, item.start_line, item.end_line, item.kind): item for item in items}
    for path, ranges in ranges_by_path.items():
        for start, end, kind in ranges:
            item = items_by_identity.get((path, start, end, kind))
            if item and supports_compressed_replacement(item, "") and item.char_count >= MIN_SECTION_CHARS:
                return True
    return False


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_shrink_records_from_apply_plan(apply_plan: dict) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    ranges_by_path = apply_plan.get("ranges_by_path") if isinstance(apply_plan.get("ranges_by_path"), dict) else {}
    for path, ranges in ranges_by_path.items():
        if not isinstance(path, str) or not isinstance(ranges, list):
            continue
        projection = projected_apply_bytes(path, ranges)
        if not projection:
            continue
        before = int(projection.get("projected_bytes_before_apply", 0))
        after = int(projection.get("projected_bytes_after_apply", before))
        files.append(
            {
                "path": path,
                "source_bytes_before": before,
                "source_bytes_after_planned": after,
                "source_bytes_delta_planned": after - before,
            }
        )
    return files


def apply_acceptance_summary(
    items: list[Item],
    apply_plan: dict,
    *,
    file_records: list[dict[str, object]] | None = None,
    max_file_shrink_ratio: float = DEFAULT_MAX_FILE_SHRINK_RATIO,
    allow_large_shrink: bool = False,
) -> dict[str, object]:
    max_ratio = max(0.0, float(max_file_shrink_ratio))
    range_records = apply_plan.get("range_records") if isinstance(apply_plan.get("range_records"), list) else []
    hard_blockers = hard_apply_range_blockers(items, range_records)
    files = file_records if file_records is not None else file_shrink_records_from_apply_plan(apply_plan)
    large_shrink_files: list[dict[str, object]] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        path = str(file.get("path") or "")
        before = int(file.get("source_bytes_before", 0) or 0)
        after = int(file.get("source_bytes_after_planned", before) or before)
        if before <= 0:
            continue
        budget = HOT_CONTEXT_BUDGETS.get(Path(path))
        target = int(budget["target_bytes"]) if isinstance(budget, dict) and budget.get("target_bytes") is not None else None
        if target is not None and before < target:
            continue
        shrink_ratio = max(0.0, (before - after) / before)
        if shrink_ratio > max_ratio:
            large_shrink_files.append(
                {
                    "path": path,
                    "source_bytes_before": before,
                    "source_bytes_after_planned": after,
                    "source_bytes_delta_planned": after - before,
                    "shrink_ratio": round(shrink_ratio, 6),
                    "max_file_shrink_ratio": max_ratio,
                    "target_bytes": target,
                }
            )
    large_shrink_requires_override = bool(large_shrink_files and not allow_large_shrink)
    return {
        "hard_blocker_count": len(hard_blockers),
        "hard_blockers": hard_blockers[:20],
        "large_shrink_requires_override": large_shrink_requires_override,
        "large_shrink_file_count": len(large_shrink_files),
        "large_shrink_files": large_shrink_files[:20],
        "max_file_shrink_ratio": max_ratio,
        "allow_large_shrink": allow_large_shrink,
        "blocked": bool(hard_blockers or large_shrink_requires_override),
    }


def active_live_heading_summary_manifest(range_records: list[dict[str, object]]) -> dict[str, object]:
    ranges = [record for record in range_records if record.get("requires_local_summary") is True]
    return {
        "range_count": len(ranges),
        "applied": 0,
        "skipped": 0,
        "skip_reasons": {},
        "skipped_ranges": [],
        "applied_ranges": [],
    }


def record_active_live_heading_summary_skip(
    manifest: dict[str, object],
    *,
    item: Item | None,
    path: str,
    start: int,
    end: int,
    reason: str,
    detail: str | None = None,
) -> None:
    summary = manifest.get("active_live_heading_summary")
    if not isinstance(summary, dict):
        return
    summary["skipped"] = int(summary.get("skipped", 0)) + 1
    skip_reasons = summary.setdefault("skip_reasons", {})
    if isinstance(skip_reasons, dict):
        skip_reasons[reason] = int(skip_reasons.get(reason, 0)) + 1
    skipped_ranges = summary.setdefault("skipped_ranges", [])
    if isinstance(skipped_ranges, list) and len(skipped_ranges) < 20:
        skipped_ranges.append(
            {
                "path": path,
                "start_line": start,
                "end_line": end,
                "section_heading": item.section_heading if item else None,
                "reason": item.reason if item else None,
                "skip_reason": reason,
                "skip_detail": detail,
                "requires_local_summary": True,
            }
        )


def record_active_live_heading_summary_apply(
    manifest: dict[str, object],
    *,
    item: Item,
    path: str,
    start: int,
    end: int,
    archive_hash: str,
) -> None:
    summary = manifest.get("active_live_heading_summary")
    if not isinstance(summary, dict):
        return
    summary["applied"] = int(summary.get("applied", 0)) + 1
    applied_ranges = summary.setdefault("applied_ranges", [])
    if isinstance(applied_ranges, list) and len(applied_ranges) < 20:
        applied_ranges.append(
            {
                "path": path,
                "start_line": start,
                "end_line": end,
                "section_heading": item.section_heading,
                "reason": item.reason,
                "archive_hash": f"sha256:{archive_hash}",
                "requires_local_summary": True,
            }
        )


def apply_pruning(
    items: list[Item],
    stamp: str,
    local_config: LocalCompressionConfig | None = None,
    dry_run: bool = False,
    *,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
    max_file_shrink_ratio: float = DEFAULT_MAX_FILE_SHRINK_RATIO,
    allow_large_shrink: bool = False,
) -> dict:
    identity_mode = normalize_identity_mode(identity_mode)
    local_config = local_config or default_local_compression_config()
    items_by_identity = {(item.path, item.start_line, item.end_line, item.kind): item for item in items}
    apply_plan = build_apply_plan(items, include_active_live_heading_summaries=True)
    ranges_by_path = apply_plan["ranges_by_path"]
    budget_summary = build_hot_context_budget_summary(items)
    now_root = ARCHIVE_ROOT / stamp
    now_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "archive_root": str(now_root),
        "mode": "dry_run" if dry_run else "apply",
        "identityMode": identity_mode,
        "pre_apply_manifest": str(now_root / "pre-apply-manifest.json"),
        "candidate_summary": apply_plan["summary"],
        "project_spine_budget_pressure": {
            key: apply_plan["summary"].get(key)
            for key in [
                "project_spine_budget_target_bytes",
                "project_spine_budget_projected_after_bytes",
                "project_spine_budget_deficit_after_planning",
                "project_spine_budget_escalated_candidate_count",
                "project_spine_budget_escalated_bytes",
                "project_spine_budget_blockers",
            ]
        },
        "range_records": apply_plan["range_records"][:200],
        "range_reason_counts": apply_plan["summary"].get("range_reason_counts", {}),
        "active_live_heading_summary": active_live_heading_summary_manifest(apply_plan["range_records"]),
        "budget_summary": budget_summary,
        "protected_budget_debt_bytes_total": budget_summary["protected_budget_debt_bytes_total"],
        "protected_budget_debt_by_category": budget_summary["protected_budget_debt_by_category"],
        "protected_budget_debt_routes": budget_summary["protected_budget_debt_routes"],
        "budget_success": budget_summary["budget_success"],
        "source_bytes_before_total": 0,
        "source_bytes_after_planned_total": 0,
        "source_bytes_delta_planned_total": 0,
        "no_op_reason": apply_plan_no_op_reason(apply_plan["summary"]),
        "apply_blocked": False,
        "large_shrink_requires_override": False,
        "apply_acceptance": apply_acceptance_summary(
            items,
            apply_plan,
            max_file_shrink_ratio=max_file_shrink_ratio,
            allow_large_shrink=allow_large_shrink,
        ),
        "files": [],
        "local_compression": {
            "enabled": local_config.enabled,
            "model": local_config.model if local_config.enabled else None,
            "max_blocks": local_config.max_blocks if local_config.enabled else 0,
            "priority": bool(local_config.enabled and local_config.priority),
            "priority_reserved": False,
            "attempted": 0,
            "succeeded": 0,
            "fallback": 0,
            "errors": [],
        },
    }
    local_used = 0
    priority_cm = nullcontext()
    if should_reserve_local_priority(items, ranges_by_path, local_config):
        priority_cm = LocalModelPriorityReservation(local_config.model)
        manifest["local_compression"]["priority_reserved"] = True

    with priority_cm:
        planned_writes: list[dict] = []
        for path, ranges in ranges_by_path.items():
            src = WORKBENCH_ROOT / path
            original_text = src.read_text()
            lines = original_text.splitlines()
            archive_path = now_root / path
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            removed_blocks = []
            keep = []
            idx = 1
            range_iter = iter(ranges)
            current = next(range_iter, None)
            while idx <= len(lines):
                if current and current[0] <= idx <= current[1]:
                    start, end, kind = current
                    removed_text = "\n".join(lines[start - 1 : end])
                    item = items_by_identity.get((path, start, end, kind))
                    replacement_lines: list[str] = []
                    replacement_source = "none"
                    local_error: str | None = None
                    removed_hash_full = sha256_text(removed_text)
                    archive_hash = removed_hash_full
                    requires_local_summary = bool(item and requires_active_live_heading_local_summary(item))
                    if item:
                        local_summary: str | None = None
                        if requires_local_summary:
                            fallback_detail: str | None = None
                            if not local_config.enabled:
                                fallback_detail = "local_compression_disabled"
                            elif local_used >= local_config.max_blocks:
                                fallback_detail = "local_compression_max_blocks_exhausted"
                            elif not can_local_compress(item, removed_text):
                                fallback_detail = "local_compression_not_available"
                            else:
                                manifest["local_compression"]["attempted"] += 1
                                try:
                                    local_summary = call_local_compressor(removed_text, item, local_config)
                                    local_used += 1
                                    manifest["local_compression"]["succeeded"] += 1
                                    replacement_source = "local_model"
                                except Exception as exc:  # noqa: BLE001
                                    local_error = str(exc)
                                    fallback_detail = f"local_compression_error:{local_error}"
                                    manifest["local_compression"]["errors"].append({
                                        "path": path,
                                        "start_line": start,
                                        "end_line": end,
                                        "error": local_error,
                                    })
                            if local_summary is None:
                                local_summary = deterministic_active_fallback_summary(item, removed_text)
                                replacement_source = "deterministic_active_fallback"
                                manifest["local_compression"]["fallback"] += 1
                            replacement_lines = compressed_replacement_lines(
                                item,
                                removed_text,
                                local_summary=local_summary,
                                archive_hash=archive_hash,
                            )
                            valid, validation_reason = validate_active_live_heading_replacement(
                                item,
                                removed_text,
                                replacement_lines,
                                archive_hash=archive_hash,
                            )
                            if not valid:
                                if replacement_source == "local_model":
                                    fallback_summary = deterministic_active_fallback_summary(item, removed_text)
                                    fallback_lines = compressed_replacement_lines(
                                        item,
                                        removed_text,
                                        local_summary=fallback_summary,
                                        archive_hash=archive_hash,
                                    )
                                    fallback_valid, fallback_validation_reason = validate_active_live_heading_replacement(
                                        item,
                                        removed_text,
                                        fallback_lines,
                                        archive_hash=archive_hash,
                                    )
                                    if fallback_valid:
                                        local_summary = fallback_summary
                                        replacement_lines = fallback_lines
                                        replacement_source = "deterministic_active_fallback"
                                        manifest["local_compression"]["fallback"] += 1
                                        valid = True
                                        validation_reason = None
                                    else:
                                        validation_reason = f"{validation_reason};fallback:{fallback_validation_reason}"
                                if not valid:
                                    detail = validation_reason
                                    if fallback_detail:
                                        detail = f"{detail};{fallback_detail}"
                                    record_active_live_heading_summary_skip(
                                        manifest,
                                        item=item,
                                        path=path,
                                        start=start,
                                        end=end,
                                        reason="validation_failed",
                                        detail=detail,
                                    )
                                    keep.extend(lines[start - 1 : end])
                                    idx = end + 1
                                    current = next(range_iter, None)
                                    continue
                            if valid:
                                record_active_live_heading_summary_apply(
                                    manifest,
                                    item=item,
                                    path=path,
                                    start=start,
                                    end=end,
                                    archive_hash=archive_hash,
                                )
                        else:
                            if local_config.enabled and local_used < local_config.max_blocks and can_local_compress(item, removed_text):
                                manifest["local_compression"]["attempted"] += 1
                                try:
                                    local_summary = call_local_compressor(removed_text, item, local_config)
                                    local_replacement_lines = compressed_replacement_lines(item, removed_text, local_summary=local_summary)
                                    if replacement_shrinks_removed_text(removed_text, local_replacement_lines):
                                        local_used += 1
                                        manifest["local_compression"]["succeeded"] += 1
                                        replacement_lines = local_replacement_lines
                                        replacement_source = "local_model"
                                    else:
                                        local_summary = None
                                        local_error = "local_compression_non_shrinking"
                                        manifest["local_compression"]["fallback"] += 1
                                        manifest["local_compression"]["errors"].append({
                                            "path": path,
                                            "start_line": start,
                                            "end_line": end,
                                            "error": local_error,
                                        })
                                except Exception as exc:  # noqa: BLE001
                                    local_error = str(exc)
                                    manifest["local_compression"]["fallback"] += 1
                                    manifest["local_compression"]["errors"].append({
                                        "path": path,
                                        "start_line": start,
                                        "end_line": end,
                                        "error": local_error,
                                    })
                            if not replacement_lines:
                                replacement_lines = compressed_replacement_lines(item, removed_text, local_summary=local_summary)
                            if replacement_lines and replacement_source == "none":
                                replacement_source = "deterministic"
                    removed_blocks.append({
                        "kind": kind,
                        "start_line": start,
                        "end_line": end,
                        "text": removed_text,
                        "text_sha256": removed_hash_full,
                        "item": asdict(item) if item else None,
                        "replacement_source": replacement_source,
                        "replacement_lines": replacement_lines,
                        "requires_local_summary": requires_local_summary,
                        "local_compression_error": local_error,
                    })
                    keep.extend(replacement_lines)
                    idx = end + 1
                    current = next(range_iter, None)
                    continue
                keep.append(lines[idx - 1])
                idx += 1
            if not removed_blocks:
                continue
            while keep and keep[-1] == "":
                keep.pop()
            new_text = "\n".join(keep) + "\n"
            archive_payload = {"source": str(src), "removed": removed_blocks}
            source_bytes_before = len(original_text.encode("utf-8"))
            source_bytes_after_planned = len(new_text.encode("utf-8"))
            source_lines_before = len(lines)
            source_lines_after_planned = len(new_text.splitlines())
            record = {
                "path": path,
                "removed_blocks": len(removed_blocks),
                "archive": str(archive_path),
                "source_sha256_before": sha256_text(original_text),
                "source_sha256_after_planned": sha256_text(new_text),
                "source_bytes_before": source_bytes_before,
                "source_bytes_after_planned": source_bytes_after_planned,
                "source_bytes_delta_planned": source_bytes_after_planned - source_bytes_before,
                "source_lines_before": source_lines_before,
                "source_lines_after_planned": source_lines_after_planned,
                "source_lines_delta_planned": source_lines_after_planned - source_lines_before,
                "dry_run": dry_run,
            }
            manifest["source_bytes_before_total"] += source_bytes_before
            manifest["source_bytes_after_planned_total"] += source_bytes_after_planned
            manifest["source_bytes_delta_planned_total"] += source_bytes_after_planned - source_bytes_before
            if Path(path) == QUANT_PIPELINE_PATH:
                manifest["candidate_summary"]["quant_pipeline_source_bytes_before"] = source_bytes_before
                manifest["candidate_summary"]["quant_pipeline_source_bytes_after_planned"] = source_bytes_after_planned
                manifest["candidate_summary"]["quant_pipeline_source_bytes_delta_planned"] = source_bytes_after_planned - source_bytes_before
                manifest["candidate_summary"]["project_spine_budget_projected_after_bytes"] = source_bytes_after_planned
                manifest["candidate_summary"]["project_spine_budget_deficit_after_planning"] = max(0, source_bytes_after_planned - project_spine_budget_target_bytes())
                manifest["project_spine_budget_pressure"]["project_spine_budget_projected_after_bytes"] = source_bytes_after_planned
                manifest["project_spine_budget_pressure"]["project_spine_budget_deficit_after_planning"] = max(0, source_bytes_after_planned - project_spine_budget_target_bytes())
            budget_hot_docs = manifest["budget_summary"].get("hot_docs", {})
            if isinstance(budget_hot_docs, dict) and isinstance(budget_hot_docs.get(path), dict):
                hot_doc_record = budget_hot_docs[path]
                hot_doc_record["source_bytes_after_planned"] = source_bytes_after_planned
                hot_doc_record["source_bytes_delta_planned"] = source_bytes_after_planned - source_bytes_before
                target = hot_doc_record.get("target_bytes")
                hard = hot_doc_record.get("hard_bytes")
                target_int = int(target) if target is not None else None
                hard_int = int(hard) if hard is not None else None
                hot_doc_record["planned_pressure_level_after_apply"] = pressure_level(source_bytes_after_planned, target_int, hard_int)
                if Path(path) == QUANT_PIPELINE_PATH:
                    project_pressure = manifest["budget_summary"].get("project_spine_budget_pressure")
                    if isinstance(project_pressure, dict):
                        project_pressure["project_spine_budget_projected_after_bytes"] = source_bytes_after_planned
                        project_pressure["project_spine_budget_deficit_after_planning"] = max(0, source_bytes_after_planned - project_spine_budget_target_bytes())
            manifest["files"].append(record)
            planned_writes.append({
                "src": src,
                "archive_path": archive_path,
                "new_text": new_text,
                "archive_payload": archive_payload,
            })
        active_summary = manifest.get("active_live_heading_summary")
        if (
            isinstance(active_summary, dict)
            and not manifest["files"]
            and int(active_summary.get("skipped", 0)) > 0
            and int(manifest["candidate_summary"].get("range_count_total", 0)) > 0
        ):
            manifest["no_op_reason"] = "all_apply_ranges_skipped"
        manifest["apply_acceptance"] = apply_acceptance_summary(
            items,
            apply_plan,
            file_records=manifest["files"],
            max_file_shrink_ratio=max_file_shrink_ratio,
            allow_large_shrink=allow_large_shrink,
        )
        manifest["apply_blocked"] = bool(manifest["apply_acceptance"].get("blocked"))
        manifest["large_shrink_requires_override"] = bool(manifest["apply_acceptance"].get("large_shrink_requires_override"))
        if manifest["large_shrink_requires_override"]:
            manifest["no_op_reason"] = "large_shrink_requires_override"
        pre_apply_path = now_root / "pre-apply-manifest.json"
        pre_apply_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        if not dry_run and manifest["apply_blocked"]:
            raise RuntimeError("apply_blocked:" + json.dumps(manifest["apply_acceptance"].get("hard_blockers") or manifest["apply_acceptance"].get("large_shrink_files") or []))
        if not dry_run:
            for planned in planned_writes:
                planned["archive_path"].write_text(json.dumps(planned["archive_payload"], indent=2) + "\n")
                planned["src"].write_text(planned["new_text"])
    return manifest


def stat_int(stats: dict[str, object], key: str) -> int:
    value = stats.get(key, 0)
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0



EVIDENCE_REPORT_EXAMPLE_LIMIT = 10
TELEMETRY_MATCH_SOURCES = ("line_span", "content_hash", "both", "none", "ambiguous_content_hash")


def context_telemetry_match_source_counts(stats: dict[str, object] | None) -> dict[str, int]:
    raw_counts = stats.get("telemetry_item_match_source_counts") if isinstance(stats, dict) else None
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    normalized = {source: int(counts.get(source, 0) or 0) for source in TELEMETRY_MATCH_SOURCES}
    extras = {str(key): int(value or 0) for key, value in counts.items() if str(key) not in normalized}
    return dict(sorted({**normalized, **extras}.items()))


def context_telemetry_stale_line_span_entry_count(stats: dict[str, object] | None) -> int:
    raw = stats.get("_stale_line_span_entry_keys") if isinstance(stats, dict) else None
    return len(raw) if isinstance(raw, set) else 0


def item_has_strong_targeted_evidence(item: Item) -> bool:
    return item.evidence_class == "strong_targeted" or item.strong_evidence_hits > 0


def item_has_medium_without_strong_evidence(item: Item) -> bool:
    return item.medium_evidence_hits > 0 and item.strong_evidence_hits == 0


def item_has_weak_broad_only_evidence(item: Item) -> bool:
    return item.evidence_class == "weak_or_broad_only" or (item.weak_broad_evidence_hits > 0 and item.strong_evidence_hits == 0 and item.medium_evidence_hits == 0)


def is_evidence_pressure_candidate(item: Item) -> bool:
    return item.classification in {"review", "prune_candidate"}


def is_medium_evidence_pressure_compression_eligible(item: Item) -> bool:
    return item_has_medium_without_strong_evidence(item) and is_evidence_pressure_candidate(item)


def is_weak_broad_review_eligible(item: Item) -> bool:
    return item_has_weak_broad_only_evidence(item) and is_evidence_pressure_candidate(item)


def build_evidence_report_diagnostics(items: list[Item]) -> dict[str, object]:
    by_evidence_class = Counter((item.evidence_class or "none") for item in items)
    strong_protected = [item for item in items if item_has_strong_targeted_evidence(item) and item.classification == "keep"]
    medium_pressure = [item for item in items if is_medium_evidence_pressure_compression_eligible(item)]
    weak_broad_review = [item for item in items if is_weak_broad_review_eligible(item)]
    invalid_unknown = [item for item in items if item.evidence_class == "invalid_or_unknown"]
    weak_broad_stale_active = [
        item
        for item in weak_broad_review
        if Path(item.path) == Path("context/active.md")
    ]
    medium_project_spine_pressure = [
        item
        for item in medium_pressure
        if is_project_spine(Path(item.path)) and "project-spine-pressure" in item.reason
    ]
    return {
        "items_by_evidence_class": dict(sorted(by_evidence_class.items())),
        "strong_targeted_protected_items": len(strong_protected),
        "medium_evidence_pressure_compression_eligible_items": len(medium_pressure),
        "weak_broad_review_eligible_items": len(weak_broad_review),
        "invalid_unknown_evidence_items": len(invalid_unknown),
        "top_strong_protected": sorted(strong_protected, key=lambda i: (-i.char_count, i.path, i.start_line))[:EVIDENCE_REPORT_EXAMPLE_LIMIT],
        "top_weak_broad_stale_active_candidates": sorted(weak_broad_stale_active, key=lambda i: (-i.char_count, -i.unrecalled_runs, i.start_line))[:EVIDENCE_REPORT_EXAMPLE_LIMIT],
        "top_medium_project_spine_pressure_candidates": sorted(medium_project_spine_pressure, key=lambda i: (-i.char_count, -i.unrecalled_runs, i.start_line))[:EVIDENCE_REPORT_EXAMPLE_LIMIT],
    }


def render_evidence_item(item: Item) -> str:
    return (
        f"- `{item.path}` {item.kind} lines {item.start_line}-{item.end_line} under **{item.section_heading}** — "
        f"{item.classification}/{item.reason} "
        f"(evidence={item.evidence_class}, strong={item.strong_evidence_hits}, medium={item.medium_evidence_hits}, "
        f"weakBroad={item.weak_broad_evidence_hits}, telemetryMatch={item.telemetry_match_source}, "
        f"hashRecovered={item.content_hash_recovered_hits}, chars={item.char_count}, itemAgeDays={item.age_days}, "
        f"seenRuns={item.seen_runs}, unrecalledRuns={item.unrecalled_runs})"
    )


def render_evidence_report_diagnostics(diagnostics: dict[str, object]) -> list[str]:
    lines = [
        "## Evidence diagnostics",
        "",
        f"- items by evidence_class: {diagnostics.get('items_by_evidence_class', {})}",
        f"- strong-targeted protected items: {diagnostics.get('strong_targeted_protected_items', 0)}",
        f"- medium-evidence pressure/compression eligible items: {diagnostics.get('medium_evidence_pressure_compression_eligible_items', 0)}",
        f"- weak/broad review-eligible items: {diagnostics.get('weak_broad_review_eligible_items', 0)}",
        f"- invalid/unknown evidence items: {diagnostics.get('invalid_unknown_evidence_items', 0)}",
        "",
        "### Top strong protected evidence items",
        "",
    ]
    for key, heading in [
        ("top_strong_protected", "### Top strong protected evidence items"),
        ("top_weak_broad_stale_active_candidates", "### Weak/broad stale active candidates"),
        ("top_medium_project_spine_pressure_candidates", "### Medium project-spine pressure candidates"),
    ]:
        if heading != "### Top strong protected evidence items":
            lines.extend(["", heading, ""])
        records = diagnostics.get(key)
        if not isinstance(records, list) or not records:
            lines.append("- none")
            continue
        for item in records[:EVIDENCE_REPORT_EXAMPLE_LIMIT]:
            if isinstance(item, Item):
                lines.append(render_evidence_item(item))
    lines.append("")
    return lines


def render_shadow_record(record: dict[str, object]) -> str:
    item = record.get("item")
    evidence = record.get("evidence")
    if not isinstance(item, Item) or not isinstance(evidence, ShadowEvidence):
        return "- `<invalid-shadow-record>`"
    tiers = evidence.tier_counts() or {"none": 0}
    return (
        f"- `{item.path}` {item.kind} lines {item.start_line}-{item.end_line} under **{item.section_heading}** — "
        f"current `{record.get('current_classification')}`/{record.get('current_reason')}; "
        f"proposed `{record.get('proposed_classification')}`/{record.get('proposed_reason')} "
        f"(chars={item.char_count}, proposedUnrecalledRuns={record.get('proposed_unrecalled_runs')}, "
        f"tiers={tiers}, broadReads={evidence.broad_read})"
    )


def build_report(
    items: list[Item],
    state: dict,
    config: AuditConfig,
    *,
    shadow_state: dict | None = None,
    run_bucket: str | None = None,
    budget_summary: dict | None = None,
) -> str:
    by_class: dict[str, list[Item]] = {}
    for item in items:
        by_class.setdefault(item.classification, []).append(item)
    recall_signal_items = sum(1 for item in items if item.recall_hits > 0 or item.recall_signal_count > 0)
    context_telemetry_items = count_items_with_hits(items, LAST_CONTEXT_TELEMETRY_HITS)
    kept_because_recalled_now = sum(1 for item in items if item.reason.startswith("recalled:"))
    high_recall_protected_items = sum(1 for item in items if item.reason == "high-recall-protected")
    recall_stats = LAST_RECALL_LOAD_STATS or empty_recall_load_stats()
    telemetry_match_stats = LAST_CONTEXT_TELEMETRY_MATCH_STATS or empty_context_telemetry_match_stats()
    telemetry_match_source_counts = context_telemetry_match_source_counts(telemetry_match_stats)
    telemetry_content_hash_recovered_hits = stat_int(telemetry_match_stats, "content_hash_recovered_hits")
    telemetry_ambiguous_content_hash_matches = stat_int(telemetry_match_stats, "ambiguous_content_hash_matches")
    telemetry_stale_line_span_entries = context_telemetry_stale_line_span_entry_count(telemetry_match_stats)
    loader_warnings = recall_stats.get("warnings") if isinstance(recall_stats.get("warnings"), list) else []
    telemetry_source_warnings = stat_int(recall_stats, "context_telemetry_source_warnings")
    lines = [
        "# Context Pruning Report",
        "",
        f"- updated: {state.get('updatedAt', now_iso())}",
        f"- identity mode: {state.get('identityMode', DEFAULT_IDENTITY_MODE)}",
        f"- stale threshold days: {config.stale_days}",
        f"- dormant threshold days: {config.dormant_days}",
        f"- recent grace days: {config.recent_grace_days}",
        f"- min seen runs (review/prune): {config.min_seen_runs_review}/{config.min_seen_runs_prune}",
        f"- min unrecalled runs (review/prune): {config.min_unrecalled_runs_review}/{config.min_unrecalled_runs_prune}",
        f"- size gates chars (section/bullet): {MIN_SECTION_CHARS}/{MIN_BULLET_CHARS}",
        f"- project spine pressure chars (soft/hard): {PROJECT_SPINE_SOFT_TARGET_CHARS}/{PROJECT_SPINE_HARD_PRESSURE_CHARS}",
        f"- project spine dated-section pressure chars: {PROJECT_SPINE_DATED_SECTION_CHARS}",
        f"- project spine oversized review chars (section/bullet): {PROJECT_SPINE_REVIEW_SECTION_CHARS}/{PROJECT_SPINE_REVIEW_BULLET_CHARS}",
        f"- project spine compressed-note cap per volatile section: {PROJECT_SPINE_COMPRESSED_NOTE_LIMIT}",
        f"- compressed item prune-after-unused days: {COMPRESSED_ITEM_PRUNE_DAYS}",
        f"- high-usage recall protection (runs/signals): {HIGH_USAGE_RECALL_RUNS}/{HIGH_USAGE_RECALL_SIGNALS}",
        f"- state tombstone retention days: {STATE_TOMBSTONE_RETENTION_DAYS}",
        f"- audited items: {len(items)}",
        f"- dream recall entries loaded: {stat_int(recall_stats, 'dream_entries_loaded')}",
        f"- context telemetry protective entries loaded: {stat_int(recall_stats, 'context_telemetry_entries_loaded')} / {stat_int(recall_stats, 'context_telemetry_entries_seen')} seen",
        f"- context telemetry expired protective entries: {stat_int(recall_stats, 'context_telemetry_expired_protective_entries')} (>{DEFAULT_CONTEXT_TELEMETRY_PROTECTIVE_MAX_AGE_DAYS} days)",
        f"- context telemetry covered files: {stat_int(recall_stats, 'context_telemetry_covered_files')}",
        f"- items with recall telemetry: {recall_signal_items}",
        f"- items with context telemetry: {context_telemetry_items}",
        f"- context telemetry item match sources: {telemetry_match_source_counts}",
        f"- context telemetry content-hash recovered hits: {telemetry_content_hash_recovered_hits}",
        f"- context telemetry stale line-span entries recoverable by content hash: {telemetry_stale_line_span_entries}",
        f"- context telemetry ambiguous content-hash matches: {telemetry_ambiguous_content_hash_matches}",
        f"- items kept because recalled now: {kept_because_recalled_now}",
        f"- items high-recall protected: {high_recall_protected_items}",
        f"- telemetry warnings (source/loader): {telemetry_source_warnings}/{len(loader_warnings)}",
        "",
        "## Summary",
        "",
    ]
    for key in ["keep", "review", "prune_candidate"]:
        group = by_class.get(key, [])
        lines.append(f"- {key}: {len(group)}")
    lines.append("")

    lines.extend(render_evidence_report_diagnostics(build_evidence_report_diagnostics(items)))

    budget_summary = budget_summary or state.get("budget_summary") or build_hot_context_budget_summary(items)
    lines.extend(render_hot_context_budget_summary(budget_summary))
    non_prunable_debt = budget_summary.get("non_prunable_size_debt") if isinstance(budget_summary.get("non_prunable_size_debt"), dict) else {}
    lines.extend(render_non_prunable_size_debt(non_prunable_debt))
    protected_debt = budget_summary.get("protected_budget_debt") if isinstance(budget_summary.get("protected_budget_debt"), dict) else {}
    lines.extend(render_protected_budget_debt(protected_debt))

    shadow_run_bucket = run_bucket or run_bucket_from_iso(str(state.get("updatedAt") or now_iso()))
    shadow = build_shadow_policy_comparison(items, shadow_state or state, config, shadow_run_bucket)
    proposed_review = sorted(
        shadow.get("proposed_review", []),
        key=lambda record: (-(record.get("item").char_count if isinstance(record.get("item"), Item) else 0), str(record.get("item"))),
    )[:15]
    proposed_prune = sorted(
        shadow.get("proposed_prune", []),
        key=lambda record: (str(record.get("item").path) if isinstance(record.get("item"), Item) else "", record.get("item").start_line if isinstance(record.get("item"), Item) else 0),
    )[:15]
    weak_only_protected = sorted(
        shadow.get("weak_only_protected", []),
        key=lambda record: (-(record.get("item").char_count if isinstance(record.get("item"), Item) else 0), str(record.get("item"))),
    )[:15]
    broad_read_only_protected = sorted(
        shadow.get("broad_read_only_protected", []),
        key=lambda record: (-(record.get("item").char_count if isinstance(record.get("item"), Item) else 0), str(record.get("item"))),
    )[:15]
    pinned_excluded = sorted(
        shadow.get("pinned_excluded", []),
        key=lambda record: (-(record.get("item").char_count if isinstance(record.get("item"), Item) else 0), str(record.get("item"))),
    )[:10]

    lines.extend([
        "## Shadow policy / dry-run comparison",
        "",
        "Mode: `report_only`; no current prune/apply classification changes are made by this section.",
        "",
        f"- current counts: {shadow.get('current_counts', {})}",
        f"- proposed tier-aware counts: {shadow.get('proposed_counts', {})}",
        f"- item overlap by strongest tier: {shadow.get('tier_overlap_counts', {})}",
        f"- weak-only currently protected items: {len(shadow.get('weak_only_protected', []))}",
        f"- broad-read-only currently protected items: {len(shadow.get('broad_read_only_protected', []))}",
        f"- proposed review candidates: {len(shadow.get('proposed_review', []))}",
        f"- proposed prune candidates: {len(shadow.get('proposed_prune', []))}",
        f"- pinned/stable-heading items excluded from proposed candidates: {len(shadow.get('pinned_excluded', []))}",
        "",
        "### Weak-only currently protected items",
        "",
    ])
    if not weak_only_protected:
        lines.append("- none")
    else:
        for record in weak_only_protected:
            lines.append(render_shadow_record(record))
    lines.extend(["", "### Broad-read-only currently protected items", ""])
    if not broad_read_only_protected:
        lines.append("- none")
    else:
        for record in broad_read_only_protected:
            lines.append(render_shadow_record(record))
    lines.extend(["", "### Largest proposed review candidates", ""])
    if not proposed_review:
        lines.append("- none")
    else:
        for record in proposed_review:
            lines.append(render_shadow_record(record))
    lines.extend(["", "### Proposed prune candidates", ""])
    if not proposed_prune:
        lines.append("- none")
    else:
        for record in proposed_prune:
            lines.append(render_shadow_record(record))
    lines.extend(["", "### Pinned/stable-heading exclusions", ""])
    if not pinned_excluded:
        lines.append("- none")
    else:
        for record in pinned_excluded:
            lines.append(render_shadow_record(record))
    lines.append("")

    review_items = sorted(by_class.get("review", []), key=lambda i: (-i.char_count, -i.unrecalled_runs, i.path, i.start_line))[:20]
    prune_items = sorted(by_class.get("prune_candidate", []), key=lambda i: (i.path, i.start_line))
    unrecalled_kept = sorted(
        [i for i in items if i.classification == "keep" and not i.pinned and i.recall_runs == 0],
        key=lambda i: (-i.char_count, -i.unrecalled_runs, i.path, i.start_line),
    )[:15]

    lines.extend(["## Review candidates", ""])
    if not review_items:
        lines.append("- none")
    else:
        for item in review_items:
            lines.append(
                f"- `{item.path}` {item.kind} lines {item.start_line}-{item.end_line} under **{item.section_heading}** — {item.reason} "
                f"(chars={item.char_count}, itemAgeDays={item.age_days}, seenRuns={item.seen_runs}, unrecalledRuns={item.unrecalled_runs})"
            )
    lines.append("")

    lines.extend(["## Prune candidates", ""])
    if not prune_items:
        lines.append("- none")
    else:
        for item in prune_items:
            lines.append(
                f"- `{item.path}` {item.kind} lines {item.start_line}-{item.end_line} under **{item.section_heading}** — {item.reason} "
                f"(chars={item.char_count}, itemAgeDays={item.age_days}, seenRuns={item.seen_runs}, unrecalledRuns={item.unrecalled_runs}, dates={','.join(item.explicit_dates) or 'none'})"
            )
    lines.append("")

    lines.extend(["## Largest unrecalled kept items", ""])
    if not unrecalled_kept:
        lines.append("- none")
    else:
        for item in unrecalled_kept:
            lines.append(
                f"- `{item.path}` {item.kind} lines {item.start_line}-{item.end_line} under **{item.section_heading}** — {item.reason} "
                f"(chars={item.char_count}, seenRuns={item.seen_runs}, unrecalledRuns={item.unrecalled_runs}, pinned={str(item.pinned).lower()})"
            )
    lines.append("")

    lines.extend([
        "## Notes",
        "",
        "- This report uses deterministic retention policy plus recall telemetry from `memory/.dreams/short-term-recall.json` and only `protectsFromPrune=true` entries in `context/state/context-usage-telemetry.json` when available; broad reads, raw search hits, and context edits are retained as telemetry but do not pin items by themselves.",
        "- Repeated audits matter: review/prune only starts after enough repeated unrecalled runs accumulate in `context/state/context-pruning-state.json`.",
        "- Missing/tombstoned state entries are garbage-collected after the retention window and archived under `tmp/context-archive/state-prune/` before removal.",
        "- Age is tracked per section/bullet version from persistence state rather than by whole-file mtime, so stale content inside active files can age out independently.",
        "- Automatic apply is intentionally limited to `context/active.md`, `context/projects/quant-pipeline.md`, and `context/projects/workbench-context.md`.",
        "- `context/active.md` is pruned more aggressively than project spines: large unrecalled items become prune candidates after the dormant threshold instead of requiring explicit historical markers.",
        "- `context/projects/quant-pipeline.md` uses a `project_spine` profile: stable anchor headings are pinned, volatile headings use stable age keys, soft/hard pressure and dated-section pressure flag oversized volatile content for review early, mature pressure compresses volatile bullets or dated sections into compact archived-detail notes, and old compressed notes are capped per volatile section.",
        "- Local Qwen compression is automatic on apply for eligible prune candidates after normal gates pass; priority apply runs reserve the shared Qwen lane so patched non-priority callers queue behind the full apply run. Use `--no-local-compress` for deterministic-only replacement or `--no-local-compress-priority` for normal shared-lock behavior.",
        "- Compressed breadcrumbs get their own lifecycle: after compression they are kept/reviewed first, then pruned only after the compressed-item unused window passes without recall.",
        "- High-usage items with repeated recall history or strong recall signal are protected from compression/pruning.",
        "- `context/projects/workbench-context.md` can be compressed only after normal age/usage gates pass; durable stable headings remain pinned by the common hot-doc protections.",
        "- Add `<!-- openclaw:prune:keep -->` inside a section or bullet to pin content that should never be auto-pruned.",
    ])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate-driven pruning/compression for Workbench hot context docs, with optional recall telemetry.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, help_text in {
        "audit": "Audit hot docs and write report/state.",
        "apply": "Audit and apply prune candidates to allowed files.",
    }.items():
        subparser = sub.add_parser(name, help=help_text)
        subparser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
        subparser.add_argument("--dormant-days", type=int, default=DEFAULT_DORMANT_DAYS)
        subparser.add_argument("--recent-grace-days", type=int, default=DEFAULT_RECENT_GRACE_DAYS)
        subparser.add_argument("--min-seen-runs-review", type=int, default=DEFAULT_MIN_SEEN_RUNS_REVIEW)
        subparser.add_argument("--min-seen-runs-prune", type=int, default=DEFAULT_MIN_SEEN_RUNS_PRUNE)
        subparser.add_argument("--min-unrecalled-runs-review", type=int, default=DEFAULT_MIN_UNRECALLED_RUNS_REVIEW)
        subparser.add_argument("--min-unrecalled-runs-prune", type=int, default=DEFAULT_MIN_UNRECALLED_RUNS_PRUNE)
        subparser.add_argument("--identity-mode", choices=IDENTITY_MODES, default=DEFAULT_IDENTITY_MODE, help="State identity matching mode; content-primary uses exact key, content fingerprint, then prefix fallback. line-legacy ignores fingerprint matches.")
        if name == "apply":
            subparser.add_argument("--stamp", default="latest")
            subparser.add_argument("--dry-run", action="store_true", help="Write pre-apply manifest only; do not edit source files or archive removed blocks.")
            local_group = subparser.add_mutually_exclusive_group()
            local_group.add_argument("--local-compress", dest="local_compress", action="store_true", help="Use local Ollama compression for a capped number of eligible blocks before deterministic fallback (default).")
            local_group.add_argument("--no-local-compress", dest="local_compress", action="store_false", help="Disable local Ollama compression and use deterministic replacements only.")
            subparser.set_defaults(local_compress=True)
            subparser.add_argument("--local-compress-model", default=DEFAULT_LOCAL_COMPRESS_MODEL, help="Local Ollama model for semantic compression.")
            subparser.add_argument("--local-compress-ollama-url", default=DEFAULT_OLLAMA_GENERATE_URL, help="Ollama generate API URL for local compression.")
            subparser.add_argument("--local-compress-max-blocks", type=int, default=LOCAL_COMPRESS_MAX_BLOCKS, help="Maximum local-model compression calls per apply run.")
            subparser.add_argument("--local-compress-timeout-seconds", type=int, default=180, help="HTTP timeout per local compression call.")
            subparser.add_argument("--local-compress-lock-timeout-seconds", type=float, default=DEFAULT_LOCAL_COMPRESS_LOCK_TIMEOUT_SECONDS, help="How long priority context compression waits for an in-flight shared Qwen/Ollama lock before falling back.")
            priority_group = subparser.add_mutually_exclusive_group()
            priority_group.add_argument("--local-compress-priority", dest="local_compress_priority", action="store_true", help="Reserve the shared Qwen lane for this apply run so patched non-priority callers queue behind it (default).")
            priority_group.add_argument("--no-local-compress-priority", dest="local_compress_priority", action="store_false", help="Do not create a priority reservation; use normal shared-lock behavior.")
            subparser.set_defaults(local_compress_priority=True)
            subparser.add_argument("--local-compress-max-summary-chars", type=int, default=LOCAL_COMPRESSED_SUMMARY_MAX_CHARS, help="Maximum characters of model-authored summary text before metadata/truncation.")
            subparser.add_argument("--max-file-shrink-ratio", type=float, default=DEFAULT_MAX_FILE_SHRINK_RATIO, help="Maximum planned per-file shrink ratio before mutating apply requires an explicit override.")
            subparser.add_argument("--allow-large-shrink", action="store_true", help="Allow mutating apply even when planned per-file shrink exceeds --max-file-shrink-ratio.")

    rebase = sub.add_parser("rebase-state", help="Rebuild context pruning state onto the selected identity mode.")
    rebase.add_argument("--stamp", required=True, help="Archive/manifest stamp for the state rebase run.")
    rebase.add_argument("--identity-mode", choices=IDENTITY_MODES, default=DEFAULT_IDENTITY_MODE, help="State identity matching mode; defaults to content-primary. Use line-legacy as a rollback mode.")
    rebase_mode = rebase.add_mutually_exclusive_group(required=True)
    rebase_mode.add_argument("--dry-run", action="store_true", help="Write the rebase preview artifact without changing state.")
    rebase_mode.add_argument("--apply", action="store_true", help="Archive current state and atomically write the rebased state.")

    compact = sub.add_parser("compact-state", help="Compact generated context pruning state with archive-before-write semantics.")
    compact.add_argument("--stamp", required=True, help="Archive/manifest stamp for the state compaction run.")
    compact.add_argument("--identity-mode", choices=IDENTITY_MODES, default=DEFAULT_IDENTITY_MODE, help="State identity matching mode used to identify current live items.")
    compact_mode = compact.add_mutually_exclusive_group(required=True)
    compact_mode.add_argument("--dry-run", action="store_true", help="Write the compaction preview artifact without changing state.")
    compact_mode.add_argument("--apply", action="store_true", help="Archive current state and atomically write compacted state.")

    decisions_plan = sub.add_parser("decisions-plan", help="Generate a deterministic archive-first consolidation plan for context/decisions.md without mutating source.")
    decisions_plan.add_argument("--stamp", required=True, help="Artifact stamp for the generated decisions consolidation plan.")

    decisions_apply = sub.add_parser("decisions-apply", help="Apply a validation-gated deterministic consolidation patch for context/decisions.md.")
    decisions_apply.add_argument("--stamp", required=True, help="Artifact/archive stamp for the decisions consolidation apply run.")
    decisions_apply.add_argument("--min-shrink-bytes", type=int, default=1000, help="Minimum safe shrink required when context/decisions.md is still over target.")
    return parser


def config_from_args(args: argparse.Namespace) -> AuditConfig:
    return AuditConfig(
        stale_days=args.stale_days,
        dormant_days=args.dormant_days,
        recent_grace_days=args.recent_grace_days,
        min_seen_runs_review=args.min_seen_runs_review,
        min_seen_runs_prune=args.min_seen_runs_prune,
        min_unrecalled_runs_review=args.min_unrecalled_runs_review,
        min_unrecalled_runs_prune=args.min_unrecalled_runs_prune,
    )


def local_compression_config_from_args(args: argparse.Namespace) -> LocalCompressionConfig:
    return LocalCompressionConfig(
        enabled=bool(getattr(args, "local_compress", False)),
        model=str(getattr(args, "local_compress_model", DEFAULT_LOCAL_COMPRESS_MODEL)),
        ollama_url=str(getattr(args, "local_compress_ollama_url", DEFAULT_OLLAMA_GENERATE_URL)),
        max_blocks=max(0, int(getattr(args, "local_compress_max_blocks", LOCAL_COMPRESS_MAX_BLOCKS))),
        timeout_seconds=max(1, int(getattr(args, "local_compress_timeout_seconds", 180))),
        lock_timeout_seconds=max(0.0, float(getattr(args, "local_compress_lock_timeout_seconds", DEFAULT_LOCAL_COMPRESS_LOCK_TIMEOUT_SECONDS))),
        max_summary_chars=max(160, int(getattr(args, "local_compress_max_summary_chars", LOCAL_COMPRESSED_SUMMARY_MAX_CHARS))),
        priority=bool(getattr(args, "local_compress_priority", True)),
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    envelope = RunEnvelope(
        job_name="Maintenance: Workbench Context Prune Engine",
        mode=args.cmd,
        runs_root=RUNS_ROOT,
        workspace_root=MAINTENANCE_ROOT,
        run_id=make_run_id("context-prune"),
    )

    try:
        preflight_path_exists(WORKBENCH_ROOT, "Workbench root")
        preflight_path_exists(CONTEXT_ROOT, "Workbench context root")
        preflight_writable_dir(STATE_PATH.parent, "Workbench context state directory")
        preflight_writable_dir(RUNS_ROOT, "Maintenance Workbench run directory")
        if args.cmd == "apply":
            preflight_writable_dir(ARCHIVE_ROOT, "Workbench section archive directory")
            preflight_writable_dir(STATE_ARCHIVE_ROOT, "Workbench state archive directory")
        if args.cmd == "rebase-state" and bool(getattr(args, "apply", False)):
            preflight_writable_dir(STATE_REBASE_ARCHIVE_ROOT, "Workbench state rebase archive directory")
        if args.cmd == "compact-state" and bool(getattr(args, "apply", False)):
            preflight_writable_dir(STATE_ARCHIVE_ROOT, "Workbench state archive directory")
            preflight_writable_dir(STATE_HISTORY_SHARD_ROOT, "Workbench state history shard archive directory")
        if args.cmd == "decisions-plan":
            preflight_writable_dir(DECISIONS_CONSOLIDATION_ROOT, "Workbench decisions consolidation artifact directory")
        if args.cmd == "decisions-apply":
            preflight_writable_dir(DECISIONS_CONSOLIDATION_ROOT, "Workbench decisions consolidation artifact directory")
            preflight_writable_dir(DECISIONS_CONSOLIDATION_ARCHIVE_ROOT, "Workbench decisions consolidation archive directory")

        now_str = now_iso()
        identity_mode = normalize_identity_mode(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))
        if args.cmd == "decisions-plan":
            summary = run_decisions_consolidation_plan(stamp=str(args.stamp))
            for key in ["input_path", "plan_path", "patch_path", "summary_path"]:
                path = Path(str(summary.get(key) or ""))
                if path.exists():
                    envelope.add_artifact(path)
            envelope.write_artifact("decisions-consolidation-summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
            summary_line = (
                "CONTEXT_DECISIONS_PLAN_OK "
                f"groups={summary['consolidation_group_count']} "
                f"exact={summary['exact_duplicate_group_count']} "
                f"prefix={summary['shared_prefix_group_count']} "
                f"bytes_delta={summary['bytes_delta_planned']} "
                f"deficit={summary['budget_deficit_after_consolidation']} "
                f"run={envelope_ref(envelope)}"
            )
            envelope.finish(status="ok", summary_line=summary_line, returncode=0)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

        if args.cmd == "decisions-apply":
            manifest = run_decisions_consolidation_apply(
                stamp=str(args.stamp),
                min_shrink_bytes=int(getattr(args, "min_shrink_bytes", 1000)),
            )
            for key in ["plan_summary_path", "plan_path", "patch_path", "apply_manifest_path", "archive_path"]:
                value = manifest.get(key)
                if value and Path(str(value)).exists():
                    envelope.add_artifact(Path(str(value)))
            backlog = manifest.get("decisions_backlog") if isinstance(manifest.get("decisions_backlog"), dict) else {}
            for key in ["history_path", "status_path", "markdown_path"]:
                value = backlog.get(key)
                if value and Path(str(value)).exists():
                    envelope.add_artifact(Path(str(value)))
            envelope.write_artifact("decisions-consolidation-apply-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            status = str(manifest.get("validation_status") or "unknown")
            summary_line = (
                "CONTEXT_DECISIONS_APPLY_"
                f"{'OK' if status == 'passed' else 'NOOP' if status == 'noop' else 'BLOCKED'} "
                f"status={status} "
                f"mutated={int(bool(manifest.get('source_mutated')))} "
                f"bytes_delta={manifest.get('bytes_delta_planned')} "
                f"reason={manifest.get('no_op_reason') or ','.join(str(item) for item in manifest.get('validation_failures', [])[:3]) or 'none'} "
                f"run={envelope_ref(envelope)}"
            )
            if status == "validation_failed":
                envelope.finish(status="blocked", summary_line=summary_line, returncode=1)
                print(json.dumps(manifest, indent=2, sort_keys=True))
                return 1
            envelope.finish(status="ok", summary_line=summary_line, returncode=0)
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0

        if args.cmd == "rebase-state":
            manifest = run_state_rebase(stamp=str(args.stamp), apply=bool(args.apply), now_str=now_str, identity_mode=identity_mode)
            if not bool(args.apply) and Path(str(manifest.get("preview_path"))).exists():
                envelope.add_artifact(Path(str(manifest.get("preview_path"))))
            if bool(args.apply) and Path(str(manifest.get("manifest_path"))).exists():
                envelope.add_artifact(Path(str(manifest.get("manifest_path"))))
            archived = manifest.get("archived_state_path")
            if archived and Path(str(archived)).exists():
                envelope.add_artifact(Path(str(archived)))
            if bool(args.apply):
                envelope.add_artifact(STATE_PATH)
            envelope.write_artifact("state-rebase-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            status_word = "OK" if bool(args.apply) else "DRY_RUN_OK"
            summary_line = (
                f"CONTEXT_PRUNE_STATE_REBASE_{status_word} "
                f"identity={manifest['identityMode']} "
                f"exact={manifest['entries_preserved_by_exact_key']} "
                f"fingerprint={manifest['entries_preserved_by_fingerprint']} "
                f"prefix={manifest['entries_preserved_by_prefix_alias']} "
                f"fresh={manifest['entries_started_fresh']} "
                f"ambiguous={manifest['ambiguous_fingerprint_count']} run={envelope_ref(envelope)}"
            )
            envelope.finish(status="ok", summary_line=summary_line, returncode=0)
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0

        if args.cmd == "compact-state":
            manifest = run_state_compaction(stamp=str(args.stamp), apply=bool(args.apply), now_str=now_str, identity_mode=identity_mode)
            if not bool(args.apply) and Path(str(manifest.get("preview_path"))).exists():
                envelope.add_artifact(Path(str(manifest.get("preview_path"))))
            if bool(args.apply) and Path(str(manifest.get("manifest_path"))).exists():
                envelope.add_artifact(Path(str(manifest.get("manifest_path"))))
            archived = manifest.get("archived_state_path")
            if archived and Path(str(archived)).exists():
                envelope.add_artifact(Path(str(archived)))
            if bool(args.apply):
                envelope.add_artifact(STATE_PATH)
            envelope.write_artifact("state-compaction-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            budget_met = bool(manifest.get("state_budget_met"))
            status_word = ("OK" if bool(args.apply) else "DRY_RUN_OK") if budget_met else "DEGRADED"
            summary_line = (
                f"CONTEXT_PRUNE_STATE_COMPACT_{status_word} "
                f"identity={manifest['identityMode']} "
                f"entries_before={manifest['entries_before']} "
                f"entries_after={manifest['entries_after']} "
                f"dropped={manifest['entries_dropped']} "
                f"archived={manifest.get('entries_archived', 0)} "
                f"budget={manifest.get('state_budget_status', 'unknown')} "
                f"bytes_after={manifest['state_bytes_after_planned']} "
                f"bytes_over_hard={manifest.get('state_bytes_over_hard', 0)} "
                f"bytes_delta={manifest['state_bytes_delta_planned']} run={envelope_ref(envelope)}"
            )
            envelope.finish(status="ok" if budget_met else "degraded", summary_line=summary_line, returncode=0)
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0

        config = config_from_args(args)
        now_dt = parse_iso(now_str)
        assert now_dt is not None
        run_bucket = run_bucket_from_iso(now_str)

        previous_state = load_state()
        items = build_items(now_dt, previous_state, config, run_bucket, identity_mode=identity_mode)
        shadow_state = json.loads(json.dumps(previous_state))
        state = update_state(previous_state, items, now_str, run_bucket, identity_mode=identity_mode)
        budget_summary = build_hot_context_budget_summary(items)
        state["budget_summary"] = budget_summary
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")
        REPORT_PATH.write_text(build_report(items, state, config, shadow_state=shadow_state, run_bucket=run_bucket, budget_summary=budget_summary))
        envelope.add_artifact(STATE_PATH)
        envelope.add_artifact(REPORT_PATH)

        if args.cmd == "apply":
            manifest = apply_pruning(
                items,
                args.stamp,
                local_compression_config_from_args(args),
                dry_run=bool(getattr(args, "dry_run", False)),
                identity_mode=identity_mode,
                max_file_shrink_ratio=float(getattr(args, "max_file_shrink_ratio", DEFAULT_MAX_FILE_SHRINK_RATIO)),
                allow_large_shrink=bool(getattr(args, "allow_large_shrink", False)),
            )
            manifest["run"] = envelope_ref(envelope)
            envelope.write_artifact("apply-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            status_word = "DRY_RUN_OK" if getattr(args, "dry_run", False) else "APPLY_OK"
            summary_line = f"CONTEXT_PRUNE_{status_word} identity={identity_mode} files={len(manifest.get('files', []))} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary_line, returncode=0)
            print(json.dumps(manifest, indent=2))
        else:
            summary = {
                "items": len(items),
                "identityMode": identity_mode,
                "review": sum(1 for i in items if i.classification == "review"),
                "prune_candidate": sum(1 for i in items if i.classification == "prune_candidate"),
                "budget_summary": budget_summary,
                "report": str(REPORT_PATH),
                "state": str(STATE_PATH),
                "run": envelope_ref(envelope),
            }
            summary_line = f"CONTEXT_PRUNE_AUDIT_OK identity={identity_mode} review={summary['review']} prune={summary['prune_candidate']} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary_line, returncode=0)
            print(json.dumps(summary, indent=2))
        return 0
    except Exception as exc:
        summary_line = f"CONTEXT_PRUNE_BLOCKED {type(exc).__name__}: {exc} run={envelope_ref(envelope)}"
        envelope.finish(status="blocked", summary_line=summary_line, error=exc, returncode=1)
        print(summary_line)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
