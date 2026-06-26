#!/usr/bin/env python3
"""Build a control-plane-only leaf researcher spawn plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.subagents import build_leaf_researcher_spawn_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignments", required=True, type=Path)
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.assignments.read_text(encoding="utf-8"))
    assignments = payload.get("assignments", payload) if isinstance(payload, dict) else payload
    plan = build_leaf_researcher_spawn_plan(assignments, max_concurrent=args.max_concurrent)
    text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
