#!/usr/bin/env python3
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_case_selector import (
    CASE_LEASE_TABLE,
    CASE_SELECTION_POLICY_REF,
    CaseLeaseRefused,
    CaseSelectionPolicy,
    acquire_case_lease,
    acquire_next_case_lease,
    ensure_case_selector_schema,
    release_case_lease,
    select_eligible_case,
)
from predquant.ads_pipeline_runner import (
    PipelineRunnerPolicy,
    build_pipeline_control_state,
    build_pipeline_run,
    write_pipeline_control_state,
    write_pipeline_run,
)
from predquant.sqlite_store import SCHEMA


class AdsCaseSelectorTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        ensure_case_selector_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def insert_market(self, **overrides) -> int:
        values = {
            "platform": "polymarket",
            "external_market_id": "poly-1",
            "slug": "fixture-market",
            "title": "Will the AUTO-002 fixture pass?",
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
            tuple(
                values[key]
                for key in [
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
                ]
            ),
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

    def enable_pipeline(self):
        write_pipeline_control_state(
            self.conn,
            build_pipeline_control_state(
                pipeline_enabled=True,
                updated_by="fixture",
                reason="unit test enables case lease acquisition",
            ),
        )

    def create_pipeline_run(self) -> str:
        record = build_pipeline_run(
            policy=PipelineRunnerPolicy(),
            status="running",
            terminal_reason="unit_test_selector_active_run",
        )
        write_pipeline_run(self.conn, record)
        return record["pipeline_run_id"]

    def policy(self) -> CaseSelectionPolicy:
        return CaseSelectionPolicy(
            forecast_timestamp="2026-06-24T18:00:00+00:00",
            lease_duration_seconds=900,
            metadata={"test_scope": "AUTO-002"},
        )

    def test_disabled_pipeline_refuses_explicit_lease_and_writes_no_forecasts(self):
        market_id = self.insert_market()
        self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00")
        self.conn.execute(
            """
            INSERT INTO market_predictions (market_id, predicted_at, predicted_probability, prediction_source)
            VALUES (?, ?, ?, ?)
            """,
            (market_id, "2026-06-24T17:00:00+00:00", 0.5, "fixture"),
        )
        before_predictions = self.conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0]
        candidate = select_eligible_case(self.conn, self.policy())

        with self.assertRaises(CaseLeaseRefused) as raised:
            acquire_case_lease(
                self.conn,
                pipeline_run_id="ads-pipeline-run:disabled",
                candidate=candidate,
                policy=self.policy(),
                lease_acquired_at="2026-06-24T18:00:00+00:00",
            )

        self.assertEqual(raised.exception.reason_code, "pipeline_disabled")
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0], before_predictions)

    def test_enabled_acquire_next_lease_binds_unique_case_and_snapshot(self):
        market_id = self.insert_market()
        old_snapshot_id = self.insert_snapshot(market_id, "2026-06-24T17:40:00+00:00")
        selected_snapshot_id = self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00")
        self.insert_snapshot(market_id, "2026-06-24T18:05:00+00:00")
        self.enable_pipeline()
        run_id = self.create_pipeline_run()

        lease = acquire_next_case_lease(
            self.conn,
            pipeline_run_id=run_id,
            policy=self.policy(),
        )

        self.assertIsNotNone(lease)
        self.assertEqual(lease["pipeline_run_id"], run_id)
        self.assertEqual(lease["market_id"], market_id)
        self.assertEqual(lease["case_key"], "polymarket:poly-1")
        self.assertEqual(lease["lease_status"], "leased")
        self.assertEqual(lease["lease_owner"], "orchestrator")
        self.assertEqual(lease["selected_snapshot_id"], selected_snapshot_id)
        self.assertNotEqual(lease["selected_snapshot_id"], old_snapshot_id)
        self.assertEqual(lease["selection_policy_ref"], CASE_SELECTION_POLICY_REF)
        self.assertTrue(lease["idempotency_key"].startswith("sha256:"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM market_predictions").fetchone()[0], 0)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 1)

    def test_acquire_next_does_not_lease_same_market_case_twice_concurrently(self):
        market_id = self.insert_market()
        self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00")
        self.enable_pipeline()
        run_id = self.create_pipeline_run()

        first = acquire_next_case_lease(self.conn, pipeline_run_id=run_id, policy=self.policy())
        second = acquire_next_case_lease(self.conn, pipeline_run_id=run_id, policy=self.policy())

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 1)

    def test_policy_can_skip_markets_with_existing_ads_scoreable_predictions(self):
        first_market_id = self.insert_market(external_market_id="poly-1", slug="first-fixture-market")
        second_market_id = self.insert_market(external_market_id="poly-2", slug="second-fixture-market")
        self.insert_snapshot(first_market_id, "2026-06-24T17:55:00+00:00")
        self.insert_snapshot(second_market_id, "2026-06-24T17:54:00+00:00")
        self.conn.execute(
            """
            INSERT INTO market_predictions (
              market_id, predicted_at, predicted_probability,
              prediction_source, prediction_label
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                first_market_id,
                "2026-06-24T17:56:00+00:00",
                0.51,
                "ads_pipeline",
                "v2_scae",
            ),
        )

        candidate = select_eligible_case(
            self.conn,
            CaseSelectionPolicy(
                forecast_timestamp="2026-06-24T18:00:00+00:00",
                skip_existing_ads_predictions=True,
            ),
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["market_id"], second_market_id)
        self.assertEqual(candidate["case_key"], "polymarket:poly-2")

    def test_explicit_acquire_is_idempotent_for_same_case_market_snapshot(self):
        market_id = self.insert_market()
        self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00")
        self.enable_pipeline()
        run_id = self.create_pipeline_run()
        other_run_id = self.create_pipeline_run()
        candidate = select_eligible_case(self.conn, self.policy())

        first = acquire_case_lease(
            self.conn,
            pipeline_run_id=run_id,
            candidate=candidate,
            policy=self.policy(),
            lease_acquired_at="2026-06-24T18:00:00+00:00",
        )
        retry = acquire_case_lease(
            self.conn,
            pipeline_run_id=run_id,
            candidate=candidate,
            policy=self.policy(),
            lease_acquired_at="2026-06-24T18:01:00+00:00",
        )
        other_run_retry = acquire_case_lease(
            self.conn,
            pipeline_run_id=other_run_id,
            candidate=candidate,
            policy=self.policy(),
            lease_acquired_at="2026-06-24T18:02:00+00:00",
        )

        self.assertEqual(retry["case_lease_id"], first["case_lease_id"])
        self.assertEqual(retry["idempotency_key"], first["idempotency_key"])
        self.assertIsNone(other_run_retry)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 1)

    def test_no_valid_pre_forecast_snapshot_means_no_lease(self):
        market_id = self.insert_market()
        self.insert_snapshot(market_id, "2026-06-24T18:05:00+00:00")
        self.enable_pipeline()
        run_id = self.create_pipeline_run()

        lease = acquire_next_case_lease(self.conn, pipeline_run_id=run_id, policy=self.policy())

        self.assertIsNone(lease)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 0)

    def test_released_snapshot_is_not_selected_again(self):
        market_id = self.insert_market()
        self.insert_snapshot(market_id, "2026-06-24T17:55:00+00:00")
        self.enable_pipeline()
        run_id = self.create_pipeline_run()

        first = acquire_next_case_lease(self.conn, pipeline_run_id=run_id, policy=self.policy())
        released = release_case_lease(
            self.conn,
            case_lease_id=first["case_lease_id"],
            release_reason="unit_test_complete",
            released_at="2026-06-24T18:10:00+00:00",
        )
        next_lease = acquire_next_case_lease(self.conn, pipeline_run_id=run_id, policy=self.policy())

        self.assertEqual(released["lease_status"], "released")
        self.assertIsNone(next_lease)
        self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {CASE_LEASE_TABLE}").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
