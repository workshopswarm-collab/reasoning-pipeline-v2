"""RET-010 native research facade.

The concrete native research artifact builders live in `retrieval.py`; this
module gives the planned runtime surface a stable import path without adding a
second implementation.
"""

from __future__ import annotations

from .retrieval import (
    NATIVE_RESEARCH_ATTEMPT_SCHEMA_VERSION,
    NATIVE_RESEARCH_RESOLVER_VERSION,
    NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION,
    build_native_research_attempt,
    build_native_research_transport_diagnostic,
)

__all__ = [
    "NATIVE_RESEARCH_ATTEMPT_SCHEMA_VERSION",
    "NATIVE_RESEARCH_RESOLVER_VERSION",
    "NATIVE_RESEARCH_TRANSPORT_DIAGNOSTIC_SCHEMA_VERSION",
    "build_native_research_attempt",
    "build_native_research_transport_diagnostic",
]
