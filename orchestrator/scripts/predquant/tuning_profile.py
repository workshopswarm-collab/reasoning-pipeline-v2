"""ADS v2 deterministic tuning profile and model-lane policy helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from predquant.ads_case_contract import parse_timestamp
from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    canonical_json,
    validate_artifact_manifest,
    write_artifact_manifest,
)
from predquant.evidence_packet import validate_evidence_packet_v2


TUNABLE_REGISTRY_SCHEMA_VERSION = "tunable-registry-metadata/v1"
MARKET_REGIME_TAGS_SCHEMA_VERSION = "market-regime-tags/v1"
EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION = "effective-tuning-profile-context/v1"
MODEL_LANE_POLICY_SCHEMA_VERSION = "model-lane-policy/v1"
EFFECTIVE_PROFILE_ARTIFACT_TYPE = "effective-tuning-profile-context"
MODEL_LANE_POLICY_PATH = Path(__file__).resolve().parents[2] / "plans" / "autonomous-decomposition-swarm-model-lane-policy.json"
GLOBAL_BASELINE_PROFILE_ID = "global_baseline_profile"
PROFILE_CONTEXT_PRODUCER = "session-02-tuning-profile"
FORBIDDEN_PROFILE_KEYS = {
    "scae_weight",
    "scae_weights",
    "numeric_scae_weight",
    "probability",
    "posterior_probability",
    "production_forecast_prob",
    "fair_value_probability",
    "scae_delta",
    "model_authored_delta",
    "autonomous_promotion",
    "hidden_learning_loop",
    "raw_payload",
    "payload",
    "raw_content",
    "content",
    "body",
    "html",
    "page_text",
}
DOMAIN_PROFILE_BY_FAMILY = {
    "politics": "politics_domain_profile",
    "macro_economic": "macro_domain_profile",
    "sports": "sports_price_sensitive_profile",
    "crypto": "crypto_price_sensitive_profile",
}
EXCLUDED_INITIAL_DOMAIN_PROFILES = {
    "sports_price_sensitive_profile",
    "crypto_price_sensitive_profile",
}


class TuningProfileError(ValueError):
    """Raised when tuning/profile/model-lane context is unsafe or malformed."""


def prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json_path(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compact_text(value: Any) -> str:
    return str(value or "").lower()


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def reject_forbidden_profile_fields(value: Any, path: str = "profile_context") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_PROFILE_KEYS:
                raise TuningProfileError(f"{path}.{key} is not allowed in tuning/profile context")
            reject_forbidden_profile_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_forbidden_profile_fields(child, f"{path}[{idx}]")


def default_tunable_registry_metadata() -> dict[str, Any]:
    profiles = [
        {
            "profile_id": GLOBAL_BASELINE_PROFILE_ID,
            "domain_family": "global",
            "promotion_status": "promoted",
            "active_by_default": True,
            "subsystem_policy_slice_ids": [
                "global_baseline_profile:retrieval_breadth",
                "global_baseline_profile:decomposition_defaults",
            ],
        },
        {
            "profile_id": "politics_domain_profile",
            "domain_family": "politics",
            "promotion_status": "inactive_candidate",
            "active_by_default": False,
            "subsystem_policy_slice_ids": ["politics_domain_profile:retrieval_breadth"],
        },
        {
            "profile_id": "macro_domain_profile",
            "domain_family": "macro_economic",
            "promotion_status": "inactive_candidate",
            "active_by_default": False,
            "subsystem_policy_slice_ids": ["macro_domain_profile:retrieval_breadth"],
        },
        {
            "profile_id": "sports_price_sensitive_profile",
            "domain_family": "sports",
            "promotion_status": "excluded_initial_profile",
            "active_by_default": False,
            "subsystem_policy_slice_ids": ["sports_price_sensitive_profile:diagnostics_only"],
        },
        {
            "profile_id": "crypto_price_sensitive_profile",
            "domain_family": "crypto",
            "promotion_status": "excluded_initial_profile",
            "active_by_default": False,
            "subsystem_policy_slice_ids": ["crypto_price_sensitive_profile:diagnostics_only"],
        },
    ]
    overlays = [
        {
            "overlay_id": "conservative_thin_liquidity_overlay",
            "trigger_tag": {"dimension": "liquidity_regime", "value": "thin_or_wide"},
            "promotion_status": "promoted",
            "risk_reducing": True,
            "subsystem_policy_slice_ids": ["conservative_thin_liquidity_overlay:retrieval_breadth"],
        },
        {
            "overlay_id": "conservative_close_to_resolution_overlay",
            "trigger_tag": {"dimension": "resolution_proximity", "value": "near_resolution"},
            "promotion_status": "promoted",
            "risk_reducing": True,
            "subsystem_policy_slice_ids": ["conservative_close_to_resolution_overlay:actionability"],
        },
        {
            "overlay_id": "conservative_source_unknown_overlay",
            "trigger_tag": {"dimension": "evidence_environment", "value": "source_of_truth_unknown"},
            "promotion_status": "promoted",
            "risk_reducing": True,
            "subsystem_policy_slice_ids": ["conservative_source_unknown_overlay:retrieval_breadth"],
        },
    ]
    registry = {
        "artifact_type": "tunable_registry_metadata",
        "schema_version": TUNABLE_REGISTRY_SCHEMA_VERSION,
        "registry_id": "ads-tunable-registry-metadata/v1",
        "global_baseline_profile_id": GLOBAL_BASELINE_PROFILE_ID,
        "autonomous_promotion_enabled": False,
        "promotion_authority": "manual_or_calibration_lane_only",
        "model_outputs_may_promote_profiles": False,
        "numeric_scae_weight_authoring": False,
        "domain_profiles": profiles,
        "conservative_overlays": overlays,
        "active_pointer_requirements": {
            "required_status": "active",
            "required_promotion_status": "promoted",
            "required_canary_status": "passing",
            "excluded_initial_profile_ids": sorted(EXCLUDED_INITIAL_DOMAIN_PROFILES),
        },
    }
    validate_tunable_registry_metadata(registry)
    return registry


def validate_tunable_registry_metadata(registry: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "registry_id",
        "global_baseline_profile_id",
        "autonomous_promotion_enabled",
        "promotion_authority",
        "model_outputs_may_promote_profiles",
        "numeric_scae_weight_authoring",
        "domain_profiles",
        "conservative_overlays",
        "active_pointer_requirements",
    ]
    for field in required:
        if field not in registry:
            raise TuningProfileError(f"registry.{field} is required")
    if registry["artifact_type"] != "tunable_registry_metadata":
        raise TuningProfileError("registry artifact_type must be tunable_registry_metadata")
    if registry["schema_version"] != TUNABLE_REGISTRY_SCHEMA_VERSION:
        raise TuningProfileError(f"registry schema_version must be {TUNABLE_REGISTRY_SCHEMA_VERSION}")
    if registry["global_baseline_profile_id"] != GLOBAL_BASELINE_PROFILE_ID:
        raise TuningProfileError("registry must define global_baseline_profile")
    if registry["autonomous_promotion_enabled"] is not False:
        raise TuningProfileError("autonomous profile promotion is not allowed")
    if registry["model_outputs_may_promote_profiles"] is not False:
        raise TuningProfileError("model outputs cannot promote profiles")
    if registry["numeric_scae_weight_authoring"] is not False:
        raise TuningProfileError("registry cannot author numeric SCAE weights")
    profile_ids = set()
    for profile in registry["domain_profiles"]:
        profile_id = profile.get("profile_id")
        if not profile_id:
            raise TuningProfileError("domain profile missing profile_id")
        if profile_id in profile_ids:
            raise TuningProfileError(f"duplicate domain profile {profile_id}")
        profile_ids.add(profile_id)
        if not profile.get("domain_family") or not profile.get("promotion_status"):
            raise TuningProfileError(f"{profile_id} missing domain_family or promotion_status")
        reject_forbidden_profile_fields(profile, f"domain_profiles.{profile_id}")
    if GLOBAL_BASELINE_PROFILE_ID not in profile_ids:
        raise TuningProfileError("global baseline profile missing")
    for overlay in registry["conservative_overlays"]:
        overlay_id = overlay.get("overlay_id")
        if not overlay_id:
            raise TuningProfileError("conservative overlay missing overlay_id")
        if overlay.get("risk_reducing") is not True:
            raise TuningProfileError(f"{overlay_id} must be risk_reducing")
        if overlay.get("promotion_status") != "promoted":
            raise TuningProfileError(f"{overlay_id} must be promoted")
        reject_forbidden_profile_fields(overlay, f"conservative_overlays.{overlay_id}")
    reject_forbidden_profile_fields({k: v for k, v in registry.items() if k not in {"autonomous_promotion_enabled"}})


def profile_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {profile["profile_id"]: profile for profile in registry["domain_profiles"]}


def overlay_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {overlay["overlay_id"]: overlay for overlay in registry["conservative_overlays"]}


def classify_domain(evidence_packet: dict[str, Any]) -> str:
    seed = evidence_packet.get("regime_seed_fields", {})
    identity = evidence_packet.get("market_identity", {})
    text = " ".join(
        compact_text(value)
        for value in [
            seed.get("category"),
            identity.get("category"),
            identity.get("title"),
            identity.get("description"),
            identity.get("platform"),
        ]
    )
    if contains_any(text, ("nfl", "nba", "mlb", "nhl", "soccer", "sports", "team ", "game ")):
        return "sports"
    if contains_any(text, ("crypto", "bitcoin", "ethereum", "solana", "btc", "eth")):
        return "crypto"
    if contains_any(text, ("election", "president", "senate", "congress", "politic", "vote")):
        return "politics"
    if contains_any(text, ("fed", "inflation", "gdp", "interest rate", "unemployment", "macro", "economic")):
        return "macro_economic"
    return "unknown"


def classify_contract(evidence_packet: dict[str, Any]) -> str:
    return str(evidence_packet.get("market_reality_constraints", {}).get("contract_structure") or "unknown")


def classify_market_state(evidence_packet: dict[str, Any]) -> str:
    status = compact_text(evidence_packet.get("regime_seed_fields", {}).get("status"))
    freshness = (
        evidence_packet.get("prior_reliability_inputs", {})
        .get("rolling_microstructure", {})
        .get("market_snapshot_freshness", {})
        .get("status")
    )
    if status not in {"open", "active"}:
        return "not_open"
    if freshness == "fresh":
        return "open_fresh_snapshot"
    if freshness == "stale":
        return "open_stale_snapshot"
    return "open_unknown_freshness"


def classify_evidence_environment(evidence_packet: dict[str, Any]) -> str:
    status = evidence_packet.get("market_reality_constraints", {}).get("source_of_truth_status")
    if status == "clear":
        return "source_of_truth_clear"
    if status == "ambiguous":
        return "source_of_truth_ambiguous"
    return "source_of_truth_unknown"


def classify_liquidity(evidence_packet: dict[str, Any]) -> str:
    micro = evidence_packet.get("prior_reliability_inputs", {}).get("rolling_microstructure", {})
    spread = micro.get("bid_ask_spread_latest")
    volume = micro.get("recent_volume_rolling", {}).get("latest")
    open_interest = micro.get("open_interest_latest")
    if spread is not None and spread >= 0.15:
        return "thin_or_wide"
    if (volume is not None and volume >= 100.0) or (open_interest is not None and open_interest >= 100.0):
        return "liquid"
    return "unknown"


def classify_resolution_proximity(evidence_packet: dict[str, Any]) -> str:
    close_timestamp = evidence_packet.get("regime_seed_fields", {}).get("close_timestamp")
    forecast_timestamp = evidence_packet.get("forecast_timestamp")
    if not close_timestamp or not forecast_timestamp:
        return "unknown"
    seconds = (parse_timestamp(close_timestamp, "close_timestamp") - parse_timestamp(forecast_timestamp, "forecast_timestamp")).total_seconds()
    if seconds < 0:
        return "closed_or_past_close"
    if seconds <= 86400:
        return "near_resolution"
    return "open_window"


def materialize_market_regime_tags(evidence_packet: dict[str, Any]) -> dict[str, Any]:
    validate_evidence_packet_v2(evidence_packet)
    tags = {
        "domain_family": classify_domain(evidence_packet),
        "contract_type": classify_contract(evidence_packet),
        "market_state": classify_market_state(evidence_packet),
        "evidence_environment": classify_evidence_environment(evidence_packet),
        "liquidity_regime": classify_liquidity(evidence_packet),
        "resolution_proximity": classify_resolution_proximity(evidence_packet),
    }
    tag_slices = [
        {
            "tag_id": prefixed_sha256([evidence_packet["case_id"], dimension, value]),
            "dimension": dimension,
            "value": value,
            "source_schema_version": evidence_packet["schema_version"],
        }
        for dimension, value in tags.items()
    ]
    result = {
        "artifact_type": "market_regime_tags",
        "schema_version": MARKET_REGIME_TAGS_SCHEMA_VERSION,
        "case_id": evidence_packet["case_id"],
        "dispatch_id": evidence_packet["dispatch_id"],
        "source_evidence_packet_schema_version": evidence_packet["schema_version"],
        "tags": tags,
        "tag_slices": tag_slices,
    }
    validate_market_regime_tags(result)
    return result


def validate_market_regime_tags(regime_tags: dict[str, Any]) -> None:
    if regime_tags.get("artifact_type") != "market_regime_tags":
        raise TuningProfileError("regime tags artifact_type must be market_regime_tags")
    if regime_tags.get("schema_version") != MARKET_REGIME_TAGS_SCHEMA_VERSION:
        raise TuningProfileError(f"regime tags schema_version must be {MARKET_REGIME_TAGS_SCHEMA_VERSION}")
    required_dimensions = {
        "domain_family",
        "contract_type",
        "market_state",
        "evidence_environment",
        "liquidity_regime",
        "resolution_proximity",
    }
    if set(regime_tags.get("tags", {})) != required_dimensions:
        raise TuningProfileError("regime tags missing required dimensions")
    if len(regime_tags.get("tag_slices", [])) != len(required_dimensions):
        raise TuningProfileError("regime tag slices must cover every dimension")
    reject_forbidden_profile_fields(regime_tags, "regime_tags")


def intended_profile_for_tags(regime_tags: dict[str, Any]) -> str:
    domain = regime_tags["tags"]["domain_family"]
    return DOMAIN_PROFILE_BY_FAMILY.get(domain, GLOBAL_BASELINE_PROFILE_ID)


def pointer_is_active(pointer: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(pointer, dict)
        and pointer.get("status") == "active"
        and pointer.get("promotion_status") == "promoted"
        and pointer.get("canary_status") == "passing"
    )


def build_subsystem_slice_refs(profile_ids: list[str], registry: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = profile_index(registry)
    overlays = overlay_index(registry)
    slices: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        source = profiles.get(profile_id) or overlays.get(profile_id)
        if not source:
            continue
        for slice_id in source.get("subsystem_policy_slice_ids", []):
            slices.append(
                {
                    "slice_id": slice_id,
                    "source_profile_or_overlay_id": profile_id,
                    "subsystem": slice_id.split(":")[-1],
                    "policy_ref": f"policy://{profile_id}/{slice_id.split(':')[-1]}",
                    "policy_sha256": prefixed_sha256([profile_id, slice_id]),
                }
            )
    return slices


def eligible_conservative_overlays(
    regime_tags: dict[str, Any],
    registry: dict[str, Any],
    active_overlay_pointers: dict[str, dict[str, Any]] | None,
) -> list[str]:
    pointers = active_overlay_pointers or {}
    tags = regime_tags["tags"]
    eligible: list[str] = []
    for overlay in registry["conservative_overlays"]:
        trigger = overlay.get("trigger_tag") or {}
        overlay_id = overlay["overlay_id"]
        if tags.get(trigger.get("dimension")) != trigger.get("value"):
            continue
        if overlay.get("risk_reducing") is True and overlay.get("promotion_status") == "promoted" and pointer_is_active(pointers.get(overlay_id)):
            eligible.append(overlay_id)
    return eligible


def resolve_tuning_profile_context(
    *,
    evidence_packet: dict[str, Any],
    evidence_packet_ref: str,
    registry_metadata: dict[str, Any] | None = None,
    active_domain_pointers: dict[str, dict[str, Any]] | None = None,
    active_overlay_pointers: dict[str, dict[str, Any]] | None = None,
    model_lane_policy_ref: str = "plans/autonomous-decomposition-swarm-model-lane-policy.json",
) -> dict[str, Any]:
    validate_evidence_packet_v2(evidence_packet)
    registry = registry_metadata or default_tunable_registry_metadata()
    validate_tunable_registry_metadata(registry)
    regime_tags = materialize_market_regime_tags(evidence_packet)
    profiles = profile_index(registry)
    intended_profile_id = intended_profile_for_tags(regime_tags)
    intended_profile = profiles.get(intended_profile_id)
    if intended_profile is None:
        intended_profile_id = GLOBAL_BASELINE_PROFILE_ID
        intended_profile = profiles[intended_profile_id]
    active_profile_id = GLOBAL_BASELINE_PROFILE_ID
    active_pointer_id = None
    intended_status = intended_profile["promotion_status"]
    if intended_profile_id == GLOBAL_BASELINE_PROFILE_ID:
        intended_status = "global_baseline"
    elif intended_profile_id in EXCLUDED_INITIAL_DOMAIN_PROFILES:
        intended_status = "excluded_initial_profile"
    else:
        pointer = (active_domain_pointers or {}).get(intended_profile_id)
        if intended_profile.get("promotion_status") == "promoted" and pointer_is_active(pointer):
            active_profile_id = intended_profile_id
            active_pointer_id = pointer.get("pointer_id")
            intended_status = "active"
        else:
            intended_status = "intended_but_inactive"

    overlay_ids = eligible_conservative_overlays(regime_tags, registry, active_overlay_pointers)
    active_ids = [active_profile_id] + overlay_ids
    context = {
        "artifact_type": "effective_tuning_profile_context",
        "schema_version": EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION,
        "case_id": evidence_packet["case_id"],
        "case_key": evidence_packet["case_key"],
        "dispatch_id": evidence_packet["dispatch_id"],
        "forecast_timestamp": evidence_packet["forecast_timestamp"],
        "source_cutoff_timestamp": evidence_packet["source_cutoff_timestamp"],
        "evidence_packet_ref": evidence_packet_ref,
        "model_lane_policy_ref": model_lane_policy_ref,
        "registry_id": registry["registry_id"],
        "registry_schema_version": registry["schema_version"],
        "global_baseline_profile_id": registry["global_baseline_profile_id"],
        "intended_domain_profile_id": intended_profile_id,
        "intended_profile_status": intended_status,
        "active_domain_profile_id": active_profile_id,
        "active_domain_pointer_id": active_pointer_id,
        "conservative_overlay_ids": overlay_ids,
        "conservative_overlay_pointer_ids": [
            active_overlay_pointers[overlay_id]["pointer_id"]
            for overlay_id in overlay_ids
            if active_overlay_pointers and overlay_id in active_overlay_pointers
        ],
        "market_regime_tags": regime_tags,
        "subsystem_policy_slices": build_subsystem_slice_refs(active_ids, registry),
        "authority_boundary": {
            "autonomous_promotion_enabled": False,
            "profile_context_authors_numeric_scae_weights": False,
            "model_outputs_may_promote_profiles": False,
        },
    }
    context["effective_profile_sha256"] = prefixed_sha256({k: v for k, v in context.items() if k != "effective_profile_sha256"})
    validate_effective_profile_context(context)
    return context


def validate_effective_profile_context(context: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "case_id",
        "case_key",
        "dispatch_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "evidence_packet_ref",
        "model_lane_policy_ref",
        "registry_id",
        "global_baseline_profile_id",
        "intended_domain_profile_id",
        "intended_profile_status",
        "active_domain_profile_id",
        "conservative_overlay_ids",
        "market_regime_tags",
        "subsystem_policy_slices",
        "authority_boundary",
        "effective_profile_sha256",
    ]
    for field in required:
        if field not in context:
            raise TuningProfileError(f"{field} is required")
    if context["artifact_type"] != "effective_tuning_profile_context":
        raise TuningProfileError("context artifact_type must be effective_tuning_profile_context")
    if context["schema_version"] != EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION:
        raise TuningProfileError(f"context schema_version must be {EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION}")
    if context["global_baseline_profile_id"] != GLOBAL_BASELINE_PROFILE_ID:
        raise TuningProfileError("context must include global baseline profile")
    if not context["active_domain_profile_id"]:
        raise TuningProfileError("active_domain_profile_id is required")
    boundary = context["authority_boundary"]
    if boundary.get("autonomous_promotion_enabled") is not False:
        raise TuningProfileError("context cannot enable autonomous promotion")
    if boundary.get("profile_context_authors_numeric_scae_weights") is not False:
        raise TuningProfileError("context cannot author numeric SCAE weights")
    if boundary.get("model_outputs_may_promote_profiles") is not False:
        raise TuningProfileError("context cannot let model outputs promote profiles")
    validate_market_regime_tags(context["market_regime_tags"])
    for slice_ref in context["subsystem_policy_slices"]:
        for key in ("slice_id", "subsystem", "policy_ref", "policy_sha256"):
            if not slice_ref.get(key):
                raise TuningProfileError(f"subsystem policy slice missing {key}")
        reject_forbidden_profile_fields(slice_ref, f"subsystem_policy_slices.{slice_ref.get('slice_id')}")
    expected = prefixed_sha256({k: v for k, v in context.items() if k != "effective_profile_sha256"})
    if context["effective_profile_sha256"] != expected:
        raise TuningProfileError("effective_profile_sha256 mismatch")
    reject_forbidden_profile_fields(context)


def effective_profile_context_path(artifact_dir: Path | str, context: dict[str, Any]) -> Path:
    base = Path(artifact_dir) / context["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{context['dispatch_id']}-effective-tuning-profile-context.json"


def write_effective_profile_context_artifact(path: Path | str, context: dict[str, Any]) -> Path:
    validate_effective_profile_context(context)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(context) + "\n", encoding="utf-8")
    return target


def build_manifest_for_effective_profile_context(context: dict[str, Any], path: Path | str) -> dict[str, Any]:
    manifest_context = ArtifactManifestContext(
        case_id=context["case_id"],
        case_key=context["case_key"],
        dispatch_id=context["dispatch_id"],
        stage="profile_context",
        producer=PROFILE_CONTEXT_PRODUCER,
        forecast_timestamp=context["forecast_timestamp"],
        source_cutoff_timestamp=context["source_cutoff_timestamp"],
    )
    input_manifest_ids = [context["evidence_packet_ref"]]
    if context.get("model_lane_policy_ref"):
        input_manifest_ids.append(context["model_lane_policy_ref"])
    manifest = build_artifact_manifest(
        context=manifest_context,
        artifact_type=EFFECTIVE_PROFILE_ARTIFACT_TYPE,
        artifact_schema_version=EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION,
        path=path,
        input_manifest_ids=input_manifest_ids,
        validation_status="valid",
        validator_version=EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION,
        temporal_isolation_status="pass",
        metadata={
            "active_domain_profile_id": context["active_domain_profile_id"],
            "intended_domain_profile_id": context["intended_domain_profile_id"],
            "conservative_overlay_ids": context["conservative_overlay_ids"],
            "effective_profile_sha256": context["effective_profile_sha256"],
        },
    )
    validate_artifact_manifest(manifest, expected_artifact_schema_version=EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION)
    return manifest


def materialize_effective_profile_context(
    conn: sqlite3.Connection,
    *,
    evidence_packet: dict[str, Any],
    evidence_packet_ref: str,
    artifact_dir: Path | str,
    registry_metadata: dict[str, Any] | None = None,
    active_domain_pointers: dict[str, dict[str, Any]] | None = None,
    active_overlay_pointers: dict[str, dict[str, Any]] | None = None,
    model_lane_policy_ref: str = "plans/autonomous-decomposition-swarm-model-lane-policy.json",
) -> dict[str, Any]:
    context = resolve_tuning_profile_context(
        evidence_packet=evidence_packet,
        evidence_packet_ref=evidence_packet_ref,
        registry_metadata=registry_metadata,
        active_domain_pointers=active_domain_pointers,
        active_overlay_pointers=active_overlay_pointers,
        model_lane_policy_ref=model_lane_policy_ref,
    )
    path = write_effective_profile_context_artifact(effective_profile_context_path(artifact_dir, context), context)
    manifest = build_manifest_for_effective_profile_context(context, path)
    artifact_id = write_artifact_manifest(conn, manifest)
    return {
        "status": "completed",
        "artifact_id": artifact_id,
        "artifact_path": str(path),
        "context": context,
        "manifest": manifest,
    }


def load_model_lane_policy(path: Path | str = MODEL_LANE_POLICY_PATH) -> dict[str, Any]:
    policy = load_json_path(path)
    validate_model_lane_policy(policy)
    return policy


def require_lane_fields(lane_id: str, lane: dict[str, Any], required_fields: set[str]) -> None:
    fields = set(lane.get("required_artifact_fields", []))
    missing = required_fields - fields
    if missing:
        raise TuningProfileError(f"{lane_id} missing required artifact fields: {', '.join(sorted(missing))}")


def require_forbidden_outputs(lane_id: str, lane: dict[str, Any], forbidden: set[str]) -> None:
    outputs = set(lane.get("forbidden_outputs", []))
    missing = forbidden - outputs
    if missing:
        raise TuningProfileError(f"{lane_id} missing forbidden outputs: {', '.join(sorted(missing))}")


def validate_model_lane_policy(policy: dict[str, Any]) -> None:
    if policy.get("artifact_type") != "model_lane_policy":
        raise TuningProfileError("model lane policy artifact_type must be model_lane_policy")
    if policy.get("schema_version") != MODEL_LANE_POLICY_SCHEMA_VERSION:
        raise TuningProfileError(f"model lane policy schema_version must be {MODEL_LANE_POLICY_SCHEMA_VERSION}")
    boundary = policy.get("authority_boundary", {})
    if boundary.get("scae_numeric_aggregation_uses_model") is not False:
        raise TuningProfileError("SCAE numeric aggregation must not use a model")
    if boundary.get("model_outputs_may_author_probability") is not False:
        raise TuningProfileError("model outputs may not author probability")
    if boundary.get("model_outputs_may_override_scae") is not False:
        raise TuningProfileError("model outputs may not override SCAE")
    lanes = policy.get("lanes", {})
    required_lane_defaults = {
        "decomposer_qdt_generation": "gpt-5.5-high",
        "researcher_leaf_nli_classification": "gpt-5.5-high",
        "native_research_candidate_discovery": "gpt-5.5-high",
    }
    for lane_id, model_id in required_lane_defaults.items():
        lane = lanes.get(lane_id)
        if not isinstance(lane, dict):
            raise TuningProfileError(f"missing lane {lane_id}")
        if lane.get("provider") != "openai":
            raise TuningProfileError(f"{lane_id} provider must be openai")
        if lane.get("default_model_id") != model_id:
            raise TuningProfileError(f"{lane_id} default_model_id must be {model_id}")
        require_lane_fields(lane_id, lane, {"resolved_model_id", "prompt_template_sha256", "model_policy_ref"})
        require_forbidden_outputs(lane_id, lane, {"probability", "scae_evidence_delta"} if lane_id == "native_research_candidate_discovery" else set())
    native = lanes["native_research_candidate_discovery"]
    if native.get("native_research_capability_required") is not True:
        raise TuningProfileError("native research lane must require native research capability")
    require_forbidden_outputs(
        "native_research_candidate_discovery",
        native,
        {
            "source_metadata_final_authority",
            "source_class_final_authority",
            "source_family_final_authority",
            "claim_family_final_authority",
            "research_sufficiency_certification",
            "probability",
            "scae_evidence_delta",
        },
    )
    classifier = lanes.get("source_metadata_classifier_assist")
    if not isinstance(classifier, dict):
        raise TuningProfileError("missing source_metadata_classifier_assist lane")
    if classifier.get("provider") != "openai":
        raise TuningProfileError("classifier assist provider must be openai")
    if classifier.get("default_model_id") != "gpt-5.4-mini":
        raise TuningProfileError("classifier assist default_model_id must be gpt-5.4-mini")
    if classifier.get("default_provider_model_key") != "openai/gpt-5.4-mini":
        raise TuningProfileError("classifier assist provider key must be openai/gpt-5.4-mini")
    if classifier.get("oauth_route_required") is not True:
        raise TuningProfileError("classifier assist must require OAuth route")
    require_lane_fields("source_metadata_classifier_assist", classifier, {"resolved_model_id", "prompt_template_sha256", "provider_model_key", "model_policy_ref"})
    require_forbidden_outputs(
        "source_metadata_classifier_assist",
        classifier,
        {
            "probability",
            "scae_evidence_delta",
            "research_sufficiency_certification",
            "protected_primary_final_authority",
            "temporal_safety_final_authority",
            "decision_output",
        },
    )
    for lane_id, lane in lanes.items():
        require_lane_fields(lane_id, lane, {"resolved_model_id"})
        if "prompt_template_id" in lane.get("required_artifact_fields", []):
            require_lane_fields(lane_id, lane, {"prompt_template_sha256"})
    embeddings = policy.get("local_embedding_lanes", {})
    embedding = embeddings.get("amrg_vector_embedding")
    if not isinstance(embedding, dict):
        raise TuningProfileError("missing amrg_vector_embedding lane")
    if embedding.get("provider") != "ollama":
        raise TuningProfileError("AMRG embedding provider must be ollama")
    if embedding.get("route_id") != "ollama/local":
        raise TuningProfileError("AMRG embedding route must be ollama/local")
    if embedding.get("default_model_id") != "BAAI/bge-base-en-v1.5":
        raise TuningProfileError("AMRG embedding model must be BAAI/bge-base-en-v1.5")
    require_lane_fields("amrg_vector_embedding", embedding, {"resolved_model_id", "descriptor_sha256", "model_policy_ref", "route_id"})
    require_forbidden_outputs(
        "amrg_vector_embedding",
        embedding,
        {"probability", "scae_evidence_delta", "relationship_promotion", "qdt_selection", "classification", "decision_output"},
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve ADS tuning profile context.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--evidence-packet-path", required=True, type=Path)
    parser.add_argument("--evidence-packet-ref", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--registry-json", type=Path)
    parser.add_argument("--active-domain-pointers-json", type=Path)
    parser.add_argument("--active-overlay-pointers-json", type=Path)
    parser.add_argument("--model-lane-policy", type=Path, default=MODEL_LANE_POLICY_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    evidence_packet = load_json_path(args.evidence_packet_path)
    registry = load_json_path(args.registry_json) if args.registry_json else None
    domain_pointers = load_json_path(args.active_domain_pointers_json) if args.active_domain_pointers_json else None
    overlay_pointers = load_json_path(args.active_overlay_pointers_json) if args.active_overlay_pointers_json else None
    load_model_lane_policy(args.model_lane_policy)
    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            result = materialize_effective_profile_context(
                conn,
                evidence_packet=evidence_packet,
                evidence_packet_ref=args.evidence_packet_ref,
                artifact_dir=args.artifact_dir,
                registry_metadata=registry,
                active_domain_pointers=domain_pointers,
                active_overlay_pointers=overlay_pointers,
                model_lane_policy_ref=str(args.model_lane_policy),
            )
        print(canonical_json({k: v for k, v in result.items() if k not in {"context", "manifest"}}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
