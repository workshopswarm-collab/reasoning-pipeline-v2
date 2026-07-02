#!/usr/bin/env python3
"""Report ADS live-market E2E Phase 8 clone-batch closure status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_live_market_e2e_phase8_closure import (  # noqa: E402
    DEFAULT_REQUIRED_REPRESENTATIVE_TAGS,
    build_live_market_e2e_phase8_closure_report,
    load_phase8_case_spec,
)


def _load_json(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object: {path}")
    return loaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-report",
        action="append",
        type=Path,
        default=[],
        help=(
            "JSON real-runtime report or wrapper object containing "
            "real_runtime_report/report, selector, expected_classification, "
            "expected_market_predictions_delta, and representative_tags. Repeat once per case."
        ),
    )
    parser.add_argument(
        "--cleanup-proof-json",
        type=Path,
        required=True,
        help="Path to ads-live-market-e2e-phase8-cleanup-proof/v1-compatible JSON.",
    )
    parser.add_argument(
        "--required-tag",
        action="append",
        default=None,
        help="Required representative tag. Defaults to the live-market E2E Phase 8 plan tags.",
    )
    parser.add_argument("--min-case-count", type=int, default=4)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required_tags = tuple(args.required_tag) if args.required_tag else DEFAULT_REQUIRED_REPRESENTATIVE_TAGS
    case_specs = [load_phase8_case_spec(path) for path in args.case_report]
    report = build_live_market_e2e_phase8_closure_report(
        case_specs,
        cleanup_proof=_load_json(args.cleanup_proof_json),
        required_representative_tags=required_tags,
        min_case_count=args.min_case_count,
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
