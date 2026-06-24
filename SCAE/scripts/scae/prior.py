"""Prior odds and market-assimilation context for ADS SCAE."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from scae.policy import default_scae_policy, validate_probability


SCAE_PRIOR_CONTEXT_SCHEMA_VERSION = "scae-prior-context/v1"
MARKET_ASSIMILATION_CONTEXT_SCHEMA_VERSION = "market-assimilation-context/v1"


class ScaePriorError(ValueError):
    """Raised when prior or assimilation inputs are malformed."""


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def logit(probability: float, epsilon: float) -> float:
    bounded = clamp(validate_probability(probability, "probability"), epsilon, 1.0 - epsilon)
    return math.log(bounded / (1.0 - bounded))


def sigmoid(log_odds: float) -> float:
    if log_odds >= 0:
        z = math.exp(-log_odds)
        return 1.0 / (1.0 + z)
    z = math.exp(log_odds)
    return z / (1.0 + z)


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ScaePriorError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def reason_codes(prior_reliability_inputs: dict[str, Any] | None) -> set[str]:
    return {
        str(candidate.get("code"))
        for candidate in (prior_reliability_inputs or {}).get("reason_code_candidates", [])
        if isinstance(candidate, dict) and candidate.get("code")
    }


def rolling_microstructure(prior_reliability_inputs: dict[str, Any] | None) -> dict[str, Any]:
    return dict((prior_reliability_inputs or {}).get("rolling_microstructure") or {})


def valid_market_prior(market_prior: dict[str, Any] | None) -> tuple[bool, float | None, list[str]]:
    if not isinstance(market_prior, dict):
        return False, None, ["market_prior_missing"]
    source = market_prior.get("source", "market_live_probability")
    probability = numeric(market_prior.get("probability"))
    flags: list[str] = []
    if source != "market_live_probability":
        flags.append("market_prior_source_not_live_probability")
    if market_prior.get("valid", True) is False:
        flags.append("market_prior_marked_invalid")
    if probability is None or not 0.0 <= probability <= 1.0:
        flags.append("market_prior_probability_invalid")
    return not flags, probability, flags


def valid_structural_prior(structural_prior: dict[str, Any] | None) -> tuple[bool, float | None, list[str]]:
    if not isinstance(structural_prior, dict):
        return False, None, ["structural_prior_missing"]
    probability = numeric(structural_prior.get("probability"))
    flags: list[str] = []
    if structural_prior.get("valid") is not True:
        flags.append("structural_prior_not_validated")
    if structural_prior.get("materialized_by_preledger_provider") is not True:
        flags.append("structural_prior_not_materialized_by_preledger_provider")
    if probability is None or not 0.0 <= probability <= 1.0:
        flags.append("structural_prior_probability_invalid")
    return not flags, probability, flags


def compute_prior_reliability(
    prior_reliability_inputs: dict[str, Any] | None,
    policy: dict[str, Any],
    *,
    contradiction_signal: bool = False,
    spoofing_signal: bool = False,
) -> dict[str, Any]:
    prior_policy = policy["prior_reliability"]
    micro = rolling_microstructure(prior_reliability_inputs)
    codes = reason_codes(prior_reliability_inputs)
    reliability = float(prior_policy["base_market_prior_reliability"])
    flags: list[str] = []

    freshness = (micro.get("market_snapshot_freshness") or {}).get("status")
    if freshness == "fresh":
        reliability += 0.10
        flags.append("fresh_snapshot")
    elif freshness == "stale":
        reliability -= 0.35
        flags.append("stale_snapshot")
    elif freshness == "unavailable":
        reliability -= 0.30
        flags.append("snapshot_age_unavailable")

    spread = numeric(micro.get("bid_ask_spread_latest"))
    if spread is None:
        spread = numeric(micro.get("bid_ask_spread_twap"))
    if spread is not None:
        if spread <= prior_policy["tight_spread_threshold"]:
            reliability += 0.10
            flags.append("tight_spread")
        elif spread >= prior_policy["wide_spread_threshold"]:
            reliability -= 0.25
            flags.append("wide_spread")

    depth = numeric(micro.get("order_book_depth_latest"))
    if depth is None:
        depth = numeric(micro.get("order_book_depth_twap"))
    volume = numeric((micro.get("recent_volume_rolling") or {}).get("latest"))
    open_interest = numeric(micro.get("open_interest_latest"))
    liquid_book = (
        (depth is not None and depth >= prior_policy["deep_depth_threshold"])
        or (volume is not None and volume >= prior_policy["liquid_volume_threshold"])
        or (open_interest is not None and open_interest >= prior_policy["liquid_volume_threshold"])
    )
    thin_book = (
        (depth is not None and depth <= prior_policy["thin_depth_threshold"])
        or (volume is not None and volume <= prior_policy["thin_volume_threshold"])
    )
    if liquid_book:
        reliability += 0.10
        flags.append("liquid_microstructure")
    elif thin_book:
        reliability -= 0.15
        flags.append("thin_microstructure")

    last_trade_age = numeric(micro.get("last_trade_age_seconds_rolling"))
    if last_trade_age is not None:
        if last_trade_age <= prior_policy["active_last_trade_seconds"]:
            reliability += 0.05
            flags.append("recent_trade")
        elif last_trade_age >= prior_policy["stale_last_trade_seconds"]:
            reliability -= 0.10
            flags.append("stale_trade")

    reliability = clamp(
        reliability,
        prior_policy["market_prior_min_reliability"],
        prior_policy["market_prior_max_reliability"],
    )

    fresh_liquid = "fresh_liquid_market_candidate" in codes or (
        freshness == "fresh" and liquid_book
    )
    stale_thin = (
        freshness == "stale"
        or "prior_snapshot_stale_candidate" in codes
        or "rolling_spread_warning_candidate" in codes
        or "instant_spread_spike_warning_candidate" in codes
        or thin_book
    )
    floor_applied = False
    ceiling_applied = False
    if fresh_liquid and not contradiction_signal and not spoofing_signal:
        reliability = max(reliability, prior_policy["fresh_liquid_reliability_floor"])
        floor_applied = True
        flags.append("fresh_liquid_floor_applied")
    if stale_thin:
        reliability = min(reliability, prior_policy["stale_thin_reliability_ceiling"])
        ceiling_applied = True
        flags.append("stale_thin_ceiling_applied")

    if contradiction_signal:
        flags.append("contradiction_signal_present")
    if spoofing_signal:
        flags.append("spoofing_signal_present")

    if floor_applied:
        reliability_class = "fresh_liquid"
    elif ceiling_applied:
        reliability_class = "stale_thin"
    elif reliability >= 0.65:
        reliability_class = "usable_market"
    else:
        reliability_class = "low_reliability_market"

    return {
        "prior_reliability_score": round(reliability, 6),
        "prior_reliability_class": reliability_class,
        "reliability_reason_codes": sorted(codes),
        "reliability_flags": flags,
        "market_priced_through_timestamp": micro.get("market_priced_through_timestamp"),
        "microstructure_input_refs": [
            ref.get("ref_id")
            for ref in (prior_reliability_inputs or {}).get("quote_observation_refs", [])
            if isinstance(ref, dict) and ref.get("ref_id")
        ],
    }


def choose_shrink_target(
    structural_prior: dict[str, Any] | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    structural_ok, structural_probability, structural_flags = valid_structural_prior(structural_prior)
    epsilon = policy["prior_reliability"]["epsilon"]
    if structural_ok and structural_probability is not None:
        return {
            "shrink_target_type": "structural_base_rate",
            "shrink_target_probability": structural_probability,
            "shrink_target_log_odds": logit(structural_probability, epsilon),
            "shrink_target_ref": structural_prior.get("prior_ref"),
            "uncertainty_flags": [],
        }
    return {
        "shrink_target_type": "neutral_default",
        "shrink_target_probability": 0.5,
        "shrink_target_log_odds": 0.0,
        "shrink_target_ref": None,
        "uncertainty_flags": structural_flags + ["neutral_default_used"],
    }


def build_prior_context(
    *,
    market_prior: dict[str, Any] | None,
    prior_reliability_inputs: dict[str, Any] | None,
    structural_prior: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    contradiction_signal: bool = False,
    spoofing_signal: bool = False,
) -> dict[str, Any]:
    """Build SCAE prior context before evidence-delta mapping."""

    active_policy = policy or default_scae_policy()
    epsilon = active_policy["prior_reliability"]["epsilon"]
    market_ok, market_probability, market_flags = valid_market_prior(market_prior)
    structural_ok, structural_probability, structural_flags = valid_structural_prior(structural_prior)

    if market_ok and market_probability is not None:
        reliability = compute_prior_reliability(
            prior_reliability_inputs,
            active_policy,
            contradiction_signal=contradiction_signal,
            spoofing_signal=spoofing_signal,
        )
        target = choose_shrink_target(structural_prior, active_policy)
        raw_market_log_odds = logit(market_probability, epsilon)
        adjusted_log_odds = (
            reliability["prior_reliability_score"] * raw_market_log_odds
            + (1.0 - reliability["prior_reliability_score"]) * target["shrink_target_log_odds"]
        )
        return {
            "schema_version": SCAE_PRIOR_CONTEXT_SCHEMA_VERSION,
            "authority": "scae_prior_context_only_no_evidence_delta",
            "prior_source": "market_live_probability",
            "market_prior_probability": market_probability,
            "raw_market_log_odds": raw_market_log_odds,
            "prior_reliability_score": reliability["prior_reliability_score"],
            "prior_reliability_class": reliability["prior_reliability_class"],
            "reliability_reason_codes": reliability["reliability_reason_codes"],
            "reliability_flags": reliability["reliability_flags"],
            "microstructure_input_refs": reliability["microstructure_input_refs"],
            "market_priced_through_timestamp": reliability["market_priced_through_timestamp"],
            "shrink_target_type": target["shrink_target_type"],
            "shrink_target_probability": target["shrink_target_probability"],
            "shrink_target_log_odds": target["shrink_target_log_odds"],
            "shrink_target_ref": target["shrink_target_ref"],
            "adjusted_prior_log_odds": adjusted_log_odds,
            "adjusted_prior_probability": sigmoid(adjusted_log_odds),
            "uncertainty_flags": target["uncertainty_flags"],
        }

    if structural_ok and structural_probability is not None:
        structural_log_odds = logit(structural_probability, epsilon)
        return {
            "schema_version": SCAE_PRIOR_CONTEXT_SCHEMA_VERSION,
            "authority": "scae_prior_context_only_no_evidence_delta",
            "prior_source": "structural_base_rate_prior",
            "market_prior_probability": market_probability,
            "raw_market_log_odds": None,
            "prior_reliability_score": active_policy["prior_reliability"]["structural_prior_default_reliability"],
            "prior_reliability_class": "structural_fallback",
            "reliability_reason_codes": [],
            "reliability_flags": ["market_prior_invalid_or_unavailable"],
            "market_priced_through_timestamp": rolling_microstructure(prior_reliability_inputs).get("market_priced_through_timestamp"),
            "shrink_target_type": "structural_base_rate",
            "shrink_target_probability": structural_probability,
            "shrink_target_log_odds": structural_log_odds,
            "shrink_target_ref": structural_prior.get("prior_ref"),
            "adjusted_prior_log_odds": structural_log_odds,
            "adjusted_prior_probability": structural_probability,
            "uncertainty_flags": market_flags,
        }

    return {
        "schema_version": SCAE_PRIOR_CONTEXT_SCHEMA_VERSION,
        "authority": "scae_prior_context_only_no_evidence_delta",
        "prior_source": "neutral_default_prior",
        "market_prior_probability": market_probability,
        "raw_market_log_odds": None,
        "prior_reliability_score": active_policy["prior_reliability"]["neutral_prior_default_reliability"],
        "prior_reliability_class": "neutral_fallback",
        "reliability_reason_codes": [],
        "reliability_flags": ["market_prior_invalid_or_unavailable"],
        "market_priced_through_timestamp": rolling_microstructure(prior_reliability_inputs).get("market_priced_through_timestamp"),
        "shrink_target_type": "neutral_default",
        "shrink_target_probability": 0.5,
        "shrink_target_log_odds": 0.0,
        "shrink_target_ref": None,
        "adjusted_prior_log_odds": 0.0,
        "adjusted_prior_probability": 0.5,
        "uncertainty_flags": market_flags + structural_flags + ["neutral_default_used"],
    }


def evidence_matches_shrinkage_anchor(evidence: dict[str, Any], prior_context: dict[str, Any]) -> bool:
    if evidence.get("matches_shrinkage_anchor") is True:
        return True
    shrink_ref = prior_context.get("shrink_target_ref")
    if not shrink_ref:
        return False
    return shrink_ref in {
        evidence.get("structural_prior_ref"),
        evidence.get("base_rate_ref"),
        evidence.get("source_prior_ref"),
    }


def build_market_assimilation_context(
    *,
    evidence: dict[str, Any],
    prior_context: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build context for later evidence-delta mapping without authoring a delta."""

    active_policy = policy or default_scae_policy()
    assimilation_policy = active_policy["market_assimilation"]
    reason_codes: list[str] = []
    discount = assimilation_policy["fresh_or_private_evidence_discount"]
    orthogonality_status = "orthogonal_or_fresh"
    signed_delta_context = "eligible_for_later_delta_mapping"

    if evidence_matches_shrinkage_anchor(evidence, prior_context):
        evidence_kind = evidence.get("evidence_kind") or evidence.get("evidence_class")
        if evidence_kind == "base_rate":
            discount = assimilation_policy["base_rate_overlap_multiplier"]
            signed_delta_context = "zero_duplicate_base_rate_prior"
            orthogonality_status = "duplicate_base_rate_shrinkage_anchor"
            reason_codes.append("base_rate_overlap_zero_signed_delta")
        else:
            discount = assimilation_policy["structural_prior_overlap_multiplier"]
            signed_delta_context = "zero_duplicate_structural_prior"
            orthogonality_status = "duplicate_structural_shrinkage_anchor"
            reason_codes.append("structural_prior_overlap_zero_signed_delta")
    elif prior_context.get("prior_source") == "market_live_probability":
        published_at = parse_timestamp(evidence.get("published_at"))
        priced_through = parse_timestamp(prior_context.get("market_priced_through_timestamp"))
        publicness = evidence.get("publicness", "public")
        if publicness == "public" and published_at and priced_through and published_at <= priced_through:
            if prior_context.get("prior_reliability_class") == "fresh_liquid":
                discount = assimilation_policy["old_public_evidence_discount_fresh_liquid"]
            else:
                discount = assimilation_policy["old_public_evidence_discount_default"]
            orthogonality_status = "not_orthogonal_to_market_prior"
            signed_delta_context = "discount_public_priced_through_market"
            reason_codes.append("old_public_evidence_priced_through_market")

    return {
        "schema_version": MARKET_ASSIMILATION_CONTEXT_SCHEMA_VERSION,
        "authority": "scae_assimilation_context_only_no_evidence_delta",
        "evidence_ref": evidence.get("evidence_ref") or evidence.get("evidence_id"),
        "market_assimilation_discount": discount,
        "suggested_signed_delta_multiplier": discount,
        "orthogonality_status": orthogonality_status,
        "signed_delta_context": signed_delta_context,
        "reason_codes": reason_codes,
    }
