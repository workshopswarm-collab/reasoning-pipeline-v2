#!/usr/bin/env python3
"""Validate RET-009 breadth coverage slices from a retrieval packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.breadth import build_retrieval_breadth_coverage_slices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-packet", required=True, type=Path)
    args = parser.parse_args()
    packet = json.loads(args.retrieval_packet.read_text(encoding="utf-8"))
    print(json.dumps({"retrieval_breadth_coverage_slices": build_retrieval_breadth_coverage_slices(packet)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
