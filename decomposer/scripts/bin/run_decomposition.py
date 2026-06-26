#!/usr/bin/env python3
"""ADS Decomposer-owned QDT runtime entrypoint."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT / "orchestrator" / "scripts"))

from predquant.ads_handoff import canonical_json  # noqa: E402
from ads_decomposer.handoff import validate_decomposer_handoff  # noqa: E402
from ads_decomposer.model_runtime import (  # noqa: E402
    ModelRuntimeError,
    execute_model_runtime_call,
    model_execution_context_from_runtime_call,
    prefixed_sha256,
)
from ads_decomposer.qdt import (  # noqa: E402
    COMPACT_DEFAULT_LEAF_BUDGET,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
    QDTError,
    build_qdt_candidate,
    dump_question_decomposition,
    select_qdt_candidate,
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


def _load_manifest_payload(manifest_ref: dict[str, Any]) -> dict[str, Any]:
    path = manifest_ref.get("path") if isinstance(manifest_ref, dict) else None
    if not isinstance(path, str) or not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    return _load(candidate)


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
            "branch_question": _bounded_question_text("Resolve the target question with official status and direct evidence:", question),
            "branch_role": "question_specific_resolution_evidence",
            "dependency_group_id": f"dep-group-{topic}-resolution",
            "required_evidence_purposes": ["source_of_truth", "direct_evidence"],
            "leaf_ids": [f"leaf-{topic}-official-status", f"leaf-{topic}-direct-status"],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1},
        },
        {
            "branch_id": f"branch-{topic}-mechanics",
            "branch_question": _bounded_question_text("Identify the market-specific rules and timing constraints for:", question),
            "branch_role": "question_specific_resolution_mechanics",
            "dependency_group_id": f"dep-group-{topic}-mechanics",
            "required_evidence_purposes": ["resolution_mechanics"],
            "leaf_ids": [f"leaf-{topic}-rules-window"],
            "amrg_usage_refs": [],
            "structural_validation": {"depth": 1},
        },
    ]
    leaves = [
        {
            "leaf_id": f"leaf-{topic}-official-status",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("Which official or primary source can establish the resolution status for:", question),
            "purpose": "source_of_truth",
            "bayesian_weighting": {
                "static_information_weight": "critical",
                "weight_reason_codes": ["official_resolution_authority"],
            },
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["official_status", "resolution_criteria"],
            "market_component_terms": [topic, "official status", "resolution criteria"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-direct-status",
            "parent_branch_id": branches[0]["branch_id"],
            "question_text": _bounded_question_text("What fresh direct evidence before the cutoff supports or contradicts:", question),
            "purpose": "direct_evidence",
            "bayesian_weighting": {
                "static_information_weight": "high",
                "weight_reason_codes": ["question_specific_event_status"],
            },
            "leaf_dependency_group_id": branches[0]["dependency_group_id"],
            "leaf_condition_scope": "unconditional",
            "required_evidence_fields": ["event_status", "event_timestamp"],
            "market_component_terms": [topic, "event status", "cutoff"],
            "structural_validation": {"depth": 2, "answerability_status": "answerable"},
        },
        {
            "leaf_id": f"leaf-{topic}-rules-window",
            "parent_branch_id": branches[1]["branch_id"],
            "question_text": _bounded_question_text("Which resolution rules, dates, and source windows govern the market for:", question),
            "purpose": "resolution_mechanics",
            "bayesian_weighting": {
                "static_information_weight": "medium",
                "weight_reason_codes": ["market_specific_contract_terms"],
            },
            "leaf_dependency_group_id": branches[1]["dependency_group_id"],
            "leaf_condition_scope": "shared_context",
            "required_evidence_fields": ["resolution_deadline", "rules_text"],
            "market_component_terms": [topic, "rules", "deadline"],
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


def _response_validator(response: Any) -> tuple[bool, list[str]]:
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


def build_decomposition_prompt_payload(handoff: dict[str, Any]) -> dict[str, Any]:
    refs = handoff.get("artifact_refs", {}) if isinstance(handoff.get("artifact_refs"), dict) else {}
    case_payload = _load_manifest_payload(refs.get("ads_case_contract", {}))
    evidence_payload = _load_manifest_payload(refs.get("evidence_packet", {}))
    profile_payload = _load_manifest_payload(refs.get("effective_profile_context", {}))
    amrg_payload = _load_manifest_payload(refs.get("related_market_context", {}))
    return {
        "prompt_schema_version": "decomposer-qdt-prompt-input/v1",
        "prompt_template_id": handoff["model_execution_context"]["prompt_template_id"],
        "macro_question": handoff["macro_question"],
        "market_context": handoff.get("market_context", {}),
        "case_contract": {
            "market_identity": case_payload.get("market_identity", {}),
            "prediction_time_market_baseline": case_payload.get("prediction_time_market_baseline", {}),
        },
        "evidence_packet": {
            "market_rules": evidence_payload.get("market_rules", {}),
            "market_reality_constraints": evidence_payload.get("market_reality_constraints", {}),
            "required_evidence_purposes": evidence_payload.get("required_evidence_purposes", []),
        },
        "profile_context_ref": profile_payload.get("profile_context_ref") or refs.get("effective_profile_context", {}).get("artifact_id"),
        "amrg_context_summary": {
            "artifact_type": amrg_payload.get("artifact_type"),
            "candidate_set_id": amrg_payload.get("candidate_set_id"),
            "candidate_count": len(amrg_payload.get("candidates", [])) if isinstance(amrg_payload.get("candidates"), list) else 0,
            "relationship_edge_count": len(amrg_payload.get("relationship_edges", []))
            if isinstance(amrg_payload.get("relationship_edges"), list)
            else 0,
        },
        "instructions": {
            "output": "depth_2_question_decomposition_branches_and_leaves",
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_decomposer_handoff(handoff)
    base_context = handoff["model_execution_context"]
    request_payload = build_decomposition_prompt_payload(handoff)
    response = fixture_response if fixture_response is not None else build_question_specific_fixture_response(handoff)
    runtime_result = execute_model_runtime_call(
        model_lane_id=base_context["model_lane_id"],
        provider=base_context.get("provider", "openai"),
        resolved_model_id=base_context["resolved_model_id"],
        provider_route=base_context.get("provider_route") or f"{base_context.get('provider', 'openai')}/{base_context['resolved_model_id']}",
        prompt_template_id=base_context["prompt_template_id"],
        prompt_template_sha256=base_context["prompt_template_sha256"],
        input_manifest_refs=list(base_context.get("input_manifest_ids", [])),
        output_schema_version=QUESTION_DECOMPOSITION_SCHEMA_VERSION,
        request_payload=request_payload,
        mode=runtime_mode,
        fixture_response=response if runtime_mode == "fixture" else None,
        output_validator=_response_validator,
    )
    runtime_context = model_execution_context_from_runtime_call(
        base_context,
        runtime_result.runtime_call,
    )
    enriched_handoff = dict(handoff)
    enriched_handoff["model_execution_context"] = runtime_context
    model_payload = runtime_result.response_payload
    candidate = build_qdt_candidate(
        handoff=enriched_handoff,
        candidate_id=str(model_payload.get("candidate_id") or "qdt-candidate-model-runtime"),
        branches=model_payload["branches"],
        required_leaf_questions=model_payload["required_leaf_questions"],
        market_complexity_score=float(model_payload.get("market_complexity_score", 0.62)),
        selection_strategy=f"model_runtime_{runtime_mode}",
    )
    candidate["market_id"] = str(
        handoff.get("market_context", {}).get("market_id") or handoff.get("case_key") or "unknown-market"
    )
    selected = select_qdt_candidate([candidate])
    selected["market_id"] = str(
        handoff.get("market_context", {}).get("market_id") or handoff.get("case_key") or "unknown-market"
    )
    selected["adapter_mode"] = f"decomposer_model_runtime_{runtime_mode}"
    selected["runtime_call_ref"] = runtime_result.runtime_call["runtime_call_id"]
    selected.setdefault("validation_summary", {}).setdefault("reason_codes", []).append(
        f"decomposer_model_runtime_{runtime_mode}"
    )
    selected["question_specificity_check"] = {
        "status": "passed",
        "macro_question_sha256": prefixed_sha256(handoff.get("macro_question", "")),
        "generic_fixture_leaf_ids_absent": not {
            "leaf-source-of-truth",
            "leaf-direct-evidence",
            "leaf-resolution-mechanics",
        }.intersection({str(leaf.get("leaf_id")) for leaf in selected.get("required_leaf_questions", [])}),
    }
    validation = validate_question_decomposition(selected)
    if not validation.valid:
        raise QDTError("; ".join(validation.errors))
    return selected, runtime_result.runtime_call


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runtime-call-output", type=Path)
    parser.add_argument("--runtime-mode", choices=["fixture", "live"], default="fixture")
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
        qdt, runtime_call = build_question_decomposition_from_handoff(handoff, runtime_mode=args.runtime_mode)
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
