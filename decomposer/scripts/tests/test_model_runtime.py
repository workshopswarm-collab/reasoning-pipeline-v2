#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))

from ads_decomposer.model_runtime import (  # noqa: E402
    MODEL_RUNTIME_CALL_SCHEMA_VERSION,
    MODEL_RUNTIME_RETRY_DIAGNOSTIC_SCHEMA_VERSION,
    MODEL_RUNTIME_TIMEOUTS,
    MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION,
    MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
    MODEL_TRANSPORT_RETRY_POLICY,
    MODEL_TRANSPORT_RETRY_POLICY_REF,
    ModelRuntimeError,
    execute_model_runtime_call,
    execute_model_runtime_call_for_lane,
    model_execution_context_from_runtime_call,
    _openclaw_agent_prompt,
    _parse_openclaw_agent_stdout,
    resolve_model_runtime_lane,
    scan_forbidden_model_outputs,
)


def _validator(value: Any) -> tuple[bool, list[str]]:
    if isinstance(value, dict) and value.get("ok") is True:
        return True, []
    return False, ["ok must be true"]


class ModelRuntimeContractTest(unittest.TestCase):
    def _call(self, **overrides: Any):
        args = {
            "model_lane_id": "decomposer_qdt_generation",
            "provider": "openai",
            "resolved_model_id": "gpt-5.5-high",
            "provider_route": "openclaw_codex_oauth/decomposer",
            "prompt_template_id": "decomposer-qdt/v1",
            "prompt_template_sha256": "sha256:" + "1" * 64,
            "input_manifest_refs": ["artifact:case", "artifact:evidence"],
            "output_schema_version": "question-decomposition/v1",
            "request_payload": {"question": "Will example happen?"},
            "mode": "fixture",
            "fixture_response": {"ok": True},
            "output_validator": _validator,
        }
        args.update(overrides)
        return execute_model_runtime_call(**args)

    def test_resolves_phase1_openai_gpt55_lanes_from_policy(self) -> None:
        for lane_id in (
            "decomposer_qdt_generation",
            "researcher_leaf_nli_classification",
            "native_research_candidate_discovery",
        ):
            with self.subTest(lane_id=lane_id):
                lane = resolve_model_runtime_lane(lane_id)

                self.assertEqual(lane["model_lane_id"], lane_id)
                self.assertEqual(lane["provider"], "openai")
                self.assertEqual(lane["resolved_model_id"], "gpt-5.5-high")
                self.assertTrue(lane["provider_route"].startswith("openclaw_codex_oauth/"))
                self.assertTrue(lane["oauth_route_required"])
                self.assertEqual(lane["timeout_seconds"], MODEL_RUNTIME_TIMEOUTS[lane_id])
                self.assertIn("resolved_model_id", lane["required_artifact_fields"])

    def test_fixture_mode_records_runtime_provenance_and_schema_validation(self) -> None:
        result = self._call()
        runtime = result.runtime_call

        self.assertEqual(result.response_payload, {"ok": True})
        self.assertEqual(runtime["schema_version"], MODEL_RUNTIME_CALL_SCHEMA_VERSION)
        self.assertEqual(runtime["execution_status"], "succeeded")
        self.assertTrue(runtime["fixture_mode"])
        self.assertTrue(runtime["model_call_performed"])
        self.assertTrue(runtime["model_executed"])
        self.assertEqual(runtime["forbidden_output_scan"]["status"], "passed")
        self.assertIn("model_executed", runtime["runtime_reason_codes"])
        self.assertIn("output_schema_validated", runtime["runtime_reason_codes"])
        self.assertTrue(runtime["request_sha256"].startswith("sha256:"))
        self.assertTrue(runtime["response_sha256"].startswith("sha256:"))

    def test_live_transport_retries_once_then_succeeds(self) -> None:
        attempts = {"count": 0}
        sleep_calls: list[float] = []

        def transport(payload: dict[str, Any]) -> dict[str, Any]:
            attempts["count"] += 1
            self.assertEqual(payload["schema_version"], MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION)
            self.assertEqual(payload["provider_route"], "openclaw_codex_oauth/decomposer")
            self.assertEqual(payload["timeout_seconds"], 180)
            self.assertEqual(payload["transport_attempt"], attempts["count"])
            self.assertEqual(payload["transport_max_attempts"], MODEL_TRANSPORT_RETRY_POLICY["max_attempts"])
            self.assertEqual(payload["transport_retry_policy_ref"], MODEL_TRANSPORT_RETRY_POLICY_REF)
            self.assertEqual(payload["request_payload"], {"question": "Will example happen?"})
            if attempts["count"] == 1:
                raise TimeoutError("transient")
            return {"ok": True}

        result = self._call(mode="live", fixture_response=None, transport=transport, sleep_fn=sleep_calls.append)

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result.runtime_call["retry_count"], 1)
        self.assertEqual(result.runtime_call["execution_status"], "succeeded")
        self.assertIn("transport_retry", result.runtime_call["runtime_reason_codes"])
        self.assertEqual(len(sleep_calls), 1)
        self.assertGreaterEqual(sleep_calls[0], 2.0)
        self.assertLessEqual(sleep_calls[0], 3.0)
        diagnostics = result.runtime_call["retry_diagnostics"]
        self.assertEqual([item["event"] for item in diagnostics], ["local_retry", "retry_succeeded"])
        self.assertEqual(diagnostics[0]["schema_version"], MODEL_RUNTIME_RETRY_DIAGNOSTIC_SCHEMA_VERSION)
        self.assertEqual(diagnostics[0]["component"], "qdt_model_runtime")
        self.assertEqual(diagnostics[0]["lane"], "decomposer_qdt_generation")
        self.assertEqual(diagnostics[0]["attempt"], 1)
        self.assertEqual(diagnostics[0]["max_attempts"], MODEL_TRANSPORT_RETRY_POLICY["max_attempts"])
        self.assertTrue(diagnostics[0]["failure_retryable"])
        self.assertEqual(diagnostics[0]["failure_class"], "timeout")
        self.assertEqual(diagnostics[0]["backoff_seconds"], sleep_calls[0])
        self.assertTrue(diagnostics[0]["jitter_seed"])
        self.assertEqual(diagnostics[0]["retry_policy_ref"], MODEL_TRANSPORT_RETRY_POLICY_REF)
        self.assertEqual(diagnostics[1]["final_retry_outcome"], "succeeded_after_retry")

    def test_live_transport_response_records_token_usage_and_provider_status(self) -> None:
        lane = resolve_model_runtime_lane("decomposer_qdt_generation")

        def transport(payload: dict[str, Any]) -> dict[str, Any]:
            self.assertEqual(payload["schema_version"], MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION)
            return {
                "schema_version": MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION,
                "response_payload": {"ok": True},
                "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "provider_status": {"finish_reason": "stop"},
            }

        result = execute_model_runtime_call_for_lane(
            lane=lane,
            prompt_template_id="decomposer-qdt/v1",
            prompt_template_sha256="sha256:" + "1" * 64,
            input_manifest_refs=["artifact:case"],
            output_schema_version="question-decomposition/v1",
            request_payload={"question": "Will example happen?"},
            mode="live",
            transport=transport,
            output_validator=_validator,
        )
        context = model_execution_context_from_runtime_call(
            {"fallback_reason_codes": ["no_fallback_required"]},
            result.runtime_call,
        )

        self.assertEqual(result.response_payload, {"ok": True})
        self.assertEqual(result.runtime_call["token_usage"]["total_tokens"], 15)
        self.assertEqual(result.runtime_call["provider_status"]["finish_reason"], "stop")
        self.assertEqual(context["token_usage"]["total_tokens"], 15)

    def test_openclaw_agent_prompt_contains_phase3_qdt_contract(self) -> None:
        prompt = _openclaw_agent_prompt(
            {
                "schema_version": MODEL_RUNTIME_TRANSPORT_REQUEST_SCHEMA_VERSION,
                "runtime_call_id": "runtime-1",
                "model_lane_id": "decomposer_qdt_generation",
                "provider": "openai",
                "resolved_model_id": "gpt-5.5-high",
                "provider_route": "openclaw_codex_oauth/decomposer",
                "prompt_template_id": "decomposer-qdt/v1",
                "prompt_template_sha256": "sha256:" + "1" * 64,
                "output_schema_version": "question-decomposition/v1",
                "timeout_seconds": 180,
                "request_payload": {
                    "macro_question": "Will Victor Marx win the 2026 Colorado primary?",
                    "market_temporal_state": "unresolved",
                },
            }
        )

        self.assertIn("pre-resolution forecast research", prompt)
        self.assertIn("terminal_verification", prompt)
        self.assertIn("dispatchable pre-resolution", prompt)
        self.assertIn("classification targets", prompt)
        self.assertIn("leaf_temporal_role", prompt)
        self.assertIn("weak AMRG context", prompt)
        self.assertIn("gpt-5.5-high", prompt)

    def test_forbidden_output_fails_closed_before_schema_use(self) -> None:
        with self.assertRaises(ModelRuntimeError) as raised:
            self._call(fixture_response={"ok": True, "probability": 0.7})

        runtime = raised.exception.runtime_call
        self.assertIsInstance(runtime, dict)
        self.assertEqual(runtime["execution_status"], "failed_forbidden_output")
        self.assertEqual(runtime["retry_count"], 0)
        self.assertEqual(runtime["retry_diagnostics"], [])
        self.assertEqual(runtime["forbidden_output_scan"]["status"], "failed")
        self.assertEqual(runtime["forbidden_output_scan"]["matches"][0]["match_type"], "key")

    def test_declarative_forbidden_outputs_list_does_not_fail_scan(self) -> None:
        scan = scan_forbidden_model_outputs(
            {
                "ok": True,
                "required_leaf_questions": [
                    {
                        "leaf_id": "leaf-a",
                        "forbidden_outputs": ["probability", "fair_value", "final_forecast"],
                    }
                ],
            }
        )

        self.assertEqual(scan["status"], "passed")

    def test_active_forbidden_values_still_fail_scan(self) -> None:
        scan = scan_forbidden_model_outputs(
            {
                "ok": True,
                "required_leaf_questions": [
                    {
                        "leaf_id": "leaf-a",
                        "classification_target": "probability",
                    }
                ],
            }
        )

        self.assertEqual(scan["status"], "failed")
        self.assertEqual(scan["matches"][0]["path"], "response.required_leaf_questions[0].classification_target")

    def test_schema_repair_is_bounded_and_records_repair_count(self) -> None:
        def repairer(_value: Any, _errors: list[str]) -> dict[str, Any]:
            return {"ok": True}

        result = self._call(fixture_response={"ok": False}, repairer=repairer)

        self.assertEqual(result.response_payload, {"ok": True})
        self.assertEqual(result.runtime_call["repair_count"], 1)
        self.assertEqual(result.runtime_call["execution_status"], "succeeded")

    def test_wrapped_json_text_response_is_parsed_before_validation(self) -> None:
        result = self._call(fixture_response='```json\\n{"ok": true}\\n```')

        self.assertEqual(result.response_payload, {"ok": True})
        self.assertEqual(result.runtime_call["execution_status"], "succeeded")

    def test_exhausted_transport_retry_returns_failed_runtime_call(self) -> None:
        sleep_calls: list[float] = []

        def transport(_payload: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("down")

        with self.assertRaises(ModelRuntimeError) as raised:
            self._call(mode="live", fixture_response=None, transport=transport, sleep_fn=sleep_calls.append)

        runtime = raised.exception.runtime_call
        self.assertIsInstance(runtime, dict)
        self.assertEqual(runtime["execution_status"], "failed_transport")
        self.assertEqual(runtime["retry_count"], 2)
        self.assertEqual(len(sleep_calls), 2)
        self.assertEqual(
            [item["event"] for item in runtime["retry_diagnostics"]],
            ["local_retry", "local_retry", "retry_exhausted"],
        )
        self.assertEqual(runtime["retry_diagnostics"][-1]["failure_class"], "transient_provider_error")
        self.assertEqual(runtime["retry_diagnostics"][-1]["final_retry_outcome"], "exhausted")

    def test_non_retryable_transport_failure_does_not_retry(self) -> None:
        sleep_calls: list[float] = []

        def transport(_payload: dict[str, Any]) -> dict[str, Any]:
            raise ModelRuntimeError("policy configuration failed")

        with self.assertRaises(ModelRuntimeError) as raised:
            self._call(mode="live", fixture_response=None, transport=transport, sleep_fn=sleep_calls.append)

        runtime = raised.exception.runtime_call
        self.assertEqual(runtime["execution_status"], "failed_transport")
        self.assertEqual(runtime["retry_count"], 0)
        self.assertEqual(sleep_calls, [])
        self.assertEqual([item["event"] for item in runtime["retry_diagnostics"]], ["retry_not_attempted"])
        self.assertFalse(runtime["retry_diagnostics"][0]["failure_retryable"])
        self.assertEqual(runtime["retry_diagnostics"][0]["failure_class"], "model_runtime_contract_error")

    def test_openclaw_agent_stdout_unwraps_gateway_reply(self) -> None:
        stdout = json_text = (
            '{"reply":"{\\"schema_version\\":\\"model-runtime-transport-response/v1\\",'
            '\\"response_payload\\":{\\"ok\\":true},'
            '\\"provider_status\\":{\\"status\\":\\"completed\\"}}"}'
        )

        parsed = _parse_openclaw_agent_stdout(stdout)

        self.assertEqual(json_text, stdout)
        self.assertEqual(parsed["schema_version"], MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION)
        self.assertEqual(parsed["response_payload"], {"ok": True})
        self.assertEqual(parsed["provider_status"]["status"], "completed")

    def test_openclaw_agent_stdout_unwraps_payload_text_shape(self) -> None:
        stdout = (
            '{"runId":"run-1","status":"ok","result":{"payloads":[{"text":"'
            '{\\"schema_version\\":\\"model-runtime-transport-response/v1\\",'
            '\\"response_payload\\":{\\"ok\\":true},'
            '\\"provider_status\\":{\\"status\\":\\"completed\\"}}'
            '"}],"finalAssistantVisibleText":"ignored"}}'
        )

        parsed = _parse_openclaw_agent_stdout(stdout)

        self.assertEqual(parsed["schema_version"], MODEL_RUNTIME_TRANSPORT_RESPONSE_SCHEMA_VERSION)
        self.assertEqual(parsed["response_payload"], {"ok": True})
        self.assertEqual(parsed["provider_status"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
