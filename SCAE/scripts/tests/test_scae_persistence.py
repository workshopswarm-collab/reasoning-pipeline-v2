import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "orchestrator" / "scripts"))

from scae.intervals import build_pre_debt_ledger_output  # noqa: E402
from scae.ledger import apply_research_sufficiency_guard, finalize_scae_probability_fields  # noqa: E402
from scae.persistence import (  # noqa: E402
    FORECAST_DECISION_TABLE,
    FORECAST_DECISION_MIGRATION,
    MIG007_TABLES,
    MISSINGNESS_SIGNAL_TABLE,
    PERSIST001_SCHEMA_VERSION,
    PERSIST002_SCHEMA_VERSION,
    RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE,
    SCAE_BRANCH_SUBLEDGER_TABLE,
    SCAE_CALIBRATION_DIAGNOSTIC_TABLE,
    SCAE_CONDITIONAL_BRANCH_TABLE,
    SCAE_CROSS_LEAF_DEPENDENCY_TABLE,
    SCAE_LEDGER_OUTPUT_TABLE,
    SCAE_LOG_ODDS_UPDATE_TABLE,
    SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE,
    SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE,
    ScaePersistenceError,
    ensure_forecast_decision_schema,
    ensure_scae_ledger_schema,
    write_forecast_decision,
    write_scae_market_prediction,
    write_scae_ledger,
    write_scae_log_odds_update_slices,
    write_scae_research_sufficiency_inputs,
)
from scae.policy import default_scae_policy  # noqa: E402
from predquant.sqlite_store import (  # noqa: E402
    BRIER_SCORING_VERSION,
    ensure_schema,
    payload_hash,
    write_resolution_score,
)


class ScaePersistenceTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.policy = default_scae_policy()

    def tearDown(self):
        self.conn.close()

    def qdt(self):
        return {
            "required_leaf_questions": [
                {
                    "leaf_id": "leaf-1",
                    "parent_branch_id": "branch-1",
                    "leaf_condition_scope": "unconditional",
                    "research_sufficiency_requirements": {
                        "requirement_id": "requirement:leaf-1",
                        "retrieval_breadth_profile_ref": "breadth-profile:leaf-1",
                    },
                }
            ]
        }

    def reconciliation(self):
        return {
            "artifact_type": "research_sufficiency_reconciliation_slice",
            "schema_version": "research-sufficiency-reconciliation/v1",
            "feature_id": "VER-004",
            "research_sufficiency_reconciliation_id": "reconciliation:leaf-1",
            "research_sufficiency_reconciliation_ref": "research-sufficiency-reconciliation:leaf-1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "research_sufficiency_certificate_ref": "research-sufficiency:leaf-1",
            "retrieval_breadth_profile_ref": "breadth-profile:leaf-1",
            "retrieval_breadth_coverage_ref": "breadth-coverage:leaf-1",
            "retrieval_breadth_certified": True,
            "required_escalation_decision_refs": ["researcher-escalation-decision:1"],
            "completed_escalation_decision_refs": ["researcher-escalation-decision:1"],
            "reconciled_status": "scae_ready_high_certainty",
            "research_sufficiency_reconciliation_status": "scae_ready_high_certainty",
            "reason_codes": ["high_certainty_research_sufficiency_verified"],
            "blocking_reason_codes": [],
        }

    def finalized_ledger(self):
        pre_debt = build_pre_debt_ledger_output(
            {
                "prior_context_id": "prior-context:case-1",
                "case_id": "case-1",
                "case_key": "case:key:1",
                "dispatch_id": "dispatch-1",
                "adjusted_prior_probability": 0.52,
            },
            evidence_delta_slices=[
                {
                    "candidate_slice_id": "log-odds:1",
                    "schema_version": "scae-log-odds-update-candidate-slice/v1",
                    "case_id": "case-1",
                    "dispatch_id": "dispatch-1",
                    "leaf_id": "leaf-1",
                    "signed_log_odds_delta": 0.11,
                    "accepted_for_ledger_input": True,
                    "ledger_input_authority": "candidate_only",
                }
            ],
            policy=self.policy,
        )
        guarded = apply_research_sufficiency_guard(
            pre_debt,
            qdt=self.qdt(),
            sufficiency_reconciliations=[self.reconciliation()],
            policy=self.policy,
        )
        finalized = finalize_scae_probability_fields(guarded, policy=self.policy)
        finalized["case_key"] = "case:key:1"
        finalized["forecast_timestamp"] = "2026-06-25T12:00:00+00:00"
        finalized["run_id"] = "run-1"
        finalized["scae_valid_forecast_requires_evidence_delta_refs"] = True
        finalized["scae_evidence_delta_ref_requirement_status"] = "satisfied"
        finalized["scae_evidence_delta_ref_count"] = 1
        finalized["scae_evidence_delta_refs"] = ["log-odds:1"]
        finalized["scoreable_forecast_output"] = True
        finalized["market_prediction_write_expected"] = True
        return finalized

    def log_odds_slice(self):
        return {
            "artifact_type": "scae_log_odds_update_candidate_slice",
            "schema_version": "scae-log-odds-update-candidate-slice/v1",
            "surface_name": SCAE_LOG_ODDS_UPDATE_TABLE,
            "feature_id": "SCAE-003",
            "candidate_slice_id": "log-odds:1",
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "source_ref": "source:1",
            "source_family_id": "source-family:1",
            "claim_family_id": "claim-family:1",
            "signed_log_odds_delta": 0.11,
            "accepted_for_ledger_input": True,
            "cap_stack": {"per_update_log_odds_cap": 0.7},
            "live_forecast_authority": False,
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
        }

    def decision_gate(self, ledger=None, **overrides):
        ledger = ledger or self.finalized_ledger()
        scae_context = {
            "scae_ledger_ref": ledger["final_probability_ledger_id"],
            "scae_ledger_digest": ledger["final_probability_ledger_digest"],
            "case_id": ledger["case_id"],
            "case_key": ledger.get("case_key"),
            "dispatch_id": ledger["dispatch_id"],
            "run_id": ledger.get("run_id"),
            "forecast_timestamp": ledger.get("forecast_timestamp"),
            "forecast_validity_status": ledger["forecast_validity_status"],
            "execution_authority_status": ledger["execution_authority_status"],
            "final_probability_fields_status": ledger["final_probability_fields_status"],
            "probability_source": "SCAE-012_final_probability_fields",
        }
        if ledger["forecast_validity_status"] != "invalid_for_forecast":
            scae_context["production_forecast_prob"] = ledger["production_forecast_prob"]
            scae_context["canonical_probability"] = ledger["canonical_probability"]
        execution = overrides.pop("execution_authority_status", ledger["execution_authority_status"])
        actionability = overrides.pop(
            "actionability_status",
            {
                "forbidden": "non_actionable",
                "needs_refresh": "refresh_required",
                "watch_only": "watch_only",
                "low_size_only": "actionable_low_size",
                "normal_execution_allowed": "actionable",
            }[execution],
        )
        gate = {
            "artifact_type": "decision_execution_gate",
            "schema_version": "decision-execution-gate/v1",
            "feature_id": "DEC-001",
            "builder_version": "ads-dec-001-decision-gate/v1",
            "authority": "execution_downgrade_only_no_probability_authority",
            "probability_authority": False,
            "replacement_probability_authority": False,
            "synthesis_upgrade_authority": False,
            "persistence_authority": False,
            "market_prediction_authority": False,
            "scoring_authority": False,
            "calibration_debt_clearance_authority": False,
            "writes_production_forecast": False,
            "writes_persistence": False,
            "writes_market_prediction": False,
            "scoreable_forecast_output": False,
            "clears_calibration_debt": False,
            "generated_at": "2026-06-25T12:01:00+00:00",
            "case_id": ledger["case_id"],
            "case_key": ledger.get("case_key"),
            "dispatch_id": ledger["dispatch_id"],
            "scae_context": scae_context,
            "synthesis_context": {
                "synthesis_annotation_ref": "synthesis-annotation:1",
                "synthesis_annotation_digest": "sha256:" + "b" * 64,
                "non_authoritative_context_only": True,
                "can_change_probability": False,
                "can_upgrade_execution": False,
            },
            "forecast_validity_status": overrides.pop(
                "forecast_validity_status",
                ledger["forecast_validity_status"],
            ),
            "execution_authority_status": execution,
            "actionability_status": actionability,
            "decision_request_summary": {
                "rationale": "Use SCAE probability and preserve or downgrade actionability only.",
                "reason_codes": ["dec001_preserve_or_downgrade_scae_authority"],
            },
            "downgrade_context": {
                "can_upgrade_scae_validity": False,
                "can_replace_scae_probability": False,
                "synthesis_can_upgrade_execution": False,
            },
            "allowed_outputs": [
                "forecast_validity_downgrade",
                "execution_authority_downgrade",
                "non_actionable_status",
                "qualitative_rationale",
            ],
            "forbidden_outputs": [
                "calibration_debt_clearance",
                "canonical_probability_override",
                "fair_value",
                "forecast_validity_upgrade",
                "interval_override",
                "market_prediction_write",
                "persistence_write",
                "probability_range",
                "production_forecast_prob_override",
                "replacement_probability",
                "scae_delta",
                "scoreable_forecast_output",
            ],
            "metadata": {},
            "decision_gate_id": "decision-gate:case-1",
            "decision_gate_digest": "sha256:" + "c" * 64,
        }
        gate.update(overrides)
        return gate

    def invalid_ledger(self):
        invalid = copy.deepcopy(self.finalized_ledger())
        invalid["forecast_validity_status"] = "invalid_for_forecast"
        invalid["execution_authority_status"] = "forbidden"
        invalid["final_probability_fields_status"] = "blocked_invalid_for_forecast"
        invalid["production_forecast_authority"] = False
        invalid["scoreable_forecast_output"] = False
        invalid["market_prediction_write_expected"] = False
        for field in ("debt_adjusted_probability", "production_forecast_prob", "canonical_probability"):
            invalid.pop(field, None)
        invalid["final_probability_ledger_id"] = "scae-final-probability-ledger:invalid"
        invalid["final_probability_ledger_digest"] = "sha256:" + "d" * 64
        return invalid

    def seed_prediction_market(self, db_path):
        with sqlite3.connect(db_path) as conn:
            ensure_schema(conn)
            market_id = conn.execute(
                """
                INSERT INTO markets (
                  platform, external_market_id, slug, title, status,
                  outcome_type, metadata, current_price
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "polymarket",
                    "scae-market-1",
                    "scae-market-1",
                    "Will the SCAE fixture resolve yes?",
                    "open",
                    "binary",
                    "{}",
                    0.49,
                ),
            ).lastrowid
            snapshot_id = conn.execute(
                """
                INSERT INTO market_snapshots (
                  market_id, observed_at, best_bid, best_ask, raw_payload
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    "2026-06-25T11:55:00+00:00",
                    0.46,
                    0.48,
                    '{"book":"contract"}',
                ),
            ).lastrowid
            later_snapshot_id = conn.execute(
                """
                INSERT INTO market_snapshots (
                  market_id, observed_at, best_bid, best_ask, raw_payload
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    market_id,
                    "2026-06-25T11:59:00+00:00",
                    0.58,
                    0.60,
                    '{"book":"later"}',
                ),
            ).lastrowid
        return int(market_id), int(snapshot_id), int(later_snapshot_id)

    def ads_case_contract(self, ledger, market_id, snapshot_id, *, age_seconds=300, max_age_seconds=3600):
        return {
            "artifact_type": "ads_case_contract",
            "schema_version": "ads-case-contract/v1",
            "case_key": ledger["case_key"],
            "case_id": ledger["case_id"],
            "dispatch_id": ledger["dispatch_id"],
            "prediction_run_id": "prediction-run:scae-1",
            "forecast_artifact_id": "forecast-artifact:scae-1",
            "forecast_timestamp": ledger["forecast_timestamp"],
            "intake_source": {
                "market_row_id": market_id,
                "market_snapshot_id": snapshot_id,
                "snapshot_observed_at": "2026-06-25T11:55:00+00:00",
                "source_payload_hash": "sha256:" + "e" * 64,
            },
            "market_identity": {
                "platform": "polymarket",
                "internal_market_id": market_id,
                "external_market_id": "scae-market-1",
                "title": "Will the SCAE fixture resolve yes?",
            },
            "prediction_time_market_baseline": {
                "market_snapshot_id": snapshot_id,
                "source_fetched_at": "2026-06-25T11:55:00+00:00",
                "snapshot_age_seconds_at_dispatch": age_seconds,
                "max_snapshot_age_seconds": max_age_seconds,
                "market_probability": 0.47,
                "market_probability_method": "bid_ask_midpoint",
            },
        }

    def fresh_snapshot_payload(self):
        return {
            "platform": "polymarket",
            "external_market_id": "scae-market-1",
            "slug": "scae-market-1",
            "title": "Will the SCAE fixture resolve yes?",
            "status": "open",
            "outcome_type": "binary",
            "snapshot": {
                "observed_at": "2026-06-25T11:59:30+00:00",
                "best_bid": 0.50,
                "best_ask": 0.52,
                "raw_payload": {"book": "fresh"},
            },
        }

    def auxiliary_slices(self):
        base = {
            "case_id": "case-1",
            "dispatch_id": "dispatch-1",
            "leaf_id": "leaf-1",
            "parent_branch_id": "branch-1",
            "live_forecast_authority": False,
            "writes_scae_ledger": False,
            "writes_production_forecast": False,
        }
        return {
            SCAE_CROSS_LEAF_DEPENDENCY_TABLE: [
                {
                    **base,
                    "artifact_type": "scae_cross_leaf_dependence_slice",
                    "schema_version": "scae-cross-leaf-dependence-slice/v1",
                    "cross_leaf_dependency_slice_id": "cross-leaf:1",
                    "surface_name": SCAE_CROSS_LEAF_DEPENDENCY_TABLE,
                    "feature_id": "SCAE-006",
                    "dependence_group_id": "claim-family:1",
                    "claim_family_ids": ["claim-family:1"],
                    "cross_leaf_guarded_signed_log_odds_delta": 0.11,
                    "accepted_for_candidate_ledger_input": True,
                }
            ],
            SCAE_BRANCH_SUBLEDGER_TABLE: [
                {
                    **base,
                    "artifact_type": "scae_branch_subledger_slice",
                    "schema_version": "scae-branch-subledger-slice/v1",
                    "branch_subledger_slice_id": "branch-ledger:1",
                    "surface_name": SCAE_BRANCH_SUBLEDGER_TABLE,
                    "feature_id": "SCAE-007",
                    "branch_subledger_signed_log_odds_delta": 0.1,
                    "accepted_for_candidate_ledger_input": True,
                }
            ],
            SCAE_CONDITIONAL_BRANCH_TABLE: [
                {
                    **base,
                    "artifact_type": "scae_conditional_branch_slice",
                    "schema_version": "scae-conditional-branch-slice/v1",
                    "conditional_branch_slice_id": "conditional:1",
                    "surface_name": SCAE_CONDITIONAL_BRANCH_TABLE,
                    "feature_id": "SCAE-010",
                    "condition_scope": "target_given_upstream",
                    "conditional_signed_log_odds_delta": 0.04,
                    "accepted_for_pre_debt_ledger_input": True,
                }
            ],
            SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE: [
                {
                    **base,
                    "artifact_type": "scae_mechanism_family_dependence_diagnostic",
                    "schema_version": "scae-mechanism-family-dependence-diagnostic/v1",
                    "mechanism_family_diagnostic_id": "mechanism:1",
                    "surface_name": SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE,
                    "feature_id": "SCAE-006",
                    "mechanism_family_id": "mechanism-family:1",
                    "diagnostic_only": True,
                    "can_increase_evidence_strength": False,
                    "signed_log_odds_delta_added_by_mechanism_family": 0.0,
                }
            ],
            MISSINGNESS_SIGNAL_TABLE: [
                {
                    **base,
                    "artifact_type": "missingness_signal_slice",
                    "schema_version": "missingness-signal-slice/v1",
                    "missingness_signal_slice_id": "missingness:1",
                    "surface_name": MISSINGNESS_SIGNAL_TABLE,
                    "feature_id": "RET-005",
                    "source_ref": "source:missing",
                    "diagnostic_only": True,
                    "can_increase_evidence_strength": False,
                }
            ],
        }

    def test_schema_creates_named_mig007_tables(self):
        ensure_scae_ledger_schema(self.conn)

        tables = {
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        self.assertTrue(set(MIG007_TABLES).issubset(tables))

    def test_log_odds_write_is_idempotent_and_keeps_typed_delta(self):
        first = write_scae_log_odds_update_slices(self.conn, [self.log_odds_slice()])
        updated = self.log_odds_slice()
        updated["signed_log_odds_delta"] = 0.12
        second = write_scae_log_odds_update_slices(self.conn, [updated])

        self.assertEqual(first, ["log-odds:1"])
        self.assertEqual(second, ["log-odds:1"])
        row = self.conn.execute(
            f"""
            SELECT slice_id, signed_log_odds_delta, accepted_for_ledger_input,
                   live_forecast_authority, writes_production_forecast, payload_json
            FROM {SCAE_LOG_ODDS_UPDATE_TABLE}
            WHERE slice_id = ?
            """,
            ("log-odds:1",),
        ).fetchone()
        self.assertEqual(row[:5], ("log-odds:1", 0.12, 1, 0, 0))
        self.assertEqual(json.loads(row[5])["cap_stack"]["per_update_log_odds_cap"], 0.7)

    def test_research_sufficiency_input_can_be_derived_from_final_ledger(self):
        ledger = self.finalized_ledger()
        row_ids = write_scae_research_sufficiency_inputs(self.conn, ledger)

        self.assertEqual(len(row_ids), 1)
        row = self.conn.execute(
            f"SELECT payload_json, diagnostic_only FROM {SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE}"
        ).fetchone()
        payload = json.loads(row[0])
        self.assertEqual(row[1], 1)
        self.assertEqual(payload["bundle_status"], "scae_ready_high_certainty")
        self.assertEqual(payload["leaf_reconciliation_refs"], ["research-sufficiency-reconciliation:leaf-1"])
        self.assertFalse(payload["writes_production_forecast"])

    def test_write_scae_ledger_covers_all_mig007_surfaces_and_no_downstream_tables(self):
        protected_tables = (
            "forecast_decision_records",
            "market_predictions",
            "outcome_scoring_records",
            "evaluator_scorecards",
            "calibration_candidate_records",
            "v2_replay_manifests",
            "training_trace_minimal_pointers",
        )
        for table in protected_tables:
            self.conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, marker TEXT NOT NULL)")
            self.conn.execute(f"INSERT INTO {table} (id, marker) VALUES (?, ?)", (f"{table}:1", "unchanged"))
        before = {
            table: self.conn.execute(f"SELECT COUNT(*), MIN(marker), MAX(marker) FROM {table}").fetchone()
            for table in protected_tables
        }

        slices = self.auxiliary_slices()
        result = write_scae_ledger(
            self.conn,
            self.finalized_ledger(),
            log_odds_update_slices=[self.log_odds_slice()],
            cross_leaf_dependency_slices=slices[SCAE_CROSS_LEAF_DEPENDENCY_TABLE],
            branch_subledger_slices=slices[SCAE_BRANCH_SUBLEDGER_TABLE],
            conditional_branch_slices=slices[SCAE_CONDITIONAL_BRANCH_TABLE],
            mechanism_family_assignment_slices=slices[SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE],
            missingness_signal_slices=slices[MISSINGNESS_SIGNAL_TABLE],
            research_sufficiency_reconciliation_slices=[self.reconciliation()],
        )

        self.assertEqual(result["surface_write_counts"][SCAE_LOG_ODDS_UPDATE_TABLE], 1)
        self.assertEqual(result["surface_write_counts"][SCAE_CALIBRATION_DIAGNOSTIC_TABLE], 2)
        self.assertEqual(result["surface_write_counts"][SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE], 1)
        for table in (
            SCAE_LEDGER_OUTPUT_TABLE,
            SCAE_LOG_ODDS_UPDATE_TABLE,
            SCAE_CROSS_LEAF_DEPENDENCY_TABLE,
            SCAE_BRANCH_SUBLEDGER_TABLE,
            SCAE_CONDITIONAL_BRANCH_TABLE,
            SCAE_CALIBRATION_DIAGNOSTIC_TABLE,
            SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE,
            SCAE_RESEARCH_SUFFICIENCY_INPUT_TABLE,
            MISSINGNESS_SIGNAL_TABLE,
            RESEARCH_SUFFICIENCY_RECONCILIATION_TABLE,
        ):
            with self.subTest(table=table):
                self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1 if table != SCAE_CALIBRATION_DIAGNOSTIC_TABLE else 2)

        ledger_row = self.conn.execute(
            f"""
            SELECT production_forecast_prob, canonical_probability,
                   writes_production_forecast, writes_persistence,
                   final_probability_fields_status
            FROM {SCAE_LEDGER_OUTPUT_TABLE}
            """
        ).fetchone()
        self.assertEqual(ledger_row[0], ledger_row[1])
        self.assertEqual(ledger_row[2:], (0, 0, "final_probability_fields_ready"))

        for table, prior in before.items():
            with self.subTest(protected_table=table):
                self.assertEqual(
                    self.conn.execute(f"SELECT COUNT(*), MIN(marker), MAX(marker) FROM {table}").fetchone(),
                    prior,
                )

    def test_invalid_forecast_ledger_cannot_smuggle_final_probability_fields(self):
        invalid = copy.deepcopy(self.finalized_ledger())
        invalid["forecast_validity_status"] = "invalid_for_forecast"
        invalid["final_probability_fields_status"] = "blocked_invalid_for_forecast"

        with self.assertRaisesRegex(ScaePersistenceError, "must not contain final probability fields"):
            write_scae_ledger(self.conn, invalid)

    def test_diagnostic_mechanism_rows_cannot_increase_strength(self):
        row = self.auxiliary_slices()[SCAE_MECHANISM_FAMILY_ASSIGNMENT_TABLE][0]
        row["can_increase_evidence_strength"] = True

        with self.assertRaisesRegex(ScaePersistenceError, "diagnostic row cannot increase evidence"):
            write_scae_ledger(
                self.conn,
                self.finalized_ledger(),
                mechanism_family_assignment_slices=[row],
            )

    def test_forecast_decision_schema_is_separate_from_market_predictions(self):
        ensure_forecast_decision_schema(self.conn)

        tables = {
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        self.assertIn(FORECAST_DECISION_TABLE, tables)
        self.assertNotIn("market_predictions", tables)

    def test_mig008_migration_defines_forecast_decision_and_existing_bridge_surfaces(self):
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(FORECAST_DECISION_MIGRATION.read_text(encoding="utf-8"))
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
            decision_columns = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({FORECAST_DECISION_TABLE})").fetchall()
            }

        self.assertIn(FORECAST_DECISION_TABLE, tables)
        self.assertNotIn("market_predictions", tables)
        self.assertTrue(
            {
                "forecast_decision_id",
                "scae_ledger_id",
                "decision_gate_id",
                "synthesis_annotation_ref",
                "production_forecast_prob",
                "canonical_probability",
                "forecast_validity_status",
                "execution_authority_status",
                "actionability_status",
                "production_forecast_persisted",
                "writes_market_prediction",
                "artifact_sha256",
            }.issubset(decision_columns)
        )

        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            ensure_schema(conn)
            prediction_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(market_predictions)").fetchall()
            }

        self.assertTrue(
            {
                "prediction_run_id",
                "forecast_artifact_id",
                "case_key",
                "case_id",
                "dispatch_id",
                "engine_stage",
                "predicted_probability",
                "market_probability",
                "market_probability_method",
                "market_snapshot_id",
                "source_fetched_at",
                "source_payload_hash",
                "input_artifact_sha256",
                "prediction_artifact_sha256",
                "snapshot_age_seconds",
            }.issubset(prediction_columns)
        )

    def test_write_forecast_decision_uses_only_scae_probability_and_is_idempotent(self):
        self.conn.execute("CREATE TABLE market_predictions (id TEXT PRIMARY KEY, marker TEXT NOT NULL)")
        self.conn.execute("INSERT INTO market_predictions (id, marker) VALUES (?, ?)", ("existing", "unchanged"))
        before_market = self.conn.execute(
            "SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions"
        ).fetchone()
        ledger = self.finalized_ledger()
        gate = self.decision_gate(ledger)

        first = write_forecast_decision(self.conn, ledger, gate, metadata={"forecast_artifact_id": "forecast:1"})
        second = write_forecast_decision(self.conn, ledger, gate, metadata={"forecast_artifact_id": "forecast:1"})

        self.assertEqual(first["forecast_decision_id"], second["forecast_decision_id"])
        self.assertEqual(first["schema_version"], PERSIST001_SCHEMA_VERSION)
        self.assertEqual(first["production_forecast_prob"], ledger["production_forecast_prob"])
        self.assertFalse(first["scoreable_forecast_output"])
        self.assertIn("market_predictions", first["protected_downstream_tables_not_written"])

        row = self.conn.execute(
            f"""
            SELECT production_forecast_prob, canonical_probability, probability_source,
                   production_persistence_status, production_forecast_persisted,
                   scoreable_forecast_output, writes_market_prediction, decision_effect_status,
                   metadata_json
            FROM {FORECAST_DECISION_TABLE}
            """
        ).fetchone()
        self.assertEqual(row[0], ledger["production_forecast_prob"])
        self.assertEqual(row[1], ledger["canonical_probability"])
        self.assertEqual(row[2], "SCAE-012.production_forecast_prob")
        self.assertEqual(row[3], "production_forecast_persisted_from_scae")
        self.assertEqual(row[4:7], (1, 0, 0))
        self.assertEqual(row[7], "decision_preserved_scae_execution")
        self.assertEqual(json.loads(row[8])["forecast_artifact_id"], "forecast:1")
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {FORECAST_DECISION_TABLE}").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*), MIN(marker), MAX(marker) FROM market_predictions").fetchone(),
            before_market,
        )

    def test_forecast_decision_records_decision_downgrade_without_modifying_probability(self):
        ledger = self.finalized_ledger()
        gate = self.decision_gate(
            ledger,
            forecast_validity_status="valid_for_forecast_watch_only",
            execution_authority_status="watch_only",
            actionability_status="non_actionable",
        )

        result = write_forecast_decision(self.conn, ledger, gate)

        self.assertEqual(result["production_forecast_prob"], ledger["production_forecast_prob"])
        row = self.conn.execute(
            f"""
            SELECT forecast_validity_status, execution_authority_status,
                   actionability_status, decision_effect_status
            FROM {FORECAST_DECISION_TABLE}
            """
        ).fetchone()
        self.assertEqual(
            row,
            (
                "valid_for_forecast_watch_only",
                "watch_only",
                "non_actionable",
                "decision_downgraded_execution_or_actionability",
            ),
        )

    def test_invalid_forecast_decision_writes_blocked_status_without_probability(self):
        ledger = self.invalid_ledger()
        gate = self.decision_gate(ledger)

        result = write_forecast_decision(self.conn, ledger, gate)

        self.assertEqual(result["production_persistence_status"], "blocked_invalid_scae_forecast")
        self.assertIsNone(result["production_forecast_prob"])
        row = self.conn.execute(
            f"""
            SELECT production_forecast_prob, canonical_probability,
                   production_forecast_persisted, forecast_validity_status,
                   execution_authority_status, actionability_status,
                   non_scoreable_reason_code
            FROM {FORECAST_DECISION_TABLE}
            """
        ).fetchone()
        self.assertEqual(
            row,
            (
                None,
                None,
                0,
                "invalid_for_forecast",
                "forbidden",
                "non_actionable",
                "forecast_validity_invalid_for_forecast",
            ),
        )

    def test_forecast_decision_rejects_decision_replacement_probability(self):
        ledger = self.finalized_ledger()
        gate = self.decision_gate(ledger)
        gate["replacement_probability"] = 0.72
        with self.assertRaisesRegex(ScaePersistenceError, "replacement_probability"):
            write_forecast_decision(self.conn, ledger, gate)

        mismatched = self.decision_gate(ledger)
        mismatched["scae_context"]["production_forecast_prob"] = 0.72
        with self.assertRaisesRegex(ScaePersistenceError, "replace SCAE production_forecast_prob"):
            write_forecast_decision(self.conn, ledger, mismatched)

    def test_forecast_decision_rejects_market_prediction_and_scoring_authority(self):
        ledger = self.finalized_ledger()
        gate = self.decision_gate(ledger)
        gate["writes_market_prediction"] = True
        with self.assertRaisesRegex(ScaePersistenceError, "writes_market_prediction"):
            write_forecast_decision(self.conn, ledger, gate)

        gate = self.decision_gate(ledger)
        gate["scoreable_forecast_output"] = True
        with self.assertRaisesRegex(ScaePersistenceError, "scoreable_forecast_output"):
            write_forecast_decision(self.conn, ledger, gate)

    def test_scae_market_prediction_bridge_uses_scae_probability_and_contract_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, later_snapshot_id = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)

            first = write_scae_market_prediction(
                db_path,
                ledger,
                gate,
                contract,
                metadata={"forecast_decision_artifact_path": "artifacts/forecast-decision.json"},
            )
            second = write_scae_market_prediction(
                db_path,
                ledger,
                gate,
                contract,
                metadata={"forecast_decision_artifact_path": "artifacts/forecast-decision.json"},
            )

            self.assertEqual(first["schema_version"], PERSIST002_SCHEMA_VERSION)
            self.assertTrue(first["market_prediction_written"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(first["production_forecast_prob"], ledger["production_forecast_prob"])
            self.assertEqual(first["market_snapshot_id"], snapshot_id)
            self.assertNotEqual(first["market_snapshot_id"], later_snapshot_id)
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT predicted_probability, market_snapshot_id, market_probability,
                           market_probability_method, prediction_run_id, forecast_artifact_id,
                           case_id, dispatch_id, engine_stage, prediction_source,
                           source_payload_hash, scoring_version, metadata
                    FROM market_predictions
                    """
                ).fetchone()
                forecast_rows = conn.execute(
                    f"SELECT COUNT(*) FROM {FORECAST_DECISION_TABLE}"
                ).fetchone()[0]
            self.assertEqual(row[0], ledger["production_forecast_prob"])
            self.assertEqual(row[1], snapshot_id)
            self.assertEqual(row[2], 0.47)
            self.assertEqual(row[3], "bid_ask_midpoint")
            self.assertEqual(row[4], "prediction-run:scae-1")
            self.assertEqual(row[5], "forecast-artifact:scae-1")
            self.assertEqual(row[6:10], ("case-1", "dispatch-1", "scae", "ads_pipeline"))
            self.assertEqual(row[10], "sha256:" + "e" * 64)
            self.assertIsNone(row[11])
            self.assertEqual(forecast_rows, 1)
            metadata = json.loads(row[12])
            self.assertEqual(metadata["scoreable_prediction_source"], "scae.production_forecast_prob")
            self.assertEqual(metadata["contract_market_snapshot_id"], snapshot_id)

    def test_scae_market_prediction_bridge_blocks_valid_non_scoreable_ledger_without_prediction_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            ledger["scoreable_forecast_output"] = False
            ledger["market_prediction_write_expected"] = False
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)

            result = write_scae_market_prediction(db_path, ledger, gate, contract)

            self.assertFalse(result["market_prediction_written"])
            self.assertFalse(result["scoreable_forecast_output"])
            self.assertEqual(result["block_reason_code"], "scoreable_forecast_output_not_expected")
            self.assertTrue(result["forecast_decision_id"].startswith("forecast-decision-"))
            with sqlite3.connect(db_path) as conn:
                prediction_count = conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]
                decision = conn.execute(
                    f"""
                    SELECT production_persistence_status, production_forecast_persisted,
                           production_forecast_prob, scoreable_forecast_output,
                           writes_market_prediction
                    FROM {FORECAST_DECISION_TABLE}
                    """
                ).fetchone()
            self.assertEqual(prediction_count, 0)
            self.assertEqual(decision[0], "production_forecast_persisted_from_scae")
            self.assertEqual(decision[1], 1)
            self.assertEqual(decision[2], ledger["production_forecast_prob"])
            self.assertEqual(decision[3:], (0, 0))

    def test_scae_market_prediction_bridge_blocks_scoreable_ledger_without_verified_delta_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            ledger["scae_evidence_delta_ref_requirement_status"] = "verified_scae_evidence_delta_refs_missing"
            ledger["scae_evidence_delta_ref_count"] = 0
            ledger["scae_evidence_delta_refs"] = []
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)

            result = write_scae_market_prediction(db_path, ledger, gate, contract)

            self.assertFalse(result["market_prediction_written"])
            self.assertFalse(result["scoreable_forecast_output"])
            self.assertEqual(result["block_reason_code"], "verified_scae_evidence_delta_refs_missing")
            with sqlite3.connect(db_path) as conn:
                prediction_count = conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]
                decision_count = conn.execute(f"SELECT COUNT(*) FROM {FORECAST_DECISION_TABLE}").fetchone()[0]
            self.assertEqual(prediction_count, 0)
            self.assertEqual(decision_count, 1)

    def test_scae_market_prediction_bridge_scores_against_prediction_time_market_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)

            prediction = write_scae_market_prediction(db_path, ledger, gate, contract)
            score = write_resolution_score(
                db_path=db_path,
                external_market_id="scae-market-1",
                outcome=1.0,
                resolved_at="2026-06-26T12:00:00+00:00",
                resolution_source="polymarket-resolution-sync",
                resolution_payload={"result": "yes", "source_id": "scae-score-fixture"},
                resolution_method="api",
                prediction_source="ads_pipeline",
                prediction_label="v2_scae",
            )

            self.assertEqual(score["feature_id"], "SCORE-001")
            self.assertEqual(score["settled_market"]["updated_predictions"], 1)
            self.assertEqual(score["scorecards"]["written_scorecards"], 1)
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                prediction_row = conn.execute(
                    """
                    SELECT prediction_brier, market_brier, scoring_version,
                           scoring_resolution_payload_hash, market_snapshot_id,
                           market_probability, market_probability_method
                    FROM market_predictions
                    WHERE id = ?
                    """,
                    (prediction["prediction_id"],),
                ).fetchone()
                scorecard = conn.execute(
                    "SELECT prediction_brier, market_brier, metadata FROM evaluator_scorecards"
                ).fetchone()

            self.assertAlmostEqual(
                prediction_row["prediction_brier"],
                (ledger["production_forecast_prob"] - 1.0) ** 2,
            )
            self.assertAlmostEqual(prediction_row["market_brier"], (0.47 - 1.0) ** 2)
            self.assertEqual(prediction_row["scoring_version"], BRIER_SCORING_VERSION)
            self.assertEqual(
                prediction_row["scoring_resolution_payload_hash"],
                payload_hash({"result": "yes", "source_id": "scae-score-fixture"}),
            )
            self.assertEqual(prediction_row["market_snapshot_id"], snapshot_id)
            self.assertEqual(prediction_row["market_probability"], 0.47)
            self.assertEqual(prediction_row["market_probability_method"], "bid_ask_midpoint")
            self.assertEqual(scorecard["prediction_brier"], prediction_row["prediction_brier"])
            self.assertEqual(scorecard["market_brier"], prediction_row["market_brier"])
            metadata = json.loads(scorecard["metadata"])
            self.assertEqual(metadata["prediction_id"], prediction["prediction_id"])
            self.assertEqual(metadata["market_snapshot_id"], snapshot_id)
            self.assertEqual(metadata["scoring_version"], BRIER_SCORING_VERSION)
            self.assertEqual(
                metadata["resolution_payload_hash"],
                prediction_row["scoring_resolution_payload_hash"],
            )

    def test_scae_market_prediction_bridge_blocks_invalid_forecast_without_prediction_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.invalid_ledger()
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)

            result = write_scae_market_prediction(db_path, ledger, gate, contract)

            self.assertFalse(result["market_prediction_written"])
            self.assertEqual(result["block_reason_code"], "forecast_decision_non_scoreable")
            with sqlite3.connect(db_path) as conn:
                prediction_count = conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]
                forecast_count = conn.execute(
                    f"SELECT COUNT(*) FROM {FORECAST_DECISION_TABLE}"
                ).fetchone()[0]
            self.assertEqual(prediction_count, 0)
            self.assertEqual(forecast_count, 1)

    def test_scae_market_prediction_bridge_blocks_stale_snapshot_without_fresh_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(
                ledger,
                market_id,
                snapshot_id,
                age_seconds=7200,
                max_age_seconds=3600,
            )

            result = write_scae_market_prediction(db_path, ledger, gate, contract)

            self.assertFalse(result["market_prediction_written"])
            self.assertEqual(result["block_reason_code"], "stale_market_snapshot")
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0], 0)

    def test_scae_market_prediction_bridge_records_fresh_snapshot_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(
                ledger,
                market_id,
                snapshot_id,
                age_seconds=7200,
                max_age_seconds=3600,
            )

            result = write_scae_market_prediction(
                db_path,
                ledger,
                gate,
                contract,
                fresh_snapshot_payload=self.fresh_snapshot_payload(),
            )

            self.assertTrue(result["market_prediction_written"])
            self.assertNotEqual(result["market_snapshot_id"], snapshot_id)
            with sqlite3.connect(db_path) as conn:
                prediction = conn.execute(
                    "SELECT market_snapshot_id, source_payload_hash, snapshot_age_seconds FROM market_predictions"
                ).fetchone()
                snapshot_count = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
            self.assertEqual(prediction[0], result["market_snapshot_id"])
            self.assertRegex(prediction[1], r"^[0-9a-f]{64}$")
            self.assertEqual(prediction[2], 30.0)
            self.assertEqual(snapshot_count, 3)

    def test_scae_market_prediction_bridge_rejects_decision_replacement_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "predictions.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            gate["scae_context"]["production_forecast_prob"] = 0.72
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)

            with self.assertRaisesRegex(ScaePersistenceError, "replace SCAE production_forecast_prob"):
                write_scae_market_prediction(db_path, ledger, gate, contract)
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0], 0)

    def test_persist_scae_forecast_cli_writes_forecast_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "forecast.sqlite3"
            ledger_path = tmp_path / "ledger.json"
            gate_path = tmp_path / "decision.json"
            output_path = tmp_path / "result.json"
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            gate_path.write_text(json.dumps(gate), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "bin" / "persist_scae_forecast.py"),
                    "--db-path",
                    str(db_path),
                    "--scae-ledger",
                    str(ledger_path),
                    "--decision-gate",
                    str(gate_path),
                    "--metadata-json",
                    '{"forecast_artifact_id":"forecast:cli"}',
                    "--output",
                    str(output_path),
                ],
                check=True,
            )

            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["production_forecast_prob"], ledger["production_forecast_prob"])
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    f"SELECT production_forecast_prob, metadata_json FROM {FORECAST_DECISION_TABLE}"
                ).fetchone()
            self.assertEqual(row[0], ledger["production_forecast_prob"])
            self.assertEqual(json.loads(row[1])["forecast_artifact_id"], "forecast:cli")

    def test_persist_scae_forecast_cli_records_market_prediction_with_case_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "forecast.sqlite3"
            market_id, snapshot_id, _ = self.seed_prediction_market(db_path)
            ledger_path = tmp_path / "ledger.json"
            gate_path = tmp_path / "decision.json"
            contract_path = tmp_path / "contract.json"
            output_path = tmp_path / "result.json"
            ledger = self.finalized_ledger()
            gate = self.decision_gate(ledger)
            contract = self.ads_case_contract(ledger, market_id, snapshot_id)
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            gate_path.write_text(json.dumps(gate), encoding="utf-8")
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "bin" / "persist_scae_forecast.py"),
                    "--db-path",
                    str(db_path),
                    "--scae-ledger",
                    str(ledger_path),
                    "--decision-gate",
                    str(gate_path),
                    "--ads-case-contract",
                    str(contract_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
            )

            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["schema_version"], PERSIST002_SCHEMA_VERSION)
            self.assertTrue(result["market_prediction_written"])
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT predicted_probability, market_snapshot_id FROM market_predictions"
                ).fetchone()
            self.assertEqual(row[0], ledger["production_forecast_prob"])
            self.assertEqual(row[1], snapshot_id)


if __name__ == "__main__":
    unittest.main()
