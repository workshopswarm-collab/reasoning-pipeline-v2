PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calibration_candidate_records (
  candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  owner_session TEXT NOT NULL,
  candidate_status TEXT NOT NULL,
  baseline_policy_sha256 TEXT,
  candidate_policy_sha256 TEXT,
  changed_parameters TEXT NOT NULL DEFAULT '[]',
  source_replay_cohort_ids TEXT NOT NULL DEFAULT '[]',
  source_scorecard_refs TEXT NOT NULL DEFAULT '[]',
  source_trace_materialization_refs TEXT NOT NULL DEFAULT '[]',
  component_diagnostics_ref TEXT,
  bounds_check_status TEXT NOT NULL,
  protected_slice_non_degradation_status TEXT NOT NULL,
  holdout_status TEXT NOT NULL,
  canary_status TEXT NOT NULL,
  promotion_status TEXT NOT NULL,
  promotion_decision TEXT NOT NULL,
  canary_bucket TEXT NOT NULL,
  rollback_pointer_ref TEXT,
  rollback_status TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_calibration_candidate_records_lane
  ON calibration_candidate_records(lane_id, created_at);

CREATE TABLE IF NOT EXISTS calibration_component_diagnostic_records (
  diagnostic_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  replay_cohort_id TEXT NOT NULL,
  headline_status TEXT NOT NULL,
  protected_slice_non_degradation_status TEXT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  protected_slice_diagnostics TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_calibration_component_diagnostics_candidate
  ON calibration_component_diagnostic_records(candidate_id, lane_id);

CREATE TABLE IF NOT EXISTS calibration_lane_health_records (
  health_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  health_status TEXT NOT NULL,
  active_pointer_id TEXT,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_calibration_lane_health_lane
  ON calibration_lane_health_records(lane_id, created_at);

CREATE TABLE IF NOT EXISTS calibration_canary_state_records (
  canary_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  canary_status TEXT NOT NULL,
  canary_bucket TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_calibration_canary_state_candidate
  ON calibration_canary_state_records(candidate_id, canary_status);

CREATE TABLE IF NOT EXISTS calibration_lane_pointer_records (
  pointer_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  pointer_status TEXT NOT NULL,
  active_policy_snapshot_ref TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  rollback_pointer_ref TEXT,
  canary_status TEXT NOT NULL,
  promoted_at TEXT NOT NULL,
  promoted_by TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_calibration_lane_pointers_lane
  ON calibration_lane_pointer_records(lane_id, pointer_status);

CREATE TABLE IF NOT EXISTS policy_rollback_events (
  rollback_event_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  pointer_id TEXT,
  rollback_pointer_ref TEXT,
  reason TEXT NOT NULL,
  actor TEXT NOT NULL,
  health_evidence_refs TEXT NOT NULL DEFAULT '[]',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_policy_rollback_events_lane
  ON policy_rollback_events(lane_id, created_at);

CREATE TABLE IF NOT EXISTS retrieval_policy_snapshot_records (
  snapshot_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  replay_feature_summary TEXT NOT NULL DEFAULT '{}',
  protected_primary_diagnostics TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decomposer_profile_candidate_records (
  profile_candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  qdt_shape_summary TEXT NOT NULL DEFAULT '{}',
  decomposer_miss_labels TEXT NOT NULL DEFAULT '[]',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decision_actionability_candidate_records (
  actionability_candidate_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  route_diagnostics TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS emergency_conservative_overlay_records (
  overlay_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  lane_id TEXT NOT NULL,
  trigger_kind TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  effects TEXT NOT NULL DEFAULT '[]',
  expires_at TEXT NOT NULL,
  rollback_semantics TEXT NOT NULL,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS optimization_maturity_results (
  maturity_result_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  status TEXT NOT NULL,
  checks_json TEXT NOT NULL DEFAULT '{}',
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}'
);
