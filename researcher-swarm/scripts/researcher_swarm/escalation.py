"""CLS-007 adaptive researcher escalation decision helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .assignments import (
    build_leaf_research_assignment,
    validate_leaf_research_assignment,
)


RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION = "researcher-escalation-decision/v1"
RESEARCHER_ESCALATION_DECISION_ARTIFACT_TYPE = "researcher_escalation_decision"
CLS_007_ESCALATION_BUILDER_VERSION = "ads-cls-007-researcher-escalation/v1"

MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE = 5
MAX_ASSIGNMENTS_PER_LEAF = 3
DEFAULT_ADDITIONAL_ASSIGNMENTS = 1

ESCALATION_TRIGGER_CODES = (
    "critical_source_of_truth_leaf",
    "evidence_conflict",
    "low_retrieval_confidence",
    "low_classification_confidence",
    "high_scae_leverage_proxy",
    "structural_unanswerability_claimed",
)
ALLOWED_TRIGGER_CODES = set(ESCALATION_TRIGGER_CODES)
ALLOWED_LEVERAGE_BUCKETS = {"low", "medium", "high"}
ALLOWED_COMPLETION_STATUSES = {
    "not_required",
    "required_pending",
    "required_complete",
    "cap_reached",
    "blocked",
}
ALLOWED_ASSIGNMENT_STATUSES = {
    "planned_not_spawned",
    "delivered",
    "already_active",
    "completed",
    "blocked_by_cap",
}

HIGH_RETRIEVAL_QUALITY_STATUSES = {"high", "usable"}
LOW_RETRIEVAL_QUALITY_STATUSES = {"low", "thin", "blocked"}
LOW_CLASSIFICATION_CONFIDENCE_VALUES = {"low", "unknown"}

FORBIDDEN_ESCALATION_FIELD_NAMES = {
    "own_probability",
    "leaf_probability",
    "researcher_reassembled_probability",
    "researcher_macro_probability",
    "macro_probability",
    "final_macro_probability",
    "forecast_probability",
    "production_probability",
    "probability",
    "probability_estimate",
    "probability_yes",
    "probability_no",
    "probability_interval",
    "prob",
    "p_yes",
    "p_no",
    "replacement_probability",
    "replacement_forecast",
    "replacement_decision",
    "fair_value",
    "fair_value_low",
    "fair_value_mid",
    "fair_value_high",
    "interval",
    "odds",
    "log_odds",
    "scae_delta",
    "scae_probability_delta",
    "decision_recommendation",
    "decision_output",
    "trade_recommendation",
}
FORBIDDEN_ESCALATION_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "replacement",
    "log_odds",
    "scae_delta",
)
ALLOWED_PROBABILITY_GUARD_FIELDS = {"probability_fields_forbidden"}
FORBIDDEN_EMBEDDED_PAYLOAD_FIELDS = {
    "full_leaf",
    "leaf_blob",
    "qdt_leaf",
    "required_leaf_questions",
    "research_sufficiency_requirements",
    "evidence_body",
    "evidence_text",
    "full_text",
    "document_text",
    "raw_text",
    "html",
    "markdown",
    "article_body",
    "content",
    "canonical_url",
    "requested_url",
    "final_url",
    "body",
    "transcript",
    "research_report",
    "narrative_report",
}


class ResearcherEscalationError(ValueError):
    """Raised when a CLS-007 escalation artifact cannot be built or validated."""


@dataclass(frozen=True)
class ResearcherEscalationValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_007_ESCALATION_BUILDER_VERSION,
        }


@dataclass(frozen=True)
class ResearcherEscalationEvaluationResult:
    decision: dict[str, Any]
    escalation_assignments: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": copy.deepcopy(self.decision),
            "escalation_assignments": copy.deepcopy(self.escalation_assignments),
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 24) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256_ref(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    text = str(value)
    return text.startswith("sha256:") and len(text) == 71 and all(ch in "0123456789abcdef" for ch in text[7:])


def _normalized_field_name(value: Any) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(item)]


def _unique_strings(*values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        raw_items = value if isinstance(value, list) else [value]
        for item in raw_items:
            if not _is_non_empty_string(item):
                continue
            text = str(item)
            if text not in seen:
                seen.add(text)
                result.append(text)
    return result


def _ordered_triggers(values: list[str]) -> list[str]:
    present = {value for value in values if value in ALLOWED_TRIGGER_CODES}
    return [code for code in ESCALATION_TRIGGER_CODES if code in present]


def _decision_ref(decision_id: str) -> str:
    return f"researcher-escalation-decision:{decision_id}"


def _assignment_artifact_ref(assignment_id: str) -> str:
    return f"artifact:leaf-research-assignment/{assignment_id}"


def _leaf_id(leaf: dict[str, Any], certificate: dict[str, Any], base_assignment: dict[str, Any]) -> str:
    for candidate in (leaf.get("leaf_id"), certificate.get("leaf_id"), base_assignment.get("leaf_id")):
        if _is_non_empty_string(candidate):
            return str(candidate)
    raise ResearcherEscalationError("leaf_id is required")


def _requirements_from_leaf(leaf: dict[str, Any]) -> dict[str, Any]:
    requirements = leaf.get("research_sufficiency_requirements")
    return requirements if isinstance(requirements, dict) else {}


def _static_information_weight(leaf: dict[str, Any]) -> str:
    if _is_non_empty_string(leaf.get("research_priority")):
        return str(leaf["research_priority"])
    weighting = leaf.get("bayesian_weighting")
    if isinstance(weighting, dict) and _is_non_empty_string(weighting.get("research_priority")):
        return str(weighting["research_priority"])
    if isinstance(weighting, dict) and _is_non_empty_string(weighting.get("static_information_weight")):
        return str(weighting["static_information_weight"])
    requirements = _requirements_from_leaf(leaf)
    if _is_non_empty_string(requirements.get("research_priority")):
        return str(requirements["research_priority"])
    if _is_non_empty_string(requirements.get("static_information_weight")):
        return str(requirements["static_information_weight"])
    return "medium"


def _condition_scope(leaf: dict[str, Any], base_assignment: dict[str, Any] | None = None) -> str:
    for candidate in (
        leaf.get("leaf_condition_scope"),
        leaf.get("condition_scope"),
        (base_assignment or {}).get("condition_scope"),
    ):
        if _is_non_empty_string(candidate):
            return str(candidate)
    return "unconditional"


def _is_critical_or_source_of_truth(leaf: dict[str, Any]) -> bool:
    requirements = _requirements_from_leaf(leaf)
    criticality_values = {
        str(leaf.get("criticality") or "").lower(),
        str(leaf.get("source_role") or "").lower(),
        str(leaf.get("required_source_role") or "").lower(),
        str(leaf.get("purpose") or "").lower(),
        str(_static_information_weight(leaf)).lower(),
    }
    return (
        leaf.get("is_critical") is True
        or leaf.get("is_source_of_truth") is True
        or leaf.get("source_of_truth") is True
        or requirements.get("protected_primary_required") is True
        or "critical" in criticality_values
        or "source_of_truth" in criticality_values
        or "critical_source_of_truth" in criticality_values
    )


def _classification_slices_from(value: Any, leaf_id: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw = value.get("classification_slices") or value.get("required_question_classifications")
    else:
        raw = value
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ResearcherEscalationError("classifications must be a list or matrix object")
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and (not _is_non_empty_string(item.get("leaf_id")) or str(item.get("leaf_id")) == leaf_id)
    ]


def _direction_slices_from(value: Any, leaf_id: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw = value.get("direction_verification_slices") or value.get("verification_slices")
    else:
        raw = value
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ResearcherEscalationError("direction_slices must be a list or bundle object")
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and (not _is_non_empty_string(item.get("leaf_id")) or str(item.get("leaf_id")) == leaf_id)
    ]


def _quality_slices_from(value: Any, leaf_id: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw = value.get("quality_verification_slices") or value.get("verification_slices")
    else:
        raw = value
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ResearcherEscalationError("quality_slices must be a list or bundle object")
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and (not _is_non_empty_string(item.get("leaf_id")) or str(item.get("leaf_id")) == leaf_id)
    ]


def _retrieval_quality_slice_from(value: Any, leaf_id: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("retrieval_quality_slices"), list):
        for item in value["retrieval_quality_slices"]:
            if isinstance(item, dict) and str(item.get("leaf_id")) == leaf_id:
                return item
        return None
    if str(value.get("leaf_id")) == leaf_id or "quality_status" in value or "quality_score" in value:
        return value
    return None


def _refs_from_dicts(items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for item in items:
        for field in fields:
            value = item.get(field)
            if _is_non_empty_string(value):
                refs.append(str(value))
    return _unique_strings(refs)


def _classification_ids(classifications: list[dict[str, Any]]) -> list[str]:
    return _refs_from_dicts(classifications, ("classification_id", "slice_id"))


def _verification_refs(
    direction_slices: list[dict[str, Any]],
    quality_slices: list[dict[str, Any]],
) -> list[str]:
    return _refs_from_dicts(
        direction_slices + quality_slices,
        (
            "verification_slice_id",
            "quality_verification_slice_id",
            "slice_id",
        ),
    )


def _trigger_evidence_refs(
    certificate: dict[str, Any],
    classifications: list[dict[str, Any]],
    retrieval_quality_slice: dict[str, Any] | None,
) -> list[str]:
    refs = _unique_strings(certificate.get("evidence_refs"))
    refs.extend(_refs_from_dicts(classifications, ("evidence_ref", "provenance_ref")))
    if isinstance(retrieval_quality_slice, dict):
        refs.extend(_string_list(retrieval_quality_slice.get("selected_evidence_refs")))
    return _unique_strings(refs)


def _has_evidence_conflict(
    classifications: list[dict[str, Any]],
    direction_slices: list[dict[str, Any]],
) -> bool:
    explicit_conflict = any(
        item.get("evidence_conflict") is True
        or item.get("conflict_status") in {"conflicting", "unresolved_conflict"}
        or _is_non_empty_string(item.get("contradiction_family_id"))
        for item in classifications
    )
    if explicit_conflict:
        return True

    directions: set[str] = set()
    for item in direction_slices:
        status = str(item.get("verification_status") or item.get("method_status") or "")
        if status == "excluded":
            continue
        direction = item.get("verified_direction") or item.get("claimed_direction")
        if direction in {"supports_yes", "supports_no"}:
            directions.add(str(direction))
    if not directions:
        for item in classifications:
            direction = item.get("impact_direction")
            if direction in {"supports_yes", "supports_no"}:
                directions.add(str(direction))
    return {"supports_yes", "supports_no"}.issubset(directions)


def _low_retrieval_confidence(
    certificate: dict[str, Any],
    retrieval_quality_slice: dict[str, Any] | None,
) -> bool:
    for field in ("retrieval_confidence_bucket", "retrieval_confidence"):
        value = certificate.get(field)
        if _is_non_empty_string(value) and str(value).lower() == "low":
            return True
    if not isinstance(retrieval_quality_slice, dict):
        return False
    status = str(retrieval_quality_slice.get("quality_status") or retrieval_quality_slice.get("retrieval_quality_status") or "").lower()
    if status in LOW_RETRIEVAL_QUALITY_STATUSES:
        return True
    score = retrieval_quality_slice.get("quality_score")
    return isinstance(score, (int, float)) and not isinstance(score, bool) and score < 0.7


def _low_classification_confidence(
    classifications: list[dict[str, Any]],
    quality_slices: list[dict[str, Any]],
) -> bool:
    for item in classifications:
        confidence = str(item.get("classification_confidence") or "").lower()
        if confidence in LOW_CLASSIFICATION_CONFIDENCE_VALUES:
            return True
    for item in quality_slices:
        candidates = []
        for field in ("accepted_quality_fields", "machine_normalized_quality_fields", "claimed_quality_fields"):
            value = item.get(field)
            if isinstance(value, dict):
                candidates.append(value.get("classification_confidence"))
        candidates.append(item.get("classification_confidence"))
        if any(str(candidate or "").lower() in LOW_CLASSIFICATION_CONFIDENCE_VALUES for candidate in candidates):
            return True
    return False


def _structural_unanswerability_claimed(certificate: dict[str, Any]) -> bool:
    status = str(certificate.get("status") or certificate.get("coverage_status") or "")
    return (
        status in {"structurally_unanswerable", "expansion_exhausted_structurally_unanswerable"}
        or _is_non_empty_string(certificate.get("structural_unanswerability_proof_ref"))
    )


def _policy_list(policy: dict[str, Any], field: str) -> set[str]:
    value = policy.get(field)
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if _is_non_empty_string(item)}


def compute_pre_scae_leverage_proxy(
    *,
    leaf: dict[str, Any],
    certificate: dict[str, Any] | None = None,
    classifications: list[dict[str, Any]] | None = None,
    quality_slices: list[dict[str, Any]] | None = None,
    retrieval_quality_slice: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    base_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a deterministic pre-SCAE leverage bucket without forecast fields."""

    certificate = certificate or {}
    classifications = classifications or []
    quality_slices = quality_slices or []
    policy = policy or {}
    leaf_id = str(leaf.get("leaf_id") or certificate.get("leaf_id") or (base_assignment or {}).get("leaf_id") or "")
    explicit_buckets = policy.get("pre_scae_leverage_bucket_by_leaf")
    if isinstance(explicit_buckets, dict) and str(explicit_buckets.get(leaf_id)) in ALLOWED_LEVERAGE_BUCKETS:
        bucket = str(explicit_buckets[leaf_id])
        return {
            "bucket": bucket,
            "input_refs": _unique_strings(leaf.get("leaf_id"), certificate.get("certificate_id")),
            "reason_codes": [f"policy_explicit_{bucket}_leverage"],
            "probability_fields_forbidden": True,
        }
    if (
        leaf_id in _policy_list(policy, "high_leverage_leaf_ids")
        or leaf_id in _policy_list(policy, "force_high_leverage_leaf_ids")
        or policy.get("force_high_leverage") is True
        or leaf.get("pre_scae_leverage_proxy_bucket") == "high"
    ):
        return {
            "bucket": "high",
            "input_refs": _unique_strings(leaf.get("leaf_id"), certificate.get("certificate_id")),
            "reason_codes": ["policy_high_leverage_leaf"],
            "probability_fields_forbidden": True,
        }

    score = 0
    reason_codes: list[str] = []
    weight = _static_information_weight(leaf)
    if weight == "critical":
        score += 3
        reason_codes.append("critical_static_information_weight")
    elif weight == "high":
        score += 2
        reason_codes.append("high_static_information_weight")
    elif weight == "medium":
        score += 1
        reason_codes.append("medium_static_information_weight")

    requirements = _requirements_from_leaf(leaf)
    if leaf.get("purpose") == "source_of_truth":
        score += 2
        reason_codes.append("source_of_truth_leaf")
    if requirements.get("protected_primary_required") is True:
        score += 1
        reason_codes.append("protected_primary_required")
    if _condition_scope(leaf, base_assignment) in {"conditional", "branch_local", "target_given_upstream", "target_given_not_upstream"}:
        score += 1
        reason_codes.append("condition_scoped_leaf")
    if _is_non_empty_string(leaf.get("dependency_group_id")):
        score += 1
        reason_codes.append("dependency_group_present")

    if any(item.get("evidence_strength") == "strong" for item in classifications):
        score += 1
        reason_codes.append("strong_classified_evidence")
    if any(
        isinstance(item.get("final_quality_multiplier"), (int, float))
        and not isinstance(item.get("final_quality_multiplier"), bool)
        and item["final_quality_multiplier"] >= 0.85
        for item in quality_slices
    ):
        score += 1
        reason_codes.append("high_verified_quality")
    if isinstance(retrieval_quality_slice, dict):
        status = str(retrieval_quality_slice.get("quality_status") or "").lower()
        if status in HIGH_RETRIEVAL_QUALITY_STATUSES:
            score += 1
            reason_codes.append("usable_or_high_retrieval_quality")
        elif status in LOW_RETRIEVAL_QUALITY_STATUSES:
            reason_codes.append("thin_or_blocked_retrieval_quality")

    cap_context = policy.get("scae_policy_cap_context")
    if cap_context in {"critical", "tight", "high"}:
        score += 1
        reason_codes.append(f"scae_policy_cap_context_{cap_context}")

    if score >= 5:
        bucket = "high"
    elif score >= 3:
        bucket = "medium"
    else:
        bucket = "low"

    input_refs = _unique_strings(
        leaf.get("leaf_id"),
        certificate.get("certificate_id"),
        [item.get("classification_id") or item.get("slice_id") for item in classifications],
        [
            item.get("quality_verification_slice_id") or item.get("verification_slice_id") or item.get("slice_id")
            for item in quality_slices
        ],
        retrieval_quality_slice.get("slice_id") if isinstance(retrieval_quality_slice, dict) else None,
        policy.get("policy_ref"),
        policy.get("effective_tuning_profile_context_ref"),
    )
    return {
        "bucket": bucket,
        "input_refs": input_refs,
        "reason_codes": sorted(set(reason_codes)) or ["default_low_leverage"],
        "probability_fields_forbidden": True,
    }


