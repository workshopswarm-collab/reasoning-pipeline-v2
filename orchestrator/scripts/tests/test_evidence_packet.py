#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_case_contract import ensure_case_contract_schema, materialize_ads_case_contract
from predquant.evidence_packet import (
    EVIDENCE_PACKET_SCHEMA_VERSION,
    EvidencePacketError,
    build_evidence_packet_v2,
    materialize_evidence_packet_v2,
)
from predquant.sqlite_store import SCHEMA


class EvidencePacketTest(unittest.TestCase):
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
            "external_market_id": "poly-1",
            "slug": "fixture-market",
            "title": "Will the fixture pass?",
            "description": "Fixture description",
            "category": "test",
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

    def insert_snapshot(self, market_id: int, observed_at: str, **overrides) -> int:
        values = {
            "last_price": None,
            "best_bid": 0.42,
            "best_ask": 0.48,
            "yes_price": None,
            "no_price": None,
            "volume": 1000.0,
            "open_interest": 250.0,
            "raw_payload": json.dumps({"snapshot": observed_at, "raw": "must-not-copy"}, sort_keys=True),
        }
        values.update(overrides)
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
                observed_at,
                values["last_price"],
                values["best_bid"],
                values["best_ask"],
                values["yes_price"],
                values["no_price"],
                values["volume"],
                values["open_interest"],
                values["raw_payload"],
            ),
        )
        return int(cursor.lastrowid)

    def case_contract_result(self):
        market_id = self.insert_market()
        snapshot_id = self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00")
        result = materialize_ads_case_contract(
            self.conn,
            market_id=market_id,
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            artifact_dir=self.artifact_dir,
        )
        snapshot = self.conn.execute(
            "SELECT * FROM market_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        return result, snapshot

    def test_standalone_binary_packet_registers_manifest(self):
        contract_result, snapshot = self.case_contract_result()
        result = materialize_evidence_packet_v2(
            self.conn,
            case_contract=contract_result["contract"],
            case_contract_ref=contract_result["artifact_id"],
            artifact_dir=self.artifact_dir,
            market_snapshot=snapshot,
            quote_refs=[{"ref_id": "quote:fixture", "source": "market_snapshots", "row_id": snapshot["id"]}],
            source_of_truth_status="clear",
        )
        packet = result["packet"]

        self.assertEqual(packet["schema_version"], EVIDENCE_PACKET_SCHEMA_VERSION)
        self.assertEqual(packet["case_contract_ref"], contract_result["artifact_id"])
        self.assertEqual(packet["family_context"]["mode"], "standalone_binary")
        self.assertEqual(packet["market_reality_constraints"]["contract_structure"], "binary")
        self.assertEqual(set(packet["market_reality_constraints"]["side_mapping"]), {"yes", "no"})
        axis_mapping = packet["market_reality_constraints"]["axis_mapping"]
        self.assertEqual(axis_mapping["probability_axis"], "selected_market_yes_probability")
        self.assertEqual(axis_mapping["scale"], "0_to_1")
        self.assertEqual(axis_mapping["side_directions"]["yes"]["higher_probability_means"], "market_resolves_yes")
        self.assertEqual(packet["prior_context_seed"]["market_snapshot_id"], snapshot["id"])
        self.assertEqual(packet["prior_context_seed"]["quote_observation_refs"][0]["ref_id"], "quote:fixture")
        self.assertEqual(packet["regime_seed_fields"]["contract_structure"], "binary")
        self.assertNotIn("raw_payload", json.dumps(packet))
        self.assertNotIn("must-not-copy", json.dumps(packet))

        artifact_path = Path(result["artifact_path"])
        self.assertTrue(artifact_path.is_file())
        persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["dispatch_id"], packet["dispatch_id"])

        manifest_row = self.conn.execute(
            """
            SELECT artifact_type, artifact_schema_version, input_manifest_ids, validation_status, stage
            FROM case_artifact_manifest
            WHERE artifact_id = ?
            """,
            (result["artifact_id"],),
        ).fetchone()
        self.assertEqual(manifest_row["artifact_type"], "evidence-packet-v2")
        self.assertEqual(manifest_row["artifact_schema_version"], EVIDENCE_PACKET_SCHEMA_VERSION)
        self.assertEqual(json.loads(manifest_row["input_manifest_ids"]), [contract_result["artifact_id"]])
        self.assertEqual(manifest_row["validation_status"], "valid")
        self.assertEqual(manifest_row["stage"], "evidence_packet")

    def test_family_aware_child_carries_siblings_as_context_only(self):
        contract_result, snapshot = self.case_contract_result()
        family_rows = [
            {
                "parent_event_id": "event-1",
                "child_market_id": "poly-1",
                "family_type": "exclusive",
                "relation_constraints": ["exactly_one_child_resolves_yes"],
            },
            {
                "parent_event_id": "event-1",
                "child_market_id": "poly-2",
                "family_type": "exclusive",
                "relation_constraints": ["same_parent"],
                "sibling_price": 0.22,
                "sibling_price_method": "yes_price",
            },
        ]
        packet = build_evidence_packet_v2(
            case_contract=contract_result["contract"],
            case_contract_ref=contract_result["artifact_id"],
            market_snapshot=snapshot,
            family_rows=family_rows,
        )

        family = packet["family_context"]
        self.assertEqual(family["mode"], "family_aware_binary_child")
        self.assertEqual(family["parent_event_id"], "event-1")
        self.assertEqual(family["selected_child_market_id"], "poly-1")
        self.assertEqual(family["sibling_child_ids"], ["poly-2"])
        self.assertEqual(family["relation_constraints"], ["exactly_one_child_resolves_yes"])
        self.assertEqual(family["sibling_prices"][0]["child_market_id"], "poly-2")
        self.assertTrue(family["sibling_prices"][0]["context_only"])
        self.assertEqual(packet["market_reality_constraints"]["contract_structure"], "family_aware_binary_child")
        self.assertEqual(packet["regime_seed_fields"]["family_type"], "exclusive")

    def test_family_aware_context_requires_selected_child_parent_and_constraints(self):
        contract_result, snapshot = self.case_contract_result()
        with self.assertRaisesRegex(EvidencePacketError, "selected child"):
            build_evidence_packet_v2(
                case_contract=contract_result["contract"],
                case_contract_ref=contract_result["artifact_id"],
                market_snapshot=snapshot,
                family_rows=[{"parent_event_id": "event-1", "child_market_id": "poly-2"}],
            )
        with self.assertRaisesRegex(EvidencePacketError, "parent_event_id"):
            build_evidence_packet_v2(
                case_contract=contract_result["contract"],
                case_contract_ref=contract_result["artifact_id"],
                market_snapshot=snapshot,
                family_rows=[{"child_market_id": "poly-1", "relation_constraints": ["exclusive"]}],
            )
        with self.assertRaisesRegex(EvidencePacketError, "relation_constraints"):
            build_evidence_packet_v2(
                case_contract=contract_result["contract"],
                case_contract_ref=contract_result["artifact_id"],
                market_snapshot=snapshot,
                family_rows=[{"parent_event_id": "event-1", "child_market_id": "poly-1"}],
            )

    def test_invalid_side_mapping_and_case_contract_fail_closed(self):
        contract_result, snapshot = self.case_contract_result()
        with self.assertRaisesRegex(EvidencePacketError, "side_mapping"):
            build_evidence_packet_v2(
                case_contract=contract_result["contract"],
                case_contract_ref=contract_result["artifact_id"],
                market_snapshot=snapshot,
                side_mapping={"yes": {"outcome": "yes", "resolves_to": "market_resolves_yes"}},
            )

        invalid_contract = dict(contract_result["contract"])
        invalid_contract["schema_version"] = "ads-case-contract/v0"
        with self.assertRaisesRegex(EvidencePacketError, "invalid ADS case contract"):
            build_evidence_packet_v2(
                case_contract=invalid_contract,
                case_contract_ref=contract_result["artifact_id"],
                market_snapshot=snapshot,
            )

    def test_missing_case_contract_ref_is_rejected(self):
        contract_result, snapshot = self.case_contract_result()
        with self.assertRaisesRegex(EvidencePacketError, "case_contract_ref"):
            build_evidence_packet_v2(
                case_contract=contract_result["contract"],
                case_contract_ref="",
                market_snapshot=snapshot,
            )


if __name__ == "__main__":
    unittest.main()
