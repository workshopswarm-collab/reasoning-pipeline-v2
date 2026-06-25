#!/usr/bin/env python3
"""Apply bounded AMRG anchor dependency repair to a QDT artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ads_decomposer.qdt import (  # noqa: E402
    QDTError,
    dump_question_decomposition,
    load_question_decomposition,
    repair_anchor_dependency_contracts,
)
from predquant.ads_handoff import canonical_json  # noqa: E402


def _load_json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QDTError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise QDTError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair missing AMRG anchor dependency contracts.")
    parser.add_argument("path", type=Path, help="question-decomposition/v1 JSON artifact")
    parser.add_argument(
        "--related-market-context",
        type=Path,
        help="Optional related-live-market-context artifact containing relationship_edges.",
    )
    parser.add_argument("--output", type=Path, help="Path for the repaired QDT artifact.")
    parser.add_argument("--max-anchor-repair-attempts", type=int, default=2)
    parser.add_argument("--max-anchor-repair-wall-clock-seconds", type=int, default=120)
    parser.add_argument(
        "--repair-exhaustion-policy",
        choices=["watch_only_if_forecastable", "fail_dispatch_preparation"],
        default="fail_dispatch_preparation",
    )
    args = parser.parse_args()

    qdt = load_question_decomposition(args.path)
    related_context = _load_json_object(args.related_market_context) if args.related_market_context else None
    result = repair_anchor_dependency_contracts(
        qdt,
        related_market_context=related_context,
        repair_policy={
            "max_anchor_repair_attempts": args.max_anchor_repair_attempts,
            "max_anchor_repair_wall_clock_seconds": args.max_anchor_repair_wall_clock_seconds,
            "repair_exhaustion_policy": args.repair_exhaustion_policy,
        },
    )
    summary = result["repair_summary"]
    if args.output:
        args.output.write_text(dump_question_decomposition(result["artifact"]), encoding="utf-8")
    print(canonical_json(summary))
    return 0 if summary["post_repair_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
