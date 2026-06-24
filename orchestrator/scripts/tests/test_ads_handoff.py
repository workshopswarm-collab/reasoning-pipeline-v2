#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff import (
    ARTIFACT_MANIFEST_TABLE,
    ARTIFACT_VALIDATION_RESULTS_TABLE,
    ArtifactManifestContext,
    ArtifactManifestError,
    build_artifact_manifest,
    build_validation_result,
    validate_artifact_manifest,
    write_artifact_manifest,
    write_validation_result,
)


class AdsHandoffTest(unittest.TestCase):
    def context(self) -> ArtifactManifestContext:
        return ArtifactManifestContext(
            case_id="case-1",
            case_key="polymarket:market-1",
            dispatch_id="dispatch-1",
            stage="retrieval",
            stage_attempt_id="stage-attempt-1",
            pipeline_run_id="pipeline-run-1",
            producer="session-3-retrieval",
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            source_cutoff_timestamp="2026-06-24T17:55:00+00:00",
            generated_at="2026-06-24T18:01:00+00:00",
        )

    def artifact_path(self, tempdir: str) -> Path:
        path = Path(tempdir) / "retrieval-packet.json"
        path.write_text('{"schema_version":"retrieval-packet/v1","items":[]}\n', encoding="utf-8")
        return path

    def test_manifest_construction_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = self.artifact_path(tempdir)
            manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=path,
                input_manifest_ids=["artifact:case-contract"],
                validation_result_refs=["artifact-validation:pending"],
                validation_status="not_validated",
                validator_version="ads-handoff-test/v1",
                temporal_isolation_status="pass",
                metadata={"source": "fixture", "bytes": path.stat().st_size},
            )

            validate_artifact_manifest(
                manifest,
                expected_artifact_schema_version="retrieval-packet/v1",
                expected_sha256=manifest["sha256"],
            )
            self.assertEqual(manifest["table"], ARTIFACT_MANIFEST_TABLE)
            self.assertEqual(manifest["case_id"], "case-1")
            self.assertEqual(manifest["dispatch_id"], "dispatch-1")
            self.assertEqual(manifest["forecast_timestamp"], "2026-06-24T18:00:00+00:00")
            self.assertEqual(manifest["source_cutoff_timestamp"], "2026-06-24T17:55:00+00:00")
            self.assertTrue(manifest["sha256"].startswith("sha256:"))
            self.assertNotIn("content", manifest)

            migration = (
                Path(__file__).resolve().parents[1]
                / "migrations"
                / "003_artifact_manifest_contract.sql"
            ).read_text(encoding="utf-8")
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(migration)
                artifact_id = write_artifact_manifest(conn, manifest)
                result = build_validation_result(
                    artifact_id=artifact_id,
                    status="valid",
                    validator_version="ads-handoff-test/v1",
                    reason_codes=["schema_passed", "digest_matched"],
                    validation_messages=["fixture manifest validated"],
                    metadata={"validator": "unit-test"},
                )
                self.assertEqual(result["table"], ARTIFACT_VALIDATION_RESULTS_TABLE)
                write_validation_result(conn, result)

                row = conn.execute(
                    "SELECT artifact_id, artifact_sha256, input_manifest_ids, metadata "
                    "FROM case_artifact_manifest"
                ).fetchone()
                self.assertEqual(row[0], artifact_id)
                self.assertEqual(row[1], manifest["sha256"])
                self.assertEqual(json.loads(row[2]), ["artifact:case-contract"])
                self.assertEqual(json.loads(row[3])["source"], "fixture")

                result_count = conn.execute(
                    "SELECT COUNT(*) FROM artifact_validation_results WHERE artifact_id = ?",
                    (artifact_id,),
                ).fetchone()[0]
                self.assertEqual(result_count, 1)
            finally:
                conn.close()

    def test_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = self.artifact_path(tempdir)
            manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=path,
            )
            path.write_text('{"schema_version":"retrieval-packet/v1","items":["changed"]}\n', encoding="utf-8")

            with self.assertRaisesRegex(ArtifactManifestError, "digest mismatch"):
                validate_artifact_manifest(manifest)

    def test_schema_expectation_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=self.artifact_path(tempdir),
            )

            with self.assertRaisesRegex(ArtifactManifestError, "schema version"):
                validate_artifact_manifest(
                    manifest,
                    expected_artifact_schema_version="retrieval-packet/v2",
                )

    def test_missing_and_unsafe_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=self.artifact_path(tempdir),
            )

            missing_case = dict(manifest)
            del missing_case["case_id"]
            with self.assertRaisesRegex(ArtifactManifestError, "case_id is required"):
                validate_artifact_manifest(missing_case)

            unsafe_metadata = dict(manifest)
            unsafe_metadata["metadata"] = {"raw_payload": "full artifact body must not be duplicated"}
            with self.assertRaisesRegex(ArtifactManifestError, "raw payload"):
                validate_artifact_manifest(unsafe_metadata)

            raw_top_level = dict(manifest)
            raw_top_level["content"] = "full artifact body must not be stored"
            with self.assertRaisesRegex(ArtifactManifestError, "raw payload"):
                validate_artifact_manifest(raw_top_level)

    def test_artifact_manifest_migration_defines_named_surfaces(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "003_artifact_manifest_contract.sql"
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
                manifest_columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(case_artifact_manifest)").fetchall()
                }
                result_columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(artifact_validation_results)").fetchall()
                }
            finally:
                conn.close()

        self.assertIn("case_artifact_manifest", tables)
        self.assertIn("artifact_validation_results", tables)
        self.assertIn("artifact_schema_version", manifest_columns)
        self.assertIn("artifact_sha256", manifest_columns)
        self.assertIn("source_cutoff_timestamp", manifest_columns)
        self.assertIn("validation_result_refs", manifest_columns)
        self.assertIn("validation_result_id", result_columns)
        self.assertIn("reason_codes", result_columns)


if __name__ == "__main__":
    unittest.main()
