#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.maintenance_phase0 import (  # noqa: E402
    SCHEMA_VERSION,
    capture_maintenance_phase0_baseline,
    phase_test_root,
    write_phase0_baseline,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class MaintenancePhase0Tests(unittest.TestCase):
    def test_phase_test_root_removes_root_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "tmp" / "maintenance-plan-tests"
            with phase_test_root("Phase 0", base_root=base, run_id="fixture") as root:
                self.assertTrue(root.exists())
                self.assertEqual(root, base / "phase-0" / "fixture")
                (root / "baseline.json").write_text("{}\n", encoding="utf-8")
            self.assertFalse((base / "phase-0" / "fixture").exists())

    def test_phase_test_root_removes_root_after_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "tmp" / "maintenance-plan-tests"
            captured_root: Path | None = None
            try:
                with phase_test_root("Phase 0", base_root=base, run_id="exception-fixture") as root:
                    captured_root = root
                    (root / "artifact.txt").write_text("temporary\n", encoding="utf-8")
                    raise RuntimeError("fixture failure")
            except RuntimeError as exc:
                self.assertEqual(str(exc), "fixture failure")
            else:
                raise AssertionError("expected fixture failure")
            self.assertIsNotNone(captured_root)
            assert captured_root is not None
            self.assertFalse(captured_root.exists())

    def test_capture_phase0_baseline_includes_required_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"

            self_check = repo / "maintenance" / "maintenance_self_check.py"
            self_check.parent.mkdir(parents=True)
            self_check.write_text(
                "EXPECTED_JOBS = [\n"
                "    'Maintenance: Workbench Context Prune Audit',\n"
                "    'Maintenance: Workbench Context Prune Pressure Check',\n"
                "]\n",
                encoding="utf-8",
            )

            pressure_run = repo / "maintenance" / "workbench-context-maintenance" / "generated" / "runs" / "run-1"
            write_json(pressure_run / "envelope.json", {"status": "ok", "summary_line": "PRUNE_PRESSURE_CHECK_OK result=applied"})
            write_json(pressure_run / "pressure-apply-manifest.json", {"mode": "apply", "source_mutated": True, "no_op_reason": "none"})

            for rel_path, text in {
                "active.md": "# Active\n",
                "decisions.md": "# Decisions\n",
                "projects/quant-pipeline.md": "# Quant\n",
                "projects/workbench-context.md": "# Workbench Context\n",
            }.items():
                path = repo / "workbench" / "context" / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            write_json(repo / "workbench" / "context" / "state" / "context-pruning-state.json", {"items": {"a": {}}})

            hygiene_root = repo / "maintenance" / "orchestrator-repo-maintenance" / "generated"
            write_json(
                hygiene_root / "script-usage-summary.json",
                {"summary": {"classified_script_count": 2}, "scripts": [{"path": "a.py"}, {"path": "b.py"}]},
            )
            write_json(hygiene_root / "scheduled-maintenance-state.json", {"last_success_at": "2026-06-18T00:00:00Z"})

            runtime_root = repo / "orchestrator" / "scripts" / ".runtime-state"
            write_json(runtime_root / "learning-maintenance-plane-status.json", {"ok": True, "status": "idle"})
            write_json(
                runtime_root / "lmd-causal-maintenance-status.json",
                {
                    "status": "failed",
                    "last_success_at": "2026-06-08T00:00:00Z",
                    "failed_at_utc": "2026-06-17T05:00:14Z",
                    "error_type": "timeout",
                },
            )

            launchd_dir = repo / "orchestrator" / "scripts" / "launchd"
            launchd_dir.mkdir(parents=True)
            (launchd_dir / "ai.openclaw.orchestrator.learning-maintenance.plist").write_text(
                f"<plist><string>{repo / 'orchestrator'}</string></plist>\n",
                encoding="utf-8",
            )

            baseline = capture_maintenance_phase0_baseline(repo, generated_at_utc="2026-06-18T17:00:00Z")

            self.assertEqual(baseline["schema_version"], SCHEMA_VERSION)
            self.assertEqual(baseline["generated_at_utc"], "2026-06-18T17:00:00Z")
            pressure = baseline["workbench_context"]["latest_pressure_run"]
            self.assertEqual(pressure["latest_envelope"]["status"], "ok")
            self.assertIs(pressure["pressure_apply_manifest"]["source_mutated"], True)
            self.assertEqual(baseline["workbench_context"]["hot_context_files"]["context/active.md"]["size_bytes"], len("# Active\n"))
            self.assertIs(baseline["workbench_context"]["state_file"]["exists"], True)
            self.assertEqual(baseline["maintenance_self_check"]["expected_cron_jobs"]["job_count"], 2)
            self.assertEqual(baseline["repo_hygiene"]["script_usage_summary"]["classified_script_count"], 2)
            self.assertEqual(baseline["repo_hygiene"]["scheduled_state"]["last_success_at"], "2026-06-18T00:00:00Z")
            self.assertEqual(baseline["learning_maintenance"]["status"], "idle")
            self.assertEqual(baseline["lmd_causal_maintenance"]["status"], "failed")
            self.assertEqual(baseline["lmd_causal_maintenance"]["error_type"], "timeout")
            self.assertEqual(baseline["launchd_path_status"]["private_tmp_path_count"], 0)

            output = tmp_path / "baseline.json"
            write_phase0_baseline(output, baseline)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["schema_version"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
