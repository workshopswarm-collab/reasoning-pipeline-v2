#!/usr/bin/env python3
"""Set the AUTO-006 durable ADS pipeline enablement switch."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_control import (  # noqa: E402
    DEFAULT_DISABLE_ACTIONS,
    RUNNER_MODES,
    set_pipeline_enabled,
)
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
    parser = argparse.ArgumentParser(description="Durably enable or disable new ADS pipeline work.")
    parser.add_argument("state", choices=("enabled", "disabled"), help="Desired pipeline enablement state.")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--updated-by", default="manual", help="Operator or system actor recording the change.")
    parser.add_argument("--reason", required=True, help="Durable reason for the manual control change.")
    parser.add_argument("--runner-mode", choices=RUNNER_MODES, help="Desired runner mode to store with the control row.")
    parser.add_argument(
        "--default-disable-action",
        choices=DEFAULT_DISABLE_ACTIONS,
        help="Disable action metadata for later stop/drain implementations.",
    )
    parser.add_argument("--acknowledged-by-run-id", help="Optional runner acknowledgement id to store.")
    parser.add_argument("--metadata-json", type=parse_metadata, help="Optional JSON object to store as safe metadata.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            control = set_pipeline_enabled(
                conn,
                pipeline_enabled=args.state == "enabled",
                updated_by=args.updated_by,
                reason=args.reason,
                desired_runner_mode=args.runner_mode,
                default_disable_action=args.default_disable_action,
                acknowledged_by_run_id=args.acknowledged_by_run_id,
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
