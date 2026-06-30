#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_runner import NonRetryableStageError, RetryableStageError
from predquant.ads_retrieval_transport import RetrievalProviderPolicy
from predquant.ads_stage_logging import validate_failure_class
from predquant.ads_production_handlers import (
    ADS_PRODUCTION_FAILURE_CLASSES,
    ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID,
    ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION,
    AdsProductionStageFailure,
    build_stage_failure_policy,
    build_stage_handlers,
    classify_stage_failure,
    wrap_production_stage_handler,
)
import predquant.ads_production_handlers as production_handlers


SCHEDULER_PATH = Path(__file__).resolve().parents[1] / "bin" / "run_ads_operational_scheduler.py"
SCHEDULER_SPEC = importlib.util.spec_from_file_location("run_ads_operational_scheduler", SCHEDULER_PATH)
assert SCHEDULER_SPEC is not None and SCHEDULER_SPEC.loader is not None
run_ads_operational_scheduler = importlib.util.module_from_spec(SCHEDULER_SPEC)
SCHEDULER_SPEC.loader.exec_module(run_ads_operational_scheduler)

ONE_CASE_PATH = Path(__file__).resolve().parents[1] / "bin" / "run_ads_one_case_canary.py"
ONE_CASE_SPEC = importlib.util.spec_from_file_location("run_ads_one_case_canary", ONE_CASE_PATH)
assert ONE_CASE_SPEC is not None and ONE_CASE_SPEC.loader is not None
run_ads_one_case_canary = importlib.util.module_from_spec(ONE_CASE_SPEC)
ONE_CASE_SPEC.loader.exec_module(run_ads_one_case_canary)


