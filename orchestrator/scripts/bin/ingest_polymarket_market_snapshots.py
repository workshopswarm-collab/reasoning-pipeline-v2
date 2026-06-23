#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUNDLE_ROOT))

from predquant.pipeline import push_filtered_markets
from predquant.polymarket_intake import OUTPUT_FILE, fetch_and_filter_all_markets
from predquant.polymarket_resolution import sync_polymarket_resolutions
from predquant.sqlite_store import cleanup_expired_markets, initialize_database


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    return Path(os.getenv("PREDQUANT_SQLITE_PATH", BUNDLE_ROOT / "data" / "predquant.sqlite3"))


def default_output_file() -> Path:
    return BUNDLE_ROOT / ".runtime-state" / OUTPUT_FILE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch filtered Polymarket markets into SQLite and run market controls."
    )
    parser.add_argument("--db-path", default=str(default_db_path()))
    parser.add_argument("--output", default=str(default_output_file()))
    parser.add_argument("--lock-file")
    parser.add_argument("--report-file")
    parser.add_argument("--grace-minutes", type=int, default=0)
    parser.add_argument("--resolution-limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--control-managed", action="store_true")
    parser.add_argument("--control-file")
    parser.add_argument("--env-file")
    parser.add_argument("--psql")
    parser.add_argument("--gamma-page-limit")
    parser.add_argument("--clob-batch-size")
    return parser.parse_args()


def write_json(path: Optional[Path], payload: dict, pretty: bool = False) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2 if pretty else None, sort_keys=pretty)
    path.write_text(text + "\n", encoding="utf-8")


def read_control_state(args: argparse.Namespace) -> dict:
    if not args.control_managed or not args.control_file:
        return {"enabled": True}
    path = Path(args.control_file)
    if not path.exists():
        return {"enabled": True, "missing": True}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"enabled": False, "error": f"invalid control JSON: {exc}"}
    enabled = not (
        payload.get("disabled")
        or payload.get("paused")
        or payload.get("enabled") is False
    )
    return {"enabled": enabled, "payload": payload}


class LockFile:
    def __init__(self, path: Optional[str]):
        self.path = Path(path) if path else None
        self.acquired = False

    def __enter__(self):
        if self.path is None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return self
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": utc_now()}) + "\n")
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.acquired and self.path:
            self.path.unlink(missing_ok=True)


def run_cycle(args: argparse.Namespace) -> dict:
    started_at = utc_now()
    db_path = Path(args.db_path)
    output_path = Path(args.output)
    dry_run = args.dry_run or not args.apply

    control_state = read_control_state(args)
    if not control_state["enabled"]:
        return {
            "runner": "ingest_polymarket_market_snapshots",
            "ok": True,
            "skipped": True,
            "reason": "control_disabled",
            "control": control_state,
            "started_at": started_at,
            "updated_at": utc_now(),
        }

    initialize_database(db_path)
    before_cleanup = cleanup_expired_markets(
        db_path=db_path,
        grace_minutes=args.grace_minutes,
        dry_run=dry_run,
    )
    before_resolutions = sync_polymarket_resolutions(
        db_path=db_path,
        limit=args.resolution_limit,
        dry_run=dry_run,
    )

    fetch_and_filter_all_markets(output_file=output_path)
    push_result = {"loaded": 0, "success": 0, "errors": 0, "messages": []}
    if not dry_run:
        push_result = push_filtered_markets(output_path, db_path)

    after_cleanup = cleanup_expired_markets(
        db_path=db_path,
        grace_minutes=args.grace_minutes,
        dry_run=dry_run,
    )
    after_resolutions = sync_polymarket_resolutions(
        db_path=db_path,
        limit=args.resolution_limit,
        dry_run=dry_run,
    )

    return {
        "runner": "ingest_polymarket_market_snapshots",
        "schema_version": "polymarket-snapshot-ingester/v1",
        "ok": push_result["errors"] == 0,
        "dry_run": dry_run,
        "db_path": str(db_path),
        "output_file": str(output_path),
        "started_at": started_at,
        "updated_at": utc_now(),
        "before_cleanup": before_cleanup,
        "before_resolutions": before_resolutions,
        "push": push_result,
        "after_cleanup": after_cleanup,
        "after_resolutions": after_resolutions,
    }


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_file) if args.report_file else None
    with LockFile(args.lock_file) as lock:
        if args.lock_file and not lock.acquired:
            report = {
                "runner": "ingest_polymarket_market_snapshots",
                "ok": True,
                "skipped": True,
                "reason": "lock_held",
                "lock_file": args.lock_file,
                "updated_at": utc_now(),
            }
            write_json(report_path, report, args.pretty)
            print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
            return 0

        try:
            report = run_cycle(args)
        except Exception as exc:
            report = {
                "runner": "ingest_polymarket_market_snapshots",
                "ok": False,
                "error": str(exc),
                "updated_at": utc_now(),
            }
            write_json(report_path, report, args.pretty)
            print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty), file=sys.stderr)
            return 1

    write_json(report_path, report, args.pretty)
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
