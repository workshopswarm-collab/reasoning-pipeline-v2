"""QDT schema, deterministic selection, and no-LLM structural validation helpers."""

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
ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION = "amrg-anchor-dependency-contract/v1"
ANCHOR_DEPENDENCY_REPAIR_HELPER_VERSION = "ads-qdt-anchor-repair/v1"
COMPACT_DEFAULT_LEAF_BUDGET = 6
MAX_REASON_CODE_LENGTH = 80
DEFAULT_ANCHOR_REPAIR_ATTEMPTS = 2
DEFAULT_ANCHOR_REPAIR_WALL_CLOCK_SECONDS = 120

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
ALLOWED_ANSWERABILITY_STATUSES = {"answerable", "unanswerable_policy_candidate"}
ALLOWED_UNANSWERABLE_POLICY_CONSEQUENCES = {
    "requires_unanswerability_proof_before_dispatch",
    "block_classification_until_sufficiency_certificate",
}
CONDITION_SCOPES_REQUIRING_ANCHOR_CONTRACT = {"target_given_upstream", "target_given_not_upstream"}
APPROVED_WAIVER_STATUS = "approved"
ALLOWED_ANCHOR_MODES = {"diagnostic_only", "anchor_optional", "anchor_required"}
ANCHOR_MODES_SATISFYING_CONDITION_SCOPE = {"anchor_optional", "anchor_required"}
STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES = {
    "strict_precedence_anchor_candidate",
    "validated_strict_precedence_anchor",
}
ALLOWED_ANCHOR_FALLBACK_MODES = {
    "watch_only_if_forecastable",
    "use_unconditional_fallback_leaf",
    "fail_dispatch_preparation",
}
ALLOWED_REPAIR_EXHAUSTION_POLICIES = {
    "watch_only_if_forecastable",
    "fail_dispatch_preparation",
}
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
REQUIRED_ANCHOR_CONTRACT_FIELDS = (
    "schema_version",
    "anchor_dependency_contract_id",
    "edge_id",
    "edge_status",
    "conditional_branch_group_id",
    "anchor_mode",
    "condition_scoped_leaf_ids",
    "fallback_policy",
    "max_anchor_repair_attempts",
    "max_anchor_repair_wall_clock_seconds",
    "repair_exhaustion_policy",
)
REQUIRED_ANCHOR_FALLBACK_FIELDS = (
    "fallback_policy_id",
    "fallback_mode",
    "fallback_leaf_ids",
    "fallback_reason_codes",
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


@dataclass(frozen=True)
class AnchorRepairPolicy:
    max_anchor_repair_attempts: int = DEFAULT_ANCHOR_REPAIR_ATTEMPTS
    max_anchor_repair_wall_clock_seconds: int = DEFAULT_ANCHOR_REPAIR_WALL_CLOCK_SECONDS
    repair_exhaustion_policy: str = "fail_dispatch_preparation"


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


def _has_approved_waiver(summary: Any, field: str) -> bool:
    if not isinstance(summary, dict):
        return False
    waiver = summary.get(field)
    return isinstance(waiver, dict) and waiver.get("waiver_status") == APPROVED_WAIVER_STATUS


def _extract_string_list(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(_is_non_empty_string(item) for item in value):
        return list(value)
    return None


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:24]}"


def _normalize_leaf_collection(leaves: Any) -> list[dict[str, Any]]:
    if isinstance(leaves, dict):
        return [leaf for leaf in leaves.values() if isinstance(leaf, dict)]
    if isinstance(leaves, list):
        return [leaf for leaf in leaves if isinstance(leaf, dict)]
    return []


def _leaves_by_id(leaves: Any) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for leaf in _normalize_leaf_collection(leaves):
        leaf_id = leaf.get("leaf_id")
        if _is_non_empty_string(leaf_id):
            indexed[str(leaf_id)] = leaf
    return indexed


def _edge_status(edge: dict[str, Any]) -> str:
    for field in ("anchor_validation_status", "edge_status", "status", "relationship_status"):
        value = edge.get(field)
        if _is_non_empty_string(value):
            return str(value)
    return "unknown"


