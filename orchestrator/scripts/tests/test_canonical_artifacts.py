#!/usr/bin/env python3
import json
import subprocess
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.canonical_artifacts import build_canonical_machine_artifact_report


class CanonicalMachineArtifactScanTest(unittest.TestCase):
    def test_static_fixture_report_passes_and_covers_core_artifacts(self):
        report = build_canonical_machine_artifact_report()

        self.assertEqual(report["schema_version"], "ads-canonical-machine-artifact-scan/v1")
        self.assertEqual(report["fixture_id"], "FIX-031")
        self.assertEqual(report["blocker_id"], "BLK-027")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["live_cutover_ready"])
        check_names = {check["name"] for check in report["checks"]}
        self.assertIn("question_decomposition_schema", check_names)
        self.assertIn("researcher_sidecar_schema", check_names)
        self.assertIn("model_provenance_trace", check_names)
        self.assertIn("active_authority_key_scan", check_names)
        self.assertGreaterEqual(report["artifact_summary"]["assignment_count"], 1)
        self.assertEqual(
            report["artifact_summary"]["assignment_count"],
            report["artifact_summary"]["coverage_proof_count"],
        )

    def test_cli_emits_json_report(self):
        script = Path(__file__).resolve().parents[1] / "bin" / "check_ads_canonical_artifacts.py"

        result = subprocess.run(
            [sys.executable, str(script)],
            check=True,
            capture_output=True,
            text=True,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["fixture_id"], "FIX-031")


if __name__ == "__main__":
    unittest.main()
