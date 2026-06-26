#!/usr/bin/env python3
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_storage_maintenance import apply_storage_maintenance, build_storage_maintenance_plan


class AdsStorageMaintenanceTest(unittest.TestCase):
    def test_plan_and_apply_prunes_only_expired_operational_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "maintenance.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE v2_stage_execution_events (
                      id INTEGER PRIMARY KEY,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                conn.executemany(
                    "INSERT INTO v2_stage_execution_events (created_at) VALUES (?)",
                    [
                        ("2000-01-01T00:00:00+00:00",),
                        ("2999-01-01T00:00:00+00:00",),
                    ],
                )
                conn.commit()
            finally:
                conn.close()

            plan = build_storage_maintenance_plan(db_path, retention_days=90)
            event_plan = next(
                item for item in plan["retention_candidates"] if item["table"] == "v2_stage_execution_events"
            )
            self.assertEqual(event_plan["candidate_rows"], 1)

            result = apply_storage_maintenance(db_path, retention_days=90)
            self.assertEqual(result["deleted_rows"]["v2_stage_execution_events"], 1)

            conn = sqlite3.connect(db_path)
            try:
                remaining = conn.execute("SELECT COUNT(*) FROM v2_stage_execution_events").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(remaining, 1)


if __name__ == "__main__":
    unittest.main()
