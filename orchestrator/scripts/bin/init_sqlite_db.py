#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import DEFAULT_DB_PATH, initialize_database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize the local SQLite database")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    initialize_database(db_path)
    print(f"Initialized SQLite database at {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
