#!/usr/bin/env python3
"""Materialize script invocation usage evidence.

Phase C1 added a tolerant JSONL ledger parser. Phase C2 joins parsed usage
against the conservative script-classification inventory and marks missing usage
as `pre_instrumentation_unknown` by default. Phase C3 adds an independent
filesystem scan and inventory-scope review. Phase C4 adds scheduler, docs, and
runtime-log reference evidence as conservative positive-use/retention signals.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

MAINTENANCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("ORCHESTRATOR_REPO_ROOT", "/Users/agent2/.openclaw/orchestrator")).resolve()
OPENCLAW_ROOT = REPO_ROOT.parent
GENERATED_DIR = MAINTENANCE_DIR / "generated"
DEFAULT_LEDGER_DIR = REPO_ROOT / "scripts" / ".runtime-state" / "script-invocations"
DEFAULT_CLASSIFICATION_JSON = GENERATED_DIR / "script-classification.json"
DEFAULT_OUTPUT_JSON = GENERATED_DIR / "script-usage-summary.json"
DEFAULT_OUTPUT_MD = GENERATED_DIR / "script-usage-summary.md"
C1_OUTPUT_JSON = GENERATED_DIR / "script-usage-ledger-c1-summary.json"
C1_OUTPUT_MD = GENERATED_DIR / "script-usage-ledger-c1-summary.md"
DEFAULT_CRON_JOBS_JSON = OPENCLAW_ROOT / "cron" / "jobs.json"
DEFAULT_LAUNCHD_ROOT = REPO_ROOT / "scripts" / "launchd"
SCHEMA_VERSION = "openclaw-script-usage-ledger-parser/v1"
JOINED_SCHEMA_VERSION = "openclaw-script-usage-summary/v1"
LEDGER_SCHEMA_VERSION = "script-invocation/v1"
SCRIPT_EXTENSIONS = {".py", ".mjs", ".js", ".sh"}
REFERENCE_TEXT_EXTENSIONS = {".md", ".txt", ".json", ".plist", ".log", ".out", ".err"}
INVENTORY_SKIP_PARTS = {
    ".git",
    "__pycache__",
    ".runtime-state",
    "generated",
    "artifacts",
    ".obsidian",
    "node_modules",
    ".venv",
    "venv",
    "site-packages",
}
DEFAULT_INVENTORY_SCAN_ROOT = OPENCLAW_ROOT
DEFAULT_INVENTORY_SKIP_ROOTS = [
    OPENCLAW_ROOT / "workbench",
    OPENCLAW_ROOT / "tmp",
    OPENCLAW_ROOT / "tmp-play",
    OPENCLAW_ROOT / "service-env",
    REPO_ROOT / "tmp",
    REPO_ROOT / "tmp-play",
]
DEFAULT_APPROVED_SCRIPT_ROOTS = [
    REPO_ROOT / "scripts",
    REPO_ROOT / "roles",
    REPO_ROOT / "runtime",
    REPO_ROOT / "quant-db/scripts",
    REPO_ROOT / "qualitative-db/scripts",
    OPENCLAW_ROOT / "decision-maker",
    OPENCLAW_ROOT / "evaluator",
    OPENCLAW_ROOT / "device-b/scripts",
    OPENCLAW_ROOT / "maintenance/runtime",
]
DEFAULT_DOC_REFERENCE_ROOTS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "TOOLS.md",
    REPO_ROOT / "scripts" / "launchd" / "README.md",
    REPO_ROOT / "runtime" / "researchers-swarm-subagents" / "README.md",
    REPO_ROOT / "runtime" / "synthesis-subagent" / "README.md",
    REPO_ROOT / "evaluator" / "runtime" / "scripts" / "README.md",
    OPENCLAW_ROOT / "decision-maker" / "README.md",
    OPENCLAW_ROOT / "decision-maker" / "AGENTS.md",
    OPENCLAW_ROOT / "evaluator" / "README.md",
    OPENCLAW_ROOT / "evaluator" / "AGENTS.md",
    OPENCLAW_ROOT / "maintenance" / "AGENTS.md",
    OPENCLAW_ROOT / "maintenance" / "TOOLS.md",
    OPENCLAW_ROOT / "maintenance" / "context",
]
DEFAULT_RUNTIME_LOG_ROOTS = [
    REPO_ROOT / "scripts" / ".runtime-state" / "launchd",
    REPO_ROOT / "scripts" / ".runtime-state" / "learning-maintenance",
    REPO_ROOT / "scripts" / ".runtime-state" / "lmd-causal-maintenance",
    REPO_ROOT / "runtime" / "researchers-swarm-subagents" / ".runtime-state",
    REPO_ROOT / "runtime" / "synthesis-subagent" / ".runtime-state",
]


@dataclass
class ParseIssue:
    shard: str
    line: int
    kind: str
    message: str


@dataclass
class ParsedLedger:
    ledger_dir: str
    shards: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    total_lines: int = 0


@dataclass
class ScriptUsage:
    script: str
    start_count: int = 0
    finish_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    exception_count: int = 0
    last_started_at: Optional[str] = None
    last_finished_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    trigger_counts: dict[str, int] = field(default_factory=dict)
    parent_callers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceEvidence:
    source_kind: str
    source_path: str
    match: str
    line: int | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def max_iso(existing: Optional[str], candidate: Any) -> Optional[str]:
    candidate_dt = parse_ts(candidate)
    if candidate_dt is None:
        return existing
    existing_dt = parse_ts(existing) if existing else None
    if existing_dt is None or candidate_dt > existing_dt:
        return candidate_dt.isoformat().replace("+00:00", "Z")
    return existing


def ledger_shards(ledger_dir: Path) -> list[Path]:
    if not ledger_dir.exists():
        return []
    return sorted(path for path in ledger_dir.glob("*.jsonl") if path.is_file())


def parse_ledger_dir(ledger_dir: Path) -> ParsedLedger:
    parsed = ParsedLedger(ledger_dir=str(ledger_dir))
    for shard in ledger_shards(ledger_dir):
        parsed.shards.append(shard.name)
        try:
            lines = shard.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            parsed.issues.append(ParseIssue(shard=shard.name, line=0, kind="read_error", message=str(exc)))
            continue
        for index, raw in enumerate(lines, 1):
            parsed.total_lines += 1
            if not raw.strip():
                parsed.issues.append(ParseIssue(shard=shard.name, line=index, kind="blank_line", message="blank JSONL row"))
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                parsed.issues.append(ParseIssue(shard=shard.name, line=index, kind="malformed_json", message=str(exc)))
                continue
            if not isinstance(row, dict):
                parsed.issues.append(ParseIssue(shard=shard.name, line=index, kind="non_object_row", message=f"row type {type(row).__name__}"))
                continue
            if row.get("schema_version") != LEDGER_SCHEMA_VERSION:
                parsed.issues.append(ParseIssue(shard=shard.name, line=index, kind="unexpected_schema", message=str(row.get("schema_version"))))
                continue
            script = row.get("script")
            event = row.get("event")
            if not isinstance(script, str) or not script.strip():
                parsed.issues.append(ParseIssue(shard=shard.name, line=index, kind="missing_script", message="row has no script"))
                continue
            if event not in {"start", "finish"}:
                parsed.issues.append(ParseIssue(shard=shard.name, line=index, kind="unexpected_event", message=str(event)))
                continue
            parsed.events.append(row)
    return parsed


def finish_is_success(row: dict[str, Any]) -> bool:
    return row.get("event") == "finish" and row.get("exit_code") == 0 and row.get("status") in {"completed", "system_exit"}


def finish_is_failure(row: dict[str, Any]) -> bool:
    if row.get("event") != "finish":
        return False
    if finish_is_success(row):
        return False
    status = row.get("status")
    exit_code = row.get("exit_code")
    return status in {"exception", "keyboard_interrupt", "timeout", "called_process_error"} or exit_code not in (0, None)


def bump(mapping: dict[str, int], key: str) -> None:
    mapping[key] = int(mapping.get(key) or 0) + 1


def append_unique(values: list[str], value: Any) -> None:
    if isinstance(value, str) and value and value not in values:
        values.append(value)


def ledger_script_is_external_command(script: str, classifier_paths: set[str]) -> bool:
    value = script.strip()
    if not value or value in classifier_paths:
        return False
    path = Path(value)
    if path.is_absolute() and not is_relative_to(path, OPENCLAW_ROOT) and not is_relative_to(path, REPO_ROOT):
        return True
    return "/" not in value and "\\" not in value and path.suffix == ""


def summarize_events(events: Iterable[dict[str, Any]]) -> dict[str, ScriptUsage]:
    summaries: dict[str, ScriptUsage] = {}
    for row in events:
        script = str(row["script"])
        summary = summaries.setdefault(script, ScriptUsage(script=script))
        event = row.get("event")
        ts = row.get("ts")
        if event == "start":
            summary.start_count += 1
            summary.last_started_at = max_iso(summary.last_started_at, ts)
        elif event == "finish":
            summary.finish_count += 1
            summary.last_finished_at = max_iso(summary.last_finished_at, ts)
            if finish_is_success(row):
                summary.success_count += 1
                summary.last_success_at = max_iso(summary.last_success_at, ts)
            elif finish_is_failure(row):
                summary.failure_count += 1
                summary.last_failure_at = max_iso(summary.last_failure_at, ts)
            if row.get("status") == "timeout":
                summary.timeout_count += 1
            if row.get("status") in {"exception", "keyboard_interrupt", "called_process_error"}:
                summary.exception_count += 1
        trigger = row.get("trigger")
        bump(summary.trigger_counts, trigger if isinstance(trigger, str) and trigger else "unknown")
        append_unique(summary.parent_callers, row.get("parent_script"))
    return summaries


def ledger_summary_dict(parsed: ParsedLedger, script_summaries: dict[str, ScriptUsage]) -> dict[str, int]:
    return {
        "shard_count": len(parsed.shards),
        "total_lines": parsed.total_lines,
        "parsed_event_count": len(parsed.events),
        "parse_issue_count": len(parsed.issues),
        "script_count": len(script_summaries),
        "start_count": sum(item.start_count for item in script_summaries.values()),
        "finish_count": sum(item.finish_count for item in script_summaries.values()),
        "success_count": sum(item.success_count for item in script_summaries.values()),
        "failure_count": sum(item.failure_count for item in script_summaries.values()),
    }


def build_summary(ledger_dir: Path) -> dict[str, Any]:
    parsed = parse_ledger_dir(ledger_dir)
    script_summaries = summarize_events(parsed.events)
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "C1",
        "generated_at_utc": utc_now_iso(),
        "ledger_dir": str(ledger_dir),
        "parser_scope": "ledger_jsonl_only_no_classifier_join",
        "summary": ledger_summary_dict(parsed, script_summaries),
        "shards": parsed.shards,
        "issues": [asdict(issue) for issue in parsed.issues],
        "scripts": [asdict(script_summaries[script]) for script in sorted(script_summaries)],
    }


def load_classifier_records(classification_json: Path) -> list[dict[str, Any]]:
    payload = json.loads(classification_json.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError(f"{classification_json} does not contain a records list")
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"classifier record {index} is not an object")
        path = record.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"classifier record {index} has no path")
        output.append(record)
    return output


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def normalize_inventory_path(path: Path, scan_root: Path) -> str:
    resolved = path.resolve()
    roots = [REPO_ROOT]
    if scan_root.resolve() != OPENCLAW_ROOT.resolve():
        roots.append(scan_root.resolve())
    roots.append(OPENCLAW_ROOT)
    for root in roots:
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def inventory_is_skipped(path: Path) -> bool:
    return any(part in INVENTORY_SKIP_PARTS for part in path.parts) or any(
        is_relative_to(path, root) for root in DEFAULT_INVENTORY_SKIP_ROOTS
    )


def has_script_shebang(path: Path) -> bool:
    if path.suffix:
        return False
    try:
        first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError, UnicodeDecodeError):
        return False
    lower = first_line.lower()
    return lower.startswith("#!") and any(token in lower for token in ["python", "bash", " sh", "/sh", "node", "env"])


def is_script_like_file(path: Path) -> bool:
    return path.is_file() and (path.suffix in SCRIPT_EXTENSIONS or has_script_shebang(path))


def iter_inventory_script_files(scan_root: Path) -> list[Path]:
    root = scan_root.resolve()
    if not root.exists():
        return []
    if root.is_file():
        return [root] if is_script_like_file(root) else []
    files: list[Path] = []
    for path in root.rglob("*"):
        if inventory_is_skipped(path):
            continue
        if is_script_like_file(path):
            files.append(path)
    return sorted(files, key=lambda item: normalize_inventory_path(item, root))


def inventory_scope_for(path: Path, approved_roots: list[Path]) -> str:
    resolved = path.resolve()
    return "approved_root" if any(is_relative_to(resolved, root) for root in approved_roots) else "outside_approved_roots"


def build_inventory_scope_review(
    classifier_records: list[dict[str, Any]],
    scan_root: Path = DEFAULT_INVENTORY_SCAN_ROOT,
    approved_roots: Optional[list[Path]] = None,
) -> dict[str, Any]:
    roots = [root.resolve() for root in (approved_roots or DEFAULT_APPROVED_SCRIPT_ROOTS)]
    files = iter_inventory_script_files(scan_root)
    classifier_paths = {str(record["path"]) for record in classifier_records}
    file_records: list[dict[str, Any]] = []
    file_paths: set[str] = set()
    for path in files:
        normalized = normalize_inventory_path(path, scan_root)
        scope = inventory_scope_for(path, roots)
        file_paths.add(normalized)
        file_records.append({
            "path": normalized,
            "extension": path.suffix,
            "inventory_scope": scope,
            "in_classifier": normalized in classifier_paths,
        })

    outside = [item for item in file_records if item["inventory_scope"] == "outside_approved_roots"]
    unclassified_approved = [
        item for item in file_records
        if item["inventory_scope"] == "approved_root" and not item["in_classifier"]
    ]
    classified_missing = sorted(path for path in classifier_paths if path not in file_paths)
    return {
        "scan_root": str(scan_root.resolve()),
        "approved_roots": [str(root) for root in roots],
        "script_like_file_count": len(file_records),
        "approved_script_like_file_count": sum(1 for item in file_records if item["inventory_scope"] == "approved_root"),
        "outside_approved_roots_count": len(outside),
        "unclassified_approved_scope_count": len(unclassified_approved),
        "classified_missing_from_filesystem_count": len(classified_missing),
        "outside_approved_roots": sorted(outside, key=lambda item: str(item["path"])),
        "unclassified_approved_scope": sorted(unclassified_approved, key=lambda item: str(item["path"])),
        "classified_missing_from_filesystem": classified_missing,
    }


def rel_display_path(path: Path) -> str:
    resolved = path.resolve()
    for root in [OPENCLAW_ROOT, REPO_ROOT, MAINTENANCE_DIR.parent]:
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def iter_reference_files(roots: Iterable[Path], extensions: set[str] = REFERENCE_TEXT_EXTENSIONS) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix in extensions:
                files.append(root)
            continue
        for path in root.rglob("*"):
            if any(part in INVENTORY_SKIP_PARTS for part in path.parts):
                continue
            if path.is_file() and path.suffix in extensions:
                files.append(path)
    return sorted(set(files), key=lambda item: rel_display_path(item))


def line_number_for_match(text: str, needle: str) -> int | None:
    index = text.find(needle)
    if index < 0:
        return None
    return text.count("\n", 0, index) + 1


def script_match_tokens(record: dict[str, Any]) -> list[str]:
    path = str(record.get("path") or "")
    name = str(record.get("name") or Path(path).name)
    tokens = [path]
    if name and name != path:
        tokens.append(name)
    return [token for token in tokens if token]


def contains_token(text: str, token: str) -> bool:
    if "/" in token:
        return token in text
    return re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w.-])", text) is not None


def collect_text_reference_evidence(
    records: list[dict[str, Any]],
    files: Iterable[Path],
    source_kind: str,
    max_matches_per_script: int = 8,
) -> dict[str, list[ReferenceEvidence]]:
    evidence: dict[str, list[ReferenceEvidence]] = {str(record["path"]): [] for record in records}
    texts: list[tuple[Path, str]] = []
    for file_path in files:
        try:
            texts.append((file_path, file_path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    for record in records:
        path = str(record["path"])
        matches = evidence[path]
        for token in script_match_tokens(record):
            for file_path, text in texts:
                if len(matches) >= max_matches_per_script:
                    break
                if contains_token(text, token):
                    matches.append(
                        ReferenceEvidence(
                            source_kind=source_kind,
                            source_path=rel_display_path(file_path),
                            match=token,
                            line=line_number_for_match(text, token),
                        )
                    )
            if len(matches) >= max_matches_per_script:
                break
    return {path: items for path, items in evidence.items() if items}


def collect_cron_reference_evidence(
    records: list[dict[str, Any]],
    cron_json: Path = DEFAULT_CRON_JOBS_JSON,
) -> dict[str, list[ReferenceEvidence]]:
    if not cron_json.exists():
        return {}
    try:
        payload = json.loads(cron_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return {}
    by_path: dict[str, list[ReferenceEvidence]] = {}
    for record in records:
        path = str(record["path"])
        tokens = script_match_tokens(record)
        for index, job in enumerate(jobs):
            if not isinstance(job, dict):
                continue
            rendered = json.dumps(job, sort_keys=True)
            if any(contains_token(rendered, token) for token in tokens):
                job_name = job.get("name") or job.get("id") or f"job[{index}]"
                by_path.setdefault(path, []).append(
                    ReferenceEvidence(
                        source_kind="cron",
                        source_path=rel_display_path(cron_json),
                        match=str(job_name),
                        line=None,
                    )
                )
    return by_path


def merge_reference_indexes(*indexes: dict[str, list[ReferenceEvidence]]) -> dict[str, list[ReferenceEvidence]]:
    merged: dict[str, list[ReferenceEvidence]] = {}
    seen: set[tuple[str, str, str, str, int | None]] = set()
    for index in indexes:
        for path, items in index.items():
            for item in items:
                key = (path, item.source_kind, item.source_path, item.match, item.line)
                if key in seen:
                    continue
                seen.add(key)
                merged.setdefault(path, []).append(item)
    return merged


def build_reference_evidence(
    classifier_records: list[dict[str, Any]],
    cron_json: Path = DEFAULT_CRON_JOBS_JSON,
    launchd_root: Path = DEFAULT_LAUNCHD_ROOT,
    doc_roots: Optional[list[Path]] = None,
    runtime_log_roots: Optional[list[Path]] = None,
) -> dict[str, list[ReferenceEvidence]]:
    launchd_files = iter_reference_files([launchd_root], {".plist"})
    doc_files = iter_reference_files(doc_roots or DEFAULT_DOC_REFERENCE_ROOTS)
    log_files = iter_reference_files(runtime_log_roots or DEFAULT_RUNTIME_LOG_ROOTS, {".log", ".out", ".err", ".json", ".jsonl", ".txt"})
    return merge_reference_indexes(
        collect_cron_reference_evidence(classifier_records, cron_json),
        collect_text_reference_evidence(classifier_records, launchd_files, "launchd"),
        collect_text_reference_evidence(classifier_records, doc_files, "operator_docs"),
        collect_text_reference_evidence(classifier_records, log_files, "runtime_logs"),
    )


def reference_summary(reference_evidence: dict[str, list[ReferenceEvidence]]) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    script_paths: dict[str, set[str]] = {}
    for path, items in reference_evidence.items():
        for item in items:
            source_counts[item.source_kind] = source_counts.get(item.source_kind, 0) + 1
            script_paths.setdefault(item.source_kind, set()).add(path)
    return {
        "referenced_script_count": len(reference_evidence),
        "reference_count_by_source": dict(sorted(source_counts.items())),
        "referenced_script_count_by_source": {key: len(value) for key, value in sorted(script_paths.items())},
    }


def empty_usage(path: str) -> ScriptUsage:
    return ScriptUsage(script=path)


def usage_to_joined_record(
    record: dict[str, Any],
    usage: ScriptUsage | None,
    filesystem_present: bool = True,
    inventory_scope: str = "approved_root",
    references: Optional[list[ReferenceEvidence]] = None,
) -> dict[str, Any]:
    usage = usage or empty_usage(str(record["path"]))
    references = references or []
    observed = usage.start_count > 0 or usage.finish_count > 0
    source_kinds = sorted({item.source_kind for item in references})
    scheduler_or_log_observed = any(kind in {"cron", "launchd", "runtime_logs"} for kind in source_kinds)
    evidence_sources = ["static_inventory"]
    blockers: list[str] = []
    if observed:
        evidence_sources.append("ledger")
        coverage_status = "direct"
    elif scheduler_or_log_observed:
        coverage_status = "parent_observed"
        blockers.extend([
            "no_observed_ledger_usage",
            "coverage_window_not_mature",
        ])
    else:
        coverage_status = "pre_instrumentation_unknown"
        blockers.extend([
            "pre_instrumentation_unknown",
            "no_observed_ledger_usage",
            "coverage_window_not_mature",
        ])
    evidence_sources.extend(kind for kind in source_kinds if kind not in evidence_sources)
    if int(record.get("inbound_reference_count") or 0) > 0:
        blockers.append("has_static_inbound_references")
    if "cron" in source_kinds:
        blockers.append("has_cron_reference")
    if "launchd" in source_kinds:
        blockers.append("has_launchd_reference")
    if "operator_docs" in source_kinds:
        blockers.append("has_operator_doc_reference")
    if "runtime_logs" in source_kinds:
        blockers.append("has_runtime_log_reference")
    if coverage_status == "direct":
        evidence_refresh_action = {
            "action": "retain_observed_script",
            "owner_lane": "Maintenance: Orchestrator Script Evidence Refresh",
            "autonomous": True,
            "mutating": False,
            "command": "python3 run_scheduled_maintenance.py --mode script-evidence-refresh",
            "reason": "direct invocation ledger evidence exists",
        }
    elif coverage_status == "parent_observed":
        evidence_refresh_action = {
            "action": "continue_observation_until_mature",
            "owner_lane": "Maintenance: Orchestrator Script Evidence Refresh",
            "autonomous": True,
            "mutating": False,
            "command": "python3 run_scheduled_maintenance.py --mode script-evidence-refresh",
            "reason": "scheduler, launchd, docs, or runtime-log evidence exists but direct ledger evidence is not mature",
        }
    else:
        evidence_refresh_action = {
            "action": "refresh_static_scheduler_doc_runtime_and_ledger_evidence",
            "owner_lane": "Maintenance: Orchestrator Script Evidence Refresh",
            "autonomous": True,
            "mutating": False,
            "command": "python3 run_scheduled_maintenance.py --mode script-evidence-refresh",
            "reason": "script is still pre-instrumentation unknown",
        }
    return {
        "path": record["path"],
        "name": record.get("name"),
        "classification": record.get("classification"),
        "confidence": record.get("confidence"),
        "inbound_reference_count": record.get("inbound_reference_count", 0),
        "filesystem_present": filesystem_present,
        "inventory_scope": inventory_scope,
        "instrumented": observed,
        "coverage_status": coverage_status,
        "first_observed_start_at": None,  # C2 has no first-seen persistence yet; C3/D3 will add maturity windows.
        "last_observed_start_at": usage.last_started_at,
        "last_observed_finish_at": usage.last_finished_at,
        "last_success_at": usage.last_success_at,
        "last_failure_at": usage.last_failure_at,
        "run_count_total": usage.finish_count,
        "start_count": usage.start_count,
        "finish_count": usage.finish_count,
        "success_count": usage.success_count,
        "failure_count": usage.failure_count,
        "timeout_count": usage.timeout_count,
        "exception_count": usage.exception_count,
        "trigger_counts": dict(sorted(usage.trigger_counts.items())),
        "parent_callers": sorted(usage.parent_callers),
        "reference_evidence": [asdict(item) for item in references],
        "evidence_sources": evidence_sources,
        "cleanup_eligibility_blockers": blockers,
        "evidence_refresh_action": evidence_refresh_action,
    }


def build_joined_summary(
    ledger_dir: Path,
    classification_json: Path,
    inventory_scan_root: Path = DEFAULT_INVENTORY_SCAN_ROOT,
    approved_roots: Optional[list[Path]] = None,
) -> dict[str, Any]:
    parsed = parse_ledger_dir(ledger_dir)
    usage_by_script = summarize_events(parsed.events)
    classifier_records = load_classifier_records(classification_json)
    classifier_paths = {str(record["path"]) for record in classifier_records}
    inventory_review = build_inventory_scope_review(classifier_records, inventory_scan_root, approved_roots)
    references_by_script = build_reference_evidence(classifier_records)
    reference_counts = reference_summary(references_by_script)
    filesystem_paths = {
        str(item["path"]): item
        for bucket in ["outside_approved_roots", "unclassified_approved_scope"]
        for item in inventory_review[bucket]
    }
    # Re-scan approved/classified files too so joined records can carry presence/scope without bloating the report.
    for path in iter_inventory_script_files(inventory_scan_root):
        normalized = normalize_inventory_path(path, inventory_scan_root)
        if normalized in classifier_paths and normalized not in filesystem_paths:
            filesystem_paths[normalized] = {
                "path": normalized,
                "inventory_scope": inventory_scope_for(path, [root.resolve() for root in (approved_roots or DEFAULT_APPROVED_SCRIPT_ROOTS)]),
                "in_classifier": True,
            }
    joined = [
        usage_to_joined_record(
            record,
            usage_by_script.get(str(record["path"])),
            filesystem_present=str(record["path"]) in filesystem_paths,
            inventory_scope=str(filesystem_paths.get(str(record["path"]), {}).get("inventory_scope") or "missing_from_filesystem"),
            references=references_by_script.get(str(record["path"]), []),
        )
        for record in classifier_records
    ]
    external_ledger_commands = [
        script
        for script in sorted(usage_by_script)
        if script not in classifier_paths and ledger_script_is_external_command(script, classifier_paths)
    ]
    external_command_set = set(external_ledger_commands)
    unmatched_ledger_scripts = [
        script
        for script in sorted(usage_by_script)
        if script not in classifier_paths and script not in external_command_set
    ]
    observed_joined_count = sum(1 for item in joined if item["coverage_status"] == "direct")
    parent_observed_count = sum(1 for item in joined if item["coverage_status"] == "parent_observed")
    pre_unknown_count = sum(1 for item in joined if item["coverage_status"] == "pre_instrumentation_unknown")
    return {
        "schema_version": JOINED_SCHEMA_VERSION,
        "phase": "C4",
        "generated_at_utc": utc_now_iso(),
        "ledger_dir": str(ledger_dir),
        "classification_json": str(classification_json),
        "parser_scope": "ledger_jsonl_with_classifier_join_inventory_scheduler_docs_logs",
        "coverage_default_for_missing_usage": "pre_instrumentation_unknown",
        "ledger_summary": ledger_summary_dict(parsed, usage_by_script),
        "summary": {
            "classified_script_count": len(classifier_records),
            "observed_classified_script_count": observed_joined_count,
            "parent_observed_script_count": parent_observed_count,
            "pre_instrumentation_unknown_count": pre_unknown_count,
            "unmatched_ledger_script_count": len(unmatched_ledger_scripts),
            "external_ledger_command_count": len(external_ledger_commands),
            "parse_issue_count": len(parsed.issues),
            "outside_approved_roots_count": inventory_review["outside_approved_roots_count"],
            "unclassified_approved_scope_count": inventory_review["unclassified_approved_scope_count"],
            "classified_missing_from_filesystem_count": inventory_review["classified_missing_from_filesystem_count"],
            **reference_counts,
        },
        "shards": parsed.shards,
        "issues": [asdict(issue) for issue in parsed.issues],
        "inventory_scope_review": inventory_review,
        "reference_evidence_summary": reference_counts,
        "scripts": sorted(joined, key=lambda item: str(item["path"])),
        "unmatched_ledger_scripts": [asdict(usage_by_script[script]) for script in unmatched_ledger_scripts],
        "external_ledger_commands": [asdict(usage_by_script[script]) for script in external_ledger_commands],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    if payload.get("phase") in {"C2", "C3", "C4"}:
        return render_joined_markdown(payload)
    summary = payload["summary"]
    lines = [
        "# Script Usage Ledger C1 Summary",
        "",
        f"Generated: `{payload['generated_at_utc']}`",
        f"Ledger dir: `{payload['ledger_dir']}`",
        "",
        "## Counts",
        "",
        f"- Shards: {summary['shard_count']}",
        f"- Parsed events: {summary['parsed_event_count']} / {summary['total_lines']} lines",
        f"- Parse issues: {summary['parse_issue_count']}",
        f"- Scripts observed: {summary['script_count']}",
        f"- Start / finish: {summary['start_count']} / {summary['finish_count']}",
        f"- Success / failure: {summary['success_count']} / {summary['failure_count']}",
        "",
        "## Observed scripts",
        "",
    ]
    scripts = payload.get("scripts") or []
    if not scripts:
        lines.append("_No valid script invocation rows observed._")
    else:
        for item in scripts:
            lines.append(
                f"- `{item['script']}` — start {item['start_count']}, finish {item['finish_count']}, "
                f"success {item['success_count']}, failure {item['failure_count']}"
            )
    lines.append("")
    return "\n".join(lines)


def render_joined_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    ledger_summary = payload["ledger_summary"]
    lines = [
        "# Script Usage Summary",
        "",
        f"Generated: `{payload['generated_at_utc']}`",
        f"Ledger dir: `{payload['ledger_dir']}`",
        f"Classifier: `{payload['classification_json']}`",
        "",
        "## Counts",
        "",
        f"- Classified scripts: {summary['classified_script_count']}",
        f"- Observed classified scripts: {summary['observed_classified_script_count']}",
        f"- Scheduler/log observed (non-ledger): {summary.get('parent_observed_script_count', 0)}",
        f"- Pre-instrumentation unknown: {summary['pre_instrumentation_unknown_count']}",
        f"- Unmatched ledger scripts: {summary['unmatched_ledger_script_count']}",
        f"- External ledger commands: {summary.get('external_ledger_command_count', 0)}",
        f"- Outside approved roots: {summary.get('outside_approved_roots_count', 0)}",
        f"- Unclassified approved-scope files: {summary.get('unclassified_approved_scope_count', 0)}",
        f"- Classified missing from filesystem: {summary.get('classified_missing_from_filesystem_count', 0)}",
        f"- Scripts with C4 references: {summary.get('referenced_script_count', 0)}",
        f"- Parsed ledger events: {ledger_summary['parsed_event_count']} / {ledger_summary['total_lines']} lines",
        f"- Parse issues: {summary['parse_issue_count']}",
        "",
        "## Observed classified scripts",
        "",
    ]
    observed = [item for item in payload.get("scripts", []) if item.get("coverage_status") == "direct"]
    if not observed:
        lines.append("_No classified scripts have direct ledger usage yet._")
    else:
        for item in observed:
            lines.append(
                f"- `{item['path']}` — runs {item['run_count_total']}, success {item['success_count']}, "
                f"failure {item['failure_count']}, triggers {item['trigger_counts']}"
            )
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_json: Path, output_md: Optional[Path]) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse script invocation ledger JSONL shards and summarize observed usage")
    parser.add_argument("--ledger-dir", default=str(DEFAULT_LEDGER_DIR))
    parser.add_argument("--classification-json", default=str(DEFAULT_CLASSIFICATION_JSON))
    parser.add_argument("--inventory-scan-root", default=str(DEFAULT_INVENTORY_SCAN_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--ledger-only", action="store_true", help="Emit the C1 ledger-only parser summary instead of the C2 classifier join")
    parser.add_argument("--no-markdown", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger_dir = Path(args.ledger_dir).expanduser().resolve()
    if args.ledger_only:
        payload = build_summary(ledger_dir)
        output_json_arg = str(C1_OUTPUT_JSON) if args.output_json == str(DEFAULT_OUTPUT_JSON) else args.output_json
        output_md_arg = str(C1_OUTPUT_MD) if args.output_md == str(DEFAULT_OUTPUT_MD) else args.output_md
    else:
        payload = build_joined_summary(
            ledger_dir,
            Path(args.classification_json).expanduser().resolve(),
            Path(args.inventory_scan_root).expanduser().resolve(),
        )
        output_json_arg = args.output_json
        output_md_arg = args.output_md
    output_json = Path(output_json_arg).expanduser().resolve()
    output_md = None if args.no_markdown else Path(output_md_arg).expanduser().resolve()
    write_outputs(payload, output_json, output_md)
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
