"""ADS native research candidate-discovery adapter.

The adapter is deliberately authority-neutral: native GPT may propose URLs and
small candidate notes, but retrieval fetch/admission remains deterministic.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
DECOMPOSER_SCRIPTS = REPO_ROOT / "decomposer" / "scripts"
RESEARCHER_SCRIPTS = REPO_ROOT / "researcher-swarm" / "scripts"
for script_dir in (DECOMPOSER_SCRIPTS, RESEARCHER_SCRIPTS):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from ads_decomposer.model_runtime import (  # noqa: E402
    MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
    ModelRuntimeError,
    Transport,
    canonical_json,
    execute_model_runtime_call_for_lane,
    openclaw_codex_agent_transport_from_env,
    prefixed_sha256,
    resolve_model_runtime_lane,
)

NATIVE_RESEARCH_MODEL_LANE_ID = "native_research_candidate_discovery"
NATIVE_RESEARCH_PROMPT_TEMPLATE_ID = "native-gpt-research/v1"
NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION = "native-research-candidate-discovery/v1"
NATIVE_RESEARCH_RUNTIME_ADAPTER_VERSION = "ads-native-research-runtime-adapter/v1"

NATIVE_ALLOWED_FIELDS = {
    "url",
    "canonical_url",
    "candidate_url",
    "source_label",
    "title",
    "why_it_may_matter",
    "why_may_matter",
    "related_leaf_id",
    "leaf_id",
    "query_variant_id",
    "native_research_attempt_ref",
    "attempt_ref",
    "resolved_model_id",
    "candidate_claim_text",
    "claim_text",
    "uncertainty_notes",
}

NATIVE_FORBIDDEN_KEY_FRAGMENTS = (
    "probability",
    "fair_value",
    "scae_delta",
    "scae_evidence_delta",
    "decision",
    "research_sufficiency",
    "sufficiency_certification",
    "source_class",
    "source_family",
    "claim_family",
    "temporal_safety",
    "temporal_gate",
    "final_authority",
    "admission_status",
    "forecast",
)

NATIVE_RESEARCH_PROMPT_TEMPLATE = {
    "schema_version": "native-research-prompt-template/v1",
    "role": "candidate_url_discovery_only",
    "allowed_fields": sorted(NATIVE_ALLOWED_FIELDS),
    "forbidden_key_fragments": list(NATIVE_FORBIDDEN_KEY_FRAGMENTS),
}


def native_candidate_list(raw_native: Any) -> list[dict[str, Any]]:
    if isinstance(raw_native, dict):
        raw_native = raw_native.get("native_research_candidates") or raw_native.get("candidate_urls") or []
    return [copy.deepcopy(item) for item in raw_native if isinstance(item, dict)] if isinstance(raw_native, list) else []


def _normalized_key(value: Any) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")


def _forbidden_native_output_errors(value: Any, *, path: str = "native_research") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if any(fragment in normalized for fragment in NATIVE_FORBIDDEN_KEY_FRAGMENTS):
                errors.append(f"{path}.{key}: forbidden native authority field")
            errors.extend(_forbidden_native_output_errors(item, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_forbidden_native_output_errors(item, path=f"{path}[{index}]"))
    return errors


def native_candidate_payload_errors(raw_native: Any) -> list[str]:
    errors = _forbidden_native_output_errors(raw_native)
    candidates = native_candidate_list(raw_native)
    if not isinstance(raw_native, (dict, list)):
        errors.append("native_research output must be an object or list")
    if isinstance(raw_native, dict) and not isinstance(
        raw_native.get("native_research_candidates") or raw_native.get("candidate_urls") or [],
        list,
    ):
        errors.append("native_research candidate container must be a list")
    for index, candidate in enumerate(candidates):
        unknown_keys = sorted(set(candidate) - NATIVE_ALLOWED_FIELDS)
        if unknown_keys:
            errors.append(f"candidate[{index}] contains unsupported fields: {', '.join(unknown_keys)}")
        if not str(candidate.get("url") or candidate.get("candidate_url") or candidate.get("canonical_url") or "").strip():
            errors.append(f"candidate[{index}] missing URL")
    return errors


def validate_native_candidate_payload(raw_native: Any) -> tuple[bool, list[str]]:
    errors = native_candidate_payload_errors(raw_native)
    return not errors, errors


def native_runtime_call_summary(runtime_call: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(runtime_call, dict):
        return None
    return {
        "schema_version": "native-research-runtime-call-summary/v1",
        "runtime_call_id": runtime_call.get("runtime_call_id"),
        "model_lane_id": runtime_call.get("model_lane_id"),
        "resolved_model_id": runtime_call.get("resolved_model_id"),
        "provider_route": runtime_call.get("provider_route"),
        "execution_status": runtime_call.get("execution_status"),
        "mode": runtime_call.get("mode"),
        "retry_count": int(runtime_call.get("retry_count") or 0),
        "retry_diagnostics": copy.deepcopy(runtime_call.get("retry_diagnostics") or []),
        "forbidden_output_scan": copy.deepcopy(runtime_call.get("forbidden_output_scan") or {}),
        "runtime_reason_codes": list(runtime_call.get("runtime_reason_codes") or []),
        "provider_status": copy.deepcopy(runtime_call.get("provider_status") or {}),
    }


def _native_research_prompt(request_payload: dict[str, Any]) -> str:
    response_skeleton = {
        "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
        "response_payload": {
            "native_research_candidates": [
                {
                    "url": "https://example.com/source",
                    "source_label": "short source label",
                    "why_it_may_matter": "bounded relevance note",
                    "related_leaf_id": request_payload.get("request_payload", {})
                    .get("query_context", {})
                    .get("leaf_id"),
                    "candidate_claim_text": "candidate claim text only, not final evidence",
                }
            ]
        },
        "provider_status": {"status": "completed"},
    }
    return (
        "You are the ADS native research candidate-discovery transport.\n\n"
        "Return exactly one JSON object and no Markdown. The object must use "
        f"schema_version={MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION!r}. "
        "Its response_payload must contain native_research_candidates: a list "
        "of candidate URL objects. Native research is URL discovery only. Do "
        "not certify source class, source family, claim family, temporal "
        "safety, research sufficiency, forecast probability, fair value, SCAE "
        "delta, or any decision. Do not include forbidden authority fields. "
        "Candidate URLs will be fetched and deterministically validated later.\n\n"
        "Allowed candidate fields:\n"
        + canonical_json(sorted(NATIVE_ALLOWED_FIELDS))
        + "\n\nForbidden key fragments:\n"
        + canonical_json(list(NATIVE_FORBIDDEN_KEY_FRAGMENTS))
        + "\n\nRequired response skeleton:\n"
        + canonical_json(response_skeleton)
        + "\n\nRuntime transport request JSON:\n"
        + canonical_json(request_payload)
    )


def _native_request_payload(query_context: dict[str, Any], query_variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "native-research-candidate-discovery-request/v1",
        "adapter_version": NATIVE_RESEARCH_RUNTIME_ADAPTER_VERSION,
        "model_lane_id": NATIVE_RESEARCH_MODEL_LANE_ID,
        "query_context": copy.deepcopy(query_context),
        "query_variant": copy.deepcopy(query_variant),
        "candidate_output_contract": copy.deepcopy(NATIVE_RESEARCH_PROMPT_TEMPLATE),
        "authority_boundary": {
            "candidate_url_discovery_only": True,
            "source_metadata_final_authority": False,
            "claim_family_final_authority": False,
            "temporal_safety_final_authority": False,
            "research_sufficiency_authority": False,
            "forecast_authority": False,
        },
    }


class NativeResearchCandidateProvider:
    """Callable provider used by Orchestrator live retrieval."""

    def __init__(
        self,
        *,
        lane: dict[str, Any] | None = None,
        mode: str = "live",
        transport: Transport | None = None,
        fixture_response: Any | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.lane = lane
        self.mode = mode
        self.transport = transport
        self.fixture_response = fixture_response
        self.sleep_fn = sleep_fn

    def _lane(self) -> dict[str, Any]:
        return self.lane or resolve_model_runtime_lane(NATIVE_RESEARCH_MODEL_LANE_ID)

    def _transport(self, lane: dict[str, Any]) -> Transport | None:
        if self.mode != "live":
            return self.transport
        return self.transport or openclaw_codex_agent_transport_from_env(
            agent_id=str(lane.get("runtime_agent_id") or "researcher-swarm"),
            session_key_prefix="ads-native-research",
            model=str(lane.get("resolved_model_id") or "gpt-5.5-high"),
            prompt_builder=_native_research_prompt,
        )

    def __call__(self, query_context: dict[str, Any], query_variant: dict[str, Any]) -> dict[str, Any]:
        lane = self._lane()
        request_payload = _native_request_payload(query_context, query_variant)
        result = execute_model_runtime_call_for_lane(
            lane=lane,
            prompt_template_id=NATIVE_RESEARCH_PROMPT_TEMPLATE_ID,
            prompt_template_sha256=prefixed_sha256(NATIVE_RESEARCH_PROMPT_TEMPLATE),
            input_manifest_refs=[
                str(query_context.get("query_context_ref") or query_context.get("leaf_id") or ""),
                str(query_variant.get("query_variant_id") or ""),
            ],
            output_schema_version=NATIVE_RESEARCH_CANDIDATE_DISCOVERY_SCHEMA_VERSION,
            request_payload=request_payload,
            mode=self.mode,
            fixture_response=self.fixture_response,
            transport=self._transport(lane),
            output_validator=validate_native_candidate_payload,
            repairer=None,
            sleep_fn=self.sleep_fn,
        )
        candidates: list[dict[str, Any]] = []
        for candidate in native_candidate_list(result.response_payload):
            enriched = copy.deepcopy(candidate)
            enriched.setdefault("leaf_id", query_context.get("leaf_id"))
            enriched.setdefault("related_leaf_id", query_context.get("leaf_id"))
            enriched.setdefault("query_variant_id", query_variant.get("query_variant_id"))
            enriched.setdefault("native_research_attempt_ref", result.runtime_call.get("runtime_call_id"))
            candidates.append(enriched)
        return {
            "schema_version": "ads-native-research-provider-result/v1",
            "native_research_candidates": candidates,
            "model_runtime_call": native_runtime_call_summary(result.runtime_call),
        }


def build_provider() -> NativeResearchCandidateProvider:
    return NativeResearchCandidateProvider()


def build_native_candidate_provider() -> NativeResearchCandidateProvider:
    return build_provider()


__all__ = [
    "NATIVE_ALLOWED_FIELDS",
    "NATIVE_FORBIDDEN_KEY_FRAGMENTS",
    "NATIVE_RESEARCH_MODEL_LANE_ID",
    "NativeResearchCandidateProvider",
    "build_native_candidate_provider",
    "build_provider",
    "native_candidate_list",
    "native_candidate_payload_errors",
    "native_runtime_call_summary",
    "validate_native_candidate_payload",
]