def _branch_ordered_leaf_ids(qdt_branch: dict[str, Any], leaves: Any) -> list[str]:
    leaves_by_id = _leaves_by_id(leaves)
    ordered: list[str] = []
    branch_leaf_ids = qdt_branch.get("leaf_ids")
    if isinstance(branch_leaf_ids, list):
        ordered.extend(str(leaf_id) for leaf_id in branch_leaf_ids if str(leaf_id) in leaves_by_id)
    branch_id = qdt_branch.get("branch_id")
    for leaf in _normalize_leaf_collection(leaves):
        leaf_id = leaf.get("leaf_id")
        if (
            _is_non_empty_string(leaf_id)
            and leaf_id not in ordered
            and _is_non_empty_string(branch_id)
            and leaf.get("parent_branch_id") == branch_id
        ):
            ordered.append(str(leaf_id))
    return ordered


def find_condition_scoped_leaves(qdt_branch: dict[str, Any], leaves: Any) -> list[str]:
    """Return branch leaves that need explicit AMRG anchor contracts."""

    leaves_by_id = _leaves_by_id(leaves)
    scoped: list[str] = []
    for leaf_id in _branch_ordered_leaf_ids(qdt_branch, leaves):
        leaf = leaves_by_id.get(leaf_id)
        if leaf and leaf.get("leaf_condition_scope") in CONDITION_SCOPES_REQUIRING_ANCHOR_CONTRACT:
            scoped.append(leaf_id)
    return scoped


def _unconditional_fallback_leaf_ids(qdt_branch: dict[str, Any], leaves: Any) -> list[str]:
    leaves_by_id = _leaves_by_id(leaves)
    fallback: list[str] = []
    for leaf_id in _branch_ordered_leaf_ids(qdt_branch, leaves):
        leaf = leaves_by_id.get(leaf_id)
        if leaf and leaf.get("leaf_condition_scope") in {"unconditional", "shared_context"}:
            fallback.append(leaf_id)
    return fallback


def choose_anchor_mode(
    edge: dict[str, Any],
    qdt_branch: dict[str, Any],
    condition_scoped_leaf_ids: list[str] | None = None,
) -> str:
    edge_status = _edge_status(edge)
    if edge_status not in STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES:
        return "diagnostic_only"
    if not condition_scoped_leaf_ids:
        return "diagnostic_only"
    explicit = qdt_branch.get("anchor_mode") or qdt_branch.get("anchor_dependency_mode")
    if explicit in ALLOWED_ANCHOR_MODES:
        return str(explicit)
    if edge_status == "validated_strict_precedence_anchor":
        return "anchor_required"
    return "anchor_optional"


def _normalize_repair_policy(policy: AnchorRepairPolicy | dict[str, Any] | None, anchor_mode: str) -> dict[str, Any]:
    if isinstance(policy, AnchorRepairPolicy):
        raw = {
            "max_anchor_repair_attempts": policy.max_anchor_repair_attempts,
            "max_anchor_repair_wall_clock_seconds": policy.max_anchor_repair_wall_clock_seconds,
            "repair_exhaustion_policy": policy.repair_exhaustion_policy,
        }
    else:
        raw = dict(policy or {})
    if anchor_mode == "diagnostic_only":
        default_attempts = 0
        default_wall_clock = 0
        default_exhaustion = "watch_only_if_forecastable"
    else:
        default_attempts = DEFAULT_ANCHOR_REPAIR_ATTEMPTS
        default_wall_clock = DEFAULT_ANCHOR_REPAIR_WALL_CLOCK_SECONDS
        default_exhaustion = "fail_dispatch_preparation" if anchor_mode == "anchor_required" else "watch_only_if_forecastable"
    return {
        "max_anchor_repair_attempts": int(raw.get("max_anchor_repair_attempts", default_attempts)),
        "max_anchor_repair_wall_clock_seconds": int(
            raw.get("max_anchor_repair_wall_clock_seconds", default_wall_clock)
        ),
        "repair_exhaustion_policy": raw.get("repair_exhaustion_policy", default_exhaustion),
    }


