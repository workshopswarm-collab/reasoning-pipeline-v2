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
    TERMINAL_REASON_AUTO003_COMPLETE,
    TERMINAL_REASON_AUTO003_FAILED,
    TERMINAL_REASON_DISABLED,
    TERMINAL_REASON_NO_ELIGIBLE_CASE,
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
from predquant.ads_case_selector import CASE_LEASE_TABLE, CaseSelectionPolicy, read_case_lease
from predquant.ads_stage_logging import (
    PIPELINE_ERROR_EVENT_TABLE,
    STAGE_EXECUTION_EVENT_TABLE,
    STAGE_STATUS_TABLE,
)
from predquant.sqlite_store import SCHEMA


class AdsPipelineRunnerTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def make_prediction_marker_table(self):
        self.conn.execute("CREATE TABLE market_predictions (id TEXT PRIMARY KEY, marker TEXT NOT NULL)")
        self.conn.execute("INSERT INTO market_predictions (id, marker) VALUES (?, ?)", ("existing", "unchanged"))
        return tuple(self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone())

    def initialize_intake_case(self, external_market_id="poly-auto003") -> int:
        self.conn.executescript(SCHEMA)
        market_id = self.conn.execute(
            """
            INSERT INTO markets (
              platform, external_market_id, slug, title, description, category,
              status, outcome_type, closes_at, resolves_at, metadata, current_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "polymarket",
                external_market_id,
                "auto003-fixture",
                "Will the AUTO-003 fixture pass?",
                "Fixture description",
                "test",
                "open",
                "binary",
                "2026-06-25T00:00:00+00:00",
                "2026-06-26T00:00:00+00:00",
                "{}",
                0.52,
            ),
        ).lastrowid
        self.conn.execute(
            """
            INSERT INTO market_snapshots (
              market_id, observed_at, last_price, best_bid, best_ask, yes_price,
              no_price, volume, open_interest, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market_id,
                "2026-06-24T17:55:00+00:00",
                None,
                0.42,
                0.48,
                None,
                None,
                1000.0,
                250.0,
                json.dumps({"source": "fixture"}, sort_keys=True),
            ),
        )
        return int(market_id)

    def enable_fixture_pipeline(self):
        write_pipeline_control_state(
            self.conn,
            build_pipeline_control_state(
                pipeline_enabled=True,
                desired_runner_mode="fixture",
                updated_by="fixture",
                reason="unit test enables AUTO-003 fixture runner",
            ),
        )

    def auto003_policy(self):
        return PipelineRunnerPolicy(
            runner_mode="fixture",
            allow_downstream_execution=True,
            allow_forecast_persistence=True,
        )

    def case_selection_policy(self):
        return CaseSelectionPolicy(
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            lease_duration_seconds=900,
            metadata={"test_scope": "AUTO-003"},
        )

    def stage_handlers(self, calls=None, *, duplicate_forecast=False, fail_stage=None, omit_forecast=False):
        calls = calls if calls is not None else []

        def make_handler(stage):
            def handler(**kwargs):
                calls.append(stage)
                if stage == fail_stage:
                    raise RuntimeError(f"{stage} fixture failure")
                result = {
                    "output_artifact_refs": [f"artifact:{stage}"],
                    "validation_result_refs": [f"validation:{stage}"],
                    "safe_metadata": {"stage": stage, "handler_scope": "AUTO-003"},
                }
                if stage == "decision" and not omit_forecast:
                    result["forecast_decision_record_id"] = "forecast-decision:auto003"
                if duplicate_forecast and stage == "replay_record":
                    result["forecast_decision_record_id"] = "forecast-decision:auto003-duplicate"
                return result

            return handler

        return {stage: make_handler(stage) for stage in ADS_PIPELINE_STAGE_ORDER[1:]}

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
            tuple(self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone()),
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
            tuple(self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone()),
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

    def test_auto003_executes_one_leased_case_and_releases_after_forecast_decision_persistence(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()
        calls = []

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(calls),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertTrue(result.started)
        self.assertEqual(result.terminal_status, TERMINAL_REASON_AUTO003_COMPLETE)
        self.assertEqual(result.completed_stage_count, len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(result.forecast_decision_record_id, "forecast-decision:auto003")
        self.assertEqual(calls, list(ADS_PIPELINE_STAGE_ORDER[1:]))

        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "stopped")
        self.assertTrue(run["downstream_execution_enabled"])
        self.assertTrue(run["forecast_persistence_enabled"])
        self.assertIsNone(run["active_case_lease_id"])
        self.assertTrue(run["last_iteration_id"].startswith("ads-loop-iteration:"))
        self.assertEqual(run["metadata"]["forecast_decision_record_id"], "forecast-decision:auto003")

        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "released")
        self.assertEqual(lease["release_reason"], "auto003_single_case_complete")

        completed = self.conn.execute(
            f"SELECT COUNT(*) FROM {STAGE_STATUS_TABLE} WHERE status = 'complete'"
        ).fetchone()[0]
        started_events = self.conn.execute(
            f"SELECT COUNT(*) FROM {STAGE_EXECUTION_EVENT_TABLE} WHERE event_type = 'stage_started'"
        ).fetchone()[0]
        completed_events = self.conn.execute(
            f"SELECT COUNT(*) FROM {STAGE_EXECUTION_EVENT_TABLE} WHERE event_type = 'stage_completed'"
        ).fetchone()[0]
        self.assertEqual(completed, len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(started_events, len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(completed_events, len(ADS_PIPELINE_STAGE_ORDER))

        second_calls = []
        second = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(second_calls),
            case_selection_policy=self.case_selection_policy(),
        )
        self.assertEqual(second.terminal_status, TERMINAL_REASON_NO_ELIGIBLE_CASE)
        self.assertEqual(second_calls, [])
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 1)

    def test_auto003_quarantines_lease_and_logs_structured_failure(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(fail_stage="retrieval"),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_AUTO003_FAILED)
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "quarantined")
        self.assertEqual(lease["release_reason"], "auto003_stage_failed")
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "failed")
        self.assertIsNone(run["active_case_lease_id"])
        failed_events = self.conn.execute(
            f"SELECT COUNT(*) FROM {STAGE_EXECUTION_EVENT_TABLE} WHERE event_type = 'stage_failed'"
        ).fetchone()[0]
        error_events = self.conn.execute(f"SELECT COUNT(*) FROM {PIPELINE_ERROR_EVENT_TABLE}").fetchone()[0]
        self.assertEqual(failed_events, 1)
        self.assertEqual(error_events, 1)

    def test_auto003_rejects_duplicate_forecast_decision_persistence_within_one_case(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(duplicate_forecast=True),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_AUTO003_FAILED)
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "quarantined")

    def test_auto003_requires_persist001_forecast_decision_record(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(omit_forecast=True),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_AUTO003_FAILED)
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "quarantined")


if __name__ == "__main__":
    unittest.main()
