"""CLS-001 researcher NLI classification prompt contract helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .model_context import (
    DEFAULT_MODEL_LANE_POLICY_PATH,
    resolve_researcher_leaf_nli_model_context,
    validate_researcher_model_execution_context,
)


RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION = "researcher-nli-prompt-contract/v1"
RESEARCHER_NLI_PROMPT_TEMPLATE_ID = "researcher-leaf-nli/v1"
RESEARCHER_NLI_PROMPT_TEMPLATE_VERSION = "cls-001-researcher-leaf-nli/v1"
RESEARCHER_SIDECAR_SCHEMA_VERSION = "researcher-sidecar/v2"
RESEARCHER_CLASSIFICATION_SCHEMA_VERSION = "researcher-classification/v1"
RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION = "researcher-coverage-proof/v1"
CLS_001_CONTRACT_BUILDER_VERSION = "ads-cls-001-researcher-nli-prompt-contract/v1"
CLS_002_SIDECAR_VALIDATOR_VERSION = "ads-cls-002-no-probability-sidecar/v1"

ALLOWED_CLASSIFICATION_DISPATCH_STATUS = "allowed"
FORBIDDEN_OUTPUT_FIELDS = (
    "own_probability",
    "fair_value",
    "interval",
    "macro_probability",
    "final_macro_probability",
    "decision_recommendation",
)
FORBIDDEN_CONTEXT_REF_PATTERNS = (
    "researcher-sidecar:*:peer",
    "researcher-escalation-decision:*:peer",
    "scae-ledger:*",
    "scae-policy:*",
    "market-prediction:*",
    "replay-result:*",
    "outcome-scoring:*",
    "aggregate-research-summary:*",
)
FORBIDDEN_V2_SIDECAR_FIELDS = (
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
    "replacement_probability_yes",
    "replacement_probability_no",
    "replacement_forecast",
    "replacement_decision",
    "fair_value",
    "fair_value_low",
    "fair_value_mid",
    "fair_value_high",
    "interval",
    "odds",
    "log_odds",
    "confidence",
    "confidence_score",
    "confidence_as_probability",
    "probability_confidence",
    "confidence_probability",
)
FORBIDDEN_V2_SIDECAR_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "replacement",
    "log_odds",
)
ALLOWED_FALSE_AUTHORITY_BOUNDARY_FIELDS = {
    "model_outputs_may_author_probability",
    "probability_authority",
}
ALLOWED_IMPACT_DIRECTIONS = {"supports_yes", "supports_no", "neutral"}
ALLOWED_EVIDENCE_STRENGTHS = {"definitive", "strong", "moderate", "weak", "none", "unanswerable"}
ALLOWED_CLASSIFICATION_CONFIDENCES = {"high", "medium", "low"}
ALLOWED_LEAF_CONDITION_SCOPES = {
    "unconditional",
    "conditional",
    "branch_local",
    "target_given_upstream",
    "target_given_not_upstream",
    "shared_context",
}
ALLOWED_SOURCE_AUTHORITY_VALUES = {"high", "medium", "low", "unknown"}
ALLOWED_DIRECTNESS_VALUES = {"direct", "indirect", "background", "unknown"}
ALLOWED_RECENCY_VALUES = {"fresh", "stale", "timeless", "unknown"}
ALLOWED_SPECIFICITY_VALUES = {"specific", "general", "ambiguous", "unknown"}
ALLOWED_VALUE_NORMALIZATION_STATUSES = {"parsed", "not_applicable", "failed"}
RESEARCHER_LEAF_NLI_MODEL_LANE_ID = "researcher_leaf_nli_classification"

RESEARCHER_NLI_PROMPT_TEMPLATE = """You are a leaf evidence classification researcher.

Task boundary:
- Classify supplied retrieval evidence against the macro question and flattened QDT leaf questions.
- Treat all market constraints, retrieval sufficiency certificates, breadth profiles, breadth coverage slices, and evidence refs as read-only inputs.
- Do evidence classification only: entailment, contradiction, neutral/no-support, or structurally-unanswerable-with-proof.
- Extract required values and negative-check observations only when supported by assigned evidence refs.
- Do not forecast, price, trade, recommend a decision, reassemble leaves, or author any numeric probability.

Required output:
- Produce only researcher-sidecar/v2 records containing researcher-classification/v1 rows and researcher-coverage-proof/v1 refs.
- Every non-neutral classification must cite retrieval evidence refs and the relevant leaf sufficiency requirement refs.
- Every gap must be reported as a structured insufficiency or structural-unanswerability observation, never as a forecast.

Forbidden output fields:
- own_probability
- fair_value
- interval
- macro_probability
- final_macro_probability
- decision_recommendation

