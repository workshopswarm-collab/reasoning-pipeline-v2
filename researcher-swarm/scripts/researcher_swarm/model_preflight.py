"""RET-007 local embedding/reranker preflight reporting contract."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LOCAL_MODEL_PREFLIGHT_CONTRACT_SCHEMA_VERSION = "local-model-preflight-contract/v1"
LOCAL_MODEL_PREFLIGHT_SLICE_SCHEMA_VERSION = "local-model-preflight-slice/v1"
LOCAL_MODEL_PREFLIGHT_REPORT_SCHEMA_VERSION = "local-model-preflight-report/v1"
LOCAL_MODEL_PREFLIGHT_VERSION = "ads-ret-007-local-model-preflight/v1"

DEFAULT_EMBEDDING_MODEL_ID = "BAAI/bge-base-en-v1.5"
DEFAULT_RERANKER_MODEL_ID = "BAAI/bge-reranker-base"
DEFAULT_RESOURCE_CAPS = {
    "max_embedding_batch_size": 32,
    "max_reranker_candidates": 50,
    "max_context_tokens": 8192,
    "min_available_memory_mb": 4096,
    "max_declared_model_memory_mb": 8192,
}

FORBIDDEN_RETRIEVAL_KEY_FRAGMENTS = (
    "probability",
    "forecast_probability",
    "production_forecast_prob",
    "fair_value",
    "scae_delta",
    "log_odds",
    "synthesis_conclusion",
    "decision_instruction",
)


class LocalModelPreflightError(ValueError):
    """Raised when a RET-007 local model preflight report is invalid."""


@dataclass(frozen=True)
class LocalModelPreflightValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": LOCAL_MODEL_PREFLIGHT_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _reject_forbidden_keys(value: Any, errors: list[str], path: str = "local_model_preflight") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_RETRIEVAL_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in RET-007 local model preflight artifacts")
            _reject_forbidden_keys(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_forbidden_keys(child, errors, f"{path}[{idx}]")


def _compact_reason_codes(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item) and len(item) <= 80 and " " not in item
        for item in value
    )


def load_model_lane_policy(path: Path | str) -> dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise LocalModelPreflightError(f"{path} must contain a JSON object")
    return loaded


def _embedding_model_from_policy(model_lane_policy: dict[str, Any] | None) -> tuple[str, str | None]:
    lanes = (model_lane_policy or {}).get("local_embedding_lanes")
    if not isinstance(lanes, dict):
        return DEFAULT_EMBEDDING_MODEL_ID, None
    lane = lanes.get("amrg_vector_embedding")
    if not isinstance(lane, dict):
        return DEFAULT_EMBEDDING_MODEL_ID, None
    model_id = lane.get("default_model_id")
    return (
        model_id if isinstance(model_id, str) and model_id else DEFAULT_EMBEDDING_MODEL_ID,
        "amrg_vector_embedding",
    )


def build_local_model_preflight_contract(
    *,
    model_lane_policy: dict[str, Any] | None = None,
    resource_caps: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a report-only RET-007 local model preflight contract."""

    embedding_model_id, policy_source_lane_id = _embedding_model_from_policy(model_lane_policy)
    caps = {**DEFAULT_RESOURCE_CAPS, **(resource_caps or {})}
    contract = {
        "artifact_type": "local_model_preflight_contract",
        "schema_version": LOCAL_MODEL_PREFLIGHT_CONTRACT_SCHEMA_VERSION,
        "feature_id": "RET-007",
        "preflight_version": LOCAL_MODEL_PREFLIGHT_VERSION,
        "contract_id": _sha_id(
            "local-model-preflight-contract",
            {
                "embedding_model_id": embedding_model_id,
                "reranker_model_id": DEFAULT_RERANKER_MODEL_ID,
                "caps": caps,
            },
        ),
        "resource_caps": caps,
        "side_effect_policy": {
            "downloads_models": False,
            "runs_long_model_tasks": False,
            "modifies_global_model_defaults": False,
            "uses_observed_state_only": True,
        },
        "lanes": [
            {
                "lane_id": "retrieval_local_embedding",
                "lane_role": "embedding",
                "provider": "ollama",
                "route_id": "ollama/local",
                "resolved_model_id": embedding_model_id,
                "policy_source_lane_id": policy_source_lane_id,
                "required": True,
                "download_allowed": False,
                "smoke_test_required": True,
                "capability_requirements": ["embedding"],
                "required_memory_mb": 2048,
            },
            {
                "lane_id": "retrieval_local_reranker",
                "lane_role": "reranker",
                "provider": "local",
                "route_id": "local/reranker",
                "resolved_model_id": DEFAULT_RERANKER_MODEL_ID,
                "policy_source_lane_id": None,
                "required": True,
                "download_allowed": False,
                "smoke_test_required": True,
                "capability_requirements": ["rerank"],
                "required_memory_mb": 4096,
            },
        ],
    }
    validation = validate_local_model_preflight_contract(contract)
    if not validation.valid:
        raise LocalModelPreflightError("; ".join(validation.errors))
    return contract


