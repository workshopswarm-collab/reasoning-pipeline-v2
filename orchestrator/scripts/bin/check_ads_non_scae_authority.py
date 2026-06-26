#!/usr/bin/env python3
"""Check ADS v2 non-SCAE probability authority boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_ROOT))

from predquant.canonical_artifacts import build_non_scae_probability_authority_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check non-SCAE probability authority boundaries.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Return exit code 0 even when the scan fails.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_non_scae_probability_authority_report()
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    if args.report_only:
        return 0
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
