"""CLS-008 researcher context isolation audit helpers."""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .assignments import (
    DEFAULT_CONTEXT_ISOLATION_POLICY_ID,
    DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS,
    LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION,
    validate_leaf_research_assignment,
)
from .classification import (
    RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
    RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
    RESEARCHER_NLI_PROMPT_TEMPLATE_ID,
    RESEARCHER_SIDECAR_SCHEMA_VERSION,
)


RESEARCHER_CONTEXT_ISOLATION_SCHEMA_VERSION = "researcher-context-isolation/v1"
RESEARCHER_CONTEXT_ISOLATION_ARTIFACT_TYPE = "researcher_context_isolation_audit"
CLS_008_CONTEXT_ISOLATION_BUILDER_VERSION = "ads-cls-008-researcher-context-isolation/v1"

DEFAULT_ALLOWED_SHARED_REFS = (
    f"prompt-template:{RESEARCHER_NLI_PROMPT_TEMPLATE_ID}",
    f"schema:{RESEARCHER_SIDECAR_SCHEMA_VERSION}",
    f"schema:{RESEARCHER_CLASSIFICATION_SCHEMA_VERSION}",
    f"schema:{RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION}",
)
REQUIRED_SHARED_REFS = (
    f"prompt-template:{RESEARCHER_NLI_PROMPT_TEMPLATE_ID}",
    f"schema:{RESEARCHER_SIDECAR_SCHEMA_VERSION}",
)
FORBIDDEN_REF_SCAN_FIELDS = (
    "sibling_assignment_refs_present",
    "peer_assignment_refs_present",
    "peer_sidecar_refs_present",
    "peer_output_refs_present",
    "aggregate_summary_refs_present",
    "scae_refs_present",
    "prediction_scoring_refs_present",
    "outcome_refs_present",
)
SCAN_REASON_CODES = {
    "sibling_assignment_refs_present": "forbidden_sibling_assignment_ref",
    "peer_assignment_refs_present": "forbidden_peer_assignment_ref",
    "peer_sidecar_refs_present": "forbidden_peer_sidecar_ref",
    "peer_output_refs_present": "forbidden_peer_output_ref",
    "aggregate_summary_refs_present": "forbidden_aggregate_summary_ref",
    "scae_refs_present": "forbidden_scae_ref",
    "prediction_scoring_refs_present": "forbidden_prediction_forecast_replay_scoring_ref",
    "outcome_refs_present": "forbidden_outcome_ref",
}

AGGREGATE_SUMMARY_TOKENS = (
    "aggregate-research-summary",
    "aggregate_research_summary",
    "research-aggregate-summary",
    "research-summary:aggregate",
)
SCAE_TOKENS = (
    "scae:",
    "scae-",
    "/scae/",
    "scae-ledger",
    "scae-policy",
    "ledger:scae",
)
PREDICTION_SCORING_TOKENS = (
    "market-prediction",
    "prediction:",
    "prediction-",
    "forecast:",
    "forecast-",
    "replay-result",
    "replay:",
    "replay-",
    "scoring:",
    "scoring-",
    "scoring/",
    "research-scoring",
    "scorecard:",
)
OUTCOME_TOKENS = (
    "outcome:",
    "outcome-",
    "outcome-scoring",
    "resolved-outcome",
    "resolution-outcome",
)
RESEARCHER_OUTPUT_TOKENS = (
    "artifact:researcher-sidecar/",
    "researcher-sidecar:",
    "artifact:researcher-classification/",
    "researcher-classification:",
    "artifact:researcher-coverage-proof/",
    "researcher-coverage-proof:",
    "coverage-proof-",
)


class ResearcherContextIsolationError(ValueError):
    """Raised when a CLS-008 isolation audit cannot be built."""


@dataclass(frozen=True)
class ResearcherContextIsolationValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_008_CONTEXT_ISOLATION_BUILDER_VERSION,
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256_ref(value: Any) -> bool:
    return (
        _is_non_empty_string(value)
        and str(value).startswith("sha256:")
        and len(str(value)) == 71
        and all(ch in "0123456789abcdef" for ch in str(value)[7:])
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if _is_non_empty_string(item)]