Forbidden context:
- No peer researcher sidecars, peer escalation decisions, SCAE ledger/policy refs, market prediction refs, replay results, outcome scoring, or aggregate research summaries.
"""

RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256 = (
    "sha256:" + hashlib.sha256(RESEARCHER_NLI_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
)


class ClassificationPromptContractError(ValueError):
    """Raised when a CLS-001 prompt contract cannot be built or validated."""


class ResearcherSidecarError(ValueError):
    """Raised when a CLS-002 sidecar artifact cannot be built or validated."""


@dataclass(frozen=True)
class ClassificationPromptValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_001_CONTRACT_BUILDER_VERSION,
        }


@dataclass(frozen=True)
class ResearcherSidecarValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_002_SIDECAR_VALIDATOR_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dicts_by_leaf(items: Any, key: str = "leaf_id") -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item[key]): item
        for item in items
        if isinstance(item, dict) and _is_non_empty_string(item.get(key))
    }


def _leaf_static_weight(leaf: dict[str, Any]) -> str | None:
    weighting = leaf.get("bayesian_weighting")
    if isinstance(weighting, dict) and _is_non_empty_string(weighting.get("static_information_weight")):
        return str(weighting["static_information_weight"])
    return None


def _compact_sufficiency_requirements(leaf: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    requirements = copy.deepcopy(leaf.get("research_sufficiency_requirements"))
    if not isinstance(requirements, dict):
        requirements = copy.deepcopy((context or {}).get("sufficiency_requirements"))
    if not isinstance(requirements, dict):
        requirements = {}
    return {
        "requirement_ref": requirements.get("requirement_id"),
        "schema_version": requirements.get("schema_version"),
        "template_version": requirements.get("template_version"),
        "sufficiency_profile_id": requirements.get("sufficiency_profile_id"),
        "target_answerability": requirements.get("target_answerability"),
        "required_source_classes": list(requirements.get("required_source_classes", [])),
        "protected_primary_required": bool(requirements.get("protected_primary_required", False)),
        "min_independent_claim_families": requirements.get("min_independent_claim_families"),
        "min_independent_source_families": requirements.get("min_independent_source_families"),
        "min_temporally_fresh_sources": requirements.get("min_temporally_fresh_sources"),
        "required_value_field_ids": list(requirements.get("required_value_fields", [])),
        "required_negative_check_ids": list(requirements.get("required_negative_checks", [])),
        "contradiction_search_required": bool(requirements.get("contradiction_search_required", False)),
        "classification_dispatch_requires_sufficiency_certificate": bool(
            requirements.get("classification_dispatch_requires_sufficiency_certificate", False)
        ),
        "unanswerability_proof_required": bool(requirements.get("unanswerability_proof_required", False)),
    }


def _compact_assigned_evidence_refs(result: dict[str, Any] | None, certificate: dict[str, Any] | None) -> list[dict[str, Any]]:
    certified_refs = set()
    if isinstance(certificate, dict):
        certified_refs = {
            str(ref)
            for ref in certificate.get("evidence_refs", [])
            if _is_non_empty_string(ref)
        }
    items = (result or {}).get("selected_evidence", [])
    compact: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not _is_non_empty_string(item.get("evidence_ref")):
            continue
        evidence_ref = str(item["evidence_ref"])
        compact.append(
            {
                "evidence_ref": evidence_ref,
                "source_class": item.get("source_class"),
                "source_family_id": item.get("source_family_id"),
                "claim_family_ids": list(item.get("claim_family_ids", item.get("claim_family_resolution_refs", []))),
                "temporal_gate_status": item.get("temporal_gate_status"),
                "content_sha256": item.get("content_sha256"),
                "counts_toward_breadth": bool(item.get("counts_toward_breadth", False)),
                "covered_by_sufficiency_certificate": evidence_ref in certified_refs,
            }
        )
    return compact


def _render_prompt_text(context_payload: dict[str, Any]) -> str:
    return (
        RESEARCHER_NLI_PROMPT_TEMPLATE
        + "\nContract payload follows as canonical JSON. Use it as read-only input:\n"
        + _canonical_json(context_payload)
        + "\n"
    )


def build_researcher_nli_prompt_contract(
    *,
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    model_execution_context: dict[str, Any] | None = None,
    model_lane_policy_path: Any = DEFAULT_MODEL_LANE_POLICY_PATH,
    output_contract_ref: str = "schema:researcher-sidecar/v2",
    classification_contract_ref: str = "schema:researcher-classification/v1",
    coverage_contract_ref: str = "schema:researcher-coverage-proof/v1",
) -> dict[str, Any]:
    """Build the CLS-001 prompt artifact for leaf evidence classification.

    The builder is deliberately fail-closed: a retrieval packet whose
    ``classification_dispatch_status`` is anything other than ``allowed`` cannot
    produce a prompt contract.
    """

    dispatch_summary = retrieval_packet.get("research_sufficiency_summary")
    if not isinstance(dispatch_summary, dict):
        raise ClassificationPromptContractError("retrieval packet missing research_sufficiency_summary")
    dispatch_status = dispatch_summary.get("classification_dispatch_status")
    if dispatch_status != ALLOWED_CLASSIFICATION_DISPATCH_STATUS:
        raise ClassificationPromptContractError(
            "classification dispatch is not allowed: "
            + str(dispatch_status or "missing_classification_dispatch_status")
        )

    leaves = qdt.get("required_leaf_questions")
    if qdt.get("schema_version") != "question-decomposition/v1" or not isinstance(leaves, list) or not leaves:
        raise ClassificationPromptContractError("qdt must be question-decomposition/v1 with required_leaf_questions")

    contexts_by_leaf = _dicts_by_leaf(retrieval_packet.get("leaf_query_contexts"))
    results_by_leaf = _dicts_by_leaf(retrieval_packet.get("leaf_retrieval_results"))
    certificates_by_leaf = _dicts_by_leaf(retrieval_packet.get("leaf_research_sufficiency_certificates"))
    coverage_by_ref = {
        str(item["coverage_id"]): item
        for item in retrieval_packet.get("retrieval_breadth_coverage_slices", [])
        if isinstance(item, dict) and _is_non_empty_string(item.get("coverage_id"))
    }
    profiles_by_ref = {
        str(item["profile_id"]): item
        for item in retrieval_packet.get("retrieval_breadth_profiles", [])
        if isinstance(item, dict) and _is_non_empty_string(item.get("profile_id"))
    }

    flattened_leaves: list[dict[str, Any]] = []
    missing: list[str] = []
    for leaf in leaves:
        if not isinstance(leaf, dict) or not _is_non_empty_string(leaf.get("leaf_id")):
            missing.append("invalid_leaf")
            continue
        leaf_id = str(leaf["leaf_id"])
        context = contexts_by_leaf.get(leaf_id)
        result = results_by_leaf.get(leaf_id)
        certificate = certificates_by_leaf.get(leaf_id)
        if not isinstance(context, dict):
            missing.append(f"{leaf_id}:missing_query_context")
        if not isinstance(result, dict):
            missing.append(f"{leaf_id}:missing_retrieval_result")
        if not isinstance(certificate, dict):
            missing.append(f"{leaf_id}:missing_sufficiency_certificate")
            certificate = {}
        elif certificate.get("classification_dispatch_allowed") is not True:
            missing.append(f"{leaf_id}:certificate_not_allowed")

        sufficiency = _compact_sufficiency_requirements(leaf, context)
        breadth_coverage_ref = certificate.get("breadth_coverage_ref") if isinstance(certificate, dict) else None
        breadth_profile_ref = (
            (context or {}).get("breadth_profile_ref")
            or sufficiency.get("retrieval_breadth_profile_ref")
            or sufficiency.get("breadth_profile_ref")
        )
        flattened_leaves.append(
            {
                "leaf_id": leaf_id,
                "parent_branch_id": leaf.get("parent_branch_id"),
                "question_text": leaf.get("question_text"),
                "purpose": leaf.get("purpose"),
                "static_information_weight": _leaf_static_weight(leaf),
                "condition_scope": leaf.get("leaf_condition_scope") or (context or {}).get("condition_scope"),
                "sufficiency_requirements": sufficiency,
                "retrieval_sufficiency_certificate_ref": certificate.get("certificate_id"),
                "retrieval_sufficiency_certificate_status": certificate.get("status"),
                "retrieval_breadth_profile_ref": breadth_profile_ref,
                "retrieval_breadth_profile_status": "present" if breadth_profile_ref in profiles_by_ref else "missing",
                "retrieval_breadth_coverage_ref": breadth_coverage_ref,
                "retrieval_breadth_coverage_status": (
                    "present" if _is_non_empty_string(breadth_coverage_ref) and breadth_coverage_ref in coverage_by_ref else "missing"
                ),
                "assigned_evidence_refs": _compact_assigned_evidence_refs(result, certificate),
                "required_output_refs": {
                    "sidecar_contract_ref": output_contract_ref,
                    "classification_contract_ref": classification_contract_ref,
                    "coverage_contract_ref": coverage_contract_ref,
                },
            }
        )

    if missing:
        raise ClassificationPromptContractError("prompt contract missing required leaf inputs: " + ", ".join(sorted(missing)))

    if model_execution_context:
        resolved_model_context = copy.deepcopy(model_execution_context)
    else:
        resolved_model_context = resolve_researcher_leaf_nli_model_context(
            model_lane_policy_path=model_lane_policy_path,
            prompt_template_id=RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
            prompt_template_sha256=RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
            sidecar_schema_version=RESEARCHER_SIDECAR_SCHEMA_VERSION,
            classification_output_schema_version=RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
        )
    model_validation = validate_researcher_model_execution_context(resolved_model_context)
    if not model_validation.valid:
        raise ClassificationPromptContractError(
            "model_execution_context invalid: " + "; ".join(model_validation.errors)
        )

    context_payload = {
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "macro_question": qdt.get("macro_question"),
        "market_constraints": {
            "read_only": True,
            "market_id": qdt.get("market_id"),
            "market_reality_constraints_digest": qdt.get("market_reality_constraints_digest"),
            "policy_context_ref": retrieval_packet.get("policy_context_ref"),
            "source_cutoff_timestamp": retrieval_packet.get("source_cutoff_timestamp"),
            "forecast_timestamp": retrieval_packet.get("forecast_timestamp"),
        },
        "flattened_required_leaves": flattened_leaves,
        "retrieval_dispatch_gate": {
            "classification_dispatch_status": dispatch_status,
            "all_required_leaves_certified": dispatch_summary.get("all_required_leaves_certified"),
            "leaf_certificate_refs": list(dispatch_summary.get("leaf_certificate_refs", [])),
        },
        "output_sidecar_contract_refs": {
            "sidecar_contract_ref": output_contract_ref,
            "classification_contract_ref": classification_contract_ref,
            "coverage_contract_ref": coverage_contract_ref,
        },
        "model_execution_context": resolved_model_context,
        "authority_boundary": {
            "researcher_work_type": "evidence_classification_not_forecasting",
            "forecast_authority": False,
            "probability_authority": False,
            "fair_value_authority": False,
            "interval_authority": False,
            "decision_authority": False,
            "scae_authority": False,
        },
        "forbidden_output_fields": list(FORBIDDEN_OUTPUT_FIELDS),
        "forbidden_context_ref_patterns": list(FORBIDDEN_CONTEXT_REF_PATTERNS),
    }
    prompt_text = _render_prompt_text(context_payload)
    contract_seed = {
        "template_sha256": RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
        "context_payload": context_payload,
        "prompt_text_sha256": _prefixed_sha256(prompt_text),
    }
    contract = {
        "artifact_type": "researcher_nli_prompt_contract",
        "schema_version": RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION,
        "feature_id": "CLS-001",
        "builder_version": CLS_001_CONTRACT_BUILDER_VERSION,
        "prompt_contract_id": _sha_id("researcher-nli-prompt-contract", contract_seed),
        "prompt_contract_digest": _prefixed_sha256(contract_seed),
        "schema_metadata": {
            "prompt_contract_schema_version": RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION,
            "sidecar_schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
            "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
            "coverage_proof_schema_version": RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
        },
        "prompt_template": {
            "prompt_template_id": RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
            "prompt_template_version": RESEARCHER_NLI_PROMPT_TEMPLATE_VERSION,
            "prompt_template_sha256": RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256,
        },
        "model_execution_context": resolved_model_context,
        "context_payload": context_payload,
        "prompt_text": prompt_text,
        "prompt_text_sha256": _prefixed_sha256(prompt_text),
        "scope_boundaries": {
            "implements": ["CLS-001", "MODEL-003"],
            "not_implemented": ["CLS-006", "CLS-007", "CLS-008", "CLS-002", "CLS-003", "CLS-004", "CLS-005", "VER-001", "VER-002", "VER-003", "VER-004", "SCAE"],
        },
    }
    validation = validate_researcher_nli_prompt_contract(contract)
    if not validation.valid:
        raise ClassificationPromptContractError("; ".join(validation.errors))
    return contract


def validate_researcher_nli_prompt_contract(contract: Any) -> ClassificationPromptValidationResult:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ClassificationPromptValidationResult(False, ("contract must be an object",))
    if contract.get("artifact_type") != "researcher_nli_prompt_contract":
        errors.append("artifact_type must be researcher_nli_prompt_contract")
    if contract.get("schema_version") != RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION}")
    if contract.get("feature_id") != "CLS-001":
        errors.append("feature_id must be CLS-001")

    template = contract.get("prompt_template")
    if not isinstance(template, dict):
        errors.append("prompt_template must be an object")
        template = {}
    else:
        if template.get("prompt_template_id") != RESEARCHER_NLI_PROMPT_TEMPLATE_ID:
            errors.append("prompt_template_id is invalid")
        if template.get("prompt_template_sha256") != RESEARCHER_NLI_PROMPT_TEMPLATE_SHA256:
            errors.append("prompt_template_sha256 is invalid")

    metadata = contract.get("schema_metadata")
    if not isinstance(metadata, dict):
        errors.append("schema_metadata must be an object")
    else:
        expected = {
            "prompt_contract_schema_version": RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION,
            "sidecar_schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
            "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
            "coverage_proof_schema_version": RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
        }
        for field, value in expected.items():
            if metadata.get(field) != value:
                errors.append(f"schema_metadata.{field} must be {value}")

    payload = contract.get("context_payload")
    if not isinstance(payload, dict):
        errors.append("context_payload must be an object")
        payload = {}
    gate = payload.get("retrieval_dispatch_gate")
    if not isinstance(gate, dict):
        errors.append("context_payload.retrieval_dispatch_gate must be an object")
    elif gate.get("classification_dispatch_status") != ALLOWED_CLASSIFICATION_DISPATCH_STATUS:
        errors.append("retrieval dispatch gate must be allowed")

    if not _is_non_empty_string(payload.get("macro_question")):
        errors.append("context_payload.macro_question is required")
    constraints = payload.get("market_constraints")
    if not isinstance(constraints, dict) or constraints.get("read_only") is not True:
        errors.append("market_constraints must be read_only")

    leaves = payload.get("flattened_required_leaves")
    if not isinstance(leaves, list) or not leaves:
        errors.append("flattened_required_leaves must be a non-empty list")
    else:
        for idx, leaf in enumerate(leaves):
            if not isinstance(leaf, dict):
                errors.append(f"flattened_required_leaves[{idx}] must be an object")
                continue
            if not _is_non_empty_string(leaf.get("leaf_id")):
                errors.append(f"flattened_required_leaves[{idx}].leaf_id is required")
            if not _is_non_empty_string(leaf.get("condition_scope")):
                errors.append(f"flattened_required_leaves[{idx}].condition_scope is required")
            if not _is_non_empty_string(leaf.get("retrieval_sufficiency_certificate_ref")):
                errors.append(f"flattened_required_leaves[{idx}] missing retrieval_sufficiency_certificate_ref")
            if leaf.get("retrieval_breadth_profile_status") != "present":
                errors.append(f"flattened_required_leaves[{idx}] missing retrieval breadth profile ref")
            if leaf.get("retrieval_breadth_coverage_status") != "present":
                errors.append(f"flattened_required_leaves[{idx}] missing retrieval breadth coverage ref")
            if not isinstance(leaf.get("assigned_evidence_refs"), list):
                errors.append(f"flattened_required_leaves[{idx}].assigned_evidence_refs must be a list")
            sufficiency = leaf.get("sufficiency_requirements")
            if not isinstance(sufficiency, dict):
                errors.append(f"flattened_required_leaves[{idx}].sufficiency_requirements must be an object")
            elif not _is_non_empty_string(sufficiency.get("requirement_ref")):
                errors.append(f"flattened_required_leaves[{idx}].sufficiency_requirements.requirement_ref is required")

    output_refs = payload.get("output_sidecar_contract_refs")
    if not isinstance(output_refs, dict):
        errors.append("output_sidecar_contract_refs must be an object")
    else:
        for field in ("sidecar_contract_ref", "classification_contract_ref", "coverage_contract_ref"):
            if not _is_non_empty_string(output_refs.get(field)):
                errors.append(f"output_sidecar_contract_refs.{field} is required")

    model_context = contract.get("model_execution_context")
    payload_model_context = payload.get("model_execution_context") if isinstance(payload, dict) else None
    if model_context != payload_model_context:
        errors.append("model_execution_context must match context_payload.model_execution_context")
    model_validation = validate_researcher_model_execution_context(model_context)
    if not model_validation.valid:
        errors.extend(f"model_execution_context.{error}" for error in model_validation.errors)
    elif isinstance(template, dict):
        if model_context.get("prompt_template_id") != template.get("prompt_template_id"):
            errors.append("model_execution_context.prompt_template_id must match prompt_template")
        if model_context.get("prompt_template_sha256") != template.get("prompt_template_sha256"):
            errors.append("model_execution_context.prompt_template_sha256 must match prompt_template")

    authority = payload.get("authority_boundary")
    if not isinstance(authority, dict):
        errors.append("authority_boundary must be an object")
    else:
        for field in (
            "forecast_authority",
            "probability_authority",
            "fair_value_authority",
            "interval_authority",
            "decision_authority",
            "scae_authority",
        ):
            if authority.get(field) is not False:
                errors.append(f"authority_boundary.{field} must be false")
        if authority.get("researcher_work_type") != "evidence_classification_not_forecasting":
            errors.append("researcher_work_type must be evidence_classification_not_forecasting")

    forbidden_fields = payload.get("forbidden_output_fields")
    if not isinstance(forbidden_fields, list) or sorted(forbidden_fields) != sorted(FORBIDDEN_OUTPUT_FIELDS):
        errors.append("forbidden_output_fields must match CLS-001 no-probability contract")
    forbidden_refs = payload.get("forbidden_context_ref_patterns")
    if not isinstance(forbidden_refs, list) or sorted(forbidden_refs) != sorted(FORBIDDEN_CONTEXT_REF_PATTERNS):
        errors.append("forbidden_context_ref_patterns must match CLS-001 context denylist")

    prompt_text = contract.get("prompt_text")
    if not _is_non_empty_string(prompt_text):
        errors.append("prompt_text is required")
    elif contract.get("prompt_text_sha256") != _prefixed_sha256(prompt_text):
        errors.append("prompt_text_sha256 does not match prompt_text")

    return ClassificationPromptValidationResult(not errors, tuple(errors))


def _normalized_field_name(value: Any) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _is_sha256_ref(value: Any) -> bool:
    if not _is_non_empty_string(value):
        return False
    text = str(value)
    return text.startswith("sha256:") and len(text) == 71 and all(ch in "0123456789abcdef" for ch in text[7:])


def _string_refs_from(value: dict[str, Any], *fields: str) -> list[str]:
    refs: list[str] = []
    for field in fields:
        raw = value.get(field)
        if _is_non_empty_string(raw):
            refs.append(str(raw))
        elif isinstance(raw, list):
            for item in raw:
                if _is_non_empty_string(item):
                    refs.append(str(item))
                elif isinstance(item, dict):
                    for key in ("evidence_ref", "supplemental_evidence_ref", "artifact_ref", "ref"):
                        if _is_non_empty_string(item.get(key)):
                            refs.append(str(item[key]))
                            break
    return refs


def _classification_evidence_refs(classification: dict[str, Any]) -> list[str]:
    return _string_refs_from(
        classification,
        "evidence_ref",
        "retrieval_evidence_ref",
        "supplemental_evidence_ref",
        "evidence_refs",
        "retrieval_evidence_refs",
        "supplemental_evidence_refs",
    )


def _unanswerability_block(classification: dict[str, Any]) -> dict[str, Any]:
    block = classification.get("unanswerability")
    if isinstance(block, dict):
        return block
    block = classification.get("unanswerable_classification")
    if isinstance(block, dict):
        return block
    return {}


def _unanswerability_provenance_refs(classification: dict[str, Any]) -> list[str]:
    block = _unanswerability_block(classification)
    refs = _string_refs_from(classification, "provenance_refs", "unanswerability_provenance_refs")
    refs.extend(_string_refs_from(block, "provenance_refs", "retrieval_gap_refs", "exhausted_expansion_refs"))
    return refs


def _unanswerability_gap_refs(classification: dict[str, Any]) -> list[str]:
    block = _unanswerability_block(classification)
    refs = _string_refs_from(
        classification,
        "retrieval_gap_refs",
        "source_gap_flags",
        "exhausted_expansion_refs",
        "structural_unanswerability_refs",
        "requirements_unanswered",
    )
    refs.extend(
        _string_refs_from(
            block,
            "retrieval_gap_refs",
            "source_gap_flags",
            "exhausted_expansion_refs",
            "structural_unanswerability_refs",
            "requirements_unanswered",
        )
    )
    return refs


def _unanswerability_rationale(classification: dict[str, Any]) -> str:
    block = _unanswerability_block(classification)
    for value in (
        classification.get("unanswerability_rationale"),
        classification.get("rationale"),
        block.get("rationale"),
    ):
        if _is_non_empty_string(value):
            return str(value)
    return ""


def _collect_forbidden_sidecar_fields(value: Any, errors: list[str], path: str = "sidecar") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_field_name(key)
            forbidden = False
            if (
                path.endswith(".authority_boundary")
                and normalized in ALLOWED_FALSE_AUTHORITY_BOUNDARY_FIELDS
                and child is False
            ):
                forbidden = False
            elif normalized == "classification_confidence":
                forbidden = False
            elif normalized in FORBIDDEN_V2_SIDECAR_FIELDS:
                forbidden = True
            elif any(fragment in normalized for fragment in FORBIDDEN_V2_SIDECAR_KEY_FRAGMENTS):
                forbidden = True
            elif normalized.endswith("_interval") or normalized.endswith("_odds"):
                forbidden = True
            elif normalized in {"confidence", "confidence_score"}:
                forbidden = True
            if forbidden:
                errors.append(f"{path}.{key} is forbidden in {RESEARCHER_SIDECAR_SCHEMA_VERSION}")
            _collect_forbidden_sidecar_fields(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _collect_forbidden_sidecar_fields(child, errors, f"{path}[{idx}]")


def _required_leaf_ids(qdt: Any, errors: list[str]) -> set[str]:
    if not isinstance(qdt, dict):
        errors.append("qdt must be an object")
        return set()
    if qdt.get("schema_version") != "question-decomposition/v1":
        errors.append("qdt.schema_version must be question-decomposition/v1")
    leaves = qdt.get("required_leaf_questions")
    if not isinstance(leaves, list) or not leaves:
        errors.append("qdt.required_leaf_questions must be a non-empty list")
        return set()
    ids: set[str] = set()
    for idx, leaf in enumerate(leaves):
        if not isinstance(leaf, dict) or not _is_non_empty_string(leaf.get("leaf_id")):
            errors.append(f"qdt.required_leaf_questions[{idx}].leaf_id is required")
            continue
        ids.add(str(leaf["leaf_id"]))
    return ids


def _canonical_classification_rows(classifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [copy.deepcopy(item) for item in classifications]
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("leaf_id", "")),
            str(item.get("classification_id", "")),
            _canonical_json(item),
        ),
    )


def compute_classification_matrix_digest(classifications: list[dict[str, Any]]) -> str:
    """Return the deterministic digest CLS-002 requires before CLS-003 materializes rows."""

    return _prefixed_sha256(
        {
            "schema_version": "classification-matrix-digest/v1",
            "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
            "classifications": _canonical_classification_rows(classifications),
        }
    )


def _sidecar_digest_payload(sidecar: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(sidecar)
    payload.pop("sidecar_digest", None)
    return payload


def compute_researcher_sidecar_digest(sidecar: dict[str, Any]) -> str:
    return _prefixed_sha256(_sidecar_digest_payload(sidecar))


def _validate_model_execution_context(
    context: Any,
    errors: list[str],
    path: str,
    *,
    expected_hash: str | None = None,
) -> None:
    if not isinstance(context, dict):
        errors.append(f"{path} must be an object")
        return
    for field in (
        "model_lane_id",
        "resolved_model_id",
        "model_policy_ref",
        "prompt_template_id",
        "prompt_template_sha256",
        "sidecar_schema_version",
        "classification_output_schema_version",
    ):
        if not _is_non_empty_string(context.get(field)):
            errors.append(f"{path}.{field} is required")
    if context.get("model_lane_id") != RESEARCHER_LEAF_NLI_MODEL_LANE_ID:
        errors.append(f"{path}.model_lane_id must be {RESEARCHER_LEAF_NLI_MODEL_LANE_ID}")
    if context.get("prompt_template_id") != RESEARCHER_NLI_PROMPT_TEMPLATE_ID:
        errors.append(f"{path}.prompt_template_id must be {RESEARCHER_NLI_PROMPT_TEMPLATE_ID}")
    if not _is_sha256_ref(context.get("prompt_template_sha256")):
        errors.append(f"{path}.prompt_template_sha256 must be a sha256 ref")
    if context.get("sidecar_schema_version") != RESEARCHER_SIDECAR_SCHEMA_VERSION:
        errors.append(f"{path}.sidecar_schema_version must be {RESEARCHER_SIDECAR_SCHEMA_VERSION}")
    if context.get("classification_output_schema_version") != RESEARCHER_CLASSIFICATION_SCHEMA_VERSION:
        errors.append(
            f"{path}.classification_output_schema_version must be {RESEARCHER_CLASSIFICATION_SCHEMA_VERSION}"
        )
    if expected_hash and _prefixed_sha256(context) != expected_hash:
        errors.append(f"{path} does not match model_execution_context_sha256")


def _validate_answer_value_extraction(value: Any, errors: list[str], path: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object when present")
        return
    status = value.get("normalization_status")
    if status not in ALLOWED_VALUE_NORMALIZATION_STATUSES:
        errors.append(f"{path}.normalization_status is invalid")


def _validate_evidence_quality_dimensions(value: Any, errors: list[str], path: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    expected = {
        "source_authority": ALLOWED_SOURCE_AUTHORITY_VALUES,
        "directness": ALLOWED_DIRECTNESS_VALUES,
        "recency": ALLOWED_RECENCY_VALUES,
        "specificity": ALLOWED_SPECIFICITY_VALUES,
    }
    for field, allowed in expected.items():
        if value.get(field) not in allowed:
            errors.append(f"{path}.{field} is invalid")


def _validate_coverage_proof(
    proof: Any,
    errors: list[str],
    path: str,
    required_leaf_ids: set[str],
) -> None:
    if not isinstance(proof, dict):
        errors.append(f"{path} must be an object")
        return
    if proof.get("schema_version") != RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION}")
    for field in (
        "coverage_proof_id",
        "leaf_id",
        "research_sufficiency_certificate_ref",
        "retrieval_breadth_coverage_ref",
    ):
        if not _is_non_empty_string(proof.get(field)):
            errors.append(f"{path}.{field} is required")
    if _is_non_empty_string(proof.get("leaf_id")) and str(proof["leaf_id"]) not in required_leaf_ids:
        errors.append(f"{path}.leaf_id is not a required QDT leaf")
    if proof.get("machine_readability_status") != "schema_valid":
        errors.append(f"{path}.machine_readability_status must be schema_valid")
    for field in (
        "evidence_refs_assigned",
        "evidence_refs_reviewed",
        "source_class_ids_reviewed",
        "claim_family_ids_reviewed",
        "source_family_ids_reviewed",
        "requirements_reviewed",
        "requirements_answered",
        "requirements_unanswered",
        "required_value_fields_extracted",
        "required_negative_checks_completed",
        "source_gap_flags",
    ):
        if not isinstance(proof.get(field), list):
            errors.append(f"{path}.{field} must be a list")


def _validate_classification(
    classification: Any,
    errors: list[str],
    path: str,
    required_leaf_ids: set[str],
    proofs_by_id: dict[str, dict[str, Any]],
    top_model_context_hash: str,
    top_model_context_ref: str,
) -> str | None:
    if not isinstance(classification, dict):
        errors.append(f"{path} must be an object")
        return None
    if classification.get("schema_version") != RESEARCHER_CLASSIFICATION_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version must be {RESEARCHER_CLASSIFICATION_SCHEMA_VERSION}")
    for field in ("classification_id", "leaf_id", "research_sufficiency_certificate_ref", "coverage_proof_ref"):
        if not _is_non_empty_string(classification.get(field)):
            errors.append(f"{path}.{field} is required")

    leaf_id = str(classification.get("leaf_id", ""))
    if leaf_id and leaf_id not in required_leaf_ids:
        errors.append(f"{path}.leaf_id is not a required QDT leaf")

    scope = classification.get("leaf_condition_scope")
    if scope not in ALLOWED_LEAF_CONDITION_SCOPES:
        errors.append(f"{path}.leaf_condition_scope is invalid")
    impact_direction = classification.get("impact_direction")
    if impact_direction not in ALLOWED_IMPACT_DIRECTIONS:
        errors.append(f"{path}.impact_direction is invalid")
    evidence_strength = classification.get("evidence_strength")
    if evidence_strength not in ALLOWED_EVIDENCE_STRENGTHS:
        errors.append(f"{path}.evidence_strength is invalid")
    if classification.get("classification_confidence") not in ALLOWED_CLASSIFICATION_CONFIDENCES:
        errors.append(f"{path}.classification_confidence is invalid")

    model_context_ref = classification.get("model_execution_context_ref", top_model_context_ref)
    if not _is_non_empty_string(model_context_ref):
        errors.append(f"{path}.model_execution_context_ref is required")
    elif model_context_ref != top_model_context_ref:
        errors.append(f"{path}.model_execution_context_ref must match sidecar.model_execution_context_ref")
    model_context_hash = classification.get("model_execution_context_sha256", top_model_context_hash)
    if model_context_hash != top_model_context_hash:
        errors.append(f"{path}.model_execution_context_sha256 must match sidecar.model_execution_context_sha256")
    _validate_model_execution_context(
        classification.get("model_execution_context"),
        errors,
        f"{path}.model_execution_context",
        expected_hash=top_model_context_hash,
    )

    evidence_refs = _classification_evidence_refs(classification)
    if not evidence_refs:
        errors.append(f"{path} must include retrieval evidence refs or supplemental evidence refs")
    _validate_answer_value_extraction(classification.get("answer_value_extraction"), errors, f"{path}.answer_value_extraction")
    _validate_evidence_quality_dimensions(
        classification.get("evidence_quality_dimensions"),
        errors,
        f"{path}.evidence_quality_dimensions",
    )
    if not isinstance(classification.get("provenance_refs", []), list):
        errors.append(f"{path}.provenance_refs must be a list")

    is_unanswerable = evidence_strength == "unanswerable"
    if is_unanswerable:
        if impact_direction != "neutral":
            errors.append(f"{path}.impact_direction must be neutral for unanswerable classifications")
        if not _unanswerability_rationale(classification):
            errors.append(f"{path}.unanswerability.rationale is required")
        if not _unanswerability_provenance_refs(classification):
            errors.append(f"{path}.unanswerability.provenance_refs is required")
        if not _unanswerability_gap_refs(classification):
            errors.append(f"{path}.unanswerability gap refs or flags are required")

    proof_ref = classification.get("coverage_proof_ref")
    proof = proofs_by_id.get(str(proof_ref)) if _is_non_empty_string(proof_ref) else None
    if not proof:
        errors.append(f"{path}.coverage_proof_ref does not match a coverage proof")
        return leaf_id or None
    if proof.get("leaf_id") != leaf_id:
        errors.append(f"{path}.coverage_proof_ref points to a different leaf")
    if proof.get("research_sufficiency_certificate_ref") != classification.get("research_sufficiency_certificate_ref"):
        errors.append(f"{path}.coverage_proof_ref has a different research_sufficiency_certificate_ref")
    reviewed_refs = set(
        _string_refs_from(
            proof,
            "evidence_refs_reviewed",
            "supplemental_evidence_refs_reviewed",
            "provenance_refs_reviewed",
        )
    )
    missing_reviewed = sorted(set(evidence_refs) - reviewed_refs)
    if missing_reviewed:
        errors.append(f"{path}.coverage_proof_ref missing reviewed refs: {', '.join(missing_reviewed)}")
    if is_unanswerable and proof.get("structural_unanswerability_acknowledged") is not True:
        errors.append(f"{path}.coverage_proof_ref must acknowledge structural unanswerability")
    return leaf_id or None


def build_researcher_sidecar_v2(
    *,
    qdt: dict[str, Any],
    required_question_classifications: list[dict[str, Any]],
    coverage_proofs: list[dict[str, Any]],
    model_execution_context_ref: str,
    model_execution_context: dict[str, Any],
    market_constraints_digest: str | None = None,
    supplemental_evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic CLS-002 sidecar artifact around supplied rows."""

    if not isinstance(required_question_classifications, list):
        raise ResearcherSidecarError("required_question_classifications must be a list")
    if not isinstance(coverage_proofs, list):
        raise ResearcherSidecarError("coverage_proofs must be a list")
    model_context_sha256 = _prefixed_sha256(model_execution_context)
    classifications = []
    for item in required_question_classifications:
        classification = copy.deepcopy(item)
        classification.setdefault("schema_version", RESEARCHER_CLASSIFICATION_SCHEMA_VERSION)
        classification.setdefault("model_execution_context_ref", model_execution_context_ref)
        classification.setdefault("model_execution_context_sha256", model_context_sha256)
        classification.setdefault("model_execution_context", copy.deepcopy(model_execution_context))
        classification.setdefault(
            "classification_id",
            _sha_id(
                "researcher-classification",
                {
                    "case_id": qdt.get("case_id"),
                    "dispatch_id": qdt.get("dispatch_id"),
                    "leaf_id": classification.get("leaf_id"),
                    "evidence_refs": _classification_evidence_refs(classification),
                    "impact_direction": classification.get("impact_direction"),
                    "evidence_strength": classification.get("evidence_strength"),
                },
            ),
        )
        classifications.append(classification)

    proofs = []
    for item in coverage_proofs:
        proof = copy.deepcopy(item)
        proof.setdefault("schema_version", RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION)
        proofs.append(proof)

    matrix_digest = compute_classification_matrix_digest(classifications)
    market_digest = (
        market_constraints_digest
        or qdt.get("market_reality_constraints_digest")
        or (qdt.get("market_context") if isinstance(qdt.get("market_context"), dict) else {}).get(
            "market_reality_constraints_digest"
        )
    )
    seed = {
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "market_constraints_digest": market_digest,
        "classification_matrix_digest": matrix_digest,
        "model_execution_context_sha256": model_context_sha256,
        "classification_ids": [item.get("classification_id") for item in _canonical_classification_rows(classifications)],
    }
    sidecar = {
        "artifact_type": "researcher_sidecar",
        "schema_version": RESEARCHER_SIDECAR_SCHEMA_VERSION,
        "feature_id": "CLS-002",
        "validator_version": CLS_002_SIDECAR_VALIDATOR_VERSION,
        "sidecar_id": _sha_id("researcher-sidecar", seed),
        "case_id": qdt.get("case_id"),
        "dispatch_id": qdt.get("dispatch_id"),
        "market_constraints_digest": market_digest,
        "classification_matrix_digest": matrix_digest,
        "model_execution_context_ref": model_execution_context_ref,
        "model_execution_context_sha256": model_context_sha256,
        "sidecar_contract_ref": "schema:researcher-sidecar/v2",
        "classification_contract_ref": "schema:researcher-classification/v1",
        "coverage_contract_ref": "schema:researcher-coverage-proof/v1",
        "required_question_classifications": classifications,
        "coverage_proofs": proofs,
        "supplemental_evidence_refs": list(supplemental_evidence_refs or []),
        "scope_boundaries": {
            "implements": ["CLS-002"],
            "not_implemented": ["CLS-003", "CLS-006", "CLS-007", "MODEL-003", "VER", "SCAE"],
        },
    }
    sidecar["sidecar_digest"] = compute_researcher_sidecar_digest(sidecar)
    validation = validate_researcher_sidecar_v2(sidecar, qdt)
    if not validation.valid:
        raise ResearcherSidecarError("; ".join(validation.errors))
    return sidecar


