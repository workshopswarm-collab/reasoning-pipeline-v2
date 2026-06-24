#!/usr/bin/env python3
"""Validate v2 feature inventory dependencies.

The inventory file is JSON-compatible YAML so this script intentionally uses
only the Python standard library. Fixture work may start early, but runtime,
calibration, and maturity modes require upstream rows to be ready or explicitly
waived.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INVENTORY = ROOT / "autonomous-decomposition-swarm-feature-inventory.yaml"
EVIDENCE_REQUIRED_STATUSES = {"ready_for_integration", "done"}
WAIVER_REQUIRED_FIELDS = ["dependency_id", "target_id", "owner", "reason", "expires_on"]


def load_inventory(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"inventory must remain JSON-compatible YAML: {exc}") from exc


def index_rows(rows: list[dict], key: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        row_id = row.get(key)
        if not row_id:
            raise SystemExit(f"row missing {key}: {row}")
        if row_id in indexed:
            raise SystemExit(f"duplicate {key}: {row_id}")
        indexed[row_id] = row
    return indexed


def waiver_is_valid(waiver: dict, dependency_id: str, target_id: str) -> bool:
    if waiver.get("dependency_id") != dependency_id:
        return False
    if waiver.get("target_id") != target_id:
        return False
    required = ["owner", "reason", "expires_on"]
    if any(not waiver.get(field) for field in required):
        return False
    try:
        return date.fromisoformat(waiver["expires_on"]) >= date.today()
    except ValueError:
        return False


def validate_waivers(waivers: list[dict], rows: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    today = date.today()
    for idx, waiver in enumerate(waivers):
        prefix = f"waiver[{idx}]"
        missing = [field for field in WAIVER_REQUIRED_FIELDS if not waiver.get(field)]
        if missing:
            errors.append(f"{prefix}: missing required fields {', '.join(missing)}")
            continue

        dependency_id = waiver["dependency_id"]
        target_id = waiver["target_id"]
        if dependency_id not in rows:
            errors.append(f"{prefix}: unknown dependency_id {dependency_id}")
        if target_id not in rows:
            errors.append(f"{prefix}: unknown target_id {target_id}")

        try:
            expires_on = date.fromisoformat(waiver["expires_on"])
        except ValueError:
            errors.append(f"{prefix}: expires_on must be YYYY-MM-DD")
            continue
        if expires_on < today:
            errors.append(f"{prefix}: expires_on {waiver['expires_on']} is expired")
    return errors


def dependency_ready(dep_id: str, target_id: str, rows: dict[str, dict], ready: set[str], waivers: list[dict]) -> tuple[bool, str]:
    dep = rows.get(dep_id)
    if dep is None:
        return False, f"missing dependency {dep_id}"
    if dep.get("status") in ready:
        return True, "ready"
    if any(waiver_is_valid(waiver, dep_id, target_id) for waiver in waivers):
        return True, "waived"
    return False, f"{dep_id} status={dep.get('status')}"


def can_start(row: dict, rows: dict[str, dict], ready: set[str], waivers: list[dict], mode: str) -> list[str]:
    if mode == "fixture":
        return []
    failures: list[str] = []
    for dep_id in row.get("dependencies", []):
        ok, reason = dependency_ready(dep_id, row["id"], rows, ready, waivers)
        if not ok:
            failures.append(reason)
    return failures


def find_feature_cycles(features: dict[str, dict]) -> list[list[str]]:
    cycles: list[list[str]] = []
    state: dict[str, str] = {}
    stack: list[str] = []

    def visit(feature_id: str) -> None:
        state[feature_id] = "visiting"
        stack.append(feature_id)
        for dep_id in features[feature_id].get("dependencies", []):
            if dep_id not in features:
                continue
            if state.get(dep_id) == "visiting":
                start = stack.index(dep_id)
                cycles.append(stack[start:] + [dep_id])
            elif state.get(dep_id) != "visited":
                visit(dep_id)
        stack.pop()
        state[feature_id] = "visited"

    for feature_id in features:
        if state.get(feature_id) is None:
            visit(feature_id)
    return cycles


def validate_inventory(inv: dict) -> list[str]:
    errors: list[str] = []
    status_values = set(inv.get("status_values", []))
    ready_statuses = set(inv.get("ready_statuses", []))
    features = index_rows(inv.get("features", []), "id")
    migrations = index_rows(inv.get("migrations", []), "id")
    combined = {**features, **migrations}

    if not status_values:
        errors.append("missing status_values")
    if not ready_statuses:
        errors.append("missing ready_statuses")
    unknown_ready = ready_statuses - status_values
    if unknown_ready:
        errors.append("ready_statuses contain unknown values: " + ", ".join(sorted(unknown_ready)))

    for feature_id, feature in features.items():
        if feature.get("status") not in status_values:
            errors.append(f"{feature_id}: invalid status {feature.get('status')}")
        if not feature.get("owner"):
            errors.append(f"{feature_id}: missing owner")
        for dep_id in feature.get("dependencies", []):
            if dep_id not in features:
                errors.append(f"{feature_id}: missing feature dependency {dep_id}")

    for cycle in find_feature_cycles(features):
        errors.append("dependency cycle: " + " -> ".join(cycle))

    for migration_id, migration in migrations.items():
        if migration.get("status") not in status_values:
            errors.append(f"{migration_id}: invalid status {migration.get('status')}")
        if not migration.get("owner"):
            errors.append(f"{migration_id}: missing owner")
        if not migration.get("write_paths"):
            errors.append(f"{migration_id}: missing write_paths")
        for feature_id in migration.get("feature_ids", []):
            if feature_id not in features:
                errors.append(f"{migration_id}: unknown feature_id {feature_id}")
        for dep_id in migration.get("dependencies", []):
            if dep_id not in features and dep_id not in migrations:
                errors.append(f"{migration_id}: missing dependency {dep_id}")
    errors.extend(validate_waivers(inv.get("waivers", []), combined))
    return errors


def validate_status_update(row_id: str, session: str, new_status: str, acceptance_evidence: str, rows: dict[str, dict], status_values: set[str]) -> list[str]:
    errors: list[str] = []
    row = rows.get(row_id)
    if row is None:
        return [f"{row_id}: unknown row"]
    if row.get("owner") != session:
        errors.append(f"{row_id}: owner is {row.get('owner')}, not {session}")
    if new_status not in status_values:
        errors.append(f"{row_id}: invalid status {new_status}")
    if new_status in EVIDENCE_REQUIRED_STATUSES and not acceptance_evidence:
        errors.append(f"{row_id}: acceptance evidence required for {new_status}")
    return errors


def selected_rows(inv: dict, args: argparse.Namespace) -> list[dict]:
    features = index_rows(inv.get("features", []), "id")
    migrations = index_rows(inv.get("migrations", []), "id")
    if args.feature_id:
        if args.feature_id not in features:
            raise SystemExit(f"unknown feature: {args.feature_id}")
        return [features[args.feature_id]]
    if args.migration_id:
        if args.migration_id not in migrations:
            raise SystemExit(f"unknown migration: {args.migration_id}")
        migration = migrations[args.migration_id]
        return [{"id": migration["id"], "dependencies": migration.get("dependencies", []), "status": migration.get("status")}]
    if args.all:
        return list(features.values())
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Check async implementation dependency gates.")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--feature-id")
    parser.add_argument("--migration-id")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--mode", choices=["fixture", "runtime_integration", "calibration_debt_clearance", "autonomous_optimization_maturity"], default="runtime_integration")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print OK/BLOCKED rows but exit 0 for blocked rows. Validation errors still fail.",
    )
    args = parser.parse_args()

    inv = load_inventory(args.inventory)
    errors = validate_inventory(inv)
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 2

    features = index_rows(inv.get("features", []), "id")
    migrations = index_rows(inv.get("migrations", []), "id")
    combined = {**features, **migrations}
    ready = set(inv.get("ready_statuses", []))
    waivers = inv.get("waivers", [])

    rows = selected_rows(inv, args)
    if not rows:
        print("inventory valid")
        return 0

    failed = False
    for row in rows:
        failures = can_start(row, combined, ready, waivers, args.mode)
        if failures:
            failed = True
            print(f"BLOCKED {row['id']}: " + "; ".join(failures))
        else:
            print(f"OK {row['id']} mode={args.mode}")
    return 0 if args.report_only or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
