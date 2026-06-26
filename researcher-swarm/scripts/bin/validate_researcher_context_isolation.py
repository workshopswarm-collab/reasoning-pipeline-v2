#!/usr/bin/env python3
"""Validate CLS-008 researcher context isolation request/audit JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from researcher_swarm.isolation import (
    validate_researcher_context_isolation_audit,
    validate_researcher_context_isolation_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    result = (
        validate_researcher_context_isolation_audit(payload)
        if args.audit
        else validate_researcher_context_isolation_request(payload)
    )
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
