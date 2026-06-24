"""ADS v2 AMRG helper contracts.

Phase 5 covers only the local vector candidate source. Deterministic AMRG
candidate pools, relationship validation, and waiver artifacts are owned by
later AMRG phases.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predquant.ads_case_contract import parse_timestamp
from predquant.ads_handoff import canonical_json
from predquant.tuning_profile import MODEL_LANE_POLICY_PATH, load_model_lane_policy


AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION = "amrg-market-vector-descriptor/v1"
AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION = "amrg-vector-index-snapshot/v1"
AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION = "amrg-vector-neighbor-candidate/v1"
AMRG_VECTOR_DIAGNOSTIC_SCHEMA_VERSION = "amrg-vector-candidate-source-diagnostic/v1"
AMRG_VECTOR_LANE_ID = "amrg_vector_embedding"
AMRG_VECTOR_MODEL_ID = "BAAI/bge-base-en-v1.5"
AMRG_VECTOR_ROUTE_ID = "ollama/local"
AMRG_VECTOR_PROVIDER = "ollama"
AMRG_VECTOR_EMBEDDING_DIMENSION = 768
AMRG_VECTOR_SIMILARITY_METRIC = "cosine"
AMRG_VECTOR_CANDIDATE_SOURCE = "local_bge_vector_neighbor"
WEAK_CONTEXT_ONLY = "weak_context_only"
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


class AMRGError(ValueError):
    """Raised when an AMRG vector-source contract is unsafe or malformed."""


@dataclass(frozen=True)
class PullResult:
    ok: bool
    reason: str | None = None


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


def build_unavailable_vector_source_diagnostic(reason: str, *, source_cutoff_timestamp: str | None) -> dict[str, Any]:
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
    }
    return diagnostic


def build_vector_index_snapshot(
    descriptors: list[dict[str, Any]],
    *,
    status: str,
    unavailable_reason: str | None = None,
    source_cutoff_timestamp: str,
    model_policy_ref: str = "plans/autonomous-decomposition-swarm-model-lane-policy.json",
    embedding_model_sha256: str = "sha256:unavailable",
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
) -> dict[str, Any]:
    for descriptor in descriptors:
        validate_active_market_descriptor(descriptor)
        embedding = embeddings_by_descriptor_sha256.get(descriptor["descriptor_sha256"])
        if embedding is None:
            raise AMRGError("missing embedding for descriptor")
        if len(embedding) != AMRG_VECTOR_EMBEDDING_DIMENSION:
            raise AMRGError("embedding dimension must be 768")
    return build_vector_index_snapshot(
        descriptors,
        status="ready",
        source_cutoff_timestamp=source_cutoff_timestamp,
        embedding_model_sha256=embedding_model_sha256,
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
