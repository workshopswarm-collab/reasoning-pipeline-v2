"""ADS v2 case-contract adapter over existing market intake rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predquant.ads_handoff import (
    ArtifactManifestContext,
    build_artifact_manifest,
    canonical_json,
    ensure_artifact_manifest_schema,
    validate_artifact_manifest,
    write_artifact_manifest,
)
from predquant.brier import market_probability_from_snapshot


ADS_CASE_CONTRACT_SCHEMA_VERSION = "ads-case-contract/v1"
CASE_INTAKE_HANDOFF_SCHEMA_VERSION = "case-intake-handoff/v1"
ADS_CASE_CONTRACT_TABLE = "ads_case_contracts"
CASE_INTAKE_HANDOFF_TABLE = "case_intake_handoff_records"
CASE_CONTRACT_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "004_ads_case_contract.sql"
DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 3600.0
OPEN_MARKET_STATUSES = {"open", "active"}


class CaseContractError(ValueError):
    """Raised when an ADS case contract is malformed."""


class CaseContractBlocked(CaseContractError):
    """Raised when intake cannot safely produce a case contract."""

    def __init__(self, reason_code: str, message: str, snapshot_row: sqlite3.Row | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.snapshot_row = snapshot_row


@dataclass(frozen=True)
class CaseContractPolicy:
    max_snapshot_age_seconds: float = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS
    adapter_policy_id: str = "ads-case-contract-intake/v1"
    ingestion_runner: str = "ingest_polymarket_market_snapshots"
    ingestion_schema_version: str = "polymarket-snapshot-ingester/v1"
    producer: str = "session-02-case-contract"
    db_path_ref: str = "PREDQUANT_SQLITE_PATH|scripts/data/predquant.sqlite3"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise CaseContractError(f"{field} is required")
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_timestamp(value: str, field: str) -> str:
    return parse_timestamp(value, field).isoformat()


def row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def json_loads_or_empty(text: str | None) -> Any:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"unparsed_text_sha256": prefixed_sha256(str(text))}


def prefixed_sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return "sha256:" + hashlib.sha256(value).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    seed = "|".join(str(part) for part in parts)
    return f"{prefix}-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def stable_ids(market: dict[str, Any], forecast_timestamp: str) -> dict[str, str]:
    case_key = f"{market['platform']}:{market['external_market_id']}"
    return {
        "case_key": case_key,
        "case_id": stable_id("case", case_key),
        "dispatch_id": stable_id("dispatch", case_key, forecast_timestamp),
        "prediction_run_id": stable_id("ads-run", case_key, forecast_timestamp),
        "forecast_artifact_id": stable_id("forecast", case_key, forecast_timestamp),
    }


def source_payload_hash(snapshot: dict[str, Any]) -> str:
    raw_payload = snapshot.get("raw_payload") or "{}"
    parsed = json_loads_or_empty(raw_payload)
    return prefixed_sha256(canonical_json(parsed))


def ensure_case_contract_schema(conn: sqlite3.Connection) -> None:
    ensure_artifact_manifest_schema(conn)
    conn.executescript(CASE_CONTRACT_MIGRATION.read_text(encoding="utf-8"))


def eligible_market_rows(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT *
        FROM markets
        WHERE lower(status) IN ('open', 'active')
        ORDER BY id
    """
    if limit is not None:
        query += " LIMIT ?"
        return list(conn.execute(query, (limit,)).fetchall())
    return list(conn.execute(query).fetchall())


