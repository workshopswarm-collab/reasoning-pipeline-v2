#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MAINTENANCE_ROOT = Path(__file__).resolve().parents[2]
if str(MAINTENANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_ROOT))

from lib.maintenance_run import (  # noqa: E402
    RunEnvelope,
    StateParseError,
    atomic_write_json,
    envelope_ref,
    load_json_with_context,
    make_run_id,
    preflight_path_exists,
    preflight_writable_dir,
)
from lib.maintenance_objective_status import (  # noqa: E402
    build_objective_rollup,
    objective_status_from_wrapper,
)

SCRIPT_ROOT = Path(__file__).resolve().parent
WORKBENCH_ROOT = Path("/Users/agent2/.openclaw/workbench")
PRUNE_SCRIPT = SCRIPT_ROOT / "context_usage_prune.py"
TELEMETRY_SCRIPT = SCRIPT_ROOT / "context_usage_telemetry.py"
GENERATED_ROOT = MAINTENANCE_ROOT / "workbench-context-maintenance" / "generated"
RUNS_ROOT = GENERATED_ROOT / "runs"
WORKBENCH_CONTEXT_ROOT = WORKBENCH_ROOT / "context"
WORKBENCH_STATE_ROOT = WORKBENCH_CONTEXT_ROOT / "state"
APPLY_LOCK_PATH = Path("/Users/agent2/.openclaw/locks/workbench-context-prune-apply.lock")
PRESSURE_TRIGGER_STATE = WORKBENCH_STATE_ROOT / "context-prune-pressure-trigger-state.json"
STATE_REBASE_PREVIEW = WORKBENCH_STATE_ROOT / "context-pruning-state-rebase-preview.json"
STATE_REBASE_MANIFEST = WORKBENCH_STATE_ROOT / "context-pruning-state.rebase-manifest.json"
STATE_COMPACTION_PREVIEW = WORKBENCH_STATE_ROOT / "context-pruning-state-compaction-preview.json"
STATE_COMPACTION_MANIFEST = WORKBENCH_STATE_ROOT / "context-pruning-state.compaction-manifest.json"
STATE_PRUNE_ARCHIVE_ROOT = WORKBENCH_ROOT / "tmp" / "context-archive" / "state-prune"
PRUNING_STATE_REL_PATH = "context/state/context-pruning-state.json"
APPLY_LOCK_STALE_SECONDS = 6 * 60 * 60
DEFAULT_PRESSURE_QUANT_BYTE_THRESHOLD = 100_000
DEFAULT_PRESSURE_ACTIVE_BYTE_THRESHOLD = 25_000
DEFAULT_PRESSURE_PRUNE_CANDIDATE_THRESHOLD = 12
DEFAULT_PRESSURE_PLANNED_BYTE_SAVINGS_THRESHOLD = 7_500
DEFAULT_PRESSURE_COOLDOWN_HOURS = 24
RECALL_STORE = WORKBENCH_ROOT / "memory" / ".dreams" / "short-term-recall.json"
TELEMETRY_JSON = WORKBENCH_STATE_ROOT / "context-usage-telemetry.json"
TELEMETRY_MARKDOWN = WORKBENCH_STATE_ROOT / "context-usage-telemetry.md"
DEFAULT_TELEMETRY_SOURCE_WINDOW_DAYS = 14
DEFAULT_TELEMETRY_MAX_HOT_ENTRIES = 750
WRAPPER_SUMMARY_SCHEMA = "workbench-context-prune-wrapper-summary/v1"
PRESSURE_TRIGGER_STATE_SCHEMA = "workbench-context-prune-pressure-trigger/v1"
DEFAULT_IDENTITY_MODE = "content-primary"
IDENTITY_MODES = ("content-primary", "line-legacy")
PRESSURE_TRIGGER_RESULTS = {
    "noop",
    "would_apply",
    "applied",
    "blocked",
    "applied_budget_met",
    "applied_partial_budget_unmet",
    "degraded_no_safe_apply",
    "degraded_primary_target_unresolved",
    "degraded_state_budget_unmet",
    "audit_only_pressure_detected",
}


def run_json(cmd: list[str], envelope: RunEnvelope, label: str) -> dict:
    proc = envelope.run_subprocess(cmd, cwd=WORKBENCH_ROOT, label=label)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise StateParseError(f"non-JSON output from {' '.join(cmd)}: {proc.stdout[:400]!r}") from exc


def run_text(cmd: list[str], envelope: RunEnvelope, label: str) -> str:
    proc = envelope.run_subprocess_with_retries(cmd, cwd=WORKBENCH_ROOT, label=label, attempts=2, backoff_seconds=2.0)
    return proc.stdout.strip()


def preflight(envelope: RunEnvelope, *, require_apply: bool, require_telemetry: bool = False) -> None:
    preflight_path_exists(WORKBENCH_ROOT, "Workbench root")
    preflight_path_exists(WORKBENCH_CONTEXT_ROOT, "Workbench context root")
    preflight_path_exists(PRUNE_SCRIPT, "context prune script")
    if require_telemetry:
        preflight_path_exists(TELEMETRY_SCRIPT, "context usage telemetry script")
    preflight_writable_dir(WORKBENCH_STATE_ROOT, "Workbench context state directory")
    preflight_writable_dir(RUNS_ROOT, "Maintenance Workbench run directory")
    if not RECALL_STORE.exists():
        envelope.warnings.append(f"recall store missing/non-fatal: {RECALL_STORE}")
    elif RECALL_STORE.is_file():
        load_json_with_context(RECALL_STORE)
    if require_apply:
        preflight_writable_dir(WORKBENCH_ROOT / "tmp" / "context-archive", "Workbench context archive directory")


def default_stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-weekly-auto-apply")


def default_pressure_stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-pressure-apply")


def default_rebase_stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-state-rebase")


def default_compact_stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-state-compaction")


def default_decisions_stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-decisions-consolidation")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
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


