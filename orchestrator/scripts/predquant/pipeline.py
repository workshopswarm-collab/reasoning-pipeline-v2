import json
from pathlib import Path

from predquant.sqlite_store import normalize_payload, run_sqlite


def infer_outcome_type(item: dict) -> str:
    outcome_type = item.get("outcome_type")
    metadata = item.get("metadata") or {}
    outcomes = metadata.get("outcome_labels") or metadata.get("market_outcomes_parsed")
    if isinstance(outcomes, list):
        normalized = [str(outcome).strip().lower() for outcome in outcomes]
        if len(normalized) == 2 and normalized == ["yes", "no"]:
            return "binary"
    return outcome_type


def load_filtered_markets(input_json_file: Path) -> list:
    if not input_json_file.exists():
        raise FileNotFoundError(f"{input_json_file} not found")

    with input_json_file.open("r", encoding="utf-8") as f:
        markets = json.load(f)

    if not isinstance(markets, list):
        raise ValueError(f"{input_json_file} must contain a JSON array")
    return markets


def normalize_market_payload(item: dict) -> dict:
    return {
        "platform": item.get("platform"),
        "external_market_id": item.get("external_market_id"),
        "slug": item.get("slug"),
        "title": item.get("title"),
        "description": item.get("description"),
        "category": item.get("category"),
        "status": item.get("status"),
        "outcome_type": infer_outcome_type(item),
        "closes_at": item.get("closes_at"),
        "resolves_at": item.get("resolves_at"),
        "metadata": item.get("metadata", {}),
        "snapshot": item.get("snapshot", {}),
    }


def push_filtered_markets(input_json_file: Path, db_path: Path) -> dict:
    markets = load_filtered_markets(input_json_file)
    success_count = 0
    error_count = 0
    errors = []

    for item in markets:
        if not isinstance(item, dict):
            error_count += 1
            errors.append("Skipping non-object item in JSON array.")
            continue

        payload = normalize_market_payload(item)
        try:
            payload, snapshot = normalize_payload(payload)
            run_sqlite(db_path, payload, snapshot)
            success_count += 1
        except Exception as exc:
            error_count += 1
            market_ref = (
                payload.get("external_market_id")
                or payload.get("slug")
                or "UNKNOWN"
            )
            errors.append(f"Failed to insert {market_ref}: {exc}")

    return {
        "loaded": len(markets),
        "success": success_count,
        "errors": error_count,
        "messages": errors,
    }
