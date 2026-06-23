#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import DEFAULT_DB_PATH, brier_score_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report pipeline Brier scores against prediction-time market baselines"
    )
    parser.add_argument("--source", help="Optional prediction_source filter")
    parser.add_argument("--label", help="Optional prediction_label filter")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = brier_score_report(
            db_path=Path(args.db_path),
            prediction_source=args.source,
            prediction_label=args.label,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
