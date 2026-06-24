PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS case_artifact_manifest (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_schema_version TEXT NOT NULL,
  case_id TEXT NOT NULL,
  case_key TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  stage_attempt_id TEXT,
  pipeline_run_id TEXT,
  producer TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  source_cutoff_timestamp TEXT NOT NULL,
  input_manifest_ids TEXT NOT NULL DEFAULT '[]',
  validation_status TEXT NOT NULL,
  validation_result_refs TEXT NOT NULL DEFAULT '[]',
  validator_version TEXT,
  temporal_isolation_status TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_case_dispatch
  ON case_artifact_manifest(case_id, dispatch_id, stage);

CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_type_schema
  ON case_artifact_manifest(artifact_type, artifact_schema_version);

CREATE INDEX IF NOT EXISTS idx_case_artifact_manifest_digest
  ON case_artifact_manifest(artifact_sha256);

CREATE TABLE IF NOT EXISTS artifact_validation_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  validation_result_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  status TEXT NOT NULL,
  validator_version TEXT NOT NULL,
  validated_at TEXT NOT NULL,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  validation_messages TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (artifact_id) REFERENCES case_artifact_manifest(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_validation_results_artifact
  ON artifact_validation_results(artifact_id, status);
