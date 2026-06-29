"""QDT schema, deterministic selection, and no-LLM structural validation helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
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
from .sufficiency_requirements import (
    REQUIRED_SUFFICIENCY_FIELDS,
    SUFFICIENCY_PROFILE_ID,
    build_research_sufficiency_requirements as _build_research_sufficiency_requirements,
    validate_research_sufficiency_requirements,
)


QUESTION_DECOMPOSITION_ARTIFACT_TYPE = "question_decomposition"
QDT_SCHEMA_VALIDATOR_VERSION = "ads-qdt-schema/v1"
QDT_SELECTION_HELPER_VERSION = "ads-qdt-selection/v1"
ANCHOR_DEPENDENCY_CONTRACT_SCHEMA_VERSION = "amrg-anchor-dependency-contract/v1"
ANCHOR_DEPENDENCY_REPAIR_HELPER_VERSION = "ads-qdt-anchor-repair/v1"
COMPACT_DEFAULT_LEAF_BUDGET = 10
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
ALLOWED_RESEARCH_PRIORITIES = {"critical", "high", "medium", "low"}
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
ALLOWED_MARKET_TEMPORAL_STATES = {"unresolved", "resolved_or_settlement_audit"}
ALLOWED_LEAF_TEMPORAL_ROLES = {
    "pre_resolution_forecast_driver",
    "current_status",
    "resolution_mechanics",
    "terminal_verification",
    "material_unknown",
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
    "bayesian",
    "probability",
    "fair_value",
    "confidence_interval",
    "credible_interval",
    "prediction_interval",
    "interval",
    "reassembly",
    "log_odds",
    "bayesian_edge",
    "scae_delta",
    "trade_decision",
    "final_forecast",
    "weight",
)
ALLOWED_COVERAGE_DIMENSIONS = {
    "resolution_mechanics",
    "current_direct_evidence",
    "key_drivers",
    "counterevidence_negative_checks",
    "timing_deadline_constraints",
    "source_quality",
    "related_market_or_base_rate_context",
    "material_unknowns",
}
REQUIRED_CORE_COVERAGE_DIMENSIONS = {
    "resolution_mechanics",
    "current_direct_evidence",
    "key_drivers",
    "counterevidence_negative_checks",
    "timing_deadline_constraints",
    "source_quality",
    "material_unknowns",
}
CONTRACT_GUARD_COVERAGE_DIMENSIONS = {"resolution_mechanics"}
UNRESOLVED_PRE_RESOLUTION_FORECAST_DIMENSIONS = {
    "current_direct_evidence",
    "key_drivers",
    "counterevidence_negative_checks",
    "timing_deadline_constraints",
    "source_quality",
    "material_unknowns",
}
TERMINAL_VERIFICATION_DOMINATION_THRESHOLD = 0.5
TERMINAL_RESULT_VERIFICATION_PATTERNS = (
    r"\bwon\b",
    r"\boverall winner\b",
    r"\bofficial result\b",
    r"\bfirst official announcement\b",
    r"\bofficial\b.{0,80}\bwinner\b",
    r"\bwhat did\b.{0,120}\bstate\b.{0,120}\bwinner\b",
    r"\bwhether\b.{0,120}\bwon\b",
    r"\bdid\b.{0,120}\btake place\b",
    r"\bfinal\b.{0,80}\bresult\b",
    r"\bresolved\b",
)
FORBIDDEN_LEAF_OUTPUTS = {
    "probability",
    "odds",
    "numeric_weight",
    "bayesian_edge",
    "log_odds_delta",
    "fair_value",
    "trade_decision",
    "scae_delta",
    "final_forecast",
}
GENERIC_QDT_SKELETONS = (
    "What official or primary-source information can resolve the market question?",
    "What fresh direct evidence bears on the target event before the cutoff?",
    "Which market rules and timing terms govern how the outcome resolves?",
    "What is the official announcement status?",
    "What is the actor identity?",
    "What is the timing window?",
    "What is the credible reporting consensus?",
    "How do official sources and reporting align?",
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
    "market_resolution_contract",
    "research_coverage_graph",
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
    "leaf_temporal_role",
    "purpose",
    "research_priority",
    "leaf_dependency_group_id",
    "leaf_condition_scope",
    "required_evidence_fields",
    "research_sufficiency_requirements",
    "coverage_dimension",
    "research_factor",
    "leaf_question",
    "evidence_requirements",
    "classification_targets",
    "sufficiency_criteria",
    "specificity_evidence",
    "overlap_risk_with_leaf_ids",
    "missingness_interpretation",
    "forbidden_outputs",
    "market_component_terms",
    "structural_validation",
)
REQUIRED_MARKET_RESOLUTION_CONTRACT_FIELDS = (
    "yes_no_mapping",
    "resolution_subject",
    "resolution_authority",
    "contract_deadline",
    "forecast_cutoff",
    "platform_family_context",
    "ambiguous_terms",
    "disqualifying_evidence_types",
    "source_hierarchy",
)
REQUIRED_RESEARCH_COVERAGE_GRAPH_FIELDS = (
    "target_event_description",
    "forecast_research_objective",
    "market_temporal_state",
    "coverage_dimensions",
    "research_factors",
    "contract_guard_leaf_ids",
    "material_question_leaf_ids",
    "terminal_verification_leaf_ids",
    "dispatchable_pre_resolution_leaf_ids",
    "required_leaf_ids_by_dimension",
    "overlap_groups",
    "unanswered_material_questions",
    "coverage_summary",
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


def _text_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 2
        and token
        not in {
            "the",
            "and",
            "for",
            "with",
            "will",
            "market",
            "question",
            "target",
            "event",
            "before",
            "after",
            "status",
            "evidence",
            "source",
            "sources",
        }
    }


def _token_slug(value: Any, *, fallback: str = "market") -> str:
    allowed = _text_tokens(value)
    tokens = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        if token in allowed and token not in seen:
            seen.add(token)
            tokens.append(token)
    slug = "-".join(tokens[:4])
    return slug or fallback


def _template_similarity(left: str, right: str) -> float:
    left_tokens = _text_tokens(left)
    right_tokens = _text_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


def _max_template_similarity(question_text: Any) -> float:
    text = str(question_text or "")
    if not text.strip():
        return 1.0
    return max((_template_similarity(text, skeleton) for skeleton in GENERIC_QDT_SKELETONS), default=0.0)


def _leaf_semantic_text(leaf: dict[str, Any]) -> str:
    values = [
        leaf.get("question_text"),
        leaf.get("leaf_question"),
        leaf.get("research_factor"),
        " ".join(str(item) for item in leaf.get("market_component_terms") or []),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _leaf_looks_like_terminal_verification(leaf: dict[str, Any]) -> bool:
    if leaf.get("leaf_temporal_role") == "terminal_verification":
        return True
    text = _leaf_semantic_text(leaf)
    return any(re.search(pattern, text) for pattern in TERMINAL_RESULT_VERIFICATION_PATTERNS)


def _result_verification_leaf_ids(leaves: list[dict[str, Any]]) -> list[str]:
    return [
        str(leaf.get("leaf_id"))
        for leaf in leaves
        if leaf.get("leaf_id") and _leaf_looks_like_terminal_verification(leaf)
    ]


def _question_looks_negative(question: Any) -> bool:
    text = " " + str(question or "").lower() + " "
    return bool(
        re.search(r"\b(no one|none|not|without|won't|will not|no qualifying|absence of)\b", text)
    )


def _ambiguous_terms_from_question(question: Any) -> list[dict[str, str]]:
    text = str(question or "")
    terms: list[dict[str, str]] = []
    for term in ("above actor", "announced", "no one", "qualifying announcement"):
        if term in text.lower():
            terms.append(
                {
                    "term": term,
                    "resolution_question": f"Clarify how '{term}' is defined by the market contract.",
                }
            )
    return terms


def _coverage_dimension_for_leaf(leaf: dict[str, Any]) -> str:
    explicit = leaf.get("coverage_dimension")
    if explicit in ALLOWED_COVERAGE_DIMENSIONS:
        return str(explicit)
    text = " ".join(
        str(value or "")
        for value in (
            leaf.get("question_text"),
            leaf.get("leaf_question"),
            leaf.get("research_factor"),
            " ".join(leaf.get("market_component_terms") or []),
        )
    ).lower()
    purpose = leaf.get("purpose")
    if any(term in text for term in ("rumor", "quality", "source class", "claim family", "syndicat")):
        return "source_quality"
    if any(term in text for term in ("timing", "deadline", "cutoff", "window", "time remaining")):
        return "timing_deadline_constraints"
    if any(term in text for term in ("negative", "contradict", "blocker", "not imminent", "unresolved")):
        return "counterevidence_negative_checks"
    if any(term in text for term in ("driver", "stage", "process", "readiness", "commitment", "negotiation")):
        return "key_drivers"
    if any(term in text for term in ("unknown", "unanswered", "missing", "structural")):
        return "material_unknowns"
    if purpose in {"resolution_mechanics", "source_of_truth"}:
        return "resolution_mechanics"
    if purpose in {"base_rate", "market_pricing"}:
        return "related_market_or_base_rate_context"
    if purpose in {"catalyst", "structural"}:
        return "key_drivers"
    return "current_direct_evidence"


def _research_factor_for_leaf(leaf: dict[str, Any]) -> str:
    explicit = leaf.get("research_factor")
    if _is_non_empty_string(explicit):
        return str(explicit)
    dimension = _coverage_dimension_for_leaf(leaf)
    terms = leaf.get("market_component_terms") if isinstance(leaf.get("market_component_terms"), list) else []
    term = _token_slug(" ".join(str(item) for item in terms), fallback=str(leaf.get("purpose") or dimension))
    return f"{dimension}:{term}".replace(" ", "_")


def _default_expected_answer_type(leaf: dict[str, Any]) -> str:
    fields = leaf.get("required_evidence_fields")
    if isinstance(fields, list) and fields:
        return "classified_values:" + ",".join(str(field) for field in fields[:4])
    return "classification_with_extracted_values"


def _default_leaf_specificity_evidence(leaf: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    terms = [str(item) for item in leaf.get("market_component_terms") or [] if _is_non_empty_string(item)]
    macro_question = str(handoff.get("macro_question") or "")
    return {
        "market_rule_clause_refs": list(leaf.get("market_rule_clause_refs") or []),
        "case_contract_field_refs": [
            "macro_question",
            "market_context.market_id",
            "source_cutoff_timestamp",
        ],
        "why_this_must_be_investigated": leaf.get("purpose_detail")
        or f"Required to classify {leaf.get('leaf_id')} for the market-specific question: {macro_question[:160]}",
        "not_a_template_reason": leaf.get("not_a_template_reason")
        or "Instantiated with market terms: " + (", ".join(terms[:6]) if terms else _token_slug(macro_question)),
        "expected_answer_type": leaf.get("expected_answer_type") or _default_expected_answer_type(leaf),
    }


def _default_evidence_requirements(leaf: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = leaf.get("evidence_requirements")
    if isinstance(requirements, list) and requirements:
        return copy.deepcopy(requirements)
    sufficiency = leaf.get("research_sufficiency_requirements")
    source_classes = []
    if isinstance(sufficiency, dict):
        source_classes = list(sufficiency.get("required_source_classes") or [])
    return [
        {
            "required_evidence_field": str(field),
            "required_source_classes": source_classes,
            "pre_cutoff_required": True,
        }
        for field in (leaf.get("required_evidence_fields") or [])
    ] or [{"required_evidence_field": "classified_status", "pre_cutoff_required": True}]


def _default_classification_targets(leaf: dict[str, Any]) -> list[str]:
    targets = leaf.get("classification_targets")
    if isinstance(targets, list) and all(_is_non_empty_string(item) for item in targets):
        return list(targets)
    fields = [str(field) for field in leaf.get("required_evidence_fields") or [] if _is_non_empty_string(field)]
    base = ["evidence_direction", "evidence_strength", "confidence", "evidence_quality", "missingness_status"]
    return sorted(set(base + fields))


def _default_sufficiency_criteria(leaf: dict[str, Any]) -> dict[str, Any]:
    criteria = leaf.get("sufficiency_criteria")
    if isinstance(criteria, dict) and criteria:
        return copy.deepcopy(criteria)
    requirements = leaf.get("research_sufficiency_requirements")
    if not isinstance(requirements, dict):
        return {"classification_dispatch_requires_sufficiency_certificate": True}
    return {
        "required_source_classes": list(requirements.get("required_source_classes") or []),
        "required_value_fields": list(requirements.get("required_value_fields") or []),
        "required_negative_checks": list(requirements.get("required_negative_checks") or []),
        "min_independent_claim_families": requirements.get("min_independent_claim_families"),
        "min_independent_source_families": requirements.get("min_independent_source_families"),
        "unanswerability_allowed": bool(requirements.get("unanswerability_proof_required")),
        "classification_dispatch_requires_sufficiency_certificate": True,
    }


def _leaf_research_priority(leaf: dict[str, Any]) -> str:
    explicit = leaf.get("research_priority")
    if explicit in ALLOWED_RESEARCH_PRIORITIES:
        return str(explicit)
    legacy = leaf.get("bayesian_weighting")
    if isinstance(legacy, dict):
        for key in ("research_priority", "static_information_weight"):
            value = legacy.get(key)
            if value in ALLOWED_RESEARCH_PRIORITIES:
                return str(value)
    return "medium"


def _market_temporal_state_from_handoff(handoff: dict[str, Any]) -> str:
    market_context = handoff.get("market_context") if isinstance(handoff.get("market_context"), dict) else {}
    raw_status = str(
        handoff.get("market_temporal_state")
        or handoff.get("resolution_status")
        or market_context.get("market_temporal_state")
        or market_context.get("resolution_status")
        or ""
    ).lower()
    if any(term in raw_status for term in ("resolved", "settled", "closed_final", "finalized")):
        return "resolved_or_settlement_audit"
    return "unresolved"


def _leaf_temporal_role(leaf: dict[str, Any]) -> str:
    explicit = leaf.get("leaf_temporal_role")
    if explicit in ALLOWED_LEAF_TEMPORAL_ROLES:
        return str(explicit)
    dimension = _coverage_dimension_for_leaf(leaf)
    purpose = leaf.get("purpose")
    if dimension == "material_unknowns":
        return "material_unknown"
    if dimension == "resolution_mechanics":
        return "resolution_mechanics"
    if dimension == "current_direct_evidence":
        return "current_status"
    if purpose == "source_of_truth":
        return "resolution_mechanics"
    return "pre_resolution_forecast_driver"


def _enrich_leaf_research_contract(leaf: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(leaf)
    enriched["research_priority"] = _leaf_research_priority(enriched)
    enriched.pop("bayesian_weighting", None)
    enriched["coverage_dimension"] = _coverage_dimension_for_leaf(enriched)
    enriched["leaf_temporal_role"] = _leaf_temporal_role(enriched)
    enriched["research_factor"] = _research_factor_for_leaf(enriched)
    enriched["leaf_question"] = str(enriched.get("leaf_question") or enriched.get("question_text") or "")
    enriched["evidence_requirements"] = _default_evidence_requirements(enriched)
    enriched["classification_targets"] = _default_classification_targets(enriched)
    enriched["sufficiency_criteria"] = _default_sufficiency_criteria(enriched)
    enriched["specificity_evidence"] = _default_leaf_specificity_evidence(enriched, handoff)
    if not isinstance(enriched.get("overlap_risk_with_leaf_ids"), list):
        enriched["overlap_risk_with_leaf_ids"] = []
    enriched["missingness_interpretation"] = str(
        enriched.get("missingness_interpretation")
        or "unanswered_material_question_or_structural_unanswerability_candidate"
    )
    forbidden = set(enriched.get("forbidden_outputs") or [])
    enriched["forbidden_outputs"] = sorted(forbidden | FORBIDDEN_LEAF_OUTPUTS)
    return enriched


def _build_market_resolution_contract(handoff: dict[str, Any]) -> dict[str, Any]:
    question = str(handoff.get("macro_question") or "the market question")
    negative = _question_looks_negative(question)
    market_context = handoff.get("market_context") if isinstance(handoff.get("market_context"), dict) else {}
    return {
        "yes_no_mapping": {
            "yes_means": (
                "The market's YES side means the negative or absence condition remains true at resolution."
                if negative
                else "The market's YES side means the target event occurs under the market rules."
            ),
            "no_means": (
                "The market's NO side means a qualifying contrary event occurred under the market rules."
                if negative
                else "The market's NO side means the target event does not occur under the market rules."
            ),
            "mapping_confidence": "requires_case_contract_confirmation",
        },
        "resolution_subject": question,
        "resolution_authority": market_context.get("resolution_authority") or "market_rules_or_platform_resolution_source",
        "contract_deadline": market_context.get("resolves_at") or market_context.get("closes_at"),
        "forecast_cutoff": handoff.get("source_cutoff_timestamp") or handoff.get("forecast_timestamp"),
        "platform_family_context": market_context.get("platform_family_context") or "unknown_not_promoted",
        "ambiguous_terms": _ambiguous_terms_from_question(question),
        "disqualifying_evidence_types": [
            "rumor_only",
            "unsupported_social_media_claim",
            "post_cutoff_source_fact",
            "market_price_only",
        ],
        "source_hierarchy": [
            "official_or_primary_resolution_source",
            "market_rules_or_resolution_source",
            "independent_secondary_confirmation",
        ],
    }


def _build_research_coverage_graph(handoff: dict[str, Any], leaves: list[dict[str, Any]]) -> dict[str, Any]:
    by_dimension: dict[str, list[str]] = {}
    research_factors: list[dict[str, str]] = []
    guard_leaf_ids: list[str] = []
    material_leaf_ids: list[str] = []
    terminal_verification_leaf_ids: list[str] = []
    dispatchable_pre_resolution_leaf_ids: list[str] = []
    market_temporal_state = _market_temporal_state_from_handoff(handoff)
    for leaf in leaves:
        leaf_id = str(leaf.get("leaf_id") or "")
        dimension = str(leaf.get("coverage_dimension") or _coverage_dimension_for_leaf(leaf))
        temporal_role = str(leaf.get("leaf_temporal_role") or _leaf_temporal_role(leaf))
        by_dimension.setdefault(dimension, []).append(leaf_id)
        research_factors.append(
            {
                "leaf_id": leaf_id,
                "coverage_dimension": dimension,
                "research_factor": str(leaf.get("research_factor") or _research_factor_for_leaf(leaf)),
                "leaf_temporal_role": temporal_role,
            }
        )
        if temporal_role == "terminal_verification":
            terminal_verification_leaf_ids.append(leaf_id)
        if market_temporal_state != "unresolved" or temporal_role != "terminal_verification":
            dispatchable_pre_resolution_leaf_ids.append(leaf_id)
        if dimension in CONTRACT_GUARD_COVERAGE_DIMENSIONS and leaf.get("purpose") in {
            "source_of_truth",
            "resolution_mechanics",
        }:
            guard_leaf_ids.append(leaf_id)
        else:
            material_leaf_ids.append(leaf_id)
    missing = sorted(REQUIRED_CORE_COVERAGE_DIMENSIONS - set(by_dimension))
    unanswered = [
        {
            "coverage_dimension": dimension,
            "question": f"No leaf currently covers required dimension {dimension}.",
            "status": "requires_decomposer_repair",
        }
        for dimension in missing
    ]
    return {
        "target_event_description": str(handoff.get("macro_question") or ""),
        "forecast_research_objective": (
            "Classify pre-resolution evidence, drivers, blockers, source quality, timing constraints, "
            "and material unknowns before SCAE estimates the market outcome."
        ),
        "market_temporal_state": market_temporal_state,
        "coverage_dimensions": sorted(by_dimension),
        "research_factors": research_factors,
        "contract_guard_leaf_ids": guard_leaf_ids,
        "material_question_leaf_ids": material_leaf_ids,
        "terminal_verification_leaf_ids": terminal_verification_leaf_ids,
        "dispatchable_pre_resolution_leaf_ids": dispatchable_pre_resolution_leaf_ids,
        "required_leaf_ids_by_dimension": {key: sorted(value) for key, value in sorted(by_dimension.items())},
        "overlap_groups": [],
        "unanswered_material_questions": unanswered,
        "coverage_summary": {
            "status": "requires_repair" if unanswered else "coverage_ready",
            "material_leaf_count": len(material_leaf_ids),
            "contract_guard_leaf_count": len(guard_leaf_ids),
            "coverage_dimension_count": len(by_dimension),
            "authority": "research_coverage_only_no_forecast_authority",
        },
    }


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
    research_priority: str,
    condition_scope: str,
    required_value_fields: list[str] | None = None,
    required_negative_checks: list[str] | None = None,
) -> dict[str, Any]:
    return _build_research_sufficiency_requirements(
        purpose=purpose,
        research_priority=research_priority,
        condition_scope=condition_scope,
        required_value_fields=required_value_fields,
        required_negative_checks=required_negative_checks,
    )


def _model_execution_context_from_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    model_context = handoff.get("model_execution_context")
    if not isinstance(model_context, dict):
        raise QDTError("handoff missing model_execution_context")
    return copy.deepcopy(model_context)


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
        priority = _leaf_research_priority(leaf)
        leaf["research_priority"] = priority
        leaf.pop("bayesian_weighting", None)
        if "research_sufficiency_requirements" not in leaf:
            leaf["research_sufficiency_requirements"] = build_research_sufficiency_requirements(
                purpose=leaf.get("purpose", "other"),
                research_priority=priority,
                condition_scope=leaf.get("leaf_condition_scope", "unconditional"),
                required_value_fields=leaf.get("required_evidence_fields")
                if isinstance(leaf.get("required_evidence_fields"), list)
                else None,
            )
    leaves = [_enrich_leaf_research_contract(leaf, handoff) for leaf in leaves]
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
        "market_resolution_contract": _build_market_resolution_contract(handoff),
        "research_coverage_graph": _build_research_coverage_graph(handoff, leaves),
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
            "question_text": "What market rule, platform resolver, or primary authority defines the exact YES/NO outcome for this market?",
            "purpose": "source_of_truth",
            "coverage_dimension": "resolution_mechanics",
            "research_factor": "resolution_condition_and_authority",
            "research_priority": "critical",
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["official_status", "resolution_criteria"],
            "market_component_terms": ["resolution", "official source"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": "leaf-direct-evidence",
            "parent_branch_id": "branch-resolution",
            "question_text": "What direct pre-cutoff evidence shows whether the target event is currently observed, contradicted, or unresolved?",
            "purpose": "direct_evidence",
            "coverage_dimension": "current_direct_evidence",
            "research_factor": "current_target_event_status",
            "research_priority": "high",
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["event_status", "event_timestamp"],
            "market_component_terms": ["event", "cutoff"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": "leaf-key-driver-status",
            "parent_branch_id": "branch-resolution",
            "question_text": "Which market-specific drivers or process milestones would make the target event materially more or less observable before cutoff?",
            "purpose": "catalyst",
            "coverage_dimension": "key_drivers",
            "research_factor": "process_stage_and_driver_status",
            "research_priority": "high",
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["driver_status", "process_stage"],
            "market_component_terms": ["driver", "process stage", "milestone"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": "leaf-negative-checks",
            "parent_branch_id": "branch-resolution",
            "question_text": "What negative checks, blockers, or contradictory signals show the target event has not cleanly occurred before cutoff?",
            "purpose": "direct_evidence",
            "coverage_dimension": "counterevidence_negative_checks",
            "research_factor": "counterevidence_and_blockers",
            "research_priority": "high",
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["negative_check_status", "contradiction_status"],
            "market_component_terms": ["negative check", "blocker", "contradiction"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": "leaf-source-quality",
            "parent_branch_id": "branch-resolution",
            "question_text": "Are the relevant claim families independent high-quality reports, official statements, or repeated low-quality rumors that should be collapsed?",
            "purpose": "direct_evidence",
            "coverage_dimension": "source_quality",
            "research_factor": "claim_family_independence_and_source_quality",
            "research_priority": "medium",
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["source_quality", "claim_family_independence"],
            "market_component_terms": ["claim family", "source quality", "rumor"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": "leaf-timing-constraints",
            "parent_branch_id": "branch-mechanics",
            "question_text": "Which deadline, cutoff, and observation-window constraints determine whether evidence can count for this market?",
            "purpose": "resolution_mechanics",
            "coverage_dimension": "timing_deadline_constraints",
            "research_factor": "deadline_and_cutoff_admissibility",
            "research_priority": "medium",
            "leaf_dependency_group_id": "dep-group-mechanics",
            "leaf_condition_scope": "shared_context",
            "required_evidence_fields": ["resolution_deadline", "cutoff_window"],
            "market_component_terms": ["deadline", "cutoff", "observation window"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": "leaf-material-unknowns",
            "parent_branch_id": "branch-resolution",
            "question_text": "What material questions remain unanswered after retrieval, and are they answerable through more source discovery or structurally unavailable before cutoff?",
            "purpose": "structural",
            "coverage_dimension": "material_unknowns",
            "research_factor": "unanswered_material_questions",
            "research_priority": "medium",
            "leaf_dependency_group_id": "dep-group-resolution",
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["unanswered_question_status", "answerability_status"],
            "market_component_terms": ["material unknown", "answerability", "retrieval gap"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
    ]
    branches = [
        {
            "branch_id": "branch-resolution",
            "branch_question": "Define the market-specific research coverage needed to classify the target outcome before cutoff.",
            "branch_role": "research_coverage",
            "dependency_group_id": "dep-group-resolution",
            "required_evidence_purposes": ["catalyst", "direct_evidence", "source_of_truth", "structural"],
            "leaf_ids": [
                "leaf-source-of-truth",
                "leaf-direct-evidence",
                "leaf-key-driver-status",
                "leaf-negative-checks",
                "leaf-source-quality",
                "leaf-material-unknowns",
            ],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1},
        }
    ]
    if include_resolution_leaf:
        leaves.append(
            {
                "leaf_id": "leaf-resolution-mechanics",
                "parent_branch_id": "branch-mechanics",
                "question_text": "Which market rules and source hierarchy distinguish a qualifying resolution claim from rumor, weak context, or post-cutoff evidence?",
                "purpose": "resolution_mechanics",
                "coverage_dimension": "resolution_mechanics",
                "research_factor": "source_hierarchy_and_qualifying_claim",
                "research_priority": "medium",
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
                "branch_question": "Clarify contract mechanics, deadlines, and source hierarchy that constrain admissible evidence.",
                "branch_role": "resolution_mechanics",
                "dependency_group_id": "dep-group-mechanics",
                "required_evidence_purposes": ["resolution_mechanics"],
                "leaf_ids": ["leaf-timing-constraints", "leaf-resolution-mechanics"],
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
    if requirements.get("sufficiency_profile_id") != SUFFICIENCY_PROFILE_ID:
        errors.append(f"{path}.sufficiency_profile_id must be {SUFFICIENCY_PROFILE_ID}")
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
    priority = leaf.get("research_priority")
    critical_or_source = (
        leaf.get("purpose") == "source_of_truth"
        or priority == "critical"
    )
    if critical_or_source and not (
        requirements.get("protected_primary_required") or requirements.get("unanswerability_proof_required")
    ):
        errors.append(f"{path} critical/source-of-truth leaves require protected primary or unanswerability proof")
    if critical_or_source and requirements.get("allow_macro_fallback_for_leaf") is True:
        errors.append(f"{path} critical/source-of-truth leaves cannot allow macro fallback as sufficient research")
    if priority in ALLOWED_RESEARCH_PRIORITIES:
        required_evidence_fields = leaf.get("required_evidence_fields")
        template_errors = validate_research_sufficiency_requirements(
            requirements,
            purpose=str(leaf.get("purpose")),
            research_priority=str(priority),
            condition_scope=str(leaf.get("leaf_condition_scope")),
            required_evidence_fields=list(required_evidence_fields)
            if _string_list(required_evidence_fields)
            else [],
        )
        for error in template_errors:
            errors.append(f"{path}.{error}")


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


def _validate_specificity_evidence(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path}.specificity_evidence must be an object")
        return
    for field in (
        "market_rule_clause_refs",
        "case_contract_field_refs",
        "why_this_must_be_investigated",
        "not_a_template_reason",
        "expected_answer_type",
    ):
        if field not in value:
            errors.append(f"{path}.specificity_evidence missing {field}")
    for list_field in ("market_rule_clause_refs", "case_contract_field_refs"):
        if not isinstance(value.get(list_field), list):
            errors.append(f"{path}.specificity_evidence.{list_field} must be a list")
    for text_field in (
        "why_this_must_be_investigated",
        "not_a_template_reason",
        "expected_answer_type",
    ):
        if not _is_non_empty_string(value.get(text_field)):
            errors.append(f"{path}.specificity_evidence.{text_field} is required")


def _validate_leaf_research_contract(leaf: dict[str, Any], path: str, errors: list[str]) -> None:
    if leaf.get("leaf_temporal_role") not in ALLOWED_LEAF_TEMPORAL_ROLES:
        errors.append(f"{path}.leaf_temporal_role is invalid")
    dimension = leaf.get("coverage_dimension")
    if dimension not in ALLOWED_COVERAGE_DIMENSIONS:
        errors.append(f"{path}.coverage_dimension is invalid")
    if not _is_non_empty_string(leaf.get("research_factor")):
        errors.append(f"{path}.research_factor is required")
    if not _is_non_empty_string(leaf.get("leaf_question")):
        errors.append(f"{path}.leaf_question is required")
    elif leaf.get("question_text") and str(leaf["leaf_question"]).strip() != str(leaf["question_text"]).strip():
        errors.append(f"{path}.leaf_question must match question_text")
    if not isinstance(leaf.get("evidence_requirements"), list) or not leaf.get("evidence_requirements"):
        errors.append(f"{path}.evidence_requirements must be non-empty")
    if not _string_list(leaf.get("classification_targets")):
        errors.append(f"{path}.classification_targets must be a string list")
    if not isinstance(leaf.get("sufficiency_criteria"), dict) or not leaf.get("sufficiency_criteria"):
        errors.append(f"{path}.sufficiency_criteria must be a non-empty object")
    _validate_specificity_evidence(leaf.get("specificity_evidence"), path, errors)
    overlap = leaf.get("overlap_risk_with_leaf_ids")
    if not isinstance(overlap, list):
        errors.append(f"{path}.overlap_risk_with_leaf_ids must be a list")
    if not _is_non_empty_string(leaf.get("missingness_interpretation")):
        errors.append(f"{path}.missingness_interpretation is required")
    forbidden = leaf.get("forbidden_outputs")
    if not _string_list(forbidden):
        errors.append(f"{path}.forbidden_outputs must be a string list")
    else:
        missing = FORBIDDEN_LEAF_OUTPUTS - set(str(item) for item in forbidden)
        if missing:
            errors.append(f"{path}.forbidden_outputs missing " + ", ".join(sorted(missing)))
    similarity = _max_template_similarity(str(leaf.get("leaf_question") or leaf.get("question_text") or ""))
    if similarity > 0.82:
        errors.append(f"{path}:template_mad_lib_leaf")


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
        if leaf.get("research_priority") not in ALLOWED_RESEARCH_PRIORITIES:
            errors.append(f"{path}.research_priority is invalid")
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
        _validate_leaf_research_contract(leaf, path, errors)

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


def _validate_market_resolution_contract(value: Any, artifact: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("market_resolution_contract must be an object")
        return
    for field in REQUIRED_MARKET_RESOLUTION_CONTRACT_FIELDS:
        if field not in value:
            errors.append(f"market_resolution_contract missing {field}")
    mapping = value.get("yes_no_mapping")
    if not isinstance(mapping, dict):
        errors.append("market_resolution_contract.yes_no_mapping must be an object")
    else:
        for field in ("yes_means", "no_means", "mapping_confidence"):
            if not _is_non_empty_string(mapping.get(field)):
                errors.append(f"market_resolution_contract.yes_no_mapping.{field} is required")
    for field in ("resolution_subject", "resolution_authority", "platform_family_context"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"market_resolution_contract.{field} is required")
    if not isinstance(value.get("ambiguous_terms"), list):
        errors.append("market_resolution_contract.ambiguous_terms must be a list")
    elif _ambiguous_terms_from_question(artifact.get("macro_question")) and not value.get("ambiguous_terms"):
        errors.append("ambiguous_terms_not_decomposed")
    if not _string_list(value.get("disqualifying_evidence_types")):
        errors.append("market_resolution_contract.disqualifying_evidence_types must be a string list")
    if not _string_list(value.get("source_hierarchy")):
        errors.append("market_resolution_contract.source_hierarchy must be a string list")
    if _question_looks_negative(artifact.get("macro_question")):
        joined = canonical_json(mapping or {}).lower()
        if not any(term in joined for term in ("absence", "negative", "no qualifying", "contrary")):
            errors.append("negative_market_mapping_not_decomposed")


def _evidence_packet_suggests_market_family(evidence_packet: dict[str, Any] | None) -> bool:
    if not isinstance(evidence_packet, dict):
        return False
    family = evidence_packet.get("family_context")
    if isinstance(family, dict):
        for field in ("family_id", "parent_market_id", "sibling_market_ids", "child_market_ids"):
            value = family.get(field)
            if value:
                return True
    identity = evidence_packet.get("market_identity")
    if isinstance(identity, dict):
        return bool(identity.get("parent_market_id") or identity.get("event_id") or identity.get("group_id"))
    return False


def _unanswered_dimensions(value: dict[str, Any]) -> set[str]:
    unanswered = value.get("unanswered_material_questions")
    dimensions: set[str] = set()
    if isinstance(unanswered, list):
        for item in unanswered:
            if isinstance(item, dict) and item.get("coverage_dimension") in ALLOWED_COVERAGE_DIMENSIONS:
                dimensions.add(str(item["coverage_dimension"]))
    return dimensions


def _minimum_material_leaf_count(leaf_budget_decision: Any) -> int:
    budget = None
    if isinstance(leaf_budget_decision, dict) and isinstance(leaf_budget_decision.get("effective_leaf_budget"), int):
        budget = int(leaf_budget_decision["effective_leaf_budget"])
    budget = budget or COMPACT_DEFAULT_LEAF_BUDGET
    return min(5, max(2, budget // 2))


def _validate_overlap_groups(
    graph: dict[str, Any],
    leaves_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    overlap_groups = graph.get("overlap_groups")
    grouped_pairs: set[tuple[str, str]] = set()
    if isinstance(overlap_groups, list):
        for idx, group in enumerate(overlap_groups):
            if not isinstance(group, dict):
                errors.append(f"research_coverage_graph.overlap_groups[{idx}] must be an object")
                continue
            ids = group.get("leaf_ids")
            if not isinstance(ids, list) or len(ids) < 2:
                errors.append(f"research_coverage_graph.overlap_groups[{idx}].leaf_ids must contain at least two leaves")
                continue
            for left in ids:
                for right in ids:
                    if left != right:
                        grouped_pairs.add(tuple(sorted((str(left), str(right)))))
    questions = {
        leaf_id: str(leaf.get("leaf_question") or leaf.get("question_text") or "")
        for leaf_id, leaf in leaves_by_id.items()
    }
    ids = list(questions)
    for idx, left in enumerate(ids):
        for right in ids[idx + 1 :]:
            if _template_similarity(questions[left], questions[right]) > 0.86:
                if tuple(sorted((left, right))) not in grouped_pairs:
                    errors.append("overlapping_leaf_questions_not_deduplicated")
                    return


def _validate_unresolved_forecast_semantics(
    graph: dict[str, Any],
    leaves_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    if graph.get("market_temporal_state") != "unresolved":
        return
    dispatchable_ids = [
        str(item)
        for item in graph.get("dispatchable_pre_resolution_leaf_ids") or []
        if str(item) in leaves_by_id
    ]
    dispatchable_leaves = [leaves_by_id[leaf_id] for leaf_id in dispatchable_ids]
    if not dispatchable_leaves:
        errors.append("missing_pre_resolution_dispatchable_leaves")
        return

    result_verification_ids = _result_verification_leaf_ids(dispatchable_leaves)
    misclassified_ids = sorted(
        str(leaf.get("leaf_id"))
        for leaf in dispatchable_leaves
        if leaf.get("leaf_id")
        and leaf.get("leaf_temporal_role") != "terminal_verification"
        and _leaf_looks_like_terminal_verification(leaf)
    )
    if misclassified_ids:
        errors.append(
            "terminal_verification_leaf_misclassified_as_pre_resolution: "
            + ", ".join(misclassified_ids)
        )

    terminal_ratio = len(result_verification_ids) / max(1, len(dispatchable_leaves))
    if result_verification_ids and terminal_ratio >= TERMINAL_VERIFICATION_DOMINATION_THRESHOLD:
        errors.append(
            "terminal_verification_dominates_unresolved_forecast_qdt: "
            + ", ".join(sorted(result_verification_ids))
        )

    dispatchable_dimensions = {
        str(leaf.get("coverage_dimension"))
        for leaf in dispatchable_leaves
        if leaf.get("coverage_dimension") in ALLOWED_COVERAGE_DIMENSIONS
    }
    missing_dimensions = (
        UNRESOLVED_PRE_RESOLUTION_FORECAST_DIMENSIONS
        - dispatchable_dimensions
        - _unanswered_dimensions(graph)
    )
    if missing_dimensions:
        errors.append("missing_pre_resolution_forecast_dimensions: " + ", ".join(sorted(missing_dimensions)))


def _validate_research_coverage_graph(
    value: Any,
    artifact: dict[str, Any],
    leaves_by_id: dict[str, dict[str, Any]],
    evidence_packet: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append("research_coverage_graph must be an object")
        return
    for field in REQUIRED_RESEARCH_COVERAGE_GRAPH_FIELDS:
        if field not in value:
            errors.append(f"research_coverage_graph missing {field}")
    if not _is_non_empty_string(value.get("target_event_description")):
        errors.append("research_coverage_graph.target_event_description is required")
    if not _is_non_empty_string(value.get("forecast_research_objective")):
        errors.append("research_coverage_graph.forecast_research_objective is required")
    market_temporal_state = value.get("market_temporal_state")
    if market_temporal_state not in ALLOWED_MARKET_TEMPORAL_STATES:
        errors.append("research_coverage_graph.market_temporal_state is invalid")
    coverage_dimensions = value.get("coverage_dimensions")
    if not isinstance(coverage_dimensions, list) or not coverage_dimensions:
        errors.append("research_coverage_graph.coverage_dimensions must be non-empty")
        coverage_set: set[str] = set()
    else:
        coverage_set = {str(item) for item in coverage_dimensions}
        unknown = sorted(coverage_set - ALLOWED_COVERAGE_DIMENSIONS)
        if unknown:
            errors.append("research_coverage_graph.coverage_dimensions contains unknown dimensions")
    by_dimension = value.get("required_leaf_ids_by_dimension")
    leaf_ids = set(leaves_by_id)
    if not isinstance(by_dimension, dict) or not by_dimension:
        errors.append("research_coverage_graph.required_leaf_ids_by_dimension must be non-empty")
        by_dimension = {}
    for dimension, ids in by_dimension.items():
        if dimension not in ALLOWED_COVERAGE_DIMENSIONS:
            errors.append(f"research_coverage_graph.required_leaf_ids_by_dimension.{dimension} is invalid")
        if not isinstance(ids, list) or not ids:
            errors.append(f"research_coverage_graph.required_leaf_ids_by_dimension.{dimension} must be non-empty")
            continue
        unknown_ids = sorted(str(item) for item in ids if str(item) not in leaf_ids)
        if unknown_ids:
            errors.append(f"research_coverage_graph.required_leaf_ids_by_dimension.{dimension} references unknown leaves")
    for list_field in (
        "contract_guard_leaf_ids",
        "material_question_leaf_ids",
        "terminal_verification_leaf_ids",
        "dispatchable_pre_resolution_leaf_ids",
    ):
        ids = value.get(list_field)
        if not isinstance(ids, list):
            errors.append(f"research_coverage_graph.{list_field} must be a list")
        else:
            unknown_ids = sorted(str(item) for item in ids if str(item) not in leaf_ids)
            if unknown_ids:
                errors.append(f"research_coverage_graph.{list_field} references unknown leaves")
    guard = set(str(item) for item in value.get("contract_guard_leaf_ids") or [])
    material = set(str(item) for item in value.get("material_question_leaf_ids") or [])
    terminal = set(str(item) for item in value.get("terminal_verification_leaf_ids") or [])
    dispatchable = set(str(item) for item in value.get("dispatchable_pre_resolution_leaf_ids") or [])
    if guard & material:
        errors.append("research_coverage_graph guard and material leaf ids must be disjoint")
    for leaf_id in terminal:
        leaf = leaves_by_id.get(leaf_id)
        if leaf and leaf.get("leaf_temporal_role") != "terminal_verification":
            errors.append("research_coverage_graph.terminal_verification_leaf_ids references non-terminal leaf")
    if market_temporal_state == "unresolved":
        terminal_dispatch = sorted(terminal & dispatchable)
        if terminal_dispatch:
            errors.append(
                "research_coverage_graph.dispatchable_pre_resolution_leaf_ids contains terminal verification leaves: "
                + ", ".join(terminal_dispatch)
            )
    if len(material) < _minimum_material_leaf_count(artifact.get("leaf_budget_decision")):
        errors.append("insufficient_material_leaf_count")
    if guard and len(guard) >= len(material):
        errors.append("resolution_checklist_dominates_research_coverage")
    missing_dimensions = REQUIRED_CORE_COVERAGE_DIMENSIONS - set(by_dimension)
    missing_unanswered = missing_dimensions - _unanswered_dimensions(value)
    if missing_unanswered:
        errors.append("required_coverage_dimension_missing: " + ", ".join(sorted(missing_unanswered)))
    for leaf_id, leaf in leaves_by_id.items():
        dimension = leaf.get("coverage_dimension")
        if dimension in ALLOWED_COVERAGE_DIMENSIONS:
            ids = by_dimension.get(dimension, [])
            if isinstance(ids, list) and leaf_id not in ids:
                errors.append(f"research_coverage_graph.required_leaf_ids_by_dimension omits {leaf_id}")
        if leaf.get("leaf_temporal_role") == "terminal_verification" and leaf_id not in terminal:
            errors.append("research_coverage_graph.terminal_verification_leaf_ids omits terminal verification leaf")
    if _evidence_packet_suggests_market_family(evidence_packet):
        contract = artifact.get("market_resolution_contract")
        context = contract.get("platform_family_context") if isinstance(contract, dict) else None
        if not _is_non_empty_string(context) or context == "unknown_not_promoted":
            errors.append("market_family_context_not_analyzed")
    _validate_unresolved_forecast_semantics(value, leaves_by_id, errors)
    _validate_overlap_groups(value, leaves_by_id, errors)


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
    _validate_market_resolution_contract(artifact.get("market_resolution_contract"), artifact, errors)
    _validate_research_coverage_graph(
        artifact.get("research_coverage_graph"),
        artifact,
        leaves_by_id,
        evidence_packet,
        errors,
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


def _amrg_context_edges_by_id(related_market_context: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(related_market_context, dict):
        return {}
    edges = related_market_context.get("relationship_edges")
    if not isinstance(edges, list):
        return {}
    return {
        str(edge["edge_id"]): edge
        for edge in edges
        if isinstance(edge, dict) and _is_non_empty_string(edge.get("edge_id"))
    }


def _amrg_context_hint_refs(related_market_context: Any) -> set[str]:
    refs: set[str] = set(_amrg_context_edges_by_id(related_market_context))
    if isinstance(related_market_context, dict):
        section = related_market_context.get("amrg_decomposer_context")
        hints = section.get("hints") if isinstance(section, dict) else None
        if isinstance(hints, list):
            for hint in hints:
                if isinstance(hint, dict) and _is_non_empty_string(hint.get("hint_ref")):
                    refs.add(str(hint["hint_ref"]))
    return refs


def _artifact_amrg_usage_refs(artifact: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    usage = artifact.get("related_market_context_usage")
    if isinstance(usage, dict) and isinstance(usage.get("amrg_usage_refs"), list):
        refs.update(str(ref) for ref in usage["amrg_usage_refs"] if _is_non_empty_string(ref))
    for branch in artifact.get("branches") or []:
        if isinstance(branch, dict) and isinstance(branch.get("amrg_usage_refs"), list):
            refs.update(str(ref) for ref in branch["amrg_usage_refs"] if _is_non_empty_string(ref))
    for leaf in artifact.get("required_leaf_questions") or []:
        if isinstance(leaf, dict) and isinstance(leaf.get("amrg_usage_refs"), list):
            refs.update(str(ref) for ref in leaf["amrg_usage_refs"] if _is_non_empty_string(ref))
    return refs


def validate_question_decomposition_against_amrg_context(
    artifact: dict[str, Any],
    related_market_context: dict[str, Any] | None,
) -> QDTValidationResult:
    """Validate QDT AMRG refs against the actual related-market context."""

    base = validate_question_decomposition(artifact)
    errors = list(base.errors)
    if related_market_context is None:
        return QDTValidationResult(not errors, tuple(errors), base.warnings)

    hint_refs = _amrg_context_hint_refs(related_market_context)
    usage_refs = _artifact_amrg_usage_refs(artifact)
    unknown_usage_refs = sorted(ref for ref in usage_refs if ref not in hint_refs)
    if unknown_usage_refs:
        errors.append("amrg_usage_refs reference unknown AMRG hints: " + ", ".join(unknown_usage_refs))

    context_type = related_market_context.get("artifact_type") if isinstance(related_market_context, dict) else None
    contracts = artifact.get("amrg_anchor_dependency_contracts")
    if contracts and context_type == "no_related_context_waiver":
        errors.append("amrg_anchor_dependency_contracts cannot be used with no-related-context waiver")
    edges_by_id = _amrg_context_edges_by_id(related_market_context)
    if isinstance(contracts, list):
        for idx, contract in enumerate(contracts):
            if not isinstance(contract, dict):
                continue
            anchor_mode = contract.get("anchor_mode")
            if anchor_mode not in ANCHOR_MODES_SATISFYING_CONDITION_SCOPE:
                continue
            edge_id = str(contract.get("edge_id") or "")
            edge = edges_by_id.get(edge_id)
            path = f"amrg_anchor_dependency_contracts[{idx}]"
            if edge is None:
                errors.append(f"{path}.edge_id references unknown AMRG context edge")
                continue
            actual_status = edge.get("relationship_status") or edge.get("status")
            if actual_status not in STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES:
                errors.append(f"{path}.edge_id is not a strict-precedence AMRG edge")
            if contract.get("edge_status") != actual_status:
                errors.append(f"{path}.edge_status does not match AMRG context edge status")
            allowed_effects = edge.get("allowed_effects")
            if isinstance(allowed_effects, list) and "qdt_anchor_dependency_hint" not in allowed_effects:
                errors.append(f"{path}.edge_id is not allowed as a QDT anchor dependency hint")
    return QDTValidationResult(not errors, tuple(errors), base.warnings)


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


def compute_qdt_quality_checks(
    artifact: dict[str, Any],
    *,
    evidence_packet: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    validation = validate_question_decomposition(
        artifact,
        require_selected=artifact.get("candidate_selection_audit", {}).get("selection_status") == "selected",
        evidence_packet=evidence_packet,
    )
    leaf_ids = {
        str(leaf.get("leaf_id"))
        for leaf in artifact.get("required_leaf_questions", [])
        if isinstance(leaf, dict) and leaf.get("leaf_id")
    }
    graph = artifact.get("research_coverage_graph") if isinstance(artifact.get("research_coverage_graph"), dict) else {}
    dimensions = graph.get("coverage_dimensions") if isinstance(graph.get("coverage_dimensions"), list) else []
    template_like = []
    for leaf in artifact.get("required_leaf_questions", []):
        if not isinstance(leaf, dict):
            continue
        similarity = _max_template_similarity(str(leaf.get("leaf_question") or leaf.get("question_text") or ""))
        if similarity > 0.82:
            template_like.append({"leaf_id": leaf.get("leaf_id"), "similarity": round(similarity, 3)})
    coverage_errors = [
        error
        for error in validation.errors
        if any(
            marker in error
            for marker in (
                "research_coverage_graph",
                "coverage_dimension",
                "template_mad_lib_leaf",
                "insufficient_material_leaf_count",
                "resolution_checklist_dominates_research_coverage",
                "required_coverage_dimension_missing",
                "overlapping_leaf_questions_not_deduplicated",
                "missing_pre_resolution_dispatchable_leaves",
                "missing_pre_resolution_forecast_dimensions",
                "terminal_verification_leaf_misclassified_as_pre_resolution",
                "terminal_verification_dominates_unresolved_forecast_qdt",
                "classification_targets",
                "evidence_requirements",
                "specificity_evidence",
            )
        )
    ]
    question_errors = [
        error
        for error in validation.errors
        if any(
            marker in error
            for marker in (
                "template_mad_lib_leaf",
                "negative_market_mapping_not_decomposed",
                "ambiguous_terms_not_decomposed",
                "market_family_context_not_analyzed",
                "terminal_verification_leaf_misclassified_as_pre_resolution",
                "terminal_verification_dominates_unresolved_forecast_qdt",
                "specificity_evidence",
                "leaf_question",
            )
        )
    ]
    question_status = "failed" if question_errors or template_like else "passed"
    coverage_status = "failed" if coverage_errors else "passed"
    return {
        "question_specificity_check": {
            "status": question_status,
            "macro_question_sha256": _prefixed_sha256(artifact.get("macro_question", "")),
            "generic_fixture_leaf_ids_absent": not {
                "leaf-source-of-truth",
                "leaf-direct-evidence",
                "leaf-resolution-mechanics",
            }.intersection(leaf_ids),
            "template_like_leaf_count": len(template_like),
            "template_like_leaf_refs": template_like,
            "reason_codes": ["semantic_specificity_passed"] if question_status == "passed" else question_errors,
        },
        "research_coverage_check": {
            "status": coverage_status,
            "coverage_dimensions": list(dimensions),
            "material_leaf_count": len(graph.get("material_question_leaf_ids") or []),
            "contract_guard_leaf_count": len(graph.get("contract_guard_leaf_ids") or []),
            "reason_codes": ["research_coverage_graph_valid"] if coverage_status == "passed" else coverage_errors,
        },
    }


def _leaf_has_verified_findings_ledger_mapping(leaf: dict[str, Any]) -> bool:
    return (
        _string_list(leaf.get("classification_targets"))
        and isinstance(leaf.get("evidence_requirements"), list)
        and bool(leaf.get("evidence_requirements"))
        and isinstance(leaf.get("sufficiency_criteria"), dict)
        and bool(leaf.get("sufficiency_criteria"))
        and _is_non_empty_string(leaf.get("missingness_interpretation"))
    )


def _leaf_market_specificity_points(leaf: dict[str, Any], macro_tokens: set[str]) -> float:
    question_tokens = _text_tokens(leaf.get("leaf_question") or leaf.get("question_text") or "")
    term_tokens = _text_tokens(" ".join(str(item) for item in leaf.get("market_component_terms") or []))
    matched_macro_tokens = len((question_tokens | term_tokens) & macro_tokens)
    non_generic_terms = len(
        term_tokens
        - {
            "event",
            "market",
            "target",
            "cutoff",
            "deadline",
            "official",
            "resolution",
            "status",
            "source",
            "evidence",
        }
    )
    return min(3.0, matched_macro_tokens * 0.8 + non_generic_terms * 0.4)


def _artifact_leaf_amrg_refs(candidate: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for branch in candidate.get("branches") or []:
        if isinstance(branch, dict) and isinstance(branch.get("amrg_usage_refs"), list):
            refs.update(str(ref) for ref in branch["amrg_usage_refs"] if _is_non_empty_string(ref))
    for leaf in candidate.get("required_leaf_questions") or []:
        if isinstance(leaf, dict) and isinstance(leaf.get("amrg_usage_refs"), list):
            refs.update(str(ref) for ref in leaf["amrg_usage_refs"] if _is_non_empty_string(ref))
    return refs


def _strict_anchor_refs(candidate: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for contract in candidate.get("amrg_anchor_dependency_contracts") or []:
        if not isinstance(contract, dict):
            continue
        if (
            contract.get("anchor_mode") in ANCHOR_MODES_SATISFYING_CONDITION_SCOPE
            and contract.get("edge_status") in STRICT_PRECEDENCE_ANCHOR_EDGE_STATUSES
            and _is_non_empty_string(contract.get("edge_id"))
        ):
            refs.add(str(contract["edge_id"]))
    return refs


def _score_qdt_candidate_details(candidate: dict[str, Any]) -> dict[str, Any]:
    leaves = candidate.get("required_leaf_questions", [])
    if not isinstance(leaves, list):
        return {
            "score": -1.0,
            "reason_codes": ["invalid_leaf_collection"],
            "score_components": {"invalid_leaf_collection": -1.0},
            "penalty_components": {},
            "diagnostics": {},
        }
    graph = (
        candidate.get("research_coverage_graph")
        if isinstance(candidate.get("research_coverage_graph"), dict)
        else {}
    )
    checks = compute_qdt_quality_checks(candidate)
    failed_checks = []
    for check_name in ("question_specificity_check", "research_coverage_check"):
        check = checks.get(check_name, {})
        if check.get("status") != "passed":
            failed_checks.extend(str(code) for code in check.get("reason_codes") or [])

    macro_tokens = _text_tokens(candidate.get("macro_question"))
    purposes = {leaf.get("purpose") for leaf in leaves if isinstance(leaf, dict)}
    dimensions = {
        leaf.get("coverage_dimension")
        for leaf in leaves
        if isinstance(leaf, dict) and leaf.get("coverage_dimension") in ALLOWED_COVERAGE_DIMENSIONS
    }
    by_dimension = (
        graph.get("required_leaf_ids_by_dimension")
        if isinstance(graph.get("required_leaf_ids_by_dimension"), dict)
        else {}
    )
    dispatchable_ids = {
        str(item)
        for item in graph.get("dispatchable_pre_resolution_leaf_ids") or []
        if _is_non_empty_string(item)
    }
    terminal_ids = {
        str(item)
        for item in graph.get("terminal_verification_leaf_ids") or []
        if _is_non_empty_string(item)
    }
    dispatchable_leaves = [
        leaf
        for leaf in leaves
        if isinstance(leaf, dict) and str(leaf.get("leaf_id")) in dispatchable_ids
    ]
    material_ids = {
        str(item)
        for item in graph.get("material_question_leaf_ids") or []
        if _is_non_empty_string(item)
    }
    non_terminal_material_count = len(material_ids - terminal_ids)
    guard_count = len(graph.get("contract_guard_leaf_ids") or [])
    unique_research_factors = {
        str(leaf.get("research_factor"))
        for leaf in leaves
        if isinstance(leaf, dict) and _is_non_empty_string(leaf.get("research_factor"))
    }
    verified_mapping_count = sum(
        1
        for leaf in leaves
        if isinstance(leaf, dict) and _leaf_has_verified_findings_ledger_mapping(leaf)
    )
    specificity_points = sum(
        _leaf_market_specificity_points(leaf, macro_tokens)
        for leaf in leaves
        if isinstance(leaf, dict)
    )
    pre_resolution_dimensions = {
        str(leaf.get("coverage_dimension"))
        for leaf in dispatchable_leaves
        if leaf.get("coverage_dimension") in UNRESOLVED_PRE_RESOLUTION_FORECAST_DIMENSIONS
    }
    pre_resolution_roles = {
        str(leaf.get("leaf_temporal_role"))
        for leaf in dispatchable_leaves
        if leaf.get("leaf_temporal_role") in {
            "pre_resolution_forecast_driver",
            "current_status",
            "material_unknown",
            "resolution_mechanics",
        }
    }
    material_unknown_leaf_count = sum(
        1
        for leaf in leaves
        if isinstance(leaf, dict)
        and leaf.get("coverage_dimension") == "material_unknowns"
        and _is_non_empty_string(leaf.get("missingness_interpretation"))
    )
    template_like_count = sum(
        1
        for leaf in leaves
        if isinstance(leaf, dict)
        and _max_template_similarity(str(leaf.get("leaf_question") or leaf.get("question_text") or "")) > 0.82
    )
    result_verification_count = len(_result_verification_leaf_ids(dispatchable_leaves))
    unsupported_amrg_refs = sorted(_artifact_leaf_amrg_refs(candidate) - _strict_anchor_refs(candidate))
    strict_anchor_count = len(_strict_anchor_refs(candidate))
    overlap_groups = graph.get("overlap_groups") if isinstance(graph.get("overlap_groups"), list) else []
    leaf_count = len(leaves)
    budget = candidate.get("leaf_budget_decision", {}).get("effective_leaf_budget", leaf_count)
    compact_overage = max(0, leaf_count - int(budget if isinstance(budget, int) else leaf_count))
    duplicate_factor_count = max(0, leaf_count - len(unique_research_factors))
    terminal_dispatch_count = len(terminal_ids & dispatchable_ids)

    score_components = {
        "coverage_diversity": len(dimensions) * 9.0,
        "required_core_dimension_coverage": len(set(by_dimension) & REQUIRED_CORE_COVERAGE_DIMENSIONS) * 4.0,
        "purpose_coverage": len(purposes) * 5.0,
        "material_research_factor_coverage": (
            non_terminal_material_count * 4.0 + len(unique_research_factors) * 2.0
        ),
        "market_specificity": specificity_points,
        "verified_findings_ledger_mapping": verified_mapping_count * 3.0,
        "missingness_clarity": material_unknown_leaf_count * 6.0,
        "pre_resolution_forecast_driver_coverage": (
            len(pre_resolution_dimensions) * 8.0 + len(pre_resolution_roles) * 2.0
        ),
        "terminal_verification_segregation": 6.0 if not terminal_dispatch_count else 0.0,
        "overlap_clarity": len(overlap_groups) * 2.0,
        "validated_amrg_strict_anchor_usage": strict_anchor_count * 5.0,
    }
    penalty_components = {
        "template_similarity": template_like_count * 12.0,
        "resolution_checklist_domination": 16.0
        if guard_count and guard_count >= non_terminal_material_count
        else 0.0,
        "result_verification_domination": result_verification_count * 18.0,
        "terminal_verification_overhead": len(terminal_ids) * 14.0
        if graph.get("market_temporal_state") == "unresolved"
        else 0.0,
        "terminal_verification_dispatch": terminal_dispatch_count * 30.0,
        "unsupported_amrg_refs": len(unsupported_amrg_refs) * 18.0,
        "excess_leaf_count": compact_overage * 8.0,
        "duplicate_research_factors": duplicate_factor_count * 3.0,
        "failed_quality_checks": 1000.0 if failed_checks else 0.0,
    }
    score = sum(score_components.values()) - sum(penalty_components.values())
    reason_codes = [
        code
        for code, value in score_components.items()
        if value > 0
    ] + [
        f"penalty_{code}"
        for code, value in penalty_components.items()
        if value > 0
    ]
    if failed_checks:
        reason_codes.append("quality_checks_failed")
    return {
        "score": float(score),
        "reason_codes": reason_codes or ["candidate_scored_neutral"],
        "score_components": score_components,
        "penalty_components": penalty_components,
        "diagnostics": {
            "coverage_dimensions": sorted(str(item) for item in dimensions),
            "dispatchable_pre_resolution_leaf_count": len(dispatchable_leaves),
            "terminal_verification_leaf_count": len(terminal_ids),
            "result_verification_dispatchable_leaf_count": result_verification_count,
            "unsupported_amrg_refs": unsupported_amrg_refs,
            "failed_quality_reason_codes": failed_checks,
        },
    }


def score_qdt_candidate(candidate: dict[str, Any]) -> float:
    return _score_qdt_candidate_details(candidate)["score"]


def select_qdt_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(candidates, list) or not candidates:
        raise QDTError("at least one QDT candidate is required")
    accepted: list[tuple[float, int, dict[str, Any], dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        candidate_id = candidate.get("candidate_id") if isinstance(candidate, dict) else None
        if not _is_non_empty_string(candidate_id):
            candidate_id = f"qdt-candidate-{idx + 1:03d}"
        result = validate_question_decomposition(candidate, require_selected=False)
        if result.valid:
            score_details = _score_qdt_candidate_details(candidate)
            accepted.append((float(score_details["score"]), idx, candidate, score_details))
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
    score, _idx, selected, selected_score_details = sorted(
        accepted,
        key=lambda item: (-item[0], str(item[2].get("candidate_id", "")), item[1]),
    )[0]
    selected_id = str(selected["candidate_id"])
    scored_candidates = []
    for candidate_score, idx, candidate, details in sorted(
        accepted,
        key=lambda item: (-item[0], str(item[2].get("candidate_id", "")), item[1]),
    ):
        candidate_id = str(candidate.get("candidate_id") or f"qdt-candidate-{idx + 1:03d}")
        scored_candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_score": candidate_score,
                "selection_status": "selected" if candidate_id == selected_id else "not_selected",
                "reason_codes": list(details["reason_codes"]),
                "score_components": copy.deepcopy(details["score_components"]),
                "penalty_components": copy.deepcopy(details["penalty_components"]),
                "diagnostics": copy.deepcopy(details["diagnostics"]),
            }
        )
    selected = copy.deepcopy(selected)
    selected["candidate_selection_audit"] = {
        "selection_status": "selected",
        "candidate_count": len(candidates),
        "selected_candidate_id": selected_id,
        "selected_candidate_score": score,
        "rejected_candidates": rejected,
        "scored_candidates": scored_candidates,
        "selected_score_components": copy.deepcopy(selected_score_details["score_components"]),
        "selected_penalty_components": copy.deepcopy(selected_score_details["penalty_components"]),
        "selected_reason_codes": [
            "highest_qdt_research_coverage_score",
            *list(selected_score_details["reason_codes"]),
        ][:12],
        "selection_helper_version": QDT_SELECTION_HELPER_VERSION,
    }
    selected["validation_summary"] = {
        "status": "valid",
        "validator_version": QDT_SCHEMA_VALIDATOR_VERSION,
        "reason_codes": [
            "question_decomposition_schema_valid",
            "depth_2_branch_leaf_contract_present",
            "deterministic_structural_validation_passed",
            "research_coverage_graph_valid",
            "semantic_specificity_check_passed",
            "research_sufficiency_requirement_fields_present",
            "model_provenance_fields_present",
            "forbidden_output_check_passed",
        ],
        "forbidden_output_check_status": "passed",
    }
    require_valid_question_decomposition(selected)
    selected.update(compute_qdt_quality_checks(selected))
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
