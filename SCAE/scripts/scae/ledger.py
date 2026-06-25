"""SCAE ledger guard helpers for research sufficiency intake.

This module currently implements the SCAE-013 research sufficiency /
forecast-validity guard. It annotates SCAE-011 pre-debt ledger output with
VER-004 reconciliation context, but does not apply calibration-debt controls,
persist forecasts, or emit production/canonical probability fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from scae.policy import default_scae_policy


SCAE_RESEARCH_SUFFICIENCY_CONTEXT_SCHEMA_VERSION = "scae-research-sufficiency-context/v1"
SCAE_013_RESEARCH_SUFFICIENCY_GUARD_VERSION = "ads-scae-013-research-sufficiency-guard/v1"
RESEARCH_SUFFICIENCY_GUARD_AUTHORITY = "research_sufficiency_validity_guard_no_production_forecast_authority"
SCAE_RECONCILIATION_SURFACE = "research_sufficiency_reconciliation_slices"
HIGH_CERTAINTY_STATUS = "scae_ready_high_certainty"
STRUCTURALLY_UNANSWERABLE_STATUS = "structurally_unanswerable"
BLOCKED_STATUS = "blocked_insufficient_research"
VALIDITY_READY = "valid_for_forecast"
VALIDITY_WATCH_ONLY = "valid_for_forecast_watch_only"
VALIDITY_INVALID = "invalid_for_forecast"
CONTEXT_READY = "scae_ready_high_certainty"
CONTEXT_WATCH_ONLY = "watch_only_structurally_unanswerable"
CONTEXT_INVALID = "invalid_insufficient_research"
FINAL_PROBABILITY_FIELDS = {
    "debt_adjusted_probability",
    "production_forecast_prob",
    "canonical_probability",
}


class ScaeLedgerError(ValueError):
    """Raised when a SCAE ledger guard cannot safely annotate a ledger."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if _is_non_empty_string(item))


