import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.policy import default_scae_policy, validate_scae_policy
from scae.prior import build_market_assimilation_context, build_prior_context


class ScaePriorTest(unittest.TestCase):
    def setUp(self):
        self.policy = default_scae_policy()

    def prior_inputs(self, *, freshness="fresh", spread=0.02, depth=1500.0, volume=1500.0):
        return {
            "schema_version": "prior-reliability-inputs/v1",
            "rolling_microstructure": {
                "bid_ask_spread_latest": spread,
                "order_book_depth_latest": depth,
                "recent_volume_rolling": {"latest": volume},
                "open_interest_latest": 500.0,
                "last_trade_age_seconds_rolling": 90.0,
                "market_priced_through_timestamp": "2026-06-24T18:00:00+00:00",
                "market_snapshot_freshness": {"status": freshness},
            },
            "quote_observation_refs": [{"ref_id": "quote:1"}],
            "reason_code_candidates": [
                {"code": "fresh_liquid_market_candidate"} if freshness == "fresh" and volume >= 1000 else
                {"code": "prior_snapshot_stale_candidate"} if freshness == "stale" else
                {"code": "quote_observations_unavailable"}
            ],
        }

    def test_invalid_market_prior_falls_back_to_materialized_structural_prior(self):
        context = build_prior_context(
            market_prior={"source": "market_live_probability", "probability": 1.2, "valid": False},
            structural_prior={
                "probability": 0.35,
                "valid": True,
                "materialized_by_preledger_provider": True,
                "prior_ref": "base-rate:fixture",
            },
            prior_reliability_inputs=self.prior_inputs(),
            policy=self.policy,
        )

        self.assertEqual(context["prior_source"], "structural_base_rate_prior")
        self.assertEqual(context["shrink_target_type"], "structural_base_rate")
        self.assertEqual(context["adjusted_prior_probability"], 0.35)
        self.assertIn("market_prior_probability_invalid", context["uncertainty_flags"])

    def test_neutral_fallback_when_no_materialized_structural_prior_exists(self):
        context = build_prior_context(
            market_prior={"source": "market_live_probability", "probability": None, "valid": False},
            structural_prior={"probability": 0.40, "valid": True, "materialized_by_preledger_provider": False},
            prior_reliability_inputs=self.prior_inputs(freshness="unavailable", spread=None, depth=None, volume=None),
            policy=self.policy,
        )

        self.assertEqual(context["prior_source"], "neutral_default_prior")
        self.assertEqual(context["adjusted_prior_probability"], 0.5)
        self.assertIn("neutral_default_used", context["uncertainty_flags"])
        self.assertIn("structural_prior_not_materialized_by_preledger_provider", context["uncertainty_flags"])

    def test_fresh_liquid_market_prior_gets_reliability_floor_without_contradiction(self):
        context = build_prior_context(
            market_prior={"source": "market_live_probability", "probability": 0.70, "valid": True},
            structural_prior=None,
            prior_reliability_inputs=self.prior_inputs(spread=0.18, depth=1200.0, volume=2000.0),
            policy=self.policy,
        )

        self.assertEqual(context["prior_reliability_class"], "fresh_liquid")
        self.assertGreaterEqual(
            context["prior_reliability_score"],
            self.policy["prior_reliability"]["fresh_liquid_reliability_floor"],
        )
        self.assertIn("fresh_liquid_floor_applied", context["reliability_flags"])

    def test_stale_thin_market_prior_gets_reliability_ceiling(self):
        context = build_prior_context(
            market_prior={"source": "market_live_probability", "probability": 0.70, "valid": True},
            structural_prior=None,
            prior_reliability_inputs=self.prior_inputs(freshness="stale", spread=0.20, depth=25.0, volume=10.0),
            policy=self.policy,
        )

        self.assertEqual(context["prior_reliability_class"], "stale_thin")
        self.assertLessEqual(
            context["prior_reliability_score"],
            self.policy["prior_reliability"]["stale_thin_reliability_ceiling"],
        )
        self.assertIn("stale_thin_ceiling_applied", context["reliability_flags"])

    def test_old_public_evidence_gets_market_assimilation_discount(self):
        prior_context = build_prior_context(
            market_prior={"source": "market_live_probability", "probability": 0.62, "valid": True},
            structural_prior=None,
            prior_reliability_inputs=self.prior_inputs(),
            policy=self.policy,
        )
        assimilation = build_market_assimilation_context(
            evidence={
                "evidence_ref": "ev:public-old",
                "publicness": "public",
                "published_at": "2026-06-24T17:00:00+00:00",
            },
            prior_context=prior_context,
            policy=self.policy,
        )

        self.assertEqual(
            assimilation["market_assimilation_discount"],
            self.policy["market_assimilation"]["old_public_evidence_discount_fresh_liquid"],
        )
        self.assertEqual(assimilation["signed_delta_context"], "discount_public_priced_through_market")

    def test_base_rate_overlap_with_shrinkage_anchor_gets_zero_delta_context(self):
        prior_context = build_prior_context(
            market_prior={"source": "market_live_probability", "probability": 0.70, "valid": True},
            structural_prior={
                "probability": 0.40,
                "valid": True,
                "materialized_by_preledger_provider": True,
                "prior_ref": "base-rate:fixture",
            },
            prior_reliability_inputs=self.prior_inputs(freshness="stale", spread=0.18, depth=25.0, volume=10.0),
            policy=self.policy,
        )
        assimilation = build_market_assimilation_context(
            evidence={
                "evidence_ref": "ev:base-rate-duplicate",
                "evidence_kind": "base_rate",
                "base_rate_ref": "base-rate:fixture",
                "published_at": "2026-06-24T16:00:00+00:00",
            },
            prior_context=prior_context,
            policy=self.policy,
        )

        self.assertEqual(assimilation["suggested_signed_delta_multiplier"], 0.0)
        self.assertEqual(assimilation["signed_delta_context"], "zero_duplicate_base_rate_prior")
        self.assertIn("base_rate_overlap_zero_signed_delta", assimilation["reason_codes"])

    def test_policy_schema_accepts_phase_two_prior_sections(self):
        validate_scae_policy(self.policy)


if __name__ == "__main__":
    unittest.main()
