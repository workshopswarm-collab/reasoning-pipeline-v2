#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUNDLE_ROOT))

from predquant.sqlite_store import ensure_schema, initialize_database, parse_market_time


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    return Path(os.getenv("PREDQUANT_SQLITE_PATH", BUNDLE_ROOT / "data" / "predquant.sqlite3"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report SQLite market pipeline health.")
    parser.add_argument("--db-path", default=str(default_db_path()))
    parser.add_argument("--report-file")
    parser.add_argument("--heartbeat-file")
    parser.add_argument("--quarantine-file")
    parser.add_argument("--max-market-snapshot-age-seconds", type=float, default=3600.0)
    parser.add_argument("--max-brier-age-seconds", type=float, default=172800.0)
    parser.add_argument("--max-heartbeat-age-seconds", type=float, default=1800.0)
    parser.add_argument("--max-resolution-sync-age-seconds", type=float, default=5400.0)
    parser.add_argument("--max-decided-market-watcher-age-seconds", type=float)
    parser.add_argument("--max-quarantine-count", type=int)
    parser.add_argument("--min-market-snapshot-fresh-coverage", type=float)
    parser.add_argument("--control-managed", action="store_true")
    parser.add_argument("--control-file")
    parser.add_argument("--artifact-contract-root")
    parser.add_argument("--artifact-contract-report-file")
    parser.add_argument("--decided-market-watcher-heartbeat-file")
    parser.add_argument("--market-checker-env-file")
    parser.add_argument("--market-checker-psql")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def write_json(path: Optional[str], payload: dict, pretty: bool = False) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2 if pretty else None, sort_keys=pretty) + "\n",
        encoding="utf-8",
    )


def scalar(conn: sqlite3.Connection, sql: str, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def age_seconds(timestamp: Optional[str]) -> Optional[float]:
    parsed = parse_market_time(timestamp)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def build_report(db_path: Path, args: argparse.Namespace) -> dict:
    initialize_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema(conn)
        counts = {
            "markets": scalar(conn, "SELECT COUNT(*) FROM markets") or 0,
            "open_markets": scalar(conn, "SELECT COUNT(*) FROM markets WHERE status = 'open'") or 0,
            "closed_markets": scalar(conn, "SELECT COUNT(*) FROM markets WHERE status = 'closed'") or 0,
            "resolved_markets": scalar(conn, "SELECT COUNT(*) FROM markets WHERE status = 'resolved'") or 0,
            "snapshots": scalar(conn, "SELECT COUNT(*) FROM market_snapshots") or 0,
            "predictions": scalar(conn, "SELECT COUNT(*) FROM market_predictions") or 0,
            "scored_predictions": scalar(
                conn,
                "SELECT COUNT(*) FROM market_predictions WHERE prediction_brier IS NOT NULL",
            )
            or 0,
            "unscored_resolved_predictions": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM market_predictions
                WHERE outcome IS NOT NULL AND prediction_brier IS NULL
                """,
            )
            or 0,
        }
        latest_snapshot_at = scalar(conn, "SELECT MAX(observed_at) FROM market_snapshots")
        latest_scored_at = scalar(
            conn,
            "SELECT MAX(updated_at) FROM market_predictions WHERE prediction_brier IS NOT NULL",
        )
        latest_resolution_checked_at = scalar(
            conn,
            "SELECT MAX(resolution_checked_at) FROM markets WHERE resolution_checked_at IS NOT NULL",
        )
        snapshot_age = age_seconds(latest_snapshot_at)
        brier_age = age_seconds(latest_scored_at)
        resolution_age = age_seconds(latest_resolution_checked_at)
        issues = []
        if counts["markets"] == 0:
            issues.append("no_markets_loaded")
        if snapshot_age is not None and snapshot_age > args.max_market_snapshot_age_seconds:
            issues.append("market_snapshots_stale")
        if counts["unscored_resolved_predictions"]:
            issues.append("resolved_predictions_missing_brier")
        if brier_age is not None and brier_age > args.max_brier_age_seconds:
            issues.append("brier_scores_stale")
        if resolution_age is not None and resolution_age > args.max_resolution_sync_age_seconds:
            issues.append("resolution_sync_stale")

        return {
            "runner": "check_pipeline_health",
            "schema_version": "sqlite-market-health/v1",
            "ok": not issues,
            "status": "ok" if not issues else "warning",
            "issues": issues,
            "db_path": str(db_path),
            "counts": counts,
            "latest_snapshot_at": latest_snapshot_at,
            "latest_snapshot_age_seconds": snapshot_age,
            "latest_scored_prediction_at": latest_scored_at,
            "latest_brier_age_seconds": brier_age,
            "latest_resolution_checked_at": latest_resolution_checked_at,
            "latest_resolution_age_seconds": resolution_age,
            "updated_at": utc_now(),
        }
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    try:
        report = build_report(db_path, args)
    except Exception as exc:
        report = {
            "runner": "check_pipeline_health",
            "schema_version": "sqlite-market-health/v1",
            "ok": False,
            "status": "error",
            "error": str(exc),
            "db_path": str(db_path),
            "updated_at": utc_now(),
        }
    write_json(args.report_file, report, args.pretty)
    write_json(args.heartbeat_file, report, args.pretty)
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
