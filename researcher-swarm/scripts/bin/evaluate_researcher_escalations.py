#!/usr/bin/env python3
"""Evaluate CLS-007 adaptive researcher escalation for one leaf packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.escalation import evaluate_researcher_escalation


def _load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leaf", required=True, type=Path)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--classifications", required=True, type=Path)
    parser.add_argument("--base-assignment", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_researcher_escalation(
        leaf=_load(args.leaf),
        certificate=_load(args.certificate),
        classifications=_load(args.classifications),
        base_assignment=_load(args.base_assignment),
    )
    text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
