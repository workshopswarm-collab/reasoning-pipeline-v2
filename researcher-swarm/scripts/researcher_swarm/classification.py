"""CLS-001 researcher NLI classification prompt contract helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


RESEARCHER_NLI_PROMPT_CONTRACT_SCHEMA_VERSION = "researcher-nli-prompt-contract/v1"
RESEARCHER_NLI_PROMPT_TEMPLATE_ID = "researcher-leaf-nli/v1"
RESEARCHER_NLI_PROMPT_TEMPLATE_VERSION = "cls-001-researcher-leaf-nli/v1"
RESEARCHER_SIDECAR_SCHEMA_VERSION = "researcher-sidecar/v2"
RESEARCHER_CLASSIFICATION_SCHEMA_VERSION = "researcher-classification/v1"
RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION = "researcher-coverage-proof/v1"
CLS_001_CONTRACT_BUILDER_VERSION = "ads-cls-001-researcher-nli-prompt-contract/v1"

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
        "context_payload": context_payload,
        "prompt_text": prompt_text,
        "prompt_text_sha256": _prefixed_sha256(prompt_text),
        "scope_boundaries": {
            "implements": ["CLS-001"],
            "not_implemented": ["CLS-006", "CLS-007", "CLS-008", "CLS-002", "CLS-003", "CLS-004", "CLS-005", "MODEL-003", "VER-001", "VER-002", "VER-003", "VER-004", "SCAE"],
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
