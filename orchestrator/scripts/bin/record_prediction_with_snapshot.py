#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import (
    DEFAULT_DB_PATH,
    load_json,
    record_prediction_with_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atomically record a market snapshot and pipeline prediction"
    )
    parser.add_argument("--file", default="-", help="Path to market payload JSON, or - for stdin")
    parser.add_argument("--probability", type=float, required=True, help="Pipeline yes probability")
    parser.add_argument("--source", default="pipeline", help="Prediction source name")
    parser.add_argument("--label", help="Optional prediction label/version")
    parser.add_argument("--predicted-at", help="Prediction timestamp; defaults to source fetch time")
    parser.add_argument("--market-probability", type=float, help="Override market yes probability")
    parser.add_argument(
        "--market-probability-method",
        help="Method used for the override, such as bid_ask_midpoint or yes_price",
    )
    parser.add_argument("--source-fetched-at", help="Timestamp when source market data was fetched")
    parser.add_argument("--source-payload-hash", help="Precomputed SHA-256 hash of source payload")
    parser.add_argument("--code-version", help="Pipeline code version or git commit")
    parser.add_argument("--model-name", help="Model name used for the prediction")
    parser.add_argument("--prompt-version", help="Prompt or strategy version used for the prediction")
    parser.add_argument("--input-hash", help="SHA-256 hash of the model or strategy input")
    parser.add_argument("--rationale", help="Optional prediction rationale")
    parser.add_argument("--metadata-json", default="{}", help="Optional JSON metadata")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = record_prediction_with_snapshot(
            db_path=Path(args.db_path),
            payload=load_json(args.file),
            predicted_probability=args.probability,
            prediction_source=args.source,
            prediction_label=args.label,
            predicted_at=args.predicted_at,
            market_probability=args.market_probability,
            market_probability_method=args.market_probability_method,
            source_fetched_at=args.source_fetched_at,
            source_payload_hash=args.source_payload_hash,
            code_version=args.code_version,
            model_name=args.model_name,
            prompt_version=args.prompt_version,
            input_hash=args.input_hash,
            rationale=args.rationale,
            metadata=json.loads(args.metadata_json),
        )
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
