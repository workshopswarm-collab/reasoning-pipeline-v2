import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_case_contract import ensure_case_contract_schema, materialize_ads_case_contract
from predquant.evidence_packet import build_evidence_packet_v2
from predquant.sqlite_store import SCHEMA
from predquant.tuning_profile import (
    EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION,
    GLOBAL_BASELINE_PROFILE_ID,
    MODEL_LANE_POLICY_PATH,
    TuningProfileError,
    default_tunable_registry_metadata,
    load_model_lane_policy,
    materialize_effective_profile_context,
    resolve_tuning_profile_context,
    validate_effective_profile_context,
    validate_model_lane_policy,
)


class TuningProfileTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.artifact_dir = Path(self.tempdir.name) / "artifacts"
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        ensure_case_contract_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def insert_market(self, **overrides) -> int:
        values = {
            "platform": "polymarket",
            "external_market_id": "poly-phase4",
            "slug": "phase4-market",
            "title": "Will the election fixture pass?",
            "description": "Fixture description",
            "category": "politics",
            "status": "open",
            "outcome_type": "binary",
            "closes_at": "2026-06-25T00:00:00+00:00",
            "resolves_at": "2026-06-26T00:00:00+00:00",
            "metadata": "{}",
            "current_price": 0.52,
        }
        values.update(overrides)
        cursor = self.conn.execute(
            """
            INSERT INTO markets (
              platform, external_market_id, slug, title, description, category,
              status, outcome_type, closes_at, resolves_at, metadata, current_price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(values[key] for key in [
                "platform",
                "external_market_id",
                "slug",
                "title",
                "description",
                "category",
                "status",
                "outcome_type",
                "closes_at",
                "resolves_at",
                "metadata",
                "current_price",
            ]),
        )
        return int(cursor.lastrowid)

    def insert_snapshot(self, market_id: int) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO market_snapshots (
              market_id, observed_at, last_price, best_bid, best_ask, yes_price,
              no_price, volume, open_interest, raw_payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market_id,
                "2026-06-24T17:55:00+00:00",
                None,
                0.42,
                0.48,
                None,
                None,
                1000.0,
                250.0,
                json.dumps({"phase": "four"}),
            ),
        )
        return int(cursor.lastrowid)

    def build_packet(self, *, category="politics", title=None, source_status="unknown", quotes=None):
        market_id = self.insert_market(
            category=category,
            title=title or "Will the election fixture pass?",
            external_market_id=f"poly-{category}-{len(category)}",
        )
        snapshot_id = self.insert_snapshot(market_id)
        contract_result = materialize_ads_case_contract(
            self.conn,
            market_id=market_id,
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            artifact_dir=self.artifact_dir,
        )
        snapshot = self.conn.execute(
            "SELECT * FROM market_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        packet = build_evidence_packet_v2(
            case_contract=contract_result["contract"],
            case_contract_ref=contract_result["artifact_id"],
            market_snapshot=snapshot,
            quote_observations=quotes if quotes is not None else [
                {
                    "ref_id": "quote:phase4",
                    "observed_at": "2026-06-24T17:58:00+00:00",
                    "best_bid": 0.50,
                    "best_ask": 0.52,
                    "volume": 500,
                    "open_interest": 300,
                }
            ],
            source_of_truth_status=source_status,
        )
        return packet, contract_result

    def active_pointer(self, pointer_id: str):
        return {
            "pointer_id": pointer_id,
            "status": "active",
            "promotion_status": "promoted",
            "canary_status": "passing",
        }

    def test_unknown_domain_falls_back_to_global_with_optional_conservative_overlay(self):
        packet, contract_result = self.build_packet(
            category="novelty",
            title="Will the unusual fixture happen?",
            source_status="unknown",
        )
        context = resolve_tuning_profile_context(
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
            active_overlay_pointers={
                "conservative_source_unknown_overlay": self.active_pointer("ptr-source-unknown"),
            },
        )

        self.assertEqual(context["market_regime_tags"]["tags"]["domain_family"], "unknown")
        self.assertEqual(context["intended_domain_profile_id"], GLOBAL_BASELINE_PROFILE_ID)
        self.assertEqual(context["active_domain_profile_id"], GLOBAL_BASELINE_PROFILE_ID)
        self.assertIn("conservative_source_unknown_overlay", context["conservative_overlay_ids"])

    def test_sports_and_crypto_profiles_are_excluded_even_with_active_pointers(self):
        for category, title, expected_profile in [
            ("sports", "Will the NBA fixture pass?", "sports_price_sensitive_profile"),
            ("crypto", "Will Bitcoin close higher?", "crypto_price_sensitive_profile"),
        ]:
            packet, contract_result = self.build_packet(category=category, title=title)
            context = resolve_tuning_profile_context(
                evidence_packet=packet,
                evidence_packet_ref=contract_result["artifact_id"],
                active_domain_pointers={expected_profile: self.active_pointer(f"ptr-{category}")},
            )
            self.assertEqual(context["intended_domain_profile_id"], expected_profile)
            self.assertEqual(context["intended_profile_status"], "excluded_initial_profile")
            self.assertEqual(context["active_domain_profile_id"], GLOBAL_BASELINE_PROFILE_ID)
            self.assertIsNone(context["active_domain_pointer_id"])

    def test_inactive_candidate_domain_profile_is_recorded_as_intended(self):
        packet, contract_result = self.build_packet(category="politics")
        context = resolve_tuning_profile_context(
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
        )

        self.assertEqual(context["intended_domain_profile_id"], "politics_domain_profile")
        self.assertEqual(context["intended_profile_status"], "intended_but_inactive")
        self.assertEqual(context["active_domain_profile_id"], GLOBAL_BASELINE_PROFILE_ID)

    def test_promoted_active_domain_profile_can_be_selected(self):
        packet, contract_result = self.build_packet(category="politics")
        registry = default_tunable_registry_metadata()
        for profile in registry["domain_profiles"]:
            if profile["profile_id"] == "politics_domain_profile":
                profile["promotion_status"] = "promoted"
        context = resolve_tuning_profile_context(
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
            registry_metadata=registry,
            active_domain_pointers={
                "politics_domain_profile": self.active_pointer("ptr-politics"),
            },
        )

        self.assertEqual(context["intended_domain_profile_id"], "politics_domain_profile")
        self.assertEqual(context["intended_profile_status"], "active")
        self.assertEqual(context["active_domain_profile_id"], "politics_domain_profile")
        self.assertEqual(context["active_domain_pointer_id"], "ptr-politics")

    def test_conservative_overlay_requires_matching_tag_and_active_pointer(self):
        packet, contract_result = self.build_packet(
            category="politics",
            source_status="clear",
            quotes=[
                {
                    "ref_id": "quote:wide",
                    "observed_at": "2026-06-24T17:58:00+00:00",
                    "best_bid": 0.20,
                    "best_ask": 0.50,
                    "volume": 500,
                }
            ],
        )
        without_pointer = resolve_tuning_profile_context(
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
        )
        with_pointer = resolve_tuning_profile_context(
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
            active_overlay_pointers={
                "conservative_thin_liquidity_overlay": self.active_pointer("ptr-thin"),
            },
        )

        self.assertEqual(without_pointer["conservative_overlay_ids"], [])
        self.assertIn("conservative_thin_liquidity_overlay", with_pointer["conservative_overlay_ids"])

    def test_unpromoted_overlay_cannot_apply_live_even_with_pointer(self):
        packet, contract_result = self.build_packet(
            category="novelty",
            source_status="unknown",
        )
        registry = default_tunable_registry_metadata()
        for overlay in registry["conservative_overlays"]:
            if overlay["overlay_id"] == "conservative_source_unknown_overlay":
                overlay["promotion_status"] = "inactive_candidate"

        with self.assertRaisesRegex(TuningProfileError, "must be promoted"):
            resolve_tuning_profile_context(
                evidence_packet=packet,
                evidence_packet_ref=contract_result["artifact_id"],
                registry_metadata=registry,
                active_overlay_pointers={
                    "conservative_source_unknown_overlay": self.active_pointer("ptr-source-unknown"),
                },
            )

    def test_profile_context_rejects_numeric_scae_authoring(self):
        packet, contract_result = self.build_packet(category="politics")
        context = resolve_tuning_profile_context(
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
        )
        context["subsystem_policy_slices"][0]["scae_weight"] = 0.2
        with self.assertRaisesRegex(TuningProfileError, "not allowed"):
            validate_effective_profile_context(context)

    def test_model_lane_policy_validates_defaults_boundaries_and_embedding_lane(self):
        policy = load_model_lane_policy(MODEL_LANE_POLICY_PATH)
        self.assertEqual(policy["lanes"]["decomposer_qdt_generation"]["default_model_id"], "gpt-5.5-high")
        self.assertEqual(policy["lanes"]["researcher_leaf_nli_classification"]["default_model_id"], "gpt-5.5-high")
        self.assertEqual(policy["lanes"]["native_research_candidate_discovery"]["default_model_id"], "gpt-5.5-high")
        self.assertTrue(policy["lanes"]["native_research_candidate_discovery"]["native_research_capability_required"])
        self.assertEqual(
            policy["lanes"]["source_metadata_classifier_assist"]["default_provider_model_key"],
            "openai/gpt-5.4-mini",
        )
        self.assertIn("probability", policy["lanes"]["native_research_candidate_discovery"]["forbidden_outputs"])
        self.assertIn("scae_evidence_delta", policy["lanes"]["native_research_candidate_discovery"]["forbidden_outputs"])
        self.assertFalse(policy["authority_boundary"]["scae_numeric_aggregation_uses_model"])
        self.assertEqual(policy["local_embedding_lanes"]["amrg_vector_embedding"]["provider"], "ollama")
        self.assertEqual(
            policy["local_embedding_lanes"]["amrg_vector_embedding"]["default_model_id"],
            "BAAI/bge-base-en-v1.5",
        )

        invalid = json.loads(json.dumps(policy))
        invalid["lanes"]["source_metadata_classifier_assist"]["default_model_id"] = "gpt-5.5-high"
        with self.assertRaisesRegex(TuningProfileError, "gpt-5.4-mini"):
            validate_model_lane_policy(invalid)

    def test_effective_profile_context_artifact_registers_manifest(self):
        packet, contract_result = self.build_packet(category="politics")
        result = materialize_effective_profile_context(
            self.conn,
            evidence_packet=packet,
            evidence_packet_ref=contract_result["artifact_id"],
            artifact_dir=self.artifact_dir,
        )
        context = result["context"]
        self.assertEqual(context["schema_version"], EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION)
        self.assertTrue(Path(result["artifact_path"]).is_file())

        row = self.conn.execute(
            """
            SELECT artifact_type, artifact_schema_version, input_manifest_ids, validation_status, metadata
            FROM case_artifact_manifest
            WHERE artifact_id = ?
            """,
            (result["artifact_id"],),
        ).fetchone()
        self.assertEqual(row["artifact_type"], "effective-tuning-profile-context")
        self.assertEqual(row["artifact_schema_version"], EFFECTIVE_PROFILE_CONTEXT_SCHEMA_VERSION)
        self.assertIn(contract_result["artifact_id"], json.loads(row["input_manifest_ids"]))
        self.assertEqual(row["validation_status"], "valid")
        self.assertEqual(
            json.loads(row["metadata"])["effective_profile_sha256"],
            context["effective_profile_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
