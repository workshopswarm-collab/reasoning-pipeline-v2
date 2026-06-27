#!/usr/bin/env python3
"""Print an AMRG operator report for a related-market context artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.amrg import build_amrg_operator_report, canonical_json  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an AMRG operator report.")
    parser.add_argument("related_market_context", type=Path)
    parser.add_argument("--question-decomposition", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    context = json.loads(args.related_market_context.read_text(encoding="utf-8"))
    qdt = (
        json.loads(args.question_decomposition.read_text(encoding="utf-8"))
        if args.question_decomposition
        else None
    )
    report = build_amrg_operator_report(context, question_decomposition=qdt)
    if args.pretty:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
