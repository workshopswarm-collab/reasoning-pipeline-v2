#!/usr/bin/env python3
"""Run the AUTO-001 non-executing ADS pipeline runner skeleton."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_pipeline_runner import (  # noqa: E402
    DEFAULT_DEPENDENCY_GATE_MODE,
    DEFAULT_RUNNER_MODE,
    DEPENDENCY_GATE_MODES,
    RUNNER_MODES,
    PipelineRunnerContractError,
    PipelineRunnerPolicy,
    run_ads_pipeline_loop,
)
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AUTO-001 ADS pipeline runner skeleton. It never selects cases or executes stages."
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--runner-mode", choices=RUNNER_MODES, default=DEFAULT_RUNNER_MODE)
    parser.add_argument(
        "--dependency-gate-mode",
        choices=DEPENDENCY_GATE_MODES,
        default=DEFAULT_DEPENDENCY_GATE_MODE,
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            result = run_ads_pipeline_loop(
                conn,
                PipelineRunnerPolicy(
                    runner_mode=args.runner_mode,
                    dependency_gate_mode=args.dependency_gate_mode,
                ),
            )
        print(json.dumps(result.to_record(), indent=2 if args.pretty else None, sort_keys=True))
        return 0
    except PipelineRunnerContractError as exc:
        print(json.dumps({"error": str(exc), "status": "contract_error"}, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