def derive_fallback_policy(
    qdt_branch: dict[str, Any],
    leaves: Any = None,
    *,
    anchor_mode: str = "anchor_required",
) -> dict[str, Any]:
    fallback = copy.deepcopy(qdt_branch.get("fallback_policy") or {})
    if not isinstance(fallback, dict):
        fallback = {}
    fallback_leaf_ids = fallback.get("fallback_leaf_ids")
    if not isinstance(fallback_leaf_ids, list):
        fallback_leaf_ids = _unconditional_fallback_leaf_ids(qdt_branch, leaves)
    fallback_leaf_ids = [str(leaf_id) for leaf_id in fallback_leaf_ids if _is_non_empty_string(leaf_id)]

    fallback_mode = fallback.get("fallback_mode")
    if fallback_mode not in ALLOWED_ANCHOR_FALLBACK_MODES:
        if fallback_leaf_ids:
            fallback_mode = "use_unconditional_fallback_leaf"
        elif anchor_mode == "anchor_required":
            fallback_mode = "fail_dispatch_preparation"
        else:
            fallback_mode = "watch_only_if_forecastable"

    reason_codes = fallback.get("fallback_reason_codes")
    if not _reason_codes_are_compact(reason_codes):
        reason_codes = [
            "anchor_required" if anchor_mode == "anchor_required" else "anchor_not_required",
            "qdt_anchor_fallback_policy",
        ]
    return {
        "fallback_policy_id": fallback.get("fallback_policy_id")
        or _stable_id(
            "anchor-fallback:",
            qdt_branch.get("branch_id"),
            fallback_mode,
            fallback_leaf_ids,
        ),
        "fallback_mode": fallback_mode,
        "fallback_leaf_ids": fallback_leaf_ids,
        "fallback_reason_codes": list(reason_codes),
    }


