import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import (
    AMRGError,
    AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION,
    AMRG_VECTOR_CANDIDATE_SOURCE,
    AMRG_VECTOR_EMBEDDING_DIMENSION,
    AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION,
    AMRG_VECTOR_MODEL_ID,
    AMRG_VECTOR_ROUTE_ID,
    PullResult,
    build_active_market_descriptor,
    build_live_amrg_vector_runtime,
    build_ready_vector_index,
    build_unavailable_vector_source_diagnostic,
    build_vector_index_snapshot,
    build_vector_neighbor_candidates,
    descriptor_rows_for_write,
    ensure_amrg_vector_model,
    parse_ollama_embeddings_response,
    preflight_ollama_vector_embeddings,
    resolve_amrg_vector_embedding_lane,
    search_vector_neighbors,
)
from predquant.tuning_profile import MODEL_LANE_POLICY_PATH, load_model_lane_policy


class AMRGVectorTest(unittest.TestCase):
    def setUp(self):
        self.policy = load_model_lane_policy(MODEL_LANE_POLICY_PATH)
        self.source_cutoff = "2026-06-24T18:00:00+00:00"

    def market(self, **overrides):
        values = {
            "id": 1,
            "external_market_id": "poly-1",
            "status": "open",
            "title": "Will the fixture pass?",
            "description": "A deterministic active-safe market",
            "category": "politics",
            "outcome_type": "binary",
            "closes_at": "2026-06-25T00:00:00+00:00",
            "resolves_at": "2026-06-26T00:00:00+00:00",
            "normalized_entities": ["fixture"],
            "contract_terms": ["yes_no"],
            "source_of_truth_kind": "official",
            "family_context_tokens": ["standalone"],
        }
        values.update(overrides)
        return values

    def embedding(self, first_value):
        vector = [0.0] * AMRG_VECTOR_EMBEDDING_DIMENSION
        vector[0] = first_value
        if AMRG_VECTOR_EMBEDDING_DIMENSION > 1:
            vector[1] = 1.0 - first_value
        return vector

    def descriptor(self, market_id, title):
        return build_active_market_descriptor(
            self.market(id=market_id, external_market_id=f"poly-{market_id}", title=title),
            self.source_cutoff,
            case_key=f"polymarket:poly-{market_id}",
        )

    def evidence_packet(self):
        return {
            "artifact_type": "evidence_packet",
            "schema_version": "evidence-packet/v2",
            "case_contract_ref": "artifact:case-contract",
            "case_id": "case-vector",
            "case_key": "polymarket:poly-1:2026-06-24T18:00:00+00:00",
            "market_id": 1,
            "dispatch_id": "dispatch-vector",
            "forecast_timestamp": "2026-06-24T18:00:00+00:00",
            "source_cutoff_timestamp": self.source_cutoff,
            "market_identity": {
                "internal_market_id": 1,
                "external_market_id": "poly-1",
                "platform": "polymarket",
                "title": "Will alpha happen?",
                "description": "Alpha fixture market",
                "category": "politics",
                "status": "open",
                "outcome_type": "binary",
                "closes_at": "2026-06-25T00:00:00+00:00",
                "resolves_at": "2026-06-26T00:00:00+00:00",
                "source_of_truth_kind": "official",
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
                        "yes": {"higher_probability_means": "market_resolves_yes"},
                        "no": {"higher_probability_means": "market_resolves_no"},
                    },
                },
                "source_of_truth_status": "clear",
                "contract_structure": "binary",
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
            "prior_context_seed": {},
            "prior_reliability_inputs": {
                "schema_version": "prior-reliability-inputs/v1",
                "authority": "candidate_inputs_only_no_scae_probability",
                "policy": {},
                "lookback_window": {},
                "quote_observation_refs": [],
                "compact_quote_observations": [],
                "rolling_microstructure": {},
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

    def test_model_lane_resolution_and_pull_unavailable_diagnostic(self):
        lane = resolve_amrg_vector_embedding_lane(self.policy)
        self.assertEqual(lane["provider"], "ollama")
        self.assertEqual(lane["route_id"], AMRG_VECTOR_ROUTE_ID)
        self.assertEqual(lane["default_model_id"], AMRG_VECTOR_MODEL_ID)
        self.assertEqual(lane["download_command_contract"], "ollama pull BAAI/bge-base-en-v1.5")

        missing = ensure_amrg_vector_model(
            self.policy,
            model_available=False,
            pull_result=PullResult(False, "ollama_route_unavailable"),
        )
        self.assertFalse(missing["ok"])
        self.assertTrue(missing["pull_attempted"])
        self.assertEqual(missing["download_command_contract"], "ollama pull BAAI/bge-base-en-v1.5")
        self.assertEqual(missing["diagnostic"]["reason_code"], "amrg_vector_candidate_source_unavailable")
        self.assertTrue(missing["diagnostic"]["non_blocking"])
        self.assertIn("QDT", missing["diagnostic"]["does_not_block"])

    def test_ollama_preflight_uses_current_embed_api_and_records_provenance(self):
        class FakeOllama:
            base_url = "http://localhost:11434"

            def __init__(self, embedding):
                self.embedding = embedding
                self.embed_calls = []

            def version(self):
                return {"version": "0.9.0"}

            def show_model(self, model):
                self.model = model
                return {"digest": "fixture-digest"}

            def embed(self, model, inputs, *, truncate=False, keep_alive=None):
                self.embed_calls.append(
                    {"model": model, "inputs": inputs, "truncate": truncate, "keep_alive": keep_alive}
                )
                count = len(inputs) if isinstance(inputs, list) else 1
                return {"embeddings": [self.embedding for _ in range(count)]}

        client = FakeOllama(self.embedding(0.7))
        preflight = preflight_ollama_vector_embeddings(self.policy, client=client, source_cutoff_timestamp=self.source_cutoff)

        self.assertTrue(preflight["ok"], preflight)
        self.assertEqual(preflight["embed_endpoint"], "/api/embed")
        self.assertEqual(preflight["provider"], "ollama")
        self.assertEqual(preflight["route_id"], AMRG_VECTOR_ROUTE_ID)
        self.assertEqual(preflight["resolved_model_id"], AMRG_VECTOR_MODEL_ID)
        self.assertEqual(preflight["model_digest"], "sha256:fixture-digest")
        self.assertFalse(client.embed_calls[0]["truncate"])

    def test_ollama_embedding_parser_rejects_wrong_dimension_and_non_finite_values(self):
        with self.assertRaisesRegex(AMRGError, "dimension"):
            parse_ollama_embeddings_response({"embeddings": [[0.1, 0.2]]}, expected_count=1)
        bad = self.embedding(0.5)
        bad[0] = float("nan")
        with self.assertRaisesRegex(AMRGError, "finite"):
            parse_ollama_embeddings_response({"embeddings": [bad]}, expected_count=1)

    def test_live_vector_runtime_builds_ready_snapshot_and_candidates(self):
        class FakeOllama:
            base_url = "http://localhost:11434"

            def version(self):
                return {"version": "0.9.0"}

            def show_model(self, model):
                return {"digest": "fixture-digest"}

            def embed(self, model, inputs, *, truncate=False, keep_alive=None):
                vectors = []
                count = len(inputs) if isinstance(inputs, list) else 1
                for idx in range(count):
                    vectors.append(self.embedding(1.0 if idx == 0 else 0.9 - (idx / 100)))
                return {"embeddings": vectors}

            def embedding(self, first_value):
                vector = [0.0] * AMRG_VECTOR_EMBEDDING_DIMENSION
                vector[0] = first_value
                vector[1] = 1.0 - first_value
                return vector

        result = build_live_amrg_vector_runtime(
            evidence_packet=self.evidence_packet(),
            active_market_index=[
                self.market(id=2, external_market_id="poly-2", title="Will alpha related happen?"),
                self.market(id=3, external_market_id="poly-3", title="Will beta happen?"),
            ],
            policy=self.policy,
            client=FakeOllama(),
            neighbor_cap=1,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["index_snapshot"]["index_status"], "ready")
        self.assertEqual(result["index_snapshot"]["model_digest"], "sha256:fixture-digest")
        self.assertEqual(len(result["vector_candidates"]), 1)
        self.assertEqual(result["vector_candidates"][0]["candidate_source"], AMRG_VECTOR_CANDIDATE_SOURCE)
        self.assertEqual(result["vector_source_diagnostics"], [])

    def test_unavailable_diagnostic_is_non_blocking(self):
        diagnostic = build_unavailable_vector_source_diagnostic(
            "vector_index_missing",
            source_cutoff_timestamp=self.source_cutoff,
        )
        self.assertEqual(diagnostic["reason_code"], "amrg_vector_candidate_source_unavailable")
        self.assertTrue(diagnostic["non_blocking"])
        self.assertIn("SCAE", diagnostic["does_not_block"])
        self.assertIn("decision", diagnostic["does_not_block"])

    def test_descriptor_rejects_inactive_resolved_post_cutoff_and_unsafe_fields(self):
        with self.assertRaisesRegex(AMRGError, "status"):
            build_active_market_descriptor(self.market(status="closed"), self.source_cutoff)
        with self.assertRaisesRegex(AMRGError, "status"):
            build_active_market_descriptor(self.market(status="resolved"), self.source_cutoff)
        with self.assertRaisesRegex(AMRGError, "after source_cutoff"):
            build_active_market_descriptor(
                self.market(updated_at="2026-06-24T18:01:00+00:00"),
                self.source_cutoff,
            )
        for field in ["raw_payload", "resolved_outcome", "brier_score", "replay_result"]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(AMRGError, "not active-safe"):
                    build_active_market_descriptor(self.market(**{field: "unsafe"}), self.source_cutoff)

    def test_descriptor_hash_is_deterministic_and_write_rows_are_compact(self):
        first = build_active_market_descriptor(self.market(), self.source_cutoff, case_key="case-a")
        second = build_active_market_descriptor(self.market(), self.source_cutoff, case_key="case-a")

        self.assertEqual(first["schema_version"], AMRG_MARKET_VECTOR_DESCRIPTOR_SCHEMA_VERSION)
        self.assertEqual(first["descriptor_sha256"], second["descriptor_sha256"])
        self.assertEqual(first["descriptor_text"], second["descriptor_text"])
        self.assertNotIn("raw_payload", first["descriptor_text"])

        rows = descriptor_rows_for_write([first])
        self.assertEqual(rows[0]["descriptor_sha256"], first["descriptor_sha256"])
        self.assertIn("active_safe_fields", rows[0])

    def test_ready_and_unavailable_index_snapshots(self):
        descriptor = self.descriptor(1, "Will alpha happen?")
        ready = build_ready_vector_index(
            [descriptor],
            {descriptor["descriptor_sha256"]: self.embedding(1.0)},
            source_cutoff_timestamp=self.source_cutoff,
        )
        self.assertEqual(ready["schema_version"], AMRG_VECTOR_INDEX_SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(ready["index_status"], "ready")
        self.assertEqual(ready["resolved_model_id"], AMRG_VECTOR_MODEL_ID)
        self.assertEqual(ready["route_id"], AMRG_VECTOR_ROUTE_ID)
        self.assertEqual(ready["embedding_dimension"], AMRG_VECTOR_EMBEDDING_DIMENSION)
        self.assertEqual(ready["similarity_metric"], "cosine")

        unavailable = build_vector_index_snapshot(
            [],
            status="unavailable",
            unavailable_reason="ollama_bge_model_unavailable",
            source_cutoff_timestamp=self.source_cutoff,
        )
        self.assertEqual(unavailable["index_status"], "unavailable")
        self.assertEqual(unavailable["diagnostic"]["reason_code"], "amrg_vector_candidate_source_unavailable")

    def test_vector_neighbors_are_capped_and_weak_context_only(self):
        query = self.descriptor(1, "Will alpha happen?")
        neighbors = [
            self.descriptor(2, "Will alpha related happen?"),
            self.descriptor(3, "Will beta happen?"),
            self.descriptor(4, "Will gamma happen?"),
        ]
        snapshot = build_vector_index_snapshot(
            neighbors,
            status="ready",
            source_cutoff_timestamp=self.source_cutoff,
            embedding_model_sha256="sha256:fixture-model",
        )
        scores = {
            neighbors[0]["descriptor_sha256"]: 0.91,
            neighbors[1]["descriptor_sha256"]: 0.88,
            neighbors[2]["descriptor_sha256"]: 0.99,
        }
        candidates = build_vector_neighbor_candidates(
            query_descriptor=query,
            index_snapshot=snapshot,
            neighbor_descriptors=neighbors,
            neighbor_scores=scores,
            cap=2,
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual([candidate["market_id"] for candidate in candidates], [4, 2])
        for candidate in candidates:
            self.assertEqual(candidate["candidate_source"], AMRG_VECTOR_CANDIDATE_SOURCE)
            self.assertEqual(candidate["relationship_status"], "weak_context_only")
            self.assertTrue(candidate["vector_only"])
            self.assertEqual(candidate["index_snapshot_id"], snapshot["index_snapshot_id"])

    def test_search_vector_neighbors_uses_cosine_and_ready_index(self):
        query = self.descriptor(1, "Will alpha happen?")
        neighbors = [
            self.descriptor(2, "Will alpha related happen?"),
            self.descriptor(3, "Will beta happen?"),
        ]
        embeddings = {
            query["descriptor_sha256"]: self.embedding(1.0),
            neighbors[0]["descriptor_sha256"]: self.embedding(0.9),
            neighbors[1]["descriptor_sha256"]: self.embedding(0.1),
        }
        snapshot = build_ready_vector_index(
            neighbors,
            {key: value for key, value in embeddings.items() if key != query["descriptor_sha256"]},
            source_cutoff_timestamp=self.source_cutoff,
        )
        candidates = search_vector_neighbors(
            query_descriptor=query,
            query_embedding=embeddings[query["descriptor_sha256"]],
            index_snapshot=snapshot,
            candidate_descriptors=neighbors,
            embeddings_by_descriptor_sha256=embeddings,
            cap=1,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["market_id"], 2)
        self.assertEqual(candidates[0]["relationship_status"], "weak_context_only")


if __name__ == "__main__":
    unittest.main()