def fetch_market(conn: sqlite3.Connection, market_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM markets WHERE id = ?", (market_id,)).fetchone()
    if row is None:
        raise CaseContractBlocked("case_contract_market_missing", f"market not found: {market_id}")
    if str(row["status"]).lower() not in OPEN_MARKET_STATUSES:
        raise CaseContractBlocked("case_contract_market_not_active", f"market {market_id} is not active/open")
    return row


def select_snapshot_for_forecast(
    conn: sqlite3.Connection,
    market_id: int,
    forecast_timestamp: str,
    *,
    max_snapshot_age_seconds: float,
) -> tuple[sqlite3.Row, float]:
    forecast_at = parse_timestamp(forecast_timestamp, "forecast_timestamp")
    latest_before = conn.execute(
        """
        SELECT *
        FROM market_snapshots
        WHERE market_id = ? AND observed_at <= ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (market_id, forecast_timestamp),
    ).fetchone()
    if latest_before is None:
        latest_any = conn.execute(
            """
            SELECT *
            FROM market_snapshots
            WHERE market_id = ?
            ORDER BY observed_at ASC, id ASC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        if latest_any is None:
            raise CaseContractBlocked("case_contract_snapshot_missing", "no snapshot exists for market")
        raise CaseContractBlocked(
            "case_contract_snapshot_lookahead",
            "only post-forecast snapshots are available",
            snapshot_row=latest_any,
        )

    observed_at = parse_timestamp(latest_before["observed_at"], "snapshot_observed_at")
    snapshot_age = (forecast_at - observed_at).total_seconds()
    if snapshot_age < 0:
        raise CaseContractBlocked(
            "case_contract_snapshot_lookahead",
            "snapshot is after forecast timestamp",
            snapshot_row=latest_before,
        )
    if snapshot_age > max_snapshot_age_seconds:
        raise CaseContractBlocked(
            "case_contract_snapshot_stale",
            "snapshot exceeds max age policy",
            snapshot_row=latest_before,
        )
    return latest_before, snapshot_age


def market_identity_from_row(market: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": market["platform"],
        "internal_market_id": market["id"],
        "external_market_id": str(market["external_market_id"]),
        "slug": market.get("slug"),
        "title": market["title"],
        "description": market.get("description"),
        "category": market.get("category"),
        "status": market["status"],
        "outcome_type": market.get("outcome_type"),
        "closes_at": market.get("closes_at"),
        "resolves_at": market.get("resolves_at"),
    }


def downstream_artifact_refs() -> dict[str, Any]:
    return {
        "evidence_packet": None,
        "related_live_market_context": None,
        "question_decomposition": None,
        "retrieval_packet": None,
        "verification_bundle": None,
        "scae_ledger": None,
        "forecast_decision": None,
        "market_prediction_row": None,
    }


def build_ads_case_contract(
    market_row: sqlite3.Row | dict[str, Any],
    snapshot_row: sqlite3.Row | dict[str, Any],
    forecast_timestamp: str,
    *,
    snapshot_age_seconds: float | None = None,
    policy: CaseContractPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or CaseContractPolicy()
    market = row_to_dict(market_row)
    snapshot = row_to_dict(snapshot_row)
    forecast_timestamp = normalize_timestamp(forecast_timestamp, "forecast_timestamp")
    observed_timestamp = normalize_timestamp(snapshot["observed_at"], "snapshot_observed_at")
    if snapshot_age_seconds is None:
        snapshot_age_seconds = (
            parse_timestamp(forecast_timestamp, "forecast_timestamp")
            - parse_timestamp(observed_timestamp, "snapshot_observed_at")
        ).total_seconds()
    if snapshot_age_seconds < 0:
        raise CaseContractBlocked("case_contract_snapshot_lookahead", "snapshot is after forecast timestamp")
    if snapshot_age_seconds > policy.max_snapshot_age_seconds:
        raise CaseContractBlocked("case_contract_snapshot_stale", "snapshot exceeds max age policy")

    ids = stable_ids(market, forecast_timestamp)
    market_probability, method = market_probability_from_snapshot(snapshot, market.get("current_price"))
    payload_digest = source_payload_hash(snapshot)
    contract = {
        "artifact_type": "ads_case_contract",
        "schema_version": ADS_CASE_CONTRACT_SCHEMA_VERSION,
        **ids,
        "forecast_timestamp": forecast_timestamp,
        "source_cutoff_timestamp": observed_timestamp,
        "intake_source": {
            "system": "predquant_sqlite",
            "db_path_ref": policy.db_path_ref,
            "source_tables": ["markets", "market_snapshots"],
            "market_row_id": market["id"],
            "market_snapshot_id": snapshot["id"],
            "snapshot_observed_at": observed_timestamp,
            "source_payload_hash": payload_digest,
            "ingestion_runner": policy.ingestion_runner,
            "ingestion_schema_version": policy.ingestion_schema_version,
        },
        "market_identity": market_identity_from_row(market),
        "prediction_time_market_baseline": {
            "market_snapshot_id": snapshot["id"],
            "source_fetched_at": observed_timestamp,
            "snapshot_age_seconds_at_dispatch": snapshot_age_seconds,
            "max_snapshot_age_seconds": policy.max_snapshot_age_seconds,
            "market_probability": market_probability,
            "market_probability_method": method,
        },
        "raw_input_refs": [
            {
                "table": "markets",
                "row_id": market["id"],
            },
            {
                "table": "market_snapshots",
                "row_id": snapshot["id"],
                "payload_hash": payload_digest,
            },
        ],
        "downstream_artifact_refs": downstream_artifact_refs(),
    }
    validate_ads_case_contract(contract)
    return contract


def validate_ads_case_contract(contract: dict[str, Any]) -> None:
    required = [
        "artifact_type",
        "schema_version",
        "case_key",
        "case_id",
        "dispatch_id",
        "prediction_run_id",
        "forecast_artifact_id",
        "forecast_timestamp",
        "source_cutoff_timestamp",
        "intake_source",
        "market_identity",
        "prediction_time_market_baseline",
        "raw_input_refs",
        "downstream_artifact_refs",
    ]
    for field in required:
        if field not in contract:
            raise CaseContractError(f"{field} is required")
    if contract["artifact_type"] != "ads_case_contract":
        raise CaseContractError("artifact_type must be ads_case_contract")
    if contract["schema_version"] != ADS_CASE_CONTRACT_SCHEMA_VERSION:
        raise CaseContractError(f"schema_version must be {ADS_CASE_CONTRACT_SCHEMA_VERSION}")
    forecast_at = parse_timestamp(contract["forecast_timestamp"], "forecast_timestamp")
    cutoff_at = parse_timestamp(contract["source_cutoff_timestamp"], "source_cutoff_timestamp")
    if cutoff_at > forecast_at:
        raise CaseContractError("source_cutoff_timestamp must not be after forecast_timestamp")
    intake = contract["intake_source"]
    if intake.get("source_tables") != ["markets", "market_snapshots"]:
        raise CaseContractError("source_tables must bind markets and market_snapshots")
    if not str(intake.get("source_payload_hash", "")).startswith("sha256:"):
        raise CaseContractError("source_payload_hash must be sha256-prefixed")
    baseline = contract["prediction_time_market_baseline"]
    if baseline.get("market_snapshot_id") != intake.get("market_snapshot_id"):
        raise CaseContractError("baseline snapshot id must match intake source")
    age = baseline.get("snapshot_age_seconds_at_dispatch")
    max_age = baseline.get("max_snapshot_age_seconds")
    if not isinstance(age, (int, float)) or age < 0:
        raise CaseContractError("snapshot age must be non-negative")
    if not isinstance(max_age, (int, float)) or age > max_age:
        raise CaseContractError("snapshot age exceeds max policy")
    ensure_no_raw_payload_fields(contract)


def ensure_no_raw_payload_fields(value: Any, path: str = "contract") -> None:
    forbidden = {"raw_payload", "payload", "raw_content", "content", "body", "html", "page_text"}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise CaseContractError(f"{path}.{key} must not duplicate raw payload content")
            ensure_no_raw_payload_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            ensure_no_raw_payload_fields(child, f"{path}[{idx}]")


def contract_path(artifact_dir: Path | str, contract: dict[str, Any]) -> Path:
    base = Path(artifact_dir) / contract["case_id"]
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{contract['dispatch_id']}-ads-case-contract.json"


def write_contract_artifact(path: Path | str, contract: dict[str, Any]) -> Path:
    validate_ads_case_contract(contract)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_json(contract) + "\n", encoding="utf-8")
    return target


def build_manifest_for_contract(contract: dict[str, Any], path: Path | str, *, policy: CaseContractPolicy) -> dict[str, Any]:
    context = ArtifactManifestContext(
        case_id=contract["case_id"],
        case_key=contract["case_key"],
        dispatch_id=contract["dispatch_id"],
        stage="case_selection",
        producer=policy.producer,
        forecast_timestamp=contract["forecast_timestamp"],
        source_cutoff_timestamp=contract["source_cutoff_timestamp"],
    )
    manifest = build_artifact_manifest(
        context=context,
        artifact_type="ads-case-contract",
        artifact_schema_version=ADS_CASE_CONTRACT_SCHEMA_VERSION,
        path=path,
        validation_status="valid",
        validator_version="ads-case-contract/v1",
        temporal_isolation_status="pass",
        metadata={
            "market_id": contract["market_identity"]["internal_market_id"],
            "market_snapshot_id": contract["intake_source"]["market_snapshot_id"],
            "source_payload_hash": contract["intake_source"]["source_payload_hash"],
        },
    )
    validate_artifact_manifest(manifest, expected_artifact_schema_version=ADS_CASE_CONTRACT_SCHEMA_VERSION)
    return manifest


def build_case_intake_handoff_record(
    *,
    contract: dict[str, Any] | None,
    market: dict[str, Any],
    snapshot: dict[str, Any] | None,
    forecast_timestamp: str,
    policy: CaseContractPolicy,
    status: str,
    reason_code: str | None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    forecast_timestamp = normalize_timestamp(forecast_timestamp, "forecast_timestamp")
    ids = contract or stable_ids(market, forecast_timestamp)
    snapshot_age = None
    source_cutoff = None
    payload_digest = None
    market_probability = None
    method = None
    snapshot_id = None
    if snapshot:
        snapshot_id = snapshot["id"]
        source_cutoff = normalize_timestamp(snapshot["observed_at"], "snapshot_observed_at")
        snapshot_age = (parse_timestamp(forecast_timestamp, "forecast_timestamp") - parse_timestamp(source_cutoff, "snapshot_observed_at")).total_seconds()
        payload_digest = source_payload_hash(snapshot)
        market_probability, method = market_probability_from_snapshot(snapshot, market.get("current_price"))
    return {
        "schema_version": CASE_INTAKE_HANDOFF_SCHEMA_VERSION,
        "handoff_id": stable_id("case-handoff", ids["case_key"], ids["dispatch_id"]),
        "case_key": ids["case_key"],
        "case_id": ids["case_id"],
        "dispatch_id": ids["dispatch_id"],
        "market_id": market["id"],
        "market_snapshot_id": snapshot_id,
        "forecast_timestamp": forecast_timestamp,
        "source_cutoff_timestamp": source_cutoff,
        "snapshot_age_seconds": snapshot_age,
        "max_snapshot_age_seconds": policy.max_snapshot_age_seconds,
        "handoff_status": status,
        "reason_code": reason_code,
        "adapter_policy": policy.adapter_policy_id,
        "source_table_refs": {"markets": market["id"], "market_snapshots": snapshot_id},
        "source_payload_hash": payload_digest,
        "market_probability": market_probability,
        "market_probability_method": method,
        "artifact_id": artifact_id,
        "metadata": {"producer": policy.producer},
    }


def write_case_intake_handoff(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    conn.execute(
        """
        INSERT INTO case_intake_handoff_records (
          handoff_id, schema_version, case_key, case_id, dispatch_id, market_id,
          market_snapshot_id, forecast_timestamp, source_cutoff_timestamp,
          snapshot_age_seconds, max_snapshot_age_seconds, handoff_status,
          reason_code, adapter_policy, source_table_refs, source_payload_hash,
          market_probability, market_probability_method, artifact_id, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(handoff_id) DO UPDATE SET
          market_snapshot_id=excluded.market_snapshot_id,
          source_cutoff_timestamp=excluded.source_cutoff_timestamp,
          snapshot_age_seconds=excluded.snapshot_age_seconds,
          handoff_status=excluded.handoff_status,
          reason_code=excluded.reason_code,
          source_payload_hash=excluded.source_payload_hash,
          market_probability=excluded.market_probability,
          market_probability_method=excluded.market_probability_method,
          artifact_id=excluded.artifact_id,
          metadata=excluded.metadata,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            record["handoff_id"],
            record["schema_version"],
            record["case_key"],
            record["case_id"],
            record["dispatch_id"],
            record["market_id"],
            record["market_snapshot_id"],
            record["forecast_timestamp"],
            record["source_cutoff_timestamp"],
            record["snapshot_age_seconds"],
            record["max_snapshot_age_seconds"],
            record["handoff_status"],
            record["reason_code"],
            record["adapter_policy"],
            canonical_json(record["source_table_refs"]),
            record["source_payload_hash"],
            record["market_probability"],
            record["market_probability_method"],
            record["artifact_id"],
            canonical_json(record["metadata"]),
        ),
    )
    return record["handoff_id"]


def write_ads_case_contract(conn: sqlite3.Connection, contract: dict[str, Any], manifest: dict[str, Any]) -> str:
    validate_ads_case_contract(contract)
    validate_artifact_manifest(manifest, expected_artifact_schema_version=ADS_CASE_CONTRACT_SCHEMA_VERSION)
    contract_id = stable_id("ads-contract", contract["case_key"], contract["dispatch_id"])
    baseline = contract["prediction_time_market_baseline"]
    intake = contract["intake_source"]
    conn.execute(
        """
        INSERT INTO ads_case_contracts (
          contract_id, schema_version, case_key, case_id, dispatch_id,
          prediction_run_id, forecast_artifact_id, market_id, market_snapshot_id,
          forecast_timestamp, source_cutoff_timestamp, source_payload_hash,
          market_probability, market_probability_method, artifact_id, artifact_path,
          artifact_sha256, validation_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dispatch_id) DO UPDATE SET
          artifact_id=excluded.artifact_id,
          artifact_path=excluded.artifact_path,
          artifact_sha256=excluded.artifact_sha256,
          validation_status=excluded.validation_status,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            contract_id,
            contract["schema_version"],
            contract["case_key"],
            contract["case_id"],
            contract["dispatch_id"],
            contract["prediction_run_id"],
            contract["forecast_artifact_id"],
            contract["market_identity"]["internal_market_id"],
            intake["market_snapshot_id"],
            contract["forecast_timestamp"],
            contract["source_cutoff_timestamp"],
            intake["source_payload_hash"],
            baseline["market_probability"],
            baseline["market_probability_method"],
            manifest["artifact_id"],
            manifest["path"],
            manifest["sha256"],
            manifest["validation_status"],
        ),
    )
    return contract_id


def materialize_ads_case_contract(
    conn: sqlite3.Connection,
    *,
    market_id: int,
    forecast_timestamp: str,
    artifact_dir: Path | str,
    policy: CaseContractPolicy | None = None,
) -> dict[str, Any]:
    policy = policy or CaseContractPolicy()
    conn.row_factory = sqlite3.Row
    ensure_case_contract_schema(conn)
    market = row_to_dict(fetch_market(conn, market_id))
    snapshot = None
    try:
        snapshot_row, snapshot_age = select_snapshot_for_forecast(
            conn,
            market_id,
            normalize_timestamp(forecast_timestamp, "forecast_timestamp"),
            max_snapshot_age_seconds=policy.max_snapshot_age_seconds,
        )
        snapshot = row_to_dict(snapshot_row)
        contract = build_ads_case_contract(
            market,
            snapshot,
            forecast_timestamp,
            snapshot_age_seconds=snapshot_age,
            policy=policy,
        )
        path = write_contract_artifact(contract_path(artifact_dir, contract), contract)
        manifest = build_manifest_for_contract(contract, path, policy=policy)
        artifact_id = write_artifact_manifest(conn, manifest)
        handoff = build_case_intake_handoff_record(
            contract=contract,
            market=market,
            snapshot=snapshot,
            forecast_timestamp=forecast_timestamp,
            policy=policy,
            status="completed",
            reason_code=None,
            artifact_id=artifact_id,
        )
        write_case_intake_handoff(conn, handoff)
        contract_id = write_ads_case_contract(conn, contract, manifest)
        return {
            "status": "completed",
            "contract_id": contract_id,
            "artifact_id": artifact_id,
            "artifact_path": str(path),
            "contract": contract,
            "manifest": manifest,
            "handoff_id": handoff["handoff_id"],
        }
    except CaseContractBlocked as exc:
        if exc.snapshot_row is not None:
            snapshot = row_to_dict(exc.snapshot_row)
        handoff = build_case_intake_handoff_record(
            contract=None,
            market=market,
            snapshot=snapshot,
            forecast_timestamp=forecast_timestamp,
            policy=policy,
            status="blocked",
            reason_code=exc.reason_code,
        )
        write_case_intake_handoff(conn, handoff)
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an ADS case contract from existing intake rows.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--market-id", required=True, type=int)
    parser.add_argument("--forecast-timestamp", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--max-snapshot-age-seconds", type=float, default=DEFAULT_MAX_SNAPSHOT_AGE_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        policy = CaseContractPolicy(max_snapshot_age_seconds=args.max_snapshot_age_seconds)
        with conn:
            result = materialize_ads_case_contract(
                conn,
                market_id=args.market_id,
                forecast_timestamp=args.forecast_timestamp,
                artifact_dir=args.artifact_dir,
                policy=policy,
            )
        print(canonical_json({k: v for k, v in result.items() if k not in {"contract", "manifest"}}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
