#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_live_market_e2e_phase0 import (
    ACTIVE_WORK_LEFT_AFTER_TIMEOUT,
    BLOCKED_BY_UPSTREAM_QDT,
    NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK,
    QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE,
    RETRIEVAL_CHILD_PROCESS_ORPHANED,
    RETRIEVAL_STAGE_TIMEOUT,
    build_live_market_phase0_report,
    classify_downstream_isolation_audit,
    classify_live_market_audit,
    load_live_market_phase0_fixture,
)
from predquant.ads_stage_health import (
    ATTEMPTED_AND_FAILED,
    build_stage_health_from_handoff,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "ads_live_market_e2e_phase0"


class AdsLiveMarketE2EPhase0Test(unittest.TestCase):
    def test_primary_qdt_failure_fixture_preserves_terminal_temporal_role_blocker(self):
        fixture = load_live_market_phase0_fixture(FIXTURE_DIR / "primary-qdt-failure.json")

        taxonomy = classify_live_market_audit(
            run=fixture["run"],
            events=fixture["events"],
            runtime_call=fixture["runtime_call"],
            protected_write_deltas=fixture["protected_write_deltas"],
        )

        self.assertEqual(
            taxonomy["primary_qdt_blocker"],
            QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE,
        )
        self.assertIn(QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE, taxonomy["status_codes"])
        self.assertIn(BLOCKED_BY_UPSTREAM_QDT, taxonomy["status_codes"])
        self.assertEqual(taxonomy["stage_statuses"]["retrieval"], NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK)
        self.assertNotIn(RETRIEVAL_STAGE_TIMEOUT, taxonomy["status_codes"])
        self.assertTrue(taxonomy["qdt_schema_repair_attempted"])
        self.assertFalse(taxonomy["scoreable_write_observed"])

        stage_health = build_stage_health_from_handoff(
            stage_order=fixture["run"]["stage_order"],
            stages=[
                {
                    "stage": "decomposition",
                    "status": "failed",
                    "reason_codes": [taxonomy["primary_qdt_blocker"]],
                    "output_manifests": [],
                }
            ],
        )
        by_stage = {item["stage"]: item for item in stage_health}
        self.assertEqual(by_stage["decomposition"]["health"], ATTEMPTED_AND_FAILED)
        self.assertEqual(by_stage["retrieval"]["health"], NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK)
        self.assertEqual(by_stage["retrieval"]["blocked_by"], "decomposition")
        self.assertIn(BLOCKED_BY_UPSTREAM_QDT, by_stage["retrieval"]["reason_codes"])
        self.assertEqual(by_stage["researcher"]["health"], NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK)
        self.assertEqual(by_stage["scae"]["health"], NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK)

    def test_downstream_isolation_fixture_preserves_retrieval_timeout_and_orphan(self):
        fixture = load_live_market_phase0_fixture(FIXTURE_DIR / "downstream-retrieval-hang.json")

        taxonomy = classify_downstream_isolation_audit(fixture)

        self.assertEqual(taxonomy["retrieval_hang_state"], RETRIEVAL_STAGE_TIMEOUT)
        self.assertIn(RETRIEVAL_STAGE_TIMEOUT, taxonomy["status_codes"])
        self.assertIn(RETRIEVAL_CHILD_PROCESS_ORPHANED, taxonomy["status_codes"])
        self.assertIn(ACTIVE_WORK_LEFT_AFTER_TIMEOUT, taxonomy["status_codes"])
        self.assertEqual(taxonomy["stage_statuses"]["retrieval"], RETRIEVAL_STAGE_TIMEOUT)
        self.assertEqual(taxonomy["active_counts"], {"active_runs": 1, "active_leases": 1})
        self.assertFalse(taxonomy["scoreable_write_observed"])

    def test_phase0_report_names_upstream_block_and_downstream_hang_separately(self):
        primary = load_live_market_phase0_fixture(FIXTURE_DIR / "primary-qdt-failure.json")
        downstream = load_live_market_phase0_fixture(FIXTURE_DIR / "downstream-retrieval-hang.json")

        report = build_live_market_phase0_report(
            primary_fixture=primary,
            downstream_fixture=downstream,
        )

        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(
            report["primary_qdt_blocker"],
            QDT_SCHEMA_REPAIR_REMAINING_TERMINAL_TEMPORAL_ROLE,
        )
        self.assertEqual(report["downstream_retrieval_hang"], RETRIEVAL_STAGE_TIMEOUT)
        self.assertEqual(
            report["primary_true_live"]["stage_statuses"]["retrieval"],
            NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK,
        )
        self.assertEqual(
            report["downstream_isolation"]["stage_statuses"]["retrieval"],
            RETRIEVAL_STAGE_TIMEOUT,
        )
        self.assertIn(NOT_ATTEMPTED_DUE_UPSTREAM_BLOCK, report["taxonomy_values"])
        self.assertIn(RETRIEVAL_CHILD_PROCESS_ORPHANED, report["taxonomy_values"])
        self.assertFalse(report["scoreable_write_observed"])


if __name__ == "__main__":
    unittest.main()
