#!/usr/bin/env python3
"""Report ADS Phase 9 representative clone-batch status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_phase9_representative_batch import (  # noqa: E402
    DEFAULT_MAX_RETRY_ATTEMPTS_PER_CASE,
    DEFAULT_MAX_RETRY_BACKOFF_SECONDS,
    DEFAULT_REQUIRED_REPRESENTATIVE_TAGS,
    build_phase9_representative_batch_report,
    load_phase9_case_spec,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-report",
        action="append",
        type=Path,
        default=[],
        help=(
            "JSON real-runtime report or wrapper object containing "
            "real_runtime_report/report, selector, and representative_tags. Repeat once per case."
        ),
    )
    parser.add_argument(
        "--required-tag",
        action="append",
        default=None,
        help="Required representative tag. Defaults to the Phase 9 plan tags.",
    )
    parser.add_argument("--min-case-count", type=int, default=4)
    parser.add_argument("--max-retry-attempts-per-case", type=int, default=DEFAULT_MAX_RETRY_ATTEMPTS_PER_CASE)
    parser.add_argument("--max-retry-backoff-seconds", type=int, default=DEFAULT_MAX_RETRY_BACKOFF_SECONDS)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required_tags = tuple(args.required_tag) if args.required_tag else DEFAULT_REQUIRED_REPRESENTATIVE_TAGS
    case_specs = [load_phase9_case_spec(path) for path in args.case_report]
    report = build_phase9_representative_batch_report(
        case_specs,
        required_representative_tags=required_tags,
        min_case_count=args.min_case_count,
        max_retry_attempts_per_case=args.max_retry_attempts_per_case,
        max_retry_backoff_seconds=args.max_retry_backoff_seconds,
    )
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