def _required_extra_assignments_for_triggers(triggers: list[str], policy: dict[str, Any]) -> int:
    if not triggers:
        return 0
    default_count = policy.get("default_additional_assignments", DEFAULT_ADDITIONAL_ASSIGNMENTS)
    if not isinstance(default_count, int) or isinstance(default_count, bool) or default_count < 0:
        default_count = DEFAULT_ADDITIONAL_ASSIGNMENTS
    confirmation_count = policy.get("independent_confirmations_required", 1)
    if not isinstance(confirmation_count, int) or isinstance(confirmation_count, bool) or confirmation_count < 1:
        confirmation_count = 1
    if {
        "critical_source_of_truth_leaf",
        "structural_unanswerability_claimed",
    }.intersection(triggers):
        return max(default_count, confirmation_count)
    return default_count


def _existing_leaf_assignment_count(
    *,
    leaf_id: str,
    base_assignment: dict[str, Any],
    existing_leaf_assignments: list[dict[str, Any]] | None,
) -> int:
    seen: set[str] = set()
    for item in [base_assignment, *(existing_leaf_assignments or [])]:
        if not isinstance(item, dict):
            continue
        if _is_non_empty_string(item.get("leaf_id")) and str(item["leaf_id"]) != leaf_id:
            continue
        identifier = item.get("assignment_id") or item.get("assignment_ref") or item.get("artifact_ref")
        if _is_non_empty_string(identifier):
            seen.add(str(identifier))
    return max(1, len(seen))


