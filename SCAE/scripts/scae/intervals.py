"""SCAE-011 pre-debt ledger probability and interval builders.

This module is the deterministic SCAE-owned handoff between candidate ledger
inputs and later research-sufficiency / calibration-debt gates. It emits raw
and post-ledger probabilities plus interval inputs, but it does not persist a
production forecast or apply calibration-debt controls.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from scae.policy import default_scae_policy, validate_probability
from scae.prior import logit, sigmoid


SCAE_PRE_DEBT_LEDGER_OUTPUT_SCHEMA_VERSION = "scae-pre-debt-ledger-output/v1"
SCAE_LOGIT_UNCERTAINTY_INTERVAL_SCHEMA_VERSION = "scae-logit-uncertainty-interval/v1"
SCAE_PRE_DEBT_LEDGER_SURFACE = "scae_pre_debt_ledger_outputs"
SCAE_011_INTERVAL_VERSION = "ads-scae-011-pre-debt-ledger-interval/v1"
LOGIT_UNCERTAINTY_WIDTH_VERSION = "logit_uncertainty_width_v1"
PRE_DEBT_LEDGER_AUTHORITY = "pre_debt_ledger_output_only_no_production_forecast_authority"
INTERVAL_COVERAGE_TARGET = "pre_debt_debug_interval_input_not_calibration_claim"
DELTA_INPUT_FIELDS = {
    "evidence": ("signed_log_odds_delta", "netted_signed_log_odds_delta"),
    "branch": ("branch_subledger_signed_log_odds_delta",),
    "conditional": (
        "conditional_signed_log_odds_delta",
        "conditional_recombined_signed_log_odds_delta",
        "conditional_recombined_log_odds_delta",
    ),
}
DELTA_REF_FIELDS = (
    "candidate_slice_id",
    "update_slice_id",
    "cluster_slice_id",
    "cross_leaf_dependency_slice_id",
    "branch_subledger_slice_id",
    "conditional_branch_slice_id",
    "conditional_branch_summary_id",
    "summary_id",
    "slice_id",
)


class ScaeIntervalError(ValueError):
    """Raised when pre-debt SCAE ledger or interval inputs are unsafe."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeIntervalError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ScaeIntervalError(f"{field_name} must be numeric") from exc


def _non_negative_numeric(value: Any, field_name: str) -> float:
    number = _numeric(value, field_name)
    if number < 0.0:
        raise ScaeIntervalError(f"{field_name} must be non-negative")
    return number


