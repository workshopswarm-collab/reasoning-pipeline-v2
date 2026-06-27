"""SCAE policy and probability taxonomy contracts for ADS v2."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


SCAE_POLICY_SCHEMA_VERSION = "scae-policy/v1"
SCAE_POLICY_ARTIFACT_TYPE = "scae_policy"
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / "scae-policy.json"

PROBABILITY_FIELDS = [
    "raw_ledger_probability",
    "post_ledger_probability",
    "debt_adjusted_probability",
    "production_forecast_prob",
    "canonical_probability",
]

FORECAST_VALIDITY_RANK = {
    "invalid_for_forecast": 0,
    "valid_for_forecast_watch_only": 1,
    "valid_for_forecast": 2,
}

EXECUTION_AUTHORITY_RANK = {
    "forbidden": 0,
    "needs_refresh": 1,
    "watch_only": 2,
    "low_size_only": 3,
    "normal_execution_allowed": 4,
}

MAX_EXECUTION_BY_VALIDITY = {
    "invalid_for_forecast": "forbidden",
    "valid_for_forecast_watch_only": "watch_only",
    "valid_for_forecast": "normal_execution_allowed",
}

AUTHORITY_BOUNDARY_FALSE_FIELDS = [
    "model_outputs_may_author_probability",
    "model_outputs_may_override_scae",
    "synthesis_may_author_probability",
    "synthesis_may_override_scae",
    "decision_may_author_probability",
    "decision_may_replace_probability",
    "decision_may_upgrade_forecast_validity",
]


class ScaePolicyError(ValueError):
    """Raised when the SCAE policy contract is malformed or unsafe."""


def load_scae_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    """Load a SCAE policy artifact from disk and validate it."""

    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_scae_policy(policy)
    return policy


def default_scae_policy() -> dict[str, Any]:
    """Return the repository default SCAE policy artifact."""

    return copy.deepcopy(load_scae_policy())


def validate_probability(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScaePolicyError(f"{field_name} must be a numeric probability")
    probability = float(value)
    if not 0.0 <= probability <= 1.0:
        raise ScaePolicyError(f"{field_name} must be in [0, 1]")
    return probability


def validate_scae_policy(policy: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "policy_id",
        "authority_boundary",
        "post_ledger_calibration",
        "calibration_debt",
        "cap_stack",
        "prior_reliability",
        "market_assimilation",
        "evidence_delta_mapping",
        "family_diagnostics",
        "temporal_missingness",
        "probability_taxonomy",
        "validity_and_execution",
    ]
    for field in required:
        if field not in policy:
            raise ScaePolicyError(f"policy.{field} is required")

    if policy["artifact_type"] != SCAE_POLICY_ARTIFACT_TYPE:
        raise ScaePolicyError(f"artifact_type must be {SCAE_POLICY_ARTIFACT_TYPE}")
    if policy["schema_version"] != SCAE_POLICY_SCHEMA_VERSION:
        raise ScaePolicyError(f"schema_version must be {SCAE_POLICY_SCHEMA_VERSION}")

    boundary = policy["authority_boundary"]
    if not isinstance(boundary, dict):
        raise ScaePolicyError("authority_boundary must be an object")
    if boundary.get("live_numeric_forecast_authority") != "scae":
        raise ScaePolicyError("SCAE must be the live numeric forecast authority")
    if boundary.get("scae_numeric_aggregation_uses_model") is not False:
        raise ScaePolicyError("SCAE numeric aggregation must not use model output")
    for field in AUTHORITY_BOUNDARY_FALSE_FIELDS:
        if boundary.get(field) is not False:
            raise ScaePolicyError(f"authority_boundary.{field} must be false")

    calibration = policy["post_ledger_calibration"]
    if calibration.get("default_method") != "identity":
        raise ScaePolicyError("post-ledger calibration default must be identity")
    if "identity" not in calibration.get("live_eligible_methods", []):
        raise ScaePolicyError("identity must be a live-eligible calibration method")
    if calibration.get("allow_beta_calibration_live_cutover") is not False:
        raise ScaePolicyError("beta calibration cannot affect live cutover")

    debt = policy["calibration_debt"]
    if not isinstance(debt.get("active"), bool):
        raise ScaePolicyError("calibration_debt.active must be a boolean")
    if debt.get("allowed_active_values") != [False, True]:
        raise ScaePolicyError("calibration_debt.allowed_active_values must be [false, true]")
    for field in [
        "tail_probability_floor",
        "tail_probability_ceiling",
        "minimum_interval_width_logit",
    ]:
        value = debt.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ScaePolicyError(f"calibration_debt.{field} must be a non-negative number")
    if debt["tail_probability_floor"] >= debt["tail_probability_ceiling"]:
        raise ScaePolicyError("calibration debt tail floor must be below tail ceiling")

    cap_stack = policy["cap_stack"]
    if not isinstance(cap_stack, dict):
        raise ScaePolicyError("cap_stack must be an object")
    for field in [
        "per_update_log_odds_cap",
        "per_cluster_log_odds_cap",
        "per_branch_log_odds_cap",
        "total_evidence_log_odds_cap",
        "debt_mode_total_evidence_log_odds_cap",
    ]:
        value = cap_stack.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ScaePolicyError(f"cap_stack.{field} must be a positive number")
    if cap_stack["debt_mode_total_evidence_log_odds_cap"] > cap_stack["total_evidence_log_odds_cap"]:
        raise ScaePolicyError("debt-mode total cap must not be looser than the normal total cap")
    if cap_stack.get("representative_selector") != "policy_bounded_signed_representative_v1":
        raise ScaePolicyError("cap_stack.representative_selector is not canonical")
    guard = cap_stack.get("correlated_quality_guard")
    if not isinstance(guard, dict):
        raise ScaePolicyError("cap_stack.correlated_quality_guard must be an object")
    if not isinstance(guard.get("enabled"), bool):
        raise ScaePolicyError("correlated_quality_guard.enabled must be a boolean")
    min_count = guard.get("repeated_group_min_count")
    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 2:
        raise ScaePolicyError("correlated_quality_guard.repeated_group_min_count must be an integer >= 2")
    multiplier_ceiling = guard.get("multiplier_ceiling")
    if (
        isinstance(multiplier_ceiling, bool)
        or not isinstance(multiplier_ceiling, (int, float))
        or not 0.0 < multiplier_ceiling <= 1.0
    ):
        raise ScaePolicyError("correlated_quality_guard.multiplier_ceiling must be in (0, 1]")

    prior_reliability = policy["prior_reliability"]
    for field in [
        "epsilon",
        "base_market_prior_reliability",
        "fresh_liquid_reliability_floor",
        "stale_thin_reliability_ceiling",
        "market_prior_min_reliability",
        "market_prior_max_reliability",
        "structural_prior_default_reliability",
        "neutral_prior_default_reliability",
    ]:
        value = prior_reliability.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScaePolicyError(f"prior_reliability.{field} must be numeric")
        if field == "epsilon":
            if not 0.0 < value < 0.5:
                raise ScaePolicyError("prior_reliability.epsilon must be in (0, 0.5)")
        elif not 0.0 <= value <= 1.0:
            raise ScaePolicyError(f"prior_reliability.{field} must be in [0, 1]")
    if prior_reliability["fresh_liquid_reliability_floor"] < prior_reliability["stale_thin_reliability_ceiling"]:
        raise ScaePolicyError("fresh/liquid reliability floor must be at least stale/thin ceiling")
    if prior_reliability["market_prior_min_reliability"] > prior_reliability["market_prior_max_reliability"]:
        raise ScaePolicyError("market prior min reliability cannot exceed max reliability")
    for field in [
        "tight_spread_threshold",
        "wide_spread_threshold",
        "deep_depth_threshold",
        "thin_depth_threshold",
        "liquid_volume_threshold",
        "thin_volume_threshold",
        "active_last_trade_seconds",
        "stale_last_trade_seconds",
    ]:
        value = prior_reliability.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ScaePolicyError(f"prior_reliability.{field} must be a non-negative number")
    if prior_reliability["tight_spread_threshold"] > prior_reliability["wide_spread_threshold"]:
        raise ScaePolicyError("tight spread threshold cannot exceed wide spread threshold")
    if prior_reliability["thin_depth_threshold"] > prior_reliability["deep_depth_threshold"]:
        raise ScaePolicyError("thin depth threshold cannot exceed deep depth threshold")
    if prior_reliability["thin_volume_threshold"] > prior_reliability["liquid_volume_threshold"]:
        raise ScaePolicyError("thin volume threshold cannot exceed liquid volume threshold")
    if prior_reliability["active_last_trade_seconds"] > prior_reliability["stale_last_trade_seconds"]:
        raise ScaePolicyError("active trade age threshold cannot exceed stale trade age threshold")

    market_assimilation = policy["market_assimilation"]
    for field in [
        "old_public_evidence_discount_fresh_liquid",
        "old_public_evidence_discount_default",
        "fresh_or_private_evidence_discount",
        "structural_prior_overlap_multiplier",
        "base_rate_overlap_multiplier",
    ]:
        value = market_assimilation.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            raise ScaePolicyError(f"market_assimilation.{field} must be in [0, 1]")
    if market_assimilation["structural_prior_overlap_multiplier"] != 0.0:
        raise ScaePolicyError("structural prior overlap must contribute zero signed delta")
    if market_assimilation["base_rate_overlap_multiplier"] != 0.0:
        raise ScaePolicyError("base-rate overlap must contribute zero signed delta")

    evidence_delta_mapping = policy["evidence_delta_mapping"]
    if evidence_delta_mapping.get("schema_version") != "scae-evidence-delta-mapping-policy/v1":
        raise ScaePolicyError("evidence delta mapping policy schema is invalid")
    strength_log_odds = evidence_delta_mapping.get("strength_log_odds")
    required_strengths = {"strong", "moderate", "weak", "none"}
    if not isinstance(strength_log_odds, dict) or set(strength_log_odds) != required_strengths:
        raise ScaePolicyError("evidence_delta_mapping.strength_log_odds is not canonical")
    for strength, value in strength_log_odds.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0:
            raise ScaePolicyError(f"evidence_delta_mapping.strength_log_odds.{strength} must be non-negative")
    if strength_log_odds["none"] != 0.0:
        raise ScaePolicyError("none evidence strength must map to zero")
    if not (
        strength_log_odds["strong"]
        >= strength_log_odds["moderate"]
        >= strength_log_odds["weak"]
        >= strength_log_odds["none"]
    ):
        raise ScaePolicyError("evidence strength log-odds mapping must be monotonic")

    direction_multipliers = evidence_delta_mapping.get("direction_multipliers")
    if direction_multipliers != {
        "supports_yes": 1.0,
        "supports_no": -1.0,
        "mixed": 0.0,
        "neutral": 0.0,
        "irrelevant": 0.0,
        "insufficient": 0.0,
    }:
        raise ScaePolicyError("evidence_delta_mapping.direction_multipliers is not canonical")
    if evidence_delta_mapping.get("classification_confidence_discounts") != {
        "high": 1.0,
        "medium": 0.6,
        "low": 0.0,
    }:
        raise ScaePolicyError("classification confidence discounts are not canonical")
    if evidence_delta_mapping.get("classification_quality_discounts") != {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.0,
        "unusable": 0.0,
    }:
        raise ScaePolicyError("classification quality discounts are not canonical")
    if evidence_delta_mapping.get("mixed_direction_behavior") != "branch_netting_candidate_no_direct_delta":
        raise ScaePolicyError("mixed direction behavior must require branch/netting candidate handling")
    if evidence_delta_mapping.get("non_scoreable_behavior") != "no_direct_delta_no_ledger_input":
        raise ScaePolicyError("non-scoreable classifications must not become ledger inputs")
    if evidence_delta_mapping.get("quality_multiplier_source") != "evidence_quality_verification_slices.final_quality_multiplier":
        raise ScaePolicyError("quality multiplier source must be VER-002 final quality multiplier")
    if (
        evidence_delta_mapping.get("market_assimilation_multiplier_source")
        != "market_assimilation_context.suggested_signed_delta_multiplier"
    ):
        raise ScaePolicyError("market assimilation multiplier source is invalid")
    if evidence_delta_mapping.get("per_update_cap_source") != "cap_stack.per_update_log_odds_cap":
        raise ScaePolicyError("per-update cap source must be cap_stack.per_update_log_odds_cap")
    if evidence_delta_mapping.get("missing_verification_behavior") != "fail_closed":
        raise ScaePolicyError("missing SCAE verification inputs must fail closed")
    if evidence_delta_mapping.get("output_authority") != "candidate_ledger_input_only_no_live_forecast_authority":
        raise ScaePolicyError("SCAE evidence deltas must remain candidate ledger inputs only")

    family_diagnostics = policy["family_diagnostics"]
    if family_diagnostics.get("schema_version") != "scae-family-diagnostics-policy/v1":
        raise ScaePolicyError("family diagnostics policy schema is invalid")
    if family_diagnostics.get("sibling_prices_context_only") is not True:
        raise ScaePolicyError("sibling prices must remain context-only")
    for field in [
        "allow_sibling_price_evidence_updates",
        "allow_sibling_softmax_reallocation",
        "allow_sibling_price_probability_movement",
    ]:
        if family_diagnostics.get(field) is not False:
            raise ScaePolicyError(f"family_diagnostics.{field} must be false")
    tolerance = family_diagnostics.get("exclusive_family_price_tolerance")
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0.0:
        raise ScaePolicyError("family_diagnostics.exclusive_family_price_tolerance must be non-negative")

    temporal_missingness = policy["temporal_missingness"]
    if temporal_missingness.get("schema_version") != "scae-temporal-missingness-policy/v1":
        raise ScaePolicyError("temporal missingness policy schema is invalid")
    if (
        temporal_missingness.get("output_authority")
        != "temporal_candidate_diagnostics_only_no_live_forecast_authority"
    ):
        raise ScaePolicyError("temporal missingness output authority must remain diagnostic/candidate-only")
    for field in [
        "missingness_requires_explicit_mechanism_proof",
        "no_catalyst_requires_source_coverage",
        "no_catalyst_requires_unpriced_interval",
        "no_catalyst_requires_distinct_absence_mechanism_proof",
    ]:
        if temporal_missingness.get(field) is not True:
            raise ScaePolicyError(f"temporal_missingness.{field} must be true")
    if temporal_missingness.get("allow_missingness_no_catalyst_same_mechanism_double_count") is not False:
        raise ScaePolicyError("temporal missingness/no-catalyst same-mechanism double count must be blocked")

    allowed_hazard_families = temporal_missingness.get("allowed_no_catalyst_hazard_families")
    required_hazard_families = [
        "continuous_arrival_hazard",
        "deadline_survival_hazard",
        "source_observable_arrival_hazard",
    ]
    if allowed_hazard_families != required_hazard_families:
        raise ScaePolicyError("temporal missingness allowed no-catalyst hazard families are not canonical")
    strength_map = temporal_missingness.get("missingness_strength_log_odds")
    required_missingness_strengths = {"strong", "moderate", "weak", "none", "unanswerable"}
    if not isinstance(strength_map, dict) or set(strength_map) != required_missingness_strengths:
        raise ScaePolicyError("temporal_missingness.missingness_strength_log_odds is not canonical")
    for strength, value in strength_map.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0:
            raise ScaePolicyError(f"temporal_missingness.missingness_strength_log_odds.{strength} must be non-negative")
    if strength_map["none"] != 0.0 or strength_map["unanswerable"] != 0.0:
        raise ScaePolicyError("none and unanswerable missingness strengths must map to zero")
    if not (
        strength_map["strong"]
        >= strength_map["moderate"]
        >= strength_map["weak"]
        >= strength_map["none"]
    ):
        raise ScaePolicyError("missingness strength mapping must be monotonic")
    if temporal_missingness.get("direction_multipliers") != {"supports_yes": 1.0, "supports_no": -1.0}:
        raise ScaePolicyError("temporal_missingness.direction_multipliers is not canonical")
    for field in ["max_missingness_log_odds_delta", "max_no_catalyst_log_odds_delta"]:
        value = temporal_missingness.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0.0:
            raise ScaePolicyError(f"temporal_missingness.{field} must be positive")
        if value > cap_stack["per_update_log_odds_cap"]:
            raise ScaePolicyError(f"temporal_missingness.{field} must not exceed per-update cap")

    taxonomy = policy["probability_taxonomy"]
    if taxonomy.get("fields") != PROBABILITY_FIELDS:
        raise ScaePolicyError("probability taxonomy fields are not canonical")
    if taxonomy.get("production_source_rule") != "debt_adjusted_when_calibration_debt_active_else_post_ledger":
        raise ScaePolicyError("probability taxonomy production rule is unsafe")
    if taxonomy.get("canonical_probability_aliases") != "production_forecast_prob":
        raise ScaePolicyError("canonical probability must alias production_forecast_prob")

    validity = policy["validity_and_execution"]
    if validity.get("forecast_validity_statuses") != list(FORECAST_VALIDITY_RANK):
        raise ScaePolicyError("forecast validity statuses are not canonical")
    if validity.get("execution_authority_statuses") != list(EXECUTION_AUTHORITY_RANK):
        raise ScaePolicyError("execution authority statuses are not canonical")
    if validity.get("max_execution_authority_by_forecast_validity") != MAX_EXECUTION_BY_VALIDITY:
        raise ScaePolicyError("validity/execution authority mapping is not canonical")


def resolve_probability_taxonomy(
    *,
    raw_ledger_probability: float,
    post_ledger_probability: float,
    debt_adjusted_probability: float,
    calibration_debt_active: bool,
) -> dict[str, float]:
    """Resolve production and canonical probability fields without doing ledger math."""

    raw = validate_probability(raw_ledger_probability, "raw_ledger_probability")
    post = validate_probability(post_ledger_probability, "post_ledger_probability")
    debt = validate_probability(debt_adjusted_probability, "debt_adjusted_probability")
    if not isinstance(calibration_debt_active, bool):
        raise ScaePolicyError("calibration_debt_active must be a boolean")

    production = debt if calibration_debt_active else post
    taxonomy = {
        "raw_ledger_probability": raw,
        "post_ledger_probability": post,
        "debt_adjusted_probability": debt,
        "production_forecast_prob": production,
        "canonical_probability": production,
    }
    validate_probability_taxonomy(taxonomy, calibration_debt_active=calibration_debt_active)
    return taxonomy


def validate_probability_taxonomy(
    taxonomy: dict[str, Any],
    *,
    calibration_debt_active: bool,
) -> None:
    for field in PROBABILITY_FIELDS:
        if field not in taxonomy:
            raise ScaePolicyError(f"{field} is required")
        validate_probability(taxonomy[field], field)
    expected_production = (
        taxonomy["debt_adjusted_probability"]
        if calibration_debt_active
        else taxonomy["post_ledger_probability"]
    )
    if taxonomy["production_forecast_prob"] != expected_production:
        raise ScaePolicyError("production_forecast_prob violates the SCAE taxonomy rule")
    if taxonomy["canonical_probability"] != taxonomy["production_forecast_prob"]:
        raise ScaePolicyError("canonical_probability must alias production_forecast_prob")


def validate_decision_authority(
    *,
    scae_forecast_validity_status: str,
    decision_forecast_validity_status: str | None = None,
    execution_authority_status: str,
) -> dict[str, str]:
    """Validate that a decision/actionability packet only preserves or downgrades SCAE status."""

    if scae_forecast_validity_status not in FORECAST_VALIDITY_RANK:
        raise ScaePolicyError(f"unknown SCAE validity status {scae_forecast_validity_status}")
    effective_validity = decision_forecast_validity_status or scae_forecast_validity_status
    if effective_validity not in FORECAST_VALIDITY_RANK:
        raise ScaePolicyError(f"unknown decision validity status {effective_validity}")
    if FORECAST_VALIDITY_RANK[effective_validity] > FORECAST_VALIDITY_RANK[scae_forecast_validity_status]:
        raise ScaePolicyError("decision/actionability cannot upgrade SCAE forecast validity")

    if execution_authority_status not in EXECUTION_AUTHORITY_RANK:
        raise ScaePolicyError(f"unknown execution authority status {execution_authority_status}")
    max_execution = MAX_EXECUTION_BY_VALIDITY[effective_validity]
    if EXECUTION_AUTHORITY_RANK[execution_authority_status] > EXECUTION_AUTHORITY_RANK[max_execution]:
        raise ScaePolicyError("execution authority cannot exceed SCAE forecast validity")

    return {
        "forecast_validity_status": effective_validity,
        "execution_authority_status": execution_authority_status,
    }
