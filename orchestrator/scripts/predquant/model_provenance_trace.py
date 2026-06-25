"""MODEL-004 model provenance trace helpers for ADS v2 minimal traces."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


MODEL_PROVENANCE_TRACE_SCHEMA_VERSION = "model-provenance-trace/v1"
MODEL_PROVENANCE_TRACE_HELPER_VERSION = "ads-model-004-provenance-trace/v1"
MODEL_LANE_POLICY_SCHEMA_VERSION = "model-lane-policy/v1"
MODEL_LANE_POLICY_REF = "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json"
DEFAULT_MODEL_LANE_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "plans"
    / "autonomous-decomposition-swarm-model-lane-policy.json"
)

EXPECTED_MODEL_ID = "gpt-5.5-high"
DECOMPOSER_MODEL_LANE_ID = "decomposer_qdt_generation"
RESEARCHER_MODEL_LANE_ID = "researcher_leaf_nli_classification"
NO_LIVE_AUTHORITY = "none"

SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

AUTHORITY_BOUNDARY_FALSE_FIELDS = (
    "model_outputs_may_author_probability",
    "model_outputs_may_override_scae",
    "scae_numeric_aggregation_uses_model",
)

TRACE_REQUIRED_POLICY_FIELDS = {
    "model_lane_id",
    "resolved_model_id",
    "model_policy_ref",
    "prompt_template_id",
    "prompt_template_sha256",
    "input_artifact_hashes",
    "output_artifact_hash",
    "output_schema_version",
}

LANE_CONTRACTS: dict[str, dict[str, Any]] = {
    DECOMPOSER_MODEL_LANE_ID: {
        "source_feature_id": "MODEL-002",
        "prompt_template_id": "decomposer-qdt/v1",
        "output_schema_field": "output_schema_version",
        "default_output_schema_version": "question-decomposition/v1",
        "required_context_fields": {
            "model_lane_id",
            "resolved_model_id",
            "model_policy_ref",
            "prompt_template_id",
            "prompt_template_sha256",
            "input_manifest_ids",
            "output_schema_version",
        },
        "schema_version_fields": ("output_schema_version",),
        "forbidden_outputs": {
            "sub_forecast_probability",
            "leaf_probability",
            "macro_probability",
            "fair_value",
            "scae_delta",
        },
    },
    RESEARCHER_MODEL_LANE_ID: {
        "source_feature_id": "MODEL-003",
        "prompt_template_id": "researcher-leaf-nli/v1",
        "output_schema_field": "classification_output_schema_version",
        "default_output_schema_version": "researcher-classification/v1",
        "required_context_fields": {
            "model_lane_id",
            "resolved_model_id",
            "model_policy_ref",
            "prompt_template_id",
            "prompt_template_sha256",
            "sidecar_schema_version",
            "classification_output_schema_version",
        },
        "schema_version_fields": (
            "schema_version",
            "sidecar_schema_version",
            "classification_output_schema_version",
        ),
        "forbidden_outputs": {
            "own_probability",
            "leaf_probability",
            "researcher_reassembled_probability",
            "final_macro_probability",
            "fair_value",
            "probability_interval",
        },
    },
}

ACTIVE_FORBIDDEN_FIELD_KEYS = frozenset(
    set().union(*(contract["forbidden_outputs"] for contract in LANE_CONTRACTS.values()))
    | {
        "probability",
        "probability_estimate",
        "forecast_probability",
        "forecast_prob",
        "production_forecast_prob",
        "replacement_probability",
        "fair_value",
        "interval",
        "confidence_interval",
        "reassembly",
        "decision_recommendation",
        "recommended_decision",
        "probability_override",
    }
)


class ModelProvenanceTraceError(ValueError):
    """Raised when MODEL-004 model provenance is missing, unsafe, or invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def is_sha256_ref(value: Any) -> bool:
    return isinstance(value, str) and SHA256_REF_RE.fullmatch(value) is not None


