#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCAE_SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_SCRIPTS = REPO_ROOT / "orchestrator" / "scripts"
sys.path.insert(0, str(ORCHESTRATOR_SCRIPTS))
sys.path.insert(0, str(SCAE_SCRIPTS))

from predquant.sqlite_store import record_prediction_with_snapshot, write_resolution_score  # noqa: E402

SCRIPT_PATH = SCAE_SCRIPTS / "bin" / "report_scae_scorecard.py"
SPEC = importlib.util.spec_from_file_location("report_scae_scorecard", SCRIPT_PATH)
assert SPEC and SPEC.loader
report_scae_scorecard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report_scae_scorecard)


class ScaeScorecardCliTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "predquant.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_cli_defaults_to_scae_prediction_rows(self):
        record_prediction_with_snapshot(
            db_path=self.db_path,
            payload={
                "platform": "polymarket",
                "external_market_id": "market-scae-scorecard",
                "title": "Will the SCAE scorecard CLI pass?",
                "status": "open",
                "snapshot": {
                    "observed_at": "2026-01-01T00:00:00+00:00",
                    "best_bid": 0.4,
                    "best_ask": 0.5,
                    "raw_payload": {"book": "scorecard"},
                },
            },
            predicted_probability=0.65,
            prediction_run_id="run-scae-scorecard",
            forecast_artifact_id="forecast-scae-scorecard",
            case_key="polymarket:market-scae-scorecard",
            case_id="case-scae-scorecard",
            dispatch_id="dispatch-scae-scorecard",
            engine_stage="scae",
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
            predicted_at="2026-01-01T00:01:00+00:00",
            metadata={"forecast_decision_id": "decision-scae-scorecard"},
        )
        write_resolution_score(
            db_path=self.db_path,
            external_market_id="market-scae-scorecard",
            outcome=1.0,
            resolution_source="polymarket-resolution-sync",
            resolution_payload={"result": "yes"},
            prediction_source="ads_pipeline",
            prediction_label="v2_scae",
            write_scorecards=False,
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = report_scae_scorecard.main(
                ["--db-path", str(self.db_path), "--write-scorecards"]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["feature_id"], "SCORE-001")
        self.assertEqual(payload["prediction_source"], "ads_pipeline")
        self.assertEqual(payload["prediction_label"], "v2_scae")
        self.assertEqual(payload["scorecard_write"]["written_scorecards"], 1)
        self.assertEqual(payload["scorecards"]["scorecards"], 1)


if __name__ == "__main__":
    unittest.main()