class ApplyLock:
    """Atomic file lock shared by weekly apply and pressure-trigger mutation paths."""

    def __init__(
        self,
        *,
        envelope: RunEnvelope,
        mode: str,
        path: Path | None = None,
        stale_seconds: int = APPLY_LOCK_STALE_SECONDS,
    ) -> None:
        self.envelope = envelope
        self.mode = mode
        self.path = path or APPLY_LOCK_PATH
        self.stale_seconds = stale_seconds
        self.acquired = False
        self.payload: dict[str, object] = {}

    def _payload(self) -> dict[str, object]:
        return {
            "pid": os.getpid(),
            "run_id": self.envelope.run_id,
            "mode": self.mode,
            "acquired_at": utc_now_iso(),
        }

    def _read_existing_payload(self) -> dict[str, object]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            return {}

    def _is_stale(self, payload: dict[str, object]) -> bool:
        if "pid" in payload and not pid_is_running(payload.get("pid")):
            return True
        acquired_epoch = parse_iso_epoch(payload.get("acquired_at"))
        if acquired_epoch is None:
            try:
                acquired_epoch = self.path.stat().st_mtime
            except OSError:
                return True
        return time.time() - acquired_epoch > self.stale_seconds

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            self.payload = self._payload()
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                existing = self._read_existing_payload()
                if not self._is_stale(existing):
                    self.acquired = False
                    return False
                latest = self._read_existing_payload()
                if latest != existing and not self._is_stale(latest):
                    self.acquired = False
                    return False
                self.envelope.warnings.append(
                    f"stale apply lock archived before replacement: path={self.path} payload={compact_text(existing)}"
                )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            try:
                os.write(fd, (json.dumps(self.payload, sort_keys=True) + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            self.acquired = True
            return True
        self.acquired = False
        return False

    def release(self) -> None:
        if not self.acquired:
            return
        existing = self._read_existing_payload()
        if existing.get("run_id") != self.payload.get("run_id") or existing.get("pid") != self.payload.get("pid"):
            self.envelope.warnings.append(f"apply lock not released because owner changed: path={self.path}")
            self.acquired = False
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self.acquired = False

    def __enter__(self) -> "ApplyLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def dict_value(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def int_value(data: dict, key: str) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def report_counter(report_path: Path, label: str) -> int:
    try:
        lines = report_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    prefix = f"- {label}:"
    for line in lines:
        if not line.startswith(prefix):
            continue
        parts = line[len(prefix):].strip().split()
        if not parts:
            return 0
        try:
            return int(parts[0])
        except ValueError:
            return 0
    return 0


def add_existing_artifact(envelope: RunEnvelope, path_value: object) -> None:
    if not isinstance(path_value, str) or not path_value:
        return
    path = Path(path_value)
    if path.exists():
        envelope.add_artifact(path)


def compact_text(value: object, *, max_chars: int = 700) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def blocker_summary(exc: BaseException) -> str:
    parts = [f"{type(exc).__name__}: {compact_text(exc)}"]
    proc = getattr(exc, "proc", None)
    if proc is not None:
        stderr = compact_text(getattr(proc, "stderr", ""), max_chars=350)
        stdout = compact_text(getattr(proc, "stdout", ""), max_chars=350)
        if stderr:
            parts.append(f"stderr={stderr}")
        elif stdout:
            parts.append(f"stdout={stdout}")
    return compact_text("; ".join(parts), max_chars=1000)


def telemetry_payload(telemetry_summary: dict) -> dict:
    return {
        "entry_count": int_value(telemetry_summary, "entry_count"),
        "covered_file_count": int_value(telemetry_summary, "covered_file_count"),
        "warning_count": int_value(telemetry_summary, "warning_count"),
        "json_artifact": str(TELEMETRY_JSON),
        "markdown_artifact": str(TELEMETRY_MARKDOWN),
        "summary": telemetry_summary,
    }


def protected_budget_debt_payload(budget_summary: dict) -> dict:
    debt = budget_summary.get("protected_budget_debt") if isinstance(budget_summary.get("protected_budget_debt"), dict) else {}
    by_category = debt.get("protected_budget_debt_by_category") if isinstance(debt.get("protected_budget_debt_by_category"), dict) else {}
    routes = debt.get("protected_budget_debt_routes") if isinstance(debt.get("protected_budget_debt_routes"), dict) else {}
    spans = debt.get("top_protected_spans") if isinstance(debt.get("top_protected_spans"), list) else []
    stale_spans = debt.get("stale_strong_evidence_overflow_spans") if isinstance(debt.get("stale_strong_evidence_overflow_spans"), list) else []
    return {
        "budget_success": bool(budget_summary.get("budget_success", True)),
        "bytes_total": int_value(debt, "protected_budget_debt_bytes_total"),
        "by_category": by_category,
        "routes": routes,
        "top_span_count": len(spans),
        "stale_strong_evidence_overflow_bytes_total": int_value(debt, "stale_strong_evidence_overflow_bytes_total"),
        "stale_strong_evidence_overflow_span_count": len(stale_spans),
    }


def audit_payload(audit_result: dict) -> dict:
    budget_summary = audit_result.get("budget_summary") if isinstance(audit_result.get("budget_summary"), dict) else {}
    return {
        "identityMode": audit_result.get("identityMode") or audit_result.get("identity_mode") or DEFAULT_IDENTITY_MODE,
        "items": int_value(audit_result, "items"),
        "review": int_value(audit_result, "review"),
        "prune_candidate": int_value(audit_result, "prune_candidate"),
        "budget_summary": budget_summary,
        "protected_budget_debt": protected_budget_debt_payload(budget_summary),
        "report": audit_result.get("report"),
        "state": audit_result.get("state"),
        "engine_run": audit_result.get("run"),
    }


def apply_payload(apply_result: dict, *, stamp: str, dry_run: bool, reindexed: bool) -> dict:
    files = apply_result.get("files") if isinstance(apply_result.get("files"), list) else []
    file_deltas = []
    for file in files:
        if not isinstance(file, dict):
            continue
        file_deltas.append(
            {
                "path": file.get("path"),
                "removed_blocks": int_value(file, "removed_blocks"),
                "source_bytes_before": int_value(file, "source_bytes_before"),
                "source_bytes_after_planned": int_value(file, "source_bytes_after_planned"),
                "source_bytes_delta_planned": int_value(file, "source_bytes_delta_planned"),
                "source_lines_before": int_value(file, "source_lines_before"),
                "source_lines_after_planned": int_value(file, "source_lines_after_planned"),
                "source_lines_delta_planned": int_value(file, "source_lines_delta_planned"),
            }
        )
    local_compression = apply_result.get("local_compression") if isinstance(apply_result.get("local_compression"), dict) else {}
    local_errors = local_compression.get("errors") if isinstance(local_compression.get("errors"), list) else []
    budget_summary = apply_result.get("budget_summary") if isinstance(apply_result.get("budget_summary"), dict) else {}
    return {
        "mode": apply_result.get("mode"),
        "identityMode": apply_result.get("identityMode") or apply_result.get("identity_mode") or DEFAULT_IDENTITY_MODE,
        "stamp": stamp,
        "dry_run": dry_run,
        "archive_root": apply_result.get("archive_root"),
        "pre_apply_manifest": apply_result.get("pre_apply_manifest"),
        "candidate_summary": apply_result.get("candidate_summary") if isinstance(apply_result.get("candidate_summary"), dict) else {},
        "project_spine_budget_pressure": apply_result.get("project_spine_budget_pressure") if isinstance(apply_result.get("project_spine_budget_pressure"), dict) else {},
        "budget_summary": budget_summary,
        "protected_budget_debt": protected_budget_debt_payload(budget_summary),
        "apply_acceptance": apply_result.get("apply_acceptance") if isinstance(apply_result.get("apply_acceptance"), dict) else {},
        "apply_blocked": bool(apply_result.get("apply_blocked")),
        "large_shrink_requires_override": bool(apply_result.get("large_shrink_requires_override")),
        "range_records_count": len(apply_result.get("range_records", [])) if isinstance(apply_result.get("range_records"), list) else 0,
        "source_bytes_before_total": int_value(apply_result, "source_bytes_before_total"),
        "source_bytes_after_planned_total": int_value(apply_result, "source_bytes_after_planned_total"),
        "source_bytes_delta_planned_total": int_value(apply_result, "source_bytes_delta_planned_total"),
        "no_op_reason": apply_result.get("no_op_reason") or "unknown",
        "removed_files": len(files),
        "removed_blocks": sum(int_value(file, "removed_blocks") for file in files if isinstance(file, dict)),
        "file_deltas": file_deltas,
        "reindexed": reindexed,
        "local_compression": {
            **local_compression,
            "attempted": int_value(local_compression, "attempted"),
            "succeeded": int_value(local_compression, "succeeded"),
            "fallback": int_value(local_compression, "fallback"),
            "error_count": len(local_errors),
        },
    }


def decisions_input_path_from_result(result: dict) -> str | None:
    input_path = result.get("input_path")
    if isinstance(input_path, str) and input_path:
        return input_path
    summary_path = result.get("summary_path") or result.get("plan_summary_path")
    if not isinstance(summary_path, str) or not summary_path:
        return None
    summary_file = Path(summary_path)
    try:
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return str(summary_file.with_name("decisions-consolidation-input.json"))
    input_from_summary = summary.get("input_path")
    if isinstance(input_from_summary, str) and input_from_summary:
        return input_from_summary
    return str(summary_file.with_name("decisions-consolidation-input.json"))


def add_decisions_artifacts(envelope: RunEnvelope, result: dict) -> None:
    for key in [
        "input_path",
        "plan_summary_path",
        "summary_path",
        "plan_path",
        "patch_path",
        "apply_manifest_path",
        "archive_path",
    ]:
        add_existing_artifact(envelope, result.get(key))
    backlog = result.get("decisions_backlog") if isinstance(result.get("decisions_backlog"), dict) else {}
    for key in ["history_path", "status_path", "markdown_path"]:
        add_existing_artifact(envelope, backlog.get(key))
    add_existing_artifact(envelope, decisions_input_path_from_result(result))


def decisions_payload(result: dict, *, stamp: str, mode: str, reindexed: bool = False) -> dict:
    validation_status = str(result.get("validation_status") or ("not_applicable" if mode == "decisions-plan" else "unknown"))
    payload = {
        "mode": mode,
        "stamp": stamp,
        "source_path": result.get("source_path"),
        "source_mutated": bool(result.get("source_mutated", False)),
        "archive_path": result.get("archive_path"),
        "bytes_before": int_value(result, "bytes_before"),
        "bytes_after": int_value(result, "bytes_after_planned"),
        "bytes_delta": int_value(result, "bytes_delta_planned"),
        "validation_status": validation_status,
        "validation_failures": result.get("validation_failures") if isinstance(result.get("validation_failures"), list) else [],
        "no_op_reason": result.get("no_op_reason"),
        "budget_deficit_after_consolidation": int_value(result, "budget_deficit_after_consolidation"),
        "consolidation_group_count": int_value(result, "consolidation_group_count"),
        "exact_duplicate_group_count": int_value(result, "exact_duplicate_group_count"),
        "shared_prefix_group_count": int_value(result, "shared_prefix_group_count"),
        "input_path": decisions_input_path_from_result(result),
        "summary_path": result.get("summary_path") or result.get("plan_summary_path"),
        "plan_path": result.get("plan_path"),
        "patch_path": result.get("patch_path"),
        "apply_manifest_path": result.get("apply_manifest_path"),
        "reindexed": reindexed,
    }
    backlog = result.get("decisions_backlog") if isinstance(result.get("decisions_backlog"), dict) else {}
    if backlog:
        payload["decisions_backlog"] = {
            "status": backlog.get("status"),
            "reason": backlog.get("reason"),
            "repeated_count": int_value(backlog, "repeated_count"),
            "safe_candidates": int_value(backlog, "safe_candidates"),
            "blocked_scope": backlog.get("blocked_scope") if isinstance(backlog.get("blocked_scope"), dict) else {},
            "allowed_forward_lanes": backlog.get("allowed_forward_lanes") if isinstance(backlog.get("allowed_forward_lanes"), list) else [],
            "recommended_action": backlog.get("recommended_action"),
            "history_path": backlog.get("history_path"),
            "status_path": backlog.get("status_path"),
            "markdown_path": backlog.get("markdown_path"),
        }
    return payload


def format_decisions_plan_summary(result: dict, *, stamp: str) -> str:
    return (
        "PRUNE_DECISIONS_PLAN_OK "
        f"groups={int_value(result, 'consolidation_group_count')} "
        f"exact={int_value(result, 'exact_duplicate_group_count')} "
        f"prefix={int_value(result, 'shared_prefix_group_count')} "
        f"bytes_delta={int_value(result, 'bytes_delta_planned')} "
        f"deficit={int_value(result, 'budget_deficit_after_consolidation')} "
        f"stamp={stamp}"
    )


def format_decisions_apply_summary(result: dict, *, stamp: str, reindexed: bool = False) -> str:
    validation_status = str(result.get("validation_status") or "unknown")
    reason = result.get("no_op_reason")
    if not reason:
        failures = result.get("validation_failures") if isinstance(result.get("validation_failures"), list) else []
        reason = ",".join(str(item) for item in failures[:3]) or "none"
    backlog = result.get("decisions_backlog") if isinstance(result.get("decisions_backlog"), dict) else {}
    backlog_status = backlog.get("status") if backlog else "none"
    repeated_count = int_value(backlog, "repeated_count") if backlog else 0
    recommended_action = backlog.get("recommended_action") if backlog else "none"
    return (
        "PRUNE_DECISIONS_APPLY_OK "
        f"status={validation_status} "
        f"mutated={int(bool(result.get('source_mutated')))} "
        f"bytes_delta={int_value(result, 'bytes_delta_planned')} "
        f"reason={reason} "
        f"backlog_status={backlog_status} "
        f"backlog_repeated={repeated_count} "
        f"backlog_action={recommended_action} "
        f"reindexed={1 if reindexed else 0} "
        f"stamp={stamp}"
    )


def build_decisions_apply_command(args: argparse.Namespace, stamp: str) -> list[str]:
    return [
        sys.executable,
        str(PRUNE_SCRIPT),
        "decisions-apply",
        "--stamp",
        stamp,
        "--min-shrink-bytes",
        str(getattr(args, "min_shrink_bytes", 1000)),
    ]


def state_rebase_payload(rebase_result: dict, *, stamp: str, dry_run: bool) -> dict:
    return {
        "stamp": stamp,
        "dry_run": dry_run,
        "old_version": rebase_result.get("old_version"),
        "new_version": rebase_result.get("new_version"),
        "identityMode": rebase_result.get("identityMode"),
        "current_item_count": int_value(rebase_result, "current_item_count"),
        "previous_entry_count": int_value(rebase_result, "previous_entry_count"),
        "rebased_entry_count": int_value(rebase_result, "rebased_entry_count"),
        "entries_preserved_by_exact_key": int_value(rebase_result, "entries_preserved_by_exact_key"),
        "entries_preserved_by_fingerprint": int_value(rebase_result, "entries_preserved_by_fingerprint"),
        "entries_preserved_by_prefix_alias": int_value(rebase_result, "entries_preserved_by_prefix_alias"),
        "entries_started_fresh": int_value(rebase_result, "entries_started_fresh"),
        "unmatched_previous_entries_preserved": int_value(rebase_result, "unmatched_previous_entries_preserved"),
        "ambiguous_fingerprint_count": int_value(rebase_result, "ambiguous_fingerprint_count"),
        "ambiguous_fingerprints": rebase_result.get("ambiguous_fingerprints") if isinstance(rebase_result.get("ambiguous_fingerprints"), list) else [],
        "state_path": rebase_result.get("state_path"),
        "preview_path": rebase_result.get("preview_path"),
        "manifest_path": rebase_result.get("manifest_path"),
        "archived_state_path": rebase_result.get("archived_state_path"),
        "engine_run": rebase_result.get("run"),
    }


def format_state_rebase_summary(*, dry_run: bool, result: dict, stamp: str) -> str:
    prefix = "PRUNE_STATE_REBASE_DRY_RUN_OK" if dry_run else "PRUNE_STATE_REBASE_OK"
    identity_mode = result.get("identityMode") or result.get("identity_mode") or DEFAULT_IDENTITY_MODE
    return (
        f"{prefix} identity={identity_mode} exact={int_value(result, 'entries_preserved_by_exact_key')} "
        f"fingerprint={int_value(result, 'entries_preserved_by_fingerprint')} "
        f"prefix={int_value(result, 'entries_preserved_by_prefix_alias')} "
        f"fresh={int_value(result, 'entries_started_fresh')} "
        f"ambiguous={int_value(result, 'ambiguous_fingerprint_count')} stamp={stamp}"
    )


def write_wrapper_summary(envelope: RunEnvelope, payload: dict) -> None:
    normalized = {"schema_version": WRAPPER_SUMMARY_SCHEMA, **payload}
    plane = str(getattr(envelope, "job_name", normalized.get("mode") or "unknown"))
    normalized.setdefault(
        "objective_rollup",
        build_objective_rollup(
            plane=plane,
            scheduler_status="unknown",
            wrapper_status="completed",
            wrapper_result=normalized,
            generated_artifacts=[str(path) for path in envelope.artifact_paths],
        ),
    )
    envelope.write_artifact("wrapper-summary.json", json.dumps(normalized, indent=2, sort_keys=True) + "\n")


def format_weekly_apply_summary(
    *,
    dry_run: bool,
    removed_files: int,
    removed_blocks: int,
    bytes_delta: int,
    no_op_reason: str,
    reindexed: bool,
    review: int,
    prune: int,
    telemetry_entries: int,
    local_compress: bool,
    local_compress_priority: bool,
    stamp: str,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
) -> str:
    return (
        ("PRUNE_AUTO_APPLY_DRY_RUN_OK " if dry_run else "PRUNE_AUTO_APPLY_OK ")
        + f"removed_files={removed_files} removed_blocks={removed_blocks} "
        f"bytes_delta={bytes_delta} no_op={no_op_reason} "
        f"reindexed={1 if reindexed else 0} identity={identity_mode} review={review} prune={prune} "
        f"telemetry={telemetry_entries} "
        f"local_compress={1 if local_compress else 0} "
        f"priority={1 if local_compress and local_compress_priority else 0} stamp={stamp}"
    )


def refresh_context_telemetry(
    envelope: RunEnvelope,
    *,
    source_window_days: int = DEFAULT_TELEMETRY_SOURCE_WINDOW_DAYS,
    max_hot_entries: int = DEFAULT_TELEMETRY_MAX_HOT_ENTRIES,
    compact_hot_json: bool = True,
    archive_before_compact: bool = True,
) -> dict:
    refresh_cmd = [
        sys.executable,
        str(TELEMETRY_SCRIPT),
        "refresh",
        "--source-window-days",
        str(source_window_days),
        "--max-hot-entries",
        str(max_hot_entries),
        "--write-markdown",
    ]
    archived_telemetry_path = None
    if compact_hot_json:
        refresh_cmd.append("--compact-hot-json")
        if archive_before_compact:
            archived_telemetry_path = archive_hot_state_file(
                TELEMETRY_JSON,
                stamp=str(getattr(envelope, "run_id", "telemetry-refresh")),
                archive_name="context-usage-telemetry.before-compact-refresh.json",
            )
            add_existing_artifact(envelope, archived_telemetry_path)
    telemetry_stdout = run_text(
        refresh_cmd,
        envelope,
        "context-telemetry-refresh",
    )
    telemetry_data = load_json_with_context(TELEMETRY_JSON)
    telemetry_summary = dict_value(telemetry_data, "summary")
    telemetry_artifact = {
        "refresh_stdout": telemetry_stdout,
        "telemetry_json": str(TELEMETRY_JSON),
        "telemetry_markdown": str(TELEMETRY_MARKDOWN),
        "source_window_days": source_window_days,
        "max_hot_entries": max_hot_entries,
        "compact_hot_json": compact_hot_json,
        "archived_telemetry_path": archived_telemetry_path,
        "compaction": telemetry_data.get("compaction") if isinstance(telemetry_data.get("compaction"), dict) else {},
        "summary": telemetry_summary,
    }
    envelope.write_artifact("context-telemetry-summary.json", json.dumps(telemetry_artifact, indent=2, sort_keys=True) + "\n")
    envelope.add_artifact(TELEMETRY_JSON)
    if TELEMETRY_MARKDOWN.exists():
        envelope.add_artifact(TELEMETRY_MARKDOWN)
    return telemetry_summary


def do_audit(envelope: RunEnvelope, *, identity_mode: str = DEFAULT_IDENTITY_MODE) -> str:
    telemetry_summary = refresh_context_telemetry(envelope)
    telemetry_entries = int_value(telemetry_summary, "entry_count")

    audit_result = run_json([sys.executable, str(PRUNE_SCRIPT), "audit", "--identity-mode", identity_mode], envelope, "context-audit")
    envelope.write_artifact("context-audit-summary.json", json.dumps(audit_result, indent=2, sort_keys=True) + "\n")
    add_existing_artifact(envelope, audit_result.get("report"))
    add_existing_artifact(envelope, audit_result.get("state"))

    review = int_value(audit_result, "review")
    prune = int_value(audit_result, "prune_candidate")
    report_path = Path(str(audit_result.get("report"))) if audit_result.get("report") else None
    recalled_now = report_counter(report_path, "items kept because recalled now") if report_path else 0
    high_recall = report_counter(report_path, "items high-recall protected") if report_path else 0
    protected = recalled_now + high_recall
    active_identity_mode = str(audit_result.get("identityMode") or identity_mode)
    summary = f"PRUNE_AUDIT_OK identity={active_identity_mode} review={review} prune={prune} telemetry={telemetry_entries} protected={protected}"
    write_wrapper_summary(
        envelope,
        {
            "status": "ok",
            "mode": "audit",
            "identityMode": active_identity_mode,
            "summary_line": summary,
            "telemetry": telemetry_payload(telemetry_summary),
            "audit": {**audit_payload(audit_result), "protected": protected},
        },
    )
    return summary


def apply_lock_busy_result(*, stamp: str, dry_run: bool) -> dict:
    return {
        "mode": "dry_run" if dry_run else "apply",
        "stamp": stamp,
        "dry_run": dry_run,
        "no_op_reason": "apply_lock_busy",
        "files": [],
        "range_records": [],
        "source_bytes_before_total": 0,
        "source_bytes_after_planned_total": 0,
        "source_bytes_delta_planned_total": 0,
        "candidate_summary": {
            "candidate_count_total": 0,
            "allowlisted_candidate_count": 0,
            "range_count_total": 0,
        },
        "local_compression": {
            "enabled": False,
            "attempted": 0,
            "succeeded": 0,
            "fallback": 0,
            "errors": [],
        },
    }


def do_apply_lock_busy_noop(args: argparse.Namespace, stamp: str, envelope: RunEnvelope, *, mode: str = "weekly-apply") -> str:
    identity_mode = str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))
    apply_result = apply_lock_busy_result(stamp=stamp, dry_run=bool(getattr(args, "dry_run", False)))
    apply_result["identityMode"] = identity_mode
    summary = format_weekly_apply_summary(
        dry_run=bool(getattr(args, "dry_run", False)),
        removed_files=0,
        removed_blocks=0,
        bytes_delta=0,
        no_op_reason="apply_lock_busy",
        reindexed=False,
        review=0,
        prune=0,
        telemetry_entries=0,
        local_compress=bool(getattr(args, "local_compress", False)),
        local_compress_priority=bool(getattr(args, "local_compress_priority", False)),
        stamp=stamp,
        identity_mode=identity_mode,
    )
    write_wrapper_summary(
        envelope,
        {
            "status": "ok",
            "mode": mode,
            "identityMode": identity_mode,
            "summary_line": summary,
            "no_op_reason": "apply_lock_busy",
            "apply_lock": {
                "path": str(APPLY_LOCK_PATH),
                "acquired": False,
                "no_op_reason": "apply_lock_busy",
            },
            "apply": apply_payload(apply_result, stamp=stamp, dry_run=bool(getattr(args, "dry_run", False)), reindexed=False),
        },
    )
    return summary