def _case_active_count(
    *,
    current_case_active_leaf_researcher_count: int | None,
    case_active_assignment_refs: list[str] | None,
) -> int:
    if isinstance(current_case_active_leaf_researcher_count, int) and not isinstance(current_case_active_leaf_researcher_count, bool):
        return max(0, current_case_active_leaf_researcher_count)
    return len(_unique_strings(case_active_assignment_refs or []))


def _assignment_plan_for_triggers(triggers: list[str]) -> tuple[str, str]:
    if "structural_unanswerability_claimed" in triggers:
        return "confirmation", "unanswerability_confirmation"
    if "critical_source_of_truth_leaf" in triggers:
        return "confirmation", "source_of_truth_check"
    if "evidence_conflict" in triggers:
        return "escalation", "conflict_resolution"
    return "escalation", "skeptical_countercheck"


def _leaf_index(qdt: dict[str, Any], leaf_id: str) -> tuple[int, dict[str, Any]]:
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list):
        raise ResearcherEscalationError("qdt.required_leaf_questions must be a list")
    for index, leaf in enumerate(leaves):
        if isinstance(leaf, dict) and str(leaf.get("leaf_id")) == leaf_id:
            return index, leaf
    raise ResearcherEscalationError(f"{leaf_id}: leaf not found in qdt")