def _observed_route(observed_state: dict[str, Any], route_id: str) -> dict[str, Any]:
    routes = observed_state.get("routes")
    if not isinstance(routes, dict):
        return {}
    route = routes.get(route_id)
    return route if isinstance(route, dict) else {}


def _observed_model(observed_state: dict[str, Any], model_id: str) -> dict[str, Any]:
    models = observed_state.get("models")
    if not isinstance(models, dict):
        return {}
    model = models.get(model_id)
    return model if isinstance(model, dict) else {}


def _resource_snapshot(observed_state: dict[str, Any]) -> dict[str, Any]:
    snapshot = observed_state.get("resource_snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _configured_value(snapshot: dict[str, Any], key: str) -> int | None:
    value = snapshot.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _resource_reason_codes(
    lane: dict[str, Any],
    resource_caps: dict[str, int],
    snapshot: dict[str, Any],
) -> tuple[list[str], list[str]]:
    unavailable: list[str] = []
    blocked: list[str] = []
    if not snapshot:
        return ["resource_snapshot_missing"], []

    available_memory = _configured_value(snapshot, "available_memory_mb")
    if available_memory is None:
        unavailable.append("available_memory_unknown")
    elif available_memory < int(lane.get("required_memory_mb", 0)):
        blocked.append("available_memory_below_lane_requirement")
    elif available_memory < int(resource_caps.get("min_available_memory_mb", 0)):
        blocked.append("available_memory_below_preflight_cap")

    declared_model_memory = _configured_value(snapshot, "declared_model_memory_mb")
    if declared_model_memory is not None and declared_model_memory > int(resource_caps["max_declared_model_memory_mb"]):
        blocked.append("declared_model_memory_exceeds_cap")

    embedding_batch_size = _configured_value(snapshot, "configured_embedding_batch_size")
    if embedding_batch_size is not None and embedding_batch_size > int(resource_caps["max_embedding_batch_size"]):
        blocked.append("embedding_batch_size_exceeds_cap")

    reranker_candidates = _configured_value(snapshot, "configured_reranker_candidates")
    if reranker_candidates is not None and reranker_candidates > int(resource_caps["max_reranker_candidates"]):
        blocked.append("reranker_candidate_count_exceeds_cap")

    context_tokens = _configured_value(snapshot, "configured_context_tokens")
    if context_tokens is not None and context_tokens > int(resource_caps["max_context_tokens"]):
        blocked.append("context_tokens_exceed_cap")

    if snapshot.get("download_attempted") is True:
        blocked.append("download_attempted_during_preflight")
    if snapshot.get("model_invocation_attempted") is True:
        blocked.append("model_invocation_attempted_during_preflight")
    return unavailable, blocked


def evaluate_local_model_preflight_slice(
    lane: dict[str, Any],
    *,
    contract: dict[str, Any],
    observed_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one preflight lane from supplied observations only."""

    observed_state = observed_state or {}
    route = _observed_route(observed_state, str(lane.get("route_id")))
    model = _observed_model(observed_state, str(lane.get("resolved_model_id")))
    snapshot = _resource_snapshot(observed_state)
    unavailable_reasons: list[str] = []
    block_reasons: list[str] = []

    if route.get("available") is not True:
        unavailable_reasons.append("route_unavailable")
    if model.get("available") is not True:
        unavailable_reasons.append("model_unavailable")

    smoke_status = model.get("smoke_test_status")
    if smoke_status == "pass":
        pass
    elif smoke_status in {"fail", "failed", "timeout", "error"}:
        block_reasons.append("smoke_test_failed")
    else:
        unavailable_reasons.append("smoke_test_not_run")

    observed_capabilities = model.get("capabilities", [])
    if model.get("available") is True and isinstance(observed_capabilities, list):
        missing = [
            item
            for item in lane.get("capability_requirements", [])
            if item not in observed_capabilities
        ]
        if missing:
            block_reasons.append("capability_missing")

    resource_unavailable, resource_blocked = _resource_reason_codes(
        lane,
        contract["resource_caps"],
        snapshot,
    )
    unavailable_reasons.extend(resource_unavailable)
    block_reasons.extend(resource_blocked)

    if block_reasons:
        status = "block"
        reason_codes = sorted(set(block_reasons + unavailable_reasons))
    elif unavailable_reasons:
        status = "unavailable"
        reason_codes = sorted(set(unavailable_reasons))
    else:
        status = "pass"
        reason_codes = ["preflight_passed_report_only"]

    slice_value = {
        "artifact_type": "local_model_preflight_slice",
        "schema_version": LOCAL_MODEL_PREFLIGHT_SLICE_SCHEMA_VERSION,
        "slice_id": _sha_id(
            "local-model-preflight",
            {
                "contract_id": contract.get("contract_id"),
                "lane_id": lane.get("lane_id"),
                "model_id": lane.get("resolved_model_id"),
                "status": status,
                "reasons": reason_codes,
            },
        ),
        "feature_id": "RET-007",
        "lane_id": lane.get("lane_id"),
        "lane_role": lane.get("lane_role"),
        "provider": lane.get("provider"),
        "route_id": lane.get("route_id"),
        "resolved_model_id": lane.get("resolved_model_id"),
        "required": lane.get("required") is True,
        "preflight_status": status,
        "reason_codes": reason_codes,
        "resource_caps": copy.deepcopy(contract["resource_caps"]),
        "observed_state_refs": {
            "route_observed": bool(route),
            "model_observed": bool(model),
            "resource_snapshot_observed": bool(snapshot),
        },
        "side_effect_policy": copy.deepcopy(contract["side_effect_policy"]),
    }
    validation = validate_local_model_preflight_slice(slice_value)
    if not validation.valid:
        raise LocalModelPreflightError("; ".join(validation.errors))
    return slice_value


def evaluate_local_model_preflight(
    *,
    contract: dict[str, Any] | None = None,
    model_lane_policy: dict[str, Any] | None = None,
    observed_state: dict[str, Any] | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic RET-007 report without pulling or invoking models."""

    contract = contract or build_local_model_preflight_contract(model_lane_policy=model_lane_policy)
    contract_validation = validate_local_model_preflight_contract(contract)
    if not contract_validation.valid:
        raise LocalModelPreflightError("; ".join(contract_validation.errors))

    observed_state = observed_state or {}
    slices = [
        evaluate_local_model_preflight_slice(lane, contract=contract, observed_state=observed_state)
        for lane in contract["lanes"]
    ]
    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for slice_value in slices:
        status_counts[slice_value["preflight_status"]] = status_counts.get(slice_value["preflight_status"], 0) + 1
        for code in slice_value["reason_codes"]:
            reason_counts[code] = reason_counts.get(code, 0) + 1
    if status_counts.get("block", 0):
        gate = "block"
    elif status_counts.get("unavailable", 0):
        gate = "unavailable"
    else:
        gate = "pass"
    report = {
        "artifact_type": "local_model_preflight_report",
        "schema_version": LOCAL_MODEL_PREFLIGHT_REPORT_SCHEMA_VERSION,
        "feature_id": "RET-007",
        "checked_at": checked_at,
        "preflight_version": LOCAL_MODEL_PREFLIGHT_VERSION,
        "contract_id": contract["contract_id"],
        "resource_caps": copy.deepcopy(contract["resource_caps"]),
        "side_effect_policy": copy.deepcopy(contract["side_effect_policy"]),
        "local_model_preflight_slices": slices,
        "preflight_summary": {
            "live_retrieval_gate": gate,
            "all_required_lanes_pass": gate == "pass",
            "passed_lane_count": status_counts.get("pass", 0),
            "unavailable_lane_count": status_counts.get("unavailable", 0),
            "blocked_lane_count": status_counts.get("block", 0),
            "reason_counts": dict(sorted(reason_counts.items())),
        },
    }
    validation = validate_local_model_preflight_report(report)
    if not validation.valid:
        raise LocalModelPreflightError("; ".join(validation.errors))
    return report


def validate_local_model_preflight_contract(contract: Any) -> LocalModelPreflightValidationResult:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return LocalModelPreflightValidationResult(False, ("contract must be an object",))
    _reject_forbidden_keys(contract, errors, "local_model_preflight_contract")
    if contract.get("artifact_type") != "local_model_preflight_contract":
        errors.append("contract.artifact_type must be local_model_preflight_contract")
    if contract.get("schema_version") != LOCAL_MODEL_PREFLIGHT_CONTRACT_SCHEMA_VERSION:
        errors.append(f"contract.schema_version must be {LOCAL_MODEL_PREFLIGHT_CONTRACT_SCHEMA_VERSION}")
    if contract.get("feature_id") != "RET-007":
        errors.append("contract.feature_id must be RET-007")
    if not isinstance(contract.get("resource_caps"), dict):
        errors.append("contract.resource_caps must be an object")
    if not isinstance(contract.get("lanes"), list) or not contract.get("lanes"):
        errors.append("contract.lanes must be a non-empty list")
    side_effect_policy = contract.get("side_effect_policy")
    if not isinstance(side_effect_policy, dict) or any(side_effect_policy.get(field) is not False for field in (
        "downloads_models",
        "runs_long_model_tasks",
        "modifies_global_model_defaults",
    )):
        errors.append("contract.side_effect_policy must deny downloads, long tasks, and global default changes")
    return LocalModelPreflightValidationResult(not errors, tuple(errors))


def validate_local_model_preflight_slice(slice_value: Any) -> LocalModelPreflightValidationResult:
    errors: list[str] = []
    if not isinstance(slice_value, dict):
        return LocalModelPreflightValidationResult(False, ("slice must be an object",))
    _reject_forbidden_keys(slice_value, errors, "local_model_preflight_slice")
    for field in (
        "artifact_type",
        "schema_version",
        "slice_id",
        "feature_id",
        "lane_id",
        "lane_role",
        "route_id",
        "resolved_model_id",
        "preflight_status",
        "reason_codes",
        "resource_caps",
        "side_effect_policy",
    ):
        if field not in slice_value:
            errors.append(f"slice missing {field}")
    if slice_value.get("artifact_type") != "local_model_preflight_slice":
        errors.append("slice.artifact_type must be local_model_preflight_slice")
    if slice_value.get("schema_version") != LOCAL_MODEL_PREFLIGHT_SLICE_SCHEMA_VERSION:
        errors.append(f"slice.schema_version must be {LOCAL_MODEL_PREFLIGHT_SLICE_SCHEMA_VERSION}")
    if slice_value.get("feature_id") != "RET-007":
        errors.append("slice.feature_id must be RET-007")
    if slice_value.get("preflight_status") not in {"pass", "unavailable", "block"}:
        errors.append("slice.preflight_status is invalid")
    if not _compact_reason_codes(slice_value.get("reason_codes")):
        errors.append("slice.reason_codes must be compact reason codes")
    side_effect_policy = slice_value.get("side_effect_policy")
    if not isinstance(side_effect_policy, dict) or any(side_effect_policy.get(field) is not False for field in (
        "downloads_models",
        "runs_long_model_tasks",
        "modifies_global_model_defaults",
    )):
        errors.append("slice.side_effect_policy must deny downloads, long tasks, and global default changes")
    return LocalModelPreflightValidationResult(not errors, tuple(errors))


def validate_local_model_preflight_report(report: Any) -> LocalModelPreflightValidationResult:
    errors: list[str] = []
    if not isinstance(report, dict):
        return LocalModelPreflightValidationResult(False, ("report must be an object",))
    _reject_forbidden_keys(report, errors, "local_model_preflight_report")
    for field in (
        "artifact_type",
        "schema_version",
        "feature_id",
        "preflight_version",
        "contract_id",
        "resource_caps",
        "side_effect_policy",
        "local_model_preflight_slices",
        "preflight_summary",
    ):
        if field not in report:
            errors.append(f"report missing {field}")
    if report.get("artifact_type") != "local_model_preflight_report":
        errors.append("report.artifact_type must be local_model_preflight_report")
    if report.get("schema_version") != LOCAL_MODEL_PREFLIGHT_REPORT_SCHEMA_VERSION:
        errors.append(f"report.schema_version must be {LOCAL_MODEL_PREFLIGHT_REPORT_SCHEMA_VERSION}")
    if report.get("feature_id") != "RET-007":
        errors.append("report.feature_id must be RET-007")
    slices = report.get("local_model_preflight_slices")
    if not isinstance(slices, list) or not slices:
        errors.append("report.local_model_preflight_slices must be a non-empty list")
    else:
        for idx, slice_value in enumerate(slices):
            validation = validate_local_model_preflight_slice(slice_value)
            errors.extend(f"local_model_preflight_slices[{idx}]: {error}" for error in validation.errors)
    summary = report.get("preflight_summary")
    if not isinstance(summary, dict):
        errors.append("report.preflight_summary must be an object")
    elif summary.get("live_retrieval_gate") not in {"pass", "unavailable", "block"}:
        errors.append("report.preflight_summary.live_retrieval_gate is invalid")
    side_effect_policy = report.get("side_effect_policy")
    if not isinstance(side_effect_policy, dict) or any(side_effect_policy.get(field) is not False for field in (
        "downloads_models",
        "runs_long_model_tasks",
        "modifies_global_model_defaults",
    )):
        errors.append("report.side_effect_policy must deny downloads, long tasks, and global default changes")
    return LocalModelPreflightValidationResult(not errors, tuple(errors))
