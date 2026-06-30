import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import (
    AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION,
    AMRG_VECTOR_CANDIDATE_SOURCE,
    AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
    AMRG_REFRESH_LIFECYCLE_SCHEMA_VERSION,
    AMRG_SHARED_CACHE_ELIGIBILITY_SCHEMA_VERSION,
    AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION,
    NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION,
    RELATED_LIVE_MARKET_CONTEXT_SCHEMA_VERSION,
    WEAK_CONTEXT_ONLY,
    apply_shared_cache_reuse_eligibility,
    build_amrg_decomposer_context,
    build_amrg_model_assist_packet,
    build_amrg_operator_report,
    build_related_live_market_context_or_waiver,
    build_unavailable_vector_source_diagnostic,
    apply_strict_precedence_anchor_validation,
    build_model_assist_provenance,
    enrich_related_live_market_context,
    ensure_amrg_context_schema,
    invoke_amrg_model_assist,
    materialize_related_live_market_context,
    model_assist_downgrade_for_missing_manifest,
    resolve_amrg_model_assist_lane,
    validate_amrg_decomposer_context,
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

    def consuming_dispatch(self, **overrides):
        dispatch = {
            "dispatch_id": "dispatch-fixture",
            "leaf_condition_scope": "unconditional",
            "contract_scope": "binary:fixture-labs-election",
            "forecast_timestamp": "2026-06-24T18:00:00+00:00",
        }
        dispatch.update(overrides)
        return dispatch

    def shared_cache_entry(self, **overrides):
        entry = {
            "cache_entry_id": "shared-cache:retrieval:fixture",
            "cache_entry_type": "retrieval_evidence",
            "leaf_condition_scope": "unconditional",
            "contract_scope": "binary:fixture-labs-election",
            "temporal_provenance": {
                "max_underlying_source_timestamp": "2026-06-24T17:55:00+00:00",
            },
            "source_ref": "retrieval-evidence:fixture",
        }
        entry.update(overrides)
        return entry

    def ollama_embedding(self, first_value):
        vector = [0.0] * 768
        vector[0] = first_value
        vector[1] = 1.0 - first_value
        return vector

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
                SELECT artifact_type, artifact_schema_version, stage, validation_status, metadata
                FROM case_artifact_manifest
                WHERE artifact_id = ?
                """,
                (result["artifact_id"],),
            ).fetchone()
            self.assertEqual(manifest_row["artifact_type"], "no-related-context-waiver")
            self.assertEqual(manifest_row["artifact_schema_version"], NO_RELATED_CONTEXT_WAIVER_SCHEMA_VERSION)
            self.assertEqual(manifest_row["stage"], "amrg")
            self.assertEqual(manifest_row["validation_status"], "valid")
            metadata = json.loads(manifest_row["metadata"])
            self.assertEqual(
                metadata["amrg_decomposer_context_schema_version"],
                AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION,
            )
            self.assertEqual(metadata["amrg_decomposer_hint_count"], 0)
        finally:
            conn.close()

    def test_materialize_live_vector_model_assist_and_operator_report(self):
        class FakeOllama:
            base_url = "http://localhost:11434"

            def __init__(self, owner):
                self.owner = owner

            def version(self):
                return {"version": "0.9.0"}

            def show_model(self, model):
                return {"digest": "fixture-digest"}

            def embed(self, model, inputs, *, truncate=False, keep_alive=None):
                count = len(inputs) if isinstance(inputs, list) else 1
                return {
                    "embeddings": [
                        self.owner.ollama_embedding(1.0 if idx == 0 else 0.9 - (idx / 100))
                        for idx in range(count)
                    ]
                }

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            def model_assist_transport(packet):
                return {
                    "artifact_type": "amrg_model_assist_output",
                    "schema_version": AMRG_MODEL_ASSIST_OUTPUT_SCHEMA_VERSION,
                    "model_lane_id": "amrg_model_assist",
                    "resolved_model_id": packet["resolved_model_id"],
                    "authority": "advisory_only_no_promotion",
                    "candidate_set_id": packet["candidate_set_id"],
                    "edge_annotations": [],
                }

            result = materialize_related_live_market_context(
                conn,
                evidence_packet=self.evidence_packet(),
                evidence_packet_ref="artifact:evidence-packet",
                artifact_dir=self.artifact_dir,
                active_market_index=[self.market(2), self.market(3, title="Will unrelated beta happen?")],
                run_vector_runtime=True,
                ollama_client=FakeOllama(self),
                model_assist_transport=model_assist_transport,
            )

            artifact = result["artifact"]
            self.assertEqual(artifact["vector_runtime"]["status"], "ready")
            self.assertEqual(artifact["vector_readiness_status"], "vector_ready")
            self.assertEqual(artifact["vector_runtime"]["preflight_status"], "ok")
            self.assertEqual(artifact["vector_runtime"]["model_digest"], "sha256:fixture-digest")
            self.assertEqual(artifact["model_assist_status"], "advisory_validated")
            self.assertEqual(artifact["assist_readiness_status"], "assist_ready")
            self.assertEqual(artifact["amrg_operator_report"]["vector_readiness_status"], "vector_ready")
            self.assertEqual(artifact["amrg_operator_report"]["assist_readiness_status"], "assist_ready")
            self.assertEqual(artifact["refresh_policy"]["schema_version"], "amrg-refresh-policy/v1")
            self.assertEqual(artifact["refresh_policy"]["weak_relationship_context_ttl_seconds"], 24 * 60 * 60)
            self.assertTrue(result["vector_descriptor_ids"])
            self.assertIsNotNone(result["vector_index_snapshot_id"])
            self.assertTrue(result["vector_neighbor_candidate_ids"])
            self.assertIsNotNone(result["model_assist_id"])

            manifest_metadata = result["manifest"]["metadata"]
            self.assertEqual(manifest_metadata["amrg_vector_status"], "ready")
            self.assertEqual(manifest_metadata["amrg_vector_readiness_status"], "vector_ready")
            self.assertEqual(manifest_metadata["amrg_model_assist_status"], "advisory_validated")
            self.assertEqual(manifest_metadata["amrg_assist_readiness_status"], "assist_ready")
            self.assertEqual(
                manifest_metadata["amrg_operator_report_schema_version"],
                "amrg-operator-report/v1",
            )

            hint_ref = artifact["amrg_decomposer_context"]["hints"][0]["hint_ref"]
            qdt_report = build_amrg_operator_report(
                artifact,
                question_decomposition={
                    "required_leaf_questions": [{"leaf_id": "leaf-1", "amrg_usage_refs": [hint_ref]}],
                    "branches": [],
                    "related_market_context_usage": {
                        "usage_status": "used_context_hints",
                        "related_context_artifact_ref": "artifact:related-live-market-context",
                        "amrg_usage_refs": [hint_ref],
                        "weak_context_only": False,
                        "anchor_dependency_status": "none",
                    },
                },
            )
            consumed = {
                item["hint_ref"]: item
                for item in qdt_report["hint_consumption"]
            }
            self.assertTrue(consumed[hint_ref]["decomposer_consumed"])
            self.assertEqual(consumed[hint_ref]["consumed_by_leaf_ids"], ["leaf-1"])
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
        self.assertEqual(
            first["amrg_decomposer_context"]["schema_version"],
            AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION,
        )
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

        prompt_context = build_amrg_decomposer_context(artifact)
        self.assertEqual(prompt_context["schema_version"], AMRG_DECOMPOSER_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(prompt_context["operator_metadata"]["hint_count_by_category"], {"weak_context_hint": 1})
        hint = prompt_context["hints"][0]
        self.assertEqual(hint["allowed_use"], ["decomposition_context_hint"])
        self.assertIn("qdt_selection", hint["prohibited_use"])
        self.assertIn("qdt_repair", hint["prohibited_use"])
        self.assertIn("probability_authority", hint["prohibited_use"])
        self.assertIn("scae_delta", hint["prohibited_use"])
        self.assertIn("context_leaf", hint["candidate_leaf_relevance"]["allowed_leaf_uses"])
        validate_amrg_decomposer_context(prompt_context)

    def test_entity_match_requires_high_salience_shared_entity(self):
        base_packet = self.evidence_packet()
        bond_identity = {
            **base_packet["market_identity"],
            "title": "Will James Bond win a franchise award?",
            "description": "James Bond entertainment award market",
            "category": "entertainment",
            "normalized_entities": ["James Bond"],
            "source_of_truth_kind": "entertainment-database",
            "source_url": "https://example.test/bond-awards",
        }
        bond_packet = self.evidence_packet(
            market_identity=bond_identity,
            regime_seed_fields={**base_packet["regime_seed_fields"], "category": "entertainment"},
        )

        unrelated = build_related_live_market_context_or_waiver(
            evidence_packet=bond_packet,
            evidence_packet_ref="artifact:evidence-packet",
            active_market_index=[
                self.market(
                    2,
                    title="Will Russia announce a policy deadline?",
                    normalized_entities=["Russia"],
                    contract_terms=["announcement", "deadline"],
                    category="politics",
                    source_of_truth_kind="government",
                    source_url="https://example.test/russia-policy",
                )
            ],
        )
        self.assertEqual(unrelated["artifact_type"], "no_related_context_waiver")
        self.assertEqual(unrelated["candidates"], [])

        related = build_related_live_market_context_or_waiver(
            evidence_packet=bond_packet,
            evidence_packet_ref="artifact:evidence-packet",
            active_market_index=[
                self.market(
                    3,
                    title="Will James Bond release another film?",
                    normalized_entities=["James Bond"],
                    contract_terms=["release"],
                    category="entertainment",
                    source_of_truth_kind="box-office",
                    source_url="https://example.test/bond-release",
                )
            ],
        )
        self.assertEqual(related["candidates"][0]["candidate_source"], "entity_match")
        self.assertIn("active_safe_salient_entity_overlap", related["candidates"][0]["reason_codes"])
        enriched = enrich_related_live_market_context(related, evidence_packet=bond_packet)
        self.assertEqual(enriched["relationship_edges"][0]["relationship_status"], "deterministic_context_candidate")

    def test_cross_domain_entity_match_is_weak_context_only(self):
        base_packet = self.evidence_packet()
        bond_packet = self.evidence_packet(
            market_identity={
                **base_packet["market_identity"],
                "title": "Will James Bond win a franchise award?",
                "description": "James Bond entertainment award market",
                "category": "entertainment",
                "normalized_entities": ["James Bond"],
                "source_of_truth_kind": "entertainment-database",
                "source_url": "https://example.test/bond-awards",
            },
            regime_seed_fields={**base_packet["regime_seed_fields"], "category": "entertainment"},
        )
        artifact = build_related_live_market_context_or_waiver(
            evidence_packet=bond_packet,
            evidence_packet_ref="artifact:evidence-packet",
            active_market_index=[
                self.market(
                    4,
                    title="Will James Bond be appointed to a policy role?",
                    normalized_entities=["James Bond"],
                    contract_terms=["appointment"],
                    category="politics",
                    source_of_truth_kind="government",
                    source_url="https://example.test/bond-policy",
                )
            ],
        )
        self.assertEqual(artifact["candidates"][0]["candidate_source"], "entity_match")
        enriched = enrich_related_live_market_context(artifact, evidence_packet=bond_packet)
        edge = enriched["relationship_edges"][0]
        self.assertEqual(edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertEqual(edge["allowed_effects"], ["decomposition_context_hint"])
        self.assertEqual(edge["domain_compatibility"]["domain_compatibility_status"], "cross_domain_weak_context_only")
        self.assertIn("domain_mismatch_downgraded_weak_context_only", edge["downgrade_reason_codes"])

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

    def test_amrg_decomposer_context_caps_relationship_vector_and_anchor_hints(self):
        deterministic_artifact = enrich_related_live_market_context(
            self.build_artifact([self.market(market_id) for market_id in range(2, 12)], candidate_cap=10),
            evidence_packet=self.evidence_packet(),
        )
        deterministic_context = build_amrg_decomposer_context(deterministic_artifact)
        self.assertEqual(
            deterministic_context["operator_metadata"]["hint_count_by_category"],
            {"deterministic_relationship_hint": 5},
        )

        vector_candidates = [
            {
                "schema_version": AMRG_VECTOR_NEIGHBOR_CANDIDATE_SCHEMA_VERSION,
                "candidate_source": AMRG_VECTOR_CANDIDATE_SOURCE,
                "relationship_status": WEAK_CONTEXT_ONLY,
                "vector_only": True,
                "market_id": market_id,
                "external_market_id": f"poly-{market_id}",
                "similarity_score": 0.95 - (market_id / 100),
                "similarity_metric": "cosine",
                "query_descriptor_sha256": "sha256:query",
                "candidate_descriptor_sha256": f"sha256:candidate-{market_id}",
                "index_snapshot_id": "amrg-vector-index:fixture",
                "embedding_lane_id": "amrg_vector_embedding",
                "resolved_model_id": "BAAI/bge-base-en-v1.5",
                "route_id": "ollama/local",
            }
            for market_id in range(20, 28)
        ]
        vector_artifact = build_related_live_market_context_or_waiver(
            evidence_packet=self.evidence_packet(
                market_identity={
                    **self.evidence_packet()["market_identity"],
                    "title": "Will an unrelated weather event happen?",
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
                    market_id,
                    title=f"Will sports event {market_id} happen?",
                    normalized_entities=[],
                    contract_terms=[],
                    category="sports",
                    source_of_truth_kind="sports",
                    source_url="https://example.test/sports",
                )
                for market_id in range(20, 28)
            ],
            vector_candidates=vector_candidates,
            candidate_cap=8,
        )
        vector_context = build_amrg_decomposer_context(vector_artifact)
        self.assertEqual(
            vector_context["operator_metadata"]["hint_count_by_category"],
            {"vector_neighbor_weak_context_hint": 5},
        )
        for hint in vector_context["hints"]:
            self.assertEqual(hint["allowed_use"], ["decomposition_context_hint"])

        anchor_artifact = enrich_related_live_market_context(
            self.build_artifact([self.market(market_id) for market_id in range(30, 34)], candidate_cap=4),
            evidence_packet=self.evidence_packet(),
        )
        for edge in anchor_artifact["relationship_edges"]:
            edge["relationship_status"] = "strict_precedence_anchor_candidate"
            edge["relationship_types"] = ["causal_upstream"]
            edge["allowed_effects"] = ["decomposition_context_hint", "qdt_anchor_dependency_hint"]
        anchor_context = build_amrg_decomposer_context(anchor_artifact)
        self.assertEqual(
            anchor_context["operator_metadata"]["hint_count_by_category"],
            {"strict_precedence_anchor_hint": 2},
        )
        for hint in anchor_context["hints"]:
            self.assertIn("qdt_anchor_dependency_hint", hint["allowed_use"])

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

    def test_shared_cache_temporal_scope_match_allows_conservative_reuse(self):
        artifact = self.build_artifact([self.market(2)])
        enriched = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            shared_cache_entries=[self.shared_cache_entry(cache_entry_type="leaf_classification")],
            consuming_dispatch=self.consuming_dispatch(),
        )

        assessment = enriched["shared_cache_eligibility"][0]
        self.assertEqual(assessment["schema_version"], AMRG_SHARED_CACHE_ELIGIBILITY_SCHEMA_VERSION)
        self.assertEqual(assessment["eligibility_status"], "eligible_reuse")
        self.assertEqual(assessment["allowed_use"], "shared_retrieval_classification_cache_reuse")
        self.assertEqual(assessment["max_underlying_source_timestamp"], "2026-06-24T17:55:00+00:00")
        self.assertIn("temporal_provenance_precedes_consuming_forecast", assessment["reason_codes"])
        self.assertIn("probability_authority", assessment["forbidden_effects"])
        self.assertIn("scae_delta", assessment["forbidden_effects"])
        self.assertIn("qdt_repair", assessment["forbidden_effects"])
        self.assertIn("production_forecast_write", assessment["forbidden_effects"])

    def test_shared_cache_without_temporal_provenance_downgrades_to_source_hint_only(self):
        artifact = self.build_artifact([self.market(2)])
        entry = self.shared_cache_entry(cache_created_at="2026-06-24T17:00:00+00:00")
        entry.pop("temporal_provenance")

        enriched = apply_shared_cache_reuse_eligibility(
            enrich_related_live_market_context(artifact, evidence_packet=self.evidence_packet()),
            shared_cache_entries=[entry],
            consuming_dispatch=self.consuming_dispatch(),
        )

        assessment = enriched["shared_cache_eligibility"][0]
        self.assertEqual(assessment["eligibility_status"], "source_hint_only")
        self.assertEqual(assessment["allowed_use"], "source_hint_only_requires_fresh_retrieval_or_classification")
        self.assertIsNone(assessment["max_underlying_source_timestamp"])
        self.assertIn("missing_max_underlying_source_timestamp", assessment["reason_codes"])

    def test_shared_cache_scope_mismatch_is_rejected(self):
        artifact = self.build_artifact([self.market(2)])
        enriched = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            shared_cache_entries=[
                self.shared_cache_entry(
                    leaf_condition_scope="target_given_upstream",
                    contract_scope="binary:other-contract",
                )
            ],
            consuming_dispatch=self.consuming_dispatch(),
        )

        assessment = enriched["shared_cache_eligibility"][0]
        self.assertEqual(assessment["eligibility_status"], "rejected")
        self.assertEqual(assessment["allowed_use"], "not_reusable")
        self.assertIn("leaf_condition_scope_mismatch", assessment["reason_codes"])
        self.assertIn("contract_scope_mismatch", assessment["reason_codes"])

    def test_shared_cache_write_path_does_not_persist_forecast_or_scae_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            result = write_related_market_context(
                conn,
                self.build_artifact([self.market(2)]),
                evidence_packet=self.evidence_packet(),
                shared_cache_entries=[self.shared_cache_entry()],
                consuming_dispatch=self.consuming_dispatch(),
            )

            self.assertEqual(result["context"]["shared_cache_eligibility"][0]["eligibility_status"], "eligible_reuse")
            table_names = [
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            ]
            self.assertFalse(any(name.startswith("scae_") for name in table_names))
            self.assertFalse(any("forecast" in name or "prediction" in name for name in table_names))
        finally:
            conn.close()

    def test_model_assist_lane_requires_oauth_route_and_gpt54(self):
        lane = {
            "provider": "openai",
            "default_model_id": "gpt-5.4-high",
            "provider_route": "openclaw_codex_oauth/amrg",
            "oauth_route_required": True,
            "runtime_agent_id": "amrg",
            "allowed_model_ids": ["gpt-5.4-high"],
            "owner_feature_id": "AMRG-004",
            "required_artifact_fields": [
                "model_lane_id",
                "resolved_model_id",
                "model_policy_ref",
                "prompt_template_id",
                "prompt_template_sha256",
                "input_manifest_sha256",
                "output_schema_version",
            ],
            "forbidden_outputs": [
                "probability",
                "scae_evidence_delta",
                "qdt_selection",
                "edge_promotion",
                "concept_creation",
                "label_creation",
                "active_graph_promotion",
            ],
        }
        policy = {"lanes": {"amrg_model_assist": lane}}
        self.assertEqual(resolve_amrg_model_assist_lane(policy)["provider_route"], "openclaw_codex_oauth/amrg")

        for field, value, error in (
            ("default_model_id", "gpt-5.5-high", "gpt-5.4-high"),
            ("provider_route", "openclaw_codex_oauth/decomposer", "provider_route"),
            ("oauth_route_required", False, "oauth_route_required"),
            ("runtime_agent_id", "decomposer", "runtime_agent_id"),
        ):
            mutated_lane = {**lane, field: value}
            if field == "default_model_id":
                mutated_lane["allowed_model_ids"] = ["gpt-5.4-high", "gpt-5.5-high"]
            with self.assertRaisesRegex(Exception, error):
                resolve_amrg_model_assist_lane({"lanes": {"amrg_model_assist": mutated_lane}})

    def test_operator_report_signs_off_optional_model_assist_policy(self):
        report = build_amrg_operator_report(self.build_artifact([self.market(2)]))

        self.assertEqual(report["assist_readiness_status"], "assist_not_requested_by_policy")
        signoff = report["dependency_readiness"]["assist_policy_signoff"]
        self.assertEqual(signoff["signoff_status"], "optional_not_requested")
        self.assertFalse(signoff["assist_requested_by_policy"])
        self.assertFalse(signoff["model_executed"])
        self.assertEqual(signoff["model_execution_claim"], "not_claimed")
        self.assertTrue(signoff["non_blocking_when_not_requested"])
        self.assertEqual(signoff["model_lane_id"], "amrg_model_assist")
        self.assertEqual(signoff["resolved_model_id"], "gpt-5.4-high")
        self.assertEqual(signoff["provider_route"], "openclaw_codex_oauth/amrg")
        self.assertTrue(signoff["oauth_route_required"])
        self.assertEqual(signoff["runtime_agent_id"], "amrg")

    def test_model_assist_forbidden_probability_output_is_rejected(self):
        artifact = self.build_artifact([self.market(2)])
        packet = build_amrg_model_assist_packet(artifact)
        self.assertEqual(packet["model_lane_id"], "amrg_model_assist")
        self.assertEqual(packet["authority"], "advisory_only_no_promotion")
        self.assertEqual(packet["resolved_model_id"], "gpt-5.4-high")
        self.assertEqual(packet["provider_route"], "openclaw_codex_oauth/amrg")
        self.assertTrue(packet["oauth_route_required"])

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

        qdt_repair_output = json.loads(json.dumps(output))
        qdt_repair_output["edge_annotations"][0].pop("probability")
        qdt_repair_output["edge_annotations"][0]["qdt_repair"] = {"action": "add_leaf"}
        with self.assertRaisesRegex(Exception, "qdt_repair"):
            validate_amrg_model_assist_output(qdt_repair_output)

        scae_delta_output = json.loads(json.dumps(output))
        scae_delta_output["edge_annotations"][0].pop("probability")
        scae_delta_output["edge_annotations"][0]["scae_delta"] = {"direction": "up"}
        with self.assertRaisesRegex(Exception, "scae_delta"):
            validate_amrg_model_assist_output(scae_delta_output)

        citation_output = json.loads(json.dumps(output))
        citation_output["edge_annotations"][0].pop("probability")
        citation_output["edge_annotations"][0]["citation"] = "https://example.test/evidence"
        with self.assertRaisesRegex(Exception, "citation"):
            validate_amrg_model_assist_output(citation_output)

        wrong_model_output = json.loads(json.dumps(output))
        wrong_model_output["edge_annotations"][0].pop("probability")
        wrong_model_output["resolved_model_id"] = "gpt-5.5-high"
        with self.assertRaisesRegex(Exception, "gpt-5.4-high"):
            validate_amrg_model_assist_output(wrong_model_output)

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
        self.assertTrue(provenance["model_executed"])
        self.assertEqual(provenance["execution_status"], "succeeded")
        self.assertEqual(provenance["provider_route"], "openclaw_codex_oauth/amrg")
        self.assertTrue(provenance["oauth_route_required"])
        self.assertTrue(provenance["output_artifact_sha256"].startswith("sha256:"))
        self.assertEqual(provenance["metadata"]["resolved_model_id"], "gpt-5.4-high")
        enriched = enrich_related_live_market_context(
            artifact,
            evidence_packet=self.evidence_packet(),
            model_assist_status=provenance["model_assist_status"],
        )

        edge = enriched["relationship_edges"][0]
        self.assertEqual(edge["relationship_status"], "model_assisted_weak_context_only")
        self.assertEqual(edge["allowed_effects"], ["decomposition_context_hint"])
        self.assertEqual(edge["model_assist_status"], "advisory_validated")
        self.assertIn("edge_promotion", edge["forbidden_effects"])

        degraded = model_assist_downgrade_for_missing_manifest({**artifact, "input_manifest_hash": None})
        self.assertEqual(degraded["model_assist_status"], "not_invoked_missing_active_safe_manifest")
        self.assertEqual(degraded["forbidden_output_check_status"], "not_applicable")

    def test_invalid_model_assist_output_records_rejected_provenance(self):
        artifact = self.build_artifact([self.market(2)])
        packet = build_amrg_model_assist_packet(artifact)
        rejected = invoke_amrg_model_assist(
            artifact,
            output={
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
                        "evidence": {"url": "https://example.test/model-authored-evidence"},
                    }
                ],
            },
        )

        self.assertEqual(rejected["model_assist_status"], "advisory_rejected_forbidden_output")
        self.assertEqual(rejected["forbidden_output_check_status"], "failed")
        self.assertTrue(rejected["model_executed"])
        self.assertEqual(rejected["execution_status"], "failed_output_validation")
        self.assertTrue(rejected["output_artifact_sha256"].startswith("sha256:"))
        self.assertIn("evidence", rejected["metadata"]["rejection_reason"])

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

    def qdt_anchor_contract(self, edge_id, *, condition_scoped_leaf_ids=None, anchor_mode="anchor_required"):
        return {
            "schema_version": "amrg-anchor-dependency-contract/v1",
            "anchor_dependency_contract_id": f"anchor-contract:{edge_id}",
            "edge_id": edge_id,
            "edge_status": "strict_precedence_anchor_candidate",
            "conditional_branch_group_id": f"conditional-branch:{edge_id}",
            "anchor_mode": anchor_mode,
            "condition_scoped_leaf_ids": condition_scoped_leaf_ids if condition_scoped_leaf_ids is not None else ["leaf-upstream"],
            "required_before_leaf_ids": condition_scoped_leaf_ids if condition_scoped_leaf_ids is not None else ["leaf-upstream"],
            "fallback_policy": {
                "fallback_policy_id": f"fallback:{edge_id}",
                "fallback_mode": "fail_dispatch_preparation",
                "fallback_leaf_ids": [],
                "fallback_reason_codes": ["anchor_required"],
            },
            "max_anchor_repair_attempts": 1,
            "max_anchor_repair_wall_clock_seconds": 10,
            "repair_exhaustion_policy": "fail_dispatch_preparation",
        }

    def strict_anchor_context(self, *, upstream_time="2026-06-24T17:00:00+00:00", target_time="2026-06-24T19:00:00+00:00"):
        enriched = enrich_related_live_market_context(
            self.build_artifact([self.market(2)]),
            evidence_packet=self.evidence_packet(),
        )
        edge = enriched["relationship_edges"][0]
        edge.update(
            {
                "relationship_status": "strict_precedence_anchor_candidate",
                "relationship_types": ["causal_upstream"],
                "strict_precedence_basis": "event_time",
                "strict_precedence_proof_ref": "artifact:amrg-strict-precedence-proof",
                "upstream_event_time": upstream_time,
                "target_event_time": target_time,
            }
        )
        return enriched

    def test_strict_precedence_anchor_validates_with_qdt_condition_scoped_leaves(self):
        context = self.strict_anchor_context()
        edge_id = context["relationship_edges"][0]["edge_id"]

        validated = apply_strict_precedence_anchor_validation(
            context,
            qdt_anchor_contracts=[self.qdt_anchor_contract(edge_id)],
        )

        edge = validated["relationship_edges"][0]
        self.assertEqual(edge["relationship_status"], "validated_strict_precedence_anchor")
        self.assertEqual(edge["anchor_validation_status"], "validated")
        self.assertEqual(edge["cycle_status"], "acyclic")
        self.assertIn("condition_scoped_anchor_validation_input", edge["allowed_effects"])
        self.assertIn("probability_authority", edge["forbidden_effects"])
        self.assertIn("scae_delta", edge["forbidden_effects"])
        self.assertIn("qdt_selection", edge["forbidden_effects"])

        anchor_slice = validated["prior_anchor_slices"][0]
        self.assertEqual(anchor_slice["validation_status"], "validated")
        self.assertEqual(anchor_slice["raw_upstream_probability"], None)
        self.assertEqual(anchor_slice["adjusted_upstream_probability"], None)
        self.assertEqual(anchor_slice["upstream_probability_as_of"], None)
        self.assertTrue(anchor_slice["metadata"]["qdt_contract_read_only"])

    def test_concurrent_or_cyclic_anchor_candidate_is_rejected_and_downgraded(self):
        concurrent = self.strict_anchor_context(target_time="2026-06-24T17:00:00+00:00")
        edge_id = concurrent["relationship_edges"][0]["edge_id"]
        rejected = apply_strict_precedence_anchor_validation(
            concurrent,
            qdt_anchor_contracts=[self.qdt_anchor_contract(edge_id)],
        )
        edge = rejected["relationship_edges"][0]
        self.assertEqual(edge["anchor_validation_status"], "rejected")
        self.assertEqual(edge["relationship_status"], "timing_mismatch_weak_context_only")
        self.assertIn("concurrent_event_time", edge["anchor_validation_reason_codes"])
        self.assertEqual(rejected["prior_anchor_slices"][0]["validation_status"], "rejected")

        cyclic = self.strict_anchor_context()
        cyclic_edge_id = cyclic["relationship_edges"][0]["edge_id"]
        cycle_rejected = apply_strict_precedence_anchor_validation(
            cyclic,
            qdt_anchor_contracts=[self.qdt_anchor_contract(cyclic_edge_id)],
            graph_edges=[{"upstream_market_id": "1", "target_market_id": "2"}],
        )
        cycle_edge = cycle_rejected["relationship_edges"][0]
        self.assertEqual(cycle_edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertEqual(cycle_edge["causal_graph_status"], "blocked_cycle_or_concurrent_timing")
        self.assertIn("causal_graph_cycle_rejected", cycle_edge["anchor_validation_reason_codes"])

    def test_reflexive_anchor_candidate_is_rejected_and_downgraded(self):
        context = self.strict_anchor_context()
        edge = context["relationship_edges"][0]
        edge_id = edge["edge_id"]
        edge["upstream_market_id"] = "same-market"
        edge["target_market_id"] = "same-market"

        rejected = apply_strict_precedence_anchor_validation(
            context,
            qdt_anchor_contracts=[self.qdt_anchor_contract(edge_id)],
        )

        rejected_edge = rejected["relationship_edges"][0]
        self.assertEqual(rejected_edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertEqual(rejected_edge["anchor_validation_status"], "rejected")
        self.assertIn("reflexive_causal_edge_rejected", rejected_edge["anchor_validation_reason_codes"])
        self.assertEqual(rejected["prior_anchor_slices"][0]["allowed_use"], "validation_audit_only")

    def test_anchor_candidate_without_qdt_condition_scoped_leaves_is_rejected(self):
        context = self.strict_anchor_context()
        edge_id = context["relationship_edges"][0]["edge_id"]

        rejected = apply_strict_precedence_anchor_validation(
            context,
            qdt_anchor_contracts=[self.qdt_anchor_contract(edge_id, condition_scoped_leaf_ids=[])],
        )

        edge = rejected["relationship_edges"][0]
        self.assertEqual(edge["relationship_status"], WEAK_CONTEXT_ONLY)
        self.assertEqual(edge["anchor_validation_status"], "rejected")
        self.assertIn("missing_qdt_condition_scoped_leaf_support", edge["anchor_validation_reason_codes"])
        self.assertEqual(rejected["prior_anchor_slices"][0]["allowed_use"], "validation_audit_only")

    def test_anchor_persistence_writes_validation_audit_without_probability_or_scae_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            artifact = self.strict_anchor_context()
            edge_id = artifact["relationship_edges"][0]["edge_id"]
            result = write_related_market_context(
                conn,
                artifact,
                evidence_packet=self.evidence_packet(),
                qdt_anchor_contracts=[self.qdt_anchor_contract(edge_id)],
            )

            self.assertEqual(len(result["prior_anchor_slice_ids"]), 1)
            row = conn.execute(
                """
                SELECT validation_status, raw_upstream_probability,
                       adjusted_upstream_probability, upstream_probability_as_of,
                       reason_codes, metadata
                FROM related_market_prior_anchor_slices
                """
            ).fetchone()
            self.assertEqual(row["validation_status"], "validated")
            self.assertIsNone(row["raw_upstream_probability"])
            self.assertIsNone(row["adjusted_upstream_probability"])
            self.assertIsNone(row["upstream_probability_as_of"])
            self.assertIn("strict_precedence_anchor_validated", json.loads(row["reason_codes"]))
            self.assertTrue(json.loads(row["metadata"])["no_scae_delta_written"])
            scae_tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'scae_%'"
                ).fetchall()
            ]
            self.assertEqual(scae_tables, [])
        finally:
            conn.close()

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
