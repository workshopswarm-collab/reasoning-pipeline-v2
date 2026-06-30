#!/usr/bin/env python3
"""Run a bounded ADS operational canary."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.ads_operational_canary import (  # noqa: E402
    OperationalCanaryConfig,
    build_handlers_from_factory,
    load_handler_factory,
    run_one_case_canary,
    validate_preflight,
)
from predquant.ads_pipeline_runner import RUNNER_MODES, PipelineRunnerContractError  # noqa: E402
from predquant.ads_retrieval_transport import RetrievalProviderPolicy  # noqa: E402
from predquant.sqlite_store import DEFAULT_DB_PATH  # noqa: E402


def parse_metadata(value: str | None) -> dict:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--metadata-json must decode to a JSON object")
    return parsed


def parse_retrieval_provider_policy(value: str | None) -> RetrievalProviderPolicy | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--retrieval-provider-policy-json must decode to a JSON object")
    try:
        return RetrievalProviderPolicy(**parsed)
    except TypeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def load_object(spec: str, *, default_attr: str):
    module_ref, _, attr = spec.partition(":")
    if not module_ref:
        raise argparse.ArgumentTypeError("object module is required")
    attr = attr or default_attr
    if module_ref.endswith(".py") or "/" in module_ref:
        path = Path(module_ref).expanduser().resolve()
        module_spec = importlib.util.spec_from_file_location(path.stem, path)
        if module_spec is None or module_spec.loader is None:
            raise argparse.ArgumentTypeError(f"cannot load object module: {path}")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    else:
        module = importlib.import_module(module_ref)
    loaded = getattr(module, attr, None)
    if not callable(loaded):
        raise argparse.ArgumentTypeError(f"object is not callable: {spec}")
    return loaded


def build_handler_factory_kwargs(args: argparse.Namespace) -> dict:
    kwargs = {}
    if getattr(args, "decomposer_runtime_mode", None):
        kwargs["decomposer_runtime_mode"] = args.decomposer_runtime_mode
    if args.decomposer_runtime_transport_response is not None:
        kwargs["decomposer_runtime_transport_response_path"] = args.decomposer_runtime_transport_response
    if args.researcher_swarm_runtime_bundle_response is not None:
        kwargs["researcher_swarm_runtime_bundle_response_path"] = args.researcher_swarm_runtime_bundle_response
    if getattr(args, "retrieval_browser_provider_factory", None):
        kwargs["retrieval_browser_provider"] = load_object(
            args.retrieval_browser_provider_factory,
            default_attr="build_provider",
        )()
    if getattr(args, "native_candidate_provider_factory", None):
        kwargs["native_candidate_provider"] = load_object(
            args.native_candidate_provider_factory,
            default_attr="build_native_candidate_provider",
        )()
    if getattr(args, "researcher_swarm_runtime_runner", None):
        kwargs["researcher_swarm_runtime_runner"] = load_object(
            args.researcher_swarm_runtime_runner,
            default_attr="run_researcher_swarm_runtime",
        )
    if getattr(args, "retrieval_provider_policy_json", None) is not None:
        kwargs["retrieval_provider_policy"] = args.retrieval_provider_policy_json
    return kwargs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path. Defaults to PREDQUANT_SQLITE_PATH or data/predquant.sqlite3.",
    )
    parser.add_argument(
        "--runner-mode",
        choices=RUNNER_MODES,
        default="fixture",
        help="Runner mode to store in control state. Use calibration_debt_production only for an explicit live canary.",
    )
    parser.add_argument("--forecast-timestamp", help="Optional forecast timestamp for deterministic case selection.")
    parser.add_argument(
        "--max-cases",
        type=int,
        default=1,
        help="Bounded case count. Use 1 for the stop-after-current canary, 2+ for a small batch canary.",
    )
    parser.add_argument("--lease-duration-seconds", type=int, default=900)
    parser.add_argument("--retry-backoff-seconds", type=int, default=60)
    parser.add_argument("--updated-by", default="manual")
    parser.add_argument("--reason", default="one-case ADS operational canary")
    parser.add_argument(
        "--handler-factory",
        help="Dotted module or .py path plus optional :factory. Factory must return ADS stage handlers.",
    )
    parser.add_argument(
        "--decomposer-runtime-transport-response",
        type=Path,
        help="Optional model-runtime transport response JSON passed to production handler factories.",
    )
    parser.add_argument(
        "--decomposer-runtime-mode",
        choices=["fixture", "live"],
        help="Optional Decomposer runtime mode passed to production handler factories.",
    )
    parser.add_argument(
        "--researcher-swarm-runtime-bundle-response",
        type=Path,
        help="Optional researcher-swarm-runtime-bundle JSON passed to production handler factories.",
    )
    parser.add_argument(
        "--retrieval-browser-provider-factory",
        help=(
            "Dotted module/path plus optional :factory returning a browser/search provider object. "
            "The provider is passed to retrieval_browser_provider and remains URL/search transport only."
        ),
    )
    parser.add_argument(
        "--native-candidate-provider-factory",
        help=(
            "Dotted module/path plus optional :factory returning a native candidate provider. "
            "The provider is passed to native_candidate_provider and may only propose candidate URLs."
        ),
    )
    parser.add_argument(
        "--researcher-swarm-runtime-runner",
        help=(
            "Dotted module/path plus optional :callable for a researcher runtime runner. "
            "The callable receives bounded certified evidence assignments and returns a runtime bundle."
        ),
    )
    parser.add_argument(
        "--retrieval-provider-policy-json",
        type=parse_retrieval_provider_policy,
        help="JSON object used to construct predquant.ads_retrieval_transport.RetrievalProviderPolicy.",
    )
    parser.add_argument(
        "--allow-non-scoreable",
        action="store_true",
        help="Do not require exactly one forecast_decision_records row and one market_predictions row.",
    )
    parser.add_argument(
        "--require-manifest-handoffs",
        action="store_true",
        help="Require every downstream stage output ref to resolve to a persisted artifact manifest.",
    )
    parser.add_argument(
        "--require-real-runtime-canary-criteria",
        action="store_true",
        help="Fail unless ads-real-runtime-canary-criteria/v1 passes after the run.",
    )
    parser.add_argument(
        "--skip-qdt-model-executed-check",
        action="store_true",
        help="Do not require live GPT 5.5 High QDT runtime evidence in the real-runtime criteria report.",
    )
    parser.add_argument(
        "--require-researcher-model-executed",
        action="store_true",
        help="Require model-executed GPT 5.5 High researcher sidecars/runtime bundles in the criteria report.",
    )
    parser.add_argument(
        "--allow-stage-failure-class",
        action="append",
        default=[],
        help="Expected failure class permitted by the criteria report for failure-injection runs.",
    )
    parser.add_argument(
        "--skip-existing-ads-predictions",
        action="store_true",
        help="Skip markets that already have ads_pipeline/v2_scae market_predictions rows.",
    )
    parser.add_argument("--metadata-json", type=parse_metadata)
    parser.add_argument("--preflight-only", action="store_true", help="Validate handler coverage and active-work state only.")
    parser.add_argument("--apply", action="store_true", help="Actually enable and run the one-case canary.")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    handler_factory_kwargs = build_handler_factory_kwargs(args)
    config = OperationalCanaryConfig(
        db_path=Path(args.db_path),
        runner_mode=args.runner_mode,
        forecast_timestamp=args.forecast_timestamp,
        max_cases=args.max_cases,
        lease_duration_seconds=args.lease_duration_seconds,
        retry_backoff_seconds=args.retry_backoff_seconds,
        updated_by=args.updated_by,
        reason=args.reason,
        require_scoreable_prediction=not args.allow_non_scoreable,
        require_manifest_handoffs=args.require_manifest_handoffs,
        skip_existing_ads_predictions=args.skip_existing_ads_predictions,
        metadata=args.metadata_json or {},
        handler_factory_kwargs=handler_factory_kwargs,
        require_real_runtime_canary_criteria=args.require_real_runtime_canary_criteria,
        require_qdt_model_executed=not args.skip_qdt_model_executed_check,
        require_researcher_model_executed=args.require_researcher_model_executed,
        allowed_stage_failure_classes=tuple(args.allow_stage_failure_class),
    )
    if not args.handler_factory:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "--handler-factory is required for operational canary preflight/apply",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        factory = load_handler_factory(args.handler_factory)
        handlers = build_handlers_from_factory(factory, config)
        if args.preflight_only:
            conn = sqlite3.connect(config.db_path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                result = validate_preflight(conn, config, handlers)
            finally:
                conn.close()
        elif args.apply:
            result = run_one_case_canary(config, handlers)
        else:
            result = {
                "ok": False,
                "error": "refusing to run without --preflight-only or --apply",
            }
    except PipelineRunnerContractError as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
