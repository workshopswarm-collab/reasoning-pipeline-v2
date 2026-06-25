#!/usr/bin/env python3
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_runner import (
    ADS_PIPELINE_STAGE_ORDER,
    PIPELINE_CONTROL_STATE_TABLE,
    PIPELINE_RUN_TABLE,
    TERMINAL_REASON_DISABLED,
    TERMINAL_REASON_NON_EXECUTING,
    PipelineRunnerContractError,
    PipelineRunnerPolicy,
    build_pipeline_control_state,
    build_pipeline_run,
    ensure_pipeline_runner_schema,
    read_pipeline_control_state,
    read_pipeline_run,
    run_ads_pipeline_loop,
    validate_pipeline_run,
    write_pipeline_control_state,
)


class AdsPipelineRunnerTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def make_prediction_marker_table(self):
        self.conn.execute("CREATE TABLE market_predictions (id TEXT PRIMARY KEY, marker TEXT NOT NULL)")
        self.conn.execute("INSERT INTO market_predictions (id, marker) VALUES (?, ?)", ("existing", "unchanged"))
        return self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone()

    def test_default_control_state_is_disabled_and_safe_by_default(self):
        control = read_pipeline_control_state(self.conn)

        self.assertFalse(control["pipeline_enabled"])
        self.assertEqual(control["desired_runner_mode"], "non_executing_canary")
        self.assertEqual(control["default_disable_action"], "no_new_leases")
        self.assertEqual(control["reason"], "no_live_autostart_default")
        self.assertEqual(
            self.conn.execute(f"SELECT COUNT(*) FROM {PIPELINE_CONTROL_STATE_TABLE}").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(f"SELECT COUNT(*) FROM {PIPELINE_RUN_TABLE}").fetchone()[0],
            0,
        )

    def test_disabled_pipeline_refuses_runner_start_without_run_or_forecast_write(self):
        before = self.make_prediction_marker_table()

        result = run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy())

        self.assertFalse(result.started)
        self.assertIsNone(result.pipeline_run_id)
        self.assertEqual(result.terminal_status, TERMINAL_REASON_DISABLED)
        self.assertEqual(result.stage_order, ADS_PIPELINE_STAGE_ORDER)
        self.assertFalse(result.downstream_execution_enabled)
        self.assertFalse(result.forecast_persistence_enabled)
        self.assertEqual(
            self.conn.execute(f"SELECT COUNT(*) FROM {PIPELINE_RUN_TABLE}").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone(),
            before,
        )

    def test_enabled_non_executing_runner_writes_run_identity_then_stops(self):
        before = self.make_prediction_marker_table()
        write_pipeline_control_state(
            self.conn,
            build_pipeline_control_state(
                pipeline_enabled=True,
                updated_by="fixture",
                reason="unit test enables non-executing canary",
            ),
        )

        result = run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy())

        self.assertTrue(result.started)
        self.assertTrue(result.pipeline_run_id)
        self.assertEqual(result.terminal_status, "stopped")
        self.assertEqual(result.reason, TERMINAL_REASON_NON_EXECUTING)

        stored = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(stored["status"], "stopped")
        self.assertEqual(stored["runner_mode"], "non_executing_canary")
        self.assertEqual(tuple(stored["stage_order"]), ADS_PIPELINE_STAGE_ORDER)
        self.assertTrue(stored["no_live_autostart"])
        self.assertFalse(stored["downstream_execution_enabled"])
        self.assertFalse(stored["forecast_persistence_enabled"])
        self.assertIsNone(stored["active_case_lease_id"])
        self.assertIsNone(stored["last_iteration_id"])
        self.assertEqual(stored["terminal_reason"], TERMINAL_REASON_NON_EXECUTING)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone(),
            before,
        )

    def test_runner_rejects_downstream_execution_hooks(self):
        write_pipeline_control_state(
            self.conn,
            build_pipeline_control_state(pipeline_enabled=True, updated_by="fixture", reason="unit test"),
        )

        with self.assertRaisesRegex(PipelineRunnerContractError, "downstream stage execution"):
            run_ads_pipeline_loop(self.conn, downstream_stage_handlers={"evidence_packet": lambda: None})

        with self.assertRaisesRegex(PipelineRunnerContractError, "downstream stage execution"):
            run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy(allow_downstream_execution=True))

    def test_enabled_runner_mode_must_match_control_state(self):
        write_pipeline_control_state(
            self.conn,
            build_pipeline_control_state(
                pipeline_enabled=True,
                desired_runner_mode="fixture",
                updated_by="fixture",
                reason="unit test fixture mode",
            ),
        )

        with self.assertRaisesRegex(PipelineRunnerContractError, "desired_runner_mode"):
            run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy(runner_mode="non_executing_canary"))

        result = run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy(runner_mode="fixture"))
        self.assertTrue(result.started)
        self.assertEqual(result.runner_mode, "fixture")

    def test_pipeline_run_contract_rejects_leases_iterations_and_forecast_authority(self):
        run = build_pipeline_run(policy=PipelineRunnerPolicy(), pipeline_run_id="ads-pipeline-run:test")
        run["active_case_lease_id"] = "ads-case-lease:not-yet-owned"
        with self.assertRaisesRegex(PipelineRunnerContractError, "forecast_probability"):
            build_pipeline_run(policy=PipelineRunnerPolicy(), metadata={"forecast_probability": 0.51})
        with self.assertRaisesRegex(PipelineRunnerContractError, "active case lease"):
            validate_pipeline_run(run)

        bad_order = build_pipeline_run(policy=PipelineRunnerPolicy(), pipeline_run_id="ads-pipeline-run:test2")
        bad_order["stage_order"] = list(reversed(json.loads(json.dumps(bad_order["stage_order"]))))
        with self.assertRaisesRegex(PipelineRunnerContractError, "stage_order"):
            validate_pipeline_run(bad_order)

    def test_migration_creates_auto001_control_run_and_auto002_lease_tables(self):
        ensure_pipeline_runner_schema(self.conn)
        tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'ads_%'"
            ).fetchall()
        }

        self.assertEqual(tables, {PIPELINE_CONTROL_STATE_TABLE, PIPELINE_RUN_TABLE, "ads_case_leases"})


if __name__ == "__main__":
    unittest.main()