def _dicts_by_leaf(items: Any, key: str = "leaf_id") -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item[key]): item
        for item in items
        if isinstance(item, dict) and _is_non_empty_string(item.get(key))
    }


def _build_assignment_packet(
    *,
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    leaf_id: str,
    model_execution_context: dict[str, Any],
    attempt_index: int,
    assignment_role: str,
    escalation_decision_ref: str,
    trigger_codes: list[str],
    assigned_lens: str,
) -> dict[str, Any]:
    index, leaf = _leaf_index(qdt, leaf_id)
    contexts = _dicts_by_leaf(retrieval_packet.get("leaf_query_contexts"))
    results = _dicts_by_leaf(retrieval_packet.get("leaf_retrieval_results"))
    certificates = _dicts_by_leaf(retrieval_packet.get("leaf_research_sufficiency_certificates"))
    context = contexts.get(leaf_id)
    result = results.get(leaf_id)
    certificate = certificates.get(leaf_id)
    if not isinstance(context, dict):
        raise ResearcherEscalationError(f"{leaf_id}: missing retrieval query context")
    if not isinstance(result, dict):
        raise ResearcherEscalationError(f"{leaf_id}: missing retrieval result")
    if not isinstance(certificate, dict):
        raise ResearcherEscalationError(f"{leaf_id}: missing research sufficiency certificate")
    return build_leaf_research_assignment(
        qdt=qdt,
        retrieval_packet=retrieval_packet,
        leaf=leaf,
        leaf_index=index,
        query_context=context,
        retrieval_result=result,
        certificate=certificate,
        model_execution_context=model_execution_context,
        attempt_index=attempt_index,
        assignment_role=assignment_role,
        escalation_decision_ref=escalation_decision_ref,
        trigger_codes=trigger_codes,
        assigned_lens=assigned_lens,
    )


