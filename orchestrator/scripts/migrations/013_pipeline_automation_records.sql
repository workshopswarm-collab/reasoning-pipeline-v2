PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ads_pipeline_loop_iterations (
  loop_iteration_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  pipeline_run_id TEXT NOT NULL,
  iteration_number INTEGER NOT NULL,
  case_lease_id TEXT,
  case_id TEXT,
  case_key TEXT,
  dispatch_id TEXT,
  selected_case_key TEXT,
  stage_order TEXT NOT NULL DEFAULT '[]',
  terminal_status TEXT NOT NULL,
  completed_stage_count INTEGER NOT NULL DEFAULT 0,
  forecast_decision_record_id TEXT,
  forecast_artifact_id TEXT,
  market_prediction_id TEXT,
  error_event_refs TEXT NOT NULL DEFAULT '[]',
  retry_summary TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  completed_at TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ads_pipeline_loop_run_iteration
  ON ads_pipeline_loop_iterations(pipeline_run_id, iteration_number);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_loop_terminal
  ON ads_pipeline_loop_iterations(terminal_status, completed_at);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_loop_case
  ON ads_pipeline_loop_iterations(case_lease_id, case_key);

CREATE TABLE IF NOT EXISTS ads_pipeline_stop_signals (
  stop_signal_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  pipeline_run_id TEXT,
  stop_policy TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  source TEXT NOT NULL,
  signal_status TEXT NOT NULL,
  acknowledged_by_run_id TEXT,
  acknowledged_at TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_stop_status
  ON ads_pipeline_stop_signals(signal_status, requested_at);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_stop_run
  ON ads_pipeline_stop_signals(pipeline_run_id, stop_policy);
