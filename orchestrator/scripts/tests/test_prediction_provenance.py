#!/usr/bin/env python3
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import (
    BRIER_SCORING_VERSION,
    brier_score_report,
    payload_hash,
    record_prediction_with_snapshot,
    settle_market_outcome,
)


class PredictionProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def payload(self, external_market_id="market-1"):
        return {
            "platform": "polymarket",
            "external_market_id": external_market_id,
            "slug": "test-market",
            "title": "Will the test pass?",
            "status": "open",
            "snapshot": {
                "observed_at": "2026-01-01T00:00:00+00:00",
                "best_bid": 0.4,
                "best_ask": 0.5,
                "raw_payload": {"book": "fixture"},
            },
        }

    def fetch_one(self, query, params=()):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(query, params).fetchone()
        finally:
            conn.close()

    def fetch_scalar(self, query):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(query).fetchone()[0]
        finally:
            conn.close()

    def record_prediction(self, **overrides):
        args = {
            "db_path": self.db_path,
            "payload": self.payload(),
            "predicted_probability": 0.65,
            "prediction_run_id": "run-1",
            "forecast_artifact_id": "forecast-1",
            "case_key": "polymarket:market-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "engine_stage": "prediction-engine",
            "prediction_source": "pipeline",
            "prediction_label": "engine-v0",
            "predicted_at": "2026-01-01T00:01:00+00:00",
            "code_version": "abc123",
            "model_name": "model-fixture",
            "prompt_version": "prompt-v1",
            "input_hash": "input-sha",
            "input_artifact_path": "artifacts/input.json",
            "input_artifact_sha256": "input-artifact-sha",
            "prediction_artifact_path": "artifacts/prediction.json",
            "prediction_artifact_sha256": "prediction-artifact-sha",
            "metadata": {"pipeline": "fixture"},
        }
        args.update(overrides)
        return record_prediction_with_snapshot(**args)

    def test_prediction_provenance_is_idempotent_and_scored(self):
        result = self.record_prediction()

        self.assertEqual(result["prediction_run_id"], "run-1")
        self.assertEqual(result["forecast_artifact_id"], "forecast-1")
        self.assertEqual(result["snapshot_age_seconds"], 60.0)
        self.assertEqual(result["market_probability_method"], "bid_ask_midpoint")
        self.assertAlmostEqual(result["market_probability"], 0.45)

        row = self.fetch_one("SELECT * FROM market_predictions WHERE id = ?", (result["prediction_id"],))
        self.assertEqual(row["case_key"], "polymarket:market-1")
        self.assertEqual(row["case_id"], "case-1")
        self.assertEqual(row["dispatch_id"], "dispatch-1")
        self.assertEqual(row["engine_stage"], "prediction-engine")
        self.assertEqual(row["input_artifact_path"], "artifacts/input.json")
        self.assertEqual(row["input_artifact_sha256"], "input-artifact-sha")
        self.assertEqual(row["prediction_artifact_path"], "artifacts/prediction.json")
        self.assertEqual(row["prediction_artifact_sha256"], "prediction-artifact-sha")
        self.assertEqual(row["source_payload_hash"], payload_hash(self.payload()))

        retry = self.record_prediction()
        self.assertTrue(retry["idempotent"])
        self.assertEqual(retry["prediction_id"], result["prediction_id"])
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM market_predictions"), 1)
        self.assertEqual(self.fetch_scalar("SELECT COUNT(*) FROM market_snapshots"), 1)

        with self.assertRaisesRegex(ValueError, "predicted_probability"):
            self.record_prediction(predicted_probability=0.66)
        with self.assertRaisesRegex(ValueError, "case_id"):
            self.record_prediction(case_id="case-2")

        resolution_payload = {"result": "yes", "source_id": "resolution-fixture"}
        settled = settle_market_outcome(
            db_path=self.db_path,
            external_market_id="market-1",
            outcome=1.0,
            resolved_at="2026-01-02T00:00:00+00:00",
            resolution_source="polymarket-resolution-sync",
            resolution_payload=resolution_payload,
            resolution_method="api",
        )
        self.assertEqual(settled["updated_predictions"], 1)

        scored = self.fetch_one(
            "SELECT * FROM market_predictions WHERE id = ?",
            (result["prediction_id"],),
        )
        self.assertAlmostEqual(scored["prediction_brier"], (0.65 - 1.0) ** 2)
        self.assertAlmostEqual(scored["market_brier"], (0.45 - 1.0) ** 2)
        self.assertEqual(scored["scoring_version"], BRIER_SCORING_VERSION)
        self.assertIsNotNone(scored["scored_at"])
        self.assertEqual(scored["scoring_resolution_source"], "polymarket-resolution-sync")
        self.assertEqual(scored["scoring_resolution_payload_hash"], payload_hash(resolution_payload))

        report = brier_score_report(self.db_path)
        self.assertEqual(report["overall"]["scoring_versions"], BRIER_SCORING_VERSION)

    def test_stale_market_snapshot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "market snapshot is stale"):
            self.record_prediction(
                payload=self.payload("stale-market"),
                prediction_run_id="run-stale",
                forecast_artifact_id="forecast-stale",
                predicted_at="2026-01-01T02:01:00+00:00",
                max_snapshot_age_seconds=3600,
            )


if __name__ == "__main__":
    unittest.main()