def _rows_from(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    rows = value
    if isinstance(value, dict):
        if SCAE_RECONCILIATION_SURFACE in value:
            rows = value[SCAE_RECONCILIATION_SURFACE]
        elif value.get("artifact_type") == "research_sufficiency_reconciliation_slice":
            rows = [value]
        else:
            rows = value.get("research_sufficiency_reconciliation_slices", [])
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ScaeLedgerError("research_sufficiency_reconciliation_slices must be a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScaeLedgerError("research_sufficiency_reconciliation_slices must contain objects")
        normalized.append(row)
    return normalized


def _required_scae_leaves(qdt: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(qdt, dict):
        raise ScaeLedgerError("qdt must be an object")
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list):
        raise ScaeLedgerError("qdt.required_leaf_questions must be a list")
    required: list[dict[str, Any]] = []
    for leaf in leaves:
        if not isinstance(leaf, dict):
            raise ScaeLedgerError("qdt.required_leaf_questions must contain objects")
        if leaf.get("included_for_scae", leaf.get("scae_bound", True)) is False:
            continue
        if not _is_non_empty_string(leaf.get("leaf_id")):
            raise ScaeLedgerError("SCAE-bound qdt leaf is missing leaf_id")
        required.append(copy.deepcopy(leaf))
    return sorted(required, key=lambda item: str(item["leaf_id"]))


def _row_leaf_id(row: dict[str, Any]) -> str:
    if not _is_non_empty_string(row.get("leaf_id")):
        raise ScaeLedgerError("research sufficiency reconciliation row is missing leaf_id")
    return str(row["leaf_id"])


def _rows_by_leaf(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_leaf: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_copy = copy.deepcopy(row)
        leaf_id = _row_leaf_id(row_copy)
        if leaf_id in by_leaf:
            raise ScaeLedgerError(f"duplicate research sufficiency reconciliation for leaf {leaf_id}")
        by_leaf[leaf_id] = row_copy
    return by_leaf


def _reconciliation_ref(row: dict[str, Any]) -> str:
    for field_name in ("research_sufficiency_reconciliation_ref", "research_sufficiency_reconciliation_id"):
        value = row.get(field_name)
        if _is_non_empty_string(value):
            return str(value)
    return _sha_id("research-sufficiency-reconciliation", row)


def _certificate_ref(row: dict[str, Any]) -> str | None:
    for field_name in ("research_sufficiency_certificate_ref", "certificate_ref"):
        value = row.get(field_name)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _breadth_profile_ref(row: dict[str, Any], leaf: dict[str, Any]) -> str | None:
    for field_name in ("retrieval_breadth_profile_ref", "breadth_profile_ref"):
        value = row.get(field_name)
        if _is_non_empty_string(value):
            return str(value)
    requirements = leaf.get("research_sufficiency_requirements")
    if isinstance(requirements, dict):
        for field_name in ("retrieval_breadth_profile_ref", "breadth_profile_ref"):
            value = requirements.get(field_name)
            if _is_non_empty_string(value):
                return str(value)
    for field_name in ("retrieval_breadth_profile_ref", "breadth_profile_ref"):
        value = leaf.get(field_name)
        if _is_non_empty_string(value):
            return str(value)
    return None


def _coverage_ref(row: dict[str, Any]) -> str | None:
    value = row.get("retrieval_breadth_coverage_ref") or row.get("breadth_coverage_ref")
    if _is_non_empty_string(value):
        return str(value)
    return None


def _status(row: dict[str, Any]) -> str:
    value = row.get("reconciled_status") or row.get("research_sufficiency_reconciliation_status")
    return str(value or "")


def _required_escalations_complete(row: dict[str, Any]) -> bool:
    required = set(_string_list(row.get("required_escalation_decision_refs")))
    completed = set(_string_list(row.get("completed_escalation_decision_refs")))
    return required <= completed


def _policy_allows_structural_watch(policy: dict[str, Any]) -> bool:
    sufficiency_policy = policy.get("research_sufficiency")
    if not isinstance(sufficiency_policy, dict):
        return False
    return sufficiency_policy.get("allow_watch_only_structural_unanswerability") is True


def _leaf_reason(
    *,
    leaf: dict[str, Any],
    row: dict[str, Any] | None,
    policy: dict[str, Any],
) -> tuple[str, list[str], dict[str, Any]]:
    leaf_id = str(leaf["leaf_id"])
    if row is None:
        return BLOCKED_STATUS, ["research_sufficiency_reconciliation_missing"], {
            "leaf_id": leaf_id,
            "reconciliation_ref": None,
            "certificate_ref": None,
            "breadth_profile_ref": _breadth_profile_ref({}, leaf),
            "breadth_coverage_ref": None,
            "required_escalation_decision_refs": [],
            "completed_escalation_decision_refs": [],
        }

    status = _status(row)
    reasons: list[str] = []
    profile_ref = _breadth_profile_ref(row, leaf)
    coverage_ref = _coverage_ref(row)
    blocking_codes = _string_list(row.get("blocking_reason_codes"))
    if blocking_codes:
        reasons.extend(blocking_codes)

    if status == HIGH_CERTAINTY_STATUS:
        if not profile_ref:
            reasons.append("retrieval_breadth_profile_ref_missing")
        if not coverage_ref:
            reasons.append("retrieval_breadth_coverage_ref_missing")
        if row.get("retrieval_breadth_certified") is not True:
            reasons.append("retrieval_breadth_not_certified")
        if not _required_escalations_complete(row):
            reasons.append("researcher_escalation_incomplete")
        effective_status = BLOCKED_STATUS if reasons else HIGH_CERTAINTY_STATUS
    elif status == STRUCTURALLY_UNANSWERABLE_STATUS:
        if not _policy_allows_structural_watch(policy):
            reasons.append("structural_unanswerability_watch_only_not_permitted")
        if blocking_codes:
            reasons.extend(blocking_codes)
        if not _required_escalations_complete(row):
            reasons.append("structural_unanswerability_confirmation_incomplete")
        if "structural_unanswerability_verified_with_required_confirmation" not in _string_list(row.get("reason_codes")):
            reasons.append("structural_unanswerability_full_expansion_proof_missing")
        effective_status = BLOCKED_STATUS if reasons else STRUCTURALLY_UNANSWERABLE_STATUS
    elif status == BLOCKED_STATUS:
        reasons.append("blocked_insufficient_research")
        effective_status = BLOCKED_STATUS
    else:
        reasons.append(f"unsupported_research_sufficiency_status:{status or 'missing'}")
        effective_status = BLOCKED_STATUS

    details = {
        "leaf_id": leaf_id,
        "reconciliation_ref": _reconciliation_ref(row),
        "certificate_ref": _certificate_ref(row),
        "breadth_profile_ref": profile_ref,
        "breadth_coverage_ref": coverage_ref,
        "required_escalation_decision_refs": _string_list(row.get("required_escalation_decision_refs")),
        "completed_escalation_decision_refs": _string_list(row.get("completed_escalation_decision_refs")),
        "source_reconciled_status": status,
    }
    return effective_status, sorted(set(reasons)), details


def _insufficiency_component(leaf_id: str, reason_codes: list[str], details: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_id": f"research-sufficiency-insufficiency:{leaf_id}",
        "component_type": "research_sufficiency_insufficiency",
        "leaf_id": leaf_id,
        "reason_codes": sorted(set(reason_codes)),
        "source_refs": sorted(
            ref
            for ref in (
                details.get("reconciliation_ref"),
                details.get("certificate_ref"),
                details.get("breadth_profile_ref"),
                details.get("breadth_coverage_ref"),
            )
            if _is_non_empty_string(ref)
        ),
        "can_increase_evidence_strength": False,
        "signed_log_odds_delta": 0.0,
        "accepted_for_ledger_input": False,
        "interval_debug_only": True,
    }


def build_research_sufficiency_context(
    *,
    qdt: dict[str, Any],
    sufficiency_reconciliations: dict[str, Any] | list[dict[str, Any]] | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the SCAE-013 research sufficiency/validity context."""

    active_policy = copy.deepcopy(policy or default_scae_policy())
    leaves = _required_scae_leaves(qdt)
    rows = _rows_from(sufficiency_reconciliations)
    rows_by_leaf = _rows_by_leaf(rows)
    leaf_details: list[dict[str, Any]] = []
    blocked_leaf_ids: list[str] = []
    structurally_unanswerable_leaf_ids: list[str] = []
    ready_leaf_ids: list[str] = []
    insufficiency_components: list[dict[str, Any]] = []

    for leaf in leaves:
        leaf_id = str(leaf["leaf_id"])
        effective_status, reasons, details = _leaf_reason(
            leaf=leaf,
            row=rows_by_leaf.get(leaf_id),
            policy=active_policy,
        )
        details["effective_scae_research_status"] = effective_status
        details["reason_codes"] = reasons
        leaf_details.append(details)
        if effective_status == HIGH_CERTAINTY_STATUS:
            ready_leaf_ids.append(leaf_id)
        elif effective_status == STRUCTURALLY_UNANSWERABLE_STATUS:
            structurally_unanswerable_leaf_ids.append(leaf_id)
        else:
            blocked_leaf_ids.append(leaf_id)
            insufficiency_components.append(_insufficiency_component(leaf_id, reasons, details))

    if blocked_leaf_ids:
        bundle_status = CONTEXT_INVALID
        forecast_validity_status = VALIDITY_INVALID
    elif structurally_unanswerable_leaf_ids:
        bundle_status = CONTEXT_WATCH_ONLY
        forecast_validity_status = VALIDITY_WATCH_ONLY
    else:
        bundle_status = CONTEXT_READY
        forecast_validity_status = VALIDITY_READY

    context = {
        "artifact_type": "scae_research_sufficiency_context",
        "schema_version": SCAE_RESEARCH_SUFFICIENCY_CONTEXT_SCHEMA_VERSION,
        "feature_id": "SCAE-013",
        "guard_version": SCAE_013_RESEARCH_SUFFICIENCY_GUARD_VERSION,
        "authority": RESEARCH_SUFFICIENCY_GUARD_AUTHORITY,
        "policy_snapshot_id": active_policy.get("policy_id"),
        "policy_allows_watch_only_structural_unanswerability": _policy_allows_structural_watch(active_policy),
        "bundle_status": bundle_status,
        "forecast_validity_status": forecast_validity_status,
        "required_leaf_ids": [str(leaf["leaf_id"]) for leaf in leaves],
        "scae_ready_high_certainty_leaf_ids": sorted(ready_leaf_ids),
        "blocked_leaf_ids": sorted(blocked_leaf_ids),
        "structurally_unanswerable_leaf_ids": sorted(structurally_unanswerable_leaf_ids),
        "leaf_reconciliation_refs": sorted(
            details["reconciliation_ref"] for details in leaf_details if _is_non_empty_string(details.get("reconciliation_ref"))
        ),
        "leaf_certificate_refs": sorted(
            details["certificate_ref"] for details in leaf_details if _is_non_empty_string(details.get("certificate_ref"))
        ),
        "leaf_breadth_profile_refs": sorted(
            details["breadth_profile_ref"] for details in leaf_details if _is_non_empty_string(details.get("breadth_profile_ref"))
        ),
        "leaf_breadth_coverage_refs": sorted(
            details["breadth_coverage_ref"] for details in leaf_details if _is_non_empty_string(details.get("breadth_coverage_ref"))
        ),
        "leaf_escalation_decision_refs": sorted(
            {
                ref
                for details in leaf_details
                for ref in details.get("completed_escalation_decision_refs", [])
                if _is_non_empty_string(ref)
            }
        ),
        "leaf_details": sorted(leaf_details, key=lambda item: str(item["leaf_id"])),
        "insufficiency_interval_debug_components": sorted(
            insufficiency_components,
            key=lambda item: str(item["component_id"]),
        ),
        "uncertified_thin_research_converted_to_evidence": False,
        "writes_production_forecast": False,
        "writes_persistence": False,
        "calibration_debt_controls_applied": False,
    }
    context["research_sufficiency_context_id"] = _sha_id("scae-research-sufficiency-context", context)
    context["research_sufficiency_context_digest"] = _prefixed_sha256(context)
    return context


def apply_research_sufficiency_guard(
    ledger: dict[str, Any],
    *,
    qdt: dict[str, Any],
    sufficiency_reconciliations: dict[str, Any] | list[dict[str, Any]] | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Annotate a SCAE-011 pre-debt ledger with SCAE-013 validity context."""

    if not isinstance(ledger, dict):
        raise ScaeLedgerError("ledger must be an object")
    if "raw_ledger_probability" not in ledger or "post_ledger_probability" not in ledger:
        raise ScaeLedgerError("SCAE-013 requires SCAE-011 raw/post ledger probabilities")
    forbidden_present = sorted(FINAL_PROBABILITY_FIELDS & set(ledger))
    if forbidden_present:
        raise ScaeLedgerError(
            "SCAE-013 cannot accept already-final probability fields: " + ", ".join(forbidden_present)
        )

    context = build_research_sufficiency_context(
        qdt=qdt,
        sufficiency_reconciliations=sufficiency_reconciliations,
        policy=policy,
    )
    annotated = copy.deepcopy(ledger)
    annotated["research_sufficiency_context"] = context
    annotated["forecast_validity_status"] = context["forecast_validity_status"]
    annotated["sufficiency_guard_authority"] = RESEARCH_SUFFICIENCY_GUARD_AUTHORITY
    annotated["calibration_debt_finalization_ready"] = context["forecast_validity_status"] != VALIDITY_INVALID
    annotated["writes_production_forecast"] = False
    annotated["writes_persistence"] = False
    scopes = [
        scope
        for scope in annotated.get("not_implemented_scope", [])
        if not str(scope).startswith("SCAE-013_")
    ]
    for scope in (
        "SCAE-012_calibration_debt_controls",
        "production_forecast_persistence",
        "decision_authority",
        "replay_scoring",
        "calibration_tuning_promotions",
    ):
        if scope not in scopes:
            scopes.append(scope)
    annotated["not_implemented_scope"] = scopes
    if isinstance(annotated.get("interval"), dict):
        interval = copy.deepcopy(annotated["interval"])
        interval["research_sufficiency_debug_components"] = copy.deepcopy(
            context["insufficiency_interval_debug_components"]
        )
        annotated["interval"] = interval
    annotated["research_sufficiency_guarded_ledger_id"] = _sha_id("scae-sufficiency-guarded-ledger", annotated)
    annotated["research_sufficiency_guarded_ledger_digest"] = _prefixed_sha256(annotated)
    return annotated
