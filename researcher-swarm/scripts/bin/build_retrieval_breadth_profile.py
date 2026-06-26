#!/usr/bin/env python3
"""Build RET-009 placeholder breadth profiles from QDT leaves."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.breadth import build_retrieval_breadth_profile_placeholder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdt", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    qdt = json.loads(args.qdt.read_text(encoding="utf-8"))
    profiles = [build_retrieval_breadth_profile_placeholder(leaf) for leaf in qdt.get("required_leaf_questions", [])]
    text = json.dumps({"retrieval_breadth_profiles": profiles}, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
