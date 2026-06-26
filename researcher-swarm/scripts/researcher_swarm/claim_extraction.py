"""Atomic claim extraction and claim-family facade."""

from __future__ import annotations

from .retrieval import (
    ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION,
    CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION,
    build_atomic_claim_candidate,
    build_atomic_claim_candidates_from_classifier_slice,
    build_claim_family_resolution,
    resolve_claim_families,
    validate_candidate_record,
)

__all__ = [
    "ATOMIC_CLAIM_CANDIDATE_SCHEMA_VERSION",
    "CLAIM_FAMILY_RESOLUTION_SCHEMA_VERSION",
    "build_atomic_claim_candidate",
    "build_atomic_claim_candidates_from_classifier_slice",
    "build_claim_family_resolution",
    "resolve_claim_families",
    "validate_candidate_record",
]
