"""SCAE-010 conditional AMRG branch recombination.

This module consumes SCAE-007 branch sub-ledgers plus a validated AMRG
strict-precedence anchor and QDT anchor dependency contract. It emits
candidate-only conditional branch audit slices and recombination math; it does
not author final SCAE ledger probability fields or production forecasts.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from scae.policy import default_scae_policy
from scae.prior import logit, sigmoid


SCAE_CONDITIONAL_BRANCH_SLICE_SCHEMA_VERSION = "scae-conditional-branch-slice/v1"
SCAE_CONDITIONAL_BRANCH_SUMMARY_SCHEMA_VERSION = "scae-conditional-branch-summary/v1"
SCAE_CONDITIONAL_BRANCH_BUNDLE_SCHEMA_VERSION = "scae-conditional-branch-bundle/v1"
SCAE_010_CONDITIONAL_RECOMBINATION_VERSION = "ads-scae-010-conditional-branch-recombination/v1"
SCAE_CONDITIONAL_BRANCH_SURFACE = "scae_conditional_branch_slices"
NO_LIVE_AUTHORITY = "conditional_math_candidate_only_no_live_forecast_authority"
VALIDATED_STRICT_PRECEDENCE_ANCHOR = "validated_strict_precedence_anchor"
TARGET_GIVEN_UPSTREAM = "target_given_upstream"
TARGET_GIVEN_NOT_UPSTREAM = "target_given_not_upstream"
CONDITION_SCOPES = {TARGET_GIVEN_UPSTREAM, TARGET_GIVEN_NOT_UPSTREAM}
ALLOWED_REPAIR_EXHAUSTION_POLICIES = {
    "watch_only_if_forecastable",
    "fail_dispatch_preparation",
}
BLOCKING_ANCHOR_STATUS_VALUES = {
    "blocked_cycle_or_concurrent_timing",
    "cycle_detected",
    "cycle_or_concurrent_rejected",
    "cycle_rejected",
    "cyclic",
    "rejected",
    "rejected_strict_precedence_anchor",
    "timing_mismatch_weak_context_only",
    "weak_context_only",
}
BLOCKING_ANCHOR_REASON_CODES = {
    "causal_graph_cycle_rejected",
    "causal_graph_nodes_missing",
    "concurrent_event_time",
    "edge_not_strict_precedence_anchor_candidate",
    "invalid_strict_precedence_event_time",
    "missing_causal_upstream_relationship",
    "reflexive_causal_edge_rejected",
    "strict_precedence_not_proven",
    "timing_alignment_not_aligned",
    "upstream_event_not_before_target",
}


class ScaeConditionalBranchError(ValueError):
    """Raised when conditional branch recombination cannot safely continue."""


@dataclass(frozen=True)
class ConditionalBranchResult:
    conditional_branch_slices: list[dict[str, Any]]
    conditional_branch_summary: dict[str, Any]
    excluded_branch_subledger_refs: list[str]
    conditional_branch_bundle_digest: str


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
        raise ScaeConditionalBranchError(f"{field_name} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaeConditionalBranchError(f"{field_name} must contain objects")
        normalized.append(row)
    return normalized


def _probability(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeConditionalBranchError(f"{field_name} must be a probability")
    if isinstance(value, (int, float)):
        probability = float(value)
    else:
        try:
            probability = float(str(value))
        except (TypeError, ValueError) as exc:
            raise ScaeConditionalBranchError(f"{field_name} must be a probability") from exc
    if not 0.0 <= probability <= 1.0:
        raise ScaeConditionalBranchError(f"{field_name} must be in [0, 1]")
    return probability


def _numeric(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ScaeConditionalBranchError(f"{field_name} must be numeric")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError) as exc:
        raise ScaeConditionalBranchError(f"{field_name} must be numeric") from exc


def _branch_subledger_id(slice_row: dict[str, Any]) -> str:
    for field in ("branch_subledger_slice_id", "slice_id"):
        value = slice_row.get(field)
        if _is_non_empty_string(value):
            return str(value)
    raise ScaeConditionalBranchError("branch subledger slice is missing branch_subledger_slice_id")


def _branch_delta(slice_row: dict[str, Any]) -> float:
    return round(_numeric(slice_row.get("branch_subledger_signed_log_odds_delta"), "branch_subledger_signed_log_odds_delta"), 9)


def _qdt_required_leaves(qdt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    leaves: dict[str, dict[str, Any]] = {}
    for leaf in qdt.get("required_leaf_questions") or []:
        if isinstance(leaf, dict) and _is_non_empty_string(leaf.get("leaf_id")):
            leaves[str(leaf["leaf_id"])] = leaf
    return leaves


def _condition_scope(leaf: dict[str, Any]) -> str | None:
    value = leaf.get("leaf_condition_scope") or leaf.get("condition_scope")
    if _is_non_empty_string(value):
        return str(value)
    return None


def _select_anchor_contract(qdt: dict[str, Any], amrg_anchor: dict[str, Any]) -> dict[str, Any] | None:
    contracts = qdt.get("amrg_anchor_dependency_contracts") or []
    if not isinstance(contracts, list):
        return None
    anchor_contract_id = amrg_anchor.get("anchor_dependency_contract_id")
    anchor_edge_id = amrg_anchor.get("edge_id")
    candidates = [contract for contract in contracts if isinstance(contract, dict)]
    if _is_non_empty_string(anchor_contract_id):
        matching = [
            contract
            for contract in candidates
            if contract.get("anchor_dependency_contract_id") == anchor_contract_id
        ]
        if matching:
            return copy.deepcopy(matching[0])
    if _is_non_empty_string(anchor_edge_id):
        matching = [contract for contract in candidates if contract.get("edge_id") == anchor_edge_id]
        if matching:
            return copy.deepcopy(matching[0])
    if len(candidates) == 1:
        return copy.deepcopy(candidates[0])
    return None


def _anchor_contract_rejection_reasons(contract: dict[str, Any] | None, leaves_by_id: dict[str, dict[str, Any]]) -> list[str]:
    if not isinstance(contract, dict):
        return ["missing_qdt_anchor_dependency_contract"]
    reasons: list[str] = []
    if contract.get("anchor_mode") != "anchor_required":
        reasons.append("qdt_anchor_mode_not_required")
    if contract.get("edge_status") != VALIDATED_STRICT_PRECEDENCE_ANCHOR:
        reasons.append("qdt_anchor_edge_not_validated_strict_precedence")
    condition_scoped_leaf_ids = contract.get("condition_scoped_leaf_ids")
    if not isinstance(condition_scoped_leaf_ids, list) or not condition_scoped_leaf_ids:
        reasons.append("missing_qdt_condition_scoped_leaf_support")
    else:
        scopes = {
            _condition_scope(leaves_by_id.get(str(leaf_id), {}))
            for leaf_id in condition_scoped_leaf_ids
        }
        if not CONDITION_SCOPES.issubset(scopes):
            reasons.append("missing_required_condition_scope_pair")
    if not isinstance(contract.get("fallback_policy"), dict):
        reasons.append("missing_qdt_anchor_fallback_policy")
    for field in ("max_anchor_repair_attempts", "max_anchor_repair_wall_clock_seconds"):
        if not isinstance(contract.get(field), int) or isinstance(contract.get(field), bool) or contract.get(field) < 0:
            reasons.append(f"invalid_{field}")
    if contract.get("repair_exhaustion_policy") not in ALLOWED_REPAIR_EXHAUSTION_POLICIES:
        reasons.append("invalid_repair_exhaustion_policy")
    return sorted(set(reasons))


def _anchor_is_validated(amrg_anchor: dict[str, Any]) -> bool:
    if _explicit_anchor_blocker_reasons(amrg_anchor):
        return False
    status_values = [
        amrg_anchor.get("relationship_status"),
        amrg_anchor.get("edge_status"),
        amrg_anchor.get("causal_edge_role"),
    ]
    if VALIDATED_STRICT_PRECEDENCE_ANCHOR in status_values:
        return True
    return (
        amrg_anchor.get("validation_status") == "validated"
        and amrg_anchor.get("allowed_use") == "condition_scoped_anchor_validation_input"
    )


def _anchor_reason_codes(amrg_anchor: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for field in ("anchor_validation_reason_codes", "reason_codes", "validation_reason_codes"):
        value = amrg_anchor.get(field)
        if isinstance(value, list):
            codes.extend(str(code) for code in value if _is_non_empty_string(code))
    return sorted(set(codes))


def _explicit_anchor_blocker_reasons(amrg_anchor: dict[str, Any]) -> list[str]:
    reasons: set[str] = set()
    for field in (
        "relationship_status",
        "edge_status",
        "causal_graph_status",
        "cycle_status",
        "causal_edge_role",
        "anchor_validation_status",
        "validation_status",
    ):
        value = amrg_anchor.get(field)
        if not _is_non_empty_string(value):
            continue
        normalized = str(value).strip()
        if normalized in BLOCKING_ANCHOR_STATUS_VALUES:
            reasons.add(normalized)
    for code in _anchor_reason_codes(amrg_anchor):
        if code in BLOCKING_ANCHOR_REASON_CODES:
            reasons.add(code)
    return sorted(reasons)


def _anchor_rejection_reasons(amrg_anchor: dict[str, Any]) -> list[str]:
    if _anchor_is_validated(amrg_anchor):
        return []
    reasons = _explicit_anchor_blocker_reasons(amrg_anchor)
    reasons.extend(_anchor_reason_codes(amrg_anchor))
    status = (
        amrg_anchor.get("relationship_status")
        or amrg_anchor.get("edge_status")
        or amrg_anchor.get("validation_status")
        or "unknown"
    )
    reasons.append(f"amrg_anchor_not_validated:{status}")
    return sorted(set(reasons))


def _anchor_probability_context(amrg_anchor: dict[str, Any]) -> tuple[float | None, dict[str, Any], list[str]]:
    reasons: list[str] = []
    probability_value = amrg_anchor.get("adjusted_upstream_probability")
    upstream_context = amrg_anchor.get("upstream_prior_context")
    if probability_value is None and isinstance(upstream_context, dict):
        probability_value = upstream_context.get("adjusted_prior_probability")
    probability: float | None = None
    if probability_value is None:
        reasons.append("missing_adjusted_upstream_probability")
    else:
        probability = _probability(probability_value, "adjusted_upstream_probability")

    reliability_context = amrg_anchor.get("upstream_prior_reliability_context")
    if not isinstance(reliability_context, dict) or not reliability_context:
        if isinstance(upstream_context, dict) and upstream_context:
            reliability_context = upstream_context
        else:
            reliability_context = {}
            reasons.append("missing_upstream_prior_reliability_context")
    return probability, copy.deepcopy(reliability_context), reasons


def _repair_audit(
    *,
    contract: dict[str, Any] | None,
    repair_state: dict[str, Any] | None,
    reason_codes: list[str],
) -> dict[str, Any]:
    contract = contract or {}
    fallback_policy = contract.get("fallback_policy") if isinstance(contract.get("fallback_policy"), dict) else {}
    max_attempts = contract.get("max_anchor_repair_attempts")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 0:
        max_attempts = 0
    attempts_used = 0
    if isinstance(repair_state, dict):
        raw_attempts = repair_state.get("repair_attempts_used", repair_state.get("attempts_used", 0))
        if isinstance(raw_attempts, int) and not isinstance(raw_attempts, bool) and raw_attempts >= 0:
            attempts_used = raw_attempts
    exhausted = bool(isinstance(repair_state, dict) and repair_state.get("repair_budget_exhausted") is True)
    exhausted = exhausted or attempts_used >= max_attempts
    attempts_remaining = max(0, max_attempts - attempts_used)
    repair_exhaustion_policy = contract.get("repair_exhaustion_policy") or "fail_dispatch_preparation"
    fallback_mode = fallback_policy.get("fallback_mode") or repair_exhaustion_policy
    if not exhausted and attempts_remaining > 0:
        status = "rejected_anchor_repair_required"
    elif fallback_mode == "watch_only_if_forecastable" or repair_exhaustion_policy == "watch_only_if_forecastable":
        status = "rejected_watch_only_if_forecastable"
    elif fallback_mode == "use_unconditional_fallback_leaf":
        status = "rejected_use_unconditional_fallback_leaf"
    else:
        status = "rejected_fail_dispatch_preparation"
    return {
        "fallback_status": status,
        "fallback_policy": copy.deepcopy(fallback_policy),
        "repair_exhaustion_policy": repair_exhaustion_policy,
        "max_anchor_repair_attempts": max_attempts,
        "repair_attempts_used": attempts_used,
        "repair_attempts_remaining": attempts_remaining,
        "repair_budget_exhausted": exhausted,
        "repair_loop_allowed": False,
        "reason_codes": sorted(set(reason_codes)),
    }


def _branch_condition_scope(slice_row: dict[str, Any], leaves_by_id: dict[str, dict[str, Any]]) -> str | None:
    scopes = {
        _condition_scope(leaves_by_id.get(str(leaf_id), {}))
        for leaf_id in slice_row.get("leaf_ids") or []
        if _is_non_empty_string(leaf_id)
    }
    target_scopes = sorted(scope for scope in scopes if scope in CONDITION_SCOPES)
    if len(target_scopes) > 1:
        raise ScaeConditionalBranchError(f"{_branch_subledger_id(slice_row)} spans multiple conditional scopes")
    return target_scopes[0] if target_scopes else None


def _branch_prior_metadata(slice_rows: list[dict[str, Any]], condition_scope: str) -> dict[str, Any]:
    if not slice_rows:
        raise ScaeConditionalBranchError(f"{condition_scope} branch sub-ledgers are required")
    metadata = copy.deepcopy(slice_rows[0].get("branch_metadata") or {})
    for row in slice_rows[1:]:
        row_metadata = row.get("branch_metadata") or {}
        for field in (
            "conditional_prior_probability",
            "branch_prior_probability",
            "conditional_prior_source",
            "branch_prior_derivation_method",
            "branch_prior_source_ref",
            "selected_market_prior_used_in_branch",
        ):
            if field in metadata or field in row_metadata:
                if metadata.get(field) != row_metadata.get(field):
                    raise ScaeConditionalBranchError(f"{condition_scope} branch prior metadata is inconsistent")
    selected_market_prior_used = metadata.get("selected_market_prior_used_in_branch")
    if selected_market_prior_used not in (False, "diagnostic_only"):
        raise ScaeConditionalBranchError("selected market prior cannot be reused as a conditional branch prior")
    probability = metadata.get("conditional_prior_probability")
    if probability is None:
        probability = metadata.get("branch_prior_probability")
    prior_source = metadata.get("conditional_prior_source")
    derivation_method = metadata.get("branch_prior_derivation_method")
    source_ref = metadata.get("branch_prior_source_ref")
    missing = [
        field
        for field, value in (
            ("conditional_prior_probability", probability),
            ("conditional_prior_source", prior_source),
            ("branch_prior_derivation_method", derivation_method),
            ("branch_prior_source_ref", source_ref),
            ("selected_market_prior_used_in_branch", selected_market_prior_used),
        )
        if value is None or value == ""
    ]
    if missing:
        raise ScaeConditionalBranchError(f"{condition_scope} branch prior metadata missing {', '.join(missing)}")
    return {
        "conditional_prior_probability": _probability(probability, f"{condition_scope}.conditional_prior_probability"),
        "conditional_prior_source": str(prior_source),
        "branch_prior_derivation_method": str(derivation_method),
        "branch_prior_source_ref": str(source_ref),
        "selected_market_prior_used_in_branch": selected_market_prior_used,
    }


def _condition_branch_slice(
    condition_scope: str,
    slice_rows: list[dict[str, Any]],
    *,
    epsilon: float,
    contract: dict[str, Any],
) -> dict[str, Any]:
    prior_metadata = _branch_prior_metadata(slice_rows, condition_scope)
    branch_delta = round(sum(_branch_delta(row) for row in slice_rows), 9)
    prior_log_odds = logit(prior_metadata["conditional_prior_probability"], epsilon)
    conditional_log_odds = prior_log_odds + branch_delta
    conditional_probability = round(sigmoid(conditional_log_odds), 9)
    row = {
        "artifact_type": "scae_conditional_branch_slice",
        "schema_version": SCAE_CONDITIONAL_BRANCH_SLICE_SCHEMA_VERSION,
        "feature_id": "SCAE-010",
        "surface_name": SCAE_CONDITIONAL_BRANCH_SURFACE,
        "condition_scope": condition_scope,
        "anchor_dependency_contract_id": contract.get("anchor_dependency_contract_id"),
        "conditional_branch_group_id": contract.get("conditional_branch_group_id"),
        "branch_subledger_slice_refs": [_branch_subledger_id(branch) for branch in slice_rows],
        "parent_branch_ids": sorted({str(branch.get("parent_branch_id")) for branch in slice_rows if _is_non_empty_string(branch.get("parent_branch_id"))}),
        "leaf_ids": sorted(
            {
                str(leaf_id)
                for branch in slice_rows
                for leaf_id in branch.get("leaf_ids", [])
                if _is_non_empty_string(leaf_id)
            }
        ),
        "conditional_prior_source": prior_metadata["conditional_prior_source"],
        "branch_prior_derivation_method": prior_metadata["branch_prior_derivation_method"],
        "branch_prior_source_ref": prior_metadata["branch_prior_source_ref"],
        "selected_market_prior_used_in_branch": prior_metadata["selected_market_prior_used_in_branch"],
        "conditional_prior_probability": prior_metadata["conditional_prior_probability"],
        "conditional_prior_log_odds": prior_log_odds,
        "branch_subledger_signed_log_odds_delta": branch_delta,
        "conditional_branch_log_odds_candidate": conditional_log_odds,
        "conditional_branch_probability_candidate": conditional_probability,
        "accepted_for_conditional_recombination": True,
        "ledger_input_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "not_implemented_scope": [
            "SCAE-011_final_probability_fields",
            "SCAE-012_research_sufficiency_forecast_validity",
            "SCAE-013_calibration_debt_gate",
        ],
        "conditional_recombination_version": SCAE_010_CONDITIONAL_RECOMBINATION_VERSION,
    }
    row["conditional_branch_slice_id"] = _sha_id("scae-conditional-branch", row)
    row["conditional_branch_slice_digest"] = _prefixed_sha256(row)
    return row


def _summary(
    *,
    status: str,
    contract: dict[str, Any] | None,
    anchor: dict[str, Any],
    conditional_branch_slices: list[dict[str, Any]],
    adjusted_upstream_probability: float | None,
    upstream_reliability_context: dict[str, Any],
    fallback_audit: dict[str, Any] | None,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    by_scope = {row["condition_scope"]: row for row in conditional_branch_slices}
    recombined_probability = None
    if (
        status == "built"
        and adjusted_upstream_probability is not None
        and TARGET_GIVEN_UPSTREAM in by_scope
        and TARGET_GIVEN_NOT_UPSTREAM in by_scope
    ):
        upstream_branch = by_scope[TARGET_GIVEN_UPSTREAM]["conditional_branch_probability_candidate"]
        not_upstream_branch = by_scope[TARGET_GIVEN_NOT_UPSTREAM]["conditional_branch_probability_candidate"]
        recombined_probability = round(
            upstream_branch * adjusted_upstream_probability
            + not_upstream_branch * (1.0 - adjusted_upstream_probability),
            9,
        )
    summary = {
        "artifact_type": "scae_conditional_branch_summary",
        "schema_version": SCAE_CONDITIONAL_BRANCH_SUMMARY_SCHEMA_VERSION,
        "feature_id": "SCAE-010",
        "conditional_recombination_status": status,
        "anchor_dependency_contract_id": (contract or {}).get("anchor_dependency_contract_id"),
        "conditional_branch_group_id": (contract or {}).get("conditional_branch_group_id"),
        "amrg_anchor_ref": anchor.get("prior_anchor_slice_id") or anchor.get("edge_id"),
        "amrg_anchor_validation_status": anchor.get("validation_status") or anchor.get("anchor_validation_status"),
        "adjusted_upstream_probability": adjusted_upstream_probability,
        "upstream_prior_reliability_context": copy.deepcopy(upstream_reliability_context),
        "target_given_upstream_branch_probability_candidate": by_scope.get(TARGET_GIVEN_UPSTREAM, {}).get(
            "conditional_branch_probability_candidate"
        ),
        "target_given_not_upstream_branch_probability_candidate": by_scope.get(TARGET_GIVEN_NOT_UPSTREAM, {}).get(
            "conditional_branch_probability_candidate"
        ),
        "conditional_recombined_probability_candidate": recombined_probability,
        "conditional_branch_slice_refs": [
            row["conditional_branch_slice_id"] for row in conditional_branch_slices
        ],
        "fallback_audit": copy.deepcopy(fallback_audit),
        "reason_codes": sorted(set(reason_codes or [])),
        "ledger_input_authority": NO_LIVE_AUTHORITY,
        "live_forecast_authority": False,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
    }
    summary["summary_id"] = _sha_id("scae-conditional-branch-summary", summary)
    summary["summary_digest"] = _prefixed_sha256(summary)
    return summary


def build_conditional_branch_recombination_slices(
    branch_subledger_slices: dict[str, Any] | list[dict[str, Any]],
    *,
    qdt: dict[str, Any],
    amrg_anchor: dict[str, Any],
    policy: dict[str, Any] | None = None,
    repair_state: dict[str, Any] | None = None,
) -> ConditionalBranchResult:
    """Build SCAE-010 candidate-only conditional branch recombination slices."""

    if not isinstance(qdt, dict):
        raise ScaeConditionalBranchError("qdt must be an object")
    if not isinstance(amrg_anchor, dict):
        raise ScaeConditionalBranchError("amrg_anchor must be an object")
    active_policy = copy.deepcopy(policy or default_scae_policy())
    epsilon = _numeric(active_policy.get("prior_reliability", {}).get("epsilon"), "prior_reliability.epsilon")
    leaves_by_id = _qdt_required_leaves(qdt)
    contract = _select_anchor_contract(qdt, amrg_anchor)
    reasons = _anchor_contract_rejection_reasons(contract, leaves_by_id)
    reasons.extend(_anchor_rejection_reasons(amrg_anchor))
    adjusted_upstream_probability, reliability_context, probability_reasons = _anchor_probability_context(amrg_anchor)
    reasons.extend(probability_reasons)

    rows = _rows_from(branch_subledger_slices, "branch_subledger_slices")
    grouped: dict[str, list[dict[str, Any]]] = {TARGET_GIVEN_UPSTREAM: [], TARGET_GIVEN_NOT_UPSTREAM: []}
    excluded_branch_subledger_refs: list[str] = []
    for slice_row in rows:
        slice_copy = copy.deepcopy(slice_row)
        if slice_copy.get("accepted_for_candidate_ledger_input") is not True:
            excluded_branch_subledger_refs.append(_branch_subledger_id(slice_copy))
            continue
        condition_scope = _branch_condition_scope(slice_copy, leaves_by_id)
        if condition_scope is None:
            excluded_branch_subledger_refs.append(_branch_subledger_id(slice_copy))
            continue
        grouped[condition_scope].append(slice_copy)
    for condition_scope in (TARGET_GIVEN_UPSTREAM, TARGET_GIVEN_NOT_UPSTREAM):
        if not grouped[condition_scope]:
            reasons.append(f"missing_{condition_scope}_branch_subledger")

    if reasons:
        fallback_audit = _repair_audit(contract=contract, repair_state=repair_state, reason_codes=reasons)
        summary = _summary(
            status=fallback_audit["fallback_status"],
            contract=contract,
            anchor=amrg_anchor,
            conditional_branch_slices=[],
            adjusted_upstream_probability=adjusted_upstream_probability,
            upstream_reliability_context=reliability_context,
            fallback_audit=fallback_audit,
            reason_codes=reasons,
        )
        bundle_digest = _prefixed_sha256(
            {
                "schema_version": "scae-conditional-branch-digest/v1",
                "slice_schema_version": SCAE_CONDITIONAL_BRANCH_SLICE_SCHEMA_VERSION,
                "summary_schema_version": SCAE_CONDITIONAL_BRANCH_SUMMARY_SCHEMA_VERSION,
                "conditional_branch_slices": [],
                "conditional_branch_summary": summary,
                "excluded_branch_subledger_refs": sorted(excluded_branch_subledger_refs),
            }
        )
        summary["conditional_branch_bundle_digest"] = bundle_digest
        return ConditionalBranchResult([], summary, sorted(excluded_branch_subledger_refs), bundle_digest)

    assert contract is not None
    conditional_branch_slices = [
        _condition_branch_slice(
            TARGET_GIVEN_UPSTREAM,
            grouped[TARGET_GIVEN_UPSTREAM],
            epsilon=epsilon,
            contract=contract,
        ),
        _condition_branch_slice(
            TARGET_GIVEN_NOT_UPSTREAM,
            grouped[TARGET_GIVEN_NOT_UPSTREAM],
            epsilon=epsilon,
            contract=contract,
        ),
    ]
    summary = _summary(
        status="built",
        contract=contract,
        anchor=amrg_anchor,
        conditional_branch_slices=conditional_branch_slices,
        adjusted_upstream_probability=adjusted_upstream_probability,
        upstream_reliability_context=reliability_context,
        fallback_audit=None,
    )
    digest_payload = {
        "schema_version": "scae-conditional-branch-digest/v1",
        "slice_schema_version": SCAE_CONDITIONAL_BRANCH_SLICE_SCHEMA_VERSION,
        "summary_schema_version": SCAE_CONDITIONAL_BRANCH_SUMMARY_SCHEMA_VERSION,
        "conditional_branch_slices": conditional_branch_slices,
        "conditional_branch_summary": summary,
        "excluded_branch_subledger_refs": sorted(excluded_branch_subledger_refs),
    }
    bundle_digest = _prefixed_sha256(digest_payload)
    for row in conditional_branch_slices:
        row["conditional_branch_bundle_digest"] = bundle_digest
    summary["conditional_branch_bundle_digest"] = bundle_digest
    return ConditionalBranchResult(
        conditional_branch_slices,
        summary,
        sorted(excluded_branch_subledger_refs),
        bundle_digest,
    )


def build_conditional_branch_recombination_bundle(
    branch_subledger_slices: dict[str, Any] | list[dict[str, Any]],
    *,
    qdt: dict[str, Any],
    amrg_anchor: dict[str, Any],
    policy: dict[str, Any] | None = None,
    repair_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the external SCAE-010 conditional branch recombination bundle."""

    result = build_conditional_branch_recombination_slices(
        branch_subledger_slices,
        qdt=qdt,
        amrg_anchor=amrg_anchor,
        policy=policy,
        repair_state=repair_state,
    )
    return {
        "artifact_type": "scae_conditional_branch_bundle",
        "schema_version": SCAE_CONDITIONAL_BRANCH_BUNDLE_SCHEMA_VERSION,
        "feature_id": "SCAE-010",
        "authority": NO_LIVE_AUTHORITY,
        "writes_scae_ledger": False,
        "writes_production_forecast": False,
        "conditional_branch_bundle_digest": result.conditional_branch_bundle_digest,
        "conditional_branch_count": len(result.conditional_branch_slices),
        "excluded_branch_subledger_refs": result.excluded_branch_subledger_refs,
        "conditional_branch_slices": result.conditional_branch_slices,
        "conditional_branch_summary": result.conditional_branch_summary,
        "conditional_recombination_version": SCAE_010_CONDITIONAL_RECOMBINATION_VERSION,
    }
