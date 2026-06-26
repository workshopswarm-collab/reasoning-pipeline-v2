"""AUTO-002 eligible-case selection and case lease guards."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from predquant.ads_case_contract import (
    DEFAULT_MAX_SNAPSHOT_AGE_SECONDS,
    CaseContractBlocked,
    CaseContractPolicy,
    eligible_market_rows,
    normalize_timestamp,
    parse_timestamp,
    row_to_dict,
    select_snapshot_for_forecast,
    stable_ids,
)
from predquant.ads_pipeline_runner import (
    canonical_json,
    ensure_pipeline_runner_schema,
    ensure_safe_metadata,
    read_pipeline_control_state,
    utc_now_iso,
)


CASE_LEASE_TABLE = "ads_case_leases"
CASE_LEASE_SCHEMA_VERSION = "ads-case-lease/v1"
CASE_SELECTION_CANDIDATE_SCHEMA_VERSION = "ads-case-selection-candidate/v1"
CASE_SELECTION_POLICY_REF = "ads-case-selection/v1"
CASE_LEASE_STATUSES = ("leased", "released", "expired", "quarantined")
DEFAULT_LEASE_DURATION_SECONDS = 3600
ADS_SCOREABLE_PREDICTION_SOURCE = "ads_pipeline"
ADS_SCOREABLE_PREDICTION_LABEL = "v2_scae"


class CaseSelectorError(ValueError):
    """Raised when AUTO-002 selection or lease state is invalid."""


class CaseLeaseRefused(CaseSelectorError):
    """Raised when the control state forbids new case leases."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class CaseSelectionPolicy:
    forecast_timestamp: str | None = None
    max_snapshot_age_seconds: float = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS
    lease_duration_seconds: int = DEFAULT_LEASE_DURATION_SECONDS
    selection_policy_ref: str = CASE_SELECTION_POLICY_REF
    lease_owner: str = "orchestrator"
    skip_existing_ads_predictions: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def ensure_case_selector_schema(conn: sqlite3.Connection) -> None:
    ensure_pipeline_runner_schema(conn)


def _require_non_empty(field: str, value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise CaseSelectorError(f"{field} is required")
    return value


def validate_selection_policy(policy: CaseSelectionPolicy) -> None:
    if policy.forecast_timestamp is not None:
        normalize_timestamp(policy.forecast_timestamp, "forecast_timestamp")
    if not isinstance(policy.max_snapshot_age_seconds, (int, float)) or policy.max_snapshot_age_seconds < 0:
        raise CaseSelectorError("max_snapshot_age_seconds must be non-negative")
    if not isinstance(policy.lease_duration_seconds, int) or policy.lease_duration_seconds <= 0:
        raise CaseSelectorError("lease_duration_seconds must be a positive integer")
    if not isinstance(policy.skip_existing_ads_predictions, bool):
        raise CaseSelectorError("skip_existing_ads_predictions must be a boolean")
    _require_non_empty("selection_policy_ref", policy.selection_policy_ref)
    _require_non_empty("lease_owner", policy.lease_owner)
    ensure_safe_metadata(policy.metadata)


def _ensure_row_factory(conn: sqlite3.Connection) -> None:
    if conn.row_factory is not sqlite3.Row:
        conn.row_factory = sqlite3.Row


def _add_seconds(timestamp: str, seconds: int) -> str:
    return (parse_timestamp(timestamp, "timestamp") + timedelta(seconds=seconds)).isoformat()


def make_case_lease_id(idempotency_key: str) -> str:
    _require_non_empty("idempotency_key", idempotency_key)
    return "ads-case-lease:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def make_case_lease_idempotency_key(
    *,
    market_id: int,
    case_key: str,
    selected_snapshot_id: int,
    selected_snapshot_observed_at: str,
    selection_policy_ref: str,
) -> str:
    payload = {
        "case_key": _require_non_empty("case_key", case_key),
        "market_id": int(market_id),
        "selected_snapshot_id": int(selected_snapshot_id),
        "selected_snapshot_observed_at": normalize_timestamp(
            selected_snapshot_observed_at,
            "selected_snapshot_observed_at",
        ),
        "selection_policy_ref": _require_non_empty("selection_policy_ref", selection_policy_ref),
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _lease_exists_for_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {CASE_LEASE_TABLE} WHERE idempotency_key = ? LIMIT 1",
        (idempotency_key,),
    ).fetchone()
    return row is not None


