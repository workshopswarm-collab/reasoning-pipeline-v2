#!/usr/bin/env python3
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_case_selector import (
    CaseLeaseRefused,
    CaseSelectionPolicy,
    acquire_case_lease,
    read_case_lease,
    select_eligible_case,
)
from predquant.ads_pipeline_control import (
    PIPELINE_STOP_SIGNAL_SCHEMA_VERSION,
    acknowledge_pipeline_control_state,
    get_pipeline_control_state,
    request_pipeline_stop,
    set_pipeline_enabled,
)
from predquant.ads_pipeline_runner import (
    ADS_PIPELINE_STAGE_ORDER,
    DEFAULT_DISABLE_ACTION,
    PipelineRunnerPolicy,
    TERMINAL_REASON_STOP_AFTER_CURRENT,
    build_pipeline_run,
    read_pipeline_control_state,
    read_pipeline_stop_signal,
    read_pipeline_run,
    run_ads_pipeline_loop,
    write_pipeline_run,
)
from predquant.sqlite_store import SCHEMA


BIN_ROOT = Path(__file__).resolve().parents[1] / "bin"


def load_bin_module(name: str):
    spec = importlib.util.spec_from_file_location(name, BIN_ROOT / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdsPipelineControlTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def initialize_intake_case(self, external_market_id="poly-auto006"):
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
                "auto006-fixture",
                "Will the AUTO-006 fixture pass?",
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

    def create_pipeline_run(self) -> str:
        record = build_pipeline_run(
            policy=PipelineRunnerPolicy(),
            status="running",
            terminal_reason="unit_test_auto006_active_run",
        )
        write_pipeline_run(self.conn, record)
        return record["pipeline_run_id"]

    def test_manual_enable_disable_persists_and_gates_runner_restart(self):
        default_control = get_pipeline_control_state(self.conn)
        self.assertFalse(default_control["pipeline_enabled"])

        disabled_result = run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy())
        self.assertFalse(disabled_result.started)

        enabled = set_pipeline_enabled(
            self.conn,
            pipeline_enabled=True,
            updated_by="fixture",
            reason="unit test enables manual AUTO-006 switch",
        )
        self.assertTrue(enabled["pipeline_enabled"])
        self.assertEqual(enabled["default_disable_action"], DEFAULT_DISABLE_ACTION)

        started_result = run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy())
        self.assertTrue(started_result.started)

        disabled = set_pipeline_enabled(
            self.conn,
            pipeline_enabled=False,
            updated_by="fixture",
            reason="unit test disables manual AUTO-006 switch",
            default_disable_action="stop_after_current_case",
        )
        self.assertFalse(disabled["pipeline_enabled"])
        self.assertEqual(disabled["default_disable_action"], "stop_after_current_case")

        restart_result = run_ads_pipeline_loop(self.conn, PipelineRunnerPolicy())
        self.assertFalse(restart_result.started)

    def test_disable_after_candidate_selection_refuses_new_lease(self):
        self.initialize_intake_case()
        set_pipeline_enabled(
            self.conn,
            pipeline_enabled=True,
            updated_by="fixture",
            reason="unit test enables candidate selection",
        )
        run_id = self.create_pipeline_run()
        candidate = select_eligible_case(
            self.conn,
            policy=CaseSelectionPolicy(forecast_timestamp="2026-06-24T18:00:00+00:00"),
        )
        self.assertIsNotNone(candidate)

        set_pipeline_enabled(
            self.conn,
            pipeline_enabled=False,
            updated_by="fixture",
            reason="unit test disables before lease acquisition",
        )

        with self.assertRaises(CaseLeaseRefused) as raised:
            acquire_case_lease(self.conn, pipeline_run_id=run_id, candidate=candidate)

        self.assertEqual(raised.exception.reason_code, "pipeline_disabled")

    def test_control_acknowledgement_records_runner_id_without_enabling(self):
        acknowledged = acknowledge_pipeline_control_state(
            self.conn,
            pipeline_run_id="ads-pipeline-run:ack",
            updated_by="fixture",
            reason="unit test acknowledgement",
        )

        self.assertFalse(acknowledged["pipeline_enabled"])
        self.assertEqual(acknowledged["acknowledged_by_run_id"], "ads-pipeline-run:ack")
        self.assertEqual(acknowledged["reason"], "unit test acknowledgement")

    def test_stop_request_records_structured_signal_without_enabling_pipeline(self):
        set_pipeline_enabled(
            self.conn,
            pipeline_enabled=True,
            updated_by="fixture",
            reason="unit test enables before stop request",
            desired_runner_mode="fixture",
        )

        stopped = request_pipeline_stop(
            self.conn,
            stop_policy="stop_after_current_case",
            requested_by="fixture",
            reason="unit test requests stop after current",
            pipeline_run_id="ads-pipeline-run:active",
            metadata={"scope": "AUTO-004"},
        )

        self.assertFalse(stopped["pipeline_enabled"])
        self.assertEqual(stopped["desired_runner_mode"], "fixture")
        self.assertEqual(stopped["default_disable_action"], "stop_after_current_case")
        signal = stopped["metadata"]["stop_signal"]
        self.assertEqual(signal["schema_version"], PIPELINE_STOP_SIGNAL_SCHEMA_VERSION)
        self.assertEqual(signal["stop_policy"], "stop_after_current_case")
        self.assertEqual(signal["pipeline_run_id"], "ads-pipeline-run:active")
        self.assertEqual(signal["metadata"], {"scope": "AUTO-004"})
        stored_signal = read_pipeline_stop_signal(self.conn, signal["stop_signal_id"])
        self.assertEqual(stored_signal["signal_status"], "pending")
        self.assertEqual(stored_signal["stop_policy"], "stop_after_current_case")
        self.assertEqual(stored_signal["metadata"], {"scope": "AUTO-004"})

    def test_manual_stop_after_current_during_active_run_acknowledges_and_blocks_next_lease(self):
        self.initialize_intake_case("poly-auto006-stop-a")
        self.initialize_intake_case("poly-auto006-stop-b")
        set_pipeline_enabled(
            self.conn,
            pipeline_enabled=True,
            updated_by="fixture",
            reason="unit test enables FIX-041 fixture",
            desired_runner_mode="fixture",
        )
        calls = []

        def make_handler(stage):
            def handler(**kwargs):
                lease = kwargs["lease"]
                calls.append((lease["case_key"], stage))
                result = {
                    "output_artifact_refs": [f"artifact:{stage}:{lease['case_id']}"],
                    "validation_result_refs": [f"validation:{stage}:{lease['case_id']}"],
                    "safe_metadata": {"stage": stage, "handler_scope": "FIX-041"},
                }
                if stage == "decision":
                    result["forecast_decision_record_id"] = f"forecast-decision:fix041:{lease['case_id']}"
                    request_pipeline_stop(
                        kwargs["conn"],
                        stop_policy="stop_after_current_case",
                        requested_by="fixture",
                        reason="FIX-041 stops after active case",
                        pipeline_run_id=kwargs["context"].pipeline_run_id,
                        metadata={"scope": "FIX-041"},
                    )
                return result

            return handler

        result = run_ads_pipeline_loop(
            self.conn,
            PipelineRunnerPolicy(
                runner_mode="fixture",
                allow_downstream_execution=True,
                allow_forecast_persistence=True,
                max_cases=2,
            ),
            downstream_stage_handlers={stage: make_handler(stage) for stage in ADS_PIPELINE_STAGE_ORDER[1:]},
            case_selection_policy=CaseSelectionPolicy(
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                lease_duration_seconds=900,
                metadata={"test_scope": "FIX-041"},
            ),
        )

        self.assertEqual(result.terminal_status, TERMINAL_REASON_STOP_AFTER_CURRENT)
        self.assertEqual(len({case_key for case_key, _ in calls}), 1)

        run = read_pipeline_run(self.conn, result.pipeline_run_id)
        self.assertEqual(run["metadata"]["processed_case_count"], 1)
        self.assertEqual(len(run["metadata"]["completed_case_lease_ids"]), 1)
        self.assertIsNone(run["active_case_lease_id"])

        lease = read_case_lease(self.conn, result.case_lease_id)
        self.assertEqual(lease["lease_status"], "released")
        self.assertEqual(lease["release_reason"], "auto004_stop_after_current_case")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM ads_case_leases WHERE lease_status = 'leased'").fetchone()[0],
            0,
        )

        control = read_pipeline_control_state(self.conn)
        self.assertFalse(control["pipeline_enabled"])
        self.assertEqual(control["acknowledged_by_run_id"], result.pipeline_run_id)
        signal = read_pipeline_stop_signal(self.conn, control["metadata"]["stop_signal"]["stop_signal_id"])
        self.assertEqual(signal["signal_status"], "acknowledged")
        self.assertEqual(signal["acknowledged_by_run_id"], result.pipeline_run_id)
        self.assertEqual(signal["stop_policy"], "stop_after_current_case")

    def test_set_and_get_cli_helpers_share_durable_state(self):
        set_cli = load_bin_module("set_ads_pipeline_enabled")
        get_cli = load_bin_module("get_ads_pipeline_control")

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "ads-control.sqlite3")
            with redirect_stdout(io.StringIO()):
                set_result = set_cli.main(
                    [
                        "enabled",
                        "--db-path",
                        db_path,
                        "--updated-by",
                        "fixture",
                        "--reason",
                        "unit test CLI enable",
                        "--metadata-json",
                        '{"scope":"AUTO-006"}',
                    ]
                )
                get_result = get_cli.main(["--db-path", db_path])

            self.assertEqual(set_result, 0)
            self.assertEqual(get_result, 0)

            conn = sqlite3.connect(db_path)
            try:
                control = get_pipeline_control_state(conn, create_default=False)
            finally:
                conn.close()

        self.assertTrue(control["pipeline_enabled"])
        self.assertEqual(control["updated_by"], "fixture")
        self.assertEqual(control["reason"], "unit test CLI enable")
        self.assertEqual(control["metadata"], {"scope": "AUTO-006"})

    def test_stop_cli_records_structured_stop_signal(self):
        stop_cli = load_bin_module("stop_ads_pipeline_loop")

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "ads-control.sqlite3")
            with redirect_stdout(io.StringIO()):
                result = stop_cli.main(
                    [
                        "safe_drain_now",
                        "--db-path",
                        db_path,
                        "--requested-by",
                        "fixture",
                        "--reason",
                        "unit test CLI stop",
                        "--metadata-json",
                        '{"scope":"AUTO-004"}',
                    ]
                )

            conn = sqlite3.connect(db_path)
            try:
                control = get_pipeline_control_state(conn, create_default=False)
                signal = read_pipeline_stop_signal(conn, control["metadata"]["stop_signal"]["stop_signal_id"])
            finally:
                conn.close()

        self.assertEqual(result, 0)
        self.assertFalse(control["pipeline_enabled"])
        self.assertEqual(control["default_disable_action"], "safe_drain_now")
        self.assertEqual(control["metadata"]["stop_signal"]["stop_policy"], "safe_drain_now")
        self.assertEqual(control["metadata"]["stop_signal"]["metadata"], {"scope": "AUTO-004"})
        self.assertEqual(signal["signal_status"], "pending")


if __name__ == "__main__":
    unittest.main()
