#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MAINTENANCE_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = MAINTENANCE_ROOT / "report_maintenance_system_implementation_check.py"
spec = importlib.util.spec_from_file_location("report_maintenance_system_implementation_check_for_tests", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not import {MODULE_PATH}")
check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check
spec.loader.exec_module(check)


def passing_test_results() -> list[dict]:
    return [
        {"name": "workbench_context", "ok": True, "returncode": 0, "timed_out": False},
        {"name": "maintenance_self_check", "ok": True, "returncode": 0, "timed_out": False},
    ]


def test_phase8_dry_runs_surface_objective_statuses_and_cleanup(tmp_path: Path) -> None:
    phase_root = tmp_path / "maintenance-plan-tests" / "phase-8"
    dry_runs = check.build_phase8_dry_runs(phase_root / "unit-run")

    assert {item["objective_rollup"]["objective_status"] for item in dry_runs.values()} >= {"met", "degraded"}
    assert dry_runs["repo_hygiene"]["throughput_movement"]["throughput_status"] == "evidence_moved"
    assert dry_runs["repo_hygiene"]["next_actions_by_lane"]["Maintenance: Orchestrator Script Evidence Refresh"]["autonomous"] is True

    check.remove_phase_artifacts(phase_root)
    assert check.scan_phase_artifacts(tmp_path / "maintenance-plan-tests") == []


def test_final_gate_passes_with_owned_stranded_items() -> None:
    dry_runs = {
        "learning": {
            "objective_rollup": {"objective_status": "degraded", "degraded_reasons": ["lmd_causal_maintenance_failed"]},
            "wrapper_result": {
                "blocked_reason": "lmd_causal_maintenance_failed",
                "recurrence_count": 2,
                "owner_lane": "lmd_causal_maintenance",
                "next_action": "retry_lmd_causal_maintenance_on_next_learning_maintenance_cadence",
                "human_review_required": False,
            },
            "throughput_movement": {},
        }
    }

    payload = check.build_payload(
        test_results=passing_test_results(),
        dry_runs=dry_runs,
        cleanup_artifacts=[],
        generated_at_utc="2026-06-18T20:00:00Z",
    )

    assert payload["final_gate_status"] == "passed"
    assert payload["unowned_stranded_items"] == []
    assert payload["stranded_items"][0]["owner_lane"] == "lmd_causal_maintenance"
    assert payload["next_action_policy"]["default"] == "owning_lane_executes_next_action_on_next_scheduled_or_dirty_cadence"


def test_final_gate_fails_unowned_stranded_items() -> None:
    dry_runs = {
        "repo_hygiene": {
            "objective_rollup": {"objective_status": "degraded", "degraded_reasons": ["pre_instrumentation_unknown"]},
            "wrapper_result": {"blocked_reason": "pre_instrumentation_unknown"},
            "throughput_movement": {"stranded_unknown_count": 1},
        }
    }

    payload = check.build_payload(
        test_results=passing_test_results(),
        dry_runs=dry_runs,
        cleanup_artifacts=[],
        generated_at_utc="2026-06-18T20:00:00Z",
    )

    assert payload["final_gate_status"] == "failed"
    assert payload["unowned_stranded_items"][0]["scope"] == "repo_hygiene"


def test_markdown_names_excluded_boundary_without_external_plan_pointer() -> None:
    payload = check.build_payload(
        test_results=passing_test_results(),
        dry_runs={},
        cleanup_artifacts=[],
        generated_at_utc="2026-06-18T20:00:00Z",
    )
    markdown = check.render_markdown(payload)

    assert "Excluded boundary: `QMD canon maintenance system`" in markdown
    assert "qmd-system-phase-implementation-plan" not in markdown.lower()
    assert "No `tmp/maintenance-plan-tests` phase artifacts remain." in markdown
