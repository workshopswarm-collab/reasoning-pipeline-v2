"""Retrieval breadth profile and coverage facade."""

from __future__ import annotations

from .retrieval import (
    RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION,
    RETRIEVAL_BREADTH_EVALUATOR_VERSION,
    RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION,
    build_retrieval_breadth_coverage_slice,
    build_retrieval_breadth_coverage_slices,
    build_retrieval_breadth_profile_placeholder,
    validate_retrieval_breadth_coverage_slice,
)

__all__ = [
    "RETRIEVAL_BREADTH_COVERAGE_SCHEMA_VERSION",
    "RETRIEVAL_BREADTH_EVALUATOR_VERSION",
    "RETRIEVAL_BREADTH_PROFILE_SCHEMA_VERSION",
    "build_retrieval_breadth_coverage_slice",
    "build_retrieval_breadth_coverage_slices",
    "build_retrieval_breadth_profile_placeholder",
    "validate_retrieval_breadth_coverage_slice",
]
