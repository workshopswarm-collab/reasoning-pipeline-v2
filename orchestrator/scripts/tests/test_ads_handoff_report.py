#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    ensure_artifact_manifest_schema,
    write_artifact_manifest,
)
from predquant.ads_handoff_report import build_handoff_report
from predquant.ads_pipeline_runner import (
    PipelineRunnerPolicy,
    build_pipeline_run,
    ensure_pipeline_runner_schema,
    write_pipeline_run,
)
from predquant.ads_stage_logging import (
    StageContext,
    build_stage_execution_event,
    build_stage_status_snapshot,
    command_sha256,
    ensure_stage_logging_schema,
    write_stage_execution_event,
    write_stage_status_snapshot,
)


PIPELINE_RUN_ID = "ads-pipeline-run:handoff-report-test"
CASE_ID = "case-handoff-report"
CASE_KEY = "polymarket:handoff-report"
DISPATCH_ID = "dispatch-handoff-report"
REPLAY_COMMAND = "python3 scripts/bin/run_ads_one_case_canary.py --unit-test"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    ensure_pipeline_runner_schema(conn)
    ensure_stage_logging_schema(conn)
    ensure_artifact_manifest_schema(conn)
    run = build_pipeline_run(
        policy=PipelineRunnerPolicy(),
        pipeline_run_id=PIPELINE_RUN_ID,
        status="stopped",
        stopped_at="2026-07-01T12:05:00+00:00",
        metadata={"unit_test": "handoff_report"},
    )
    write_pipeline_run(conn, run)
    conn.commit()
    return conn


def _manifest_context(stage: str) -> ArtifactManifestContext:
    return ArtifactManifestContext(
        case_id=CASE_ID,
        case_key=CASE_KEY,
        dispatch_id=DISPATCH_ID,
        stage=stage,
        stage_attempt_id=f"stage-attempt:{stage}",
        pipeline_run_id=PIPELINE_RUN_ID,
        producer="handoff-report-unit-test",
        forecast_timestamp="2026-07-01T12:00:00+00:00",
        source_cutoff_timestamp="2026-07-01T11:55:00+00:00",
        generated_at="2026-07-01T12:01:00+00:00",
    )


def _write_manifest(
    conn: sqlite3.Connection,
    root: Path,
    *,
    stage: str,
    artifact_type: str,
    artifact_schema_version: str,
    input_manifest_ids: list[str] | None = None,
) -> str:
    path = root / f"{stage}-{artifact_type}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": artifact_schema_version,
                "artifact_type": artifact_type.replace("-", "_"),
                "stage": stage,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = build_artifact_manifest(
        context=_manifest_context(stage),
        artifact_type=artifact_type,
        artifact_schema_version=artifact_schema_version,
        path=path,
        input_manifest_ids=input_manifest_ids or [],
        validation_status="valid",
        validator_version="handoff-report-test/v1",
        temporal_isolation_status="pass",
        metadata={"unit_test": "handoff_report"},
    )
    return write_artifact_manifest(conn, manifest)


def _record_complete_stage(
    conn: sqlite3.Connection,
    *,
    stage: str,
    output_refs: list[str],
) -> None:
    context = StageContext(
        case_id=CASE_ID,
        case_key=CASE_KEY,
        dispatch_id=DISPATCH_ID,
        stage=stage,
        stage_attempt_id=f"stage-attempt:{stage}",
        pipeline_run_id=PIPELINE_RUN_ID,
    )
    event_id = f"stage-event:{stage}:completed"
    event = build_stage_execution_event(
        execution_event_id=event_id,
        context=context,
        event_type="stage_completed",
        event_status="info",
        started_at="2026-07-01T12:00:00+00:00",
        completed_at="2026-07-01T12:01:00+00:00",
        duration_ms=1000,
        attempt_number=1,
        max_attempts=1,
        runner_ref=f"ads-runner:{PIPELINE_RUN_ID}",
        agent_or_component_ref="orchestrator",
        script_path="scripts/bin/run_ads_one_case_canary.py",
        command_sha256_value=command_sha256(REPLAY_COMMAND),
        output_artifact_refs=output_refs,
        no_log_reason="handoff_report_test_has_no_raw_log",
        redaction_status="not_needed",
        replay_command=REPLAY_COMMAND,
        safe_metadata={"unit_test": "handoff_report"},
    )
    write_stage_execution_event(conn, event)
    status = build_stage_status_snapshot(
        context=context,
        status="complete",
        started_at="2026-07-01T12:00:00+00:00",
        completed_at="2026-07-01T12:01:00+00:00",
        duration_ms=1000,
        output_artifacts=output_refs,
        latest_execution_event_ids=[event_id],
        replay_command=REPLAY_COMMAND,
        metadata={"unit_test": "handoff_report"},
    )
    write_stage_status_snapshot(conn, status)


