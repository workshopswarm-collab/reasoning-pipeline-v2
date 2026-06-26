#!/usr/bin/env python3
"""Record a RET-010 native research attempt or unavailable diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.native_research import build_native_research_transport_diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default="unavailable")
    parser.add_argument("--unavailable-reason", default="native_research_not_invoked")
    args = parser.parse_args()
    payload = build_native_research_transport_diagnostic(
        availability_status=args.status,
        unavailable_reason=args.unavailable_reason,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
