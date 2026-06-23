"""Shared OpenClaw contract helpers for cross-surface runtime code."""

from .entrypoints import resolve_entrypoint
from .paths import openclaw_root, orchestrator_root

__all__ = ["openclaw_root", "orchestrator_root", "resolve_entrypoint"]