def _unique_sorted_strings(value: Any) -> list[str]:
    return sorted(set(_string_list(value)))


def _assignment_artifact_ref(assignment: dict[str, Any]) -> str | None:
    outputs = assignment.get("artifact_outputs")
    if isinstance(outputs, dict) and _is_non_empty_string(outputs.get("assignment_artifact_ref")):
        return str(outputs["assignment_artifact_ref"])
    if _is_non_empty_string(assignment.get("assignment_id")):
        return f"artifact:leaf-research-assignment/{assignment['assignment_id']}"
    return None


def _own_assignment_refs(assignment: dict[str, Any]) -> set[str]:
    refs = set()
    if _is_non_empty_string(assignment.get("assignment_id")):
        assignment_id = str(assignment["assignment_id"])
        refs.add(assignment_id)
        refs.add(f"artifact:leaf-research-assignment/{assignment_id}")
    artifact_ref = _assignment_artifact_ref(assignment)
    if artifact_ref:
        refs.add(artifact_ref)
    return refs


def _context_isolation(assignment: dict[str, Any]) -> dict[str, Any]:
    context = assignment.get("context_isolation")
    return context if isinstance(context, dict) else {}


def _visible_allowlist(assignment: dict[str, Any]) -> list[str]:
    return _unique_sorted_strings(_context_isolation(assignment).get("visible_artifact_ref_allowlist"))


def _visible_refs_or_allowlist(
    assignment: dict[str, Any],
    visible_artifact_refs: list[str] | None,
) -> list[str]:
    if visible_artifact_refs is None:
        return _visible_allowlist(assignment)
    return _unique_sorted_strings(visible_artifact_refs)


def _allowed_shared_refs_for_assignment(assignment: dict[str, Any]) -> set[str]:
    refs = set(DEFAULT_ALLOWED_SHARED_REFS)
    model_context = assignment.get("model_execution_context")
    if isinstance(model_context, dict) and _is_non_empty_string(model_context.get("prompt_template_id")):
        refs.add(f"prompt-template:{model_context['prompt_template_id']}")
    return refs


def _allowed_shared_refs(
    assignment: dict[str, Any],
    visible_refs: list[str],
    allowed_shared_refs: list[str] | None,
) -> list[str]:
    allowed_candidates = _allowed_shared_refs_for_assignment(assignment)
    if allowed_shared_refs is not None:
        requested = set(_unique_sorted_strings(allowed_shared_refs))
        return sorted(requested & allowed_candidates & set(visible_refs))
    return sorted(allowed_candidates & set(visible_refs))


def _matches_any(ref: str, patterns: Any) -> bool:
    lowered = ref.lower()
    for pattern in _string_list(patterns):
        if fnmatch.fnmatchcase(lowered, pattern.lower()):
            return True
    return False


def _contains_any(ref: str, tokens: tuple[str, ...]) -> bool:
    lowered = ref.lower()
    return any(token in lowered for token in tokens)


def _is_assignment_ref(ref: str) -> bool:
    lowered = ref.lower()
    return (
        "leaf-research-assignment" in lowered
        or lowered.startswith("leaf-assignment-")
        or lowered.startswith("artifact:leaf-assignment/")
    )


def _is_other_assignment_ref(ref: str, assignment: dict[str, Any]) -> bool:
    return _is_assignment_ref(ref) and ref not in _own_assignment_refs(assignment)


def _is_peer_sidecar_ref(ref: str, patterns: Any) -> bool:
    if ref.startswith("schema:"):
        return False
    sidecar_patterns = [
        pattern
        for pattern in _string_list(patterns)
        if "researcher-sidecar" in pattern.lower()
    ]
    return _contains_any(ref, ("artifact:researcher-sidecar/", "researcher-sidecar:")) or _matches_any(
        ref, sidecar_patterns
    )


def _is_researcher_output_ref(ref: str) -> bool:
    if ref.startswith("schema:"):
        return False
    return _contains_any(ref, RESEARCHER_OUTPUT_TOKENS)


