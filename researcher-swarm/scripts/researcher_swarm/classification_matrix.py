"""CLS-003 researcher evidence classification matrix materialization."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .classification import (
    RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
    validate_researcher_sidecar_v2,
)
from .retrieval import validate_retrieval_packet
from .supplemental import (
    SupplementalEvidenceError,
    normalized_supplemental_records_by_ref,
    supplemental_record_as_classification_evidence,
    supplemental_record_as_provenance,
)


CLASSIFICATION_MATRIX_SCHEMA_VERSION = "researcher-classification-matrix/v1"
CLASSIFICATION_SLICE_SCHEMA_VERSION = "classification-lane-evidence-classification-slice/v1"
PROVENANCE_SLICE_SCHEMA_VERSION = "classification-lane-evidence-provenance-slice/v1"
COVERAGE_PROOF_SLICE_SCHEMA_VERSION = "researcher-leaf-coverage-proof-slice/v1"
CLS_003_MATRIX_MATERIALIZER_VERSION = "ads-cls-003-classification-matrix-materializer/v1"

CLASSIFICATION_SLICE_SURFACE = "classification_lane_evidence_classification_slices"
PROVENANCE_SLICE_SURFACE = "classification_lane_evidence_provenance_slices"
COVERAGE_PROOF_SURFACE = "researcher_leaf_coverage_proofs"
SPEC_CLASSIFICATION_SLICE_SURFACE = "persona_evidence_classification_slices"
SPEC_PROVENANCE_SLICE_SURFACE = "persona_evidence_provenance_slices"

COMPOSITE_CLAIM_POLICIES = {"split", "reject"}


class ClassificationMatrixError(ValueError):
    """Raised when CLS-003 matrix materialization cannot proceed."""


@dataclass(frozen=True)
class RetrievalLookups:
    evidence_by_ref: dict[str, dict[str, Any]]
    chunks_by_ref: dict[str, dict[str, Any]]
    provenance_by_id: dict[str, dict[str, Any]]
    provenance_by_evidence_ref: dict[str, dict[str, Any]]
    certificate_by_id: dict[str, dict[str, Any]]
    breadth_coverage_by_id: dict[str, dict[str, Any]]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _prefixed_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha_id(prefix: str, value: Any, length: int = 20) -> str:
    return f"{prefix}-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_string_list(value: Any) -> list[str]:
    if _is_non_empty_string(value):
        return [str(value)]
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if _is_non_empty_string(item):
            refs.append(str(item))
        elif isinstance(item, dict):
            for key in ("evidence_ref", "supplemental_evidence_ref", "artifact_ref", "ref"):
                if _is_non_empty_string(item.get(key)):
                    refs.append(str(item[key]))
                    break
    return refs


def _refs_from(value: dict[str, Any], *fields: str) -> list[str]:
    refs: list[str] = []
    for field in fields:
        refs.extend(_as_string_list(value.get(field)))
    return list(dict.fromkeys(refs))


def _classification_evidence_refs(classification: dict[str, Any]) -> list[str]:
    return _refs_from(
        classification,
        "evidence_ref",
        "retrieval_evidence_ref",
        "evidence_refs",
        "retrieval_evidence_refs",
    )


def _supplemental_evidence_refs(classification: dict[str, Any]) -> list[str]:
    return _refs_from(
        classification,
        "supplemental_evidence_ref",
        "supplemental_evidence_refs",
    )


def _classification_claim_family_ids(classification: dict[str, Any]) -> list[str]:
    return _refs_from(
        classification,
        "claim_family_id",
        "claim_family_ids",
        "claim_family_ref",
        "claim_family_refs",
    )


def _lookup_qdt_leaves(qdt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(leaf["leaf_id"]): leaf
        for leaf in qdt.get("required_leaf_questions", [])
        if isinstance(leaf, dict) and _is_non_empty_string(leaf.get("leaf_id"))
    }


def _materializable_payload(value: dict[str, Any], *drop_fields: str) -> dict[str, Any]:
    payload = copy.deepcopy(value)
    for field in drop_fields:
        payload.pop(field, None)
    return payload


def _build_retrieval_lookups(retrieval_packet: dict[str, Any]) -> RetrievalLookups:
    evidence_by_ref: dict[str, dict[str, Any]] = {}
    for result in retrieval_packet.get("leaf_retrieval_results", []):
        if not isinstance(result, dict):
            continue
        for evidence in result.get("selected_evidence", []):
            if not isinstance(evidence, dict) or not _is_non_empty_string(evidence.get("evidence_ref")):
                continue
            evidence_ref = str(evidence["evidence_ref"])
            if evidence_ref in evidence_by_ref:
                raise ClassificationMatrixError(f"duplicate retrieval evidence ref: {evidence_ref}")
            evidence_by_ref[evidence_ref] = evidence

    chunks_by_ref = {
        str(chunk["chunk_ref"]): chunk
        for chunk in retrieval_packet.get("evidence_chunks", [])
        if isinstance(chunk, dict) and _is_non_empty_string(chunk.get("chunk_ref"))
    }

    provenance_by_id: dict[str, dict[str, Any]] = {}
    provenance_by_evidence_ref: dict[str, dict[str, Any]] = {}
    for provenance in retrieval_packet.get("retrieval_evidence_provenance_slices", []):
        if not isinstance(provenance, dict):
            continue
        if _is_non_empty_string(provenance.get("provenance_id")):
            provenance_by_id[str(provenance["provenance_id"])] = provenance
        if _is_non_empty_string(provenance.get("evidence_ref")):
            provenance_by_evidence_ref[str(provenance["evidence_ref"])] = provenance

    certificate_by_id = {
        str(item["certificate_id"]): item
        for item in retrieval_packet.get("leaf_research_sufficiency_certificates", [])
        if isinstance(item, dict) and _is_non_empty_string(item.get("certificate_id"))
    }
    breadth_coverage_by_id = {
        str(item["coverage_id"]): item
        for item in retrieval_packet.get("retrieval_breadth_coverage_slices", [])
        if isinstance(item, dict) and _is_non_empty_string(item.get("coverage_id"))
    }
    return RetrievalLookups(
        evidence_by_ref=evidence_by_ref,
        chunks_by_ref=chunks_by_ref,
        provenance_by_id=provenance_by_id,
        provenance_by_evidence_ref=provenance_by_evidence_ref,
        certificate_by_id=certificate_by_id,
        breadth_coverage_by_id=breadth_coverage_by_id,
    )


def _build_supplemental_lookups(records: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not records:
        return {}
    try:
        return normalized_supplemental_records_by_ref(records)
    except SupplementalEvidenceError as exc:
        raise ClassificationMatrixError(str(exc)) from exc


def _require_retrieval_packet(retrieval_packet: Any) -> dict[str, Any]:
    if not isinstance(retrieval_packet, dict):
        raise ClassificationMatrixError("retrieval_packet must be an object")
    validation = validate_retrieval_packet(retrieval_packet)
    if not validation.valid:
        raise ClassificationMatrixError("retrieval_packet invalid: " + "; ".join(validation.errors))
    return retrieval_packet


def _validate_sidecar(sidecar: Any, qdt: dict[str, Any]) -> dict[str, Any]:
    validation = validate_researcher_sidecar_v2(sidecar, qdt)
    if not validation.valid:
        raise ClassificationMatrixError("researcher sidecar invalid: " + "; ".join(validation.errors))
    if not isinstance(sidecar, dict):
        raise ClassificationMatrixError("researcher sidecar must be an object")
    return sidecar


def _certificate_for_proof(
    proof: dict[str, Any],
    lookups: RetrievalLookups,
) -> dict[str, Any]:
    cert_ref = proof.get("research_sufficiency_certificate_ref")
    if not _is_non_empty_string(cert_ref):
        raise ClassificationMatrixError(f"{proof.get('coverage_proof_id')}: missing research_sufficiency_certificate_ref")
    certificate = lookups.certificate_by_id.get(str(cert_ref))
    if not certificate:
        raise ClassificationMatrixError(f"{proof.get('coverage_proof_id')}: unknown research sufficiency certificate {cert_ref}")
    return certificate


def _coverage_for_proof(
    proof: dict[str, Any],
    certificate: dict[str, Any],
    lookups: RetrievalLookups,
) -> dict[str, Any]:
    proof_ref = proof.get("retrieval_breadth_coverage_ref")
    cert_ref = certificate.get("breadth_coverage_ref")
    if proof_ref != cert_ref:
        raise ClassificationMatrixError(
            f"{proof.get('coverage_proof_id')}: retrieval_breadth_coverage_ref does not match certificate"
        )
    coverage = lookups.breadth_coverage_by_id.get(str(proof_ref))
    if not coverage:
        raise ClassificationMatrixError(f"{proof.get('coverage_proof_id')}: unknown retrieval breadth coverage {proof_ref}")
    return coverage


def _leaf_requirements(leaf: dict[str, Any]) -> dict[str, Any]:
    requirements = leaf.get("research_sufficiency_requirements")
    return requirements if isinstance(requirements, dict) else {}


def _required_strings(requirements: dict[str, Any], field: str) -> set[str]:
    return {str(item) for item in requirements.get(field, []) if _is_non_empty_string(item)}


def _evidence_family_sets(evidence_refs: set[str], lookups: RetrievalLookups) -> tuple[set[str], set[str], set[str]]:
    source_classes: set[str] = set()
    claim_family_ids: set[str] = set()
    source_family_ids: set[str] = set()
    for evidence_ref in sorted(evidence_refs):
        evidence = lookups.evidence_by_ref.get(evidence_ref)
        if not evidence:
            raise ClassificationMatrixError(f"coverage proof references unknown retrieval evidence {evidence_ref}")
        if _is_non_empty_string(evidence.get("source_class")):
            source_classes.add(str(evidence["source_class"]))
        for claim_family_id in _as_string_list(evidence.get("claim_family_ids")):
            claim_family_ids.add(claim_family_id)
        if _is_non_empty_string(evidence.get("source_family_id")):
            source_family_ids.add(str(evidence["source_family_id"]))
    return source_classes, claim_family_ids, source_family_ids


def _validate_coverage_proof_for_matrix(
    *,
    proof: dict[str, Any],
    certificate: dict[str, Any],
    coverage: dict[str, Any],
    leaf: dict[str, Any],
    lookups: RetrievalLookups,
) -> None:
    proof_id = proof.get("coverage_proof_id")
    assigned = set(_refs_from(proof, "evidence_refs_assigned"))
    reviewed = set(_refs_from(proof, "evidence_refs_reviewed"))
    reviewed_unassigned = sorted(reviewed - assigned)
    if reviewed_unassigned:
        raise ClassificationMatrixError(
            f"{proof_id}: reviewed_unassigned_evidence: " + ", ".join(reviewed_unassigned)
        )

    certificate_evidence_refs = {
        str(ref) for ref in certificate.get("evidence_refs", []) if _is_non_empty_string(ref)
    }
    missing_assigned = sorted(certificate_evidence_refs - assigned)
    missing_reviewed = sorted(certificate_evidence_refs - reviewed)
    if missing_assigned:
        raise ClassificationMatrixError(
            f"{proof_id}: certificate evidence not assigned: " + ", ".join(missing_assigned)
        )
    if missing_reviewed:
        raise ClassificationMatrixError(
            f"{proof_id}: certificate evidence not reviewed: " + ", ".join(missing_reviewed)
        )

    requirement_ref = certificate.get("requirement_ref")
    if _is_non_empty_string(requirement_ref) and str(requirement_ref) not in set(
        _refs_from(proof, "requirements_reviewed")
    ):
        raise ClassificationMatrixError(f"{proof_id}: research_requirement_not_reviewed: {requirement_ref}")

    source_classes, claim_family_ids, source_family_ids = _evidence_family_sets(certificate_evidence_refs, lookups)
    missing_source_classes = sorted(source_classes - set(_refs_from(proof, "source_class_ids_reviewed")))
    missing_claim_families = sorted(claim_family_ids - set(_refs_from(proof, "claim_family_ids_reviewed")))
    missing_source_families = sorted(source_family_ids - set(_refs_from(proof, "source_family_ids_reviewed")))
    if missing_source_classes:
        raise ClassificationMatrixError(f"{proof_id}: source classes not reviewed: " + ", ".join(missing_source_classes))
    if missing_claim_families:
        raise ClassificationMatrixError(f"{proof_id}: claim families not reviewed: " + ", ".join(missing_claim_families))
    if missing_source_families:
        raise ClassificationMatrixError(f"{proof_id}: source families not reviewed: " + ", ".join(missing_source_families))

    requirements = _leaf_requirements(leaf)
    missing_value_fields = sorted(
        _required_strings(requirements, "required_value_fields")
        - set(_refs_from(proof, "required_value_fields_extracted"))
    )
    missing_negative_checks = sorted(
        _required_strings(requirements, "required_negative_checks")
        - set(_refs_from(proof, "required_negative_checks_completed"))
    )
    if missing_value_fields and certificate.get("status") != "structurally_unanswerable":
        raise ClassificationMatrixError(f"{proof_id}: required value fields not extracted: " + ", ".join(missing_value_fields))
    if missing_negative_checks and certificate.get("status") != "structurally_unanswerable":
        raise ClassificationMatrixError(
            f"{proof_id}: required negative checks not completed: " + ", ".join(missing_negative_checks)
        )
    if certificate.get("status") == "structurally_unanswerable" and proof.get("structural_unanswerability_acknowledged") is not True:
        raise ClassificationMatrixError(f"{proof_id}: structural unanswerability not acknowledged")
    if coverage.get("coverage_id") != proof.get("retrieval_breadth_coverage_ref"):
        raise ClassificationMatrixError(f"{proof_id}: coverage proof is not backed by the requested breadth coverage")


def _coverage_proof_slice(
    *,
    sidecar: dict[str, Any],
    proof: dict[str, Any],
    certificate: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    seed = {
        "sidecar_id": sidecar.get("sidecar_id"),
        "coverage_proof_id": proof.get("coverage_proof_id"),
        "research_sufficiency_certificate_ref": certificate.get("certificate_id"),
    }
    slice_id = _sha_id("researcher-coverage-proof-slice", seed)
    row = {
        "artifact_type": "researcher_leaf_coverage_proof_slice",
        "schema_version": COVERAGE_PROOF_SLICE_SCHEMA_VERSION,
        "surface_name": COVERAGE_PROOF_SURFACE,
        "slice_id": slice_id,
        "feature_id": "CLS-003",
        "coverage_feature_scope": "cls003_matrix_completeness_support_only",
        "does_not_mark_cls005_ready": True,
        "sidecar_id": sidecar.get("sidecar_id"),
        "sidecar_digest": sidecar.get("sidecar_digest"),
        "case_id": sidecar.get("case_id"),
        "dispatch_id": sidecar.get("dispatch_id"),
        "leaf_id": proof.get("leaf_id"),
        "coverage_proof_id": proof.get("coverage_proof_id"),
        "research_sufficiency_certificate_ref": certificate.get("certificate_id"),
        "retrieval_breadth_coverage_ref": coverage.get("coverage_id"),
        "certificate_status": certificate.get("status"),
        "classification_dispatch_allowed": certificate.get("classification_dispatch_allowed"),
        "evidence_refs_assigned": sorted(_refs_from(proof, "evidence_refs_assigned")),
        "evidence_refs_reviewed": sorted(_refs_from(proof, "evidence_refs_reviewed")),
        "source_class_ids_reviewed": sorted(_refs_from(proof, "source_class_ids_reviewed")),
        "claim_family_ids_reviewed": sorted(_refs_from(proof, "claim_family_ids_reviewed")),
        "source_family_ids_reviewed": sorted(_refs_from(proof, "source_family_ids_reviewed")),
        "requirements_reviewed": sorted(_refs_from(proof, "requirements_reviewed")),
        "requirements_answered": sorted(_refs_from(proof, "requirements_answered")),
        "requirements_unanswered": sorted(_refs_from(proof, "requirements_unanswered")),
        "required_value_fields_extracted": sorted(_refs_from(proof, "required_value_fields_extracted")),
        "required_negative_checks_completed": sorted(_refs_from(proof, "required_negative_checks_completed")),
        "source_gap_flags": sorted(_refs_from(proof, "source_gap_flags")),
        "coverage_completeness_status": "matrix_complete",
        "materializer_version": CLS_003_MATRIX_MATERIALIZER_VERSION,
    }
    row["coverage_proof_slice_digest"] = _prefixed_sha256(row)
    return row


def _claim_family_resolution_ref(evidence: dict[str, Any], claim_family_id: str) -> str | None:
    claim_ids = _as_string_list(evidence.get("claim_family_ids"))
    resolution_refs = _as_string_list(evidence.get("claim_family_resolution_refs"))
    if claim_family_id in claim_ids and len(claim_ids) == len(resolution_refs):
        return resolution_refs[claim_ids.index(claim_family_id)]
    if len(resolution_refs) == 1:
        return resolution_refs[0]
    return None


def _certified_snippet_lineage(evidence: dict[str, Any], lookups: RetrievalLookups) -> dict[str, Any]:
    chunk_refs = evidence.get("chunk_refs")
    if not isinstance(chunk_refs, list):
        return {}
    for ref in chunk_refs:
        if not _is_non_empty_string(ref):
            continue
        chunk = lookups.chunks_by_ref.get(str(ref))
        if not isinstance(chunk, dict):
            continue
        if chunk.get("evidence_ref") != evidence.get("evidence_ref"):
            continue
        if str(chunk.get("excerpt_policy") or "") == "hash_only":
            continue
        if not _is_non_empty_string(chunk.get("content_artifact_ref")):
            continue
        if not _is_non_empty_string(chunk.get("text_sha256")):
            continue
        return {
            "certified_snippet_ref": str(chunk["chunk_ref"]),
            "certified_snippet_sha256": str(chunk["text_sha256"]),
            "certified_snippet_access_mode": "bounded_certified_snippet",
            "certified_snippet_content_artifact_ref": str(chunk["content_artifact_ref"]),
            "certified_snippet_excerpt_policy": str(chunk.get("excerpt_policy") or "bounded_excerpt"),
        }
    return {}


def _claim_family_ids_for_row(
    *,
    classification: dict[str, Any],
    evidence: dict[str, Any],
    composite_claim_policy: str,
) -> tuple[list[str], str]:
    classification_claims = _classification_claim_family_ids(classification)
    evidence_claims = sorted(set(_as_string_list(evidence.get("claim_family_ids"))))
    if classification_claims:
        unknown = sorted(set(classification_claims) - set(evidence_claims))
        if unknown:
            raise ClassificationMatrixError(
                f"{classification.get('classification_id')}: classification claim family not present in evidence: "
                + ", ".join(unknown)
            )
        return sorted(set(classification_claims)), "classification_claim_family_filter"
    if not evidence_claims:
        raise ClassificationMatrixError(f"{classification.get('classification_id')}: missing claim_family_ids")
    if len(evidence_claims) > 1:
        if composite_claim_policy == "reject":
            raise ClassificationMatrixError(
                f"{classification.get('classification_id')}: composite_multi_claim_classification"
            )
        return evidence_claims, "split_from_evidence_claim_families"
    return evidence_claims, "single_claim_family"


def _resolved_provenance_refs(
    *,
    classification: dict[str, Any],
    evidence: dict[str, Any],
    certificate: dict[str, Any],
    proof: dict[str, Any],
    retrieval_provenance: dict[str, Any],
    claim_family_resolution_ref: str | None,
) -> list[str]:
    known_refs = {
        str(evidence.get("evidence_ref")),
        str(evidence.get("source_metadata_resolution_ref")),
        str(certificate.get("certificate_id")),
        str(proof.get("coverage_proof_id")),
        str(proof.get("retrieval_breadth_coverage_ref")),
        str(retrieval_provenance.get("provenance_id")),
    }
    known_refs.update(_as_string_list(evidence.get("claim_family_resolution_refs")))
    known_refs.update(_as_string_list(retrieval_provenance.get("claim_family_resolution_refs")))
    if claim_family_resolution_ref:
        known_refs.add(claim_family_resolution_ref)
    known_refs = {ref for ref in known_refs if _is_non_empty_string(ref)}

    classification_refs = _refs_from(classification, "provenance_refs")
    if not classification_refs:
        raise ClassificationMatrixError(f"{classification.get('classification_id')}: provenance_refs are required")
    unresolved = sorted(set(classification_refs) - known_refs)
    if unresolved:
        raise ClassificationMatrixError(
            f"{classification.get('classification_id')}: provenance_refs not resolvable: " + ", ".join(unresolved)
        )
    return sorted(set(classification_refs + sorted(known_refs)))


def _classification_slice(
    *,
    sidecar: dict[str, Any],
    classification: dict[str, Any],
    leaf: dict[str, Any],
    evidence: dict[str, Any],
    certificate: dict[str, Any],
    proof: dict[str, Any],
    lookups: RetrievalLookups,
    claim_family_id: str,
    claim_split_status: str,
    claim_family_resolution_ref: str | None,
) -> dict[str, Any]:
    source_family_id = evidence.get("source_family_id")
    if not _is_non_empty_string(source_family_id) or source_family_id == "source-family-unknown":
        raise ClassificationMatrixError(f"{classification.get('classification_id')}: missing source_family_id")
    source_class = evidence.get("source_class")
    if not _is_non_empty_string(source_class) or source_class == "unknown":
        raise ClassificationMatrixError(f"{classification.get('classification_id')}: missing source_class")
    snippet_lineage = _certified_snippet_lineage(evidence, lookups)

    row_seed = {
        "sidecar_id": sidecar.get("sidecar_id"),
        "classification_id": classification.get("classification_id"),
        "leaf_id": classification.get("leaf_id"),
        "condition_scope": classification.get("leaf_condition_scope"),
        "evidence_ref": evidence.get("evidence_ref"),
        "source_family_id": source_family_id,
        "claim_family_id": claim_family_id,
    }
    slice_id = _sha_id("classification-slice", row_seed)
    row = {
        "artifact_type": "classification_lane_evidence_classification_slice",
        "schema_version": CLASSIFICATION_SLICE_SCHEMA_VERSION,
        "surface_name": CLASSIFICATION_SLICE_SURFACE,
        "spec_surface_name": SPEC_CLASSIFICATION_SLICE_SURFACE,
        "slice_id": slice_id,
        "feature_id": "CLS-003",
        "case_id": sidecar.get("case_id"),
        "dispatch_id": sidecar.get("dispatch_id"),
        "sidecar_id": sidecar.get("sidecar_id"),
        "sidecar_digest": sidecar.get("sidecar_digest"),
        "source_sidecar_classification_matrix_digest": sidecar.get("classification_matrix_digest"),
        "researcher_run_id": sidecar.get("researcher_run_id"),
        "persona_id": sidecar.get("persona_id") or sidecar.get("researcher_id") or sidecar.get("sidecar_id"),
        "classification_id": classification.get("classification_id"),
        "classification_schema_version": RESEARCHER_CLASSIFICATION_SCHEMA_VERSION,
        "leaf_id": classification.get("leaf_id"),
        "parent_branch_id": classification.get("parent_branch_id") or leaf.get("parent_branch_id") or evidence.get("parent_branch_id"),
        "question_id": classification.get("leaf_id"),
        "question_text": leaf.get("question_text") or leaf.get("leaf_question") or leaf.get("question"),
        "condition_scope": classification.get("leaf_condition_scope"),
        "condition_ref": classification.get("condition_ref") or classification.get("branch_condition_ref") or leaf.get("condition_ref"),
        "evidence_ref": evidence.get("evidence_ref"),
        "retrieval_transport": evidence.get("retrieval_transport"),
        "source_ref": evidence.get("canonical_source_id") or evidence.get("source_metadata_resolution_ref"),
        "canonical_source_id": evidence.get("canonical_source_id"),
        "source_metadata_resolution_ref": evidence.get("source_metadata_resolution_ref"),
        **snippet_lineage,
        "source_class": source_class,
        "source_family_id": source_family_id,
        "claim_family_id": claim_family_id,
        "claim_family_resolution_ref": claim_family_resolution_ref,
        "claim_split_status": claim_split_status,
        "impact_direction": classification.get("impact_direction"),
        "evidence_strength": classification.get("evidence_strength"),
        "classification_confidence": classification.get("classification_confidence"),
        "classification_quality": classification.get("classification_quality"),
        "classification_acceptance_status": classification.get("classification_acceptance_status"),
        "evidence_delta_eligible_for_scae": bool(
            classification.get("evidence_delta_eligible_for_scae") is True
        ),
        "answer_value_extraction": copy.deepcopy(classification.get("answer_value_extraction")),
        "evidence_quality_dimensions": copy.deepcopy(classification.get("evidence_quality_dimensions")),
        "research_sufficiency_certificate_ref": classification.get("research_sufficiency_certificate_ref"),
        "coverage_proof_ref": classification.get("coverage_proof_ref"),
        "retrieval_breadth_coverage_ref": proof.get("retrieval_breadth_coverage_ref"),
        "model_execution_context_ref": classification.get("model_execution_context_ref") or sidecar.get("model_execution_context_ref"),
        "model_execution_context_sha256": classification.get("model_execution_context_sha256")
        or sidecar.get("model_execution_context_sha256"),
        "content_sha256": evidence.get("content_sha256"),
        "temporal_gate_status": evidence.get("temporal_gate_status"),
        "ledger_ready": (
            classification.get("classification_acceptance_status") == "accepted_for_verification"
            and classification.get("evidence_delta_eligible_for_scae") is True
        ),
        "included_for_scae": (
            classification.get("classification_acceptance_status") == "accepted_for_verification"
            and classification.get("evidence_delta_eligible_for_scae") is True
        ),
        "authority_boundary": {
            "researcher_probability_authority": False,
            "researcher_forecast_authority": False,
            "scae_numeric_authority": False,
        },
        "materializer_version": CLS_003_MATRIX_MATERIALIZER_VERSION,
    }
    if evidence.get("evidence_source_type") == "supplemental":
        row["evidence_source_type"] = "supplemental"
        row["supplemental_evidence_ref"] = evidence.get("supplemental_evidence_ref")
        row["normalized_supplemental_evidence_ref"] = evidence.get("normalized_supplemental_evidence_ref")
    row["classification_slice_digest"] = _prefixed_sha256(row)
    return row


def _provenance_slice(
    *,
    classification_slice: dict[str, Any],
    classification: dict[str, Any],
    evidence: dict[str, Any],
    certificate: dict[str, Any],
    proof: dict[str, Any],
    retrieval_provenance: dict[str, Any],
    claim_family_resolution_ref: str | None,
) -> dict[str, Any]:
    refs = _resolved_provenance_refs(
        classification=classification,
        evidence=evidence,
        certificate=certificate,
        proof=proof,
        retrieval_provenance=retrieval_provenance,
        claim_family_resolution_ref=claim_family_resolution_ref,
    )
    seed = {
        "classification_slice_id": classification_slice["slice_id"],
        "evidence_ref": evidence.get("evidence_ref"),
        "claim_family_id": classification_slice.get("claim_family_id"),
        "source_family_id": classification_slice.get("source_family_id"),
    }
    row = {
        "artifact_type": "classification_lane_evidence_provenance_slice",
        "schema_version": PROVENANCE_SLICE_SCHEMA_VERSION,
        "surface_name": PROVENANCE_SLICE_SURFACE,
        "spec_surface_name": SPEC_PROVENANCE_SLICE_SURFACE,
        "slice_id": _sha_id("classification-provenance-slice", seed),
        "feature_id": "CLS-003",
        "case_id": classification_slice.get("case_id"),
        "dispatch_id": classification_slice.get("dispatch_id"),
        "sidecar_id": classification_slice.get("sidecar_id"),
        "classification_slice_ref": classification_slice["slice_id"],
        "classification_id": classification_slice.get("classification_id"),
        "leaf_id": classification_slice.get("leaf_id"),
        "condition_scope": classification_slice.get("condition_scope"),
        "evidence_ref": evidence.get("evidence_ref"),
        "retrieval_evidence_provenance_ref": retrieval_provenance.get("provenance_id"),
        "source_metadata_resolution_ref": evidence.get("source_metadata_resolution_ref"),
        "source_ref": classification_slice.get("source_ref"),
        "source_class": classification_slice.get("source_class"),
        "source_family_id": classification_slice.get("source_family_id"),
        "claim_family_id": classification_slice.get("claim_family_id"),
        "claim_family_resolution_ref": claim_family_resolution_ref,
        "research_sufficiency_certificate_ref": certificate.get("certificate_id"),
        "coverage_proof_ref": proof.get("coverage_proof_id"),
        "retrieval_breadth_coverage_ref": proof.get("retrieval_breadth_coverage_ref"),
        "provenance_refs": refs,
        "content_sha256": evidence.get("content_sha256"),
        "materializer_version": CLS_003_MATRIX_MATERIALIZER_VERSION,
    }
    if classification_slice.get("evidence_source_type") == "supplemental":
        row["evidence_source_type"] = "supplemental"
        row["supplemental_evidence_ref"] = classification_slice.get("supplemental_evidence_ref")
        row["normalized_supplemental_evidence_ref"] = classification_slice.get("normalized_supplemental_evidence_ref")
    row["provenance_slice_digest"] = _prefixed_sha256(row)
    return row


def compute_materialized_classification_matrix_digest(
    classification_slices: list[dict[str, Any]],
    provenance_slices: list[dict[str, Any]],
    coverage_proof_slices: list[dict[str, Any]],
) -> str:
    """Return a deterministic digest for materialized CLS-003 matrix rows."""

    return _prefixed_sha256(
        {
            "schema_version": "materialized-classification-matrix-digest/v1",
            "classification_slice_schema_version": CLASSIFICATION_SLICE_SCHEMA_VERSION,
            "provenance_slice_schema_version": PROVENANCE_SLICE_SCHEMA_VERSION,
            "coverage_proof_slice_schema_version": COVERAGE_PROOF_SLICE_SCHEMA_VERSION,
            "classification_slices": sorted(
                [_materializable_payload(item, "matrix_digest") for item in classification_slices],
                key=lambda item: (str(item.get("slice_id")), _canonical_json(item)),
            ),
            "provenance_slices": sorted(
                [_materializable_payload(item, "matrix_digest") for item in provenance_slices],
                key=lambda item: (str(item.get("slice_id")), _canonical_json(item)),
            ),
            "coverage_proof_slices": sorted(
                [_materializable_payload(item, "matrix_digest") for item in coverage_proof_slices],
                key=lambda item: (str(item.get("slice_id")), _canonical_json(item)),
            ),
        }
    )


def _classification_output_sort_key(item: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(item.get("sidecar_id") or ""),
        str(item.get("leaf_id") or ""),
        str(item.get("condition_scope") or ""),
        str(item.get("evidence_ref") or ""),
        str(item.get("source_family_id") or ""),
        str(item.get("claim_family_id") or ""),
        str(item.get("slice_id") or ""),
        _canonical_json(item),
    )


def _provenance_output_sort_key(item: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(item.get("sidecar_id") or ""),
        str(item.get("leaf_id") or ""),
        str(item.get("condition_scope") or ""),
        str(item.get("evidence_ref") or ""),
        str(item.get("source_family_id") or ""),
        str(item.get("claim_family_id") or ""),
        str(item.get("classification_slice_ref") or ""),
        str(item.get("slice_id") or ""),
        _canonical_json(item),
    )


def materialize_classification_matrix(
    sidecars: list[dict[str, Any]],
    qdt: dict[str, Any],
    retrieval_packet: dict[str, Any],
    *,
    composite_claim_policy: str = "split",
    normalized_supplemental_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Materialize CLS-003 classification/provenance rows from valid sidecars."""

    if composite_claim_policy not in COMPOSITE_CLAIM_POLICIES:
        raise ClassificationMatrixError("composite_claim_policy must be split or reject")
    if not isinstance(sidecars, list) or not sidecars:
        raise ClassificationMatrixError("sidecars must be a non-empty list")
    if not isinstance(qdt, dict):
        raise ClassificationMatrixError("qdt must be an object")

    packet = _require_retrieval_packet(retrieval_packet)
    lookups = _build_retrieval_lookups(packet)
    supplemental_by_ref = _build_supplemental_lookups(normalized_supplemental_evidence)
    leaves_by_id = _lookup_qdt_leaves(qdt)

    classification_slices: list[dict[str, Any]] = []
    provenance_slices: list[dict[str, Any]] = []
    coverage_proof_slices: list[dict[str, Any]] = []
    proof_by_sidecar_and_id: dict[tuple[str, str], dict[str, Any]] = {}
    seen_grain: set[tuple[str, str, str, str, str, str]] = set()
    validated_sidecars: list[dict[str, Any]] = []
    joined_supplemental_refs: set[str] = set()

    for raw_sidecar in sidecars:
        sidecar = _validate_sidecar(raw_sidecar, qdt)
        validated_sidecars.append(sidecar)
        sidecar_id = str(sidecar["sidecar_id"])
        if sidecar.get("case_id") != packet.get("case_id") or sidecar.get("dispatch_id") != packet.get("dispatch_id"):
            raise ClassificationMatrixError(f"{sidecar_id}: sidecar case/dispatch does not match retrieval packet")

        for proof in sidecar.get("coverage_proofs", []):
            if not isinstance(proof, dict):
                continue
            proof_id = str(proof.get("coverage_proof_id"))
            leaf = leaves_by_id.get(str(proof.get("leaf_id")))
            if not leaf:
                raise ClassificationMatrixError(f"{proof_id}: unknown qdt leaf {proof.get('leaf_id')}")
            certificate = _certificate_for_proof(proof, lookups)
            coverage = _coverage_for_proof(proof, certificate, lookups)
            _validate_coverage_proof_for_matrix(
                proof=proof,
                certificate=certificate,
                coverage=coverage,
                leaf=leaf,
                lookups=lookups,
            )
            proof_by_sidecar_and_id[(sidecar_id, proof_id)] = proof
            coverage_proof_slices.append(
                _coverage_proof_slice(
                    sidecar=sidecar,
                    proof=proof,
                    certificate=certificate,
                    coverage=coverage,
                )
            )

        for classification in sidecar.get("required_question_classifications", []):
            if not isinstance(classification, dict):
                continue
            if classification.get("schema_version") != RESEARCHER_CLASSIFICATION_SCHEMA_VERSION:
                raise ClassificationMatrixError(
                    f"{classification.get('classification_id')}: invalid classification schema version"
                )
            supplemental_refs = _supplemental_evidence_refs(classification)
            if supplemental_refs and not supplemental_by_ref:
                raise ClassificationMatrixError(
                    f"{classification.get('classification_id')}: supplemental evidence requires CLS-004 normalization"
                )
            leaf_id = str(classification.get("leaf_id"))
            leaf = leaves_by_id.get(leaf_id)
            if not leaf:
                raise ClassificationMatrixError(f"{classification.get('classification_id')}: unknown qdt leaf {leaf_id}")
            proof_id = str(classification.get("coverage_proof_ref"))
            proof = proof_by_sidecar_and_id.get((sidecar_id, proof_id))
            if not proof:
                raise ClassificationMatrixError(f"{classification.get('classification_id')}: missing materialized coverage proof")
            certificate = lookups.certificate_by_id[str(classification["research_sufficiency_certificate_ref"])]

            for evidence_ref in _classification_evidence_refs(classification):
                evidence = lookups.evidence_by_ref.get(evidence_ref)
                if not evidence:
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: unknown retrieval evidence {evidence_ref}"
                    )
                if evidence.get("leaf_id") != leaf_id:
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: evidence leaf does not match classification leaf"
                    )
                retrieval_provenance = lookups.provenance_by_evidence_ref.get(evidence_ref)
                if not retrieval_provenance:
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: missing retrieval provenance for {evidence_ref}"
                    )
                claim_family_ids, claim_split_status = _claim_family_ids_for_row(
                    classification=classification,
                    evidence=evidence,
                    composite_claim_policy=composite_claim_policy,
                )
                for claim_family_id in claim_family_ids:
                    claim_family_resolution_ref = _claim_family_resolution_ref(evidence, claim_family_id)
                    classification_slice = _classification_slice(
                        sidecar=sidecar,
                        classification=classification,
                        leaf=leaf,
                        evidence=evidence,
                        certificate=certificate,
                        proof=proof,
                        lookups=lookups,
                        claim_family_id=claim_family_id,
                        claim_split_status=claim_split_status,
                        claim_family_resolution_ref=claim_family_resolution_ref,
                    )
                    grain = (
                        str(classification_slice["sidecar_id"]),
                        str(classification_slice["leaf_id"]),
                        str(classification_slice["condition_scope"]),
                        str(classification_slice["evidence_ref"]),
                        str(classification_slice["source_family_id"]),
                        str(classification_slice["claim_family_id"]),
                    )
                    if grain in seen_grain:
                        raise ClassificationMatrixError(
                            f"{classification.get('classification_id')}: duplicate classification grain"
                        )
                    seen_grain.add(grain)
                    provenance_slice = _provenance_slice(
                        classification_slice=classification_slice,
                        classification=classification,
                        evidence=evidence,
                        certificate=certificate,
                        proof=proof,
                        retrieval_provenance=retrieval_provenance,
                        claim_family_resolution_ref=claim_family_resolution_ref,
                    )
                    classification_slice["provenance_slice_ref"] = provenance_slice["slice_id"]
                    classification_slice["classification_slice_digest"] = _prefixed_sha256(classification_slice)
                    classification_slices.append(classification_slice)
                    provenance_slices.append(provenance_slice)

            for supplemental_ref in supplemental_refs:
                record = supplemental_by_ref.get(supplemental_ref)
                if not record:
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: missing normalized supplemental evidence {supplemental_ref}"
                    )
                if record.get("case_id") and record.get("case_id") != packet.get("case_id"):
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: supplemental evidence case does not match retrieval packet"
                    )
                if record.get("dispatch_id") and record.get("dispatch_id") != packet.get("dispatch_id"):
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: supplemental evidence dispatch does not match retrieval packet"
                    )
                if record.get("leaf_id") and record.get("leaf_id") != leaf_id:
                    raise ClassificationMatrixError(
                        f"{classification.get('classification_id')}: supplemental evidence leaf does not match classification leaf"
                    )
                try:
                    supplemental_evidence = supplemental_record_as_classification_evidence(record)
                    supplemental_provenance = supplemental_record_as_provenance(record)
                except SupplementalEvidenceError as exc:
                    raise ClassificationMatrixError(str(exc)) from exc
                supplemental_evidence["leaf_id"] = supplemental_evidence.get("leaf_id") or leaf_id
                supplemental_evidence["parent_branch_id"] = (
                    supplemental_evidence.get("parent_branch_id")
                    or leaf.get("parent_branch_id")
                    or classification.get("parent_branch_id")
                )
                claim_family_ids, claim_split_status = _claim_family_ids_for_row(
                    classification=classification,
                    evidence=supplemental_evidence,
                    composite_claim_policy=composite_claim_policy,
                )
                for claim_family_id in claim_family_ids:
                    claim_family_resolution_ref = _claim_family_resolution_ref(supplemental_evidence, claim_family_id)
                    classification_slice = _classification_slice(
                        sidecar=sidecar,
                        classification=classification,
                        leaf=leaf,
                        evidence=supplemental_evidence,
                        certificate=certificate,
                        proof=proof,
                        lookups=lookups,
                        claim_family_id=claim_family_id,
                        claim_split_status=claim_split_status,
                        claim_family_resolution_ref=claim_family_resolution_ref,
                    )
                    grain = (
                        str(classification_slice["sidecar_id"]),
                        str(classification_slice["leaf_id"]),
                        str(classification_slice["condition_scope"]),
                        str(classification_slice["evidence_ref"]),
                        str(classification_slice["source_family_id"]),
                        str(classification_slice["claim_family_id"]),
                    )
                    if grain in seen_grain:
                        raise ClassificationMatrixError(
                            f"{classification.get('classification_id')}: duplicate classification grain"
                        )
                    seen_grain.add(grain)
                    provenance_slice = _provenance_slice(
                        classification_slice=classification_slice,
                        classification=classification,
                        evidence=supplemental_evidence,
                        certificate=certificate,
                        proof=proof,
                        retrieval_provenance=supplemental_provenance,
                        claim_family_resolution_ref=claim_family_resolution_ref,
                    )
                    classification_slice["provenance_slice_ref"] = provenance_slice["slice_id"]
                    classification_slice["classification_slice_digest"] = _prefixed_sha256(classification_slice)
                    classification_slices.append(classification_slice)
                    provenance_slices.append(provenance_slice)
                    joined_supplemental_refs.add(supplemental_ref)

    classification_slices.sort(key=_classification_output_sort_key)
    provenance_slices.sort(key=_provenance_output_sort_key)
    coverage_proof_slices.sort(key=lambda item: (str(item["slice_id"]), _canonical_json(item)))
    matrix_digest = compute_materialized_classification_matrix_digest(
        classification_slices,
        provenance_slices,
        coverage_proof_slices,
    )
    for row in classification_slices:
        row["matrix_digest"] = matrix_digest
    for row in provenance_slices:
        row["matrix_digest"] = matrix_digest
    for row in coverage_proof_slices:
        row["matrix_digest"] = matrix_digest

    matrix_seed = {
        "case_id": packet.get("case_id"),
        "dispatch_id": packet.get("dispatch_id"),
        "matrix_digest": matrix_digest,
    }
    implements = ["CLS-003"]
    not_implemented = ["CLS-004", "CLS-005", "CLS-006", "CLS-007", "CLS-008", "VER", "SCAE"]
    if joined_supplemental_refs:
        implements.append("CLS-004")
        not_implemented.remove("CLS-004")

    return {
        "artifact_type": "researcher_classification_matrix",
        "schema_version": CLASSIFICATION_MATRIX_SCHEMA_VERSION,
        "feature_id": "CLS-003",
        "materializer_version": CLS_003_MATRIX_MATERIALIZER_VERSION,
        "matrix_id": _sha_id("researcher-classification-matrix", matrix_seed),
        "case_id": packet.get("case_id"),
        "dispatch_id": packet.get("dispatch_id"),
        "classification_slice_surface": CLASSIFICATION_SLICE_SURFACE,
        "provenance_slice_surface": PROVENANCE_SLICE_SURFACE,
        "coverage_proof_surface": COVERAGE_PROOF_SURFACE,
        "classification_slices": classification_slices,
        "provenance_slices": provenance_slices,
        "coverage_proof_slices": coverage_proof_slices,
        "matrix_digest": matrix_digest,
        "source_sidecars": [
            {
                "sidecar_id": sidecar.get("sidecar_id"),
                "sidecar_digest": sidecar.get("sidecar_digest"),
                "classification_matrix_digest": sidecar.get("classification_matrix_digest"),
                "model_execution_context_ref": sidecar.get("model_execution_context_ref"),
                "model_execution_context_sha256": sidecar.get("model_execution_context_sha256"),
            }
            for sidecar in validated_sidecars
        ],
        "retrieval_packet_ref": packet.get("retrieval_packet_id")
        or packet.get("packet_id")
        or packet.get("question_decomposition_artifact_id"),
        "normalized_supplemental_evidence_refs": sorted(joined_supplemental_refs),
        "scope_boundaries": {
            "implements": implements,
            "not_implemented": not_implemented,
        },
    }
