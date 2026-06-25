#!/usr/bin/env python3
"""Run ADS v2 golden fixture harness cases."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

from predquant.golden_fixtures import (  # noqa: E402
    DEFAULT_INVENTORY_PATH,
    DEFAULT_MATRIX_PATH,
    STARTER_FIXTURE_IDS,
    build_fixture_registry,
    result_report_payload,
    run_fixture_case,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ADS v2 golden fixture cases.")
    parser.add_argument("--fixture-id", action="append", help="Fixture ID to run. Repeatable.")
    parser.add_argument("--all-starter", action="store_true", help="Run the starter Wave B fixtures FIX-001 through FIX-007.")
    parser.add_argument("--db", type=Path, default=SCRIPT_ROOT / ".runtime-state" / "golden-fixtures.sqlite3")
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_ROOT / ".runtime-state" / "golden-fixtures")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--dependency-mode", choices=["fixture", "runtime_integration"], default="fixture")
    parser.add_argument("--run-id")
    parser.add_argument("--stage", help="Replay metadata only; accepted so replay commands have stable argv.")
    args = parser.parse_args()

    registry = build_fixture_registry(args.matrix)
    fixture_ids = args.fixture_id or []
    if args.all_starter:
        fixture_ids.extend(sorted(STARTER_FIXTURE_IDS))
    if not fixture_ids:
        print(json.dumps({"registered_fixture_count": len(registry), "starter_fixture_ids": sorted(STARTER_FIXTURE_IDS)}, sort_keys=True))
        return 0

    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    conn = sqlite3.connect(args.db)
    try:
        for fixture_id in fixture_ids:
            result = run_fixture_case(
                fixture_id,
                conn=conn,
                output_dir=args.output_dir / fixture_id,
                matrix_path=args.matrix,
                inventory_path=args.inventory,
                dependency_mode=args.dependency_mode,
                run_id=args.run_id,
            )
            outputs.append(result_report_payload(result))
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"results": outputs}, sort_keys=True, indent=2))
    return 0 if all(item["status"] == "passed" for item in outputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
