import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import (
    AMRG_VECTOR_CANDIDATE_SOURCE,
    AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
    AMRG_REFRESH_LIFECYCLE_SCHEMA_VERSION,
    AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION,
    NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION,
    RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION,
    WEAK_CONTEXT_ONLY,
    build_amrg_model_assist_packet,
    build_related_live_market_context_or_waiver,
    build_unavailable_vector_source_diagnostic,
    build_model_assist_provenance,
    enrich_related_live_market_context,
    ensure_amrg_context_schema,
    materialize_related_live_market_context,
    model_assist_downgrade_for_missing_manifest,
    validate_amrg_model_assist_output,
    write_related_market_context,
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

    def test_relationship_typing_and_timing_alignment_can_add_safe_context_status(self):
        packet = self.evidence_packet()
        artifact = self.build_artifact([self.market(2)])
        enriched = enrich_related_live_market_context(artifact, evidence_packet=packet)
        edge = enriched["relationship_edges"][0]

        self.assertEqual(edge["timing_alignment_status"], "aligned")
        self.assertEqual(edge["relationship_status"], "deterministic_context_candidate")
        self.assertIn("shared_named_entity", edge["relationship_types"])
        self.assertIn("shared_contract_source", edge["relationship_types"])
        self.assertIn("retrieval_query_hint", edge["allowed_effects"])
        self.assertIn("probability_authority", edge["forbidden_effects"])
        self.assertIn("scae_delta", edge["forbidden_effects"])
        self.assertIn("qdt_selection", edge["forbidden_effects"])

    def test_timing_mismatch_prevents_stronger_effects(self):
        packet = self.evidence_packet()
        artifact = self.build_artifact([self.market(2)])
        artifact["candidates"][0]["timing_inputs"]["related_market_snapshot_as_of"] = "2026-06-24T17:00:00+00:00"
        enriched = enrich_related_live_market_context(artifact, evidence_packet=packet)
        edge = enriched["relationship_edges"][0]

        self.assertEqual(edge["timing_alignment_status"], "skew_exceeds_policy")
        self.assertEqual(edge["relationship_status"], "timing_mismatch_weak_context_only")
        self.assertEqual(edge["allowed_effects"], ["decomposition_context_hint"])
        self.assertNotIn("retrieval_query_hint", edge["allowed_effects"])

    def test_model_assist_forbidden_probability_output_is_rejected(self):
        artifact = self.build_artifact([self.market(2)])
        packet = build_amrg_model_assist_packet(artifact)
        self.assertEqual(packet["model_lane_id"], "amrg_model_assist")
        self.assertEqual(packet["authority"], "advisory_only_no_promotion")

        output = {
            "artifact_type": "amrg_model_assist_output",
            "schema_version": AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
            "model_lane_id": "amrg_model_assist",
            "resolved_model_id": packet["resolved_model_id"],
            "authority": "advisory_only_no_promotion",
            "candidate_set_id": artifact["candidate_set_id"],
            "edge_annotations": [
                {
                    "edge_id": artifact["relationship_edges"][0]["edge_id"],
                    "candidate_id": artifact["candidates"][0]["candidate_id"],
                    "suggested_relationship_types": ["shared_named_entity"],
                    "advisory_only": True,
                    "probability": 0.7,
                }
            ],
        }
        with self.assertRaisesRegex(Exception, "forbidden"):
            validate_amrg_model_assist_output(output)

    def test_model_assist_remains_advisory_and_model_only_candidate_stays_weak(self):
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
        packet = build_amrg_model_assist_packet(artifact)
        output = {
            "artifact_type": "amrg_model_assist_output",
            "schema_version": AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
            "model_lane_id": "amrg_model_assist",
            "resolved_model_id": packet["resolved_model_id"],
            "authority": "advisory_only_no_promotion",
            "candidate_set_id": artifact["candidate_set_id"],
            "edge_annotations": [
                {
                    "edge_id": artifact["relationship_edges"][0]["edge_id"],
                    "candidate_id": artifact["candidates"][0]["candidate_id"],
                    "suggested_relationship_types": ["generic_theme"],
                    "advisory_only": True,
                    "rationale_ref": "compact:theme",
                }
            ],
        }
        validate_amrg_model_assist_output(output)
        provenance = build_model_assist_provenance(artifact, packet=packet, output=output)
        enriched = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            model_assist_status=provenance["model_assist_status"],
        )

        edge = enriched["relationship_edges"][0]
        self.assertEqual(edge["relationship_status"], "model_assisted_weak_context_only")
        self.assertEqual(edge["allowed_effects"], ["decomposition_context_hint"])
        self.assertIn("edge_promotion", edge["forbidden_effects"])

        degraded = model_assist_downgrade_for_missing_manifest({**artifact, "input_manifest_hash": None})
        self.assertEqual(degraded["model_assist_status"], "not_invoked_missing_active_safe_manifest")
        self.assertEqual(degraded["forbidden_output_check_status"], "not_applicable")

    def test_refresh_success_retains_deterministic_effect_after_ttl_refresh(self):
        artifact = self.build_artifact([self.market(2)])
        edge_id = artifact["relationship_edges"][0]["edge_id"]
        refreshed = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            refresh_policy={
                "refresh_as_of_timestamp": "2026-06-24T18:30:00+00:00",
                "ttl_seconds": 900,
                "refresh_budget": 1,
            },
            refresh_results={
                edge_id: {
                    "ok": True,
                    "reason_codes": ["refresh_ok"],
                    "related_market_snapshot_as_of": "2026-06-24T18:29:00+00:00",
                    "selected_market_snapshot_as_of": "2026-06-24T18:28:00+00:00",
                    "material_change": False,
                }
            },
        )

        edge = refreshed["relationship_edges"][0]
        lifecycle = edge["refresh_lifecycle_state"]
        self.assertEqual(lifecycle["schema_version"], AMRG_REFRESH_LIFECYCLE_SCHEMA_VERSION)
        self.assertEqual(lifecycle["refresh_status"], "refresh_succeeded")
        self.assertTrue(lifecycle["refresh_attempted"])
        self.assertEqual(lifecycle["refresh_budget_consumed"], 1)
        self.assertFalse(lifecycle["stale_effect_downgrade_applied"])
        self.assertEqual(edge["relationship_status"], "deterministic_context_candidate")
        self.assertIn("retrieval_query_hint", edge["allowed_effects"])

    def test_stale_promoted_effect_without_refresh_downgrades_to_weak_context(self):
        artifact = self.build_artifact([self.market(2)])
        refreshed = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            refresh_policy={
                "refresh_as_of_timestamp": "2026-06-24T18:30:00+00:00",
                "ttl_seconds": 900,
                "refresh_budget": 1,
            },
        )

        edge = refreshed["relationship_edges"][0]
        lifecycle = edge["refresh_lifecycle_state"]
        self.assertEqual(lifecycle["refresh_status"], "stale_promoted_effect_downgraded_weak_context_only")
        self.assertTrue(lifecycle["stale_effect_downgrade_applied"])
        self.assertEqual(edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertEqual(edge["allowed_effects"], ["decomposition_context_hint"])

    def test_refresh_budget_exhaustion_downgrades_stale_promoted_effect(self):
        artifact = self.build_artifact([self.market(2)])
        refreshed = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            refresh_policy={
                "refresh_as_of_timestamp": "2026-06-24T18:30:00+00:00",
                "ttl_seconds": 900,
                "refresh_budget": 0,
            },
        )

        edge = refreshed["relationship_edges"][0]
        self.assertEqual(
            edge["refresh_lifecycle_state"]["refresh_status"],
            "refresh_budget_exhausted_downgraded_weak_context_only",
        )
        self.assertEqual(edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertIn("refresh_budget_exhausted", edge["downgrade_reason_codes"])

    def test_material_change_requires_deterministic_revalidation(self):
        artifact = self.build_artifact([self.market(2)])
        edge_id = artifact["relationship_edges"][0]["edge_id"]
        refreshed = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            refresh_policy={
                "refresh_as_of_timestamp": "2026-06-24T18:30:00+00:00",
                "ttl_seconds": 900,
                "refresh_budget": 1,
            },
            refresh_results={
                edge_id: {
                    "ok": True,
                    "reason_codes": ["refresh_ok"],
                    "related_market_snapshot_as_of": "2026-06-24T18:29:00+00:00",
                    "selected_market_snapshot_as_of": "2026-06-24T18:28:00+00:00",
                    "material_change": True,
                    "deterministic_validation_status": "not_evaluated",
                }
            },
        )

        edge = refreshed["relationship_edges"][0]
        lifecycle = edge["refresh_lifecycle_state"]
        self.assertEqual(lifecycle["refresh_status"], "material_change_downgraded_weak_context_only")
        self.assertTrue(lifecycle["material_change_detected"])
        self.assertEqual(edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertIn("material_change_requires_deterministic_revalidation", edge["downgrade_reason_codes"])

    def test_refresh_never_upgrades_advisory_or_vector_only_candidates(self):
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
        edge_id = artifact["relationship_edges"][0]["edge_id"]
        refreshed = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            model_assist_status="advisory_validated",
            refresh_policy={
                "refresh_as_of_timestamp": "2026-06-24T18:30:00+00:00",
                "ttl_seconds": 1,
                "refresh_budget": 1,
            },
            refresh_results={
                edge_id: {
                    "ok": True,
                    "material_change": True,
                    "deterministic_validation_status": "passed",
                    "related_market_snapshot_as_of": "2026-06-24T18:29:00+00:00",
                    "selected_market_snapshot_as_of": "2026-06-24T18:28:00+00:00",
                }
            },
        )

        edge = refreshed["relationship_edges"][0]
        self.assertEqual(edge["relationship_status"], "model_assisted_weak_context_only")
        self.assertEqual(edge["allowed_effects"], ["decomposition_context_hint"])
        self.assertEqual(edge["refresh_lifecycle_state"]["refresh_status"], "not_requested_no_promoted_effect")

    def test_refresh_result_forbids_scae_delta_payloads(self):
        artifact = self.build_artifact([self.market(2)])
        edge_id = artifact["relationship_edges"][0]["edge_id"]
        with self.assertRaisesRegex(Exception, "scae_evidence_delta"):
            enrich_related_live_market_context(
                artifact,
                evidence_packet=self.evidence_packet(),
                refresh_policy={
                    "refresh_as_of_timestamp": "2026-06-24T18:30:00+00:00",
                    "ttl_seconds": 900,
                    "refresh_budget": 1,
                },
                refresh_results={edge_id: {"ok": True, "scae_evidence_delta": 0.2}},
            )

    def test_amrg_persistence_schema_and_write_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            ensure_amrg_context_schema(conn)
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertIn("related_market_relationship_slices", table_names)
            self.assertIn("amrg_causal_graph_safety_slices", table_names)
            self.assertIn("related_market_refresh_events", table_names)
            self.assertIn("amrg_model_assist_provenance", table_names)
            self.assertIn("amrg_market_vector_descriptors", table_names)

            artifact = self.build_artifact([self.market(2)])
            packet = build_amrg_model_assist_packet(artifact)
            output = {
                "artifact_type": "amrg_model_assist_output",
                "schema_version": AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
                "model_lane_id": "amrg_model_assist",
                "resolved_model_id": packet["resolved_model_id"],
                "authority": "advisory_only_no_promotion",
                "candidate_set_id": artifact["candidate_set_id"],
                "edge_annotations": [
                    {
                        "edge_id": artifact["relationship_edges"][0]["edge_id"],
                        "candidate_id": artifact["candidates"][0]["candidate_id"],
                        "suggested_relationship_types": ["shared_named_entity"],
                        "advisory_only": True,
                    }
                ],
            }
            provenance = build_model_assist_provenance(artifact, packet=packet, output=output)
            result = write_related_market_context(
                conn,
                artifact,
                evidence_packet=self.evidence_packet(),
                model_assist_provenance=provenance,
                artifact_path="/tmp/related-live-market-context.json",
                artifact_sha256="sha256:artifact",
            )
            second = write_related_market_context(
                conn,
                artifact,
                evidence_packet=self.evidence_packet(),
                model_assist_provenance=provenance,
                artifact_path="/tmp/related-live-market-context.json",
                artifact_sha256="sha256:artifact",
            )

            self.assertEqual(len(result["candidate_row_ids"]), 1)
            self.assertEqual(len(result["relationship_slice_ids"]), 1)
            self.assertEqual(len(result["graph_safety_slice_ids"]), 1)
            self.assertEqual(len(result["refresh_event_ids"]), 1)
            self.assertEqual(result["refresh_event_ids"], second["refresh_event_ids"])
            self.assertIsNotNone(result["model_assist_id"])

            relationship = conn.execute(
                "SELECT relationship_types, timing_alignment_status, allowed_effects, forbidden_effects FROM related_market_relationship_slices"
            ).fetchone()
            self.assertIn("shared_named_entity", json.loads(relationship["relationship_types"]))
            self.assertEqual(relationship["timing_alignment_status"], "aligned")
            self.assertIn("retrieval_query_hint", json.loads(relationship["allowed_effects"]))
            self.assertIn("probability_authority", json.loads(relationship["forbidden_effects"]))

            refresh = conn.execute(
                """
                SELECT refresh_status, refresh_reason_codes, stale_effect_downgrade_applied,
                       next_refresh_after, metadata
                FROM related_market_refresh_events
                """
            ).fetchone()
            self.assertEqual(refresh["refresh_status"], "fresh_no_refresh_needed")
            self.assertIn("within_refresh_ttl", json.loads(refresh["refresh_reason_codes"]))
            self.assertEqual(refresh["stale_effect_downgrade_applied"], 0)
            self.assertIsNotNone(refresh["next_refresh_after"])
            self.assertEqual(json.loads(refresh["metadata"])["schema_version"], AMRG_REFRESH_LIFECYCLE_SCHEMA_VERSION)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM related_market_refresh_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM related_market_prior_anchor_slices").fetchone()[0], 0)
            scae_tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'scae_%'"
                ).fetchall()
            ]
            self.assertEqual(scae_tables, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
