#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import DEFAULT_DB_PATH, settle_market_outcome


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Settle a market and score predictions")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--market-id", type=int, help="Internal SQLite market id")
    target.add_argument("--external-market-id", help="External platform market id")
    parser.add_argument("--platform", default="polymarket", help="Market platform")
    parser.add_argument("--outcome", type=float, required=True, help="Final outcome, usually 0 or 1")
    parser.add_argument("--resolved-at", help="Resolution timestamp; defaults to now")
    parser.add_argument("--source", default="manual", help="Resolution source")
    parser.add_argument("--resolution-method", help="Method used to determine the final outcome")
    parser.add_argument("--resolution-payload-file", help="Optional JSON source payload file")
    parser.add_argument("--resolution-payload-hash", help="Optional precomputed source payload hash")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        resolution_payload = None
        if args.resolution_payload_file:
            resolution_payload = json.loads(Path(args.resolution_payload_file).read_text())
        result = settle_market_outcome(
            db_path=Path(args.db_path),
            market_id=args.market_id,
            platform=args.platform,
            external_market_id=args.external_market_id,
            outcome=args.outcome,
            resolved_at=args.resolved_at,
            resolution_source=args.source,
            resolution_payload=resolution_payload,
            resolution_payload_hash=args.resolution_payload_hash,
            resolution_method=args.resolution_method,
        )
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
