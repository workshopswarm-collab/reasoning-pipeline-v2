#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.pipeline import push_filtered_markets

DEFAULT_INPUT_JSON_FILE = Path("filtered_markets.json")
DEFAULT_DB_PATH = Path("data/predquant.sqlite3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push filtered market payloads to SQLite")
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_JSON_FILE),
        help="Path to filtered markets JSON produced by fetch_polymarket_markets.py",
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_json_file = Path(args.input)
    db_path = Path(args.db_path)
    try:
        result = push_filtered_markets(input_json_file, db_path)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Loaded {result['loaded']} markets. Pushing to SQLite at {db_path}...")
    for message in result["messages"]:
        print(message)
    print(
        "Finished pushing to SQLite! "
        f"Success: {result['success']}, Errors: {result['errors']}"
    )
    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
