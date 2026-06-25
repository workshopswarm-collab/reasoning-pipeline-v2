#!/usr/bin/env python3
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_case_contract import (
    ADS_CASE_CONTRACT_SCHEMA_VERSION,
    CaseContractBlocked,
    CaseContractPolicy,
    build_ads_case_contract,
    eligible_market_rows,
    ensure_case_contract_schema,
    materialize_ads_case_contract,
    select_snapshot_for_forecast,
    stable_ids,
)
from predquant.sqlite_store import SCHEMA, ensure_schema as ensure_sqlite_store_schema


class AdsCaseContractTest(unittest.TestCase):
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
            "raw_payload": json.dumps({"snapshot": observed_at, "source": "fixture"}, sort_keys=True),
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

    def test_valid_fixture_contract_persists_manifest_handoff_and_contract_idempotently(self):
        market_id = self.insert_market()
        older_snapshot_id = self.insert_snapshot(market_id, "2026-06-24T17:45:00+00:00", best_bid=0.2, best_ask=0.3)
        selected_snapshot_id = self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00", best_bid=0.4, best_ask=0.5)
        self.insert_snapshot(market_id, "2026-06-24T18:05:00+00:00", best_bid=0.7, best_ask=0.8)

        result = materialize_ads_case_contract(
            self.conn,
            market_id=market_id,
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            artifact_dir=self.artifact_dir,
        )
        contract = result["contract"]

        self.assertEqual(contract["schema_version"], ADS_CASE_CONTRACT_SCHEMA_VERSION)
        self.assertEqual(contract["case_key"], "polymarket:poly-1")
        self.assertEqual(contract["intake_source"]["source_tables"], ["markets", "market_snapshots"])
        self.assertEqual(contract["intake_source"]["market_row_id"], market_id)
        self.assertEqual(contract["intake_source"]["market_snapshot_id"], selected_snapshot_id)
        self.assertTrue(contract["intake_source"]["source_payload_hash"].startswith("sha256:"))
        self.assertEqual(contract["prediction_time_market_baseline"]["snapshot_age_seconds_at_dispatch"], 300.0)
        self.assertAlmostEqual(contract["prediction_time_market_baseline"]["market_probability"], 0.45)
        self.assertEqual(contract["prediction_time_market_baseline"]["market_probability_method"], "bid_ask_midpoint")
        self.assertNotIn("raw_payload", json.dumps(contract))
        self.assertEqual(contract["raw_input_refs"][1]["payload_hash"], contract["intake_source"]["source_payload_hash"])
        self.assertNotEqual(older_snapshot_id, selected_snapshot_id)

        artifact_path = Path(result["artifact_path"])
        self.assertTrue(artifact_path.is_file())
        persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["dispatch_id"], contract["dispatch_id"])

        manifest_row = self.conn.execute("SELECT * FROM case_artifact_manifest").fetchone()
        self.assertEqual(manifest_row["artifact_id"], result["artifact_id"])
        self.assertEqual(manifest_row["artifact_type"], "ads-case-contract")
        self.assertEqual(manifest_row["artifact_schema_version"], ADS_CASE_CONTRACT_SCHEMA_VERSION)
        self.assertEqual(manifest_row["validation_status"], "valid")

        handoff_row = self.conn.execute("SELECT * FROM case_intake_handoff_records").fetchone()
        self.assertEqual(handoff_row["handoff_status"], "completed")
        self.assertEqual(handoff_row["market_snapshot_id"], selected_snapshot_id)

        retry = materialize_ads_case_contract(
            self.conn,
            market_id=market_id,
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            artifact_dir=self.artifact_dir,
        )
        self.assertEqual(retry["contract"]["case_id"], contract["case_id"])
        self.assertEqual(retry["contract"]["dispatch_id"], contract["dispatch_id"])
        self.assertEqual(retry["contract"]["prediction_run_id"], contract["prediction_run_id"])
        self.assertEqual(retry["contract"]["forecast_artifact_id"], contract["forecast_artifact_id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM ads_case_contracts").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM case_intake_handoff_records").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM case_artifact_manifest").fetchone()[0], 1)

    def test_post_forecast_lookahead_snapshot_is_blocked_and_records_handoff(self):
        market_id = self.insert_market()
        self.insert_snapshot(market_id, "2026-06-24T18:05:00+00:00")

        with self.assertRaises(CaseContractBlocked) as raised:
            materialize_ads_case_contract(
                self.conn,
                market_id=market_id,
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                artifact_dir=self.artifact_dir,
            )
        self.assertEqual(raised.exception.reason_code, "case_contract_snapshot_lookahead")
        row = self.conn.execute("SELECT handoff_status, reason_code FROM case_intake_handoff_records").fetchone()
        self.assertEqual(row["handoff_status"], "blocked")
        self.assertEqual(row["reason_code"], "case_contract_snapshot_lookahead")

    def test_stale_snapshot_blocks_with_reason_code(self):
        market_id = self.insert_market()
        snapshot_id = self.insert_snapshot(market_id, "2026-06-24T16:00:00+00:00")

        with self.assertRaises(CaseContractBlocked) as raised:
            materialize_ads_case_contract(
                self.conn,
                market_id=market_id,
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                artifact_dir=self.artifact_dir,
                policy=CaseContractPolicy(max_snapshot_age_seconds=3600.0),
            )
        self.assertEqual(raised.exception.reason_code, "case_contract_snapshot_stale")
        row = self.conn.execute("SELECT reason_code, market_snapshot_id FROM case_intake_handoff_records").fetchone()
        self.assertEqual(row["reason_code"], "case_contract_snapshot_stale")
        self.assertEqual(row["market_snapshot_id"], snapshot_id)

    def test_missing_snapshot_blocks_with_reason_code(self):
        market_id = self.insert_market()
        with self.assertRaises(CaseContractBlocked) as raised:
            select_snapshot_for_forecast(
                self.conn,
                market_id,
                "2026-06-24T18:00:00+00:00",
                max_snapshot_age_seconds=3600.0,
            )
        self.assertEqual(raised.exception.reason_code, "case_contract_snapshot_missing")

    def test_stable_ids_for_same_market_and_forecast_timestamp(self):
        market_id = self.insert_market()
        market = self.conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        first = stable_ids(dict(market), "2026-06-24T18:00:00+00:00")
        second = stable_ids(dict(market), "2026-06-24T18:00:00+00:00")
        changed = stable_ids(dict(market), "2026-06-24T18:01:00+00:00")

        self.assertEqual(first, second)
        self.assertEqual(first["case_id"], changed["case_id"])
        self.assertNotEqual(first["dispatch_id"], changed["dispatch_id"])
        self.assertNotEqual(first["prediction_run_id"], changed["prediction_run_id"])
        self.assertNotEqual(first["forecast_artifact_id"], changed["forecast_artifact_id"])

    def test_yes_last_and_current_price_baseline_methods(self):
        market_id = self.insert_market(current_price=0.62)
        yes_snapshot_id = self.insert_snapshot(
            market_id,
            "2026-06-24T17:55:00+00:00",
            best_bid=None,
            best_ask=None,
            yes_price=0.57,
        )
        market = self.conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
        yes_snapshot = self.conn.execute("SELECT * FROM market_snapshots WHERE id = ?", (yes_snapshot_id,)).fetchone()
        yes_contract = build_ads_case_contract(market, yes_snapshot, "2026-06-24T18:00:00+00:00")
        self.assertEqual(yes_contract["prediction_time_market_baseline"]["market_probability_method"], "yes_price")

        last_market_id = self.insert_market(external_market_id="poly-2", current_price=0.63)
        last_snapshot_id = self.insert_snapshot(
            last_market_id,
            "2026-06-24T17:55:00+00:00",
            best_bid=None,
            best_ask=None,
            last_price=0.51,
        )
        last_market = self.conn.execute("SELECT * FROM markets WHERE id = ?", (last_market_id,)).fetchone()
        last_snapshot = self.conn.execute("SELECT * FROM market_snapshots WHERE id = ?", (last_snapshot_id,)).fetchone()
        last_contract = build_ads_case_contract(last_market, last_snapshot, "2026-06-24T18:00:00+00:00")
        self.assertEqual(last_contract["prediction_time_market_baseline"]["market_probability_method"], "last_price")

        current_market_id = self.insert_market(external_market_id="poly-3", current_price=0.64)
        current_snapshot_id = self.insert_snapshot(
            current_market_id,
            "2026-06-24T17:55:00+00:00",
            best_bid=None,
            best_ask=None,
            last_price=None,
            yes_price=None,
        )
        current_market = self.conn.execute("SELECT * FROM markets WHERE id = ?", (current_market_id,)).fetchone()
        current_snapshot = self.conn.execute("SELECT * FROM market_snapshots WHERE id = ?", (current_snapshot_id,)).fetchone()
        current_contract = build_ads_case_contract(current_market, current_snapshot, "2026-06-24T18:00:00+00:00")
        self.assertEqual(current_contract["prediction_time_market_baseline"]["market_probability_method"], "current_price")

    def test_eligible_market_rows_only_returns_active_open_markets(self):
        open_id = self.insert_market(external_market_id="open-market", status="open")
        active_id = self.insert_market(external_market_id="active-market", status="active")
        self.insert_market(external_market_id="closed-market", status="closed")

        rows = eligible_market_rows(self.conn)
        self.assertEqual([row["id"] for row in rows], [open_id, active_id])

    def test_migration_surfaces_exist(self):
        tables = {
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        handoff_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(case_intake_handoff_records)").fetchall()
        }
        contract_columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(ads_case_contracts)").fetchall()
        }

        self.assertIn("case_intake_handoff_records", tables)
        self.assertIn("ads_case_contracts", tables)
        self.assertIn("handoff_id", handoff_columns)
        self.assertIn("reason_code", handoff_columns)
        self.assertIn("source_payload_hash", handoff_columns)
        self.assertIn("contract_id", contract_columns)
        self.assertIn("prediction_run_id", contract_columns)
        self.assertIn("forecast_artifact_id", contract_columns)
        self.assertIn("artifact_id", contract_columns)

    def test_sqlite_store_bootstrap_upgrades_artifact_manifest_surface(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            ensure_sqlite_store_schema(conn)
            bootstrap_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(case_artifact_manifest)").fetchall()
            }
            self.assertIn("producer_stage", bootstrap_columns)
            self.assertIn("stage", bootstrap_columns)
            self.assertIn("artifact_id", bootstrap_columns)
            self.assertIn("artifact_schema_version", bootstrap_columns)
            self.assertIn("validation_status", bootstrap_columns)
            self.assertIn("validation_result_refs", bootstrap_columns)

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
                    "legacy-poly-1",
                    "legacy-fixture",
                    "Will legacy bootstrap work?",
                    "open",
                    "binary",
                    "{}",
                    0.55,
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
                    "2026-06-24T17:55:00+00:00",
                    0.44,
                    0.5,
                    json.dumps({"legacy": "fixture"}, sort_keys=True),
                ),
            ).lastrowid

            result = materialize_ads_case_contract(
                conn,
                market_id=market_id,
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                artifact_dir=self.artifact_dir,
            )

            materialized_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(case_artifact_manifest)").fetchall()
            }
            self.assertIn("stage", materialized_columns)
            self.assertIn("artifact_schema_version", materialized_columns)
            self.assertIn("validation_status", materialized_columns)
            self.assertEqual(result["contract"]["intake_source"]["market_snapshot_id"], snapshot_id)
            manifest = conn.execute("SELECT * FROM case_artifact_manifest").fetchone()
            self.assertEqual(manifest["artifact_id"], result["artifact_id"])
            self.assertEqual(manifest["stage"], "case_selection")
            self.assertEqual(manifest["producer_stage"], "case_selection")
            self.assertEqual(manifest["artifact_schema_version"], ADS_CASE_CONTRACT_SCHEMA_VERSION)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ads_case_contracts").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
