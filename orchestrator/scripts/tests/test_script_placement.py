#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.script_placement import build_script_placement_report, parse_script_placement_map


class ScriptPlacementTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.owner_roots = {
            "Orchestrator": self.root / "orchestrator" / "scripts",
            "ADS Decomposer": self.root / "decomposer" / "scripts",
            "ADS Researcher Swarm": self.root / "researcher-swarm" / "scripts",
            "SCAE": self.root / "SCAE" / "scripts",
        }
        for root in self.owner_roots.values():
            root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tempdir.cleanup()

    def write_map(self, rows_by_heading):
        lines = [
            "# Test Script Placement Map",
            "",
            "## Planned Script Paths",
            "",
        ]
        for heading, rows in rows_by_heading.items():
            lines.extend(
                [
                    f"### {heading}",
                    "",
                    "| Planned path | Owning features | Purpose |",
                    "| --- | --- | --- |",
                ]
            )
            lines.extend(rows)
            lines.append("")
        path = self.root / "placement.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_passing_report_requires_existing_paths_under_declared_owner(self):
        planned = self.owner_roots["Orchestrator"] / "bin" / "run_fixture.py"
        planned.parent.mkdir(parents=True, exist_ok=True)
        planned.write_text("# fixture\n", encoding="utf-8")
        map_path = self.write_map(
            {
                "Orchestrator Scripts": [
                    f"| `{planned}` | `FIX-039`, `BLK-032` | Static fixture scan. |",
                ]
            }
        )

        rows = parse_script_placement_map(map_path)
        report = build_script_placement_report(map_path=map_path, owner_roots=self.owner_roots)

        self.assertEqual(len(rows), 1)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["checked_path_count"], 1)
        self.assertEqual(report["missing_path_count"], 0)
        self.assertTrue(report["live_cutover_ready"])

    def test_missing_path_fails_closed(self):
        planned = self.owner_roots["SCAE"] / "bin" / "run_scae_ledger.py"
        map_path = self.write_map(
            {
                "SCAE Scripts": [
                    f"| `{planned}` | `SCAE-001`, `FIX-039` | Ledger runner. |",
                ]
            }
        )

        report = build_script_placement_report(map_path=map_path, owner_roots=self.owner_roots)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["missing_path_count"], 1)
        self.assertEqual(report["missing_paths"][0]["planned_path"], str(planned))
        self.assertFalse(report["live_cutover_ready"])

    def test_owner_mismatch_fails_closed(self):
        planned = self.owner_roots["Orchestrator"] / "bin" / "run_decomposition.py"
        planned.parent.mkdir(parents=True, exist_ok=True)
        planned.write_text("# wrong owner\n", encoding="utf-8")
        map_path = self.write_map(
            {
                "Decomposer Scripts": [
                    f"| `{planned}` | `QDT-001`, `FIX-039` | Decomposer runner. |",
                ]
            }
        )

        report = build_script_placement_report(map_path=map_path, owner_roots=self.owner_roots)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["owner_mismatch_count"], 1)
        self.assertEqual(report["owner_mismatches"][0]["actual_owner"], "Orchestrator")
        self.assertEqual(report["owner_mismatches"][0]["expected_owner"], "ADS Decomposer")

    def test_duplicate_path_fails_closed(self):
        planned = self.owner_roots["ADS Researcher Swarm"] / "bin" / "run_researcher_swarm.py"
        planned.parent.mkdir(parents=True, exist_ok=True)
        planned.write_text("# researcher\n", encoding="utf-8")
        row = f"| `{planned}` | `CLS-001`, `FIX-039` | Researcher runner. |"
        map_path = self.write_map({"Researcher Swarm Scripts": [row, row]})

        report = build_script_placement_report(map_path=map_path, owner_roots=self.owner_roots)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["duplicate_path_count"], 1)
        self.assertEqual(report["duplicate_paths"][0]["planned_path"], str(planned))


if __name__ == "__main__":
    unittest.main()