def build_anchor_dependency_contract(
    edge: dict[str, Any],
    qdt_branch: dict[str, Any],
    *,
    leaves: Any = None,
    related_market_ref: str | None = None,
    repair_policy: AnchorRepairPolicy | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(edge, dict):
        raise QDTError("edge must be an object")
    if not isinstance(qdt_branch, dict):
        raise QDTError("qdt_branch must be an object")
    edge_id = edge.get("edge_id")
    if not _is_non_empty_string(edge_id):
        raise QDTError("edge_id is required")
    condition_scoped_leaf_ids = find_condition_scoped_leaves(qdt_branch, leaves)
    anchor_mode = choose_anchor_mode(edge, qdt_branch, condition_scoped_leaf_ids)
    normalized_policy = _normalize_repair_policy(repair_policy, anchor_mode)
    branch_id = qdt_branch.get("branch_id")
    fallback_policy = derive_fallback_policy(qdt_branch, leaves, anchor_mode=anchor_mode)
    ref = (
        related_market_ref
        or edge.get("related_market_ref")
        or edge.get("context_artifact_ref")
        or edge.get("candidate_set_id")
    )
    contract = {
        "schema_version": ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION,
        "anchor_dependency_contract_id": _stable_id(
            "anchor-contract:",
            edge_id,
            branch_id,
            anchor_mode,
            condition_scoped_leaf_ids,
        ),
        "edge_id": str(edge_id),
        "edge_status": _edge_status(edge),
        "conditional_branch_group_id": _stable_id("conditional-branch-group:", edge_id, branch_id),
        "anchor_mode": anchor_mode,
        "condition_scoped_leaf_ids": condition_scoped_leaf_ids,
        "required_before_leaf_ids": condition_scoped_leaf_ids,
        "fallback_policy": fallback_policy,
        "max_anchor_repair_attempts": normalized_policy["max_anchor_repair_attempts"],
        "max_anchor_repair_wall_clock_seconds": normalized_policy["max_anchor_repair_wall_clock_seconds"],
        "repair_exhaustion_policy": normalized_policy["repair_exhaustion_policy"],
    }
    if _is_non_empty_string(branch_id):
        contract["qdt_branch_id"] = branch_id
    if _is_non_empty_string(ref):
        contract["related_market_ref"] = str(ref)
    if _is_non_empty_string(edge.get("candidate_id")):
        contract["edge_candidate_id"] = str(edge["candidate_id"])
    if _is_non_empty_string(edge.get("related_market_id")):
        contract["related_market_id"] = str(edge["related_market_id"])
    return contract


def _required_purposes_from_evidence_packet(evidence_packet: dict[str, Any] | None) -> list[str] | None:
    if not isinstance(evidence_packet, dict):
        return None
    candidates = [
        evidence_packet.get("required_evidence_purposes"),
        evidence_packet.get("required_research_purposes"),
    ]
    for container_key in ("decomposition_requirements", "market_reality_constraints"):
        container = evidence_packet.get(container_key)
        if isinstance(container, dict):
            candidates.extend(
                [
                    container.get("required_evidence_purposes"),
                    container.get("required_research_purposes"),
                    container.get("required_purposes"),
                ]
            )
    for candidate in candidates:
        purposes = _extract_string_list(candidate)
        if purposes is not None:
            return sorted(set(purposes))
    return None


def _market_reality_constraints_digest_from_evidence_packet(evidence_packet: dict[str, Any] | None) -> str | None:
    if not isinstance(evidence_packet, dict):
        return None
    digest = evidence_packet.get("market_reality_constraints_digest")
    if _is_non_empty_string(digest):
        return str(digest)
    if "market_reality_constraints" in evidence_packet:
        return _prefixed_sha256(evidence_packet.get("market_reality_constraints") or {})
    return None


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
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
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
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
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
            "structural_validation": {"depth": 1},
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
                "structural_validation": {"depth": 2, "answerability_status": "answerable"},
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
                "structural_validation": {"depth": 1},
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


def _validate_branches(branches: Any, errors: list[str], *, depth_waived: bool) -> dict[str, dict[str, Any]]:
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
        if any(key in branch for key in ("branches", "child_branches", "children")) and not depth_waived:
            errors.append(f"{path} invalid_depth: nested branches require approved depth waiver")
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
        structural = branch.get("structural_validation")
        if not isinstance(structural, dict):
            errors.append(f"{path}.structural_validation must be an object")
        elif structural.get("depth") != 1 and not depth_waived:
            errors.append(f"{path}.structural_validation.depth invalid_depth: branch depth must equal 1")
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
    if critical_or_source and requirements.get("allow_macro_fallback_for_leaf") is True:
        errors.append(f"{path} critical/source-of-truth leaves cannot allow macro fallback as sufficient research")


def _validate_leaf_structural_validation(
    structural: Any,
    requirements: Any,
    path: str,
    errors: list[str],
    *,
    depth_waived: bool,
) -> None:
    if not isinstance(structural, dict):
        errors.append(f"{path}.structural_validation must be an object")
        return
    if structural.get("depth") != 2 and not depth_waived:
        errors.append(f"{path}.structural_validation.depth invalid_depth: leaf depth must equal 2")
    answerability = structural.get("answerability_status")
    if answerability not in ALLOWED_ANSWERABILITY_STATUSES:
        errors.append(f"{path}.structural_validation.answerability_status is required")
        return
    if answerability != "unanswerable_policy_candidate":
        return
    consequence = structural.get("unanswerable_policy_consequence")
    if consequence not in ALLOWED_UNANSWERABLE_POLICY_CONSEQUENCES:
        errors.append(f"{path}.structural_validation.unanswerable_policy_consequence is required")
    if not isinstance(requirements, dict) or requirements.get("unanswerability_proof_required") is not True:
        errors.append(f"{path}.structural_validation unanswerable policy candidates require proof before dispatch")


def _validate_leaves(
    leaves: Any,
    branches_by_id: dict[str, dict[str, Any]],
    top_level_purposes: Any,
    errors: list[str],
    *,
    depth_waived: bool,
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
        if any(key in leaf for key in ("branches", "child_branches", "children", "required_leaf_questions")) and not depth_waived:
            errors.append(f"{path} invalid_depth: leaves must not contain child decomposition nodes")
        _validate_leaf_structural_validation(
            leaf.get("structural_validation"),
            leaf.get("research_sufficiency_requirements"),
            path,
            errors,
            depth_waived=depth_waived,
        )
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


def _validate_anchor_fallback_policy(
    fallback: Any,
    path: str,
    leaf_ids: set[str],
    leaves_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    if not isinstance(fallback, dict):
        errors.append(f"{path}.fallback_policy must be an object")
        return
    for field in REQUIRED_ANCHOR_FALLBACK_FIELDS:
        if field not in fallback:
            errors.append(f"{path}.fallback_policy missing {field}")
    if not _is_non_empty_string(fallback.get("fallback_policy_id")):
        errors.append(f"{path}.fallback_policy.fallback_policy_id is required")
    if fallback.get("fallback_mode") not in ALLOWED_ANCHOR_FALLBACK_MODES:
        errors.append(f"{path}.fallback_policy.fallback_mode is invalid")
    fallback_leaf_ids = fallback.get("fallback_leaf_ids")
    if not isinstance(fallback_leaf_ids, list):
        errors.append(f"{path}.fallback_policy.fallback_leaf_ids must be a list")
    elif not set(fallback_leaf_ids).issubset(leaf_ids):
        errors.append(f"{path}.fallback_policy.fallback_leaf_ids references unknown leaves")
    elif fallback.get("fallback_mode") == "use_unconditional_fallback_leaf":
        if not fallback_leaf_ids:
            errors.append(f"{path}.fallback_policy fallback leaf mode requires fallback_leaf_ids")
        for leaf_id in fallback_leaf_ids:
            leaf = leaves_by_id.get(leaf_id)
            if leaf and leaf.get("leaf_condition_scope") in CONDITION_SCOPES_REQUIRING_ANCHOR_CONTRACT:
                errors.append(f"{path}.fallback_policy fallback leaves must be unconditional or shared context")
    if not _reason_codes_are_compact(fallback.get("fallback_reason_codes")):
        errors.append(f"{path}.fallback_policy.fallback_reason_codes must be compact reason codes")


def _validate_anchor_dependency_contract(
    contract: Any,
    path: str,
    leaf_ids: set[str],
    leaves_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    if not isinstance(contract, dict):
        errors.append(f"{path} must be an object")
        return
    for field in REQUIRED_ANCHOR_CONTRACT_FIELDS:
        if field not in contract:
            errors.append(f"{path} missing {field}")
    if contract.get("schema_version") != ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION}")
    if not _is_non_empty_string(contract.get("anchor_dependency_contract_id")):
        errors.append(f"{path}.anchor_dependency_contract_id is required")
    if not _is_non_empty_string(contract.get("edge_id")):
        errors.append(f"{path}.edge_id is required")
    edge_status = contract.get("edge_status")
    if not _is_non_empty_string(edge_status):
        errors.append(f"{path}.edge_status is required")
    if not _is_non_empty_string(contract.get("conditional_branch_group_id")):
        errors.append(f"{path}.conditional_branch_group_id is required")
    anchor_mode = contract.get("anchor_mode")
    if anchor_mode not in ALLOWED_ANCHOR_MODES:
        errors.append(f"{path}.anchor_mode is invalid")
    condition_scoped = contract.get("condition_scoped_leaf_ids")
    if not isinstance(condition_scoped, list):
        errors.append(f"{path}.condition_scoped_leaf_ids must be a list")
        condition_scoped = []
    elif not set(condition_scoped).issubset(leaf_ids):
        errors.append(f"{path}.condition_scoped_leaf_ids references unknown leaves")
    else:
        for leaf_id in condition_scoped:
            leaf = leaves_by_id.get(leaf_id)
            if leaf and leaf.get("leaf_condition_scope") not in CONDITION_SCOPES_REQUIRING_ANCHOR_CONTRACT:
                errors.append(f"{path}.condition_scoped_leaf_ids must reference condition-scoped leaves")

    required_before = contract.get("required_before_leaf_ids")
    if required_before is not None:
        if not isinstance(required_before, list):
            errors.append(f"{path}.required_before_leaf_ids must be a list")
        elif not set(required_before).issubset(leaf_ids):
            errors.append(f"{path}.required_before_leaf_ids references unknown leaves")

    if anchor_mode in ANCHOR_MODES_SATISFYING_CONDITION_SCOPE:
        if edge_status not in STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES:
            errors.append(f"{path}.anchor_mode cannot use weak or non-strict AMRG edge status {edge_status}")
        if not condition_scoped:
            errors.append(f"{path}.condition_scoped_leaf_ids required for {anchor_mode}")

    _validate_anchor_fallback_policy(contract.get("fallback_policy"), path, leaf_ids, leaves_by_id, errors)
    for int_field in ("max_anchor_repair_attempts", "max_anchor_repair_wall_clock_seconds"):
        if not _non_negative_int(contract.get(int_field)):
            errors.append(f"{path}.{int_field} must be a non-negative integer")
    if anchor_mode == "anchor_required":
        if not _positive_int(contract.get("max_anchor_repair_attempts")):
            errors.append(f"{path}.max_anchor_repair_attempts must be positive for anchor_required")
        if not _positive_int(contract.get("max_anchor_repair_wall_clock_seconds")):
            errors.append(f"{path}.max_anchor_repair_wall_clock_seconds must be positive for anchor_required")
    if contract.get("repair_exhaustion_policy") not in ALLOWED_REPAIR_EXHAUSTION_POLICIES:
        errors.append(f"{path}.repair_exhaustion_policy is invalid")
    related_ref = contract.get("related_market_ref")
    if related_ref is not None and not _is_non_empty_string(related_ref):
        errors.append(f"{path}.related_market_ref must be string or null")


def validate_anchor_dependency_contract(
    contract: dict[str, Any],
    *,
    leaves: Any = None,
) -> QDTValidationResult:
    leaves_by_id = _leaves_by_id(leaves)
    errors: list[str] = []
    _validate_anchor_dependency_contract(contract, "anchor_dependency_contract", set(leaves_by_id), leaves_by_id, errors)
    return QDTValidationResult(not errors, tuple(errors))


def _validate_amrg_contracts(value: Any, leaves_by_id: dict[str, dict[str, Any]], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("amrg_anchor_dependency_contracts must be a list")
        return
    leaf_ids = set(leaves_by_id)
    seen_contract_ids: set[str] = set()
    for idx, contract in enumerate(value):
        path = f"amrg_anchor_dependency_contracts[{idx}]"
        before = len(errors)
        _validate_anchor_dependency_contract(contract, path, leaf_ids, leaves_by_id, errors)
        if isinstance(contract, dict):
            contract_id = contract.get("anchor_dependency_contract_id")
            if _is_non_empty_string(contract_id):
                if contract_id in seen_contract_ids:
                    errors.append(f"{path}.anchor_dependency_contract_id is duplicated")
                seen_contract_ids.add(str(contract_id))
            if len(errors) == before and contract.get("anchor_mode") == "anchor_required":
                fallback = contract.get("fallback_policy", {})
                if not fallback or not contract.get("repair_exhaustion_policy"):
                    errors.append(f"{path} anchor_required requires fallback and repair policy")


def _validate_condition_scope_contracts(
    leaves_by_id: dict[str, dict[str, Any]],
    contracts: Any,
    errors: list[str],
) -> None:
    if not isinstance(contracts, list):
        return
    contracted_leaf_ids: set[str] = set()
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        if contract.get("anchor_mode") not in ANCHOR_MODES_SATISFYING_CONDITION_SCOPE:
            continue
        for field in ("condition_scoped_leaf_ids", "required_before_leaf_ids"):
            values = contract.get(field)
            if isinstance(values, list):
                contracted_leaf_ids.update(item for item in values if isinstance(item, str))
    for leaf_id, leaf in leaves_by_id.items():
        scope = leaf.get("leaf_condition_scope")
        if scope in CONDITION_SCOPES_REQUIRING_ANCHOR_CONTRACT and leaf_id not in contracted_leaf_ids:
            errors.append(
                f"required_leaf_questions[{leaf_id}].leaf_condition_scope requires valid anchor contract"
            )


def _validate_required_purpose_coverage(
    artifact: dict[str, Any],
    leaves_by_id: dict[str, dict[str, Any]],
    evidence_packet: dict[str, Any] | None,
    errors: list[str],
) -> None:
    required = _required_purposes_from_evidence_packet(evidence_packet)
    if required is None:
        return
    observed = sorted({leaf.get("purpose") for leaf in leaves_by_id.values() if leaf.get("purpose")})
    missing = sorted(set(required) - set(observed))
    if missing and not _has_approved_waiver(artifact.get("validation_summary"), "purpose_coverage_waiver"):
        errors.append("required_purpose_coverage_missing: " + ", ".join(missing))


def _validate_market_reality_digest(
    artifact: dict[str, Any],
    evidence_packet: dict[str, Any] | None,
    errors: list[str],
) -> None:
    expected = _market_reality_constraints_digest_from_evidence_packet(evidence_packet)
    if expected is None:
        return
    if artifact.get("market_reality_constraints_digest") != expected:
        errors.append("market_reality_constraints_digest does not match evidence packet")


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
    evidence_packet: dict[str, Any] | None = None,
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
    _validate_market_reality_digest(artifact, evidence_packet, errors)
    depth_waived = _has_approved_waiver(artifact.get("validation_summary"), "depth_waiver")
    branches_by_id = _validate_branches(artifact.get("branches"), errors, depth_waived=depth_waived)
    leaves_by_id = _validate_leaves(
        artifact.get("required_leaf_questions"),
        branches_by_id,
        artifact.get("required_evidence_purposes"),
        errors,
        depth_waived=depth_waived,
    )
    _validate_required_purpose_coverage(artifact, leaves_by_id, evidence_packet, errors)
    _validate_leaf_budget(
        artifact.get("leaf_budget_decision"),
        len(artifact.get("required_leaf_questions") or []),
        errors,
    )
    _validate_related_context_usage(artifact.get("related_market_context_usage"), errors)
    _validate_amrg_contracts(artifact.get("amrg_anchor_dependency_contracts"), leaves_by_id, errors)
    _validate_condition_scope_contracts(leaves_by_id, artifact.get("amrg_anchor_dependency_contracts"), errors)
    _validate_model_context(artifact.get("model_execution_context"), errors)
    _validate_candidate_selection_audit(
        artifact.get("candidate_selection_audit"),
        errors,
        require_selected=require_selected,
    )
    _validate_validation_summary(artifact.get("validation_summary"), errors, require_selected=require_selected)
    return QDTValidationResult(not errors, tuple(errors), tuple(warnings))


def validate_qdt_structure(
    artifact: dict[str, Any],
    evidence_packet: dict[str, Any] | None = None,
    *,
    require_selected: bool = True,
) -> QDTValidationResult:
    return validate_question_decomposition(
        artifact,
        require_selected=require_selected,
        evidence_packet=evidence_packet,
    )


def require_valid_question_decomposition(
    artifact: dict[str, Any],
    *,
    require_selected: bool = True,
    evidence_packet: dict[str, Any] | None = None,
) -> None:
    result = validate_question_decomposition(
        artifact,
        require_selected=require_selected,
        evidence_packet=evidence_packet,
    )
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
            "deterministic_structural_validation_passed",
            "research_sufficiency_requirement_fields_present",
            "model_provenance_fields_present",
            "forbidden_output_check_passed",
        ],
        "forbidden_output_check_status": "passed",
    }
    require_valid_question_decomposition(selected)
    return selected


def _relationship_edges_from_context(related_market_context: Any) -> list[dict[str, Any]]:
    if not isinstance(related_market_context, dict):
        return []
    edges = related_market_context.get("relationship_edges")
    if not isinstance(edges, list):
        return []
    return [edge for edge in edges if isinstance(edge, dict) and _is_non_empty_string(edge.get("edge_id"))]


def _edge_ref_value(ref: Any) -> str | None:
    if _is_non_empty_string(ref):
        return str(ref)
    if isinstance(ref, dict):
        for field in ("edge_id", "ref_id", "id"):
            if _is_non_empty_string(ref.get(field)):
                return str(ref[field])
    return None


def _select_repair_edge(qdt_branch: dict[str, Any], edges: list[dict[str, Any]]) -> dict[str, Any] | None:
    edges_by_id = {str(edge["edge_id"]): edge for edge in edges}
    preferred_refs = qdt_branch.get("amrg_usage_refs")
    if isinstance(preferred_refs, list):
        for ref in preferred_refs:
            edge_id = _edge_ref_value(ref)
            if edge_id in edges_by_id and _edge_status(edges_by_id[edge_id]) in STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES:
                return edges_by_id[edge_id]
    for edge in edges:
        if _edge_status(edge) in STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES:
            return edge
    return None


def _covered_condition_scoped_leaf_ids(contracts: Any) -> set[str]:
    covered: set[str] = set()
    if not isinstance(contracts, list):
        return covered
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        if contract.get("anchor_mode") not in ANCHOR_MODES_SATISFYING_CONDITION_SCOPE:
            continue
        values = contract.get("condition_scoped_leaf_ids")
        if isinstance(values, list):
            covered.update(item for item in values if isinstance(item, str))
    return covered


def repair_anchor_dependency_contracts(
    artifact: dict[str, Any],
    *,
    related_market_context: dict[str, Any] | None = None,
    repair_policy: AnchorRepairPolicy | dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise QDTError("qdt must be an object")
    repaired = copy.deepcopy(artifact)
    leaves = repaired.get("required_leaf_questions") or []
    contracts = repaired.get("amrg_anchor_dependency_contracts")
    if not isinstance(contracts, list):
        contracts = []
    contracts = copy.deepcopy(contracts)
    edges = _relationship_edges_from_context(related_market_context)
    covered = _covered_condition_scoped_leaf_ids(contracts)
    repaired_contract_ids: list[str] = []
    unrepaired_leaf_ids: list[str] = []
    edge_ids_used: list[str] = []
    related_ref = repaired.get("related_market_context_usage", {}).get("related_context_artifact_ref")

    for branch in repaired.get("branches") or []:
        if not isinstance(branch, dict):
            continue
        condition_scoped_leaf_ids = find_condition_scoped_leaves(branch, leaves)
        missing = [leaf_id for leaf_id in condition_scoped_leaf_ids if leaf_id not in covered]
        if not missing:
            continue
        edge = _select_repair_edge(branch, edges)
        if edge is None:
            unrepaired_leaf_ids.extend(missing)
            continue
        contract = build_anchor_dependency_contract(
            edge,
            branch,
            leaves=leaves,
            related_market_ref=related_ref,
            repair_policy=repair_policy,
        )
        contracts.append(contract)
        repaired_contract_ids.append(contract["anchor_dependency_contract_id"])
        edge_ids_used.append(contract["edge_id"])
        covered.update(contract["condition_scoped_leaf_ids"])

    repaired["amrg_anchor_dependency_contracts"] = contracts
    if isinstance(repaired.get("related_market_context_usage"), dict):
        usage = copy.deepcopy(repaired["related_market_context_usage"])
        existing_refs = [str(ref) for ref in usage.get("amrg_usage_refs", []) if _is_non_empty_string(ref)]
        usage["amrg_usage_refs"] = sorted(set(existing_refs + edge_ids_used))
        if unrepaired_leaf_ids:
            usage["anchor_dependency_status"] = "repair_exhausted"
        elif contracts:
            usage["anchor_dependency_status"] = "declared"
        repaired["related_market_context_usage"] = usage
    if repaired_contract_ids and isinstance(repaired.get("validation_summary"), dict):
        summary = copy.deepcopy(repaired["validation_summary"])
        reason_codes = list(summary.get("reason_codes") or [])
        for code in ("amrg_anchor_dependency_contract_present", "anchor_dependency_repair_bounded"):
            if code not in reason_codes:
                reason_codes.append(code)
        summary["reason_codes"] = reason_codes
        repaired["validation_summary"] = summary

    require_selected = repaired.get("candidate_selection_audit", {}).get("selection_status") == "selected"
    validation = validate_question_decomposition(repaired, require_selected=require_selected)
    return {
        "artifact": repaired,
        "repair_summary": {
            "repair_helper_version": ANCHOR_DEPENDENCY_REPAIR_HELPER_VERSION,
            "repaired_contract_ids": repaired_contract_ids,
            "edge_ids_used": sorted(set(edge_ids_used)),
            "unrepaired_condition_scoped_leaf_ids": sorted(set(unrepaired_leaf_ids)),
            "repair_exhausted": bool(unrepaired_leaf_ids),
            "post_repair_valid": validation.valid,
            "post_repair_errors": list(validation.errors),
        },
    }


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
