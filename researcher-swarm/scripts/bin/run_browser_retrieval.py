#!/usr/bin/env python3
"""Record a browser retrieval provider diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.browser_provider import OPENCLAW_BROWSER_PROVIDER_ID, build_browser_search_provider_diagnostic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--available", action="store_true")
    parser.add_argument("--unavailable-reason", default="browser_provider_not_invoked")
    args = parser.parse_args()
    payload = build_browser_search_provider_diagnostic(
        availability_status="available" if args.available else "unavailable",
        unavailable_reason=None if args.available else args.unavailable_reason,
    )
    payload["provider_id"] = OPENCLAW_BROWSER_PROVIDER_ID
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
