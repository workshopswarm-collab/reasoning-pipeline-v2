#!/usr/bin/env python3
"""Persist SCAE forecast decision and optional market prediction bridge records."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scae.persistence import canonical_json, write_forecast_decision, write_scae_market_prediction


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist SCAE production forecast decision output.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--scae-ledger", required=True, type=Path)
    parser.add_argument("--decision-gate", required=True, type=Path)
    parser.add_argument("--ads-case-contract", type=Path)
    parser.add_argument("--fresh-snapshot-payload", type=Path)
    parser.add_argument("--metadata-json", default="{}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(args.metadata_json)
    scae_ledger = _load_json(args.scae_ledger)
    decision_gate = _load_json(args.decision_gate)
    if args.ads_case_contract:
        result = write_scae_market_prediction(
            args.db_path,
            scae_ledger,
            decision_gate,
            _load_json(args.ads_case_contract),
            fresh_snapshot_payload=(
                _load_json(args.fresh_snapshot_payload) if args.fresh_snapshot_payload else None
            ),
            metadata=metadata,
        )
    else:
        with sqlite3.connect(args.db_path) as conn:
            result = write_forecast_decision(
                conn,
                scae_ledger,
                decision_gate,
                metadata=metadata,
            )
            conn.commit()

    output = canonical_json(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
