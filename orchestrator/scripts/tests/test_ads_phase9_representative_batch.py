#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_phase9_representative_batch import build_phase9_representative_batch_report


def _report(
    *,
    classification: str,
    tag: str,
    pipeline_run_id: str,
    clone_only: bool = True,
    no_scoreable_write_when_blocked: bool = True,
    market_predictions_delta: int = 0,
    retry_attempt_count: int = 0,
    retry_backoff_seconds: list[float] | None = None,
) -> dict:
    live_db_mutation = "clone_only" if clone_only else "unknown_or_live"
    retry_summary = {
        "retry_attempt_count": retry_attempt_count,
        "retryable_failure_count": retry_attempt_count,
        "non_retryable_failure_count": 0,
        "terminal_retry_exhausted_count": 0,
        "stage_retry_scheduled_count": retry_attempt_count,
        "qdt_model_transport_retry_count": 0,
        "retry_backoff_seconds": retry_backoff_seconds or [],
        "retry_policy_refs": ["unit-test-retry-policy/v1"] if retry_attempt_count else [],
        "components": ["retrieval"] if retry_attempt_count else [],
        "final_retry_outcome": "retry_recorded" if retry_attempt_count else "no_retries_recorded",
    }
    scoreable_success_requirements = {
        "qdt_quality_passed": True,
        "retrieval_acceptance_passed": True,
        "researcher_model_executed": True,
        "classification_verification_passed": True,
        "scae_valid_forecast_has_delta_refs": True,
        "decision_authorized_prediction_persisted": True,
    }
    return {
        "selector": tag,
        "representative_tags": [tag],
        "real_runtime_report": {
            "pipeline_run_id": pipeline_run_id,
            "live_db_mutation": live_db_mutation,
            "clone_only": clone_only,
            "active_work": {"active_runs": 0, "active_leases": 0},
            "handoff_report": {"ok": True},
            "retry_summary": retry_summary,
            "prediction_delta_evidence": {
                "market_predictions_delta": market_predictions_delta,
            },
            "phase9_representative_case": {
                "classification": classification,
                "reason_codes": ["unit_test"],
                "clone_only": clone_only,
                "live_db_mutation": live_db_mutation,
                "retry_summary": retry_summary,
                "no_scoreable_write_when_blocked": no_scoreable_write_when_blocked,
                "scoreable_success_requirements": scoreable_success_requirements
                if classification == "scoreable_success"
                else {
                    key: False for key in scoreable_success_requirements
                },
            },
        },
    }


def _passing_cases() -> list[dict]:
    return [
        _report(
            classification="scoreable_success",
            tag="boi_central_bank_rate_decision",
            pipeline_run_id="run:boi",
            market_predictions_delta=1,
        ),
        _report(
            classification="structured_non_scoreable_insufficiency",
            tag="protected_primary_binary_market",
            pipeline_run_id="run:protected-primary",
        ),
        _report(
            classification="structural_unanswerability",
            tag="market_family_sibling_context",
            pipeline_run_id="run:sibling",
        ),
        _report(
            classification="structured_non_scoreable_insufficiency",
            tag="unresolved_pre_resolution_qdt",
            pipeline_run_id="run:unresolved",
            retry_attempt_count=1,
            retry_backoff_seconds=[2.5],
        ),
    ]


class AdsPhase9RepresentativeBatchTest(unittest.TestCase):
    def test_batch_report_passes_representative_clone_success_and_blocked_cases(self):
        report = build_phase9_representative_batch_report(_passing_cases())

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["case_count"], 4)
        self.assertEqual(report["scoreable_success_count"], 1)
        self.assertEqual(report["unexpected_failure_count"], 0)
        self.assertEqual(report["clone_only_case_count"], 4)
        self.assertEqual(report["missing_representative_tags"], [])
        self.assertEqual(report["classification_counts"]["structured_non_scoreable_insufficiency"], 2)
        self.assertTrue(all(item["retry_bounded"] for item in report["case_summaries"]))

    def test_batch_report_blocks_missing_scoreable_success(self):
        cases = _passing_cases()
        cases[0] = _report(
            classification="structured_non_scoreable_insufficiency",
            tag="boi_central_bank_rate_decision",
            pipeline_run_id="run:boi",
        )

        report = build_phase9_representative_batch_report(cases)

        self.assertFalse(report["ok"])
        self.assertIn("missing_scoreable_success", report["issues"])

    def test_batch_report_blocks_non_clone_only_case(self):
        cases = _passing_cases()
        cases[1] = _report(
            classification="structured_non_scoreable_insufficiency",
            tag="protected_primary_binary_market",
            pipeline_run_id="run:protected-primary",
            clone_only=False,
        )

        report = build_phase9_representative_batch_report(cases)

        self.assertFalse(report["ok"])
        self.assertIn("non_clone_only_case", report["issues"])
        self.assertIn("case_not_explicit_clone_only", report["case_summaries"][1]["issues"])

    def test_batch_report_blocks_retry_storm(self):
        cases = _passing_cases()
        cases[3] = _report(
            classification="structured_non_scoreable_insufficiency",
            tag="unresolved_pre_resolution_qdt",
            pipeline_run_id="run:unresolved",
            retry_attempt_count=25,
            retry_backoff_seconds=[2.0],
        )

        report = build_phase9_representative_batch_report(cases)

        self.assertFalse(report["ok"])
        self.assertIn("retry_attempts_or_backoff_exceed_policy", report["issues"])

    def test_batch_report_blocks_scoreable_success_without_prediction(self):
        cases = _passing_cases()
        cases[0] = _report(
            classification="scoreable_success",
            tag="boi_central_bank_rate_decision",
            pipeline_run_id="run:boi",
            market_predictions_delta=0,
        )

        report = build_phase9_representative_batch_report(cases)

        self.assertFalse(report["ok"])
        self.assertIn("scoreable_success_market_prediction_missing", report["issues"])

    def test_batch_report_blocks_scoreable_write_from_blocked_case(self):
        cases = _passing_cases()
        cases[1] = _report(
            classification="structured_non_scoreable_insufficiency",
            tag="protected_primary_binary_market",
            pipeline_run_id="run:protected-primary",
            no_scoreable_write_when_blocked=False,
            market_predictions_delta=1,
        )

        report = build_phase9_representative_batch_report(cases)

        self.assertFalse(report["ok"])
        self.assertIn("blocked_case_wrote_scoreable_prediction", report["issues"])
        self.assertIn("blocked_case_market_prediction_delta_nonzero", report["issues"])

    def test_cli_reports_phase9_batch_status(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "report_ads_phase9_representative_batch.py"
        with tempfile.TemporaryDirectory() as tempdir:
            paths = []
            for index, case in enumerate(_passing_cases(), start=1):
                path = Path(tempdir) / f"case-{index}.json"
                path.write_text(json.dumps(case, sort_keys=True), encoding="utf-8")
                paths.append(path)
            command = [sys.executable, str(script)]
            for path in paths:
                command.extend(["--case-report", str(path)])
            completed = subprocess.run(command, check=True, capture_output=True, text=True)

        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["schema_version"], "ads-phase9-representative-batch/v1")


if __name__ == "__main__":
    unittest.main()
