#!/usr/bin/env python3
"""Shared objective-status rollups for Maintenance wrappers and self-checks."""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "maintenance-objective-status/v1"
OBJECTIVE_STATUSES = ("met", "partial", "degraded", "no_action_needed")
WRAPPER_STATUSES = ("completed", "blocked", "skipped", "running", "unknown")
SCHEDULER_STATUSES = ("healthy", "warning", "missing", "unknown")


def int_value(data: dict[str, Any], key: str) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def nested_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def list_value(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def wrapper_status_from_envelope_status(status: object) -> str:
    if status in {"ok", "degraded"}:
        return "completed"
    if status in {"blocked", "error", "failed"}:
        return "blocked"
    if status == "skipped":
        return "skipped"
    if status == "running":
        return "running"
    return "unknown"


def mutation_count_from_wrapper(wrapper_result: dict[str, Any]) -> int:
    pressure_objective = nested_dict(wrapper_result, "pressure_objective")
    changed_paths = list_value(pressure_objective, "changed_paths")
    if changed_paths:
        return len(changed_paths)
    direct = int_value(wrapper_result, "mutation_count")
    if direct:
        return direct
    destructive = destructive_action_count_from_wrapper(wrapper_result)
    if destructive:
        return destructive
    apply_result = nested_dict(wrapper_result, "apply")
    removed_blocks = int_value(apply_result, "removed_blocks")
    removed_files = int_value(apply_result, "removed_files")
    if removed_blocks or removed_files:
        return removed_blocks + removed_files
    decisions = nested_dict(wrapper_result, "decisions_consolidation")
    if decisions.get("source_mutated"):
        return 1
    delegated = nested_dict(wrapper_result, "delegated_apply")
    for key in ("archived_count", "deleted_count"):
        count = int_value(delegated, key)
        if count:
            return count
    for key in ("archived_count", "deleted_count"):
        count = int_value(wrapper_result, key)
        if count:
            return count
    return 1 if wrapper_result.get("mutating") else 0


def destructive_action_count_from_wrapper(wrapper_result: dict[str, Any]) -> int:
    direct = int_value(wrapper_result, "destructive_action_count")
    if direct:
        return direct
    delegated = nested_dict(wrapper_result, "delegated_apply")
    return (
        int_value(wrapper_result, "archived_count")
        + int_value(wrapper_result, "deleted_count")
        + int_value(delegated, "archived_count")
        + int_value(delegated, "deleted_count")
    )


def pressure_before_from_wrapper(wrapper_result: dict[str, Any]) -> dict[str, Any]:
    trigger = nested_dict(wrapper_result, "pressure_trigger")
    observed = nested_dict(trigger, "observed")
    if not observed:
        return {}
    return {
        "primary_pressure_paths": list_value(observed, "hard_budget_records"),
        "state_pressure_paths": list_value(observed, "state_json_hard_budget_records"),
        "decisions_required": bool(observed.get("decisions_autonomous_consolidation_required")),
    }


def pressure_after_from_wrapper(wrapper_result: dict[str, Any]) -> dict[str, Any]:
    pressure_objective = nested_dict(wrapper_result, "pressure_objective")
    if not pressure_objective:
        return {}
    return {
        "hard_budget_met": bool(pressure_objective.get("hard_budget_met")),
        "remaining_hard_budget_paths": list_value(pressure_objective, "remaining_hard_budget_paths"),
        "remaining_decisions_hard_budget_paths": list_value(pressure_objective, "remaining_decisions_hard_budget_paths"),
    }


def backlog_before_from_wrapper(wrapper_result: dict[str, Any]) -> dict[str, Any]:
    trigger = nested_dict(wrapper_result, "pressure_trigger")
    observed = nested_dict(trigger, "observed")
    if not observed:
        return {}
    return {
        "decisions_required": bool(observed.get("decisions_autonomous_consolidation_required")),
    }


def backlog_after_from_wrapper(wrapper_result: dict[str, Any]) -> dict[str, Any]:
    decisions = nested_dict(wrapper_result, "decisions_consolidation")
    backlog = nested_dict(decisions, "decisions_backlog")
    if not backlog:
        return {}
    return {
        "status": backlog.get("status"),
        "reason": backlog.get("reason"),
        "repeated_count": int_value(backlog, "repeated_count"),
        "safe_candidates": int_value(backlog, "safe_candidates"),
        "recommended_action": backlog.get("recommended_action"),
    }


def remaining_blockers_from_wrapper(wrapper_result: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    pressure_objective = nested_dict(wrapper_result, "pressure_objective")
    for path in list_value(pressure_objective, "remaining_hard_budget_paths"):
        blockers.append(f"remaining_pressure:{path}")
    if pressure_objective.get("primary_target_unresolved"):
        blockers.append("primary_target_unresolved")
    decisions = nested_dict(wrapper_result, "decisions_consolidation")
    backlog = nested_dict(decisions, "decisions_backlog")
    if backlog.get("status") == "review_required":
        blockers.append(f"decisions_backlog:{backlog.get('reason') or 'review_required'}")
    blocked_reason = wrapper_result.get("blocked_reason")
    if blocked_reason:
        blockers.append(f"blocked_reason:{blocked_reason}")
    if wrapper_result.get("ok") is False:
        blockers.append("wrapper_not_ok")
    return sorted(set(str(item) for item in blockers if item))


def backlog_reduced(wrapper_result: dict[str, Any]) -> bool:
    backlog = backlog_after_from_wrapper(wrapper_result)
    if backlog.get("status") == "resolved":
        return True
    delegated = nested_dict(wrapper_result, "delegated_apply")
    return any(int_value(container, key) > 0 for container in (wrapper_result, delegated) for key in ("archived_count", "deleted_count"))


def objective_status_from_wrapper(wrapper_result: dict[str, Any]) -> str:
    pressure_objective = nested_dict(wrapper_result, "pressure_objective")
    remaining_blockers = remaining_blockers_from_wrapper(wrapper_result)
    changed_anything = mutation_count_from_wrapper(wrapper_result) > 0
    if pressure_objective.get("hard_budget_met") is True or backlog_reduced(wrapper_result):
        return "met"
    if changed_anything and remaining_blockers:
        return "partial"
    if remaining_blockers:
        return "degraded"
    if wrapper_result.get("status") in {"blocked", "error", "failed"} or wrapper_result.get("ok") is False:
        return "degraded"
    return "no_action_needed"


def build_objective_rollup(
    *,
    plane: str,
    wrapper_result: dict[str, Any] | None = None,
    scheduler_status: str = "unknown",
    wrapper_status: str = "unknown",
    generated_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    result = wrapper_result if isinstance(wrapper_result, dict) else {}
    objective_status = objective_status_from_wrapper(result) if result else "no_action_needed"
    if wrapper_status == "blocked":
        objective_status = "degraded"
    return {
        "schema_version": SCHEMA_VERSION,
        "plane": plane,
        "scheduler_status": scheduler_status if scheduler_status in SCHEDULER_STATUSES else "unknown",
        "wrapper_status": wrapper_status if wrapper_status in WRAPPER_STATUSES else "unknown",
        "objective_status": objective_status,
        "mutation_count": mutation_count_from_wrapper(result),
        "pressure_before": pressure_before_from_wrapper(result),
        "pressure_after": pressure_after_from_wrapper(result),
        "backlog_before": backlog_before_from_wrapper(result),
        "backlog_after": backlog_after_from_wrapper(result),
        "destructive_action_count": destructive_action_count_from_wrapper(result),
        "degraded_reasons": remaining_blockers_from_wrapper(result),
        "generated_artifacts": generated_artifacts or [],
    }
