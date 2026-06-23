from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_context_prune_maintenance.py"
spec = importlib.util.spec_from_file_location("run_context_prune_maintenance", MODULE_PATH)
wrapper = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = wrapper
spec.loader.exec_module(wrapper)


class FakeEnvelope:
    def __init__(self, run_id: str = "unit-run") -> None:
        self.run_id = run_id
        self.warnings: list[str] = []
        self.artifacts: dict[str, str] = {}
        self.artifact_paths: list[str] = []
        self.retry_results: dict[str, dict] = {}
        self.retry_calls: list[dict] = []

    def write_artifact(self, name: str, content: str) -> Path:
        self.artifacts[name] = content
        return Path(name)

    def add_artifact(self, path: Path) -> None:
        self.artifact_paths.append(str(path))

    def run_subprocess_with_retries(self, cmd, cwd, label, attempts=1, backoff_seconds=0):  # noqa: ANN001, ARG002
        self.retry_calls.append({"cmd": cmd, "cwd": cwd, "label": label, "attempts": attempts, "backoff_seconds": backoff_seconds})
        result = self.retry_results.get(label)
        if result is None:
            result = {"items": 1, "review": 0, "prune_candidate": 0, "budget_summary": {}}
        return SimpleNamespace(stdout=json.dumps(result))


