#!/usr/bin/env python3
"""SCAE-owned deterministic ledger entrypoint placeholder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.persistence import canonical_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scae-readiness", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    readiness = {}
    if args.scae_readiness:
        readiness = json.loads(args.scae_readiness.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "scae-ledger-run-plan/v1",
        "runtime_owner": "SCAE",
        "status": "available",
        "input_readiness_ref": readiness.get("readiness_reconciliation_id") if isinstance(readiness, dict) else None,
        "authority": "deterministic_scae_ledger_only",
    }
    text = canonical_json(payload) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
