#!/usr/bin/env python3
"""Build VER-002 evidence quality verification slices."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.verification import build_quality_verification_slices


def _result_payload(result) -> dict:
    return {
        "quality_verification_slices": result.quality_verification_slices,
        "quality_verification_digest": result.quality_verification_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification-matrix", required=True, type=Path)
    parser.add_argument("--retrieval-packet", type=Path)
    args = parser.parse_args()
    result = build_quality_verification_slices(
        json.loads(args.classification_matrix.read_text(encoding="utf-8")),
        retrieval_packet=json.loads(args.retrieval_packet.read_text(encoding="utf-8")) if args.retrieval_packet else None,
    )
    print(json.dumps(_result_payload(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
