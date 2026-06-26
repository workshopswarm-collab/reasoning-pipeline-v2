#!/usr/bin/env python3
"""Researcher Swarm stage entrypoint for validated assignment artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.subagents import build_leaf_research_barrier, build_leaf_researcher_spawn_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignments", type=Path, help="Leaf assignment bundle JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assignments = []
    if args.assignments:
        assignments = json.loads(args.assignments.read_text(encoding="utf-8"))
        if isinstance(assignments, dict):
            assignments = assignments.get("assignments", [])
    spawn_plan = build_leaf_researcher_spawn_plan(assignments) if isinstance(assignments, list) and assignments else None
    barrier = build_leaf_research_barrier(assignments) if isinstance(assignments, list) and assignments else None
    payload = {
        "schema_version": "researcher-swarm-run-plan/v1",
        "runtime_owner": "ADS Researcher Swarm",
        "status": "planned",
        "assignment_count": len(assignments) if isinstance(assignments, list) else 0,
        "live_spawn_authority": False,
        "spawn_plan": spawn_plan,
        "leaf_research_barrier": barrier,
    }
    text = json.dumps(payload, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
