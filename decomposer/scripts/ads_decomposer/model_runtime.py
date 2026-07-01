"""Shared ADS specialist model runtime records.

The runtime boundary is intentionally small: callers own prompts, schemas, and
artifact persistence; this module owns transport policy, provenance, and
fail-closed forbidden-output scanning.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


MODEL_RUNTIME_CALL_SCHEMA_VERSION = "model-runtime-call/v1"
MODEL_RUNTIME_CALL_ARTIFACT_TYPE = "model_runtime_call"
MODEL_RUNTIME_VERSION = "ads-model-runtime-call/v1"

MODEL_RUNTIME_TIMEOUTS = {
    "decomposer_qdt_generation": 180,
    "researcher_leaf_nli_classification": 240,
    "native_research_candidate_discovery": 180,
}
DEFAULT_TIMEOUT_SECONDS = 180
MODEL_RUNTIME_RETRY_DIAGNOSTIC_SCHEMA_VERSION = "model-runtime-retry-diagnostic/v1"
MODEL_RUNTIME_SCHEMA_REPAIR_DIAGNOSTIC_SCHEMA_VERSION = "model-runtime-schema-repair-diagnostic/v1"
MODEL_TRANSPORT_RETRY_POLICY_REF = "ads-model-transport-retry/v1"
MODEL_TRANSPORT_RETRY_POLICY = {
    "policy_ref": MODEL_TRANSPORT_RETRY_POLICY_REF,
    "max_attempts": 3,
    "base_backoff_seconds": 2.0,
    "max_backoff_seconds": 20.0,
    "jitter_fraction": 0.25,
}
DEFAULT_MAX_TRANSPORT_RETRIES = MODEL_TRANSPORT_RETRY_POLICY["max_attempts"] - 1
DEFAULT_MAX_SCHEMA_REPAIRS = 1
MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION = "model-runtime-transport-request/v1"
MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION = "model-runtime-transport-response/v1"
OPENCLAW_CODEX_OAUTH_PROVIDER_ROUTE_PREFIX = "openclaw_codex_oauth"
DEFAULT_OPENCLAW_DECOMPOSER_AGENT_ID = "decomposer"
DEFAULT_MODEL_LANE_POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestrator"
    / "plans"
    / "autonomous-decomposition-swarm-model-lane-policy.json"
)

FORBIDDEN_OUTPUT_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "scae_delta",
    "scae_evidence_delta",
    "decision_recommendation",
    "decision_output",
    "production_forecast",
    "forecast_probability",
    "leaf_probability",
    "macro_probability",
    "sub_forecast_probability",
    "log_odds",
)
FORBIDDEN_OUTPUT_VALUES = {
    "probability",
    "fair_value",
    "scae_delta",
    "scae_evidence_delta",
    "decision_output",
    "production_forecast_prob",
    "forecast_probability",
    "leaf_probability",
    "macro_probability",
    "sub_forecast_probability",
}
DECLARATIVE_FORBIDDEN_OUTPUT_LIST_KEYS = {
    "forbidden_outputs",
}
NON_REPAIRABLE_VALIDATION_ERROR_MARKERS = (
    "ambiguous_terms_not_decomposed",
    "insufficient_material_leaf_count",
    "market_family_context_not_analyzed",
    "missing_pre_resolution_dispatchable_leaves",
    "missing_pre_resolution_forecast_dimensions",
    "negative_market_mapping_not_decomposed",
    "overlapping_leaf_questions_not_deduplicated",
    "required_coverage_dimension_missing",
    "resolution_checklist_dominates_research_coverage",
    "template_mad_lib_leaf",
    "terminal_verification_dominates_unresolved_forecast_qdt",
    "terminal_verification_leaf_misclassified_as_pre_resolution",
)
TERMINAL_TEMPORAL_ROLE_VALIDATION_ERROR_MARKERS = (
    "terminal_verification_dominates_unresolved_forecast_qdt",
    "terminal_verification_leaf_misclassified_as_pre_resolution",
    "dispatchable_pre_resolution_leaf_ids contains terminal verification leaves",
)
FORBIDDEN_AUTHORITY_VALIDATION_ERROR_MARKERS = (
    "forbidden",
    "probability_authority",
    "forecast authority",
    "model output authority",
    "scae_delta",
    "fair_value",
    "decision_output",
    "production_forecast",
)
SEMANTIC_QUALITY_VALIDATION_ERROR_MARKERS = tuple(
    marker
    for marker in NON_REPAIRABLE_VALIDATION_ERROR_MARKERS
    if marker not in TERMINAL_TEMPORAL_ROLE_VALIDATION_ERROR_MARKERS
) + (
    "required_purpose_coverage_missing",
    "critical/source-of-truth leaves require protected primary or unanswerability proof",
    "critical/source-of-truth leaves cannot allow macro fallback",
)
MECHANICAL_SCHEMA_VALIDATION_ERROR_MARKERS = (
    "analyst_consensus_leaf_must_be_pre_resolution_or_source_quality",
    "analyst_consensus_leaf_wrong_temporal_role",
    " is invalid",
    " is required",
    " is duplicated",
    " must be ",
    " must contain",
    " must equal",
    " must match",
    " must reference",
    " must start",
    " missing ",
    " references unknown ",
    "not valid json",
)
VALIDATION_ERROR_GROUPS = (
    "forbidden_authority",
    "mechanical_schema",
    "semantic_quality",
    "terminal_temporal_role",
)
SCHEMA_REPAIR_CHANGED_PATH_LIMIT = 80


class ModelRuntimeError(RuntimeError):
    """Raised when a specialist model call fails closed."""

    def __init__(self, message: str, *, runtime_call: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.runtime_call = runtime_call


@dataclass(frozen=True)
class ModelRuntimeResult:
    response_payload: Any
    runtime_call: dict[str, Any]


Transport = Callable[[dict[str, Any]], Any]
OutputValidator = Callable[[Any], tuple[bool, list[str]]]
Repairer = Callable[[Any, list[str]], Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def prefixed_sha256(value: Any) -> str:
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8")
    else:
        data = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(item)]


def _load_model_lane_policy(path: Path | str = DEFAULT_MODEL_LANE_POLICY_PATH) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelRuntimeError(f"{path} is not valid JSON") from exc
    if not isinstance(policy, dict):
        raise ModelRuntimeError("model lane policy must be an object")
    if policy.get("artifact_type") != "model_lane_policy":
        raise ModelRuntimeError("model lane policy artifact_type must be model_lane_policy")
    if policy.get("schema_version") != "model-lane-policy/v1":
        raise ModelRuntimeError("model lane policy schema_version must be model-lane-policy/v1")
    authority = policy.get("authority_boundary")
    if not isinstance(authority, dict):
        raise ModelRuntimeError("model lane policy authority_boundary must be an object")
    for field in (
        "scae_numeric_aggregation_uses_model",
        "model_outputs_may_author_probability",
        "model_outputs_may_override_scae",
    ):
        if authority.get(field) is not False:
            raise ModelRuntimeError(f"authority_boundary.{field} must be false")
    return policy


def resolve_model_runtime_lane(
    lane_id: str,
    *,
    model_lane_policy: dict[str, Any] | None = None,
    model_lane_policy_path: Path | str = DEFAULT_MODEL_LANE_POLICY_PATH,
    requested_model_id: str | None = None,
) -> dict[str, Any]:
    """Resolve a model-lane policy row into runtime transport metadata."""

    if not _is_non_empty_string(lane_id):
        raise ModelRuntimeError("lane_id is required")
    policy = model_lane_policy or _load_model_lane_policy(model_lane_policy_path)
    lanes = policy.get("lanes")
    lane = lanes.get(lane_id) if isinstance(lanes, dict) else None
    if not isinstance(lane, dict):
        raise ModelRuntimeError(f"missing model lane {lane_id}")
    provider = str(lane.get("provider") or policy.get("default_provider") or "")
    if provider != "openai":
        raise ModelRuntimeError(f"{lane_id} provider must be openai for Phase 1 runtime")
    default_model_id = str(lane.get("default_model_id") or "")
    allowed_model_ids = _string_list(lane.get("allowed_model_ids"))
    if not default_model_id:
        raise ModelRuntimeError(f"{lane_id} default_model_id is required")
    if default_model_id not in allowed_model_ids:
        raise ModelRuntimeError(f"{lane_id} default model must be in allowed_model_ids")
    requested = requested_model_id.strip() if isinstance(requested_model_id, str) else None
    if requested and requested not in allowed_model_ids:
        raise ModelRuntimeError(f"{lane_id} requested model is not allowed")
    resolved_model_id = requested or default_model_id
    if lane_id in MODEL_RUNTIME_TIMEOUTS and resolved_model_id != "gpt-5.5-high":
        raise ModelRuntimeError(f"{lane_id} must resolve to gpt-5.5-high")
    provider_route = str(lane.get("provider_route") or f"{provider}/{resolved_model_id}")
    oauth_route_required = bool(lane.get("oauth_route_required", False))
    runtime_agent_id = lane.get("runtime_agent_id")
    if lane_id in MODEL_RUNTIME_TIMEOUTS:
        if oauth_route_required is not True:
            raise ModelRuntimeError(f"{lane_id} must require OpenClaw OAuth routing")
        if not provider_route.startswith(OPENCLAW_CODEX_OAUTH_PROVIDER_ROUTE_PREFIX + "/"):
            raise ModelRuntimeError(f"{lane_id} provider_route must use OpenClaw Codex OAuth")
    return {
        "schema_version": "model-runtime-lane-resolution/v1",
        "model_lane_id": lane_id,
        "provider": provider,
        "resolved_model_id": resolved_model_id,
        "provider_route": provider_route,
        "oauth_route_required": oauth_route_required,
        "runtime_agent_id": runtime_agent_id,
        "model_policy_ref": str(Path(model_lane_policy_path)),
        "model_policy_id": policy.get("policy_id"),
        "default_model_id": default_model_id,
        "allowed_model_ids": allowed_model_ids,
        "required_artifact_fields": _string_list(lane.get("required_artifact_fields")),
        "forbidden_outputs": _string_list(lane.get("forbidden_outputs")),
        "timeout_seconds": MODEL_RUNTIME_TIMEOUTS.get(lane_id, DEFAULT_TIMEOUT_SECONDS),
    }


def _normalized_field_name(value: Any) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _collect_forbidden_outputs(
    value: Any,
    matches: list[dict[str, str]],
    path: str = "response",
    *,
    declarative_forbidden_list: bool = False,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if any(fragment in normalized for fragment in FORBIDDEN_OUTPUT_KEY_FRAGMENTS):
                matches.append({"path": f"{path}.{key}", "match_type": "key", "matched": normalized})
            _collect_forbidden_outputs(
                child,
                matches,
                f"{path}.{key}",
                declarative_forbidden_list=normalized in DECLARATIVE_FORBIDDEN_OUTPUT_LIST_KEYS,
            )
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _collect_forbidden_outputs(
                child,
                matches,
                f"{path}[{idx}]",
                declarative_forbidden_list=declarative_forbidden_list,
            )
    elif isinstance(value, str) and not declarative_forbidden_list:
        normalized = _normalized_field_name(value)
        if normalized in FORBIDDEN_OUTPUT_VALUES:
            matches.append({"path": path, "match_type": "value", "matched": normalized})


def scan_forbidden_model_outputs(value: Any) -> dict[str, Any]:
    matches: list[dict[str, str]] = []
    _collect_forbidden_outputs(value, matches)
    return {
        "schema_version": "forbidden-model-output-scan/v1",
        "status": "failed" if matches else "passed",
        "matches": matches,
        "scanner_version": MODEL_RUNTIME_VERSION,
    }


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(marker.lower() in normalized for marker in markers)


def classify_qdt_validation_errors(errors: list[str]) -> dict[str, list[str]]:
    groups = {group: [] for group in VALIDATION_ERROR_GROUPS}
    for error in errors:
        text = str(error)
        normalized = text.lower()
        if _contains_marker(normalized, FORBIDDEN_AUTHORITY_VALIDATION_ERROR_MARKERS):
            groups["forbidden_authority"].append(text)
            continue
        matched = False
        if _contains_marker(normalized, TERMINAL_TEMPORAL_ROLE_VALIDATION_ERROR_MARKERS):
            groups["terminal_temporal_role"].append(text)
            matched = True
        if _contains_marker(normalized, SEMANTIC_QUALITY_VALIDATION_ERROR_MARKERS):
            groups["semantic_quality"].append(text)
            matched = True
        if _contains_marker(normalized, MECHANICAL_SCHEMA_VALIDATION_ERROR_MARKERS):
            groups["mechanical_schema"].append(text)
            matched = True
        if not matched:
            groups["semantic_quality"].append(text)
    return groups


def _validation_error_group_counts(groups: dict[str, list[str]]) -> dict[str, int]:
    return {group: len(groups.get(group, [])) for group in VALIDATION_ERROR_GROUPS}


def _schema_repair_decision(
    groups: dict[str, list[str]],
    *,
    max_schema_repairs: int,
    repairer_configured: bool,
) -> tuple[bool, str]:
    if groups.get("forbidden_authority"):
        return False, "forbidden_authority_not_repairable"
    if not repairer_configured:
        return False, "no_repairer_configured"
    if max_schema_repairs <= 0:
        return False, "repair_budget_exhausted"
    if groups.get("mechanical_schema"):
        return True, "mechanical_schema_repair_available"
    return False, "no_mechanical_schema_errors"


def _validation_errors_are_repairable(errors: list[str]) -> bool:
    groups = classify_qdt_validation_errors(errors)
    should_repair, _reason = _schema_repair_decision(
        groups,
        max_schema_repairs=DEFAULT_MAX_SCHEMA_REPAIRS,
        repairer_configured=True,
    )
    return should_repair


def _changed_json_paths(before: Any, after: Any, path: str = "response") -> list[str]:
    if before == after:
        return []
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        changed: list[str] = []
        keys = sorted(set(before) | set(after), key=str)
        for key in keys:
            child_path = f"{path}.{key}"
            if key not in before or key not in after:
                changed.append(child_path)
            else:
                changed.extend(_changed_json_paths(before[key], after[key], child_path))
            if len(changed) >= SCHEMA_REPAIR_CHANGED_PATH_LIMIT:
                return changed[:SCHEMA_REPAIR_CHANGED_PATH_LIMIT]
        return changed
    if isinstance(before, list):
        changed = []
        for idx, (before_item, after_item) in enumerate(zip(before, after)):
            changed.extend(_changed_json_paths(before_item, after_item, f"{path}[{idx}]"))
            if len(changed) >= SCHEMA_REPAIR_CHANGED_PATH_LIMIT:
                return changed[:SCHEMA_REPAIR_CHANGED_PATH_LIMIT]
        if len(before) != len(after):
            changed.append(f"{path}.length")
        return changed[:SCHEMA_REPAIR_CHANGED_PATH_LIMIT]
    return [path]


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            extracted = _extract_json_object_text(value)
            if extracted is None:
                raise
            return json.loads(extracted)
    return copy.deepcopy(value)


def _extract_json_object_text(value: str) -> str | None:
    start = value.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index, ch in enumerate(value[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return None


def _transport_request(
    runtime_call: dict[str, Any],
    request_payload: dict[str, Any],
    *,
    transport_attempt: int = 1,
    transport_max_attempts: int = 1,
) -> dict[str, Any]:
    return {
        "schema_version": MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION,
        "runtime_call_id": runtime_call["runtime_call_id"],
        "model_lane_id": runtime_call["model_lane_id"],
        "provider": runtime_call["provider"],
        "resolved_model_id": runtime_call["resolved_model_id"],
        "provider_route": runtime_call["provider_route"],
        "prompt_template_id": runtime_call["prompt_template_id"],
        "prompt_template_sha256": runtime_call["prompt_template_sha256"],
        "output_schema_version": runtime_call["output_schema_version"],
        "timeout_seconds": runtime_call["timeout_seconds"],
        "transport_attempt": transport_attempt,
        "transport_max_attempts": transport_max_attempts,
        "transport_retry_policy_ref": runtime_call.get("transport_retry_policy", {}).get("policy_ref"),
        "request_payload": copy.deepcopy(request_payload),
    }


def _unwrap_transport_response(raw: Any) -> tuple[Any, Any, Any]:
    if (
        isinstance(raw, dict)
        and raw.get("schema_version") == MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION
        and "response_payload" in raw
    ):
        return (
            raw.get("response_payload"),
            copy.deepcopy(raw.get("token_usage")),
            copy.deepcopy(raw.get("provider_status")),
        )
    return raw, None, None


def _model_runtime_component(model_lane_id: str) -> str:
    if model_lane_id == "decomposer_qdt_generation":
        return "qdt_model_runtime"
    return "model_runtime"


def _model_transport_max_attempts(max_transport_retries: int) -> int:
    if isinstance(max_transport_retries, bool) or not isinstance(max_transport_retries, int):
        raise ModelRuntimeError("max_transport_retries must be a non-negative integer")
    if max_transport_retries < 0:
        raise ModelRuntimeError("max_transport_retries must be a non-negative integer")
    requested_attempts = max_transport_retries + 1
    return max(1, min(int(MODEL_TRANSPORT_RETRY_POLICY["max_attempts"]), requested_attempts))


def _classify_model_transport_failure(exc: Exception) -> dict[str, Any]:
    text = str(exc).lower()
    exc_type = type(exc).__name__
    if isinstance(exc, ModelRuntimeError):
        return {
            "retryable": False,
            "failure_class": "model_runtime_contract_error",
            "exception_type": exc_type,
        }
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) or "timed out" in text or "timeout" in text:
        return {"retryable": True, "failure_class": "timeout", "exception_type": exc_type}
    if isinstance(exc, json.JSONDecodeError):
        return {"retryable": True, "failure_class": "malformed_model_output", "exception_type": exc_type}
    if isinstance(exc, (ConnectionError, ConnectionResetError, BrokenPipeError)):
        return {"retryable": True, "failure_class": "connection_reset", "exception_type": exc_type}
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return {"retryable": True, "failure_class": "rate_limit", "exception_type": exc_type}
    if any(marker in text for marker in ("temporar", "try again", "502", "503", "504", "gateway")):
        return {"retryable": True, "failure_class": "transient_provider_error", "exception_type": exc_type}
    if isinstance(exc, subprocess.SubprocessError):
        return {"retryable": True, "failure_class": "temporary_subprocess_failure", "exception_type": exc_type}
    if isinstance(exc, RuntimeError):
        return {"retryable": True, "failure_class": "transient_provider_error", "exception_type": exc_type}
    return {
        "retryable": False,
        "failure_class": "non_retryable_transport_failure",
        "exception_type": exc_type,
    }


def _model_transport_backoff(
    *,
    runtime_call_id: str,
    attempt: int,
    failure_class: str,
) -> tuple[float, str, list[float]]:
    raw = min(
        float(MODEL_TRANSPORT_RETRY_POLICY["max_backoff_seconds"]),
        float(MODEL_TRANSPORT_RETRY_POLICY["base_backoff_seconds"]) * (2 ** max(0, attempt - 1)),
    )
    jitter_upper = max(1.0, raw * float(MODEL_TRANSPORT_RETRY_POLICY["jitter_fraction"]))
    seed_material = {
        "runtime_call_id": runtime_call_id,
        "attempt": attempt,
        "failure_class": failure_class,
        "policy_ref": MODEL_TRANSPORT_RETRY_POLICY_REF,
    }
    digest = hashlib.sha256(canonical_json(seed_material).encode("utf-8")).hexdigest()
    unit = int(digest[:12], 16) / float(0xFFFFFFFFFFFF)
    backoff = raw + (unit * jitter_upper)
    return round(backoff, 3), digest[:16], [0.0, round(jitter_upper, 3)]


def _retry_diagnostic_event(
    runtime_call: dict[str, Any],
    *,
    event: str,
    attempt: int,
    max_attempts: int,
    failure: dict[str, Any] | None = None,
    backoff_seconds: float | None = None,
    jitter_seed: str | None = None,
    jitter_range_seconds: list[float] | None = None,
    final_retry_outcome: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MODEL_RUNTIME_RETRY_DIAGNOSTIC_SCHEMA_VERSION,
        "event": event,
        "component": _model_runtime_component(str(runtime_call.get("model_lane_id") or "")),
        "lane": runtime_call.get("model_lane_id"),
        "model_lane_id": runtime_call.get("model_lane_id"),
        "runtime_call_ref": runtime_call.get("runtime_call_id"),
        "attempt": attempt,
        "max_attempts": max_attempts,
        "failure_retryable": bool(failure.get("retryable")) if isinstance(failure, dict) else False,
        "failure_class": failure.get("failure_class") if isinstance(failure, dict) else None,
        "exception_type": failure.get("exception_type") if isinstance(failure, dict) else None,
        "backoff_seconds": backoff_seconds,
        "jitter_seed": jitter_seed,
        "jitter_range_seconds": jitter_range_seconds or [0.0, 0.0],
        "repair_count": runtime_call.get("repair_count", 0),
        "retry_policy_ref": MODEL_TRANSPORT_RETRY_POLICY_REF,
        "final_retry_outcome": final_retry_outcome,
    }


def _openclaw_agent_prompt(request_payload: dict[str, Any]) -> str:
    compact_candidate_schema = {
        "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
        "response_payload": {
            "candidate_id": "qdt-candidate-model-runtime",
            "market_complexity_score": 0.62,
            "branches": [
                {
                    "branch_id": "branch-resolution",
                    "branch_question": "Question-specific branch to define bounded research coverage for the market outcome.",
                    "branch_role": "model_generated_research_coverage",
                    "dependency_group_id": "dep-group-resolution",
                    "required_evidence_purposes": ["source_of_truth", "direct_evidence", "catalyst", "structural"],
                    "leaf_ids": ["leaf-official-resolution", "leaf-current-status"],
                    "amrg_usage_refs": [],
                    "structural_validation": {"depth": 1},
                }
            ],
            "required_leaf_questions": [
                {
                    "leaf_id": "leaf-official-resolution",
                    "parent_branch_id": "branch-resolution",
                    "question_text": "Market-specific research question for one bounded research leaf.",
                    "leaf_temporal_role": "resolution_mechanics",
                    "purpose": "source_of_truth",
                    "coverage_dimension": "resolution_mechanics",
                    "research_factor": "resolution_condition_and_authority",
                    "research_priority": "critical",
                    "leaf_dependency_group_id": "dep-group-resolution",
                    "leaf_condition_scope": "unconditional",
                    "required_evidence_fields": ["official_status", "resolution_criteria"],
                    "evidence_requirements": [
                        {"required_evidence_field": "official_status", "pre_cutoff_required": True}
                    ],
                    "classification_targets": [
                        "official_status",
                        "resolution_criteria",
                        "evidence_quality",
                        "missingness_status",
                    ],
                    "sufficiency_criteria": {
                        "classification_dispatch_requires_sufficiency_certificate": True
                    },
                    "market_component_terms": [],
                    "amrg_usage_refs": [],
                    "specificity_evidence": {
                        "market_rule_clause_refs": [],
                        "case_contract_field_refs": ["macro_question", "source_cutoff_timestamp"],
                        "why_this_must_be_investigated": "Market-specific reason this leaf is material.",
                        "not_a_template_reason": "Uses the concrete market subject and rule terms.",
                        "expected_answer_type": "classification_with_extracted_values",
                    },
                    "overlap_risk_with_leaf_ids": [],
                    "missingness_interpretation": "unanswered_material_question_or_structural_unanswerability_candidate",
                    "forbidden_outputs": ["probability", "fair_value", "final_forecast"],
                    "structural_validation": {"depth": 2, "answerability_status": "answerable"},
                }
            ],
            "related_market_context_usage": {
                "usage_status": "related_context_used",
                "related_context_artifact_ref": None,
                "amrg_usage_refs": [],
                "weak_context_only": False,
                "anchor_dependency_status": "not_declared_phase2",
            },
            "amrg_anchor_dependency_contracts": [],
        },
        "provider_status": {"status": "completed"},
    }
    return (
        "You are the ADS Decomposer runtime transport for the Autonomous "
        "Decomposition-Swarm pipeline.\n\n"
        "Return exactly one JSON object and no Markdown. The object must use "
        f"schema_version={MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION!r} "
        "and must contain response_payload with this compact model candidate "
        "shape, not a full question_decomposition artifact. The local runtime "
        "will wrap the compact candidate into the canonical QDT artifact after "
        "validation. Every branch leaf_ids list must exactly match the leaves "
        "whose parent_branch_id references that branch. required_leaf_questions "
        "must be non-empty and must fit the requested leaf_budget. Use only "
        "question-specific leaf IDs, branch IDs, questions, evidence fields, "
        "and market terms for the runtime request. Do not include "
        "probabilities, fair values, SCAE deltas, decisions, execution advice, "
        "numeric weights, Bayesian/log-odds edges, or production forecast "
        "outputs anywhere in the response payload. Produce a bounded research "
        "decomposition that maximizes coverage of material uncertainty. Do not "
        "estimate probability. Do not assign weights. Do not make a final "
        "forecast. Emit leaf questions, purposes, evidence requirements, "
        "classification targets, and sufficiency criteria. Avoid mad-lib leaves "
        "that could be reused across unrelated markets by swapping entity names. "
        "If the request market_temporal_state is unresolved, prioritize "
        "pre-resolution forecast research: current evidence, drivers, blockers, "
        "source quality, timing constraints, and material unknowns before cutoff. "
        "Do not make official-result or final-winner verification the dominant "
        "dispatchable leaf set. Put future settlement/result checks in "
        "terminal_verification leaves and mark them non-dispatchable before "
        "resolution unless already observable before the source cutoff. Separate "
        "contract guard leaves, material research-factor leaves, material unknowns, "
        "overlap groups, terminal verification leaves, and dispatchable "
        "pre-resolution leaves. Treat weak AMRG context as diagnostic context only; "
        "do not use it for QDT selection, QDT repair, probability authority, SCAE "
        "delta, or forecast writes unless a strict anchor dependency is validated. "
        "If the runtime request includes qdt_schema_crib, treat it as authoritative: "
        "use only its allowed enum values, include structural_validation.answerability_status "
        "on every leaf, and keep terminal_verification leaves out of dispatchable "
        "pre-resolution leaf IDs for unresolved markets.\n\n"
        "Required response skeleton:\n"
        + canonical_json(compact_candidate_schema)
        + "\n\n"
        "Runtime transport request JSON:\n"
        + canonical_json(request_payload)
    )


def _extract_openclaw_reply_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = [_extract_openclaw_reply_text(item) for item in value]
        joined = "\n".join(text for text in texts if text)
        return joined or None
    if not isinstance(value, dict):
        return None
    if value.get("schema_version") == MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION:
        return canonical_json(value)
    for key in (
        "reply",
        "response",
        "message",
        "content",
        "text",
        "output",
        "stdout",
        "payloads",
        "finalAssistantVisibleText",
        "finalAssistantRawText",
    ):
        text = _extract_openclaw_reply_text(value.get(key))
        if text:
            return text
    result = value.get("result")
    text = _extract_openclaw_reply_text(result)
    if text:
        return text
    return None


def _parse_openclaw_agent_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = stdout
    text = _extract_openclaw_reply_text(parsed)
    if not text:
        raise RuntimeError("OpenClaw agent response did not contain reply text")
    payload = _json_payload(text)
    if not isinstance(payload, dict):
        raise RuntimeError("OpenClaw agent reply did not parse to a JSON object")
    if payload.get("schema_version") == MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION:
        return payload
    return {
        "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
        "response_payload": payload,
        "provider_status": {"transport": "openclaw_agent_reply_wrapped"},
    }


def openclaw_codex_agent_transport_from_env(
    *,
    agent_id: str | None = None,
    cli_path: str | None = None,
    session_key_prefix: str | None = None,
    model: str | None = None,
    prompt_builder: Callable[[dict[str, Any]], str] | None = None,
) -> Transport:
    """Return an OpenClaw Gateway agent transport using Codex OAuth auth.

    This replaces direct API-key transport for ADS live model lanes. OpenClaw
    owns provider OAuth and Codex execution; this transport only adapts the
    Gateway agent response back into the existing model-runtime response
    contract.
    """

    resolved_agent_id = (
        agent_id
        or os.environ.get("ADS_DECOMPOSER_OPENCLAW_AGENT_ID")
        or DEFAULT_OPENCLAW_DECOMPOSER_AGENT_ID
    )
    resolved_cli = cli_path or os.environ.get("ADS_OPENCLAW_CLI") or shutil.which("openclaw")
    if not resolved_cli:
        raise ModelRuntimeError("openclaw CLI is required for OpenClaw Codex OAuth runtime")
    resolved_prefix = (
        session_key_prefix
        or os.environ.get("ADS_DECOMPOSER_OPENCLAW_SESSION_KEY_PREFIX")
        or "ads-decomposer"
    )
    resolved_model = model or os.environ.get("ADS_DECOMPOSER_OPENCLAW_MODEL")
    build_prompt = prompt_builder or _openclaw_agent_prompt

    def transport(request_payload: dict[str, Any]) -> dict[str, Any]:
        timeout = int(request_payload.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        runtime_call_id = str(request_payload.get("runtime_call_id") or stable_id("runtime", request_payload))
        session_key = f"{resolved_prefix}-{runtime_call_id}".replace(":", "-")
        command = [
            resolved_cli,
            "agent",
            "--agent",
            resolved_agent_id,
            "--session-key",
            session_key,
            "--message",
            build_prompt(request_payload),
            "--json",
            "--timeout",
            str(timeout),
        ]
        if resolved_model:
            command.extend(["--model", resolved_model])
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"OpenClaw agent transport failed: {detail[:500]}")
        response = _parse_openclaw_agent_stdout(completed.stdout)
        provider_status = copy.deepcopy(response.get("provider_status") or {})
        provider_status.update(
            {
                "transport": "openclaw_agent",
                "auth_route": "openclaw_codex_oauth",
                "agent_id": resolved_agent_id,
                "session_key": session_key,
                "provider_route": request_payload.get("provider_route"),
            }
        )
        response["provider_status"] = provider_status
        return response

    return transport


def _base_runtime_call(
    *,
    model_lane_id: str,
    provider: str,
    resolved_model_id: str,
    provider_route: str,
    prompt_template_id: str,
    prompt_template_sha256: str,
    input_manifest_refs: list[str],
    output_schema_version: str,
    request_payload: dict[str, Any],
    timeout_seconds: int,
    mode: str,
) -> dict[str, Any]:
    seed = {
        "model_lane_id": model_lane_id,
        "resolved_model_id": resolved_model_id,
        "prompt_template_sha256": prompt_template_sha256,
        "input_manifest_refs": input_manifest_refs,
        "request_sha256": prefixed_sha256(request_payload),
        "mode": mode,
    }
    return {
        "artifact_type": MODEL_RUNTIME_CALL_ARTIFACT_TYPE,
        "schema_version": MODEL_RUNTIME_CALL_SCHEMA_VERSION,
        "runtime_call_id": stable_id("model-runtime-call", seed),
        "runtime_version": MODEL_RUNTIME_VERSION,
        "model_lane_id": model_lane_id,
        "provider": provider,
        "resolved_model_id": resolved_model_id,
        "provider_route": provider_route,
        "prompt_template_id": prompt_template_id,
        "prompt_template_sha256": prompt_template_sha256,
        "input_manifest_refs": list(input_manifest_refs),
        "request_sha256": prefixed_sha256(request_payload),
        "response_sha256": None,
        "output_schema_version": output_schema_version,
        "timeout_seconds": int(timeout_seconds),
        "retry_count": 0,
        "repair_count": 0,
        "mode": mode,
        "fixture_mode": mode == "fixture",
        "model_call_performed": mode in {"fixture", "live"},
        "model_executed": mode in {"fixture", "live"},
        "execution_status": "started",
        "forbidden_output_scan": {
            "schema_version": "forbidden-model-output-scan/v1",
            "status": "not_run",
            "matches": [],
            "scanner_version": MODEL_RUNTIME_VERSION,
        },
        "latency_ms": None,
        "token_usage": None,
        "transport_retry_policy": {
            "policy_ref": MODEL_TRANSPORT_RETRY_POLICY_REF,
            "component": _model_runtime_component(model_lane_id),
            "max_attempts": MODEL_TRANSPORT_RETRY_POLICY["max_attempts"],
            "base_backoff_seconds": MODEL_TRANSPORT_RETRY_POLICY["base_backoff_seconds"],
            "max_backoff_seconds": MODEL_TRANSPORT_RETRY_POLICY["max_backoff_seconds"],
            "jitter_fraction": MODEL_TRANSPORT_RETRY_POLICY["jitter_fraction"],
        },
        "retry_diagnostics": [],
        "schema_repair_diagnostics": [],
        "runtime_reason_codes": [],
    }


def execute_model_runtime_call(
    *,
    model_lane_id: str,
    provider: str,
    resolved_model_id: str,
    provider_route: str,
    prompt_template_id: str,
    prompt_template_sha256: str,
    input_manifest_refs: list[str],
    output_schema_version: str,
    request_payload: dict[str, Any],
    mode: str,
    fixture_response: Any | None = None,
    transport: Transport | None = None,
    output_validator: OutputValidator | None = None,
    repairer: Repairer | None = None,
    timeout_seconds: int | None = None,
    max_transport_retries: int = DEFAULT_MAX_TRANSPORT_RETRIES,
    max_schema_repairs: int = DEFAULT_MAX_SCHEMA_REPAIRS,
    sleep_fn: Callable[[float], None] | None = None,
) -> ModelRuntimeResult:
    """Execute a model runtime call or explicit fixture transport.

    `mode=fixture` requires `fixture_response`. `mode=live` requires a
    transport callable. In both modes the response is scanned for forbidden
    authority-bearing outputs before schema validation or downstream use.
    """

    if mode not in {"fixture", "live", "metadata_only"}:
        raise ModelRuntimeError("mode must be fixture, live, or metadata_only")
    timeout = int(timeout_seconds or MODEL_RUNTIME_TIMEOUTS.get(model_lane_id, DEFAULT_TIMEOUT_SECONDS))
    runtime_call = _base_runtime_call(
        model_lane_id=model_lane_id,
        provider=provider,
        resolved_model_id=resolved_model_id,
        provider_route=provider_route,
        prompt_template_id=prompt_template_id,
        prompt_template_sha256=prompt_template_sha256,
        input_manifest_refs=input_manifest_refs,
        output_schema_version=output_schema_version,
        request_payload=request_payload,
        timeout_seconds=timeout,
        mode=mode,
    )
    if mode == "metadata_only":
        runtime_call["execution_status"] = "metadata_only"
        runtime_call["model_call_performed"] = False
        runtime_call["model_executed"] = False
        runtime_call["runtime_reason_codes"] = ["metadata_only_no_model_call"]
        return ModelRuntimeResult(response_payload=None, runtime_call=runtime_call)
    if mode == "fixture" and fixture_response is None:
        runtime_call["execution_status"] = "failed_missing_fixture_response"
        raise ModelRuntimeError("fixture mode requires fixture_response", runtime_call=runtime_call)
    if mode == "live" and transport is None:
        runtime_call["execution_status"] = "failed_missing_live_transport"
        raise ModelRuntimeError("live mode requires transport", runtime_call=runtime_call)

    started = time.monotonic()
    response: Any = None
    max_attempts = 1 if mode == "fixture" else _model_transport_max_attempts(max_transport_retries)
    runtime_call["transport_retry_policy"]["max_attempts"] = max_attempts
    sleep = sleep_fn or time.sleep
    attempt_number = 1
    for attempt_number in range(1, max_attempts + 1):
        try:
            if mode == "fixture":
                response = copy.deepcopy(fixture_response)
                runtime_call["runtime_reason_codes"].append("fixture_response_used")
            else:
                assert transport is not None
                raw_response = transport(
                    _transport_request(
                        runtime_call,
                        request_payload,
                        transport_attempt=attempt_number,
                        transport_max_attempts=max_attempts,
                    )
                )
                response, token_usage, provider_status = _unwrap_transport_response(raw_response)
                if token_usage is not None:
                    runtime_call["token_usage"] = token_usage
                if provider_status is not None:
                    runtime_call["provider_status"] = provider_status
                runtime_call["runtime_reason_codes"].append("live_transport_called")
            response = _json_payload(response)
            break
        except Exception as exc:  # noqa: BLE001 - runtime boundary records safe class only
            failure = _classify_model_transport_failure(exc)
            if not failure["retryable"] or attempt_number >= max_attempts:
                runtime_call["retry_count"] = max(0, attempt_number - 1)
                runtime_call["execution_status"] = "failed_transport"
                runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
                runtime_call["runtime_reason_codes"].append(str(failure["failure_class"]))
                runtime_call["runtime_reason_codes"].append(type(exc).__name__)
                terminal_event = "retry_exhausted" if failure["retryable"] else "retry_not_attempted"
                terminal_outcome = "exhausted" if failure["retryable"] else "non_retryable_failure"
                runtime_call["retry_diagnostics"].append(
                    _retry_diagnostic_event(
                        runtime_call,
                        event=terminal_event,
                        attempt=attempt_number,
                        max_attempts=max_attempts,
                        failure=failure,
                        final_retry_outcome=terminal_outcome,
                    )
                )
                raise ModelRuntimeError("model runtime transport failed", runtime_call=runtime_call) from exc
            backoff_seconds, jitter_seed, jitter_range_seconds = _model_transport_backoff(
                runtime_call_id=str(runtime_call["runtime_call_id"]),
                attempt=attempt_number,
                failure_class=str(failure["failure_class"]),
            )
            runtime_call["retry_diagnostics"].append(
                _retry_diagnostic_event(
                    runtime_call,
                    event="local_retry",
                    attempt=attempt_number,
                    max_attempts=max_attempts,
                    failure=failure,
                    backoff_seconds=backoff_seconds,
                    jitter_seed=jitter_seed,
                    jitter_range_seconds=jitter_range_seconds,
                    final_retry_outcome="retry_scheduled",
                )
            )
            runtime_call["runtime_reason_codes"].append("transport_retry")
            sleep(backoff_seconds)
    runtime_call["retry_count"] = max(0, attempt_number - 1)
    if runtime_call["retry_count"] > 0:
        runtime_call["retry_diagnostics"].append(
            _retry_diagnostic_event(
                runtime_call,
                event="retry_succeeded",
                attempt=attempt_number,
                max_attempts=max_attempts,
                final_retry_outcome="succeeded_after_retry",
            )
        )

    forbidden_scan = scan_forbidden_model_outputs(response)
    runtime_call["forbidden_output_scan"] = forbidden_scan
    runtime_call["response_sha256"] = prefixed_sha256(response)
    if forbidden_scan["status"] != "passed":
        runtime_call["execution_status"] = "failed_forbidden_output"
        runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
        raise ModelRuntimeError("model output contained forbidden authority fields", runtime_call=runtime_call)

    validation_errors: list[str] = []
    if output_validator is not None:
        valid, validation_errors = output_validator(response)
        if not valid:
            pre_repair_groups = classify_qdt_validation_errors(validation_errors)
            should_repair, repair_decision = _schema_repair_decision(
                pre_repair_groups,
                max_schema_repairs=max_schema_repairs,
                repairer_configured=repairer is not None,
            )
            repair_diagnostic: dict[str, Any] = {
                "schema_version": MODEL_RUNTIME_SCHEMA_REPAIR_DIAGNOSTIC_SCHEMA_VERSION,
                "event": "schema_repair_evaluation",
                "repair_attempted": False,
                "repair_decision": repair_decision,
                "repair_skipped_reason": None if should_repair else repair_decision,
                "pre_repair_errors": list(validation_errors),
                "pre_repair_error_groups": pre_repair_groups,
                "pre_repair_error_counts": _validation_error_group_counts(pre_repair_groups),
                "repaired_fields": [],
                "remaining_errors": list(validation_errors),
                "remaining_error_groups": pre_repair_groups,
                "remaining_error_counts": _validation_error_group_counts(pre_repair_groups),
            }
            if should_repair and repairer is not None:
                runtime_call["repair_count"] = 1
                runtime_call["runtime_reason_codes"].append("schema_repair_attempted")
                runtime_call["runtime_reason_codes"].append(repair_decision)
                original_response = copy.deepcopy(response)
                repaired = repairer(copy.deepcopy(response), list(validation_errors))
                repaired = _json_payload(repaired)
                repair_diagnostic["repair_attempted"] = True
                repair_diagnostic["repair_skipped_reason"] = None
                repair_diagnostic["repaired_fields"] = _changed_json_paths(original_response, repaired)
                repair_scan = scan_forbidden_model_outputs(repaired)
                runtime_call["forbidden_output_scan"] = repair_scan
                runtime_call["response_sha256"] = prefixed_sha256(repaired)
                if repair_scan["status"] != "passed":
                    repair_diagnostic["remaining_errors"] = [
                        "repaired_model_output_contained_forbidden_authority_fields"
                    ]
                    repair_diagnostic["remaining_error_groups"] = {
                        "forbidden_authority": repair_diagnostic["remaining_errors"],
                        "mechanical_schema": [],
                        "semantic_quality": [],
                        "terminal_temporal_role": [],
                    }
                    repair_diagnostic["remaining_error_counts"] = _validation_error_group_counts(
                        repair_diagnostic["remaining_error_groups"]
                    )
                    runtime_call["schema_repair_diagnostics"].append(repair_diagnostic)
                    runtime_call["execution_status"] = "failed_forbidden_output_after_repair"
                    runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
                    raise ModelRuntimeError(
                        "repaired model output contained forbidden authority fields",
                        runtime_call=runtime_call,
                    )
                valid, validation_errors = output_validator(repaired)
                remaining_groups = classify_qdt_validation_errors(validation_errors)
                repair_diagnostic["remaining_errors"] = list(validation_errors)
                repair_diagnostic["remaining_error_groups"] = remaining_groups
                repair_diagnostic["remaining_error_counts"] = _validation_error_group_counts(remaining_groups)
                response = repaired
                runtime_call["schema_repair_diagnostics"].append(repair_diagnostic)
                if not valid:
                    runtime_call["runtime_reason_codes"].append("schema_repair_remaining_validation_errors")
                    for group, errors in remaining_groups.items():
                        if errors:
                            runtime_call["runtime_reason_codes"].append(f"schema_repair_remaining_{group}")
            else:
                runtime_call["schema_repair_diagnostics"].append(repair_diagnostic)
                runtime_call["runtime_reason_codes"].append(f"schema_repair_skipped_{repair_decision}")
                if repairer is not None and max_schema_repairs > 0:
                    runtime_call["runtime_reason_codes"].append(
                        "schema_repair_skipped_non_repairable_validation"
                    )
        if not valid:
            runtime_call["execution_status"] = "failed_schema_validation"
            runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
            runtime_call["runtime_reason_codes"].extend(str(error) for error in validation_errors[:5])
            raise ModelRuntimeError("model output failed schema validation", runtime_call=runtime_call)

    runtime_call["response_sha256"] = prefixed_sha256(response)
    runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
    runtime_call["execution_status"] = "succeeded"
    runtime_call["runtime_reason_codes"].append("model_executed")
    runtime_call["runtime_reason_codes"].append("forbidden_output_scan_passed")
    if output_validator is not None:
        runtime_call["runtime_reason_codes"].append("output_schema_validated")
    return ModelRuntimeResult(response_payload=response, runtime_call=runtime_call)


def execute_model_runtime_call_for_lane(
    *,
    lane: dict[str, Any],
    prompt_template_id: str,
    prompt_template_sha256: str,
    input_manifest_refs: list[str],
    output_schema_version: str,
    request_payload: dict[str, Any],
    mode: str,
    fixture_response: Any | None = None,
    transport: Transport | None = None,
    output_validator: OutputValidator | None = None,
    repairer: Repairer | None = None,
    timeout_seconds: int | None = None,
    max_transport_retries: int = DEFAULT_MAX_TRANSPORT_RETRIES,
    max_schema_repairs: int = DEFAULT_MAX_SCHEMA_REPAIRS,
    sleep_fn: Callable[[float], None] | None = None,
) -> ModelRuntimeResult:
    """Execute a runtime call from a resolved model-lane policy row."""

    required = ("model_lane_id", "provider", "resolved_model_id", "provider_route")
    missing = [field for field in required if not _is_non_empty_string(lane.get(field))]
    if missing:
        raise ModelRuntimeError("resolved lane missing " + ", ".join(missing))
    return execute_model_runtime_call(
        model_lane_id=str(lane["model_lane_id"]),
        provider=str(lane["provider"]),
        resolved_model_id=str(lane["resolved_model_id"]),
        provider_route=str(lane["provider_route"]),
        prompt_template_id=prompt_template_id,
        prompt_template_sha256=prompt_template_sha256,
        input_manifest_refs=input_manifest_refs,
        output_schema_version=output_schema_version,
        request_payload=request_payload,
        mode=mode,
        fixture_response=fixture_response,
        transport=transport,
        output_validator=output_validator,
        repairer=repairer,
        timeout_seconds=timeout_seconds
        if timeout_seconds is not None
        else int(lane.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        max_transport_retries=max_transport_retries,
        max_schema_repairs=max_schema_repairs,
        sleep_fn=sleep_fn,
    )


def model_execution_context_from_runtime_call(
    base_context: dict[str, Any],
    runtime_call: dict[str, Any],
) -> dict[str, Any]:
    """Attach runtime provenance to an existing model-lane context."""

    context = copy.deepcopy(base_context)
    context.update(
        {
            "provider": runtime_call.get("provider", context.get("provider")),
            "provider_route": runtime_call.get("provider_route"),
            "runtime_call_ref": runtime_call.get("runtime_call_id"),
            "runtime_call_schema_version": runtime_call.get("schema_version"),
            "request_sha256": runtime_call.get("request_sha256"),
            "response_sha256": runtime_call.get("response_sha256"),
            "timeout_seconds": runtime_call.get("timeout_seconds"),
            "retry_count": runtime_call.get("retry_count"),
            "repair_count": runtime_call.get("repair_count"),
            "transport_retry_policy": copy.deepcopy(runtime_call.get("transport_retry_policy")),
            "retry_diagnostics": copy.deepcopy(runtime_call.get("retry_diagnostics", [])),
            "schema_repair_diagnostics": copy.deepcopy(
                runtime_call.get("schema_repair_diagnostics", [])
            ),
            "fixture_mode": runtime_call.get("fixture_mode"),
            "model_call_performed": runtime_call.get("model_call_performed"),
            "model_executed": runtime_call.get("model_executed"),
            "execution_status": runtime_call.get("execution_status"),
            "runtime_reason_codes": list(runtime_call.get("runtime_reason_codes", [])),
            "latency_ms": runtime_call.get("latency_ms"),
            "token_usage": copy.deepcopy(runtime_call.get("token_usage")),
        }
    )
    context["runtime"] = {
        "execution_mode": runtime_call.get("mode"),
        "model_call_performed": runtime_call.get("model_call_performed"),
        "model_executed": runtime_call.get("model_executed"),
        "fixture_mode": runtime_call.get("fixture_mode"),
        "runtime_call_ref": runtime_call.get("runtime_call_id"),
        "execution_status": runtime_call.get("execution_status"),
        "retry_count": runtime_call.get("retry_count"),
        "repair_count": runtime_call.get("repair_count"),
        "transport_retry_policy": copy.deepcopy(runtime_call.get("transport_retry_policy")),
        "retry_diagnostics": copy.deepcopy(runtime_call.get("retry_diagnostics", [])),
        "schema_repair_diagnostics": copy.deepcopy(runtime_call.get("schema_repair_diagnostics", [])),
        "runtime_reason_codes": list(runtime_call.get("runtime_reason_codes", [])),
        "fallback_reason_codes": list(context.get("fallback_reason_codes", ["no_fallback_required"])),
    }
    return context


__all__ = [
    "MODEL_RUNTIME_CALL_ARTIFACT_TYPE",
    "MODEL_RUNTIME_CALL_SCHEMA_VERSION",
    "MODEL_RUNTIME_RETRY_DIAGNOSTIC_SCHEMA_VERSION",
    "MODEL_RUNTIME_SCHEMA_REPAIR_DIAGNOSTIC_SCHEMA_VERSION",
    "MODEL_RUNTIME_TIMEOUTS",
    "MODEL_TRANSPORT_RETRY_POLICY",
    "MODEL_TRANSPORT_RETRY_POLICY_REF",
    "ModelRuntimeError",
    "ModelRuntimeResult",
    "classify_qdt_validation_errors",
    "execute_model_runtime_call",
    "execute_model_runtime_call_for_lane",
    "model_execution_context_from_runtime_call",
    "openclaw_codex_agent_transport_from_env",
    "prefixed_sha256",
    "resolve_model_runtime_lane",
    "scan_forbidden_model_outputs",
]
