"""Conservative SQLite storage maintenance for ADS operational tables."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_RETENTION_TABLES = {
    "v2_stage_execution_events": "created_at",
    "v2_stage_status_snapshots": "created_at",
    "v2_pipeline_error_events": "created_at",
    "ads_pipeline_loop_iterations": "created_at",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})").fetchall())


def _database_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def build_storage_maintenance_plan(
    db_path: Path | str,
    *,
    retention_days: int = 90,
    tables: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    active_tables = tables or DEFAULT_RETENTION_TABLES
    conn = sqlite3.connect(path)
    try:
        candidates: list[dict[str, Any]] = []
        for table, timestamp_column in active_tables.items():
            if not _column_exists(conn, table, timestamp_column):
                candidates.append(
                    {
                        "table": table,
                        "timestamp_column": timestamp_column,
                        "exists": False,
                        "candidate_rows": 0,
                    }
                )
                continue
            count = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE {timestamp_column} < datetime('now', ?)
                    """,
                    (f"-{retention_days} days",),
                ).fetchone()[0]
            )
            candidates.append(
                {
                    "table": table,
                    "timestamp_column": timestamp_column,
                    "exists": True,
                    "candidate_rows": count,
                }
            )
        wal_path = path.with_name(path.name + "-wal")
        shm_path = path.with_name(path.name + "-shm")
        return {
            "schema_version": "ads-storage-maintenance-plan/v1",
            "db_path": str(path),
            "retention_days": retention_days,
            "db_size_bytes": _database_size(path),
            "wal_size_bytes": _database_size(wal_path),
            "shm_size_bytes": _database_size(shm_path),
            "retention_candidates": candidates,
            "apply_required": True,
        }
    finally:
        conn.close()


def apply_storage_maintenance(
    db_path: Path | str,
    *,
    retention_days: int = 90,
    vacuum: bool = False,
    tables: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    before = build_storage_maintenance_plan(path, retention_days=retention_days, tables=tables)
    active_tables = tables or DEFAULT_RETENTION_TABLES
    deleted: dict[str, int] = {}
    conn = sqlite3.connect(path)
    try:
        with conn:
            for table, timestamp_column in active_tables.items():
                if not _column_exists(conn, table, timestamp_column):
                    continue
                cursor = conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE {timestamp_column} < datetime('now', ?)
                    """,
                    (f"-{retention_days} days",),
                )
                deleted[table] = int(cursor.rowcount if cursor.rowcount is not None else 0)
    finally:
        conn.close()
    checkpoint_conn = sqlite3.connect(path)
    try:
        checkpoint = checkpoint_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        checkpoint_conn.close()
    if vacuum:
        vacuum_conn = sqlite3.connect(path)
        try:
            vacuum_conn.execute("VACUUM")
            checkpoint_after_vacuum = vacuum_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        finally:
            vacuum_conn.close()
    else:
        checkpoint_after_vacuum = []
    after = build_storage_maintenance_plan(path, retention_days=retention_days, tables=tables)
    return {
        "schema_version": "ads-storage-maintenance-result/v1",
        "db_path": str(path),
        "retention_days": retention_days,
        "deleted_rows": deleted,
        "vacuum_ran": vacuum,
        "wal_checkpoint": checkpoint,
        "wal_checkpoint_after_vacuum": checkpoint_after_vacuum,
        "before": before,
        "after": after,
    }


__all__ = ["DEFAULT_RETENTION_TABLES", "apply_storage_maintenance", "build_storage_maintenance_plan"]