class AdsHandoffReportTest(unittest.TestCase):
    def test_readiness_block_is_valid_but_not_accepted_downstream_input(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "predquant.sqlite3"
            root = Path(tempdir) / "artifacts"
            root.mkdir()
            conn = _connect(db_path)
            try:
                retrieval_ref = _write_manifest(
                    conn,
                    root,
                    stage="retrieval",
                    artifact_type="retrieval-packet",
                    artifact_schema_version="retrieval-packet/v1",
                )
                readiness_ref = _write_manifest(
                    conn,
                    root,
                    stage="researcher_classification",
                    artifact_type="researcher-classification-readiness-block",
                    artifact_schema_version="researcher-classification-readiness-block/v1",
                    input_manifest_ids=[retrieval_ref],
                )
                scae_ref = _write_manifest(
                    conn,
                    root,
                    stage="scae",
                    artifact_type="scae-final-probability-ledger",
                    artifact_schema_version="scae-final-probability-ledger/v1",
                    input_manifest_ids=[readiness_ref],
                )
                _record_complete_stage(conn, stage="retrieval", output_refs=[retrieval_ref])
                _record_complete_stage(conn, stage="researcher_classification", output_refs=[readiness_ref])
                _record_complete_stage(conn, stage="scae", output_refs=[scae_ref])
                conn.commit()
            finally:
                conn.close()

            report = build_handoff_report(db_path, pipeline_run_id=PIPELINE_RUN_ID)

        manifests = {
            manifest["artifact_id"]: manifest
            for stage in report["stages"]
            for manifest in stage["output_manifests"]
        }
        self.assertTrue(report["ok"], report["unresolved_output_manifest_refs"])
        self.assertEqual(report["stage_completion_count"], 3)
        self.assertEqual(report["readiness_block_count"], 1)
        self.assertEqual(report["accepted_intelligence_stage_count"], 1)
        self.assertEqual(manifests[retrieval_ref]["handoff_status"], "valid_and_accepted")
        self.assertTrue(manifests[retrieval_ref]["accepted_for_downstream"])
        self.assertEqual(
            manifests[readiness_ref]["handoff_status"],
            "valid_readiness_block_not_downstream_accepted",
        )
        self.assertTrue(manifests[readiness_ref]["artifact_valid"])
        self.assertTrue(manifests[readiness_ref]["readiness_block"])
        self.assertFalse(manifests[readiness_ref]["accepted_for_downstream"])
        self.assertEqual(manifests[scae_ref]["handoff_status"], "valid_not_accepted")
        self.assertEqual(
            report["handoff_health"]["handoff_counts_by_status"],
            {
                "valid_and_accepted": 1,
                "valid_not_accepted": 1,
                "valid_readiness_block_not_downstream_accepted": 1,
            },
        )

    def test_missing_artifact_refs_fail_manifest_checks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "predquant.sqlite3"
            conn = _connect(db_path)
            try:
                _record_complete_stage(conn, stage="retrieval", output_refs=["artifact:missing"])
                conn.commit()
            finally:
                conn.close()

            report = build_handoff_report(db_path, pipeline_run_id=PIPELINE_RUN_ID)

        self.assertFalse(report["ok"])
        self.assertEqual(report["stage_completion_count"], 1)
        self.assertEqual(report["handoff_counts_by_status"], {"missing_or_unresolved": 1})
        self.assertEqual(len(report["unresolved_output_manifest_refs"]), 1)
        self.assertEqual(report["unresolved_output_manifest_refs"][0]["artifact_id"], "artifact:missing")


if __name__ == "__main__":
    unittest.main()
