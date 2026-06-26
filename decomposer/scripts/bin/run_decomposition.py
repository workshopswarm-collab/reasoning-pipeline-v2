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
    openai_responses_transport_from_env,
    prefixed_sha256,
)
from ads_decomposer.qdt import (  # noqa: E402
    COMPACT_DEFAULT_LEAF_BUDGET,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
    QDTError,
    build_qdt_candidate,
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


def _response_repairer(response: Any, _errors: list[str]) -> Any:
    if not isinstance(response, dict):
        return response
    repaired = dict(response)
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
    return repaired


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
    selected["question_specificity_check"] = {
        "status": "passed",
        "macro_question_sha256": prefixed_sha256(handoff.get("macro_question", "")),
        "generic_fixture_leaf_ids_absent": not {
            "leaf-source-of-truth",
            "leaf-direct-evidence",
            "leaf-resolution-mechanics",
        }.intersection({str(leaf.get("leaf_id")) for leaf in selected.get("required_leaf_questions", [])}),
    }
    return selected


def _amrg_operator_metadata(
    selected: dict[str, Any],
    amrg_decomposer_context: dict[str, Any] | None,
) -> dict[str, Any]:
    hints = amrg_decomposer_context.get("hints", []) if isinstance(amrg_decomposer_context, dict) else []
    hint_refs = {str(hint.get("hint_ref")) for hint in hints if isinstance(hint, dict) and hint.get("hint_ref")}
    leaf_refs: dict[str, list[str]] = {}
    branch_refs: dict[str, list[str]] = {}
    for branch in selected.get("branches", []):
        if isinstance(branch, dict) and isinstance(branch.get("amrg_usage_refs"), list):
            refs = sorted({str(ref) for ref in branch["amrg_usage_refs"] if str(ref) in hint_refs})
            if refs:
                branch_refs[str(branch.get("branch_id"))] = refs
    for leaf in selected.get("required_leaf_questions", []):
        if isinstance(leaf, dict) and isinstance(leaf.get("amrg_usage_refs"), list):
            refs = sorted({str(ref) for ref in leaf["amrg_usage_refs"] if str(ref) in hint_refs})
            if refs:
                leaf_refs[str(leaf.get("leaf_id"))] = refs
    return {
        "schema_version": "qdt-amrg-operator-metadata/v1",
        "amrg_decomposer_context_ref": amrg_decomposer_context.get("context_ref")
        if isinstance(amrg_decomposer_context, dict)
        else None,
        "hint_refs_considered": sorted(hint_refs),
        "branch_hint_refs": branch_refs,
        "leaf_hint_refs": leaf_refs,
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
    return {
        "prompt_schema_version": "decomposer-qdt-prompt-input/v1",
        "prompt_template_id": handoff["model_execution_context"]["prompt_template_id"],
        "macro_question": handoff["macro_question"],
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
            "source_cutoff_timestamp": case_payload.get("source_cutoff_timestamp")
            or handoff.get("source_cutoff_timestamp"),
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
            "candidate_count": len(amrg_payload.get("candidates", [])) if isinstance(amrg_payload.get("candidates"), list) else 0,
            "relationship_edge_count": len(amrg_payload.get("relationship_edges", []))
            if isinstance(amrg_payload.get("relationship_edges"), list)
            else 0,
            "waiver_reason_codes": amrg_payload.get("waiver_reason_codes", []),
        },
        "amrg_decomposer_context": amrg_decomposer_context,
        "instructions": {
            "output": "depth_2_question_decomposition_branches_and_leaves",
            "depth": "exactly branches at depth 1 and required_leaf_questions at depth 2",
            "leaf_budget": COMPACT_DEFAULT_LEAF_BUDGET,
            "make_leaves_question_specific": True,
            "include_research_sufficiency_inputs": [
                "purpose",
                "static_information_weight",
                "leaf_condition_scope",
                "required_evidence_fields",
            ],
            "amrg_allowed_uses": [
                "context_leaf",
                "retrieval_hint",
                "conditional_anchor_dependency_request",
            ],
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
        provider_route=base_context.get("provider_route") or f"{base_context.get('provider', 'openai')}/{base_context['resolved_model_id']}",
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
    return openai_responses_transport_from_env()


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
