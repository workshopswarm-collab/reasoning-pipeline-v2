from pathlib import Path
import sqlite3


FOUNDATION_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "001_foundation_persistence_and_artifacts.sql"
)


def foundation_schema_sql() -> str:
    return FOUNDATION_MIGRATION.read_text(encoding="utf-8")


def ensure_foundation_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(foundation_schema_sql())
    from predquant.ads_handoff import ensure_artifact_manifest_schema

    ensure_artifact_manifest_schema(conn)
