import copy
import json
import sqlite3
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.intervals import build_pre_debt_ledger_output  # noqa: E402
from scae.ledger import apply_research_sufficiency_guard, finalize_scae_probability_fields  # noqa: E402
from scae.persistence import (  # noqa: E402
    MIG007_TABLES,
    MISSINGNESS_SIGNAL_TABLE,
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
    ensure_scae_ledger_schema,
    write_scae_ledger,
    write_scae_log_odds_update_slices,
    write_scae_research_sufficiency_inputs,
)
from scae.policy import default_scae_policy  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
