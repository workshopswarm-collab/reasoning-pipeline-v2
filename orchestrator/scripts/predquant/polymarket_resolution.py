import json
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")

import requests

from predquant.polymarket_intake import GAMMA_API_BASE
from predquant.sqlite_store import (
    ensure_schema,
    parse_market_time,
    payload_hash,
    settle_market_outcome,
    to_json_text,
)


DEFAULT_TERMINAL_TOLERANCE = 0.001
RESOLUTION_SYNC_HEARTBEAT_TABLE = "polymarket_resolution_sync_heartbeats"


def ensure_resolution_sync_heartbeat_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RESOLUTION_SYNC_HEARTBEAT_TABLE} (
          heartbeat_id TEXT PRIMARY KEY,
          checked_at TEXT NOT NULL,
          candidate_count INTEGER NOT NULL,
          resolved_count INTEGER NOT NULL,
          unresolved_count INTEGER NOT NULL,
          error_count INTEGER NOT NULL,
          dry_run INTEGER NOT NULL DEFAULT 0,
          metadata TEXT NOT NULL DEFAULT '{{}}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def parse_json_list(value, default=None):
    if default is None:
        default = []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else default
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def fetch_polymarket_market(external_market_id: str, timeout: int = 30) -> dict:
    response = requests.get(
        f"{GAMMA_API_BASE}/markets/{external_market_id}",
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected market response for {external_market_id}")
    return payload


def parse_probability(value) -> Optional[float]:
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= probability <= 1.0:
        return None
    return probability


def normalize_time(value) -> Optional[str]:
    parsed = parse_market_time(value)
    return parsed.isoformat() if parsed else None


def infer_binary_resolution(
    market_payload: dict,
    terminal_tolerance: float = DEFAULT_TERMINAL_TOLERANCE,
) -> dict:
    if not market_payload.get("closed"):
        return {
            "resolved": False,
            "reason": "source_market_not_closed",
        }

    outcomes = parse_json_list(market_payload.get("outcomes"))
    prices = parse_json_list(market_payload.get("outcomePrices"))
    if len(outcomes) != 2 or len(prices) != 2:
        return {
            "resolved": False,
            "reason": "not_binary_outcome_prices",
        }

    normalized_outcomes = [str(outcome).strip().lower() for outcome in outcomes]
    if normalized_outcomes[:2] != ["yes", "no"]:
        return {
            "resolved": False,
            "reason": "not_yes_no_outcome_order",
        }

    yes_price = parse_probability(prices[0])
    no_price = parse_probability(prices[1])
    if yes_price is None or no_price is None:
        return {
            "resolved": False,
            "reason": "invalid_outcome_prices",
        }

    if yes_price >= 1.0 - terminal_tolerance and no_price <= terminal_tolerance:
        outcome = 1.0
    elif yes_price <= terminal_tolerance and no_price >= 1.0 - terminal_tolerance:
        outcome = 0.0
    elif (
        abs(yes_price - 0.5) <= terminal_tolerance
        and abs(no_price - 0.5) <= terminal_tolerance
    ):
        outcome = 0.5
    else:
        return {
            "resolved": False,
            "reason": "closed_without_terminal_outcome_prices",
            "yes_price": yes_price,
            "no_price": no_price,
        }

    resolved_at = normalize_time(market_payload.get("closedTime"))
    if not resolved_at:
        return {
            "resolved": False,
            "reason": "missing_closed_time",
            "outcome": outcome,
            "yes_price": yes_price,
            "no_price": no_price,
        }

    return {
        "resolved": True,
        "outcome": outcome,
        "resolved_at": resolved_at,
        "method": "polymarket_closed_terminal_outcome_price",
        "yes_price": yes_price,
        "no_price": no_price,
    }


def candidate_markets_for_resolution(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT id, external_market_id, title, status, closes_at
        FROM markets
        WHERE platform = 'polymarket'
          AND resolution_outcome IS NULL
          AND status = 'closed'
        ORDER BY closes_at ASC, id ASC
    """
    params = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    return conn.execute(sql, params).fetchall()


def mark_resolution_checked(
    conn: sqlite3.Connection,
    market_id: int,
    market_payload: dict,
    method: str,
    checked_at: str,
) -> None:
    conn.execute(
        """
        UPDATE markets
        SET resolution_payload_hash = ?,
            resolution_payload = ?,
            resolution_method = ?,
            resolution_checked_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            payload_hash(market_payload),
            to_json_text(market_payload),
            method,
            checked_at,
            checked_at,
            market_id,
        ),
    )


def sync_polymarket_resolutions(
    db_path: Path,
    limit: Optional[int] = None,
    terminal_tolerance: float = DEFAULT_TERMINAL_TOLERANCE,
    dry_run: bool = False,
) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    resolved = []
    unresolved = []
    errors = []

    try:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        ensure_resolution_sync_heartbeat_schema(conn)
        candidates = candidate_markets_for_resolution(conn, limit)

        for market in candidates:
            market_id = int(market["id"])
            external_market_id = str(market["external_market_id"])
            checked_at = datetime.now(timezone.utc).isoformat()
            try:
                source_payload = fetch_polymarket_market(external_market_id)
                inference = infer_binary_resolution(
                    source_payload,
                    terminal_tolerance=terminal_tolerance,
                )

                if inference["resolved"]:
                    result = {
                        "market_id": market_id,
                        "external_market_id": external_market_id,
                        "outcome": inference["outcome"],
                        "resolved_at": inference["resolved_at"],
                        "method": inference["method"],
                        "dry_run": dry_run,
                    }
                    if not dry_run:
                        result.update(
                            settle_market_outcome(
                                db_path=db_path,
                                market_id=market_id,
                                outcome=inference["outcome"],
                                resolved_at=inference["resolved_at"],
                                resolution_source="polymarket_gamma",
                                resolution_payload=source_payload,
                                resolution_method=inference["method"],
                                resolution_checked_at=checked_at,
                            )
                        )
                    resolved.append(result)
                    continue

                method = f"unresolved:{inference['reason']}"
                if not dry_run:
                    with conn:
                        mark_resolution_checked(
                            conn,
                            market_id,
                            source_payload,
                            method,
                            checked_at,
                        )
                unresolved.append(
                    {
                        "market_id": market_id,
                        "external_market_id": external_market_id,
                        "reason": inference["reason"],
                        "dry_run": dry_run,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "market_id": market_id,
                        "external_market_id": external_market_id,
                        "error": str(exc),
                    }
                )

        if not dry_run:
            checked_at = datetime.now(timezone.utc).isoformat()
            metadata = {
                "schema_version": "polymarket-resolution-sync-heartbeat/v1",
                "limit": limit,
                "terminal_tolerance": terminal_tolerance,
            }
            with conn:
                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {RESOLUTION_SYNC_HEARTBEAT_TABLE} (
                      heartbeat_id, checked_at, candidate_count, resolved_count,
                      unresolved_count, error_count, dry_run, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "polymarket-resolution-sync-current",
                        checked_at,
                        len(candidates),
                        len(resolved),
                        len(unresolved),
                        len(errors),
                        0,
                        to_json_text(metadata),
                    ),
                )

        return {
            "candidates": len(candidates),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "errors": len(errors),
            "resolved_markets": resolved,
            "unresolved_markets": unresolved,
            "error_markets": errors,
        }
    finally:
        conn.close()
