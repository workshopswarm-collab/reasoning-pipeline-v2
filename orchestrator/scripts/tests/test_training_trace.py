#!/usr/bin/env python3
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.training_trace import (
    TRAINING_TRACE_MINIMAL_TABLE,
    TrainingTraceContext,
    TrainingTraceContractError,
    build_minimal_training_trace,
    build_session5_minimal_training_trace,
    ensure_training_trace_schema,
    validate_minimal_training_trace,
    write_minimal_training_trace,
    write_session5_minimal_training_trace,
)


class TrainingTraceTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.context = TrainingTraceContext(
            case_id="case-1",
            case_key="case:key:1",
            dispatch_id="dispatch-1",
            run_id="run-1",
            forecast_timestamp="2026-06-24T12:00:00+00:00",
        )
        self.manifests = [
            {"artifact_id": "artifact:case", "sha256": "sha256:" + "a" * 64},
            {"artifact_id": "artifact:scae", "artifact_sha256": "sha256:" + "b" * 64},
        ]

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

    def test_trace_requires_artifact_pointers_and_hashes(self):
        with self.assertRaisesRegex(TrainingTraceContractError, "at least one manifest pointer"):
            build_minimal_training_trace(context=self.context, artifact_manifests=[])

        broken = [{"artifact_id": "artifact:missing-hash"}]
        with self.assertRaisesRegex(TrainingTraceContractError, "sha256 is required"):
            build_minimal_training_trace(context=self.context, artifact_manifests=broken)

    def test_trace_is_non_authoritative_and_rejects_replacement_probability(self):
        trace = build_minimal_training_trace(context=self.context, artifact_manifests=self.manifests)

        self.assertEqual(trace["live_authority"], "none")
        self.assertFalse(trace["live_forecast_authority"])
        self.assertEqual(trace["trace_status"], "minimal_pointer_written")
        self.assertEqual(set(trace["artifact_hashes"]), set(trace["artifact_manifest_ids"]))

        invalid = dict(trace)
        invalid["replacement_probability"] = 0.74
        with self.assertRaisesRegex(TrainingTraceContractError, "replacement_probability"):
            validate_minimal_training_trace(invalid)

        with self.assertRaisesRegex(TrainingTraceContractError, "replacement_probability"):
            build_minimal_training_trace(
                context=self.context,
                artifact_manifests=self.manifests,
                metadata={"replacement_probability": 0.74},
            )

    def test_session5_trace_requires_research_scae_and_decision_artifact_refs(self):
        with self.assertRaisesRegex(TrainingTraceContractError, "decision"):
            build_session5_minimal_training_trace(
                context=self.context,
                artifact_manifests=self.session5_manifests()[:-1],
            )

        broken = self.session5_manifests()
        broken[0]["payload"] = {"production_forecast_prob": 0.61}
        with self.assertRaisesRegex(TrainingTraceContractError, "production_forecast_prob"):
            build_session5_minimal_training_trace(context=self.context, artifact_manifests=broken)

    def test_session5_trace_metadata_records_required_roles_without_authority(self):
        trace = build_session5_minimal_training_trace(
            context=self.context,
            artifact_manifests=self.session5_manifests(),
            metadata={"handoff_surface": "session5"},
        )

        validate_minimal_training_trace(trace)
        self.assertEqual(trace["live_authority"], "none")
        self.assertFalse(trace["live_forecast_authority"])
        self.assertEqual(trace["materialization_status"], "not_materialized")
        handoff = trace["metadata"]["session5_handoff"]
        self.assertTrue(handoff["non_authoritative"])
        self.assertTrue(handoff["no_production_probability_authoring"])
        self.assertTrue(handoff["no_replay_scoring_or_calibration_writes"])
        self.assertEqual(set(handoff["artifact_role_refs"]), {"research", "scae", "decision"})
        self.assertEqual(
            handoff["artifact_role_refs"]["scae"],
            [{"artifact_id": "artifact:scae", "sha256": "sha256:" + "d" * 64}],
        )
        self.assertEqual(trace["metadata"]["caller_metadata"], {"handoff_surface": "session5"})

    def test_persistence_writes_only_trace_pointer_table(self):
        protected_tables = (
            "retrieval_evidence_items",
            "scae_ledger_outputs",
            "synthesis_context_records",
            "forecast_decision_records",
            "market_predictions",
            "pipeline_replay_manifests",
            "v2_replay_manifests",
            "pipeline_replay_result_records",
            "v2_replay_result_records",
            "outcome_scoring_records",
            "evaluator_scorecards",
            "calibration_candidate_records",
            "training_trace_full_materializations",
        )
        for table in protected_tables:
            self.conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, marker TEXT NOT NULL)")
            self.conn.execute(f"INSERT INTO {table} (id, marker) VALUES (?, ?)", (f"{table}:1", "unchanged"))
        before = {
            table: self.conn.execute(f"SELECT COUNT(*), MIN(marker), MAX(marker) FROM {table}").fetchone()
            for table in protected_tables
        }

        trace = build_session5_minimal_training_trace(context=self.context, artifact_manifests=self.session5_manifests())
        trace_id = write_minimal_training_trace(self.conn, trace)

        self.assertEqual(trace_id, trace["trace_id"])
        self.assertEqual(
            self.conn.execute(f"SELECT COUNT(*) FROM {TRAINING_TRACE_MINIMAL_TABLE}").fetchone()[0],
            1,
        )
        for table, prior in before.items():
            with self.subTest(table=table):
                self.assertEqual(
                    self.conn.execute(f"SELECT COUNT(*), MIN(marker), MAX(marker) FROM {table}").fetchone(),
                    prior,
                )

    def test_session5_write_uses_fnd_pointer_persistence(self):
        trace_id = write_session5_minimal_training_trace(
            self.conn,
            context=self.context,
            artifact_manifests=self.session5_manifests(),
        )

        row = self.conn.execute(
            f"SELECT trace_id, trace_status, live_authority, live_forecast_authority FROM {TRAINING_TRACE_MINIMAL_TABLE}"
        ).fetchone()
        self.assertEqual(row, (trace_id, "minimal_pointer_written", "none", 0))

    def test_persisted_pointer_keeps_minimal_contract_fields(self):
        ensure_training_trace_schema(self.conn)
        trace = build_minimal_training_trace(context=self.context, artifact_manifests=self.manifests)
        write_minimal_training_trace(self.conn, trace)

        row = self.conn.execute(
            f"""
            SELECT trace_id, case_id, dispatch_id, run_id, forecast_timestamp,
                   artifact_manifest_ids, artifact_hashes, trace_status,
                   live_authority, live_forecast_authority, materialization_status
            FROM {TRAINING_TRACE_MINIMAL_TABLE}
            WHERE trace_id = ?
            """,
            (trace["trace_id"],),
        ).fetchone()

        self.assertEqual(row[:5], (trace["trace_id"], "case-1", "dispatch-1", "run-1", "2026-06-24T12:00:00+00:00"))
        self.assertEqual(json.loads(row[5]), trace["artifact_manifest_ids"])
        self.assertEqual(json.loads(row[6]), trace["artifact_hashes"])
        self.assertEqual(row[7:], ("minimal_pointer_written", "none", 0, "not_materialized"))


if __name__ == "__main__":
    unittest.main()
