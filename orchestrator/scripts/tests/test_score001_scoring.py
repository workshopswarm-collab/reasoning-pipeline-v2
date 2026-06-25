#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import (
    CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID,
    SCORE001_REPORT_SCHEMA_VERSION,
    brier_score_report,
    record_prediction_with_snapshot,
    write_evaluator_scorecard,
    write_resolution_score,
)


class Score001ScoringTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def payload(self, external_market_id="market-1"):
        return {
            "platform": "polymarket",
            "external_market_id": external_market_id,
            "slug": external_market_id,
            "title": "Will SCORE-001 pass?",
            "status": "open",
            "snapshot": {
                "observed_at": "2026-01-01T00:00:00+00:00",
                "best_bid": 0.4,
                "best_ask": 0.5,
                "raw_payload": {"book": external_market_id},
            },
        }

    def record_scae_prediction(self, external_market_id="market-1"):
        return record_prediction_with_snapshot(
            db_path=self.db_path,
            payload=self.payload(external_market_id),
            predicted_probability=0.65,
            prediction_run_id=f"run-{external_market_id}",
            forecast_artifact_id=f"forecast-{external_market_id}",
            case_key=f"polymarket:{external_market_id}",
            case_id=f"case-{external_market_id}",
            dispatch_id=f"dispatch-{external_market_id}",
            engine_stage="scae",
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
            predicted_at="2026-01-01T00:01:00+00:00",
            input_artifact_path="artifacts/scae-ledger.json",
            input_artifact_sha256="sha256:ledger",
            prediction_artifact_path="artifacts/forecast-decision.json",
            prediction_artifact_sha256="sha256:decision",
            metadata={"forecast_decision_id": f"decision-{external_market_id}"},
        )

    def fetch_one(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(query, params).fetchone()
        finally:
            conn.close()

    def test_resolution_score_writes_market_baseline_scorecard_and_report(self):
        prediction = self.record_scae_prediction()

        score = write_resolution_score(
            db_path=self.db_path,
            external_market_id="market-1",
            outcome=1.0,
            resolved_at="2026-01-02T00:00:00+00:00",
            resolution_source="polymarket-resolution-sync",
            resolution_payload={"result": "yes", "source_id": "resolution-fixture"},
            resolution_method="api",
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
        )

        self.assertEqual(score["feature_id"], "SCORE-001")
        self.assertFalse(score["calibration_policy_promotion_authority"])
        self.assertFalse(score["production_forecast_write_authority"])
        self.assertFalse(score["scae_probability_rewrite_authority"])
        self.assertEqual(score["scorecards"]["written_scorecards"], 1)

        scorecard = self.fetch_one("SELECT * FROM evaluator_scorecards")
        self.assertEqual(scorecard["evaluation_cluster_id"], CALIBRATION_DEBT_CLEARANCE_CLUSTER_ID)
        self.assertEqual(scorecard["forecast_decision_id"], "decision-market-1")
        self.assertEqual(scorecard["reliability_bucket"], "p60_70")
        self.assertAlmostEqual(scorecard["prediction_brier"], (0.65 - 1.0) ** 2)
        self.assertAlmostEqual(scorecard["market_brier"], (0.45 - 1.0) ** 2)
        self.assertAlmostEqual(
            scorecard["resolution_component"],
            (0.45 - 1.0) ** 2 - (0.65 - 1.0) ** 2,
        )

        metadata = json.loads(scorecard["metadata"])
        self.assertEqual(metadata["prediction_id"], prediction["prediction_id"])
        self.assertEqual(metadata["market_snapshot_id"], prediction["snapshot_id"])
        self.assertEqual(metadata["prediction_run_id"], "run-market-1")
        self.assertEqual(metadata["forecast_artifact_id"], "forecast-market-1")
        self.assertEqual(metadata["market_probability_method"], "bid_ask_midpoint")
        self.assertEqual(metadata["resolution_source"], "polymarket-resolution-sync")
        self.assertFalse(metadata["calibration_policy_promotion_authority"])
        self.assertFalse(metadata["production_forecast_write_authority"])
        self.assertFalse(metadata["scae_probability_rewrite_authority"])
        self.assertIn("calibration_policy_promotion", metadata["forbidden_uses"])

        retry = write_evaluator_scorecard(self.db_path, prediction["prediction_id"])
        self.assertTrue(retry["idempotent"])
        self.assertEqual(retry["scorecard_id"], scorecard["scorecard_id"])

        report = brier_score_report(
            self.db_path,
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
        )
        self.assertEqual(report["schema_version"], SCORE001_REPORT_SCHEMA_VERSION)
        self.assertEqual(report["feature_id"], "SCORE-001")
        self.assertEqual(report["overall"]["scored_predictions"], 1)
        self.assertEqual(report["overall"]["scored_predictions_with_market_baseline"], 1)
        self.assertEqual(report["overall"]["scoreable_resolution_records"], 1)
        self.assertAlmostEqual(report["overall"]["avg_brier_edge"], metadata["brier_edge"])
        self.assertEqual(report["scorecards"]["scorecards"], 1)
        self.assertEqual(report["by_reliability_bucket"][0]["reliability_bucket"], "p60_70")

    def test_scorecard_rejects_unscored_prediction(self):
        prediction = self.record_scae_prediction("market-unscored")

        with self.assertRaisesRegex(ValueError, "must be scored"):
            write_evaluator_scorecard(self.db_path, prediction["prediction_id"])


if __name__ == "__main__":
    unittest.main()
