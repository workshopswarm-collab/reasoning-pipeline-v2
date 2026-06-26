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
from predquant.ads_handoff_resolver import (
    ManifestRequirement,
    load_manifest_payload,
    resolve_artifact_manifest,
)
from predquant.foundation_schema import ensure_foundation_schema


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

    def test_write_artifact_manifest_can_persist_validation_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = self.artifact_path(tempdir)
            manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=path,
                validation_status="not_validated",
                validator_version="ads-handoff-test/v1",
            )
            validation = build_validation_result(
                artifact_id=manifest["artifact_id"],
                status="valid",
                validator_version="ads-handoff-test/v1",
                reason_codes=["schema_passed"],
                validation_messages=["manifest and payload validated"],
                metadata={"validator": "unit-test"},
            )
            conn = sqlite3.connect(":memory:")
            try:
                artifact_id = write_artifact_manifest(conn, manifest, validation_results=[validation])

                manifest_row = conn.execute(
                    "SELECT artifact_id, validation_status, validation_result_refs "
                    "FROM case_artifact_manifest"
                ).fetchone()
                validation_row = conn.execute(
                    "SELECT validation_result_id, artifact_id, status FROM artifact_validation_results"
                ).fetchone()
                self.assertEqual(manifest_row[0], artifact_id)
                self.assertEqual(manifest_row[1], "valid")
                self.assertEqual(json.loads(manifest_row[2]), [validation["validation_result_id"]])
                self.assertEqual(validation_row, (validation["validation_result_id"], artifact_id, "valid"))
            finally:
                conn.close()

    def test_resolver_loads_and_validates_persisted_manifest_payload(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = self.artifact_path(tempdir).resolve()
            manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=path,
                validation_status="valid",
                validator_version="ads-handoff-test/v1",
                temporal_isolation_status="pass",
            )
            conn = sqlite3.connect(":memory:")
            try:
                artifact_id = write_artifact_manifest(conn, manifest)
                resolved = resolve_artifact_manifest(
                    conn,
                    artifact_id,
                    ManifestRequirement(
                        role="retrieval",
                        artifact_type="retrieval-packet",
                        artifact_schema_version="retrieval-packet/v1",
                        stage="retrieval",
                    ),
                )
                self.assertEqual(resolved["artifact_id"], artifact_id)
                self.assertEqual(load_manifest_payload(resolved)["schema_version"], "retrieval-packet/v1")
            finally:
                conn.close()

    def test_validation_result_requires_existing_artifact_manifest(self):
        result = build_validation_result(
            artifact_id="artifact:missing",
            status="valid",
            validator_version="ads-handoff-test/v1",
            reason_codes=["schema_passed"],
            validation_messages=["manifest and payload validated"],
        )
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(ArtifactManifestError, "unknown artifact_id"):
                write_validation_result(conn, result)
        finally:
            conn.close()

    def test_combined_manifest_write_rejects_reused_validation_result_id(self):
        with tempfile.TemporaryDirectory() as tempdir:
            first_path = self.artifact_path(tempdir)
            second_path = Path(tempdir) / "second-retrieval-packet.json"
            second_path.write_text('{"schema_version":"retrieval-packet/v1","items":[2]}\n', encoding="utf-8")
            first_manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=first_path,
            )
            second_manifest = build_artifact_manifest(
                context=self.context(),
                artifact_type="retrieval-packet",
                artifact_schema_version="retrieval-packet/v1",
                path=second_path,
            )
            reused_id = "artifact-validation:shared"
            first_validation = build_validation_result(
                artifact_id=first_manifest["artifact_id"],
                status="valid",
                validator_version="ads-handoff-test/v1",
                validation_result_id=reused_id,
            )
            second_validation = build_validation_result(
                artifact_id=second_manifest["artifact_id"],
                status="valid",
                validator_version="ads-handoff-test/v1",
                validation_result_id=reused_id,
            )
            conn = sqlite3.connect(":memory:")
            try:
                write_artifact_manifest(conn, first_manifest, validation_results=[first_validation])
                with self.assertRaisesRegex(ArtifactManifestError, "already linked"):
                    write_artifact_manifest(conn, second_manifest, validation_results=[second_validation])
                second_count = conn.execute(
                    "SELECT COUNT(*) FROM case_artifact_manifest WHERE artifact_id = ?",
                    (second_manifest["artifact_id"],),
                ).fetchone()[0]
                self.assertEqual(second_count, 0)
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

    def test_foundation_migration_defines_mig001_named_surfaces(self):
        conn = sqlite3.connect(":memory:")
        try:
            ensure_foundation_schema(conn)
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
        self.assertIn("artifact_id", manifest_columns)
        self.assertIn("artifact_schema_version", manifest_columns)
        self.assertIn("validation_result_refs", manifest_columns)
        self.assertIn("artifact_id", result_columns)
        self.assertIn("validation_result_id", result_columns)

    def test_foundation_migration_upgrades_compact_legacy_manifest_table(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE case_artifact_manifest (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  case_id TEXT,
                  case_key TEXT,
                  market_id TEXT,
                  dispatch_id TEXT NOT NULL,
                  feature_id TEXT,
                  artifact_type TEXT NOT NULL,
                  schema_version TEXT,
                  schema_id TEXT,
                  producer_stage TEXT NOT NULL,
                  artifact_path TEXT NOT NULL,
                  sha256 TEXT,
                  artifact_sha256 TEXT,
                  replay_command TEXT,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            ensure_foundation_schema(conn)

            manifest_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(case_artifact_manifest)").fetchall()
            }
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(case_artifact_manifest)").fetchall()
            }
        finally:
            conn.close()

        self.assertIn("stage", manifest_columns)
        self.assertIn("artifact_id", manifest_columns)
        self.assertIn("artifact_schema_version", manifest_columns)
        self.assertIn("validation_status", manifest_columns)
        self.assertIn("idx_case_artifact_manifest_case_dispatch", indexes)
        self.assertIn("idx_case_artifact_manifest_type_schema", indexes)


if __name__ == "__main__":
    unittest.main()
