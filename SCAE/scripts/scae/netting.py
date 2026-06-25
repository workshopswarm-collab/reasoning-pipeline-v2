"""SCAE-005/SCAE-006 candidate-only netting guards.

This module consumes bounded SCAE candidate update slices and emits
candidate-only cluster netting and cross-leaf dependence slices. It does not
apply branch sub-ledgers, final ledger aggregation, probability fields, or
forecast persistence.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from scae.policy import default_scae_policy


SCAE_CLUSTER_NETTING_SLICE_SCHEMA_VERSION = "scae-intra-leaf-cluster-netting-slice/v1"
SCAE_CLUSTER_NETTING_BUNDLE_SCHEMA_VERSION = "scae-intra-leaf-cluster-netting-bundle/v1"
SCAE_CLUSTER_NETTING_SUMMARY_SCHEMA_VERSION = "scae-intra-leaf-cluster-netting-summary/v1"
SCAE_CROSS_LEAF_DEPENDENCE_SLICE_SCHEMA_VERSION = "scae-cross-leaf-dependence-slice/v1"
SCAE_CROSS_LEAF_DEPENDENCE_BUNDLE_SCHEMA_VERSION = "scae-cross-leaf-dependence-bundle/v1"
SCAE_MECHANISM_FAMILY_DIAGNOSTIC_SCHEMA_VERSION = "scae-mechanism-family-dependence-diagnostic/v1"
SCAE_005_NETTING_VERSION = "ads-scae-005-intra-leaf-cluster-netting/v1"
SCAE_006_DEPENDENCE_VERSION = "ads-scae-006-cross-leaf-dependence-guard/v1"
NO_LIVE_AUTHORITY = "candidate_ledger_input_only_no_live_forecast_authority"
REPRESENTATIVE_SELECTOR = "policy_bounded_signed_representative_v1"
CROSS_LEAF_REPRESENTATIVE_SELECTOR = "shared_claim_union_signed_representative_v1"
AMBIGUOUS_CLAIM_FAMILY_UNION_ID = "ambiguous_claim_family_conservative_union"
AMBIGUOUS_CLAIM_FAMILY_VALUES = {
    "ambiguous",
    "ambiguous_claim_family",
    "unknown",
    "unknown_claim_family",
    "unknown_not_counted",
    "unresolved",
}
ACCEPTED_CLAIM_FAMILY_STATUSES = {
    "",
    "accepted",
    "claim_family_resolved",
    "deterministically_resolved",
    "known",
    "resolved",
}


class ScaeNettingError(ValueError):
    """Raised when SCAE-005 netting cannot safely continue."""


@dataclass(frozen=True)
class LeafClusterNettingResult:
    cluster_slices: list[dict[str, Any]]
    leaf_netting_summaries: list[dict[str, Any]]
    excluded_candidate_refs: list[str]
    zero_delta_candidate_refs: list[str]
    netting_bundle_digest: str


@dataclass(frozen=True)
class CrossLeafDependenceResult:
    cross_leaf_dependency_slices: list[dict[str, Any]]
    mechanism_family_diagnostics: list[dict[str, Any]]
    cross_leaf_summary: dict[str, Any]
    cross_leaf_dependence_bundle_digest: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _rows_from(value: Any, field_name: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        rows = value.get(field_name)
    else:
        rows = value
    if not isinstance(rows, list):
        raise ScaeNettingError(f"{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaeNettingError(f"{field_name} must contain objects")
        normalized.append(row)
    return normalized


def _numeric(value: Any, field_name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeNettingError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        try:
            number = float(str(value))
        except (TypeError, ValueError) as exc:
            raise ScaeNettingError(f"{field_name} must be numeric") from exc
    if not allow_zero and number <= 0.0:
        raise ScaeNettingError(f"{field_name} must be positive")
    return number


def _optional_non_negative(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    number = _numeric(value, "verified_quality_multiplier")
    if number < 0.0:
        raise ScaeNettingError("verified_quality_multiplier must be non-negative")
    return number


def _candidate_id(candidate: dict[str, Any]) -> str:
    for field in ("candidate_slice_id", "update_slice_id", "slice_id"):
        value = candidate.get(field)
        if _is_non_empty_string(value):
            return str(value)
    raise ScaeNettingError("candidate slice is missing candidate_slice_id")


def _cluster_id(cluster: dict[str, Any]) -> str:
    for field in ("cluster_slice_id", "cross_leaf_dependency_slice_id", "slice_id"):
        value = cluster.get(field)
        if _is_non_empty_string(value):
            return str(value)
    raise ScaeNettingError("cluster slice is missing cluster_slice_id")


def _cluster_identity(candidate: dict[str, Any]) -> tuple[str, str, str]:
    leaf_id = candidate.get("leaf_id")
    source_family_id = candidate.get("event_source_family") or candidate.get("source_family_id")
    claim_family_id = candidate.get("claim_family_id")
    if not _is_non_empty_string(leaf_id):
        raise ScaeNettingError(f"{_candidate_id(candidate)} is missing leaf_id")
    if not _is_non_empty_string(source_family_id):
        raise ScaeNettingError(f"{_candidate_id(candidate)} is missing source_family_id")
    if not _is_non_empty_string(claim_family_id):
        raise ScaeNettingError(f"{_candidate_id(candidate)} is missing claim_family_id")
    return str(leaf_id), str(source_family_id), str(claim_family_id)


def _candidate_mechanism_family_ids(candidate: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for field in (
        "mechanism_family_id",
        "absence_mechanism_family_id",
        "missingness_mechanism_family_id",
        "no_catalyst_mechanism_family_id",
    ):
        values.append(candidate.get(field))
    mechanism_family_ids = candidate.get("mechanism_family_ids")
    if isinstance(mechanism_family_ids, list):
        values.extend(mechanism_family_ids)
    normalized = [str(value) for value in values if _is_non_empty_string(value)]
    return sorted(set(normalized))


def _candidate_claim_family_status(candidate: dict[str, Any]) -> str:
    for field in (
        "claim_family_equivalence_status",
        "claim_family_resolution_status",
        "claim_family_status",
    ):
        value = candidate.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return "accepted"


def _claim_family_statuses(candidates: list[dict[str, Any]]) -> list[str]:
    return sorted({_candidate_claim_family_status(candidate) for candidate in candidates})


def _claim_family_is_ambiguous(claim_family_id: Any, statuses: list[str] | None = None) -> bool:
    if not _is_non_empty_string(claim_family_id):
        return True
    normalized_claim = str(claim_family_id).strip().lower()
    if normalized_claim in AMBIGUOUS_CLAIM_FAMILY_VALUES:
        return True
    for status in statuses or []:
        normalized_status = str(status).strip().lower()
        if normalized_status not in ACCEPTED_CLAIM_FAMILY_STATUSES:
            return True
    return False


def _signed_delta(candidate: dict[str, Any]) -> float:
    return round(_numeric(candidate.get("signed_log_odds_delta"), "signed_log_odds_delta"), 9)


def _accepted_force_candidate(candidate: dict[str, Any]) -> bool:
    if candidate.get("accepted_for_ledger_input") is not True:
        return False
    return _signed_delta(candidate) != 0.0


def _representative_key(candidate: dict[str, Any]) -> tuple[float, float, str]:
    """Policy selector key: quality first, then bounded force, then stable ID."""

    return (
        _optional_non_negative(candidate.get("verified_quality_multiplier")),
        abs(_signed_delta(candidate)),
        _candidate_id(candidate),
    )


def _select_representative(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(candidates, key=_representative_key)


def _cap_signed_delta(value: float, cap: float) -> tuple[float, bool]:
    bounded = max(-cap, min(cap, value))
    return round(bounded, 9), bounded != value


def _source_class_cap(candidate: dict[str, Any] | None, source_class_caps: dict[str, Any]) -> float | None:
    if candidate is None:
        return None
    source_class = candidate.get("source_class")
    if _is_non_empty_string(source_class) and source_class in source_class_caps:
        return _numeric(source_class_caps[str(source_class)], f"source_class_log_odds_caps.{source_class}", allow_zero=False)
    if "*" in source_class_caps:
        return _numeric(source_class_caps["*"], "source_class_log_odds_caps.*", allow_zero=False)
    return None


def _apply_optional_cap(value: float, cap: float | None) -> tuple[float, bool]:
    if cap is None:
        return value, False
    return _cap_signed_delta(value, cap)


def _leaf_summary(cluster_slices: list[dict[str, Any]], leaf_id: str) -> dict[str, Any]:
    leaf_clusters = [cluster for cluster in cluster_slices if cluster["leaf_id"] == leaf_id]
    candidate_delta = round(sum(cluster["netted_signed_log_odds_delta"] for cluster in leaf_clusters), 9)
    representative_refs: list[str] = []
    for cluster in leaf_clusters:
        representative_refs.extend(cluster["posterior_force_inputs"]["representative_candidate_refs"])
    summary = {
        "artifact_type": "scae_intra_leaf_cluster_netting_summary",
        "schema_version": SCAE_CLUSTER_NETTING_SUMMARY_SCHEMA_VERSION,
        "feature_id": "SCAE-005",
        "leaf_id": leaf_id,
        "case_id": leaf_clusters[0].get("case_id") if leaf_clusters else None,
        "dispatch_id": leaf_clusters[0].get("dispatch_id") if leaf_clusters else None,
        "cluster_slice_refs": [cluster["cluster_slice_id"] for cluster in leaf_clusters],
        "representative_candidate_refs": representative_refs,
        "candidate_leaf_net_log_odds_delta": candidate_delta,
        "cluster_count": len(leaf_clusters),
        "ledger_input_authority": NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
    }
    summary["summary_id"] = _sha_id("scae-leaf-netting-summary", summary)
    summary["summary_digest"] = _prefixed_sha256(summary)
    return summary


def _cluster_slice(
    cluster_key: tuple[str, str, str],
    candidates: list[dict[str, Any]],
    *,
    per_cluster_cap: float,
    representative_selector: str,
    source_class_caps: dict[str, Any],
) -> dict[str, Any]:
    leaf_id, source_family_id, claim_family_id = cluster_key
    sorted_candidates = sorted(candidates, key=_candidate_id)
    positive_candidates = [candidate for candidate in sorted_candidates if _signed_delta(candidate) > 0.0]
    negative_candidates = [candidate for candidate in sorted_candidates if _signed_delta(candidate) < 0.0]
    positive_representative = _select_representative(positive_candidates)
    negative_representative = _select_representative(negative_candidates)

    positive_pre_source_cap_delta = _signed_delta(positive_representative) if positive_representative else 0.0
    negative_pre_source_cap_delta = _signed_delta(negative_representative) if negative_representative else 0.0
    positive_source_class_cap = _source_class_cap(positive_representative, source_class_caps)
    negative_source_class_cap = _source_class_cap(negative_representative, source_class_caps)
    positive_delta, positive_bounded_by_source_cap = _apply_optional_cap(
        positive_pre_source_cap_delta,
        positive_source_class_cap,
    )
    negative_delta, negative_bounded_by_source_cap = _apply_optional_cap(
        negative_pre_source_cap_delta,
        negative_source_class_cap,
    )
    pre_cap_delta = round(positive_delta + negative_delta, 9)
    netted_delta, bounded_by_cap = _cap_signed_delta(pre_cap_delta, per_cluster_cap)
    candidate_refs = [_candidate_id(candidate) for candidate in sorted_candidates]
    positive_refs = [_candidate_id(candidate) for candidate in positive_candidates]
    negative_refs = [_candidate_id(candidate) for candidate in negative_candidates]
    representative_refs = [
        _candidate_id(candidate)
        for candidate in [positive_representative, negative_representative]
        if candidate is not None
    ]
    mechanism_family_ids = sorted(
        {
            mechanism_family_id
            for candidate in sorted_candidates
            for mechanism_family_id in _candidate_mechanism_family_ids(candidate)
        }
    )
    claim_family_statuses = _claim_family_statuses(sorted_candidates)
    ambiguous_claim_family = _claim_family_is_ambiguous(claim_family_id, claim_family_statuses)
    positive_corroborating_refs = [
        ref for ref in positive_refs if positive_representative is not None and ref != _candidate_id(positive_representative)
    ]
    negative_corroborating_refs = [
        ref for ref in negative_refs if negative_representative is not None and ref != _candidate_id(negative_representative)
    ]

    cluster = {
        "artifact_type": "scae_intra_leaf_cluster_netting_slice",
        "schema_version": SCAE_CLUSTER_NETTING_SLICE_SCHEMA_VERSION,
        "feature_id": "SCAE-005",
        "surface_name": "scae_log_odds_update_slices",
        "case_id": sorted_candidates[0].get("case_id"),
        "dispatch_id": sorted_candidates[0].get("dispatch_id"),
        "leaf_id": leaf_id,
        "source_family_id": source_family_id,
        "claim_family_id": claim_family_id,
        "claim_family_statuses": claim_family_statuses,
        "claim_family_ambiguity_status": (
            "ambiguous_or_unresolved_conservative" if ambiguous_claim_family else "resolved"
        ),
        "mechanism_family_ids": mechanism_family_ids,
        "cluster_key": {
            "leaf_id": leaf_id,
            "source_family_id": source_family_id,
            "claim_family_id": claim_family_id,
        },
        "candidate_slice_refs": candidate_refs,
        "candidate_count": len(candidate_refs),
        "representative_selector": representative_selector,
        "positive_representative_candidate_ref": (
            _candidate_id(positive_representative) if positive_representative else None
        ),
        "positive_representative_pre_source_cap_signed_log_odds_delta": positive_pre_source_cap_delta,
        "positive_source_class_log_odds_cap": positive_source_class_cap,
        "positive_representative_signed_log_odds_delta": positive_delta,
        "negative_representative_candidate_ref": (
            _candidate_id(negative_representative) if negative_representative else None
        ),
        "negative_representative_pre_source_cap_signed_log_odds_delta": negative_pre_source_cap_delta,
        "negative_source_class_log_odds_cap": negative_source_class_cap,
        "negative_representative_signed_log_odds_delta": negative_delta,
        "posterior_force_inputs": {
            "representative_candidate_refs": representative_refs,
            "positive_representative_delta": positive_delta,
            "negative_representative_delta": negative_delta,
            "non_representative_candidate_refs_excluded_from_force": sorted(
                set(candidate_refs) - set(representative_refs)
            ),
        },
        "corroboration_metadata": {
            "separated_from_posterior_force": True,
            "positive_candidate_refs": positive_refs,
            "negative_candidate_refs": negative_refs,
            "positive_corroborating_candidate_refs": positive_corroborating_refs,
            "negative_corroborating_candidate_refs": negative_corroborating_refs,
            "same_claim_source_family_repeat_count": max(0, len(candidate_refs) - len(representative_refs)),
        },
        "contradiction_metadata": {
            "separated_from_posterior_force": True,
            "has_positive_and_negative_representatives": positive_representative is not None
            and negative_representative is not None,
            "positive_candidate_refs": positive_refs,
            "negative_candidate_refs": negative_refs,
        },
        "mechanism_family_diagnostics": {
            "diagnostic_dependence_only": True,
            "can_increase_evidence_strength": False,
            "mechanism_family_ids": mechanism_family_ids,
            "signed_log_odds_delta_added_by_mechanism_family": 0.0,
        },
        "pre_cap_cluster_signed_log_odds_delta": pre_cap_delta,
        "per_cluster_log_odds_cap": per_cluster_cap,
        "netted_signed_log_odds_delta": netted_delta,
        "bounded_by_source_class_cap": positive_bounded_by_source_cap or negative_bounded_by_source_cap,
        "bounded_by_cluster_cap": bounded_by_cap,
        "cap_application_scope": "candidate_ledger_input_only",
        "accepted_for_ledger_input": True,
        "ledger_input_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "not_implemented_scope": [
            "SCAE-006_cross_leaf_dependence",
            "SCAE-007_branch_sub_ledgers",
            "SCAE-011_final_probability_fields",
        ],
        "netting_version": SCAE_005_NETTING_VERSION,
    }
    cluster["cluster_slice_id"] = _sha_id("scae-cluster-netting", cluster)
    cluster["cluster_slice_digest"] = _prefixed_sha256(cluster)
    return cluster


def build_leaf_cluster_netting_slices(
    candidate_slices: dict[str, Any] | list[dict[str, Any]],
    *,
    policy: dict[str, Any] | None = None,
) -> LeafClusterNettingResult:
    """Build candidate-only SCAE-005 intra-leaf cluster netting slices."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    cap_stack = active_policy.get("cap_stack")
    if not isinstance(cap_stack, dict):
        raise ScaeNettingError("policy.cap_stack is required")
    representative_selector = cap_stack.get("representative_selector")
    if representative_selector != REPRESENTATIVE_SELECTOR:
        raise ScaeNettingError(f"unsupported representative_selector {representative_selector!r}")
    per_cluster_cap = _numeric(cap_stack.get("per_cluster_log_odds_cap"), "per_cluster_log_odds_cap", allow_zero=False)
    source_class_caps = cap_stack.get("source_class_log_odds_caps") or {}
    if not isinstance(source_class_caps, dict):
        raise ScaeNettingError("source_class_log_odds_caps must be an object")

    rows = _rows_from(candidate_slices, "candidate_slices")
    clusters: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    excluded_candidate_refs: list[str] = []
    zero_delta_candidate_refs: list[str] = []
    for candidate in rows:
        candidate_copy = copy.deepcopy(candidate)
        if candidate_copy.get("accepted_for_ledger_input") is True and _signed_delta(candidate_copy) == 0.0:
            zero_delta_candidate_refs.append(_candidate_id(candidate_copy))
            continue
        if not _accepted_force_candidate(candidate_copy):
            excluded_candidate_refs.append(_candidate_id(candidate_copy))
            continue
        clusters.setdefault(_cluster_identity(candidate_copy), []).append(candidate_copy)

    cluster_slices = [
        _cluster_slice(
            cluster_key,
            updates,
            per_cluster_cap=per_cluster_cap,
            representative_selector=representative_selector,
            source_class_caps=source_class_caps,
        )
        for cluster_key, updates in sorted(clusters.items())
    ]
    leaf_netting_summaries = [_leaf_summary(cluster_slices, leaf_id) for leaf_id in sorted({key[0] for key in clusters})]
    digest_payload = {
        "schema_version": "scae-intra-leaf-cluster-netting-digest/v1",
        "cluster_slice_schema_version": SCAE_CLUSTER_NETTING_SLICE_SCHEMA_VERSION,
        "summary_schema_version": SCAE_CLUSTER_NETTING_SUMMARY_SCHEMA_VERSION,
        "cluster_slices": cluster_slices,
        "leaf_netting_summaries": leaf_netting_summaries,
        "excluded_candidate_refs": sorted(excluded_candidate_refs),
        "zero_delta_candidate_refs": sorted(zero_delta_candidate_refs),
    }
    bundle_digest = _prefixed_sha256(digest_payload)
    for cluster in cluster_slices:
        cluster["netting_bundle_digest"] = bundle_digest
    for summary in leaf_netting_summaries:
        summary["netting_bundle_digest"] = bundle_digest
    return LeafClusterNettingResult(
        cluster_slices,
        leaf_netting_summaries,
        sorted(excluded_candidate_refs),
        sorted(zero_delta_candidate_refs),
        bundle_digest,
    )


