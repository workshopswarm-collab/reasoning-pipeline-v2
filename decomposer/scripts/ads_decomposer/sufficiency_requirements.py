"""Canonical per-leaf research sufficiency requirement template helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION = "qdt-research-sufficiency-requirements/v1"
RESEARCH_SUFFICIENCY_TEMPLATE_VERSION = "high-certainty-research-sufficiency-template/v1"
SUFFICIENCY_PROFILE_ID = "high-certainty-default/v1"
TARGET_ANSWERABILITY = "high_confidence_or_structurally_unanswerable"
RETRIEVAL_BREADTH_PROFILE_PREFIX = "breadth-profile-template"
RECENCY_WINDOW_SECONDS = 259200
MAX_TARGETED_EXPANSION_ATTEMPTS = 3
MAX_REASON_CODE_LENGTH = 80

REQUIRED_SUFFICIENCY_FIELDS = (
    "schema_version",
    "template_version",
    "requirement_id",
    "leaf_purpose",
    "research_priority",
    "leaf_condition_scope",
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
    "requirement_reason_codes",
)

FRESHNESS_PURPOSES = {"direct_evidence", "source_of_truth", "catalyst", "market_pricing"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_non_empty_string(item) for item in value)


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _reason_codes_are_compact(value: Any) -> bool:
    return isinstance(value, list) and all(
        _is_non_empty_string(item) and len(item) <= MAX_REASON_CODE_LENGTH and " " not in item
        for item in value
    )


def _dedupe(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        if _is_non_empty_string(value) and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def source_classes_for_purpose(purpose: str) -> list[str]:
    if purpose == "market_pricing":
        return ["market_or_exchange", "independent_secondary"]
    if purpose in {"source_of_truth", "resolution_mechanics"}:
        return ["official_or_primary", "independent_secondary"]
    if purpose == "catalyst":
        return ["official_or_primary", "independent_secondary", "expert_or_specialist"]
    return ["official_or_primary", "independent_secondary"]


def negative_checks_for_purpose(purpose: str) -> list[str]:
    if purpose == "market_pricing":
        return ["stale_price_check", "cross_venue_conflict_check"]
    if purpose in {"source_of_truth", "resolution_mechanics"}:
        return ["resolution_rule_conflict_check", "contradiction_search"]
    if purpose in {"direct_evidence", "catalyst"}:
        return ["post_cutoff_evidence_check", "contradiction_search"]
    return ["contradiction_search"]


def retrieval_breadth_profile_ref(
    *,
    purpose: str,
    research_priority: str,
    condition_scope: str,
) -> str:
    return f"{RETRIEVAL_BREADTH_PROFILE_PREFIX}:{purpose}:{research_priority}:{condition_scope}"


def requirement_id_for_leaf(
    *,
    purpose: str,
    research_priority: str,
    condition_scope: str,
    required_value_fields: list[str],
    required_negative_checks: list[str],
) -> str:
    digest = hashlib.sha256(
        _canonical_json(
            {
                "purpose": purpose,
                "research_priority": research_priority,
                "condition_scope": condition_scope,
                "required_value_fields": required_value_fields,
                "required_negative_checks": required_negative_checks,
                "template_version": RESEARCH_SUFFICIENCY_TEMPLATE_VERSION,
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"qdt-sufficiency:{digest[:24]}"


def build_research_sufficiency_requirements(
    *,
    purpose: str,
    research_priority: str,
    condition_scope: str,
    required_value_fields: list[str] | None = None,
    required_negative_checks: list[str] | None = None,
) -> dict[str, Any]:
    """Build the canonical QDT high-certainty sufficiency requirement block."""

    value_fields = _dedupe(required_value_fields)
    negative_checks = _dedupe(required_negative_checks) or negative_checks_for_purpose(purpose)
    critical_or_source = research_priority == "critical" or purpose == "source_of_truth"
    family_minimum = 2 if research_priority in {"critical", "high"} else 1
    fresh_sources = 1 if purpose in FRESHNESS_PURPOSES else 0
    return {
        "schema_version": RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION,
        "template_version": RESEARCH_SUFFICIENCY_TEMPLATE_VERSION,
        "requirement_id": requirement_id_for_leaf(
            purpose=purpose,
            research_priority=research_priority,
            condition_scope=condition_scope,
            required_value_fields=value_fields,
            required_negative_checks=negative_checks,
        ),
        "leaf_purpose": purpose,
        "research_priority": research_priority,
        "leaf_condition_scope": condition_scope,
        "sufficiency_profile_id": SUFFICIENCY_PROFILE_ID,
        "target_answerability": TARGET_ANSWERABILITY,
        "retrieval_breadth_profile_ref": retrieval_breadth_profile_ref(
            purpose=purpose,
            research_priority=research_priority,
            condition_scope=condition_scope,
        ),
        "required_source_classes": source_classes_for_purpose(purpose),
        "protected_primary_required": purpose == "source_of_truth",
        "min_independent_claim_families": family_minimum,
        "min_independent_source_families": family_minimum,
        "min_temporally_fresh_sources": fresh_sources,
        "required_value_fields": value_fields,
        "required_negative_checks": negative_checks,
        "contradiction_search_required": True,
        "recency_window_seconds": RECENCY_WINDOW_SECONDS,
        "max_targeted_expansion_attempts": MAX_TARGETED_EXPANSION_ATTEMPTS,
        "allow_macro_fallback_for_leaf": False,
        "unanswerability_proof_required": critical_or_source,
        "classification_dispatch_requires_sufficiency_certificate": True,
        "requirement_reason_codes": [
            "high_certainty_template",
            f"purpose_{purpose}",
            f"priority_{research_priority}",
            f"scope_{condition_scope}",
        ],
    }


def validate_research_sufficiency_requirements(
    requirements: Any,
    *,
    purpose: str,
    research_priority: str,
    condition_scope: str,
    required_evidence_fields: list[str],
) -> list[str]:
    """Return deterministic validation errors for a per-leaf requirement block."""

    if not isinstance(requirements, dict):
        return ["research_sufficiency_requirements must be an object"]

    errors: list[str] = []
    for field in REQUIRED_SUFFICIENCY_FIELDS:
        if field not in requirements:
            errors.append(f"research_sufficiency_requirements missing {field}")

    if requirements.get("schema_version") != RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RESEARCH_SUFFICIENCY_REQUIREMENTS_SCHEMA_VERSION}")
    if requirements.get("template_version") != RESEARCH_SUFFICIENCY_TEMPLATE_VERSION:
        errors.append(f"template_version must be {RESEARCH_SUFFICIENCY_TEMPLATE_VERSION}")
    if requirements.get("sufficiency_profile_id") != SUFFICIENCY_PROFILE_ID:
        errors.append(f"sufficiency_profile_id must be {SUFFICIENCY_PROFILE_ID}")
    if requirements.get("target_answerability") != TARGET_ANSWERABILITY:
        errors.append(f"target_answerability must be {TARGET_ANSWERABILITY}")

    if requirements.get("leaf_purpose") != purpose:
        errors.append("leaf_purpose must match leaf purpose")
    if requirements.get("research_priority") != research_priority:
        errors.append("research_priority must match leaf priority")
    if requirements.get("leaf_condition_scope") != condition_scope:
        errors.append("leaf_condition_scope must match leaf condition scope")

    expected_breadth_ref = retrieval_breadth_profile_ref(
        purpose=purpose,
        research_priority=research_priority,
        condition_scope=condition_scope,
    )
    if requirements.get("retrieval_breadth_profile_ref") != expected_breadth_ref:
        errors.append("retrieval_breadth_profile_ref must match canonical leaf template")

    expected_source_classes = source_classes_for_purpose(purpose)
    if requirements.get("required_source_classes") != expected_source_classes:
        errors.append("required_source_classes must match canonical purpose template")

    expected_family_minimum = 2 if research_priority in {"critical", "high"} else 1
    if requirements.get("min_independent_claim_families") != expected_family_minimum:
        errors.append("min_independent_claim_families must match research priority")
    if requirements.get("min_independent_source_families") != expected_family_minimum:
        errors.append("min_independent_source_families must match research priority")

    expected_fresh_sources = 1 if purpose in FRESHNESS_PURPOSES else 0
    if requirements.get("min_temporally_fresh_sources") != expected_fresh_sources:
        errors.append("min_temporally_fresh_sources must match leaf purpose")
    if requirements.get("protected_primary_required") != (purpose == "source_of_truth"):
        errors.append("protected_primary_required must match leaf purpose")

    required_value_fields = requirements.get("required_value_fields")
    if not _string_list(required_value_fields):
        errors.append("required_value_fields must be a string list")
        required_value_fields = []
    missing_values = sorted(set(required_evidence_fields) - set(required_value_fields))
    if missing_values:
        errors.append("required_value_fields must include leaf required_evidence_fields: " + ", ".join(missing_values))

    negative_checks = requirements.get("required_negative_checks")
    if not _string_list(negative_checks) or not negative_checks:
        errors.append("required_negative_checks must be a non-empty string list")
        negative_checks = []

    if requirements.get("contradiction_search_required") is not True:
        errors.append("contradiction_search_required must be true")
    if requirements.get("classification_dispatch_requires_sufficiency_certificate") is not True:
        errors.append("classification_dispatch_requires_sufficiency_certificate must be true")
    if requirements.get("allow_macro_fallback_for_leaf") is not False:
        errors.append("allow_macro_fallback_for_leaf must be false")

    critical_or_source = research_priority == "critical" or purpose == "source_of_truth"
    if requirements.get("unanswerability_proof_required") != critical_or_source:
        errors.append("unanswerability_proof_required must match critical/source-of-truth policy")

    if not _positive_int(requirements.get("recency_window_seconds")):
        errors.append("recency_window_seconds must be a positive integer")
    if not _positive_int(requirements.get("max_targeted_expansion_attempts")):
        errors.append("max_targeted_expansion_attempts must be a positive integer")

    reason_codes = requirements.get("requirement_reason_codes")
    expected_reason_codes = {
        "high_certainty_template",
        f"purpose_{purpose}",
        f"priority_{research_priority}",
        f"scope_{condition_scope}",
    }
    if not _reason_codes_are_compact(reason_codes):
        errors.append("requirement_reason_codes must be compact reason codes")
    elif not expected_reason_codes.issubset(set(reason_codes)):
        errors.append("requirement_reason_codes must include template, purpose, priority, and scope codes")

    if _string_list(required_value_fields) and _string_list(negative_checks):
        expected_requirement_id = requirement_id_for_leaf(
            purpose=purpose,
            research_priority=research_priority,
            condition_scope=condition_scope,
            required_value_fields=list(required_value_fields),
            required_negative_checks=list(negative_checks),
        )
        if requirements.get("requirement_id") != expected_requirement_id:
            errors.append("requirement_id must match canonical leaf sufficiency template")
    elif not _is_non_empty_string(requirements.get("requirement_id")):
        errors.append("requirement_id is required")

    for int_field in (
        "min_independent_claim_families",
        "min_independent_source_families",
        "min_temporally_fresh_sources",
        "recency_window_seconds",
        "max_targeted_expansion_attempts",
    ):
        if not _non_negative_int(requirements.get(int_field)):
            errors.append(f"{int_field} must be a non-negative integer")

    return errors
