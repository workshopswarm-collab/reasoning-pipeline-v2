PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scae_ledger_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scae_ledger_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT,
  dispatch_id TEXT NOT NULL,
  run_id TEXT,
  forecast_timestamp TEXT,
  policy_snapshot_id TEXT,
  raw_ledger_probability REAL NOT NULL,
  post_ledger_probability REAL NOT NULL,
  debt_adjusted_probability REAL,
  production_forecast_prob REAL,
  canonical_probability REAL,
  forecast_validity_status TEXT NOT NULL,
  execution_authority_status TEXT NOT NULL,
  final_probability_fields_status TEXT NOT NULL,
  production_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  writes_persistence INTEGER NOT NULL DEFAULT 0,
  prior_context_id TEXT,
  prior_context_json TEXT NOT NULL DEFAULT '{}',
  market_prior_assimilation_context_json TEXT NOT NULL DEFAULT '{}',
  research_sufficiency_context_id TEXT,
  research_sufficiency_context_json TEXT NOT NULL DEFAULT '{}',
  calibration_context_json TEXT NOT NULL DEFAULT '{}',
  calibration_debt_context_json TEXT NOT NULL DEFAULT '{}',
  interval_json TEXT NOT NULL DEFAULT '{}',
  cap_stack_json TEXT NOT NULL DEFAULT '{}',
  accepted_delta_input_refs TEXT NOT NULL DEFAULT '[]',
  artifact_payload_json TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_ledger_outputs_case
  ON scae_ledger_outputs(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_scae_ledger_outputs_validity
  ON scae_ledger_outputs(forecast_validity_status, execution_authority_status);

CREATE TABLE IF NOT EXISTS scae_log_odds_update_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_log_odds_update_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 0,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_log_odds_case
  ON scae_log_odds_update_slices(case_id, dispatch_id, leaf_id);
CREATE INDEX IF NOT EXISTS idx_scae_log_odds_claim_family
  ON scae_log_odds_update_slices(claim_family_id, source_family_id);

CREATE TABLE IF NOT EXISTS scae_cross_leaf_dependency_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_cross_leaf_dependency_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 0,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_cross_leaf_case
  ON scae_cross_leaf_dependency_slices(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_scae_cross_leaf_group
  ON scae_cross_leaf_dependency_slices(dependency_group_id);

CREATE TABLE IF NOT EXISTS scae_branch_subledger_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_branch_subledger_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 0,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_branch_case
  ON scae_branch_subledger_slices(case_id, dispatch_id, parent_branch_id);

CREATE TABLE IF NOT EXISTS scae_conditional_branch_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_conditional_branch_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 0,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_conditional_case
  ON scae_conditional_branch_slices(case_id, dispatch_id, condition_scope);

CREATE TABLE IF NOT EXISTS scae_calibration_diagnostic_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_calibration_diagnostic_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 1,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_calibration_case
  ON scae_calibration_diagnostic_slices(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS scae_mechanism_family_assignment_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_mechanism_family_assignment_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 1,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_mechanism_case
  ON scae_mechanism_family_assignment_slices(case_id, dispatch_id);
CREATE INDEX IF NOT EXISTS idx_scae_mechanism_family
  ON scae_mechanism_family_assignment_slices(mechanism_family_id);

CREATE TABLE IF NOT EXISTS scae_research_sufficiency_input_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'scae_research_sufficiency_input_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 1,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scae_research_input_case
  ON scae_research_sufficiency_input_slices(case_id, dispatch_id);

CREATE TABLE IF NOT EXISTS missingness_signal_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'missingness_signal_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 1,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_missingness_signal_case
  ON missingness_signal_slices(case_id, dispatch_id, leaf_id);

CREATE TABLE IF NOT EXISTS research_sufficiency_reconciliation_slices (
  slice_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  artifact_type TEXT,
  case_id TEXT,
  dispatch_id TEXT,
  leaf_id TEXT,
  parent_branch_id TEXT,
  condition_scope TEXT,
  feature_id TEXT,
  surface_name TEXT NOT NULL DEFAULT 'research_sufficiency_reconciliation_slices',
  source_ref TEXT,
  source_family_id TEXT,
  claim_family_id TEXT,
  mechanism_family_id TEXT,
  dependency_group_id TEXT,
  signed_log_odds_delta REAL,
  accepted_for_ledger_input INTEGER NOT NULL DEFAULT 0,
  diagnostic_only INTEGER NOT NULL DEFAULT 1,
  can_increase_evidence_strength INTEGER NOT NULL DEFAULT 0,
  live_forecast_authority INTEGER NOT NULL DEFAULT 0,
  writes_scae_ledger INTEGER NOT NULL DEFAULT 0,
  writes_production_forecast INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  source_refs TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_reconciliation_case
  ON research_sufficiency_reconciliation_slices(case_id, dispatch_id, leaf_id);
