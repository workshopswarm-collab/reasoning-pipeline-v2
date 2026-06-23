#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.polymarket_resolution import (
    DEFAULT_TERMINAL_TOLERANCE,
    sync_polymarket_resolutions,
)
from predquant.sqlite_store import DEFAULT_DB_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync final Polymarket resolutions and score settled predictions"
    )
    parser.add_argument("--limit", type=int, help="Maximum closed markets to check")
    parser.add_argument(
        "--terminal-tolerance",
        type=float,
        default=DEFAULT_TERMINAL_TOLERANCE,
        help="Tolerance for terminal 0/1/0.5 outcome prices.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Check without writing updates")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = sync_polymarket_resolutions(
            db_path=Path(args.db_path),
            limit=args.limit,
            terminal_tolerance=args.terminal_tolerance,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
