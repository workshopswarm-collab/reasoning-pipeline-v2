"""CLS-005 researcher evidence-review coverage proof helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .assignments import validate_leaf_research_assignment
from .classification import (
    RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION,
    compute_researcher_sidecar_digest,
    validate_researcher_sidecar_v2,
)
from .classification_matrix import compute_materialized_classification_matrix_digest
from .isolation import validate_researcher_context_isolation_audit
from .retrieval import validate_retrieval_packet


RESEARCHER_EVIDENCE_REVIEW_COVERAGE_PROOF_SCHEMA_VERSION = (
    "researcher-evidence-review-coverage-proof/v1"
)
RESEARCHER_EVIDENCE_REVIEW_COVERAGE_BUNDLE_SCHEMA_VERSION = (
    "researcher-evidence-review-coverage-proof-bundle/v1"
)
CLS_005_COVERAGE_PROOF_BUILDER_VERSION = "ads-cls-005-evidence-review-coverage-proof/v1"

ALLOWED_CERTIFICATE_STATUSES = {"certified_high_certainty", "structurally_unanswerable"}
FORBIDDEN_AUTHORITY_TERMS = (
    "probability",
    "fair_value",
    "fair-value",
    "fair value",
    "interval",
    "decision",
    "scae",
)


class ResearcherCoverageProofError(ValueError):
    """Raised when CLS-005 coverage proof construction cannot proceed."""


@dataclass(frozen=True)
class ResearcherCoverageProofValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "validator_version": CLS_005_COVERAGE_PROOF_BUILDER_VERSION,
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
    return (
        _is_non_empty_string(value)
        and str(value).startswith("sha256:")
        and len(str(value)) == 71
        and all(ch in "0123456789abcdef" for ch in str(value)[7:])
    )


def _string_refs(value: Any) -> list[str]:
    if _is_non_empty_string(value):
        return [str(value)]
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if _is_non_empty_string(item):
            refs.append(str(item))
        elif isinstance(item, dict):
            for key in ("evidence_ref", "artifact_ref", "ref"):
                if _is_non_empty_string(item.get(key)):
                    refs.append(str(item[key]))
                    break
    return sorted(set(refs))


def _refs_from(value: dict[str, Any], *fields: str) -> list[str]:
    refs: list[str] = []
    for field in fields:
        refs.extend(_string_refs(value.get(field)))
    return sorted(set(refs))


def _assigned_evidence_refs(assignment: dict[str, Any]) -> list[str]:
    return _refs_from({"refs": assignment.get("assigned_evidence_refs")}, "refs")


def _dicts_by_id(items: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item[key]): item
        for item in items
        if isinstance(item, dict) and _is_non_empty_string(item.get(key))
    }


def _sidecar_proofs_by_id(sidecars: list[dict[str, Any]]) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    proofs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for sidecar in sidecars:
        for proof in sidecar.get("coverage_proofs", []):
            if not isinstance(proof, dict) or not _is_non_empty_string(proof.get("coverage_proof_id")):
                continue
            proof_id = str(proof["coverage_proof_id"])
            if proof_id in proofs:
                raise ResearcherCoverageProofError(f"duplicate coverage proof id: {proof_id}")
            proofs[proof_id] = (sidecar, proof)
    return proofs


def _matrix_classified_evidence_refs(
    classification_matrix: dict[str, Any],
    *,
    coverage_proof_ref: str,
    sidecar_id: str,
    leaf_id: str,
) -> list[str]:
    refs = [
        str(row["evidence_ref"])
        for row in classification_matrix.get("classification_slices", [])
        if isinstance(row, dict)
        and row.get("coverage_proof_ref") == coverage_proof_ref
        and row.get("sidecar_id") == sidecar_id
        and row.get("leaf_id") == leaf_id
        and _is_non_empty_string(row.get("evidence_ref"))
    ]
    return sorted(set(refs))


def _matrix_coverage_slice_by_proof_id(classification_matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _dicts_by_id(classification_matrix.get("coverage_proof_slices"), "coverage_proof_id")


def _forbidden_authority_term_errors(value: Any, path: str = "bundle") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(term in lowered for term in FORBIDDEN_AUTHORITY_TERMS):
                errors.append(f"{path}.{key} contains forbidden authority term")
            errors.extend(_forbidden_authority_term_errors(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            errors.extend(_forbidden_authority_term_errors(child, f"{path}[{idx}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        if any(term in lowered for term in FORBIDDEN_AUTHORITY_TERMS):
            errors.append(f"{path} contains forbidden authority term")
    return errors


def _validate_source_inputs(
    *,
    qdt: dict[str, Any] | None,
    sidecars: list[dict[str, Any]],
    classification_matrix: dict[str, Any],
    assignments: list[dict[str, Any]],
    isolation_audits: list[dict[str, Any]],
    retrieval_packet: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, tuple[dict[str, Any], dict[str, Any]]],
]:
    if not isinstance(sidecars, list) or not sidecars:
        raise ResearcherCoverageProofError("sidecars must be a non-empty list")
    if not isinstance(classification_matrix, dict):
        raise ResearcherCoverageProofError("classification_matrix must be an object")
    if classification_matrix.get("feature_id") != "CLS-003":
        raise ResearcherCoverageProofError("classification_matrix feature_id must be CLS-003")
    expected_matrix_digest = compute_materialized_classification_matrix_digest(
        classification_matrix.get("classification_slices", []),
        classification_matrix.get("provenance_slices", []),
        classification_matrix.get("coverage_proof_slices", []),
    )
    if classification_matrix.get("matrix_digest") != expected_matrix_digest:
        raise ResearcherCoverageProofError("classification_matrix digest does not match rows")
    if not isinstance(assignments, list) or not assignments:
        raise ResearcherCoverageProofError("assignments must be a non-empty list")
    if not isinstance(isolation_audits, list) or not isolation_audits:
        raise ResearcherCoverageProofError("isolation_audits must be a non-empty list")
    if not isinstance(retrieval_packet, dict):
        raise ResearcherCoverageProofError("retrieval_packet must be an object")

    packet_validation = validate_retrieval_packet(retrieval_packet)
    if not packet_validation.valid:
        raise ResearcherCoverageProofError("retrieval_packet invalid: " + "; ".join(packet_validation.errors))
    if retrieval_packet.get("research_sufficiency_summary", {}).get("classification_dispatch_status") != "allowed":
        raise ResearcherCoverageProofError("RET-008 classification dispatch must be allowed")

    sidecars_by_id = _dicts_by_id(sidecars, "sidecar_id")
    matrix_source_ids = {
        str(item["sidecar_id"])
        for item in classification_matrix.get("source_sidecars", [])
        if isinstance(item, dict) and _is_non_empty_string(item.get("sidecar_id"))
    }
    if matrix_source_ids != set(sidecars_by_id):
        raise ResearcherCoverageProofError("sidecars must exactly match classification_matrix.source_sidecars")
    for item in classification_matrix.get("source_sidecars", []):
        if not isinstance(item, dict) or not _is_non_empty_string(item.get("sidecar_id")):
            continue
        sidecar = sidecars_by_id[str(item["sidecar_id"])]
        if sidecar.get("sidecar_digest") != item.get("sidecar_digest"):
            raise ResearcherCoverageProofError(f"{item['sidecar_id']}: sidecar digest does not match matrix")
        if compute_researcher_sidecar_digest(sidecar) != sidecar.get("sidecar_digest"):
            raise ResearcherCoverageProofError(f"{item['sidecar_id']}: sidecar digest does not match payload")
        if qdt is not None:
            sidecar_validation = validate_researcher_sidecar_v2(sidecar, qdt)
            if not sidecar_validation.valid:
                raise ResearcherCoverageProofError(
                    f"{item['sidecar_id']}: sidecar invalid: " + "; ".join(sidecar_validation.errors)
                )
        if sidecar.get("supplemental_evidence_refs"):
            raise ResearcherCoverageProofError(f"{item['sidecar_id']}: supplemental evidence requires CLS-004")

    assignments_by_id = _dicts_by_id(assignments, "assignment_id")
    if len(assignments_by_id) != len(assignments):
        raise ResearcherCoverageProofError("assignments contain duplicate or missing assignment_id values")
    for assignment in assignments:
        assignment_validation = validate_leaf_research_assignment(assignment)
        if not assignment_validation.valid:
            raise ResearcherCoverageProofError(
                f"{assignment.get('assignment_id')}: assignment invalid: " + "; ".join(assignment_validation.errors)
            )

    audits_by_assignment = _dicts_by_id(isolation_audits, "assignment_id")
    if set(audits_by_assignment) != set(assignments_by_id):
        raise ResearcherCoverageProofError("isolation audits must exactly match assignment ids")
    for assignment_id, audit in audits_by_assignment.items():
        audit_validation = validate_researcher_context_isolation_audit(
            audit,
            assignment=assignments_by_id[assignment_id],
        )
        if not audit_validation.valid:
            raise ResearcherCoverageProofError(
                f"{assignment_id}: isolation audit invalid: " + "; ".join(audit_validation.errors)
            )
        if audit.get("launch_allowed") is not True:
            raise ResearcherCoverageProofError(f"{assignment_id}: isolation audit is not launch allowed")

    certificates_by_id = _dicts_by_id(retrieval_packet.get("leaf_research_sufficiency_certificates"), "certificate_id")
    if not certificates_by_id:
        raise ResearcherCoverageProofError("RET-008 certificates are required")

    return assignments_by_id, audits_by_assignment, certificates_by_id, _sidecar_proofs_by_id(sidecars)


def _append_set_errors(
    errors: list[str],
    *,
    reason_code: str,
    values: set[str],
) -> None:
    if values:
        errors.append(f"{reason_code}: " + ", ".join(sorted(values)))


def _build_assignment_coverage_record(
    *,
    assignment: dict[str, Any],
    audit: dict[str, Any],
    certificate: dict[str, Any],
    sidecar: dict[str, Any],
    proof: dict[str, Any],
    coverage_slice: dict[str, Any],
    classification_matrix: dict[str, Any],
) -> dict[str, Any]:
    proof_ref = str(proof["coverage_proof_id"])
    sidecar_id = str(sidecar["sidecar_id"])
    leaf_id = str(assignment["leaf_id"])
    assigned_refs = set(_assigned_evidence_refs(assignment))
    proof_assigned_refs = set(_refs_from(proof, "evidence_refs_assigned"))
    reviewed_refs = set(_refs_from(proof, "evidence_refs_reviewed"))
    certificate_refs = set(_refs_from(certificate, "evidence_refs"))
    classified_refs = set(
        _matrix_classified_evidence_refs(
            classification_matrix,
            coverage_proof_ref=proof_ref,
            sidecar_id=sidecar_id,
            leaf_id=leaf_id,
        )
    )
    assignment_requirements = set(_refs_from(assignment, "sufficiency_requirement_refs"))
    reviewed_requirements = set(_refs_from(proof, "requirements_reviewed"))
    answered_requirements = set(_refs_from(proof, "requirements_answered"))
    unanswered_requirements = set(_refs_from(proof, "requirements_unanswered"))
    required_value_fields = set(_refs_from(assignment, "required_value_field_ids"))
    extracted_value_fields = set(_refs_from(proof, "required_value_fields_extracted"))
    required_negative_checks = set(_refs_from(assignment, "required_negative_check_ids"))
    completed_negative_checks = set(_refs_from(proof, "required_negative_checks_completed"))

    errors: list[str] = []
    if proof.get("schema_version") != RESEARCHER_COVERAGE_PROOF_SCHEMA_VERSION:
        errors.append("coverage_proof_schema_invalid")
    if proof_ref != assignment.get("artifact_outputs", {}).get("coverage_proof_ref"):
        errors.append("coverage_proof_ref_does_not_match_assignment_output")
    if proof.get("leaf_id") != assignment.get("leaf_id"):
        errors.append("coverage_proof_leaf_mismatch")
    if proof.get("research_sufficiency_certificate_ref") != assignment.get("research_sufficiency_certificate_ref"):
        errors.append("coverage_proof_certificate_mismatch")
    if certificate.get("certificate_id") != assignment.get("research_sufficiency_certificate_ref"):
        errors.append("assignment_certificate_ref_unknown")
    if certificate.get("classification_dispatch_allowed") is not True:
        errors.append("certificate_dispatch_not_allowed")
    if certificate.get("status") not in ALLOWED_CERTIFICATE_STATUSES:
        errors.append("certificate_status_not_dispatchable")
    if proof.get("retrieval_breadth_coverage_ref") != certificate.get("breadth_coverage_ref"):
        errors.append("coverage_ref_does_not_match_certificate")
    if assignment.get("retrieval_breadth_coverage_ref") != certificate.get("breadth_coverage_ref"):
        errors.append("assignment_coverage_ref_does_not_match_certificate")
    if coverage_slice.get("coverage_proof_id") != proof_ref:
        errors.append("matrix_coverage_slice_missing")
    if coverage_slice.get("does_not_mark_cls005_ready") is not True:
        errors.append("matrix_coverage_slice_must_remain_cls003_support_only")

    _append_set_errors(errors, reason_code="proof_assigned_unassigned_evidence", values=proof_assigned_refs - assigned_refs)
    _append_set_errors(errors, reason_code="assigned_evidence_missing_from_proof", values=assigned_refs - proof_assigned_refs)
    _append_set_errors(errors, reason_code="reviewed_unassigned_evidence", values=reviewed_refs - assigned_refs)
    _append_set_errors(errors, reason_code="assigned_evidence_not_reviewed", values=assigned_refs - reviewed_refs)
    _append_set_errors(errors, reason_code="certificate_evidence_not_assigned", values=certificate_refs - assigned_refs)
    _append_set_errors(errors, reason_code="assigned_evidence_not_certified", values=assigned_refs - certificate_refs)
    _append_set_errors(errors, reason_code="certificate_evidence_not_reviewed", values=certificate_refs - reviewed_refs)
    _append_set_errors(errors, reason_code="classified_evidence_not_assigned", values=classified_refs - assigned_refs)
    _append_set_errors(errors, reason_code="classified_evidence_not_reviewed", values=classified_refs - reviewed_refs)

    certificate_requirement = certificate.get("requirement_ref")
    if _is_non_empty_string(certificate_requirement):
        requirement = str(certificate_requirement)
        if requirement not in assignment_requirements:
            errors.append(f"certificate_requirement_not_assigned: {requirement}")
        if requirement not in reviewed_requirements:
            errors.append(f"certificate_requirement_not_reviewed: {requirement}")
        if certificate.get("status") == "certified_high_certainty" and requirement not in answered_requirements:
            errors.append(f"certificate_requirement_not_answered: {requirement}")
        if certificate.get("status") == "structurally_unanswerable":
            if proof.get("structural_unanswerability_acknowledged") is not True:
                errors.append("structural_unanswerability_not_acknowledged")
            if requirement not in unanswered_requirements:
                errors.append(f"structural_requirement_not_marked_unanswered: {requirement}")

    _append_set_errors(
        errors,
        reason_code="assignment_requirement_not_reviewed",
        values=assignment_requirements - reviewed_requirements,
    )
    if certificate.get("status") == "certified_high_certainty":
        _append_set_errors(
            errors,
            reason_code="required_value_field_not_extracted",
            values=required_value_fields - extracted_value_fields,
        )
        _append_set_errors(
            errors,
            reason_code="required_negative_check_not_completed",
            values=required_negative_checks - completed_negative_checks,
        )

    if errors:
        raise ResearcherCoverageProofError(f"{assignment.get('assignment_id')}: " + "; ".join(errors))

    seed = {
        "assignment_id": assignment.get("assignment_id"),
        "coverage_proof_ref": proof_ref,
        "certificate_ref": certificate.get("certificate_id"),
        "matrix_digest": classification_matrix.get("matrix_digest"),
    }
    record = {
        "artifact_type": "researcher_evidence_review_coverage_proof",
        "schema_version": RESEARCHER_EVIDENCE_REVIEW_COVERAGE_PROOF_SCHEMA_VERSION,
        "feature_id": "CLS-005",
        "builder_version": CLS_005_COVERAGE_PROOF_BUILDER_VERSION,
        "proof_id": _sha_id("researcher-evidence-review-coverage-proof", seed),
        "case_id": assignment.get("case_id"),
        "dispatch_id": assignment.get("dispatch_id"),
        "leaf_id": assignment.get("leaf_id"),
        "assignment_id": assignment.get("assignment_id"),
        "assignment_digest": assignment.get("assignment_digest"),
        "assignment_role": assignment.get("assignment_role"),
        "attempt_index": assignment.get("attempt_index"),
        "isolation_audit_ref": audit.get("isolation_audit_id"),
        "isolation_audit_digest": audit.get("audit_digest"),
        "sidecar_id": sidecar.get("sidecar_id"),
        "sidecar_digest": sidecar.get("sidecar_digest"),
        "coverage_proof_ref": proof_ref,
        "coverage_proof_slice_ref": coverage_slice.get("slice_id"),
        "classification_matrix_id": classification_matrix.get("matrix_id"),
        "classification_matrix_digest": classification_matrix.get("matrix_digest"),
        "research_sufficiency_certificate_ref": certificate.get("certificate_id"),
        "certificate_status": certificate.get("status"),
        "retrieval_breadth_coverage_ref": certificate.get("breadth_coverage_ref"),
        "assigned_evidence_refs": sorted(assigned_refs),
        "reviewed_evidence_refs": sorted(reviewed_refs),
        "certificate_evidence_refs": sorted(certificate_refs),
        "classified_evidence_refs": sorted(classified_refs),
        "requirements_reviewed": sorted(reviewed_requirements),
        "requirements_answered": sorted(answered_requirements),
        "requirements_unanswered": sorted(unanswered_requirements),
        "required_value_fields": sorted(required_value_fields),
        "required_value_fields_extracted": sorted(extracted_value_fields),
        "required_negative_checks": sorted(required_negative_checks),
        "required_negative_checks_completed": sorted(completed_negative_checks),
        "coverage_status": "complete",
        "reason_codes": [],
        "authority_boundary": {
            "numeric_estimate_authority": False,
            "pricing_authority": False,
            "range_estimate_authority": False,
            "market_action_authority": False,
            "downstream_ledger_authority": False,
        },
    }
    record["proof_digest"] = _prefixed_sha256(record)
    return record


def compute_researcher_coverage_proof_bundle_digest(bundle: dict[str, Any]) -> str:
    payload = copy.deepcopy(bundle)
    payload.pop("bundle_digest", None)
    return _prefixed_sha256(payload)


def build_researcher_evidence_review_coverage_proof_bundle(
    *,
    sidecars: list[dict[str, Any]],
    classification_matrix: dict[str, Any],
    assignments: list[dict[str, Any]],
    isolation_audits: list[dict[str, Any]],
    retrieval_packet: dict[str, Any],
    qdt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic CLS-005 evidence-review coverage proof records."""

    assignments_by_id, audits_by_assignment, certificates_by_id, proof_by_id = _validate_source_inputs(
        qdt=qdt,
        sidecars=sidecars,
        classification_matrix=classification_matrix,
        assignments=assignments,
        isolation_audits=isolation_audits,
        retrieval_packet=retrieval_packet,
    )
    coverage_slices = _matrix_coverage_slice_by_proof_id(classification_matrix)
    extra_matrix_proofs = sorted(set(coverage_slices) - set(proof_by_id))
    if extra_matrix_proofs:
        raise ResearcherCoverageProofError(
            "matrix coverage proof slices without sidecar proofs: " + ", ".join(extra_matrix_proofs)
        )
    classification_proof_refs = {
        str(row["coverage_proof_ref"])
        for row in classification_matrix.get("classification_slices", [])
        if isinstance(row, dict) and _is_non_empty_string(row.get("coverage_proof_ref"))
    }
    extra_classification_proofs = sorted(classification_proof_refs - set(proof_by_id))
    if extra_classification_proofs:
        raise ResearcherCoverageProofError(
            "matrix classification slices without sidecar proofs: " + ", ".join(extra_classification_proofs)
        )

    records: list[dict[str, Any]] = []
    seen_proofs: set[str] = set()
    for assignment_id, assignment in sorted(assignments_by_id.items()):
        proof_ref = assignment.get("artifact_outputs", {}).get("coverage_proof_ref")
        if not _is_non_empty_string(proof_ref):
            raise ResearcherCoverageProofError(f"{assignment_id}: assignment coverage proof ref is required")
        if str(proof_ref) not in proof_by_id:
            raise ResearcherCoverageProofError(f"{assignment_id}: missing sidecar coverage proof {proof_ref}")
        if str(proof_ref) not in coverage_slices:
            raise ResearcherCoverageProofError(f"{assignment_id}: missing matrix coverage proof slice {proof_ref}")
        sidecar, proof = proof_by_id[str(proof_ref)]
        certificate_ref = assignment.get("research_sufficiency_certificate_ref")
        if not _is_non_empty_string(certificate_ref) or str(certificate_ref) not in certificates_by_id:
            raise ResearcherCoverageProofError(f"{assignment_id}: unknown research sufficiency certificate")
        records.append(
            _build_assignment_coverage_record(
                assignment=assignment,
                audit=audits_by_assignment[assignment_id],
                certificate=certificates_by_id[str(certificate_ref)],
                sidecar=sidecar,
                proof=proof,
                coverage_slice=coverage_slices[str(proof_ref)],
                classification_matrix=classification_matrix,
            )
        )
        seen_proofs.add(str(proof_ref))

    unused_proofs = sorted(set(proof_by_id) - seen_proofs)
    if unused_proofs:
        raise ResearcherCoverageProofError("sidecar coverage proofs without assignments: " + ", ".join(unused_proofs))

    records.sort(key=lambda item: (str(item["assignment_id"]), str(item["proof_id"])))
    seed = {
        "case_id": retrieval_packet.get("case_id"),
        "dispatch_id": retrieval_packet.get("dispatch_id"),
        "record_digests": [record["proof_digest"] for record in records],
    }
    bundle = {
        "artifact_type": "researcher_evidence_review_coverage_proof_bundle",
        "schema_version": RESEARCHER_EVIDENCE_REVIEW_COVERAGE_BUNDLE_SCHEMA_VERSION,
        "feature_id": "CLS-005",
        "builder_version": CLS_005_COVERAGE_PROOF_BUILDER_VERSION,
        "bundle_id": _sha_id("researcher-evidence-review-coverage-bundle", seed),
        "case_id": retrieval_packet.get("case_id"),
        "dispatch_id": retrieval_packet.get("dispatch_id"),
        "coverage_proofs": records,
        "source_sidecars": [
            {"sidecar_id": item["sidecar_id"], "sidecar_digest": item["sidecar_digest"]}
            for item in sorted(
                (
                    {"sidecar_id": sidecar["sidecar_id"], "sidecar_digest": sidecar["sidecar_digest"]}
                    for sidecar in sidecars
                ),
                key=lambda item: str(item["sidecar_id"]),
            )
        ],
        "source_matrix": {
            "matrix_id": classification_matrix.get("matrix_id"),
            "matrix_digest": classification_matrix.get("matrix_digest"),
        },
        "source_assignments": [
            {
                "assignment_id": assignment["assignment_id"],
                "assignment_digest": assignment["assignment_digest"],
            }
            for assignment in sorted(assignments, key=lambda item: str(item["assignment_id"]))
        ],
        "source_isolation_audits": [
            {
                "isolation_audit_id": audit["isolation_audit_id"],
                "audit_digest": audit["audit_digest"],
            }
            for audit in sorted(isolation_audits, key=lambda item: str(item["isolation_audit_id"]))
        ],
        "source_certificates": [
            {
                "certificate_id": certificate["certificate_id"],
                "certificate_status": certificate["status"],
            }
            for certificate in sorted(certificates_by_id.values(), key=lambda item: str(item["certificate_id"]))
        ],
        "coverage_summary": {
            "proof_count": len(records),
            "leaf_count": len({record["leaf_id"] for record in records}),
            "all_assigned_evidence_reviewed": True,
            "all_certificate_evidence_reviewed": True,
            "all_required_outputs_addressed": True,
            "all_context_isolation_audits_launch_allowed": True,
        },
        "authority_boundary": {
            "numeric_estimate_authority": False,
            "pricing_authority": False,
            "range_estimate_authority": False,
            "market_action_authority": False,
            "downstream_ledger_authority": False,
        },
        "scope_boundaries": {
            "implements": ["CLS-005"],
            "excludes": ["CLS-007", "VER-003", "VER-004", "numeric_ledger_readiness", "runtime_spawning"],
        },
    }
    bundle["bundle_digest"] = compute_researcher_coverage_proof_bundle_digest(bundle)
    validation = validate_researcher_evidence_review_coverage_proof_bundle(bundle)
    if not validation.valid:
        raise ResearcherCoverageProofError("; ".join(validation.errors))
    return bundle


