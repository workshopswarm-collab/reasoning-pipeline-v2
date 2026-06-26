"""RET browser provider facade for OpenClaw browser/web_fetch retrieval."""

from __future__ import annotations

from .retrieval import (
    BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION,
    OPENCLAW_BROWSER_PROVIDER_ID,
    build_browser_search_provider_diagnostic,
)

__all__ = [
    "BROWSER_PROVIDER_DIAGNOSTIC_SCHEMA_VERSION",
    "OPENCLAW_BROWSER_PROVIDER_ID",
    "build_browser_search_provider_diagnostic",
]
