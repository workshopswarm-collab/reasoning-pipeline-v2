#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from predquant.sqlite_store import (
    DEFAULT_DB_PATH,
    DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    record_market_prediction,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record a market prediction benchmark")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--market-id", type=int, help="Internal SQLite market id")
    target.add_argument("--external-market-id", help="External platform market id")
    parser.add_argument("--platform", default="polymarket", help="Market platform")
    parser.add_argument("--probability", type=float, required=True, help="Pipeline yes probability")
    parser.add_argument("--source", default="pipeline", help="Prediction source name")
    parser.add_argument("--label", help="Optional prediction label/version")
    parser.add_argument("--prediction-run-id", help="Stable id for this prediction run")
    parser.add_argument("--forecast-artifact-id", help="Stable id for the forecast artifact")
    parser.add_argument("--case-key", help="Pipeline case key associated with this prediction")
    parser.add_argument("--case-id", help="Pipeline case id associated with this prediction")
    parser.add_argument("--dispatch-id", help="Pipeline dispatch id associated with this prediction")
    parser.add_argument("--engine-stage", help="Prediction engine stage that produced this record")
    parser.add_argument("--predicted-at", help="Prediction timestamp; defaults to now")
    parser.add_argument("--market-probability", type=float, help="Override market yes probability")
    parser.add_argument("--market-probability-method", help="Method used for the market probability")
    parser.add_argument("--source-fetched-at", help="Timestamp when source market data was fetched")
    parser.add_argument("--source-payload-hash", help="Precomputed SHA-256 hash of source payload")
    parser.add_argument("--code-version", help="Pipeline code version or git commit")
    parser.add_argument("--model-name", help="Model name used for the prediction")
    parser.add_argument("--prompt-version", help="Prompt or strategy version used for the prediction")
    parser.add_argument("--input-hash", help="SHA-256 hash of the model or strategy input")
    parser.add_argument("--input-artifact-path", help="Path to the prediction input artifact")
    parser.add_argument("--input-artifact-sha256", help="SHA-256 of the prediction input artifact")
    parser.add_argument("--prediction-artifact-path", help="Path to the prediction output artifact")
    parser.add_argument("--prediction-artifact-sha256", help="SHA-256 of the prediction output artifact")
    parser.add_argument(
        "--max-snapshot-age-seconds",
        type=float,
        default=DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
        help="Reject predictions using older market data; default is 3600 seconds.",
    )
    parser.add_argument("--rationale", help="Optional prediction rationale")
    parser.add_argument("--metadata-json", default="{}", help="Optional JSON metadata")
    parser.add_argument(
        "--db-path",
        default=os.getenv("PREDQUANT_SQLITE_PATH", str(DEFAULT_DB_PATH)),
        help="SQLite database path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = record_market_prediction(
            db_path=Path(args.db_path),
            market_id=args.market_id,
            platform=args.platform,
            external_market_id=args.external_market_id,
            predicted_probability=args.probability,
            prediction_run_id=args.prediction_run_id,
            forecast_artifact_id=args.forecast_artifact_id,
            case_key=args.case_key,
            case_id=args.case_id,
            dispatch_id=args.dispatch_id,
            engine_stage=args.engine_stage,
            prediction_source=args.source,
            prediction_label=args.label,
            predicted_at=args.predicted_at,
            market_probability=args.market_probability,
            market_probability_method=args.market_probability_method,
            source_fetched_at=args.source_fetched_at,
            source_payload_hash=args.source_payload_hash,
            code_version=args.code_version,
            model_name=args.model_name,
            prompt_version=args.prompt_version,
            input_hash=args.input_hash,
            input_artifact_path=args.input_artifact_path,
            input_artifact_sha256=args.input_artifact_sha256,
            prediction_artifact_path=args.prediction_artifact_path,
            prediction_artifact_sha256=args.prediction_artifact_sha256,
            max_snapshot_age_seconds=args.max_snapshot_age_seconds,
            rationale=args.rationale,
            metadata=json.loads(args.metadata_json),
        )
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
