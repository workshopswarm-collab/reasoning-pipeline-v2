#!/usr/bin/env python3
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_stage_logging import (
    FAILURE_PATTERN_GROUP_TABLE,
    PIPELINE_ERROR_EVENT_TABLE,
    STAGE_EXECUTION_EVENT_TABLE,
    STAGE_STATUS_TABLE,
    StageContext,
    StageContractError,
    build_pipeline_error_event,
    build_stage_execution_event,
    build_stage_status_snapshot,
    command_sha256,
    validate_pipeline_error_event,
    validate_stage_execution_event,
    validate_stage_status_snapshot,
    validate_stage,
    validate_transition,
    write_pipeline_error_event,
)


class AdsStageLoggingTest(unittest.TestCase):
    def context(self, stage="retrieval"):
        return StageContext(
            case_id="case-1",
            case_key="polymarket:market-1",
            dispatch_id="dispatch-1",
            stage=stage,
            stage_attempt_id="stage-attempt-1",
            pipeline_run_id="ads-pipeline-run-1",
            case_lease_id="ads-case-lease-1",
        )

    def test_unknown_stage_is_rejected(self):
        with self.assertRaisesRegex(StageContractError, "unknown stage"):
            validate_stage("swarm")

        with self.assertRaisesRegex(StageContractError, "unknown stage"):
            build_stage_status_snapshot(
                context=self.context("swarm"),
                status="running",
                replay_command="python3 run.py",
            )

    def test_illegal_status_transition_is_rejected(self):
        validate_transition("not_started", "running")
        validate_transition("running", "complete")

        with self.assertRaisesRegex(StageContractError, "illegal stage transition"):
            validate_transition("not_started", "complete")

        with self.assertRaisesRegex(StageContractError, "illegal stage transition"):
            validate_transition("complete", "running")

    def test_stage_status_snapshot_preserves_artifact_refs(self):
        record = build_stage_status_snapshot(
            context=self.context("decomposition"),
            status="complete",
            started_at="2026-06-24T18:00:00+00:00",
            completed_at="2026-06-24T18:01:00+00:00",
            duration_ms=60000,
            input_artifacts=["artifact:case-contract", "artifact:evidence-packet"],
            output_artifacts=["artifact:qdt"],
            dependency_feature_ids=["QDT-002"],
            latest_execution_event_ids=["stage-exec-event-1"],
            replay_command="python3 /Users/agent2/.openclaw/decomposer/scripts/bin/run_decomposition.py",
        )

        validate_stage_status_snapshot(record)
        self.assertEqual(record["table"], STAGE_STATUS_TABLE)
        self.assertEqual(record["stage"], "decomposition")
        self.assertEqual(record["input_artifacts"], ["artifact:case-contract", "artifact:evidence-packet"])
        self.assertEqual(record["output_artifacts"], ["artifact:qdt"])

    def test_execution_event_requires_contract_fields_and_log_ref(self):
        with self.assertRaisesRegex(StageContractError, "bounded log artifact ref or no_log_reason"):
            build_stage_execution_event(
                execution_event_id="stage-exec-event-1",
                context=self.context(),
                event_type="stage_started",
                event_status="info",
                attempt_number=1,
                max_attempts=3,
                runner_ref="ads-runner:fixture",
                agent_or_component_ref="orchestrator",
                script_path="/Users/agent2/.openclaw/orchestrator/scripts/bin/run_ads_pipeline_loop.py",
                command_sha256_value=command_sha256("python3 run_ads_pipeline_loop.py"),
                redaction_status="not_needed",
                replay_command="python3 run_ads_pipeline_loop.py --stage retrieval",
            )

        with self.assertRaisesRegex(StageContractError, "replay_command is required"):
            build_stage_execution_event(
                execution_event_id="stage-exec-event-1",
                context=self.context(),
                event_type="stage_started",
                event_status="info",
                attempt_number=1,
                max_attempts=3,
                runner_ref="ads-runner:fixture",
                agent_or_component_ref="orchestrator",
                script_path="/Users/agent2/.openclaw/orchestrator/scripts/bin/run_ads_pipeline_loop.py",
                command_sha256_value=command_sha256("python3 run_ads_pipeline_loop.py"),
                no_log_reason="stage not yet invoked",
                redaction_status="not_needed",
                replay_command="",
            )

    def test_execution_event_validates_artifacts_and_rejects_raw_logs(self):
        record = build_stage_execution_event(
            execution_event_id="stage-exec-event-1",
            context=self.context(),
            event_type="stage_completed",
            event_status="info",
            started_at="2026-06-24T18:00:00+00:00",
            completed_at="2026-06-24T18:01:00+00:00",
            duration_ms=60000,
            attempt_number=1,
            max_attempts=3,
            runner_ref="ads-runner:fixture",
            agent_or_component_ref="orchestrator",
            script_path="/Users/agent2/.openclaw/orchestrator/scripts/bin/wake_researcher_swarm.py",
            command_sha256_value=command_sha256("python3 wake_researcher_swarm.py"),
            input_artifact_refs=["artifact:qdt", "artifact:retrieval-packet"],
            output_artifact_refs=["artifact:researcher-bundle"],
            validation_result_refs=["validation:researcher-bundle"],
            bounded_log_artifact_ref="artifact:bounded-log",
            redaction_status="redacted",
            replay_command="python3 wake_researcher_swarm.py --case-id case-1 --dispatch-id dispatch-1",
        )

        validate_stage_execution_event(record)
        self.assertEqual(record["table"], STAGE_EXECUTION_EVENT_TABLE)
        self.assertEqual(record["input_artifact_refs"], ["artifact:qdt", "artifact:retrieval-packet"])
        self.assertEqual(record["output_artifact_refs"], ["artifact:researcher-bundle"])

        contaminated = dict(record)
        contaminated["stdout"] = "raw stdout should not be stored on event rows"
        with self.assertRaisesRegex(StageContractError, "raw log fields are forbidden"):
            validate_stage_execution_event(contaminated)

    def test_stage_status_migration_defines_named_surfaces(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "002_v2_stage_status_model.sql"
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "fixture.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(migration)
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            finally:
                conn.close()

        self.assertIn("v2_stage_status_snapshots", tables)
        self.assertIn("v2_stage_execution_events", tables)
        self.assertIn("v2_pipeline_error_events", tables)
        self.assertIn("v2_failure_pattern_groups", tables)

    def test_pipeline_error_event_contract_and_persistence(self):
        error = build_pipeline_error_event(
            error_event_id="pipeline-error-1",
            execution_event_id="stage-exec-event-1",
            context=self.context("retrieval"),
            failure_class="missing_required_artifact",
            failure_grouping_key="retrieval:missing_required_artifact:retrieval-packet",
            retryability="terminal",
            safe_message="retrieval packet artifact was missing",
            safe_metadata={"artifact_ref": "artifact:retrieval-packet"},
            replay_command="python3 wake_researcher_swarm.py --case-id case-1 --dispatch-id dispatch-1",
        )
        validate_pipeline_error_event(error)
        self.assertEqual(error["table"], PIPELINE_ERROR_EVENT_TABLE)

        contaminated = dict(error)
        contaminated["safe_metadata"] = {"raw_payload": "must not be stored"}
        with self.assertRaisesRegex(StageContractError, "raw payload"):
            validate_pipeline_error_event(contaminated)

        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "002_v2_stage_status_model.sql"
        ).read_text(encoding="utf-8")
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(migration)
            write_pipeline_error_event(conn, error)
            event_count = conn.execute(
                f"SELECT COUNT(*) FROM {PIPELINE_ERROR_EVENT_TABLE}"
            ).fetchone()[0]
            group_count = conn.execute(
                f"SELECT event_count FROM {FAILURE_PATTERN_GROUP_TABLE} "
                "WHERE failure_grouping_key = ?",
                (error["failure_grouping_key"],),
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(event_count, 1)
        self.assertEqual(group_count, 1)


if __name__ == "__main__":
    unittest.main()