def scan_researcher_context_refs(
    visible_artifact_refs: list[str],
    *,
    assignment: dict[str, Any],
    allowed_shared_refs: list[str] | None = None,
    peer_output_refs: list[str] | None = None,
) -> dict[str, bool]:
    """Scan visible refs for CLS-008 forbidden researcher context categories."""

    context = _context_isolation(assignment)
    patterns = context.get("forbidden_artifact_ref_patterns", DEFAULT_FORBIDDEN_ARTIFACT_REF_PATTERNS)
    shared = set(allowed_shared_refs or [])
    known_peer_outputs = set(_unique_sorted_strings(peer_output_refs or []))
    scan = {field: False for field in FORBIDDEN_REF_SCAN_FIELDS}

    for ref in _unique_sorted_strings(visible_artifact_refs):
        if ref in shared:
            continue
        if _is_other_assignment_ref(ref, assignment):
            scan["sibling_assignment_refs_present"] = True
            scan["peer_assignment_refs_present"] = True
        if _is_peer_sidecar_ref(ref, patterns):
            scan["peer_sidecar_refs_present"] = True
            scan["peer_output_refs_present"] = True
        if _is_researcher_output_ref(ref) or ref in known_peer_outputs:
            scan["peer_output_refs_present"] = True
        if _contains_any(ref, AGGREGATE_SUMMARY_TOKENS):
            scan["aggregate_summary_refs_present"] = True
        if _contains_any(ref, SCAE_TOKENS) or _matches_any(ref, ("scae-ledger:*", "scae-policy:*")):
            scan["scae_refs_present"] = True
        if _contains_any(ref, PREDICTION_SCORING_TOKENS) or _matches_any(
            ref, ("market-prediction:*", "replay-result:*")
        ):
            scan["prediction_scoring_refs_present"] = True
        if _contains_any(ref, OUTCOME_TOKENS) or _matches_any(ref, ("outcome-scoring:*", "resolved-outcome:*")):
            scan["outcome_refs_present"] = True

    return scan


def _peer_output_exclusion_proof(
    visible_artifact_refs: list[str],
    peer_output_refs: list[str] | None,
) -> dict[str, Any]:
    peers = _unique_sorted_strings(peer_output_refs or [])
    overlap = sorted(set(visible_artifact_refs) & set(peers))
    return {
        "known_peer_output_refs_digest": _prefixed_sha256(peers),
        "visible_peer_output_overlap_count": len(overlap),
        "visible_peer_output_overlap_digest": _prefixed_sha256(overlap),
    }


