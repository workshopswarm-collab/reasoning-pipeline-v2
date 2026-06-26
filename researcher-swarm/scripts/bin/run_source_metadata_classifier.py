#!/usr/bin/env python3
"""Record a RET-011 classifier unavailable diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.metadata_classifier import build_source_metadata_classifier_unavailable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unavailable-reason", default="classifier_not_invoked")
    args = parser.parse_args()
    payload = build_source_metadata_classifier_unavailable(
        unavailable_reason=args.unavailable_reason,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
