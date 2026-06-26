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
from predquant.ads_manifest_canary_handlers import build_stage_handlers as build_manifest_stage_handlers
from predquant.ads_production_pilot_handlers import build_stage_handlers as build_production_pilot_handlers
from predquant.ads_production_readiness_handlers import build_stage_handlers as build_production_readiness_handlers
from predquant.ads_handoff_report import build_handoff_report
from predquant.ads_scoreable_canary_handlers import build_stage_handlers
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

    def _seed_market(
        self,
        *,
        external_market_id="operational-canary",
        slug="operational-canary",
        title="Will the operational canary complete?",
        best_bid=0.49,
        best_ask=0.53,
    ):
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
                slug,
                title,
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
                best_bid,
                best_ask,
                None,
                None,
                100.0,
                50.0,
                json.dumps({"source": "unit-test"}, sort_keys=True),
            ),
        )

    def config(self, *, require_scoreable_prediction=False, max_cases=1, require_manifest_handoffs=False):
        return OperationalCanaryConfig(
            db_path=self.db_path,
            runner_mode="fixture",
            forecast_timestamp="2100-01-01T00:00:00+00:00",
            max_cases=max_cases,
            updated_by="unit-test",
            reason="unit-test one-case canary",
            require_scoreable_prediction=require_scoreable_prediction,
            require_manifest_handoffs=require_manifest_handoffs,
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
        self.assertTrue(validate_preflight(self.conn, self.config(), self.stage_handlers())["eligible_case_available"])

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
        self.assertIn("scoreable canary expected exactly 1 market_predictions row(s)", result["errors"])

    def test_scoreable_canary_factory_writes_one_prediction(self):
        config = self.config(require_scoreable_prediction=True)
        handlers = build_stage_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        with sqlite3.connect(self.db_path) as conn:
            prediction_source = conn.execute("SELECT prediction_source FROM market_predictions").fetchone()[0]
        self.assertEqual(prediction_source, "ads_pipeline")

    def test_scoreable_canary_factory_runs_bounded_batch(self):
        self._seed_market(
            external_market_id="operational-canary-b",
            slug="operational-canary-b",
            title="Will the second operational canary complete?",
            best_bid=0.58,
            best_ask=0.62,
        )
        self.conn.commit()
        config = self.config(require_scoreable_prediction=True, max_cases=2)
        handlers = build_stage_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["terminal_status"], "auto005_max_cases_complete")
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 2)
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 2)

    def test_manifest_canary_factory_satisfies_strict_handoff_mode(self):
        config = self.config(require_scoreable_prediction=True, require_manifest_handoffs=True)
        handlers = build_manifest_stage_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        with sqlite3.connect(self.db_path) as conn:
            manifest_count = conn.execute("SELECT COUNT(*) FROM case_artifact_manifest").fetchone()[0]
        self.assertGreaterEqual(manifest_count, len(ADS_PIPELINE_STAGE_ORDER))

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertEqual(
            report["manifest_counts_by_validation_status"],
            {"valid": len(ADS_PIPELINE_STAGE_ORDER) - 1},
        )
        self.assertEqual(
            {stage["stage"] for stage in report["stages"]},
            set(ADS_PIPELINE_STAGE_ORDER),
        )

    def test_production_readiness_factory_blocks_prediction_until_research_sufficiency(self):
        config = self.config(require_scoreable_prediction=False, require_manifest_handoffs=True)
        handlers = build_production_readiness_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 0)
        with sqlite3.connect(self.db_path) as conn:
            decision = conn.execute(
                """
                SELECT production_persistence_status, production_forecast_persisted,
                       scoreable_forecast_output, non_scoreable_reason_code
                FROM forecast_decision_records
                """
            ).fetchone()
            self.assertEqual(decision[0], "blocked_invalid_scae_forecast")
            self.assertEqual(decision[1], 0)
            self.assertEqual(decision[2], 0)
            self.assertEqual(decision[3], "forecast_validity_invalid_for_forecast")

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertGreaterEqual(report["manifest_counts_by_validation_status"].get("valid", 0), len(ADS_PIPELINE_STAGE_ORDER))

    def test_production_pilot_factory_writes_scoreable_prediction_with_manifest_handoffs(self):
        config = self.config(require_scoreable_prediction=True, require_manifest_handoffs=True)
        handlers = build_production_pilot_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["completed_stage_count"], len(ADS_PIPELINE_STAGE_ORDER))
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 1)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 1)
        with sqlite3.connect(self.db_path) as conn:
            decision = conn.execute(
                """
                SELECT production_persistence_status, production_forecast_persisted,
                       production_forecast_prob, non_scoreable_reason_code
                FROM forecast_decision_records
                """
            ).fetchone()
            prediction = conn.execute(
                """
                SELECT prediction_source, prediction_label, predicted_probability
                FROM market_predictions
                """
            ).fetchone()
            self.assertEqual(decision[0], "production_forecast_persisted_from_scae")
            self.assertEqual(decision[1], 1)
            self.assertIsNotNone(decision[2])
            self.assertIsNone(decision[3])
            self.assertEqual(prediction[0], "ads_pipeline")
            self.assertEqual(prediction[1], "v2_scae")
            self.assertIsNotNone(prediction[2])

        report = build_handoff_report(self.db_path)
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertGreaterEqual(
            report["manifest_counts_by_validation_status"].get("valid", 0),
            len(ADS_PIPELINE_STAGE_ORDER),
        )

    def test_production_pilot_factory_runs_bounded_batch(self):
        self._seed_market(
            external_market_id="operational-pilot-b",
            slug="operational-pilot-b",
            title="Will the second production pilot complete?",
            best_bid=0.58,
            best_ask=0.62,
        )
        self.conn.commit()
        config = self.config(require_scoreable_prediction=True, max_cases=2, require_manifest_handoffs=True)
        handlers = build_production_pilot_handlers(
            db_path=config.db_path,
            runner_mode=config.runner_mode,
            forecast_timestamp=config.forecast_timestamp,
            max_cases=config.max_cases,
            metadata=config.metadata,
        )

        result = run_one_case_canary(config, handlers)

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["result"]["terminal_status"], "auto005_max_cases_complete")
        self.assertEqual(result["protected_count_deltas"]["forecast_decision_records"], 2)
        self.assertEqual(result["protected_count_deltas"]["market_predictions"], 2)


if __name__ == "__main__":
    unittest.main()
