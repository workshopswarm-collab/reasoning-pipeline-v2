"""QDT schema and deterministic candidate-selection helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _add_orchestrator_scripts_to_path() -> None:
    configured = os.environ.get("ADS_ORCHESTRATOR_SCRIPTS")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path(__file__).resolve().parents[3] / "orchestrator" / "scripts")
    for candidate in candidates:
        if candidate.is_dir():
            text = str(candidate)
            if text not in sys.path:
                sys.path.insert(0, text)
            return


_add_orchestrator_scripts_to_path()

from predquant.ads_handoff import canonical_json

from .handoff import (
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
)


QUESTION_DECOMPOSITION_ARTIFACT_TYPE = "question_decomposition"
QDT_SCHEMA_VALIDATOR_VERSION = "ads-qdt-schema/v1"
QDT_SELECTION_HELPER_VERSION = "ads-qdt-selection/v1"
COMPACT_DEFAULT_LEAF_BUDGET = 6
MAX_REASON_CODE_LENGTH = 80

ALLOWED_PURPOSES = {
    "base_rate",
    "market_pricing",
    "direct_evidence",
    "source_of_truth",
    "catalyst",
    "resolution_mechanics",
    "structural",
    "other",
}
ALLOWED_STATIC_INFORMATION_WEIGHTS = {"critical", "high", "medium", "low"}
ALLOWED_CONDITION_SCOPES = {
    "unconditional",
    "target_given_upstream",
    "target_given_not_upstream",
    "shared_context",
}
ALLOWED_SOURCE_CLASSES = {
    "official_or_primary",
    "independent_secondary",
    "market_or_exchange",
    "expert_or_specialist",
    "public_record",
}
ALLOWED_TARGET_ANSWERABILITY = {"high_confidence_or_structurally_unanswerable"}
ALLOWED_RELATED_CONTEXT_USAGE_STATUS = {
    "related_context_used",
    "no_related_context_waiver",
    "not_used",
}
FORBIDDEN_QDT_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "confidence_interval",
    "credible_interval",
    "prediction_interval",
    "interval",
    "reassembly",
)
REQUIRED_QDT_FIELDS = (
    "artifact_type",
    "schema_version",
    "case_id",
    "market_id",
    "dispatch_id",
    "macro_question",
    "market_reality_constraints_digest",
    "leaf_budget_decision",
    "branches",
    "required_leaf_questions",
    "required_evidence_purposes",
    "related_market_context_usage",
    "amrg_anchor_dependency_contracts",
    "model_execution_context",
    "validation_summary",
)
REQUIRED_LEAF_FIELDS = (
    "leaf_id",
    "parent_branch_id",
    "question_text",
    "purpose",
    "bayesian_weighting",
    "leaf_dependency_group_id",
    "leaf_condition_scope",
    "required_evidence_fields",
    "research_sufficiency_requirements",
    "market_component_terms",
    "structural_validation",
)
REQUIRED_SUFFICIENCY_FIELDS = (
    "sufficiency_profile_id",
    "target_answerability",
    "retrieval_breadth_profile_ref",
    "required_source_classes",
    "protected_primary_required",
    "min_independent_claim_families",
    "min_independent_source_families",
    "min_temporally_fresh_sources",
    "required_value_fields",
    "required_negative_checks",
    "contradiction_search_required",
    "recency_window_seconds",
    "max_targeted_expansion_attempts",
    "allow_macro_fallback_for_leaf",
    "unanswerability_proof_required",
    "classification_dispatch_requires_sufficiency_certificate",
)
REQUIRED_MODEL_FIELDS = (
    "model_lane_id",
    "resolved_model_id",
    "model_policy_ref",
    "prompt_template_id",
    "prompt_template_sha256",
    "input_manifest_ids",
    "output_schema_version",
)


class QDTError(ValueError):
    """Raised when a QDT artifact is malformed or has no valid candidate."""


@dataclass(frozen=True)
class QDTValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": QDT_SCHEMA_VALIDATOR_VERSION,
        }


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reason_codes_are_compact(value: Any) -> bool:
    return isinstance(value, list) and all(
        _is_non_empty_string(item) and len(item) <= MAX_REASON_CODE_LENGTH and " " not in item
        for item in value
    )


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_string(item) for item in value)


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _reject_forbidden_qdt_keys(value: Any, errors: list[str], path: str = "qdt") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in FORBIDDEN_QDT_KEY_FRAGMENTS):
                errors.append(f"{path}.{key} is forbidden in question-decomposition/v1")
            _reject_forbidden_qdt_keys(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_forbidden_qdt_keys(child, errors, f"{path}[{idx}]")


def build_leaf_budget_decision(
    *,
    market_complexity_score: float,
    effective_leaf_budget: int,
    selected_leaf_count: int,
    requested_leaf_count: int | None = None,
    reason_codes: list[str] | None = None,
    compact_default_leaf_budget: int = COMPACT_DEFAULT_LEAF_BUDGET,
) -> dict[str, Any]:
    hierarchical_required = effective_leaf_budget > compact_default_leaf_budget
    return {
        "market_complexity_score": float(market_complexity_score),
        "effective_leaf_budget": int(effective_leaf_budget),
        "compact_default_leaf_budget": int(compact_default_leaf_budget),
        "hierarchical_branch_ledger_required": hierarchical_required,
        "reason_codes": list(reason_codes or ["default_leaf_budget_policy"]),
        "budget_audit": {
            "requested_leaf_count": int(requested_leaf_count or selected_leaf_count),
            "selected_leaf_count": int(selected_leaf_count),
            "leaf_budget_rule": "compact_default_or_hierarchical_branch_ledger",
            "audit_schema_version": "leaf-budget-decision-audit/v1",
        },
    }


def build_research_sufficiency_requirements(
    *,
    purpose: str,
    static_information_weight: str,
    condition_scope: str,
    required_value_fields: list[str] | None = None,
    required_negative_checks: list[str] | None = None,
) -> dict[str, Any]:
    protected_primary_required = purpose == "source_of_truth"
    critical_or_source = static_information_weight == "critical" or purpose == "source_of_truth"
    required_classes = ["official_or_primary", "independent_secondary"]
    if purpose == "market_pricing":
        required_classes = ["market_or_exchange", "independent_secondary"]
    claim_family_minimum = 2 if static_information_weight in {"critical", "high"} else 1
    source_family_minimum = 2 if static_information_weight in {"critical", "high"} else 1
    fresh_sources = 1 if purpose in {"direct_evidence", "source_of_truth", "catalyst", "market_pricing"} else 0
    return {
        "sufficiency_profile_id": "high-certainty-default/v1",
        "target_answerability": "high_confidence_or_structurally_unanswerable",
        "retrieval_breadth_profile_ref": f"breadth-profile-template:{purpose}:{static_information_weight}:{condition_scope}",
        "required_source_classes": required_classes,
        "protected_primary_required": protected_primary_required,
        "min_independent_claim_families": claim_family_minimum,
        "min_independent_source_families": source_family_minimum,
        "min_temporally_fresh_sources": fresh_sources,
        "required_value_fields": list(required_value_fields or []),
        "required_negative_checks": list(required_negative_checks or []),
        "contradiction_search_required": True,
        "recency_window_seconds": 259200,
        "max_targeted_expansion_attempts": 3,
        "allow_macro_fallback_for_leaf": False,
        "unanswerability_proof_required": critical_or_source,
        "classification_dispatch_requires_sufficiency_certificate": True,
    }


def _model_execution_context_from_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    model_context = handoff.get("model_execution_context")
    if not isinstance(model_context, dict):
        raise QDTError("handoff missing model_execution_context")
    return {field: copy.deepcopy(model_context.get(field)) for field in REQUIRED_MODEL_FIELDS}


def _related_context_usage_from_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    ref = handoff.get("artifact_refs", {}).get("related_market_context", {})
    artifact_type = ref.get("artifact_type")
    if artifact_type == "related-live-market-context":
        status = "related_context_used"
    elif artifact_type == "no-related-context-waiver":
        status = "no_related_context_waiver"
    else:
        status = "not_used"
    return {
        "usage_status": status,
        "related_context_artifact_ref": ref.get("artifact_id"),
        "amrg_usage_refs": [],
        "weak_context_only": status != "related_context_used",
        "anchor_dependency_status": "not_declared_phase2",
    }


def build_qdt_candidate(
    *,
    handoff: dict[str, Any],
    candidate_id: str,
    branches: list[dict[str, Any]],
    required_leaf_questions: list[dict[str, Any]],
    leaf_budget_decision: dict[str, Any] | None = None,
    market_complexity_score: float = 0.5,
    market_reality_constraints_digest: str | None = None,
    related_market_context_usage: dict[str, Any] | None = None,
    amrg_anchor_dependency_contracts: list[dict[str, Any]] | None = None,
    selection_strategy: str = "deterministic_fixture",
) -> dict[str, Any]:
    leaves = copy.deepcopy(required_leaf_questions)
    for leaf in leaves:
        weighting = leaf.get("bayesian_weighting", {})
        if isinstance(weighting, dict) and "research_sufficiency_requirements" not in leaf:
            leaf["research_sufficiency_requirements"] = build_research_sufficiency_requirements(
                purpose=leaf.get("purpose", "other"),
                static_information_weight=weighting.get("static_information_weight", "medium"),
                condition_scope=leaf.get("leaf_condition_scope", "unconditional"),
            )
    purposes = sorted({leaf.get("purpose") for leaf in leaves if leaf.get("purpose")})
    if leaf_budget_decision is None:
        leaf_budget_decision = build_leaf_budget_decision(
            market_complexity_score=market_complexity_score,
            effective_leaf_budget=max(COMPACT_DEFAULT_LEAF_BUDGET, len(leaves)),
            selected_leaf_count=len(leaves),
            requested_leaf_count=len(leaves),
        )
    model_context = _model_execution_context_from_handoff(handoff)
    return {
        "artifact_type": QUESTION_DECOMPOSITION_ARTIFACT_TYPE,
        "schema_version": QUESTION_DECOMPOSITION_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "case_id": handoff.get("case_id"),
        "case_key": handoff.get("case_key"),
        "market_id": handoff.get("market_context", {}).get("market_id"),
        "dispatch_id": handoff.get("dispatch_id"),
        "macro_question": handoff.get("macro_question"),
        "market_reality_constraints_digest": (
            market_reality_constraints_digest
            or handoff.get("market_context", {}).get("market_reality_constraints_digest")
            or _prefixed_sha256({})
        ),
        "leaf_budget_decision": leaf_budget_decision,
        "branches": copy.deepcopy(branches),
        "required_leaf_questions": leaves,
        "required_evidence_purposes": purposes,
        "related_market_context_usage": related_market_context_usage
        or _related_context_usage_from_handoff(handoff),
        "amrg_anchor_dependency_contracts": copy.deepcopy(amrg_anchor_dependency_contracts or []),
        "model_execution_context": model_context,
        "candidate_selection_audit": {
            "selection_status": "candidate",
            "candidate_id": candidate_id,
            "selection_strategy": selection_strategy,
            "selection_helper_version": QDT_SELECTION_HELPER_VERSION,
        },
        "validation_summary": {
            "status": "candidate",
            "validator_version": QDT_SCHEMA_VALIDATOR_VERSION,
            "reason_codes": ["candidate_schema_pending_selection"],
            "forbidden_output_check_status": "passed",
        },
    }


def build_fixture_qdt_candidate(
    handoff: dict[str, Any],
    *,
    candidate_id: str = "qdt-candidate-001",
    include_resolution_leaf: bool = True,
    effective_leaf_budget: int = COMPACT_DEFAULT_LEAF_BUDGET,
) -> dict[str, Any]:
    leaves = [
        {
            "leaf_id": "leaf-source-of-truth",
            "parent_branch_id": "branch-resolution",
            "question_text": "What official or primary-source information can resolve the market question?",
            "purpose": "source_of_truth",
            "bayesian_weighting": {
                "static_information_weight": "critical",
                "weight_reason_codes": ["official_resolution_authority"],
            },
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["official_status", "resolution_criteria"],
            "market_component_terms": ["resolution", "official source"],
            "structural_validation": {"depth": 2, "schema_only_status": "pending_qdt_003"},
        },
        {
            "leaf_id": "leaf-direct-evidence",
            "parent_branch_id": "branch-resolution",
            "question_text": "What fresh direct evidence bears on the target event before the cutoff?",
            "purpose": "direct_evidence",
            "bayesian_weighting": {
                "static_information_weight": "high",
                "weight_reason_codes": ["event_proximity"],
            },
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["event_status", "event_timestamp"],
            "market_component_terms": ["event", "cutoff"],
            "structural_validation": {"depth": 2, "schema_only_status": "pending_qdt_003"},
        },
    ]
    branches = [
        {
            "branch_id": "branch-resolution",
            "branch_question": "Resolve the target market through primary authority and fresh direct evidence.",
            "branch_role": "resolution_evidence",
            "dependency_group_id": "dep-group-resolution",
            "required_evidence_purposes": ["direct_evidence", "source_of_truth"],
            "leaf_ids": ["leaf-source-of-truth", "leaf-direct-evidence"],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1, "schema_only_status": "pending_qdt_003"},
        }
    ]
    if include_resolution_leaf:
        leaves.append(
            {
                "leaf_id": "leaf-resolution-mechanics",
                "parent_branch_id": "branch-mechanics",
                "question_text": "Which market rules and timing terms govern how the outcome resolves?",
                "purpose": "resolution_mechanics",
                "bayesian_weighting": {
                    "static_information_weight": "medium",
                    "weight_reason_codes": ["contract_resolution_terms"],
                },
                "leaf_dependency_group_id": "dep-group-mechanics",
                "leaf_condition_scope": "shared_context",
                "required_evidence_fields": ["resolution_deadline", "rules_text"],
                "market_component_terms": ["rules", "deadline"],
                "structural_validation": {"depth": 2, "schema_only_status": "pending_qdt_003"},
            }
        )
        branches.append(
            {
                "branch_id": "branch-mechanics",
                "branch_question": "Clarify contract mechanics that constrain admissible evidence.",
                "branch_role": "resolution_mechanics",
                "dependency_group_id": "dep-group-mechanics",
                "required_evidence_purposes": ["resolution_mechanics"],
                "leaf_ids": ["leaf-resolution-mechanics"],
                "amrg_usage_refs": [],
                "structural_validation": {"depth": 1, "schema_only_status": "pending_qdt_003"},
            }
        )
    leaf_budget = build_leaf_budget_decision(
        market_complexity_score=0.5 if effective_leaf_budget <= COMPACT_DEFAULT_LEAF_BUDGET else 0.85,
        effective_leaf_budget=effective_leaf_budget,
        selected_leaf_count=len(leaves),
        requested_leaf_count=len(leaves),
    )
    return build_qdt_candidate(
        handoff=handoff,
        candidate_id=candidate_id,
        branches=branches,
        required_leaf_questions=leaves,
        leaf_budget_decision=leaf_budget,
    )


def _validate_leaf_budget(decision: Any, leaf_count: int, errors: list[str]) -> None:
    if not isinstance(decision, dict):
        errors.append("leaf_budget_decision must be an object")
        return
    for field in (
        "market_complexity_score",
        "effective_leaf_budget",
        "compact_default_leaf_budget",
        "hierarchical_branch_ledger_required",
        "reason_codes",
        "budget_audit",
    ):
        if field not in decision:
            errors.append(f"leaf_budget_decision missing {field}")
    if not isinstance(decision.get("market_complexity_score"), (int, float)) or isinstance(
        decision.get("market_complexity_score"), bool
    ):
        errors.append("leaf_budget_decision.market_complexity_score must be numeric")
    if not _positive_int(decision.get("effective_leaf_budget")):
        errors.append("leaf_budget_decision.effective_leaf_budget must be a positive integer")
    if not _positive_int(decision.get("compact_default_leaf_budget")):
        errors.append("leaf_budget_decision.compact_default_leaf_budget must be a positive integer")
    if not isinstance(decision.get("hierarchical_branch_ledger_required"), bool):
        errors.append("leaf_budget_decision.hierarchical_branch_ledger_required must be boolean")
    if not _reason_codes_are_compact(decision.get("reason_codes")):
        errors.append("leaf_budget_decision.reason_codes must be compact reason codes")
    budget = decision.get("effective_leaf_budget")
    default = decision.get("compact_default_leaf_budget")
    if _positive_int(budget) and _positive_int(default):
        if budget > default and decision.get("hierarchical_branch_ledger_required") is not True:
            errors.append("leaf_budget_decision must require hierarchical branch ledger above compact default")
        if leaf_count > budget:
            errors.append("required_leaf_questions exceeds effective_leaf_budget")
    audit = decision.get("budget_audit")
    if not isinstance(audit, dict):
        errors.append("leaf_budget_decision.budget_audit must be an object")
        return
    for field in ("requested_leaf_count", "selected_leaf_count", "leaf_budget_rule", "audit_schema_version"):
        if field not in audit:
            errors.append(f"leaf_budget_decision.budget_audit missing {field}")
    if not _positive_int(audit.get("requested_leaf_count")):
        errors.append("leaf_budget_decision.budget_audit.requested_leaf_count must be positive integer")
    if audit.get("selected_leaf_count") != leaf_count:
        errors.append("leaf_budget_decision.budget_audit.selected_leaf_count must equal leaf count")


def _validate_branches(branches: Any, errors: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(branches, list) or not branches:
        errors.append("branches must be a non-empty list")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for idx, branch in enumerate(branches):
        path = f"branches[{idx}]"
        if not isinstance(branch, dict):
            errors.append(f"{path} must be an object")
            continue
        for field in (
            "branch_id",
            "branch_question",
            "branch_role",
            "dependency_group_id",
            "required_evidence_purposes",
            "leaf_ids",
            "amrg_usage_refs",
            "structural_validation",
        ):
            if field not in branch:
                errors.append(f"{path} missing {field}")
        branch_id = branch.get("branch_id")
        if not _is_non_empty_string(branch_id) or not str(branch_id).startswith("branch-"):
            errors.append(f"{path}.branch_id must start with branch-")
            continue
        if branch_id in indexed:
            errors.append(f"{path}.branch_id is duplicated")
        indexed[branch_id] = branch
        if "branches" in branch or "child_branches" in branch or "children" in branch:
            errors.append(f"{path} must not contain nested branches")
        if not _is_non_empty_string(branch.get("branch_question")):
            errors.append(f"{path}.branch_question is required")
        if not _is_non_empty_string(branch.get("branch_role")):
            errors.append(f"{path}.branch_role is required")
        if not _is_non_empty_string(branch.get("dependency_group_id")):
            errors.append(f"{path}.dependency_group_id is required")
        purposes = branch.get("required_evidence_purposes")
        if not isinstance(purposes, list) or not purposes:
            errors.append(f"{path}.required_evidence_purposes must be non-empty")
        elif not set(purposes).issubset(ALLOWED_PURPOSES):
            errors.append(f"{path}.required_evidence_purposes contains unknown purpose")
        if not isinstance(branch.get("leaf_ids"), list) or not branch.get("leaf_ids"):
            errors.append(f"{path}.leaf_ids must be non-empty")
        elif not all(_is_non_empty_string(item) and str(item).startswith("leaf-") for item in branch["leaf_ids"]):
            errors.append(f"{path}.leaf_ids must contain leaf-* IDs")
        if not isinstance(branch.get("amrg_usage_refs"), list):
            errors.append(f"{path}.amrg_usage_refs must be a list")
        if not isinstance(branch.get("structural_validation"), dict):
            errors.append(f"{path}.structural_validation must be an object")
    return indexed


def _validate_sufficiency(requirements: Any, leaf: dict[str, Any], path: str, errors: list[str]) -> None:
    if not isinstance(requirements, dict):
        errors.append(f"{path}.research_sufficiency_requirements must be an object")
        return
    for field in REQUIRED_SUFFICIENCY_FIELDS:
        if field not in requirements:
            errors.append(f"{path}.research_sufficiency_requirements missing {field}")
    if requirements.get("sufficiency_profile_id") != "high-certainty-default/v1":
        errors.append(f"{path}.sufficiency_profile_id must be high-certainty-default/v1")
    if requirements.get("target_answerability") not in ALLOWED_TARGET_ANSWERABILITY:
        errors.append(f"{path}.target_answerability is invalid")
    if not _is_non_empty_string(requirements.get("retrieval_breadth_profile_ref")):
        errors.append(f"{path}.retrieval_breadth_profile_ref is required")
    source_classes = requirements.get("required_source_classes")
    if not isinstance(source_classes, list) or not source_classes:
        errors.append(f"{path}.required_source_classes must be non-empty")
    elif not set(source_classes).issubset(ALLOWED_SOURCE_CLASSES):
        errors.append(f"{path}.required_source_classes contains unknown source class")
    for bool_field in (
        "protected_primary_required",
        "contradiction_search_required",
        "allow_macro_fallback_for_leaf",
        "unanswerability_proof_required",
        "classification_dispatch_requires_sufficiency_certificate",
    ):
        if not isinstance(requirements.get(bool_field), bool):
            errors.append(f"{path}.{bool_field} must be boolean")
    for int_field in (
        "min_independent_claim_families",
        "min_independent_source_families",
        "min_temporally_fresh_sources",
        "recency_window_seconds",
        "max_targeted_expansion_attempts",
    ):
        if not _non_negative_int(requirements.get(int_field)):
            errors.append(f"{path}.{int_field} must be a non-negative integer")
    for list_field in ("required_value_fields", "required_negative_checks"):
        if not _string_list(requirements.get(list_field)):
            errors.append(f"{path}.{list_field} must be a string list")
    if requirements.get("classification_dispatch_requires_sufficiency_certificate") is not True:
        errors.append(f"{path}.classification_dispatch_requires_sufficiency_certificate must be true")
    weighting = leaf.get("bayesian_weighting", {})
    critical_or_source = (
        leaf.get("purpose") == "source_of_truth"
        or isinstance(weighting, dict)
        and weighting.get("static_information_weight") == "critical"
    )
    if critical_or_source and not (
        requirements.get("protected_primary_required") or requirements.get("unanswerability_proof_required")
    ):
        errors.append(f"{path} critical/source-of-truth leaves require protected primary or unanswerability proof")


def _validate_leaves(
    leaves: Any,
    branches_by_id: dict[str, dict[str, Any]],
    top_level_purposes: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(leaves, list) or not leaves:
        errors.append("required_leaf_questions must be a non-empty list")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    parent_membership: dict[str, list[str]] = {}
    for idx, leaf in enumerate(leaves):
        path = f"required_leaf_questions[{idx}]"
        if not isinstance(leaf, dict):
            errors.append(f"{path} must be an object")
            continue
        for field in REQUIRED_LEAF_FIELDS:
            if field not in leaf:
                errors.append(f"{path} missing {field}")
        leaf_id = leaf.get("leaf_id")
        if not _is_non_empty_string(leaf_id) or not str(leaf_id).startswith("leaf-"):
            errors.append(f"{path}.leaf_id must start with leaf-")
            continue
        if leaf_id in indexed:
            errors.append(f"{path}.leaf_id is duplicated")
        indexed[leaf_id] = leaf
        parent_id = leaf.get("parent_branch_id")
        if parent_id not in branches_by_id:
            errors.append(f"{path}.parent_branch_id must reference an existing branch")
        else:
            parent_membership.setdefault(parent_id, []).append(leaf_id)
        if not _is_non_empty_string(leaf.get("question_text")):
            errors.append(f"{path}.question_text is required")
        if leaf.get("purpose") not in ALLOWED_PURPOSES:
            errors.append(f"{path}.purpose is invalid")
        weighting = leaf.get("bayesian_weighting")
        if not isinstance(weighting, dict):
            errors.append(f"{path}.bayesian_weighting must be an object")
        else:
            if weighting.get("static_information_weight") not in ALLOWED_STATIC_INFORMATION_WEIGHTS:
                errors.append(f"{path}.static_information_weight is invalid")
            if not _reason_codes_are_compact(weighting.get("weight_reason_codes")):
                errors.append(f"{path}.weight_reason_codes must be compact reason codes")
        if not _is_non_empty_string(leaf.get("leaf_dependency_group_id")):
            errors.append(f"{path}.leaf_dependency_group_id is required")
        if leaf.get("leaf_condition_scope") not in ALLOWED_CONDITION_SCOPES:
            errors.append(f"{path}.leaf_condition_scope is invalid")
        if not _string_list(leaf.get("required_evidence_fields")):
            errors.append(f"{path}.required_evidence_fields must be a string list")
        if not _string_list(leaf.get("market_component_terms")):
            errors.append(f"{path}.market_component_terms must be a string list")
        if not isinstance(leaf.get("structural_validation"), dict):
            errors.append(f"{path}.structural_validation must be an object")
        _validate_sufficiency(leaf.get("research_sufficiency_requirements"), leaf, path, errors)

    for branch_id, branch in branches_by_id.items():
        expected = set(branch.get("leaf_ids", []))
        actual = set(parent_membership.get(branch_id, []))
        if expected != actual:
            errors.append(f"branches[{branch_id}].leaf_ids must match leaf parent refs")
    leaf_purposes = sorted({leaf.get("purpose") for leaf in indexed.values() if leaf.get("purpose")})
    if top_level_purposes != leaf_purposes:
        errors.append("required_evidence_purposes must equal sorted unique leaf purposes")
    return indexed


def _validate_related_context_usage(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("related_market_context_usage must be an object")
        return
    for field in (
        "usage_status",
        "related_context_artifact_ref",
        "amrg_usage_refs",
        "weak_context_only",
        "anchor_dependency_status",
    ):
        if field not in value:
            errors.append(f"related_market_context_usage missing {field}")
    if value.get("usage_status") not in ALLOWED_RELATED_CONTEXT_USAGE_STATUS:
        errors.append("related_market_context_usage.usage_status is invalid")
    if value.get("related_context_artifact_ref") is not None and not _is_non_empty_string(
        value.get("related_context_artifact_ref")
    ):
        errors.append("related_market_context_usage.related_context_artifact_ref must be string or null")
    if not isinstance(value.get("amrg_usage_refs"), list):
        errors.append("related_market_context_usage.amrg_usage_refs must be a list")
    if not isinstance(value.get("weak_context_only"), bool):
        errors.append("related_market_context_usage.weak_context_only must be boolean")
    if not _is_non_empty_string(value.get("anchor_dependency_status")):
        errors.append("related_market_context_usage.anchor_dependency_status is required")


def _validate_amrg_contracts(value: Any, leaf_ids: set[str], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("amrg_anchor_dependency_contracts must be a list")
        return
    for idx, contract in enumerate(value):
        path = f"amrg_anchor_dependency_contracts[{idx}]"
        if not isinstance(contract, dict):
            errors.append(f"{path} must be an object")
            continue
        for field in ("contract_id", "related_market_ref", "anchor_role", "required_before_leaf_ids"):
            if field not in contract:
                errors.append(f"{path} missing {field}")
        if not _is_non_empty_string(contract.get("contract_id")):
            errors.append(f"{path}.contract_id is required")
        if not isinstance(contract.get("required_before_leaf_ids"), list):
            errors.append(f"{path}.required_before_leaf_ids must be a list")
        elif not set(contract["required_before_leaf_ids"]).issubset(leaf_ids):
            errors.append(f"{path}.required_before_leaf_ids references unknown leaves")


def _validate_model_context(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("model_execution_context must be an object")
        return
    for field in REQUIRED_MODEL_FIELDS:
        if field not in value:
            errors.append(f"model_execution_context missing {field}")
    if value.get("model_lane_id") != DECOMPOSER_MODEL_LANE_ID:
        errors.append("model_execution_context.model_lane_id must be decomposer_qdt_generation")
    if value.get("resolved_model_id") != DECOMPOSER_MODEL_ID:
        errors.append(f"model_execution_context.resolved_model_id must be {DECOMPOSER_MODEL_ID}")
    if not _is_non_empty_string(value.get("model_policy_ref")):
        errors.append("model_execution_context.model_policy_ref is required")
    if value.get("prompt_template_id") != DECOMPOSER_PROMPT_TEMPLATE_ID:
        errors.append("model_execution_context.prompt_template_id is invalid")
    prompt_hash = value.get("prompt_template_sha256")
    if not _is_non_empty_string(prompt_hash) or not str(prompt_hash).startswith("sha256:"):
        errors.append("model_execution_context.prompt_template_sha256 must be sha256-prefixed")
    if not _string_list(value.get("input_manifest_ids")):
        errors.append("model_execution_context.input_manifest_ids must be a string list")
    if value.get("output_schema_version") != QUESTION_DECOMPOSITION_SCHEMA_VERSION:
        errors.append("model_execution_context.output_schema_version must be question-decomposition/v1")


def _validate_candidate_selection_audit(value: Any, errors: list[str], *, require_selected: bool) -> None:
    if not isinstance(value, dict):
        if require_selected:
            errors.append("candidate_selection_audit must be an object")
        return
    status = value.get("selection_status")
    if require_selected and status != "selected":
        errors.append("candidate_selection_audit.selection_status must be selected")
    if not require_selected and status not in {"candidate", "selected"}:
        errors.append("candidate_selection_audit.selection_status is invalid")
    if status == "selected":
        for field in (
            "candidate_count",
            "selected_candidate_id",
            "selected_candidate_score",
            "rejected_candidates",
            "selected_reason_codes",
            "selection_helper_version",
        ):
            if field not in value:
                errors.append(f"candidate_selection_audit missing {field}")
        if not _positive_int(value.get("candidate_count")):
            errors.append("candidate_selection_audit.candidate_count must be positive integer")
        if not _is_non_empty_string(value.get("selected_candidate_id")):
            errors.append("candidate_selection_audit.selected_candidate_id is required")
        if not isinstance(value.get("selected_candidate_score"), (int, float)) or isinstance(
            value.get("selected_candidate_score"), bool
        ):
            errors.append("candidate_selection_audit.selected_candidate_score must be numeric")
        if not isinstance(value.get("rejected_candidates"), list):
            errors.append("candidate_selection_audit.rejected_candidates must be a list")
        if not _reason_codes_are_compact(value.get("selected_reason_codes")):
            errors.append("candidate_selection_audit.selected_reason_codes must be compact reason codes")


def _validate_validation_summary(value: Any, errors: list[str], *, require_selected: bool) -> None:
    if not isinstance(value, dict):
        errors.append("validation_summary must be an object")
        return
    for field in ("status", "validator_version", "reason_codes", "forbidden_output_check_status"):
        if field not in value:
            errors.append(f"validation_summary missing {field}")
    if require_selected and value.get("status") != "valid":
        errors.append("validation_summary.status must be valid")
    if value.get("validator_version") != QDT_SCHEMA_VALIDATOR_VERSION:
        errors.append("validation_summary.validator_version is invalid")
    if not _reason_codes_are_compact(value.get("reason_codes")):
        errors.append("validation_summary.reason_codes must be compact reason codes")
    if value.get("forbidden_output_check_status") != "passed":
        errors.append("validation_summary.forbidden_output_check_status must be passed")


def validate_question_decomposition(
    artifact: dict[str, Any],
    *,
    require_selected: bool = True,
) -> QDTValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(artifact, dict):
        return QDTValidationResult(False, ("qdt must be an object",))
    _reject_forbidden_qdt_keys(artifact, errors)
    for field in REQUIRED_QDT_FIELDS:
        if field not in artifact:
            errors.append(f"qdt missing {field}")
    if require_selected and "candidate_selection_audit" not in artifact:
        errors.append("qdt missing candidate_selection_audit")
    if artifact.get("artifact_type") != QUESTION_DECOMPOSITION_ARTIFACT_TYPE:
        errors.append("artifact_type must be question_decomposition")
    if artifact.get("schema_version") != QUESTION_DECOMPOSITION_SCHEMA_VERSION:
        errors.append("schema_version must be question-decomposition/v1")
    for field in ("case_id", "market_id", "dispatch_id", "macro_question"):
        if not _is_non_empty_string(artifact.get(field)):
            errors.append(f"{field} is required")
    digest = artifact.get("market_reality_constraints_digest")
    if not _is_non_empty_string(digest) or not str(digest).startswith("sha256:"):
        errors.append("market_reality_constraints_digest must be sha256-prefixed")
    branches_by_id = _validate_branches(artifact.get("branches"), errors)
    leaves_by_id = _validate_leaves(
        artifact.get("required_leaf_questions"),
        branches_by_id,
        artifact.get("required_evidence_purposes"),
        errors,
    )
    _validate_leaf_budget(
        artifact.get("leaf_budget_decision"),
        len(artifact.get("required_leaf_questions") or []),
        errors,
    )
    _validate_related_context_usage(artifact.get("related_market_context_usage"), errors)
    _validate_amrg_contracts(artifact.get("amrg_anchor_dependency_contracts"), set(leaves_by_id), errors)
    _validate_model_context(artifact.get("model_execution_context"), errors)
    _validate_candidate_selection_audit(
        artifact.get("candidate_selection_audit"),
        errors,
        require_selected=require_selected,
    )
    _validate_validation_summary(artifact.get("validation_summary"), errors, require_selected=require_selected)
    if artifact.get("amrg_anchor_dependency_contracts"):
        warnings.append("amrg_anchor_dependency_contracts_schema_only_pending_qdt_004")
    return QDTValidationResult(not errors, tuple(errors), tuple(warnings))


def require_valid_question_decomposition(artifact: dict[str, Any], *, require_selected: bool = True) -> None:
    result = validate_question_decomposition(artifact, require_selected=require_selected)
    if not result.valid:
        raise QDTError("; ".join(result.errors))


def score_qdt_candidate(candidate: dict[str, Any]) -> float:
    leaves = candidate.get("required_leaf_questions", [])
    if not isinstance(leaves, list):
        return -1.0
    purposes = {leaf.get("purpose") for leaf in leaves if isinstance(leaf, dict)}
    weights = [
        leaf.get("bayesian_weighting", {}).get("static_information_weight")
        for leaf in leaves
        if isinstance(leaf, dict) and isinstance(leaf.get("bayesian_weighting"), dict)
    ]
    critical_count = weights.count("critical")
    high_count = weights.count("high")
    source_of_truth_bonus = 2 if "source_of_truth" in purposes else 0
    purpose_coverage = len(purposes)
    leaf_count = len(leaves)
    budget = candidate.get("leaf_budget_decision", {}).get("effective_leaf_budget", leaf_count)
    compact_penalty = max(0, leaf_count - int(budget if isinstance(budget, int) else leaf_count))
    return float(purpose_coverage * 10 + critical_count * 3 + high_count * 2 + source_of_truth_bonus - compact_penalty)


def select_qdt_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(candidates, list) or not candidates:
        raise QDTError("at least one QDT candidate is required")
    accepted: list[tuple[float, int, dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        candidate_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
        if not _is_non_empty_string(candidate_id):
            candidate_id = f"qdt-candidate-{idx + 1:03d}"
        result = validate_question_decomposition(candidate, require_selected=False)
        if result.valid:
            accepted.append((score_qdt_candidate(candidate), idx, candidate))
        else:
            rejected.append(
                {
                    "candidate_id": candidate_id,
                    "rejection_status": "rejected_schema_invalid",
                    "reason_codes": ["qdt_schema_invalid"],
                    "validation_errors": list(result.errors),
                }
            )
    if not accepted:
        raise QDTError("no valid QDT candidates: " + canonical_json(rejected))
    score, _idx, selected = sorted(
        accepted,
        key=lambda item: (-item[0], str(item[2].get("candidate_id", "")), item[1]),
    )[0]
    selected = copy.deepcopy(selected)
    selected_id = selected["candidate_id"]
    selected["candidate_selection_audit"] = {
        "selection_status": "selected",
        "candidate_count": len(candidates),
        "selected_candidate_id": selected_id,
        "selected_candidate_score": score,
        "rejected_candidates": rejected,
        "selected_reason_codes": ["highest_valid_schema_score", "deterministic_tie_break"],
        "selection_helper_version": QDT_SELECTION_HELPER_VERSION,
    }
    selected["validation_summary"] = {
        "status": "valid",
        "validator_version": QDT_SCHEMA_VALIDATOR_VERSION,
        "reason_codes": [
            "question_decomposition_schema_valid",
            "depth_2_branch_leaf_contract_present",
            "research_sufficiency_requirement_fields_present",
            "model_provenance_fields_present",
            "forbidden_output_check_passed",
        ],
        "forbidden_output_check_status": "passed",
    }
    require_valid_question_decomposition(selected)
    return selected


def load_question_decomposition(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QDTError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise QDTError(f"{path} must contain a JSON object")
    return value


def dump_question_decomposition(artifact: dict[str, Any]) -> str:
    require_valid_question_decomposition(artifact)
    return canonical_json(artifact) + "\n"
