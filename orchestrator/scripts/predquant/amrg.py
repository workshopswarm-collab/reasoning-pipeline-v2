"""ADS v2 AMRG helper contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from predquant.ads_case_contract import parse_timestamp
from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    canonical_json,
    validate_artifact_manifest,
    write_artifact_manifest,
)
from predquant.evidence_packet import EVIDENCE_PACKET_SCHEMA_VERSION, validate_evidence_packet_v2
from predquant.tuning_profile import MODEL_LANE_POLICY_PATH, load_model_lane_policy


AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION = "amrg-market-vector-descriptor/v1"
AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION = "amrg-vector-index-snapshot/v1"
AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION = "amrg-vector-neighbor-candidate/v1"
AMRG_VECTOR_DIAGNOSTIC_SCHEMA_VERSION = "amrg-vector-candidate-source-diagnostic/v1"
AMRG_CANDIDATE_SCHEMA_VERSION = "amrg-candidate/v1"
AMRG_WEAK_EDGE_SCHEMA_VERSION = "amrg-weak-context-edge/v1"
RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION = "related-live-market-context/v1"
NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION = "no-related-context-waiver/v1"
AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION = "amrg-decomposer-context/v1"
RELATED_LIVE_MARKET_CONTEXT_ARTIFACT_TYPE = "related-live-market-context"
NO_RELATED_CONTEXT_WAIVER_ARTIFACT_TYPE = "no-related-context-waiver"
AMRG_VECTOR_LANE_ID = "amrg_vector_embedding"
AMRG_MODEL_ASSIST_LANE_ID = "amrg_model_assist"
AMRG_MODEL_ASSIST_PACKET_SCHEMA_VERSION = "amrg-model-assist-packet/v1"
AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION = "amrg-model-assist-output/v1"
AMRG_MODEL_ASSIST_PROVENANCE_SCHEMA_VERSION = "amrg-model-assist-provenance/v1"
AMRG_OLLAMA_PREFLIGHT_SCHEMA_VERSION = "amrg-ollama-vector-preflight/v1"
AMRG_DEPENDENCY_READINESS_SCHEMA_VERSION = "amrg-dependency-readiness/v1"
AMRG_OPERATOR_REPORT_SCHEMA_VERSION = "amrg-operator-report/v1"
AMRG_REFRESH_POLICY_SCHEMA_VERSION = "amrg-refresh-policy/v1"
AMRG_REFRESH_LIFECYCLE_SCHEMA_VERSION = "amrg-refresh-lifecycle/v1"
AMRG_SHARED_CACHE_ELIGIBILITY_SCHEMA_VERSION = "amrg-shared-cache-eligibility/v1"
AMRG_VECTOR_MODEL_ID = "BAAI/bge-base-en-v1.5"
AMRG_VECTOR_ROUTE_ID = "ollama/local"
AMRG_VECTOR_PROVIDER = "ollama"
AMRG_VECTOR_EMBEDDING_DIMENSION = 768
AMRG_VECTOR_SIMILARITY_METRIC = "cosine"
AMRG_VECTOR_CANDIDATE_SOURCE = "local_bge_vector_neighbor"
AMRG_VECTOR_EMBED_ENDPOINT = "/api/embed"
AMRG_VECTOR_KEEP_ALIVE = "5m"
AMRG_VECTOR_RUNTIME_NEIGHBOR_CAP = 5
AMRG_CONTEXT_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "005_amrg_context_persistence.sql"
AMRG_STAGE = "amrg"
AMRG_PRODUCER = "session-02-amrg"
DEFAULT_AMRG_CANDIDATE_CAP = 8
AMRG_DECOMPOSER_CONTEXT_MAX_HINTS = 12
AMRG_DECOMPOSER_DETERMINISTIC_HINT_CAP = 5
AMRG_DECOMPOSER_VECTOR_HINT_CAP = 5
AMRG_DECOMPOSER_ANCHOR_HINT_CAP = 2
WEAK_CONTEXT_ONLY = "weak_context_only"
RELATIONSHIP_TYPES = {
    "causal_upstream",
    "same_platform_family_sibling",
    "shared_named_entity",
    "shared_contract_source",
    "shared_resolution_source",
    "current_exposure_context",
    "generic_theme",
    "vector_similarity_neighbor",
}
RELATIONSHIP_STATUSES = {
    WEAK_CONTEXT_ONLY,
    "deterministic_context_candidate",
    "timing_mismatch_weak_context_only",
    "model_assisted_weak_context_only",
    "strict_precedence_anchor_candidate",
    "validated_strict_precedence_anchor",
}
TIMING_ALIGNMENT_STATUSES = {
    "aligned",
    "skew_warning",
    "skew_exceeds_policy",
    "missing_related_snapshot",
    "lookahead_blocked",
}
GRAPH_SAFETY_STATUSES = {
    "not_applicable_weak_context",
    "acyclic_placeholder",
    "acyclic_validated",
    "blocked_cycle_or_concurrent_timing",
}
STRICT_PRECEDENCE_ANCHOR_STATUSES = {
    "strict_precedence_anchor_candidate",
    "validated_strict_precedence_anchor",
}
ANCHOR_VALIDATION_STATUSES = {"not_evaluated", "validated", "rejected"}
QDT_ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION = "amrg-anchor-dependency-contract/v1"
QDT_ANCHOR_MODES_REQUIRING_CONDITION_SCOPE = {"anchor_optional", "anchor_required"}
SHARED_CACHE_ELIGIBILITY_STATUSES = {"eligible_reuse", "source_hint_only", "rejected"}
SHARED_CACHE_ENTRY_TYPE_TOKENS = {"retrieval", "classification", "classifier"}
REFRESH_STATUSES = {
    "not_requested_phase7_placeholder",
    "refresh_required_later",
    "unavailable_not_blocking",
    "not_requested_no_promoted_effect",
    "fresh_no_refresh_needed",
    "refresh_succeeded",
    "material_change_revalidated",
    "refresh_failed_downgraded_weak_context_only",
    "refresh_budget_exhausted_downgraded_weak_context_only",
    "stale_promoted_effect_downgraded_weak_context_only",
    "material_change_downgraded_weak_context_only",
}
MODEL_ASSIST_STATUSES = {
    "not_requested",
    "not_invoked_missing_active_safe_manifest",
    "advisory_validated",
    "advisory_unavailable_non_blocking",
    "advisory_rejected_forbidden_output",
}
VECTOR_READINESS_STATUSES = {
    "vector_ready",
    "vector_unavailable_allowed_weak_context",
    "vector_required_but_unavailable",
}
ASSIST_READINESS_STATUSES = {
    "assist_not_requested_by_policy",
    "assist_ready",
    "assist_failed",
}
AMRG_ALLOWED_EFFECTS_BY_STATUS = {
    WEAK_CONTEXT_ONLY: ["decomposition_context_hint"],
    "model_assisted_weak_context_only": ["decomposition_context_hint"],
    "timing_mismatch_weak_context_only": ["decomposition_context_hint"],
    "deterministic_context_candidate": ["decomposition_context_hint", "retrieval_query_hint"],
    "strict_precedence_anchor_candidate": ["decomposition_context_hint", "qdt_anchor_dependency_hint"],
    "validated_strict_precedence_anchor": [
        "decomposition_context_hint",
        "retrieval_query_hint",
        "qdt_anchor_dependency_hint",
        "condition_scoped_anchor_validation_input",
    ],
}
AMRG_WEAK_ALLOWED_EFFECTS = set(AMRG_ALLOWED_EFFECTS_BY_STATUS[WEAK_CONTEXT_ONLY])
AMRG_FORBIDDEN_EFFECTS = [
    "probability_authority",
    "scae_delta",
    "prior_anchor",
    "relationship_promotion",
    "edge_promotion",
    "retrieval_sufficiency",
    "qdt_selection",
    "qdt_repair",
    "scae_evidence_delta",
    "fair_value_authority",
    "interval_authority",
]
AMRG_SHARED_CACHE_FORBIDDEN_EFFECTS = sorted(
    set(
        AMRG_FORBIDDEN_EFFECTS
        + [
            "classification_authority",
            "researcher_verdict_authority",
            "production_forecast_write",
        ]
    )
)
AMRG_DECOMPOSER_CONTEXT_FORBIDDEN_USES = sorted(
    set(
        AMRG_FORBIDDEN_EFFECTS
        + [
            "qdt_selection",
            "qdt_repair",
            "prior_anchor",
            "probability_authority",
            "scae_delta",
            "production_forecast_write",
        ]
    )
)
AMRG_FORBIDDEN_ANCHOR_VALIDATED_EFFECTS = [
    effect for effect in AMRG_FORBIDDEN_EFFECTS if effect != "prior_anchor"
]
OPEN_STATUSES = {"open", "active"}
POST_CUTOFF_FIELDS = {"observed_at", "updated_at", "last_seen_at", "captured_at", "snapshot_observed_at"}
UNSAFE_MARKET_FIELDS = {
    "raw_payload",
    "payload",
    "raw_content",
    "content",
    "body",
    "html",
    "page_text",
    "resolved_outcome",
    "outcome",
    "outcome_status",
    "resolution_status",
    "resolution_source_payload",
    "score",
    "brier_score",
    "scoring",
    "scorecard",
    "market_prediction",
    "market_predictions",
    "replay",
    "replay_result",
    "training_trace",
    "post_resolution",
}
DETERMINISTIC_CANDIDATE_SOURCES = (
    "platform_family_context",
    "entity_match",
    "contract_source_match",
    "shared_resolution_source",
    "current_exposure",
    "generic_theme_match",
)
OPTIONAL_CANDIDATE_SOURCES = (AMRG_VECTOR_CANDIDATE_SOURCE,)
CANDIDATE_SOURCE_PRIORITY = {
    source: idx
    for idx, source in enumerate(DETERMINISTIC_CANDIDATE_SOURCES + OPTIONAL_CANDIDATE_SOURCES)
}
AMRG_FORBIDDEN_ARTIFACT_KEYS = UNSAFE_MARKET_FIELDS | {
    "raw_payload",
    "payload",
    "raw_content",
    "content",
    "body",
    "html",
    "page_text",
    "probability",
    "probabilities",
    "fair_value",
    "fair_value_probability",
    "probability_interval",
    "confidence_interval",
    "posterior_probability",
    "production_forecast_prob",
    "scae_delta",
    "scae_evidence_delta",
    "qdt_repair",
    "qdt_repairs",
    "repair_action",
    "repair_patch",
}
AMRG_FORBIDDEN_MODEL_OUTPUT_KEYS = AMRG_FORBIDDEN_ARTIFACT_KEYS | {
    "probability",
    "probabilities",
    "fair_value",
    "fair_value_probability",
    "interval",
    "probability_interval",
    "confidence_interval",
    "scae_delta",
    "scae_evidence_delta",
    "qdt_selection",
    "qdt_repair",
    "qdt_repairs",
    "repair_action",
    "repair_patch",
    "edge_promotion",
    "active_graph_promotion",
    "production_forecast_prob",
    "posterior_probability",
}
TOKEN_STOPWORDS = {
    "the",
    "and",
    "for",
    "will",
    "with",
    "this",
    "that",
    "market",
    "binary",
    "yes",
    "no",
}


class AMRGError(ValueError):
    """Raised when an AMRG vector-source contract is unsafe or malformed."""


@dataclass(frozen=True)
class PullResult:
    ok: bool
    reason: str | None = None


def forbidden_effects_for_status(status: str) -> list[str]:
    if status == "validated_strict_precedence_anchor":
        return list(AMRG_FORBIDDEN_ANCHOR_VALIDATED_EFFECTS)
    return list(AMRG_FORBIDDEN_EFFECTS)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prefixed_sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def row_to_dict(row: dict[str, Any] | Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def resolve_amrg_vector_embedding_lane(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_model_lane_policy(MODEL_LANE_POLICY_PATH)
    lane = policy.get("local_embedding_lanes", {}).get(AMRG_VECTOR_LANE_ID)
    if not isinstance(lane, dict):
        raise AMRGError("model policy missing amrg_vector_embedding lane")
    if lane.get("provider") != AMRG_VECTOR_PROVIDER:
        raise AMRGError("amrg_vector_embedding provider must be ollama")
    if lane.get("route_id") != AMRG_VECTOR_ROUTE_ID:
        raise AMRGError("amrg_vector_embedding route_id must be ollama/local")
    if lane.get("default_model_id") != AMRG_VECTOR_MODEL_ID:
        raise AMRGError("amrg_vector_embedding model must be BAAI/bge-base-en-v1.5")
    if lane.get("download_command_contract") != f"ollama pull {AMRG_VECTOR_MODEL_ID}":
        raise AMRGError("amrg_vector_embedding download contract is missing")
    required = set(lane.get("required_artifact_fields", []))
    missing = {
        "resolved_model_id",
        "model_policy_ref",
        "route_id",
        "descriptor_sha256",
        "embedding_dimension",
        "index_snapshot_id",
        "source_cutoff_timestamp",
    } - required
    if missing:
        raise AMRGError("amrg_vector_embedding missing required fields: " + ", ".join(sorted(missing)))
    return dict(lane)


def resolve_amrg_model_assist_lane(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_model_lane_policy(MODEL_LANE_POLICY_PATH)
    lane = policy.get("lanes", {}).get(AMRG_MODEL_ASSIST_LANE_ID)
    if not isinstance(lane, dict):
        raise AMRGError("model policy missing amrg_model_assist lane")
    if lane.get("provider") != "openai":
        raise AMRGError("amrg_model_assist provider must be openai")
    if lane.get("default_model_id") not in lane.get("allowed_model_ids", []):
        raise AMRGError("amrg_model_assist default_model_id must be allowed")
    if lane.get("owner_feature_id") != "AMRG-004":
        raise AMRGError("amrg_model_assist owner_feature_id must be AMRG-004")
    required = set(lane.get("required_artifact_fields", []))
    missing = {
        "model_lane_id",
        "resolved_model_id",
        "model_policy_ref",
        "prompt_template_id",
        "prompt_template_sha256",
        "input_manifest_sha256",
        "output_schema_version",
    } - required
    if missing:
        raise AMRGError("amrg_model_assist missing required fields: " + ", ".join(sorted(missing)))
    forbidden = set(lane.get("forbidden_outputs", []))
    missing_forbidden = {
        "probability",
        "scae_evidence_delta",
        "qdt_selection",
        "edge_promotion",
        "concept_creation",
        "label_creation",
        "active_graph_promotion",
    } - forbidden
    if missing_forbidden:
        raise AMRGError("amrg_model_assist missing forbidden outputs: " + ", ".join(sorted(missing_forbidden)))
    return dict(lane)


def amrg_vector_pull_policy(lane: dict[str, Any]) -> dict[str, Any]:
    configured = lane.get("pull_policy") if isinstance(lane.get("pull_policy"), dict) else {}
    explicit_allowed = configured.get("explicit_preflight_pull_allowed")
    if explicit_allowed is None:
        explicit_allowed = bool(lane.get("download_required"))
    return {
        "download_required": bool(lane.get("download_required")),
        "download_command_contract": lane["download_command_contract"],
        "default_pull_allowed": bool(configured.get("default_pull_allowed", False)),
        "explicit_preflight_pull_allowed": bool(explicit_allowed),
        "default_tests_must_not_require_ollama": bool(
            configured.get("default_tests_must_not_require_ollama", True)
        ),
    }


def amrg_model_assist_runtime_policy(lane: dict[str, Any]) -> dict[str, Any]:
    configured = lane.get("runtime_policy") if isinstance(lane.get("runtime_policy"), dict) else {}
    blocker = configured.get("shared_runtime_blocker") or (
        "AMRG assist has no registered shared runtime adapter in this phase; "
        "the existing runtime path is decomposer/QDT-specific."
    )
    return {
        "default_requested": bool(configured.get("default_requested", False)),
        "shared_runtime_reuse_status": configured.get("shared_runtime_reuse_status", "blocked"),
        "shared_runtime_blocker": str(blocker),
        "oauth_route_required": bool(lane.get("oauth_route_required", False)),
        "provider_route": lane.get("provider_route"),
        "runtime_agent_id": lane.get("runtime_agent_id"),
    }


def ensure_amrg_vector_model(
    policy: dict[str, Any] | None = None,
    *,
    model_available: bool = True,
    pull_result: PullResult | None = None,
) -> dict[str, Any]:
    lane = resolve_amrg_vector_embedding_lane(policy)
    if model_available:
        return {
            "ok": True,
            "embedding_lane_id": AMRG_VECTOR_LANE_ID,
            "provider": lane["provider"],
            "route_id": lane["route_id"],
            "resolved_model_id": lane["default_model_id"],
            "download_command_contract": lane["download_command_contract"],
            "pull_attempted": False,
            "unavailable_reason": None,
        }
    pull_result = pull_result or PullResult(False, "ollama_bge_model_unavailable")
    if pull_result.ok:
        return {
            "ok": True,
            "embedding_lane_id": AMRG_VECTOR_LANE_ID,
            "provider": lane["provider"],
            "route_id": lane["route_id"],
            "resolved_model_id": lane["default_model_id"],
            "download_command_contract": lane["download_command_contract"],
            "pull_attempted": True,
            "unavailable_reason": None,
        }
    return {
        "ok": False,
        "embedding_lane_id": AMRG_VECTOR_LANE_ID,
        "provider": lane["provider"],
        "route_id": lane["route_id"],
        "resolved_model_id": lane["default_model_id"],
        "download_command_contract": lane["download_command_contract"],
        "pull_attempted": True,
        "unavailable_reason": pull_result.reason or "ollama_bge_model_unavailable",
        "diagnostic": build_unavailable_vector_source_diagnostic(
            pull_result.reason or "ollama_bge_model_unavailable",
            source_cutoff_timestamp=None,
        ),
    }


class OllamaEmbeddingClient:
    """Tiny stdlib client for the local Ollama embedding route."""

    def __init__(self, base_url: str | None = None, *, timeout_seconds: int = 5) -> None:
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout_seconds = int(timeout_seconds)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = canonical_json(payload).encode("utf-8") if payload is not None else None
        request = urllib_request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AMRGError(f"ollama_http_{exc.code}: {detail[:200]}") from exc
        except (urllib_error.URLError, TimeoutError) as exc:
            raise AMRGError("ollama_route_unavailable") from exc
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise AMRGError("ollama_invalid_json_response") from exc
        if not isinstance(parsed, dict):
            raise AMRGError("ollama_response_must_be_object")
        return parsed

    def version(self) -> dict[str, Any]:
        return self._request("GET", "/api/version")

    def show_model(self, model: str) -> dict[str, Any]:
        return self._request("POST", "/api/show", {"model": model})

    def pull_model(self, model: str) -> dict[str, Any]:
        return self._request("POST", "/api/pull", {"model": model, "stream": False})

    def embed(
        self,
        model: str,
        inputs: str | list[str],
        *,
        truncate: bool = False,
        keep_alive: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "input": inputs,
            "truncate": truncate,
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        return self._request("POST", AMRG_VECTOR_EMBED_ENDPOINT, payload)


def redacted_ollama_base_url(base_url: str) -> str:
    parsed = urllib_parse.urlparse(base_url)
    hostname = parsed.hostname or ""
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return base_url.rstrip("/")
    netloc = "<redacted>"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urllib_parse.urlunparse((parsed.scheme, netloc, "", "", "", ""))


def _model_digest_from_show_payload(payload: dict[str, Any]) -> str:
    for key in ("digest", "model_digest", "sha256"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value if value.startswith("sha256:") else f"sha256:{value}"
    details = payload.get("details")
    if isinstance(details, dict):
        for key in ("digest", "model_digest", "sha256"):
            value = details.get(key)
            if isinstance(value, str) and value:
                return value if value.startswith("sha256:") else f"sha256:{value}"
    return prefixed_sha256(canonical_json(payload))


def validate_embedding_vector(
    vector: Any,
    *,
    expected_dimension: int = AMRG_VECTOR_EMBEDDING_DIMENSION,
) -> list[float]:
    if not isinstance(vector, list) or not vector:
        raise AMRGError("embedding vector must be a non-empty list")
    normalized: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AMRGError("embedding vector values must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise AMRGError("embedding vector values must be finite")
        normalized.append(numeric)
    if len(normalized) != expected_dimension:
        raise AMRGError(f"embedding dimension must be {expected_dimension}")
    return normalized


def parse_ollama_embeddings_response(
    payload: dict[str, Any],
    *,
    expected_count: int,
    expected_dimension: int = AMRG_VECTOR_EMBEDDING_DIMENSION,
) -> list[list[float]]:
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list):
        raise AMRGError("ollama /api/embed response must include embeddings")
    if len(embeddings) != expected_count:
        raise AMRGError("ollama embedding count mismatch")
    return [
        validate_embedding_vector(vector, expected_dimension=expected_dimension)
        for vector in embeddings
    ]


def _preflight_failure(
    reason: str,
    *,
    lane: dict[str, Any],
    client: Any,
    source_cutoff_timestamp: str | None,
    pull_policy: dict[str, Any] | None = None,
    allow_pull_requested: bool = False,
    allow_pull_effective: bool = False,
    model_show_payload: dict[str, Any] | None = None,
    pull_attempted: bool = False,
    pull_succeeded: bool = False,
    ollama_version: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": AMRG_OLLAMA_PREFLIGHT_SCHEMA_VERSION,
        "ok": False,
        "provider": lane["provider"],
        "route_id": lane["route_id"],
        "resolved_model_id": lane["default_model_id"],
        "download_command_contract": lane["download_command_contract"],
        "pull_policy": pull_policy or amrg_vector_pull_policy(lane),
        "allow_pull_requested": allow_pull_requested,
        "allow_pull_effective": allow_pull_effective,
        "ollama_base_url_redacted": redacted_ollama_base_url(getattr(client, "base_url", "")),
        "ollama_version": ollama_version,
        "model_digest": _model_digest_from_show_payload(model_show_payload) if model_show_payload else None,
        "pull_attempted": pull_attempted,
        "pull_succeeded": pull_succeeded,
        "embed_endpoint": AMRG_VECTOR_EMBED_ENDPOINT,
        "embedding_dimension": AMRG_VECTOR_EMBEDDING_DIMENSION,
        "unavailable_reason": reason,
        "diagnostic": build_unavailable_vector_source_diagnostic(
            reason,
            source_cutoff_timestamp=source_cutoff_timestamp,
            metadata={
                "preflight_schema_version": AMRG_OLLAMA_PREFLIGHT_SCHEMA_VERSION,
                "route_id": lane["route_id"],
                "resolved_model_id": lane["default_model_id"],
                "ollama_base_url_redacted": redacted_ollama_base_url(getattr(client, "base_url", "")),
                "download_command_contract": lane["download_command_contract"],
                "pull_policy": pull_policy or amrg_vector_pull_policy(lane),
                "allow_pull_requested": allow_pull_requested,
                "allow_pull_effective": allow_pull_effective,
            },
        ),
    }


def preflight_ollama_vector_embeddings(
    policy: dict[str, Any] | None = None,
    *,
    client: Any | None = None,
    allow_pull: bool = False,
    source_cutoff_timestamp: str | None = None,
) -> dict[str, Any]:
    lane = resolve_amrg_vector_embedding_lane(policy)
    pull_policy = amrg_vector_pull_policy(lane)
    allow_pull_effective = bool(allow_pull and pull_policy["explicit_preflight_pull_allowed"])
    client = client or OllamaEmbeddingClient()
    ollama_version = None
    try:
        version_payload = client.version()
        ollama_version = str(version_payload.get("version") or version_payload.get("ollama_version") or "unknown")
    except Exception:
        return _preflight_failure(
            "ollama_route_unavailable",
            lane=lane,
            client=client,
            source_cutoff_timestamp=source_cutoff_timestamp,
            pull_policy=pull_policy,
            allow_pull_requested=allow_pull,
            allow_pull_effective=allow_pull_effective,
        )

    pull_attempted = False
    pull_succeeded = False
    try:
        model_payload = client.show_model(lane["default_model_id"])
    except Exception:
        if not allow_pull_effective:
            return _preflight_failure(
                "ollama_bge_model_unavailable",
                lane=lane,
                client=client,
                source_cutoff_timestamp=source_cutoff_timestamp,
                pull_policy=pull_policy,
                allow_pull_requested=allow_pull,
                allow_pull_effective=allow_pull_effective,
                pull_attempted=False,
                ollama_version=ollama_version,
            )
        pull_attempted = True
        try:
            pull_payload = client.pull_model(lane["default_model_id"])
            pull_succeeded = bool(pull_payload.get("status") in {None, "success"} or pull_payload.get("completed") is True)
            model_payload = client.show_model(lane["default_model_id"])
        except Exception:
            return _preflight_failure(
                "ollama_bge_model_pull_failed",
                lane=lane,
                client=client,
                source_cutoff_timestamp=source_cutoff_timestamp,
                pull_policy=pull_policy,
                allow_pull_requested=allow_pull,
                allow_pull_effective=allow_pull_effective,
                pull_attempted=True,
                pull_succeeded=False,
                ollama_version=ollama_version,
            )

    try:
        smoke_payload = client.embed(
            lane["default_model_id"],
            "AMRG embedding smoke test",
            truncate=False,
        )
        parse_ollama_embeddings_response(smoke_payload, expected_count=1)
    except Exception as exc:
        return _preflight_failure(
            str(exc) or "ollama_embed_smoke_failed",
            lane=lane,
            client=client,
            source_cutoff_timestamp=source_cutoff_timestamp,
            pull_policy=pull_policy,
            allow_pull_requested=allow_pull,
            allow_pull_effective=allow_pull_effective,
            model_show_payload=model_payload,
            pull_attempted=pull_attempted,
            pull_succeeded=pull_succeeded,
            ollama_version=ollama_version,
        )

    return {
        "schema_version": AMRG_OLLAMA_PREFLIGHT_SCHEMA_VERSION,
        "ok": True,
        "provider": lane["provider"],
        "route_id": lane["route_id"],
        "resolved_model_id": lane["default_model_id"],
        "download_command_contract": lane["download_command_contract"],
        "pull_policy": pull_policy,
        "allow_pull_requested": allow_pull,
        "allow_pull_effective": allow_pull_effective,
        "ollama_base_url_redacted": redacted_ollama_base_url(getattr(client, "base_url", "")),
        "ollama_version": ollama_version,
        "model_digest": _model_digest_from_show_payload(model_payload),
        "pull_attempted": pull_attempted,
        "pull_succeeded": pull_succeeded,
        "embed_endpoint": AMRG_VECTOR_EMBED_ENDPOINT,
        "embedding_dimension": AMRG_VECTOR_EMBEDDING_DIMENSION,
        "unavailable_reason": None,
        "diagnostic": None,
    }


def amrg_vector_readiness_status(
    *,
    preflight: dict[str, Any] | None = None,
    vector_runtime_status: str | None = None,
    vector_required: bool = False,
) -> str:
    ready = bool((preflight or {}).get("ok")) or vector_runtime_status == "ready"
    if ready:
        return "vector_ready"
    if vector_required:
        return "vector_required_but_unavailable"
    return "vector_unavailable_allowed_weak_context"


def amrg_assist_readiness_status(
    *,
    model_assist_status: str | None = None,
    assist_requested_by_policy: bool = False,
) -> str:
    status = model_assist_status or "not_requested"
    if status == "advisory_validated":
        return "assist_ready"
    if status in {
        "not_invoked_missing_active_safe_manifest",
        "advisory_unavailable_non_blocking",
        "advisory_rejected_forbidden_output",
    }:
        return "assist_failed"
    if status == "not_requested" and not assist_requested_by_policy:
        return "assist_not_requested_by_policy"
    if status == "not_requested" and assist_requested_by_policy:
        return "assist_failed"
    return "assist_failed"


def build_amrg_dependency_readiness(
    *,
    policy: dict[str, Any] | None = None,
    vector_preflight: dict[str, Any] | None = None,
    vector_runtime: dict[str, Any] | None = None,
    vector_required: bool = False,
    model_assist_status: str | None = None,
    assist_requested_by_policy: bool | None = None,
) -> dict[str, Any]:
    policy = policy or load_model_lane_policy(MODEL_LANE_POLICY_PATH)
    vector_lane = resolve_amrg_vector_embedding_lane(policy)
    assist_lane = resolve_amrg_model_assist_lane(policy)
    vector_runtime = vector_runtime if isinstance(vector_runtime, dict) else {}
    vector_preflight = vector_preflight if isinstance(vector_preflight, dict) else (vector_runtime.get("preflight") or {})
    runtime_policy = amrg_model_assist_runtime_policy(assist_lane)
    if assist_requested_by_policy is None:
        assist_requested_by_policy = runtime_policy["default_requested"]
    vector_status = amrg_vector_readiness_status(
        preflight=vector_preflight,
        vector_runtime_status=vector_runtime.get("status"),
        vector_required=vector_required,
    )
    assist_status = amrg_assist_readiness_status(
        model_assist_status=model_assist_status,
        assist_requested_by_policy=bool(assist_requested_by_policy),
    )
    diagnostics = []
    vector_diagnostic = vector_preflight.get("diagnostic") if isinstance(vector_preflight, dict) else None
    if isinstance(vector_diagnostic, dict):
        diagnostics.append(vector_diagnostic)
    readiness = {
        "schema_version": AMRG_DEPENDENCY_READINESS_SCHEMA_VERSION,
        "vector_status": vector_status,
        "vector_required": bool(vector_required),
        "vector_ready": vector_status == "vector_ready",
        "vector_diagnostics": diagnostics,
        "ollama_route": {
            "provider": vector_preflight.get("provider") or vector_lane["provider"],
            "route_id": vector_preflight.get("route_id") or vector_lane["route_id"],
            "resolved_model_id": vector_preflight.get("resolved_model_id") or vector_lane["default_model_id"],
            "embedding_dimension": vector_preflight.get("embedding_dimension") or AMRG_VECTOR_EMBEDDING_DIMENSION,
            "embed_endpoint": vector_preflight.get("embed_endpoint") or AMRG_VECTOR_EMBED_ENDPOINT,
            "download_command_contract": vector_preflight.get("download_command_contract")
            or vector_lane["download_command_contract"],
            "pull_policy": vector_preflight.get("pull_policy") or amrg_vector_pull_policy(vector_lane),
            "pull_attempted": bool(vector_preflight.get("pull_attempted")),
            "pull_succeeded": bool(vector_preflight.get("pull_succeeded")),
            "allow_pull_requested": bool(vector_preflight.get("allow_pull_requested")),
            "allow_pull_effective": bool(vector_preflight.get("allow_pull_effective")),
            "ollama_base_url_redacted": vector_preflight.get("ollama_base_url_redacted"),
            "ollama_version": vector_preflight.get("ollama_version"),
            "model_digest": vector_preflight.get("model_digest"),
            "unavailable_reason": vector_preflight.get("unavailable_reason"),
        },
        "assist_status": assist_status,
        "assist_requested_by_policy": bool(assist_requested_by_policy),
        "model_assist_status": model_assist_status or "not_requested",
        "model_assist": {
            "model_lane_id": AMRG_MODEL_ASSIST_LANE_ID,
            "resolved_model_id": assist_lane.get("default_model_id"),
            "runtime_policy": runtime_policy,
            "forbidden_outputs": sorted(assist_lane.get("forbidden_outputs", [])),
            "authority": "advisory_only_no_promotion",
        },
        "authority": "dependency_readiness_only_no_probability_or_scae_authority",
    }
    ensure_no_raw_amrg_fields(readiness, "amrg_dependency_readiness")
    return readiness


def build_amrg_vector_preflight_report(
    policy: dict[str, Any] | None = None,
    *,
    client: Any | None = None,
    allow_pull: bool = False,
    vector_required: bool = False,
    source_cutoff_timestamp: str | None = None,
) -> dict[str, Any]:
    preflight = preflight_ollama_vector_embeddings(
        policy,
        client=client,
        allow_pull=allow_pull,
        source_cutoff_timestamp=source_cutoff_timestamp,
    )
    readiness = build_amrg_dependency_readiness(
        policy=policy,
        vector_preflight=preflight,
        vector_required=vector_required,
        model_assist_status="not_requested",
    )
    return {
        "schema_version": AMRG_OLLAMA_PREFLIGHT_SCHEMA_VERSION,
        "status": readiness["vector_status"],
        "ok": preflight["ok"],
        "blocking": readiness["vector_status"] == "vector_required_but_unavailable",
        "preflight": preflight,
        "dependency_readiness": readiness,
        "diagnostics": readiness["vector_diagnostics"],
        "authority": "vector_preflight_only_no_probability_or_scae_authority",
    }


def validate_no_unsafe_market_fields(market: dict[str, Any]) -> None:
    for key in market:
        normalized = str(key).lower()
        if normalized in UNSAFE_MARKET_FIELDS:
            raise AMRGError(f"market field {key} is not active-safe for AMRG vector descriptors")


def ensure_not_post_cutoff(market: dict[str, Any], source_cutoff_timestamp: str) -> None:
    cutoff = parse_timestamp(source_cutoff_timestamp, "source_cutoff_timestamp")
    for key in POST_CUTOFF_FIELDS:
        value = market.get(key)
        if value and parse_timestamp(str(value), key) > cutoff:
            raise AMRGError(f"market field {key} is after source_cutoff_timestamp")


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None and str(item)]
    return [str(value)]


def active_safe_market_fields(market_row: dict[str, Any] | Any, source_cutoff_timestamp: str) -> dict[str, Any]:
    market = row_to_dict(market_row)
    validate_no_unsafe_market_fields(market)
    status = str(market.get("status", "")).lower()
    if status not in OPEN_STATUSES:
        raise AMRGError(f"market status {status or '<missing>'} is not active-safe")
    ensure_not_post_cutoff(market, source_cutoff_timestamp)
    return {
        "title": market.get("title"),
        "description_or_rules": market.get("description") or market.get("rules_summary") or market.get("rules"),
        "normalized_entities": sorted(normalize_list(market.get("normalized_entities"))),
        "contract_terms": sorted(normalize_list(market.get("contract_terms"))),
        "source_of_truth_kind": market.get("source_of_truth_kind") or "unknown",
        "family_context_tokens": sorted(normalize_list(market.get("family_context_tokens"))),
        "close_timestamp": market.get("closes_at") or market.get("close_timestamp"),
        "resolve_timestamp": market.get("resolves_at") or market.get("resolve_timestamp"),
        "market_state_tags": sorted(
            normalize_list(market.get("market_state_tags"))
            + [status]
            + normalize_list(market.get("category"))
            + normalize_list(market.get("outcome_type"))
        ),
    }


def descriptor_text(active_safe_fields: dict[str, Any]) -> str:
    lines = [
        f"title={active_safe_fields.get('title') or ''}",
        f"description_or_rules={active_safe_fields.get('description_or_rules') or ''}",
        "normalized_entities=" + ",".join(active_safe_fields.get("normalized_entities") or []),
        "contract_terms=" + ",".join(active_safe_fields.get("contract_terms") or []),
        f"source_of_truth_kind={active_safe_fields.get('source_of_truth_kind') or 'unknown'}",
        "family_context_tokens=" + ",".join(active_safe_fields.get("family_context_tokens") or []),
        f"close_timestamp={active_safe_fields.get('close_timestamp') or ''}",
        f"resolve_timestamp={active_safe_fields.get('resolve_timestamp') or ''}",
        "market_state_tags=" + ",".join(active_safe_fields.get("market_state_tags") or []),
    ]
    return "\n".join(lines)


def build_active_market_descriptor(
    market_row: dict[str, Any] | Any,
    source_cutoff_timestamp: str,
    *,
    case_key: str | None = None,
) -> dict[str, Any]:
    market = row_to_dict(market_row)
    source_cutoff_timestamp = parse_timestamp(source_cutoff_timestamp, "source_cutoff_timestamp").isoformat()
    active_safe = active_safe_market_fields(market, source_cutoff_timestamp)
    text = descriptor_text(active_safe)
    descriptor = {
        "artifact_type": "amrg_market_vector_descriptor",
        "schema_version": AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION,
        "market_id": market.get("id") or market.get("market_id") or market.get("external_market_id"),
        "external_market_id": market.get("external_market_id"),
        "case_key": case_key,
        "source_cutoff_timestamp": source_cutoff_timestamp,
        "active_safe_fields": active_safe,
        "descriptor_text": text,
        "descriptor_sha256": prefixed_sha256(text),
    }
    validate_active_market_descriptor(descriptor)
    return descriptor


def validate_active_market_descriptor(descriptor: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "market_id",
        "source_cutoff_timestamp",
        "active_safe_fields",
        "descriptor_text",
        "descriptor_sha256",
    ]
    for field in required:
        if field not in descriptor:
            raise AMRGError(f"descriptor.{field} is required")
    if descriptor["artifact_type"] != "amrg_market_vector_descriptor":
        raise AMRGError("descriptor artifact_type must be amrg_market_vector_descriptor")
    if descriptor["schema_version"] != AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION:
        raise AMRGError(f"descriptor schema_version must be {AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION}")
    if descriptor["descriptor_sha256"] != prefixed_sha256(descriptor["descriptor_text"]):
        raise AMRGError("descriptor hash mismatch")
    validate_no_unsafe_market_fields(descriptor["active_safe_fields"])


def build_unavailable_vector_source_diagnostic(
    reason: str,
    *,
    source_cutoff_timestamp: str | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "schema_version": AMRG_VECTOR_DIAGNOSTIC_SCHEMA_VERSION,
        "reason_code": "amrg_vector_candidate_source_unavailable",
        "unavailable_reason": reason,
        "candidate_source": AMRG_VECTOR_CANDIDATE_SOURCE,
        "non_blocking": True,
        "does_not_block": [
            "deterministic_amrg_candidates",
            "related-live-market-context.json",
            "no-related-context waiver",
            "QDT",
            "retrieval",
            "SCAE",
            "decision",
        ],
        "source_cutoff_timestamp": source_cutoff_timestamp,
        "metadata": metadata or {},
    }
    ensure_no_raw_amrg_fields(diagnostic, "vector_source_diagnostic")
    return diagnostic


def build_vector_index_snapshot(
    descriptors: list[dict[str, Any]],
    *,
    status: str,
    unavailable_reason: str | None = None,
    source_cutoff_timestamp: str,
    model_policy_ref: str = "plans/autonomous-decomposition-swarm-model-lane-policy.json",
    embedding_model_sha256: str = "sha256:unavailable",
    ollama_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in {"ready", "unavailable", "degraded"}:
        raise AMRGError("index status must be ready, unavailable, or degraded")
    source_cutoff_timestamp = parse_timestamp(source_cutoff_timestamp, "source_cutoff_timestamp").isoformat()
    for descriptor in descriptors:
        validate_active_market_descriptor(descriptor)
    descriptor_hashes = sorted(descriptor["descriptor_sha256"] for descriptor in descriptors)
    index_snapshot_id = stable_id("amrg-vector-index", source_cutoff_timestamp, descriptor_hashes, status, unavailable_reason)
    snapshot = {
        "artifact_type": "amrg_vector_index_snapshot",
        "schema_version": AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION,
        "embedding_lane_id": AMRG_VECTOR_LANE_ID,
        "provider": AMRG_VECTOR_PROVIDER,
        "route_id": AMRG_VECTOR_ROUTE_ID,
        "resolved_model_id": AMRG_VECTOR_MODEL_ID,
        "model_policy_ref": model_policy_ref,
        "embedding_model_sha256": embedding_model_sha256,
        "embedding_dimension": AMRG_VECTOR_EMBEDDING_DIMENSION,
        "similarity_metric": AMRG_VECTOR_SIMILARITY_METRIC,
        "source_cutoff_timestamp": source_cutoff_timestamp,
        "descriptor_schema_version": AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION,
        "descriptor_count": len(descriptors),
        "descriptor_sha256s": descriptor_hashes,
        "index_snapshot_id": index_snapshot_id,
        "index_status": status,
        "unavailable_reason": unavailable_reason,
        "diagnostic": build_unavailable_vector_source_diagnostic(unavailable_reason, source_cutoff_timestamp=source_cutoff_timestamp)
        if status == "unavailable" and unavailable_reason
        else None,
        "ollama_preflight": ollama_preflight or {},
        "ollama_base_url_redacted": (ollama_preflight or {}).get("ollama_base_url_redacted"),
        "ollama_version": (ollama_preflight or {}).get("ollama_version"),
        "model_digest": (ollama_preflight or {}).get("model_digest"),
        "download_command_contract": (ollama_preflight or {}).get("download_command_contract")
        or f"ollama pull {AMRG_VECTOR_MODEL_ID}",
        "embed_endpoint": AMRG_VECTOR_EMBED_ENDPOINT,
        "keep_alive": AMRG_VECTOR_KEEP_ALIVE if status == "ready" else None,
    }
    validate_vector_index_snapshot(snapshot)
    return snapshot


def validate_vector_index_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("artifact_type") != "amrg_vector_index_snapshot":
        raise AMRGError("index snapshot artifact_type must be amrg_vector_index_snapshot")
    if snapshot.get("schema_version") != AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION:
        raise AMRGError(f"index snapshot schema_version must be {AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION}")
    for field, expected in (
        ("embedding_lane_id", AMRG_VECTOR_LANE_ID),
        ("provider", AMRG_VECTOR_PROVIDER),
        ("route_id", AMRG_VECTOR_ROUTE_ID),
        ("resolved_model_id", AMRG_VECTOR_MODEL_ID),
        ("similarity_metric", AMRG_VECTOR_SIMILARITY_METRIC),
        ("descriptor_schema_version", AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION),
    ):
        if snapshot.get(field) != expected:
            raise AMRGError(f"index snapshot {field} must be {expected}")
    if snapshot.get("embedding_dimension") != AMRG_VECTOR_EMBEDDING_DIMENSION:
        raise AMRGError("index snapshot embedding_dimension must be 768")
    if snapshot.get("index_status") == "ready" and snapshot.get("unavailable_reason"):
        raise AMRGError("ready index snapshot cannot have unavailable_reason")
    if snapshot.get("index_status") == "unavailable" and not snapshot.get("diagnostic"):
        raise AMRGError("unavailable index snapshot requires diagnostic")


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise AMRGError("embedding dimensions must match")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def build_vector_neighbor_candidates(
    *,
    query_descriptor: dict[str, Any],
    index_snapshot: dict[str, Any],
    neighbor_descriptors: list[dict[str, Any]],
    neighbor_scores: dict[str, float],
    cap: int,
) -> list[dict[str, Any]]:
    validate_active_market_descriptor(query_descriptor)
    validate_vector_index_snapshot(index_snapshot)
    if cap < 0:
        raise AMRGError("neighbor cap must be non-negative")
    if index_snapshot["index_status"] != "ready":
        return []
    rows: list[dict[str, Any]] = []
    for descriptor in neighbor_descriptors:
        validate_active_market_descriptor(descriptor)
        if descriptor["market_id"] == query_descriptor["market_id"]:
            continue
        descriptor_hash = descriptor["descriptor_sha256"]
        if descriptor_hash not in neighbor_scores:
            continue
        rows.append(
            {
                "schema_version": AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION,
                "candidate_source": AMRG_VECTOR_CANDIDATE_SOURCE,
                "relationship_status": WEAK_CONTEXT_ONLY,
                "vector_only": True,
                "market_id": descriptor["market_id"],
                "external_market_id": descriptor.get("external_market_id"),
                "similarity_score": float(neighbor_scores[descriptor_hash]),
                "similarity_metric": index_snapshot["similarity_metric"],
                "query_descriptor_sha256": query_descriptor["descriptor_sha256"],
                "candidate_descriptor_sha256": descriptor_hash,
                "index_snapshot_id": index_snapshot["index_snapshot_id"],
                "embedding_lane_id": index_snapshot["embedding_lane_id"],
                "resolved_model_id": index_snapshot["resolved_model_id"],
                "route_id": index_snapshot["route_id"],
            }
        )
    rows.sort(key=lambda row: (-row["similarity_score"], str(row["market_id"])))
    capped = rows[:cap]
    for row in capped:
        validate_vector_neighbor_candidate(row)
    return capped


def validate_vector_neighbor_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version") != AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION:
        raise AMRGError(f"candidate schema_version must be {AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION}")
    if candidate.get("candidate_source") != AMRG_VECTOR_CANDIDATE_SOURCE:
        raise AMRGError("candidate_source must be local_bge_vector_neighbor")
    if candidate.get("relationship_status") != WEAK_CONTEXT_ONLY:
        raise AMRGError("vector-only candidates must be weak_context_only")
    if candidate.get("vector_only") is not True:
        raise AMRGError("vector neighbor candidates must be marked vector_only")
    if not isinstance(candidate.get("similarity_score"), float):
        raise AMRGError("candidate similarity_score must be float")


def build_ready_vector_index(
    descriptors: list[dict[str, Any]],
    embeddings_by_descriptor_sha256: dict[str, list[float]],
    *,
    source_cutoff_timestamp: str,
    embedding_model_sha256: str = "sha256:fixture-model",
    ollama_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for descriptor in descriptors:
        validate_active_market_descriptor(descriptor)
        embedding = embeddings_by_descriptor_sha256.get(descriptor["descriptor_sha256"])
        if embedding is None:
            raise AMRGError("missing embedding for descriptor")
        validate_embedding_vector(embedding)
    return build_vector_index_snapshot(
        descriptors,
        status="ready",
        source_cutoff_timestamp=source_cutoff_timestamp,
        embedding_model_sha256=embedding_model_sha256,
        ollama_preflight=ollama_preflight,
    )


def search_vector_neighbors(
    *,
    query_descriptor: dict[str, Any],
    query_embedding: list[float],
    index_snapshot: dict[str, Any],
    candidate_descriptors: list[dict[str, Any]],
    embeddings_by_descriptor_sha256: dict[str, list[float]],
    cap: int,
) -> list[dict[str, Any]]:
    if index_snapshot["index_status"] != "ready":
        return []
    scores = {
        descriptor["descriptor_sha256"]: cosine_similarity(
            query_embedding,
            embeddings_by_descriptor_sha256[descriptor["descriptor_sha256"]],
        )
        for descriptor in candidate_descriptors
        if descriptor["descriptor_sha256"] in embeddings_by_descriptor_sha256
    }
    return build_vector_neighbor_candidates(
        query_descriptor=query_descriptor,
        index_snapshot=index_snapshot,
        neighbor_descriptors=candidate_descriptors,
        neighbor_scores=scores,
        cap=cap,
    )


def selected_market_descriptor_from_evidence_packet(evidence_packet: dict[str, Any]) -> dict[str, Any]:
    validate_evidence_packet_v2(evidence_packet)
    identity = evidence_packet.get("market_identity") or {}
    regime = evidence_packet.get("regime_seed_fields") or {}
    return build_active_market_descriptor(
        {
            "id": identity.get("internal_market_id") or evidence_packet.get("market_id"),
            "external_market_id": identity.get("external_market_id"),
            "status": identity.get("status") or regime.get("status") or "open",
            "title": identity.get("title"),
            "description": identity.get("description"),
            "category": identity.get("category") or regime.get("category"),
            "outcome_type": identity.get("outcome_type") or regime.get("outcome_type"),
            "closes_at": identity.get("closes_at") or regime.get("close_timestamp"),
            "resolves_at": identity.get("resolves_at") or regime.get("resolve_timestamp"),
            "normalized_entities": identity.get("normalized_entities") or [],
            "contract_terms": identity.get("contract_terms") or [identity.get("outcome_type") or regime.get("outcome_type")],
            "source_of_truth_kind": identity.get("source_of_truth_kind") or regime.get("source_of_truth_kind"),
            "family_context_tokens": [],
        },
        evidence_packet["source_cutoff_timestamp"],
        case_key=evidence_packet.get("case_key"),
    )


def active_market_vector_descriptors(
    active_market_index: list[dict[str, Any] | Any],
    *,
    source_cutoff_timestamp: str,
    selected_market_ids: set[str],
) -> tuple[list[dict[str, Any]], Counter]:
    records, exclusions = active_safe_candidate_records(
        active_market_index,
        source_cutoff_timestamp=source_cutoff_timestamp,
        selected_market_ids=selected_market_ids,
    )
    descriptors: list[dict[str, Any]] = []
    for record in records:
        try:
            descriptors.append(
                build_active_market_descriptor(
                    record["market"],
                    source_cutoff_timestamp,
                    case_key=str(record["market_id"]),
                )
            )
        except AMRGError as exc:
            exclusions[classify_active_safe_exclusion(exc)] += 1
    return descriptors, exclusions


def _vector_runtime_failure_result(
    reason: str,
    *,
    source_cutoff_timestamp: str,
    descriptors: list[dict[str, Any]] | None = None,
    selected_descriptor: dict[str, Any] | None = None,
    candidate_descriptors: list[dict[str, Any]] | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if descriptors is None:
        descriptors = ([selected_descriptor] if selected_descriptor else []) + list(candidate_descriptors or [])
    diagnostic = (preflight or {}).get("diagnostic") or build_unavailable_vector_source_diagnostic(
        reason,
        source_cutoff_timestamp=source_cutoff_timestamp,
    )
    snapshot = build_vector_index_snapshot(
        descriptors or [],
        status="unavailable",
        unavailable_reason=reason,
        source_cutoff_timestamp=source_cutoff_timestamp,
        ollama_preflight=preflight,
    )
    return {
        "schema_version": "amrg-live-vector-runtime/v1",
        "status": "unavailable",
        "preflight": preflight or {},
        "descriptors": descriptors or [],
        "selected_descriptor": selected_descriptor,
        "candidate_descriptors": candidate_descriptors or [],
        "embeddings_by_descriptor_sha256": {},
        "index_snapshot": snapshot,
        "vector_candidates": [],
        "vector_source_diagnostics": [diagnostic],
        "descriptor_exclusion_counts": {},
    }


def build_live_amrg_vector_runtime(
    *,
    evidence_packet: dict[str, Any],
    active_market_index: list[dict[str, Any] | Any],
    policy: dict[str, Any] | None = None,
    client: Any | None = None,
    allow_pull: bool = False,
    neighbor_cap: int = AMRG_VECTOR_RUNTIME_NEIGHBOR_CAP,
) -> dict[str, Any]:
    source_cutoff = parse_timestamp(evidence_packet["source_cutoff_timestamp"], "source_cutoff_timestamp").isoformat()
    try:
        selected_descriptor = selected_market_descriptor_from_evidence_packet(evidence_packet)
    except AMRGError as exc:
        return _vector_runtime_failure_result(
            str(exc),
            source_cutoff_timestamp=source_cutoff,
        )
    candidate_descriptors, exclusions = active_market_vector_descriptors(
        active_market_index,
        source_cutoff_timestamp=source_cutoff,
        selected_market_ids=selected_market_identity_strings(evidence_packet),
    )
    if not candidate_descriptors:
        return _vector_runtime_failure_result(
            "vector_candidate_descriptor_pool_empty",
            source_cutoff_timestamp=source_cutoff,
            selected_descriptor=selected_descriptor,
            candidate_descriptors=[],
        )
    preflight = preflight_ollama_vector_embeddings(
        policy,
        client=client,
        allow_pull=allow_pull,
        source_cutoff_timestamp=source_cutoff,
    )
    all_descriptors = [selected_descriptor] + candidate_descriptors
    if not preflight["ok"]:
        result = _vector_runtime_failure_result(
            preflight.get("unavailable_reason") or "ollama_vector_preflight_failed",
            source_cutoff_timestamp=source_cutoff,
            selected_descriptor=selected_descriptor,
            candidate_descriptors=candidate_descriptors,
            preflight=preflight,
        )
        result["descriptor_exclusion_counts"] = dict(sorted(exclusions.items()))
        return result

    client = client or OllamaEmbeddingClient()
    try:
        embed_payload = client.embed(
            preflight["resolved_model_id"],
            [descriptor["descriptor_text"] for descriptor in all_descriptors],
            truncate=False,
            keep_alive=AMRG_VECTOR_KEEP_ALIVE,
        )
        embeddings = parse_ollama_embeddings_response(embed_payload, expected_count=len(all_descriptors))
        embeddings_by_hash = {
            descriptor["descriptor_sha256"]: embedding
            for descriptor, embedding in zip(all_descriptors, embeddings)
        }
        index_snapshot = build_ready_vector_index(
            candidate_descriptors,
            {
                descriptor["descriptor_sha256"]: embeddings_by_hash[descriptor["descriptor_sha256"]]
                for descriptor in candidate_descriptors
            },
            source_cutoff_timestamp=source_cutoff,
            embedding_model_sha256=preflight["model_digest"],
            ollama_preflight=preflight,
        )
        vector_candidates = search_vector_neighbors(
            query_descriptor=selected_descriptor,
            query_embedding=embeddings_by_hash[selected_descriptor["descriptor_sha256"]],
            index_snapshot=index_snapshot,
            candidate_descriptors=candidate_descriptors,
            embeddings_by_descriptor_sha256=embeddings_by_hash,
            cap=neighbor_cap,
        )
    except Exception as exc:
        result = _vector_runtime_failure_result(
            str(exc) or "ollama_embed_failed",
            source_cutoff_timestamp=source_cutoff,
            selected_descriptor=selected_descriptor,
            candidate_descriptors=candidate_descriptors,
            preflight=preflight,
        )
        result["descriptor_exclusion_counts"] = dict(sorted(exclusions.items()))
        return result

    return {
        "schema_version": "amrg-live-vector-runtime/v1",
        "status": "ready",
        "preflight": preflight,
        "descriptors": all_descriptors,
        "selected_descriptor": selected_descriptor,
        "candidate_descriptors": candidate_descriptors,
        "embeddings_by_descriptor_sha256": embeddings_by_hash,
        "index_snapshot": index_snapshot,
        "vector_candidates": vector_candidates,
        "vector_source_diagnostics": [],
        "descriptor_exclusion_counts": dict(sorted(exclusions.items())),
    }


def descriptor_rows_for_write(descriptors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for descriptor in descriptors:
        validate_active_market_descriptor(descriptor)
    return [
        {
            "market_id": descriptor["market_id"],
            "external_market_id": descriptor.get("external_market_id"),
            "case_key": descriptor.get("case_key"),
            "source_cutoff_timestamp": descriptor["source_cutoff_timestamp"],
            "descriptor_schema_version": descriptor["schema_version"],
            "descriptor_sha256": descriptor["descriptor_sha256"],
            "descriptor_text": descriptor["descriptor_text"],
            "active_safe_fields": canonical_json(descriptor["active_safe_fields"]),
        }
        for descriptor in descriptors
    ]


def ensure_no_raw_amrg_fields(value: Any, path: str = "amrg_artifact") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in AMRG_FORBIDDEN_ARTIFACT_KEYS:
                raise AMRGError(f"{path}.{key} must not store raw, outcome, replay, or scoring content")
            ensure_no_raw_amrg_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_raw_amrg_fields(child, f"{path}[{idx}]")


def ensure_no_forbidden_model_output_fields(value: Any, path: str = "model_output") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in AMRG_FORBIDDEN_MODEL_OUTPUT_KEYS:
                raise AMRGError(f"{path}.{key} is forbidden in AMRG model-assist output")
            ensure_no_forbidden_model_output_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_forbidden_model_output_fields(child, f"{path}[{idx}]")


def text_tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        tokens: set[str] = set()
        for item in value:
            tokens.update(text_tokens(item))
        return tokens
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(token) >= 3 and token not in TOKEN_STOPWORDS
    }


def normalize_source_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        refs: list[str] = []
        for item in value:
            refs.extend(normalize_source_refs(item))
        return sorted(set(refs))
    normalized = str(value).strip().lower()
    return [normalized] if normalized else []


def normalize_timestamp_or_none(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return parse_timestamp(str(value), field).isoformat()


def normalized_scope_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def first_nested_value(source: dict[str, Any], fields: tuple[str, ...], containers: tuple[str, ...]) -> Any:
    for field in fields:
        if field in source:
            return source[field]
    for container_name in containers:
        container = source.get(container_name)
        if not isinstance(container, dict):
            continue
        for field in fields:
            if field in container:
                return container[field]
    return None


def shared_cache_entry_id(entry: dict[str, Any]) -> str:
    entry_id = first_nested_value(
        entry,
        ("cache_entry_id", "shared_cache_entry_id", "entry_id", "evidence_ref", "classification_id", "cache_key"),
        ("metadata",),
    )
    return str(entry_id) if entry_id else stable_id("amrg-shared-cache-entry", prefixed_sha256(canonical_json(entry)))


def shared_cache_entry_type(entry: dict[str, Any]) -> str:
    entry_type = first_nested_value(
        entry,
        ("cache_entry_type", "entry_type", "artifact_type", "cache_type"),
        ("metadata",),
    )
    return str(entry_type).strip().lower() if entry_type else "unknown"


def shared_cache_entry_type_supported(entry_type: str) -> bool:
    tokens = text_tokens(entry_type)
    return bool(tokens & SHARED_CACHE_ENTRY_TYPE_TOKENS)


def shared_cache_scope_value(entry: dict[str, Any], field: str) -> str | None:
    return normalized_scope_value(
        first_nested_value(
            entry,
            (field,),
            ("scope", "dispatch_scope", "cache_scope", "metadata"),
        )
    )


def shared_cache_source_timestamp_value(entry: dict[str, Any]) -> Any:
    return first_nested_value(
        entry,
        (
            "max_underlying_source_timestamp",
            "max_source_timestamp",
            "source_max_timestamp",
            "latest_underlying_source_timestamp",
        ),
        ("temporal_provenance", "source_temporal_provenance", "provenance"),
    )


def max_temporal_source_timestamp(value: Any) -> str | None:
    if value is None or value == "":
        return None
    values = value if isinstance(value, (list, tuple, set)) else [value]
    parsed = [parse_timestamp(str(item), "max_underlying_source_timestamp") for item in values if item not in (None, "")]
    if not parsed:
        return None
    return max(parsed).isoformat()


def normalize_consuming_dispatch(
    context: dict[str, Any] | None = None,
    consuming_dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    dispatch = dict(consuming_dispatch or {})
    dispatch_id = dispatch.get("dispatch_id") or context.get("dispatch_id")
    forecast_timestamp = dispatch.get("forecast_timestamp") or context.get("forecast_timestamp")
    normalized = {
        "dispatch_id": str(dispatch_id) if dispatch_id else None,
        "leaf_condition_scope": normalized_scope_value(dispatch.get("leaf_condition_scope") or context.get("leaf_condition_scope")),
        "contract_scope": normalized_scope_value(dispatch.get("contract_scope") or context.get("contract_scope")),
        "forecast_timestamp": parse_timestamp(str(forecast_timestamp), "forecast_timestamp").isoformat()
        if forecast_timestamp
        else None,
    }
    return normalized


def shared_cache_reuse_reason_codes(
    *,
    entry_leaf_scope: str | None,
    entry_contract_scope: str | None,
    entry_type: str,
    max_source_timestamp: str | None,
    consuming_dispatch: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not shared_cache_entry_type_supported(entry_type):
        reasons.append("unsupported_cache_entry_type")
    if not consuming_dispatch.get("leaf_condition_scope"):
        reasons.append("missing_consuming_leaf_condition_scope")
    if not consuming_dispatch.get("contract_scope"):
        reasons.append("missing_consuming_contract_scope")
    if not consuming_dispatch.get("forecast_timestamp"):
        reasons.append("missing_consuming_forecast_timestamp")
    if not entry_leaf_scope:
        reasons.append("missing_cache_leaf_condition_scope")
    elif entry_leaf_scope != consuming_dispatch.get("leaf_condition_scope"):
        reasons.append("leaf_condition_scope_mismatch")
    if not entry_contract_scope:
        reasons.append("missing_cache_contract_scope")
    elif entry_contract_scope != consuming_dispatch.get("contract_scope"):
        reasons.append("contract_scope_mismatch")

    scope_rejected = any(
        reason in reasons
        for reason in (
            "unsupported_cache_entry_type",
            "missing_consuming_leaf_condition_scope",
            "missing_consuming_contract_scope",
            "missing_consuming_forecast_timestamp",
            "missing_cache_leaf_condition_scope",
            "leaf_condition_scope_mismatch",
            "missing_cache_contract_scope",
            "contract_scope_mismatch",
        )
    )
    if scope_rejected:
        return "rejected", sorted(set(reasons))

    if not max_source_timestamp:
        return "source_hint_only", ["missing_max_underlying_source_timestamp"]

    source_at = parse_timestamp(max_source_timestamp, "max_underlying_source_timestamp")
    forecast_at = parse_timestamp(consuming_dispatch["forecast_timestamp"], "forecast_timestamp")
    if source_at >= forecast_at:
        return "source_hint_only", ["max_underlying_source_not_before_consuming_forecast"]
    return "eligible_reuse", ["temporal_provenance_precedes_consuming_forecast"]


def validate_shared_cache_eligibility(assessment: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "eligibility_id",
        "cache_entry_id",
        "cache_entry_type",
        "eligibility_status",
        "allowed_use",
        "reason_codes",
        "leaf_condition_scope",
        "contract_scope",
        "max_underlying_source_timestamp",
        "consuming_forecast_timestamp",
        "forbidden_effects",
        "authority",
    ]
    for field in required:
        if field not in assessment:
            raise AMRGError(f"shared cache eligibility {field} is required")
    if assessment["schema_version"] != AMRG_SHARED_CACHE_ELIGIBILITY_SCHEMA_VERSION:
        raise AMRGError(f"shared cache eligibility schema_version must be {AMRG_SHARED_CACHE_ELIGIBILITY_SCHEMA_VERSION}")
    if assessment["eligibility_status"] not in SHARED_CACHE_ELIGIBILITY_STATUSES:
        raise AMRGError("shared cache eligibility status is unknown")
    if assessment["authority"] != "temporal_provenance_only_no_forecast_authority":
        raise AMRGError("shared cache eligibility authority must be temporal-provenance only")
    for effect in ("probability_authority", "scae_delta", "qdt_repair", "production_forecast_write"):
        if effect not in assessment["forbidden_effects"]:
            raise AMRGError(f"shared cache eligibility must forbid {effect}")
    if assessment["eligibility_status"] == "eligible_reuse":
        if assessment["allowed_use"] != "shared_retrieval_classification_cache_reuse":
            raise AMRGError("eligible shared cache must use the conservative cache reuse mode")
        source_at = parse_timestamp(assessment["max_underlying_source_timestamp"], "max_underlying_source_timestamp")
        forecast_at = parse_timestamp(assessment["consuming_forecast_timestamp"], "consuming_forecast_timestamp")
        if source_at >= forecast_at:
            raise AMRGError("eligible shared cache source timestamp must be before forecast timestamp")
    ensure_no_raw_amrg_fields(assessment, "shared_cache_eligibility")


def evaluate_shared_cache_entry_eligibility(
    entry: dict[str, Any],
    consuming_dispatch: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise AMRGError("shared cache entry must be an object")
    ensure_no_raw_amrg_fields(entry, "shared_cache_entry")
    normalized_dispatch = normalize_consuming_dispatch(consuming_dispatch=consuming_dispatch)
    entry_id = shared_cache_entry_id(entry)
    entry_type = shared_cache_entry_type(entry)
    entry_leaf_scope = shared_cache_scope_value(entry, "leaf_condition_scope")
    entry_contract_scope = shared_cache_scope_value(entry, "contract_scope")
    invalid_timestamp = False
    try:
        max_source_timestamp = max_temporal_source_timestamp(shared_cache_source_timestamp_value(entry))
    except Exception:
        max_source_timestamp = None
        invalid_timestamp = True
    status, reason_codes = shared_cache_reuse_reason_codes(
        entry_leaf_scope=entry_leaf_scope,
        entry_contract_scope=entry_contract_scope,
        entry_type=entry_type,
        max_source_timestamp=max_source_timestamp,
        consuming_dispatch=normalized_dispatch,
    )
    if invalid_timestamp and status != "rejected":
        status = "source_hint_only"
        reason_codes = ["invalid_max_underlying_source_timestamp"]

    if status == "eligible_reuse":
        allowed_use = "shared_retrieval_classification_cache_reuse"
    elif status == "source_hint_only":
        allowed_use = "source_hint_only_requires_fresh_retrieval_or_classification"
    else:
        allowed_use = "not_reusable"
    assessment = {
        "schema_version": AMRG_SHARED_CACHE_ELIGIBILITY_SCHEMA_VERSION,
        "eligibility_id": stable_id(
            "amrg-shared-cache-eligibility",
            normalized_dispatch.get("dispatch_id"),
            entry_id,
            status,
            sorted(set(reason_codes)),
        ),
        "cache_entry_id": entry_id,
        "cache_entry_type": entry_type,
        "consuming_dispatch_id": normalized_dispatch.get("dispatch_id"),
        "eligibility_status": status,
        "allowed_use": allowed_use,
        "reason_codes": sorted(set(reason_codes)),
        "leaf_condition_scope": {
            "entry": entry_leaf_scope,
            "consuming_dispatch": normalized_dispatch.get("leaf_condition_scope"),
        },
        "contract_scope": {
            "entry": entry_contract_scope,
            "consuming_dispatch": normalized_dispatch.get("contract_scope"),
        },
        "max_underlying_source_timestamp": max_source_timestamp,
        "consuming_forecast_timestamp": normalized_dispatch.get("forecast_timestamp"),
        "forbidden_effects": AMRG_SHARED_CACHE_FORBIDDEN_EFFECTS,
        "authority": "temporal_provenance_only_no_forecast_authority",
        "metadata": {
            "temporal_provenance_required": True,
            "scope_match_required": True,
            "cache_payload_persisted_by_amrg": False,
            "no_probability_authority": True,
            "no_scae_delta_written": True,
            "qdt_repair_authority": "forbidden",
            "production_forecast_write_authority": "forbidden",
        },
    }
    validate_shared_cache_eligibility(assessment)
    return assessment


def normalize_shared_cache_entries(shared_cache_entries: Any) -> list[dict[str, Any]]:
    if shared_cache_entries is None:
        return []
    if isinstance(shared_cache_entries, dict):
        for key in ("shared_cache_entries", "cache_entries", "entries"):
            if key in shared_cache_entries:
                return normalize_shared_cache_entries(shared_cache_entries[key])
        return [shared_cache_entries]
    if isinstance(shared_cache_entries, (list, tuple)):
        entries = list(shared_cache_entries)
    else:
        raise AMRGError("shared_cache_entries must be an object or list")
    if any(not isinstance(entry, dict) for entry in entries):
        raise AMRGError("shared cache entries must be objects")
    return entries


def apply_shared_cache_reuse_eligibility(
    context: dict[str, Any],
    *,
    shared_cache_entries: Any = None,
    consuming_dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_related_live_market_context(context)
    entries = normalize_shared_cache_entries(shared_cache_entries)
    if not entries:
        return dict(context)
    dispatch = normalize_consuming_dispatch(context, consuming_dispatch)
    assessments = [
        evaluate_shared_cache_entry_eligibility(entry, dispatch)
        for entry in entries
    ]
    updated = {**context, "shared_cache_eligibility": assessments}
    validate_related_live_market_context(updated)
    return updated


def market_identity_value(market: dict[str, Any]) -> Any:
    return market.get("id") or market.get("market_id") or market.get("external_market_id")


def market_identity_strings(market: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for value in (
            market.get("id"),
            market.get("market_id"),
            market.get("external_market_id"),
        )
        if value is not None and str(value)
    }


def selected_market_identity_strings(evidence_packet: dict[str, Any]) -> set[str]:
    market_identity = evidence_packet.get("market_identity", {})
    return {
        str(value)
        for value in (
            evidence_packet.get("market_id"),
            market_identity.get("internal_market_id"),
            market_identity.get("external_market_id"),
        )
        if value is not None and str(value)
    }


def classify_active_safe_exclusion(exc: AMRGError) -> str:
    message = str(exc)
    if "after source_cutoff" in message:
        return "post_cutoff_market"
    if "status" in message:
        return "inactive_or_resolved_market"
    return "unsafe_market_fields"


def is_before_or_at_cutoff(timestamp: str | None, source_cutoff_timestamp: str, field: str) -> bool:
    if not timestamp:
        return False
    return parse_timestamp(timestamp, field) <= parse_timestamp(source_cutoff_timestamp, "source_cutoff_timestamp")


def active_safe_candidate_records(
    active_market_index: list[dict[str, Any] | Any],
    *,
    source_cutoff_timestamp: str,
    selected_market_ids: set[str],
) -> tuple[list[dict[str, Any]], Counter]:
    records: list[dict[str, Any]] = []
    exclusions: Counter = Counter()
    normalized_cutoff = parse_timestamp(source_cutoff_timestamp, "source_cutoff_timestamp").isoformat()
    for row in active_market_index:
        market = row_to_dict(row)
        if market_identity_strings(market) & selected_market_ids:
            exclusions["selected_market_excluded"] += 1
            continue
        try:
            active_safe = active_safe_market_fields(market, normalized_cutoff)
        except AMRGError as exc:
            exclusions[classify_active_safe_exclusion(exc)] += 1
            continue
        if is_before_or_at_cutoff(active_safe.get("close_timestamp"), normalized_cutoff, "candidate_close_timestamp"):
            exclusions["past_market"] += 1
            continue
        if is_before_or_at_cutoff(active_safe.get("resolve_timestamp"), normalized_cutoff, "candidate_resolve_timestamp"):
            exclusions["past_market"] += 1
            continue

        active_safe_hash = prefixed_sha256(canonical_json(active_safe))
        records.append(
            {
                "market": market,
                "market_id": market_identity_value(market),
                "external_market_id": market.get("external_market_id"),
                "active_safe_fields": active_safe,
                "active_safe_fields_hash": active_safe_hash,
                "timing_inputs": {
                    "source_cutoff_timestamp": normalized_cutoff,
                    "candidate_close_timestamp": active_safe.get("close_timestamp"),
                    "candidate_resolve_timestamp": active_safe.get("resolve_timestamp"),
                },
            }
        )
    records.sort(key=lambda row: (str(row["market_id"]), row["active_safe_fields_hash"]))
    return records, exclusions


def selected_case_tokens(evidence_packet: dict[str, Any]) -> dict[str, set[str]]:
    identity = evidence_packet.get("market_identity", {})
    regime = evidence_packet.get("regime_seed_fields", {})
    family = evidence_packet.get("family_context", {})
    return {
        "entities": text_tokens(identity.get("title")) | text_tokens(identity.get("description")),
        "contract_terms": text_tokens(identity.get("outcome_type")),
        "category": text_tokens(identity.get("category") or regime.get("category")),
        "family": text_tokens(family.get("parent_event_id"))
        | text_tokens(family.get("selected_child_market_id"))
        | text_tokens(family.get("relation_constraints")),
        "source_refs": set(normalize_source_refs(
            [
                identity.get("source_of_truth_kind"),
                identity.get("resolution_source"),
                identity.get("source_url"),
                identity.get("source_of_truth_url"),
            ]
        )),
    }


def source_reference_tokens(market: dict[str, Any], active_safe_fields: dict[str, Any]) -> set[str]:
    return set(
        normalize_source_refs(
            [
                active_safe_fields.get("source_of_truth_kind"),
                market.get("resolution_source"),
                market.get("source_url"),
                market.get("source_of_truth_url"),
                market.get("shared_resolution_source"),
            ]
        )
    )


def market_record_tokens(record: dict[str, Any]) -> dict[str, set[str]]:
    active_safe = record["active_safe_fields"]
    market = record["market"]
    return {
        "entities": text_tokens(active_safe.get("normalized_entities")) | text_tokens(active_safe.get("title")),
        "contract_terms": text_tokens(active_safe.get("contract_terms")),
        "category": text_tokens(market.get("category")) | text_tokens(active_safe.get("market_state_tags")),
        "family": text_tokens(active_safe.get("family_context_tokens")),
        "source_refs": source_reference_tokens(market, active_safe),
    }


def candidate_source_ref(source: str, ref_id: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    ref = {"source": source, "ref_id": str(ref_id)}
    if details:
        ref["details"] = details
    return ref


def make_candidate(
    record: dict[str, Any],
    *,
    source: str,
    reason_codes: list[str],
    source_refs: list[dict[str, Any]],
    vector_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source not in CANDIDATE_SOURCE_PRIORITY:
        raise AMRGError(f"unknown candidate source: {source}")
    vector_fields = vector_fields or {}
    active_safe = record["active_safe_fields"]
    candidate = {
        "schema_version": AMRG_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": stable_id(
            "amrg-candidate",
            record["market_id"],
            source,
            sorted(reason_codes),
            record["active_safe_fields_hash"],
        ),
        "candidate_source": source,
        "candidate_sources": [source],
        "relationship_status": WEAK_CONTEXT_ONLY,
        "market_id": record["market_id"],
        "external_market_id": record.get("external_market_id"),
        "title": active_safe.get("title"),
        "active_safe_fields_hash": record["active_safe_fields_hash"],
        "reason_codes": sorted(set(reason_codes)),
        "source_refs": source_refs,
        "timing_inputs": dict(record["timing_inputs"]),
        "vector_only": bool(vector_fields.get("vector_only", False)),
        "vector_provenance": vector_fields.get("vector_provenance"),
    }
    validate_amrg_candidate(candidate)
    return candidate


def validate_amrg_candidate(candidate: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "candidate_id",
        "candidate_source",
        "candidate_sources",
        "relationship_status",
        "market_id",
        "active_safe_fields_hash",
        "reason_codes",
        "source_refs",
        "timing_inputs",
        "vector_only",
    ]
    for field in required:
        if field not in candidate:
            raise AMRGError(f"candidate.{field} is required")
    if candidate["schema_version"] != AMRG_CANDIDATE_SCHEMA_VERSION:
        raise AMRGError(f"candidate schema_version must be {AMRG_CANDIDATE_SCHEMA_VERSION}")
    if candidate["relationship_status"] != WEAK_CONTEXT_ONLY:
        raise AMRGError("Phase 6 candidates must default to weak_context_only")
    if candidate["candidate_source"] not in CANDIDATE_SOURCE_PRIORITY:
        raise AMRGError("candidate_source is unknown")
    for source in candidate["candidate_sources"]:
        if source not in CANDIDATE_SOURCE_PRIORITY:
            raise AMRGError("candidate_sources contains unknown source")
    if not candidate["candidate_id"].startswith("amrg-candidate:"):
        raise AMRGError("candidate_id must use amrg-candidate prefix")
    if not str(candidate["active_safe_fields_hash"]).startswith("sha256:"):
        raise AMRGError("candidate active_safe_fields_hash must be sha256")
    if not isinstance(candidate["reason_codes"], list) or not candidate["reason_codes"]:
        raise AMRGError("candidate reason_codes must be non-empty")
    if not isinstance(candidate["source_refs"], list):
        raise AMRGError("candidate source_refs must be a list")
    timing = candidate["timing_inputs"]
    if not isinstance(timing, dict) or not timing.get("source_cutoff_timestamp"):
        raise AMRGError("candidate timing_inputs.source_cutoff_timestamp is required")
    parse_timestamp(timing["source_cutoff_timestamp"], "candidate.source_cutoff_timestamp")
    ensure_no_raw_amrg_fields(candidate, "candidate")


def platform_family_candidates(
    evidence_packet: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    family = evidence_packet.get("family_context", {})
    sibling_ids = {str(item) for item in family.get("sibling_child_ids", []) if item is not None}
    if not sibling_ids:
        return []
    parent_event_id = family.get("parent_event_id")
    rows: list[dict[str, Any]] = []
    for record in records:
        market_ids = market_identity_strings(record["market"])
        if market_ids & sibling_ids:
            rows.append(
                make_candidate(
                    record,
                    source="platform_family_context",
                    reason_codes=["family_sibling_context_only"],
                    source_refs=[
                        candidate_source_ref(
                            "evidence_packet.family_context",
                            parent_event_id or "family",
                            {"selected_child_market_id": family.get("selected_child_market_id")},
                        )
                    ],
                )
            )
    return rows


def active_market_entity_matches(
    evidence_packet: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = selected_case_tokens(evidence_packet)
    rows: list[dict[str, Any]] = []
    for record in records:
        tokens = market_record_tokens(record)
        overlaps = (selected["entities"] & tokens["entities"]) | (selected["contract_terms"] & tokens["contract_terms"])
        if overlaps:
            rows.append(
                make_candidate(
                    record,
                    source="entity_match",
                    reason_codes=["active_safe_entity_or_contract_term_overlap"],
                    source_refs=[
                        candidate_source_ref(
                            "active_market_index",
                            record["market_id"],
                            {"overlap_tokens": sorted(overlaps)[:8]},
                        )
                    ],
                )
            )
    return rows


def contract_source_matches(
    evidence_packet: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = selected_case_tokens(evidence_packet)
    rows: list[dict[str, Any]] = []
    for record in records:
        tokens = market_record_tokens(record)
        overlaps = selected["source_refs"] & tokens["source_refs"]
        if overlaps and "unknown" not in overlaps:
            rows.append(
                make_candidate(
                    record,
                    source="contract_source_match",
                    reason_codes=["contract_source_of_truth_overlap"],
                    source_refs=[
                        candidate_source_ref(
                            "active_market_index.source_of_truth",
                            record["market_id"],
                            {"overlap_tokens": sorted(overlaps)[:8]},
                        )
                    ],
                )
            )
    return rows


def shared_resolution_source_matches(
    evidence_packet: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    identity = evidence_packet.get("market_identity", {})
    selected_refs = set(
        normalize_source_refs(
            [
                identity.get("resolution_source"),
                identity.get("source_url"),
                identity.get("source_of_truth_url"),
            ]
        )
    )
    if not selected_refs:
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        overlaps = selected_refs & market_record_tokens(record)["source_refs"]
        if overlaps:
            rows.append(
                make_candidate(
                    record,
                    source="shared_resolution_source",
                    reason_codes=["shared_resolution_source_overlap"],
                    source_refs=[
                        candidate_source_ref(
                            "active_market_index.resolution_source",
                            record["market_id"],
                            {"overlap_tokens": sorted(overlaps)[:8]},
                        )
                    ],
                )
            )
    return rows


def exposure_market_ids(exposure_context: Any) -> set[str]:
    if exposure_context is None:
        return set()
    if isinstance(exposure_context, dict):
        values = []
        for key in ("market_ids", "current_market_ids", "exposed_market_ids", "markets"):
            value = exposure_context.get(key)
            if isinstance(value, list):
                values.extend(value)
            elif value:
                values.append(value)
        return {str(value.get("market_id", value.get("id"))) if isinstance(value, dict) else str(value) for value in values}
    if isinstance(exposure_context, list):
        return {str(value.get("market_id", value.get("id"))) if isinstance(value, dict) else str(value) for value in exposure_context}
    return set()


def current_exposure_matches(
    records: list[dict[str, Any]],
    exposure_context: Any,
) -> list[dict[str, Any]]:
    ids = exposure_market_ids(exposure_context)
    if not ids:
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        if market_identity_strings(record["market"]) & ids:
            rows.append(
                make_candidate(
                    record,
                    source="current_exposure",
                    reason_codes=["current_exposure_context"],
                    source_refs=[candidate_source_ref("exposure_context", record["market_id"])],
                )
            )
    return rows


def generic_theme_matches(
    evidence_packet: dict[str, Any],
    records: list[dict[str, Any]],
    existing_market_ids: set[str],
) -> list[dict[str, Any]]:
    selected = selected_case_tokens(evidence_packet)
    rows: list[dict[str, Any]] = []
    for record in records:
        if str(record["market_id"]) in existing_market_ids:
            continue
        tokens = market_record_tokens(record)
        overlaps = selected["category"] & tokens["category"]
        if overlaps:
            rows.append(
                make_candidate(
                    record,
                    source="generic_theme_match",
                    reason_codes=["generic_theme_match_weak_context_only"],
                    source_refs=[
                        candidate_source_ref(
                            "active_market_index.category",
                            record["market_id"],
                            {"overlap_tokens": sorted(overlaps)[:8]},
                        )
                    ],
                )
            )
    return rows


def vector_neighbor_context_candidates(
    vector_candidates: list[dict[str, Any]] | None,
    records_by_market_id: dict[str, dict[str, Any]],
    exclusions: Counter,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vector_candidate in vector_candidates or []:
        try:
            validate_vector_neighbor_candidate(vector_candidate)
        except AMRGError:
            exclusions["invalid_vector_candidate"] += 1
            continue
        record = records_by_market_id.get(str(vector_candidate["market_id"]))
        if not record:
            exclusions["vector_candidate_not_active_safe"] += 1
            continue
        rows.append(
            make_candidate(
                record,
                source=AMRG_VECTOR_CANDIDATE_SOURCE,
                reason_codes=["local_vector_neighbor_weak_context_only"],
                source_refs=[
                    candidate_source_ref(
                        AMRG_VECTOR_CANDIDATE_SOURCE,
                        vector_candidate.get("index_snapshot_id", "vector-index"),
                        {
                            "candidate_descriptor_sha256": vector_candidate.get("candidate_descriptor_sha256"),
                            "query_descriptor_sha256": vector_candidate.get("query_descriptor_sha256"),
                        },
                    )
                ],
                vector_fields={
                    "vector_only": True,
                    "vector_provenance": {
                        "similarity_score": vector_candidate.get("similarity_score"),
                        "similarity_metric": vector_candidate.get("similarity_metric"),
                        "index_snapshot_id": vector_candidate.get("index_snapshot_id"),
                        "embedding_lane_id": vector_candidate.get("embedding_lane_id"),
                        "resolved_model_id": vector_candidate.get("resolved_model_id"),
                        "route_id": vector_candidate.get("route_id"),
                    },
                },
            )
        )
    return rows


def normalize_vector_diagnostics(vector_source_diagnostics: Any) -> list[dict[str, Any]]:
    if vector_source_diagnostics is None:
        return []
    diagnostics = vector_source_diagnostics if isinstance(vector_source_diagnostics, list) else [vector_source_diagnostics]
    normalized: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        if not diagnostic:
            continue
        if not isinstance(diagnostic, dict):
            raise AMRGError("vector diagnostics must be objects")
        if diagnostic.get("reason_code") == "amrg_vector_candidate_source_unavailable" and diagnostic.get("non_blocking") is not True:
            raise AMRGError("vector unavailable diagnostic must be non-blocking")
        ensure_no_raw_amrg_fields(diagnostic, "vector_source_diagnostic")
        normalized.append(dict(diagnostic))
    return normalized


def merge_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed = {canonical_json(ref): ref for ref in refs}
    return [keyed[key] for key in sorted(keyed)]


def dedupe_and_cap_candidates(candidates: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    if cap < 0:
        raise AMRGError("candidate cap must be non-negative")
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        validate_amrg_candidate(candidate)
        market_id = str(candidate["market_id"])
        existing = grouped.get(market_id)
        if existing is None:
            grouped[market_id] = dict(candidate)
            continue
        source_order = min(
            CANDIDATE_SOURCE_PRIORITY[existing["candidate_source"]],
            CANDIDATE_SOURCE_PRIORITY[candidate["candidate_source"]],
        )
        preferred_source = next(source for source, priority in CANDIDATE_SOURCE_PRIORITY.items() if priority == source_order)
        existing["candidate_source"] = preferred_source
        existing["candidate_sources"] = sorted(
            set(existing["candidate_sources"]) | set(candidate["candidate_sources"]),
            key=lambda source: CANDIDATE_SOURCE_PRIORITY[source],
        )
        existing["reason_codes"] = sorted(set(existing["reason_codes"]) | set(candidate["reason_codes"]))
        existing["source_refs"] = merge_source_refs(existing["source_refs"] + candidate["source_refs"])
        existing["vector_only"] = existing["vector_only"] and candidate["vector_only"]
        if candidate.get("vector_provenance") and not existing.get("vector_provenance"):
            existing["vector_provenance"] = candidate["vector_provenance"]
        existing["candidate_id"] = stable_id(
            "amrg-candidate",
            existing["market_id"],
            existing["candidate_sources"],
            existing["reason_codes"],
            existing["active_safe_fields_hash"],
        )
    ordered = sorted(
        grouped.values(),
        key=lambda candidate: (
            CANDIDATE_SOURCE_PRIORITY[candidate["candidate_source"]],
            str(candidate["market_id"]),
        ),
    )[:cap]
    for idx, candidate in enumerate(ordered, start=1):
        candidate["candidate_rank"] = idx
        validate_amrg_candidate(candidate)
    return ordered


def amrg_source_policy(candidate_cap: int) -> dict[str, Any]:
    return {
        "candidate_pool_max": candidate_cap,
        "deterministic_sources": list(DETERMINISTIC_CANDIDATE_SOURCES),
        "optional_sources": list(OPTIONAL_CANDIDATE_SOURCES),
        "vector_source_required": False,
        "active_safe_statuses": sorted(OPEN_STATUSES),
        "forbidden_market_field_policy": "reject_outcome_replay_scoring_and_raw_content_fields",
        "forbidden_market_field_count": len(UNSAFE_MARKET_FIELDS),
        "post_cutoff_fields": sorted(POST_CUTOFF_FIELDS),
        "edge_default": WEAK_CONTEXT_ONLY,
        "phase_scope": "phase_6_candidate_pool_and_weak_context_artifact",
    }


def amrg_timing_inputs(evidence_packet: dict[str, Any]) -> dict[str, Any]:
    prior = evidence_packet.get("prior_reliability_inputs", {})
    micro = prior.get("rolling_microstructure", {}) if isinstance(prior, dict) else {}
    return {
        "forecast_timestamp": evidence_packet["forecast_timestamp"],
        "source_cutoff_timestamp": evidence_packet["source_cutoff_timestamp"],
        "market_priced_through_timestamp": micro.get("market_priced_through_timestamp"),
        "prior_snapshot_age_seconds": micro.get("market_snapshot_age_seconds"),
    }


def input_manifest_hash(input_manifest_ids: list[str]) -> str:
    return prefixed_sha256(canonical_json(sorted(input_manifest_ids)))


def candidate_set_id_for(
    *,
    evidence_packet: dict[str, Any],
    candidates: list[dict[str, Any]],
    input_hash: str,
) -> str:
    return stable_id(
        "amrg-candidate-set",
        evidence_packet["case_id"],
        evidence_packet["dispatch_id"],
        input_hash,
        [candidate["candidate_id"] for candidate in candidates],
    )


def build_amrg_candidate_pool(
    *,
    evidence_packet: dict[str, Any],
    evidence_packet_ref: str,
    active_market_index: list[dict[str, Any] | Any],
    exposure_context: Any = None,
    vector_candidates: list[dict[str, Any]] | None = None,
    vector_source_diagnostics: Any = None,
    profile_context_ref: str | None = None,
    candidate_cap: int = DEFAULT_AMRG_CANDIDATE_CAP,
) -> dict[str, Any]:
    validate_evidence_packet_v2(evidence_packet)
    if evidence_packet["schema_version"] != EVIDENCE_PACKET_SCHEMA_VERSION:
        raise AMRGError("AMRG candidate pool requires evidence-packet/v2")
    if not evidence_packet_ref:
        raise AMRGError("evidence_packet_ref is required")
    selected_ids = selected_market_identity_strings(evidence_packet)
    records, exclusion_counts = active_safe_candidate_records(
        active_market_index,
        source_cutoff_timestamp=evidence_packet["source_cutoff_timestamp"],
        selected_market_ids=selected_ids,
    )
    records_by_market_id = {str(record["market_id"]): record for record in records}

    deterministic_candidates: list[dict[str, Any]] = []
    deterministic_candidates.extend(platform_family_candidates(evidence_packet, records))
    deterministic_candidates.extend(active_market_entity_matches(evidence_packet, records))
    deterministic_candidates.extend(contract_source_matches(evidence_packet, records))
    deterministic_candidates.extend(shared_resolution_source_matches(evidence_packet, records))
    deterministic_candidates.extend(current_exposure_matches(records, exposure_context))
    deterministic_ids = {str(candidate["market_id"]) for candidate in deterministic_candidates}
    deterministic_candidates.extend(generic_theme_matches(evidence_packet, records, deterministic_ids))

    vector_context_candidates = vector_neighbor_context_candidates(vector_candidates, records_by_market_id, exclusion_counts)
    candidates = dedupe_and_cap_candidates(
        deterministic_candidates + vector_context_candidates,
        candidate_cap,
    )
    input_manifest_ids = [evidence_packet_ref]
    if profile_context_ref:
        input_manifest_ids.append(profile_context_ref)
    hashed_inputs = input_manifest_hash(input_manifest_ids)
    return {
        "candidate_set_id": candidate_set_id_for(
            evidence_packet=evidence_packet,
            candidates=candidates,
            input_hash=hashed_inputs,
        ),
        "input_manifest_ids": input_manifest_ids,
        "input_manifest_hash": hashed_inputs,
        "source_policy": amrg_source_policy(candidate_cap),
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "timing_inputs": amrg_timing_inputs(evidence_packet),
        "vector_source_diagnostics": normalize_vector_diagnostics(vector_source_diagnostics),
        "candidates": candidates,
    }


def make_weak_edge(candidate_set_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    validate_amrg_candidate(candidate)
    edge = {
        "schema_version": AMRG_WEAK_EDGE_SCHEMA_VERSION,
        "edge_id": stable_id("amrg-edge", candidate_set_id, candidate["candidate_id"]),
        "candidate_id": candidate["candidate_id"],
        "market_id": candidate["market_id"],
        "relationship_status": WEAK_CONTEXT_ONLY,
        "relationship_label": "weak_context_untyped_phase6",
        "allowed_effects": AMRG_ALLOWED_EFFECTS_BY_STATUS[WEAK_CONTEXT_ONLY],
        "forbidden_effects": forbidden_effects_for_status(WEAK_CONTEXT_ONLY),
        "concept_authority": "none_candidate_input_only",
    }
    ensure_no_raw_amrg_fields(edge, "relationship_edge")
    return edge


def build_related_live_market_context_or_waiver(
    *,
    evidence_packet: dict[str, Any],
    evidence_packet_ref: str,
    active_market_index: list[dict[str, Any] | Any],
    exposure_context: Any = None,
    vector_candidates: list[dict[str, Any]] | None = None,
    vector_source_diagnostics: Any = None,
    profile_context_ref: str | None = None,
    candidate_cap: int = DEFAULT_AMRG_CANDIDATE_CAP,
) -> dict[str, Any]:
    pool = build_amrg_candidate_pool(
        evidence_packet=evidence_packet,
        evidence_packet_ref=evidence_packet_ref,
        active_market_index=active_market_index,
        exposure_context=exposure_context,
        vector_candidates=vector_candidates,
        vector_source_diagnostics=vector_source_diagnostics,
        profile_context_ref=profile_context_ref,
        candidate_cap=candidate_cap,
    )
    common = {
        "case_id": evidence_packet["case_id"],
        "case_key": evidence_packet["case_key"],
        "market_id": evidence_packet["market_id"],
        "dispatch_id": evidence_packet["dispatch_id"],
        "forecast_timestamp": evidence_packet["forecast_timestamp"],
        "source_cutoff_timestamp": evidence_packet["source_cutoff_timestamp"],
        "evidence_packet_ref": evidence_packet_ref,
        "profile_context_ref": profile_context_ref,
        **pool,
    }
    common["refresh_policy"] = normalize_refresh_policy(common, None)
    if not pool["candidates"]:
        waiver = {
            "artifact_type": "no_related_context_waiver",
            "schema_version": NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION,
            "waiver_id": stable_id(
                "amrg-waiver",
                evidence_packet["case_id"],
                evidence_packet["dispatch_id"],
                pool["input_manifest_hash"],
                "empty_active_safe_candidate_pool",
            ),
            "reason_code": "empty_active_safe_candidate_pool",
            "non_blocking": True,
            "relationship_edges": [],
            **common,
        }
        validate_no_related_context_waiver(waiver)
        return attach_amrg_decomposer_context(waiver)
    context = {
        "artifact_type": "related_live_market_context",
        "schema_version": RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION,
        "relationship_edges": [
            make_weak_edge(pool["candidate_set_id"], candidate)
            for candidate in pool["candidates"]
        ],
        **common,
    }
    validate_related_live_market_context(context)
    return attach_amrg_decomposer_context(context)


def validate_common_amrg_artifact(artifact: dict[str, Any], *, schema_version: str) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "case_id",
        "case_key",
        "dispatch_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "evidence_packet_ref",
        "candidate_set_id",
        "input_manifest_ids",
        "input_manifest_hash",
        "source_policy",
        "exclusion_counts",
        "timing_inputs",
        "vector_source_diagnostics",
        "candidates",
        "relationship_edges",
    ]
    for field in required:
        if field not in artifact:
            raise AMRGError(f"{field} is required")
    if artifact["schema_version"] != schema_version:
        raise AMRGError(f"schema_version must be {schema_version}")
    for field in ("case_id", "case_key", "dispatch_id", "forecast_timestamp", "source_cutoff_timestamp", "evidence_packet_ref"):
        if not artifact.get(field):
            raise AMRGError(f"{field} is required")
    parse_timestamp(artifact["forecast_timestamp"], "forecast_timestamp")
    parse_timestamp(artifact["source_cutoff_timestamp"], "source_cutoff_timestamp")
    if artifact["input_manifest_hash"] != input_manifest_hash(artifact["input_manifest_ids"]):
        raise AMRGError("input_manifest_hash mismatch")
    cap = artifact["source_policy"].get("candidate_pool_max")
    if len(artifact["candidates"]) > cap:
        raise AMRGError("candidate cap exceeded")
    for candidate in artifact["candidates"]:
        validate_amrg_candidate(candidate)
    expected_candidate_set_id = stable_id(
        "amrg-candidate-set",
        artifact["case_id"],
        artifact["dispatch_id"],
        artifact["input_manifest_hash"],
        [candidate["candidate_id"] for candidate in artifact["candidates"]],
    )
    if artifact["candidate_set_id"] != expected_candidate_set_id:
        raise AMRGError("candidate_set_id mismatch")
    shared_cache_eligibility = artifact.get("shared_cache_eligibility", [])
    if not isinstance(shared_cache_eligibility, list):
        raise AMRGError("shared_cache_eligibility must be a list")
    for assessment in shared_cache_eligibility:
        validate_shared_cache_eligibility(assessment)
    ensure_no_raw_amrg_fields(artifact)


def validate_related_live_market_context(context: dict[str, Any]) -> None:
    validate_common_amrg_artifact(context, schema_version=RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION)
    if context["artifact_type"] != "related_live_market_context":
        raise AMRGError("artifact_type must be related_live_market_context")
    if not context["candidates"]:
        raise AMRGError("related_live_market_context requires at least one candidate")
    candidate_ids = {candidate["candidate_id"] for candidate in context["candidates"]}
    if len(context["relationship_edges"]) != len(context["candidates"]):
        raise AMRGError("relationship edge count must match candidate count")
    for edge in context["relationship_edges"]:
        if edge.get("candidate_id") not in candidate_ids:
            raise AMRGError("edge references unknown candidate")
        validate_relationship_edge(edge)


def validate_no_related_context_waiver(waiver: dict[str, Any]) -> None:
    validate_common_amrg_artifact(waiver, schema_version=NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION)
    if waiver["artifact_type"] != "no_related_context_waiver":
        raise AMRGError("artifact_type must be no_related_context_waiver")
    if waiver.get("reason_code") != "empty_active_safe_candidate_pool":
        raise AMRGError("waiver reason_code must be empty_active_safe_candidate_pool")
    if waiver.get("non_blocking") is not True:
        raise AMRGError("no-related-context waiver must be non-blocking")
    if waiver["candidates"] or waiver["relationship_edges"]:
        raise AMRGError("no-related-context waiver must not include candidates or edges")
    if not str(waiver.get("waiver_id", "")).startswith("amrg-waiver:"):
        raise AMRGError("waiver_id must use amrg-waiver prefix")


def _candidate_lookup(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        candidate["candidate_id"]: candidate
        for candidate in context.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }


def _edge_relation_types(edge: dict[str, Any]) -> list[str]:
    if isinstance(edge.get("relationship_types"), list) and edge["relationship_types"]:
        return validate_relationship_type_list(edge["relationship_types"])
    label = edge.get("relationship_label")
    if label == "weak_context_untyped_phase6":
        return ["generic_theme"]
    return ["generic_theme"]


def _refresh_status_for_hint(edge: dict[str, Any]) -> str:
    lifecycle = edge.get("refresh_lifecycle_state")
    if isinstance(lifecycle, dict) and lifecycle.get("refresh_status"):
        return str(lifecycle["refresh_status"])
    status = edge.get("relationship_status")
    if status in {"deterministic_context_candidate", "strict_precedence_anchor_candidate", "validated_strict_precedence_anchor"}:
        return "fresh_no_refresh_needed"
    return "not_requested_no_promoted_effect"


def _hint_category(edge: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    status = edge.get("relationship_status")
    relationship_types = set(_edge_relation_types(edge))
    candidate_sources = set(candidate.get("candidate_sources") or [])
    if status in STRICT_PRECEDENCE_ANCHOR_STATUSES:
        return "strict_precedence_anchor_hint"
    if status == "deterministic_context_candidate":
        return "deterministic_relationship_hint"
    if (
        candidate.get("vector_only")
        or candidate.get("candidate_source") == AMRG_VECTOR_CANDIDATE_SOURCE
        or AMRG_VECTOR_CANDIDATE_SOURCE in candidate_sources
        or "vector_similarity_neighbor" in relationship_types
    ):
        return "vector_neighbor_weak_context_hint"
    if status in {WEAK_CONTEXT_ONLY, "timing_mismatch_weak_context_only", "model_assisted_weak_context_only"}:
        return "weak_context_hint"
    return None


def _candidate_leaf_relevance(edge: dict[str, Any], candidate: dict[str, Any], category: str) -> dict[str, Any]:
    allowed_leaf_uses = ["context_leaf"]
    if "retrieval_query_hint" in edge.get("allowed_effects", []):
        allowed_leaf_uses.append("retrieval_hint")
    if "qdt_anchor_dependency_hint" in edge.get("allowed_effects", []):
        allowed_leaf_uses.append("conditional_anchor_dependency_request")
    return {
        "allowed_leaf_uses": sorted(set(allowed_leaf_uses)),
        "suggested_purposes": (
            ["structural", "resolution_mechanics"]
            if category == "strict_precedence_anchor_hint"
            else ["other"]
            if category in {"weak_context_hint", "vector_neighbor_weak_context_hint"}
            else ["direct_evidence", "catalyst", "other"]
        ),
        "reason_codes": sorted(set(candidate.get("reason_codes", [])))[:6],
    }


def _amrg_decomposer_hint(edge: dict[str, Any], candidate: dict[str, Any], category: str) -> dict[str, Any]:
    relation_types = _edge_relation_types(edge)
    hint = {
        "hint_ref": edge["edge_id"],
        "candidate_ref": edge["candidate_id"],
        "hint_category": category,
        "source_market_ref": {
            "market_id": str(candidate.get("market_id")),
            "external_market_id": candidate.get("external_market_id"),
            "candidate_id": candidate["candidate_id"],
        },
        "relation_type": relation_types[0],
        "relation_types": relation_types,
        "effect_status": edge["relationship_status"],
        "allowed_use": list(edge.get("allowed_effects", [])),
        "prohibited_use": list(edge.get("forbidden_effects", [])),
        "freshness_status": {
            "timing_alignment_status": edge.get("timing_alignment_status"),
            "refresh_status": _refresh_status_for_hint(edge),
            "selected_market_snapshot_as_of": edge.get("selected_market_snapshot_as_of"),
            "related_market_snapshot_as_of": edge.get("related_market_snapshot_as_of"),
        },
        "candidate_leaf_relevance": _candidate_leaf_relevance(edge, candidate, category),
        "authority": "context_hint_only_no_forecast_authority",
    }
    ensure_no_raw_amrg_fields(hint, "amrg_decomposer_hint")
    return hint


def _sort_hint_key(hint: dict[str, Any]) -> tuple[int, str]:
    priority = {
        "strict_precedence_anchor_hint": 0,
        "deterministic_relationship_hint": 1,
        "vector_neighbor_weak_context_hint": 2,
        "weak_context_hint": 3,
    }
    return priority.get(str(hint.get("hint_category")), 9), str(hint.get("hint_ref"))


def _capped_hint_groups(hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = {
        "deterministic_relationship_hint": AMRG_DECOMPOSER_DETERMINISTIC_HINT_CAP,
        "vector_neighbor_weak_context_hint": AMRG_DECOMPOSER_VECTOR_HINT_CAP,
        "strict_precedence_anchor_hint": AMRG_DECOMPOSER_ANCHOR_HINT_CAP,
    }
    selected: list[dict[str, Any]] = []
    for category, cap in groups.items():
        rows = [hint for hint in hints if hint["hint_category"] == category]
        selected.extend(sorted(rows, key=_sort_hint_key)[:cap])
    if not selected:
        weak_rows = [hint for hint in hints if hint["hint_category"] == "weak_context_hint"]
        selected.extend(sorted(weak_rows, key=_sort_hint_key)[:AMRG_DECOMPOSER_CONTEXT_MAX_HINTS])
    return sorted(selected, key=_sort_hint_key)[:AMRG_DECOMPOSER_CONTEXT_MAX_HINTS]


def build_amrg_decomposer_context(context: dict[str, Any]) -> dict[str, Any]:
    """Build the bounded, non-authoritative AMRG prompt section for Decomposer."""

    if context.get("artifact_type") == "no_related_context_waiver":
        validate_no_related_context_waiver(context)
        hints: list[dict[str, Any]] = []
    else:
        validate_related_live_market_context(context)
        candidates_by_id = _candidate_lookup(context)
        raw_hints: list[dict[str, Any]] = []
        for edge in context.get("relationship_edges", []):
            candidate = candidates_by_id.get(edge.get("candidate_id"))
            if candidate is None:
                continue
            category = _hint_category(edge, candidate)
            if category is None:
                continue
            raw_hints.append(_amrg_decomposer_hint(edge, candidate, category))
        hints = _capped_hint_groups(raw_hints)

    section = {
        "schema_version": AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION,
        "context_ref": context.get("candidate_set_id"),
        "source_artifact_type": context.get("artifact_type"),
        "source_schema_version": context.get("schema_version"),
        "hint_cap": AMRG_DECOMPOSER_CONTEXT_MAX_HINTS,
        "hint_caps": {
            "deterministic_relationship_hint": AMRG_DECOMPOSER_DETERMINISTIC_HINT_CAP,
            "vector_neighbor_weak_context_hint": AMRG_DECOMPOSER_VECTOR_HINT_CAP,
            "strict_precedence_anchor_hint": AMRG_DECOMPOSER_ANCHOR_HINT_CAP,
        },
        "hints": hints,
        "operator_metadata": {
            "hint_refs_considered": [hint["hint_ref"] for hint in hints],
            "hint_count_by_category": dict(Counter(hint["hint_category"] for hint in hints)),
            "allowed_qdt_uses": ["context_leaf", "retrieval_hint", "conditional_anchor_dependency_request"],
            "forbidden_qdt_uses": AMRG_DECOMPOSER_CONTEXT_FORBIDDEN_USES,
            "qdt_leaf_reference_field": "branches[].amrg_usage_refs or related_market_context_usage.amrg_usage_refs",
        },
        "authority": "context_hints_only_no_forecast_or_selection_authority",
    }
    validate_amrg_decomposer_context(section)
    return section


def validate_amrg_decomposer_context(section: dict[str, Any]) -> None:
    if section.get("schema_version") != AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION:
        raise AMRGError(f"amrg decomposer context schema_version must be {AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION}")
    if section.get("authority") != "context_hints_only_no_forecast_or_selection_authority":
        raise AMRGError("amrg decomposer context authority is invalid")
    hints = section.get("hints")
    if not isinstance(hints, list):
        raise AMRGError("amrg decomposer context hints must be a list")
    if len(hints) > AMRG_DECOMPOSER_CONTEXT_MAX_HINTS:
        raise AMRGError("amrg decomposer context hint cap exceeded")
    counts = Counter(hint.get("hint_category") for hint in hints if isinstance(hint, dict))
    if counts["deterministic_relationship_hint"] > AMRG_DECOMPOSER_DETERMINISTIC_HINT_CAP:
        raise AMRGError("deterministic AMRG hint cap exceeded")
    if counts["vector_neighbor_weak_context_hint"] > AMRG_DECOMPOSER_VECTOR_HINT_CAP:
        raise AMRGError("vector AMRG hint cap exceeded")
    if counts["strict_precedence_anchor_hint"] > AMRG_DECOMPOSER_ANCHOR_HINT_CAP:
        raise AMRGError("strict-precedence AMRG hint cap exceeded")
    for idx, hint in enumerate(hints):
        path = f"amrg_decomposer_context.hints[{idx}]"
        for field in (
            "hint_ref",
            "source_market_ref",
            "relation_type",
            "effect_status",
            "allowed_use",
            "prohibited_use",
            "freshness_status",
            "candidate_leaf_relevance",
        ):
            if field not in hint:
                raise AMRGError(f"{path}.{field} is required")
        if "qdt_selection" not in hint["prohibited_use"]:
            raise AMRGError(f"{path} must prohibit qdt_selection")
        if "qdt_repair" not in hint["prohibited_use"]:
            raise AMRGError(f"{path} must prohibit qdt_repair")
        if "probability_authority" not in hint["prohibited_use"]:
            raise AMRGError(f"{path} must prohibit probability_authority")
        if "scae_delta" not in hint["prohibited_use"]:
            raise AMRGError(f"{path} must prohibit scae_delta")
        if hint.get("hint_category") in {"weak_context_hint", "vector_neighbor_weak_context_hint"}:
            if set(hint["allowed_use"]) != {"decomposition_context_hint"}:
                raise AMRGError(f"{path} weak hints may only allow decomposition context use")
        if hint.get("hint_category") == "strict_precedence_anchor_hint":
            if "qdt_anchor_dependency_hint" not in hint["allowed_use"]:
                raise AMRGError(f"{path} strict-precedence hints must allow qdt anchor dependency hints")
        ensure_no_raw_amrg_fields(hint, path)
    metadata = section.get("operator_metadata")
    if not isinstance(metadata, dict):
        raise AMRGError("amrg decomposer context operator_metadata is required")
    for forbidden in ("probability_authority", "qdt_selection", "qdt_repair", "scae_delta"):
        if forbidden not in metadata.get("forbidden_qdt_uses", []):
            raise AMRGError(f"amrg decomposer operator metadata must forbid {forbidden}")
    ensure_no_raw_amrg_fields(section, "amrg_decomposer_context")


def attach_amrg_decomposer_context(context: dict[str, Any]) -> dict[str, Any]:
    section = build_amrg_decomposer_context(context)
    attached = {**context, "amrg_decomposer_context": section}
    if attached.get("artifact_type") == "no_related_context_waiver":
        validate_no_related_context_waiver(attached)
    else:
        validate_related_live_market_context(attached)
    return attached


def validate_relationship_type_list(types: list[str]) -> list[str]:
    if not isinstance(types, list):
        raise AMRGError("relationship_types must be a list")
    unknown = sorted(set(types) - RELATIONSHIP_TYPES)
    if unknown:
        raise AMRGError("unknown relationship types: " + ", ".join(unknown))
    return sorted(set(types))


def relationship_types_for_candidate(candidate: dict[str, Any]) -> list[str]:
    validate_amrg_candidate(candidate)
    types: set[str] = set()
    sources = set(candidate.get("candidate_sources") or [candidate["candidate_source"]])
    reasons = set(candidate.get("reason_codes") or [])
    if "platform_family_context" in sources or "family_sibling_context_only" in reasons:
        types.add("same_platform_family_sibling")
    if "entity_match" in sources:
        types.add("shared_named_entity")
    if "contract_source_match" in sources:
        types.add("shared_contract_source")
    if "shared_resolution_source" in sources:
        types.add("shared_resolution_source")
    if "current_exposure" in sources:
        types.add("current_exposure_context")
    if "generic_theme_match" in sources:
        types.add("generic_theme")
    if AMRG_VECTOR_CANDIDATE_SOURCE in sources or candidate.get("vector_only"):
        types.add("vector_similarity_neighbor")
    if not types:
        types.add("generic_theme")
    return validate_relationship_type_list(sorted(types))


def timing_alignment_for_candidate(
    evidence_packet: dict[str, Any],
    candidate: dict[str, Any],
    *,
    max_snapshot_skew_seconds: int = 900,
) -> dict[str, Any]:
    validate_evidence_packet_v2(evidence_packet)
    validate_amrg_candidate(candidate)
    forecast_at = parse_timestamp(evidence_packet["forecast_timestamp"], "forecast_timestamp")
    selected_snapshot = evidence_packet.get("prior_context_seed", {}).get("market_snapshot_timestamp")
    related_snapshot = (
        candidate.get("timing_inputs", {}).get("related_market_snapshot_as_of")
        or candidate.get("timing_inputs", {}).get("source_cutoff_timestamp")
    )
    basis_refs = [
        {
            "source": "evidence_packet.prior_context_seed",
            "ref_id": str(evidence_packet.get("prior_context_seed", {}).get("market_snapshot_id")),
            "timestamp": selected_snapshot,
        },
        {
            "source": "amrg_candidate.timing_inputs",
            "ref_id": candidate["candidate_id"],
            "timestamp": related_snapshot,
        },
    ]
    if not related_snapshot:
        status = "missing_related_snapshot"
        skew = None
    else:
        related_at = parse_timestamp(related_snapshot, "related_market_snapshot_as_of")
        if related_at > forecast_at:
            status = "lookahead_blocked"
            skew = None
        elif not selected_snapshot:
            status = "skew_warning"
            skew = None
        else:
            selected_at = parse_timestamp(selected_snapshot, "selected_market_snapshot_as_of")
            if selected_at > forecast_at:
                status = "lookahead_blocked"
                skew = None
            else:
                skew = int(abs((selected_at - related_at).total_seconds()))
                status = "aligned" if skew <= max_snapshot_skew_seconds else "skew_exceeds_policy"
    return {
        "timing_alignment_status": status,
        "timing_alignment_basis_refs": basis_refs,
        "selected_market_snapshot_as_of": selected_snapshot,
        "related_market_snapshot_as_of": related_snapshot,
        "max_snapshot_skew_seconds": max_snapshot_skew_seconds,
        "snapshot_skew_seconds": skew,
    }


def status_for_typed_candidate(candidate: dict[str, Any], relationship_types: list[str], timing_status: str) -> str:
    if timing_status in {"lookahead_blocked", "skew_exceeds_policy", "missing_related_snapshot"}:
        return "timing_mismatch_weak_context_only"
    if candidate.get("vector_only") or relationship_types == ["generic_theme"] or relationship_types == ["vector_similarity_neighbor"]:
        return WEAK_CONTEXT_ONLY
    if timing_status == "aligned":
        return "deterministic_context_candidate"
    return WEAK_CONTEXT_ONLY


def graph_safety_for_edge(edge: dict[str, Any]) -> dict[str, Any]:
    status = edge.get("relationship_status")
    timing = edge.get("timing_alignment_status")
    if status == "validated_strict_precedence_anchor":
        graph_status = "acyclic_validated"
        cycle_status = "acyclic"
        causal_edge_role = "validated_strict_precedence_anchor"
        downgrade_applied = False
        downgrade_reasons = []
    elif status == "strict_precedence_anchor_candidate" and timing == "aligned":
        graph_status = "acyclic_placeholder"
        cycle_status = "anchor_validation_required"
        causal_edge_role = "causal_upstream_candidate"
        downgrade_applied = False
        downgrade_reasons = []
    elif status == "deterministic_context_candidate" and timing == "aligned":
        graph_status = "acyclic_placeholder"
        cycle_status = "not_evaluated_phase7_no_anchor_authority"
        causal_edge_role = "not_validated_anchor"
        downgrade_applied = False
        downgrade_reasons: list[str] = []
    else:
        graph_status = "not_applicable_weak_context"
        cycle_status = "not_applicable_weak_context"
        causal_edge_role = "not_validated_anchor"
        downgrade_applied = status != WEAK_CONTEXT_ONLY
        downgrade_reasons = ["weak_context_or_timing_mismatch"]
    return {
        "graph_safety_slice_id": stable_id("amrg-graph-safety", edge["edge_id"]),
        "graph_component_id": stable_id("amrg-graph-component", edge["edge_id"]),
        "causal_graph_status": graph_status,
        "cycle_status": cycle_status,
        "causal_edge_role": causal_edge_role,
        "event_time_ordering_basis": edge.get("timing_alignment_status"),
        "strict_precedence_proof_ref": edge.get("strict_precedence_proof_ref"),
        "max_refresh_hop_depth": 0,
        "refresh_generation_id": stable_id("amrg-refresh-generation", edge["edge_id"], "phase7"),
        "downgrade_applied": downgrade_applied,
        "downgrade_reason_codes": downgrade_reasons,
    }


def normalize_qdt_anchor_contracts(qdt_contract: Any) -> list[dict[str, Any]]:
    if qdt_contract is None:
        return []
    if isinstance(qdt_contract, dict):
        for key in ("amrg_anchor_dependency_contracts", "anchor_dependency_contracts", "contracts"):
            if key in qdt_contract:
                return normalize_qdt_anchor_contracts(qdt_contract[key])
        if "anchor_dependency_contract_id" in qdt_contract:
            ensure_no_raw_amrg_fields(qdt_contract, "qdt_anchor_contract")
            return [dict(qdt_contract)]
        raise AMRGError("qdt anchor contract input must be a contract, contract list, or QDT artifact")
    if isinstance(qdt_contract, (list, tuple)):
        contracts: list[dict[str, Any]] = []
        for contract in qdt_contract:
            if not isinstance(contract, dict):
                raise AMRGError("qdt anchor contracts must be objects")
            ensure_no_raw_amrg_fields(contract, "qdt_anchor_contract")
            contracts.append(dict(contract))
        return contracts
    raise AMRGError("qdt anchor contract input must be an object or list")


def relationship_types_for_edge(edge: dict[str, Any]) -> list[str]:
    if isinstance(edge.get("relationship_types"), list):
        return validate_relationship_type_list(edge["relationship_types"])
    if edge.get("relationship_type"):
        return validate_relationship_type_list([str(edge["relationship_type"])])
    return []


def matching_qdt_anchor_contract(edge: dict[str, Any], qdt_contract: Any) -> tuple[dict[str, Any] | None, list[str]]:
    contracts = normalize_qdt_anchor_contracts(qdt_contract)
    if not contracts:
        return None, ["missing_qdt_anchor_dependency_contract"]
    edge_id = edge.get("edge_id")
    matches = [contract for contract in contracts if contract.get("edge_id") == edge_id]
    if not matches:
        return None, ["missing_qdt_anchor_dependency_contract_for_edge"]
    contract = matches[0]
    reasons: list[str] = []
    if contract.get("schema_version") != QDT_ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION:
        reasons.append("qdt_anchor_dependency_contract_schema_invalid")
    if contract.get("anchor_mode") not in QDT_ANCHOR_MODES_REQUIRING_CONDITION_SCOPE:
        reasons.append("qdt_anchor_dependency_contract_not_condition_scoped")
    condition_scoped_leaf_ids = contract.get("condition_scoped_leaf_ids")
    if not isinstance(condition_scoped_leaf_ids, list) or not condition_scoped_leaf_ids:
        reasons.append("missing_qdt_condition_scoped_leaf_support")
    return contract, reasons


def first_present(edge: dict[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        value = edge.get(field)
        if value not in (None, ""):
            return value
    return None


def strict_event_time_or_contractual_precedence(edge: dict[str, Any]) -> tuple[bool, str | None, str | None, list[str]]:
    proof_ref = first_present(
        edge,
        (
            "strict_precedence_proof_ref",
            "contractual_precedence_proof_ref",
            "event_time_ordering_proof_ref",
        ),
    )
    basis = edge.get("strict_precedence_basis") or edge.get("event_time_ordering_basis")
    contractual_basis = basis in {"contractual", "contractual_precedence", "strict_contractual_precedence"}
    if edge.get("contractual_precedence") is True or contractual_basis:
        if proof_ref:
            return True, "contractual_precedence", str(proof_ref), []
        return False, None, None, ["contractual_precedence_missing_proof_ref"]

    upstream_time = first_present(
        edge,
        (
            "upstream_event_time",
            "related_event_time",
            "upstream_resolve_timestamp",
            "related_market_event_time",
        ),
    )
    target_time = first_present(
        edge,
        (
            "target_event_time",
            "selected_event_time",
            "target_resolve_timestamp",
            "selected_market_event_time",
        ),
    )
    if upstream_time and target_time:
        try:
            upstream_at = parse_timestamp(str(upstream_time), "upstream_event_time")
            target_at = parse_timestamp(str(target_time), "target_event_time")
        except Exception:
            return False, None, None, ["invalid_strict_precedence_event_time"]
        if upstream_at < target_at:
            return True, "strict_event_time_precedence", str(proof_ref) if proof_ref else None, []
        if upstream_at == target_at:
            return False, None, None, ["concurrent_event_time"]
        return False, None, None, ["upstream_event_not_before_target"]

    if basis in {"strict_event_time_precedence", "event_time_precedence"} and proof_ref:
        return True, "strict_event_time_precedence", str(proof_ref), []
    return False, None, None, ["strict_precedence_not_proven"]


def graph_edge_nodes(edge: Any) -> tuple[str | None, str | None]:
    if isinstance(edge, (list, tuple)) and len(edge) == 2:
        return str(edge[0]), str(edge[1])
    if not isinstance(edge, dict):
        return None, None
    upstream = first_present(
        edge,
        (
            "upstream_market_id",
            "related_market_id",
            "source_market_id",
            "from_market_id",
            "market_id",
        ),
    )
    target = first_present(
        edge,
        (
            "target_market_id",
            "selected_market_id",
            "to_market_id",
            "downstream_market_id",
        ),
    )
    if upstream is None or target is None:
        return None, None
    return str(upstream), str(target)


def path_exists(adjacency: dict[str, set[str]], start: str, target: str) -> bool:
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(sorted(adjacency.get(node, set()) - seen))
    return False


def graph_is_acyclic_for_edge(edge: dict[str, Any], graph_edges: Any = None) -> tuple[bool, list[str]]:
    if edge.get("causal_graph_status") == "blocked_cycle_or_concurrent_timing":
        return False, ["causal_graph_cycle_rejected"]
    if str(edge.get("cycle_status", "")).lower() in {"cycle_detected", "cyclic", "cycle_rejected"}:
        return False, ["causal_graph_cycle_rejected"]

    upstream, target = graph_edge_nodes(edge)
    if not upstream or not target:
        return False, ["causal_graph_nodes_missing"]
    if upstream == target:
        return False, ["reflexive_causal_edge_rejected"]

    adjacency: dict[str, set[str]] = {}
    for existing in graph_edges or []:
        existing_upstream, existing_target = graph_edge_nodes(existing)
        if not existing_upstream or not existing_target:
            continue
        if isinstance(existing, dict) and existing.get("edge_id") == edge.get("edge_id"):
            continue
        adjacency.setdefault(existing_upstream, set()).add(existing_target)
    if path_exists(adjacency, target, upstream):
        return False, ["causal_graph_cycle_rejected"]
    return True, []


def validate_prior_anchor_slice(slice_row: dict[str, Any]) -> None:
    if slice_row.get("validation_status") not in ANCHOR_VALIDATION_STATUSES:
        raise AMRGError("prior anchor validation_status is unknown")
    if slice_row.get("raw_upstream_probability") is not None:
        raise AMRGError("AMRG anchor validation must not write raw_upstream_probability")
    if slice_row.get("adjusted_upstream_probability") is not None:
        raise AMRGError("AMRG anchor validation must not write adjusted_upstream_probability")
    if slice_row.get("upstream_probability_as_of") is not None:
        raise AMRGError("AMRG anchor validation must not write upstream_probability_as_of")
    ensure_no_raw_amrg_fields(slice_row.get("metadata") or {}, "prior_anchor_slice.metadata")


def make_prior_anchor_slice(
    edge: dict[str, Any],
    *,
    qdt_contract: dict[str, Any] | None,
    validation_status: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    contract_id = (
        qdt_contract.get("anchor_dependency_contract_id")
        if qdt_contract and qdt_contract.get("anchor_dependency_contract_id")
        else stable_id("missing-anchor-contract", edge["edge_id"])
    )
    slice_row = {
        "prior_anchor_slice_id": stable_id(
            "amrg-prior-anchor",
            edge["edge_id"],
            contract_id,
            validation_status,
            sorted(set(reason_codes)),
        ),
        "case_id": edge.get("case_id") or "unknown_case",
        "market_id": str(edge.get("selected_market_id") or edge.get("target_market_id") or edge.get("market_id")),
        "dispatch_id": edge.get("dispatch_id") or "unknown_dispatch",
        "edge_id": edge["edge_id"],
        "upstream_market_id": str(edge.get("upstream_market_id") or edge.get("related_market_id") or edge.get("market_id")),
        "upstream_probability_source": "not_written_by_amrg_anchor_validation",
        "raw_upstream_probability": None,
        "adjusted_upstream_probability": None,
        "upstream_probability_as_of": None,
        "allowed_use": "condition_scoped_anchor_validation_input" if validation_status == "validated" else "validation_audit_only",
        "conditional_model": "qdt_condition_scoped_leaves_required" if validation_status == "validated" else None,
        "upstream_prior_reliability_context": {
            "authority": "none_no_probability_written_by_amrg",
            "qdt_anchor_contract_schema_version": qdt_contract.get("schema_version") if qdt_contract else None,
        },
        "dependence_adjustment": {"authority": "none_no_scae_delta_written_by_amrg"},
        "double_counting_risk": "not_independent_evidence_anchor_only",
        "not_independent_evidence": True,
        "conditional_branch_group_id": qdt_contract.get("conditional_branch_group_id") if qdt_contract else None,
        "anchor_dependency_contract_id": contract_id,
        "graph_safety_slice_id": edge.get("graph_safety_slice_id"),
        "validation_status": validation_status,
        "reason_codes": sorted(set(reason_codes)),
        "metadata": {
            "condition_scoped_leaf_ids": qdt_contract.get("condition_scoped_leaf_ids", []) if qdt_contract else [],
            "no_probability_fields_written": True,
            "no_scae_delta_written": True,
            "qdt_contract_read_only": True,
        },
    }
    validate_prior_anchor_slice(slice_row)
    return slice_row


def reject_strict_precedence_anchor_edge(edge: dict[str, Any], reason_codes: list[str]) -> dict[str, Any]:
    timing_or_precedence_reasons = {
        "timing_alignment_not_aligned",
        "concurrent_event_time",
        "upstream_event_not_before_target",
        "strict_precedence_not_proven",
        "invalid_strict_precedence_event_time",
    }
    status = "timing_mismatch_weak_context_only" if timing_or_precedence_reasons & set(reason_codes) else WEAK_CONTEXT_ONLY
    updated = {
        **edge,
        "relationship_status": status,
        "allowed_effects": AMRG_ALLOWED_EFFECTS_BY_STATUS[status],
        "forbidden_effects": forbidden_effects_for_status(status),
        "anchor_validation_status": "rejected",
        "anchor_validation_reason_codes": sorted(set(reason_codes)),
        "downgrade_applied": True,
        "downgrade_reason_codes": sorted(set(edge.get("downgrade_reason_codes", []) + reason_codes)),
        "causal_edge_role": "rejected_strict_precedence_anchor",
    }
    if {"causal_graph_cycle_rejected", "reflexive_causal_edge_rejected", "concurrent_event_time"} & set(reason_codes):
        updated["causal_graph_status"] = "blocked_cycle_or_concurrent_timing"
        updated["cycle_status"] = "cycle_or_concurrent_rejected"
    else:
        updated.update(graph_safety_for_edge(updated))
        updated["anchor_validation_status"] = "rejected"
        updated["anchor_validation_reason_codes"] = sorted(set(reason_codes))
        updated["downgrade_applied"] = True
        updated["downgrade_reason_codes"] = sorted(set(edge.get("downgrade_reason_codes", []) + reason_codes))
        updated["causal_edge_role"] = "rejected_strict_precedence_anchor"
    validate_relationship_edge(updated)
    return updated


def validate_strict_precedence_anchor(
    edge: dict[str, Any],
    qdt_contract: Any,
    *,
    graph_edges: Any = None,
) -> dict[str, Any]:
    if not isinstance(edge, dict):
        raise AMRGError("edge must be an object")
    if "edge_id" not in edge:
        raise AMRGError("edge.edge_id is required")

    reasons: list[str] = []
    if edge.get("relationship_status") not in STRICT_PRECEDENCE_ANCHOR_STATUSES:
        reasons.append("edge_not_strict_precedence_anchor_candidate")
    if "causal_upstream" not in relationship_types_for_edge(edge):
        reasons.append("missing_causal_upstream_relationship")
    if edge.get("timing_alignment_status") != "aligned":
        reasons.append("timing_alignment_not_aligned")

    precedence_ok, precedence_basis, proof_ref, precedence_reasons = strict_event_time_or_contractual_precedence(edge)
    if not precedence_ok:
        reasons.extend(precedence_reasons)

    graph_ok, graph_reasons = graph_is_acyclic_for_edge(edge, graph_edges)
    if not graph_ok:
        reasons.extend(graph_reasons)

    contract, contract_reasons = matching_qdt_anchor_contract(edge, qdt_contract)
    reasons.extend(contract_reasons)

    if reasons:
        rejected = reject_strict_precedence_anchor_edge(edge, reasons)
        slice_row = make_prior_anchor_slice(
            rejected,
            qdt_contract=contract,
            validation_status="rejected",
            reason_codes=reasons,
        )
        return {"edge": rejected, "prior_anchor_slice": slice_row}

    validated = {
        **edge,
        "relationship_status": "validated_strict_precedence_anchor",
        "relationship_types": validate_relationship_type_list(relationship_types_for_edge(edge)),
        "allowed_effects": AMRG_ALLOWED_EFFECTS_BY_STATUS["validated_strict_precedence_anchor"],
        "forbidden_effects": forbidden_effects_for_status("validated_strict_precedence_anchor"),
        "causal_graph_status": "acyclic_validated",
        "cycle_status": "acyclic",
        "causal_edge_role": "validated_strict_precedence_anchor",
        "event_time_ordering_basis": precedence_basis,
        "strict_precedence_proof_ref": proof_ref,
        "anchor_validation_status": "validated",
        "anchor_validation_reason_codes": ["strict_precedence_anchor_validated"],
        "anchor_dependency_contract_id": contract["anchor_dependency_contract_id"],
        "conditional_branch_group_id": contract.get("conditional_branch_group_id"),
        "condition_scoped_leaf_ids": list(contract.get("condition_scoped_leaf_ids") or []),
        "downgrade_applied": False,
        "downgrade_reason_codes": [],
    }
    validated.update(
        {
            "graph_safety_slice_id": edge.get("graph_safety_slice_id")
            or stable_id("amrg-graph-safety", edge["edge_id"]),
            "graph_component_id": edge.get("graph_component_id")
            or stable_id("amrg-graph-component", edge["edge_id"]),
            "max_refresh_hop_depth": edge.get("max_refresh_hop_depth", 0),
            "refresh_generation_id": edge.get("refresh_generation_id")
            or stable_id("amrg-refresh-generation", edge["edge_id"], "anchor-validation"),
        }
    )
    validate_relationship_edge(validated)
    slice_row = make_prior_anchor_slice(
        validated,
        qdt_contract=contract,
        validation_status="validated",
        reason_codes=["strict_precedence_anchor_validated"],
    )
    return {"edge": validated, "prior_anchor_slice": slice_row}


def context_edges_requiring_anchor_validation(context: dict[str, Any], qdt_anchor_contracts: Any) -> set[str]:
    edge_ids = {
        edge["edge_id"]
        for edge in context.get("relationship_edges", [])
        if edge.get("relationship_status") in STRICT_PRECEDENCE_ANCHOR_STATUSES
    }
    for contract in normalize_qdt_anchor_contracts(qdt_anchor_contracts):
        if contract.get("edge_id"):
            edge_ids.add(contract["edge_id"])
    return edge_ids


def apply_strict_precedence_anchor_validation(
    context: dict[str, Any],
    *,
    qdt_anchor_contracts: Any = None,
    graph_edges: Any = None,
) -> dict[str, Any]:
    validate_related_live_market_context(context)
    if context["artifact_type"] != "related_live_market_context":
        return dict(context)
    edge_ids = context_edges_requiring_anchor_validation(context, qdt_anchor_contracts)
    if not edge_ids:
        return attach_amrg_decomposer_context(
            {**context, "prior_anchor_slices": list(context.get("prior_anchor_slices", []))}
        )

    validated_edges: list[dict[str, Any]] = []
    prior_anchor_slices: list[dict[str, Any]] = []
    for edge in context["relationship_edges"]:
        if edge["edge_id"] not in edge_ids:
            validated_edges.append(edge)
            continue
        edge_context = {
            "case_id": context["case_id"],
            "dispatch_id": context["dispatch_id"],
            "selected_market_id": str(context["market_id"]),
            "target_market_id": str(context["market_id"]),
            "related_market_id": str(edge.get("market_id")),
            "candidate_set_id": context["candidate_set_id"],
            **edge,
        }
        result = validate_strict_precedence_anchor(
            edge_context,
            qdt_anchor_contracts,
            graph_edges=graph_edges,
        )
        validated_edges.append(result["edge"])
        prior_anchor_slices.append(result["prior_anchor_slice"])

    validated_context = {
        **context,
        "relationship_edges": validated_edges,
        "prior_anchor_slices": prior_anchor_slices,
    }
    validate_related_live_market_context(validated_context)
    return attach_amrg_decomposer_context(validated_context)


def normalize_refresh_policy(context: dict[str, Any], refresh_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = dict(refresh_policy or {})
    refresh_as_of = policy.get("refresh_as_of_timestamp") or context["forecast_timestamp"]
    ttl_seconds = int(policy.get("ttl_seconds", policy.get("weak_relationship_context_ttl_seconds", 24 * 60 * 60)))
    if ttl_seconds < 0:
        raise AMRGError("refresh ttl_seconds must be non-negative")
    refresh_budget = int(policy.get("refresh_budget", DEFAULT_AMRG_CANDIDATE_CAP))
    if refresh_budget < 0:
        raise AMRGError("refresh_budget must be non-negative")
    return {
        "schema_version": AMRG_REFRESH_POLICY_SCHEMA_VERSION,
        "refresh_as_of_timestamp": parse_timestamp(refresh_as_of, "refresh_as_of_timestamp").isoformat(),
        "ttl_seconds": ttl_seconds,
        "market_descriptor_ttl_seconds": int(policy.get("market_descriptor_ttl_seconds", 60 * 60)),
        "weak_relationship_context_ttl_seconds": int(policy.get("weak_relationship_context_ttl_seconds", 24 * 60 * 60)),
        "vector_index_snapshot_ttl_seconds": int(policy.get("vector_index_snapshot_ttl_seconds", 24 * 60 * 60)),
        "strict_precedence_anchor_validation_ttl_seconds": int(
            policy.get("strict_precedence_anchor_validation_ttl_seconds", 6 * 60 * 60)
        ),
        "model_assist_classification_ttl_seconds": int(policy.get("model_assist_classification_ttl_seconds", 24 * 60 * 60)),
        "refresh_budget": refresh_budget,
        "max_snapshot_skew_seconds": int(policy.get("max_snapshot_skew_seconds", 900)),
    }


def edge_has_promoted_effect(edge: dict[str, Any]) -> bool:
    return any(effect not in AMRG_WEAK_ALLOWED_EFFECTS for effect in edge.get("allowed_effects", []))


def edge_snapshot_timestamp(edge: dict[str, Any]) -> str | None:
    return edge.get("related_market_snapshot_as_of") or edge.get("selected_market_snapshot_as_of")


def next_refresh_after_for_edge(edge: dict[str, Any], ttl_seconds: int) -> str | None:
    snapshot = edge_snapshot_timestamp(edge)
    if not snapshot:
        return None
    return (parse_timestamp(snapshot, "related_market_snapshot_as_of") + timedelta(seconds=ttl_seconds)).isoformat()


def edge_is_stale(edge: dict[str, Any], *, refresh_as_of_timestamp: str, ttl_seconds: int) -> bool:
    snapshot = edge_snapshot_timestamp(edge)
    if not snapshot:
        return True
    snapshot_at = parse_timestamp(snapshot, "related_market_snapshot_as_of")
    refresh_as_of = parse_timestamp(refresh_as_of_timestamp, "refresh_as_of_timestamp")
    return refresh_as_of - snapshot_at > timedelta(seconds=ttl_seconds)


def normalize_refresh_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    if not isinstance(result, dict):
        raise AMRGError("refresh result must be an object")
    ensure_no_raw_amrg_fields(result, "refresh_result")
    reason_codes = normalize_list(result.get("reason_codes") or result.get("reason_code"))
    normalized = dict(result)
    normalized["ok"] = bool(result.get("ok"))
    normalized["reason_codes"] = sorted(set(reason_codes))
    return normalized


def normalize_refresh_results(refresh_results: Any) -> dict[str, dict[str, Any]]:
    if refresh_results is None:
        return {}
    if isinstance(refresh_results, list):
        items = refresh_results
    elif isinstance(refresh_results, dict) and ("ok" in refresh_results or "edge_id" in refresh_results):
        items = [refresh_results]
    elif isinstance(refresh_results, dict):
        items = []
        for key, value in refresh_results.items():
            if not isinstance(value, dict):
                raise AMRGError("refresh result mapping values must be objects")
            item = dict(value)
            item.setdefault("edge_id", key)
            items.append(item)
    else:
        raise AMRGError("refresh_results must be a mapping or list")

    normalized: dict[str, dict[str, Any]] = {}
    for item in items:
        result = normalize_refresh_result(item)
        for key in (
            result.get("edge_id"),
            result.get("candidate_id"),
            result.get("market_id"),
            result.get("related_market_id"),
        ):
            if key is not None:
                normalized[str(key)] = result
    return normalized


def explicit_refresh_result_for_edge(
    edge: dict[str, Any],
    candidate: dict[str, Any],
    refresh_results: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key in (
        edge.get("edge_id"),
        edge.get("candidate_id"),
        candidate.get("candidate_id"),
        candidate.get("market_id"),
        candidate.get("external_market_id"),
    ):
        if key is not None and str(key) in refresh_results:
            return refresh_results[str(key)]
    return None


def active_index_refresh_result_for_candidate(
    candidate: dict[str, Any],
    active_market_index: list[dict[str, Any] | Any] | None,
    *,
    refresh_as_of_timestamp: str,
) -> dict[str, Any] | None:
    if active_market_index is None:
        return None
    candidate_ids = {str(value) for value in (candidate.get("market_id"), candidate.get("external_market_id")) if value is not None}
    for row in active_market_index:
        market = row_to_dict(row)
        if not (market_identity_strings(market) & candidate_ids):
            continue
        try:
            active_safe = active_safe_market_fields(market, refresh_as_of_timestamp)
        except AMRGError as exc:
            return {
                "ok": False,
                "market_id": candidate.get("market_id"),
                "reason_codes": [classify_active_safe_exclusion(exc)],
                "material_change": False,
            }
        if is_before_or_at_cutoff(active_safe.get("close_timestamp"), refresh_as_of_timestamp, "candidate_close_timestamp"):
            return {
                "ok": False,
                "market_id": candidate.get("market_id"),
                "reason_codes": ["past_market"],
                "material_change": False,
            }
        if is_before_or_at_cutoff(active_safe.get("resolve_timestamp"), refresh_as_of_timestamp, "candidate_resolve_timestamp"):
            return {
                "ok": False,
                "market_id": candidate.get("market_id"),
                "reason_codes": ["past_market"],
                "material_change": False,
            }
        active_safe_hash = prefixed_sha256(canonical_json(active_safe))
        return {
            "ok": True,
            "market_id": candidate.get("market_id"),
            "related_market_snapshot_as_of": refresh_as_of_timestamp,
            "active_safe_fields_hash": active_safe_hash,
            "material_change": active_safe_hash != candidate.get("active_safe_fields_hash"),
            "reason_codes": ["active_market_index_refresh"],
        }
    return {
        "ok": False,
        "market_id": candidate.get("market_id"),
        "reason_codes": ["related_market_not_found"],
        "material_change": False,
    }


def refresh_result_for_edge(
    edge: dict[str, Any],
    candidate: dict[str, Any],
    *,
    refresh_results: dict[str, dict[str, Any]],
    active_market_index: list[dict[str, Any] | Any] | None,
    refresh_as_of_timestamp: str,
) -> dict[str, Any] | None:
    explicit = explicit_refresh_result_for_edge(edge, candidate, refresh_results)
    if explicit is not None:
        return explicit
    return normalize_refresh_result(
        active_index_refresh_result_for_candidate(
            candidate,
            active_market_index,
            refresh_as_of_timestamp=refresh_as_of_timestamp,
        )
    )


def refreshed_timing_for_edge(edge: dict[str, Any], result: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    selected_snapshot = result.get("selected_market_snapshot_as_of", edge.get("selected_market_snapshot_as_of"))
    related_snapshot = (
        result.get("related_market_snapshot_as_of")
        or result.get("snapshot_as_of")
        or result.get("refreshed_snapshot_as_of")
        or edge.get("related_market_snapshot_as_of")
    )
    refresh_as_of = parse_timestamp(policy["refresh_as_of_timestamp"], "refresh_as_of_timestamp")
    if not related_snapshot:
        status = "missing_related_snapshot"
        skew = None
    else:
        related_at = parse_timestamp(related_snapshot, "related_market_snapshot_as_of")
        if related_at > refresh_as_of:
            status = "lookahead_blocked"
            skew = None
        elif selected_snapshot:
            selected_at = parse_timestamp(selected_snapshot, "selected_market_snapshot_as_of")
            if selected_at > refresh_as_of:
                status = "lookahead_blocked"
                skew = None
            else:
                skew = int(abs((selected_at - related_at).total_seconds()))
                status = "aligned" if skew <= policy["max_snapshot_skew_seconds"] else "skew_exceeds_policy"
        else:
            status = "skew_warning"
            skew = None
    return {
        "timing_alignment_status": status,
        "selected_market_snapshot_as_of": selected_snapshot,
        "related_market_snapshot_as_of": related_snapshot,
        "max_snapshot_skew_seconds": policy["max_snapshot_skew_seconds"],
        "snapshot_skew_seconds": skew,
    }


def refresh_lifecycle_state(
    *,
    edge: dict[str, Any],
    refresh_status: str,
    reason_codes: list[str],
    policy: dict[str, Any],
    stale_before_refresh: bool,
    material_change: bool = False,
    refresh_attempted: bool = False,
    refresh_budget_consumed: int = 0,
    stale_effect_downgrade_applied: bool = False,
    deterministic_validation_status: str | None = None,
    next_refresh_after: str | None = None,
) -> dict[str, Any]:
    if refresh_status not in REFRESH_STATUSES:
        raise AMRGError("unknown refresh lifecycle status")
    generation_id = stable_id(
        "amrg-refresh-generation",
        edge["edge_id"],
        policy["refresh_as_of_timestamp"],
        refresh_status,
        sorted(set(reason_codes)),
    )
    state = {
        "schema_version": AMRG_REFRESH_LIFECYCLE_SCHEMA_VERSION,
        "refresh_status": refresh_status,
        "refresh_reason_codes": sorted(set(reason_codes)),
        "refresh_generation_id": generation_id,
        "refresh_as_of_timestamp": policy["refresh_as_of_timestamp"],
        "ttl_seconds": policy["ttl_seconds"],
        "stale_before_refresh": stale_before_refresh,
        "material_change_detected": material_change,
        "refresh_attempted": refresh_attempted,
        "refresh_budget_consumed": refresh_budget_consumed,
        "stale_effect_downgrade_applied": stale_effect_downgrade_applied,
        "deterministic_validation_status": deterministic_validation_status,
        "next_refresh_after": next_refresh_after,
    }
    ensure_no_raw_amrg_fields(state, "refresh_lifecycle_state")
    return state


def apply_refresh_state_to_edge(edge: dict[str, Any], state: dict[str, Any], *, downgrade_reasons: list[str] | None = None) -> dict[str, Any]:
    updated = dict(edge)
    if state["stale_effect_downgrade_applied"]:
        updated["relationship_status"] = WEAK_CONTEXT_ONLY
        updated["allowed_effects"] = AMRG_ALLOWED_EFFECTS_BY_STATUS[WEAK_CONTEXT_ONLY]
        updated["forbidden_effects"] = forbidden_effects_for_status(WEAK_CONTEXT_ONLY)
    updated["refresh_lifecycle_state"] = state
    updated["refresh_generation_id"] = state["refresh_generation_id"]
    updated.update(graph_safety_for_edge(updated))
    updated["refresh_generation_id"] = state["refresh_generation_id"]
    if state["stale_effect_downgrade_applied"]:
        updated["downgrade_applied"] = True
        updated["downgrade_reason_codes"] = sorted(set((downgrade_reasons or []) + state["refresh_reason_codes"]))
    validate_relationship_edge(updated)
    return updated


def downgrade_edge_for_refresh(
    edge: dict[str, Any],
    *,
    refresh_status: str,
    reason_codes: list[str],
    policy: dict[str, Any],
    stale_before_refresh: bool,
    material_change: bool = False,
    refresh_attempted: bool = False,
    refresh_budget_consumed: int = 0,
    deterministic_validation_status: str | None = None,
) -> dict[str, Any]:
    state = refresh_lifecycle_state(
        edge=edge,
        refresh_status=refresh_status,
        reason_codes=reason_codes,
        policy=policy,
        stale_before_refresh=stale_before_refresh,
        material_change=material_change,
        refresh_attempted=refresh_attempted,
        refresh_budget_consumed=refresh_budget_consumed,
        stale_effect_downgrade_applied=True,
        deterministic_validation_status=deterministic_validation_status,
        next_refresh_after=None,
    )
    return apply_refresh_state_to_edge(edge, state, downgrade_reasons=reason_codes)


def refresh_lifecycle_for_edge(
    edge: dict[str, Any],
    *,
    candidate: dict[str, Any],
    policy: dict[str, Any],
    refresh_results: dict[str, dict[str, Any]],
    active_market_index: list[dict[str, Any] | Any] | None,
    budget_remaining: int,
) -> tuple[dict[str, Any], int]:
    promoted = edge_has_promoted_effect(edge)
    stale = edge_is_stale(
        edge,
        refresh_as_of_timestamp=policy["refresh_as_of_timestamp"],
        ttl_seconds=policy["ttl_seconds"],
    )
    result = refresh_result_for_edge(
        edge,
        candidate,
        refresh_results=refresh_results,
        active_market_index=active_market_index,
        refresh_as_of_timestamp=policy["refresh_as_of_timestamp"],
    )
    material_change = bool(result and result.get("material_change"))

    if not promoted:
        state = refresh_lifecycle_state(
            edge=edge,
            refresh_status="not_requested_no_promoted_effect",
            reason_codes=["weak_or_advisory_or_vector_only_no_promoted_effect"],
            policy=policy,
            stale_before_refresh=stale,
            material_change=material_change,
            next_refresh_after=next_refresh_after_for_edge(edge, policy["ttl_seconds"]),
        )
        return apply_refresh_state_to_edge(edge, state), 0

    if not stale and not material_change:
        state = refresh_lifecycle_state(
            edge=edge,
            refresh_status="fresh_no_refresh_needed",
            reason_codes=["within_refresh_ttl"],
            policy=policy,
            stale_before_refresh=False,
            next_refresh_after=next_refresh_after_for_edge(edge, policy["ttl_seconds"]),
        )
        return apply_refresh_state_to_edge(edge, state), 0

    if budget_remaining <= 0:
        return (
            downgrade_edge_for_refresh(
                edge,
                refresh_status="refresh_budget_exhausted_downgraded_weak_context_only",
                reason_codes=["refresh_budget_exhausted"],
                policy=policy,
                stale_before_refresh=stale,
                material_change=material_change,
            ),
            0,
        )

    if result is None:
        return (
            downgrade_edge_for_refresh(
                edge,
                refresh_status="stale_promoted_effect_downgraded_weak_context_only",
                reason_codes=["stale_promoted_effect_without_refresh"],
                policy=policy,
                stale_before_refresh=stale,
            ),
            1,
        )

    result_reason_codes = normalize_list(result.get("reason_codes")) or (["refresh_ok"] if result.get("ok") else ["refresh_failed"])
    if not result.get("ok"):
        return (
            downgrade_edge_for_refresh(
                edge,
                refresh_status="refresh_failed_downgraded_weak_context_only",
                reason_codes=result_reason_codes,
                policy=policy,
                stale_before_refresh=stale,
                material_change=material_change,
                refresh_attempted=True,
                refresh_budget_consumed=1,
            ),
            1,
        )

    timing = refreshed_timing_for_edge(edge, result, policy)
    refreshed_edge = {
        **edge,
        **timing,
    }
    deterministic_validation_status = result.get("deterministic_validation_status") or result.get("deterministic_validation")
    if timing["timing_alignment_status"] != "aligned":
        return (
            downgrade_edge_for_refresh(
                refreshed_edge,
                refresh_status="refresh_failed_downgraded_weak_context_only",
                reason_codes=sorted(set(result_reason_codes + [timing["timing_alignment_status"]])),
                policy=policy,
                stale_before_refresh=stale,
                material_change=material_change,
                refresh_attempted=True,
                refresh_budget_consumed=1,
                deterministic_validation_status=deterministic_validation_status,
            ),
            1,
        )
    if material_change and deterministic_validation_status != "passed":
        return (
            downgrade_edge_for_refresh(
                refreshed_edge,
                refresh_status="material_change_downgraded_weak_context_only",
                reason_codes=sorted(set(result_reason_codes + ["material_change_requires_deterministic_revalidation"])),
                policy=policy,
                stale_before_refresh=stale,
                material_change=True,
                refresh_attempted=True,
                refresh_budget_consumed=1,
                deterministic_validation_status=deterministic_validation_status,
            ),
            1,
        )

    refresh_status = "material_change_revalidated" if material_change else "refresh_succeeded"
    success_reasons = sorted(set(result_reason_codes + ["deterministic_effect_retained_after_refresh"]))
    state = refresh_lifecycle_state(
        edge=refreshed_edge,
        refresh_status=refresh_status,
        reason_codes=success_reasons,
        policy=policy,
        stale_before_refresh=stale,
        material_change=material_change,
        refresh_attempted=True,
        refresh_budget_consumed=1,
        deterministic_validation_status=deterministic_validation_status,
        next_refresh_after=next_refresh_after_for_edge(refreshed_edge, policy["ttl_seconds"]),
    )
    return apply_refresh_state_to_edge(refreshed_edge, state), 1


def apply_refresh_lifecycle(
    context: dict[str, Any],
    *,
    refresh_policy: dict[str, Any] | None = None,
    refresh_results: Any = None,
    active_market_index: list[dict[str, Any] | Any] | None = None,
) -> dict[str, Any]:
    validate_related_live_market_context(context)
    if context["artifact_type"] != "related_live_market_context":
        return dict(context)
    policy = normalize_refresh_policy(context, refresh_policy)
    normalized_results = normalize_refresh_results(refresh_results)
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in context["candidates"]}
    budget_remaining = policy["refresh_budget"]
    refreshed_edges: list[dict[str, Any]] = []
    for edge in context["relationship_edges"]:
        refreshed_edge, consumed = refresh_lifecycle_for_edge(
            edge,
            candidate=candidates_by_id[edge["candidate_id"]],
            policy=policy,
            refresh_results=normalized_results,
            active_market_index=active_market_index,
            budget_remaining=budget_remaining,
        )
        budget_remaining -= consumed
        refreshed_edges.append(refreshed_edge)
    refreshed = {**context, "relationship_edges": refreshed_edges, "refresh_policy": policy}
    validate_related_live_market_context(refreshed)
    return refreshed


def type_and_validate_edge(
    edge: dict[str, Any],
    *,
    evidence_packet: dict[str, Any],
    candidate: dict[str, Any],
    model_assist_status: str = "not_requested",
) -> dict[str, Any]:
    explicit_relationship_types = edge.get("relationship_types")
    relationship_types = (
        validate_relationship_type_list(list(explicit_relationship_types))
        if explicit_relationship_types is not None
        else relationship_types_for_candidate(candidate)
    )
    timing = timing_alignment_for_candidate(evidence_packet, candidate)
    status = status_for_typed_candidate(candidate, relationship_types, timing["timing_alignment_status"])
    explicit_status = edge.get("relationship_status")
    if explicit_status == "strict_precedence_anchor_candidate":
        status = explicit_status if timing["timing_alignment_status"] == "aligned" else "timing_mismatch_weak_context_only"
    if model_assist_status == "advisory_validated" and status == WEAK_CONTEXT_ONLY:
        status = "model_assisted_weak_context_only"
    enriched = {
        **edge,
        "relationship_types": relationship_types,
        "relationship_status": status,
        "timing_alignment_status": timing["timing_alignment_status"],
        "timing_alignment_basis_refs": timing["timing_alignment_basis_refs"],
        "selected_market_snapshot_as_of": timing["selected_market_snapshot_as_of"],
        "related_market_snapshot_as_of": timing["related_market_snapshot_as_of"],
        "max_snapshot_skew_seconds": timing["max_snapshot_skew_seconds"],
        "snapshot_skew_seconds": timing["snapshot_skew_seconds"],
        "allowed_effects": AMRG_ALLOWED_EFFECTS_BY_STATUS[status],
        "forbidden_effects": forbidden_effects_for_status(status),
        "model_assist_status": model_assist_status,
        "model_assist_context": {},
    }
    enriched.update(graph_safety_for_edge(enriched))
    validate_relationship_edge(enriched)
    return enriched


def validate_relationship_edge(edge: dict[str, Any]) -> None:
    if edge.get("schema_version") != AMRG_WEAK_EDGE_SCHEMA_VERSION:
        raise AMRGError(f"edge schema_version must be {AMRG_WEAK_EDGE_SCHEMA_VERSION}")
    status = edge.get("relationship_status")
    if status not in RELATIONSHIP_STATUSES:
        raise AMRGError("relationship_status is unknown")
    if "probability_authority" not in edge.get("forbidden_effects", []):
        raise AMRGError("edge must forbid probability authority")
    if "scae_delta" not in edge.get("forbidden_effects", []):
        raise AMRGError("edge must forbid SCAE deltas")
    if "qdt_selection" not in edge.get("forbidden_effects", []):
        raise AMRGError("edge must forbid QDT selection")
    relationship_types = edge.get("relationship_types")
    if relationship_types is not None:
        validate_relationship_type_list(relationship_types)
    timing_status = edge.get("timing_alignment_status")
    if timing_status is not None and timing_status not in TIMING_ALIGNMENT_STATUSES:
        raise AMRGError("timing_alignment_status is unknown")
    if status == "deterministic_context_candidate":
        if timing_status != "aligned":
            raise AMRGError("deterministic_context_candidate requires aligned timing")
        if not relationship_types:
            raise AMRGError("deterministic_context_candidate requires relationship_types")
    if status == "validated_strict_precedence_anchor":
        if timing_status != "aligned":
            raise AMRGError("validated strict-precedence anchor requires aligned timing")
        if "causal_upstream" not in (relationship_types or []):
            raise AMRGError("validated strict-precedence anchor requires causal_upstream")
        if edge.get("anchor_validation_status") != "validated":
            raise AMRGError("validated strict-precedence anchor requires validated audit status")
        if "condition_scoped_anchor_validation_input" not in edge.get("allowed_effects", []):
            raise AMRGError("validated strict-precedence anchor requires condition-scoped allowed use")
    ensure_no_raw_amrg_fields(edge, "relationship_edge")


def enrich_related_live_market_context(
    context: dict[str, Any],
    *,
    evidence_packet: dict[str, Any],
    model_assist_status: str = "not_requested",
    refresh_policy: dict[str, Any] | None = None,
    refresh_results: Any = None,
    active_market_index: list[dict[str, Any] | Any] | None = None,
    shared_cache_entries: Any = None,
    consuming_dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_related_live_market_context(context)
    if context["artifact_type"] != "related_live_market_context":
        return dict(context)
    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in context["candidates"]}
    enriched_edges = [
        type_and_validate_edge(
            edge,
            evidence_packet=evidence_packet,
            candidate=candidates_by_id[edge["candidate_id"]],
            model_assist_status=model_assist_status,
        )
        for edge in context["relationship_edges"]
    ]
    enriched = {**context, "relationship_edges": enriched_edges}
    enriched = apply_refresh_lifecycle(
        enriched,
        refresh_policy=refresh_policy,
        refresh_results=refresh_results,
        active_market_index=active_market_index,
    )
    enriched = apply_shared_cache_reuse_eligibility(
        enriched,
        shared_cache_entries=shared_cache_entries,
        consuming_dispatch=consuming_dispatch,
    )
    validate_related_live_market_context(enriched)
    return attach_amrg_decomposer_context(enriched)


def model_assist_prompt_descriptor() -> str:
    return "\n".join(
        [
            "amrg model assist advisory prompt v1",
            "classify only existing candidate rows using fixed relationship vocabularies",
            "do not author probability, SCAE deltas, QDT selection, edge promotion, labels, or concepts",
        ]
    )


def build_amrg_model_assist_packet(
    context: dict[str, Any],
    *,
    model_lane_policy_ref: str = "plans/autonomous-decomposition-swarm-model-lane-policy.json",
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_related_live_market_context(context)
    if not context.get("input_manifest_hash"):
        raise AMRGError("active-safe input_manifest_hash is required for model assist")
    lane = resolve_amrg_model_assist_lane(policy)
    packet = {
        "artifact_type": "amrg_model_assist_packet",
        "schema_version": AMRG_MODEL_ASSIST_PACKET_SCHEMA_VERSION,
        "model_lane_id": AMRG_MODEL_ASSIST_LANE_ID,
        "resolved_model_id": lane["default_model_id"],
        "model_policy_ref": model_lane_policy_ref,
        "prompt_template_id": "amrg-model-assist-advisory/v1",
        "prompt_template_sha256": prefixed_sha256(model_assist_prompt_descriptor()),
        "input_manifest_sha256": context["input_manifest_hash"],
        "input_manifest_ids": context["input_manifest_ids"],
        "output_schema_version": AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
        "authority": "advisory_only_no_promotion",
        "forbidden_outputs": sorted(lane["forbidden_outputs"]),
        "relationship_type_vocabulary": sorted(RELATIONSHIP_TYPES),
        "relationship_status_vocabulary": sorted(RELATIONSHIP_STATUSES),
        "candidate_set_id": context["candidate_set_id"],
        "candidate_refs": [
            {
                "candidate_id": candidate["candidate_id"],
                "market_id": candidate["market_id"],
                "candidate_sources": candidate["candidate_sources"],
                "reason_codes": candidate["reason_codes"],
                "active_safe_fields_hash": candidate["active_safe_fields_hash"],
            }
            for candidate in context["candidates"]
        ],
        "edge_refs": [
            {
                "edge_id": edge["edge_id"],
                "candidate_id": edge["candidate_id"],
                "relationship_status": edge["relationship_status"],
            }
            for edge in context["relationship_edges"]
        ],
    }
    validate_amrg_model_assist_packet(packet)
    return packet


def validate_amrg_model_assist_packet(packet: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "model_lane_id",
        "resolved_model_id",
        "model_policy_ref",
        "prompt_template_id",
        "prompt_template_sha256",
        "input_manifest_sha256",
        "output_schema_version",
        "authority",
        "forbidden_outputs",
        "candidate_set_id",
        "candidate_refs",
        "edge_refs",
    ]
    for field in required:
        if field not in packet:
            raise AMRGError(f"model assist packet {field} is required")
    if packet["artifact_type"] != "amrg_model_assist_packet":
        raise AMRGError("model assist packet artifact_type is invalid")
    if packet["schema_version"] != AMRG_MODEL_ASSIST_PACKET_SCHEMA_VERSION:
        raise AMRGError(f"model assist packet schema_version must be {AMRG_MODEL_ASSIST_PACKET_SCHEMA_VERSION}")
    if packet["model_lane_id"] != AMRG_MODEL_ASSIST_LANE_ID:
        raise AMRGError("model assist packet must use amrg_model_assist lane")
    if packet["output_schema_version"] != AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION:
        raise AMRGError(f"model assist output schema must be {AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION}")
    if packet["authority"] != "advisory_only_no_promotion":
        raise AMRGError("model assist packet authority must be advisory_only_no_promotion")
    if not str(packet["input_manifest_sha256"]).startswith("sha256:"):
        raise AMRGError("model assist packet input_manifest_sha256 must be sha256")
    ensure_no_raw_amrg_fields(packet, "model_assist_packet")


def validate_amrg_model_assist_output(output: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "model_lane_id",
        "resolved_model_id",
        "authority",
        "candidate_set_id",
        "edge_annotations",
    ]
    for field in required:
        if field not in output:
            raise AMRGError(f"model assist output {field} is required")
    if output["artifact_type"] != "amrg_model_assist_output":
        raise AMRGError("model assist output artifact_type is invalid")
    if output["schema_version"] != AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION:
        raise AMRGError(f"model assist output schema_version must be {AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION}")
    if output["model_lane_id"] != AMRG_MODEL_ASSIST_LANE_ID:
        raise AMRGError("model assist output must use amrg_model_assist lane")
    if output["authority"] != "advisory_only_no_promotion":
        raise AMRGError("model assist output authority must be advisory_only_no_promotion")
    ensure_no_forbidden_model_output_fields(output)
    for annotation in output["edge_annotations"]:
        if not isinstance(annotation, dict):
            raise AMRGError("edge_annotations must be objects")
        if annotation.get("suggested_relationship_types") is not None:
            validate_relationship_type_list(annotation["suggested_relationship_types"])
        if annotation.get("advisory_only") is not True:
            raise AMRGError("model assist edge annotations must be advisory_only")


def build_model_assist_provenance(
    context: dict[str, Any],
    *,
    packet: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    status: str | None = None,
    output_artifact_ref: str | None = None,
) -> dict[str, Any]:
    if status is None:
        status = "advisory_validated" if output is not None else "not_requested"
    if status not in MODEL_ASSIST_STATUSES:
        raise AMRGError("unknown model assist status")
    if status != "not_invoked_missing_active_safe_manifest":
        validate_related_live_market_context(context)
    if packet is not None:
        validate_amrg_model_assist_packet(packet)
    if output is not None:
        validate_amrg_model_assist_output(output)
    provenance = {
        "schema_version": AMRG_MODEL_ASSIST_PROVENANCE_SCHEMA_VERSION,
        "model_assist_id": stable_id("amrg-model-assist", context["case_id"], context["dispatch_id"], context["candidate_set_id"], status),
        "case_id": context["case_id"],
        "market_id": str(context.get("market_id") or context["case_key"]),
        "dispatch_id": context["dispatch_id"],
        "candidate_set_id": context["candidate_set_id"],
        "model_assist_status": status,
        "model_id": packet.get("resolved_model_id") if packet else "not_invoked",
        "input_manifest_sha256": context.get("input_manifest_hash") or "sha256:missing",
        "output_artifact_ref": output_artifact_ref,
        "forbidden_output_check_status": "passed" if output is not None else "not_applicable",
        "invoked_at": utc_now_iso() if output is not None else None,
        "generated_at": utc_now_iso(),
        "metadata": {
            "authority": "advisory_only_no_promotion",
            "output_schema_version": output.get("schema_version") if output else None,
            "edge_annotation_count": len(output.get("edge_annotations", [])) if output else 0,
        },
    }
    ensure_no_raw_amrg_fields(provenance, "model_assist_provenance")
    return provenance


def model_assist_downgrade_for_missing_manifest(context: dict[str, Any]) -> dict[str, Any]:
    degraded = dict(context)
    degraded["input_manifest_hash"] = context.get("input_manifest_hash") or "sha256:missing"
    return build_model_assist_provenance(
        degraded,
        status="not_invoked_missing_active_safe_manifest",
    )


def invoke_amrg_model_assist(
    context: dict[str, Any],
    *,
    output: dict[str, Any] | None = None,
    transport: Any | None = None,
    output_artifact_ref: str | None = None,
) -> dict[str, Any] | None:
    if output is None and transport is None:
        return None
    if not context.get("input_manifest_hash"):
        return model_assist_downgrade_for_missing_manifest(context)
    packet = build_amrg_model_assist_packet(context)
    try:
        raw_output = output if output is not None else transport(packet)
        if not isinstance(raw_output, dict):
            raise AMRGError("model assist output must be an object")
    except Exception as exc:
        provenance = build_model_assist_provenance(
            context,
            packet=packet,
            status="advisory_unavailable_non_blocking",
            output_artifact_ref=output_artifact_ref,
        )
        provenance["metadata"]["unavailable_reason"] = str(exc)
        return provenance
    try:
        validate_amrg_model_assist_output(raw_output)
    except AMRGError as exc:
        provenance = build_model_assist_provenance(
            context,
            packet=packet,
            status="advisory_rejected_forbidden_output",
            output_artifact_ref=output_artifact_ref,
        )
        provenance["forbidden_output_check_status"] = "failed"
        provenance["metadata"]["rejection_reason"] = str(exc)
        return provenance
    return build_model_assist_provenance(
        context,
        packet=packet,
        output=raw_output,
        output_artifact_ref=output_artifact_ref,
    )


def compact_vector_runtime_metadata(vector_runtime: dict[str, Any] | None) -> dict[str, Any]:
    if not vector_runtime:
        return {
            "schema_version": "amrg-live-vector-runtime-summary/v1",
            "status": "not_requested",
            "readiness_status": "vector_unavailable_allowed_weak_context",
            "vector_candidate_count": 0,
            "descriptor_count": 0,
        }
    preflight = vector_runtime.get("preflight") or {}
    snapshot = vector_runtime.get("index_snapshot") or {}
    diagnostics = vector_runtime.get("vector_source_diagnostics") or []
    return {
        "schema_version": "amrg-live-vector-runtime-summary/v1",
        "status": vector_runtime.get("status"),
        "readiness_status": amrg_vector_readiness_status(
            preflight=preflight,
            vector_runtime_status=vector_runtime.get("status"),
            vector_required=False,
        ),
        "preflight_status": "ok" if preflight.get("ok") else "unavailable",
        "provider": preflight.get("provider") or snapshot.get("provider"),
        "route_id": preflight.get("route_id") or snapshot.get("route_id"),
        "resolved_model_id": preflight.get("resolved_model_id") or snapshot.get("resolved_model_id"),
        "download_command_contract": preflight.get("download_command_contract") or snapshot.get("download_command_contract"),
        "pull_attempted": bool(preflight.get("pull_attempted")),
        "pull_succeeded": bool(preflight.get("pull_succeeded")),
        "ollama_base_url_redacted": preflight.get("ollama_base_url_redacted") or snapshot.get("ollama_base_url_redacted"),
        "ollama_version": preflight.get("ollama_version") or snapshot.get("ollama_version"),
        "model_digest": preflight.get("model_digest") or snapshot.get("model_digest"),
        "embed_endpoint": preflight.get("embed_endpoint") or snapshot.get("embed_endpoint"),
        "embedding_dimension": preflight.get("embedding_dimension") or snapshot.get("embedding_dimension"),
        "descriptor_count": len(vector_runtime.get("descriptors") or []),
        "candidate_descriptor_count": len(vector_runtime.get("candidate_descriptors") or []),
        "descriptor_sha256s": [
            descriptor["descriptor_sha256"]
            for descriptor in vector_runtime.get("descriptors", [])
            if isinstance(descriptor, dict) and descriptor.get("descriptor_sha256")
        ],
        "index_snapshot_id": snapshot.get("index_snapshot_id"),
        "index_status": snapshot.get("index_status"),
        "vector_candidate_count": len(vector_runtime.get("vector_candidates") or []),
        "diagnostic_unavailable_reasons": [
            diagnostic.get("unavailable_reason")
            for diagnostic in diagnostics
            if isinstance(diagnostic, dict) and diagnostic.get("unavailable_reason")
        ],
        "descriptor_exclusion_counts": vector_runtime.get("descriptor_exclusion_counts") or {},
    }


def build_amrg_operator_report(
    context: dict[str, Any],
    *,
    question_decomposition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if context.get("artifact_type") == "related_live_market_context":
        validate_related_live_market_context(context)
    else:
        validate_no_related_context_waiver(context)
    hints = (
        context.get("amrg_decomposer_context", {}).get("hints", [])
        if isinstance(context.get("amrg_decomposer_context"), dict)
        else []
    )
    consumed_leaf_refs: dict[str, list[str]] = {}
    consumed_branch_refs: dict[str, list[str]] = {}
    if isinstance(question_decomposition, dict):
        metadata = question_decomposition.get("amrg_operator_metadata")
        if isinstance(metadata, dict):
            consumed_leaf_refs = {
                str(leaf_id): [str(ref) for ref in refs]
                for leaf_id, refs in (metadata.get("leaf_hint_refs") or {}).items()
                if isinstance(refs, list)
            }
            consumed_branch_refs = {
                str(branch_id): [str(ref) for ref in refs]
                for branch_id, refs in (metadata.get("branch_hint_refs") or {}).items()
                if isinstance(refs, list)
            }
    consumed_by_ref: dict[str, dict[str, list[str]]] = {
        str(hint.get("hint_ref")): {"leaf_ids": [], "branch_ids": []}
        for hint in hints
        if isinstance(hint, dict) and hint.get("hint_ref")
    }
    for leaf_id, refs in consumed_leaf_refs.items():
        for ref in refs:
            consumed_by_ref.setdefault(ref, {"leaf_ids": [], "branch_ids": []})["leaf_ids"].append(leaf_id)
    for branch_id, refs in consumed_branch_refs.items():
        for ref in refs:
            consumed_by_ref.setdefault(ref, {"leaf_ids": [], "branch_ids": []})["branch_ids"].append(branch_id)
    vector_runtime = context.get("vector_runtime") if isinstance(context.get("vector_runtime"), dict) else {}
    source_policy = context.get("source_policy") if isinstance(context.get("source_policy"), dict) else {}
    vector_required = bool(source_policy.get("vector_source_required", False))
    dependency_readiness = build_amrg_dependency_readiness(
        vector_runtime=vector_runtime,
        vector_required=vector_required,
        model_assist_status=context.get("model_assist_status", "not_requested"),
    )
    report = {
        "schema_version": AMRG_OPERATOR_REPORT_SCHEMA_VERSION,
        "candidate_set_id": context["candidate_set_id"],
        "artifact_type": context["artifact_type"],
        "candidate_count": len(context.get("candidates", [])),
        "candidate_source_mix": dict(Counter(
            source
            for candidate in context.get("candidates", [])
            for source in candidate.get("candidate_sources", [])
        )),
        "vector_status": vector_runtime.get("status", "not_requested"),
        "vector_readiness_status": dependency_readiness["vector_status"],
        "ollama_route": {
            "provider": vector_runtime.get("provider"),
            "route_id": vector_runtime.get("route_id"),
            "resolved_model_id": vector_runtime.get("resolved_model_id"),
            "preflight_status": vector_runtime.get("preflight_status"),
            "pull_attempted": bool(vector_runtime.get("pull_attempted")),
            "pull_policy": dependency_readiness["ollama_route"]["pull_policy"],
            "ollama_base_url_redacted": vector_runtime.get("ollama_base_url_redacted"),
        },
        "embedding": {
            "dimension": vector_runtime.get("embedding_dimension"),
            "descriptor_count": vector_runtime.get("descriptor_count", 0),
            "candidate_descriptor_count": vector_runtime.get("candidate_descriptor_count", 0),
            "index_snapshot_id": vector_runtime.get("index_snapshot_id"),
            "index_status": vector_runtime.get("index_status"),
        },
        "model_assist_status": context.get("model_assist_status", "not_requested"),
        "assist_readiness_status": dependency_readiness["assist_status"],
        "dependency_readiness": dependency_readiness,
        "relationship_status_counts": dict(Counter(
            edge.get("relationship_status")
            for edge in context.get("relationship_edges", [])
            if isinstance(edge, dict)
        )),
        "refresh_status_counts": dict(Counter(
            (edge.get("refresh_lifecycle_state") or {}).get("refresh_status")
            for edge in context.get("relationship_edges", [])
            if isinstance(edge, dict)
        )),
        "downgrade_reason_codes": sorted({
            reason
            for edge in context.get("relationship_edges", [])
            for reason in edge.get("downgrade_reason_codes", [])
        }),
        "strict_precedence_anchor_state": dict(Counter(
            edge.get("anchor_validation_status", "not_evaluated")
            for edge in context.get("relationship_edges", [])
            if edge.get("relationship_status") in STRICT_PRECEDENCE_ANCHOR_STATUSES
        )),
        "decomposer_consumption_status": (
            "evaluated"
            if isinstance(question_decomposition, dict)
            else "pending_decomposition"
        ),
        "hint_consumption": [
            {
                "hint_ref": hint.get("hint_ref"),
                "hint_category": hint.get("hint_category"),
                "effect_status": hint.get("effect_status"),
                "source_market_ref": hint.get("source_market_ref"),
                "decomposer_consumed": bool(
                    consumed_by_ref.get(str(hint.get("hint_ref")), {}).get("leaf_ids")
                    or consumed_by_ref.get(str(hint.get("hint_ref")), {}).get("branch_ids")
                ),
                "consumed_by_leaf_ids": sorted(consumed_by_ref.get(str(hint.get("hint_ref")), {}).get("leaf_ids", [])),
                "consumed_by_branch_ids": sorted(consumed_by_ref.get(str(hint.get("hint_ref")), {}).get("branch_ids", [])),
            }
            for hint in hints
            if isinstance(hint, dict)
        ],
        "authority": "operator_audit_only_no_forecast_authority",
    }
    ensure_no_raw_amrg_fields(report, "amrg_operator_report")
    return report


def related_live_market_artifact_path(artifact_dir: Path | str, artifact: dict[str, Any]) -> Path:
    base = Path(artifact_dir) / artifact["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    suffix = (
        "related-live-market-context"
        if artifact["artifact_type"] == "related_live_market_context"
        else "no-related-context-waiver"
    )
    return base / f"{artifact['dispatch_id']}-{suffix}.json"


def write_related_live_market_artifact(path: Path | str, artifact: dict[str, Any]) -> Path:
    if artifact.get("artifact_type") == "related_live_market_context":
        validate_related_live_market_context(artifact)
    elif artifact.get("artifact_type") == "no_related_context_waiver":
        validate_no_related_context_waiver(artifact)
    else:
        raise AMRGError("unknown AMRG artifact_type")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(artifact) + "\n", encoding="utf-8")
    return target


def build_manifest_for_related_live_market_artifact(artifact: dict[str, Any], path: Path | str) -> dict[str, Any]:
    if artifact.get("artifact_type") == "related_live_market_context":
        schema_version = RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION
        artifact_type = RELATED_LIVE_MARKET_CONTEXT_ARTIFACT_TYPE
        validate_related_live_market_context(artifact)
    elif artifact.get("artifact_type") == "no_related_context_waiver":
        schema_version = NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION
        artifact_type = NO_RELATED_CONTEXT_WAIVER_ARTIFACT_TYPE
        validate_no_related_context_waiver(artifact)
    else:
        raise AMRGError("unknown AMRG artifact_type")
    manifest_context = ArtifactManifestContext(
        case_id=artifact["case_id"],
        case_key=artifact["case_key"],
        dispatch_id=artifact["dispatch_id"],
        stage=AMRG_STAGE,
        producer=AMRG_PRODUCER,
        forecast_timestamp=artifact["forecast_timestamp"],
        source_cutoff_timestamp=artifact["source_cutoff_timestamp"],
    )
    manifest = build_artifact_manifest(
        context=manifest_context,
        artifact_type=artifact_type,
        artifact_schema_version=schema_version,
        path=path,
        input_manifest_ids=artifact["input_manifest_ids"],
        validation_status="valid",
        validator_version=schema_version,
        temporal_isolation_status="pass",
        metadata={
            "candidate_set_id": artifact["candidate_set_id"],
            "candidate_count": len(artifact["candidates"]),
            "waiver_reason_code": artifact.get("reason_code"),
            "input_manifest_hash": artifact["input_manifest_hash"],
            "vector_diagnostic_reason_codes": [
                diagnostic.get("reason_code")
                for diagnostic in artifact.get("vector_source_diagnostics", [])
                if diagnostic.get("reason_code")
            ],
            "amrg_decomposer_context_schema_version": (
                artifact.get("amrg_decomposer_context", {}).get("schema_version")
            ),
            "amrg_decomposer_hint_count": len(
                artifact.get("amrg_decomposer_context", {}).get("hints", [])
                if isinstance(artifact.get("amrg_decomposer_context"), dict)
                else []
            ),
            "amrg_decomposer_hint_refs": (
                artifact.get("amrg_decomposer_context", {})
                .get("operator_metadata", {})
                .get("hint_refs_considered", [])
                if isinstance(artifact.get("amrg_decomposer_context"), dict)
                else []
            ),
            "amrg_vector_status": (artifact.get("vector_runtime") or {}).get("status"),
            "amrg_vector_readiness_status": artifact.get("vector_readiness_status")
            or (artifact.get("dependency_readiness") or {}).get("vector_status"),
            "amrg_vector_preflight_status": (artifact.get("vector_runtime") or {}).get("preflight_status"),
            "amrg_vector_candidate_count": (artifact.get("vector_runtime") or {}).get("vector_candidate_count"),
            "amrg_model_assist_status": artifact.get("model_assist_status"),
            "amrg_assist_readiness_status": artifact.get("assist_readiness_status")
            or (artifact.get("dependency_readiness") or {}).get("assist_status"),
            "amrg_operator_report_schema_version": (
                artifact.get("amrg_operator_report", {}).get("schema_version")
                if isinstance(artifact.get("amrg_operator_report"), dict)
                else None
            ),
        },
    )
    validate_artifact_manifest(manifest, expected_artifact_schema_version=schema_version)
    return manifest


def materialize_related_live_market_context(
    conn: sqlite3.Connection,
    *,
    evidence_packet: dict[str, Any],
    evidence_packet_ref: str,
    artifact_dir: Path | str,
    active_market_index: list[dict[str, Any] | Any],
    exposure_context: Any = None,
    vector_candidates: list[dict[str, Any]] | None = None,
    vector_source_diagnostics: Any = None,
    profile_context_ref: str | None = None,
    candidate_cap: int = DEFAULT_AMRG_CANDIDATE_CAP,
    run_vector_runtime: bool = False,
    ollama_client: Any | None = None,
    allow_vector_pull: bool = False,
    vector_neighbor_cap: int = AMRG_VECTOR_RUNTIME_NEIGHBOR_CAP,
    model_assist_output: dict[str, Any] | None = None,
    model_assist_transport: Any | None = None,
    model_assist_output_artifact_ref: str | None = None,
    refresh_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    vector_runtime: dict[str, Any] | None = None
    runtime_vector_candidates: list[dict[str, Any]] = []
    runtime_vector_diagnostics: list[dict[str, Any]] = []
    if run_vector_runtime:
        vector_runtime = build_live_amrg_vector_runtime(
            evidence_packet=evidence_packet,
            active_market_index=active_market_index,
            client=ollama_client,
            allow_pull=allow_vector_pull,
            neighbor_cap=vector_neighbor_cap,
        )
        runtime_vector_candidates = list(vector_runtime.get("vector_candidates") or [])
        runtime_vector_diagnostics = list(vector_runtime.get("vector_source_diagnostics") or [])
    combined_vector_candidates = list(vector_candidates or []) + runtime_vector_candidates
    combined_vector_diagnostics = normalize_vector_diagnostics(vector_source_diagnostics) + runtime_vector_diagnostics

    artifact = build_related_live_market_context_or_waiver(
        evidence_packet=evidence_packet,
        evidence_packet_ref=evidence_packet_ref,
        active_market_index=active_market_index,
        exposure_context=exposure_context,
        vector_candidates=combined_vector_candidates,
        vector_source_diagnostics=combined_vector_diagnostics,
        profile_context_ref=profile_context_ref,
        candidate_cap=candidate_cap,
    )
    model_assist_provenance = invoke_amrg_model_assist(
        artifact,
        output=model_assist_output,
        transport=model_assist_transport,
        output_artifact_ref=model_assist_output_artifact_ref,
    )
    model_assist_status = (
        model_assist_provenance["model_assist_status"]
        if model_assist_provenance
        else "not_requested"
    )
    if artifact["artifact_type"] == "related_live_market_context":
        artifact = enrich_related_live_market_context(
            artifact,
            evidence_packet=evidence_packet,
            model_assist_status=model_assist_status,
            refresh_policy=refresh_policy or artifact.get("refresh_policy"),
            active_market_index=active_market_index,
        )
    artifact = {
        **artifact,
        "vector_runtime": compact_vector_runtime_metadata(vector_runtime),
        "model_assist_status": model_assist_status,
    }
    dependency_readiness = build_amrg_dependency_readiness(
        vector_runtime=artifact["vector_runtime"],
        vector_required=bool((artifact.get("source_policy") or {}).get("vector_source_required", False)),
        model_assist_status=model_assist_status,
    )
    artifact = {
        **artifact,
        "vector_readiness_status": dependency_readiness["vector_status"],
        "assist_readiness_status": dependency_readiness["assist_status"],
        "dependency_readiness": dependency_readiness,
    }
    artifact = attach_amrg_decomposer_context(artifact)
    artifact = {
        **artifact,
        "amrg_operator_report": build_amrg_operator_report(artifact),
    }
    if artifact["artifact_type"] == "related_live_market_context":
        validate_related_live_market_context(artifact)
    else:
        validate_no_related_context_waiver(artifact)

    vector_descriptor_ids: list[str] = []
    vector_index_snapshot_id = None
    vector_neighbor_candidate_ids: list[str] = []
    if vector_runtime:
        vector_descriptor_ids = write_amrg_vector_descriptors(conn, vector_runtime.get("descriptors") or [])
        vector_index_snapshot_id = write_amrg_vector_index_snapshot(conn, vector_runtime["index_snapshot"])
        vector_neighbor_candidate_ids = write_amrg_vector_neighbor_candidates(
            conn,
            candidate_set_id=artifact["candidate_set_id"],
            case_id=artifact["case_id"],
            dispatch_id=artifact["dispatch_id"],
            candidates=runtime_vector_candidates,
        )
    model_assist_id = write_model_assist_provenance(conn, model_assist_provenance) if model_assist_provenance else None

    path = write_related_live_market_artifact(related_live_market_artifact_path(artifact_dir, artifact), artifact)
    manifest = build_manifest_for_related_live_market_artifact(artifact, path)
    artifact_id = write_artifact_manifest(conn, manifest)
    return {
        "status": "completed",
        "artifact_id": artifact_id,
        "artifact_path": str(path),
        "artifact_type": artifact["artifact_type"],
        "artifact": artifact,
        "manifest": manifest,
        "vector_descriptor_ids": vector_descriptor_ids,
        "vector_index_snapshot_id": vector_index_snapshot_id,
        "vector_neighbor_candidate_ids": vector_neighbor_candidate_ids,
        "model_assist_id": model_assist_id,
    }


def ensure_amrg_context_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(AMRG_CONTEXT_MIGRATION.read_text(encoding="utf-8"))


def selected_market_id_for_context(context: dict[str, Any], evidence_packet: dict[str, Any] | None = None) -> str:
    return str(context.get("market_id") or (evidence_packet or {}).get("market_id") or context["case_key"])


def write_amrg_vector_descriptors(conn: sqlite3.Connection, descriptors: list[dict[str, Any]]) -> list[str]:
    ensure_amrg_context_schema(conn)
    rows = descriptor_rows_for_write(descriptors)
    written: list[str] = []
    for row in rows:
        conn.execute(
            """
            INSERT INTO amrg_market_vector_descriptors (
              descriptor_sha256, market_id, external_market_id, case_key,
              source_cutoff_timestamp, descriptor_schema_version, descriptor_text,
              active_safe_fields
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(descriptor_sha256) DO UPDATE SET
              market_id=excluded.market_id,
              external_market_id=excluded.external_market_id,
              case_key=excluded.case_key,
              source_cutoff_timestamp=excluded.source_cutoff_timestamp,
              descriptor_schema_version=excluded.descriptor_schema_version,
              descriptor_text=excluded.descriptor_text,
              active_safe_fields=excluded.active_safe_fields
            """,
            (
                row["descriptor_sha256"],
                str(row["market_id"]),
                row.get("external_market_id"),
                row.get("case_key"),
                row["source_cutoff_timestamp"],
                row["descriptor_schema_version"],
                row["descriptor_text"],
                row["active_safe_fields"],
            ),
        )
        written.append(row["descriptor_sha256"])
    return written


def write_amrg_vector_index_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> str:
    ensure_amrg_context_schema(conn)
    validate_vector_index_snapshot(snapshot)
    conn.execute(
        """
        INSERT INTO amrg_vector_index_snapshots (
          index_snapshot_id, schema_version, embedding_lane_id, provider, route_id,
          resolved_model_id, model_policy_ref, embedding_model_sha256,
          embedding_dimension, similarity_metric, source_cutoff_timestamp,
          descriptor_schema_version, descriptor_count, descriptor_sha256s,
          index_status, unavailable_reason, diagnostic
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(index_snapshot_id) DO UPDATE SET
          index_status=excluded.index_status,
          unavailable_reason=excluded.unavailable_reason,
          diagnostic=excluded.diagnostic
        """,
        (
            snapshot["index_snapshot_id"],
            snapshot["schema_version"],
            snapshot["embedding_lane_id"],
            snapshot["provider"],
            snapshot["route_id"],
            snapshot["resolved_model_id"],
            snapshot["model_policy_ref"],
            snapshot["embedding_model_sha256"],
            snapshot["embedding_dimension"],
            snapshot["similarity_metric"],
            snapshot["source_cutoff_timestamp"],
            snapshot["descriptor_schema_version"],
            snapshot["descriptor_count"],
            canonical_json(snapshot["descriptor_sha256s"]),
            snapshot["index_status"],
            snapshot.get("unavailable_reason"),
            canonical_json(snapshot.get("diagnostic") or {}),
        ),
    )
    return snapshot["index_snapshot_id"]


def write_amrg_vector_neighbor_candidates(
    conn: sqlite3.Connection,
    *,
    candidate_set_id: str | None,
    case_id: str | None,
    dispatch_id: str | None,
    candidates: list[dict[str, Any]],
) -> list[str]:
    ensure_amrg_context_schema(conn)
    written: list[str] = []
    for candidate in candidates:
        validate_vector_neighbor_candidate(candidate)
        row_id = stable_id(
            "amrg-vector-neighbor",
            candidate_set_id,
            case_id,
            dispatch_id,
            candidate["market_id"],
            candidate["index_snapshot_id"],
            candidate["candidate_descriptor_sha256"],
        )
        conn.execute(
            """
            INSERT INTO amrg_vector_neighbor_candidate_slices (
              vector_neighbor_candidate_id, candidate_set_id, case_id, dispatch_id,
              market_id, external_market_id, relationship_status, similarity_score,
              similarity_metric, query_descriptor_sha256, candidate_descriptor_sha256,
              index_snapshot_id, embedding_lane_id, resolved_model_id, route_id,
              metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vector_neighbor_candidate_id) DO UPDATE SET
              similarity_score=excluded.similarity_score,
              metadata=excluded.metadata
            """,
            (
                row_id,
                candidate_set_id,
                case_id,
                dispatch_id,
                str(candidate["market_id"]),
                candidate.get("external_market_id"),
                candidate["relationship_status"],
                candidate["similarity_score"],
                candidate["similarity_metric"],
                candidate["query_descriptor_sha256"],
                candidate["candidate_descriptor_sha256"],
                candidate["index_snapshot_id"],
                candidate["embedding_lane_id"],
                candidate["resolved_model_id"],
                candidate["route_id"],
                canonical_json({"vector_only": True}),
            ),
        )
        written.append(row_id)
    return written


def write_model_assist_provenance(conn: sqlite3.Connection, provenance: dict[str, Any]) -> str:
    ensure_amrg_context_schema(conn)
    if provenance.get("schema_version") != AMRG_MODEL_ASSIST_PROVENANCE_SCHEMA_VERSION:
        raise AMRGError(f"model assist provenance schema_version must be {AMRG_MODEL_ASSIST_PROVENANCE_SCHEMA_VERSION}")
    if provenance.get("model_assist_status") not in MODEL_ASSIST_STATUSES:
        raise AMRGError("unknown model assist provenance status")
    ensure_no_raw_amrg_fields(provenance, "model_assist_provenance")
    conn.execute(
        """
        INSERT INTO amrg_model_assist_provenance (
          model_assist_id, case_id, market_id, dispatch_id, candidate_set_id,
          model_assist_status, model_id, input_manifest_sha256,
          output_artifact_ref, forbidden_output_check_status, invoked_at,
          generated_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(model_assist_id) DO UPDATE SET
          model_assist_status=excluded.model_assist_status,
          output_artifact_ref=excluded.output_artifact_ref,
          forbidden_output_check_status=excluded.forbidden_output_check_status,
          metadata=excluded.metadata
        """,
        (
            provenance["model_assist_id"],
            provenance["case_id"],
            str(provenance["market_id"]),
            provenance["dispatch_id"],
            provenance["candidate_set_id"],
            provenance["model_assist_status"],
            provenance["model_id"],
            provenance["input_manifest_sha256"],
            provenance.get("output_artifact_ref"),
            provenance["forbidden_output_check_status"],
            provenance.get("invoked_at"),
            provenance["generated_at"],
            canonical_json(provenance.get("metadata") or {}),
        ),
    )
    return provenance["model_assist_id"]


def relationship_strength_for_status(status: str) -> str:
    if status == "validated_strict_precedence_anchor":
        return "validated_strict_precedence_anchor"
    if status == "strict_precedence_anchor_candidate":
        return "strict_precedence_anchor_candidate"
    return "context_candidate" if status == "deterministic_context_candidate" else "weak_context"


def guardrail_reason_codes_for_edge(edge: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if edge.get("timing_alignment_status") in {"lookahead_blocked", "skew_exceeds_policy", "missing_related_snapshot"}:
        reasons.append(edge["timing_alignment_status"])
    if edge.get("relationship_status") in {"timing_mismatch_weak_context_only", WEAK_CONTEXT_ONLY}:
        reasons.append("weak_context_only")
    if edge.get("anchor_validation_status") == "rejected":
        reasons.extend(edge.get("anchor_validation_reason_codes", []))
    return sorted(set(reasons))


def write_related_market_context(
    conn: sqlite3.Connection,
    context: dict[str, Any],
    *,
    evidence_packet: dict[str, Any],
    model_assist_provenance: dict[str, Any] | None = None,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
    refresh_policy: dict[str, Any] | None = None,
    refresh_results: Any = None,
    active_market_index: list[dict[str, Any] | Any] | None = None,
    qdt_anchor_contracts: Any = None,
    anchor_graph_edges: Any = None,
    shared_cache_entries: Any = None,
    consuming_dispatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_amrg_context_schema(conn)
    model_assist_status = model_assist_provenance["model_assist_status"] if model_assist_provenance else "not_requested"
    enriched = enrich_related_live_market_context(
        context,
        evidence_packet=evidence_packet,
        model_assist_status=model_assist_status,
        refresh_policy=refresh_policy,
        refresh_results=refresh_results,
        active_market_index=active_market_index,
        shared_cache_entries=shared_cache_entries,
        consuming_dispatch=consuming_dispatch,
    )
    if qdt_anchor_contracts is not None or any(
        edge.get("relationship_status") in STRICT_PRECEDENCE_ANCHOR_STATUSES
        for edge in enriched.get("relationship_edges", [])
    ):
        enriched = apply_strict_precedence_anchor_validation(
            enriched,
            qdt_anchor_contracts=qdt_anchor_contracts,
            graph_edges=anchor_graph_edges,
        )
    selected_market_id = selected_market_id_for_context(enriched, evidence_packet)
    generated_at = utc_now_iso()

    conn.execute(
        """
        INSERT INTO amrg_candidate_sets (
          candidate_set_id, case_id, case_key, market_id, dispatch_id,
          forecast_timestamp, source_policy, candidate_pool_max, candidate_count,
          exclusion_counts, input_manifest_sha256, artifact_path, artifact_sha256,
          generated_at, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_set_id) DO UPDATE SET
          candidate_count=excluded.candidate_count,
          exclusion_counts=excluded.exclusion_counts,
          artifact_path=excluded.artifact_path,
          artifact_sha256=excluded.artifact_sha256,
          metadata=excluded.metadata
        """,
        (
            enriched["candidate_set_id"],
            enriched["case_id"],
            enriched["case_key"],
            selected_market_id,
            enriched["dispatch_id"],
            enriched["forecast_timestamp"],
            canonical_json(enriched["source_policy"]),
            enriched["source_policy"]["candidate_pool_max"],
            len(enriched["candidates"]),
            canonical_json(enriched["exclusion_counts"]),
            enriched["input_manifest_hash"],
            artifact_path,
            artifact_sha256,
            generated_at,
            canonical_json({"schema_version": enriched["schema_version"], "profile_context_ref": enriched.get("profile_context_ref")}),
        ),
    )

    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in enriched["candidates"]}
    candidate_row_ids: list[str] = []
    relationship_row_ids: list[str] = []
    graph_row_ids: list[str] = []
    refresh_row_ids: list[str] = []
    prior_anchor_row_ids: list[str] = []
    prior_anchor_slices_by_edge = {
        slice_row["edge_id"]: slice_row
        for slice_row in enriched.get("prior_anchor_slices", [])
    }

    for edge in enriched["relationship_edges"]:
        validate_relationship_edge(edge)
        candidate = candidates_by_id[edge["candidate_id"]]
        relationship_types = edge.get("relationship_types") or relationship_types_for_candidate(candidate)
        timing_refs = edge.get("timing_alignment_basis_refs") or []
        conn.execute(
            """
            INSERT INTO amrg_candidate_peer_rows (
              candidate_id, candidate_set_id, case_id, market_id, dispatch_id,
              selected_market_id, related_market_id, candidate_rank,
              nomination_methods, relationship_type_proposals, directionality_proposal,
              timing_input_refs, snapshot_as_of, generated_at, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
              candidate_rank=excluded.candidate_rank,
              nomination_methods=excluded.nomination_methods,
              relationship_type_proposals=excluded.relationship_type_proposals,
              timing_input_refs=excluded.timing_input_refs,
              metadata=excluded.metadata
            """,
            (
                candidate["candidate_id"],
                enriched["candidate_set_id"],
                enriched["case_id"],
                selected_market_id,
                enriched["dispatch_id"],
                selected_market_id,
                str(candidate["market_id"]),
                candidate.get("candidate_rank", 0),
                canonical_json(candidate["candidate_sources"]),
                canonical_json(relationship_types),
                "undirected_context",
                canonical_json(timing_refs),
                edge.get("related_market_snapshot_as_of"),
                generated_at,
                canonical_json({"candidate_source": candidate["candidate_source"], "reason_codes": candidate["reason_codes"]}),
            ),
        )
        candidate_row_ids.append(candidate["candidate_id"])

        relationship_slice_id = stable_id("amrg-relationship-slice", enriched["candidate_set_id"], edge["edge_id"])
        guardrail_reasons = guardrail_reason_codes_for_edge(edge)
        conn.execute(
            """
            INSERT INTO related_market_relationship_slices (
              relationship_slice_id, case_id, market_id, dispatch_id, edge_id,
              selected_market_id, related_market_id, related_case_key,
              related_pipeline_state, candidate_set_id, candidate_rank,
              candidate_generation_methods, candidate_pool_input_manifest_sha256,
              model_assist_status, model_assist_context, relationship_types,
              relationship_strength, shared_causal_driver_tier, directionality,
              concrete_shared_objects, causal_influence_fingerprint,
              relationship_valid_before_forecast, selected_market_snapshot_as_of,
              related_market_snapshot_as_of, max_snapshot_skew_seconds,
              timing_alignment_status, evidence_basis, source_policy,
              allowed_effects, forbidden_effects, related_market_snapshot_pricing,
              causal_graph_status, guardrail_status, guardrail_reason_codes,
              artifact_path, artifact_sha256, generated_at, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relationship_slice_id) DO UPDATE SET
              model_assist_status=excluded.model_assist_status,
              relationship_types=excluded.relationship_types,
              relationship_strength=excluded.relationship_strength,
              timing_alignment_status=excluded.timing_alignment_status,
              guardrail_status=excluded.guardrail_status,
              guardrail_reason_codes=excluded.guardrail_reason_codes,
              metadata=excluded.metadata
            """,
            (
                relationship_slice_id,
                enriched["case_id"],
                selected_market_id,
                enriched["dispatch_id"],
                edge["edge_id"],
                selected_market_id,
                str(candidate["market_id"]),
                candidate.get("external_market_id"),
                "active_safe_candidate",
                enriched["candidate_set_id"],
                candidate.get("candidate_rank", 0),
                canonical_json(candidate["candidate_sources"]),
                enriched["input_manifest_hash"],
                edge.get("model_assist_status", model_assist_status),
                canonical_json(edge.get("model_assist_context") or {}),
                canonical_json(relationship_types),
                relationship_strength_for_status(edge["relationship_status"]),
                "none_phase7_no_anchor_authority",
                "undirected_context",
                canonical_json({"source_refs": candidate.get("source_refs", [])}),
                None,
                1 if edge.get("timing_alignment_status") == "aligned" else 0,
                edge.get("selected_market_snapshot_as_of"),
                edge.get("related_market_snapshot_as_of"),
                edge.get("max_snapshot_skew_seconds"),
                edge.get("timing_alignment_status") or "missing_related_snapshot",
                canonical_json(timing_refs),
                canonical_json(enriched["source_policy"]),
                canonical_json(edge["allowed_effects"]),
                canonical_json(edge["forbidden_effects"]),
                canonical_json({}),
                edge.get("causal_graph_status", "not_applicable_weak_context"),
                "pass" if not guardrail_reasons else "downgraded",
                canonical_json(guardrail_reasons),
                artifact_path,
                artifact_sha256,
                generated_at,
                canonical_json({"relationship_status": edge["relationship_status"], "schema_version": AMRG_WEAK_EDGE_SCHEMA_VERSION}),
            ),
        )
        relationship_row_ids.append(relationship_slice_id)

        graph_slice_id = edge["graph_safety_slice_id"]
        conn.execute(
            """
            INSERT INTO amrg_causal_graph_safety_slices (
              graph_safety_slice_id, case_id, market_id, dispatch_id, edge_id,
              graph_component_id, causal_edge_role, topological_rank,
              event_time_ordering_basis, strict_precedence_proof_ref,
              cycle_status, cycle_break_reason, max_refresh_hop_depth,
              refresh_generation_id, downgrade_applied, downgrade_reason_codes,
              generated_at, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(graph_safety_slice_id) DO UPDATE SET
              cycle_status=excluded.cycle_status,
              downgrade_applied=excluded.downgrade_applied,
              downgrade_reason_codes=excluded.downgrade_reason_codes,
              metadata=excluded.metadata
            """,
            (
                graph_slice_id,
                enriched["case_id"],
                selected_market_id,
                enriched["dispatch_id"],
                edge["edge_id"],
                edge["graph_component_id"],
                edge["causal_edge_role"],
                None,
                edge.get("event_time_ordering_basis"),
                edge.get("strict_precedence_proof_ref"),
                edge["cycle_status"],
                None,
                edge["max_refresh_hop_depth"],
                edge["refresh_generation_id"],
                1 if edge["downgrade_applied"] else 0,
                canonical_json(edge["downgrade_reason_codes"]),
                generated_at,
                canonical_json({"causal_graph_status": edge.get("causal_graph_status")}),
            ),
        )
        graph_row_ids.append(graph_slice_id)

        lifecycle = edge.get("refresh_lifecycle_state") or refresh_lifecycle_state(
            edge=edge,
            refresh_status="refresh_required_later",
            reason_codes=["missing_refresh_lifecycle_state"],
            policy=normalize_refresh_policy(enriched, refresh_policy),
            stale_before_refresh=True,
        )
        refresh_event_id = stable_id("amrg-refresh-event", edge["edge_id"], lifecycle["refresh_generation_id"])
        conn.execute(
            """
            INSERT INTO related_market_refresh_events (
              refresh_event_id, case_id, market_id, dispatch_id, edge_id,
              candidate_set_id, refresh_status, refresh_reason_codes,
              refresh_generation_id, max_refresh_hop_depth,
              stale_effect_downgrade_applied, next_refresh_after,
              generated_at, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(refresh_event_id) DO UPDATE SET
              refresh_status=excluded.refresh_status,
              refresh_reason_codes=excluded.refresh_reason_codes,
              refresh_generation_id=excluded.refresh_generation_id,
              max_refresh_hop_depth=excluded.max_refresh_hop_depth,
              stale_effect_downgrade_applied=excluded.stale_effect_downgrade_applied,
              next_refresh_after=excluded.next_refresh_after,
              metadata=excluded.metadata
            """,
            (
                refresh_event_id,
                enriched["case_id"],
                selected_market_id,
                enriched["dispatch_id"],
                edge["edge_id"],
                enriched["candidate_set_id"],
                lifecycle["refresh_status"],
                canonical_json(lifecycle["refresh_reason_codes"]),
                lifecycle["refresh_generation_id"],
                edge["max_refresh_hop_depth"],
                1 if lifecycle["stale_effect_downgrade_applied"] else 0,
                lifecycle.get("next_refresh_after"),
                generated_at,
                canonical_json(
                    {
                        "schema_version": lifecycle["schema_version"],
                        "refresh_as_of_timestamp": lifecycle["refresh_as_of_timestamp"],
                        "ttl_seconds": lifecycle["ttl_seconds"],
                        "stale_before_refresh": lifecycle["stale_before_refresh"],
                        "material_change_detected": lifecycle["material_change_detected"],
                        "refresh_attempted": lifecycle["refresh_attempted"],
                        "refresh_budget_consumed": lifecycle["refresh_budget_consumed"],
                        "deterministic_validation_status": lifecycle.get("deterministic_validation_status"),
                    }
                ),
            ),
        )
        refresh_row_ids.append(refresh_event_id)

        prior_anchor_slice = prior_anchor_slices_by_edge.get(edge["edge_id"])
        if prior_anchor_slice:
            validate_prior_anchor_slice(prior_anchor_slice)
            conn.execute(
                """
                INSERT INTO related_market_prior_anchor_slices (
                  prior_anchor_slice_id, case_id, market_id, dispatch_id, edge_id,
                  upstream_market_id, upstream_probability_source, raw_upstream_probability,
                  adjusted_upstream_probability, upstream_probability_as_of, allowed_use,
                  conditional_model, upstream_prior_reliability_context,
                  dependence_adjustment, double_counting_risk, not_independent_evidence,
                  conditional_branch_group_id, anchor_dependency_contract_id,
                  graph_safety_slice_id, validation_status, reason_codes,
                  generated_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prior_anchor_slice_id) DO UPDATE SET
                  validation_status=excluded.validation_status,
                  reason_codes=excluded.reason_codes,
                  metadata=excluded.metadata
                """,
                (
                    prior_anchor_slice["prior_anchor_slice_id"],
                    prior_anchor_slice["case_id"],
                    str(prior_anchor_slice["market_id"]),
                    prior_anchor_slice["dispatch_id"],
                    prior_anchor_slice["edge_id"],
                    prior_anchor_slice.get("upstream_market_id"),
                    prior_anchor_slice.get("upstream_probability_source"),
                    prior_anchor_slice.get("raw_upstream_probability"),
                    prior_anchor_slice.get("adjusted_upstream_probability"),
                    prior_anchor_slice.get("upstream_probability_as_of"),
                    prior_anchor_slice["allowed_use"],
                    prior_anchor_slice.get("conditional_model"),
                    canonical_json(prior_anchor_slice.get("upstream_prior_reliability_context") or {}),
                    canonical_json(prior_anchor_slice.get("dependence_adjustment") or {}),
                    prior_anchor_slice["double_counting_risk"],
                    1 if prior_anchor_slice["not_independent_evidence"] else 0,
                    prior_anchor_slice.get("conditional_branch_group_id"),
                    prior_anchor_slice["anchor_dependency_contract_id"],
                    prior_anchor_slice.get("graph_safety_slice_id"),
                    prior_anchor_slice["validation_status"],
                    canonical_json(prior_anchor_slice["reason_codes"]),
                    generated_at,
                    canonical_json(prior_anchor_slice.get("metadata") or {}),
                ),
            )
            prior_anchor_row_ids.append(prior_anchor_slice["prior_anchor_slice_id"])

    model_assist_id = write_model_assist_provenance(conn, model_assist_provenance) if model_assist_provenance else None
    return {
        "candidate_set_id": enriched["candidate_set_id"],
        "candidate_row_ids": candidate_row_ids,
        "relationship_slice_ids": relationship_row_ids,
        "graph_safety_slice_ids": graph_row_ids,
        "refresh_event_ids": refresh_row_ids,
        "prior_anchor_slice_ids": prior_anchor_row_ids,
        "model_assist_id": model_assist_id,
        "context": enriched,
    }


def load_json_path(path: Path | None, default: Any) -> Any:
    if path is None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an ADS related live-market context artifact or waiver.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--evidence-packet-path", required=True, type=Path)
    parser.add_argument("--evidence-packet-ref", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--active-market-index-json", required=True, type=Path)
    parser.add_argument("--exposure-context-json", type=Path)
    parser.add_argument("--vector-candidates-json", type=Path)
    parser.add_argument("--vector-diagnostic-json", type=Path)
    parser.add_argument("--run-vector-runtime", action="store_true")
    parser.add_argument("--allow-vector-pull", action="store_true")
    parser.add_argument("--ollama-host")
    parser.add_argument("--model-assist-output-json", type=Path)
    parser.add_argument("--profile-context-ref")
    parser.add_argument("--candidate-cap", type=int, default=DEFAULT_AMRG_CANDIDATE_CAP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    evidence_packet = json.loads(args.evidence_packet_path.read_text(encoding="utf-8"))
    active_market_index = load_json_path(args.active_market_index_json, [])
    exposure_context = load_json_path(args.exposure_context_json, None)
    vector_candidates = load_json_path(args.vector_candidates_json, [])
    vector_diagnostic = load_json_path(args.vector_diagnostic_json, None)
    model_assist_output = load_json_path(args.model_assist_output_json, None)
    ollama_client = OllamaEmbeddingClient(args.ollama_host) if args.ollama_host else None
    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            result = materialize_related_live_market_context(
                conn,
                evidence_packet=evidence_packet,
                evidence_packet_ref=args.evidence_packet_ref,
                artifact_dir=args.artifact_dir,
                active_market_index=active_market_index,
                exposure_context=exposure_context,
                vector_candidates=vector_candidates,
                vector_source_diagnostics=vector_diagnostic,
                profile_context_ref=args.profile_context_ref,
                candidate_cap=args.candidate_cap,
                run_vector_runtime=args.run_vector_runtime,
                allow_vector_pull=args.allow_vector_pull,
                ollama_client=ollama_client,
                model_assist_output=model_assist_output,
            )
        print(canonical_json({k: v for k, v in result.items() if k not in {"artifact", "manifest"}}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