def validate_researcher_sidecar_v2(sidecar: Any, qdt: Any) -> ResearcherSidecarValidationResult:
    """Validate the CLS-002 no-probability researcher sidecar contract."""

    errors: list[str] = []
    if not isinstance(sidecar, dict):
        return ResearcherSidecarValidationResult(False, ("sidecar must be an object",))
    _collect_forbidden_sidecar_fields(sidecar, errors)
    required_leaf_ids = _required_leaf_ids(qdt, errors)

    if sidecar.get("artifact_type") != "researcher_sidecar":
        errors.append("artifact_type must be researcher_sidecar")
    if sidecar.get("schema_version") != RESEARCHER_SIDECAR_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RESEARCHER_SIDECAR_SCHEMA_VERSION}")
    if sidecar.get("sidecar_contract_ref") != "schema:researcher-sidecar/v2":
        errors.append("sidecar_contract_ref must be schema:researcher-sidecar/v2")
    if sidecar.get("classification_contract_ref") != "schema:researcher-classification/v1":
        errors.append("classification_contract_ref must be schema:researcher-classification/v1")
    if sidecar.get("coverage_contract_ref") != "schema:researcher-coverage-proof/v1":
        errors.append("coverage_contract_ref must be schema:researcher-coverage-proof/v1")
    for field in ("sidecar_id", "case_id", "dispatch_id", "market_constraints_digest"):
        if not _is_non_empty_string(sidecar.get(field)):
            errors.append(f"{field} is required")

    if isinstance(qdt, dict):
        if _is_non_empty_string(qdt.get("case_id")) and sidecar.get("case_id") != qdt.get("case_id"):
            errors.append("case_id must match qdt.case_id")
        if _is_non_empty_string(qdt.get("dispatch_id")) and sidecar.get("dispatch_id") != qdt.get("dispatch_id"):
            errors.append("dispatch_id must match qdt.dispatch_id")
        qdt_market_digest = qdt.get("market_reality_constraints_digest")
        if not _is_non_empty_string(qdt_market_digest) and isinstance(qdt.get("market_context"), dict):
            qdt_market_digest = qdt["market_context"].get("market_reality_constraints_digest")
        if _is_non_empty_string(qdt_market_digest) and sidecar.get("market_constraints_digest") != qdt_market_digest:
            errors.append("market_constraints_digest must match qdt market constraints digest")

    model_context_ref = sidecar.get("model_execution_context_ref")
    if not _is_non_empty_string(model_context_ref):
        errors.append("model_execution_context_ref is required")
        model_context_ref = ""
    model_context_hash = sidecar.get("model_execution_context_sha256")
    if not _is_sha256_ref(model_context_hash):
        errors.append("model_execution_context_sha256 must be a sha256 ref")
        model_context_hash = ""
    if isinstance(sidecar.get("model_execution_context"), dict) and model_context_hash:
        _validate_model_execution_context(
            sidecar["model_execution_context"],
            errors,
            "model_execution_context",
            expected_hash=str(model_context_hash),
        )

    classifications = sidecar.get("required_question_classifications")
    if not isinstance(classifications, list) or not classifications:
        errors.append("required_question_classifications must be a non-empty list")
        classifications = []
    proofs = sidecar.get("coverage_proofs")
    if not isinstance(proofs, list) or not proofs:
        errors.append("coverage_proofs must be a non-empty list")
        proofs = []

    proofs_by_id: dict[str, dict[str, Any]] = {}
    for idx, proof in enumerate(proofs):
        _validate_coverage_proof(proof, errors, f"coverage_proofs[{idx}]", required_leaf_ids)
        if isinstance(proof, dict) and _is_non_empty_string(proof.get("coverage_proof_id")):
            proof_id = str(proof["coverage_proof_id"])
            if proof_id in proofs_by_id:
                errors.append(f"coverage_proofs[{idx}].coverage_proof_id is duplicated")
            proofs_by_id[proof_id] = proof

    covered_leaf_ids: set[str] = set()
    for idx, classification in enumerate(classifications):
        leaf_id = _validate_classification(
            classification,
            errors,
            f"required_question_classifications[{idx}]",
            required_leaf_ids,
            proofs_by_id,
            str(model_context_hash),
            str(model_context_ref),
        )
        if leaf_id:
            covered_leaf_ids.add(leaf_id)

    missing_leaf_ids = sorted(required_leaf_ids - covered_leaf_ids)
    if missing_leaf_ids:
        errors.append("classification_coverage_missing: " + ", ".join(missing_leaf_ids))

    matrix_digest = sidecar.get("classification_matrix_digest")
    if not _is_sha256_ref(matrix_digest):
        errors.append("classification_matrix_digest must be a sha256 ref")
    elif isinstance(classifications, list):
        expected_matrix_digest = compute_classification_matrix_digest(
            [item for item in classifications if isinstance(item, dict)]
        )
        if matrix_digest != expected_matrix_digest:
            errors.append("classification_matrix_digest does not match classifications")

    sidecar_digest = sidecar.get("sidecar_digest")
    if not _is_sha256_ref(sidecar_digest):
        errors.append("sidecar_digest must be a sha256 ref")
    elif sidecar_digest != compute_researcher_sidecar_digest(sidecar):
        errors.append("sidecar_digest does not match sidecar payload")

    return ResearcherSidecarValidationResult(not errors, tuple(errors))


def validate_sidecar_v2(sidecar: Any, qdt: Any) -> ResearcherSidecarValidationResult:
    """Compatibility alias matching the Session 4 plan pseudocode."""

    return validate_researcher_sidecar_v2(sidecar, qdt)