def run_weekly_apply_with_lock(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:
    if bool(getattr(args, "dry_run", False)):
        return do_weekly_apply(args, stamp, envelope)
    with ApplyLock(envelope=envelope, mode="weekly-apply") as lock:
        if not lock.acquired:
            return do_apply_lock_busy_noop(args, stamp, envelope)
        return do_weekly_apply(args, stamp, envelope)


def build_apply_command(args: argparse.Namespace, stamp: str) -> list[str]:
    apply_cmd = [
        sys.executable,
        str(PRUNE_SCRIPT),
        "apply",
        "--stamp",
        stamp,
        "--identity-mode",
        str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE)),
    ]
    if bool(getattr(args, "dry_run", False)):
        apply_cmd.append("--dry-run")
    if bool(getattr(args, "local_compress", False)):
        apply_cmd.extend([
            "--local-compress",
            "--local-compress-model", str(getattr(args, "local_compress_model", "qwen3.5:4b")),
            "--local-compress-max-blocks", str(getattr(args, "local_compress_max_blocks", 3)),
            "--local-compress-timeout-seconds", str(getattr(args, "local_compress_timeout_seconds", 180)),
            "--local-compress-lock-timeout-seconds", str(getattr(args, "local_compress_lock_timeout_seconds", 600.0)),
            "--local-compress-max-summary-chars", str(getattr(args, "local_compress_max_summary_chars", 700)),
        ])
        if bool(getattr(args, "local_compress_priority", True)):
            apply_cmd.append("--local-compress-priority")
        else:
            apply_cmd.append("--no-local-compress-priority")
    else:
        apply_cmd.append("--no-local-compress")
    return apply_cmd


def run_apply_and_post_audit(
    args: argparse.Namespace,
    stamp: str,
    envelope: RunEnvelope,
    *,
    telemetry_summary: dict,
    apply_label: str = "context-apply",
    apply_artifact_name: str = "apply-manifest.json",
    audit_label: str = "post-apply-audit",
    audit_artifact_name: str = "post-apply-audit.json",
) -> dict:
    apply_result = run_json(build_apply_command(args, stamp), envelope, apply_label)
    removed_files = int(len(apply_result.get("files", [])))
    removed_blocks = int(sum(int(f.get("removed_blocks", 0)) for f in apply_result.get("files", [])))
    bytes_delta = int_value(apply_result, "source_bytes_delta_planned_total")
    no_op_reason = str(apply_result.get("no_op_reason") or "unknown")
    envelope.write_artifact(apply_artifact_name, json.dumps(apply_result, indent=2, sort_keys=True) + "\n")

    reindexed = False
    if removed_blocks > 0 and not bool(getattr(args, "dry_run", False)):
        run_text(["openclaw", "memory", "index", "--force", "--agent", "workbench"], envelope, "memory-reindex")
        reindexed = True

    audit_proc = envelope.run_subprocess_with_retries(
        [sys.executable, str(PRUNE_SCRIPT), "audit", "--identity-mode", str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))],
        cwd=WORKBENCH_ROOT,
        label=audit_label,
        attempts=2,
        backoff_seconds=2.0,
    )
    try:
        audit_result = json.loads(audit_proc.stdout)
    except json.JSONDecodeError as exc:
        raise StateParseError(f"non-JSON output from post-apply audit: {audit_proc.stdout[:400]!r}") from exc
    envelope.write_artifact(audit_artifact_name, json.dumps(audit_result, indent=2, sort_keys=True) + "\n")
    add_existing_artifact(envelope, audit_result.get("report"))
    add_existing_artifact(envelope, audit_result.get("state"))

    return {
        "telemetry_summary": telemetry_summary,
        "apply_result": apply_result,
        "audit_result": audit_result,
        "removed_files": removed_files,
        "removed_blocks": removed_blocks,
        "bytes_delta": bytes_delta,
        "no_op_reason": no_op_reason,
        "reindexed": reindexed,
    }


def do_weekly_apply(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:
    telemetry_summary = refresh_context_telemetry(envelope)
    telemetry_entries = int_value(telemetry_summary, "entry_count")
    apply_run = run_apply_and_post_audit(args, stamp, envelope, telemetry_summary=telemetry_summary)
    audit_result = apply_run["audit_result"]
    review = int_value(audit_result, "review")
    prune = int_value(audit_result, "prune_candidate")
    summary = format_weekly_apply_summary(
        dry_run=bool(args.dry_run),
        removed_files=int(apply_run["removed_files"]),
        removed_blocks=int(apply_run["removed_blocks"]),
        bytes_delta=int(apply_run["bytes_delta"]),
        no_op_reason=str(apply_run["no_op_reason"]),
        reindexed=bool(apply_run["reindexed"]),
        review=review,
        prune=prune,
        telemetry_entries=telemetry_entries,
        local_compress=bool(args.local_compress),
        local_compress_priority=bool(args.local_compress_priority),
        stamp=stamp,
        identity_mode=str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE)),
    )
    write_wrapper_summary(
        envelope,
        {
            "status": "ok",
            "mode": "weekly-apply",
            "identityMode": audit_result.get("identityMode") or getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE),
            "summary_line": summary,
            "telemetry": telemetry_payload(telemetry_summary),
            "apply": apply_payload(apply_run["apply_result"], stamp=stamp, dry_run=bool(args.dry_run), reindexed=bool(apply_run["reindexed"])),
            "post_apply_audit": audit_payload(audit_result),
        },
    )
    return summary