class RunContextPruneMaintenanceTest(unittest.TestCase):
    def test_apply_payload_surfaces_candidate_summary_and_byte_delta(self) -> None:
        apply_result = {
            "mode": "dry_run",
            "archive_root": "/tmp/archive",
            "pre_apply_manifest": "/tmp/archive/pre-apply-manifest.json",
            "candidate_summary": {
                "candidate_count_total": 2,
                "allowlisted_candidate_count": 2,
                "range_count_total": 1,
                "nested_deduped_count": 1,
                "project_spine_budget_target_bytes": 100000,
                "project_spine_budget_projected_after_bytes": 99000,
                "project_spine_budget_deficit_after_planning": 0,
                "project_spine_budget_escalated_candidate_count": 1,
                "project_spine_budget_escalated_bytes": 12000,
                "project_spine_budget_blockers": [],
            },
            "project_spine_budget_pressure": {
                "project_spine_budget_target_bytes": 100000,
                "project_spine_budget_projected_after_bytes": 99000,
                "project_spine_budget_deficit_after_planning": 0,
                "project_spine_budget_escalated_candidate_count": 1,
                "project_spine_budget_escalated_bytes": 12000,
                "project_spine_budget_blockers": [],
            },
            "budget_summary": {
                "hot_markdown_bytes_total": 1000,
                "hot_markdown_budget_success": False,
                "budget_success": False,
                "hot_docs": {
                    "context/active.md": {
                        "bytes": 1000,
                        "target_bytes": 500,
                        "pressure_level": "target",
                    }
                },
                "protected_budget_debt": {
                    "protected_budget_debt_bytes_total": 600,
                    "protected_budget_debt_by_category": {"recent_zero_to_three_day_content": 600},
                    "protected_budget_debt_routes": {"defer_recent_content": 600},
                    "top_protected_spans": [{"path": "context/active.md"}],
                    "stale_strong_evidence_overflow_bytes_total": 0,
                    "stale_strong_evidence_overflow_spans": [],
                },
            },
            "apply_acceptance": {
                "large_shrink_requires_override": True,
                "large_shrink_file_count": 1,
                "max_file_shrink_ratio": 0.35,
            },
            "apply_blocked": True,
            "large_shrink_requires_override": True,
            "range_records": [{"path": "context/active.md"}],
            "source_bytes_before_total": 1000,
            "source_bytes_after_planned_total": 800,
            "source_bytes_delta_planned_total": -200,
            "no_op_reason": "none",
            "files": [
                {
                    "path": "context/active.md",
                    "removed_blocks": 1,
                    "source_bytes_before": 1000,
                    "source_bytes_after_planned": 800,
                    "source_bytes_delta_planned": -200,
                    "source_lines_before": 20,
                    "source_lines_after_planned": 15,
                    "source_lines_delta_planned": -5,
                }
            ],
            "local_compression": {
                "attempted": 1,
                "succeeded": 0,
                "fallback": 1,
                "errors": [{"error": "local model busy"}],
            },
        }

        payload = wrapper.apply_payload(apply_result, stamp="unit-stamp", dry_run=True, reindexed=False)

        self.assertEqual(payload["candidate_summary"]["candidate_count_total"], 2)
        self.assertEqual(payload["candidate_summary"]["nested_deduped_count"], 1)
        self.assertEqual(payload["project_spine_budget_pressure"]["project_spine_budget_projected_after_bytes"], 99000)
        self.assertEqual(payload["project_spine_budget_pressure"]["project_spine_budget_escalated_candidate_count"], 1)
        self.assertEqual(payload["budget_summary"]["hot_markdown_bytes_total"], 1000)
        self.assertEqual(payload["budget_summary"]["hot_docs"]["context/active.md"]["pressure_level"], "target")
        self.assertEqual(payload["protected_budget_debt"]["bytes_total"], 600)
        self.assertEqual(payload["protected_budget_debt"]["by_category"], {"recent_zero_to_three_day_content": 600})
        self.assertFalse(payload["protected_budget_debt"]["budget_success"])
        self.assertTrue(payload["apply_blocked"])
        self.assertTrue(payload["large_shrink_requires_override"])
        self.assertEqual(payload["apply_acceptance"]["large_shrink_file_count"], 1)
        self.assertEqual(payload["range_records_count"], 1)
        self.assertEqual(payload["source_bytes_before_total"], 1000)
        self.assertEqual(payload["source_bytes_after_planned_total"], 800)
        self.assertEqual(payload["source_bytes_delta_planned_total"], -200)
        self.assertEqual(payload["no_op_reason"], "none")
        self.assertEqual(payload["removed_files"], 1)
        self.assertEqual(payload["removed_blocks"], 1)
        self.assertEqual(
            payload["file_deltas"][0],
            {
                "path": "context/active.md",
                "removed_blocks": 1,
                "source_bytes_before": 1000,
                "source_bytes_after_planned": 800,
                "source_bytes_delta_planned": -200,
                "source_lines_before": 20,
                "source_lines_after_planned": 15,
                "source_lines_delta_planned": -5,
            },
        )
        self.assertEqual(payload["local_compression"]["attempted"], 1)
        self.assertEqual(payload["local_compression"]["succeeded"], 0)
        self.assertEqual(payload["local_compression"]["fallback"], 1)
        self.assertEqual(payload["local_compression"]["error_count"], 1)

    def test_audit_payload_surfaces_budget_summary(self) -> None:
        payload = wrapper.audit_payload(
            {
                "items": 3,
                "review": 1,
                "prune_candidate": 2,
                "budget_summary": {
                    "hot_markdown_budget_success": True,
                    "budget_success": True,
                    "protected_budget_debt": {
                        "protected_budget_debt_bytes_total": 0,
                        "protected_budget_debt_by_category": {},
                        "protected_budget_debt_routes": {},
                        "top_protected_spans": [],
                    },
                },
                "report": "/tmp/report.md",
                "state": "/tmp/state.json",
                "run": "/tmp/envelope.json",
            }
        )

        self.assertTrue(payload["budget_summary"]["hot_markdown_budget_success"])
        self.assertEqual(payload["protected_budget_debt"]["bytes_total"], 0)
        self.assertTrue(payload["protected_budget_debt"]["budget_success"])
        self.assertEqual(payload["review"], 1)
        self.assertEqual(payload["prune_candidate"], 2)

    def pressure_args(self, *, dry_run: bool = False, local_compress: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            dry_run=dry_run,
            local_compress=local_compress,
            local_compress_model="qwen3.5:4b",
            local_compress_max_blocks=3,
            local_compress_timeout_seconds=180,
            local_compress_lock_timeout_seconds=600.0,
            local_compress_priority=True,
            local_compress_max_summary_chars=700,
            quant_byte_threshold=100000,
            active_byte_threshold=25000,
            prune_candidate_threshold=12,
            planned_byte_savings_threshold=7500,
            cooldown_hours=24,
            identity_mode="content-primary",
        )

    def pressure_dry_run_result(self) -> dict:
        return {
            "budget_summary": {
                "hot_docs": {
                    "context/projects/quant-pipeline.md": {
                        "bytes": 130000,
                        "target_bytes": 100000,
                        "hard_bytes": 125000,
                        "pressure_level": "hard",
                        "projected_bytes_after_apply": 99000,
                        "projected_pressure_level_after_apply": "none",
                    },
                    "context/active.md": {
                        "bytes": 12000,
                        "target_bytes": 25000,
                        "hard_bytes": 30000,
                        "pressure_level": "none",
                    },
                },
                "active_live_headings": {},
            },
            "candidate_summary": {
                "candidate_count_total": 13,
                "range_count_total": 3,
            },
            "project_spine_budget_pressure": {
                "project_spine_budget_target_bytes": 100000,
                "project_spine_budget_projected_after_bytes": 99000,
                "project_spine_budget_deficit_after_planning": 0,
                "project_spine_budget_blockers": [],
            },
            "range_records": [{"path": "context/projects/quant-pipeline.md"}],
            "source_bytes_delta_planned_total": -8000,
            "apply_acceptance": {"blocked": False, "hard_blocker_count": 0},
        }

    def below_threshold_pressure_dry_run_result(self) -> dict:
        result = self.pressure_dry_run_result()
        result["budget_summary"]["hot_docs"]["context/projects/quant-pipeline.md"].update(
            {
                "bytes": 90000,
                "target_bytes": 100000,
                "hard_bytes": 125000,
                "pressure_level": "none",
                "projected_bytes_after_apply": 89000,
                "projected_pressure_level_after_apply": "none",
            }
        )
        result["candidate_summary"] = {"candidate_count_total": 2, "range_count_total": 1}
        result["range_records"] = [{"path": "context/projects/quant-pipeline.md"}]
        result["source_bytes_delta_planned_total"] = -1000
        result["project_spine_budget_pressure"] = {
            "project_spine_budget_target_bytes": 100000,
            "project_spine_budget_projected_after_bytes": 89000,
            "project_spine_budget_deficit_after_planning": 0,
            "project_spine_budget_blockers": [],
        }
        return result

    def budget_deficit_pressure_dry_run_result(self) -> dict:
        result = self.pressure_dry_run_result()
        result["budget_summary"]["hot_docs"]["context/projects/quant-pipeline.md"].update(
            {
                "bytes": 140000,
                "target_bytes": 100000,
                "hard_bytes": 125000,
                "pressure_level": "hard",
                "projected_bytes_after_apply": 112000,
                "projected_pressure_level_after_apply": "target",
            }
        )
        result["project_spine_budget_pressure"] = {
            "project_spine_budget_target_bytes": 100000,
            "project_spine_budget_projected_after_bytes": 112000,
            "project_spine_budget_deficit_after_planning": 12000,
            "project_spine_budget_blockers": [{"reason": "strong_evidence_blocks_target"}],
        }
        return result

    def budget_met_pressure_summary(self) -> dict:
        summary = deepcopy(self.pressure_dry_run_result()["budget_summary"])
        summary["hot_docs"]["context/projects/quant-pipeline.md"].update(
            {
                "bytes": 99000,
                "target_bytes": 100000,
                "hard_bytes": 125000,
                "pressure_level": "none",
                "projected_bytes_after_apply": 99000,
                "projected_pressure_level_after_apply": "none",
            }
        )
        return summary

    def active_hard_budget_summary(self) -> dict:
        summary = self.budget_met_pressure_summary()
        summary["hot_docs"]["context/active.md"].update(
            {
                "bytes": 32000,
                "target_bytes": 25000,
                "hard_bytes": 30000,
                "pressure_level": "hard",
            }
        )
        return summary

    def fake_pressure_apply_run(
        self,
        *,
        post_budget_summary: dict | None = None,
        files: list[dict] | None = None,
        bytes_delta: int = -8000,
        reindexed: bool = True,
    ) -> dict:
        apply_result = self.pressure_dry_run_result()
        if files is None:
            files = [
                {
                    "path": "context/projects/quant-pipeline.md",
                    "removed_blocks": 1,
                    "source_bytes_before": 130000,
                    "source_bytes_after_planned": 122000,
                    "source_bytes_delta_planned": -8000,
                    "source_lines_before": 2000,
                    "source_lines_after_planned": 1900,
                    "source_lines_delta_planned": -100,
                }
            ]
        apply_result = {
            **apply_result,
            "mode": "apply",
            "files": files,
            "no_op_reason": "none",
        }
        return {
            "telemetry_summary": {"entry_count": 5, "covered_file_count": 2, "warning_count": 0},
            "apply_result": apply_result,
            "audit_result": {"items": 8, "review": 1, "prune_candidate": 4, "budget_summary": post_budget_summary or self.budget_met_pressure_summary()},
            "removed_files": len(files),
            "removed_blocks": sum(int(file.get("removed_blocks", 0) or 0) for file in files),
            "bytes_delta": bytes_delta,
            "no_op_reason": "none",
            "reindexed": reindexed,
        }

    def fake_decisions_apply_run(self) -> dict:
        manifest = {
            "mode": "decisions-apply",
            "source_path": "context/decisions.md",
            "source_mutated": True,
            "archive_path": "/tmp/decisions.before.md",
            "validation_status": "passed",
            "validation_failures": [],
            "no_op_reason": None,
            "bytes_before": 20000,
            "bytes_after_planned": 17000,
            "bytes_delta_planned": -3000,
            "budget_deficit_after_consolidation": 0,
            "consolidation_group_count": 2,
            "exact_duplicate_group_count": 1,
            "shared_prefix_group_count": 1,
            "plan_summary_path": "/tmp/decisions-consolidation-summary.json",
            "plan_path": "/tmp/decisions-consolidation-plan.md",
            "patch_path": "/tmp/decisions-consolidation.patch",
            "apply_manifest_path": "/tmp/decisions-consolidation-apply-manifest.json",
        }
        return {
            "manifest": manifest,
            "audit_result": {"items": 7, "review": 1, "prune_candidate": 3, "budget_summary": {}},
            "source_mutated": True,
            "bytes_delta": -3000,
            "validation_status": "passed",
            "no_op_reason": "none",
            "reindexed": True,
        }

    def fake_decisions_noop_run(self) -> dict:
        manifest = {
            "mode": "decisions-apply",
            "source_path": "context/decisions.md",
            "source_mutated": False,
            "archive_path": None,
            "validation_status": "noop",
            "validation_failures": ["insufficient_safe_decisions_shrink"],
            "no_op_reason": "insufficient_safe_decisions_shrink",
            "bytes_before": 22000,
            "bytes_after_planned": 21800,
            "bytes_delta_planned": -200,
            "budget_deficit_after_consolidation": 6800,
            "consolidation_group_count": 0,
            "exact_duplicate_group_count": 0,
            "shared_prefix_group_count": 0,
            "plan_summary_path": "/tmp/decisions-consolidation-summary.json",
            "plan_path": "/tmp/decisions-consolidation-plan.md",
            "patch_path": "/tmp/decisions-consolidation.patch",
            "apply_manifest_path": "/tmp/decisions-consolidation-apply-manifest.json",
            "decisions_backlog": {
                "status": "review_required",
                "reason": "repeated_insufficient_safe_shrink",
                "repeated_count": 3,
                "safe_candidates": 0,
                "blocked_scope": {
                    "source_path": "context/decisions.md",
                    "validation_status": "noop",
                    "reason": "insufficient_safe_decisions_shrink",
                    "budget_deficit_after_consolidation": 6800,
                    "min_shrink_bytes": 1000,
                },
                "allowed_forward_lanes": ["manual_decisions_consolidation_review", "generic_context_prune_apply_ranges", "state_compaction"],
                "recommended_action": "manual_decisions_consolidation_review",
                "history_path": "/tmp/decisions-backlog-history.json",
                "status_path": "/tmp/decisions-backlog-status.json",
                "markdown_path": "/tmp/decisions-backlog-status.md",
            },
        }
        return {
            "manifest": manifest,
            "audit_result": {
                "items": 7,
                "review": 1,
                "prune_candidate": 0,
                "budget_summary": {"decisions_autonomous_consolidation_required": True},
            },
            "source_mutated": False,
            "bytes_delta": -200,
            "validation_status": "noop",
            "no_op_reason": "insufficient_safe_decisions_shrink",
            "reindexed": False,
        }

    def run_pressure_check_with_fakes(
        self,
        *,
        args: SimpleNamespace,
        dry_run_result: dict | None = None,
        audit_result: dict | None = None,
        pressure_state: dict | None = None,
        existing_lock_busy: bool = False,
        apply_lock_acquired: bool = True,
        apply_run: dict | None = None,
        decisions_run: dict | None = None,
        decisions_calls: list[dict] | None = None,
        state_compaction_result: dict | None = None,
    ) -> tuple[str, FakeEnvelope, list[dict], list[dict]]:
        dry_run_result = dry_run_result or self.pressure_dry_run_result()
        audit_result = audit_result or {"items": 8, "review": 1, "prune_candidate": 13, "budget_summary": dry_run_result.get("budget_summary", {})}
        pressure_state = pressure_state or {}
        apply_calls: list[dict] = []
        state_writes: list[dict] = []

        original_refresh = wrapper.refresh_context_telemetry
        original_run_json = wrapper.run_json
        original_run_pressure_dry_run_apply = wrapper.run_pressure_dry_run_apply
        original_load_pressure_trigger_state = wrapper.load_pressure_trigger_state
        original_existing_apply_lock_busy = wrapper.existing_apply_lock_busy
        original_write_pressure_trigger_state = wrapper.write_pressure_trigger_state
        original_apply_lock = wrapper.ApplyLock
        original_run_apply_and_post_audit = wrapper.run_apply_and_post_audit
        original_run_decisions_apply_and_post_audit = wrapper.run_decisions_apply_and_post_audit

        class FakeApplyLock:
            def __init__(self, *, envelope, mode, path=None, stale_seconds=None):  # noqa: ANN001, ARG002
                self.acquired = apply_lock_acquired

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return None

        def fake_write_pressure_trigger_state(previous_state, *, result, evaluation, envelope):  # noqa: ANN001
            payload = wrapper.build_pressure_trigger_state_payload(
                previous_state,
                result=result,
                evaluation=evaluation,
                envelope=envelope,
                updated_at="2026-05-27T05:00:00Z",
            )
            state_writes.append(payload)
            return payload

        def fake_run_apply_and_post_audit(apply_args, stamp, envelope, **kwargs):  # noqa: ANN001
            apply_calls.append({"args": apply_args, "stamp": stamp, "kwargs": kwargs})
            if apply_run is None:
                raise AssertionError("run_apply_and_post_audit should not be called for this pressure-check path")
            return apply_run

        def fake_run_decisions_apply_and_post_audit(apply_args, stamp, envelope, **kwargs):  # noqa: ANN001
            if decisions_calls is not None:
                decisions_calls.append({"args": apply_args, "stamp": stamp, "kwargs": kwargs})
            if decisions_run is None:
                raise AssertionError("run_decisions_apply_and_post_audit should not be called for this pressure-check path")
            return decisions_run

        def fake_run_json(cmd, envelope, label):  # noqa: ANN001
            if "state-compaction" in label:
                if state_compaction_result is None:
                    raise AssertionError("pressure-state-compaction should not be called for this pressure-check path")
                return state_compaction_result
            return audit_result

        try:
            wrapper.refresh_context_telemetry = lambda envelope, **kwargs: {"entry_count": 5, "covered_file_count": 2, "warning_count": 0}
            wrapper.run_json = fake_run_json
            wrapper.run_pressure_dry_run_apply = lambda stamp, envelope, **kwargs: dry_run_result
            wrapper.load_pressure_trigger_state = lambda: pressure_state
            wrapper.existing_apply_lock_busy = lambda path=None: existing_lock_busy
            wrapper.write_pressure_trigger_state = fake_write_pressure_trigger_state
            wrapper.ApplyLock = FakeApplyLock
            wrapper.run_apply_and_post_audit = fake_run_apply_and_post_audit
            wrapper.run_decisions_apply_and_post_audit = fake_run_decisions_apply_and_post_audit
            envelope = FakeEnvelope(run_id="pressure-check-run")
            summary = wrapper.do_pressure_check(args, "unit-pressure", envelope)
            return summary, envelope, state_writes, apply_calls
        finally:
            wrapper.refresh_context_telemetry = original_refresh
            wrapper.run_json = original_run_json
            wrapper.run_pressure_dry_run_apply = original_run_pressure_dry_run_apply
            wrapper.load_pressure_trigger_state = original_load_pressure_trigger_state
            wrapper.existing_apply_lock_busy = original_existing_apply_lock_busy
            wrapper.write_pressure_trigger_state = original_write_pressure_trigger_state
            wrapper.ApplyLock = original_apply_lock
            wrapper.run_apply_and_post_audit = original_run_apply_and_post_audit
            wrapper.run_decisions_apply_and_post_audit = original_run_decisions_apply_and_post_audit

    def test_pressure_check_parser_defaults_and_local_flags(self) -> None:
        args = wrapper.build_parser().parse_args(["pressure-check", "--dry-run", "--no-local-compress", "--quant-byte-threshold", "123456"])

        self.assertEqual(args.cmd, "pressure-check")
        self.assertTrue(args.dry_run)
        self.assertFalse(args.local_compress)
        self.assertEqual(args.quant_byte_threshold, 123456)
        self.assertEqual(args.active_byte_threshold, 25000)
        self.assertEqual(args.prune_candidate_threshold, 12)
        self.assertEqual(args.planned_byte_savings_threshold, 7500)
        self.assertEqual(args.cooldown_hours, 24)
        self.assertIsNone(args.stamp)
        self.assertEqual(args.identity_mode, "content-primary")

    def test_wrapper_parser_accepts_identity_mode_rollback_flag(self) -> None:
        parser = wrapper.build_parser()

        self.assertEqual(parser.parse_args(["audit", "--identity-mode", "line-legacy"]).identity_mode, "line-legacy")
        self.assertEqual(parser.parse_args(["weekly-apply", "--identity-mode", "line-legacy"]).identity_mode, "line-legacy")
        self.assertEqual(parser.parse_args(["pressure-check", "--identity-mode", "line-legacy"]).identity_mode, "line-legacy")
        self.assertEqual(parser.parse_args(["rebase-state", "--dry-run", "--identity-mode", "line-legacy"]).identity_mode, "line-legacy")
        self.assertEqual(parser.parse_args(["compact-state", "--dry-run", "--identity-mode", "line-legacy"]).identity_mode, "line-legacy")

    def test_wrapper_parser_accepts_decisions_commands(self) -> None:
        parser = wrapper.build_parser()

        plan = parser.parse_args(["decisions-plan", "--stamp", "unit-decisions"])
        apply = parser.parse_args(["decisions-apply", "--stamp", "unit-decisions", "--min-shrink-bytes", "250", "--identity-mode", "line-legacy"])

        self.assertEqual(plan.cmd, "decisions-plan")
        self.assertEqual(plan.stamp, "unit-decisions")
        self.assertEqual(apply.cmd, "decisions-apply")
        self.assertEqual(apply.stamp, "unit-decisions")
        self.assertEqual(apply.min_shrink_bytes, 250)
        self.assertEqual(apply.identity_mode, "line-legacy")

    def test_decisions_payload_surfaces_wrapper_fields(self) -> None:
        payload = wrapper.decisions_payload(
            {
                "source_path": "context/decisions.md",
                "source_mutated": True,
                "archive_path": "/tmp/archive/decisions.before.md",
                "validation_status": "passed",
                "bytes_before": 20000,
                "bytes_after_planned": 17000,
                "bytes_delta_planned": -3000,
                "budget_deficit_after_consolidation": 0,
                "consolidation_group_count": 2,
                "exact_duplicate_group_count": 1,
                "shared_prefix_group_count": 1,
                "plan_summary_path": "/tmp/decisions-consolidation-summary.json",
                "plan_path": "/tmp/decisions-consolidation-plan.md",
                "patch_path": "/tmp/decisions-consolidation.patch",
                "apply_manifest_path": "/tmp/decisions-consolidation-apply-manifest.json",
                "decisions_backlog": {
                    "status": "review_required",
                    "reason": "repeated_insufficient_safe_shrink",
                    "repeated_count": 3,
                    "safe_candidates": 1,
                    "blocked_scope": {"source_path": "context/decisions.md"},
                    "allowed_forward_lanes": ["safe_deterministic_decisions_shrink"],
                    "recommended_action": "apply_or_stage_safe_deterministic_shrink",
                    "history_path": "/tmp/history.json",
                    "status_path": "/tmp/backlog-status.json",
                    "markdown_path": "/tmp/backlog-status.md",
                },
            },
            stamp="unit",
            mode="decisions-apply",
            reindexed=True,
        )

        self.assertEqual(payload["mode"], "decisions-apply")
        self.assertTrue(payload["source_mutated"])
        self.assertEqual(payload["archive_path"], "/tmp/archive/decisions.before.md")
        self.assertEqual(payload["bytes_before"], 20000)
        self.assertEqual(payload["bytes_after"], 17000)
        self.assertEqual(payload["bytes_delta"], -3000)
        self.assertEqual(payload["validation_status"], "passed")
        self.assertEqual(payload["consolidation_group_count"], 2)
        self.assertEqual(payload["exact_duplicate_group_count"], 1)
        self.assertEqual(payload["shared_prefix_group_count"], 1)
        self.assertEqual(payload["decisions_backlog"]["status"], "review_required")
        self.assertEqual(payload["decisions_backlog"]["repeated_count"], 3)
        self.assertEqual(payload["decisions_backlog"]["recommended_action"], "apply_or_stage_safe_deterministic_shrink")
        self.assertTrue(payload["reindexed"])

    def test_do_decisions_plan_calls_engine_and_records_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "decisions-consolidation-input.json"
            plan_path = Path(tmp) / "decisions-consolidation-plan.md"
            patch_path = Path(tmp) / "decisions-consolidation.patch"
            summary_path = Path(tmp) / "decisions-consolidation-summary.json"
            for path in [input_path, plan_path, patch_path, summary_path]:
                path.write_text("{}\n", encoding="utf-8")
            original_run_json = wrapper.run_json
            try:
                captured: dict[str, object] = {}

                def fake_run_json(cmd, envelope, label):  # noqa: ANN001
                    captured["cmd"] = cmd
                    captured["label"] = label
                    return {
                        "source_path": "context/decisions.md",
                        "bytes_before": 14000,
                        "bytes_after_planned": 14000,
                        "bytes_delta_planned": 0,
                        "budget_deficit_after_consolidation": 0,
                        "consolidation_group_count": 0,
                        "exact_duplicate_group_count": 0,
                        "shared_prefix_group_count": 0,
                        "input_path": str(input_path),
                        "plan_path": str(plan_path),
                        "patch_path": str(patch_path),
                        "summary_path": str(summary_path),
                    }

                wrapper.run_json = fake_run_json
                envelope = FakeEnvelope(run_id="unit-decisions-plan")
                summary = wrapper.do_decisions_plan(SimpleNamespace(), "unit-stamp", envelope)
            finally:
                wrapper.run_json = original_run_json

            self.assertIn("decisions-plan", captured["cmd"])
            self.assertEqual(captured["label"], "decisions-consolidation-plan")
            self.assertIn("PRUNE_DECISIONS_PLAN_OK", summary)
            self.assertIn(str(input_path), envelope.artifact_paths)
            self.assertIn(str(plan_path), envelope.artifact_paths)
            self.assertIn(str(patch_path), envelope.artifact_paths)
            wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
            self.assertEqual(wrapper_summary["mode"], "decisions-plan")
            self.assertFalse(wrapper_summary["decisions_consolidation"]["source_mutated"])
            self.assertEqual(wrapper_summary["decisions_consolidation"]["validation_status"], "not_applicable")

    def test_run_decisions_apply_reindexes_and_audits_when_source_mutates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "decisions-consolidation-summary.json"
            input_path = Path(tmp) / "decisions-consolidation-input.json"
            plan_path = Path(tmp) / "decisions-consolidation-plan.md"
            patch_path = Path(tmp) / "decisions-consolidation.patch"
            apply_manifest_path = Path(tmp) / "decisions-consolidation-apply-manifest.json"
            archive_path = Path(tmp) / "decisions.before.md"
            summary_path.write_text(json.dumps({"input_path": str(input_path)}) + "\n", encoding="utf-8")
            for path in [input_path, plan_path, patch_path, apply_manifest_path, archive_path]:
                path.write_text("{}\n", encoding="utf-8")
            original_run_json = wrapper.run_json
            original_run_text = wrapper.run_text
            try:
                reindex_calls: list[dict] = []

                def fake_run_json(cmd, envelope, label):  # noqa: ANN001
                    self.assertEqual(label, "decisions-consolidation-apply")
                    self.assertIn("decisions-apply", cmd)
                    return {
                        "source_path": "context/decisions.md",
                        "source_mutated": True,
                        "archive_path": str(archive_path),
                        "validation_status": "passed",
                        "validation_failures": [],
                        "bytes_before": 20000,
                        "bytes_after_planned": 17000,
                        "bytes_delta_planned": -3000,
                        "budget_deficit_after_consolidation": 0,
                        "consolidation_group_count": 2,
                        "exact_duplicate_group_count": 1,
                        "shared_prefix_group_count": 1,
                        "plan_summary_path": str(summary_path),
                        "plan_path": str(plan_path),
                        "patch_path": str(patch_path),
                        "apply_manifest_path": str(apply_manifest_path),
                    }

                def fake_run_text(cmd, envelope, label):  # noqa: ANN001
                    reindex_calls.append({"cmd": cmd, "label": label})
                    return "indexed"

                wrapper.run_json = fake_run_json
                wrapper.run_text = fake_run_text
                envelope = FakeEnvelope(run_id="unit-decisions-apply")
                apply_run = wrapper.run_decisions_apply_and_post_audit(
                    SimpleNamespace(identity_mode="content-primary", min_shrink_bytes=1000),
                    "unit-stamp",
                    envelope,
                )
            finally:
                wrapper.run_json = original_run_json
                wrapper.run_text = original_run_text

            self.assertTrue(apply_run["source_mutated"])
            self.assertTrue(apply_run["reindexed"])
            self.assertEqual(reindex_calls[0]["label"], "memory-reindex")
            self.assertIn(str(input_path), envelope.artifact_paths)
            self.assertIn(str(apply_manifest_path), envelope.artifact_paths)
            self.assertEqual(envelope.retry_calls[0]["label"], "decisions-post-apply-audit")

    def test_pressure_check_noops_below_thresholds(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 2},
            self.below_threshold_pressure_dry_run_result(),
            {},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "noop")
        self.assertIn("budget_thresholds_not_met", evaluation["noop_reasons"])
        self.assertIn("work_thresholds_not_met", evaluation["noop_reasons"])
        self.assertNotIn("no_apply_ranges", evaluation["noop_reasons"])
        self.assertFalse(evaluation["conditions"]["budget_threshold_met"])
        self.assertFalse(evaluation["conditions"]["work_threshold_met"])

    def test_pressure_check_noops_during_cooldown(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {"last_successful_apply_at": wrapper.utc_now_iso(), "last_observed": {"hot_doc_hard_budget_exceeded": False}},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "noop")
        self.assertIn("cooldown_active", evaluation["noop_reasons"])
        self.assertTrue(evaluation["conditions"]["cooldown_active"])
        self.assertGreater(evaluation["conditions"]["cooldown_remaining_seconds"], 0)

    def test_pressure_check_noops_when_apply_lock_busy(self) -> None:
        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            apply_lock_acquired=False,
            apply_run=None,
        )

        self.assertEqual(apply_calls, [])
        self.assertIn("result=noop", summary)
        self.assertIn("no_op=apply_lock_busy", summary)
        self.assertEqual(state_writes[-1]["last_result"], "noop")
        self.assertEqual(state_writes[-1]["last_noop_reasons"], ["apply_lock_busy"])
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_trigger_result"], "noop")
        self.assertEqual(wrapper_summary["pressure_trigger"]["noop_reasons"], ["apply_lock_busy"])
        self.assertFalse(wrapper_summary["pressure_trigger"]["conditions"]["apply_lock_available"])

    def test_pressure_check_would_apply_in_dry_run_when_thresholds_pass(self) -> None:
        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=True),
            apply_run=None,
        )

        self.assertEqual(apply_calls, [])
        self.assertIn("PRUNE_PRESSURE_CHECK_DRY_RUN_OK result=would_apply", summary)
        self.assertEqual(state_writes[-1]["last_result"], "would_apply")
        self.assertEqual(state_writes[-1]["last_objective_result"], "audit_only_pressure_detected")
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_trigger_result"], "would_apply")
        self.assertEqual(wrapper_summary["pressure_objective_result"], "audit_only_pressure_detected")
        self.assertEqual(wrapper_summary["pressure_trigger_state"]["last_result"], "would_apply")
        self.assertNotIn("apply", wrapper_summary)

    def test_pressure_check_calls_same_apply_payload_when_thresholds_pass(self) -> None:
        apply_run = self.fake_pressure_apply_run()
        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            apply_run=apply_run,
        )

        self.assertEqual(len(apply_calls), 1)
        self.assertEqual(apply_calls[0]["stamp"], "unit-pressure")
        self.assertEqual(apply_calls[0]["kwargs"]["apply_label"], "pressure-context-apply")
        self.assertEqual(apply_calls[0]["kwargs"]["audit_label"], "pressure-post-apply-audit")
        self.assertIn("PRUNE_PRESSURE_CHECK_OK result=applied_budget_met", summary)
        self.assertEqual(state_writes[-1]["last_result"], "applied_budget_met")
        self.assertEqual(state_writes[-1]["last_successful_apply_run"], "pressure-check-run")
        self.assertEqual(state_writes[-1]["last_objective_result"], "applied_budget_met")
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_trigger_result"], "applied_budget_met")
        self.assertEqual(wrapper_summary["pressure_objective_result"], "applied_budget_met")
        self.assertEqual(wrapper_summary["apply"]["mode"], "apply")
        self.assertEqual(wrapper_summary["apply"]["removed_blocks"], 1)
        self.assertTrue(wrapper_summary["apply"]["reindexed"])
        self.assertEqual(wrapper_summary["post_apply_audit"]["prune_candidate"], 4)

    def test_pressure_check_compacts_state_again_when_post_apply_audit_expands_it(self) -> None:
        apply_run = self.fake_pressure_apply_run()
        apply_run["audit_result"]["budget_summary"]["state_files"] = {
            "context/state/context-pruning-state.json": {
                "bytes": 900000,
                "target_bytes": 250000,
                "hard_bytes": 500000,
                "pressure_level": "hard",
            }
        }
        state_compaction_result = {
            "identityMode": "content-primary",
            "entries_before": 120,
            "entries_after": 120,
            "entries_retained_current": 20,
            "entries_retained_history": 100,
            "entries_archived": 0,
            "entries_dropped": 0,
            "fingerprints_before": 40,
            "fingerprints_after": 0,
            "state_bytes_before": 900000,
            "state_bytes_after_planned": 240000,
            "state_bytes_delta_planned": -660000,
            "state_hard_budget_bytes": 500000,
            "state_budget_met": True,
            "state_budget_status": "state_budget_met",
            "state_bytes_over_hard": 0,
            "archived_history_shards": [],
            "archived_history_shard_count": 0,
            "dropped_reason_counts": {},
            "state_path": "/tmp/state.json",
            "preview_path": "/tmp/preview.json",
            "manifest_path": "/tmp/manifest.json",
            "archived_state_path": "/tmp/state.before.json",
        }

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            apply_run=apply_run,
            state_compaction_result=state_compaction_result,
        )

        self.assertEqual(len(apply_calls), 1)
        self.assertIn("PRUNE_PRESSURE_CHECK_OK result=applied_budget_met", summary)
        self.assertEqual(state_writes[-1]["last_result"], "applied_budget_met")
        self.assertIn("pressure-post-apply-state-compaction-manifest.json", envelope.artifacts)
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_objective_result"], "applied_budget_met")
        self.assertEqual(wrapper_summary["post_apply_state_compaction"]["stamp"], "unit-pressure-post-apply-audit")
        self.assertEqual(wrapper_summary["post_apply_state_compaction"]["state_bytes_after_planned"], 240000)
        self.assertTrue(wrapper_summary["post_apply_state_compaction"]["state_budget_met"])

    def test_pressure_check_reports_partial_when_primary_hard_budget_remains(self) -> None:
        dry_run_result = self.pressure_dry_run_result()
        dry_run_result["budget_summary"]["hot_docs"]["context/active.md"].update(
            {"bytes": 33000, "target_bytes": 25000, "hard_bytes": 30000, "pressure_level": "hard"}
        )
        apply_run = self.fake_pressure_apply_run(post_budget_summary=self.active_hard_budget_summary())

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            dry_run_result=dry_run_result,
            audit_result={"items": 8, "review": 1, "prune_candidate": 13, "budget_summary": dry_run_result["budget_summary"]},
            apply_run=apply_run,
        )

        self.assertEqual(len(apply_calls), 1)
        self.assertIn("result=applied_partial_budget_unmet", summary)
        self.assertIn("remaining_hard_budget_paths=context/active.md", summary)
        self.assertEqual(state_writes[-1]["last_result"], "applied_partial_budget_unmet")
        self.assertIsNone(state_writes[-1]["last_successful_apply_run"])
        self.assertEqual(state_writes[-1]["unresolved_pressure_recurrence"], {"context/active.md": 1})
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        objective = wrapper_summary["pressure_objective"]
        self.assertEqual(objective["result"], "applied_partial_budget_unmet")
        self.assertFalse(objective["hard_budget_met"])
        self.assertTrue(objective["primary_target_unresolved"])
        self.assertEqual(objective["remaining_hard_budget_paths"], ["context/active.md"])
        self.assertEqual(objective["changed_paths"], ["context/projects/quant-pipeline.md"])

    def test_pressure_check_reports_degraded_when_no_safe_apply_and_pressure_remains(self) -> None:
        dry_run_result = self.pressure_dry_run_result()
        dry_run_result["budget_summary"]["hot_docs"]["context/active.md"].update(
            {"bytes": 33000, "target_bytes": 25000, "hard_bytes": 30000, "pressure_level": "hard"}
        )
        apply_run = self.fake_pressure_apply_run(
            post_budget_summary=self.active_hard_budget_summary(),
            files=[],
            bytes_delta=0,
            reindexed=False,
        )

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            dry_run_result=dry_run_result,
            audit_result={"items": 8, "review": 1, "prune_candidate": 13, "budget_summary": dry_run_result["budget_summary"]},
            pressure_state={"unresolved_pressure_recurrence": {"context/active.md": 2}},
            apply_run=apply_run,
        )

        self.assertEqual(len(apply_calls), 1)
        self.assertIn("result=degraded_no_safe_apply", summary)
        self.assertIn("remaining_hard_budget_paths=context/active.md", summary)
        self.assertEqual(state_writes[-1]["last_result"], "degraded_no_safe_apply")
        self.assertIsNone(state_writes[-1]["last_successful_apply_run"])
        self.assertEqual(state_writes[-1]["unresolved_pressure_recurrence"], {"context/active.md": 3})
        self.assertEqual(state_writes[-1]["max_unresolved_pressure_recurrence"], 3)
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        objective = wrapper_summary["pressure_objective"]
        self.assertEqual(objective["result"], "degraded_no_safe_apply")
        self.assertFalse(objective["changed_any_file"])
        self.assertTrue(objective["primary_target_unresolved"])

    def test_pressure_state_records_last_result(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {},
            lock_busy=False,
        )
        payload = wrapper.build_pressure_trigger_state_payload(
            {},
            result="noop",
            evaluation={**evaluation, "noop_reasons": ["apply_lock_busy"]},
            envelope=FakeEnvelope(run_id="state-run"),
            updated_at="2026-05-27T06:00:00Z",
        )

        self.assertEqual(payload["last_result"], "noop")
        self.assertEqual(payload["last_noop_reasons"], ["apply_lock_busy"])
        self.assertEqual(payload["last_pressure_check_run"], "state-run")
        self.assertEqual(payload["last_thresholds"], evaluation["thresholds"])
        self.assertEqual(payload["last_observed"], evaluation["observed"])

    def test_pressure_check_triggers_when_hot_doc_hard_budget_exceeded(self) -> None:
        dry_run_result = self.pressure_dry_run_result()
        dry_run_result["budget_summary"]["hot_docs"]["context/projects/quant-pipeline.md"].update(
            {"bytes": 90000, "pressure_level": "hard"}
        )
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            dry_run_result,
            {},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "eligible")
        self.assertTrue(evaluation["conditions"]["hard_budget_threshold_met"])
        self.assertTrue(evaluation["conditions"]["budget_threshold_met"])
        self.assertTrue(evaluation["observed"]["hot_doc_hard_budget_exceeded"])
        self.assertEqual(evaluation["observed"]["hard_budget_records"][0]["path"], "context/projects/quant-pipeline.md")

    def test_pressure_check_reports_budget_deficit_when_apply_cannot_reach_target(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.budget_deficit_pressure_dry_run_result(),
            {},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "eligible")
        self.assertTrue(evaluation["conditions"]["projected_post_apply_over_target"])
        self.assertTrue(evaluation["observed"]["projected_post_apply_over_target"])
        self.assertEqual(evaluation["observed"]["projected_budget_deficits"][0]["path"], "context/projects/quant-pipeline.md")
        self.assertEqual(evaluation["observed"]["projected_budget_deficits"][0]["projected_bytes_over_target"], 12000)
        self.assertEqual(
            evaluation["observed"]["project_spine_budget_pressure"]["project_spine_budget_deficit_after_planning"],
            12000,
        )

    def test_pressure_check_triggers_when_state_json_hard_budget_exceeded(self) -> None:
        dry_run_result = self.pressure_dry_run_result()
        dry_run_result["budget_summary"]["hot_docs"]["context/projects/quant-pipeline.md"].update(
            {"bytes": 90000, "target_bytes": 100000, "hard_bytes": 125000, "pressure_level": "none"}
        )
        dry_run_result["budget_summary"]["state_files"] = {
            "context/state/context-pruning-state.json": {
                "bytes": 500000,
                "target_bytes": 250000,
                "hard_bytes": 400000,
                "pressure_level": "hard",
            }
        }

        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            dry_run_result,
            {},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "eligible")
        self.assertTrue(evaluation["conditions"]["state_json_hard_budget_threshold_met"])
        self.assertTrue(evaluation["conditions"]["budget_threshold_met"])
        self.assertTrue(evaluation["observed"]["state_json_hard_budget_exceeded"])
        self.assertEqual(evaluation["observed"]["state_json_hard_budget_records"][0]["path"], "context/state/context-pruning-state.json")

    def test_pressure_trigger_evaluates_thresholds_as_eligible(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "eligible")
        self.assertEqual(evaluation["noop_reasons"], [])
        self.assertTrue(evaluation["conditions"]["hard_budget_threshold_met"])
        self.assertTrue(evaluation["conditions"]["prune_candidate_threshold_met"])
        self.assertTrue(evaluation["conditions"]["planned_byte_savings_threshold_met"])
        self.assertTrue(evaluation["conditions"]["apply_lock_available"])
        self.assertEqual(evaluation["observed"]["planned_byte_savings"], 8000)

    def test_pressure_trigger_noops_during_cooldown(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {"last_successful_apply_at": wrapper.utc_now_iso(), "last_observed": {"hot_doc_hard_budget_exceeded": False}},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "noop")
        self.assertIn("cooldown_active", evaluation["noop_reasons"])
        self.assertTrue(evaluation["conditions"]["cooldown_active"])
        self.assertGreater(evaluation["conditions"]["cooldown_remaining_seconds"], 0)

    def test_pressure_state_payload_records_last_result(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {},
            lock_busy=False,
        )
        payload = wrapper.build_pressure_trigger_state_payload(
            {"last_successful_apply_at": "2026-05-26T01:00:00Z", "last_successful_apply_run": "previous-run"},
            result="would_apply",
            evaluation=evaluation,
            envelope=FakeEnvelope(run_id="pressure-run"),
            updated_at="2026-05-27T02:00:00Z",
        )

        self.assertEqual(payload["schema_version"], wrapper.PRESSURE_TRIGGER_STATE_SCHEMA)
        self.assertEqual(payload["updated_at"], "2026-05-27T02:00:00Z")
        self.assertEqual(payload["last_pressure_check_at"], "2026-05-27T02:00:00Z")
        self.assertEqual(payload["last_pressure_check_run"], "pressure-run")
        self.assertEqual(payload["last_result"], "would_apply")
        self.assertEqual(payload["last_noop_reasons"], [])
        self.assertEqual(payload["last_successful_apply_at"], "2026-05-26T01:00:00Z")
        self.assertEqual(payload["last_successful_apply_run"], "previous-run")
        self.assertEqual(payload["last_thresholds"]["quant_byte_threshold"], 100000)
        self.assertEqual(payload["last_observed"]["planned_byte_savings"], 8000)

    def test_pressure_state_payload_updates_successful_apply(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {},
            lock_busy=False,
        )
        payload = wrapper.build_pressure_trigger_state_payload(
            {"last_successful_apply_at": "2026-05-26T01:00:00Z", "last_successful_apply_run": "previous-run"},
            result="applied",
            evaluation=evaluation,
            envelope=FakeEnvelope(run_id="applied-run"),
            updated_at="2026-05-27T03:00:00Z",
        )

        self.assertEqual(payload["last_result"], "applied")
        self.assertEqual(payload["last_successful_apply_at"], "2026-05-27T03:00:00Z")
        self.assertEqual(payload["last_successful_apply_run"], "applied-run")
        self.assertEqual(payload["last_noop_reasons"], [])

    def test_write_pressure_state_writes_json_and_tracks_artifact(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {},
            lock_busy=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "context-prune-pressure-trigger-state.json"
            original_state_path = wrapper.PRESSURE_TRIGGER_STATE
            try:
                wrapper.PRESSURE_TRIGGER_STATE = state_path
                envelope = FakeEnvelope(run_id="write-run")
                payload = wrapper.write_pressure_trigger_state({}, result="would_apply", evaluation=evaluation, envelope=envelope)
            finally:
                wrapper.PRESSURE_TRIGGER_STATE = original_state_path

            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored, payload)
            self.assertEqual(stored["schema_version"], wrapper.PRESSURE_TRIGGER_STATE_SCHEMA)
            self.assertEqual(stored["last_result"], "would_apply")
            self.assertEqual(stored["last_pressure_check_run"], "write-run")
            self.assertIn(str(state_path), envelope.artifact_paths)

    def test_pressure_summary_payload_includes_written_state(self) -> None:
        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 13},
            self.pressure_dry_run_result(),
            {},
            lock_busy=False,
        )
        state_payload = wrapper.build_pressure_trigger_state_payload(
            {},
            result="would_apply",
            evaluation=evaluation,
            envelope=FakeEnvelope(run_id="summary-run"),
            updated_at="2026-05-27T04:00:00Z",
        )
        payload = wrapper.pressure_summary_payload(
            summary="summary",
            result="would_apply",
            telemetry_summary={},
            audit_result={"items": 1, "review": 0, "prune_candidate": 1},
            dry_run_result=self.pressure_dry_run_result(),
            evaluation=evaluation,
            stamp="unit-pressure",
            state_payload=state_payload,
        )

        self.assertTrue(payload["pressure_trigger_state"]["written"])
        self.assertEqual(payload["pressure_trigger_state"]["last_result"], "would_apply")
        self.assertEqual(payload["pressure_trigger_state"]["state"], state_payload)

    def test_pressure_check_summary_line_reports_observed_values(self) -> None:
        summary = wrapper.format_pressure_check_summary(
            dry_run=True,
            result="would_apply",
            noop_reasons=[],
            observed={"apply_range_count": 3, "planned_byte_savings": 8000, "quant_bytes": 130000, "active_bytes": 12000},
            stamp="unit-pressure",
        )

        self.assertEqual(
            summary,
            "PRUNE_PRESSURE_CHECK_DRY_RUN_OK result=would_apply identity=content-primary no_op=none "
            "ranges=3 savings=8000 quant_bytes=130000 active_bytes=12000 "
            "remaining_hard_budget_paths=none "
            "decisions_autonomous_consolidation_required=false reindexed=0 stamp=unit-pressure",
        )

    def test_pressure_check_summary_line_reports_decisions_consolidation_required(self) -> None:
        summary = wrapper.format_pressure_check_summary(
            dry_run=True,
            result="would_apply",
            noop_reasons=[],
            observed={
                "apply_range_count": 0,
                "planned_byte_savings": 0,
                "quant_bytes": 90000,
                "active_bytes": 12000,
                "decisions_autonomous_consolidation_required": True,
            },
            stamp="unit-pressure",
        )

        self.assertIn("decisions_autonomous_consolidation_required=true", summary)

    def test_pressure_observed_extracts_decisions_consolidation_required(self) -> None:
        dry_run = self.pressure_dry_run_result()
        dry_run["budget_summary"]["decisions_autonomous_consolidation_required"] = True

        observed = wrapper.pressure_observed_from_results({}, dry_run)

        self.assertTrue(observed["decisions_autonomous_consolidation_required"])

    def test_pressure_trigger_allows_decisions_consolidation_without_generic_ranges(self) -> None:
        dry_run = self.below_threshold_pressure_dry_run_result()
        dry_run["budget_summary"]["decisions_autonomous_consolidation_required"] = True
        dry_run["candidate_summary"] = {"candidate_count_total": 0, "range_count_total": 0}
        dry_run["range_records"] = []
        dry_run["source_bytes_delta_planned_total"] = 0

        evaluation = wrapper.evaluate_pressure_trigger(
            self.pressure_args(),
            {"prune_candidate": 0},
            dry_run,
            {},
            lock_busy=False,
        )

        self.assertEqual(evaluation["pressure_trigger_result"], "eligible")
        self.assertEqual(evaluation["noop_reasons"], [])
        self.assertTrue(evaluation["conditions"]["decisions_consolidation_required"])
        self.assertTrue(evaluation["conditions"]["budget_threshold_met"])
        self.assertTrue(evaluation["conditions"]["work_threshold_met"])
        self.assertFalse(evaluation["conditions"]["apply_ranges_present"])
        self.assertTrue(evaluation["conditions"]["decisions_apply_present"])

    def test_pressure_check_runs_decisions_apply_when_decisions_hard_budget_exceeded(self) -> None:
        dry_run = self.below_threshold_pressure_dry_run_result()
        dry_run["budget_summary"]["decisions_autonomous_consolidation_required"] = True
        dry_run["candidate_summary"] = {"candidate_count_total": 0, "range_count_total": 0}
        dry_run["range_records"] = []
        dry_run["source_bytes_delta_planned_total"] = 0
        decisions_calls: list[dict] = []

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            dry_run_result=dry_run,
            audit_result={"items": 8, "review": 1, "prune_candidate": 0, "budget_summary": dry_run["budget_summary"]},
            decisions_run=self.fake_decisions_apply_run(),
            decisions_calls=decisions_calls,
            apply_run=None,
        )

        self.assertEqual(apply_calls, [])
        self.assertEqual(len(decisions_calls), 1)
        self.assertEqual(decisions_calls[0]["stamp"], "unit-pressure")
        self.assertEqual(decisions_calls[0]["kwargs"]["apply_label"], "pressure-decisions-apply")
        self.assertEqual(decisions_calls[0]["kwargs"]["audit_label"], "pressure-decisions-post-apply-audit")
        self.assertIn("PRUNE_PRESSURE_CHECK_OK result=applied_budget_met", summary)
        self.assertIn("decisions_autonomous_consolidation_required=true", summary)
        self.assertIn("reindexed=1", summary)
        self.assertEqual(state_writes[-1]["last_result"], "applied_budget_met")
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_trigger_result"], "applied_budget_met")
        self.assertEqual(wrapper_summary["decisions_consolidation"]["validation_status"], "passed")
        self.assertTrue(wrapper_summary["decisions_consolidation"]["source_mutated"])
        self.assertTrue(wrapper_summary["decisions_consolidation"]["reindexed"])
        self.assertEqual(wrapper_summary["post_decisions_audit"]["prune_candidate"], 3)

    def test_pressure_check_surfaces_repeated_decisions_noop_backlog(self) -> None:
        dry_run = self.below_threshold_pressure_dry_run_result()
        dry_run["budget_summary"]["decisions_autonomous_consolidation_required"] = True
        dry_run["candidate_summary"] = {"candidate_count_total": 0, "range_count_total": 0}
        dry_run["range_records"] = []
        dry_run["source_bytes_delta_planned_total"] = 0
        decisions_calls: list[dict] = []

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            dry_run_result=dry_run,
            audit_result={"items": 8, "review": 1, "prune_candidate": 0, "budget_summary": dry_run["budget_summary"]},
            pressure_state={"unresolved_pressure_recurrence": {"context/decisions.md": 2}},
            decisions_run=self.fake_decisions_noop_run(),
            decisions_calls=decisions_calls,
            apply_run=None,
        )

        self.assertEqual(apply_calls, [])
        self.assertEqual(len(decisions_calls), 1)
        self.assertIn("PRUNE_PRESSURE_CHECK_OK result=degraded_no_safe_apply", summary)
        self.assertIn("remaining_hard_budget_paths=context/decisions.md", summary)
        self.assertIn("decisions_backlog_status=review_required", summary)
        self.assertIn("decisions_backlog_repeated=3", summary)
        self.assertIn("decisions_backlog_action=manual_decisions_consolidation_review", summary)
        self.assertEqual(state_writes[-1]["last_result"], "degraded_no_safe_apply")
        self.assertEqual(state_writes[-1]["unresolved_pressure_recurrence"], {"context/decisions.md": 3})
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_objective_result"], "degraded_no_safe_apply")
        objective = wrapper_summary["pressure_objective"]
        self.assertEqual(objective["remaining_decisions_hard_budget_paths"], ["context/decisions.md"])
        self.assertEqual(objective["skipped_reasons"]["decisions_no_op_reason"], "insufficient_safe_decisions_shrink")
        self.assertEqual(objective["skipped_reasons"]["decisions_backlog"]["status"], "review_required")
        backlog = wrapper_summary["decisions_consolidation"]["decisions_backlog"]
        self.assertEqual(backlog["status"], "review_required")
        self.assertEqual(backlog["repeated_count"], 3)
        self.assertEqual(backlog["recommended_action"], "manual_decisions_consolidation_review")

    def test_apply_lock_acquires_writes_payload_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "workbench-context-prune-apply.lock"
            envelope = FakeEnvelope(run_id="unit-lock-run")

            with wrapper.ApplyLock(envelope=envelope, mode="weekly-apply", path=lock_path) as lock:
                self.assertTrue(lock.acquired)
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["run_id"], "unit-lock-run")
                self.assertEqual(payload["mode"], "weekly-apply")
                self.assertIn("pid", payload)
                self.assertIn("acquired_at", payload)

            self.assertFalse(lock_path.exists())

    def test_apply_lock_busy_preserves_fresh_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "workbench-context-prune-apply.lock"
            existing = {
                "pid": os.getpid(),
                "run_id": "other-run",
                "mode": "weekly-apply",
                "acquired_at": wrapper.utc_now_iso(),
            }
            lock_path.write_text(json.dumps(existing), encoding="utf-8")
            envelope = FakeEnvelope(run_id="unit-lock-run")

            with wrapper.ApplyLock(envelope=envelope, mode="weekly-apply", path=lock_path) as lock:
                self.assertFalse(lock.acquired)

            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["run_id"], "other-run")
            self.assertEqual(envelope.warnings, [])

    def test_apply_lock_replaces_stale_lock_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "workbench-context-prune-apply.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "pid": 999999,
                        "run_id": "stale-run",
                        "mode": "weekly-apply",
                        "acquired_at": "2000-01-01T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            envelope = FakeEnvelope(run_id="replacement-run")

            with wrapper.ApplyLock(envelope=envelope, mode="weekly-apply", path=lock_path) as lock:
                self.assertTrue(lock.acquired)
                self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["run_id"], "replacement-run")

            self.assertFalse(lock_path.exists())
            self.assertEqual(len(envelope.warnings), 1)
            self.assertIn("stale apply lock archived before replacement", envelope.warnings[0])
            self.assertIn("stale-run", envelope.warnings[0])

    def test_apply_lock_replaces_dead_pid_lock_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "workbench-context-prune-apply.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "pid": 999999,
                        "run_id": "dead-pid-run",
                        "mode": "weekly-apply",
                        "acquired_at": wrapper.utc_now_iso(),
                    }
                ),
                encoding="utf-8",
            )
            envelope = FakeEnvelope(run_id="replacement-run")

            with wrapper.ApplyLock(envelope=envelope, mode="weekly-apply", path=lock_path) as lock:
                self.assertTrue(lock.acquired)
                self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["run_id"], "replacement-run")

            self.assertFalse(lock_path.exists())
            self.assertEqual(len(envelope.warnings), 1)
            self.assertIn("stale apply lock archived before replacement", envelope.warnings[0])
            self.assertIn("dead-pid-run", envelope.warnings[0])

    def test_existing_apply_lock_busy_ignores_dead_pid_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "workbench-context-prune-apply.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "pid": 999999,
                        "run_id": "dead-pid-run",
                        "mode": "pressure-check",
                        "acquired_at": wrapper.utc_now_iso(),
                    }
                ),
                encoding="utf-8",
            )

            self.assertFalse(wrapper.existing_apply_lock_busy(lock_path))

    def test_weekly_apply_noops_when_apply_lock_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "workbench-context-prune-apply.lock"
            lock_path.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "run_id": "other-run",
                        "mode": "weekly-apply",
                        "acquired_at": wrapper.utc_now_iso(),
                    }
                ),
                encoding="utf-8",
            )
            original_lock_path = wrapper.APPLY_LOCK_PATH
            original_do_weekly_apply = wrapper.do_weekly_apply
            try:
                wrapper.APPLY_LOCK_PATH = lock_path
                called = False

                def fail_if_called(args, stamp, envelope):  # noqa: ANN001
                    nonlocal called
                    called = True
                    raise AssertionError("do_weekly_apply should not run when apply lock is busy")

                wrapper.do_weekly_apply = fail_if_called
                envelope = FakeEnvelope(run_id="unit-lock-run")
                args = SimpleNamespace(dry_run=False, local_compress=True, local_compress_priority=True)

                summary = wrapper.run_weekly_apply_with_lock(args, "unit-stamp", envelope)
            finally:
                wrapper.APPLY_LOCK_PATH = original_lock_path
                wrapper.do_weekly_apply = original_do_weekly_apply

            self.assertFalse(called)
            self.assertIn("no_op=apply_lock_busy", summary)
            wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
            self.assertEqual(wrapper_summary["status"], "ok")
            self.assertEqual(wrapper_summary["no_op_reason"], "apply_lock_busy")
            self.assertFalse(wrapper_summary["apply_lock"]["acquired"])
            self.assertEqual(wrapper_summary["apply"]["no_op_reason"], "apply_lock_busy")
            self.assertEqual(wrapper_summary["apply"]["removed_blocks"], 0)

    def test_state_compaction_payload_and_summary(self) -> None:
        result = {
            "identityMode": "content-primary",
            "entries_before": 100,
            "entries_after": 40,
            "entries_retained_current": 10,
            "entries_retained_history": 30,
            "entries_archived": 60,
            "entries_dropped": 60,
            "fingerprints_before": 80,
            "fingerprints_after": 35,
            "state_bytes_before": 500000,
            "state_bytes_after_planned": 120000,
            "state_bytes_delta_planned": -380000,
            "state_hard_budget_bytes": 400000,
            "state_budget_met": True,
            "state_budget_status": "state_budget_met",
            "state_bytes_over_hard": 0,
            "archived_history_shards": [{"path": "/tmp/shard.jsonl", "entry_count": 60, "bytes": 1234}],
            "archived_history_shard_count": 1,
            "dropped_reason_counts": {"expired_orphan": 60},
            "state_path": "/tmp/state.json",
            "preview_path": "/tmp/preview.json",
            "manifest_path": "/tmp/manifest.json",
            "archived_state_path": None,
        }

        payload = wrapper.state_compaction_payload(result, stamp="unit", dry_run=True, telemetry_summary={"entry_count": 7})
        summary = wrapper.format_state_compaction_summary(dry_run=True, result=result, stamp="unit", telemetry_entries=7)

        self.assertEqual(payload["entries_before"], 100)
        self.assertEqual(payload["entries_after"], 40)
        self.assertEqual(payload["entries_retained_current"], 10)
        self.assertEqual(payload["entries_retained_history"], 30)
        self.assertEqual(payload["entries_archived"], 60)
        self.assertEqual(payload["entries_dropped"], 60)
        self.assertEqual(payload["fingerprints_after"], 35)
        self.assertTrue(payload["state_budget_met"])
        self.assertEqual(payload["state_budget_status"], "state_budget_met")
        self.assertEqual(payload["archived_history_shard_count"], 1)
        self.assertEqual(payload["dropped_reason_counts"], {"expired_orphan": 60})
        self.assertEqual(payload["telemetry"]["entry_count"], 7)
        self.assertEqual(
            summary,
            "PRUNE_STATE_COMPACT_DRY_RUN_OK identity=content-primary entries_before=100 entries_after=40 "
            "retained_current=10 retained_history=30 archived=60 dropped=60 budget=state_budget_met "
            "bytes_after=120000 bytes_over_hard=0 bytes_delta=-380000 telemetry=7 stamp=unit",
        )

    def test_wrapper_compact_state_dry_run_does_not_mutate_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            state_root.mkdir(parents=True)
            state_path = state_root / "context-pruning-state.json"
            telemetry_path = state_root / "context-usage-telemetry.json"
            preview_path = state_root / "context-pruning-state-compaction-preview.json"
            original_state_text = '{"items": {}}\n'
            original_telemetry_text = '{"entries": {}}\n'
            state_path.write_text(original_state_text, encoding="utf-8")
            telemetry_path.write_text(original_telemetry_text, encoding="utf-8")
            preview_path.write_text("{}\n", encoding="utf-8")
            original_state_root = wrapper.WORKBENCH_STATE_ROOT
            original_telemetry_json = wrapper.TELEMETRY_JSON
            original_preview = wrapper.STATE_COMPACTION_PREVIEW
            original_run_json = wrapper.run_json
            try:
                wrapper.WORKBENCH_STATE_ROOT = state_root
                wrapper.TELEMETRY_JSON = telemetry_path
                wrapper.STATE_COMPACTION_PREVIEW = preview_path
                captured: dict[str, object] = {}

                def fake_run_json(cmd, envelope, label):  # noqa: ANN001
                    captured["cmd"] = cmd
                    captured["label"] = label
                    return {
                        "identityMode": "content-primary",
                        "entries_before": 2,
                        "entries_after": 1,
                        "entries_retained_current": 1,
                        "entries_retained_history": 0,
                        "entries_archived": 1,
                        "entries_dropped": 1,
                        "fingerprints_before": 2,
                        "fingerprints_after": 1,
                        "state_bytes_before": 2000,
                        "state_bytes_after_planned": 1200,
                        "state_bytes_delta_planned": -800,
                        "state_hard_budget_bytes": 500000,
                        "state_budget_met": True,
                        "state_budget_status": "state_budget_met",
                        "state_bytes_over_hard": 0,
                        "archived_history_shards": [],
                        "archived_history_shard_count": 0,
                        "dropped_reason_counts": {"expired_orphan": 1},
                        "state_path": str(state_path),
                        "preview_path": str(preview_path),
                        "manifest_path": str(state_root / "context-pruning-state.compaction-manifest.json"),
                        "archived_state_path": None,
                    }

                wrapper.run_json = fake_run_json
                envelope = FakeEnvelope(run_id="unit-compact-run")
                args = SimpleNamespace(dry_run=True, apply=False, identity_mode="content-primary")

                summary = wrapper.do_compact_state(args, "unit-stamp", envelope)
            finally:
                wrapper.WORKBENCH_STATE_ROOT = original_state_root
                wrapper.TELEMETRY_JSON = original_telemetry_json
                wrapper.STATE_COMPACTION_PREVIEW = original_preview
                wrapper.run_json = original_run_json

            self.assertIn("PRUNE_STATE_COMPACT_DRY_RUN_OK", summary)
            self.assertIn("compact-state", captured["cmd"])
            self.assertIn("--dry-run", captured["cmd"])
            self.assertEqual(captured["label"], "context-state-compaction")
            self.assertIn(str(preview_path), envelope.artifact_paths)
            self.assertIn("context-pruning-state.before-compaction.json", envelope.artifacts)
            self.assertIn("context-usage-telemetry.before-compaction.json", envelope.artifacts)
            self.assertEqual(state_path.read_text(encoding="utf-8"), original_state_text)
            self.assertEqual(telemetry_path.read_text(encoding="utf-8"), original_telemetry_text)
            wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
            self.assertEqual(wrapper_summary["mode"], "compact-state")
            self.assertEqual(wrapper_summary["status"], "ok")
            self.assertTrue(wrapper_summary["state_compaction"]["dry_run"])
            self.assertEqual(wrapper_summary["state_compaction"]["entries_dropped"], 1)
            self.assertTrue(wrapper_summary["state_compaction"]["state_budget_met"])

    def test_pressure_check_runs_state_compaction_when_state_hard_budget_exceeded(self) -> None:
        dry_run_result = self.pressure_dry_run_result()
        dry_run_result["budget_summary"]["state_files"] = {
            "context/state/context-pruning-state.json": {
                "bytes": 500000,
                "target_bytes": 250000,
                "hard_bytes": 400000,
                "pressure_level": "hard",
            }
        }
        state_compaction_result = {
            "identityMode": "content-primary",
            "entries_before": 100,
            "entries_after": 40,
            "entries_retained_current": 10,
            "entries_retained_history": 30,
            "entries_archived": 60,
            "entries_dropped": 60,
            "fingerprints_before": 80,
            "fingerprints_after": 35,
            "state_bytes_before": 500000,
            "state_bytes_after_planned": 120000,
            "state_bytes_delta_planned": -380000,
            "state_hard_budget_bytes": 400000,
            "state_budget_met": True,
            "state_budget_status": "state_budget_met",
            "state_bytes_over_hard": 0,
            "archived_history_shards": [],
            "archived_history_shard_count": 0,
            "dropped_reason_counts": {"expired_orphan": 60},
            "state_path": "/tmp/state.json",
            "preview_path": "/tmp/preview.json",
            "manifest_path": "/tmp/manifest.json",
            "archived_state_path": None,
        }

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=True),
            dry_run_result=dry_run_result,
            state_compaction_result=state_compaction_result,
            apply_run=None,
        )

        self.assertEqual(apply_calls, [])
        self.assertIn("result=would_apply", summary)
        self.assertEqual(state_writes[-1]["last_result"], "would_apply")
        self.assertIn("pressure-state-compaction-manifest.json", envelope.artifacts)
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["state_compaction"]["entries_dropped"], 60)
        self.assertTrue(wrapper_summary["state_compaction"]["dry_run"])
        self.assertTrue(wrapper_summary["state_compaction"]["state_budget_met"])

    def test_pressure_check_reports_degraded_when_state_compaction_budget_unmet(self) -> None:
        dry_run_result = self.below_threshold_pressure_dry_run_result()
        dry_run_result["candidate_summary"] = {"candidate_count_total": 0, "range_count_total": 0}
        dry_run_result["range_records"] = []
        dry_run_result["source_bytes_delta_planned_total"] = 0
        dry_run_result["budget_summary"]["state_files"] = {
            "context/state/context-pruning-state.json": {
                "bytes": 900000,
                "target_bytes": 250000,
                "hard_bytes": 500000,
                "pressure_level": "hard",
            }
        }
        state_compaction_result = {
            "identityMode": "content-primary",
            "entries_before": 500,
            "entries_after": 120,
            "entries_retained_current": 120,
            "entries_retained_history": 0,
            "entries_archived": 380,
            "entries_dropped": 380,
            "fingerprints_before": 300,
            "fingerprints_after": 0,
            "state_bytes_before": 900000,
            "state_bytes_after_planned": 530000,
            "state_bytes_delta_planned": -370000,
            "state_hard_budget_bytes": 500000,
            "state_budget_met": False,
            "state_budget_status": "degraded_state_budget_unmet",
            "state_bytes_over_hard": 30000,
            "archived_history_shards": [{"path": "/tmp/shard.jsonl", "entry_count": 380, "bytes": 12000}],
            "archived_history_shard_count": 1,
            "dropped_reason_counts": {"expired_orphan": 380},
            "state_path": "/tmp/state.json",
            "preview_path": "/tmp/preview.json",
            "manifest_path": "/tmp/manifest.json",
            "archived_state_path": "/tmp/state.before.json",
        }

        summary, envelope, state_writes, apply_calls = self.run_pressure_check_with_fakes(
            args=self.pressure_args(dry_run=False),
            dry_run_result=dry_run_result,
            state_compaction_result=state_compaction_result,
            apply_run=None,
        )

        self.assertEqual(apply_calls, [])
        self.assertIn("result=degraded_state_budget_unmet", summary)
        self.assertIn("remaining_hard_budget_paths=context/state/context-pruning-state.json", summary)
        self.assertEqual(state_writes[-1]["last_result"], "degraded_state_budget_unmet")
        self.assertEqual(state_writes[-1]["last_objective_result"], "degraded_state_budget_unmet")
        wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
        self.assertEqual(wrapper_summary["pressure_objective_result"], "degraded_state_budget_unmet")
        self.assertFalse(wrapper_summary["state_compaction"]["state_budget_met"])
        self.assertEqual(wrapper_summary["state_compaction"]["state_bytes_over_hard"], 30000)

    def test_state_rebase_payload_and_summary(self) -> None:
        result = {
            "old_version": 2,
            "new_version": 3,
            "identityMode": "content-primary",
            "current_item_count": 4,
            "previous_entry_count": 3,
            "rebased_entry_count": 5,
            "entries_preserved_by_exact_key": 1,
            "entries_preserved_by_fingerprint": 1,
            "entries_preserved_by_prefix_alias": 1,
            "entries_started_fresh": 1,
            "unmatched_previous_entries_preserved": 1,
            "ambiguous_fingerprint_count": 0,
            "ambiguous_fingerprints": [],
            "state_path": "/tmp/state.json",
            "preview_path": "/tmp/preview.json",
            "manifest_path": "/tmp/manifest.json",
            "archived_state_path": None,
        }

        payload = wrapper.state_rebase_payload(result, stamp="unit", dry_run=True)
        summary = wrapper.format_state_rebase_summary(dry_run=True, result=result, stamp="unit")

        self.assertEqual(payload["entries_preserved_by_exact_key"], 1)
        self.assertEqual(payload["entries_preserved_by_fingerprint"], 1)
        self.assertEqual(payload["entries_preserved_by_prefix_alias"], 1)
        self.assertEqual(payload["entries_started_fresh"], 1)
        self.assertEqual(payload["identityMode"], "content-primary")
        self.assertEqual(
            summary,
            "PRUNE_STATE_REBASE_DRY_RUN_OK identity=content-primary exact=1 fingerprint=1 prefix=1 fresh=1 ambiguous=0 stamp=unit",
        )

    def test_do_rebase_state_calls_engine_and_records_wrapper_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview_path = Path(tmp) / "context-pruning-state-rebase-preview.json"
            state_path = Path(tmp) / "context-pruning-state.json"
            preview_path.write_text("{}\n", encoding="utf-8")
            state_path.write_text("{}\n", encoding="utf-8")
            original_run_json = wrapper.run_json
            original_preview = wrapper.STATE_REBASE_PREVIEW
            try:
                wrapper.STATE_REBASE_PREVIEW = preview_path
                captured: dict[str, object] = {}

                def fake_run_json(cmd, envelope, label):  # noqa: ANN001
                    captured["cmd"] = cmd
                    captured["label"] = label
                    return {
                        "old_version": 2,
                        "new_version": 3,
                        "identityMode": "content-primary",
                        "current_item_count": 2,
                        "previous_entry_count": 1,
                        "rebased_entry_count": 2,
                        "entries_preserved_by_exact_key": 1,
                        "entries_preserved_by_fingerprint": 0,
                        "entries_preserved_by_prefix_alias": 0,
                        "entries_started_fresh": 1,
                        "unmatched_previous_entries_preserved": 0,
                        "ambiguous_fingerprint_count": 0,
                        "ambiguous_fingerprints": [],
                        "state_path": str(state_path),
                        "preview_path": str(preview_path),
                        "manifest_path": str(Path(tmp) / "context-pruning-state.rebase-manifest.json"),
                        "archived_state_path": None,
                    }

                wrapper.run_json = fake_run_json
                envelope = FakeEnvelope(run_id="unit-rebase-run")
                args = SimpleNamespace(dry_run=True, apply=False)

                summary = wrapper.do_rebase_state(args, "unit-stamp", envelope)
            finally:
                wrapper.run_json = original_run_json
                wrapper.STATE_REBASE_PREVIEW = original_preview

            self.assertIn("PRUNE_STATE_REBASE_DRY_RUN_OK", summary)
            self.assertIn("rebase-state", captured["cmd"])
            self.assertIn("--dry-run", captured["cmd"])
            self.assertEqual(captured["label"], "context-state-rebase")
            self.assertIn(str(preview_path), envelope.artifact_paths)
            self.assertIn(str(state_path), envelope.artifact_paths)
            wrapper_summary = json.loads(envelope.artifacts["wrapper-summary.json"])
            self.assertEqual(wrapper_summary["mode"], "rebase-state")
            self.assertEqual(wrapper_summary["state_rebase"]["entries_preserved_by_exact_key"], 1)
            self.assertTrue(wrapper_summary["state_rebase"]["dry_run"])

    def test_rebase_state_parser_requires_mode_flag(self) -> None:
        parser = wrapper.build_parser()

        parsed = parser.parse_args(["rebase-state", "--dry-run", "--stamp", "unit"])

        self.assertEqual(parsed.cmd, "rebase-state")
        self.assertTrue(parsed.dry_run)
        self.assertEqual(parsed.stamp, "unit")

    def test_apply_summary_line_includes_no_op_reason(self) -> None:
        summary = wrapper.format_weekly_apply_summary(
            dry_run=True,
            removed_files=0,
            removed_blocks=0,
            bytes_delta=0,
            no_op_reason="no_prune_candidates",
            reindexed=False,
            review=2,
            prune=0,
            telemetry_entries=42,
            local_compress=False,
            local_compress_priority=True,
            stamp="unit-stamp",
        )

        self.assertEqual(
            summary,
            "PRUNE_AUTO_APPLY_DRY_RUN_OK removed_files=0 removed_blocks=0 "
            "bytes_delta=0 no_op=no_prune_candidates reindexed=0 identity=content-primary review=2 prune=0 "
            "telemetry=42 local_compress=0 priority=0 stamp=unit-stamp",
        )


if __name__ == "__main__":
    unittest.main()
