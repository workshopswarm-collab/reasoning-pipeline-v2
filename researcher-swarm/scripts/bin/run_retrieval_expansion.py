#!/usr/bin/env python3
"""Build retrieval expansion/fallback plan records from a retrieval packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.retrieval import build_retrieval_expansion_and_fallback_plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-packet", required=True, type=Path)
    args = parser.parse_args()
    packet = json.loads(args.retrieval_packet.read_text(encoding="utf-8"))
    print(json.dumps(build_retrieval_expansion_and_fallback_plan(packet), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
