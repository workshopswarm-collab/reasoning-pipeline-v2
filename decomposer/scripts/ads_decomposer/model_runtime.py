"""Shared ADS specialist model runtime records.

The runtime boundary is intentionally small: callers own prompts, schemas, and
artifact persistence; this module owns transport policy, provenance, and
fail-closed forbidden-output scanning.
"""

from __future__ import annotations

import copy
import hashlib
import json
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
DEFAULT_MAX_TRANSPORT_RETRIES = 1
DEFAULT_MAX_SCHEMA_REPAIRS = 1
MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION = "model-runtime-transport-request/v1"
MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION = "model-runtime-transport-response/v1"
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
    return {
        "schema_version": "model-runtime-lane-resolution/v1",
        "model_lane_id": lane_id,
        "provider": provider,
        "resolved_model_id": resolved_model_id,
        "provider_route": f"{provider}/{resolved_model_id}",
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


def _collect_forbidden_outputs(value: Any, matches: list[dict[str, str]], path: str = "response") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if any(fragment in normalized for fragment in FORBIDDEN_OUTPUT_KEY_FRAGMENTS):
                matches.append({"path": f"{path}.{key}", "match_type": "key", "matched": normalized})
            _collect_forbidden_outputs(child, matches, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _collect_forbidden_outputs(child, matches, f"{path}[{idx}]")
    elif isinstance(value, str):
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


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return copy.deepcopy(value)


def _transport_request(runtime_call: dict[str, Any], request_payload: dict[str, Any]) -> dict[str, Any]:
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
    attempt = 0
    while True:
        try:
            if mode == "fixture":
                response = copy.deepcopy(fixture_response)
                runtime_call["runtime_reason_codes"].append("fixture_response_used")
            else:
                assert transport is not None
                raw_response = transport(_transport_request(runtime_call, request_payload))
                response, token_usage, provider_status = _unwrap_transport_response(raw_response)
                if token_usage is not None:
                    runtime_call["token_usage"] = token_usage
                if provider_status is not None:
                    runtime_call["provider_status"] = provider_status
                runtime_call["runtime_reason_codes"].append("live_transport_called")
            response = _json_payload(response)
            break
        except Exception as exc:  # noqa: BLE001 - runtime boundary records safe class only
            if attempt >= max_transport_retries:
                runtime_call["retry_count"] = attempt
                runtime_call["execution_status"] = "failed_transport"
                runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
                runtime_call["runtime_reason_codes"].append(type(exc).__name__)
                raise ModelRuntimeError("model runtime transport failed", runtime_call=runtime_call) from exc
            attempt += 1
            runtime_call["runtime_reason_codes"].append("transport_retry")
    runtime_call["retry_count"] = attempt

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
        if not valid and repairer is not None and max_schema_repairs > 0:
            runtime_call["repair_count"] = 1
            repaired = repairer(copy.deepcopy(response), list(validation_errors))
            repaired = _json_payload(repaired)
            repair_scan = scan_forbidden_model_outputs(repaired)
            runtime_call["forbidden_output_scan"] = repair_scan
            runtime_call["response_sha256"] = prefixed_sha256(repaired)
            if repair_scan["status"] != "passed":
                runtime_call["execution_status"] = "failed_forbidden_output_after_repair"
                runtime_call["latency_ms"] = int((time.monotonic() - started) * 1000)
                raise ModelRuntimeError("repaired model output contained forbidden authority fields", runtime_call=runtime_call)
            valid, validation_errors = output_validator(repaired)
            response = repaired
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
        timeout_seconds=timeout_seconds if timeout_seconds is not None else int(lane.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        max_transport_retries=max_transport_retries,
        max_schema_repairs=max_schema_repairs,
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
        "runtime_reason_codes": list(runtime_call.get("runtime_reason_codes", [])),
        "fallback_reason_codes": list(context.get("fallback_reason_codes", ["no_fallback_required"])),
    }
    return context


__all__ = [
    "MODEL_RUNTIME_CALL_ARTIFACT_TYPE",
    "MODEL_RUNTIME_CALL_SCHEMA_VERSION",
    "MODEL_RUNTIME_TIMEOUTS",
    "ModelRuntimeError",
    "ModelRuntimeResult",
    "execute_model_runtime_call",
    "execute_model_runtime_call_for_lane",
    "model_execution_context_from_runtime_call",
    "prefixed_sha256",
    "resolve_model_runtime_lane",
    "scan_forbidden_model_outputs",
]
