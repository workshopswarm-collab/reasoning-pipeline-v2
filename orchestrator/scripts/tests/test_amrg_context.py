import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import (
    AMRG_VECTOR_CANDIDATE_SOURCE,
    AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION,
    NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION,
    RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION,
    WEAK_CONTEXT_ONLY,
    build_related_live_market_context_or_waiver,
    build_unavailable_vector_source_diagnostic,
    materialize_related_live_market_context,
)
from predquant.evidence_packet import EVIDENCE_PACKET_SCHEMA_VERSION, PRIOR_RELIABILITY_INPUT_SCHEMA_VERSION


class AMRGContextTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.artifact_dir = Path(self.tempdir.name) / "artifacts"
        self.source_cutoff = "2026-06-24T18:00:00+00:00"

    def tearDown(self):
        self.tempdir.cleanup()

    def evidence_packet(self, **overrides):
        packet = {
            "artifact_type": "evidence_packet",
            "schema_version": EVIDENCE_PACKET_SCHEMA_VERSION,
            "case_contract_ref": "artifact:case-contract",
            "case_id": "case-fixture",
            "case_key": "polymarket:poly-1:2026-06-24T18:00:00+00:00",
            "market_id": 1,
            "dispatch_id": "dispatch-fixture",
            "forecast_timestamp": "2026-06-24T18:00:00+00:00",
            "source_cutoff_timestamp": self.source_cutoff,
            "market_identity": {
                "internal_market_id": 1,
                "external_market_id": "poly-1",
                "platform": "polymarket",
                "title": "Will Fixture Labs win the election?",
                "description": "Fixture Labs election market",
                "category": "politics",
                "status": "open",
                "outcome_type": "binary",
                "closes_at": "2026-06-25T00:00:00+00:00",
                "resolves_at": "2026-06-26T00:00:00+00:00",
                "source_of_truth_kind": "official",
                "source_url": "https://example.test/results",
            },
            "market_reality_constraints": {
                "side_mapping": {
                    "yes": {"outcome": "yes", "resolves_to": "market_resolves_yes"},
                    "no": {"outcome": "no", "resolves_to": "market_resolves_no"},
                },
                "axis_mapping": {
                    "probability_axis": "selected_market_yes_probability",
                    "scale": "0_to_1",
                    "favorable_side": "yes",
                    "unfavorable_side": "no",
                    "side_directions": {
                        "yes": {
                            "higher_probability_means": "market_resolves_yes",
                            "lower_probability_means": "market_resolves_no",
                        },
                        "no": {
                            "higher_probability_means": "market_resolves_no",
                            "lower_probability_means": "market_resolves_yes",
                        },
                    },
                },
                "source_of_truth_status": "clear",
                "contract_structure": "binary",
                "close_timestamp": "2026-06-25T00:00:00+00:00",
                "resolve_timestamp": "2026-06-26T00:00:00+00:00",
            },
            "family_context": {
                "mode": "standalone_binary",
                "parent_event_id": None,
                "selected_child_market_id": "poly-1",
                "sibling_child_ids": [],
                "family_type": "none",
                "relation_constraints": [],
                "sibling_prices": [],
                "family_validation_flags": [],
            },
            "prior_context_seed": {
                "market_live_probability": 0.52,
                "market_probability_method": "midpoint_bid_ask",
                "market_snapshot_id": 10,
                "market_snapshot_timestamp": "2026-06-24T17:58:00+00:00",
                "snapshot_age_seconds_at_dispatch": 120.0,
                "quote_observation_refs": [],
                "microstructure_input_refs": [],
                "market_priced_through_timestamp": self.source_cutoff,
                "compact_snapshot_fields": {},
            },
            "prior_reliability_inputs": {
                "schema_version": PRIOR_RELIABILITY_INPUT_SCHEMA_VERSION,
                "authority": "candidate_inputs_only_no_scae_probability",
                "policy": {},
                "lookback_window": {
                    "source": "compact_quote_observations",
                    "observation_count": 0,
                    "first_observed_at": None,
                    "latest_observed_at": None,
                },
                "quote_observation_refs": [],
                "compact_quote_observations": [],
                "rolling_microstructure": {
                    "bid_ask_spread_twap": None,
                    "bid_ask_spread_latest": None,
                    "bid_ask_spread_max": None,
                    "order_book_depth_twap": None,
                    "order_book_depth_latest": None,
                    "recent_volume_rolling": {"latest": None, "max": None},
                    "open_interest_latest": None,
                    "last_trade_age_seconds_rolling": None,
                    "market_snapshot_age_seconds": 120.0,
                    "market_snapshot_freshness": {
                        "status": "fresh",
                        "fresh_snapshot_seconds": 300.0,
                        "stale_snapshot_seconds": 900.0,
                    },
                    "market_priced_through_timestamp": self.source_cutoff,
                    "microstructure_spoofing_check_status": "not_evaluated_candidate_input_only",
                },
                "reason_code_candidates": [],
            },
            "regime_seed_fields": {
                "platform": "polymarket",
                "category": "politics",
                "status": "open",
                "outcome_type": "binary",
                "contract_structure": "binary",
                "family_type": "none",
                "close_timestamp": "2026-06-25T00:00:00+00:00",
                "resolve_timestamp": "2026-06-26T00:00:00+00:00",
            },
            "active_safe_refs": {
                "ads_case_contract": "artifact:case-contract",
                "source_payload_hash": "sha256:fixture",
                "market_snapshot_id": 10,
            },
        }
        packet.update(overrides)
        return packet

    def market(self, market_id, **overrides):
        values = {
            "id": market_id,
            "external_market_id": f"poly-{market_id}",
            "status": "open",
            "title": f"Will Fixture Labs related event {market_id} happen?",
            "description": "Active-safe related market",
            "category": "politics",
            "outcome_type": "binary",
            "closes_at": "2026-06-25T00:00:00+00:00",
            "resolves_at": "2026-06-26T00:00:00+00:00",
            "normalized_entities": ["fixture labs"],
            "contract_terms": ["election"],
            "source_of_truth_kind": "official",
            "source_url": "https://example.test/results",
            "family_context_tokens": [],
        }
        values.update(overrides)
        return values

    def build_artifact(self, markets, **kwargs):
        return build_related_live_market_context_or_waiver(
            evidence_packet=self.evidence_packet(),
            evidence_packet_ref="artifact:evidence-packet",
            active_market_index=markets,
            **kwargs,
        )

    def test_empty_candidate_pool_produces_explicit_manifested_waiver(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            result = materialize_related_live_market_context(
                conn,
                evidence_packet=self.evidence_packet(),
                evidence_packet_ref="artifact:evidence-packet",
                artifact_dir=self.artifact_dir,
                active_market_index=[],
                vector_source_diagnostics=build_unavailable_vector_source_diagnostic(
                    "vector_index_missing",
                    source_cutoff_timestamp=self.source_cutoff,
                ),
            )
            waiver = result["artifact"]
            self.assertEqual(waiver["schema_version"], NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION)
            self.assertEqual(waiver["reason_code"], "empty_active_safe_candidate_pool")
            self.assertTrue(waiver["non_blocking"])
            self.assertEqual(waiver["candidates"], [])
            self.assertEqual(waiver["relationship_edges"], [])

            manifest_row = conn.execute(
                """
                SELECT artifact_type, artifact_schema_version, stage, validation_status
                FROM case_artifact_manifest
                WHERE artifact_id = ?
                """,
                (result["artifact_id"],),
            ).fetchone()
            self.assertEqual(manifest_row["artifact_type"], "no-related-context-waiver")
            self.assertEqual(manifest_row["artifact_schema_version"], NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION)
            self.assertEqual(manifest_row["stage"], "amrg")
            self.assertEqual(manifest_row["validation_status"], "valid")
        finally:
            conn.close()

    def test_candidate_cap_dedupe_and_deterministic_order(self):
        markets = [
            self.market(3, title="Will Fixture Labs event C happen?"),
            self.market(2, title="Will Fixture Labs event B happen?"),
            self.market(2, title="Will Fixture Labs duplicate event B happen?"),
            self.market(4, title="Will Fixture Labs event D happen?"),
        ]

        first = self.build_artifact(markets, candidate_cap=2)
        second = self.build_artifact(list(reversed(markets)), candidate_cap=2)

        self.assertEqual(first["schema_version"], RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(len(first["candidates"]), 2)
        self.assertEqual([candidate["market_id"] for candidate in first["candidates"]], [2, 3])
        self.assertEqual(first["candidate_set_id"], second["candidate_set_id"])
        self.assertEqual([candidate["candidate_id"] for candidate in first["candidates"]], [candidate["candidate_id"] for candidate in second["candidates"]])
        self.assertIn("entity_match", first["candidates"][0]["candidate_sources"])
        self.assertIn("contract_source_match", first["candidates"][0]["candidate_sources"])

    def test_resolved_past_and_unsafe_sources_are_excluded(self):
        artifact = self.build_artifact(
            [
                self.market(2, status="closed"),
                self.market(3, closes_at="2026-06-24T17:59:00+00:00"),
                self.market(4, raw_payload="must-not-copy"),
            ]
        )

        self.assertEqual(artifact["artifact_type"], "no_related_context_waiver")
        self.assertEqual(artifact["exclusion_counts"]["inactive_or_resolved_market"], 1)
        self.assertEqual(artifact["exclusion_counts"]["past_market"], 1)
        self.assertEqual(artifact["exclusion_counts"]["unsafe_market_fields"], 1)
        serialized = json.dumps(artifact)
        self.assertNotIn("raw_payload", serialized)
        self.assertNotIn("must-not-copy", serialized)

    def test_generic_theme_candidate_remains_weak_context_only(self):
        artifact = self.build_artifact(
            [
                self.market(
                    2,
                    title="Will a policy bill pass?",
                    normalized_entities=[],
                    contract_terms=[],
                    source_of_truth_kind="different",
                    source_url="https://example.test/other",
                )
            ]
        )

        self.assertEqual(artifact["artifact_type"], "related_live_market_context")
        self.assertEqual(artifact["candidates"][0]["candidate_source"], "generic_theme_match")
        for candidate in artifact["candidates"]:
            self.assertEqual(candidate["relationship_status"], WEAK_CONTEXT_ONLY)
        for edge in artifact["relationship_edges"]:
            self.assertEqual(edge["relationship_status"], WEAK_CONTEXT_ONLY)
            self.assertIn("probability_authority", edge["forbidden_effects"])

    def test_vector_unavailable_is_non_blocking_with_deterministic_candidate(self):
        diagnostic = build_unavailable_vector_source_diagnostic(
            "ollama_route_unavailable",
            source_cutoff_timestamp=self.source_cutoff,
        )
        artifact = self.build_artifact([self.market(2)], vector_source_diagnostics=diagnostic)

        self.assertEqual(artifact["artifact_type"], "related_live_market_context")
        self.assertEqual(len(artifact["candidates"]), 1)
        self.assertEqual(artifact["vector_source_diagnostics"][0]["reason_code"], "amrg_vector_candidate_source_unavailable")
        self.assertTrue(artifact["vector_source_diagnostics"][0]["non_blocking"])

    def test_vector_candidates_integrate_as_capped_weak_context(self):
        vector_candidate = {
            "schema_version": AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION,
            "candidate_source": AMRG_VECTOR_CANDIDATE_SOURCE,
            "relationship_status": WEAK_CONTEXT_ONLY,
            "vector_only": True,
            "market_id": 2,
            "external_market_id": "poly-2",
            "similarity_score": 0.91,
            "similarity_metric": "cosine",
            "query_descriptor_sha256": "sha256:query",
            "candidate_descriptor_sha256": "sha256:candidate",
            "index_snapshot_id": "amrg-vector-index:fixture",
            "embedding_lane_id": "amrg_vector_embedding",
            "resolved_model_id": "BAAI/bge-base-en-v1.5",
            "route_id": "ollama/local",
        }
        artifact = build_related_live_market_context_or_waiver(
            evidence_packet=self.evidence_packet(
                market_identity={
                    **self.evidence_packet()["market_identity"],
                    "title": "Will a completely unrelated event happen?",
                    "category": "weather",
                    "source_of_truth_kind": "weather",
                    "source_url": "https://example.test/weather",
                },
                regime_seed_fields={
                    **self.evidence_packet()["regime_seed_fields"],
                    "category": "weather",
                },
            ),
            evidence_packet_ref="artifact:evidence-packet",
            active_market_index=[
                self.market(
                    2,
                    title="Will a sports team win?",
                    normalized_entities=[],
                    contract_terms=[],
                    category="sports",
                    source_of_truth_kind="sports",
                    source_url="https://example.test/sports",
                ),
                self.market(
                    3,
                    title="Will another sports team win?",
                    normalized_entities=[],
                    contract_terms=[],
                    category="sports",
                    source_of_truth_kind="sports",
                    source_url="https://example.test/sports",
                ),
            ],
            vector_candidates=[vector_candidate],
            candidate_cap=1,
        )

        self.assertEqual(len(artifact["candidates"]), 1)
        self.assertEqual(artifact["candidates"][0]["candidate_source"], AMRG_VECTOR_CANDIDATE_SOURCE)
        self.assertEqual(artifact["candidates"][0]["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertTrue(artifact["candidates"][0]["vector_only"])


if __name__ == "__main__":
    unittest.main()
