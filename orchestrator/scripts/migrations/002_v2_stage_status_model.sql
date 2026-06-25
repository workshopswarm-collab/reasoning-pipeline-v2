PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS v2_stage_status_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  stage_attempt_id TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  duration_ms INTEGER,
  input_artifacts TEXT NOT NULL DEFAULT '[]',
  output_artifacts TEXT NOT NULL DEFAULT '[]',
  dependency_feature_ids TEXT NOT NULL DEFAULT '[]',
  blocking_feature_ids TEXT NOT NULL DEFAULT '[]',
  reason_codes TEXT NOT NULL DEFAULT '[]',
  latest_execution_event_ids TEXT NOT NULL DEFAULT '[]',
  error_event_ids TEXT NOT NULL DEFAULT '[]',
  replay_command TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_v2_stage_status_case_dispatch
  ON v2_stage_status_snapshots(case_id, dispatch_id, stage);

CREATE INDEX IF NOT EXISTS idx_v2_stage_status_attempt
  ON v2_stage_status_snapshots(stage_attempt_id);

CREATE TABLE IF NOT EXISTS v2_stage_execution_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_event_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  pipeline_run_id TEXT,
  case_lease_id TEXT,
  case_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  stage_attempt_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_status TEXT NOT NULL,
  event_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  duration_ms INTEGER,
  attempt_number INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL,
  runner_ref TEXT NOT NULL,
  agent_or_component_ref TEXT NOT NULL,
  script_path TEXT NOT NULL,
  command_sha256 TEXT NOT NULL,
  input_artifact_refs TEXT NOT NULL DEFAULT '[]',
  output_artifact_refs TEXT NOT NULL DEFAULT '[]',
  validation_result_refs TEXT NOT NULL DEFAULT '[]',
  error_event_id TEXT,
  failure_class TEXT,
  safe_exception_class TEXT,
  safe_exception_message TEXT,
  traceback_sha256 TEXT,
  stdout_artifact_ref TEXT,
  stderr_artifact_ref TEXT,
  bounded_log_artifact_ref TEXT,
  no_log_reason TEXT,
  redaction_status TEXT NOT NULL,
  resource_counters TEXT NOT NULL DEFAULT '{}',
  retry_policy_ref TEXT,
  next_retry_at TEXT,
  replay_command TEXT NOT NULL,
  safe_metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_v2_stage_exec_case_dispatch
  ON v2_stage_execution_events(case_id, dispatch_id, stage);

CREATE INDEX IF NOT EXISTS idx_v2_stage_exec_attempt
  ON v2_stage_execution_events(stage_attempt_id, event_type);

CREATE TABLE IF NOT EXISTS v2_pipeline_error_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  error_event_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  execution_event_id TEXT NOT NULL,
  pipeline_run_id TEXT,
  case_lease_id TEXT,
  case_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  stage_attempt_id TEXT NOT NULL,
  failure_class TEXT NOT NULL,
  failure_grouping_key TEXT NOT NULL,
  retryability TEXT NOT NULL,
  safe_message TEXT NOT NULL,
  safe_metadata TEXT NOT NULL DEFAULT '{}',
  replay_command TEXT NOT NULL,
  unsafe_secret_exclusion_status TEXT NOT NULL,
  bounded_log_artifact_refs TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_v2_pipeline_error_case_dispatch
  ON v2_pipeline_error_events(case_id, dispatch_id, stage);

CREATE INDEX IF NOT EXISTS idx_v2_pipeline_error_group
  ON v2_pipeline_error_events(failure_grouping_key, failure_class);

CREATE TABLE IF NOT EXISTS v2_failure_pattern_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  failure_grouping_key TEXT NOT NULL UNIQUE,
  failure_class TEXT NOT NULL,
  stage TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  event_count INTEGER NOT NULL DEFAULT 0,
  safe_metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_v2_failure_pattern_stage
  ON v2_failure_pattern_groups(stage, failure_class);