def _descriptor_from_assignment(
    *,
    assignment: dict[str, Any],
    decision_ref: str,
    status: str,
) -> dict[str, Any]:
    return {
        "assignment_ref": _assignment_artifact_ref(str(assignment["assignment_id"])),
        "assignment_id": assignment["assignment_id"],
        "assignment_role": assignment["assignment_role"],
        "attempt_index": assignment["attempt_index"],
        "assigned_lens": assignment["assigned_lens"],
        "trigger_codes": list(assignment.get("trigger_codes", [])),
        "escalation_decision_ref": decision_ref,
        "delivery_status": status,
    }


def _planned_assignment_descriptor(
    *,
    decision_id: str,
    decision_ref: str,
    leaf_id: str,
    attempt_index: int,
    assignment_role: str,
    assigned_lens: str,
    trigger_codes: list[str],
    delivered_refs: set[str],
    active_refs: set[str],
    completed_refs: set[str],
) -> dict[str, Any]:
    planned_id = _sha_id(
        "leaf-assignment",
        {
            "decision_id": decision_id,
            "leaf_id": leaf_id,
            "attempt_index": attempt_index,
            "assignment_role": assignment_role,
            "assigned_lens": assigned_lens,
            "trigger_codes": trigger_codes,
        },
    )
    assignment_ref = _assignment_artifact_ref(planned_id)
    if assignment_ref in completed_refs or planned_id in completed_refs:
        status = "completed"
    elif assignment_ref in delivered_refs or planned_id in delivered_refs:
        status = "delivered"
    elif assignment_ref in active_refs or planned_id in active_refs:
        status = "already_active"
    else:
        status = "planned_not_spawned"
    return {
        "assignment_ref": assignment_ref,
        "assignment_id": planned_id,
        "assignment_role": assignment_role,
        "attempt_index": attempt_index,
        "assigned_lens": assigned_lens,
        "trigger_codes": list(trigger_codes),
        "escalation_decision_ref": decision_ref,
        "delivery_status": status,
    }


def _completion_status(
    *,
    triggers: list[str],
    additional_count: int,
    descriptors: list[dict[str, Any]],
    leaf_or_case_cap_reached: bool,
) -> str:
    if not triggers:
        return "not_required"
    if additional_count <= 0:
        return "cap_reached" if leaf_or_case_cap_reached else "blocked"
    completed = {"completed"}
    active_or_delivered = {"completed", "delivered", "already_active"}
    statuses = {str(item.get("delivery_status")) for item in descriptors}
    if statuses and statuses.issubset(completed) and len(descriptors) == additional_count:
        return "required_complete"
    if statuses.intersection(active_or_delivered):
        return "required_pending"
    return "required_pending"


def _decision_digest_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(decision)
    payload.pop("decision_digest", None)
    return payload


def compute_researcher_escalation_decision_digest(decision: dict[str, Any]) -> str:
    return _prefixed_sha256(_decision_digest_payload(decision))


