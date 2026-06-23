#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import DEFAULT_DB_PATH, cleanup_expired_markets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark expired markets closed in SQLite")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument(
        "--grace-minutes",
        type=int,
        default=0,
        help="Minutes to wait after close/resolve time before marking a market closed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be marked closed without modifying the database.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = cleanup_expired_markets(
        db_path=Path(args.db_path),
        grace_minutes=args.grace_minutes,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        for message in result["messages"]:
            print(message)
        print(f"Expired markets found: {result['expired']}")
    else:
        print(f"Marked expired markets closed: {result['marked_closed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
