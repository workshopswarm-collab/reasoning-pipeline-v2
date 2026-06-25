import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.family import (
    SCAE_FAMILY_DIAGNOSTICS_SCHEMA_VERSION,
    ScaeFamilyDiagnosticsError,
    build_family_diagnostics,
    validate_family_diagnostics,
)
from scae.policy import default_scae_policy, resolve_probability_taxonomy


class ScaeFamilyDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def evidence_packet(self, *, selected_price=0.40, sibling_prices=None, family_mode="family_aware_binary_child"):
        if sibling_prices is None:
            sibling_prices = [
                {"child_market_id": "poly-sibling-a", "price": 0.55, "price_method": "yes_price", "context_only": True},
                {"child_market_id": "poly-sibling-b", "price": 0.10, "price_method": "yes_price", "context_only": True},
            ]
        sibling_ids = ["poly-sibling-a", "poly-sibling-b"]
        if family_mode == "standalone_binary":
            family_context = {
                "mode": "standalone_binary",
                "parent_event_id": None,
                "selected_child_market_id": "poly-selected",
                "sibling_child_ids": [],
                "family_type": "none",
                "relation_constraints": [],
                "sibling_prices": [],
                "family_validation_flags": [],
            }
        else:
            family_context = {
                "mode": family_mode,
                "parent_event_id": "event-1",
                "selected_child_market_id": "poly-selected",
                "sibling_child_ids": sibling_ids,
                "family_type": "exclusive",
                "relation_constraints": ["exactly_one_child_resolves_yes"],
                "sibling_prices": sibling_prices,
                "family_validation_flags": ["sibling_prices_context_only"],
            }
        return {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            "case_contract_ref": "artifact:case-contract-1",
            "case_id": "case-1",
            "market_id": "market-1",
            "dispatch_id": "dispatch-1",
            "family_context": family_context,
            "prior_context_seed": {
                "market_live_probability": selected_price,
                "market_priced_through_timestamp": "2026-06-24T18:00:00+00:00",
            },
        }

    def test_family_aware_child_emits_displacement_and_consistency_diagnostics(self):
        diagnostics = build_family_diagnostics(self.evidence_packet(), policy=self.policy)

        self.assertEqual(diagnostics["schema_version"], SCAE_FAMILY_DIAGNOSTICS_SCHEMA_VERSION)
        self.assertEqual(diagnostics["diagnostic_status"], "emitted")
        self.assertEqual(diagnostics["family_context_summary"]["parent_event_id"], "event-1")
        self.assertEqual(diagnostics["family_context_summary"]["selected_child_market_id"], "poly-selected")
        self.assertEqual(diagnostics["sibling_price_context"]["known_sibling_price_count"], 2)
        self.assertTrue(diagnostics["sibling_price_context"]["sibling_prices_context_only"])
        self.assertEqual(diagnostics["displacement_signals"]["selected_child_market_price"], 0.40)
        self.assertEqual(diagnostics["displacement_signals"]["known_sibling_price_sum"], 0.65)
        self.assertEqual(diagnostics["displacement_signals"]["selected_rank_by_market_price"], 2)
        self.assertEqual(
            diagnostics["displacement_signals"]["strongest_sibling"]["child_market_id"],
            "poly-sibling-a",
        )
        self.assertEqual(
            diagnostics["displacement_signals"]["sibling_pressure_direction"],
            "strongest_sibling_above_selected",
        )
        self.assertEqual(
            diagnostics["consistency_diagnostics"]["family_price_mass_status"],
            "exclusive_price_mass_overfull",
        )
        self.assertIn("sibling_price_above_selected", diagnostics["consistency_diagnostics"]["diagnostic_flags"])
        validate_family_diagnostics(diagnostics)

    def test_sibling_prices_cannot_author_scae_updates_or_move_probability(self):
        taxonomy_before = resolve_probability_taxonomy(
            raw_ledger_probability=0.40,
            post_ledger_probability=0.41,
            debt_adjusted_probability=0.39,
            calibration_debt_active=False,
        )
        high_sibling = build_family_diagnostics(
            self.evidence_packet(
                selected_price=0.40,
                sibling_prices=[
                    {
                        "child_market_id": "poly-sibling-a",
                        "price": 0.90,
                        "price_method": "yes_price",
                        "context_only": True,
                    }
                ],
            ),
            policy=self.policy,
        )
        low_sibling = build_family_diagnostics(
            self.evidence_packet(
                selected_price=0.40,
                sibling_prices=[
                    {
                        "child_market_id": "poly-sibling-a",
                        "price": 0.05,
                        "price_method": "yes_price",
                        "context_only": True,
                    }
                ],
            ),
            policy=self.policy,
        )
        taxonomy_after = resolve_probability_taxonomy(
            raw_ledger_probability=0.40,
            post_ledger_probability=0.41,
            debt_adjusted_probability=0.39,
            calibration_debt_active=False,
        )

        self.assertEqual(taxonomy_before, taxonomy_after)
        for diagnostics in [high_sibling, low_sibling]:
            self.assertFalse(diagnostics["ledger_adjacency"]["may_mutate_scae_ledger"])
            self.assertFalse(diagnostics["ledger_adjacency"]["may_mutate_prior_context"])
            self.assertFalse(diagnostics["ledger_adjacency"]["may_move_probability"])
            self.assertEqual(
                diagnostics["no_update_guards"]["sibling_price_effect_on_scae_ledger"],
                "none_context_only",
            )
            self.assertEqual(diagnostics["no_update_guards"]["probability_movement_authority"], "none")
            self.assertFalse(diagnostics["no_update_guards"]["softmax_reallocation_applied"])
            serialized = json.dumps(diagnostics, sort_keys=True)
            self.assertNotIn("production_forecast_prob", serialized)
            self.assertNotIn("evidence_delta", serialized)
            self.assertNotIn("scae_evidence_delta", serialized)
            self.assertNotIn("signed_delta", serialized)
            self.assertNotIn("raw_market_log_odds", serialized)
            self.assertNotIn("adjusted_prior_probability", serialized)

    def test_family_diagnostics_do_not_mutate_evidence_packet_input(self):
        packet = self.evidence_packet()
        original = copy.deepcopy(packet)

        build_family_diagnostics(packet, policy=self.policy)

        self.assertEqual(packet, original)

    def test_context_only_and_selected_child_sibling_guards_fail_closed(self):
        packet = self.evidence_packet(
            sibling_prices=[
                {"child_market_id": "poly-sibling-a", "price": 0.55, "price_method": "yes_price", "context_only": False}
            ]
        )
        with self.assertRaisesRegex(ScaeFamilyDiagnosticsError, "context-only"):
            build_family_diagnostics(packet, policy=self.policy)

        selected_as_sibling = self.evidence_packet(
            sibling_prices=[
                {"child_market_id": "poly-selected", "price": 0.55, "price_method": "yes_price", "context_only": True}
            ]
        )
        with self.assertRaisesRegex(ScaeFamilyDiagnosticsError, "selected child"):
            build_family_diagnostics(selected_as_sibling, policy=self.policy)

    def test_standalone_binary_gets_not_applicable_diagnostic_sidecar(self):
        diagnostics = build_family_diagnostics(
            self.evidence_packet(family_mode="standalone_binary"),
            policy=self.policy,
        )

        self.assertEqual(diagnostics["diagnostic_status"], "not_applicable_standalone_binary")
        self.assertFalse(diagnostics["displacement_signals"]["applicable"])
        self.assertEqual(diagnostics["consistency_diagnostics"]["family_price_mass_status"], "not_applicable")
        self.assertFalse(diagnostics["ledger_adjacency"]["may_move_probability"])
        validate_family_diagnostics(diagnostics)


if __name__ == "__main__":
    unittest.main()
