#!/usr/bin/env python3
"""Request an AUTO-004 ADS pipeline stop or drain through durable control state."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_control import STOP_SIGNAL_POLICIES, request_pipeline_stop  # noqa: E402
from predquant.ads_pipeline_runner import PipelineRunnerContractError  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_metadata(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--metadata-json must decode to a JSON object")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Request a durable ADS pipeline stop or drain.")
    parser.add_argument("stop_policy", choices=STOP_SIGNAL_POLICIES)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--requested-by", default="manual", help="Operator or system actor requesting the stop.")
    parser.add_argument("--reason", required=True, help="Durable reason for the stop request.")
    parser.add_argument("--pipeline-run-id", help="Optional active runner id this request targets.")
    parser.add_argument("--metadata-json", type=parse_metadata, help="Optional JSON object to store on the stop signal.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            control = request_pipeline_stop(
                conn,
                stop_policy=args.stop_policy,
                requested_by=args.requested_by,
                reason=args.reason,
                pipeline_run_id=args.pipeline_run_id,
                metadata=args.metadata_json,
            )
        print(json.dumps(control, indent=2 if args.pretty else None, sort_keys=True))
        return 0
    except PipelineRunnerContractError as exc:
        print(json.dumps({"error": str(exc), "status": "contract_error"}, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
