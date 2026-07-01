"""Leaf researcher subagent coordination contracts.

This module builds spawn plans only. Actual OpenClaw session creation remains a
control-plane operation outside Researcher Swarm library code.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .assignments import (
    ASSIGNMENT_ALLOWED_EVIDENCE_TRANSPORTS,
    ASSIGNMENT_FORBIDDEN_RETRIEVAL_TRANSPORTS,
    validate_leaf_research_assignment,
)
from .classification import (
    validate_researcher_sidecar_against_retrieval_packet,
    validate_researcher_sidecar_v2,
)
from .isolation import validate_researcher_context_isolation_audit
from .model_context import RESEARCHER_PROVIDER_MODEL_KEY

LEAF_SUBAGENT_EXECUTION_POLICY_SCHEMA_VERSION = "leaf-subagent-execution-policy/v1"
LEAF_SUBAGENT_RESULT_SCHEMA_VERSION = "leaf-subagent-result/v1"
LEAF_RESEARCH_BARRIER_SCHEMA_VERSION = "leaf-research-barrier/v1"
RESEARCHER_SWARM_RUNTIME_BUNDLE_SCHEMA_VERSION = "researcher-swarm-runtime-bundle/v1"
LEAF_SUBAGENT_POLICY_ID = "ads-leaf-subagent-execution-policy/v1"
LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF = "openclaw-control-plane-subagent-adapter/v1"
LEAF_SUBAGENT_CONTRACT_VALIDATOR_VERSION = "ads-phase-2-leaf-subagent-contract/v1"

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
TRANSIENT_RETRY_STATUSES = {"missing", "active", "timed_out", "cancelled", "launch_blocked"}
NEVER_RETRY_STATUSES = {
    "contaminated",
    "forbidden_output",
    "invalid_sidecar",
    "invalid_runtime_provenance",
}
ALLOWED_TIMEOUT_STATUSES = {"not_timed_out", "timed_out"}
ALLOWED_CANCEL_STATUSES = {"not_cancelled", "cancelled"}


@dataclass(frozen=True)
class LeafSubagentContractValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": LEAF_SUBAGENT_CONTRACT_VALIDATOR_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256_ref(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(item)]


def _validate_string_list(value: Any, field: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(_is_non_empty_string(item) for item in value):
        errors.append(f"{field} must be a string list")
        return []
    return [str(item) for item in value]


def _validate_classifier_only_follow_up(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return
    for quota in ("max_direct_url_fetches", "max_native_candidate_urls", "max_supplemental_evidence_refs"):
        if value.get(quota) != 0:
            errors.append(f"{field}.{quota} must be 0")
    transports = _validate_string_list(value.get("allowed_transports"), f"{field}.allowed_transports", errors)
    if set(transports) != ASSIGNMENT_ALLOWED_EVIDENCE_TRANSPORTS:
        errors.append(f"{field}.allowed_transports must be assigned evidence and certified snippet artifacts only")
    forbidden = sorted(set(transports) & ASSIGNMENT_FORBIDDEN_RETRIEVAL_TRANSPORTS)
    if forbidden:
        errors.append(f"{field}.allowed_transports includes forbidden retrieval transports: " + ", ".join(forbidden))
    if value.get("retrieval_expansion_authority") != "upstream_retrieval_only":
        errors.append(f"{field}.retrieval_expansion_authority must be upstream_retrieval_only")


def _result_digest_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(result)
    payload.pop("result_digest", None)
    return payload


def compute_leaf_subagent_result_digest(result: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_result_digest_payload(result)).encode("utf-8")).hexdigest()


def _barrier_digest_payload(barrier: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(barrier)
    payload.pop("barrier_digest", None)
    return payload


def compute_leaf_research_barrier_digest(barrier: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_barrier_digest_payload(barrier)).encode("utf-8")).hexdigest()


def _retry_state_for_status(status: str, *, attempt_index: int = 0, max_retries: int = 1) -> dict[str, Any]:
    retry_eligible = status in TRANSIENT_RETRY_STATUSES and attempt_index < max_retries
    retry_blockers: list[str] = []
    if status in NEVER_RETRY_STATUSES:
        retry_blockers.append(f"never_retry_status_{status}")
    if attempt_index >= max_retries and status in TRANSIENT_RETRY_STATUSES:
        retry_blockers.append("transient_retry_budget_exhausted")
    return {
        "attempt_index": attempt_index,
        "max_retries": max_retries,
        "retry_eligible": retry_eligible,
        "retry_blocked_reason_codes": retry_blockers,
    }


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
        "never_retry_statuses": sorted(NEVER_RETRY_STATUSES),
        "launch_authority": "control_plane_only",
        "control_plane_adapter_ref": LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF,
        "required_runtime_provider_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
        "leaf_scoped_follow_up_research_allowed": False,
        "retrieval_expansion_authority": "upstream_retrieval_only",
        "researcher_runtime_role": "classifier_only",
        "supplemental_evidence_resolver_required": True,
    }


def validate_leaf_subagent_execution_policy(policy: Any) -> LeafSubagentContractValidationResult:
    errors: list[str] = []
    if not isinstance(policy, dict):
        return LeafSubagentContractValidationResult(False, ("policy must be an object",))
    expected_values = {
        "artifact_type": "leaf_subagent_execution_policy",
        "schema_version": LEAF_SUBAGENT_EXECUTION_POLICY_SCHEMA_VERSION,
        "policy_id": LEAF_SUBAGENT_POLICY_ID,
        "launch_authority": "control_plane_only",
    }
    for field, expected in expected_values.items():
        if policy.get(field) != expected:
            errors.append(f"{field} must be {expected}")
    max_concurrent = policy.get("max_concurrent_leaf_researchers_per_case")
    if not isinstance(max_concurrent, int) or isinstance(max_concurrent, bool) or not 1 <= max_concurrent <= 5:
        errors.append("max_concurrent_leaf_researchers_per_case must be an integer between 1 and 5")
    if policy.get("max_wall_time_seconds_per_leaf") != 1200:
        errors.append("max_wall_time_seconds_per_leaf must be 1200")
    if policy.get("heartbeat_poll_interval_seconds") != 60:
        errors.append("heartbeat_poll_interval_seconds must be 60")
    if policy.get("transient_launch_retry_budget") != 1:
        errors.append("transient_launch_retry_budget must be 1")
    if policy.get("never_retry_statuses") != sorted(NEVER_RETRY_STATUSES):
        errors.append("never_retry_statuses does not match Phase 2 policy")
    if policy.get("control_plane_adapter_ref") != LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF:
        errors.append(f"control_plane_adapter_ref must be {LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF}")
    if policy.get("required_runtime_provider_model_id") != RESEARCHER_PROVIDER_MODEL_KEY:
        errors.append(f"required_runtime_provider_model_id must be {RESEARCHER_PROVIDER_MODEL_KEY}")
    if policy.get("leaf_scoped_follow_up_research_allowed") is not False:
        errors.append("leaf_scoped_follow_up_research_allowed must be false")
    if policy.get("retrieval_expansion_authority") != "upstream_retrieval_only":
        errors.append("retrieval_expansion_authority must be upstream_retrieval_only")
    if policy.get("researcher_runtime_role") != "classifier_only":
        errors.append("researcher_runtime_role must be classifier_only")
    if policy.get("supplemental_evidence_resolver_required") is not True:
        errors.append("supplemental_evidence_resolver_required must be true")
    return LeafSubagentContractValidationResult(not errors, tuple(errors))


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
    policy = build_leaf_subagent_execution_policy(max_concurrent=max_concurrent)
    plan = {
        "schema_version": "leaf-researcher-spawn-plan/v1",
        "runtime_owner": "ADS Researcher Swarm",
        "launch_authority": "control_plane_only",
        "execution_policy": policy,
        "max_concurrent": max_concurrent,
        "assignment_refs": assignment_refs,
        "launch_queue": [
            {
                "assignment_ref": assignment_ref,
                "queue_position": idx,
                "launch_allowed": assignment_ref in running_refs,
                "queue_status": "ready_to_launch" if assignment_ref in running_refs else "queued_waiting_for_capacity",
                "launch_block_reason_codes": [] if assignment_ref in running_refs else ["queued_waiting_for_capacity"],
                "subagent_session_ref": None,
                "control_plane_adapter_ref": LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF,
                "required_runtime_provider_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
                "assignment_input_ref": assignment_ref,
                "leaf_scoped_follow_up_research": copy.deepcopy(
                    assignment.get("budget", {}).get("follow_up_research", {})
                ),
                "timeout_state": {
                    "max_wall_time_seconds": policy["max_wall_time_seconds_per_leaf"],
                    "heartbeat_poll_interval_seconds": policy["heartbeat_poll_interval_seconds"],
                },
                "retry_state": _retry_state_for_status(
                    "launch_blocked" if assignment_ref in queued_refs else "active",
                    attempt_index=0,
                    max_retries=policy["transient_launch_retry_budget"],
                ),
            }
            for idx, assignment_ref in enumerate(assignment_refs)
        ],
        "queued_assignment_refs": queued_refs,
        "spawn_count": len(assignment_refs),
    }
    return plan


def validate_leaf_researcher_spawn_plan(
    plan: Any,
    assignments: list[dict[str, Any]] | None = None,
) -> LeafSubagentContractValidationResult:
    errors: list[str] = []
    if not isinstance(plan, dict):
        return LeafSubagentContractValidationResult(False, ("spawn plan must be an object",))
    if plan.get("schema_version") != "leaf-researcher-spawn-plan/v1":
        errors.append("schema_version must be leaf-researcher-spawn-plan/v1")
    if plan.get("runtime_owner") != "ADS Researcher Swarm":
        errors.append("runtime_owner must be ADS Researcher Swarm")
    if plan.get("launch_authority") != "control_plane_only":
        errors.append("launch_authority must be control_plane_only")
    policy = plan.get("execution_policy")
    policy_validation = validate_leaf_subagent_execution_policy(policy)
    if not policy_validation.valid:
        errors.extend(f"execution_policy.{error}" for error in policy_validation.errors)
    max_concurrent = plan.get("max_concurrent")
    if not isinstance(max_concurrent, int) or isinstance(max_concurrent, bool) or not 1 <= max_concurrent <= 5:
        errors.append("max_concurrent must be an integer between 1 and 5")
        max_concurrent = 0
    assignment_refs = _validate_string_list(plan.get("assignment_refs"), "assignment_refs", errors)
    if assignments is not None:
        expected_refs: list[str] = []
        for assignment in assignments:
            validation = validate_leaf_research_assignment(assignment)
            if not validation.valid:
                errors.extend(f"assignment.{error}" for error in validation.errors)
            elif _is_non_empty_string(assignment.get("assignment_id")):
                expected_refs.append(str(assignment["assignment_id"]))
        if assignment_refs != expected_refs:
            errors.append("assignment_refs must match validated assignments")
    if len(set(assignment_refs)) != len(assignment_refs):
        errors.append("assignment_refs must be unique")
    if plan.get("spawn_count") != len(assignment_refs):
        errors.append("spawn_count must match assignment_refs")
    queued_assignment_refs = _validate_string_list(plan.get("queued_assignment_refs"), "queued_assignment_refs", errors)
    expected_queued_refs = assignment_refs[max_concurrent:] if max_concurrent else []
    if queued_assignment_refs != expected_queued_refs:
        errors.append("queued_assignment_refs must match assignments over the concurrency cap")

    launch_queue = plan.get("launch_queue")
    if not isinstance(launch_queue, list):
        errors.append("launch_queue must be a list")
        launch_queue = []
    if len(launch_queue) != len(assignment_refs):
        errors.append("launch_queue must have one row per assignment")
    for idx, row in enumerate(launch_queue):
        if not isinstance(row, dict):
            errors.append(f"launch_queue[{idx}] must be an object")
            continue
        expected_ref = assignment_refs[idx] if idx < len(assignment_refs) else None
        if row.get("assignment_ref") != expected_ref:
            errors.append(f"launch_queue[{idx}].assignment_ref must match assignment_refs order")
        if row.get("queue_position") != idx:
            errors.append(f"launch_queue[{idx}].queue_position must be {idx}")
        launch_allowed = row.get("launch_allowed")
        expected_launch_allowed = idx < max_concurrent
        if launch_allowed is not True and launch_allowed is not False:
            errors.append(f"launch_queue[{idx}].launch_allowed must be a boolean")
        elif launch_allowed != expected_launch_allowed:
            errors.append(f"launch_queue[{idx}].launch_allowed must reflect the concurrency cap")
        expected_status = "ready_to_launch" if expected_launch_allowed else "queued_waiting_for_capacity"
        if row.get("queue_status") != expected_status:
            errors.append(f"launch_queue[{idx}].queue_status must be {expected_status}")
        reason_codes = _validate_string_list(
            row.get("launch_block_reason_codes"),
            f"launch_queue[{idx}].launch_block_reason_codes",
            errors,
        )
        if launch_allowed is True and reason_codes:
            errors.append(f"launch_queue[{idx}] cannot launch with launch_block_reason_codes")
        if launch_allowed is False and not reason_codes:
            errors.append(f"launch_queue[{idx}] must explain why launch is blocked")
        if row.get("subagent_session_ref") is not None:
            errors.append(f"launch_queue[{idx}].subagent_session_ref must be null before control-plane launch")
        if row.get("control_plane_adapter_ref") != LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF:
            errors.append(
                f"launch_queue[{idx}].control_plane_adapter_ref must be {LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF}"
            )
        if row.get("required_runtime_provider_model_id") != RESEARCHER_PROVIDER_MODEL_KEY:
            errors.append(
                f"launch_queue[{idx}].required_runtime_provider_model_id must be {RESEARCHER_PROVIDER_MODEL_KEY}"
            )
        if row.get("assignment_input_ref") != expected_ref:
            errors.append(f"launch_queue[{idx}].assignment_input_ref must match assignment_ref")
        _validate_classifier_only_follow_up(
            row.get("leaf_scoped_follow_up_research"),
            f"launch_queue[{idx}].leaf_scoped_follow_up_research",
            errors,
        )
        timeout_state = row.get("timeout_state")
        if not isinstance(timeout_state, dict):
            errors.append(f"launch_queue[{idx}].timeout_state must be an object")
        else:
            if timeout_state.get("max_wall_time_seconds") != 1200:
                errors.append(f"launch_queue[{idx}].timeout_state.max_wall_time_seconds must be 1200")
            if timeout_state.get("heartbeat_poll_interval_seconds") != 60:
                errors.append(f"launch_queue[{idx}].timeout_state.heartbeat_poll_interval_seconds must be 60")
        retry_state = row.get("retry_state")
        if not isinstance(retry_state, dict):
            errors.append(f"launch_queue[{idx}].retry_state must be an object")
        else:
            if retry_state.get("max_retries") != 1:
                errors.append(f"launch_queue[{idx}].retry_state.max_retries must be 1")
            if not isinstance(retry_state.get("retry_eligible"), bool):
                errors.append(f"launch_queue[{idx}].retry_state.retry_eligible must be a boolean")
    return LeafSubagentContractValidationResult(not errors, tuple(errors))


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
    attempt_index: int = 0,
    tool_use_summary: dict[str, Any] | None = None,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    validation = validate_leaf_research_assignment(assignment)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    if terminal_status not in TERMINAL_RESULT_STATUSES | BLOCKING_RESULT_STATUSES:
        raise ValueError("terminal_status is invalid")
    if not _is_non_empty_string(subagent_session_ref):
        raise ValueError("subagent_session_ref is required for leaf subagent results")
    if timeout_status not in ALLOWED_TIMEOUT_STATUSES:
        raise ValueError("timeout_status is invalid")
    if cancel_status not in ALLOWED_CANCEL_STATUSES:
        raise ValueError("cancel_status is invalid")
    if attempt_index < 0:
        raise ValueError("attempt_index must be non-negative")
    runtime = runtime_provenance or {}
    model_executed = bool(
        runtime.get("model_executed") is True
        or (isinstance(runtime.get("runtime"), dict) and runtime["runtime"].get("model_executed") is True)
    )
    resolved_model = runtime.get("resolved_model_id") or (
        runtime.get("runtime", {}).get("resolved_model_id") if isinstance(runtime.get("runtime"), dict) else None
    )
    summary = copy.deepcopy(tool_use_summary or {})
    summary.setdefault("leaf_scoped_only", True)
    summary.setdefault("approved_transports_only", True)
    summary.setdefault("candidate_supplemental_evidence_requires_resolver_admission", True)
    summary.setdefault("retrieval_expansion_performed", False)
    summary.setdefault("free_browsing_performed", False)
    summary.setdefault("browser_search_performed", False)
    summary.setdefault("summary_available", False)
    policy = build_leaf_subagent_execution_policy()
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
        "tool_use_summary": summary,
        "timeout_status": timeout_status,
        "cancel_status": cancel_status,
        "isolation_audit_ref": isolation_audit_ref or assignment["context_isolation"]["isolation_audit_ref"],
        "runtime_provenance": copy.deepcopy(runtime),
        "model_executed": model_executed,
        "resolved_model_id": resolved_model,
        "retry_state": _retry_state_for_status(
            terminal_status,
            attempt_index=attempt_index,
            max_retries=policy["transient_launch_retry_budget"],
        ),
        "reason_codes": list(reason_codes or []),
    }
    result["result_digest"] = compute_leaf_subagent_result_digest(result)
    return result


def validate_leaf_subagent_result(
    result: Any,
    *,
    assignment: dict[str, Any] | None = None,
    true_production_mode: bool = False,
) -> LeafSubagentContractValidationResult:
    errors: list[str] = []
    if not isinstance(result, dict):
        return LeafSubagentContractValidationResult(False, ("result must be an object",))
    expected_values = {
        "artifact_type": "leaf_subagent_result",
        "schema_version": LEAF_SUBAGENT_RESULT_SCHEMA_VERSION,
    }
    for field, expected in expected_values.items():
        if result.get(field) != expected:
            errors.append(f"{field} must be {expected}")
    for field in ("result_id", "assignment_ref", "leaf_id", "subagent_session_ref", "isolation_audit_ref"):
        if not _is_non_empty_string(result.get(field)):
            errors.append(f"{field} is required")
    status = result.get("terminal_status")
    if status not in TERMINAL_RESULT_STATUSES | BLOCKING_RESULT_STATUSES:
        errors.append("terminal_status is invalid")
        status = "invalid_sidecar"
    sidecar_refs = _validate_string_list(result.get("sidecar_refs"), "sidecar_refs", errors)
    classification_refs = _validate_string_list(result.get("classification_refs"), "classification_refs", errors)
    _validate_string_list(
        result.get("proposed_supplemental_evidence_refs"),
        "proposed_supplemental_evidence_refs",
        errors,
    )
    reason_codes = _validate_string_list(result.get("reason_codes"), "reason_codes", errors)
    if len(set(reason_codes)) != len(reason_codes):
        errors.append("reason_codes must be unique")
    if result.get("timeout_status") not in ALLOWED_TIMEOUT_STATUSES:
        errors.append("timeout_status is invalid")
    if result.get("cancel_status") not in ALLOWED_CANCEL_STATUSES:
        errors.append("cancel_status is invalid")
    if status == "timed_out" and result.get("timeout_status") != "timed_out":
        errors.append("timed_out terminal_status requires timeout_status=timed_out")
    if status == "cancelled" and result.get("cancel_status") != "cancelled":
        errors.append("cancelled terminal_status requires cancel_status=cancelled")
    if status == "accepted_classification":
        if not sidecar_refs:
            errors.append("accepted_classification requires sidecar_refs")
        if not classification_refs:
            errors.append("accepted_classification requires classification_refs")
        if result.get("timeout_status") != "not_timed_out":
            errors.append("accepted_classification cannot be timed out")
        if result.get("cancel_status") != "not_cancelled":
            errors.append("accepted_classification cannot be cancelled")
    tool_use_summary = result.get("tool_use_summary")
    if not isinstance(tool_use_summary, dict):
        errors.append("tool_use_summary must be an object")
    else:
        if tool_use_summary.get("leaf_scoped_only") is not True:
            errors.append("tool_use_summary.leaf_scoped_only must be true")
        if tool_use_summary.get("approved_transports_only") is not True:
            errors.append("tool_use_summary.approved_transports_only must be true")
        if tool_use_summary.get("candidate_supplemental_evidence_requires_resolver_admission") is not True:
            errors.append(
                "tool_use_summary.candidate_supplemental_evidence_requires_resolver_admission must be true"
            )
        if tool_use_summary.get("retrieval_expansion_performed") is not False:
            errors.append("tool_use_summary.retrieval_expansion_performed must be false")
        if tool_use_summary.get("free_browsing_performed") is not False:
            errors.append("tool_use_summary.free_browsing_performed must be false")
        if tool_use_summary.get("browser_search_performed") is not False:
            errors.append("tool_use_summary.browser_search_performed must be false")
    if not isinstance(result.get("runtime_provenance"), dict):
        errors.append("runtime_provenance must be an object")
    if result.get("model_executed") is not True and result.get("model_executed") is not False:
        errors.append("model_executed must be a boolean")
    if result.get("resolved_model_id") is not None and not _is_non_empty_string(result.get("resolved_model_id")):
        errors.append("resolved_model_id must be a non-empty string or null")
    if true_production_mode:
        if result.get("model_executed") is not True:
            errors.append("true production requires model_executed=true")
        if result.get("resolved_model_id") != RESEARCHER_PROVIDER_MODEL_KEY:
            errors.append(f"true production requires resolved_model_id={RESEARCHER_PROVIDER_MODEL_KEY}")
    retry_state = result.get("retry_state")
    if not isinstance(retry_state, dict):
        errors.append("retry_state must be an object")
    else:
        if not isinstance(retry_state.get("attempt_index"), int) or isinstance(retry_state.get("attempt_index"), bool):
            errors.append("retry_state.attempt_index must be an integer")
        if retry_state.get("max_retries") != 1:
            errors.append("retry_state.max_retries must be 1")
        if not isinstance(retry_state.get("retry_eligible"), bool):
            errors.append("retry_state.retry_eligible must be a boolean")
        _validate_string_list(
            retry_state.get("retry_blocked_reason_codes"),
            "retry_state.retry_blocked_reason_codes",
            errors,
        )
    digest = result.get("result_digest")
    if not _is_sha256_ref(digest):
        errors.append("result_digest must be a sha256 ref")
    elif digest != compute_leaf_subagent_result_digest(result):
        errors.append("result_digest does not match result payload")
    if assignment is not None:
        if not isinstance(assignment, dict):
            errors.append("assignment must be an object when provided")
        else:
            assignment_validation = validate_leaf_research_assignment(assignment)
            if not assignment_validation.valid:
                errors.extend(f"assignment.{error}" for error in assignment_validation.errors)
            if result.get("assignment_ref") != assignment.get("assignment_id"):
                errors.append("assignment_ref must match assignment")
            if result.get("leaf_id") != assignment.get("leaf_id"):
                errors.append("leaf_id must match assignment")
            expected_audit_ref = assignment.get("context_isolation", {}).get("isolation_audit_ref")
            if result.get("isolation_audit_ref") != expected_audit_ref:
                errors.append("isolation_audit_ref must match assignment")
    return LeafSubagentContractValidationResult(not errors, tuple(errors))


def build_leaf_research_barrier(
    assignments: list[dict[str, Any]],
    *,
    subagent_results: list[dict[str, Any]] | None = None,
    true_production_mode: bool = False,
) -> dict[str, Any]:
    assignment_by_ref: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        validation = validate_leaf_research_assignment(assignment)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        assignment_by_ref[str(assignment["assignment_id"])] = assignment
    policy = build_leaf_subagent_execution_policy()
    results_by_assignment: dict[str, dict[str, Any]] = {}
    global_reason_codes: list[str] = []
    result_validation_errors: list[dict[str, Any]] = []
    for idx, item in enumerate(subagent_results or []):
        if not isinstance(item, dict):
            global_reason_codes.append("invalid_leaf_subagent_result")
            result_validation_errors.append({"result_index": idx, "errors": ["result must be an object"]})
            continue
        assignment_ref = item.get("assignment_ref")
        if not _is_non_empty_string(assignment_ref):
            global_reason_codes.append("invalid_leaf_subagent_result")
            result_validation_errors.append({"result_index": idx, "errors": ["assignment_ref is required"]})
            continue
        assignment_ref = str(assignment_ref)
        if assignment_ref not in assignment_by_ref:
            global_reason_codes.append("unknown_leaf_subagent_result")
            result_validation_errors.append({"result_index": idx, "assignment_ref": assignment_ref, "errors": ["unknown assignment_ref"]})
            continue
        if assignment_ref in results_by_assignment:
            global_reason_codes.append("duplicate_leaf_subagent_result")
            result_validation_errors.append({"result_index": idx, "assignment_ref": assignment_ref, "errors": ["duplicate assignment_ref"]})
            continue
        validation = validate_leaf_subagent_result(
            item,
            assignment=assignment_by_ref[assignment_ref],
            true_production_mode=true_production_mode,
        )
        if not validation.valid:
            global_reason_codes.append("invalid_leaf_subagent_result")
            result_validation_errors.append(
                {
                    "result_index": idx,
                    "assignment_ref": assignment_ref,
                    "errors": list(validation.errors),
                }
            )
        results_by_assignment[assignment_ref] = item
    terminal_rows: list[dict[str, Any]] = []
    proceed = not global_reason_codes
    for assignment in assignments:
        result = results_by_assignment.get(str(assignment["assignment_id"]))
        if not result:
            retry_state = _retry_state_for_status(
                "missing",
                attempt_index=0,
                max_retries=policy["transient_launch_retry_budget"],
            )
            row = {
                "assignment_ref": assignment["assignment_id"],
                "leaf_id": assignment["leaf_id"],
                "terminal_status": "missing",
                "proceed": False,
                "reason_codes": ["missing_leaf_subagent_result"],
                "subagent_session_ref": None,
                "isolation_audit_ref": assignment["context_isolation"]["isolation_audit_ref"],
                "timeout_status": "not_timed_out",
                "cancel_status": "not_cancelled",
                "retry_state": retry_state,
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
                if result.get("resolved_model_id") != RESEARCHER_PROVIDER_MODEL_KEY:
                    row_proceed = False
                    reasons.append("true_production_requires_openai_gpt_5_5_high")
            result_validation = validate_leaf_subagent_result(
                result,
                assignment=assignment,
                true_production_mode=true_production_mode,
            )
            if not result_validation.valid:
                row_proceed = False
                reasons.append("invalid_leaf_subagent_result")
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
                "timeout_status": result.get("timeout_status"),
                "cancel_status": result.get("cancel_status"),
                "retry_state": result.get("retry_state"),
            }
            proceed = proceed and row_proceed
        terminal_rows.append(row)
    seed = {
        "assignments": [assignment["assignment_id"] for assignment in assignments],
        "terminal_rows": terminal_rows,
        "true_production_mode": true_production_mode,
    }
    barrier = {
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
                for reason in global_reason_codes
            }
            | {
                reason
                for row in terminal_rows
                if not row["proceed"]
                for reason in row.get("reason_codes", [])
            }
        ),
        "result_validation_errors": result_validation_errors,
        "true_production_mode": bool(true_production_mode),
        "barrier_policy": policy,
    }
    barrier["barrier_digest"] = compute_leaf_research_barrier_digest(barrier)
    return barrier


def validate_leaf_research_barrier(
    barrier: Any,
    *,
    assignments: list[dict[str, Any]] | None = None,
    true_production_mode: bool | None = None,
) -> LeafSubagentContractValidationResult:
    errors: list[str] = []
    if not isinstance(barrier, dict):
        return LeafSubagentContractValidationResult(False, ("barrier must be an object",))
    if barrier.get("artifact_type") != "leaf_research_barrier":
        errors.append("artifact_type must be leaf_research_barrier")
    if barrier.get("schema_version") != LEAF_RESEARCH_BARRIER_SCHEMA_VERSION:
        errors.append(f"schema_version must be {LEAF_RESEARCH_BARRIER_SCHEMA_VERSION}")
    if not _is_non_empty_string(barrier.get("barrier_id")):
        errors.append("barrier_id is required")
    assignment_refs = _validate_string_list(barrier.get("assignment_refs"), "assignment_refs", errors)
    if len(set(assignment_refs)) != len(assignment_refs):
        errors.append("assignment_refs must be unique")
    if assignments is not None:
        expected_refs: list[str] = []
        for assignment in assignments:
            validation = validate_leaf_research_assignment(assignment)
            if not validation.valid:
                errors.extend(f"assignment.{error}" for error in validation.errors)
            elif _is_non_empty_string(assignment.get("assignment_id")):
                expected_refs.append(str(assignment["assignment_id"]))
        if assignment_refs != expected_refs:
            errors.append("assignment_refs must match validated assignments")
    policy_validation = validate_leaf_subagent_execution_policy(barrier.get("barrier_policy"))
    if not policy_validation.valid:
        errors.extend(f"barrier_policy.{error}" for error in policy_validation.errors)
    terminal_rows = barrier.get("terminal_state_by_leaf")
    if not isinstance(terminal_rows, list):
        errors.append("terminal_state_by_leaf must be a list")
        terminal_rows = []
    if len(terminal_rows) != len(assignment_refs):
        errors.append("terminal_state_by_leaf must have one row per assignment")
    row_proceed_values: list[bool] = []
    row_terminal_values: list[bool] = []
    for idx, row in enumerate(terminal_rows):
        if not isinstance(row, dict):
            errors.append(f"terminal_state_by_leaf[{idx}] must be an object")
            row_proceed_values.append(False)
            row_terminal_values.append(False)
            continue
        expected_ref = assignment_refs[idx] if idx < len(assignment_refs) else None
        if row.get("assignment_ref") != expected_ref:
            errors.append(f"terminal_state_by_leaf[{idx}].assignment_ref must match assignment_refs order")
        if not _is_non_empty_string(row.get("leaf_id")):
            errors.append(f"terminal_state_by_leaf[{idx}].leaf_id is required")
        status = row.get("terminal_status")
        if status not in TERMINAL_RESULT_STATUSES | BLOCKING_RESULT_STATUSES | {"missing"}:
            errors.append(f"terminal_state_by_leaf[{idx}].terminal_status is invalid")
            status = "invalid_sidecar"
        if row.get("proceed") is not True and row.get("proceed") is not False:
            errors.append(f"terminal_state_by_leaf[{idx}].proceed must be a boolean")
            row_proceed = False
        else:
            row_proceed = bool(row.get("proceed"))
        row_proceed_values.append(row_proceed)
        row_terminal_values.append(status in TERMINAL_RESULT_STATUSES)
        _validate_string_list(row.get("reason_codes"), f"terminal_state_by_leaf[{idx}].reason_codes", errors)
        if status in BLOCKING_RESULT_STATUSES | {"missing"} and row_proceed:
            errors.append(f"terminal_state_by_leaf[{idx}] cannot proceed with blocking status")
        if row_proceed and status not in TERMINAL_RESULT_STATUSES:
            errors.append(f"terminal_state_by_leaf[{idx}] cannot proceed without terminal status")
        if row.get("subagent_session_ref") is not None and not _is_non_empty_string(row.get("subagent_session_ref")):
            errors.append(f"terminal_state_by_leaf[{idx}].subagent_session_ref must be a string or null")
        if not _is_non_empty_string(row.get("isolation_audit_ref")):
            errors.append(f"terminal_state_by_leaf[{idx}].isolation_audit_ref is required")
        if row.get("timeout_status") not in ALLOWED_TIMEOUT_STATUSES:
            errors.append(f"terminal_state_by_leaf[{idx}].timeout_status is invalid")
        if row.get("cancel_status") not in ALLOWED_CANCEL_STATUSES:
            errors.append(f"terminal_state_by_leaf[{idx}].cancel_status is invalid")
        if not isinstance(row.get("retry_state"), dict):
            errors.append(f"terminal_state_by_leaf[{idx}].retry_state must be an object")
    expected_all_terminal = bool(terminal_rows) and all(row_terminal_values)
    if barrier.get("all_leaves_terminal") != expected_all_terminal:
        errors.append("all_leaves_terminal does not match terminal rows")
    blocker_reason_codes = _validate_string_list(barrier.get("blocker_reason_codes"), "blocker_reason_codes", errors)
    expected_proceed = bool(terminal_rows) and all(row_proceed_values) and not blocker_reason_codes
    if barrier.get("proceed_to_verification_scae") != expected_proceed:
        errors.append("proceed_to_verification_scae does not match terminal rows and blockers")
    if true_production_mode is not None and barrier.get("true_production_mode") is not bool(true_production_mode):
        errors.append("true_production_mode does not match expected mode")
    if not isinstance(barrier.get("result_validation_errors"), list):
        errors.append("result_validation_errors must be a list")
    digest = barrier.get("barrier_digest")
    if not _is_sha256_ref(digest):
        errors.append("barrier_digest must be a sha256 ref")
    elif digest != compute_leaf_research_barrier_digest(barrier):
        errors.append("barrier_digest does not match barrier payload")
    return LeafSubagentContractValidationResult(not errors, tuple(errors))


def _runtime_bundle_digest_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(bundle)
    payload.pop("runtime_bundle_digest", None)
    payload.pop("runtime_bundle_validation", None)
    return payload


def compute_researcher_swarm_runtime_bundle_digest(bundle: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(_runtime_bundle_digest_payload(bundle)).encode("utf-8")).hexdigest()


def _sidecar_id(sidecar: dict[str, Any], index: int) -> str:
    return str(sidecar.get("sidecar_id") or f"sidecar-index:{index}")


def _string_refs_from_item(item: dict[str, Any], *fields: str) -> list[str]:
    refs: list[str] = []
    for field in fields:
        value = item.get(field)
        if _is_non_empty_string(value):
            refs.append(str(value))
        elif isinstance(value, list):
            refs.extend(str(ref) for ref in value if _is_non_empty_string(ref))
    return list(dict.fromkeys(refs))


def _sidecar_classification_leaf_ids(sidecar: dict[str, Any]) -> list[str]:
    leaf_ids: list[str] = []
    for classification in sidecar.get("required_question_classifications", []):
        if isinstance(classification, dict) and _is_non_empty_string(classification.get("leaf_id")):
            leaf_ids.append(str(classification["leaf_id"]))
    return sorted(set(leaf_ids))


def _certified_evidence_runtime_proof(
    *,
    assignments: list[dict[str, Any]],
    retrieval_packet: dict[str, Any] | None,
    sidecars: list[dict[str, Any]],
    sidecar_validations: list[dict[str, Any]],
    leaf_runtime_status: list[dict[str, Any]],
) -> dict[str, Any]:
    retrieval_summary = (
        retrieval_packet.get("research_sufficiency_summary", {})
        if isinstance(retrieval_packet, dict)
        else {}
    )
    certificates = (
        retrieval_packet.get("leaf_research_sufficiency_certificates", [])
        if isinstance(retrieval_packet, dict)
        else []
    )
    certificate_by_ref = {
        str(certificate.get("certificate_id")): certificate
        for certificate in certificates
        if isinstance(certificate, dict) and _is_non_empty_string(certificate.get("certificate_id"))
    }
    runtime_by_assignment = {
        str(row.get("assignment_ref")): row
        for row in leaf_runtime_status
        if isinstance(row, dict) and _is_non_empty_string(row.get("assignment_ref"))
    }
    valid_sidecar_ids = {
        str(row.get("sidecar_id"))
        for row in sidecar_validations
        if isinstance(row, dict)
        and _is_non_empty_string(row.get("sidecar_id"))
        and isinstance(row.get("validation"), dict)
        and row["validation"].get("valid") is True
    }
    assignment_leaf_ids = {
        str(assignment.get("leaf_id"))
        for assignment in assignments
        if isinstance(assignment, dict) and _is_non_empty_string(assignment.get("leaf_id"))
    }

    leaf_rows: list[dict[str, Any]] = []
    bounded_evidence_ref_count = 0
    certified_snippet_ref_count = 0
    source_metadata_ref_count = 0
    claim_family_ref_count = 0
    dispatch_allowed_leaf_count = 0
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        assigned_evidence = [
            item for item in assignment.get("assigned_evidence_refs", []) if isinstance(item, dict)
        ]
        snippet_refs = [
            str(item["certified_snippet"]["snippet_ref"])
            for item in assigned_evidence
            if isinstance(item.get("certified_snippet"), dict)
            and _is_non_empty_string(item["certified_snippet"].get("snippet_ref"))
        ]
        source_metadata_refs = sorted(
            set(
                ref
                for item in assigned_evidence
                for ref in _string_refs_from_item(
                    item,
                    "source_metadata_resolution_ref",
                    "source_metadata_refs",
                )
            )
        )
        claim_family_refs = sorted(
            set(
                ref
                for item in assigned_evidence
                for ref in _string_refs_from_item(
                    item,
                    "claim_family_id",
                    "claim_family_ids",
                    "claim_family_resolution_refs",
                )
            )
        )
        certificate = certificate_by_ref.get(str(assignment.get("research_sufficiency_certificate_ref")))
        dispatch_allowed = bool(
            isinstance(certificate, dict)
            and certificate.get("classification_dispatch_allowed") is True
        )
        if dispatch_allowed:
            dispatch_allowed_leaf_count += 1
        bounded_evidence_ref_count += len(assigned_evidence)
        certified_snippet_ref_count += len(set(snippet_refs))
        source_metadata_ref_count += len(source_metadata_refs)
        claim_family_ref_count += len(claim_family_refs)
        runtime_row = runtime_by_assignment.get(str(assignment.get("assignment_id")), {})
        leaf_rows.append(
            {
                "assignment_ref": assignment.get("assignment_id"),
                "leaf_id": assignment.get("leaf_id"),
                "research_sufficiency_certificate_ref": assignment.get(
                    "research_sufficiency_certificate_ref"
                ),
                "classification_dispatch_allowed": dispatch_allowed,
                "bounded_evidence_ref_count": len(assigned_evidence),
                "certified_snippet_ref_count": len(set(snippet_refs)),
                "source_metadata_ref_count": len(source_metadata_refs),
                "claim_family_ref_count": len(claim_family_refs),
                "model_executed": runtime_row.get("model_executed") is True,
                "accepted_classification_coverage": runtime_row.get(
                    "accepted_classification_coverage"
                ) is True,
                "lineage_complete": bool(assigned_evidence)
                and len(set(snippet_refs)) == len(assigned_evidence)
                and bool(source_metadata_refs)
                and bool(claim_family_refs)
                and dispatch_allowed,
            }
        )

    sidecar_rows: list[dict[str, Any]] = []
    for idx, sidecar in enumerate(sidecars):
        if not isinstance(sidecar, dict):
            continue
        leaf_ids = _sidecar_classification_leaf_ids(sidecar)
        model_backed = bool(
            _is_non_empty_string(sidecar.get("model_execution_context_ref"))
            and _is_sha256_ref(sidecar.get("model_execution_context_sha256"))
        )
        leaf_scoped = bool(leaf_ids) and set(leaf_ids) <= assignment_leaf_ids
        sidecar_rows.append(
            {
                "sidecar_index": idx,
                "sidecar_id": _sidecar_id(sidecar, idx),
                "validation_valid": _sidecar_id(sidecar, idx) in valid_sidecar_ids,
                "model_backed": model_backed,
                "leaf_scoped": leaf_scoped,
                "classification_leaf_ids": leaf_ids,
            }
        )

    assignment_count = len(assignments)
    valid_sidecar_count = sum(1 for row in sidecar_rows if row["validation_valid"])
    model_backed_sidecar_count = sum(
        1 for row in sidecar_rows if row["validation_valid"] and row["model_backed"]
    )
    leaf_scoped_sidecar_count = sum(
        1 for row in sidecar_rows if row["validation_valid"] and row["leaf_scoped"]
    )
    model_executed_leaf_count = sum(1 for row in leaf_rows if row["model_executed"])
    accepted_leaf_count = sum(1 for row in leaf_rows if row["accepted_classification_coverage"])
    return {
        "schema_version": "researcher-runtime-certified-evidence-proof/v1",
        "classification_dispatch_status": retrieval_summary.get("classification_dispatch_status"),
        "all_required_leaves_certified": retrieval_summary.get("all_required_leaves_certified") is True,
        "assignment_count": assignment_count,
        "dispatch_allowed_leaf_count": dispatch_allowed_leaf_count,
        "bounded_evidence_ref_count": bounded_evidence_ref_count,
        "certified_snippet_ref_count": certified_snippet_ref_count,
        "source_metadata_ref_count": source_metadata_ref_count,
        "claim_family_ref_count": claim_family_ref_count,
        "valid_sidecar_count": valid_sidecar_count,
        "model_backed_sidecar_count": model_backed_sidecar_count,
        "leaf_scoped_sidecar_count": leaf_scoped_sidecar_count,
        "model_executed_leaf_count": model_executed_leaf_count,
        "accepted_classification_leaf_count": accepted_leaf_count,
        "all_assignment_certificates_dispatch_allowed": assignment_count > 0
        and dispatch_allowed_leaf_count == assignment_count,
        "all_certified_evidence_lineage_complete": assignment_count > 0
        and all(row["lineage_complete"] for row in leaf_rows),
        "all_runtime_leaves_model_executed": assignment_count > 0
        and model_executed_leaf_count == assignment_count,
        "all_sidecars_model_backed_and_leaf_scoped": valid_sidecar_count > 0
        and model_backed_sidecar_count == valid_sidecar_count
        and leaf_scoped_sidecar_count == valid_sidecar_count,
        "all_leaves_have_accepted_classification_coverage": assignment_count > 0
        and accepted_leaf_count == assignment_count,
        "leaf_evidence_lineage": leaf_rows,
        "sidecar_lineage": sidecar_rows,
    }


def build_researcher_swarm_runtime_bundle(
    assignments: list[dict[str, Any]],
    *,
    qdt: dict[str, Any] | None = None,
    retrieval_packet: dict[str, Any] | None = None,
    sidecars: list[dict[str, Any]] | None = None,
    isolation_audits: list[dict[str, Any]] | None = None,
    subagent_results: list[dict[str, Any]] | None = None,
    true_production_mode: bool = False,
    max_concurrent: int = 5,
) -> dict[str, Any]:
    """Assemble Phase 8's validated researcher-swarm runtime handoff.

    The bundle remains a contract artifact: Researcher Swarm records launch
    requests, returned subagent result refs, sidecar/admission validation, and
    the barrier. Actual OpenClaw session launch authority stays in the control
    plane.
    """

    assignment_validations: list[dict[str, Any]] = []
    assignments_by_id: dict[str, dict[str, Any]] = {}
    for idx, assignment in enumerate(assignments):
        validation = validate_leaf_research_assignment(assignment)
        assignment_validations.append(
            {
                "assignment_index": idx,
                "assignment_ref": assignment.get("assignment_id") if isinstance(assignment, dict) else None,
                "leaf_id": assignment.get("leaf_id") if isinstance(assignment, dict) else None,
                "validation": validation.to_dict(),
            }
        )
        if isinstance(assignment, dict) and validation.valid:
            assignments_by_id[str(assignment["assignment_id"])] = assignment

    spawn_plan = build_leaf_researcher_spawn_plan(assignments, max_concurrent=max_concurrent) if assignments else None
    barrier = build_leaf_research_barrier(
        assignments,
        subagent_results=subagent_results,
        true_production_mode=true_production_mode,
    ) if assignments else None

    sidecar_validations: list[dict[str, Any]] = []
    accepted_classification_leaf_ids: set[str] = set()
    non_scoreable_leaf_ids: set[str] = set()
    sidecar_inputs = sidecars or []
    for idx, sidecar in enumerate(sidecar_inputs):
        if not isinstance(sidecar, dict):
            sidecar_validations.append(
                {
                    "sidecar_index": idx,
                    "sidecar_id": None,
                    "validation": {
                        "valid": False,
                        "errors": ["sidecar must be an object"],
                        "warnings": [],
                        "validator_version": LEAF_SUBAGENT_CONTRACT_VALIDATOR_VERSION,
                    },
                }
            )
            continue
        if qdt is None:
            validation = LeafSubagentContractValidationResult(False, ("qdt is required to validate sidecars",))
            validation_dict = validation.to_dict()
        elif retrieval_packet is not None:
            validation_dict = validate_researcher_sidecar_against_retrieval_packet(
                sidecar,
                qdt,
                retrieval_packet,
            ).to_dict()
        else:
            validation_dict = validate_researcher_sidecar_v2(sidecar, qdt).to_dict()
        sidecar_validations.append(
            {
                "sidecar_index": idx,
                "sidecar_id": _sidecar_id(sidecar, idx),
                "validation": validation_dict,
            }
        )
        if validation_dict.get("valid") is True:
            for classification in sidecar.get("required_question_classifications", []):
                if not isinstance(classification, dict) or not _is_non_empty_string(classification.get("leaf_id")):
                    continue
                leaf_id = str(classification["leaf_id"])
                if classification.get("classification_acceptance_status") == "accepted_for_verification":
                    accepted_classification_leaf_ids.add(leaf_id)
                elif classification.get("classification_acceptance_status") in {"non_scoreable", "blocked"}:
                    non_scoreable_leaf_ids.add(leaf_id)

    isolation_validations: list[dict[str, Any]] = []
    for idx, audit in enumerate(isolation_audits or []):
        assignment = assignments_by_id.get(str(audit.get("assignment_id"))) if isinstance(audit, dict) else None
        validation = validate_researcher_context_isolation_audit(audit, assignment=assignment)
        isolation_validations.append(
            {
                "audit_index": idx,
                "isolation_audit_id": audit.get("isolation_audit_id") if isinstance(audit, dict) else None,
                "assignment_ref": audit.get("assignment_id") if isinstance(audit, dict) else None,
                "leaf_id": audit.get("leaf_id") if isinstance(audit, dict) else None,
                "validation": validation.to_dict(),
            }
        )

    barrier_rows_by_assignment = {
        str(row.get("assignment_ref")): row
        for row in (barrier or {}).get("terminal_state_by_leaf", [])
        if isinstance(row, dict) and _is_non_empty_string(row.get("assignment_ref"))
    }
    subagent_results_by_assignment = {
        str(result.get("assignment_ref")): result
        for result in (subagent_results or [])
        if isinstance(result, dict) and _is_non_empty_string(result.get("assignment_ref"))
    }
    leaf_runtime_status: list[dict[str, Any]] = []
    for assignment in assignments:
        assignment_ref = str(assignment.get("assignment_id"))
        leaf_id = str(assignment.get("leaf_id"))
        barrier_row = barrier_rows_by_assignment.get(assignment_ref, {})
        result = subagent_results_by_assignment.get(assignment_ref, {})
        accepted_coverage = leaf_id in accepted_classification_leaf_ids
        blocker_recorded = (
            leaf_id in non_scoreable_leaf_ids
            or barrier_row.get("proceed") is False
            or barrier_row.get("terminal_status") in BLOCKING_RESULT_STATUSES
        )
        reason_codes = set(_string_list(barrier_row.get("reason_codes")))
        if not accepted_coverage and not blocker_recorded:
            reason_codes.add("leaf_unclassified")
        if accepted_coverage and blocker_recorded:
            reason_codes.add("accepted_coverage_with_blocker")
        leaf_runtime_status.append(
            {
                "assignment_ref": assignment_ref,
                "leaf_id": leaf_id,
                "terminal_status": barrier_row.get("terminal_status", "missing"),
                "subagent_session_ref": result.get("subagent_session_ref"),
                "model_executed": result.get("model_executed") is True,
                "resolved_model_id": result.get("resolved_model_id"),
                "accepted_classification_coverage": accepted_coverage,
                "blocker_recorded": blocker_recorded,
                "ready_for_reconciliation": bool(accepted_coverage or blocker_recorded),
                "reason_codes": sorted(reason_codes),
            }
        )

    validation_errors = []
    validation_errors.extend(
        error
        for item in assignment_validations
        if item["validation"].get("valid") is not True
        for error in item["validation"].get("errors", [])
    )
    validation_errors.extend(
        error
        for item in sidecar_validations
        if item["validation"].get("valid") is not True
        for error in item["validation"].get("errors", [])
    )
    validation_errors.extend(
        error
        for item in isolation_validations
        if item["validation"].get("valid") is not True
        for error in item["validation"].get("errors", [])
    )
    if barrier is not None:
        barrier_validation = validate_leaf_research_barrier(
            barrier,
            assignments=assignments,
            true_production_mode=true_production_mode,
        ).to_dict()
        if barrier_validation.get("valid") is not True:
            validation_errors.extend(barrier_validation.get("errors", []))
    else:
        barrier_validation = None

    certified_evidence_proof = _certified_evidence_runtime_proof(
        assignments=assignments,
        retrieval_packet=retrieval_packet,
        sidecars=copy.deepcopy(sidecars or []),
        sidecar_validations=sidecar_validations,
        leaf_runtime_status=leaf_runtime_status,
    )

    bundle = {
        "artifact_type": "researcher_swarm_runtime_bundle",
        "schema_version": RESEARCHER_SWARM_RUNTIME_BUNDLE_SCHEMA_VERSION,
        "runtime_owner": "ADS Researcher Swarm",
        "launch_authority": "control_plane_only",
        "control_plane_adapter_ref": LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF,
        "required_runtime_provider_model_id": RESEARCHER_PROVIDER_MODEL_KEY,
        "true_production_mode": bool(true_production_mode),
        "assignment_validations": assignment_validations,
        "spawn_plan": spawn_plan,
        "sidecars": copy.deepcopy(sidecars or []),
        "sidecar_validations": sidecar_validations,
        "isolation_audits": copy.deepcopy(isolation_audits or []),
        "isolation_audit_validations": isolation_validations,
        "subagent_results": copy.deepcopy(subagent_results or []),
        "leaf_research_barrier": barrier,
        "leaf_research_barrier_validation": barrier_validation,
        "leaf_runtime_status": leaf_runtime_status,
        "certified_evidence_runtime_proof": certified_evidence_proof,
        "all_leaves_have_assignment_and_resolution": bool(assignments)
        and all(row["ready_for_reconciliation"] for row in leaf_runtime_status),
        "proceed_to_verification_scae": bool(
            barrier
            and barrier.get("proceed_to_verification_scae") is True
            and not validation_errors
            and all(row["accepted_classification_coverage"] for row in leaf_runtime_status)
        ),
        "validation_errors": sorted(set(str(error) for error in validation_errors)),
        "authority_boundary": {
            "orchestrator_state_machine_authority": False,
            "selects_global_next_work": False,
            "forecast_authority": False,
            "probability_authority": False,
            "scae_ledger_authority": False,
        },
    }
    bundle["runtime_bundle_id"] = _sha_id(
        "researcher-swarm-runtime-bundle",
        {
            "assignments": [assignment.get("assignment_id") for assignment in assignments],
            "barrier_id": (barrier or {}).get("barrier_id"),
            "true_production_mode": true_production_mode,
        },
    )
    bundle["runtime_bundle_digest"] = compute_researcher_swarm_runtime_bundle_digest(bundle)
    return bundle


def validate_researcher_swarm_runtime_bundle(bundle: Any) -> LeafSubagentContractValidationResult:
    errors: list[str] = []
    if not isinstance(bundle, dict):
        return LeafSubagentContractValidationResult(False, ("runtime bundle must be an object",))
    if bundle.get("artifact_type") != "researcher_swarm_runtime_bundle":
        errors.append("artifact_type must be researcher_swarm_runtime_bundle")
    if bundle.get("schema_version") != RESEARCHER_SWARM_RUNTIME_BUNDLE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RESEARCHER_SWARM_RUNTIME_BUNDLE_SCHEMA_VERSION}")
    if bundle.get("launch_authority") != "control_plane_only":
        errors.append("launch_authority must be control_plane_only")
    if bundle.get("control_plane_adapter_ref") != LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF:
        errors.append(f"control_plane_adapter_ref must be {LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF}")
    if bundle.get("required_runtime_provider_model_id") != RESEARCHER_PROVIDER_MODEL_KEY:
        errors.append(f"required_runtime_provider_model_id must be {RESEARCHER_PROVIDER_MODEL_KEY}")
    authority = bundle.get("authority_boundary")
    if not isinstance(authority, dict):
        errors.append("authority_boundary must be an object")
    else:
        for field in (
            "orchestrator_state_machine_authority",
            "selects_global_next_work",
            "forecast_authority",
            "probability_authority",
            "scae_ledger_authority",
        ):
            if authority.get(field) is not False:
                errors.append(f"authority_boundary.{field} must be false")
    for field in (
        "assignment_validations",
        "sidecars",
        "sidecar_validations",
        "isolation_audits",
        "isolation_audit_validations",
        "subagent_results",
        "leaf_runtime_status",
        "validation_errors",
    ):
        if not isinstance(bundle.get(field), list):
            errors.append(f"{field} must be a list")
    for field in ("assignment_validations", "sidecar_validations", "isolation_audit_validations"):
        rows = bundle.get(field)
        if not isinstance(rows, list):
            continue
        for idx, row in enumerate(rows):
            validation = row.get("validation") if isinstance(row, dict) else None
            if not isinstance(validation, dict):
                errors.append(f"{field}[{idx}].validation must be an object")
            elif validation.get("valid") is not True:
                nested_errors = validation.get("errors") if isinstance(validation.get("errors"), list) else []
                detail = "; ".join(str(error) for error in nested_errors) or "invalid nested artifact"
                errors.append(f"{field}[{idx}] invalid: {detail}")
    if isinstance(bundle.get("leaf_research_barrier_validation"), dict):
        barrier_validation = bundle["leaf_research_barrier_validation"]
        if barrier_validation.get("valid") is not True:
            nested_errors = barrier_validation.get("errors") if isinstance(barrier_validation.get("errors"), list) else []
            detail = "; ".join(str(error) for error in nested_errors) or "invalid leaf research barrier"
            errors.append("leaf_research_barrier_validation invalid: " + detail)
    if isinstance(bundle.get("validation_errors"), list) and bundle["validation_errors"]:
        errors.append("validation_errors must be empty for accepted runtime bundles")
    if bundle.get("all_leaves_have_assignment_and_resolution") is not True and bundle.get("all_leaves_have_assignment_and_resolution") is not False:
        errors.append("all_leaves_have_assignment_and_resolution must be a boolean")
    if bundle.get("proceed_to_verification_scae") is not True and bundle.get("proceed_to_verification_scae") is not False:
        errors.append("proceed_to_verification_scae must be a boolean")
    proof = bundle.get("certified_evidence_runtime_proof")
    if not isinstance(proof, dict):
        errors.append("certified_evidence_runtime_proof must be an object")
    else:
        if proof.get("schema_version") != "researcher-runtime-certified-evidence-proof/v1":
            errors.append("certified_evidence_runtime_proof.schema_version is invalid")
        for field in (
            "assignment_count",
            "dispatch_allowed_leaf_count",
            "bounded_evidence_ref_count",
            "certified_snippet_ref_count",
            "source_metadata_ref_count",
            "claim_family_ref_count",
            "valid_sidecar_count",
            "model_backed_sidecar_count",
            "leaf_scoped_sidecar_count",
            "model_executed_leaf_count",
            "accepted_classification_leaf_count",
        ):
            if not isinstance(proof.get(field), int) or isinstance(proof.get(field), bool):
                errors.append(f"certified_evidence_runtime_proof.{field} must be an integer")
        for field in ("leaf_evidence_lineage", "sidecar_lineage"):
            if not isinstance(proof.get(field), list):
                errors.append(f"certified_evidence_runtime_proof.{field} must be a list")
        if bundle.get("proceed_to_verification_scae") is True:
            required_true_fields = (
                "all_required_leaves_certified",
                "all_assignment_certificates_dispatch_allowed",
                "all_certified_evidence_lineage_complete",
                "all_runtime_leaves_model_executed",
                "all_sidecars_model_backed_and_leaf_scoped",
                "all_leaves_have_accepted_classification_coverage",
            )
            for field in required_true_fields:
                if proof.get(field) is not True:
                    errors.append(f"certified_evidence_runtime_proof.{field} must be true when proceeding")
    digest = bundle.get("runtime_bundle_digest")
    if not _is_sha256_ref(digest):
        errors.append("runtime_bundle_digest must be a sha256 ref")
    elif digest != compute_researcher_swarm_runtime_bundle_digest(bundle):
        errors.append("runtime_bundle_digest does not match bundle payload")
    return LeafSubagentContractValidationResult(not errors, tuple(errors))


__all__ = [
    "LEAF_RESEARCH_BARRIER_SCHEMA_VERSION",
    "LEAF_SUBAGENT_EXECUTION_POLICY_SCHEMA_VERSION",
    "LEAF_SUBAGENT_RESULT_SCHEMA_VERSION",
    "LEAF_SUBAGENT_CONTROL_PLANE_ADAPTER_REF",
    "RESEARCHER_SWARM_RUNTIME_BUNDLE_SCHEMA_VERSION",
    "compute_leaf_research_barrier_digest",
    "compute_leaf_subagent_result_digest",
    "compute_researcher_swarm_runtime_bundle_digest",
    "build_leaf_research_barrier",
    "build_leaf_researcher_spawn_plan",
    "build_leaf_subagent_execution_policy",
    "build_leaf_subagent_result",
    "build_researcher_swarm_runtime_bundle",
    "validate_leaf_research_barrier",
    "validate_leaf_researcher_spawn_plan",
    "validate_leaf_subagent_execution_policy",
    "validate_leaf_subagent_result",
    "validate_researcher_swarm_runtime_bundle",
]