def validate_researcher_evidence_review_coverage_proof_bundle(
    bundle: Any,
) -> ResearcherCoverageProofValidationResult:
    """Validate the CLS-005 bundle artifact and its no-authority boundary."""

    errors: list[str] = []
    if not isinstance(bundle, dict):
        return ResearcherCoverageProofValidationResult(False, ("bundle must be an object",))
    expected = {
        "artifact_type": "researcher_evidence_review_coverage_proof_bundle",
        "schema_version": RESEARCHER_EVIDENCE_REVIEW_COVERAGE_BUNDLE_SCHEMA_VERSION,
        "feature_id": "CLS-005",
        "builder_version": CLS_005_COVERAGE_PROOF_BUILDER_VERSION,
    }
    for field, value in expected.items():
        if bundle.get(field) != value:
            errors.append(f"{field} must be {value}")
    for field in ("bundle_id", "case_id", "dispatch_id"):
        if not _is_non_empty_string(bundle.get(field)):
            errors.append(f"{field} is required")
    records = bundle.get("coverage_proofs")
    if not isinstance(records, list) or not records:
        errors.append("coverage_proofs must be a non-empty list")
        records = []
    seen_ids: set[str] = set()
    for idx, record in enumerate(records):
        path = f"coverage_proofs[{idx}]"
        if not isinstance(record, dict):
            errors.append(f"{path} must be an object")
            continue
        if record.get("schema_version") != RESEARCHER_EVIDENCE_REVIEW_COVERAGE_PROOF_SCHEMA_VERSION:
            errors.append(f"{path}.schema_version must be {RESEARCHER_EVIDENCE_REVIEW_COVERAGE_PROOF_SCHEMA_VERSION}")
        if record.get("feature_id") != "CLS-005":
            errors.append(f"{path}.feature_id must be CLS-005")
        for field in (
            "proof_id",
            "case_id",
            "dispatch_id",
            "leaf_id",
            "assignment_id",
            "assignment_digest",
            "isolation_audit_ref",
            "isolation_audit_digest",
            "sidecar_id",
            "sidecar_digest",
            "coverage_proof_ref",
            "coverage_proof_slice_ref",
            "classification_matrix_id",
            "classification_matrix_digest",
            "research_sufficiency_certificate_ref",
            "certificate_status",
            "retrieval_breadth_coverage_ref",
        ):
            if not _is_non_empty_string(record.get(field)):
                errors.append(f"{path}.{field} is required")
        if record.get("coverage_status") != "complete":
            errors.append(f"{path}.coverage_status must be complete")
        if record.get("reason_codes") != []:
            errors.append(f"{path}.reason_codes must be empty")
        if record.get("certificate_status") not in ALLOWED_CERTIFICATE_STATUSES:
            errors.append(f"{path}.certificate_status is invalid")
        for field in (
            "assigned_evidence_refs",
            "reviewed_evidence_refs",
            "certificate_evidence_refs",
            "classified_evidence_refs",
            "requirements_reviewed",
            "requirements_answered",
            "requirements_unanswered",
            "required_value_fields",
            "required_value_fields_extracted",
            "required_negative_checks",
            "required_negative_checks_completed",
        ):
            if not isinstance(record.get(field), list):
                errors.append(f"{path}.{field} must be a list")
        proof_id = record.get("proof_id")
        if _is_non_empty_string(proof_id):
            if str(proof_id) in seen_ids:
                errors.append(f"{path}.proof_id is duplicated")
            seen_ids.add(str(proof_id))
        if record.get("case_id") != bundle.get("case_id"):
            errors.append(f"{path}.case_id must match bundle")
        if record.get("dispatch_id") != bundle.get("dispatch_id"):
            errors.append(f"{path}.dispatch_id must match bundle")
        proof_digest = record.get("proof_digest")
        if not _is_sha256_ref(proof_digest):
            errors.append(f"{path}.proof_digest must be a sha256 ref")
        else:
            payload = copy.deepcopy(record)
            payload.pop("proof_digest", None)
            if proof_digest != _prefixed_sha256(payload):
                errors.append(f"{path}.proof_digest does not match payload")

    summary = bundle.get("coverage_summary")
    if not isinstance(summary, dict):
        errors.append("coverage_summary must be an object")
        summary = {}
    else:
        if summary.get("proof_count") != len(records):
            errors.append("coverage_summary.proof_count must match coverage_proofs")
        for field in (
            "all_assigned_evidence_reviewed",
            "all_certificate_evidence_reviewed",
            "all_required_outputs_addressed",
            "all_context_isolation_audits_launch_allowed",
        ):
            if summary.get(field) is not True:
                errors.append(f"coverage_summary.{field} must be true")

    bundle_digest = bundle.get("bundle_digest")
    if not _is_sha256_ref(bundle_digest):
        errors.append("bundle_digest must be a sha256 ref")
    elif bundle_digest != compute_researcher_coverage_proof_bundle_digest(bundle):
        errors.append("bundle_digest does not match bundle payload")

    errors.extend(_forbidden_authority_term_errors(bundle))
    return ResearcherCoverageProofValidationResult(not errors, tuple(errors))
