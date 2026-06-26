#!/usr/bin/env python3
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.training_trace import (
    TRAINING_TRACE_FULL_TABLE,
    TRAINING_TRACE_MINIMAL_TABLE,
    TrainingTraceContext,
    TrainingTraceContractError,
    build_full_training_trace_materialization,
    build_minimal_training_trace,
    build_session5_minimal_training_trace,
    ensure_training_trace_schema,
    validate_minimal_training_trace,
    write_full_training_trace_materialization,
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
                "source_cutoff_timestamp": "2026-06-24T11:59:00+00:00",
            },
            {
                "artifact_id": "artifact:scae",
                "sha256": "sha256:" + "d" * 64,
                "stage": "scae",
                "artifact_type": "scae-ledger",
                "source_cutoff_timestamp": "2026-06-24T11:59:00+00:00",
            },
            {
                "artifact_id": "artifact:decision",
                "sha256": "sha256:" + "e" * 64,
                "stage": "decision",
                "artifact_type": "decision-context",
                "source_cutoff_timestamp": "2026-06-24T11:59:00+00:00",
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

    def test_full_trace_materialization_rejects_hash_or_temporal_leaks(self):
        trace = build_session5_minimal_training_trace(
            context=self.context,
            artifact_manifests=self.session5_manifests(),
            created_at="2026-06-24T12:00:01+00:00",
        )
        broken_hashes = self.session5_manifests()
        broken_hashes[0]["sha256"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(TrainingTraceContractError, "hashes must match"):
            build_full_training_trace_materialization(
                trace_pointer=trace,
                artifact_manifests=broken_hashes,
            )

        future_artifact = self.session5_manifests()
        future_artifact[0]["source_cutoff_timestamp"] = "2026-06-24T12:01:00+00:00"
        with self.assertRaisesRegex(TrainingTraceContractError, "temporal isolation"):
            build_full_training_trace_materialization(
                trace_pointer=trace,
                artifact_manifests=future_artifact,
            )

    def test_full_trace_materialization_is_non_authoritative_and_persisted(self):
        trace = build_session5_minimal_training_trace(
            context=self.context,
            artifact_manifests=self.session5_manifests(),
            created_at="2026-06-24T12:00:01+00:00",
        )
        materialization = build_full_training_trace_materialization(
            trace_pointer=trace,
            artifact_manifests=self.session5_manifests(),
            replay_manifest_refs=["replay-manifest:1"],
            created_at="2026-06-24T12:03:00+00:00",
            metadata={"requested_by": "TRACE-002"},
        )
        materialization_id = write_full_training_trace_materialization(self.conn, materialization)
        write_full_training_trace_materialization(self.conn, materialization)

        self.assertEqual(materialization_id, materialization["trace_materialization_id"])
        row = self.conn.execute(
            f"""
            SELECT trace_materialization_id, trace_id, materialization_status,
                   temporal_leak_check_status, live_authority, live_forecast_authority,
                   artifact_manifest_ids, replay_manifest_refs
            FROM {TRAINING_TRACE_FULL_TABLE}
            WHERE trace_materialization_id = ?
            """,
            (materialization_id,),
        ).fetchone()
        self.assertEqual(row[:6], (materialization_id, trace["trace_id"], "full_materialized", "passed", "none", 0))
        self.assertEqual(json.loads(row[6]), trace["artifact_manifest_ids"])
        self.assertEqual(json.loads(row[7]), ["replay-manifest:1"])


if __name__ == "__main__":
    unittest.main()
