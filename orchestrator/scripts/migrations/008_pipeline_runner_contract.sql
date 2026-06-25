PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ads_pipeline_control_state (
  control_state_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  pipeline_enabled INTEGER NOT NULL DEFAULT 0,
  desired_runner_mode TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  default_disable_action TEXT NOT NULL,
  acknowledged_by_run_id TEXT,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_control_enabled
  ON ads_pipeline_control_state(pipeline_enabled, desired_runner_mode);

CREATE TABLE IF NOT EXISTS ads_pipeline_runs (
  pipeline_run_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  runner_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  stage_order TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  stopped_at TEXT,
  stop_policy TEXT NOT NULL,
  max_cases INTEGER,
  idle_policy TEXT NOT NULL DEFAULT '{}',
  dependency_gate_mode TEXT NOT NULL,
  active_case_lease_id TEXT,
  last_iteration_id TEXT,
  no_live_autostart INTEGER NOT NULL DEFAULT 1,
  downstream_execution_enabled INTEGER NOT NULL DEFAULT 0,
  forecast_persistence_enabled INTEGER NOT NULL DEFAULT 0,
  terminal_reason TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_runs_status
  ON ads_pipeline_runs(status, runner_mode, started_at);

CREATE INDEX IF NOT EXISTS idx_ads_pipeline_runs_gate_mode
  ON ads_pipeline_runs(dependency_gate_mode, runner_mode);

CREATE TABLE IF NOT EXISTS ads_case_leases (
  case_lease_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  pipeline_run_id TEXT NOT NULL,
  market_id INTEGER NOT NULL,
  case_key TEXT NOT NULL,
  case_id TEXT NOT NULL,
  lease_status TEXT NOT NULL,
  lease_owner TEXT NOT NULL,
  lease_acquired_at TEXT NOT NULL,
  lease_expires_at TEXT NOT NULL,
  lease_released_at TEXT,
  dispatch_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  selected_snapshot_id INTEGER NOT NULL,
  selected_snapshot_observed_at TEXT NOT NULL,
  selection_policy_ref TEXT NOT NULL,
  release_reason TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ads_case_leases_active_case
  ON ads_case_leases(market_id, case_key)
  WHERE lease_status = 'leased';

CREATE INDEX IF NOT EXISTS idx_ads_case_leases_status
  ON ads_case_leases(lease_status, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_ads_case_leases_snapshot
  ON ads_case_leases(market_id, selected_snapshot_id);
