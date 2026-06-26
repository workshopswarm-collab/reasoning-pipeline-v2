"""Browser capture facade for retrieval evidence materialization."""

from __future__ import annotations

from .retrieval import (
    BROWSER_RETRIEVAL_ATTEMPT_SCHEMA_VERSION,
    RETRIEVAL_CANDIDATE_RECORD_SCHEMA_VERSION,
    RETRIEVAL_EVIDENCE_SCHEMA_VERSION,
    build_browser_retrieval_attempt,
    build_retrieval_candidate_record,
    build_retrieval_evidence_item,
)

__all__ = [
    "BROWSER_RETRIEVAL_ATTEMPT_SCHEMA_VERSION",
    "RETRIEVAL_CANDIDATE_RECORD_SCHEMA_VERSION",
    "RETRIEVAL_EVIDENCE_SCHEMA_VERSION",
    "build_browser_retrieval_attempt",
    "build_retrieval_candidate_record",
    "build_retrieval_evidence_item",
]
