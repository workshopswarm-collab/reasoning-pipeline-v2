#!/usr/bin/env python3
"""Build CLS-006 compact leaf research assignments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.assignments import build_leaf_research_assignments


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdt", required=True, type=Path)
    parser.add_argument("--retrieval-packet", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    assignments = build_leaf_research_assignments(qdt=_load(args.qdt), retrieval_packet=_load(args.retrieval_packet))
    text = json.dumps({"assignments": assignments}, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