def _probability(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeIntervalError(f"{field_name} must be a probability")
    if isinstance(value, (int, float)):
        probability = float(value)
    else:
        try:
            probability = float(str(value))
        except (TypeError, ValueError) as exc:
            raise ScaeIntervalError(f"{field_name} must be a probability") from exc
    if not 0.0 <= probability <= 1.0:
        raise ScaeIntervalError(f"{field_name} must be in [0, 1]")
    return probability


def _rows_from(value: Any, field_names: tuple[str, ...]) -> list[dict[str, Any]]:
    if value is None:
        return []
    rows = value
    if isinstance(value, dict):
        rows = None
        for field_name in field_names:
            if field_name in value:
                rows = value[field_name]
                break
        if rows is None:
            if value.get("artifact_type") or any(field in value for field in DELTA_REF_FIELDS):
                return [value]
            raise ScaeIntervalError(f"{field_names[0]} must be a list")
        if isinstance(rows, dict):
            return [rows]
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ScaeIntervalError(f"{field_names[0]} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaeIntervalError(f"{field_names[0]} must contain objects")
        normalized.append(row)
    return normalized


def _input_ref(row: dict[str, Any]) -> str:
    for field in DELTA_REF_FIELDS:
        value = row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return _sha_id("scae-delta-input", row)


def _first_non_empty(rows: list[dict[str, Any]], field_name: str) -> Any:
    for row in rows:
        value = row.get(field_name)
        if value not in (None, ""):
            return value
    return None


def _prior_log_odds(prior_context: dict[str, Any], *, epsilon: float) -> tuple[float, float]:
    if "adjusted_prior_log_odds" in prior_context:
        prior_log_odds = round(_numeric(prior_context["adjusted_prior_log_odds"], "adjusted_prior_log_odds"), 9)
        return prior_log_odds, round(sigmoid(prior_log_odds), 9)
    if "adjusted_prior_probability" in prior_context:
        probability = _probability(prior_context["adjusted_prior_probability"], "adjusted_prior_probability")
        return round(logit(probability, epsilon), 9), round(probability, 9)
    raise ScaeIntervalError("prior_context.adjusted_prior_log_odds is required")


def _accepted_delta_input(row: dict[str, Any], source_kind: str) -> bool:
    if row.get("accepted_for_pre_debt_ledger_input") is True:
        return True
    if source_kind == "evidence":
        return row.get("accepted_for_ledger_input") is True
    if source_kind == "branch":
        return row.get("accepted_for_candidate_ledger_input") is True
    if source_kind == "conditional":
        return (
            row.get("accepted_for_pre_debt_ledger_input") is True
            or row.get("conditional_recombination_status") == "built"
        )
    return False


def _explicit_delta(row: dict[str, Any], source_kind: str) -> float | None:
    for field_name in DELTA_INPUT_FIELDS[source_kind]:
        if field_name in row:
            return round(_numeric(row[field_name], field_name), 9)
    return None


def _conditional_delta_from_probability(
    row: dict[str, Any],
    *,
    adjusted_prior_log_odds: float,
    epsilon: float,
) -> float | None:
    if "conditional_recombined_probability_candidate" not in row:
        return None
    probability = _probability(
        row["conditional_recombined_probability_candidate"],
        "conditional_recombined_probability_candidate",
    )
    return round(logit(probability, epsilon) - adjusted_prior_log_odds, 9)


def _collect_delta_inputs(
    rows: list[dict[str, Any]],
    *,
    source_kind: str,
    adjusted_prior_log_odds: float,
    epsilon: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    excluded_refs: list[str] = []
    for row in rows:
        row_copy = copy.deepcopy(row)
        ref = _input_ref(row_copy)
        if not _accepted_delta_input(row_copy, source_kind):
            excluded_refs.append(ref)
            continue
        delta = _explicit_delta(row_copy, source_kind)
        derivation = "explicit_signed_log_odds_delta"
        if delta is None and source_kind == "conditional":
            delta = _conditional_delta_from_probability(
                row_copy,
                adjusted_prior_log_odds=adjusted_prior_log_odds,
                epsilon=epsilon,
            )
            derivation = "conditional_probability_candidate_minus_adjusted_prior"
        if delta is None:
            raise ScaeIntervalError(f"{source_kind} input {ref} is missing a signed log-odds delta")
        accepted.append(
            {
                "delta_input_ref": ref,
                "source_kind": source_kind,
                "signed_log_odds_delta": round(delta, 9),
                "delta_derivation": derivation,
                "feature_id": row_copy.get("feature_id"),
                "case_id": row_copy.get("case_id"),
                "dispatch_id": row_copy.get("dispatch_id"),
                "parent_branch_id": row_copy.get("parent_branch_id"),
                "condition_scope": row_copy.get("condition_scope"),
                "ledger_input_authority": row_copy.get("ledger_input_authority"),
            }
        )
    return sorted(accepted, key=lambda item: (item["source_kind"], item["delta_input_ref"])), sorted(excluded_refs)


def _cap_signed_delta(delta: float, cap: float) -> tuple[float, bool]:
    if abs(delta) <= cap:
        return round(delta, 9), False
    return round(cap if delta > 0.0 else -cap, 9), True


def _normalize_width_component(component: dict[str, Any]) -> dict[str, Any]:
    component_id = component.get("component_id") or component.get("width_component_id")
    if not _is_non_empty_string(component_id):
        raise ScaeIntervalError("width component is missing component_id")
    if "half_width_logit" in component:
        half_width = _non_negative_numeric(component["half_width_logit"], "half_width_logit")
    elif "width_logit" in component:
        half_width = _non_negative_numeric(component["width_logit"], "width_logit")
    else:
        raise ScaeIntervalError(f"width component {component_id} is missing half_width_logit")
    reason_codes = component.get("reason_codes") or []
    if not isinstance(reason_codes, list):
        raise ScaeIntervalError(f"width component {component_id} reason_codes must be a list")
    source_refs = component.get("source_refs") or component.get("input_refs") or []
    if not isinstance(source_refs, list):
        raise ScaeIntervalError(f"width component {component_id} source_refs must be a list")
    return {
        "component_id": str(component_id),
        "component_type": component.get("component_type") or component.get("width_component_type") or "diagnostic",
        "half_width_logit": round(half_width, 9),
        "reason_codes": sorted(str(code) for code in reason_codes if _is_non_empty_string(code)),
        "source_refs": sorted(str(ref) for ref in source_refs if _is_non_empty_string(ref)),
        "can_tighten_interval": False,
    }


def build_logit_uncertainty_interval(
    *,
    post_logit: float,
    width_components: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic probability interval from logit half-widths."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    center_log_odds = round(_numeric(post_logit, "post_logit"), 9)
    normalized_components = sorted(
        [_normalize_width_component(component) for component in (width_components or [])],
        key=lambda item: item["component_id"],
    )
    total_half_width = round(sum(component["half_width_logit"] for component in normalized_components), 9)
    lower_log_odds = round(center_log_odds - total_half_width, 9)
    upper_log_odds = round(center_log_odds + total_half_width, 9)
    interval = {
        "artifact_type": "scae_logit_uncertainty_interval",
        "schema_version": SCAE_LOGIT_UNCERTAINTY_INTERVAL_SCHEMA_VERSION,
        "feature_id": "SCAE-011",
        "interval_builder_version": SCAE_011_INTERVAL_VERSION,
        "interval_width_version": LOGIT_UNCERTAINTY_WIDTH_VERSION,
        "coverage_target": INTERVAL_COVERAGE_TARGET,
        "policy_snapshot_id": active_policy.get("policy_id"),
        "center_log_odds": center_log_odds,
        "total_half_width_logit": total_half_width,
        "lower_log_odds": lower_log_odds,
        "upper_log_odds": upper_log_odds,
        "lower_probability": round(sigmoid(lower_log_odds), 9),
        "upper_probability": round(sigmoid(upper_log_odds), 9),
        "width_components": normalized_components,
        "component_count": len(normalized_components),
        "deterministic": True,
        "calibration_debt_minimum_width_applied": False,
        "live_forecast_authority": False,
    }
    interval["interval_id"] = _sha_id("scae-logit-interval", interval)
    interval["interval_digest"] = _prefixed_sha256(interval)
    return interval


def apply_post_ledger_calibration(
    raw_ledger_probability: float,
    *,
    policy: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Apply the SCAE post-ledger calibration policy for the pre-debt stage."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    calibration_policy = active_policy.get("post_ledger_calibration")
    if not isinstance(calibration_policy, dict):
        raise ScaeIntervalError("policy.post_ledger_calibration is required")
    method = calibration_policy.get("default_method")
    if method != "identity":
        raise ScaeIntervalError("SCAE-011 only supports identity post-ledger calibration")
    raw = round(validate_probability(raw_ledger_probability, "raw_ledger_probability"), 9)
    context = {
        "schema_version": "scae-post-ledger-calibration-context/v1",
        "feature_id": "SCAE-011",
        "policy_snapshot_id": active_policy.get("policy_id"),
        "post_ledger_calibration_method": "identity",
        "live_eligible_method": "identity" in calibration_policy.get("live_eligible_methods", []),
        "non_identity_calibration_applied": False,
        "calibration_debt_controls_applied": False,
        "calibration_authority_stage": "pre_debt_post_ledger_only",
    }
    return raw, context


def build_pre_debt_ledger_output(
    prior_context: dict[str, Any],
    *,
    evidence_delta_slices: dict[str, Any] | list[dict[str, Any]] | None = None,
    branch_subledger_slices: dict[str, Any] | list[dict[str, Any]] | None = None,
    conditional_delta_slices: dict[str, Any] | list[dict[str, Any]] | None = None,
    width_components: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a SCAE-011 pre-debt ledger output artifact."""

    if not isinstance(prior_context, dict):
        raise ScaeIntervalError("prior_context must be an object")
    active_policy = copy.deepcopy(policy or default_scae_policy())
    cap_stack = active_policy.get("cap_stack")
    if not isinstance(cap_stack, dict):
        raise ScaeIntervalError("policy.cap_stack is required")
    epsilon = _numeric(active_policy.get("prior_reliability", {}).get("epsilon"), "prior_reliability.epsilon")
    adjusted_prior_log_odds, adjusted_prior_probability = _prior_log_odds(prior_context, epsilon=epsilon)

    evidence_rows = _rows_from(evidence_delta_slices, ("candidate_slices", "evidence_delta_slices"))
    branch_rows = _rows_from(branch_subledger_slices, ("branch_subledger_slices",))
    conditional_rows = _rows_from(
        conditional_delta_slices,
        (
            "conditional_delta_slices",
            "conditional_branch_summary",
            "conditional_branch_summaries",
            "conditional_branch_slices",
        ),
    )
    evidence_inputs, excluded_evidence_refs = _collect_delta_inputs(
        evidence_rows,
        source_kind="evidence",
        adjusted_prior_log_odds=adjusted_prior_log_odds,
        epsilon=epsilon,
    )
    branch_inputs, excluded_branch_refs = _collect_delta_inputs(
        branch_rows,
        source_kind="branch",
        adjusted_prior_log_odds=adjusted_prior_log_odds,
        epsilon=epsilon,
    )
    conditional_inputs, excluded_conditional_refs = _collect_delta_inputs(
        conditional_rows,
        source_kind="conditional",
        adjusted_prior_log_odds=adjusted_prior_log_odds,
        epsilon=epsilon,
    )
    accepted_delta_inputs = sorted(
        [*evidence_inputs, *branch_inputs, *conditional_inputs],
        key=lambda item: (item["source_kind"], item["delta_input_ref"]),
    )

    evidence_delta_sum = round(sum(item["signed_log_odds_delta"] for item in evidence_inputs), 9)
    branch_delta_sum = round(sum(item["signed_log_odds_delta"] for item in branch_inputs), 9)
    conditional_delta_sum = round(sum(item["signed_log_odds_delta"] for item in conditional_inputs), 9)
    pre_cap_total_evidence_delta = round(
        evidence_delta_sum + branch_delta_sum + conditional_delta_sum,
        9,
    )
    total_evidence_cap = _non_negative_numeric(
        cap_stack.get("total_evidence_log_odds_cap"),
        "total_evidence_log_odds_cap",
    )
    total_evidence_delta, bounded_by_total_cap = _cap_signed_delta(
        pre_cap_total_evidence_delta,
        total_evidence_cap,
    )
    posterior_log_odds = round(adjusted_prior_log_odds + total_evidence_delta, 9)
    raw_ledger_probability = round(sigmoid(posterior_log_odds), 9)
    post_ledger_probability, calibration_context = apply_post_ledger_calibration(
        raw_ledger_probability,
        policy=active_policy,
    )
    interval = build_logit_uncertainty_interval(
        post_logit=posterior_log_odds,
        width_components=width_components,
        policy=active_policy,
    )
    all_rows = [prior_context, *evidence_rows, *branch_rows, *conditional_rows]
    output = {
        "artifact_type": "scae_pre_debt_ledger_output",
        "schema_version": SCAE_PRE_DEBT_LEDGER_OUTPUT_SCHEMA_VERSION,
        "feature_id": "SCAE-011",
        "surface_name": SCAE_PRE_DEBT_LEDGER_SURFACE,
        "authority": PRE_DEBT_LEDGER_AUTHORITY,
        "case_id": prior_context.get("case_id") or _first_non_empty(all_rows, "case_id"),
        "dispatch_id": prior_context.get("dispatch_id") or _first_non_empty(all_rows, "dispatch_id"),
        "prior_context_ref": prior_context.get("prior_context_id") or prior_context.get("prior_context_ref"),
        "adjusted_prior_log_odds": adjusted_prior_log_odds,
        "adjusted_prior_probability": adjusted_prior_probability,
        "evidence_signed_log_odds_delta": evidence_delta_sum,
        "branch_signed_log_odds_delta": branch_delta_sum,
        "conditional_signed_log_odds_delta": conditional_delta_sum,
        "pre_cap_total_evidence_log_odds_delta": pre_cap_total_evidence_delta,
        "total_evidence_log_odds_cap": total_evidence_cap,
        "total_evidence_log_odds_delta": total_evidence_delta,
        "bounded_by_total_evidence_cap": bounded_by_total_cap,
        "posterior_log_odds": posterior_log_odds,
        "raw_ledger_probability": raw_ledger_probability,
        "post_ledger_probability": post_ledger_probability,
        "delta_input_count": len(accepted_delta_inputs),
        "accepted_delta_inputs": accepted_delta_inputs,
        "excluded_delta_input_refs": {
            "evidence": excluded_evidence_refs,
            "branch": excluded_branch_refs,
            "conditional": excluded_conditional_refs,
        },
        "cap_stack_snapshot": {
            "policy_snapshot_id": active_policy.get("policy_id"),
            "total_evidence_log_odds_cap": total_evidence_cap,
            "per_update_log_odds_cap": cap_stack.get("per_update_log_odds_cap"),
            "per_cluster_log_odds_cap": cap_stack.get("per_cluster_log_odds_cap"),
            "per_branch_log_odds_cap": cap_stack.get("per_branch_log_odds_cap"),
            "debt_mode_total_evidence_log_odds_cap_recorded_not_applied": cap_stack.get(
                "debt_mode_total_evidence_log_odds_cap"
            ),
        },
        "calibration_context": calibration_context,
        "interval": interval,
        "pre_debt_output_stage": "post_ledger_calibrated_before_sufficiency_and_debt_controls",
        "ledger_input_authority": PRE_DEBT_LEDGER_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "writes_persistence": False,
        "not_implemented_scope": [
            "SCAE-013_research_sufficiency_forecast_validity",
            "SCAE-012_calibration_debt_controls",
            "production_forecast_persistence",
            "decision_authority",
            "replay_scoring",
            "calibration_tuning_promotions",
        ],
        "pre_debt_ledger_version": SCAE_011_INTERVAL_VERSION,
    }
    output["pre_debt_ledger_output_id"] = _sha_id("scae-pre-debt-ledger", output)
    output["pre_debt_ledger_output_digest"] = _prefixed_sha256(output)
    return output


def finalize_pre_debt_ledger(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility alias for callers that use the plan's finalize wording."""

    return build_pre_debt_ledger_output(*args, **kwargs)


def finalize_ledger(
    adjusted_prior_log_odds: float,
    branch_deltas: list[float],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Small plan-pseudocode adapter for tests and fixtures."""

    branch_slices = [
        {
            "branch_subledger_slice_id": f"inline-branch-delta:{index}",
            "branch_subledger_signed_log_odds_delta": delta,
            "accepted_for_candidate_ledger_input": True,
        }
        for index, delta in enumerate(branch_deltas)
    ]
    return build_pre_debt_ledger_output(
        {"adjusted_prior_log_odds": adjusted_prior_log_odds},
        branch_subledger_slices=branch_slices,
        policy=policy,
    )