class AdsProductionHandlersTest(unittest.TestCase):
    def test_stage_failure_policy_exposes_phase10_failure_classes(self):
        policy = build_stage_failure_policy()

        self.assertEqual(policy["schema_version"], ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION)
        self.assertEqual(policy["policy_id"], ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID)
        self.assertEqual(tuple(policy["failure_classes"]), ADS_PRODUCTION_FAILURE_CLASSES)
        for failure_class in ADS_PRODUCTION_FAILURE_CLASSES:
            self.assertEqual(validate_failure_class(failure_class), failure_class)
        self.assertEqual(policy["retry_rules"]["retryable_transport"]["max_retries"], 1)
        self.assertEqual(policy["retry_rules"]["retryable_model_transport"]["max_retries"], 1)
        self.assertEqual(policy["retry_rules"]["invalid_artifact_terminal"]["max_retries"], 0)
        self.assertEqual(policy["scoreable_write_surface"], "decision_stage_only")

    def test_retryable_model_transport_failure_maps_to_runner_retry(self):
        def handler(**_kwargs):
            raise AdsProductionStageFailure(
                "model transport timeout",
                failure_class="retryable_model_transport",
                retry_after_seconds=5,
            )

        wrapped = wrap_production_stage_handler("decomposition", handler)

        with self.assertRaises(RetryableStageError) as caught:
            wrapped()

        error = caught.exception
        self.assertEqual(error.failure_class, "retryable_model_transport")
        self.assertEqual(error.safe_reason_code, "ads_production_retryable_model_transport")
        self.assertEqual(
            error.failure_policy_ref,
            f"{ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID}#retryable_model_transport",
        )
        self.assertEqual(error.retry_policy_ref, error.failure_policy_ref)
        self.assertEqual(error.retry_after_seconds, 5)
        self.assertEqual(error.lease_release_or_drain_action, "keep_lease_recoverable")
        self.assertEqual(error.pipeline_decision, "continue_after_retry_backoff")

    def test_non_decision_scoreable_output_is_quarantined(self):
        def handler(**_kwargs):
            return {
                "output_artifact_refs": ["artifact:retrieval"],
                "validation_result_refs": [],
                "safe_metadata": {"scoreable_forecast_output": True},
            }

        wrapped = wrap_production_stage_handler("retrieval", handler)

        with self.assertRaises(NonRetryableStageError) as caught:
            wrapped()

        error = caught.exception
        self.assertEqual(error.failure_class, "policy_violation_quarantine")
        self.assertEqual(error.safe_reason_code, "ads_production_policy_violation_quarantine")
        self.assertEqual(
            error.failure_policy_ref,
            f"{ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID}#policy_violation_quarantine",
        )
        self.assertEqual(error.lease_release_or_drain_action, "quarantine_case_lease")
        self.assertEqual(error.pipeline_decision, "quarantine_and_block_scoreable_persistence")

    def test_decision_stage_remains_allowed_scoreable_surface(self):
        result = {
            "forecast_artifact_id": "forecast:decision",
            "market_prediction_id": "prediction:decision",
            "safe_metadata": {"scoreable_forecast_output": True},
        }

        wrapped = wrap_production_stage_handler("decision", lambda **_kwargs: result)

        self.assertIs(wrapped(), result)

    def test_classifier_distinguishes_policy_and_transport_failures(self):
        self.assertEqual(
            classify_stage_failure("retrieval", TimeoutError("transport timed out")),
            "retryable_transport",
        )
        self.assertEqual(
            classify_stage_failure("verification", ValueError("forbidden output contamination")),
            "policy_violation_quarantine",
        )

    def test_scheduler_can_pass_explicit_retrieval_browser_provider_factory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            provider_module = Path(tempdir) / "provider_factory.py"
            provider_module.write_text(
                "\n".join(
                    [
                        "class Provider:",
                        "    def __init__(self):",
                        "        self.provider_id = 'test-provider'",
                        "    def fetch_url(self, url):",
                        "        return {'url': url, 'extraction_status': 'rejected'}",
                        "    def search_candidate_urls(self, query_context, query_variant, *, searched_at=None):",
                        "        return []",
                        "def build_provider():",
                        "    return Provider()",
                        "def build_native_candidate_provider():",
                        "    return lambda context, variant: []",
                    ]
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                decomposer_runtime_transport_response=None,
                researcher_swarm_runtime_bundle_response=None,
                retrieval_browser_provider_factory=str(provider_module),
                native_candidate_provider_factory=str(provider_module),
            )

            kwargs = run_ads_operational_scheduler.build_handler_factory_kwargs(args)

        provider = kwargs["retrieval_browser_provider"]
        self.assertEqual(provider.provider_id, "test-provider")
        self.assertTrue(callable(provider.fetch_url))
        self.assertTrue(callable(provider.search_candidate_urls))
        self.assertTrue(callable(kwargs["native_candidate_provider"]))

    def test_one_case_canary_can_pass_explicit_runtime_factories(self):
        with tempfile.TemporaryDirectory() as tempdir:
            provider_module = Path(tempdir) / "runtime_factories.py"
            provider_module.write_text(
                "\n".join(
                    [
                        "class Provider:",
                        "    provider_id = 'one-case-provider'",
                        "    def fetch_url(self, url):",
                        "        return {'url': url, 'extraction_status': 'rejected'}",
                        "    def search_candidate_urls(self, query_context, query_variant, *, searched_at=None):",
                        "        return []",
                        "def build_provider():",
                        "    return Provider()",
                        "def build_native_candidate_provider():",
                        "    return lambda context, variant: []",
                        "def run_researcher_swarm_runtime(**kwargs):",
                        "    return {'artifact_type': 'researcher_swarm_runtime_bundle', 'kwargs': sorted(kwargs)}",
                    ]
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                decomposer_runtime_mode="fixture",
                decomposer_runtime_transport_response=None,
                researcher_swarm_runtime_bundle_response=None,
                retrieval_browser_provider_factory=str(provider_module),
                native_candidate_provider_factory=str(provider_module),
                researcher_swarm_runtime_runner=str(provider_module),
                retrieval_provider_policy_json=run_ads_one_case_canary.parse_retrieval_provider_policy(
                    '{"max_direct_urls":0,"max_total_search_calls":10,"max_total_search_result_fetches":50}'
                ),
            )

            kwargs = run_ads_one_case_canary.build_handler_factory_kwargs(args)

        provider = kwargs["retrieval_browser_provider"]
        self.assertEqual(kwargs["decomposer_runtime_mode"], "fixture")
        self.assertEqual(provider.provider_id, "one-case-provider")
        self.assertTrue(callable(provider.fetch_url))
        self.assertTrue(callable(provider.search_candidate_urls))
        runner = kwargs["researcher_swarm_runtime_runner"]
        self.assertTrue(callable(runner))
        self.assertEqual(
            runner(example=True)["artifact_type"],
            "researcher_swarm_runtime_bundle",
        )
        self.assertTrue(callable(kwargs["native_candidate_provider"]))
        policy = kwargs["retrieval_provider_policy"]
        self.assertIsInstance(policy, RetrievalProviderPolicy)
        self.assertEqual(policy.max_direct_urls, 0)
        self.assertEqual(policy.max_total_search_calls, 10)
        self.assertEqual(policy.max_total_search_result_fetches, 50)

    def test_true_production_factory_loads_default_retrieval_provider(self):
        class Provider:
            provider_id = "default-provider"

            def fetch_url(self, url):
                return {"url": url, "extraction_status": "rejected"}

            def search_candidate_urls(self, query_context, query_variant, *, searched_at=None):
                return []

        captured = {}
        provider = Provider()
        native_provider = lambda _context, _variant: []

        def fake_build_stage_handlers(**kwargs):
            captured.update(kwargs)
            return {}

        with patch.object(
            production_handlers,
            "build_default_retrieval_browser_provider",
            return_value=provider,
        ), patch.object(
            production_handlers,
            "build_default_native_candidate_provider",
            return_value=native_provider,
        ), patch.object(production_handlers, "_build_stage_handlers", side_effect=fake_build_stage_handlers):
            handlers = build_stage_handlers(db_path=":memory:")

        self.assertEqual(handlers, {})
        self.assertIs(captured["retrieval_browser_provider"], provider)
        self.assertIs(captured["native_candidate_provider"], native_provider)
        self.assertTrue(captured["retrieval_provider_policy"].native_enabled)
        self.assertTrue(captured["live_retrieval_runtime"])

    def test_true_production_factory_preserves_explicit_retrieval_provider(self):
        class Provider:
            provider_id = "explicit-provider"

            def fetch_url(self, url):
                return {"url": url, "extraction_status": "rejected"}

            def search_candidate_urls(self, query_context, query_variant, *, searched_at=None):
                return []

        captured = {}
        provider = Provider()

        def fake_build_stage_handlers(**kwargs):
            captured.update(kwargs)
            return {}

        with patch.object(
            production_handlers,
            "build_default_retrieval_browser_provider",
            side_effect=AssertionError("default provider should not be loaded"),
        ), patch.object(production_handlers, "_build_stage_handlers", side_effect=fake_build_stage_handlers):
            handlers = build_stage_handlers(db_path=":memory:", retrieval_browser_provider=provider)

        self.assertEqual(handlers, {})
        self.assertIs(captured["retrieval_browser_provider"], provider)

    def test_true_production_factory_rejects_unconfigured_retrieval_search_provider(self):
        class Provider:
            provider_id = "unconfigured-provider"

            def fetch_url(self, url):
                return {"url": url, "extraction_status": "rejected"}

            def search_candidate_urls(self, query_context, query_variant, *, searched_at=None):
                return []

            def provider_diagnostics(self):
                return {
                    "provider_id": self.provider_id,
                    "fetch_configured": True,
                    "search_configured": False,
                }

        with self.assertRaises(AdsProductionStageFailure) as caught:
            build_stage_handlers(db_path=":memory:", retrieval_browser_provider=Provider())

        self.assertEqual(caught.exception.failure_class, "fatal_operational")
        self.assertIn("search_candidate_urls", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
