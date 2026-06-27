#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "decomposer" / "scripts"))
sys.path.insert(0, str(ROOT / "orchestrator" / "scripts"))

from ads_decomposer.handoff import (  # noqa: E402
    DECOMPOSER_MODEL_ID,
    DECOMPOSER_MODEL_LANE_ID,
    DECOMPOSER_PROMPT_TEMPLATE_ID,
    QUESTION_DECOMPOSITION_SCHEMA_VERSION,
)
from ads_decomposer.persistence import (  # noqa: E402
    QDTPersistenceError,
    decomposition_run_id_for,
    ensure_qdt_persistence_schema,
    write_decomposition_run,
    write_qdt_research_sufficiency_requirements,
)
from ads_decomposer.qdt import (  # noqa: E402
    QDT_SCHEMA_VALIDATOR_VERSION,
    build_anchor_dependency_contract,
    build_fixture_qdt_candidate,
    build_research_sufficiency_requirements,
    dump_question_decomposition,
    select_qdt_candidate,
)
from predquant.ads_handoff import ArtifactManifestContext, build_artifact_manifest  # noqa: E402
from predquant.sqlite_store import SCHEMA as LEGACY_SQLITE_SCHEMA  # noqa: E402


FORECAST_TIMESTAMP = "2026-06-25T12:00:00+00:00"
SOURCE_CUTOFF_TIMESTAMP = "2026-06-25T11:55:00+00:00"


class QDTPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_qdt_persistence_schema(self.conn)
        self.handoff = {
            "artifact_type": "decomposer_handoff",
            "schema_version": "decomposer-handoff/v1",
            "case_id": "case-1",
            "case_key": "polymarket:market-1",
            "dispatch_id": "dispatch-1",
            "macro_question": "Will example happen?",
            "market_context": {
                "market_id": "market-1",
                "market_reality_constraints_digest": "sha256:" + "0" * 64,
            },
            "artifact_refs": {
                "related_market_context": {
                    "artifact_id": "artifact:amrg-1",
                    "artifact_type": "related-live-market-context",
                },
            },
            "model_execution_context": {
                "model_lane_id": DECOMPOSER_MODEL_LANE_ID,
                "resolved_model_id": DECOMPOSER_MODEL_ID,
                "model_policy_ref": "orchestrator/plans/autonomous-decomposition-swarm-model-lane-policy.json",
                "prompt_template_id": DECOMPOSER_PROMPT_TEMPLATE_ID,
                "prompt_template_sha256": "sha256:" + "1" * 64,
                "input_manifest_ids": ["artifact:case", "artifact:evidence", "artifact:profile", "artifact:amrg"],
                "output_schema_version": QUESTION_DECOMPOSITION_SCHEMA_VERSION,
            },
        }

    def tearDown(self) -> None:
        self.conn.close()

    def _selected_qdt(self) -> dict:
        return select_qdt_candidate([build_fixture_qdt_candidate(self.handoff)])

    def _manifest(self, qdt: dict, directory: Path) -> dict:
        qdt_path = directory / "question-decomposition.json"
        qdt_path.write_text(dump_question_decomposition(qdt), encoding="utf-8")
        return build_artifact_manifest(
            context=ArtifactManifestContext(
                case_id=qdt["case_id"],
                case_key=qdt["case_key"],
                dispatch_id=qdt["dispatch_id"],
                stage="decomposition",
                producer="session-03-mig-003-test",
                forecast_timestamp=FORECAST_TIMESTAMP,
                source_cutoff_timestamp=SOURCE_CUTOFF_TIMESTAMP,
                generated_at=FORECAST_TIMESTAMP,
            ),
            artifact_type="question_decomposition",
            artifact_schema_version=QUESTION_DECOMPOSITION_SCHEMA_VERSION,
            path=qdt_path,
            input_manifest_ids=qdt["model_execution_context"]["input_manifest_ids"],
            validation_status="valid",
            validator_version=QDT_SCHEMA_VALIDATOR_VERSION,
            metadata={"market_id": qdt["market_id"]},
        )

    def _refresh_leaf_sufficiency(self, leaf: dict) -> None:
        leaf["research_sufficiency_requirements"] = build_research_sufficiency_requirements(
            purpose=leaf["purpose"],
            static_information_weight=leaf["bayesian_weighting"]["static_information_weight"],
            condition_scope=leaf["leaf_condition_scope"],
            required_value_fields=leaf["required_evidence_fields"],
        )

    def _anchored_qdt(self) -> dict:
        qdt = copy.deepcopy(self._selected_qdt())
        qdt["required_leaf_questions"][1]["leaf_condition_scope"] = "target_given_upstream"
        self._refresh_leaf_sufficiency(qdt["required_leaf_questions"][1])
        qdt["branches"][0]["anchor_mode"] = "anchor_required"
        qdt["amrg_anchor_dependency_contracts"] = [
            build_anchor_dependency_contract(
                {"edge_id": "edge-1", "status": "validated_strict_precedence_anchor"},
                qdt["branches"][0],
                leaves=qdt["required_leaf_questions"],
                related_market_ref="artifact:amrg-1",
            )
        ]
        qdt["related_market_context_usage"]["anchor_dependency_status"] = "declared"
        return qdt

    def test_writes_decomposition_run_leaf_requirements_and_anchor_slices(self) -> None:
        qdt = self._anchored_qdt()
        with tempfile.TemporaryDirectory() as temp:
            manifest = self._manifest(qdt, Path(temp))

            run_id = write_decomposition_run(self.conn, qdt, manifest=manifest)
            result = write_qdt_research_sufficiency_requirements(
                self.conn,
                qdt,
                decomposition_run_id=run_id,
                qdt_artifact_id=manifest["artifact_id"],
            )

        self.assertEqual(run_id, decomposition_run_id_for(qdt))
        run = self.conn.execute("SELECT * FROM qdt_decomposition_runs").fetchone()
        self.assertEqual(run["decomposition_run_id"], run_id)
        self.assertEqual(run["model_lane_id"], DECOMPOSER_MODEL_LANE_ID)
        self.assertEqual(run["resolved_model_id"], DECOMPOSER_MODEL_ID)
        self.assertEqual(run["prompt_template_id"], DECOMPOSER_PROMPT_TEMPLATE_ID)
        self.assertEqual(run["output_schema_version"], QUESTION_DECOMPOSITION_SCHEMA_VERSION)
        self.assertEqual(json.loads(run["branch_ids"]), ["branch-resolution", "branch-mechanics"])
        self.assertEqual(json.loads(run["amrg_anchor_dependency_contract_refs"])[0], qdt["amrg_anchor_dependency_contracts"][0]["anchor_dependency_contract_id"])

        leaf_count = self.conn.execute("SELECT COUNT(*) FROM qdt_required_research_questions").fetchone()[0]
        self.assertEqual(leaf_count, len(qdt["required_leaf_questions"]))
        source_leaf = self.conn.execute(
            "SELECT * FROM qdt_required_research_questions WHERE question_id = ?",
            ("leaf-source-of-truth",),
        ).fetchone()
        self.assertEqual(source_leaf["required_sufficiency_requirement_id"], qdt["required_leaf_questions"][0]["research_sufficiency_requirements"]["requirement_id"])
        self.assertEqual(json.loads(source_leaf["required_source_classes"]), ["official_or_primary", "independent_secondary"])

        self.assertEqual(len(result["sufficiency_requirement_record_ids"]), len(qdt["required_leaf_questions"]))
        sufficiency_count = self.conn.execute(
            "SELECT COUNT(*) FROM qdt_leaf_research_sufficiency_requirements"
        ).fetchone()[0]
        self.assertEqual(sufficiency_count, len(qdt["required_leaf_questions"]))
        source_requirement = self.conn.execute(
            "SELECT * FROM qdt_leaf_research_sufficiency_requirements WHERE leaf_id = ?",
            ("leaf-source-of-truth",),
        ).fetchone()
        self.assertEqual(source_requirement["protected_primary_required"], 1)
        self.assertEqual(source_requirement["allow_macro_fallback_for_leaf"], 0)

        self.assertEqual(len(result["anchor_dependency_slice_ids"]), 1)
        anchor = self.conn.execute("SELECT * FROM qdt_amrg_anchor_dependency_slices").fetchone()
        self.assertEqual(anchor["edge_id"], "edge-1")
        self.assertEqual(anchor["anchor_mode"], "anchor_required")
        self.assertEqual(json.loads(anchor["condition_scoped_leaf_ids"]), ["leaf-direct-evidence"])

    def test_qdt_persistence_is_idempotent(self) -> None:
        qdt = self._selected_qdt()
        with tempfile.TemporaryDirectory() as temp:
            manifest = self._manifest(qdt, Path(temp))
            run_id = write_decomposition_run(self.conn, qdt, manifest=manifest)
            write_qdt_research_sufficiency_requirements(
                self.conn,
                qdt,
                decomposition_run_id=run_id,
                qdt_artifact_id=manifest["artifact_id"],
            )
            write_decomposition_run(self.conn, qdt, manifest=manifest)
            write_qdt_research_sufficiency_requirements(
                self.conn,
                qdt,
                decomposition_run_id=run_id,
                qdt_artifact_id=manifest["artifact_id"],
            )

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM qdt_decomposition_runs").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM qdt_required_research_questions").fetchone()[0],
            len(qdt["required_leaf_questions"]),
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM qdt_leaf_research_sufficiency_requirements").fetchone()[0],
            len(qdt["required_leaf_questions"]),
        )

    def test_accepts_orchestrator_hyphenated_question_decomposition_manifest_type(self) -> None:
        qdt = self._selected_qdt()
        with tempfile.TemporaryDirectory() as temp:
            manifest = self._manifest(qdt, Path(temp))
            manifest["artifact_type"] = "question-decomposition"

            run_id = write_decomposition_run(self.conn, qdt, manifest=manifest)

        self.assertEqual(run_id, decomposition_run_id_for(qdt))
        run = self.conn.execute("SELECT qdt_artifact_id, artifact_path FROM qdt_decomposition_runs").fetchone()
        self.assertEqual(run["qdt_artifact_id"], manifest["artifact_id"])
        self.assertEqual(run["artifact_path"], manifest["path"])

    def test_rejects_scae_and_probability_authority_fields(self) -> None:
        qdt = self._selected_qdt()
        unsafe = copy.deepcopy(qdt)
        unsafe["scae_delta_authority"] = True
        with self.assertRaises(QDTPersistenceError):
            write_decomposition_run(self.conn, unsafe)

        unsafe_probability = copy.deepcopy(qdt)
        unsafe_probability["required_leaf_questions"][0]["probability_estimate"] = 0.7
        with self.assertRaises(QDTPersistenceError):
            write_qdt_research_sufficiency_requirements(self.conn, unsafe_probability)

    def test_schema_upgrade_preflights_legacy_qdt_tables_before_migration_indexes(self) -> None:
        self.conn.close()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(LEGACY_SQLITE_SCHEMA)

        ensure_qdt_persistence_schema(self.conn)

        run_columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(qdt_decomposition_runs)").fetchall()
        }
        question_columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(qdt_required_research_questions)").fetchall()
        }
        indexes = {
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        self.assertIn("qdt_artifact_id", run_columns)
        self.assertIn("decomposition_run_id", question_columns)
        self.assertIn("leaf_id", question_columns)
        self.assertIn("idx_qdt_decomposition_runs_artifact", indexes)
        self.assertIn("idx_qdt_required_questions_run_leaf", indexes)

    def test_upgrades_legacy_sqlite_qdt_tables_before_writing(self) -> None:
        self.conn.close()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(LEGACY_SQLITE_SCHEMA)
        qdt = self._selected_qdt()

        with tempfile.TemporaryDirectory() as temp:
            manifest = self._manifest(qdt, Path(temp))
            run_id = write_decomposition_run(self.conn, qdt, manifest=manifest)
            write_qdt_research_sufficiency_requirements(
                self.conn,
                qdt,
                decomposition_run_id=run_id,
                qdt_artifact_id=manifest["artifact_id"],
            )

        run = self.conn.execute(
            "SELECT decomposition_run_id, qdt_artifact_id FROM qdt_decomposition_runs"
        ).fetchone()
        self.assertEqual(run["decomposition_run_id"], run_id)
        self.assertTrue(run["qdt_artifact_id"].startswith("artifact:"))
        question = self.conn.execute(
            "SELECT required_sufficiency_requirement_id FROM qdt_required_research_questions LIMIT 1"
        ).fetchone()
        self.assertTrue(question["required_sufficiency_requirement_id"].startswith("qdt-sufficiency:"))


if __name__ == "__main__":
    unittest.main()
