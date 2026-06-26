#!/usr/bin/env python3
"""ADS Decomposer-owned QDT entrypoint placeholder for runtime handoff execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_handoff import canonical_json


def _load(path: Path | None) -> dict:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = {
        "schema_version": "ads-decomposer-runtime-entrypoint/v1",
        "entrypoint": "run_decomposition.py",
        "runtime_owner": "ADS Decomposer",
        "status": "available",
        "handoff": _load(args.handoff),
        "authority": "qdt_generation_only_no_probability",
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