def _request_analysis(
    assignment: dict[str, Any],
    *,
    visible_artifact_refs: list[str] | None = None,
    allowed_shared_refs: list[str] | None = None,
    peer_output_refs: list[str] | None = None,
    fresh_context: bool = True,
) -> dict[str, Any]:
    assignment_validation = validate_leaf_research_assignment(assignment)
    context = _context_isolation(assignment)
    visible_refs = _visible_refs_or_allowlist(assignment, visible_artifact_refs)
    allowlist = set(_visible_allowlist(assignment))
    shared_refs = _allowed_shared_refs(assignment, visible_refs, allowed_shared_refs)
    scan = scan_researcher_context_refs(
        visible_refs,
        assignment=assignment,
        allowed_shared_refs=shared_refs,
        peer_output_refs=peer_output_refs,
    )

    reason_codes: set[str] = set()
    messages: list[str] = []
    if not assignment_validation.valid:
        reason_codes.add("assignment_contract_invalid")
        messages.extend(assignment_validation.errors)
    if assignment.get("schema_version") != LEAF_RESEARCH_ASSIGNMENT_SCHEMA_VERSION:
        reason_codes.add("assignment_schema_invalid")
    if context.get("isolation_policy_id") != DEFAULT_CONTEXT_ISOLATION_POLICY_ID:
        reason_codes.add("context_isolation_policy_invalid")
    if context.get("peer_context_allowed") is not False:
        reason_codes.add("peer_context_not_allowed")
    if visible_artifact_refs is not None and not isinstance(visible_artifact_refs, list):
        reason_codes.add("visible_refs_invalid")
    outside_allowlist = sorted(set(visible_refs) - allowlist)
    if outside_allowlist:
        reason_codes.add("visible_refs_outside_allowlist")
    own_assignment_ref = _assignment_artifact_ref(assignment)
    if own_assignment_ref and own_assignment_ref not in visible_refs:
        reason_codes.add("own_assignment_ref_missing")
    if fresh_context is not True:
        reason_codes.add("fresh_context_required")
    missing_shared_refs = sorted(set(REQUIRED_SHARED_REFS) - set(shared_refs))
    if missing_shared_refs:
        reason_codes.add("required_shared_ref_missing")
    if peer_output_refs is not None and not isinstance(peer_output_refs, list):
        reason_codes.add("peer_output_refs_invalid")
    if allowed_shared_refs is not None:
        if not isinstance(allowed_shared_refs, list):
            reason_codes.add("allowed_shared_refs_invalid")
        unknown_shared = sorted(set(_unique_sorted_strings(allowed_shared_refs)) - _allowed_shared_refs_for_assignment(assignment))
        if unknown_shared:
            reason_codes.add("allowed_shared_refs_invalid")

    for field, present in scan.items():
        if present:
            reason_codes.add(SCAN_REASON_CODES[field])

    proof = _peer_output_exclusion_proof(visible_refs, peer_output_refs)
    if proof["visible_peer_output_overlap_count"] > 0:
        reason_codes.add("forbidden_peer_output_ref")

    return {
        "visible_artifact_refs": visible_refs,
        "allowed_shared_refs": shared_refs,
        "forbidden_ref_scan": scan,
        "peer_output_exclusion_proof": proof,
        "reason_codes": sorted(reason_codes),
        "messages": tuple(messages),
    }


def _isolation_audit_id(assignment: dict[str, Any], visible_artifact_refs_digest: str) -> str:
    audit_ref = _context_isolation(assignment).get("isolation_audit_ref")
    if _is_non_empty_string(audit_ref) and str(audit_ref).startswith("researcher-context-isolation"):
        return str(audit_ref)
    seed = {
        "assignment_id": assignment.get("assignment_id"),
        "leaf_id": assignment.get("leaf_id"),
        "visible_artifact_refs_digest": visible_artifact_refs_digest,
    }
    return "researcher-context-isolation-" + hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()[:24]


def _subagent_session_ref(assignment: dict[str, Any], subagent_session_ref: str | None) -> str:
    if _is_non_empty_string(subagent_session_ref):
        return str(subagent_session_ref)
    return f"agent:researcher-swarm:subagent:planned:{assignment.get('assignment_id', 'unknown')}"


