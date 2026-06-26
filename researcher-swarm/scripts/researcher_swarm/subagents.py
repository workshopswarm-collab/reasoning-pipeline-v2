"""Leaf researcher subagent coordination contracts.

This module builds spawn plans only. Actual OpenClaw session creation remains a
control-plane operation outside Researcher Swarm library code.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .assignments import validate_leaf_research_assignment

LEAF_SUBAGENT_EXECUTION_POLICY_SCHEMA_VERSION = "leaf-subagent-execution-policy/v1"
LEAF_SUBAGENT_RESULT_SCHEMA_VERSION = "leaf-subagent-result/v1"
LEAF_RESEARCH_BARRIER_SCHEMA_VERSION = "leaf-research-barrier/v1"
LEAF_SUBAGENT_POLICY_ID = "ads-leaf-subagent-execution-policy/v1"

TERMINAL_RESULT_STATUSES = {
    "accepted_classification",
    "structurally_unanswerable",
    "insufficient_evidence_blocker",
    "policy_waived_non_dispatchable",
}
BLOCKING_RESULT_STATUSES = {
    "missing",
    "active",
    "timed_out",
    "cancelled",
    "contaminated",
    "invalid_sidecar",
    "invalid_runtime_provenance",
    "launch_blocked",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def build_leaf_subagent_execution_policy(*, max_concurrent: int = 5) -> dict[str, Any]:
    if max_concurrent < 1 or max_concurrent > 5:
        raise ValueError("max_concurrent must be between 1 and 5")
    return {
        "artifact_type": "leaf_subagent_execution_policy",
        "schema_version": LEAF_SUBAGENT_EXECUTION_POLICY_SCHEMA_VERSION,
        "policy_id": LEAF_SUBAGENT_POLICY_ID,
        "max_concurrent_leaf_researchers_per_case": max_concurrent,
        "max_wall_time_seconds_per_leaf": 1200,
        "heartbeat_poll_interval_seconds": 60,
        "transient_launch_retry_budget": 1,
        "never_retry_statuses": [
            "contaminated",
            "forbidden_output",
            "invalid_sidecar",
            "invalid_runtime_provenance",
        ],
        "launch_authority": "control_plane_only",
    }


def build_leaf_researcher_spawn_plan(assignments: list[dict[str, Any]], *, max_concurrent: int = 5) -> dict[str, Any]:
    if max_concurrent < 1 or max_concurrent > 5:
        raise ValueError("max_concurrent must be between 1 and 5")
    assignment_refs: list[str] = []
    for assignment in assignments:
        validation = validate_leaf_research_assignment(assignment)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        assignment_refs.append(str(assignment["assignment_id"]))
    running_refs = assignment_refs[:max_concurrent]
    queued_refs = assignment_refs[max_concurrent:]
    return {
        "schema_version": "leaf-researcher-spawn-plan/v1",
        "runtime_owner": "ADS Researcher Swarm",
        "launch_authority": "control_plane_only",
        "execution_policy": build_leaf_subagent_execution_policy(max_concurrent=max_concurrent),
        "max_concurrent": max_concurrent,
        "assignment_refs": assignment_refs,
        "launch_queue": [
            {
                "assignment_ref": assignment_ref,
                "queue_position": idx,
                "launch_allowed": assignment_ref in running_refs,
                "queue_status": "ready_to_launch" if assignment_ref in running_refs else "queued_waiting_for_capacity",
            }
            for idx, assignment_ref in enumerate(assignment_refs)
        ],
        "queued_assignment_refs": queued_refs,
        "spawn_count": len(assignment_refs),
    }


def build_leaf_subagent_result(
    assignment: dict[str, Any],
    *,
    terminal_status: str,
    subagent_session_ref: str | None = None,
    sidecar_refs: list[str] | None = None,
    classification_refs: list[str] | None = None,
    supplemental_evidence_refs: list[str] | None = None,
    isolation_audit_ref: str | None = None,
    runtime_provenance: dict[str, Any] | None = None,
    timeout_status: str = "not_timed_out",
    cancel_status: str = "not_cancelled",
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    validation = validate_leaf_research_assignment(assignment)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    if terminal_status not in TERMINAL_RESULT_STATUSES | BLOCKING_RESULT_STATUSES:
        raise ValueError("terminal_status is invalid")
    runtime = runtime_provenance or {}
    model_executed = bool(
        runtime.get("model_executed") is True
        or (isinstance(runtime.get("runtime"), dict) and runtime["runtime"].get("model_executed") is True)
    )
    resolved_model = runtime.get("resolved_model_id") or (
        runtime.get("runtime", {}).get("resolved_model_id") if isinstance(runtime.get("runtime"), dict) else None
    )
    result = {
        "artifact_type": "leaf_subagent_result",
        "schema_version": LEAF_SUBAGENT_RESULT_SCHEMA_VERSION,
        "result_id": _sha_id(
            "leaf-subagent-result",
            {
                "assignment_id": assignment["assignment_id"],
                "terminal_status": terminal_status,
                "sidecar_refs": sidecar_refs or [],
                "session": subagent_session_ref,
            },
        ),
        "assignment_ref": assignment["assignment_id"],
        "leaf_id": assignment["leaf_id"],
        "subagent_session_ref": subagent_session_ref,
        "terminal_status": terminal_status,
        "sidecar_refs": list(sidecar_refs or []),
        "classification_refs": list(classification_refs or []),
        "proposed_supplemental_evidence_refs": list(supplemental_evidence_refs or []),
        "tool_use_summary": {"leaf_scoped_only": True, "summary_available": False},
        "timeout_status": timeout_status,
        "cancel_status": cancel_status,
        "isolation_audit_ref": isolation_audit_ref or assignment["context_isolation"]["isolation_audit_ref"],
        "runtime_provenance": copy.deepcopy(runtime),
        "model_executed": model_executed,
        "resolved_model_id": resolved_model,
        "reason_codes": list(reason_codes or []),
    }
    result["result_digest"] = "sha256:" + hashlib.sha256(_canonical_json(result).encode("utf-8")).hexdigest()
    return result


def build_leaf_research_barrier(
    assignments: list[dict[str, Any]],
    *,
    subagent_results: list[dict[str, Any]] | None = None,
    true_production_mode: bool = False,
) -> dict[str, Any]:
    results_by_assignment = {
        str(item.get("assignment_ref")): item
        for item in subagent_results or []
        if isinstance(item, dict) and _is_non_empty_string(item.get("assignment_ref"))
    }
    terminal_rows: list[dict[str, Any]] = []
    proceed = True
    for assignment in assignments:
        validation = validate_leaf_research_assignment(assignment)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        result = results_by_assignment.get(str(assignment["assignment_id"]))
        if not result:
            row = {
                "assignment_ref": assignment["assignment_id"],
                "leaf_id": assignment["leaf_id"],
                "terminal_status": "missing",
                "proceed": False,
                "reason_codes": ["missing_leaf_subagent_result"],
                "subagent_session_ref": None,
                "isolation_audit_ref": assignment["context_isolation"]["isolation_audit_ref"],
            }
            proceed = False
        else:
            status = str(result.get("terminal_status") or "missing")
            reasons = list(result.get("reason_codes") or [])
            row_proceed = status in TERMINAL_RESULT_STATUSES
            if status in BLOCKING_RESULT_STATUSES:
                row_proceed = False
                reasons.append(f"leaf_status_{status}")
            if true_production_mode:
                if result.get("model_executed") is not True:
                    row_proceed = False
                    reasons.append("true_production_requires_model_executed")
                if result.get("resolved_model_id") != "gpt-5.5-high":
                    row_proceed = False
                    reasons.append("true_production_requires_gpt_5_5_high")
            row = {
                "assignment_ref": assignment["assignment_id"],
                "leaf_id": assignment["leaf_id"],
                "terminal_status": status,
                "proceed": row_proceed,
                "reason_codes": sorted(set(reasons)),
                "subagent_session_ref": result.get("subagent_session_ref"),
                "isolation_audit_ref": result.get("isolation_audit_ref"),
                "sidecar_refs": list(result.get("sidecar_refs") or []),
                "proposed_supplemental_evidence_refs": list(result.get("proposed_supplemental_evidence_refs") or []),
            }
            proceed = proceed and row_proceed
        terminal_rows.append(row)
    seed = {
        "assignments": [assignment["assignment_id"] for assignment in assignments],
        "terminal_rows": terminal_rows,
        "true_production_mode": true_production_mode,
    }
    return {
        "artifact_type": "leaf_research_barrier",
        "schema_version": LEAF_RESEARCH_BARRIER_SCHEMA_VERSION,
        "barrier_id": _sha_id("leaf-research-barrier", seed),
        "assignment_refs": [assignment["assignment_id"] for assignment in assignments],
        "terminal_state_by_leaf": terminal_rows,
        "all_leaves_terminal": all(row["terminal_status"] in TERMINAL_RESULT_STATUSES for row in terminal_rows),
        "proceed_to_verification_scae": bool(proceed and terminal_rows),
        "blocker_reason_codes": sorted(
            {
                reason
                for row in terminal_rows
                if not row["proceed"]
                for reason in row.get("reason_codes", [])
            }
        ),
        "true_production_mode": bool(true_production_mode),
        "barrier_policy": build_leaf_subagent_execution_policy(),
    }


__all__ = [
    "LEAF_RESEARCH_BARRIER_SCHEMA_VERSION",
    "LEAF_SUBAGENT_EXECUTION_POLICY_SCHEMA_VERSION",
    "LEAF_SUBAGENT_RESULT_SCHEMA_VERSION",
    "build_leaf_research_barrier",
    "build_leaf_researcher_spawn_plan",
    "build_leaf_subagent_execution_policy",
    "build_leaf_subagent_result",
]
