#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_runner import NonRetryableStageError, RetryableStageError
from predquant.ads_production_handlers import (
    ADS_PRODUCTION_FAILURE_CLASSES,
    ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID,
    ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION,
    AdsProductionStageFailure,
    build_stage_failure_policy,
    classify_stage_failure,
    wrap_production_stage_handler,
)


class AdsProductionHandlersTest(unittest.TestCase):
    def test_stage_failure_policy_exposes_phase10_failure_classes(self):
        policy = build_stage_failure_policy()

        self.assertEqual(policy["schema_version"], ADS_PRODUCTION_STAGE_FAILURE_POLICY_SCHEMA_VERSION)
        self.assertEqual(policy["policy_id"], ADS_PRODUCTION_STAGE_FAILURE_POLICY_ID)
        self.assertEqual(tuple(policy["failure_classes"]), ADS_PRODUCTION_FAILURE_CLASSES)
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


if __name__ == "__main__":
    unittest.main()
