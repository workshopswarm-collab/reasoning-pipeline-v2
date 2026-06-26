#!/usr/bin/env python3
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.replay import (
    FIRST100_COHORT_LIMIT,
    FIRST100_REPLAY_SCOPE,
    REPLAY_MANIFEST_TABLE,
    REPLAY_RESULT_TABLE,
    ReplayContractError,
    build_first100_replay_manifest,
    build_first100_replay_manifests,
    build_replay_result_record,
    validate_replay_manifest,
    validate_replay_result_record,
    write_replay_manifest,
    write_replay_result_record,
)
from predquant.training_trace import TrainingTraceContext, build_session5_minimal_training_trace


class ReplayContractTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.context = TrainingTraceContext(
            case_id="case-1",
            case_key="case:key:1",
            dispatch_id="dispatch-1",
            run_id="run-1",
            forecast_timestamp="2026-06-24T12:00:00+00:00",
        )

    def tearDown(self):
        self.conn.close()

    def session5_manifests(self):
        return [
            {
                "artifact_id": "artifact:research",
                "sha256": "sha256:" + "c" * 64,
                "stage": "researcher_classification",
                "artifact_type": "researcher-sidecar",
            },
            {
                "artifact_id": "artifact:scae",
                "sha256": "sha256:" + "d" * 64,
                "stage": "scae",
                "artifact_type": "scae-ledger",
            },
            {
                "artifact_id": "artifact:decision",
                "sha256": "sha256:" + "e" * 64,
                "stage": "decision",
                "artifact_type": "decision-context",
            },
        ]

    def trace_pointer(self, trace_id="trace:1"):
        return build_session5_minimal_training_trace(
            context=self.context,
            artifact_manifests=self.session5_manifests(),
            trace_id=trace_id,
            created_at="2026-06-24T12:00:01+00:00",
        )

    def replay_manifest(self):
        return build_first100_replay_manifest(
            trace_pointer=self.trace_pointer(),
            replay_cohort_id="first100:direct-cutover:test",
            cohort_sequence=1,
            replay_command="python3 orchestrator/scripts/bin/run_golden_fixture.py --stage replay_record",
            created_at="2026-06-24T12:00:02+00:00",
            metadata={"requested_by": "REPLAY-001"},
        )

    def test_first100_manifest_uses_trace_pointer_refs_and_has_no_live_authority(self):
        trace = self.trace_pointer()
        manifest = self.replay_manifest()

        validate_replay_manifest(manifest)
        self.assertEqual(manifest["table"], REPLAY_MANIFEST_TABLE)
        self.assertEqual(manifest["replay_scope"], FIRST100_REPLAY_SCOPE)
        self.assertEqual(manifest["cohort_limit"], FIRST100_COHORT_LIMIT)
        self.assertEqual(manifest["trace_id"], trace["trace_id"])
        self.assertEqual(manifest["trace_artifact_manifest_ids"], trace["artifact_manifest_ids"])
        self.assertEqual(manifest["trace_artifact_hashes"], trace["artifact_hashes"])
        self.assertEqual(manifest["live_authority"], "none")
        self.assertFalse(manifest["live_forecast_authority"])
        self.assertFalse(manifest["production_write_authority"])
        self.assertFalse(manifest["calibration_policy_promotion_authority"])
        self.assertFalse(manifest["full_trace_materialization_authority"])
        self.assertIn("production_forecast_write", manifest["forbidden_uses"])
        self.assertIn("probability_replacement", manifest["forbidden_uses"])

    def test_manifest_rejects_authoritative_or_materialized_trace_inputs(self):
        trace = self.trace_pointer()
        trace["live_forecast_authority"] = True
        with self.assertRaisesRegex(ReplayContractError, "live forecast authority"):
            build_first100_replay_manifest(
                trace_pointer=trace,
                replay_cohort_id="first100:direct-cutover:test",
                cohort_sequence=1,
            )

        trace = self.trace_pointer()
        trace["materialization_status"] = "full_materialized"
        with self.assertRaisesRegex(ReplayContractError, "materialization_status"):
            build_first100_replay_manifest(
                trace_pointer=trace,
                replay_cohort_id="first100:direct-cutover:test",
                cohort_sequence=1,
            )

        with self.assertRaisesRegex(ReplayContractError, "cohort_sequence"):
            build_first100_replay_manifest(
                trace_pointer=self.trace_pointer(),
                replay_cohort_id="first100:direct-cutover:test",
                cohort_sequence=101,
            )

        with self.assertRaisesRegex(ReplayContractError, "production_forecast_prob"):
            build_first100_replay_manifest(
                trace_pointer=self.trace_pointer(),
                replay_cohort_id="first100:direct-cutover:test",
                cohort_sequence=1,
                metadata={"production_forecast_prob": 0.61},
            )

    def test_batch_builder_caps_first100_cohort_and_assigns_sequences(self):
        traces = [self.trace_pointer(trace_id=f"trace:{idx}") for idx in range(1, 4)]
        manifests = build_first100_replay_manifests(
            trace_pointers=traces,
            replay_cohort_id="first100:direct-cutover:test",
            created_at="2026-06-24T12:00:02+00:00",
        )

        self.assertEqual([manifest["cohort_sequence"] for manifest in manifests], [1, 2, 3])
        self.assertEqual({manifest["cohort_limit"] for manifest in manifests}, {100})

        too_many = [self.trace_pointer(trace_id=f"trace:{idx}") for idx in range(101)]
        with self.assertRaisesRegex(ReplayContractError, "more than 100"):
            build_first100_replay_manifests(
                trace_pointers=too_many,
                replay_cohort_id="first100:direct-cutover:test",
            )

    def test_result_record_is_ref_only_and_rejects_scoring_fields(self):
        result = build_replay_result_record(
            replay_manifest=self.replay_manifest(),
            replay_attempt_id="attempt-1",
            result_status="scoring_ref_available",
            replay_started_at="2026-06-24T12:01:00+00:00",
            replay_completed_at="2026-06-24T12:02:00+00:00",
            replay_output_artifact_ref="artifact:replay-output",
            replay_output_hash="sha256:" + "f" * 64,
            outcome_ref="outcome:market-1",
            scorecard_artifact_ref="artifact:scorecard-ref",
            safe_message="ref-only result contract",
            created_at="2026-06-24T12:02:01+00:00",
        )

        validate_replay_result_record(result)
        self.assertEqual(result["table"], REPLAY_RESULT_TABLE)
        self.assertEqual(result["live_authority"], "none")
        self.assertFalse(result["production_write_authority"])
        self.assertFalse(result["probability_replacement_authority"])
        self.assertIn("brier_clearance", result["forbidden_uses"])
        self.assertEqual(result["outcome_ref"], "outcome:market-1")
        self.assertEqual(result["scorecard_artifact_ref"], "artifact:scorecard-ref")

        invalid = dict(result)
        invalid["prediction_brier"] = 0.08
        with self.assertRaisesRegex(ReplayContractError, "prediction_brier"):
            validate_replay_result_record(invalid)

        with self.assertRaisesRegex(ReplayContractError, "market_brier"):
            build_replay_result_record(
                replay_manifest=self.replay_manifest(),
                replay_attempt_id="attempt-2",
                result_status="outcome_pending",
                metadata={"market_brier": 0.1},
            )

        with self.assertRaisesRegex(ReplayContractError, "scoring_ref_available"):
            build_replay_result_record(
                replay_manifest=self.replay_manifest(),
                replay_attempt_id="attempt-3",
                result_status="scoring_ref_available",
            )

    def test_persistence_writes_only_replay_surfaces(self):
        protected_tables = (
            "training_trace_minimal_pointers",
            "training_trace_full_materializations",
            "forecast_decision_records",
            "market_predictions",
            "pipeline_replay_manifests",
            "pipeline_replay_result_records",
            "outcome_scoring_records",
            "evaluator_scorecards",
            "calibration_candidate_records",
            "calibration_lane_pointer_records",
        )
        for table in protected_tables:
            if table == "training_trace_full_materializations":
                self.conn.execute(
                    f"""
                    CREATE TABLE {table} (
                      id TEXT PRIMARY KEY,
                      marker TEXT NOT NULL,
                      case_id TEXT,
                      run_id TEXT,
                      trace_id TEXT,
                      materialization_status TEXT
                    )
                    """
                )
            else:
                self.conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, marker TEXT NOT NULL)")
            self.conn.execute(f"INSERT INTO {table} (id, marker) VALUES (?, ?)", (f"{table}:1", "unchanged"))
        before = {
            table: self.conn.execute(f"SELECT COUNT(*), MIN(marker), MAX(marker) FROM {table}").fetchone()
            for table in protected_tables
        }

        manifest = self.replay_manifest()
        manifest_id = write_replay_manifest(self.conn, manifest)
        result = build_replay_result_record(
            replay_manifest=manifest,
            replay_attempt_id="attempt-1",
            result_status="outcome_pending",
            replay_output_hash="sha256:" + "f" * 64,
            created_at="2026-06-24T12:02:01+00:00",
        )
        result_id = write_replay_result_record(self.conn, result)

        self.assertEqual(manifest_id, manifest["replay_manifest_id"])
        self.assertEqual(result_id, result["replay_result_id"])
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {REPLAY_MANIFEST_TABLE}").fetchone()[0], 1)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {REPLAY_RESULT_TABLE}").fetchone()[0], 1)
        for table, prior in before.items():
            with self.subTest(table=table):
                self.assertEqual(
                    self.conn.execute(f"SELECT COUNT(*), MIN(marker), MAX(marker) FROM {table}").fetchone(),
                    prior,
                )

    def test_persisted_records_are_idempotent_and_json_encoded(self):
        manifest = self.replay_manifest()
        write_replay_manifest(self.conn, manifest)
        write_replay_manifest(self.conn, manifest)
        row = self.conn.execute(
            f"""
            SELECT replay_cohort_id, cohort_sequence, trace_artifact_manifest_ids,
                   trace_artifact_hashes, live_authority, live_forecast_authority,
                   production_write_authority, calibration_policy_promotion_authority
            FROM {REPLAY_MANIFEST_TABLE}
            WHERE replay_manifest_id = ?
            """,
            (manifest["replay_manifest_id"],),
        ).fetchone()
        self.assertEqual(row[:2], ("first100:direct-cutover:test", 1))
        self.assertEqual(json.loads(row[2]), manifest["trace_artifact_manifest_ids"])
        self.assertEqual(json.loads(row[3]), manifest["trace_artifact_hashes"])
        self.assertEqual(row[4:], ("none", 0, 0, 0))

        result = build_replay_result_record(
            replay_manifest=manifest,
            replay_attempt_id="attempt-1",
            result_status="outcome_pending",
            replay_output_hash="sha256:" + "f" * 64,
            created_at="2026-06-24T12:02:01+00:00",
        )
        write_replay_result_record(self.conn, result)
        write_replay_result_record(self.conn, result)
        self.assertEqual(
            self.conn.execute(
                f"SELECT COUNT(*) FROM {REPLAY_RESULT_TABLE} WHERE replay_result_id = ?",
                (result["replay_result_id"],),
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
