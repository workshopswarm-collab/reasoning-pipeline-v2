#!/usr/bin/env python3
"""Check ADS v2 runtime script placement against the canonical map."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

from predquant.script_placement import (  # noqa: E402
    DEFAULT_SCRIPT_PLACEMENT_MAP,
    ScriptPlacementError,
    build_script_placement_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ADS runtime script placement against the canonical placement map.")
    parser.add_argument("--map", type=Path, default=DEFAULT_SCRIPT_PLACEMENT_MAP, help="Script placement map Markdown file.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Return exit code 0 even when the scan finds missing or misplaced planned paths.",
    )
    parser.add_argument(
        "--skip-existence-check",
        action="store_true",
        help="Only validate ownership/duplicates; do not require planned paths to exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build_script_placement_report(
            map_path=args.map,
            require_existing_paths=not args.skip_existence_check,
        )
    except ScriptPlacementError as exc:
        report = {
            "schema_version": "ads-script-placement-scan/v1",
            "fixture_id": "FIX-039",
            "blocker_id": "BLK-032",
            "status": "failed",
            "error": str(exc),
        }
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    if args.report_only:
        return 0
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
