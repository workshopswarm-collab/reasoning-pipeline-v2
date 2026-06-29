#!/usr/bin/env python3
"""ADS Decomposer-owned QDT runtime entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT / "orchestrator" / "scripts"))

from predquant.ads_handoff import canonical_json  # noqa: E402
from predquant.amrg import (  # noqa: E402
    build_amrg_decomposer_context,
    validate_amrg_decomposer_context,
)
from ads_decomposer.handoff import validate_decomposer_handoff  # noqa: E402
from ads_decomposer.model_runtime import (  # noqa: E402
    MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
    ModelRuntimeError,
    execute_model_runtime_call,
    model_execution_context_from_runtime_call,
    openclaw_codex_agent_transport_from_env,
    prefixed_sha256,
)
from ads_decomposer.qdt import (  # noqa: E402
    ALLOWED_CONDITION_SCOPES,
    ALLOWED_PURPOSES,
    ALLOWED_RESEARCH_PRIORITIES,
    COMPACT_DEFAULT_LEAF_BUDGET,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
    QDTError,
    build_qdt_candidate,
    compute_qdt_quality_checks,
    dump_question_decomposition,
    select_qdt_candidate,
    validate_question_decomposition_against_amrg_context,
    validate_question_decomposition,
)


def _load(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


Transport = Callable[[dict[str, Any]], Any]


def _load_manifest_payload(manifest_ref: dict[str, Any]) -> dict[str, Any]:
    path = manifest_ref.get("path") if isinstance(manifest_ref, dict) else None
    if not isinstance(path, str) or not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    return _load(candidate)


def _load_manifest_payloads(handoff: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = handoff.get("artifact_refs", {}) if isinstance(handoff.get("artifact_refs"), dict) else {}
    return {
        "ads_case_contract": _load_manifest_payload(refs.get("ads_case_contract", {})),
        "evidence_packet": _load_manifest_payload(refs.get("evidence_packet", {})),
        "effective_profile_context": _load_manifest_payload(refs.get("effective_profile_context", {})),
        "related_market_context": _load_manifest_payload(refs.get("related_market_context", {})),
    }


def _amrg_decomposer_context_from_payload(amrg_payload: dict[str, Any]) -> dict[str, Any] | None:
    if not amrg_payload:
        return None
    section = amrg_payload.get("amrg_decomposer_context")
    if isinstance(section, dict):
        validate_amrg_decomposer_context(section)
        return section
    if amrg_payload.get("artifact_type") in {"related_live_market_context", "no_related_context_waiver"}:
        return build_amrg_decomposer_context(amrg_payload)
    return None


def _market_temporal_state_from_handoff(
    handoff: dict[str, Any],
    *,
    case_payload: dict[str, Any] | None = None,
    evidence_payload: dict[str, Any] | None = None,
) -> str:
    market_context = handoff.get("market_context") if isinstance(handoff.get("market_context"), dict) else {}
    case_payload = case_payload or {}
    evidence_payload = evidence_payload or {}
    case_identity = case_payload.get("market_identity") if isinstance(case_payload.get("market_identity"), dict) else {}
    constraints = (
        evidence_payload.get("market_reality_constraints")
        if isinstance(evidence_payload.get("market_reality_constraints"), dict)
        else {}
    )
    raw_status = str(
        handoff.get("market_temporal_state")
        or handoff.get("resolution_status")
        or market_context.get("market_temporal_state")
        or market_context.get("resolution_status")
        or case_identity.get("resolution_status")
        or constraints.get("resolution_status")
        or constraints.get("source_of_truth_status")
        or ""
    ).lower()
    if any(term in raw_status for term in ("resolved", "settled", "closed_final", "finalized")):
        return "resolved_or_settlement_audit"
    return "unresolved"


def _slug(value: str, *, fallback: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    slug = "-".join(tokens[:4])
    return slug or fallback


def _bounded_question_text(prefix: str, question: str) -> str:
    text = " ".join(f"{prefix} {question}".split())
    return text[:280]


def build_question_specific_fixture_response(handoff: dict[str, Any]) -> dict[str, Any]:
    """Build an offline model-shaped response with question-specific leaves."""

    question = str(handoff.get("macro_question") or "the market question")
    topic = _slug(question, fallback="market")
    branches = [
        {
            "branch_id": f"branch-{topic}-resolution",
            "branch_question": _bounded_question_text("Define market-specific research coverage for the target outcome:", question),
            "branch_role": "question_specific_research_coverage",
            "dependency_group_id": f"dep-group-{topic}-resolution",
            "required_evidence_purposes": ["source_of_truth", "direct_evidence", "catalyst", "structural"],
            "leaf_ids": [
                f"leaf-{topic}-official-status",
                f"leaf-{topic}-direct-status",
                f"leaf-{topic}-driver-stage",
                f"leaf-{topic}-negative-checks",
                f"leaf-{topic}-source-quality",
                f"leaf-{topic}-material-unknowns",
            ],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1},
        },
        {
            "branch_id": f"branch-{topic}-mechanics",
            "branch_question": _bounded_question_text("Identify the market-specific rules and timing constraints for:", question),
            "branch_role": "question_specific_resolution_mechanics",
            "dependency_group_id": f"dep-group-{topic}-mechanics",
            "required_evidence_purposes": ["resolution_mechanics"],
            "leaf_ids": [f"leaf-{topic}-rules-window", f"leaf-{topic}-timing-constraints"],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1},
        },
    ]
    leaves = [
        {
            "leaf_id": f"leaf-{topic}-official-status",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("Which official, platform, or primary resolver source defines the exact YES/NO condition for:", question),
            "purpose": "source_of_truth",
            "coverage_dimension": "resolution_mechanics",
            "research_factor": "resolution_condition_and_authority",
            "research_priority": "critical",
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["official_status", "resolution_criteria"],
            "market_component_terms": [topic, "official status", "resolution criteria"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-direct-status",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("What direct pre-cutoff evidence shows the target event is observed, contradicted, or unresolved for:", question),
            "purpose": "direct_evidence",
            "coverage_dimension": "current_direct_evidence",
            "research_factor": "current_target_event_status",
            "research_priority": "high",
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["event_status", "event_timestamp"],
            "market_component_terms": [topic, "event status", "cutoff"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-driver-stage",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("Which process stage, commitment signal, or market-specific driver materially changes observability before cutoff for:", question),
            "purpose": "catalyst",
            "coverage_dimension": "key_drivers",
            "research_factor": "process_stage_and_driver_status",
            "research_priority": "high",
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["driver_status", "process_stage"],
            "market_component_terms": [topic, "driver", "process stage"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-negative-checks",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("What negative checks, blockers, or contradictions show the target event has not cleanly occurred before cutoff for:", question),
            "purpose": "direct_evidence",
            "coverage_dimension": "counterevidence_negative_checks",
            "research_factor": "counterevidence_and_blockers",
            "research_priority": "high",
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["negative_check_status", "contradiction_status"],
            "market_component_terms": [topic, "negative check", "blocker"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-source-quality",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("Are the relevant claim families independent high-quality evidence or repeated weak reports that should be collapsed for:", question),
            "purpose": "direct_evidence",
            "coverage_dimension": "source_quality",
            "research_factor": "claim_family_independence_and_source_quality",
            "research_priority": "medium",
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["source_quality", "claim_family_independence"],
            "market_component_terms": [topic, "claim family", "source quality"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-rules-window",
            "parent_branch_id": branches[1]["branch_id"],
            "question_text": _bounded_question_text("Which source hierarchy and rule clauses distinguish qualifying evidence from rumor or weak context for:", question),
            "purpose": "resolution_mechanics",
            "coverage_dimension": "resolution_mechanics",
            "research_factor": "source_hierarchy_and_qualifying_claim",
            "research_priority": "medium",
            "leaf_dependency_group_id": branches[1]["dependency_group_id"],
            "leaf_condition_scope": "shared_context",
            "required_evidence_fields": ["resolution_deadline", "rules_text"],
            "market_component_terms": [topic, "rules", "deadline"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-timing-constraints",
            "parent_branch_id": branches[1]["branch_id"],
            "question_text": _bounded_question_text("Which deadline, cutoff, and observation-window constraints govern whether evidence can count for:", question),
            "purpose": "resolution_mechanics",
            "coverage_dimension": "timing_deadline_constraints",
            "research_factor": "deadline_and_cutoff_admissibility",
            "research_priority": "medium",
            "leaf_dependency_group_id": branches[1]["dependency_group_id"],
            "leaf_condition_scope": "shared_context",
            "required_evidence_fields": ["resolution_deadline", "cutoff_window"],
            "market_component_terms": [topic, "deadline", "cutoff"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-material-unknowns",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("What material questions remain unanswered after retrieval, and are they answerable through more source discovery for:", question),
            "purpose": "structural",
            "coverage_dimension": "material_unknowns",
            "research_factor": "unanswered_material_questions",
            "research_priority": "medium",
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["unanswered_question_status", "answerability_status"],
            "market_component_terms": [topic, "material unknown", "answerability"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
    ]
    return {
        "candidate_id": f"qdt-candidate-{topic}",
        "market_complexity_score": 0.62,
        "branches": branches,
        "required_leaf_questions": leaves,
        "reason_codes": ["fixture_question_specific_decomposition"],
    }


def _basic_response_validator(response: Any) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(response, dict):
        return False, ["response must be an object"]
    if not isinstance(response.get("branches"), list) or not response["branches"]:
        errors.append("branches must be a non-empty list")
    if not isinstance(response.get("required_leaf_questions"), list) or not response["required_leaf_questions"]:
        errors.append("required_leaf_questions must be a non-empty list")
    if len(response.get("required_leaf_questions", [])) > COMPACT_DEFAULT_LEAF_BUDGET:
        errors.append("required_leaf_questions exceeds compact default leaf budget")
    return not errors, errors


PURPOSE_ALIASES = {
    "official_resolution": "source_of_truth",
    "official_source": "source_of_truth",
    "source": "source_of_truth",
    "source_of_truth_evidence": "source_of_truth",
    "resolution_criteria": "resolution_mechanics",
    "resolution_rules": "resolution_mechanics",
    "market_rules": "resolution_mechanics",
    "rules": "resolution_mechanics",
    "status": "direct_evidence",
    "event_status": "direct_evidence",
    "candidate_status": "direct_evidence",
    "filing_status": "direct_evidence",
    "nomination_status": "direct_evidence",
    "endorsement_status": "direct_evidence",
    "current_status": "direct_evidence",
    "historical_base_rate": "base_rate",
    "history": "base_rate",
    "pricing": "market_pricing",
    "market": "market_pricing",
    "mechanics": "resolution_mechanics",
}


def _normalized_token(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower())
    return re.sub(r"_+", "_", text).strip("_")


def _normalize_purpose(value: Any) -> str:
    token = _normalized_token(value)
    if token in ALLOWED_PURPOSES:
        return token
    if token in PURPOSE_ALIASES:
        return PURPOSE_ALIASES[token]
    if "source" in token or "official" in token:
        return "source_of_truth"
    if "rule" in token or "criteria" in token or "mechanic" in token:
        return "resolution_mechanics"
    if "price" in token or "market" in token:
        return "market_pricing"
    if "base" in token or "historic" in token:
        return "base_rate"
    if "catalyst" in token:
        return "catalyst"
    if "structure" in token:
        return "structural"
    if token:
        return "direct_evidence"
    return "other"


def _normalize_condition_scope(value: Any) -> str:
    token = _normalized_token(value)
    if token in ALLOWED_CONDITION_SCOPES:
        return token
    if token in {"shared", "shared_context_leaf", "context"}:
        return "shared_context"
    return "unconditional"


def _compact_reason_codes(value: Any, fallback: str) -> list[str]:
    if isinstance(value, list):
        codes = []
        for item in value:
            token = _normalized_token(item)
            if token:
                codes.append(token[:80])
        if codes:
            return codes
    return [fallback]


def _ensure_model_candidate_contract_shape(repaired: dict[str, Any]) -> dict[str, Any]:
    leaves = repaired.get("required_leaf_questions")
    if not isinstance(leaves, list):
        return repaired
    branches = repaired.get("branches")
    if not isinstance(branches, list):
        branches = []
        repaired["branches"] = branches
    branch_by_id = {
        str(branch.get("branch_id")): branch
        for branch in branches
        if isinstance(branch, dict) and isinstance(branch.get("branch_id"), str)
    }
    if not branch_by_id:
        branch = {
            "branch_id": "branch-resolution",
            "branch_question": "Resolve the market-specific outcome.",
            "branch_role": "model_repaired_branch",
            "dependency_group_id": "dep-group-resolution",
            "required_evidence_purposes": ["source_of_truth", "direct_evidence"],
            "leaf_ids": [],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1},
        }
        branches.append(branch)
        branch_by_id[branch["branch_id"]] = branch

    default_branch_id = next(iter(branch_by_id))
    membership: dict[str, list[str]] = {branch_id: [] for branch_id in branch_by_id}
    leaf_purposes_by_branch: dict[str, set[str]] = {branch_id: set() for branch_id in branch_by_id}

    for idx, leaf in enumerate(leaves):
        if not isinstance(leaf, dict):
            continue
        leaf_id = str(leaf.get("leaf_id") or f"leaf-model-{idx + 1}")
        if not leaf_id.startswith("leaf-"):
            leaf_id = "leaf-" + _normalized_token(leaf_id)
        leaf["leaf_id"] = leaf_id
        if not leaf.get("question_text") and leaf.get("leaf_question"):
            leaf["question_text"] = leaf["leaf_question"]
        if not leaf.get("question_text"):
            leaf["question_text"] = f"What market-specific evidence should classify {leaf_id}?"
        parent_id = str(leaf.get("parent_branch_id") or default_branch_id)
        if parent_id not in branch_by_id:
            parent_id = default_branch_id
        leaf["parent_branch_id"] = parent_id
        membership.setdefault(parent_id, []).append(leaf_id)
        purpose = _normalize_purpose(leaf.get("purpose"))
        leaf["purpose"] = purpose
        leaf_purposes_by_branch.setdefault(parent_id, set()).add(purpose)
        legacy_weighting = leaf.pop("bayesian_weighting", None)
        priority = leaf.get("research_priority")
        if priority not in ALLOWED_RESEARCH_PRIORITIES and isinstance(legacy_weighting, dict):
            priority = legacy_weighting.get("research_priority") or legacy_weighting.get("static_information_weight")
        if priority not in ALLOWED_RESEARCH_PRIORITIES:
            priority = "medium"
        leaf["research_priority"] = priority
        leaf["leaf_dependency_group_id"] = str(
            leaf.get("leaf_dependency_group_id")
            or branch_by_id[parent_id].get("dependency_group_id")
            or f"dep-group-{parent_id.removeprefix('branch-')}"
        )
        leaf["leaf_condition_scope"] = _normalize_condition_scope(leaf.get("leaf_condition_scope"))
        if not isinstance(leaf.get("required_evidence_fields"), list) or not leaf["required_evidence_fields"]:
            leaf["required_evidence_fields"] = [f"{purpose}_status"]
        if not isinstance(leaf.get("market_component_terms"), list):
            leaf["market_component_terms"] = []
        if not isinstance(leaf.get("amrg_usage_refs"), list):
            leaf["amrg_usage_refs"] = []
        structural = leaf.get("structural_validation")
        if not isinstance(structural, dict):
            structural = {}
        structural["depth"] = 2
        structural.setdefault("answerability_status", "answerable")
        leaf["structural_validation"] = structural

    has_anchor_contracts = bool(repaired.get("amrg_anchor_dependency_contracts"))
    if not has_anchor_contracts:
        for leaf in leaves:
            if isinstance(leaf, dict) and leaf.get("leaf_condition_scope") in {
                "target_given_upstream",
                "target_given_not_upstream",
            }:
                leaf["leaf_condition_scope"] = "unconditional"

    for branch in branches:
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("branch_id") or default_branch_id)
        if not branch_id.startswith("branch-"):
            branch_id = "branch-" + _normalized_token(branch_id)
            branch["branch_id"] = branch_id
        if not branch.get("branch_question"):
            branch["branch_question"] = f"Resolve {branch_id} from market-specific leaves."
        if not branch.get("branch_role"):
            branch["branch_role"] = "model_repaired_branch"
        if not branch.get("dependency_group_id"):
            branch["dependency_group_id"] = f"dep-group-{branch_id.removeprefix('branch-')}"
        branch["leaf_ids"] = membership.get(branch_id, [])
        purposes = sorted(leaf_purposes_by_branch.get(branch_id, set()))
        branch["required_evidence_purposes"] = purposes or ["other"]
        if not isinstance(branch.get("amrg_usage_refs"), list):
            branch["amrg_usage_refs"] = []
        structural = branch.get("structural_validation")
        if not isinstance(structural, dict):
            structural = {}
        structural["depth"] = 1
        branch["structural_validation"] = structural

    return repaired


def _unwrap_model_candidate_container(response: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "response_payload",
        "qdt_candidate",
        "candidate",
        "model_candidate",
        "question_decomposition_candidate",
        "question_decomposition",
        "decomposition",
        "payload",
    ):
        nested = response.get(key)
        if isinstance(nested, dict):
            if isinstance(nested.get("branches"), list) or isinstance(nested.get("required_leaf_questions"), list):
                return dict(nested)
            deeper = _unwrap_model_candidate_container(nested)
            if deeper is not nested:
                return deeper
    candidates = response.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict) and (
                isinstance(candidate.get("branches"), list)
                or isinstance(candidate.get("required_leaf_questions"), list)
            ):
                return dict(candidate)
    return response


def _response_repairer(response: Any, _errors: list[str]) -> Any:
    if not isinstance(response, dict):
        return response
    repaired = _unwrap_model_candidate_container(dict(response))
    if "required_leaf_questions" not in repaired:
        for alias in ("leaf_questions", "leaves", "required_research_questions"):
            if isinstance(repaired.get(alias), list):
                repaired["required_leaf_questions"] = repaired[alias]
                break
    if "branches" not in repaired and isinstance(repaired.get("required_leaf_questions"), list):
        parent_ids = sorted(
            {
                str(leaf.get("parent_branch_id"))
                for leaf in repaired["required_leaf_questions"]
                if isinstance(leaf, dict) and isinstance(leaf.get("parent_branch_id"), str)
            }
        )
        if parent_ids:
            repaired["branches"] = [
                {
                    "branch_id": parent_id,
                    "branch_question": f"Resolve branch {parent_id} from the market-specific leaves.",
                    "branch_role": "model_repaired_branch",
                    "dependency_group_id": f"dep-group-{parent_id.removeprefix('branch-')}",
                    "required_evidence_purposes": sorted(
                        {
                            str(leaf.get("purpose"))
                            for leaf in repaired["required_leaf_questions"]
                            if isinstance(leaf, dict)
                            and leaf.get("parent_branch_id") == parent_id
                            and isinstance(leaf.get("purpose"), str)
                        }
                    )
                    or ["other"],
                    "leaf_ids": [
                        str(leaf.get("leaf_id"))
                        for leaf in repaired["required_leaf_questions"]
                        if isinstance(leaf, dict)
                        and leaf.get("parent_branch_id") == parent_id
                        and isinstance(leaf.get("leaf_id"), str)
                    ],
                    "amrg_usage_refs": [],
                    "structural_validation": {"depth": 1},
                }
                for parent_id in parent_ids
            ]
    return _ensure_model_candidate_contract_shape(repaired)


def _candidate_from_model_payload(
    handoff: dict[str, Any],
    model_payload: dict[str, Any],
    *,
    runtime_mode: str,
    runtime_context: dict[str, Any],
) -> dict[str, Any]:
    enriched_handoff = dict(handoff)
    enriched_handoff["model_execution_context"] = runtime_context
    candidate = build_qdt_candidate(
        handoff=enriched_handoff,
        candidate_id=str(model_payload.get("candidate_id") or "qdt-candidate-model-runtime"),
        branches=model_payload["branches"],
        required_leaf_questions=model_payload["required_leaf_questions"],
        market_complexity_score=float(model_payload.get("market_complexity_score", 0.62)),
        related_market_context_usage=model_payload.get("related_market_context_usage")
        if isinstance(model_payload.get("related_market_context_usage"), dict)
        else None,
        amrg_anchor_dependency_contracts=model_payload.get("amrg_anchor_dependency_contracts")
        if isinstance(model_payload.get("amrg_anchor_dependency_contracts"), list)
        else None,
        selection_strategy=f"model_runtime_{runtime_mode}",
    )
    market_id = str(
        handoff.get("market_context", {}).get("market_id") or handoff.get("case_key") or "unknown-market"
    )
    candidate["market_id"] = market_id
    selected = select_qdt_candidate([candidate])
    selected["market_id"] = market_id
    selected["adapter_mode"] = f"decomposer_model_runtime_{runtime_mode}"
    selected.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        f"decomposer_model_runtime_{runtime_mode}"
    )
    selected.update(compute_qdt_quality_checks(selected))
    return selected


def _amrg_operator_metadata(
    selected: dict[str, Any],
    amrg_decomposer_context: dict[str, Any] | None,
) -> dict[str, Any]:
    hints = amrg_decomposer_context.get("hints", []) if isinstance(amrg_decomposer_context, dict) else []
    hint_refs = {str(hint.get("hint_ref")) for hint in hints if isinstance(hint, dict) and hint.get("hint_ref")}
    leaf_slices: list[dict[str, Any]] = []
    branch_slices: list[dict[str, Any]] = []
    for branch in selected.get("branches", []):
        if isinstance(branch, dict) and isinstance(branch.get("amrg_usage_refs"), list):
            refs = sorted({str(ref) for ref in branch["amrg_usage_refs"] if str(ref) in hint_refs})
            if refs:
                branch_slices.append(
                    {
                        "branch_id": str(branch.get("branch_id")),
                        "hint_refs": refs,
                        "consumption_status": "diagnostic_or_validated_context_ref_only",
                    }
                )
    for leaf in selected.get("required_leaf_questions", []):
        if isinstance(leaf, dict) and isinstance(leaf.get("amrg_usage_refs"), list):
            refs = sorted({str(ref) for ref in leaf["amrg_usage_refs"] if str(ref) in hint_refs})
            if refs:
                leaf_slices.append(
                    {
                        "leaf_id": str(leaf.get("leaf_id")),
                        "hint_refs": refs,
                        "consumption_status": "diagnostic_or_validated_context_ref_only",
                    }
                )
    return {
        "schema_version": "qdt-amrg-operator-metadata/v1",
        "amrg_decomposer_context_ref": amrg_decomposer_context.get("context_ref")
        if isinstance(amrg_decomposer_context, dict)
        else None,
        "hint_refs_considered": sorted(hint_refs),
        "branch_hint_ref_slices": branch_slices,
        "leaf_hint_ref_slices": leaf_slices,
        "weak_hint_promotion_status": "not_promoted_without_validated_anchor_contract",
        "anchor_contract_edge_refs": sorted(
            {
                str(contract.get("edge_id"))
                for contract in selected.get("amrg_anchor_dependency_contracts", [])
                if isinstance(contract, dict) and contract.get("edge_id")
            }
        ),
        "authority": "operator_audit_only_no_forecast_authority",
    }


def _response_validator_for_handoff(
    handoff: dict[str, Any],
    *,
    runtime_mode: str,
    evidence_packet: dict[str, Any] | None = None,
) -> Callable[[Any], tuple[bool, list[str]]]:
    base_context = handoff["model_execution_context"]

    def validator(response: Any) -> tuple[bool, list[str]]:
        valid, errors = _basic_response_validator(response)
        if not valid:
            return False, errors
        assert isinstance(response, dict)
        try:
            selected = _candidate_from_model_payload(
                handoff,
                response,
                runtime_mode=runtime_mode,
                runtime_context=base_context,
            )
            qdt_validation = validate_question_decomposition(
                selected,
                evidence_packet=evidence_packet,
            )
        except (QDTError, KeyError, TypeError, ValueError) as exc:
            return False, [str(exc)]
        if not qdt_validation.valid:
            return False, list(qdt_validation.errors)
        return True, []

    return validator


def build_decomposition_prompt_payload(
    handoff: dict[str, Any],
    *,
    payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refs = handoff.get("artifact_refs", {}) if isinstance(handoff.get("artifact_refs"), dict) else {}
    payloads = payloads or _load_manifest_payloads(handoff)
    case_payload = payloads.get("ads_case_contract", {})
    evidence_payload = payloads.get("evidence_packet", {})
    profile_payload = payloads.get("effective_profile_context", {})
    amrg_payload = payloads.get("related_market_context", {})
    amrg_decomposer_context = _amrg_decomposer_context_from_payload(amrg_payload)
    market_identity = case_payload.get("market_identity") or evidence_payload.get("market_identity", {})
    market_constraints = evidence_payload.get("market_reality_constraints", {})
    source_cutoff_timestamp = (
        case_payload.get("source_cutoff_timestamp")
        or handoff.get("source_cutoff_timestamp")
    )
    market_temporal_state = _market_temporal_state_from_handoff(
        handoff,
        case_payload=case_payload,
        evidence_payload=evidence_payload,
    )
    pre_resolution_instruction = (
        "If market_temporal_state is unresolved, prioritize pre-resolution forecast research. "
        "Ask what current evidence, drivers, blockers, source quality, timing constraints, "
        "and missing information should be classified before cutoff. Do not make official-result "
        "or final-winner verification the dominant dispatchable leaf set. Put future settlement/result "
        "checks in terminal_verification leaves and mark them non-dispatchable before resolution unless "
        "already observable before the source cutoff."
    )
    return {
        "prompt_schema_version": "decomposer-qdt-prompt-input/v1",
        "prompt_template_id": handoff["model_execution_context"]["prompt_template_id"],
        "macro_question": handoff["macro_question"],
        "market_temporal_state": market_temporal_state,
        "source_cutoff_timestamp": source_cutoff_timestamp,
        "market_context": handoff.get("market_context", {}),
        "market_identity": {
            "title": market_identity.get("title"),
            "description": market_identity.get("description"),
            "slug": market_identity.get("slug"),
            "platform": market_identity.get("platform"),
            "external_market_id": market_identity.get("external_market_id"),
            "outcome_type": market_identity.get("outcome_type"),
            "closes_at": market_identity.get("closes_at") or market_constraints.get("close_timestamp"),
            "resolves_at": market_identity.get("resolves_at") or market_constraints.get("resolve_timestamp"),
        },
        "case_contract": {
            "market_identity": case_payload.get("market_identity", {}),
            "prediction_time_market_baseline": case_payload.get("prediction_time_market_baseline", {}),
            "forecast_timestamp": case_payload.get("forecast_timestamp") or handoff.get("forecast_timestamp"),
            "source_cutoff_timestamp": source_cutoff_timestamp,
        },
        "evidence_packet": {
            "market_rules": evidence_payload.get("market_rules", {}),
            "market_reality_constraints": market_constraints,
            "side_mapping": market_constraints.get("side_mapping"),
            "axis_mapping": market_constraints.get("axis_mapping"),
            "source_of_truth_status": market_constraints.get("source_of_truth_status"),
            "required_evidence_purposes": evidence_payload.get("required_evidence_purposes", []),
            "family_context": evidence_payload.get("family_context", {}),
            "prior_context_seed": evidence_payload.get("prior_context_seed", {}),
        },
        "profile_context": {
            "profile_context_ref": profile_payload.get("profile_context_ref")
            or refs.get("effective_profile_context", {}).get("artifact_id"),
            "profile_id": profile_payload.get("profile_id"),
            "model_lane_policy_ref": profile_payload.get("model_lane_policy_ref"),
        },
        "amrg_context_summary": {
            "artifact_type": amrg_payload.get("artifact_type"),
            "candidate_set_id": amrg_payload.get("candidate_set_id"),
            "candidate_count": len(amrg_payload.get("candidates", []))
            if isinstance(amrg_payload.get("candidates"), list)
            else 0,
            "relationship_edge_count": len(amrg_payload.get("relationship_edges", []))
            if isinstance(amrg_payload.get("relationship_edges"), list)
            else 0,
            "waiver_reason_codes": amrg_payload.get("waiver_reason_codes", []),
        },
        "amrg_decomposer_context": amrg_decomposer_context,
        "instruction_blocks": [
            {
                "block_id": "no_probability_authority",
                "text": (
                    "Produce a bounded research decomposition that maximizes coverage of material uncertainty. "
                    "Do not estimate probability. Do not assign weights. Do not make a final forecast. "
                    "Emit leaf questions, purposes, evidence requirements, classification targets, and "
                    "sufficiency criteria."
                ),
            },
            {
                "block_id": "pre_resolution_forecast_research",
                "text": pre_resolution_instruction,
            },
            {
                "block_id": "required_qdt_partitions",
                "text": (
                    "Separate contract guard leaves, material research-factor leaves, material unknowns, "
                    "overlap groups, terminal verification leaves, and dispatchable pre-resolution leaves."
                ),
            },
            {
                "block_id": "amrg_context_boundary",
                "text": (
                    "AMRG hints are bounded context only. Weak or generic AMRG refs must remain "
                    "weak_context_only=true unless a strict anchor dependency is validated, and must not be "
                    "used for QDT selection, QDT repair, probability authority, SCAE delta, or forecast writes."
                ),
            },
            {
                "block_id": "schema_repair_policy",
                "text": (
                    "Schema repair may normalize shape, aliases, and enum drift only. It must not invent "
                    "semantic forecast coverage, terminal-verification classification, market-family analysis, "
                    "or negative-market YES/NO semantics."
                ),
            },
        ],
        "instructions": {
            "output": "depth_2_research_coverage_decomposition_branches_and_leaves",
            "depth": "exactly branches at depth 1 and required_leaf_questions at depth 2",
            "leaf_budget": COMPACT_DEFAULT_LEAF_BUDGET,
            "make_leaves_question_specific": True,
            "market_temporal_state": market_temporal_state,
            "pre_resolution_forecast_research": pre_resolution_instruction,
            "terminal_verification_gating": (
                "Terminal verification leaves are for settlement/result checks and must not be dispatched "
                "as pre-resolution research for unresolved markets unless the result is already observable "
                "before source_cutoff_timestamp."
            ),
            "required_leaf_partitions": [
                "contract_guard_leaf_ids",
                "material_question_leaf_ids",
                "material_unknowns",
                "overlap_groups",
                "terminal_verification_leaf_ids",
                "dispatchable_pre_resolution_leaf_ids",
            ],
            "contract_text": (
                "Produce a bounded research decomposition that maximizes coverage of material uncertainty. "
                "Do not estimate probability. Do not assign weights. Do not make a final forecast. "
                "Emit leaf questions, purposes, evidence requirements, classification targets, "
                "and sufficiency criteria."
            ),
            "required_top_level_contracts": [
                "market_resolution_contract",
                "research_coverage_graph",
            ],
            "required_coverage_dimensions": [
                "resolution_mechanics",
                "current_direct_evidence",
                "key_drivers",
                "counterevidence_negative_checks",
                "timing_deadline_constraints",
                "source_quality",
                "material_unknowns",
            ],
            "include_research_sufficiency_inputs": [
                "purpose",
                "coverage_dimension",
                "research_factor",
                "classification_targets",
                "evidence_requirements",
                "sufficiency_criteria",
                "research_priority",
                "leaf_condition_scope",
                "required_evidence_fields",
            ],
            "amrg_allowed_uses": [
                "context_leaf",
                "retrieval_hint",
                "conditional_anchor_dependency_request",
            ],
            "amrg_weak_context_policy": (
                "Weak AMRG refs remain weak_context_only=true unless a strict anchor dependency is validated."
            ),
            "amrg_forbidden_uses": [
                "qdt_selection",
                "qdt_repair",
                "prior_anchor",
                "probability_authority",
                "scae_delta",
                "production_forecast_write",
            ],
            "forbidden": [
                "probability",
                "fair_value",
                "scae_delta",
                "decision_recommendation",
            ],
            "decomposer_authority": "qdt_generation_only",
        },
    }


def build_question_decomposition_from_handoff(
    handoff: dict[str, Any],
    *,
    runtime_mode: str = "fixture",
    fixture_response: dict[str, Any] | None = None,
    transport: Transport | None = None,
    max_schema_repairs: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_decomposer_handoff(handoff)
    base_context = handoff["model_execution_context"]
    payloads = _load_manifest_payloads(handoff)
    request_payload = build_decomposition_prompt_payload(handoff, payloads=payloads)
    response = fixture_response if fixture_response is not None else build_question_specific_fixture_response(handoff)
    if runtime_mode == "live" and transport is None:
        transport = _configured_live_transport()
    evidence_packet = payloads.get("evidence_packet") or None
    related_market_context = payloads.get("related_market_context") or None
    amrg_decomposer_context = request_payload.get("amrg_decomposer_context")
    runtime_result = execute_model_runtime_call(
        model_lane_id=base_context["model_lane_id"],
        provider=base_context.get("provider", "openai"),
        resolved_model_id=base_context["resolved_model_id"],
        provider_route=base_context.get("provider_route")
        or f"{base_context.get('provider', 'openai')}/{base_context['resolved_model_id']}",
        prompt_template_id=base_context["prompt_template_id"],
        prompt_template_sha256=base_context["prompt_template_sha256"],
        input_manifest_refs=list(base_context.get("input_manifest_ids", [])),
        output_schema_version=QUESTION_DECOMPOSITION_SCHEMA_VERSION,
        request_payload=request_payload,
        mode=runtime_mode,
        fixture_response=response if runtime_mode == "fixture" else None,
        transport=transport,
        output_validator=_response_validator_for_handoff(
            handoff,
            runtime_mode=runtime_mode,
            evidence_packet=evidence_packet,
        ),
        repairer=_response_repairer,
        max_schema_repairs=max_schema_repairs,
    )
    runtime_context = model_execution_context_from_runtime_call(
        base_context,
        runtime_result.runtime_call,
    )
    model_payload = runtime_result.response_payload
    selected = _candidate_from_model_payload(
        handoff,
        model_payload,
        runtime_mode=runtime_mode,
        runtime_context=runtime_context,
    )
    selected["runtime_call_ref"] = runtime_result.runtime_call["runtime_call_id"]
    selected["amrg_operator_metadata"] = _amrg_operator_metadata(selected, amrg_decomposer_context)
    validation = validate_question_decomposition(selected, evidence_packet=evidence_packet)
    if not validation.valid:
        raise QDTError("; ".join(validation.errors))
    amrg_validation = validate_question_decomposition_against_amrg_context(
        selected,
        related_market_context,
    )
    if not amrg_validation.valid:
        raise QDTError("; ".join(amrg_validation.errors))
    return selected, runtime_result.runtime_call


def _transport_response_file(path: Path) -> Transport:
    def transport(_payload: dict[str, Any]) -> dict[str, Any]:
        loaded = _load(path)
        if loaded.get("schema_version") == MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION:
            return loaded
        return {
            "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
            "response_payload": loaded,
            "provider_status": {"transport": "file_response", "path": str(path)},
        }

    return transport


def _configured_live_transport() -> Transport:
    response_path = os.environ.get("ADS_DECOMPOSER_LIVE_RESPONSE_PATH")
    if response_path:
        return _transport_response_file(Path(response_path))
    return openclaw_codex_agent_transport_from_env()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-call-output", type=Path)
    parser.add_argument("--runtime-mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--fixture-response", type=Path)
    parser.add_argument("--transport-response", type=Path)
    args = parser.parse_args()
    if args.handoff is None:
        payload = {
            "schema_version": "ads-decomposer-runtime-entrypoint/v1",
            "entrypoint": "run_decomposition.py",
            "runtime_owner": "ADS Decomposer",
            "status": "available",
            "authority": "qdt_generation_only_no_probability",
        }
        sys.stdout.write(canonical_json(payload) + "\n")
        return 0

    try:
        handoff = _load(args.handoff)
        fixture_response = _load(args.fixture_response) if args.fixture_response else None
        transport = _transport_response_file(args.transport_response) if args.transport_response else None
        qdt, runtime_call = build_question_decomposition_from_handoff(
            handoff,
            runtime_mode=args.runtime_mode,
            fixture_response=fixture_response,
            transport=transport,
        )
    except (ModelRuntimeError, QDTError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        runtime_call = getattr(exc, "runtime_call", None)
        if isinstance(runtime_call, dict) and args.runtime_call_output:
            args.runtime_call_output.parent.mkdir(parents=True, exist_ok=True)
            args.runtime_call_output.write_text(canonical_json(runtime_call) + "\n", encoding="utf-8")
        return 2

    text = dump_question_decomposition(qdt) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.runtime_call_output:
        args.runtime_call_output.parent.mkdir(parents=True, exist_ok=True)
        args.runtime_call_output.write_text(canonical_json(runtime_call) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
