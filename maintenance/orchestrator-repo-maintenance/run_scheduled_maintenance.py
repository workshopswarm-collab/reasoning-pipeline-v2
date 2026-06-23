#!/usr/bin/env python3
"""Run Orchestrator maintenance on a minimum interval.

This wrapper is intended for launchd/cron. It is conservative: it only runs
`run_maintenance.py` when the prior successful scheduled run is at least
`--interval-days` old, unless `--force` is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAINTENANCE_DIR = Path(__file__).resolve().parent
MAINTENANCE_ROOT = MAINTENANCE_DIR.parent
if str(MAINTENANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_ROOT))

from lib.maintenance_run import (  # noqa: E402
    RunEnvelope,
    SubprocessFailedError,
    atomic_write_json,
    envelope_ref,
    load_json_with_context,
    make_run_id,
    preflight_path_exists,
    preflight_writable_dir,
)
from lib.maintenance_objective_status import build_objective_rollup  # noqa: E402

REPO_ROOT = Path(os.environ.get("ORCHESTRATOR_REPO_ROOT", "/Users/agent2/.openclaw/orchestrator")).resolve()
GENERATED_DIR = MAINTENANCE_DIR / "generated"
RUNS_ROOT = GENERATED_DIR / "runs"
STATE_JSON = GENERATED_DIR / "scheduled-maintenance-state.json"
HISTORY_JSONL = GENERATED_DIR / "scheduled-maintenance-history.jsonl"
CANDIDATE_HISTORY_JSON = GENERATED_DIR / "scheduled-maintenance-candidate-history.json"
CANDIDATE_HISTORY_MD = GENERATED_DIR / "scheduled-maintenance-candidate-history.md"
LOG_PATH = GENERATED_DIR / "scheduled-maintenance.log"
RUN_MAINTENANCE = MAINTENANCE_DIR / "run_maintenance.py"
MAINTENANCE_SUMMARY_JSON = GENERATED_DIR / "maintenance-summary.json"
CLEANUP_PLAN_JSON = GENERATED_DIR / "cleanup-plan.json"
CLEANUP_CANDIDATE_HISTORY_JSON = GENERATED_DIR / "cleanup-candidate-history.json"
CLEANUP_CANDIDATE_HISTORY_MD = GENERATED_DIR / "cleanup-candidate-history.md"
SCRIPT_CLEANUP_BLOCKERS_JSON = GENERATED_DIR / "script-cleanup-blockers.json"
SCRIPT_CLEANUP_BLOCKERS_MD = GENERATED_DIR / "script-cleanup-blockers.md"
SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON = GENERATED_DIR / "script-cleanup-evidence-movement.json"
SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_MD = GENERATED_DIR / "script-cleanup-evidence-movement.md"
ARCHIVE_DRY_RUN_JSON = GENERATED_DIR / "script-archive-dry-run.json"
ARCHIVE_DRY_RUN_MD = GENERATED_DIR / "script-archive-dry-run.md"
ARCHIVE_APPLY_RESULT_JSON = GENERATED_DIR / "script-archive-apply-result.json"
ARCHIVE_APPLY_RESULT_MD = GENERATED_DIR / "script-archive-apply-result.md"
POST_ARCHIVE_SMOKE_JSON = GENERATED_DIR / "post-archive-smoke.json"
POST_ARCHIVE_SMOKE_MD = GENERATED_DIR / "post-archive-smoke.md"
AUTO_ARCHIVE_PROMOTION_JSON = GENERATED_DIR / "script-auto-archive-promotion.json"
DELETE_DRY_RUN_JSON = GENERATED_DIR / "script-delete-dry-run.json"
DELETE_DRY_RUN_MD = GENERATED_DIR / "script-delete-dry-run.md"
DELETE_READINESS_JSON = GENERATED_DIR / "script-delete-readiness.json"
DELETE_APPLY_RESULT_JSON = GENERATED_DIR / "script-delete-apply-result.json"
DELETE_APPLY_RESULT_MD = GENERATED_DIR / "script-delete-apply-result.md"
POST_DELETE_VERIFICATION_JSON = GENERATED_DIR / "post-delete-verification.json"
POST_DELETE_VERIFICATION_MD = GENERATED_DIR / "post-delete-verification.md"
QUARANTINE_MONITOR_JSON = GENERATED_DIR / "script-quarantine-monitor.json"
SCRIPT_AUTO_ARCHIVE_STATE_JSON = GENERATED_DIR / "script-auto-archive-apply-state.json"
SCRIPT_AUTO_ARCHIVE_LOCK = GENERATED_DIR / "script-auto-archive-apply.lock"
SCRIPT_AUTO_DELETE_STATE_JSON = GENERATED_DIR / "script-auto-delete-apply-state.json"
SCRIPT_AUTO_DELETE_LOCK = GENERATED_DIR / "script-auto-delete-apply.lock"


def maintenance_path(path: Path) -> str:
    try:
        return str(path.relative_to(MAINTENANCE_DIR.parent))
    except ValueError:
        return str(path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def load_state() -> dict[str, Any]:
    if not STATE_JSON.exists():
        return {}
    return load_json_with_context(STATE_JSON)


def write_state(payload: dict[str, Any]) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(STATE_JSON, payload)


def append_log(message: str) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as fh:
        fh.write(message.rstrip() + "\n")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def due_to_run(state: dict[str, Any], interval_days: int, now: datetime) -> tuple[bool, str]:
    last_success = parse_timestamp(state.get("last_success_at"))
    if last_success is None:
        return True, "no_prior_success"
    next_due = last_success + timedelta(days=interval_days)
    if now >= next_due:
        return True, "interval_elapsed"
    return False, f"not_due_until_{next_due.isoformat()}"


def run_maintenance(envelope: RunEnvelope) -> subprocess.CompletedProcess[str]:
    return envelope.run_subprocess_with_retries(
        [sys.executable, str(RUN_MAINTENANCE), "--pretty"],
        cwd=REPO_ROOT,
        label="run-maintenance",
        attempts=2,
        backoff_seconds=3.0,
    )


def run_maintenance_script_delete_apply(envelope: RunEnvelope) -> subprocess.CompletedProcess[str]:
    return envelope.run_subprocess(
        [sys.executable, str(RUN_MAINTENANCE), "--apply-script-delete", "--pretty"],
        cwd=REPO_ROOT,
        label="script-auto-delete-apply",
    )


def run_maintenance_script_archive_apply(envelope: RunEnvelope) -> subprocess.CompletedProcess[str]:
    return envelope.run_subprocess(
        [sys.executable, str(RUN_MAINTENANCE), "--apply-script-archive", "--post-archive-smoke", "--quarantine-monitor", "--pretty"],
        cwd=REPO_ROOT,
        label="script-auto-archive-apply",
    )


def run_maintenance_script_evidence_refresh(envelope: RunEnvelope) -> subprocess.CompletedProcess[str]:
    return envelope.run_subprocess_with_retries(
        [sys.executable, str(RUN_MAINTENANCE), "--pretty"],
        cwd=REPO_ROOT,
        label="script-evidence-refresh",
        attempts=2,
        backoff_seconds=3.0,
    )


def acquire_lock(lock_path: Path) -> int | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return None
    os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
    return fd


def release_lock(lock_path: Path, fd: int | None) -> None:
    if fd is not None:
        os.close(fd)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def attach_objective_rollup(
    result: dict[str, Any],
    *,
    plane: str,
    envelope: RunEnvelope,
    scheduler_status: str = "healthy",
    wrapper_status: str | None = None,
) -> dict[str, Any]:
    if wrapper_status is None:
        if result.get("status") == "skipped":
            wrapper_status = "skipped"
        elif result.get("ok") is False or result.get("status") == "blocked":
            wrapper_status = "blocked"
        else:
            wrapper_status = "completed"
    result["objective_rollup"] = build_objective_rollup(
        plane=plane,
        scheduler_status=scheduler_status,
        wrapper_status=wrapper_status,
        wrapper_result=result,
        generated_artifacts=[str(path) for path in envelope.artifact_paths],
    )
    return result


def objective_status_token(result: dict[str, Any]) -> str:
    rollup = result.get("objective_rollup") if isinstance(result.get("objective_rollup"), dict) else {}
    return str(rollup.get("objective_status") or "unknown")


def build_script_evidence_refresh_result(
    summary: dict[str, Any],
    blockers: dict[str, Any],
    movement: dict[str, Any],
) -> dict[str, Any]:
    manual_owner_review_count = int(blockers.get("manual_owner_review_required_count", 0) or 0)
    movement_status = str(movement.get("throughput_status") or "unknown")
    ok = manual_owner_review_count == 0 and movement_status != "owner_review_required"
    return {
        "schema_version": "scheduled-script-evidence-refresh/v1",
        "mode": "script-evidence-refresh",
        "ok": ok,
        "status": "completed" if ok else "blocked",
        "mutating": False,
        "blocked_reason": None if ok else "unowned_cleanup_next_actions",
        "script_count": summary.get("script_classification", {}).get("script_count"),
        "review_candidate_count": summary.get("review_candidate_count"),
        "high_confidence_archive_count": summary.get("cleanup_plan", {}).get("high_confidence_archive_count"),
        "high_confidence_removal_count": summary.get("cleanup_plan", {}).get("high_confidence_removal_count"),
        "cleanup_action_counts": summary.get("cleanup_plan", {}).get("action_counts", {}),
        "autonomous_next_action_count": blockers.get("autonomous_next_action_count", 0),
        "manual_owner_review_required_count": manual_owner_review_count,
        "ready_candidate_slo": blockers.get("ready_candidate_slo", {}),
        "evidence_movement": {
            "throughput_status": movement_status,
            "unknown_reduced_count": movement.get("unknown_reduced_count", 0),
            "new_observed_count": movement.get("new_observed_count", 0),
            "new_referenced_count": movement.get("new_referenced_count", 0),
            "ready_candidate_count": movement.get("ready_candidate_count", 0),
            "retired_candidate_count": movement.get("retired_candidate_count", 0),
            "stranded_unknown_count": movement.get("stranded_unknown_count", 0),
            "blocker_retired_count": movement.get("blocker_retired_count", 0),
            "zero_archive_delete_throughput_acceptable": movement.get("zero_archive_delete_throughput_acceptable", False),
        },
        "next_actions_by_lane": blockers.get("next_actions_by_lane", {}),
        "generated_artifacts": {
            "summary": maintenance_path(MAINTENANCE_SUMMARY_JSON),
            "cleanup_plan": maintenance_path(CLEANUP_PLAN_JSON),
            "blockers": maintenance_path(SCRIPT_CLEANUP_BLOCKERS_JSON),
            "movement": maintenance_path(SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON),
        },
    }


def run_script_evidence_refresh_mode(envelope: RunEnvelope) -> int:
    try:
        preflight(envelope)
        proc = run_maintenance_script_evidence_refresh(envelope)
        summary = read_json_if_exists(MAINTENANCE_SUMMARY_JSON)
        blockers = read_json_if_exists(SCRIPT_CLEANUP_BLOCKERS_JSON)
        movement = read_json_if_exists(SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON)
        result = build_script_evidence_refresh_result(summary, blockers, movement)
        result["last_stdout_tail"] = proc.stdout[-2000:]
        result["run_envelope"] = envelope_ref(envelope)
        for artifact in [
            MAINTENANCE_SUMMARY_JSON,
            CLEANUP_PLAN_JSON,
            CLEANUP_CANDIDATE_HISTORY_JSON,
            CLEANUP_CANDIDATE_HISTORY_MD,
            SCRIPT_CLEANUP_BLOCKERS_JSON,
            SCRIPT_CLEANUP_BLOCKERS_MD,
            SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON,
            SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_MD,
        ]:
            if artifact.exists():
                envelope.add_artifact(artifact)
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope, wrapper_status="completed" if result["ok"] else "blocked")
        status = "ok" if result["ok"] else "blocked"
        summary_line = (
            f"SCRIPT_EVIDENCE_REFRESH_{status.upper()} "
            f"movement={result['evidence_movement']['throughput_status']} "
            f"autonomous_next_actions={result['autonomous_next_action_count']} "
            f"owner_review={result['manual_owner_review_required_count']} "
            f"objective_status={objective_status_token(result)} run={envelope_ref(envelope)}"
        )
        envelope.finish(status=status, summary_line=summary_line, returncode=0 if result["ok"] else 1)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result = {
            "schema_version": "scheduled-script-evidence-refresh/v1",
            "mode": "script-evidence-refresh",
            "ok": False,
            "status": "blocked",
            "mutating": False,
            "blocked_reason": getattr(exc, "error_type", "unexpected_exception"),
            "error_summary": str(exc).splitlines()[0][:1000],
            "run_envelope": envelope_ref(envelope),
        }
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope, wrapper_status="blocked")
        envelope.finish(status="blocked", summary_line=f"SCRIPT_EVIDENCE_REFRESH_BLOCKED {result['blocked_reason']} objective_status={objective_status_token(result)} run={envelope_ref(envelope)}", error=exc, returncode=1)
        print(json.dumps(result, sort_keys=True))
        return 1


def validate_archive_dry_run_evidence(payload: dict[str, Any], promotion: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append({
        "name": "archive_dry_run_schema",
        "status": "ok" if payload.get("schema_version") == "orchestrator-script-archive-dry-run/v1" else "error",
        "detail": str(payload.get("schema_version")),
    })
    checks.append({
        "name": "archive_dry_run_non_mutating",
        "status": "ok" if payload.get("mutating") is False else "error",
        "detail": f"mutating={payload.get('mutating')}",
    })
    checks.append({
        "name": "promotion_schema",
        "status": "ok" if promotion.get("schema_version") == "script-auto-archive-promotion/v1" else "error",
        "detail": str(promotion.get("schema_version")),
    })
    proposals = payload.get("proposals", []) if isinstance(payload.get("proposals"), list) else []
    eligible_paths = set(promotion.get("eligible_paths", [])) if isinstance(promotion.get("eligible_paths"), list) else set()
    for idx, proposal in enumerate(proposals):
        missing = [key for key in ["archive_path", "tombstone_path", "source_path", "source_sha256", "restore_command"] if not proposal.get(key)]
        path = str(proposal.get("source_path") or "")
        checks.append({
            "name": "archive_proposal_shape",
            "status": "ok" if not missing else "error",
            "detail": f"index={idx} missing={missing}",
        })
        checks.append({
            "name": "archive_proposal_has_promotion_evidence",
            "status": "ok" if path in eligible_paths else "error",
            "detail": path,
        })
    return {
        "ok": all(item["status"] == "ok" for item in checks),
        "checks": checks,
        "proposal_count": len(proposals),
        "promotion_eligible_count": len(eligible_paths),
    }


def build_script_auto_archive_apply_result(
    archive_dry_run: dict[str, Any],
    promotion: dict[str, Any],
    archive_apply: dict[str, Any] | None = None,
    post_archive_smoke: dict[str, Any] | None = None,
    quarantine_monitor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_archive_dry_run_evidence(archive_dry_run, promotion)
    archive_apply = archive_apply or {}
    post_archive_smoke = post_archive_smoke or {}
    quarantine_monitor = quarantine_monitor or {}
    apply_schema_ok = not archive_apply or archive_apply.get("schema_version") == "orchestrator-script-archive-apply-result/v1"
    smoke_schema_ok = not post_archive_smoke or post_archive_smoke.get("schema_version") == "orchestrator-post-archive-smoke/v1"
    smoke_ok = bool(post_archive_smoke.get("ok", False)) if post_archive_smoke else False
    monitor_schema_ok = not quarantine_monitor or quarantine_monitor.get("schema_version") == "orchestrator-script-quarantine-monitor/v1"
    monitor_ok = bool(quarantine_monitor.get("ok", False)) if quarantine_monitor else False
    archived_count = int(archive_apply.get("archived_count", 0) or 0) if archive_apply else 0
    skipped_count = int(archive_apply.get("skipped_count", 0) or 0) if archive_apply else 0
    blocked_reason = None
    if not validation["ok"]:
        blocked_reason = "fresh_archive_evidence_validation_failed"
    elif not apply_schema_ok:
        blocked_reason = "archive_apply_result_invalid"
    elif not smoke_schema_ok or not smoke_ok:
        blocked_reason = "post_archive_smoke_failed"
    elif not monitor_schema_ok or not monitor_ok:
        blocked_reason = "quarantine_monitor_failed"
    elif validation["proposal_count"] and archived_count == 0 and skipped_count > 0:
        blocked_reason = "archive_apply_preflight_blocked"
    return {
        "schema_version": "orchestrator-script-auto-archive-apply-run/v1",
        "phase": "H2",
        "mode": "script-auto-archive-apply",
        "mutating": bool(archived_count),
        "ok": blocked_reason is None,
        "status": "archived" if archived_count else ("no_op" if blocked_reason is None else "blocked"),
        "blocked_reason": blocked_reason,
        "archive_dry_run_proposal_count": validation["proposal_count"],
        "fresh_evidence_validation": validation,
        "delegated_apply": {
            "implemented": True,
            "schema_version": archive_apply.get("schema_version"),
            "mode": archive_apply.get("mode"),
            "mutating": bool(archive_apply.get("mutating", False)),
            "archived_count": archived_count,
            "skipped_count": skipped_count,
            "json_path": maintenance_path(ARCHIVE_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(ARCHIVE_APPLY_RESULT_MD),
        },
        "post_archive_smoke": {
            "implemented": True,
            "schema_version": post_archive_smoke.get("schema_version"),
            "ok": smoke_ok,
            "check_count": len(post_archive_smoke.get("checks", [])) if isinstance(post_archive_smoke.get("checks"), list) else 0,
            "json_path": maintenance_path(POST_ARCHIVE_SMOKE_JSON),
            "markdown_path": maintenance_path(POST_ARCHIVE_SMOKE_MD),
        },
        "quarantine_monitor": {
            "implemented": True,
            "schema_version": quarantine_monitor.get("schema_version"),
            "ok": monitor_ok,
            "archived_script_count": int(quarantine_monitor.get("archived_script_count", 0) or 0) if quarantine_monitor else 0,
            "restore_required_count": int(quarantine_monitor.get("restore_required_count", 0) or 0) if quarantine_monitor else 0,
            "json_path": maintenance_path(QUARANTINE_MONITOR_JSON),
        },
        "notes": [
            "H2 delegates to run_maintenance.py --apply-script-archive after lock and fresh deterministic promotion evidence validation.",
            "The delegated archive apply remains at-most-one and revalidates source hash, tombstone path, and gates before moving a script into quarantine.",
            "Post-archive smoke and quarantine monitor must pass before this scheduled mode reports ok.",
        ],
    }


def run_script_auto_archive_apply_mode(envelope: RunEnvelope) -> int:
    lock_fd = acquire_lock(SCRIPT_AUTO_ARCHIVE_LOCK)
    if lock_fd is None:
        result = {
            "schema_version": "orchestrator-script-auto-archive-apply-run/v1",
            "phase": "H2",
            "mode": "script-auto-archive-apply",
            "mutating": False,
            "ok": True,
            "status": "skipped",
            "blocked_reason": "lock_already_held",
            "archive_dry_run_proposal_count": 0,
        }
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope, wrapper_status="skipped")
        atomic_write_json(SCRIPT_AUTO_ARCHIVE_STATE_JSON, result)
        envelope.add_artifact(SCRIPT_AUTO_ARCHIVE_STATE_JSON)
        summary = f"SCRIPT_AUTO_ARCHIVE_APPLY_SKIPPED lock_already_held objective_status={objective_status_token(result)} run={envelope_ref(envelope)}"
        envelope.finish(status="skipped", summary_line=summary, returncode=0)
        print(json.dumps(result, sort_keys=True))
        return 0
    try:
        preflight(envelope)
        proc = run_maintenance_script_archive_apply(envelope)
        archive_dry_run = read_json_if_exists(ARCHIVE_DRY_RUN_JSON)
        promotion = read_json_if_exists(AUTO_ARCHIVE_PROMOTION_JSON)
        archive_apply = read_json_if_exists(ARCHIVE_APPLY_RESULT_JSON)
        post_archive_smoke = read_json_if_exists(POST_ARCHIVE_SMOKE_JSON)
        quarantine_monitor = read_json_if_exists(QUARANTINE_MONITOR_JSON)
        result = build_script_auto_archive_apply_result(archive_dry_run, promotion, archive_apply, post_archive_smoke, quarantine_monitor)
        result["last_stdout_tail"] = proc.stdout[-2000:]
        result["run_envelope"] = envelope_ref(envelope)
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope)
        atomic_write_json(SCRIPT_AUTO_ARCHIVE_STATE_JSON, result)
        for artifact in [SCRIPT_AUTO_ARCHIVE_STATE_JSON, AUTO_ARCHIVE_PROMOTION_JSON, ARCHIVE_DRY_RUN_JSON, ARCHIVE_DRY_RUN_MD, ARCHIVE_APPLY_RESULT_JSON, ARCHIVE_APPLY_RESULT_MD, POST_ARCHIVE_SMOKE_JSON, POST_ARCHIVE_SMOKE_MD, QUARANTINE_MONITOR_JSON]:
            if artifact.exists():
                envelope.add_artifact(artifact)
        status = "ok" if result["ok"] else "blocked"
        summary = f"SCRIPT_AUTO_ARCHIVE_APPLY_{status.upper()} status={result['status']} proposals={result['archive_dry_run_proposal_count']} objective_status={objective_status_token(result)} run={envelope_ref(envelope)}"
        envelope.finish(status=status, summary_line=summary, returncode=0 if result["ok"] else 1)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result = {
            "schema_version": "orchestrator-script-auto-archive-apply-run/v1",
            "phase": "H2",
            "mode": "script-auto-archive-apply",
            "mutating": False,
            "ok": False,
            "status": "blocked",
            "blocked_reason": getattr(exc, "error_type", "unexpected_exception"),
            "error_summary": str(exc).splitlines()[0][:1000],
            "run_envelope": envelope_ref(envelope),
        }
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope, wrapper_status="blocked")
        atomic_write_json(SCRIPT_AUTO_ARCHIVE_STATE_JSON, result)
        envelope.add_artifact(SCRIPT_AUTO_ARCHIVE_STATE_JSON)
        envelope.finish(status="blocked", summary_line=f"SCRIPT_AUTO_ARCHIVE_APPLY_BLOCKED {result['blocked_reason']} objective_status={objective_status_token(result)} run={envelope_ref(envelope)}", error=exc, returncode=1)
        print(json.dumps(result, sort_keys=True))
        return 1
    finally:
        release_lock(SCRIPT_AUTO_ARCHIVE_LOCK, lock_fd)


def validate_delete_dry_run_evidence(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    expected_period = now.strftime("%Y-%m")
    checks.append({
        "name": "delete_dry_run_schema",
        "status": "ok" if payload.get("schema_version") == "orchestrator-script-delete-dry-run/v1" else "error",
        "detail": str(payload.get("schema_version")),
    })
    checks.append({
        "name": "delete_dry_run_non_mutating",
        "status": "ok" if payload.get("mutating") is False else "error",
        "detail": f"mutating={payload.get('mutating')}",
    })
    checks.append({
        "name": "delete_dry_run_current_month",
        "status": "ok" if payload.get("evidence_period") == expected_period else "error",
        "detail": f"expected={expected_period} actual={payload.get('evidence_period')}",
    })
    operations = payload.get("operations", []) if isinstance(payload.get("operations"), list) else []
    for idx, operation in enumerate(operations):
        missing = [key for key in ["archive_path", "tombstone_path", "source_path", "required_preflight"] if not operation.get(key)]
        checks.append({
            "name": "delete_operation_preflight_shape",
            "status": "ok" if not missing else "error",
            "detail": f"index={idx} missing={missing}",
        })
    return {
        "ok": all(item["status"] == "ok" for item in checks),
        "checks": checks,
        "operation_count": len(operations),
    }


def build_script_auto_delete_apply_result(
    delete_dry_run: dict[str, Any],
    now: datetime,
    delete_apply: dict[str, Any] | None = None,
    post_delete_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_delete_dry_run_evidence(delete_dry_run, now)
    operations = delete_dry_run.get("operations", []) if isinstance(delete_dry_run.get("operations"), list) else []
    delete_apply = delete_apply or {}
    post_delete_verification = post_delete_verification or {}
    apply_schema_ok = not delete_apply or delete_apply.get("schema_version") == "orchestrator-script-delete-apply-result/v1"
    post_delete_schema_ok = not post_delete_verification or post_delete_verification.get("schema_version") == "orchestrator-script-post-delete-verification/v1"
    post_delete_ok = bool(post_delete_verification.get("ok", False)) if post_delete_verification else False
    apply_deleted_count = int(delete_apply.get("deleted_count", 0) or 0) if delete_apply else 0
    apply_skipped_count = int(delete_apply.get("skipped_count", 0) or 0) if delete_apply else 0
    blocked_reason = None
    if not validation["ok"]:
        blocked_reason = "fresh_evidence_validation_failed"
    elif not apply_schema_ok:
        blocked_reason = "delete_apply_result_invalid"
    elif not post_delete_schema_ok or not post_delete_ok:
        blocked_reason = "post_delete_verification_failed"
    elif operations and apply_deleted_count == 0 and apply_skipped_count > 0:
        blocked_reason = "delete_apply_preflight_blocked"
    return {
        "schema_version": "orchestrator-script-auto-delete-apply-run/v1",
        "phase": "G6",
        "mode": "script-auto-delete-apply",
        "mutating": bool(apply_deleted_count),
        "ok": blocked_reason is None,
        "status": "deleted" if apply_deleted_count else ("no_op" if blocked_reason is None else "blocked"),
        "blocked_reason": blocked_reason,
        "delete_dry_run_operation_count": len(operations),
        "fresh_evidence_validation": validation,
        "delegated_apply": {
            "implemented": True,
            "schema_version": delete_apply.get("schema_version"),
            "mode": delete_apply.get("mode"),
            "mutating": bool(delete_apply.get("mutating", False)),
            "deleted_count": apply_deleted_count,
            "skipped_count": apply_skipped_count,
            "json_path": maintenance_path(DELETE_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(DELETE_APPLY_RESULT_MD),
        },
        "post_delete_verification": {
            "implemented": True,
            "schema_version": post_delete_verification.get("schema_version"),
            "mode": post_delete_verification.get("mode"),
            "ok": post_delete_ok,
            "deleted_count": int(post_delete_verification.get("deleted_count", 0) or 0) if post_delete_verification else 0,
            "check_count": int(post_delete_verification.get("check_count", 0) or 0) if post_delete_verification else 0,
            "json_path": maintenance_path(POST_DELETE_VERIFICATION_JSON),
            "markdown_path": maintenance_path(POST_DELETE_VERIFICATION_MD),
        },
        "notes": [
            "G6 delegates to run_maintenance.py --apply-script-delete after lock and fresh evidence validation.",
            "The delegated apply remains at-most-one and revalidates archive/tombstone/source/hash preflights before deletion.",
            "The delegated apply also runs post-apply and post-delete verification before this scheduled mode reports ok.",
        ],
    }


def run_script_auto_delete_apply_mode(envelope: RunEnvelope) -> int:
    now = utc_now()
    lock_fd = acquire_lock(SCRIPT_AUTO_DELETE_LOCK)
    if lock_fd is None:
        result = {
            "schema_version": "orchestrator-script-auto-delete-apply-run/v1",
            "phase": "G6",
            "mode": "script-auto-delete-apply",
            "mutating": False,
            "ok": True,
            "status": "skipped",
            "blocked_reason": "lock_already_held",
            "delete_dry_run_operation_count": 0,
        }
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope, wrapper_status="skipped")
        atomic_write_json(SCRIPT_AUTO_DELETE_STATE_JSON, result)
        envelope.add_artifact(SCRIPT_AUTO_DELETE_STATE_JSON)
        summary = f"SCRIPT_AUTO_DELETE_APPLY_SKIPPED lock_already_held objective_status={objective_status_token(result)} run={envelope_ref(envelope)}"
        envelope.finish(status="skipped", summary_line=summary, returncode=0)
        print(json.dumps(result, sort_keys=True))
        return 0
    try:
        preflight(envelope)
        proc = run_maintenance_script_delete_apply(envelope)
        dry_run = read_json_if_exists(DELETE_DRY_RUN_JSON)
        delete_apply = read_json_if_exists(DELETE_APPLY_RESULT_JSON)
        post_delete_verification = read_json_if_exists(POST_DELETE_VERIFICATION_JSON)
        result = build_script_auto_delete_apply_result(dry_run, now, delete_apply, post_delete_verification)
        result["last_stdout_tail"] = proc.stdout[-2000:]
        result["run_envelope"] = envelope_ref(envelope)
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope)
        atomic_write_json(SCRIPT_AUTO_DELETE_STATE_JSON, result)
        for artifact in [SCRIPT_AUTO_DELETE_STATE_JSON, DELETE_DRY_RUN_JSON, DELETE_DRY_RUN_MD, DELETE_APPLY_RESULT_JSON, DELETE_APPLY_RESULT_MD, POST_DELETE_VERIFICATION_JSON, POST_DELETE_VERIFICATION_MD, DELETE_READINESS_JSON, QUARANTINE_MONITOR_JSON]:
            if artifact.exists():
                envelope.add_artifact(artifact)
        status = "ok" if result["ok"] else "blocked"
        summary = f"SCRIPT_AUTO_DELETE_APPLY_{status.upper()} status={result['status']} operations={result['delete_dry_run_operation_count']} objective_status={objective_status_token(result)} run={envelope_ref(envelope)}"
        envelope.finish(status=status, summary_line=summary, returncode=0 if result["ok"] else 1)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result = {
            "schema_version": "orchestrator-script-auto-delete-apply-run/v1",
            "phase": "G6",
            "mode": "script-auto-delete-apply",
            "mutating": False,
            "ok": False,
            "status": "blocked",
            "blocked_reason": getattr(exc, "error_type", "unexpected_exception"),
            "error_summary": str(exc).splitlines()[0][:1000],
            "run_envelope": envelope_ref(envelope),
        }
        attach_objective_rollup(result, plane=envelope.job_name, envelope=envelope, wrapper_status="blocked")
        atomic_write_json(SCRIPT_AUTO_DELETE_STATE_JSON, result)
        envelope.add_artifact(SCRIPT_AUTO_DELETE_STATE_JSON)
        envelope.finish(status="blocked", summary_line=f"SCRIPT_AUTO_DELETE_APPLY_BLOCKED {result['blocked_reason']} objective_status={objective_status_token(result)} run={envelope_ref(envelope)}", error=exc, returncode=1)
        print(json.dumps(result, sort_keys=True))
        return 1
    finally:
        release_lock(SCRIPT_AUTO_DELETE_LOCK, lock_fd)


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json_with_context(path)


def preflight(envelope: RunEnvelope) -> None:
    preflight_path_exists(REPO_ROOT, "Orchestrator repo root")
    preflight_path_exists(RUN_MAINTENANCE, "run_maintenance.py")
    preflight_path_exists(MAINTENANCE_DIR / "script_classifier.py", "script_classifier.py")
    preflight_writable_dir(GENERATED_DIR, "Orchestrator maintenance generated directory")
    preflight_writable_dir(RUNS_ROOT, "Orchestrator maintenance run directory")
    overrides = MAINTENANCE_DIR / "script-lifecycle-overrides.json"
    if overrides.exists():
        load_json_with_context(overrides)
    else:
        envelope.warnings.append(f"lifecycle overrides missing/non-fatal: {overrides}")


def cleanup_delete_readiness_guard(cleanup_plan: dict[str, Any]) -> dict[str, Any]:
    script_actions = cleanup_plan.get("script_review_actions", []) if isinstance(cleanup_plan.get("script_review_actions"), list) else []
    planned_delete_ready = sorted(str(item.get("path")) for item in script_actions if item.get("planned_action") == "auto_delete_ready")
    gate_delete_ready = sorted(
        str(item.get("path"))
        for item in script_actions
        if item.get("cleanup_gate_evaluation", {}).get("delete", {}).get("ready")
    )
    summary = cleanup_plan.get("summary", {}) if isinstance(cleanup_plan.get("summary"), dict) else {}
    guard_paths = sorted(set(planned_delete_ready) | set(gate_delete_ready))
    return {
        "schema_version": "scheduled-cleanup-delete-readiness-guard/v1",
        "mode": "report_only",
        "ok": not guard_paths,
        "premature_delete_ready_count": len(guard_paths),
        "planned_delete_ready_paths": planned_delete_ready,
        "gate_delete_ready_paths": gate_delete_ready,
        "gate_ready_delete_count": int(summary.get("gate_ready_counts", {}).get("delete", 0) or 0) if isinstance(summary.get("gate_ready_counts"), dict) else 0,
        "note": "D4 guard verifies scheduled maintenance did not surface delete-ready script candidates before archive/quarantine phases.",
    }


def cleanup_candidate_history_summary() -> dict[str, Any]:
    history = read_json_if_exists(CLEANUP_CANDIDATE_HISTORY_JSON)
    if not history:
        return {"available": False}
    return {
        "available": True,
        "schema_version": history.get("schema_version"),
        "candidate_count": history.get("candidate_count", 0),
        "mature_no_use_candidate_count": history.get("mature_no_use_candidate_count", 0),
        "json_path": maintenance_path(CLEANUP_CANDIDATE_HISTORY_JSON),
        "markdown_path": maintenance_path(CLEANUP_CANDIDATE_HISTORY_MD),
    }


def append_history_record(ran_at: datetime, reason: str) -> dict[str, Any]:
    summary = read_json_if_exists(MAINTENANCE_SUMMARY_JSON)
    cleanup_plan = read_json_if_exists(CLEANUP_PLAN_JSON)
    blockers = read_json_if_exists(SCRIPT_CLEANUP_BLOCKERS_JSON)
    movement = read_json_if_exists(SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON)
    delete_guard = cleanup_delete_readiness_guard(cleanup_plan)
    record = {
        "ran_at": ran_at.isoformat(),
        "reason": reason,
        "script_count": summary.get("script_classification", {}).get("script_count"),
        "review_candidate_count": summary.get("review_candidate_count"),
        "medium_confidence_count": summary.get("medium_confidence_count"),
        "repo_health_overall_score": summary.get("repo_health", {}).get("overall_score"),
        "cleanup_action_counts": cleanup_plan.get("summary", {}).get("action_counts", {}),
        "high_confidence_archive_count": cleanup_plan.get("summary", {}).get("high_confidence_archive_count", 0),
        "high_confidence_removal_count": cleanup_plan.get("summary", {}).get("high_confidence_removal_count", 0),
        "gate_evaluation_mode": cleanup_plan.get("summary", {}).get("gate_evaluation_mode"),
        "gate_ready_counts": cleanup_plan.get("summary", {}).get("gate_ready_counts", {}),
        "cleanup_candidate_history": cleanup_candidate_history_summary(),
        "script_cleanup_blockers": {
            "autonomous_next_action_count": blockers.get("autonomous_next_action_count", 0),
            "manual_owner_review_required_count": blockers.get("manual_owner_review_required_count", 0),
            "ready_candidate_slo": blockers.get("ready_candidate_slo", {}),
        },
        "script_cleanup_evidence_movement": {
            "throughput_status": movement.get("throughput_status"),
            "unknown_reduced_count": movement.get("unknown_reduced_count", 0),
            "new_observed_count": movement.get("new_observed_count", 0),
            "new_referenced_count": movement.get("new_referenced_count", 0),
            "ready_candidate_count": movement.get("ready_candidate_count", 0),
            "retired_candidate_count": movement.get("retired_candidate_count", 0),
            "stranded_unknown_count": movement.get("stranded_unknown_count", 0),
            "blocker_retired_count": movement.get("blocker_retired_count", 0),
        },
        "delete_readiness_guard": delete_guard,
    }
    with HISTORY_JSONL.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def confidence_stage(action: str, consecutive: int, failed_checks: list[str]) -> str:
    if action in {"auto_delete_ready", "high_confidence_removal_candidate"}:
        return "high_confidence_removal_ready"
    if action in {"auto_archive_ready", "high_confidence_archive_candidate"}:
        return "high_confidence_archive_ready"
    if action in {"archive_review_candidate", "manual_lifecycle_review"} and consecutive >= 4:
        return "stable_review_candidate"
    if action in {"archive_review_candidate", "manual_lifecycle_review"} and consecutive >= 2:
        return "strengthening_review_candidate"
    if action in {"archive_review_candidate", "manual_lifecycle_review"}:
        return "new_or_changed_review_candidate"
    if failed_checks:
        return "retained_with_failed_checks"
    return "retained_or_not_actionable"


def confidence_score(action: str, consecutive: int, failed_checks: list[str]) -> int:
    if action in {"auto_delete_ready", "high_confidence_removal_candidate"}:
        return 100
    if action in {"auto_archive_ready", "high_confidence_archive_candidate"}:
        return 90
    base_by_action = {
        "archive_review_candidate": 45,
        "manual_lifecycle_review": 35,
        "retain_review_surface": 10,
        "retain_referenced": 8,
        "retain_recently_used": 8,
        "manual_review_required": 5,
    }
    score = base_by_action.get(action, 5)
    score += min(consecutive, 6) * 5
    score -= min(len(failed_checks), 8) * 3
    return max(0, min(score, 85))


def next_checks(failed_checks: list[str]) -> list[str]:
    labels = {
        "lifecycle_approved": "decide whether lifecycle status should become archive_approved or removal_approved",
        "operator_docs_checked": "search operator docs/runbooks for references",
        "launchd_cron_checked": "check launchd, cron, and other scheduler references",
        "external_usage_checked": "check shell wrappers, known manual workflows, and external invocation paths",
        "runtime_state_checked": "confirm runtime/generated state does not depend on this script",
        "archive_path_defined": "define the archive/retired namespace before any move",
        "underlying_condition_resolved_if_needed": "prove the repair/backfill condition is fixed and recurrence is prevented",
        "archived_for_one_cycle": "wait at least one scheduled maintenance cycle after archival before deletion",
    }
    return [labels.get(check, f"satisfy `{check}`") for check in failed_checks]


def render_candidate_history_markdown(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", {})
    ordered = sorted(
        candidates.items(),
        key=lambda kv: (-int(kv[1].get("confidence_score", 0) or 0), kv[0]),
    )
    lines = ["# Scheduled Maintenance Candidate History", ""]
    lines.append(f"Updated at: `{payload.get('updated_at')}`")
    lines.append(f"Candidate count: **{payload.get('candidate_count', 0)}**")
    lines.append("")
    lines.append("This report turns repeated scheduled observations into advisory confidence evidence. It does not approve deletion by itself.")
    lines.append("")
    lines.append("## Confidence ladder")
    lines.append("")
    lines.append("1. `new_or_changed_review_candidate` — first observed or changed action.")
    lines.append("2. `strengthening_review_candidate` — same review/archive action for at least 2 consecutive scheduled runs.")
    lines.append("3. `stable_review_candidate` — same review/archive action for at least 4 consecutive scheduled runs.")
    lines.append("4. `high_confidence_archive_ready` — explicit lifecycle approval and verification checks satisfied.")
    lines.append("5. `high_confidence_removal_ready` — archive-ready plus archived for at least one cycle and removal-approved.")
    lines.append("")
    lines.append("## Candidates")
    lines.append("")
    for path, item in ordered:
        failed = item.get("failed_high_confidence_checks", [])
        lines.append(f"### `{path}`")
        lines.append("")
        lines.append(f"- Stage: `{item.get('confidence_stage')}`")
        lines.append(f"- Advisory score: `{item.get('confidence_score')}`")
        lines.append(f"- Last action: `{item.get('last_planned_action')}`")
        lines.append(f"- Classification: `{item.get('last_classification')}`")
        lines.append(f"- Consecutive same-action runs: `{item.get('consecutive_same_action_count')}`")
        lines.append(f"- Reason: {item.get('last_reason')}")
        if failed:
            lines.append(f"- Failed high-confidence checks: `{', '.join(failed)}`")
            lines.append("- Next checks:")
            for check in item.get("next_checks", []):
                lines.append(f"  - {check}")
        else:
            lines.append("- Failed high-confidence checks: _None._")
        lines.append("")
    return "\n".join(lines)


def update_candidate_history(ran_at: datetime) -> dict[str, Any]:
    cleanup_plan = read_json_if_exists(CLEANUP_PLAN_JSON)
    existing = read_json_if_exists(CANDIDATE_HISTORY_JSON)
    candidates: dict[str, Any] = existing.get("candidates", {}) if isinstance(existing.get("candidates"), dict) else {}
    current_actions = {item.get("path"): item for item in cleanup_plan.get("script_review_actions", []) if item.get("path")}
    for path, item in sorted(current_actions.items()):
        prior = candidates.get(path, {})
        prior_action = prior.get("last_planned_action")
        consecutive = int(prior.get("consecutive_same_action_count", 0) or 0)
        if prior_action == item.get("planned_action"):
            consecutive += 1
        else:
            consecutive = 1
        high_confidence = item.get("high_confidence", {}) if isinstance(item.get("high_confidence", {}), dict) else {}
        failed_checks = high_confidence.get("failed_checks", [])
        action = str(item.get("planned_action"))
        candidates[path] = {
            "first_seen_at": prior.get("first_seen_at", ran_at.isoformat()),
            "last_seen_at": ran_at.isoformat(),
            "last_planned_action": action,
            "last_classification": item.get("classification"),
            "last_reason": item.get("reason"),
            "consecutive_same_action_count": consecutive,
            "failed_high_confidence_checks": failed_checks,
            "next_checks": next_checks(failed_checks),
            "confidence_stage": confidence_stage(action, consecutive, failed_checks),
            "confidence_score": confidence_score(action, consecutive, failed_checks),
            "stability_evidence": "strengthening" if consecutive >= 2 else "new_or_changed",
        }
    current_paths = set(current_actions)
    for path, prior in list(candidates.items()):
        if path not in current_paths:
            prior["last_absent_at"] = ran_at.isoformat()
            prior["stability_evidence"] = "absent_from_latest_cleanup_plan"
            prior["confidence_stage"] = "absent_from_latest_cleanup_plan"
            candidates[path] = prior
    payload = {
        "schema_version": "orchestrator-scheduled-maintenance-candidate-history/v2",
        "updated_at": ran_at.isoformat(),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "note": "Stability evidence is advisory. High-confidence archive/removal still requires explicit lifecycle approval and verification checks.",
    }
    CANDIDATE_HISTORY_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    CANDIDATE_HISTORY_MD.write_text(render_candidate_history_markdown(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Orchestrator maintenance when the configured interval has elapsed")
    parser.add_argument("--interval-days", type=int, default=14, help="minimum days between successful scheduled maintenance runs")
    parser.add_argument("--force", action="store_true", help="run even if the interval has not elapsed")
    parser.add_argument("--mode", choices=["scheduled-audit", "script-evidence-refresh", "script-auto-archive-apply", "script-auto-delete-apply"], default="scheduled-audit")
    args = parser.parse_args()

    if args.interval_days < 1:
        raise SystemExit("--interval-days must be at least 1")

    job_names = {
        "scheduled-audit": "Maintenance: Orchestrator Repo Maintenance Audit",
        "script-evidence-refresh": "Maintenance: Orchestrator Script Evidence Refresh",
        "script-auto-archive-apply": "Maintenance: Orchestrator Script Auto-Archive Apply",
        "script-auto-delete-apply": "Maintenance: Orchestrator Script Auto-Delete Apply",
    }
    envelope = RunEnvelope(
        job_name=job_names[args.mode],
        mode=("scheduled-wrapper-force" if args.force else "scheduled-wrapper") if args.mode == "scheduled-audit" else args.mode,
        runs_root=RUNS_ROOT,
        workspace_root=MAINTENANCE_ROOT,
        run_id=make_run_id("orchestrator-repo"),
    )

    if args.mode == "script-evidence-refresh":
        return run_script_evidence_refresh_mode(envelope)
    if args.mode == "script-auto-archive-apply":
        return run_script_auto_archive_apply_mode(envelope)
    if args.mode == "script-auto-delete-apply":
        return run_script_auto_delete_apply_mode(envelope)

    now = utc_now()
    try:
        preflight(envelope)
        state = load_state()
    except Exception as exc:
        ran_at = utc_now()
        payload = {
            "last_checked_at": ran_at.isoformat(),
            "last_failure_at": ran_at.isoformat(),
            "last_check_result": "failed",
            "last_check_reason": "preflight",
            "interval_days": args.interval_days,
            "last_error_type": getattr(exc, "error_type", "unexpected_exception"),
            "last_error_summary": str(exc).splitlines()[0][:1000],
            "last_run_envelope": envelope_ref(envelope),
        }
        attach_objective_rollup(payload, plane=envelope.job_name, envelope=envelope, wrapper_status="blocked")
        write_state(payload)
        append_log(f"{ran_at.isoformat()} failed preflight {type(exc).__name__}: {exc}")
        summary = f"ORCHESTRATOR_MAINTENANCE_BLOCKED preflight {type(exc).__name__}: {exc} objective_status={objective_status_token(payload)} run={envelope_ref(envelope)}"
        envelope.finish(status="blocked", summary_line=summary, error=exc, returncode=1)
        print(summary)
        return 1

    should_run, reason = due_to_run(state, args.interval_days, now)
    if not should_run and not args.force:
        payload = {
            **state,
            "last_checked_at": now.isoformat(),
            "last_check_result": "skipped",
            "last_check_reason": reason,
            "interval_days": args.interval_days,
            "last_run_envelope": envelope_ref(envelope),
        }
        attach_objective_rollup(payload, plane=envelope.job_name, envelope=envelope, wrapper_status="skipped")
        write_state(payload)
        append_log(f"{now.isoformat()} skipped {reason}")
        summary = f"ORCHESTRATOR_MAINTENANCE_SKIPPED {reason} objective_status={objective_status_token(payload)} run={envelope_ref(envelope)}"
        envelope.finish(status="skipped", summary_line=summary, returncode=0)
        print(json.dumps({"ran": False, "reason": reason, "objective_rollup": payload["objective_rollup"], "run": envelope_ref(envelope)}, sort_keys=True))
        return 0

    try:
        proc = run_maintenance(envelope)
    except Exception as exc:
        ran_at = utc_now()
        proc = exc.proc if isinstance(exc, SubprocessFailedError) else None
        payload = {
            **state,
            "last_checked_at": ran_at.isoformat(),
            "last_failure_at": ran_at.isoformat(),
            "last_check_result": "failed",
            "last_check_reason": "forced" if args.force else reason,
            "interval_days": args.interval_days,
            "last_returncode": getattr(proc, "returncode", 1),
            "last_stdout_tail": (getattr(proc, "stdout", "") or "")[-4000:],
            "last_stderr_tail": (getattr(proc, "stderr", "") or "")[-4000:],
            "last_error_type": getattr(exc, "error_type", "unexpected_exception"),
            "last_error_summary": str(exc).splitlines()[0][:1000],
            "last_run_envelope": envelope_ref(envelope),
        }
        attach_objective_rollup(payload, plane=envelope.job_name, envelope=envelope, wrapper_status="blocked")
        write_state(payload)
        append_log(f"{ran_at.isoformat()} failed returncode={payload['last_returncode']} {'forced' if args.force else reason}")
        summary = f"ORCHESTRATOR_MAINTENANCE_BLOCKED {payload['last_error_type']} {payload['last_error_summary']} objective_status={objective_status_token(payload)} run={envelope_ref(envelope)}"
        envelope.finish(status="blocked", summary_line=summary, error=exc, returncode=payload["last_returncode"])
        if proc is not None and proc.stderr:
            sys.stderr.write(proc.stderr)
        print(summary)
        return int(payload["last_returncode"] or 1)

    ran_at = utc_now()
    run_reason = "forced" if args.force else reason
    history_record = append_history_record(ran_at, run_reason)
    candidate_history = update_candidate_history(ran_at)
    for artifact in [
        STATE_JSON,
        HISTORY_JSONL,
        CANDIDATE_HISTORY_JSON,
        CANDIDATE_HISTORY_MD,
        MAINTENANCE_SUMMARY_JSON,
        CLEANUP_PLAN_JSON,
        CLEANUP_CANDIDATE_HISTORY_JSON,
        CLEANUP_CANDIDATE_HISTORY_MD,
        SCRIPT_CLEANUP_BLOCKERS_JSON,
        SCRIPT_CLEANUP_BLOCKERS_MD,
        SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON,
        SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_MD,
    ]:
        if artifact.exists():
            envelope.add_artifact(artifact)
    payload = {
        **state,
        "last_checked_at": ran_at.isoformat(),
        "last_success_at": ran_at.isoformat(),
        "last_check_result": "ran",
        "last_check_reason": run_reason,
        "interval_days": args.interval_days,
        "history_path": maintenance_path(HISTORY_JSONL),
        "candidate_history_path": maintenance_path(CANDIDATE_HISTORY_JSON),
        "candidate_history_markdown_path": maintenance_path(CANDIDATE_HISTORY_MD),
        "candidate_history_count": candidate_history["candidate_count"],
        "cleanup_candidate_history": cleanup_candidate_history_summary(),
        "delete_readiness_guard": history_record.get("delete_readiness_guard", {}),
        "last_history_record": history_record,
        "last_stdout_tail": proc.stdout[-4000:],
        "last_run_envelope": envelope_ref(envelope),
    }
    if not history_record.get("delete_readiness_guard", {}).get("ok", True):
        payload["blocked_reason"] = "delete_readiness_guard"
    attach_objective_rollup(payload, plane=envelope.job_name, envelope=envelope)
    write_state(payload)
    if not history_record.get("delete_readiness_guard", {}).get("ok", True):
        envelope.warnings.append("cleanup delete readiness guard found report-only delete-ready candidates")
    append_log(f"{ran_at.isoformat()} ran {'forced' if args.force else reason} delete_guard_ok={history_record.get('delete_readiness_guard', {}).get('ok', True)}")
    summary = f"ORCHESTRATOR_MAINTENANCE_OK reason={payload['last_check_reason']} objective_status={objective_status_token(payload)} run={envelope_ref(envelope)}"
    envelope.finish(status="ok", summary_line=summary, returncode=0)
    print(json.dumps({"ran": True, "reason": payload["last_check_reason"], "state": maintenance_path(STATE_JSON), "objective_rollup": payload["objective_rollup"], "run": envelope_ref(envelope)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
