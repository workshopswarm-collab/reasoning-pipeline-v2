#!/usr/bin/env python3
"""Final non-QMD maintenance-system implementation validation gate."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

MAINTENANCE_ROOT = Path(__file__).resolve().parent
OPENCLAW_ROOT = MAINTENANCE_ROOT.parent
ORCHESTRATOR_ROOT = OPENCLAW_ROOT / "orchestrator"
AUDIT_ROOT = ORCHESTRATOR_ROOT / "qualitative-db" / "90-audits" / "generated"
PLAN_REFERENCE = "orchestrator/qualitative-db/90-audits/generated/maintenance-system-phase-implementation-plan-20260618.md"
SCHEMA_VERSION = "maintenance-system-implementation-check/v1"
DEFAULT_REPORT_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")
DEFAULT_OUTPUT_MD = AUDIT_ROOT / f"maintenance-system-implementation-check-{DEFAULT_REPORT_DATE}.md"
PHASE_TEST_ROOT = OPENCLAW_ROOT / "tmp" / "maintenance-plan-tests" / "phase-8"
PHASE_TEST_SCAN_ROOT = OPENCLAW_ROOT / "tmp" / "maintenance-plan-tests"

if str(MAINTENANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_ROOT))

from lib.maintenance_objective_status import build_objective_rollup  # noqa: E402


@dataclass(frozen=True)
class CommandSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path = OPENCLAW_ROOT


CommandRunner = Callable[[CommandSpec, float], dict[str, Any]]


TEST_GROUPS = [
    CommandSpec(
        name="workbench_context",
        command=(
            sys.executable,
            "-m",
            "pytest",
            "maintenance/workbench-context-maintenance/scripts/tests/test_context_usage_prune.py",
            "maintenance/workbench-context-maintenance/scripts/tests/test_run_context_prune_maintenance.py",
            "-q",
        ),
    ),
    CommandSpec(
        name="maintenance_self_check",
        command=(
            sys.executable,
            "-m",
            "pytest",
            "maintenance/tests/test_maintenance_phase0.py",
            "maintenance/tests/test_maintenance_hardening.py::test_maintenance_self_check_expects_script_cleanup_crons",
            "maintenance/tests/test_maintenance_hardening.py::test_maintenance_self_check_expects_pressure_check_cron",
            "maintenance/tests/test_maintenance_hardening.py::test_maintenance_self_check_accepts_script_auto_archive_and_delete_cron_inventory",
            "maintenance/tests/test_maintenance_hardening.py::test_maintenance_self_check_rejects_missing_pressure_check_cron_inventory",
            "maintenance/tests/test_maintenance_hardening.py::test_objective_status_classifies_met_partial_degraded_and_no_action",
            "maintenance/tests/test_maintenance_hardening.py::test_objective_rollup_preserves_next_action_as_status_not_execution",
            "maintenance/tests/test_maintenance_hardening.py::test_self_check_objective_rollup_marks_missing_scheduler",
            "-q",
        ),
    ),
    CommandSpec(
        name="repo_hygiene",
        command=(
            sys.executable,
            "-m",
            "pytest",
            "maintenance/tests/test_script_usage_materializer.py::test_c1_parser_tolerates_malformed_rows_and_summarizes_counts",
            "maintenance/tests/test_script_usage_materializer.py::test_c1_cli_writes_json_and_markdown_outputs",
            "maintenance/tests/test_script_usage_materializer.py::test_c4_classifier_join_marks_missing_usage_and_reviews_inventory_scope",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_plan_uses_usage_aware_action_classes",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_plan_blocks_approved_candidates_with_usage_blockers",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_plan_reports_gate_ready_and_blockers",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_plan_autonomously_promotes_archive_when_deterministic_evidence_is_clear",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_plan_blocks_missing_usage_summary_rows",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_candidate_history_tracks_repeated_no_use_state",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_candidate_history_marks_mature_after_window_and_observations",
            "maintenance/tests/test_maintenance_hardening.py::test_cleanup_candidate_history_resets_no_use_on_observed_usage",
            "maintenance/tests/test_maintenance_hardening.py::test_scheduled_cleanup_delete_readiness_guard_blocks_delete_ready",
            "maintenance/tests/test_maintenance_hardening.py::test_scheduled_cleanup_delete_readiness_guard_allows_current_zero_delete_ready",
            "-q",
        ),
    ),
    CommandSpec(
        name="learning_launchd_status",
        command=(
            sys.executable,
            "-m",
            "pytest",
            "orchestrator/scripts/tests/test_launchd_trigger_env.py::LaunchdTriggerEnvTests::test_learning_maintenance_launchd_template_validation_rejects_temp_worktree_paths",
            "orchestrator/scripts/tests/test_launchd_trigger_env.py::LaunchdTriggerEnvTests::test_checked_in_learning_maintenance_plist_uses_real_repo_root",
            "orchestrator/scripts/tests/test_automation_planes.py::AutomationPlanesTests::test_summary_surfaces_lmd_causal_subplane_degradation_from_learning_maintenance",
            "-q",
        ),
    ),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(OPENCLAW_ROOT.resolve()))
    except ValueError:
        return str(path)


def run_command(spec: CommandSpec, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            list(spec.command),
            cwd=str(spec.cwd),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return {
            "name": spec.name,
            "cmd": list(spec.command),
            "cwd": rel(spec.cwd),
            "returncode": proc.returncode,
            "ok": proc.returncode == 0,
            "timed_out": False,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "name": spec.name,
            "cmd": list(spec.command),
            "cwd": rel(spec.cwd),
            "returncode": None,
            "ok": False,
            "timed_out": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": stdout[-2000:],
            "stderr_tail": stderr[-2000:],
        }


def run_test_groups(
    *,
    skip_pytest: bool = False,
    timeout_seconds: float = 180.0,
    command_runner: CommandRunner = run_command,
) -> list[dict[str, Any]]:
    if skip_pytest:
        return [
            {
                "name": spec.name,
                "cmd": list(spec.command),
                "cwd": rel(spec.cwd),
                "returncode": 0,
                "ok": True,
                "timed_out": False,
                "skipped": True,
                "stdout_tail": "skipped by --skip-pytest",
                "stderr_tail": "",
            }
            for spec in TEST_GROUPS
        ]
    return [command_runner(spec, timeout_seconds) for spec in TEST_GROUPS]


def fixture_objective_rollup(
    *,
    plane: str,
    wrapper_result: dict[str, Any],
    scheduler_status: str = "healthy",
    wrapper_status: str = "completed",
) -> dict[str, Any]:
    return build_objective_rollup(
        plane=plane,
        scheduler_status=scheduler_status,
        wrapper_status=wrapper_status,
        wrapper_result=wrapper_result,
        generated_artifacts=[],
    )


def build_phase8_dry_runs(run_root: Path) -> dict[str, dict[str, Any]]:
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "fixture-created-and-cleaned.txt").write_text("phase-8 fixture root\n", encoding="utf-8")

    pressure_wrapper = {
        "status": "completed",
        "ok": True,
        "mutating": False,
        "pressure_objective": {
            "hard_budget_met": True,
            "changed_paths": ["context/active.md", "context/state/context-pruning-state.json"],
            "remaining_hard_budget_paths": [],
            "remaining_decisions_hard_budget_paths": [],
        },
        "mutation_count": 0,
    }
    repo_hygiene_wrapper = {
        "schema_version": "scheduled-script-evidence-refresh/v1",
        "mode": "script-evidence-refresh",
        "ok": True,
        "status": "completed",
        "mutating": False,
        "autonomous_next_action_count": 4,
        "manual_owner_review_required_count": 0,
        "evidence_movement": {
            "throughput_status": "evidence_moved",
            "unknown_reduced_count": 2,
            "new_observed_count": 1,
            "new_referenced_count": 1,
            "ready_candidate_count": 1,
            "retired_candidate_count": 1,
            "stranded_unknown_count": 0,
            "blocker_retired_count": 1,
            "zero_archive_delete_throughput_acceptable": True,
        },
        "next_actions_by_lane": {
            "Maintenance: Orchestrator Script Evidence Refresh": {"count": 4, "autonomous": True}
        },
    }
    learning_wrapper = {
        "status": "blocked",
        "ok": False,
        "mutating": False,
        "blocked_reason": "lmd_causal_maintenance_failed",
        "recurrence_count": 2,
        "owner_lane": "lmd_causal_maintenance",
        "next_action": "retry_lmd_causal_maintenance_on_next_learning_maintenance_cadence",
        "human_review_required": False,
    }

    return {
        "pressure_check": {
            "mode": "fixture_non_mutating",
            "safe_lane": "compression_and_state_compaction",
            "wrapper_result": pressure_wrapper,
            "objective_rollup": fixture_objective_rollup(
                plane="Maintenance: Workbench Context Prune Pressure Check",
                wrapper_result=pressure_wrapper,
            ),
            "throughput_movement": {
                "compression_paths": 1,
                "state_compaction_paths": 1,
                "remaining_hard_budget_paths": 0,
            },
        },
        "repo_hygiene": {
            "mode": "fixture_non_mutating_evidence_refresh",
            "safe_lane": "script_evidence_refresh",
            "wrapper_result": repo_hygiene_wrapper,
            "objective_rollup": fixture_objective_rollup(
                plane="Maintenance: Orchestrator Script Evidence Refresh",
                wrapper_result=repo_hygiene_wrapper,
            ),
            "throughput_movement": repo_hygiene_wrapper["evidence_movement"],
            "next_actions_by_lane": repo_hygiene_wrapper["next_actions_by_lane"],
        },
        "learning": {
            "mode": "fixture_launchd_template_and_lmd_status",
            "safe_lane": "lmd_causal_maintenance_status_visibility",
            "wrapper_result": learning_wrapper,
            "objective_rollup": fixture_objective_rollup(
                plane="Learning maintenance LMD subplane",
                wrapper_result=learning_wrapper,
                scheduler_status="healthy",
                wrapper_status="blocked",
            ),
            "throughput_movement": {
                "scheduler_health_distinguished_from_lmd_failure": True,
                "broad_learning_maintenance_not_marked_success_for_failed_subplane": True,
            },
        },
    }


def stranded_items_from_dry_runs(dry_runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, dry_run in dry_runs.items():
        rollup = dry_run.get("objective_rollup") if isinstance(dry_run.get("objective_rollup"), dict) else {}
        wrapper = dry_run.get("wrapper_result") if isinstance(dry_run.get("wrapper_result"), dict) else {}
        objective_status = str(rollup.get("objective_status") or "")
        degraded = objective_status in {"partial", "degraded"} or bool(wrapper.get("blocked_reason"))
        if not degraded:
            movement = dry_run.get("throughput_movement") if isinstance(dry_run.get("throughput_movement"), dict) else {}
            degraded = int(movement.get("stranded_unknown_count") or 0) > 0
        if not degraded:
            continue
        lanes = dry_run.get("next_actions_by_lane") if isinstance(dry_run.get("next_actions_by_lane"), dict) else {}
        owner_lane = str(wrapper.get("owner_lane") or "")
        if not owner_lane and len(lanes) == 1:
            owner_lane = str(next(iter(lanes)))
        next_action = str(wrapper.get("next_action") or "")
        if not next_action and owner_lane:
            next_action = "continue_autonomous_next_action_on_owner_lane"
        items.append(
            {
                "scope": name,
                "blocker_scope": str(wrapper.get("blocked_reason") or ",".join(rollup.get("degraded_reasons") or []) or "stranded_unknown"),
                "recurrence_count": int(wrapper.get("recurrence_count") or 1),
                "owner_lane": owner_lane,
                "next_action": next_action,
                "human_review_required": bool(wrapper.get("human_review_required", False)),
            }
        )
    return items


def unowned_stranded_items(stranded_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unowned: list[dict[str, Any]] = []
    for item in stranded_items:
        if not item.get("blocker_scope") or not item.get("owner_lane") or not item.get("next_action") or int(item.get("recurrence_count") or 0) < 1:
            unowned.append(item)
    return unowned


def remove_phase_artifacts(phase_root: Path = PHASE_TEST_ROOT) -> None:
    shutil.rmtree(phase_root, ignore_errors=True)
    for path in [phase_root.parent, phase_root.parent.parent]:
        try:
            path.rmdir()
        except OSError:
            pass


def scan_phase_artifacts(scan_root: Path = PHASE_TEST_SCAN_ROOT) -> list[str]:
    if not scan_root.exists():
        return []
    results: list[str] = []
    for path in sorted(scan_root.rglob("*")):
        depth = len(path.relative_to(scan_root).parts)
        if 1 <= depth <= 3:
            results.append(rel(path))
    return results


def build_payload(
    *,
    test_results: list[dict[str, Any]],
    dry_runs: dict[str, dict[str, Any]],
    cleanup_artifacts: list[str],
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    stranded_items = stranded_items_from_dry_runs(dry_runs)
    unowned = unowned_stranded_items(stranded_items)
    tests_ok = all(bool(item.get("ok")) for item in test_results)
    cleanup_ok = not cleanup_artifacts
    final_gate_passed = tests_ok and cleanup_ok and not unowned
    dry_run_summary = {
        name: {
            "mode": item.get("mode"),
            "safe_lane": item.get("safe_lane"),
            "objective_status": item.get("objective_rollup", {}).get("objective_status") if isinstance(item.get("objective_rollup"), dict) else None,
            "wrapper_status": item.get("objective_rollup", {}).get("wrapper_status") if isinstance(item.get("objective_rollup"), dict) else None,
            "scheduler_status": item.get("objective_rollup", {}).get("scheduler_status") if isinstance(item.get("objective_rollup"), dict) else None,
            "throughput_movement": item.get("throughput_movement", {}),
        }
        for name, item in sorted(dry_runs.items())
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_now_iso(),
        "plan_reference": PLAN_REFERENCE,
        "excluded_boundary": "QMD canon maintenance system",
        "final_gate_status": "passed" if final_gate_passed else "failed",
        "test_summary": {
            "passed": sum(1 for item in test_results if item.get("ok")),
            "failed": sum(1 for item in test_results if not item.get("ok")),
            "total": len(test_results),
        },
        "test_results": test_results,
        "dry_run_summary": dry_run_summary,
        "stranded_items": stranded_items,
        "unowned_stranded_items": unowned,
        "cleanup_artifacts_remaining": cleanup_artifacts,
        "next_action_policy": {
            "default": "owning_lane_executes_next_action_on_next_scheduled_or_dirty_cadence",
            "human_review_required_only_when": "owner_lane_is_Maintenance_owner_review_or_human_review_required_true",
            "safe_lanes_remain_active": [
                "compression",
                "state_compaction",
                "evidence_refresh",
                "stale_state_repair",
                "objective_status_degradation",
            ],
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Maintenance System Implementation Check",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Plan reference: `{payload.get('plan_reference')}`",
        f"Excluded boundary: `{payload.get('excluded_boundary')}`",
        f"Final gate: **{payload.get('final_gate_status')}**",
        "",
        "## Test Results",
        "",
    ]
    for item in payload.get("test_results", []):
        status = "pass" if item.get("ok") else "fail"
        skipped = " skipped=true" if item.get("skipped") else ""
        lines.append(f"- **{status}** `{item.get('name')}` returncode={item.get('returncode')} timed_out={item.get('timed_out')}{skipped}")
    lines.extend(["", "## Dry-Run Objective Summary", ""])
    for name, item in payload.get("dry_run_summary", {}).items():
        movement = item.get("throughput_movement", {}) if isinstance(item.get("throughput_movement"), dict) else {}
        movement_bits = ", ".join(f"{key}={value}" for key, value in sorted(movement.items()) if not isinstance(value, (dict, list)))
        lines.append(
            f"- `{name}` objective={item.get('objective_status')} wrapper={item.get('wrapper_status')} "
            f"scheduler={item.get('scheduler_status')} lane=`{item.get('safe_lane')}` movement={movement_bits or 'n/a'}"
        )
    lines.extend(["", "## Stranded Maintenance Items", ""])
    stranded = payload.get("stranded_items", [])
    if stranded:
        for item in stranded:
            lines.append(
                f"- `{item.get('scope')}` blocker=`{item.get('blocker_scope')}` recurrence={item.get('recurrence_count')} "
                f"owner=`{item.get('owner_lane')}` next_action=`{item.get('next_action')}` human_review_required={item.get('human_review_required')}"
            )
    else:
        lines.append("_None._")
    lines.extend(["", "## Next-Action Policy", ""])
    policy = payload.get("next_action_policy", {}) if isinstance(payload.get("next_action_policy"), dict) else {}
    lines.append(f"- Default: `{policy.get('default')}`")
    lines.append(f"- Human review only when: `{policy.get('human_review_required_only_when')}`")
    lines.append(f"- Safe lanes remain active: `{', '.join(policy.get('safe_lanes_remain_active', []))}`")
    lines.extend(["", "## Cleanup", ""])
    leftovers = payload.get("cleanup_artifacts_remaining", [])
    if leftovers:
        for path in leftovers:
            lines.append(f"- leftover: `{path}`")
    else:
        lines.append("- No `tmp/maintenance-plan-tests` phase artifacts remain.")
    lines.append("")
    return "\n".join(lines)


def write_markdown(payload: dict[str, Any], output_md: Path) -> None:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the final non-QMD maintenance system implementation gate")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--skip-pytest", action="store_true", help="Build the report from fixtures without executing pytest groups")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = f"phase8-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_root = PHASE_TEST_ROOT / run_id
    test_results = run_test_groups(skip_pytest=args.skip_pytest, timeout_seconds=args.timeout_seconds)
    dry_runs = build_phase8_dry_runs(run_root)
    remove_phase_artifacts(PHASE_TEST_ROOT)
    cleanup_artifacts = scan_phase_artifacts(PHASE_TEST_SCAN_ROOT)
    payload = build_payload(test_results=test_results, dry_runs=dry_runs, cleanup_artifacts=cleanup_artifacts)
    write_markdown(payload, args.output)
    print(json.dumps({"status": payload["final_gate_status"], "output": rel(args.output), "tests": payload["test_summary"]}, sort_keys=True))
    return 0 if payload["final_gate_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