def _audit_digest_payload(audit: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(audit)
    payload.pop("audit_digest", None)
    return payload


def compute_researcher_context_isolation_audit_digest(audit: dict[str, Any]) -> str:
    return _prefixed_sha256(_audit_digest_payload(audit))


def build_researcher_context_isolation_audit(
    assignment: dict[str, Any],
    *,
    visible_artifact_refs: list[str] | None = None,
    allowed_shared_refs: list[str] | None = None,
    peer_output_refs: list[str] | None = None,
    fresh_context: bool = True,
    subagent_session_ref: str | None = None,
) -> dict[str, Any]:
    """Build a compact prelaunch researcher-context-isolation/v1 audit."""

    if not isinstance(assignment, dict):
        raise ResearcherContextIsolationError("assignment must be an object")

    analysis = _request_analysis(
        assignment,
        visible_artifact_refs=visible_artifact_refs,
        allowed_shared_refs=allowed_shared_refs,
        peer_output_refs=peer_output_refs,
        fresh_context=fresh_context,
    )
    visible_refs = analysis["visible_artifact_refs"]
    visible_digest = _prefixed_sha256(visible_refs)
    reason_codes = list(analysis["reason_codes"])
    audit = {
        "artifact_type": RESEARCHER_CONTEXT_ISOLATION_ARTIFACT_TYPE,
        "schema_version": RESEARCHER_CONTEXT_ISOLATION_SCHEMA_VERSION,
        "feature_id": "CLS-008",
        "builder_version": CLS_008_CONTEXT_ISOLATION_BUILDER_VERSION,
        "isolation_audit_id": _isolation_audit_id(assignment, visible_digest),
        "case_id": assignment.get("case_id"),
        "dispatch_id": assignment.get("dispatch_id"),
        "assignment_id": assignment.get("assignment_id"),
        "leaf_id": assignment.get("leaf_id"),
        "subagent_session_ref": _subagent_session_ref(assignment, subagent_session_ref),
        "fresh_context": fresh_context is True,
        "visible_artifact_refs": visible_refs,
        "visible_artifact_refs_digest": visible_digest,
        "forbidden_ref_scan": analysis["forbidden_ref_scan"],
        "peer_output_exclusion_proof": analysis["peer_output_exclusion_proof"],
        "allowed_shared_refs": analysis["allowed_shared_refs"],
        "runtime_launch_performed": False,
        "launch_allowed": not reason_codes,
        "reason_codes": reason_codes,
    }
    audit["audit_digest"] = compute_researcher_context_isolation_audit_digest(audit)
    return audit


def validate_researcher_context_isolation_request(
    assignment: Any,
    *,
    visible_artifact_refs: list[str] | None = None,
    allowed_shared_refs: list[str] | None = None,
    peer_output_refs: list[str] | None = None,
    fresh_context: bool = True,
) -> ResearcherContextIsolationValidationResult:
    """Validate assignment context isolation inputs before a subagent launch."""

    if not isinstance(assignment, dict):
        return ResearcherContextIsolationValidationResult(False, ("assignment must be an object",))
    analysis = _request_analysis(
        assignment,
        visible_artifact_refs=visible_artifact_refs,
        allowed_shared_refs=allowed_shared_refs,
        peer_output_refs=peer_output_refs,
        fresh_context=fresh_context,
    )
    reason_codes = tuple(analysis["reason_codes"])
    return ResearcherContextIsolationValidationResult(not reason_codes, reason_codes, analysis["messages"])


def validate_researcher_context_isolation_audit(
    audit: Any,
    *,
    assignment: dict[str, Any] | None = None,
    peer_output_refs: list[str] | None = None,
) -> ResearcherContextIsolationValidationResult:
    """Validate a researcher-context-isolation/v1 audit artifact."""

    errors: list[str] = []
    if not isinstance(audit, dict):
        return ResearcherContextIsolationValidationResult(False, ("audit must be an object",))

    expected_values = {
        "artifact_type": RESEARCHER_CONTEXT_ISOLATION_ARTIFACT_TYPE,
        "schema_version": RESEARCHER_CONTEXT_ISOLATION_SCHEMA_VERSION,
        "feature_id": "CLS-008",
        "builder_version": CLS_008_CONTEXT_ISOLATION_BUILDER_VERSION,
    }
    for field, expected in expected_values.items():
        if audit.get(field) != expected:
            errors.append(f"{field} must be {expected}")

    for field in ("isolation_audit_id", "case_id", "dispatch_id", "assignment_id", "leaf_id", "subagent_session_ref"):
        if not _is_non_empty_string(audit.get(field)):
            errors.append(f"{field} is required")
    if audit.get("fresh_context") is not True and audit.get("fresh_context") is not False:
        errors.append("fresh_context must be a boolean")
    if audit.get("runtime_launch_performed") is not False:
        errors.append("runtime_launch_performed must be false for CLS-008 prelaunch audits")
    if audit.get("launch_allowed") is not True and audit.get("launch_allowed") is not False:
        errors.append("launch_allowed must be a boolean")

    visible_refs = audit.get("visible_artifact_refs")
    if not isinstance(visible_refs, list) or not all(_is_non_empty_string(item) for item in visible_refs):
        errors.append("visible_artifact_refs must be a string list")
        visible_refs = []
    elif visible_refs != sorted(set(str(item) for item in visible_refs)):
        errors.append("visible_artifact_refs must be unique and sorted")
    visible_digest = audit.get("visible_artifact_refs_digest")
    if not _is_sha256_ref(visible_digest):
        errors.append("visible_artifact_refs_digest must be a sha256 ref")
    elif visible_digest != _prefixed_sha256(visible_refs):
        errors.append("visible_artifact_refs_digest does not match visible refs")

    shared_refs = audit.get("allowed_shared_refs")
    if not isinstance(shared_refs, list) or not all(_is_non_empty_string(item) for item in shared_refs):
        errors.append("allowed_shared_refs must be a string list")
        shared_refs = []
    elif shared_refs != sorted(set(str(item) for item in shared_refs)):
        errors.append("allowed_shared_refs must be unique and sorted")
    if set(shared_refs) - set(visible_refs):
        errors.append("allowed_shared_refs must be visible")

    scan = audit.get("forbidden_ref_scan")
    if not isinstance(scan, dict):
        errors.append("forbidden_ref_scan must be an object")
        scan = {}
    for field in FORBIDDEN_REF_SCAN_FIELDS:
        if scan.get(field) is not True and scan.get(field) is not False:
            errors.append(f"forbidden_ref_scan.{field} must be a boolean")

    proof = audit.get("peer_output_exclusion_proof")
    if not isinstance(proof, dict):
        errors.append("peer_output_exclusion_proof must be an object")
        proof = {}
    else:
        for field in ("known_peer_output_refs_digest", "visible_peer_output_overlap_digest"):
            if not _is_sha256_ref(proof.get(field)):
                errors.append(f"peer_output_exclusion_proof.{field} must be a sha256 ref")
        if not isinstance(proof.get("visible_peer_output_overlap_count"), int) or isinstance(
            proof.get("visible_peer_output_overlap_count"), bool
        ):
            errors.append("peer_output_exclusion_proof.visible_peer_output_overlap_count must be an integer")

    reason_codes = audit.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(_is_non_empty_string(item) for item in reason_codes):
        errors.append("reason_codes must be a string list")
        reason_codes = []
    elif reason_codes != sorted(set(str(item) for item in reason_codes)):
        errors.append("reason_codes must be unique and sorted")

    any_forbidden = any(scan.get(field) is True for field in FORBIDDEN_REF_SCAN_FIELDS)
    if audit.get("launch_allowed") is True:
        if audit.get("fresh_context") is not True:
            errors.append("launch_allowed requires fresh_context=true")
        if any_forbidden:
            errors.append("launch_allowed cannot be true with forbidden refs present")
        if reason_codes:
            errors.append("launch_allowed cannot be true with reason_codes")
    elif audit.get("launch_allowed") is False and not reason_codes:
        errors.append("launch_allowed=false requires reason_codes")

    audit_digest = audit.get("audit_digest")
    if not _is_sha256_ref(audit_digest):
        errors.append("audit_digest must be a sha256 ref")
    elif audit_digest != compute_researcher_context_isolation_audit_digest(audit):
        errors.append("audit_digest does not match audit payload")

    if assignment is not None:
        if not isinstance(assignment, dict):
            errors.append("assignment must be an object when provided")
        else:
            for field in ("case_id", "dispatch_id", "assignment_id", "leaf_id"):
                if audit.get(field) != assignment.get(field):
                    errors.append(f"{field} must match assignment")
            analysis = _request_analysis(
                assignment,
                visible_artifact_refs=list(visible_refs),
                allowed_shared_refs=list(shared_refs),
                peer_output_refs=peer_output_refs,
                fresh_context=bool(audit.get("fresh_context")),
            )
            if audit.get("forbidden_ref_scan") != analysis["forbidden_ref_scan"]:
                errors.append("forbidden_ref_scan does not match visible refs")
            if audit.get("allowed_shared_refs") != analysis["allowed_shared_refs"]:
                errors.append("allowed_shared_refs do not match assignment")
            if audit.get("peer_output_exclusion_proof") != analysis["peer_output_exclusion_proof"]:
                errors.append("peer_output_exclusion_proof does not match peer refs")
            if audit.get("reason_codes") != analysis["reason_codes"]:
                errors.append("reason_codes do not match visible refs")
            if audit.get("launch_allowed") != (not analysis["reason_codes"]):
                errors.append("launch_allowed does not match context-isolation analysis")

    return ResearcherContextIsolationValidationResult(not errors, tuple(errors))