def do_decisions_plan(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:  # noqa: ARG001
    result = run_json([sys.executable, str(PRUNE_SCRIPT), "decisions-plan", "--stamp", stamp], envelope, "decisions-consolidation-plan")
    envelope.write_artifact("decisions-consolidation-summary.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    add_decisions_artifacts(envelope, result)
    summary = format_decisions_plan_summary(result, stamp=stamp)
    write_wrapper_summary(
        envelope,
        {
            "status": "ok",
            "mode": "decisions-plan",
            "summary_line": summary,
            "decisions_consolidation": decisions_payload(result, stamp=stamp, mode="decisions-plan"),
        },
    )
    return summary


def run_decisions_apply_and_post_audit(
    args: argparse.Namespace,
    stamp: str,
    envelope: RunEnvelope,
    *,
    apply_label: str = "decisions-consolidation-apply",
    apply_artifact_name: str = "decisions-consolidation-apply-manifest.json",
    audit_label: str = "decisions-post-apply-audit",
    audit_artifact_name: str = "decisions-post-apply-audit.json",
) -> dict:
    manifest = run_json(build_decisions_apply_command(args, stamp), envelope, apply_label)
    envelope.write_artifact(apply_artifact_name, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    add_decisions_artifacts(envelope, manifest)

    reindexed = False
    if bool(manifest.get("source_mutated")):
        run_text(["openclaw", "memory", "index", "--force", "--agent", "workbench"], envelope, "memory-reindex")
        reindexed = True

    audit_proc = envelope.run_subprocess_with_retries(
        [sys.executable, str(PRUNE_SCRIPT), "audit", "--identity-mode", str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))],
        cwd=WORKBENCH_ROOT,
        label=audit_label,
        attempts=2,
        backoff_seconds=2.0,
    )
    try:
        audit_result = json.loads(audit_proc.stdout)
    except json.JSONDecodeError as exc:
        raise StateParseError(f"non-JSON output from decisions post-apply audit: {audit_proc.stdout[:400]!r}") from exc
    envelope.write_artifact(audit_artifact_name, json.dumps(audit_result, indent=2, sort_keys=True) + "\n")
    add_existing_artifact(envelope, audit_result.get("report"))
    add_existing_artifact(envelope, audit_result.get("state"))
    return {
        "manifest": manifest,
        "audit_result": audit_result,
        "source_mutated": bool(manifest.get("source_mutated")),
        "bytes_delta": int_value(manifest, "bytes_delta_planned"),
        "validation_status": str(manifest.get("validation_status") or "unknown"),
        "no_op_reason": str(manifest.get("no_op_reason") or "none"),
        "reindexed": reindexed,
    }


def do_decisions_apply(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:
    apply_run = run_decisions_apply_and_post_audit(args, stamp, envelope)
    manifest = apply_run["manifest"]
    validation_status = str(manifest.get("validation_status") or "unknown")
    if validation_status == "validation_failed":
        raise StateParseError(f"decisions consolidation validation failed: {manifest.get('validation_failures')}")
    summary = format_decisions_apply_summary(manifest, stamp=stamp, reindexed=bool(apply_run["reindexed"]))
    write_wrapper_summary(
        envelope,
        {
            "status": "ok",
            "mode": "decisions-apply",
            "summary_line": summary,
            "decisions_consolidation": decisions_payload(
                manifest,
                stamp=stamp,
                mode="decisions-apply",
                reindexed=bool(apply_run["reindexed"]),
            ),
            "post_apply_audit": audit_payload(apply_run["audit_result"]),
        },
    )
    return summary


def do_rebase_state(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:
    dry_run = bool(getattr(args, "dry_run", False))
    mode_flag = "--dry-run" if dry_run else "--apply"
    identity_mode = str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))
    rebase_result = run_json(
        [sys.executable, str(PRUNE_SCRIPT), "rebase-state", mode_flag, "--stamp", stamp, "--identity-mode", identity_mode],
        envelope,
        "context-state-rebase",
    )
    envelope.write_artifact("state-rebase-manifest.json", json.dumps(rebase_result, indent=2, sort_keys=True) + "\n")
    if dry_run and STATE_REBASE_PREVIEW.exists():
        envelope.add_artifact(STATE_REBASE_PREVIEW)
    if not dry_run and STATE_REBASE_MANIFEST.exists():
        envelope.add_artifact(STATE_REBASE_MANIFEST)
    add_existing_artifact(envelope, rebase_result.get("archived_state_path"))
    add_existing_artifact(envelope, rebase_result.get("state_path"))
    summary = format_state_rebase_summary(dry_run=dry_run, result=rebase_result, stamp=stamp)
    write_wrapper_summary(
        envelope,
        {
            "status": "ok",
            "mode": "rebase-state",
            "identityMode": rebase_result.get("identityMode") or identity_mode,
            "summary_line": summary,
            "state_rebase": state_rebase_payload(rebase_result, stamp=stamp, dry_run=dry_run),
        },
    )
    return summary


def path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def safe_archive_stamp(stamp: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", stamp).strip("-_") or "state-compaction"


def archive_hot_state_file(path: Path, *, stamp: str, archive_name: str) -> str | None:
    if not path.exists():
        return None
    archive_root = STATE_PRUNE_ARCHIVE_ROOT / safe_archive_stamp(stamp)
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_path = archive_root / archive_name
    archive_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(archive_path)


def write_file_artifact_if_exists(envelope: RunEnvelope, path: Path, artifact_name: str) -> str | None:
    if not path.exists():
        return None
    envelope.write_artifact(artifact_name, path.read_text(encoding="utf-8"))
    return artifact_name


def state_compaction_payload(result: dict, *, stamp: str, dry_run: bool, telemetry_summary: dict | None = None) -> dict:
    budget_met = state_compaction_budget_met(result)
    remaining_paths = [] if budget_met else [PRUNING_STATE_REL_PATH]
    return {
        "mode": "dry_run" if dry_run else "apply",
        "stamp": stamp,
        "dry_run": dry_run,
        "identityMode": result.get("identityMode") or DEFAULT_IDENTITY_MODE,
        "entries_before": int_value(result, "entries_before"),
        "entries_after": int_value(result, "entries_after"),
        "entries_retained_current": int_value(result, "entries_retained_current"),
        "entries_retained_history": int_value(result, "entries_retained_history"),
        "entries_archived": int_value(result, "entries_archived"),
        "entries_dropped": int_value(result, "entries_dropped"),
        "fingerprints_before": int_value(result, "fingerprints_before"),
        "fingerprints_after": int_value(result, "fingerprints_after"),
        "state_bytes_before": int_value(result, "state_bytes_before"),
        "state_bytes_after_planned": int_value(result, "state_bytes_after_planned"),
        "state_bytes_delta_planned": int_value(result, "state_bytes_delta_planned"),
        "state_hard_budget_bytes": int_value(result, "state_hard_budget_bytes"),
        "state_budget_met": budget_met,
        "state_budget_status": result.get("state_budget_status") or ("state_budget_met" if budget_met else "degraded_state_budget_unmet"),
        "state_bytes_over_hard": int_value(result, "state_bytes_over_hard"),
        "remaining_hard_budget_paths": remaining_paths,
        "archived_history_shards": result.get("archived_history_shards") if isinstance(result.get("archived_history_shards"), list) else [],
        "archived_history_shard_count": int_value(result, "archived_history_shard_count"),
        "dropped_reason_counts": result.get("dropped_reason_counts") if isinstance(result.get("dropped_reason_counts"), dict) else {},
        "state_path": result.get("state_path"),
        "preview_path": result.get("preview_path"),
        "manifest_path": result.get("manifest_path"),
        "archived_state_path": result.get("archived_state_path"),
        "telemetry": telemetry_payload(telemetry_summary or {}),
    }


def state_compaction_budget_met(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return True
    if "state_budget_met" in result:
        return bool(result.get("state_budget_met"))
    hard_budget = int_value(result, "state_hard_budget_bytes") or 500_000
    after_bytes = int_value(result, "state_bytes_after_planned")
    return after_bytes <= hard_budget if after_bytes else True


def state_compaction_budget_unmet(result: dict | None) -> bool:
    return not state_compaction_budget_met(result)


def format_state_compaction_summary(*, dry_run: bool, result: dict, stamp: str, telemetry_entries: int = 0) -> str:
    budget_met = state_compaction_budget_met(result)
    prefix = "PRUNE_STATE_COMPACT_DRY_RUN_OK" if dry_run and budget_met else "PRUNE_STATE_COMPACT_OK" if budget_met else "PRUNE_STATE_COMPACT_DEGRADED"
    return (
        f"{prefix} identity={result.get('identityMode') or DEFAULT_IDENTITY_MODE} "
        f"entries_before={int_value(result, 'entries_before')} "
        f"entries_after={int_value(result, 'entries_after')} "
        f"retained_current={int_value(result, 'entries_retained_current')} "
        f"retained_history={int_value(result, 'entries_retained_history')} "
        f"archived={int_value(result, 'entries_archived')} "
        f"dropped={int_value(result, 'entries_dropped')} "
        f"budget={result.get('state_budget_status') or ('state_budget_met' if budget_met else 'degraded_state_budget_unmet')} "
        f"bytes_after={int_value(result, 'state_bytes_after_planned')} "
        f"bytes_over_hard={int_value(result, 'state_bytes_over_hard')} "
        f"bytes_delta={int_value(result, 'state_bytes_delta_planned')} "
        f"telemetry={telemetry_entries} stamp={stamp}"
    )


def do_compact_state(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:
    dry_run = bool(getattr(args, "dry_run", False))
    identity_mode = str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))
    write_file_artifact_if_exists(envelope, WORKBENCH_STATE_ROOT / "context-pruning-state.json", "context-pruning-state.before-compaction.json")
    write_file_artifact_if_exists(envelope, TELEMETRY_JSON, "context-usage-telemetry.before-compaction.json")
    archived_telemetry_path = None
    telemetry_summary: dict = {}
    if not dry_run:
        archived_telemetry_path = archive_hot_state_file(
            TELEMETRY_JSON,
            stamp=stamp,
            archive_name="context-usage-telemetry.before-compaction.json",
        )
        telemetry_summary = refresh_context_telemetry(envelope, archive_before_compact=False)
    mode_flag = "--dry-run" if dry_run else "--apply"
    result = run_json(
        [sys.executable, str(PRUNE_SCRIPT), "compact-state", mode_flag, "--stamp", stamp, "--identity-mode", identity_mode],
        envelope,
        "context-state-compaction",
    )
    if archived_telemetry_path:
        result["archived_telemetry_path"] = archived_telemetry_path
    envelope.write_artifact("state-compaction-manifest.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    if dry_run and STATE_COMPACTION_PREVIEW.exists():
        envelope.add_artifact(STATE_COMPACTION_PREVIEW)
    if not dry_run and STATE_COMPACTION_MANIFEST.exists():
        envelope.add_artifact(STATE_COMPACTION_MANIFEST)
    add_existing_artifact(envelope, result.get("archived_state_path"))
    add_existing_artifact(envelope, archived_telemetry_path)
    add_existing_artifact(envelope, result.get("state_path"))
    write_file_artifact_if_exists(envelope, WORKBENCH_STATE_ROOT / "context-pruning-state.json", "context-pruning-state.after-compaction.json")
    write_file_artifact_if_exists(envelope, TELEMETRY_JSON, "context-usage-telemetry.after-compaction.json")
    telemetry_entries = int_value(telemetry_summary, "entry_count")
    summary = format_state_compaction_summary(dry_run=dry_run, result=result, stamp=stamp, telemetry_entries=telemetry_entries)
    budget_met = state_compaction_budget_met(result)
    write_wrapper_summary(
        envelope,
        {
            "status": "ok" if budget_met else "degraded",
            "mode": "compact-state",
            "identityMode": result.get("identityMode") or identity_mode,
            "summary_line": summary,
            "state_compaction": state_compaction_payload(result, stamp=stamp, dry_run=dry_run, telemetry_summary=telemetry_summary),
            "archived_telemetry_path": archived_telemetry_path,
            "state_bytes_after": path_size(WORKBENCH_STATE_ROOT / "context-pruning-state.json"),
            "telemetry_bytes_after": path_size(TELEMETRY_JSON),
        },
    )
    return summary


def pressure_thresholds_from_args(args: argparse.Namespace) -> dict:
    return {
        "quant_byte_threshold": int(getattr(args, "quant_byte_threshold", DEFAULT_PRESSURE_QUANT_BYTE_THRESHOLD)),
        "active_byte_threshold": int(getattr(args, "active_byte_threshold", DEFAULT_PRESSURE_ACTIVE_BYTE_THRESHOLD)),
        "prune_candidate_threshold": int(getattr(args, "prune_candidate_threshold", DEFAULT_PRESSURE_PRUNE_CANDIDATE_THRESHOLD)),
        "planned_byte_savings_threshold": int(getattr(args, "planned_byte_savings_threshold", DEFAULT_PRESSURE_PLANNED_BYTE_SAVINGS_THRESHOLD)),
        "cooldown_hours": float(getattr(args, "cooldown_hours", DEFAULT_PRESSURE_COOLDOWN_HOURS)),
    }


def load_pressure_trigger_state() -> dict:
    if not PRESSURE_TRIGGER_STATE.exists():
        return {}
    return load_json_with_context(PRESSURE_TRIGGER_STATE)


def budget_records(summary: dict, key: str) -> dict:
    records = summary.get(key)
    return records if isinstance(records, dict) else {}


def pressure_record_excerpt(path: str, record: dict) -> dict:
    return {
        "path": path,
        "heading": record.get("heading"),
        "bytes": int_value(record, "bytes"),
        "target_bytes": record.get("target_bytes"),
        "hard_bytes": record.get("hard_bytes"),
        "bytes_over_target": int_value(record, "bytes_over_target"),
        "bytes_over_hard": int_value(record, "bytes_over_hard"),
        "pressure_level": record.get("pressure_level"),
        "projected_pressure_level_after_apply": record.get("projected_pressure_level_after_apply"),
        "planned_pressure_level_after_apply": record.get("planned_pressure_level_after_apply"),
    }


def pressure_observed_from_results(audit_result: dict, dry_run_result: dict) -> dict:
    budget_summary = dry_run_result.get("budget_summary") if isinstance(dry_run_result.get("budget_summary"), dict) else {}
    if not budget_summary:
        budget_summary = audit_result.get("budget_summary") if isinstance(audit_result.get("budget_summary"), dict) else {}
    hot_docs = budget_records(budget_summary, "hot_docs")
    state_files = budget_records(budget_summary, "state_files")
    active_headings = budget_records(budget_summary, "active_live_headings")
    candidate_summary = dry_run_result.get("candidate_summary") if isinstance(dry_run_result.get("candidate_summary"), dict) else {}
    apply_acceptance = dry_run_result.get("apply_acceptance") if isinstance(dry_run_result.get("apply_acceptance"), dict) else {}
    project_spine_pressure = dry_run_result.get("project_spine_budget_pressure") if isinstance(dry_run_result.get("project_spine_budget_pressure"), dict) else {}
    if not project_spine_pressure:
        project_spine_pressure = budget_summary.get("project_spine_budget_pressure") if isinstance(budget_summary.get("project_spine_budget_pressure"), dict) else {}

    quant_record = hot_docs.get("context/projects/quant-pipeline.md") if isinstance(hot_docs.get("context/projects/quant-pipeline.md"), dict) else {}
    active_record = hot_docs.get("context/active.md") if isinstance(hot_docs.get("context/active.md"), dict) else {}
    hard_budget_records: list[dict] = []
    for path, record in hot_docs.items():
        if isinstance(record, dict) and record.get("pressure_level") == "hard":
            hard_budget_records.append(pressure_record_excerpt(str(path), record))
    for heading, record in active_headings.items():
        if isinstance(record, dict) and record.get("pressure_level") == "hard":
            hard_budget_records.append(pressure_record_excerpt(f"context/active.md#{heading}", record))
    state_hard_records: list[dict] = []
    for path, record in state_files.items():
        if isinstance(record, dict) and record.get("pressure_level") == "hard":
            state_hard_records.append(pressure_record_excerpt(str(path), record))

    projected_deficits: list[dict] = []
    for path, record in hot_docs.items():
        if not isinstance(record, dict):
            continue
        projected_level = record.get("planned_pressure_level_after_apply") or record.get("projected_pressure_level_after_apply")
        target = record.get("target_bytes")
        projected_after = record.get("source_bytes_after_planned") or record.get("projected_bytes_after_apply")
        if projected_level in {"target", "hard"} or (target is not None and projected_after is not None and int(projected_after) > int(target)):
            excerpt = pressure_record_excerpt(str(path), record)
            if projected_after is not None:
                excerpt["projected_bytes_after_apply"] = int(projected_after)
                excerpt["projected_bytes_over_target"] = max(0, int(projected_after) - int(target or 0))
            projected_deficits.append(excerpt)
    spine_deficit = int_value(project_spine_pressure, "project_spine_budget_deficit_after_planning")
    if spine_deficit > 0 and not any(record.get("path") == "context/projects/quant-pipeline.md" for record in projected_deficits):
        projected_deficits.append(
            {
                "path": "context/projects/quant-pipeline.md",
                "projected_bytes_after_apply": int_value(project_spine_pressure, "project_spine_budget_projected_after_bytes"),
                "target_bytes": int_value(project_spine_pressure, "project_spine_budget_target_bytes"),
                "projected_bytes_over_target": spine_deficit,
                "pressure_level": "target",
            }
        )

    range_records = dry_run_result.get("range_records") if isinstance(dry_run_result.get("range_records"), list) else []
    range_count = len(range_records) or int_value(candidate_summary, "range_count_total")
    planned_byte_savings = max(0, -int_value(dry_run_result, "source_bytes_delta_planned_total"))
    prune_candidates = int_value(candidate_summary, "candidate_count_total") or int_value(audit_result, "prune_candidate")
    return {
        "quant_bytes": int_value(quant_record, "bytes"),
        "active_bytes": int_value(active_record, "bytes"),
        "decisions_autonomous_consolidation_required": bool(budget_summary.get("decisions_autonomous_consolidation_required")),
        "hot_doc_hard_budget_exceeded": bool(hard_budget_records),
        "hard_budget_records": hard_budget_records[:20],
        "state_json_hard_budget_exceeded": bool(state_hard_records),
        "state_json_hard_budget_records": state_hard_records[:20],
        "prune_candidate_count": prune_candidates,
        "planned_byte_savings": planned_byte_savings,
        "projected_post_apply_over_target": bool(projected_deficits),
        "projected_budget_deficits": projected_deficits[:20],
        "apply_range_count": range_count,
        "apply_acceptance_blocked": bool(apply_acceptance.get("blocked") or dry_run_result.get("apply_blocked")),
        "apply_acceptance": apply_acceptance,
        "project_spine_budget_pressure": project_spine_pressure,
    }


def pressure_record_paths(records: list[dict]) -> list[str]:
    paths: list[str] = []
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("path"), str) and record["path"]:
            paths.append(record["path"])
    return sorted(set(paths))


def primary_pressure_paths(observed: dict) -> list[str]:
    primary = pressure_record_paths(observed.get("hard_budget_records") if isinstance(observed.get("hard_budget_records"), list) else [])
    primary.extend(pressure_record_paths(observed.get("state_json_hard_budget_records") if isinstance(observed.get("state_json_hard_budget_records"), list) else []))
    if bool(observed.get("decisions_autonomous_consolidation_required")):
        primary.append("context/decisions.md")
    if not primary:
        primary.extend(pressure_record_paths(observed.get("projected_budget_deficits") if isinstance(observed.get("projected_budget_deficits"), list) else []))
    return sorted(set(primary))


def changed_paths_from_pressure_runs(apply_run: dict | None, decisions_run: dict | None) -> list[str]:
    paths: list[str] = []
    if isinstance(apply_run, dict):
        apply_result = apply_run.get("apply_result") if isinstance(apply_run.get("apply_result"), dict) else {}
        files = apply_result.get("files") if isinstance(apply_result.get("files"), list) else []
        for file in files:
            if isinstance(file, dict) and isinstance(file.get("path"), str) and file["path"]:
                paths.append(file["path"])
    if isinstance(decisions_run, dict) and bool(decisions_run.get("source_mutated")):
        manifest = decisions_run.get("manifest") if isinstance(decisions_run.get("manifest"), dict) else {}
        source_path = manifest.get("source_path")
        if isinstance(source_path, str) and source_path:
            paths.append(source_path)
        else:
            paths.append("context/decisions.md")
    return sorted(set(paths))


def pressure_apply_skip_reasons(apply_run: dict | None, decisions_run: dict | None) -> dict[str, object]:
    reasons: dict[str, object] = {}
    if isinstance(apply_run, dict):
        apply_result = apply_run.get("apply_result") if isinstance(apply_run.get("apply_result"), dict) else {}
        no_op_reason = apply_result.get("no_op_reason")
        if no_op_reason:
            reasons["context_no_op_reason"] = no_op_reason
        active_summary = apply_result.get("active_live_heading_summary") if isinstance(apply_result.get("active_live_heading_summary"), dict) else {}
        skip_reasons = active_summary.get("skip_reasons") if isinstance(active_summary.get("skip_reasons"), dict) else {}
        if skip_reasons:
            reasons["active_live_heading_skip_reasons"] = skip_reasons
        apply_acceptance = apply_result.get("apply_acceptance") if isinstance(apply_result.get("apply_acceptance"), dict) else {}
        hard_blockers = apply_acceptance.get("hard_blockers") if isinstance(apply_acceptance.get("hard_blockers"), list) else []
        if hard_blockers:
            reasons["hard_blockers"] = hard_blockers[:20]
    if isinstance(decisions_run, dict):
        no_op_reason = decisions_run.get("no_op_reason")
        if no_op_reason and no_op_reason != "none":
            reasons["decisions_no_op_reason"] = no_op_reason
        validation_status = decisions_run.get("validation_status")
        if validation_status and validation_status != "passed":
            reasons["decisions_validation_status"] = validation_status
        manifest = decisions_run.get("manifest") if isinstance(decisions_run.get("manifest"), dict) else {}
        backlog = manifest.get("decisions_backlog") if isinstance(manifest.get("decisions_backlog"), dict) else {}
        if backlog:
            reasons["decisions_backlog"] = {
                "status": backlog.get("status"),
                "reason": backlog.get("reason"),
                "repeated_count": int_value(backlog, "repeated_count"),
                "recommended_action": backlog.get("recommended_action"),
            }
    return reasons


def classify_pressure_objective(
    *,
    evaluation: dict,
    final_audit_result: dict,
    apply_run: dict | None = None,
    decisions_run: dict | None = None,
    state_compaction: dict | None = None,
    post_apply_state_compaction: dict | None = None,
) -> dict[str, object]:
    before_observed = evaluation.get("observed") if isinstance(evaluation.get("observed"), dict) else {}
    after_observed = pressure_observed_from_results(final_audit_result, {})
    remaining_hot_paths = pressure_record_paths(after_observed.get("hard_budget_records") if isinstance(after_observed.get("hard_budget_records"), list) else [])
    remaining_state_paths = pressure_record_paths(after_observed.get("state_json_hard_budget_records") if isinstance(after_observed.get("state_json_hard_budget_records"), list) else [])
    remaining_decisions_paths: list[str] = []
    if bool(after_observed.get("decisions_autonomous_consolidation_required")):
        remaining_decisions_paths.append("context/decisions.md")
    compaction_payloads = [payload for payload in (state_compaction, post_apply_state_compaction) if isinstance(payload, dict)]
    pruning_state_compaction_ran = any(
        payload.get("mode") == "apply" or payload.get("dry_run") is False
        for payload in compaction_payloads
    )
    pruning_state_budget_met = any(state_compaction_budget_met(payload) for payload in compaction_payloads)
    pruning_state_budget_unmet = any(state_compaction_budget_unmet(payload) for payload in compaction_payloads)
    if pruning_state_compaction_ran and pruning_state_budget_met:
        remaining_state_paths = [path for path in remaining_state_paths if path != PRUNING_STATE_REL_PATH]
    if pruning_state_budget_unmet and PRUNING_STATE_REL_PATH not in remaining_state_paths:
        remaining_state_paths.append(PRUNING_STATE_REL_PATH)
    remaining_paths = sorted(set(remaining_hot_paths + remaining_state_paths + remaining_decisions_paths))
    primary_paths = primary_pressure_paths(before_observed)
    primary_remaining_paths = sorted(set(primary_paths).intersection(remaining_paths))
    changed_paths = changed_paths_from_pressure_runs(apply_run, decisions_run)
    changed_any_file = bool(changed_paths)
    hard_budget_met = not remaining_paths
    if hard_budget_met:
        result = "applied_budget_met" if changed_any_file else "audit_only_pressure_detected"
    elif changed_any_file:
        result = "applied_partial_budget_unmet"
    else:
        result = "degraded_no_safe_apply"
    return {
        "result": result,
        "hard_budget_met": hard_budget_met,
        "degraded": result.startswith("degraded") or result == "applied_partial_budget_unmet",
        "remaining_hard_budget_paths": remaining_paths,
        "remaining_hot_doc_hard_budget_paths": remaining_hot_paths,
        "remaining_state_json_hard_budget_paths": remaining_state_paths,
        "remaining_decisions_hard_budget_paths": remaining_decisions_paths,
        "primary_pressure_paths": primary_paths,
        "primary_target_unresolved": bool(primary_remaining_paths),
        "primary_target_unresolved_paths": primary_remaining_paths,
        "changed_any_file": changed_any_file,
        "changed_paths": changed_paths,
        "skipped_reasons": pressure_apply_skip_reasons(apply_run, decisions_run),
        "state_compaction_budget_met": pruning_state_budget_met if compaction_payloads else None,
        "state_compaction_budget_unmet": pruning_state_budget_unmet if compaction_payloads else None,
        "post_apply_observed": after_observed,
    }


def recurrence_counts_for_paths(previous_state: dict, paths: list[str]) -> dict[str, int]:
    previous_counts = previous_state.get("unresolved_pressure_recurrence") if isinstance(previous_state.get("unresolved_pressure_recurrence"), dict) else {}
    return {
        path: int(previous_counts.get(path, 0) or 0) + 1
        for path in sorted(set(paths))
    }


def existing_apply_lock_busy(path: Path | None = None) -> bool:
    lock_path = path or APPLY_LOCK_PATH
    if not lock_path.exists():
        return False
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        payload = {}
    if "pid" in payload and not pid_is_running(payload.get("pid")):
        return False
    acquired_epoch = parse_iso_epoch(payload.get("acquired_at"))
    if acquired_epoch is None:
        try:
            acquired_epoch = lock_path.stat().st_mtime
        except OSError:
            return False
    return time.time() - acquired_epoch <= APPLY_LOCK_STALE_SECONDS


def normalize_pressure_state_result(result: str) -> str:
    return result if result in PRESSURE_TRIGGER_RESULTS else "blocked"


def build_pressure_trigger_state_payload(
    previous_state: dict,
    *,
    result: str,
    evaluation: dict,
    envelope: RunEnvelope,
    updated_at: str | None = None,
) -> dict:
    normalized_result = normalize_pressure_state_result(result)
    now = updated_at or utc_now_iso()
    previous = previous_state if isinstance(previous_state, dict) else {}
    last_successful_apply_at = previous.get("last_successful_apply_at")
    last_successful_apply_run = previous.get("last_successful_apply_run")
    if normalized_result == "applied_budget_met" or normalized_result == "applied":
        last_successful_apply_at = now
        last_successful_apply_run = envelope.run_id
    noop_reasons = evaluation.get("noop_reasons") if isinstance(evaluation.get("noop_reasons"), list) else []
    thresholds = evaluation.get("thresholds") if isinstance(evaluation.get("thresholds"), dict) else {}
    observed = evaluation.get("observed") if isinstance(evaluation.get("observed"), dict) else {}
    pressure_objective = evaluation.get("pressure_objective") if isinstance(evaluation.get("pressure_objective"), dict) else {}
    remaining_paths = pressure_objective.get("remaining_hard_budget_paths") if isinstance(pressure_objective.get("remaining_hard_budget_paths"), list) else []
    unresolved_recurrence = recurrence_counts_for_paths(previous, [str(path) for path in remaining_paths])
    payload = {
        "schema_version": PRESSURE_TRIGGER_STATE_SCHEMA,
        "updated_at": now,
        "last_successful_apply_at": last_successful_apply_at,
        "last_successful_apply_run": last_successful_apply_run,
        "last_pressure_check_at": now,
        "last_pressure_check_run": envelope.run_id,
        "last_result": normalized_result,
        "last_noop_reasons": [str(reason) for reason in noop_reasons],
        "last_thresholds": thresholds,
        "last_observed": observed,
        "last_objective_result": pressure_objective.get("result"),
        "last_objective": pressure_objective,
        "unresolved_pressure_recurrence": unresolved_recurrence,
        "max_unresolved_pressure_recurrence": max(unresolved_recurrence.values()) if unresolved_recurrence else 0,
    }
    return payload


def write_pressure_trigger_state(
    previous_state: dict,
    *,
    result: str,
    evaluation: dict,
    envelope: RunEnvelope,
) -> dict:
    payload = build_pressure_trigger_state_payload(previous_state, result=result, evaluation=evaluation, envelope=envelope)
    atomic_write_json(PRESSURE_TRIGGER_STATE, payload)
    envelope.add_artifact(PRESSURE_TRIGGER_STATE)
    return payload


def write_blocked_pressure_trigger_state(args: argparse.Namespace, envelope: RunEnvelope, blocker: str) -> dict | None:
    try:
        previous_state = load_pressure_trigger_state()
    except Exception as exc:  # noqa: BLE001 - state write is best-effort on blocked wrapper paths.
        envelope.warnings.append(f"pressure trigger blocked-state load skipped: {type(exc).__name__}: {compact_text(exc)}")
        previous_state = {}
    evaluation = {
        "noop_reasons": ["blocked"],
        "thresholds": pressure_thresholds_from_args(args),
        "observed": {},
        "conditions": {"blocked": True, "blocker": blocker},
    }
    try:
        return write_pressure_trigger_state(previous_state, result="blocked", evaluation=evaluation, envelope=envelope)
    except Exception as exc:  # noqa: BLE001 - preserve original failure as wrapper outcome.
        envelope.warnings.append(f"pressure trigger blocked-state write failed: {type(exc).__name__}: {compact_text(exc)}")
        return None


def evaluate_pressure_trigger(args: argparse.Namespace, audit_result: dict, dry_run_result: dict, pressure_state: dict, *, lock_busy: bool) -> dict:
    thresholds = pressure_thresholds_from_args(args)
    observed = pressure_observed_from_results(audit_result, dry_run_result)
    quant_trigger = observed["quant_bytes"] >= thresholds["quant_byte_threshold"]
    active_trigger = observed["active_bytes"] >= thresholds["active_byte_threshold"]
    hard_budget_trigger = bool(observed["hot_doc_hard_budget_exceeded"])
    state_hard_budget_trigger = bool(observed.get("state_json_hard_budget_exceeded"))
    decisions_trigger = bool(observed.get("decisions_autonomous_consolidation_required"))
    budget_threshold_met = bool(quant_trigger or active_trigger or hard_budget_trigger or state_hard_budget_trigger or decisions_trigger)
    prune_trigger = observed["prune_candidate_count"] >= thresholds["prune_candidate_threshold"]
    savings_trigger = observed["planned_byte_savings"] >= thresholds["planned_byte_savings_threshold"]
    projected_trigger = bool(observed["projected_post_apply_over_target"])
    work_threshold_met = bool(prune_trigger or savings_trigger or projected_trigger or decisions_trigger)

    cooldown_active = False
    cooldown_remaining_seconds = 0
    last_successful_apply_at = pressure_state.get("last_successful_apply_at") if isinstance(pressure_state, dict) else None
    last_successful_epoch = parse_iso_epoch(last_successful_apply_at)
    if last_successful_epoch is not None:
        cooldown_seconds = max(0, int(float(thresholds["cooldown_hours"]) * 3600))
        elapsed = max(0, int(time.time() - last_successful_epoch))
        previous_observed = pressure_state.get("last_observed") if isinstance(pressure_state.get("last_observed"), dict) else {}
        consecutive_hard_budget = bool(hard_budget_trigger and previous_observed.get("hot_doc_hard_budget_exceeded"))
        if elapsed < cooldown_seconds and not consecutive_hard_budget:
            cooldown_active = True
            cooldown_remaining_seconds = cooldown_seconds - elapsed

    no_op_reasons: list[str] = []
    if not budget_threshold_met:
        no_op_reasons.append("budget_thresholds_not_met")
    if not work_threshold_met:
        no_op_reasons.append("work_thresholds_not_met")
    if cooldown_active:
        no_op_reasons.append("cooldown_active")
    if observed["apply_range_count"] <= 0 and not decisions_trigger:
        no_op_reasons.append("no_apply_ranges")
    if lock_busy:
        no_op_reasons.append("apply_lock_busy")
    if observed["apply_acceptance_blocked"]:
        no_op_reasons.append("apply_acceptance_blocked")

    conditions = {
        "quant_byte_threshold_met": quant_trigger,
        "active_byte_threshold_met": active_trigger,
        "hard_budget_threshold_met": hard_budget_trigger,
        "state_json_hard_budget_threshold_met": state_hard_budget_trigger,
        "decisions_consolidation_required": decisions_trigger,
        "budget_threshold_met": budget_threshold_met,
        "prune_candidate_threshold_met": prune_trigger,
        "planned_byte_savings_threshold_met": savings_trigger,
        "projected_post_apply_over_target": projected_trigger,
        "work_threshold_met": work_threshold_met,
        "cooldown_active": cooldown_active,
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "apply_ranges_present": observed["apply_range_count"] > 0,
        "decisions_apply_present": decisions_trigger,
        "apply_lock_available": not lock_busy,
        "apply_acceptance_passed": not observed["apply_acceptance_blocked"],
    }
    return {
        "pressure_trigger_result": "noop" if no_op_reasons else "eligible",
        "noop_reasons": no_op_reasons,
        "thresholds": thresholds,
        "observed": observed,
        "conditions": conditions,
        "state_path": str(PRESSURE_TRIGGER_STATE),
        "state_loaded": bool(pressure_state),
    }


def format_pressure_check_summary(
    *,
    dry_run: bool,
    result: str,
    noop_reasons: list[str],
    observed: dict,
    stamp: str,
    reindexed: bool = False,
    identity_mode: str = DEFAULT_IDENTITY_MODE,
) -> str:
    prefix = "PRUNE_PRESSURE_CHECK_DRY_RUN_OK" if dry_run else "PRUNE_PRESSURE_CHECK_OK"
    no_op = ",".join(noop_reasons) if noop_reasons else "none"
    remaining_paths = observed.get("remaining_hard_budget_paths") if isinstance(observed.get("remaining_hard_budget_paths"), list) else []
    remaining_text = "|".join(str(path) for path in remaining_paths[:5]) if remaining_paths else "none"
    backlog_parts = ""
    if observed.get("decisions_backlog_status"):
        backlog_parts = (
            f" decisions_backlog_status={observed.get('decisions_backlog_status')} "
            f"decisions_backlog_repeated={int(observed.get('decisions_backlog_repeated_count') or 0)} "
            f"decisions_backlog_action={observed.get('decisions_backlog_recommended_action') or 'none'}"
        )
    objective_part = f" objective_status={observed.get('objective_status')}" if observed.get("objective_status") else ""
    return (
        f"{prefix} result={result} identity={identity_mode} no_op={no_op} "
        f"ranges={int(observed.get('apply_range_count', 0) or 0)} "
        f"savings={int(observed.get('planned_byte_savings', 0) or 0)} "
        f"quant_bytes={int(observed.get('quant_bytes', 0) or 0)} "
        f"active_bytes={int(observed.get('active_bytes', 0) or 0)} "
        f"remaining_hard_budget_paths={remaining_text} "
        f"decisions_autonomous_consolidation_required={str(bool(observed.get('decisions_autonomous_consolidation_required'))).lower()} "
        f"reindexed={1 if reindexed else 0}{backlog_parts}{objective_part} stamp={stamp}"
    )


def run_pressure_dry_run_apply(stamp: str, envelope: RunEnvelope, *, identity_mode: str = DEFAULT_IDENTITY_MODE) -> dict:
    dry_run_args = argparse.Namespace(dry_run=True, local_compress=False, identity_mode=identity_mode)
    apply_result = run_json(build_apply_command(dry_run_args, stamp), envelope, "pressure-dry-run-apply")
    envelope.write_artifact("pressure-dry-run-apply-manifest.json", json.dumps(apply_result, indent=2, sort_keys=True) + "\n")
    add_existing_artifact(envelope, apply_result.get("pre_apply_manifest"))
    return apply_result


def state_json_compaction_needed(*results: dict) -> bool:
    for result in results:
        budget_summary = result.get("budget_summary") if isinstance(result.get("budget_summary"), dict) else {}
        for record in budget_records(budget_summary, "state_files").values():
            if isinstance(record, dict) and record.get("pressure_level") == "hard":
                return True
    return False


def run_pressure_state_compaction(
    args: argparse.Namespace,
    stamp: str,
    envelope: RunEnvelope,
    *,
    label: str = "pressure-state-compaction",
    artifact_name: str = "pressure-state-compaction-manifest.json",
) -> dict | None:
    dry_run = bool(getattr(args, "dry_run", False))
    identity_mode = str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))
    telemetry_summary: dict = {}
    archived_telemetry_path = None
    if not dry_run:
        archived_telemetry_path = archive_hot_state_file(
            TELEMETRY_JSON,
            stamp=stamp,
            archive_name="context-usage-telemetry.before-compaction.json",
        )
        telemetry_summary = refresh_context_telemetry(envelope, archive_before_compact=False)
    mode_flag = "--dry-run" if dry_run else "--apply"
    result = run_json(
        [sys.executable, str(PRUNE_SCRIPT), "compact-state", mode_flag, "--stamp", stamp, "--identity-mode", identity_mode],
        envelope,
        label,
    )
    if archived_telemetry_path:
        result["archived_telemetry_path"] = archived_telemetry_path
        add_existing_artifact(envelope, archived_telemetry_path)
    envelope.write_artifact(artifact_name, json.dumps(result, indent=2, sort_keys=True) + "\n")
    add_existing_artifact(envelope, result.get("archived_state_path"))
    add_existing_artifact(envelope, result.get("state_path"))
    return state_compaction_payload(result, stamp=stamp, dry_run=dry_run, telemetry_summary=telemetry_summary)


