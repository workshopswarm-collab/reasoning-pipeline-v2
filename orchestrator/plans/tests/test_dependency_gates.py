#!/usr/bin/env python3
"""Static tests for ADS inventory dependency gates."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import unittest
from datetime import date, timedelta
from pathlib import Path


PLANS_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PLANS_ROOT / "autonomous-decomposition-swarm-feature-inventory.yaml"
INVENTORY_MD_PATH = PLANS_ROOT / "autonomous-decomposition-swarm-feature-inventory.md"
PHASE_REPORT_README = PLANS_ROOT / "phase-reports" / "README.md"
GATE_PATH = PLANS_ROOT / "check_dependency_gates.py"

spec = importlib.util.spec_from_file_location("check_dependency_gates", GATE_PATH)
assert spec and spec.loader
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)


def load_inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def rows_by_id(inv: dict) -> dict[str, dict]:
    features = {row["id"]: row for row in inv["features"]}
    migrations = {row["id"]: row for row in inv["migrations"]}
    return {**features, **migrations}


def markdown_feature_rows() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in INVENTORY_MD_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 8:
            continue
        feature_id = cells[0].strip("`")
        if not re.fullmatch(r"[A-Z]+-\d{3}", feature_id):
            continue
        dependency_cell = cells[5]
        dependencies = [] if dependency_cell == "none" else re.findall(r"\b[A-Z]+-\d{3}\b", dependency_cell)
        rows[feature_id] = {
            "stage": cells[1],
            "owner": cells[4],
            "dependencies": dependencies,
            "status": cells[7],
        }
    return rows


class DependencyGateTests(unittest.TestCase):
    def test_inventory_is_valid(self) -> None:
        self.assertEqual(gates.validate_inventory(load_inventory()), [])

    def test_markdown_and_yaml_feature_rows_are_synchronized(self) -> None:
        inv = load_inventory()
        md_rows = markdown_feature_rows()
        for feature in inv["features"]:
            with self.subTest(feature=feature["id"]):
                md = md_rows.get(feature["id"])
                self.assertIsNotNone(md)
                self.assertEqual(md["stage"], feature["stage"])
                self.assertEqual(md["owner"], feature["owner"])
                self.assertEqual(md["dependencies"], feature.get("dependencies", []))
                self.assertEqual(md["status"], feature["status"])

    def test_unknown_feature_dependency_is_rejected(self) -> None:
        inv = load_inventory()
        inv["features"][1]["dependencies"] = ["MISSING-999"]
        errors = gates.validate_inventory(inv)
        self.assertTrue(any("missing feature dependency MISSING-999" in error for error in errors))

    def test_feature_dependency_cycle_is_rejected(self) -> None:
        inv = load_inventory()
        by_id = {row["id"]: row for row in inv["features"]}
        by_id["FND-001"]["dependencies"] = ["FND-002"]
        errors = gates.validate_inventory(inv)
        self.assertTrue(any("dependency cycle" in error for error in errors))

    def test_unready_runtime_integration_is_blocked(self) -> None:
        inv = load_inventory()
        rows = rows_by_id(inv)
        failures = gates.can_start(rows["AUTO-003"], rows, set(inv["ready_statuses"]), inv["waivers"], "runtime_integration")
        self.assertIn("AUTO-002 status=not_started", failures)
        self.assertIn("CLS-001 status=not_started", failures)
        self.assertIn("SCAE-012 status=not_started", failures)
        self.assertNotIn("CASE-002 status=not_started", failures)
        self.assertNotIn("QDT-001 status=not_started", failures)

    def test_fixture_mode_allows_start_even_when_runtime_is_blocked(self) -> None:
        inv = load_inventory()
        rows = rows_by_id(inv)
        failures = gates.can_start(rows["AUTO-002"], rows, set(inv["ready_statuses"]), inv["waivers"], "fixture")
        self.assertEqual(failures, [])

    def test_valid_waiver_can_unblock_a_specific_target_dependency_pair(self) -> None:
        inv = load_inventory()
        expires_on = (date.today() + timedelta(days=7)).isoformat()
        inv["waivers"] = [
            {
                "dependency_id": "FND-003",
                "target_id": "FND-005",
                "owner": "Session 1",
                "reason": "fixture contract review",
                "expires_on": expires_on,
            },
            {
                "dependency_id": "FND-004",
                "target_id": "FND-005",
                "owner": "Session 1",
                "reason": "fixture contract review",
                "expires_on": expires_on,
            },
        ]
        self.assertEqual(gates.validate_inventory(inv), [])
        rows = rows_by_id(inv)
        failures = gates.can_start(rows["FND-005"], rows, set(inv["ready_statuses"]), inv["waivers"], "runtime_integration")
        self.assertEqual(failures, [])

    def test_malformed_or_expired_waivers_are_rejected(self) -> None:
        inv = load_inventory()
        malformed = copy.deepcopy(inv)
        malformed["waivers"] = [{"dependency_id": "FND-003", "target_id": "FND-005"}]
        malformed_errors = gates.validate_inventory(malformed)
        self.assertTrue(any("missing required fields" in error for error in malformed_errors))

        expired = copy.deepcopy(inv)
        expired["waivers"] = [
            {
                "dependency_id": "FND-003",
                "target_id": "FND-005",
                "owner": "Session 1",
                "reason": "stale waiver",
                "expires_on": (date.today() - timedelta(days=1)).isoformat(),
            }
        ]
        expired_errors = gates.validate_inventory(expired)
        self.assertTrue(any("is expired" in error for error in expired_errors))

    def test_status_update_requires_owner_and_acceptance_evidence(self) -> None:
        inv = load_inventory()
        rows = rows_by_id(inv)
        status_values = set(inv["status_values"])
        self.assertEqual(
            gates.validate_status_update("FND-001", "Session 1", "done", "audit passed", rows, status_values),
            [],
        )
        owner_errors = gates.validate_status_update("FND-001", "Session 2", "done", "audit passed", rows, status_values)
        self.assertTrue(any("owner is Session 1" in error for error in owner_errors))
        evidence_errors = gates.validate_status_update("FND-001", "Session 1", "done", "", rows, status_values)
        self.assertTrue(any("acceptance evidence required" in error for error in evidence_errors))

    def test_phase_report_convention_is_documented(self) -> None:
        text = PHASE_REPORT_README.read_text(encoding="utf-8")
        self.assertIn("plans/phase-reports/session-0N-phase-M-short-slug.md", text)
        for field in [
            "Session:",
            "Phase:",
            "Owner:",
            "Feature IDs:",
            "Migration Groups:",
            "Status:",
            "Acceptance Evidence:",
            "Checks Run:",
            "Shared Inventory Updates Requested:",
            "Shared Map/Matrix Updates Requested:",
            "Blockers:",
            "Commit SHA:",
        ]:
            with self.subTest(field=field):
                self.assertIn(field, text)

    def test_migration_surface_contracts_cover_write_paths_and_order(self) -> None:
        inv = load_inventory()
        contracts = inv["migration_surface_contracts"]
        self.assertEqual(contracts["implementation_order"][:3], ["MIG-001", "MIG-002", "MIG-013"])
        self.assertIn("MIG-012", contracts["implementation_order"])
        self.assertIn("MIG-011", contracts["autonomous_optimization_maturity_groups"])

        rows = rows_by_id(inv)
        for migration_id, contract in contracts["groups"].items():
            with self.subTest(migration=migration_id):
                migration = rows[migration_id]
                self.assertEqual(contract["surface_contract_status"], "ready_for_component_implementation")
                self.assertTrue(contract["destinations"])
                self.assertTrue(contract["idempotency_keys"])
                for write_path in migration["write_paths"]:
                    destinations = contract["write_path_destinations"].get(write_path)
                    self.assertTrue(destinations, f"{write_path} is missing destination coverage")
                    for destination in destinations:
                        self.assertIn(destination, contract["destinations"])

        self.assertIn(
            "ads_case_contracts",
            contracts["groups"]["MIG-012"]["write_path_destinations"]["write_ads_case_contract"],
        )
        self.assertIn(
            "effective_tuning_profile_context.json",
            contracts["groups"]["MIG-011"]["write_path_destinations"]["promote_policy_pointer"],
        )

    def test_missing_migration_write_path_destination_is_rejected(self) -> None:
        inv = load_inventory()
        broken = copy.deepcopy(inv)
        del broken["migration_surface_contracts"]["groups"]["MIG-012"]["write_path_destinations"][
            "write_ads_case_contract"
        ]
        errors = gates.validate_inventory(broken)
        self.assertTrue(
            any("MIG-012: write path write_ads_case_contract has no destination surface" in error for error in errors)
        )

    def test_migration_contract_preserves_owner_boundaries(self) -> None:
        inv = load_inventory()
        rows = rows_by_id(inv)
        for migration_id in ["MIG-001", "MIG-002", "MIG-013"]:
            self.assertEqual(rows[migration_id]["owner"], "Session 1")
        for migration_id in [
            "MIG-003",
            "MIG-004",
            "MIG-005",
            "MIG-006",
            "MIG-007",
            "MIG-008",
            "MIG-009",
            "MIG-010",
            "MIG-011",
            "MIG-012",
        ]:
            self.assertNotEqual(rows[migration_id]["owner"], "Session 1")


if __name__ == "__main__":
    unittest.main()
