PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS v2_replay_manifests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  replay_manifest_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  replay_cohort_id TEXT NOT NULL,
  cohort_sequence INTEGER NOT NULL,
  cohort_limit INTEGER NOT NULL,
  replay_scope TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  trace_artifact_manifest_ids TEXT NOT NULL DEFAULT '[]',
  trace_artifact_hashes TEXT NOT NULL DEFAULT '{}',
  replay_status TEXT NOT NULL,
  replay_command TEXT,
  live_authority TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  production_write_authority INTEGER NOT NULL DEFAULT 0,
  calibration_policy_promotion_authority INTEGER NOT NULL DEFAULT 0,
  full_trace_materialization_authority INTEGER NOT NULL DEFAULT 0,
  allowed_uses TEXT NOT NULL DEFAULT '[]',
  forbidden_uses TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_v2_replay_manifests_cohort
  ON v2_replay_manifests(replay_cohort_id, cohort_sequence);

CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_replay_manifests_replay_manifest_id
  ON v2_replay_manifests(replay_manifest_id);

CREATE INDEX IF NOT EXISTS idx_v2_replay_manifests_trace
  ON v2_replay_manifests(trace_id);

CREATE INDEX IF NOT EXISTS idx_v2_replay_manifests_case_dispatch
  ON v2_replay_manifests(case_id, dispatch_id, run_id);

CREATE TABLE IF NOT EXISTS v2_replay_result_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  replay_result_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  replay_manifest_id TEXT NOT NULL,
  replay_cohort_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  replay_attempt_id TEXT NOT NULL,
  result_status TEXT NOT NULL,
  replay_started_at TEXT,
  replay_completed_at TEXT,
  replay_output_artifact_ref TEXT,
  replay_output_hash TEXT,
  outcome_ref TEXT,
  scoring_record_ref TEXT,
  scorecard_artifact_ref TEXT,
  safe_message TEXT,
  live_authority TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  production_write_authority INTEGER NOT NULL DEFAULT 0,
  probability_replacement_authority INTEGER NOT NULL DEFAULT 0,
  calibration_policy_promotion_authority INTEGER NOT NULL DEFAULT 0,
  allowed_uses TEXT NOT NULL DEFAULT '[]',
  forbidden_uses TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (replay_manifest_id) REFERENCES v2_replay_manifests(replay_manifest_id)
);

CREATE INDEX IF NOT EXISTS idx_v2_replay_results_manifest
  ON v2_replay_result_records(replay_manifest_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_replay_results_replay_result_id
  ON v2_replay_result_records(replay_result_id);

CREATE INDEX IF NOT EXISTS idx_v2_replay_results_cohort_status
  ON v2_replay_result_records(replay_cohort_id, result_status);
