"""Source metadata resolver facade for deterministic retrieval validators."""

from __future__ import annotations

from .retrieval import (
    SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION,
    build_source_metadata_resolution,
    build_source_metadata_resolution_placeholder,
    validate_source_metadata_resolution,
)

__all__ = [
    "SOURCE_METADATA_RESOLUTION_SCHEMA_VERSION",
    "build_source_metadata_resolution",
    "build_source_metadata_resolution_placeholder",
    "validate_source_metadata_resolution",
]
