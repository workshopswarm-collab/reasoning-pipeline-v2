"""ADS v2 evidence packet construction and validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from predquant.ads_case_contract import (
    CaseContractError,
    parse_timestamp,
    validate_ads_case_contract,
)
from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    canonical_json,
    validate_artifact_manifest,
    write_artifact_manifest,
)


EVIDENCE_PACKET_SCHEMA_VERSION = "evidence-packet/v2"
EVIDENCE_PACKET_ARTIFACT_TYPE = "evidence-packet-v2"
PRIOR_RELIABILITY_INPUT_SCHEMA_VERSION = "prior-reliability-inputs/v1"
SOURCE_OF_TRUTH_STATUSES = {"clear", "ambiguous", "unknown"}
CONTRACT_STRUCTURES = {"binary", "family_aware_binary_child", "other"}
FAMILY_MODES = {"standalone_binary", "family_aware_binary_child", "unknown"}
DEFAULT_PRIOR_RELIABILITY_POLICY = {
    "fresh_snapshot_seconds": 300.0,
    "stale_snapshot_seconds": 900.0,
    "spread_warning_threshold": 0.15,
    "liquid_volume_threshold": 100.0,
    "liquid_open_interest_threshold": 100.0,
}
FORBIDDEN_PRIOR_RELIABILITY_KEYS = {
    "posterior_probability",
    "production_forecast_prob",
    "fair_value_probability",
    "scae_probability",
    "prior_reliability",
    "prior_reliability_score",
    "reliability_score",
    "final_reliability",
    "final_reliability_downgrade",
}


class EvidencePacketError(ValueError):
    """Raised when an evidence packet is malformed or cannot be built safely."""


def ensure_no_raw_payload_fields(value: Any, path: str = "packet") -> None:
    forbidden = {"raw_payload", "payload", "raw_content", "content", "body", "html", "page_text"}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise EvidencePacketError(f"{path}.{key} must not duplicate raw payload content")
            ensure_no_raw_payload_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_raw_payload_fields(child, f"{path}[{idx}]")


def snapshot_value(snapshot: sqlite3.Row | dict[str, Any] | None, key: str) -> Any:
    if snapshot is None:
        return None
    if isinstance(snapshot, sqlite3.Row):
        return snapshot[key] if key in snapshot.keys() else None
    return snapshot.get(key)


def numeric_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def optional_normalized_timestamp(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    return parse_timestamp(str(value), field).isoformat()


def seconds_between(later: str, earlier: str, field: str) -> float:
    return (parse_timestamp(later, "later_timestamp") - parse_timestamp(earlier, field)).total_seconds()


def arithmetic_average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def time_weighted_average(observations: list[dict[str, Any]], field: str, forecast_timestamp: str) -> float | None:
    values = [obs for obs in observations if obs.get(field) is not None]
    if not values:
        return None
    if len(values) == 1:
        return values[0][field]
    if any(not obs.get("observed_at") for obs in values):
        return arithmetic_average([obs[field] for obs in values])

    forecast_at = parse_timestamp(forecast_timestamp, "forecast_timestamp")
    sorted_values = sorted(values, key=lambda obs: parse_timestamp(obs["observed_at"], "quote_observed_at"))
    weighted_sum = 0.0
    total_seconds = 0.0
    for idx, obs in enumerate(sorted_values):
        start = parse_timestamp(obs["observed_at"], "quote_observed_at")
        end = (
            parse_timestamp(sorted_values[idx + 1]["observed_at"], "quote_observed_at")
            if idx + 1 < len(sorted_values)
            else forecast_at
        )
        span = max((end - start).total_seconds(), 0.0)
        if span > 0:
            weighted_sum += obs[field] * span
            total_seconds += span
    if total_seconds == 0:
        return arithmetic_average([obs[field] for obs in values])
    return weighted_sum / total_seconds


def latest_non_null(observations: list[dict[str, Any]], field: str) -> Any:
    for obs in reversed(observations):
        if obs.get(field) is not None:
            return obs[field]
    return None


def default_side_mapping(outcome_type: str | None) -> dict[str, Any]:
    if outcome_type and str(outcome_type).lower() != "binary":
        return {
            "primary": {"outcome": "primary", "resolves_to": "market_primary_outcome"},
        }
    return {
        "yes": {"outcome": "yes", "resolves_to": "market_resolves_yes"},
        "no": {"outcome": "no", "resolves_to": "market_resolves_no"},
    }


def validate_side_mapping(side_mapping: dict[str, Any], outcome_type: str | None) -> None:
    if not isinstance(side_mapping, dict) or not side_mapping:
        raise EvidencePacketError("side_mapping must be a non-empty object")
    normalized_outcome_type = str(outcome_type or "").lower()
    if normalized_outcome_type in {"", "binary"}:
        if set(side_mapping) != {"yes", "no"}:
            raise EvidencePacketError("binary side_mapping must contain exactly yes and no")
        yes = side_mapping["yes"].get("resolves_to")
        no = side_mapping["no"].get("resolves_to")
        if not yes or not no or yes == no:
            raise EvidencePacketError("binary side_mapping must map yes/no to distinct outcomes")
    for side, mapping in side_mapping.items():
        if not isinstance(mapping, dict):
            raise EvidencePacketError(f"side_mapping.{side} must be an object")
        if not mapping.get("outcome") or not mapping.get("resolves_to"):
            raise EvidencePacketError(f"side_mapping.{side} requires outcome and resolves_to")


def build_axis_mapping(side_mapping: dict[str, Any], outcome_type: str | None) -> dict[str, Any]:
    validate_side_mapping(side_mapping, outcome_type)
    if set(side_mapping) == {"yes", "no"}:
        return {
            "probability_axis": "selected_market_yes_probability",
            "scale": "0_to_1",
            "favorable_side": "yes",
            "unfavorable_side": "no",
            "side_directions": {
                "yes": {
                    "higher_probability_means": side_mapping["yes"]["resolves_to"],
                    "lower_probability_means": side_mapping["no"]["resolves_to"],
                },
                "no": {
                    "higher_probability_means": side_mapping["no"]["resolves_to"],
                    "lower_probability_means": side_mapping["yes"]["resolves_to"],
                },
            },
        }
    primary_side = next(iter(side_mapping))
    return {
        "probability_axis": "selected_market_primary_probability",
        "scale": "0_to_1",
        "favorable_side": primary_side,
        "unfavorable_side": None,
        "side_directions": {
            primary_side: {
                "higher_probability_means": side_mapping[primary_side]["resolves_to"],
                "lower_probability_means": "not_" + str(side_mapping[primary_side]["resolves_to"]),
            },
        },
    }


def normalize_relation_constraints(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    raise EvidencePacketError("relation_constraints must be a string or list")


def normalize_family_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_event_id": row.get("parent_event_id"),
        "child_market_id": row.get("child_market_id") or row.get("selected_child_market_id"),
        "family_type": row.get("family_type", "unknown"),
        "relation_constraints": normalize_relation_constraints(row.get("relation_constraints")),
        "sibling_price": row.get("sibling_price", row.get("price")),
        "sibling_price_method": row.get("sibling_price_method", row.get("price_method")),
    }


def build_family_context(case_contract: dict[str, Any], family_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    market_identity = case_contract["market_identity"]
    selected_child_id = str(market_identity.get("external_market_id") or market_identity["internal_market_id"])
    rows = [normalize_family_row(row) for row in (family_rows or [])]
    if not rows:
        outcome_type = str(market_identity.get("outcome_type") or "").lower()
        mode = "standalone_binary" if outcome_type in {"", "binary"} else "unknown"
        return {
            "mode": mode,
            "parent_event_id": None,
            "selected_child_market_id": selected_child_id if mode == "standalone_binary" else None,
            "sibling_child_ids": [],
            "family_type": "none" if mode == "standalone_binary" else "unknown",
            "relation_constraints": [],
            "sibling_prices": [],
            "family_validation_flags": [],
        }

    selected_rows = [row for row in rows if str(row.get("child_market_id")) == selected_child_id]
    if not selected_rows:
        raise EvidencePacketError("family-aware context requires selected child market row")
    selected = selected_rows[0]
    if not selected.get("parent_event_id"):
        raise EvidencePacketError("family-aware context requires parent_event_id")
    constraints = selected.get("relation_constraints") or []
    if not constraints:
        raise EvidencePacketError("family-aware context requires relation_constraints")

    sibling_rows = [row for row in rows if str(row.get("child_market_id")) != selected_child_id]
    return {
        "mode": "family_aware_binary_child",
        "parent_event_id": selected["parent_event_id"],
        "selected_child_market_id": selected_child_id,
        "sibling_child_ids": [str(row["child_market_id"]) for row in sibling_rows if row.get("child_market_id")],
        "family_type": selected.get("family_type") or "unknown",
        "relation_constraints": constraints,
        "sibling_prices": [
            {
                "child_market_id": str(row["child_market_id"]),
                "price": row.get("sibling_price"),
                "price_method": row.get("sibling_price_method"),
                "context_only": True,
            }
            for row in sibling_rows
            if row.get("child_market_id") and row.get("sibling_price") is not None
        ],
        "family_validation_flags": ["sibling_prices_context_only"],
    }


def build_market_reality_constraints(
    case_contract: dict[str, Any],
    *,
    side_mapping: dict[str, Any] | None = None,
    source_of_truth_status: str = "unknown",
    contract_structure: str | None = None,
) -> dict[str, Any]:
    market_identity = case_contract["market_identity"]
    mapping = side_mapping or default_side_mapping(market_identity.get("outcome_type"))
    validate_side_mapping(mapping, market_identity.get("outcome_type"))
    if source_of_truth_status not in SOURCE_OF_TRUTH_STATUSES:
        raise EvidencePacketError(f"unknown source_of_truth_status: {source_of_truth_status}")
    structure = contract_structure or ("binary" if str(market_identity.get("outcome_type") or "").lower() in {"", "binary"} else "other")
    if structure not in CONTRACT_STRUCTURES:
        raise EvidencePacketError(f"unknown contract_structure: {structure}")
    return {
        "side_mapping": mapping,
        "axis_mapping": build_axis_mapping(mapping, market_identity.get("outcome_type")),
        "source_of_truth_status": source_of_truth_status,
        "contract_structure": structure,
        "close_timestamp": market_identity.get("closes_at"),
        "resolve_timestamp": market_identity.get("resolves_at"),
    }


def build_prior_context_seed(
    case_contract: dict[str, Any],
    market_snapshot: sqlite3.Row | dict[str, Any] | None,
    quote_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    baseline = case_contract["prediction_time_market_baseline"]
    return {
        "market_live_probability": baseline.get("market_probability"),
        "market_probability_method": baseline.get("market_probability_method"),
        "market_snapshot_id": baseline.get("market_snapshot_id"),
        "market_snapshot_timestamp": baseline.get("source_fetched_at") or case_contract["source_cutoff_timestamp"],
        "snapshot_age_seconds_at_dispatch": baseline.get("snapshot_age_seconds_at_dispatch"),
        "quote_observation_refs": quote_refs or [],
        "microstructure_input_refs": [],
        "market_priced_through_timestamp": case_contract["source_cutoff_timestamp"],
        "compact_snapshot_fields": {
            "last_price": snapshot_value(market_snapshot, "last_price"),
            "best_bid": snapshot_value(market_snapshot, "best_bid"),
            "best_ask": snapshot_value(market_snapshot, "best_ask"),
            "yes_price": snapshot_value(market_snapshot, "yes_price"),
            "no_price": snapshot_value(market_snapshot, "no_price"),
            "volume": snapshot_value(market_snapshot, "volume"),
            "open_interest": snapshot_value(market_snapshot, "open_interest"),
        },
    }


def quote_observation_ref(row: dict[str, Any], compact: dict[str, Any], index: int) -> dict[str, Any]:
    source = row.get("source") or row.get("table") or "quote_observation"
    row_id = row.get("row_id", row.get("id"))
    ref_id = row.get("ref_id")
    if not ref_id:
        if row_id is not None:
            ref_id = f"{source}:{row_id}"
        else:
            digest = hashlib.sha256(canonical_json(compact).encode("utf-8")).hexdigest()[:16]
            ref_id = f"quote-observation:{index}:{digest}"
    ref = {
        "ref_id": str(ref_id),
        "source": str(source),
        "observed_at": compact.get("observed_at"),
    }
    if row_id is not None:
        ref["row_id"] = row_id
    return ref


def normalize_quote_observation(observation: sqlite3.Row | dict[str, Any], index: int) -> dict[str, Any]:
    row = dict(observation) if not isinstance(observation, sqlite3.Row) else {key: observation[key] for key in observation.keys()}
    observed_at = optional_normalized_timestamp(
        first_present(row, "observed_at", "quote_observed_at", "timestamp"),
        f"quote_observations[{index}].observed_at",
    )
    bid = numeric_value(first_present(row, "best_bid", "bid", "yes_bid"))
    ask = numeric_value(first_present(row, "best_ask", "ask", "yes_ask"))
    spread = numeric_value(first_present(row, "bid_ask_spread", "spread"))
    if spread is None and bid is not None and ask is not None:
        spread = max(ask - bid, 0.0)
    bid_size = numeric_value(first_present(row, "bid_size", "best_bid_size"))
    ask_size = numeric_value(first_present(row, "ask_size", "best_ask_size"))
    depth = numeric_value(first_present(row, "order_book_depth", "depth"))
    if depth is None and (bid_size is not None or ask_size is not None):
        depth = (bid_size or 0.0) + (ask_size or 0.0)
    compact = {
        "observed_at": observed_at,
        "best_bid": bid,
        "best_ask": ask,
        "bid_ask_spread": spread,
        "order_book_depth": depth,
        "volume": numeric_value(first_present(row, "volume", "recent_volume", "volume_24h")),
        "open_interest": numeric_value(first_present(row, "open_interest", "liquidity")),
        "last_trade_at": optional_normalized_timestamp(
            first_present(row, "last_trade_at", "last_traded_at"),
            f"quote_observations[{index}].last_trade_at",
        ),
    }
    compact["ref"] = quote_observation_ref(row, compact, index)
    return compact


def reason_candidate(code: str, *, severity: str, evidence_refs: list[str], details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "candidate_only": True,
        "scae_reliability_authority": "none_candidate_input_only",
        "evidence_refs": evidence_refs,
        "details": details or {},
    }


def validate_quote_temporal_isolation(observations: list[dict[str, Any]], forecast_timestamp: str) -> None:
    forecast_at = parse_timestamp(forecast_timestamp, "forecast_timestamp")
    for obs in observations:
        if obs.get("observed_at") and parse_timestamp(obs["observed_at"], "quote_observed_at") > forecast_at:
            raise EvidencePacketError("quote observation must not be after forecast_timestamp")
        if obs.get("last_trade_at") and parse_timestamp(obs["last_trade_at"], "last_trade_at") > forecast_at:
            raise EvidencePacketError("last trade timestamp must not be after forecast_timestamp")


def build_prior_reliability_inputs(
    *,
    case_contract: dict[str, Any],
    market_snapshot: sqlite3.Row | dict[str, Any] | None = None,
    quote_observations: list[sqlite3.Row | dict[str, Any]] | None = None,
    quote_refs: list[dict[str, Any]] | None = None,
    policy: dict[str, float] | None = None,
) -> dict[str, Any]:
    validate_ads_case_contract(case_contract)
    runtime_policy = dict(DEFAULT_PRIOR_RELIABILITY_POLICY)
    if policy:
        runtime_policy.update(policy)
    forecast_timestamp = case_contract["forecast_timestamp"]
    compact_observations = [
        normalize_quote_observation(observation, idx)
        for idx, observation in enumerate(quote_observations or [])
    ]
    compact_observations.sort(key=lambda obs: obs.get("observed_at") or "")
    validate_quote_temporal_isolation(compact_observations, forecast_timestamp)

    baseline = case_contract["prediction_time_market_baseline"]
    snapshot_age = baseline.get("snapshot_age_seconds_at_dispatch")
    if snapshot_age is None and market_snapshot is not None and snapshot_value(market_snapshot, "observed_at"):
        snapshot_age = seconds_between(forecast_timestamp, snapshot_value(market_snapshot, "observed_at"), "snapshot_observed_at")
    source_cutoff = case_contract["source_cutoff_timestamp"]
    latest_quote_timestamp = latest_non_null(compact_observations, "observed_at")
    priced_through_timestamp = latest_quote_timestamp or source_cutoff
    last_trade_timestamp = latest_non_null(compact_observations, "last_trade_at")
    last_trade_age = seconds_between(forecast_timestamp, last_trade_timestamp, "last_trade_at") if last_trade_timestamp else None
    quote_ref_list = [obs["ref"] for obs in compact_observations] or (quote_refs or [])
    quote_ref_ids = [str(ref.get("ref_id")) for ref in quote_ref_list if isinstance(ref, dict) and ref.get("ref_id")]
    reason_codes: list[dict[str, Any]] = []

    freshness_status = "unavailable"
    if isinstance(snapshot_age, (int, float)):
        if snapshot_age >= runtime_policy["stale_snapshot_seconds"]:
            freshness_status = "stale"
            reason_codes.append(
                reason_candidate(
                    "prior_snapshot_stale_candidate",
                    severity="warning",
                    evidence_refs=[str(baseline.get("market_snapshot_id"))],
                    details={"snapshot_age_seconds": snapshot_age},
                )
            )
        elif snapshot_age <= runtime_policy["fresh_snapshot_seconds"]:
            freshness_status = "fresh"
        else:
            freshness_status = "usable"

    if not compact_observations:
        reason_codes.append(
            reason_candidate(
                "quote_observations_unavailable",
                severity="info",
                evidence_refs=[],
                details={"fallback_priced_through_timestamp": priced_through_timestamp},
            )
        )

    spread_values = [obs["bid_ask_spread"] for obs in compact_observations if obs.get("bid_ask_spread") is not None]
    if spread_values and max(spread_values) >= runtime_policy["spread_warning_threshold"]:
        code = "instant_spread_spike_warning_candidate" if len(spread_values) == 1 else "rolling_spread_warning_candidate"
        reason_codes.append(
            reason_candidate(
                code,
                severity="warning",
                evidence_refs=quote_ref_ids,
                details={
                    "max_bid_ask_spread": max(spread_values),
                    "observation_count": len(spread_values),
                    "downgrade_authority": False,
                },
            )
        )

    latest_volume = latest_non_null(compact_observations, "volume")
    latest_open_interest = latest_non_null(compact_observations, "open_interest")
    if (
        compact_observations
        and freshness_status == "fresh"
        and (
            (latest_volume is not None and latest_volume >= runtime_policy["liquid_volume_threshold"])
            or (
                latest_open_interest is not None
                and latest_open_interest >= runtime_policy["liquid_open_interest_threshold"]
            )
        )
    ):
        reason_codes.append(
            reason_candidate(
                "fresh_liquid_market_candidate",
                severity="info",
                evidence_refs=quote_ref_ids,
                details={
                    "snapshot_age_seconds": snapshot_age,
                    "latest_volume": latest_volume,
                    "latest_open_interest": latest_open_interest,
                },
            )
        )

    inputs = {
        "schema_version": PRIOR_RELIABILITY_INPUT_SCHEMA_VERSION,
        "authority": "candidate_inputs_only_no_scae_probability",
        "policy": runtime_policy,
        "lookback_window": {
            "source": "compact_quote_observations",
            "observation_count": len(compact_observations),
            "first_observed_at": compact_observations[0]["observed_at"] if compact_observations else None,
            "latest_observed_at": compact_observations[-1]["observed_at"] if compact_observations else None,
        },
        "quote_observation_refs": quote_ref_list,
        "compact_quote_observations": compact_observations,
        "rolling_microstructure": {
            "bid_ask_spread_twap": time_weighted_average(compact_observations, "bid_ask_spread", forecast_timestamp),
            "bid_ask_spread_latest": latest_non_null(compact_observations, "bid_ask_spread"),
            "bid_ask_spread_max": max(spread_values) if spread_values else None,
            "order_book_depth_twap": time_weighted_average(compact_observations, "order_book_depth", forecast_timestamp),
            "order_book_depth_latest": latest_non_null(compact_observations, "order_book_depth"),
            "recent_volume_rolling": {
                "latest": latest_volume,
                "max": max([obs["volume"] for obs in compact_observations if obs.get("volume") is not None], default=None),
            },
            "open_interest_latest": latest_open_interest,
            "last_trade_age_seconds_rolling": last_trade_age,
            "market_snapshot_age_seconds": snapshot_age,
            "market_snapshot_freshness": {
                "status": freshness_status,
                "fresh_snapshot_seconds": runtime_policy["fresh_snapshot_seconds"],
                "stale_snapshot_seconds": runtime_policy["stale_snapshot_seconds"],
            },
            "market_priced_through_timestamp": priced_through_timestamp,
            "microstructure_spoofing_check_status": "not_evaluated_candidate_input_only",
        },
        "reason_code_candidates": reason_codes,
    }
    validate_prior_reliability_inputs(inputs)
    return inputs


def validate_prior_reliability_inputs(inputs: dict[str, Any]) -> None:
    if not isinstance(inputs, dict):
        raise EvidencePacketError("prior_reliability_inputs must be an object")
    required = [
        "schema_version",
        "authority",
        "policy",
        "lookback_window",
        "quote_observation_refs",
        "compact_quote_observations",
        "rolling_microstructure",
        "reason_code_candidates",
    ]
    for field in required:
        if field not in inputs:
            raise EvidencePacketError(f"prior_reliability_inputs.{field} is required")
    if inputs["schema_version"] != PRIOR_RELIABILITY_INPUT_SCHEMA_VERSION:
        raise EvidencePacketError(f"prior_reliability_inputs.schema_version must be {PRIOR_RELIABILITY_INPUT_SCHEMA_VERSION}")
    if inputs["authority"] != "candidate_inputs_only_no_scae_probability":
        raise EvidencePacketError("prior_reliability_inputs authority must be candidate-only")
    for candidate in inputs["reason_code_candidates"]:
        if not candidate.get("candidate_only"):
            raise EvidencePacketError("prior reliability reason codes must be candidates only")
        if candidate.get("scae_reliability_authority") != "none_candidate_input_only":
            raise EvidencePacketError("prior reliability inputs cannot assign SCAE reliability authority")

    def reject_authority_fields(value: Any, path: str = "prior_reliability_inputs") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in FORBIDDEN_PRIOR_RELIABILITY_KEYS:
                    raise EvidencePacketError(f"{path}.{key} is reserved for SCAE, not CTX-003")
                reject_authority_fields(child, f"{path}.{key}")
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                reject_authority_fields(child, f"{path}[{idx}]")

    reject_authority_fields(inputs)
    ensure_no_raw_payload_fields(inputs, "prior_reliability_inputs")


def build_regime_seed_fields(case_contract: dict[str, Any], family_context: dict[str, Any]) -> dict[str, Any]:
    market_identity = case_contract["market_identity"]
    return {
        "platform": market_identity.get("platform"),
        "category": market_identity.get("category"),
        "status": market_identity.get("status"),
        "outcome_type": market_identity.get("outcome_type"),
        "contract_structure": "family_aware_binary_child"
        if family_context["mode"] == "family_aware_binary_child"
        else "binary",
        "family_type": family_context.get("family_type"),
        "close_timestamp": market_identity.get("closes_at"),
        "resolve_timestamp": market_identity.get("resolves_at"),
    }


def build_evidence_packet_v2(
    *,
    case_contract: dict[str, Any],
    case_contract_ref: str,
    market_snapshot: sqlite3.Row | dict[str, Any] | None = None,
    family_rows: list[dict[str, Any]] | None = None,
    quote_refs: list[dict[str, Any]] | None = None,
    quote_observations: list[sqlite3.Row | dict[str, Any]] | None = None,
    side_mapping: dict[str, Any] | None = None,
    source_of_truth_status: str = "unknown",
    prior_reliability_policy: dict[str, float] | None = None,
) -> dict[str, Any]:
    try:
        validate_ads_case_contract(case_contract)
    except CaseContractError as exc:
        raise EvidencePacketError(f"invalid ADS case contract: {exc}") from exc

    family_context = build_family_context(case_contract, family_rows)
    structure = "family_aware_binary_child" if family_context["mode"] == "family_aware_binary_child" else "binary"
    constraints = build_market_reality_constraints(
        case_contract,
        side_mapping=side_mapping,
        source_of_truth_status=source_of_truth_status,
        contract_structure=structure,
    )
    packet = {
        "artifact_type": "evidence_packet",
        "schema_version": EVIDENCE_PACKET_SCHEMA_VERSION,
        "case_contract_ref": case_contract_ref,
        "case_id": case_contract["case_id"],
        "case_key": case_contract["case_key"],
        "market_id": case_contract["market_identity"]["internal_market_id"],
        "dispatch_id": case_contract["dispatch_id"],
        "forecast_timestamp": case_contract["forecast_timestamp"],
        "source_cutoff_timestamp": case_contract["source_cutoff_timestamp"],
        "market_identity": dict(case_contract["market_identity"]),
        "market_reality_constraints": constraints,
        "family_context": family_context,
        "prior_context_seed": build_prior_context_seed(case_contract, market_snapshot, quote_refs),
        "prior_reliability_inputs": build_prior_reliability_inputs(
            case_contract=case_contract,
            market_snapshot=market_snapshot,
            quote_observations=quote_observations,
            quote_refs=quote_refs,
            policy=prior_reliability_policy,
        ),
        "regime_seed_fields": build_regime_seed_fields(case_contract, family_context),
        "active_safe_refs": {
            "ads_case_contract": case_contract_ref,
            "source_payload_hash": case_contract["intake_source"]["source_payload_hash"],
            "market_snapshot_id": case_contract["intake_source"]["market_snapshot_id"],
        },
    }
    validate_evidence_packet_v2(packet)
    return packet


def validate_evidence_packet_v2(packet: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "case_contract_ref",
        "case_id",
        "case_key",
        "market_id",
        "dispatch_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "market_identity",
        "market_reality_constraints",
        "family_context",
        "prior_context_seed",
        "prior_reliability_inputs",
        "regime_seed_fields",
        "active_safe_refs",
    ]
    for field in required:
        if field not in packet:
            raise EvidencePacketError(f"{field} is required")
    if packet["artifact_type"] != "evidence_packet":
        raise EvidencePacketError("artifact_type must be evidence_packet")
    if packet["schema_version"] != EVIDENCE_PACKET_SCHEMA_VERSION:
        raise EvidencePacketError(f"schema_version must be {EVIDENCE_PACKET_SCHEMA_VERSION}")
    if not packet["case_contract_ref"]:
        raise EvidencePacketError("case_contract_ref is required")
    parse_timestamp(packet["forecast_timestamp"], "forecast_timestamp")
    parse_timestamp(packet["source_cutoff_timestamp"], "source_cutoff_timestamp")
    constraints = packet["market_reality_constraints"]
    validate_side_mapping(constraints.get("side_mapping"), packet["market_identity"].get("outcome_type"))
    axis_mapping = constraints.get("axis_mapping")
    if not isinstance(axis_mapping, dict) or not axis_mapping.get("probability_axis"):
        raise EvidencePacketError("market_reality_constraints.axis_mapping is required")
    if axis_mapping.get("scale") != "0_to_1":
        raise EvidencePacketError("axis_mapping.scale must be 0_to_1")
    if constraints.get("source_of_truth_status") not in SOURCE_OF_TRUTH_STATUSES:
        raise EvidencePacketError("invalid source_of_truth_status")
    if constraints.get("contract_structure") not in CONTRACT_STRUCTURES:
        raise EvidencePacketError("invalid contract_structure")
    validate_prior_reliability_inputs(packet["prior_reliability_inputs"])
    family = packet["family_context"]
    if family.get("mode") not in FAMILY_MODES:
        raise EvidencePacketError("invalid family context mode")
    if family["mode"] == "family_aware_binary_child":
        if not family.get("selected_child_market_id"):
            raise EvidencePacketError("family-aware packet requires selected child")
        if not family.get("parent_event_id"):
            raise EvidencePacketError("family-aware packet requires parent event")
        if not family.get("relation_constraints"):
            raise EvidencePacketError("family-aware packet requires relation constraints")
        for sibling in family.get("sibling_prices", []):
            if not sibling.get("context_only"):
                raise EvidencePacketError("sibling prices must be context-only")
            if sibling.get("child_market_id") == family.get("selected_child_market_id"):
                raise EvidencePacketError("selected child cannot appear as sibling price")
    ensure_no_raw_payload_fields(packet)


def evidence_packet_path(artifact_dir: Path | str, packet: dict[str, Any]) -> Path:
    base = Path(artifact_dir) / packet["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{packet['dispatch_id']}-evidence-packet-v2.json"


def write_evidence_packet_artifact(path: Path | str, packet: dict[str, Any]) -> Path:
    validate_evidence_packet_v2(packet)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(packet) + "\n", encoding="utf-8")
    return target


def build_manifest_for_evidence_packet(packet: dict[str, Any], path: Path | str) -> dict[str, Any]:
    context = ArtifactManifestContext(
        case_id=packet["case_id"],
        case_key=packet["case_key"],
        dispatch_id=packet["dispatch_id"],
        stage="evidence_packet",
        producer="session-02-evidence-packet",
        forecast_timestamp=packet["forecast_timestamp"],
        source_cutoff_timestamp=packet["source_cutoff_timestamp"],
    )
    manifest = build_artifact_manifest(
        context=context,
        artifact_type=EVIDENCE_PACKET_ARTIFACT_TYPE,
        artifact_schema_version=EVIDENCE_PACKET_SCHEMA_VERSION,
        path=path,
        input_manifest_ids=[packet["case_contract_ref"]],
        validation_status="valid",
        validator_version="evidence-packet-v2",
        temporal_isolation_status="pass",
        metadata={
            "market_id": packet["market_id"],
            "market_snapshot_id": packet["prior_context_seed"].get("market_snapshot_id"),
            "family_mode": packet["family_context"]["mode"],
            "case_contract_ref": packet["case_contract_ref"],
            "prior_reliability_schema_version": packet["prior_reliability_inputs"]["schema_version"],
            "prior_reliability_reason_codes": [
                candidate["code"] for candidate in packet["prior_reliability_inputs"]["reason_code_candidates"]
            ],
        },
    )
    validate_artifact_manifest(manifest, expected_artifact_schema_version=EVIDENCE_PACKET_SCHEMA_VERSION)
    return manifest


def materialize_evidence_packet_v2(
    conn: sqlite3.Connection,
    *,
    case_contract: dict[str, Any],
    case_contract_ref: str,
    artifact_dir: Path | str,
    market_snapshot: sqlite3.Row | dict[str, Any] | None = None,
    family_rows: list[dict[str, Any]] | None = None,
    quote_refs: list[dict[str, Any]] | None = None,
    quote_observations: list[sqlite3.Row | dict[str, Any]] | None = None,
    side_mapping: dict[str, Any] | None = None,
    source_of_truth_status: str = "unknown",
    prior_reliability_policy: dict[str, float] | None = None,
) -> dict[str, Any]:
    packet = build_evidence_packet_v2(
        case_contract=case_contract,
        case_contract_ref=case_contract_ref,
        market_snapshot=market_snapshot,
        family_rows=family_rows,
        quote_refs=quote_refs,
        quote_observations=quote_observations,
        side_mapping=side_mapping,
        source_of_truth_status=source_of_truth_status,
        prior_reliability_policy=prior_reliability_policy,
    )
    path = write_evidence_packet_artifact(evidence_packet_path(artifact_dir, packet), packet)
    manifest = build_manifest_for_evidence_packet(packet, path)
    artifact_id = write_artifact_manifest(conn, manifest)
    return {
        "status": "completed",
        "artifact_id": artifact_id,
        "artifact_path": str(path),
        "packet": packet,
        "manifest": manifest,
    }


def load_json_path(path: Path | None, default: Any) -> Any:
    if path is None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an ADS evidence packet v2 artifact.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--case-contract-path", required=True, type=Path)
    parser.add_argument("--case-contract-ref", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--family-rows-json", type=Path)
    parser.add_argument("--quote-refs-json", type=Path)
    parser.add_argument("--quote-observations-json", type=Path)
    parser.add_argument("--side-mapping-json", type=Path)
    parser.add_argument("--source-of-truth-status", default="unknown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    contract = json.loads(args.case_contract_path.read_text(encoding="utf-8"))
    family_rows = load_json_path(args.family_rows_json, [])
    quote_refs = load_json_path(args.quote_refs_json, [])
    quote_observations = load_json_path(args.quote_observations_json, [])
    side_mapping = load_json_path(args.side_mapping_json, None)
    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            result = materialize_evidence_packet_v2(
                conn,
                case_contract=contract,
                case_contract_ref=args.case_contract_ref,
                artifact_dir=args.artifact_dir,
                family_rows=family_rows,
                quote_refs=quote_refs,
                quote_observations=quote_observations,
                side_mapping=side_mapping,
                source_of_truth_status=args.source_of_truth_status,
            )
        print(canonical_json({k: v for k, v in result.items() if k not in {"packet", "manifest"}}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