def _collect_forbidden_fields(value: Any, errors: list[str], path: str = "decision") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if normalized not in ALLOWED_PROBABILITY_GUARD_FIELDS:
                if normalized in FORBIDDEN_ESCALATION_FIELD_NAMES:
                    errors.append(f"{path}.{key} is forbidden in {RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION}")
                elif any(fragment in normalized for fragment in FORBIDDEN_ESCALATION_KEY_FRAGMENTS):
                    errors.append(f"{path}.{key} is forbidden in {RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION}")
                elif normalized.endswith("_interval") or normalized.endswith("_odds"):
                    errors.append(f"{path}.{key} is forbidden in {RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION}")
            if normalized in FORBIDDEN_EMBEDDED_PAYLOAD_FIELDS:
                errors.append(f"{path}.{key} embeds payload content forbidden in compact escalation decisions")
            _collect_forbidden_fields(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _collect_forbidden_fields(child, errors, f"{path}[{idx}]")


def _validate_string_list(value: Any, errors: list[str], path: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list")
        return
    if not allow_empty and not value:
        errors.append(f"{path} must be non-empty")
    for idx, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{path}[{idx}] must be a non-empty string")


def _validate_leverage_proxy(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("pre_scae_leverage_proxy must be an object")
        return
    if value.get("bucket") not in ALLOWED_LEVERAGE_BUCKETS:
        errors.append("pre_scae_leverage_proxy.bucket is invalid")
    _validate_string_list(value.get("input_refs"), errors, "pre_scae_leverage_proxy.input_refs")
    _validate_string_list(value.get("reason_codes"), errors, "pre_scae_leverage_proxy.reason_codes", allow_empty=False)
    if value.get("probability_fields_forbidden") is not True:
        errors.append("pre_scae_leverage_proxy.probability_fields_forbidden must be true")


def _validate_assignment_descriptors(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("escalation_assignment_descriptors must be a list")
        return
    for idx, item in enumerate(value):
        path = f"escalation_assignment_descriptors[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        for field in ("assignment_ref", "assignment_id", "assignment_role", "assigned_lens", "escalation_decision_ref", "delivery_status"):
            if not _is_non_empty_string(item.get(field)):
                errors.append(f"{path}.{field} is required")
        if item.get("assignment_role") not in {"escalation", "confirmation"}:
            errors.append(f"{path}.assignment_role must be escalation or confirmation")
        if item.get("delivery_status") not in ALLOWED_ASSIGNMENT_STATUSES:
            errors.append(f"{path}.delivery_status is invalid")
        if not isinstance(item.get("attempt_index"), int) or isinstance(item.get("attempt_index"), bool) or item.get("attempt_index") < 1:
            errors.append(f"{path}.attempt_index must be a positive integer")
        _validate_string_list(item.get("trigger_codes"), errors, f"{path}.trigger_codes", allow_empty=False)


def validate_researcher_escalation_decision(decision: Any) -> ResearcherEscalationValidationResult:
    """Validate a compact CLS-007 escalation decision artifact."""

    errors: list[str] = []
    if not isinstance(decision, dict):
        return ResearcherEscalationValidationResult(False, ("decision must be an object",))
    _collect_forbidden_fields(decision, errors)

    if decision.get("artifact_type") != RESEARCHER_ESCALATION_DECISION_ARTIFACT_TYPE:
        errors.append(f"artifact_type must be {RESEARCHER_ESCALATION_DECISION_ARTIFACT_TYPE}")
    if decision.get("schema_version") != RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION}")
    if decision.get("feature_id") != "CLS-007":
        errors.append("feature_id must be CLS-007")
    if decision.get("builder_version") != CLS_007_ESCALATION_BUILDER_VERSION:
        errors.append(f"builder_version must be {CLS_007_ESCALATION_BUILDER_VERSION}")

    for field in ("decision_id", "case_id", "dispatch_id", "leaf_id", "base_assignment_id"):
        if not _is_non_empty_string(decision.get(field)):
            errors.append(f"{field} is required")
    if _is_non_empty_string(decision.get("decision_id")) and not str(decision["decision_id"]).startswith("researcher-escalation-"):
        errors.append("decision_id must use researcher-escalation prefix")
    if decision.get("decision_ref") != _decision_ref(str(decision.get("decision_id"))):
        errors.append("decision_ref must match decision_id")

    trigger_codes = decision.get("trigger_codes")
    _validate_string_list(trigger_codes, errors, "trigger_codes")
    if isinstance(trigger_codes, list):
        invalid = sorted(set(str(code) for code in trigger_codes) - ALLOWED_TRIGGER_CODES)
        if invalid:
            errors.append("trigger_codes contain invalid codes: " + ", ".join(invalid))
        if list(trigger_codes) != _ordered_triggers([str(code) for code in trigger_codes]):
            errors.append("trigger_codes must use canonical order")
    _validate_string_list(decision.get("trigger_evidence_refs"), errors, "trigger_evidence_refs")
    _validate_string_list(decision.get("classification_ids"), errors, "classification_ids")
    _validate_string_list(decision.get("verification_slice_refs"), errors, "verification_slice_refs")
    _validate_leverage_proxy(decision.get("pre_scae_leverage_proxy"), errors)

    if not isinstance(decision.get("escalation_required"), bool):
        errors.append("escalation_required must be boolean")
    for field in (
        "additional_assignment_count",
        "max_assignments_for_leaf",
        "max_concurrent_leaf_researchers_per_case",
        "current_assignments_for_leaf",
        "current_active_leaf_researchers_for_case",
    ):
        if not isinstance(decision.get(field), int) or isinstance(decision.get(field), bool) or decision.get(field) < 0:
            errors.append(f"{field} must be a non-negative integer")
    if isinstance(decision.get("max_assignments_for_leaf"), int) and decision["max_assignments_for_leaf"] != MAX_ASSIGNMENTS_PER_LEAF:
        errors.append(f"max_assignments_for_leaf must be {MAX_ASSIGNMENTS_PER_LEAF}")
    if (
        isinstance(decision.get("max_concurrent_leaf_researchers_per_case"), int)
        and decision["max_concurrent_leaf_researchers_per_case"] != MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE
    ):
        errors.append(
            "max_concurrent_leaf_researchers_per_case must be "
            f"{MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE}"
        )
    if decision.get("completion_status") not in ALLOWED_COMPLETION_STATUSES:
        errors.append("completion_status is invalid")
    if decision.get("completion_status") == "required_complete" and not decision.get("escalation_required"):
        errors.append("required_complete requires escalation_required true")

    refs = decision.get("escalation_assignment_refs")
    _validate_string_list(refs, errors, "escalation_assignment_refs")
    _validate_assignment_descriptors(decision.get("escalation_assignment_descriptors"), errors)
    if isinstance(refs, list) and isinstance(decision.get("additional_assignment_count"), int):
        if len(refs) != decision["additional_assignment_count"]:
            errors.append("escalation_assignment_refs length must equal additional_assignment_count")
    if decision.get("escalation_required") is True and not decision.get("trigger_codes"):
        errors.append("escalation_required requires at least one trigger")
    if decision.get("trigger_codes") == [] and decision.get("additional_assignment_count") != 0:
        errors.append("no-trigger decisions must not add assignments")

    digest = decision.get("decision_digest")
    if not _is_sha256_ref(digest):
        errors.append("decision_digest must be a sha256 ref")
    elif digest != compute_researcher_escalation_decision_digest(decision):
        errors.append("decision_digest does not match decision payload")

    return ResearcherEscalationValidationResult(not errors, tuple(errors))


def evaluate_researcher_escalation(
    *,
    leaf: dict[str, Any],
    certificate: dict[str, Any],
    classifications: list[dict[str, Any]] | dict[str, Any],
    direction_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    quality_slices: list[dict[str, Any]] | dict[str, Any] | None = None,
    base_assignment: dict[str, Any],
    retrieval_quality: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    existing_leaf_assignments: list[dict[str, Any]] | None = None,
    current_case_active_leaf_researcher_count: int | None = None,
    case_active_assignment_refs: list[str] | None = None,
    delivered_assignment_refs: list[str] | None = None,
    active_assignment_refs: list[str] | None = None,
    completed_assignment_refs: list[str] | None = None,
    qdt: dict[str, Any] | None = None,
    retrieval_packet: dict[str, Any] | None = None,
    model_execution_context: dict[str, Any] | None = None,
) -> ResearcherEscalationEvaluationResult:
    """Build a CLS-007 decision and linked extra assignment packets/descriptors.

    This helper is intentionally local and deterministic: it plans escalation
    artifacts and does not spawn subagents or persist records.
    """

    if not isinstance(leaf, dict):
        raise ResearcherEscalationError("leaf must be an object")
    if not isinstance(certificate, dict):
        raise ResearcherEscalationError("certificate must be an object")
    if not isinstance(base_assignment, dict):
        raise ResearcherEscalationError("base_assignment must be an object")
    if not _is_non_empty_string(base_assignment.get("assignment_id")):
        raise ResearcherEscalationError("base_assignment.assignment_id is required")

    policy = policy or {}
    leaf_id = _leaf_id(leaf, certificate, base_assignment)
    case_id = str(base_assignment.get("case_id") or certificate.get("case_id") or leaf.get("case_id") or "")
    dispatch_id = str(base_assignment.get("dispatch_id") or certificate.get("dispatch_id") or leaf.get("dispatch_id") or "")
    if not case_id or not dispatch_id:
        raise ResearcherEscalationError("case_id and dispatch_id are required")

    filtered_classifications = _classification_slices_from(classifications, leaf_id)
    filtered_direction_slices = _direction_slices_from(direction_slices, leaf_id)
    filtered_quality_slices = _quality_slices_from(quality_slices, leaf_id)
    retrieval_quality_slice = _retrieval_quality_slice_from(retrieval_quality, leaf_id)

    leverage = compute_pre_scae_leverage_proxy(
        leaf=leaf,
        certificate=certificate,
        classifications=filtered_classifications,
        quality_slices=filtered_quality_slices,
        retrieval_quality_slice=retrieval_quality_slice,
        policy=policy,
        base_assignment=base_assignment,
    )

    triggers: list[str] = []
    if _is_critical_or_source_of_truth(leaf):
        triggers.append("critical_source_of_truth_leaf")
    if _has_evidence_conflict(filtered_classifications, filtered_direction_slices):
        triggers.append("evidence_conflict")
    if _low_retrieval_confidence(certificate, retrieval_quality_slice):
        triggers.append("low_retrieval_confidence")
    if _low_classification_confidence(filtered_classifications, filtered_quality_slices):
        triggers.append("low_classification_confidence")
    if leverage["bucket"] == "high":
        triggers.append("high_scae_leverage_proxy")
    if _structural_unanswerability_claimed(certificate):
        triggers.append("structural_unanswerability_claimed")
    triggers = _ordered_triggers(triggers)

    max_for_leaf = MAX_ASSIGNMENTS_PER_LEAF
    max_concurrent = MAX_CONCURRENT_LEAF_RESEARCHERS_PER_CASE
    current_leaf_assignments = _existing_leaf_assignment_count(
        leaf_id=leaf_id,
        base_assignment=base_assignment,
        existing_leaf_assignments=existing_leaf_assignments,
    )
    current_case_active = _case_active_count(
        current_case_active_leaf_researcher_count=current_case_active_leaf_researcher_count,
        case_active_assignment_refs=case_active_assignment_refs,
    )
    desired_additional = _required_extra_assignments_for_triggers(triggers, policy)
    leaf_available = max(0, max_for_leaf - current_leaf_assignments)
    case_available = max(0, max_concurrent - current_case_active)
    additional_count = min(desired_additional, leaf_available, case_available)
    cap_reached = bool(triggers and desired_additional > additional_count)

    role, lens = _assignment_plan_for_triggers(triggers)
    seed = {
        "schema_version": RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION,
        "case_id": case_id,
        "dispatch_id": dispatch_id,
        "leaf_id": leaf_id,
        "base_assignment_id": base_assignment["assignment_id"],
        "trigger_codes": triggers,
        "desired_additional": desired_additional,
        "current_leaf_assignments": current_leaf_assignments,
        "current_case_active": current_case_active,
    }
    decision_id = _sha_id("researcher-escalation", seed)
    decision_ref = _decision_ref(decision_id)

    delivered_refs = set(_unique_strings(delivered_assignment_refs or []))
    active_refs = set(_unique_strings(active_assignment_refs or []))
    completed_refs = set(_unique_strings(completed_assignment_refs or []))
    descriptors: list[dict[str, Any]] = []
    escalation_assignments: list[dict[str, Any]] = []
    for offset in range(additional_count):
        attempt_index = current_leaf_assignments + offset
        if qdt is not None and retrieval_packet is not None:
            full_model_context = model_execution_context or base_assignment.get("model_execution_context")
            if not isinstance(full_model_context, dict):
                raise ResearcherEscalationError("model_execution_context is required to build assignment packets")
            assignment = _build_assignment_packet(
                qdt=qdt,
                retrieval_packet=retrieval_packet,
                leaf_id=leaf_id,
                model_execution_context=full_model_context,
                attempt_index=attempt_index,
                assignment_role=role,
                escalation_decision_ref=decision_ref,
                trigger_codes=triggers,
                assigned_lens=lens,
            )
            validation = validate_leaf_research_assignment(assignment)
            if not validation.valid:
                raise ResearcherEscalationError("escalation assignment invalid: " + "; ".join(validation.errors))
            assignment_ref = _assignment_artifact_ref(str(assignment["assignment_id"]))
            if assignment_ref in completed_refs or assignment["assignment_id"] in completed_refs:
                status = "completed"
            elif assignment_ref in delivered_refs or assignment["assignment_id"] in delivered_refs:
                status = "delivered"
            elif assignment_ref in active_refs or assignment["assignment_id"] in active_refs:
                status = "already_active"
            else:
                status = "planned_not_spawned"
            descriptors.append(_descriptor_from_assignment(assignment=assignment, decision_ref=decision_ref, status=status))
            escalation_assignments.append(assignment)
        else:
            descriptors.append(
                _planned_assignment_descriptor(
                    decision_id=decision_id,
                    decision_ref=decision_ref,
                    leaf_id=leaf_id,
                    attempt_index=attempt_index,
                    assignment_role=role,
                    assigned_lens=lens,
                    trigger_codes=triggers,
                    delivered_refs=delivered_refs,
                    active_refs=active_refs,
                    completed_refs=completed_refs,
                )
            )

    escalation_assignment_refs = [item["assignment_ref"] for item in descriptors]
    completion_status = _completion_status(
        triggers=triggers,
        additional_count=additional_count,
        descriptors=descriptors,
        leaf_or_case_cap_reached=cap_reached,
    )
    decision = {
        "artifact_type": RESEARCHER_ESCALATION_DECISION_ARTIFACT_TYPE,
        "schema_version": RESEARCHER_ESCALATION_DECISION_SCHEMA_VERSION,
        "feature_id": "CLS-007",
        "builder_version": CLS_007_ESCALATION_BUILDER_VERSION,
        "decision_id": decision_id,
        "decision_ref": decision_ref,
        "case_id": case_id,
        "dispatch_id": dispatch_id,
        "leaf_id": leaf_id,
        "base_assignment_id": base_assignment["assignment_id"],
        "trigger_codes": triggers,
        "trigger_evidence_refs": _trigger_evidence_refs(certificate, filtered_classifications, retrieval_quality_slice),
        "retrieval_quality_ref": (
            retrieval_quality_slice.get("slice_id") if isinstance(retrieval_quality_slice, dict) else None
        ),
        "classification_ids": _classification_ids(filtered_classifications),
        "verification_slice_refs": _verification_refs(filtered_direction_slices, filtered_quality_slices),
        "pre_scae_leverage_proxy": leverage,
        "escalation_required": additional_count > 0,
        "additional_assignment_count": additional_count,
        "max_assignments_for_leaf": max_for_leaf,
        "max_concurrent_leaf_researchers_per_case": max_concurrent,
        "current_assignments_for_leaf": current_leaf_assignments,
        "current_active_leaf_researchers_for_case": current_case_active,
        "escalation_assignment_refs": escalation_assignment_refs,
        "escalation_assignment_descriptors": descriptors,
        "completion_status": completion_status,
        "scope_boundaries": {
            "implements": ["CLS-007"],
            "not_implemented": [
                "VER-003",
                "VER-004",
                "SCAE",
                "forecast",
                "replay",
                "scoring",
                "persistence",
                "runtime_subagent_spawning",
            ],
        },
    }
    decision["decision_digest"] = compute_researcher_escalation_decision_digest(decision)
    validation = validate_researcher_escalation_decision(decision)
    if not validation.valid:
        raise ResearcherEscalationError("; ".join(validation.errors))
    return ResearcherEscalationEvaluationResult(
        decision=decision,
        escalation_assignments=escalation_assignments,
    )
