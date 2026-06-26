#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_live_readiness import build_live_readiness_report
from predquant.sqlite_store import SCHEMA


class AdsLiveReadinessTest(unittest.TestCase):
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
                "live-readiness",
                "live-readiness",
                "Will ADS live readiness pass?",
                "Synthetic readiness market",
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

    def test_production_readiness_handler_passes_non_scoreable_gate(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_readiness_handlers:build_stage_handlers",
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["status"], "ready")
        self.assertFalse(report["require_scoreable_live"])
        self.assertFalse(report["calibration_debt_report"]["clears_calibration_debt"])

    def test_canary_handler_is_blocked_without_explicit_allowance(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_scoreable_canary_handlers:build_stage_handlers",
        )

        self.assertFalse(report["ok"])
        self.assertIn("canary_handler_factory_not_allowed", report["issues"])

    def test_scoreable_gate_blocks_non_scoreable_readiness_handler(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_readiness_handlers:build_stage_handlers",
            require_scoreable_live=True,
        )

        self.assertFalse(report["ok"])
        self.assertIn("production_readiness_handler_is_non_scoreable", report["issues"])
        self.assertIn("calibration_debt_not_cleared", report["issues"])

    def test_scoreable_gate_blocks_production_pilot_without_debt_canary_allowance(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            requested_max_cases=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("calibration_debt_not_cleared", report["issues"])

    def test_scoreable_gate_allows_bounded_production_pilot_debt_canary(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=1,
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertTrue(report["allow_calibration_debt_scoreable_canary"])
        self.assertEqual(report["requested_max_cases"], 1)

    def test_scoreable_gate_blocks_overlarge_debt_canary_batch(self):
        report = build_live_readiness_report(
            self.db_path,
            runner_mode="calibration_debt_production",
            handler_factory="predquant.ads_production_pilot_handlers:build_stage_handlers",
            require_scoreable_live=True,
            allow_calibration_debt_scoreable_canary=True,
            requested_max_cases=3,
            max_calibration_debt_canary_cases=2,
        )

        self.assertFalse(report["ok"])
        self.assertIn("calibration_debt_scoreable_canary_exceeds_case_limit", report["issues"])


if __name__ == "__main__":
    unittest.main()
