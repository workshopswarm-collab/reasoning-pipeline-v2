#!/usr/bin/env python3
import argparse
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEALTH_PATH = ROOT / "bin" / "check_pipeline_health.py"
spec = importlib.util.spec_from_file_location("check_pipeline_health", HEALTH_PATH)
check_pipeline_health = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(check_pipeline_health)

from predquant.polymarket_resolution import ensure_resolution_sync_heartbeat_schema  # noqa: E402
from predquant.sqlite_store import initialize_database  # noqa: E402


class PipelineHealthTest(unittest.TestCase):
    def test_resolution_sync_heartbeat_clears_stale_market_resolution_timestamp(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "predquant.sqlite3"
            initialize_database(db_path)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO markets (
                      platform, external_market_id, slug, title, description, category,
                      status, outcome_type, closes_at, resolves_at, metadata,
                      current_price, resolution_checked_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "polymarket",
                        "poly-health-1",
                        "health-fixture",
                        "Will the health fixture pass?",
                        "Fixture",
                        "test",
                        "resolved",
                        "binary",
                        "2026-06-25T00:00:00+00:00",
                        "2026-06-26T00:00:00+00:00",
                        "{}",
                        0.5,
                        "2000-01-01T00:00:00+00:00",
                    ),
                )
                ensure_resolution_sync_heartbeat_schema(conn)
                conn.execute(
                    """
                    INSERT INTO polymarket_resolution_sync_heartbeats (
                      heartbeat_id, checked_at, candidate_count, resolved_count,
                      unresolved_count, error_count, dry_run, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "polymarket-resolution-sync-current",
                        datetime.now(timezone.utc).isoformat(),
                        0,
                        0,
                        0,
                        0,
                        0,
                        "{}",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            args = argparse.Namespace(
                max_market_snapshot_age_seconds=3600.0,
                max_brier_age_seconds=172800.0,
                max_resolution_sync_age_seconds=5400.0,
            )
            report = check_pipeline_health.build_report(db_path, args)

        self.assertTrue(report["ok"], report["issues"])
        self.assertNotIn("resolution_sync_stale", report["issues"])
        self.assertIsNotNone(report["latest_resolution_sync_heartbeat_at"])


if __name__ == "__main__":
    unittest.main()
