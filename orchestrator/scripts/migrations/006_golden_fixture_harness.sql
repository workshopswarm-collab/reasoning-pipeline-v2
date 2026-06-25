PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS golden_fixture_case_registry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fixture_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_key TEXT NOT NULL UNIQUE,
  title TEXT,
  stage_gate TEXT NOT NULL,
  owner_sessions TEXT NOT NULL DEFAULT '[]',
  scenario TEXT NOT NULL,
  required_assertions TEXT NOT NULL,
  matrix_status TEXT NOT NULL,
  target_feature_ids TEXT NOT NULL DEFAULT '[]',
  blocker_ids TEXT NOT NULL DEFAULT '[]',
  expected_outcome TEXT NOT NULL,
  expected_stages TEXT NOT NULL DEFAULT '[]',
  starter_implemented INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_golden_fixture_registry_stage_gate
  ON golden_fixture_case_registry(stage_gate, matrix_status);

CREATE TABLE IF NOT EXISTS golden_fixture_case_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fixture_result_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  fixture_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  stage_records TEXT NOT NULL DEFAULT '[]',
  artifact_manifest_ids TEXT NOT NULL DEFAULT '[]',
  validation_result_ids TEXT NOT NULL DEFAULT '[]',
  error_event_ids TEXT NOT NULL DEFAULT '[]',
  missing_artifacts TEXT NOT NULL DEFAULT '[]',
  failure_class TEXT,
  report_artifact_id TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (fixture_id) REFERENCES golden_fixture_case_registry(fixture_id)
);

CREATE INDEX IF NOT EXISTS idx_golden_fixture_results_fixture_status
  ON golden_fixture_case_results(fixture_id, status);

CREATE INDEX IF NOT EXISTS idx_golden_fixture_results_run
  ON golden_fixture_case_results(run_id);