def pressure_summary_payload(
    *,
    summary: str,
    result: str,
    telemetry_summary: dict,
    audit_result: dict,
    dry_run_result: dict,
    evaluation: dict,
    stamp: str,
    state_payload: dict,
    apply_run: dict | None = None,
    decisions_run: dict | None = None,
    state_compaction: dict | None = None,
    post_apply_state_compaction: dict | None = None,
) -> dict:
    identity_mode = audit_result.get("identityMode") or dry_run_result.get("identityMode") or DEFAULT_IDENTITY_MODE
    pressure_objective = evaluation.get("pressure_objective") if isinstance(evaluation.get("pressure_objective"), dict) else {}
    payload = {
        "status": "ok",
        "mode": "pressure-check",
        "identityMode": identity_mode,
        "summary_line": summary,
        "pressure_trigger_result": result,
        "pressure_trigger": {**evaluation, "pressure_trigger_result": result},
        "pressure_objective_result": pressure_objective.get("result"),
        "pressure_objective": pressure_objective,
        "telemetry": telemetry_payload(telemetry_summary),
        "audit": audit_payload(audit_result),
        "pressure_dry_run_apply": apply_payload(dry_run_result, stamp=stamp, dry_run=True, reindexed=False),
        "pressure_trigger_state": {
            "path": str(PRESSURE_TRIGGER_STATE),
            "loaded": bool(evaluation.get("state_loaded")),
            "written": True,
            "last_result": state_payload.get("last_result"),
            "last_pressure_check_run": state_payload.get("last_pressure_check_run"),
            "last_successful_apply_run": state_payload.get("last_successful_apply_run"),
            "state": state_payload,
        },
    }
    if state_compaction is not None:
        payload["state_compaction"] = state_compaction
    if post_apply_state_compaction is not None:
        payload["post_apply_state_compaction"] = post_apply_state_compaction
    if decisions_run is not None:
        payload["decisions_consolidation"] = decisions_payload(
            decisions_run["manifest"],
            stamp=stamp,
            mode="decisions-apply",
            reindexed=bool(decisions_run["reindexed"]),
        )
        payload["post_decisions_audit"] = audit_payload(decisions_run["audit_result"])
    if apply_run is not None:
        payload["apply"] = apply_payload(apply_run["apply_result"], stamp=stamp, dry_run=False, reindexed=bool(apply_run["reindexed"]))
        payload["post_apply_audit"] = audit_payload(apply_run["audit_result"])
    return payload


