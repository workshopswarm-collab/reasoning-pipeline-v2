"""Phase 1 handoff contract for ADS Decomposer."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _add_orchestrator_scripts_to_path() -> None:
    configured = os.environ.get("ADS_ORCHESTRATOR_SCRIPTS")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(__file__).resolve().parents[3] / "orchestrator" / "scripts")
    for candidate in candidates:
        if candidate.is_dir():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            return


_add_orchestrator_scripts_to_path()

from predquant.ads_handoff import ArtifactManifestError, canonical_json, validate_artifact_manifest
from predquant.tuning_profile import MODEL_LANE_POLICY_PATH, TuningProfileError, load_model_lane_policy


DECOMPOSER_HANDOFF_SCHEMA_VERSION = "decomposer-handoff/v1"
DECOMPOSER_HANDOFF_ARTIFACT_TYPE = "decomposer_handoff"
DECOMPOSER_MODEL_LANE_ID = "decomposer_qdt_generation"
DECOMPOSER_MODEL_ID = "gpt-5.5-high"
DECOMPOSER_PROMPT_TEMPLATE_ID = "decomposer-qdt/v1"
QUESTION_DECOMPOSITION_SCHEMA_VERSION = "question-decomposition/v1"
DECOMPOSER_HANDOFF_VALIDATOR_VERSION = "ads-decomposer-handoff/v1"

FORBIDDEN_DECOMPOSER_REF_KEYS = (
    "scae",
    "synthesis",
    "decision",
    "outcomes",
    "evaluator_labels",
    "replay",
    "scoring",
)

FORBIDDEN_MODEL_OUTPUTS = {
    "sub_forecast_probability",
    "leaf_probability",
    "macro_probability",
    "fair_value",
    "scae_delta",
}
FORBIDDEN_ACTIVE_FIELD_KEYS = {
    "production_forecast_prob",
    "scae_delta",
    "leaf_probability",
    "macro_probability",
    "sub_forecast_probability",
    "fair_value",
}


class DecomposerHandoffError(ValueError):
    """Raised when a decomposer handoff packet is malformed or unsafe."""


@dataclass(frozen=True)
class ManifestRequirement:
    role: str
    artifact_type: str
    artifact_schema_version: str
    payload_artifact_type: str
    payload_schema_version: str
    accepted_temporal_statuses: tuple[str, ...] = ("pass",)


ADS_CASE_CONTRACT_REQUIREMENT = ManifestRequirement(
    role="ads_case_contract",
    artifact_type="ads-case-contract",
    artifact_schema_version="ads-case-contract/v1",
    payload_artifact_type="ads_case_contract",
    payload_schema_version="ads-case-contract/v1",
)
EVIDENCE_PACKET_REQUIREMENT = ManifestRequirement(
    role="evidence_packet",
    artifact_type="evidence-packet-v2",
    artifact_schema_version="evidence-packet/v2",
    payload_artifact_type="evidence_packet",
    payload_schema_version="evidence-packet/v2",
)
PROFILE_CONTEXT_REQUIREMENT = ManifestRequirement(
    role="effective_profile_context",
    artifact_type="effective-tuning-profile-context",
    artifact_schema_version="effective-tuning-profile-context/v1",
    payload_artifact_type="effective_tuning_profile_context",
    payload_schema_version="effective-tuning-profile-context/v1",
)
RELATED_CONTEXT_REQUIREMENT = ManifestRequirement(
    role="related_market_context",
    artifact_type="related-live-market-context",
    artifact_schema_version="related-live-market-context/v1",
    payload_artifact_type="related_live_market_context",
    payload_schema_version="related-live-market-context/v1",
)
NO_RELATED_CONTEXT_WAIVER_REQUIREMENT = ManifestRequirement(
    role="related_market_context",
    artifact_type="no-related-context-waiver",
    artifact_schema_version="no-related-context-waiver/v1",
    payload_artifact_type="no_related_context_waiver",
    payload_schema_version="no-related-context-waiver/v1",
)

AMRG_REQUIREMENTS_BY_ARTIFACT_TYPE = {
    RELATED_CONTEXT_REQUIREMENT.artifact_type: RELATED_CONTEXT_REQUIREMENT,
    NO_RELATED_CONTEXT_WAIVER_REQUIREMENT.artifact_type: NO_RELATED_CONTEXT_WAIVER_REQUIREMENT,
}


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DecomposerHandoffError(f"{field} must be an object")
    return value


def _load_json_path(path: Path | str) -> dict[str, Any]:
    try:
        return _require_object(json.loads(Path(path).read_text(encoding="utf-8")), str(path))
    except json.JSONDecodeError as exc:
        raise DecomposerHandoffError(f"{path} is not valid JSON: {exc}") from exc


def _parse_timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DecomposerHandoffError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecomposerHandoffError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _same_timestamp(left: str, right: str) -> bool:
    return _parse_timestamp(left, "timestamp") == _parse_timestamp(right, "timestamp")


def _safe_artifact_ref(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": manifest["artifact_id"],
        "artifact_type": manifest["artifact_type"],
        "artifact_schema_version": manifest["artifact_schema_version"],
        "path": manifest["path"],
        "sha256": manifest["sha256"],
        "stage": manifest["stage"],
        "producer": manifest["producer"],
        "validation_status": manifest["validation_status"],
        "temporal_isolation_status": manifest["temporal_isolation_status"],
    }


def _manifest_path(manifest: dict[str, Any], role: str) -> Path:
    if not isinstance(manifest.get("path"), str) or not manifest["path"]:
        raise DecomposerHandoffError(f"{role} manifest path is required")
    path = Path(manifest["path"])
    if not path.is_absolute():
        raise DecomposerHandoffError(f"{role} manifest path must be absolute")
    return path


def validate_manifest_for_requirement(
    manifest: dict[str, Any],
    requirement: ManifestRequirement,
) -> dict[str, Any]:
    manifest = _require_object(manifest, f"{requirement.role} manifest")
    _manifest_path(manifest, requirement.role)
    try:
        validate_artifact_manifest(
            manifest,
            expected_artifact_schema_version=requirement.artifact_schema_version,
        )
    except ArtifactManifestError as exc:
        raise DecomposerHandoffError(f"{requirement.role} manifest invalid: {exc}") from exc
    if manifest["artifact_type"] != requirement.artifact_type:
        raise DecomposerHandoffError(
            f"{requirement.role} artifact_type must be {requirement.artifact_type}"
        )
    if manifest["validation_status"] != "valid":
        raise DecomposerHandoffError(f"{requirement.role} manifest must be valid")
    if manifest["temporal_isolation_status"] not in requirement.accepted_temporal_statuses:
        raise DecomposerHandoffError(
            f"{requirement.role} temporal isolation must be one of "
            f"{', '.join(requirement.accepted_temporal_statuses)}"
        )
    return manifest


def load_payload_for_manifest(
    manifest: dict[str, Any],
    requirement: ManifestRequirement,
) -> dict[str, Any]:
    payload = _load_json_path(_manifest_path(manifest, requirement.role))
    if payload.get("artifact_type") != requirement.payload_artifact_type:
        raise DecomposerHandoffError(
            f"{requirement.role} payload artifact_type must be {requirement.payload_artifact_type}"
        )
    if payload.get("schema_version") != requirement.payload_schema_version:
        raise DecomposerHandoffError(
            f"{requirement.role} payload schema_version must be {requirement.payload_schema_version}"
        )
    for field in ("case_id", "case_key", "dispatch_id", "forecast_timestamp", "source_cutoff_timestamp"):
        if not payload.get(field):
            raise DecomposerHandoffError(f"{requirement.role} payload missing {field}")
    return payload


def _select_amrg_manifest(
    related_market_context_manifest: dict[str, Any] | None,
    no_related_context_waiver_manifest: dict[str, Any] | None,
) -> tuple[dict[str, Any], ManifestRequirement]:
    if related_market_context_manifest and no_related_context_waiver_manifest:
        raise DecomposerHandoffError("provide related market context or no-related-context waiver, not both")
    manifest = related_market_context_manifest or no_related_context_waiver_manifest
    if manifest is None:
        raise DecomposerHandoffError("related market context or no-related-context waiver manifest is required")
    manifest = _require_object(manifest, "related market context manifest")
    requirement = AMRG_REQUIREMENTS_BY_ARTIFACT_TYPE.get(manifest.get("artifact_type"))
    if requirement is None:
        raise DecomposerHandoffError("related market context manifest has unknown artifact_type")
    return manifest, requirement


def _check_manifest_payload_continuity(
    role: str,
    manifest: dict[str, Any],
    payload: dict[str, Any],
    expected: dict[str, str],
) -> None:
    for field in ("case_id", "case_key", "dispatch_id"):
        if manifest.get(field) != expected[field]:
            raise DecomposerHandoffError(f"{role} manifest {field} mismatch")
        if payload.get(field) != expected[field]:
            raise DecomposerHandoffError(f"{role} payload {field} mismatch")
    for field in ("forecast_timestamp", "source_cutoff_timestamp"):
        if not _same_timestamp(manifest.get(field), expected[field]):
            raise DecomposerHandoffError(f"{role} manifest {field} mismatch")
        if not _same_timestamp(payload.get(field), expected[field]):
            raise DecomposerHandoffError(f"{role} payload {field} mismatch")


def _require_input_manifest_ref(role: str, manifest: dict[str, Any], artifact_id: str) -> None:
    if artifact_id not in manifest.get("input_manifest_ids", []):
        raise DecomposerHandoffError(f"{role} manifest missing input manifest ref {artifact_id}")


def _validate_transitive_refs(
    *,
    case_manifest: dict[str, Any],
    evidence_manifest: dict[str, Any],
    evidence_payload: dict[str, Any],
    profile_manifest: dict[str, Any],
    profile_payload: dict[str, Any],
    amrg_manifest: dict[str, Any],
    amrg_payload: dict[str, Any],
) -> None:
    case_ref = case_manifest["artifact_id"]
    evidence_ref = evidence_manifest["artifact_id"]
    profile_ref = profile_manifest["artifact_id"]
    if evidence_payload.get("case_contract_ref") != case_ref:
        raise DecomposerHandoffError("evidence packet must reference ADS case contract manifest")
    _require_input_manifest_ref("evidence_packet", evidence_manifest, case_ref)

    if profile_payload.get("evidence_packet_ref") != evidence_ref:
        raise DecomposerHandoffError("profile context must reference evidence packet manifest")
    _require_input_manifest_ref("effective_profile_context", profile_manifest, evidence_ref)

    if amrg_payload.get("evidence_packet_ref") != evidence_ref:
        raise DecomposerHandoffError("related market context must reference evidence packet manifest")
    if amrg_payload.get("profile_context_ref") != profile_ref:
        raise DecomposerHandoffError("related market context must reference effective profile context manifest")
    _require_input_manifest_ref("related_market_context", amrg_manifest, evidence_ref)
    _require_input_manifest_ref("related_market_context", amrg_manifest, profile_ref)


def resolve_decomposer_model_lane(
    *,
    model_lane_policy_path: Path | str = MODEL_LANE_POLICY_PATH,
    input_manifest_ids: list[str] | None = None,
    prompt_template_id: str = DECOMPOSER_PROMPT_TEMPLATE_ID,
    prompt_template_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        policy = load_model_lane_policy(model_lane_policy_path)
    except TuningProfileError as exc:
        raise DecomposerHandoffError(f"model lane policy invalid: {exc}") from exc
    lane = policy.get("lanes", {}).get(DECOMPOSER_MODEL_LANE_ID)
    if not isinstance(lane, dict):
        raise DecomposerHandoffError(f"missing model lane {DECOMPOSER_MODEL_LANE_ID}")
    if lane.get("provider") != "openai":
        raise DecomposerHandoffError("decomposer QDT model lane provider must be openai")
    if lane.get("default_model_id") != DECOMPOSER_MODEL_ID:
        raise DecomposerHandoffError(f"decomposer QDT model must be {DECOMPOSER_MODEL_ID}")
    if DECOMPOSER_MODEL_ID not in lane.get("allowed_model_ids", []):
        raise DecomposerHandoffError(f"{DECOMPOSER_MODEL_ID} must be allowed for decomposer QDT")
    missing_forbidden = FORBIDDEN_MODEL_OUTPUTS - set(lane.get("forbidden_outputs", []))
    if missing_forbidden:
        raise DecomposerHandoffError(
            "decomposer model lane missing forbidden outputs: "
            + ", ".join(sorted(missing_forbidden))
        )
    missing_fields = {
        "model_lane_id",
        "resolved_model_id",
        "model_policy_ref",
        "prompt_template_id",
        "prompt_template_sha256",
        "input_manifest_ids",
        "output_schema_version",
    } - set(lane.get("required_artifact_fields", []))
    if missing_fields:
        raise DecomposerHandoffError(
            "decomposer model lane missing required artifact fields: "
            + ", ".join(sorted(missing_fields))
        )
    prompt_sha = prompt_template_sha256 or _prefixed_sha256(
        {
            "prompt_template_id": prompt_template_id,
            "placeholder": "session-03-phase-1-contract",
        }
    )
    if not prompt_sha.startswith("sha256:"):
        raise DecomposerHandoffError("prompt_template_sha256 must start with sha256:")
    policy_path = Path(model_lane_policy_path)
    return {
        "model_lane_id": DECOMPOSER_MODEL_LANE_ID,
        "provider": lane["provider"],
        "resolved_model_id": lane["default_model_id"],
        "provider_route": f"{lane['provider']}/{lane['default_model_id']}",
        "model_policy_ref": str(policy_path),
        "model_policy_id": policy["policy_id"],
        "prompt_template_id": prompt_template_id,
        "prompt_template_sha256": prompt_sha,
        "input_manifest_ids": list(input_manifest_ids or []),
        "output_schema_version": QUESTION_DECOMPOSITION_SCHEMA_VERSION,
        "forbidden_outputs": list(lane.get("forbidden_outputs", [])),
        "provenance_status": "lane_resolved_pending_model_runtime_call",
    }


def build_decomposer_handoff(
    *,
    ads_case_contract_manifest: dict[str, Any],
    evidence_packet_manifest: dict[str, Any],
    effective_profile_context_manifest: dict[str, Any],
    related_market_context_manifest: dict[str, Any] | None = None,
    no_related_context_waiver_manifest: dict[str, Any] | None = None,
    model_lane_policy_path: Path | str = MODEL_LANE_POLICY_PATH,
    macro_question: str | None = None,
) -> dict[str, Any]:
    case_manifest = validate_manifest_for_requirement(ads_case_contract_manifest, ADS_CASE_CONTRACT_REQUIREMENT)
    evidence_manifest = validate_manifest_for_requirement(evidence_packet_manifest, EVIDENCE_PACKET_REQUIREMENT)
    profile_manifest = validate_manifest_for_requirement(effective_profile_context_manifest, PROFILE_CONTEXT_REQUIREMENT)
    amrg_manifest_raw, amrg_requirement = _select_amrg_manifest(
        related_market_context_manifest,
        no_related_context_waiver_manifest,
    )
    amrg_manifest = validate_manifest_for_requirement(amrg_manifest_raw, amrg_requirement)

    case_payload = load_payload_for_manifest(case_manifest, ADS_CASE_CONTRACT_REQUIREMENT)
    evidence_payload = load_payload_for_manifest(evidence_manifest, EVIDENCE_PACKET_REQUIREMENT)
    profile_payload = load_payload_for_manifest(profile_manifest, PROFILE_CONTEXT_REQUIREMENT)
    amrg_payload = load_payload_for_manifest(amrg_manifest, amrg_requirement)

    for field in ("prediction_run_id", "forecast_artifact_id", "market_identity", "prediction_time_market_baseline"):
        if not case_payload.get(field):
            raise DecomposerHandoffError(f"case contract payload missing {field}")

    expected = {
        "case_id": case_payload["case_id"],
        "case_key": case_payload["case_key"],
        "dispatch_id": case_payload["dispatch_id"],
        "forecast_timestamp": case_payload["forecast_timestamp"],
        "source_cutoff_timestamp": case_payload["source_cutoff_timestamp"],
    }
    for role, manifest, payload in (
        ("ads_case_contract", case_manifest, case_payload),
        ("evidence_packet", evidence_manifest, evidence_payload),
        ("effective_profile_context", profile_manifest, profile_payload),
        ("related_market_context", amrg_manifest, amrg_payload),
    ):
        _check_manifest_payload_continuity(role, manifest, payload, expected)

    _validate_transitive_refs(
        case_manifest=case_manifest,
        evidence_manifest=evidence_manifest,
        evidence_payload=evidence_payload,
        profile_manifest=profile_manifest,
        profile_payload=profile_payload,
        amrg_manifest=amrg_manifest,
        amrg_payload=amrg_payload,
    )

    input_manifest_ids = [
        case_manifest["artifact_id"],
        evidence_manifest["artifact_id"],
        profile_manifest["artifact_id"],
        amrg_manifest["artifact_id"],
    ]
    model_execution_context = resolve_decomposer_model_lane(
        model_lane_policy_path=model_lane_policy_path,
        input_manifest_ids=input_manifest_ids,
    )
    market_identity = case_payload["market_identity"]
    baseline = case_payload["prediction_time_market_baseline"]
    handoff = {
        "artifact_type": DECOMPOSER_HANDOFF_ARTIFACT_TYPE,
        "schema_version": DECOMPOSER_HANDOFF_SCHEMA_VERSION,
        "case_id": expected["case_id"],
        "case_key": expected["case_key"],
        "dispatch_id": expected["dispatch_id"],
        "prediction_run_id": case_payload["prediction_run_id"],
        "forecast_artifact_id": case_payload["forecast_artifact_id"],
        "forecast_timestamp": expected["forecast_timestamp"],
        "source_cutoff_timestamp": expected["source_cutoff_timestamp"],
        "macro_question": macro_question or market_identity.get("title") or market_identity.get("slug"),
        "market_context": {
            "market_id": evidence_payload.get("market_id") or market_identity.get("internal_market_id"),
            "platform": market_identity.get("platform"),
            "external_market_id": market_identity.get("external_market_id"),
            "current_market_probability": baseline.get("market_probability"),
            "current_market_probability_method": baseline.get("market_probability_method"),
            "market_reality_constraints_digest": _prefixed_sha256(
                evidence_payload.get("market_reality_constraints", {})
            ),
        },
        "artifact_refs": {
            "ads_case_contract": _safe_artifact_ref(case_manifest),
            "evidence_packet": _safe_artifact_ref(evidence_manifest),
            "effective_profile_context": _safe_artifact_ref(profile_manifest),
            "related_market_context": _safe_artifact_ref(amrg_manifest),
        },
        "input_manifest_ids": input_manifest_ids,
        "model_execution_context": model_execution_context,
        "forbidden_refs": list(FORBIDDEN_DECOMPOSER_REF_KEYS),
        "validation_summary": {
            "status": "valid",
            "validator_version": DECOMPOSER_HANDOFF_VALIDATOR_VERSION,
            "reason_codes": [
                "artifact_manifest_digest_passed",
                "schema_versions_matched",
                "case_dispatch_timestamp_continuity_passed",
                "transitive_manifest_refs_matched",
                "decomposer_model_lane_resolved",
            ],
        },
    }
    validate_decomposer_handoff(handoff)
    return handoff


def validate_decomposer_handoff(handoff: dict[str, Any]) -> None:
    handoff = _require_object(handoff, "handoff")
    if handoff.get("artifact_type") != DECOMPOSER_HANDOFF_ARTIFACT_TYPE:
        raise DecomposerHandoffError("handoff artifact_type must be decomposer_handoff")
    if handoff.get("schema_version") != DECOMPOSER_HANDOFF_SCHEMA_VERSION:
        raise DecomposerHandoffError(f"handoff schema_version must be {DECOMPOSER_HANDOFF_SCHEMA_VERSION}")
    for field in (
        "case_id",
        "case_key",
        "dispatch_id",
        "prediction_run_id",
        "forecast_artifact_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "macro_question",
        "artifact_refs",
        "input_manifest_ids",
        "model_execution_context",
        "forbidden_refs",
        "validation_summary",
    ):
        if field not in handoff:
            raise DecomposerHandoffError(f"handoff missing {field}")
    model_context = _require_object(handoff["model_execution_context"], "model_execution_context")
    if model_context.get("model_lane_id") != DECOMPOSER_MODEL_LANE_ID:
        raise DecomposerHandoffError("handoff model lane mismatch")
    if model_context.get("resolved_model_id") != DECOMPOSER_MODEL_ID:
        raise DecomposerHandoffError("handoff model ID mismatch")
    if set(handoff["input_manifest_ids"]) != set(model_context.get("input_manifest_ids", [])):
        raise DecomposerHandoffError("model execution context input manifest IDs must match handoff")
    forbidden_refs = set(handoff.get("forbidden_refs", []))
    missing_forbidden = set(FORBIDDEN_DECOMPOSER_REF_KEYS) - forbidden_refs
    if missing_forbidden:
        raise DecomposerHandoffError("handoff missing forbidden refs")
    _reject_active_forbidden_fields(handoff)


def _reject_active_forbidden_fields(value: Any, path: str = "handoff") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in {"forbidden_outputs", "forbidden_refs"}:
                continue
            if normalized in FORBIDDEN_ACTIVE_FIELD_KEYS:
                raise DecomposerHandoffError(f"{path}.{key} is not allowed in decomposer handoff")
            _reject_active_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_active_forbidden_fields(child, f"{path}[{idx}]")
