#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_current_audit_plan_closure import (
    build_current_audit_plan_closure_report,
    parse_current_audit_plan_phase_statuses,
)


def _plan_text(*, incomplete_phase: int | None = None) -> str:
    lines = ["# Test ADS Plan", ""]
    for phase in range(10):
        lines.append(f"## Phase {phase} - Test Phase {phase}")
        status = "pending" if phase == incomplete_phase else "complete"
        if phase == 0 and incomplete_phase != 0:
            status = "completed on 2026-06-30"
        lines.append(f"Status: {status}")
        lines.append("")
    lines.append("## Phase 10 - Plan Closure And Next-State Decision")
    lines.append("Status: pending")
    return "\n".join(lines)


def _phase9_report(*, ok: bool = True) -> dict:
    return {
        "schema_version": "ads-phase9-representative-batch/v1",
        "ok": ok,
        "status": "passed" if ok else "blocked",
        "issues": [] if ok else ["missing_scoreable_success"],
        "case_count": 4,
        "scoreable_success_count": 1 if ok else 0,
        "unexpected_failure_count": 0,
        "clone_only_case_count": 4,
        "missing_representative_tags": [],
    }


def _live_readiness_report(
    *,
    status: str = "blocked_true_runtime_cutover",
    true_runtime_cutover_status: str = "blocked_clone_only_canary",
    true_runtime_cutover_ready: bool = False,
    clears_cal001: bool = False,
    include_cal001: bool = True,
) -> dict:
    report = {
        "schema_version": "ads-live-readiness-report/v1",
        "ok": True,
        "status": status,
        "true_runtime_cutover_status": true_runtime_cutover_status,
        "true_runtime_cutover_ready": true_runtime_cutover_ready,
        "live_db_mutation": "clone_only" if true_runtime_cutover_status == "blocked_clone_only_canary" else "unknown_or_live",
        "clone_only": true_runtime_cutover_status == "blocked_clone_only_canary",
        "issues": [],
    }
    if include_cal001:
        report["calibration_debt_report"] = {
            "feature_id": "CAL-001",
            "clears_calibration_debt": clears_cal001,
        }
    return report


class AdsCurrentAuditPlanClosureTest(unittest.TestCase):
    def test_closure_is_ready_for_vm_review_but_not_live_cutover_without_authorization(self):
        report = build_current_audit_plan_closure_report(
            phase_statuses=parse_current_audit_plan_phase_statuses(_plan_text()),
            phase9_report=_phase9_report(),
            live_readiness_report=_live_readiness_report(),
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["plan_status"], "implementation_ready_for_vm_review")
        self.assertEqual(report["next_state"], "awaiting_vm_review_and_live_authorization")
        self.assertEqual(report["live_cutover_decision"], "blocked_vm_authorization_required")
        self.assertIn("live_readiness:blocked_clone_only_canary", report["remaining_blockers"])
        self.assertIn("cal001_not_cleared", report["remaining_blockers"])
        self.assertIn("vm_live_mutation_authorization_required", report["remaining_blockers"])
        self.assertFalse(report["live_mutation_authorized"])
        self.assertTrue(report["phase_completion"]["all_required_phase_checklists_evaluated"])

    def test_closure_blocks_when_required_phase_is_incomplete(self):
        report = build_current_audit_plan_closure_report(
            phase_statuses=parse_current_audit_plan_phase_statuses(_plan_text(incomplete_phase=4)),
            phase9_report=_phase9_report(),
            live_readiness_report=_live_readiness_report(),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["plan_status"], "blocked")
        self.assertEqual(report["blocking_phase"], "Phase 4")
        self.assertIn("required_phase_not_complete", report["issues"])

    def test_closure_blocks_when_phase9_batch_did_not_pass(self):
        report = build_current_audit_plan_closure_report(
            phase_statuses=parse_current_audit_plan_phase_statuses(_plan_text()),
            phase9_report=_phase9_report(ok=False),
            live_readiness_report=_live_readiness_report(),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["blocking_phase"], "Phase 9")
        self.assertIn("phase9_representative_batch_not_passed", report["issues"])

    def test_closure_blocks_when_cal001_is_not_honestly_represented(self):
        report = build_current_audit_plan_closure_report(
            phase_statuses=parse_current_audit_plan_phase_statuses(_plan_text()),
            phase9_report=_phase9_report(),
            live_readiness_report=_live_readiness_report(include_cal001=False),
        )

        self.assertFalse(report["ok"])
        self.assertIn("cal001_not_honestly_represented", report["issues"])

    def test_authorized_ready_readiness_can_report_live_cutover_ready(self):
        report = build_current_audit_plan_closure_report(
            phase_statuses=parse_current_audit_plan_phase_statuses(_plan_text()),
            phase9_report=_phase9_report(),
            live_readiness_report=_live_readiness_report(
                status="ready",
                true_runtime_cutover_status="ready",
                true_runtime_cutover_ready=True,
                clears_cal001=True,
            ),
            live_mutation_authorized=True,
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["plan_status"], "ready_for_live_cutover")
        self.assertEqual(report["live_cutover_decision"], "ready_after_explicit_authorization")
        self.assertEqual(report["remaining_blockers"], [])

    def test_cli_reports_closure_status(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "report_ads_current_audit_plan_closure.py"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            plan_path = root / "plan.md"
            phase9_path = root / "phase9.json"
            readiness_path = root / "readiness.json"
            plan_path.write_text(_plan_text(), encoding="utf-8")
            phase9_path.write_text(json.dumps(_phase9_report(), sort_keys=True), encoding="utf-8")
            readiness_path.write_text(json.dumps(_live_readiness_report(), sort_keys=True), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--plan-path",
                    str(plan_path),
                    "--phase9-report-json",
                    str(phase9_path),
                    "--live-readiness-report-json",
                    str(readiness_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        report = json.loads(completed.stdout)
        self.assertEqual(report["schema_version"], "ads-current-audit-plan-closure/v1")
        self.assertEqual(report["plan_status"], "implementation_ready_for_vm_review")


if __name__ == "__main__":
    unittest.main()
