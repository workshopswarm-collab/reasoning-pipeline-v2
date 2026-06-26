"""Retrieval evidence and chunk/span facade."""

from __future__ import annotations

from .retrieval import (
    RETRIEVAL_EVIDENCE_CHUNK_SCHEMA_VERSION,
    RETRIEVAL_EVIDENCE_SCHEMA_VERSION,
    RETRIEVAL_EVIDENCE_SPAN_SCHEMA_VERSION,
    build_evidence_chunk,
    build_evidence_span,
    build_retrieval_evidence_item,
    validate_retrieval_evidence_item,
)

__all__ = [
    "RETRIEVAL_EVIDENCE_CHUNK_SCHEMA_VERSION",
    "RETRIEVAL_EVIDENCE_SCHEMA_VERSION",
    "RETRIEVAL_EVIDENCE_SPAN_SCHEMA_VERSION",
    "build_evidence_chunk",
    "build_evidence_span",
    "build_retrieval_evidence_item",
    "validate_retrieval_evidence_item",
]
