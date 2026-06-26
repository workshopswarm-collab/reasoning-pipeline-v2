"""RET-011 compact source metadata classifier facade."""

from __future__ import annotations

from .retrieval import (
    DEFAULT_SOURCE_METADATA_CLASSIFIER_MODEL_ID,
    SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION,
    SOURCE_METADATA_CLASSIFIER_UNAVAILABLE_SCHEMA_VERSION,
    build_compact_source_candidate_packet,
    build_source_metadata_classifier_slice,
    build_source_metadata_classifier_unavailable,
    resolve_source_metadata_classifier_lane,
    validate_source_metadata_classifier_slice,
    validate_source_metadata_classifier_unavailable,
)

__all__ = [
    "DEFAULT_SOURCE_METADATA_CLASSIFIER_MODEL_ID",
    "SOURCE_METADATA_CLASSIFIER_SCHEMA_VERSION",
    "SOURCE_METADATA_CLASSIFIER_UNAVAILABLE_SCHEMA_VERSION",
    "build_compact_source_candidate_packet",
    "build_source_metadata_classifier_slice",
    "build_source_metadata_classifier_unavailable",
    "resolve_source_metadata_classifier_lane",
    "validate_source_metadata_classifier_slice",
    "validate_source_metadata_classifier_unavailable",
]
