"""ADS true-production specialist runtime stage handlers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from predquant.ads_pipeline_runner import NonRetryableStageError, RetryableStageError
from predquant.ads_production_readiness_handlers import (
    TRUE_PRODUCTION_HANDLER_FACTORY_REF,
    TRUE_PRODUCTION_HANDLER_SCOPE,
    build_stage_handlers as _build_stage_handlers,
)
from predquant.ads_retrieval_transport import RetrievalProviderPolicy
from predquant.ads_native_research import build_provider as build_default_native_candidate_provider
from researcher_swarm.browser_provider import build_provider as build_default_retrieval_browser_provider

ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION = "ads-production-stage-failure-policy/v1"
ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID = "ads-production-stage-failure-policy:strict-v1"
ADS_PRODUCTION_FAILURE_CLASSES = (
    "retryable_transport",
    "retryable_model_transport",
    "invalid_artifact_terminal",
    "thin_evidence_watch_only",
    "policy_violation_quarantine",
    "fatal_operational",
)
RETRYABLE_FAILURE_CLASSES = {"retryable_transport", "retryable_model_transport"}
NON_RETRYABLE_FAILURE_CLASSES = set(ADS_PRODUCTION_FAILURE_CLASSES) - RETRYABLE_FAILURE_CLASSES


class AdsProductionStageFailure(Exception):
    """Stage failure with an explicit production failure class."""

    def __init__(
        self,
        message: str,
        *,
        failure_class: str,
        retry_after_seconds: int | None = None,
    ):
        if failure_class not in ADS_PRODUCTION_FAILURE_CLASSES:
            raise ValueError(f"unknown ADS production failure class: {failure_class}")
        super().__init__(message)
        self.failure_class = failure_class
        self.retry_after_seconds = retry_after_seconds


def build_stage_failure_policy() -> dict[str, Any]:
    return {
        "schema_version": ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION,
        "policy_id": ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID,
        "failure_classes": list(ADS_PRODUCTION_FAILURE_CLASSES),
        "retry_rules": {
            "retryable_transport": {"max_retries": 1, "runner_error": "RetryableStageError"},
            "retryable_model_transport": {"max_retries": 1, "runner_error": "RetryableStageError"},
            "invalid_artifact_terminal": {"max_retries": 0, "runner_error": "NonRetryableStageError"},
            "thin_evidence_watch_only": {"max_retries": 0, "runner_error": "NonRetryableStageError"},
            "policy_violation_quarantine": {"max_retries": 0, "runner_error": "NonRetryableStageError"},
            "fatal_operational": {"max_retries": 0, "runner_error": "NonRetryableStageError"},
        },
        "failure_actions": {
            "retryable_transport": {
                "lease_release_or_drain_action": "keep_lease_recoverable",
                "pipeline_decision": "continue_after_retry_backoff",
            },
            "retryable_model_transport": {
                "lease_release_or_drain_action": "keep_lease_recoverable",
                "pipeline_decision": "continue_after_retry_backoff",
            },
            "invalid_artifact_terminal": {
                "lease_release_or_drain_action": "quarantine_case_lease",
                "pipeline_decision": "block_scoreable_persistence",
            },
            "thin_evidence_watch_only": {
                "lease_release_or_drain_action": "quarantine_case_lease",
                "pipeline_decision": "watch_only_no_scoreable_persistence",
            },
            "policy_violation_quarantine": {
                "lease_release_or_drain_action": "quarantine_case_lease",
                "pipeline_decision": "quarantine_and_block_scoreable_persistence",
            },
            "fatal_operational": {
                "lease_release_or_drain_action": "quarantine_case_lease",
                "pipeline_decision": "block_scoreable_persistence",
            },
        },
        "scoreable_write_surface": "decision_stage_only",
    }


def _failure_policy_ref(failure_class: str) -> str:
    return f"{ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID}#{failure_class}"


def _safe_reason_code(failure_class: str) -> str:
    return f"ads_production_{failure_class}"


def _pipeline_decision(failure_class: str) -> str:
    return build_stage_failure_policy()["failure_actions"][failure_class]["pipeline_decision"]


def _lease_release_or_drain_action(failure_class: str) -> str:
    return build_stage_failure_policy()["failure_actions"][failure_class]["lease_release_or_drain_action"]


def _message_for(exc: BaseException) -> str:
    return str(exc)[:512] or exc.__class__.__name__


def _retrieval_provider_diagnostics(provider: Any | None) -> dict[str, Any]:
    if provider is None or not hasattr(provider, "provider_diagnostics"):
        return {}
    diagnostics = provider.provider_diagnostics()
    return diagnostics if isinstance(diagnostics, dict) else {}


def _provider_capability_configured(
    provider: Any | None,
    *,
    method_name: str,
    diagnostic_key: str,
) -> bool:
    if provider is None or not callable(getattr(provider, method_name, None)):
        return False
    diagnostics = _retrieval_provider_diagnostics(provider)
    diagnostic_value = diagnostics.get(diagnostic_key)
    if isinstance(diagnostic_value, bool):
        return diagnostic_value
    attr_value = getattr(provider, diagnostic_key, None)
    if isinstance(attr_value, bool):
        return attr_value
    return True


def _assert_retrieval_browser_provider_configured(provider: Any | None) -> None:
    missing: list[str] = []
    if not _provider_capability_configured(
        provider,
        method_name="fetch_url",
        diagnostic_key="fetch_configured",
    ):
        missing.append("fetch_url")
    if not _provider_capability_configured(
        provider,
        method_name="search_candidate_urls",
        diagnostic_key="search_configured",
    ):
        missing.append("search_candidate_urls")
    if missing:
        raise AdsProductionStageFailure(
            "retrieval_browser_provider is not configured for strict true-production retrieval: "
            + ", ".join(sorted(missing)),
            failure_class="fatal_operational",
        )


def _is_transport_exception(exc: BaseException) -> bool:
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def classify_stage_failure(stage: str, exc: BaseException) -> str:
    if isinstance(exc, AdsProductionStageFailure):
        return exc.failure_class
    text = _message_for(exc).lower()
    if (
        "policy" in text
        or "forbidden" in text
        or "contamination" in text
        or "probability" in text
        or "fair_value" in text
        or "fair value" in text
        or "scae_delta" in text
        or "scae delta" in text
        or "authority" in text
    ):
        return "policy_violation_quarantine"
    if "thin_evidence" in text or "thin evidence" in text or "insufficient evidence" in text:
        return "thin_evidence_watch_only"
    if "validation" in text or "invalid artifact" in text or "malformed" in text:
        return "invalid_artifact_terminal"
    if "model" in text and ("transport" in text or "runtime failed" in text or "timeout" in text):
        return "retryable_model_transport"
    if "transport" in text or _is_transport_exception(exc):
        return "retryable_transport"
    if stage == "decomposition" and "runtime failed" in text:
        return "retryable_model_transport"
    return "fatal_operational"


def _runner_error_for(stage: str, exc: BaseException) -> RetryableStageError | NonRetryableStageError:
    if isinstance(exc, (RetryableStageError, NonRetryableStageError)):
        return exc
    failure_class = classify_stage_failure(stage, exc)
    safe_reason_code = _safe_reason_code(failure_class)
    common = {
        "failure_class": failure_class,
        "safe_reason_code": safe_reason_code,
        "failure_policy_ref": _failure_policy_ref(failure_class),
        "lease_release_or_drain_action": _lease_release_or_drain_action(failure_class),
        "pipeline_decision": _pipeline_decision(failure_class),
    }
    if failure_class in RETRYABLE_FAILURE_CLASSES:
        retry_after_seconds = exc.retry_after_seconds if isinstance(exc, AdsProductionStageFailure) else None
        return RetryableStageError(
            _message_for(exc),
            retry_after_seconds=retry_after_seconds,
            retry_policy_ref=_failure_policy_ref(failure_class),
            **common,
        )
    return NonRetryableStageError(_message_for(exc), **common)


def _assert_decision_only_scoreable_outputs(stage: str, result: dict[str, Any]) -> None:
    if stage == "decision":
        return
    forbidden_fields = [
        field
        for field in ("forecast_decision_record_id", "forecast_decision_record_ref", "forecast_artifact_id", "market_prediction_id")
        if result.get(field)
    ]
    metadata = result.get("safe_metadata") if isinstance(result.get("safe_metadata"), dict) else {}
    if metadata.get("market_prediction_written") is True or metadata.get("scoreable_forecast_output") is True:
        forbidden_fields.append("safe_metadata.scoreable_write")
    if forbidden_fields:
        raise AdsProductionStageFailure(
            f"non-decision stage {stage} attempted scoreable write output: {', '.join(sorted(forbidden_fields))}",
            failure_class="policy_violation_quarantine",
        )


def wrap_production_stage_handler(stage: str, handler: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(**kwargs: Any) -> Any:
        try:
            result = handler(**kwargs)
            if isinstance(result, dict):
                _assert_decision_only_scoreable_outputs(stage, result)
            return result
        except Exception as exc:
            raise _runner_error_for(stage, exc) from exc

    return wrapped


def build_stage_handlers(**kwargs: Any) -> dict[str, Callable[..., Any]]:
    kwargs = dict(kwargs)
    metadata = dict(kwargs.pop("metadata", {}) or {})
    metadata.setdefault("stage_failure_policy_schema_version", ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION)
    metadata.setdefault("stage_failure_policy_id", ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID)
    metadata.setdefault("scoreable_write_surface", "decision_stage_only")
    kwargs.pop("handler_factory_ref", None)
    kwargs.pop("handler_scope", None)
    kwargs.pop("scoreable_pilot", None)
    kwargs.pop("decomposer_runtime", None)
    kwargs.pop("live_policy_overlay", None)
    kwargs.pop("live_retrieval_runtime", None)
    kwargs.pop("live_fixture_retrieval", None)
    kwargs.pop("block_at_leaf_research_barrier", None)
    kwargs.pop("researcher_swarm_openclaw_runtime", None)
    kwargs.pop("amrg_vector_runtime", None)
    runtime_mode = kwargs.pop("decomposer_runtime_mode", "live")
    if kwargs.get("retrieval_browser_provider") is None:
        kwargs["retrieval_browser_provider"] = build_default_retrieval_browser_provider()
    _assert_retrieval_browser_provider_configured(kwargs.get("retrieval_browser_provider"))
    policy = kwargs.get("retrieval_provider_policy")
    if policy is None:
        policy = RetrievalProviderPolicy(native_enabled=True)
    elif isinstance(policy, RetrievalProviderPolicy) and not policy.native_enabled:
        policy = replace(policy, native_enabled=True)
    kwargs["retrieval_provider_policy"] = policy
    if kwargs.get("native_candidate_provider") is None:
        kwargs["native_candidate_provider"] = build_default_native_candidate_provider()
    handlers = _build_stage_handlers(
        **kwargs,
        metadata=metadata,
        handler_factory_ref=TRUE_PRODUCTION_HANDLER_FACTORY_REF,
        handler_scope=TRUE_PRODUCTION_HANDLER_SCOPE,
        scoreable_pilot=False,
        decomposer_runtime=True,
        decomposer_runtime_mode=runtime_mode,
        live_policy_overlay=True,
        live_retrieval_runtime=True,
        live_fixture_retrieval=False,
        block_at_leaf_research_barrier=True,
        researcher_swarm_openclaw_runtime=True,
        amrg_vector_runtime=True,
    )
    return {stage: wrap_production_stage_handler(stage, handler) for stage, handler in handlers.items()}


__all__ = [
    "ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION",
    "ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID",
    "ADS_PRODUCTION_FAILURE_CLASSES",
    "AdsProductionStageFailure",
    "build_stage_failure_policy",
    "build_stage_handlers",
    "classify_stage_failure",
    "wrap_production_stage_handler",
]