def do_pressure_check(args: argparse.Namespace, stamp: str, envelope: RunEnvelope) -> str:
    telemetry_summary = refresh_context_telemetry(envelope)
    identity_mode = str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE))
    audit_result = run_json([sys.executable, str(PRUNE_SCRIPT), "audit", "--identity-mode", identity_mode], envelope, "pressure-context-audit")
    envelope.write_artifact("pressure-context-audit-summary.json", json.dumps(audit_result, indent=2, sort_keys=True) + "\n")
    add_existing_artifact(envelope, audit_result.get("report"))
    add_existing_artifact(envelope, audit_result.get("state"))
    dry_run_result = run_pressure_dry_run_apply(stamp, envelope, identity_mode=identity_mode)
    state_compaction = None
    if state_json_compaction_needed(audit_result, dry_run_result):
        state_compaction = run_pressure_state_compaction(args, stamp, envelope)
    pressure_state = load_pressure_trigger_state()
    evaluation = evaluate_pressure_trigger(args, audit_result, dry_run_result, pressure_state, lock_busy=existing_apply_lock_busy())
    noop_reasons = list(evaluation.get("noop_reasons", []))
    observed = evaluation.get("observed") if isinstance(evaluation.get("observed"), dict) else {}

    if noop_reasons:
        result = "degraded_state_budget_unmet" if state_compaction_budget_unmet(state_compaction) else "noop"
        no_op_evaluation = evaluation
        no_op_observed = observed
        if result == "degraded_state_budget_unmet":
            remaining_paths = state_compaction.get("remaining_hard_budget_paths") if isinstance(state_compaction, dict) and isinstance(state_compaction.get("remaining_hard_budget_paths"), list) else [PRUNING_STATE_REL_PATH]
            pressure_objective = {
                "result": result,
                "hard_budget_met": False,
                "degraded": True,
                "remaining_hard_budget_paths": [str(path) for path in remaining_paths],
                "remaining_hot_doc_hard_budget_paths": [],
                "remaining_state_json_hard_budget_paths": [str(path) for path in remaining_paths],
                "primary_pressure_paths": primary_pressure_paths(observed),
                "primary_target_unresolved": bool(set(primary_pressure_paths(observed)).intersection(str(path) for path in remaining_paths)),
                "primary_target_unresolved_paths": sorted(set(primary_pressure_paths(observed)).intersection(str(path) for path in remaining_paths)),
                "changed_any_file": False,
                "changed_paths": [],
                "skipped_reasons": {"state_compaction": "state_budget_unmet"},
                "state_compaction_budget_met": False,
                "state_compaction_budget_unmet": True,
                "post_apply_observed": observed,
            }
            no_op_evaluation = {**evaluation, "pressure_objective": pressure_objective}
            no_op_observed = {
                **observed,
                "remaining_hard_budget_paths": pressure_objective["remaining_hard_budget_paths"],
                "objective_status": objective_status_from_wrapper({"pressure_objective": pressure_objective}),
            }
        else:
            no_op_observed = {**no_op_observed, "objective_status": "no_action_needed"}
        state_payload = write_pressure_trigger_state(pressure_state, result=result, evaluation=no_op_evaluation, envelope=envelope)
        summary = format_pressure_check_summary(dry_run=bool(args.dry_run), result=result, noop_reasons=noop_reasons, observed=no_op_observed, stamp=stamp, identity_mode=identity_mode)
        write_wrapper_summary(
            envelope,
            pressure_summary_payload(
                summary=summary,
                result=result,
                telemetry_summary=telemetry_summary,
                audit_result=audit_result,
                dry_run_result=dry_run_result,
                evaluation=no_op_evaluation,
                stamp=stamp,
                state_payload=state_payload,
                state_compaction=state_compaction,
            ),
        )
        return summary

    if bool(args.dry_run):
        dry_objective = {
            "result": "audit_only_pressure_detected",
            "hard_budget_met": not bool(observed.get("hot_doc_hard_budget_exceeded") or observed.get("state_json_hard_budget_exceeded")),
            "degraded": False,
            "remaining_hard_budget_paths": primary_pressure_paths(observed),
            "primary_pressure_paths": primary_pressure_paths(observed),
            "primary_target_unresolved": bool(primary_pressure_paths(observed)),
            "primary_target_unresolved_paths": primary_pressure_paths(observed),
            "changed_any_file": False,
            "changed_paths": [],
            "skipped_reasons": {},
            "post_apply_observed": observed,
        }
        dry_evaluation = {**evaluation, "pressure_objective": dry_objective}
        dry_observed = {
            **observed,
            "remaining_hard_budget_paths": dry_objective["remaining_hard_budget_paths"],
            "objective_status": objective_status_from_wrapper({"pressure_objective": dry_objective}),
        }
        state_payload = write_pressure_trigger_state(pressure_state, result="would_apply", evaluation=dry_evaluation, envelope=envelope)
        summary = format_pressure_check_summary(dry_run=True, result="would_apply", noop_reasons=[], observed=dry_observed, stamp=stamp, identity_mode=identity_mode)
        write_wrapper_summary(
            envelope,
            pressure_summary_payload(
                summary=summary,
                result="would_apply",
                telemetry_summary=telemetry_summary,
                audit_result=audit_result,
                dry_run_result=dry_run_result,
                evaluation=dry_evaluation,
                stamp=stamp,
                state_payload=state_payload,
                state_compaction=state_compaction,
            ),
        )
        return summary

    with ApplyLock(envelope=envelope, mode="pressure-check") as lock:
        if not lock.acquired:
            lock_conditions = evaluation.get("conditions") if isinstance(evaluation.get("conditions"), dict) else {}
            evaluation = {
                **evaluation,
                "pressure_trigger_result": "noop",
                "noop_reasons": ["apply_lock_busy"],
                "conditions": {**lock_conditions, "apply_lock_available": False},
            }
            state_payload = write_pressure_trigger_state(pressure_state, result="noop", evaluation=evaluation, envelope=envelope)
            summary = format_pressure_check_summary(dry_run=False, result="noop", noop_reasons=["apply_lock_busy"], observed=observed, stamp=stamp, identity_mode=identity_mode)
            write_wrapper_summary(
                envelope,
                pressure_summary_payload(
                    summary=summary,
                    result="noop",
                    telemetry_summary=telemetry_summary,
                    audit_result=audit_result,
                    dry_run_result=dry_run_result,
                    evaluation=evaluation,
                    stamp=stamp,
                    state_payload=state_payload,
                    state_compaction=state_compaction,
                ),
            )
            return summary
        decisions_run = None
        if bool(observed.get("decisions_autonomous_consolidation_required")):
            decisions_run = run_decisions_apply_and_post_audit(
                args,
                stamp,
                envelope,
                apply_label="pressure-decisions-apply",
                apply_artifact_name="pressure-decisions-apply-manifest.json",
                audit_label="pressure-decisions-post-apply-audit",
                audit_artifact_name="pressure-decisions-post-apply-audit.json",
            )
            if decisions_run["validation_status"] == "validation_failed":
                raise StateParseError(
                    "decisions consolidation required but validation failed: "
                    f"status={decisions_run['validation_status']} no_op={decisions_run['no_op_reason']}"
                )
        apply_run = None
        if int_value(observed, "apply_range_count") > 0:
            apply_run = run_apply_and_post_audit(
                args,
                stamp,
                envelope,
                telemetry_summary=telemetry_summary,
                apply_label="pressure-context-apply",
                apply_artifact_name="pressure-apply-manifest.json",
                audit_label="pressure-post-apply-audit",
                audit_artifact_name="pressure-post-apply-audit.json",
            )

    post_apply_audits = []
    if apply_run is not None:
        post_apply_audits.append(apply_run["audit_result"])
    if decisions_run is not None:
        post_apply_audits.append(decisions_run["audit_result"])
    post_apply_state_compaction = None
    if post_apply_audits and state_json_compaction_needed(*post_apply_audits):
        post_apply_state_compaction = run_pressure_state_compaction(
            args,
            f"{stamp}-post-apply-audit",
            envelope,
            label="pressure-post-apply-state-compaction",
            artifact_name="pressure-post-apply-state-compaction-manifest.json",
        )

    effective_bytes_delta = 0
    if apply_run is not None:
        effective_bytes_delta = int(apply_run["bytes_delta"])
    elif decisions_run is not None:
        effective_bytes_delta = int(decisions_run["bytes_delta"])
    final_audit_result = apply_run["audit_result"] if apply_run is not None else decisions_run["audit_result"] if decisions_run is not None else audit_result
    pressure_objective = classify_pressure_objective(
        evaluation=evaluation,
        final_audit_result=final_audit_result,
        apply_run=apply_run,
        decisions_run=decisions_run,
        state_compaction=state_compaction,
        post_apply_state_compaction=post_apply_state_compaction,
    )
    result = str(pressure_objective.get("result") or "degraded_no_safe_apply")
    observed_after_apply = {
        **observed,
        "planned_byte_savings": effective_bytes_delta * -1 if effective_bytes_delta < 0 else 0,
        "remaining_hard_budget_paths": pressure_objective.get("remaining_hard_budget_paths", []),
        "objective_status": objective_status_from_wrapper({"pressure_objective": pressure_objective}),
    }
    if decisions_run is not None:
        manifest = decisions_run.get("manifest") if isinstance(decisions_run.get("manifest"), dict) else {}
        backlog = manifest.get("decisions_backlog") if isinstance(manifest.get("decisions_backlog"), dict) else {}
        if backlog:
            observed_after_apply.update(
                {
                    "decisions_backlog_status": backlog.get("status"),
                    "decisions_backlog_reason": backlog.get("reason"),
                    "decisions_backlog_repeated_count": int_value(backlog, "repeated_count"),
                    "decisions_backlog_recommended_action": backlog.get("recommended_action"),
                }
            )
    reindexed = bool((apply_run and apply_run["reindexed"]) or (decisions_run and decisions_run["reindexed"]))
    summary = format_pressure_check_summary(
        dry_run=False,
        result=result,
        noop_reasons=[],
        observed=observed_after_apply,
        stamp=stamp,
        reindexed=reindexed,
        identity_mode=identity_mode,
    )
    applied_evaluation = {**evaluation, "pressure_trigger_result": result, "noop_reasons": [], "pressure_objective": pressure_objective}
    state_payload = write_pressure_trigger_state(pressure_state, result=result, evaluation=applied_evaluation, envelope=envelope)
    write_wrapper_summary(
        envelope,
        pressure_summary_payload(
            summary=summary,
            result=result,
            telemetry_summary=telemetry_summary,
            audit_result=audit_result,
            dry_run_result=dry_run_result,
            evaluation=applied_evaluation,
            stamp=stamp,
            state_payload=state_payload,
            apply_run=apply_run,
            decisions_run=decisions_run,
            state_compaction=state_compaction,
            post_apply_state_compaction=post_apply_state_compaction,
        ),
    )
    return summary


