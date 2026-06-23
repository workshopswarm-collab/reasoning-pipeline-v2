#!/usr/bin/env python3
"""Run deterministic Orchestrator maintenance audits.

This runner is non-mutating outside of the maintenance directory by default:
it refreshes generated maintenance reports and emits a compact summary. Narrow
clutter apply slices require explicit flags and fresh preflight checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAINTENANCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("ORCHESTRATOR_REPO_ROOT", "/Users/agent2/.openclaw/orchestrator")).resolve()
GENERATED_DIR = MAINTENANCE_DIR / "generated"
SCRIPT_CLASSIFIER = MAINTENANCE_DIR / "script_classifier.py"
SCRIPT_USAGE_MATERIALIZER = MAINTENANCE_DIR / "script_usage_materializer.py"
SCRIPT_LIFECYCLE_OVERRIDES_JSON = MAINTENANCE_DIR / "script-lifecycle-overrides.json"
SCRIPT_CLASSIFICATION_JSON = GENERATED_DIR / "script-classification.json"
SCRIPT_CLASSIFICATION_MD = GENERATED_DIR / "script-classification.md"
CLUTTER_INVENTORY_JSON = GENERATED_DIR / "clutter-inventory.json"
CLUTTER_INVENTORY_MD = GENERATED_DIR / "clutter-inventory.md"
MAINTENANCE_SUMMARY_JSON = GENERATED_DIR / "maintenance-summary.json"
PREVIOUS_MAINTENANCE_SUMMARY_JSON = GENERATED_DIR / "maintenance-summary.previous.json"
MAINTENANCE_DRIFT_JSON = GENERATED_DIR / "maintenance-drift.json"
MAINTENANCE_DRIFT_MD = GENERATED_DIR / "maintenance-drift.md"
CLEANUP_EVIDENCE_DIFF_JSON = GENERATED_DIR / "cleanup-evidence-diff.json"
CLEANUP_EVIDENCE_DIFF_MD = GENERATED_DIR / "cleanup-evidence-diff.md"
SCRIPT_CLEANUP_BLOCKERS_JSON = GENERATED_DIR / "script-cleanup-blockers.json"
SCRIPT_CLEANUP_BLOCKERS_MD = GENERATED_DIR / "script-cleanup-blockers.md"
SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON = GENERATED_DIR / "script-cleanup-evidence-movement.json"
SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_MD = GENERATED_DIR / "script-cleanup-evidence-movement.md"
REPO_HEALTH_JSON = GENERATED_DIR / "repo-health-summary.json"
REPO_HEALTH_MD = GENERATED_DIR / "repo-health-summary.md"
CLEANUP_PLAN_JSON = GENERATED_DIR / "cleanup-plan.json"
CLEANUP_PLAN_MD = GENERATED_DIR / "cleanup-plan.md"
CLUTTER_APPLY_DRY_RUN_JSON = GENERATED_DIR / "clutter-apply-dry-run.json"
CLUTTER_APPLY_DRY_RUN_MD = GENERATED_DIR / "clutter-apply-dry-run.md"
CLUTTER_APPLY_RESULT_JSON = GENERATED_DIR / "clutter-apply-result.json"
CLUTTER_APPLY_RESULT_MD = GENERATED_DIR / "clutter-apply-result.md"
GENERATED_RETENTION_RESULT_JSON = GENERATED_DIR / "generated-artifact-retention-result.json"
GENERATED_RETENTION_RESULT_MD = GENERATED_DIR / "generated-artifact-retention-result.md"
RUNS_ROOT = GENERATED_DIR / "runs"
GENERATED_RUN_RETENTION_KEEP_LATEST = 3
CLEANUP_CANDIDATE_HISTORY_JSON = GENERATED_DIR / "cleanup-candidate-history.json"
CLEANUP_CANDIDATE_HISTORY_MD = GENERATED_DIR / "cleanup-candidate-history.md"
SCRIPT_USAGE_SUMMARY_JSON = GENERATED_DIR / "script-usage-summary.json"
SCRIPT_USAGE_SUMMARY_MD = GENERATED_DIR / "script-usage-summary.md"
POST_APPLY_VERIFICATION_JSON = GENERATED_DIR / "post-apply-verification.json"
POST_APPLY_VERIFICATION_MD = GENERATED_DIR / "post-apply-verification.md"
ARCHIVE_LAYOUT_JSON = GENERATED_DIR / "script-archive-layout.json"
ARCHIVE_LAYOUT_MD = GENERATED_DIR / "script-archive-layout.md"
ARCHIVE_DRY_RUN_JSON = GENERATED_DIR / "script-archive-dry-run.json"
ARCHIVE_DRY_RUN_MD = GENERATED_DIR / "script-archive-dry-run.md"
ARCHIVE_APPLY_RESULT_JSON = GENERATED_DIR / "script-archive-apply-result.json"
ARCHIVE_APPLY_RESULT_MD = GENERATED_DIR / "script-archive-apply-result.md"
POST_ARCHIVE_SMOKE_JSON = GENERATED_DIR / "post-archive-smoke.json"
POST_ARCHIVE_SMOKE_MD = GENERATED_DIR / "post-archive-smoke.md"
QUARANTINE_MONITOR_JSON = GENERATED_DIR / "script-quarantine-monitor.json"
QUARANTINE_MONITOR_MD = GENERATED_DIR / "script-quarantine-monitor.md"
DELETE_READINESS_JSON = GENERATED_DIR / "script-delete-readiness.json"
DELETE_READINESS_MD = GENERATED_DIR / "script-delete-readiness.md"
DELETE_DRY_RUN_JSON = GENERATED_DIR / "script-delete-dry-run.json"
DELETE_DRY_RUN_MD = GENERATED_DIR / "script-delete-dry-run.md"
DELETE_APPLY_RESULT_JSON = GENERATED_DIR / "script-delete-apply-result.json"
DELETE_APPLY_RESULT_MD = GENERATED_DIR / "script-delete-apply-result.md"
POST_DELETE_VERIFICATION_JSON = GENERATED_DIR / "post-delete-verification.json"
POST_DELETE_VERIFICATION_MD = GENERATED_DIR / "post-delete-verification.md"
AUTO_ARCHIVE_PROMOTION_JSON = GENERATED_DIR / "script-auto-archive-promotion.json"
AUTO_ARCHIVE_PROMOTION_MD = GENERATED_DIR / "script-auto-archive-promotion.md"
SCRIPT_ARCHIVE_ROOT = MAINTENANCE_DIR / "archive" / "scripts"
DELETE_READINESS_REQUIRED_CLEAN_CYCLES = 3
MAINTENANCE_SELF_CHECK = MAINTENANCE_DIR.parent / "maintenance_self_check.py"
MAINTENANCE_SELF_CHECK_JSON = MAINTENANCE_DIR.parent / "generated" / "maintenance-self-check.json"
MAINTENANCE_SELF_CHECK_MD = MAINTENANCE_DIR.parent / "generated" / "maintenance-self-check.md"
AUTO_ARCHIVE_ELIGIBLE_CLASSES = {"deprecated_candidate", "diagnostic_harness", "manual_repair", "migration_backfill"}


def run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_json(path)


def clutter_category(path: Path) -> str:
    if path.name == ".DS_Store":
        return "macos_metadata"
    if "__pycache__" in path.parts:
        return "python_bytecode_cache"
    if ".runtime-state" in path.parts:
        return "runtime_state"
    return "unknown"


def clutter_cleanup_policy(category: str) -> str:
    return {
        "macos_metadata": "safe_to_remove_after_git_status_check",
        "python_bytecode_cache": "safe_to_remove_after_process_check",
        "runtime_state": "do_not_remove_without_runtime_owner_review",
        "unknown": "manual_review_required",
    }.get(category, "manual_review_required")


def clutter_inventory() -> dict[str, Any]:
    candidates: set[Path] = set()
    patterns = [
        "scripts/.runtime-state",
        "roles/**/.runtime-state",
        "scripts/__pycache__",
        "roles/**/__pycache__",
        "quant-db/scripts/__pycache__",
    ]
    for pattern in patterns:
        for path in REPO_ROOT.glob(pattern):
            if path.exists() and ".git" not in path.parts:
                candidates.add(path)
    for path in REPO_ROOT.rglob(".DS_Store"):
        if ".git" not in path.parts and "maintenance" not in path.parts:
            candidates.add(path)

    records: list[dict[str, Any]] = []
    for path in sorted(candidates, key=lambda p: str(p.relative_to(REPO_ROOT))):
        category = clutter_category(path)
        records.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "kind": "directory" if path.is_dir() else "file",
                "category": category,
                "cleanup_policy": clutter_cleanup_policy(category),
            }
        )
    category_counts = Counter(record["category"] for record in records)
    policy_counts = Counter(record["cleanup_policy"] for record in records)
    return {
        "schema_version": "orchestrator-clutter-inventory/v1",
        "count": len(records),
        "category_counts": dict(sorted(category_counts.items())),
        "cleanup_policy_counts": dict(sorted(policy_counts.items())),
        "records": records,
    }


def write_clutter_inventory() -> dict[str, Any]:
    payload = clutter_inventory()
    CLUTTER_INVENTORY_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    CLUTTER_INVENTORY_MD.write_text(render_clutter_markdown(payload))
    return payload


def render_clutter_markdown(payload: dict[str, Any]) -> str:
    records = payload["records"]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_category.setdefault(record["category"], []).append(record)
    lines = ["# Clutter Inventory", ""]
    lines.append(f"Total clutter candidates: **{payload['count']}**")
    lines.append("")
    lines.append("## Category counts")
    lines.append("")
    for category, count in payload["category_counts"].items():
        lines.append(f"- `{category}`: {count}")
    lines.append("")
    lines.append("## Cleanup policy counts")
    lines.append("")
    for policy, count in payload["cleanup_policy_counts"].items():
        lines.append(f"- `{policy}`: {count}")
    lines.append("")
    for category in sorted(by_category):
        items = by_category[category]
        lines.append(f"## {category} ({len(items)})")
        lines.append("")
        for item in items:
            lines.append(f"- `{item['path']}` — {item['kind']}; `{item['cleanup_policy']}`")
        lines.append("")
    return "\n".join(lines)


def maintenance_path(path: Path) -> str:
    try:
        return str(path.relative_to(MAINTENANCE_DIR.parent))
    except ValueError:
        return str(path)


def generated_clutter_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "count": payload["count"],
        "category_counts": payload["category_counts"],
        "cleanup_policy_counts": payload["cleanup_policy_counts"],
        "json_path": maintenance_path(CLUTTER_INVENTORY_JSON),
        "markdown_path": maintenance_path(CLUTTER_INVENTORY_MD),
    }


def generated_script_usage_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    return {
        "schema_version": payload.get("schema_version"),
        "phase": payload.get("phase"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "classified_script_count": summary.get("classified_script_count"),
        "observed_classified_script_count": summary.get("observed_classified_script_count"),
        "parent_observed_script_count": summary.get("parent_observed_script_count"),
        "pre_instrumentation_unknown_count": summary.get("pre_instrumentation_unknown_count"),
        "referenced_script_count": summary.get("referenced_script_count"),
        "parse_issue_count": summary.get("parse_issue_count"),
        "unmatched_ledger_script_count": summary.get("unmatched_ledger_script_count"),
        "complete_join": summary.get("classified_script_count") == len(payload.get("scripts", [])) if isinstance(payload.get("scripts"), list) else False,
        "json_path": maintenance_path(SCRIPT_USAGE_SUMMARY_JSON),
        "markdown_path": maintenance_path(SCRIPT_USAGE_SUMMARY_MD),
    }


def keyed_script_usage(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, list):
        return {}
    return {str(item.get("path")): item for item in scripts if isinstance(item, dict) and item.get("path")}


def script_usage_for_cleanup(candidate: dict[str, Any]) -> dict[str, Any]:
    usage = candidate.get("script_usage") if isinstance(candidate.get("script_usage"), dict) else {}
    coverage_status = str(usage.get("coverage_status") or "missing_from_usage_summary")
    evidence_sources = usage.get("evidence_sources") if isinstance(usage.get("evidence_sources"), list) else []
    blockers = list(usage.get("cleanup_eligibility_blockers") or []) if isinstance(usage.get("cleanup_eligibility_blockers"), list) else []
    observed = coverage_status == "direct" or int(usage.get("run_count_total") or 0) > 0 or int(usage.get("start_count") or 0) > 0
    referenced = bool(int(candidate.get("inbound_reference_count", 0) or 0) > 0 or usage.get("reference_evidence"))
    return {
        "coverage_status": coverage_status,
        "evidence_sources": evidence_sources,
        "cleanup_eligibility_blockers": blockers,
        "last_success_at": usage.get("last_success_at"),
        "last_observed_start_at": usage.get("last_observed_start_at"),
        "run_count_total": usage.get("run_count_total", 0),
        "reference_evidence_count": len(usage.get("reference_evidence", [])) if isinstance(usage.get("reference_evidence"), list) else 0,
        "observed_recently_or_directly": observed,
        "referenced_by_static_or_c4_evidence": referenced,
        "usage_summary_available": bool(usage),
    }


def cleanup_gate_evaluation(candidate: dict[str, Any], confidence: dict[str, Any]) -> dict[str, Any]:
    cleanup_usage = script_usage_for_cleanup(candidate)
    checks = confidence.get("checks", {}) if isinstance(confidence.get("checks"), dict) else {}
    failed_checks = list(confidence.get("failed_checks") or []) if isinstance(confidence.get("failed_checks"), list) else []
    override = candidate.get("lifecycle_override") if isinstance(candidate.get("lifecycle_override"), dict) else {}
    lifecycle_status = str(override.get("lifecycle_status") or "")
    verification = override.get("verification", {}) if isinstance(override.get("verification"), dict) else {}

    archive_blockers: list[str] = []
    if not cleanup_usage["usage_summary_available"]:
        archive_blockers.append("missing_usage_summary_row")
    archive_blockers.extend(f"usage:{blocker}" for blocker in cleanup_usage["cleanup_eligibility_blockers"])
    if cleanup_usage["observed_recently_or_directly"]:
        archive_blockers.append("observed_ledger_usage")
    if cleanup_usage["referenced_by_static_or_c4_evidence"]:
        archive_blockers.append("referenced_by_static_or_c4_evidence")
    archive_blockers.extend(f"verification:{check}" for check in failed_checks if check != "archived_for_one_cycle")
    if lifecycle_status != "archive_approved":
        archive_blockers.append("lifecycle_not_archive_approved")

    delete_blockers = [blocker for blocker in archive_blockers if blocker != "lifecycle_not_archive_approved"]
    if lifecycle_status != "removal_approved":
        delete_blockers.append("lifecycle_not_removal_approved")
    if not verification.get("archived_for_one_cycle"):
        delete_blockers.append("not_archived_for_one_cycle")
    if lifecycle_status != "archived_quarantine" and not verification.get("archived_for_one_cycle"):
        delete_blockers.append("not_in_archived_quarantine")

    archive_blockers = sorted(set(archive_blockers))
    delete_blockers = sorted(set(delete_blockers))
    return {
        "schema_version": "script-cleanup-gate-evaluation/v1",
        "mode": "report_only",
        "archive": {
            "ready": not archive_blockers,
            "decision": "auto_archive_ready" if not archive_blockers else "blocked",
            "blockers": archive_blockers,
            "passed_checks": sorted(key for key, value in checks.items() if value),
        },
        "delete": {
            "ready": not delete_blockers,
            "decision": "auto_delete_ready" if not delete_blockers else "blocked",
            "blockers": delete_blockers,
            "passed_checks": sorted(key for key, value in checks.items() if value),
        },
    }


def usage_aware_action(candidate: dict[str, Any], confidence: dict[str, Any], no_refs: bool, gate_evaluation: dict[str, Any]) -> tuple[str, str]:
    cleanup_usage = script_usage_for_cleanup(candidate)
    blockers = cleanup_usage["cleanup_eligibility_blockers"]
    if cleanup_usage["observed_recently_or_directly"]:
        return "retain_recently_used", "direct_ledger_usage_or_recent_observation"
    if cleanup_usage["referenced_by_static_or_c4_evidence"]:
        return "retain_referenced", "static_or_scheduler_doc_log_reference_evidence"
    if cleanup_usage["coverage_status"] == "missing_from_usage_summary":
        return "manual_review_required", "missing_usage_summary_row"
    if gate_evaluation.get("delete", {}).get("ready"):
        return "auto_delete_ready", "gate_evaluator_delete_ready_report_only"
    if gate_evaluation.get("archive", {}).get("ready"):
        return "auto_archive_ready", "gate_evaluator_archive_ready_report_only"
    if "pre_instrumentation_unknown" in blockers or "coverage_window_not_mature" in blockers:
        return "manual_lifecycle_review", "usage_coverage_not_mature"
    if blockers:
        return "manual_lifecycle_review", "usage_cleanup_blockers_present"
    if candidate.get("classification") == "deprecated_candidate" and no_refs:
        return "archive_review_candidate", "deprecated_candidate_with_no_refs_after_usage_checks"
    if no_refs:
        return "manual_lifecycle_review", "no_refs_but_manual_or_diagnostic_class"
    return "manual_review_required", "unclassified_cleanup_state"


def load_lifecycle_overrides() -> dict[str, Any]:
    payload = load_json_if_exists(SCRIPT_LIFECYCLE_OVERRIDES_JSON)
    overrides = payload.get("overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError(f"invalid overrides payload: {SCRIPT_LIFECYCLE_OVERRIDES_JSON}")
    return overrides


def apply_lifecycle_overrides(records: list[dict[str, Any]], overrides: dict[str, Any]) -> dict[str, Any]:
    by_path = {str(record.get("path")): record for record in records}
    applied: list[dict[str, Any]] = []
    missing: list[str] = []
    for path, override in sorted(overrides.items()):
        if path not in by_path:
            missing.append(path)
            continue
        record = by_path[path]
        record["lifecycle_override"] = override
        applied.append(
            {
                "path": path,
                "classification": record.get("classification"),
                "lifecycle_status": override.get("lifecycle_status"),
                "review_after": override.get("review_after"),
            }
        )
    return {
        "override_count": len(overrides),
        "applied_count": len(applied),
        "missing_count": len(missing),
        "applied": applied,
        "missing_paths": missing,
    }


def build_summary(clutter_payload: dict[str, Any]) -> dict[str, Any]:
    classification = load_json(SCRIPT_CLASSIFICATION_JSON)
    usage_summary = load_json_if_exists(SCRIPT_USAGE_SUMMARY_JSON)
    usage_by_path = keyed_script_usage(usage_summary)
    class_summary = classification["summary"]
    records = classification["records"]
    lifecycle_overrides = load_lifecycle_overrides()
    override_summary = apply_lifecycle_overrides(records, lifecycle_overrides)
    review_classes = {
        "deprecated_candidate",
        "diagnostic_harness",
        "manual_repair",
        "migration_backfill",
        "unreferenced_library_review",
    }
    review_records = [r for r in records if r["classification"] in review_classes]
    medium_records = [r for r in records if r["confidence"] != "high"]
    return {
        "schema_version": "orchestrator-maintenance-summary/v1",
        "script_classification": class_summary,
        "review_candidate_count": len(review_records),
        "medium_confidence_count": len(medium_records),
        "review_candidates": [
            {
                "path": r["path"],
                "classification": r["classification"],
                "confidence": r["confidence"],
                "inbound_reference_count": r["inbound_reference_count"],
                "lifecycle_override": r.get("lifecycle_override"),
                "script_usage": usage_by_path.get(str(r["path"]), {}),
            }
            for r in review_records
        ],
        "lifecycle_overrides": override_summary,
        "generated_clutter": generated_clutter_summary(clutter_payload),
        "script_usage": generated_script_usage_summary(usage_summary),
    }


def keyed_review_candidates(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["path"]): item for item in summary.get("review_candidates", [])}


def count_delta(current: dict[str, Any], previous: dict[str, Any], key: str) -> dict[str, int]:
    previous_value = int(previous.get(key, 0) or 0)
    current_value = int(current.get(key, 0) or 0)
    return {
        "previous": previous_value,
        "current": current_value,
        "delta": current_value - previous_value,
    }


def dict_count_delta(current: dict[str, Any], previous: dict[str, Any], key: str) -> dict[str, dict[str, int]]:
    current_counts = current.get(key, {}) or {}
    previous_counts = previous.get(key, {}) or {}
    result: dict[str, dict[str, int]] = {}
    for name in sorted(set(current_counts) | set(previous_counts)):
        result[name] = {
            "previous": int(previous_counts.get(name, 0) or 0),
            "current": int(current_counts.get(name, 0) or 0),
            "delta": int(current_counts.get(name, 0) or 0) - int(previous_counts.get(name, 0) or 0),
        }
    return result


def build_drift_report(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {
            "schema_version": "orchestrator-maintenance-drift/v1",
            "baseline_available": False,
            "message": "No previous maintenance summary was available for drift comparison.",
        }

    current_script = current.get("script_classification", {})
    previous_script = previous.get("script_classification", {})
    current_review = keyed_review_candidates(current)
    previous_review = keyed_review_candidates(previous)
    new_review_paths = sorted(set(current_review) - set(previous_review))
    removed_review_paths = sorted(set(previous_review) - set(current_review))
    new_medium_paths = sorted(
        path
        for path, item in current_review.items()
        if item.get("confidence") != "high" and previous_review.get(path, {}).get("confidence") == "high"
    )
    new_unoverridden_review_paths = sorted(
        path
        for path in current_review
        if not current_review[path].get("lifecycle_override")
        and (path not in previous_review or previous_review[path].get("lifecycle_override"))
    )
    return {
        "schema_version": "orchestrator-maintenance-drift/v1",
        "baseline_available": True,
        "script_count": count_delta(current_script, previous_script, "script_count"),
        "line_count": count_delta(current_script, previous_script, "line_count"),
        "large_files_over_500_lines": count_delta(current_script, previous_script, "large_files_over_500_lines"),
        "large_files_over_1000_lines": count_delta(current_script, previous_script, "large_files_over_1000_lines"),
        "class_counts": dict_count_delta(current_script, previous_script, "class_counts"),
        "confidence_counts": dict_count_delta(current_script, previous_script, "confidence_counts"),
        "review_candidate_count": count_delta(current, previous, "review_candidate_count"),
        "medium_confidence_count": count_delta(current, previous, "medium_confidence_count"),
        "generated_clutter_count": count_delta(current.get("generated_clutter", {}), previous.get("generated_clutter", {}), "count"),
        "new_review_candidate_paths": new_review_paths,
        "removed_review_candidate_paths": removed_review_paths,
        "new_medium_confidence_paths": new_medium_paths,
        "new_unoverridden_review_candidate_paths": new_unoverridden_review_paths,
        "lifecycle_override_count": count_delta(current.get("lifecycle_overrides", {}), previous.get("lifecycle_overrides", {}), "override_count"),
        "lifecycle_override_missing_count": count_delta(current.get("lifecycle_overrides", {}), previous.get("lifecycle_overrides", {}), "missing_count"),
    }


def cleanup_actions_by_path(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    actions = plan.get("script_review_actions", []) if isinstance(plan.get("script_review_actions"), list) else []
    return {str(item.get("path")): item for item in actions if item.get("path")}


def cleanup_history_by_path(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = history.get("candidates", {}) if isinstance(history.get("candidates"), dict) else {}
    return {str(path): item for path, item in candidates.items() if isinstance(item, dict)}


def sorted_count_delta(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        key: {
            "previous": int(previous.get(key, 0) or 0),
            "current": int(current.get(key, 0) or 0),
            "delta": int(current.get(key, 0) or 0) - int(previous.get(key, 0) or 0),
        }
        for key in sorted(set(current) | set(previous))
    }


def build_cleanup_evidence_diff(
    current_plan: dict[str, Any],
    previous_plan: dict[str, Any],
    current_history: dict[str, Any],
    previous_history: dict[str, Any],
    *,
    max_paths: int = 30,
) -> dict[str, Any]:
    if not previous_plan:
        return {
            "schema_version": "orchestrator-cleanup-evidence-diff/v1",
            "baseline_available": False,
            "meaningful_change_count": 0,
            "message": "No previous cleanup plan was available for evidence diffing.",
        }

    current_summary = current_plan.get("summary", {}) if isinstance(current_plan.get("summary"), dict) else {}
    previous_summary = previous_plan.get("summary", {}) if isinstance(previous_plan.get("summary"), dict) else {}
    current_actions = cleanup_actions_by_path(current_plan)
    previous_actions = cleanup_actions_by_path(previous_plan)
    current_hist = cleanup_history_by_path(current_history)
    previous_hist = cleanup_history_by_path(previous_history)

    new_paths = sorted(set(current_actions) - set(previous_actions))
    removed_paths = sorted(set(previous_actions) - set(current_actions))
    action_changed_paths = sorted(
        path
        for path in set(current_actions) & set(previous_actions)
        if current_actions[path].get("planned_action") != previous_actions[path].get("planned_action")
        or current_actions[path].get("reason") != previous_actions[path].get("reason")
    )
    blocker_changed_paths = sorted(
        path
        for path in set(current_actions) & set(previous_actions)
        if current_actions[path].get("cleanup_gate_evaluation", {}).get("archive", {}).get("blockers", [])
        != previous_actions[path].get("cleanup_gate_evaluation", {}).get("archive", {}).get("blockers", [])
        or current_actions[path].get("cleanup_gate_evaluation", {}).get("delete", {}).get("blockers", [])
        != previous_actions[path].get("cleanup_gate_evaluation", {}).get("delete", {}).get("blockers", [])
    )
    maturity_changed_paths = sorted(
        path
        for path in set(current_hist) & set(previous_hist)
        if bool(current_hist[path].get("observation_window", {}).get("mature"))
        != bool(previous_hist[path].get("observation_window", {}).get("mature"))
    )
    new_mature_paths = [path for path in maturity_changed_paths if current_hist[path].get("observation_window", {}).get("mature")]
    no_longer_mature_paths = [path for path in maturity_changed_paths if not current_hist[path].get("observation_window", {}).get("mature")]

    action_count_delta = sorted_count_delta(current_summary.get("action_counts", {}) or {}, previous_summary.get("action_counts", {}) or {})
    gate_ready_delta = sorted_count_delta(current_summary.get("gate_ready_counts", {}) or {}, previous_summary.get("gate_ready_counts", {}) or {})
    meaningful_change_count = (
        len(new_paths)
        + len(removed_paths)
        + len(action_changed_paths)
        + len(blocker_changed_paths)
        + len(maturity_changed_paths)
        + sum(1 for item in action_count_delta.values() if item["delta"] != 0)
        + sum(1 for item in gate_ready_delta.values() if item["delta"] != 0)
    )
    return {
        "schema_version": "orchestrator-cleanup-evidence-diff/v1",
        "baseline_available": True,
        "quiet_mode": True,
        "meaningful_change_count": meaningful_change_count,
        "action_count_delta": action_count_delta,
        "gate_ready_delta": gate_ready_delta,
        "new_script_action_paths": new_paths[:max_paths],
        "removed_script_action_paths": removed_paths[:max_paths],
        "action_changed_paths": action_changed_paths[:max_paths],
        "blocker_changed_paths": blocker_changed_paths[:max_paths],
        "new_mature_no_use_paths": new_mature_paths[:max_paths],
        "no_longer_mature_no_use_paths": no_longer_mature_paths[:max_paths],
        "truncated": any(len(values) > max_paths for values in [new_paths, removed_paths, action_changed_paths, blocker_changed_paths, new_mature_paths, no_longer_mature_paths]),
        "note": "D5 reports path/action/blocker/maturity changes and count deltas only; routine history counter increments are intentionally suppressed.",
    }


def render_cleanup_evidence_diff_markdown(diff: dict[str, Any]) -> str:
    lines = ["# Cleanup Evidence Diff", ""]
    if not diff.get("baseline_available"):
        lines.append(diff.get("message", "No baseline available."))
        lines.append("")
        return "\n".join(lines)
    lines.append(f"Meaningful change count: **{diff.get('meaningful_change_count', 0)}**")
    lines.append("")
    lines.append("## Count deltas")
    lines.append("")
    for title, key in [("Action counts", "action_count_delta"), ("Gate-ready counts", "gate_ready_delta")]:
        lines.append(f"### {title}")
        lines.append("")
        deltas = diff.get(key, {}) if isinstance(diff.get(key), dict) else {}
        changed = {name: value for name, value in deltas.items() if int(value.get("delta", 0) or 0) != 0}
        if changed:
            for name, value in changed.items():
                lines.append(f"- `{name}`: {value.get('previous')} -> {value.get('current')} (`{value.get('delta')}`)")
        else:
            lines.append("_No meaningful count changes._")
        lines.append("")
    sections = [
        ("New script action paths", "new_script_action_paths"),
        ("Removed script action paths", "removed_script_action_paths"),
        ("Action/reason changed paths", "action_changed_paths"),
        ("Gate blocker changed paths", "blocker_changed_paths"),
        ("New mature no-use paths", "new_mature_no_use_paths"),
        ("No-longer mature no-use paths", "no_longer_mature_no_use_paths"),
    ]
    for title, key in sections:
        values = diff.get(key, []) if isinstance(diff.get(key), list) else []
        lines.append(f"## {title} ({len(values)})")
        lines.append("")
        if values:
            lines.extend(f"- `{value}`" for value in values)
        else:
            lines.append("_None._")
        lines.append("")
    if diff.get("truncated"):
        lines.append("_Some path lists were truncated._")
        lines.append("")
    return "\n".join(lines)


def write_cleanup_evidence_diff(current_plan: dict[str, Any], previous_plan: dict[str, Any], current_history: dict[str, Any], previous_history: dict[str, Any]) -> dict[str, Any]:
    diff = build_cleanup_evidence_diff(current_plan, previous_plan, current_history, previous_history)
    CLEANUP_EVIDENCE_DIFF_JSON.write_text(json.dumps(diff, indent=2, sort_keys=True) + "\n")
    CLEANUP_EVIDENCE_DIFF_MD.write_text(render_cleanup_evidence_diff_markdown(diff))
    return diff


def script_rows_by_path(usage_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scripts = usage_summary.get("scripts", []) if isinstance(usage_summary.get("scripts"), list) else []
    return {str(item.get("path")): item for item in scripts if isinstance(item, dict) and item.get("path")}


def row_has_reference_evidence(row: dict[str, Any]) -> bool:
    return bool(
        int(row.get("inbound_reference_count", 0) or 0) > 0
        or row.get("reference_evidence")
        or any(source in set(row.get("evidence_sources") or []) for source in ("cron", "launchd", "operator_docs", "runtime_logs"))
    )


def blocker_core(blocker: str) -> str:
    if blocker.startswith("usage:"):
        return blocker.split(":", 1)[1]
    if blocker.startswith("verification:"):
        return blocker.split(":", 1)[1]
    return blocker


def cleanup_blocker_next_action(blocker: str) -> dict[str, Any]:
    core = blocker_core(str(blocker))
    command = "python3 run_scheduled_maintenance.py --mode script-evidence-refresh"
    evidence_refresh = {
        "pre_instrumentation_unknown",
        "no_observed_ledger_usage",
        "coverage_window_not_mature",
        "missing_usage_summary_row",
        "has_static_inbound_references",
        "has_cron_reference",
        "has_launchd_reference",
        "has_operator_doc_reference",
        "has_runtime_log_reference",
        "no_static_inbound_refs",
        "operator_docs_checked",
        "launchd_cron_checked",
        "external_usage_checked",
        "runtime_state_checked",
        "source_present",
        "tracked_by_git",
    }
    lifecycle_refresh = {
        "lifecycle_not_archive_approved",
        "lifecycle_not_removal_approved",
        "lifecycle_approved",
        "removal_eligible_class",
        "underlying_condition_resolved_if_needed",
        "archive_path_defined",
    }
    quarantine_wait = {
        "not_archived_for_one_cycle",
        "not_in_archived_quarantine",
        "archived_for_one_cycle",
    }
    if core in evidence_refresh:
        return {
            "blocker": blocker,
            "action": "refresh_usage_reference_and_runtime_evidence",
            "owner_lane": "Maintenance: Orchestrator Script Evidence Refresh",
            "autonomous": True,
            "mutating": False,
            "command": command,
        }
    if core in lifecycle_refresh:
        return {
            "blocker": blocker,
            "action": "rerun_deterministic_archive_promotion_checks",
            "owner_lane": "Maintenance: Orchestrator Script Evidence Refresh",
            "autonomous": True,
            "mutating": False,
            "command": command,
        }
    if core in quarantine_wait:
        return {
            "blocker": blocker,
            "action": "continue_quarantine_monitoring_until_delete_ready",
            "owner_lane": "Maintenance: Orchestrator Script Auto-Delete Apply",
            "autonomous": True,
            "mutating": False,
            "command": "python3 run_scheduled_maintenance.py --mode script-auto-delete-apply",
        }
    if core in {"observed_ledger_usage", "referenced_by_static_or_c4_evidence"}:
        return {
            "blocker": blocker,
            "action": "retain_currently_used_or_referenced_script",
            "owner_lane": "Maintenance: Orchestrator Script Evidence Refresh",
            "autonomous": True,
            "mutating": False,
            "command": command,
        }
    return {
        "blocker": blocker,
        "action": "surface_unknown_blocker_for_owner_attention",
        "owner_lane": "Maintenance owner review",
        "autonomous": False,
        "mutating": False,
        "command": None,
    }


def cleanup_action_blockers(action: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    usage = action.get("usage_cleanup", {}) if isinstance(action.get("usage_cleanup"), dict) else {}
    blockers.extend(str(item) for item in usage.get("cleanup_eligibility_blockers", []) if item)
    for gate in ("archive", "delete"):
        gate_payload = action.get("cleanup_gate_evaluation", {}).get(gate, {}) if isinstance(action.get("cleanup_gate_evaluation"), dict) else {}
        blockers.extend(str(item) for item in gate_payload.get("blockers", []) if item)
    return sorted(set(blockers))


def build_script_cleanup_blocker_report(cleanup_plan: dict[str, Any], usage_summary: dict[str, Any]) -> dict[str, Any]:
    actions = cleanup_plan.get("script_review_actions", []) if isinstance(cleanup_plan.get("script_review_actions"), list) else []
    records: list[dict[str, Any]] = []
    blocker_counts: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    stranded_unknown_paths: list[str] = []
    autonomous_next_action_count = 0
    manual_owner_review_required_count = 0
    for action in actions:
        path = str(action.get("path"))
        blockers = cleanup_action_blockers(action)
        blocker_counts.update(blockers)
        next_actions: list[dict[str, Any]] = []
        for blocker in blockers:
            next_action = cleanup_blocker_next_action(blocker)
            next_actions.append(next_action)
            lane_counts[str(next_action.get("owner_lane"))] += 1
            action_counts[str(next_action.get("action"))] += 1
            if next_action.get("autonomous"):
                autonomous_next_action_count += 1
            else:
                manual_owner_review_required_count += 1
        usage = action.get("usage_cleanup", {}) if isinstance(action.get("usage_cleanup"), dict) else {}
        if usage.get("coverage_status") == "pre_instrumentation_unknown":
            stranded_unknown_paths.append(path)
        records.append(
            {
                "path": path,
                "classification": action.get("classification"),
                "planned_action": action.get("planned_action"),
                "reason": action.get("reason"),
                "coverage_status": usage.get("coverage_status"),
                "archive_ready": bool(action.get("cleanup_gate_evaluation", {}).get("archive", {}).get("ready")),
                "delete_ready": bool(action.get("cleanup_gate_evaluation", {}).get("delete", {}).get("ready")),
                "blockers": blockers,
                "next_actions": next_actions,
            }
        )
    ready_archive = [item["path"] for item in records if item.get("archive_ready")]
    ready_delete = [item["path"] for item in records if item.get("delete_ready")]
    usage_rows = script_rows_by_path(usage_summary)
    observed_count = sum(1 for item in usage_rows.values() if item.get("coverage_status") == "direct")
    referenced_count = sum(1 for item in usage_rows.values() if row_has_reference_evidence(item))
    stranded_with_action = [
        item["path"]
        for item in records
        if item["path"] in stranded_unknown_paths and any(next_action.get("autonomous") for next_action in item.get("next_actions", []))
    ]
    next_actions_by_lane = {
        lane: {
            "count": count,
            "autonomous": lane != "Maintenance owner review",
        }
        for lane, count in sorted(lane_counts.items())
    }
    return {
        "schema_version": "orchestrator-script-cleanup-blockers/v1",
        "generated_at_utc": utc_now_iso(),
        "mode": "non_mutating_evidence_refresh",
        "mutating": False,
        "candidate_count": len(records),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "next_action_counts": dict(sorted(action_counts.items())),
        "next_actions_by_lane": next_actions_by_lane,
        "autonomous_next_action_count": autonomous_next_action_count,
        "manual_owner_review_required_count": manual_owner_review_required_count,
        "ready_candidate_slo": {
            "name": "zero_stranded_unknown_without_autonomous_next_action",
            "stranded_unknown_count": len(stranded_unknown_paths),
            "stranded_unknown_with_autonomous_next_action_count": len(stranded_with_action),
            "met": len(stranded_unknown_paths) == len(stranded_with_action),
        },
        "usage_evidence_counts": {
            "observed_script_count": observed_count,
            "referenced_script_count": referenced_count,
            "pre_instrumentation_unknown_count": int(usage_summary.get("summary", {}).get("pre_instrumentation_unknown_count", 0) or 0),
        },
        "ready_candidate_counts": {
            "archive": len(ready_archive),
            "delete": len(ready_delete),
        },
        "ready_archive_paths": sorted(ready_archive),
        "ready_delete_paths": sorted(ready_delete),
        "records": sorted(records, key=lambda item: item["path"]),
        "note": "Next actions are lane-owned automation work. Evidence refresh is non-mutating; archive/delete remains guarded by readiness gates.",
    }


def render_script_cleanup_blocker_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Cleanup Blockers", ""]
    lines.append(f"Generated: `{payload.get('generated_at_utc')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Candidates: **{payload.get('candidate_count', 0)}**")
    lines.append(f"Autonomous next actions: **{payload.get('autonomous_next_action_count', 0)}**")
    lines.append(f"Owner-review next actions: **{payload.get('manual_owner_review_required_count', 0)}**")
    slo = payload.get("ready_candidate_slo", {}) if isinstance(payload.get("ready_candidate_slo"), dict) else {}
    lines.append(f"Stranded unknown SLO met: **{slo.get('met', False)}**")
    lines.append("")
    lines.append("## Next Actions By Lane")
    lines.append("")
    lanes = payload.get("next_actions_by_lane", {}) if isinstance(payload.get("next_actions_by_lane"), dict) else {}
    if lanes:
        for lane, item in lanes.items():
            lines.append(f"- `{lane}`: {item.get('count', 0)} autonomous={item.get('autonomous', False)}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Blocker Counts")
    lines.append("")
    blockers = payload.get("blocker_counts", {}) if isinstance(payload.get("blocker_counts"), dict) else {}
    if blockers:
        for blocker, count in blockers.items():
            lines.append(f"- `{blocker}`: {count}")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def write_script_cleanup_blocker_report(cleanup_plan: dict[str, Any], usage_summary: dict[str, Any]) -> dict[str, Any]:
    payload = build_script_cleanup_blocker_report(cleanup_plan, usage_summary)
    SCRIPT_CLEANUP_BLOCKERS_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    SCRIPT_CLEANUP_BLOCKERS_MD.write_text(render_script_cleanup_blocker_markdown(payload))
    return payload


def build_script_cleanup_evidence_movement(
    previous_usage_summary: dict[str, Any],
    current_usage_summary: dict[str, Any],
    previous_cleanup_plan: dict[str, Any],
    current_cleanup_plan: dict[str, Any],
    previous_blocker_report: dict[str, Any],
    current_blocker_report: dict[str, Any],
) -> dict[str, Any]:
    previous_rows = script_rows_by_path(previous_usage_summary)
    current_rows = script_rows_by_path(current_usage_summary)
    previous_unknown = {path for path, item in previous_rows.items() if item.get("coverage_status") == "pre_instrumentation_unknown"}
    current_unknown = {path for path, item in current_rows.items() if item.get("coverage_status") == "pre_instrumentation_unknown"}
    previous_observed = {path for path, item in previous_rows.items() if item.get("coverage_status") == "direct"}
    current_observed = {path for path, item in current_rows.items() if item.get("coverage_status") == "direct"}
    previous_referenced = {path for path, item in previous_rows.items() if row_has_reference_evidence(item)}
    current_referenced = {path for path, item in current_rows.items() if row_has_reference_evidence(item)}
    previous_actions = cleanup_actions_by_path(previous_cleanup_plan)
    current_actions = cleanup_actions_by_path(current_cleanup_plan)
    retained_now = {
        path
        for path, item in current_actions.items()
        if item.get("planned_action") in {"retain_recently_used", "retain_referenced"}
    }
    retired_paths = sorted((set(previous_actions) - set(current_actions)) | retained_now)
    previous_blockers = previous_blocker_report.get("blocker_counts", {}) if isinstance(previous_blocker_report.get("blocker_counts"), dict) else {}
    current_blockers = current_blocker_report.get("blocker_counts", {}) if isinstance(current_blocker_report.get("blocker_counts"), dict) else {}
    blocker_retired_count = sum(max(0, int(previous_blockers.get(key, 0) or 0) - int(current_blockers.get(key, 0) or 0)) for key in set(previous_blockers) | set(current_blockers))
    ready_counts = current_cleanup_plan.get("summary", {}).get("gate_ready_counts", {}) if isinstance(current_cleanup_plan.get("summary"), dict) else {}
    movement_score = (
        len(previous_unknown - current_unknown)
        + len(current_observed - previous_observed)
        + len(current_referenced - previous_referenced)
        + len(retired_paths)
        + blocker_retired_count
        + int(ready_counts.get("archive", 0) or 0)
        + int(ready_counts.get("delete", 0) or 0)
    )
    if movement_score > 0:
        throughput_status = "evidence_moved"
    elif current_blocker_report.get("autonomous_next_action_count", 0):
        throughput_status = "waiting_on_autonomous_next_actions"
    elif current_blocker_report.get("manual_owner_review_required_count", 0):
        throughput_status = "owner_review_required"
    else:
        throughput_status = "no_action_needed"
    return {
        "schema_version": "orchestrator-script-cleanup-evidence-movement/v1",
        "generated_at_utc": utc_now_iso(),
        "mode": "non_mutating_evidence_refresh",
        "mutating": False,
        "baseline_available": bool(previous_usage_summary or previous_cleanup_plan or previous_blocker_report),
        "unknown_reduced_count": len(previous_unknown - current_unknown),
        "unknown_reduced_paths": sorted(previous_unknown - current_unknown)[:30],
        "new_observed_count": len(current_observed - previous_observed),
        "new_observed_paths": sorted(current_observed - previous_observed)[:30],
        "new_referenced_count": len(current_referenced - previous_referenced),
        "new_referenced_paths": sorted(current_referenced - previous_referenced)[:30],
        "ready_candidate_count": int(ready_counts.get("archive", 0) or 0) + int(ready_counts.get("delete", 0) or 0),
        "ready_candidate_counts": {
            "archive": int(ready_counts.get("archive", 0) or 0),
            "delete": int(ready_counts.get("delete", 0) or 0),
        },
        "retired_candidate_count": len(retired_paths),
        "retired_candidate_paths": retired_paths[:30],
        "stranded_unknown_count": len(current_unknown),
        "blocker_retired_count": blocker_retired_count,
        "throughput_status": throughput_status,
        "next_actions_by_lane": current_blocker_report.get("next_actions_by_lane", {}),
        "zero_archive_delete_throughput_acceptable": (
            movement_score > 0
            or bool(current_blocker_report.get("autonomous_next_action_count", 0))
            or bool(current_blocker_report.get("manual_owner_review_required_count", 0))
        ),
    }


def render_script_cleanup_evidence_movement_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Cleanup Evidence Movement", ""]
    lines.append(f"Generated: `{payload.get('generated_at_utc')}`")
    lines.append(f"Throughput status: **{payload.get('throughput_status')}**")
    lines.append(f"Zero archive/delete throughput acceptable: **{payload.get('zero_archive_delete_throughput_acceptable', False)}**")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    for key in [
        "unknown_reduced_count",
        "new_observed_count",
        "new_referenced_count",
        "ready_candidate_count",
        "retired_candidate_count",
        "stranded_unknown_count",
        "blocker_retired_count",
    ]:
        lines.append(f"- `{key}`: {payload.get(key, 0)}")
    lines.append("")
    return "\n".join(lines)


def write_script_cleanup_evidence_movement(
    previous_usage_summary: dict[str, Any],
    current_usage_summary: dict[str, Any],
    previous_cleanup_plan: dict[str, Any],
    current_cleanup_plan: dict[str, Any],
    previous_blocker_report: dict[str, Any],
    current_blocker_report: dict[str, Any],
) -> dict[str, Any]:
    payload = build_script_cleanup_evidence_movement(
        previous_usage_summary,
        current_usage_summary,
        previous_cleanup_plan,
        current_cleanup_plan,
        previous_blocker_report,
        current_blocker_report,
    )
    SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_MD.write_text(render_script_cleanup_evidence_movement_markdown(payload))
    return payload


def render_drift_markdown(drift: dict[str, Any]) -> str:
    lines = ["# Maintenance Drift", ""]
    if not drift.get("baseline_available"):
        lines.append(drift.get("message", "No baseline available."))
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "## Summary",
            "",
            f"- Script count delta: `{drift['script_count']['delta']}` ({drift['script_count']['previous']} -> {drift['script_count']['current']})",
            f"- Review candidate delta: `{drift['review_candidate_count']['delta']}` ({drift['review_candidate_count']['previous']} -> {drift['review_candidate_count']['current']})",
            f"- Medium-confidence delta: `{drift['medium_confidence_count']['delta']}` ({drift['medium_confidence_count']['previous']} -> {drift['medium_confidence_count']['current']})",
            f"- Generated clutter delta: `{drift['generated_clutter_count']['delta']}` ({drift['generated_clutter_count']['previous']} -> {drift['generated_clutter_count']['current']})",
            f"- Large files >500 lines delta: `{drift['large_files_over_500_lines']['delta']}`",
            f"- Large files >1000 lines delta: `{drift['large_files_over_1000_lines']['delta']}`",
            "",
        ]
    )
    sections = [
        ("New review candidates", "new_review_candidate_paths"),
        ("Removed review candidates", "removed_review_candidate_paths"),
        ("New medium-confidence review paths", "new_medium_confidence_paths"),
        ("New review candidates without lifecycle overrides", "new_unoverridden_review_candidate_paths"),
    ]
    for title, key in sections:
        values = drift.get(key, [])
        lines.append(f"## {title} ({len(values)})")
        lines.append("")
        if values:
            lines.extend(f"- `{value}`" for value in values)
        else:
            lines.append("_None._")
        lines.append("")
    return "\n".join(lines)


def git_status_summary() -> dict[str, Any]:
    proc = subprocess.run(["git", "status", "--short"], cwd=str(REPO_ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        return {"available": False, "error": proc.stderr.strip(), "count": 0, "tracked_modified_count": 0, "untracked_count": 0}
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    tracked_modified = [line for line in lines if not line.startswith("??")]
    untracked = [line for line in lines if line.startswith("??")]
    return {
        "available": True,
        "count": len(lines),
        "tracked_modified_count": len(tracked_modified),
        "untracked_count": len(untracked),
        "sample": lines[:40],
        "truncated": len(lines) > 40,
    }


def project_config_summary() -> dict[str, Any]:
    config_files = ["pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "requirements.txt", "requirements-dev.txt"]
    present = [name for name in config_files if (REPO_ROOT / name).exists()]
    return {
        "present": present,
        "missing_core_test_config": not any(name in present for name in ["pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"]),
    }


def score_band(score: int) -> str:
    if score >= 85:
        return "good"
    if score >= 70:
        return "watch"
    return "needs_attention"


def health_component(name: str, score: int, findings: list[str], recommendations: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "score": score,
        "band": score_band(score),
        "findings": findings,
        "recommendations": recommendations,
    }


def build_repo_health_scorecard(summary: dict[str, Any], drift: dict[str, Any], clutter_payload: dict[str, Any]) -> dict[str, Any]:
    script_summary = summary["script_classification"]
    class_counts = script_summary["class_counts"]
    git_status = git_status_summary()
    config = project_config_summary()
    script_count = int(script_summary["script_count"])
    review_count = int(summary["review_candidate_count"])
    medium_count = int(summary["medium_confidence_count"])
    large_500 = int(script_summary["large_files_over_500_lines"])
    large_1000 = int(script_summary["large_files_over_1000_lines"])
    clutter_count = int(clutter_payload["count"])
    runtime_state_count = int(clutter_payload["category_counts"].get("runtime_state", 0))
    override_missing = int(summary["lifecycle_overrides"].get("missing_count", 0))

    lifecycle_score = max(0, 100 - medium_count * 4 - override_missing * 10 - max(0, review_count - 12))
    dependency_score = max(0, 82 - large_1000 * 2 - max(0, large_500 - 40))
    clutter_score = max(0, 100 - clutter_count - runtime_state_count * 3)
    worktree_score = 100 if git_status["count"] == 0 else max(0, 90 - min(git_status["count"], 80))
    config_score = 55 if config["missing_core_test_config"] else 85
    drift_score = 85
    if drift.get("baseline_available"):
        drift_score = max(
            0,
            100
            - abs(int(drift["review_candidate_count"]["delta"])) * 8
            - abs(int(drift["medium_confidence_count"]["delta"])) * 8
            - abs(int(drift["generated_clutter_count"]["delta"])) * 2
            - len(drift.get("new_unoverridden_review_candidate_paths", [])) * 10,
        )

    components = [
        health_component(
            "script_lifecycle_clarity",
            lifecycle_score,
            [
                f"{script_count} script-like files classified",
                f"{review_count} review candidates",
                f"{medium_count} medium-confidence candidates",
                f"{summary['lifecycle_overrides']['applied_count']} lifecycle overrides applied",
            ],
            ["Review medium-confidence candidates first", "Keep lifecycle overrides current as scripts move/archive"],
        ),
        health_component(
            "dependency_explicitness_and_size",
            dependency_score,
            [f"{large_500} files exceed 500 lines", f"{large_1000} files exceed 1000 lines"],
            ["Extract pure helpers from largest orchestration/materializer scripts", "Prefer explicit module calls over implicit subprocess conventions where safe"],
        ),
        health_component(
            "generated_clutter",
            clutter_score,
            [f"{clutter_count} clutter candidates", f"{runtime_state_count} runtime-state directories require owner review"],
            ["Clean .DS_Store files after git-status check", "Clean __pycache__ after process check", "Do not delete runtime-state without owner review"],
        ),
        health_component(
            "working_tree_cleanliness",
            worktree_score,
            [f"{git_status['count']} git status entries", f"{git_status['tracked_modified_count']} tracked modified entries", f"{git_status['untracked_count']} untracked entries"],
            ["Preserve commit split before large cleanup", "Avoid mixing maintenance commits with pipeline feature work"],
        ),
        health_component(
            "central_project_config",
            config_score,
            ["present config files: " + (", ".join(config["present"]) if config["present"] else "none")],
            [
                "Keep pytest/pyproject exclusions aligned with generated/runtime directories"
                if not config["missing_core_test_config"]
                else "Add minimal pytest.ini or pyproject.toml with test discovery and generated/runtime exclusions"
            ],
        ),
        health_component(
            "maintenance_drift_control",
            drift_score,
            ["baseline available" if drift.get("baseline_available") else "no baseline available"],
            ["Investigate nonzero deltas before cleanup/refactors", "Keep generated reports deterministic"],
        ),
    ]
    overall = round(sum(component["score"] for component in components) / len(components), 1)
    return {
        "schema_version": "orchestrator-repo-health-summary/v1",
        "overall_score": overall,
        "overall_band": score_band(int(overall)),
        "components": components,
        "git_status": git_status,
        "project_config": config,
    }


def render_repo_health_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Repo Health Summary", ""]
    lines.append(f"Overall score: **{payload['overall_score']}** (`{payload['overall_band']}`)")
    lines.append("")
    lines.append("## Components")
    lines.append("")
    for component in payload["components"]:
        lines.append(f"### {component['name']} — {component['score']} (`{component['band']}`)")
        lines.append("")
        lines.append("Findings:")
        for finding in component["findings"]:
            lines.append(f"- {finding}")
        lines.append("")
        lines.append("Recommendations:")
        for recommendation in component["recommendations"]:
            lines.append(f"- {recommendation}")
        lines.append("")
    lines.append("## Git status sample")
    lines.append("")
    sample = payload["git_status"].get("sample", [])
    if sample:
        for line in sample:
            lines.append(f"- `{line}`")
        if payload["git_status"].get("truncated"):
            lines.append("- _sample truncated_")
    else:
        lines.append("_Clean or unavailable._")
    lines.append("")
    return "\n".join(lines)


def write_repo_health_scorecard(summary: dict[str, Any], drift: dict[str, Any], clutter_payload: dict[str, Any]) -> dict[str, Any]:
    payload = build_repo_health_scorecard(summary, drift, clutter_payload)
    REPO_HEALTH_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    REPO_HEALTH_MD.write_text(render_repo_health_markdown(payload))
    return payload


def git_tracked_paths() -> set[str]:
    proc = subprocess.run(["git", "ls-files"], cwd=str(REPO_ROOT), text=True, capture_output=True)
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed_days(start: str | None, end: str | None) -> int:
    start_dt = parse_iso_datetime(start)
    end_dt = parse_iso_datetime(end)
    if start_dt is None or end_dt is None:
        return 0
    return max(0, (end_dt - start_dt).days)


def stable_candidate_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("planned_action") or ""),
            str(item.get("classification") or ""),
            str(item.get("reason") or ""),
            str(item.get("usage_cleanup", {}).get("coverage_status") or ""),
        ]
    )


def no_use_observed(item: dict[str, Any]) -> bool:
    usage = item.get("usage_cleanup", {}) if isinstance(item.get("usage_cleanup"), dict) else {}
    return bool(
        usage.get("usage_summary_available")
        and not usage.get("observed_recently_or_directly")
        and int(usage.get("run_count_total") or 0) == 0
    )


def candidate_history_entry(path: str, item: dict[str, Any], prior: dict[str, Any], now_iso: str) -> dict[str, Any]:
    current_key = stable_candidate_key(item)
    prior_key = prior.get("candidate_state_key")
    consecutive_same_state = int(prior.get("consecutive_same_state_count", 0) or 0) + 1 if current_key == prior_key else 1
    current_no_use = no_use_observed(item)
    prior_window = prior.get("observation_window", {}) if isinstance(prior.get("observation_window"), dict) else {}
    if current_no_use:
        consecutive_no_use = int(prior.get("consecutive_no_use_count", 0) or 0) + 1
        first_no_use_at = prior_window.get("first_no_use_at") or prior.get("first_no_use_at") or now_iso
        last_no_use_at = now_iso
    else:
        consecutive_no_use = 0
        first_no_use_at = None
        last_no_use_at = None
    no_use_days = elapsed_days(first_no_use_at, last_no_use_at)
    observation_window = {
        "mature": no_use_days >= 45 and consecutive_no_use >= 3,
        "required_days": 45,
        "required_no_use_observations": 3,
        "no_use_days": no_use_days,
        "first_no_use_at": first_no_use_at,
        "last_no_use_at": last_no_use_at,
    }
    return {
        "path": path,
        "first_seen_at": prior.get("first_seen_at") or now_iso,
        "last_seen_at": now_iso,
        "candidate_state_key": current_key,
        "last_planned_action": item.get("planned_action"),
        "last_classification": item.get("classification"),
        "last_reason": item.get("reason"),
        "consecutive_same_state_count": consecutive_same_state,
        "total_seen_count": int(prior.get("total_seen_count", 0) or 0) + 1,
        "consecutive_no_use_count": consecutive_no_use,
        "total_no_use_observation_count": int(prior.get("total_no_use_observation_count", 0) or 0) + (1 if current_no_use else 0),
        "observation_window": observation_window,
        "usage_coverage_status": item.get("usage_cleanup", {}).get("coverage_status"),
        "cleanup_gate_decisions": {
            "archive": item.get("cleanup_gate_evaluation", {}).get("archive", {}).get("decision"),
            "delete": item.get("cleanup_gate_evaluation", {}).get("delete", {}).get("decision"),
        },
        "report_only": True,
    }


def build_cleanup_candidate_history(cleanup_plan: dict[str, Any], previous: dict[str, Any], now_iso: str | None = None) -> dict[str, Any]:
    now_iso = now_iso or utc_now_iso()
    previous_candidates = previous.get("candidates", {}) if isinstance(previous.get("candidates"), dict) else {}
    current_items = {str(item.get("path")): item for item in cleanup_plan.get("script_review_actions", []) if item.get("path")}
    candidates: dict[str, Any] = {}
    for path, item in sorted(current_items.items()):
        prior = previous_candidates.get(path, {}) if isinstance(previous_candidates.get(path), dict) else {}
        candidates[path] = candidate_history_entry(path, item, prior, now_iso)
    for path, prior in sorted(previous_candidates.items()):
        if path in candidates or not isinstance(prior, dict):
            continue
        retained = dict(prior)
        retained["last_absent_at"] = now_iso
        retained["report_only"] = True
        candidates[path] = retained
    mature_count = sum(1 for item in candidates.values() if item.get("observation_window", {}).get("mature"))
    return {
        "schema_version": "orchestrator-cleanup-candidate-history/v1",
        "updated_at_utc": now_iso,
        "candidate_count": len(candidates),
        "mature_no_use_candidate_count": mature_count,
        "required_no_use_days": 45,
        "required_no_use_observations": 3,
        "candidates": candidates,
        "note": "D3 history is report-only evidence for repeated state, no-use observations, and observation-window maturity; it does not approve archive/delete apply.",
    }


def attach_candidate_history(cleanup_plan: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    candidates = history.get("candidates", {}) if isinstance(history.get("candidates"), dict) else {}
    for item in cleanup_plan.get("script_review_actions", []):
        path = str(item.get("path"))
        entry = candidates.get(path, {}) if isinstance(candidates.get(path), dict) else {}
        item["candidate_history"] = {
            "consecutive_same_state_count": entry.get("consecutive_same_state_count", 0),
            "consecutive_no_use_count": entry.get("consecutive_no_use_count", 0),
            "total_no_use_observation_count": entry.get("total_no_use_observation_count", 0),
            "observation_window": entry.get("observation_window", {}),
        }
    cleanup_plan.setdefault("summary", {})["candidate_history"] = {
        "schema_version": history.get("schema_version"),
        "candidate_count": history.get("candidate_count", 0),
        "mature_no_use_candidate_count": history.get("mature_no_use_candidate_count", 0),
        "required_no_use_days": history.get("required_no_use_days"),
        "required_no_use_observations": history.get("required_no_use_observations"),
        "json_path": maintenance_path(CLEANUP_CANDIDATE_HISTORY_JSON),
        "markdown_path": maintenance_path(CLEANUP_CANDIDATE_HISTORY_MD),
    }
    return cleanup_plan


def render_cleanup_candidate_history_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Cleanup Candidate History", ""]
    lines.append(f"Updated at: `{payload.get('updated_at_utc')}`")
    lines.append(f"Candidate count: **{payload.get('candidate_count', 0)}**")
    lines.append(f"Mature no-use candidates: **{payload.get('mature_no_use_candidate_count', 0)}**")
    lines.append("")
    lines.append("This report is advisory/report-only. It tracks repeated cleanup-plan state, no-use observations, and observation-window maturity.")
    lines.append("")
    lines.append("## Candidates")
    lines.append("")
    ordered = sorted(
        payload.get("candidates", {}).items(),
        key=lambda kv: (-int(kv[1].get("consecutive_no_use_count", 0) or 0), -int(kv[1].get("consecutive_same_state_count", 0) or 0), kv[0]),
    )
    for path, item in ordered:
        window = item.get("observation_window", {}) if isinstance(item.get("observation_window"), dict) else {}
        lines.append(f"- `{path}` — action=`{item.get('last_planned_action')}`; same_state={item.get('consecutive_same_state_count', 0)}; no_use={item.get('consecutive_no_use_count', 0)}; no_use_days={window.get('no_use_days', 0)}; mature={window.get('mature', False)}")
    lines.append("")
    return "\n".join(lines)


def write_cleanup_candidate_history(cleanup_plan: dict[str, Any]) -> dict[str, Any]:
    previous = load_json_if_exists(CLEANUP_CANDIDATE_HISTORY_JSON)
    history = build_cleanup_candidate_history(cleanup_plan, previous)
    CLEANUP_CANDIDATE_HISTORY_JSON.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n")
    CLEANUP_CANDIDATE_HISTORY_MD.write_text(render_cleanup_candidate_history_markdown(history))
    return history


def build_auto_archive_promotion_report(script_actions: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [item.get("autonomous_archive_promotion", {}) for item in script_actions if isinstance(item.get("autonomous_archive_promotion"), dict)]
    eligible = [item for item in candidates if item.get("eligible_for_auto_archive_promotion")]
    blocker_counts: Counter[str] = Counter()
    for item in candidates:
        blocker_counts.update(str(blocker) for blocker in item.get("blockers", []) if blocker)
    return {
        "schema_version": "script-auto-archive-promotion/v1",
        "phase": "H1",
        "mode": "deterministic_evidence",
        "mutating": False,
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "eligible_paths": sorted(str(item.get("path")) for item in eligible),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "candidates": sorted(candidates, key=lambda item: str(item.get("path"))),
        "selection_rule": "Autonomous archive promotion is allowed only when deterministic usage/reference/runtime/operator/scheduler/archive-path checks all pass and no explicit lifecycle status blocks automation.",
    }


def render_auto_archive_promotion_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Auto-Archive Promotion Evidence", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Candidates: **{payload.get('candidate_count', 0)}**")
    lines.append(f"Eligible: **{payload.get('eligible_count', 0)}**")
    lines.append("")
    lines.append("## Eligible paths")
    lines.append("")
    eligible_paths = payload.get("eligible_paths", []) if isinstance(payload.get("eligible_paths"), list) else []
    if eligible_paths:
        for path in eligible_paths:
            lines.append(f"- `{path}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Blocker summary")
    lines.append("")
    blockers = payload.get("blocker_counts", {}) if isinstance(payload.get("blocker_counts"), dict) else {}
    if blockers:
        for blocker, count in blockers.items():
            lines.append(f"- `{blocker}`: {count}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Selection rule")
    lines.append("")
    lines.append(f"- {payload.get('selection_rule')}")
    lines.append("")
    return "\n".join(lines)


def write_auto_archive_promotion_report(script_actions: list[dict[str, Any]]) -> dict[str, Any]:
    payload = build_auto_archive_promotion_report(script_actions)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    AUTO_ARCHIVE_PROMOTION_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    AUTO_ARCHIVE_PROMOTION_MD.write_text(render_auto_archive_promotion_markdown(payload))
    return payload


def script_reference_evidence(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    usage = candidate.get("script_usage") if isinstance(candidate.get("script_usage"), dict) else {}
    evidence = usage.get("reference_evidence") if isinstance(usage.get("reference_evidence"), list) else []
    return [item for item in evidence if isinstance(item, dict)]


def deterministic_archive_promotion_evidence(candidate: dict[str, Any], tracked_paths: set[str]) -> dict[str, Any]:
    path = str(candidate.get("path", ""))
    classification = str(candidate.get("classification", ""))
    usage = script_usage_for_cleanup(candidate)
    usage_blockers = set(usage.get("cleanup_eligibility_blockers", []))
    reference_evidence = script_reference_evidence(candidate)
    reference_sources = {str(item.get("source_kind") or "") for item in reference_evidence}
    parent_callers = candidate.get("script_usage", {}).get("parent_callers", []) if isinstance(candidate.get("script_usage"), dict) else []
    checks: dict[str, bool] = {
        "no_static_inbound_refs": int(candidate.get("inbound_reference_count", 0) or 0) == 0,
        "removal_eligible_class": classification in AUTO_ARCHIVE_ELIGIBLE_CLASSES,
        "usage_summary_available": bool(usage.get("usage_summary_available")),
        "usage_window_clear": bool(usage.get("usage_summary_available")) and not usage_blockers,
        "no_observed_ledger_usage": not bool(usage.get("observed_recently_or_directly")),
        "no_static_or_c4_references": not bool(usage.get("referenced_by_static_or_c4_evidence")),
        "operator_docs_checked": "operator_docs" not in reference_sources and "has_operator_doc_reference" not in usage_blockers,
        "launchd_cron_checked": not ({"has_cron_reference", "has_launchd_reference"} & usage_blockers) and not ({"cron", "launchd", "scheduler"} & reference_sources),
        "external_usage_checked": not reference_evidence and not parent_callers,
        "runtime_state_checked": "has_runtime_log_reference" not in usage_blockers and not bool(usage.get("observed_recently_or_directly")),
        "tracked_by_git": path in tracked_paths,
        "archive_path_defined": False,
        "source_present": False,
    }
    archive_path = None
    try:
        source = safe_repo_relative_path(path)
        archive_path = maintenance_path(SCRIPT_ARCHIVE_ROOT / archive_relative_path(path))
        checks["archive_path_defined"] = bool(path) and source.is_relative_to(REPO_ROOT)
        checks["source_present"] = source.exists() and source.is_file()
    except ValueError:
        checks["archive_path_defined"] = False
    underlying_condition_required = classification in {"manual_repair", "migration_backfill"}
    checks["underlying_condition_resolved_if_needed"] = not underlying_condition_required
    explicit_override = candidate.get("lifecycle_override") if isinstance(candidate.get("lifecycle_override"), dict) else {}
    explicit_status = str(explicit_override.get("lifecycle_status") or "")
    explicit_allows_auto = explicit_status not in {"retain", "do_not_archive", "blocked", "removal_approved", "archived_quarantine"}
    eligible = all(checks.values()) and explicit_allows_auto
    blockers = sorted(key for key, value in checks.items() if not value)
    if not explicit_allows_auto:
        blockers.append(f"explicit_lifecycle_status:{explicit_status}")
    return {
        "schema_version": "script-auto-archive-promotion-evidence/v1",
        "phase": "H1",
        "mode": "deterministic_evidence",
        "path": path,
        "classification": classification,
        "tracked_by_git": path in tracked_paths,
        "archive_path": archive_path,
        "checks": checks,
        "blockers": blockers,
        "eligible_for_auto_archive_promotion": eligible,
        "effective_lifecycle_status": "archive_approved" if eligible else explicit_status,
        "note": "Autonomous promotion requires clear usage evidence, no references, safe class, source presence, and deterministic verification checks; it does not override explicit retain/block/removal/quarantine statuses.",
    }


def merge_autonomous_archive_promotion(override: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    if not evidence.get("eligible_for_auto_archive_promotion"):
        return override
    merged = dict(override) if isinstance(override, dict) else {}
    verification = dict(merged.get("verification", {})) if isinstance(merged.get("verification"), dict) else {}
    verification.update(
        {
            "underlying_condition_resolved": True,
            "operator_docs_checked": True,
            "launchd_cron_checked": True,
            "external_usage_checked": True,
            "runtime_state_checked": True,
            "archive_path_defined": True,
            "autonomous_promotion_evidence": "script-auto-archive-promotion/v1",
        }
    )
    merged.update(
        {
            "lifecycle_status": "archive_approved",
            "owner": merged.get("owner") or "Maintenance automation",
            "rationale": merged.get("rationale") or "Phase H deterministic promotion evidence satisfied all archive checks.",
            "verification": verification,
        }
    )
    return merged


def script_high_confidence_checks(candidate: dict[str, Any], override: dict[str, Any], tracked_paths: set[str]) -> dict[str, Any]:
    path = str(candidate.get("path", ""))
    verification = override.get("verification", {}) if isinstance(override.get("verification", {}), dict) else {}
    lifecycle_status = str(override.get("lifecycle_status", ""))
    classification = str(candidate.get("classification", ""))
    underlying_condition_required = classification in {"manual_repair", "migration_backfill"}
    checks = {
        "no_static_inbound_refs": int(candidate.get("inbound_reference_count", 0) or 0) == 0,
        "removal_eligible_class": classification in AUTO_ARCHIVE_ELIGIBLE_CLASSES,
        "underlying_condition_resolved_if_needed": not underlying_condition_required or bool(verification.get("underlying_condition_resolved")),
        "lifecycle_approved": lifecycle_status in {"archive_approved", "removal_approved"},
        "operator_docs_checked": bool(verification.get("operator_docs_checked")),
        "launchd_cron_checked": bool(verification.get("launchd_cron_checked")),
        "external_usage_checked": bool(verification.get("external_usage_checked")),
        "runtime_state_checked": bool(verification.get("runtime_state_checked")),
        "archive_path_defined": bool(verification.get("archive_path_defined")),
    }
    eligible_for_archive = all(checks.values()) and lifecycle_status == "archive_approved"
    eligible_for_removal = all(checks.values()) and lifecycle_status == "removal_approved" and bool(verification.get("archived_for_one_cycle"))
    failed_checks = [key for key, value in checks.items() if not value]
    if lifecycle_status == "removal_approved" and not verification.get("archived_for_one_cycle"):
        failed_checks.append("archived_for_one_cycle")
    return {
        "checks": checks,
        "failed_checks": failed_checks,
        "eligible_for_archive": eligible_for_archive,
        "eligible_for_removal": eligible_for_removal,
        "confidence_level": "high" if eligible_for_archive or eligible_for_removal else "review",
    }


def archive_relative_path(source_path: str, archived_at_utc: str = "YYYYMMDDTHHMMSSZ") -> str:
    safe = source_path.strip("/").replace("/", "__")
    digest = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:12]
    return f"{archived_at_utc}/{safe}.{digest}"


def archive_restore_command(tombstone_path: str) -> str:
    return f"python3 maintenance/orchestrator-repo-maintenance/run_maintenance.py --restore-archived-script {tombstone_path}"


def build_archive_layout_contract() -> dict[str, Any]:
    sample_source = "scripts/example_retired_helper.py"
    sample_archived_at = "20260518T000000Z"
    sample_archive_relative = archive_relative_path(sample_source, sample_archived_at)
    sample_tombstone = f"{sample_archive_relative}.tombstone.json"
    return {
        "schema_version": "orchestrator-script-archive-layout/v1",
        "phase": "F1",
        "mode": "contract_only",
        "mutating": False,
        "archive_root": maintenance_path(SCRIPT_ARCHIVE_ROOT),
        "archive_root_policy": {
            "root_must_be_inside_maintenance": True,
            "archive_by_utc_run_id": True,
            "preserve_original_relative_path_in_tombstone": True,
            "archive_filename_format": "<repo-relative-path-with-slashes-as-double-underscores>.<source_sha256_12>",
            "tombstone_suffix": ".tombstone.json",
        },
        "tombstone_schema": {
            "schema_version": "orchestrator-script-archive-tombstone/v1",
            "required_fields": [
                "schema_version",
                "archived_at_utc",
                "source_repo_root",
                "source_path",
                "archive_path",
                "source_sha256",
                "source_size_bytes",
                "cleanup_plan_schema_version",
                "cleanup_plan_generated_at_utc",
                "planned_action",
                "reason",
                "usage_cleanup",
                "cleanup_gate_evaluation",
                "restore_command",
            ],
            "hash_algorithm": "sha256",
            "restore_preconditions": [
                "archive_path exists",
                "archive sha256 matches tombstone source_sha256",
                "source_path is absent unless --force restore is explicitly implemented later",
                "parent directory can be created under Orchestrator repo root",
            ],
        },
        "restore_command_format": archive_restore_command("<tombstone-json-path>"),
        "sample": {
            "source_path": sample_source,
            "archive_path": maintenance_path(SCRIPT_ARCHIVE_ROOT / sample_archive_relative),
            "tombstone_path": maintenance_path(SCRIPT_ARCHIVE_ROOT / sample_tombstone),
            "restore_command": archive_restore_command(maintenance_path(SCRIPT_ARCHIVE_ROOT / sample_tombstone)),
        },
        "notes": [
            "F1 defines archive layout only; it does not move, archive, restore, or delete scripts.",
            "F2 may generate archive proposals only for candidates whose report-only gates are fully ready.",
            "F3 apply must write tombstones before moving a script into quarantine/archive.",
        ],
    }


def render_archive_layout_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Archive Layout", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Archive root: `{payload.get('archive_root')}`")
    lines.append("")
    lines.append("## Tombstone required fields")
    lines.append("")
    for field in payload.get("tombstone_schema", {}).get("required_fields", []):
        lines.append(f"- `{field}`")
    lines.append("")
    lines.append("## Restore command format")
    lines.append("")
    lines.append(f"`{payload.get('restore_command_format')}`")
    lines.append("")
    sample = payload.get("sample", {}) if isinstance(payload.get("sample"), dict) else {}
    lines.append("## Sample")
    lines.append("")
    for key in ["source_path", "archive_path", "tombstone_path", "restore_command"]:
        lines.append(f"- `{key}`: `{sample.get(key)}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_archive_layout_contract() -> dict[str, Any]:
    payload = build_archive_layout_contract()
    ARCHIVE_LAYOUT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ARCHIVE_LAYOUT_MD.write_text(render_archive_layout_markdown(payload))
    return payload


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_archive_dry_run(cleanup_plan: dict[str, Any], archive_layout: dict[str, Any], archived_at_utc: str = "DRYRUN") -> dict[str, Any]:
    proposals: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    actions = cleanup_plan.get("script_review_actions", []) if isinstance(cleanup_plan.get("script_review_actions"), list) else []
    for item in actions:
        path = str(item.get("path") or "")
        archive_gate = item.get("cleanup_gate_evaluation", {}).get("archive", {}) if isinstance(item.get("cleanup_gate_evaluation"), dict) else {}
        ready = bool(archive_gate.get("ready"))
        if item.get("planned_action") != "auto_archive_ready" or not ready:
            blockers = archive_gate.get("blockers", []) if isinstance(archive_gate, dict) else []
            blocked.append({
                "path": path,
                "planned_action": item.get("planned_action"),
                "reason": "archive_gate_not_fully_ready",
                "archive_gate_ready": ready,
                "archive_gate_blockers": blockers,
            })
            continue
        try:
            source = safe_repo_relative_path(path)
        except ValueError as exc:
            blocked.append({"path": path, "reason": "unsafe_path", "detail": str(exc), "archive_gate_ready": ready})
            continue
        if not source.exists() or not source.is_file():
            blocked.append({"path": path, "reason": "source_missing_or_not_file", "archive_gate_ready": ready})
            continue
        source_hash = file_sha256(source)
        archive_rel = archive_relative_path(path, archived_at_utc)
        archive_path = SCRIPT_ARCHIVE_ROOT / archive_rel
        tombstone_path = Path(f"{archive_path}.tombstone.json")
        proposals.append({
            "source_path": path,
            "archive_path": maintenance_path(archive_path),
            "tombstone_path": maintenance_path(tombstone_path),
            "source_sha256": source_hash,
            "source_size_bytes": source.stat().st_size,
            "planned_action": item.get("planned_action"),
            "reason": item.get("reason"),
            "cleanup_gate_evaluation": item.get("cleanup_gate_evaluation"),
            "usage_cleanup": item.get("usage_cleanup"),
            "restore_command": archive_restore_command(maintenance_path(tombstone_path)),
        })
    return {
        "schema_version": "orchestrator-script-archive-dry-run/v1",
        "phase": "F2",
        "mode": "dry_run_only",
        "mutating": False,
        "archive_layout_schema_version": archive_layout.get("schema_version"),
        "archive_root": archive_layout.get("archive_root"),
        "proposal_count": len(proposals),
        "blocked_count": len(blocked),
        "proposals": proposals,
        "blocked": blocked,
        "selection_rule": "Propose only script candidates with planned_action=auto_archive_ready and cleanup_gate_evaluation.archive.ready=true.",
        "notes": [
            "F2 is non-mutating and does not create archive directories, tombstones, or moves.",
            "F3 may apply at most one low-risk proposal after revalidating source hash and gates at runtime.",
        ],
    }


def render_archive_dry_run_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Archive Dry Run", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Proposal count: **{payload.get('proposal_count', 0)}**")
    lines.append(f"Blocked count: **{payload.get('blocked_count', 0)}**")
    lines.append("")
    lines.append("## Proposals")
    lines.append("")
    proposals = payload.get("proposals", []) if isinstance(payload.get("proposals"), list) else []
    if proposals:
        for item in proposals:
            lines.append(f"- `{item.get('source_path')}` -> `{item.get('archive_path')}`; restore=`{item.get('restore_command')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Blocked summary")
    lines.append("")
    blocked = payload.get("blocked", []) if isinstance(payload.get("blocked"), list) else []
    counts = Counter(item.get("reason") for item in blocked)
    if counts:
        for reason, count in sorted(counts.items()):
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Selection rule")
    lines.append("")
    lines.append(f"- {payload.get('selection_rule')}")
    lines.append("")
    return "\n".join(lines)


def write_archive_dry_run(cleanup_plan: dict[str, Any], archive_layout: dict[str, Any]) -> dict[str, Any]:
    payload = build_archive_dry_run(cleanup_plan, archive_layout, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ARCHIVE_DRY_RUN_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ARCHIVE_DRY_RUN_MD.write_text(render_archive_dry_run_markdown(payload))
    return payload


def archive_apply_tombstone(proposal: dict[str, Any], source_hash: str, archived_at_utc: str) -> dict[str, Any]:
    return {
        "schema_version": "orchestrator-script-archive-tombstone/v1",
        "archived_at_utc": archived_at_utc,
        "source_repo_root": str(REPO_ROOT),
        "source_path": proposal.get("source_path"),
        "archive_path": proposal.get("archive_path"),
        "source_sha256": source_hash,
        "source_size_bytes": proposal.get("source_size_bytes"),
        "cleanup_plan_schema_version": "orchestrator-cleanup-plan/v2",
        "cleanup_plan_generated_at_utc": load_json_if_exists(CLEANUP_PLAN_JSON).get("generated_at_utc"),
        "planned_action": proposal.get("planned_action"),
        "reason": proposal.get("reason"),
        "usage_cleanup": proposal.get("usage_cleanup"),
        "cleanup_gate_evaluation": proposal.get("cleanup_gate_evaluation"),
        "restore_command": proposal.get("restore_command"),
        "restore_preconditions": [
            "archive_path exists",
            "archive sha256 matches tombstone source_sha256",
            "source_path is absent unless future force restore is explicitly used",
        ],
    }


def select_archive_apply_proposal(dry_run: dict[str, Any], source_path: str | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    proposals = dry_run.get("proposals", []) if isinstance(dry_run.get("proposals"), list) else []
    if source_path:
        matches = [item for item in proposals if item.get("source_path") == source_path]
        if not matches:
            return None, [{"path": source_path, "reason": "requested_source_path_not_in_ready_proposals"}]
        if len(matches) > 1:
            return None, [{"path": source_path, "reason": "multiple_matching_ready_proposals"}]
        return matches[0], []
    if len(proposals) == 1:
        return proposals[0], []
    if not proposals:
        return None, [{"reason": "no_ready_archive_proposals"}]
    return None, [{"reason": "multiple_ready_proposals_require_explicit_source_path", "ready_proposal_count": len(proposals)}]


def build_script_archive_apply_result(dry_run: dict[str, Any], *, apply: bool, source_path: str | None = None) -> dict[str, Any]:
    archived_at_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    proposal, selection_skips = select_archive_apply_proposal(dry_run, source_path)
    archived: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = list(selection_skips)
    if proposal is not None:
        path = str(proposal.get("source_path") or "")
        try:
            source = safe_repo_relative_path(path)
        except ValueError as exc:
            skipped.append({"path": path, "reason": "unsafe_path", "detail": str(exc)})
        else:
            archive_path = MAINTENANCE_DIR.parent / str(proposal.get("archive_path"))
            tombstone_path = MAINTENANCE_DIR.parent / str(proposal.get("tombstone_path"))
            if not str(archive_path.resolve()).startswith(str(SCRIPT_ARCHIVE_ROOT.resolve())):
                skipped.append({"path": path, "reason": "archive_path_outside_archive_root"})
            elif not source.exists() or not source.is_file():
                skipped.append({"path": path, "reason": "source_missing_or_not_file"})
            else:
                current_hash = file_sha256(source)
                expected_hash = proposal.get("source_sha256")
                if current_hash != expected_hash:
                    skipped.append({"path": path, "reason": "source_hash_changed", "expected_sha256": expected_hash, "current_sha256": current_hash})
                elif archive_path.exists() or tombstone_path.exists():
                    skipped.append({"path": path, "reason": "archive_or_tombstone_already_exists"})
                else:
                    tombstone = archive_apply_tombstone(proposal, current_hash, archived_at_utc)
                    if apply:
                        tombstone_path.parent.mkdir(parents=True, exist_ok=True)
                        archive_path.parent.mkdir(parents=True, exist_ok=True)
                        tombstone_path.write_text(json.dumps(tombstone, indent=2, sort_keys=True) + "\n")
                        shutil.move(str(source), str(archive_path))
                    archived.append({
                        "source_path": path,
                        "archive_path": maintenance_path(archive_path),
                        "tombstone_path": maintenance_path(tombstone_path),
                        "source_sha256": current_hash,
                        "restore_command": proposal.get("restore_command"),
                    })
    return {
        "schema_version": "orchestrator-script-archive-apply-result/v1",
        "phase": "F3",
        "mode": "single_candidate_apply" if apply else "single_candidate_dry_run",
        "mutating": bool(apply and archived),
        "requested_source_path": source_path,
        "ready_proposal_count": len(dry_run.get("proposals", [])) if isinstance(dry_run.get("proposals"), list) else 0,
        "archived_count": len(archived) if apply else 0,
        "would_archive_count": len(archived) if not apply else 0,
        "skipped_count": len(skipped),
        "archived": archived if apply else [],
        "would_archive": archived if not apply else [],
        "skipped": skipped,
        "guardrails": [
            "Apply at most one ready archive proposal per run.",
            "Ready proposals require planned_action=auto_archive_ready and archive gate ready=true.",
            "Write tombstone before moving source file.",
            "Verify source SHA-256 immediately before moving.",
        ],
    }


def render_script_archive_apply_result_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Archive Apply Result", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Ready proposals: **{payload.get('ready_proposal_count', 0)}**")
    lines.append(f"Archived: **{payload.get('archived_count', 0)}**")
    lines.append(f"Would archive: **{payload.get('would_archive_count', 0)}**")
    lines.append(f"Skipped: **{payload.get('skipped_count', 0)}**")
    lines.append("")
    lines.append("## Archived / would archive")
    lines.append("")
    items = payload.get("archived") or payload.get("would_archive") or []
    if items:
        for item in items:
            lines.append(f"- `{item.get('source_path')}` -> `{item.get('archive_path')}`; tombstone=`{item.get('tombstone_path')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Skipped")
    lines.append("")
    skipped = payload.get("skipped", []) if isinstance(payload.get("skipped"), list) else []
    if skipped:
        for item in skipped:
            path = f" `{item.get('path')}`" if item.get("path") else ""
            lines.append(f"-{path} — `{item.get('reason')}`")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def write_script_archive_apply_result(payload: dict[str, Any]) -> dict[str, Any]:
    ARCHIVE_APPLY_RESULT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    ARCHIVE_APPLY_RESULT_MD.write_text(render_script_archive_apply_result_markdown(payload))
    return payload


def py_compile_check(paths: list[Path]) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, "-m", "py_compile", *[str(path) for path in paths]], cwd=str(MAINTENANCE_DIR.parent), text=True, capture_output=True)
    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1000:],
        "stderr_tail": proc.stderr[-1000:],
        "path_count": len(paths),
    }


def archived_touched_surface_checks(archive_apply_result: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    archived = archive_apply_result.get("archived", []) if isinstance(archive_apply_result.get("archived"), list) else []
    if not archived:
        return [{"name": "touched_surface_smoke", "status": "ok", "detail": "no archived paths in latest archive apply result"}]
    for item in archived:
        source_path = str(item.get("source_path") or "")
        archive_path = MAINTENANCE_DIR.parent / str(item.get("archive_path"))
        tombstone_path = MAINTENANCE_DIR.parent / str(item.get("tombstone_path"))
        try:
            source = safe_repo_relative_path(source_path)
        except ValueError as exc:
            checks.append({"name": "archived_path_safe", "status": "error", "detail": str(exc), "path": source_path})
            continue
        if source.exists():
            checks.append({"name": "source_removed_after_archive", "status": "error", "detail": "source path still exists", "path": source_path})
        else:
            checks.append({"name": "source_removed_after_archive", "status": "ok", "detail": "source path absent", "path": source_path})
        if not archive_path.exists() or not archive_path.is_file():
            checks.append({"name": "archive_file_exists", "status": "error", "detail": "archive path missing or not file", "path": maintenance_path(archive_path)})
            continue
        checks.append({"name": "archive_file_exists", "status": "ok", "detail": "archive file present", "path": maintenance_path(archive_path)})
        if not tombstone_path.exists() or not tombstone_path.is_file():
            checks.append({"name": "tombstone_exists", "status": "error", "detail": "tombstone missing or not file", "path": maintenance_path(tombstone_path)})
            continue
        tombstone = load_json_if_exists(tombstone_path)
        expected_hash = tombstone.get("source_sha256")
        current_hash = file_sha256(archive_path)
        if current_hash == expected_hash:
            checks.append({"name": "archive_hash_matches_tombstone", "status": "ok", "detail": current_hash, "path": maintenance_path(archive_path)})
        else:
            checks.append({"name": "archive_hash_matches_tombstone", "status": "error", "detail": f"expected={expected_hash} current={current_hash}", "path": maintenance_path(archive_path)})
        if archive_path.suffix == ".py":
            compile_result = py_compile_check([archive_path])
            checks.append({
                "name": "archived_python_py_compile",
                "status": "ok" if compile_result["returncode"] == 0 else "error",
                "detail": f"returncode={compile_result['returncode']}",
                "path": maintenance_path(archive_path),
            })
    return checks


def build_post_archive_smoke_result(archive_apply_result: dict[str, Any]) -> dict[str, Any]:
    compile_paths = [Path(__file__).resolve(), SCRIPT_CLASSIFIER, SCRIPT_USAGE_MATERIALIZER]
    package_compile = py_compile_check(compile_paths)
    self_check = run_maintenance_self_check()
    self_payload = self_check.get("payload", {}) if isinstance(self_check.get("payload"), dict) else {}
    classification = load_json_if_exists(SCRIPT_CLASSIFICATION_JSON)
    cleanup_plan = load_json_if_exists(CLEANUP_PLAN_JSON)
    checks = [
        {
            "name": "maintenance_package_py_compile",
            "status": "ok" if package_compile.get("returncode") == 0 else "error",
            "detail": f"returncode={package_compile.get('returncode')} path_count={package_compile.get('path_count')}",
        },
        {
            "name": "classifier_refresh_output",
            "status": "ok" if classification.get("schema_version") == "orchestrator-script-classification/v1" and int((classification.get("summary") or {}).get("script_count", 0) or 0) > 0 else "error",
            "detail": f"schema={classification.get('schema_version')} script_count={(classification.get('summary') or {}).get('script_count')}",
        },
        {
            "name": "cleanup_plan_refresh_output",
            "status": "ok" if cleanup_plan.get("schema_version") == "orchestrator-cleanup-plan/v2" else "error",
            "detail": f"schema={cleanup_plan.get('schema_version')}",
        },
        {
            "name": "maintenance_self_check",
            "status": "ok" if self_check.get("returncode") == 0 and self_payload.get("overall_status") != "error" else "error",
            "detail": f"overall={self_payload.get('overall_status')} returncode={self_check.get('returncode')}",
        },
    ]
    checks.extend(archived_touched_surface_checks(archive_apply_result))
    statuses = {item.get("status") for item in checks}
    return {
        "schema_version": "orchestrator-post-archive-smoke/v1",
        "phase": "F4",
        "mode": "post_archive_smoke",
        "mutating": False,
        "ok": "error" not in statuses,
        "checks": checks,
        "archive_apply_summary": {
            "schema_version": archive_apply_result.get("schema_version"),
            "mode": archive_apply_result.get("mode"),
            "mutating": archive_apply_result.get("mutating"),
            "ready_proposal_count": archive_apply_result.get("ready_proposal_count"),
            "archived_count": archive_apply_result.get("archived_count", 0),
            "skipped_count": archive_apply_result.get("skipped_count", 0),
            "json_path": maintenance_path(ARCHIVE_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(ARCHIVE_APPLY_RESULT_MD),
        },
        "self_check": {
            "overall_status": self_payload.get("overall_status"),
            "summary": self_payload.get("summary", {}),
            "json_path": maintenance_path(MAINTENANCE_SELF_CHECK_JSON),
            "markdown_path": maintenance_path(MAINTENANCE_SELF_CHECK_MD),
        },
        "note": "F4 verifies package/import health, refreshed classifier/cleanup outputs, maintenance self-check, and archived touched surfaces. If no script was archived, touched-surface smoke passes as an explicit no-op.",
    }


def render_post_archive_smoke_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Post-Archive Smoke", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"OK: **{payload.get('ok', False)}**")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for item in payload.get("checks", []):
        path = f" path=`{item.get('path')}`" if item.get("path") else ""
        lines.append(f"- **{item.get('status')}** `{item.get('name')}` — {item.get('detail')}{path}")
    lines.append("")
    archive_summary = payload.get("archive_apply_summary", {}) if isinstance(payload.get("archive_apply_summary"), dict) else {}
    lines.append("## Archive apply summary")
    lines.append("")
    for key in ["mode", "mutating", "ready_proposal_count", "archived_count", "skipped_count"]:
        lines.append(f"- `{key}`: `{archive_summary.get(key)}`")
    lines.append("")
    return "\n".join(lines)


def write_post_archive_smoke_result(payload: dict[str, Any]) -> dict[str, Any]:
    POST_ARCHIVE_SMOKE_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    POST_ARCHIVE_SMOKE_MD.write_text(render_post_archive_smoke_markdown(payload))
    return payload


def archive_abs_path_from_maintenance_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path.resolve()
    return (MAINTENANCE_DIR.parent / path).resolve()


def restore_archived_script(tombstone_path_text: str) -> dict[str, Any]:
    tombstone_path = archive_abs_path_from_maintenance_path(tombstone_path_text)
    if not tombstone_path.exists() or not tombstone_path.is_file():
        return {"ok": False, "reason": "tombstone_missing_or_not_file", "tombstone_path": maintenance_path(tombstone_path)}
    tombstone = load_json_if_exists(tombstone_path)
    source_path = str(tombstone.get("source_path") or "")
    archive_path_text = str(tombstone.get("archive_path") or "")
    if tombstone.get("schema_version") != "orchestrator-script-archive-tombstone/v1":
        return {"ok": False, "reason": "invalid_tombstone_schema", "tombstone_path": maintenance_path(tombstone_path)}
    try:
        source = safe_repo_relative_path(source_path)
    except ValueError as exc:
        return {"ok": False, "reason": "unsafe_source_path", "detail": str(exc), "tombstone_path": maintenance_path(tombstone_path)}
    archive_path = archive_abs_path_from_maintenance_path(archive_path_text)
    if not str(archive_path).startswith(str(SCRIPT_ARCHIVE_ROOT.resolve())):
        return {"ok": False, "reason": "archive_path_outside_archive_root", "archive_path": str(archive_path)}
    if source.exists():
        return {"ok": False, "reason": "source_already_exists", "source_path": source_path}
    if not archive_path.exists() or not archive_path.is_file():
        return {"ok": False, "reason": "archive_missing_or_not_file", "archive_path": maintenance_path(archive_path)}
    current_hash = file_sha256(archive_path)
    expected_hash = tombstone.get("source_sha256")
    if current_hash != expected_hash:
        return {"ok": False, "reason": "archive_hash_mismatch", "expected_sha256": expected_hash, "current_sha256": current_hash}
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(archive_path), str(source))
    return {
        "ok": True,
        "reason": "restored",
        "source_path": source_path,
        "archive_path": maintenance_path(archive_path),
        "tombstone_path": maintenance_path(tombstone_path),
        "source_sha256": current_hash,
    }


def quarantine_restore_command(tombstone_path: Path | str) -> str:
    return archive_restore_command(maintenance_path(tombstone_path) if isinstance(tombstone_path, Path) else str(tombstone_path))


def discover_archive_tombstones() -> list[Path]:
    if not SCRIPT_ARCHIVE_ROOT.exists():
        return []
    return sorted(SCRIPT_ARCHIVE_ROOT.rglob("*.tombstone.json"))


def prior_quarantine_records(previous_monitor: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = previous_monitor.get("records", []) if isinstance(previous_monitor.get("records"), list) else []
    return {str(item.get("source_path")): item for item in records if isinstance(item, dict) and item.get("source_path")}


def monitor_record_for_tombstone(tombstone_path: Path, previous: dict[str, dict[str, Any]], post_archive_smoke: dict[str, Any]) -> dict[str, Any]:
    tombstone = load_json_if_exists(tombstone_path)
    source_path = str(tombstone.get("source_path") or "")
    archive_path = archive_abs_path_from_maintenance_path(str(tombstone.get("archive_path") or ""))
    blockers: list[str] = []
    checks: list[dict[str, Any]] = []
    if tombstone.get("schema_version") != "orchestrator-script-archive-tombstone/v1":
        blockers.append("invalid_tombstone_schema")
    try:
        source = safe_repo_relative_path(source_path)
    except ValueError as exc:
        source = None
        blockers.append("unsafe_source_path")
        checks.append({"name": "source_path_safe", "status": "error", "detail": str(exc)})
    if not str(archive_path).startswith(str(SCRIPT_ARCHIVE_ROOT.resolve())):
        blockers.append("archive_path_outside_archive_root")
    if source is not None and source.exists():
        blockers.append("source_path_already_restored_or_recreated")
    if not archive_path.exists() or not archive_path.is_file():
        blockers.append("archive_missing_or_not_file")
    else:
        expected_hash = tombstone.get("source_sha256")
        current_hash = file_sha256(archive_path)
        if current_hash != expected_hash:
            blockers.append("archive_hash_mismatch")
        checks.append({"name": "archive_hash", "status": "ok" if current_hash == expected_hash else "error", "detail": f"expected={expected_hash} current={current_hash}"})
    smoke_ok = post_archive_smoke.get("ok") if isinstance(post_archive_smoke, dict) else None
    if smoke_ok is False:
        blockers.append("post_archive_smoke_failed")
    previous_record = previous.get(source_path, {})
    previous_clean = int(previous_record.get("clean_cycle_count", 0) or 0)
    clean = not blockers
    clean_cycle_count = previous_clean + 1 if clean else 0
    restore_required = "post_archive_smoke_failed" in blockers or "source_path_already_restored_or_recreated" in blockers
    restore_blocked = any(item in blockers for item in ["invalid_tombstone_schema", "unsafe_source_path", "archive_path_outside_archive_root", "archive_missing_or_not_file", "archive_hash_mismatch"])
    return {
        "source_path": source_path,
        "archive_path": maintenance_path(archive_path),
        "tombstone_path": maintenance_path(tombstone_path),
        "archived_at_utc": tombstone.get("archived_at_utc"),
        "clean": clean,
        "clean_cycle_count": clean_cycle_count,
        "restore_required": restore_required,
        "restore_blocked": restore_blocked,
        "restore_command": quarantine_restore_command(tombstone_path),
        "blockers": sorted(set(blockers)),
        "checks": checks,
    }


def build_quarantine_monitor_result(previous_monitor: dict[str, Any], post_archive_smoke: dict[str, Any]) -> dict[str, Any]:
    previous = prior_quarantine_records(previous_monitor)
    tombstones = discover_archive_tombstones()
    records = [monitor_record_for_tombstone(path, previous, post_archive_smoke) for path in tombstones]
    restore_required = [item for item in records if item.get("restore_required")]
    restore_blocked = [item for item in records if item.get("restore_blocked")]
    clean_records = [item for item in records if item.get("clean")]
    return {
        "schema_version": "orchestrator-script-quarantine-monitor/v1",
        "phase": "F5",
        "mode": "quarantine_monitor",
        "mutating": False,
        "ok": not restore_required and not restore_blocked,
        "archive_root": maintenance_path(SCRIPT_ARCHIVE_ROOT),
        "archived_script_count": len(records),
        "clean_quarantine_count": len(clean_records),
        "restore_required_count": len(restore_required),
        "restore_blocked_count": len(restore_blocked),
        "records": records,
        "notes": [
            "F5 is non-mutating monitoring; explicit restore uses --restore-archived-script <tombstone-json-path>.",
            "Clean cycle counts increment only while tombstone, archive hash, source absence, and post-archive smoke remain healthy.",
            "G-phase deletion readiness must depend on multiple clean quarantine cycles, not a single archive event.",
        ],
    }


def render_quarantine_monitor_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Quarantine Monitor", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"OK: **{payload.get('ok', False)}**")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Archived scripts: **{payload.get('archived_script_count', 0)}**")
    lines.append(f"Clean quarantine: **{payload.get('clean_quarantine_count', 0)}**")
    lines.append(f"Restore required: **{payload.get('restore_required_count', 0)}**")
    lines.append(f"Restore blocked: **{payload.get('restore_blocked_count', 0)}**")
    lines.append("")
    lines.append("## Records")
    lines.append("")
    records = payload.get("records", []) if isinstance(payload.get("records"), list) else []
    if records:
        for item in records:
            lines.append(f"- `{item.get('source_path')}` clean={item.get('clean')} clean_cycles={item.get('clean_cycle_count')} restore_required={item.get('restore_required')} blockers={item.get('blockers', [])}")
    else:
        lines.append("_No archived scripts currently under quarantine._")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_quarantine_monitor_result(payload: dict[str, Any]) -> dict[str, Any]:
    QUARANTINE_MONITOR_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    QUARANTINE_MONITOR_MD.write_text(render_quarantine_monitor_markdown(payload))
    return payload


def delete_readiness_record(record: dict[str, Any], required_clean_cycles: int = DELETE_READINESS_REQUIRED_CLEAN_CYCLES) -> dict[str, Any]:
    blockers: list[str] = []
    if not record.get("source_path"):
        blockers.append("missing_source_path")
    if not record.get("archive_path"):
        blockers.append("missing_archive_path")
    if not record.get("tombstone_path"):
        blockers.append("missing_tombstone_path")
    if not record.get("clean"):
        blockers.append("quarantine_not_clean")
    clean_cycle_count = int(record.get("clean_cycle_count", 0) or 0)
    if clean_cycle_count < required_clean_cycles:
        blockers.append("insufficient_clean_quarantine_cycles")
    if record.get("restore_required"):
        blockers.append("restore_required")
    if record.get("restore_blocked"):
        blockers.append("restore_blocked")
    for blocker in record.get("blockers", []) if isinstance(record.get("blockers"), list) else []:
        blockers.append(f"quarantine:{blocker}")
    ready = not blockers
    return {
        "source_path": record.get("source_path"),
        "archive_path": record.get("archive_path"),
        "tombstone_path": record.get("tombstone_path"),
        "archived_at_utc": record.get("archived_at_utc"),
        "planned_action": "auto_delete_ready" if ready else "archived_quarantine",
        "delete_ready": ready,
        "clean_cycle_count": clean_cycle_count,
        "required_clean_cycles": required_clean_cycles,
        "blockers": sorted(set(blockers)),
        "restore_command": record.get("restore_command"),
    }


def build_delete_readiness_result(quarantine_monitor: dict[str, Any], required_clean_cycles: int = DELETE_READINESS_REQUIRED_CLEAN_CYCLES) -> dict[str, Any]:
    records = quarantine_monitor.get("records", []) if isinstance(quarantine_monitor.get("records"), list) else []
    readiness = [delete_readiness_record(item, required_clean_cycles) for item in records if isinstance(item, dict)]
    ready = [item for item in readiness if item.get("delete_ready")]
    blocked = [item for item in readiness if not item.get("delete_ready")]
    blocker_counts = Counter(blocker for item in blocked for blocker in item.get("blockers", []))
    return {
        "schema_version": "orchestrator-script-delete-readiness/v1",
        "phase": "G1",
        "mode": "report_only",
        "mutating": False,
        "required_clean_cycles": required_clean_cycles,
        "archived_script_count": len(readiness),
        "auto_delete_ready_count": len(ready),
        "blocked_count": len(blocked),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "records": readiness,
        "notes": [
            "G1 is report-only and cannot delete files.",
            "Only archived/quarantined scripts from the F5 quarantine monitor can become auto_delete_ready.",
            "Delete readiness requires multiple clean quarantine cycles and no restore-required or restore-blocked state.",
        ],
    }


def render_delete_readiness_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Delete Readiness", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Required clean cycles: **{payload.get('required_clean_cycles')}**")
    lines.append(f"Archived scripts: **{payload.get('archived_script_count', 0)}**")
    lines.append(f"Auto-delete ready: **{payload.get('auto_delete_ready_count', 0)}**")
    lines.append(f"Blocked: **{payload.get('blocked_count', 0)}**")
    lines.append("")
    lines.append("## Blockers")
    lines.append("")
    blocker_counts = payload.get("blocker_counts", {}) if isinstance(payload.get("blocker_counts"), dict) else {}
    if blocker_counts:
        for blocker, count in blocker_counts.items():
            lines.append(f"- `{blocker}`: {count}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Records")
    lines.append("")
    records = payload.get("records", []) if isinstance(payload.get("records"), list) else []
    if records:
        for item in records:
            lines.append(f"- `{item.get('source_path')}` — `{item.get('planned_action')}`; clean_cycles={item.get('clean_cycle_count')}; blockers={item.get('blockers', [])}")
    else:
        lines.append("_No archived/quarantined scripts to evaluate._")
    lines.append("")
    return "\n".join(lines)


def write_delete_readiness_result(payload: dict[str, Any]) -> dict[str, Any]:
    DELETE_READINESS_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    DELETE_READINESS_MD.write_text(render_delete_readiness_markdown(payload))
    return payload


def build_delete_dry_run_result(delete_readiness: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = delete_readiness.get("records", []) if isinstance(delete_readiness.get("records"), list) else []
    operations: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in records:
        if item.get("delete_ready") and item.get("planned_action") == "auto_delete_ready":
            operations.append(
                {
                    "source_path": item.get("source_path"),
                    "archive_path": item.get("archive_path"),
                    "tombstone_path": item.get("tombstone_path"),
                    "dry_run_action": "would_delete_archived_script_and_tombstone",
                    "required_preflight": [
                        "fresh_delete_readiness_report",
                        "archive_path_exists_inside_archive_root",
                        "tombstone_schema_valid",
                        "archive_hash_matches_tombstone",
                        "source_path_absent",
                        "post_delete_verification_available",
                    ],
                    "restore_command": item.get("restore_command"),
                    "clean_cycle_count": item.get("clean_cycle_count"),
                    "required_clean_cycles": item.get("required_clean_cycles"),
                }
            )
        else:
            excluded.append(
                {
                    "source_path": item.get("source_path"),
                    "archive_path": item.get("archive_path"),
                    "tombstone_path": item.get("tombstone_path"),
                    "planned_action": item.get("planned_action"),
                    "delete_ready": bool(item.get("delete_ready")),
                    "blockers": item.get("blockers", []),
                    "exclude_reason": "not_auto_delete_ready",
                }
            )
    return {
        "schema_version": "orchestrator-script-delete-dry-run/v1",
        "phase": "G2",
        "mode": "monthly_dry_run_only",
        "mutating": False,
        "generated_at_utc": generated_at,
        "evidence_period": generated_at[:7],
        "delete_readiness_schema_version": delete_readiness.get("schema_version"),
        "operation_count": len(operations),
        "excluded_count": len(excluded),
        "operation_counts": dict(sorted(Counter(op["dry_run_action"] for op in operations).items())),
        "operations": operations,
        "excluded": excluded,
        "notes": [
            "G2 is a non-mutating monthly dry-run report; it cannot delete files.",
            "Operations are emitted only for G1 auto_delete_ready archived/quarantined scripts.",
            "G3/G4 must revalidate every preflight at runtime before any deletion can occur.",
        ],
    }


def render_delete_dry_run_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Delete Dry Run", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Evidence period: `{payload.get('evidence_period')}`")
    lines.append(f"Operations: **{payload.get('operation_count', 0)}**")
    lines.append(f"Excluded: **{payload.get('excluded_count', 0)}**")
    lines.append("")
    lines.append("## Operations")
    lines.append("")
    operations = payload.get("operations", []) if isinstance(payload.get("operations"), list) else []
    if operations:
        for item in operations:
            lines.append(f"- `{item.get('source_path')}` — `{item.get('dry_run_action')}`; archive=`{item.get('archive_path')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Excluded")
    lines.append("")
    excluded = payload.get("excluded", []) if isinstance(payload.get("excluded"), list) else []
    if excluded:
        for item in excluded:
            lines.append(f"- `{item.get('source_path')}` — `{item.get('exclude_reason')}`; blockers={item.get('blockers', [])}")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def write_delete_dry_run_result(payload: dict[str, Any]) -> dict[str, Any]:
    DELETE_DRY_RUN_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    DELETE_DRY_RUN_MD.write_text(render_delete_dry_run_markdown(payload))
    return payload


def select_delete_apply_operation(dry_run: dict[str, Any], source_path: str | None = None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    operations = dry_run.get("operations", []) if isinstance(dry_run.get("operations"), list) else []
    if source_path:
        matches = [item for item in operations if item.get("source_path") == source_path]
        if not matches:
            return None, [{"path": source_path, "reason": "requested_source_path_not_in_ready_delete_operations"}]
        if len(matches) > 1:
            return None, [{"path": source_path, "reason": "multiple_matching_ready_delete_operations"}]
        return matches[0], []
    if len(operations) == 1:
        return operations[0], []
    if not operations:
        return None, [{"reason": "no_ready_delete_operations"}]
    return None, [{"reason": "multiple_ready_delete_operations_require_explicit_source_path", "ready_operation_count": len(operations)}]


def validate_delete_apply_operation(operation: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    source_path = str(operation.get("source_path") or "")
    archive_path_text = str(operation.get("archive_path") or "")
    tombstone_path_text = str(operation.get("tombstone_path") or "")
    blockers: list[dict[str, Any]] = []
    try:
        source = safe_repo_relative_path(source_path)
    except ValueError as exc:
        source = None
        blockers.append({"path": source_path, "reason": "unsafe_source_path", "detail": str(exc)})
    archive_path = archive_abs_path_from_maintenance_path(archive_path_text)
    tombstone_path = archive_abs_path_from_maintenance_path(tombstone_path_text)
    try:
        archive_root = SCRIPT_ARCHIVE_ROOT.resolve()
        archive_resolved = archive_path.resolve()
        tombstone_resolved = tombstone_path.resolve()
    except OSError as exc:
        blockers.append({"path": archive_path_text, "reason": "archive_path_resolution_failed", "detail": str(exc)})
        archive_root = SCRIPT_ARCHIVE_ROOT.resolve()
        archive_resolved = archive_path
        tombstone_resolved = tombstone_path
    if not str(archive_resolved).startswith(str(archive_root)):
        blockers.append({"path": archive_path_text, "reason": "archive_path_outside_archive_root"})
    if not str(tombstone_resolved).startswith(str(archive_root)):
        blockers.append({"path": tombstone_path_text, "reason": "tombstone_path_outside_archive_root"})
    if tombstone_path.name != f"{archive_path.name}.tombstone.json":
        blockers.append({"path": tombstone_path_text, "reason": "tombstone_not_paired_with_archive_path"})
    if source is not None and source.exists():
        blockers.append({"path": source_path, "reason": "source_path_present_restore_or_recreate_detected"})
    if not archive_path.exists() or not archive_path.is_file():
        blockers.append({"path": archive_path_text, "reason": "archive_missing_or_not_file"})
    if not tombstone_path.exists() or not tombstone_path.is_file():
        blockers.append({"path": tombstone_path_text, "reason": "tombstone_missing_or_not_file"})
    tombstone = load_json_if_exists(tombstone_path) if tombstone_path.exists() and tombstone_path.is_file() else {}
    if tombstone.get("schema_version") != "orchestrator-script-archive-tombstone/v1":
        blockers.append({"path": tombstone_path_text, "reason": "invalid_tombstone_schema", "schema_version": tombstone.get("schema_version")})
    if tombstone.get("source_path") != source_path:
        blockers.append({"path": tombstone_path_text, "reason": "tombstone_source_path_mismatch", "expected": source_path, "actual": tombstone.get("source_path")})
    if tombstone.get("archive_path") != archive_path_text:
        blockers.append({"path": tombstone_path_text, "reason": "tombstone_archive_path_mismatch", "expected": archive_path_text, "actual": tombstone.get("archive_path")})
    if archive_path.exists() and archive_path.is_file():
        current_hash = file_sha256(archive_path)
        expected_hash = tombstone.get("source_sha256")
        if current_hash != expected_hash:
            blockers.append({"path": archive_path_text, "reason": "archive_hash_mismatch", "expected_sha256": expected_hash, "current_sha256": current_hash})
    else:
        current_hash = None
    if blockers:
        return None, blockers
    return {
        "source_path": source_path,
        "archive_path": maintenance_path(archive_path),
        "tombstone_path": maintenance_path(tombstone_path),
        "source_sha256": current_hash,
        "archive_size_bytes": archive_path.stat().st_size,
    }, []


def build_script_delete_apply_result(dry_run: dict[str, Any], *, apply: bool, source_path: str | None = None) -> dict[str, Any]:
    operation, selection_skips = select_delete_apply_operation(dry_run, source_path)
    deleted: list[dict[str, Any]] = []
    would_delete: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = list(selection_skips)
    if operation is not None:
        validated, blockers = validate_delete_apply_operation(operation)
        if blockers:
            skipped.extend(blockers)
        elif validated is not None:
            archive_path = archive_abs_path_from_maintenance_path(validated["archive_path"])
            tombstone_path = archive_abs_path_from_maintenance_path(validated["tombstone_path"])
            record = {
                **validated,
                "deleted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if apply else None,
                "restore_available": False,
            }
            if apply:
                archive_path.unlink()
                tombstone_path.unlink()
                deleted.append(record)
            else:
                would_delete.append(record)
    ready_count = len(dry_run.get("operations", [])) if isinstance(dry_run.get("operations"), list) else 0
    return {
        "schema_version": "orchestrator-script-delete-apply-result/v1",
        "phase": "G4",
        "mode": "single_candidate_apply" if apply else "single_candidate_dry_run",
        "mutating": bool(apply and deleted),
        "requested_source_path": source_path,
        "ready_operation_count": ready_count,
        "deleted_count": len(deleted) if apply else 0,
        "would_delete_count": len(would_delete) if not apply else 0,
        "skipped_count": len(skipped),
        "deleted": deleted,
        "would_delete": would_delete,
        "skipped": skipped,
        "guardrails": [
            "Apply at most one ready delete operation per run.",
            "Ready operations must come from current G2 monthly dry-run evidence.",
            "Revalidate archive root containment, tombstone schema, source absence, and archive SHA-256 immediately before deletion.",
            "Delete only archived script artifact and paired tombstone; never delete a live source path.",
        ],
    }


def render_script_delete_apply_result_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Script Delete Apply Result", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Ready operations: **{payload.get('ready_operation_count', 0)}**")
    lines.append(f"Deleted: **{payload.get('deleted_count', 0)}**")
    lines.append(f"Would delete: **{payload.get('would_delete_count', 0)}**")
    lines.append(f"Skipped: **{payload.get('skipped_count', 0)}**")
    lines.append("")
    lines.append("## Deleted / would delete")
    lines.append("")
    items = payload.get("deleted") or payload.get("would_delete") or []
    if items:
        for item in items:
            lines.append(f"- `{item.get('source_path')}` archive=`{item.get('archive_path')}` tombstone=`{item.get('tombstone_path')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Skipped")
    lines.append("")
    skipped = payload.get("skipped", []) if isinstance(payload.get("skipped"), list) else []
    if skipped:
        for item in skipped:
            path = f" `{item.get('path')}`" if item.get("path") else ""
            lines.append(f"-{path} — `{item.get('reason')}`")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def write_script_delete_apply_result(payload: dict[str, Any]) -> dict[str, Any]:
    DELETE_APPLY_RESULT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    DELETE_APPLY_RESULT_MD.write_text(render_script_delete_apply_result_markdown(payload))
    return payload


def post_delete_record_checks(record: dict[str, Any]) -> list[dict[str, Any]]:
    source_path = str(record.get("source_path") or "")
    archive_path_text = str(record.get("archive_path") or "")
    tombstone_path_text = str(record.get("tombstone_path") or "")
    checks: list[dict[str, Any]] = []
    try:
        source = safe_repo_relative_path(source_path)
        source_absent = not source.exists()
        checks.append({"name": "source_path_absent_after_delete", "status": "ok" if source_absent else "error", "path": source_path, "detail": "absent" if source_absent else "present"})
    except ValueError as exc:
        checks.append({"name": "source_path_safe_after_delete", "status": "error", "path": source_path, "detail": str(exc)})
    archive_path = archive_abs_path_from_maintenance_path(archive_path_text)
    tombstone_path = archive_abs_path_from_maintenance_path(tombstone_path_text)
    archive_absent = not archive_path.exists()
    tombstone_absent = not tombstone_path.exists()
    checks.append({"name": "archive_absent_after_delete", "status": "ok" if archive_absent else "error", "path": maintenance_path(archive_path), "detail": "absent" if archive_absent else "present"})
    checks.append({"name": "tombstone_absent_after_delete", "status": "ok" if tombstone_absent else "error", "path": maintenance_path(tombstone_path), "detail": "absent" if tombstone_absent else "present"})
    restore_result = restore_archived_script(tombstone_path_text)
    restore_safe = restore_result.get("ok") is False and restore_result.get("reason") in {"tombstone_missing_or_not_file", "archive_missing_or_not_file"}
    checks.append({
        "name": "restore_after_delete_fails_safely",
        "status": "ok" if restore_safe else "error",
        "path": tombstone_path_text,
        "detail": f"ok={restore_result.get('ok')} reason={restore_result.get('reason')}",
    })
    return checks


def build_post_delete_verification_result(delete_apply_result: dict[str, Any]) -> dict[str, Any]:
    deleted = delete_apply_result.get("deleted", []) if isinstance(delete_apply_result.get("deleted"), list) else []
    checks: list[dict[str, Any]] = []
    if delete_apply_result.get("schema_version") != "orchestrator-script-delete-apply-result/v1":
        checks.append({"name": "delete_apply_result_schema", "status": "error", "detail": str(delete_apply_result.get("schema_version"))})
    else:
        checks.append({"name": "delete_apply_result_schema", "status": "ok", "detail": str(delete_apply_result.get("schema_version"))})
    if not deleted:
        checks.append({"name": "no_deleted_records", "status": "ok", "detail": "no deletion occurred; post-delete path checks are a no-op"})
    for record in deleted:
        checks.extend(post_delete_record_checks(record))
    self_check = run_maintenance_self_check()
    self_payload = self_check.get("payload", {}) if isinstance(self_check.get("payload"), dict) else {}
    checks.append({
        "name": "maintenance_self_check_after_delete",
        "status": "ok" if self_check.get("returncode") == 0 and self_payload.get("overall_status") != "error" else "error",
        "detail": f"overall={self_payload.get('overall_status')} returncode={self_check.get('returncode')}",
    })
    statuses = {item["status"] for item in checks}
    return {
        "schema_version": "orchestrator-script-post-delete-verification/v1",
        "phase": "G5",
        "mode": "post_delete_verification",
        "mutating": False,
        "ok": "error" not in statuses,
        "deleted_count": len(deleted),
        "check_count": len(checks),
        "checks": checks,
        "delete_apply_summary": {
            "schema_version": delete_apply_result.get("schema_version"),
            "mode": delete_apply_result.get("mode"),
            "mutating": delete_apply_result.get("mutating"),
            "ready_operation_count": delete_apply_result.get("ready_operation_count"),
            "deleted_count": delete_apply_result.get("deleted_count"),
            "skipped_count": delete_apply_result.get("skipped_count"),
            "json_path": maintenance_path(DELETE_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(DELETE_APPLY_RESULT_MD),
        },
        "self_check": {
            "overall_status": self_payload.get("overall_status"),
            "summary": self_payload.get("summary", {}),
            "json_path": maintenance_path(MAINTENANCE_SELF_CHECK_JSON),
            "markdown_path": maintenance_path(MAINTENANCE_SELF_CHECK_MD),
        },
        "notes": [
            "G5 is non-mutating verification after G4 delete apply.",
            "If deletion occurred, source, archive, and tombstone must all be absent, and restore must fail safely/evidently because the tombstone/archive were deleted.",
        ],
    }


def render_post_delete_verification_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Post-Delete Verification", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"OK: **{payload.get('ok', False)}**")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Deleted count: **{payload.get('deleted_count', 0)}**")
    lines.append(f"Check count: **{payload.get('check_count', 0)}**")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for item in payload.get("checks", []):
        path = f" path=`{item.get('path')}`" if item.get("path") else ""
        lines.append(f"- **{item.get('status')}** `{item.get('name')}` — {item.get('detail')}{path}")
    lines.append("")
    return "\n".join(lines)


def write_post_delete_verification_result(payload: dict[str, Any]) -> dict[str, Any]:
    POST_DELETE_VERIFICATION_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    POST_DELETE_VERIFICATION_MD.write_text(render_post_delete_verification_markdown(payload))
    return payload


def build_cleanup_plan(summary: dict[str, Any], clutter_payload: dict[str, Any]) -> dict[str, Any]:
    tracked = git_tracked_paths()
    clutter_actions: list[dict[str, Any]] = []
    for record in clutter_payload.get("records", []):
        path = record["path"]
        tracked_by_git = path in tracked
        if tracked_by_git:
            action = "blocked"
            reason = "tracked_by_git"
        elif record["category"] == "macos_metadata":
            action = "auto_remove_clutter_ready"
            reason = "macos_metadata_untracked"
        elif record["category"] == "python_bytecode_cache":
            action = "auto_remove_clutter_ready"
            reason = "python_bytecode_cache_untracked_after_process_check"
        elif record["category"] == "runtime_state":
            action = "manual_review_only"
            reason = "runtime_state_may_be_live_or_diagnostic"
        else:
            action = "blocked"
            reason = "unknown_clutter_category"
        clutter_actions.append({**record, "tracked_by_git": tracked_by_git, "planned_action": action, "reason": reason})

    script_actions: list[dict[str, Any]] = []
    for candidate in summary.get("review_candidates", []):
        override = candidate.get("lifecycle_override") or {}
        auto_promotion = deterministic_archive_promotion_evidence(candidate, tracked)
        effective_override = merge_autonomous_archive_promotion(override, auto_promotion)
        effective_candidate = {**candidate, "lifecycle_override": effective_override}
        no_refs = int(candidate.get("inbound_reference_count", 0) or 0) == 0
        confidence = script_high_confidence_checks(effective_candidate, effective_override, tracked)
        gate_evaluation = cleanup_gate_evaluation(effective_candidate, confidence)
        action, reason = usage_aware_action(effective_candidate, confidence, no_refs, gate_evaluation)
        cleanup_usage = script_usage_for_cleanup(effective_candidate)
        script_actions.append(
            {
                **candidate,
                "lifecycle_override": effective_override if effective_override else candidate.get("lifecycle_override"),
                "autonomous_archive_promotion": auto_promotion,
                "planned_action": action,
                "reason": reason,
                "review_after": effective_override.get("review_after"),
                "usage_cleanup": cleanup_usage,
                "cleanup_gate_evaluation": gate_evaluation,
                "high_confidence": confidence,
            }
        )

    auto_archive_promotion = write_auto_archive_promotion_report(script_actions)
    action_counts = Counter(item["planned_action"] for item in [*clutter_actions, *script_actions])
    high_confidence_removal_count = sum(1 for item in script_actions if item["planned_action"] == "auto_delete_ready")
    high_confidence_archive_count = sum(1 for item in script_actions if item["planned_action"] == "auto_archive_ready")
    return {
        "schema_version": "orchestrator-cleanup-plan/v2",
        "mode": "dry_run_only",
        "high_confidence_threshold": {
            "required": [
                "no_static_inbound_refs",
                "removal_eligible_class",
                "underlying_condition_resolved_if_needed",
                "lifecycle_approved",
                "operator_docs_checked",
                "launchd_cron_checked",
                "external_usage_checked",
                "runtime_state_checked",
                "archive_path_defined",
            ],
            "removal_extra_required": ["archived_for_one_cycle"],
            "approval_statuses": ["archive_approved", "removal_approved", "phase_h_autonomous_archive_promotion"],
            "usage_required_blockers": [
                "pre_instrumentation_unknown",
                "no_observed_ledger_usage",
                "coverage_window_not_mature",
                "has_static_inbound_references",
                "has_cron_reference",
                "has_launchd_reference",
                "has_operator_doc_reference",
                "has_runtime_log_reference",
            ],
        },
        "summary": {
            "clutter_action_count": len(clutter_actions),
            "script_review_action_count": len(script_actions),
            "action_counts": dict(sorted(action_counts.items())),
            "high_confidence_archive_count": high_confidence_archive_count,
            "high_confidence_removal_count": high_confidence_removal_count,
            "automatic_loop_required": False,
            "gate_evaluation_mode": "report_only",
            "auto_archive_promotion": {
                "schema_version": auto_archive_promotion.get("schema_version"),
                "phase": auto_archive_promotion.get("phase"),
                "mode": auto_archive_promotion.get("mode"),
                "candidate_count": auto_archive_promotion.get("candidate_count", 0),
                "eligible_count": auto_archive_promotion.get("eligible_count", 0),
                "json_path": maintenance_path(AUTO_ARCHIVE_PROMOTION_JSON),
                "markdown_path": maintenance_path(AUTO_ARCHIVE_PROMOTION_MD),
            },
            "gate_ready_counts": {
                "archive": sum(1 for item in script_actions if item.get("cleanup_gate_evaluation", {}).get("archive", {}).get("ready")),
                "delete": sum(1 for item in script_actions if item.get("cleanup_gate_evaluation", {}).get("delete", {}).get("ready")),
            },
            "usage_aware_action_classes": [
                "auto_remove_clutter_ready",
                "archive_review_candidate",
                "auto_archive_ready",
                "archived_quarantine",
                "auto_delete_ready",
                "retain_recently_used",
                "retain_referenced",
                "manual_lifecycle_review",
                "manual_review_required",
            ],
        },
        "clutter_actions": clutter_actions,
        "script_review_actions": script_actions,
        "notes": [
            "This plan is non-mutating and does not delete, move, or archive files.",
            "High-confidence archive/removal requires explicit lifecycle approval plus verification checks and usage-aware blockers must be clear.",
            "Prefer archive/move plans for scripts before deletion; removal requires at least one archived maintenance cycle.",
            "D2 gate evaluation is report-only; it does not enable archive/delete apply.",
            "D3 candidate history tracks repeated state and no-use maturity as report-only evidence.",
            "E1 clutter apply dry-run is non-mutating and limited to trivial clutter classes.",
        ],
    }


def build_clutter_apply_dry_run(cleanup_plan: dict[str, Any]) -> dict[str, Any]:
    actions = cleanup_plan.get("clutter_actions", []) if isinstance(cleanup_plan.get("clutter_actions"), list) else []
    operations: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in actions:
        category = item.get("category")
        planned_action = item.get("planned_action")
        tracked_by_git = bool(item.get("tracked_by_git"))
        kind = item.get("kind")
        path = item.get("path")
        if planned_action == "auto_remove_clutter_ready" and not tracked_by_git and category == "macos_metadata" and kind == "file":
            operations.append(
                {
                    "path": path,
                    "category": category,
                    "kind": kind,
                    "dry_run_action": "would_remove_file",
                    "apply_slice": "E2",
                    "required_preflight": ["fresh_git_status_confirms_untracked_or_ignored"],
                }
            )
        elif planned_action == "auto_remove_clutter_ready" and not tracked_by_git and category == "python_bytecode_cache" and kind == "directory":
            operations.append(
                {
                    "path": path,
                    "category": category,
                    "kind": kind,
                    "dry_run_action": "would_remove_directory_after_process_check",
                    "apply_slice": "E3",
                    "required_preflight": ["fresh_git_status_confirms_untracked_or_ignored", "no_live_python_process_using_tree"],
                }
            )
        else:
            excluded.append(
                {
                    "path": path,
                    "category": category,
                    "kind": kind,
                    "planned_action": planned_action,
                    "reason": item.get("reason"),
                    "tracked_by_git": tracked_by_git,
                    "exclude_reason": "not_trivial_clutter_ready_for_e1_dry_run",
                }
            )
    operation_counts = Counter(op["dry_run_action"] for op in operations)
    return {
        "schema_version": "orchestrator-clutter-apply-dry-run/v1",
        "phase": "E1",
        "mode": "dry_run_only",
        "mutating": False,
        "trivial_categories": ["macos_metadata", "python_bytecode_cache"],
        "operation_count": len(operations),
        "excluded_count": len(excluded),
        "operation_counts": dict(sorted(operation_counts.items())),
        "operations": operations,
        "excluded": excluded,
        "notes": [
            "E1 is a non-mutating dry-run only; it does not remove files or directories.",
            "E2 may apply only macOS metadata removals after a fresh git-status check.",
            "E3 may apply Python bytecode cache removals only after process checks confirm the tree is not live.",
            "Runtime-state and unknown clutter remain manual-review only.",
        ],
    }


def render_clutter_apply_dry_run_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Clutter Apply Dry Run", ""]
    lines.append("Mode: `dry_run_only`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Operation count: **{payload.get('operation_count', 0)}**")
    lines.append(f"Excluded count: **{payload.get('excluded_count', 0)}**")
    lines.append("")
    lines.append("## Operation counts")
    lines.append("")
    counts = payload.get("operation_counts", {}) if isinstance(payload.get("operation_counts"), dict) else {}
    if counts:
        for name, count in counts.items():
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Dry-run operations")
    lines.append("")
    operations = payload.get("operations", []) if isinstance(payload.get("operations"), list) else []
    if operations:
        for item in operations:
            preflight = ",".join(item.get("required_preflight", []))
            lines.append(f"- `{item.get('path')}` — `{item.get('dry_run_action')}`; slice={item.get('apply_slice')}; preflight={preflight}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Excluded")
    lines.append("")
    excluded = payload.get("excluded", []) if isinstance(payload.get("excluded"), list) else []
    if excluded:
        for item in excluded:
            lines.append(f"- `{item.get('path')}` — `{item.get('planned_action')}`; {item.get('exclude_reason')}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_clutter_apply_dry_run(cleanup_plan: dict[str, Any]) -> dict[str, Any]:
    payload = build_clutter_apply_dry_run(cleanup_plan)
    CLUTTER_APPLY_DRY_RUN_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    CLUTTER_APPLY_DRY_RUN_MD.write_text(render_clutter_apply_dry_run_markdown(payload))
    return payload


def git_status_lines_for_path(path: str) -> list[str]:
    proc = run_command(["git", "status", "--porcelain=v1", "--ignored", "--untracked-files=all", "--", path])
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_status_path_prefix() -> str:
    proc = run_command(["git", "rev-parse", "--show-prefix"])
    return proc.stdout.strip()


def git_status_confirms_untracked_or_ignored(lines: list[str], path: str, prefix: str = "") -> bool:
    if not lines:
        return False
    prefixed = f"{prefix.rstrip('/')}/{path}" if prefix else path
    expected_suffixes = {path, f"{path}/", prefixed, f"{prefixed}/"}
    for line in lines:
        if len(line) < 4:
            return False
        status = line[:2]
        reported = line[3:].strip('"')
        if status not in {"??", "!!"}:
            return False
        if reported not in expected_suffixes:
            return False
    return True


def git_status_confirms_tree_untracked_or_ignored(lines: list[str], path: str, prefix: str = "") -> bool:
    if not lines:
        return False
    base = path.rstrip("/")
    prefixed = f"{prefix.rstrip('/')}/{base}" if prefix else base
    allowed_prefixes = (f"{base}/", f"{prefixed}/")
    allowed_exact = {base, f"{base}/", prefixed, f"{prefixed}/"}
    for line in lines:
        if len(line) < 4:
            return False
        status = line[:2]
        reported = line[3:].strip('"')
        if status not in {"??", "!!"}:
            return False
        if reported in allowed_exact:
            continue
        if not reported.startswith(allowed_prefixes):
            return False
    return True


def safe_repo_relative_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe repo-relative path: {path}")
    resolved = (REPO_ROOT / candidate).resolve()
    if not resolved.is_relative_to(REPO_ROOT):
        raise ValueError(f"path escapes repo root: {path}")
    return resolved


def live_python_processes_using_tree(target: Path) -> list[dict[str, Any]]:
    target_text = str(target)
    matches: list[dict[str, Any]] = []
    lsof_proc = subprocess.run(["lsof", "+D", target_text], text=True, capture_output=True)
    if lsof_proc.returncode not in {0, 1}:
        matches.append({"source": "lsof", "error": lsof_proc.stderr.strip() or f"exit_{lsof_proc.returncode}"})
    for line in lsof_proc.stdout.splitlines()[1:]:
        parts = line.split(None, 8)
        if len(parts) >= 2 and "python" in parts[0].lower():
            matches.append({"source": "lsof", "pid": parts[1], "command": parts[0], "line": line})
    ps_proc = subprocess.run(["ps", "-axo", "pid=,comm=,args="], text=True, capture_output=True)
    if ps_proc.returncode != 0:
        matches.append({"source": "ps", "error": ps_proc.stderr.strip() or f"exit_{ps_proc.returncode}"})
    for line in ps_proc.stdout.splitlines():
        if target_text in line and "python" in line.lower():
            parts = line.split(None, 2)
            matches.append({"source": "ps", "pid": parts[0] if parts else "", "line": line.strip()})
    return matches


def build_ds_store_apply_result(dry_run: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    operations = dry_run.get("operations", []) if isinstance(dry_run.get("operations"), list) else []
    status_prefix = git_status_path_prefix()
    removed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in operations:
        path = str(item.get("path") or "")
        if item.get("apply_slice") != "E2" or item.get("category") != "macos_metadata" or item.get("kind") != "file" or not path.endswith(".DS_Store"):
            skipped.append({"path": path, "reason": "not_e2_ds_store_operation"})
            continue
        try:
            target = safe_repo_relative_path(path)
        except ValueError as exc:
            skipped.append({"path": path, "reason": "unsafe_path", "detail": str(exc)})
            continue
        status_lines = git_status_lines_for_path(path)
        if not git_status_confirms_untracked_or_ignored(status_lines, path, status_prefix):
            skipped.append({"path": path, "reason": "fresh_git_status_not_untracked_or_ignored", "git_status_lines": status_lines})
            continue
        if not target.exists():
            skipped.append({"path": path, "reason": "already_absent", "git_status_lines": status_lines})
            continue
        if not target.is_file():
            skipped.append({"path": path, "reason": "not_a_file", "git_status_lines": status_lines})
            continue
        if apply:
            target.unlink()
            removed.append({"path": path, "git_status_lines": status_lines, "action": "removed_file"})
        else:
            removed.append({"path": path, "git_status_lines": status_lines, "action": "would_remove_file"})
    return {
        "schema_version": "orchestrator-clutter-apply-result/v1",
        "phase": "E2",
        "mode": "apply" if apply else "dry_run_only",
        "mutating": apply,
        "removed_count": len(removed) if apply else 0,
        "would_remove_count": len(removed) if not apply else 0,
        "skipped_count": len(skipped),
        "removed": removed if apply else [],
        "would_remove": removed if not apply else [],
        "skipped": skipped,
        "preflight": "fresh git status --porcelain=v1 --ignored --untracked-files=all confirmed every removed path was untracked or ignored",
        "scope": "Only .DS_Store files from E2 clutter dry-run operations are eligible.",
    }


def build_pycache_apply_result(dry_run: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    operations = dry_run.get("operations", []) if isinstance(dry_run.get("operations"), list) else []
    status_prefix = git_status_path_prefix()
    removed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in operations:
        path = str(item.get("path") or "")
        if item.get("apply_slice") != "E3" or item.get("category") != "python_bytecode_cache" or item.get("kind") != "directory" or not path.endswith("__pycache__"):
            skipped.append({"path": path, "reason": "not_e3_pycache_operation"})
            continue
        try:
            target = safe_repo_relative_path(path)
        except ValueError as exc:
            skipped.append({"path": path, "reason": "unsafe_path", "detail": str(exc)})
            continue
        status_lines = git_status_lines_for_path(path)
        if not git_status_confirms_tree_untracked_or_ignored(status_lines, path, status_prefix):
            skipped.append({"path": path, "reason": "fresh_git_status_not_untracked_or_ignored_tree", "git_status_lines": status_lines})
            continue
        if not target.exists():
            skipped.append({"path": path, "reason": "already_absent", "git_status_lines": status_lines})
            continue
        if not target.is_dir():
            skipped.append({"path": path, "reason": "not_a_directory", "git_status_lines": status_lines})
            continue
        live_processes = live_python_processes_using_tree(target)
        if live_processes:
            skipped.append({"path": path, "reason": "live_python_process_using_tree", "git_status_lines": status_lines, "live_processes": live_processes})
            continue
        if apply:
            shutil.rmtree(target)
            removed.append({"path": path, "git_status_lines": status_lines, "action": "removed_directory", "process_check": "no_live_python_process_using_tree"})
        else:
            removed.append({"path": path, "git_status_lines": status_lines, "action": "would_remove_directory", "process_check": "no_live_python_process_using_tree"})
    return {
        "schema_version": "orchestrator-clutter-apply-result/v1",
        "phase": "E3",
        "mode": "apply" if apply else "dry_run_only",
        "mutating": apply,
        "removed_count": len(removed) if apply else 0,
        "would_remove_count": len(removed) if not apply else 0,
        "skipped_count": len(skipped),
        "removed": removed if apply else [],
        "would_remove": removed if not apply else [],
        "skipped": skipped,
        "preflight": "fresh git status confirmed every removed __pycache__ tree was untracked or ignored, and process checks found no live Python process using the tree",
        "scope": "Only __pycache__ directories from E3 clutter dry-run operations are eligible.",
    }


def select_generated_run_retention(run_dirs: list[Path], *, keep_latest: int = GENERATED_RUN_RETENTION_KEEP_LATEST) -> dict[str, list[Path]]:
    ordered = sorted((path for path in run_dirs if path.is_dir()), key=lambda path: path.name, reverse=True)
    protected = ordered[:keep_latest]
    removable = ordered[keep_latest:]
    return {"protected": protected, "removable": removable}


def safe_generated_run_dir(path: Path) -> Path:
    resolved = path.resolve()
    runs_root = RUNS_ROOT.resolve()
    if not resolved.is_dir():
        raise ValueError(f"not a run directory: {path}")
    if resolved.parent != runs_root:
        raise ValueError(f"not an approved generated run artifact: {path}")
    if not resolved.name.startswith("orchestrator-repo-"):
        raise ValueError(f"unexpected generated run artifact name: {path.name}")
    return resolved


def build_generated_artifact_retention_result(*, apply: bool, keep_latest: int = GENERATED_RUN_RETENTION_KEEP_LATEST) -> dict[str, Any]:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_dirs = [path for path in RUNS_ROOT.iterdir() if path.is_dir()]
    selection = select_generated_run_retention(run_dirs, keep_latest=keep_latest)
    removed: list[dict[str, Any]] = []
    would_remove: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    protected = [maintenance_path(path) for path in selection["protected"]]
    for path in selection["removable"]:
        try:
            safe_path = safe_generated_run_dir(path)
        except ValueError as exc:
            skipped.append({"path": maintenance_path(path), "reason": "unsafe_or_unapproved_generated_artifact", "detail": str(exc)})
            continue
        record = {"path": maintenance_path(safe_path), "artifact_type": "scheduled_run_envelope", "action": "removed_generated_run_dir" if apply else "would_remove_generated_run_dir"}
        if apply:
            shutil.rmtree(safe_path)
            removed.append(record)
        else:
            would_remove.append(record)
    return {
        "schema_version": "orchestrator-generated-artifact-retention-result/v1",
        "phase": "E4",
        "mode": "apply" if apply else "dry_run_only",
        "mutating": apply,
        "approved_roots": [maintenance_path(RUNS_ROOT)],
        "protected_latest_status_outputs": [
            maintenance_path(MAINTENANCE_SUMMARY_JSON),
            maintenance_path(REPO_HEALTH_JSON),
            maintenance_path(CLEANUP_PLAN_JSON),
            maintenance_path(CLUTTER_INVENTORY_JSON),
            maintenance_path(SCRIPT_USAGE_SUMMARY_JSON),
        ],
        "retention_policy": {"run_envelopes_keep_latest": keep_latest},
        "protected_count": len(protected),
        "removed_count": len(removed),
        "would_remove_count": len(would_remove),
        "skipped_count": len(skipped),
        "protected": protected,
        "removed": removed,
        "would_remove": would_remove,
        "skipped": skipped,
        "scope": "Only generated/runs/orchestrator-repo-* run directories are eligible; latest status outputs and ledger evidence are protected.",
    }


def render_generated_artifact_retention_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Generated Artifact Retention Result", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Removed count: **{payload.get('removed_count', 0)}**")
    lines.append(f"Would-remove count: **{payload.get('would_remove_count', 0)}**")
    lines.append(f"Protected count: **{payload.get('protected_count', 0)}**")
    lines.append(f"Skipped count: **{payload.get('skipped_count', 0)}**")
    lines.append("")
    lines.append("## Removed")
    lines.append("")
    removed = payload.get("removed", []) if isinstance(payload.get("removed"), list) else []
    if removed:
        for item in removed:
            lines.append(f"- `{item.get('path')}` — `{item.get('action')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Protected latest run artifacts")
    lines.append("")
    protected = payload.get("protected", []) if isinstance(payload.get("protected"), list) else []
    if protected:
        for item in protected:
            lines.append(f"- `{item}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Protected status outputs")
    lines.append("")
    for item in payload.get("protected_latest_status_outputs", []):
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("## Guardrails")
    lines.append("")
    lines.append(f"- {payload.get('scope')}")
    lines.append("")
    return "\n".join(lines)


def write_generated_artifact_retention_result(payload: dict[str, Any]) -> dict[str, Any]:
    GENERATED_RETENTION_RESULT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    GENERATED_RETENTION_RESULT_MD.write_text(render_generated_artifact_retention_markdown(payload))
    return payload


def render_clutter_apply_result_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Clutter Apply Result", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Mode: `{payload.get('mode')}`")
    lines.append(f"Mutating: **{payload.get('mutating', False)}**")
    lines.append(f"Removed count: **{payload.get('removed_count', 0)}**")
    lines.append(f"Would-remove count: **{payload.get('would_remove_count', 0)}**")
    lines.append(f"Skipped count: **{payload.get('skipped_count', 0)}**")
    lines.append("")
    lines.append("## Removed")
    lines.append("")
    removed = payload.get("removed", []) if isinstance(payload.get("removed"), list) else []
    if removed:
        for item in removed:
            lines.append(f"- `{item.get('path')}` — `{item.get('action')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Skipped")
    lines.append("")
    skipped = payload.get("skipped", []) if isinstance(payload.get("skipped"), list) else []
    if skipped:
        for item in skipped:
            lines.append(f"- `{item.get('path')}` — `{item.get('reason')}`")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Guardrails")
    lines.append("")
    lines.append(f"- {payload.get('preflight')}")
    lines.append(f"- {payload.get('scope')}")
    lines.append("")
    return "\n".join(lines)


def write_clutter_apply_result(payload: dict[str, Any]) -> dict[str, Any]:
    CLUTTER_APPLY_RESULT_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    CLUTTER_APPLY_RESULT_MD.write_text(render_clutter_apply_result_markdown(payload))
    return payload


def run_maintenance_self_check() -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(MAINTENANCE_SELF_CHECK), "--pretty"], cwd=str(MAINTENANCE_DIR.parent), text=True, capture_output=True)
    payload = load_json_if_exists(MAINTENANCE_SELF_CHECK_JSON)
    return {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1000:],
        "stderr_tail": proc.stderr[-1000:],
        "payload": payload,
    }


def build_post_apply_verification_result(apply_kind: str, apply_summary: dict[str, Any]) -> dict[str, Any]:
    self_check = run_maintenance_self_check()
    self_payload = self_check.get("payload", {}) if isinstance(self_check.get("payload"), dict) else {}
    repo_health = load_json_if_exists(REPO_HEALTH_JSON)
    checks = [
        {
            "name": "maintenance_self_check",
            "status": "ok" if self_check.get("returncode") == 0 and self_payload.get("overall_status") != "error" else "error",
            "detail": f"overall={self_payload.get('overall_status')} returncode={self_check.get('returncode')}",
        },
        {
            "name": "repo_health_scorecard",
            "status": "ok" if repo_health.get("schema_version") == "orchestrator-repo-health-summary/v1" else "error",
            "detail": f"overall_band={repo_health.get('overall_band')} overall_score={repo_health.get('overall_score')}",
        },
    ]
    statuses = {item["status"] for item in checks}
    return {
        "schema_version": "orchestrator-post-apply-verification/v1",
        "phase": "E5",
        "apply_kind": apply_kind,
        "ok": "error" not in statuses,
        "checks": checks,
        "apply_summary": apply_summary,
        "self_check": {
            "overall_status": self_payload.get("overall_status"),
            "summary": self_payload.get("summary", {}),
            "json_path": maintenance_path(MAINTENANCE_SELF_CHECK_JSON),
            "markdown_path": maintenance_path(MAINTENANCE_SELF_CHECK_MD),
        },
        "repo_health": {
            "overall_band": repo_health.get("overall_band"),
            "overall_score": repo_health.get("overall_score"),
            "json_path": maintenance_path(REPO_HEALTH_JSON),
            "markdown_path": maintenance_path(REPO_HEALTH_MD),
        },
        "note": "E5 records post-apply verification after each explicit apply slice. Repo health may be needs_attention due pre-existing backlog; verification fails only on missing/invalid scorecard or self-check errors.",
    }


def render_post_apply_verification_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Post-Apply Verification", ""]
    lines.append(f"Phase: `{payload.get('phase')}`")
    lines.append(f"Apply kind: `{payload.get('apply_kind')}`")
    lines.append(f"OK: **{payload.get('ok', False)}**")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for item in payload.get("checks", []):
        lines.append(f"- **{item.get('status')}** `{item.get('name')}` — {item.get('detail')}")
    lines.append("")
    self_check = payload.get("self_check", {}) if isinstance(payload.get("self_check"), dict) else {}
    lines.append("## Self-check")
    lines.append("")
    lines.append(f"- Overall: `{self_check.get('overall_status')}`")
    lines.append(f"- Summary: `{self_check.get('summary', {})}`")
    lines.append("")
    repo_health = payload.get("repo_health", {}) if isinstance(payload.get("repo_health"), dict) else {}
    lines.append("## Repo health")
    lines.append("")
    lines.append(f"- Band: `{repo_health.get('overall_band')}`")
    lines.append(f"- Score: `{repo_health.get('overall_score')}`")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append(f"- {payload.get('note')}")
    lines.append("")
    return "\n".join(lines)


def write_post_apply_verification_result(payload: dict[str, Any]) -> dict[str, Any]:
    POST_APPLY_VERIFICATION_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    POST_APPLY_VERIFICATION_MD.write_text(render_post_apply_verification_markdown(payload))
    return payload


def apply_summary_for_post_apply(kind: str, summary: dict[str, Any]) -> dict[str, Any]:
    if kind in {"ds_store_clutter", "pycache_clutter"}:
        return summary.get("clutter_apply_result", {}) if isinstance(summary.get("clutter_apply_result"), dict) else {}
    if kind == "generated_retention":
        return summary.get("generated_artifact_retention", {}) if isinstance(summary.get("generated_artifact_retention"), dict) else {}
    if kind == "script_archive":
        return summary.get("script_archive_apply_result", {}) if isinstance(summary.get("script_archive_apply_result"), dict) else {}
    if kind == "script_delete":
        return summary.get("script_delete_apply_result", {}) if isinstance(summary.get("script_delete_apply_result"), dict) else {}
    return {}


def refresh_cleanup_outputs(
    summary: dict[str, Any],
    previous_cleanup_plan: dict[str, Any],
    previous_cleanup_history: dict[str, Any],
    previous_usage_summary: dict[str, Any] | None = None,
    previous_blocker_report: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    clutter_payload = write_clutter_inventory()
    health = write_repo_health_scorecard(summary, build_drift_report(summary, load_json_if_exists(PREVIOUS_MAINTENANCE_SUMMARY_JSON)), clutter_payload)
    cleanup_plan = write_cleanup_plan(summary, clutter_payload)
    clutter_apply_dry_run = write_clutter_apply_dry_run(cleanup_plan)
    cleanup_history = load_json_if_exists(CLEANUP_CANDIDATE_HISTORY_JSON)
    cleanup_evidence_diff = write_cleanup_evidence_diff(cleanup_plan, previous_cleanup_plan, cleanup_history, previous_cleanup_history)
    current_usage_summary = load_json_if_exists(SCRIPT_USAGE_SUMMARY_JSON)
    blocker_report = write_script_cleanup_blocker_report(cleanup_plan, current_usage_summary)
    evidence_movement = write_script_cleanup_evidence_movement(
        previous_usage_summary or {},
        current_usage_summary,
        previous_cleanup_plan,
        cleanup_plan,
        previous_blocker_report or {},
        blocker_report,
    )
    summary["clutter"] = generated_clutter_summary(clutter_payload)
    summary["repo_health"] = {
        "overall_score": health["overall_score"],
        "overall_band": health["overall_band"],
        "json_path": maintenance_path(REPO_HEALTH_JSON),
        "markdown_path": maintenance_path(REPO_HEALTH_MD),
    }
    summary["cleanup_plan"] = {
        "mode": cleanup_plan["mode"],
        "action_counts": cleanup_plan["summary"]["action_counts"],
        "high_confidence_archive_count": cleanup_plan["summary"]["high_confidence_archive_count"],
        "high_confidence_removal_count": cleanup_plan["summary"]["high_confidence_removal_count"],
        "auto_archive_promotion": cleanup_plan["summary"].get("auto_archive_promotion", {}),
        "candidate_history": cleanup_plan["summary"].get("candidate_history", {}),
        "json_path": maintenance_path(CLEANUP_PLAN_JSON),
        "markdown_path": maintenance_path(CLEANUP_PLAN_MD),
        "evidence_diff": {
            "meaningful_change_count": cleanup_evidence_diff.get("meaningful_change_count"),
            "json_path": maintenance_path(CLEANUP_EVIDENCE_DIFF_JSON),
            "markdown_path": maintenance_path(CLEANUP_EVIDENCE_DIFF_MD),
        },
        "blockers": {
            "autonomous_next_action_count": blocker_report.get("autonomous_next_action_count", 0),
            "manual_owner_review_required_count": blocker_report.get("manual_owner_review_required_count", 0),
            "ready_candidate_slo": blocker_report.get("ready_candidate_slo", {}),
            "json_path": maintenance_path(SCRIPT_CLEANUP_BLOCKERS_JSON),
            "markdown_path": maintenance_path(SCRIPT_CLEANUP_BLOCKERS_MD),
        },
        "evidence_movement": {
            "throughput_status": evidence_movement.get("throughput_status"),
            "unknown_reduced_count": evidence_movement.get("unknown_reduced_count", 0),
            "new_observed_count": evidence_movement.get("new_observed_count", 0),
            "new_referenced_count": evidence_movement.get("new_referenced_count", 0),
            "ready_candidate_count": evidence_movement.get("ready_candidate_count", 0),
            "retired_candidate_count": evidence_movement.get("retired_candidate_count", 0),
            "stranded_unknown_count": evidence_movement.get("stranded_unknown_count", 0),
            "blocker_retired_count": evidence_movement.get("blocker_retired_count", 0),
            "zero_archive_delete_throughput_acceptable": evidence_movement.get("zero_archive_delete_throughput_acceptable", False),
            "json_path": maintenance_path(SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_JSON),
            "markdown_path": maintenance_path(SCRIPT_CLEANUP_EVIDENCE_MOVEMENT_MD),
        },
    }
    summary["clutter_apply_dry_run"] = {
        "mode": clutter_apply_dry_run["mode"],
        "mutating": clutter_apply_dry_run["mutating"],
        "operation_count": clutter_apply_dry_run["operation_count"],
        "excluded_count": clutter_apply_dry_run["excluded_count"],
        "operation_counts": clutter_apply_dry_run["operation_counts"],
        "json_path": maintenance_path(CLUTTER_APPLY_DRY_RUN_JSON),
        "markdown_path": maintenance_path(CLUTTER_APPLY_DRY_RUN_MD),
    }
    return clutter_payload, cleanup_plan, clutter_apply_dry_run


def render_cleanup_plan_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Cleanup Plan", "", "Mode: `dry_run_only`", ""]
    summary = payload["summary"]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Clutter actions: **{summary['clutter_action_count']}**")
    lines.append(f"- Script review actions: **{summary['script_review_action_count']}**")
    lines.append(f"- High-confidence archive candidates: **{summary.get('high_confidence_archive_count', 0)}**")
    lines.append(f"- High-confidence removals: **{summary['high_confidence_removal_count']}**")
    lines.append("")
    lines.append(f"- Automatic loop required for high-confidence classification: **{summary.get('automatic_loop_required', False)}**")
    lines.append("")
    lines.append("## High-confidence threshold")
    lines.append("")
    lines.append("Required checks:")
    for check in payload.get("high_confidence_threshold", {}).get("required", []):
        lines.append(f"- `{check}`")
    extra = payload.get("high_confidence_threshold", {}).get("removal_extra_required", [])
    if extra:
        lines.append("")
        lines.append("Removal-only extra checks:")
        for check in extra:
            lines.append(f"- `{check}`")
    lines.append("")
    lines.append("### Action counts")
    lines.append("")
    for action, count in summary["action_counts"].items():
        lines.append(f"- `{action}`: {count}")
    lines.append("")
    lines.append("## Safe clutter candidates")
    lines.append("")
    safe = [item for item in payload["clutter_actions"] if item["planned_action"] == "auto_remove_clutter_ready"]
    if safe:
        for item in safe:
            lines.append(f"- `{item['path']}` — `{item['planned_action']}`; {item['reason']}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Manual/blocking clutter candidates")
    lines.append("")
    manual = [item for item in payload["clutter_actions"] if item["planned_action"] != "auto_remove_clutter_ready"]
    if manual:
        for item in manual:
            lines.append(f"- `{item['path']}` — `{item['planned_action']}`; {item['reason']}")
    else:
        lines.append("_None._")
    lines.append("")
    lines.append("## Script lifecycle review actions")
    lines.append("")
    for item in payload["script_review_actions"]:
        review_after = f"; review_after={item['review_after']}" if item.get("review_after") else ""
        failed = item.get("high_confidence", {}).get("failed_checks", [])
        failed_text = f"; failed_checks={','.join(failed)}" if failed else ""
        usage = item.get("usage_cleanup", {})
        usage_text = f"; usage={usage.get('coverage_status', 'unknown')} blockers={len(usage.get('cleanup_eligibility_blockers', []))}"
        gates = item.get("cleanup_gate_evaluation", {})
        archive_blockers = len(gates.get("archive", {}).get("blockers", [])) if isinstance(gates.get("archive"), dict) else 0
        delete_blockers = len(gates.get("delete", {}).get("blockers", [])) if isinstance(gates.get("delete"), dict) else 0
        gate_text = f"; archive_gate_blockers={archive_blockers}; delete_gate_blockers={delete_blockers}"
        history = item.get("candidate_history", {}) if isinstance(item.get("candidate_history"), dict) else {}
        window = history.get("observation_window", {}) if isinstance(history.get("observation_window"), dict) else {}
        history_text = f"; same_state={history.get('consecutive_same_state_count', 0)}; no_use={history.get('consecutive_no_use_count', 0)}; mature={window.get('mature', False)}"
        lines.append(f"- `{item['path']}` — `{item['planned_action']}`; {item['reason']}{review_after}{failed_text}{usage_text}{gate_text}{history_text}")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in payload.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_cleanup_plan(summary: dict[str, Any], clutter_payload: dict[str, Any]) -> dict[str, Any]:
    payload = build_cleanup_plan(summary, clutter_payload)
    history = write_cleanup_candidate_history(payload)
    payload = attach_candidate_history(payload, history)
    CLEANUP_PLAN_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    CLEANUP_PLAN_MD.write_text(render_cleanup_plan_markdown(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Orchestrator maintenance audit outputs")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--apply-ds-store-clutter", action="store_true", help="E2: remove only .DS_Store files after fresh git-status confirms each path is untracked or ignored")
    parser.add_argument("--apply-pycache-clutter", action="store_true", help="E3: remove only __pycache__ directories after git-status and live-Python process checks")
    parser.add_argument("--apply-generated-retention", action="store_true", help="E4: apply bounded retention to approved generated run artifacts while protecting latest status outputs")
    parser.add_argument("--apply-script-archive", action="store_true", help="F3: archive at most one fully gated script proposal after hash/tombstone preflight")
    parser.add_argument("--archive-source-path", help="F3: explicit repo-relative source path to archive when multiple ready proposals exist")
    parser.add_argument("--post-archive-smoke", action="store_true", help="F4: run non-mutating post-archive import/package, classifier, self-check, and touched-surface smoke report")
    parser.add_argument("--quarantine-monitor", action="store_true", help="F5: monitor archived scripts across quarantine cycles and flag restore requirements")
    parser.add_argument("--delete-readiness-report", action="store_true", help="G1: report-only delete readiness for archived/quarantined scripts after clean cycles")
    parser.add_argument("--delete-dry-run-report", action="store_true", help="G2: non-mutating monthly dry-run evidence for delete-ready archived scripts")
    parser.add_argument("--apply-script-delete", action="store_true", help="G4: delete at most one validated archived script artifact+tombstone from G2 dry-run evidence")
    parser.add_argument("--delete-source-path", help="G4: explicit repo-relative original source path to delete when multiple ready delete operations exist")
    parser.add_argument("--post-delete-verification", action="store_true", help="G5: verify post-delete source/archive/tombstone absence and restore safety semantics")
    parser.add_argument("--restore-archived-script", help="Restore one archived script from a tombstone after hash/source preflight")
    args = parser.parse_args()

    if args.restore_archived_script:
        result = restore_archived_script(args.restore_archived_script)
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
        return 0 if result.get("ok") else 1

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    previous_summary = load_json_if_exists(MAINTENANCE_SUMMARY_JSON)
    previous_cleanup_plan = load_json_if_exists(CLEANUP_PLAN_JSON)
    previous_cleanup_history = load_json_if_exists(CLEANUP_CANDIDATE_HISTORY_JSON)
    previous_usage_summary = load_json_if_exists(SCRIPT_USAGE_SUMMARY_JSON)
    previous_blocker_report = load_json_if_exists(SCRIPT_CLEANUP_BLOCKERS_JSON)
    if previous_summary:
        PREVIOUS_MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(previous_summary, indent=2, sort_keys=True) + "\n")
    run_command(
        [
            sys.executable,
            str(SCRIPT_CLASSIFIER),
            "--json-out",
            str(SCRIPT_CLASSIFICATION_JSON),
            "--md-out",
            str(SCRIPT_CLASSIFICATION_MD),
        ]
    )
    run_command(
        [
            sys.executable,
            str(SCRIPT_USAGE_MATERIALIZER),
            "--classification-json",
            str(SCRIPT_CLASSIFICATION_JSON),
            "--output-json",
            str(SCRIPT_USAGE_SUMMARY_JSON),
            "--output-md",
            str(SCRIPT_USAGE_SUMMARY_MD),
        ]
    )
    clutter_payload = write_clutter_inventory()
    summary = build_summary(clutter_payload)
    MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    drift = build_drift_report(summary, previous_summary)
    MAINTENANCE_DRIFT_JSON.write_text(json.dumps(drift, indent=2, sort_keys=True) + "\n")
    MAINTENANCE_DRIFT_MD.write_text(render_drift_markdown(drift))
    _clutter_payload, _cleanup_plan, clutter_apply_dry_run = refresh_cleanup_outputs(
        summary,
        previous_cleanup_plan,
        previous_cleanup_history,
        previous_usage_summary,
        previous_blocker_report,
    )
    archive_layout = write_archive_layout_contract()
    archive_dry_run = write_archive_dry_run(_cleanup_plan, archive_layout)
    summary["archive_layout"] = {
        "mode": archive_layout["mode"],
        "mutating": archive_layout["mutating"],
        "archive_root": archive_layout["archive_root"],
        "schema_version": archive_layout["schema_version"],
        "json_path": maintenance_path(ARCHIVE_LAYOUT_JSON),
        "markdown_path": maintenance_path(ARCHIVE_LAYOUT_MD),
    }
    summary["archive_dry_run"] = {
        "mode": archive_dry_run["mode"],
        "mutating": archive_dry_run["mutating"],
        "proposal_count": archive_dry_run["proposal_count"],
        "blocked_count": archive_dry_run["blocked_count"],
        "json_path": maintenance_path(ARCHIVE_DRY_RUN_JSON),
        "markdown_path": maintenance_path(ARCHIVE_DRY_RUN_MD),
    }
    apply_flags = [args.apply_ds_store_clutter, args.apply_pycache_clutter, args.apply_generated_retention, args.apply_script_archive, args.apply_script_delete]
    if sum(1 for flag in apply_flags if flag) > 1:
        parser.error("apply only one maintenance cleanup slice at a time")
    apply_kind = "none"
    if args.apply_ds_store_clutter:
        apply_result = write_clutter_apply_result(build_ds_store_apply_result(clutter_apply_dry_run, apply=True))
        clutter_payload = write_clutter_inventory()
        summary = build_summary(clutter_payload)
        summary["clutter_apply_result"] = {
            "mode": apply_result["mode"],
            "mutating": apply_result["mutating"],
            "removed_count": apply_result["removed_count"],
            "skipped_count": apply_result["skipped_count"],
            "json_path": maintenance_path(CLUTTER_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(CLUTTER_APPLY_RESULT_MD),
        }
        drift = build_drift_report(summary, previous_summary)
        MAINTENANCE_DRIFT_JSON.write_text(json.dumps(drift, indent=2, sort_keys=True) + "\n")
        MAINTENANCE_DRIFT_MD.write_text(render_drift_markdown(drift))
        refresh_cleanup_outputs(summary, previous_cleanup_plan, previous_cleanup_history)
        apply_kind = "ds_store_clutter"
    if args.apply_pycache_clutter:
        apply_result = write_clutter_apply_result(build_pycache_apply_result(clutter_apply_dry_run, apply=True))
        clutter_payload = write_clutter_inventory()
        summary = build_summary(clutter_payload)
        summary["clutter_apply_result"] = {
            "mode": apply_result["mode"],
            "mutating": apply_result["mutating"],
            "removed_count": apply_result["removed_count"],
            "skipped_count": apply_result["skipped_count"],
            "json_path": maintenance_path(CLUTTER_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(CLUTTER_APPLY_RESULT_MD),
        }
        drift = build_drift_report(summary, previous_summary)
        MAINTENANCE_DRIFT_JSON.write_text(json.dumps(drift, indent=2, sort_keys=True) + "\n")
        MAINTENANCE_DRIFT_MD.write_text(render_drift_markdown(drift))
        refresh_cleanup_outputs(summary, previous_cleanup_plan, previous_cleanup_history)
        apply_kind = "pycache_clutter"
    if args.apply_generated_retention:
        retention_result = write_generated_artifact_retention_result(build_generated_artifact_retention_result(apply=True))
        summary["generated_artifact_retention"] = {
            "mode": retention_result["mode"],
            "mutating": retention_result["mutating"],
            "removed_count": retention_result["removed_count"],
            "protected_count": retention_result["protected_count"],
            "skipped_count": retention_result["skipped_count"],
            "json_path": maintenance_path(GENERATED_RETENTION_RESULT_JSON),
            "markdown_path": maintenance_path(GENERATED_RETENTION_RESULT_MD),
        }
        apply_kind = "generated_retention"
    if args.apply_script_archive:
        archive_apply_result = write_script_archive_apply_result(build_script_archive_apply_result(archive_dry_run, apply=True, source_path=args.archive_source_path))
        summary["script_archive_apply_result"] = {
            "mode": archive_apply_result["mode"],
            "mutating": archive_apply_result["mutating"],
            "ready_proposal_count": archive_apply_result["ready_proposal_count"],
            "archived_count": archive_apply_result["archived_count"],
            "skipped_count": archive_apply_result["skipped_count"],
            "json_path": maintenance_path(ARCHIVE_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(ARCHIVE_APPLY_RESULT_MD),
        }
        apply_kind = "script_archive"
    if apply_kind != "none":
        MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        verification = write_post_apply_verification_result(build_post_apply_verification_result(apply_kind, apply_summary_for_post_apply(apply_kind, summary)))
        summary["post_apply_verification"] = {
            "ok": verification["ok"],
            "apply_kind": verification["apply_kind"],
            "self_check_overall_status": verification["self_check"].get("overall_status"),
            "repo_health_overall_band": verification["repo_health"].get("overall_band"),
            "json_path": maintenance_path(POST_APPLY_VERIFICATION_JSON),
            "markdown_path": maintenance_path(POST_APPLY_VERIFICATION_MD),
        }
        if not verification["ok"]:
            MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            raise RuntimeError("post-apply verification failed")
    if args.post_archive_smoke:
        archive_apply_result = load_json_if_exists(ARCHIVE_APPLY_RESULT_JSON)
        smoke = write_post_archive_smoke_result(build_post_archive_smoke_result(archive_apply_result))
        summary["post_archive_smoke"] = {
            "ok": smoke["ok"],
            "mode": smoke["mode"],
            "mutating": smoke["mutating"],
            "archived_count": smoke["archive_apply_summary"].get("archived_count"),
            "check_count": len(smoke.get("checks", [])),
            "json_path": maintenance_path(POST_ARCHIVE_SMOKE_JSON),
            "markdown_path": maintenance_path(POST_ARCHIVE_SMOKE_MD),
        }
        if not smoke["ok"]:
            MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            raise RuntimeError("post-archive smoke failed")
    if args.post_delete_verification:
        delete_apply_result = load_json_if_exists(DELETE_APPLY_RESULT_JSON)
        post_delete = write_post_delete_verification_result(build_post_delete_verification_result(delete_apply_result))
        summary["post_delete_verification"] = {
            "ok": post_delete["ok"],
            "mode": post_delete["mode"],
            "mutating": post_delete["mutating"],
            "deleted_count": post_delete["deleted_count"],
            "check_count": post_delete["check_count"],
            "json_path": maintenance_path(POST_DELETE_VERIFICATION_JSON),
            "markdown_path": maintenance_path(POST_DELETE_VERIFICATION_MD),
        }
        if not post_delete["ok"]:
            MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            raise RuntimeError("post-delete verification failed")
    if args.quarantine_monitor or args.delete_readiness_report or args.delete_dry_run_report or args.apply_script_delete:
        previous_monitor = load_json_if_exists(QUARANTINE_MONITOR_JSON)
        post_archive_smoke = load_json_if_exists(POST_ARCHIVE_SMOKE_JSON)
        monitor = write_quarantine_monitor_result(build_quarantine_monitor_result(previous_monitor, post_archive_smoke))
        summary["quarantine_monitor"] = {
            "ok": monitor["ok"],
            "mode": monitor["mode"],
            "mutating": monitor["mutating"],
            "archived_script_count": monitor["archived_script_count"],
            "clean_quarantine_count": monitor["clean_quarantine_count"],
            "restore_required_count": monitor["restore_required_count"],
            "restore_blocked_count": monitor["restore_blocked_count"],
            "json_path": maintenance_path(QUARANTINE_MONITOR_JSON),
            "markdown_path": maintenance_path(QUARANTINE_MONITOR_MD),
        }
    if args.delete_readiness_report or args.delete_dry_run_report or args.apply_script_delete:
        delete_readiness = write_delete_readiness_result(build_delete_readiness_result(monitor))
        summary["delete_readiness"] = {
            "mode": delete_readiness["mode"],
            "mutating": delete_readiness["mutating"],
            "archived_script_count": delete_readiness["archived_script_count"],
            "auto_delete_ready_count": delete_readiness["auto_delete_ready_count"],
            "blocked_count": delete_readiness["blocked_count"],
            "json_path": maintenance_path(DELETE_READINESS_JSON),
            "markdown_path": maintenance_path(DELETE_READINESS_MD),
        }
    if args.delete_dry_run_report or args.apply_script_delete:
        delete_dry_run = write_delete_dry_run_result(build_delete_dry_run_result(delete_readiness))
        summary["delete_dry_run"] = {
            "mode": delete_dry_run["mode"],
            "mutating": delete_dry_run["mutating"],
            "evidence_period": delete_dry_run["evidence_period"],
            "operation_count": delete_dry_run["operation_count"],
            "excluded_count": delete_dry_run["excluded_count"],
            "json_path": maintenance_path(DELETE_DRY_RUN_JSON),
            "markdown_path": maintenance_path(DELETE_DRY_RUN_MD),
        }
    if args.apply_script_delete:
        delete_apply_result = write_script_delete_apply_result(build_script_delete_apply_result(delete_dry_run, apply=True, source_path=args.delete_source_path))
        summary["script_delete_apply_result"] = {
            "mode": delete_apply_result["mode"],
            "mutating": delete_apply_result["mutating"],
            "ready_operation_count": delete_apply_result["ready_operation_count"],
            "deleted_count": delete_apply_result["deleted_count"],
            "skipped_count": delete_apply_result["skipped_count"],
            "json_path": maintenance_path(DELETE_APPLY_RESULT_JSON),
            "markdown_path": maintenance_path(DELETE_APPLY_RESULT_MD),
        }
        apply_kind = "script_delete"
        MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        verification = write_post_apply_verification_result(build_post_apply_verification_result(apply_kind, apply_summary_for_post_apply(apply_kind, summary)))
        post_delete = write_post_delete_verification_result(build_post_delete_verification_result(delete_apply_result))
        summary["post_delete_verification"] = {
            "ok": post_delete["ok"],
            "mode": post_delete["mode"],
            "mutating": post_delete["mutating"],
            "deleted_count": post_delete["deleted_count"],
            "check_count": post_delete["check_count"],
            "json_path": maintenance_path(POST_DELETE_VERIFICATION_JSON),
            "markdown_path": maintenance_path(POST_DELETE_VERIFICATION_MD),
        }
        summary["post_apply_verification"] = {
            "ok": verification["ok"],
            "apply_kind": verification["apply_kind"],
            "self_check_overall_status": verification["self_check"].get("overall_status"),
            "repo_health_overall_band": verification["repo_health"].get("overall_band"),
            "json_path": maintenance_path(POST_APPLY_VERIFICATION_JSON),
            "markdown_path": maintenance_path(POST_APPLY_VERIFICATION_MD),
        }
        if not verification["ok"] or not post_delete["ok"]:
            MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            raise RuntimeError("post-delete apply verification failed")
    MAINTENANCE_SUMMARY_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if args.pretty:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(json.dumps({"summary": str(MAINTENANCE_SUMMARY_JSON), "drift": str(MAINTENANCE_DRIFT_JSON), "health": str(REPO_HEALTH_JSON), "cleanup_plan": str(CLEANUP_PLAN_JSON)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