def _require_string(field: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelProvenanceTraceError(f"{field} is required")
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _load_model_lane_policy(path: Path | str) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelProvenanceTraceError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(policy, dict):
        raise ModelProvenanceTraceError("model lane policy must be an object")
    return policy


def _validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("artifact_type") != "model_lane_policy":
        raise ModelProvenanceTraceError("model lane policy artifact_type must be model_lane_policy")
    if policy.get("schema_version") != MODEL_LANE_POLICY_SCHEMA_VERSION:
        raise ModelProvenanceTraceError(
            f"model lane policy schema_version must be {MODEL_LANE_POLICY_SCHEMA_VERSION}"
        )
    _require_string("model lane policy policy_id", policy.get("policy_id"))

    boundary = policy.get("authority_boundary")
    if not isinstance(boundary, dict):
        raise ModelProvenanceTraceError("model lane policy authority_boundary must be an object")
    for field in AUTHORITY_BOUNDARY_FALSE_FIELDS:
        if boundary.get(field) is not False:
            raise ModelProvenanceTraceError(f"authority_boundary.{field} must be false")

    trace_requirements = policy.get("trace_requirements")
    if not isinstance(trace_requirements, dict):
        raise ModelProvenanceTraceError("model lane policy trace_requirements must be an object")
    if trace_requirements.get("owner_feature_id") != "MODEL-004":
        raise ModelProvenanceTraceError("trace_requirements.owner_feature_id must be MODEL-004")
    required_trace_fields = set(_string_list(trace_requirements.get("training_trace_minimal_must_record")))
    missing_trace_fields = TRACE_REQUIRED_POLICY_FIELDS - required_trace_fields
    if missing_trace_fields:
        raise ModelProvenanceTraceError(
            "trace_requirements.training_trace_minimal_must_record missing "
            + ", ".join(sorted(missing_trace_fields))
        )

    lanes = policy.get("lanes")
    if not isinstance(lanes, dict):
        raise ModelProvenanceTraceError("model lane policy lanes must be an object")
    for lane_id, contract in LANE_CONTRACTS.items():
        lane = lanes.get(lane_id)
        if not isinstance(lane, dict):
            raise ModelProvenanceTraceError(f"missing model lane {lane_id}")
        if lane.get("provider") != "openai":
            raise ModelProvenanceTraceError(f"{lane_id} provider must be openai")
        if lane.get("default_model_id") != EXPECTED_MODEL_ID:
            raise ModelProvenanceTraceError(f"{lane_id} default_model_id must be {EXPECTED_MODEL_ID}")
        if EXPECTED_MODEL_ID not in _string_list(lane.get("allowed_model_ids")):
            raise ModelProvenanceTraceError(f"{lane_id} must allow {EXPECTED_MODEL_ID}")
        if lane.get("owner_feature_id") != contract["source_feature_id"]:
            raise ModelProvenanceTraceError(f"{lane_id} owner_feature_id must be {contract['source_feature_id']}")

        required_fields = set(_string_list(lane.get("required_artifact_fields")))
        missing_fields = contract["required_context_fields"] - required_fields
        if missing_fields:
            raise ModelProvenanceTraceError(
                f"{lane_id} missing required artifact fields: " + ", ".join(sorted(missing_fields))
            )
        forbidden_outputs = set(_string_list(lane.get("forbidden_outputs")))
        missing_forbidden = contract["forbidden_outputs"] - forbidden_outputs
        if missing_forbidden:
            raise ModelProvenanceTraceError(
                f"{lane_id} missing forbidden outputs: " + ", ".join(sorted(missing_forbidden))
            )


def _reject_active_forbidden_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized.startswith("forbidden_"):
                continue
            if normalized in ACTIVE_FORBIDDEN_FIELD_KEYS:
                raise ModelProvenanceTraceError(f"{path}.{key} may not author or replace forecast probability")
            _reject_active_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_active_forbidden_fields(child, f"{path}[{idx}]")


def _validate_no_live_or_probability_authority(record: dict[str, Any], context: dict[str, Any], path: str) -> None:
    for source_name, source in (("record", record), ("model_execution_context", context)):
        live_authority = source.get("live_authority")
        if live_authority not in (None, False, NO_LIVE_AUTHORITY):
            raise ModelProvenanceTraceError(f"{path}.{source_name}.live_authority must be {NO_LIVE_AUTHORITY}")
        if source.get("live_forecast_authority") not in (None, False, 0):
            raise ModelProvenanceTraceError(f"{path}.{source_name}.live_forecast_authority must be false")
        if source.get("forecast_authority") not in (None, False, NO_LIVE_AUTHORITY):
            raise ModelProvenanceTraceError(f"{path}.{source_name}.forecast_authority must be false")

    runtime = context.get("runtime")
    if isinstance(runtime, dict) and runtime.get("model_call_performed") is not False:
        raise ModelProvenanceTraceError(f"{path}.model_execution_context.runtime.model_call_performed must be false")

    authority = context.get("authority_boundary")
    if isinstance(authority, dict):
        for field in AUTHORITY_BOUNDARY_FALSE_FIELDS:
            if field in authority and authority.get(field) is not False:
                raise ModelProvenanceTraceError(f"{path}.model_execution_context.authority_boundary.{field} must be false")


def _validate_artifact_hashes(field: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ModelProvenanceTraceError(f"{field} must be a non-empty object")
    normalized: dict[str, str] = {}
    for artifact_id, artifact_hash in value.items():
        artifact_key = _require_string(f"{field} artifact id", artifact_id)
        if not is_sha256_ref(artifact_hash):
            raise ModelProvenanceTraceError(f"{field}[{artifact_key}] must be a sha256 ref")
        normalized[artifact_key] = str(artifact_hash)
    return dict(sorted(normalized.items()))


def _input_artifact_hashes(record: dict[str, Any], context: dict[str, Any], path: str) -> dict[str, str]:
    explicit = record.get("input_artifact_hashes")
    if explicit is None:
        explicit = context.get("input_artifact_hashes")

    input_manifest_ids = _string_list(context.get("input_manifest_ids"))
    if explicit is None and input_manifest_ids:
        artifact_hashes = record.get("artifact_hashes") or record.get("trace_artifact_hashes")
        if isinstance(artifact_hashes, dict):
            missing = [artifact_id for artifact_id in input_manifest_ids if artifact_id not in artifact_hashes]
            if missing:
                raise ModelProvenanceTraceError(
                    f"{path}.artifact_hashes missing input manifest hashes: " + ", ".join(sorted(missing))
                )
            explicit = {artifact_id: artifact_hashes[artifact_id] for artifact_id in input_manifest_ids}

    normalized = _validate_artifact_hashes(f"{path}.input_artifact_hashes", explicit)
    missing_manifest_hashes = [artifact_id for artifact_id in input_manifest_ids if artifact_id not in normalized]
    if missing_manifest_hashes:
        raise ModelProvenanceTraceError(
            f"{path}.input_artifact_hashes missing input manifest hashes: "
            + ", ".join(sorted(missing_manifest_hashes))
        )
    return normalized


def _output_artifact_hash(record: dict[str, Any], context: dict[str, Any], path: str) -> str:
    artifact_hash = record.get("output_artifact_hash") or context.get("output_artifact_hash")
    if not is_sha256_ref(artifact_hash):
        raise ModelProvenanceTraceError(f"{path}.output_artifact_hash must be a sha256 ref")
    return str(artifact_hash)


def _schema_versions(
    record: dict[str, Any],
    context: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    output_schema_version = (
        record.get("output_schema_version")
        or context.get(contract["output_schema_field"])
        or contract["default_output_schema_version"]
    )
    _require_string("output_schema_version", output_schema_version)
    schema_versions: dict[str, str] = {"output_schema_version": str(output_schema_version)}
    for field in contract["schema_version_fields"]:
        value = context.get(field)
        if isinstance(value, str) and value.strip():
            schema_versions[field] = value
    return str(output_schema_version), dict(sorted(schema_versions.items()))


def _context_from_record(record: Any, idx: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(record, dict):
        raise ModelProvenanceTraceError(f"model_execution_contexts[{idx}] must be an object")
    context = record.get("model_execution_context") if "model_execution_context" in record else record
    if not isinstance(context, dict):
        raise ModelProvenanceTraceError(f"model_execution_contexts[{idx}].model_execution_context must be an object")
    return record, context


def _normalize_model_record(record: Any, idx: int, policy: dict[str, Any], policy_hash: str) -> dict[str, Any]:
    record, context = _context_from_record(record, idx)
    path = f"model_execution_contexts[{idx}]"
    _reject_active_forbidden_fields(record, path)

    lane_id = _require_string(f"{path}.model_execution_context.model_lane_id", context.get("model_lane_id"))
    contract = LANE_CONTRACTS.get(lane_id)
    if contract is None:
        raise ModelProvenanceTraceError(f"{path}.model_execution_context.model_lane_id is unsupported: {lane_id}")

    for field in sorted(contract["required_context_fields"]):
        if field not in context:
            raise ModelProvenanceTraceError(f"{path}.model_execution_context missing {field}")

    if context.get("resolved_model_id") != EXPECTED_MODEL_ID:
        raise ModelProvenanceTraceError(f"{path}.resolved_model_id must be {EXPECTED_MODEL_ID}")
    if context.get("prompt_template_id") != contract["prompt_template_id"]:
        raise ModelProvenanceTraceError(f"{path}.prompt_template_id must be {contract['prompt_template_id']}")
    if not is_sha256_ref(context.get("prompt_template_sha256")):
        raise ModelProvenanceTraceError(f"{path}.prompt_template_sha256 must be a sha256 ref")

    model_policy_ref = _require_string(f"{path}.model_policy_ref", context.get("model_policy_ref"))
    model_policy_id = context.get("model_policy_id", policy["policy_id"])
    if model_policy_id != policy["policy_id"]:
        raise ModelProvenanceTraceError(f"{path}.model_policy_id must be {policy['policy_id']}")
    context_policy_hash = context.get("model_policy_sha256")
    if context_policy_hash is not None and context_policy_hash != policy_hash:
        raise ModelProvenanceTraceError(f"{path}.model_policy_sha256 does not match model lane policy")

    _validate_no_live_or_probability_authority(record, context, path)

    input_hashes = _input_artifact_hashes(record, context, path)
    output_hash = _output_artifact_hash(record, context, path)
    output_schema_version, schema_versions = _schema_versions(record, context, contract)
    source_context_digest = context.get("model_context_digest")
    if source_context_digest is not None and not is_sha256_ref(source_context_digest):
        raise ModelProvenanceTraceError(f"{path}.model_context_digest must be a sha256 ref")

    source_feature_id = context.get("feature_id") or contract["source_feature_id"]
    if source_feature_id != contract["source_feature_id"]:
        raise ModelProvenanceTraceError(f"{path}.feature_id must be {contract['source_feature_id']}")

    normalized = {
        "source_feature_id": source_feature_id,
        "model_lane_id": lane_id,
        "resolved_model_id": EXPECTED_MODEL_ID,
        "model_policy_ref": model_policy_ref,
        "model_policy_id": policy["policy_id"],
        "model_policy_sha256": policy_hash,
        "prompt_template_id": context["prompt_template_id"],
        "prompt_template_sha256": context["prompt_template_sha256"],
        "input_artifact_hashes": input_hashes,
        "output_artifact_hash": output_hash,
        "output_schema_version": output_schema_version,
        "schema_versions": schema_versions,
        "source_context_sha256": prefixed_sha256(context),
        "authority_boundary": {
            "live_authority": NO_LIVE_AUTHORITY,
            "live_forecast_authority": False,
            "model_outputs_may_author_probability": False,
            "model_outputs_may_override_scae": False,
            "scae_numeric_aggregation_uses_model": False,
        },
        "forbidden_outputs": sorted(contract["forbidden_outputs"]),
    }
    output_artifact_id = record.get("output_artifact_id") or context.get("output_artifact_id")
    if output_artifact_id is not None:
        normalized["output_artifact_id"] = _require_string(f"{path}.output_artifact_id", output_artifact_id)
    if source_context_digest is not None:
        normalized["source_model_context_digest"] = source_context_digest
    if "provenance_status" in context:
        normalized["provenance_status"] = context["provenance_status"]
    return normalized


def collect_model_execution_contexts(artifacts: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    """Collect decomposer/researcher model_execution_context objects from artifacts."""

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            context = value.get("model_execution_context")
            if isinstance(context, dict) and context.get("model_lane_id") in LANE_CONTRACTS:
                digest = prefixed_sha256(context)
                if digest not in seen:
                    seen.add(digest)
                    collected.append(copy.deepcopy(context))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(list(artifacts))
    return collected


def build_model_provenance_trace(
    *,
    model_execution_contexts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    model_lane_policy: dict[str, Any] | None = None,
    model_lane_policy_path: Path | str = DEFAULT_MODEL_LANE_POLICY_PATH,
) -> dict[str, Any]:
    """Build a deterministic MODEL-004 payload safe for minimal trace metadata."""

    if not isinstance(model_execution_contexts, (list, tuple)) or not model_execution_contexts:
        raise ModelProvenanceTraceError("model_execution_contexts must contain at least one context")

    policy = copy.deepcopy(model_lane_policy) if model_lane_policy is not None else _load_model_lane_policy(model_lane_policy_path)
    _validate_policy(policy)
    policy_hash = prefixed_sha256(policy)
    contexts = [
        _normalize_model_record(record, idx, policy, policy_hash)
        for idx, record in enumerate(model_execution_contexts)
    ]
    contexts.sort(
        key=lambda item: (
            item["model_lane_id"],
            item.get("output_artifact_id", ""),
            item["output_artifact_hash"],
            item["source_context_sha256"],
        )
    )

    trace = {
        "schema_version": MODEL_PROVENANCE_TRACE_SCHEMA_VERSION,
        "helper_version": MODEL_PROVENANCE_TRACE_HELPER_VERSION,
        "model_policy_ref": MODEL_LANE_POLICY_REF,
        "model_policy_id": policy["policy_id"],
        "model_policy_schema_version": policy["schema_version"],
        "model_policy_sha256": policy_hash,
        "context_count": len(contexts),
        "model_execution_contexts": contexts,
        "resolved_model_ids": {
            context["model_lane_id"]: context["resolved_model_id"]
            for context in contexts
        },
        "lane_ids": sorted({context["model_lane_id"] for context in contexts}),
        "live_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "no_model_call_performed_by_trace_helper": True,
        "no_probability_authority": True,
        "no_production_probability_authoring": True,
        "no_replay_scoring_or_calibration_writes": True,
        "full_trace_materialization_authority": False,
    }
    trace["model_provenance_trace_digest"] = prefixed_sha256(trace)
    validate_model_provenance_trace(trace)
    return trace


def validate_model_provenance_trace(trace: Any) -> None:
    if not isinstance(trace, dict):
        raise ModelProvenanceTraceError("model provenance trace must be an object")
    if trace.get("schema_version") != MODEL_PROVENANCE_TRACE_SCHEMA_VERSION:
        raise ModelProvenanceTraceError(f"schema_version must be {MODEL_PROVENANCE_TRACE_SCHEMA_VERSION}")
    if trace.get("helper_version") != MODEL_PROVENANCE_TRACE_HELPER_VERSION:
        raise ModelProvenanceTraceError(f"helper_version must be {MODEL_PROVENANCE_TRACE_HELPER_VERSION}")
    if trace.get("live_authority") != NO_LIVE_AUTHORITY:
        raise ModelProvenanceTraceError("model provenance trace has no live authority")
    if trace.get("live_forecast_authority") not in (False, 0):
        raise ModelProvenanceTraceError("model provenance trace cannot have live forecast authority")
    for field in (
        "no_model_call_performed_by_trace_helper",
        "no_probability_authority",
        "no_production_probability_authoring",
        "no_replay_scoring_or_calibration_writes",
    ):
        if trace.get(field) is not True:
            raise ModelProvenanceTraceError(f"{field} must be true")
    if trace.get("full_trace_materialization_authority") is not False:
        raise ModelProvenanceTraceError("full_trace_materialization_authority must be false")
    if not is_sha256_ref(trace.get("model_policy_sha256")):
        raise ModelProvenanceTraceError("model_policy_sha256 must be a sha256 ref")

    contexts = trace.get("model_execution_contexts")
    if not isinstance(contexts, list) or not contexts:
        raise ModelProvenanceTraceError("model_execution_contexts are required")
    if trace.get("context_count") != len(contexts):
        raise ModelProvenanceTraceError("context_count must match model_execution_contexts")
    for idx, context in enumerate(contexts):
        prefix = f"model_execution_contexts[{idx}]"
        lane_id = _require_string(f"{prefix}.model_lane_id", context.get("model_lane_id"))
        if lane_id not in LANE_CONTRACTS:
            raise ModelProvenanceTraceError(f"{prefix}.model_lane_id is unsupported: {lane_id}")
        if context.get("resolved_model_id") != EXPECTED_MODEL_ID:
            raise ModelProvenanceTraceError(f"{prefix}.resolved_model_id must be {EXPECTED_MODEL_ID}")
        for field in (
            "model_policy_ref",
            "model_policy_id",
            "prompt_template_id",
            "output_schema_version",
            "source_feature_id",
        ):
            _require_string(f"{prefix}.{field}", context.get(field))
        for field in (
            "model_policy_sha256",
            "prompt_template_sha256",
            "source_context_sha256",
            "output_artifact_hash",
        ):
            if not is_sha256_ref(context.get(field)):
                raise ModelProvenanceTraceError(f"{prefix}.{field} must be a sha256 ref")
        _validate_artifact_hashes(f"{prefix}.input_artifact_hashes", context.get("input_artifact_hashes"))
        authority = context.get("authority_boundary")
        if not isinstance(authority, dict) or authority.get("live_authority") != NO_LIVE_AUTHORITY:
            raise ModelProvenanceTraceError(f"{prefix}.authority_boundary.live_authority must be {NO_LIVE_AUTHORITY}")
        if authority.get("live_forecast_authority") is not False:
            raise ModelProvenanceTraceError(f"{prefix}.authority_boundary.live_forecast_authority must be false")

    digest = trace.get("model_provenance_trace_digest")
    if not is_sha256_ref(digest):
        raise ModelProvenanceTraceError("model_provenance_trace_digest must be a sha256 ref")
    digest_input = {key: value for key, value in trace.items() if key != "model_provenance_trace_digest"}
    if digest != prefixed_sha256(digest_input):
        raise ModelProvenanceTraceError("model_provenance_trace_digest does not match trace")