def add_identity_mode_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--identity-mode",
        choices=IDENTITY_MODES,
        default=DEFAULT_IDENTITY_MODE,
        help="State identity matching mode; defaults to content-primary. Use line-legacy as rollback.",
    )


def add_local_compression_flags(parser: argparse.ArgumentParser) -> None:
    local_group = parser.add_mutually_exclusive_group()
    local_group.add_argument("--local-compress", dest="local_compress", action="store_true", help="Enable capped local Ollama compression for eligible blocks (default).")
    local_group.add_argument("--no-local-compress", dest="local_compress", action="store_false", help="Disable local Ollama compression and use deterministic replacements only.")
    parser.set_defaults(local_compress=True)
    parser.add_argument("--local-compress-model", default="qwen3.5:4b")
    parser.add_argument("--local-compress-max-blocks", type=int, default=3)
    parser.add_argument("--local-compress-timeout-seconds", type=int, default=180)
    parser.add_argument("--local-compress-lock-timeout-seconds", type=float, default=600.0)
    priority_group = parser.add_mutually_exclusive_group()
    priority_group.add_argument("--local-compress-priority", dest="local_compress_priority", action="store_true", help="Reserve the shared Qwen lane for the full apply run so patched non-priority callers queue behind it (default).")
    priority_group.add_argument("--no-local-compress-priority", dest="local_compress_priority", action="store_false", help="Use normal shared-lock behavior without a priority reservation.")
    parser.set_defaults(local_compress_priority=True)
    parser.add_argument("--local-compress-max-summary-chars", type=int, default=700)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintenance wrapper for Workbench gate-driven context pruning/compression.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit = sub.add_parser("audit", help="Refresh context-usage telemetry and run a read-only Workbench context prune audit.")
    add_identity_mode_arg(audit)

    weekly = sub.add_parser("weekly-apply", help="Apply mature prune candidates, refresh report, and reindex if content changed.")
    add_identity_mode_arg(weekly)
    weekly.add_argument("--stamp", help="Archive stamp override.")
    weekly.add_argument("--dry-run", action="store_true", help="Plan weekly apply and write manifests without editing Workbench context or reindexing.")
    add_local_compression_flags(weekly)

    pressure = sub.add_parser("pressure-check", help="Run a daily pressure check and apply through the shared wrapper path when thresholds pass.")
    add_identity_mode_arg(pressure)
    pressure.add_argument("--dry-run", action="store_true", help="Report whether pressure thresholds would apply without mutating Workbench context.")
    pressure.add_argument("--quant-byte-threshold", type=int, default=DEFAULT_PRESSURE_QUANT_BYTE_THRESHOLD)
    pressure.add_argument("--active-byte-threshold", type=int, default=DEFAULT_PRESSURE_ACTIVE_BYTE_THRESHOLD)
    pressure.add_argument("--prune-candidate-threshold", type=int, default=DEFAULT_PRESSURE_PRUNE_CANDIDATE_THRESHOLD)
    pressure.add_argument("--planned-byte-savings-threshold", type=int, default=DEFAULT_PRESSURE_PLANNED_BYTE_SAVINGS_THRESHOLD)
    pressure.add_argument("--cooldown-hours", type=float, default=DEFAULT_PRESSURE_COOLDOWN_HOURS)
    pressure.add_argument("--stamp", help="Archive stamp override; defaults to YYYY-MM-DD-pressure-apply.")
    add_local_compression_flags(pressure)

    decisions_plan = sub.add_parser("decisions-plan", help="Generate a deterministic consolidation plan for context/decisions.md through the maintenance wrapper.")
    decisions_plan.add_argument("--stamp", required=True, help="Artifact stamp for the decisions consolidation plan.")

    decisions_apply = sub.add_parser("decisions-apply", help="Apply a validation-gated consolidation patch for context/decisions.md through the maintenance wrapper.")
    add_identity_mode_arg(decisions_apply)
    decisions_apply.add_argument("--stamp", required=True, help="Artifact/archive stamp for the decisions consolidation apply run.")
    decisions_apply.add_argument("--min-shrink-bytes", type=int, default=1000, help="Minimum safe shrink required when context/decisions.md is still over target.")

    rebase = sub.add_parser("rebase-state", help="Rebase context pruning state onto the selected identity mode.")
    add_identity_mode_arg(rebase)
    rebase.add_argument("--stamp", help="State rebase stamp override; defaults to YYYY-MM-DD-state-rebase.")
    rebase_mode = rebase.add_mutually_exclusive_group(required=True)
    rebase_mode.add_argument("--dry-run", action="store_true", help="Write state rebase preview without mutating state.")
    rebase_mode.add_argument("--apply", action="store_true", help="Archive current state and write the rebased state.")

    compact = sub.add_parser("compact-state", help="Compact generated pruning state and telemetry with archive-first retention.")
    add_identity_mode_arg(compact)
    compact.add_argument("--stamp", help="State compaction stamp override; defaults to YYYY-MM-DD-state-compaction.")
    compact_mode = compact.add_mutually_exclusive_group(required=True)
    compact_mode.add_argument("--dry-run", action="store_true", help="Write state compaction preview without mutating state/telemetry.")
    compact_mode.add_argument("--apply", action="store_true", help="Archive current generated state/telemetry and write compact hot state.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    now = datetime.now()
    run_id = make_run_id("workbench-context")
    if args.cmd == "audit":
        job_name = "Maintenance: Workbench Context Prune Audit"
    elif args.cmd == "pressure-check":
        job_name = "Maintenance: Workbench Context Prune Pressure Check"
    elif args.cmd == "decisions-plan":
        job_name = "Maintenance: Workbench Decisions Consolidation Plan"
    elif args.cmd == "decisions-apply":
        job_name = "Maintenance: Workbench Decisions Consolidation Apply"
    elif args.cmd == "rebase-state":
        job_name = "Maintenance: Workbench Context State Rebase"
    elif args.cmd == "compact-state":
        job_name = "Maintenance: Workbench Context State Compaction"
    else:
        job_name = "Maintenance: Workbench Context Prune Auto-Apply"
    envelope = RunEnvelope(
        job_name=job_name,
        mode=args.cmd,
        runs_root=RUNS_ROOT,
        workspace_root=MAINTENANCE_ROOT,
        run_id=run_id,
    )

    try:
        if args.cmd == "audit":
            preflight(envelope, require_apply=False, require_telemetry=True)
            summary = do_audit(envelope, identity_mode=str(getattr(args, "identity_mode", DEFAULT_IDENTITY_MODE)))
            summary = f"{summary} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary, returncode=0)
            print(summary)
            return 0
        if args.cmd == "weekly-apply":
            preflight(envelope, require_apply=True, require_telemetry=True)
            stamp = args.stamp or default_stamp(now)
            summary = run_weekly_apply_with_lock(args, stamp, envelope)
            summary = f"{summary} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary, returncode=0)
            print(summary)
            return 0
        if args.cmd == "pressure-check":
            preflight(envelope, require_apply=True, require_telemetry=True)
            stamp = args.stamp or default_pressure_stamp(now)
            summary = do_pressure_check(args, stamp, envelope)
            summary = f"{summary} run={envelope_ref(envelope)}"
            pressure_status = "degraded" if "result=degraded_" in summary or "result=applied_partial_budget_unmet" in summary else "ok"
            envelope.finish(status=pressure_status, summary_line=summary, returncode=0)
            print(summary)
            return 0
        if args.cmd == "decisions-plan":
            preflight(envelope, require_apply=False, require_telemetry=False)
            stamp = args.stamp or default_decisions_stamp(now)
            summary = do_decisions_plan(args, stamp, envelope)
            summary = f"{summary} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary, returncode=0)
            print(summary)
            return 0
        if args.cmd == "decisions-apply":
            preflight(envelope, require_apply=True, require_telemetry=False)
            stamp = args.stamp or default_decisions_stamp(now)
            summary = do_decisions_apply(args, stamp, envelope)
            summary = f"{summary} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary, returncode=0)
            print(summary)
            return 0
        if args.cmd == "rebase-state":
            preflight(envelope, require_apply=bool(getattr(args, "apply", False)), require_telemetry=False)
            stamp = args.stamp or default_rebase_stamp(now)
            summary = do_rebase_state(args, stamp, envelope)
            summary = f"{summary} run={envelope_ref(envelope)}"
            envelope.finish(status="ok", summary_line=summary, returncode=0)
            print(summary)
            return 0
        if args.cmd == "compact-state":
            preflight(envelope, require_apply=bool(getattr(args, "apply", False)), require_telemetry=bool(getattr(args, "apply", False)))
            stamp = args.stamp or default_compact_stamp(now)
            summary = do_compact_state(args, stamp, envelope)
            summary = f"{summary} run={envelope_ref(envelope)}"
            envelope.finish(status="degraded" if "PRUNE_STATE_COMPACT_DEGRADED" in summary else "ok", summary_line=summary, returncode=0)
            print(summary)
            return 0
    except Exception as exc:
        if args.cmd == "audit":
            blocked_prefix = "PRUNE_AUDIT_BLOCKED"
        elif args.cmd == "pressure-check":
            blocked_prefix = "PRUNE_PRESSURE_CHECK_BLOCKED"
        elif args.cmd == "decisions-plan":
            blocked_prefix = "PRUNE_DECISIONS_PLAN_BLOCKED"
        elif args.cmd == "decisions-apply":
            blocked_prefix = "PRUNE_DECISIONS_APPLY_BLOCKED"
        elif args.cmd == "rebase-state":
            blocked_prefix = "PRUNE_STATE_REBASE_BLOCKED"
        elif args.cmd == "compact-state":
            blocked_prefix = "PRUNE_STATE_COMPACT_BLOCKED"
        else:
            blocked_prefix = "PRUNE_AUTO_APPLY_BLOCKED"
        blocker = blocker_summary(exc)
        blocked_payload = {
            "status": "blocked",
            "mode": args.cmd,
            "blocker": blocker,
            "blocker_type": type(exc).__name__,
        }
        if args.cmd == "pressure-check":
            state_payload = write_blocked_pressure_trigger_state(args, envelope, blocker)
            if state_payload is not None:
                blocked_payload["pressure_trigger_state"] = {
                    "path": str(PRESSURE_TRIGGER_STATE),
                    "written": True,
                    "last_result": state_payload.get("last_result"),
                    "last_pressure_check_run": state_payload.get("last_pressure_check_run"),
                    "state": state_payload,
                }
        write_wrapper_summary(envelope, blocked_payload)
        summary = f"{blocked_prefix} {blocker} run={envelope_ref(envelope)}"
        envelope.finish(status="blocked", summary_line=summary, error=exc, returncode=1)
        print(summary)
        return 1

    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
