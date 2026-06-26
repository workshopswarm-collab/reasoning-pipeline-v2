#!/usr/bin/env python3
"""Run one bounded ADS operational scheduler iteration."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_operational_canary import (  # noqa: E402
    OperationalCanaryConfig,
    build_handlers_from_factory,
    build_operational_case_selection_policy,
    load_handler_factory,
)
from predquant.ads_live_readiness import build_live_readiness_report  # noqa: E402
from predquant.ads_pipeline_control import set_pipeline_enabled  # noqa: E402
from predquant.ads_pipeline_runner import (  # noqa: E402
    RUNNER_MODES,
    PipelineRunnerContractError,
    PipelineRunnerPolicy,
    run_ads_pipeline_loop,
)
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_metadata(value: str | None) -> dict:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--metadata-json must decode to an object")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument("--runner-mode", choices=RUNNER_MODES, default="non_executing_canary")
    parser.add_argument("--handler-factory", help="Dotted module/path plus optional :factory for downstream stage handlers.")
    parser.add_argument("--forecast-timestamp", help="Forecast timestamp passed to handler factory/case policy.")
    parser.add_argument("--max-cases", type=int, default=1, help="Maximum cases for this bounded scheduler run.")
    parser.add_argument("--retry-backoff-seconds", type=int, default=60)
    parser.add_argument("--require-manifest-handoffs", action="store_true")
    parser.add_argument(
        "--skip-existing-ads-predictions",
        action="store_true",
        help="Skip markets that already have ads_pipeline/v2_scae market_predictions rows.",
    )
    parser.add_argument("--enable-for-run", action="store_true", help="Enable pipeline control before running.")
    parser.add_argument("--disable-after-run", action="store_true", help="Disable pipeline control after running.")
    parser.add_argument(
        "--require-live-readiness",
        action="store_true",
        help="Refuse to run unless the ADS live-readiness gate passes.",
    )
    parser.add_argument(
        "--require-scoreable-live",
        action="store_true",
        help="Require calibration-debt clearance and a scoreable-capable handler in the live-readiness gate.",
    )
    parser.add_argument(
        "--allow-canary-handler",
        action="store_true",
        help="Allow scoreable/manifest canary handlers to pass the live-readiness handler policy check.",
    )
    parser.add_argument("--updated-by", default="ads-operational-scheduler")
    parser.add_argument("--reason", default="bounded ADS operational scheduler run")
    parser.add_argument("--metadata-json", type=parse_metadata)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    metadata = args.metadata_json or {}
    handlers = None
    if args.handler_factory:
        config = OperationalCanaryConfig(
            db_path=db_path,
            runner_mode=args.runner_mode,
            forecast_timestamp=args.forecast_timestamp,
            max_cases=args.max_cases,
            retry_backoff_seconds=args.retry_backoff_seconds,
            updated_by=args.updated_by,
            reason=args.reason,
            require_manifest_handoffs=args.require_manifest_handoffs,
            skip_existing_ads_predictions=args.skip_existing_ads_predictions,
            metadata=metadata,
        )
        handlers = build_handlers_from_factory(load_handler_factory(args.handler_factory), config)
    else:
        config = OperationalCanaryConfig(
            db_path=db_path,
            runner_mode=args.runner_mode,
            forecast_timestamp=args.forecast_timestamp,
            max_cases=args.max_cases,
            retry_backoff_seconds=args.retry_backoff_seconds,
            updated_by=args.updated_by,
            reason=args.reason,
            require_manifest_handoffs=args.require_manifest_handoffs,
            skip_existing_ads_predictions=args.skip_existing_ads_predictions,
            metadata=metadata,
        )

    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        readiness = None
        if args.require_live_readiness:
            readiness = build_live_readiness_report(
                db_path,
                handler_factory=args.handler_factory,
                runner_mode=args.runner_mode,
                require_scoreable_live=args.require_scoreable_live,
                allow_canary_handler=args.allow_canary_handler,
            )
            if not readiness["ok"]:
                record = {
                    "ok": False,
                    "status": "live_readiness_blocked",
                    "live_readiness_report": readiness,
                }
                print(json.dumps(record, indent=2 if args.pretty else None, sort_keys=True))
                return 2
        if args.enable_for_run:
            set_pipeline_enabled(
                conn,
                pipeline_enabled=True,
                desired_runner_mode=args.runner_mode,
                updated_by=args.updated_by,
                reason=args.reason,
                default_disable_action="stop_after_current_case",
                metadata={"purpose": "bounded_scheduler_enable", **metadata},
            )
        result = run_ads_pipeline_loop(
            conn,
            PipelineRunnerPolicy(
                runner_mode=args.runner_mode,
                max_cases=args.max_cases,
                stop_policy="none",
                dependency_gate_mode="calibration_debt_clearance",
                allow_downstream_execution=bool(handlers),
                allow_forecast_persistence=bool(handlers),
                retry_backoff_seconds=args.retry_backoff_seconds,
                require_manifest_handoffs=args.require_manifest_handoffs,
            ),
            downstream_stage_handlers=handlers,
            case_selection_policy=build_operational_case_selection_policy(config),
        )
        record = result.to_record()
        if readiness is not None:
            record["live_readiness_report"] = readiness
        if args.disable_after_run:
            record["control_after_disable"] = set_pipeline_enabled(
                conn,
                pipeline_enabled=False,
                desired_runner_mode=args.runner_mode,
                updated_by=args.updated_by,
                reason="bounded ADS operational scheduler run disabled after completion",
                default_disable_action="no_new_leases",
                metadata={"purpose": "bounded_scheduler_disable", **metadata},
            )
    except PipelineRunnerContractError as exc:
        record = {"ok": False, "status": "contract_error", "error": str(exc)}
    finally:
        conn.close()
    print(json.dumps(record, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if record.get("ok", True) is not False else 2


if __name__ == "__main__":
    raise SystemExit(main())
