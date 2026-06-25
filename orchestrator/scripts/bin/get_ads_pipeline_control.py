#!/usr/bin/env python3
"""Inspect the AUTO-006 durable ADS pipeline control switch."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_control import get_pipeline_control_state  # noqa: E402
from predquant.ads_pipeline_runner import PipelineRunnerContractError  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect durable ADS pipeline enablement state.")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument(
        "--no-create-default",
        action="store_true",
        help="Fail if the control row has not been initialized instead of creating the disabled default.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            control = get_pipeline_control_state(conn, create_default=not args.no_create_default)
        print(json.dumps(control, indent=2 if args.pretty else None, sort_keys=True))
        return 0
    except PipelineRunnerContractError as exc:
        print(json.dumps({"error": str(exc), "status": "contract_error"}, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