def _active_case_lease_exists(conn: sqlite3.Connection, *, market_id: int, case_key: str) -> bool:
    row = conn.execute(
        f"""
        SELECT 1
        FROM {CASE_LEASE_TABLE}
        WHERE market_id = ? AND case_key = ? AND lease_status = 'leased'
        LIMIT 1
        """,
        (market_id, case_key),
    ).fetchone()
    return row is not None


def _table_has_columns(conn: sqlite3.Connection, table: str, required_columns: tuple[str, ...]) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    columns = {row[1] for row in rows}
    return all(column in columns for column in required_columns)


def _existing_ads_prediction_for_market(conn: sqlite3.Connection, market_id: int) -> bool:
    if not _table_has_columns(
        conn,
        "market_predictions",
        ("market_id", "prediction_source", "prediction_label"),
    ):
        return False
    row = conn.execute(
        """
        SELECT 1
        FROM market_predictions
        WHERE market_id = ?
          AND prediction_source = ?
          AND prediction_label = ?
        LIMIT 1
        """,
        (market_id, ADS_SCOREABLE_PREDICTION_SOURCE, ADS_SCOREABLE_PREDICTION_LABEL),
    ).fetchone()
    return row is not None


def _fetch_lease_by_idempotency_key(conn: sqlite3.Connection, idempotency_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT case_lease_id, schema_version, pipeline_run_id, market_id, case_key,
               case_id, lease_status, lease_owner, lease_acquired_at, lease_expires_at,
               lease_released_at, dispatch_id, idempotency_key, selected_snapshot_id,
               selected_snapshot_observed_at, selection_policy_ref, release_reason,
               metadata
        FROM {CASE_LEASE_TABLE}
        WHERE idempotency_key = ?
        """,
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_case_lease(row)


def read_case_lease(conn: sqlite3.Connection, case_lease_id: str) -> dict[str, Any]:
    ensure_case_selector_schema(conn)
    _ensure_row_factory(conn)
    row = conn.execute(
        f"""
        SELECT case_lease_id, schema_version, pipeline_run_id, market_id, case_key,
               case_id, lease_status, lease_owner, lease_acquired_at, lease_expires_at,
               lease_released_at, dispatch_id, idempotency_key, selected_snapshot_id,
               selected_snapshot_observed_at, selection_policy_ref, release_reason,
               metadata
        FROM {CASE_LEASE_TABLE}
        WHERE case_lease_id = ?
        """,
        (case_lease_id,),
    ).fetchone()
    if row is None:
        raise CaseSelectorError(f"unknown case_lease_id: {case_lease_id}")
    return _row_to_case_lease(row)


def _row_to_case_lease(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    values = tuple(row)
    record = {
        "case_lease_id": values[0],
        "schema_version": values[1],
        "table": CASE_LEASE_TABLE,
        "pipeline_run_id": values[2],
        "market_id": values[3],
        "case_key": values[4],
        "case_id": values[5],
        "lease_status": values[6],
        "lease_owner": values[7],
        "lease_acquired_at": values[8],
        "lease_expires_at": values[9],
        "lease_released_at": values[10],
        "dispatch_id": values[11],
        "idempotency_key": values[12],
        "selected_snapshot_id": values[13],
        "selected_snapshot_observed_at": values[14],
        "selection_policy_ref": values[15],
        "release_reason": values[16],
        "metadata": _json_loads(values[17]),
    }
    validate_case_lease(record)
    return record


def _json_loads(value: str | None) -> Any:
    if not value:
        return {}
    import json

    return json.loads(value)


def validate_case_selection_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version") != CASE_SELECTION_CANDIDATE_SCHEMA_VERSION:
        raise CaseSelectorError(f"schema_version must be {CASE_SELECTION_CANDIDATE_SCHEMA_VERSION}")
    _require_non_empty("case_key", candidate.get("case_key"))
    _require_non_empty("case_id", candidate.get("case_id"))
    _require_non_empty("dispatch_id", candidate.get("dispatch_id"))
    _require_non_empty("forecast_timestamp", candidate.get("forecast_timestamp"))
    _require_non_empty("source_cutoff_timestamp", candidate.get("source_cutoff_timestamp"))
    _require_non_empty("selection_policy_ref", candidate.get("selection_policy_ref"))
    idempotency_key = _require_non_empty("idempotency_key", candidate.get("idempotency_key"))
    if not idempotency_key.startswith("sha256:"):
        raise CaseSelectorError("idempotency_key must be sha256-prefixed")
    if not isinstance(candidate.get("market_id"), int):
        raise CaseSelectorError("market_id must be an integer")
    if not isinstance(candidate.get("selected_snapshot_id"), int):
        raise CaseSelectorError("selected_snapshot_id must be an integer")
    snapshot_age = candidate.get("snapshot_age_seconds")
    if not isinstance(snapshot_age, (int, float)) or snapshot_age < 0:
        raise CaseSelectorError("snapshot_age_seconds must be non-negative")
    if parse_timestamp(candidate["source_cutoff_timestamp"], "source_cutoff_timestamp") > parse_timestamp(
        candidate["forecast_timestamp"],
        "forecast_timestamp",
    ):
        raise CaseSelectorError("source_cutoff_timestamp must not be after forecast_timestamp")


def validate_case_lease(record: dict[str, Any]) -> None:
    if record.get("schema_version") != CASE_LEASE_SCHEMA_VERSION:
        raise CaseSelectorError(f"schema_version must be {CASE_LEASE_SCHEMA_VERSION}")
    if record.get("table") != CASE_LEASE_TABLE:
        raise CaseSelectorError(f"table must be {CASE_LEASE_TABLE}")
    for field_name in [
        "case_lease_id",
        "pipeline_run_id",
        "case_key",
        "case_id",
        "lease_owner",
        "lease_acquired_at",
        "lease_expires_at",
        "dispatch_id",
        "idempotency_key",
        "selected_snapshot_observed_at",
        "selection_policy_ref",
    ]:
        _require_non_empty(field_name, record.get(field_name))
    if record["lease_status"] not in CASE_LEASE_STATUSES:
        raise CaseSelectorError("lease_status is invalid")
    if not isinstance(record.get("market_id"), int):
        raise CaseSelectorError("market_id must be an integer")
    if not isinstance(record.get("selected_snapshot_id"), int):
        raise CaseSelectorError("selected_snapshot_id must be an integer")
    if not str(record["idempotency_key"]).startswith("sha256:"):
        raise CaseSelectorError("idempotency_key must be sha256-prefixed")
    if record.get("lease_released_at") is not None:
        _require_non_empty("lease_released_at", record.get("lease_released_at"))
    if record.get("release_reason") is not None:
        _require_non_empty("release_reason", record.get("release_reason"))
    if parse_timestamp(record["lease_expires_at"], "lease_expires_at") <= parse_timestamp(
        record["lease_acquired_at"],
        "lease_acquired_at",
    ):
        raise CaseSelectorError("lease_expires_at must be after lease_acquired_at")
    ensure_safe_metadata(record.get("metadata"))


def build_case_selection_candidate(
    market: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    forecast_timestamp: str,
    snapshot_age_seconds: float,
    selection_policy_ref: str,
) -> dict[str, Any]:
    forecast_timestamp = normalize_timestamp(forecast_timestamp, "forecast_timestamp")
    snapshot_observed_at = normalize_timestamp(snapshot["observed_at"], "selected_snapshot_observed_at")
    ids = stable_ids(market, forecast_timestamp)
    candidate = {
        "schema_version": CASE_SELECTION_CANDIDATE_SCHEMA_VERSION,
        "market_id": market["id"],
        "case_key": ids["case_key"],
        "case_id": ids["case_id"],
        "dispatch_id": ids["dispatch_id"],
        "forecast_timestamp": forecast_timestamp,
        "source_cutoff_timestamp": snapshot_observed_at,
        "selected_snapshot_id": snapshot["id"],
        "selected_snapshot_observed_at": snapshot_observed_at,
        "snapshot_age_seconds": snapshot_age_seconds,
        "selection_policy_ref": selection_policy_ref,
    }
    candidate["idempotency_key"] = make_case_lease_idempotency_key(
        market_id=candidate["market_id"],
        case_key=candidate["case_key"],
        selected_snapshot_id=candidate["selected_snapshot_id"],
        selected_snapshot_observed_at=candidate["selected_snapshot_observed_at"],
        selection_policy_ref=selection_policy_ref,
    )
    validate_case_selection_candidate(candidate)
    return candidate


def select_eligible_case(conn: sqlite3.Connection, policy: CaseSelectionPolicy | None = None) -> dict[str, Any] | None:
    policy = policy or CaseSelectionPolicy()
    validate_selection_policy(policy)
    ensure_case_selector_schema(conn)
    _ensure_row_factory(conn)
    forecast_timestamp = normalize_timestamp(policy.forecast_timestamp or utc_now_iso(), "forecast_timestamp")
    contract_policy = CaseContractPolicy(max_snapshot_age_seconds=policy.max_snapshot_age_seconds)

    for market_row in eligible_market_rows(conn):
        market = row_to_dict(market_row)
        if policy.skip_existing_ads_predictions and _existing_ads_prediction_for_market(conn, market["id"]):
            continue
        try:
            snapshot_row, snapshot_age = select_snapshot_for_forecast(
                conn,
                market["id"],
                forecast_timestamp,
                max_snapshot_age_seconds=contract_policy.max_snapshot_age_seconds,
            )
        except CaseContractBlocked:
            continue
        snapshot = row_to_dict(snapshot_row)
        candidate = build_case_selection_candidate(
            market,
            snapshot,
            forecast_timestamp=forecast_timestamp,
            snapshot_age_seconds=snapshot_age,
            selection_policy_ref=policy.selection_policy_ref,
        )
        if _lease_exists_for_idempotency_key(conn, candidate["idempotency_key"]):
            continue
        if _active_case_lease_exists(conn, market_id=candidate["market_id"], case_key=candidate["case_key"]):
            continue
        return candidate
    return None


def _ensure_pipeline_enabled_for_new_lease(conn: sqlite3.Connection) -> None:
    control = read_pipeline_control_state(conn)
    if not control["pipeline_enabled"]:
        raise CaseLeaseRefused("pipeline_disabled", "pipeline_enabled=false refuses new case leases")


def build_case_lease(
    *,
    pipeline_run_id: str,
    candidate: dict[str, Any],
    lease_owner: str,
    lease_acquired_at: str,
    lease_duration_seconds: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_case_selection_candidate(candidate)
    metadata_record = ensure_safe_metadata(metadata)
    record = {
        "schema_version": CASE_LEASE_SCHEMA_VERSION,
        "table": CASE_LEASE_TABLE,
        "case_lease_id": make_case_lease_id(candidate["idempotency_key"]),
        "pipeline_run_id": _require_non_empty("pipeline_run_id", pipeline_run_id),
        "market_id": candidate["market_id"],
        "case_key": candidate["case_key"],
        "case_id": candidate["case_id"],
        "lease_status": "leased",
        "lease_owner": _require_non_empty("lease_owner", lease_owner),
        "lease_acquired_at": normalize_timestamp(lease_acquired_at, "lease_acquired_at"),
        "lease_expires_at": _add_seconds(lease_acquired_at, lease_duration_seconds),
        "lease_released_at": None,
        "dispatch_id": candidate["dispatch_id"],
        "idempotency_key": candidate["idempotency_key"],
        "selected_snapshot_id": candidate["selected_snapshot_id"],
        "selected_snapshot_observed_at": candidate["selected_snapshot_observed_at"],
        "selection_policy_ref": candidate["selection_policy_ref"],
        "release_reason": None,
        "metadata": metadata_record,
    }
    validate_case_lease(record)
    return record


def acquire_case_lease(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str,
    candidate: dict[str, Any],
    policy: CaseSelectionPolicy | None = None,
    lease_acquired_at: str | None = None,
) -> dict[str, Any] | None:
    policy = policy or CaseSelectionPolicy()
    validate_selection_policy(policy)
    ensure_case_selector_schema(conn)
    _ensure_row_factory(conn)
    _ensure_pipeline_enabled_for_new_lease(conn)
    record = build_case_lease(
        pipeline_run_id=pipeline_run_id,
        candidate=candidate,
        lease_owner=policy.lease_owner,
        lease_acquired_at=lease_acquired_at or utc_now_iso(),
        lease_duration_seconds=policy.lease_duration_seconds,
        metadata=policy.metadata,
    )
    existing = _fetch_lease_by_idempotency_key(conn, record["idempotency_key"])
    if existing is not None:
        if existing["lease_status"] == "leased" and existing["pipeline_run_id"] == pipeline_run_id:
            return existing
        return None

    try:
        conn.execute(
            f"""
            INSERT INTO {CASE_LEASE_TABLE} (
              case_lease_id, schema_version, pipeline_run_id, market_id, case_key,
              case_id, lease_status, lease_owner, lease_acquired_at, lease_expires_at,
              lease_released_at, dispatch_id, idempotency_key, selected_snapshot_id,
              selected_snapshot_observed_at, selection_policy_ref, release_reason,
              metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["case_lease_id"],
                record["schema_version"],
                record["pipeline_run_id"],
                record["market_id"],
                record["case_key"],
                record["case_id"],
                record["lease_status"],
                record["lease_owner"],
                record["lease_acquired_at"],
                record["lease_expires_at"],
                record["lease_released_at"],
                record["dispatch_id"],
                record["idempotency_key"],
                record["selected_snapshot_id"],
                record["selected_snapshot_observed_at"],
                record["selection_policy_ref"],
                record["release_reason"],
                canonical_json(record["metadata"]),
            ),
        )
    except sqlite3.IntegrityError:
        existing = _fetch_lease_by_idempotency_key(conn, record["idempotency_key"])
        if existing is not None and existing["lease_status"] == "leased" and existing["pipeline_run_id"] == pipeline_run_id:
            return existing
        return None
    return read_case_lease(conn, record["case_lease_id"])


