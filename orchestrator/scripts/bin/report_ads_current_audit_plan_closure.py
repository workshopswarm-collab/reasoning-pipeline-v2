#!/usr/bin/env python3
"""Report ADS current-audit remediation plan closure status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_current_audit_plan_closure import (  # noqa: E402
    build_current_audit_plan_closure_report,
    load_current_audit_plan_phase_statuses,
)


def _load_json(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object: {path}")
    return loaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-path",
        type=Path,
        required=True,
        help="Path to ads-v2-current-audit-issue-remediation-plan.md.",
    )
    parser.add_argument(
        "--phase9-report-json",
        type=Path,
        required=True,
        help="Path to ads-phase9-representative-batch/v1 report JSON.",
    )
    parser.add_argument(
        "--live-readiness-report-json",
        type=Path,
        required=True,
        help="Path to ads-live-readiness-report/v1 report JSON.",
    )
    parser.add_argument(
        "--live-mutation-authorized",
        action="store_true",
        help="Set only after VM explicitly authorizes live DB mutation/cutover work.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_current_audit_plan_closure_report(
        phase_statuses=load_current_audit_plan_phase_statuses(args.plan_path),
        phase9_report=_load_json(args.phase9_report_json),
        live_readiness_report=_load_json(args.live_readiness_report_json),
        live_mutation_authorized=args.live_mutation_authorized,
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
