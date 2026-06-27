"""ADS true-production specialist runtime stage handlers.

This module reuses the existing ADS runner and manifest-backed handler spine,
but opts into the first real v2 intelligence slice: Decomposer-owned runtime
QDT generation, live-policy retrieval semantics, leaf assignment fan-out, and
a fail-closed leaf-research barrier before verification/SCAE.
"""

from __future__ import annotations

from typing import Any, Callable

from predquant.ads_production_readiness_handlers import (
    TRUE_PRODUCTION_HANDLER_FACTORY_REF,
    TRUE_PRODUCTION_HANDLER_SCOPE,
    build_stage_handlers as _build_stage_handlers,
)


def build_stage_handlers(**kwargs: Any) -> dict[str, Callable[..., Any]]:
    kwargs = dict(kwargs)
    kwargs.pop("handler_factory_ref", None)
    kwargs.pop("handler_scope", None)
    kwargs.pop("decomposer_runtime", None)
    kwargs.pop("live_policy_overlay", None)
    kwargs.pop("live_fixture_retrieval", None)
    kwargs.pop("block_at_leaf_research_barrier", None)
    kwargs.pop("amrg_vector_runtime", None)
    runtime_mode = kwargs.pop("decomposer_runtime_mode", "live")
    return _build_stage_handlers(
        **kwargs,
        handler_factory_ref=TRUE_PRODUCTION_HANDLER_FACTORY_REF,
        handler_scope=TRUE_PRODUCTION_HANDLER_SCOPE,
        decomposer_runtime=True,
        decomposer_runtime_mode=runtime_mode,
        live_policy_overlay=True,
        live_fixture_retrieval=True,
        block_at_leaf_research_barrier=True,
        amrg_vector_runtime=True,
    )


__all__ = ["build_stage_handlers"]
