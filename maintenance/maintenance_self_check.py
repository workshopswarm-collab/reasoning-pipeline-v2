#!/usr/bin/env python3
"""Maintenance workspace health/self-check rollup."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lib.maintenance_objective_status import (  # noqa: E402
    build_objective_rollup,
    wrapper_status_from_envelope_status,
)

ROOT = Path(__file__).resolve().parent
EXPECTED_JOBS = [
    "Maintenance: Workbench Context Prune Audit",
    "Maintenance: Workbench Context Prune Auto-Apply",
    "Maintenance: Workbench Context Prune Pressure Check",
    "Maintenance: Orchestrator Repo Maintenance Audit",
    "Maintenance: Orchestrator Script Evidence Refresh",
    "Maintenance: Orchestrator Script Auto-Archive Apply",
    "Maintenance: Orchestrator Script Auto-Delete Apply",
]
CHECK_JSON = ROOT / "generated" / "maintenance-self-check.json"
CHECK_MD = ROOT / "generated" / "maintenance-self-check.md"
SCRIPT_USAGE_SUMMARY_JSON = ROOT / "orchestrator-repo-maintenance" / "generated" / "script-usage-summary.json"
SCRIPT_USAGE_SUMMARY_MD = ROOT / "orchestrator-repo-maintenance" / "generated" / "script-usage-summary.md"
SCRIPT_CLASSIFICATION_JSON = ROOT / "orchestrator-repo-maintenance" / "generated" / "script-classification.json"
WORKBENCH_RUNS_ROOT = ROOT / "workbench-context-maintenance" / "generated" / "runs"
ORCHESTRATOR_RUNS_ROOT = ROOT / "orchestrator-repo-maintenance" / "generated" / "runs"
JOB_RUN_ROOTS = {
    "Maintenance: Workbench Context Prune Audit": WORKBENCH_RUNS_ROOT,
    "Maintenance: Workbench Context Prune Auto-Apply": WORKBENCH_RUNS_ROOT,
    "Maintenance: Workbench Context Prune Pressure Check": WORKBENCH_RUNS_ROOT,
    "Maintenance: Orchestrator Repo Maintenance Audit": ORCHESTRATOR_RUNS_ROOT,
    "Maintenance: Orchestrator Script Evidence Refresh": ORCHESTRATOR_RUNS_ROOT,
    "Maintenance: Orchestrator Script Auto-Archive Apply": ORCHESTRATOR_RUNS_ROOT,
    "Maintenance: Orchestrator Script Auto-Delete Apply": ORCHESTRATOR_RUNS_ROOT,
}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def check_path(checks: list[Check], path: Path, name: str, *, directory: bool = False) -> None:
    if not path.exists():
        checks.append(Check(name, "error", f"missing: {path}"))
    elif directory and not path.is_dir():
        checks.append(Check(name, "error", f"not a directory: {path}"))
    elif not directory and not path.is_file():
        checks.append(Check(name, "error", f"not a file: {path}"))
    else:
        checks.append(Check(name, "ok", str(path)))


def check_json_file(checks: list[Check], path: Path, name: str) -> None:
    try:
        payload = load_json(path)
        if isinstance(payload, dict):
            checks.append(Check(name, "ok", f"parsed object keys={len(payload)} path={path}"))
        else:
            checks.append(Check(name, "warning", f"parsed non-object JSON type={type(payload).__name__} path={path}"))
    except Exception as exc:
        checks.append(Check(name, "error", f"{path}: {type(exc).__name__}: {exc}"))


def latest_envelope(runs_root: Path) -> Path | None:
    if not runs_root.exists():
        return None
    envelopes = sorted(runs_root.glob("*/envelope.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return envelopes[0] if envelopes else None


def latest_envelope_for_job(runs_root: Path, job_name: str) -> Path | None:
    if not runs_root.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for envelope in runs_root.glob("*/envelope.json"):
        try:
            payload = load_json(envelope)
        except Exception:
            continue
        if payload.get("job_name") != job_name:
            continue
        try:
            mtime = envelope.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, envelope))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def check_latest_envelope(checks: list[Check], runs_root: Path, name: str) -> None:
    env = latest_envelope(runs_root)
    if env is None:
        checks.append(Check(name, "warning", f"no envelope found under {runs_root}"))
        return
    try:
        payload = load_json(env)
        status = payload.get("status")
        if status in {"ok", "skipped"}:
            checks.append(Check(name, "ok", f"latest status={status} envelope={env.relative_to(ROOT)}"))
        else:
            checks.append(Check(name, "warning", f"latest status={status} envelope={env.relative_to(ROOT)}"))
    except Exception as exc:
        checks.append(Check(name, "error", f"invalid envelope {env}: {exc}"))


def scheduler_status_for_job(job: dict[str, Any] | None) -> str:
    if not isinstance(job, dict):
        return "missing"
    if job.get("agentId") != "maintenance":
        return "warning"
    if not job.get("failureAlert"):
        return "warning"
    if job.get("state", {}).get("lastStatus") not in {"ok", None}:
        return "warning"
    return "healthy"


def cron_jobs_by_name(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return {}
    return {str(job.get("name")): job for job in jobs if isinstance(job, dict) and job.get("name")}


def load_wrapper_summary_for_envelope(envelope_path: Path | None) -> dict[str, Any]:
    if envelope_path is None:
        return {}
    wrapper_summary = envelope_path.parent / "wrapper-summary.json"
    if wrapper_summary.exists():
        try:
            return load_json(wrapper_summary)
        except Exception:
            return {}
    try:
        envelope = load_json(envelope_path)
    except Exception:
        return {}
    return envelope if isinstance(envelope, dict) else {}


def objective_rollups_from_cron_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    jobs_by_name = cron_jobs_by_name(payload)
    rollups: list[dict[str, Any]] = []
    for job_name in EXPECTED_JOBS:
        runs_root = JOB_RUN_ROOTS.get(job_name, ROOT / "generated" / "runs")
        envelope_path = latest_envelope_for_job(runs_root, job_name)
        try:
            envelope = load_json(envelope_path) if envelope_path is not None else {}
        except Exception:
            envelope = {}
        wrapper_result = load_wrapper_summary_for_envelope(envelope_path)
        artifacts = envelope.get("artifact_paths") if isinstance(envelope.get("artifact_paths"), list) else []
        rollups.append(
            build_objective_rollup(
                plane=job_name,
                scheduler_status=scheduler_status_for_job(jobs_by_name.get(job_name)),
                wrapper_status=wrapper_status_from_envelope_status(envelope.get("status")),
                wrapper_result=wrapper_result,
                generated_artifacts=[str(item) for item in artifacts],
            )
        )
    return rollups


def run_compile_check(checks: list[Check]) -> None:
    scripts = [
        ROOT / "lib" / "maintenance_run.py",
        ROOT / "lib" / "maintenance_phase0.py",
        ROOT / "lib" / "maintenance_objective_status.py",
        ROOT / "git_origin_main_guard.py",
        ROOT / "maintenance_self_check.py",
        ROOT / "workbench-context-maintenance" / "scripts" / "context_usage_prune.py",
        ROOT / "workbench-context-maintenance" / "scripts" / "run_context_prune_maintenance.py",
        ROOT / "orchestrator-repo-maintenance" / "run_scheduled_maintenance.py",
        ROOT / "orchestrator-repo-maintenance" / "run_maintenance.py",
        ROOT / "orchestrator-repo-maintenance" / "script_usage_materializer.py",
    ]
    proc = subprocess.run([sys.executable, "-m", "py_compile", *map(str, scripts)], cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode == 0:
        checks.append(Check("python_compile", "ok", f"compiled {len(scripts)} scripts"))
    else:
        checks.append(Check("python_compile", "error", (proc.stderr or proc.stdout)[-1000:]))


def parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def check_script_usage_summary(checks: list[Check], *, max_age_hours: int = 48, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    try:
        usage = load_json(SCRIPT_USAGE_SUMMARY_JSON)
    except Exception as exc:
        checks.append(Check("script_usage_summary", "error", f"{SCRIPT_USAGE_SUMMARY_JSON}: {type(exc).__name__}: {exc}"))
        return
    try:
        classification = load_json(SCRIPT_CLASSIFICATION_JSON)
    except Exception as exc:
        checks.append(Check("script_usage_summary", "error", f"classifier unavailable for join validation: {type(exc).__name__}: {exc}"))
        return

    problems: list[str] = []
    if usage.get("schema_version") != "openclaw-script-usage-summary/v1":
        problems.append(f"unexpected_schema={usage.get('schema_version')}")
    if usage.get("phase") not in {"C4", "C5"}:
        problems.append(f"unexpected_phase={usage.get('phase')}")
    generated_at = parse_iso_timestamp(usage.get("generated_at_utc"))
    if generated_at is None:
        problems.append("missing_or_invalid_generated_at_utc")
    elif now - generated_at > timedelta(hours=max_age_hours):
        problems.append(f"stale_generated_at_utc={usage.get('generated_at_utc')}")
    scripts = usage.get("scripts")
    records = classification.get("records")
    if not isinstance(scripts, list):
        problems.append("scripts_not_list")
    if not isinstance(records, list):
        problems.append("classifier_records_not_list")
    if isinstance(scripts, list) and isinstance(records, list) and len(scripts) != len(records):
        problems.append(f"join_incomplete scripts={len(scripts)} classifier_records={len(records)}")
    summary = usage.get("summary", {}) if isinstance(usage.get("summary"), dict) else {}
    if summary.get("classified_script_count") != (len(records) if isinstance(records, list) else None):
        problems.append("classified_script_count_mismatch")
    if int(summary.get("parse_issue_count") or 0) != 0:
        problems.append(f"parse_issue_count={summary.get('parse_issue_count')}")
    if int(summary.get("unmatched_ledger_script_count") or 0) != 0:
        problems.append(f"unmatched_ledger_script_count={summary.get('unmatched_ledger_script_count')}")
    if not SCRIPT_USAGE_SUMMARY_MD.exists():
        problems.append(f"missing_markdown={SCRIPT_USAGE_SUMMARY_MD}")

    if problems:
        checks.append(Check("script_usage_summary", "error", "; ".join(problems)))
    else:
        checks.append(Check("script_usage_summary", "ok", f"fresh complete join: scripts={len(scripts)} generated_at={usage.get('generated_at_utc')}"))


def load_cron_inventory_payload(checks: list[Check]) -> dict[str, Any] | None:
    proc = subprocess.run(["openclaw", "cron", "list", "--all", "--json"], cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        checks.append(Check("cron_inventory", "warning", f"openclaw cron list failed: {(proc.stderr or proc.stdout)[-500:]}"))
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        checks.append(Check("cron_inventory", "warning", f"non-json cron output: {exc}"))
        return None
    return payload


def run_cron_check(checks: list[Check], payload: dict[str, Any] | None = None) -> None:
    if payload is None:
        payload = load_cron_inventory_payload(checks)
    if payload is None:
        return
    by_name = cron_jobs_by_name(payload)
    missing = [name for name in EXPECTED_JOBS if name not in by_name]
    if missing:
        checks.append(Check("cron_inventory", "error", f"missing expected jobs: {missing}"))
        return
    bad: list[str] = []
    for name in EXPECTED_JOBS:
        job = by_name[name]
        if job.get("agentId") != "maintenance":
            bad.append(f"{name}: agentId={job.get('agentId')}")
        if not job.get("failureAlert"):
            bad.append(f"{name}: missing failureAlert")
        if job.get("state", {}).get("lastStatus") not in {"ok", None}:
            bad.append(f"{name}: lastStatus={job.get('state', {}).get('lastStatus')}")
    if bad:
        checks.append(Check("cron_inventory", "warning", "; ".join(bad)))
    else:
        checks.append(Check("cron_inventory", "ok", f"{len(EXPECTED_JOBS)} expected jobs present with failure alerts"))


def render_md(payload: dict[str, Any]) -> str:
    lines = ["# Maintenance Self-Check", "", f"Updated: `{payload['updated_at']}`", f"Overall: **{payload['overall_status']}**", "", "## Checks", ""]
    for item in payload["checks"]:
        lines.append(f"- **{item['status']}** `{item['name']}` — {item.get('detail', '')}")
    lines.extend(["", "## Objective Rollups", ""])
    for item in payload.get("objective_rollups", []):
        lines.append(
            f"- **{item['objective_status']}** `{item['plane']}` — "
            f"scheduler={item['scheduler_status']} wrapper={item['wrapper_status']} "
            f"mutations={item['mutation_count']} degraded={len(item.get('degraded_reasons', []))}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Maintenance self-check rollup")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    checks: list[Check] = []
    for path, name, is_dir in [
        (ROOT / "lib", "lib_dir", True),
        (ROOT / "workbench-context-maintenance" / "generated" / "runs", "workbench_runs_dir", True),
        (ROOT / "orchestrator-repo-maintenance" / "generated" / "runs", "orchestrator_runs_dir", True),
        (ROOT / "context" / "active.md", "active_context", False),
        (ROOT / "context" / "decisions.md", "decisions_context", False),
    ]:
        check_path(checks, path, name, directory=is_dir)

    for path, name in [
        (ROOT / "orchestrator-repo-maintenance" / "generated" / "scheduled-maintenance-state.json", "orchestrator_scheduled_state"),
        (Path("/Users/agent2/.openclaw/workbench/context/state/context-pruning-state.json"), "workbench_context_pruning_state"),
    ]:
        check_json_file(checks, path, name)

    check_latest_envelope(checks, WORKBENCH_RUNS_ROOT, "latest_workbench_envelope")
    check_latest_envelope(checks, ORCHESTRATOR_RUNS_ROOT, "latest_orchestrator_envelope")
    check_script_usage_summary(checks)
    run_compile_check(checks)
    cron_payload = load_cron_inventory_payload(checks)
    run_cron_check(checks, cron_payload)
    objective_rollups = objective_rollups_from_cron_payload(cron_payload)

    statuses = {c.status for c in checks}
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    objective_summary: dict[str, int] = {}
    for item in objective_rollups:
        objective_summary[str(item.get("objective_status"))] = objective_summary.get(str(item.get("objective_status")), 0) + 1
    payload = {
        "schema_version": "maintenance-self-check/v1",
        "updated_at": now_iso(),
        "overall_status": overall,
        "checks": [asdict(c) for c in checks],
        "objective_rollups": objective_rollups,
        "summary": {"ok": sum(c.status == "ok" for c in checks), "warning": sum(c.status == "warning" for c in checks), "error": sum(c.status == "error" for c in checks)},
        "objective_summary": objective_summary,
    }
    CHECK_JSON.parent.mkdir(parents=True, exist_ok=True)
    CHECK_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    CHECK_MD.write_text(render_md(payload))
    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps({"overall_status": overall, "json": str(CHECK_JSON), "markdown": str(CHECK_MD)}, sort_keys=True))
    return 0 if overall != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
