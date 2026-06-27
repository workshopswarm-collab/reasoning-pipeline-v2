#!/usr/bin/env python3
"""Validate CLS sidecar JSON against a QDT artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.classification import (
    validate_researcher_sidecar_against_retrieval_packet,
    validate_researcher_sidecar_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--qdt", required=True, type=Path)
    parser.add_argument("--retrieval-packet", type=Path)
    args = parser.parse_args()
    sidecar = json.loads(args.sidecar.read_text(encoding="utf-8"))
    qdt = json.loads(args.qdt.read_text(encoding="utf-8"))
    if args.retrieval_packet:
        result = validate_researcher_sidecar_against_retrieval_packet(
            sidecar,
            qdt,
            json.loads(args.retrieval_packet.read_text(encoding="utf-8")),
        )
    else:
        result = validate_researcher_sidecar_v2(sidecar, qdt)
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
