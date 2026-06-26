#!/usr/bin/env python3
"""Validate SCAE ledger persistence authority fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.persistence import ScaePersistenceError, validate_scae_ledger_for_persistence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    try:
        validate_scae_ledger_for_persistence(ledger)
    except ScaePersistenceError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"valid": True, "schema_version": "scae-ledger-validation-result/v1"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