def acquire_next_case_lease(
    conn: sqlite3.Connection,
    *,
    pipeline_run_id: str,
    policy: CaseSelectionPolicy | None = None,
) -> dict[str, Any] | None:
    policy = policy or CaseSelectionPolicy()
    validate_selection_policy(policy)
    ensure_case_selector_schema(conn)
    _ensure_row_factory(conn)
    _ensure_pipeline_enabled_for_new_lease(conn)
    candidate = select_eligible_case(conn, policy)
    if candidate is None:
        return None
    return acquire_case_lease(conn, pipeline_run_id=pipeline_run_id, candidate=candidate, policy=policy)


def release_case_lease(
    conn: sqlite3.Connection,
    *,
    case_lease_id: str,
    release_reason: str,
    lease_status: str = "released",
    released_at: str | None = None,
) -> dict[str, Any]:
    ensure_case_selector_schema(conn)
    _ensure_row_factory(conn)
    if lease_status not in {"released", "expired", "quarantined"}:
        raise CaseSelectorError("release lease_status must be released, expired, or quarantined")
    released_at = normalize_timestamp(released_at or utc_now_iso(), "released_at")
    _require_non_empty("release_reason", release_reason)
    current = read_case_lease(conn, case_lease_id)
    if current["lease_status"] == lease_status and current["release_reason"] == release_reason:
        return current
    if current["lease_status"] != "leased":
        raise CaseSelectorError("only leased case leases may be released")
    conn.execute(
        f"""
        UPDATE {CASE_LEASE_TABLE}
        SET lease_status = ?,
            lease_released_at = ?,
            release_reason = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE case_lease_id = ?
        """,
        (lease_status, released_at, release_reason, case_lease_id),
    )
    return read_case_lease(conn, case_lease_id)
