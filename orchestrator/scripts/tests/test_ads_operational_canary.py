#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_operational_canary import OperationalCanaryConfig, run_one_case_canary, validate_preflight
from predquant.ads_pipeline_runner import ADS_PIPELINE_STAGE_ORDER, PipelineRunnerContractError
from predquant.sqlite_store import SCHEMA


class AdsOperationalCanaryTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seed_market()
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def _seed_market(self):
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
                "operational-canary",
                "operational-canary",
                "Will the operational canary complete?",
                "Synthetic canary market",
                "test",
                "open",
                "binary",
                "2100-01-01T00:00:00+00:00",
                "2100-01-02T00:00:00+00:00",
                "{}",
                0.51,
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
                "2099-12-31T23:55:00+00:00",
                None,
                0.49,
                0.53,
                None,
                None,
                100.0,
                50.0,
                json.dumps({"source": "unit-test"}, sort_keys=True),
            ),
        )

    def config(self, *, require_scoreable_prediction=False):
        return OperationalCanaryConfig(
            db_path=self.db_path,
            runner_mode="fixture",
            forecast_timestamp="2100-01-01T00:00:00+00:00",
            updated_by="unit-test",
            reason="unit-test one-case canary",
            require_scoreable_prediction=require_scoreable_prediction,
            metadata={"test_scope": "operational_canary"},
        )

    def stage_handlers(self):
        def make_handler(stage):
            def handler(**_kwargs):
                result = {
                    "output_artifact_refs": [f"artifact:{stage}"],
                    "validation_result_refs": [f"validation:{stage}"],
                    "safe_metadata": {"stage": stage, "handler_scope": "operational_canary"},
                }
                if stage == "decision":
                    result["forecast_decision_record_id"] = "forecast-decision:operational-canary"
                return result

            return handler

        return {stage: make_handler(stage) for stage in ADS_PIPELINE_STAGE_ORDER[1:]}

    def test_preflight_rejects_missing_handler_stage(self):
        handlers = self.stage_handlers()
        handlers.pop("decision")

        with self.assertRaisesRegex(PipelineRunnerContractError, "missing AUTO-003 stage handlers"):
            validate_preflight(self.conn, self.config(), handlers)

    def test_one_case_canary_runs_once_and_disables_pipeline(self):
        result = run_one_case_canary(self.config(), self.stage_handlers())

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["terminal_status"], "stopped_after_current_case")
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertFalse(result["control_after"]["pipeline_enabled"])
        self.assertEqual(result["active_after"], {"active_runs": 0, "active_leases": 0})
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 0)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ads_case_leases").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM ads_case_leases WHERE lease_status = 'released'").fetchone()[0],
                1,
            )

    def test_scoreable_requirement_fails_without_prediction_bridge_write(self):
        result = run_one_case_canary(self.config(require_scoreable_prediction=True), self.stage_handlers())

        self.assertFalse(result["ok"])
        self.assertIn("scoreable canary expected exactly one market_predictions row", result["errors"])


if __name__ == "__main__":
    unittest.main()
