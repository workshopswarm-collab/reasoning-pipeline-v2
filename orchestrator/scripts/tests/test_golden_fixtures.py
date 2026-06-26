#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.golden_fixtures import (
    GOLDEN_FIXTURE_RESULTS_TABLE,
    GOLDEN_FIXTURE_RESULT_SCHEMA_VERSION,
    STARTER_FIXTURE_IDS,
    build_fixture_registry,
    run_fixture_case,
)
from predquant.training_trace import TRAINING_TRACE_MINIMAL_TABLE


class GoldenFixturesTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tempdir.name) / "fixture-output"
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def run_fixture(self, fixture_id, **kwargs):
        result = run_fixture_case(
            fixture_id,
            conn=self.conn,
            output_dir=self.output_dir / fixture_id,
            run_id=f"test-run-{fixture_id}-{len(kwargs)}",
            **kwargs,
        )
        self.conn.commit()
        return result

    def test_registry_loads_all_matrix_rows_and_starter_specs(self):
        registry = build_fixture_registry()

        self.assertGreaterEqual(len(registry), 48)
        for fixture_id, spec in registry.items():
            self.assertTrue(spec.owner_sessions, fixture_id)
            self.assertTrue(spec.target_feature_ids, fixture_id)
            self.assertTrue(spec.blocker_ids, fixture_id)
            self.assertTrue(spec.expected_outcome, fixture_id)
            self.assertTrue(spec.matrix_status, fixture_id)

        self.assertEqual(set(STARTER_FIXTURE_IDS), {fixture_id for fixture_id, spec in registry.items() if spec.starter_implemented})
        self.assertGreater(len(registry["FIX-001"].expected_stages), 8)

    def test_all_starter_wave_b_fixtures_pass_harness(self):
        expected_failure_classes = {
            "FIX-005": "amrg_anchor_required_unrepairable",
            "FIX-006": "forbidden_probability_field",
            "FIX-007": "decision_probability_override_attempt",
        }

        for fixture_id in sorted(STARTER_FIXTURE_IDS):
            with self.subTest(fixture_id=fixture_id):
                result = self.run_fixture(fixture_id)

                self.assertEqual(result.status, "passed")
                self.assertEqual(result.failure_class, expected_failure_classes.get(fixture_id))
                if fixture_id in expected_failure_classes:
                    self.assertTrue(result.error_event_ids)
                else:
                    self.assertFalse(result.error_event_ids)

    def test_minimal_fixture_reaches_stub_terminal_state(self):
        result = self.run_fixture("FIX-001")

        self.assertEqual(result.status, "passed")
        self.assertFalse(result.error_event_ids)
        self.assertTrue(result.report_artifact_id)
        self.assertIn("case_selection", {record["stage"] for record in result.stage_records})
        self.assertIn("decision", {record["stage"] for record in result.stage_records})
        self.assertIn("terminal", {record["stage"] for record in result.stage_records})

        stored = self.conn.execute(
            f"SELECT status, report_artifact_id FROM {GOLDEN_FIXTURE_RESULTS_TABLE} WHERE fixture_result_id = ?",
            (result.fixture_result_id,),
        ).fetchone()
        self.assertEqual(stored, ("passed", result.report_artifact_id))

        report = json.loads((self.output_dir / "FIX-001" / "FIX-001-result-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], GOLDEN_FIXTURE_RESULT_SCHEMA_VERSION)
        self.assertEqual(report["status"], "passed")
        self.assertIn("training_trace_id", report["metadata"])

        trace_rows = self.conn.execute(
            f"""
            SELECT trace_id, case_id, dispatch_id, run_id, forecast_timestamp,
                   artifact_manifest_ids, artifact_hashes, trace_status,
                   live_authority, live_forecast_authority, metadata
            FROM {TRAINING_TRACE_MINIMAL_TABLE}
            WHERE case_id = ? AND run_id = ?
            """,
            (result.case_id, result.run_id),
        ).fetchall()
        self.assertEqual(len(trace_rows), 1)
        trace_row = trace_rows[0]
        self.assertEqual(trace_row[0], report["metadata"]["training_trace_id"])
        self.assertEqual(trace_row[1:5], (result.case_id, result.dispatch_id, result.run_id, result.started_at))
        self.assertEqual(json.loads(trace_row[5]), result.artifact_manifest_ids[:-1])
        self.assertEqual(set(json.loads(trace_row[6])), set(result.artifact_manifest_ids[:-1]))
        self.assertEqual(trace_row[7:10], ("minimal_pointer_written", "none", 0))
        trace_metadata = json.loads(trace_row[10])
        self.assertEqual(
            set(trace_metadata["session5_handoff"]["artifact_role_refs"]),
            {"research", "scae", "decision"},
        )
        self.assertTrue(trace_metadata["session5_handoff"]["no_replay_scoring_or_calibration_writes"])

    def test_missing_artifact_fails_closed_with_error_event(self):
        result = self.run_fixture("FIX-001", simulate_missing_artifact_stage="retrieval")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "missing_required_artifact")
        self.assertTrue(result.missing_artifacts)
        self.assertTrue(result.error_event_ids)

        row = self.conn.execute(
            "SELECT failure_class, retryability FROM v2_pipeline_error_events WHERE error_event_id = ?",
            (result.error_event_ids[0],),
        ).fetchone()
        self.assertEqual(row, ("missing_required_artifact", "terminal"))

    def test_invalid_stage_transition_fails_closed(self):
        result = self.run_fixture("FIX-001", force_invalid_transition_stage="retrieval")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "invalid_stage_transition")
        row = self.conn.execute(
            "SELECT failure_class FROM v2_pipeline_error_events WHERE error_event_id = ?",
            (result.error_event_ids[0],),
        ).fetchone()
        self.assertEqual(row[0], "invalid_stage_transition")

    def test_probability_authoring_attempt_fails_closed(self):
        result = self.run_fixture("FIX-006")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.failure_class, "forbidden_probability_field")
        error_row = self.conn.execute(
            "SELECT stage, failure_class FROM v2_pipeline_error_events WHERE error_event_id = ?",
            (result.error_event_ids[0],),
        ).fetchone()
        self.assertEqual(error_row, ("researcher_classification", "forbidden_probability_field"))

        validation_rows = self.conn.execute(
            "SELECT status FROM artifact_validation_results WHERE status = 'invalid_terminal'"
        ).fetchall()
        self.assertTrue(validation_rows)

    def test_decision_override_attempt_fails_closed(self):
        result = self.run_fixture("FIX-007")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.failure_class, "decision_probability_override_attempt")
        error_row = self.conn.execute(
            "SELECT stage, failure_class FROM v2_pipeline_error_events WHERE error_event_id = ?",
            (result.error_event_ids[0],),
        ).fetchone()
        self.assertEqual(error_row, ("decision", "decision_probability_override_attempt"))

    def test_runtime_dependency_mode_allows_ready_fixture_path(self):
        result = self.run_fixture("FIX-001", dependency_mode="runtime_integration")

        self.assertEqual(result.status, "passed")
        self.assertFalse(result.error_event_ids)
        self.assertIn("decision", {record["stage"] for record in result.stage_records})


if __name__ == "__main__":
    unittest.main()
