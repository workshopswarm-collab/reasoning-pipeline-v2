#!/usr/bin/env python3
"""Deterministically classify Orchestrator script surfaces.

This is intentionally conservative. It classifies by path, filename patterns,
static inbound references, Python import references, launchd references, and
known runtime entrypoint names. A file with no inbound reference is a review
candidate, not automatically unused.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

MAINTENANCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("ORCHESTRATOR_REPO_ROOT", "/Users/agent2/.openclaw/orchestrator")).resolve()
OPENCLAW_ROOT = REPO_ROOT.parent
GENERATED_DIR = MAINTENANCE_DIR / "generated"

SCAN_ROOTS = [
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
TEXT_ROOTS = [
    REPO_ROOT / "scripts",
    REPO_ROOT / "roles",
    REPO_ROOT / "runtime",
    REPO_ROOT / "quant-db",
    OPENCLAW_ROOT / "decision-maker",
    OPENCLAW_ROOT / "evaluator",
    OPENCLAW_ROOT / "device-b/scripts",
    OPENCLAW_ROOT / "maintenance/runtime",
    # Keep this fast and source-oriented. qualitative-db case artifacts are huge
    # and not authoritative for code references; add targeted docs here if needed.
    REPO_ROOT / "README.md",
    REPO_ROOT / "AGENTS.md",
]
SCRIPT_EXTENSIONS = {".py", ".mjs", ".js", ".sh"}
TEXT_EXTENSIONS = {".py", ".mjs", ".js", ".sh", ".md", ".sql", ".plist", ".toml", ".yml", ".yaml"}
SKIP_PARTS = {
    ".git",
    "__pycache__",
    ".runtime-state",
    "generated",
    "artifacts",
    ".obsidian",
    "node_modules",
}
KNOWN_ACTIVE_ENTRYPOINTS = {
    "run_sequential_market_pipeline.py",
    "watch_pipeline.py",
    "check_pipeline_health.py",
    "watch_decided_market_prices.py",
    "automation_planes.py",
    "pipeline_automation_actions.py",
    "manual_batch_controller.py",
    "prepare_and_launch_headless_telegram_dispatch.py",
    "run_telegram_swarm_runtime_loop.py",
    "reconcile_swarm_stage.py",
    "resume_swarm_stage.py",
    "reconcile_research_run_completion.py",
    "dispatch_case_research.py",
    "select_next_market.py",
    "select_refresh_case.py",
    "create_research_run.py",
    "kickoff_synthesis_after_swarm.py",
    "launch_synthesis_if_ready.py",
    "run_synthesis_executor.py",
    "run_decision_maker.py",
    "run_light_refresh_update.py",
    "reconcile_decision_stage.py",
    "finalize_decision_stage.py",
    "run_resolved_case_learning_sync.py",
    "run_evaluator_learning_maintenance_cycle.py",
    "run_lmd_causal_maintenance_cycle.py",
    "sync_polymarket_market_resolutions.py",
    "score_brier.py",
    "persist_brier_history.py",
}
REPAIR_TOKENS = ("repair", "sweep_stale", "canonicalize", "fixup", "cleanup")
BACKFILL_TOKENS = ("backfill", "migrate", "migration")
DIAGNOSTIC_TOKENS = ("replay", "audit", "query", "show", "status", "check", "validate", "probe")
REPORT_TOKENS = ("report", "materialize", "aggregate", "render", "scan")


@dataclass(frozen=True)
class Ref:
    path: str
    kind: str
    line: int | None = None


@dataclass
class ScriptRecord:
    path: str
    name: str
    extension: str
    line_count: int
    classification: str
    confidence: str
    inbound_reference_count: int
    inbound_reference_paths: list[str]
    evidence: list[str]
    risk_notes: list[str]


def is_skipped(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        pass
    try:
        return str(path.relative_to(OPENCLAW_ROOT))
    except ValueError:
        return str(path)


def iter_files(root: Path) -> list[Path]:
    full = root if root.is_absolute() else REPO_ROOT / root
    if not full.exists():
        return []
    if full.is_file():
        return [full]
    return [p for p in full.rglob("*") if p.is_file() and not is_skipped(p)]


def read_text(path: Path) -> str:
    return path.read_text(errors="ignore")


def script_files() -> list[Path]:
    files: set[Path] = set()
    for root in SCAN_ROOTS:
        for path in iter_files(root):
            if path.suffix in SCRIPT_EXTENSIONS:
                files.add(path)
    return sorted(files, key=lambda p: rel(p))


def text_corpus() -> list[tuple[Path, str]]:
    corpus: list[tuple[Path, str]] = []
    for root in TEXT_ROOTS:
        for path in iter_files(root):
            if path.suffix in TEXT_EXTENSIONS:
                corpus.append((path, read_text(path)))
    return corpus


def python_import_names(path: Path) -> set[str]:
    if path.suffix != ".py":
        return set()
    try:
        tree = ast.parse(read_text(path), filename=str(path))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[-1])
            for alias in node.names:
                if alias.name and alias.name != "*":
                    names.add(alias.name.split(".")[-1])
    return names


def inbound_refs(target: Path, corpus: list[tuple[Path, str]], import_index: dict[Path, set[str]]) -> list[Ref]:
    target_rel = rel(target)
    basename = target.name
    stem = target.stem
    refs: dict[tuple[str, str, int | None], Ref] = {}
    for source, text in corpus:
        if source == target:
            continue
        source_rel = rel(source)
        has_text_ref = basename in text or target_rel in text
        if has_text_ref:
            for idx, line in enumerate(text.splitlines(), 1):
                if basename in line or target_rel in line:
                    refs[(source_rel, "text", idx)] = Ref(source_rel, "text", idx)
        if target.suffix == ".py" and stem in import_index.get(source, set()):
            refs[(source_rel, "python_import", None)] = Ref(source_rel, "python_import", None)
    return sorted(refs.values(), key=lambda r: (r.path, r.kind, r.line or 0))


def classify(path: Path, refs: list[Ref], line_count: int) -> tuple[str, str, list[str], list[str]]:
    name = path.name
    path_text = rel(path)
    lower_name = name.lower()
    lower_path = path_text.lower()
    ref_count = len({r.path for r in refs})
    evidence: list[str] = []
    risk: list[str] = []

    if "/tests/" in f"/{path_text}" or name.startswith("test_"):
        evidence.append("test path/name")
        return "test_only", "high", evidence, risk

    if "launchd/" in lower_path or name.endswith(".plist"):
        evidence.append("launchd management/plist path")
        return "active_entrypoint", "high", evidence, risk

    if name in KNOWN_ACTIVE_ENTRYPOINTS:
        evidence.append("known pipeline entrypoint")
        if ref_count:
            evidence.append(f"{ref_count} inbound reference path(s)")
        return "active_entrypoint", "high", evidence, risk

    if any(token in lower_name for token in BACKFILL_TOKENS):
        evidence.append("backfill/migration filename token")
        if ref_count == 0:
            evidence.append("no inbound static references")
            risk.append("manual utility; verify DB state class before deleting")
            return "migration_backfill", "medium", evidence, risk
        evidence.append(f"{ref_count} inbound reference path(s)")
        return "migration_backfill", "high", evidence, risk

    if any(token in lower_name for token in REPAIR_TOKENS):
        evidence.append("repair/cleanup filename token")
        if ref_count == 0:
            evidence.append("no inbound static references")
            risk.append("manual repair utility; move to repair namespace before deletion")
            return "manual_repair", "medium", evidence, risk
        evidence.append(f"{ref_count} inbound reference path(s)")
        return "manual_repair", "high", evidence, risk

    if ref_count > 0:
        evidence.append(f"{ref_count} inbound reference path(s)")
        if any(token in lower_name for token in REPORT_TOKENS):
            return "report_or_materializer", "high", evidence, risk
        if any(token in lower_name for token in DIAGNOSTIC_TOKENS):
            return "diagnostic_or_status", "high", evidence, risk
        return "called_helper", "high", evidence, risk

    if any(token in lower_name for token in DIAGNOSTIC_TOKENS):
        evidence.append("diagnostic/status filename token")
        evidence.append("no inbound static references")
        return "diagnostic_harness", "medium", evidence, risk

    if path.suffix == ".py" and ("/lib/" in f"/{path_text}" or name in {"common.py", "validation.py", "status.py"}):
        evidence.append("library-like path/name")
        evidence.append("no inbound static references found by conservative scan")
        risk.append("may be imported dynamically or via sys.path in tests/scripts")
        return "unreferenced_library_review", "low", evidence, risk

    evidence.append("no inbound static references")
    risk.append("review candidate; static scan cannot see shell history/manual use")
    return "deprecated_candidate", "medium", evidence, risk


def build_records() -> tuple[list[ScriptRecord], dict[str, Any]]:
    scripts = script_files()
    corpus = text_corpus()
    import_index = {path: python_import_names(path) for path, _ in corpus if path.suffix == ".py"}
    records: list[ScriptRecord] = []
    for path in scripts:
        refs = inbound_refs(path, corpus, import_index)
        unique_ref_paths = sorted({r.path for r in refs})
        try:
            line_count = len(read_text(path).splitlines())
        except Exception:
            line_count = 0
        classification, confidence, evidence, risk_notes = classify(path, refs, line_count)
        records.append(
            ScriptRecord(
                path=rel(path),
                name=path.name,
                extension=path.suffix,
                line_count=line_count,
                classification=classification,
                confidence=confidence,
                inbound_reference_count=len(unique_ref_paths),
                inbound_reference_paths=unique_ref_paths[:25],
                evidence=evidence,
                risk_notes=risk_notes,
            )
        )
    summary: dict[str, Any] = {
        "generated_at": "deterministic",
        "repo_root": str(REPO_ROOT),
        "openclaw_root": str(OPENCLAW_ROOT),
        "script_count": len(records),
        "class_counts": {},
        "confidence_counts": {},
        "line_count": sum(r.line_count for r in records),
        "large_files_over_500_lines": sum(1 for r in records if r.line_count > 500),
        "large_files_over_1000_lines": sum(1 for r in records if r.line_count > 1000),
        "skip_parts": sorted(SKIP_PARTS),
    }
    for r in records:
        summary["class_counts"][r.classification] = summary["class_counts"].get(r.classification, 0) + 1
        summary["confidence_counts"][r.confidence] = summary["confidence_counts"].get(r.confidence, 0) + 1
    return records, summary


def render_markdown(records: list[ScriptRecord], summary: dict[str, Any]) -> str:
    by_class: dict[str, list[ScriptRecord]] = {}
    for record in records:
        by_class.setdefault(record.classification, []).append(record)

    lines: list[str] = []
    lines.append("# Script Classification")
    lines.append("")
    lines.append(f"Generated: `{summary['generated_at']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Script-like files scanned: **{summary['script_count']}**")
    lines.append(f"- Total script lines: **{summary['line_count']}**")
    lines.append(f"- Files >500 lines: **{summary['large_files_over_500_lines']}**")
    lines.append(f"- Files >1000 lines: **{summary['large_files_over_1000_lines']}**")
    lines.append("")
    lines.append("### Classification counts")
    lines.append("")
    for key, value in sorted(summary["class_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Review buckets")
    lines.append("")
    for bucket in ["deprecated_candidate", "manual_repair", "migration_backfill", "diagnostic_harness", "unreferenced_library_review"]:
        items = sorted(by_class.get(bucket, []), key=lambda r: r.path)
        lines.append(f"### {bucket} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("_None._")
            lines.append("")
            continue
        for item in items:
            evidence = "; ".join(item.evidence)
            risk = f" Risk: {'; '.join(item.risk_notes)}" if item.risk_notes else ""
            lines.append(f"- `{item.path}` — confidence `{item.confidence}`; refs={item.inbound_reference_count}; {evidence}.{risk}")
        lines.append("")
    lines.append("## All records")
    lines.append("")
    lines.append("| path | class | confidence | refs | lines |")
    lines.append("|---|---:|---:|---:|---:|")
    for item in sorted(records, key=lambda r: (r.classification, r.path)):
        lines.append(f"| `{item.path}` | `{item.classification}` | `{item.confidence}` | {item.inbound_reference_count} | {item.line_count} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Orchestrator script surfaces deterministically")
    parser.add_argument("--json-out", default=str(GENERATED_DIR / "script-classification.json"))
    parser.add_argument("--md-out", default=str(GENERATED_DIR / "script-classification.md"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    records, summary = build_records()
    payload = {
        "schema_version": "orchestrator-script-classification/v1",
        "summary": summary,
        "records": [asdict(r) for r in records],
    }
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    md_out.write_text(render_markdown(records, summary))
    if args.pretty:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(json.dumps({"json_out": str(json_out), "md_out": str(md_out), "script_count": len(records)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
