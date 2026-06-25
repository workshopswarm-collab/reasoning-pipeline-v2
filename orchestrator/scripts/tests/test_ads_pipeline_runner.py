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
    PIPELINE_LOOP_ITERATION_TABLE,
    PIPELINE_RUN_TABLE,
    PIPELINE_STOP_SIGNAL_TABLE,
    TERMINAL_REASON_AUTO003_COMPLETE,
    TERMINAL_REASON_AUTO003_FAILED,
    TERMINAL_REASON_DISABLED,
    TERMINAL_REASON_NO_ELIGIBLE_CASE,
    TERMINAL_REASON_NON_EXECUTING,
    TERMINAL_REASON_RETRY_SCHEDULED,
    TERMINAL_REASON_SAFE_DRAIN,
    TERMINAL_REASON_STOP_AFTER_CURRENT,
    TERMINAL_REASON_STOP_BEFORE_NEXT,
    TERMINAL_REASON_STUCK_LEASE_RECOVERED,
    NonRetryableStageError,
    PipelineRunnerContractError,
    PipelineRunnerPolicy,
    RetryableStageError,
    build_pipeline_control_state,
    build_pipeline_run,
    ensure_pipeline_runner_schema,
    read_pipeline_control_state,
    read_pipeline_loop_iteration,
    read_pipeline_run,
    read_pipeline_stop_signal,
    recover_stuck_case_leases,
    run_ads_pipeline_loop,
    validate_pipeline_run,
    write_pipeline_control_state,
)
from predquant.ads_pipeline_control import request_pipeline_stop
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

    def auto003_policy(self, **overrides):
        values = {
            "runner_mode": "fixture",
            "allow_downstream_execution": True,
            "allow_forecast_persistence": True,
        }
        values.update(overrides)
        return PipelineRunnerPolicy(**values)

    def case_selection_policy(self):
        return CaseSelectionPolicy(
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            lease_duration_seconds=900,
            metadata={"test_scope": "AUTO-003"},
        )

    def stage_handlers(
        self,
        calls=None,
        *,
        duplicate_forecast=False,
        fail_stage=None,
        retry_stage=None,
        non_retryable_stage=None,
        disable_after_stage=None,
        disable_action="safe_drain_now",
        omit_forecast=False,
    ):
        calls = calls if calls is not None else []

        def make_handler(stage):
            def handler(**kwargs):
                calls.append(stage)
                if stage == retry_stage:
                    raise RetryableStageError(f"{stage} transient fixture failure", retry_after_seconds=7)
                if stage == non_retryable_stage:
                    raise NonRetryableStageError(f"{stage} non-retryable fixture failure")
                if stage == fail_stage:
                    raise RuntimeError(f"{stage} fixture failure")
                result = {
                    "output_artifact_refs": [f"artifact:{stage}"],
                    "validation_result_refs": [f"validation:{stage}"],
                    "safe_metadata": {"stage": stage, "handler_scope": "AUTO-003"},
                }
                if stage == disable_after_stage:
                    write_pipeline_control_state(
                        self.conn,
                        build_pipeline_control_state(
                            pipeline_enabled=False,
                            desired_runner_mode="fixture",
                            updated_by="fixture",
                            reason="unit test disables active AUTO-004 run",
                            default_disable_action=disable_action,
                        ),
                    )
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

        self.assertEqual(
            tables,
            {
                PIPELINE_CONTROL_STATE_TABLE,
                PIPELINE_RUN_TABLE,
                PIPELINE_LOOP_ITERATION_TABLE,
                PIPELINE_STOP_SIGNAL_TABLE,
                "ads_case_leases",
            },
        )

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
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_AUTO003_COMPLETE)
        self.assertEqual(loop["case_lease_id"], result.case_lease_id)
        self.assertEqual(loop["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(loop["forecast_decision_record_id"], "forecast-decision:auto003")
        self.assertEqual(loop["error_event_refs"], [])

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
        second_run = read_pipeline_run(self.conn, second.pipeline_run_id)
        second_loop = read_pipeline_loop_iteration(self.conn, second_run["last_iteration_id"])
        self.assertEqual(second_loop["terminal_status"], TERMINAL_REASON_NO_ELIGIBLE_CASE)
        self.assertIsNone(second_loop["case_lease_id"])
        self.assertTrue(second_loop["metadata"]["empty_queue"])

    def test_auto004_stop_before_next_case_exits_without_acquiring_lease(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(stop_policy="stop_before_next_case"),
            downstream_stage_handlers=self.stage_handlers(),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_STOP_BEFORE_NEXT)
        self.assertIsNone(result.case_lease_id)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 0)
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "stopped")
        self.assertIsNone(run["active_case_lease_id"])
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_STOP_BEFORE_NEXT)
        self.assertIsNone(loop["case_lease_id"])

    def test_auto004_stop_after_current_case_finishes_and_acknowledges(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()
        calls = []

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(stop_policy="stop_after_current_case"),
            downstream_stage_handlers=self.stage_handlers(calls),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_STOP_AFTER_CURRENT)
        self.assertEqual(calls, list(ADS_PIPELINE_STAGE_ORDER[1:]))
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "released")
        self.assertEqual(lease["release_reason"], "auto004_stop_after_current_case")
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "stopped")
        self.assertIsNone(run["active_case_lease_id"])
        self.assertTrue(run["metadata"]["stop_after_current_requested"])
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_STOP_AFTER_CURRENT)
        self.assertEqual(loop["forecast_decision_record_id"], "forecast-decision:auto003")

    def test_auto004_retryable_stage_failure_writes_backoff_and_keeps_lease_recoverable(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(retry_backoff_seconds=11),
            downstream_stage_handlers=self.stage_handlers(retry_stage="retrieval"),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_RETRY_SCHEDULED)
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "leased")
        self.assertIsNone(lease["release_reason"])
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "draining")
        self.assertEqual(run["active_case_lease_id"], result.case_lease_id)
        self.assertEqual(run["metadata"]["retry_stage"], "retrieval")
        self.assertIn("next_retry_at", run["metadata"])
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_RETRY_SCHEDULED)
        self.assertEqual(loop["retry_summary"]["retry_stage"], "retrieval")
        self.assertEqual(loop["error_event_refs"][0].split(":")[0], "pipeline-error")
        retry_events = self.conn.execute(
            f"SELECT COUNT(*) FROM {STAGE_EXECUTION_EVENT_TABLE} WHERE event_type = 'retry_scheduled'"
        ).fetchone()[0]
        retryable_errors = self.conn.execute(
            f"SELECT COUNT(*) FROM {PIPELINE_ERROR_EVENT_TABLE} WHERE retryability = 'retryable'"
        ).fetchone()[0]
        self.assertEqual(retry_events, 1)
        self.assertEqual(retryable_errors, 1)

    def test_auto004_non_retryable_stage_failure_quarantines_with_soft_fail_reason(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(non_retryable_stage="retrieval"),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_AUTO003_FAILED)
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "quarantined")
        self.assertEqual(lease["release_reason"], "auto004_non_retryable_stage_failed")
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertTrue(run["metadata"]["non_retryable_failure"])
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_AUTO003_FAILED)
        self.assertTrue(loop["metadata"]["non_retryable_failure"])

    def test_auto004_safe_drain_disable_releases_active_lease_and_acknowledges_control(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(disable_after_stage="retrieval"),
            case_selection_policy=self.case_selection_policy(),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_SAFE_DRAIN)
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "expired")
        self.assertEqual(lease["release_reason"], TERMINAL_REASON_SAFE_DRAIN)
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "stopped")
        self.assertIsNone(run["active_case_lease_id"])
        self.assertEqual(run["metadata"]["safe_drained_after_stage"], "retrieval")
        control = read_pipeline_control_state(self.conn)
        self.assertEqual(control["acknowledged_by_run_id"], result.pipeline_run_id)
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_SAFE_DRAIN)
        self.assertEqual(loop["metadata"]["safe_drained_after_stage"], "retrieval")

    def test_auto004_stuck_lease_recovery_expires_lease_and_clears_active_run(self):
        self.initialize_intake_case()
        self.enable_fixture_pipeline()
        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(),
            downstream_stage_handlers=self.stage_handlers(retry_stage="retrieval"),
            case_selection_policy=CaseSelectionPolicy(
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                lease_duration_seconds=1,
                metadata={"test_scope": "AUTO-004"},
            ),
        )
        self.assertEqual(result.terminal_status, TERMINAL_REASON_RETRY_SCHEDULED)

        recovered = recover_stuck_case_leases(
            self.conn,
            recovered_at="2100-01-01T00:00:00+00:00",
        )

        self.assertEqual([lease["case_lease_id"] for lease in recovered], [result.case_lease_id])
        self.assertEqual(recovered[0]["cleared_pipeline_run_ids"], [result.pipeline_run_id])
        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "expired")
        self.assertEqual(lease["release_reason"], TERMINAL_REASON_STUCK_LEASE_RECOVERED)
        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "failed")
        self.assertIsNone(run["active_case_lease_id"])
        self.assertEqual(run["terminal_reason"], TERMINAL_REASON_STUCK_LEASE_RECOVERED)

    def test_auto005_continuous_fixture_runs_two_unique_cases_and_stops_after_current_request(self):
        self.initialize_intake_case("poly-auto005-a")
        self.initialize_intake_case("poly-auto005-b")
        self.enable_fixture_pipeline()
        calls = []
        decision_record_ids = []

        def make_handler(stage):
            def handler(**kwargs):
                context = kwargs["context"]
                lease = kwargs["lease"]
                calls.append((lease["case_key"], stage))
                result = {
                    "output_artifact_refs": [f"artifact:{stage}:{lease['case_id']}"],
                    "validation_result_refs": [f"validation:{stage}:{lease['case_id']}"],
                    "safe_metadata": {"stage": stage, "handler_scope": "AUTO-005"},
                }
                if stage == "decision":
                    record_id = f"forecast-decision:auto005:{lease['case_id']}"
                    decision_record_ids.append(record_id)
                    result["forecast_decision_record_id"] = record_id
                    if len(decision_record_ids) == 2:
                        request_pipeline_stop(
                            kwargs["conn"],
                            stop_policy="stop_after_current_case",
                            reason="AUTO-005 fixture stops after second case",
                            requested_by="fixture",
                            pipeline_run_id=context.pipeline_run_id,
                            metadata={"scope": "AUTO-005", "decision_count": 2},
                        )
                return result

            return handler

        handlers = {stage: make_handler(stage) for stage in ADS_PIPELINE_STAGE_ORDER[1:]}

        result = run_ads_pipeline_loop(
            self.conn,
            self.auto003_policy(max_cases=2),
            downstream_stage_handlers=handlers,
            case_selection_policy=CaseSelectionPolicy(
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                lease_duration_seconds=900,
                metadata={"test_scope": "AUTO-005"},
            ),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_STOP_AFTER_CURRENT)
        self.assertEqual(result.completed_stage_count, len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(len(decision_record_ids), 2)
        self.assertEqual(len(set(decision_record_ids)), 2)

        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["status"], "stopped")
        self.assertEqual(run["terminal_reason"], TERMINAL_REASON_STOP_AFTER_CURRENT)
        self.assertIsNone(run["active_case_lease_id"])
        self.assertEqual(run["metadata"]["processed_case_count"], 2)
        self.assertEqual(len(run["metadata"]["completed_case_lease_ids"]), 2)
        self.assertEqual(len(set(run["metadata"]["completed_case_keys"])), 2)
        self.assertEqual(run["metadata"]["forecast_decision_record_ids"], decision_record_ids)

        lease_rows = self.conn.execute(
            f"""
            SELECT case_lease_id, case_key, lease_status, release_reason
            FROM {CASE_LEASE_TABLE}
            ORDER BY lease_acquired_at, case_lease_id
            """
        ).fetchall()
        self.assertEqual(len(lease_rows), 2)
        self.assertEqual({row[2] for row in lease_rows}, {"released"})
        self.assertEqual(len({row[1] for row in lease_rows}), 2)
        self.assertEqual(lease_rows[0][3], "auto005_iteration_complete")
        self.assertEqual(lease_rows[1][3], "auto004_stop_after_current_case")
        self.assertEqual(
            self.conn.execute(
                f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE} WHERE lease_status = 'leased'"
            ).fetchone()[0],
            0,
        )

        loop_rows = self.conn.execute(
            f"""
            SELECT loop_iteration_id, iteration_number, case_lease_id,
                   terminal_status, completed_stage_count, forecast_decision_record_id
            FROM {PIPELINE_LOOP_ITERATION_TABLE}
            WHERE pipeline_run_id = ?
            ORDER BY iteration_number
            """,
            (result.pipeline_run_id,),
        ).fetchall()
        self.assertEqual(len(loop_rows), 2)
        self.assertEqual([row[1] for row in loop_rows], [1, 2])
        self.assertEqual(len({row[2] for row in loop_rows}), 2)
        self.assertEqual(loop_rows[0][3], TERMINAL_REASON_AUTO003_COMPLETE)
        self.assertEqual(loop_rows[1][3], TERMINAL_REASON_STOP_AFTER_CURRENT)
        self.assertEqual([row[4] for row in loop_rows], [len(ADS_PIPELINE_STAGE_ORDER)] * 2)
        self.assertEqual([row[5] for row in loop_rows], decision_record_ids)
        second_loop = read_pipeline_loop_iteration(self.conn, loop_rows[1][0])
        self.assertTrue(second_loop["metadata"]["stop_after_current_requested"])

        self.assertEqual(
            self.conn.execute(f"SELECT COUNT(*) FROM {STAGE_STATUS_TABLE} WHERE status = 'complete'").fetchone()[0],
            len(ADS_PIPELINE_STAGE_ORDER) * 2,
        )
        self.assertEqual(
            [case_key for case_key, stage in calls if stage == "decision"],
            run["metadata"]["completed_case_keys"],
        )

        control = read_pipeline_control_state(self.conn)
        self.assertFalse(control["pipeline_enabled"])
        self.assertEqual(control["acknowledged_by_run_id"], result.pipeline_run_id)
        signal = read_pipeline_stop_signal(self.conn, control["metadata"]["stop_signal"]["stop_signal_id"])
        self.assertEqual(signal["signal_status"], "acknowledged")
        self.assertEqual(signal["acknowledged_by_run_id"], result.pipeline_run_id)
        self.assertEqual(signal["stop_policy"], "stop_after_current_case")

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
        loop = read_pipeline_loop_iteration(self.conn, run["last_iteration_id"])
        self.assertEqual(loop["terminal_status"], TERMINAL_REASON_AUTO003_FAILED)
        self.assertEqual(len(loop["error_event_refs"]), 1)

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
