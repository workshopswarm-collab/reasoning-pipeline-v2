"""ADS v2 AMRG helper contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
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
RELATED_LIVE_MARKET_CONTEXT_ARTIFACT_TYPE = "related-live-market-context"
NO_RELATED_CONTEXT_WAIVER_ARTIFACT_TYPE = "no-related-context-waiver"
AMRG_VECTOR_LANE_ID = "amrg_vector_embedding"
AMRG_VECTOR_MODEL_ID = "BAAI/bge-base-en-v1.5"
AMRG_VECTOR_ROUTE_ID = "ollama/local"
AMRG_VECTOR_PROVIDER = "ollama"
AMRG_VECTOR_EMBEDDING_DIMENSION = 768
AMRG_VECTOR_SIMILARITY_METRIC = "cosine"
AMRG_VECTOR_CANDIDATE_SOURCE = "local_bge_vector_neighbor"
AMRG_STAGE = "amrg"
AMRG_PRODUCER = "session-02-amrg"
DEFAULT_AMRG_CANDIDATE_CAP = 8
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


def ensure_no_raw_amrg_fields(value: Any, path: str = "amrg_artifact") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in AMRG_FORBIDDEN_ARTIFACT_KEYS:
                raise AMRGError(f"{path}.{key} must not store raw, outcome, replay, or scoring content")
            ensure_no_raw_amrg_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_raw_amrg_fields(child, f"{path}[{idx}]")


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
        "allowed_effects": ["decomposition_context_hint"],
        "forbidden_effects": [
            "probability_authority",
            "scae_delta",
            "prior_anchor",
            "relationship_promotion",
            "retrieval_sufficiency",
        ],
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
        "dispatch_id": evidence_packet["dispatch_id"],
        "forecast_timestamp": evidence_packet["forecast_timestamp"],
        "source_cutoff_timestamp": evidence_packet["source_cutoff_timestamp"],
        "evidence_packet_ref": evidence_packet_ref,
        "profile_context_ref": profile_context_ref,
        **pool,
    }
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
        return waiver
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
    return context


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
        if edge.get("schema_version") != AMRG_WEAK_EDGE_SCHEMA_VERSION:
            raise AMRGError(f"edge schema_version must be {AMRG_WEAK_EDGE_SCHEMA_VERSION}")
        if edge.get("candidate_id") not in candidate_ids:
            raise AMRGError("edge references unknown candidate")
        if edge.get("relationship_status") != WEAK_CONTEXT_ONLY:
            raise AMRGError("Phase 6 relationship edges must be weak_context_only")
        if "probability_authority" not in edge.get("forbidden_effects", []):
            raise AMRGError("weak edge must forbid probability authority")


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
) -> dict[str, Any]:
    artifact = build_related_live_market_context_or_waiver(
        evidence_packet=evidence_packet,
        evidence_packet_ref=evidence_packet_ref,
        active_market_index=active_market_index,
        exposure_context=exposure_context,
        vector_candidates=vector_candidates,
        vector_source_diagnostics=vector_source_diagnostics,
        profile_context_ref=profile_context_ref,
        candidate_cap=candidate_cap,
    )
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
            )
        print(canonical_json({k: v for k, v in result.items() if k not in {"artifact", "manifest"}}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
