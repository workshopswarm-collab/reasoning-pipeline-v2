#!/usr/bin/env python3
"""Build VER-001 evidence direction verification slices."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.verification import build_direction_verification_slices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification-matrix", required=True, type=Path)
    parser.add_argument("--qdt", type=Path)
    args = parser.parse_args()
    result = build_direction_verification_slices(
        json.loads(args.classification_matrix.read_text(encoding="utf-8")),
        qdt=json.loads(args.qdt.read_text(encoding="utf-8")) if args.qdt else None,
    )
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
