"""CLS-006 compact leaf research assignment packet helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .classification import (
    FORBIDDEN_OUTPUT_FIELDS,
    RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
    RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
    RESEARCHER_SIDECAR_SCHEMA_VERSION,
)
from .model_context import (
    DEFAULT_MODEL_LANE_POLICY_PATH,
    RESEARCHER_MODEL_ID,
    RESEARCHER_MODEL_LANE_ID,
    RESEARCHER_PROVIDER_ROUTE,
    RESEARCHER_PROVIDER_MODEL_KEY,
    RESEARCHER_RUNTIME_AGENT_ID,
    resolve_researcher_leaf_nli_model_context,
    validate_researcher_model_execution_context,
)
from .retrieval import ALLOWED_SOURCE_CLASSES, validate_retrieval_packet


LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION = "leaf-research-assignment/v1"
LEAF_RESEARCH_ASSIGNMENT_ARTIFACT_TYPE = "leaf_research_assignment"
QDT_LEAF_ASSIGNMENT_CONTRACT_SCHEMA_VERSION = "qdt-leaf-assignment-contract/v1"
CLS_006_ASSIGNMENT_BUILDER_VERSION = "ads-cls-006-leaf-research-assignment/v1"
DEFAULT_CONTEXT_ISOLATION_POLICY_ID = "researcher-context-isolation/v1"

ALLOWED_ASSIGNMENT_ROLES = {"primary", "escalation", "confirmation"}
ALLOWED_ASSIGNED_LENSES = {
    "baseline",
    "source_of_truth_check",
    "conflict_resolution",
    "skeptical_countercheck",
    "unanswerability_confirmation",
}
ALLOWED_CONDITION_SCOPES = {
    "unconditional",
    "conditional",
    "branch_local",
    "target_given_upstream",
    "target_given_not_upstream",
    "shared_context",
}
ALLOWED_QDT_MARKET_TEMPORAL_STATES = {"unresolved", "resolved_or_settlement_audit"}
ALLOWED_QDT_LEAF_TEMPORAL_ROLES = {
    "pre_resolution_forecast_driver",
    "current_status",
    "resolution_mechanics",
    "terminal_verification",
    "material_unknown",
}
UNRESOLVED_ASSIGNMENT_TEMPORAL_ROLES = {
    "pre_resolution_forecast_driver",
    "current_status",
    "resolution_mechanics",
    "material_unknown",
}
ALLOWED_QDT_COVERAGE_DIMENSIONS = {
    "resolution_mechanics",
    "current_direct_evidence",
    "key_drivers",
    "counterevidence_negative_checks",
    "timing_deadline_constraints",
    "source_quality",
    "related_market_or_base_rate_context",
    "material_unknowns",
}
DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS = (
    "researcher-sidecar:*",
    "researcher-escalation-decision:*:peer",
    "scae-ledger:*",
    "market-prediction:*",
    "replay-result:*",
    "outcome-scoring:*",
)
DEFAULT_BUDGET = {
    "max_input_tokens": 12000,
    "max_output_tokens": 2500,
    "deadline_seconds": 900,
    "retry_budget": 1,
    "follow_up_research": {
        "max_direct_url_fetches": 0,
        "max_native_candidate_urls": 0,
        "max_supplemental_evidence_refs": 0,
        "allowed_transports": [
            "assigned_evidence_refs",
            "certified_snippet_artifacts",
        ],
        "retrieval_expansion_authority": "upstream_retrieval_only",
        "supplemental_evidence_requires_deterministic_admission": True,
    },
}
ASSIGNMENT_ALLOWED_EVIDENCE_TRANSPORTS = {
    "assigned_evidence_refs",
    "certified_snippet_artifacts",
}
ASSIGNMENT_FORBIDDEN_RETRIEVAL_TRANSPORTS = {
    "browser_retrieval",
    "direct_url_from_assigned_evidence",
    "direct_url_fetch",
    "native_research_candidate_discovery",
    "web_search",
}

FORBIDDEN_ASSIGNMENT_FIELD_NAMES = {
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
    "decision_recommendation",
    "decision_output",
    "trade_recommendation",
}
FORBIDDEN_ASSIGNMENT_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "replacement",
    "log_odds",
)
ALLOWED_DECISION_REF_FIELDS = {"escalation_decision_ref"}
FORBIDDEN_EMBEDDED_PAYLOAD_FIELDS = {
    "full_leaf",
    "leaf_blob",
    "qdt_leaf",
    "required_leaf_questions",
    "branch_questions",
    "question_text",
    "leaf_question",
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


class LeafResearchAssignmentError(ValueError):
    """Raised when a CLS-006 assignment cannot be built or validated."""


@dataclass(frozen=True)
class LeafResearchAssignmentValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_006_ASSIGNMENT_BUILDER_VERSION,
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


def _dicts_by_leaf(items: Any, key: str = "leaf_id") -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item[key]): item
        for item in items
        if isinstance(item, dict) and _is_non_empty_string(item.get(key))
    }


def _dicts_by_id(items: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item[key]): item
        for item in items
        if isinstance(item, dict) and _is_non_empty_string(item.get(key))
    }


def _requirements_from(leaf: dict[str, Any], query_context: dict[str, Any] | None) -> dict[str, Any]:
    requirements = leaf.get("research_sufficiency_requirements")
    if not isinstance(requirements, dict):
        requirements = (query_context or {}).get("sufficiency_requirements")
    if not isinstance(requirements, dict):
        return {}
    return requirements


def _requirement_refs(requirements: dict[str, Any]) -> list[str]:
    return _unique_strings(
        requirements.get("requirement_id"),
        requirements.get("requirement_ref"),
        requirements.get("sufficiency_requirement_ref"),
    )


def _required_value_field_ids(requirements: dict[str, Any]) -> list[str]:
    return _unique_strings(
        requirements.get("required_value_fields"),
        requirements.get("required_value_field_ids"),
    )


def _required_negative_check_ids(requirements: dict[str, Any]) -> list[str]:
    return _unique_strings(
        requirements.get("required_negative_checks"),
        requirements.get("required_negative_check_ids"),
    )


def _first_claim_family_id(item: dict[str, Any]) -> str | None:
    for value in item.get("claim_family_ids", []):
        if _is_non_empty_string(value):
            return str(value)
    for value in item.get("claim_family_resolution_refs", []):
        if _is_non_empty_string(value):
            return str(value)
    if _is_non_empty_string(item.get("claim_family_id")):
        return str(item["claim_family_id"])
    return None


def _chunk_lookup(retrieval_packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    chunks = retrieval_packet.get("evidence_chunks")
    if not isinstance(chunks, list):
        return {}
    return {
        str(chunk["chunk_ref"]): chunk
        for chunk in chunks
        if isinstance(chunk, dict) and _is_non_empty_string(chunk.get("chunk_ref"))
    }


def _certified_snippet_descriptor(
    item: dict[str, Any],
    chunks_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    chunk_refs = item.get("chunk_refs")
    if isinstance(chunk_refs, list):
        for ref in chunk_refs:
            if not _is_non_empty_string(ref):
                continue
            chunk = chunks_by_ref.get(str(ref))
            if not isinstance(chunk, dict):
                continue
            if chunk.get("evidence_ref") != item.get("evidence_ref"):
                continue
            if not _is_non_empty_string(chunk.get("content_artifact_ref")):
                continue
            if not _is_sha256_ref(chunk.get("text_sha256")):
                continue
            excerpt_count = chunk.get("excerpt_char_count")
            if not isinstance(excerpt_count, int) or isinstance(excerpt_count, bool) or excerpt_count <= 0:
                continue
            return {
                "access_mode": "bounded_certified_snippet",
                "snippet_ref": str(chunk["chunk_ref"]),
                "content_artifact_ref": str(chunk["content_artifact_ref"]),
                "text_sha256": str(chunk["text_sha256"]),
                "char_range": {
                    "start": int(chunk.get("char_start") or 0),
                    "end": int(chunk.get("char_end") or 0),
                },
                "excerpt_char_count": int(excerpt_count),
                "excerpt_policy": str(chunk.get("excerpt_policy") or "bounded_excerpt"),
            }
    return None


def _compact_assigned_evidence_refs(
    result: dict[str, Any] | None,
    certificate: dict[str, Any],
    *,
    chunks_by_ref: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    certified_refs = {
        str(ref)
        for ref in certificate.get("evidence_refs", [])
        if _is_non_empty_string(ref)
    }
    compact: list[dict[str, Any]] = []
    selected = (result or {}).get("selected_evidence", [])
    for item in selected if isinstance(selected, list) else []:
        if not isinstance(item, dict) or not _is_non_empty_string(item.get("evidence_ref")):
            continue
        evidence_ref = str(item["evidence_ref"])
        if certified_refs and evidence_ref not in certified_refs:
            continue
        certified_snippet = _certified_snippet_descriptor(item, chunks_by_ref)
        if certified_snippet is None:
            raise LeafResearchAssignmentError(
                f"{evidence_ref}: certified bounded snippet or artifact access is required"
            )
        compact_item = {
            "evidence_ref": evidence_ref,
            "claim_family_id": _first_claim_family_id(item),
            "source_family_id": item.get("source_family_id"),
            "source_class": item.get("source_class", "unknown"),
            "snippet_ref": certified_snippet["snippet_ref"],
            "snippet_sha256": certified_snippet["text_sha256"],
            "certified_snippet": certified_snippet,
        }
        if isinstance(item.get("byte_range"), dict):
            compact_item["byte_range"] = copy.deepcopy(item["byte_range"])
        if isinstance(item.get("char_range"), dict):
            compact_item["char_range"] = copy.deepcopy(item["char_range"])
        compact.append(compact_item)
    return compact


def _compact_model_execution_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_lane_id": context.get("model_lane_id"),
        "resolved_model_id": context.get("resolved_model_id"),
        "provider_model_key": context.get("provider_model_key") or RESEARCHER_PROVIDER_MODEL_KEY,
        "provider_route": context.get("provider_route") or RESEARCHER_PROVIDER_ROUTE,
        "oauth_route_required": context.get("oauth_route_required"),
        "runtime_agent_id": context.get("runtime_agent_id") or RESEARCHER_RUNTIME_AGENT_ID,
        "model_policy_ref": context.get("model_policy_ref"),
        "model_policy_sha256": context.get("model_policy_sha256"),
        "model_context_digest": context.get("model_context_digest"),
        "prompt_template_id": context.get("prompt_template_id"),
        "prompt_template_sha256": context.get("prompt_template_sha256"),
    }


def _resolve_model_context(
    model_execution_context: dict[str, Any] | None,
    model_lane_policy_path: Path | str,
) -> dict[str, Any]:
    if model_execution_context is not None:
        validation = validate_researcher_model_execution_context(model_execution_context)
        if not validation.valid:
            raise LeafResearchAssignmentError("model_execution_context invalid: " + "; ".join(validation.errors))
        return copy.deepcopy(model_execution_context)
    return resolve_researcher_leaf_nli_model_context(
        model_lane_policy_path=model_lane_policy_path,
        prompt_template_id=RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
        prompt_template_sha256=RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
        sidecar_schema_version=RESEARCHER_SIDECAR_SCHEMA_VERSION,
        classification_output_schema_version=RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
    )


def _leaf_pointer(index: int) -> str:
    return f"/required_leaf_questions/{index}"


def _leaf_ref(qdt: dict[str, Any], leaf: dict[str, Any], index: int, retrieval_packet: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = (
        retrieval_packet.get("question_decomposition_artifact_id")
        or qdt.get("artifact_id")
        or "artifact:question-decomposition-unregistered"
    )
    return {
        "artifact_ref": artifact_ref,
        "leaf_json_pointer": _leaf_pointer(index),
        "leaf_digest": leaf.get("leaf_digest") or _prefixed_sha256(leaf),
    }


def _profile_ref(query_context: dict[str, Any] | None, leaf: dict[str, Any], requirements: dict[str, Any]) -> str | None:
    return (
        (query_context or {}).get("breadth_profile_ref")
        or requirements.get("retrieval_breadth_profile_ref")
        or requirements.get("breadth_profile_ref")
        or leaf.get("retrieval_breadth_profile_ref")
    )


def _qdt_graph(qdt: dict[str, Any]) -> dict[str, Any]:
    graph = qdt.get("research_coverage_graph")
    if not isinstance(graph, dict):
        raise LeafResearchAssignmentError("qdt.research_coverage_graph must be present for assignment compilation")
    return graph


def _ordered_leaves_by_id(qdt: dict[str, Any]) -> dict[str, tuple[int, dict[str, Any]]]:
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list):
        return {}
    indexed: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, leaf in enumerate(leaves):
        if isinstance(leaf, dict) and _is_non_empty_string(leaf.get("leaf_id")):
            indexed[str(leaf["leaf_id"])] = (index, leaf)
    return indexed


def _assignment_leaf_ids(qdt: dict[str, Any]) -> list[str]:
    graph = _qdt_graph(qdt)
    market_temporal_state = graph.get("market_temporal_state")
    if market_temporal_state not in ALLOWED_QDT_MARKET_TEMPORAL_STATES:
        raise LeafResearchAssignmentError("qdt.research_coverage_graph.market_temporal_state is invalid")
    raw_ids = graph.get("dispatchable_pre_resolution_leaf_ids")
    if not isinstance(raw_ids, list):
        raise LeafResearchAssignmentError(
            "qdt.research_coverage_graph.dispatchable_pre_resolution_leaf_ids must be a list"
        )
    leaves_by_id = _ordered_leaves_by_id(qdt)
    leaf_ids = []
    seen: set[str] = set()
    for raw_id in raw_ids:
        leaf_id = str(raw_id)
        if not _is_non_empty_string(leaf_id):
            raise LeafResearchAssignmentError("dispatchable_pre_resolution_leaf_ids contains an empty leaf id")
        if leaf_id not in leaves_by_id:
            raise LeafResearchAssignmentError(f"dispatchable_pre_resolution_leaf_ids references unknown leaf {leaf_id}")
        if leaf_id not in seen:
            seen.add(leaf_id)
            leaf_ids.append(leaf_id)
    if market_temporal_state == "unresolved" and not leaf_ids:
        raise LeafResearchAssignmentError("missing_dispatchable_pre_resolution_leaf_assignments")

    dispatchable_leaves = [leaves_by_id[leaf_id][1] for leaf_id in leaf_ids]
    if market_temporal_state == "unresolved":
        terminal_ids = sorted(
            str(leaf.get("leaf_id"))
            for leaf in dispatchable_leaves
            if leaf.get("leaf_temporal_role") == "terminal_verification"
        )
        if terminal_ids:
            raise LeafResearchAssignmentError(
                "terminal_verification_leaf_not_dispatchable_for_unresolved_forecast: "
                + ", ".join(terminal_ids)
            )
        invalid_roles = sorted(
            str(leaf.get("leaf_id"))
            for leaf in dispatchable_leaves
            if leaf.get("leaf_temporal_role") not in UNRESOLVED_ASSIGNMENT_TEMPORAL_ROLES
        )
        if invalid_roles:
            raise LeafResearchAssignmentError(
                "unresolved_assignment_leaf_has_invalid_temporal_role: " + ", ".join(invalid_roles)
            )
        has_forecast_driver = any(
            leaf.get("leaf_temporal_role") == "pre_resolution_forecast_driver"
            for leaf in dispatchable_leaves
        )
        if not has_forecast_driver:
            raise LeafResearchAssignmentError("missing_pre_resolution_forecast_driver_coverage")
    return leaf_ids


def _qdt_leaf_contract_seed(
    *,
    qdt: dict[str, Any],
    leaf: dict[str, Any],
    leaf_ref: dict[str, Any],
) -> dict[str, Any]:
    leaf_id = leaf.get("leaf_id")
    if not _is_non_empty_string(leaf_id):
        raise LeafResearchAssignmentError("leaf_id is required for qdt leaf contract")
    leaf_question = leaf.get("leaf_question") or leaf.get("question_text")
    if not _is_non_empty_string(leaf_question):
        raise LeafResearchAssignmentError(f"{leaf_id}: leaf_question is required for qdt leaf contract")
    temporal_role = leaf.get("leaf_temporal_role")
    if temporal_role not in ALLOWED_QDT_LEAF_TEMPORAL_ROLES:
        raise LeafResearchAssignmentError(f"{leaf_id}: leaf_temporal_role is invalid")
    coverage_dimension = leaf.get("coverage_dimension")
    if coverage_dimension not in ALLOWED_QDT_COVERAGE_DIMENSIONS:
        raise LeafResearchAssignmentError(f"{leaf_id}: coverage_dimension is invalid")
    research_factor = leaf.get("research_factor")
    if not _is_non_empty_string(research_factor):
        raise LeafResearchAssignmentError(f"{leaf_id}: research_factor is required")
    classification_targets = _string_list(leaf.get("classification_targets"))
    if not classification_targets:
        raise LeafResearchAssignmentError(f"{leaf_id}: classification_targets are required")
    evidence_requirements = leaf.get("evidence_requirements")
    if not isinstance(evidence_requirements, list) or not evidence_requirements:
        raise LeafResearchAssignmentError(f"{leaf_id}: evidence_requirements are required")
    compact_requirements = []
    for index, requirement in enumerate(evidence_requirements):
        if not isinstance(requirement, dict):
            raise LeafResearchAssignmentError(f"{leaf_id}: evidence_requirements[{index}] must be an object")
        required_field = requirement.get("required_evidence_field")
        if not _is_non_empty_string(required_field):
            raise LeafResearchAssignmentError(
                f"{leaf_id}: evidence_requirements[{index}].required_evidence_field is required"
            )
        compact_requirements.append(
            {
                "requirement_ref": str(
                    requirement.get("requirement_id")
                    or requirement.get("evidence_requirement_id")
                    or f"qdt-evidence-requirement:{leaf_id}:{index}"
                ),
                "required_evidence_field": str(required_field),
                "required_source_classes": _string_list(requirement.get("required_source_classes")),
                "pre_cutoff_required": requirement.get("pre_cutoff_required") is not False,
                "requirement_digest": _prefixed_sha256(requirement),
            }
        )
    sufficiency_criteria = leaf.get("sufficiency_criteria")
    if not isinstance(sufficiency_criteria, dict) or not sufficiency_criteria:
        raise LeafResearchAssignmentError(f"{leaf_id}: sufficiency_criteria are required")
    missingness = leaf.get("missingness_interpretation")
    if not _is_non_empty_string(missingness):
        raise LeafResearchAssignmentError(f"{leaf_id}: missingness_interpretation is required")
    forbidden_outputs = _string_list(leaf.get("forbidden_outputs"))
    if not forbidden_outputs:
        raise LeafResearchAssignmentError(f"{leaf_id}: forbidden_outputs are required")

    leaf_pointer = leaf_ref.get("leaf_json_pointer")
    artifact_ref = leaf_ref.get("artifact_ref")
    if not _is_non_empty_string(leaf_pointer) or not _is_non_empty_string(artifact_ref):
        raise LeafResearchAssignmentError(f"{leaf_id}: leaf_ref is required for qdt leaf contract")
    return {
        "schema_version": QDT_LEAF_ASSIGNMENT_CONTRACT_SCHEMA_VERSION,
        "artifact_ref": artifact_ref,
        "leaf_id": str(leaf_id),
        "leaf_question_ref": f"{artifact_ref}{leaf_pointer}/leaf_question",
        "leaf_question_sha256": _prefixed_sha256(str(leaf_question)),
        "market_temporal_state": _qdt_graph(qdt).get("market_temporal_state"),
        "leaf_temporal_role": str(temporal_role),
        "coverage_dimension": str(coverage_dimension),
        "research_factor": str(research_factor),
        "evidence_requirement_refs": compact_requirements,
        "classification_targets": classification_targets,
        "sufficiency_criteria_ref": f"{artifact_ref}{leaf_pointer}/sufficiency_criteria",
        "sufficiency_criteria_sha256": _prefixed_sha256(sufficiency_criteria),
        "sufficiency_criteria_summary": {
            "required_source_classes": _string_list(sufficiency_criteria.get("required_source_classes")),
            "required_value_fields": _string_list(sufficiency_criteria.get("required_value_fields")),
            "required_negative_checks": _string_list(sufficiency_criteria.get("required_negative_checks")),
            "min_independent_claim_families": sufficiency_criteria.get("min_independent_claim_families"),
            "min_independent_source_families": sufficiency_criteria.get("min_independent_source_families"),
            "classification_dispatch_requires_sufficiency_certificate": bool(
                sufficiency_criteria.get("classification_dispatch_requires_sufficiency_certificate")
            ),
        },
        "missingness_interpretation": str(missingness),
        "forbidden_outputs": sorted(forbidden_outputs),
        "assignment_authority": "classification_only_no_forecast_authority",
    }


def _assignment_artifact_ref(assignment_id: str) -> str:
    return f"artifact:leaf-research-assignment/{assignment_id}"


def _default_output_refs(assignment_id: str) -> dict[str, str]:
    suffix = assignment_id.removeprefix("leaf-assignment-")
    return {
        "assignment_artifact_ref": _assignment_artifact_ref(assignment_id),
        "sidecar_artifact_ref": f"artifact:researcher-sidecar/{assignment_id}",
        "classification_artifact_ref": f"artifact:researcher-classification/{assignment_id}",
        "coverage_proof_ref": f"coverage-proof-{suffix}",
    }


def _visible_allowlist(
    *,
    assignment_id: str,
    leaf_ref: dict[str, Any],
    model_execution_context: dict[str, Any],
    research_sufficiency_certificate_ref: str,
    retrieval_breadth_profile_ref: str,
    retrieval_breadth_coverage_ref: str,
    assigned_evidence_refs: list[dict[str, Any]],
) -> list[str]:
    refs = [
        _assignment_artifact_ref(assignment_id),
        leaf_ref.get("artifact_ref"),
        research_sufficiency_certificate_ref,
        retrieval_breadth_profile_ref,
        retrieval_breadth_coverage_ref,
        "schema:researcher-sidecar/v2",
        "schema:researcher-classification/v1",
        "schema:researcher-coverage-proof/v1",
        f"prompt-template:{model_execution_context.get('prompt_template_id')}",
        model_execution_context.get("model_policy_ref"),
    ]
    refs.extend(item.get("snippet_ref") for item in assigned_evidence_refs if isinstance(item, dict))
    refs.extend(item.get("evidence_ref") for item in assigned_evidence_refs if isinstance(item, dict))
    refs.extend(
        item.get("certified_snippet", {}).get("content_artifact_ref")
        for item in assigned_evidence_refs
        if isinstance(item, dict) and isinstance(item.get("certified_snippet"), dict)
    )
    return sorted(_unique_strings(refs))


def _assignment_digest_payload(assignment: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(assignment)
    payload.pop("assignment_digest", None)
    return payload


def compute_leaf_research_assignment_digest(assignment: dict[str, Any]) -> str:
    return _prefixed_sha256(_assignment_digest_payload(assignment))


def _collect_forbidden_assignment_fields(value: Any, errors: list[str], path: str = "assignment") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            if normalized not in ALLOWED_DECISION_REF_FIELDS:
                if normalized in FORBIDDEN_ASSIGNMENT_FIELD_NAMES:
                    errors.append(f"{path}.{key} is forbidden in {LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION}")
                elif any(fragment in normalized for fragment in FORBIDDEN_ASSIGNMENT_KEY_FRAGMENTS):
                    errors.append(f"{path}.{key} is forbidden in {LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION}")
                elif normalized.endswith("_interval") or normalized.endswith("_odds"):
                    errors.append(f"{path}.{key} is forbidden in {LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION}")
                elif "decision" in normalized and normalized != "escalation_decision_ref":
                    errors.append(f"{path}.{key} is forbidden in {LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION}")
            if normalized in FORBIDDEN_EMBEDDED_PAYLOAD_FIELDS:
                errors.append(f"{path}.{key} embeds payload content forbidden in compact assignments")
            _collect_forbidden_assignment_fields(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _collect_forbidden_assignment_fields(child, errors, f"{path}[{idx}]")


def _validate_string_list(value: Any, errors: list[str], path: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list")
        return
    if not allow_empty and not value:
        errors.append(f"{path} must be non-empty")
    for idx, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{path}[{idx}] must be a non-empty string")


def _validate_context_isolation(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("context_isolation must be an object")
        return
    if value.get("isolation_policy_id") != DEFAULT_CONTEXT_ISOLATION_POLICY_ID:
        errors.append(f"context_isolation.isolation_policy_id must be {DEFAULT_CONTEXT_ISOLATION_POLICY_ID}")
    if not _is_non_empty_string(value.get("isolation_audit_ref")):
        errors.append("context_isolation.isolation_audit_ref is required")
    if value.get("peer_context_allowed") is not False:
        errors.append("context_isolation.peer_context_allowed must be false")
    _validate_string_list(
        value.get("visible_artifact_ref_allowlist"),
        errors,
        "context_isolation.visible_artifact_ref_allowlist",
    )
    patterns = value.get("forbidden_artifact_ref_patterns")
    _validate_string_list(patterns, errors, "context_isolation.forbidden_artifact_ref_patterns", allow_empty=False)
    if isinstance(patterns, list):
        missing = sorted(set(DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS) - set(str(item) for item in patterns))
        if missing:
            errors.append("context_isolation.forbidden_artifact_ref_patterns missing " + ", ".join(missing))


def _validate_leaf_ref(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("leaf_ref must be an object")
        return
    for field in ("artifact_ref", "leaf_json_pointer", "leaf_digest"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"leaf_ref.{field} is required")
    if _is_non_empty_string(value.get("leaf_digest")) and not _is_sha256_ref(value["leaf_digest"]):
        errors.append("leaf_ref.leaf_digest must be a sha256 ref")
    pointer = value.get("leaf_json_pointer")
    if _is_non_empty_string(pointer) and not str(pointer).startswith("/required_leaf_questions/"):
        errors.append("leaf_ref.leaf_json_pointer must point into required_leaf_questions")


def _validate_qdt_leaf_contract(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("qdt_leaf_contract must be an object")
        return
    if value.get("schema_version") != QDT_LEAF_ASSIGNMENT_CONTRACT_SCHEMA_VERSION:
        errors.append(f"qdt_leaf_contract.schema_version must be {QDT_LEAF_ASSIGNMENT_CONTRACT_SCHEMA_VERSION}")
    for field in (
        "artifact_ref",
        "leaf_id",
        "leaf_question_ref",
        "leaf_question_sha256",
        "research_factor",
        "sufficiency_criteria_ref",
        "sufficiency_criteria_sha256",
        "missingness_interpretation",
        "assignment_authority",
    ):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"qdt_leaf_contract.{field} is required")
    for field in ("leaf_question_sha256", "sufficiency_criteria_sha256"):
        if _is_non_empty_string(value.get(field)) and not _is_sha256_ref(value[field]):
            errors.append(f"qdt_leaf_contract.{field} must be a sha256 ref")
    if value.get("market_temporal_state") not in ALLOWED_QDT_MARKET_TEMPORAL_STATES:
        errors.append("qdt_leaf_contract.market_temporal_state is invalid")
    if value.get("leaf_temporal_role") not in ALLOWED_QDT_LEAF_TEMPORAL_ROLES:
        errors.append("qdt_leaf_contract.leaf_temporal_role is invalid")
    if value.get("coverage_dimension") not in ALLOWED_QDT_COVERAGE_DIMENSIONS:
        errors.append("qdt_leaf_contract.coverage_dimension is invalid")
    if (
        value.get("market_temporal_state") == "unresolved"
        and value.get("leaf_temporal_role") == "terminal_verification"
    ):
        errors.append("qdt_leaf_contract terminal verification leaves are not unresolved forecast assignments")
    _validate_string_list(
        value.get("classification_targets"),
        errors,
        "qdt_leaf_contract.classification_targets",
        allow_empty=False,
    )
    _validate_string_list(
        value.get("forbidden_outputs"),
        errors,
        "qdt_leaf_contract.forbidden_outputs",
        allow_empty=False,
    )
    if value.get("assignment_authority") != "classification_only_no_forecast_authority":
        errors.append("qdt_leaf_contract.assignment_authority must be classification_only_no_forecast_authority")

    requirement_refs = value.get("evidence_requirement_refs")
    if not isinstance(requirement_refs, list) or not requirement_refs:
        errors.append("qdt_leaf_contract.evidence_requirement_refs must be non-empty")
    else:
        for idx, requirement in enumerate(requirement_refs):
            path = f"qdt_leaf_contract.evidence_requirement_refs[{idx}]"
            if not isinstance(requirement, dict):
                errors.append(f"{path} must be an object")
                continue
            for field in ("requirement_ref", "required_evidence_field", "requirement_digest"):
                if not _is_non_empty_string(requirement.get(field)):
                    errors.append(f"{path}.{field} is required")
            if _is_non_empty_string(requirement.get("requirement_digest")) and not _is_sha256_ref(
                requirement["requirement_digest"]
            ):
                errors.append(f"{path}.requirement_digest must be a sha256 ref")
            _validate_string_list(
                requirement.get("required_source_classes"),
                errors,
                f"{path}.required_source_classes",
            )
            if requirement.get("pre_cutoff_required") is not True:
                errors.append(f"{path}.pre_cutoff_required must be true")

    summary = value.get("sufficiency_criteria_summary")
    if not isinstance(summary, dict):
        errors.append("qdt_leaf_contract.sufficiency_criteria_summary must be an object")
        return
    for field in ("required_source_classes", "required_value_fields", "required_negative_checks"):
        _validate_string_list(
            summary.get(field),
            errors,
            f"qdt_leaf_contract.sufficiency_criteria_summary.{field}",
        )
    if summary.get("classification_dispatch_requires_sufficiency_certificate") is not True:
        errors.append(
            "qdt_leaf_contract.sufficiency_criteria_summary.classification_dispatch_requires_sufficiency_certificate "
            "must be true"
        )


def _validate_evidence_refs(value: Any, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("assigned_evidence_refs must be a list")
        return
    for idx, item in enumerate(value):
        path = f"assigned_evidence_refs[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        for field in ("evidence_ref", "source_family_id", "source_class", "snippet_sha256"):
            if not _is_non_empty_string(item.get(field)):
                errors.append(f"{path}.{field} is required")
        if item.get("source_class") not in ALLOWED_SOURCE_CLASSES:
            errors.append(f"{path}.source_class is invalid")
        if item.get("snippet_sha256") and not _is_sha256_ref(item.get("snippet_sha256")):
            errors.append(f"{path}.snippet_sha256 must be a sha256 ref")
        if item.get("claim_family_id") is not None and not _is_non_empty_string(item.get("claim_family_id")):
            errors.append(f"{path}.claim_family_id must be a string or null")
        if item.get("snippet_ref") is not None and not _is_non_empty_string(item.get("snippet_ref")):
            errors.append(f"{path}.snippet_ref must be a string or null")
        _validate_certified_snippet(item.get("certified_snippet"), errors, path, expected_snippet_ref=item.get("snippet_ref"))


def _validate_certified_snippet(
    value: Any,
    errors: list[str],
    path: str,
    *,
    expected_snippet_ref: Any,
) -> None:
    snippet_path = f"{path}.certified_snippet"
    if not isinstance(value, dict):
        errors.append(f"{snippet_path} is required")
        return
    expected = {
        "access_mode": "bounded_certified_snippet",
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            errors.append(f"{snippet_path}.{field} must be {expected_value}")
    for field in ("snippet_ref", "content_artifact_ref", "text_sha256", "excerpt_policy"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"{snippet_path}.{field} is required")
    if _is_non_empty_string(value.get("snippet_ref")) and value.get("snippet_ref") != expected_snippet_ref:
        errors.append(f"{snippet_path}.snippet_ref must match {path}.snippet_ref")
    if _is_non_empty_string(value.get("text_sha256")) and not _is_sha256_ref(value.get("text_sha256")):
        errors.append(f"{snippet_path}.text_sha256 must be a sha256 ref")
    char_range = value.get("char_range")
    if not isinstance(char_range, dict):
        errors.append(f"{snippet_path}.char_range must be an object")
    else:
        for field in ("start", "end"):
            if not isinstance(char_range.get(field), int) or isinstance(char_range.get(field), bool) or char_range.get(field) < 0:
                errors.append(f"{snippet_path}.char_range.{field} must be a non-negative integer")
        if (
            isinstance(char_range.get("start"), int)
            and not isinstance(char_range.get("start"), bool)
            and isinstance(char_range.get("end"), int)
            and not isinstance(char_range.get("end"), bool)
            and char_range["end"] < char_range["start"]
        ):
            errors.append(f"{snippet_path}.char_range.end must be >= start")
    excerpt_count = value.get("excerpt_char_count")
    if not isinstance(excerpt_count, int) or isinstance(excerpt_count, bool) or excerpt_count <= 0:
        errors.append(f"{snippet_path}.excerpt_char_count must be a positive integer")


def _validate_output_contract(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("output_contract must be an object")
        return
    expected = {
        "sidecar_schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
        "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
        "coverage_proof_schema_version": RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            errors.append(f"output_contract.{field} must be {expected_value}")
    if value.get("coverage_proof_required") is not True:
        errors.append("output_contract.coverage_proof_required must be true")
    forbidden = value.get("forbidden_fields")
    if not isinstance(forbidden, list) or sorted(forbidden) != sorted(FORBIDDEN_OUTPUT_FIELDS):
        errors.append("output_contract.forbidden_fields must match no-probability output contract")


def _validate_model_execution_context(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("model_execution_context must be an object")
        return
    expected = {
        "model_lane_id": RESEARCHER_MODEL_LANE_ID,
        "resolved_model_id": RESEARCHER_MODEL_ID,
        "provider_route": RESEARCHER_PROVIDER_ROUTE,
        "runtime_agent_id": RESEARCHER_RUNTIME_AGENT_ID,
        "prompt_template_id": RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
        "prompt_template_sha256": RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            errors.append(f"model_execution_context.{field} must be {expected_value}")
    if value.get("provider_model_key") != RESEARCHER_PROVIDER_MODEL_KEY:
        errors.append(f"model_execution_context.provider_model_key must be {RESEARCHER_PROVIDER_MODEL_KEY}")
    if value.get("oauth_route_required") is not True:
        errors.append("model_execution_context.oauth_route_required must be true")
    for field in ("model_policy_ref", "model_policy_sha256", "model_context_digest"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"model_execution_context.{field} is required")
    for field in ("model_policy_sha256", "model_context_digest", "prompt_template_sha256"):
        if _is_non_empty_string(value.get(field)) and not _is_sha256_ref(value[field]):
            errors.append(f"model_execution_context.{field} must be a sha256 ref")


def _validate_budget(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("budget must be an object")
        return
    for field in ("max_input_tokens", "max_output_tokens", "deadline_seconds"):
        if not isinstance(value.get(field), int) or isinstance(value.get(field), bool) or value.get(field) <= 0:
            errors.append(f"budget.{field} must be a positive integer")
    if not isinstance(value.get("retry_budget"), int) or isinstance(value.get("retry_budget"), bool) or value.get("retry_budget") < 0:
        errors.append("budget.retry_budget must be a non-negative integer")
    follow_up = value.get("follow_up_research")
    if not isinstance(follow_up, dict):
        errors.append("budget.follow_up_research must be an object")
        return
    for field in ("max_direct_url_fetches", "max_native_candidate_urls", "max_supplemental_evidence_refs"):
        if (
            not isinstance(follow_up.get(field), int)
            or isinstance(follow_up.get(field), bool)
            or follow_up.get(field) < 0
        ):
            errors.append(f"budget.follow_up_research.{field} must be a non-negative integer")
        elif follow_up.get(field) != 0:
            errors.append(f"budget.follow_up_research.{field} must be 0 for classifier-only researchers")
    _validate_string_list(
        follow_up.get("allowed_transports"),
        errors,
        "budget.follow_up_research.allowed_transports",
        allow_empty=False,
    )
    transports = _string_list(follow_up.get("allowed_transports"))
    if set(transports) != ASSIGNMENT_ALLOWED_EVIDENCE_TRANSPORTS:
        errors.append(
            "budget.follow_up_research.allowed_transports must be assigned evidence and certified snippet artifacts only"
        )
    forbidden_transports = sorted(set(transports) & ASSIGNMENT_FORBIDDEN_RETRIEVAL_TRANSPORTS)
    if forbidden_transports:
        errors.append(
            "budget.follow_up_research.allowed_transports includes forbidden retrieval transports: "
            + ", ".join(forbidden_transports)
        )
    if follow_up.get("retrieval_expansion_authority") != "upstream_retrieval_only":
        errors.append("budget.follow_up_research.retrieval_expansion_authority must be upstream_retrieval_only")
    if follow_up.get("supplemental_evidence_requires_deterministic_admission") is not True:
        errors.append(
            "budget.follow_up_research.supplemental_evidence_requires_deterministic_admission must be true"
        )


def _validate_artifact_outputs(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("artifact_outputs must be an object")
        return
    for field in ("assignment_artifact_ref", "sidecar_artifact_ref", "coverage_proof_ref"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"artifact_outputs.{field} is required")


def validate_leaf_research_assignment(assignment: Any) -> LeafResearchAssignmentValidationResult:
    """Validate a compact CLS-006 assignment without launching a subagent."""

    errors: list[str] = []
    if not isinstance(assignment, dict):
        return LeafResearchAssignmentValidationResult(False, ("assignment must be an object",))
    _collect_forbidden_assignment_fields(assignment, errors)

    if assignment.get("artifact_type") != LEAF_RESEARCH_ASSIGNMENT_ARTIFACT_TYPE:
        errors.append(f"artifact_type must be {LEAF_RESEARCH_ASSIGNMENT_ARTIFACT_TYPE}")
    if assignment.get("schema_version") != LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION}")
    if assignment.get("feature_id") != "CLS-006":
        errors.append("feature_id must be CLS-006")
    if assignment.get("builder_version") != CLS_006_ASSIGNMENT_BUILDER_VERSION:
        errors.append(f"builder_version must be {CLS_006_ASSIGNMENT_BUILDER_VERSION}")

    for field in ("assignment_id", "case_id", "dispatch_id", "leaf_id", "parent_branch_id"):
        if not _is_non_empty_string(assignment.get(field)):
            errors.append(f"{field} is required")
    if not isinstance(assignment.get("attempt_index"), int) or isinstance(assignment.get("attempt_index"), bool) or assignment.get("attempt_index") < 0:
        errors.append("attempt_index must be a non-negative integer")
    if assignment.get("assignment_role") not in ALLOWED_ASSIGNMENT_ROLES:
        errors.append("assignment_role is invalid")
    if assignment.get("assigned_lens") not in ALLOWED_ASSIGNED_LENSES:
        errors.append("assigned_lens is invalid")
    if assignment.get("condition_scope") not in ALLOWED_CONDITION_SCOPES:
        errors.append("condition_scope is invalid")
    if assignment.get("assignment_role") == "primary":
        if assignment.get("escalation_decision_ref") is not None:
            errors.append("primary assignments must not carry escalation_decision_ref")
        if assignment.get("trigger_codes") != []:
            errors.append("primary assignments must have empty trigger_codes")
    else:
        if not _is_non_empty_string(assignment.get("escalation_decision_ref")):
            errors.append("escalation_decision_ref is required for escalation/confirmation assignments")
    _validate_string_list(assignment.get("trigger_codes"), errors, "trigger_codes")

    _validate_context_isolation(assignment.get("context_isolation"), errors)
    _validate_leaf_ref(assignment.get("leaf_ref"), errors)
    _validate_qdt_leaf_contract(assignment.get("qdt_leaf_contract"), errors)
    if (
        isinstance(assignment.get("qdt_leaf_contract"), dict)
        and assignment["qdt_leaf_contract"].get("leaf_id") != assignment.get("leaf_id")
    ):
        errors.append("qdt_leaf_contract.leaf_id must match assignment.leaf_id")
    _validate_string_list(
        assignment.get("sufficiency_requirement_refs"),
        errors,
        "sufficiency_requirement_refs",
        allow_empty=False,
    )
    for field in (
        "research_sufficiency_certificate_ref",
        "retrieval_breadth_profile_ref",
        "retrieval_breadth_coverage_ref",
    ):
        if not _is_non_empty_string(assignment.get(field)):
            errors.append(f"{field} is required")
    _validate_evidence_refs(assignment.get("assigned_evidence_refs"), errors)
    _validate_string_list(assignment.get("required_value_field_ids"), errors, "required_value_field_ids")
    _validate_string_list(assignment.get("required_negative_check_ids"), errors, "required_negative_check_ids")
    _validate_output_contract(assignment.get("output_contract"), errors)
    _validate_model_execution_context(assignment.get("model_execution_context"), errors)
    _validate_budget(assignment.get("budget"), errors)
    _validate_artifact_outputs(assignment.get("artifact_outputs"), errors)

    assignment_digest = assignment.get("assignment_digest")
    if not _is_sha256_ref(assignment_digest):
        errors.append("assignment_digest must be a sha256 ref")
    elif assignment_digest != compute_leaf_research_assignment_digest(assignment):
        errors.append("assignment_digest does not match assignment payload")

    return LeafResearchAssignmentValidationResult(not errors, tuple(errors))


def _validate_dispatchable_inputs(qdt: dict[str, Any], retrieval_packet: dict[str, Any]) -> None:
    if not isinstance(qdt, dict) or qdt.get("schema_version") != "question-decomposition/v1":
        raise LeafResearchAssignmentError("qdt must be question-decomposition/v1")
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list) or not leaves:
        raise LeafResearchAssignmentError("qdt.required_leaf_questions must be a non-empty list")
    _assignment_leaf_ids(qdt)
    summary = retrieval_packet.get("research_sufficiency_summary")
    if not isinstance(summary, dict) or summary.get("classification_dispatch_status") != "allowed":
        status = summary.get("classification_dispatch_status") if isinstance(summary, dict) else "missing"
        raise LeafResearchAssignmentError(f"classification dispatch is not allowed: {status}")
    packet_validation = validate_retrieval_packet(retrieval_packet)
    if not packet_validation.valid:
        raise LeafResearchAssignmentError("retrieval_packet invalid: " + "; ".join(packet_validation.errors))


def build_leaf_research_assignment(
    *,
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    leaf: dict[str, Any],
    leaf_index: int,
    query_context: dict[str, Any],
    retrieval_result: dict[str, Any],
    certificate: dict[str, Any],
    model_execution_context: dict[str, Any],
    attempt_index: int = 0,
    assignment_role: str = "primary",
    escalation_decision_ref: str | None = None,
    trigger_codes: list[str] | None = None,
    assigned_lens: str = "baseline",
    isolation_audit_ref: str | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one compact leaf-research-assignment/v1 packet."""

    if assignment_role not in ALLOWED_ASSIGNMENT_ROLES:
        raise LeafResearchAssignmentError("assignment_role is invalid")
    if assigned_lens not in ALLOWED_ASSIGNED_LENSES:
        raise LeafResearchAssignmentError("assigned_lens is invalid")
    if assignment_role == "primary" and escalation_decision_ref is not None:
        raise LeafResearchAssignmentError("primary assignments must not carry escalation_decision_ref")
    if assignment_role != "primary" and not _is_non_empty_string(escalation_decision_ref):
        raise LeafResearchAssignmentError("escalation_decision_ref is required for escalation/confirmation assignments")
    if not isinstance(attempt_index, int) or isinstance(attempt_index, bool) or attempt_index < 0:
        raise LeafResearchAssignmentError("attempt_index must be a non-negative integer")
    if certificate.get("classification_dispatch_allowed") is not True:
        raise LeafResearchAssignmentError(f"leaf {leaf.get('leaf_id')} is not dispatchable")

    requirements = _requirements_from(leaf, query_context)
    sufficiency_requirement_refs = _requirement_refs(requirements)
    if not sufficiency_requirement_refs:
        raise LeafResearchAssignmentError(f"leaf {leaf.get('leaf_id')} missing sufficiency requirement refs")
    breadth_profile_ref = _profile_ref(query_context, leaf, requirements)
    breadth_coverage_ref = certificate.get("breadth_coverage_ref")
    if not _is_non_empty_string(breadth_profile_ref):
        raise LeafResearchAssignmentError(f"leaf {leaf.get('leaf_id')} missing retrieval breadth profile ref")
    if not _is_non_empty_string(breadth_coverage_ref):
        raise LeafResearchAssignmentError(f"leaf {leaf.get('leaf_id')} missing retrieval breadth coverage ref")

    leaf_ref = _leaf_ref(qdt, leaf, leaf_index, retrieval_packet)
    assigned_evidence_refs = _compact_assigned_evidence_refs(
        retrieval_result,
        certificate,
        chunks_by_ref=_chunk_lookup(retrieval_packet),
    )
    qdt_leaf_contract = _qdt_leaf_contract_seed(qdt=qdt, leaf=leaf, leaf_ref=leaf_ref)
    seed = {
        "schema_version": LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION,
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "leaf_id": leaf.get("leaf_id"),
        "leaf_digest": leaf_ref["leaf_digest"],
        "qdt_leaf_contract": qdt_leaf_contract,
        "attempt_index": attempt_index,
        "assignment_role": assignment_role,
        "escalation_decision_ref": escalation_decision_ref,
        "trigger_codes": sorted(trigger_codes or []),
        "assigned_lens": assigned_lens,
        "research_sufficiency_certificate_ref": certificate.get("certificate_id"),
        "assigned_evidence_refs": [item.get("evidence_ref") for item in assigned_evidence_refs],
    }
    assignment_id = _sha_id("leaf-assignment", seed)
    compact_model_context = _compact_model_execution_context(model_execution_context)
    artifact_outputs = _default_output_refs(assignment_id)
    audit_ref = isolation_audit_ref or f"researcher-context-isolation:{assignment_id}"
    assignment = {
        "artifact_type": LEAF_RESEARCH_ASSIGNMENT_ARTIFACT_TYPE,
        "schema_version": LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION,
        "feature_id": "CLS-006",
        "builder_version": CLS_006_ASSIGNMENT_BUILDER_VERSION,
        "assignment_id": assignment_id,
        "attempt_index": attempt_index,
        "assignment_role": assignment_role,
        "escalation_decision_ref": escalation_decision_ref,
        "trigger_codes": list(trigger_codes or []),
        "assigned_lens": assigned_lens,
        "context_isolation": {
            "isolation_policy_id": DEFAULT_CONTEXT_ISOLATION_POLICY_ID,
            "isolation_audit_ref": audit_ref,
            "peer_context_allowed": False,
            "visible_artifact_ref_allowlist": _visible_allowlist(
                assignment_id=assignment_id,
                leaf_ref=leaf_ref,
                model_execution_context=compact_model_context,
                research_sufficiency_certificate_ref=str(certificate.get("certificate_id")),
                retrieval_breadth_profile_ref=str(breadth_profile_ref),
                retrieval_breadth_coverage_ref=str(breadth_coverage_ref),
                assigned_evidence_refs=assigned_evidence_refs,
            ),
            "forbidden_artifact_ref_patterns": list(DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS),
        },
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "leaf_id": leaf.get("leaf_id"),
        "parent_branch_id": leaf.get("parent_branch_id") or query_context.get("parent_branch_id"),
        "leaf_ref": leaf_ref,
        "qdt_leaf_contract": qdt_leaf_contract,
        "condition_scope": leaf.get("leaf_condition_scope") or query_context.get("condition_scope"),
        "sufficiency_requirement_refs": sufficiency_requirement_refs,
        "research_sufficiency_certificate_ref": certificate.get("certificate_id"),
        "retrieval_breadth_profile_ref": breadth_profile_ref,
        "retrieval_breadth_coverage_ref": breadth_coverage_ref,
        "assigned_evidence_refs": assigned_evidence_refs,
        "required_value_field_ids": _required_value_field_ids(requirements),
        "required_negative_check_ids": _required_negative_check_ids(requirements),
        "output_contract": {
            "sidecar_schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
            "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
            "coverage_proof_schema_version": RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
            "coverage_proof_required": True,
            "forbidden_fields": list(FORBIDDEN_OUTPUT_FIELDS),
        },
        "model_execution_context": compact_model_context,
        "budget": {
            **DEFAULT_BUDGET,
            **(budget or {}),
            "follow_up_research": {
                **DEFAULT_BUDGET["follow_up_research"],
                **((budget or {}).get("follow_up_research", {}) if isinstance((budget or {}).get("follow_up_research"), dict) else {}),
            },
        },
        "artifact_outputs": artifact_outputs,
        "scope_boundaries": {
            "implements": ["CLS-006"],
            "not_implemented": [
                "CLS-003",
                "CLS-005",
                "CLS-007",
                "CLS-008",
                "VER",
                "SCAE",
                "runtime_subagent_spawning",
            ],
        },
    }
    assignment["assignment_digest"] = compute_leaf_research_assignment_digest(assignment)
    validation = validate_leaf_research_assignment(assignment)
    if not validation.valid:
        raise LeafResearchAssignmentError("; ".join(validation.errors))
    return assignment


