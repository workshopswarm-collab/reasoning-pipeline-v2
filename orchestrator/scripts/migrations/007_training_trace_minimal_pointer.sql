PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS training_trace_minimal_pointers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  artifact_manifest_ids TEXT NOT NULL DEFAULT '[]',
  artifact_hashes TEXT NOT NULL DEFAULT '{}',
  trace_status TEXT NOT NULL,
  live_authority TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  materialization_status TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_trace_minimal_case_dispatch
  ON training_trace_minimal_pointers(case_id, dispatch_id, run_id);

CREATE INDEX IF NOT EXISTS idx_training_trace_minimal_status
  ON training_trace_minimal_pointers(trace_status, materialization_status);
