"""Scoreable ADS production-pilot stage handlers.

This module deliberately wraps the production-readiness handlers instead of
changing their default fail-closed behavior. The pilot lane is only for bounded
calibration-debt canaries using structured market metadata as certified input.
"""

from __future__ import annotations

from typing import Any, Callable

from predquant.ads_production_readiness_handlers import (
    PRODUCTION_PILOT_HANDLER_FACTORY_REF,
    PRODUCTION_PILOT_HANDLER_SCOPE,
    build_stage_handlers as _build_stage_handlers,
)


def build_stage_handlers(**kwargs: Any) -> dict[str, Callable[..., Any]]:
    kwargs = dict(kwargs)
    kwargs.pop("scoreable_pilot", None)
    kwargs.pop("handler_factory_ref", None)
    kwargs.pop("handler_scope", None)
    return _build_stage_handlers(
        **kwargs,
        scoreable_pilot=True,
        handler_factory_ref=PRODUCTION_PILOT_HANDLER_FACTORY_REF,
        handler_scope=PRODUCTION_PILOT_HANDLER_SCOPE,
    )


__all__ = ["build_stage_handlers"]