def build_leaf_research_assignments(
    *,
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    model_execution_context: dict[str, Any] | None = None,
    model_lane_policy_path: Path | str = DEFAULT_MODEL_LANE_POLICY_PATH,
    attempt_index: int = 0,
    assignment_role: str = "primary",
    escalation_decision_ref: str | None = None,
    trigger_codes_by_leaf: dict[str, list[str]] | None = None,
    assigned_lens_by_leaf: dict[str, str] | None = None,
    isolation_audit_refs_by_leaf: dict[str, str] | None = None,
    budget: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build compact assignments for every RET-008 dispatchable QDT leaf."""

    _validate_dispatchable_inputs(qdt, retrieval_packet)
    full_model_context = _resolve_model_context(model_execution_context, model_lane_policy_path)
    contexts = _dicts_by_leaf(retrieval_packet.get("leaf_query_contexts"))
    results = _dicts_by_leaf(retrieval_packet.get("leaf_retrieval_results"))
    certificates = _dicts_by_leaf(retrieval_packet.get("leaf_research_sufficiency_certificates"))
    profiles = _dicts_by_id(retrieval_packet.get("retrieval_breadth_profiles"), "profile_id")
    coverage = _dicts_by_id(retrieval_packet.get("retrieval_breadth_coverage_slices"), "coverage_id")
    assignments: list[dict[str, Any]] = []

    leaves_by_id = _ordered_leaves_by_id(qdt)
    for leaf_id in _assignment_leaf_ids(qdt):
        index, leaf = leaves_by_id[leaf_id]
        context = contexts.get(leaf_id)
        result = results.get(leaf_id)
        certificate = certificates.get(leaf_id)
        if not isinstance(context, dict):
            raise LeafResearchAssignmentError(f"{leaf_id}: missing retrieval query context")
        if not isinstance(result, dict):
            raise LeafResearchAssignmentError(f"{leaf_id}: missing retrieval result")
        if not isinstance(certificate, dict):
            raise LeafResearchAssignmentError(f"{leaf_id}: missing research sufficiency certificate")
        requirements = _requirements_from(leaf, context)
        profile_ref = _profile_ref(context, leaf, requirements)
        if _is_non_empty_string(profile_ref) and str(profile_ref) not in profiles:
            raise LeafResearchAssignmentError(f"{leaf_id}: retrieval breadth profile ref is not present")
        coverage_ref = certificate.get("breadth_coverage_ref")
        if _is_non_empty_string(coverage_ref) and str(coverage_ref) not in coverage:
            raise LeafResearchAssignmentError(f"{leaf_id}: retrieval breadth coverage ref is not present")

        assignments.append(
            build_leaf_research_assignment(
                qdt=qdt,
                retrieval_packet=retrieval_packet,
                leaf=leaf,
                leaf_index=index,
                query_context=context,
                retrieval_result=result,
                certificate=certificate,
                model_execution_context=full_model_context,
                attempt_index=attempt_index,
                assignment_role=assignment_role,
                escalation_decision_ref=escalation_decision_ref,
                trigger_codes=(trigger_codes_by_leaf or {}).get(leaf_id, []),
                assigned_lens=(assigned_lens_by_leaf or {}).get(leaf_id, "baseline"),
                isolation_audit_ref=(isolation_audit_refs_by_leaf or {}).get(leaf_id),
                budget=budget,
            )
        )
    return assignments