def build_leaf_cluster_netting_bundle(
    candidate_slices: dict[str, Any] | list[dict[str, Any]],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the external SCAE-005 intra-leaf netting bundle artifact."""

    result = build_leaf_cluster_netting_slices(candidate_slices, policy=policy)
    return {
        "artifact_type": "scae_intra_leaf_cluster_netting_bundle",
        "schema_version": SCAE_CLUSTER_NETTING_BUNDLE_SCHEMA_VERSION,
        "feature_id": "SCAE-005",
        "authority": NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "netting_bundle_digest": result.netting_bundle_digest,
        "cluster_count": len(result.cluster_slices),
        "leaf_count": len(result.leaf_netting_summaries),
        "excluded_candidate_refs": result.excluded_candidate_refs,
        "zero_delta_candidate_refs": result.zero_delta_candidate_refs,
        "cluster_slices": result.cluster_slices,
        "leaf_netting_summaries": result.leaf_netting_summaries,
        "netting_version": SCAE_005_NETTING_VERSION,
    }


def _cluster_delta(cluster: dict[str, Any]) -> float:
    return round(_numeric(cluster.get("netted_signed_log_odds_delta"), "netted_signed_log_odds_delta"), 9)


def _cluster_source_family_id(cluster: dict[str, Any]) -> str:
    source_family_id = cluster.get("source_family_id") or cluster.get("event_source_family")
    if not _is_non_empty_string(source_family_id):
        raise ScaeNettingError(f"{_cluster_id(cluster)} is missing source_family_id")
    return str(source_family_id)


def _cluster_claim_family_id(cluster: dict[str, Any]) -> str:
    claim_family_id = cluster.get("claim_family_id")
    if not _is_non_empty_string(claim_family_id):
        raise ScaeNettingError(f"{_cluster_id(cluster)} is missing claim_family_id")
    return str(claim_family_id)


def _cluster_leaf_id(cluster: dict[str, Any]) -> str:
    leaf_id = cluster.get("leaf_id")
    if not _is_non_empty_string(leaf_id):
        raise ScaeNettingError(f"{_cluster_id(cluster)} is missing leaf_id")
    return str(leaf_id)


def _cluster_mechanism_family_ids(cluster: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for field in (
        "mechanism_family_id",
        "absence_mechanism_family_id",
        "missingness_mechanism_family_id",
        "no_catalyst_mechanism_family_id",
    ):
        values.append(cluster.get(field))
    mechanism_family_ids = cluster.get("mechanism_family_ids")
    if isinstance(mechanism_family_ids, list):
        values.extend(mechanism_family_ids)
    return sorted({str(value) for value in values if _is_non_empty_string(value)})


def _cluster_claim_family_statuses(cluster: dict[str, Any]) -> list[str]:
    statuses = cluster.get("claim_family_statuses")
    if isinstance(statuses, list):
        return sorted({str(status) for status in statuses if _is_non_empty_string(status)})
    status = None
    for field in (
        "claim_family_equivalence_status",
        "claim_family_resolution_status",
        "claim_family_status",
        "claim_family_ambiguity_status",
    ):
        if _is_non_empty_string(cluster.get(field)):
            status = str(cluster[field])
            break
    return [status] if status else ["accepted"]


def _cross_leaf_group_key(cluster: dict[str, Any]) -> tuple[str, str]:
    claim_family_id = _cluster_claim_family_id(cluster)
    statuses = _cluster_claim_family_statuses(cluster)
    if _claim_family_is_ambiguous(claim_family_id, statuses):
        return "ambiguous_claim_family", AMBIGUOUS_CLAIM_FAMILY_UNION_ID
    return "resolved_claim_family", claim_family_id


def _cross_leaf_representative_key(cluster: dict[str, Any]) -> tuple[float, str]:
    return abs(_cluster_delta(cluster)), _cluster_id(cluster)


def _select_cluster_representative(clusters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not clusters:
        return None
    return max(clusters, key=_cross_leaf_representative_key)


def _cross_leaf_dependence_slice(group_key: tuple[str, str], clusters: list[dict[str, Any]]) -> dict[str, Any]:
    group_type, group_id = group_key
    sorted_clusters = sorted((copy.deepcopy(cluster) for cluster in clusters), key=_cluster_id)
    positive_clusters = [cluster for cluster in sorted_clusters if _cluster_delta(cluster) > 0.0]
    negative_clusters = [cluster for cluster in sorted_clusters if _cluster_delta(cluster) < 0.0]
    positive_representative = _select_cluster_representative(positive_clusters)
    negative_representative = _select_cluster_representative(negative_clusters)
    representative_refs = [
        _cluster_id(cluster)
        for cluster in [positive_representative, negative_representative]
        if cluster is not None
    ]
    cluster_refs = [_cluster_id(cluster) for cluster in sorted_clusters]
    excluded_refs = sorted(set(cluster_refs) - set(representative_refs))
    source_family_ids = sorted({_cluster_source_family_id(cluster) for cluster in sorted_clusters})
    leaf_ids = sorted({_cluster_leaf_id(cluster) for cluster in sorted_clusters})
    claim_family_ids = sorted({_cluster_claim_family_id(cluster) for cluster in sorted_clusters})
    mechanism_family_ids = sorted(
        {
            mechanism_family_id
            for cluster in sorted_clusters
            for mechanism_family_id in _cluster_mechanism_family_ids(cluster)
        }
    )
    positive_delta = _cluster_delta(positive_representative) if positive_representative else 0.0
    negative_delta = _cluster_delta(negative_representative) if negative_representative else 0.0
    raw_additive_delta = round(sum(_cluster_delta(cluster) for cluster in sorted_clusters), 9)
    guarded_delta = round(positive_delta + negative_delta, 9)
    prevented_duplicate_delta = round(raw_additive_delta - guarded_delta, 9)
    ambiguous_claim_family = group_type == "ambiguous_claim_family"
    cross_leaf_reuse = len(leaf_ids) > 1
    slice_row = {
        "artifact_type": "scae_cross_leaf_dependence_slice",
        "schema_version": SCAE_CROSS_LEAF_DEPENDENCE_SLICE_SCHEMA_VERSION,
        "feature_id": "SCAE-006",
        "surface_name": "scae_cross_leaf_dependency_slices",
        "case_id": sorted_clusters[0].get("case_id"),
        "dispatch_id": sorted_clusters[0].get("dispatch_id"),
        "dependence_group_type": group_type,
        "dependence_group_id": group_id,
        "claim_family_ids": claim_family_ids,
        "source_family_ids": source_family_ids,
        "mechanism_family_ids": mechanism_family_ids,
        "leaf_ids": leaf_ids,
        "cluster_slice_refs": cluster_refs,
        "cluster_count": len(cluster_refs),
        "cross_leaf_representative_selector": CROSS_LEAF_REPRESENTATIVE_SELECTOR,
        "positive_representative_cluster_ref": (
            _cluster_id(positive_representative) if positive_representative else None
        ),
        "negative_representative_cluster_ref": (
            _cluster_id(negative_representative) if negative_representative else None
        ),
        "posterior_force_inputs": {
            "representative_cluster_refs": representative_refs,
            "positive_representative_delta": positive_delta,
            "negative_representative_delta": negative_delta,
            "non_representative_cluster_refs_excluded_from_force": excluded_refs,
        },
        "raw_additive_signed_log_odds_delta": raw_additive_delta,
        "cross_leaf_guarded_signed_log_odds_delta": guarded_delta,
        "prevented_duplicate_or_dependent_signed_log_odds_delta": prevented_duplicate_delta,
        "same_claim_union_applied": group_type == "resolved_claim_family" and cross_leaf_reuse,
        "ambiguous_claim_family_conservative_union_applied": ambiguous_claim_family,
        "independent_corroboration_status": (
            "blocked_ambiguous_claim_family"
            if ambiguous_claim_family
            else ("shared_claim_union" if cross_leaf_reuse else "single_leaf_no_cross_leaf_reuse")
        ),
        "source_family_diagnostics": {
            "source_family_ids": source_family_ids,
            "same_source_family_across_leaves": cross_leaf_reuse and len(source_family_ids) < len(leaf_ids),
            "separated_from_independent_corroboration": True,
        },
        "mechanism_family_diagnostics": {
            "diagnostic_dependence_only": True,
            "can_increase_evidence_strength": False,
            "mechanism_family_ids": mechanism_family_ids,
            "signed_log_odds_delta_added_by_mechanism_family": 0.0,
        },
        "accepted_for_candidate_ledger_input": True,
        "ledger_input_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "not_implemented_scope": [
            "SCAE-007_branch_sub_ledgers",
            "SCAE-011_final_probability_fields",
        ],
        "dependence_version": SCAE_006_DEPENDENCE_VERSION,
    }
    slice_row["cross_leaf_dependency_slice_id"] = _sha_id("scae-cross-leaf-dependence", slice_row)
    slice_row["cross_leaf_dependency_slice_digest"] = _prefixed_sha256(slice_row)
    return slice_row


def _mechanism_family_diagnostics(cluster_slices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_mechanism: dict[str, list[dict[str, Any]]] = {}
    for cluster in cluster_slices:
        for mechanism_family_id in _cluster_mechanism_family_ids(cluster):
            by_mechanism.setdefault(mechanism_family_id, []).append(cluster)

    diagnostics: list[dict[str, Any]] = []
    for mechanism_family_id, clusters in sorted(by_mechanism.items()):
        sorted_clusters = sorted(clusters, key=_cluster_id)
        diagnostic = {
            "artifact_type": "scae_mechanism_family_dependence_diagnostic",
            "schema_version": SCAE_MECHANISM_FAMILY_DIAGNOSTIC_SCHEMA_VERSION,
            "feature_id": "SCAE-006",
            "surface_name": "scae_mechanism_family_assignment_slices",
            "mechanism_family_id": mechanism_family_id,
            "cluster_slice_refs": [_cluster_id(cluster) for cluster in sorted_clusters],
            "leaf_ids": sorted({_cluster_leaf_id(cluster) for cluster in sorted_clusters}),
            "claim_family_ids": sorted({_cluster_claim_family_id(cluster) for cluster in sorted_clusters}),
            "diagnostic_dependence_only": True,
            "can_increase_evidence_strength": False,
            "signed_log_odds_delta_added_by_mechanism_family": 0.0,
            "downstream_effect_scope": "dependence_or_interval_only",
            "ledger_input_authority": NO_LIVE_AUTHORITY,
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
        }
        diagnostic["mechanism_family_diagnostic_id"] = _sha_id("scae-mechanism-family-diagnostic", diagnostic)
        diagnostic["mechanism_family_diagnostic_digest"] = _prefixed_sha256(diagnostic)
        diagnostics.append(diagnostic)
    return diagnostics


def _cross_leaf_summary(cross_leaf_slices: list[dict[str, Any]]) -> dict[str, Any]:
    raw_additive_delta = round(sum(slice_row["raw_additive_signed_log_odds_delta"] for slice_row in cross_leaf_slices), 9)
    guarded_delta = round(
        sum(slice_row["cross_leaf_guarded_signed_log_odds_delta"] for slice_row in cross_leaf_slices),
        9,
    )
    summary = {
        "artifact_type": "scae_cross_leaf_dependence_summary",
        "schema_version": "scae-cross-leaf-dependence-summary/v1",
        "feature_id": "SCAE-006",
        "dependence_slice_refs": [
            slice_row["cross_leaf_dependency_slice_id"] for slice_row in cross_leaf_slices
        ],
        "raw_additive_signed_log_odds_delta": raw_additive_delta,
        "cross_leaf_guarded_signed_log_odds_delta": guarded_delta,
        "prevented_duplicate_or_dependent_signed_log_odds_delta": round(raw_additive_delta - guarded_delta, 9),
        "ambiguous_claim_family_group_count": sum(
            1 for slice_row in cross_leaf_slices if slice_row["dependence_group_type"] == "ambiguous_claim_family"
        ),
        "same_claim_union_group_count": sum(
            1 for slice_row in cross_leaf_slices if slice_row["same_claim_union_applied"]
        ),
        "ledger_input_authority": NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
    }
    summary["summary_id"] = _sha_id("scae-cross-leaf-summary", summary)
    summary["summary_digest"] = _prefixed_sha256(summary)
    return summary


def build_cross_leaf_dependence_slices(
    cluster_netting_slices: dict[str, Any] | list[dict[str, Any]],
) -> CrossLeafDependenceResult:
    """Build candidate-only SCAE-006 cross-leaf dependence slices."""

    rows = _rows_from(cluster_netting_slices, "cluster_slices")
    accepted_clusters: list[dict[str, Any]] = []
    for cluster in rows:
        cluster_copy = copy.deepcopy(cluster)
        if cluster_copy.get("accepted_for_ledger_input") is not True:
            continue
        if _cluster_delta(cluster_copy) == 0.0:
            continue
        _cluster_leaf_id(cluster_copy)
        _cluster_source_family_id(cluster_copy)
        _cluster_claim_family_id(cluster_copy)
        accepted_clusters.append(cluster_copy)

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cluster in accepted_clusters:
        groups.setdefault(_cross_leaf_group_key(cluster), []).append(cluster)

    cross_leaf_slices = [
        _cross_leaf_dependence_slice(group_key, clusters)
        for group_key, clusters in sorted(groups.items())
    ]
    mechanism_diagnostics = _mechanism_family_diagnostics(accepted_clusters)
    summary = _cross_leaf_summary(cross_leaf_slices)
    digest_payload = {
        "schema_version": "scae-cross-leaf-dependence-digest/v1",
        "slice_schema_version": SCAE_CROSS_LEAF_DEPENDENCE_SLICE_SCHEMA_VERSION,
        "diagnostic_schema_version": SCAE_MECHANISM_FAMILY_DIAGNOSTIC_SCHEMA_VERSION,
        "cross_leaf_dependency_slices": cross_leaf_slices,
        "mechanism_family_diagnostics": mechanism_diagnostics,
        "cross_leaf_summary": summary,
    }
    bundle_digest = _prefixed_sha256(digest_payload)
    for slice_row in cross_leaf_slices:
        slice_row["cross_leaf_dependence_bundle_digest"] = bundle_digest
    for diagnostic in mechanism_diagnostics:
        diagnostic["cross_leaf_dependence_bundle_digest"] = bundle_digest
    summary["cross_leaf_dependence_bundle_digest"] = bundle_digest
    return CrossLeafDependenceResult(
        cross_leaf_slices,
        mechanism_diagnostics,
        summary,
        bundle_digest,
    )


def build_cross_leaf_dependence_bundle(
    cluster_netting_slices: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the external SCAE-006 cross-leaf dependence bundle artifact."""

    result = build_cross_leaf_dependence_slices(cluster_netting_slices)
    return {
        "artifact_type": "scae_cross_leaf_dependence_bundle",
        "schema_version": SCAE_CROSS_LEAF_DEPENDENCE_BUNDLE_SCHEMA_VERSION,
        "feature_id": "SCAE-006",
        "authority": NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "cross_leaf_dependence_bundle_digest": result.cross_leaf_dependence_bundle_digest,
        "dependence_group_count": len(result.cross_leaf_dependency_slices),
        "mechanism_family_diagnostic_count": len(result.mechanism_family_diagnostics),
        "cross_leaf_dependency_slices": result.cross_leaf_dependency_slices,
        "mechanism_family_diagnostics": result.mechanism_family_diagnostics,
        "cross_leaf_summary": result.cross_leaf_summary,
        "dependence_version": SCAE_006_DEPENDENCE_VERSION,
    }
