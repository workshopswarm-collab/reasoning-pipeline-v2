"""MODEL-003 researcher leaf NLI model execution metadata helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION = "researcher-model-execution-context/v1"
RESEARCHER_MODEL_CONTEXT_RESOLVER_VERSION = "ads-model-003-researcher-model-context/v1"
RESEARCHER_MODEL_LANE_ID = "researcher_leaf_nli_classification"
RESEARCHER_MODEL_ID = "gpt-5.5-high"
RESEARCHER_PROVIDER_MODEL_KEY = "openai/gpt-5.5-high"
RESEARCHER_PROVIDER_ROUTE = "openclaw_codex_oauth/researcher-swarm"
RESEARCHER_RUNTIME_AGENT_ID = "researcher-swarm"
RESEARCHER_PROMPT_TEMPLATE_ID = "researcher-leaf-nli/v1"
RESEARCHER_SIDECAR_SCHEMA_VERSION = "researcher-sidecar/v2"
RESEARCHER_CLASSIFICATION_OUTPUT_SCHEMA_VERSION = "researcher-classification/v1"
MODEL_LANE_POLICY_SCHEMA_VERSION = "model-lane-policy/v1"
MODEL_LANE_POLICY_REF = "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json"
DEFAULT_MODEL_LANE_POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestrator"
    / "plans"
    / "autonomous-decomposition-swarm-model-lane-policy.json"
)

RESEARCHER_MODEL_REQUIRED_ARTIFACT_FIELDS = {
    "model_lane_id",
    "resolved_model_id",
    "model_policy_ref",
    "prompt_template_id",
    "prompt_template_sha256",
    "sidecar_schema_version",
    "classification_output_schema_version",
}
RESEARCHER_MODEL_FORBIDDEN_OUTPUTS = {
    "own_probability",
    "leaf_probability",
    "researcher_reassembled_probability",
    "final_macro_probability",
    "fair_value",
    "probability_interval",
}


class ResearcherModelContextError(ValueError):
    """Raised when MODEL-003 model metadata cannot be resolved or validated."""


@dataclass(frozen=True)
class ResearcherModelContextValidationResult:
    valid: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "validator_version": RESEARCHER_MODEL_CONTEXT_RESOLVER_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(str(item))]


def _default_prompt_template_sha256() -> str:
    from .classification import RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256

    return RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256


def _policy_ref_for_path(path: Path | str) -> str:
    policy_path = Path(path)
    try:
        if policy_path.resolve() == DEFAULT_MODEL_LANE_POLICY_PATH.resolve():
            return MODEL_LANE_POLICY_REF
    except FileNotFoundError:
        pass
    return str(policy_path)


def load_model_lane_policy(path: Path | str = DEFAULT_MODEL_LANE_POLICY_PATH) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResearcherModelContextError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(policy, dict):
        raise ResearcherModelContextError("model lane policy must be an object")
    return policy


def _researcher_lane_from_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("artifact_type") != "model_lane_policy":
        raise ResearcherModelContextError("model lane policy artifact_type must be model_lane_policy")
    if policy.get("schema_version") != MODEL_LANE_POLICY_SCHEMA_VERSION:
        raise ResearcherModelContextError(
            f"model lane policy schema_version must be {MODEL_LANE_POLICY_SCHEMA_VERSION}"
        )
    if not _is_non_empty_string(policy.get("policy_id")):
        raise ResearcherModelContextError("model lane policy policy_id is required")
    boundary = policy.get("authority_boundary")
    if not isinstance(boundary, dict):
        raise ResearcherModelContextError("model lane policy authority_boundary must be an object")
    for field in (
        "scae_numeric_aggregation_uses_model",
        "model_outputs_may_author_probability",
        "model_outputs_may_override_scae",
    ):
        if boundary.get(field) is not False:
            raise ResearcherModelContextError(f"authority_boundary.{field} must be false")

    lanes = policy.get("lanes")
    lane = lanes.get(RESEARCHER_MODEL_LANE_ID) if isinstance(lanes, dict) else None
    if not isinstance(lane, dict):
        raise ResearcherModelContextError(f"missing model lane {RESEARCHER_MODEL_LANE_ID}")
    if lane.get("provider") != "openai":
        raise ResearcherModelContextError("researcher leaf NLI model lane provider must be openai")
    if lane.get("default_model_id") != RESEARCHER_MODEL_ID:
        raise ResearcherModelContextError(
            f"researcher leaf NLI default_model_id must be {RESEARCHER_MODEL_ID}"
        )
    if lane.get("oauth_route_required") is not True:
        raise ResearcherModelContextError("researcher leaf NLI model lane must require OAuth route")
    if lane.get("provider_route") != RESEARCHER_PROVIDER_ROUTE:
        raise ResearcherModelContextError(
            f"researcher leaf NLI provider_route must be {RESEARCHER_PROVIDER_ROUTE}"
        )
    if lane.get("runtime_agent_id") != RESEARCHER_RUNTIME_AGENT_ID:
        raise ResearcherModelContextError(
            f"researcher leaf NLI runtime_agent_id must be {RESEARCHER_RUNTIME_AGENT_ID}"
        )
    allowed_model_ids = _string_list(lane.get("allowed_model_ids"))
    if RESEARCHER_MODEL_ID not in allowed_model_ids:
        raise ResearcherModelContextError(
            f"{RESEARCHER_MODEL_ID} must be allowed for researcher leaf NLI classification"
        )

    required_fields = set(_string_list(lane.get("required_artifact_fields")))
    missing_fields = RESEARCHER_MODEL_REQUIRED_ARTIFACT_FIELDS - required_fields
    if missing_fields:
        raise ResearcherModelContextError(
            "researcher leaf NLI model lane missing required artifact fields: "
            + ", ".join(sorted(missing_fields))
        )
    forbidden_outputs = set(_string_list(lane.get("forbidden_outputs")))
    missing_forbidden = RESEARCHER_MODEL_FORBIDDEN_OUTPUTS - forbidden_outputs
    if missing_forbidden:
        raise ResearcherModelContextError(
            "researcher leaf NLI model lane missing forbidden outputs: "
            + ", ".join(sorted(missing_forbidden))
        )
    return lane


def resolve_researcher_leaf_nli_model_context(
    *,
    model_lane_policy: dict[str, Any] | None = None,
    model_lane_policy_path: Path | str = DEFAULT_MODEL_LANE_POLICY_PATH,
    model_policy_ref: str | None = None,
    prompt_template_id: str = RESEARCHER_PROMPT_TEMPLATE_ID,
    prompt_template_sha256: str | None = None,
    sidecar_schema_version: str = RESEARCHER_SIDECAR_SCHEMA_VERSION,
    classification_output_schema_version: str = RESEARCHER_CLASSIFICATION_OUTPUT_SCHEMA_VERSION,
    requested_model_id: str | None = None,
) -> dict[str, Any]:
    """Resolve metadata for researcher leaf NLI classification without a model call."""

    policy = model_lane_policy or load_model_lane_policy(model_lane_policy_path)
    lane = _researcher_lane_from_policy(policy)
    allowed_model_ids = _string_list(lane.get("allowed_model_ids"))
    default_model_id = str(lane["default_model_id"])

    runtime_reason_codes = [
        "metadata_only_no_model_call",
        "model_policy_validated",
        "prompt_template_hash_recorded",
        "schema_metadata_recorded",
    ]
    fallback_reason_codes = ["no_fallback_required"]
    requested = requested_model_id.strip() if isinstance(requested_model_id, str) else None
    if requested:
        if requested in allowed_model_ids:
            resolved_model_id = requested
            runtime_reason_codes.append("requested_model_allowed")
        else:
            resolved_model_id = default_model_id
            runtime_reason_codes.append("requested_model_not_allowed_policy_default_used")
            fallback_reason_codes = ["requested_model_not_allowed"]
    else:
        resolved_model_id = default_model_id
        runtime_reason_codes.append("policy_default_model_selected")

    prompt_sha = prompt_template_sha256 or _default_prompt_template_sha256()
    if not _is_non_empty_string(prompt_template_id):
        raise ResearcherModelContextError("prompt_template_id is required")
    if not _is_non_empty_string(prompt_sha) or not prompt_sha.startswith("sha256:"):
        raise ResearcherModelContextError("prompt_template_sha256 must be sha256-prefixed")
    if sidecar_schema_version != RESEARCHER_SIDECAR_SCHEMA_VERSION:
        raise ResearcherModelContextError(
            f"sidecar_schema_version must be {RESEARCHER_SIDECAR_SCHEMA_VERSION}"
        )
    if classification_output_schema_version != RESEARCHER_CLASSIFICATION_OUTPUT_SCHEMA_VERSION:
        raise ResearcherModelContextError(
            "classification_output_schema_version must be "
            + RESEARCHER_CLASSIFICATION_OUTPUT_SCHEMA_VERSION
        )

    policy_ref = model_policy_ref or _policy_ref_for_path(model_lane_policy_path)
    context = {
        "artifact_type": "researcher_model_execution_context",
        "schema_version": RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION,
        "feature_id": "MODEL-003",
        "resolver_version": RESEARCHER_MODEL_CONTEXT_RESOLVER_VERSION,
        "model_lane_id": RESEARCHER_MODEL_LANE_ID,
        "provider": lane["provider"],
        "provider_route": lane["provider_route"],
        "oauth_route_required": True,
        "runtime_agent_id": lane["runtime_agent_id"],
        "default_model_id": default_model_id,
        "allowed_model_ids": allowed_model_ids,
        "resolved_model_id": resolved_model_id,
        "model_policy_ref": policy_ref,
        "model_policy_id": policy["policy_id"],
        "model_policy_schema_version": policy["schema_version"],
        "model_policy_sha256": _prefixed_sha256(policy),
        "prompt_template_id": prompt_template_id,
        "prompt_template_sha256": prompt_sha,
        "sidecar_schema_version": sidecar_schema_version,
        "classification_output_schema_version": classification_output_schema_version,
        "schema_metadata": {
            "model_context_schema_version": RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION,
            "sidecar_schema_version": sidecar_schema_version,
            "classification_output_schema_version": classification_output_schema_version,
            "prompt_template_id": prompt_template_id,
            "prompt_template_sha256": prompt_sha,
        },
        "runtime": {
            "execution_mode": "metadata_only",
            "model_call_performed": False,
            "availability_check_status": "not_checked",
            "runtime_reason_codes": list(runtime_reason_codes),
            "fallback_reason_codes": list(fallback_reason_codes),
        },
        "runtime_reason_codes": list(runtime_reason_codes),
        "fallback_reason_codes": list(fallback_reason_codes),
        "authority_boundary": {
            "model_outputs_may_author_probability": False,
            "model_outputs_may_override_scae": False,
            "scae_numeric_aggregation_uses_model": False,
        },
        "forbidden_outputs": sorted(RESEARCHER_MODEL_FORBIDDEN_OUTPUTS),
    }
    context["model_context_digest"] = _prefixed_sha256(context)
    validation = validate_researcher_model_execution_context(context)
    if not validation.valid:
        raise ResearcherModelContextError("; ".join(validation.errors))
    return context


def validate_researcher_model_execution_context(
    context: Any,
) -> ResearcherModelContextValidationResult:
    errors: list[str] = []
    if not isinstance(context, dict):
        return ResearcherModelContextValidationResult(False, ("model_execution_context must be an object",))

    expected_values = {
        "artifact_type": "researcher_model_execution_context",
        "schema_version": RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION,
        "feature_id": "MODEL-003",
        "model_lane_id": RESEARCHER_MODEL_LANE_ID,
        "provider": "openai",
        "provider_route": RESEARCHER_PROVIDER_ROUTE,
        "oauth_route_required": True,
        "runtime_agent_id": RESEARCHER_RUNTIME_AGENT_ID,
        "resolved_model_id": RESEARCHER_MODEL_ID,
        "prompt_template_id": RESEARCHER_PROMPT_TEMPLATE_ID,
        "sidecar_schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
        "classification_output_schema_version": RESEARCHER_CLASSIFICATION_OUTPUT_SCHEMA_VERSION,
    }
    for field, expected in expected_values.items():
        if context.get(field) != expected:
            errors.append(f"{field} must be {expected}")

    for field in (
        "resolver_version",
        "model_policy_ref",
        "model_policy_id",
        "model_policy_schema_version",
        "model_policy_sha256",
        "prompt_template_sha256",
        "model_context_digest",
    ):
        if not _is_non_empty_string(context.get(field)):
            errors.append(f"{field} is required")
    for field in ("model_policy_sha256", "prompt_template_sha256", "model_context_digest"):
        value = context.get(field)
        if _is_non_empty_string(value) and not str(value).startswith("sha256:"):
            errors.append(f"{field} must be sha256-prefixed")

    schema_metadata = context.get("schema_metadata")
    if not isinstance(schema_metadata, dict):
        errors.append("schema_metadata must be an object")
    else:
        if schema_metadata.get("model_context_schema_version") != RESEARCHER_MODEL_CONTEXT_SCHEMA_VERSION:
            errors.append("schema_metadata.model_context_schema_version is invalid")
        if schema_metadata.get("sidecar_schema_version") != RESEARCHER_SIDECAR_SCHEMA_VERSION:
            errors.append("schema_metadata.sidecar_schema_version is invalid")
        if (
            schema_metadata.get("classification_output_schema_version")
            != RESEARCHER_CLASSIFICATION_OUTPUT_SCHEMA_VERSION
        ):
            errors.append("schema_metadata.classification_output_schema_version is invalid")
        if schema_metadata.get("prompt_template_id") != RESEARCHER_PROMPT_TEMPLATE_ID:
            errors.append("schema_metadata.prompt_template_id is invalid")
        if schema_metadata.get("prompt_template_sha256") != context.get("prompt_template_sha256"):
            errors.append("schema_metadata.prompt_template_sha256 must match context prompt hash")

    runtime = context.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("runtime must be an object")
    else:
        execution_mode = runtime.get("execution_mode")
        if execution_mode not in {"metadata_only", "fixture", "live"}:
            errors.append("runtime.execution_mode must be metadata_only, fixture, or live")
        model_call_performed = runtime.get("model_call_performed")
        if execution_mode == "metadata_only":
            if model_call_performed is not False:
                errors.append("runtime.model_call_performed must be false for metadata_only")
            if runtime.get("availability_check_status") != "not_checked":
                errors.append("runtime.availability_check_status must be not_checked")
        else:
            if model_call_performed is not True:
                errors.append("runtime.model_call_performed must be true for model-executed contexts")
            if runtime.get("model_executed") is not True:
                errors.append("runtime.model_executed must be true for model-executed contexts")
            if runtime.get("execution_status") not in {"succeeded", "accepted"}:
                errors.append("runtime.execution_status must be succeeded or accepted for model-executed contexts")
            if not _is_non_empty_string(runtime.get("runtime_call_ref")):
                errors.append("runtime.runtime_call_ref is required for model-executed contexts")
        if runtime.get("runtime_reason_codes") != context.get("runtime_reason_codes"):
            errors.append("runtime.runtime_reason_codes must match top-level runtime_reason_codes")
        if runtime.get("fallback_reason_codes") != context.get("fallback_reason_codes"):
            errors.append("runtime.fallback_reason_codes must match top-level fallback_reason_codes")

    runtime_reason_codes = context.get("runtime_reason_codes")
    if not isinstance(runtime_reason_codes, list) or not all(
        _is_non_empty_string(code) for code in runtime_reason_codes
    ):
        errors.append("runtime_reason_codes must be a non-empty string list")
    else:
        runtime_mode = runtime.get("execution_mode") if isinstance(runtime, dict) else None
        if runtime_mode == "metadata_only" and "metadata_only_no_model_call" not in runtime_reason_codes:
            errors.append("runtime_reason_codes must include metadata_only_no_model_call")
        if runtime_mode in {"fixture", "live"} and "model_executed" not in runtime_reason_codes:
            errors.append("model-executed runtime_reason_codes must include model_executed")

    fallback_reason_codes = context.get("fallback_reason_codes")
    if not isinstance(fallback_reason_codes, list) or not all(
        _is_non_empty_string(code) for code in fallback_reason_codes
    ):
        errors.append("fallback_reason_codes must be a non-empty string list")

    authority = context.get("authority_boundary")
    if not isinstance(authority, dict):
        errors.append("authority_boundary must be an object")
    else:
        for field in (
            "model_outputs_may_author_probability",
            "model_outputs_may_override_scae",
            "scae_numeric_aggregation_uses_model",
        ):
            if authority.get(field) is not False:
                errors.append(f"authority_boundary.{field} must be false")

    forbidden_outputs = set(_string_list(context.get("forbidden_outputs")))
    missing_forbidden = RESEARCHER_MODEL_FORBIDDEN_OUTPUTS - forbidden_outputs
    if missing_forbidden:
        errors.append("forbidden_outputs missing " + ", ".join(sorted(missing_forbidden)))

    digest = context.get("model_context_digest")
    if _is_non_empty_string(digest):
        digest_input = {key: value for key, value in context.items() if key != "model_context_digest"}
        if digest != _prefixed_sha256(digest_input):
            errors.append("model_context_digest does not match context")

    return ResearcherModelContextValidationResult(not errors, tuple(errors))
