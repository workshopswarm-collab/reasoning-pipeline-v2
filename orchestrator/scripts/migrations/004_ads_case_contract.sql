PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS case_intake_handoff_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  handoff_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_key TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  market_id INTEGER NOT NULL,
  market_snapshot_id INTEGER,
  forecast_timestamp TEXT NOT NULL,
  source_cutoff_timestamp TEXT,
  snapshot_age_seconds REAL,
  max_snapshot_age_seconds REAL NOT NULL,
  handoff_status TEXT NOT NULL,
  reason_code TEXT,
  adapter_policy TEXT NOT NULL,
  source_table_refs TEXT NOT NULL DEFAULT '{}',
  source_payload_hash TEXT,
  market_probability REAL,
  market_probability_method TEXT,
  artifact_id TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (market_id) REFERENCES markets(id) ON DELETE CASCADE,
  FOREIGN KEY (market_snapshot_id) REFERENCES market_snapshots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_case_intake_handoff_case
  ON case_intake_handoff_records(case_key, dispatch_id, handoff_status);

CREATE TABLE IF NOT EXISTS ads_case_contracts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  case_key TEXT NOT NULL,
  case_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL UNIQUE,
  prediction_run_id TEXT NOT NULL UNIQUE,
  forecast_artifact_id TEXT NOT NULL UNIQUE,
  market_id INTEGER NOT NULL,
  market_snapshot_id INTEGER NOT NULL,
  forecast_timestamp TEXT NOT NULL,
  source_cutoff_timestamp TEXT NOT NULL,
  source_payload_hash TEXT NOT NULL,
  market_probability REAL,
  market_probability_method TEXT,
  artifact_id TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  artifact_sha256 TEXT NOT NULL,
  validation_status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (market_id) REFERENCES markets(id) ON DELETE CASCADE,
  FOREIGN KEY (market_snapshot_id) REFERENCES market_snapshots(id) ON DELETE RESTRICT,
  FOREIGN KEY (artifact_id) REFERENCES case_artifact_manifest(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ads_case_contracts_case
  ON ads_case_contracts(case_key, case_id, dispatch_id);

CREATE INDEX IF NOT EXISTS idx_ads_case_contracts_snapshot
  ON ads_case_contracts(market_id, market_snapshot_id);
